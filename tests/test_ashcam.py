import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from conftest import make_jpeg
from vigil.config import Camera
from vigil.ingest.ashcam import AshcamClient, AshcamIngestor, ChecksumMismatch, IndexFormatError, backfill, main
from vigil.ingest.store import FrameStore

INDEX = Path(__file__).parent / "fixtures" / "ashcam_index_kp.json"
START = datetime(2026, 10, 17, 14, 50, tzinfo=timezone.utc)  # 04:50 HST
END = datetime(2026, 10, 17, 15, 1, tzinfo=timezone.utc)
COLORS = [(200, 80, 40), (40, 200, 80), (80, 40, 200)]


class FakeAshcam:
    """Serves the trimmed KP index with a distinct small JPEG per image, and records every request."""

    def __init__(self):
        self.index = json.loads(INDEX.read_text(encoding="utf-8"))
        self.bodies = {}
        for item, color in zip(self.index["images"], COLORS):
            body = make_jpeg(color=color)
            item["md5"] = hashlib.md5(body).hexdigest()
            self.bodies[item["imageUrl"]] = body
        self.list_status = 200
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/imageApi/webcam"):
            return httpx.Response(self.list_status, json=self.index)
        body = self.bodies.get(str(request.url))
        return httpx.Response(200, content=body) if body is not None else httpx.Response(404)

    def list_requests(self):
        return [r for r in self.requests if r.url.path.endswith("/imageApi/webcam")]

    def image_requests(self):
        return [r for r in self.requests if r.url.path.endswith(".jpg")]


@pytest.fixture
def archive():
    return FakeAshcam()


@pytest.fixture
def client(archive):
    return AshcamClient(httpx.Client(transport=httpx.MockTransport(archive)))


def test_list_images_asks_for_the_camera_and_window_in_epoch_seconds(client, archive):
    client.list_images("kilauea-kp-cam", START, END)

    [request] = archive.list_requests()
    assert request.url.path == "/ashcam-api/imageApi/webcam"
    assert dict(request.url.params) == {
        "webcamCode": "kilauea-kp-cam", "startTimestamp": "1792248600", "endTimestamp": "1792249260",
        "order": "ASC", "limit": "0",
    }


def test_list_images_returns_exact_capture_times_oldest_first(client):
    images = client.list_images("kilauea-kp-cam", START, END)

    assert [i.timestamp for i in images] == [
        datetime(2026, 10, 17, 14, 50, 5, tzinfo=timezone.utc),
        datetime(2026, 10, 17, 14, 55, 5, tzinfo=timezone.utc),
        datetime(2026, 10, 17, 15, 0, 5, tzinfo=timezone.utc),
    ]
    assert images[0].webcam_code == "kilauea-kp-cam"
    assert images[0].url.endswith("/kilauea-kp-cam-1792248605.jpg")


def test_list_images_raises_when_the_archive_fails(client, archive):
    archive.list_status = 503

    with pytest.raises(httpx.HTTPStatusError):
        client.list_images("kilauea-kp-cam", START, END)


def test_list_images_reports_an_index_without_the_expected_fields(client, archive):
    archive.index = {"frames": []}

    with pytest.raises(IndexFormatError, match="KeyError"):
        client.list_images("kilauea-kp-cam", START, END)


def test_list_images_reports_a_field_of_an_unexpected_type(client, archive):
    archive.index["images"][0]["imageTimestamp"] = "yesterday"

    with pytest.raises(IndexFormatError, match="TypeError"):
        client.list_images("kilauea-kp-cam", START, END)


def test_fetch_returns_the_image_when_its_md5_matches(client, archive):
    image = client.list_images("kilauea-kp-cam", START, END)[0]

    assert client.fetch(image) == archive.bodies[image.url]


def test_fetch_rejects_an_image_whose_md5_does_not_match(client, archive):
    image = client.list_images("kilauea-kp-cam", START, END)[0]
    archive.bodies[image.url] = b"truncated"

    with pytest.raises(ChecksumMismatch, match="MD5"):
        client.fetch(image)


@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def kp_camera():
    return Camera(id="kilauea-kp", name="KPcam", volcano="kilauea", url="https://example.org/KPcam/images/M.jpg",
                  license="Public Domain", attribution="U.S. Geological Survey", ashcam_code="kilauea-kp-cam")


def stored(conn):
    return conn.execute("SELECT * FROM frames ORDER BY captured_at").fetchall()


def test_backfill_stores_each_frame_with_its_exact_ashcam_time(client, store, archive, conn, tmp_path):
    report = backfill(client, store, kp_camera(), START, END)

    rows = stored(conn)
    assert (report.listed, report.new) == (3, 3)
    assert [r["captured_at"] for r in rows] == ["2026-10-17T14:50:05Z", "2026-10-17T14:55:05Z", "2026-10-17T15:00:05Z"]
    assert {r["timestamp_source"] for r in rows} == {"ashcam"}
    assert {(tmp_path / r["path"]).read_bytes() for r in rows} == set(archive.bodies.values())
    assert report.frame_ids == [r["id"] for r in rows]


