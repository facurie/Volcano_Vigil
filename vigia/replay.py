"""Replay a past episode through the live pipeline on a simulated clock, and set what it says against the record.

The replay has its own database, data/replay/ep<key>/vigia.sqlite. Every `step` of simulated time it copies
into it the episode's frames captured by then, as live ingest would have, and runs one pipeline step at that
time (vigia.pipeline): quality verdicts, one SAM window per camera per closed hour with its measurements, and
the agent's bulletin at every full hour and once more at the end. Nothing captured after the simulated clock
exists for any of them. Each step's report goes to replay_ticks, so an interrupted replay resumes where it
stopped. With --speed S the simulated clock runs at most S times faster than the wall clock (it cannot run
faster than tracking does).

At the end it writes timeline.json (the steps, the bulletins and the comparisons with the official values) and
report.md next to the database. Its Meta spend goes to that database's ledger.

    vigia-replay --episode 55 --speed 60
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sqlite3
import sys
import time
from collections import Counter
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from vigia import db
from vigia.agent.bulletin import Bulletin
from vigia.agent.loop import context_from_settings
from vigia.agent.tools import ToolContext
from vigia.episodes import (DRIFT_HEADER, END_HEADER, EPISODES, HEIGHT_HEADER, Episode, drift_rows, end_rows,
                            height_row, local_time, table)
from vigia.meta.client import MetaClient
from vigia.meta.ledger import CostLedger
from vigia.pipeline import AGENT_EVERY, Pipeline, PipelineConfig
from vigia.settings import Settings
from vigia.timeutil import parse_utc, to_iso

log = logging.getLogger(__name__)

STEP = timedelta(minutes=5)
FRAME_COLUMNS = ("id", "camera_id", "captured_at", "timestamp_source", "fetched_at", "sha256", "path", "bytes",
                 "width", "height")
BULLETIN_HEADER = ["Quantity", "Official", "Bulletin (local)", "It quoted", "Error", "Checked"]
ACTIVITY_HEADER = ["Event", "Bulletins (local)", "Official (local)", "Difference"]


def ticks(start: datetime, end: datetime, step: timedelta) -> list[datetime]:
    """The simulated clock's steps: every `step` after start, and the end itself."""
    out, tick = [], start + step
    while tick < end:
        out.append(tick)
        tick += step
    return out + [end]


def feed(source: sqlite3.Connection, conn: sqlite3.Connection, cameras: tuple[str, ...], start: datetime,
         clock: datetime) -> dict[str, int]:
    """Copy the cameras' frames captured from start to clock that the replay lacks, keeping their ids; returns the
    new frames per camera."""
    marks = ",".join("?" * len(cameras))
    rows = source.execute(
        f"""SELECT {', '.join(FRAME_COLUMNS)} FROM frames WHERE camera_id IN ({marks})
            AND captured_at BETWEEN ? AND ? ORDER BY captured_at, id""",
        (*cameras, to_iso(start), to_iso(clock))).fetchall()
    new: Counter[str] = Counter()
    with conn:
        for row in rows:
            inserted = conn.execute(
                f"INSERT OR IGNORE INTO frames ({', '.join(FRAME_COLUMNS)}) "
                f"VALUES ({', '.join('?' * len(FRAME_COLUMNS))})", tuple(row)).rowcount
            new[row["camera_id"]] += inserted
    return {camera: count for camera, count in new.items() if count}


