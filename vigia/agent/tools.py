"""The agent's tools: what Muse Spark can look at and do, as strict JSON-schema functions.

Every tool sees the world as of the agent's clock (`ToolContext.now`): live
that is the current time; in a replay it is the simulated time, and frames,
detections and measurements captured after it do not exist. Each tool's
arguments are a Pydantic model whose JSON schema, in the strict subset of
the Responses API, is what Muse Spark sees. The API does not guarantee that
the arguments match it (Muse Spark sent the string "null" for a null while
this was planned), so every call is validated, and a bad call or a failing
tool becomes an error message for the model instead of an exception.
"""

from __future__ import annotations

import itertools
import json
import logging
import math
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from vigia import tracking
from vigia.calibration import Calibration, sample_geometry
from vigia.config import Camera, Sources
from vigia.gate import QualityGate
from vigia.imaging import load_for_upload
from vigia.meta.client import MetaClient
from vigia.meta.ledger import BudgetExceeded
from vigia.metrics import measure_window
from vigia.prompts import Prompts, Target
from vigia.timeutil import parse_utc, to_iso
from vigia.wind import SOURCE_NAMES, SOURCE_URLS, Wind, WindService, WindUnavailable, compare_drift

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=30)
RECENT_FRAMES = 30   # get_recent_frames lists at most this many, newest first
HISTORY_POINTS = 40  # get_history thins longer series to this many points
Metric = Literal["top_height", "top_altitude", "area", "drift_offset", "drift_bearing"]


class ToolError(Exception):
    """A tool cannot do what was asked; the message goes back to the model."""


@dataclass(frozen=True)
class ToolContext:
    conn: sqlite3.Connection
    data_dir: Path
    sources: Sources
    calibration: Calibration
    prompts: Prompts
    winds: WindService
    now: datetime                     # the agent's clock, UTC
    client: MetaClient | None = None  # the tools that call SAM or Muse Spark fail without one

    def __post_init__(self):
        if self.now.tzinfo is None:
            raise ValueError("the agent's clock needs a time zone")

    def camera(self, camera_id: str) -> Camera:
        for camera in self.sources.cameras:
            if camera.id == camera_id:
                return camera
        raise ToolError(f"unknown camera {camera_id!r}; list_cameras_status gives the ids")

    def meta(self) -> MetaClient:
        if self.client is None:
            raise ToolError("this agent has no Meta client, so it cannot call SAM or Muse Spark")
        return self.client


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(Args):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[Args]
    run: Callable[[ToolContext, Any], dict[str, Any]]

    def definition(self) -> dict[str, Any]:
        """The Responses API function tool."""
        return {"type": "function", "name": self.name, "description": self.description,
                "parameters": strict_schema(self.args), "strict": True}


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The arguments' JSON schema in the strict subset: every property required, no others allowed, a nullable
    one typed [type, "null"]. Bounds such as a minimum are left out; Pydantic checks them on every call."""
    properties = {}
    for name, prop in model.model_json_schema().get("properties", {}).items():
        nullable = "anyOf" in prop
        if nullable:
            (inner,) = [option for option in prop["anyOf"] if option.get("type") != "null"]
            prop = {**inner, "description": prop.get("description")}
        if prop.get("type") not in ("string", "integer", "number", "boolean"):
            raise TypeError(f"{model.__name__}.{name}: only scalar arguments are supported")
        out: dict[str, Any] = {"type": [prop["type"], "null"] if nullable else prop["type"]}
        if "enum" in prop:
            out["enum"] = [*prop["enum"], None] if nullable else prop["enum"]
        if prop.get("description"):
            out["description"] = prop["description"]
        properties[name] = out
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _nullable(model: type[BaseModel]) -> list[str]:
    return [name for name, prop in model.model_json_schema().get("properties", {}).items() if "anyOf" in prop]


class Toolbox:
    """The tools of one agent run, bound to its context."""

    def __init__(self, ctx: ToolContext, tools: Sequence[Tool] | None = None):
        self.ctx = ctx
        self._tools = {tool.name: tool for tool in (TOOLS if tools is None else tools)}

    def definitions(self) -> list[dict[str, Any]]:
        return [tool.definition() for tool in self._tools.values()]

    def call(self, name: str, arguments: str) -> tuple[dict[str, Any], bool]:
        """Run one tool call; returns what goes back to the model and whether the call worked."""
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"unknown tool {name!r}; the tools are {', '.join(self._tools)}"}, False
        try:
            raw = json.loads(arguments or "{}")
        except json.JSONDecodeError as exc:
            return {"error": f"the arguments are not JSON: {exc}"}, False
        if not isinstance(raw, dict):
            return {"error": "the arguments must be a JSON object"}, False
        for key in _nullable(tool.args):
            if raw.get(key) in ("null", "None", ""):
                raw[key] = None
        try:
            args = tool.args.model_validate(raw)
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in exc.errors())
            return {"error": f"invalid arguments: {problems}"}, False
        try:
            return tool.run(self.ctx, args), True
        except ToolError as exc:
            return {"error": str(exc)}, False
        except BudgetExceeded as exc:
            return {"error": f"the run's budget is spent: {exc}"}, False
        except Exception as exc:  # a failing tool must not end the run: the model hears about it instead
            log.exception("tool %s failed", name)
            return {"error": f"{name} failed: {type(exc).__name__}: {exc}"[:500]}, False


def _verdict_reasons(row: sqlite3.Row) -> list[str]:
    return json.loads(row["reasons"]) if row["reasons"] else []


def _usable(row: sqlite3.Row) -> bool | None:
    return None if row["usable"] is None else bool(row["usable"])


def _round(value: float, unit: str) -> float:
    return round(value, 1) if unit == "deg" else round(value)


def _point(row: sqlite3.Row) -> dict[str, Any]:
    """A measurement row: when, on which frame, value and sigma."""
    return {"captured_at": row["captured_at"], "frame_id": row["frame_id"],
            "value": _round(row["value"], row["unit"]), "sigma": _round(row["sigma"], row["unit"])}


def _frame(ctx: ToolContext, frame_id: int) -> sqlite3.Row:
    """A stored frame captured by the agent's clock."""
    row = ctx.conn.execute("SELECT * FROM frames WHERE id = ? AND captured_at <= ?",
                           (frame_id, to_iso(ctx.now))).fetchone()
    if row is None:
        raise ToolError(f"no frame {frame_id} captured by {to_iso(ctx.now)}")
    return row


