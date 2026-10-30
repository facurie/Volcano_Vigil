# Replaying episode 55: seven bilingual bulletins on a simulated clock

Phase 5 acceptance, run on 2026-10-30:

> The replay produces six or more bulletins across the episode, plus the comparison table against USGS.

```
vigil-replay --episode 55
```

**Where the output is:**
- The replay's own database is `data/replay/ep55/vigil.sqlite`, with `timeline.json` and `report.md` next to it.
- Each bulletin is in `data/replay/ep55/bulletins/run<N>/`: one HTML page, Markdown in each language, and its evidence overlays.

**The run:**
- **Clock:** 78 steps of 5 simulated minutes, from 13:00 to 19:30Z (03:00–09:30 HST).
- **Bulletins:** one at every full hour, and one more at the end.
- **Time and cost:** 64 minutes of wall time, $1.03.

## What a step does

At each step the replay:
1. **Copies the frames.** It copies into its database, with their ids, the KPcam, K2cam and V1cam frames captured by the simulated clock. Nothing captured later exists for any part of the step. The tests pin this.
2. **Runs the quality gate.** All 468 frames pass the local checks, so Muse Spark is never asked.
3. **Tracks each closed hour.** It tracks every camera's closed hour with SAM 3.1 video (`steam`, `lava fountain`, `glow`). Each window is led in by earlier usable frames up to the 50 frames SAM bills anyway (see run 1 below). Then it measures the new KPcam detections, KPcam being the calibrated camera.
4. **Writes a bulletin** at each full hour, and once more at the end: the agent runs at the simulated time and writes a bulletin in the strict JSON format. The code then:
   - checks every number against the stored measurements;
   - adds the official source and the disclaimer;
   - takes the wind check from the run's own `get_wind` call;
   - draws the evidence frames with their masks.

## The bulletins

| HST | Activity | Headline | Titular | Numbers checked |
|---|---|---|---|---|
| 04:00 | fountaining | Lava fountaining at the summit with a 1.6-km-high plume drifting with the wind. | Fuente de lava en la cumbre con una pluma de 1,6 km de altura a favor del viento. | yes |
| 05:00 | fountaining | Lava fountaining continues at the summit with a nearly 5.9-km-high plume drifting with the wind. | Continúan las fuentes de lava en la cumbre con una pluma de casi 5,9 km de altura a favor del viento. | yes |
| 06:00 | fountaining | Lava fountaining continues at the summit with a 4-km-high plume drifting with the wind. | La fuente de lava continúa en la cima con una pluma de 4 km a la deriva con el viento. | yes |
| 07:00 | fountaining | Lava fountaining continues at the summit with a plume about 3.6 km above the vent drifting with the wind. | Continúan las fuentes de lava en la cumbre con una pluma de unos 3,6 km sobre el ventín que deriva con el viento. | yes |
| 08:00 | fountaining | Lava fountaining continues at the summit with a plume about 3.2 km above the vent drifting with the wind. | Continúa la fuente de lava en la cima con una pluma de unos 3,2 km sobre el cráter a favor del viento. | yes |
| 09:00 | fountaining | Lava fountaining continues at the summit with a plume about 3,100 m above the vent drifting with the wind. | Continúa la fuente de lava en la cumbre con un penacho a unos 3.100 m sobre el respiradero, a favor del viento. | yes |
| 09:30 | degassing | Degassing continues with a ~2,370-m plume; no lava fountains visible now. | Continúa la desgasificación con un penacho de ~2.370 m; sin fuentes de lava visibles ahora. | yes |

**What every bulletin has:**
- a body of one paragraph in each language;
- 5 to 7 measurements, each matched to a stored measurement on its frame;
- the layer-mean wind check;
- two or three evidence overlays;
- the disclaimer and the link to HVO.

**What the bulletins got right:**
- **Every quoted number** matched a stored measurement, in all seven bulletins.
- **The 09:30 bulletin** reports that the fountains were last tracked "at about 09:03 local" (HVO: 09:03), and that the faint glow was last seen at 09:10.
- **The 05:00 bulletin** quotes the peak frame (04:55) alongside the latest one.
- **The drift was read correctly.** The bulletins describe `drift_bearing` as the side of the camera's line of sight, and the wind check as consistent in every bulletin: angles from 23° to 74°.

## What the bulletins said against HVO

The first bulletin written once each official window opened, and the value of that target and metric it quoted nearest the window's middle:

