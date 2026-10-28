# Phase 3: Geometry, Metrics and First Validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn SAM masks into heights in metres ± σ: a camera model with lens distortion fitted to independent references (the Moon, published landmarks, the sea horizon), a Monte Carlo over every uncertain input, per-detection metrics stored in SQLite, and the first validation of episode 55 against the official USGS values.

**Architecture:** `vigia/geometry.py` is pure math: positions to lines of sight (curvature and refraction included), a pinhole view with radial distortion, a batched Levenberg–Marquardt solver for the view, and heights on the vertical plane through the vent. `vigia/calibration.py` loads `config/calibration.yaml` (vent, camera positions, presets with references and priors) and draws Monte Carlo samples of the solved view. `vigia/metrics.py` measures each stored detection (top height and altitude, area, plume drift) into a `measurements` table (`vigia-measure` CLI). Three scripts derive Moon references, check a calibration visually, and write `docs/VALIDATION.md`.

**Tech Stack:** Python 3.12, numpy (no scipy: the solver is ~40 lines), Pillow, pydantic, PyYAML, SQLite, httpx (JPL Horizons in one script), pytest.

**Spec:** Phase 3 of [docs/PLAN.md](../../PLAN.md).

---

## Facts this plan relies on (measured 2026-10-28)

**KPcam needs a lens-distortion term, and the Moon measures it.**
- KPcam's sea horizon is never visible: on all 29 mornings from Sep 28 to Oct 26, trade cumulus sit on it. The far landmarks (GNIS cones) do not stand out on its skyline, which it sees from above.
- The Moon crosses KPcam's field every afternoon of Oct 15–20 (azimuth 113–140°, elevation 0–29°; JPL Horizons). On clear AshCam frames it is a small crescent or gibbous disk in a blue sky. The usable frames:

| AshCam capture (UTC) | Moon near pixel |
|---|---|
| 2026-10-16 22:15:09 | 487, 878 |
| 2026-10-16 22:30:09 | 587, 702 |
| 2026-10-16 22:45:09 | 695, 529 |
| 2026-10-16 23:00:09 | 808, 361 |
| 2026-10-16 23:15:09 | 931, 197 |
| 2026-10-19 00:45:08 | 637, 135 |
| 2026-10-20 00:45:09 | 66, 551 |
| 2026-10-20 01:00:09 | 176, 359 |
| 2026-10-20 01:15:09 | 303, 183 |

- A pure pinhole fitted to those nine Moon positions leaves a 24 px RMS misfit. It also puts the vent 117 px above the fountain.
- One radial term fixes both. A point at radius r (in focal lengths) lands at r(1 + k1 r²). The Task 6 script (JPL airless position, refraction for 792 hPa, free-radius limb fit) gives:
  - RMS misfit 1.64 px (worst 4.0 px);
  - azimuth 145.59° ± 0.06, tilt 3.24° ± 0.05, roll −0.65° ± 0.10;
  - focal 3,509 ± 13 px, k1 −0.280 ± 0.006;
  - field of view 62.9° across the middle row.
- Two checks come from the Moon alone, without the vent or any official value:
  - the vent lands about 30 px left of the fountain, well inside the ±120 px that KPcam's ±500 m position allows;
  - the predicted sea horizon (dip 1.35° from 2,034 m) runs exactly along the base of the trade-cumulus band.
- KPcam's framing (tree, skyline) is the same from Sep 28 to Oct 27.

**K2cam stays under-determined with the references at hand.**
- Its framing held through episode 55: frames from 13:00 to 19:28Z register within 4 px. It was re-aimed by Oct 26.
- Four GNIS cones stand on its right-hand skyline: Puʻukoaʻe at about (2992, 1629), and three humps at (3297, 1623), (3393, 1617) and (3478, 1617). All lie on one row, so they barely constrain tilt, roll and focal length.
  - Every assignment of the humps to the Kamakaiʻa, Red Cones, Yellow Cone and Puʻukou points fits within 4–7 px, with focal lengths from 2,300 to 5,600 px.
  - With a level-mount roll prior (0 ± 1°), the two best assignments still differ: f 2,498 or 2,783 px.
  - The peak fountain heights they give differ by 25 %: 279, 254 and 209 m for the three best.
- The USGS 3DEP elevation model (one `exportImage` request, about 27 m per pixel, within 3 m of EPQS) gives K2's skyline profile, −1.67° to −2.02° from azimuth 150° to 225°.
  - Fitted with Puʻukoaʻe, it has two solutions: focal 2,122 px with tilt 12.8°, or 3,479 px with tilt 7.1°. The skyline is too flat to choose.
  - The DEM predates 2018 inside the caldera, so the crater rim cannot serve as a reference.
- The sea horizon above K2's land skyline would separate those solutions: it would lie 32 or 53 px above the land skyline. On Oct 17 it is only a faint band near row 1580. Task 8 looks for a clearer K2 frame with the same framing.
- K2's night frames show no stars, because the overflow glow saturates the sky.

**V1cam is not calibrated in this phase.**
- Its position is known to ±150 m at 407 m from the vent, which is ±37 % on distance.
- It also panned between 05:01 and 05:17 HST (the fountain jumps from x≈800 to x≈1380), on top of the zoom changes at 03:47 and 04:41.
- It still gives the end time.

**KPcam's `glow` masks are not the fountain.**
- At night the glow halo reaches 440–750 m above the vent.
- By day the masks cover only the incandescent core: 145 m at 06:00 HST, 49 m at 08:00.

**Other inputs.**
- Vent: north vent 19.40496 N, 155.29022 W (published), elevation 1,080 ± 5 m (Aug 28, 2026 survey through episode 54; 1,075 m through episode 50).
- KPcam lens elevation: 2,034 ± 15 m. EPQS gives 2,032 m at the estimated spot, plus the mast; HVO says "6,700 ft", which is 2,027–2,057 m.
- K2cam lens elevation: 1,245 ± 5 m (EPQS 1,243 m plus the mast).
- Curvature and refraction lower a point 13,948 m away by d²(1−k)/2R = 13.3 m (k = 0.13).
- The `measurements` metrics run fast: the scratch implementation measured all 123 KPcam detections of episode 55 (1,000 Monte Carlo samples) in 3 s.

## Decisions beyond the roadmap bullets

1. **Radial distortion.** The camera model carries one radial-distortion term, k1. A preset's `distortion` prior pins it (no prior means k1 = 0) or frees it (sigma 1).
2. **Reference kinds.**
   - Landmarks: points with positions.
   - Celestial bodies: directions from JPL Horizons.
   - Sea-horizon pixels: a level line at minus the dip.
   - Priors on field of view, roll and k1.
   - The solver needs at least one landmark or celestial body, plus four constraints.
3. **KPcam is calibrated from the Moon, not from B1/F1-KW.** Those two cameras have published positions, but they are not tracked and they are fisheyes. Official values are only compared with, never fitted. **Freeze rule:** `config/calibration.yaml` is committed before `validate_ep55.py` runs, and a later change needs calibration evidence, never a validation error.
4. **Measurement plane.** A mask's highest pixel is placed on the vertical plane through the vent, square to the line of sight. The `top_height` and `top_altitude` metrics are the highest point of the whole mask, which can be the drifting cloud: the Phase 2 caveat stays documented, and no column window is chosen after seeing results.
5. **Monte Carlo.**
   - 1,000 samples; sample 0 is the nominal value.
   - Inputs: camera and vent position, every picked pixel, refraction k 0.13 ± 0.05, priors, mask edge ±3 px, lean along the line of sight (5° for fountains, 10° for plumes).
   - Calibration samples are shared by all detections of a preset (systematic); edge and lean are drawn per detection.
6. **Storage.** A narrow `measurements` table, one row per detection and metric, with value, sigma, unit and preset. It serves Phase 4's `get_history` and Phase 6's charts.
7. **Validation rows.**
   - Fountain rows use K2cam if Task 8 calibrates it, otherwise "no measurement" with the reason.
   - "Max" rows take our highest frame inside HVO's window.
   - "Mean" rows average our frames within ±5 min; their sigma is the RMS of the frame sigmas, because calibration errors do not average out.

## File structure

| File | Responsibility |
|---|---|
| `vigia/geometry.py` (create) | `local_en`, `sight`, `horizon_dip`, `direction`, `View` (project/ray with k1), `References`, `solve_view`, `on_vent_plane` |
| `vigia/calibration.py` (create) | YAML schema (`Site`, `Landmark`, `VentPixel`, `Celestial`, `HorizonPixel`, `FieldOfView`, `Distortion`, `Roll`, `Preset`, `CameraCalibration`, `Calibration`), `load_calibration`, `Geometry`, `sample_geometry` |
| `config/calibration.yaml` (create) | vent and camera positions, presets (references added in Tasks 7–8) |
| `vigia/settings.py`, `.env.example` (modify) | `calibration_path` / `CALIBRATION_PATH` |
| `vigia/db.py` (modify) | `measurements` table |
| `vigia/metrics.py` (create) | `measure_mask`, `measure_window`, `MeasureReport`, `vigia-measure` CLI |
| `pyproject.toml` (modify) | `vigia-measure` console script |
| `scripts/moon_references.py` (create) | JPL Horizons Moon direction plus limb-fit centre → `celestial` YAML lines |
| `scripts/check_calibration.py` (create) | solved view with sigma, per-reference misfit, overlay image |
| `scripts/validate_ep55.py` (create) | comparison with official values → `docs/VALIDATION.md` |
| `tests/test_geometry.py`, `tests/test_calibration.py`, `tests/test_metrics.py` (create) | tests |
| `docs/research/calibration_ep55.md`, `docs/VALIDATION.md` (create, orchestrator) | evidence and results |

Scripts follow the existing precedent: thin wrappers over tested package code, checked by running them, with no unit tests of their own.

Run every command from the repo root (Git Bash). Commit messages are imperative and sentence case, with **no** `Co-Authored-By` or other trailer. The suite has 190 tests before this phase; every task below gives the count after it.

## Execution

- **Tasks 1–6:** dispatch the `implementer` subagent with the task text, then the `reviewer` subagent with the task text, BASE and HEAD.
- **Tasks 7–10:** orchestrator only. They use public endpoints (AshCam, JPL Horizons, USGS 3DEP) and spend no Meta API money. Task 10 pushes.

---

### Task 1: Positions and the camera model (`vigia/geometry.py`, part 1)

**Files:**
- Create: `vigia/geometry.py`, `tests/test_geometry.py`

- [ ] **Step 1: Write the failing tests** (`tests/test_geometry.py`)

