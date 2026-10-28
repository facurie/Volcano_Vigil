# Phase 2: Quality Gate and Timelapse Tracking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Judge every stored frame for free with local checks (stale, frozen, dark night, fog) and ask Muse Spark only about the frames those checks cannot decide; then track plumes, fountains and incandescence with SAM 3.1 video over timelapses of the usable frames, storing runs, tracks and per-frame detections (box, score, area, COCO RLE mask) for episode 55 V1/K2/KP.

**Architecture:** `vigia/quality.py` holds the pure local measurements and decision rules, calibrated on real frames; `vigia/sun.py` gives the sun's elevation for the night check; `vigia/gate.py` runs the checks per frame, calls Muse Spark through `MetaClient` for hazy frames, and stores one `frame_quality` row per frame (`vigia-quality` CLI). `vigia/tracking.py` selects a camera's usable frames in a window, encodes them into one MP4, uploads it once, runs SAM video once per phrase of `config/prompts.yaml` and stores `tracking_runs`, `tracks` and `detections` in the frames' own pixel coordinates (`vigia-track` CLI). `vigia/masks.py` encodes masks as COCO RLE.

**Tech Stack:** Python 3.12, Pillow, numpy, SQLite, ffmpeg (`vigia/video.py`), OpenAI SDK against the Meta Model API through `MetaClient` (`muse-spark-1.3`, `sam-3.1`), `meta-sam-parser`, pytest with `httpx.MockTransport` fakes.

**Spec:** Phase 2 of [docs/PLAN.md](../../PLAN.md).

---

## Facts this plan relies on (measured 2026-10-27)

**Calibration frames.** Episode 55 (2026-10-17 13:00–19:30Z: KP 78, K2 195, V1 195) plus three windows backfilled from AshCam for this plan:
- a foggy afternoon, 2026-10-26 22:00Z – 2026-10-27 02:00Z (12:00–16:00 HST): V1 120, K2 120, KP 48 frames;
- a quiet night (no eruption, full moon), 2026-10-27 06:00–08:00Z (20:00–22:00 HST): V1 60, K2 60, KP 24;
- a clear quiet morning, 2026-10-27 16:00–19:00Z (06:50–08:55 HST, live frames): K2 60, KP 24.

The V1 fog frame of the smoke test is `frames/kilauea-v1/2026-10-27/20261027T000902Z_8d8e4205.jpg` (14:09 HST).

**What the frames look like.**
- USGS frames print the HST time at the top left, the USGS logo at the bottom left and, on PTZ cameras, the readout at the bottom right (`P: 29, T: +0.00, Z: 29 1.0`). They sit in the top 5 % and bottom 8 % of the height.
- At night KPcam switches to monochrome. Episode 55 incandescence then shows as saturated white, not orange. K2 renders the fountain as saturated bluish white. V1 keeps the lava orange with luminance under 200. A detector that relies only on colour, or only on brightness, misses one of them.
- K2 lights a row of yellow path lamps at night. Its quiet-night frames also show a real small glow of the north vent, as does V1's 9.6× view of the vent.
- In K2 fog the foreground trees and platform stay sharp while the crater is hidden. On overcast days KP keeps its vegetation sharp while the summit 14 km away is hidden. A quiet clear day at K2 is mostly smooth sky and a soft gas plume.

**Measurements** (definitions in Task 2: edge density = share of pixels with a luminance step > 8 per pixel on a blurred copy ≤ 512 px; glow = share of a block-averaged copy ≤ 256 px that is warm-bright or near-white; change = mean absolute luminance difference of 128-px fingerprints):

| condition | edge density | glow | change from the previous frame |
|---|---|---|---|
| dense fog, day (V1, K2, KP) | 0.000–0.004 | — | 1.3–19 |
| haze with the target faintly visible (V1) | 0.001–0.040 | — | |
| K2 fog with a sharp foreground | 0.028–0.040 | — | |
| KP overcast, summit hidden | 0.011–0.021 | — | |
| clear quiet morning (K2 / KP) | 0.023–0.034 / 0.035–0.049 | — | |
| episode 55 day (K2 / KP / V1) | 0.044–0.10 / 0.031–0.10 / 0.14–0.25 | — | 3–15 |
| episode 55 night (K2 / KP / V1) | 0.021–0.034 / 0.028–0.050 / 0.078–0.18 | min 0.654 % / 0.161 % / 4.6 % | 1.6–41 |
| quiet night (KP / K2 / V1) | 0.000 / 0.006–0.009 / 0.000–0.004 | 0 % / 0.019–0.208 % / 0–3.4 % | 0.24–5.6 |
| the same image re-encoded as JPEG (q 70–95) | | | 0.005–0.161 |

Contrast (standard deviation of luminance) separates conditions less well than edge density: clear V1 frames reach only 33, K2 fog with a sharp foreground 28–36. It is stored, but the rules do not use it.

A V1 zoom change (03:49 HST) shows as change 65, and a KP exposure switch (04:15 HST) as 41. Those are scene cuts, not frozen frames.

**Chosen thresholds** (`Thresholds` in Task 2), with the decisions they give (checked with the exact Task 2 code):
- `fog_edges = 0.005`: below it a visible-camera frame is rejected as `low_visibility`.
- `clear_edges = 0.015`: between the two, a daytime frame is `uncertain` and goes to Muse Spark.
- `night_sun_deg = -6`: civil twilight.
- `night_glow = 0.0005`: at night a frame needs a glow fraction of at least 0.05 % (about 16 blocks), otherwise `night`.
- `frozen_change = 0.15`.
- `stale_after = 30 min`, judged only when a live `now` is given.

| window | KP pass / uncertain / reject | K2 | V1 |
|---|---|---|---|
| episode 55 | 78 / 0 / 0 | 195 / 0 / 0 | 195 / 0 / 0 |
| foggy afternoon | 16 / 7 / 25 | 98 / 8 / 14 | 52 / 24 / 44 |
| quiet night | 0 / 0 / 24 (night) | 39 / 0 / 21 (night) | 5 / 0 / 55 (41 night, 14 low_visibility) |
| clear morning | 24 / 0 / 0 | 60 / 0 / 0 | — |

A wide uncertain band (`clear_edges = 0.05`) would have sent every quiet clear K2 frame to Muse Spark: about $0.24 per hour for K2 alone. The narrow band sends about 39 frames of a 4-hour foggy afternoon across three cameras (about $0.31). The price is that K2 fog with a sharp foreground passes locally. SAM then finds little in those frames, and Phase 3 keeps only masks attached to the vent.

**Sun.** `vigia/sun.py` (Task 1) matches the `astral` library to 0.001° on 8 cases. At Kīlauea (19.405 N, 155.29 W) on 2026-10-17: −46.927° at 13:00Z, −6.956° at 15:50Z, −4.621° at 16:00Z, +61.04° at 22:00:05Z. Civil dawn at 05:54 HST, sunrise at 06:16 HST. Also +73.438° at 40 N, 0 E on 2026-06-21 12:02Z, and −13.438° at 80 N on 2026-12-21 12:00Z.

**Muse Spark gate cost.** The smoke-test assessments used 3,173 input and 920–996 output tokens: $0.008 per frame, 9–12 s. Assessing every live frame (KP every 5 min, K2 every 2 min, F1 every 10 min) would cost about $9 a day. The gate therefore asks only about uncertain frames, plus explicit requests (`spark="all"`, and the Phase 4 agent tool).

**SAM video.** $0.0002 per frame with a 50-frame minimum per request. Episode 55 with 3 phrases costs: K2 195 frames, $0.117; V1 195, $0.117; KP 78, $0.047. The smoke test tracked a 2-min-cadence V1 timelapse at 10 fps: 93/100 frames, one track.

**COCO RLE.** `meta_sam_parser.decode_mask_to_rle` returns `RLEObject(size=(h, w), counts=str)`. It is a pure-Python per-pixel loop, and it encodes the raw SAM raster, which can be smaller than its box. The `vigia/masks.py` encoder in Task 6 produces byte-identical `counts` for the docs' sample masks (checked), runs on numpy, and is used on the box-sized mask after scaling it to the frame's resolution. The parser's decoder is private (`_decode`), so `vigia/masks.py` has its own.

**Frames on disk.** Episode 55 KP and K2 are 3840×2160; V1 is 1920×1080. Tracking videos are at most 1080 px high, so K2 and KP are scaled by exactly 2.

## Decisions beyond the roadmap bullets

1. **Contrast is measured and stored but not used in the rules.** On these cameras it separates fog from clear views less well than edge density (see Facts).
2. **Narrow uncertain band.** Muse Spark is called automatically only for hazy frames (edge density 0.005–0.015). Overcast KP and K2 fog with a sharp foreground pass locally; this is documented as a caveat.
3. **Incandescence at night** counts warm-bright or near-white blocks, so it works for orange lava, saturated white lava and monochrome night mode. Quiet-night vent glow on K2 and V1 is kept: it is real incandescence.
4. **Thermal cameras** (F1) skip the night and fog checks; only stale and frozen apply.
5. **Masks** are stored as COCO RLE of the box-sized mask at the frame's resolution, encoded by `vigia/masks.py`, whose format matches `decode_mask_to_rle`. See Facts for why.
6. **`vigia-ingest` does not run the gate.** The Phase 5 pipeline runner calls `QualityGate.assess_range` on new frames, and also owns the live rule of one tracking window per camera per hour. Phase 2 enforces the backfill half of the cost rule: `vigia-track` refuses windows under 50 usable frames by default.
7. **A printed time more than 10 minutes away from the stored capture time** makes a frame unusable (`timestamp_mismatch`), because its measurements would land at the wrong time.

## File structure

| File | Responsibility |
|---|---|
| `vigia/sun.py` (create) | `solar_elevation(when, lat, lon)`, NOAA equations |
| `vigia/config.py` (modify) | `Volcano.lat`, `Volcano.lon` |
| `config/sources.yaml` (modify) | volcano positions |
| `vigia/quality.py` (create) | `ImageStats`, `measure`, `fingerprint`, `difference`, `Thresholds`, `LocalVerdict`, `check_local` |
| `scripts/calibrate_quality.py` (create) | local measurements and decisions over stored frames, CSV, summary, contact sheets |
| `vigia/db.py` (modify) | `frame_quality` (Task 4); `tracking_runs`, `tracks`, `detections` (Task 7) |
| `vigia/gate.py` (create) | gate prompt and schema (moved from the smoke test), `parse_ptz`, `read_answer`, `SparkAssessment`, `FrameVerdict`, `GateReport`, `QualityGate`, `vigia-quality` CLI |
| `scripts/smoke_test.py` (modify) | import the gate prompt and schema from `vigia.gate` |
| `vigia/masks.py` (create) | COCO RLE `encode` / `decode` |
| `vigia/meta/sam.py` (modify) | `_fit_to_box` becomes the public `fit_mask` |
| `vigia/video.py` (modify) | `assemble(..., height=)` |
| `vigia/tracking.py` (create) | `WindowFrame`, `usable_frames`, `unassessed_frames`, `detection_mask`, `track_window`, `TrackingReport`, `RunSummary`, `vigia-track` CLI |
| `vigia/settings.py`, `.env.example` (modify) | `prompts_path` / `PROMPTS_PATH` |
| `scripts/render_tracks.py` (create) | overlay MP4 and contact sheet of a camera's tracks |
| `pyproject.toml` (modify) | `vigia-quality`, `vigia-track` console scripts |
| `tests/test_sun.py`, `tests/test_quality.py`, `tests/test_gate.py`, `tests/test_masks.py`, `tests/test_tracking.py` (create) | tests |
| `tests/test_config.py`, `tests/test_sam.py`, `tests/test_video.py` (modify) | tests |
| `docs/research/quality_calibration.md`, `docs/research/tracking_ep55.md` (create) | evidence and results |

Scripts follow the existing precedent: thin wrappers over tested package code, checked by running them, with no unit tests of their own.

Run every command from the repo root (Git Bash). Commit messages are imperative and sentence case, with **no** `Co-Authored-By` or other trailer. The suite has 105 tests before this phase.

## Execution

- **Tasks 1, 2 and 4–9:** dispatch the `implementer` subagent with the task text, then the `reviewer` subagent with the task text, BASE and HEAD.
- **Task 3:** the implementer writes and commits the script. The orchestrator then runs it, checks the contact sheets by eye and writes the evidence doc.
- **Tasks 10 and 11:** orchestrator only. Task 10 spends Meta API money (budget ≤ $1.00); Task 11 pushes.

---

### Task 1: Sun elevation and volcano positions

**Files:**
- Create: `vigia/sun.py`, `tests/test_sun.py`
- Modify: `vigia/config.py`, `config/sources.yaml`, `tests/test_config.py`

- [ ] **Step 1: Write the failing sun tests** (`tests/test_sun.py`)

```python
from datetime import datetime, timedelta, timezone

import pytest

from vigia.sun import solar_elevation

UTC = timezone.utc
HST = timezone(timedelta(hours=-10))
KILAUEA = (19.405, -155.29)


def test_noon_sun_at_the_june_solstice_stands_at_90_minus_latitude_plus_tilt():
    assert solar_elevation(datetime(2026, 6, 21, 12, 2, tzinfo=UTC), 40.0, 0.0) == pytest.approx(73.438, abs=0.01)


def test_polar_night_keeps_the_noon_sun_below_the_horizon():
    assert solar_elevation(datetime(2026, 12, 21, 12, 0, tzinfo=UTC), 80.0, 0.0) == pytest.approx(-13.438, abs=0.01)


def test_civil_twilight_at_kilauea_began_at_0554_hst_on_episode_55():
    assert solar_elevation(datetime(2026, 10, 17, 15, 50, tzinfo=UTC), *KILAUEA) == pytest.approx(-6.956, abs=0.01)
    assert solar_elevation(datetime(2026, 10, 17, 16, 0, tzinfo=UTC), *KILAUEA) == pytest.approx(-4.621, abs=0.01)


def test_any_utc_offset_gives_the_same_elevation():
    assert solar_elevation(datetime(2026, 10, 17, 3, 0, tzinfo=HST), *KILAUEA) == pytest.approx(
        solar_elevation(datetime(2026, 10, 17, 13, 0, tzinfo=UTC), *KILAUEA))


def test_a_naive_time_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        solar_elevation(datetime(2026, 10, 17, 13, 0), *KILAUEA)
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sun.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigia.sun'`

- [ ] **Step 3: Create `vigia/sun.py`**

