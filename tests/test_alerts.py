import io
import json
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np
import openai
import pytest
from PIL import Image

from test_agent_tools import context, store  # store: fixture
from test_meta_client import FakeApi, make_client
from vigil import db, masks
from vigil.alerts import (CAPTION_MAX, LAVA_GLOW, MAX_SEND_ATTEMPTS, NOTE_EN, NOTE_ES, Alert, AlertConfig,
                          AlertWatcher, CameraRule, Sighting, alert_texts, best_sighting, caption, draw_alert_frame,
                          duration_text, load_alert, load_alert_config, main, post_replay, send_pending, size_of,
                          store_alert)
from vigil.config import ConfigError, Volcano
from vigil.meta.ledger import BudgetExceeded
from vigil.meta.sam import SamObject
from vigil.telegram import TelegramError
from vigil.timeutil import to_iso

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


T0 = datetime(2026, 10, 17, 13, 0, tzinfo=timezone.utc)   # 03:00 HST: night at Kīlauea
DAY = datetime(2026, 10, 17, 22, 0, tzinfo=timezone.utc)  # 12:00 HST
M = timedelta(minutes=1)
CONFIG = AlertConfig(cameras={"kilauea-v1": RULE, "kilauea-k2": RULE})
SIZE = (384, 216)
LARGE, AMBIGUOUS, SMALL = (200, 100), (100, 30), (40, 20)  # 0.24, 0.036 and 0.0096 of a 384x216 frame
SUSTAINED = {"fountain_visible": True, "larger_than_before": True, "looks_like": "sustained_fountain",
             "reason": "much larger"}
OVERFLOW = {"fountain_visible": True, "larger_than_before": False, "looks_like": "overflow_or_dome",
            "reason": "same as before"}


def scene_jpeg(seed, lava=True):
    """A frame with detail, dark enough never to look hot, and a block of lava's colour when `lava`."""
    pixels = np.random.default_rng(seed).integers(0, 120, (SIZE[1], SIZE[0], 3), dtype=np.uint8)
    if lava:
        pixels[80:180, 120:260] = (255, 120, 20)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, format="JPEG")
    return buffer.getvalue()


class Fakes:
    """SAM and Muse Spark for the watcher: SAM answers per frame id, Muse Spark with one answer."""

    def __init__(self):
        self.sam = {}           # frame id -> (width, height) of a full-box sighting; others show nothing
        self.looked = []        # frame ids SAM looked at, in order
        self.tags = []          # the tag of the client each look used
        self.answer = SUSTAINED
        self.asked = []         # minutes between the two frames of each Muse Spark comparison
        self.raises = None      # an exception SAM raises
        self.compare_raises = None  # an exception Muse Spark raises

    def segment(self, client, frame_id, jpeg):
        if self.raises is not None:
            raise self.raises
        self.looked.append(frame_id)
        self.tags.append(client.tag)
        width, height = self.sam.get(frame_id, (0, 0))
        return [obj(width, height)] if width else []

    def compare(self, client, earlier, now, minutes):
        self.asked.append(minutes)
        if self.compare_raises is not None:
            raise self.compare_raises
        return self.answer


@pytest.fixture
def fakes():
    return Fakes()


def add(store, camera_id, when, lava=True):
    seed = int(when.timestamp()) // 60 * 10 + {"kilauea-v1": 1, "kilauea-k2": 2}[camera_id]
    return store.add(camera_id, scene_jpeg(seed, lava), captured_at=when, timestamp_source="ashcam", fetched_at=when)


def series(store, camera_id, start, first, last, every=2, lava=True):
    """Frames every `every` minutes from `first` to `last` minutes after `start`: {minute: frame id}."""
    return {minute: add(store, camera_id, start + minute * M, lava) for minute in range(first, last + 1, every)}


def watcher(conn, tmp_path, fakes, config=CONFIG, now=T0):
    client = make_client(FakeApi(lambda request: httpx.Response(500)), conn, budget=5.0)
    return AlertWatcher(context(conn, tmp_path, client=client, now=now), "kilauea", config, tmp_path / "alerts",
                        budget_usd=0.75, segment=fakes.segment, compare=fakes.compare)


def run(w, start, first, last):
    """Step the watcher every minute from `first` to `last` minutes after `start`; the reports."""
    return [w.step(start + minute * M) for minute in range(first, last + 1)]


V1_ONLY = AlertConfig(cameras={"kilauea-v1": RULE})


def looked_minutes(frames, fakes):
    by_id = {frame_id: minute for minute, frame_id in frames.items()}
    return [by_id[frame_id] for frame_id in fakes.looked]


