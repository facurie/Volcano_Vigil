# K2cam live preset with a framing guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure K2cam's lava fountain (and plume) live on the Space for episode 56, but only on frames that still show the framing its calibration was solved for.

**Architecture:** K2cam's only preset, `ep55`, covers Oct 17. A new preset `live` reuses ep55's references (YAML merge) from Oct 18 on, and adds `framing`: two reference frames that the episode 55 mirror already ships. `vigil/framing.py` decides per frame whether the camera kept that framing (phase correlation of the overlook's edges against a reference; on dark fountain-lit frames, the fountain's foot on the projected vent plus a confirmed frame in the last 2 h). `measure_window` skips detections on frames the guard does not confirm and counts them. No Meta API call is added.

**Tech Stack:** numpy FFT, Pillow, pydantic, SQLite; pytest.

**Decision of 2026-11-02:** the user asked whether a live K2 preset is worth building and to build it if so. Recommended because HVO forecasts episode 56 for Nov 2–9 (the video and the judging), K2cam's framing on Nov 2 matches Oct 17 within 4 px, and it costs no Meta API money.

---

## Facts measured while planning (prototype in the scratchpad, not committed)

- **Framing today.** K2cam frame 2026-11-02 20:58Z against 2026-10-17 19:28Z: shift (−1, 0) px at 960 px wide (≈ 4 px of the 4K frame), the same view.
- **Signature.** Grayscale at 960 px wide; rows below 0.80 of the height (the overlook: railings, benches, path lamps); columns 0.40–0.62 of the width zeroed (the vent projects at column 1,670 of 3,840: fountain, glow and plume live there); gradient magnitude, mean removed, 2-D Hann window. Phase correlation (cross-power spectrum normalised by its magnitude).
- **References** (both in the episode 55 mirror, so the Space has them under its data dir):
  - day: `frames/kilauea-k2/2026-10-17/20261017T192802Z_75366d46.jpg`, sha256 `75366d46129bcc0aa85aebba24ca9cb4fa2c17a6c68b2e516732d3ca3a214f72`;
  - night (path lamps, overflow glow, before the fountain): `frames/kilauea-k2/2026-10-17/20261017T123001Z_7ffa63d8.jpg`, sha256 `7ffa63d848f01209c13def7b90cb2288a680d50167dc192fcd5f7f3e6bcd0551`.
- **Rule:** a frame keeps the framing when, for either reference, the correlation's highest peak lies within ±2 analysis px of no shift and is ≥ 0.05.
- **Results of that rule:**
  - episode 55, all 210 K2 frames (12:30–19:28Z): 165 confirmed; the 45 others are 14:18–16:00Z, the brightest fountaining at night, when the fountain's light changes the whole scene;
  - 101 other frames (Oct 16, 17, 26, 27 every 30 min, and 28 Space frames Nov 1–2, day and night): 100 confirmed; the miss is a fog frame (2026-10-27 01:00Z);
  - synthetic moves of real day and night frames: shifts of (0, 12) and (24, 24) px, zooms 1.02, 1.05 and 0.97, a 400 px pan: never confirmed. A 12 px shift is sometimes confirmed (12 px is about 6 m at the fountain).
- **Fountain foot.** On the 139 ep55 frames with a K2 fountain detection, the mask's foot (middle of its lowest rows) lies from the nominal projected vent (1,669.9, 1,853.2) at median (+33, −4) px, |d| 50 % 50 px, 99 % 139 px, max 167 px. A zoom of 1.25× or a turn of 3.3° moves it more than 200 px.
- **Dark frames:** daylight frames have mean brightness ≥ 82 (of 255); night frames ≤ 50, fountain-lit ones 13–33.
- **Inheritance:** frames 14:18–16:00Z follow a confirmed frame at 14:16Z, so a 2 h window with the foot check keeps the peak (04:50–05:10 HST) measured.
- **South vent:** 94 m south of the north vent, almost along K2's sightline (bearing ≈ 185°, range 1,678 → 1,772 m). A fountain from it would read about 6 % low (inside σ ≈ 9 %). It was buried by tephra in episode 55.

