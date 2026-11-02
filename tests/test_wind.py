from datetime import datetime, timedelta, timezone

import httpx
import pytest

from vigil import db
from vigil.config import Sources, Volcano
from vigil.wind import Level, Wind, WindProfile, WindService, WindUnavailable, compare_drift, main

T = datetime(2026, 10, 17, 15, tzinfo=timezone.utc)
# Open-Meteo's profile over Kilauea's north vent at 2026-10-17 15:00Z (Historical Forecast API):
# hPa, altitude (m), speed (m/s), direction the wind comes from (degrees)
EP55_LEVELS = ((850, 1534, 6.64, 8), (700, 3159, 2.47, 335), (600, 4423, 3.53, 15), (500, 5875, 4.53, 287),
               (400, 7588.89, 12.13, 254), (300, 9690.32, 11.71, 265))


def profile(*levels):
    return WindProfile("kilauea", T, tuple(Level(p, z, Wind(s, d)) for p, z, s, d in levels),
                       "historical_forecast", (19.437609, -155.26785, 1111.0))


EP55 = profile(*EP55_LEVELS)


def test_a_wind_from_the_north_blows_towards_the_south():
    assert Wind(5, 0).toward_deg == 180
    assert Wind(5, 350).toward_deg == 170


def test_the_wind_at_a_level_is_that_levels_wind():
    wind = EP55.at(3159)

    assert wind.speed_ms == pytest.approx(2.47)
    assert wind.from_deg == pytest.approx(335)


def test_between_levels_the_components_are_interpolated_not_the_angles():
    # halfway between 4 m/s from the north and 4 m/s from the east: 2.83 m/s from the north-east
    wind = profile((850, 1000, 4, 0), (700, 3000, 4, 90)).at(2000)

    assert wind.from_deg == pytest.approx(45)
    assert wind.speed_ms == pytest.approx(4 / 2 ** 0.5)


def test_outside_the_levels_the_nearest_levels_wind_holds():
    assert EP55.at(500).from_deg == pytest.approx(8)
    assert EP55.at(15000).from_deg == pytest.approx(265)


def test_the_layer_mean_is_the_height_average_of_the_wind():
    two = profile((850, 1000, 4, 0), (700, 3000, 8, 0))

    assert two.layer_mean(1000, 3000).speed_ms == pytest.approx(6)
    assert two.layer_mean(0, 3000).speed_ms == pytest.approx((1000 * 4 + 2000 * 6) / 3000)  # 4 m/s held below 1 km


def test_opposite_winds_cancel_in_the_layer_mean():
    assert profile((850, 1000, 4, 0), (700, 3000, 4, 180)).layer_mean(1000, 3000).speed_ms == pytest.approx(0, abs=1e-9)


def test_a_layer_without_thickness_is_the_wind_at_its_bottom():
    assert EP55.layer_mean(3159, 3000).from_deg == pytest.approx(335)


def test_on_episode_55_the_layer_under_the_plume_top_blows_towards_the_south_south_east():
    mean = EP55.layer_mean(1080, 6951)

    assert mean.toward_deg == pytest.approx(151.1, abs=0.1)
    assert mean.speed_ms == pytest.approx(3.31, abs=0.01)
    assert EP55.at(6951).toward_deg == pytest.approx(79.8, abs=0.1)  # the top alone points the other way


def test_levels_must_be_listed_lowest_first():
    with pytest.raises(ValueError, match="lowest first"):
        profile((700, 3000, 4, 0), (850, 1500, 4, 0))


def test_a_wind_towards_the_measured_side_is_consistent():
    check = compare_drift(224.4, Wind(3.3, 331.1))  # blows towards 151.1

    assert check.angle_deg == pytest.approx(73.3)
    assert (check.toward_deg, check.consistent) == (pytest.approx(151.1), True)


def test_a_wind_towards_the_other_side_is_not_consistent():
    check = compare_drift(224, Wind(9, 260))  # blows towards 80

    assert check.angle_deg == pytest.approx(144)
    assert check.consistent is False


def test_angles_wrap_around_north():
    assert compare_drift(350, Wind(5, 190)).angle_deg == pytest.approx(20)  # towards 10