def test_while_lava_is_visible_sam_looks_every_eight_minutes(conn, store, tmp_path, fakes):
    frames = series(store, "kilauea-v1", T0, 0, 30)
    fakes.sam = {frame_id: SMALL for frame_id in frames.values()}

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 30)

    assert looked_minutes(frames, fakes) == [0, 8, 16, 24]
    sizes = [row["size"] for row in conn.execute("SELECT size FROM alert_checks ORDER BY captured_at")]
    assert sizes == ["small"] * 4


def test_a_clear_day_with_no_lava_gets_a_look_every_half_hour(conn, store, tmp_path, fakes):
    frames = series(store, "kilauea-v1", DAY, 0, 62, lava=False)

    run(watcher(conn, tmp_path, fakes, V1_ONLY, now=DAY), DAY, 0, 62)

    assert looked_minutes(frames, fakes) == [0, 30, 60]


def test_a_dark_night_frame_is_never_sent_to_sam(conn, store, tmp_path, fakes):
    series(store, "kilauea-v1", T0, 0, 40, lava=False)  # night, no glow: the local checks reject it

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 40)

    assert fakes.looked == []


def test_an_episode_size_sighting_gets_the_very_next_frame_looked_at(conn, store, tmp_path, fakes):
    frames = series(store, "kilauea-v1", T0, 0, 12)
    fakes.sam = {frames[8]: LARGE}
    fakes.answer = OVERFLOW  # so no alert changes the cadence

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 12)

    assert looked_minutes(frames, fakes)[:3] == [0, 8, 10]


def test_a_step_never_sees_a_frame_captured_after_its_clock(conn, store, tmp_path, fakes):
    frames = series(store, "kilauea-v1", T0, 0, 20)

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 7)

    assert looked_minutes(frames, fakes) == [0]
    assert conn.execute("SELECT MAX(captured_at) FROM alert_checks").fetchone()[0] <= "2026-10-17T13:07:00Z"


def test_a_first_step_does_not_look_at_frames_older_than_ten_minutes(conn, store, tmp_path, fakes):
    frames = series(store, "kilauea-v1", T0, -40, 0)

    watcher(conn, tmp_path, fakes, V1_ONLY).step(T0)

    assert looked_minutes(frames, fakes) == [-8, 0]  # frames from 10 minutes back only, then the 8-minute cadence


def test_a_look_is_stored_with_its_box_mask_and_size_and_reported(conn, store, tmp_path, fakes):
    frame_id = add(store, "kilauea-v1", T0)
    fakes.sam = {frame_id: SMALL}

    report = watcher(conn, tmp_path, fakes, V1_ONLY).step(T0)

    row = conn.execute("SELECT * FROM alert_checks").fetchone()
    assert (row["frame_id"], row["camera_id"], row["clock"], row["size"], row["episode"]) == (
        frame_id, "kilauea-v1", "2026-10-17T13:00:00Z", "small", 0)
    assert (row["box_left"], row["box_top"], row["box_right"], row["box_bottom"]) == (10, 10, 50, 30)
    assert row["glow"] >= LAVA_GLOW and row["score"] == pytest.approx(0.8)
    assert report.looks == [{"camera_id": "kilauea-v1", "frame_id": frame_id, "captured_at": "2026-10-17T13:00:00Z",
                             "size": "small", "episode": False}]


def test_the_alerts_spend_under_a_tag_of_the_simulated_utc_day(conn, store, tmp_path, fakes):
    add(store, "kilauea-v1", T0)

    watcher(conn, tmp_path, fakes, V1_ONLY).step(T0)

    assert fakes.tags == ["alerts:2026-10-17"]


def test_a_spent_budget_stops_the_step_and_says_so(conn, store, tmp_path, fakes):
    add(store, "kilauea-v1", T0)
    fakes.raises = BudgetExceeded("budget $0.75 of alerts:2026-10-17 would be exceeded")

    report = watcher(conn, tmp_path, fakes, V1_ONLY).step(T0)

    assert report.errors == ["alerts stopped: budget $0.75 of alerts:2026-10-17 would be exceeded"]


def test_without_a_meta_client_nothing_is_looked_at(conn, store, tmp_path, fakes):
    add(store, "kilauea-v1", T0)
    w = AlertWatcher(context(conn, tmp_path, now=T0), "kilauea", V1_ONLY, tmp_path / "alerts", budget_usd=0.75,
                     segment=fakes.segment, compare=fakes.compare)

    report = w.step(T0)

    assert fakes.looked == [] and report.errors == ["no Meta client: SAM cannot look for a fountain"]


