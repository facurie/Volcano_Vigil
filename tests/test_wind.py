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
