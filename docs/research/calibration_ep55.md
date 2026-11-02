# Camera calibration for episode 55

Done on 2026-10-28 for Phase 3 (KPcam) and 2026-11-02 for Phase 9 (K2cam). It covers how each camera's view was fixed, the evidence, and what is still missing.
- Code: `vigil/geometry.py` and `vigil/calibration.py`.
- Data: `config/calibration.yaml`.
- Tools: `scripts/moon_references.py` and `scripts/check_calibration.py`.

Official eruption values were not used here. They only check the result, in [VALIDATION.md](../VALIDATION.md).

## Camera model

**Pinhole with one radial distortion term.**
- A point at radius r from the image centre (in focal lengths) lands at r(1 + k1 r²).
- The principal point is the image centre.
- The view is the azimuth and tilt of the optical axis, the roll about it, the focal length and k1.

**Lines of sight.**
- Positions become east-north-up offsets from the camera.
- Curvature and refraction lower a point by d²(1 − k)/2R, with k = 0.13. That is 13.3 m over the 13,948 m from KPcam to the vent.

**Heights.** A mask's highest pixel is placed on the vertical plane through the north vent, square to the camera's line of sight. The vent is at 19.40496 N, 155.29022 W, 1,080 ± 5 m.

**Why distortion.** On KPcam's nine Moon positions:
- a plain pinhole misfits by 24 px RMS and puts the vent 117 px above the fountain;
- one k1 term brings the misfit to 1.6 px, and the vent to where the fountain is.

**Monte Carlo.** 1,000 samples; sample 0 is the nominal solution; σ is the standard deviation of the others.

| Input | σ |
|---|---|
| KPcam position (Mauna Loa Lookout, estimated) | 500 m horizontal, 15 m vertical |
| K2cam position (Uēkahuna bluff, estimated) | 75 m, 5 m |
| K2cam field of view (datasheet, widest zoom) | 1.5° |
| K2cam roll (level mount), k1 | 1°, 0.05 |
| Puʻukoaʻe (GNIS, EPQS) | 50 m, 10 m; its pixel 3 px |
| North vent | 10 m, 5 m |
| Refraction coefficient k (0.13) | 0.05 |
| Each Moon centre | 2 px |
| Mask edge | 3 px |
| Lean along the line of sight | 5° fountains, 10° plumes |

The calibration samples are shared by all detections of a preset, because a calibration error is systematic. Edge and lean are drawn per detection.

A draw the solver cannot fit makes the calibration fail instead of corrupting the sigmas. That means a misfit above 10 times the samples' median plus 10 px.

## KPcam: calibrated from the Moon

**Why the Moon.**
- KPcam's position is only an estimate.
- Its sea horizon is always hidden under trade cumulus: all 29 mornings checked, Sep 28 – Oct 26.
- The GNIS cones of the Kaʻū Desert do not stand out on its skyline, which it sees from above.
- The Moon, though, crosses its field every afternoon of Oct 15–20 (JPL Horizons), as a small crescent or gibbous disk in a blue sky. Nine frames are clear, and they were backfilled from AshCam:
  - Oct 16, 22:15–23:15Z (five frames);
  - Oct 19, 00:45Z;
  - Oct 20, 00:45–01:15Z (three frames).

**Method** (`scripts/moon_references.py`):
1. JPL Horizons gives the Moon's airless topocentric azimuth and elevation, seen from KPcam at each frame's AshCam capture time.
2. Refraction is added for the camera's pressure: 792 hPa at 2,034 m, 12 °C, Saemundsson's formula. It adds 2.6′ at 17° elevation and 6.9′ at 6°.
3. The Moon's centre is the centre of a circle fitted to the lit limb, with the radius free. The fitted radius is 11–13 px, because distortion shrinks the disk toward the corners. The limb misfit is 0.5–1.6 px.

**Result** (`scripts/check_calibration.py --camera kilauea-kp --at 2026-10-17T17:00Z`):

