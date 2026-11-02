"""Whether a frame still shows the framing its pan-tilt-zoom camera's preset was solved for.

A preset's view (vigil.calibration) holds only while the camera stays put, and K2cam is a pan-tilt-zoom camera
with no readout on its frames. A preset with `framing` names reference frames of its framing. A frame keeps it
when the gradient magnitude of its lowest rows (the overlook's railings, benches and path lamps, with the
columns around the vent left out), at ANALYSIS_WIDTH px wide, phase-correlates with a reference's with the
highest peak within MAX_SHIFT px of no shift and at least MIN_PEAK high. A day reference confirms daylight
frames and a night one, lit by the path lamps, dark ones. Calibrated on K2cam's frames from Oct 16 to Nov 2
(docs/research/calibration_ep55.md): no shift of 24 px, zoom of 2 % or more, or turn tried there is confirmed.

On the brightest fountaining nights the fountain's light changes the whole scene and no reference matches. A
dark frame is then measured when a frame of the INHERIT before it was confirmed and a lava fountain's foot on
it stands within FOOT_PX px of the vent's projection, which a zoom or a turn large enough to matter moves away.
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np
from PIL import Image

from vigil import masks
from vigil.calibration import Framing, Preset
from vigil.timeutil import parse_utc, to_iso

ANALYSIS_WIDTH = 960          # px; one analysis pixel is 4 px of a 3840 px frame
MAX_SHIFT = 2                 # analysis px: 8 px of a 4K frame, about 4 m at K2cam's fountain
MIN_PEAK = 0.05               # unrelated K2cam frames peak below 0.04
DARK = 60.0                   # mean brightness (0-255) under which a frame is dark; daylight frames are over 80
INHERIT = timedelta(hours=2)  # how long a confirmed frame vouches for the dark frames after it
FOOT_PX = 200.0               # frame px from a fountain's foot to the vent's projection; episode 55: at most 167


@dataclass(frozen=True)
class Match:
    dx: int       # shift between the frame and the reference, analysis px
    dy: int
    peak: float   # height of the phase correlation's highest peak; 1 for identical signatures

    @property
    def same(self) -> bool:
        return abs(self.dx) <= MAX_SHIFT and abs(self.dy) <= MAX_SHIFT and self.peak >= MIN_PEAK


def signature(image: Image.Image, framing: Framing) -> tuple[np.ndarray, float]:
    """The windowed gradient magnitude of the frame's compared rows and columns at ANALYSIS_WIDTH px, and the
    frame's mean brightness (0-255)."""
    width, height = image.size
    small = image.convert("L").resize((ANALYSIS_WIDTH, round(ANALYSIS_WIDTH * height / width)), Image.BILINEAR)
    gray = np.asarray(small, dtype=np.float32)
    gy, gx = np.gradient(gray[int(gray.shape[0] * framing.rows_from):])
    edges = np.hypot(gx, gy)
    left, right = (int(ANALYSIS_WIDTH * f) for f in framing.skip_columns)
    edges[:, left:right] = 0
    edges -= edges.mean()
    return edges * np.outer(np.hanning(edges.shape[0]), np.hanning(edges.shape[1])), float(gray.mean())


def match(reference: np.ndarray, frame: np.ndarray) -> Match:
    """Phase-correlate two signatures of the same size: where the highest peak lies, and how high it is."""
    cross = np.fft.fft2(reference) * np.conj(np.fft.fft2(frame))
    surface = np.fft.ifft2(cross / (np.abs(cross) + 1e-6)).real
    row, col = np.unravel_index(surface.argmax(), surface.shape)
    dy = row if row <= surface.shape[0] // 2 else row - surface.shape[0]
    dx = col if col <= surface.shape[1] // 2 else col - surface.shape[1]
    return Match(int(dx), int(dy), float(surface.max()))


def foot(mask: np.ndarray, left: int, top: int) -> np.ndarray | None:
    """The middle of a box-sized mask's lowest rows, as (column, row) in frame pixels: a fountain's foot."""
    rows, cols = np.nonzero(mask)
    if not rows.size:
        return None
    bottom = rows.max()
    base = cols[rows >= bottom - max(2, int(0.02 * (bottom - rows.min())))]
    return np.array([left + base.mean(), top + bottom], dtype=float)


class FramingGuard:
    """Decides frame by frame whether one camera kept a preset's framing, caching every comparison."""

    def __init__(self, conn: sqlite3.Connection, data_dir: str | Path, camera_id: str):
        self._conn, self._data_dir, self._camera_id = conn, Path(data_dir), camera_id
        self._references: dict[str, list[np.ndarray]] = {}       # per preset name
        self._compared: dict[int, tuple[bool, float]] = {}        # per frame id: confirmed, mean brightness

    def keeps(self, preset: Preset, frame: sqlite3.Row, vent_pixel: np.ndarray) -> bool:
        """Whether the frame (a `frames` row) still shows the preset's framing; `vent_pixel` is the vent's
        projection in the preset's view. Raises ValueError when a reference frame is missing or another file."""
        confirmed, bright = self._compare(preset, frame["id"], frame["path"])
        if confirmed:
            return True
        if bright >= DARK:
            return False
        feet = [foot(masks.decode(json.loads(row["mask_rle"])), row["box_left"], row["box_top"])
                for row in self._conn.execute(
                    """SELECT d.mask_rle, d.box_left, d.box_top FROM detections d
                       JOIN tracks t ON t.id = d.track_id JOIN tracking_runs r ON r.id = t.run_id
                       WHERE d.frame_id = ? AND r.target = 'fountain'""", (frame["id"],))]
        if not any(f is not None and np.hypot(*(f - vent_pixel)) <= FOOT_PX for f in feet):
            return False
        earlier = self._conn.execute(
            "SELECT id, path FROM frames WHERE camera_id = ? AND captured_at >= ? AND captured_at < ? "
            "ORDER BY captured_at DESC",
            (self._camera_id, to_iso(parse_utc(frame["captured_at"]) - INHERIT), frame["captured_at"])).fetchall()
        return any(self._compare(preset, row["id"], row["path"])[0] for row in earlier)

    def _compare(self, preset: Preset, frame_id: int, path: str) -> tuple[bool, float]:
        if frame_id not in self._compared:
            references = self._signatures(preset)
            try:
                with Image.open(self._data_dir / path) as image:
                    frame, bright = signature(image, preset.framing)
            except OSError:
                self._compared[frame_id] = (False, 255.0)  # a frame that cannot be read confirms nothing
            else:
                self._compared[frame_id] = (any(match(r, frame).same for r in references), bright)
        return self._compared[frame_id]

    def _signatures(self, preset: Preset) -> list[np.ndarray]:
        if preset.name not in self._references:
            signatures = []
            for reference in preset.framing.references:
                try:
                    data = (self._data_dir / reference.path).read_bytes()
                except OSError:
                    raise ValueError(f"preset {preset.name}: reference frame {reference.path} is missing "
                                     f"from {self._data_dir}") from None
                if hashlib.sha256(data).hexdigest() != reference.sha256:
                    raise ValueError(f"preset {preset.name}: {reference.path} is not the reference frame it names")
                with Image.open(io.BytesIO(data)) as image:
                    if image.size != tuple(preset.image_size):
                        raise ValueError(f"preset {preset.name}: reference frame {reference.path} is "
                                         f"{image.size[0]}x{image.size[1]}, not the preset's size")
                    signatures.append(signature(image, preset.framing)[0])
            self._references[preset.name] = signatures
        return self._references[preset.name]
