"""Local frame checks that cost nothing: stale, frozen, dark night and fog.

The measurements cover the scene between the burned-in text bands (the
timestamp at the top; the USGS logo and the PTZ readout at the bottom):
- edge density: the share of pixels where luminance changes by more than 8
  levels per pixel, on a lightly blurred copy at most 512 px wide. Fog
  flattens everything.
- glow fraction: the share of a block-averaged copy (at most 256 px wide)
  covered by 2x2 squares of blocks that are warm and bright (orange lava) or
  nearly white (lava that saturates the sensor, or a camera in monochrome
  night mode). Lone bright blocks, such as stars and K2cam's path lamps, do
  not count.
- fingerprint: a block-averaged luminance copy at most 128 px wide. Two
  consecutive frames of a frozen camera share it, even when the printed time
  changes.

Thresholds were calibrated on episode 55 and on a foggy afternoon, a quiet
night and a clear morning of 2026-10-26/27 (docs/research/quality_calibration.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import numpy as np
from PIL import Image, ImageFilter

from vigil.config import CameraKind

OVERLAY_TOP = 0.05     # share of the frame height taken by the printed timestamp
OVERLAY_BOTTOM = 0.08  # share taken by the logo and the PTZ readout
_MEASURE_SIDE = 512
_EDGE_STEP = 8.0
_GLOW_SIDE = 256
_FINGERPRINT_SIDE = 128

Decision = Literal["pass", "uncertain", "reject"]


@dataclass(frozen=True)
class ImageStats:
    brightness: float     # mean luminance, 0-255
    contrast: float       # standard deviation of luminance
    edge_density: float   # share of pixels on an edge
    glow_fraction: float  # share of the scene in patches that look incandescent


@dataclass(frozen=True)
class Thresholds:
    stale_after: timedelta = timedelta(minutes=30)
    frozen_change: float = 0.15  # re-encoding one image changes it by 0.005-0.16; real consecutive frames by 0.24+
    night_sun_deg: float = -6.0  # civil twilight
    night_glow: float = 0.0005   # episode 55 nights: 0.09 % and up; quiet nights: 0 %, or a vent glow up to 0.07 % (K2)
    fog_edges: float = 0.005     # dense fog: 0.000-0.004
    clear_edges: float = 0.015   # in between, the frame is hazy and Muse Spark decides


@dataclass(frozen=True)
class LocalVerdict:
    decision: Decision
    reasons: tuple[str, ...] = ()  # stale, frozen, night, low_visibility


def measure(image: Image.Image) -> ImageStats:
    scene = _scene(image.convert("RGB"))
    small = scene.copy()
    small.thumbnail((_MEASURE_SIDE, _MEASURE_SIDE))
    luminance = np.asarray(small.convert("L").filter(ImageFilter.GaussianBlur(1)), dtype=np.float32)
    rows, cols = np.gradient(luminance)
    blocks = np.asarray(_reduce(scene, _GLOW_SIDE), dtype=np.int16)
    red, green, blue = blocks[..., 0], blocks[..., 1], blocks[..., 2]
    hot = ((red >= 150) & (red - blue >= 60) & (red >= green)) | (blocks.min(axis=-1) >= 200)
    patches = hot[:-1, :-1] & hot[1:, :-1] & hot[:-1, 1:] & hot[1:, 1:]  # 2x2 squares of hot blocks
    return ImageStats(
        brightness=float(luminance.mean()),
        contrast=float(luminance.std()),
        edge_density=float((np.hypot(rows, cols) > _EDGE_STEP).mean()),
        glow_fraction=float(patches.mean()),
    )


def fingerprint(image: Image.Image) -> np.ndarray:
    """Block-averaged luminance of the scene, to compare a frame with the camera's previous one."""
    return np.asarray(_reduce(_scene(image.convert("RGB")).convert("L"), _FINGERPRINT_SIDE), dtype=np.float32)


def difference(previous: np.ndarray, current: np.ndarray) -> float | None:
    """Mean absolute luminance difference of two fingerprints; None if the frame size changed."""
    if previous.shape != current.shape:
        return None
    return float(np.abs(current - previous).mean())


def check_local(
    stats: ImageStats,
    *,
    kind: CameraKind,
    captured_at: datetime,
    sun_elevation: float | None,
    change: float | None,
    now: datetime | None = None,
    thresholds: Thresholds = Thresholds(),
) -> LocalVerdict:
    """Decide from the frame's own pixels and times whether it can be used.

    `change` is the difference from the camera's previous frame (None for its
    first frame). Staleness counts only when `now` is given, i.e. live.
    Thermal cameras see through fog and darkness, so only staleness and
    frozen images apply to them. Without a sun elevation (the volcano has no
    position) every frame counts as daytime.
    """
    t = thresholds
    reasons = []
    hazy = False
    if now is not None and now - captured_at > t.stale_after:
        reasons.append("stale")
    if change is not None and change < t.frozen_change:
        reasons.append("frozen")
    if kind == "visible":
        night = sun_elevation is not None and sun_elevation < t.night_sun_deg
        if night and stats.glow_fraction < t.night_glow:
            reasons.append("night")
        elif stats.edge_density < t.fog_edges:
            reasons.append("low_visibility")
        elif not night and stats.edge_density < t.clear_edges:
            hazy = True
    if reasons:
        return LocalVerdict("reject", tuple(reasons))
    if hazy:
        return LocalVerdict("uncertain", ("low_visibility",))
    return LocalVerdict("pass")


def _scene(image: Image.Image) -> Image.Image:
    width, height = image.size
    return image.crop((0, round(height * OVERLAY_TOP), width, round(height * (1 - OVERLAY_BOTTOM))))


def _reduce(image: Image.Image, side: int) -> Image.Image:
    """Block-average the image down to a long side of at most `side` pixels."""
    return image.reduce(max(1, math.ceil(max(image.size) / side)))