def _when(ctx: ToolContext, when: datetime | None) -> datetime:
    """A time argument in UTC, the agent's clock if None; never after the clock."""
    when = ctx.now if when is None else when.astimezone(timezone.utc)
    if when > ctx.now:
        raise ToolError(f"{to_iso(when)} is after now ({to_iso(ctx.now)})")
    return when


def _volcano(ctx: ToolContext, volcano_id: str) -> None:
    if volcano_id not in ctx.sources.volcanoes:
        raise ToolError(f"unknown volcano {volcano_id!r}; the volcanoes are {', '.join(ctx.sources.volcanoes)}")


# --- list_cameras_status


def list_cameras_status(ctx: ToolContext, args: NoArgs) -> dict[str, Any]:
    now, hour_ago = to_iso(ctx.now), to_iso(ctx.now - timedelta(hours=1))
    cameras = []
    for camera in ctx.sources.cameras:
        latest = ctx.conn.execute(
            """SELECT f.id, f.captured_at, q.usable, q.reasons FROM frames f
               LEFT JOIN frame_quality q ON q.frame_id = f.id
               WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ?
               ORDER BY f.captured_at DESC LIMIT 1""",
            (camera.id, to_iso(ctx.now - timedelta(hours=24)), now)).fetchone()
        if latest is None and not camera.enabled:
            continue
        hour = ctx.conn.execute(
            """SELECT COUNT(*) AS frames, COALESCE(SUM(q.usable), 0) AS usable FROM frames f
               LEFT JOIN frame_quality q ON q.frame_id = f.id
               WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ?""", (camera.id, hour_ago, now)).fetchone()
        seen = ctx.conn.execute(
            """SELECT r.target, MAX(f.captured_at) AS last FROM detections d JOIN frames f ON f.id = d.frame_id
               JOIN tracks t ON t.id = d.track_id JOIN tracking_runs r ON r.id = t.run_id
               WHERE r.camera_id = ? AND f.captured_at BETWEEN ? AND ? GROUP BY r.target""",
            (camera.id, hour_ago, now)).fetchall()
        cameras.append({
            "camera_id": camera.id, "name": camera.name, "volcano": camera.volcano, "kind": camera.kind,
            "enabled": camera.enabled,
            "status": _status(ctx, latest),
            "latest_frame": None if latest is None else {
                "frame_id": latest["id"], "captured_at": latest["captured_at"],
                "minutes_ago": round((ctx.now - parse_utc(latest["captured_at"])).total_seconds() / 60, 1),
                "usable": _usable(latest), "reasons": _verdict_reasons(latest)},
            "frames_last_hour": hour["frames"], "usable_last_hour": hour["usable"],
            "calibrated": _calibrated(ctx, camera.id, ctx.now),
            "last_detection": {row["target"]: row["last"] for row in seen},
        })
    return {"now": now, "cameras": cameras}


