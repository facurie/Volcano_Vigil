import io
from datetime import datetime, timezone

import httpx
import numpy as np
import pytest
from PIL import Image, ImageFilter

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


def make_textured_jpeg(seed=0, size=(960, 540), shift=(0, 0), zoom=1.0, brightness=1.0) -> bytes:
    """A JPEG of smooth random texture, the same for the same seed; `shift` (columns, rows) rolls it, `zoom`
    enlarges it about its centre, `brightness` scales it (a dark frame below about 0.45)."""
    rng = np.random.default_rng(seed)
    width, height = size
    texture = Image.fromarray((rng.random((height, width)) * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(2))
    pixels = np.roll(np.asarray(texture, dtype=np.float32), (shift[1], shift[0]), axis=(0, 1))
    image = Image.fromarray(np.clip(pixels * brightness, 0, 255).astype(np.uint8))
    if zoom != 1.0:
        cw, ch = width / zoom, height / zoom
        left, top = (width - cw) / 2, (height - ch) / 2
        image = image.transform(size, Image.EXTENT, (left, top, left + cw, top + ch), Image.BILINEAR)
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=92)
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