```python
import numpy as np
import pytest

from vigia.geometry import View, direction, horizon_dip, local_en, on_vent_plane, sight

KP = (19.492709, -155.385281)
NORTH_VENT = (19.40496, -155.29022)
SIZE = (3840, 2160)


def view(yaw=180.0, pitch=0.0, roll=0.0, focal=1000.0, cx=1920.0, cy=1080.0):
    return View(np.atleast_1d(np.asarray(yaw, dtype=float)), np.atleast_1d(np.asarray(pitch, dtype=float)),
                np.atleast_1d(np.asarray(roll, dtype=float)), np.atleast_1d(np.asarray(focal, dtype=float)), cx, cy)


def at(azimuth, elevation):
    """One sample's directions (1, P, 3) for lists of azimuths and elevations."""
    return direction(np.asarray(azimuth, dtype=float), np.asarray(elevation, dtype=float))[None]


# --- positions


def test_kpcam_is_13948_m_from_the_north_vent_at_bearing_134_4():
    east, north = local_en(*NORTH_VENT, *KP)

    assert np.hypot(east, north) == pytest.approx(13948, abs=2)
    assert np.degrees(np.arctan2(east, north)) == pytest.approx(134.4, abs=0.05)


def test_curvature_and_refraction_lower_a_point_14_km_away_by_13_m():
    assert sight(13948.0, 0.0, 0.0)[2] == pytest.approx(-13.28, abs=0.01)
    assert sight(13948.0, 0.0, 0.0, k=0.0)[2] == pytest.approx(-15.27, abs=0.01)


def test_the_sea_horizon_from_2034_m_dips_1_35_degrees():
    assert horizon_dip(2034.0) == pytest.approx(1.3504, abs=1e-4)
    assert horizon_dip(2034.0, k=0.0) == pytest.approx(1.4478, abs=1e-4)


# --- projection


def test_the_optical_axis_lands_on_the_principal_point():
    pixels = view(yaw=134.4, pitch=-3.9).project(at([134.4], [-3.9]))

    assert pixels[0, 0] == pytest.approx([1920, 1080])


def test_a_level_point_10_degrees_right_lands_f_tan_10_right_of_centre():
    pixels = view(yaw=180).project(at([190], [0]))

    assert pixels[0, 0] == pytest.approx([1920 + 1000 * np.tan(np.radians(10)), 1080])


def test_a_point_above_the_axis_lands_above_the_centre():
    assert view(pitch=5).project(at([180], [10]))[0, 0, 1] == pytest.approx(1080 - 1000 * np.tan(np.radians(5)))


def test_positive_roll_raises_the_right_side_of_a_level_line():
    left, right = view(roll=2).project(at([170, 190], [0, 0]))[0]

    assert right[1] < 1080 < left[1]


def test_points_behind_the_camera_do_not_project():
    assert np.isnan(view(yaw=0).project(at([180], [0]))).all()


def test_ray_inverts_project():
    camera = view(yaw=146.6, pitch=3.8, roll=0.7, focal=3050)
    pixels = camera.project(at([130, 150, 170], [-4, 10, 21]))

    azimuth, elevation = camera.ray(pixels)

    assert azimuth[0] == pytest.approx([130, 150, 170])
    assert elevation[0] == pytest.approx([-4, 10, 21])


def test_barrel_distortion_pulls_a_point_towards_the_centre_by_k1_r_squared():
    camera = View(np.array([180.0]), np.array([0.0]), np.array([0.0]), np.array([1000.0]), 1920, 1080, k1=-0.2)
    r = np.tan(np.radians(30))

    pixel = camera.project(at([210], [0]))[0, 0]

    assert pixel == pytest.approx([1920 + 1000 * r * (1 - 0.2 * r ** 2), 1080])


def test_ray_undoes_the_distortion_out_to_the_corners():
    camera = View(np.array([145.5]), np.array([3.0]), np.array([-0.1]), np.array([3485.0]), 1920, 1080, k1=-0.27)
    pixels = np.array([[[0.0, 0.0], [3839.0, 2159.0], [66.8, 562.1], [1920.0, 1080.0]]])

    assert camera.project(direction(*camera.ray(pixels))) == pytest.approx(pixels, abs=1e-6)


# --- heights on the vent plane


def vent_1km_north_100m_below():
    return sight(0.0, 1000.0, -100.0)[None]  # (1, 3)


def test_a_point_above_the_vent_rises_to_its_true_height():
    camera = view(yaw=0, focal=1500)
    target = sight(0.0, 1000.0, 100.0)[None, None]  # 200 m above the vent: 100 m above the camera

    reach, across, rise = on_vent_plane(camera, camera.project(target), vent_1km_north_100m_below())

    assert (reach[0, 0], across[0, 0], rise[0, 0]) == pytest.approx((1000, 0, 100), abs=1e-6)


def test_a_point_beside_the_vent_is_measured_in_the_plane_square_to_the_line_of_sight():
    camera = view(yaw=0, focal=1500)
    target = sight(100.0, 1000.0, 50.0)[None, None]

    reach, across, rise = on_vent_plane(camera, camera.project(target), vent_1km_north_100m_below())

    assert (reach[0, 0], across[0, 0], rise[0, 0]) == pytest.approx((np.hypot(100, 1000), 100, 50), abs=1e-6)


def test_a_point_beyond_the_plane_is_measured_where_along_puts_it():
    camera = view(yaw=0, focal=1500)
    target = sight(0.0, 1050.0, 100.0)[None, None]

    reach, _, rise = on_vent_plane(camera, camera.project(target), vent_1km_north_100m_below(), along=50.0)

    assert (reach[0, 0], rise[0, 0]) == pytest.approx((1050, 100), abs=1e-6)


def test_a_pixel_looking_far_from_the_vent_is_refused():
    camera = view(yaw=90, focal=1500)

    with pytest.raises(ValueError, match="80 degrees"):
        on_vent_plane(camera, np.array([[[1920.0, 1080.0]]]), vent_1km_north_100m_below())
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_geometry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigia.geometry'`

- [ ] **Step 3: Create `vigia/geometry.py`** (Task 2 adds the solver to this file)

```python
"""Camera geometry: where a camera points, and how high a pixel is above the vent.

Positions become east-north-up offsets in metres from the camera. Over the
14 km from KPcam to the vent the Earth's surface curves 15 m below a level
line, and refraction bends the line of sight back by 2 m, so a point's
apparent height is lowered by d^2 (1 - k) / 2R: k = 0.13 is the standard
refraction coefficient, d the horizontal distance.

A view is a pinhole camera with radial distortion: the azimuth (yaw) and
elevation (pitch) of the optical axis, the roll about it, the focal length
in pixels, the principal point at the image centre, and k1: a point at
radius r from the centre (in focal lengths) lands at r (1 + k1 r^2). Wide
webcam lenses bend straight lines outward (barrel distortion, k1 < 0).
Pixel coordinates are column and row indices, as read off the image.

`solve_view` fits yaw, pitch, roll, focal length and k1 to references by
least squares:
- landmarks: pixels of points with known positions, or of celestial bodies
  (the Moon) in known directions;
- the sea horizon: pixels on a level line whose dip below horizontal follows
  from the camera's elevation;
- priors: the lens's focal length when a datasheet gives its field of view;
  the roll of a pan-tilt-zoom camera, which a level mount keeps near 0; and
  k1, pinned at 0 unless the references can measure it.

Arrays carry a leading axis of N samples, so the Monte Carlo of
vigia.calibration re-solves every perturbed sample at once.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

EARTH_RADIUS_M = 6_371_008.8
REFRACTION_K = 0.13


def local_en(lat, lon, origin_lat: float, origin_lon: float) -> tuple[np.ndarray, np.ndarray]:
    """East and north offsets in metres of points from an origin; good to about 1 m over 20 km."""
    lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    middle = np.radians((lat + origin_lat) / 2)
    east = np.radians(lon - origin_lon) * EARTH_RADIUS_M * np.cos(middle)
    north = np.radians(lat - origin_lat) * EARTH_RADIUS_M
    return east, north


def sight(east, north, rise, k=REFRACTION_K) -> np.ndarray:
    """Lines of sight (..., 3: east, north, up) to points at these offsets and heights above the camera.

    The up part is the apparent height: the true one lowered by the Earth's
    curvature and raised back by refraction, d^2 (1 - k) / 2R in all.
    """
    east, north = np.asarray(east, dtype=float), np.asarray(north, dtype=float)
    drop = (east ** 2 + north ** 2) * (1 - np.asarray(k, dtype=float)) / (2 * EARTH_RADIUS_M)
    return np.stack(np.broadcast_arrays(east, north, np.asarray(rise, dtype=float) - drop), axis=-1)


def horizon_dip(elev_m, k=REFRACTION_K) -> np.ndarray:
    """Degrees by which the sea horizon lies below level, seen from elev_m metres above the sea."""
    elev_m, k = np.asarray(elev_m, dtype=float), np.asarray(k, dtype=float)
    return np.degrees(np.sqrt(2 * elev_m * (1 - k) / EARTH_RADIUS_M))


def direction(azimuth, elevation) -> np.ndarray:
    """Unit vectors (..., 3: east, north, up) for azimuths and elevations in degrees."""
    azimuth, elevation = np.radians(np.asarray(azimuth, dtype=float)), np.radians(np.asarray(elevation, dtype=float))
    return np.stack(np.broadcast_arrays(np.sin(azimuth) * np.cos(elevation), np.cos(azimuth) * np.cos(elevation),
                                        np.sin(elevation)), axis=-1)


@dataclass(frozen=True)
class View:
    """Where a camera points; yaw, pitch, roll, focal and k1 have shape (N,), one value per sample."""

    yaw: np.ndarray    # azimuth of the optical axis, degrees clockwise from north
    pitch: np.ndarray  # elevation of the optical axis, degrees
    roll: np.ndarray   # degrees; positive raises the right-hand side of a level line in the image
    focal: np.ndarray  # pixels
    cx: float          # principal point, at the image centre
    cy: float
    k1: np.ndarray | float = 0.0  # radial distortion; 0 is a plain pinhole

    def axes(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """The image's right, down and forward directions, each (N, 1, 3) in east-north-up."""
        yaw, pitch, roll = (np.radians(np.asarray(a, dtype=float))[:, None, None]
                            for a in (self.yaw, self.pitch, self.roll))
        forward = np.concatenate([np.sin(yaw) * np.cos(pitch), np.cos(yaw) * np.cos(pitch), np.sin(pitch)], -1)
        level_right = np.concatenate([np.cos(yaw), -np.sin(yaw), np.zeros_like(yaw)], -1)
        level_down = np.concatenate([np.sin(yaw) * np.sin(pitch), np.cos(yaw) * np.sin(pitch), -np.cos(pitch)], -1)
        right = level_right * np.cos(roll) + level_down * np.sin(roll)
        down = level_down * np.cos(roll) - level_right * np.sin(roll)
        return right, down, forward

    def project(self, vectors: np.ndarray) -> np.ndarray:
        """Pixels (N, P, 2) where directions (N, P, 3) appear; NaN for those behind the camera."""
        right, down, forward = self.axes()
        x, y, z = ((vectors * axis).sum(-1) for axis in (right, down, forward))
        z = np.where(z > 0, z, np.nan)
        x, y = x / z, y / z
        stretch = self._per_point(self.focal, x.shape) * (1 + self._per_point(self.k1, x.shape) * (x ** 2 + y ** 2))
        return np.stack([self.cx + stretch * x, self.cy + stretch * y], -1)

    def ray(self, pixels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Azimuth and elevation in degrees, each (N, P), of the lines of sight through pixels (N, P, 2)."""
        right, down, forward = self.axes()
        focal, k1 = self._per_point(self.focal, pixels.shape[:2]), self._per_point(self.k1, pixels.shape[:2])
        bent_x, bent_y = (pixels[..., 0] - self.cx) / focal, (pixels[..., 1] - self.cy) / focal
        x, y = bent_x, bent_y
        for _ in range(20):  # undo the distortion: converges fast while |k1| r^2 stays well under 1
            shrink = 1 + k1 * (x ** 2 + y ** 2)
            x, y = bent_x / shrink, bent_y / shrink
        w = forward + x[..., None] * right + y[..., None] * down
        azimuth = np.degrees(np.arctan2(w[..., 0], w[..., 1])) % 360
        elevation = np.degrees(np.arctan2(w[..., 2], np.hypot(w[..., 0], w[..., 1])))
        return azimuth, elevation

    @staticmethod
    def _per_point(value, shape: tuple[int, ...]) -> np.ndarray:
        """A per-sample value (N,) or a scalar, broadcast to (N, P)."""
        value = np.asarray(value, dtype=float)
        return np.broadcast_to(value[:, None] if value.ndim else value, shape)


def on_vent_plane(view: View, pixels: np.ndarray, vent: np.ndarray, along=0.0,
                  k=REFRACTION_K) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Where the lines of sight through pixels (N, P, 2) meet the vertical plane through the vent.

    The plane stands square to the line of sight to the vent, `vent` (N, 3),
    unless `along` (metres, broadcast to (N, P)) moves the point that far
    beyond it: a leaning plume. Returns three (N, P) arrays: the horizontal
    distance from the camera, the offset across the line of sight (positive
    to the right) and the true height above the camera, with curvature and
    refraction added back. Raises ValueError for a pixel more than 80 degrees
    from the vent's azimuth.
    """
    azimuth, elevation = view.ray(pixels)
    vent_azimuth = np.degrees(np.arctan2(vent[:, 0], vent[:, 1]))[:, None]
    distance = np.hypot(vent[:, 0], vent[:, 1])[:, None]
    turn = np.radians((azimuth - vent_azimuth + 180) % 360 - 180)
    if np.any(np.abs(turn) >= np.radians(80)):
        raise ValueError("a pixel looks more than 80 degrees away from the vent")
    reach = distance / np.cos(turn) + np.asarray(along, dtype=float)
    rise = reach * np.tan(np.radians(elevation)) + reach ** 2 * (1 - np.asarray(k, dtype=float)) / (2 * EARTH_RADIUS_M)
    return reach, distance * np.tan(turn), rise
```