## File map

- Create `vigil/framing.py`: signature, match, foot, `FramingGuard`.
- Modify `vigil/calibration.py`: `FramingReference`, `Framing`, `Preset.framing`.
- Modify `vigil/metrics.py`: `measure_window(..., data_dir=None)`, `MeasureReport.unconfirmed`, the CLI passes `settings.data_dir`.
- Modify `vigil/pipeline.py:204` and `vigil/agent/tools.py:504`: pass `data_dir`.
- Modify `config/calibration.yaml`: anchor on K2's ep55 preset, new preset `live`.
- Tests: create `tests/test_framing.py`; modify `tests/conftest.py` (`make_textured_jpeg`), `tests/test_metrics.py`, `tests/test_pipeline.py`, `tests/test_agent_tools.py`, `tests/test_calibration.py`.
- Docs: `docs/research/calibration_ep55.md` (new section), `README.md`, `docs/PLAN.md`.

---

### Task 1: The framing check (`vigil/framing.py` and the config schema)

**Files:**
- Modify: `vigil/calibration.py` (after `class Roll`, and `class Preset`)
- Create: `vigil/framing.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_framing.py`

- [ ] **Step 1: Add the textured JPEG helper to `tests/conftest.py`** (next to `make_noisy_jpeg`):

```python
def make_textured_jpeg(seed=0, size=(960, 540), shift=(0, 0), zoom=1.0, brightness=1.0) -> bytes:
    """A JPEG of smooth random texture, the same for the same seed; `shift` (columns, rows) rolls it, `zoom`
    enlarges it about its centre, `brightness` scales it (a dark frame below about 0.45)."""
    rng = np.random.default_rng(seed)
    width, height = size
    texture = Image.fromarray((rng.random((height, width)) * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(2))
    pixels = np.roll(np.asarray(texture, dtype=np.float32), (shift[1], shift[0]), axis=(0, 1))
    image = Image.fromarray(np.clip(pixels * brightness, 0, 255).astype(np.uint8))
    if zoom != 1.0:
        cw, ch = width / zoom, height / zoom
        left, top = (width - cw) / 2, (height - ch) / 2
        image = image.transform(size, Image.EXTENT, (left, top, left + cw, top + ch), Image.BILINEAR)
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=92)
    return buf.getvalue()
```

Add `import numpy as np` and `from PIL import ImageFilter` to conftest's imports if missing (it already imports `Image` and `io`).

- [ ] **Step 2: Write the failing tests `tests/test_framing.py`** (pure functions first; the guard comes in Task 2):

