import hashlib

import httpx
import pytest

from conftest import CAM_URL, NOW, make_jpeg, make_noisy_jpeg
from vigia.ingest.fetch import Ingestor
from vigia.ingest.store import FrameStore

LAST_MODIFIED = "Mon, 26 Oct 2026 18:25:00 GMT"


@pytest.fixture
def ingestor(conn, server, tmp_path):
    return Ingestor(FrameStore(conn, tmp_path), http=server.client(), now=lambda: NOW)


def frames(conn):
    return conn.execute("SELECT * FROM frames ORDER BY id").fetchall()


def state(conn, camera_id="kilauea-v1"):
    return conn.execute("SELECT * FROM camera_state WHERE camera_id = ?", (camera_id,)).fetchone()


def test_new_image_is_saved_to_disk_and_database(ingestor, server, camera, conn, tmp_path):
    body = make_jpeg()
    server.add(CAM_URL, body=body, headers={"Last-Modified": LAST_MODIFIED})

    result = ingestor.ingest(camera)

    assert result.status == "new"
    [row] = frames(conn)
    assert row["id"] == result.frame_id
    assert row["camera_id"] == "kilauea-v1"
    assert row["sha256"] == hashlib.sha256(body).hexdigest()
    assert (row["width"], row["height"], row["bytes"]) == (64, 48, len(body))
    assert (tmp_path / row["path"]).read_bytes() == body


def test_frame_path_is_relative_and_organized_by_camera_and_day(ingestor, server, camera, conn):
    server.add(CAM_URL, body=make_jpeg(), headers={"Last-Modified": LAST_MODIFIED})

    ingestor.ingest(camera)

    [row] = frames(conn)
    assert row["path"].startswith("frames/kilauea-v1/2026-10-26/20261026T182500Z_")
    assert row["path"].endswith(".jpg")


def test_captured_at_comes_from_last_modified_header(ingestor, server, camera, conn):
    server.add(CAM_URL, body=make_jpeg(), headers={"Last-Modified": LAST_MODIFIED})

    ingestor.ingest(camera)

    [row] = frames(conn)
    assert row["captured_at"] == "2026-10-26T18:25:00Z"
    assert row["timestamp_source"] == "http_last_modified"
    assert row["fetched_at"] == "2026-10-26T18:30:05Z"


def test_captured_at_falls_back_to_fetch_time_without_last_modified(ingestor, server, camera, conn):
    server.add(CAM_URL, body=make_jpeg())

    ingestor.ingest(camera)

    [row] = frames(conn)
    assert row["captured_at"] == "2026-10-26T18:30:05Z"
    assert row["timestamp_source"] == "fetched_at"


def test_identical_image_is_discarded_as_duplicate(ingestor, server, camera, conn, tmp_path):
    body = make_jpeg()
    server.add(CAM_URL, body=body, headers={"Last-Modified": LAST_MODIFIED})
    server.add(CAM_URL, body=body, headers={"Last-Modified": "Mon, 26 Oct 2026 18:35:00 GMT"})

    ingestor.ingest(camera)
    result = ingestor.ingest(camera)

    assert result.status == "duplicate"
    assert len(frames(conn)) == 1
    assert len(list((tmp_path / "frames").rglob("*.jpg"))) == 1


def test_stored_validators_are_sent_and_304_means_not_modified(ingestor, server, camera, conn):
    server.add(CAM_URL, body=make_jpeg(), headers={"Last-Modified": LAST_MODIFIED, "ETag": '"abc"'})
    server.add(CAM_URL, status=304)

    ingestor.ingest(camera)
    result = ingestor.ingest(camera)

    second = server.requests[1]
    assert second.headers["If-None-Match"] == '"abc"'
    assert second.headers["If-Modified-Since"] == LAST_MODIFIED
    assert result.status == "not_modified"
    assert len(frames(conn)) == 1


def test_camera_state_tracks_new_and_unchanged_frames(ingestor, server, camera, conn):
    body = make_jpeg()
    server.add(CAM_URL, body=body, headers={"Last-Modified": LAST_MODIFIED})
    server.add(CAM_URL, body=body)

    ingestor.ingest(camera)
    ingestor.ingest(camera)

    row = state(conn)
    assert row["last_status"] == "duplicate"
    assert row["last_new_frame_at"] == "2026-10-26T18:30:05Z"
    assert row["consecutive_unchanged"] == 1
    assert row["consecutive_errors"] == 0


def test_http_error_is_recorded_without_raising(ingestor, server, camera, conn):
    server.add(CAM_URL, status=503)

    result = ingestor.ingest(camera)

    assert result.status == "error"
    assert "503" in result.error
    row = state(conn)
    assert row["last_status"] == "error"
    assert row["consecutive_errors"] == 1
    assert "503" in row["last_error"]


def test_network_failure_is_recorded_without_raising(ingestor, server, camera, conn):
    server.add(CAM_URL, exc=httpx.ConnectTimeout("timed out"))

    result = ingestor.ingest(camera)

    assert result.status == "error"
    assert state(conn)["consecutive_errors"] == 1


def test_body_that_is_not_an_image_is_rejected(ingestor, server, camera, conn):
    server.add(CAM_URL, body=b"<html>down for maintenance</html>", headers={"Content-Type": "text/html"})

    result = ingestor.ingest(camera)

    assert result.status == "error"
    assert frames(conn) == []


def test_truncated_jpeg_is_rejected(ingestor, server, camera, conn):
    body = make_noisy_jpeg()
    server.add(CAM_URL, body=body[: len(body) // 2])

    result = ingestor.ingest(camera)

    assert result.status == "error"
    assert frames(conn) == []
