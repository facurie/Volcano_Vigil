# SAM 3.1 prompt tuning on episode 55 frames

Run on 2026-10-27 with `scripts/tune_prompts.py`, which applies every candidate phrase for a target to each frame where that target is visible. The chosen phrases are in [`config/prompts.yaml`](../../config/prompts.yaml), which `vigil/prompts.py` reads.

## Method

**Frames.** All frames are USGS public domain. AshCam frames are 3840×2160 (KP, K2) or 1920×1080 (V1) and were sent at most 2048 px on the long side, as the pipeline does.

| frame | camera, time (HST) | why | file under `data/raw/usgs_ep55/` |
|---|---|---|---|
| `kp_0450_night` | KPcam, 04:50:01 | Peak (official plume 25,000 ft a.s.l.); the column is lit only by the fountain; ~14 km away | `ashcam/kilauea-kp-cam/kilauea-kp-cam-1792248605.jpg` |
| `kp_0602_dawn` | KPcam, 06:00 | Dawn; official plume 17,000 ft a.s.l. at 06:02 | `ashcam/kilauea-kp-cam/kilauea-kp-cam-1792252808.jpg` |
| `k2_0500_night` | K2cam, 05:00:02 | Peak; incandescent fountain at night, ~1.7 km | `ashcam/kilauea-k2-cam/kilauea-k2-cam-1792249204.jpg` |
| `k2_0700_day` | K2cam, 07:00 | Daylight fountain (official 500 ft) under a large white column | `ashcam/kilauea-k2-cam/kilauea-k2-cam-1792256403.jpg` |
| `v1_0659_day` | V1cam, 06:59:01 | Daylight close-up; the smoke-test frame | `ashcam/kilauea-v1-cam/kilauea-v1-cam-1792256342.jpg` |
| `v1_0459_night` | V1cam, 04:59:01 | Night close-up with glowing flows over the whole crater floor (follow-up run) | `ashcam/kilauea-v1-cam/kilauea-v1-cam-1792249142.jpg` |
| `f1_0601_thermal` | F1cam (thermal), 06:01:25 | Thermal view; the fountain sits at the right edge | `20261017060125M_F1.jpg` |

**Candidates.**
- Plume:
  - `steam` won the smoke test.
  - `volcanic plume` was the smoke-test baseline that returned the fountain.
  - New candidates: `steam plume`, `white plume`, `eruption column`, `gas plume`, `volcanic gas plume`, `ash cloud`.
  - `volcanic eruption plume` was suggested by Muse Spark in the smoke test.
- Fountain: `lava fountain`, `fountain of lava`, `glowing lava`.
- Incandescence: `incandescent lava`, `glow`.

**Runs.** Overlays, one contact sheet per frame, `results.json` and `summary.md` are in these runs:
- `data/tuning/20261027T171313Z`: 57 calls, the six original frames.
- `data/tuning/20261027T172002Z`: 3 calls, the fountain follow-up on `v1_0459_night`.
- `data/tuning/20261027T171058Z`: 1 call, aborted. It exposed that SAM sends large masks at reduced resolution; `vigil/meta/sam.py` now scales them to their box, see [META_API_NOTES §4](../META_API_NOTES.md).

**Cost.** 61 SAM image calls, **$0.1525**.

**Verdicts.** Each one comes from the overlays and the object boxes in `results.json`:
- **✓** the intended target: for a plume, the gas or ash column above the vent including its top; for a fountain, the lava jet; for incandescence, the glowing lava.
- **~** the target plus something else, or only part of it.
- **✗** the wrong object.
- **–** nothing found.

Numbers are SAM confidences.

## Results

### Plume (visible cameras)

| phrase | KP 04:50 night | KP 06:02 dawn | K2 07:00 day | V1 06:59 day |
|---|---|---|---|---|
| **steam** | **✓ 0.63** | **✓ 0.66** | **✓ 0.80** | **✓ 0.75** |
| volcanic plume | – | ✓ 0.65 | ✗ column 0.54 + fountain 0.79 | ✗ fountain 0.88 |
| steam plume | – | – | ✓ 0.57 | ✓ 0.52 |
| white plume | – | – | – | – |
| eruption column | – | – | ✗ fountain 0.53 | ✗ fountain 0.70 |
| gas plume | – | – | ✓ 0.68 | ✗ column 0.55 + fountain 0.52 |
| volcanic gas plume | ~ 0.56, column reaching into the fountain glow | ✓ 0.68 | ✗ column 0.66 + fountain 0.73 | ✗ fountain 0.86 |
| ash cloud | ~ column 0.62 + a low glowing band left of the vent 0.51 | ✓ 0.71 | – | ✓ 0.59 |
| volcanic eruption plume | – | ✓ 0.72 | ✗ column 0.71 + fountain 0.71 | ✗ fountain 0.85 |