def _calibrated(ctx: ToolContext, camera_id: str, when: datetime) -> bool:
    """Whether a preset covers the camera at `when` and its references fix the view (a two-sample solve)."""
    preset = ctx.calibration.preset_for(camera_id, when)
    if preset is None:
        return False
    try:
        sample_geometry(ctx.calibration, camera_id, preset, samples=2)
    except ValueError:
        return False
    return True


def _status(ctx: ToolContext, latest: sqlite3.Row | None) -> str:
    if latest is None:
        return "no_frames"
    if ctx.now - parse_utc(latest["captured_at"]) > STALE_AFTER:
        return "stale"
    if latest["usable"] is None:
        return "unassessed"
    return "usable" if latest["usable"] else "rejected"


# --- get_recent_frames


class RecentFramesArgs(Args):
    camera_id: str = Field(description="camera id, e.g. kilauea-kp")
    hours: float = Field(gt=0, le=24, description="how far back from now to look, in hours (at most 24)")


def get_recent_frames(ctx: ToolContext, args: RecentFramesArgs) -> dict[str, Any]:
    camera = ctx.camera(args.camera_id)
    rows = ctx.conn.execute(
        """SELECT f.id, f.captured_at, q.usable, q.reasons FROM frames f
           LEFT JOIN frame_quality q ON q.frame_id = f.id
           WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ? ORDER BY f.captured_at DESC""",
        (camera.id, to_iso(ctx.now - timedelta(hours=args.hours)), to_iso(ctx.now))).fetchall()
    shown = rows[:RECENT_FRAMES]
    found: dict[int, dict[str, int]] = defaultdict(dict)
    if shown:
        marks = ",".join("?" * len(shown))
        for row in ctx.conn.execute(
                f"""SELECT d.frame_id, r.target, COUNT(*) AS n FROM detections d JOIN tracks t ON t.id = d.track_id
                    JOIN tracking_runs r ON r.id = t.run_id
                    WHERE d.frame_id IN ({marks}) GROUP BY d.frame_id, r.target""", [row["id"] for row in shown]):
            found[row["frame_id"]][row["target"]] = row["n"]
    rejected = Counter(reason for row in rows if row["usable"] == 0 for reason in _verdict_reasons(row))
    return {
        "camera_id": camera.id, "frames": len(rows),
        "usable": sum(row["usable"] == 1 for row in rows),
        "unassessed": sum(row["usable"] is None for row in rows),
        "rejected_by_reason": dict(rejected),
        "recent": [{"frame_id": row["id"], "captured_at": row["captured_at"], "usable": _usable(row),
                    "reasons": _verdict_reasons(row), "detections": found.get(row["id"], {})} for row in shown],
    }


# --- get_history


class HistoryArgs(Args):
    camera_id: str = Field(description="camera id, e.g. kilauea-kp")
    metric: Metric = Field(description="top_height (m above the vent), top_altitude (m above sea level), area (m2), "
                                       "drift_offset (m) or drift_bearing (degrees)")
    target: Target = Field(description="what was tracked: plume, fountain or incandescence")
    hours: float = Field(gt=0, le=48, description="how far back from now, in hours (at most 48)")


