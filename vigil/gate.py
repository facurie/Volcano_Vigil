"""The quality gate: local checks on every frame, Muse Spark when they cannot decide.

Local checks (vigil/quality.py) cost nothing: they reject stale, frozen,
dark-night and foggy frames, pass clear ones and leave hazy ones uncertain.
Muse Spark looks at the uncertain frames, or on request at every frame the
local checks let through: is the view usable, and which timestamp and
pan/tilt/zoom readout are printed on it. A printed time more than 10 minutes
from the stored capture time makes a frame unusable, since its measurements
would land at the wrong time. An uncertain frame that Muse Spark did not see
is not used. Each frame's verdict is one row of `frame_quality`.

    vigil-quality --camera kilauea-k2 --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import re
import sqlite3
from collections import Counter
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
import openai
from PIL import Image

from vigil import db
from vigil.config import Sources, load_sources
from vigil.imaging import load_for_upload
from vigil.meta.client import MetaClient
from vigil.meta.ledger import CostLedger
from vigil.settings import Settings
from vigil.quality import ImageStats, LocalVerdict, Thresholds, check_local, difference, fingerprint, measure
from vigil.sun import solar_elevation
from vigil.timeutil import parse_utc, to_iso, utcnow

log = logging.getLogger(__name__)

SparkMode = Literal["never", "uncertain", "all"]
TIMESTAMP_TOLERANCE = timedelta(minutes=10)

GATE_INSTRUCTIONS = (
    "You are the quality gate of a volcano webcam monitoring system. You look at one webcam frame "
    "and report only what is actually visible. Never infer activity that you cannot see."
)
GATE_PROMPT = (
    "Assess this volcano webcam frame.\n"
    "1. Is it usable for measuring a volcanic plume or lava fountain, or is the view blocked "
    "(cloud, fog, darkness, rain on the lens, glare, frozen or corrupted image)? Explain briefly.\n"
    "2. Transcribe any timestamp printed on the image exactly as written, and convert it to "
    "ISO 8601 keeping the printed time zone (leave the offset out if no zone is printed). "
    "Use empty strings if there is no readable timestamp. Also transcribe any camera label.\n"
    "3. Transcribe any pan/tilt/zoom readout printed on the image exactly as written, for example "
    "'P: 29, T: +0.00, Z: 29 1.0'. Use an empty string if there is none.\n"
    "4. List the visible features, classify the activity, and describe the scene in English."
)
GATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "usable": {"type": "boolean"},
        "view": {"type": "string", "enum": [
            "clear", "partly_obscured", "obscured_by_cloud_or_fog", "night_dark", "night_with_glow",
            "rain_or_lens_water", "glare", "frozen_or_corrupted"]},
        "usable_reason": {"type": "string"},
        "printed_timestamp_text": {"type": "string"},
        "printed_timestamp_iso": {"type": "string"},
        "printed_camera_label": {"type": "string"},
        "printed_ptz_text": {"type": "string"},
        "visible_features": {"type": "array", "items": {"type": "string", "enum": [
            "crater", "crater_floor", "vent", "lava_lake", "lava_fountain", "incandescent_glow",
            "volcanic_plume", "steam", "gas_haze", "ash_cloud", "meteorological_cloud", "fog",
            "blue_sky", "night_sky", "people", "structures"]}},
        "activity": {"type": "string", "enum": [
            "no_visible_activity", "degassing", "steaming", "ash_emission", "lava_fountaining",
            "lava_lake_activity", "unclear"]},
        "description_en": {"type": "string"},
    },
    "additionalProperties": False,
}
GATE_SCHEMA["required"] = list(GATE_SCHEMA["properties"])

# e.g. "P: +178.54, T: -0.06, Z: 959 3.9": pan, tilt, then the raw zoom position and the zoom factor
_PTZ = re.compile(r"P:\s*(?P<pan>[+-]?\d+(?:\.\d+)?)\s*,\s*T:\s*(?P<tilt>[+-]?\d+(?:\.\d+)?)\s*,\s*"
                  r"Z:\s*(?P<zoom_raw>\d+(?:\.\d+)?)(?:\s+(?P<zoom>\d+(?:\.\d+)?))?")


@dataclass(frozen=True)
class SparkAssessment:
    usable: bool
    view: str
    reason: str
    printed_time_text: str
    printed_time: datetime | None  # UTC; None if unreadable or printed without a zone
    printed_ptz: dict[str, float] | None
    answer: dict[str, Any]


@dataclass(frozen=True)
class FrameVerdict:
    frame_id: int
    usable: bool
    decided_by: Literal["local", "spark"]
    local: LocalVerdict
    reasons: tuple[str, ...]  # the local reasons, plus timestamp_mismatch from the printed time
    stats: ImageStats
    sun_elevation: float | None
    change: float | None
    spark: SparkAssessment | None = None


@dataclass
class GateReport:
    verdicts: list[FrameVerdict] = field(default_factory=list)
    skipped: int = 0  # frames that already had a verdict
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        usable = sum(v.usable for v in self.verdicts)
        rejected = Counter(reason for v in self.verdicts if not v.usable for reason in v.reasons)
        details = ", ".join(f"{reason} {count}" for reason, count in sorted(rejected.items()))
        spark = sum(v.decided_by == "spark" for v in self.verdicts)
        return (f"{len(self.verdicts)} assessed, {usable} usable, {len(self.verdicts) - usable} rejected"
                + (f" ({details})" if details else "")
                + f", {spark} by Muse Spark, {self.skipped} already assessed, {len(self.errors)} failed")


def parse_ptz(text: str) -> dict[str, float] | None:
    """Read a printed pan/tilt/zoom readout; None if the text holds none."""
    match = _PTZ.search(text or "")
    if match is None:
        return None
    return {key: float(value) for key, value in match.groupdict().items() if value is not None}


def read_answer(answer: dict[str, Any]) -> SparkAssessment:
    return SparkAssessment(
        usable=bool(answer["usable"]),
        view=answer["view"],
        reason=answer["usable_reason"],
        printed_time_text=answer["printed_timestamp_text"],
        printed_time=_printed_time(answer["printed_timestamp_iso"]),
        printed_ptz=parse_ptz(answer["printed_ptz_text"]),
        answer=answer,
    )


class QualityGate:
    def __init__(
        self,
        conn: sqlite3.Connection,
        data_dir: str | Path,
        sources: Sources,
        client: MetaClient | None = None,
        thresholds: Thresholds = Thresholds(),
        clock: Callable[[], datetime] = utcnow,
    ):
        self._conn = conn
        self._data_dir = Path(data_dir)
        self._sources = sources
        self._cameras = {camera.id: camera for camera in sources.cameras}
        self._client = client
        self._thresholds = thresholds
        self._clock = clock
        self._last: dict[str, tuple[int, np.ndarray]] = {}  # camera id -> (frame id, fingerprint)

    def assess(self, frame_id: int, *, spark: SparkMode = "uncertain", now: datetime | None = None) -> FrameVerdict:
        """Assess one stored frame and store its verdict, replacing any earlier one.

        `spark` says which frames Muse Spark sees: none, those the local
        checks find uncertain, or all that they do not reject. `now` (live
        use) also rejects frames captured more than 30 minutes before it.
        """
        frame = self._conn.execute("SELECT * FROM frames WHERE id = ?", (frame_id,)).fetchone()
        if frame is None:
            raise ValueError(f"no frame with id {frame_id}")
        camera = self._cameras.get(frame["camera_id"])
        if camera is None:
            raise ValueError(f"frame {frame_id}: camera {frame['camera_id']} is not in the sources file")
        volcano = self._sources.volcanoes[camera.volcano]
        captured_at = parse_utc(frame["captured_at"])
        image = _open_rgb(self._data_dir / frame["path"])
        stats, current = measure(image), fingerprint(image)
        previous = self._previous_fingerprint(frame)
        change = difference(previous, current) if previous is not None else None
        self._last[frame["camera_id"]] = (frame_id, current)
        sun = (solar_elevation(captured_at, volcano.lat, volcano.lon)
               if volcano.lat is not None and volcano.lon is not None else None)
        local = check_local(stats, kind=camera.kind, captured_at=captured_at, sun_elevation=sun, change=change,
                            now=now, thresholds=self._thresholds)
        verdict = FrameVerdict(frame_id, usable=local.decision == "pass", decided_by="local", local=local,
                               reasons=local.reasons, stats=stats, sun_elevation=sun, change=change)
        if ((spark == "all" and local.decision != "reject")
                or (spark == "uncertain" and local.decision == "uncertain")):
            verdict = self._ask_spark(verdict, frame["path"], captured_at)
        self._store(verdict)
        return verdict

    def assess_range(self, camera_id: str, start: datetime, end: datetime, *,
                     spark: SparkMode = "uncertain", redo: bool = False) -> GateReport:
        """Assess the camera's frames captured between start and end (inclusive), oldest first.

        Frames that already have a verdict are skipped unless `redo`. A failed
        Muse Spark call leaves its frame without a verdict, and the rest go on.
        """
        report = GateReport()
        frames = self._conn.execute(
            """SELECT f.id, q.frame_id IS NOT NULL AS assessed
               FROM frames f LEFT JOIN frame_quality q ON q.frame_id = f.id
               WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ?
               ORDER BY f.captured_at""",
            (camera_id, to_iso(start), to_iso(end)),
        ).fetchall()
        for frame in frames:
            if frame["assessed"] and not redo:
                report.skipped += 1
                continue
            try:
                report.verdicts.append(self.assess(frame["id"], spark=spark))
            except (openai.APIError, json.JSONDecodeError) as exc:
                log.warning("frame %s: Muse Spark failed: %s", frame["id"], exc)
                report.errors.append(f"frame {frame['id']}: {type(exc).__name__}: {exc}"[:300])
        return report

    def _previous_fingerprint(self, frame: sqlite3.Row) -> np.ndarray | None:
        previous = self._conn.execute(
            "SELECT id, path FROM frames WHERE camera_id = ? AND captured_at < ? ORDER BY captured_at DESC LIMIT 1",
            (frame["camera_id"], frame["captured_at"]),
        ).fetchone()
        if previous is None:
            return None
        cached = self._last.get(frame["camera_id"])
        if cached is not None and cached[0] == previous["id"]:
            return cached[1]
        return fingerprint(_open_rgb(self._data_dir / previous["path"]))

    def _ask_spark(self, verdict: FrameVerdict, path: str, captured_at: datetime) -> FrameVerdict:
        if self._client is None:
            raise RuntimeError(f"frame {verdict.frame_id} needs Muse Spark but the gate has no Meta client; "
                               "pass spark='never' to assess it locally")
        _, jpeg = load_for_upload(self._data_dir / path)
        answer = self._client.ask_json(prompt=GATE_PROMPT, images=[jpeg], schema_name="frame_assessment",
                                       schema=GATE_SCHEMA, instructions=GATE_INSTRUCTIONS, purpose="gate:assess")
        assessment = read_answer(answer)
        reasons = verdict.reasons
        if assessment.printed_time is not None and abs(assessment.printed_time - captured_at) > TIMESTAMP_TOLERANCE:
            reasons += ("timestamp_mismatch",)
        return dataclasses.replace(verdict, usable=assessment.usable and "timestamp_mismatch" not in reasons,
                                   decided_by="spark", reasons=reasons, spark=assessment)

    def _store(self, verdict: FrameVerdict) -> None:
        spark = verdict.spark
        spark_columns = (None,) * 6 if spark is None else (
            spark.view,
            spark.reason,
            spark.printed_time_text,
            to_iso(spark.printed_time) if spark.printed_time else None,
            json.dumps(spark.printed_ptz) if spark.printed_ptz else None,
            json.dumps(spark.answer, ensure_ascii=False),
        )
        self._conn.execute(
            """INSERT OR REPLACE INTO frame_quality (
                   frame_id, assessed_at, usable, decided_by, local_decision, reasons, sun_elevation_deg,
                   brightness, contrast, edge_density, glow_fraction, change,
                   spark_view, spark_reason, printed_time_text, printed_time, printed_ptz, spark_answer)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (verdict.frame_id, to_iso(self._clock()), int(verdict.usable), verdict.decided_by,
             verdict.local.decision, json.dumps(list(verdict.reasons)), verdict.sun_elevation,
             verdict.stats.brightness, verdict.stats.contrast, verdict.stats.edge_density,
             verdict.stats.glow_fraction, verdict.change, *spark_columns),
        )
        self._conn.commit()


