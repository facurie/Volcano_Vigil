"""The pipeline a live deployment runs every few minutes, and the replay runs on its simulated clock.

One step at time `now`, for one volcano's cameras:
1. the quality gate gives a verdict to every frame of the last hours that has none (local checks, and Muse
   Spark for the uncertain ones when there is a client; a camera with `track: false` gets local verdicts only);
2. every closed window (one per camera per hour, the Phase 2 cost rule) with enough usable frames that lacks
   a run of some target is tracked, for the missing targets only, with SAM 3.1 video, and a calibrated
   camera's new detections are measured (a camera with `track: false` is never tracked: it is ingested for
   the alerts);
3. at each full `agent_every` after the pipeline started, the agent writes a bulletin.
A window counts as closed once `settle` has passed after its end, so that late frames are in; the replay, whose
frames are all on time, settles for nothing. The agent waits for the same `settle`: live, the 14:00 bulletin runs
at 14:05, after the step has tracked the 13:00-14:00 window. A window that fails is reported and the step goes
on; one that still lacks a target after a try is tried again, at most `MAX_WINDOW_ATTEMPTS` times. An agent run
that ended in error is not the bulletin: it is run again, until `MAX_AGENT_ERRORS` runs have failed. Nothing in a
step looks past `now`.
Tracking and measuring take minutes (mask decoding), so a server runs the steps in a background thread, never in
a request.

    vigil-pipeline --volcano kilauea
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import openai

from vigil import db, tracking
from vigil.agent.bulletin import write_bulletin
from vigil.agent.loop import BUDGET_USD, context_from_settings
from vigil.agent.tools import ToolContext, calibrated
from vigil.config import Camera, load_sources
from vigil.gate import QualityGate, SparkMode
from vigil.meta.client import MetaClient
from vigil.meta.ledger import BudgetExceeded, CostLedger
from vigil.metrics import measure_window
from vigil.prompts import Target
from vigil.settings import Settings
from vigil.timeutil import to_iso, utcnow

log = logging.getLogger(__name__)

TRACK_WINDOW = timedelta(hours=1)
LOOKBACK = timedelta(hours=3)
SETTLE = timedelta(minutes=5)
MIN_WINDOW_FRAMES = 5
MAX_WINDOW_ATTEMPTS = 3
MAX_AGENT_ERRORS = 2
AGENT_EVERY = timedelta(hours=1)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class PipelineConfig:
    volcano: str
    cameras: tuple[str, ...]
    bulletin_dir: Path                   # inside the data dir
    window: timedelta = TRACK_WINDOW
    lookback: timedelta = LOOKBACK       # how far back frames are assessed and windows tracked
    settle: timedelta = SETTLE
    min_frames: int = MIN_WINDOW_FRAMES  # fewer usable frames in a window: not worth a SAM request
    spark: SparkMode = "uncertain"
    agent_every: timedelta | None = AGENT_EVERY
    agent_budget_usd: float = BUDGET_USD


@dataclass
class StepReport:
    clock: datetime
    assessed: int = 0
    usable: int = 0
    tracked: list[dict[str, Any]] = field(default_factory=list)  # per window: camera, start, end, frames, runs
    measured: int = 0
    agent_run_id: int | None = None
    bulletin_id: int | None = None
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"clock": to_iso(self.clock), "assessed": self.assessed, "usable": self.usable,
                "tracked": self.tracked, "measured": self.measured, "agent_run_id": self.agent_run_id,
                "bulletin_id": self.bulletin_id, "errors": self.errors}

    def summary(self) -> str:
        parts = [f"{to_iso(self.clock)}: {self.assessed} frames assessed ({self.usable} usable)"]
        parts += [f"tracked {w['camera_id']} {w['start'][11:16]}-{w['end'][11:16]} "
                  f"({sum(run['detections'] for run in w['runs'])} detections)" for w in self.tracked]
        if self.measured:
            parts.append(f"{self.measured} detections measured")
        if self.bulletin_id is not None:
            parts.append(f"bulletin {self.bulletin_id} (agent run {self.agent_run_id})")
        elif self.agent_run_id is not None:
            parts.append(f"agent run {self.agent_run_id}, no bulletin")
        return "; ".join(parts) + "".join(f"\n  failed: {error}" for error in self.errors)


def floor_time(when: datetime, every: timedelta) -> datetime:
    """The latest whole multiple of `every` since the Unix epoch at or before `when`."""
    return _EPOCH + (when - _EPOCH) // every * every


class Pipeline:
    """Quality, tracking, measuring and bulletins for one volcano; `base.now` is when the pipeline started."""

    def __init__(self, base: ToolContext, config: PipelineConfig, *, track: Callable = tracking.track_window,
                 measure: Callable = measure_window, write: Callable = write_bulletin):
        self.base, self.config = base, config
        self.started_at = base.now
        self._cameras = [base.camera(camera_id) for camera_id in config.cameras]
        self._track, self._measure, self._write = track, measure, write
        self._attempts: dict[tuple[str, datetime], int] = {}  # windows tracked and still missing a target
        self._gave_up: set[datetime] = set()                  # agent boundaries reported as given up

    def step(self, now: datetime, *, flush: bool = False, agent: bool | None = None) -> StepReport:
        """One step at `now`. `flush` also tracks the open window up to now (the end of a replay). `agent`: None
        runs the agent when a full `agent_every` has come; True runs it unless a run at this very clock exists;
        False holds it back."""
        ctx = dataclasses.replace(self.base, now=now)
        report = StepReport(now)
        self._assess(ctx, report)
        if ctx.client is None:
            return report
        self._track_windows(ctx, report, flush)
        due = self._agent_due(now, report) if agent is None else agent and not self._ran_at(now, report)
        if due:
            self._run_agent(ctx, report)
        return report

    def _assess(self, ctx: ToolContext, report: StepReport) -> None:
        gate = QualityGate(ctx.conn, ctx.data_dir, ctx.sources, ctx.client)
        spark = self.config.spark if ctx.client is not None else "never"
        try:
            for camera in self._cameras:
                result = gate.assess_range(camera.id, ctx.now - self.config.lookback, ctx.now,
                                           spark=spark if camera.track else "never")
                report.assessed += len(result.verdicts)
                report.usable += sum(verdict.usable for verdict in result.verdicts)
                report.errors += result.errors
        except BudgetExceeded as exc:
            report.errors.append(f"quality gate stopped: {exc}")

    def _windows(self, now: datetime, flush: bool) -> list[tuple[datetime, datetime]]:
        """[start, end] of the closed windows in the lookback, and of the open one up to now when flushing."""
        every = self.config.window
        start = floor_time(max(now - self.config.lookback, self.started_at), every)
        windows = []
        while start + every + self.config.settle <= now:
            windows.append((start, start + every - timedelta(seconds=1)))
            start += every
        if flush and start < now:
            windows.append((start, min(now, start + every - timedelta(seconds=1))))
        return windows

    def _missing(self, ctx: ToolContext, camera: Camera, start: datetime) -> list[Target]:
        """The targets the prompts have phrases for on this camera that the window has no run of."""
        done = {row[0] for row in ctx.conn.execute(
            "SELECT DISTINCT target FROM tracking_runs WHERE camera_id = ? AND window_start >= ? AND window_end < ?",
            (camera.id, to_iso(start), to_iso(start + self.config.window)))}
        return [target for target in tracking.TARGETS
                if ctx.prompts.phrases(target, camera.kind) and target not in done]

    def _track_windows(self, ctx: ToolContext, report: StepReport, flush: bool) -> None:
        for camera in self._cameras:
            if not camera.track:
                continue
            for start, end in self._windows(ctx.now, flush):
                missing = self._missing(ctx, camera, start)
                if not missing or self._attempts.get((camera.id, start), 0) >= MAX_WINDOW_ATTEMPTS:
                    continue
                usable = len(tracking.usable_frames(ctx.conn, ctx.data_dir, camera.id, start, end))
                if usable < self.config.min_frames:
                    continue
                try:
                    result = self._track(ctx.client, ctx.conn, ctx.data_dir, camera, ctx.prompts, start, end,
                                         targets=missing, lead_in=max(0, tracking.MIN_BILLED_FRAMES - usable))
                except BudgetExceeded as exc:
                    report.errors.append(f"tracking stopped: {exc}")
                    return
                except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError, openai.APIError) as exc:
                    # e.g. the upload or ffmpeg failed, a frame file is gone: the next step tries again
                    report.errors.append(f"{camera.id} {to_iso(start)}: {exc}")
                    self._count_attempt(camera.id, start, report)
                    continue
                report.errors += result.errors
                report.tracked.append({
                    "camera_id": camera.id, "start": to_iso(start), "end": to_iso(end), "frames": result.frames,
                    "runs": [{"run_id": run.run_id, "target": run.target, "phrase": run.phrase, "tracks": run.tracks,
                              "detections": run.detections} for run in result.runs]})
                if result.runs and calibrated(ctx.calibration, camera.id, start):
                    try:
                        measured = self._measure(ctx.conn, ctx.calibration, camera.id, start, end)
                    except ValueError as exc:
                        report.errors.append(f"{camera.id} {to_iso(start)}: {exc}")
                    else:
                        report.measured += measured.measured
                        report.errors += measured.errors
                if self._missing(ctx, camera, start):
                    self._count_attempt(camera.id, start, report)

    def _count_attempt(self, camera_id: str, start: datetime, report: StepReport) -> None:
        key = (camera_id, start)
        self._attempts[key] = self._attempts.get(key, 0) + 1
        if self._attempts[key] == MAX_WINDOW_ATTEMPTS:
            report.errors.append(f"{camera_id} {to_iso(start)}: gave up after {MAX_WINDOW_ATTEMPTS} attempts")

    def _agent_due(self, now: datetime, report: StepReport) -> bool:
        every = self.config.agent_every
        if every is None:
            return False
        boundary = floor_time(now - self.config.settle, every)
        if boundary <= self.started_at:
            return False
        return not self._agent_settled(boundary, boundary + every, report)

    def _ran_at(self, now: datetime, report: StepReport) -> bool:
        return self._agent_settled(now, now + timedelta(seconds=1), report)

    def _agent_settled(self, low: datetime, high: datetime, report: StepReport) -> bool:
        """True if the agent needs no more runs with a clock in [low, high): one did not end in error, or
        `MAX_AGENT_ERRORS` did (said once in a report). A run in error is run again, so a Ctrl-C or an API
        failure does not lose the bulletin."""
        finished, failed = self.base.conn.execute(
            """SELECT COALESCE(SUM(status != 'error'), 0), COALESCE(SUM(status = 'error'), 0) FROM agent_runs
               WHERE volcano = ? AND clock >= ? AND clock < ?""",
            (self.config.volcano, to_iso(low), to_iso(high))).fetchone()
        if finished:
            return True
        if failed < MAX_AGENT_ERRORS:
            return False
        if low not in self._gave_up:
            self._gave_up.add(low)
            report.errors.append(f"agent at {to_iso(low)}: gave up after {failed} failed runs")
        return True

    def _run_agent(self, ctx: ToolContext, report: StepReport) -> None:
        written = self._write(ctx.client, ctx, self.config.volcano, self.config.bulletin_dir,
                              budget_usd=self.config.agent_budget_usd)
        report.agent_run_id = written.run.run_id
        if written.bulletin is not None:
            report.bulletin_id = written.bulletin.id
        else:
            report.errors.append(f"agent run {written.run.run_id}: {written.problem}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the pipeline live for one volcano: quality verdicts, hourly "
                                                 "SAM tracking and measuring, and an hourly bulletin. Run "
                                                 "vigil-ingest alongside it.")
    parser.add_argument("--volcano", required=True, help="volcano id from the sources file, e.g. kilauea")
    parser.add_argument("--interval", type=float, default=5, help="minutes between steps (default 5)")
    parser.add_argument("--agent-every", type=float, default=60,
                        help="minutes between bulletins, 0 for none (default 60)")
    parser.add_argument("--once", action="store_true", help="run one step and exit")
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be positive")
    if args.agent_every < 0:
        parser.error("--agent-every must not be negative")
    settings = Settings.from_env()
    sources = load_sources(settings.sources_path)
    if args.volcano not in sources.volcanoes:
        parser.error(f"unknown volcano {args.volcano!r} in {settings.sources_path}")
    cameras = tuple(camera.id for camera in sources.enabled_cameras() if camera.volcano == args.volcano)
    if not cameras:
        parser.error(f"{args.volcano} has no enabled camera in {settings.sources_path}")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with closing(db.connect(settings.db_path)) as conn, \
            httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=30) as http:
        # the alerts keep their reserve of the cap (vigil-alerts)
        client = MetaClient.from_env(CostLedger(conn, settings.pipeline_budget_usd))
        config = PipelineConfig(volcano=args.volcano, cameras=cameras, bulletin_dir=settings.data_dir / "bulletins",
                                agent_every=timedelta(minutes=args.agent_every) if args.agent_every > 0 else None)
        pipeline = Pipeline(context_from_settings(settings, conn, http, utcnow(), client, sources), config)
        while True:
            try:
                print(pipeline.step(utcnow()).summary(), flush=True)
            except Exception:
                if args.once:
                    raise
                log.exception("the step failed; the next one tries again")
            if args.once:
                return
            time.sleep(args.interval * 60)