def test_a_calm_says_nothing_about_the_drift():
    assert compare_drift(224, Wind(0.4, 45)).consistent is None


NOW = datetime(2026, 10, 28, 18, 0, tzinfo=timezone.utc)
SOURCES = Sources(
    volcanoes={
        "kilauea": Volcano(name="Kilauea", country="United States", official_agency="USGS HVO",
                           official_url="https://www.usgs.gov/volcanoes/kilauea", lat=19.405, lon=-155.29),
        "nowhere": Volcano(name="Nowhere", country="-", official_agency="-", official_url="https://example.org"),
    },
    cameras=[],
)


def open_meteo_day(day="2026-10-17", blank_hours=()):
    """Open-Meteo's hourly answer for one UTC day, every hour with the episode 55 profile."""
    hourly = {"time": [f"{day}T{hour:02d}:00" for hour in range(24)]}
    for pressure, altitude, speed, direction in EP55_LEVELS:
        for name, value in (("wind_speed", speed), ("wind_direction", direction), ("geopotential_height", altitude)):
            hourly[f"{name}_{pressure}hPa"] = [None if hour in blank_hours else value for hour in range(24)]
    return {"latitude": 19.437609, "longitude": -155.26785, "elevation": 1111.0, "utc_offset_seconds": 0,
            "timezone": "GMT", "hourly": hourly}


class OpenMeteo:
    """Answers every request with one body and status; records the requests."""

    def __init__(self, body=None, status=200):
        self.body, self.status, self.requests = body, status, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=self.body if self.body is not None else {"error": True})


def service(conn, api, clock=lambda: NOW):
    return WindService(conn, httpx.Client(transport=httpx.MockTransport(api)), SOURCES, now=clock)


def test_a_past_hour_comes_from_the_historical_forecast_api(conn):
    api = OpenMeteo(open_meteo_day())

    found = service(conn, api).profile("kilauea", datetime(2026, 10, 17, 14, 55, 5, tzinfo=timezone.utc))

    request = api.requests[0]
    assert request.url.host == "historical-forecast-api.open-meteo.com"
    params = request.url.params
    assert (params["start_date"], params["end_date"], params["wind_speed_unit"], params["timezone"]) == (
        "2026-10-17", "2026-10-17", "ms", "GMT")
    assert (params["latitude"], params["longitude"]) == ("19.405", "-155.29")
    assert "geopotential_height_300hPa" in params["hourly"].split(",")
    assert found.valid_at == datetime(2026, 10, 17, 15, tzinfo=timezone.utc)
    assert (found.source, found.grid) == ("historical_forecast", (19.437609, -155.26785, 1111.0))
    assert [level.pressure_hpa for level in found.levels] == [850, 700, 600, 500, 400, 300]
    assert found.layer_mean(1080, 6951).from_deg == pytest.approx(331.1, abs=0.1)


def test_a_profile_bounded_by_a_clock_never_reads_an_hour_after_it(conn):
    when = datetime(2026, 10, 17, 15, 40, tzinfo=timezone.utc)
    winds = service(conn, OpenMeteo(open_meteo_day()))

    assert winds.profile("kilauea", when).valid_at.hour == 16  # the nearest hour
    assert winds.profile("kilauea", when, not_after=when).valid_at.hour == 15
    assert winds.profile("kilauea", when, not_after=datetime(2026, 10, 17, 16, tzinfo=timezone.utc)).valid_at.hour == 16


def test_a_recent_hour_comes_from_the_forecast_api(conn):
    api = OpenMeteo(open_meteo_day("2026-10-28"))

    found = service(conn, api).profile("kilauea", datetime(2026, 10, 28, 17, 40, tzinfo=timezone.utc))

    assert api.requests[0].url.host == "api.open-meteo.com"
    assert (found.source, found.valid_at.hour) == ("forecast", 18)


def test_a_fetched_day_is_cached(conn):
    api = OpenMeteo(open_meteo_day())
    winds = service(conn, api)

    winds.profile("kilauea", datetime(2026, 10, 17, 15, tzinfo=timezone.utc))
    winds.profile("kilauea", datetime(2026, 10, 17, 19, tzinfo=timezone.utc))

    assert len(api.requests) == 1
    assert conn.execute("SELECT COUNT(*) FROM wind_profiles").fetchone()[0] == 24


