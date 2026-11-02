"""Bulletins: what the agent tells the public about a volcano, in English, with its evidence.

Muse Spark writes a draft as the final answer of an agent run, in the strict JSON format DRAFT_FORMAT: a
descriptive activity level (what the cameras show, never an alert level), a headline and a body, the
measurements the body quotes and the frames that show them. The code adds what must never depend
on the model: the volcano's official agency and link, the disclaimer, the wind check as the get_wind tool
returned it, an overlay of each evidence frame with its masks, and a check of every quoted number against the
stored measurements up to the agent's clock (a number nothing stored supports is marked unverified). Bulletins
are stored in the `bulletins` table; vigil.agent.render turns them into Markdown and HTML. Evidence overlays are
JPEGs at most 1,280 pixels wide, in the bulletin's folder.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple, get_args

import httpx
import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vigil import db
from vigil.agent.loop import (BUDGET_USD, DEFAULT_TASK, MAX_TURNS, AgentRun, context_from_settings, run_agent,
                              trace)
from vigil.agent.render import local_time, publish, to_markdown
from vigil.agent.tools import Metric, ToolContext
from vigil.config import load_sources
from vigil.meta.client import MetaClient
from vigil.meta.ledger import CostLedger
from vigil.overlay import Layer, draw_layers
from vigil.prompts import Target
from vigil.settings import Settings
from vigil.timeutil import parse_utc, to_iso, utcnow
from vigil.tracking import detection_mask

ActivityLevel = Literal["no_view", "quiet", "degassing", "incandescence", "fountaining"]
Unit = Literal["m", "m2", "deg"]
EVIDENCE_MAX = 3
OVERLAY_WIDTH = 1280  # evidence overlays are scaled down to this width
COLORS = {"plume": (80, 200, 255), "fountain": (255, 90, 30), "incandescence": (255, 210, 0)}
TOLERANCE = {"m": 1.0, "m2": 1.0, "deg": 0.1}  # what rounding can change in a quoted number
DISCLAIMER = ("Automated, experimental reading of public webcams by Volcano Vigil. It does not replace official "
              "alerts or warnings. For the official status of {name}, see {agency}: {url}")

BULLETIN_FINISH = """\
Finish with a bulletin for the public, in English, as the JSON your answer format describes:
- activity_level: what the cameras show now. It describes, it never sets an alert level: no_view (no camera can see \
the vent: cloud, fog, darkness or no fresh frames), quiet (a clear view with no plume, glow or fountain), degassing \
(a gas or steam plume and no glowing lava), incandescence (glowing lava but no fountain), fountaining (a lava \
fountain).
- headline: one sentence. body: three to six sentences on what each useful camera shows, the measurements with \
± sigma, units and local times, the drift against the wind, and what could not be measured and why. Write the \
body's numbers as people read them, rounded to what the sigma supports: 6,951 ± 429 m, an area of about 20.6 km², \
3.3 m/s.
- measurements: every number the body quotes from measure_track or get_history, exactly as the tool returned it \
(value and sigma), with its camera, target, metric, unit and the frame ids it came from. Quote per-frame values \
(latest or max), not means.
- evidence: one to three frames that best show what you describe, each with the target whose mask to draw and a \
short caption.
- drift_bearing is the side of the camera's line of sight the plume sits on, not the direction it travels.
Do not write a disclaimer or the official source: every bulletin gets them."""


class EvidenceError(Exception):
    """An evidence frame cannot be drawn; the message says why."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftMeasurement(_Strict):
    camera_id: str
    target: Target
    metric: Metric
    value: float
    sigma: float = Field(ge=0)
    unit: Unit
    frame_ids: list[int] = Field(min_length=1)


class DraftEvidence(_Strict):
    frame_id: int
    target: Target
    caption: str


class BulletinDraft(_Strict):
    """What Muse Spark writes."""

    activity_level: ActivityLevel
    headline: str = Field(min_length=1)
    body: str = Field(min_length=1)
    measurements: list[DraftMeasurement]
    evidence: list[DraftEvidence]


