# Kīlauea summit episode 55 (2026-10-17): media, official values, timeline

Research for the Vigía Andino "replay" mode. Everything was retrieved live on **2026-10-26**.

- **Time zone.** HST = UTC−10 (Hawaiʻi has no daylight saving time). HVO's own headers confirm the offset, for example "Saturday, October 17, 2026, 9:50 AM HST (Saturday, October 17, 2026, 19:50 UTC)" ([DU 10-17][DU17]). Webcam overlays and webcam file names are in HST. AshCam file names are Unix epoch seconds (UTC).
- **Local data.** `data/raw/usgs_ep55/manifest.json` has 31 items. `data/raw/usgs_ep55/ashcam/manifest_ashcam.json` has 857 archived webcam frames. Both use the requested schema.
- **Quotes.** Quoted text is verbatim, including HVO's typos (marked [sic]). Notes marked *derived* come from my own EXIF, ffprobe or visual inspection of the downloaded files, not from USGS text.

### Source keys (all fetched 2026-10-26)

| Key | What | URL |
|---|---|---|
| CHRON | Photo & Video Chronology — Kīlauea summit episode 55 (dated Oct 17, 2026) | https://www.usgs.gov/observatories/hvo/news/photo-video-chronology-kilauea-summit-episode-55-0 |
| DU17 | HVO Daily Update, Sat Oct 17 2026 9:50 AM HST (19:50 UTC). Holds the detailed account of episode 55. | [DU17] |
| VAN488 | VAN 2026/H488, issued 3:43 AM HST (onset), with VONA 2026/66 (DTG 20261017/1343Z) | [VAN488] |
| VAN490 | VAN 2026/H490, issued 5:22 AM HST (peak), with VONA 2026/67 (DTG 20261017/1522Z) | [VAN490] |
| VAN489 | VAN 2026/H489, issued 9:11 AM HST (end), with VONA 2026/68 (DTG 20261017/1911Z) | [VAN489] |
| VAN492 | VAN 2026/H492, issued 9:59 AM HST (WATCH→ADVISORY), with VONA 2026/69 (DTG 20261017/1959Z) | [VAN492] |
| MSG | HVO Observatory Messages (Kilauea Messages 2026-10-17 03:40:12 to 09:13:41 HST) | https://www.usgs.gov/observatories/hvo/observatory-messages |
| DU15, DU16, DU18, DU19, DU20 | Daily Updates for Oct 15, 16, 18, 19 and 20 | [DU15], [DU16], [DU18], [DU19], [DU20] |
| UPD | Kīlauea Volcano Updates page, showing the DU of Mon Oct 26 2026 8:10 AM HST | https://www.usgs.gov/volcanoes/kilauea/volcano-updates (notice [DU26]) |
| ERUP | Kīlauea "Recent Eruption" page: episode table, maps, hazards | https://www.usgs.gov/volcanoes/kilauea/science/eruption-information |
| MAP0908 | Sep 8, 2026 summit eruption reference map (statistics through episode 54) | https://www.usgs.gov/media/images/september-8-2026-kilauea-summit-eruption-reference-map |
| VW1023 | Volcano Watch, Oct 23, 2026. No new episode 55 numbers. | https://www.usgs.gov/observatories/hvo/news/volcano-watch-a-look-back-recent-kilauea-eruptions-and-intrusions |
| OVF | Photo & Video Chronology — monitoring overflight, Oct 22, 2026 | https://www.usgs.gov/observatories/hvo/news/photo-video-chronology-kilauea-summit-monitoring-overflight-8 |
| CAMS | Kīlauea webcams index | https://www.usgs.gov/volcanoes/kilauea/webcams |
| ASHCAM | USGS VHP AshCam (archive of past webcam images) | https://volcview.wr.usgs.gov/ashcam-gui/webcam.html |

[DU17]: https://volcanoes.usgs.gov/hans-public/notice/DOI-USGS-HVO-2026-10-17T15:47:29+00:00
[VAN488]: https://volcanoes.usgs.gov/hans-public/notice/DOI-USGS-HVO-2026-10-17T13:25:52+00:00
[VAN490]: https://volcanoes.usgs.gov/hans-public/notice/DOI-USGS-HVO-2026-10-17T14:51:56+00:00
[VAN489]: https://volcanoes.usgs.gov/hans-public/notice/DOI-USGS-HVO-2026-10-17T19:04:00+00:00
[VAN492]: https://volcanoes.usgs.gov/hans-public/notice/DOI-USGS-HVO-2026-10-17T19:56:12+00:00
[DU15]: https://volcanoes.usgs.gov/hans-public/notice/DOI-USGS-HVO-2026-10-15T19:07:17+00:00
[DU16]: https://volcanoes.usgs.gov/hans-public/notice/DOI-USGS-HVO-2026-10-16T18:37:16+00:00
[DU18]: https://volcanoes.usgs.gov/hans-public/notice/DOI-USGS-HVO-2026-10-18T18:32:10+00:00
[DU19]: https://volcanoes.usgs.gov/hans-public/notice/DOI-USGS-HVO-2026-10-19T17:51:54+00:00
[DU20]: https://volcanoes.usgs.gov/hans-public/notice/DOI-USGS-HVO-2026-10-20T18:46:06+00:00
[DU26]: https://volcanoes.usgs.gov/hans-public/notice/DOI-USGS-HVO-2026-10-26T17:50:18+00:00
[MSG]: https://www.usgs.gov/observatories/hvo/observatory-messages
[CHRON]: https://www.usgs.gov/observatories/hvo/news/photo-video-chronology-kilauea-summit-episode-55-0
[ERUP]: https://www.usgs.gov/volcanoes/kilauea/science/eruption-information
[UPD]: https://www.usgs.gov/volcanoes/kilauea/volcano-updates
[MAP0908]: https://www.usgs.gov/media/images/september-8-2026-kilauea-summit-eruption-reference-map

A VONA-only view of each notice is at `https://volcanoes.usgs.gov/hans-public/vona/<notice id>`. The HANS notices for Oct 15–20 were listed through `POST https://volcanoes.usgs.gov/hans-public/api/search/search` (14 notices: DU, VAN, VV). There was no separate Status Report or Information Statement for episode 55.