def test_a_cached_forecast_is_fetched_again_after_an_hour(conn):
    clock = [NOW]
    api = OpenMeteo(open_meteo_day("2026-10-28"))
    winds = service(conn, api, clock=lambda: clock[0])
    when = datetime(2026, 10, 28, 20, tzinfo=timezone.utc)

    winds.profile("kilauea", when)
    clock[0] = NOW + timedelta(minutes=30)
    winds.profile("kilauea", when)
    clock[0] = NOW + timedelta(minutes=90)
    winds.profile("kilauea", when)

    assert len(api.requests) == 2


def test_an_hour_without_levels_is_unavailable(conn):
    api = OpenMeteo(open_meteo_day(blank_hours={15}))

    with pytest.raises(WindUnavailable, match="2026-10-17T15:00:00Z"):
        service(conn, api).profile("kilauea", datetime(2026, 10, 17, 15, tzinfo=timezone.utc))


def test_a_failed_request_is_unavailable(conn):
    with pytest.raises(WindUnavailable, match="Open-Meteo"):
        service(conn, OpenMeteo(status=500)).profile("kilauea", datetime(2026, 10, 17, 15, tzinfo=timezone.utc))


def test_a_malformed_answer_is_unavailable(conn):
    body = open_meteo_day()
    del body["hourly"]["wind_speed_500hPa"]

    with pytest.raises(WindUnavailable, match="Open-Meteo"):
        service(conn, OpenMeteo(body)).profile("kilauea", datetime(2026, 10, 17, 15, tzinfo=timezone.utc))


def test_a_volcano_without_a_position_has_no_wind(conn):
    with pytest.raises(WindUnavailable, match="no position"):
        service(conn, OpenMeteo(open_meteo_day())).profile("nowhere", datetime(2026, 10, 17, 15, tzinfo=timezone.utc))


SOURCES_YAML = """
volcanoes:
  kilauea: {name: Kilauea, country: United States, official_agency: USGS HVO,
            official_url: "https://www.usgs.gov/volcanoes/kilauea", lat: 19.405, lon: -155.29}
cameras: []
"""


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(SOURCES_YAML, encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigil.sqlite"))
    return tmp_path / "data"


def test_cli_prints_the_profile_and_the_drift_check(cli_env, capsys):
    conn = db.connect(cli_env / "vigil.sqlite")
    service(conn, OpenMeteo(open_meteo_day())).profile("kilauea", datetime(2026, 10, 17, 15, tzinfo=timezone.utc))
    conn.close()  # the day is cached, so the CLI makes no request

    main(["--volcano", "kilauea", "--at", "2026-10-17T05:00-10:00", "--altitude", "6951", "--bottom", "1080",
          "--side", "224.4"])

    out = capsys.readouterr().out
    assert "kilauea 2026-10-17T15:00:00Z: Open-Meteo Historical Forecast API" in out
    assert "850 hPa" in out
    assert "mean 1080-6951 m: from 331 deg (towards 151 deg) at 3.3 m/s" in out
    assert "drift side 224 deg: 73 deg from the mean wind: consistent" in out


def test_cli_refuses_an_unknown_volcano(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--volcano", "etna"])

    assert "etna" in capsys.readouterr().err


def test_an_unreadable_answer_value_is_unavailable(conn):
    body = open_meteo_day()
    body["hourly"]["time"][15] = "17 Oct 2026 15h"

    with pytest.raises(WindUnavailable, match="Open-Meteo"):
        service(conn, OpenMeteo(body)).profile("kilauea", datetime(2026, 10, 17, 15, tzinfo=timezone.utc))


def test_an_old_forecast_stands_in_when_open_meteo_fails(conn):
    clock = [NOW]
    api = OpenMeteo(open_meteo_day("2026-10-28"))
    winds = service(conn, api, clock=lambda: clock[0])
    when = datetime(2026, 10, 28, 20, tzinfo=timezone.utc)
    winds.profile("kilauea", when)

    clock[0] = NOW + timedelta(hours=2)
    api.status = 500
    found = winds.profile("kilauea", when)

    assert len(api.requests) == 2
    assert (found.source, found.valid_at) == ("forecast", when)
