# Kīlauea (Hawaiʻi) USGS webcams: research for Volcano Vigil

Research date: 2026-10-26/27 (UTC). All HTTP facts were measured live from Windows/curl during 2026-10-26 20:19 to 2026-10-27 00:20 UTC.
Status context: the Halemaʻumaʻu eruption is paused after episode 55 (2026-10-17, 03:19–09:03 HST, north vent, fountain ~220 m, plume ~7,600 m asl). On 2026-10-26 08:10 HST, HVO forecast episode 56 for **Oct 31 – Nov 6, 2026**, and reported glow from the west and north vents ([S8](https://www.usgs.gov/volcanoes/kilauea/volcano-updates), [S7](https://www.usgs.gov/observatories/hvo/news/photo-video-chronology-kilauea-summit-episode-55-0)).

Labels used below. **published** means the value is stated in the cited USGS source. **measured** means I observed it in my own HTTP requests or images. **estimated** means I derived it; the method and ± uncertainty are given.

---

## Key takeaways

1. **Image URLs.** Every camera's latest image is at `https://volcanoes.usgs.gov/cams/<CAM>/images/M.jpg`. The alternative path `https://volcanoes.usgs.gov/observatories/hvo/cams/<CAM>/images/M.jpg` returns the identical file (same ETag) for all 16 cameras tested. Both return 200, `image/jpeg`, no redirect, and `Access-Control-Allow-Origin: *`.
2. **Update rate.** Public images refresh every **10 min** for all live summit cameras (measured over 66 min). Internally, the cameras capture every **2 min** (5 min for KPcam). The camera pages state no interval.
3. **Burned-in time.** All live cameras burn a timestamp into the image, in **HST** (UTC−10). The sibling `js.js` file gives the capture time as machine-readable text.
4. **License.** Every camera page says, under "Sources/Usage": **"Public Domain."** The fountain-height data release is marked "CC0 1.0 Universal".
5. **Archives.** Past frames are available from:
   - a 24-hour hourly GIF per camera;
   - per-episode timelapse MP4s (2-min cadence) on the USGS S3 bucket;
   - a CC0 USGS data release with fountain-height ground truth and raw timelapse images for episodes 1–50;
   - YouTube livestreams with 12 h of DVR;
   - sparse Wayback Machine captures.
6. **Geometry.** Vent coordinates are **published**: north vent 19.40496 N, 155.29022 W; south vent 19.40412 N, 155.29043 W. Vent elevation is **1,075 m** through episode 50. The B1cam site and the F1cam/KWcam station have published GPS positions. KPcam, K2cam, V1cam and V3cam are estimated.
7. **MVP recommendation.** Use **KPcam** (wide plume camera, ~13.9 km), **K2cam** (mid range, ~1.7 km) and **F1cam** (thermal, sees through fog). Poll each every 60–120 s with `If-None-Match` and de-duplicate by SHA-256.

---

## A. Camera inventory

Sources:
- The USGS Kīlauea webcam list has 18 entries: [S1](https://www.usgs.gov/volcanoes/kilauea/multimedia/webcams). There is no pagination.
- Each camera has its own page at `https://www.usgs.gov/media/webcams/<slug>` ([S2](https://www.usgs.gov/media/webcams/v1cam-kilauea-volcano-hawaii-west-halemaumau-crater)).
- The HVO index at [S5](https://volcanoes.usgs.gov/cams/) also lists **S2cam**, **B2cam** and **PGcam**, which are not on the usgs.gov list.
- Hardware and history come from Patrick et al. 2026, *J. Appl. Volcanol.* 15:10 ([S12](https://doi.org/10.1186/s13617-026-00170-x)).

The latest-image URL for every row is `https://volcanoes.usgs.gov/cams/<CAM>/images/M.jpg`; the `/observatories/hvo/cams/...` path also works. "Status" was measured on 2026-10-26.

| Code | Name and view (verbatim page text, shortened) | Location text | Type | Status / last capture | Image size | Burned-in timestamp |
|---|---|---|---|---|---|---|
| **V1cam** | "[V1cam] Kīlauea volcano, Hawaii (west Halemaʻumaʻu crater)". "Live view of Halemaʻumaʻu crater within Kaluapele (Kīlauea caldera), from the northwest rim of the crater… pan-tilt-zoom model and the view may change depending on activity." | NW rim of Halemaʻumaʻu / caldera | Visible, PTZ (Axis M5525, then M5526, replaced after tephra damage on 2026-03-10 [S12]); also on YouTube | LIVE | 1920×1080 | Yes. Top-left `2026-10-26 10:19:01 HST`. Bottom-right PTZ readout `P: 9594, T: +0.00, Z: 9594 9.6`; the P value appears to mirror Z, so it is not a usable azimuth |
| **V2cam** | "[V2cam] Kīlauea volcano, Hawaii (east Halemaʻumaʻu crater)". "Live view of Kaluapele (Kīlauea caldera) and Halemaʻumaʻu crater, from the northeast rim of the caldera… pan-tilt-zoom" | Volcano House hotel, NE caldera rim [S12] | Visible, PTZ 4K (Axis Q6318) [S12]; YouTube | LIVE | 3840×2160 | Yes. `YYYY-MM-DD HH:MM:SS HST` plus PTZ readout `P: +179.94, T: -0.96, Z: 3350 11.1` |
| **V3cam** | "[V3cam] Kīlauea volcano, Hawaii (south Halemaʻumaʻu crater)". "Last 24 Hours - Live view of Halemaʻumaʻu crater… from the south rim of the crater… pan-tilt-zoom" | South rim. The original unit was destroyed in episode 38 (2025-12-06). The replacement was installed 2025-12-19 "a safer distance to the east" [S12], [S15](https://www.usgs.gov/observatories/hvo/news/photo-video-chronology-december-19-2025-new-v3cam-and-overflight-kilauea) | Visible, PTZ (Axis M5526 originally) [S12]; YouTube | LIVE | 1920×1080 | Yes. Timestamp plus PTZ readout `P: +43.74, T: -4.08, Z: 4846 5.4` |
| **KWcam** | "[KWcam] - Halemaʻumaʻu and down-dropped caldera floor; from the west rim of the summit caldera, looking southeast." "Live Panorama…" | West caldera rim, co-located with F1cam [S11](https://volcanoes.usgs.gov/vsc/file_mngr/file-234/2019%2011-07_HVO_webcam_news_update_PDF.pdf) | Visible, fixed wide-angle 4K (fisheye look; probably Axis P1378 [S12], inferred) | LIVE | 3840×2160 | Yes. Top-left `YYYY-MM-DD HH:MM:SS HST` |
| **F1cam** | "[F1cam] - Kīlauea summit thermal from the west rim of the summit caldera, looking southeast". "upgraded on December 20, 2023, offering a wider field-of-view… Thermal webcams record in Centigrade" | West caldera rim (KWcam station) | **Thermal** (FLIR A65 per [S12]; the 2019–22 unit was an A655sc with 45° HFOV [S10]) | LIVE | 1200×900, including a °C colorbar about 100 px wide on the right | Yes. White box `F1cam: 2026-10-26 10:18:15 HST`. The colorbar range is auto-scaled (15–75 °C on a quiet day, 30–650 °C during fountaining) |
| **K2cam** | "[K2cam] Live Image of Kaluapele (Kīlauea caldera) from Uēkahuna bluff". "…research camera on the bluff at Uēkahuna… pan-tilt-zoom model" | Uēkahuna bluff, former HVO building [S12 Fig. 1B] | Visible, PTZ 4K (probably Axis Q6318 [S12], inferred) | LIVE | 3840×2160 | Yes. Top-left HST timestamp, no PTZ readout |
| **B1cam** | "[B1cam] - Kīlauea caldera down-dropped block and Halemaʻumaʻu". "Live view… from the east rim of the caldera." | E/SE caldera rim near Keanakākoʻi. The data release gives a "B1cam site" with GPS coordinates [S9] | Visible, fixed wide-angle 4K (fisheye) | LIVE | 3840×2160 | Yes. Top-left HST timestamp |
| **KPcam** | "[KPcam] - Kīlauea Summit from Mauna Loa Strip Road". "View from Mauna Loa Strip Road looking at the Kīlauea summit to document volcanic eruption plumes." | South flank of Mauna Loa, about 2,000 m (6,700 ft), looking SE, on a mast about 2 m high [S14](https://www.usgs.gov/observatories/hvo/news/photo-and-video-chronology-webcam-upgrade-kilauea-summit-and-southwest-rift) | Visible, fixed, upgraded 2024-06-25 to a "slightly wider field of view" | LIVE | 3840×2160 | Yes. Top-left HST timestamp |
| **S2cam** *(HVO index only)* | "Live Image of Halemaʻumaʻu from south side of crater". The panorama notes say "on the west rim of Kilauea caldera and looks southeast at the southwest vent" ([S5 panorama](https://volcanoes.usgs.gov/cams/panorama.php?cam=S2cam)) | Contradictory text | Visible, cellular trail camera (Spartan GC-Z4Gc2) | LIVE (captures 10:11:03 and 14:01:04 HST) | 1280×960 | Yes. Bottom banner `10/26/2026 10:11:03` with °F and no time zone (HST per js.js) |
| S1cam | "Live view of the upper Southwest Rift Zone of Kīlauea, view is to the south - temporary webcam image" | Upper SWRZ | Visible, Spartan trail camera (GL-V6EB) | **STALE**: content dated 2026-01-16 21:02 HST, re-uploaded every 10 min | 1376×768 | Yes. Bottom banner `01/16/26 21:02:00` |
| MITDcam | "Live view of Kīlauea's upper Southwest Rift Zone, looking northwest from a seismic station in the Kaʻū Desert" | Kaʻū Desert | Visible | **STALE**: 2026-08-16 07:51 HST (fog), re-uploaded every 10 min | 2688×1520 | Yes. Top-left HST |
| KOcam | "temporary research camera positioned near Maunaulu, looking northwest toward the upper East Rift Zone" | Near Maunaulu | Visible, Spartan GC-G4Gb | LIVE (new content about every 30 min) | 1280×960 | Yes. Bottom banner `10/26/2026 10:11:36`, no time zone |
| MUcam | "temporary research camera located on Mauna Ulu, looking northeast" | Mauna Ulu | Visible | LIVE | 1280×720 | Yes. Small top-left box, HST |
| PEcam | "…northeast of Puʻu ʻŌʻō, on Puʻu Halulu, looking southwest…" | Puʻu Halulu | Visible | LIVE (about 20 min) | 1280×720 | Yes, HST |
| PWcam | "…northwest flank of Puʻu ʻŌʻō, looking southwest…" | Puʻu ʻŌʻō NW flank | Visible | LIVE (about 60 min) | 1280×720 | Yes, HST |
| HPcam | "Lava Flow 61G from Holei Pali… looking east towards Lava Flow 61G and Kalapana" | Holei Pali | Visible | LIVE. The page `<img>` uses `https://volcanoes.usgs.gov/vsc/captures/kilauea/hpcam.jpg`, which also works | 1280×720 | Yes, HST |
| R3cam | "[R3cam] Mobile Cam 3": "…southeast flank of Puʻu ʻŌʻō, looking toward the southeast" | Puʻu ʻŌʻō SE flank | Visible | **STALE**: 2026-09-09 08:20 HST | 1920×1080 | Yes |
| PScam | "…just south of Puʻu ʻŌʻō, looking north…" | South of Puʻu ʻŌʻō | Visible | **STALE**: 2021-08-17 | 1280×720 | Yes. `PScam: Tue Aug 17, 2021 08:31:02` |
| B2cam *(HVO index only)* | "Halemaʻumaʻu and lava lake from the down-dropped block" | In the crater at 933 m [S9] | Visible, Axis P1378 4K [S9] | **STALE**: 2025-04-22 10:42 HST (last frame shows a fountain and lava approaching) | 3840×2160 | Yes |
| PGcam *(HVO index only)* | "Fissures in Leilani Estates from Puʻu Honuaula" | LERZ | Visible | **STALE**: js.js says 2025-08-21; the camera clock reads `02-06-2000` | 1075×605 | Yes, but the clock is wrong |

The [livestream entry](https://www.usgs.gov/media/webcams/kilauea-volcano-live-stream-halemaumau-crater) points to YouTube. The current streams were all **live** on 2026-10-26:
- V1cam: <https://www.youtube.com/watch?v=HggWKlZv9yk> (live since 2026-04-24)
- V2cam: <https://www.youtube.com/watch?v=f9-oSpYpubg> (via <https://url.usgs.gov/v2cam>)
- V3cam: <https://www.youtube.com/watch?v=gXKuUyKt8mc> (via <https://url.usgs.gov/v3cam>)

**Stated update interval.** None of the camera pages states one. The only related text is the disclaimer, "The webcams are operational 24/7…". The HVO paper says snapshots are "commonly one image every 1–10 minutes" and "often delayed by several minutes due to latency in syncing data from HVO to webservers on the continental United States" ([S12](https://doi.org/10.1186/s13617-026-00170-x)).

**Location wording is inconsistent across USGS pages.** For example, the episode 55 chronology captions put KWcam, K2cam and F1cam on the "northwest rim of Halemaʻumaʻu" and B1cam on the "south rim of Halemaʻumaʻu" ([S7](https://www.usgs.gov/observatories/hvo/news/photo-video-chronology-kilauea-summit-episode-55-0)). The camera pages put KWcam and F1cam on the "west rim of the summit caldera" and B1cam on the "east rim of the caldera". The paper's text calls the thermal camera's position the "north rim", while its Fig. 1B places it on the NW rim cluster with KWcam and V1cam.

### License and credit (verbatim)
- Every camera page (all 18 checked), under **"Sources/Usage"**: **"Public Domain."**
- Disclaimer on every page: *"The webcams are operational 24/7 and faithfully record the dark of night if there are no sources of incandescence or other lights. Thermal webcams record heat rather than light and get better views through volcanic gas. At times, clouds and rain obscure visibility. The cameras are subject to sporadic breakdown, and may not be repaired immediately. Some cameras are observing an area that is off-limits to the general public because of significant volcanic hazards."*
- By-lines: "By Hawaiian Volcano Observatory" or "By Kīlauea".
- Fountain-height data release: **"This work is marked with CC0 1.0 Universal"** ([S9](https://www.usgs.gov/data/lava-fountain-heights-and-associated-timelapse-images-summit-eruption-kilauea-volcano-island)).
- Suggested credit: "Image: USGS Hawaiian Volcano Observatory (public domain)". A USGS logo is burned into every frame; mask it before segmentation.

---

## B. HTTP behavior (measured)

**Response headers**, identical for all cameras on both paths:
```
HTTP/1.1 200 OK
Last-Modified: Mon, 26 Oct 2026 20:09:02 GMT
ETag: "34e4a-65ec3e6b6f85b"            # Apache style: hex(size)-hex(mtime µs)
Accept-Ranges: bytes
Content-Length: 216650
Content-Type: image/jpeg
Access-Control-Allow-Origin: *
Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
```

**Other request behavior:**
- There is no `Cache-Control`, no `Expires` and no CDN header.
- `If-None-Match` and `If-Modified-Since` both return **304**.
- Range requests return 206.
- `http://` redirects with 302 to `https://`.
- Query strings are ignored, so `?t=` cache-busting is harmless.
- `www.usgs.gov` pages sit behind CloudFront and return **403** to a bare `Mozilla/5.0` User-Agent; send a full browser User-Agent. `volcanoes.usgs.gov` images have no such check.

**Sibling `js.js`:** `https://volcanoes.usgs.gov/cams/<CAM>/images/js.js` returns, for example, `var datetime = "2026-10-26 14:09:02 (HST)"; var frames = new Array("M");`. This is the capture time and is the cheapest way to detect stale cameras.

### Update cadence

I polled HEAD every ~70 s from 20:21 to 21:27 UTC. On each ETag change I fetched the image and computed its SHA-256.

| Camera | Last-Modified pattern (UTC) | New images in 66 min | Interval |
|---|---|---|---|
| V1cam, V3cam, F1cam | hh:m9:02 (for example 20:19:02, 20:29:02 … 21:19:02) | 7 of 7 new | **10 min** |
| V2cam, KWcam, K2cam, B1cam, KPcam | Batch sync at about hh:m0:05–:19 (20:20:08, 20:30:19, 20:40:09…) | 7 of 7 new | **10 min** |
| MUcam | hh:m6:02 | 7 of 7 | 10 min |
| HPcam | hh:m3:3x | 5 unique in 8 ETag changes | 10 min, with repeats |
| PEcam | 20:01 → 20:21 | 2 | about 20 min |
| PWcam | 20:11:56 → 21:12:00 | 2 | about 60 min |
| KOcam | ETag every 10 min | 3 unique in 7 | about 30 min |
| S1cam, MITDcam | ETag every 10 min | 1 unique (stale) | stale |

**Notes on cadence:**
- **Last-Modified is the HVO file time, not the time the file appears publicly.** At 20:20:13 UTC the V1cam still served LM 20:09:02; by 20:21:17 it served LM 20:19:02. So public availability lags by about 1–2 min. The burned-in capture time is about 1 s before LM for V1/V3/F1, and up to about 10 min before LM for batch-synced cameras.
- **A new ETag does not always mean new content.** Stale or slow cameras are re-copied every 10 min. De-duplicate by SHA-256, or by the `js.js` datetime.
- **Internal capture cadence:**
  - **2 min** for V1, V2, V3, K2, KW, B1 and F1. Frame spacing in the episode 55 timelapses works out to 2.006 min (V1cam: 319 frames from 01:21:03 to 11:59:01 HST).
  - **5 min** for KPcam (155 frames from 01:45 to 14:40 HST).
  - These internal frames are **not** public in real time.

**Timestamp format:**
- Axis cameras: `YYYY-MM-DD HH:MM:SS HST`, top-left, white with an outline. This is local time, HST = UTC−10, with no daylight saving.
- Livestream PTZ cameras (V1, V2, V3) also show `P:, T:, Z:` bottom-right. HVO began stamping PTZ positions in late 2025 [S12].
- Spartan trail cameras: bottom banner `MM/DD/YYYY HH:MM:SS` (S1cam uses `MM/DD/YY`), with no time-zone label.
- USGS logo: bottom-left on all cameras.

---

## C. Archives / past frames

| Source | URL pattern / example | Coverage | Notes |
|---|---|---|---|
| **24-hour animated GIF** (linked as "Link to page with 24-hour animated GIF" on [S3](https://www.usgs.gov/volcanoes/kilauea/summit-webcams)) | `https://volcanoes.usgs.gov/cams/<CAM>/images/<CAM>.gif`, for example [V1cam.gif](https://volcanoes.usgs.gov/cams/V1cam/images/V1cam.gif) | Previous 24 h, **hourly** (24–25 frames, 0.6 s each). For example, V1cam covered 2026-10-25 09:01 to 2026-10-26 09:01 HST | 1920×1080 (F1cam 1200×900), 10–17 MB, regenerated about hourly. Exists for all 16 cameras tested. ffmpeg decodes only the first frame of V1/V3; Pillow reads all 25 |
| **Episode timelapse MP4s** on the USGS S3 bucket, linked from the photo chronology pages | `https://usgs-ocapsv2-public-input-media.s3.us-west-2.amazonaws.com/assets/palladium/production/s3fs-public/media/video/vlc-record-2026-10-19-14h15m07s-V1cam20261017M.avi-.mp4`. The other episode 55 files are listed below this table | Episode 55, 2026-10-17. Spans: V1 01:21–11:59, V2 02:27–10:41, V3 01:05–10:33, K2 02:14–11:14, F1 01:00–12:08, KW 00:46–11:58, B1 01:00–13:50, KP 01:45–14:40 HST | 1920×1080 (F1 1200×900), 10 fps, **2-min frames** (KPcam 5-min). Earlier episodes have similar "Photo & Video Chronology" pages. The internal name `<CAM><YYYYMMDD>M.avi` suggests daily movies exist at HVO but are not public (404) |
| **Fountain-height data release** (CC0): Patrick & Adams 2026, [doi:10.5066/P14MLKCX](https://doi.org/10.5066/P14MLKCX), [metadata XML](https://data.usgs.gov/datacatalog/metadata/USGS.691cfaedd4be021d1d89b467.xml) | ScienceBase item `691cfaedd4be021d1d89b467` | Episodes 1–50 (2024-12-23 to 2026-06-27): manual fountain heights **every minute**, north and south vents, plus raw Reconyx images (2048×1440, 30 s–1 min) from Cameras A–C and B2cam (episode 1) | **Ground truth for validating our heights.** ScienceBase returns a Cloudflare 403 to scripts, so download in a browser |
| Webcam/timelapse data release: Adams et al. 2026, "Timelapse and webcam images of eruptive activity at Kīlauea volcano, 2024 to present", doi:10.5066/P147QBSZ | — | Cited in S9 | **DOI returned 404** on 2026-10-26, so probably not yet public |
| **YouTube livestreams** (V1, V2, V3) | URLs in section A | 12 h DVR rewind, per HVO [S12] | HVO itself archives them with yt-dlp [S12]. Check YouTube's terms before scraping |
| **Wayback Machine** | `https://web.archive.org/cdx/search/cdx?url=volcanoes.usgs.gov/cams/V3cam/images/M.jpg` | Sparse. Captures since 2024: V3cam 1,231 (7 on 2026-10-17, including 06:24 HST mid-episode); V1cam 520 (under the `/observatories/hvo/cams/` path); KWcam 342; KPcam 309; K2cam 54 | Irregular, about 1–10 per day |
| **USGS AshCam API** | Frames named like `kilauea-v1-cam-<epoch>.jpg` | — | Reported by another agent. **Not verified by me** |
| Not available | Directory listings `/cams/<CAM>/` and `/images/` return 403. `M1.jpg`, `T.jpg`, `<CAM>.mp4`, `archive/` return 404. `/vsc/api/hvoWebcamsApi/cams` returns `[]` | — | No numbered or older frames on the live server |

Other episode 55 MP4s use the same prefix: `…-14h15m54s-V2cam…`, `…-14h16m39s-V3cam…`, `…-14h17m18s-K2cam…`, `…-14h17m52s-F1cam…`, `…-14h18m28s-KWcam…`, `…-14h19m08s-B1cam…`, `…-14h25m02s-KPcam20261017M.avi-.mp4`.

---

## D. Snapshots

One image per camera was saved to `data/raw/webcams_snapshot/<CAM>/20261027T0018xxZ.jpg` (UTC download time; capture about 14:00–14:10 HST on Oct 26). Twenty cameras: V1cam, V2cam, V3cam, KWcam, K2cam, B1cam, F1cam, KPcam, S2cam, S1cam, MUcam, PEcam, PScam, PWcam, R3cam, KOcam, MITDcam, HPcam, B2cam, PGcam.

**Conditions at about 14:10 HST:** rain and fog over the summit. Every visible camera is mostly obscured, and only **F1cam (thermal) still shows the crater floor**. The earlier frames, from about 10:20 HST and kept in scratch, were clearer. Descriptions below combine both.

- **V1cam:** zoomed (9.6×) on a degassing vent pit with a steaming rim and yellow sulfur. Close view. The crater floor is the background.
- **V2cam:** zoomed (11.1×) from Volcano House across the caldera. A vent with a white gas plume, the dark tephra cone/shield as the skyline, red oxidized tephra. Fully fogged at 14:09.
- **V3cam:** from the south rim. The vent complex with gas plumes, the Halemaʻumaʻu wall on the right, the caldera rim and the forest skyline beyond.
- **KWcam:** fisheye panorama of the whole Halemaʻumaʻu floor, the far caldera walls and the skyline (rim). The vent plume is at the **far right edge** next to the camera's own rim. Raindrops on the window at 14:10.
- **K2cam:** from Uēkahuna. The overlook platform with visitors in the foreground. The tephra cone with a degassing plume at the image centre, a low Kaʻū/SWRZ skyline, and a large sky area (good for the plume).
- **B1cam:** fisheye from the east/SE rim. The Halemaʻumaʻu floor, the Uēkahuna and west caldera wall on the right, and the vent cone with plume at the **far left edge**.
- **F1cam:** thermal view of the crater floor. Warm recent flows are 30–60 °C with cold sky. During episode 55 the fountain appears **at the right edge**, saturated on a 30–650 °C scale.
- **KPcam:** wide view from Mauna Loa. The ʻōhiʻa scrub foreground and a distant flat skyline, about 70% of the frame is sky. During episode 55 at 06:00 HST, the fountain sits on the skyline and the whole eruption column is in frame. Fully clouded at 14:10.
- **S2cam:** trail camera. Vents with gas, the cone on the left, sky. Foggy.
- **Stale cameras:** S1cam (night IR, January), MITDcam (fog, August), R3cam (fog/droplets, September), PScam (2021), B2cam (April 2025 fountain frame), PGcam (clock 2000).
- **ERZ cameras:** MUcam (Mauna Ulu cones and Puʻu ʻŌʻō), PEcam and PWcam (Puʻu ʻŌʻō flanks), HPcam (Holei Pali to the coast), KOcam (lava field and forest). No activity.

---

## E. Geometry for height estimation

### Vents and elevations

| Item | Value | Label / source |
|---|---|---|
| **North vent** | **19.40496 N, 155.29022 W** | published "as of August 2026, from DEMs (Carr et al. 2026)"; vents moved less than 20 m in a year ([S9 metadata](https://data.usgs.gov/datacatalog/metadata/USGS.691cfaedd4be021d1d89b467.xml)) |
| **South vent** | **19.40412 N, 155.29043 W** | published, same source |
| West vent (third vent, glowing on Oct 26) | 19.40443 N, 155.29080 W | **estimated ±20 m**: position of the third "earlier eruptive vent" circle on the 2026-09-23 HVO map relative to the N/S vents. The map's N–S circle spacing (90.5 px = 95.6 m) and bearing (13.4° vs 13.3°) match the published coordinates ([S17](https://www.usgs.gov/media/images/september-23-2026-new-kilauea-summit-vents-and-lava-flows-september-14-16)) |
| New NW-wall vents 1–6 (2026-09-14/16) | about 320 m N of the north vent, along the NW wall | estimated from the same map. Average vent elevation **1,055 m** is published [S17] |
| **Vent elevation** | **1,075 m (3,525 ft)** | published through episode 50 (DEM of 2026-06-30) ([S16](https://www.usgs.gov/maps/july-10-2026-kilauea-summit-eruption-lava-thickness-through-episode-50)) |
| Vent level below crater rim | 65 m, so the **crater rim at the vents ≈ 1,140 m** | published 65 m; the 1,140 m is derived |
| Vent height above surrounding lava | 50 m | published [S16] |
| Tephra cone peak (on the west caldera rim) | **1,185 m** (45 m above the crater rim). Location: W/SW of the vents, coordinates not published | published [S16] |
| Average crater-floor lava | 1,007 m; maximum thickness 170 m at the north vent | published [S16] |
| Eruption column, episode 55 | about 25,000 ft (7,600 m) asl, about 6.5 km above the vent; fountain max 220 m | published [S7], [S8] |

### Cameras: position, distance and bearing to the north vent

Distances are haversine on a sphere with R = 6,371,008.8 m. Ground elevations come from [USGS EPQS 3DEP](https://epqs.nationalmap.gov/v1/json). As a check, EPQS gives 1,139.2 m at the F1cam point (published 1,141.16 m) and 1,109.1 m at the B1cam site (published 1,106.5 m), so it agrees within about 3 m.

| Camera | lat, lon | Ground elevation (m) | Label | → N vent | → S vent | → W vent (est.) |
|---|---|---|---|---|---|---|
| **KPcam** | 19.492709, −155.385281 | 2,032 (EPQS); camera on about 2 m mast | **estimated ±500 m**: published "south flank of Mauna Loa, ~2,000 m (6,700 ft)", reached "along the Mauna Loa trail" [S14]; placed at the OSM Mauna Loa Lookout / trailhead ([node 5061563731](https://www.openstreetmap.org/node/5061563731)) | **13,948 m @ 134.4°** | 13,998 m @ 134.7° | 13,946 m @ 134.7° |
| **K2cam** | 19.4200, −155.2889 | 1,243 (EPQS) | **estimated ±75 m**: "bluff at Uēkahuna" / "former HVO building" [S2, S12 Fig. 1B]. The image shows the Uēkahuna overlook platform (OSM [node 582340071](https://www.openstreetmap.org/node/582340071), 19.419387, −155.289021) in the foreground looking S, so the camera is just N of it | **1,678 m @ 184.7°** | 1,773 m @ 185.2° | 1,743 m @ 186.6° |
| **F1cam** (and KWcam, co-located) | 19.407494, −155.291750 | 1,141.16 ground; camera 1.0 m above ground | **published** 2019–2022, Trimble GPS ±20 cm ([S10 metadata](https://data.usgs.gov/datacatalog/metadata/USGS.61fc8cd2d34e622189cc1624.xml)). KWcam is co-located [S11]; the laser rangefinder is on the "KWcam station" [S13]. **Assumed unchanged** after the 2023 upgrade (±30 m) | **324 m @ 150.3°** | 400 m @ 159.7° | 355 m @ 163.7° |
| **B1cam** | 19.402379, −155.267539 | 1,106.5 (published) | **published** for "Camera C: South rim – B1cam site" (Trimble ±0.3 m) [S9]. B1cam assumed at the same site (±20 m) | **2,396 m @ 276.9°** | 2,409 m @ 274.6° | 2,450 m @ 275.3° |
| V1cam | 19.4085, −155.2912 | 1,130 (EPQS) | **estimated ±150 m**: NW-rim cluster in Patrick et al. 2026 Fig. 1B, just NE of the KWcam/F1cam station | ≈407 m @ 165° | ≈494 m @ 171° | ≈455 m @ 175° |
| V3cam (current) | 19.4002, −155.2830 | 1,118 (EPQS) | **estimated ±250 m**: "south rim… a safer distance to the east" of the destroyed unit, which was 630 m from the vent and sat at about 19.4006, −155.2853 by Fig. 1B [S12] | ≈924 m @ 305° | ≈893 m @ 299° | ≈944 m @ 300° |
| V2cam | 19.428712, −155.258324 | 1,208 (EPQS) | **estimated ±50 m**: "at the Volcano House hotel" [S12]; OSM Volcano House node | ≈4,262 m @ 232° | ≈4,338 m @ 231° | ≈4,346 m @ 232° |

As a check, the same formulas reproduce the published camera-to-vent distances: Camera A ≈640 m (computed 620–682 m), Camera B ≈967 m (958–986 m) and the B1cam site ≈2.4 km (2,396–2,409 m) [S9].

### Reference points, hardware and field of view

- **KPcam**
  - The vent and fountain base are at −3.9° elevation angle. A 7.6 km asl plume top would be at +21.8°.
  - The sea-horizon dip from 2,032 m is about 1.4° (geometric). Useful for roll and tilt checks.
  - Earth curvature over 14 km is about 15 m (about 13 m with refraction). Negligible.
  - HFOV: **unknown**. Model not published; only "slightly wider field of view" after the 2024 upgrade.
- **K2cam**
  - The tephra cone peak at 1,185 m [S16] and the Uēkahuna platform at 1,241 m are visible.
  - The fountain base is at −5.8°; 1 km above the vent would be at +26°.
  - PTZ: the view changed between Oct 17 (fountain right of centre) and Oct 26 (cone centred).
  - HFOV: unknown.
- **F1cam**
  - The far east rim / B1cam site (published, 2.6 km at bearing ≈103°) is in view.
  - The 2019–22 unit used azimuth 93°, dip 23.7°, 45° HFOV, 640×480 [S10]. The current unit has a wider FOV and an unknown HFOV.
- **B1cam**
  - The Uēkahuna bluff (≈1,241 m) is on the right-hand skyline. The KWcam/F1cam station (1,141 m) is on the far west rim.
  - It is a fisheye and the vents sit at the edge, so it needs undistortion.
- **Reconyx Hyperfire 2 timelapse cameras** (HVO measurement cameras, not public in real time)
  - HFOV 38.3° ± 0.1°, 2048×1440 [S9].
  - Published pixel footprints: Cam A 0.2170 m, Cam B 0.3278 m, Cam C 0.8204 m.
  - Formula: `m_per_px = 2·d·tan(HFOV/2)/W`. This is the same approach as ours, so it can be reused for any calibrated fixed camera.

Two caveats from S9:
1. Inclined fountains can shift the top laterally by 100 m or more (for example episode 30), which breaks the vertical-column assumption.
2. Choosing the base and top by hand is subjective: about 4.5 m mean difference between observers.

---

## F. Recommendation for the MVP

| Priority | Camera | Why | Poll |
|---|---|---|---|
| 1 | **KPcam**: `https://volcanoes.usgs.gov/cams/KPcam/images/M.jpg` | Fixed and wide. HVO uses it "to evaluate how high eruptive plumes are extending" [S14]. The whole column (to about 7.6 km asl) is in frame. At about 13.9 km distance, a ±500 m position error is only about ±4%. 4K | Every 60–120 s with `If-None-Match`. New image every 10 min, published at about hh:m0:05–:20 UTC. Process the 304/200 delta only |
| 2 | **K2cam**: `https://volcanoes.usgs.gov/cams/K2cam/images/M.jpg` | Mid range (1.68 km). Fountain, cone (1,185 m reference) and lower plume in a 4K frame with plenty of sky. Position estimated ±75 m (±4.5% on distance). PTZ, so re-check framing each episode | Same, 60–120 s (10-min cadence, batch sync) |
| 3 | **F1cam** (thermal): `https://volcanoes.usgs.gov/cams/F1cam/images/M.jpg` | Sees through fog and rain, when all visible cameras were blind at 14:10 HST today. Detects whether fountaining is on or off, and lava coverage. The fountain sits at the right edge, so it is **not** for height. Position published | 60–120 s (new image at about hh:m9:02 + 1–2 min) |
| Alternates | **B1cam** (published site, 2.4 km, fixed 4K fisheye, vents at the left edge, needs undistortion); **V3cam** / **V1cam** (closest, 1080p PTZ with burned-in zoom readout; positions only ±150–250 m) | Cross-checks and visual close-ups | 10-min cadence |

**Pipeline tips:**
- Read the capture time from `js.js`, or OCR the burned-in HST stamp. Convert with HST = UTC−10.
- De-duplicate by hash.
- Mask the USGS logo and the PTZ text.
- For KPcam, convert pixel rows to elevation angles with `h = d·(tanθ_top − tanθ_base)`. Do not use a linear m/px value: the top is about 22° above the horizontal.
- For validation, back-test on the episode 55 MP4s and on the per-minute fountain heights in doi:10.5066/P14MLKCX (episodes 1–50).

## Open questions
1. KPcam's exact position, model and HFOV are not published (±500 m).
   - Fix: calibrate from two known bearings, such as the vent and the Uēkahuna bluff, or from published fountain heights on archived frames.
2. K2cam, V1cam and V3cam positions are estimated; the PTZ cameras change zoom and framing.
3. Whether F1cam and KWcam still sit at the 2019 GPS point after the 2023 upgrade. Fig. 1B suggests yes, but the 2026 paper's text says "north rim".
4. The Adams et al. 2026 webcam data release (doi:10.5066/P147QBSZ) does not resolve yet. ScienceBase blocks scripted downloads.
5. The USGS AshCam API (archived `kilauea-v1-cam-<epoch>.jpg` frames) was reported by another agent and is not verified here.

## Sources
- S1 Kīlauea webcams list: https://www.usgs.gov/volcanoes/kilauea/multimedia/webcams
- S2 Camera pages: `https://www.usgs.gov/media/webcams/<slug>`, for example https://www.usgs.gov/media/webcams/kpcam-kilauea-summit-mauna-loa-strip-road
- S3 Summit webcams (GIF and YouTube links): https://www.usgs.gov/volcanoes/kilauea/summit-webcams
- S5 HVO cams index: https://volcanoes.usgs.gov/cams/ ; panorama pages `https://volcanoes.usgs.gov/cams/panorama.php?cam=<CAM>`
- S7 Episode 55 chronology: https://www.usgs.gov/observatories/hvo/news/photo-video-chronology-kilauea-summit-episode-55-0
- S8 Kīlauea updates: https://www.usgs.gov/volcanoes/kilauea/volcano-updates
- S9 Patrick & Adams 2026 data release: https://www.usgs.gov/data/lava-fountain-heights-and-associated-timelapse-images-summit-eruption-kilauea-volcano-island ; https://data.usgs.gov/datacatalog/metadata/USGS.691cfaedd4be021d1d89b467.xml
- S10 Thermal camera data release 2019–2022 metadata: https://data.usgs.gov/datacatalog/metadata/USGS.61fc8cd2d34e622189cc1624.xml
- S11 HVO 2019 webcam update: https://volcanoes.usgs.gov/vsc/file_mngr/file-234/2019%2011-07_HVO_webcam_news_update_PDF.pdf
- S12 Patrick et al. 2026, "Seeing is believing": https://doi.org/10.1186/s13617-026-00170-x
- S13 Younger et al. 2025, laser rangefinders: https://doi.org/10.1186/s13617-025-00152-5
- S14 KPcam upgrade, 2024-06-27: https://www.usgs.gov/observatories/hvo/news/photo-and-video-chronology-webcam-upgrade-kilauea-summit-and-southwest-rift
- S15 New V3cam: https://www.usgs.gov/observatories/hvo/news/new-v3cam-provides-another-livestream-view-halemaumau ; https://www.usgs.gov/observatories/hvo/news/photo-video-chronology-december-19-2025-new-v3cam-and-overflight-kilauea
- S16 Episode 50 lava thickness map: https://www.usgs.gov/maps/july-10-2026-kilauea-summit-eruption-lava-thickness-through-episode-50
- S17 Sept 14–16 vents map: https://www.usgs.gov/media/images/september-23-2026-new-kilauea-summit-vents-and-lava-flows-september-14-16
- HVO webcam API (empty): https://volcanoes.usgs.gov/vsc/api/hvoWebcamsApi/
- USGS EPQS: https://epqs.nationalmap.gov/v1/json ; OSM nodes 582340071 and 5061563731
