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
import logging
import sqlite3
import tempfile
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import openai

from vigia import masks
from vigia.config import Camera
from vigia.meta.client import MetaClient, SamStreamError
from vigia.meta.sam import SamObject, SamParseError, fit_mask
from vigia.prompts import Prompts, Target
from vigia.timeutil import parse_utc, to_iso, utcnow
from vigia.video import VideoInfo, assemble, probe

log = logging.getLogger(__name__)

TARGETS: tuple[Target, ...] = ("plume", "fountain", "incandescence")
VIDEO_FPS = 10
VIDEO_MAX_HEIGHT = 1080
MIN_BILLED_FRAMES = 50


@dataclass(frozen=True)
class WindowFrame:
    id: int
    captured_at: datetime
    path: Path
    width: int
    height: int


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    target: str
    phrase: str
    tracks: int
    detections: int
    first_seen: datetime | None  # capture time of the run's first detection
    last_seen: datetime | None


@dataclass
class TrackingReport:
    camera_id: str
    frames: int
    video_size: tuple[int, int] | None = None
    runs: list[RunSummary] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        size = f", video {self.video_size[0]}x{self.video_size[1]}" if self.video_size else ""
        lines = [f"{self.camera_id}: {self.frames} usable frames{size}"]
        for run in self.runs:
            seen = f", seen {to_iso(run.first_seen)} to {to_iso(run.last_seen)}" if run.first_seen else ""
            lines.append(f"  {run.target} / {run.phrase}: {run.tracks} track(s), {run.detections} detection(s){seen}")
        lines += [f"  failed: {error}" for error in self.errors]
        return "\n".join(lines)


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


def track_window(
    client: MetaClient,
    conn: sqlite3.Connection,
    data_dir: str | Path,
    camera: Camera,
    prompts: Prompts,
    start: datetime,
    end: datetime,
    *,
    targets: Sequence[Target] = TARGETS,
    redo: bool = False,
    max_height: int = VIDEO_MAX_HEIGHT,
    now: Callable[[], datetime] = utcnow,
) -> TrackingReport:
    """Track each phrase of `targets` for the camera's kind through its usable frames in [start, end].

    Raises ValueError before spending anything when the window has no usable
    frames, mixes frame sizes or formats, or was already tracked with one of
    the phrases (`redo` replaces those runs). A failed SAM request is reported
    and the other phrases go on.
    """
    frames = usable_frames(conn, data_dir, camera.id, start, end)
    if not frames:
        raise ValueError(f"camera {camera.id} has no usable frames between {to_iso(start)} and {to_iso(end)}")
    if len({(f.width, f.height, f.path.suffix.lower()) for f in frames}) > 1:
        raise ValueError(f"camera {camera.id}: the window mixes frame sizes or formats; split it")
    phrases = [(target, phrase) for target in targets for phrase in prompts.phrases(target, camera.kind)]
    window = (to_iso(frames[0].captured_at), to_iso(frames[-1].captured_at))
    existing = _existing_runs(conn, camera.id, [phrase for _, phrase in phrases], *window)
    if existing and not redo:
        raise ValueError(f"camera {camera.id}: window {window[0]} to {window[1]} was already tracked "
                         f"with {', '.join(existing)}; pass redo to replace it")

    report = TrackingReport(camera.id, len(frames))
    if not phrases:
        return report
    with tempfile.TemporaryDirectory() as tmp:
        height = min(max_height, frames[0].height) // 2 * 2
        video = assemble([f.path for f in frames], Path(tmp) / "window.mp4", fps=VIDEO_FPS, height=height)
        info = probe(video)
        if info.frames != len(frames):
            raise RuntimeError(f"the window video has {info.frames} frames instead of {len(frames)}")
        report.video_size = (info.width, info.height)
        file_id = client.upload_video(video)
    try:
        for target, phrase in phrases:
            try:
                objects = client.segment_video(file_id, phrase, purpose=f"track:{target}",
                                               expected_frames=len(frames))
            except (openai.APIError, SamStreamError, SamParseError) as exc:
                log.warning("camera %s, %s: %s", camera.id, phrase, exc)
                report.errors.append(f"{target} / {phrase}: {type(exc).__name__}: {exc}"[:300])
                continue
            with conn:
                _delete_runs(conn, existing.get(phrase, []))
                report.runs.append(_store_run(conn, camera.id, target, phrase, frames, info, objects, now()))
    finally:
        try:
            client.delete_file(file_id)
        except openai.APIError as exc:
            log.warning("could not delete the uploaded window %s (it expires in an hour): %s", file_id, exc)
    return report


