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

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from vigil.config import ConfigError
from vigil.meta.sam import SamObject, fit_mask

MIN_SCORE = 0.5  # SAM's floor: overflow and fountain sightings both scored 0.50-0.91, so the size decides
Size = Literal["none", "small", "ambiguous", "large"]


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
