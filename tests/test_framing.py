import hashlib
import io
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from PIL import Image

from conftest import make_textured_jpeg
from vigil import masks
from vigil.calibration import Framing, FramingReference, Preset
from vigil.framing import FOOT_PX, MAX_SHIFT, MIN_PEAK, FramingGuard, foot, match, signature
from vigil.ingest.store import FrameStore

FRAMING = Framing(references=[FramingReference(path="refs/day.jpg", sha256="0" * 64)], rows_from=0.5,
                  skip_columns=(0.4, 0.6))


def image(**kwargs):
    return Image.open(io.BytesIO(make_textured_jpeg(**kwargs)))


def compare(reference, frame):
    return match(signature(reference, FRAMING)[0], signature(frame, FRAMING)[0])


def test_a_frame_keeps_its_own_framing():
    found = compare(image(seed=1), image(seed=1))

    assert found.same and (found.dx, found.dy) == (0, 0) and found.peak > 0.5


def test_a_shift_within_max_shift_keeps_the_framing():
    assert compare(image(seed=1), image(seed=1, shift=(MAX_SHIFT, -1))).same


def test_a_shift_beyond_max_shift_does_not_and_is_measured():
    found = compare(image(seed=1), image(seed=1, shift=(0, 6)))

    assert not found.same
    assert abs(found.dy) == 6 and found.dx == 0


@pytest.mark.parametrize("zoom", [1.05, 0.95])
def test_a_zoom_does_not_keep_the_framing(zoom):
    assert not compare(image(seed=1), image(seed=1, zoom=zoom)).same


def test_another_scene_does_not_keep_the_framing():
    found = compare(image(seed=1), image(seed=2))

    assert not found.same and found.peak < MIN_PEAK


def test_rows_above_rows_from_and_the_skipped_columns_are_left_out():
    reference = np.asarray(image(seed=1)).copy()
    frame = reference.copy()
    frame[:250] = 255                    # the sky: above rows_from (0.5 of 540 rows)
    frame[300:, 400:560] = 0             # inside skip_columns (0.4-0.6 of 960 columns): the vent
    found = match(signature(Image.fromarray(reference), FRAMING)[0], signature(Image.fromarray(frame), FRAMING)[0])

    assert found.same and found.peak > 0.5


def test_signature_gives_the_mean_brightness():
    _, bright = signature(image(seed=1, brightness=0.2), FRAMING)

    assert 15 < bright < 35


def test_a_masks_foot_is_the_middle_of_its_lowest_rows():
    mask = np.zeros((50, 40), dtype=bool)
    mask[0:50, 18:22] = True             # the jet
    mask[48:50, 10:30] = True            # its spreading base

    assert foot(mask, left=100, top=200).tolist() == pytest.approx([100 + 19.5, 200 + 49])


def test_an_empty_mask_has_no_foot():
    assert foot(np.zeros((5, 5), dtype=bool), 0, 0) is None


T0 = datetime(2026, 11, 3, 14, 0, 2, tzinfo=timezone.utc)
VENT = np.array([480.0, 500.0])
CAMERA = "kilauea-k2"


def live_preset(tmp_path, references=(("refs/day.jpg", 1, 1.0), ("refs/night.jpg", 1, 0.15))):
    refs = []
    for path, seed, brightness in references:
        data = make_textured_jpeg(seed=seed, brightness=brightness)
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(data)
        refs.append(FramingReference(path=path, sha256=hashlib.sha256(data).hexdigest()))
    return Preset(name="live", valid_from="2026-10-18T00:00:00Z", image_size=(960, 540),
                  framing=Framing(references=refs, rows_from=0.5, skip_columns=(0.4, 0.6)))


@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def add_frame(conn, store, minutes, camera=CAMERA, **texture):
    captured_at = T0 + timedelta(minutes=minutes)
    frame_id = store.add(camera, make_textured_jpeg(**texture), captured_at=captured_at, timestamp_source="ashcam",
                         fetched_at=captured_at)
    return conn.execute("SELECT * FROM frames WHERE id = ?", (frame_id,)).fetchone()


