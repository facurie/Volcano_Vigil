# Phase 4: Wind and Agent Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a Muse Spark agent that, replayed at 05:00 HST on 2026-10-17, picks KPcam, measures the plume, checks its drift against the forecast wind and leaves a full trace in SQLite.

**Architecture:** `vigia/wind.py` fetches Open-Meteo winds aloft (850–300 hPa) per volcano and hour, caches them in `wind_profiles`, interpolates them as east/north components and compares a measured drift side with the mean wind between the vent and the plume top. `vigia/agent/tools.py` exposes nine strict JSON-schema tools over the stored frames, tracks and measurements, all bounded by the agent's clock (live: now; replay: the simulated time), with arguments validated by Pydantic. `vigia/agent/loop.py` runs the Responses API tool loop through a new `MetaClient.respond`, chains turns with `previous_response_id`, guards turns and a per-run budget (a tagged client), and stores every turn and tool call in `agent_runs` / `agent_steps`.

**Tech stack:** Python 3.12, httpx, OpenAI SDK 2.x against the Meta Model API (`muse-spark-1.3`), Pydantic 2, numpy, SQLite, Open-Meteo (Forecast and Historical Forecast APIs).

---

## Facts this plan relies on (measured while planning, 2026-10-28)

**Open-Meteo** (docs read through Context7 `/websites/open-meteo_en`; endpoints called live):
- Forecast API `https://api.open-meteo.com/v1/forecast`; Historical Forecast API `https://historical-forecast-api.open-meteo.com/v1/forecast`. Both take `latitude`, `longitude`, `hourly=<comma list>`, `wind_speed_unit=ms`, `timezone=GMT`, `start_date`, `end_date` (YYYY-MM-DD). Both served 2026-10-17 and 2026-10-29 when asked on 2026-10-28.
- Pressure-level variables: `wind_speed_{p}hPa`, `wind_direction_{p}hPa` (degrees, where the wind comes from), `geopotential_height_{p}hPa` (m above sea level).
- Answer: `{"latitude": 19.437609, "longitude": -155.26785, "elevation": 1111.0, "utc_offset_seconds": 0, "timezone": "GMT", "hourly_units": {...}, "hourly": {"time": ["2026-10-17T00:00", ...], "wind_speed_850hPa": [...], ...}}`. Times have no zone (GMT). The model cell is 4 km NE of the north vent.
- Profile at 2026-10-17 15:00Z (05:00 HST), Historical Forecast API:

  | hPa | altitude m | speed m/s | from ° |
  |---|---|---|---|
  | 850 | 1534 | 6.64 | 8 |
  | 700 | 3159 | 2.47 | 335 |
  | 600 | 4423 | 3.53 | 15 |
  | 500 | 5875 | 4.53 | 287 |
  | 400 | 7588.89 | 12.13 | 254 |
  | 300 | 9690.32 | 11.71 | 265 |

  Mean wind 1,080–6,951 m (vent to the peak plume top), height-averaged components: from 331.1°, towards 151.1°, 3.307 m/s. Wind at 6,951 m alone: from 259.8°, towards 79.8°, 9.08 m/s.
