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

import json
import logging
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vigia.calibration import Calibration
from vigia.config import Camera, Sources
from vigia.gate import QualityGate
from vigia.imaging import load_for_upload
from vigia.meta.client import MetaClient
from vigia.prompts import Prompts, Target
from vigia.timeutil import parse_utc, to_iso
from vigia.wind import WindService

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
            "calibrated": ctx.calibration.preset_for(camera.id, ctx.now) is not None,
            "last_detection": {row["target"]: row["last"] for row in seen},
        })
    return {"now": now, "cameras": cameras}


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
    return {**head, "unit": points[0]["unit"], "frames": len(points), "latest": _point(points[-1]),
            "max": _point(points[int(values.argmax())]), "min": _point(points[int(values.argmin())]),
            "points": [_point(points[i]) for i in keep]}


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
    Tool("get_history",
         "A camera's series of one metric for one target over the last `hours` (at most 48): the highest "
         "detection on each frame, thinned to 40 points, with the latest, maximum and minimum and their frame ids.",
         HistoryArgs, get_history),
]