class CitedMeasurement(DraftMeasurement):
    verified: bool                  # a stored measurement on one of its frames, captured by the clock, matches it
    captured_at: str | None = None  # UTC capture time of that frame


class Evidence(DraftEvidence):
    camera_id: str
    captured_at: str  # UTC
    overlay: str      # the frame with the target's masks drawn, relative to the data dir (POSIX)


class Bulletin(_Strict):
    """A published bulletin: the draft, checked, plus what never depends on the model."""

    id: int | None = None
    run_id: int
    volcano: str
    volcano_name: str
    utc_offset_hours: float | None
    clock: str       # UTC: the time it describes, the agent's clock
    created_at: str  # UTC wall clock
    activity_level: ActivityLevel
    headline: str
    body: str
    measurements: list[CitedMeasurement]
    evidence: list[Evidence]
    wind: dict[str, Any] | None  # the run's last get_wind result that checked a drift, without its levels
    official_agency: str
    official_url: str
    disclaimer: str
    notes: list[str] = []  # what the code left out or could not support
    text_checked: bool = True  # every length and area in the headline and body matches a verified measurement

    @property
    def verified(self) -> bool:
        return self.text_checked and all(m.verified for m in self.measurements)


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _enum(literal: Any) -> dict[str, Any]:
    return {"type": "string", "enum": list(get_args(literal))}


DRAFT_SCHEMA = _object({
    "activity_level": _enum(ActivityLevel),
    "headline": {"type": "string"},
    "body": {"type": "string"},
    "measurements": {"type": "array", "items": _object({
        "camera_id": {"type": "string"}, "target": _enum(Target), "metric": _enum(Metric),
        "value": {"type": "number"}, "sigma": {"type": "number"}, "unit": _enum(Unit),
        "frame_ids": {"type": "array", "items": {"type": "integer"}}})},
    "evidence": {"type": "array", "items": _object({
        "frame_id": {"type": "integer"}, "target": _enum(Target),
        "caption": {"type": "string"}})},
})
DRAFT_FORMAT = {"type": "json_schema", "name": "bulletin", "schema": DRAFT_SCHEMA, "strict": True}


def _close(quoted: float, stored: float, unit: str) -> bool:
    gap = abs(quoted - stored)
    if unit == "deg":
        gap = min(gap % 360, 360 - gap % 360)  # bearings wrap: 359.95 is 0.05 from 0
    return gap <= TOLERANCE[unit]


class Quote(NamedTuple):
    """A length or an area written in a text, in metres or square metres."""

    value: float
    half_step: float  # half a unit of its last written digit
    dimension: Literal["length", "area"]
    written: str


_NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_UNIT = (r"square\s+(?P<sq>kilomet(?:re|er)s?|met(?:re|er)s?)|(?P<area>km²|km2|m²|m2)|"
         r"(?P<length>kilomet(?:re|er)s?|met(?:re|er)s?|km|m)")
_QUOTE = re.compile(rf"(?<![\w.,])(?P<value>{_NUMBER})(?:\s*(?:±|\+/-)\s*(?P<sigma>{_NUMBER}))?\s*(?P<unit>{_UNIT})"
                    r"(?![\w/])(?!\s+per\b)", re.IGNORECASE)


def _quote(number: str, unit: str, kilo: bool, dimension: str) -> Quote:
    decimals = len(number.split(".")[1]) if "." in number else 0
    factor = (1000 if kilo else 1) ** (2 if dimension == "area" else 1)
    return Quote(round(float(number.replace(",", "")) * factor, 6), round(0.5 * 10 ** -decimals * factor, 6),
                 dimension, f"{number} {unit}")  # type: ignore[arg-type]


