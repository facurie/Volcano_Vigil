# Vigía Andino: Implementation Plan (Oct 27 – Nov 4, 2026)

> **For agentic workers:** this is the master roadmap, approved by the author on 2026-10-27. Work phase by phase. At the start of each phase, write that phase's bite-sized TDD plan with `superpowers:writing-plans` into `docs/superpowers/plans/YYYY-MM-DD-<phase>.md`, then execute it with `superpowers:executing-plans` or `superpowers:subagent-driven-development`. Tick the checkboxes here when a task is done and commit the change.

**Goal:** an agent that watches public volcano webcams, measures plumes and lava fountains (height in meters ± σ, drift direction against forecast wind), tracks them over time, writes cited ES/EN bulletins, and proves its accuracy by replaying Kīlauea episode 55 against official USGS values.

**Architecture:** a polling ingest feeds SQLite and `data/`. Then a quality gate runs: cheap local checks first, Muse Spark only when they can't decide. Next, SAM 3.1 tracks objects in video mode over timelapses built from the frames, and geometric metrics are computed. A Muse Spark agent with tool calling decides what to inspect and writes the bulletins. A FastAPI dashboard shows live and replay modes. Every Meta call goes through `MetaClient` (budget check + cost ledger).

**Tech stack:** Python 3.12, httpx, OpenAI SDK against the Meta Model API (`muse-spark-1.3`, `sam-3.1`), `meta-sam-parser`, SQLite, Pillow/numpy, ffmpeg, FastAPI, Leaflet, Open-Meteo. Deployment: Hugging Face Spaces (Docker).

---

## How to resume in a new session

1. Read this file, then [docs/META_API_NOTES.md](META_API_NOTES.md), [docs/research/](research/), [DATA_SOURCES.md](../DATA_SOURCES.md), and the private brief `prompt-vigia-andino.md` (workspace root, git-excluded).
2. Set up the environment:
   - `py -3.12 -m venv .venv`
   - `.venv\Scripts\python.exe -m pip install -e ".[dev]"`
   - add `MODEL_API_KEY` to `.env`
