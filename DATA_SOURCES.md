# Data sources

Every source Volcano Vigil reads, its license, and how it is used. Cameras are declared in [`config/sources.yaml`](config/sources.yaml), each with a `license`, an `attribution` and an `enabled` flag; a camera is fetched only when it is enabled.

**No images, videos or masks are stored in this repository.** Everything downloaded lives under `data/`, which is git-ignored. A deployment fetches its own copies from the original sources.

## In use

| Source | What we use | License / terms | Credit |
|---|---|---|---|
| [USGS HVO Kīlauea webcams](https://www.usgs.gov/volcanoes/kilauea/multimedia/webcams) | Latest frame of each summit camera (`https://volcanoes.usgs.gov/cams/<CAM>/images/M.jpg`), polled every few minutes with conditional GET for cameras with `live_source: url` (F1cam today). Cameras: V1cam, V2cam, V3cam, K2cam, KWcam, B1cam, KPcam, F1cam (thermal). | Public domain (USGS webcam pages are marked "Public Domain") | U.S. Geological Survey |
| [USGS AshCam API](https://volcview.wr.usgs.gov/ashcam-api/) | Archived frames of the same cameras with exact capture timestamps and MD5 checksums. The files are byte-identical to the `M.jpg` of the same capture. Query: `imageApi/webcam?webcamCode=kilauea-v1-cam&startTimestamp=<epoch>&endTimestamp=<epoch>`. The archive keeps about 31 days. Uses: `vigil-backfill` (episode 55 replay, history), and live polling of KPcam and K2cam (`live_source: ashcam`), where it is fresher than `M.jpg` ([measurement](docs/research/ashcam_latency.md)). The API is undocumented, so if it fails those cameras fall back to `M.jpg` automatically. | Public domain (USGS imagery) | U.S. Geological Survey |
| [USGS HVO episode 55 photo and video chronology](https://www.usgs.gov/observatories/hvo/news/photo-video-chronology-kilauea-summit-episode-55-0) | Photos, a video and the daily webcam timelapses of 2026-10-17 for the replay and validation mode. | Public domain | U.S. Geological Survey |
| [USGS HVO Kīlauea updates](https://www.usgs.gov/volcanoes/kilauea/volcano-updates) | Officially reported fountain and plume heights, quoted with their source, to validate the agent's measurements. | Public domain | U.S. Geological Survey |

## Planned

| Source | What we will use | License / terms | Credit |
|---|---|---|---|
| [Open-Meteo](https://open-meteo.com) | Forecast winds at pressure levels over each volcano, to compare with the observed plume drift. No API key. | CC BY 4.0, free for non-commercial use | Weather data by Open-Meteo.com |
| [USGS Kīlauea fountain-height dataset](https://doi.org/10.5066/P14MLKCX) | Per-minute fountain heights for episodes 1–50, as extra ground truth for validating height estimates. The download host blocks scripts, so it is fetched manually. | CC0 1.0 | U.S. Geological Survey |

## Not configured yet

| Source | Status |
|---|---|
| USGS Alaska Volcano Observatory webcams | Not configured yet. USGS-hosted AVO webcam pages state "Sources/Usage: Public Domain" (e.g. [Akutan](https://www.usgs.gov/media/webcams/akutan-aksd)); check each camera's page before enabling it. |

## Not used

| Source | Reason |
|---|---|
| IGEPN (Ecuador) webcams | Copyrighted, no published license. Not used without permission. |
| Sernageomin (Chile) webcams | Block automated access. Not used without permission. |

## Processing services (not data sources)

Frames are sent to the [Meta Model API](https://dev.meta.ai) (Muse Spark 1.3 and SAM 3.1) for analysis. Only frames from sources listed under "In use" are sent.