def get_history(ctx: ToolContext, args: HistoryArgs) -> dict[str, Any]:
    camera = ctx.camera(args.camera_id)
    rows = ctx.conn.execute(
        """SELECT captured_at, frame_id, value, sigma, unit FROM measurements
           WHERE camera_id = ? AND target = ? AND metric = ? AND captured_at BETWEEN ? AND ?
           ORDER BY captured_at, value DESC""",
        (camera.id, args.target, args.metric, to_iso(ctx.now - timedelta(hours=args.hours)),
         to_iso(ctx.now))).fetchall()
    best: dict[str, sqlite3.Row] = {}
    for row in rows:  # the highest detection of each frame
        best.setdefault(row["captured_at"], row)
    points = list(best.values())
    head = {"camera_id": camera.id, "metric": args.metric, "target": args.target}
    if not points:
        return {**head, "points": [], "note": "no measurements in that span: track the camera (track_window) "
                                              "and measure its tracks (measure_track) first"}
    values = np.array([point["value"] for point in points])
    keep = sorted(set(np.linspace(0, len(points) - 1, min(len(points), HISTORY_POINTS)).round().astype(int)))
    result = {**head, "unit": points[0]["unit"], "frames": len(points), "latest": _point(points[-1])}
    if args.metric != "drift_bearing":  # the extremes of a bearing mean nothing (359 degrees against 1)
        result |= {"max": _point(points[int(values.argmax())]), "min": _point(points[int(values.argmin())])}
    return result | {"points": [_point(points[i]) for i in keep]}


# --- assess_frame


class FrameArgs(Args):
    frame_id: int = Field(description="frame id, from list_cameras_status or get_recent_frames")


def _quality(ctx: ToolContext, frame_id: int) -> sqlite3.Row | None:
    return ctx.conn.execute("SELECT * FROM frame_quality WHERE frame_id = ?", (frame_id,)).fetchone()


def assess_frame(ctx: ToolContext, args: FrameArgs) -> dict[str, Any]:
    frame = _frame(ctx, args.frame_id)
    row = _quality(ctx, frame["id"])
    if row is None or (row["spark_answer"] is None and row["local_decision"] != "reject"):
        # Muse Spark looks at every frame the local checks did not reject; a rejected frame costs nothing
        gate = QualityGate(ctx.conn, ctx.data_dir, ctx.sources, ctx.client)
        verdict = gate.assess(frame["id"], spark="never")
        if verdict.local.decision != "reject":
            gate = QualityGate(ctx.conn, ctx.data_dir, ctx.sources, ctx.meta())
            gate.assess(frame["id"], spark="all")
        row = _quality(ctx, frame["id"])
    answer = json.loads(row["spark_answer"]) if row["spark_answer"] else {}
    return {
        "frame_id": frame["id"], "camera_id": frame["camera_id"], "captured_at": frame["captured_at"],
        "usable": bool(row["usable"]), "decided_by": row["decided_by"], "reasons": _verdict_reasons(row),
        "sun_elevation_deg": None if row["sun_elevation_deg"] is None else round(row["sun_elevation_deg"], 1),
        "view": answer.get("view"), "activity": answer.get("activity"),
        "visible_features": answer.get("visible_features", []), "description": answer.get("description_en"),
        "printed_time": row["printed_time"],
        "printed_ptz": json.loads(row["printed_ptz"]) if row["printed_ptz"] else None,
    }


# --- segment_frame


SEGMENT_OBJECTS = 10


class SegmentArgs(Args):
    frame_id: int = Field(description="frame id")
    phrase: str = Field(min_length=1, max_length=60,
                        description="ONE short noun phrase, e.g. 'steam' or 'lava fountain'")


def segment_frame(ctx: ToolContext, args: SegmentArgs) -> dict[str, Any]:
    frame = _frame(ctx, args.frame_id)
    client = ctx.meta()
    image, jpeg = load_for_upload(ctx.data_dir / frame["path"])
    objects = client.segment_image(jpeg, args.phrase, purpose="segment")
    sx, sy = frame["width"] / image.width, frame["height"] / image.height
    found = []
    for obj in sorted(objects, key=lambda o: -(o.score or 0.0))[:SEGMENT_OBJECTS]:
        left, top, right, bottom = obj.box
        rows = np.nonzero(obj.mask.any(axis=1))[0]
        found.append({
            "object_id": obj.object_id, "score": None if obj.score is None else round(obj.score, 3),
            "box": [round(left * sx), round(top * sy), round(right * sx), round(bottom * sy)],
            "top_row": round((top + rows.min()) * sy) if rows.size else None,
            "area_fraction": round(obj.area_px / (image.width * image.height), 5),
        })
    return {"frame_id": frame["id"], "camera_id": frame["camera_id"], "phrase": args.phrase,
            "objects_found": len(objects), "objects": found}


