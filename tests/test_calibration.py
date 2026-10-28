from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from vigia.calibration import (Calibration, CameraCalibration, Celestial, Distortion, FieldOfView, HorizonPixel,
                               Landmark, Preset, Roll, Site, VentPixel, load_calibration, sample_geometry)
from vigia.config import ConfigError
from vigia.geometry import View, direction, horizon_dip, local_en, sight
from vigia.settings import Settings

REPO = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def write(tmp_path, text):
    path = tmp_path / "calibration.yaml"
    path.write_text(text, encoding="utf-8")
    return path


TWO_PRESETS = """
vents:
  kilauea: {lat: 19.40496, lon: -155.29022, elev_m: 1080}
cameras:
  kilauea-k2:
    volcano: kilauea
    position: {lat: 19.42, lon: -155.2889, elev_m: 1245}
    presets:
      - {name: wide, valid_from: "2026-10-17T00:00:00Z", valid_until: "2026-10-18T00:00:00Z", image_size: [3840, 2160]}
      - {name: cone, valid_from: "2026-10-26T00:00:00Z", image_size: [3840, 2160]}
"""


def test_the_committed_calibration_loads_and_places_kp_and_k2():
    calibration = load_calibration(REPO / "config" / "calibration.yaml")

    assert {"kilauea-kp", "kilauea-k2"} <= set(calibration.cameras)
    assert calibration.vents["kilauea"].elev_m == 1080


def test_preset_for_picks_the_view_in_force(tmp_path):
    calibration = load_calibration(write(tmp_path, TWO_PRESETS))

    def name(when):
        found = calibration.preset_for("kilauea-k2", when)
        return found.name if found else None

    assert name(datetime(2026, 10, 17, 15, 0, tzinfo=UTC)) == "wide"
    assert name(datetime(2026, 10, 18, 0, 0, tzinfo=UTC)) is None  # valid_until is exclusive
    assert name(datetime(2026, 10, 27, 0, 0, tzinfo=UTC)) == "cone"
    assert name(datetime(2026, 10, 16, 0, 0, tzinfo=UTC)) is None
    assert calibration.preset_for("kilauea-v1", datetime(2026, 10, 17, 15, 0, tzinfo=UTC)) is None


def test_overlapping_presets_are_refused(tmp_path):
    text = TWO_PRESETS.replace('valid_until: "2026-10-18T00:00:00Z"', 'valid_until: "2026-10-27T00:00:00Z"')

    with pytest.raises(ConfigError, match="overlap"):
        load_calibration(write(tmp_path, text))


def test_a_camera_whose_volcano_has_no_vent_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="no vent"):
        load_calibration(write(tmp_path, TWO_PRESETS.replace("volcano: kilauea", "volcano: nevado-del-ruiz")))


def test_times_must_state_their_offset(tmp_path):
    with pytest.raises(ConfigError, match="timezone"):
        load_calibration(write(tmp_path, TWO_PRESETS.replace('"2026-10-26T00:00:00Z"', '"2026-10-26T00:00:00"')))


def test_settings_name_the_calibration_file(monkeypatch):
    monkeypatch.setenv("CALIBRATION_PATH", "elsewhere/calibration.yaml")

    assert Settings.from_env().calibration_path == Path("elsewhere/calibration.yaml")


# --- Monte Carlo samples

KP = Site(lat=19.492709, lon=-155.385281, elev_m=2034, sigma_m=500, sigma_elev_m=15)
VENT = Site(lat=19.40496, lon=-155.29022, elev_m=1080, sigma_m=10, sigma_elev_m=5)
PUUKOAE = Site(lat=19.35528, lon=-155.32235, elev_m=979, sigma_m=50, sigma_elev_m=10)
TRUE = View(np.array([146.6]), np.array([3.8]), np.array([0.7]), np.array([3050.0]), 1920, 1080)
WIDE = View(np.array([145.5]), np.array([3.0]), np.array([-0.1]), np.array([3485.0]), 1920, 1080, k1=-0.27)
MOONS = [(114.7, 10.6), (117.9, 16.8), (122.2, 5.8), (125.2, 11.4), (128.7, 16.9)]


def seen(site, view=TRUE):
    """Where a view puts a site, seen from KP."""
    east, north = local_en(site.lat, site.lon, KP.lat, KP.lon)
    return tuple(view.project(sight(east, north, site.elev_m - KP.elev_m)[None, None])[0, 0])


def on_horizon(azimuth):
    return tuple(TRUE.project(direction(azimuth, -horizon_dip(KP.elev_m))[None, None])[0, 0])


def preset(**fields):
    defaults = dict(name="fixed", valid_from="2026-10-17T00:00:00Z", image_size=(3840, 2160),
                    vent_pixel=VentPixel(pixel=seen(VENT)),
                    horizon=[HorizonPixel(pixel=on_horizon(a)) for a in (125, 145, 165)])
    return Preset(**(defaults | fields))