How high the `steam` mask starts, as a share of the frame height from the top:
- KP 04:50: 7.1 %. KP 06:02: 27.0 %. KP sees the column top.
- K2 07:00 and V1 06:59: 0 %. The column leaves the frame, so those cameras cannot give the plume top.

### Fountain (visible cameras)

| phrase | KP 04:50 night (14 km) | K2 05:00 night | K2 07:00 day | V1 06:59 day | V1 04:59 night, glowing flows |
|---|---|---|---|---|---|
| **lava fountain** | – | **✓ 0.89** | **✓ 0.84** | **✓ 0.89** | **✓ 0.91** |
| fountain of lava | – | – | ✓ 0.62 | – | – |
| glowing lava | ~ 0.62, the glow halo, not a jet | ✓ 0.85 | ✓ 0.86 | ✓ 0.88 | ✓ 0.85 |

On `v1_0459_night` both phrases returned only the jet (the same box, 7.9 % of the frame), not the glowing flows around it.

### Incandescence, and the thermal camera

| phrase | KP 04:50 night | K2 05:00 night | F1 06:01 thermal |
|---|---|---|---|
| incandescent lava | – | – | – |
| **glow** | **✓ 0.70** (glow halo) | **✓ 0.70** (fountain) | – |
| glowing lava (run as a fountain candidate) | ✓ 0.62 | ✓ 0.85 | **✓ 0.71**, the whole hot lava field (32 % of the frame) |
| lava fountain (run as a fountain candidate) | – | ✓ 0.89 | ~ 0.62, the whole hot lava field, not the fountain |

On F1 no phrase isolates the fountain. `fountain of lava` found nothing there.

## Choice

The plan's rule:
1. Rank phrases by the number of ✓, then by their lowest ✓ score.
2. Add a second phrase only if it gets ✓ where the first does not.
3. Never choose a phrase that returns the fountain for the plume, or the reverse.

| target | visible | thermal |
|---|---|---|
| plume | `steam` | none |
| fountain | `lava fountain` | none |
| incandescence | `glow` | `glowing lava` |

- **Plume:**
  - `steam` is the only phrase with ✓ on all four frames, from 14 km at night to about 1 km in daylight, and it never returns the fountain.
  - Every phrase with "volcanic" in it, and `eruption column`, returns the fountain on the close cameras (rule 3). This confirms the smoke-test finding.
- **Fountain:**
  - `lava fountain` and `glowing lava` tie on the four frames where the jet is resolvable. The rule's tie-break gives `glowing lava` by 0.01 (lowest scores 0.85 vs 0.84), which is below SAM's run-to-run variation.
  - We chose `lava fountain` for two reasons. In the smoke test its video track ended when the fountain ended, and Phase 2 needs exactly that to time the end of an episode. It also names the jet, while "glowing lava" names a property that flows and the vent share.
  - KPcam is not a fountain camera: at 14 km only the glow halo shows.
- **Fountain on thermal:** none. Every phrase that answered took the whole lava field.
- **Incandescence:**
  - Visible: `glow` (✓ on both night frames, ahead of `glowing lava` on its lowest score).
  - Thermal: `glowing lava`, whose mask is the hot lava field. That mask is what F1 is for (lava coverage, fountaining on/off). The evidence comes from the call made under the fountain list, which is the same SAM request.
- **Plume on thermal:** not tested. The gas column is faint in F1 frames.

## Caveats for the next phases

- **Small sample.** There is one frame per condition, and SAM results vary slightly between runs. Re-check the phrases on the timelapse tracks in Phase 2.
- **Masks include the drifting cloud.** On KP the `steam` mask also covers the cloud drifting downwind. Phase 3 should measure the top of the column above the vent, not the far end of the cloud.
- **Look-alikes in live frames.** `steam` may also match meteorological cloud or vog. Keep only masks attached to the vent column (box bottom near the vent).
- **Night plumes.** At night the plume is visible only while the fountain lights it, so a low fountain means no night plume.
- **Edge accuracy.** Large masks arrive at reduced resolution (long side 1024 px). On a 2048 px KP frame the plume edge is good to about 2 px. Count this in the height σ in Phase 3.