```python
import io

import numpy as np
import pytest
from PIL import Image

from conftest import make_textured_jpeg
from vigil.calibration import Framing, FramingReference
from vigil.framing import MAX_SHIFT, MIN_PEAK, foot, match, signature

FRAMING = Framing(references=[FramingReference(path="refs/day.jpg", sha256="0" * 64)], rows_from=0.5,
                  skip_columns=(0.4, 0.6))


def image(**kwargs):
    return Image.open(io.BytesIO(make_textured_jpeg(**kwargs)))


def compare(reference, frame):
    return match(signature(reference, FRAMING)[0], signature(frame, FRAMING)[0])


def test_a_frame_keeps_its_own_framing():
    found = compare(image(seed=1), image(seed=1))

    assert found.same and (found.dx, found.dy) == (0, 0) and found.peak > 0.5


def test_a_shift_within_max_shift_keeps_the_framing():
    assert compare(image(seed=1), image(seed=1, shift=(MAX_SHIFT, -1))).same


def test_a_shift_beyond_max_shift_does_not_and_is_measured():
    found = compare(image(seed=1), image(seed=1, shift=(0, 6)))

    assert not found.same
    assert abs(found.dy) == 6 and found.dx == 0


@pytest.mark.parametrize("zoom", [1.05, 0.95])
def test_a_zoom_does_not_keep_the_framing(zoom):
    assert not compare(image(seed=1), image(seed=1, zoom=zoom)).same


def test_another_scene_does_not_keep_the_framing():
    found = compare(image(seed=1), image(seed=2))

    assert not found.same and found.peak < MIN_PEAK


def test_rows_above_rows_from_and_the_skipped_columns_are_left_out():
    reference = np.asarray(image(seed=1)).copy()
    frame = reference.copy()
    frame[:250] = 255                    # the sky: above rows_from (0.5 of 540 rows)
    frame[300:, 400:560] = 0             # inside skip_columns (0.4-0.6 of 960 columns): the vent
    found = match(signature(Image.fromarray(reference), FRAMING)[0], signature(Image.fromarray(frame), FRAMING)[0])

    assert found.same and found.peak > 0.5


def test_signature_gives_the_mean_brightness():
    _, bright = signature(image(seed=1, brightness=0.2), FRAMING)

    assert 15 < bright < 35


def test_a_masks_foot_is_the_middle_of_its_lowest_rows():
    mask = np.zeros((50, 40), dtype=bool)
    mask[0:50, 18:22] = True             # the jet
    mask[48:50, 10:30] = True            # its spreading base

    assert foot(mask, left=100, top=200).tolist() == pytest.approx([100 + 19.5, 200 + 49])


def test_an_empty_mask_has_no_foot():
    assert foot(np.zeros((5, 5), dtype=bool), 0, 0) is None
```

- [ ] **Step 3: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_framing.py`
Expected: ImportError (`Framing`, `vigil.framing` do not exist).

- [ ] **Step 4: Add the config models to `vigil/calibration.py`** (after `class Roll`):

```python
class FramingReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str     # relative to the data dir: a frame with the preset's framing (the episode mirror ships it)
    sha256: str   # of that file, so a different frame never stands in for it
    note: str = ""


class Framing(BaseModel):
    """Frames that show a pan-tilt-zoom preset's framing, for checking that later frames still do (vigil.framing)."""

    model_config = ConfigDict(extra="forbid")

    references: list[FramingReference] = Field(min_length=1)
    rows_from: float = Field(gt=0, lt=1)   # compare only the rows below this fraction of the height
    skip_columns: tuple[float, float]      # and leave out these fractions of the width (where the vent is)
    source: str = ""
```

and in `class Preset`, after `roll`:

```python
    framing: Framing | None = None               # set on a PTZ preset used live: frames must show its framing
```

Also add one sentence to the module docstring after "...each valid for a span of capture times.": "A preset kept for live use on a pan-tilt-zoom camera also lists reference frames of its framing, and only frames that still show it are measured (vigil.framing)."

- [ ] **Step 5: Create `vigil/framing.py`** with the pure functions (the guard follows in Task 2):

```python
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
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_framing.py`
Expected: all pass. If `test_signature_gives_the_mean_brightness` misses its range, print the value and fix the test's range only if the texture's mean (≈ 127 × 0.2) explains it.

- [ ] **Step 7: Run the full suite, then commit**

```bash
.venv/Scripts/python.exe -m pytest
git add vigil/framing.py vigil/calibration.py tests/conftest.py tests/test_framing.py
git commit -m "Add a framing check that tells whether a pan-tilt-zoom frame still shows its preset's framing"
```

---

### Task 2: The guard over stored frames (`FramingGuard`)

**Files:**
- Modify: `vigil/framing.py`
- Modify: `tests/test_framing.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_framing.py`):

```python
import hashlib
import json
from datetime import datetime, timedelta, timezone

from vigil import masks
from vigil.calibration import Preset
from vigil.framing import FOOT_PX, FramingGuard
from vigil.ingest.store import FrameStore
from vigil.timeutil import to_iso