def run_replay(source: sqlite3.Connection, base: ToolContext, episode: Episode, out_dir: Path, *,
               step: timedelta = STEP, agent_every: timedelta | None = AGENT_EVERY, speed: float = 0.0,
               pipeline: Pipeline | None = None, sleep: Callable[[float], None] = time.sleep,
               monotonic: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Replay the episode into base.conn, the replay's own database, and write timeline.json and report.md to
    out_dir (inside the data dir); returns the timeline."""
    conn = base.conn
    if pipeline is None:
        config = PipelineConfig(volcano=episode.volcano, cameras=episode.cameras, bulletin_dir=out_dir / "bulletins",
                                settle=timedelta(0), agent_every=agent_every)
        pipeline = Pipeline(dataclasses.replace(base, now=episode.start), config)
    done = {row[0] for row in conn.execute("SELECT clock FROM replay_ticks")}
    origin: tuple[datetime, float] | None = None
    for tick in ticks(episode.start, episode.end, step):
        if to_iso(tick) in done:
            continue
        if speed > 0:
            if origin is None:
                origin = (tick, monotonic())
            wait = (tick - origin[0]).total_seconds() / speed - (monotonic() - origin[1])
            if wait > 0:
                sleep(wait)
        new = feed(source, conn, episode.cameras, episode.start, tick)
        last = tick == episode.end
        report = pipeline.step(tick, flush=last, agent=True if last and agent_every else None)
        with conn:
            conn.execute("INSERT INTO replay_ticks (clock, report) VALUES (?, ?)",
                         (to_iso(tick), json.dumps({**report.as_json(), "new_frames": new})))
        log.info("%s", report.summary())
    timeline = build_timeline(conn, episode, step, agent_every)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "report.md").write_text(report_markdown(timeline, episode), encoding="utf-8")
    return timeline


def bulletin_rows(conn: sqlite3.Connection, episode: Episode) -> list[list[str]]:
    """Each official height against the first bulletin written once its window opened: the value of that target
    and metric it quoted nearest the window's middle."""
    rows = []
    for check in episode.checks:
        official = f"{check.official} ({check.official_m:,.0f} m)"
        row = conn.execute("SELECT body FROM bulletins WHERE volcano = ? AND clock >= ? ORDER BY clock, id LIMIT 1",
                           (episode.volcano, check.start)).fetchone()
        if row is None:
            rows.append([check.quantity, official, "none", "", "", ""])
            continue
        bulletin = Bulletin.model_validate_json(row["body"])
        written = f"#{bulletin.id} at {local_time(bulletin.clock, episode.local)}"
        quoted = [m for m in bulletin.measurements if (m.target, m.metric) == (check.target, check.metric)]
        if not quoted:
            rows.append([check.quantity, official, written, "not quoted", "", ""])
            continue
        middle = parse_utc(check.start) + (parse_utc(check.end) - parse_utc(check.start)) / 2
        m = min(quoted, key=lambda q: abs(parse_utc(q.captured_at) - middle) if q.captured_at else timedelta.max)
        error = m.value - check.official_m
        if check.upper_bound:
            error_text = "within the bound" if m.value <= check.official_m else f"{error:+,.0f} m above it"
        else:
            error_text = f"{error:+,.0f} m ({100 * error / check.official_m:+.0f} %)"
        at = f" at {local_time(m.captured_at, episode.local)}" if m.captured_at else ""
        rows.append([check.quantity, official, written, f"{m.value:,.0f} ± {m.sigma:,.0f} m{at}", error_text,
                     "yes" if m.verified else "no"])
    return rows


def activity_rows(conn: sqlite3.Connection, episode: Episode) -> list[list[str]]:
    """When the bulletins first reported fountaining, and first stopped reporting it, against the official onset
    and end."""
    levels = conn.execute("SELECT clock, activity_level FROM bulletins WHERE volcano = ? ORDER BY clock, id",
                          (episode.volcano,)).fetchall()
    first = next((row["clock"] for row in levels if row["activity_level"] == "fountaining"), None)
    stopped = None if first is None else next(
        (row["clock"] for row in levels if row["clock"] > first and row["activity_level"] != "fountaining"), None)
    rows = []
    for event, clock, official in (("fountaining first reported", first, episode.phases["onset"][0]),
                                   ("fountaining no longer reported", stopped, episode.phases["end"][0])):
        when = local_time(to_iso(official), episode.local)
        if clock is None:
            rows.append([event, "never", when, ""])
        else:
            minutes = (parse_utc(clock) - official) / timedelta(minutes=1)
            rows.append([event, local_time(clock, episode.local), when, f"{minutes:+.0f} min"])
    return rows


def build_timeline(conn: sqlite3.Connection, episode: Episode, step: timedelta, agent_every: timedelta | None,
                   phases: dict[str, Any] | None = None) -> dict[str, Any]:
    """Everything the replay produced, as one JSON-ready dict (the dashboard's replay player reads it)."""
    return {
        "episode": episode.key, "volcano": episode.volcano, "cameras": list(episode.cameras),
        "start": to_iso(episode.start), "end": to_iso(episode.end), "step_minutes": step / timedelta(minutes=1),
        "agent_every_minutes": None if agent_every is None else agent_every / timedelta(minutes=1),
        "official_phases": {phase: [to_iso(low), to_iso(high)] for phase, (low, high) in episode.phases.items()},
        "ticks": [json.loads(row[0]) for row in conn.execute("SELECT report FROM replay_ticks ORDER BY clock")],
        "bulletins": [json.loads(row[0]) for row in conn.execute(
            "SELECT body FROM bulletins WHERE volcano = ? ORDER BY clock, id", (episode.volcano,))],
        "phases": phases,
        "comparison": {
            "heights": [height_row(conn, check, episode.local) for check in episode.checks],
            "ends": end_rows(conn, episode), "drift": drift_rows(conn, episode),
            "bulletins": bulletin_rows(conn, episode), "activity": activity_rows(conn, episode)},
        "cost_usd": round(conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM api_calls").fetchone()[0], 4),
    }


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def report_markdown(timeline: dict[str, Any], episode: Episode) -> str:
    comparison, every = timeline["comparison"], timeline["agent_every_minutes"]
    bulletins = [[local_time(b["clock"], episode.local), b["activity_level"], _cell(b["headline_en"]),
                  _cell(b["headline_es"]), "yes" if all(m["verified"] for m in b["measurements"]) else "no"]
                 for b in timeline["bulletins"]]
    agent = f"a bulletin every {every:g} min and at the end" if every else "no agent"
    return "\n".join([
        f"# Replay of episode {episode.key}: {episode.volcano}", "",
        f"From {local_time(timeline['start'], episode.local)} to {local_time(timeline['end'], episode.local)} local "
        f"time: {len(timeline['ticks'])} steps of {timeline['step_minutes']:g} min, {agent}. "
        f"Meta API cost: ${timeline['cost_usd']:.2f}.", "",
        "## Bulletins", "",
        table(["Time (local)", "Activity", "Headline", "Titular", "Numbers checked"], bulletins), "",
        "## What the bulletins quoted against the official values", "",
        table(BULLETIN_HEADER, comparison["bulletins"]), "",
        "## Activity against the official times", "", table(ACTIVITY_HEADER, comparison["activity"]), "",
        "## The replay's measurements against the official values", "",
        table(HEIGHT_HEADER, comparison["heights"]), "",
        "## End of fountaining", "", table(END_HEADER, comparison["ends"]), "",
        "## Drift", "", table(DRIFT_HEADER, comparison["drift"]), "",
    ])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Replay a past episode through the pipeline on a simulated clock "
                                                 "(quality, hourly SAM tracking and measuring, the agent's "
                                                 "bulletins) and compare it with the official values.")
    parser.add_argument("--episode", required=True, choices=sorted(EPISODES), help="which episode")
    parser.add_argument("--speed", type=float, default=0,
                        help="at most this many simulated seconds per wall second, e.g. 60 (default 0: no limit)")
    parser.add_argument("--step", type=float, default=STEP / timedelta(minutes=1),
                        help="simulated minutes per step (default 5)")
    parser.add_argument("--agent-every", type=float, default=AGENT_EVERY / timedelta(minutes=1),
                        help="simulated minutes between bulletins (default 60)")
    parser.add_argument("--no-agent", action="store_true", help="no agent runs and no bulletins")
    args = parser.parse_args(argv)
    if args.step <= 0 or args.agent_every <= 0 or args.speed < 0:
        parser.error("--step and --agent-every must be positive and --speed not negative")
    episode = EPISODES[args.episode]
    settings = Settings.from_env()
    out_dir = settings.data_dir / "replay" / f"ep{episode.key}"
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with closing(db.connect(settings.db_path)) as source, closing(db.connect(out_dir / "vigia.sqlite")) as conn, \
            httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=30) as http:
        marks = ",".join("?" * len(episode.cameras))
        stored = source.execute(f"SELECT COUNT(*) FROM frames WHERE camera_id IN ({marks}) AND captured_at "
                                "BETWEEN ? AND ?", (*episode.cameras, to_iso(episode.start), to_iso(episode.end)))
        if not stored.fetchone()[0]:
            parser.error(f"{settings.db_path} has no frames of episode {episode.key}; backfill them with vigia-backfill")
        client = MetaClient.from_env(CostLedger(conn, settings.daily_budget_usd))
        run_replay(source, context_from_settings(settings, conn, http, episode.start, client), episode, out_dir,
                   step=timedelta(minutes=args.step), speed=args.speed,
                   agent_every=None if args.no_agent else timedelta(minutes=args.agent_every))
    print((out_dir / "report.md").read_text(encoding="utf-8"))
    print(f"timeline: {out_dir / 'timeline.json'}")
