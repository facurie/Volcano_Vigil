# Local quality checks: calibration

Run on 2026-10-28 UTC with `scripts/calibrate_quality.py` over 984 stored frames. The thresholds are in `Thresholds` in [`vigil/quality.py`](../../vigil/quality.py), and the quality gate ([`vigil/gate.py`](../../vigil/gate.py)) applies them. Results: `data/calibration/20261028T013408Z/` (`stats.csv`, `summary.md`, contact sheets per camera, window and decision).

## Method

**Frames.** All are USGS public domain. KP and K2 are 3840×2160 and V1 is 1920×1080. The last three windows were backfilled from AshCam for this calibration.

| window (UTC) | HST | KP | K2 | V1 | what it shows |
|---|---|---|---|---|---|
| 2026-10-17 13:00–19:30 | 03:00–09:30 | 78 | 195 | 195 | Episode 55: night fountain, dawn, daylight fountain, end at 09:03 |
| 2026-10-26 22:00 – 10-27 02:00 | 12:00–16:00 | 48 | 120 | 120 | Foggy afternoon. Includes the smoke test's V1 fog frame (14:09) |
| 2026-10-27 06:00–08:00 | 20:00–22:00 | 24 | 60 | 60 | Quiet night (no eruption, full moon), with a small glow at the north vent |
| 2026-10-27 16:00–19:00 | 06:50–08:55 | 24 | 60 | — | Clear, quiet morning with a large gas plume (K2) |

**Measurements.** They are taken on the scene between the burned-in text bands: the top 5 % (the timestamp) and the bottom 8 % (the logo and the PTZ readout) are cut away.
- **Edge density:** the share of pixels where luminance changes by more than 8 levels per pixel, on a copy at most 512 px wide with a radius-1 Gaussian blur. Fog flattens it.
- **Glow fraction:** the share of a block-averaged copy, at most 256 px wide, covered by 2×2 squares of blocks that are either warm and bright (R ≥ 150, R − B ≥ 60, R ≥ G) or nearly white (every channel ≥ 200).
  - Warm and bright is orange lava. Nearly white is lava that saturates the sensor (K2), or KPcam in monochrome night mode.
  - Lone hot blocks, such as stars and K2's path lamps, do not count.
- **Change:** the mean absolute luminance difference of 128-px block-averaged fingerprints. It is measured against the camera's previous stored frame.
- **Sun elevation:** computed at the volcano's position (`vigil/sun.py`).

**Command:**

```bash
python scripts/calibrate_quality.py --camera kilauea-kp --camera kilauea-k2 --camera kilauea-v1 \
    --window 2026-10-17T13:00Z/2026-10-17T19:30Z --window 2026-10-26T22:00Z/2026-10-27T02:00Z \
    --window 2026-10-27T06:00Z/2026-10-27T08:00Z --window 2026-10-27T16:00Z/2026-10-27T19:00Z
```

## Measurements

Ranges per camera. The labels come from looking at the contact sheets.

| condition | edge density | contrast | glow |
|---|---|---|---|
| dense fog, day | V1 0.000–0.004, K2 0.000–0.003, KP 0.000–0.004 | V1 11–29, K2 22–29, KP 20–35 | 0 |
| haze, target faint (uncertain band) | V1 0.005–0.015, K2 0.005–0.015, KP 0.006–0.014 | V1 20–39, K2 26–33, KP 35–40 | 0 |
| K2 fog that leaves the foreground sharp | 0.018–0.040 | 27–36 | 0 |
| KP overcast, summit hidden | 0.015–0.027 | 37–42 | 0 |
| clear quiet morning | K2 0.022–0.038, KP 0.035–0.053 | | |
| episode 55 (night to day) | KP 0.025–0.133, K2 0.020–0.109, V1 0.078–0.264 | | |
| episode 55 nights | | | minimum KP 0.094 %, K2 0.273 %, V1 2.156 % |
| quiet night | KP 0.000–0.004, K2 0.004–0.009, V1 0.000–0.006 | | KP 0 %, K2 up to 0.066 % (vent), V1 up to 2.954 % (vent at 9.6× zoom) |

**Change between frames.**
- Re-encoding one image as JPEG (quality 70–95) changes its fingerprint by 0.005–0.161.
- Real consecutive frames differ by at least 0.23 (K2 on the dark quiet night), 1.30 (V1 in fog) or 1.40 (episode 55).
- Scene cuts show up as large values: a V1 zoom change gives 65 and the KP night-mode switch 41.

**Contrast is not used in the rules.** It overlaps across conditions:
- clear V1 frames of the afternoon go as low as 21;
- K2 fog with a sharp foreground reaches 36;
- KP fog reaches 35.

Edge density separates dense fog from the rest without overlap. Contrast is stored with every verdict.

## Thresholds