T0 = datetime(2026, 11, 3, 14, 0, 2, tzinfo=timezone.utc)
VENT = np.array([480.0, 500.0])
CAMERA = "kilauea-k2"


def live_preset(tmp_path, references=(("refs/day.jpg", 1, 1.0), ("refs/night.jpg", 1, 0.15))):
    refs = []
    for path, seed, brightness in references:
        data = make_textured_jpeg(seed=seed, brightness=brightness)
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(data)
        refs.append(FramingReference(path=path, sha256=hashlib.sha256(data).hexdigest()))
    return Preset(name="live", valid_from="2026-10-18T00:00:00Z", image_size=(960, 540),
                  framing=Framing(references=refs, rows_from=0.5, skip_columns=(0.4, 0.6)))


@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def add_frame(conn, store, minutes, **texture):
    captured_at = T0 + timedelta(minutes=minutes)
    frame_id = store.add(CAMERA, make_textured_jpeg(**texture), captured_at=captured_at, timestamp_source="ashcam",
                         fetched_at=captured_at)
    return conn.execute("SELECT * FROM frames WHERE id = ?", (frame_id,)).fetchone()


def add_fountain(conn, frame, foot_at):
    """A fountain detection on the frame whose foot is at `foot_at` (column, row)."""
    left, bottom = int(foot_at[0]) - 10, int(foot_at[1])
    mask = np.ones((100, 21), dtype=bool)
    with conn:
        run_id = conn.execute(
            """INSERT INTO tracking_runs (camera_id, target, phrase, window_start, window_end, frame_ids,
                                          video_width, video_height, created_at)
               VALUES (?, 'fountain', 'lava fountain', ?, ?, ?, 960, 540, '2026-11-03T15:00:00Z')""",
            (CAMERA, frame["captured_at"], frame["captured_at"], json.dumps([frame["id"]]))).lastrowid
        track_id = conn.execute(
            "INSERT INTO tracks (run_id, object_id, first_seen, last_seen, detections) VALUES (?, '0', ?, ?, 1)",
            (run_id, frame["captured_at"], frame["captured_at"])).lastrowid
        conn.execute(
            """INSERT INTO detections (track_id, frame_id, box_left, box_top, box_right, box_bottom, score, area_px,
                                       mask_rle) VALUES (?, ?, ?, ?, ?, ?, 0.8, ?, ?)""",
            (track_id, frame["id"], left, bottom - 99, left + 21, bottom + 1, int(mask.sum()),
             json.dumps(masks.encode(mask))))


def guard(conn, tmp_path):
    return FramingGuard(conn, tmp_path, CAMERA)


def test_a_daylight_frame_of_the_reference_scene_keeps_the_framing(conn, store, tmp_path):
    frame = add_frame(conn, store, 0, seed=1)

    assert guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_dark_frame_matching_the_night_reference_keeps_the_framing(conn, store, tmp_path):
    frame = add_frame(conn, store, 0, seed=1, brightness=0.15)

    assert guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_moved_daylight_frame_does_not_even_with_a_fountain_on_the_vent(conn, store, tmp_path):
    add_frame(conn, store, -10, seed=1)
    frame = add_frame(conn, store, 0, seed=1, shift=(0, 20))
    add_fountain(conn, frame, VENT)

    assert not guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_dark_unmatched_frame_with_the_fountain_on_the_vent_follows_a_confirmed_frame(conn, store, tmp_path):
    add_frame(conn, store, -90, seed=1)                       # confirmed, 1.5 h before
    frame = add_frame(conn, store, 0, seed=7, brightness=0.15)  # the fountain's light: no reference matches
    add_fountain(conn, frame, VENT + (30, -5))

    assert guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_confirmed_frame_older_than_inherit_does_not_vouch(conn, store, tmp_path):
    add_frame(conn, store, -130, seed=1)                      # 2 h 10 min before
    frame = add_frame(conn, store, 0, seed=7, brightness=0.15)
    add_fountain(conn, frame, VENT)

    assert not guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_confirmed_frame_after_the_frame_does_not_vouch(conn, store, tmp_path):
    frame = add_frame(conn, store, 0, seed=7, brightness=0.15)
    add_fountain(conn, frame, VENT)
    add_frame(conn, store, 10, seed=1)                        # later than the frame: never looked at

    assert not guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_fountain_foot_off_the_vent_does_not_keep_the_framing(conn, store, tmp_path):
    add_frame(conn, store, -30, seed=1)
    frame = add_frame(conn, store, 0, seed=7, brightness=0.15)
    add_fountain(conn, frame, VENT + (FOOT_PX + 20, 0))

    assert not guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_dark_unmatched_frame_without_a_fountain_does_not_keep_the_framing(conn, store, tmp_path):
    add_frame(conn, store, -30, seed=1)
    frame = add_frame(conn, store, 0, seed=7, brightness=0.15)

    assert not guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)


