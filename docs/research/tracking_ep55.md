# Episode 55: quality verdicts and SAM 3.1 tracks

Run on 2026-10-28 UTC with `vigia-quality` and `vigia-track` (Phase 2) on the AshCam frames of Kīlauea episode 55. Window: 2026-10-17 13:00–19:30Z, which is 03:00–09:30 HST. Official values are in [episode55.md](episode55.md): onset at 03:19 HST, end at 09:03 HST.

## Method

```bash
vigia-quality --camera kilauea-kp --camera kilauea-k2 --camera kilauea-v1 --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z
vigia-track --camera kilauea-k2 --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z   # likewise for kilauea-v1 and kilauea-kp
python scripts/render_tracks.py --camera kilauea-k2 --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z
```

- **Phrases:** from `config/prompts.yaml`, visible cameras: plume `steam`, fountain `lava fountain`, incandescence `glow`.
- **Video:** one window per camera, encoded at 10 fps and at most 1080 px high. All three came out 1920×1080; K2 and KP frames (3840×2160) are scaled by exactly 2.
- **Requests:** one upload per camera, then one SAM request per phrase.

**Cost.** Billed frames come from the cost ledger (`api_calls`).

| camera | frames | SAM requests | cost (USD) |
|---|---|---|---|
| K2 | 195 | 3 | 0.1170 |
| V1 | 195 | 3 | 0.1170 |
| KP | 78 | 3 | 0.0468 |
| **total** | | 9 | **0.2808** |

The `cost:` line that `vigia-track` prints sums every `track:` call made since the run started. V1 and KP ran in parallel, so each printed line also included the other's calls. The ledger itself is exact.

## Quality gate

**Episode 55.** All 468 frames pass the local checks: KP 78, K2 195, V1 195 usable. Muse Spark was not called.

**Calibration windows.** These are the foggy afternoon, the quiet night and the clear morning of 2026-10-26/27, described in [quality_calibration.md](quality_calibration.md).

| camera | assessed | usable | rejected locally | sent to Muse Spark | Muse Spark verdict |
|---|---|---|---|---|---|
| KP | 96 | 40 | 49 (25 fog, 24 night) | 7 | 7 obscured_by_cloud_or_fog, unusable |
| K2 | 240 | 160 | 72 (14 fog, 58 night) | 8 | 8 obscured_by_cloud_or_fog, unusable |
| V1 | 180 | 80 | 99 (55 fog, 44 night) | 24 | 23 usable (17 clear, 6 partly_obscured), 1 partly_obscured unusable |

- **Muse Spark calls:** 39, costing **$0.3024** with no failures.
- **Rejected frames:** none of the locally rejected frames was sent to Muse Spark. That is the third acceptance check.
- **Agreement with the visual check:** K2 and KP uncertain frames were fog with only the foreground visible, and Muse Spark rejected all of them. The V1 uncertain frames were hazy views in which the gas plume is visible, and Muse Spark kept 23 of 24.

**Printed timestamps and PTZ readouts.** Muse Spark read them on all 43 frames it assessed: the 39 above plus a 4-frame `--spark all` sample on episode 55.

| camera | frames | printed time − capture time | PTZ readout |
|---|---|---|---|
| K2 | 9 | −1 to 0 s | none |
| KP | 8 | −6 to −2 s | none |
| V1 | 26 | −1 to 0 s | `P: 9594, T: +0.00, Z: 9594 9.6` on Oct 26 (24 frames); `P: 29, T: +0.00, Z: 29 1.0` on episode 55 (2 frames) |

AshCam overlays read a few seconds earlier than the archive's capture time ([ashcam_latency.md](ashcam_latency.md)). Every readout was parsed into `{pan, tilt, zoom_raw, zoom}`.

## Tracks

Times are HST.