```python
"""The sun's elevation above the horizon, for the quality gate's night check.

NOAA's solar position equations (https://gml.noaa.gov/grad/solcalc/calcdetails.html),
good to about 0.1 degree for dates near the present. Atmospheric refraction is
left out: it lifts the sun by about half a degree at the horizon, which does
not matter at the -6 degree civil-twilight limit the gate uses.
"""

from __future__ import annotations

import math
from datetime import datetime


def solar_elevation(when: datetime, lat: float, lon: float) -> float:
    """Degrees of the sun's centre above the horizon at `when`, seen from lat/lon (east positive)."""
    if when.tzinfo is None:
        raise ValueError("solar_elevation needs a timezone-aware time")
    t = (when.timestamp() / 86400.0 + 2440587.5 - 2451545.0) / 36525.0  # Julian centuries since J2000.0

    mean_longitude = (280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360
    mean_anomaly = math.radians(357.52911 + t * (35999.05029 - 0.0001537 * t))
    eccentricity = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    centre = (math.sin(mean_anomaly) * (1.914602 - t * (0.004817 + 0.000014 * t))
              + math.sin(2 * mean_anomaly) * (0.019993 - 0.000101 * t)
              + math.sin(3 * mean_anomaly) * 0.000289)
    omega = math.radians(125.04 - 1934.136 * t)
    apparent_longitude = math.radians(mean_longitude + centre - 0.00569 - 0.00478 * math.sin(omega))
    obliquity = math.radians(23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
                             + 0.00256 * math.cos(omega))
    declination = math.asin(math.sin(obliquity) * math.sin(apparent_longitude))

    y = math.tan(obliquity / 2) ** 2
    l0 = math.radians(mean_longitude)
    equation_of_time = 4 * math.degrees(  # minutes
        y * math.sin(2 * l0) - 2 * eccentricity * math.sin(mean_anomaly)
        + 4 * eccentricity * y * math.sin(mean_anomaly) * math.cos(2 * l0)
        - 0.5 * y * y * math.sin(4 * l0) - 1.25 * eccentricity ** 2 * math.sin(2 * mean_anomaly))

    utc_minutes = (when.timestamp() % 86400) / 60
    hour_angle = math.radians(((utc_minutes + equation_of_time + 4 * lon) % 1440) / 4 - 180)
    latitude = math.radians(lat)
    cos_zenith = (math.sin(latitude) * math.sin(declination)
                  + math.cos(latitude) * math.cos(declination) * math.cos(hour_angle))
    return 90 - math.degrees(math.acos(max(-1.0, min(1.0, cos_zenith))))
```

- [ ] **Step 4: Run the sun tests to see them pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sun.py -v`
Expected: 5 passed

- [ ] **Step 5: Write the failing config tests** (append to `tests/test_config.py`)

```python
def placed(text, lat="19.405", lon="-155.29"):
    return text.replace("    official_url: https://www.usgs.gov/volcanoes/kilauea",
                        f"    official_url: https://www.usgs.gov/volcanoes/kilauea\n    lat: {lat}\n    lon: {lon}")


def test_volcano_position_is_optional(tmp_path):
    assert load_sources(write(tmp_path, VALID)).volcanoes["kilauea"].lat is None

    volcano = load_sources(write(tmp_path, placed(VALID))).volcanoes["kilauea"]

    assert (volcano.lat, volcano.lon) == (19.405, -155.29)


def test_volcano_latitude_out_of_range_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="lat"):
        load_sources(write(tmp_path, placed(VALID, lat="119.4")))


def test_committed_sources_place_every_volcano():
    sources = load_sources(REPO / "config" / "sources.yaml")

    assert [name for name, v in sources.volcanoes.items() if v.lat is None or v.lon is None] == []
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: the three new tests FAIL (`Volcano` has no `lat`)

- [ ] **Step 6: Add the position to `Volcano`** in `vigia/config.py`

```python
class Volcano(BaseModel):
    name: str
    country: str
    official_agency: str
    official_url: str
    lat: float | None = Field(default=None, ge=-90, le=90)  # summit area: sets the sun's elevation for the night check
    lon: float | None = Field(default=None, ge=-180, le=180)
```

- [ ] **Step 7: Place both volcanoes in `config/sources.yaml`**

Add to the header comment, after the `live_source` lines:

```yaml
# Each volcano's lat/lon (summit area, east positive) sets the sun's elevation
# for the quality gate's night check.
```

and add two lines at the end of each volcano:

```yaml
  kilauea:
    name: Kīlauea
    country: United States (Hawaiʻi)
    official_agency: USGS Hawaiian Volcano Observatory (HVO)
    official_url: https://www.usgs.gov/volcanoes/kilauea
    lat: 19.405    # Halemaʻumaʻu north vent (19.40496 N, 155.29022 W)
    lon: -155.290
  nevado-del-ruiz:
    name: Nevado del Ruiz
    country: Colombia
    official_agency: Servicio Geológico Colombiano (SGC)
    official_url: https://www2.sgc.gov.co/Noticias/Paginas/Boletines-semanales.aspx
    lat: 4.895     # Arenas crater
    lon: -75.323
```

- [ ] **Step 8: Run the suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 113 passed

- [ ] **Step 9: Commit**

```bash
git add vigia/sun.py vigia/config.py config/sources.yaml tests/test_sun.py tests/test_config.py
git commit -m "Compute the sun's elevation at each volcano for the night check"
```

---

### Task 2: Local frame measurements and checks (`vigia/quality.py`)

The thresholds are the calibrated values from the Facts section; Task 3 records the evidence.

**Files:**
- Create: `vigia/quality.py`, `tests/test_quality.py`

- [ ] **Step 1: Write the failing tests** (`tests/test_quality.py`)

```python
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from PIL import Image, ImageDraw

from vigia.quality import ImageStats, LocalVerdict, check_local, difference, fingerprint, measure

DAY = datetime(2026, 10, 17, 22, 0, tzinfo=timezone.utc)
CLEAR = ImageStats(brightness=120, contrast=50, edge_density=0.10, glow_fraction=0.0)


def checkerboard(size=(320, 240), square=16):
    x, y = np.meshgrid(np.arange(size[0]), np.arange(size[1]))
    return Image.fromarray(((x // square + y // square) % 2 * 255).astype(np.uint8)).convert("RGB")


def dark_with_square(color, size=(320, 240)):
    image = Image.new("RGB", size, (0, 0, 0))
    ImageDraw.Draw(image).rectangle((120, 80, 199, 159), fill=color)
    return image


def with_edges(edges, glow=0.0):
    return ImageStats(brightness=120, contrast=40, edge_density=edges, glow_fraction=glow)


def check(stats=CLEAR, **kwargs):
    args = {"kind": "visible", "captured_at": DAY, "sun_elevation": 60.0, "change": 5.0} | kwargs
    return check_local(stats, **args)


# --- measurements


def test_a_flat_frame_has_no_contrast_edges_or_glow():
    stats = measure(Image.new("RGB", (320, 240), (128, 128, 128)))

    assert stats.brightness == pytest.approx(128, abs=0.5)
    assert stats.contrast == pytest.approx(0, abs=0.01)
    assert (stats.edge_density, stats.glow_fraction) == (0.0, 0.0)


def test_a_sharp_pattern_is_mostly_edges():
    stats = measure(checkerboard())

    assert stats.edge_density > 0.2
    assert stats.contrast > 100


def test_printed_text_bands_are_left_out():
    image = Image.new("RGB", (320, 240), (128, 128, 128))
    image.paste(checkerboard((320, 12), square=4), (0, 0))    # timestamp band: top 5 %
    image.paste(checkerboard((320, 19), square=4), (0, 221))  # logo and PTZ band: bottom 8 %

    stats = measure(image)

    assert stats.edge_density == 0.0
    assert stats.contrast == pytest.approx(0, abs=0.01)


@pytest.mark.parametrize("color", [(255, 120, 20), (255, 255, 255)], ids=["orange lava", "saturated white"])
def test_bright_lava_in_the_dark_counts_as_glow(color):
    stats = measure(dark_with_square(color))

    assert stats.glow_fraction == pytest.approx(80 * 80 / (320 * 209), rel=0.1)


def test_dim_light_is_not_glow():
    assert measure(dark_with_square((40, 60, 200))).glow_fraction == 0.0


def test_difference_is_zero_for_the_same_scene_under_a_new_timestamp():
    before = checkerboard()
    after = before.copy()
    after.paste(Image.new("RGB", (100, 10), (255, 255, 255)), (0, 0))  # only the printed time changed

    assert difference(fingerprint(before), fingerprint(after)) == 0.0


def test_difference_measures_luminance_change():
    darker = fingerprint(Image.new("RGB", (320, 240), (100, 100, 100)))
    brighter = fingerprint(Image.new("RGB", (320, 240), (110, 110, 110)))

    assert difference(darker, brighter) == pytest.approx(10, abs=0.5)


def test_difference_is_undefined_across_frame_sizes():
    assert difference(fingerprint(checkerboard((320, 240))), fingerprint(checkerboard((640, 480)))) is None


# --- decisions


def test_a_clear_daytime_frame_passes():
    assert check() == LocalVerdict("pass")


def test_fog_is_rejected():
    assert check(with_edges(0.004)) == LocalVerdict("reject", ("low_visibility",))


def test_haze_is_left_to_muse_spark():
    assert check(with_edges(0.010)) == LocalVerdict("uncertain", ("low_visibility",))


def test_a_dark_night_frame_is_rejected():
    assert check(with_edges(0.002), sun_elevation=-30.0) == LocalVerdict("reject", ("night",))


def test_a_night_frame_with_incandescence_passes_even_with_few_edges():
    assert check(with_edges(0.010, glow=0.002), sun_elevation=-30.0) == LocalVerdict("pass")


def test_glow_seen_through_fog_at_night_is_rejected():
    assert check(with_edges(0.001, glow=0.002), sun_elevation=-30.0) == LocalVerdict("reject", ("low_visibility",))


def test_civil_twilight_still_counts_as_day():
    assert check(with_edges(0.020), sun_elevation=-5.0) == LocalVerdict("pass")


def test_thermal_cameras_skip_the_night_and_fog_checks():
    assert check(with_edges(0.0), kind="thermal", sun_elevation=-30.0) == LocalVerdict("pass")


def test_a_frame_identical_to_the_previous_one_is_frozen():
    assert check(change=0.05) == LocalVerdict("reject", ("frozen",))


def test_the_first_frame_of_a_camera_cannot_be_frozen():
    assert check(change=None) == LocalVerdict("pass")


def test_staleness_is_judged_only_against_a_given_now():
    assert check(now=DAY + timedelta(minutes=31)) == LocalVerdict("reject", ("stale",))
    assert check(now=DAY + timedelta(minutes=29)) == LocalVerdict("pass")
    assert check(now=None) == LocalVerdict("pass")


def test_every_failing_check_is_reported():
    assert check(with_edges(0.0), sun_elevation=-30.0, change=0.0) == LocalVerdict("reject", ("frozen", "night"))


def test_without_a_sun_elevation_the_frame_counts_as_daytime():
    assert check(with_edges(0.002), sun_elevation=None) == LocalVerdict("reject", ("low_visibility",))
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_quality.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigia.quality'`

- [ ] **Step 3: Create `vigia/quality.py`**

```python
"""Local frame checks that cost nothing: stale, frozen, dark night and fog.

The measurements cover the scene between the burned-in text bands (the
timestamp at the top; the USGS logo and the PTZ readout at the bottom):
- edge density: the share of pixels where luminance changes by more than 8
  levels per pixel, on a lightly blurred copy at most 512 px wide. Fog
  flattens everything.
- glow fraction: the share of a block-averaged copy (at most 256 px wide)
  that is warm and bright (orange lava) or nearly white (lava that saturates
  the sensor, or a camera in monochrome night mode). Averaging leaves out
  small lights such as stars and path lamps.
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

from vigia.config import CameraKind

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
    glow_fraction: float  # share of blocks that look incandescent


@dataclass(frozen=True)
class Thresholds:
    stale_after: timedelta = timedelta(minutes=30)
    frozen_change: float = 0.15  # re-encoding one image changes it by 0.005-0.16; real consecutive frames by 0.24+
    night_sun_deg: float = -6.0  # civil twilight
    night_glow: float = 0.0005   # episode 55 nights: 0.16 % and up; quiet nights: 0 %, or a vent glow up to 0.2 %
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
    warm = (red >= 150) & (red - blue >= 60) & (red >= green)
    white_hot = blocks.min(axis=-1) >= 200
    return ImageStats(
        brightness=float(luminance.mean()),
        contrast=float(luminance.std()),
        edge_density=float((np.hypot(rows, cols) > _EDGE_STEP).mean()),
        glow_fraction=float((warm | white_hot).mean()),
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
```

- [ ] **Step 4: Run the tests to see them pass, then the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_quality.py -v` → 22 passed
Run: `.venv/Scripts/python.exe -m pytest` → 135 passed

- [ ] **Step 5: Commit**

```bash
git add vigia/quality.py tests/test_quality.py
git commit -m "Add local frame checks for stale, frozen, night and fog frames"
```

---

### Task 3: Calibration script and evidence

**Files:**
- Create: `scripts/calibrate_quality.py` (implementer), `docs/research/quality_calibration.md` (orchestrator)

- [ ] **Step 1: Write the script** (`scripts/calibrate_quality.py`)

```python
"""Measure the local quality checks on stored frames, to calibrate their thresholds.

For each camera and time window, every stored frame gets the local
measurements of vigia.quality (edge density, contrast, glow, difference from
the camera's previous frame), the sun's elevation at its volcano and the
decision under the current thresholds. Results go to
data/calibration/<UTC time>/:
  - stats.csv: one row per frame;
  - summary.md: decision counts and value ranges per camera and window;
  - <camera>_<window start>_<decision>.jpg: contact sheets of up to 24
    frames, captioned with the HST time, edge density and glow, to check the
    decisions by eye.

    python scripts/calibrate_quality.py --camera kilauea-kp --camera kilauea-k2 --camera kilauea-v1 \\
        --window 2026-10-17T13:00Z/2026-10-17T19:30Z --window 2026-10-26T22:00Z/2026-10-27T02:00Z
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from vigia import db
from vigia.config import Camera, Sources, load_sources
from vigia.quality import check_local, difference, fingerprint, measure
from vigia.settings import Settings
from vigia.sun import solar_elevation
from vigia.timeutil import parse_utc, to_iso, utcnow

HST = timezone(timedelta(hours=-10))
FIELDS = ["camera_id", "window", "captured_at", "hst", "path", "sun_elevation", "brightness", "contrast",
          "edge_density", "glow_fraction", "change", "decision", "reasons"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camera", action="append", required=True, help="camera id; repeat for several")
    parser.add_argument("--window", action="append", required=True, type=parse_window,
                        help="START/END with offsets, e.g. 2026-10-17T13:00Z/2026-10-17T19:30Z; repeat for several")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    sources = load_sources(settings.sources_path)
    cameras = {c.id: c for c in sources.cameras}
    unknown = [camera_id for camera_id in args.camera if camera_id not in cameras]
    if unknown:
        parser.error(f"unknown camera(s): {', '.join(unknown)}")
    conn = db.connect(settings.db_path)
    out = settings.data_dir / "calibration" / f"{utcnow():%Y%m%dT%H%M%SZ}"
    out.mkdir(parents=True)

    rows = []
    for camera_id in args.camera:
        for start, end in args.window:
            window_rows = measure_window(conn, settings.data_dir, sources, cameras[camera_id], start, end)
            rows += window_rows
            for decision, group in grouped(window_rows).items():
                sheet = contact_sheet(settings.data_dir, group)
                sheet.save(out / f"{camera_id}_{start:%Y%m%dT%H%M}_{decision}.jpg", quality=85)
    with open(out / "stats.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (out / "summary.md").write_text(summary(rows), encoding="utf-8")
    print(f"{len(rows)} frames measured; results in {out}")


def parse_window(text: str) -> tuple[datetime, datetime]:
    start, _, end = text.partition("/")
    return parse_utc(start), parse_utc(end)


def measure_window(conn, data_dir: Path, sources: Sources, camera: Camera,
                   start: datetime, end: datetime) -> list[dict]:
    """Measurements and local decisions for the camera's stored frames in [start, end], oldest first."""
    volcano = sources.volcanoes[camera.volcano]
    before = conn.execute(
        "SELECT path FROM frames WHERE camera_id = ? AND captured_at < ? ORDER BY captured_at DESC LIMIT 1",
        (camera.id, to_iso(start))).fetchone()
    previous = fingerprint(open_rgb(data_dir / before["path"])) if before else None
    rows = []
    for frame in conn.execute(
            "SELECT * FROM frames WHERE camera_id = ? AND captured_at BETWEEN ? AND ? ORDER BY captured_at",
            (camera.id, to_iso(start), to_iso(end))).fetchall():
        image = open_rgb(data_dir / frame["path"])
        stats, current = measure(image), fingerprint(image)
        captured_at = parse_utc(frame["captured_at"])
        sun = (solar_elevation(captured_at, volcano.lat, volcano.lon)
               if volcano.lat is not None and volcano.lon is not None else None)
        change = difference(previous, current) if previous is not None else None
        verdict = check_local(stats, kind=camera.kind, captured_at=captured_at, sun_elevation=sun, change=change)
        previous = current
        rows.append({"camera_id": camera.id, "window": to_iso(start), "captured_at": frame["captured_at"],
                     "hst": captured_at.astimezone(HST).strftime("%Y-%m-%d %H:%M"), "path": frame["path"],
                     "sun_elevation": sun, **asdict(stats), "change": change,
                     "decision": verdict.decision, "reasons": " ".join(verdict.reasons)})
    return rows


