from datetime import datetime, timezone
from pathlib import Path

import pytest

from vigia.calibration import load_calibration
from vigia.config import ConfigError
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
