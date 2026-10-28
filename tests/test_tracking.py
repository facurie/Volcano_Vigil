import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from conftest import make_jpeg
from vigia import masks
from vigia.ingest.store import FrameStore
from vigia.tracking import detection_mask, unassessed_frames, usable_frames

T0 = datetime(2026, 10, 17, 18, 0, 2, tzinfo=timezone.utc)


@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def add_frame(store, conn, minutes, usable=True, size=(64, 48), camera_id="kilauea-k2"):
    """Store a frame `minutes` after T0 with a quality verdict (usable=None: no verdict yet)."""
    frame_id = store.add(camera_id, make_jpeg(color=(10 + 3 * minutes, 80, 40), size=size),
                         captured_at=T0 + timedelta(minutes=minutes), timestamp_source="ashcam", fetched_at=T0)
    if usable is not None:
        conn.execute(
            """INSERT INTO frame_quality (frame_id, assessed_at, usable, decided_by, local_decision, reasons,
                                          brightness, contrast, edge_density, glow_fraction)
               VALUES (?, '2026-10-28T00:00:00Z', ?, 'local', ?, '[]', 100, 40, 0.1, 0)""",
            (frame_id, int(usable), "pass" if usable else "reject"),
        )
        conn.commit()
    return frame_id


def test_the_database_has_tracking_tables(conn):
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert {"tracking_runs", "tracks", "detections"} <= tables


def test_usable_frames_keeps_the_cameras_usable_frames_in_the_window_oldest_first(store, conn, tmp_path):
    later, first, middle = (add_frame(store, conn, minutes) for minutes in (4, 0, 2))
    add_frame(store, conn, 6, usable=False)
    add_frame(store, conn, 8, usable=None)
    add_frame(store, conn, 10)  # after the window
    add_frame(store, conn, 2, camera_id="kilauea-kp")

    frames = usable_frames(conn, tmp_path, "kilauea-k2", T0, T0 + timedelta(minutes=9))

    assert [f.id for f in frames] == [first, middle, later]
    assert frames[0].captured_at == T0
    assert frames[0].path.is_file() and (frames[0].width, frames[0].height) == (64, 48)


def test_unassessed_frames_counts_frames_without_a_verdict(store, conn):
    add_frame(store, conn, 0)
    add_frame(store, conn, 2, usable=None)
    add_frame(store, conn, 4, usable=None)

    assert unassessed_frames(conn, "kilauea-k2", T0, T0 + timedelta(minutes=5)) == 2


def test_detection_mask_places_the_box_mask_in_the_frame():
    box_mask = np.zeros((3, 4), dtype=bool)
    box_mask[1, 1:3] = True
    detection = {"id": 1, "box_left": 10, "box_top": 5, "box_right": 14, "box_bottom": 8,
                 "mask_rle": json.dumps(masks.encode(box_mask))}

    full = detection_mask(detection, width=20, height=10)

    assert full.shape == (10, 20) and full.sum() == 2
    assert full[6, 11] and full[6, 12]


def test_detection_mask_refuses_a_mask_that_does_not_fit_its_box():
    detection = {"id": 7, "box_left": 0, "box_top": 0, "box_right": 4, "box_bottom": 4,
                 "mask_rle": json.dumps(masks.encode(np.ones((3, 4), dtype=bool)))}

    with pytest.raises(ValueError, match="detection 7"):
        detection_mask(detection, width=10, height=10)