def quoted_numbers(text: str) -> list[Quote]:
    """Every length and area written in the text with a unit: m, km, metres, kilometres (also meters,
    kilometers) and m², km², m2, km2, square metres, square kilometres. Both numbers of "6,951 ± 429 m" count.
    Speeds (m/s, km/h, per hour), feet and numbers with no unit do not."""
    found = []
    for match in _QUOTE.finditer(text):
        unit = " ".join(match["unit"].split())
        if match["sq"]:
            dimension, kilo = "area", match["sq"].lower().startswith("k")
        elif match["area"]:
            dimension, kilo = "area", match["area"].lower().startswith("k")
        else:
            dimension, kilo = "length", match["length"].lower().startswith("k")
        for number in (match["value"], match["sigma"]):
            if number:
                found.append(_quote(number, unit, kilo, dimension))
    return found


def supports(quote: Quote, checked: list[tuple[str, float]]) -> bool:
    """Whether a checked (unit, number) pair, a value or sigma in m or m2, is the quote's number to the precision
    it is written to, plus the stored rounding."""
    unit = "m" if quote.dimension == "length" else "m2"
    return any(u == unit and abs(quote.value - number) <= quote.half_step + TOLERANCE[unit]
               for u, number in checked)


def verify(conn: sqlite3.Connection, measurement: DraftMeasurement, clock: datetime) -> CitedMeasurement:
    """The quoted measurement, verified if a stored one of its camera, target, metric and unit, on one of its
    frames and captured by the clock, has its value and sigma."""
    marks = ",".join("?" * len(measurement.frame_ids))
    rows = conn.execute(
        f"""SELECT value, sigma, captured_at FROM measurements
            WHERE camera_id = ? AND target = ? AND metric = ? AND unit = ? AND frame_id IN ({marks})
            AND captured_at <= ? ORDER BY captured_at DESC""",
        (measurement.camera_id, measurement.target, measurement.metric, measurement.unit, *measurement.frame_ids,
         to_iso(clock))).fetchall()
    for row in rows:
        if (_close(measurement.value, row["value"], measurement.unit)
                and _close(measurement.sigma, row["sigma"], measurement.unit)):
            return CitedMeasurement(**measurement.model_dump(), verified=True, captured_at=row["captured_at"])
    return CitedMeasurement(**measurement.model_dump(), verified=False)