def episode(conn, store, tmp_path, fakes, *, large_from, none_from=None, k2=None, config=V1_ONLY, last=None):
    """V1 frames every 2 min from -40 to `last` minutes; SAM sees an episode-size fountain from `large_from` and
    nothing from `none_from`; K2 sightings per minute from `k2` ({minute: size or None}). The frames by camera."""
    last = last if last is not None else (none_from + 10 if none_from is not None else large_from + 10)
    v1 = series(store, "kilauea-v1", T0, -40, last)
    for minute, frame_id in v1.items():
        if minute >= large_from and (none_from is None or minute < none_from):
            fakes.sam[frame_id] = LARGE
        elif minute < large_from:
            fakes.sam[frame_id] = SMALL
    frames = {"kilauea-v1": v1}
    if k2 is not None:
        frames["kilauea-k2"] = series(store, "kilauea-k2", T0, -40, last)
        for minute, size in k2.items():
            if size is not None:
                fakes.sam[frames["kilauea-k2"][minute]] = size
    w = watcher(conn, tmp_path, fakes, config)
    run(w, T0, 0, last)
    return frames


def alerts_of(conn):
    return conn.execute("SELECT kind, camera_id, captured_at, seen_at, clock FROM alerts ORDER BY clock").fetchall()


def test_two_consecutive_episode_size_sightings_confirmed_by_muse_spark_raise_the_onset(conn, store, tmp_path, fakes):
    frames = episode(conn, store, tmp_path, fakes, large_from=6)

    # looks at 0 (small), 8 (large), the next frame 10 (large): Muse Spark compares 10 with the frame 30 min before
    assert [tuple(row) for row in alerts_of(conn)] == [
        ("onset", "kilauea-v1", "2026-10-17T13:10:00Z", "2026-10-17T13:08:00Z", "2026-10-17T13:10:00Z")]
    assert fakes.asked == [30]
    alert = load_alert(conn, 1)
    assert alert.seen_by == "kilauea-v1" and (tmp_path / alert.overlay).is_file()
    assert alert.disclaimer_en.startswith("Automated, experimental reading") and "usgs.gov" in alert.disclaimer_en


def test_overflow_size_sightings_all_night_raise_nothing_and_never_ask_muse_spark(conn, store, tmp_path, fakes):
    frames = series(store, "kilauea-v1", T0, -40, 120)
    fakes.sam = {frame_id: SMALL for frame_id in frames.values()}

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 120)

    assert alerts_of(conn) == [] and fakes.asked == []


def test_muse_spark_saying_overflow_holds_the_onset_back(conn, store, tmp_path, fakes):
    fakes.answer = OVERFLOW

    episode(conn, store, tmp_path, fakes, large_from=6)

    assert alerts_of(conn) == []
    assert conn.execute("SELECT episode FROM alert_checks WHERE spark IS NOT NULL").fetchone()["episode"] == 0


def test_an_ambiguous_size_is_settled_by_muse_spark_and_counts_toward_the_onset(conn, store, tmp_path, fakes):
    v1 = series(store, "kilauea-v1", T0, -40, 12)
    fakes.sam = {v1[0]: SMALL, v1[8]: AMBIGUOUS, v1[10]: LARGE}

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 12)

    assert fakes.asked == [30]  # once for the ambiguous look; it already confirmed the pair
    assert [row["kind"] for row in alerts_of(conn)] == ["onset"]


def test_one_episode_size_sighting_alone_raises_nothing(conn, store, tmp_path, fakes):
    v1 = series(store, "kilauea-v1", T0, -40, 20)
    fakes.sam = {v1[8]: LARGE}  # the next frame shows nothing

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 20)

    assert alerts_of(conn) == [] and fakes.asked == []


def test_two_misses_in_a_row_on_the_camera_that_saw_it_end_the_episode(conn, store, tmp_path, fakes):
    episode(conn, store, tmp_path, fakes, large_from=6, none_from=34, last=44)

    # onset at 10; looks every 6 min: 16, 22, 28 (sightings), 34 (miss), then the next frame 36 (miss)
    rows = [tuple(row) for row in alerts_of(conn)]
    assert rows[1] == ("end", "kilauea-v1", "2026-10-17T13:36:00Z", "2026-10-17T13:28:00Z", "2026-10-17T13:36:00Z")
    end = load_alert(conn, 2)
    # the test volcano has no UTC offset, so "local time" is UTC here
    assert "since 13:28 local time" in end.text_en and "It had lasted 20 min" in end.text_en


