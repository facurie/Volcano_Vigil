"""The phases of an eruptive episode, read two ways and set against the official times.

Muse Spark watches the timelapse of one fixed camera, uploaded through the Files API, and names the video second
at which the lava fountain starts, peaks, declines and ends; the frame shown at that second gives each phase's
capture time. SAM's fountain tracks give the same phases from numbers: the first and last detection, and the
peak and the start of the decline of the fountain's height in pixels (its tallest box on each frame as a running
median over 5 frames; on a fixed camera the box's bottom stays at the vent). In the planning probe on episode
55's K2cam timelapse, Muse Spark put the end 1-5 minutes after HVO's but the peak after sunrise, two hours late;
SAM put the peak at 04:52 HST, inside HVO's 04:50-05:10.
"""

from __future__ import annotations

import logging
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import openai

from vigia import tracking
from vigia.config import Camera, Volcano
from vigia.episodes import Episode, local_time
from vigia.meta.client import MetaClient
from vigia.timeutil import parse_utc, to_iso
from vigia.video import assemble

log = logging.getLogger(__name__)

PHASES = ("onset", "peak", "decline", "end")
FPS = 2.0      # timelapse frames per second: about 130 input tokens per frame
HEIGHT = 720   # timelapse height in pixels: the printed time stays readable
RUNNING = 5    # frames in the running median of the fountain's height
DECLINE = 0.9  # the decline starts at the first frame after the peak under this share of it
HEADER = ["Phase", "Official (local)", "SAM, timelapse camera", "SAM, any camera", "Muse Spark, timelapse"]
PROMPT = (
    "This is a timelapse from the {camera} webcam at {volcano}. It has {frames} frames, captured about every "
    "{cadence} minutes from {first} to {last} ({zone}), played at {fps} frames per second, so video second t shows "
    "the frame captured about {per_second} minutes x t after the first. The capture time may be printed on the "
    "frames.\n"
    "The light may change during the clip, between night and day: at night a lava fountain glows yellow-white, by "
    "day it looks red-orange. Judge its height against fixed features such as trees and the crater rim, not by its "
    "brightness or colour.\n"
    "Find the phases of the eruptive episode: onset (the lava fountain starts), peak (the fountain is at its "
    "highest), decline (the fountain is clearly lower than at its peak and dropping), end (fountaining stops). For "
    "each, give the video second and the time printed on that frame exactly as printed (empty if none), and "
    "describe what you see. Set seen to false for a phase the clip does not show.")
_PHASE = {"type": "object", "properties": {
    "seen": {"type": "boolean"}, "video_second": {"type": "number"}, "printed_time": {"type": "string"},
    "description": {"type": "string"}}, "required": ["seen", "video_second", "printed_time", "description"],
    "additionalProperties": False}
SCHEMA = {"type": "object", "properties": {**{phase: _PHASE for phase in PHASES}, "summary": {"type": "string"}},
          "required": [*PHASES, "summary"], "additionalProperties": False}


def fountain_heights(conn: sqlite3.Connection, camera_ids: list[str], start: datetime,
                     end: datetime) -> list[tuple[str, str, int]]:
    """(capture time, camera, tallest fountain box in pixels) per frame with a fountain detection, oldest first."""
    marks = ",".join("?" * len(camera_ids))
    return [tuple(row) for row in conn.execute(
        f"""SELECT f.captured_at, r.camera_id, MAX(d.box_bottom - d.box_top) FROM detections d
            JOIN frames f ON f.id = d.frame_id JOIN tracks t ON t.id = d.track_id
            JOIN tracking_runs r ON r.id = t.run_id
            WHERE r.camera_id IN ({marks}) AND r.target = 'fountain' AND f.captured_at BETWEEN ? AND ?
            GROUP BY f.id ORDER BY f.captured_at, f.id""", (*camera_ids, to_iso(start), to_iso(end)))]


def sam_phases(conn: sqlite3.Connection, camera_id: str, start: datetime, end: datetime) -> dict[str, str | None]:
    """The camera's first and last fountain detection, the frame with the highest running median of the
    fountain's height, and the first frame after it under 90 % of that median."""
    rows = fountain_heights(conn, [camera_id], start, end)
    if not rows:
        return dict.fromkeys(PHASES)
    heights = np.array([row[2] for row in rows], dtype=float)
    half = RUNNING // 2
    running = np.array([np.median(heights[max(0, i - half):i + half + 1]) for i in range(len(heights))])
    peak = int(running.argmax())
    decline = next((i for i in range(peak + 1, len(running)) if running[i] < DECLINE * running[peak]), None)
    return {"onset": rows[0][0], "peak": rows[peak][0], "decline": None if decline is None else rows[decline][0],
            "end": rows[-1][0]}