def run_wind(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    """The run's last successful get_wind result that checked a drift, without its level list."""
    for row in conn.execute(
            "SELECT result FROM agent_steps WHERE run_id = ? AND tool_name = 'get_wind' AND ok = 1 ORDER BY seq DESC",
            (run_id,)):
        result = json.loads(row["result"])
        if "drift_check" in result:
            return {key: value for key, value in result.items() if key != "levels"}
    return None


def draw_evidence(conn: sqlite3.Connection, data_dir: Path, folder: Path, item: DraftEvidence,
                  clock: datetime) -> Evidence | None:
    """Draw the target's masks on the evidence frame into `folder` (inside the data dir); None if no such frame
    was captured by the clock. Raises EvidenceError if the frame's image cannot be read."""
    frame = conn.execute("SELECT * FROM frames WHERE id = ? AND captured_at <= ?",
                         (item.frame_id, to_iso(clock))).fetchone()
    if frame is None:
        return None
    detections = conn.execute(
        """SELECT d.*, r.phrase FROM detections d JOIN tracks t ON t.id = d.track_id
           JOIN tracking_runs r ON r.id = t.run_id WHERE d.frame_id = ? AND r.target = ? ORDER BY d.id""",
        (frame["id"], item.target)).fetchall()
    try:
        with Image.open(data_dir / frame["path"]) as source:
            image = source.convert("RGB")
    except OSError as error:
        raise EvidenceError(f"evidence frame {item.frame_id} left out: its image could not be read") from error
    scale = min(1.0, OVERLAY_WIDTH / image.width)
    size = (round(image.width * scale), round(image.height * scale))
    if scale < 1:
        image = image.resize(size, Image.Resampling.LANCZOS)
    layers = []
    for detection in detections:
        mask = detection_mask(detection, frame["width"], frame["height"])
        if scale < 1:
            mask = np.asarray(Image.fromarray(mask).resize(size, Image.Resampling.NEAREST), dtype=bool)
        layers.append(Layer(mask, COLORS[item.target], f"{item.target}: {detection['phrase']}"))
    path = folder / f"frame{frame['id']}_{item.target}.jpg"
    overlay = path.relative_to(data_dir).as_posix()  # before writing: a folder outside the data dir leaves no file
    folder.mkdir(parents=True, exist_ok=True)
    draw_layers(image, layers).save(path, quality=85)
    return Evidence(**item.model_dump(), camera_id=frame["camera_id"], captured_at=frame["captured_at"],
                    overlay=overlay)


def build_bulletin(ctx: ToolContext, volcano_id: str, run_id: int, draft: BulletinDraft, out_dir: Path, *,
                   wall_clock: Callable[[], datetime] = utcnow) -> Bulletin:
    """Check the draft against what was stored by the agent's clock and add what never depends on the model.
    Evidence overlays go to out_dir/run<run_id>, which must be inside the data dir."""
    volcano = ctx.sources.volcanoes[volcano_id]
    measurements = [verify(ctx.conn, m, ctx.now) for m in draft.measurements]
    evidence, notes = [], []
    for item in draft.evidence[:EVIDENCE_MAX]:
        try:
            drawn = draw_evidence(ctx.conn, ctx.data_dir, out_dir / f"run{run_id}", item, ctx.now)
        except EvidenceError as error:
            notes.append(str(error))
            continue
        if drawn is None:
            notes.append(f"evidence frame {item.frame_id} left out: no such frame captured by {to_iso(ctx.now)}")
        else:
            evidence.append(drawn)
    if len(draft.evidence) > EVIDENCE_MAX:
        notes.append(f"{len(draft.evidence) - EVIDENCE_MAX} evidence frame(s) beyond {EVIDENCE_MAX} left out")
    unverified = sum(not m.verified for m in measurements)
    if unverified:
        notes.append(f"{unverified} of {len(measurements)} quoted number(s) match no stored measurement")
    checked = [(m.unit, number) for m in measurements if m.verified for number in (m.value, m.sigma)]
    unsupported = [q for q in quoted_numbers(f"{draft.headline}\n{draft.body}") if not supports(q, checked)]
    notes += [f"the text quotes {written}, which no checked measurement supports"
              for written in dict.fromkeys(q.written for q in unsupported)]
    names = {"name": volcano.name, "agency": volcano.official_agency, "url": volcano.official_url}
    return Bulletin(
        run_id=run_id, volcano=volcano_id, volcano_name=volcano.name, utc_offset_hours=volcano.utc_offset_hours,
        clock=to_iso(ctx.now), created_at=to_iso(wall_clock()),
        **draft.model_dump(exclude={"measurements", "evidence"}), measurements=measurements, evidence=evidence,
        wind=run_wind(ctx.conn, run_id), official_agency=volcano.official_agency, official_url=volcano.official_url,
        disclaimer=DISCLAIMER.format(**names), notes=notes,
        text_checked=not unsupported)


def store_bulletin(conn: sqlite3.Connection, bulletin: Bulletin) -> Bulletin:
    """Insert the bulletin; returns it with its id."""
    with conn:
        bulletin_id = conn.execute(
            """INSERT INTO bulletins (run_id, volcano, clock, created_at, activity_level, headline, verified,
                                      body) VALUES (?, ?, ?, ?, ?, ?, ?, '')""",
            (bulletin.run_id, bulletin.volcano, bulletin.clock, bulletin.created_at, bulletin.activity_level,
             bulletin.headline, int(bulletin.verified))).lastrowid
        stored = bulletin.model_copy(update={"id": bulletin_id})
        conn.execute("UPDATE bulletins SET body = ? WHERE id = ?", (stored.model_dump_json(), bulletin_id))
    return stored


def load_bulletin(conn: sqlite3.Connection, bulletin_id: int) -> Bulletin:
    row = conn.execute("SELECT body FROM bulletins WHERE id = ?", (bulletin_id,)).fetchone()
    if row is None:
        raise KeyError(f"no bulletin {bulletin_id}")
    return Bulletin.model_validate_json(row["body"])


@dataclass(frozen=True)
class Written:
    run: AgentRun
    bulletin: Bulletin | None
    problem: str | None = None  # why there is no bulletin


def write_bulletin(client: MetaClient, ctx: ToolContext, volcano_id: str, out_dir: Path, *, task: str | None = None,
                   wall_clock: Callable[[], datetime] = utcnow, **agent: Any) -> Written:
    """Run the agent at the context's clock with a bulletin as its final answer, then check, store and publish it
    in out_dir (inside the data dir). The task recalls the last bulletin before the clock, so the agent can say
    what changed. Other keyword arguments go to run_agent."""
    volcano = ctx.sources.volcanoes[volcano_id]
    task = task or DEFAULT_TASK.format(name=volcano.name)
    previous = ctx.conn.execute(
        "SELECT clock, activity_level, headline FROM bulletins WHERE volcano = ? AND clock < ? "
        "ORDER BY clock DESC, id DESC LIMIT 1", (volcano_id, to_iso(ctx.now))).fetchone()
    if previous is not None:
        task += (f"\nYour previous bulletin, at {local_time(previous['clock'], volcano.utc_offset_hours)}, reported "
                 f"{previous['activity_level']}: {previous['headline']}")
    run = run_agent(client, ctx, volcano_id, task, finish=BULLETIN_FINISH, text_format=DRAFT_FORMAT,
                    wall_clock=wall_clock, **agent)
    if run.status not in ("done", "max_turns"):
        return Written(run, None, f"the agent run ended with {run.status}: {run.error}")
    try:
        draft = BulletinDraft.model_validate_json(run.final_text)
    except ValidationError as exc:
        return Written(run, None, f"the final answer is not a bulletin: {exc.errors()[0]['msg']}")
    bulletin = store_bulletin(ctx.conn, build_bulletin(ctx, volcano_id, run.run_id, draft, out_dir,
                                                       wall_clock=wall_clock))
    publish(bulletin, ctx.data_dir, out_dir)
    return Written(run, bulletin)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Have the agent write a bulletin about a volcano at a time (now, "
                                                 "or a past time to replay it), check it and publish it.")
    parser.add_argument("--volcano", required=True, help="volcano id from the sources file, e.g. kilauea")
    parser.add_argument("--at", type=parse_utc, help="the agent's clock, e.g. 2026-10-17T05:00-10:00 (default: now)")
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS, help=f"model turns (default {MAX_TURNS})")
    parser.add_argument("--budget", type=float, default=BUDGET_USD,
                        help=f"USD for the whole run, tool calls included (default {BUDGET_USD})")
    parser.add_argument("--effort", choices=["low", "medium", "high"], default="medium", help="reasoning effort")
    args = parser.parse_args(argv)
    if args.max_turns < 1:
        parser.error("--max-turns must be at least 1")

    settings = Settings.from_env()
    sources = load_sources(settings.sources_path)
    if args.volcano not in sources.volcanoes:
        parser.error(f"unknown volcano {args.volcano!r} in {settings.sources_path}")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # a Windows console may not show every character
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    out_dir = settings.data_dir / "bulletins"
    with closing(db.connect(settings.db_path)) as conn, \
            httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=30) as http:
        ctx = context_from_settings(settings, conn, http, args.at or utcnow(), sources=sources)
        client = MetaClient.from_env(CostLedger(conn, settings.daily_budget_usd))
        written = write_bulletin(client, ctx, args.volcano, out_dir, max_turns=args.max_turns,
                                 budget_usd=args.budget, effort=args.effort)
        print(trace(conn, written.run.run_id))
    if written.bulletin is None:
        print(f"no bulletin: {written.problem}")
        raise SystemExit(1)
    print()
    print(to_markdown(written.bulletin))
    print(f"published in {out_dir / f'run{written.run.run_id}'}")