# --- track_window


MAX_TRACK_HOURS = 3
MIN_TRACK_FRAMES = 10


class TrackArgs(Args):
    camera_id: str = Field(description="camera id")
    start: AwareDatetime = Field(description="window start, UTC, e.g. 2026-10-17T14:00:00Z")
    end: AwareDatetime = Field(description="window end, UTC; clipped to now")
    target: Target = Field(description="plume, fountain or incandescence")


def track_window_tool(ctx: ToolContext, args: TrackArgs) -> dict[str, Any]:
    camera = ctx.camera(args.camera_id)
    start, end = args.start.astimezone(timezone.utc), min(args.end.astimezone(timezone.utc), ctx.now)
    if start >= end:
        raise ToolError(f"the window must start before it ends and before now ({to_iso(ctx.now)})")
    if end - start > timedelta(hours=MAX_TRACK_HOURS):
        raise ToolError(f"windows are limited to {MAX_TRACK_HOURS} hours")
    frames = tracking.usable_frames(ctx.conn, ctx.data_dir, camera.id, start, end)
    if not frames:
        raise ToolError(f"{camera.id} has no usable frames between {to_iso(start)} and {to_iso(end)}")
    run_ids = _covering_runs(ctx.conn, camera.id, args.target, start, end, {frame.id for frame in frames})
    cached = bool(run_ids)
    if not cached:
        if len(frames) < MIN_TRACK_FRAMES:
            raise ToolError(f"only {len(frames)} usable frames in the window; tracking needs {MIN_TRACK_FRAMES} "
                            "(and SAM bills 50 per request anyway), so widen it")
        try:
            report = tracking.track_window(ctx.meta(), ctx.conn, ctx.data_dir, camera, ctx.prompts, start, end,
                                           targets=[args.target])
        except ValueError as exc:
            if "already tracked" not in str(exc):
                raise
            raise ToolError("stored runs of exactly this window exist but miss frames that became usable since; "
                            "shift or widen the window by a few minutes") from exc
        if not report.runs:
            raise ToolError("tracking stored nothing: " + ("; ".join(report.errors)
                                                         or f"no {args.target} phrase for a {camera.kind} camera"))
        run_ids = [run.run_id for run in report.runs]
    return {"camera_id": camera.id, "target": args.target, "start": to_iso(start), "end": to_iso(end),
            "usable_frames": len(frames), "cached": cached, "tracks": _tracks(ctx.conn, run_ids, start, end)}


def _covering_runs(conn: sqlite3.Connection, camera_id: str, target: str, start: datetime, end: datetime,
                   wanted: set[int]) -> list[int]:
    """The stored runs of the camera and target over the window, if together they include every wanted frame."""
    chosen, covered = [], set()
    for row in conn.execute(
            """SELECT id, frame_ids FROM tracking_runs
               WHERE camera_id = ? AND target = ? AND window_start <= ? AND window_end >= ? ORDER BY id""",
            (camera_id, target, to_iso(end), to_iso(start))):
        frames = wanted & set(json.loads(row["frame_ids"]))
        if frames:
            chosen.append(row["id"])
            covered |= frames
    return chosen if covered >= wanted else []


