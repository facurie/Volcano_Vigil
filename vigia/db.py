"""SQLite storage: schema and connection helper."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS frames (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id        TEXT    NOT NULL,
    captured_at      TEXT    NOT NULL,  -- UTC, best estimate of when the camera took it
    timestamp_source TEXT    NOT NULL,  -- how captured_at was obtained
    fetched_at       TEXT    NOT NULL,  -- UTC, when we downloaded it
    sha256           TEXT    NOT NULL,
    path             TEXT    NOT NULL,  -- relative to the data dir, POSIX separators
    bytes            INTEGER NOT NULL,
    width            INTEGER NOT NULL,
    height           INTEGER NOT NULL,
    UNIQUE (camera_id, sha256)
);
CREATE INDEX IF NOT EXISTS idx_frames_camera_time ON frames (camera_id, captured_at);

CREATE TABLE IF NOT EXISTS camera_state (
    camera_id             TEXT PRIMARY KEY,
    last_checked_at       TEXT,
    last_new_frame_at     TEXT,
    last_status           TEXT,     -- new | duplicate | not_modified | error
    last_error            TEXT,     -- error of the last check, NULL if it succeeded
    consecutive_errors    INTEGER NOT NULL DEFAULT 0,
    consecutive_unchanged INTEGER NOT NULL DEFAULT 0,
    etag                  TEXT,
    last_modified         TEXT      -- raw Last-Modified header, sent back as If-Modified-Since
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    return conn
