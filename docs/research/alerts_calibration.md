# Fountaining alerts: calibration

Measured on 2026-11-01 while planning Phase 8 ([plan](../superpowers/plans/2026-11-01-phase-8-alerts.md)). The goal is an alert within minutes of a lava fountain starting or stopping at Kīlauea's summit, silent through the 29 h of overflows before episode 55.

Raw results (git-ignored): `data/calibration/alerts/` (`probe_*.jsonl`, `local_stats.csv`, the probe scripts `sam_probe.py`, `spark_probe.py`, `local_stats.py`, and the contact sheets `v1_onset.jpg`, `v1_overflow_peaks.jpg`). Times are HST (UTC−10) unless a `Z` says otherwise.

## 1. Frames

Backfilled from AshCam (free) for Oct 16 08:00Z – Oct 17 12:59Z:

| Camera | Frames |
|---|---|
| V1 | 863 |
| K2 | 863 |
| KP | 345 |
| F1 | 116 |

With episode 55 (13:00–19:30Z), the database holds 35.5 h of V1 and K2 at 2-min cadence. AshCam drops these frames around Nov 16.

**V1cam's framing:**
- P 8778 / 8.9× until about 21:00 HST Oct 16, then P 9321 / 9.4× until 03:47 HST Oct 17.
- Episode 55 then switches to 1.4× at 03:49 and 1.0× at 04:43.
- Live on 2026-11-01 08:09 HST: P 9594 / 9.6×, the cone close up, the same kind of view.

**What HVO says happened** ([`episode55.md`](episode55.md) §3, from the Daily Update of Oct 17 and the VAN/VONA notices):
- South-vent overflows are continuous from 05:56 HST Oct 16, and end at 03:55 on Oct 17.
- The north vent overflows intermittently from 18:11 and continuously from 23:35.
- The west vent overflows from 22:49 and continuously from 02:23; it is drowned by the north vent at 04:13. The south and west vents had small dome fountains that fed flows, but never fountained during the episode.
- Onset 03:19, by rising tremor (from 02:45), rapid deflation and the north-vent fountain doubling while still under 100 ft (30 m). The VONA notice came at 03:43 (fountain 100–150 ft).
- End 09:03, abrupt; the VONA notice came at 09:11.

## 2. Local signals

V1's whole-frame glow fraction (`vigil.quality`):

| Period | Glow fraction |
|---|---|
| Overflow nights | median 0.026, p95 0.26, max 0.59 |
| Onset hour | median 0.29, max 0.52 |
| Quiet days | median 0.0003, p95 0.0067 |
| After the end (09:03, daylight) | 0.03–0.05 (the flows are still hot) |

It rises steadily from 0.075 at 02:49 to 0.30 at 03:19, with no step at the onset. The local check therefore cannot tell overflows from the episode; it is only a gate ("is lava visible?", "is the view clear?").

## 3. SAM 3.1 `lava fountain`, image mode

Area is the mask's share of the frame.

| Set | Frames | With a fountain | Area | Score |
|---|---|---|---|---|
| V1 overflow night Oct 16 (8.9×), every 12 min | 40 | 0 | | |
| V1 overflow night Oct 17, 21:00–03:00 (9.4×), every 4 min | 90 | 50 | 0.0021–0.0329 | 0.50–0.77 |
| K2 overflow night Oct 17, 18:00–03:00, every 16 min | 34 | 0 | | |
| V1 episode 55, 03:01–04:49, every frame | 55 | 51 | 0.0155–0.7374 | 0.51–0.91 |
| K2 episode 55, 03:02–04:50, every 4 min | 28 | 9 (from 04:10, steady from 04:22) | 0.0039–0.0228 | 0.50–0.87 |
| V1 end, 08:47–09:29 | 22 | 8 (last at 09:01:05) | 0.009–0.020 | 0.81–0.90 |
| K2 end, 08:46–09:28 | 22 | 9 (last at 09:02:01) | 0.0007–0.004 | 0.66–0.87 |

Scores do not separate overflow domes from the fountain; area does. Every overflow sighting on V1 covers ≤ 0.033 of the frame.

**V1 onset, minute by minute.** From 03:03 the episode's fountain covers 0.137 or more until the zoom-out at 03:49:

| HST | Area |
|---|---|
| 03:03 | 0.23 |
| 03:05 | 0.44 |
| 03:07–03:15 | 0.14–0.18 |
| 03:17–03:45 | 0.20–0.40 |
| 03:47 | 0.74 |

