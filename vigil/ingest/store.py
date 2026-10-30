"""Ingest persistence shared by every frame source.

A frame must be a complete JPEG or PNG. It is dropped when the camera already
has the same bytes (SHA-256); otherwise it is written under
`<data_dir>/frames/<camera>/<UTC day>/` and recorded in the `frames` table.
The outcome of each poll is kept per camera in `camera_state`.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from PIL import Image

from vigil.timeutil import parse_utc, to_iso

log = logging.getLogger(__name__)

Status = Literal["new", "duplicate", "not_modified", "error"]

_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png"}


@dataclass(frozen=True)
class IngestResult:
    camera_id: str
    status: Status
    frame_id: int | None = None
    error: str | None = None


class FrameStore:
    def __init__(self, conn: sqlite3.Connection, data_dir: str | Path):
        self._conn = conn
        self._data_dir = Path(data_dir)

    def add(
        self,
        camera_id: str,
        body: bytes,
        *,
        captured_at: datetime,
        timestamp_source: str,
        fetched_at: datetime,
    ) -> int | None:
        """Store a frame and return its id, or None if the camera already has these bytes.

        Raises ValueError if the body is not a complete JPEG or PNG image.
        """
        extension, width, height = _decode_image(body)
        sha256 = hashlib.sha256(body).hexdigest()
        if self._is_known(camera_id, sha256):
            return None
        rel_path = self._write(camera_id, captured_at, sha256, extension, body)
        cursor = self._conn.execute(
            """INSERT INTO frames (camera_id, captured_at, timestamp_source, fetched_at,
                                   sha256, path, bytes, width, height)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (camera_id, to_iso(captured_at), timestamp_source, to_iso(fetched_at),
             sha256, rel_path, len(body), width, height),
        )
        self._conn.commit()
        log.info("camera %s: new frame %s (%s)", camera_id, rel_path, timestamp_source)
        return cursor.lastrowid

    def has_capture(self, camera_id: str, captured_at: datetime, timestamp_source: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM frames WHERE camera_id = ? AND captured_at = ? AND timestamp_source = ?",
            (camera_id, to_iso(captured_at), timestamp_source),
        ).fetchone()
        return row is not None

    def latest_capture(self, camera_id: str, timestamp_source: str) -> datetime | None:
        row = self._conn.execute(
            "SELECT MAX(captured_at) AS latest FROM frames WHERE camera_id = ? AND timestamp_source = ?",
            (camera_id, timestamp_source),
        ).fetchone()
        return parse_utc(row["latest"]) if row["latest"] else None

    def validators(self, camera_id: str) -> tuple[str | None, str | None]:
        """The ETag and Last-Modified the camera's server last sent, to send back as conditions."""
        row = self._conn.execute(
            "SELECT etag, last_modified FROM camera_state WHERE camera_id = ?", (camera_id,)
        ).fetchone()
        return (row["etag"], row["last_modified"]) if row else (None, None)

    def record_check(
        self,
        camera_id: str,
        checked_at: datetime,
        status: Status,
        frame_id: int | None = None,
        error: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> IngestResult:
        """Update the camera's polling state with the outcome of one check."""
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
