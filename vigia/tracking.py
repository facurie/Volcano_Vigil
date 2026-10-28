"""Track plumes and fountains through timelapses of usable frames with SAM 3.1 video.

A window is a camera's usable frames (see vigia.gate) between two capture
times, oldest first. It is encoded into one MP4 (10 fps, at most 1080 px
high), uploaded once and tracked once per phrase of config/prompts.yaml. Each
SAM request is a tracking run; each SAM object in a run is a track; each
object on one frame is a detection, stored in that frame's own pixels with its
mask as COCO RLE (vigia.masks).

Cost rule: SAM bills at least 50 frames per video request, so backfills send
windows of 50 frames or more (vigia-track refuses fewer by default); live
tracking uses one window per camera per hour.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from vigia import masks
from vigia.timeutil import parse_utc, to_iso


@dataclass(frozen=True)
class WindowFrame:
    id: int
    captured_at: datetime
    path: Path
    width: int
    height: int


def usable_frames(conn: sqlite3.Connection, data_dir: str | Path, camera_id: str,
                  start: datetime, end: datetime) -> list[WindowFrame]:
    """The camera's frames judged usable, captured between start and end (inclusive), oldest first."""
    rows = conn.execute(
        """SELECT f.id, f.captured_at, f.path, f.width, f.height
           FROM frames f JOIN frame_quality q ON q.frame_id = f.id
           WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ? AND q.usable = 1
           ORDER BY f.captured_at""",
        (camera_id, to_iso(start), to_iso(end)),
    ).fetchall()
    return [WindowFrame(row["id"], parse_utc(row["captured_at"]), Path(data_dir) / row["path"],
                        row["width"], row["height"]) for row in rows]


def unassessed_frames(conn: sqlite3.Connection, camera_id: str, start: datetime, end: datetime) -> int:
    """How many of the camera's frames in the window have no quality verdict yet."""
    return conn.execute(
        """SELECT COUNT(*) FROM frames f LEFT JOIN frame_quality q ON q.frame_id = f.id
           WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ? AND q.frame_id IS NULL""",
        (camera_id, to_iso(start), to_iso(end)),
    ).fetchone()[0]


def detection_mask(detection: Mapping[str, Any], width: int, height: int) -> np.ndarray:
    """A stored detection's mask over its whole frame (height x width, bool)."""
    box_mask = masks.decode(json.loads(detection["mask_rle"]))
    left, top = detection["box_left"], detection["box_top"]
    right, bottom = detection["box_right"], detection["box_bottom"]
    if box_mask.shape != (bottom - top, right - left):
        raise ValueError(f"detection {detection['id']}: mask {box_mask.shape} does not fit its box")
    full = np.zeros((height, width), dtype=bool)
    full[top:bottom, left:right] = box_mask
    return full