def test_backfill_skips_frames_it_already_stored_without_downloading_them(client, store, archive):
    backfill(client, store, kp_camera(), START, END)
    downloads = len(archive.image_requests())

    report = backfill(client, store, kp_camera(), START, END)

    assert (report.new, report.skipped) == (0, 3)
    assert len(archive.image_requests()) == downloads


def test_backfill_keeps_going_after_a_bad_download(client, store, archive):
    oldest = archive.index["images"][2]["imageUrl"]
    archive.bodies[oldest] = b"truncated"

    report = backfill(client, store, kp_camera(), START, END)

    assert report.new == 2
    assert len(report.errors) == 1 and "MD5" in report.errors[0]


def test_backfill_counts_repeated_bytes_as_duplicates(client, store, archive):
    newest, middle = archive.index["images"][:2]
    archive.bodies[middle["imageUrl"]] = archive.bodies[newest["imageUrl"]]
    middle["md5"] = newest["md5"]

    report = backfill(client, store, kp_camera(), START, END)

    assert (report.new, report.duplicate) == (2, 1)


def test_backfill_needs_an_ashcam_code(client, store):
    camera = kp_camera().model_copy(update={"ashcam_code": None})

    with pytest.raises(ValueError, match="ashcam_code"):
        backfill(client, store, camera, START, END)


LIVE_NOW = datetime(2026, 10, 17, 15, 1, tzinfo=timezone.utc)


@pytest.fixture
def live(client, store):
    return AshcamIngestor(client, store, now=lambda: LIVE_NOW, lookback=timedelta(minutes=15))


def camera_state(conn):
    return conn.execute("SELECT * FROM camera_state WHERE camera_id = 'kilauea-kp'").fetchone()


def test_first_live_poll_stores_the_lookback_window(live, archive, conn):
    result = live.ingest(kp_camera())

    [listing] = archive.list_requests()
    assert listing.url.params["startTimestamp"] == str(int((LIVE_NOW - timedelta(minutes=15)).timestamp()))
    assert listing.url.params["endTimestamp"] == str(int(LIVE_NOW.timestamp()))
    newest = conn.execute("SELECT id FROM frames ORDER BY captured_at DESC LIMIT 1").fetchone()
    assert (result.status, result.frame_id) == ("new", newest["id"])
    assert camera_state(conn)["last_status"] == "new"


def test_later_live_polls_start_after_the_newest_stored_frame(live, archive):
    live.ingest(kp_camera())

    live.ingest(kp_camera())

    assert archive.list_requests()[-1].url.params["startTimestamp"] == str(1792249205 + 1)


def test_live_poll_without_new_frames_is_not_modified(live, conn):
    live.ingest(kp_camera())

    result = live.ingest(kp_camera())

    assert result.status == "not_modified"
    assert camera_state(conn)["consecutive_unchanged"] == 1


def test_live_poll_records_an_archive_outage_as_an_error(live, archive, conn):
    archive.list_status = 503

    result = live.ingest(kp_camera())

    assert result.status == "error" and "503" in result.error
    assert camera_state(conn)["consecutive_errors"] == 1


def test_live_poll_records_an_unexpected_index_format_as_an_error(live, archive, conn):
    archive.index = {"frames": []}

    result = live.ingest(kp_camera())

    assert result.status == "error" and "IndexFormatError" in result.error
    assert camera_state(conn)["consecutive_errors"] == 1


SOURCES = """
volcanoes:
  kilauea:
    name: Kīlauea
    country: United States
    official_agency: USGS Hawaiian Volcano Observatory
    official_url: https://www.usgs.gov/volcanoes/kilauea
cameras:
  - id: kilauea-kp
    name: KPcam
    volcano: kilauea
    url: https://example.org/KPcam/images/M.jpg
    license: Public Domain
    attribution: U.S. Geological Survey
    ashcam_code: kilauea-kp-cam
  - id: kilauea-s2
    name: S2cam
    volcano: kilauea
    url: https://example.org/S2cam/images/M.jpg
    license: Public Domain
    attribution: U.S. Geological Survey
"""
WINDOW = ["--start", "2026-10-17T13:00Z", "--end", "2026-10-17T19:30Z"]


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(SOURCES, encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigil.sqlite"))


def test_cli_refuses_a_camera_without_an_ashcam_code(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--camera", "kilauea-s2", *WINDOW])

    assert "ashcam_code" in capsys.readouterr().err


def test_cli_refuses_an_unknown_camera(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--camera", "etna-1", *WINDOW])

    assert "etna-1" in capsys.readouterr().err


def test_cli_refuses_times_without_an_offset(cli_env):
    with pytest.raises(SystemExit):
        main(["--camera", "kilauea-kp", "--start", "2026-10-17T13:00", "--end", "2026-10-17T19:30Z"])


def test_cli_refuses_an_empty_window(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--camera", "kilauea-kp", "--start", "2026-10-17T19:30Z", "--end", "2026-10-17T13:00Z"])

    assert "before" in capsys.readouterr().err
