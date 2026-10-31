"""What the dashboard shows: one database seen at one clock.

Live, the database is the pipeline's and the clock is now; in a replay it is the replay's database at the simulated
time. Every query here is bounded by the clock, so a replay shows only what existed then:
- frames captured by the clock, with their quality verdicts;
- detections, and the measurements made from them, of SAM runs whose every frame was captured by the clock (the
  run's window_end): SAM tracks a window as a whole, so a detection on an early frame depends on the later ones;
- bulletins and agent runs whose clock is not after it;
- HVO's values once HVO had given them: a height once its window has closed, a phase once its latest time has
  passed, and the replay's comparison with them only at the episode's end.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from vigil.agent.tools import STALE_AFTER, calibrated
from vigil.calibration import Calibration
from vigil.config import Camera, Sources
from vigil.episodes import Episode
from vigil.timeutil import parse_utc, to_iso

# A rejected frame's condition: its first reason in this order (vigil.gate's reasons).
CONDITIONS = (("night", "night"), ("low_visibility", "fog"), ("frozen", "frozen"),
              ("timestamp_mismatch", "clock_mismatch"), ("stale", "stale"))
_RUN = "JOIN tracks t ON t.id = d.track_id JOIN tracking_runs r ON r.id = t.run_id"
_FRAME = """SELECT f.id, f.camera_id, f.captured_at, f.path, f.width, f.height, q.usable, q.reasons FROM frames f
            LEFT JOIN frame_quality q ON q.frame_id = f.id"""


@dataclass(frozen=True)
class Scene:
    conn: sqlite3.Connection
    clock: datetime                 # UTC: nothing after it is shown
    data_dir: Path
    sources: Sources
    calibration: Calibration
    volcano: str
    cameras: tuple[str, ...]        # the cameras shown, in order
    episode: Episode | None = None  # the replayed episode; None live

    def __post_init__(self):
        if self.clock.tzinfo is None:
            raise ValueError("the dashboard's clock needs a time zone")

    @property
    def now(self) -> str:
        return to_iso(self.clock)

    def camera(self, camera_id: str) -> Camera:
        """A camera the scene shows; LookupError for any other."""
        if camera_id not in self.cameras:
            raise LookupError(f"camera {camera_id!r} is not shown here; the cameras are {', '.join(self.cameras)}")
        return next(camera for camera in self.sources.cameras if camera.id == camera_id)


def condition(captured_at: str | None, usable: int | None, reasons: list[str], clock: datetime) -> str:
    """A camera's condition from its latest frame: no_frames, stale, unchecked, usable, or why the frame was
    rejected (night, fog, frozen, clock_mismatch, stale, rejected)."""
    if captured_at is None:
        return "no_frames"
    if clock - parse_utc(captured_at) > STALE_AFTER:
        return "stale"
    if usable is None:
        return "unchecked"
    if usable:
        return "usable"
    return next((name for reason, name in CONDITIONS if reason in reasons), "rejected")


def _reasons(text: str | None) -> list[str]:
    return json.loads(text) if text else []


def camera_status(scene: Scene) -> list[dict[str, Any]]:
    """Each shown camera's latest frame by the clock, its last hour, whether it measures heights, and when SAM last
    saw each target on it."""
    now, hour_ago = scene.now, to_iso(scene.clock - timedelta(hours=1))
    out = []
    for camera_id in scene.cameras:
        camera = scene.camera(camera_id)
        latest = scene.conn.execute(
            """SELECT f.id, f.captured_at, q.usable, q.reasons FROM frames f
               LEFT JOIN frame_quality q ON q.frame_id = f.id
               WHERE f.camera_id = ? AND f.captured_at <= ? ORDER BY f.captured_at DESC LIMIT 1""",
            (camera_id, now)).fetchone()
        frames, usable = scene.conn.execute(
            """SELECT COUNT(*), COALESCE(SUM(q.usable), 0) FROM frames f LEFT JOIN frame_quality q ON q.frame_id = f.id
               WHERE f.camera_id = ? AND f.captured_at > ? AND f.captured_at <= ?""",
            (camera_id, hour_ago, now)).fetchone()
        seen = scene.conn.execute(
            f"""SELECT r.target, MAX(f.captured_at) FROM detections d JOIN frames f ON f.id = d.frame_id {_RUN}
                WHERE r.camera_id = ? AND r.window_end <= ? GROUP BY r.target""", (camera_id, now)).fetchall()
        reasons = _reasons(latest["reasons"]) if latest else []
        site = scene.calibration.cameras.get(camera_id)
        out.append({
            "camera_id": camera_id, "name": camera.name, "kind": camera.kind,
            "condition": condition(latest["captured_at"] if latest else None, latest["usable"] if latest else None,
                                   reasons, scene.clock),
            "reasons": reasons,
            "latest": None if latest is None else {
                "frame_id": latest["id"], "captured_at": latest["captured_at"],
                "minutes_ago": round((scene.clock - parse_utc(latest["captured_at"])).total_seconds() / 60, 1)},
            "frames_last_hour": frames, "usable_last_hour": usable,
            "calibrated": calibrated(scene.calibration, camera_id, scene.clock),
            "position": None if site is None else {
                "lat": site.position.lat, "lon": site.position.lon, "elev_m": site.position.elev_m,
                "sigma_m": site.position.sigma_m},
            "last_detection": {row[0]: row[1] for row in seen},
        })
    return out


def _detection_rows(scene: Scene, frame_ids: list[int]) -> list[sqlite3.Row]:
    """The detections on these frames whose run closed by the clock, largest first."""
    if not frame_ids:
        return []
    marks = ",".join("?" * len(frame_ids))
    return scene.conn.execute(
        f"""SELECT d.*, r.target FROM detections d {_RUN}
            WHERE d.frame_id IN ({marks}) AND r.window_end <= ? ORDER BY d.area_px DESC, d.id""",
        (*frame_ids, scene.now)).fetchall()


def detections(scene: Scene, frame_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """Per frame, its detections that exist at the clock, each with the measurements made from it."""
    rows = _detection_rows(scene, frame_ids)
    measured: dict[int, dict[str, Any]] = defaultdict(dict)
    if rows:
        marks = ",".join("?" * len(rows))
        for m in scene.conn.execute(
                f"SELECT detection_id, metric, value, sigma, unit FROM measurements WHERE detection_id IN ({marks})",
                [row["id"] for row in rows]):
            measured[m["detection_id"]][m["metric"]] = {"value": m["value"], "sigma": m["sigma"], "unit": m["unit"]}
    found: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        found[row["frame_id"]].append({
            "detection_id": row["id"], "target": row["target"],
            "box": [row["box_left"], row["box_top"], row["box_right"], row["box_bottom"]], "score": row["score"],
            "measurements": measured.get(row["id"], {})})
    return dict(found)


def _frame_row(scene: Scene, frame_id: int) -> sqlite3.Row | None:
    return scene.conn.execute(f"{_FRAME} WHERE f.id = ? AND f.captured_at <= ?", (frame_id, scene.now)).fetchone()


def _frame_json(scene: Scene, row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"frame_id": row["id"], "camera_id": row["camera_id"], "captured_at": row["captured_at"],
            "width": row["width"], "height": row["height"],
            "usable": None if row["usable"] is None else bool(row["usable"]), "reasons": _reasons(row["reasons"]),
            "detections": detections(scene, [row["id"]]).get(row["id"], [])}


def frame(scene: Scene, frame_id: int) -> dict[str, Any] | None:
    """A frame captured by the clock with its verdict and visible detections; None for any other."""
    return _frame_json(scene, _frame_row(scene, frame_id))


def latest_frames(scene: Scene, camera_id: str) -> dict[str, Any]:
    """The camera's newest frame by the clock, and its newest frame with a visible detection (SAM tracks an hour
    at a time, so the two differ while an hour is open)."""
    scene.camera(camera_id)
    latest = scene.conn.execute(f"{_FRAME} WHERE f.camera_id = ? AND f.captured_at <= ? "
                                "ORDER BY f.captured_at DESC LIMIT 1", (camera_id, scene.now)).fetchone()
    tracked = scene.conn.execute(
        f"""{_FRAME} WHERE f.id = (SELECT d.frame_id FROM detections d JOIN frames g ON g.id = d.frame_id {_RUN}
                                   WHERE g.camera_id = ? AND g.captured_at <= ? AND r.window_end <= ?
                                   ORDER BY g.captured_at DESC LIMIT 1)""",
        (camera_id, scene.now, scene.now)).fetchone()
    return {"camera_id": camera_id, "latest": _frame_json(scene, latest), "tracked": _frame_json(scene, tracked)}


def frame_strip(scene: Scene, camera_id: str, since: datetime) -> list[dict[str, Any]]:
    """The camera's frames from `since` to the clock, oldest first: each verdict and the targets SAM saw on it."""
    scene.camera(camera_id)
    span = (camera_id, to_iso(since), scene.now)
    rows = scene.conn.execute(
        """SELECT f.id, f.captured_at, q.usable FROM frames f LEFT JOIN frame_quality q ON q.frame_id = f.id
           WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ? ORDER BY f.captured_at, f.id""", span).fetchall()
    targets: dict[int, set[str]] = defaultdict(set)
    for frame_id, target in scene.conn.execute(
            f"""SELECT d.frame_id, r.target FROM detections d JOIN frames f ON f.id = d.frame_id {_RUN}
                WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ? AND r.window_end <= ?""",
            (*span, scene.now)):
        targets[frame_id].add(target)
    return [{"frame_id": row["id"], "captured_at": row["captured_at"],
             "usable": None if row["usable"] is None else bool(row["usable"]),
             "targets": sorted(targets.get(row["id"], ()))} for row in rows]
