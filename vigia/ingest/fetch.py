"""Download one camera image, timestamp it, drop duplicates, and store it.

Capture time comes from the HTTP Last-Modified header when the server sends
one; otherwise the fetch time is used. `timestamp_source` records which, so the
quality filter can later cross-check against the timestamp burned into the
image.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

import httpx

from vigia.config import Camera
from vigia.ingest.store import FrameStore, IngestResult
from vigia.timeutil import parse_http_date, utcnow

log = logging.getLogger(__name__)


class Ingestor:
    def __init__(self, store: FrameStore, http: httpx.Client, now: Callable[[], datetime] = utcnow):
        self._store = store
        self._http = http
        self._now = now

    def ingest(self, camera: Camera) -> IngestResult:
        fetched_at = self._now()
        try:
            response = self._http.get(camera.url, headers=self._conditional_headers(camera.id))
            if response.status_code == 304:
                return self._store.record_check(camera.id, fetched_at, "not_modified")
            response.raise_for_status()
            validators = {"etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified")}
            captured_at = parse_http_date(validators["last_modified"])
            timestamp_source = "http_last_modified" if captured_at else "fetched_at"
            frame_id = self._store.add(camera.id, response.content, captured_at=captured_at or fetched_at,
                                       timestamp_source=timestamp_source, fetched_at=fetched_at)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("camera %s: %s", camera.id, describe_error(exc))
            return self._store.record_check(camera.id, fetched_at, "error", error=describe_error(exc))
        status = "new" if frame_id is not None else "duplicate"
        return self._store.record_check(camera.id, fetched_at, status, frame_id=frame_id, **validators)

    def _conditional_headers(self, camera_id: str) -> dict[str, str]:
        etag, last_modified = self._store.validators(camera_id)
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        return headers


def describe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: {exc}"
