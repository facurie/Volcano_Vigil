from datetime import datetime, timedelta, timezone

import pytest

from conftest import NOW, make_jpeg
from vigia.ingest.store import FrameStore

CAPTURED = datetime(2026, 10, 17, 14, 50, 5, tzinfo=timezone.utc)


@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def add(store, body, captured_at=CAPTURED, source="ashcam", camera_id="kilauea-kp"):
    return store.add(camera_id, body, captured_at=captured_at, timestamp_source=source, fetched_at=NOW)


def test_add_writes_the_file_and_returns_the_new_frame_id(store, conn, tmp_path):
    body = make_jpeg()

    frame_id = add(store, body)

    row = conn.execute("SELECT * FROM frames WHERE id = ?", (frame_id,)).fetchone()
    assert (row["captured_at"], row["timestamp_source"]) == ("2026-10-17T14:50:05Z", "ashcam")
    assert (tmp_path / row["path"]).read_bytes() == body


def test_add_returns_none_for_bytes_the_camera_already_has(store):
    body = make_jpeg()
    add(store, body)

    assert add(store, body, captured_at=CAPTURED + timedelta(minutes=5)) is None


def test_add_rejects_a_body_that_is_not_an_image(store):
    with pytest.raises(ValueError, match="image"):
        add(store, b"<html>not found</html>")


def test_has_capture_matches_camera_time_and_timestamp_source(store):
    add(store, make_jpeg())

    assert store.has_capture("kilauea-kp", CAPTURED, "ashcam")
    assert not store.has_capture("kilauea-kp", CAPTURED, "http_last_modified")
    assert not store.has_capture("kilauea-k2", CAPTURED, "ashcam")


def test_latest_capture_is_the_newest_frame_from_that_source(store):
    add(store, make_jpeg(color=(200, 80, 40)), captured_at=CAPTURED)
    add(store, make_jpeg(color=(40, 200, 80)), captured_at=CAPTURED + timedelta(minutes=5))
    add(store, make_jpeg(color=(80, 40, 200)), captured_at=CAPTURED + timedelta(hours=1), source="http_last_modified")

    assert store.latest_capture("kilauea-kp", "ashcam") == CAPTURED + timedelta(minutes=5)
    assert store.latest_capture("kilauea-k2", "ashcam") is None
