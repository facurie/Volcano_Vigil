# Volcano Vigil: Implementation Plan (Oct 27 – Nov 4, 2026)

> **For agentic workers:** this is the master roadmap, approved by the author on 2026-10-27. Work phase by phase. At the start of each phase, write that phase's bite-sized TDD plan with `superpowers:writing-plans` into `docs/superpowers/plans/YYYY-MM-DD-<phase>.md`, then execute it with `superpowers:executing-plans` or `superpowers:subagent-driven-development`. Tick the checkboxes here when a task is done and commit the change.

> **Renamed on 2026-10-30.** The project was called Vigía Andino until then, with the package `vigia` and the CLIs `vigia-*`. The phase plans written before the rename keep the old names.

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
3. Run the tests: `.venv\Scripts\python.exe -m pytest -o addopts=""` (556 passing at the end of Phase 6, session 7; they include the dashboard's JS helper tests, run with node).
4. Conventions:
   - TDD; small commits with no `Co-Authored-By` trailer (author's request).
   - English code, comments and docs; bulletins in ES and EN.
   - No images in git: everything lives in git-ignored `data/`.
   - Every Meta call goes through `vigil/meta/client.py`.
   - Subagents live in `.claude/agents/`:
     - `implementer` (Sonnet) runs one plan task with TDD and commits locally.
     - `reviewer` (Sonnet) reviews those commits, read-only.
     - `researcher` (Haiku, or Sonnet when the answer feeds a decision) does read-only research.
     - The orchestrator verifies the result, ticks the boxes and pushes.
5. Hard rules:
   - The scope is Kīlauea only (decided 2026-10-30).
   - Every bulletin carries the "does not replace official alerts" disclaimer and a link to the official agency.
   - No RAG and no generic features.
6. Remote: `github.com/facurie/Volcano_Vigil`. It is private now and must be made public before submission.

## Done in session 1 (2026-10-26)

- [x] Meta Model API notes: IDs, endpoints, formats, limits, prices ([META_API_NOTES.md](META_API_NOTES.md))
- [x] Repo scaffold: `.gitignore`, `.env.example`, README, LICENSE (MIT), [DATA_SOURCES.md](../DATA_SOURCES.md), [config/sources.yaml](../config/sources.yaml)
- [x] Ingest worker `vigil-ingest`: conditional GET, image validation, SHA-256 de-dup, Last-Modified timestamps, camera state. Verified live against USGS.
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
- **AshCam frames are byte-identical to the live `M.jpg`** (same SHA-256 and MD5), and their epoch equals the capture time in the camera's `js.js`, so SHA-256 de-duplication works across both sources. Episode 55 KP (78), K2 (195) and V1 (195) frames are in `data/frames/` with `timestamp_source='ashcam'`.
- **Live source** ([ashcam_latency.md](research/ashcam_latency.md)):
  - AshCam publishes each frame within 0.2–0.4 min (median) at 2-min cadence (KP 5 min). `M.jpg` publishes one capture every 10 min, 1–3.5 min after it was taken.
  - KPcam and K2cam (and V1cam if enabled) poll AshCam live (`live_source: ashcam`). F1cam keeps `M.jpg`, because AshCam archives it only every ~20 min.
  - If AshCam fails (HTTP error, timeout, unexpected index format), those cameras fall back to `M.jpg` in the same poll. While that lasts, their timestamps are approximate.
- **SAM phrases** ([prompt_tuning.md](research/prompt_tuning.md)):
  - Visible cameras: plume `steam` (the whole column from 14 km at night to 1 km by day), fountain `lava fountain`, incandescence `glow`.
  - Thermal cameras: incandescence `glowing lava` (the hot lava field).
  - Every phrase with "volcanic" in it returns the fountain on close cameras.
  - Large masks come at reduced raster resolution (long side 1024 px); `vigil/meta/sam.py` scales them to their box.
- **Quality gate** ([quality_calibration.md](research/quality_calibration.md)):
  - Local checks, calibrated on 984 frames:
    - fog: edge density < 0.005;
    - hazy, sent to Muse Spark: 0.005–0.015;
    - night (sun < −6°): rejected unless incandescent patches cover ≥ 0.05 % (2×2 block patches, so K2's path lamps don't count);
    - frozen: fingerprint change < 0.15.
  - Episode 55: all 468 frames pass locally, with no Muse Spark call.
  - A foggy afternoon sends 39 hazy frames to Muse Spark ($0.30). Muse Spark rejected all 15 K2/KP fog frames and kept 23 of 24 hazy V1 views.
  - Known false passes: K2 fog that leaves the foreground sharp; KP overcast.
  - Muse Spark reads the printed time within 6 s of the capture time and parses PTZ readouts (V1 presets 9.4×, 1.4×, 1.0×, and 9.6× on Oct 26).
- **Tracking** ([tracking_ep55.md](research/tracking_ep55.md)):
  - Episode 55 on V1, K2 and KP: one 1920×1080 window per camera at 10 fps, 3 phrases each, $0.28.
  - The fountain's last detection is 09:02 HST on K2 and 09:01 HST on V1; the official end is 09:03.
  - V1 keeps one fountain track through its PTZ changes.
  - `steam` masks include the cloud drifting downwind.
  - KP `glow` hit a lens flare in daylight.
  - Decoding big plume masks in `meta_sam_parser` (pure Python) takes about 11 min for K2's 168 masks.
- **Calibration** ([calibration_ep55.md](research/calibration_ep55.md)):
  - The camera model is a pinhole plus one radial-distortion term k1. Heights sit on the vertical plane through the vent, with curvature and refraction.
  - σ comes from a 1,000-sample Monte Carlo over positions, refraction, picked pixels, mask edge and lean.
  - **KPcam is calibrated from nine Moon positions** (AshCam frames of Oct 16, 19 and 20, JPL Horizons, `scripts/moon_references.py`):
    - RMS misfit 1.6 px, focal 3,509 ± 13 px, k1 −0.280 ± 0.006, field of view 62.9°. A pinhole would misfit by 24 px.
    - Independent checks: the vent lands 30 px from the fountain, and the predicted sea horizon lies on the trade-cumulus base.
  - **K2cam is not calibrated.** Its GNIS cones and the 3DEP skyline leave the focal length between 2,100 and 3,500 px. No clear sea horizon shows on Oct 15–19, and the night frames are black.
  - V1cam's position is known only to ±150 m.
- **Validation** ([VALIDATION.md](VALIDATION.md)):
  - KPcam plume top at the peak: 6,951 ± 429 m against 7,620 m (−9 %, within 2σ).
  - At 06:02: 5,169 ± 205 m against 5,182 m.
  - At 07:30: 4,416 ± 137 m against "under 3,962 m". The mask's top is cloud 2.5–3 km downwind.
  - End of fountaining: K2 −1.0 min and V1 −1.9 min against 09:03.
  - Drift: all 75 KPcam frames on the 224° side, consistent with HVO's SW.
  - Fountain heights are not measured yet.
- **Wind** (`vigil/wind.py`, [VALIDATION.md](VALIDATION.md)):
  - Open-Meteo levels 850–300 hPa. Hours older than 2 days come from the Historical Forecast API, the rest from the Forecast API. One UTC day is fetched at a time and cached in `wind_profiles`.
  - The drift side is compared with the mean wind between the vent and the plume top. It agrees in 74 of 75 KPcam frames (median 39°); the wind at the top alone agrees in only 58.
  - At 05:00 HST the layer blew from 331° towards 151° at 3.3 m/s, 73° from the measured side.
  - The model has the low-level wind from N–NNW; HVO said NE.
- **Agent** ([agent_ep55.md](research/agent_ep55.md)):
  - Nine strict tools (`vigil/agent/tools.py`) see only data captured up to the agent's clock. Arguments are validated, and Muse Spark has sent the string "null" for null.
  - The loop (`vigil/agent/loop.py`, `vigil-agent`) resends the whole conversation on every turn, with `store: false`. Until Phase 5 it chained turns with `previous_response_id`, but Meta's response store failed on 4 of 39 replay turns (503, and 400 "referenced response not found"). A turn that gets a 5xx is sent again after 2 s and then 8 s.
  - Guards: 12 turns, with a wrap-up message on the last, and $0.30 per run through a tagged `MetaClient`. The trace goes to `agent_runs` and `agent_steps`.
  - The replay at 05:00 HST took 5 turns and $0.03–0.06. It picked KPcam, measured 6,951 ± 429 m and found the drift consistent with the wind.
- **Bulletins** (`vigil/agent/bulletin.py`, `vigil/agent/render.py`, `vigil-bulletin`):
  - Muse Spark's final answer is a draft in a strict JSON format (`text.format` on every turn). Commentary before tool calls stays plain text.
  - The code checks every quoted number against the stored measurements up to the clock. It adds the official agency, the link and the disclaimer from config, takes the wind check from the run's `get_wind`, and draws the evidence overlays.
  - Output: HTML (both languages, escaped) and Markdown per language.
  - `tool_choice` accepts only `"auto"` on the Meta API.
- **Pipeline and replay** ([replay_ep55.md](research/replay_ep55.md)):
  - `vigil/pipeline.py` (`vigil-pipeline` live) runs one step:
    - the quality gate;
    - one SAM window per camera per closed hour, led in by earlier frames up to the 50 billed, so a window that starts on a faint plume still tracks it;
    - measuring;
    - the agent's bulletin every hour.
  - `vigil-replay --episode 55` replays 13:00–19:30Z on a 5-minute simulated clock in `data/replay/ep55/`:
    - 7 bulletins, every number verified; 64 min and $1.03;
    - the bulletins quote the plume top at −9 % (peak) and +1 % (06:02) of HVO's values;
    - fountaining was first reported at 04:00 and no longer reported at 09:30 (hourly);
    - end of fountaining: K2 −1.0 min, V1 +0.0 min.
  - Muse Spark reading the K2cam timelapse (video input, $0.05) gets the end within 3 min, but puts the peak after sunrise (+110 min). SAM's fountain-box heights put the peak and the decline inside HVO's windows.
- **Dashboard** (`vigil-web`, [phase 6 plan](superpowers/plans/2026-10-30-phase-6-dashboard.md)):
  - A `Scene` is one database (live, or `data/replay/ep<key>/`) seen at one clock. A SAM detection, and the measurements made from it, show only once its run's `window_end` (the capture time of the run's last frame) is ≤ the clock. HVO heights show once their window has closed, phases once their latest time has passed, and the comparison tables only at the episode's end.
  - Frames go to the browser as JPEGs at most 1,280 px wide, with their visible masks drawn: about 95 ms each.
  - The bulletins show the disclaimer as the code gives it now. The episode 55 bulletins were stored before the rename and still say "Vigía Andino".
  - Chart colours passed the dataviz checks on the dark panels: plume `#259ed6`, HVO `#c3518d` (lehua), fountain `#f25820`. The overlay colours are too light for a dark chart, so they only key the masks drawn on the frames.
  - Headless Edge (`--headless=new` with a separate `--user-data-dir`) takes the screenshots. It will not render below about 500 px wide.

## Target module map

```
vigil/
  config.py settings.py db.py timeutil.py overlay.py video.py   (exist)
  imaging.py              frame preprocessing for upload        (exists, phase 1)
  prompts.py              SAM phrases per target and camera kind (exists, phase 1)
  ingest/fetch.py ingest/worker.py                              (exist)
  ingest/store.py         shared frame storage + camera state   (exists, phase 1)
  ingest/ashcam.py        AshCam archive client and backfill    (exists, phase 1)
  meta/client.py sam.py pricing.py ledger.py                    (exist)
  sun.py                  sun elevation for the night check      (exists, phase 2)
  quality.py              local checks: stale, frozen, night, fog (exists, phase 2)
  gate.py                 quality gate + frame_quality; vigil-quality (exists, phase 2)
  masks.py                COCO RLE masks                         (exists, phase 2)
  tracking.py             timelapse build + SAM video tracks; vigil-track (exists, phase 2)
  geometry.py             camera model, view solver, heights     (exists, phase 3)
  calibration.py          calibration.yaml + Monte Carlo of the view (exists, phase 3)
  metrics.py              area, height, drift per detection; vigil-measure (exists, phase 3)
  wind.py                 Open-Meteo winds aloft; vigil-wind     (exists, phase 4)
  agent/tools.py loop.py  nine tools + tool loop; vigil-agent    (exist, phase 4)
  agent/bulletin.py       checked bilingual bulletins; vigil-bulletin (exists, phase 5)
  agent/render.py         bulletins as Markdown and HTML         (exists, phase 5)
  pipeline.py             quality, hourly tracking, bulletins; vigil-pipeline (exists, phase 5)
  episodes.py             episode 55 and its official values    (exists, phase 5)
  replay.py               episode replay on a simulated clock; vigil-replay (exists, phase 5)
  phases.py               episode phases: SAM vs Muse Spark video (exists, phase 5)
  web/views.py            the dashboard's queries, one DB at one clock (exists, phase 6)
  web/app.py web/static/  FastAPI + dashboard; vigil-web          (exist, phase 6)
config/prompts.yaml       SAM phrases per target/camera kind     (exists, phase 1)
config/calibration.yaml   per camera and PTZ preset              (exists, phase 3)
```

---

## Phase 1: Tue Oct 27. AshCam, prompt tuning, overlay legend

- [x] **AshCam client** in `vigil/ingest/ashcam.py`.
  - `list_images(webcam_code, start, end) -> list[AshcamImage]`, where `AshcamImage` has timestamp, url and md5.
  - `download(image)` verifies the MD5 and stores the frame through the same `frames` table, with `timestamp_source='ashcam'`.
  - Add an `ashcam_code` field to cameras in `sources.yaml`, e.g. `kilauea-kp-cam`.
  - CLI: `vigil-backfill --camera kilauea-kp --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z`.
  - Test against a trimmed copy of a real index JSON served by `httpx.MockTransport`.
- [x] **Live source decision:** measure AshCam latency against `M.jpg`. If AshCam publishes within about 5 min, use it for live polling too: 2-min cadence and exact timestamps.
- [x] **SAM prompt tuning** in `scripts/tune_prompts.py`. Use frames from KP at the 04:50–05:10 peak, K2, V1 at 06:59 and F1.
  - Plume candidates: `steam plume`, `white plume`, `eruption column`, `gas plume`, `volcanic gas plume`, `ash cloud`.
  - Fountain candidates: `lava fountain`, `fountain of lava`, `glowing lava`.
  - Night candidates: `incandescent lava`, `glow`.
  - Write the chosen phrases to `config/prompts.yaml` (per target and camera kind) and the evidence table to `docs/research/prompt_tuning.md`. Budget about $0.15.
- [x] **Overlay legend:** draw the legend in a strip below the image so it never hides burned-in text or the plume. Update `tests/test_overlay.py`.

**Acceptance:** episode 55 KP/K2/V1 frames backfilled from AshCam with exact timestamps; `prompts.yaml` committed; tests green.

## Phase 2: Wed Oct 28. Quality gate and timelapse tracking

- [x] **`vigil/quality.py`, local checks** (no API cost):
  - stale: capture time older than 30 min;
  - frozen: the same hash, or an unchanged streak;
  - night: solar elevation at the camera below −6° (keep only if incandescence is plausible);
  - low visibility: contrast and edge-density thresholds, calibrated on the smoke test's fog frame.
- [x] **Muse Spark gate** for frames that pass the local checks: usability, the printed timestamp and the printed PTZ values. Move the smoke test's JSON schema into the package. Store the result in a `frame_quality` table.
- [x] **`vigil/tracking.py`:**
  - Assemble N consecutive usable frames of a camera into an MP4.
  - Upload it and run SAM video once per phrase from `prompts.yaml`.
  - Persist `tracks` (camera, phrase, window) and `detections` (frame_id, track_id, box, score, area, mask as COCO RLE via `decode_mask_to_rle`).
- [x] **Cost rule:** SAM bills at least 50 frames per video request, so send windows of 50 frames or more when backfilling; live, use one window per hour.

**Acceptance:**
- Tracks exist for episode 55 V1/K2/KP.
- The fountain track ends within ±10 min of 09:03 HST.
- Fog and night frames are rejected without Muse Spark calls.

## Phase 3: Thu Oct 29. Geometry, metrics, first validation

- [x] **`config/calibration.yaml`** (user-fillable, seeded from the geometry draft). Per camera and PTZ preset:
  - camera position and elevation ± σ;
  - vent position;
  - image size;
  - field of view and/or reference points `{name, pixel [x, y], lat, lon, elev}`.
- [x] **`vigil/geometry.py`:**
  - Pinhole model. Solve azimuth, tilt and focal length from two or more reference points (least squares). Done with one radial-distortion term too: KPcam's lens bends its corners by a tenth.
  - Height above the vent: `D · (tan θ_top − tan θ_vent)`. Correct for Earth curvature and refraction at long range (~13 m for KPcam at 14 km).
  - σ by Monte Carlo over camera position, distance, focal length, mask edge (±3 px) and plume lean.
- [x] **`vigil/metrics.py`:** per detection, top height (m ± σ), area (m² at vent range) and drift bearing (mask centroid offset against the vent column, plus camera azimuth; with one camera only the across-track component is known).
- [x] **Calibration strategy:** use cameras with published positions (B1, F1/KW) and landmarks. Use the official values only to check the result, never to fit it. Done differently: KPcam is calibrated from nine Moon positions (JPL Horizons); B1 and F1/KW are fisheye and untracked, so they are not used.
- [x] **`scripts/validate_ep55.py`:** (fountain rows pending: no K2cam calibration, see [VALIDATION.md](VALIDATION.md) and Phase 9)
  - Measure the fountain at the peak, 06:02, 07:00 and 08:00, and the plume at the peak, 06:02 and 07:30.
  - Also measure the end time and the drift direction.
  - Write the comparison table with errors to `docs/VALIDATION.md`.

**Acceptance:** first validation table, with errors and σ.

## Phase 4: Fri Oct 30. Wind and agent tools

- [x] **`vigil/wind.py`** (check the current Open-Meteo docs via Context7 first):
  - Get wind speed and direction plus geopotential height at the 850/700/600/500/400/300 hPa levels over the vent.
  - For Oct 17, use Open-Meteo's historical forecast API.
  - Interpolate to the plume height, then compare with the measured drift bearing (agreement in degrees). Done as the mean wind between the vent and the plume top, which matches the drift side far better than the wind at the top alone.
- [x] **`vigil/agent/tools.py`:** (`track_window` takes a target and uses the tuned phrases; `get_wind` takes `altitude_m` and an optional drift side; `get_history` also takes a target)
  - Strict JSON-schema tools: `list_cameras_status`, `get_recent_frames(camera, hours)`, `assess_frame(frame_id)`, `segment_frame(frame_id, phrase)`, `track_window(camera, start, end, phrase)`, `measure_track(track_id)`, `get_wind(volcano, height_m, time)`, `compare_cameras(volcano, time)`, `get_history(camera, metric, hours)`.
  - Validate tool arguments; the API does not guarantee them.
- [x] **`vigil/agent/loop.py`:**
  - Responses API loop with `previous_response_id`, resending tools and instructions on every turn, and parallel tool calls. (Since Phase 5 every turn resends the whole conversation with `store: false` instead.)
  - Max-turn and budget guards.
  - Persist the trace in `agent_runs` and `agent_steps`; it will be shown in the dashboard.

**Acceptance:** replayed at 05:00 HST on Oct 17, the agent picks KPcam, measures the plume, checks it against the wind (SW drift) and leaves a full trace.

## Phase 5: Sat Oct 31. Bulletins and replay

- [x] **`vigil/agent/bulletin.py`:** (the model writes the level, the texts, the measurements with camera and target, and the evidence frame ids; the code adds the official source, the disclaimer, the wind check and the overlays, and checks every number; rendering in `vigil/agent/render.py`)
  - Strict schema: descriptive activity level (never an official alert level), headline and body in ES and EN, `measurements[{metric, value, sigma, unit, frame_ids}]`, `evidence[{frame_id, overlay}]`, official source (agency and URL), disclaimer.
  - Render to HTML and Markdown.
- [x] **`vigil/replay.py` and the `vigil-replay --episode 55 --speed 60` CLI:** (the runner is `vigil/pipeline.py`, with `vigil-pipeline` for live mode; the replay has its own database and resumes after an interruption)
  - Feed the AshCam episode-55 frames through the same pipeline on a simulated clock: quality, tracking, metrics, and the agent every N minutes.
  - Write a timeline JSON.
  - The pipeline runner also serves live mode:
    - it runs `QualityGate.assess_range(spark="uncertain")` on new frames;
    - it tracks one SAM window per camera per hour (the Phase 2 cost rule), off the request path, because mask decoding takes minutes.
- [x] **Muse Spark video understanding:** send the episode timelapse and ask for the phases (onset, peak, decline, end). Cross-check with the SAM-derived times. (`vigil/phases.py`)

**Acceptance:** the replay produces six or more bulletins across the episode, plus the comparison table against USGS. Done: 7 bulletins, every number verified, the comparison tables in [replay_ep55.md](research/replay_ep55.md).

## Phase 6: Sun Nov 1. Dashboard

- [x] **`vigil/web/app.py`** (FastAPI): `/api/cameras`, `/api/frames/latest`, `/api/series`, `/api/bulletins`, `/api/replay`, `/api/agent/trace`. (Also:
  - `/api/config`;
  - `/api/frames`, the per-camera frame strip;
  - `/api/frames/{id}` and `/api/frames/{id}/image`, a scaled JPEG with its masks;
  - `/media/`, bulletin images only.

  Every endpoint takes `replay` and `at`, and its queries live in `vigil/web/views.py`, a `Scene` = one database at one clock. CLI: `vigil-web`.)
- [x] **`vigil/web/static/`:** (plain ES modules, no build step; dark "observatory night shift" design; plan [2026-10-30-phase-6-dashboard.md](superpowers/plans/2026-10-30-phase-6-dashboard.md))
  - Leaflet map: cameras, vent, drift arrow, wind arrow. (USGS imagery tiles. Each camera's position is drawn as a circle of its σ, with its line of sight to the vent; the drift is drawn across KPcam's line of sight, and the wind is the newest bulletin's layer mean.)
  - Current frame with mask overlay. (Last tracked frame or latest frame, plus the hero readout of the plume top ± σ.)
  - Height chart over time. (A helicorder "drum" that inks only up to the clock; HVO's values appear once their window has closed, with per-camera frame strips.)
  - Bulletin feed with an ES/EN toggle.
  - Camera status (fresh / stale / fog / night). (Words, not alert colours: usable, night, fog, frozen, stale, unchecked, no frames.)
  - Replay player and agent trace view. (A transport with a scrubber on the 5-min grid, 2.5–10 simulated min/s, and the step summary. At the episode's end, the comparison tables against HVO.)
  - The disclaimer banner is always visible. (It is in the page's markup and sticky with the top bar.)

**Acceptance:** the local dashboard shows both live and replay. Done: replay checked at 03:05, 05:00, 06:10 and 09:30 HST, and live (3-day-old data shows as stale, with dated times), in headless Edge screenshots at 1440 and 500 px.

## Phase 7: Sat Oct 31. Deployment

- [ ] **Hugging Face Spaces (Docker):**
  - `Dockerfile` from `python:3.12-slim` with ffmpeg.
  - The ingest worker runs in-process with the web app.
  - Secrets are Space secrets. Set `DAILY_BUDGET_USD=3`.
- [ ] **Episode 55 data that does not depend on AshCam (required):**
  - Mirror the episode-55 frames (public domain) to a public HF dataset, and on startup load the replay from that mirror.
  - Why it is required:
    - AshCam's API is undocumented and can change without notice.
    - Its Oct 17 frames expire around Nov 17.
    - A Space without paid persistent storage loses its disk on every restart (confirm this here).
  - On startup, backfill only the last days of live history from AshCam.
  - Images never go into the git repo.

**Acceptance:** a public URL is live, with ingest running and the replay working.

## Phase 8: Sun Nov 1 – Mon Nov 2. Episode alerts

Bulletins come once an hour, so the episode 55 replay first reported fountaining at 04:00 HST, 41 min after the 03:19 onset, and stopped reporting it 27 min after the 09:03 end ([replay_ep55.md](research/replay_ep55.md)). SAM already sees the fountain on V1cam at 03:25 ([tracking_ep55.md](research/tracking_ep55.md)), and HVO's public onset notice came at 03:43 ([episode55.md](research/episode55.md)).

- [ ] **Onset and end detection:**
  - Every new frame goes through the local checks. A change near the vent triggers a SAM confirmation on that frame, and Muse Spark is asked only when SAM leaves it ambiguous.
  - One state per volcano (quiet → fountaining → ended), with the frame that shows each change.
  - It must tell a fountain from the overflows that came before episode 55 (south and west vents).
- [ ] **False-alarm test set:** backfill the Oct 16–17 overflow frames from AshCam (they expire around Nov 16). No alert may fire on them, nor on the episode 55 frames before 03:19 HST.
- [ ] **The alert:** ES and EN text, the frame with its mask, the detection time, the disclaimer and the link to HVO.
  - It is stored in the database and shown as a banner on the dashboard, live and in replay, bounded by the clock.
  - It is sent to a public Telegram channel.
- [ ] **Telegram bot and channel**, set up together in the Phase 8 session:
  - Claude guides the BotFather steps, which need the user's own Telegram account, and the creation of the public channel with the bot as its admin.
  - The user puts the token into `.env` and the Space secrets.
  - A check confirms the token and finds the channel's chat id without printing the token.
- [ ] **Replay:** the episode 55 replay emits the alerts at their simulated times, and its report compares them with the onset (03:19), HVO's onset notice (03:43) and the end (09:03).
- [ ] Deploy the alerts to the Space before Nov 2, when the episode 56 window opens.

**Acceptance:** on the episode 55 replay, the onset alert fires between 03:19 and 03:43 HST, and the end alert after 09:03 with a latency the phase plan sets from the stored frames. No alert fires on the overflow frames. A test alert arrives on the Telegram channel.

## Phase 9: Tue Nov 3. Validation report, README, polish

- [ ] **Calibrate a fountain camera** so the validation's fountain rows get measured. Options:
  - K2cam needs a vertical reference: a clear sea horizon on a frame with the episode 55 framing, or a post-2018 DEM of the crater rim.
  - V1cam: the Moon for its view, plus a resection on the vent for its ±150 m position.
- [ ] Name the Spanish vocabulary in the bulletin prompt ("columna", "boca", "fuente de lava"). In the replay Muse Spark wrote "pluma" and "ventín" ([replay_ep55.md](research/replay_ep55.md)).
- [ ] Final `docs/VALIDATION.md`: errors, σ, limitations.
- [ ] Final README: updated diagram, live URL, how to run, the "Built during the hackathon" section, disclaimer, credits, cost report.
- [ ] Code review pass (`superpowers:requesting-code-review`) and fixes.

## Phase 10: Wed Nov 4. Video and submission (afternoon, not last minute)

- [ ] **3-minute video:**
  1. The problem: observatory webcams publish a frame every few minutes, and nobody can watch them all day.
  2. Live dashboard: camera status and the quality gate at work.
  3. Episode-55 replay: the onset alert arriving on Telegram, SAM tracking overlay, agent trace, bilingual bulletins.
  4. Validation numbers against USGS.
  5. The disclaimer.
- [ ] Make the repository public and submit before 21:00 ET (23:00 Argentina).

## Extras (only if time remains)

None left: the Telegram notifications became part of Phase 8.

## Budget

Spent so far: $3.19 (smoke test $0.05, SAM prompt tuning $0.15, Phase 2 quality gate $0.33 and episode 55 tracking $0.28; Phase 3 made no Meta API call; Phase 4 $0.10: tool-calling probes $0.01, two agent replays $0.09; Phase 5 $2.28: probes $0.15, a smoke bulletin $0.05, replay run 1 $1.05 and run 2 $1.03, each in its own database's ledger; Phase 6 made no Meta API call). Estimate: about $3–5/day with the live agent, about $40 in total out of the $150 credit. `DAILY_BUDGET_USD` caps every day.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| SAM prompts for gas plumes are ambiguous | Phase 1 tuning; let Muse Spark suggest phrases |
| Camera positions and fields of view unpublished | `calibration.yaml` + reference points; validate on B1 and F1/KW, whose positions are published |
| PTZ cameras change framing | Read P/T/Z from the frame and calibrate per preset; skip unknown presets |
| AshCam keeps about 31 days, and its API is undocumented | Live: automatic fallback to `M.jpg` per camera (done in Phase 1). Replay: local copies plus the required HF dataset mirror, loaded at startup (Phase 7) |
| Volcano quiet during judging | The replay is the centerpiece; live mode shows the quality gate and camera status |
| Episode 56 (HVO forecast of Oct 30: Nov 2–9) erupts during the hackathon or the judging | Keep `vigil-ingest` running locally from Oct 31. On restart it catches up gaps of up to 1 h by itself; `vigil-backfill` fills longer ones while AshCam keeps them (about 31 days). Phase 8's alerts run on the Space before Nov 2 |
| The overflows before an episode glow like a fountain and fire a false onset alert | Phase 8's test set of Oct 16–17 overflow frames: no alert may fire on them |
| Session quota runs out mid-task | This file plus the memory notes; commit often |
