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

CREATE TABLE IF NOT EXISTS tracking_runs (   -- one SAM video request: one phrase over one window of frames
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id    TEXT    NOT NULL,
    target       TEXT    NOT NULL,  -- plume | fountain | incandescence
    phrase       TEXT    NOT NULL,
    window_start TEXT    NOT NULL,  -- UTC capture time of the window's first frame
    window_end   TEXT    NOT NULL,  -- UTC capture time of its last frame
    frame_ids    TEXT    NOT NULL,  -- JSON list; video frame i is frame_ids[i]
    video_width  INTEGER NOT NULL,
    video_height INTEGER NOT NULL,
    created_at   TEXT    NOT NULL,  -- UTC
    UNIQUE (camera_id, phrase, window_start, window_end)
);

CREATE TABLE IF NOT EXISTS tracks (          -- one SAM object of a run
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL REFERENCES tracking_runs (id),
    object_id  TEXT    NOT NULL,  -- SAM's id, stable within its run
    first_seen TEXT    NOT NULL,  -- UTC capture time of its first detection
    last_seen  TEXT    NOT NULL,
    detections INTEGER NOT NULL,
    UNIQUE (run_id, object_id)
);

CREATE TABLE IF NOT EXISTS detections (      -- one tracked object on one frame
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id   INTEGER NOT NULL REFERENCES tracks (id),
    frame_id   INTEGER NOT NULL REFERENCES frames (id),
    box_left   INTEGER NOT NULL,  -- half-open box in the frame's own pixels
    box_top    INTEGER NOT NULL,
    box_right  INTEGER NOT NULL,
    box_bottom INTEGER NOT NULL,
    score      REAL,
    area_px    INTEGER NOT NULL,  -- mask pixels at the frame's resolution
    mask_rle   TEXT    NOT NULL   -- JSON COCO RLE of the box-sized mask: {"size": [h, w], "counts": "..."}
);
CREATE INDEX IF NOT EXISTS idx_detections_frame ON detections (frame_id);
CREATE INDEX IF NOT EXISTS idx_detections_track ON detections (track_id);
CREATE TABLE IF NOT EXISTS measurements (    -- one metric of one detection (vigia.metrics)
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    detection_id INTEGER NOT NULL REFERENCES detections (id),
    frame_id     INTEGER NOT NULL REFERENCES frames (id),
    camera_id    TEXT    NOT NULL,
    captured_at  TEXT    NOT NULL,  -- UTC capture time of the frame
    target       TEXT    NOT NULL,  -- plume | fountain | incandescence
    metric       TEXT    NOT NULL,  -- top_height | top_altitude | area | drift_offset | drift_bearing
    value        REAL    NOT NULL,
    sigma        REAL    NOT NULL,  -- one standard deviation, from the Monte Carlo
    unit         TEXT    NOT NULL,  -- m | m2 | deg
    preset       TEXT    NOT NULL,  -- the calibration preset used
    computed_at  TEXT    NOT NULL,  -- UTC
    UNIQUE (detection_id, metric)
);
CREATE INDEX IF NOT EXISTS idx_measurements_series ON measurements (camera_id, metric, captured_at);

CREATE TABLE IF NOT EXISTS wind_profiles (   -- Open-Meteo winds aloft over a volcano, one row per model hour (vigia.wind)
    volcano     TEXT NOT NULL,
    valid_at    TEXT NOT NULL,  -- UTC model hour
    source      TEXT NOT NULL,  -- forecast | historical_forecast
    fetched_at  TEXT NOT NULL,  -- UTC
    grid_lat    REAL NOT NULL,  -- the model cell Open-Meteo used
    grid_lon    REAL NOT NULL,
    grid_elev_m REAL NOT NULL,
    levels      TEXT NOT NULL,  -- JSON [[pressure_hpa, altitude_m, speed_ms, from_deg], ...], lowest first
    PRIMARY KEY (volcano, valid_at)
);

CREATE TABLE IF NOT EXISTS agent_runs (      -- one run of the Muse Spark agent (vigia.agent.loop)
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT    NOT NULL,  -- UTC wall clock
    finished_at TEXT,
    clock       TEXT    NOT NULL,  -- UTC time the agent worked at: now live, the simulated time in a replay
    volcano     TEXT    NOT NULL,
    task        TEXT    NOT NULL,  -- what it was asked
    model       TEXT    NOT NULL,
    status      TEXT    NOT NULL,  -- running | done | max_turns | budget | error
    turns       INTEGER NOT NULL DEFAULT 0,
    cost_usd    REAL    NOT NULL DEFAULT 0,  -- every Meta call of the run, its tools' calls included
    final_text  TEXT,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS agent_steps (     -- one model turn or tool call of a run, in order
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES agent_runs (id),
    seq         INTEGER NOT NULL,  -- order within the run
    turn        INTEGER NOT NULL,  -- the model turn that made it
    kind        TEXT    NOT NULL,  -- model | tool
    created_at  TEXT    NOT NULL,  -- UTC
    response_id TEXT,              -- model: the Responses API id
    text        TEXT,              -- model: its visible text, commentary or the final answer
    reasoning   TEXT,              -- model: reasoning summaries, when sent
    tool_name   TEXT,              -- tool: the function called
    call_id     TEXT,
    arguments   TEXT,              -- tool: the JSON arguments as Muse Spark sent them
    result      TEXT,              -- tool: the JSON sent back
    ok          INTEGER,           -- tool: 0 if the arguments were invalid or the tool failed
    cost_usd    REAL    NOT NULL DEFAULT 0,  -- model: the turn; tool: the Meta calls it made
    latency_ms  INTEGER,
    UNIQUE (run_id, seq)
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