def open_rgb(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB")


def grouped(rows: list[dict]) -> dict[str, list[dict]]:
    groups = defaultdict(list)
    for row in rows:
        groups[row["decision"]].append(row)
    return groups


def contact_sheet(data_dir: Path, rows: list[dict], limit: int = 24, columns: int = 4, width: int = 400) -> Image.Image:
    picks = rows if len(rows) <= limit else [rows[round(i * (len(rows) - 1) / (limit - 1))] for i in range(limit)]
    font = ImageFont.load_default(size=18)
    cells = []
    for row in picks:
        thumb = open_rgb(data_dir / row["path"])
        thumb.thumbnail((width, width))
        cell = Image.new("RGB", (width, thumb.height + 24), (25, 25, 25))
        cell.paste(thumb, (0, 24))
        caption = f"{row['hst'][11:]} e={row['edge_density']:.3f} g={100 * row['glow_fraction']:.2f}%"
        ImageDraw.Draw(cell).text((4, 2), caption, fill=(255, 255, 0), font=font)
        cells.append(cell)
    cell_h = max(cell.height for cell in cells)
    sheet = Image.new("RGB", (width * columns, cell_h * -(-len(cells) // columns)))
    for i, cell in enumerate(cells):
        sheet.paste(cell, ((i % columns) * width, (i // columns) * cell_h))
    return sheet


def summary(rows: list[dict]) -> str:
    lines = ["# Local quality checks", "",
             "| camera | window start (UTC) | frames | pass | uncertain | reject (reasons) | edge density | glow % |",
             "|---|---|---|---|---|---|---|---|"]
    windows = defaultdict(list)
    for row in rows:
        windows[(row["camera_id"], row["window"])].append(row)
    for (camera_id, window), group in windows.items():
        decisions = Counter(row["decision"] for row in group)
        reasons = Counter(reason for row in group if row["decision"] == "reject" for reason in row["reasons"].split())
        edges = [row["edge_density"] for row in group]
        glows = [100 * row["glow_fraction"] for row in group]
        rejected = ", ".join(f"{reason} {count}" for reason, count in sorted(reasons.items())) or "-"
        lines.append(f"| {camera_id} | {window} | {len(group)} | {decisions['pass']} | {decisions['uncertain']} "
                     f"| {decisions['reject']} ({rejected}) | {min(edges):.3f}-{max(edges):.3f} "
                     f"| {min(glows):.3f}-{max(glows):.3f} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Check it runs on one small window**

Run: `.venv/Scripts/python.exe scripts/calibrate_quality.py --camera kilauea-v1 --window 2026-10-27T00:00Z/2026-10-27T00:30Z`
Expected: `15 frames measured; results in data/calibration/<time>`. Its `summary.md` lists `kilauea-v1` with mostly `reject (low_visibility …)` (this is the smoke test's fog half hour).

- [ ] **Step 3: Commit the script** (implementer stops here)

```bash
git add scripts/calibrate_quality.py
git commit -m "Add script that calibrates the local quality checks on stored frames"
```

- [ ] **Step 4 (orchestrator): Run the full calibration**

Run:

```bash
.venv/Scripts/python.exe scripts/calibrate_quality.py --camera kilauea-kp --camera kilauea-k2 --camera kilauea-v1 \
    --window 2026-10-17T13:00Z/2026-10-17T19:30Z --window 2026-10-26T22:00Z/2026-10-27T02:00Z \
    --window 2026-10-27T06:00Z/2026-10-27T08:00Z --window 2026-10-27T16:00Z/2026-10-27T19:00Z
```

Expected: the counts of the "Chosen thresholds" table in Facts, within ±2 per cell. The first frame of each window now has a change value, which could flip at most one frozen verdict. V1 has no frames in the last window, so it gets no row there.

- [ ] **Step 5 (orchestrator): Check the decisions by eye.** Open each `*_reject.jpg` and `*_uncertain.jpg` sheet, and the `*_pass.jpg` sheets of the foggy afternoon and the quiet night. Record any misclassified frame by camera and HST time.

- [ ] **Step 6 (orchestrator): Write `docs/research/quality_calibration.md`** with these sections:
  - *Method*: windows and frame counts; metric definitions (as in the `vigia/quality.py` docstring); the run directory; the command.
  - *Measurements*: the condition table from Facts, updated with the run's ranges.
  - *Thresholds*: each value and the measurement that fixes it.
  - *Decisions*: the run's `summary.md` table, plus the visual check: misclassified frames, with camera and time.
  - *Caveats*: K2 fog with a sharp foreground and overcast KP pass locally; Muse Spark sees only hazy frames; quiet-night vent glow is kept on purpose; contrast is not used; the night check skips thermal cameras; one calibration day.

- [ ] **Step 7 (orchestrator): Commit**

```bash
git add docs/research/quality_calibration.md
git commit -m "Record the quality check calibration on episode 55 and Oct 26-27 frames"
```

---

### Task 4: The quality gate (`vigia/gate.py`, `frame_quality`)

The gate runs the local checks on one stored frame, asks Muse Spark when its mode requires it, and stores one row per frame. The Muse Spark prompt and schema move from the smoke test into the package, gaining the PTZ readout and losing the SAM phrase suggestions. Task 5 points the smoke test at them.

**Files:**
- Create: `vigia/gate.py`, `tests/test_gate.py`
- Modify: `vigia/db.py`

- [ ] **Step 1: Write the failing tests** (`tests/test_gate.py`)

```python
import io
import json
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np
import pytest
from PIL import Image, ImageDraw

from test_meta_client import SPARK_USAGE, FakeApi, make_client, response_body
from vigia.config import Camera, Sources, Volcano
from vigia.gate import GATE_SCHEMA, QualityGate, parse_ptz, read_answer
from vigia.ingest.store import FrameStore
from vigia.quality import Thresholds

DAY = datetime(2026, 10, 17, 22, 0, 5, tzinfo=timezone.utc)    # 12:00 HST, sun at +61 degrees
NIGHT = datetime(2026, 10, 17, 13, 0, 5, tzinfo=timezone.utc)  # 03:00 HST, sun at -47 degrees
SOURCES = Sources(
    volcanoes={"kilauea": Volcano(name="Kīlauea", country="United States", official_agency="USGS HVO",
                                  official_url="https://www.usgs.gov/volcanoes/kilauea", lat=19.405, lon=-155.29)},
    cameras=[
        Camera(id="kilauea-v1", name="V1cam", volcano="kilauea", url="https://example.org/V1.jpg",
               license="Public Domain", attribution="U.S. Geological Survey"),
        Camera(id="kilauea-f1", name="F1cam", volcano="kilauea", url="https://example.org/F1.jpg",
               license="Public Domain", attribution="U.S. Geological Survey", kind="thermal"),
    ],
)
ANSWER = {
    "usable": True, "view": "clear", "usable_reason": "The vent and the plume are in clear view.",
    "printed_timestamp_text": "2026-10-17 12:00:01 HST", "printed_timestamp_iso": "2026-10-17T12:00:01-10:00",
    "printed_camera_label": "USGS", "printed_ptz_text": "P: 29, T: +0.00, Z: 29 1.0",
    "visible_features": ["crater", "vent", "steam"], "activity": "steaming",
    "description_en": "A steam plume rises from the vent.",
    "description_es": "Un penacho de vapor sale del respiradero.",
}
HAZY = Thresholds(clear_edges=1.01)  # every daytime frame with detail counts as hazy


def encode(image, fmt="JPEG"):
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def sharp(seed=0):
    """A frame full of detail, like a clear view."""
    return Image.fromarray(np.random.default_rng(seed).integers(0, 256, (240, 320, 3), dtype=np.uint8))


def flat(level):
    return Image.new("RGB", (320, 240), (level, level, level))


def glowing():
    image = Image.new("RGB", (320, 240), (0, 0, 0))
    ImageDraw.Draw(image).rectangle((120, 80, 199, 159), fill=(255, 120, 20))
    return image


@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def add(store, image, captured_at, camera_id="kilauea-v1", fmt="JPEG"):
    return store.add(camera_id, encode(image, fmt), captured_at=captured_at, timestamp_source="ashcam",
                     fetched_at=captured_at)


def spark_api(answer=ANSWER):
    return FakeApi(lambda r: httpx.Response(200, json=response_body("muse-spark-1.3", json.dumps(answer), SPARK_USAGE)))


def gate(conn, tmp_path, api=None, **kwargs):
    client = make_client(api, conn) if api is not None else None
    return QualityGate(conn, tmp_path, SOURCES, client, **kwargs)


def stored(conn, frame_id):
    return conn.execute("SELECT * FROM frame_quality WHERE frame_id = ?", (frame_id,)).fetchone()


def test_a_clear_frame_is_usable_without_asking_muse_spark(conn, store, tmp_path):
    api = spark_api()
    frame_id = add(store, sharp(), DAY)

    verdict = gate(conn, tmp_path, api).assess(frame_id)

    assert (verdict.usable, verdict.decided_by, verdict.reasons) == (True, "local", ())
    assert api.requests == []
    row = stored(conn, frame_id)
    assert (row["usable"], row["local_decision"], row["spark_view"]) == (1, "pass", None)
    assert row["sun_elevation_deg"] == pytest.approx(61.04, abs=0.01)


def test_fog_and_dark_night_frames_are_rejected_without_asking_muse_spark(conn, store, tmp_path):
    api = spark_api()
    fog = add(store, flat(150), DAY)
    night = add(store, flat(6), NIGHT)
    checker = gate(conn, tmp_path, api)

    assert checker.assess(fog).reasons == ("low_visibility",)
    assert checker.assess(night).reasons == ("night",)
    assert api.requests == []
    assert json.loads(stored(conn, night)["reasons"]) == ["night"]


def test_a_night_frame_with_glowing_lava_is_usable(conn, store, tmp_path):
    frame_id = add(store, glowing(), NIGHT)

    verdict = gate(conn, tmp_path).assess(frame_id)

    assert verdict.usable
    assert verdict.stats.glow_fraction > 0.05


def test_muse_spark_decides_a_hazy_frame_and_reads_its_timestamp_and_ptz(conn, store, tmp_path):
    api = spark_api()
    frame_id = add(store, sharp(), DAY)

    verdict = gate(conn, tmp_path, api, thresholds=HAZY).assess(frame_id)

    assert (verdict.local.decision, verdict.usable, verdict.decided_by) == ("uncertain", True, "spark")
    assert api.json_body()["text"]["format"]["schema"] == GATE_SCHEMA
    row = stored(conn, frame_id)
    assert row["printed_time"] == "2026-10-17T22:00:01Z"
    assert json.loads(row["printed_ptz"]) == {"pan": 29.0, "tilt": 0.0, "zoom_raw": 29.0, "zoom": 1.0}
    assert json.loads(row["spark_answer"]) == ANSWER
    [call] = conn.execute("SELECT purpose FROM api_calls").fetchall()
    assert call["purpose"] == "gate:assess"


def test_muse_spark_can_reject_a_hazy_frame(conn, store, tmp_path):
    frame_id = add(store, sharp(), DAY)
    answer = ANSWER | {"usable": False, "view": "obscured_by_cloud_or_fog"}

    verdict = gate(conn, tmp_path, spark_api(answer), thresholds=HAZY).assess(frame_id)

    assert (verdict.usable, verdict.decided_by) == (False, "spark")
    assert stored(conn, frame_id)["spark_view"] == "obscured_by_cloud_or_fog"


def test_a_hazy_frame_muse_spark_did_not_see_is_not_used(conn, store, tmp_path):
    frame_id = add(store, sharp(), DAY)

    verdict = gate(conn, tmp_path, thresholds=HAZY).assess(frame_id, spark="never")

    assert (verdict.local.decision, verdict.usable, verdict.decided_by) == ("uncertain", False, "local")


def test_spark_all_also_checks_frames_that_passed_but_never_rejected_ones(conn, store, tmp_path):
    api = spark_api()
    clear = add(store, sharp(), DAY)
    fog = add(store, flat(150), DAY + timedelta(minutes=2))
    checker = gate(conn, tmp_path, api)

    checker.assess(clear, spark="all")
    checker.assess(fog, spark="all")

    assert len(api.requests) == 1
    assert stored(conn, clear)["decided_by"] == "spark"


def test_a_printed_time_far_from_the_capture_time_makes_the_frame_unusable(conn, store, tmp_path):
    frame_id = add(store, sharp(), DAY)
    answer = ANSWER | {"printed_timestamp_iso": "2026-10-17T10:00:01-10:00"}

    verdict = gate(conn, tmp_path, spark_api(answer), thresholds=HAZY).assess(frame_id)

    assert (verdict.usable, verdict.reasons) == (False, ("low_visibility", "timestamp_mismatch"))


def test_a_frame_needing_muse_spark_without_a_client_is_an_error(conn, store, tmp_path):
    frame_id = add(store, sharp(), DAY)

    with pytest.raises(RuntimeError, match="spark='never'"):
        gate(conn, tmp_path, thresholds=HAZY).assess(frame_id)


def test_the_same_scene_under_a_new_timestamp_is_frozen(conn, store, tmp_path):
    first, second = sharp(), sharp()
    ImageDraw.Draw(second).rectangle((0, 0, 100, 8), fill=(255, 255, 255))  # only the printed time changed
    add(store, first, DAY, fmt="PNG")
    frozen = add(store, second, DAY + timedelta(minutes=2), fmt="PNG")

    verdict = gate(conn, tmp_path).assess(frozen)

    assert (verdict.usable, verdict.reasons, verdict.change) == (False, ("frozen",), 0.0)


def test_a_live_frame_older_than_30_minutes_is_stale(conn, store, tmp_path):
    frame_id = add(store, sharp(), DAY)

    verdict = gate(conn, tmp_path).assess(frame_id, now=DAY + timedelta(minutes=45))

    assert verdict.reasons == ("stale",)


def test_thermal_frames_are_not_judged_by_darkness(conn, store, tmp_path):
    frame_id = add(store, flat(6), NIGHT, camera_id="kilauea-f1")

    assert gate(conn, tmp_path).assess(frame_id).usable


def test_assess_range_skips_frames_already_assessed_unless_redo(conn, store, tmp_path):
    api = spark_api()
    ids = [add(store, sharp(seed), DAY + timedelta(minutes=2 * seed)) for seed in range(3)]
    checker = gate(conn, tmp_path, api, thresholds=HAZY)
    checker.assess(ids[0])

    report = checker.assess_range("kilauea-v1", DAY, DAY + timedelta(minutes=10))

    assert ([v.frame_id for v in report.verdicts], report.skipped) == (ids[1:], 1)
    assert len(api.requests) == 3
    assert len(checker.assess_range("kilauea-v1", DAY, DAY + timedelta(minutes=10), redo=True).verdicts) == 3


def test_assess_range_reports_a_failed_muse_spark_call_and_goes_on(conn, store, tmp_path):
    error = {"error": {"message": "overloaded", "type": "server_error", "param": None, "code": None}}
    api = FakeApi(lambda r: httpx.Response(503, json=error))
    ids = [add(store, sharp(seed), DAY + timedelta(minutes=2 * seed)) for seed in range(2)]

    report = gate(conn, tmp_path, api, thresholds=HAZY).assess_range("kilauea-v1", DAY, DAY + timedelta(minutes=5))

    assert (len(report.errors), report.verdicts) == (2, [])
    assert stored(conn, ids[0]) is None


def test_report_summary_counts_decisions(conn, store, tmp_path):
    add(store, sharp(), DAY)
    add(store, flat(150), DAY + timedelta(minutes=2))

    report = gate(conn, tmp_path).assess_range("kilauea-v1", DAY, DAY + timedelta(minutes=5))

    assert report.summary() == ("2 assessed, 1 usable, 1 rejected (low_visibility 1), 0 by Muse Spark, "
                                "0 already assessed, 0 failed")


@pytest.mark.parametrize("text, expected", [
    ("P: 29, T: +0.00, Z: 29 1.0", {"pan": 29.0, "tilt": 0.0, "zoom_raw": 29.0, "zoom": 1.0}),
    ("P: +178.54, T: -0.06, Z: 959 3.9", {"pan": 178.54, "tilt": -0.06, "zoom_raw": 959.0, "zoom": 3.9}),
    ("P: 9594, T: +0.00, Z: 9594 9.6", {"pan": 9594.0, "tilt": 0.0, "zoom_raw": 9594.0, "zoom": 9.6}),
])
def test_parse_ptz_reads_the_printed_readouts_of_usgs_ptz_cameras(text, expected):
    assert parse_ptz(text) == expected


@pytest.mark.parametrize("text", ["", "USGS", "P: 29"])
def test_parse_ptz_without_a_full_readout_is_none(text):
    assert parse_ptz(text) is None


def test_read_answer_converts_the_printed_time_to_utc():
    assert read_answer(ANSWER).printed_time == datetime(2026, 10, 17, 22, 0, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("iso", ["", "2026-10-17T12:00:01", "17/10/2026 12:00"])
def test_read_answer_without_a_zoned_printed_time_has_none(iso):
    assert read_answer(ANSWER | {"printed_timestamp_iso": iso}).printed_time is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigia.gate'`

- [ ] **Step 3: Add the `frame_quality` table** — in `vigia/db.py`, append to `SCHEMA` after the `api_calls` index:

```sql
CREATE TABLE IF NOT EXISTS frame_quality (
    frame_id          INTEGER PRIMARY KEY REFERENCES frames (id),
    assessed_at       TEXT    NOT NULL,  -- UTC
    usable            INTEGER NOT NULL,  -- 1 if measurements may use the frame
    decided_by        TEXT    NOT NULL,  -- local | spark
    local_decision    TEXT    NOT NULL,  -- pass | uncertain | reject
    reasons           TEXT    NOT NULL,  -- JSON list: stale, frozen, night, low_visibility, timestamp_mismatch
    sun_elevation_deg REAL,              -- NULL when the volcano has no position
    brightness        REAL    NOT NULL,
    contrast          REAL    NOT NULL,
    edge_density      REAL    NOT NULL,
    glow_fraction     REAL    NOT NULL,
    change            REAL,              -- against the camera's previous frame; NULL for its first
    spark_view        TEXT,              -- this and the columns below stay NULL unless Muse Spark was asked
    spark_reason      TEXT,
    printed_time_text TEXT,
    printed_time      TEXT,              -- UTC, when the printed timestamp states its zone
    printed_ptz       TEXT,              -- JSON {"pan", "tilt", "zoom_raw", "zoom"}
    spark_answer      TEXT               -- the whole JSON answer
);
```

- [ ] **Step 4: Create `vigia/gate.py`**

```python
"""The quality gate: local checks on every frame, Muse Spark when they cannot decide.

Local checks (vigia/quality.py) cost nothing: they reject stale, frozen,
dark-night and foggy frames, pass clear ones and leave hazy ones uncertain.
Muse Spark looks at the uncertain frames, or on request at every frame the
local checks let through: is the view usable, and which timestamp and
pan/tilt/zoom readout are printed on it. A printed time more than 10 minutes
from the stored capture time makes a frame unusable, since its measurements
would land at the wrong time. An uncertain frame that Muse Spark did not see
is not used. Each frame's verdict is one row of `frame_quality`.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
import openai
from PIL import Image

from vigia.config import Sources
from vigia.imaging import load_for_upload
from vigia.meta.client import MetaClient
from vigia.quality import ImageStats, LocalVerdict, Thresholds, check_local, difference, fingerprint, measure
from vigia.sun import solar_elevation
from vigia.timeutil import parse_utc, to_iso, utcnow

log = logging.getLogger(__name__)

SparkMode = Literal["never", "uncertain", "all"]
TIMESTAMP_TOLERANCE = timedelta(minutes=10)

GATE_INSTRUCTIONS = (
    "You are the quality gate of a volcano webcam monitoring system. You look at one webcam frame "
    "and report only what is actually visible. Never infer activity that you cannot see."
)
GATE_PROMPT = (
    "Assess this volcano webcam frame.\n"
    "1. Is it usable for measuring a volcanic plume or lava fountain, or is the view blocked "
    "(cloud, fog, darkness, rain on the lens, glare, frozen or corrupted image)? Explain briefly.\n"
    "2. Transcribe any timestamp printed on the image exactly as written, and convert it to "
    "ISO 8601 keeping the printed time zone (leave the offset out if no zone is printed). "
    "Use empty strings if there is no readable timestamp. Also transcribe any camera label.\n"
    "3. Transcribe any pan/tilt/zoom readout printed on the image exactly as written, for example "
    "'P: 29, T: +0.00, Z: 29 1.0'. Use an empty string if there is none.\n"
    "4. List the visible features, classify the activity, and describe the scene in English and Spanish."
)
GATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "usable": {"type": "boolean"},
        "view": {"type": "string", "enum": [
            "clear", "partly_obscured", "obscured_by_cloud_or_fog", "night_dark", "night_with_glow",
            "rain_or_lens_water", "glare", "frozen_or_corrupted"]},
        "usable_reason": {"type": "string"},
        "printed_timestamp_text": {"type": "string"},
        "printed_timestamp_iso": {"type": "string"},
        "printed_camera_label": {"type": "string"},
        "printed_ptz_text": {"type": "string"},
        "visible_features": {"type": "array", "items": {"type": "string", "enum": [
            "crater", "crater_floor", "vent", "lava_lake", "lava_fountain", "incandescent_glow",
            "volcanic_plume", "steam", "gas_haze", "ash_cloud", "meteorological_cloud", "fog",
            "blue_sky", "night_sky", "people", "structures"]}},
        "activity": {"type": "string", "enum": [
            "no_visible_activity", "degassing", "steaming", "ash_emission", "lava_fountaining",
            "lava_lake_activity", "unclear"]},
        "description_en": {"type": "string"},
        "description_es": {"type": "string"},
    },
    "additionalProperties": False,
}
GATE_SCHEMA["required"] = list(GATE_SCHEMA["properties"])

# e.g. "P: +178.54, T: -0.06, Z: 959 3.9": pan, tilt, then the raw zoom position and the zoom factor
_PTZ = re.compile(r"P:\s*(?P<pan>[+-]?\d+(?:\.\d+)?)\s*,\s*T:\s*(?P<tilt>[+-]?\d+(?:\.\d+)?)\s*,\s*"
                  r"Z:\s*(?P<zoom_raw>\d+(?:\.\d+)?)(?:\s+(?P<zoom>\d+(?:\.\d+)?))?")


@dataclass(frozen=True)
class SparkAssessment:
    usable: bool
    view: str
    reason: str
    printed_time_text: str
    printed_time: datetime | None  # UTC; None if unreadable or printed without a zone
    printed_ptz: dict[str, float] | None
    answer: dict[str, Any]


@dataclass(frozen=True)
class FrameVerdict:
    frame_id: int
    usable: bool
    decided_by: Literal["local", "spark"]
    local: LocalVerdict
    reasons: tuple[str, ...]  # the local reasons, plus timestamp_mismatch from the printed time
    stats: ImageStats
    sun_elevation: float | None
    change: float | None
    spark: SparkAssessment | None = None


@dataclass
class GateReport:
    verdicts: list[FrameVerdict] = field(default_factory=list)
    skipped: int = 0  # frames that already had a verdict
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        usable = sum(v.usable for v in self.verdicts)
        rejected = Counter(reason for v in self.verdicts if not v.usable for reason in v.reasons)
        details = ", ".join(f"{reason} {count}" for reason, count in sorted(rejected.items()))
        spark = sum(v.decided_by == "spark" for v in self.verdicts)
        return (f"{len(self.verdicts)} assessed, {usable} usable, {len(self.verdicts) - usable} rejected"
                + (f" ({details})" if details else "")
                + f", {spark} by Muse Spark, {self.skipped} already assessed, {len(self.errors)} failed")


def parse_ptz(text: str) -> dict[str, float] | None:
    """Read a printed pan/tilt/zoom readout; None if the text holds none."""
    match = _PTZ.search(text or "")
    if match is None:
        return None
    return {key: float(value) for key, value in match.groupdict().items() if value is not None}


def read_answer(answer: dict[str, Any]) -> SparkAssessment:
    return SparkAssessment(
        usable=bool(answer["usable"]),
        view=answer["view"],
        reason=answer["usable_reason"],
        printed_time_text=answer["printed_timestamp_text"],
        printed_time=_printed_time(answer["printed_timestamp_iso"]),
        printed_ptz=parse_ptz(answer["printed_ptz_text"]),
        answer=answer,
    )


class QualityGate:
    def __init__(
        self,
        conn: sqlite3.Connection,
        data_dir: str | Path,
        sources: Sources,
        client: MetaClient | None = None,
        thresholds: Thresholds = Thresholds(),
        clock: Callable[[], datetime] = utcnow,
    ):
        self._conn = conn
        self._data_dir = Path(data_dir)
        self._sources = sources
        self._cameras = {camera.id: camera for camera in sources.cameras}
        self._client = client
        self._thresholds = thresholds
        self._clock = clock
        self._last: dict[str, tuple[int, np.ndarray]] = {}  # camera id -> (frame id, fingerprint)

    def assess(self, frame_id: int, *, spark: SparkMode = "uncertain", now: datetime | None = None) -> FrameVerdict:
        """Assess one stored frame and store its verdict, replacing any earlier one.

        `spark` says which frames Muse Spark sees: none, those the local
        checks find uncertain, or all that they do not reject. `now` (live
        use) also rejects frames captured more than 30 minutes before it.
        """
        frame = self._conn.execute("SELECT * FROM frames WHERE id = ?", (frame_id,)).fetchone()
        if frame is None:
            raise ValueError(f"no frame with id {frame_id}")
        camera = self._cameras.get(frame["camera_id"])
        if camera is None:
            raise ValueError(f"frame {frame_id}: camera {frame['camera_id']} is not in the sources file")
        volcano = self._sources.volcanoes[camera.volcano]
        captured_at = parse_utc(frame["captured_at"])
        image = _open_rgb(self._data_dir / frame["path"])
        stats, current = measure(image), fingerprint(image)
        previous = self._previous_fingerprint(frame)
        change = difference(previous, current) if previous is not None else None
        self._last[frame["camera_id"]] = (frame_id, current)
        sun = (solar_elevation(captured_at, volcano.lat, volcano.lon)
               if volcano.lat is not None and volcano.lon is not None else None)
        local = check_local(stats, kind=camera.kind, captured_at=captured_at, sun_elevation=sun, change=change,
                            now=now, thresholds=self._thresholds)
        verdict = FrameVerdict(frame_id, usable=local.decision == "pass", decided_by="local", local=local,
                               reasons=local.reasons, stats=stats, sun_elevation=sun, change=change)
        if ((spark == "all" and local.decision != "reject")
                or (spark == "uncertain" and local.decision == "uncertain")):
            verdict = self._ask_spark(verdict, frame["path"], captured_at)
        self._store(verdict)
        return verdict

    def assess_range(self, camera_id: str, start: datetime, end: datetime, *,
                     spark: SparkMode = "uncertain", redo: bool = False) -> GateReport:
        """Assess the camera's frames captured between start and end (inclusive), oldest first.

        Frames that already have a verdict are skipped unless `redo`. A failed
        Muse Spark call leaves its frame without a verdict, and the rest go on.
        """
        report = GateReport()
        frames = self._conn.execute(
            """SELECT f.id, q.frame_id IS NOT NULL AS assessed
               FROM frames f LEFT JOIN frame_quality q ON q.frame_id = f.id
               WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ?
               ORDER BY f.captured_at""",
            (camera_id, to_iso(start), to_iso(end)),
        ).fetchall()
        for frame in frames:
            if frame["assessed"] and not redo:
                report.skipped += 1
                continue
            try:
                report.verdicts.append(self.assess(frame["id"], spark=spark))
            except (openai.APIError, json.JSONDecodeError) as exc:
                log.warning("frame %s: Muse Spark failed: %s", frame["id"], exc)
                report.errors.append(f"frame {frame['id']}: {type(exc).__name__}: {exc}"[:300])
        return report

    def _previous_fingerprint(self, frame: sqlite3.Row) -> np.ndarray | None:
        previous = self._conn.execute(
            "SELECT id, path FROM frames WHERE camera_id = ? AND captured_at < ? ORDER BY captured_at DESC LIMIT 1",
            (frame["camera_id"], frame["captured_at"]),
        ).fetchone()
        if previous is None:
            return None
        cached = self._last.get(frame["camera_id"])
        if cached is not None and cached[0] == previous["id"]:
            return cached[1]
        return fingerprint(_open_rgb(self._data_dir / previous["path"]))

    def _ask_spark(self, verdict: FrameVerdict, path: str, captured_at: datetime) -> FrameVerdict:
        if self._client is None:
            raise RuntimeError(f"frame {verdict.frame_id} needs Muse Spark but the gate has no Meta client; "
                               "pass spark='never' to assess it locally")
        _, jpeg = load_for_upload(self._data_dir / path)
        answer = self._client.ask_json(prompt=GATE_PROMPT, images=[jpeg], schema_name="frame_assessment",
                                       schema=GATE_SCHEMA, instructions=GATE_INSTRUCTIONS, purpose="gate:assess")
        assessment = read_answer(answer)
        reasons = verdict.reasons
        if assessment.printed_time is not None and abs(assessment.printed_time - captured_at) > TIMESTAMP_TOLERANCE:
            reasons += ("timestamp_mismatch",)
        return dataclasses.replace(verdict, usable=assessment.usable and "timestamp_mismatch" not in reasons,
                                   decided_by="spark", reasons=reasons, spark=assessment)

    def _store(self, verdict: FrameVerdict) -> None:
        spark = verdict.spark
        spark_columns = (None,) * 6 if spark is None else (
            spark.view,
            spark.reason,
            spark.printed_time_text,
            to_iso(spark.printed_time) if spark.printed_time else None,
            json.dumps(spark.printed_ptz) if spark.printed_ptz else None,
            json.dumps(spark.answer, ensure_ascii=False),
        )
        self._conn.execute(
            """INSERT OR REPLACE INTO frame_quality (
                   frame_id, assessed_at, usable, decided_by, local_decision, reasons, sun_elevation_deg,
                   brightness, contrast, edge_density, glow_fraction, change,
                   spark_view, spark_reason, printed_time_text, printed_time, printed_ptz, spark_answer)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (verdict.frame_id, to_iso(self._clock()), int(verdict.usable), verdict.decided_by,
             verdict.local.decision, json.dumps(list(verdict.reasons)), verdict.sun_elevation,
             verdict.stats.brightness, verdict.stats.contrast, verdict.stats.edge_density,
             verdict.stats.glow_fraction, verdict.change, *spark_columns),
        )
        self._conn.commit()


def _printed_time(iso: str) -> datetime | None:
    """The printed timestamp in UTC; None if missing, malformed or printed without a zone."""
    if not iso:
        return None
    try:
        return parse_utc(iso)
    except ValueError:
        return None


def _open_rgb(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB")
```

- [ ] **Step 5: Run the tests to see them pass, then the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gate.py -v` → 25 passed
Run: `.venv/Scripts/python.exe -m pytest` → 160 passed

- [ ] **Step 6: Commit**

```bash
git add vigia/db.py vigia/gate.py tests/test_gate.py
git commit -m "Add the quality gate: local verdicts, Muse Spark for hazy frames"
```

---

### Task 5: `vigia-quality` CLI, and the smoke test uses the gate's prompt

**Files:**
- Modify: `vigia/gate.py`, `pyproject.toml`, `scripts/smoke_test.py`, `tests/test_gate.py`

- [ ] **Step 1: Write the failing CLI tests** (append to `tests/test_gate.py`; add `from vigia import db` and `from vigia.gate import main` to its imports)

```python
SOURCES_YAML = """
volcanoes:
  kilauea:
    name: Kīlauea
    country: United States
    official_agency: USGS Hawaiian Volcano Observatory
    official_url: https://www.usgs.gov/volcanoes/kilauea
    lat: 19.405
    lon: -155.29
cameras:
  - id: kilauea-v1
    name: V1cam
    volcano: kilauea
    url: https://example.org/V1cam/images/M.jpg
    license: Public Domain
    attribution: U.S. Geological Survey
"""
WINDOW = ["--start", "2026-10-17T21:00Z", "--end", "2026-10-17T23:00Z"]


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(SOURCES_YAML, encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigia.sqlite"))
    return tmp_path / "data"


def test_cli_assesses_the_window_locally_and_prints_a_summary(cli_env, capsys):
    conn = db.connect(cli_env / "vigia.sqlite")
    store = FrameStore(conn, cli_env)
    add(store, sharp(), DAY)
    add(store, flat(150), DAY + timedelta(minutes=2))

    main(["--camera", "kilauea-v1", *WINDOW, "--spark", "never"])

    assert capsys.readouterr().out.startswith("kilauea-v1: 2 assessed, 1 usable, 1 rejected (low_visibility 1)")
    assert conn.execute("SELECT COUNT(*) FROM frame_quality").fetchone()[0] == 2
    conn.close()


def test_cli_refuses_an_unknown_camera(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--camera", "etna-1", *WINDOW, "--spark", "never"])

    assert "etna-1" in capsys.readouterr().err


def test_cli_refuses_an_empty_window(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--camera", "kilauea-v1", "--start", "2026-10-17T23:00Z", "--end", "2026-10-17T21:00Z"])

    assert "before" in capsys.readouterr().err
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_gate.py -v`
Expected: FAIL with `ImportError: cannot import name 'main' from 'vigia.gate'`

- [ ] **Step 2: Add the CLI** — in `vigia/gate.py` add `import argparse` and `from contextlib import closing` to the standard-library imports, replace `from vigia.config import Sources` with

```python
from vigia import db
from vigia.config import Sources, load_sources
```

add `from vigia.meta.ledger import CostLedger` and `from vigia.settings import Settings` after the `vigia.meta.client` import, add this paragraph at the end of the module docstring:

```text
    vigia-quality --camera kilauea-k2 --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z
```

and append:

```python
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Assess stored frames: local checks first, then Muse Spark "
                                                 "for the frames they cannot decide.")
    parser.add_argument("--camera", action="append", required=True, help="camera id; repeat it for several")
    parser.add_argument("--start", type=parse_utc, required=True, help="first capture time, e.g. 2026-10-17T13:00Z")
    parser.add_argument("--end", type=parse_utc, required=True, help="last capture time, e.g. 2026-10-17T19:30Z")
    parser.add_argument("--spark", choices=["never", "uncertain", "all"], default="uncertain",
                        help="frames Muse Spark sees: none, those the local checks cannot decide (default), "
                             "or all that they do not reject")
    parser.add_argument("--redo", action="store_true", help="assess again frames that already have a verdict")
    args = parser.parse_args(argv)
    if args.start >= args.end:
        parser.error("--start must be before --end")

    settings = Settings.from_env()
    sources = load_sources(settings.sources_path)
    known = {camera.id for camera in sources.cameras}
    for camera_id in args.camera:
        if camera_id not in known:
            parser.error(f"unknown camera {camera_id!r} in {settings.sources_path}")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with closing(db.connect(settings.db_path)) as conn:
        client = None if args.spark == "never" else MetaClient.from_env(CostLedger(conn, settings.daily_budget_usd))
        gate = QualityGate(conn, settings.data_dir, sources, client)
        for camera_id in args.camera:
            report = gate.assess_range(camera_id, args.start, args.end, spark=args.spark, redo=args.redo)
            print(f"{camera_id}: {report.summary()}")


if __name__ == "__main__":
    main()
```

In `pyproject.toml` `[project.scripts]` add:

```toml
vigia-quality = "vigia.gate:main"
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_gate.py -v` → 28 passed

- [ ] **Step 3: Point the smoke test at the package's prompt and schema** — in `scripts/smoke_test.py`:
  - delete `ASSESS_INSTRUCTIONS`, `ASSESS_PROMPT`, `ASSESS_SCHEMA` and the `ASSESS_SCHEMA["required"] = ...` line;
  - add `from vigia.gate import GATE_INSTRUCTIONS, GATE_PROMPT, GATE_SCHEMA` after `from vigia.imaging import load_for_upload`;
  - in `analyze_image`, replace the whole `else:` branch of `if client is None:` with:

```python
    else:
        assessment = client.ask_json(prompt=GATE_PROMPT, images=[jpeg], schema_name="frame_assessment",
                                     schema=GATE_SCHEMA, instructions=GATE_INSTRUCTIONS, purpose="smoke:assess")
        (out / "assessment.json").write_text(json.dumps(assessment, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[{out.name}] assessment: usable={assessment['usable']} view={assessment['view']} "
              f"timestamp={assessment['printed_timestamp_text']!r}")
        lines += ["### Muse Spark assessment", "",
                  "| usable | view | printed timestamp | ISO | camera label | PTZ | activity |",
                  "|---|---|---|---|---|---|---|",
                  f"| {assessment['usable']} | {assessment['view']} | {assessment['printed_timestamp_text']} "
                  f"| {assessment['printed_timestamp_iso']} | {assessment['printed_camera_label']} "
                  f"| {assessment['printed_ptz_text']} | {assessment['activity']} |", "",
                  f"Why: {assessment['usable_reason']}", "",
                  f"Visible: {', '.join(assessment['visible_features'])}", "",
                  f"EN: {assessment['description_en']}", "",
                  f"ES: {assessment['description_es']}", ""]
```

Run: `.venv/Scripts/python.exe scripts/smoke_test.py --help`
Expected: the usage text (the imports work). Do not run the smoke test itself: it calls the paid API.

- [ ] **Step 4: Register the console script and run the suite**

Run: `.venv/Scripts/python.exe -m pip install -e ".[dev]" -q` then `.venv/Scripts/vigia-quality.exe --help`
Expected: usage listing `--camera`, `--start`, `--end`, `--spark`, `--redo`
Run: `.venv/Scripts/python.exe -m pytest` → 163 passed

- [ ] **Step 5: Commit**

```bash
git add vigia/gate.py pyproject.toml scripts/smoke_test.py tests/test_gate.py
git commit -m "Add vigia-quality CLI and share the gate prompt with the smoke test"
```

---

### Task 6: Mask and video helpers for tracking

**Files:**
- Create: `vigia/masks.py`, `tests/test_masks.py`
- Modify: `vigia/meta/sam.py`, `vigia/video.py`, `tests/test_sam.py`, `tests/test_video.py`

- [ ] **Step 1: Write the failing mask tests** (`tests/test_masks.py`)

```python
import numpy as np
import pytest
from meta_sam_parser import CompletedOutcome, decode_mask_to_raster, decode_mask_to_rle, image_segmentation_format

from test_sam import IMAGE_OUTPUT
from vigia.masks import decode, encode


def sam_masks():
    """The mask records of the docs' sample SAM output."""
    parser = image_segmentation_format().create_parser()
    for _ in parser.push(IMAGE_OUTPUT):
        pass
    return [record.mask for record in parser.finish(CompletedOutcome()).result.records if record.kind == "mask"]


def test_encode_matches_the_sam_parser_rle():
    for mask in sam_masks():
        raster = np.frombuffer(decode_mask_to_raster(mask), dtype=np.uint8).reshape(mask.height, mask.width)
        expected = decode_mask_to_rle(mask)

        assert encode(raster.astype(bool)) == {"size": list(expected.size), "counts": expected.counts}


@pytest.mark.parametrize("mask", [
    np.random.default_rng(1).random((37, 53)) > 0.6,
    np.ones((4, 5), dtype=bool),
    np.zeros((4, 5), dtype=bool),
    np.eye(6, dtype=bool),
    np.pad(np.ones((300, 200), dtype=bool), 50),
], ids=["random", "full", "empty", "diagonal", "large blob"])
def test_decode_reverses_encode(mask):
    decoded = decode(encode(mask))

    assert decoded.dtype == bool
    assert np.array_equal(decoded, mask)


def test_decode_rejects_runs_that_do_not_fill_the_size():
    counts = encode(np.ones((4, 5), dtype=bool))["counts"]

    with pytest.raises(ValueError, match="not 5x5"):
        decode({"size": [5, 5], "counts": counts})
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_masks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigia.masks'`

- [ ] **Step 2: Create `vigia/masks.py`**

```python
"""COCO run-length encoding of boolean masks.

The format of pycocotools and of meta_sam_parser.decode_mask_to_rle: pixels in
column-major order, alternating runs of 0s and 1s that start with 0s, and the
run lengths packed into a string (5 bits per character plus a continuation
bit, offset 48; each run after the second is stored as the difference from
the run two before it).
"""

from __future__ import annotations

from typing import Any

import numpy as np


def encode(mask: np.ndarray) -> dict[str, Any]:
    """{"size": [height, width], "counts": "..."} for a 2-D boolean mask."""
    height, width = mask.shape
    flat = np.asarray(mask, dtype=bool).ravel(order="F")
    starts = np.flatnonzero(flat[1:] != flat[:-1]) + 1
    runs = np.diff(np.concatenate(([0], starts, [flat.size]))).tolist()
    if flat.size and flat[0]:
        runs.insert(0, 0)
    return {"size": [height, width], "counts": _to_string(runs)}


def decode(rle: dict[str, Any]) -> np.ndarray:
    """The boolean mask of an RLE made by `encode` (or by pycocotools)."""
    height, width = rle["size"]
    runs = _from_string(rle["counts"])
    if sum(runs) != height * width:
        raise ValueError(f"RLE runs cover {sum(runs)} pixels, not {height}x{width}")
    values = np.zeros(len(runs), dtype=bool)
    values[1::2] = True
    return np.repeat(values, runs).reshape((width, height)).T


def _to_string(runs: list[int]) -> str:
    chars = []
    for i, run in enumerate(runs):
        value = run - runs[i - 2] if i > 2 else run
        more = True
        while more:
            chunk = value & 0x1F
            value >>= 5
            more = value != -1 if chunk & 0x10 else value != 0
            if more:
                chunk |= 0x20
            chars.append(chr(chunk + 48))
    return "".join(chars)


def _from_string(counts: str) -> list[int]:
    runs: list[int] = []
    position = 0
    while position < len(counts):
        value, shift, more = 0, 0, True
        while more:
            chunk = ord(counts[position]) - 48
            value |= (chunk & 0x1F) << (5 * shift)
            more = bool(chunk & 0x20)
            position += 1
            shift += 1
            if not more and chunk & 0x10:
                value |= -1 << (5 * shift)
        if len(runs) > 2:
            value += runs[-2]
        runs.append(value)
    return runs
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_masks.py -v` → 7 passed

- [ ] **Step 3: Write the failing `fit_mask` and `assemble` tests**

Append to `tests/test_sam.py` (and change its import to `from vigia.meta.sam import SamParseError, fit_mask, parse_output`):

```python
def test_fit_mask_scales_up_and_down_by_nearest_neighbour():
    checker = np.array([[True, False], [False, True]])

    up = fit_mask(checker, 4, 6)

    assert up.shape == (4, 6)
    assert up[:2, :3].all() and not up[:2, 3:].any()
    assert np.array_equal(fit_mask(up, 2, 2), checker)
```

Append to `tests/test_video.py`:

```python
def test_assemble_can_scale_to_a_height(source, tmp_path):
    clip = cut_clip(source, tmp_path / "clip.mp4", start_s=0, duration_s=1.0, fps=5, height=240)
    frames = extract_frames(clip, tmp_path / "frames")

    info = probe(assemble(frames, tmp_path / "out.mp4", fps=5, height=120))

    assert (info.width, info.height, info.frames) == (160, 120, 5)
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_sam.py tests/test_video.py -v`
Expected: FAIL: `fit_mask` cannot be imported; `assemble()` got an unexpected keyword argument `height`

- [ ] **Step 4: Make `fit_mask` public** — in `vigia/meta/sam.py`, rename `_fit_to_box` to `fit_mask`, call it from `parse_output` as `mask=fit_mask(raster.astype(bool), bounds.bottom - bounds.top, bounds.right - bounds.left)`, and give it this signature and docstring (the body stays, with `raster` renamed to `mask`):

```python
def fit_mask(mask: np.ndarray, height: int, width: int) -> np.ndarray:
    """Scale a mask to height x width, nearest neighbour.

    SAM sends large masks at reduced resolution (a 1081x680 px box came with a
    1024x644 raster), and tracking maps masks from the video's pixels back to
    the frame's, so a mask often needs another size.
    """
    if mask.shape == (height, width):
        return mask
    rows = ((np.arange(height) + 0.5) * mask.shape[0] / height).astype(int)
    cols = ((np.arange(width) + 0.5) * mask.shape[1] / width).astype(int)
    return mask[np.ix_(rows, cols)]
```

- [ ] **Step 5: Let `assemble` scale** — in `vigia/video.py` replace `assemble` with:

```python
def assemble(frames: Sequence[str | Path], dst: str | Path, *, fps: float, height: int | None = None) -> Path:
    """Encode an ordered list of same-sized images into an H.264 MP4.

    With `height` (even) the video is scaled to it, keeping the aspect ratio.
    """
    suffix = Path(frames[0]).suffix
    scale = f"scale=-2:{height}" if height else "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    with tempfile.TemporaryDirectory() as tmp:
        for i, frame in enumerate(frames):
            shutil.copyfile(frame, Path(tmp) / f"{i:05d}{suffix}")
        _run([
            "ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-start_number", "0",
            "-i", str(Path(tmp) / f"%05d{suffix}"),
            "-vf", scale,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst),
        ])
    return Path(dst)
```

- [ ] **Step 6: Run the tests, then the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sam.py tests/test_video.py -v` → all pass
Run: `.venv/Scripts/python.exe -m pytest` → 172 passed

- [ ] **Step 7: Commit**

```bash
git add vigia/masks.py vigia/meta/sam.py vigia/video.py tests/test_masks.py tests/test_sam.py tests/test_video.py
git commit -m "Encode masks as COCO RLE and let tracking scale videos and masks"
```

---

### Task 7: Tracking storage and window selection

**Files:**
- Create: `vigia/tracking.py`, `tests/test_tracking.py`
- Modify: `vigia/db.py`

- [ ] **Step 1: Write the failing tests** (`tests/test_tracking.py`)

```python
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from conftest import make_jpeg
from vigia import masks
from vigia.ingest.store import FrameStore
from vigia.tracking import detection_mask, unassessed_frames, usable_frames

T0 = datetime(2026, 10, 17, 18, 0, 2, tzinfo=timezone.utc)


@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def add_frame(store, conn, minutes, usable=True, size=(64, 48), camera_id="kilauea-k2"):
    """Store a frame `minutes` after T0 with a quality verdict (usable=None: no verdict yet)."""
    frame_id = store.add(camera_id, make_jpeg(color=(10 + 3 * minutes, 80, 40), size=size),
                         captured_at=T0 + timedelta(minutes=minutes), timestamp_source="ashcam", fetched_at=T0)
    if usable is not None:
        conn.execute(
            """INSERT INTO frame_quality (frame_id, assessed_at, usable, decided_by, local_decision, reasons,
                                          brightness, contrast, edge_density, glow_fraction)
               VALUES (?, '2026-10-28T00:00:00Z', ?, 'local', ?, '[]', 100, 40, 0.1, 0)""",
            (frame_id, int(usable), "pass" if usable else "reject"),
        )
        conn.commit()
    return frame_id


def test_the_database_has_tracking_tables(conn):
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert {"tracking_runs", "tracks", "detections"} <= tables


def test_usable_frames_keeps_the_cameras_usable_frames_in_the_window_oldest_first(store, conn, tmp_path):
    later, first, middle = (add_frame(store, conn, minutes) for minutes in (4, 0, 2))
    add_frame(store, conn, 6, usable=False)
    add_frame(store, conn, 8, usable=None)
    add_frame(store, conn, 10)  # after the window
    add_frame(store, conn, 2, camera_id="kilauea-kp")

    frames = usable_frames(conn, tmp_path, "kilauea-k2", T0, T0 + timedelta(minutes=9))

    assert [f.id for f in frames] == [first, middle, later]
    assert frames[0].captured_at == T0
    assert frames[0].path.is_file() and (frames[0].width, frames[0].height) == (64, 48)


def test_unassessed_frames_counts_frames_without_a_verdict(store, conn):
    add_frame(store, conn, 0)
    add_frame(store, conn, 2, usable=None)
    add_frame(store, conn, 4, usable=None)

    assert unassessed_frames(conn, "kilauea-k2", T0, T0 + timedelta(minutes=5)) == 2


def test_detection_mask_places_the_box_mask_in_the_frame():
    box_mask = np.zeros((3, 4), dtype=bool)
    box_mask[1, 1:3] = True
    detection = {"id": 1, "box_left": 10, "box_top": 5, "box_right": 14, "box_bottom": 8,
                 "mask_rle": json.dumps(masks.encode(box_mask))}

    full = detection_mask(detection, width=20, height=10)

    assert full.shape == (10, 20) and full.sum() == 2
    assert full[6, 11] and full[6, 12]


def test_detection_mask_refuses_a_mask_that_does_not_fit_its_box():
    detection = {"id": 7, "box_left": 0, "box_top": 0, "box_right": 4, "box_bottom": 4,
                 "mask_rle": json.dumps(masks.encode(np.ones((3, 4), dtype=bool)))}

    with pytest.raises(ValueError, match="detection 7"):
        detection_mask(detection, width=10, height=10)
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigia.tracking'`

- [ ] **Step 2: Add the tracking tables** — in `vigia/db.py`, append to `SCHEMA` after `frame_quality`:

```sql
CREATE TABLE IF NOT EXISTS tracking_runs (   -- one SAM video request: one phrase over one window of frames
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id    TEXT    NOT NULL,
    target       TEXT    NOT NULL,  -- plume | fountain | incandescence
    phrase       TEXT    NOT NULL,
    window_start TEXT    NOT NULL,  -- UTC capture time of the window's first frame
    window_end   TEXT    NOT NULL,  -- UTC capture time of its last frame
    frame_ids    TEXT    NOT NULL,  -- JSON list; video frame i is frame_ids[i]
    video_width  INTEGER NOT NULL,
    video_height INTEGER NOT NULL,
    created_at   TEXT    NOT NULL,  -- UTC
    UNIQUE (camera_id, phrase, window_start, window_end)
);

CREATE TABLE IF NOT EXISTS tracks (          -- one SAM object of a run
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL REFERENCES tracking_runs (id),
    object_id  TEXT    NOT NULL,  -- SAM's id, stable within its run
    first_seen TEXT    NOT NULL,  -- UTC capture time of its first detection
    last_seen  TEXT    NOT NULL,
    detections INTEGER NOT NULL,
    UNIQUE (run_id, object_id)
);

CREATE TABLE IF NOT EXISTS detections (      -- one tracked object on one frame
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id   INTEGER NOT NULL REFERENCES tracks (id),
    frame_id   INTEGER NOT NULL REFERENCES frames (id),
    box_left   INTEGER NOT NULL,  -- half-open box in the frame's own pixels
    box_top    INTEGER NOT NULL,
    box_right  INTEGER NOT NULL,
    box_bottom INTEGER NOT NULL,
    score      REAL,
    area_px    INTEGER NOT NULL,  -- mask pixels at the frame's resolution
    mask_rle   TEXT    NOT NULL   -- JSON COCO RLE of the box-sized mask: {"size": [h, w], "counts": "..."}
);
CREATE INDEX IF NOT EXISTS idx_detections_frame ON detections (frame_id);
CREATE INDEX IF NOT EXISTS idx_detections_track ON detections (track_id);
```

- [ ] **Step 3: Create `vigia/tracking.py`**

```python
"""Track plumes and fountains through timelapses of usable frames with SAM 3.1 video.

A window is a camera's usable frames (see vigia.gate) between two capture
times, oldest first. It is encoded into one MP4 (10 fps, at most 1080 px
high), uploaded once and tracked once per phrase of config/prompts.yaml. Each
SAM request is a tracking run; each SAM object in a run is a track; each
object on one frame is a detection, stored in that frame's own pixels with its
mask as COCO RLE (vigia.masks).

Cost rule: SAM bills at least 50 frames per video request, so backfills send
windows of 50 frames or more (vigia-track refuses fewer by default); live
tracking uses one window per camera per hour.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from vigia import masks
from vigia.timeutil import parse_utc, to_iso


@dataclass(frozen=True)
class WindowFrame:
    id: int
    captured_at: datetime
    path: Path
    width: int
    height: int


def usable_frames(conn: sqlite3.Connection, data_dir: str | Path, camera_id: str,
                  start: datetime, end: datetime) -> list[WindowFrame]:
    """The camera's frames judged usable, captured between start and end (inclusive), oldest first."""
    rows = conn.execute(
        """SELECT f.id, f.captured_at, f.path, f.width, f.height
           FROM frames f JOIN frame_quality q ON q.frame_id = f.id
           WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ? AND q.usable = 1
           ORDER BY f.captured_at""",
        (camera_id, to_iso(start), to_iso(end)),
    ).fetchall()
    return [WindowFrame(row["id"], parse_utc(row["captured_at"]), Path(data_dir) / row["path"],
                        row["width"], row["height"]) for row in rows]


def unassessed_frames(conn: sqlite3.Connection, camera_id: str, start: datetime, end: datetime) -> int:
    """How many of the camera's frames in the window have no quality verdict yet."""
    return conn.execute(
        """SELECT COUNT(*) FROM frames f LEFT JOIN frame_quality q ON q.frame_id = f.id
           WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ? AND q.frame_id IS NULL""",
        (camera_id, to_iso(start), to_iso(end)),
    ).fetchone()[0]


def detection_mask(detection: Mapping[str, Any], width: int, height: int) -> np.ndarray:
    """A stored detection's mask over its whole frame (height x width, bool)."""
    box_mask = masks.decode(json.loads(detection["mask_rle"]))
    left, top = detection["box_left"], detection["box_top"]
    right, bottom = detection["box_right"], detection["box_bottom"]
    if box_mask.shape != (bottom - top, right - left):
        raise ValueError(f"detection {detection['id']}: mask {box_mask.shape} does not fit its box")
    full = np.zeros((height, width), dtype=bool)
    full[top:bottom, left:right] = box_mask
    return full
```

- [ ] **Step 4: Run the tests, then the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking.py -v` → 5 passed
Run: `.venv/Scripts/python.exe -m pytest` → 177 passed

- [ ] **Step 5: Commit**

```bash
git add vigia/db.py vigia/tracking.py tests/test_tracking.py
git commit -m "Store tracking runs and select a camera's usable frames"
```

---

### Task 8: Track a window with SAM 3.1 video

**Files:**
- Modify: `vigia/tracking.py`, `tests/test_tracking.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_tracking.py`; add `import shutil`, `import httpx`, `from test_meta_client import make_client, response_body, sse`, `from test_sam import OBJ_0`, `from vigia.config import Camera`, `from vigia.prompts import Prompts` to its imports, and `track_window` to the `vigia.tracking` import)

```python
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

K2 = Camera(id="kilauea-k2", name="K2cam", volcano="kilauea", url="https://example.org/K2.jpg",
            license="Public Domain", attribution="U.S. Geological Survey")
PROMPTS = Prompts(plume={"visible": ["steam"]}, fountain={"visible": ["lava fountain"]})
UPLOADED = {"id": "file-1", "object": "file", "bytes": 1000, "created_at": 1793000000,
            "filename": "window.mp4", "purpose": "user_data"}
SERVER_ERROR = {"error": {"message": "boom", "type": "server_error", "param": None, "code": None}}


class FakeMeta:
    """The Files API plus streamed SAM video answers, one output text per phrase; records every request."""

    def __init__(self, outputs, failing=()):
        self.outputs = outputs
        self.failing = failing
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/v1/files":
            return httpx.Response(200, json=UPLOADED)
        if request.method == "DELETE":
            return httpx.Response(200, json={"id": "file-1", "object": "file", "deleted": True})
        phrase = json.loads(request.content)["input"][0]["content"][0]["text"]
        if phrase in self.failing:
            return httpx.Response(500, json=SERVER_ERROR)
        final = response_body("sam-3.1", "", {"video_frames_processed": 50})
        events = [{"type": "response.created", "sequence_number": 0,
                   "response": {**final, "status": "in_progress", "output": []}}]
        if self.outputs[phrase]:
            events.append({"type": "response.output_text.delta", "sequence_number": 1, "item_id": "msg_1",
                           "output_index": 0, "content_index": 0, "delta": self.outputs[phrase], "logprobs": []})
        events.append({"type": "response.completed", "sequence_number": 2, "response": final})
        return httpx.Response(200, content=sse(events), headers={"content-type": "text/event-stream"})

    def calls(self):
        return [(request.method, request.url.path) for request in self.requests]


def window(store, conn, count=3, size=(640, 668)):
    """`count` usable frames, 2 minutes apart from T0, twice the size of the 320x334 SAM sample."""
    return [add_frame(store, conn, 2 * i, size=size) for i in range(count)]


def track(fake, conn, tmp_path, **kwargs):
    return track_window(make_client(fake, conn), conn, tmp_path, K2, PROMPTS, T0, T0 + timedelta(hours=1),
                        max_height=334, **kwargs)


@needs_ffmpeg
def test_track_window_stores_runs_tracks_and_detections_in_frame_pixels(store, conn, tmp_path):
    ids = window(store, conn)
    fake = FakeMeta({"steam": f"<0f>{OBJ_0}\n<2f>{OBJ_0}\n", "lava fountain": ""})

    report = track(fake, conn, tmp_path)

    assert report.video_size == (320, 334)
    plume, fountain = report.runs
    assert (plume.target, plume.tracks, plume.detections) == ("plume", 1, 2)
    assert (plume.first_seen, plume.last_seen) == (T0, T0 + timedelta(minutes=4))
    assert (fountain.target, fountain.tracks, fountain.first_seen) == ("fountain", 0, None)
    run = conn.execute("SELECT * FROM tracking_runs WHERE id = ?", (plume.run_id,)).fetchone()
    assert json.loads(run["frame_ids"]) == ids
    rows = conn.execute("SELECT * FROM detections ORDER BY frame_id").fetchall()
    assert [row["frame_id"] for row in rows] == [ids[0], ids[2]]
    first = rows[0]
    assert (first["box_left"], first["box_top"], first["box_right"], first["box_bottom"]) == (422, 456, 542, 510)
    assert first["area_px"] == 4 * 1539
    assert first["score"] == pytest.approx(0.96)
    assert detection_mask(first, width=640, height=668).sum() == 4 * 1539


@needs_ffmpeg
def test_track_window_uploads_the_window_once_and_deletes_it(store, conn, tmp_path):
    window(store, conn)
    fake = FakeMeta({"steam": "", "lava fountain": ""})

    track(fake, conn, tmp_path)

    assert fake.calls() == [("POST", "/v1/files"), ("POST", "/v1/responses"), ("POST", "/v1/responses"),
                            ("DELETE", "/v1/files/file-1")]
    assert [row["purpose"] for row in conn.execute("SELECT purpose FROM api_calls ORDER BY id")] == [
        "track:plume", "track:fountain"]


@needs_ffmpeg
def test_track_window_refuses_a_window_it_already_tracked_unless_redo(store, conn, tmp_path):
    window(store, conn)
    track(FakeMeta({"steam": f"<0f>{OBJ_0}\n", "lava fountain": ""}), conn, tmp_path)
    again = FakeMeta({"steam": "", "lava fountain": ""})

    with pytest.raises(ValueError, match="already tracked"):
        track(again, conn, tmp_path)
    assert again.requests == []

    track(again, conn, tmp_path, redo=True)
    assert conn.execute("SELECT COUNT(*) FROM tracking_runs").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0] == 0


@needs_ffmpeg
def test_a_failed_phrase_is_reported_and_the_others_go_on(store, conn, tmp_path):
    window(store, conn)
    fake = FakeMeta({"lava fountain": ""}, failing={"steam"})

    report = track(fake, conn, tmp_path)

    assert [run.phrase for run in report.runs] == ["lava fountain"]
    assert len(report.errors) == 1 and "steam" in report.errors[0]
    assert fake.calls()[-1] == ("DELETE", "/v1/files/file-1")


def test_track_window_needs_usable_frames(store, conn, tmp_path):
    add_frame(store, conn, 0, usable=False)

    with pytest.raises(ValueError, match="no usable frames"):
        track(FakeMeta({}), conn, tmp_path)


def test_track_window_refuses_frames_of_different_sizes(store, conn, tmp_path):
    add_frame(store, conn, 0, size=(640, 668))
    add_frame(store, conn, 2, size=(320, 334))
    fake = FakeMeta({})

    with pytest.raises(ValueError, match="sizes"):
        track(fake, conn, tmp_path)
    assert fake.requests == []
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking.py -v`
Expected: FAIL with `ImportError: cannot import name 'track_window'`

- [ ] **Step 2: Implement** — in `vigia/tracking.py` replace the imports with:

```python
from __future__ import annotations

import json
import logging
import sqlite3
import tempfile
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import openai

from vigia import masks
from vigia.config import Camera
from vigia.meta.client import MetaClient, SamStreamError
from vigia.meta.sam import SamObject, SamParseError, fit_mask
from vigia.prompts import Prompts, Target
from vigia.timeutil import parse_utc, to_iso, utcnow
from vigia.video import VideoInfo, assemble, probe

log = logging.getLogger(__name__)

TARGETS: tuple[Target, ...] = ("plume", "fountain", "incandescence")
VIDEO_FPS = 10
VIDEO_MAX_HEIGHT = 1080
MIN_BILLED_FRAMES = 50
```

add after `WindowFrame`:

```python
@dataclass(frozen=True)
class RunSummary:
    run_id: int
    target: str
    phrase: str
    tracks: int
    detections: int
    first_seen: datetime | None  # capture time of the run's first detection
    last_seen: datetime | None


@dataclass
class TrackingReport:
    camera_id: str
    frames: int
    video_size: tuple[int, int] | None = None
    runs: list[RunSummary] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        size = f", video {self.video_size[0]}x{self.video_size[1]}" if self.video_size else ""
        lines = [f"{self.camera_id}: {self.frames} usable frames{size}"]
        for run in self.runs:
            seen = f", seen {to_iso(run.first_seen)} to {to_iso(run.last_seen)}" if run.first_seen else ""
            lines.append(f"  {run.target} / {run.phrase}: {run.tracks} track(s), {run.detections} detection(s){seen}")
        lines += [f"  failed: {error}" for error in self.errors]
        return "\n".join(lines)
```

and append after `detection_mask`:

```python
def track_window(
    client: MetaClient,
    conn: sqlite3.Connection,
    data_dir: str | Path,
    camera: Camera,
    prompts: Prompts,
    start: datetime,
    end: datetime,
    *,
    targets: Sequence[Target] = TARGETS,
    redo: bool = False,
    max_height: int = VIDEO_MAX_HEIGHT,
    now: Callable[[], datetime] = utcnow,
) -> TrackingReport:
    """Track each phrase of `targets` for the camera's kind through its usable frames in [start, end].

    Raises ValueError before spending anything when the window has no usable
    frames, mixes frame sizes or formats, or was already tracked with one of
    the phrases (`redo` replaces those runs). A failed SAM request is reported
    and the other phrases go on.
    """
    frames = usable_frames(conn, data_dir, camera.id, start, end)
    if not frames:
        raise ValueError(f"camera {camera.id} has no usable frames between {to_iso(start)} and {to_iso(end)}")
    if len({(f.width, f.height, f.path.suffix.lower()) for f in frames}) > 1:
        raise ValueError(f"camera {camera.id}: the window mixes frame sizes or formats; split it")
    phrases = [(target, phrase) for target in targets for phrase in prompts.phrases(target, camera.kind)]
    window = (to_iso(frames[0].captured_at), to_iso(frames[-1].captured_at))
    existing = _existing_runs(conn, camera.id, [phrase for _, phrase in phrases], *window)
    if existing and not redo:
        raise ValueError(f"camera {camera.id}: window {window[0]} to {window[1]} was already tracked "
                         f"with {', '.join(existing)}; pass redo to replace it")

    report = TrackingReport(camera.id, len(frames))
    if not phrases:
        return report
    with tempfile.TemporaryDirectory() as tmp:
        height = min(max_height, frames[0].height) // 2 * 2
        video = assemble([f.path for f in frames], Path(tmp) / "window.mp4", fps=VIDEO_FPS, height=height)
        info = probe(video)
        if info.frames != len(frames):
            raise RuntimeError(f"the window video has {info.frames} frames instead of {len(frames)}")
        report.video_size = (info.width, info.height)
        file_id = client.upload_video(video)
    try:
        for target, phrase in phrases:
            try:
                objects = client.segment_video(file_id, phrase, purpose=f"track:{target}",
                                               expected_frames=len(frames))
            except (openai.APIError, SamStreamError, SamParseError) as exc:
                log.warning("camera %s, %s: %s", camera.id, phrase, exc)
                report.errors.append(f"{target} / {phrase}: {type(exc).__name__}: {exc}"[:300])
                continue
            with conn:
                _delete_runs(conn, existing.get(phrase, []))
                report.runs.append(_store_run(conn, camera.id, target, phrase, frames, info, objects, now()))
    finally:
        try:
            client.delete_file(file_id)
        except openai.APIError as exc:
            log.warning("could not delete the uploaded window %s (it expires in an hour): %s", file_id, exc)
    return report


def _existing_runs(conn: sqlite3.Connection, camera_id: str, phrases: list[str],
                   window_start: str, window_end: str) -> dict[str, list[int]]:
    found: dict[str, list[int]] = defaultdict(list)
    for row in conn.execute(
            "SELECT id, phrase FROM tracking_runs WHERE camera_id = ? AND window_start = ? AND window_end = ?",
            (camera_id, window_start, window_end)):
        if row["phrase"] in phrases:
            found[row["phrase"]].append(row["id"])
    return found


def _delete_runs(conn: sqlite3.Connection, run_ids: list[int]) -> None:
    for run_id in run_ids:
        conn.execute("DELETE FROM detections WHERE track_id IN (SELECT id FROM tracks WHERE run_id = ?)", (run_id,))
        conn.execute("DELETE FROM tracks WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM tracking_runs WHERE id = ?", (run_id,))


def _store_run(conn: sqlite3.Connection, camera_id: str, target: str, phrase: str, frames: list[WindowFrame],
               info: VideoInfo, objects: list[SamObject], created_at: datetime) -> RunSummary:
    run_id = conn.execute(
        """INSERT INTO tracking_runs (camera_id, target, phrase, window_start, window_end, frame_ids,
                                      video_width, video_height, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (camera_id, target, phrase, to_iso(frames[0].captured_at), to_iso(frames[-1].captured_at),
         json.dumps([f.id for f in frames]), info.width, info.height, to_iso(created_at)),
    ).lastrowid
    tracks: dict[str, list[SamObject]] = defaultdict(list)
    for obj in sorted(objects, key=lambda o: o.frame_index):
        if not 0 <= obj.frame_index < len(frames):
            raise ValueError(f"SAM returned frame {obj.frame_index} for a {len(frames)}-frame video")
        tracks[obj.object_id].append(obj)
    seen = []
    for object_id, track in tracks.items():
        first, last = frames[track[0].frame_index], frames[track[-1].frame_index]
        track_id = conn.execute(
            "INSERT INTO tracks (run_id, object_id, first_seen, last_seen, detections) VALUES (?, ?, ?, ?, ?)",
            (run_id, object_id, to_iso(first.captured_at), to_iso(last.captured_at), len(track)),
        ).lastrowid
        for obj in track:
            frame = frames[obj.frame_index]
            box, mask = _to_frame_pixels(obj, frame, info)
            conn.execute(
                """INSERT INTO detections (track_id, frame_id, box_left, box_top, box_right, box_bottom,
                                           score, area_px, mask_rle)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (track_id, frame.id, *box, obj.score, int(mask.sum()), json.dumps(masks.encode(mask))),
            )
        seen += [first.captured_at, last.captured_at]
    return RunSummary(run_id, target, phrase, len(tracks), sum(len(track) for track in tracks.values()),
                      min(seen, default=None), max(seen, default=None))


def _to_frame_pixels(obj: SamObject, frame: WindowFrame, info: VideoInfo) -> tuple[tuple[int, int, int, int], np.ndarray]:
    """The object's box and box-sized mask, scaled from the video's pixels to the frame's."""
    sx, sy = frame.width / info.width, frame.height / info.height
    left, top, right, bottom = obj.box
    box = (round(left * sx), round(top * sy), min(frame.width, round(right * sx)), min(frame.height, round(bottom * sy)))
    return box, fit_mask(obj.mask, box[3] - box[1], box[2] - box[0])
```

- [ ] **Step 3: Run the tests, then the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking.py -v` → 11 passed
Run: `.venv/Scripts/python.exe -m pytest` → 183 passed

- [ ] **Step 4: Commit**

```bash
git add vigia/tracking.py tests/test_tracking.py
git commit -m "Track a window of usable frames with SAM 3.1 video, one run per phrase"
```

---

### Task 9: `vigia-track` CLI and track overlays

**Files:**
- Modify: `vigia/tracking.py`, `vigia/settings.py`, `.env.example`, `pyproject.toml`, `tests/test_tracking.py`
- Create: `scripts/render_tracks.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_tracking.py`; add `from pathlib import Path`, `from vigia import db`, `from vigia.settings import Settings` and `main` to the `vigia.tracking` import)

```python
SOURCES_YAML = """
volcanoes:
  kilauea:
    name: Kīlauea
    country: United States
    official_agency: USGS Hawaiian Volcano Observatory
    official_url: https://www.usgs.gov/volcanoes/kilauea
    lat: 19.405
    lon: -155.29
cameras:
  - id: kilauea-k2
    name: K2cam
    volcano: kilauea
    url: https://example.org/K2cam/images/M.jpg
    license: Public Domain
    attribution: U.S. Geological Survey
"""
WINDOW = ["--start", "2026-10-17T18:00Z", "--end", "2026-10-17T19:00Z"]


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(SOURCES_YAML, encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigia.sqlite"))
    return tmp_path / "data"


def test_cli_refuses_a_window_under_the_billed_minimum(cli_env, capsys):
    conn = db.connect(cli_env / "vigia.sqlite")
    store = FrameStore(conn, cli_env)
    add_frame(store, conn, 0)
    add_frame(store, conn, 2, usable=None)
    conn.close()

    with pytest.raises(SystemExit):
        main(["--camera", "kilauea-k2", *WINDOW])

    err = capsys.readouterr().err
    assert "1 usable frames" in err and "50" in err and "vigia-quality" in err


def test_cli_refuses_an_unknown_camera(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--camera", "etna-1", *WINDOW])

    assert "etna-1" in capsys.readouterr().err


def test_cli_refuses_an_empty_window(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--camera", "kilauea-k2", "--start", "2026-10-17T19:00Z", "--end", "2026-10-17T18:00Z"])

    assert "before" in capsys.readouterr().err


def test_settings_name_the_prompts_file(monkeypatch):
    monkeypatch.setenv("PROMPTS_PATH", "elsewhere/prompts.yaml")

    assert Settings.from_env().prompts_path == Path("elsewhere/prompts.yaml")
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking.py -v`
Expected: FAIL with `ImportError: cannot import name 'main'`

- [ ] **Step 2: Add `prompts_path` to the settings** — in `vigia/settings.py` add the field after `sources_path`:

```python
    prompts_path: Path
```

and the argument after `sources_path=...` in `from_env`:

```python
            prompts_path=Path(os.getenv("PROMPTS_PATH", "config/prompts.yaml")),
```

In `.env.example`, add under `SOURCES_PATH=config/sources.yaml`:

```
PROMPTS_PATH=config/prompts.yaml
```

- [ ] **Step 3: Add the CLI** — in `vigia/tracking.py` add `import argparse` and `from contextlib import closing` to the standard-library imports; replace `from vigia import masks` with `from vigia import db, masks`; replace `from vigia.config import Camera` with `from vigia.config import Camera, load_sources`; add `from vigia.meta.ledger import CostLedger` after the `vigia.meta.client` import; replace `from vigia.prompts import Prompts, Target` with `from vigia.prompts import Prompts, Target, load_prompts`; add `from vigia.settings import Settings` after it. Add this line at the end of the module docstring:

```text
    vigia-track --camera kilauea-k2 --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z
```

and append:

```python
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Track plumes and fountains through a camera's usable frames "
                                                 "with SAM 3.1 video.")
    parser.add_argument("--camera", required=True, help="camera id from the sources file")
    parser.add_argument("--start", type=parse_utc, required=True, help="first capture time, e.g. 2026-10-17T13:00Z")
    parser.add_argument("--end", type=parse_utc, required=True, help="last capture time, e.g. 2026-10-17T19:30Z")
    parser.add_argument("--target", action="append", choices=TARGETS,
                        help="what to track; repeat it for several (default: all)")
    parser.add_argument("--min-frames", type=int, default=MIN_BILLED_FRAMES,
                        help=f"refuse windows with fewer usable frames (default {MIN_BILLED_FRAMES}: "
                             "SAM bills that many per request anyway)")
    parser.add_argument("--redo", action="store_true", help="replace runs of the same window and phrases")
    args = parser.parse_args(argv)
    if args.start >= args.end:
        parser.error("--start must be before --end")

    settings = Settings.from_env()
    cameras = {camera.id: camera for camera in load_sources(settings.sources_path).cameras}
    if args.camera not in cameras:
        parser.error(f"unknown camera {args.camera!r} in {settings.sources_path}")
    with closing(db.connect(settings.db_path)) as conn:
        usable = len(usable_frames(conn, settings.data_dir, args.camera, args.start, args.end))
        if usable < args.min_frames:
            pending = unassessed_frames(conn, args.camera, args.start, args.end)
            parser.error(f"{usable} usable frames in the window, fewer than {args.min_frames}: SAM bills "
                         f"{MIN_BILLED_FRAMES} frames per request, so widen the window"
                         + (f"; {pending} frames have no quality verdict yet, run vigia-quality first"
                            if pending else ""))
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        client = MetaClient.from_env(CostLedger(conn, settings.daily_budget_usd))
        started = utcnow()
        try:
            report = track_window(client, conn, settings.data_dir, cameras[args.camera],
                                  load_prompts(settings.prompts_path), args.start, args.end,
                                  targets=args.target or TARGETS, redo=args.redo)
        except ValueError as exc:
            parser.error(str(exc))
        cost = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM api_calls WHERE purpose LIKE 'track:%' AND called_at >= ?",
            (to_iso(started),),
        ).fetchone()[0]
    print(report.summary())
    print(f"cost: ${cost:.4f}")


if __name__ == "__main__":
    main()
```

In `pyproject.toml` `[project.scripts]` add:

```toml
vigia-track = "vigia.tracking:main"
```

- [ ] **Step 4: Run the tests, then the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking.py -v` → 15 passed
Run: `.venv/Scripts/python.exe -m pytest` → 187 passed
Run: `.venv/Scripts/python.exe -m pip install -e ".[dev]" -q` then `.venv/Scripts/vigia-track.exe --help`
Expected: usage listing `--camera`, `--start`, `--end`, `--target`, `--min-frames`, `--redo`

- [ ] **Step 5: Write `scripts/render_tracks.py`**

```python
"""Draw a camera's SAM tracks over its frames: an MP4 and a contact sheet.

Every tracking run of the camera whose window lies between --start and --end
is drawn on the frames it covered: plume masks cyan, fountains orange,
incandescence magenta, each labelled with its target, track and score in the
legend strip. Frames are drawn at most 1280 px wide. Output goes to
data/tracks/<camera>_<start>/: overlay.mp4 (10 fps) and contact_sheet.jpg
(12 frames, captioned with the HST time).

    python scripts/render_tracks.py --camera kilauea-k2 --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import defaultdict
from datetime import timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from vigia import db
from vigia.overlay import Layer, draw_layers
from vigia.settings import Settings
from vigia.timeutil import parse_utc, to_iso
from vigia.tracking import VIDEO_FPS, detection_mask
from vigia.video import assemble

HST = timezone(timedelta(hours=-10))
COLORS = {"plume": (0, 200, 255), "fountain": (255, 120, 0), "incandescence": (255, 0, 160)}
MAX_WIDTH = 1280


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--start", type=parse_utc, required=True)
    parser.add_argument("--end", type=parse_utc, required=True)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    conn = db.connect(settings.db_path)
    runs = conn.execute(
        "SELECT * FROM tracking_runs WHERE camera_id = ? AND window_start >= ? AND window_end <= ?",
        (args.camera, to_iso(args.start), to_iso(args.end)),
    ).fetchall()
    if not runs:
        raise SystemExit(f"no tracking runs for {args.camera} between {to_iso(args.start)} and {to_iso(args.end)}")
    run_ids = [run["id"] for run in runs]
    frame_ids = sorted({frame_id for run in runs for frame_id in json.loads(run["frame_ids"])})
    frames = conn.execute(f"SELECT * FROM frames WHERE id IN ({','.join('?' * len(frame_ids))}) "
                          "ORDER BY captured_at", frame_ids).fetchall()
    by_frame = defaultdict(list)
    for detection in conn.execute(
            f"""SELECT d.*, t.object_id, r.target FROM detections d
                JOIN tracks t ON t.id = d.track_id JOIN tracking_runs r ON r.id = t.run_id
                WHERE r.id IN ({','.join('?' * len(run_ids))})""", run_ids):
        by_frame[detection["frame_id"]].append(detection)
    rows = max((len(detections) for detections in by_frame.values()), default=0)

    out = settings.data_dir / "tracks" / f"{args.camera}_{args.start:%Y%m%dT%H%MZ}"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        rendered = []
        for i, frame in enumerate(frames):
            with Image.open(settings.data_dir / frame["path"]) as raw:
                image = raw.convert("RGB")
            scale = min(1.0, MAX_WIDTH / image.width)
            size = (round(image.width * scale), round(image.height * scale))
            layers = [Layer(mask=resized(detection_mask(d, frame["width"], frame["height"]), size),
                            color=COLORS[d["target"]], label=f"{d['target']} #{d['object_id']} {d['score'] or 0:.2f}")
                      for d in by_frame.get(frame["id"], [])]
            path = Path(tmp) / f"{i:05d}.jpg"
            draw_layers(image.resize(size), layers, min_legend_rows=rows).save(path, quality=90)
            rendered.append((frame, path))
        assemble([path for _, path in rendered], out / "overlay.mp4", fps=VIDEO_FPS)
        contact_sheet(rendered).save(out / "contact_sheet.jpg", quality=88)
    detections = sum(len(v) for v in by_frame.values())
    print(f"{len(frames)} frames, {detections} detections from {len(runs)} runs; results in {out}")


def resized(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return np.asarray(Image.fromarray(mask).resize(size, Image.NEAREST), dtype=bool)


def contact_sheet(rendered: list, count: int = 12, columns: int = 3, width: int = 640) -> Image.Image:
    picks = rendered if len(rendered) <= count else [
        rendered[round(i * (len(rendered) - 1) / (count - 1))] for i in range(count)]
    font = ImageFont.load_default(size=20)
    cells = []
    for frame, path in picks:
        with Image.open(path) as image:
            thumb = image.convert("RGB")
        thumb.thumbnail((width, width))
        cell = Image.new("RGB", (width, thumb.height + 28), (25, 25, 25))
        cell.paste(thumb, (0, 28))
        hst = parse_utc(frame["captured_at"]).astimezone(HST)
        ImageDraw.Draw(cell).text((6, 4), f"{hst:%Y-%m-%d %H:%M} HST", fill=(240, 240, 240), font=font)
        cells.append(cell)
    cell_h = max(cell.height for cell in cells)
    sheet = Image.new("RGB", (width * columns, cell_h * -(-len(cells) // columns)))
    for i, cell in enumerate(cells):
        sheet.paste(cell, ((i % columns) * width, (i // columns) * cell_h))
    return sheet


if __name__ == "__main__":
    main()
```

Run: `.venv/Scripts/python.exe scripts/render_tracks.py --help`
Expected: the usage text. Its real run comes in Task 10, after tracks exist.

- [ ] **Step 6: Commit**

```bash
git add vigia/tracking.py vigia/settings.py .env.example pyproject.toml tests/test_tracking.py scripts/render_tracks.py
git commit -m "Add vigia-track CLI and a script that renders tracks over the frames"
```

---

### Task 10 (orchestrator): Episode 55 run and acceptance

Live Meta API spend, about $0.65 (budget ≤ $1.00):
- Muse Spark on about 39 hazy calibration frames: $0.31;
- a verification sample of about 6 frames: $0.05;
- SAM video on episode 55: $0.28.

**Files:**
- Create: `docs/research/tracking_ep55.md`

- [ ] **Step 1: Pre-flight.** `git status` is clean, `.venv/Scripts/python.exe -m pytest` passes, and `vigia-quality --help` and `vigia-track --help` work. Today's spend (`SELECT SUM(cost_usd) FROM api_calls WHERE called_at >= '<today>'`) leaves room under `DAILY_BUDGET_USD`.

- [ ] **Step 2: Assess episode 55** (local checks; Muse Spark only for hazy frames)

Run: `.venv/Scripts/vigia-quality.exe --camera kilauea-kp --camera kilauea-k2 --camera kilauea-v1 --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z`
Expected: KP `78 assessed, 78 usable`, K2 `195 … 195 usable`, V1 `195 … 195 usable`, `0 by Muse Spark` each (per the calibration).

- [ ] **Step 3: Assess the calibration windows**

Run: `.venv/Scripts/vigia-quality.exe --camera kilauea-kp --camera kilauea-k2 --camera kilauea-v1 --start 2026-10-26T22:00Z --end 2026-10-27T19:00Z`
Expected: the fog and the dark night are rejected locally. About 39 frames are decided by Muse Spark. The live frames after 08:00Z (if `vigia-ingest` stored any) are assessed too.

- [ ] **Step 4: Check that Muse Spark never saw a rejected frame**

```bash
.venv/Scripts/python.exe -c "
import sqlite3
c = sqlite3.connect('data/vigia.sqlite')
print(c.execute(\"SELECT COUNT(*) FROM frame_quality WHERE local_decision = 'reject' AND spark_answer IS NOT NULL\").fetchone())
for r in c.execute(\"SELECT f.camera_id, q.local_decision, q.reasons, q.decided_by, COUNT(*) FROM frame_quality q JOIN frames f ON f.id = q.frame_id GROUP BY 1, 2, 3, 4\"): print(r)
"
```

Expected: `(0,)`. Every `reject` row has `decided_by = 'local'`.

- [ ] **Step 5: Verification sample with `--spark all`.** Read printed times and PTZ on frames with known answers:

Run, one by one:
- `.venv/Scripts/vigia-quality.exe --camera kilauea-v1 --start 2026-10-17T16:58Z --end 2026-10-17T17:02Z --spark all --redo`
- `.venv/Scripts/vigia-quality.exe --camera kilauea-k2 --start 2026-10-17T16:59Z --end 2026-10-17T17:01Z --spark all --redo`
- `.venv/Scripts/vigia-quality.exe --camera kilauea-kp --start 2026-10-17T16:59Z --end 2026-10-17T17:01Z --spark all --redo`

Expected:
- `printed_time` within 10 s of `captured_at` on each frame (AshCam overlays read 0–4 s earlier);
- V1 `printed_ptz` = `{"pan": 29.0, "tilt": 0.0, "zoom_raw": 29.0, "zoom": 1.0}`;
- K2 and KP `printed_ptz` NULL (no readout).

If Muse Spark misreads 4K overlays scaled to 2048 px, record it as a finding; do not change code in this task.

- [ ] **Step 6: Track episode 55** (one window per camera; 3 phrases each)

Run, one by one:
- `.venv/Scripts/vigia-track.exe --camera kilauea-k2 --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z`
- `.venv/Scripts/vigia-track.exe --camera kilauea-v1 --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z`
- `.venv/Scripts/vigia-track.exe --camera kilauea-kp --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z`

Expected: K2 and V1 report `195 usable frames, video 1920x1080` and KP `78`; each has plume, fountain and incandescence runs; costs about $0.117, $0.117 and $0.047.

- [ ] **Step 7: Render and look**

Run: `.venv/Scripts/python.exe scripts/render_tracks.py --camera <camera> --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z` for each of the three cameras, then open each `contact_sheet.jpg`. Check that:
- the plume (`steam`) mask covers the gas column;
- `lava fountain` covers the jet on K2 and V1;
- `glow` covers the night incandescence.

Note track breaks, for example at V1's zoom changes (03:49 and 04:43 HST).

- [ ] **Step 8: Acceptance checks**

```bash
.venv/Scripts/python.exe -c "
import sqlite3
c = sqlite3.connect('data/vigia.sqlite')
q = '''SELECT r.camera_id, r.target, COUNT(DISTINCT t.id), SUM(t.detections), MIN(t.first_seen), MAX(t.last_seen)
       FROM tracking_runs r LEFT JOIN tracks t ON t.run_id = r.id
       WHERE r.window_start >= '2026-10-17T13:00:00Z' AND r.window_end <= '2026-10-17T19:30:00Z'
       GROUP BY r.camera_id, r.target'''
for row in c.execute(q): print(row)
"
```

Expected:
1. Tracks exist for V1, K2 and KP.
2. The last `fountain` detection on K2 and V1 falls between `2026-10-17T18:53:00Z` and `19:13:00Z` (09:03 HST ± 10 min).
3. Step 4 gave `(0,)`.

If check 2 fails, investigate with superpowers:systematic-debugging before changing anything:
- look at the frames around 19:03Z;
- check the scores of the last detections (a residual low-score glow after the end?);
- check whether the track was lost early.

Then record the cause and the fix (or the documented limitation) in the results doc.

- [ ] **Step 9: Write `docs/research/tracking_ep55.md`** with these sections:
  - *Method*: commands, windows, video size, cost per camera from `api_calls`.
  - *Quality gate results*: counts per camera and window from `frame_quality`, Muse Spark calls and their cost, and the Step 5 sample table (frame, view, printed time vs. capture time, PTZ).
  - *Tracks*: per camera and target, the tracks, detections and first/last seen in HST.
  - *Acceptance*: the three checks with numbers; the fountain end against 09:03 HST.
  - *Overlays*: paths of the contact sheets and MP4s under `data/tracks/`.
  - *Caveats*: track breaks at zoom changes; KP is not a fountain camera; `steam` masks include the drifting cloud; mask edges good to about 2 px; what Phase 3 should use.

- [ ] **Step 10: Commit**

```bash
git add docs/research/tracking_ep55.md
git commit -m "Record episode 55 quality verdicts and SAM tracks"
```

---

### Task 11 (orchestrator): Docs, roadmap, push, memory

**Files:**
- Modify: `README.md`, `docs/PLAN.md`

- [ ] **Step 1: README.**
  - In *Status*, replace `- [ ] Quality gate, SAM 3.1 segmentation and tracking, metrics, wind comparison` with:

```markdown
- [x] Quality gate: free local checks (stale, frozen, night without incandescence, fog), Muse Spark for hazy frames, printed time and PTZ readout ([calibration](docs/research/quality_calibration.md))
- [x] SAM 3.1 video tracking over timelapses of usable frames, with per-frame masks ([episode 55 results](docs/research/tracking_ep55.md))
- [ ] Metrics (height ± σ, drift) and wind comparison
```

  - In *Running it*, after the `vigia-backfill` lines, add:

```bash
vigia-quality --camera kilauea-k2 --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z
                                   # judge frames: local checks, Muse Spark for hazy ones
vigia-track --camera kilauea-k2 --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z
                                   # SAM 3.1 video tracks over the usable frames
```

- [ ] **Step 2: docs/PLAN.md.**
  - Tick the four Phase 2 boxes.
  - Module map:
    - mark `quality.py` and `tracking.py` as `(exists, phase 2)`;
    - add `sun.py` (sun elevation for the night check), `gate.py` (quality gate + `frame_quality`, `vigia-quality`) and `masks.py` (COCO RLE), all `(exists, phase 2)`.
  - *How to resume*: update the passing-test count.
  - *Facts the plan depends on*, add:
    - a **Quality gate** bullet: thresholds, what passes locally, Muse Spark only for hazy frames, cost;
    - a **Tracking** bullet: episode 55 tracks, the fountain end time against 09:03 HST, video size, cost.
  - *Phase 5*: add two lines to the replay bullet:
    - "run `QualityGate.assess_range(spark='uncertain')` on new frames";
    - "live tracking: one SAM window per camera per hour (Phase 2 cost rule)".
  - *Budget*: update *Spent so far*.

- [ ] **Step 3: Final verification**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: all pass, 0 failures (187 if nothing changed in Task 10).

- [ ] **Step 4: Commit and push**

```bash
git add README.md docs/PLAN.md
git commit -m "Mark Phase 2 done: quality gate and timelapse tracking"
git push origin main
```

- [ ] **Step 5: Update the project memory** (`vigia-andino-status`). Record:
  - Phase 2 done and pushed;
  - the new modules and CLIs, thresholds and their calibration windows;
  - the episode 55 tracking results and the fountain end time;
  - the Muse Spark gate policy;
  - test count, spend, the calibration frames backfilled (Oct 26–27);
  - next: Phase 3 (geometry, metrics, first validation).