def test_a_single_miss_during_the_episode_does_not_end_it(conn, store, tmp_path, fakes):
    v1 = series(store, "kilauea-v1", T0, -40, 40)
    fakes.sam = {frame_id: (LARGE if minute >= 6 else SMALL) for minute, frame_id in v1.items()}
    fakes.sam[v1[22]] = (0, 0)

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 40)

    assert [row["kind"] for row in alerts_of(conn)] == ["onset"]
    assert looked_minutes(v1, fakes)[4:7] == [16, 22, 24]  # the miss gets the next frame looked at at once


def test_a_camera_that_still_sees_the_fountain_holds_the_end_back(conn, store, tmp_path, fakes):
    k2 = {minute: LARGE for minute in range(0, 61, 2)}  # K2 keeps seeing it all along

    episode(conn, store, tmp_path, fakes, large_from=6, none_from=34, k2=k2, config=CONFIG, last=60)

    assert [row["kind"] for row in alerts_of(conn)] == ["onset"]


def test_a_camera_that_never_saw_the_fountain_cannot_end_it(conn, store, tmp_path, fakes):
    k2 = {minute: None for minute in range(-40, 41, 2)}  # K2 sees nothing all along (night saturation)

    episode(conn, store, tmp_path, fakes, large_from=6, k2=k2, config=CONFIG, last=40)

    assert [row["kind"] for row in alerts_of(conn)] == ["onset"]


def test_a_camera_that_has_gone_blind_does_not_hold_the_end_back(conn, store, tmp_path, fakes):
    # K2 sees the fountain until minute 20, then its frames stop (fog rejects them, or the camera is down); V1 sees
    # it from 6 to 48 and nothing from 50
    v1 = series(store, "kilauea-v1", T0, -40, 70)
    k2 = series(store, "kilauea-k2", T0, -40, 20)
    fakes.sam = {**{frame_id: (LARGE if m >= 6 else SMALL) for m, frame_id in v1.items() if m < 50},
                 **{frame_id: LARGE for m, frame_id in k2.items() if m >= 0}}

    run(watcher(conn, tmp_path, fakes, CONFIG), T0, 0, 70)

    kinds = [row["kind"] for row in alerts_of(conn)]
    assert kinds == ["onset", "end"]
    end = conn.execute("SELECT * FROM alerts WHERE kind = 'end'").fetchone()
    assert end["camera_id"] == "kilauea-v1" and end["seen_at"] >= "2026-10-17T13:40:00Z"
    # K2 was blind: it is not named as having no fountain, since its last look (13:20) saw one
    text = load_alert(conn, 2).text_en
    assert "No lava fountain on kilauea-v1 since" in text and "kilauea-k2" not in text


def test_the_alerts_state_survives_a_new_watcher(conn, store, tmp_path, fakes):
    episode(conn, store, tmp_path, fakes, large_from=6, last=12)

    fresh = watcher(conn, tmp_path, fakes, V1_ONLY)

    assert fresh.state(T0 + 12 * M)[0] == "fountaining"
    assert fresh.state(T0 + 9 * M)[0] == "quiet"  # bounded by the clock: the onset was raised at 13:10


# --- the clock bounds, the error paths and the cadence's edges -------------------------------------------------------

API_ERROR = openai.APIConnectionError(request=httpx.Request("POST", "https://api.meta.ai/v1/responses"))
# rows a resumed replay leaves after the new clock: about a frame captured later, or made later (minutes after T0)
LATER = [pytest.param(30, 0, id="captured-after-the-clock"), pytest.param(-11, 30, id="made-after-the-clock")]


def put_look(conn, store, camera_id, minute, *, clock=None, size="none", episode=0):
    """An alert_checks row for a new frame captured `minute` minutes after T0, made at `clock` minutes after T0 (by
    default its capture time): what an earlier run, or a replay that is resumed, leaves in the table."""
    frame_id = add(store, camera_id, T0 + minute * M)
    made = T0 + (minute if clock is None else clock) * M
    with conn:
        conn.execute("INSERT INTO alert_checks (frame_id, camera_id, captured_at, clock, glow, size, episode) "
                     "VALUES (?, ?, ?, ?, 0.1, ?, ?)",
                     (frame_id, camera_id, to_iso(T0 + minute * M), to_iso(made), size, episode))
    return frame_id


def put_onset(conn):
    """The onset alert of a fountain first seen 20 minutes before T0 and raised 14 minutes before it."""
    return store_alert(conn, make_alert("onset", clock=to_iso(T0 - 14 * M), seen_at=to_iso(T0 - 20 * M)))


def fountaining(conn, store):
    """V1 saw the fountain from 20 to 12 minutes before T0 and missed it 6 minutes before."""
    put_onset(conn)
    put_look(conn, store, "kilauea-v1", -20, size="large", episode=1)
    put_look(conn, store, "kilauea-v1", -12, size="large", episode=1)
    put_look(conn, store, "kilauea-v1", -6)


