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
vigil.calibration re-solves every perturbed sample at once.
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