def _tracks(conn: sqlite3.Connection, run_ids: list[int], start: datetime, end: datetime) -> list[dict[str, Any]]:
    marks = ",".join("?" * len(run_ids))
    rows = conn.execute(
        f"""SELECT t.id, t.object_id, r.phrase, COUNT(*) AS detections, MIN(f.captured_at) AS first_seen,
                   MAX(f.captured_at) AS last_seen, AVG(d.score) AS mean_score, MAX(d.area_px) AS max_area_px
            FROM tracks t JOIN tracking_runs r ON r.id = t.run_id JOIN detections d ON d.track_id = t.id
            JOIN frames f ON f.id = d.frame_id
            WHERE t.run_id IN ({marks}) AND f.captured_at BETWEEN ? AND ?
            GROUP BY t.id ORDER BY detections DESC, t.id""", (*run_ids, to_iso(start), to_iso(end))).fetchall()
    return [{"track_id": row["id"], "phrase": row["phrase"], "object_id": row["object_id"],
             "detections": row["detections"], "first_seen": row["first_seen"], "last_seen": row["last_seen"],
             "mean_score": None if row["mean_score"] is None else round(row["mean_score"], 2),
             "max_area_px": row["max_area_px"]} for row in rows]


# --- measure_track


class TrackIdArgs(Args):
    track_id: int = Field(description="track id, from track_window")


def measure_track(ctx: ToolContext, args: TrackIdArgs) -> dict[str, Any]:
    track = ctx.conn.execute(
        """SELECT t.id, r.camera_id, r.target, r.phrase FROM tracks t JOIN tracking_runs r ON r.id = t.run_id
           WHERE t.id = ?""", (args.track_id,)).fetchone()
    if track is None:
        raise ToolError(f"no track {args.track_id}")
    now = to_iso(ctx.now)
    span = ctx.conn.execute(
        """SELECT MIN(f.captured_at) AS first, MAX(f.captured_at) AS last FROM detections d
           JOIN frames f ON f.id = d.frame_id WHERE d.track_id = ? AND f.captured_at <= ?""",
        (track["id"], now)).fetchone()
    if span["first"] is None:
        raise ToolError(f"track {track['id']} has no detections by {now}")
    camera_id = track["camera_id"]
    if camera_id not in ctx.calibration.cameras:
        raise ToolError(f"{camera_id} is not calibrated, so its tracks cannot be measured; its detections still "
                        "show what it sees")
    report = measure_window(ctx.conn, ctx.calibration, camera_id, parse_utc(span["first"]), parse_utc(span["last"]))
    rows = ctx.conn.execute(
        """SELECT m.metric, m.value, m.sigma, m.unit, m.captured_at, m.frame_id FROM measurements m
           JOIN detections d ON d.id = m.detection_id WHERE d.track_id = ? AND m.captured_at <= ?
           ORDER BY m.captured_at""", (track["id"], now)).fetchall()
    if not rows:
        problems = report.errors or [f"{report.uncalibrated} detections lie on frames no calibration preset covers"]
        raise ToolError(f"track {track['id']} could not be measured: {'; '.join(problems)}")
    series: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        series[row["metric"]].append(row)
    metrics = {}
    for metric, values in series.items():
        latest = values[-1]
        summary = {"unit": latest["unit"], "frames": len(values), "latest": _point(latest)}
        if metric == "drift_bearing":
            summary["frames_per_side"] = dict(Counter(str(round(row["value"])) for row in values))
        else:
            numbers = np.array([row["value"] for row in values])
            summary["max"] = _point(values[int(numbers.argmax())])
            summary["mean"] = _round(float(numbers.mean()), latest["unit"])
        metrics[metric] = summary
    return {"track_id": track["id"], "camera_id": camera_id, "target": track["target"], "phrase": track["phrase"],
            "first": span["first"], "last": span["last"], "metrics": metrics}


# --- get_wind


class WindArgs(Args):
    volcano: str = Field(description="volcano id, e.g. kilauea")
    altitude_m: float = Field(ge=0, le=20000, description="metres above sea level, e.g. a plume's top_altitude")
    time: AwareDatetime | None = Field(default=None, description="UTC time of the measurement; null for now")
    drift_bearing_deg: float | None = Field(default=None, ge=0, lt=360,
                                            description="a measured drift side (drift_bearing from measure_track) "
                                                        "to check against the wind; null to skip the check")


def _wind_json(wind: Wind) -> dict[str, Any]:
    return {"from_deg": round(wind.from_deg) % 360, "toward_deg": round(wind.toward_deg) % 360,
            "speed_ms": round(wind.speed_ms, 1)}


