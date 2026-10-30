import io
from datetime import datetime, timezone

import httpx
import pytest
from PIL import Image

from vigil import db
from vigil.config import Camera

NOW = datetime(2026, 10, 26, 18, 30, 5, tzinfo=timezone.utc)
CAM_URL = "https://cams.example.org/V1cam/images/M.jpg"


def make_jpeg(color=(200, 80, 40), size=(64, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def make_noisy_jpeg(size=(320, 240)) -> bytes:
    """A JPEG with real scan data, so truncating it actually corrupts it."""
    buf = io.BytesIO()
    Image.effect_noise(size, 80).convert("RGB").save(buf, format="JPEG", quality=95)
    return buf.getvalue()


class FakeServer:
    """Serves queued responses per URL and records every request it receives."""

    def __init__(self):
        self._queue: dict[str, list] = {}
        self.requests: list[httpx.Request] = []

    def add(self, url, *, status=200, body=b"", headers=None, exc=None):
        self._queue.setdefault(url, []).append((status, body, headers or {}, exc))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, body, headers, exc = self._queue[str(request.url)].pop(0)
        if exc is not None:
            raise exc
        return httpx.Response(status, content=body, headers=headers)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))


@pytest.fixture
def server():
    return FakeServer()


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "vigil.sqlite")
    yield connection
    connection.close()


@pytest.fixture
def camera():
    return Camera(
        id="kilauea-v1",
        name="V1cam",
        volcano="kilauea",
        url=CAM_URL,
        license="Public Domain",
        attribution="U.S. Geological Survey",
        enabled=True,
    )