def _printed_time(iso: str) -> datetime | None:
    """The printed timestamp in UTC; None if missing, malformed or printed without a zone."""
    if not iso:
        return None
    try:
        return parse_utc(iso)
    except ValueError:
        return None


def _open_rgb(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Assess stored frames: local checks first, then Muse Spark "
                                                 "for the frames they cannot decide.")
    parser.add_argument("--camera", action="append", required=True, help="camera id; repeat it for several")
    parser.add_argument("--start", type=parse_utc, required=True, help="first capture time, e.g. 2026-10-17T13:00Z")
    parser.add_argument("--end", type=parse_utc, required=True, help="last capture time, e.g. 2026-10-17T19:30Z")
    parser.add_argument("--spark", choices=["never", "uncertain", "all"], default="uncertain",
                        help="frames Muse Spark sees: none, those the local checks cannot decide (default), "
                             "or all that they do not reject")
    parser.add_argument("--redo", action="store_true", help="assess again frames that already have a verdict")
    args = parser.parse_args(argv)
    if args.start >= args.end:
        parser.error("--start must be before --end")

    settings = Settings.from_env()
    sources = load_sources(settings.sources_path)
    known = {camera.id for camera in sources.cameras}
    for camera_id in args.camera:
        if camera_id not in known:
            parser.error(f"unknown camera {camera_id!r} in {settings.sources_path}")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with closing(db.connect(settings.db_path)) as conn:
        client = None if args.spark == "never" else MetaClient.from_env(CostLedger(conn, settings.daily_budget_usd))
        gate = QualityGate(conn, settings.data_dir, sources, client)
        for camera_id in args.camera:
            report = gate.assess_range(camera_id, args.start, args.end, spark=args.spark, redo=args.redo)
            print(f"{camera_id}: {report.summary()}")


if __name__ == "__main__":
    main()