def get_wind(ctx: ToolContext, args: WindArgs) -> dict[str, Any]:
    _volcano(ctx, args.volcano)
    when = _when(ctx, args.time)
    try:
        profile = ctx.winds.profile(args.volcano, when)
    except WindUnavailable as exc:
        raise ToolError(str(exc)) from exc
    vent = ctx.calibration.vents.get(args.volcano)
    bottom = vent.elev_m if vent is not None else profile.levels[0].altitude_m
    mean = profile.layer_mean(bottom, args.altitude_m)
    result = {
        "volcano": args.volcano, "model_hour": to_iso(profile.valid_at), "source": SOURCE_NAMES[profile.source],
        "source_url": SOURCE_URLS[profile.source], "altitude_m": round(args.altitude_m),
        "at_altitude": _wind_json(profile.at(args.altitude_m)),
        "layer_mean": {"bottom_m": round(bottom), "top_m": round(max(args.altitude_m, bottom)), **_wind_json(mean)},
        "levels": [{"pressure_hpa": level.pressure_hpa, "altitude_m": round(level.altitude_m), **_wind_json(level.wind)}
                   for level in profile.levels],
    }
    if args.drift_bearing_deg is not None:
        check = compare_drift(args.drift_bearing_deg, mean)
        result["drift_check"] = {"measured_side_deg": round(check.side_deg, 1),
                                 "wind_toward_deg": round(check.toward_deg) % 360,
                                 "angle_deg": round(check.angle_deg, 1), "consistent": check.consistent}
    return result


# --- compare_cameras


NEAR = timedelta(minutes=10)


class CompareArgs(Args):
    volcano: str = Field(description="volcano id, e.g. kilauea")
    time: AwareDatetime | None = Field(default=None, description="UTC time to compare at; null for now")


def compare_cameras(ctx: ToolContext, args: CompareArgs) -> dict[str, Any]:
    _volcano(ctx, args.volcano)
    when = _when(ctx, args.time)
    low, high = to_iso(when - NEAR), to_iso(min(when + NEAR, ctx.now))
    cameras, heights = [], defaultdict(dict)  # (target, metric) -> {camera id: (value, sigma)}
    for camera in ctx.sources.cameras:
        if camera.volcano != args.volcano:
            continue
        frames = ctx.conn.execute(
            """SELECT f.id, f.captured_at, q.usable FROM frames f LEFT JOIN frame_quality q ON q.frame_id = f.id
               WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ?""", (camera.id, low, high)).fetchall()
        if not frames:
            continue
        frame = min(frames, key=lambda row: abs(parse_utc(row["captured_at"]) - when))
        detections = ctx.conn.execute(
            """SELECT d.id, r.target FROM detections d JOIN tracks t ON t.id = d.track_id
               JOIN tracking_runs r ON r.id = t.run_id WHERE d.frame_id = ? ORDER BY d.area_px DESC, d.id""",
            (frame["id"],)).fetchall()
        largest: dict[str, int] = {}
        for row in detections:
            largest.setdefault(row["target"], row["id"])
        measured = {}
        for target, detection_id in largest.items():
            rows = ctx.conn.execute("SELECT metric, value, sigma, unit FROM measurements WHERE detection_id = ?",
                                    (detection_id,)).fetchall()
            if rows:
                measured[target] = {row["metric"]: {"value": _round(row["value"], row["unit"]),
                                                    "sigma": _round(row["sigma"], row["unit"]), "unit": row["unit"]}
                                    for row in rows}
                for row in rows:
                    heights[(target, row["metric"])][camera.id] = (row["value"], row["sigma"])
        cameras.append({"camera_id": camera.id, "frame_id": frame["id"], "captured_at": frame["captured_at"],
                        "usable": _usable(frame), "detections": dict(Counter(row["target"] for row in detections)),
                        "calibrated": _calibrated(ctx, camera.id, parse_utc(frame["captured_at"])),
                        "measurements": measured})
    if not cameras:
        raise ToolError(f"no {args.volcano} camera has a frame within 10 minutes of {to_iso(when)}")
    agreement = []
    for (target, metric), by_camera in sorted(heights.items()):
        if metric not in ("top_height", "top_altitude"):
            continue
        for a, b in itertools.combinations(sorted(by_camera), 2):
            (value_a, sigma_a), (value_b, sigma_b) = by_camera[a], by_camera[b]
            sigma = math.hypot(sigma_a, sigma_b)
            agreement.append({"target": target, "metric": metric, "cameras": [a, b],
                              "difference_m": round(value_a - value_b), "sigma_m": round(sigma),
                              "z": round((value_a - value_b) / sigma, 1) if sigma else None})
    return {"volcano": args.volcano, "time": to_iso(when), "cameras": cameras, "agreement": agreement,
            "note": "" if agreement else "fewer than two cameras measured the same height, so nothing is cross-checked"}


