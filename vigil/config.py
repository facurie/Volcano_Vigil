"""Camera and volcano definitions loaded from a YAML sources file.

Every camera must declare its license and attribution. Cameras are disabled
unless explicitly enabled, so a source without permission can live in the
config without ever being fetched. USGS cameras also name their AshCam
archive (`ashcam_code`), from which `vigil-backfill` downloads past frames.
The alert cameras' size rules (config/alerts.yaml) are loaded here too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ConfigError(ValueError):
    """Raised when the sources file is missing fields or inconsistent."""


CameraKind = Literal["visible", "thermal"]


class Volcano(BaseModel):
    name: str
    country: str
    official_agency: str
    official_url: str
    lat: float | None = Field(default=None, ge=-90, le=90)  # summit area: sets the sun's elevation for the night check
    lon: float | None = Field(default=None, ge=-180, le=180)
    utc_offset_hours: float | None = Field(default=None, ge=-12, le=14)  # local standard time; neither volcano
                                                                         # observes daylight saving


class Camera(BaseModel):
    id: str
    name: str
    volcano: str
    url: str
    license: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    enabled: bool = False
    track: bool = True  # the pipeline tracks it hourly with SAM video; False: ingested for the alerts only
    poll_minutes: float = Field(default=5, gt=0)
    kind: CameraKind = "visible"
    ashcam_code: str | None = None  # USGS AshCam archive code, e.g. kilauea-kp-cam
    live_source: Literal["url", "ashcam"] = "url"  # where the live poller gets new frames
    page_url: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _ashcam_needs_a_code(self) -> Camera:
        if self.live_source == "ashcam" and not self.ashcam_code:
            raise ValueError(f"camera {self.id} polls AshCam live but has no ashcam_code")
        return self


class Sources(BaseModel):
    volcanoes: dict[str, Volcano]
    cameras: list[Camera]

    @model_validator(mode="after")
    def _check_references(self) -> Sources:
        seen: set[str] = set()
        for camera in self.cameras:
            if camera.id in seen:
                raise ValueError(f"duplicate camera id: {camera.id}")
            seen.add(camera.id)
            if camera.volcano not in self.volcanoes:
                raise ValueError(f"camera {camera.id} references unknown volcano: {camera.volcano}")
        return self

    def enabled_cameras(self) -> list[Camera]:
        return [c for c in self.cameras if c.enabled]


def load_sources(path: str | Path) -> Sources:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    try:
        return Sources.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc


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