def step_with_a_miss(conn, store, tmp_path, fakes):
    """A step at T0 whose new V1 frame shows no fountain."""
    add(store, "kilauea-v1", T0)
    return watcher(conn, tmp_path, fakes).step(T0)


def test_a_look_of_a_frame_captured_after_the_clock_does_not_hide_the_frame_of_the_clock(conn, store, tmp_path, fakes):
    put_look(conn, store, "kilauea-v1", 30, clock=0)
    frame_id = add(store, "kilauea-v1", T0)

    watcher(conn, tmp_path, fakes, V1_ONLY).step(T0)

    assert fakes.looked == [frame_id]


@pytest.mark.parametrize("captured, clock", LATER)
def test_a_large_look_after_the_clock_does_not_complete_an_onset_pair(conn, store, tmp_path, fakes, captured, clock):
    put_look(conn, store, "kilauea-v1", -12)  # the last look that exists at T0: it saw nothing
    put_look(conn, store, "kilauea-v1", captured, clock=clock, size="large", episode=1)
    frame_id = add(store, "kilauea-v1", T0)
    fakes.sam = {frame_id: LARGE}

    report = watcher(conn, tmp_path, fakes, V1_ONLY).step(T0)

    assert fakes.looked == [frame_id]
    assert report.alerts == [] and fakes.asked == []


@pytest.mark.parametrize("captured, clock", LATER)
def test_a_sighting_after_the_clock_does_not_hold_the_end_back(conn, store, tmp_path, fakes, captured, clock):
    fountaining(conn, store)
    put_look(conn, store, "kilauea-k2", -3)  # K2's one recent miss: had K2 seen this fountain, it would hold the end
    put_look(conn, store, "kilauea-k2", captured, clock=clock, size="large", episode=1)

    report = step_with_a_miss(conn, store, tmp_path, fakes)

    assert [a["kind"] for a in report.alerts] == ["end"]


@pytest.mark.parametrize("captured, clock", LATER)
def test_a_miss_after_the_clock_is_not_a_second_miss(conn, store, tmp_path, fakes, captured, clock):
    put_onset(conn)
    put_look(conn, store, "kilauea-v1", -20, size="large", episode=1)
    put_look(conn, store, "kilauea-v1", -12, size="large", episode=1)  # V1's last look at T0 saw the fountain
    put_look(conn, store, "kilauea-v1", captured, clock=clock)         # a miss that does not exist yet

    report = step_with_a_miss(conn, store, tmp_path, fakes)

    assert len(fakes.looked) == 1 and report.alerts == []  # the new miss is the first in a row


@pytest.mark.parametrize("captured, clock", LATER)
def test_the_end_names_the_fountains_last_sighting_as_of_the_clock(conn, store, tmp_path, fakes, captured, clock):
    fountaining(conn, store)
    put_look(conn, store, "kilauea-v1", captured, clock=clock, size="large", episode=1)

    report = step_with_a_miss(conn, store, tmp_path, fakes)

    assert [a["kind"] for a in report.alerts] == ["end"]
    assert conn.execute("SELECT seen_at FROM alerts WHERE kind = 'end'").fetchone()[0] == to_iso(T0 - 12 * M)


@pytest.mark.parametrize("captured, clock", [pytest.param(30, -8, id="captured-after-the-clock"),
                                             pytest.param(-9, 30, id="made-after-the-clock")])  # the step is at -6
def test_a_sighting_after_the_clock_does_not_make_a_miss_a_follow_up(conn, store, tmp_path, fakes, captured, clock):
    put_onset(conn)
    put_look(conn, store, "kilauea-v1", -8)  # V1 has not seen this fountain, and missed it at -8
    put_look(conn, store, "kilauea-v1", captured, clock=clock, size="large", episode=1)
    add(store, "kilauea-v1", T0 - 6 * M)

    watcher(conn, tmp_path, fakes, V1_ONLY).step(T0 - 6 * M)

    assert fakes.looked == []  # two minutes after the last look, while fountaining: not due


def test_muse_spark_never_compares_a_frame_with_one_captured_after_it(conn, store, tmp_path, fakes):
    v1 = series(store, "kilauea-v1", T0, 0, 4)  # the frame asked about is the oldest: nothing is earlier
    fakes.sam = {v1[0]: AMBIGUOUS}

    report = watcher(conn, tmp_path, fakes, V1_ONLY).step(T0)

    assert fakes.asked == []
    assert any("no earlier frame" in error for error in report.errors)


