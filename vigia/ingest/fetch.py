"""Download one camera image, timestamp it, drop duplicates, and store it.

Capture time comes from the HTTP Last-Modified header when the server sends
one; otherwise the fetch time is used. `timestamp_source` records which, so the
quality filter can later cross-check against the timestamp burned into the
image.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx
from PIL import Image

from vigia.config import Camera
from vigia.timeutil import parse_http_date, to_iso, utcnow

log = logging.getLogger(__name__)

Status = Literal["new", "duplicate", "not_modified", "error"]

_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png"}


@dataclass(frozen=True)
class IngestResult:
    camera_id: str
    status: Status
    frame_id: int | None = None
    error: str | None = None


class Ingestor:
    def __init__(
        self,
        conn: sqlite3.Connection,
        data_dir: str | Path,
        http: httpx.Client,
        now: Callable[[], datetime] = utcnow,
    ):
        self._conn = conn
        self._data_dir = Path(data_dir)
        self._http = http
        self._now = now

    def ingest(self, camera: Camera) -> IngestResult:
        fetched_at = self._now()
        try:
            response = self._http.get(camera.url, headers=self._conditional_headers(camera.id))
            if response.status_code == 304:
                return self._record(camera.id, fetched_at, "not_modified")
            response.raise_for_status()
            extension, width, height = _decode_image(response.content)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("camera %s: %s", camera.id, _describe(exc))
            return self._record(camera.id, fetched_at, "error", error=_describe(exc))

        body = response.content
        sha256 = hashlib.sha256(body).hexdigest()
        validators = {"etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified")}
        if self._is_known(camera.id, sha256):
            return self._record(camera.id, fetched_at, "duplicate", **validators)

        captured_at = parse_http_date(validators["last_modified"])
        timestamp_source = "http_last_modified" if captured_at else "fetched_at"
        captured_at = captured_at or fetched_at
        rel_path = self._write(camera.id, captured_at, sha256, extension, body)
        cursor = self._conn.execute(
            """INSERT INTO frames (camera_id, captured_at, timestamp_source, fetched_at,
                                   sha256, path, bytes, width, height)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (camera.id, to_iso(captured_at), timestamp_source, to_iso(fetched_at),
             sha256, rel_path, len(body), width, height),
        )
        log.info("camera %s: new frame %s (%s)", camera.id, rel_path, timestamp_source)
        return self._record(camera.id, fetched_at, "new", frame_id=cursor.lastrowid, **validators)

    def _conditional_headers(self, camera_id: str) -> dict[str, str]:
        row = self._conn.execute(
            "SELECT etag, last_modified FROM camera_state WHERE camera_id = ?", (camera_id,)
        ).fetchone()
        headers = {}
        if row and row["etag"]:
            headers["If-None-Match"] = row["etag"]
        if row and row["last_modified"]:
            headers["If-Modified-Since"] = row["last_modified"]
        return headers

    def _is_known(self, camera_id: str, sha256: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM frames WHERE camera_id = ? AND sha256 = ?", (camera_id, sha256)
        ).fetchone()
        return row is not None

    def _write(self, camera_id: str, captured_at: datetime, sha256: str, extension: str, body: bytes) -> str:
        rel_path = (
            f"frames/{camera_id}/{captured_at:%Y-%m-%d}/"
            f"{captured_at:%Y%m%dT%H%M%SZ}_{sha256[:8]}{extension}"
        )
        target = self._data_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        partial.write_bytes(body)
        os.replace(partial, target)
        return rel_path

    def _record(
        self,
        camera_id: str,
        checked_at: datetime,
        status: Status,
        frame_id: int | None = None,
        error: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> IngestResult:
        checked = to_iso(checked_at)
        self._conn.execute("INSERT OR IGNORE INTO camera_state (camera_id) VALUES (?)", (camera_id,))
        self._conn.execute(
            """UPDATE camera_state SET
                   last_checked_at = :checked,
                   last_status = :status,
                   last_error = :error,
                   last_new_frame_at = CASE WHEN :status = 'new' THEN :checked ELSE last_new_frame_at END,
                   consecutive_errors = CASE WHEN :status = 'error' THEN consecutive_errors + 1 ELSE 0 END,
                   consecutive_unchanged = CASE
                       WHEN :status = 'new' THEN 0
                       WHEN :status IN ('duplicate', 'not_modified') THEN consecutive_unchanged + 1
                       ELSE consecutive_unchanged END,
                   etag = COALESCE(:etag, etag),
                   last_modified = COALESCE(:last_modified, last_modified)
               WHERE camera_id = :camera_id""",
            {"checked": checked, "status": status, "error": error, "etag": etag,
             "last_modified": last_modified, "camera_id": camera_id},
        )
        self._conn.commit()
        return IngestResult(camera_id, status, frame_id=frame_id, error=error)


def _decode_image(body: bytes) -> tuple[str, int, int]:
    """Fully decode the body to reject HTML error pages and truncated JPEGs."""
    try:
        with Image.open(io.BytesIO(body)) as img:
            img.load()
            image_format, width, height = img.format, img.width, img.height
    except Exception as exc:  # Pillow raises several unrelated types for bad data
        raise ValueError(f"not a valid image: {exc}") from exc
    if image_format not in _EXTENSIONS:
        raise ValueError(f"unsupported image format: {image_format}")
    return _EXTENSIONS[image_format], width, height


def _describe(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: {exc}"