| Quantity | Official | Bulletin (HST) | It quoted | Error | Checked |
|---|---|---|---|---|---|
| plume top (peak) | 25,000 ft a.s.l., 04:50–05:10 (7,620 m) | #2 at 05:00 | 6,964 ± 419 m at 04:55 | −656 m (−9 %) | yes |
| plume top | 17,000 ft a.s.l. at 06:02 (5,182 m) | #3 at 06:00 | 5,215 ± 200 m at 05:55 | +33 m (+1 %) | yes |
| plume top | under 13,000 ft a.s.l. by 07:30 (3,962 m) | #5 at 08:00 | 4,286 ± 122 m at 07:55 | +324 m above it | yes |
| fountain height (4 rows) | 720 ft at the peak; 650, 500 and 300 ft later | #2–#5 | not quoted | | |

**Plume top:** the bulletins agree with HVO at the peak (within 2σ) and at 06:02 (1 %).

**The 07:30 bound:** it is exceeded. It is the same case as in [VALIDATION.md](../VALIDATION.md): after 07:00 the top of the `steam` mask is earlier cloud drifting downwind, not the column above the vent.

**Fountain heights:** no fountain height is quoted, because K2cam and V1cam are not calibrated (PLAN Phase 8). Every bulletin says so.

**Activity against the official times:**

| Event | Bulletins (HST) | Official (HST) | Difference |
|---|---|---|---|
| fountaining first reported | 04:00 | 03:19 | +41 min |
| fountaining no longer reported | 09:30 | 09:03 | +27 min |

With hourly bulletins, both are the first bulletin after the event. The replay's frames start at 03:00 HST, and its first bulletin is at 04:00.

## The replay's own measurements against HVO

The replay tracked the episode again in hourly windows and measured it again in its own database. These are the same rows that `scripts/validate_ep55.py` writes:

| Quantity | Official | Replay | Phase 3 validation (one long window) |
|---|---|---|---|
| plume top, peak (max) | 7,620 m | 6,964 ± 419 m at 04:55 (−9 %, z −1.6) | 6,951 ± 429 m (−9 %) |
| plume top, 06:02 (mean) | 5,182 m | 5,169 ± 210 m (−0 %, z −0.1) | 5,169 ± 205 m |
| plume top, 07:30 (mean) | under 3,962 m | 4,419 ± 139 m (+457 m above) | 4,416 ± 137 m |
| end of fountaining | 09:03 | K2cam 09:02:01 (−1.0 min), V1cam 09:03:02 (+0.0 min) | K2cam −1.0 min, V1cam −1.9 min |
| drift | SW | 75 of 75 KPcam frames on the 224° side | 75 of 75 |

The hourly windows reproduce the validation within a few metres. V1cam's last fountain detection moved from 09:01 to 09:03.

## The episode's phases: SAM, Muse Spark and HVO

**Muse Spark's reading:**
- **Input:** the K2cam timelapse (195 frames, 2 fps, 1280×720), uploaded through the Files API and sent as `input_video`.
- **Mapping:** each phase's video second is mapped back to its frame's capture time.
- **Cost:** $0.046, asked once and cached in `spark_phases.json`.

**SAM's reading:** it comes from the fountain tracks: the first and last detection, plus the peak and the start of the decline of the tallest fountain box (a 5-frame running median; the decline starts under 90 % of the peak).

| Phase | HVO (HST) | SAM, K2cam | SAM, any camera | Muse Spark, K2cam timelapse |
|---|---|---|---|---|
| onset | 03:19 | 04:26 (+67 min) | V1cam 03:25 (+6 min) | 04:20 (+61 min) |
| peak | 04:50–05:10 | 04:50 (in the window) | – | 07:00 (+110 min) |
| decline | 05:10–06:02 (650 ft by 06:02) | 05:26 (in the window) | – | 08:56 (+174 min) |
| end | 09:03 | 09:02 (−1 min) | V1cam 09:03 (+0 min) | 09:00 (−3 min) |

The minutes are those outside the official window.

**What the comparison shows:**
- **Onset:** K2cam first sees the fountain at 04:20–04:26, when it rises above the foreground. SAM and Muse Spark agree on that, and V1cam sees the onset 6 minutes after HVO.
- **Muse Spark's peak:** it puts the peak after sunrise in all three readings (07:33 and 06:42 in the planning probes, 07:00 here). The daylight fountain looks bigger, even with the instruction to judge its height against fixed features.
- **SAM's peak and decline:** the box heights put both inside HVO's windows.
- **Muse Spark's printed times:** it reads the time printed on each frame within about 2 minutes of the frame it names.