- [ ] **Step 4: Run the tests, then the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_geometry.py -v` → 15 passed
Run: `.venv/Scripts/python.exe -m pytest` → 205 passed

- [ ] **Step 5: Commit**

```bash
git add vigia/geometry.py tests/test_geometry.py
git commit -m "Add a camera model with lens distortion and heights on the plane through the vent"
```

---

### Task 2: Solving a view (`vigia/geometry.py`, part 2)

A batched Levenberg–Marquardt fit of yaw, pitch, roll, focal length and k1. Jacobian columns are scaled to unit length before each step, because degrees, pixels and k1 differ by orders of magnitude. Without the scaling, a pinned k1 (prior sigma 1e-6) wrecks the step.

**Files:**
- Modify: `vigia/geometry.py`, `tests/test_geometry.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_geometry.py`, and extend its imports)

Change the imports at the top of the file to:

```python
from dataclasses import replace

import numpy as np
import pytest

from vigia.geometry import (References, View, direction, horizon_dip, local_en, on_vent_plane, sight,
                            solve_view)
```

Append:

```python
# --- solving a view


TRUE = dict(yaw=146.6, pitch=3.8, roll=0.7, focal=3050.0)


def kp_like_references(true=TRUE, landmarks=((134.4, -3.98), (160.0, -3.6)), horizon_azimuths=(),
                       focal=None, noise=0.0, sigma=2.0):
    """References seen by a known view: landmarks 14 km away at these azimuths/elevations, horizon pixels."""
    camera = view(**true)
    points = 14000 * at([a for a, _ in landmarks], [e for _, e in landmarks])
    points_px = camera.project(points)
    points_px = points_px + np.random.default_rng(1).normal(0, noise, points_px.shape) if noise else points_px
    dip = float(horizon_dip(2034.0))
    horizon_px = camera.project(at(list(horizon_azimuths), [-dip] * len(horizon_azimuths))).reshape(1, -1, 2)
    return References(points=points, points_px=points_px, points_sigma=np.full((len(landmarks), 2), sigma),
                      horizon_px=horizon_px, horizon_el=np.array([-dip]),
                      horizon_sigma=np.full(len(horizon_azimuths), sigma),
                      focal=None if focal is None else np.array([focal]), focal_sigma=None if focal is None else 30.0)


def solved(refs):
    found, rms = solve_view(refs, SIZE)
    return (found.yaw[0], found.pitch[0], found.roll[0], found.focal[0]), rms[0]


def test_two_landmarks_fix_the_view():
    params, rms = solved(kp_like_references())

    assert params == pytest.approx((146.6, 3.8, 0.7, 3050.0), abs=1e-4)
    assert rms == pytest.approx(0, abs=1e-6)


def test_the_vent_and_the_sea_horizon_fix_the_view():
    params, _ = solved(kp_like_references(landmarks=((134.4, -3.98),), horizon_azimuths=(125, 145, 165)))

    assert params == pytest.approx((146.6, 3.8, 0.7, 3050.0), abs=1e-3)


def test_a_known_lens_completes_one_landmark_and_one_horizon_pixel():
    refs = kp_like_references(landmarks=((134.4, -3.98),), horizon_azimuths=(165,), focal=3050.0)

    params, _ = solved(refs)

    assert params == pytest.approx((146.6, 3.8, 0.7, 3050.0), abs=1e-3)


def test_noisy_landmarks_are_fitted_by_least_squares():
    refs = kp_like_references(landmarks=((125, -3.0), (134.4, -3.98), (150, -3.5), (165, -3.7), (172, 2.0)),
                              noise=1.0)

    (yaw, pitch, roll, focal), rms = solved(refs)

    assert (yaw, pitch, roll) == pytest.approx((146.6, 3.8, 0.7), abs=0.05)
    assert focal == pytest.approx(3050, rel=0.01)
    assert 0.3 < rms < 2.0


def test_every_sample_is_solved_on_its_own():
    yaws = np.array([140.0, 146.6, 150.0])
    camera = View(yaws, np.full(3, 3.8), np.zeros(3), np.array([2900.0, 3050.0, 3200.0]), 1920, 1080)
    points = np.repeat(14000 * at([134.4, 160.0], [-3.98, -3.6]), 3, axis=0)
    refs = References(points=points, points_px=camera.project(points), points_sigma=np.full((2, 2), 2.0),
                      horizon_px=np.zeros((3, 0, 2)), horizon_el=np.zeros(3), horizon_sigma=np.zeros(0))

    found, _ = solve_view(refs, SIZE)

    assert found.yaw == pytest.approx(yaws, abs=1e-4)
    assert found.focal == pytest.approx([2900, 3050, 3200], abs=1e-2)


def test_references_from_centre_to_corner_measure_the_distortion():
    true = View(np.array([145.5]), np.array([3.0]), np.array([-0.1]), np.array([3485.0]), 1920, 1080, k1=-0.27)
    points = at([114.7, 117.9, 122.2, 125.2, 128.7, 134.4, 150.0], [10.6, 16.8, 5.8, 11.4, 16.9, -4.0, 2.0])
    refs = References(points=points, points_px=true.project(points), points_sigma=np.full((7, 2), 2.0),
                      horizon_px=np.zeros((1, 0, 2)), horizon_el=np.zeros(1), horizon_sigma=np.zeros(0),
                      k1=np.zeros(1), k1_sigma=1.0)

    found, rms = solve_view(refs, SIZE)

    assert (found.yaw[0], found.pitch[0], found.roll[0]) == pytest.approx((145.5, 3.0, -0.1), abs=1e-3)
    assert (found.focal[0], found.k1[0]) == pytest.approx((3485.0, -0.27), rel=1e-3)
    assert rms[0] == pytest.approx(0, abs=1e-3)


def test_without_a_prior_k1_stays_a_pinhole():
    found, _ = solve_view(kp_like_references(), SIZE)

    assert found.k1[0] == pytest.approx(0, abs=1e-9)


def test_a_roll_prior_completes_one_landmark_and_two_horizon_pixels():
    refs = replace(kp_like_references(landmarks=((134.4, -3.98),), horizon_azimuths=(140, 160)),
                   roll=np.array([0.7]), roll_sigma=0.01)

    params, _ = solved(refs)

    assert params == pytest.approx((146.6, 3.8, 0.7, 3050.0), abs=1e-2)


@pytest.mark.parametrize("landmarks, horizon_azimuths", [(((134.4, -3.98),), ()), ((), (125, 145, 165))],
                         ids=["one landmark alone", "horizon alone"])
def test_too_few_references_are_refused(landmarks, horizon_azimuths):
    with pytest.raises(ValueError, match="cannot fix a view"):
        solve_view(kp_like_references(landmarks=landmarks, horizon_azimuths=horizon_azimuths), SIZE)


def test_horizon_pixels_at_one_spot_leave_the_view_free():
    refs = kp_like_references(landmarks=((134.4, -3.98),), horizon_azimuths=(150, 150))

    with pytest.raises(ValueError, match="free"):
        solve_view(refs, SIZE)
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_geometry.py -v`
Expected: FAIL with `ImportError: cannot import name 'References' from 'vigia.geometry'`

- [ ] **Step 3: Add the solver to `vigia/geometry.py`**, between `View` and `on_vent_plane`

```python
@dataclass(frozen=True)
class References:
    """What fixes a view, for N samples: P landmarks, Q horizon pixels and the priors."""

    points: np.ndarray         # (N, P, 3) lines of sight to the landmarks (see `sight`) or celestial directions
    points_px: np.ndarray      # (N, P, 2) where they appear
    points_sigma: np.ndarray   # (P, 2) their pixel uncertainty, column and row
    horizon_px: np.ndarray     # (N, Q, 2) pixels on the sea horizon
    horizon_el: np.ndarray     # (N,) the horizon's elevation (minus its dip), degrees
    horizon_sigma: np.ndarray  # (Q,) pixel uncertainty across the line
    focal: np.ndarray | None = None  # (N,) focal length from the lens's field of view, pixels
    focal_sigma: float | None = None
    k1: np.ndarray | None = None     # (N,) prior on the distortion; None pins k1 at 0
    k1_sigma: float | None = None
    roll: np.ndarray | None = None   # (N,) prior on the roll, degrees
    roll_sigma: float | None = None


def solve_view(refs: References, size: tuple[int, int], iterations: int = 40) -> tuple[View, np.ndarray]:
    """Fit yaw, pitch, roll, focal length and k1 to the references; also each sample's RMS pixel misfit.

    Needs at least one landmark (nothing else fixes the azimuth) and at least
    four constraints: two per landmark, one per horizon pixel, one each for
    a focal length and a roll prior. Measuring k1 also needs references from
    near the centre to near the edges. Raises ValueError when the references
    cannot fix the view.
    """
    n_points, n_horizon = refs.points.shape[1], refs.horizon_px.shape[1]
    constraints = 2 * n_points + n_horizon + (refs.focal is not None) + (refs.roll is not None)
    if n_points < 1 or constraints < 4:
        raise ValueError(f"{n_points} landmark(s), {n_horizon} horizon pixel(s) and "
                         f"{'a' if refs.focal is not None else 'no'} focal length cannot fix a view: "
                         "give at least one landmark and four constraints")
    cx, cy = size[0] / 2, size[1] / 2
    sigma = np.concatenate([refs.points_sigma.reshape(-1), refs.horizon_sigma.reshape(-1)])
    k1_prior = refs.k1 if refs.k1 is not None else np.zeros(len(refs.points))
    k1_sigma = refs.k1_sigma if refs.k1 is not None else 1e-6

    def misfit(p: np.ndarray) -> np.ndarray:
        """Landmark and horizon misfits in pixels, (N, 2P + Q)."""
        view = View(p[:, 0], p[:, 1], p[:, 2], p[:, 3], cx, cy, p[:, 4])
        parts = [(view.project(refs.points) - refs.points_px).reshape(len(p), -1)]
        if n_horizon:
            azimuth, _ = view.ray(refs.horizon_px)
            level = view.project(direction(azimuth, refs.horizon_el[:, None]))
            parts.append(level[..., 1] - refs.horizon_px[..., 1])
        return np.nan_to_num(np.concatenate(parts, axis=1), nan=1e6)

    def residuals(p: np.ndarray) -> np.ndarray:
        parts = [misfit(p) / sigma, ((p[:, 4] - k1_prior) / k1_sigma)[:, None]]
        if refs.focal is not None:
            parts.append(((p[:, 3] - refs.focal) / refs.focal_sigma)[:, None])
        if refs.roll is not None:
            parts.append(((p[:, 2] - refs.roll) / refs.roll_sigma)[:, None])
        return np.concatenate(parts, axis=1)

    def jacobian(p: np.ndarray, at: np.ndarray) -> np.ndarray:
        return np.stack([(residuals(p + _STEPS * np.eye(5)[i]) - at) / _STEPS[i] for i in range(5)], -1)

    params = _start(refs, cx, cy, size[0], k1_prior)
    current = residuals(params)
    damping = np.full(len(params), 1e-3)
    for _ in range(iterations):
        jac = jacobian(params, current)
        scale = np.maximum(np.linalg.norm(jac, axis=1), 1e-300)  # (N, 5): solve for unit-sized columns
        jac = jac / scale[:, None, :]
        normal = np.einsum("nmi,nmj->nij", jac, jac)
        gradient = np.einsum("nmi,nm->ni", jac, current)
        step = -np.einsum("nij,nj->ni", np.linalg.pinv(normal + damping[:, None, None] * normal * np.eye(5)),
                          gradient) / scale
        trial = residuals(params + step)
        better = (trial ** 2).sum(1) < (current ** 2).sum(1)
        params = np.where(better[:, None], params + step, params)
        current = np.where(better[:, None], trial, current)
        damping = np.where(better, damping / 3, damping * 4)
    jac = jacobian(params, current)[0]
    jac = jac / np.maximum(np.linalg.norm(jac, axis=0), 1e-300)  # unit columns: degrees, pixels and k1 alike
    if np.linalg.matrix_rank(jac, tol=1e-6) < 5:
        raise ValueError("the references leave the view free in some direction (for example every "
                         "horizon pixel at one spot): spread them out or add a landmark")
    view = View(params[:, 0] % 360, params[:, 1], params[:, 2], params[:, 3], cx, cy, params[:, 4])
    return view, np.sqrt((misfit(params) ** 2).mean(1))