def calibration(*presets, position=KP):
    camera = CameraCalibration(volcano="kilauea", position=position, presets=list(presets) or [preset()])
    return Calibration(vents={"kilauea": VENT}, cameras={"kilauea-kp": camera})


def test_sample_zero_is_the_nominal_view():
    geometry = sample_geometry(calibration(), "kilauea-kp", preset(), samples=50)

    view = geometry.view
    assert (view.yaw[0], view.pitch[0], view.roll[0], view.focal[0]) == pytest.approx((146.6, 3.8, 0.7, 3050),
                                                                                      abs=1e-3)
    assert geometry.rms_px[0] == pytest.approx(0, abs=1e-3)
    assert (geometry.camera_elev[0], geometry.vent_elev[0]) == (2034, 1080)
    assert np.hypot(*geometry.vent[0, :2]) == pytest.approx(13948, abs=2)


def test_samples_spread_with_the_camera_uncertainty():
    tight = sample_geometry(calibration(position=KP.model_copy(update={"sigma_elev_m": 5})), "kilauea-kp",
                            preset(), samples=400)
    loose = sample_geometry(calibration(position=KP.model_copy(update={"sigma_elev_m": 60})), "kilauea-kp",
                            preset(), samples=400)

    assert 0 < tight.view.focal.std() < loose.view.focal.std()
    assert tight.camera_elev.std() == pytest.approx(5, rel=0.15)


def test_samples_repeat_with_the_same_seed():
    first, again, other = (sample_geometry(calibration(), "kilauea-kp", preset(), samples=20, seed=seed)
                           for seed in (7, 7, 8))

    assert np.array_equal(first.view.focal, again.view.focal)
    assert not np.array_equal(first.view.focal, other.view.focal)


def test_landmarks_and_a_field_of_view_fix_the_view():
    hfov = 2 * np.degrees(np.arctan(1920 / 3050))
    fixed = preset(horizon=[HorizonPixel(pixel=on_horizon(150))], fov=FieldOfView(hfov_deg=hfov),
                   landmarks=[Landmark(name="Puukoae", pixel=seen(PUUKOAE), **PUUKOAE.model_dump())])

    view = sample_geometry(calibration(fixed), "kilauea-kp", fixed, samples=5).view

    assert (view.yaw[0], view.pitch[0], view.roll[0], view.focal[0]) == pytest.approx((146.6, 3.8, 0.7, 3050),
                                                                                      abs=1e-3)


def test_a_preset_without_references_cannot_be_sampled():
    bare = preset(vent_pixel=None, horizon=[])

    with pytest.raises(ValueError, match="cannot fix a view"):
        sample_geometry(calibration(bare), "kilauea-kp", bare, samples=5)


def test_the_moon_and_a_free_distortion_fix_a_wide_lens():
    moons = [Celestial(name=f"moon {i}", pixel=tuple(WIDE.project(direction(az, el)[None, None])[0, 0]),
                       az_deg=az, el_deg=el) for i, (az, el) in enumerate(MOONS)]
    wide = preset(vent_pixel=VentPixel(pixel=seen(VENT, WIDE)), horizon=[], celestial=moons,
                  distortion=Distortion(k1=0.0, sigma=1.0))

    view = sample_geometry(calibration(wide), "kilauea-kp", wide, samples=5).view

    assert (view.yaw[0], view.pitch[0], view.roll[0]) == pytest.approx((145.5, 3.0, -0.1), abs=1e-3)
    assert (view.focal[0], view.k1[0]) == pytest.approx((3485.0, -0.27), rel=1e-3)


def test_a_distortion_the_references_cannot_measure_follows_its_prior():
    # two landmarks fit any k1 exactly, so only the prior decides it
    lens = preset(horizon=[], distortion=Distortion(k1=-0.15, sigma=0.15),
                  landmarks=[Landmark(name="Puukoae", pixel=seen(PUUKOAE), **PUUKOAE.model_dump())])

    view = sample_geometry(calibration(lens), "kilauea-kp", lens, samples=400).view

    assert view.k1[0] == pytest.approx(-0.15, abs=1e-3)
    assert view.k1[1:].std() == pytest.approx(0.15, rel=0.15)


def test_a_roll_the_references_cannot_measure_follows_its_prior():
    # the vent and the lens fix azimuth, tilt and focal length; nothing but the prior sets the roll
    level = preset(horizon=[], fov=FieldOfView(hfov_deg=2 * np.degrees(np.arctan(1920 / 3050))),
                   roll=Roll(deg=0.7, sigma_deg=0.5))

    view = sample_geometry(calibration(level), "kilauea-kp", level, samples=400).view

    assert view.roll[0] == pytest.approx(0.7, abs=1e-3)
    assert view.roll[1:].std() == pytest.approx(0.5, rel=0.2)