def _existing_runs(conn: sqlite3.Connection, camera_id: str, phrases: list[str],
                   window_start: str, window_end: str) -> dict[str, list[int]]:
    found: dict[str, list[int]] = defaultdict(list)
    for row in conn.execute(
            "SELECT id, phrase FROM tracking_runs WHERE camera_id = ? AND window_start = ? AND window_end = ?",
            (camera_id, window_start, window_end)):
        if row["phrase"] in phrases:
            found[row["phrase"]].append(row["id"])
    return found


def _delete_runs(conn: sqlite3.Connection, run_ids: list[int]) -> None:
    for run_id in run_ids:
        conn.execute("DELETE FROM detections WHERE track_id IN (SELECT id FROM tracks WHERE run_id = ?)", (run_id,))
        conn.execute("DELETE FROM tracks WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM tracking_runs WHERE id = ?", (run_id,))


def _store_run(conn: sqlite3.Connection, camera_id: str, target: str, phrase: str, frames: list[WindowFrame],
               info: VideoInfo, objects: list[SamObject], created_at: datetime) -> RunSummary:
    run_id = conn.execute(
        """INSERT INTO tracking_runs (camera_id, target, phrase, window_start, window_end, frame_ids,
                                      video_width, video_height, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (camera_id, target, phrase, to_iso(frames[0].captured_at), to_iso(frames[-1].captured_at),
         json.dumps([f.id for f in frames]), info.width, info.height, to_iso(created_at)),
    ).lastrowid
    tracks: dict[str, list[SamObject]] = defaultdict(list)
    for obj in sorted(objects, key=lambda o: o.frame_index):
        if not 0 <= obj.frame_index < len(frames):
            raise ValueError(f"SAM returned frame {obj.frame_index} for a {len(frames)}-frame video")
        tracks[obj.object_id].append(obj)
    seen = []
    for object_id, track in tracks.items():
        first, last = frames[track[0].frame_index], frames[track[-1].frame_index]
        track_id = conn.execute(
            "INSERT INTO tracks (run_id, object_id, first_seen, last_seen, detections) VALUES (?, ?, ?, ?, ?)",
            (run_id, object_id, to_iso(first.captured_at), to_iso(last.captured_at), len(track)),
        ).lastrowid
        for obj in track:
            frame = frames[obj.frame_index]
            box, mask = _to_frame_pixels(obj, frame, info)
            conn.execute(
                """INSERT INTO detections (track_id, frame_id, box_left, box_top, box_right, box_bottom,
                                           score, area_px, mask_rle)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (track_id, frame.id, *box, obj.score, int(mask.sum()), json.dumps(masks.encode(mask))),
            )
        seen += [first.captured_at, last.captured_at]
    return RunSummary(run_id, target, phrase, len(tracks), sum(len(track) for track in tracks.values()),
                      min(seen, default=None), max(seen, default=None))


def _to_frame_pixels(obj: SamObject, frame: WindowFrame, info: VideoInfo) -> tuple[tuple[int, int, int, int], np.ndarray]:
    """The object's box and box-sized mask, scaled from the video's pixels to the frame's."""
    sx, sy = frame.width / info.width, frame.height / info.height
    left, top, right, bottom = obj.box
    box = (round(left * sx), round(top * sy), min(frame.width, round(right * sx)), min(frame.height, round(bottom * sy)))
    return box, fit_mask(obj.mask, box[3] - box[1], box[2] - box[0])
