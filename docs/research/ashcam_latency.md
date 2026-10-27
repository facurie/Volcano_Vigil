# AshCam vs M.jpg: the live source decision

Phase 1 asked whether the USGS AshCam archive is fresh enough to feed live polling. AshCam would give 2-min frames with exact timestamps instead of the 10-min public `M.jpg`.

## How it was measured

`scripts/measure_ashcam_latency.py --minutes 40` polled both sources every 30 s from **2026-10-27 17:08:35 to 17:48:37 UTC** (07:08–07:48 HST) for KPcam, K2cam, V1cam and F1cam:
- **AshCam:** the capture time (Unix epoch) of the newest frame in the index.
- **M.jpg:** the capture time printed in the camera's `js.js`, for example `var datetime = "2026-10-27 06:40:03 (HST)"`.

Each new capture was logged when first seen. **Latency** is the time it was first seen minus its capture time, with a resolution of about 30 s. Captures already present at the first poll are left out of the latency figures. The raw log is `data/latency/20261027T170835Z.json` (git-ignored).

Two facts checked by hand the same day, at 16:50 UTC:
- AshCam files are **byte-identical** to the `M.jpg` of the same capture: same SHA-256 and same MD5, on K2cam and KPcam. SHA-256 de-duplication therefore works across both sources.
- AshCam's `imageTimestamp` **equals** the `js.js` capture time to the second (16:50:02 on K2cam, 16:50:06 on KPcam). AshCam timestamps are exact; `M.jpg`'s Last-Modified can trail the capture by up to about 10 min on batch-synced cameras.

## Results

| camera | source | new captures | median latency (min) | max latency (min) | median spacing (min) | expected age of the newest frame (min)* |
|---|---|---|---|---|---|---|
| KPcam | AshCam | 8 | 0.2 | 0.2 | 5.0 | 2.7 |
| KPcam | M.jpg | 4 | 3.5 | 6.3 | 7.5 | 7.3 |
| K2cam | AshCam | 20 | 0.4 | 0.6 | 2.0 | 1.4 |
| K2cam | M.jpg | 4 | 1.1 | 1.4 | 10.0 | 6.1 |
| V1cam | AshCam | 20 | 0.3 | 0.6 | 2.0 | 1.3 |
| V1cam | M.jpg | 4 | 1.8 | 1.8 | 10.0 | 6.8 |
| F1cam (thermal) | AshCam | 3 | 6.3 | 11.3 | 20.0 | 16.3 |
| F1cam (thermal) | M.jpg | 4 | 3.1 | 4.1 | 10.2 | 8.2 |

\* Derived: median latency + half the median spacing, which is the average age of the newest frame at a random moment.

An earlier spot check at 16:48 UTC agrees. The newest AshCam frame was 1–3 min old for V1, K2 and KP, and 9 min old for F1. The newest `M.jpg` captures were 8–13 min old. F1's `M.jpg` capture of 16:48:13 had no AshCam frame within ±60 s.

## Decision

**Rule (from the Phase 1 plan):** a camera polls AshCam live when its median AshCam latency is ≤ 5 min and AshCam's spacing is no longer than `M.jpg`'s. Otherwise it keeps `M.jpg`.

| camera | AshCam latency ≤ 5 min | spacing ≤ M.jpg's | live source |
|---|---|---|---|
| KPcam | yes (0.2) | yes (5.0 ≤ 7.5) | **AshCam** |
| K2cam | yes (0.4) | yes (2.0 ≤ 10.0) | **AshCam** |
| V1cam | yes (0.3) | yes (2.0 ≤ 10.0) | **AshCam** (the camera stays disabled for live polling; the setting applies if it is enabled) |
| F1cam | no (6.3) | no (20.0 > 10.2) | **M.jpg** (AshCam archives F1 sparsely) |

`config/sources.yaml` sets `live_source: ashcam` on KPcam, K2cam and V1cam. The worker sends those cameras to `AshcamIngestor`, which stores every frame archived since the newest stored one, reaching back at most one hour. Longer gaps are filled with `vigia-backfill`. If AshCam fails, those cameras fall back to `M.jpg` automatically (see Caveats). F1cam keeps the conditional-GET `M.jpg` poller.

## Caveats

- **One short window.** The measurement covers 40 min on one morning (HST) during a quiet period. Re-check the latency if the archive seems to lag during an eruption.
- **Undocumented API.** AshCam's API can change without notice. When it fails for a camera, the worker falls back to that camera's `M.jpg` in the same poll, so frames keep coming every 10 min. This covers an HTTP error, a timeout, an index in an unexpected format, or any exception from the AshCam ingestor; it is checked against the real servers with a broken API URL.
  - AshCam's error is logged, and `camera_state` shows the `M.jpg` outcome.
  - Frames from the fallback carry `timestamp_source = 'http_last_modified'`, so on KP and K2 their times are approximate (Last-Modified trails the capture by up to ~10 min).
  - When AshCam recovers, its next poll fills the last hour at the full cadence. Frames already stored from `M.jpg` de-duplicate and keep their approximate time.
  - Setting `live_source: url` on a camera turns AshCam off for it entirely.
- **Live source only.** The archive keeps about 31 days, and the episode 55 replay depends on frames already stored locally, not on this setting.
