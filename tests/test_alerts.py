import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from vigil.alerts import AlertConfig, CameraRule, Sighting, best_sighting, load_alert_config, size_of
from vigil.config import ConfigError
from vigil.meta.sam import SamObject

ROOT = Path(__file__).resolve().parent.parent
RULE = CameraRule(fountain_area=0.06, ambiguous_area=0.03)


def obj(width, height, score=0.8, left=10, top=10):
    """A SAM object whose box-sized mask is full."""
    return SamObject("0", None, (left, top, left + width, top + height), score, np.ones((height, width), dtype=bool))


def test_the_committed_alert_config_watches_v1_and_k2_with_the_calibrated_thresholds():
    config = load_alert_config(ROOT / "config" / "alerts.yaml")

    assert config.cameras == {"kilauea-v1": CameraRule(fountain_area=0.06, ambiguous_area=0.03),
                              "kilauea-k2": CameraRule(fountain_area=0.01, ambiguous_area=0.005)}


def test_an_ambiguous_band_above_the_fountain_threshold_is_refused(tmp_path):
    path = tmp_path / "alerts.yaml"
    path.write_text("cameras:\n  kilauea-v1: {fountain_area: 0.03, ambiguous_area: 0.06}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="ambiguous_area"):
        load_alert_config(path)


def test_the_best_sighting_is_the_top_score_moved_to_the_frames_pixels():
    # the frame is 4096x2304 and was sent at 2048x1152, so boxes double on the way back
    objects = [obj(100, 50, score=0.55), obj(200, 100, score=0.9, left=300, top=200), obj(400, 400, score=0.3)]

    sighting = best_sighting(objects, sent=(2048, 1152), frame=(4096, 2304))

    assert sighting.score == pytest.approx(0.9)
    assert sighting.box == (600, 400, 1000, 600)
    assert sighting.mask.shape == (200, 400) and sighting.mask.all()
    assert sighting.area == pytest.approx(200 * 100 / (2048 * 1152))


def test_objects_under_sams_floor_are_no_sighting():
    assert best_sighting([obj(400, 400, score=0.49)], sent=(1920, 1080), frame=(1920, 1080)) is None
    assert best_sighting([], sent=(1920, 1080), frame=(1920, 1080)) is None


@pytest.mark.parametrize("area, size", [(0.0299, "small"), (0.03, "ambiguous"), (0.0329, "ambiguous"),
                                        (0.059, "ambiguous"), (0.06, "large"), (0.137, "large")])
def test_a_sightings_size_follows_the_cameras_thresholds(area, size):
    sighting = Sighting(0.8, area, (0, 0, 1, 1), np.ones((1, 1), dtype=bool))

    assert size_of(sighting, RULE) == size


def test_no_sighting_is_size_none():
    assert size_of(None, RULE) == "none"
