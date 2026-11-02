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

from dataclasses import dataclass
from datetime import timedelta

import numpy as np
from PIL import Image

from vigil.calibration import Framing

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
