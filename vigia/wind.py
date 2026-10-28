"""Winds aloft over a volcano from Open-Meteo, and how a plume's drift compares with them.

Open-Meteo serves the best-matching weather model's wind speed, direction and
geopotential height at pressure levels (850 to 300 hPa: about 1.5 to 9.7 km
over Kilauea) for any hour: hours more than two days old from the Historical
Forecast API, recent and coming ones from the Forecast API. A UTC day is
fetched at once and cached per volcano and hour in `wind_profiles`; a cached
forecast hour is fetched again after an hour. Between levels the wind is
interpolated as east and north components, never as angles.

A plume drifts with the wind of the layer it fills, so its drift is compared
with the mean wind between the vent and its top (`WindProfile.layer_mean`),
not with the wind at the top alone: on episode 55 the layer mean blows to the
side KPcam saw the plume on in 74 of 75 frames, the wind at the top in 58.
One camera measures only the side of its line of sight the plume sits on
(vigia.metrics drift_bearing), so `compare_drift` gives the angle between that
side and where the wind blows: under 90 degrees the wind pushes the plume to
the side it was seen on.

    vigia-wind --volcano kilauea --at 2026-10-17T15:00Z --altitude 6951 --bottom 1080 --side 224.4
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np

from vigia import db
from vigia.config import Sources, Volcano, load_sources
from vigia.settings import Settings
from vigia.timeutil import parse_utc, to_iso, utcnow

CALM_MS = 1.0  # under this mean speed the wind's direction says nothing about the drift
LEVELS_HPA = (850, 700, 600, 500, 400, 300)
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HISTORICAL_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
HISTORICAL_AFTER = timedelta(days=2)   # hours older than this come from the Historical Forecast API
FORECAST_MAX_AGE = timedelta(hours=1)  # a cached forecast hour is fetched again after this
SOURCE_NAMES = {"forecast": "Open-Meteo Forecast API", "historical_forecast": "Open-Meteo Historical Forecast API"}
SOURCE_URLS = {"forecast": "https://open-meteo.com/en/docs",
               "historical_forecast": "https://open-meteo.com/en/docs/historical-forecast-api"}
_VARIABLES = ("geopotential_height", "wind_speed", "wind_direction")


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


class WindUnavailable(RuntimeError):
    """Open-Meteo has no usable profile for that volcano and hour."""


class WindService:
    """Wind profiles over each volcano, fetched a UTC day at a time and cached in `wind_profiles`."""

    def __init__(self, conn: sqlite3.Connection, http: httpx.Client, sources: Sources,
                 now: Callable[[], datetime] = utcnow):
        self._conn = conn
        self._http = http
        self._sources = sources
        self._now = now

    def profile(self, volcano_id: str, when: datetime) -> WindProfile:
        """The profile of the model hour nearest to `when`."""
        volcano = self._sources.volcanoes.get(volcano_id)
        if volcano is None:
            raise WindUnavailable(f"unknown volcano {volcano_id!r}")
        if volcano.lat is None or volcano.lon is None:
            raise WindUnavailable(f"volcano {volcano_id} has no position in the sources file")
        hour = (when.astimezone(timezone.utc) + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
        cached = self._cached(volcano_id, hour, fresh_only=True)
        if cached is not None:
            return cached
        try:
            self._fetch_day(volcano_id, volcano, hour)
        except WindUnavailable:
            stale = self._cached(volcano_id, hour, fresh_only=False)  # an older forecast beats no wind at all
            if stale is None:
                raise
            return stale
        fetched = self._cached(volcano_id, hour, fresh_only=False)
        if fetched is None:
            raise WindUnavailable(f"Open-Meteo has no wind profile for {volcano_id} at {to_iso(hour)}")
        return fetched

    def _cached(self, volcano_id: str, hour: datetime, *, fresh_only: bool) -> WindProfile | None:
        row = self._conn.execute("SELECT * FROM wind_profiles WHERE volcano = ? AND valid_at = ?",
                                 (volcano_id, to_iso(hour))).fetchone()
        if row is None:
            return None
        if (fresh_only and row["source"] == "forecast"
                and self._now() - parse_utc(row["fetched_at"]) > FORECAST_MAX_AGE):
            return None
        levels = tuple(Level(int(p), z, Wind(s, d)) for p, z, s, d in json.loads(row["levels"]))
        return WindProfile(volcano_id, hour, levels, row["source"],
                           (row["grid_lat"], row["grid_lon"], row["grid_elev_m"]))

    def _fetch_day(self, volcano_id: str, volcano: Volcano, hour: datetime) -> None:
        source = "historical_forecast" if hour < self._now() - HISTORICAL_AFTER else "forecast"
        names = [f"{name}_{p}hPa" for p in LEVELS_HPA for name in _VARIABLES]
        day = hour.date().isoformat()
        try:
            response = self._http.get(HISTORICAL_URL if source == "historical_forecast" else FORECAST_URL, params={
                "latitude": volcano.lat, "longitude": volcano.lon, "hourly": ",".join(names),
                "wind_speed_unit": "ms", "timezone": "GMT", "start_date": day, "end_date": day})
            response.raise_for_status()
            body = response.json()
            times = body["hourly"]["time"]
            columns = {name: body["hourly"][name] for name in names}
            if any(len(column) != len(times) for column in columns.values()):
                raise ValueError("hourly columns of different lengths")
            grid = (float(body["latitude"]), float(body["longitude"]), float(body["elevation"]))
            fetched_at = to_iso(self._now())
            rows = []
            for i, stamp in enumerate(times):
                levels = []
                for p in LEVELS_HPA:
                    z, speed, direction = (columns[f"{name}_{p}hPa"][i] for name in _VARIABLES)
                    if None not in (z, speed, direction):
                        levels.append([p, float(z), float(speed), float(direction)])
                if len(levels) < 2:
                    continue
                levels.sort(key=lambda level: level[1])
                valid_at = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
                rows.append((volcano_id, to_iso(valid_at), source, fetched_at, *grid, json.dumps(levels)))
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise WindUnavailable(f"Open-Meteo failed for {volcano_id} on {day}: {type(exc).__name__}: {exc}"[:300]) from exc
        with self._conn:
            self._conn.executemany(
                """INSERT OR REPLACE INTO wind_profiles (volcano, valid_at, source, fetched_at, grid_lat, grid_lon,
                                                         grid_elev_m, levels)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Show Open-Meteo's winds aloft over a volcano and compare a "
                                                 "measured drift side with the mean wind of the layer under a plume top.")
    parser.add_argument("--volcano", required=True, help="volcano id from the sources file, e.g. kilauea")
    parser.add_argument("--at", type=parse_utc, help="time, e.g. 2026-10-17T15:00Z (default: now)")
    parser.add_argument("--altitude", type=float, help="plume top, metres above sea level")
    parser.add_argument("--bottom", type=float, help="the layer's bottom in metres, e.g. the vent (default: the lowest level)")
    parser.add_argument("--side", type=float, help="the measured drift side (drift_bearing), degrees; needs --altitude")
    args = parser.parse_args(argv)
    if args.side is not None and args.altitude is None:
        parser.error("--side needs --altitude")

    settings = Settings.from_env()
    sources = load_sources(settings.sources_path)
    if args.volcano not in sources.volcanoes:
        parser.error(f"unknown volcano {args.volcano!r} in {settings.sources_path}")
    with closing(db.connect(settings.db_path)) as conn, \
            httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=30) as http:
        try:
            profile = WindService(conn, http, sources).profile(args.volcano, args.at or utcnow())
        except WindUnavailable as exc:
            parser.exit(1, f"{exc}\n")
    lat, lon, elev = profile.grid
    print(f"{args.volcano} {to_iso(profile.valid_at)}: {SOURCE_NAMES[profile.source]}, "
          f"model cell {lat:.3f}, {lon:.3f} at {elev:.0f} m")
    for level in profile.levels:
        print(f"  {level.pressure_hpa} hPa {level.altitude_m:6.0f} m  from {level.wind.from_deg:3.0f} deg "
              f"{level.wind.speed_ms:5.1f} m/s")
    if args.altitude is None:
        return
    bottom = args.bottom if args.bottom is not None else profile.levels[0].altitude_m
    at, mean = profile.at(args.altitude), profile.layer_mean(bottom, args.altitude)
    print(f"at {args.altitude:.0f} m: from {at.from_deg:.0f} deg at {at.speed_ms:.1f} m/s")
    print(f"mean {bottom:.0f}-{args.altitude:.0f} m: from {mean.from_deg:.0f} deg (towards {mean.toward_deg:.0f} deg) "
          f"at {mean.speed_ms:.1f} m/s")
    if args.side is not None:
        check = compare_drift(args.side, mean)
        verdict = {True: "consistent", False: "not consistent", None: "too calm to tell"}[check.consistent]
        print(f"drift side {check.side_deg:.0f} deg: {check.angle_deg:.0f} deg from the mean wind: {verdict}")


if __name__ == "__main__":
    main()