3. Run the tests: `.venv\Scripts\python.exe -m pytest` (53 passing at the end of session 1).
4. Conventions:
   - TDD; small commits with no `Co-Authored-By` trailer (author's request).
   - English code, comments and docs; bulletins in ES and EN.
   - No images in git: everything lives in git-ignored `data/`.
   - Every Meta call goes through `vigia/meta/client.py`.
5. Hard rules:
   - SGC (Ruiz) cameras stay `enabled: false` until SGC grants permission.
   - Every bulletin carries the "does not replace official alerts" disclaimer and a link to the official agency.
   - No RAG and no generic features.
6. Remote: `github.com/facurie/vigia-andino`. It is private now and must be made public before submission.

## Done in session 1 (2026-10-26)

- [x] Meta Model API notes: IDs, endpoints, formats, limits, prices ([META_API_NOTES.md](META_API_NOTES.md))
- [x] Repo scaffold: `.gitignore`, `.env.example`, README, LICENSE (MIT), [DATA_SOURCES.md](../DATA_SOURCES.md), [config/sources.yaml](../config/sources.yaml)
- [x] Ingest worker `vigia-ingest`: conditional GET, image validation, SHA-256 de-dup, Last-Modified timestamps, camera state. Verified live against USGS.
- [x] Cost ledger with daily cap, pricing, SAM output parser, `MetaClient` (Muse Spark JSON, SAM image, SAM video streaming, Files API)
- [x] Mask overlay renderer, ffmpeg helpers, smoke test (`scripts/smoke_test.py`)
- [x] Research: [episode 55](research/episode55.md), [Kīlauea webcams](research/kilauea_webcams.md), [geometry draft](research/kilauea_geometry_draft.yaml)

## Facts the plan depends on

- **Smoke test** (`data/smoke/20261027T001945Z/summary.md`, $0.05):
  - Muse Spark reads burned-in HST timestamps exactly and rejects fog.
  - SAM `lava fountain` works (0.89).
  - SAM `volcanic plume` returns the fountain, not the gas column; only `steam` found the column. Plume prompts must be tuned.
  - SAM video kept one stable track of the fountain for 93/100 frames and dropped it when the fountain ended.
- **Live cameras** (public domain): KPcam (whole plume column, ~14 km, the camera USGS uses for plume height), K2cam (fountain and lower plume, PTZ) and F1cam (thermal, sees through fog), polled every 2 min. Public `M.jpg` images change every 10 min.
- **USGS AshCam API:** 2-min archived frames with exact epoch timestamps and MD5 checksums, kept for about 31 days. Query pattern: `https://volcview.wr.usgs.gov/ashcam-api/imageApi/webcam?webcamCode=kilauea-kp-cam&startTimestamp=<epoch>&endTimestamp=<epoch>`. 857 episode-55 frames are already in `data/raw/usgs_ep55/ashcam/`; the Oct 17 frames will expire around Nov 17.
- **PTZ cameras** (V1, V2, V3, K2) print pan/tilt/zoom and the HST time on the frame, so calibration must be per preset.
- **Official episode 55 values** (quotes in [episode55.md](research/episode55.md)):
  - Fountain: 720 ft (220 m) at 04:50–05:10 HST; then 650 ft at 06:02, 500 ft at 07:00 and 300 ft at 08:00.
  - Plume: 25,000 ft a.s.l. at the peak; 17,000 ft at 06:02; under 13,000 ft by 07:30.
  - Onset 03:19 HST, end 09:03 HST. Drift to the SW (wind from the NNE). Vent elevation ~1,075–1,080 m.
- **Geometry:** vent coordinates are published (north vent 19.40496 N, 155.29022 W). B1cam and F1/KWcam positions are published; KP, K2 and V1–V3 are estimates.
- **Extra ground truth:** USGS fountain-height dataset, CC0, doi:10.5066/P14MLKCX (episodes 1–50; manual download).

## Target module map

```
vigia/
  config.py settings.py db.py timeutil.py overlay.py video.py   (exist)
  ingest/fetch.py ingest/worker.py                              (exist)
  ingest/ashcam.py        AshCam archive client and backfill    (phase 1)
  meta/client.py sam.py pricing.py ledger.py                    (exist)
  quality.py              local checks + Muse Spark gate         (phase 2)
  tracking.py             timelapse build + SAM video tracks     (phase 2)
  geometry.py             camera model, calibration, height ± σ  (phase 3)
  metrics.py              area, height, drift per detection      (phase 3)
  wind.py                 Open-Meteo winds aloft                 (phase 4)
  agent/tools.py loop.py bulletin.py                             (phases 4–5)
  replay.py               episode replay on a simulated clock    (phase 5)
  web/app.py web/static/  FastAPI + dashboard                    (phase 6)
config/prompts.yaml       SAM phrases per target/camera kind     (phase 1)
config/calibration.yaml   per camera and PTZ preset              (phase 3)
```

---

## Phase 1: Tue Oct 27. AshCam, prompt tuning, overlay legend

- [ ] **AshCam client** in `vigia/ingest/ashcam.py`.
  - `list_images(webcam_code, start, end) -> list[AshcamImage]`, where `AshcamImage` has timestamp, url and md5.
  - `download(image)` verifies the MD5 and stores the frame through the same `frames` table, with `timestamp_source='ashcam'`.
  - Add an `ashcam_code` field to cameras in `sources.yaml`, e.g. `kilauea-kp-cam`.
  - CLI: `vigia-backfill --camera kilauea-kp --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z`.
  - Test against a trimmed copy of a real index JSON served by `httpx.MockTransport`.
- [ ] **Live source decision:** measure AshCam latency against `M.jpg`. If AshCam publishes within about 5 min, use it for live polling too: 2-min cadence and exact timestamps.
- [ ] **SAM prompt tuning** in `scripts/tune_prompts.py`. Use frames from KP at the 04:50–05:10 peak, K2, V1 at 06:59 and F1.
  - Plume candidates: `steam plume`, `white plume`, `eruption column`, `gas plume`, `volcanic gas plume`, `ash cloud`.
  - Fountain candidates: `lava fountain`, `fountain of lava`, `glowing lava`.
  - Night candidates: `incandescent lava`, `glow`.
  - Write the chosen phrases to `config/prompts.yaml` (per target and camera kind) and the evidence table to `docs/research/prompt_tuning.md`. Budget about $0.15.
- [ ] **Overlay legend:** draw the legend in a strip below the image so it never hides burned-in text or the plume. Update `tests/test_overlay.py`.

**Acceptance:** episode 55 KP/K2/V1 frames backfilled from AshCam with exact timestamps; `prompts.yaml` committed; tests green.

## Phase 2: Wed Oct 28. Quality gate and timelapse tracking

- [ ] **`vigia/quality.py`, local checks** (no API cost):
  - stale: capture time older than 30 min;
  - frozen: the same hash, or an unchanged streak;
  - night: solar elevation at the camera below −6° (keep only if incandescence is plausible);
  - low visibility: contrast and edge-density thresholds, calibrated on the smoke test's fog frame.
- [ ] **Muse Spark gate** for frames that pass the local checks: usability, the printed timestamp and the printed PTZ values. Move the smoke test's JSON schema into the package. Store the result in a `frame_quality` table.
- [ ] **`vigia/tracking.py`:**
  - Assemble N consecutive usable frames of a camera into an MP4.
  - Upload it and run SAM video once per phrase from `prompts.yaml`.
  - Persist `tracks` (camera, phrase, window) and `detections` (frame_id, track_id, box, score, area, mask as COCO RLE via `decode_mask_to_rle`).
- [ ] **Cost rule:** SAM bills at least 50 frames per video request, so send windows of 50 frames or more when backfilling; live, use one window per hour.

**Acceptance:**
- Tracks exist for episode 55 V1/K2/KP.
- The fountain track ends within ±10 min of 09:03 HST.
- Fog and night frames are rejected without Muse Spark calls.

## Phase 3: Thu Oct 29. Geometry, metrics, first validation

- [ ] **`config/calibration.yaml`** (user-fillable, seeded from the geometry draft). Per camera and PTZ preset:
  - camera position and elevation ± σ;
  - vent position;
  - image size;
  - field of view and/or reference points `{name, pixel [x, y], lat, lon, elev}`.
- [ ] **`vigia/geometry.py`:**
  - Pinhole model. Solve azimuth, tilt and focal length from two or more reference points (least squares).
  - Height above the vent: `D · (tan θ_top − tan θ_vent)`. Correct for Earth curvature and refraction at long range (~13 m for KPcam at 14 km).
  - σ by Monte Carlo over camera position, distance, focal length, mask edge (±3 px) and plume lean.
- [ ] **`vigia/metrics.py`:** per detection, top height (m ± σ), area (m² at vent range) and drift bearing (mask centroid offset against the vent column, plus camera azimuth; with one camera only the across-track component is known).
- [ ] **Calibration strategy:** use cameras with published positions (B1, F1/KW) and landmarks. Use the official values only to check the result, never to fit it.
- [ ] **`scripts/validate_ep55.py`:**
  - Measure the fountain at the peak, 06:02, 07:00 and 08:00, and the plume at the peak, 06:02 and 07:30.
  - Also measure the end time and the drift direction.
  - Write the comparison table with errors to `docs/VALIDATION.md`.

**Acceptance:** first validation table, with errors and σ.

## Phase 4: Fri Oct 30. Wind and agent tools

- [ ] **`vigia/wind.py`** (check the current Open-Meteo docs via Context7 first):
  - Get wind speed and direction plus geopotential height at the 850/700/600/500/400/300 hPa levels over the vent.
  - For Oct 17, use Open-Meteo's historical forecast API.
  - Interpolate to the plume height, then compare with the measured drift bearing (agreement in degrees).
- [ ] **`vigia/agent/tools.py`:**
  - Strict JSON-schema tools: `list_cameras_status`, `get_recent_frames(camera, hours)`, `assess_frame(frame_id)`, `segment_frame(frame_id, phrase)`, `track_window(camera, start, end, phrase)`, `measure_track(track_id)`, `get_wind(volcano, height_m, time)`, `compare_cameras(volcano, time)`, `get_history(camera, metric, hours)`.
  - Validate tool arguments; the API does not guarantee them.
- [ ] **`vigia/agent/loop.py`:**
  - Responses API loop with `previous_response_id`, resending tools and instructions on every turn, and parallel tool calls.
  - Max-turn and budget guards.
  - Persist the trace in `agent_runs` and `agent_steps`; it will be shown in the dashboard.

**Acceptance:** replayed at 05:00 HST on Oct 17, the agent picks KPcam, measures the plume, checks it against the wind (SW drift) and leaves a full trace.

## Phase 5: Sat Oct 31. Bulletins and replay

- [ ] **`vigia/agent/bulletin.py`:**
  - Strict schema: descriptive activity level (never an official alert level), headline and body in ES and EN, `measurements[{metric, value, sigma, unit, frame_ids}]`, `evidence[{frame_id, overlay}]`, official source (agency and URL), disclaimer.
  - Render to HTML and Markdown.
- [ ] **`vigia/replay.py` and the `vigia-replay --episode 55 --speed 60` CLI:**
  - Feed the AshCam episode-55 frames through the same pipeline on a simulated clock: quality, tracking, metrics, and the agent every N minutes.
  - Write a timeline JSON.
- [ ] **Muse Spark video understanding:** send the episode timelapse and ask for the phases (onset, peak, decline, end). Cross-check with the SAM-derived times.

**Acceptance:** the replay produces six or more bulletins across the episode, plus the comparison table against USGS.

## Phase 6: Sun Nov 1. Dashboard

- [ ] **`vigia/web/app.py`** (FastAPI): `/api/cameras`, `/api/frames/latest`, `/api/series`, `/api/bulletins`, `/api/replay`, `/api/agent/trace`.
- [ ] **`vigia/web/static/`:**
  - Leaflet map: cameras, vent, drift arrow, wind arrow.
  - Current frame with mask overlay.
  - Height chart over time.
  - Bulletin feed with an ES/EN toggle.
  - Camera status (fresh / stale / fog / night).
  - Replay player and agent trace view.
  - The disclaimer banner is always visible.

**Acceptance:** the local dashboard shows both live and replay.

## Phase 7: Mon Nov 2. Deployment

- [ ] **Hugging Face Spaces (Docker):**
  - `Dockerfile` from `python:3.12-slim` with ffmpeg.
  - The ingest worker runs in-process with the web app.
  - Secrets are Space secrets. Set `DAILY_BUDGET_USD=3`.
- [ ] **On startup:** backfill the last days of live history and the episode-55 frames from AshCam, until about Nov 17. Optionally mirror the episode-55 frames (public domain) to a public HF dataset so the replay survives AshCam expiry. Images never go into the git repo.

**Acceptance:** a public URL is live, with ingest running and the replay working.

## Phase 8: Tue Nov 3. Validation report, README, polish

- [ ] Final `docs/VALIDATION.md`: errors, σ, limitations.
- [ ] Final README: updated diagram, live URL, how to run, the "Built during the hackathon" section, disclaimer, credits, cost report.
- [ ] Code review pass (`superpowers:requesting-code-review`) and fixes.

## Phase 9: Wed Nov 4. Video and submission (afternoon, not last minute)

- [ ] **3-minute video:**
  1. The problem: Armero 1985, and webcams nobody watches.
  2. Live dashboard: camera status and the quality gate at work.
  3. Episode-55 replay: SAM tracking overlay, agent trace, bilingual bulletins.
  4. Validation numbers against USGS.
  5. The Ruiz-ready config (disabled pending permission).
  6. The disclaimer.
- [ ] Make the repository public and submit before 21:00 ET (23:00 Argentina).

## Extras (only if time remains)

- [ ] River/lahar module on the Río Gualí camera (needs SGC permission)
- [ ] Nevado del Ruiz live (if SGC authorizes)
- [ ] Telegram notifications

## Budget

Spent so far: $0.05 (smoke test). Estimate: about $3–5/day with the live agent, about $40 in total out of the $150 credit. `DAILY_BUDGET_USD` caps every day.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| SAM prompts for gas plumes are ambiguous | Phase 1 tuning; let Muse Spark suggest phrases |
| Camera positions and fields of view unpublished | `calibration.yaml` + reference points; validate on B1 and F1/KW, whose positions are published |
| PTZ cameras change framing | Read P/T/Z from the frame and calibrate per preset; skip unknown presets |
| AshCam keeps about 31 days | Keep local copies; optional HF dataset mirror |
| Volcano quiet during judging | The replay is the centerpiece; live mode shows the quality gate and camera status |
| Session quota runs out mid-task | This file plus the memory notes; commit often |