_STEPS = np.array([1e-4, 1e-4, 1e-4, 1e-2, 1e-6])  # finite-difference steps: degrees (3), pixels, k1


def _start(refs: References, cx: float, cy: float, width: int, k1: np.ndarray) -> np.ndarray:
    """A first guess: the first landmark where it appears, the priors, else level and a 60 degree lens."""
    focal = refs.focal if refs.focal is not None else np.full(len(refs.points), width / 2 / np.tan(np.radians(30)))
    first, pixel = refs.points[:, 0], refs.points_px[:, 0]
    azimuth = np.degrees(np.arctan2(first[:, 0], first[:, 1]))
    elevation = np.degrees(np.arctan2(first[:, 2], np.hypot(first[:, 0], first[:, 1])))
    yaw = azimuth - np.degrees(np.arctan((pixel[:, 0] - cx) / focal))
    pitch = elevation + np.degrees(np.arctan((pixel[:, 1] - cy) / focal))
    roll = refs.roll if refs.roll is not None else np.zeros_like(yaw)
    return np.stack([yaw, pitch, roll, focal, k1], -1)
```

- [ ] **Step 4: Run the tests, then the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_geometry.py -v` → 26 passed
Run: `.venv/Scripts/python.exe -m pytest` → 216 passed

- [ ] **Step 5: Commit**

```bash
git add vigia/geometry.py tests/test_geometry.py
git commit -m "Fit a camera's view to landmarks, the sea horizon and priors by least squares"
```

---

### Task 3: The calibration file (`vigia/calibration.py`, `config/calibration.yaml`)

**Files:**
- Create: `vigia/calibration.py`, `config/calibration.yaml`, `tests/test_calibration.py`
- Modify: `vigia/settings.py`, `.env.example`

- [ ] **Step 1: Write the failing tests** (`tests/test_calibration.py`)

```python
from datetime import datetime, timezone
from pathlib import Path

import pytest

from vigia.calibration import load_calibration
from vigia.config import ConfigError
from vigia.settings import Settings

REPO = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def write(tmp_path, text):
    path = tmp_path / "calibration.yaml"
    path.write_text(text, encoding="utf-8")
    return path


TWO_PRESETS = """
vents:
  kilauea: {lat: 19.40496, lon: -155.29022, elev_m: 1080}
cameras:
  kilauea-k2:
    volcano: kilauea
    position: {lat: 19.42, lon: -155.2889, elev_m: 1245}
    presets:
      - {name: wide, valid_from: "2026-10-17T00:00:00Z", valid_until: "2026-10-18T00:00:00Z", image_size: [3840, 2160]}
      - {name: cone, valid_from: "2026-10-26T00:00:00Z", image_size: [3840, 2160]}
"""


def test_the_committed_calibration_loads_and_places_kp_and_k2():
    calibration = load_calibration(REPO / "config" / "calibration.yaml")

    assert {"kilauea-kp", "kilauea-k2"} <= set(calibration.cameras)
    assert calibration.vents["kilauea"].elev_m == 1080


def test_preset_for_picks_the_view_in_force(tmp_path):
    calibration = load_calibration(write(tmp_path, TWO_PRESETS))

    def name(when):
        found = calibration.preset_for("kilauea-k2", when)
        return found.name if found else None

    assert name(datetime(2026, 10, 17, 15, 0, tzinfo=UTC)) == "wide"
    assert name(datetime(2026, 10, 18, 0, 0, tzinfo=UTC)) is None  # valid_until is exclusive
    assert name(datetime(2026, 10, 27, 0, 0, tzinfo=UTC)) == "cone"
    assert name(datetime(2026, 10, 16, 0, 0, tzinfo=UTC)) is None
    assert calibration.preset_for("kilauea-v1", datetime(2026, 10, 17, 15, 0, tzinfo=UTC)) is None


def test_overlapping_presets_are_refused(tmp_path):
    text = TWO_PRESETS.replace('valid_until: "2026-10-18T00:00:00Z"', 'valid_until: "2026-10-27T00:00:00Z"')

    with pytest.raises(ConfigError, match="overlap"):
        load_calibration(write(tmp_path, text))


def test_a_camera_whose_volcano_has_no_vent_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="no vent"):
        load_calibration(write(tmp_path, TWO_PRESETS.replace("volcano: kilauea", "volcano: nevado-del-ruiz")))


def test_times_must_state_their_offset(tmp_path):
    with pytest.raises(ConfigError, match="timezone"):
        load_calibration(write(tmp_path, TWO_PRESETS.replace('"2026-10-26T00:00:00Z"', '"2026-10-26T00:00:00"')))


def test_settings_name_the_calibration_file(monkeypatch):
    monkeypatch.setenv("CALIBRATION_PATH", "elsewhere/calibration.yaml")

    assert Settings.from_env().calibration_path == Path("elsewhere/calibration.yaml")
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calibration.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigia.calibration'`

- [ ] **Step 3: Create `vigia/calibration.py`** (Task 4 adds the Monte Carlo)

```python
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
```

- [ ] **Step 4: Create `config/calibration.yaml`** (Tasks 7 and 8 add the references)

```yaml
# Camera calibration for measuring heights: where each camera stands and
# where it points (vigia/calibration.py, vigia/geometry.py).
#
# - vents: the point each volcano's heights are measured from.
# - cameras: the lens position (lat/lon and elevation, with one-sigma
#   uncertainties) and one preset per view. A PTZ camera gets a new preset
#   whenever its framing changes; a camera's presets must not overlap in time.
# - A preset's references fix the camera's azimuth, tilt, roll, focal length
#   and lens distortion by least squares (vigia.geometry.solve_view):
#     vent_pixel  where the vent appears: the fountain's axis and foot;
#     landmarks   pixels of points with published positions (GNIS, USGS);
#     celestial   pixels of the Moon's centre, with its apparent azimuth and
#                 elevation at the frame's capture time (scripts/moon_references.py);
#     horizon     pixels on the sea horizon, whose dip below level follows
#                 from the camera's elevation;
#     fov, roll, distortion   priors: the datasheet's field of view, the roll
#                 of a level pan-tilt-zoom mount, the radial distortion k1.
#   Pixels are (column, row) in the full-size frame, picked on frames the
#   preset covers. Check a preset with scripts/check_calibration.py.
# - Official eruption values never go in here; they only check the result.
#
# Sources: docs/research/kilauea_geometry_draft.yaml, docs/research/kilauea_webcams.md
# and docs/research/calibration_ep55.md.

vents:
  kilauea:
    lat: 19.40496      # north vent, the only vent that fountained in episode 55
    lon: -155.29022
    elev_m: 1080
    sigma_m: 10
    sigma_elev_m: 5
    source: >-
      Position published in the Patrick & Adams 2026 data release
      (https://data.usgs.gov/datacatalog/metadata/USGS.691cfaedd4be021d1d89b467.xml);
      the vents moved under 20 m in a year. Elevation 1,080 m from the Aug 28, 2026
      survey through episode 54
      (https://www.usgs.gov/media/images/september-8-2026-kilauea-summit-eruption-reference-map);
      1,075 m through episode 50.

cameras:
  kilauea-kp:
    volcano: kilauea
    position:
      lat: 19.492709
      lon: -155.385281
      elev_m: 2034
      sigma_m: 500
      sigma_elev_m: 15
      source: >-
        Estimated. HVO puts KPcam on the south flank of Mauna Loa at about 6,700 ft
        (2,042 m, rounded to 100 ft), serviced along the Mauna Loa trail; placed at the
        Mauna Loa Lookout (OSM node 5061563731): ground 2,032 m (USGS EPQS) plus a 2 m mast.
    presets:
      - name: fixed
        valid_from: "2026-09-25T00:00:00Z"
        image_size: [3840, 2160]
        note: Fixed camera; the same framing (tree, skyline) on every AshCam morning from Sep 28 to Oct 27.
  kilauea-k2:
    volcano: kilauea
    position:
      lat: 19.4200
      lon: -155.2889
      elev_m: 1245
      sigma_m: 75
      sigma_elev_m: 5
      source: >-
        Estimated. On the Uēkahuna bluff, about 70 m north of the overlook platform in its
        foreground (OSM node 582340071): ground 1,243 m (USGS EPQS) plus 2 m.
    presets:
      - name: ep55
        valid_from: "2026-10-17T00:00:00Z"
        valid_until: "2026-10-18T00:00:00Z"
        image_size: [3840, 2160]
        note: PTZ without a readout; the framing held through episode 55 (frames register within 4 px).
```

- [ ] **Step 5: Name the file in the settings**

In `vigia/settings.py`, add the field after `prompts_path`:

```python
    prompts_path: Path
    calibration_path: Path
```

and in `from_env`, after the `prompts_path=` line:

```python
            calibration_path=Path(os.getenv("CALIBRATION_PATH", "config/calibration.yaml")),
```

In `.env.example`, after `PROMPTS_PATH=config/prompts.yaml`:

```
CALIBRATION_PATH=config/calibration.yaml
```

- [ ] **Step 6: Run the tests, then the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calibration.py -v` → 6 passed
Run: `.venv/Scripts/python.exe -m pytest` → 222 passed

- [ ] **Step 7: Commit**

```bash
git add vigia/calibration.py config/calibration.yaml vigia/settings.py .env.example tests/test_calibration.py
git commit -m "Describe camera positions, vents and calibration presets in config/calibration.yaml"
```

---

### Task 4: Monte Carlo samples of a preset's view (`sample_geometry`)

**Files:**
- Modify: `vigia/calibration.py`, `tests/test_calibration.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_calibration.py`, and extend its imports)

Change the imports at the top of the file to:

```python
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from vigia.calibration import (Calibration, CameraCalibration, Celestial, Distortion, FieldOfView, HorizonPixel,
                               Landmark, Preset, Roll, Site, VentPixel, load_calibration, sample_geometry)
from vigia.config import ConfigError
from vigia.geometry import View, direction, horizon_dip, local_en, sight
from vigia.settings import Settings
```

Append:

```python
# --- Monte Carlo samples

KP = Site(lat=19.492709, lon=-155.385281, elev_m=2034, sigma_m=500, sigma_elev_m=15)
VENT = Site(lat=19.40496, lon=-155.29022, elev_m=1080, sigma_m=10, sigma_elev_m=5)
PUUKOAE = Site(lat=19.35528, lon=-155.32235, elev_m=979, sigma_m=50, sigma_elev_m=10)
TRUE = View(np.array([146.6]), np.array([3.8]), np.array([0.7]), np.array([3050.0]), 1920, 1080)
WIDE = View(np.array([145.5]), np.array([3.0]), np.array([-0.1]), np.array([3485.0]), 1920, 1080, k1=-0.27)
MOONS = [(114.7, 10.6), (117.9, 16.8), (122.2, 5.8), (125.2, 11.4), (128.7, 16.9)]


def seen(site, view=TRUE):
    """Where a view puts a site, seen from KP."""
    east, north = local_en(site.lat, site.lon, KP.lat, KP.lon)
    return tuple(view.project(sight(east, north, site.elev_m - KP.elev_m)[None, None])[0, 0])


def on_horizon(azimuth):
    return tuple(TRUE.project(direction(azimuth, -horizon_dip(KP.elev_m))[None, None])[0, 0])


def preset(**fields):
    defaults = dict(name="fixed", valid_from="2026-10-17T00:00:00Z", image_size=(3840, 2160),
                    vent_pixel=VentPixel(pixel=seen(VENT)),
                    horizon=[HorizonPixel(pixel=on_horizon(a)) for a in (125, 145, 165)])
    return Preset(**(defaults | fields))


def calibration(*presets, position=KP):
    camera = CameraCalibration(volcano="kilauea", position=position, presets=list(presets) or [preset()])
    return Calibration(vents={"kilauea": VENT}, cameras={"kilauea-kp": camera})


def test_sample_zero_is_the_nominal_view():
    geometry = sample_geometry(calibration(), "kilauea-kp", preset(), samples=50)

    view = geometry.view
    assert (view.yaw[0], view.pitch[0], view.roll[0], view.focal[0]) == pytest.approx((146.6, 3.8, 0.7, 3050),
                                                                                      abs=1e-3)
    assert geometry.rms_px[0] == pytest.approx(0, abs=1e-3)
    assert (geometry.camera_elev[0], geometry.vent_elev[0]) == (2034, 1080)
    assert np.hypot(*geometry.vent[0, :2]) == pytest.approx(13948, abs=2)


