"""Moon references for a camera's calibration: where the Moon was, and where the frame shows it.

For each frame, JPL Horizons gives the Moon's airless topocentric azimuth and
elevation seen from the camera (config/calibration.yaml) at the capture time,
and refraction for the camera's air pressure is added (Saemundsson's formula,
scaled to the standard pressure at its elevation and 12 C). The Moon's centre
in the frame is the centre of a circle fitted to the outer edge of its lit
part, near the pixel given. The script prints `celestial` entries for the
preset; check them with scripts/check_calibration.py before committing.

    python scripts/moon_references.py --camera kilauea-kp \\
        --frame "data/frames/kilauea-kp/2026-10-16/20261016T224509Z_<hash>.jpg@2026-10-16T22:45:09Z@695,529"
"""

from __future__ import annotations

import argparse
import math
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
from PIL import Image, ImageFilter

from vigia.calibration import load_calibration
from vigia.settings import Settings
from vigia.timeutil import parse_utc

HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--frame", action="append", required=True,
                        help="PATH@CAPTURE_TIME@X,Y: a frame, its UTC capture time and the Moon's pixel within 40 px")
    args = parser.parse_args(argv)

    position = load_calibration(Settings.from_env().calibration_path).cameras[args.camera].position
    with httpx.Client(timeout=60) as http:
        for spec in args.frame:
            path, when, near = spec.split("@")
            captured_at = parse_utc(when)
            azimuth, airless = moon(http, position.lat, position.lon, position.elev_m, captured_at)
            x, y, radius, misfit = limb_centre(Path(path), tuple(float(v) for v in near.split(",")))
            print(f'          - {{name: "Moon {captured_at:%Y%m%dT%H%MZ}", pixel: [{x:.1f}, {y:.1f}], '
                  f"az_deg: {azimuth:.4f}, el_deg: {airless + refraction(airless, position.elev_m):.4f}}}"
                  f"  # limb radius {radius:.1f} px, misfit {misfit:.1f} px")


def moon(http: httpx.Client, lat: float, lon: float, elev_m: float, when: datetime) -> tuple[float, float]:
    """The Moon's airless azimuth and elevation in degrees seen from the site, interpolated to `when`."""
    start = when.replace(second=0, microsecond=0)
    params = {"format": "text", "COMMAND": "'301'", "OBJ_DATA": "'NO'", "MAKE_EPHEM": "'YES'",
              "EPHEM_TYPE": "'OBSERVER'", "CENTER": "'coord@399'", "COORD_TYPE": "'GEODETIC'",
              "SITE_COORD": f"'{lon},{lat},{elev_m / 1000}'", "START_TIME": f"'{start:%Y-%m-%d %H:%M}'",
              "STOP_TIME": f"'{start + timedelta(minutes=1):%Y-%m-%d %H:%M}'", "STEP_SIZE": "'1 m'",
              "QUANTITIES": "'4'", "ANG_FORMAT": "'DEG'", "APPARENT": "'AIRLESS'", "EXTRA_PREC": "'YES'"}
    text = http.get(HORIZONS, params=params).raise_for_status().text
    rows = [line.split() for line in text[text.index("$$SOE") + 5:text.index("$$EOE")].strip().splitlines()]
    (az0, el0), (az1, el1) = [(float(row[-2]), float(row[-1])) for row in rows[:2]]
    share = (when - start).total_seconds() / 60
    return az0 + share * (az1 - az0), el0 + share * (el1 - el0)


def refraction(elevation: float, site_elev_m: float, celsius: float = 12.0) -> float:
    """Degrees by which the air lifts a body at this airless elevation, seen from site_elev_m."""
    pressure = 1013.25 * (1 - 2.25577e-5 * site_elev_m) ** 5.25588
    minutes = 1.02 / math.tan(math.radians(elevation + 10.3 / (elevation + 5.11)))
    return minutes / 60 * pressure / 1010 * 283 / (273 + celsius)


def limb_centre(path: Path, near: tuple[float, float]) -> tuple[float, float, float, float]:
    """Centre, radius and misfit (pixels) of a circle fitted to the Moon's lit limb near `near`.

    The Moon is the brightest spot of the red channel above its local
    background within 40 px of `near` (the sky around it is blue). Its lit
    pixels are those of an 80 px window around that spot brighter than 35 %
    of the peak; the limb is their outer edge, seen from their centroid. The
    circle's radius is fitted too: wide-lens distortion shrinks the Moon
    differently across the frame.
    """
    with Image.open(path) as image:
        rgb = image.convert("RGB")
    left, top = round(near[0]) - 60, round(near[1]) - 60
    search = rgb.crop((left, top, left + 120, top + 120))
    excess = (np.asarray(search, dtype=float)[..., 0]
              - np.asarray(search.filter(ImageFilter.BoxBlur(15)), dtype=float)[..., 0])
    row, col = np.unravel_index(np.argmax(excess[20:100, 20:100]), (80, 80))
    left, top = left + 20 + col - 40, top + 20 + row - 40
    red = np.asarray(rgb.crop((left, top, left + 80, top + 80)), dtype=float)[..., 0]
    lit = red - np.median(red)
    rows, cols = np.nonzero(lit > 0.35 * lit.max())
    centroid = np.array([cols.mean(), rows.mean()])
    angle = np.round(np.arctan2(rows - centroid[1], cols - centroid[0]) / (np.pi / 36))
    reach = np.hypot(cols - centroid[0], rows - centroid[1])
    edge = np.array([(cols[i], rows[i]) for i in (np.flatnonzero(angle == a)[np.argmax(reach[angle == a])]
                                                  for a in np.unique(angle) if (angle == a).sum() >= 2)], float)
    edge = edge[np.hypot(*(edge - centroid).T) >= np.median(np.hypot(*(edge - centroid).T))]  # not the terminator
    x, y = edge.T
    (d, e, f), *_ = np.linalg.lstsq(np.column_stack([x, y, np.ones_like(x)]), -(x ** 2 + y ** 2), rcond=None)
    cx, cy = -d / 2, -e / 2
    radius = math.sqrt(cx ** 2 + cy ** 2 - f)
    misfit = float(np.sqrt(((np.hypot(x - cx, y - cy) - radius) ** 2).mean()))
    return left + cx, top + cy, radius, misfit


if __name__ == "__main__":
    main()