---

## 1. Bottom line

| What you believed | Official statement | Match? |
|---|---|---|
| Fountain up to ~720 ft (~220 m) | "Maximum fountain heights of 720 feet (220 m) were recorded between 4:50 and 5:10 a.m. HST" ([DU17]). The reference is ground or vent level: "approximately 720 feet (220 meters) above ground level from the north vent" ([UPD]); "FOUNTAINS CURRENTLY REACHING 700 FT AGL" (VONA 2026/67, [VAN490]). | **Yes.** 720 ft = 219.5 m. Several texts say "just over 700 feet (220 m)". |
| Plume ~25,000 ft above sea level (~7.6 km) | "VA CLD HGT: 25000FT AMSL" and "HGT SOURCE: WEBCAM" (VONA 2026/67, 15:22Z, [VAN490]); "the plume cloud reaching up to 25,000 feet (7500 m) above sea level (a.s.l.) during that time" (4:50–5:10 a.m. HST, [DU17]) | **Yes for 25,000 ft a.s.l.** HVO's metric conversion varies: 7,500 m ([DU17], [MSG], [UPD]), 7,600 m ([CHRON] captions) and 7,000 m (one sentence in [DU17]). The exact conversion is 7,620 m. |

**Key times.** Onset at 3:19 a.m. HST (13:19 UTC), peak from 4:50 to 5:10 a.m. HST (14:50–15:10 UTC), end at 9:03 a.m. HST (19:03 UTC). That is 5 h 44 min, which HVO rounds to "5.7 hours". The north vent was the only fountaining vent. The plume drifted to the southwest.

---

## 2. Official values (exact quotes)

