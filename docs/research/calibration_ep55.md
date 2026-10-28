# Camera calibration for episode 55

Done on 2026-10-28 for Phase 3. It covers how each camera's view was fixed, the evidence, and what is still missing.
- Code: `vigia/geometry.py` and `vigia/calibration.py`.
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

## K2cam: not calibrated in this phase

K2cam's framing held through episode 55 (frames register within 4 px). It also held from Oct 15 to 19: 19 of 20 hourly frames register within 5 px. Every reference tried leaves its focal length and tilt undetermined.

**GNIS cones.**
- Puʻukoaʻe, at about (2992, 1629), and three humps at (3297, 1623), (3393, 1617) and (3478, 1617) stand on the right-hand skyline.
- They all lie on one row, 8–23 km away, so they barely constrain tilt, roll and focal length.
  - Every assignment of the humps to the Kamakaiʻa, Red Cones, Yellow Cone and Puʻukou GNIS points fits within 4–7 px, with focal lengths from 2,300 to 5,600 px.
  - With a level-mount roll prior (0 ± 1°), the two best assignments still give f 2,498 or 2,783 px.
- The peak fountain heights they imply are 279, 254 and 209 m for the three best: a 25 % spread.

**USGS 3DEP skyline.**
- The skyline profile comes from one `exportImage` request (about 27 m per pixel, within 3 m of EPQS). It runs from −1.67° to −2.02° between azimuth 150° and 225°.
- Fitted with Puʻukoaʻe, it has two solutions: f 2,122 px with tilt 12.8°, or f 3,479 px with tilt 7.1°. The profile is too flat to choose.
- The DEM predates 2018 inside the caldera, so the crater rim near the vent cannot serve.

**Sea horizon.** It would separate the two solutions, lying 32 or 53 px above the land skyline (row ≈ 1634). It never appears as a sharp line on the 19 frames with the episode framing. A faint tonal boundary near row 1612, 21 px above the land, matches neither.

**Stars.** K2cam's night frames from Oct 18 and 19 are black.

So the `ep55` preset carries no references, and the fountain rows of the validation read "no measurement". Phase 8 lists the fix: a vertical reference for K2cam, or V1cam through the Moon plus a resection on the vent.

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
- **The lean is assumed, not measured.** It is 5° for fountains and 10° for plumes.
- **The distortion model is limited.** It has one radial term, no tangential term, and a principal point fixed at the image centre.
