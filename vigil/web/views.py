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

import io
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from vigil import masks
from vigil.agent import render
from vigil.agent.bulletin import COLORS, DISCLAIMER_EN, DISCLAIMER_ES, Bulletin
from vigil.agent.tools import STALE_AFTER, calibrated
from vigil.calibration import Calibration
from vigil.config import Camera, Sources
from vigil.episodes import DRIFT_HEADER, END_HEADER, HEIGHT_HEADER, Episode
from vigil.overlay import Layer, draw_layers
from vigil.phases import HEADER as PHASES_HEADER
from vigil.replay import ACTIVITY_HEADER, BULLETIN_HEADER, STEP
from vigil.timeutil import parse_utc, to_iso

# A rejected frame's condition: its first reason in this order (vigil.gate's reasons).
CONDITIONS = (("night", "night"), ("low_visibility", "fog"), ("frozen", "frozen"),
              ("timestamp_mismatch", "clock_mismatch"), ("stale", "stale"))
_RUN = "JOIN tracks t ON t.id = d.track_id JOIN tracking_runs r ON r.id = t.run_id"
_FRAME = """SELECT f.id, f.camera_id, f.captured_at, f.path, f.width, f.height, q.usable, q.reasons FROM frames f
            LEFT JOIN frame_quality q ON q.frame_id = f.id"""
UNITS = {"area": "m2", "drift_bearing": "deg"}  # every other metric is in metres
JPEG_QUALITY = 82
RESULT_TABLES = (  # the replay's comparison with the official values, as report.md titles it
    ("What the bulletins quoted against the official values", BULLETIN_HEADER, "bulletins"),
    ("Activity against the official times", ACTIVITY_HEADER, "activity"),
    ("Measurements against the official values", HEIGHT_HEADER, "heights"),
    ("End of fountaining", END_HEADER, "ends"),
    ("Drift", DRIFT_HEADER, "drift"),
)


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


def series(scene: Scene, camera_id: str, target: str, metric: str, since: datetime) -> dict[str, Any]:
    """The camera's measurements of a target and metric from `since` to the clock: the highest detection of each
    frame, oldest first. In a replay, also the official values of that target and metric whose window has closed."""
    scene.camera(camera_id)
    rows = scene.conn.execute(
        f"""SELECT m.captured_at, m.frame_id, m.value, m.sigma FROM measurements m
            JOIN detections d ON d.id = m.detection_id {_RUN}
            WHERE m.camera_id = ? AND m.target = ? AND m.metric = ? AND m.captured_at BETWEEN ? AND ?
            AND r.window_end <= ? ORDER BY m.captured_at, m.value DESC""",
        (camera_id, target, metric, to_iso(since), scene.now, scene.now)).fetchall()
    best: dict[str, sqlite3.Row] = {}
    for row in rows:
        best.setdefault(row["captured_at"], row)
    official = [] if scene.episode is None else [
        {"quantity": check.quantity, "start": check.start, "end": check.end, "value_m": check.official_m,
         "official": check.official, "source": check.source, "upper_bound": check.upper_bound}
        for check in scene.episode.checks
        if (check.target, check.metric) == (target, metric) and parse_utc(check.end) <= scene.clock]
    return {"camera_id": camera_id, "target": target, "metric": metric, "unit": UNITS.get(metric, "m"),
            "points": [{"captured_at": row["captured_at"], "frame_id": row["frame_id"], "value": row["value"],
                        "sigma": row["sigma"]} for row in best.values()],
            "official": official}


def _language(b: Bulletin, lang: render.Lang) -> dict[str, Any]:
    headline, body, _ = render.texts(b, lang)
    # The disclaimer is the code's, never the model's: shown as the code gives it now (bulletins written before
    # the rename to Volcano Vigil name the project Vigía Andino).
    disclaimer = (DISCLAIMER_EN if lang == "en" else DISCLAIMER_ES).format(
        name=b.volcano_name, agency=b.official_agency, url=b.official_url)
    return {"headline": headline, "body": body, "disclaimer": disclaimer,
            "level": render.LEVELS[b.activity_level][0 if lang == "en" else 1],
            "when": render.local_time(b.clock, b.utc_offset_hours),
            "header": render.table_header(lang), "rows": render.table_rows(b, lang),
            "wind_text": render.wind_text(b, lang) if b.wind else None}


def bulletins(scene: Scene, limit: int = 20) -> list[dict[str, Any]]:
    """The volcano's bulletins written by the clock, newest first, in both languages with the published tables."""
    rows = scene.conn.execute("SELECT body FROM bulletins WHERE volcano = ? AND clock <= ? "
                              "ORDER BY clock DESC, id DESC LIMIT ?", (scene.volcano, scene.now, limit)).fetchall()
    out = []
    for row in rows:
        b = Bulletin.model_validate_json(row["body"])
        out.append({"id": b.id, "run_id": b.run_id, "clock": b.clock, "activity_level": b.activity_level,
                    "verified": b.verified, "official_agency": b.official_agency, "official_url": b.official_url,
                    "wind": b.wind, "evidence": [e.model_dump() for e in b.evidence], "notes": b.notes,
                    "en": _language(b, "en"), "es": _language(b, "es")})
    return out


