"""Camera and volcano definitions loaded from a YAML sources file.

Every camera must declare its license and attribution. Cameras are disabled
unless explicitly enabled, so a source without permission can live in the
config without ever being fetched. USGS cameras also name their AshCam
archive (`ashcam_code`), from which `vigia-backfill` downloads past frames.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator


class ConfigError(ValueError):
    """Raised when the sources file is missing fields or inconsistent."""


CameraKind = Literal["visible", "thermal"]


class Volcano(BaseModel):
    name: str
    country: str
    official_agency: str
    official_url: str


class Camera(BaseModel):
    id: str
    name: str
    volcano: str
    url: str
    license: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    enabled: bool = False
    poll_minutes: float = Field(default=5, gt=0)
    kind: CameraKind = "visible"
    ashcam_code: str | None = None  # USGS AshCam archive code, e.g. kilauea-kp-cam
    page_url: str | None = None
    notes: str | None = None


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