def test_samples_spread_with_the_camera_uncertainty():
    tight = sample_geometry(calibration(position=KP.model_copy(update={"sigma_elev_m": 5})), "kilauea-kp",
                            preset(), samples=400)
    loose = sample_geometry(calibration(position=KP.model_copy(update={"sigma_elev_m": 60})), "kilauea-kp",
                            preset(), samples=400)

    assert 0 < tight.view.focal.std() < loose.view.focal.std()
    assert tight.camera_elev.std() == pytest.approx(5, rel=0.15)


def test_samples_repeat_with_the_same_seed():
    first, again, other = (sample_geometry(calibration(), "kilauea-kp", preset(), samples=20, seed=seed)
                           for seed in (7, 7, 8))

    assert np.array_equal(first.view.focal, again.view.focal)
    assert not np.array_equal(first.view.focal, other.view.focal)


def test_landmarks_and_a_field_of_view_fix_the_view():
    hfov = 2 * np.degrees(np.arctan(1920 / 3050))
    fixed = preset(horizon=[HorizonPixel(pixel=on_horizon(150))], fov=FieldOfView(hfov_deg=hfov),
                   landmarks=[Landmark(name="Puukoae", pixel=seen(PUUKOAE), **PUUKOAE.model_dump())])

    view = sample_geometry(calibration(fixed), "kilauea-kp", fixed, samples=5).view

    assert (view.yaw[0], view.pitch[0], view.roll[0], view.focal[0]) == pytest.approx((146.6, 3.8, 0.7, 3050),
                                                                                      abs=1e-3)


def test_a_preset_without_references_cannot_be_sampled():
    bare = preset(vent_pixel=None, horizon=[])

    with pytest.raises(ValueError, match="cannot fix a view"):
        sample_geometry(calibration(bare), "kilauea-kp", bare, samples=5)


def test_the_moon_and_a_free_distortion_fix_a_wide_lens():
    moons = [Celestial(name=f"moon {i}", pixel=tuple(WIDE.project(direction(az, el)[None, None])[0, 0]),
                       az_deg=az, el_deg=el) for i, (az, el) in enumerate(MOONS)]
    wide = preset(vent_pixel=VentPixel(pixel=seen(VENT, WIDE)), horizon=[], celestial=moons,
                  distortion=Distortion(k1=0.0, sigma=1.0))

    view = sample_geometry(calibration(wide), "kilauea-kp", wide, samples=5).view

    assert (view.yaw[0], view.pitch[0], view.roll[0]) == pytest.approx((145.5, 3.0, -0.1), abs=1e-3)
    assert (view.focal[0], view.k1[0]) == pytest.approx((3485.0, -0.27), rel=1e-3)


def test_a_distortion_the_references_cannot_measure_follows_its_prior():
    # two landmarks fit any k1 exactly, so only the prior decides it
    lens = preset(horizon=[], distortion=Distortion(k1=-0.15, sigma=0.15),
                  landmarks=[Landmark(name="Puukoae", pixel=seen(PUUKOAE), **PUUKOAE.model_dump())])

    view = sample_geometry(calibration(lens), "kilauea-kp", lens, samples=400).view

    assert view.k1[0] == pytest.approx(-0.15, abs=1e-3)
    assert view.k1[1:].std() == pytest.approx(0.15, rel=0.15)


def test_a_roll_the_references_cannot_measure_follows_its_prior():
    # the vent and the lens fix azimuth, tilt and focal length; nothing but the prior sets the roll
    level = preset(horizon=[], fov=FieldOfView(hfov_deg=2 * np.degrees(np.arctan(1920 / 3050))),
                   roll=Roll(deg=0.7, sigma_deg=0.5))

    view = sample_geometry(calibration(level), "kilauea-kp", level, samples=400).view

    assert view.roll[0] == pytest.approx(0.7, abs=1e-3)
    assert view.roll[1:].std() == pytest.approx(0.5, rel=0.2)
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calibration.py -v`
Expected: FAIL with `ImportError: cannot import name 'sample_geometry' from 'vigia.calibration'`

- [ ] **Step 3: Add the Monte Carlo to `vigia/calibration.py`**

Change the imports to:

```python
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
```

Append at the end of the file:

```python
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
```

- [ ] **Step 4: Run the tests, then the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calibration.py -v` → 14 passed
Run: `.venv/Scripts/python.exe -m pytest` → 230 passed

- [ ] **Step 5: Commit**

```bash
git add vigia/calibration.py tests/test_calibration.py
git commit -m "Draw Monte Carlo samples of a preset's view over every uncertain input"
```

---

### Task 5: Measurements of detections (`vigia/metrics.py`, `vigia-measure`)

**Files:**
- Create: `vigia/metrics.py`, `tests/test_metrics.py`
- Modify: `vigia/db.py`, `pyproject.toml`

- [ ] **Step 1: Write the failing tests** (`tests/test_metrics.py`)

```python
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from conftest import make_jpeg
from vigia import db, masks
from vigia.calibration import Calibration, CameraCalibration, Geometry, HorizonPixel, Preset, Site, VentPixel
from vigia.geometry import View, direction, horizon_dip, local_en, sight
from vigia.ingest.store import FrameStore
from vigia.metrics import main, measure_mask, measure_window
from vigia.timeutil import to_iso

T0 = datetime(2026, 10, 17, 15, 0, 5, tzinfo=timezone.utc)


# --- one detection, on a camera 1 km south of the vent and 100 m above it


def geometry(samples=400):
    """A level camera at 1200 m looking north at a vent 1000 m away and 100 m below; f = 1000 px."""
    n = samples
    view = View(np.zeros(n), np.zeros(n), np.zeros(n), np.full(n, 1000.0), 960.0, 540.0)
    vent = np.repeat(sight(0.0, 1000.0, -100.0)[None], n, axis=0)
    return Geometry("test-cam", "test", view, np.full(n, 1200.0), vent, np.full(n, 1100.0), np.full(n, 0.13),
                    np.zeros(n))


def block(rows, cols):
    return np.ones((rows, cols), dtype=bool)


def by_metric(results):
    return {m.metric: m for m in results}


def test_the_top_of_a_fountain_300_m_above_the_vent_is_measured_with_sigma():
    # 300 m above the vent is 200 m above the camera: row 540 - 1000 * 0.2 = 340
    results = by_metric(measure_mask(geometry(), block(60, 20), left=950, top=340, target="fountain",
                                     rng=np.random.default_rng(0)))

    assert results["top_height"].value == pytest.approx(300.07, abs=0.01)
    assert results["top_altitude"].value == pytest.approx(1400.07, abs=0.01)
    assert results["top_height"].unit == "m"
    assert 3 < results["top_height"].sigma < 10   # 3 px of mask edge (3 m) and 5 degrees of lean (5 m)


def test_a_plume_leans_more_than_a_fountain():
    def sigma(target):
        found = by_metric(measure_mask(geometry(), block(60, 20), 950, 340, target, np.random.default_rng(0)))
        return found["top_height"].sigma

    assert sigma("plume") > 1.5 * sigma("fountain")


def test_a_mask_cut_off_by_the_top_of_the_frame_has_no_top():
    results = by_metric(measure_mask(geometry(), block(60, 20), 950, 1, "plume", np.random.default_rng(0)))

    assert "top_height" not in results and "top_altitude" not in results
    assert "area" in results


def test_area_counts_pixels_at_the_vents_distance():
    results = by_metric(measure_mask(geometry(), block(10, 20), 950, 400, "fountain", np.random.default_rng(0)))

    # 200 pixels of (1005 m / 1000 px) squared
    assert results["area"].value == pytest.approx(200 * (np.linalg.norm(sight(0.0, 1000.0, -100.0)) / 1000) ** 2)
    assert results["area"].unit == "m2"


@pytest.mark.parametrize("left, offset_sign, bearing", [(1060, 1, 90.0), (821, -1, 270.0)],
                         ids=["right of the vent", "left of the vent"])
def test_a_plume_drifting_across_the_line_of_sight_gives_its_side(left, offset_sign, bearing):
    results = by_metric(measure_mask(geometry(), block(40, 40), left, 300, "plume", np.random.default_rng(0)))

    assert np.sign(results["drift_offset"].value) == offset_sign
    assert abs(results["drift_offset"].value) == pytest.approx(120, abs=1)  # centroid 120 px from the vent column
    assert (results["drift_bearing"].value, results["drift_bearing"].unit) == (bearing, "deg")


def test_fountains_get_no_drift():
    results = by_metric(measure_mask(geometry(), block(40, 40), 1060, 300, "fountain", np.random.default_rng(0)))

    assert "drift_offset" not in results


def test_an_empty_mask_gives_nothing():
    assert measure_mask(geometry(), np.zeros((5, 5), dtype=bool), 0, 0, "plume", np.random.default_rng(0)) == []


# --- detections in the database


KP = Site(lat=19.492709, lon=-155.385281, elev_m=2034, sigma_m=500, sigma_elev_m=15)
VENT = Site(lat=19.40496, lon=-155.29022, elev_m=1080, sigma_m=10, sigma_elev_m=5)
SIZE = (384, 216)
TRUE = View(np.array([146.6]), np.array([3.8]), np.array([0.7]), np.array([305.0]), 192, 108)


def kp_calibration(valid_from="2026-10-17T00:00:00Z", image_size=SIZE, references=True):
    east, north = local_en(VENT.lat, VENT.lon, KP.lat, KP.lon)
    vent_px = TRUE.project(sight(east, north, VENT.elev_m - KP.elev_m)[None, None])[0, 0]
    horizon = [TRUE.project(direction(a, -horizon_dip(KP.elev_m))[None, None])[0, 0] for a in (125, 145, 165)]
    preset = Preset(name="fixed", valid_from=valid_from, image_size=image_size,
                    vent_pixel=VentPixel(pixel=tuple(vent_px)) if references else None,
                    horizon=[HorizonPixel(pixel=tuple(p)) for p in horizon] if references else [])
    camera = CameraCalibration(volcano="kilauea", position=KP, presets=[preset])
    return Calibration(vents={"kilauea": VENT}, cameras={"kilauea-kp": camera})


@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def add_detection(conn, store, minutes, target="fountain", box=(60, 140, 70, 150), size=SIZE):
    captured_at = T0 + timedelta(minutes=minutes)
    frame_id = store.add("kilauea-kp", make_jpeg(color=(10 + minutes, 80, 40), size=size), captured_at=captured_at,
                         timestamp_source="ashcam", fetched_at=captured_at)
    left, top, right, bottom = box
    mask = block(bottom - top, right - left)
    with conn:
        run_id = conn.execute(
            """INSERT INTO tracking_runs (camera_id, target, phrase, window_start, window_end, frame_ids,
                                          video_width, video_height, created_at)
               VALUES ('kilauea-kp', ?, ?, ?, ?, ?, ?, ?, '2026-10-28T00:00:00Z')""",
            (target, target, to_iso(captured_at), to_iso(captured_at), json.dumps([frame_id]), *size)).lastrowid
        track_id = conn.execute(
            "INSERT INTO tracks (run_id, object_id, first_seen, last_seen, detections) VALUES (?, '0', ?, ?, 1)",
            (run_id, to_iso(captured_at), to_iso(captured_at))).lastrowid
        return conn.execute(
            """INSERT INTO detections (track_id, frame_id, box_left, box_top, box_right, box_bottom, score,
                                       area_px, mask_rle) VALUES (?, ?, ?, ?, ?, ?, 0.8, ?, ?)""",
            (track_id, frame_id, *box, int(mask.sum()), json.dumps(masks.encode(mask)))).lastrowid


def stored(conn, detection_id):
    return {row["metric"]: row for row in conn.execute(
        "SELECT * FROM measurements WHERE detection_id = ?", (detection_id,))}


def window(conn, calibration, **kwargs):
    return measure_window(conn, calibration, "kilauea-kp", T0 - timedelta(minutes=1), T0 + timedelta(hours=1),
                          samples=50, **kwargs)


def test_measure_window_stores_each_metric_of_each_detection(conn, store):
    fountain = add_detection(conn, store, 0)
    plume = add_detection(conn, store, 5, target="plume", box=(80, 60, 120, 150))

    report = window(conn, kp_calibration())

    assert (report.measured, report.values, report.errors) == (2, 3 + 5, [])
    row = stored(conn, fountain)["top_height"]
    assert (row["camera_id"], row["captured_at"], row["target"], row["unit"], row["preset"]) == (
        "kilauea-kp", "2026-10-17T15:00:05Z", "fountain", "m", "fixed")
    assert row["sigma"] > 0
    assert set(stored(conn, plume)) == {"top_height", "top_altitude", "area", "drift_offset", "drift_bearing"}


def test_measured_detections_are_skipped_unless_redo(conn, store):
    detection = add_detection(conn, store, 0)
    calibration = kp_calibration()
    window(conn, calibration)

    again = window(conn, calibration)
    redone = window(conn, calibration, redo=True)

    assert (again.measured, again.skipped) == (0, 1)
    assert (redone.measured, redone.skipped) == (1, 0)
    assert conn.execute("SELECT COUNT(*) FROM measurements WHERE detection_id = ?", (detection,)).fetchone()[0] == 3


def test_detections_outside_every_preset_are_counted_not_measured(conn, store):
    add_detection(conn, store, 0)

    report = window(conn, kp_calibration(valid_from="2026-10-18T00:00:00Z"))

    assert (report.measured, report.uncalibrated) == (0, 1)


def test_a_frame_of_another_size_is_reported(conn, store):
    add_detection(conn, store, 0, size=(320, 240))

    report = window(conn, kp_calibration())

    assert report.measured == 0
    assert "320x240" in report.errors[0]


def test_a_preset_that_cannot_be_solved_is_reported_once(conn, store):
    add_detection(conn, store, 0)
    add_detection(conn, store, 5)

    report = window(conn, kp_calibration(references=False))

    assert report.measured == 0
    assert len(report.errors) == 1 and "preset fixed" in report.errors[0]


def test_the_same_seed_gives_the_same_sigmas(conn, store):
    detection = add_detection(conn, store, 0)
    window(conn, kp_calibration())
    first = stored(conn, detection)["top_height"]["sigma"]

    window(conn, kp_calibration(), redo=True)

    assert stored(conn, detection)["top_height"]["sigma"] == first


CALIBRATION_YAML = """
vents:
  kilauea: {lat: 19.40496, lon: -155.29022, elev_m: 1080}
cameras:
  kilauea-kp:
    volcano: kilauea
    position: {lat: 19.492709, lon: -155.385281, elev_m: 2034}
    presets:
      - {name: later, valid_from: "2026-10-20T00:00:00Z", image_size: [384, 216]}
"""


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    path = tmp_path / "calibration.yaml"
    path.write_text(CALIBRATION_YAML, encoding="utf-8")
    monkeypatch.setenv("CALIBRATION_PATH", str(path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigia.sqlite"))
    return tmp_path / "data"


def test_cli_reports_the_window(cli_env, capsys):
    conn = db.connect(cli_env / "vigia.sqlite")
    add_detection(conn, FrameStore(conn, cli_env), 0)  # Oct 17, before the only preset (Oct 20)
    conn.close()

    main(["--camera", "kilauea-kp", "--start", "2026-10-17T13:00Z", "--end", "2026-10-17T19:30Z"])

    assert "0 detections measured" in capsys.readouterr().out


def test_cli_refuses_a_camera_without_calibration(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--camera", "kilauea-v1", "--start", "2026-10-17T13:00Z", "--end", "2026-10-17T19:30Z"])

    assert "kilauea-v1" in capsys.readouterr().err
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigia.metrics'`