| Moon (UTC) | picked (col, row) | solved | misfit |
|---|---|---|---|
| Oct 16 22:15 | 490.1, 885.2 | 491.8, 887.4 | 2.8 px |
| Oct 16 22:30 | 589.3, 710.5 | 589.9, 712.0 | 1.7 px |
| Oct 16 22:45 | 695.5, 539.1 | 695.8, 540.1 | 1.0 px |
| Oct 16 23:00 | 809.8, 370.7 | 809.0, 372.3 | 1.8 px |
| Oct 16 23:15 | 930.4, 208.8 | 929.5, 209.2 | 1.0 px |
| Oct 19 00:45 | 627.9, 127.5 | 624.5, 125.5 | 4.0 px |
| Oct 20 00:45 | 66.5, 562.4 | 68.8, 560.7 | 2.9 px |
| Oct 20 01:00 | 174.7, 370.3 | 176.0, 368.2 | 2.5 px |
| Oct 20 01:15 | 293.2, 181.0 | 292.2, 179.9 | 1.5 px |

**Solved view.**
- RMS misfit 1.64 px.
- Azimuth 145.59° ± 0.06.
- Tilt 3.24° ± 0.05.
- Roll −0.65° ± 0.10.
- Focal length 3,509 ± 13 px.
- k1 −0.280 ± 0.006.
- Field of view 62.9° ± 0.1 across the middle row.
- All 1,000 Monte Carlo samples converge (median misfit 2.3 px, worst 3.8 px).

**Two checks, independent of the vent and of every official value:**
1. **The vent.** It lands at (1228, 1514).
   - That is 30 px left of the fountain's visible foot at about (1258, 1505). KPcam's ±500 m position allows ±120 px across the line of sight.
   - It is 9 px below the foot, as expected: the crater rim hides the lowest tens of metres of the fountain from 14 km.
2. **The sea horizon.** Predicted from the camera's elevation alone (dip 1.35° from 2,034 m), it runs along the base of the trade-cumulus band, where the sea disappears behind the clouds.

The overlay is `data/calibration/kilauea-kp_fixed_2026-10-17T1700.jpg`. It shows the picked and solved Moon centres, the sea horizon, the vent and altitude ticks.

**Preset validity.** The framing (the tree, the skyline) is the same on every AshCam morning from Sep 28 to Oct 27, so the preset covers frames from Sep 25 on.

## K2cam: calibrated from its lens datasheet and Puʻukoaʻe

Done on 2026-11-02 for Phase 9. K2cam's framing held through episode 55 (frames register within 4 px), and from Oct 15 to 19 (19 of 20 hourly frames within 5 px). It is a pan-tilt-zoom camera with no readout on its frames, so the view must come from what the frames show.

**What Phase 3 found.** The references in the frame leave the focal length open.
- Puʻukoaʻe, at (2992, 1629), and three humps at (3297, 1623), (3393, 1617) and (3478, 1617) stand on the right-hand skyline. They all lie on one row, 8–23 km away, so they barely constrain tilt, roll and focal length. Every assignment of the humps to the Kamakaiʻa, Red Cones, Yellow Cone and Puʻukou GNIS points fits within 4–7 px, with focal lengths from 2,300 to 5,600 px.
- The USGS 3DEP skyline (one `exportImage` request, about 27 m per pixel) fitted with Puʻukoaʻe has two solutions: focal 2,122 px (field of view 84.3°) with tilt 12.8°, or 3,479 px (57.8°) with tilt 7.1°. The profile is too flat to choose. The DEM predates 2018 inside the caldera, so the crater rim near the vent cannot serve.
- No clear sea horizon shows on the 19 frames with the episode framing, and the night frames are black.

**The lens decides.** Patrick et al. 2026 (doi:10.1186/s13617-026-00170-x) list HVO's snapshot webcams: "Two of these are wide angle 4K cameras (Axis P1378), one is PTZ (Axis Q6318)". K2cam is the only pan-tilt-zoom camera among them, so it is that Axis Q6318; the paper does not name K2cam, so this is an inference. Axis gives the AXIS Q6318-LE a horizontal field of view of 58.5° at its widest zoom and 2.3° at its narrowest, on 3840×2160 ([product page](https://www.axis.com/products/axis-q6318-le)). Zooming only narrows the view, so:
- the 84.3° solution is impossible;
- the 57.8° solution is 1.2 % from the widest zoom, so the camera was at its widest zoom (or next to it) during the episode.

