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

import dataclasses
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
import yaml
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from vigil.agent.bulletin import COLORS, OVERLAY_WIDTH
from vigil.config import ConfigError, Volcano
from vigil.meta.sam import SamObject, fit_mask
from vigil.overlay import Layer, draw_layers
from vigil.timeutil import parse_utc
from vigil.tracking import detection_mask

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