def _parsed(text: str | None) -> Any:
    """A stored JSON text as data; the text itself if it is not JSON (Muse Spark may send broken arguments)."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def agent_trace(scene: Scene, run_id: int | None = None) -> dict[str, Any]:
    """The agent runs by the clock, newest first, and the steps of one: `run_id`, or the newest. LookupError for a
    run after the clock or of another volcano."""
    runs = [{"run_id": row["id"], "clock": row["clock"], "status": row["status"], "turns": row["turns"],
             "cost_usd": row["cost_usd"], "bulletin_id": row["bulletin_id"], "task": row["task"],
             "model": row["model"], "error": row["error"]}
            for row in scene.conn.execute(
                """SELECT r.*, (SELECT MAX(b.id) FROM bulletins b WHERE b.run_id = r.id) AS bulletin_id
                   FROM agent_runs r WHERE r.volcano = ? AND r.clock <= ? ORDER BY r.clock DESC, r.id DESC""",
                (scene.volcano, scene.now))]
    if run_id is None:
        run = runs[0] if runs else None
    else:
        run = next((r for r in runs if r["run_id"] == run_id), None)
        if run is None:
            raise LookupError(f"no agent run {run_id} by {scene.now}")
    steps = [] if run is None else [
        {"seq": row["seq"], "turn": row["turn"], "kind": row["kind"], "text": row["text"],
         "reasoning": row["reasoning"], "tool_name": row["tool_name"], "arguments": _parsed(row["arguments"]),
         "result": _parsed(row["result"]), "ok": None if row["ok"] is None else bool(row["ok"]),
         "cost_usd": row["cost_usd"], "latency_ms": row["latency_ms"]}
        for row in scene.conn.execute("SELECT * FROM agent_steps WHERE run_id = ? ORDER BY seq", (run["run_id"],))]
    return {"runs": runs, "run": run, "steps": steps}


def replay_state(scene: Scene, folder: Path) -> dict[str, Any]:
    """The replay's steps by the clock, HVO's phases whose latest time has passed, and, at the episode's end, the
    comparison with the official values from the replay's timeline.json in `folder`."""
    episode = scene.episode
    if episode is None:
        raise ValueError("a live scene has no replay")
    path = folder / "timeline.json"
    timeline = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    results = None
    if timeline is not None and scene.clock >= episode.end:
        comparison = timeline["comparison"]
        tables = [{"title": title, "header": header, "rows": comparison[key]} for title, header, key in RESULT_TABLES]
        if timeline.get("phases"):
            tables.append({"title": "Episode phases", "header": PHASES_HEADER, "rows": timeline["phases"]["rows"]})
        results = {"tables": tables, "cost_usd": timeline["cost_usd"]}
    return {
        "episode": episode.key, "volcano": episode.volcano, "cameras": list(episode.cameras),
        "start": to_iso(episode.start), "end": to_iso(episode.end),
        "step_minutes": timeline["step_minutes"] if timeline else STEP / timedelta(minutes=1),
        "ticks": [json.loads(row[0]) for row in scene.conn.execute(
            "SELECT report FROM replay_ticks WHERE clock <= ? ORDER BY clock", (scene.now,))],
        "official_phases": {phase: [to_iso(low), to_iso(high)] for phase, (low, high) in episode.phases.items()
                            if high <= scene.clock},
        "results": results,
    }


def frame_image(scene: Scene, frame_id: int, *, width: int, overlay: bool = True) -> bytes:
    """The frame as a JPEG at most `width` pixels wide (never enlarged), with the masks of its detections that exist
    at the clock tinted on it and no legend (the page has one). LookupError for a frame after the clock."""
    row = _frame_row(scene, frame_id)
    if row is None:
        raise LookupError(f"no frame {frame_id} captured by {scene.now}")
    scale = min(1.0, width / row["width"])
    size = (max(1, round(row["width"] * scale)), max(1, round(row["height"] * scale)))
    with Image.open(scene.data_dir / row["path"]) as image:
        image.draft("RGB", size)  # JPEG: decode at a fraction of the size, which is much faster
        picture = image.convert("RGB").resize(size, Image.LANCZOS)
    layers = []
    for d in _detection_rows(scene, [frame_id]) if overlay else []:
        left, top, right, bottom = (round(v * scale) for v in (d["box_left"], d["box_top"], d["box_right"],
                                                                d["box_bottom"]))
        w, h = max(1, right - left), max(1, bottom - top)
        box_mask = masks.decode(json.loads(d["mask_rle"]))
        small = np.asarray(Image.fromarray(box_mask).resize((w, h), Image.NEAREST), dtype=bool)
        full = np.zeros((size[1], size[0]), dtype=bool)
        full[top:top + h, left:left + w] = small[:size[1] - top, :size[0] - left]
        layers.append(Layer(full, COLORS[d["target"]], d["target"]))
    buffer = io.BytesIO()
    draw_layers(picture, layers, legend=False).save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()