**Conclusion:** the video reading is a qualitative cross-check, and the SAM-derived times are the measurement.

## Cost and how the agent worked

| Item | Calls | Cost |
|---|---|---|
| SAM 3.1 video tracking: 7 windows × 3 cameras × 3 phrases, 50 frames billed each | 63 | $0.630 |
| Muse Spark agent turns (7 runs, 5–6 turns each) | 36 | $0.292 |
| `assess_frame` calls the agent made | 8 | $0.067 |
| Muse Spark reading the timelapse | 1 | $0.046 |
| **Total** | | **$1.034** |

**How the agent worked:**
- **Cost:** each run took 5–6 turns and $0.036–0.074, in 26–63 s.
- **Calls:** in every run it called, in order:
  1. `list_cameras_status`;
  2. `track_window`, which always found the pipeline's stored runs, so the agent never paid for tracking;
  3. `measure_track`;
  4. `get_wind`, with the plume's top altitude and drift side;
  5. `compare_cameras`.
- **Failed tool calls:** 3 of 77, all measuring uncalibrated cameras. The tool explained why.
- **Muse Spark API failures:** none in this run.

## What replay run 1 found

The first replay ran the same plan, before three fixes. Its database and log are kept in `data/replay/ep55-run1-no-lead-in/`. It was stopped after the 19:00 step, having cost $1.05 and written 4 bulletins.

**1. KPcam's plume vanished from hourly windows after 15:00Z.**

| Hourly window (Z) | 13 | 14 | 15 | 16 | 17 | 18 | 19 |
|---|---|---|---|---|---|---|---|
| Run 1: KPcam `steam` detections | 9 | 11 | 0 | 0 | 9 | 9 | (stopped) |
| Run 2: with lead-in | 9 | 12 | 12 | 12 | 12 | 12 | 6 |

- **The probes:**
  - On its own, the 15:00–15:55 window gave 0 detections, and repeating the request gave 0 again.
  - SAM image mode found the plume on the 15:30 frame (score 0.52).
  - The same hour sent with the hour before it was tracked on 23 of 24 frames.
- **The cause:** SAM video needs to pick an object up where it is clear, and then it carries it. The Phase 2 whole-episode window had always started at night, when the glowing column is clear.
- **Fix (`f6c012b`):** `track_window(lead_in=)` puts the camera's earlier usable frames before the window, up to the 50 billed frames, and stores only the window's detections. For KPcam's 12 frames an hour that is about 3 hours of context, at no extra cost. The pipeline and the agent's `track_window` tool both use it.
- **Effect:** without fresh KPcam data, run 1's 06:00 bulletin quoted the 05:00 plume top, 6,512 m. That is 26 % above HVO's 06:02 value. In run 2 the same bulletin quoted the 05:55 frame (+1 %).

**2. Meta's response store failed.**
- Four of 39 turns failed: three with `503 persistence service error` and one with `400 referenced response not found or expired` on a turn chained with `previous_response_id`.
- Each failure ended an agent run, so two bulletin hours were lost.
- **Fixes:**
  - `9148bb9` sends a turn that got a 5xx again, after 2 s and then 8 s.
  - `9d7009c` makes every turn stateless: `store: false`, and the whole conversation is resent (the user task, each reply's message and function-call items, the tool outputs), with no `previous_response_id`. A live probe confirmed that Meta accepts the resent items. Input tokens are billed the same, because a chained turn's context also counts as input.
- Run 2 had no API failure.

**3. K2cam's preset made noise.**
- K2cam has an `ep55` preset with no references, so the pipeline tried to measure it every hour and logged "cannot fix a view".
- Fix (`f345e51`): the pipeline measures only cameras whose preset fixes a view, using the same test `list_cameras_status` uses.

## Limits

- **No fountain heights.** They need a calibrated close camera (PLAN Phase 8).
- **Hourly bulletins** place the onset and the end only to the hour. A live deployment can run the agent more often, at about $0.04–0.07 per run.
- **The plume top** is the top of the whole `steam` mask. After 07:00 that is cloud downwind, so the 07:30 row exceeds HVO's bound.
- **Muse Spark's Spanish:**
  - It sometimes uses English loans or invents words: "pluma" for plume, "ventín" for vent, and "fountaining" in run 1.
  - The bulletin prompt should name the vocabulary ("columna", "boca", "fuente de lava").
  - Its English is clean.
- **The video reading** of the phases gets the end right and the peak wrong (see above).
- **The replay's spend** goes to its own database's ledger. The daily cap counts each database separately.