def test_two_cameras_that_both_missed_it_twice_are_both_named_in_the_end(conn, store, tmp_path, fakes):
    fountaining(conn, store)
    put_look(conn, store, "kilauea-k2", -14, size="large", episode=1)
    put_look(conn, store, "kilauea-k2", -5)
    put_look(conn, store, "kilauea-k2", -2)

    step_with_a_miss(conn, store, tmp_path, fakes)

    alert = load_alert(conn, 2)
    assert alert.kind == "end"
    assert "No lava fountain on kilauea-k2 and kilauea-v1 since 12:48 local time" in alert.text_en
    assert "Ninguna fuente de lava en kilauea-k2 y kilauea-v1 desde las 12:48" in alert.text_es


def test_a_failed_sam_call_is_reported_stores_no_look_and_is_not_retried_by_the_next_step(conn, store, tmp_path,
                                                                                         fakes):
    frames = series(store, "kilauea-v1", T0, 0, 4)
    w = watcher(conn, tmp_path, fakes, V1_ONLY)
    fakes.raises = API_ERROR

    first = w.step(T0)
    fakes.raises = None
    second = w.step(T0 + 1 * M)

    assert first.looks == [] and len(first.errors) == 1 and "APIConnectionError" in first.errors[0]
    assert f"frame {frames[0]}" in first.errors[0]
    assert conn.execute("SELECT COUNT(*) FROM alert_checks").fetchone()[0] == 0
    assert second.looks == [] and second.errors == [] and fakes.looked == []  # the failed frame is not tried again
    third = w.step(T0 + 2 * M)
    assert fakes.looked == [frames[2]] and len(third.looks) == 1  # the next frame is looked at


@pytest.mark.parametrize("error", [API_ERROR, ValueError("not JSON")], ids=["api-error", "value-error"])
def test_a_failing_muse_spark_call_holds_the_onset_back_and_is_asked_again_with_the_next_frame(
        conn, store, tmp_path, fakes, error):
    v1 = series(store, "kilauea-v1", T0, -40, 20)
    fakes.sam = {frame_id: (LARGE if minute >= 6 else SMALL) for minute, frame_id in v1.items()}
    fakes.compare_raises = error
    w = watcher(conn, tmp_path, fakes, V1_ONLY)

    reports = run(w, T0, 0, 10)

    assert alerts_of(conn) == []
    assert [e for report in reports for e in report.errors if "Muse Spark failed" in e]
    fakes.compare_raises = None
    run(w, T0, 11, 12)  # frame 12 is a follow-up of the episode-size look at 10: Muse Spark is asked again
    assert [tuple(row)[:3] for row in alerts_of(conn)] == [("onset", "kilauea-v1", "2026-10-17T13:12:00Z")]
    assert fakes.asked == [30, 30]


def test_a_look_is_stored_before_muse_spark_is_asked_so_a_failure_never_pays_sam_twice(conn, store, tmp_path, fakes):
    v1 = series(store, "kilauea-v1", T0, -40, 12)
    fakes.sam = {v1[8]: AMBIGUOUS}
    earlier = conn.execute("SELECT path FROM frames WHERE id = ?", (v1[-22],)).fetchone()[0]
    (tmp_path / earlier).unlink()  # the frame Muse Spark would compare with is unreadable

    reports = run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 12)

    row = conn.execute("SELECT size, spark, episode FROM alert_checks WHERE frame_id = ?", (v1[8],)).fetchone()
    assert tuple(row) == ("ambiguous", None, 0)
    assert fakes.looked.count(v1[8]) == 1
    assert any(f"frame {v1[8]}" in error for r in reports for error in r.errors)


def test_the_report_matches_the_stored_look_when_muse_spark_says_overflow(conn, store, tmp_path, fakes):
    v1 = series(store, "kilauea-v1", T0, -40, 12)
    fakes.sam = {frame_id: (LARGE if minute >= 6 else SMALL) for minute, frame_id in v1.items()}
    fakes.answer = OVERFLOW

    reports = run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 12)

    look = next(entry for r in reports for entry in r.looks if entry["frame_id"] == v1[10])
    stored = conn.execute("SELECT episode FROM alert_checks WHERE frame_id = ?", (v1[10],)).fetchone()[0]
    assert (look["episode"], stored) == (False, 0)


def test_the_budget_tag_is_the_utc_day_of_a_clock_in_another_zone(conn, store, tmp_path, fakes):
    now = datetime(2026, 10, 17, 20, 0, tzinfo=timezone(timedelta(hours=-10)))  # 2026-10-18 06:00 UTC
    add(store, "kilauea-v1", now)

    watcher(conn, tmp_path, fakes, V1_ONLY, now=now).step(now)

    assert fakes.tags == ["alerts:2026-10-18"]


