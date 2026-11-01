import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from vigil import db, masks
from vigil.alerts import (CAPTION_MAX, NOTE_EN, NOTE_ES, Alert, AlertConfig, CameraRule, Sighting, alert_texts,
                          best_sighting, caption, draw_alert_frame, duration_text, load_alert, load_alert_config,
                          size_of, store_alert)
from vigil.config import ConfigError, Volcano
from vigil.meta.sam import SamObject

ROOT = Path(__file__).resolve().parent.parent
RULE = CameraRule(fountain_area=0.06, ambiguous_area=0.03)
KILAUEA = Volcano(name="Kīlauea", country="United States (Hawaiʻi)",
                  official_agency="USGS Hawaiian Volcano Observatory (HVO)",
                  official_url="https://www.usgs.gov/volcanoes/kilauea", lat=19.405, lon=-155.29, utc_offset_hours=-10)


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


def test_the_box_scales_each_axis_by_its_own_factor_and_a_one_pixel_box_keeps_its_size():
    # sent at 1920x1080, the frame is 960x1080: x halves, y stays; the 1-px-wide box (11..12 -> 6..6) is widened
    sighting = best_sighting([obj(1, 1, left=11, top=10)], sent=(1920, 1080), frame=(960, 1080))

    assert sighting.box == (6, 10, 7, 11)
    assert sighting.mask.shape == (1, 1)
    assert sighting.area == pytest.approx(1 / (1920 * 1080))


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


def test_onset_texts_give_both_sightings_in_local_time_and_utc_in_both_languages():
    texts = alert_texts("onset", KILAUEA, camera="V1cam", captured_at="2026-10-17T13:07:02Z",
                        seen_at="2026-10-17T13:05:02Z", seen_by="V1cam")

    assert texts["headline_en"] == "Lava fountaining seen at the summit of Kīlauea"
    assert texts["headline_es"] == "Fuente de lava visible en la cumbre del Kīlauea"
    assert "at 03:05 and again at 03:07 local time (13:07 UTC, 2026-10-17)" in texts["text_en"]
    assert "a las 03:05 y de nuevo a las 03:07, hora local (13:07 UTC, 2026-10-17)" in texts["text_es"]
    assert "Only USGS Hawaiian Volcano Observatory (HVO) declares" in texts["text_en"]


def test_end_texts_name_the_cameras_the_last_sighting_and_how_long_it_lasted():
    texts = alert_texts("end", KILAUEA, camera="K2cam", captured_at="2026-10-17T19:08:02Z",
                        seen_at="2026-10-17T19:02:01Z", seen_by="K2cam", onset_at="2026-10-17T13:05:02Z",
                        cameras=("V1cam", "K2cam"))

    assert "No lava fountain on V1cam and K2cam since 09:02 local time, when K2cam last showed one" in texts["text_en"]
    assert "Ninguna fuente de lava en V1cam y K2cam desde las 09:02" in texts["text_es"]
    assert "5 h 57 min" in texts["text_en"] and "5 h 57 min" in texts["text_es"]


@pytest.mark.parametrize("minutes, text", [(7, "7 min"), (60, "1 h 00 min"), (357, "5 h 57 min")])
def test_durations_read_in_hours_and_minutes(minutes, text):
    assert duration_text(timedelta(minutes=minutes)) == text


def make_alert(kind="onset", **fields):
    texts = alert_texts(kind, KILAUEA, camera="V1cam", captured_at="2026-10-17T13:07:02Z",
                        seen_at="2026-10-17T13:05:02Z", seen_by="V1cam",
                        onset_at="2026-10-17T13:05:02Z" if kind == "end" else None,
                        cameras=("V1cam", "K2cam") if kind == "end" else ())
    values = {"volcano": "kilauea", "volcano_name": "Kīlauea", "utc_offset_hours": -10, "kind": kind,
              "clock": "2026-10-17T13:08:00Z", "created_at": "2026-11-01T20:00:00Z", "camera_id": "kilauea-v1",
              "camera_name": "V1cam", "frame_id": 1, "captured_at": "2026-10-17T13:07:02Z",
              "seen_at": "2026-10-17T13:05:02Z", "seen_by": "V1cam", "overlay": "alerts/x/frame1.jpg",
              "official_agency": KILAUEA.official_agency, "official_url": KILAUEA.official_url,
              "disclaimer_en": "Automated … does not replace official alerts …",
              "disclaimer_es": "Lectura automática … No reemplaza las alertas …", **texts}
    return Alert(**{**values, **fields})


@pytest.mark.parametrize("kind", ["onset", "end"])
def test_the_caption_has_both_languages_the_notes_and_the_official_link_within_telegrams_limit(kind):
    alert = make_alert(kind)

    text = caption(alert, prefix="REPLAY of episode 55 (2026-10-17): not a live alert. / REPETICIÓN del episodio 55: "
                                 "no es una alerta en vivo.")

    assert len(text) <= CAPTION_MAX
    for part in (alert.headline_en, alert.text_en, NOTE_EN, alert.headline_es, alert.text_es, NOTE_ES,
                 "https://www.usgs.gov/volcanoes/kilauea"):
        assert part in text


def test_an_alert_is_stored_with_its_id_and_read_back(conn):
    stored = store_alert(conn, make_alert())

    assert stored.id is not None
    assert load_alert(conn, stored.id) == stored
    row = conn.execute("SELECT kind, seen_at, sent_at, send_attempts FROM alerts").fetchone()
    assert tuple(row) == ("onset", "2026-10-17T13:05:02Z", None, 0)


def look_row(box, mask):
    """What draw_alert_frame reads from an alert_checks row."""
    left, top, right, bottom = box
    return {"id": 1, "box_left": left, "box_top": top, "box_right": right, "box_bottom": bottom,
            "mask_rle": json.dumps(masks.encode(mask))}


def test_the_alert_frame_is_scaled_to_the_overlay_width_with_the_fountain_tinted(tmp_path):
    (tmp_path / "frames").mkdir()
    Image.new("RGB", (2560, 1440), (20, 20, 20)).save(tmp_path / "frames" / "f.jpg")
    frame = {"id": 7, "path": "frames/f.jpg", "width": 2560, "height": 1440}
    look = look_row((1000, 400, 1400, 900), np.ones((500, 400), dtype=bool))

    overlay = draw_alert_frame(tmp_path, frame, look, tmp_path / "alerts" / "20261017T1308Z_onset")

    assert overlay == "alerts/20261017T1308Z_onset/frame7.jpg"
    with Image.open(tmp_path / overlay) as drawn:
        assert drawn.width == 1280
        inside, outside = drawn.getpixel((600, 320)), drawn.getpixel((100, 100))
    assert inside[0] > outside[0] + 50  # tinted with the fountain's colour


def test_an_end_frame_is_drawn_without_a_mask(tmp_path):
    (tmp_path / "frames").mkdir()
    Image.new("RGB", (640, 360), (20, 20, 20)).save(tmp_path / "frames" / "f.jpg")

    overlay = draw_alert_frame(tmp_path, {"id": 8, "path": "frames/f.jpg", "width": 640, "height": 360},
                               {"id": 2, "mask_rle": None}, tmp_path / "alerts" / "x")

    with Image.open(tmp_path / overlay) as drawn:
        assert drawn.size == (640, 360)
