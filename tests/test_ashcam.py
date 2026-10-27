import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from conftest import make_jpeg
from vigia.ingest.ashcam import AshcamClient, ChecksumMismatch

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


def test_fetch_returns_the_image_when_its_md5_matches(client, archive):
    image = client.list_images("kilauea-kp-cam", START, END)[0]

    assert client.fetch(image) == archive.bodies[image.url]


def test_fetch_rejects_an_image_whose_md5_does_not_match(client, archive):
    image = client.list_images("kilauea-kp-cam", START, END)[0]
    archive.bodies[image.url] = b"truncated"

    with pytest.raises(ChecksumMismatch, match="MD5"):
        client.fetch(image)
