# The agent replayed at 05:00 HST on episode 55

Phase 4 acceptance, run on 2026-10-28:

> Replayed at 05:00 HST on Oct 17, the agent picks KPcam, measures the plume, checks it against the wind (SW drift) and leaves a full trace.

```
vigil-agent --volcano kilauea --at 2026-10-17T05:00-10:00
```

- **Clock:** 2026-10-17T15:00:00Z.
- **Model:** `muse-spark-1.3`, reasoning effort medium.
- **Budget:** 12 turns and $0.30 per run.
- **Task:** the default one: "Check Kīlauea now: which cameras show activity? Measure the plume and any lava fountain you can, compare the plume's drift with the forecast wind, and report."
- **Trace:** in the `agent_runs` and `agent_steps` tables of `data/vigil.sqlite`. Run 2 is the clean run (below); run 1 found a bug.

## Run 2: done in 5 turns, $0.0302, 66 s

| Turn | What Muse Spark did | What came back |
|---|---|---|
| 1 | `list_cameras_status` | V1, K2 and KP were usable at 14:55–14:59Z. F1 had no frames. Only KPcam was calibrated. |
| 2 | In parallel: `track_window` (KPcam plume, 14:00–15:00Z), `compare_cameras` (15:00Z) and `get_recent_frames` (KPcam, 2 h) | The stored run covered the window (`cached: true`, no SAM call). Plume track 6 had 12 detections, the last at 14:55:05Z. |
| 3 | In parallel: `measure_track` (track 6), `track_window` (KPcam and K2cam fountain), and `assess_frame` on the latest V1, K2 and KP frames | top_altitude 6,951 ± 429 m at 14:55:05Z (frame 29); drift side 224° on all 21 frames so far. The verdicts came from the database, since run 1 had stored them. |
| 4 | `get_wind`: altitude 6,951 m, drift side 224.4° | Layer-mean wind from the vent at 1,080 m to the top: from 331°, blowing towards 151°, at 3.3 m/s. Angle to the measured side: 73.3°, **consistent**. |
| 5 | Final report, no tool call | (excerpt below) |

The run passes the acceptance test:
- It picked KPcam, the only calibrated camera, for heights.
- It measured the plume as 6,951 ± 429 m above sea level and 5,871 ± 429 m above the vent, at 14:55:05Z.
- It checked the drift against the wind. The plume sits on KPcam's south-west side (224°), and the mean wind under the plume top pushes it to that side.
- Nothing captured after the clock appears: the latest frames are V1 14:59:02Z, K2 14:58:02Z and KP 14:55:05Z. The KPcam frame of 15:00:05Z stayed invisible.
- Every turn and tool call is stored with its arguments, result, cost and latency.

From the final report:

> Lava fountain height: could not measure. kilauea-kp fountain track_window 14:00-15:00Z returned 0 tracks [...]. kilauea-k2 has fountain track 2 (phrase `lava fountain`, 16 detections, 2026-10-17T14:28:02Z to 2026-10-17T14:58:02Z) and kilauea-v1 shows fountain, but both cameras are not calibrated, so measure_track cannot give metres.
>
> drift check for measured side 224.4 deg vs layer toward 151 deg: angle 73.3 deg, consistent = true. [...] Single camera: drift_bearing is only side of line of sight, cannot see drift along line of sight.

The report quotes only tool numbers, each with its sigma, unit, capture time and frame id. It says no alert is issued and names HVO as the official source.

## Run 1: $0.0569, and the bug it found

Run 1 also passed: 5 turns, the same plume measurement and the same wind check. It showed two things:

- **K2cam was listed as calibrated.** `config/calibration.yaml` has a K2cam preset, `ep55`, which records the image size but has no references. So `measure_track` failed on K2's tracks with "0 landmark(s) ... cannot fix a view", and the report called K2cam "calibrated but currently unmeasurable".
  - Fix (`c888d45`): a camera counts as calibrated only when a preset covers the time **and** a two-sample solve of its view succeeds (0.05 s for three cameras).
- **Muse Spark spent most of the money on looking.** It called `assess_frame` on the latest V1, K2 and KP frames, at $0.025 for the three, and used the descriptions in its report ("night_with_glow", "lava_fountaining").
  - Those verdicts are stored, so run 2 got them for free.
  - A live agent that looks at fresh frames will pay about $0.008 per frame.

## Cost per run

| Run | Turns | Spark turns | Tools' Meta calls | Total | Input / output tokens (turns) |
|---|---|---|---|---|---|
| 1 | 5 | $0.0321 | $0.0248 (3 × `assess_frame`) | $0.0569 | 24,502 / 3,422 |
| 2 | 5 | $0.0302 | $0 | $0.0302 | 27,477 / 3,940 |

No turn reported cached input tokens. A run every hour of the day would cost about $0.75–1.40, inside the $3/day cap planned for the Space.

## Tool calling against the Meta API

Two live probes while planning ($0.0082 in total) and the two runs showed:

- **Schemas.** Strict function tools are accepted with a nullable argument typed `["string", "null"]`, an `enum`, or an empty `properties` object.
- **Arguments are not guaranteed.** In the probe Muse Spark sent `"time": "null"`, the string, for a nullable argument. `Toolbox.call` reads `"null"`, `"None"` and `""` as null on nullable arguments, then validates every call with Pydantic. A bad call goes back to the model as an error message.
- **Parallel calls.** Muse Spark makes them without being asked: up to 6 calls in one turn, 3 to 6 whenever the calls didn't depend on each other. They run one after another.
- **Commentary.** It writes a sentence before each batch of calls ("Found plume and fountain tracks. Now measuring their heights and positions."). The trace stores it next to the reasoning summaries (`reasoning.summary: auto`).
- **Chaining.** `previous_response_id` with `function_call_output` items works when the tools, instructions and reasoning are re-sent every turn.
- **Wrap-up.** A user message after the tool outputs ("No turns left: write your final report now...") makes Muse Spark answer without tools. The loop sends it on the last allowed turn.
- **Tools and structured output together.** A request with both `tools` and `text.format` (a strict JSON schema) worked, which Phase 5's bulletin schema can use.

## The wind check

`vigil/wind.py` uses Open-Meteo's Historical Forecast API for hours more than two days old. For the hour 2026-10-17 15:00Z it returned levels from 850 to 300 hPa, from a model cell 4 km north-east of the vent.

The drift is compared with the **mean wind between the vent and the plume top**, not with the wind at the top. Over the 75 KPcam plume frames of the episode ([VALIDATION.md](../VALIDATION.md)):

- the layer-mean wind blows to the side the plume was seen on in **74 of 75** frames (median angle 39°, range 22–104°);
- the wind at the top alone does so in 58 of 75. At the peak it blows towards 80°, almost opposite the side measured.

The model has the low-level wind from the north to north-northwest. HVO reported it from the northeast, so an agreement of a few tens of degrees is the expected level.

## Limits and next steps

- Fountain heights wait for a calibrated close camera (PLAN Phase 9: K2cam needs a vertical reference; V1cam needs the Moon plus a resection on the vent).
- With one camera, drift is a side of the line of sight, not a direction. `compare_cameras` will cross-check heights once a second camera is calibrated.
- A tool's model hour is the hour nearest the clock, which can be up to 30 minutes after it. The profile is a model forecast, not an observation, so the replay can use it.