**References and priors** (`config/calibration.yaml`, preset `ep55`):
- field of view 58.5 ± 1.5°. The sigma covers the spread between units and the barrel distortion, which is not measured: a k1 of −0.1 would move the focal length that matches 58.5° by about 3 %;
- roll 0 ± 1°: a level pan-tilt-zoom mount;
- radial distortion k1 0 ± 0.05;
- Puʻukoaʻe: pixel (2992, 1629) ± 3 px, GNIS 19.35528 N, 155.32235 W ± 50 m, EPQS ground elevation 979 ± 10 m. It is 8.0 km away at 206°. Its pixel holds within 2 px on the 07:00, 08:00 and 09:00 HST frames.

The vent is not a reference. Its bearing from the camera depends on K2cam's estimated position (±75 m at 1,678 m is ±2.6°). With the fountain's axis as a reference, the solver bends the focal length to 3,070 ± 242 px to absorb that.

**Result** (`scripts/check_calibration.py --camera kilauea-k2 --at 2026-10-17T18:00Z`):
- Azimuth 188.82° ± 0.81.
- Tilt +7.07° ± 0.43 (the optical axis points above level, so the frame holds the plume).
- Roll 0.0° ± 1.0.
- Focal length 3,428 ± 103 px; field of view 58.9° ± 1.7 across the middle row.
- All 1,000 Monte Carlo samples converge. Two references and three priors fix five unknowns exactly, so the misfit is 0 px and says nothing; the checks below do.

