"""Measurements of tracked objects: top height and altitude, area and plume drift, each with sigma.

Every stored detection (vigil.tracking) on a frame its camera's calibration
covers is placed on the vertical plane through the vent, square to the line
of sight (vigil.geometry.on_vent_plane):
- top_height: metres above the vent, and top_altitude: metres above sea
  level, of the mask's highest pixel. A mask that reaches the frame's top
  edge is cut off, so it gets neither.
- area: the mask's pixels times the area one pixel covers on that plane
  (m2), summed over up to 32 bands of rows because the pixel's footprint
  grows with elevation and off-axis angle.
- drift_offset and drift_bearing, plumes only: how far the mask's centroid
  sits across the line of sight from the vent (metres, positive to the
  right) and the bearing of that side. One camera sees only the part of the
  drift across its line of sight.

Each value is sample 0 of the calibration's Monte Carlo (vigil.calibration)
and its sigma the spread of the other samples, which also move the top pixel
by the mask edge's uncertainty and lean the object along the line of sight.
Results go to the `measurements` table.

    vigil-measure --camera kilauea-kp --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from vigil import db, masks
from vigil.calibration import Calibration, Geometry, load_calibration, sample_geometry
from vigil.geometry import on_vent_plane
from vigil.settings import Settings
from vigil.timeutil import parse_utc, to_iso, utcnow

SAMPLES = 1000
MASK_EDGE_PX = 3.0  # uncertainty of a SAM mask's edge, in frame pixels
LEAN_SIGMA_DEG = {"plume": 10.0, "fountain": 5.0, "incandescence": 5.0}  # tilt along the line of sight
AREA_BANDS = 32     # the most bands of rows an area is summed over
CUT_OFF_ROWS = 2   # a mask whose top lies in the frame's first rows runs off the frame


@dataclass(frozen=True)
class Measurement:
    metric: str
    value: float
    sigma: float  # one standard deviation
    unit: str


def measure_mask(geometry: Geometry, mask: np.ndarray, left: int, top: int, target: str,
                 rng: np.random.Generator) -> list[Measurement]:
    """The metrics of one detection; `mask` is its box-sized mask, whose top-left pixel is (left, top)."""
    rows, cols = np.nonzero(mask)
    if not rows.size:
        return []
    samples = len(geometry.view.focal)
    k = geometry.refraction[:, None]
    results = []
    if top + rows.min() >= CUT_OFF_ROWS:
        pixel = np.zeros((samples, 1, 2))
        pixel[..., 0] = left + cols[rows == rows.min()].mean()
        pixel[..., 1] = top + rows.min() + _noise(rng, MASK_EDGE_PX, samples)[:, None]
        lean = np.tan(np.radians(_noise(rng, LEAN_SIGMA_DEG[target], samples)))[:, None]
        _, _, rise = on_vent_plane(geometry.view, pixel, geometry.vent, k=k)
        height = geometry.camera_elev[:, None] + rise - geometry.vent_elev[:, None]
        _, _, rise = on_vent_plane(geometry.view, pixel, geometry.vent, along=height * lean, k=k)
        altitude = geometry.camera_elev + rise[:, 0]
        results += [_summary("top_height", altitude - geometry.vent_elev, "m"),
                    _summary("top_altitude", altitude, "m")]
    results.append(_summary("area", _plane_area(geometry, left + cols, top + rows, k), "m2"))
    if target == "plume":
        centroid = np.zeros((samples, 1, 2))
        centroid[..., 0], centroid[..., 1] = left + cols.mean(), top + rows.mean()
        _, across, _ = on_vent_plane(geometry.view, centroid, geometry.vent, k=k)
        vent_azimuth = np.degrees(np.arctan2(geometry.vent[:, 0], geometry.vent[:, 1]))
        bearing = (vent_azimuth + np.where(across[:, 0] >= 0, 90.0, -90.0)) % 360
        turn = (bearing - bearing[0] + 180) % 360 - 180
        results += [_summary("drift_offset", across[:, 0], "m"),
                    Measurement("drift_bearing", float(bearing[0]), float(turn[1:].std()), "deg")]
    return results


def _plane_area(geometry: Geometry, cols: np.ndarray, rows: np.ndarray, k: np.ndarray) -> np.ndarray:
    """Area on the vent plane of the pixels at these columns and rows, per sample (m2).

    What a pixel covers there changes with elevation and angle off the axis,
    so the mask's rows are cut into bands: each band's pixel count times the
    area of one pixel at the band's mean column and row, from the plane
    points half a pixel to either side of it.
    """
    first = rows.min()
    bands = min(AREA_BANDS, rows.max() - first + 1)
    band = (rows - first) * bands // (rows.max() - first + 1)
    count = np.bincount(band, minlength=bands)
    used = count > 0
    column = np.bincount(band, weights=cols, minlength=bands)[used] / count[used]
    row = np.bincount(band, weights=rows, minlength=bands)[used] / count[used]
    samples = len(geometry.view.focal)
    pixel = np.zeros((samples, 4 * used.sum(), 2))
    pixel[..., 0] = np.tile(np.concatenate([column + 0.5, column - 0.5, column, column]), (samples, 1))
    pixel[..., 1] = np.tile(np.concatenate([row, row, row + 0.5, row - 0.5]), (samples, 1))
    _, across, rise = on_vent_plane(geometry.view, pixel, geometry.vent, k=k)
    n = used.sum()
    local = np.abs(across[:, :n] - across[:, n:2 * n]) * np.abs(rise[:, 2 * n:3 * n] - rise[:, 3 * n:])
    return (count[used] * local).sum(axis=1)


def _noise(rng: np.random.Generator, sigma: float, samples: int) -> np.ndarray:
    draw = rng.normal(0.0, sigma, samples)
    draw[0] = 0.0  # sample 0 stays nominal
    return draw


def _summary(metric: str, samples: np.ndarray, unit: str) -> Measurement:
    return Measurement(metric, float(samples[0]), float(samples[1:].std()), unit)


@dataclass
class MeasureReport:
    camera_id: str
    measured: int = 0      # detections measured
    values: int = 0        # measurements stored
    skipped: int = 0       # detections measured before
    uncalibrated: int = 0  # detections on frames no preset covers
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        line = (f"{self.camera_id}: {self.measured} detections measured ({self.values} values), "
                f"{self.skipped} measured before, {self.uncalibrated} on frames without a calibration")
        return "\n".join([line] + [f"  failed: {error}" for error in self.errors])


def measure_window(conn: sqlite3.Connection, calibration: Calibration, camera_id: str, start: datetime,
                   end: datetime, *, samples: int = SAMPLES, seed: int = 0, redo: bool = False,
                   now: Callable[[], datetime] = utcnow) -> MeasureReport:
    """Measure the detections of the camera's tracks on frames captured in [start, end].

    Detections measured before are skipped unless `redo`. A preset whose
    references cannot fix the view is reported once and its detections left
    unmeasured.
    """
    report = MeasureReport(camera_id)
    rows = conn.execute(
        """SELECT d.*, f.captured_at, f.width, f.height, r.target,
                  EXISTS (SELECT 1 FROM measurements m WHERE m.detection_id = d.id) AS measured
           FROM detections d JOIN frames f ON f.id = d.frame_id
           JOIN tracks t ON t.id = d.track_id JOIN tracking_runs r ON r.id = t.run_id
           WHERE r.camera_id = ? AND f.captured_at BETWEEN ? AND ?
           ORDER BY f.captured_at, d.id""",
        (camera_id, to_iso(start), to_iso(end)),
    ).fetchall()
    geometries: dict[str, Geometry | None] = {}
    for row in rows:
        preset = calibration.preset_for(camera_id, parse_utc(row["captured_at"]))
        if preset is None:
            report.uncalibrated += 1
            continue
        if row["measured"] and not redo:
            report.skipped += 1
            continue
        if (row["width"], row["height"]) != tuple(preset.image_size):
            report.errors.append(f"detection {row['id']}: a {row['width']}x{row['height']} frame, but preset "
                                 f"{preset.name} is {preset.image_size[0]}x{preset.image_size[1]}")
            continue
        if preset.name not in geometries:
            try:
                geometries[preset.name] = sample_geometry(calibration, camera_id, preset, samples, seed)
            except ValueError as exc:
                geometries[preset.name] = None
                report.errors.append(f"preset {preset.name}: {exc}")
        geometry = geometries[preset.name]
        if geometry is None:
            continue
        values = measure_mask(geometry, masks.decode(json.loads(row["mask_rle"])), row["box_left"],
                              row["box_top"], row["target"], np.random.default_rng([seed, row["id"]]))
        computed_at = to_iso(now())
        with conn:
            conn.execute("DELETE FROM measurements WHERE detection_id = ?", (row["id"],))
            conn.executemany(
                """INSERT INTO measurements (detection_id, frame_id, camera_id, captured_at, target, metric,
                                             value, sigma, unit, preset, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(row["id"], row["frame_id"], camera_id, row["captured_at"], row["target"], v.metric, v.value,
                  v.sigma, v.unit, preset.name, computed_at) for v in values],
            )
        report.measured += 1
        report.values += len(values)
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Measure the heights, areas and drift of a camera's tracked "
                                                 "objects, with Monte Carlo sigmas.")
    parser.add_argument("--camera", required=True, help="camera id from the calibration file")
    parser.add_argument("--start", type=parse_utc, required=True, help="first capture time, e.g. 2026-10-17T13:00Z")
    parser.add_argument("--end", type=parse_utc, required=True, help="last capture time, e.g. 2026-10-17T19:30Z")
    parser.add_argument("--samples", type=int, default=SAMPLES, help=f"Monte Carlo samples (default {SAMPLES})")
    parser.add_argument("--redo", action="store_true", help="measure detections measured before again")
    args = parser.parse_args(argv)
    if args.start >= args.end:
        parser.error("--start must be before --end")
    if args.samples < 2:
        parser.error("--samples must be at least 2")

    settings = Settings.from_env()
    calibration = load_calibration(settings.calibration_path)
    if args.camera not in calibration.cameras:
        parser.error(f"camera {args.camera!r} is not calibrated in {settings.calibration_path}")
    with closing(db.connect(settings.db_path)) as conn:
        report = measure_window(conn, calibration, args.camera, args.start, args.end, samples=args.samples,
                                redo=args.redo)
    print(report.summary())


if __name__ == "__main__":
    main()