The boxes at 03:03 and 03:05 take in the flows below the fountain. Isolated misses during the episode: 03:01 (before the fountain), 03:11, 03:29 and 04:11.

**Thresholds:**

| Camera | `fountain_area` | `ambiguous_area` | Margins |
|---|---|---|---|
| V1 | 0.06 | 0.03 | ×1.8 above the largest overflow (0.033), ×2.3 below the smallest episode sighting (0.137) |
| K2 | 0.01 | 0.005 | K2 had no overflow sighting; its episode fountain covers 0.016–0.023 from 04:22 |

**The end is crisp:** V1 sees nothing on the 14 frames from 09:03:02, and K2 sees nothing on the 13 frames from 09:04:02.

**Latency:** a SAM image call takes 1.5 s median (6.9 s with V1's big episode masks, parsing included).

## 4. Muse Spark on frame pairs

V1, 1280 px images, 30 min apart, $0.0058 and about 6 s per call.

| Pair (HST) | What it is | `looks_like` | `larger_than_before` |
|---|---|---|---|
| 22:19 → 22:49 | overflows | `overflow_or_dome` | false |
| 00:41 → 01:11 | overflows | `overflow_or_dome` | false |
| 02:37 → 03:07 | episode onset | `sustained_fountain` | true |
| 02:55 → 03:25 | episode onset | `sustained_fountain` | true |

The prompt (`COMPARE_PROMPT` in `vigil/alerts.py`; `{minutes}` is the gap between the frames):

> These two frames come from the same USGS webcam at the summit of Kilauea, {minutes} minutes apart: the first is the earlier one, the second is now. Between eruptive episodes, lava overflows the vents and can form low dome fountains and lava cascades a few metres high. An episode begins when a lava fountain at a vent becomes sustained and grows much taller and wider than those overflows. Report only what you can see. Is there a lava fountain in the second frame, and is it clearly taller and wider than anything in the first frame?

## 5. What the rule does

Simulated on these results: looks every 8 min while lava is visible, the next frame looked at right after an episode-size sighting, Muse Spark confirms.

- **Onset:** raised between 03:06 and 03:22, depending on where the 8-min cadence falls; all inside [03:03, 03:43].
- **End:** looks every 6 min while fountaining, plus a re-look on the next frame after a miss. The alert comes between 09:07 and 09:11.

**The acceptance follows the visible fountain, not HVO's 03:19 onset** (the user chose "Visible fountaining", 2026-11-01). On V1cam, a fountain far larger than anything in the overflow frames appears at 03:03. HVO's onset is defined by tremor, tilt and the doubling of that same north-vent fountain. So:
- the onset alert fires between 03:03 (the first frame that shows the fountain) and 03:43 (HVO's notice);
- zero alerts fire on the 29 h of overflow frames;
- the end alert fires between 09:03 and 09:15 (HVO's end notice came at 09:11).

The text says "lava fountaining seen", never "episode declared", and names HVO as the one that declares episodes.

Muse Spark confirms **every** onset before it goes public, not only borderline sizes: the size thresholds are shares of the frame, so they belong to one PTZ framing, and zoomed in further than V1's 9.4–9.6× an overflow dome could pass the threshold. Muse Spark told domes from the fountain on 4 of 4 pairs, for about $0.006 per onset.

## 6. Cost

- **Calibration probes:** $0.7505 (291 SAM images and 4 Muse Spark calls, tag `probe:alerts` in the local ledger), inside the $1.00 the user approved.
- **Live:** about 180 looks on a day of overflows (V1 every 8 min through the night, heartbeats every 30 min by day, K2 mostly heartbeats), so about $0.45. An eruption day adds about 120 looks at 6 min, so about $0.75. That fits the $0.75/day reserve inside the $5 cap.
- **Replays:** overflows about 260 looks plus a few Muse Spark calls, about $0.70; episode 55 about 140 looks, about $0.36.

## 7. Limits

- One night of overflows and one episode, with the thresholds set on the same frames the replays run on. Episode 56 is the first out-of-sample test.
- The thresholds are shares of the frame, so they belong to a framing; that is why Muse Spark confirms every onset.
- K2 alone would alert about 67 min late at night (it sees the fountain from 04:10, steady from 04:22).
- A camera that is blind and one turned away can end an episode early (see Task 7 of the plan).