| camera | target (phrase) | tracks | detections | first seen | last seen |
|---|---|---|---|---|---|
| K2 | plume (`steam`) | 1 | 168 | 03:54 | 09:28 |
| K2 | fountain (`lava fountain`) | 1 | 138 | 04:28 | **09:02** |
| K2 | incandescence (`glow`) | 3 | 141 | 03:58 | 09:02 |
| V1 | plume (`steam`) | 2 | 158 | 04:13 | 09:29 |
| V1 | fountain (`lava fountain`) | 1 | 169 | 03:25 | **09:01** |
| V1 | incandescence (`glow`) | 0 | 0 | | |
| KP | plume (`steam`) | 1 | 75 | 03:15 | 09:25 |
| KP | fountain (`lava fountain`) | 0 | 0 | | |
| KP | incandescence (`glow`) | 3 | 48 | 03:55 | 09:10 |

- **Fountain tracks.** Each fountain track is one SAM object detected on every frame of its span:
  - K2: 04:28–09:02 is 138 frames at 2 min.
  - V1: 03:25–09:01 is 169 frames.
  - The V1 track survives the camera's PTZ changes. The frames print `P: 9321 … Z: 9.4` until 03:47, `P: 493 … Z: 1.4` until 04:41, and `P: 29 … Z: 1.0` after that.
- **Plume tracks.** K2 and KP each follow the plume as one track all morning. V1's plume splits in two at 07:41/07:43.
- **Incandescence tracks.**
  - K2: track #2, 04:42–09:02, follows the fountain's glow and ends with it.
  - KP: track #1, 05:00–08:00, is the glow at the vent. Track #2, 08:25–09:10, is a **false detection on sun glare and a lens flare** in daylight.
- **Episode onset.** V1 first sees the fountain at 03:25, six minutes after the official onset at 03:19. On K2 the young fountain saturates the sensor, and SAM finds nothing before 03:54.

## Acceptance

1. **Tracks exist for episode 55 V1, K2 and KP:** yes, see the table above.
2. **The fountain track ends within ±10 min of 09:03 HST:**
   - K2's last fountain detection is at **09:02:01 HST**, with no fountain at 09:04, 09:06 and 09:08.
   - V1's last fountain detection is at **09:01:05 HST**, with none at 09:03, 09:05 and 09:07.
   - Both are within 2 minutes of HVO's 09:03.
3. **Fog and night frames are rejected without Muse Spark calls:** yes. 220 frames were rejected locally (fog or night), and none of them reached Muse Spark.

## Overlays

The overlays are in `data/tracks/<camera>_20261017T1300Z/` (git-ignored): `overlay.mp4` (195 or 78 frames at 10 fps) and `contact_sheet.jpg` (12 frames). Masks are drawn in colour: plume cyan, fountain orange, incandescence magenta.

## Caveats for Phase 3 and later

- **Plume masks.** `steam` masks include the cloud drifting downwind: on K2 in daylight, and on KP from 05:55. Measure the top of the column above the vent, not the far end of the cloud. On KP the whole column is inside the mask at the peak (04:45–05:20), top included.
- **False incandescence.** Incandescence detections can be false, like the KP lens flare. Keep only those near the vent, and do not trust `glow` in daylight.
- **`glow` on V1.** It found nothing. The phrase was tuned only on KP and K2 frames, and on V1 the fountain track already covers the lava jet.
- **Calibration per preset.** V1's PTZ presets change during the episode, so Phase 3 must calibrate per preset. The printed readouts identify them (9.4×, 1.4×, 1.0×).
- **Mask accuracy.** SAM sends large masks at reduced resolution (long side 1024 px), and K2/KP masks are then scaled ×2 to 4K, so mask edges are good to about 2 px on the video and 4 px on the 4K frames.
- **Parsing time.**
  - `meta_sam_parser` decodes mask rasters in pure Python. K2's 168 plume masks took about 11 minutes, while the SAM requests took 10–18 s each.
  - An hourly live window (30 frames) costs about 2 minutes per camera. The Phase 5 pipeline should run tracking off the request path.
- **Render colours.** The orange fountain colour is hard to see over V1's orange lava at night. The dashboard (Phase 6) should use a contrasting colour.
