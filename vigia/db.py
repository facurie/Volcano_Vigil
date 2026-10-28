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

CREATE TABLE IF NOT EXISTS api_calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    called_at     TEXT    NOT NULL,  -- UTC
    model         TEXT    NOT NULL,
    purpose       TEXT    NOT NULL,  -- what the call was for, e.g. 'segment', 'bulletin'
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL    NOT NULL,
    latency_ms    INTEGER,
    ok            INTEGER NOT NULL,
    error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_calls_time ON api_calls (called_at);

CREATE TABLE IF NOT EXISTS frame_quality (
    frame_id          INTEGER PRIMARY KEY REFERENCES frames (id),
    assessed_at       TEXT    NOT NULL,  -- UTC
    usable            INTEGER NOT NULL,  -- 1 if measurements may use the frame
    decided_by        TEXT    NOT NULL,  -- local | spark
    local_decision    TEXT    NOT NULL,  -- pass | uncertain | reject
    reasons           TEXT    NOT NULL,  -- JSON list: stale, frozen, night, low_visibility, timestamp_mismatch
    sun_elevation_deg REAL,              -- NULL when the volcano has no position
    brightness        REAL    NOT NULL,
    contrast          REAL    NOT NULL,
    edge_density      REAL    NOT NULL,
    glow_fraction     REAL    NOT NULL,
    change            REAL,              -- against the camera's previous frame; NULL for its first
    spark_view        TEXT,              -- this and the columns below stay NULL unless Muse Spark was asked
    spark_reason      TEXT,
    printed_time_text TEXT,
    printed_time      TEXT,              -- UTC, when the printed timestamp states its zone
    printed_ptz       TEXT,              -- JSON {"pan", "tilt", "zoom_raw", "zoom"}
    spark_answer      TEXT               -- the whole JSON answer
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