def ask_phases(client: MetaClient, conn: sqlite3.Connection, data_dir: Path, camera: Camera, volcano: Volcano,
               start: datetime, end: datetime, *, fps: float = FPS, height: int = HEIGHT) -> dict[str, Any]:
    """Muse Spark's reading of the camera's timelapse: per phase whether it saw it, the video second, the capture
    time of the frame at that second, the printed time it read there, and what it saw."""
    frames = tracking.usable_frames(conn, data_dir, camera.id, start, end)
    if len(frames) < 2:
        raise ValueError(f"{camera.id} has {len(frames)} usable frames from {to_iso(start)} to {to_iso(end)}")
    cadence = float(np.median(np.diff([frame.captured_at.timestamp() for frame in frames]))) / 60
    offset = timedelta(hours=volcano.utc_offset_hours or 0)
    zone = "UTC" if volcano.utc_offset_hours is None else f"UTC{volcano.utc_offset_hours:+g}"
    prompt = PROMPT.format(camera=camera.name, volcano=volcano.name, frames=len(frames), cadence=f"{cadence:g}",
                           first=f"{frames[0].captured_at + offset:%H:%M}", last=f"{frames[-1].captured_at + offset:%H:%M}",
                           zone=zone, fps=f"{fps:g}", per_second=f"{cadence * fps:g}")
    with tempfile.TemporaryDirectory() as tmp:
        video = assemble([frame.path for frame in frames], Path(tmp) / "timelapse.mp4", fps=fps,
                         height=min(height, frames[0].height) // 2 * 2)
        file_id = client.upload_video(video)
    try:
        answer = client.ask_json(prompt=prompt, videos=[file_id], schema_name="phases", schema=SCHEMA,
                                 purpose="phases", effort="medium", max_output_tokens=8000)
    finally:
        try:
            client.delete_file(file_id)
        except openai.APIError as exc:
            log.warning("could not delete the uploaded timelapse %s: %s", file_id, exc)
    result: dict[str, Any] = {"camera_id": camera.id, "frames": len(frames), "fps": fps, "summary": answer["summary"]}
    for phase in PHASES:
        item = answer[phase]
        index = min(max(round(item["video_second"] * fps), 0), len(frames) - 1)
        result[phase] = {**item, "time": to_iso(frames[index].captured_at) if item["seen"] else None}
    return result


def _reading(time: str | None, low: datetime, high: datetime, episode: Episode) -> str:
    """'04:52 (+0 min)': a time in local time and its minutes outside the official window."""
    if time is None:
        return "-"
    when = parse_utc(time)
    outside = when - high if when > high else when - low if when < low else timedelta(0)
    return f"{local_time(time, episode.local)} ({outside / timedelta(minutes=1):+.0f} min)"


def cross_check(conn: sqlite3.Connection, episode: Episode, spark: dict[str, Any] | None) -> dict[str, Any]:
    """Each phase by SAM on the timelapse camera, by SAM on any camera (onset and end), by Muse Spark (None: not
    asked) and officially, with each reading's minutes outside the official window."""
    fixed = sam_phases(conn, episode.timelapse_camera, episode.start, episode.end)
    heights = fountain_heights(conn, list(episode.cameras), episode.start, episode.end)
    anywhere = {"onset": heights[0] if heights else None, "end": heights[-1] if heights else None}
    rows = []
    for phase in PHASES:
        low, high = episode.phases[phase]
        official = local_time(to_iso(low), episode.local)
        if high != low:
            official += f"-{local_time(to_iso(high), episode.local)}"
        found = anywhere.get(phase)
        if spark is None:
            asked = "not asked"
        else:
            asked = _reading(spark[phase]["time"] if spark[phase]["seen"] else None, low, high, episode)
        rows.append([phase, official, _reading(fixed[phase], low, high, episode),
                     f"{found[1]}: {_reading(found[0], low, high, episode)}" if found else "-", asked])
    return {"camera_id": episode.timelapse_camera, "sam": fixed,
            "sam_any_camera": {phase: found and {"time": found[0], "camera_id": found[1]}
                               for phase, found in anywhere.items()},
            "muse_spark": spark, "rows": rows}