def add_fountain(conn, frame, foot_at):
    """A fountain detection on the frame whose foot is at `foot_at` (column, row)."""
    left, bottom = int(foot_at[0]) - 10, int(foot_at[1])
    mask = np.ones((100, 21), dtype=bool)
    with conn:
        run_id = conn.execute(
            """INSERT INTO tracking_runs (camera_id, target, phrase, window_start, window_end, frame_ids,
                                          video_width, video_height, created_at)
               VALUES (?, 'fountain', 'lava fountain', ?, ?, ?, 960, 540, '2026-11-03T15:00:00Z')""",
            (CAMERA, frame["captured_at"], frame["captured_at"], json.dumps([frame["id"]]))).lastrowid
        track_id = conn.execute(
            "INSERT INTO tracks (run_id, object_id, first_seen, last_seen, detections) VALUES (?, '0', ?, ?, 1)",
            (run_id, frame["captured_at"], frame["captured_at"])).lastrowid
        conn.execute(
            """INSERT INTO detections (track_id, frame_id, box_left, box_top, box_right, box_bottom, score, area_px,
                                       mask_rle) VALUES (?, ?, ?, ?, ?, ?, 0.8, ?, ?)""",
            (track_id, frame["id"], left, bottom - 99, left + 21, bottom + 1, int(mask.sum()),
             json.dumps(masks.encode(mask))))


def guard(conn, tmp_path):
    return FramingGuard(conn, tmp_path, CAMERA)


def test_a_daylight_frame_of_the_reference_scene_keeps_the_framing(conn, store, tmp_path):
    frame = add_frame(conn, store, 0, seed=1)

    assert guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_dark_frame_matching_the_night_reference_keeps_the_framing(conn, store, tmp_path):
    frame = add_frame(conn, store, 0, seed=1, brightness=0.15)

    assert guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_moved_daylight_frame_does_not_even_with_a_fountain_on_the_vent(conn, store, tmp_path):
    add_frame(conn, store, -10, seed=1)
    frame = add_frame(conn, store, 0, seed=1, shift=(0, 20))
    add_fountain(conn, frame, VENT)

    assert not guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_dark_unmatched_frame_with_the_fountain_on_the_vent_follows_a_confirmed_frame(conn, store, tmp_path):
    add_frame(conn, store, -90, seed=1)                       # confirmed, 1.5 h before
    frame = add_frame(conn, store, 0, seed=7, brightness=0.15)  # the fountain's light: no reference matches
    add_fountain(conn, frame, VENT + (30, -5))

    assert guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_confirmed_frame_older_than_inherit_does_not_vouch(conn, store, tmp_path):
    add_frame(conn, store, -130, seed=1)                      # 2 h 10 min before
    frame = add_frame(conn, store, 0, seed=7, brightness=0.15)
    add_fountain(conn, frame, VENT)

    assert not guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_confirmed_frame_after_the_frame_does_not_vouch(conn, store, tmp_path):
    frame = add_frame(conn, store, 0, seed=7, brightness=0.15)
    add_fountain(conn, frame, VENT)
    add_frame(conn, store, 10, seed=1)                        # later than the frame: never looked at

    assert not guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_fountain_foot_off_the_vent_does_not_keep_the_framing(conn, store, tmp_path):
    add_frame(conn, store, -30, seed=1)
    frame = add_frame(conn, store, 0, seed=7, brightness=0.15)
    add_fountain(conn, frame, VENT + (FOOT_PX + 20, 0))

    assert not guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_confirmed_frame_of_another_camera_does_not_vouch(conn, store, tmp_path):
    add_frame(conn, store, -30, camera="kilauea-kp", seed=1)  # would be confirmed by the reference
    frame = add_frame(conn, store, 0, seed=7, brightness=0.15)
    add_fountain(conn, frame, VENT)

    assert not guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_dark_unmatched_frame_without_a_fountain_does_not_keep_the_framing(conn, store, tmp_path):
    add_frame(conn, store, -30, seed=1)
    frame = add_frame(conn, store, 0, seed=7, brightness=0.15)

    assert not guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_missing_reference_frame_is_an_error(conn, store, tmp_path):
    preset = live_preset(tmp_path)
    (tmp_path / "refs/night.jpg").unlink()

    with pytest.raises(ValueError, match="refs/night.jpg"):
        guard(conn, tmp_path).keeps(preset, add_frame(conn, store, 0, seed=1), VENT)


def test_a_reference_frame_with_another_hash_is_an_error(conn, store, tmp_path):
    preset = live_preset(tmp_path)
    (tmp_path / "refs/day.jpg").write_bytes(make_textured_jpeg(seed=3))

    with pytest.raises(ValueError, match="refs/day.jpg"):
        guard(conn, tmp_path).keeps(preset, add_frame(conn, store, 0, seed=1), VENT)


def test_a_missing_frame_file_does_not_keep_the_framing(conn, store, tmp_path):
    frame = add_frame(conn, store, 0, seed=1)
    (tmp_path / frame["path"]).unlink()

    assert not guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)