def test_a_missing_reference_frame_is_an_error(conn, store, tmp_path):
    preset = live_preset(tmp_path)
    (tmp_path / "refs/night.jpg").unlink()

    with pytest.raises(ValueError, match="refs/night.jpg"):
        guard(conn, tmp_path).keeps(preset, add_frame(conn, store, 0, seed=1), VENT)


def test_a_reference_frame_with_another_hash_is_an_error(conn, store, tmp_path):
    preset = live_preset(tmp_path)
    (tmp_path / "refs/day.jpg").write_bytes(make_textured_jpeg(seed=3))

    with pytest.raises(ValueError, match="refs/day.jpg"):
        guard(conn, tmp_path).keeps(preset, add_frame(conn, store, 0, seed=1), VENT)


def test_a_missing_frame_file_does_not_keep_the_framing(conn, store, tmp_path):
    frame = add_frame(conn, store, 0, seed=1)
    (tmp_path / frame["path"]).unlink()

    assert not guard(conn, tmp_path).keeps(live_preset(tmp_path), frame, VENT)
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_framing.py`
Expected: ImportError on `FramingGuard`.

- [ ] **Step 3: Add the guard to `vigil/framing.py`** (imports: `hashlib`, `io`, `json`, `sqlite3`, `from pathlib import Path`, `from vigil import masks`, `from vigil.calibration import Framing, Preset`, `from vigil.timeutil import parse_utc, to_iso`):

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_framing.py`
Expected: all pass.

- [ ] **Step 5: Run the full suite, then commit**

```bash
.venv/Scripts/python.exe -m pytest
git add vigil/framing.py tests/test_framing.py
git commit -m "Confirm a stored frame's framing against the references, and let a fountain on the vent carry a dark frame for 2 h"
```

---

### Task 3: Measure only confirmed frames (`measure_window`, pipeline, agent, CLI)

**Files:**
- Modify: `vigil/metrics.py` (`MeasureReport`, `measure_window`, `main`)
- Modify: `vigil/pipeline.py:204`, `vigil/agent/tools.py:504-510`
- Modify: `tests/test_metrics.py`, `tests/test_pipeline.py`, `tests/test_agent_tools.py`

- [ ] **Step 1: Write the failing tests.**

In `tests/test_metrics.py`: give `add_detection` a `jpeg=None` parameter (`store.add("kilauea-kp", jpeg or make_jpeg(...), ...)`), give `kp_calibration` a `framing=None` parameter passed to `Preset(..., framing=framing)`, import `make_textured_jpeg`, `hashlib`, `Framing`, `FramingReference`, and add:

```python
def kp_framing(tmp_path):
    data = make_textured_jpeg(seed=1, size=SIZE)
    (tmp_path / "refs").mkdir(exist_ok=True)
    (tmp_path / "refs/kp.jpg").write_bytes(data)
    return Framing(references=[FramingReference(path="refs/kp.jpg", sha256=hashlib.sha256(data).hexdigest())],
                   rows_from=0.5, skip_columns=(0.45, 0.55))


def test_a_preset_with_framing_measures_only_frames_that_keep_it(conn, store, tmp_path):
    kept = add_detection(conn, store, 0, jpeg=make_textured_jpeg(seed=1, size=SIZE))
    moved = add_detection(conn, store, 5, jpeg=make_textured_jpeg(seed=1, size=SIZE, shift=(0, 12)))

    report = window(conn, kp_calibration(framing=kp_framing(tmp_path)), data_dir=tmp_path)

    assert (report.measured, report.unconfirmed, report.errors) == (1, 1, [])
    assert stored(conn, kept) and not stored(conn, moved)
    assert "1 on frames whose framing is not confirmed" in report.summary()


def test_a_preset_with_framing_measures_nothing_without_the_data_dir(conn, store, tmp_path):
    add_detection(conn, store, 0, jpeg=make_textured_jpeg(seed=1, size=SIZE))

    report = window(conn, kp_calibration(framing=kp_framing(tmp_path)))

    assert (report.measured, report.unconfirmed) == (0, 1)
    assert report.errors == ["preset fixed: its framing cannot be checked without the frames' data dir"]


def test_a_missing_reference_frame_is_reported_once(conn, store, tmp_path):
    framing = kp_framing(tmp_path)
    (tmp_path / "refs/kp.jpg").unlink()
    add_detection(conn, store, 0, jpeg=make_textured_jpeg(seed=1, size=SIZE))
    add_detection(conn, store, 5, jpeg=make_textured_jpeg(seed=1, size=SIZE))

    report = window(conn, kp_calibration(framing=framing), data_dir=tmp_path)

    assert (report.measured, report.unconfirmed) == (0, 2)
    assert len(report.errors) == 1 and "refs/kp.jpg" in report.errors[0]
```

In `tests/test_pipeline.py`: make `Fakes.measure` accept and record `data_dir=None` (e.g. append it to a `self.measure_data_dirs` list), and add a test that a step which measures passes the pipeline's data dir (find the existing test that asserts a measure happened and reuse its setup; assert the recorded data dir equals the `tmp_path`-based data dir the pipeline was built with).

In `tests/test_agent_tools.py`: add a test that `measure_track` passes `ctx.data_dir` to `measure_window` (monkeypatch `vigil.agent.tools.measure_window` with a fake that records its kwargs and returns a `MeasureReport`, reusing the setup of an existing `measure_track` test), and one that a track whose detections all lie on unconfirmed frames raises a `ToolError` saying "framing" (fake returns `MeasureReport(camera_id, unconfirmed=3)` and no measurements are stored).

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_metrics.py tests/test_pipeline.py tests/test_agent_tools.py`
Expected: the new tests fail (`unexpected keyword argument 'data_dir'`, no `unconfirmed`).

- [ ] **Step 3: Implement in `vigil/metrics.py`.**

`MeasureReport` gets `unconfirmed: int = 0  # detections on frames that may not show their preset's framing (vigil.framing)`, and `summary` appends `f", {self.unconfirmed} on frames whose framing is not confirmed"` to the first line only when `self.unconfirmed` is non-zero (so existing summaries stay word for word).

`measure_window` gets `data_dir: str | Path | None = None` (import `Path` from `pathlib`, `FramingGuard` from `vigil.framing`); its docstring gains: "A preset with `framing` (a pan-tilt-zoom camera's live preset) measures only frames that still show its framing (vigil.framing), which needs the frames' `data_dir`; the other detections are counted as unconfirmed." The query also selects `f.path`. After `geometry` is known to be not None and before `measure_mask`:

```python
        if preset.framing is not None:
            if row["frame_id"] not in kept:
                kept[row["frame_id"]] = _keeps_framing(guard, preset, row, geometry, report)
            if not kept[row["frame_id"]]:
                report.unconfirmed += 1
                continue
```