def test_a_step_refuses_a_clock_without_a_time_zone(conn, tmp_path, fakes):
    with pytest.raises(ValueError, match="time zone"):
        watcher(conn, tmp_path, fakes, V1_ONLY).step(datetime(2026, 10, 17, 13, 0))


@pytest.mark.parametrize("gap, kinds", [(10, ["onset"]), (12, [])])
def test_two_episode_size_looks_make_an_onset_only_when_at_most_ten_minutes_apart(conn, store, tmp_path, fakes, gap,
                                                                                   kinds):
    first = add(store, "kilauea-v1", T0)
    second, third = add(store, "kilauea-v1", T0 + 8 * M), add(store, "kilauea-v1", T0 + (8 + gap) * M)
    fakes.sam = {first: SMALL, second: LARGE, third: LARGE}

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 8 + gap)

    assert [row["kind"] for row in alerts_of(conn)] == kinds


@pytest.mark.parametrize("seconds, looks", [(419, 1), (420, 2)])
def test_a_frame_seven_minutes_after_the_last_look_is_due_but_not_one_second_earlier(conn, store, tmp_path, fakes,
                                                                                      seconds, looks):
    add(store, "kilauea-v1", T0)
    late = T0 + timedelta(seconds=seconds)
    add(store, "kilauea-v1", late)
    w = watcher(conn, tmp_path, fakes, V1_ONLY)

    w.step(T0)
    w.step(late)

    assert len(fakes.looked) == looks


# --- posting and the command line ------------------------------------------------------------------------------------


class FakeTelegram:
    def __init__(self, fail=False):
        self.posts, self.fail = [], fail

    def send_photo(self, photo, text):
        if self.fail:
            raise TelegramError("sendPhoto: 500 Internal Server Error")
        self.posts.append((photo, text))
        return len(self.posts)


def stored(conn, tmp_path, clock="2026-11-02T13:08:00Z"):
    (tmp_path / "alerts" / "x").mkdir(parents=True, exist_ok=True)
    (tmp_path / "alerts" / "x" / "frame1.jpg").write_bytes(b"\xff\xd8jpeg")
    return store_alert(conn, make_alert(clock=clock, overlay="alerts/x/frame1.jpg"))


NOW = datetime(2026, 11, 2, 13, 9, tzinfo=timezone.utc)


def test_a_new_alert_is_posted_once_with_its_frame_and_caption(conn, tmp_path):
    alert = stored(conn, tmp_path)
    telegram = FakeTelegram()

    assert send_pending(conn, telegram, tmp_path, NOW) == []
    assert send_pending(conn, telegram, tmp_path, NOW) == []

    assert telegram.posts == [(b"\xff\xd8jpeg", caption(alert))]
    assert conn.execute("SELECT sent_at FROM alerts").fetchone()[0] == "2026-11-02T13:09:00Z"


def test_a_failed_post_is_tried_again_and_given_up_after_five_attempts(conn, tmp_path):
    stored(conn, tmp_path)
    telegram = FakeTelegram(fail=True)

    errors = [send_pending(conn, telegram, tmp_path, NOW) for _ in range(MAX_SEND_ATTEMPTS + 2)]

    assert [len(e) for e in errors] == [1] * MAX_SEND_ATTEMPTS + [0, 0]
    row = conn.execute("SELECT sent_at, send_attempts, send_error FROM alerts").fetchone()
    assert (row[0], row[1]) == (None, MAX_SEND_ATTEMPTS) and "500" in row[2]


def test_an_alert_older_than_two_hours_is_never_posted(conn, tmp_path):
    stored(conn, tmp_path, clock="2026-11-02T10:00:00Z")
    telegram = FakeTelegram()

    send_pending(conn, telegram, tmp_path, NOW)

    assert telegram.posts == []


def test_alerts_are_posted_oldest_first_so_an_end_never_precedes_its_onset(conn, tmp_path):
    (tmp_path / "alerts" / "x").mkdir(parents=True)
    (tmp_path / "alerts" / "x" / "frame1.jpg").write_bytes(b"\xff\xd8jpeg")
    end = make_alert("end", clock="2026-11-02T13:08:00Z")  # stored first, so it has the lower id
    onset = make_alert("onset", clock="2026-11-02T12:30:00Z")
    store_alert(conn, end)
    store_alert(conn, onset)
    telegram = FakeTelegram()

    send_pending(conn, telegram, tmp_path, NOW)

    assert [text for _, text in telegram.posts] == [caption(onset), caption(end)]


