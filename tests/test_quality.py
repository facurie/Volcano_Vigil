from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from PIL import Image, ImageDraw

from vigia.quality import ImageStats, LocalVerdict, check_local, difference, fingerprint, measure

DAY = datetime(2026, 10, 17, 22, 0, tzinfo=timezone.utc)
CLEAR = ImageStats(brightness=120, contrast=50, edge_density=0.10, glow_fraction=0.0)


def checkerboard(size=(320, 240), square=16):
    x, y = np.meshgrid(np.arange(size[0]), np.arange(size[1]))
    return Image.fromarray(((x // square + y // square) % 2 * 255).astype(np.uint8)).convert("RGB")


def dark_with_square(color, size=(320, 240)):
    image = Image.new("RGB", size, (0, 0, 0))
    ImageDraw.Draw(image).rectangle((120, 80, 199, 159), fill=color)
    return image


def with_edges(edges, glow=0.0):
    return ImageStats(brightness=120, contrast=40, edge_density=edges, glow_fraction=glow)


def check(stats=CLEAR, **kwargs):
    args = {"kind": "visible", "captured_at": DAY, "sun_elevation": 60.0, "change": 5.0} | kwargs
    return check_local(stats, **args)


# --- measurements


def test_a_flat_frame_has_no_contrast_edges_or_glow():
    stats = measure(Image.new("RGB", (320, 240), (128, 128, 128)))

    assert stats.brightness == pytest.approx(128, abs=0.5)
    assert stats.contrast == pytest.approx(0, abs=0.01)
    assert (stats.edge_density, stats.glow_fraction) == (0.0, 0.0)


def test_a_sharp_pattern_is_mostly_edges():
    stats = measure(checkerboard())

    assert stats.edge_density > 0.2
    assert stats.contrast > 100


def test_printed_text_bands_are_left_out():
    image = Image.new("RGB", (320, 240), (128, 128, 128))
    image.paste(checkerboard((320, 12), square=4), (0, 0))    # timestamp band: top 5 %
    image.paste(checkerboard((320, 19), square=4), (0, 221))  # logo and PTZ band: bottom 8 %

    stats = measure(image)

    assert stats.edge_density == 0.0
    assert stats.contrast == pytest.approx(0, abs=0.01)


@pytest.mark.parametrize("color", [(255, 120, 20), (255, 255, 255)], ids=["orange lava", "saturated white"])
def test_bright_lava_in_the_dark_counts_as_glow(color):
    stats = measure(dark_with_square(color))

    assert stats.glow_fraction == pytest.approx(80 * 80 / (320 * 209), rel=0.1)


def test_dim_light_is_not_glow():
    assert measure(dark_with_square((40, 60, 200))).glow_fraction == 0.0


def test_difference_is_zero_for_the_same_scene_under_a_new_timestamp():
    before = checkerboard()
    after = before.copy()
    after.paste(Image.new("RGB", (100, 10), (255, 255, 255)), (0, 0))  # only the printed time changed

    assert difference(fingerprint(before), fingerprint(after)) == 0.0


def test_difference_measures_luminance_change():
    darker = fingerprint(Image.new("RGB", (320, 240), (100, 100, 100)))
    brighter = fingerprint(Image.new("RGB", (320, 240), (110, 110, 110)))

    assert difference(darker, brighter) == pytest.approx(10, abs=0.5)


def test_difference_is_undefined_across_frame_sizes():
    assert difference(fingerprint(checkerboard((320, 240))), fingerprint(checkerboard((640, 480)))) is None


# --- decisions


def test_a_clear_daytime_frame_passes():
    assert check() == LocalVerdict("pass")


def test_fog_is_rejected():
    assert check(with_edges(0.004)) == LocalVerdict("reject", ("low_visibility",))


def test_haze_is_left_to_muse_spark():
    assert check(with_edges(0.010)) == LocalVerdict("uncertain", ("low_visibility",))


def test_a_dark_night_frame_is_rejected():
    assert check(with_edges(0.002), sun_elevation=-30.0) == LocalVerdict("reject", ("night",))


def test_a_night_frame_with_incandescence_passes_even_with_few_edges():
    assert check(with_edges(0.010, glow=0.002), sun_elevation=-30.0) == LocalVerdict("pass")


def test_glow_seen_through_fog_at_night_is_rejected():
    assert check(with_edges(0.001, glow=0.002), sun_elevation=-30.0) == LocalVerdict("reject", ("low_visibility",))


def test_civil_twilight_still_counts_as_day():
    assert check(with_edges(0.020), sun_elevation=-5.0) == LocalVerdict("pass")


def test_thermal_cameras_skip_the_night_and_fog_checks():
    assert check(with_edges(0.0), kind="thermal", sun_elevation=-30.0) == LocalVerdict("pass")


def test_a_frame_identical_to_the_previous_one_is_frozen():
    assert check(change=0.05) == LocalVerdict("reject", ("frozen",))


def test_the_first_frame_of_a_camera_cannot_be_frozen():
    assert check(change=None) == LocalVerdict("pass")


def test_staleness_is_judged_only_against_a_given_now():
    assert check(now=DAY + timedelta(minutes=31)) == LocalVerdict("reject", ("stale",))
    assert check(now=DAY + timedelta(minutes=29)) == LocalVerdict("pass")
    assert check(now=None) == LocalVerdict("pass")


def test_every_failing_check_is_reported():
    assert check(with_edges(0.0), sun_elevation=-30.0, change=0.0) == LocalVerdict("reject", ("frozen", "night"))


def test_without_a_sun_elevation_the_frame_counts_as_daytime():
    assert check(with_edges(0.002), sun_elevation=None) == LocalVerdict("reject", ("low_visibility",))