| threshold | value | fixed by |
|---|---|---|
| `fog_edges` | 0.005 | Dense fog is 0.000–0.004 on all three cameras. |
| `clear_edges` | 0.015 | Frames with edge density between 0.005 and 0.015 are hazy views and go to Muse Spark. A wider band (0.05) would also take every quiet clear K2 frame (0.022–0.038), at about $0.24 per hour for K2 alone. |
| `night_sun_deg` | −6° | Civil twilight. At Kīlauea on 2026-10-17 it began at 05:54 HST. |
| `night_glow` | 0.0005 (0.05 %) | Episode 55 nights are ≥ 0.094 % (KP at 04:15 HST is the minimum, a 1.9× margin). A quiet KP night is 0 %. |
| `frozen_change` | 0.15 | It sits above the JPEG re-encoding range (≤ 0.161 at quality 70; ≤ 0.08 at quality 85 and above) and below real consecutive frames (≥ 0.23). |
| `stale_after` | 30 min | The roadmap. It is judged only for live assessment. |

## Decisions

| camera | window (UTC) | frames | pass | uncertain | reject |
|---|---|---|---|---|---|
| KP | episode 55 | 78 | 78 | 0 | 0 |
| KP | foggy afternoon | 48 | 16 | 7 | 25 (low_visibility) |
| KP | quiet night | 24 | 0 | 0 | 24 (night) |
| KP | clear morning | 24 | 24 | 0 | 0 |
| K2 | episode 55 | 195 | 195 | 0 | 0 |
| K2 | foggy afternoon | 120 | 98 | 8 | 14 (low_visibility) |
| K2 | quiet night | 60 | 2 | 0 | 58 (night) |
| K2 | clear morning | 60 | 60 | 0 | 0 |
| V1 | episode 55 | 195 | 195 | 0 | 0 |
| V1 | foggy afternoon | 120 | 52 | 24 | 44 (low_visibility) |
| V1 | quiet night | 60 | 5 | 0 | 55 (44 night, 11 low_visibility) |

Episode 55 passes entirely with no Muse Spark call. The foggy afternoon sends 39 frames to Muse Spark, about $0.31 at the smoke test's $0.008 per assessment.

**Visual check of the contact sheets.**
- **V1 uncertain (24 frames):** hazy views of the crater in which the gas plume is visible. These are the right frames for Muse Spark.
- **K2 and KP uncertain (8 and 7):** fog or overcast with only the foreground visible. Muse Spark should reject them.
- **V1 reject (44):**
  - 12:27–12:57 HST is dense fog.
  - At 13:05–13:13, 13:51–14:03 and 14:21–15:13 HST the gas plume shows faintly through haze, at an edge density of 0.004 or less.
  - These rejections are conservative. V1 was zoomed 9.6× on the vent, and that view is not used for plume height (KP is).
- **K2 pass on the foggy afternoon (98).** These include false passes:
  - 54 of them fall between 13:00 and 15:30 HST, when fog mostly hides the crater while the trees and the Uēkahuna platform stay sharp.
  - From 12:00 to 12:50 and after 15:30 the lower plume is visible.
- **KP pass on the foggy afternoon (16).** All are false passes. At 12:00–13:10 and 14:20–14:30 HST the sky is overcast and the summit 14 km away is hidden, while the vegetation in front of the camera stays sharp.
- **Nights.**
  - The first calibration run counted single hot blocks. K2's row of path lamps then passed 39 of the 60 quiet-night frames, against 21 rejected.
  - With 2×2 patches (commit `b0ee2d3`), 58 are rejected as night. The 2 that pass (20:52 and 20:56 HST) show the north vent glowing (0.056–0.066 %).
  - V1 keeps 5 quiet-night frames (20:05–20:53 HST) in which the vent glows at 9.6× zoom. Eleven more glowing V1 frames have an edge density under 0.005 and are rejected as `low_visibility`.

## Caveats

- **Fog that leaves the foreground sharp passes the local check** (K2, and KP overcast).
  - SAM finds little in those frames.
  - Phase 3 keeps only masks attached to the vent.
  - The agent can ask Muse Spark about any frame (the Phase 4 `assess_frame` tool).
- **By default Muse Spark sees only hazy frames.** `vigil-quality --spark all` sends it every frame the local checks let through, to read printed times and PTZ readouts.
- **A quiet night's vent glow is kept on purpose:** it is incandescence.
- **The 2×2 rule needs a glow at least two blocks wide**, about 30 px on a 4K frame. A tiny distant glow, such as KP at the very start of an episode, could be missed; the episode 55 minimum has a 1.9× margin.
- **Thermal cameras (F1) skip the night and fog checks.** Only stale and frozen apply to them.
- **Limited calibration data:** one day per condition, and only the USGS overlay layout. Edge density depends on scene content, so a new camera (for example one at another volcano) needs its own check with this script.
