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

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from vigia.config import ConfigError
from vigia.geometry import (REFRACTION_K, References, View, direction, horizon_dip, local_en, sight,
                            solve_view)

REFRACTION_SIGMA = 0.05  # the refraction coefficient near the ground varies by about this much


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


@dataclass(frozen=True)
class Geometry:
    """One preset's view and positions for N samples; sample 0 is the nominal solution."""

    camera_id: str
    preset: str
    view: View
    camera_elev: np.ndarray  # (N,) metres above sea level
    vent: np.ndarray         # (N, 3) line of sight from the camera to the vent
    vent_elev: np.ndarray    # (N,)
    refraction: np.ndarray   # (N,) refraction coefficient
    rms_px: np.ndarray       # (N,) how far the references sit from the solved view


def sample_geometry(calibration: Calibration, camera_id: str, preset: Preset, samples: int = 1000,
                    seed: int = 0) -> Geometry:
    """Solve the preset's view for `samples` Monte Carlo draws; raises ValueError if it cannot be fixed."""
    camera = calibration.cameras[camera_id]
    vent = calibration.vents[camera.volcano]
    origin = camera.position
    rng = np.random.default_rng(seed)

    def noise(sigma, shape=()) -> np.ndarray:
        draw = rng.normal(0.0, 1.0, (samples, *shape)) * np.asarray(sigma, dtype=float)
        draw[0] = 0.0
        return draw

    camera_east, camera_north = noise(origin.sigma_m), noise(origin.sigma_m)
    camera_elev = origin.elev_m + noise(origin.sigma_elev_m)
    k = np.clip(REFRACTION_K + noise(REFRACTION_SIGMA), 0.0, 0.5)

    def line_of_sight(site: Site, elev: np.ndarray) -> np.ndarray:
        east, north = local_en(site.lat, site.lon, origin.lat, origin.lon)
        return sight(east + noise(site.sigma_m) - camera_east, north + noise(site.sigma_m) - camera_north,
                     elev - camera_elev, k)

    vent_elev = vent.elev_m + noise(vent.sigma_elev_m)
    vent_sight = line_of_sight(vent, vent_elev)
    points, pixels, sigmas = [], [], []
    if preset.vent_pixel is not None:
        points.append(vent_sight)
        pixels.append(np.asarray(preset.vent_pixel.pixel) + noise(preset.vent_pixel.sigma_px, (2,)))
        sigmas.append(preset.vent_pixel.sigma_px)
    for mark in preset.landmarks:
        points.append(line_of_sight(mark, mark.elev_m + noise(mark.sigma_elev_m)))
        pixels.append(np.asarray(mark.pixel) + noise(mark.sigma_px, (2,)))
        sigmas.append(mark.sigma_px)
    for body in preset.celestial:
        points.append(np.broadcast_to(direction(body.az_deg, body.el_deg), (samples, 3)))
        pixels.append(np.asarray(body.pixel) + noise(body.sigma_px, (2,)))
        sigmas.append(body.sigma_px)
    horizon = np.array([h.pixel for h in preset.horizon], dtype=float).reshape(-1, 2)
    horizon_sigma = np.array([h.sigma_px for h in preset.horizon], dtype=float)
    horizon_px = np.repeat(horizon[None], samples, axis=0)
    horizon_px[..., 1] += noise(horizon_sigma, (len(horizon_sigma),))
    focal = focal_sigma = None
    if preset.fov is not None:
        half_width = preset.image_size[0] / 2
        hfov = preset.fov.hfov_deg + noise(preset.fov.sigma_deg)
        focal = half_width / np.tan(np.radians(hfov) / 2)
        wide, narrow = (half_width / np.tan(np.radians(preset.fov.hfov_deg + s * preset.fov.sigma_deg) / 2)
                        for s in (1, -1))
        focal_sigma = (narrow - wide) / 2
    k1 = k1_sigma = roll = roll_sigma = None
    if preset.distortion is not None:
        k1, k1_sigma = preset.distortion.k1 + noise(preset.distortion.sigma), preset.distortion.sigma
    if preset.roll is not None:
        roll, roll_sigma = preset.roll.deg + noise(preset.roll.sigma_deg), preset.roll.sigma_deg
    refs = References(
        points=np.stack(points, axis=1) if points else np.zeros((samples, 0, 3)),
        points_px=np.stack(pixels, axis=1) if pixels else np.zeros((samples, 0, 2)),
        points_sigma=np.array(sigmas, dtype=float).reshape(-1, 2),
        horizon_px=horizon_px, horizon_el=-horizon_dip(camera_elev, k), horizon_sigma=horizon_sigma,
        focal=focal, focal_sigma=focal_sigma, k1=k1, k1_sigma=k1_sigma, roll=roll, roll_sigma=roll_sigma,
    )
    view, rms = solve_view(refs, preset.image_size)
    return Geometry(camera_id, preset.name, view, camera_elev, vent_sight, vent_elev, k, rms)
