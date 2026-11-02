"""Fountaining alerts: watch the alert cameras' new frames and say when lava fountaining starts and when it stops.

At every step (every minute live, every simulated minute in a replay), for each camera in config/alerts.yaml:
1. Local checks, free (vigil.quality): a dark, foggy or stale frame is skipped.
2. SAM 3.1 looks for a 'lava fountain' on a frame when a look is due: every QUIET_EVERY while lava is visible (the
   frame's glow fraction reaches LAVA_GLOW), every HEARTBEAT when it is not, every ACTIVE_EVERY while the volcano is
   fountaining, and on the very next frame after an episode-size sighting or, while fountaining, after a miss.
3. A sighting is episode-size when its mask covers at least the camera's fountain_area of the frame. On V1cam the
   overflows before episode 55 never covered more than 0.033 of the frame, and the episode's fountain 0.137 or more
   (docs/research/alerts_calibration.md). Between ambiguous_area and fountain_area, Muse Spark compares the frame
   with the camera's frame from COMPARE_AGO earlier.
4. Onset, while the volcano is quiet: two consecutive episode-size sightings on one camera, at most PAIR_WITHIN
   apart, and Muse Spark's word that the fountain is sustained and larger than before (asked once, unless it
   already confirmed one of the two). End, while fountaining: every camera that saw this episode's fountain has
   missed it on its last two looks or has not looked for BLIND_AFTER, and at least one has missed it twice.
Each look is a row of alert_checks, and each change an alert (the alerts table) with its texts in English and
Spanish, the frame with its mask, the disclaimer and the link to the official agency. The state lives in the alerts
table, so a restart or a resumed replay keeps it. Nothing in a step looks past `now`. The live loop also posts new
alerts to Telegram (vigil.telegram); a replay never does.

    vigil-alerts --volcano kilauea
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sqlite3
import sys
import time
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
import numpy as np
import openai
import yaml
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from vigil import db, masks
from vigil.agent.bulletin import COLORS, DISCLAIMER, DISCLAIMER_ES, OVERLAY_WIDTH
from vigil.agent.loop import context_from_settings
from vigil.agent.tools import ToolContext
from vigil.config import Camera, ConfigError, Volcano, load_sources
from vigil.episodes import EPISODES
from vigil.imaging import load_for_upload
from vigil.meta.client import MetaClient
from vigil.meta.ledger import BudgetExceeded, CostLedger
from vigil.meta.sam import SamObject, fit_mask
from vigil.overlay import Layer, draw_layers
from vigil.quality import ImageStats, check_local, measure
from vigil.settings import Settings
from vigil.sun import solar_elevation
from vigil.telegram import Telegram, TelegramError, describe
from vigil.timeutil import parse_utc, to_iso, utcnow
from vigil.tracking import detection_mask

log = logging.getLogger(__name__)

PHRASE = "lava fountain"
CAPTION_MAX = 1024  # Telegram's limit on a photo's caption
MIN_SCORE = 0.5  # SAM's floor: overflow and fountain sightings both scored 0.50-0.91, so the size decides
Size = Literal["none", "small", "ambiguous", "large"]
Kind = Literal["onset", "end"]


class CameraRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fountain_area: float = Field(gt=0, le=1)   # share of the frame from which a sighting is episode-size
    ambiguous_area: float = Field(gt=0, le=1)  # from here up to fountain_area, Muse Spark decides

    @model_validator(mode="after")
    def _ordered(self) -> CameraRule:
        if self.ambiguous_area >= self.fountain_area:
            raise ValueError("ambiguous_area must be below fountain_area")
        return self


class AlertConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cameras: dict[str, CameraRule]


def load_alert_config(path: str | Path) -> AlertConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    try:
        return AlertConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc


@dataclass(frozen=True)
class Sighting:
    score: float
    area: float                     # the mask's pixels as a share of the frame
    box: tuple[int, int, int, int]  # left, top, right, bottom: half-open, in the frame's pixels
    mask: np.ndarray                # bool, box-sized, in the frame's pixels


def best_sighting(objects: list[SamObject], sent: tuple[int, int], frame: tuple[int, int]) -> Sighting | None:
    """SAM's highest-scoring object of at least MIN_SCORE, moved from the image sent (width, height) to the frame's
    pixels; None if there is none."""
    kept = [obj for obj in objects if (obj.score or 0.0) >= MIN_SCORE]
    if not kept:
        return None
    obj = max(kept, key=lambda o: o.score or 0.0)
    sx, sy = frame[0] / sent[0], frame[1] / sent[1]
    left, top, right, bottom = obj.box
    box = (round(left * sx), round(top * sy), max(round(right * sx), round(left * sx) + 1),
           max(round(bottom * sy), round(top * sy) + 1))
    mask = fit_mask(obj.mask, box[3] - box[1], box[2] - box[0])
    return Sighting(float(obj.score or 0.0), obj.area_px / (sent[0] * sent[1]), box, mask)


def size_of(sighting: Sighting | None, rule: CameraRule) -> Size:
    if sighting is None:
        return "none"
    if sighting.area >= rule.fountain_area:
        return "large"
    return "ambiguous" if sighting.area >= rule.ambiguous_area else "small"


HEADLINES = {
    "onset": ("Lava fountaining seen at the summit of {name}", "Fuente de lava visible en la cumbre del {name}"),
    "end": ("Lava fountaining has stopped at the summit of {name}",
            "Terminaron las fuentes de lava en la cumbre del {name}"),
}
TEXTS = {
    "onset": (
        "{camera} shows a lava fountain far larger than the overflows before it: at {seen} and again at {when} "
        "local time ({utc} UTC, {date}). Only {agency} declares an eruptive episode.",
        "{camera} muestra una fuente de lava mucho mayor que los desbordes previos: a las {seen} y de nuevo a las "
        "{when}, hora local ({utc} UTC, {date}). Solo {agency} declara un episodio eruptivo."),
    "end": (
        "No lava fountain on {cameras} since {seen} local time, when {seen_by} last showed one; confirmed at {when} "
        "({utc} UTC, {date}). It had lasted {duration} since it was first seen at {onset}.",
        "Ninguna fuente de lava en {cameras} desde las {seen}, hora local, cuando {seen_by} mostró una por última "
        "vez; confirmado a las {when} ({utc} UTC, {date}). Duró {duration} desde que se vio por primera vez a las "
        "{onset}."),
}
NOTE_EN = "Automated, experimental reading of public webcams by Volcano Vigil. It does not replace official alerts."
NOTE_ES = ("Lectura automática y experimental de cámaras públicas hecha por Volcano Vigil. No reemplaza las alertas "
           "oficiales.")


class Alert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    volcano: str
    volcano_name: str
    utc_offset_hours: float | None
    kind: Kind
    clock: str           # UTC, when the watcher raised it
    created_at: str      # UTC wall clock
    camera_id: str       # the camera whose frame shows the change
    camera_name: str
    frame_id: int
    captured_at: str     # UTC capture time of that frame
    seen_at: str         # onset: the first episode-size sighting; end: the fountain's last sighting
    seen_by: str         # the camera of that sighting
    headline_en: str
    headline_es: str
    text_en: str
    text_es: str
    overlay: str         # the frame with its mask, relative to the data dir
    official_agency: str
    official_url: str
    disclaimer_en: str
    disclaimer_es: str


def _local(utc: str, offset_hours: float | None) -> str:
    return f"{parse_utc(utc) + timedelta(hours=offset_hours or 0):%H:%M}"


def duration_text(span: timedelta) -> str:
    minutes = round(span / timedelta(minutes=1))
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


def _names(names: tuple[str, ...], lang: str) -> str:
    if len(names) < 2:
        return "".join(names)
    return f"{', '.join(names[:-1])} {'and' if lang == 'en' else 'y'} {names[-1]}"


def alert_texts(kind: Kind, volcano: Volcano, *, camera: str, captured_at: str, seen_at: str, seen_by: str,
                onset_at: str | None = None, cameras: tuple[str, ...] = ()) -> dict[str, str]:
    """The headline and text in English and Spanish, written by the code from stored times only."""
    offset = volcano.utc_offset_hours
    words = {"name": volcano.name, "camera": camera, "seen": _local(seen_at, offset),
             "when": _local(captured_at, offset), "utc": captured_at[11:16], "date": captured_at[:10],
             "agency": volcano.official_agency, "seen_by": seen_by,
             "onset": _local(onset_at, offset) if onset_at else "",
             "duration": duration_text(parse_utc(seen_at) - parse_utc(onset_at)) if onset_at else ""}
    (head_en, head_es), (text_en, text_es) = HEADLINES[kind], TEXTS[kind]
    return {"headline_en": head_en.format(**words), "headline_es": head_es.format(**words),
            "text_en": text_en.format(**words, cameras=_names(cameras, "en")),
            "text_es": text_es.format(**words, cameras=_names(cameras, "es"))}


def caption(alert: Alert, prefix: str = "") -> str:
    """The Telegram caption: both languages, the notes and the official link (at most CAPTION_MAX characters)."""
    lines = [prefix, ""] if prefix else []
    lines += [alert.headline_en, alert.text_en, NOTE_EN, "", alert.headline_es, alert.text_es, NOTE_ES, "",
              f"{alert.official_agency}: {alert.official_url}"]
    return "\n".join(lines)


def store_alert(conn: sqlite3.Connection, alert: Alert) -> Alert:
    """Insert the alert; returns it with its id."""
    with conn:
        alert_id = conn.execute(
            """INSERT INTO alerts (volcano, kind, clock, created_at, camera_id, frame_id, captured_at, seen_at, body)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, '')""",
            (alert.volcano, alert.kind, alert.clock, alert.created_at, alert.camera_id, alert.frame_id,
             alert.captured_at, alert.seen_at)).lastrowid
        stored = alert.model_copy(update={"id": alert_id})
        conn.execute("UPDATE alerts SET body = ? WHERE id = ?", (stored.model_dump_json(), alert_id))
    return stored


def load_alert(conn: sqlite3.Connection, alert_id: int) -> Alert:
    row = conn.execute("SELECT body FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if row is None:
        raise KeyError(f"no alert {alert_id}")
    return Alert.model_validate_json(row["body"])


def draw_alert_frame(data_dir: Path, frame: Mapping[str, Any], look: Mapping[str, Any] | None, folder: Path) -> str:
    """The frame at most OVERLAY_WIDTH wide, with the look's fountain mask tinted when it has one, saved in `folder`
    (inside the data dir); returns its path relative to the data dir."""
    with Image.open(data_dir / frame["path"]) as source:
        image = source.convert("RGB")
    layers = []
    if look is not None and look["mask_rle"] is not None:
        layers.append(Layer(detection_mask(look, frame["width"], frame["height"]), COLORS["fountain"],
                            f"fountain: {PHRASE}"))
    scale = min(1.0, OVERLAY_WIDTH / image.width)
    if scale < 1:
        size = (round(image.width * scale), round(image.height * scale))
        image = image.resize(size, Image.Resampling.LANCZOS)
        layers = [dataclasses.replace(layer, mask=np.asarray(
            Image.fromarray(layer.mask).resize(size, Image.Resampling.NEAREST), dtype=bool)) for layer in layers]
    path = folder / f"frame{frame['id']}.jpg"
    relative = path.relative_to(data_dir).as_posix()  # before writing: a folder outside the data dir leaves no file
    folder.mkdir(parents=True, exist_ok=True)
    draw_layers(image, layers).save(path, quality=85)
    return relative


QUIET_EVERY = timedelta(minutes=8)    # a look while quiet and lava is visible
HEARTBEAT = timedelta(minutes=30)     # a look while quiet and no lava is visible, e.g. on a clear day
ACTIVE_EVERY = timedelta(minutes=6)   # a look while fountaining
SLACK = timedelta(minutes=1)          # frames come every ~2 min, seconds early or late
LOOKBACK = timedelta(minutes=10)      # a step looks at frames this recent, so a restart never looks at history
LAVA_GLOW = 0.003                     # glow fraction from which lava is visible; quiet days on V1: median 0.0003
State = Literal["quiet", "fountaining"]
Segment = Callable[[MetaClient, int, bytes], list[SamObject]]
Compare = Callable[[MetaClient, bytes, bytes, int], dict[str, Any]]


def sam_segment(client: MetaClient, frame_id: int, jpeg: bytes) -> list[SamObject]:
    return client.segment_image(jpeg, PHRASE, purpose="segment")


PAIR_WITHIN = timedelta(minutes=10)   # two sightings this close are consecutive
COMPARE_AGO = timedelta(minutes=30)   # Muse Spark compares a frame with the camera's frame this much earlier
COMPARE_SPAN = timedelta(hours=2)     # ... found within this span; after a gap, with the oldest frame in it
BLIND_AFTER = timedelta(minutes=20)   # a camera that has not looked for this long cannot hold the end back

COMPARE_PROMPT = (
    "These two frames come from the same USGS webcam at the summit of Kilauea, {minutes} minutes apart: the first "
    "is the earlier one, the second is now. Between eruptive episodes, lava overflows the vents and can form low "
    "dome fountains and lava cascades a few metres high. An episode begins when a lava fountain at a vent becomes "
    "sustained and grows much taller and wider than those overflows. Report only what you can see. Is there a lava "
    "fountain in the second frame, and is it clearly taller and wider than anything in the first frame?"
)
COMPARE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fountain_visible": {"type": "boolean"},
        "larger_than_before": {"type": "boolean"},
        "looks_like": {"type": "string",
                       "enum": ["no_fountain", "overflow_or_dome", "sustained_fountain", "unclear"]},
        "reason": {"type": "string"},
    },
    "additionalProperties": False,
}
COMPARE_SCHEMA["required"] = list(COMPARE_SCHEMA["properties"])


def spark_compare(client: MetaClient, earlier: bytes, now: bytes, minutes: int) -> dict[str, Any]:
    """Muse Spark's comparison of two frames of one camera (validated on 4 pairs, docs/research/alerts_calibration.md)."""
    return client.ask_json(prompt=COMPARE_PROMPT.format(minutes=minutes), images=[earlier, now],
                           schema_name="fountain_check", schema=COMPARE_SCHEMA, purpose="compare")


def sustained(answer: dict[str, Any]) -> bool:
    return answer.get("looks_like") == "sustained_fountain" and bool(answer.get("larger_than_before"))


def short_name(camera: Camera) -> str:
    """'V1cam' for 'V1cam (Halemaʻumaʻu vents, PTZ)'."""
    return camera.name.split(" (")[0]


@dataclass
class AlertReport:
    clock: datetime
    looks: list[dict[str, Any]] = field(default_factory=list)   # camera_id, frame_id, captured_at, size, episode
    alerts: list[dict[str, Any]] = field(default_factory=list)  # id, kind, camera_id, captured_at
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"clock": to_iso(self.clock), "looks": self.looks, "alerts": self.alerts, "errors": self.errors}

    def summary(self) -> str:
        parts = [f"{to_iso(self.clock)}: {len(self.looks)} looks"]
        parts += [f"{look['camera_id']} {look['captured_at'][11:19]} {look['size']}" for look in self.looks]
        parts += [f"ALERT {a['kind']} #{a['id']} ({a['camera_id']} {a['captured_at'][11:19]})" for a in self.alerts]
        return "; ".join(parts) + "".join(f"\n  failed: {error}" for error in self.errors)


class AlertWatcher:
    """The fountaining alerts of one volcano's alert cameras. Each step sets its own clock; `base.now` is unused."""

    def __init__(self, base: ToolContext, volcano: str, config: AlertConfig, out_dir: Path, *, budget_usd: float,
                 segment: Segment = sam_segment, compare: Compare = spark_compare,
                 wall_clock: Callable[[], datetime] = utcnow):
        self.base, self.volcano, self.config, self.out_dir = base, volcano, config, out_dir
        self.budget_usd = budget_usd  # per UTC day of the clock, under the tag alerts:<date>
        self._segment, self._compare, self._wall_clock = segment, compare, wall_clock
        self._seen: dict[str, str] = {}  # camera id -> capture time of the newest frame considered in this run

    @property
    def cameras(self) -> tuple[str, ...]:
        return tuple(self.config.cameras)

    def step(self, now: datetime) -> AlertReport:
        if now.tzinfo is None:
            raise ValueError("the alert clock needs a time zone")
        now = now.astimezone(timezone.utc)  # the budget tag's date and the alert folders' names are UTC
        report = AlertReport(now)
        if self.base.client is None:
            report.errors.append("no Meta client: SAM cannot look for a fountain")
            return report
        ctx = dataclasses.replace(self.base, now=now)
        client = self.base.client.tagged(f"alerts:{now:%Y-%m-%d}", self.budget_usd)
        try:
            for camera_id, rule in self.config.cameras.items():
                self._watch(ctx, client, ctx.camera(camera_id), rule, report)
        except BudgetExceeded as exc:
            report.errors.append(f"alerts stopped: {exc}")
        return report

    def state(self, now: datetime) -> tuple[State, sqlite3.Row | None]:
        """The volcano's state at `now`, and the onset alert that started it (None while quiet)."""
        row = self.base.conn.execute(
            "SELECT * FROM alerts WHERE volcano = ? AND clock <= ? ORDER BY clock DESC, id DESC LIMIT 1",
            (self.volcano, to_iso(now))).fetchone()
        return ("fountaining", row) if row is not None and row["kind"] == "onset" else ("quiet", None)

    def _watch(self, ctx: ToolContext, client: MetaClient, camera: Camera, rule: CameraRule,
               report: AlertReport) -> None:
        since = max(to_iso(ctx.now - LOOKBACK), self._seen.get(camera.id, ""))
        frames = ctx.conn.execute(
            "SELECT * FROM frames WHERE camera_id = ? AND captured_at > ? AND captured_at <= ? ORDER BY captured_at",
            (camera.id, since, to_iso(ctx.now))).fetchall()
        for frame in frames:
            self._seen[camera.id] = frame["captured_at"]
            try:
                self._consider(ctx, client, camera, rule, frame, report)
            except (openai.APIError, ValueError, OSError) as exc:  # SAM failed, an unreadable image, a bad answer
                report.errors.append(f"{camera.id} frame {frame['id']}: {type(exc).__name__}: {exc}"[:300])

    def _looks(self, ctx: ToolContext, camera_id: str, n: int) -> list[sqlite3.Row]:
        """The camera's last n looks by the clock, newest first."""
        return ctx.conn.execute(
            "SELECT * FROM alert_checks WHERE camera_id = ? AND captured_at <= ? AND clock <= ? "
            "ORDER BY captured_at DESC LIMIT ?", (camera_id, to_iso(ctx.now), to_iso(ctx.now), n)).fetchall()

    def _follow_up(self, ctx: ToolContext, last: sqlite3.Row, state: State, onset: sqlite3.Row | None) -> bool:
        """True if the camera's next frame needs a look at once: after an episode-size sighting while quiet, or
        after a miss on a camera that saw this episode's fountain."""
        if state == "quiet":
            return bool(last["episode"])
        return last["size"] == "none" and self._saw(ctx, last["camera_id"], onset)

    def _saw(self, ctx: ToolContext, camera_id: str, onset: sqlite3.Row | None) -> bool:
        return onset is not None and ctx.conn.execute(
            "SELECT 1 FROM alert_checks WHERE camera_id = ? AND size != 'none' AND captured_at >= ? "
            "AND captured_at <= ? AND clock <= ? LIMIT 1",
            (camera_id, onset["seen_at"], to_iso(ctx.now), to_iso(ctx.now))).fetchone() is not None

    def _consider(self, ctx: ToolContext, client: MetaClient, camera: Camera, rule: CameraRule,
                  frame: sqlite3.Row, report: AlertReport) -> None:
        state, onset = self.state(ctx.now)
        captured = parse_utc(frame["captured_at"])
        last = self._looks(ctx, camera.id, 1)
        if last and frame["captured_at"] <= last[0]["captured_at"]:
            return
        since = captured - parse_utc(last[0]["captured_at"]) if last else None
        follow_up = bool(last) and self._follow_up(ctx, last[0], state, onset)
        every = ACTIVE_EVERY if state == "fountaining" else QUIET_EVERY
        if not follow_up and since is not None and since < every - SLACK:
            return
        image, jpeg = load_for_upload(ctx.data_dir / frame["path"])
        stats = measure(image)
        volcano = ctx.sources.volcanoes[camera.volcano]
        sun = (solar_elevation(captured, volcano.lat, volcano.lon)
               if volcano.lat is not None and volcano.lon is not None else None)
        local = check_local(stats, kind=camera.kind, captured_at=captured, sun_elevation=sun, change=None,
                            now=ctx.now)
        if local.decision == "reject":
            return
        lava = stats.glow_fraction >= LAVA_GLOW
        heartbeat = since is None or since >= HEARTBEAT - SLACK
        if state == "quiet" and not (follow_up or lava or heartbeat):
            return
        self._look(ctx, client, camera, rule, frame, image, jpeg, stats, state, onset, report)

    def _look(self, ctx: ToolContext, client: MetaClient, camera: Camera, rule: CameraRule, frame: sqlite3.Row,
              image: Image.Image, jpeg: bytes, stats: ImageStats, state: State, onset: sqlite3.Row | None,
              report: AlertReport) -> None:
        sighting = best_sighting(self._segment(client, frame["id"], jpeg), image.size,
                                 (frame["width"], frame["height"]))
        size = size_of(sighting, rule)
        answer, episode = None, size == "large"
        look_id = self._store_look(ctx, frame, stats, sighting, size, answer, episode)  # SAM is paid: keep its look
        entry = {"camera_id": camera.id, "frame_id": frame["id"], "captured_at": frame["captured_at"],
                 "size": size, "episode": episode}
        report.looks.append(entry)
        if state == "quiet" and size == "ambiguous":
            answer = self._ask(ctx, client, camera, frame, report)
            if answer is not None:
                episode = sustained(answer)
                self._set_spark(ctx, look_id, answer, episode)
        if state == "quiet" and episode:
            entry["episode"] = self._onset(ctx, client, camera, frame, look_id, answer, report)
        elif state == "fountaining" and size == "none":
            self._end(ctx, camera, frame, onset, report)

    def _ask(self, ctx: ToolContext, client: MetaClient, camera: Camera, frame: sqlite3.Row,
             report: AlertReport) -> dict[str, Any] | None:
        """Muse Spark's comparison of the frame with the camera's newest frame at least COMPARE_AGO older (or, after a
        gap, its oldest frame of the last COMPARE_SPAN); None if there is none or the call failed."""
        captured = parse_utc(frame["captured_at"])
        earlier = ctx.conn.execute(
            "SELECT * FROM frames WHERE camera_id = ? AND captured_at BETWEEN ? AND ? ORDER BY captured_at DESC LIMIT 1",
            (camera.id, to_iso(captured - COMPARE_SPAN), to_iso(captured - COMPARE_AGO))).fetchone()
        if earlier is None:
            earlier = ctx.conn.execute(
                "SELECT * FROM frames WHERE camera_id = ? AND captured_at >= ? AND captured_at < ? "
                "ORDER BY captured_at LIMIT 1",
                (camera.id, to_iso(captured - COMPARE_SPAN), frame["captured_at"])).fetchone()
        if earlier is None:
            report.errors.append(f"{camera.id} frame {frame['id']}: no earlier frame for Muse Spark to compare with")
            return None
        minutes = round((captured - parse_utc(earlier["captured_at"])) / timedelta(minutes=1))
        images = [load_for_upload(ctx.data_dir / row["path"], max_side=1280)[1] for row in (earlier, frame)]
        try:
            return self._compare(client, images[0], images[1], minutes)
        except (openai.APIError, ValueError, KeyError) as exc:
            report.errors.append(f"{camera.id} frame {frame['id']}: Muse Spark failed: {type(exc).__name__}: {exc}"[:300])
            return None

    def _set_spark(self, ctx: ToolContext, look_id: int, answer: dict[str, Any], episode: bool) -> None:
        with ctx.conn:
            ctx.conn.execute("UPDATE alert_checks SET spark = ?, episode = ? WHERE id = ?",
                             (json.dumps(answer, ensure_ascii=False), int(episode), look_id))

    def _onset(self, ctx: ToolContext, client: MetaClient, camera: Camera, frame: sqlite3.Row, look_id: int,
               answer: dict[str, Any] | None, report: AlertReport) -> bool:
        """Raise the onset if this episode-size look and the camera's previous one are consecutive, once Muse Spark
        has confirmed one of them (it is asked now if it has not). False if Muse Spark said this look is not a
        sustained fountain, so that it no longer counts as an episode-size look."""
        looks = self._looks(ctx, camera.id, 2)  # this look, then the one before it
        if len(looks) < 2 or not looks[1]["episode"]:
            return True
        if parse_utc(looks[0]["captured_at"]) - parse_utc(looks[1]["captured_at"]) > PAIR_WITHIN:
            return True
        if answer is None and looks[1]["spark"] is None:
            answer = self._ask(ctx, client, camera, frame, report)
            if answer is None:
                return True  # asked again with the next frame, which is a follow-up
            confirmed = sustained(answer)
            self._set_spark(ctx, look_id, answer, confirmed)
            if not confirmed:
                return False
        self._raise(ctx, "onset", camera, frame, looks[0], seen_at=looks[1]["captured_at"],
                    seen_by=short_name(camera), report=report)
        return True

    def _end(self, ctx: ToolContext, camera: Camera, frame: sqlite3.Row, onset: sqlite3.Row,
             report: AlertReport) -> None:
        """Raise the end if every camera that saw this episode's fountain missed it on its last two looks or has not
        looked for BLIND_AFTER, and at least one missed it twice. The alert names the cameras that missed it twice,
        never a blind one: its last look saw the fountain."""
        now = to_iso(ctx.now)
        seen = [row[0] for row in ctx.conn.execute(
            "SELECT DISTINCT camera_id FROM alert_checks WHERE size != 'none' AND captured_at >= ? "
            "AND captured_at <= ? AND clock <= ? ORDER BY camera_id", (onset["seen_at"], now, now))]
        if camera.id not in seen:
            return
        sightings, missed_twice = [], []
        for camera_id in seen:
            looks = self._looks(ctx, camera_id, 2)
            sightings.append(ctx.conn.execute(
                "SELECT camera_id, captured_at FROM alert_checks WHERE camera_id = ? AND size != 'none' "
                "AND captured_at <= ? AND clock <= ? ORDER BY captured_at DESC LIMIT 1",
                (camera_id, now, now)).fetchone())
            if len(looks) == 2 and all(look["size"] == "none" for look in looks):
                missed_twice.append(camera_id)
            elif looks and ctx.now - parse_utc(looks[0]["captured_at"]) <= BLIND_AFTER:
                return
        if not missed_twice:
            return
        last = max(sightings, key=lambda row: row["captured_at"])
        look = self._looks(ctx, camera.id, 1)[0]
        self._raise(ctx, "end", camera, frame, look, seen_at=last["captured_at"],
                    seen_by=short_name(ctx.camera(last["camera_id"])), report=report, onset=onset,
                    cameras=tuple(missed_twice))

    def _raise(self, ctx: ToolContext, kind: Kind, camera: Camera, frame: sqlite3.Row, look: sqlite3.Row, *,
               seen_at: str, seen_by: str, report: AlertReport, onset: sqlite3.Row | None = None,
               cameras: tuple[str, ...] = ()) -> None:
        volcano = ctx.sources.volcanoes[self.volcano]
        overlay = draw_alert_frame(ctx.data_dir, frame, look, self.out_dir / f"{ctx.now:%Y%m%dT%H%MZ}_{kind}")
        texts = alert_texts(kind, volcano, camera=short_name(camera), captured_at=frame["captured_at"],
                            seen_at=seen_at, seen_by=seen_by,
                            onset_at=None if onset is None else onset["seen_at"],
                            cameras=tuple(short_name(ctx.camera(camera_id)) for camera_id in cameras))
        names = {"name": volcano.name, "agency": volcano.official_agency, "url": volcano.official_url}
        alert = store_alert(ctx.conn, Alert(
            volcano=self.volcano, volcano_name=volcano.name, utc_offset_hours=volcano.utc_offset_hours, kind=kind,
            clock=to_iso(ctx.now), created_at=to_iso(self._wall_clock()), camera_id=camera.id,
            camera_name=short_name(camera), frame_id=frame["id"], captured_at=frame["captured_at"],
            seen_at=seen_at, seen_by=seen_by, overlay=overlay, official_agency=volcano.official_agency,
            official_url=volcano.official_url, disclaimer_en=DISCLAIMER.format(**names),
            disclaimer_es=DISCLAIMER_ES.format(**names), **texts))
        report.alerts.append({"id": alert.id, "kind": kind, "camera_id": camera.id,
                              "captured_at": frame["captured_at"]})
        log.info("alert %s: %s on %s at %s", alert.id, kind, camera.id, frame["captured_at"])

    def _store_look(self, ctx: ToolContext, frame: sqlite3.Row, stats: ImageStats, sighting: Sighting | None,
                    size: Size, answer: dict[str, Any] | None, episode: bool) -> int:
        box = sighting.box if sighting is not None else (None, None, None, None)
        with ctx.conn:
            return ctx.conn.execute(
                """INSERT INTO alert_checks (frame_id, camera_id, captured_at, clock, glow, score, area, box_left,
                       box_top, box_right, box_bottom, mask_rle, size, spark, episode)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (frame["id"], frame["camera_id"], frame["captured_at"], to_iso(ctx.now), stats.glow_fraction,
                 None if sighting is None else sighting.score, None if sighting is None else sighting.area, *box,
                 None if sighting is None else json.dumps(masks.encode(sighting.mask)), size,
                 None if answer is None else json.dumps(answer, ensure_ascii=False), int(episode))).lastrowid


SEND_WITHIN = timedelta(hours=2)  # an alert older than this is never posted (after a long outage, say)
MAX_SEND_ATTEMPTS = 5
REPLAY_NOTE = "REPLAY of episode {key} ({date}): not a live alert. / REPETICIÓN del episodio {key}: no es una alerta en vivo."


def send_pending(conn: sqlite3.Connection, telegram: Telegram, data_dir: Path, now: datetime) -> list[str]:
    """Post the alerts raised in the last SEND_WITHIN that are not posted yet, oldest first; returns the failures. A
    failed post is tried again on later steps, MAX_SEND_ATTEMPTS times in all."""
    errors = []
    rows = conn.execute(
        "SELECT id, body FROM alerts WHERE sent_at IS NULL AND send_attempts < ? AND clock >= ? ORDER BY clock, id",
        (MAX_SEND_ATTEMPTS, to_iso(now - SEND_WITHIN))).fetchall()
    for row in rows:
        try:
            alert = Alert.model_validate_json(row["body"])
            telegram.send_photo((data_dir / alert.overlay).read_bytes(), caption(alert))
        except (TelegramError, OSError, ValueError) as exc:  # a caption over the limit or a bad stored body, too
            with conn:
                conn.execute("UPDATE alerts SET send_attempts = send_attempts + 1, send_error = ? WHERE id = ?",
                             (str(exc)[:300], row["id"]))
            errors.append(f"alert {row['id']} not posted: {exc}"[:300])
            continue
        with conn:
            conn.execute("UPDATE alerts SET sent_at = ?, send_error = NULL WHERE id = ?", (to_iso(now), row["id"]))
    return errors


def post_replay(data_dir: Path, key: str, telegram: Telegram) -> list[int]:
    """Post an episode's replayed alerts, each marked as a replay (for demos); returns the message ids."""
    path = data_dir / "replay" / f"ep{key}" / "vigil.sqlite"
    with closing(db.connect_readonly(path)) as conn:
        alerts = [Alert.model_validate_json(row[0]) for row in conn.execute("SELECT body FROM alerts ORDER BY clock")]
    prefix = REPLAY_NOTE.format(key=key, date=EPISODES[key].start.date().isoformat())
    return [telegram.send_photo((data_dir / alert.overlay).read_bytes(), caption(alert, prefix)) for alert in alerts]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Watch a volcano's alert cameras (config/alerts.yaml) for lava "
                                                 "fountaining starting and stopping, and post each change to "
                                                 "Telegram. Run vigil-ingest alongside it.")
    parser.add_argument("--volcano", required=True, help="volcano id from the sources file, e.g. kilauea")
    parser.add_argument("--interval", type=float, default=1, help="minutes between steps (default 1)")
    parser.add_argument("--once", action="store_true", help="run one step and exit")
    parser.add_argument("--post-replay", metavar="EPISODE", choices=sorted(EPISODES),
                        help="post that episode's replayed alerts to Telegram, marked as a replay, and exit")
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be positive")
    settings = Settings.from_env()
    sources = load_sources(settings.sources_path)
    if args.volcano not in sources.volcanoes:
        parser.error(f"unknown volcano {args.volcano!r} in {settings.sources_path}")
    config = load_alert_config(settings.alerts_path)
    enabled = {camera.id for camera in sources.enabled_cameras() if camera.volcano == args.volcano}
    missing = [camera_id for camera_id in config.cameras if camera_id not in enabled]
    if missing:
        parser.error(f"alert cameras not enabled for {args.volcano} in {settings.sources_path}: {', '.join(missing)}")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its request lines would print the Telegram token
    with closing(db.connect(settings.db_path)) as conn, httpx.Client() as telegram_http, \
            httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=30) as http:
        telegram = (Telegram(telegram_http, settings.telegram_token, settings.telegram_chat, settings.telegram_api)
                    if settings.telegram_token and settings.telegram_chat else None)
        if args.post_replay:
            if telegram is None:
                parser.error("set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to post")
            print(f"posted messages {post_replay(settings.data_dir, args.post_replay, telegram)}")
            return
        if telegram is None:
            log.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set: alerts are stored but not posted")
        else:
            try:
                log.info("Telegram: %s", describe(telegram.check()))
            except TelegramError as exc:
                log.warning("Telegram check failed (posts are still tried): %s", exc)
        client = MetaClient.from_env(CostLedger(conn, settings.daily_budget_usd))
        watcher = AlertWatcher(context_from_settings(settings, conn, http, utcnow(), client, sources), args.volcano,
                               config, settings.data_dir / "alerts", budget_usd=settings.alert_reserve_usd)
        while True:
            try:
                report = watcher.step(utcnow())
                if telegram is not None:
                    report.errors += send_pending(conn, telegram, settings.data_dir, utcnow())
                if report.looks or report.alerts or report.errors:
                    print(report.summary(), flush=True)
            except Exception:
                if args.once:
                    raise
                log.exception("the step failed; the next one tries again")
            if args.once:
                return
            time.sleep(args.interval * 60)