with, before the loop, `guard = FramingGuard(conn, data_dir, camera_id) if data_dir is not None else None` and `kept: dict[int, bool] = {}`, and at module level:

```python
def _keeps_framing(guard: FramingGuard | None, preset: Preset, row: sqlite3.Row, geometry: Geometry,
                   report: MeasureReport) -> bool:
    """Whether the detection's frame shows the preset's framing; a reason it cannot be told goes to the report
    once per preset."""
    if guard is None:
        problem = f"preset {preset.name}: its framing cannot be checked without the frames' data dir"
    else:
        vent_pixel = geometry.view.project(geometry.vent[:, None, :])[0, 0]
        frame = {"id": row["frame_id"], "path": row["path"], "captured_at": row["captured_at"]}
        try:
            return guard.keeps(preset, frame, vent_pixel)
        except ValueError as exc:
            problem = str(exc)
    if problem not in report.errors:
        report.errors.append(problem)
    return False
```

(`FramingGuard.keeps` reads `frame["id"]`, `frame["path"]`, `frame["captured_at"]`, so a dict works; import `Preset` from `vigil.calibration`.)

`main` passes `data_dir=settings.data_dir`.

- [ ] **Step 4: Pass the data dir from the callers.**

`vigil/pipeline.py:204`: `self._measure(ctx.conn, ctx.calibration, camera.id, start, end, data_dir=ctx.data_dir)`.

`vigil/agent/tools.py:504`: `measure_window(ctx.conn, ctx.calibration, camera_id, parse_utc(span["first"]), parse_utc(span["last"]), data_dir=ctx.data_dir)`, and the "could not be measured" problems become:

```python
        problems = report.errors or [
            f"{report.unconfirmed} detections lie on frames that may not show the calibrated framing (the camera "
            "may have moved)" if report.unconfirmed else
            f"{report.uncalibrated} detections lie on frames no calibration preset covers"]
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_metrics.py tests/test_pipeline.py tests/test_agent_tools.py`
Expected: all pass.

- [ ] **Step 6: Run the full suite, then commit**

```bash
.venv/Scripts/python.exe -m pytest
git add vigil/metrics.py vigil/pipeline.py vigil/agent/tools.py tests/test_metrics.py tests/test_pipeline.py tests/test_agent_tools.py
git commit -m "Measure a live pan-tilt-zoom preset only on frames that keep its framing, and say why the others are skipped"
```

---

### Task 4: K2cam's live preset in the config