| Quantity | Value (units, reference) | Exact sentence | Source | Time (issued, or valid for) |
|---|---|---|---|---|
| Onset | 3:19 a.m. HST, Oct 17 (13:19 UTC) | "Episode 55 of the ongoing Halemaʻumaʻu eruption began at 3:19 AM HST on October 17, 2026." | [VAN488] | Issued 3:43 AM HST |
| Onset definition | Tremor doubled, deflation began, fountain under 30 m | "This along with the doubling of the north vent fountain height defined the onset of episode 55 fountaining even though the fountain was less than 100 feet (30 m) high at the time." | [DU17] | 9:50 AM HST |
| End | 9:03 a.m. HST (19:03 UTC) | "Episode 55 of the ongoing Halemaʻumaʻu eruption ended abruptly at 9:03 a.m. HST on October 17, 2026 after about 6 hours of continuous lava fountaining." | [VAN489] | 9:11 AM HST |
| End (conflicting) | 9:06 a.m. HST | Episode table row: "55 · October 17, 2026 - 3:19 a.m. · October 17, 2026 - 9:06 a.m. · 6 hours · TBD · 220 · 7 · Overflows from the north, south and west vents prior to lava fountaining from the north vent". The column header is "Pause Date/Time (HST)". | [ERUP] | Page as of Oct 26 |
| Duration | ~6 h; 5.7 h | "…paused following 5.7 hours of lava fountaining during episode 55 on October 17, 2026." Also "Episode 55 fountaining ended abruptly at 9:03 a.m. HST after just under 6 hours of eruption." | [DU18]; [MSG] 09:13:41 HST | Oct 18 10:30 AM HST |
| Max fountain height | 720 ft (220 m), north vent, 4:50–5:10 a.m. HST | "Maximum fountain heights of 720 feet (220 m) were recorded between 4:50 and 5:10 a.m. HST with the plume cloud reaching up to 25,000 feet (7500 m) above sea level (a.s.l.) during that time." | [DU17] | Valid 14:50–15:10 UTC |
| Max fountain height (reference level) | 220 m above ground level | "The maximum lava fountain height was approximately 720 feet (220 meters) above ground level from the north vent." | [UPD] (same text in [DU18]–[DU20]) | Oct 18–26 |
| Fountain height at the peak notice | 720 ft; "just over 700 feet" | Summary: "The north vent fountain has reached a maximum height of 720 feet (220 m)." Body: "The fountain from the north vent reached a maximum height of just over 700 feet (220 m) by 5:00 a.m. HST." VONA: "FOUNTAINS CURRENTLY REACHING 700 FT AGL." | [VAN490] | 5:22 AM HST / 15:22Z |
| Fountain at onset notice | 100–150 ft (30–45 m) | "Fountain heights are relatively low at about 100-150 feet (30-45 m)…" VONA: "CURRENT FOUNTAIN HEIGHTS 100 FT AGL." | [VAN488] | 3:43 AM HST / 13:43Z |
| Fountain, 4:21 a.m. | ~250 ft (80 m) | "The north vent fountain has grown to about 250 feet (80 m) high and is at least as wide." | [MSG] | 04:21:15 HST |
| Fountain, 5:11 a.m. | just over 700 ft (220 m) | "The north fountain is now just over 700 feet (220 m) with a plume cloud rising to about 25,000 feet (7500 m) a.s.l." | [MSG] | 05:11:55 HST |
| Fountain, ~5:50 a.m. | nearly 600 ft (180 m) | "This photo was taken at about 5:50 a.m. HST with the lava fountain at nearly 600 ft (180 m) tall." | [CHRON] (D. Downs caption) | ~15:50 UTC |
| Fountain, 6:02 a.m. | ~650 ft (200 m) | "The north vent fountain has dropped to about 650 feet (200 m) high and the plume cloud is down to 17,000 feet asl." | [MSG] | 06:02:51 HST |
| Fountain, 7:00 to 8:00 a.m. | 650 → 500 ft by 7:00; ~300 ft (100 m) by 8:00 | "The fountain dropped quickly back to 650 feet and then to 500 feet by 7:00 a.m. HST this morning and was down to about 300 feet (100 m) high by 8:00 a.m. HST." | [DU17] | — |
| Fountain, ~7:00 a.m. (caption) | ~400 ft (120 m) | "The lava fountain was about 400 feet (120 m) high at this point." | [CHRON] (D. Downs caption, "about 7:00 am") | ~17:00 UTC |
| Fountain, 7:47 a.m. | ~500 ft (150 m) | "The north vent fountain has dropped to about 500 feet (150 m) high, about the same as the maximum fountain height for episodes 51-54." | [MSG] | 07:47:26 HST |
| Max plume height | 25,000 ft AMSL, measured by webcam | VONA: "VA CLD HGT: 25000FT AMSL"; "HGT SOURCE: WEBCAM"; "WEBCAMS SHOW THE PLUME AT ABOUT 25000 FT AMSL." VAN: "The plume from this eruption is reaching about 25,000 feet above sea level." | [VAN490] | 5:22 AM HST / 15:22Z |
| Max plume height (summary) | 25,000 [ft] (7,500 m) AMSL | "The maximum plume height was approximately 25,000 (7,500 meters) above mean sea level." [sic: the unit "feet" is missing] | [UPD], [DU18]–[DU20] | Oct 18–26 |
| Max plume height (third conversion) | 25,000 ft (7000 m) a.s.l. | "Plumes of volcanic gas and tephra reached as high as 25,000 feet (7000 m) above sea level but dropped rapidly to under 20,000 feet above sea level." | [DU17] | — |
| Max plume height (captions) | 25,000 ft (7,600 m) a.s.l. | "The plume from this eruption reached about 25,000 feet (7,600 meters) above sea level." | [CHRON] (B. Wenzel caption) | — |
| Plume, 6:02 a.m. | 17,000 ft a.s.l. | (same 06:02:51 message as the 650 ft fountain row) | [MSG] | 06:02:51 HST |
| Plume, 7:30 to 7:47 a.m. | under 13,000 ft (4,000 m) a.s.l. | "Likewise, the plume cloud dropped to under 13,000 feet (4000 m) a.s.l. by 7:30 a.m. HST." Also "Top of the plume cloud has dropped under 13,000 ft (4,000 m) above sea level." | [DU17]; [MSG] 07:47:26 | — |
| Tephra height in the plume (radar) | 8,000 [ft] a.s.l. | "Current radar images show significant tephra within the plume up to only 8,000 above sea level." [sic: no unit] | [VAN490] | 5:22 AM HST |
| Drift direction | SW below 20,000 ft; possibly east above 20,000 ft | VONA: "MOV: SW"; "FALLOUT LIKELY IN THE SOUTHWEST DIRECTION DOWNWIND OF VENTS. ABOVE 20000 FT AMSL THE PLUME MAY MOVE TO THE EAST." DU: "Winds below 20,000 feet were out of the northeast, pushing the plume to the southwest." | [VAN490]; [DU17] | 15:22Z |
| Winds (VAN) | from NNE, so material goes SSW; west winds above 20,000 ft | "Winds are blowing from the north-northeast direction, which suggests that volcanic gas emissions and volcanic material may be distributed to the south-southwest direction from Halemaʻumaʻu." Also "The National Weather Service reports winds above 20,000 feet coming from the west." | [VAN490] (similar wording in [VAN488]) | 3:43 and 5:22 AM HST |
| Drift in a photo | SW over the Kaʻū Desert | "The sun was illuminating the plume as it drifted to the southwest over the Kaʻū Desert." | [CHRON] (D. Downs, ~7:00 am) | ~17:00 UTC |
| Tephra and Pele's hair | Mostly in the closed park area, SW; traces in Pāhala | "Most tephra fall is expected to occur southwest of the vent area within the closed area of Hawaiʻī Volcanoes National Park, but traces of fine ash and Peleʻs hair in Pāhala and possibly other communities to the southwest in Kaʻū." Later: "Tephra fall was restricted mostly to the closed area of Hawaiʻi Volcanoes National Park, southwest of the active Halemaʻumaʻu vents." | [DU17]; [UPD] | — |
| Tephra range (generic) | 3 mi (5 km) | "Tephra fall from volcanic ash clouds is greatest within 3 miles (5 km) of the vents, lighter ash and Pele's Hair may stay suspended for large distances from the vents." | [VAN488] | — |
| Erupted volume | ~7 million m³ (9 million yd³), preliminary | "Preliminary estimates indicate about 9 million cubic yards (7 million cubic meters) of lava erupted during this episode." The [ERUP] table also gives 7 (million m³). | [DU17]; [ERUP] | — |
| Effusion rate | Peak ~770 m³/s at ~5:00 a.m.; mean 290 m³/s | "The instantaneous effusion rate peaked at about 1000 cubic yards (770 cubic meters) per second at approximately 5:00 a.m. HST, with an average effusion rate of 380 cubic yards (290 cubic meters) per second for the entire fountaining episode." | [DU17] | — |
| Lava coverage | 30–40% of floor at 6:02; 75% by 8:30 | "Lava flows are now covering about 30-40% of the floor of Halema'uma'u crater." Also "…by 8:30 a.m. HST were covering 75% of the crater floor." | [MSG] 06:02:51; [DU17] | — |
| Vents | Only the north vent fountained | "The south and west vents never fountained during this episode but did produce overflows prior to the fountaining episode." DU17 adds: "…while the south and west vents had small dome fountains that continued to feed flows. The south vent overflows ended at 3:55 a.m. HST while the west vent fountains and overflows were drowned by the north vent at 4:13 a.m. HST." | [UPD]; [DU17] | — |
| Vent state afterwards | South vent buried by tephra | "No glow was visible from the south vent, which was covered in a layer of tephra during episode 55." | [UPD] | Oct 26 |
| Tilt | 21 µrad deflation at UWD | "Deflationary tilt measured at a summit tiltmeter at Uēkahuna (UWD) totaled 21 microradians during episode 55." | [UPD], [DU18] | — |
| Tremor | ~10× background at 4:30 | "Tremor rapidly increased to about 10 times background by 4:30 a.m. HST about 20 minutes prior to the fountain reaching its maximum height of 720 feet." | [DU17] | — |
| SO₂ | Generic value, not measured for episode 55 | "During fountain episodes, the sulfur dioxide (SO2) emission rate from the summit typically 100,000 tonnes per day." [sic] | [DU17] | — |
| Precursors | 39 days; 359 overflows | "The episode was also preceded by 39 days of intermittent overflows, a record for the length of precursory activity prior to fountaining." Also "There were 359 precursory overflows since the episode 54 fountains ended." | [UPD]; [MSG] 03:40:12 | — |
| Alert level | WATCH/ORANGE → ADVISORY/YELLOW at 9:59 a.m. HST | "VAN is being reissued to drop the alert level from WATCH to ADVISORY and the color code from ORANGE to YELLOW." | [VAN492] | 9:59 AM HST / 19:59Z |

---

## 3. Timeline (HST and UTC)

| HST | UTC | Event | Source |
|---|---|---|---|
| Sep 7 | — | "Initial precursory flows erupted on September 7 preceding episode 55 fountains by 39 days." | [DU17] |
| Sep 14 20:36 to Sep 16 20:30 | Sep 15 06:36 to Sep 17 06:30 | Six new vents on the NW wall; flows without fountaining | [ERUP] |
| Sep 30 14:00 to Oct 1 04:00 | Oct 1 00:00 to 14:00 | Intrusion beneath the caldera; new cracks | [ERUP] |
| Oct 14 11:08 | Oct 14 21:08 | North-vent overflows resume | [DU15] |
| Oct 15 22:16 | Oct 16 08:16 | South-vent overflows begin overnight (15 small ones) | [DU16] |
| Oct 16 05:10 | Oct 16 15:10 | High-volume south-vent overflow | [DU16] |
| Oct 16 05:56 | Oct 16 15:56 | Continuous south-vent overflows begin | [DU16], [DU17] |
| Oct 16 18:11 | Oct 17 04:11 | Intermittent north-vent overflows begin | [DU17] |
| Oct 16 22:49 | Oct 17 08:49 | West-vent overflows begin | [DU17] |
| Oct 16 23:35 | Oct 17 09:35 | North-vent flows become continuous | [DU17] |
| Oct 17 ~01:30 | 11:30 | Minor deflationary tilt at UWD | [DU17] |
| 02:23 | 12:23 | West vent erupts lava continuously | [DU17] |
| 02:45 | 12:45 | Tremor begins to increase | [DU17] |
| **03:19** | **13:19** | **Onset.** North-vent fountain doubles (under 100 ft / 30 m); RSAM doubles; rapid deflation | [DU17], [VAN488] |
| 03:40 | 13:40 | Message: onset; 359 precursory overflows | [MSG] |
| 03:43 | 13:43 | VAN H488 / VONA 2026/66: fountain 100–150 ft (30–45 m), "100 FT AGL"; winds from NNE | [VAN488] |
| 03:55 | 13:55 | South-vent overflows end | [DU17] |
| 04:13 | 14:13 | West vent drowned by the north vent | [DU17] |
| 04:21 | 14:21 | Fountain ~250 ft (80 m); wind from NE | [MSG] |
| 04:30 | 14:30 | Tremor ~10× background. VONA 2026/67 also lists "ONSET: 20261017/1430Z". | [DU17], [VAN490] |
| **04:50–05:10** | **14:50–15:10** | **Peak.** Fountain 720 ft (220 m); plume up to 25,000 ft (7,500 m) a.s.l. | [DU17] |
| ~05:00 | ~15:00 | Peak effusion ~770 m³/s | [DU17] |
| 05:11 | 15:11 | Fountain just over 700 ft (220 m); plume ~25,000 ft a.s.l.; winds below 20,000 ft from NE | [MSG] |
| 05:22 | 15:22 | VAN H490 / VONA 2026/67: "VA CLD HGT: 25000FT AMSL" (webcam), "MOV: SW"; radar shows tephra only up to 8,000 [ft] | [VAN490] |
| ~05:50 | ~15:50 | Fountain nearly 600 ft (180 m) (photo caption) | [CHRON] |
| 06:02 | 16:02 | Fountain ~650 ft (200 m); plume 17,000 ft a.s.l.; lava on 30–40% of the floor | [MSG] |
| ~07:00 | ~17:00 | Fountain 500 ft ([DU17]) or ~400 ft / 120 m (caption); plume drifts SW over the Kaʻū Desert | [DU17], [CHRON] |
| 07:30 | 17:30 | Plume under 13,000 ft (4,000 m) a.s.l. | [DU17] |
| 07:47 | 17:47 | Fountain ~500 ft (150 m); plume top under 13,000 ft | [MSG] |
| 08:00 | 18:00 | Fountain ~300 ft (100 m) | [DU17] |
| 08:30 | 18:30 | Lava covers 75% of the crater floor | [DU17] |
| ~08:50 | ~18:50 | Waning behavior noted | [DU17] |
| **09:03** | **19:03** | **End**, abrupt. The [ERUP] table lists 9:06. | [VAN489], [DU17], [MSG] |
| 09:11 | 19:11 | VAN H489 / VONA 2026/68: "ERUPTION OCCURRED", "NO VA CLD PRODUCED" | [VAN489] |
| 09:50 | 19:50 | Daily Update with the detailed account | [DU17] |
| 09:59 | 19:59 | VAN H492 / VONA 2026/69: ADVISORY/YELLOW | [VAN492] |
| Oct 18 → Oct 26 | — | UWD recovers +5.4 (Oct 18), +7.1 (Oct 19), +8.6 (Oct 20) and +13.2 µrad (Oct 26). The episode 56 forecast moves from Oct 27–Nov 6 to Oct 31–Nov 6. | [DU18], [DU19], [DU20], [UPD] |
| Oct 22 | — | HVO overflight and sampling of the episode 55 flows | [OVF] |

---

## 4. Elevation reference and wind context

**Vent elevation.** The latest published value predates episode 55. [MAP0908] says: "Most of the data for this map were collected during a USGS Hawaiian Volcano Observatory helicopter overflight on August 28, 2026, so the provided statistics are reflective of the entire eruption through episode 54". Its statistics:

- "Vent elevations: 1,080 meters (3,545 feet)"
- "Vent level below crater rim: 60 meters (195 feet)"
- "Vent height to surrounding lava: 50 meters (165 feet)"
- "Cone's peak elevation: 1,186 meters (3,891 feet)"
- "Average lava elevation: 1,014 meters (3,327 feet)"

Earlier and nearby values for comparison:

- Through episode 50 (DEM of June 30): "Vent elevations: 1,075 meters (3,525 feet)" ([ERUP]).
- The six NW-wall vents of Sep 14–16: "Average vent elevation: 1,055 meters (3,460 feet) above sea level" ([ERUP]).

I found no post-episode-55 survey. The 39 days of overflows may have changed the vent elevation by some meters.

**Summit reference used in notices.** "Summit Elevation 4091 ft (1247 m)" and "SOURCE ELEV: 4091FT AMSL" ([VAN490], [DU17]). This is the nominal summit elevation, not the vent.

**Reference levels.** Fountain heights are given "above ground level" ([UPD]) or "AGL" (VONA). The [ERUP] impacts table header says "Fountain Height above vent level". Plume heights are given "above sea level" or "AMSL".

**Conversions** (*derived*; vent at 1,080 m a.s.l.):

| Official value | m a.s.l. | m above vent (1,080 m) | Notes |
|---|---|---|---|
| 25,000 ft a.s.l. (peak) | 7,620 | **6,540** (≈ 21,460 ft) | With HVO's own 7,500 m: 6,420 m. Relative to the 1,247 m summit reference: 6,373 m. |
| 20,000 ft (wind-shear level) | 6,096 | 5,016 | |
| 17,000 ft (06:02) | 5,182 | 4,102 | |
| 13,000 ft (07:30–07:47) | 3,962 | 2,882 | |
| 8,000 [ft] (radar tephra) | 2,438 | 1,358 | |
| Fountain 720 ft AGL | top ≈ 1,300 | 219.5 | The fountain top is about 60 m above Uēkahuna. The phones' GPS altitude at Uēkahuna was about 1,240 m (*derived* from EXIF). |

**Wind context from HVO.**

- "Winds are currently forecast from the north-northeast through today." ([DU16])
- From NNE, so material goes SSW ([VAN488], [VAN490]).
- "Wind is from the northeast…" ([MSG] 04:21).
- "Winds below 20,000 feet a.s.l. are from the northeast…" ([MSG] 05:11).
- "The National Weather Service reports winds above 20,000 feet coming from the west." ([VAN490])
- "ABOVE 20000 FT AMSL THE PLUME MAY MOVE TO THE EAST." (VONA 2026/67)
- General: "Where rising warm air from the Earthʻs surface meets the trade winds, an inversion layer exists between 5,000-10,000 feet (1,500-3,000 m) elevation." and "Eruptive plumes at the summit of Kīlauea can rise vertically and be sheared to the southwest where they encounter the trade wind inversion." ([ERUP])

---

## 5. Media inventory (all on disk in `data/raw/usgs_ep55/`)

**Licence.** Every media page has a **"Sources/Usage"** section that reads **"Public Domain."** The chronology page repeats "Sources/Usage: Public Domain." under every item ([CHRON]).

**Download URLs.**

- Photos: `https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/s3fs-public/media/images/<file>`. This is the page's "Original" link.
- Videos: `https://usgs-ocapsv2-public-input-media.s3.us-west-2.amazonaws.com/assets/palladium/production/s3fs-public/media/video/<file>`. This is the "Download Video" link. A transcoded copy sits at `…public-output-media…/media/video/<name>/MP4/<file>`.

The exact URL, SHA-256, size, dimensions and duration of each file are in `manifest.json`. Every file was under 300 MB (the largest is 22.4 MB), so nothing was skipped.

**What was downloaded.** 13 photos plus 1 video preview still (34.5 MB), 8 webcam stills (6.1 MB), 1 handheld video (7.4 MB) and 8 webcam timelapses (101.6 MB): 149.6 MB in total.

### 5a. Handheld photos

Media pages are at `https://www.usgs.gov/media/images/<slug>`. EXIF times are *derived*. iPhone EXIF times carry a −10:00 offset and are GPS-synced. Canon EXIF times are camera-clock and unverified.

| File | Slug (media page) | Time as stated | EXIF time (HST) | Credit (as printed) | Camera / place | Fountain | Plume |
|---|---|---|---|---|---|---|---|
| IMG_4481.jpeg | october-17-2026-episode-55-lava-fountain-and-flows-kilauea-summit | none | 05:41:46 | USGS photo by K. Mulliken. | iPhone 15 Pro Max, 24 mm-eq; GPS Steam Vents area | small | dark, partial |
| IMG_4446.jpeg | october-17-2026-episode-55-lava-fountaining-mist-kilauea-summit | "around 5:45 a.m. HST" | **05:25:53** | K. Mulliken | 255 mm-eq; "from the Steam Vents" | yes (misty) | no |
| **IMG_4430.jpeg** | october-17-2026-episode-55-north-vent-lava-fountain-kilauea-summit | none (caption cites the peak "by 5:00 a.m.") | **05:10:59** | K. Mulliken | 120 mm-eq; GPS 19.41975 N 155.28829 W (Uēkahuna), heading 177.6° | **yes, best near-peak** | no |
| IMG_4494.jpeg | october-17-2026-episode-55-lava-fountaining-kilauea-summit | "just before 6 a.m. HST" | 05:48:06 | K. Mulliken | 14 mm-eq; GPS 19.43093 N 155.26723 W, heading 258.8° | tiny | yes (left edge cut, ultra-wide) |
| multimediaFile-4765.jpg | october-17-2026-episode-55-kilauea-summit | none (caption cites "720 feet (220m) by 5:00 a.m.") | 05:53:25 (clock) | USGS photo by B. Wenzel. | Canon EOS Rebel T6, 89 mm; "from Uēkahuna" | yes | no |
| multimediaFile-4764.jpg | october-17-2026-early-morning-view-episode-55-lava-fountain-north-vent-kilauea-summit | "just before sunrise" | 06:22:50 (clock) | "USGU photo by K. Van Helden." [sic] | Canon T6, 63 mm; "from Uēkahuna" | yes | base only |
| multimediaFile-4760.jpg | october-17-2026-sunrise-over-summit-kilauea-during-episode-55 | sunrise, "about 3 hours" after onset | 05:55:17 | USGS photo by D. Downs. | iPhone 16, 14 mm-eq; "Uēkahuna overlook" | small | yes (cut at right edge) |
| multimediaFile-4766.jpg | october-17-2026-kilauea-episode-55-lava-fountain-and-flow-within-summit-caldera | none | 06:16:08 (clock) | B. Wenzel | Canon T6, 21 mm | small | top out of frame |
| **multimediaFile-4759.jpg** | october-17-2026-kilauea-summit-episode-55-lava-fountain-and-plume-sunrise | "about 5:50 a.m. HST", "nearly 600 ft (180 m)" | 05:48:55 | D. Downs | iPhone 16, 26 mm-eq (portrait) | yes | **yes, top in frame** |
| **multimediaFile-4768.jpg** | october-17-2026-episode-55-lava-fountain-and-flows-kilauea-summit-sunrise | "at 6:15 am" | 06:15:16 | USGS photo by N. Deligne. | iPhone 13, 26 mm-eq; GPS Uēkahuna, heading 170.9°; EXIF Orientation 6 (portrait) | yes | **yes, top just in frame** |
| multimediaFile-4762.jpg | october-17-2026-uekahuna-sunrise-during-episode-55-kilauea-summit | "morning" | 06:18:07 | D. Downs | iPhone 16, 14 mm-eq | small | yes (ultra-wide) |
| multimediaFile-4767.jpg | october-17-2026-episode-55-lava-fountaining-kilauea-summit-0 | none | 07:20:44 (clock) | "USGU photo by K. Van Helden." [sic] | Canon T6, 63 mm; "from Uēkahuna" | yes (daylight) | base only |
| multimediaFile-4763.jpg | october-17-2026-kilauea-summit-episode-55-lava-fountain-and-plume | "about 7:00 am", "about 400 feet (120 m)" | 07:04:44 | D. Downs | iPhone 16, 26 mm-eq | yes (daylight) | top cut |
| previewImage-4758.jpg | preview still of the Gallant video page | — | 06:14:19 | inferred from the video page | Nikon Z 6_2, 24 mm | small | top cut |

What the photos show (*derived*):

- **Night close-ups of the fountain:** IMG_4430, 4765 and IMG_4446.
- **Dawn views of fountain plus plume column:** 4759, 4768, 4762, 4760 and IMG_4494 (Mauna Loa silhouette).
- **Daylight fountain beside the tephra hill:** 4763, 4767 (with a small dust devil) and 4764.
- **Wide caldera views with lava flows:** IMG_4481 and 4766.

Full descriptions are in each manifest entry's `notes` field.

### 5b. Webcam stills

These are the preview (og:image) originals of the timelapse pages, not separately listed items. The timestamps are burned in.

| File | Camera | Overlay (HST) | PTZ overlay | Size | Use |
|---|---|---|---|---|---|
| 20261017055803M_KW.jpg | KWcam fisheye, W rim | 05:58:00 | — | 3840×2160 | Lava flows; fountain cut at the edge |
| 20261017060009M_B1.jpg | B1cam fisheye, S rim | 06:00:03 | — | 3840×2160 | Flows; fountain small at the left |
| 20261017060105M_V1.jpg | V1cam, NW rim | 06:01:03 | "P: 29, T: +0.00, Z: 29 1.0" | 1920×1080 | **Fountain** |
| 20261017060108M_V2.jpg | V2cam | 06:01:04 | "P: +178.54, T: -0.06, Z: 959 3.9" | 3840×2160 | **Fountain** |
| 20261017060105M_V3.jpg | V3cam, S rim | 06:01:03 | "P: +46.71, T: -2.81, Z: 245 1.2" | 1920×1080 | **Fountain** |
| 20261017060125M_F1.jpg | F1cam, thermal | 06:01:25 | — | 1200×900 | Hot areas only |
| 20261017060203M_K2.jpg | K2cam, Uēkahuna bluff | 06:02:01 | — | 3840×2160 | Fountain plus lower plume |
| **20261017062507M_KP.jpg** | KPcam, Mauna Loa Strip Road | 06:25:02 | — | 3840×2160 | **Whole plume, including its top** |

File names are `YYYYMMDDHHMMSSM_<cam>.jpg` in HST and run a few seconds later than the overlay.

### 5c. Videos

Media pages are at `https://www.usgs.gov/media/videos/<slug>`. Timing is *derived* from the burned-in overlays: I checked every 25th frame (every 12th for KP), and frame n's time is t0 + Δ·n. The last frame of each series comes one extra interval late.

| File (short) | Camera | Duration / frames / codec | MB | Overlay span (HST) | Frame time | Zoom changes (PTZ overlay) | Episode frames |
|---|---|---|---|---|---|---|---|
| multimediaFile-4758_mp4.mp4 | Handheld, L. Gallant ("USGS video by L. Gallant.") | 21.8 s, 1308 frames at 59.94 fps, H.264 + AAC, 1080p | 7.4 | ~06:00 (caption: "an hour before this video was taken") | real time | — | — |
| …V1cam20261017M.avi-.mp4 | V1 | 31.9 s, 319 frames at 10 fps, **HEVC**, 1080p | 20.0 | 01:21:03–11:59:01 | 01:21:03 + 2 min·n | 9.4× for n≤73; 1.4× for n=74–100; **1.0× for n≥101 (04:43 on)** | n≈59–231 |
| …V2cam… | V2 | 24.8 s, 248 frames, HEVC | 10.6 | 02:27:01–10:41:03 | 02:27:01 + 2 min·n | 23× for n≤43; **3.9× for n≥44 (03:55 on)** | n≈26–198 |
| …V3cam… | V3 | 28.4 s, 284 frames, HEVC | 13.9 | 01:05:02–10:33:01 | 01:05:02 + 2 min·n | 6.0× for n≤85; 3.0× for n=86–104; **1.2× for n≥105 (04:35 on)** | n≈67–239 |
| …K2cam… | K2 | 27.0 s, 270 frames, HEVC | 8.3 | 02:14:01–11:14:00 | 02:14:01 + 2 min·n | — | n≈32/33–204/205 |
| …KWcam… | KW | 33.6 s, 336 frames, HEVC | 22.4 | 00:46:01–11:58:01 | 00:46:01 + 2 min·n | — | n≈76/77–248/249 |
| …F1cam… | F1, thermal | 31.1 s, 311 frames, H.264, 1200×900 | 6.2 | 01:00:13–12:08:13 | **irregular**: OCR the overlay | — | — |
| …B1cam… | B1 | 38.5 s, 385 frames, HEVC | 15.7 | 01:00:02–13:50:01 | 01:00:02 + 2 min·n | — | n≈69/70–241/242 |
| …KPcam… | KP | 15.5 s, 155 frames, HEVC | 4.6 | 01:45:02–14:40:02 | 01:45:02 + **5 min**·n | — | n≈18/19–87/88 |

Notes on the timelapses:

- The captions say "six hours", but every clip spans roughly 9 to 13 hours.
- The V3 caption ends "USGS webcam image." [sic].
- HEVC needs an ffmpeg-enabled decoder. Transcode with `ffmpeg -i in.mp4 -c:v libx264 out.mp4` if OpenCV fails.

### 5d. Best material for measurement

**Fountain height.**

- IMG_4430: EXIF 05:10:59, inside HVO's 4:50–5:10 peak window. It has GPS and a compass heading, so it is the handheld ground truth for 720 ft.
- V1, V2, V3 and K2: use the timelapses or, better, the AshCam stills. Their zoom is fixed from 04:43 (V1), 03:55 (V2) and 04:35 (V3) to the end. V2 and K2 are 4K.
- Daylight: 4763 (07:04; caption says ~400 ft), 4767 and 4764.
- Do not treat 4765 as a 720 ft frame. Its EXIF time is ~05:53.

**Plume height.**

- KPcam is the camera HVO uses for plume height. VAN H488 says "KPcam and MKcam provide views of the plume height for aviation purposes", and the VONA lists "HGT SOURCE: WEBCAM".
- The AshCam KP frames show the whole column, top included, at 04:50 and 05:10 HST (night-lit) and through the morning (*derived*, viewed). For 04:50, 05:10 and 05:11 use `kilauea-kp-cam-1792248605.jpg` and `…1792249805.jpg`. 06:02 and 07:30–07:47 are also covered.
- Handheld frames with the plume top inside: 4759, 4768, 4762 and IMG_4494 (ultra-wide), plus 20261017062507M_KP.jpg.

**Ground-truth pairs for replay** (V1 frame index n = (t − 01:21)/2 min; KP index = (t − 01:45)/5 min):

| HST | Official value | Media |
|---|---|---|
| 03:43 | fountain 100–150 ft | V1 n=71 (9.4× zoom); AshCam ~13:43Z |
| 04:21 | fountain ~250 ft | V1 n=90 (1.4×); V2 n=57 |
| 04:50–05:10 | fountain 720 ft; plume 25,000 ft a.s.l. | IMG_4430; V1 n=104–114; K2 n=78–88; KP n=37–41 and AshCam KP 14:50–15:10Z |
| ~05:50 | fountain ~600 ft (caption) | 4759; V1 n=134 |
| 06:02 | fountain ~650 ft; plume 17,000 ft a.s.l. | V1/V2/V3/K2 stills 06:01–06:02; KP n=51 |
| ~07:00 | fountain 500 ft (DU) or ~400 ft (caption) | 4763; V1 n=169–170 |
| 07:30–07:47 | plume under 13,000 ft; fountain ~500 ft | KP n=69–72; V1 n=193 |
| 08:00 | fountain ~300 ft | V1 n=199–200 |
| 09:03 | end | V1 n=231; KP n=87–88 |

---

## 6. Timelapses and webcam archives

**USGS timelapses: yes.** The chronology publishes eight webcam timelapses of episode 55: V1, V2, V3, K2, KW, F1, B1 and KP ([CHRON]). They are listed in §5c and downloaded. There is no separate MKcam timelapse.

**Webcam frame archive (AshCam): yes, with full-resolution stills.** The CAMS page says: "To browse past webcam images, see the USGS Volcano Hazards Program AshCam website: https://volcview.wr.usgs.gov/ashcam-gui/webcam.html". The API behind it was found in the GUI's JavaScript; it is not documented elsewhere.

- **Base URL:** `https://volcview.wr.usgs.gov/ashcam-api/`
- **Camera list:** `GET …/webcamApi/webcams` returns `{webcams:[…], meta}`. Each camera has `webcamCode`, `webcamName`, `firstImageTimestamp`, `lastImageTimestamp`, `imageTotal`, `currentImageUrl` and `externalUrl`. Latitude, longitude, elevation and bearing are 0 for most HVO cameras.
- **Image list:** `GET …/imageApi/webcam?webcamCode=<code>&startTimestamp=<unix s>&endTimestamp=<unix s>&order=ASC&limit=0`. For episode 55 I used `startTimestamp=1792242000` (13:00Z = 03:00 HST) and `endTimestamp=1792265400` (19:30Z = 09:30 HST).
- **What the index JSON contains.** It returns `{images:[…], webcam:{…}, meta:{imageTotal, firstImageTimestamp, lastImageTimestamp, apiUrl, querySec}}`. Each image has `imageId`, `md5`, `webcamCode`, `imageTimestamp` (Unix seconds, UTC), `imageDate` (for example "Sat, 17 Oct 2026 13:00:06 +0000"), `isNighttimeInd`, `interestingCode`, `imageUrl` and `suninfo`. The list came back newest-first even with `order=ASC`, so sort by `imageTimestamp`.
- **Frame URLs and names.** The pattern is `https://volcview.wr.usgs.gov/ashcam-api/images/webcams//<code>/2026/289/<code>-<unix_utc>.jpg`. The day folder is 289 for Oct 17 (day 290 counted from 1, so it is apparently 0-based). The file name is the Unix epoch in UTC, while the burned-in overlay is HST and reads about 0–4 s earlier: `kilauea-kp-cam-1792248605.jpg` is 14:50:05Z (04:50:05 HST) and its overlay says 04:50:01 HST.
- **Camera codes.** `kilauea-v1-cam`, `-v2-`, `-v3-`, `-k2-`, `-kw-`, `-b1-`, `-f1-` and `-kp-cam`. The plume view from Mauna Kea is `mauna-loa-mk2-cam`, which matches the MKcam page view "Mauna Loa's Summit and Northeast Rift Zone from Mauna Kea". This mapping is my inference. `mauna-loa-mk-cam` has 0 images.
- **Cadence.** V1, V2, V3, K2, KW and B1: 2 min. KP and MK2: 5 min. F1: sparse (26 frames in 6.5 h).
- **Retention: about 31 days, rolling** (*inferred*). On 2026-10-26 the earliest image was 2026-09-25 20:37Z and the latest 2026-10-26 20:37Z. The Oct 17 frames will probably disappear after about **2026-11-17**.
- **Licence and credit.** The API JSON has no licence field. Each camera's usgs.gov page states "Sources/Usage: Public Domain." I checked this on the KPcam, V1, V2, V3, K2, KW, B1, F1 and MKcam pages linked from [CAMS]. Credit "USGS Hawaiian Volcano Observatory".

**Downloaded** to `data/raw/usgs_ep55/ashcam/<code>/` (857 frames, 471 MB). All md5 values match the API. Index JSONs are in `ashcam/index/`.

| Camera | Frames | Size |
|---|---|---|
| KP | 78 at 3840×2160 | 47 MB |
| V1 | 195 at 1920×1080 | 58 MB |
| V2 | 194 at 3840×2160 | 168 MB |
| V3 | 195 at 1920×1080 | 45 MB |
| K2 | 195 at 3840×2160 | 136 MB |

**Not downloaded** (index saved; fetch before about Nov 17):

| Camera | Frames | Query URL |
|---|---|---|
| KW | 195 (~1.7 MB each) | `…/imageApi/webcam?webcamCode=kilauea-kw-cam&startTimestamp=1792242000&endTimestamp=1792265400&order=ASC&limit=0` |
| B1 | 195 | `…webcamCode=kilauea-b1-cam…` (same parameters) |
| F1 | 26 | `…webcamCode=kilauea-f1-cam…` |
| MK2 | 77 at 1920×1080 | `…webcamCode=mauna-loa-mk2-cam…` |

The MK2 frames show the Kīlauea plume rising beside Mauna Loa, whose summit could serve as a height reference.

**Other archives.**

- Each webcam page shows a live `M.jpg` and a rolling last-24-hours GIF, for example `https://volcanoes.usgs.gov/observatories/hvo/cams/KPcam/images/KPcam.gif`. Neither covers Oct 17 any more.
- I found no archived Oct 17 recording of the USGS livestreams (https://www.youtube.com/@usgs/streams).

---

## 7. Extras

**Canonical pages to link from bulletins:**

- USGS Kīlauea: https://www.usgs.gov/volcanoes/kilauea
- Kīlauea updates: https://www.usgs.gov/volcanoes/kilauea/volcano-updates
- Eruption information: [ERUP]
- HVO: https://www.usgs.gov/observatories/hvo
- HVO observatory messages: https://www.usgs.gov/observatories/hvo/observatory-messages
- Latest HANS notice for Kīlauea: https://volcanoes.usgs.gov/hans-public/volcano/hi3
- Kīlauea webcams: https://www.usgs.gov/volcanoes/kilauea/webcams

All returned HTTP 200 on 2026-10-26.

**Servicio Geológico Colombiano (Nevado del Ruiz):**

- Weekly bulletin list: https://www2.sgc.gov.co/Noticias/Paginas/Boletines-semanales.aspx. It lists "Boletín semanal de actividad del volcán Nevado del Ruiz del 13 al 19 de octubre de 2026", published 20/10/2026 17:30, level "Amarilla".
- That bulletin's PDF: https://www2.sgc.gov.co/Noticias/boletinesDocumentos/Boletin_semanal_de_actividad_del_volcan_Nevado_del_Ruiz_del_13_de_octubre_al_19_de_octubre_de_2026.pdf (HTTP 200).
- Extraordinary bulletins: https://www2.sgc.gov.co/Noticias/Paginas/Boletines-extraordinarios.aspx
- Monthly bulletins: https://www2.sgc.gov.co/Noticias/Paginas/Boletines-mensuales.aspx
- The SGC "Volcanes" portal is https://www.sgc.gov.co/volcanes. It is a JavaScript app, so I could not verify its contents with curl.
- Caution: the list shows "Verde" for the Ruiz bulletin of 6–12 Oct. Check the PDF before taking an alert level from that column.

**AVO webcams and "Public Domain": no** on AVO's own page.

- https://avo.alaska.edu/webcam/ (title "Alaska Volcano Observatory | Webcams"). Its raw HTML has no match for "public domain", "copyright", "credit", "terms of use" or "citation".
- The USGS-hosted AVO webcam media pages do state it. For example, https://www.usgs.gov/media/webcams/akutan-aksd reads "View from webcam of Akutan [AV06, 1519 ft] by the Alaska Volcano Observatory." and "Sources/Usage: Public Domain."

---

## 8. Discrepancies and open questions

1. **End time.** 9:03 a.m. in all notices and messages, but 9:06 a.m. in the [ERUP] table.
2. **Duration.** "about 6 hours", "5.7 hours" and "just under 6 hours". The computed value is 5 h 44 min.
3. **25,000 ft in metres.** HVO uses 7,500 m (notices), 7,600 m (captions) and 7,000 m (one [DU17] sentence). The exact value is 7,620 m. The summary sentence also drops the word "feet".
4. **VONA onset.** VONA 2026/67 gives "ONSET: 20261017/1430Z" (04:30 HST), not 13:19Z. It probably marks the onset of the ash cloud, but this is unconfirmed.
5. **Fountain at ~7:00.** 500 ft in [DU17], ~400 ft (120 m) in the D. Downs caption.
6. **Caption times versus EXIF.** IMG_4446 is captioned ~5:45 but EXIF says 05:25:53. The B. Wenzel "720 ft" photo has an EXIF time of ~05:53 (camera clock).
7. **Camera geometry is not published.** Position, elevation, bearing and field of view per zoom level are missing for V1, V2, V3, K2 and KP (AshCam gives lat/lon 0). Geometric heights need landmark calibration or a question to askHVO@usgs.gov. The iPhone photos do carry GPS and heading.
8. **Vent elevation on Oct 17.** The latest published value is 1,080 m (Aug 28 survey, through episode 54). No post-episode-55 DEM is published yet.
9. **AshCam expiry.** Fetch the KW, B1, F1 and MK2 frames before about 2026-11-17 if they are wanted.