class RefusingTelegram(FakeTelegram):
    """Refuses its first post as Telegram.send_photo does a caption over the limit."""

    def __init__(self):
        super().__init__()
        self.refused = False

    def send_photo(self, photo, text):
        if not self.refused:
            self.refused = True
            raise ValueError("caption is 1100 characters; Telegram's limit is 1024")
        return super().send_photo(photo, text)


def test_a_post_refused_with_a_value_error_counts_as_an_attempt_and_does_not_block_newer_alerts(conn, tmp_path):
    stored(conn, tmp_path, clock="2026-11-02T12:30:00Z")
    newer = stored(conn, tmp_path, clock="2026-11-02T13:08:00Z")
    telegram = RefusingTelegram()

    errors = send_pending(conn, telegram, tmp_path, NOW)

    assert len(errors) == 1 and "1024" in errors[0]
    assert telegram.posts == [(b"\xff\xd8jpeg", caption(newer))]
    assert conn.execute("SELECT send_attempts, sent_at FROM alerts ORDER BY clock").fetchall()[0][:] == (1, None)


def test_a_stored_body_that_no_longer_validates_counts_as_an_attempt_and_does_not_block_newer_alerts(conn, tmp_path):
    stored(conn, tmp_path, clock="2026-11-02T12:30:00Z")
    stored(conn, tmp_path, clock="2026-11-02T13:08:00Z")
    with conn:
        conn.execute("UPDATE alerts SET body = '{}' WHERE clock = '2026-11-02T12:30:00Z'")
    telegram = FakeTelegram()

    errors = send_pending(conn, telegram, tmp_path, NOW)

    assert len(errors) == 1 and len(telegram.posts) == 1
    assert conn.execute("SELECT send_attempts FROM alerts ORDER BY clock").fetchall()[0][0] == 1


def test_a_replays_alerts_are_posted_oldest_first_each_marked_as_a_replay(tmp_path):
    folder = tmp_path / "replay" / "ep55"
    (tmp_path / "alerts" / "x").mkdir(parents=True)
    (tmp_path / "alerts" / "x" / "frame1.jpg").write_bytes(b"\xff\xd8jpeg")
    with closing(db.connect(folder / "vigil.sqlite")) as replay:
        store_alert(replay, make_alert("end", clock="2026-10-17T19:00:00Z", overlay="alerts/x/frame1.jpg"))
        store_alert(replay, make_alert("onset", clock="2026-10-17T13:08:00Z", overlay="alerts/x/frame1.jpg"))
    telegram = FakeTelegram()

    ids = post_replay(tmp_path, "55", telegram)

    assert ids == [1, 2]
    assert [text.splitlines()[2] for _, text in telegram.posts] == [
        make_alert("onset").headline_en, make_alert("end").headline_en]
    assert all(text.startswith("REPLAY of episode 55 (2026-10-17): not a live alert.") for _, text in telegram.posts)


def test_cli_refuses_an_alert_camera_that_is_not_enabled(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("vigil.settings.load_dotenv", lambda: None)
    sources = tmp_path / "sources.yaml"
    sources.write_text(
        "volcanoes:\n  kilauea: {name: Kilauea, country: US, official_agency: HVO, official_url: 'https://x'}\n"
        "cameras:\n  - {id: kilauea-k2, name: K2cam, volcano: kilauea, url: 'https://x/k2.jpg',\n"
        "     license: PD, attribution: USGS, enabled: true}\n", encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("ALERTS_PATH", str(ROOT / "config" / "alerts.yaml"))  # watches kilauea-v1 too

    with pytest.raises(SystemExit):
        main(["--volcano", "kilauea", "--once"])

    assert "kilauea-v1" in capsys.readouterr().err


def test_cli_posts_through_the_relay_in_telegram_api_url(monkeypatch, tmp_path):
    # Hugging Face Spaces cannot reach api.telegram.org, so the Space posts through a relay
    monkeypatch.setattr("vigil.settings.load_dotenv", lambda: None)
    for name, value in {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "@volcano_vigil",
                        "TELEGRAM_API_URL": "https://vigil-telegram.example.workers.dev",
                        "SOURCES_PATH": str(ROOT / "config" / "sources.yaml"),
                        "ALERTS_PATH": str(ROOT / "config" / "alerts.yaml"), "DATA_DIR": str(tmp_path),
                        "DB_PATH": str(tmp_path / "vigil.sqlite")}.items():
        monkeypatch.setenv(name, value)
    apis = []

    class Stop(Exception):
        pass

    def check(self):
        apis.append(self._api)
        raise Stop

    monkeypatch.setattr("vigil.alerts.Telegram.check", check)

    with pytest.raises(Stop):
        main(["--volcano", "kilauea", "--once"])

    assert apis == ["https://vigil-telegram.example.workers.dev"]