- [ ] **Step 3: Add the `measurements` table** to `SCHEMA` in `vigia/db.py`, after the `idx_detections_track` index

```sql
CREATE TABLE IF NOT EXISTS measurements (    -- one metric of one detection (vigia.metrics)
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    detection_id INTEGER NOT NULL REFERENCES detections (id),
    frame_id     INTEGER NOT NULL REFERENCES frames (id),
    camera_id    TEXT    NOT NULL,
    captured_at  TEXT    NOT NULL,  -- UTC capture time of the frame
    target       TEXT    NOT NULL,  -- plume | fountain | incandescence
    metric       TEXT    NOT NULL,  -- top_height | top_altitude | area | drift_offset | drift_bearing
    value        REAL    NOT NULL,
    sigma        REAL    NOT NULL,  -- one standard deviation, from the Monte Carlo
    unit         TEXT    NOT NULL,  -- m | m2 | deg
    preset       TEXT    NOT NULL,  -- the calibration preset used
    computed_at  TEXT    NOT NULL,  -- UTC
    UNIQUE (detection_id, metric)
);
CREATE INDEX IF NOT EXISTS idx_measurements_series ON measurements (camera_id, metric, captured_at);
```

- [ ] **Step 4: Create `vigia/metrics.py`**

```python
"""Measurements of tracked objects: top height and altitude, area and plume drift, each with sigma.

Every stored detection (vigia.tracking) on a frame its camera's calibration
covers is placed on the vertical plane through the vent, square to the line
of sight (vigia.geometry.on_vent_plane):
- top_height: metres above the vent, and top_altitude: metres above sea
  level, of the mask's highest pixel. A mask that reaches the frame's top
  edge is cut off, so it gets neither.
- area: the mask's pixels times the square of the metres per pixel at the
  vent's distance (m2).
- drift_offset and drift_bearing, plumes only: how far the mask's centroid
  sits across the line of sight from the vent (metres, positive to the
  right) and the bearing of that side. One camera sees only the part of the
  drift across its line of sight.

Each value is sample 0 of the calibration's Monte Carlo (vigia.calibration)
and its sigma the spread of the other samples, which also move the top pixel
by the mask edge's uncertainty and lean the object along the line of sight.
Results go to the `measurements` table.

    vigia-measure --camera kilauea-kp --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z
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

from vigia import db, masks
from vigia.calibration import Calibration, Geometry, load_calibration, sample_geometry
from vigia.geometry import on_vent_plane
from vigia.settings import Settings
from vigia.timeutil import parse_utc, to_iso, utcnow

SAMPLES = 1000
MASK_EDGE_PX = 3.0  # uncertainty of a SAM mask's edge, in frame pixels
LEAN_SIGMA_DEG = {"plume": 10.0, "fountain": 5.0, "incandescence": 5.0}  # tilt along the line of sight
CUT_OFF_ROWS = 2    # a mask whose top lies in the frame's first rows runs off the frame


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
    metres_per_px = np.linalg.norm(geometry.vent, axis=-1) / geometry.view.focal
    results.append(_summary("area", rows.size * metres_per_px ** 2, "m2"))
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
```

- [ ] **Step 5: Register the console script** in `pyproject.toml`, after `vigia-quality`:

```toml
vigia-measure = "vigia.metrics:main"
```

Run: `.venv/Scripts/python.exe -m pip install -e ".[dev]"`

- [ ] **Step 6: Run the tests, then the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_metrics.py -v` → 16 passed
Run: `.venv/Scripts/python.exe -m pytest` → 246 passed
Run: `.venv/Scripts/vigia-measure.exe --help` → the usage text

- [ ] **Step 7: Commit**

```bash
git add vigia/metrics.py vigia/db.py pyproject.toml tests/test_metrics.py
git commit -m "Measure each detection's height, area and drift with Monte Carlo sigmas"
```

---

### Task 6: Calibration and validation scripts

Three thin scripts. Check each by running it as Step 4 says. This task may call the public JPL Horizons API once.

**Files:**
- Create: `scripts/moon_references.py`, `scripts/check_calibration.py`, `scripts/validate_ep55.py`

- [ ] **Step 1: Create `scripts/moon_references.py`**

```python
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
```

- [ ] **Step 2: Create `scripts/check_calibration.py`**

```python
"""Check a camera preset's calibration: the solved view, each reference's misfit, and an overlay.

Solves the preset in force at --at (config/calibration.yaml) with its Monte
Carlo and prints the view (azimuth, tilt, roll, focal length, distortion and
the field of view across the middle row, each with sigma) and, for every
reference, where it was picked and where the solved view puts it. Then draws
on the camera's stored frame nearest --at:
- each reference as picked (yellow cross) and as solved (magenta circle);
- the sea horizon (cyan) and the vent (red);
- a height scale above the vent (white): every 1,000 m above sea level, or
  every 50 m above the vent for a camera within 5 km of it.
The overlay goes to data/calibration/<camera>_<preset>_<frame time>.jpg.

    python scripts/check_calibration.py --camera kilauea-kp --at 2026-10-17T17:00Z
"""

from __future__ import annotations

import argparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from vigia import db
from vigia.calibration import load_calibration, sample_geometry
from vigia.geometry import REFRACTION_K, View, direction, horizon_dip, local_en, sight
from vigia.settings import Settings
from vigia.timeutil import parse_utc, to_iso


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--at", type=parse_utc, required=True, help="a capture time the preset covers")
    parser.add_argument("--samples", type=int, default=1000)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    calibration = load_calibration(settings.calibration_path)
    preset = calibration.preset_for(args.camera, args.at)
    if preset is None:
        raise SystemExit(f"no preset of {args.camera} covers {to_iso(args.at)}")
    camera = calibration.cameras[args.camera]
    try:
        geometry = sample_geometry(calibration, args.camera, preset, args.samples)
    except ValueError as exc:
        raise SystemExit(f"preset {preset.name}: {exc}")
    view = geometry.view
    nominal = View(view.yaw[:1], view.pitch[:1], view.roll[:1], view.focal[:1], view.cx, view.cy, view.k1[:1])
    edges = np.repeat(np.array([[[0.0, view.cy], [2 * view.cx, view.cy]]]), len(view.yaw), axis=0)
    left, right = view.ray(edges)[0].T
    hfov = (right - left) % 360  # the field of view across the middle row, distortion included
    print(f"{args.camera} / {preset.name}: RMS misfit {geometry.rms_px[0]:.2f} px")
    for name, values, unit in [("azimuth", view.yaw, "deg"), ("tilt", view.pitch, "deg"), ("roll", view.roll, "deg"),
                               ("focal", view.focal, "px"), ("k1", view.k1, ""), ("hfov", hfov, "deg")]:
        print(f"  {name:8s} {values[0]:9.3f} ± {values[1:].std():.3f} {unit}")

    origin = camera.position
    vent = calibration.vents[camera.volcano]

    def seen(site) -> np.ndarray:
        east, north = local_en(site.lat, site.lon, origin.lat, origin.lon)
        return nominal.project(sight(east, north, site.elev_m - origin.elev_m)[None, None])[0, 0]

    marks = [("vent", preset.vent_pixel.pixel, seen(vent))] if preset.vent_pixel else []
    marks += [(mark.name, mark.pixel, seen(mark)) for mark in preset.landmarks]
    marks += [(body.name, body.pixel, nominal.project(direction(body.az_deg, body.el_deg)[None, None])[0, 0])
              for body in preset.celestial]
    dip = float(horizon_dip(origin.elev_m, REFRACTION_K))
    for i, pick in enumerate(preset.horizon):
        azimuth, _ = nominal.ray(np.array([[pick.pixel]], dtype=float))
        marks.append((f"horizon {i + 1}", pick.pixel, nominal.project(direction(azimuth, -dip))[0, 0]))
    print("  reference          picked (col, row)      solved (col, row)      misfit")
    for name, picked, solved in marks:
        print(f"  {name:16s} ({picked[0]:7.1f}, {picked[1]:7.1f})  ({solved[0]:7.1f}, {solved[1]:7.1f})  "
              f"{np.hypot(*(np.asarray(picked) - solved)):6.1f} px")

    conn = db.connect(settings.db_path)
    frame = conn.execute(
        """SELECT * FROM frames WHERE camera_id = ? AND width = ? AND height = ?
           ORDER BY ABS(julianday(captured_at) - julianday(?)) LIMIT 1""",
        (args.camera, *preset.image_size, to_iso(args.at))).fetchone()
    conn.close()
    if frame is None:
        raise SystemExit(f"no stored {preset.image_size[0]}x{preset.image_size[1]} frame of {args.camera}")
    with Image.open(settings.data_dir / frame["path"]) as raw:
        image = raw.convert("RGB")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=max(14, image.width // 160))
    size = max(6, image.width // 300)
    for name, picked, solved in marks:
        x, y = picked
        draw.line([(x - size, y), (x + size, y)], fill=(255, 255, 0), width=2)
        draw.line([(x, y - size), (x, y + size)], fill=(255, 255, 0), width=2)
        draw.ellipse([solved[0] - size, solved[1] - size, solved[0] + size, solved[1] + size],
                     outline=(255, 0, 255), width=2)
        draw.text((x + size, y - 3 * size), name, fill=(255, 255, 0), font=font)
    azimuths = left[0] + np.linspace(0, hfov[0], 400)  # only across the frame: past its edges the lens folds back
    line = nominal.project(direction(azimuths, -dip)[None])[0]
    draw.line([tuple(p) for p in line if np.isfinite(p).all()], fill=(0, 255, 255), width=2)
    east, north = local_en(vent.lat, vent.lon, origin.lat, origin.lon)
    distance = float(np.hypot(east, north))
    ticks = ([(h - vent.elev_m, f"{h:,.0f} m a.s.l.") for h in range(2000, 11000, 1000)] if distance > 5000
             else [(h, f"{h} m") for h in range(0, 501, 50)])
    for height, label in ticks:
        x, y = nominal.project(sight(east, north, vent.elev_m + height - origin.elev_m)[None, None])[0, 0]
        if np.isfinite(x) and 0 <= y < image.height:
            draw.line([(x - 2 * size, y), (x + 2 * size, y)], fill=(255, 255, 255), width=2)
            draw.text((x + 3 * size, y - size), label, fill=(255, 255, 255), font=font)
    vx, vy = nominal.project(sight(east, north, vent.elev_m - origin.elev_m)[None, None])[0, 0]
    draw.ellipse([vx - size, vy - size, vx + size, vy + size], outline=(255, 0, 0), width=3)
    out = settings.data_dir / "calibration" / f"{args.camera}_{preset.name}_{frame['captured_at'][:16].replace(':', '')}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, quality=90)
    print(f"overlay: {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Create `scripts/validate_ep55.py`**

```python
"""Compare our Kīlauea episode 55 measurements with the official USGS values: docs/VALIDATION.md.

Run vigia-measure for kilauea-kp and kilauea-k2 over 2026-10-17
13:00-19:30Z first. This script reads those measurements, the fountain
tracks' last detections and the plume drift, and writes the comparison with
errors and sigmas. The official values and their sources are in
docs/research/episode55.md: they are compared with, never fitted.

    python scripts/validate_ep55.py
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path

import numpy as np

from vigia import db
from vigia.settings import Settings
from vigia.timeutil import parse_utc, utcnow

FT = 0.3048
HST = timezone(timedelta(hours=-10))
EPISODE = ("2026-10-17T13:00:00Z", "2026-10-17T19:30:00Z")
OFFICIAL_END = "2026-10-17T19:03:00Z"  # 9:03 a.m. HST, VAN 2026/H489 (the eruption table says 9:06)
OFFICIAL_DRIFT_DEG = 225.0             # "MOV: SW" (VONA 2026/67), winds from the NE below 20,000 ft


@dataclass(frozen=True)
class Check:
    quantity: str
    camera_id: str
    target: str
    metric: str          # top_height: above the vent; top_altitude: above sea level
    start: str           # UTC window of our frames, inclusive
    end: str
    aggregate: str       # max: our highest frame in the window; mean: the window's average
    official_m: float
    official: str        # as HVO stated it
    source: str
    upper_bound: bool = False  # HVO said "under" this value


CHECKS = [
    Check("fountain height (peak)", "kilauea-k2", "fountain", "top_height", "2026-10-17T14:50:00Z",
          "2026-10-17T15:10:59Z", "max", 720 * FT, "720 ft, 04:50-05:10", "HVO Daily Update, Oct 17"),
    Check("fountain height", "kilauea-k2", "fountain", "top_height", "2026-10-17T15:57:00Z",
          "2026-10-17T16:07:59Z", "mean", 650 * FT, "about 650 ft at 06:02", "HVO message 06:02 HST"),
    Check("fountain height", "kilauea-k2", "fountain", "top_height", "2026-10-17T16:55:00Z",
          "2026-10-17T17:05:59Z", "mean", 500 * FT, "500 ft by 07:00", "HVO Daily Update, Oct 17"),
    Check("fountain height", "kilauea-k2", "fountain", "top_height", "2026-10-17T17:55:00Z",
          "2026-10-17T18:05:59Z", "mean", 300 * FT, "about 300 ft by 08:00", "HVO Daily Update, Oct 17"),
    Check("plume top (peak)", "kilauea-kp", "plume", "top_altitude", "2026-10-17T14:50:00Z",
          "2026-10-17T15:10:59Z", "max", 25000 * FT, "25,000 ft a.s.l., 04:50-05:10",
          "VONA 2026/67 (webcam); HVO Daily Update"),
    Check("plume top", "kilauea-kp", "plume", "top_altitude", "2026-10-17T15:57:00Z", "2026-10-17T16:07:59Z",
          "mean", 17000 * FT, "17,000 ft a.s.l. at 06:02", "HVO message 06:02 HST"),
    Check("plume top", "kilauea-kp", "plume", "top_altitude", "2026-10-17T17:25:00Z", "2026-10-17T17:35:59Z",
          "mean", 13000 * FT, "under 13,000 ft a.s.l. by 07:30", "HVO Daily Update, Oct 17", upper_bound=True),
]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("docs/VALIDATION.md"))
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    conn = db.connect(settings.db_path)
    rows = [height_row(conn, check) for check in CHECKS]
    ends = end_rows(conn)
    drifts = drift_rows(conn)
    conn.close()
    args.out.write_text(report(rows, ends, drifts), encoding="utf-8")
    print(f"wrote {args.out}")
    for row in rows:
        print(" | ".join(row))


def per_frame(conn, check: Check) -> list[tuple[str, float, float]]:
    """(capture time, value, sigma) per frame in the window: the highest detection on each frame."""
    found = conn.execute(
        """SELECT captured_at, value, sigma FROM measurements
           WHERE camera_id = ? AND target = ? AND metric = ? AND captured_at BETWEEN ? AND ?
           ORDER BY captured_at, value DESC""",
        (check.camera_id, check.target, check.metric, check.start, check.end)).fetchall()
    best = {}
    for captured_at, value, sigma in found:
        best.setdefault(captured_at, (captured_at, value, sigma))
    return list(best.values())


def height_row(conn, check: Check) -> list[str]:
    frames = per_frame(conn, check)
    window = f"{hst(check.start)}-{hst(check.end)}"
    official = f"{check.official} ({check.official_m:,.0f} m)"
    if not frames:
        return [check.quantity, window, check.camera_id, official, "no measurement", "", "", ""]
    values = np.array([f[1] for f in frames])
    sigmas = np.array([f[2] for f in frames])
    if check.aggregate == "max":
        i = int(values.argmax())
        value, sigma, how = values[i], sigmas[i], f"max of {len(frames)} frames, at {hst(frames[i][0])}"
    else:
        value, sigma = values.mean(), float(np.sqrt((sigmas ** 2).mean()))
        how = f"mean of {len(frames)} frames (spread {values.std():.0f} m)"
    error = value - check.official_m
    if check.upper_bound:
        verdict = "yes" if value - 2 * sigma <= check.official_m else "no"
        error_text = "within the bound" if value <= check.official_m else f"{error:+,.0f} m above it"
        z_text = f"{error / sigma:+.1f}" if value > check.official_m else "-"
    else:
        verdict = "yes" if abs(error) <= 2 * sigma else "no"
        error_text = f"{error:+,.0f} m ({100 * error / check.official_m:+.0f} %)"
        z_text = f"{error / sigma:+.1f}"
    ours = f"{value:,.0f} ± {sigma:,.0f} m ({value / FT:,.0f} ft); {how}"
    return [check.quantity, window, check.camera_id, official, ours, error_text, z_text, verdict]


def end_rows(conn) -> list[list[str]]:
    rows = []
    for camera_id, last in conn.execute(
            """SELECT r.camera_id, MAX(t.last_seen) FROM tracks t JOIN tracking_runs r ON r.id = t.run_id
               WHERE r.target = 'fountain' AND r.window_start >= ? AND r.window_end <= ?
               GROUP BY r.camera_id ORDER BY r.camera_id""", EPISODE):
        if last is None:
            continue
        minutes = (parse_utc(last) - parse_utc(OFFICIAL_END)).total_seconds() / 60
        rows.append([camera_id, hst(last, seconds=True), "09:03", f"{minutes:+.1f} min"])
    return rows


def drift_rows(conn) -> list[list[str]]:
    rows = []
    for camera_id in ("kilauea-kp", "kilauea-k2"):
        bearings = np.array([value for (value,) in conn.execute(
            """SELECT value FROM measurements WHERE camera_id = ? AND metric = 'drift_bearing'
               AND captured_at BETWEEN ? AND ?""", (camera_id, *EPISODE))])
        if not bearings.size:
            continue
        sides, counts = np.unique(np.round(bearings).astype(int), return_counts=True)
        main_side = int(sides[counts.argmax()])
        off = (main_side - OFFICIAL_DRIFT_DEG + 180) % 360 - 180
        share = ", ".join(f"{side}°: {count}" for side, count in zip(sides, counts))
        rows.append([camera_id, str(bearings.size), share, f"{main_side}° ({off:+.0f}° from SW)",
                     "yes" if abs(off) <= 90 else "no"])
    return rows


def hst(utc: str, seconds: bool = False) -> str:
    return parse_utc(utc).astimezone(HST).strftime("%H:%M:%S" if seconds else "%H:%M")


def table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join(lines + ["| " + " | ".join(row) + " |" for row in rows])


def report(rows: list[list[str]], ends: list[list[str]], drifts: list[list[str]]) -> str:
    agree = sum(row[-1] == "yes" for row in rows)
    return f"""# Validation: Kīlauea episode 55 (2026-10-17)

Generated by `scripts/validate_ep55.py` on {utcnow():%Y-%m-%d %H:%M} UTC from the measurements in
`data/vigia.sqlite`. Official values and their sources: [episode55.md](research/episode55.md).
Calibration: `config/calibration.yaml`, with the evidence in
[calibration_ep55.md](research/calibration_ep55.md).

**Method.** SAM 3.1 tracks the fountain on K2cam and the plume on KPcam (Phase 2). Each mask's highest
pixel is placed on the vertical plane through the north vent, square to the camera's line of sight,
with the camera's solved azimuth, tilt, roll, focal length and lens distortion (`vigia/geometry.py`).
Fountain heights are above the vent (1,080 ± 5 m); plume tops are above sea level. Each value is the
nominal solution of a 1,000-sample Monte Carlo over the camera and vent positions, refraction, every
calibration pixel, the mask edge (±3 px) and a lean along the line of sight (5° fountains, 10°
plumes); σ is one standard deviation of the samples. The official values were never used to fit
anything.

**Rows.** A "max" row takes our highest frame inside HVO's stated window; a "mean" row averages our
frames within 5 minutes of the stated time, with σ the RMS of their sigmas (calibration errors do not
average out). "Agrees" means within 2σ, or under the bound for an "under" value.

## Heights: {agree} of {len(rows)} agree

{table(["Quantity", "Window (HST)", "Camera", "Official", "Ours", "Error", "z", "Agrees"], rows)}

## End of fountaining

The last frame on which SAM still tracks the fountain, against HVO's end at 09:03 HST (VAN 2026/H489;
the eruption table says 09:06). The cameras capture every 2 minutes.

{table(["Camera", "Last fountain detection (HST)", "Official end (HST)", "Difference"], ends)}

## Drift direction

HVO: the plume drifted to the southwest (VONA 2026/67 "MOV: SW"; winds below 20,000 ft from the
northeast). One camera sees only the drift's component across its line of sight, so each frame gives
the bearing of that side: KPcam looks southeast (134°), so its right-hand side points to 224°, almost
exactly southwest. K2cam looks south (185°); its right-hand side points to 275°.

{table(["Camera", "Frames", "Across-track side (frames)", "Most frames", "Consistent with SW"], drifts)}
"""


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Check that they run**

Run:
- `.venv/Scripts/python.exe scripts/moon_references.py --help`
- `.venv/Scripts/python.exe scripts/check_calibration.py --help`

Expected: both print their usage.

Run: `.venv/Scripts/python.exe scripts/check_calibration.py --camera kilauea-kp --at 2026-10-17T17:00Z`
Expected: exits with `preset fixed: 0 landmark(s), 0 horizon pixel(s) and no focal length cannot fix a view: ...`. Task 7 adds the references.

Run: `.venv/Scripts/python.exe scripts/validate_ep55.py --out "$TEMP/validation_check.md"`
Expected: `wrote ...`, then 7 rows ending in `no measurement` (nothing is measured yet). Open the file: the end-of-fountaining table lists kilauea-k2 at 09:02:01 (−1.0 min) and kilauea-v1 at 09:01:05 (−1.9 min); the drift table is empty.

Run: `.venv/Scripts/python.exe -m pytest` → 246 passed (scripts have no tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/moon_references.py scripts/check_calibration.py scripts/validate_ep55.py
git commit -m "Add scripts that derive Moon references, check a calibration and write the episode 55 validation"
```

---

### Task 7 (orchestrator): Calibrate KPcam from the Moon

**Files:**
- Modify: `config/calibration.yaml`

- [ ] **Step 1: Store the Moon frames.** Back them up from AshCam (public, free):
  - `vigia-backfill --camera kilauea-kp --start 2026-10-16T22:10Z --end 2026-10-16T23:20Z`
  - `vigia-backfill --camera kilauea-kp --start 2026-10-19T00:40Z --end 2026-10-19T00:50Z`
  - `vigia-backfill --camera kilauea-kp --start 2026-10-20T00:40Z --end 2026-10-20T01:20Z`

  Then list the nine frames of the Facts table with `SELECT path, captured_at FROM frames WHERE camera_id = 'kilauea-kp' AND captured_at IN (...)`.

- [ ] **Step 2: Derive the references.** Run `scripts/moon_references.py --camera kilauea-kp` with one `--frame "data/<path>@<captured_at>@<x>,<y>"` per frame, using the "Moon near pixel" column of the Facts table.

  Expected:
  - limb radius 11–14 px and misfit under 2 px on every frame;
  - for example `pixel: [695.5, 539.1], az_deg: 125.2388, el_deg: 11.4180` for 22:45Z.

  If a frame's misfit exceeds 3 px, look at its 80 px crop and drop it (haze, timestamp text).

- [ ] **Step 3: Add the references to the `fixed` preset** of `kilauea-kp` in `config/calibration.yaml`: the script's `celestial` lines, plus:

```yaml
        distortion:
          k1: 0.0
          sigma: 1.0
          source: Free; the nine Moon positions from the centre to the top-left corner measure it.
        celestial:  # scripts/moon_references.py: JPL Horizons airless position + refraction for 792 hPa
          - ...
```

- [ ] **Step 4: Check the solution.** Run `scripts/check_calibration.py --camera kilauea-kp --at 2026-10-17T17:00Z`.

  Expected:
  - RMS misfit about 1.6 px, every Moon under 5 px;
  - focal about 3,509 ± 13 px, k1 about −0.28 ± 0.01, tilt about 3.2°, field of view about 62.9°.

  Open the overlay and check by eye:
  - the vent's red circle sits within ±120 px of the fountain at (1258, 1505), the range KPcam's ±500 m position allows;
  - the cyan sea horizon lies along the base of the trade-cumulus band;
  - the altitude ticks rise above the vent.

  Record the misfit table and the view in the evidence doc (Task 9).

- [ ] **Step 5: Commit** (the freeze rule starts here for KPcam)

```bash
git add config/calibration.yaml
git commit -m "Calibrate KPcam from nine Moon positions, lens distortion included"
```

---

### Task 8 (orchestrator, time-box 45 min): Try to calibrate K2cam for fountain heights

The Facts show why the cones alone cannot fix K2cam. What is missing is a crisp sea horizon on a frame with the episode 55 framing.

- [ ] **Step 1: Find candidate frames.**
  - Backfill one K2cam AshCam frame per hour, 06:00–12:00 HST (16:00–22:00Z), for Oct 15–19. Store them in a scratch directory with a small httpx loop, as for KPcam, not in the database.
  - Keep the frames whose foreground (rows 1900–2160) registers to the Oct 17 17:00Z frame within 5 px (phase correlation). These have the episode 55 framing.

- [ ] **Step 2: Look for the sea horizon.**
  - On each kept frame, look for a sharp, straight sea/sky boundary between rows 1560 and 1610 across at least half the width.
  - The Facts predict it about 32 px (f ≈ 2,100) or 53 px (f ≈ 3,480) above the land skyline at row ≈1634.

- [ ] **Step 3: If one shows it,** pick 6+ horizon pixels spread across the width (sigma 2 px). Add to the `ep55` preset:
  - the horizon pixels;
  - the Puʻukoaʻe landmark: pixel (2992, 1629), GNIS 19.35528, −155.32235, EPQS 979 m, sigma 75 m and 15 m;
  - `distortion: {k1: 0.0, sigma: 1.0}`.

  Run `scripts/check_calibration.py --camera kilauea-k2 --at 2026-10-17T17:00Z`, then `vigia-measure --camera kilauea-k2 ...`. **Accept** only if:
  - the RMS misfit is ≤ 3 px;
  - the field of view is between 40° and 90°;
  - the median sigma of `top_height` over 14:50–15:10Z is ≤ 15 % of the median value.

  Then commit: `Calibrate K2cam from the sea horizon and Puʻukoaʻe for episode 55`.

- [ ] **Step 4: Otherwise,** leave the `ep55` preset without references. Record in the evidence doc:
  - the GNIS hypotheses and the DEM-skyline result from the Facts;
  - the frames tried and why they failed.

  The validation's fountain rows will read "no measurement".

---

### Task 9 (orchestrator): Measure, validate, document

**Files:**
- Create: `docs/research/calibration_ep55.md`, `docs/VALIDATION.md`

- [ ] **Step 1: Measure** (no Meta API spend)
  - `vigia-measure --camera kilauea-kp --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z` → `123 detections measured`
  - the same for `kilauea-k2` → measured if Task 8 succeeded; otherwise `failed: preset ep55: ... cannot fix a view`.

- [ ] **Step 2: Validate.** `.venv/Scripts/python.exe scripts/validate_ep55.py` writes `docs/VALIDATION.md`.
  - Spot-check one plume row by hand with `SELECT captured_at, value, sigma FROM measurements WHERE camera_id = 'kilauea-kp' AND metric = 'top_altitude' AND captured_at BETWEEN '2026-10-17T14:50:00Z' AND '2026-10-17T15:10:59Z'`.
  - Check the drift row: KPcam frames mostly at 224°.
  - If a row disagrees, explain it in the evidence doc. Do not change the calibration or the method to make it agree.

- [ ] **Step 3: Write `docs/research/calibration_ep55.md`** with these sections:
  - *Camera model*: pinhole plus k1, why distortion is needed (24 px misfit without it), the Monte Carlo inputs and their sigmas.
  - *KPcam from the Moon*: method (JPL airless position, refraction at 792 hPa, free-radius limb fit), the frames, the Task 7 misfit table and solved view, and the two independent checks (vent near the fountain, sea horizon on the cloud base).
  - *K2cam*: the cones and their hypotheses, the 3DEP skyline fit, the Task 8 outcome.
  - *V1cam*: why it is not calibrated (position ±150 m, pan at 05:05–05:17 HST).
  - *Not used*: B1cam and F1/KWcam (fisheye, untracked); KPcam `glow` masks as fountain heights (halo at night, incandescent core by day).
  - *Limitations*: KPcam's ±500 m position (±3.6 % on distance); plume tops include drifting cloud; lean along the line of sight assumed 5°/10°; distortion is one radial term.

- [ ] **Step 4: Commit**

```bash
git add docs/research/calibration_ep55.md docs/VALIDATION.md
git commit -m "Record the camera calibration evidence and the first episode 55 validation"
```

---

### Task 10 (orchestrator): Docs, roadmap, push, memory

**Files:**
- Modify: `README.md`, `docs/PLAN.md`

- [ ] **Step 1: README.**
  - In *Status*, replace `- [ ] Metrics (height ± σ, drift) and wind comparison` with:

```markdown
- [x] Camera geometry with lens distortion, calibrated from the Moon (KPcam); heights ± σ by Monte Carlo, area and drift per detection ([calibration](docs/research/calibration_ep55.md))
- [x] First validation against USGS episode 55 values ([VALIDATION.md](docs/VALIDATION.md))
- [ ] Wind comparison
```

  - In *Running it*, after the `vigia-track` lines, add:

```bash
vigia-measure --camera kilauea-kp --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z
                                   # heights ± σ, area and drift of the tracked objects
python scripts/validate_ep55.py    # compare with the official USGS values: docs/VALIDATION.md
```

- [ ] **Step 2: docs/PLAN.md.**
  - **Tick the Phase 3 boxes.**
    - On the *Calibration strategy* box, add: "KPcam calibrated from the Moon (JPL Horizons); B1 and F1/KW not used (fisheye, untracked)".
    - Tick `validate_ep55.py` fully only if the fountain rows were measured. Otherwise tick it with "(fountain rows pending: no K2cam calibration, see VALIDATION.md)".
  - **Module map.**
    - Mark `geometry.py` and `metrics.py` as `(exists, phase 3)`.
    - Add `calibration.py           calibration.yaml + Monte Carlo of the view (exists, phase 3)`.
    - Mark `config/calibration.yaml` as `(exists, phase 3)`.
  - *How to resume*: update the passing-test count.
  - **Facts the plan depends on**: add a **Calibration** bullet (KPcam from the Moon: focal, k1, misfit, the two checks; K2cam outcome) and a **Validation** bullet (rows that agree, end time, drift).
  - **Phase 8**: if K2cam was not calibrated, add "Calibrate a fountain camera: K2cam needs a vertical reference (sea horizon on a clear frame, a post-2018 crater DEM), or V1cam via the Moon plus resection on the vent".
  - *Budget*: unchanged (Phase 3 made no Meta API call).

- [ ] **Step 3: Final verification**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 246 passed

- [ ] **Step 4: Commit and push**

```bash
git add README.md docs/PLAN.md
git commit -m "Mark Phase 3 done: camera geometry, metrics and the first validation"
git push origin main
```

- [ ] **Step 5: Update the project memory** (`vigia-andino-status`). Record:
  - Phase 3 done and pushed;
  - the new modules and the `vigia-measure` CLI;
  - the KPcam Moon calibration numbers and the K2cam outcome;
  - the validation summary;
  - the test count;
  - next: Phase 4 (wind and agent tools).

---

## Execution notes (2026-10-28)

Tasks 1–6 were run by `implementer` subagents, which read their task text from this file by line range, and checked by `reviewer` subagents. Tasks 1+2 and 3+4 each went to one implementer, with one commit per task. All four reviews approved, with no critical or important findings. The orchestrator ran Tasks 7–10. The suite went from 190 to 247 tests. Deviations from the steps above:

1. **Monte Carlo convergence guard (`85e21ac`, after Task 5).**
   - The Task 1–2 reviewer found that a draw the solver cannot fit comes back with a huge misfit and no error, which would corrupt every sigma.
   - `sample_geometry` now raises when a sample's misfit exceeds 10 times the median plus 10 px.
   - A first version compared against the nominal misfit. It refused legitimate draws: a vent pixel is 10–30 px off when the camera moves ±500 m. The median rule fixed that.
   - It adds one test, so the suite has 247 tests, not 246.
2. **Validation report (`7d49c31`, `6730fad`).**
   - The summary heading counts only measured rows ("2 of 3 measured rows agree (4 not measured)").
   - A fixed note explains the "no measurement" rows and the drifting-cloud plume tops.
   - The script's docstring is ASCII, so `--help` prints on a cp1252 console.
3. **Task 7.** KPcam's Moon references, re-derived with the committed script on the backfilled frames, are identical to the planning values: RMS 1.64 px, focal 3,509 ± 13 px, k1 −0.280.
4. **Task 8 outcome: K2cam not calibrated.**
   - 19 hourly frames from Oct 15–19 keep the episode 55 framing, but none shows a sharp sea horizon. A faint tonal boundary near row 1612 matches neither solution.
   - The night frames of Oct 18 and 19 are black.
   - The fountain rows read "no measurement", and Phase 8 lists the fix.
5. **Results.**
   - KPcam plume top: 6,951 ± 429 m at the peak (−9 %, z −1.6); 5,169 ± 205 m at 06:02 (−0 %).
   - At 07:30: 4,416 ± 137 m, above HVO's "under 3,962 m". The mask's top is cloud downwind.
   - End of fountaining: −1.0 min (K2) and −1.9 min (V1).
   - Drift: 75 of 75 KPcam frames on the 224° side (SW).
   - No Meta API money was spent.