- **Comparison choice, from the data:** over the 75 KPcam plume frames of episode 55, the layer-mean wind (vent to each frame's plume top) blows to the side the plume was measured on (angle < 90°) in **74 of 75** frames (median angle 39°); the wind at the top alone in only 59 of 75, and it fails at the peak (145°). So the drift is compared with the layer mean. HVO said winds from the NE below 20,000 ft; the model has them from the N to NNW, so expect agreement of a few tens of degrees, not zero.

**Meta tool calling** (two live probes through `MetaClient._call`, $0.0128, purpose `probe:tools`):
- Strict function tools with a nullable parameter typed `["string", "null"]`, an `enum` and an empty `properties` object were accepted.
- Muse Spark made two tool calls in one turn (parallel), wrote commentary before them (a `message` item: "First I'll check the volcano cameras."), and returned reasoning summaries with `reasoning={"effort": ..., "summary": "auto"}`.
- **It sent `"time": "null"` (the string) for a nullable argument.** Arguments must be validated and the string `"null"` read as null.
- `previous_response_id` chaining with `function_call_output` items works. A user message appended after the `function_call_output` items ("No turns left: write your final answer now…") made it answer without calling tools.
- Tools plus `text.format` (json_schema) in one request worked (useful in Phase 5).
- A small turn cost about $0.0023 (690 input, 413 output tokens). No cached tokens were reported on the chained turn.

**Stored data the 05:00 HST replay will see** (clock 2026-10-17T15:00:00Z):
- 14:00–15:00Z frames, all usable: KPcam 12, K2cam 30, V1cam 30.
- Tracking runs cover 13:00–19:30Z for all three cameras and the targets plume (`steam`), fountain (`lava fountain`), incandescence (`glow`). The KPcam plume is track 6 (75 detections).
- KPcam plume measurements before the clock: 14:45:05Z top 6,495 ± 345 m; 14:50:05Z 6,552 ± 358 m; **14:55:05Z top 6,951 ± 429 m, drift side 224.4°**. The 15:00:05Z frame is 5 s after the clock and must stay invisible.
- Only KPcam is calibrated (`config/calibration.yaml`); K2cam and V1cam tracks cannot be measured.
- `sample_geometry` for KPcam with 1,000 samples takes 0.6 s.

**Spend so far:** $0.83 ($0.82 before this phase, plus the $0.0128 probes).

## File map

| File | Change | Responsibility |
|---|---|---|
| `vigia/wind.py` | create | Wind profiles: interpolation, layer mean, drift comparison; Open-Meteo fetch and cache; `vigia-wind` CLI |
| `vigia/db.py` | modify | Tables `wind_profiles`, `agent_runs`, `agent_steps` |
| `vigia/meta/ledger.py` | modify | `spent_on(tag)`, `ensure_tag_budget` |
| `vigia/meta/client.py` | modify | `ToolCall`, `Turn`, `MetaClient.respond`, tagged clients with a budget |
| `vigia/agent/__init__.py` | create | Package docstring |
| `vigia/agent/tools.py` | create | `ToolError`, `ToolContext`, `Tool`, `strict_schema`, `Toolbox` and the nine tools |
| `vigia/agent/loop.py` | create | Instructions, `run_agent`, `trace`, `vigia-agent` CLI |
| `vigia/config.py`, `config/sources.yaml` | modify | `Volcano.utc_offset_hours` (local time in the instructions) |
| `pyproject.toml` | modify | Console scripts `vigia-wind`, `vigia-agent` |
| `scripts/validate_ep55.py`, `docs/VALIDATION.md` | modify | Drift against the forecast wind |
| `docs/research/agent_ep55.md` | create | The replay at 05:00 HST: trace, cost, findings |
| `tests/test_wind.py`, `tests/test_agent_tools.py`, `tests/test_agent_loop.py` | create | Tests |
| `tests/test_meta_client.py`, `tests/test_ledger.py`, `tests/test_config.py` | modify | Tests |

**Deviations from the tool signatures in `docs/PLAN.md`, on purpose:**
- `track_window(camera, start, end, target)` takes a target (plume, fountain, incandescence) instead of a free phrase: tracking costs money and minutes, so it uses the tuned phrases of `config/prompts.yaml`. `segment_frame(frame_id, phrase)` keeps the free phrase for cheap experiments.
- `get_wind(volcano, altitude_m, time, drift_bearing_deg)`: `altitude_m` says what `height_m` meant (above sea level, like `top_altitude`), and the optional drift side makes the wind check one call.
- `get_history(camera, metric, target, hours)`: a camera measures several targets, so the series needs one.
- `list_cameras_status()` lists every camera that is enabled or has frames in the last 24 hours, whatever its volcano.

Conventions for every task: English code and comments; run the whole suite with `.venv\Scripts\python.exe -m pytest` before committing; commit only the task's files; **no `Co-Authored-By` trailer**; never push (the orchestrator pushes).

---

### Task 1: Wind profile math

**Files:**
- Create: `vigia/wind.py`
- Test: `tests/test_wind.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_wind.py`:

```python
from datetime import datetime, timezone

import pytest

from vigia.wind import Level, Wind, WindProfile, compare_drift

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_wind.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigia.wind'`.

- [ ] **Step 3: Write the implementation**

Create `vigia/wind.py`:

```python
"""Winds aloft over a volcano from Open-Meteo, and how a plume's drift compares with them.

Open-Meteo serves the best-matching weather model's wind speed, direction and
geopotential height at pressure levels (850 to 300 hPa: about 1.5 to 9.7 km
over Kilauea). Between levels the wind is interpolated as east and north
components, never as angles.

A plume drifts with the wind of the layer it fills, so its drift is compared
with the mean wind between the vent and its top (`WindProfile.layer_mean`),
not with the wind at the top alone: on episode 55 the layer mean blows to the
side KPcam saw the plume on in 74 of 75 frames, the wind at the top in 59.
One camera measures only the side of its line of sight the plume sits on
(vigia.metrics drift_bearing), so `compare_drift` gives the angle between that
side and where the wind blows: under 90 degrees the wind pushes the plume to
the side it was seen on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np

CALM_MS = 1.0  # under this mean speed the wind's direction says nothing about the drift


@dataclass(frozen=True)
class Wind:
    speed_ms: float
    from_deg: float  # where the wind blows from, clockwise from north (the meteorological convention)

    @property
    def toward_deg(self) -> float:
        return (self.from_deg + 180.0) % 360.0


@dataclass(frozen=True)
class Level:
    pressure_hpa: int
    altitude_m: float  # geopotential height above sea level
    wind: Wind


@dataclass(frozen=True)
class WindProfile:
    volcano: str
    valid_at: datetime                # the model hour, UTC
    levels: tuple[Level, ...]         # lowest first
    source: str                       # forecast | historical_forecast
    grid: tuple[float, float, float]  # lat, lon and elevation (m) of the model cell Open-Meteo used

    def __post_init__(self) -> None:
        altitudes = [level.altitude_m for level in self.levels]
        if not altitudes or any(b <= a for a, b in zip(altitudes, altitudes[1:])):
            raise ValueError(f"a wind profile needs levels listed lowest first, got altitudes {altitudes}")

    def at(self, altitude_m: float) -> Wind:
        """The wind at an altitude; below the lowest level or above the highest, that level's wind."""
        z, u, v = self._components()
        return _wind(float(np.interp(altitude_m, z, u)), float(np.interp(altitude_m, z, v)))

    def layer_mean(self, bottom_m: float, top_m: float) -> Wind:
        """The height average of the wind between two altitudes; with no thickness, the wind at the bottom."""
        if top_m <= bottom_m:
            return self.at(bottom_m)
        z, u, v = self._components()
        heights = np.concatenate(([bottom_m], z[(z > bottom_m) & (z < top_m)], [top_m]))
        thickness = np.diff(heights)

        def mean(component: np.ndarray) -> float:
            values = np.interp(heights, z, component)
            return float(np.sum((values[1:] + values[:-1]) / 2 * thickness) / (top_m - bottom_m))

        return _wind(mean(u), mean(v))

    def _components(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        z = np.array([level.altitude_m for level in self.levels])
        speed = np.array([level.wind.speed_ms for level in self.levels])
        rad = np.radians([level.wind.from_deg for level in self.levels])
        return z, -speed * np.sin(rad), -speed * np.cos(rad)


def _wind(east: float, north: float) -> Wind:
    """The wind blowing towards `east` and `north` metres per second."""
    return Wind(math.hypot(east, north), math.degrees(math.atan2(-east, -north)) % 360.0)


@dataclass(frozen=True)
class DriftCheck:
    side_deg: float          # bearing of the side of the line of sight the plume was measured on
    toward_deg: float        # where the wind blows
    speed_ms: float
    angle_deg: float         # between the two, 0 to 180
    consistent: bool | None  # under 90 degrees: the wind pushes the plume to that side; None in a calm


def compare_drift(side_deg: float, wind: Wind) -> DriftCheck:
    """Compare a measured drift side (vigia.metrics drift_bearing) with a wind."""
    angle = abs((wind.toward_deg - side_deg + 180.0) % 360.0 - 180.0)
    consistent = None if wind.speed_ms < CALM_MS else angle < 90.0
    return DriftCheck(side_deg % 360.0, wind.toward_deg, wind.speed_ms, angle, consistent)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_wind.py -v`
Expected: 13 passed.

- [ ] **Step 5: Run the whole suite and commit**

```bash
.venv\Scripts\python.exe -m pytest
git add vigia/wind.py tests/test_wind.py
git commit -m "Interpolate winds aloft and compare a plume's drift side with the layer's mean wind"
```

---

### Task 2: Open-Meteo profiles, their cache and `vigia-wind`

**Files:**
- Modify: `vigia/wind.py` (append), `vigia/db.py` (SCHEMA), `pyproject.toml` (scripts)
- Test: `tests/test_wind.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wind.py` (merge the imports into the file's import block):

```python
from datetime import timedelta

import httpx

from vigia import db
from vigia.config import Sources, Volcano
from vigia.wind import WindService, WindUnavailable, main

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
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigia.sqlite"))
    return tmp_path / "data"


def test_cli_prints_the_profile_and_the_drift_check(cli_env, capsys):
    conn = db.connect(cli_env / "vigia.sqlite")
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_wind.py -v`
Expected: FAIL with `ImportError: cannot import name 'WindService'`.

- [ ] **Step 3: Add the cache table**

In `vigia/db.py`, append to `SCHEMA` (before its closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS wind_profiles (   -- Open-Meteo winds aloft over a volcano, one row per model hour (vigia.wind)
    volcano     TEXT NOT NULL,
    valid_at    TEXT NOT NULL,  -- UTC model hour
    source      TEXT NOT NULL,  -- forecast | historical_forecast
    fetched_at  TEXT NOT NULL,  -- UTC
    grid_lat    REAL NOT NULL,  -- the model cell Open-Meteo used
    grid_lon    REAL NOT NULL,
    grid_elev_m REAL NOT NULL,
    levels      TEXT NOT NULL,  -- JSON [[pressure_hpa, altitude_m, speed_ms, from_deg], ...], lowest first
    PRIMARY KEY (volcano, valid_at)
);
```

- [ ] **Step 4: Write the service and the CLI**

In `vigia/wind.py`, replace the module docstring's first paragraph and extend the imports, then append the code below. The new docstring opening:

```python
"""Winds aloft over a volcano from Open-Meteo, and how a plume's drift compares with them.

Open-Meteo serves the best-matching weather model's wind speed, direction and
geopotential height at pressure levels (850 to 300 hPa: about 1.5 to 9.7 km
over Kilauea) for any hour: hours more than two days old from the Historical
Forecast API, recent and coming ones from the Forecast API. A UTC day is
fetched at once and cached per volcano and hour in `wind_profiles`; a cached
forecast hour is fetched again after an hour. Between levels the wind is
interpolated as east and north components, never as angles.
```

(keep the second paragraph and add a usage line at the end of the docstring:)

```python
    vigia-wind --volcano kilauea --at 2026-10-17T15:00Z --altitude 6951 --bottom 1080 --side 224.4
"""
```

Imports become:

```python
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np

from vigia import db
from vigia.config import Sources, Volcano, load_sources
from vigia.settings import Settings
from vigia.timeutil import parse_utc, to_iso, utcnow
```

Constants, next to `CALM_MS`:

```python
LEVELS_HPA = (850, 700, 600, 500, 400, 300)
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HISTORICAL_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
HISTORICAL_AFTER = timedelta(days=2)   # hours older than this come from the Historical Forecast API
FORECAST_MAX_AGE = timedelta(hours=1)  # a cached forecast hour is fetched again after this
SOURCE_NAMES = {"forecast": "Open-Meteo Forecast API", "historical_forecast": "Open-Meteo Historical Forecast API"}
SOURCE_URLS = {"forecast": "https://open-meteo.com/en/docs",
               "historical_forecast": "https://open-meteo.com/en/docs/historical-forecast-api"}
_VARIABLES = ("geopotential_height", "wind_speed", "wind_direction")
```

Append at the end of the module:

```python
class WindUnavailable(RuntimeError):
    """Open-Meteo has no usable profile for that volcano and hour."""


class WindService:
    """Wind profiles over each volcano, fetched a UTC day at a time and cached in `wind_profiles`."""

    def __init__(self, conn: sqlite3.Connection, http: httpx.Client, sources: Sources,
                 now: Callable[[], datetime] = utcnow):
        self._conn = conn
        self._http = http
        self._sources = sources
        self._now = now

    def profile(self, volcano_id: str, when: datetime) -> WindProfile:
        """The profile of the model hour nearest to `when`."""
        volcano = self._sources.volcanoes.get(volcano_id)
        if volcano is None:
            raise WindUnavailable(f"unknown volcano {volcano_id!r}")
        if volcano.lat is None or volcano.lon is None:
            raise WindUnavailable(f"volcano {volcano_id} has no position in the sources file")
        hour = (when.astimezone(timezone.utc) + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
        cached = self._cached(volcano_id, hour, fresh_only=True)
        if cached is not None:
            return cached
        self._fetch_day(volcano_id, volcano, hour)
        fetched = self._cached(volcano_id, hour, fresh_only=False)
        if fetched is None:
            raise WindUnavailable(f"Open-Meteo has no wind profile for {volcano_id} at {to_iso(hour)}")
        return fetched

    def _cached(self, volcano_id: str, hour: datetime, *, fresh_only: bool) -> WindProfile | None:
        row = self._conn.execute("SELECT * FROM wind_profiles WHERE volcano = ? AND valid_at = ?",
                                 (volcano_id, to_iso(hour))).fetchone()
        if row is None:
            return None
        if (fresh_only and row["source"] == "forecast"
                and self._now() - parse_utc(row["fetched_at"]) > FORECAST_MAX_AGE):
            return None
        levels = tuple(Level(int(p), z, Wind(s, d)) for p, z, s, d in json.loads(row["levels"]))
        return WindProfile(volcano_id, hour, levels, row["source"],
                           (row["grid_lat"], row["grid_lon"], row["grid_elev_m"]))

    def _fetch_day(self, volcano_id: str, volcano: Volcano, hour: datetime) -> None:
        source = "historical_forecast" if hour < self._now() - HISTORICAL_AFTER else "forecast"
        names = [f"{name}_{p}hPa" for p in LEVELS_HPA for name in _VARIABLES]
        day = hour.date().isoformat()
        try:
            response = self._http.get(HISTORICAL_URL if source == "historical_forecast" else FORECAST_URL, params={
                "latitude": volcano.lat, "longitude": volcano.lon, "hourly": ",".join(names),
                "wind_speed_unit": "ms", "timezone": "GMT", "start_date": day, "end_date": day})
            response.raise_for_status()
            body = response.json()
            times = body["hourly"]["time"]
            columns = {name: body["hourly"][name] for name in names}
            if any(len(column) != len(times) for column in columns.values()):
                raise ValueError("hourly columns of different lengths")
            grid = (float(body["latitude"]), float(body["longitude"]), float(body["elevation"]))
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise WindUnavailable(f"Open-Meteo failed for {volcano_id} on {day}: {type(exc).__name__}: {exc}"[:300]) from exc
        fetched_at = to_iso(self._now())
        rows = []
        for i, stamp in enumerate(times):
            levels = []
            for p in LEVELS_HPA:
                z, speed, direction = (columns[f"{name}_{p}hPa"][i] for name in _VARIABLES)
                if None not in (z, speed, direction):
                    levels.append([p, float(z), float(speed), float(direction)])
            if len(levels) < 2:
                continue
            levels.sort(key=lambda level: level[1])
            valid_at = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
            rows.append((volcano_id, to_iso(valid_at), source, fetched_at, *grid, json.dumps(levels)))
        with self._conn:
            self._conn.executemany(
                """INSERT OR REPLACE INTO wind_profiles (volcano, valid_at, source, fetched_at, grid_lat, grid_lon,
                                                         grid_elev_m, levels)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Show Open-Meteo's winds aloft over a volcano and compare a "
                                                 "measured drift side with the mean wind of the layer under a plume top.")
    parser.add_argument("--volcano", required=True, help="volcano id from the sources file, e.g. kilauea")
    parser.add_argument("--at", type=parse_utc, help="time, e.g. 2026-10-17T15:00Z (default: now)")
    parser.add_argument("--altitude", type=float, help="plume top, metres above sea level")
    parser.add_argument("--bottom", type=float, help="the layer's bottom in metres, e.g. the vent (default: the lowest level)")
    parser.add_argument("--side", type=float, help="the measured drift side (drift_bearing), degrees; needs --altitude")
    args = parser.parse_args(argv)
    if args.side is not None and args.altitude is None:
        parser.error("--side needs --altitude")

    settings = Settings.from_env()
    sources = load_sources(settings.sources_path)
    if args.volcano not in sources.volcanoes:
        parser.error(f"unknown volcano {args.volcano!r} in {settings.sources_path}")
    with closing(db.connect(settings.db_path)) as conn, \
            httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=30) as http:
        try:
            profile = WindService(conn, http, sources).profile(args.volcano, args.at or utcnow())
        except WindUnavailable as exc:
            parser.exit(1, f"{exc}\n")
    lat, lon, elev = profile.grid
    print(f"{args.volcano} {to_iso(profile.valid_at)}: {SOURCE_NAMES[profile.source]}, "
          f"model cell {lat:.3f}, {lon:.3f} at {elev:.0f} m")
    for level in profile.levels:
        print(f"  {level.pressure_hpa} hPa {level.altitude_m:6.0f} m  from {level.wind.from_deg:3.0f} deg "
              f"{level.wind.speed_ms:5.1f} m/s")
    if args.altitude is None:
        return
    bottom = args.bottom if args.bottom is not None else profile.levels[0].altitude_m
    at, mean = profile.at(args.altitude), profile.layer_mean(bottom, args.altitude)
    print(f"at {args.altitude:.0f} m: from {at.from_deg:.0f} deg at {at.speed_ms:.1f} m/s")
    print(f"mean {bottom:.0f}-{args.altitude:.0f} m: from {mean.from_deg:.0f} deg (towards {mean.toward_deg:.0f} deg) "
          f"at {mean.speed_ms:.1f} m/s")
    if args.side is not None:
        check = compare_drift(args.side, mean)
        verdict = {True: "consistent", False: "not consistent", None: "too calm to tell"}[check.consistent]
        print(f"drift side {check.side_deg:.0f} deg: {check.angle_deg:.0f} deg from the mean wind: {verdict}")


if __name__ == "__main__":
    main()
```

In `pyproject.toml`, add to `[project.scripts]`:

```toml
vigia-wind = "vigia.wind:main"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_wind.py -v`
Expected: 23 passed.

- [ ] **Step 6: Run the whole suite and commit**

```bash
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest
git add vigia/wind.py vigia/db.py pyproject.toml tests/test_wind.py
git commit -m "Fetch winds aloft from Open-Meteo per volcano and hour, cache them, and show them with vigia-wind"
```

---

### Task 3: Agent turns and per-job budgets in the Meta client

**Files:**
- Modify: `vigia/meta/ledger.py`, `vigia/meta/client.py`
- Test: `tests/test_ledger.py`, `tests/test_meta_client.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ledger.py` (reuse its imports; add `import pytest` and `from conftest import NOW` if missing, and build the ledger the way the file's other tests do):

```python
def test_the_spend_of_a_tag_counts_only_calls_logged_under_it(conn):
    ledger = CostLedger(conn, daily_budget_usd=1.0, now=lambda: NOW)
    ledger.record(model="muse-spark-1.3", purpose="agent:1/turn", cost_usd=0.01)
    ledger.record(model="sam-3.1", purpose="agent:1/segment", cost_usd=0.0025)
    ledger.record(model="muse-spark-1.3", purpose="agent:12/turn", cost_usd=0.5)
    ledger.record(model="muse-spark-1.3", purpose="agent:1", cost_usd=0.5)

    assert ledger.spent_on("agent:1") == pytest.approx(0.0125)


def test_a_tag_budget_refuses_a_call_that_would_exceed_it(conn):
    ledger = CostLedger(conn, daily_budget_usd=1.0, now=lambda: NOW)
    ledger.record(model="muse-spark-1.3", purpose="agent:1/turn", cost_usd=0.25)

    ledger.ensure_tag_budget("agent:1", 0.30, 0.04)
    with pytest.raises(BudgetExceeded, match="agent:1"):
        ledger.ensure_tag_budget("agent:1", 0.30, 0.06)
```

Append to `tests/test_meta_client.py`:

```python
TOOL = {"type": "function", "name": "list_cameras_status", "description": "Status of every camera.",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        "strict": True}


def turn_body(calls, text="", reasoning="", rid="resp_2", status="completed"):
    """A Muse Spark Responses answer: optional reasoning summary and commentary, then function calls."""
    output = []
    if reasoning:
        output.append({"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": reasoning}]})
    if text:
        output.append({"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": text, "annotations": []}]})
    output += [{"type": "function_call", "id": f"fc_{i}", "call_id": f"call_{i}", "name": name,
                "arguments": arguments, "status": "completed"} for i, (name, arguments) in enumerate(calls)]
    return {"id": rid, "object": "response", "created_at": 1793000000, "status": status,
            "model": "muse-spark-1.3", "output": output, "usage": SPARK_USAGE}


def test_respond_sends_tools_and_instructions_every_turn_and_chains_the_previous_one(conn):
    api = FakeApi(lambda r: httpx.Response(200, json=turn_body([("list_cameras_status", "{}")])))
    client = make_client(api, conn)

    client.respond(input=[{"role": "user", "content": "Check the cameras."}], tools=[TOOL],
                   instructions="Be brief.", purpose="agent")
    client.respond(input=[{"type": "function_call_output", "call_id": "call_0", "output": "{}"}], tools=[TOOL],
                   instructions="Be brief.", purpose="agent", previous_response_id="resp_2")

    first, second = api.json_body(0), api.json_body(1)
    assert "previous_response_id" not in first
    assert second["previous_response_id"] == "resp_2"
    assert second["input"] == [{"type": "function_call_output", "call_id": "call_0", "output": "{}"}]
    for body in (first, second):
        assert body["model"] == "muse-spark-1.3"
        assert (body["tools"], body["instructions"]) == ([TOOL], "Be brief.")
        assert body["reasoning"] == {"effort": "medium", "summary": "auto"}
        assert body["parallel_tool_calls"] is True


def test_respond_returns_the_tool_calls_the_commentary_and_the_reasoning(conn):
    body = turn_body([("get_wind", '{"volcano": "kilauea"}'), ("list_cameras_status", "{}")],
                     text="First the cameras.", reasoning="Two independent checks.")
    api = FakeApi(lambda r: httpx.Response(200, json=body))

    turn = make_client(api, conn).respond(input=[], tools=[TOOL], instructions="x", purpose="agent")

    assert [(c.call_id, c.name, c.arguments) for c in turn.calls] == [
        ("call_0", "get_wind", '{"volcano": "kilauea"}'), ("call_1", "list_cameras_status", "{}")]
    assert (turn.response_id, turn.status, turn.text, turn.reasoning) == (
        "resp_2", "completed", "First the cameras.", "Two independent checks.")
    assert turn.cost_usd == pytest.approx(1800 * 1.25e-6 + 300 * 4.25e-6)
    assert turn.context_tokens == 2100
    assert calls(conn)[0]["purpose"] == "agent"


def test_a_tagged_client_logs_its_calls_under_the_tag(conn):
    api = FakeApi(lambda r: httpx.Response(200, json=turn_body([])))
    client = make_client(api, conn)
    job = client.tagged("agent:7")

    job.respond(input=[], tools=[TOOL], instructions="x", purpose="turn")
    client.respond(input=[], tools=[TOOL], instructions="x", purpose="turn")

    assert [row["purpose"] for row in calls(conn)] == ["agent:7/turn", "turn"]
    assert job.tag_spent() == pytest.approx(0.003525)


def test_a_tagged_budget_refuses_a_call_before_sending_it(conn):
    api = FakeApi(lambda r: httpx.Response(200, json=turn_body([])))
    job = make_client(api, conn, budget=10.0).tagged("agent:7", budget_usd=0.02)

    job.respond(input=[], tools=[TOOL], instructions="x", purpose="turn", max_output_tokens=2000)
    with pytest.raises(BudgetExceeded, match="agent:7"):
        job.respond(input=[], tools=[TOOL], instructions="x", purpose="turn")  # 6000 output tokens: ~$0.026

    assert len(api.requests) == 1


def test_an_untagged_client_has_no_job_spend(conn):
    with pytest.raises(RuntimeError, match="tagged"):
        make_client(FakeApi(lambda r: httpx.Response(500)), conn).tag_spent()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ledger.py tests/test_meta_client.py -v`
Expected: FAIL with `AttributeError: 'CostLedger' object has no attribute 'spent_on'` and `'MetaClient' object has no attribute 'respond'`.

- [ ] **Step 3: Extend the ledger**

In `vigia/meta/ledger.py`, add to `CostLedger` after `ensure_budget`:

```python
    def spent_on(self, tag: str) -> float:
        """The cost of every call logged under a tag, i.e. whose purpose starts with '<tag>/'."""
        prefix = f"{tag}/"
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM api_calls WHERE substr(purpose, 1, ?) = ?",
            (len(prefix), prefix),
        ).fetchone()
        return row["total"]

    def ensure_tag_budget(self, tag: str, budget_usd: float, estimated_cost_usd: float) -> None:
        spent = self.spent_on(tag)
        if spent + estimated_cost_usd > budget_usd:
            raise BudgetExceeded(
                f"budget ${budget_usd:.2f} of {tag} would be exceeded: "
                f"spent ${spent:.4f}, next call estimated at ${estimated_cost_usd:.4f}"
            )
```

Update the module docstring's first line to mention it:

```python
"""Cost ledger: every Meta Model API call is recorded with its cost, and a
configurable daily cap (UTC day) blocks calls that would exceed it. A job,
such as one agent run, can log its calls under a tag and have its own cap."""
```

- [ ] **Step 4: Extend the client**

In `vigia/meta/client.py`:

1. Add `from dataclasses import dataclass` to the imports.
2. Add after `SamStreamError`:

```python
@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str  # JSON text as Muse Spark wrote it; not guaranteed to match the tool's schema


@dataclass(frozen=True)
class Turn:
    """One agent turn of Muse Spark."""

    response_id: str
    status: str                  # completed, or incomplete when max_output_tokens cut it off
    text: str                    # visible text: commentary before tool calls, or the final answer
    reasoning: str               # reasoning summaries, when the API sends them
    calls: tuple[ToolCall, ...]
    cost_usd: float
    context_tokens: int          # input plus output tokens: what the next chained turn starts from
```

3. Replace `__init__` and add `tagged` and `tag_spent`:

```python
    def __init__(
        self,
        sdk: openai.OpenAI,
        ledger: CostLedger,
        *,
        spark_model: str = SPARK_MODEL,
        sam_model: str = SAM_MODEL,
        tag: str | None = None,
        tag_budget_usd: float | None = None,
    ):
        self._sdk = sdk
        self._ledger = ledger
        self.spark_model = spark_model
        self.sam_model = sam_model
        self.tag = tag
        self._tag_budget_usd = tag_budget_usd

    def tagged(self, tag: str, budget_usd: float | None = None) -> MetaClient:
        """A client for one job: its calls are logged as '<tag>/<purpose>' and, with a budget, refused once
        the job's calls would cost more than it. The daily cap still applies."""
        return MetaClient(self._sdk, self._ledger, spark_model=self.spark_model, sam_model=self.sam_model,
                          tag=tag, tag_budget_usd=budget_usd)

    def tag_spent(self) -> float:
        """What this client's job has cost so far."""
        if self.tag is None:
            raise RuntimeError("only a tagged client knows what its job has cost")
        return self._ledger.spent_on(self.tag)
```

4. Add `respond` after `ask_json`:

```python
    def respond(
        self,
        *,
        input: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        instructions: str,
        purpose: str,
        previous_response_id: str | None = None,
        effort: str = "medium",
        max_output_tokens: int = 6000,
        context_tokens: int = 0,
    ) -> Turn:
        """One agent turn of Muse Spark with function tools, chained to the previous turn.

        The server keeps the conversation of `previous_response_id` but not the request settings, so the
        tools, instructions and reasoning effort go with every turn. `context_tokens` (the previous turn's)
        feeds the pre-call budget estimate.
        """
        request: dict[str, Any] = {
            "model": self.spark_model,
            "input": input,
            "tools": tools,
            "instructions": instructions,
            "reasoning": {"effort": effort, "summary": "auto"},
            "parallel_tool_calls": True,
            "max_output_tokens": max_output_tokens,
        }
        if previous_response_id is not None:
            request["previous_response_id"] = previous_response_id
        sent = len(json.dumps(input)) + len(json.dumps(tools)) + len(instructions)
        estimate = cost_usd(self.spark_model, {"input_tokens": context_tokens + sent // 3,
                                               "output_tokens": max_output_tokens})
        response = self._call(self.spark_model, purpose, estimate, lambda: self._sdk.responses.create(**request))
        calls, reasoning = [], []
        for item in response.output:
            if item.type == "function_call":
                calls.append(ToolCall(item.call_id, item.name, item.arguments))
            elif item.type == "reasoning":
                reasoning += [part.text for part in item.summary or []]
        usage = response.usage.model_dump() if response.usage else {}
        return Turn(response.id, response.status or "", response.output_text, "\n".join(reasoning), tuple(calls),
                    cost_usd(self.spark_model, usage),
                    (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0))
```

5. In `_call`, apply the tag before the budget checks:

```python
    def _call(self, model: str, purpose: str, estimate_usd: float, send: Callable[[], Any]) -> Any:
        if self.tag is not None:
            purpose = f"{self.tag}/{purpose}"
            if self._tag_budget_usd is not None:
                self._ledger.ensure_tag_budget(self.tag, self._tag_budget_usd, estimate_usd)
        self._ledger.ensure_budget(estimate_usd)
        started = time.perf_counter()
        # ... the rest of _call is unchanged
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ledger.py tests/test_meta_client.py -v`
Expected: all pass.

- [ ] **Step 6: Run the whole suite and commit**

```bash
.venv\Scripts\python.exe -m pytest
git add vigia/meta/ledger.py vigia/meta/client.py tests/test_ledger.py tests/test_meta_client.py
git commit -m "Add Muse Spark tool-calling turns and tagged clients with a budget per job"
```

---

### Task 4: Tool framework and the read-only tools

**Files:**
- Create: `vigia/agent/__init__.py`, `vigia/agent/tools.py`
- Test: `tests/test_agent_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_tools.py`:

```python
import io
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx
import numpy as np
import pytest
from PIL import Image
from pydantic import AwareDatetime, Field

from test_metrics import kp_calibration
from vigia import masks
from vigia.agent.tools import (TOOLS, Args, HistoryArgs, NoArgs, RecentFramesArgs, Tool, ToolContext, ToolError,
                               Toolbox, get_history, get_recent_frames, list_cameras_status, strict_schema)
from vigia.config import Camera, Sources, Volcano
from vigia.ingest.store import FrameStore
from vigia.prompts import Prompts
from vigia.timeutil import to_iso
from vigia.wind import WindService

NOW = datetime(2026, 10, 28, 18, 0, tzinfo=timezone.utc)   # wall clock: Oct 17 is history for Open-Meteo
T0 = datetime(2026, 10, 17, 15, 0, 0, tzinfo=timezone.utc)  # the agent's clock: 05:00 HST in episode 55
SIZE = (384, 216)                                           # the frame size kp_calibration() expects


def cam(camera_id, enabled=False):
    return Camera(id=camera_id, name=camera_id, volcano="kilauea", url=f"https://example.org/{camera_id}.jpg",
                  license="Public Domain", attribution="U.S. Geological Survey", enabled=enabled)


SOURCES = Sources(
    volcanoes={"kilauea": Volcano(name="Kilauea", country="United States",
                                  official_agency="USGS Hawaiian Volcano Observatory (HVO)",
                                  official_url="https://www.usgs.gov/volcanoes/kilauea", lat=19.405, lon=-155.29)},
    cameras=[cam("kilauea-kp", enabled=True), cam("kilauea-k2", enabled=True), cam("kilauea-v1"), cam("kilauea-v2")],
)
PROMPTS = Prompts(plume={"visible": ["steam"]}, fountain={"visible": ["lava fountain"]})


def context(conn, tmp_path, *, client=None, now=T0, open_meteo=None):
    """Tools over the test database at clock `now`; Open-Meteo answers `open_meteo` or fails with HTTP 500."""
    def answer(request):
        return httpx.Response(200, json=open_meteo) if open_meteo is not None else httpx.Response(500)
    winds = WindService(conn, httpx.Client(transport=httpx.MockTransport(answer)), SOURCES, now=lambda: NOW)
    return ToolContext(conn=conn, data_dir=tmp_path, sources=SOURCES, calibration=kp_calibration(),
                       prompts=PROMPTS, winds=winds, now=now, client=client)


@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def frame_jpeg(n, size=SIZE):
    """A JPEG unique to n: its bits as white squares along the top edge."""
    image = Image.new("RGB", size, (90, 90, 90))
    for bit in range(12):
        if n >> bit & 1:
            image.paste((255, 255, 255), (bit * 16, 0, bit * 16 + 16, 16))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def add_frame(conn, store, camera_id, minutes, usable=True, reasons=(), size=SIZE):
    """A frame `minutes` from the agent's clock, with a quality verdict (usable=None: none yet)."""
    captured_at = T0 + timedelta(minutes=minutes)
    frame_id = store.add(camera_id, frame_jpeg(minutes + 1000, size), captured_at=captured_at,
                         timestamp_source="ashcam", fetched_at=captured_at)
    if usable is not None:
        with conn:
            conn.execute(
                """INSERT INTO frame_quality (frame_id, assessed_at, usable, decided_by, local_decision, reasons,
                                              brightness, contrast, edge_density, glow_fraction)
                   VALUES (?, '2026-10-28T00:00:00Z', ?, 'local', ?, ?, 100, 40, 0.1, 0)""",
                (frame_id, int(usable), "pass" if usable else "reject", json.dumps(list(reasons))))
    return frame_id


def capture_times(conn, frame_ids):
    return [conn.execute("SELECT captured_at FROM frames WHERE id = ?", (i,)).fetchone()[0] for i in frame_ids]


def add_run(conn, camera_id, target, frame_ids, phrase=None):
    times = capture_times(conn, frame_ids)
    with conn:
        return conn.execute(
            """INSERT INTO tracking_runs (camera_id, target, phrase, window_start, window_end, frame_ids,
                                          video_width, video_height, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 384, 216, '2026-10-28T00:00:00Z')""",
            (camera_id, target, phrase or target, min(times), max(times), json.dumps(frame_ids))).lastrowid


def add_track(conn, run_id, frame_ids, box=(60, 60, 120, 150), object_id="0"):
    """A track of the run detected on every frame of `frame_ids` with a full-box mask; returns its id."""
    times = capture_times(conn, frame_ids)
    left, top, right, bottom = box
    mask = np.ones((bottom - top, right - left), dtype=bool)
    with conn:
        track_id = conn.execute(
            "INSERT INTO tracks (run_id, object_id, first_seen, last_seen, detections) VALUES (?, ?, ?, ?, ?)",
            (run_id, object_id, min(times), max(times), len(frame_ids))).lastrowid
        for frame_id in frame_ids:
            conn.execute(
                """INSERT INTO detections (track_id, frame_id, box_left, box_top, box_right, box_bottom, score,
                                           area_px, mask_rle) VALUES (?, ?, ?, ?, ?, ?, 0.8, ?, ?)""",
                (track_id, frame_id, *box, int(mask.sum()), json.dumps(masks.encode(mask))))
    return track_id


def detection_ids(conn, track_id):
    return [row[0] for row in conn.execute("SELECT id FROM detections WHERE track_id = ? ORDER BY id", (track_id,))]


def add_measurement(conn, frame_id, metric, value, sigma, *, detection_id, target="plume", unit="m"):
    with conn:
        conn.execute(
            """INSERT INTO measurements (detection_id, frame_id, camera_id, captured_at, target, metric, value,
                                         sigma, unit, preset, computed_at)
               SELECT ?, id, camera_id, captured_at, ?, ?, ?, ?, ?, 'fixed', '2026-10-28T00:00:00Z'
               FROM frames WHERE id = ?""",
            (detection_id, target, metric, value, sigma, unit, frame_id))


# --- the framework


class Example(Args):
    camera_id: str = Field(description="camera id")
    hours: float = Field(gt=0, le=24)
    target: Literal["plume", "fountain"]
    time: AwareDatetime | None = Field(default=None, description="UTC; null for now")


def test_strict_schema_requires_every_argument_and_types_nullable_ones_with_null():
    assert strict_schema(Example) == {
        "type": "object",
        "properties": {
            "camera_id": {"type": "string", "description": "camera id"},
            "hours": {"type": "number"},
            "target": {"type": "string", "enum": ["plume", "fountain"]},
            "time": {"type": ["string", "null"], "description": "UTC; null for now"},
        },
        "required": ["camera_id", "hours", "target", "time"],
        "additionalProperties": False,
    }


def test_every_tool_is_a_strict_function_with_a_valid_name():
    for tool in TOOLS:
        definition = tool.definition()
        assert definition["type"] == "function" and definition["strict"] is True
        assert re.fullmatch(r"[a-zA-Z0-9_-]+", definition["name"])
        parameters = definition["parameters"]
        assert parameters["additionalProperties"] is False
        assert parameters["required"] == list(parameters["properties"])


class EchoArgs(Args):
    n: int = Field(ge=1)
    when: AwareDatetime | None = None


def echo(ctx, args):
    if args.n == 13:
        raise ToolError("unlucky")
    if args.n == 99:
        raise RuntimeError("boom")
    return {"n": args.n, "when": None if args.when is None else to_iso(args.when)}


ECHO = Tool("echo", "Echo n.", EchoArgs, echo)


def test_a_valid_call_runs_the_tool(conn, tmp_path):
    box = Toolbox(context(conn, tmp_path), [ECHO])

    assert box.call("echo", '{"n": 2, "when": "2026-10-17T05:00:00-10:00"}') == (
        {"n": 2, "when": "2026-10-17T15:00:00Z"}, True)


def test_the_string_null_counts_as_null(conn, tmp_path):
    # Muse Spark sent "time": "null" in the planning probe
    assert Toolbox(context(conn, tmp_path), [ECHO]).call("echo", '{"n": 2, "when": "null"}') == (
        {"n": 2, "when": None}, True)


@pytest.mark.parametrize("name, arguments, message", [
    ("nope", "{}", "unknown tool 'nope'"),
    ("echo", "{n: 2}", "not JSON"),
    ("echo", "[2]", "JSON object"),
    ("echo", '{"n": 0}', "n: Input should be greater than or equal to 1"),
    ("echo", '{"n": 2, "extra": 1}', "extra"),
    ("echo", '{"n": 2, "when": "2026-10-17T05:00"}', "when: Input should have timezone info"),
    ("echo", '{"n": 13}', "unlucky"),
    ("echo", '{"n": 99}', "echo failed: RuntimeError: boom"),
])
def test_a_bad_call_or_a_failing_tool_is_an_error_for_the_model(conn, tmp_path, name, arguments, message):
    result, ok = Toolbox(context(conn, tmp_path), [ECHO]).call(name, arguments)

    assert ok is False
    assert message in result["error"]


# --- list_cameras_status


def test_list_cameras_status_reports_each_cameras_latest_frame_as_of_the_clock(conn, store, tmp_path):
    kp_old = add_frame(conn, store, "kilauea-kp", -10)
    kp_latest = add_frame(conn, store, "kilauea-kp", -5)
    add_frame(conn, store, "kilauea-kp", 5)                              # after the clock: unseen
    add_frame(conn, store, "kilauea-k2", -45, usable=False, reasons=["low_visibility"])
    add_frame(conn, store, "kilauea-v1", -2, usable=None)                # disabled, but it has frames
    add_track(conn, add_run(conn, "kilauea-kp", "plume", [kp_old, kp_latest]), [kp_old, kp_latest])

    result = list_cameras_status(context(conn, tmp_path), NoArgs())

    cameras = {c["camera_id"]: c for c in result["cameras"]}
    assert result["now"] == "2026-10-17T15:00:00Z"
    assert set(cameras) == {"kilauea-kp", "kilauea-k2", "kilauea-v1"}  # kilauea-v2: disabled and no frames
    kp = cameras["kilauea-kp"]
    assert (kp["status"], kp["calibrated"]) == ("usable", True)
    assert kp["latest_frame"] == {"frame_id": kp_latest, "captured_at": "2026-10-17T14:55:00Z", "minutes_ago": 5.0,
                                  "usable": True, "reasons": []}
    assert (kp["frames_last_hour"], kp["usable_last_hour"]) == (2, 2)
    assert kp["last_detection"] == {"plume": "2026-10-17T14:55:00Z"}
    assert (cameras["kilauea-k2"]["status"], cameras["kilauea-k2"]["calibrated"]) == ("stale", False)
    assert cameras["kilauea-v1"]["status"] == "unassessed"


# --- get_recent_frames


def test_get_recent_frames_lists_the_newest_frames_with_verdicts_and_detections(conn, store, tmp_path):
    older, earlier, later = (add_frame(conn, store, "kilauea-kp", m) for m in (-90, -50, -30))
    rejected = add_frame(conn, store, "kilauea-kp", -20, usable=False, reasons=["low_visibility"])
    add_frame(conn, store, "kilauea-kp", 3)  # after the clock
    add_track(conn, add_run(conn, "kilauea-kp", "plume", [earlier, later]), [earlier, later])

    result = get_recent_frames(context(conn, tmp_path), RecentFramesArgs(camera_id="kilauea-kp", hours=1))

    assert (result["frames"], result["usable"], result["unassessed"]) == (3, 2, 0)
    assert result["rejected_by_reason"] == {"low_visibility": 1}
    assert [f["frame_id"] for f in result["recent"]] == [rejected, later, earlier]
    assert result["recent"][0]["reasons"] == ["low_visibility"]
    assert result["recent"][1]["detections"] == {"plume": 1}


def test_an_unknown_camera_is_a_tool_error(conn, tmp_path):
    with pytest.raises(ToolError, match="list_cameras_status"):
        get_recent_frames(context(conn, tmp_path), RecentFramesArgs(camera_id="etna-1", hours=1))


# --- get_history


def test_get_history_gives_the_series_up_to_the_clock_with_its_extremes(conn, store, tmp_path):
    frames = [add_frame(conn, store, "kilauea-kp", m) for m in (-30, -20, -10, 5)]
    for i, (frame_id, value) in enumerate(zip(frames, (5000, 6900, 6500, 7500))):
        add_measurement(conn, frame_id, "top_altitude", value, 300, detection_id=i)
    add_measurement(conn, frames[1], "top_altitude", 2000, 50, detection_id=10)  # a lower detection, same frame

    result = get_history(context(conn, tmp_path), HistoryArgs(camera_id="kilauea-kp", metric="top_altitude",
                                                              target="plume", hours=1))

    assert (result["frames"], result["unit"]) == (3, "m")
    assert [p["value"] for p in result["points"]] == [5000, 6900, 6500]
    assert result["max"] == {"captured_at": "2026-10-17T14:40:00Z", "frame_id": frames[1], "value": 6900, "sigma": 300}
    assert result["latest"]["value"] == 6500


def test_a_long_history_is_thinned_but_keeps_its_ends(conn, store, tmp_path):
    frames = [add_frame(conn, store, "kilauea-kp", -2 * i) for i in range(60, 0, -1)]
    for i, frame_id in enumerate(frames):
        add_measurement(conn, frame_id, "top_altitude", 1000 + i, 10, detection_id=i)

    result = get_history(context(conn, tmp_path), HistoryArgs(camera_id="kilauea-kp", metric="top_altitude",
                                                              target="plume", hours=3))

    assert (result["frames"], len(result["points"])) == (60, 40)
    assert (result["points"][0]["value"], result["points"][-1]["value"]) == (1000, 1059)


def test_a_camera_without_measurements_has_an_empty_history_and_a_hint(conn, tmp_path):
    result = get_history(context(conn, tmp_path), HistoryArgs(camera_id="kilauea-kp", metric="top_height",
                                                              target="fountain", hours=6))

    assert result["points"] == []
    assert "measure_track" in result["note"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigia.agent'`.

- [ ] **Step 3: Write the framework and the three read-only tools**

Create `vigia/agent/__init__.py`:

```python
"""The Muse Spark agent: tools over the stored frames and measurements, and the tool-calling loop."""
```

Create `vigia/agent/tools.py`:

```python
"""The agent's tools: what Muse Spark can look at and do, as strict JSON-schema functions.

Every tool sees the world as of the agent's clock (`ToolContext.now`): live
that is the current time; in a replay it is the simulated time, and frames,
detections and measurements captured after it do not exist. Each tool's
arguments are a Pydantic model whose JSON schema, in the strict subset of
the Responses API, is what Muse Spark sees. The API does not guarantee that
the arguments match it (Muse Spark sent the string "null" for a null while
this was planned), so every call is validated, and a bad call or a failing
tool becomes an error message for the model instead of an exception.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vigia.calibration import Calibration
from vigia.config import Camera, Sources
from vigia.meta.client import MetaClient
from vigia.prompts import Prompts, Target
from vigia.timeutil import parse_utc, to_iso
from vigia.wind import WindService

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=30)
RECENT_FRAMES = 30   # get_recent_frames lists at most this many, newest first
HISTORY_POINTS = 40  # get_history thins longer series to this many points
Metric = Literal["top_height", "top_altitude", "area", "drift_offset", "drift_bearing"]


class ToolError(Exception):
    """A tool cannot do what was asked; the message goes back to the model."""


@dataclass(frozen=True)
class ToolContext:
    conn: sqlite3.Connection
    data_dir: Path
    sources: Sources
    calibration: Calibration
    prompts: Prompts
    winds: WindService
    now: datetime                     # the agent's clock, UTC
    client: MetaClient | None = None  # the tools that call SAM or Muse Spark fail without one

    def camera(self, camera_id: str) -> Camera:
        for camera in self.sources.cameras:
            if camera.id == camera_id:
                return camera
        raise ToolError(f"unknown camera {camera_id!r}; list_cameras_status gives the ids")

    def meta(self) -> MetaClient:
        if self.client is None:
            raise ToolError("this agent has no Meta client, so it cannot call SAM or Muse Spark")
        return self.client


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(Args):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[Args]
    run: Callable[[ToolContext, Any], dict[str, Any]]

    def definition(self) -> dict[str, Any]:
        """The Responses API function tool."""
        return {"type": "function", "name": self.name, "description": self.description,
                "parameters": strict_schema(self.args), "strict": True}


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The arguments' JSON schema in the strict subset: every property required, no others allowed, a nullable
    one typed [type, "null"]. Bounds such as a minimum are left out; Pydantic checks them on every call."""
    properties = {}
    for name, prop in model.model_json_schema().get("properties", {}).items():
        nullable = "anyOf" in prop
        if nullable:
            (inner,) = [option for option in prop["anyOf"] if option.get("type") != "null"]
            prop = {**inner, "description": prop.get("description")}
        if prop.get("type") not in ("string", "integer", "number", "boolean"):
            raise TypeError(f"{model.__name__}.{name}: only scalar arguments are supported")
        out: dict[str, Any] = {"type": [prop["type"], "null"] if nullable else prop["type"]}
        if "enum" in prop:
            out["enum"] = [*prop["enum"], None] if nullable else prop["enum"]
        if prop.get("description"):
            out["description"] = prop["description"]
        properties[name] = out
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _nullable(model: type[BaseModel]) -> list[str]:
    return [name for name, prop in model.model_json_schema().get("properties", {}).items() if "anyOf" in prop]


class Toolbox:
    """The tools of one agent run, bound to its context."""

    def __init__(self, ctx: ToolContext, tools: Sequence[Tool] | None = None):
        self.ctx = ctx
        self._tools = {tool.name: tool for tool in (TOOLS if tools is None else tools)}

    def definitions(self) -> list[dict[str, Any]]:
        return [tool.definition() for tool in self._tools.values()]

    def call(self, name: str, arguments: str) -> tuple[dict[str, Any], bool]:
        """Run one tool call; returns what goes back to the model and whether the call worked."""
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"unknown tool {name!r}; the tools are {', '.join(self._tools)}"}, False
        try:
            raw = json.loads(arguments or "{}")
        except json.JSONDecodeError as exc:
            return {"error": f"the arguments are not JSON: {exc}"}, False
        if not isinstance(raw, dict):
            return {"error": "the arguments must be a JSON object"}, False
        for key in _nullable(tool.args):
            if raw.get(key) in ("null", "None", ""):
                raw[key] = None
        try:
            args = tool.args.model_validate(raw)
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in exc.errors())
            return {"error": f"invalid arguments: {problems}"}, False
        try:
            return tool.run(self.ctx, args), True
        except ToolError as exc:
            return {"error": str(exc)}, False
        except Exception as exc:  # a failing tool must not end the run: the model hears about it instead
            log.exception("tool %s failed", name)
            return {"error": f"{name} failed: {type(exc).__name__}: {exc}"[:500]}, False


def _verdict_reasons(row: sqlite3.Row) -> list[str]:
    return json.loads(row["reasons"]) if row["reasons"] else []


def _usable(row: sqlite3.Row) -> bool | None:
    return None if row["usable"] is None else bool(row["usable"])


def _round(value: float, unit: str) -> float:
    return round(value, 1) if unit == "deg" else round(value)


def _point(row: sqlite3.Row) -> dict[str, Any]:
    """A measurement row: when, on which frame, value and sigma."""
    return {"captured_at": row["captured_at"], "frame_id": row["frame_id"],
            "value": _round(row["value"], row["unit"]), "sigma": _round(row["sigma"], row["unit"])}


# --- list_cameras_status


def list_cameras_status(ctx: ToolContext, args: NoArgs) -> dict[str, Any]:
    now, hour_ago = to_iso(ctx.now), to_iso(ctx.now - timedelta(hours=1))
    cameras = []
    for camera in ctx.sources.cameras:
        latest = ctx.conn.execute(
            """SELECT f.id, f.captured_at, q.usable, q.reasons FROM frames f
               LEFT JOIN frame_quality q ON q.frame_id = f.id
               WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ?
               ORDER BY f.captured_at DESC LIMIT 1""",
            (camera.id, to_iso(ctx.now - timedelta(hours=24)), now)).fetchone()
        if latest is None and not camera.enabled:
            continue
        hour = ctx.conn.execute(
            """SELECT COUNT(*) AS frames, COALESCE(SUM(q.usable), 0) AS usable FROM frames f
               LEFT JOIN frame_quality q ON q.frame_id = f.id
               WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ?""", (camera.id, hour_ago, now)).fetchone()
        seen = ctx.conn.execute(
            """SELECT r.target, MAX(f.captured_at) AS last FROM detections d JOIN frames f ON f.id = d.frame_id
               JOIN tracks t ON t.id = d.track_id JOIN tracking_runs r ON r.id = t.run_id
               WHERE r.camera_id = ? AND f.captured_at BETWEEN ? AND ? GROUP BY r.target""",
            (camera.id, hour_ago, now)).fetchall()
        cameras.append({
            "camera_id": camera.id, "name": camera.name, "volcano": camera.volcano, "kind": camera.kind,
            "enabled": camera.enabled,
            "status": _status(ctx, latest),
            "latest_frame": None if latest is None else {
                "frame_id": latest["id"], "captured_at": latest["captured_at"],
                "minutes_ago": round((ctx.now - parse_utc(latest["captured_at"])).total_seconds() / 60, 1),
                "usable": _usable(latest), "reasons": _verdict_reasons(latest)},
            "frames_last_hour": hour["frames"], "usable_last_hour": hour["usable"],
            "calibrated": ctx.calibration.preset_for(camera.id, ctx.now) is not None,
            "last_detection": {row["target"]: row["last"] for row in seen},
        })
    return {"now": now, "cameras": cameras}


def _status(ctx: ToolContext, latest: sqlite3.Row | None) -> str:
    if latest is None:
        return "no_frames"
    if ctx.now - parse_utc(latest["captured_at"]) > STALE_AFTER:
        return "stale"
    if latest["usable"] is None:
        return "unassessed"
    return "usable" if latest["usable"] else "rejected"


# --- get_recent_frames


class RecentFramesArgs(Args):
    camera_id: str = Field(description="camera id, e.g. kilauea-kp")
    hours: float = Field(gt=0, le=24, description="how far back from now to look, in hours (at most 24)")


def get_recent_frames(ctx: ToolContext, args: RecentFramesArgs) -> dict[str, Any]:
    camera = ctx.camera(args.camera_id)
    rows = ctx.conn.execute(
        """SELECT f.id, f.captured_at, q.usable, q.reasons FROM frames f
           LEFT JOIN frame_quality q ON q.frame_id = f.id
           WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ? ORDER BY f.captured_at DESC""",
        (camera.id, to_iso(ctx.now - timedelta(hours=args.hours)), to_iso(ctx.now))).fetchall()
    shown = rows[:RECENT_FRAMES]
    found: dict[int, dict[str, int]] = defaultdict(dict)
    if shown:
        marks = ",".join("?" * len(shown))
        for row in ctx.conn.execute(
                f"""SELECT d.frame_id, r.target, COUNT(*) AS n FROM detections d JOIN tracks t ON t.id = d.track_id
                    JOIN tracking_runs r ON r.id = t.run_id
                    WHERE d.frame_id IN ({marks}) GROUP BY d.frame_id, r.target""", [row["id"] for row in shown]):
            found[row["frame_id"]][row["target"]] = row["n"]
    rejected = Counter(reason for row in rows if row["usable"] == 0 for reason in _verdict_reasons(row))
    return {
        "camera_id": camera.id, "frames": len(rows),
        "usable": sum(row["usable"] == 1 for row in rows),
        "unassessed": sum(row["usable"] is None for row in rows),
        "rejected_by_reason": dict(rejected),
        "recent": [{"frame_id": row["id"], "captured_at": row["captured_at"], "usable": _usable(row),
                    "reasons": _verdict_reasons(row), "detections": found.get(row["id"], {})} for row in shown],
    }


# --- get_history


class HistoryArgs(Args):
    camera_id: str = Field(description="camera id, e.g. kilauea-kp")
    metric: Metric = Field(description="top_height (m above the vent), top_altitude (m above sea level), area (m2), "
                                       "drift_offset (m) or drift_bearing (degrees)")
    target: Target = Field(description="what was tracked: plume, fountain or incandescence")
    hours: float = Field(gt=0, le=48, description="how far back from now, in hours (at most 48)")


def get_history(ctx: ToolContext, args: HistoryArgs) -> dict[str, Any]:
    camera = ctx.camera(args.camera_id)
    rows = ctx.conn.execute(
        """SELECT captured_at, frame_id, value, sigma, unit FROM measurements
           WHERE camera_id = ? AND target = ? AND metric = ? AND captured_at BETWEEN ? AND ?
           ORDER BY captured_at, value DESC""",
        (camera.id, args.target, args.metric, to_iso(ctx.now - timedelta(hours=args.hours)),
         to_iso(ctx.now))).fetchall()
    best: dict[str, sqlite3.Row] = {}
    for row in rows:  # the highest detection of each frame
        best.setdefault(row["captured_at"], row)
    points = list(best.values())
    head = {"camera_id": camera.id, "metric": args.metric, "target": args.target}
    if not points:
        return {**head, "points": [], "note": "no measurements in that span: track the camera (track_window) "
                                              "and measure its tracks (measure_track) first"}
    values = np.array([point["value"] for point in points])
    keep = sorted(set(np.linspace(0, len(points) - 1, min(len(points), HISTORY_POINTS)).round().astype(int)))
    return {**head, "unit": points[0]["unit"], "frames": len(points), "latest": _point(points[-1]),
            "max": _point(points[int(values.argmax())]), "min": _point(points[int(values.argmin())]),
            "points": [_point(points[i]) for i in keep]}


TOOLS: list[Tool] = [
    Tool("list_cameras_status",
         "Every camera that is enabled or sent frames in the last 24 hours, as of now: its latest frame and quality "
         "verdict; its status (usable, rejected, unassessed, stale when the latest frame is over 30 minutes old, or "
         "no_frames); frames and usable frames in the last hour; whether it is calibrated (only calibrated cameras "
         "give heights); and when each target (plume, fountain, incandescence) was last detected in the last hour.",
         NoArgs, list_cameras_status),
    Tool("get_recent_frames",
         "A camera's frames from the last `hours`, newest first (at most 30 listed): each frame's quality verdict "
         "and how many objects of each target its stored tracks detected on it, plus counts of usable frames and "
         "of rejections by reason.",
         RecentFramesArgs, get_recent_frames),
    Tool("get_history",
         "A camera's series of one metric for one target over the last `hours` (at most 48): the highest "
         "detection on each frame, thinned to 40 points, with the latest, maximum and minimum and their frame ids.",
         HistoryArgs, get_history),
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_tools.py -v`
Expected: all pass.

- [ ] **Step 5: Run the whole suite and commit**

```bash
.venv\Scripts\python.exe -m pytest
git add vigia/agent/__init__.py vigia/agent/tools.py tests/test_agent_tools.py
git commit -m "Add the agent's tool framework with validated strict tools for camera status, recent frames and history"
```

---

### Task 5: `assess_frame` and `segment_frame`

**Files:**
- Modify: `vigia/agent/tools.py`
- Test: `tests/test_agent_tools.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_tools.py` (merge imports; `FrameArgs`, `SegmentArgs`, `assess_frame`, `segment_frame` come from `vigia.agent.tools`):

```python
from test_gate import ANSWER, encode, flat, sharp, spark_api
from test_meta_client import FakeApi, make_client, response_body
from test_sam import IMAGE_OUTPUT

DAY = datetime(2026, 10, 17, 22, 0, 5, tzinfo=timezone.utc)  # 12:00 HST: the night check stays out of the way


def add_image(store, image, captured_at=DAY):
    return store.add("kilauea-kp", encode(image), captured_at=captured_at, timestamp_source="ashcam",
                     fetched_at=captured_at)


def test_assess_frame_asks_muse_spark_about_a_frame_the_local_checks_passed(conn, store, tmp_path):
    frame_id = add_image(store, sharp())
    api = spark_api()
    ctx = context(conn, tmp_path, client=make_client(api, conn), now=DAY + timedelta(minutes=5))

    result = assess_frame(ctx, FrameArgs(frame_id=frame_id))

    assert len(api.requests) == 1
    assert (result["usable"], result["decided_by"], result["activity"]) == (True, "spark", "steaming")
    assert result["description"] == ANSWER["description_en"]
    assert result["printed_ptz"] == {"pan": 29.0, "tilt": 0.0, "zoom_raw": 29.0, "zoom": 1.0}
    assert result["camera_id"] == "kilauea-kp" and result["captured_at"] == "2026-10-17T22:00:05Z"


def test_assess_frame_reuses_a_muse_spark_verdict(conn, store, tmp_path):
    frame_id = add_image(store, sharp())
    api = spark_api()
    ctx = context(conn, tmp_path, client=make_client(api, conn), now=DAY + timedelta(minutes=5))

    assess_frame(ctx, FrameArgs(frame_id=frame_id))
    again = assess_frame(ctx, FrameArgs(frame_id=frame_id))

    assert len(api.requests) == 1 and again["decided_by"] == "spark"


def test_assess_frame_does_not_ask_about_a_frame_the_local_checks_rejected(conn, store, tmp_path):
    frame_id = add_image(store, flat(150))  # fog: no edges
    api = spark_api()
    ctx = context(conn, tmp_path, client=make_client(api, conn), now=DAY + timedelta(minutes=5))

    result = assess_frame(ctx, FrameArgs(frame_id=frame_id))

    assert api.requests == []
    assert result["usable"] is False and "low_visibility" in result["reasons"]


def test_a_frame_after_the_clock_does_not_exist_for_the_agent(conn, store, tmp_path):
    frame_id = add_image(store, sharp())

    with pytest.raises(ToolError, match=f"no frame {frame_id}"):
        assess_frame(context(conn, tmp_path, now=DAY - timedelta(minutes=1)), FrameArgs(frame_id=frame_id))


def test_segment_frame_returns_sams_objects_in_the_frames_pixels(conn, store, tmp_path):
    # a 4096 px frame is sent at 2048 px, so SAM's boxes double on the way back
    frame_id = store.add("kilauea-kp", frame_jpeg(1, size=(4096, 4096)), captured_at=T0 - timedelta(minutes=5),
                         timestamp_source="ashcam", fetched_at=T0)
    api = FakeApi(lambda r: httpx.Response(200, json=response_body("sam-3.1", IMAGE_OUTPUT, {"images_processed": 1})))

    result = segment_frame(context(conn, tmp_path, client=make_client(api, conn)),
                           SegmentArgs(frame_id=frame_id, phrase="steam"))

    assert api.json_body()["input"][0]["content"][0] == {"type": "input_text", "text": "steam"}
    assert (result["phrase"], result["objects_found"]) == ("steam", 2)
    best = result["objects"][0]
    assert best == {"object_id": "0", "score": 0.96, "box": [422, 456, 542, 510], "top_row": 456,
                    "area_fraction": 0.00037}
    assert result["objects"][1]["score"] == 0.5


def test_segment_frame_needs_a_meta_client(conn, store, tmp_path):
    frame_id = add_frame(conn, store, "kilauea-kp", -5)

    with pytest.raises(ToolError, match="Meta client"):
        segment_frame(context(conn, tmp_path), SegmentArgs(frame_id=frame_id, phrase="steam"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_tools.py -v`
Expected: FAIL with `ImportError: cannot import name 'FrameArgs'`.

- [ ] **Step 3: Write the two tools**

In `vigia/agent/tools.py`, add imports:

```python
from vigia.gate import QualityGate
from vigia.imaging import load_for_upload
```

Add after the `_point` helper:

```python
def _frame(ctx: ToolContext, frame_id: int) -> sqlite3.Row:
    """A stored frame captured by the agent's clock."""
    row = ctx.conn.execute("SELECT * FROM frames WHERE id = ? AND captured_at <= ?",
                           (frame_id, to_iso(ctx.now))).fetchone()
    if row is None:
        raise ToolError(f"no frame {frame_id} captured by {to_iso(ctx.now)}")
    return row
```

Add before `TOOLS`:

```python
# --- assess_frame


class FrameArgs(Args):
    frame_id: int = Field(description="frame id, from list_cameras_status or get_recent_frames")


def _quality(ctx: ToolContext, frame_id: int) -> sqlite3.Row | None:
    return ctx.conn.execute("SELECT * FROM frame_quality WHERE frame_id = ?", (frame_id,)).fetchone()


def assess_frame(ctx: ToolContext, args: FrameArgs) -> dict[str, Any]:
    frame = _frame(ctx, args.frame_id)
    row = _quality(ctx, frame["id"])
    if row is None or (row["spark_answer"] is None and row["local_decision"] != "reject"):
        # Muse Spark looks at every frame the local checks did not reject; a rejected frame costs nothing
        gate = QualityGate(ctx.conn, ctx.data_dir, ctx.sources, ctx.client)
        verdict = gate.assess(frame["id"], spark="never")
        if verdict.local.decision != "reject":
            gate = QualityGate(ctx.conn, ctx.data_dir, ctx.sources, ctx.meta())
            gate.assess(frame["id"], spark="all")
        row = _quality(ctx, frame["id"])
    answer = json.loads(row["spark_answer"]) if row["spark_answer"] else {}
    return {
        "frame_id": frame["id"], "camera_id": frame["camera_id"], "captured_at": frame["captured_at"],
        "usable": bool(row["usable"]), "decided_by": row["decided_by"], "reasons": _verdict_reasons(row),
        "sun_elevation_deg": None if row["sun_elevation_deg"] is None else round(row["sun_elevation_deg"], 1),
        "view": answer.get("view"), "activity": answer.get("activity"),
        "visible_features": answer.get("visible_features", []), "description": answer.get("description_en"),
        "printed_time": row["printed_time"],
        "printed_ptz": json.loads(row["printed_ptz"]) if row["printed_ptz"] else None,
    }


# --- segment_frame


SEGMENT_OBJECTS = 10


class SegmentArgs(Args):
    frame_id: int = Field(description="frame id")
    phrase: str = Field(min_length=1, max_length=60,
                        description="ONE short noun phrase, e.g. 'steam' or 'lava fountain'")


def segment_frame(ctx: ToolContext, args: SegmentArgs) -> dict[str, Any]:
    frame = _frame(ctx, args.frame_id)
    client = ctx.meta()
    image, jpeg = load_for_upload(ctx.data_dir / frame["path"])
    objects = client.segment_image(jpeg, args.phrase, purpose="segment")
    sx, sy = frame["width"] / image.width, frame["height"] / image.height
    found = []
    for obj in sorted(objects, key=lambda o: -(o.score or 0.0))[:SEGMENT_OBJECTS]:
        left, top, right, bottom = obj.box
        rows = np.nonzero(obj.mask.any(axis=1))[0]
        found.append({
            "object_id": obj.object_id, "score": None if obj.score is None else round(obj.score, 3),
            "box": [round(left * sx), round(top * sy), round(right * sx), round(bottom * sy)],
            "top_row": round((top + rows.min()) * sy) if rows.size else None,
            "area_fraction": round(obj.area_px / (image.width * image.height), 5),
        })
    return {"frame_id": frame["id"], "camera_id": frame["camera_id"], "phrase": args.phrase,
            "objects_found": len(objects), "objects": found}
```

Insert into `TOOLS`, between `get_recent_frames` and `get_history`:

```python
    Tool("assess_frame",
         "Look at one frame through the quality gate: local checks, then Muse Spark (about $0.008) unless they "
         "rejected it or Muse Spark has already seen it. Returns whether the frame is usable and why, the activity "
         "and features Muse Spark sees, a description, and the time and pan/tilt/zoom printed on it.",
         FrameArgs, assess_frame),
    Tool("segment_frame",
         "Run SAM 3.1 on one frame for ONE short noun phrase ($0.0025). Returns up to 10 objects, best first: "
         "score, box and highest row in the frame's pixels, and the share of the image each covers. Tuned "
         "phrases: 'steam' for a plume, 'lava fountain', 'glow' for incandescence ('glowing lava' on thermal "
         "cameras); a phrase with 'volcanic' in it returns the fountain.",
         SegmentArgs, segment_frame),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_tools.py -v`
Expected: all pass.

- [ ] **Step 5: Run the whole suite and commit**

```bash
.venv\Scripts\python.exe -m pytest
git add vigia/agent/tools.py tests/test_agent_tools.py
git commit -m "Let the agent assess a frame through the quality gate and segment it with SAM"
```

---

### Task 6: `track_window` and `measure_track`

**Files:**
- Modify: `vigia/agent/tools.py`
- Test: `tests/test_agent_tools.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_tools.py` (merge imports; `TrackArgs`, `TrackIdArgs`, `track_window_tool`, `measure_track` come from `vigia.agent.tools`):

```python
from test_sam import OBJ_0
from test_tracking import FakeMeta, needs_ffmpeg


def test_track_window_returns_stored_tracks_that_cover_the_window_without_calling_sam(conn, store, tmp_path):
    frames = [add_frame(conn, store, "kilauea-kp", m) for m in range(-55, 30, 5)]  # the last 5 after the clock
    track = add_track(conn, add_run(conn, "kilauea-kp", "plume", frames, phrase="steam"), frames)

    result = track_window_tool(context(conn, tmp_path), TrackArgs(
        camera_id="kilauea-kp", start=T0 - timedelta(hours=1), end=T0 + timedelta(hours=1), target="plume"))

    assert (result["cached"], result["end"], result["usable_frames"]) == (True, "2026-10-17T15:00:00Z", 12)
    assert result["tracks"] == [{"track_id": track, "phrase": "steam", "object_id": "0", "detections": 12,
                                 "first_seen": "2026-10-17T14:05:00Z", "last_seen": "2026-10-17T15:00:00Z",
                                 "mean_score": 0.8, "max_area_px": 5400}]


def test_track_window_refuses_to_track_too_few_frames(conn, store, tmp_path):
    for m in (-15, -10, -5):
        add_frame(conn, store, "kilauea-kp", m)

    with pytest.raises(ToolError, match="only 3 usable frames"):
        track_window_tool(context(conn, tmp_path), TrackArgs(
            camera_id="kilauea-kp", start=T0 - timedelta(hours=1), end=T0, target="plume"))


def test_track_window_refuses_windows_over_three_hours(conn, tmp_path):
    with pytest.raises(ToolError, match="3 hours"):
        track_window_tool(context(conn, tmp_path), TrackArgs(
            camera_id="kilauea-kp", start=T0 - timedelta(hours=4), end=T0, target="plume"))


@needs_ffmpeg
def test_track_window_tracks_an_untracked_window_with_the_targets_phrases(conn, store, tmp_path):
    for m in range(-50, 1, 5):  # 11 frames
        add_frame(conn, store, "kilauea-kp", m, size=(640, 668))
    fake = FakeMeta({"steam": f"<0f>{OBJ_0}\n<10f>{OBJ_0}\n"})

    result = track_window_tool(context(conn, tmp_path, client=make_client(fake, conn)), TrackArgs(
        camera_id="kilauea-kp", start=T0 - timedelta(hours=1), end=T0, target="plume"))

    assert (result["cached"], result["usable_frames"]) == (False, 11)
    assert [track["detections"] for track in result["tracks"]] == [2]
    assert [row[0] for row in conn.execute("SELECT phrase FROM tracking_runs")] == ["steam"]


def test_measure_track_measures_the_track_up_to_the_clock(conn, store, tmp_path):
    frames = [add_frame(conn, store, "kilauea-kp", m) for m in (-10, -5, 5)]
    track = add_track(conn, add_run(conn, "kilauea-kp", "plume", frames), frames, box=(80, 60, 120, 150))

    result = measure_track(context(conn, tmp_path), TrackIdArgs(track_id=track))

    assert (result["camera_id"], result["target"], result["last"]) == ("kilauea-kp", "plume", "2026-10-17T14:55:00Z")
    assert set(result["metrics"]) == {"top_height", "top_altitude", "area", "drift_offset", "drift_bearing"}
    top = result["metrics"]["top_altitude"]
    assert (top["frames"], top["unit"], top["latest"]["frame_id"]) == (2, "m", frames[1])
    assert top["latest"]["sigma"] > 0
    assert sum(result["metrics"]["drift_bearing"]["frames_per_side"].values()) == 2
    assert conn.execute("SELECT COUNT(DISTINCT frame_id) FROM measurements").fetchone()[0] == 2  # not the later one


def test_a_track_of_an_uncalibrated_camera_cannot_be_measured(conn, store, tmp_path):
    frames = [add_frame(conn, store, "kilauea-k2", -5)]
    track = add_track(conn, add_run(conn, "kilauea-k2", "fountain", frames), frames)

    with pytest.raises(ToolError, match="kilauea-k2 is not calibrated"):
        measure_track(context(conn, tmp_path), TrackIdArgs(track_id=track))


def test_a_track_seen_only_after_the_clock_cannot_be_measured(conn, store, tmp_path):
    frames = [add_frame(conn, store, "kilauea-kp", 5)]
    track = add_track(conn, add_run(conn, "kilauea-kp", "plume", frames), frames)

    with pytest.raises(ToolError, match="no detections by 2026-10-17T15:00:00Z"):
        measure_track(context(conn, tmp_path), TrackIdArgs(track_id=track))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_tools.py -v`
Expected: FAIL with `ImportError: cannot import name 'TrackArgs'`.

- [ ] **Step 3: Write the two tools**

In `vigia/agent/tools.py`, add imports (merge `timezone` into the datetime import and `AwareDatetime` into the pydantic import):

```python
from datetime import datetime, timedelta, timezone

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from vigia import tracking
from vigia.metrics import measure_window
```

Add before `TOOLS`:

```python
# --- track_window


MAX_TRACK_HOURS = 3
MIN_TRACK_FRAMES = 10


class TrackArgs(Args):
    camera_id: str = Field(description="camera id")
    start: AwareDatetime = Field(description="window start, UTC, e.g. 2026-10-17T14:00:00Z")
    end: AwareDatetime = Field(description="window end, UTC; clipped to now")
    target: Target = Field(description="plume, fountain or incandescence")


def track_window_tool(ctx: ToolContext, args: TrackArgs) -> dict[str, Any]:
    camera = ctx.camera(args.camera_id)
    start, end = args.start.astimezone(timezone.utc), min(args.end.astimezone(timezone.utc), ctx.now)
    if start >= end:
        raise ToolError(f"the window must start before it ends and before now ({to_iso(ctx.now)})")
    if end - start > timedelta(hours=MAX_TRACK_HOURS):
        raise ToolError(f"windows are limited to {MAX_TRACK_HOURS} hours")
    frames = tracking.usable_frames(ctx.conn, ctx.data_dir, camera.id, start, end)
    if not frames:
        raise ToolError(f"{camera.id} has no usable frames between {to_iso(start)} and {to_iso(end)}")
    run_ids = _covering_runs(ctx.conn, camera.id, args.target, start, end, {frame.id for frame in frames})
    cached = bool(run_ids)
    if not cached:
        if len(frames) < MIN_TRACK_FRAMES:
            raise ToolError(f"only {len(frames)} usable frames in the window; tracking needs {MIN_TRACK_FRAMES} "
                            "(and SAM bills 50 per request anyway), so widen it")
        report = tracking.track_window(ctx.meta(), ctx.conn, ctx.data_dir, camera, ctx.prompts, start, end,
                                       targets=[args.target])
        if not report.runs:
            raise ToolError("tracking stored nothing: " + ("; ".join(report.errors)
                                                         or f"no {args.target} phrase for a {camera.kind} camera"))
        run_ids = [run.run_id for run in report.runs]
    return {"camera_id": camera.id, "target": args.target, "start": to_iso(start), "end": to_iso(end),
            "usable_frames": len(frames), "cached": cached, "tracks": _tracks(ctx.conn, run_ids, start, end)}


def _covering_runs(conn: sqlite3.Connection, camera_id: str, target: str, start: datetime, end: datetime,
                   wanted: set[int]) -> list[int]:
    """The stored runs of the camera and target over the window, if together they include every wanted frame."""
    chosen, covered = [], set()
    for row in conn.execute(
            """SELECT id, frame_ids FROM tracking_runs
               WHERE camera_id = ? AND target = ? AND window_start <= ? AND window_end >= ? ORDER BY id""",
            (camera_id, target, to_iso(end), to_iso(start))):
        frames = wanted & set(json.loads(row["frame_ids"]))
        if frames:
            chosen.append(row["id"])
            covered |= frames
    return chosen if covered >= wanted else []


def _tracks(conn: sqlite3.Connection, run_ids: list[int], start: datetime, end: datetime) -> list[dict[str, Any]]:
    marks = ",".join("?" * len(run_ids))
    rows = conn.execute(
        f"""SELECT t.id, t.object_id, r.phrase, COUNT(*) AS detections, MIN(f.captured_at) AS first_seen,
                   MAX(f.captured_at) AS last_seen, AVG(d.score) AS mean_score, MAX(d.area_px) AS max_area_px
            FROM tracks t JOIN tracking_runs r ON r.id = t.run_id JOIN detections d ON d.track_id = t.id
            JOIN frames f ON f.id = d.frame_id
            WHERE t.run_id IN ({marks}) AND f.captured_at BETWEEN ? AND ?
            GROUP BY t.id ORDER BY detections DESC, t.id""", (*run_ids, to_iso(start), to_iso(end))).fetchall()
    return [{"track_id": row["id"], "phrase": row["phrase"], "object_id": row["object_id"],
             "detections": row["detections"], "first_seen": row["first_seen"], "last_seen": row["last_seen"],
             "mean_score": None if row["mean_score"] is None else round(row["mean_score"], 2),
             "max_area_px": row["max_area_px"]} for row in rows]


# --- measure_track


class TrackIdArgs(Args):
    track_id: int = Field(description="track id, from track_window")


def measure_track(ctx: ToolContext, args: TrackIdArgs) -> dict[str, Any]:
    track = ctx.conn.execute(
        """SELECT t.id, r.camera_id, r.target, r.phrase FROM tracks t JOIN tracking_runs r ON r.id = t.run_id
           WHERE t.id = ?""", (args.track_id,)).fetchone()
    if track is None:
        raise ToolError(f"no track {args.track_id}")
    now = to_iso(ctx.now)
    span = ctx.conn.execute(
        """SELECT MIN(f.captured_at) AS first, MAX(f.captured_at) AS last FROM detections d
           JOIN frames f ON f.id = d.frame_id WHERE d.track_id = ? AND f.captured_at <= ?""",
        (track["id"], now)).fetchone()
    if span["first"] is None:
        raise ToolError(f"track {track['id']} has no detections by {now}")
    camera_id = track["camera_id"]
    if camera_id not in ctx.calibration.cameras:
        raise ToolError(f"{camera_id} is not calibrated, so its tracks cannot be measured; its detections still "
                        "show what it sees")
    report = measure_window(ctx.conn, ctx.calibration, camera_id, parse_utc(span["first"]), parse_utc(span["last"]))
    rows = ctx.conn.execute(
        """SELECT m.metric, m.value, m.sigma, m.unit, m.captured_at, m.frame_id FROM measurements m
           JOIN detections d ON d.id = m.detection_id WHERE d.track_id = ? AND m.captured_at <= ?
           ORDER BY m.captured_at""", (track["id"], now)).fetchall()
    if not rows:
        problems = report.errors or [f"{report.uncalibrated} detections lie on frames no calibration preset covers"]
        raise ToolError(f"track {track['id']} could not be measured: {'; '.join(problems)}")
    series: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        series[row["metric"]].append(row)
    metrics = {}
    for metric, values in series.items():
        latest = values[-1]
        summary = {"unit": latest["unit"], "frames": len(values), "latest": _point(latest)}
        if metric == "drift_bearing":
            summary["frames_per_side"] = dict(Counter(str(round(row["value"])) for row in values))
        else:
            numbers = np.array([row["value"] for row in values])
            summary["max"] = _point(values[int(numbers.argmax())])
            summary["mean"] = _round(float(numbers.mean()), latest["unit"])
        metrics[metric] = summary
    return {"track_id": track["id"], "camera_id": camera_id, "target": track["target"], "phrase": track["phrase"],
            "first": span["first"], "last": span["last"], "metrics": metrics}
```

Insert into `TOOLS`, between `segment_frame` and `get_history`:

```python
    Tool("track_window",
         "Track a target through a camera's usable frames between start and end (at most 3 hours, clipped to now) "
         "with SAM 3.1 video and the target's tuned phrases. If stored runs already cover every usable frame of the "
         "window it returns their tracks at no cost; otherwise it tracks the window (about $0.01 per phrase, a few "
         "minutes; needs 10 usable frames). Returns each track's id, phrase, detections in the window, and first "
         "and last detection.",
         TrackArgs, track_window_tool),
    Tool("measure_track",
         "Measure a track's detections up to now on the vertical plane through the vent: top_height (m above the "
         "vent) and top_altitude (m above sea level) of the mask's highest pixel, area (m2), and for plumes "
         "drift_offset (m across the line of sight, positive to the right) and drift_bearing (the bearing of the "
         "side of the line of sight the plume sits on). Each value has a one-sigma uncertainty from a Monte Carlo "
         "over the calibration. Returns per metric the latest, the maximum and the mean with frame ids. Only "
         "calibrated cameras can be measured.",
         TrackIdArgs, measure_track),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_tools.py -v`
Expected: all pass (the ffmpeg test is skipped only if ffmpeg is missing; it is installed on this machine).

- [ ] **Step 5: Run the whole suite and commit**

```bash
.venv\Scripts\python.exe -m pytest
git add vigia/agent/tools.py tests/test_agent_tools.py
git commit -m "Let the agent reuse or run SAM tracking over a window and measure a track up to its clock"
```

---

### Task 7: `get_wind` and `compare_cameras`

**Files:**
- Modify: `vigia/agent/tools.py`
- Test: `tests/test_agent_tools.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_tools.py` (merge imports; `WindArgs`, `CompareArgs`, `get_wind`, `compare_cameras` come from `vigia.agent.tools`):

```python
from test_wind import open_meteo_day


def test_get_wind_compares_the_drift_side_with_the_layers_mean_wind(conn, tmp_path):
    ctx = context(conn, tmp_path, open_meteo=open_meteo_day())

    result = get_wind(ctx, WindArgs(volcano="kilauea", altitude_m=6951, drift_bearing_deg=224.39))

    assert (result["model_hour"], result["source"]) == ("2026-10-17T15:00:00Z", "Open-Meteo Historical Forecast API")
    assert result["layer_mean"] == {"bottom_m": 1080, "top_m": 6951, "from_deg": 331, "toward_deg": 151,
                                    "speed_ms": 3.3}
    assert result["at_altitude"]["toward_deg"] == 80
    assert result["drift_check"] == {"measured_side_deg": 224.4, "wind_toward_deg": 151, "angle_deg": 73,
                                     "consistent": True}
    assert len(result["levels"]) == 6


def test_get_wind_without_a_drift_has_no_check(conn, tmp_path):
    result = get_wind(context(conn, tmp_path, open_meteo=open_meteo_day()), WindArgs(volcano="kilauea", altitude_m=3000))

    assert "drift_check" not in result


@pytest.mark.parametrize("args, message", [
    (dict(volcano="etna", altitude_m=3000), "unknown volcano 'etna'"),
    (dict(volcano="kilauea", altitude_m=3000, time=T0 + timedelta(hours=1)), "after now"),
])
def test_get_wind_refuses_bad_requests(conn, tmp_path, args, message):
    with pytest.raises(ToolError, match=message):
        get_wind(context(conn, tmp_path, open_meteo=open_meteo_day()), WindArgs(**args))


def test_get_wind_reports_open_meteo_failures(conn, tmp_path):
    with pytest.raises(ToolError, match="Open-Meteo"):
        get_wind(context(conn, tmp_path), WindArgs(volcano="kilauea", altitude_m=3000))


def test_compare_cameras_lines_up_each_cameras_nearest_frame(conn, store, tmp_path):
    kp = add_frame(conn, store, "kilauea-kp", -5)
    k2 = add_frame(conn, store, "kilauea-k2", -4)
    add_frame(conn, store, "kilauea-v1", -20)  # more than 10 minutes away
    (kp_detection,) = detection_ids(conn, add_track(conn, add_run(conn, "kilauea-kp", "plume", [kp]), [kp]))
    add_track(conn, add_run(conn, "kilauea-k2", "fountain", [k2]), [k2])
    add_measurement(conn, kp, "top_altitude", 6951, 429, detection_id=kp_detection)
    add_measurement(conn, kp, "drift_bearing", 224.4, 2, detection_id=kp_detection, unit="deg")

    result = compare_cameras(context(conn, tmp_path), CompareArgs(volcano="kilauea"))

    cameras = {c["camera_id"]: c for c in result["cameras"]}
    assert set(cameras) == {"kilauea-kp", "kilauea-k2"}
    assert cameras["kilauea-kp"]["measurements"] == {"plume": {
        "top_altitude": {"value": 6951, "sigma": 429, "unit": "m"},
        "drift_bearing": {"value": 224.4, "sigma": 2.0, "unit": "deg"}}}
    assert cameras["kilauea-k2"] == {"camera_id": "kilauea-k2", "frame_id": k2, "captured_at": "2026-10-17T14:56:00Z",
                                     "usable": True, "detections": {"fountain": 1}, "calibrated": False,
                                     "measurements": {}}
    assert result["agreement"] == [] and "fewer than two" in result["note"]


def test_two_cameras_measuring_the_same_height_are_cross_checked(conn, store, tmp_path):
    kp, v1 = add_frame(conn, store, "kilauea-kp", -5), add_frame(conn, store, "kilauea-v1", -3)
    for frame, value, sigma, camera_id in ((kp, 6951, 429, "kilauea-kp"), (v1, 6500, 300, "kilauea-v1")):
        (detection,) = detection_ids(conn, add_track(conn, add_run(conn, camera_id, "plume", [frame]), [frame]))
        add_measurement(conn, frame, "top_altitude", value, sigma, detection_id=detection)

    result = compare_cameras(context(conn, tmp_path), CompareArgs(volcano="kilauea", time=T0 - timedelta(minutes=4)))

    assert result["agreement"] == [{"target": "plume", "metric": "top_altitude", "cameras": ["kilauea-kp", "kilauea-v1"],
                                    "difference_m": 451, "sigma_m": 523, "z": 0.9}]


def test_compare_cameras_needs_a_frame_near_the_time(conn, tmp_path):
    with pytest.raises(ToolError, match="within 10 minutes"):
        compare_cameras(context(conn, tmp_path), CompareArgs(volcano="kilauea"))


def test_the_agent_has_the_nine_planned_tools():
    assert [tool.name for tool in TOOLS] == [
        "list_cameras_status", "get_recent_frames", "assess_frame", "segment_frame", "track_window",
        "measure_track", "get_wind", "compare_cameras", "get_history"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_tools.py -v`
Expected: FAIL with `ImportError: cannot import name 'WindArgs'`.

- [ ] **Step 3: Write the two tools**

In `vigia/agent/tools.py`, add imports:

```python
import itertools
import math

from vigia.wind import SOURCE_NAMES, SOURCE_URLS, Wind, WindService, WindUnavailable, compare_drift
```

(`WindService` was already imported; merge the line.)

Add a helper next to `_frame`:

```python
def _when(ctx: ToolContext, when: datetime | None) -> datetime:
    """A time argument in UTC, the agent's clock if None; never after the clock."""
    when = ctx.now if when is None else when.astimezone(timezone.utc)
    if when > ctx.now:
        raise ToolError(f"{to_iso(when)} is after now ({to_iso(ctx.now)})")
    return when


def _volcano(ctx: ToolContext, volcano_id: str) -> None:
    if volcano_id not in ctx.sources.volcanoes:
        raise ToolError(f"unknown volcano {volcano_id!r}; the volcanoes are {', '.join(ctx.sources.volcanoes)}")
```

Add before `TOOLS`:

```python
# --- get_wind


class WindArgs(Args):
    volcano: str = Field(description="volcano id, e.g. kilauea")
    altitude_m: float = Field(ge=0, le=20000, description="metres above sea level, e.g. a plume's top_altitude")
    time: AwareDatetime | None = Field(default=None, description="UTC time of the measurement; null for now")
    drift_bearing_deg: float | None = Field(default=None, ge=0, lt=360,
                                            description="a measured drift side (drift_bearing from measure_track) "
                                                        "to check against the wind; null to skip the check")


def _wind_json(wind: Wind) -> dict[str, Any]:
    return {"from_deg": round(wind.from_deg), "toward_deg": round(wind.toward_deg), "speed_ms": round(wind.speed_ms, 1)}


def get_wind(ctx: ToolContext, args: WindArgs) -> dict[str, Any]:
    _volcano(ctx, args.volcano)
    when = _when(ctx, args.time)
    try:
        profile = ctx.winds.profile(args.volcano, when)
    except WindUnavailable as exc:
        raise ToolError(str(exc)) from exc
    vent = ctx.calibration.vents.get(args.volcano)
    bottom = vent.elev_m if vent is not None else profile.levels[0].altitude_m
    mean = profile.layer_mean(bottom, args.altitude_m)
    result = {
        "volcano": args.volcano, "model_hour": to_iso(profile.valid_at), "source": SOURCE_NAMES[profile.source],
        "source_url": SOURCE_URLS[profile.source], "altitude_m": round(args.altitude_m),
        "at_altitude": _wind_json(profile.at(args.altitude_m)),
        "layer_mean": {"bottom_m": round(bottom), "top_m": round(max(args.altitude_m, bottom)), **_wind_json(mean)},
        "levels": [{"pressure_hpa": level.pressure_hpa, "altitude_m": round(level.altitude_m), **_wind_json(level.wind)}
                   for level in profile.levels],
    }
    if args.drift_bearing_deg is not None:
        check = compare_drift(args.drift_bearing_deg, mean)
        result["drift_check"] = {"measured_side_deg": round(check.side_deg, 1), "wind_toward_deg": round(check.toward_deg),
                                 "angle_deg": round(check.angle_deg), "consistent": check.consistent}
    return result


# --- compare_cameras


NEAR = timedelta(minutes=10)


class CompareArgs(Args):
    volcano: str = Field(description="volcano id, e.g. kilauea")
    time: AwareDatetime | None = Field(default=None, description="UTC time to compare at; null for now")


def compare_cameras(ctx: ToolContext, args: CompareArgs) -> dict[str, Any]:
    _volcano(ctx, args.volcano)
    when = _when(ctx, args.time)
    low, high = to_iso(when - NEAR), to_iso(min(when + NEAR, ctx.now))
    cameras, heights = [], defaultdict(dict)  # (target, metric) -> {camera id: (value, sigma)}
    for camera in ctx.sources.cameras:
        if camera.volcano != args.volcano:
            continue
        frames = ctx.conn.execute(
            """SELECT f.id, f.captured_at, q.usable FROM frames f LEFT JOIN frame_quality q ON q.frame_id = f.id
               WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ?""", (camera.id, low, high)).fetchall()
        if not frames:
            continue
        frame = min(frames, key=lambda row: abs(parse_utc(row["captured_at"]) - when))
        detections = ctx.conn.execute(
            """SELECT d.id, r.target FROM detections d JOIN tracks t ON t.id = d.track_id
               JOIN tracking_runs r ON r.id = t.run_id WHERE d.frame_id = ? ORDER BY d.area_px DESC, d.id""",
            (frame["id"],)).fetchall()
        largest: dict[str, int] = {}
        for row in detections:
            largest.setdefault(row["target"], row["id"])
        measured = {}
        for target, detection_id in largest.items():
            rows = ctx.conn.execute("SELECT metric, value, sigma, unit FROM measurements WHERE detection_id = ?",
                                    (detection_id,)).fetchall()
            if rows:
                measured[target] = {row["metric"]: {"value": _round(row["value"], row["unit"]),
                                                    "sigma": _round(row["sigma"], row["unit"]), "unit": row["unit"]}
                                    for row in rows}
                for row in rows:
                    heights[(target, row["metric"])][camera.id] = (row["value"], row["sigma"])
        cameras.append({"camera_id": camera.id, "frame_id": frame["id"], "captured_at": frame["captured_at"],
                        "usable": _usable(frame), "detections": dict(Counter(row["target"] for row in detections)),
                        "calibrated": ctx.calibration.preset_for(camera.id, parse_utc(frame["captured_at"])) is not None,
                        "measurements": measured})
    if not cameras:
        raise ToolError(f"no {args.volcano} camera has a frame within 10 minutes of {to_iso(when)}")
    agreement = []
    for (target, metric), by_camera in sorted(heights.items()):
        if metric not in ("top_height", "top_altitude"):
            continue
        for a, b in itertools.combinations(sorted(by_camera), 2):
            (value_a, sigma_a), (value_b, sigma_b) = by_camera[a], by_camera[b]
            sigma = math.hypot(sigma_a, sigma_b)
            agreement.append({"target": target, "metric": metric, "cameras": [a, b],
                              "difference_m": round(value_a - value_b), "sigma_m": round(sigma),
                              "z": round((value_a - value_b) / sigma, 1) if sigma else None})
    return {"volcano": args.volcano, "time": to_iso(when), "cameras": cameras, "agreement": agreement,
            "note": "" if agreement else "fewer than two cameras measured the same height, so nothing is cross-checked"}
```

Insert into `TOOLS`, between `measure_track` and `get_history`:

```python
    Tool("get_wind",
         "The model wind over a volcano at an hour (Open-Meteo, 850 to 300 hPa): the wind at an altitude, the mean "
         "wind between the vent and that altitude, and every level. Pass a plume's top_altitude and its measured "
         "drift_bearing to check the drift: the check gives the angle between that side and where the layer's mean "
         "wind blows; under 90 degrees the wind pushes the plume to the side it was seen on.",
         WindArgs, get_wind),
    Tool("compare_cameras",
         "Line up every camera of a volcano at one time: each camera's frame nearest to it (within 10 minutes), its "
         "quality, what its tracks detected there, the measurements of the largest detection per target, and, when "
         "two cameras measured the same height, their difference against the combined sigma.",
         CompareArgs, compare_cameras),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_tools.py -v`
Expected: all pass.

- [ ] **Step 5: Run the whole suite and commit**

```bash
.venv\Scripts\python.exe -m pytest
git add vigia/agent/tools.py tests/test_agent_tools.py
git commit -m "Let the agent check a drift against the forecast wind and line up the cameras at one time"
```

---

### Task 8: The agent loop and its trace

**Files:**
- Create: `vigia/agent/loop.py`
- Modify: `vigia/db.py` (SCHEMA), `vigia/config.py`, `config/sources.yaml`
- Test: `tests/test_agent_loop.py`, `tests/test_config.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_the_repo_sources_give_each_volcanos_local_time():
    sources = load_sources(REPO / "config" / "sources.yaml")

    assert sources.volcanoes["kilauea"].utc_offset_hours == -10      # HST, no daylight saving
    assert sources.volcanoes["nevado-del-ruiz"].utc_offset_hours == -5
```

Create `tests/test_agent_loop.py`:

```python
import json

import httpx
import pytest

from conftest import NOW, make_jpeg
from test_agent_tools import SOURCES, T0, context
from test_meta_client import make_client, response_body, turn_body
from test_sam import IMAGE_OUTPUT
from vigia.agent.loop import WRAP_UP, instructions, run_agent, trace
from vigia.agent.tools import Args, NoArgs, Tool
from vigia.config import Volcano
from vigia.timeutil import to_iso


class Script:
    """Answers each Meta request with the next scripted answer: a JSON body (HTTP 200) or an httpx.Response."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        answer = self.answers.pop(0)
        return answer if isinstance(answer, httpx.Response) else httpx.Response(200, json=answer)


class EchoArgs(Args):
    n: int


def echo(ctx, args):
    return {"n": args.n, "now": to_iso(ctx.now)}


def segment(ctx, args):
    return {"objects": len(ctx.meta().segment_image(make_jpeg(), "steam", purpose="segment"))}


FAKE_TOOLS = [Tool("echo", "Echo n.", EchoArgs, echo), Tool("segment", "Segment steam.", NoArgs, segment)]
TURN = 1800 * 1.25e-6 + 300 * 4.25e-6  # the cost of one scripted turn


def run(conn, tmp_path, api, **kwargs):
    return run_agent(make_client(api, conn), context(conn, tmp_path), "kilauea", "Echo twice.", tools=FAKE_TOOLS,
                     wall_clock=lambda: NOW, **kwargs)


def steps(conn, run_id):
    return conn.execute("SELECT * FROM agent_steps WHERE run_id = ? ORDER BY seq", (run_id,)).fetchall()


def test_a_run_calls_tools_until_muse_spark_answers_and_stores_the_trace(conn, tmp_path):
    api = Script(turn_body([("echo", '{"n": 1}'), ("echo", '{"n": 2}')], text="Checking.", reasoning="Two calls.",
                           rid="resp_1"),
                 turn_body([], text="n was 1 and 2.", rid="resp_2"))

    result = run(conn, tmp_path, api)

    assert (result.status, result.turns, result.final_text, result.error) == ("done", 2, "n was 1 and 2.", None)
    first, second = api.requests
    assert first["input"] == [{"role": "user", "content": "Echo twice."}] and "previous_response_id" not in first
    assert second["previous_response_id"] == "resp_1"
    assert [item["call_id"] for item in second["input"]] == ["call_0", "call_1"]
    assert json.loads(second["input"][1]["output"]) == {"n": 2, "now": "2026-10-17T15:00:00Z"}
    assert (second["tools"], second["instructions"]) == (first["tools"], first["instructions"])
    trace_rows = steps(conn, result.run_id)
    assert [(s["kind"], s["turn"], s["tool_name"]) for s in trace_rows] == [
        ("model", 1, None), ("tool", 1, "echo"), ("tool", 1, "echo"), ("model", 2, None)]
    assert (trace_rows[0]["text"], trace_rows[0]["reasoning"], trace_rows[0]["response_id"]) == (
        "Checking.", "Two calls.", "resp_1")
    assert (trace_rows[1]["ok"], trace_rows[1]["arguments"], trace_rows[1]["call_id"]) == (1, '{"n": 1}', "call_0")
    row = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (result.run_id,)).fetchone()
    assert (row["status"], row["clock"], row["volcano"], row["turns"], row["task"]) == (
        "done", "2026-10-17T15:00:00Z", "kilauea", 2, "Echo twice.")
    assert row["cost_usd"] == pytest.approx(2 * TURN) == result.cost_usd


def test_a_bad_tool_call_goes_back_to_muse_spark_as_an_error(conn, tmp_path):
    api = Script(turn_body([("echo", '{"n": "x"}'), ("nope", "{}")], rid="resp_1"), turn_body([], text="Sorry."))

    result = run(conn, tmp_path, api)

    assert result.status == "done"
    outputs = [json.loads(item["output"]) for item in api.requests[1]["input"]]
    assert "invalid arguments" in outputs[0]["error"] and "unknown tool" in outputs[1]["error"]
    assert [s["ok"] for s in steps(conn, result.run_id) if s["kind"] == "tool"] == [0, 0]


def test_tool_steps_record_what_their_meta_calls_cost(conn, tmp_path):
    api = Script(turn_body([("segment", "{}")], rid="resp_1"),
                 response_body("sam-3.1", IMAGE_OUTPUT, {"images_processed": 1}),
                 turn_body([], text="Two objects."))

    result = run(conn, tmp_path, api)

    tool_step = [s for s in steps(conn, result.run_id) if s["kind"] == "tool"][0]
    assert tool_step["cost_usd"] == pytest.approx(0.0025)
    assert json.loads(tool_step["result"]) == {"objects": 2}
    purposes = [row[0] for row in conn.execute("SELECT purpose FROM api_calls ORDER BY id")]
    assert purposes == [f"agent:{result.run_id}/turn", f"agent:{result.run_id}/segment", f"agent:{result.run_id}/turn"]
    assert result.cost_usd == pytest.approx(2 * TURN + 0.0025)


def test_the_last_turn_tells_muse_spark_to_answer_and_its_tool_calls_are_not_run(conn, tmp_path):
    api = Script(turn_body([("echo", '{"n": 1}')], rid="resp_1"), turn_body([("echo", '{"n": 2}')], rid="resp_2"))

    result = run(conn, tmp_path, api, max_turns=2)

    assert (result.status, result.turns) == ("max_turns", 2)
    assert api.requests[1]["input"][-1] == {"role": "user", "content": WRAP_UP}
    assert len([s for s in steps(conn, result.run_id) if s["kind"] == "tool"]) == 1


def test_a_run_stops_before_a_turn_that_would_exceed_its_budget(conn, tmp_path):
    api = Script()

    result = run(conn, tmp_path, api, budget_usd=0.02)  # one turn is estimated at about $0.026

    assert (result.status, result.turns, api.requests) == ("budget", 0, [])
    assert f"agent:{result.run_id}" in result.error


def test_an_api_failure_ends_the_run_with_an_error(conn, tmp_path):
    failure = httpx.Response(500, json={"error": {"message": "boom", "type": "server_error", "param": None,
                                                  "code": None}})

    result = run(conn, tmp_path, Script(failure))

    assert result.status == "error" and "boom" in result.error
    assert conn.execute("SELECT status FROM agent_runs WHERE id = ?", (result.run_id,)).fetchone()[0] == "error"


def test_an_answer_cut_off_by_the_token_limit_is_an_error(conn, tmp_path):
    result = run(conn, tmp_path, Script(turn_body([], text="The plume is", status="incomplete")))

    assert result.status == "error" and "max_output_tokens" in result.error


def test_the_instructions_give_the_clock_the_agency_and_the_rules():
    volcano = Volcano(**{**SOURCES.volcanoes["kilauea"].model_dump(), "utc_offset_hours": -10})

    text = instructions(volcano, "kilauea", T0)

    assert "It is 2026-10-17 15:00 UTC (2026-10-17 05:00 local time, UTC-10)." in text
    assert "USGS Hawaiian Volcano Observatory (HVO)" in text and "https://www.usgs.gov/volcanoes/kilauea" in text
    assert "never issue alerts" in text
    assert "The volcano's id is kilauea." in text


def test_trace_prints_each_step_and_the_final_report(conn, tmp_path):
    api = Script(turn_body([("echo", '{"n": 1}')], text="Checking.", rid="resp_1"), turn_body([], text="n was 1."))
    result = run(conn, tmp_path, api)

    text = trace(conn, result.run_id)

    assert text.splitlines()[0].startswith(f"run {result.run_id} at 2026-10-17T15:00:00Z (kilauea): done after 2 turns, $0.00")
    assert "  1 model: Checking." in text
    assert '  1 tool echo {"n": 1} -> ok' in text
    assert text.endswith("n was 1.")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigia.agent.loop'` and an `AttributeError` on `utc_offset_hours`.

- [ ] **Step 3: Add the volcano's local time**

In `vigia/config.py`, add to `Volcano` after `lon`:

```python
    utc_offset_hours: float | None = Field(default=None, ge=-12, le=14)  # local standard time; neither volcano
                                                                         # observes daylight saving
```

In `config/sources.yaml`, add to `kilauea` after `lon: -155.290`:

```yaml
    utc_offset_hours: -10   # HST
```

and to `nevado-del-ruiz` after `lon: -75.323`:

```yaml
    utc_offset_hours: -5    # Colombia
```

Also extend the file's header comment: after the lat/lon sentence add `# utc_offset_hours gives the agent the volcano's local time.`

- [ ] **Step 4: Add the trace tables**

In `vigia/db.py`, append to `SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS agent_runs (      -- one run of the Muse Spark agent (vigia.agent.loop)
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT    NOT NULL,  -- UTC wall clock
    finished_at TEXT,
    clock       TEXT    NOT NULL,  -- UTC time the agent worked at: now live, the simulated time in a replay
    volcano     TEXT    NOT NULL,
    task        TEXT    NOT NULL,  -- what it was asked
    model       TEXT    NOT NULL,
    status      TEXT    NOT NULL,  -- running | done | max_turns | budget | error
    turns       INTEGER NOT NULL DEFAULT 0,
    cost_usd    REAL    NOT NULL DEFAULT 0,  -- every Meta call of the run, its tools' calls included
    final_text  TEXT,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS agent_steps (     -- one model turn or tool call of a run, in order
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES agent_runs (id),
    seq         INTEGER NOT NULL,  -- order within the run
    turn        INTEGER NOT NULL,  -- the model turn that made it
    kind        TEXT    NOT NULL,  -- model | tool
    created_at  TEXT    NOT NULL,  -- UTC
    response_id TEXT,              -- model: the Responses API id
    text        TEXT,              -- model: its visible text, commentary or the final answer
    reasoning   TEXT,              -- model: reasoning summaries, when sent
    tool_name   TEXT,              -- tool: the function called
    call_id     TEXT,
    arguments   TEXT,              -- tool: the JSON arguments as Muse Spark sent them
    result      TEXT,              -- tool: the JSON sent back
    ok          INTEGER,           -- tool: 0 if the arguments were invalid or the tool failed
    cost_usd    REAL    NOT NULL DEFAULT 0,  -- model: the turn; tool: the Meta calls it made
    latency_ms  INTEGER,
    UNIQUE (run_id, seq)
);
```

- [ ] **Step 5: Write the loop**

Create `vigia/agent/loop.py`:

```python
"""The agent loop: Muse Spark calls the tools of vigia.agent.tools until it can answer.

Turns are chained with previous_response_id. The server keeps the
conversation but not the request settings, so the instructions, tools and
reasoning effort go with every turn. Muse Spark may call several tools in one
turn; they run one after another, in order. A run ends when Muse Spark
answers without calling a tool (done), when it still calls tools on its last
turn (max_turns; it is told to answer on that turn), when a call would push
the run's Meta spend (its own turns plus the SAM and Muse Spark calls its
tools make) past `budget_usd` or the day past the daily cap (budget), or when
the API fails (error). Every turn and tool call is a row of `agent_steps`
under one `agent_runs` row: the trace the dashboard shows.

    vigia-agent --volcano kilauea --at 2026-10-17T05:00-10:00
"""

from __future__ import annotations

import dataclasses
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import openai

from vigia.agent.tools import Tool, Toolbox, ToolContext
from vigia.config import Volcano
from vigia.meta.client import MetaClient
from vigia.meta.ledger import BudgetExceeded
from vigia.timeutil import to_iso, utcnow

MAX_TURNS = 12
BUDGET_USD = 0.30
INSTRUCTIONS = """\
You are Vigía Andino, an agent that watches the public webcams of {name} ({country}) and measures what they \
show. The official source for this volcano is {agency} ({url}). You never issue alerts or alert levels: you \
describe what the cameras show, with numbers and the frame ids that support them.

It is {now} UTC{local}. The tools only see frames captured up to this time. Give tool times in UTC with a Z, \
e.g. {example}. The volcano's id is {volcano_id}.

How to work:
- Start with list_cameras_status. Only calibrated cameras give heights.
- Prefer work already done: track_window returns stored tracks for free when the window was tracked before. \
Tracking a new window costs about $0.01 per phrase and takes minutes; segment_frame costs $0.0025 and \
assess_frame up to $0.008 per frame.
- measure_track gives top_altitude (metres above sea level) and top_height (metres above the vent) of the \
mask's highest pixel, each with a one-sigma uncertainty. drift_bearing is only the side of the camera's line of \
sight the plume sits on: one camera cannot see drift along its line of sight.
- To check a plume's drift against the wind, call get_wind with the plume top's altitude and the measured \
drift_bearing; it compares that side with the mean wind between the vent and the top.
- Call tools that do not depend on each other in the same turn.
- Quote only numbers the tools returned, with their uncertainty; never invent one.

Finish with a short report in English: what each camera shows now; the measurements with ± sigma, units, \
capture times and frame ids; the drift against the wind; and what you could not measure and why."""
WRAP_UP = "No turns left: write your final report now with what you have, without calling tools."
DEFAULT_TASK = ("Check {name} now: which cameras show activity? Measure the plume and any lava fountain you can, "
                "compare the plume's drift with the forecast wind, and report.")


@dataclass(frozen=True)
class AgentRun:
    run_id: int
    status: str  # done | max_turns | budget | error
    turns: int
    cost_usd: float
    final_text: str
    error: str | None


def instructions(volcano: Volcano, volcano_id: str, now: datetime) -> str:
    local = ""
    if volcano.utc_offset_hours is not None:
        offset = timedelta(hours=volcano.utc_offset_hours)
        local = f" ({(now + offset):%Y-%m-%d %H:%M} local time, UTC{volcano.utc_offset_hours:+g})"
    return INSTRUCTIONS.format(name=volcano.name, country=volcano.country, agency=volcano.official_agency,
                               url=volcano.official_url, now=f"{now.astimezone(timezone.utc):%Y-%m-%d %H:%M}",
                               local=local, example=to_iso(now), volcano_id=volcano_id)


def run_agent(client: MetaClient, ctx: ToolContext, volcano_id: str, task: str, *, max_turns: int = MAX_TURNS,
              budget_usd: float = BUDGET_USD, effort: str = "medium", tools: Sequence[Tool] | None = None,
              wall_clock: Callable[[], datetime] = utcnow) -> AgentRun:
    """Run the agent on one task at the context's clock and store its trace."""
    conn = ctx.conn
    text = instructions(ctx.sources.volcanoes[volcano_id], volcano_id, ctx.now)
    with conn:
        run_id = conn.execute(
            "INSERT INTO agent_runs (started_at, clock, volcano, task, model, status) VALUES (?, ?, ?, ?, ?, 'running')",
            (to_iso(wall_clock()), to_iso(ctx.now), volcano_id, task, client.spark_model)).lastrowid
    job = client.tagged(f"agent:{run_id}", budget_usd)
    toolbox = Toolbox(dataclasses.replace(ctx, client=job), tools)
    definitions = toolbox.definitions()
    pending: list[dict[str, Any]] = [{"role": "user", "content": task}]
    previous, context_tokens, seq, turns = None, 0, 0, 0
    status, final, error = "max_turns", "", None

    def step(kind: str, **columns: Any) -> None:
        nonlocal seq
        seq += 1
        columns = {"run_id": run_id, "seq": seq, "turn": turns, "kind": kind, "created_at": to_iso(wall_clock()),
                   **columns}
        with conn:
            conn.execute(f"INSERT INTO agent_steps ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                         tuple(columns.values()))

    for turn in range(1, max_turns + 1):
        if turn == max_turns:
            pending.append({"role": "user", "content": WRAP_UP})
        started = time.perf_counter()
        try:
            reply = job.respond(input=pending, tools=definitions, instructions=text, purpose="turn",
                                previous_response_id=previous, effort=effort, context_tokens=context_tokens)
        except BudgetExceeded as exc:
            status, error = "budget", str(exc)
            break
        except openai.APIError as exc:
            status, error = "error", f"{type(exc).__name__}: {exc}"[:500]
            break
        turns = turn
        step("model", response_id=reply.response_id, text=reply.text, reasoning=reply.reasoning,
             cost_usd=reply.cost_usd, latency_ms=_ms(started))
        if not reply.calls:
            final = reply.text
            if reply.status == "incomplete":
                status, error = "error", "the answer was cut off at max_output_tokens"
            else:
                status = "done"
            break
        if turn == max_turns:
            final = reply.text
            break
        pending = []
        for call in reply.calls:
            spent, started = job.tag_spent(), time.perf_counter()
            result, ok = toolbox.call(call.name, call.arguments)
            output = json.dumps(result, ensure_ascii=False)
            step("tool", tool_name=call.name, call_id=call.call_id, arguments=call.arguments, result=output,
                 ok=int(ok), cost_usd=job.tag_spent() - spent, latency_ms=_ms(started))
            pending.append({"type": "function_call_output", "call_id": call.call_id, "output": output})
        previous, context_tokens = reply.response_id, reply.context_tokens
    cost = job.tag_spent()
    with conn:
        conn.execute(
            "UPDATE agent_runs SET finished_at = ?, status = ?, turns = ?, cost_usd = ?, final_text = ?, error = ? "
            "WHERE id = ?", (to_iso(wall_clock()), status, turns, cost, final, error, run_id))
    return AgentRun(run_id, status, turns, cost, final, error)


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def trace(conn, run_id: int) -> str:
    """A stored run as text: one line per step, then the final report."""
    run = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    lines = [f"run {run_id} at {run['clock']} ({run['volcano']}): {run['status']} after {run['turns']} turns, "
             f"${run['cost_usd']:.4f}"]
    for row in conn.execute("SELECT * FROM agent_steps WHERE run_id = ? ORDER BY seq", (run_id,)):
        if row["kind"] == "model":
            if row["text"]:
                lines.append(f"  {row['turn']} model: {_short(row['text'])}")
        else:
            outcome = "ok" if row["ok"] else "error"
            lines.append(f"  {row['turn']} tool {row['tool_name']} {row['arguments']} -> {outcome} "
                         f"({row['latency_ms'] / 1000:.1f} s, ${row['cost_usd']:.4f}): {_short(row['result'])}")
    if run["error"]:
        lines.append(f"error: {run['error']}")
    lines += ["final:", run["final_text"] or ""]
    return "\n".join(lines)


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 3] + "..."
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py tests/test_config.py -v`
Expected: all pass.

- [ ] **Step 7: Run the whole suite and commit**

```bash
.venv\Scripts\python.exe -m pytest
git add vigia/agent/loop.py vigia/db.py vigia/config.py config/sources.yaml tests/test_agent_loop.py tests/test_config.py
git commit -m "Run the Muse Spark agent with turn and budget guards and store its trace"
```

---

### Task 9: The `vigia-agent` CLI

**Files:**
- Modify: `vigia/agent/loop.py`, `pyproject.toml`
- Test: `tests/test_agent_loop.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_loop.py` (merge the imports: `main` from `vigia.agent.loop`, `import openai`, `from vigia.meta.client import MetaClient`):

```python
SOURCES_YAML = """
volcanoes:
  kilauea: {name: Kilauea, country: United States, official_agency: USGS HVO,
            official_url: "https://www.usgs.gov/volcanoes/kilauea", lat: 19.405, lon: -155.29, utc_offset_hours: -10}
cameras: []
"""


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(SOURCES_YAML, encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigia.sqlite"))
    return tmp_path


def test_cli_refuses_an_unknown_volcano(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--volcano", "etna"])

    assert "etna" in capsys.readouterr().err


def test_cli_runs_the_agent_at_the_given_clock_and_prints_its_trace(cli_env, monkeypatch, capsys):
    api = Script(turn_body([("list_cameras_status", "{}")], rid="resp_1"), turn_body([], text="No cameras."))

    def fake_from_env(ledger):  # the CLI's own ledger, so its database connection is the only one
        sdk = openai.OpenAI(base_url="https://api.meta.ai/v1", api_key="test-key", max_retries=0,
                            http_client=httpx.Client(transport=httpx.MockTransport(api)))
        return MetaClient(sdk, ledger)

    monkeypatch.setattr("vigia.agent.loop.MetaClient.from_env", fake_from_env)

    main(["--volcano", "kilauea", "--at", "2026-10-17T05:00-10:00"])

    out = capsys.readouterr().out
    assert "at 2026-10-17T15:00:00Z (kilauea): done after 2 turns" in out
    assert "tool list_cameras_status {} -> ok" in out
    assert out.rstrip().endswith("No cameras.")
    assert "Check Kilauea now" in api.requests[0]["input"][0]["content"]
```

Note: `MetaClient.from_env` is a classmethod; `monkeypatch.setattr` with a plain function replaces it on the class, so `MetaClient.from_env(ledger)` calls `fake_from_env(ledger)`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py -v`
Expected: FAIL with `ImportError: cannot import name 'main'`.

- [ ] **Step 3: Write the CLI**

In `vigia/agent/loop.py`, add imports:

```python
import argparse
import logging
import sys
from contextlib import closing

import httpx

from vigia import db
from vigia.calibration import load_calibration
from vigia.config import load_sources
from vigia.meta.ledger import CostLedger
from vigia.prompts import load_prompts
from vigia.settings import Settings
from vigia.timeutil import parse_utc
from vigia.wind import WindService
```

Append at the end of the module:

```python
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Muse Spark agent on a volcano at a time: now, or a past "
                                                 "time to replay it.")
    parser.add_argument("--volcano", required=True, help="volcano id from the sources file, e.g. kilauea")
    parser.add_argument("--at", type=parse_utc, help="the agent's clock, e.g. 2026-10-17T05:00-10:00 (default: now)")
    parser.add_argument("--task", help="what to ask (default: check the volcano, measure, compare with the wind)")
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS, help=f"model turns (default {MAX_TURNS})")
    parser.add_argument("--budget", type=float, default=BUDGET_USD,
                        help=f"USD for the whole run, tool calls included (default {BUDGET_USD})")
    parser.add_argument("--effort", choices=["low", "medium", "high"], default="medium", help="reasoning effort")
    args = parser.parse_args(argv)
    if args.max_turns < 1:
        parser.error("--max-turns must be at least 1")

    settings = Settings.from_env()
    sources = load_sources(settings.sources_path)
    if args.volcano not in sources.volcanoes:
        parser.error(f"unknown volcano {args.volcano!r} in {settings.sources_path}")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # the report may hold characters a Windows console cannot show
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    task = args.task or DEFAULT_TASK.format(name=sources.volcanoes[args.volcano].name)
    with closing(db.connect(settings.db_path)) as conn, \
            httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=30) as http:
        ctx = ToolContext(conn=conn, data_dir=settings.data_dir, sources=sources,
                          calibration=load_calibration(settings.calibration_path),
                          prompts=load_prompts(settings.prompts_path), winds=WindService(conn, http, sources),
                          now=args.at or utcnow())
        client = MetaClient.from_env(CostLedger(conn, settings.daily_budget_usd))
        result = run_agent(client, ctx, args.volcano, task, max_turns=args.max_turns, budget_usd=args.budget,
                           effort=args.effort)
        print(trace(conn, result.run_id))


if __name__ == "__main__":
    main()
```

The CLI test's sources file names no calibration or prompts file: `Settings.from_env()` defaults them to `config/calibration.yaml` and `config/prompts.yaml`, which exist in the repo, and pytest runs from the repo root. In `pyproject.toml` add:

```toml
vigia-agent = "vigia.agent.loop:main"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py -v`
Expected: all pass.

- [ ] **Step 5: Run the whole suite and commit**

```bash
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest
git add vigia/agent/loop.py pyproject.toml tests/test_agent_loop.py
git commit -m "Add vigia-agent: run the agent now or at a replayed time and print its trace"
```

---

### Task 10: Acceptance run, wind validation and notes (orchestrator)

Done by the orchestrator, not an implementer: it spends real money and needs judgment.

**Files:**
- Modify: `scripts/validate_ep55.py`, `docs/VALIDATION.md`, `docs/PLAN.md`
- Create: `docs/research/agent_ep55.md`

- [ ] **Step 1: Check the wind module live**

```bash
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\vigia-wind --volcano kilauea --at 2026-10-17T15:00Z --altitude 6951 --bottom 1080 --side 224.4
```

Expected: the Historical Forecast API profile of the table above, `mean 1080-6951 m: from 331 deg (towards 151 deg) at 3.3 m/s` and `drift side 224 deg: 73 deg from the mean wind: consistent`. This caches Oct 17 in `wind_profiles`.

- [ ] **Step 2: Add the wind comparison to the validation**

In `scripts/validate_ep55.py`, add a `wind_rows(conn)` that, for `kilauea-kp`, pairs each frame's `drift_bearing` with its `top_altitude` (same `detection_id`, episode window), compares the side with `WindService(...).profile("kilauea", captured_at).layer_mean(vent_elev, top)` and with `.at(top)` via `compare_drift`, and returns one row: camera, frames, consistent with the layer mean, median angle to the layer mean, consistent with the wind at the top. The vent elevation comes from `load_calibration(settings.calibration_path).vents["kilauea"].elev_m`. Pass the rows to `report()` and add a section after "Drift direction":

```markdown
## Drift against the forecast wind

Open-Meteo's model wind over the vent (Historical Forecast API, hourly), averaged between the vent and each
frame's plume top, against the side of KPcam's line of sight the plume was measured on. The angle is between
that side and where the layer's mean wind blows; under 90° the wind pushes the plume to the side it was seen
on. The wind at the plume top alone is shown for contrast.

| Camera | Frames | Consistent with the layer mean | Median angle | Consistent with the wind at the top |
|---|---|---|---|---|
```

Run `.venv\Scripts\python.exe scripts/validate_ep55.py`. Expected row: `kilauea-kp | 75 | 74 | 39° | 59`.

- [ ] **Step 3: Replay the agent at 05:00 HST**

```bash
.venv\Scripts\vigia-agent --volcano kilauea --at 2026-10-17T05:00-10:00
```

Acceptance (PLAN Phase 4): the trace shows `list_cameras_status`; the agent picks KPcam (the only calibrated camera); it calls `track_window` on KPcam for the plume (cached: no SAM call) and `measure_track` on the KPcam plume track (track 6), whose latest value is 6,951 ± 429 m at 14:55:05Z; it calls `get_wind` with that altitude and drift side 224.4°, and the check comes back consistent (≈73°); nothing after 15:00:00Z appears; the run ends `done` under $0.30. If the agent strays (for example it never calls `get_wind`), fix the instructions or tool descriptions, rerun, and record what changed.

- [ ] **Step 4: Write `docs/research/agent_ep55.md`**

Record: the command, the trace (tools, arguments, key results), turns, cost and run id; the planning probes (strict nullable schemas accepted, the `"null"` string, parallel calls, commentary, wrap-up message, tools plus `text.format`); the wind choice (layer mean 74/75 against 59/75); anything the replay revealed.

- [ ] **Step 5: Tick `docs/PLAN.md` and update its facts**

Tick the three Phase 4 boxes; add a **Wind and agent** bullet to "Facts the plan depends on" (Open-Meteo endpoints and the layer-mean result, the agent's tools and guards, the replay's cost); update the test count in "How to resume", the module map (`wind.py` and `agent/tools.py loop.py` exist) and the budget line.

- [ ] **Step 6: Commit, push, update memory**

```bash
.venv\Scripts\python.exe -m pytest
git add scripts/validate_ep55.py docs/VALIDATION.md docs/research/agent_ep55.md docs/PLAN.md
git commit -m "Record the episode 55 agent replay and check the plume drift against the forecast wind"
git push
```

Then update the `vigia-andino-status` memory.

---

## Execution notes

- **Order:** Tasks 1–2 (wind) → 3 (client) → 4–5 → 6–7 (tools) → 8–9 (loop and CLI) → 10. Tests of later tasks import helpers from earlier test files (`test_wind.open_meteo_day`, `test_meta_client.turn_body`, `test_agent_tools.context`), so the order matters.
- **Subagents:** one `implementer` per group (1–2, 3, 4–5, 6–7, 8–9), each with one commit per task; a `reviewer` per group with its BASE and HEAD; findings go back to the same implementer by SendMessage. Task 10 is the orchestrator's.
- **Money:** Tasks 1–9 call no paid API (every test uses fakes). Task 10 calls Open-Meteo (free) and runs one agent replay (budget $0.30, expected about $0.05–0.15).