**Files:**
- Modify: `config/calibration.yaml` (K2's presets)
- Modify: `tests/test_calibration.py`

- [ ] **Step 1: Write the failing test** in `tests/test_calibration.py` (next to the test that loads the real config, `REPO` is defined there):

```python
def test_k2cams_live_preset_reuses_ep55s_view_and_checks_its_framing():
    calibration = load_calibration(REPO / "config" / "calibration.yaml")
    ep55 = calibration.preset_for("kilauea-k2", datetime(2026, 10, 17, 15, tzinfo=timezone.utc))
    live = calibration.preset_for("kilauea-k2", datetime(2026, 11, 3, 15, tzinfo=timezone.utc))

    assert (ep55.name, ep55.framing) == ("ep55", None)
    assert (live.name, live.valid_from, live.valid_until) == (
        "live", datetime(2026, 10, 18, tzinfo=timezone.utc), None)
    assert (live.fov, live.roll, live.distortion, live.landmarks, live.image_size) == (
        ep55.fov, ep55.roll, ep55.distortion, ep55.landmarks, ep55.image_size)
    assert [r.path for r in live.framing.references] == [
        "frames/kilauea-k2/2026-10-17/20261017T192802Z_75366d46.jpg",
        "frames/kilauea-k2/2026-10-17/20261017T123001Z_7ffa63d8.jpg"]
    assert (live.framing.rows_from, live.framing.skip_columns) == (0.80, (0.40, 0.62))
```

(Add `from datetime import datetime, timezone` if the file lacks it.)

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calibration.py -k live`
Expected: FAIL (`preset_for` returns None for Nov 3).

- [ ] **Step 3: Edit `config/calibration.yaml`.** Put the anchor `&k2_ep55` on K2's ep55 preset item (`- &k2_ep55` then `name: ep55` on the next line, indented as now; no value of ep55 changes), and append after it:

```yaml
      - <<: *k2_ep55   # the same references and priors: the framing has not changed since episode 55
        name: live
        valid_from: "2026-10-18T00:00:00Z"
        valid_until: null
        framing:
          references:
            - path: frames/kilauea-k2/2026-10-17/20261017T192802Z_75366d46.jpg
              sha256: 75366d46129bcc0aa85aebba24ca9cb4fa2c17a6c68b2e516732d3ca3a214f72
              note: Daylight, 09:28 HST after episode 55; matches daylight frames.
            - path: frames/kilauea-k2/2026-10-17/20261017T123001Z_7ffa63d8.jpg
              sha256: 7ffa63d848f01209c13def7b90cb2288a680d50167dc192fcd5f7f3e6bcd0551
              note: Night, 02:30 HST before episode 55, lit by the path lamps; matches dark frames.
          rows_from: 0.80
          skip_columns: [0.40, 0.62]
          source: >-
            Both frames ship in the episode 55 mirror (frames/**). The compared rows hold the overlook in the
            foreground; the left-out columns 1,536-2,381 hold the vent (projected at column 1,670), its fountain,
            glow and plume. Calibrated on K2cam's frames of Oct 16 to Nov 2 (docs/research/calibration_ep55.md).
        note: >-
          Live use from Oct 18. A frame is measured only while it shows ep55's framing (vigil.framing); K2cam's
          frame of Nov 2 20:58Z registers within 4 px of Oct 17.
```

Check first that both files exist under `data/` and that their SHA-256 matches (`python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" data/frames/...`); if ep55's preset has its own `note`, the live one overrides it as above.

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calibration.py`
Expected: pass. Also run `.venv/Scripts/python.exe -m pytest tests/test_agent_tools.py tests/test_web_*.py` in case a test assumed K2 uncalibrated after Oct 18 with the real config; such a test must keep its intent (use a time before Oct 17 or the synthetic calibration), never be deleted.

- [ ] **Step 5: Run the full suite, then commit**

```bash
.venv/Scripts/python.exe -m pytest
git add config/calibration.yaml tests/test_calibration.py
git commit -m "Give K2cam a live preset from Oct 18 that reuses episode 55's view and checks every frame's framing"
```

---

### Task 5: Check on real frames, document, deploy (main session)

- [ ] Run the guard over the replay's 210 K2 frames of episode 55 with the `live` preset's framing (a scratchpad script using `FramingGuard` with the replay DB and `data/`), and over a sample of the Space's frames since Nov 1, and write the counts into a new section of `docs/research/calibration_ep55.md` ("K2cam live: the framing guard"), with the facts above (references, rule, synthetic moves, foot offsets, the south vent's −6 %).
- [ ] README "Measuring a height": one sentence that live K2cam heights are measured only on frames that still show the calibrated framing. `docs/PLAN.md`: a line under Phase 9's facts that the live K2 preset was added on 2026-11-02 after the phase.
- [ ] Raise the Space's cap (user's OK of 2026-11-02, $138 left): `Dockerfile` `DAILY_BUDGET_USD=8`; `docs/DEPLOY.md` (lines 27, 95 and "Costs") and README "Cost" say $8, of which $0.75 for the alerts.
- [ ] Suite green; push; `vigil-space deploy`; check in the Space log that the pipeline measures K2 windows ("kilauea-k2: N detections measured") without a framing error, and that the dashboard's K2 tab shows a readout.
- [ ] Execution notes at the end of this plan; memory.
