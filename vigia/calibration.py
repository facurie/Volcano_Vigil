"""Camera calibration from config/calibration.yaml, and its Monte Carlo samples.

The file holds the vent each volcano's heights are measured from, and per
camera its position and one preset per view: a PTZ camera gets a new preset
whenever its framing changes, each valid for a span of capture times. A
preset lists the references that fix where the camera points (see
vigia.geometry): landmarks with published positions, the vent where it
appears, celestial bodies in known directions (the Moon), pixels on the sea
horizon, and priors on the lens's field of view (from its datasheet), on
the roll of a level pan-tilt-zoom mount and on the radial distortion.
Official eruption values never go in here; they only check the result
(docs/VALIDATION.md).

`sample_geometry` draws N samples of everything uncertain (the camera and
vent positions, landmark positions, refraction, every picked pixel and the
priors) and re-solves the view for each. Sample 0 is the nominal solution;
the spread of the others gives each measurement's sigma.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from vigia.config import ConfigError


class Site(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    elev_m: float
    sigma_m: float = Field(default=0, ge=0)       # horizontal uncertainty, one standard deviation
    sigma_elev_m: float = Field(default=0, ge=0)
    source: str = ""


class Landmark(Site):
    name: str
    pixel: tuple[float, float]                   # column, row in the preset's image
    sigma_px: tuple[float, float] = (2.0, 2.0)


class VentPixel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pixel: tuple[float, float]
    sigma_px: tuple[float, float] = (3.0, 3.0)
    note: str = ""


class Celestial(BaseModel):
    """A body seen in a known direction: its apparent (refracted) azimuth and elevation from the camera at
    the capture time of the frame its pixel was picked on, e.g. the Moon's centre from JPL Horizons."""

    model_config = ConfigDict(extra="forbid")

    name: str
    pixel: tuple[float, float]
    sigma_px: tuple[float, float] = (2.0, 2.0)
    az_deg: float = Field(ge=0, lt=360)
    el_deg: float = Field(ge=-90, le=90)
    source: str = ""


class HorizonPixel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pixel: tuple[float, float]
    sigma_px: float = Field(default=3.0, gt=0)   # across the line


class FieldOfView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hfov_deg: float = Field(gt=0, lt=180)
    sigma_deg: float = Field(default=0.5, gt=0)
    source: str = ""


class Distortion(BaseModel):
    """A prior on the lens's radial distortion k1 (vigia.geometry.View); a wide sigma leaves it to the references."""

    model_config = ConfigDict(extra="forbid")

    k1: float = 0.0
    sigma: float = Field(gt=0)
    source: str = ""


class Roll(BaseModel):
    """A prior on the roll: a pan-tilt-zoom camera on a level mount keeps it near 0 at any pan and tilt."""

    model_config = ConfigDict(extra="forbid")

    deg: float = 0.0
    sigma_deg: float = Field(gt=0)
    source: str = ""


class Preset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    valid_from: AwareDatetime
    valid_until: AwareDatetime | None = None     # exclusive; None: still valid
    image_size: tuple[int, int]
    vent_pixel: VentPixel | None = None
    landmarks: list[Landmark] = []
    celestial: list[Celestial] = []
    horizon: list[HorizonPixel] = []
    fov: FieldOfView | None = None
    distortion: Distortion | None = None         # None: a plain pinhole lens, k1 = 0
    roll: Roll | None = None
    note: str = ""

    def covers(self, when: datetime) -> bool:
        return self.valid_from <= when and (self.valid_until is None or when < self.valid_until)


class CameraCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    volcano: str
    position: Site
    presets: list[Preset] = []


class Calibration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vents: dict[str, Site]
    cameras: dict[str, CameraCalibration] = {}

    @model_validator(mode="after")
    def _check(self) -> Calibration:
        for camera_id, camera in self.cameras.items():
            if camera.volcano not in self.vents:
                raise ValueError(f"camera {camera_id}: no vent for volcano {camera.volcano}")
            presets = sorted(camera.presets, key=lambda p: p.valid_from)
            for earlier, later in zip(presets, presets[1:]):
                if earlier.valid_until is None or earlier.valid_until > later.valid_from:
                    raise ValueError(f"camera {camera_id}: presets {earlier.name} and {later.name} overlap")
        return self

    def preset_for(self, camera_id: str, when: datetime) -> Preset | None:
        """The camera's preset in force at `when`, or None if the camera or that time is not calibrated."""
        camera = self.cameras.get(camera_id)
        return next((p for p in camera.presets if p.covers(when)), None) if camera else None


def load_calibration(path: str | Path) -> Calibration:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    try:
        return Calibration.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc
