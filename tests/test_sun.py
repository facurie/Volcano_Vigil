from datetime import datetime, timedelta, timezone

import pytest

from vigia.sun import solar_elevation

UTC = timezone.utc
HST = timezone(timedelta(hours=-10))
KILAUEA = (19.405, -155.29)


def test_noon_sun_at_the_june_solstice_stands_at_90_minus_latitude_plus_tilt():
    assert solar_elevation(datetime(2026, 6, 21, 12, 2, tzinfo=UTC), 40.0, 0.0) == pytest.approx(73.438, abs=0.01)


def test_polar_night_keeps_the_noon_sun_below_the_horizon():
    assert solar_elevation(datetime(2026, 12, 21, 12, 0, tzinfo=UTC), 80.0, 0.0) == pytest.approx(-13.438, abs=0.01)


def test_civil_twilight_at_kilauea_began_at_0554_hst_on_episode_55():
    assert solar_elevation(datetime(2026, 10, 17, 15, 50, tzinfo=UTC), *KILAUEA) == pytest.approx(-6.956, abs=0.01)
    assert solar_elevation(datetime(2026, 10, 17, 16, 0, tzinfo=UTC), *KILAUEA) == pytest.approx(-4.621, abs=0.01)


def test_any_utc_offset_gives_the_same_elevation():
    assert solar_elevation(datetime(2026, 10, 17, 3, 0, tzinfo=HST), *KILAUEA) == pytest.approx(
        solar_elevation(datetime(2026, 10, 17, 13, 0, tzinfo=UTC), *KILAUEA))


def test_a_naive_time_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        solar_elevation(datetime(2026, 10, 17, 13, 0), *KILAUEA)