TOOLS: list[Tool] = [
    Tool("list_cameras_status",
         "Every camera that is enabled or sent frames in the last 24 hours, as of now: its latest frame and quality "
         "verdict; its status (usable, rejected, unassessed, stale when the latest frame is over 30 minutes old, or "
         "no_frames); frames and usable frames in the last hour; whether it is calibrated (only calibrated cameras "
         "give heights); and when each target (plume, fountain, incandescence) was last detected in the last hour.",
         NoArgs, list_cameras_status),
    Tool("get_recent_frames",
         "A camera's frames from the last `hours`, newest first (at most 30 listed): each frame's quality verdict "
         "and how many objects of each target its stored tracks detected on it, plus counts of usable frames and "
         "of rejections by reason.",
         RecentFramesArgs, get_recent_frames),
    Tool("assess_frame",
         "Look at one frame through the quality gate: local checks, then Muse Spark (about $0.008) unless they "
         "rejected it or Muse Spark has already seen it. Returns whether the frame is usable and why, the activity "
         "and features Muse Spark sees, a description, and the time and pan/tilt/zoom printed on it.",
         FrameArgs, assess_frame),
    Tool("segment_frame",
         "Run SAM 3.1 on one frame for ONE short noun phrase ($0.0025). Returns up to 10 objects, best first: "
         "score, box and highest row in the frame's pixels, and the share of the image each covers. Tuned "
         "phrases: 'steam' for a plume, 'lava fountain', 'glow' for incandescence ('glowing lava' on thermal "
         "cameras); a phrase with 'volcanic' in it returns the fountain.",
         SegmentArgs, segment_frame),
    Tool("track_window",
         "Track a target through a camera's usable frames between start and end (at most 3 hours, clipped to now) "
         "with SAM 3.1 video and the target's tuned phrases. If stored runs already cover every usable frame of the "
         "window it returns their tracks at no cost; otherwise it tracks the window (about $0.01 per phrase, a few "
         "minutes; needs 10 usable frames). Returns each track's id, phrase, detections in the window, and first "
         "and last detection.",
         TrackArgs, track_window_tool),
    Tool("measure_track",
         "Measure a track's detections up to now on the vertical plane through the vent: top_height (m above the "
         "vent) and top_altitude (m above sea level) of the mask's highest pixel, area (m2), and for plumes "
         "drift_offset (m across the line of sight, positive to the right) and drift_bearing (the bearing of the "
         "side of the line of sight the plume sits on). Each value has a one-sigma uncertainty from a Monte Carlo "
         "over the calibration. Returns per metric the latest, the maximum and the mean with frame ids. Only "
         "calibrated cameras can be measured.",
         TrackIdArgs, measure_track),
    Tool("get_wind",
         "The model wind over a volcano at an hour (Open-Meteo, 850 to 300 hPa): the wind at an altitude, the mean "
         "wind between the vent and that altitude, and every level. Pass a plume's top_altitude and its measured "
         "drift_bearing to check the drift: the check gives the angle between that side and where the layer's mean "
         "wind blows; under 90 degrees the wind pushes the plume to the side it was seen on.",
         WindArgs, get_wind),
    Tool("compare_cameras",
         "Line up every camera of a volcano at one time: each camera's frame nearest to it (within 10 minutes), its "
         "quality, what its tracks detected there, the measurements of the largest detection per target, and, when "
         "two cameras measured the same height, their difference against the combined sigma.",
         CompareArgs, compare_cameras),
    Tool("get_history",
         "A camera's series of one metric for one target over the last `hours` (at most 48): the highest "
         "detection on each frame, thinned to 40 points, with the latest, maximum and minimum and their frame ids (for drift_bearing only "
         "the latest and the points).",
         HistoryArgs, get_history),
]
