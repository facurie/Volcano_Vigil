"""Winds aloft over a volcano from Open-Meteo, and how a plume's drift compares with them.

Open-Meteo serves the best-matching weather model's wind speed, direction and
geopotential height at pressure levels (850 to 300 hPa: about 1.5 to 9.7 km
over Kilauea). Between levels the wind is interpolated as east and north
components, never as angles.

A plume drifts with the wind of the layer it fills, so its drift is compared
with the mean wind between the vent and its top (`WindProfile.layer_mean`),
not with the wind at the top alone: on episode 55 the layer mean blows to the
side KPcam saw the plume on in 74 of 75 frames, the wind at the top in 59.
One camera measures only the side of its line of sight the plume sits on
(vigia.metrics drift_bearing), so `compare_drift` gives the angle between that
side and where the wind blows: under 90 degrees the wind pushes the plume to
the side it was seen on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np

CALM_MS = 1.0  # under this mean speed the wind's direction says nothing about the drift


@dataclass(frozen=True)
class Wind:
    speed_ms: float
    from_deg: float  # where the wind blows from, clockwise from north (the meteorological convention)

    @property
    def toward_deg(self) -> float:
        return (self.from_deg + 180.0) % 360.0


@dataclass(frozen=True)
class Level:
    pressure_hpa: int
    altitude_m: float  # geopotential height above sea level
    wind: Wind


@dataclass(frozen=True)
class WindProfile:
    volcano: str
    valid_at: datetime                # the model hour, UTC
    levels: tuple[Level, ...]         # lowest first
    source: str                       # forecast | historical_forecast
    grid: tuple[float, float, float]  # lat, lon and elevation (m) of the model cell Open-Meteo used

    def __post_init__(self) -> None:
        altitudes = [level.altitude_m for level in self.levels]
        if not altitudes or any(b <= a for a, b in zip(altitudes, altitudes[1:])):
            raise ValueError(f"a wind profile needs levels listed lowest first, got altitudes {altitudes}")

    def at(self, altitude_m: float) -> Wind:
        """The wind at an altitude; below the lowest level or above the highest, that level's wind."""
        z, u, v = self._components()
        return _wind(float(np.interp(altitude_m, z, u)), float(np.interp(altitude_m, z, v)))

    def layer_mean(self, bottom_m: float, top_m: float) -> Wind:
        """The height average of the wind between two altitudes; with no thickness, the wind at the bottom."""
        if top_m <= bottom_m:
            return self.at(bottom_m)
        z, u, v = self._components()
        heights = np.concatenate(([bottom_m], z[(z > bottom_m) & (z < top_m)], [top_m]))
        thickness = np.diff(heights)

        def mean(component: np.ndarray) -> float:
            values = np.interp(heights, z, component)
            return float(np.sum((values[1:] + values[:-1]) / 2 * thickness) / (top_m - bottom_m))

        return _wind(mean(u), mean(v))

    def _components(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        z = np.array([level.altitude_m for level in self.levels])
        speed = np.array([level.wind.speed_ms for level in self.levels])
        rad = np.radians([level.wind.from_deg for level in self.levels])
        return z, -speed * np.sin(rad), -speed * np.cos(rad)


def _wind(east: float, north: float) -> Wind:
    """The wind blowing towards `east` and `north` metres per second."""
    return Wind(math.hypot(east, north), math.degrees(math.atan2(-east, -north)) % 360.0)


@dataclass(frozen=True)
class DriftCheck:
    side_deg: float          # bearing of the side of the line of sight the plume was measured on
    toward_deg: float        # where the wind blows
    speed_ms: float
    angle_deg: float         # between the two, 0 to 180
    consistent: bool | None  # under 90 degrees: the wind pushes the plume to that side; None in a calm


def compare_drift(side_deg: float, wind: Wind) -> DriftCheck:
    """Compare a measured drift side (vigia.metrics drift_bearing) with a wind."""
    angle = abs((wind.toward_deg - side_deg + 180.0) % 360.0 - 180.0)
    consistent = None if wind.speed_ms < CALM_MS else angle < 90.0
    return DriftCheck(side_deg % 360.0, wind.toward_deg, wind.speed_ms, angle, consistent)