**Two checks, independent of every official value:**
1. **The vent.** It lands at (1670, 1853).
   - Vertically, that is 3 px below the foot of the fountain, at row 1850 (the median lowest row of SAM's 136 fountain boxes). At 1,678 m, 3 px is 1.5 m.
   - Horizontally, it is 166 px left of the fountain's axis, at column 1836 (the median box centre): 2.8° of bearing, about one sigma of K2cam's estimated position. The camera probably stands some 80 m east of where it was placed.
2. **The sea horizon.** Predicted from the camera's elevation alone (dip 1.06° from 1,245 m), it runs along rows 1571–1581 from column 2600 to the right edge. That is just under the base of the trade cumulus over the sea and above the land skyline (row ≈ 1630), as on KPcam.

The overlay is `data/calibration/kilauea-k2_ep55_2026-10-17T1800.jpg`, with the vent, the sea horizon, Puʻukoaʻe and a scale every 50 m above the vent.

**What the sigmas carry.** A fountain height from K2cam is about D · Δrow / f, with D = 1,678 m. Its sigma comes from the focal length (3 %), the distance (K2cam's position, 4.5 %), the tilt fixed by Puʻukoaʻe (0.43°, about 13 m at the vent, mostly from the roll prior), the mask edge (±3 px, 1.5 m) and the lean (5°).

## K2cam live: the framing guard

Added on 2026-11-02, after Phase 9, so the Space measures episode 56's fountain ([plan](../superpowers/plans/2026-11-02-k2cam-live-preset.md)). The preset `live` reuses ep55's references and priors from Oct 18 on; the values that the validation used are unchanged. A pan-tilt-zoom camera can be moved at any time, so `vigil/framing.py` measures a live frame only while it still shows ep55's framing. K2cam's frame of Nov 2 20:58Z registers within 4 px of Oct 17's.

**The check.** Each frame is compared with two reference frames that the episode 55 mirror ships:
- day: Oct 17 19:28Z;
- night: Oct 17 12:30Z, lit by the overlook's path lamps.

The comparison:
- it uses the gradient magnitude of the overlook in the foreground (rows below 80 % of the height), at 960 px wide;
- the columns around the vent (40–62 % of the width) are left out, since the fountain, its glow and the plume live there;
- a phase correlation must peak within ±2 px at 960 (8 px of the 4K frame, about 4 m at the fountain) with a peak of at least 0.05.

**Calibration on real frames:**
- 100 of 101 K2cam frames from Oct 16 to Nov 2 register. These are every 30 minutes on Oct 16, 17, 26 and 27, plus 28 Space frames, day and night. The miss is a fog frame.
- Synthetic moves of real day and night frames never register: shifts of 12 px down and 24 px diagonally, zooms of 1.02, 1.05 and 0.97, and a 400 px pan. A 12 px sideways shift sometimes does; that is under 6 m.

**The fountain's light.** On the brightest fountaining night no reference matches, because the fountain lights the whole scene. In episode 55 that happens on most frames from 14:18 to 15:58Z (04:18–05:58 HST), the peak. A dark frame (mean brightness under 60 of 255) is then still measured when both hold:
- a lava fountain's foot on it lies within 200 px of the vent's projection, at (1670, 1853);
- a frame registered within the previous 2 h.

The foot is the middle of the mask's lowest rows. On episode 55's 139 frames with a fountain it lies a median (+33, −4) px from the projection, and 167 px at most. A zoom of 1.25× or a turn of 3.3° moves it farther than 200 px.

**Episode 55 through the guard** (`FramingGuard` with the `live` preset over the replay's 210 K2cam frames):
- 165 frames register;
- 40 dark frames pass on the fountain's foot;
- 5 frames are not measured: four at 14:18–14:24Z, which have no fountain detection, and one at dawn, 16:02Z, with brightness 62.8 that does not register.
- In all, 138 of the 139 frames with a fountain would be measured.

## V1cam: not calibrated

- Its position is known only to ±150 m, at 407 m from the vent: ±37 % on distance.
- During the episode its PTZ preset changed three times: zoom at 03:47 and 04:41 HST, then a pan between 05:01 and 05:17 HST, where the fountain jumps from x ≈ 800 to x ≈ 1380.
- It still gives the end of fountaining.

## Not used

- **B1cam and F1/KWcam.** Their positions are published, but they are fisheye cameras and they are not tracked.
- **KPcam's `glow` masks as fountain heights.**
  - At night the glow's halo reaches 440–750 m above the vent.
  - By day the masks cover only the incandescent core: about 145 m at 06:00 HST and 49 m at 08:00, while HVO reported 650 and 300 ft.

## Limitations

- **KPcam's position is an estimate.** Its ±500 m becomes ±3.6 % on distance, the largest term in the plume sigmas after the lean.
- **Plume tops are the highest point of the whole `steam` mask.** Downwind of the vent that can be cloud from earlier, higher injection. At 07:30 HST the mask's top is 2.5–3 km downwind of the vent (see [VALIDATION.md](../VALIDATION.md)).
- **K2cam's lens is an inference.** Its model comes from HVO's list of cameras, not from a statement about K2cam; its zoom is taken as the widest, which the 3DEP skyline supports; its distortion is not measured. A view zoomed in by 10 % would make every K2cam height 10 % too high.
- **K2cam's position is an estimate.** Its ±75 m becomes ±4.5 % on distance. The vent's bearing hints that the camera stands about 80 m east of the estimate, which barely changes the distance.
- **K2cam's live heights assume the north vent.** The south vent lies 94 m beyond it, almost along K2cam's line of sight (1,678 → 1,772 m). A fountain from the south vent would read about 6 % low, inside its sigma; that vent was buried by tephra in episode 55.
- **The framing guard leaves a gap on fountain-lit nights.** It cannot see a small move then. A move after the last registered frame passes for up to 2 h if it keeps the fountain's foot within 200 px of the vent's projection. That covers zooms under about 1.25× and turns under about 3°.
- **Fountain tops are the highest point of the `lava fountain` mask.** At night the mask can include spray and the glow on the plume above the jet.
- **The lean is assumed, not measured.** It is 5° for fountains and 10° for plumes.
- **The distortion model is limited.** It has one radial term, no tangential term, and a principal point fixed at the image centre.
