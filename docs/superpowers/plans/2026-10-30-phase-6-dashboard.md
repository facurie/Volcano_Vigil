# Phase 6: Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a local web dashboard, `vigil-web`, that shows Volcano Vigil live and replays episode 55: camera status, the current frame with SAM's masks, the plume-height record against HVO's values, the map of what the cameras see, the bilingual bulletins and the agent's trace. In a replay it shows only what existed at the simulated time.

**Architecture:**
- `vigil/web/views.py`: a `Scene` is one database (the live one, or a replay's) seen at one clock. Every query is bounded by that clock: frames captured by then; detections and measurements of SAM runs whose every frame was captured by then; bulletins and agent runs whose clock is not after it; HVO's values once HVO had given them. Pure functions over SQLite, tested without HTTP.
- `vigil/web/app.py`: a FastAPI app factory. Every `/api` endpoint takes `replay` (episode key, absent for live) and `at` (a UTC time), builds the `Scene` through one dependency with a read-only connection, and returns JSON or a JPEG. `vigil-web` runs it with uvicorn.
- `vigil/web/static/`: one page, no build step. ES modules, Leaflet 1.9.4 from unpkg with SRI, IBM Plex from Google Fonts. Model text reaches the DOM only through `textContent`.

**Tech stack:** Python 3.12, FastAPI 0.162 and uvicorn 0.54 (current on 2026-10-30), Starlette's `TestClient` (httpx is already installed), SQLite, Pillow, numpy. Browser: vanilla JS modules, SVG, Leaflet 1.9.4, USGS The National Map imagery tiles. JS helper tests: `node --test` (Node 24), run from pytest.

---

## Facts this plan relies on (measured while planning, 2026-10-30)

- **Data on disk.**
  - Replay database `data/replay/ep55/vigil.sqlite`: 468 frames (KP 78, K2 195, V1 195), 63 tracking runs, 804 detections, 492 measurements (all on KPcam: plume 75 frames × 5 metrics, incandescence 39 × 3), 7 agent runs with 113 steps, 7 bulletins, 78 replay ticks. `timeline.json` (84 KB) and `spark_phases.json` sit next to it.
  - Live database `data/vigil.sqlite` (the configured `DB_PATH`, which exists): 1,011 frames, the newest on Oct 27. Live mode will show every camera as stale until `vigil-ingest` runs again; that is correct.
  - KP and K2 frames are 3840×2160 JPEGs (~0.6–0.7 MB); V1 is 1920×1080. The browser must get scaled copies.
- **`tracking_runs.window_end` is the capture time of the window's last frame** (e.g. `14:55:05Z` for KP, `14:58:02Z` for K2), not `hh:59:59`. A detection depends on every frame of its run, so the dashboard shows a detection, and the measurements made from it, only when `window_end <= clock`. That is the exact "nothing after the clock" rule for SAM output.
- **Rendering a frame for the browser** (KP frame 29 with 1 plume mask; K2 frame 142 with 3 masks), Pillow `draft` + LANCZOS to 1280 px + box-sized mask decode + `draw_layers` + JPEG q82: about 120 ms and 80–100 KB per image. No cache is needed.
- **KPcam plume top altitude in the replay:** 75 frames from 13:15Z to 19:25Z, 2,199–7,732 m. A fixed 0–9 km axis holds it.
- **Bulletin evidence overlays** are stored relative to the data dir (`replay/ep55/bulletins/run2/frame29_plume.jpg`), always inside a `bulletins` folder.
- **Leaflet 1.9.4 SRI** (computed from the unpkg files): CSS `sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=`, JS `sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=`.
- **USGS The National Map tiles answer** (public domain): `https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}` (note y before x) returned 200 `image/jpeg` over the caldera at z13.
- **Headless screenshots work** with Edge (PowerShell, a separate profile directory is required):
  ```powershell
  $S = "<scratchpad>"; Start-Process -FilePath "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" -ArgumentList "--headless=new","--disable-gpu","--hide-scrollbars","--user-data-dir=$S\edge-profile","--window-size=1440,2000","--virtual-time-budget=10000","--screenshot=$S\shot.png","http://127.0.0.1:8765/#mode=replay&at=2026-10-17T15:00:00Z" -Wait -NoNewWindow
  ```
- `fastapi` and `uvicorn` are not installed yet. Node v24.12.0 is (ESM syntax in `.js` files is detected without a `package.json`).
- The GitHub repo is still `facurie/vigia-andino` (the rename is pending on the author); `git push origin` works.

## Design direction (interface-design)

**Who and what.** A hackathon judge, or someone on the Big Island checking the summit, opens one link for a few minutes. They must *see the agent watch the eruption and get it right*: frames with SAM's masks, numbers with ± σ, the bulletin in their language, and the official values beside ours. The author records the 3-minute video from the replay.

**Feel.** An observatory's night shift: dark like the summit at 04:00 when the fountain lights the plume, calm and exact like a survey instrument. Not a SaaS dashboard.

- **Domain:** helicorder drum, line of sight, vent, plume column, lava fountain, HST night shift, survey uncertainty (± σ on everything), Moon calibration, VONA notices (whose alert colours we must NOT imitate).
- **Color world:** basalt (warm black of fresh lava), tephra and ash greys, steam white, incandescent lava orange, the blue-white of the steam column, glow yellow, sulphur.
- **Signature:**
  1. **The drum.** The plume-height chart is a helicorder drum on the episode's time axis: it inks only up to the clock and leaves the future as blank paper; HVO's values appear on it only once HVO had stated them.
  2. **The line of sight.** The map draws each camera's position as a circle of its σ, its sightline to the vent, the plume's measured side *across* KPcam's sightline (one camera sees only that component) and the model wind beside it.
  3. **± σ everywhere.** Every number carries its uncertainty in a quieter weight.
- **Rejecting:**
  - KPI tile row → one hero readout under the frame.
  - OSM street tiles → USGS imagery (public domain), dimmed.
  - Green/yellow/red status → the target colours (what is visible: plume blue, glow yellow, fountain orange) plus a word. Never anything that reads as an alert level.
  - Sidebar navigation → one console screen with a Live / Replay switch in the top bar.
- **Tokens:** `--basalt #100e0d` (page), `--basalt-1 #161311` (panels), `--basalt-2 #1d1916` (raised), `--well #0a0908` (insets, the drum's future), hairlines `rgba(236,226,212,.08/.14)`; ink `--steam #ede4d6`, `--ash #b4aa9c`, `--tephra #8d8377`, `--cinder #5a524a`; the one accent `--lava #f25820` (also the fountain on dark surfaces); data colours on dark surfaces `--plume #259ed6`, `--glow #b68c00`, and `--lehua #c3518d` for HVO's official values (the ʻōhiʻa lehua blossom, the first plant on new lava); `--sulfur #d8b04a` for the notice only. The masks drawn on the frames keep their overlay colours (`vigil.agent.bulletin.COLORS`), and only the keys under the frame use them: `--mask-plume #50c8ff`, `--mask-fountain #ff5a1e`, `--mask-glow #ffd200`.
- **Chart colours, validated** with the dataviz validator on the panel surface `#161311`, dark mode, all pairs: plume `#259ed6`, HVO `#c3518d`, fountain `#f25820` pass every check (lightness band 0.48–0.67, chroma, CVD worst ΔE 11.0 deutan, normal-vision worst 16.2, contrast ≥ 3:1). The overlay colours fail the dark band (too light: L 0.79 and 0.88), hence the separate tokens. Glow (`#b68c00`) cannot share a figure with the fountain (deutan ΔE 0.6), so the drum's strips do not use it.
- **Type:** IBM Plex Sans (body 14/1.5), IBM Plex Sans Condensed (labels: 11px/600, uppercase, tracked), IBM Plex Mono (every time and number, tabular). Hierarchy by weight and ink before size. One hero figure: the plume top, 48px/600.
- **Depth and density:** borders-only (hairlines), dark only; 4px base unit, 16px panel padding, 16px gaps; radius 4px controls, 6px panels.

## File map

- Modify `vigil/agent/render.py`: make `_texts`, `_header`, `_rows` public as `texts`, `table_header`, `table_rows` (the feed shows exactly the published tables).
- Modify `vigil/agent/tools.py` and `vigil/pipeline.py`: `calibrated(calibration, camera_id, when)` takes the `Calibration` instead of a `ToolContext`.
- Modify `vigil/replay.py`: `replay_dir(data_dir, episode)`, used by `main` and the web app.
- Modify `vigil/db.py`: `connect_readonly(path)`.
- Modify `vigil/overlay.py`: `draw_layers(..., legend=True)`.
- Create `vigil/web/__init__.py`, `vigil/web/views.py`, `vigil/web/app.py`.
- Create `vigil/web/static/index.html`, `vigil/web/static/css/app.css`, `vigil/web/static/js/{lib,dom,api,main,viewer,feed,trace,drum,map,results}.js`.
- Modify `pyproject.toml`: dependencies `fastapi`, `uvicorn`; script `vigil-web`; package data for `vigil/web/static`.
- Tests: `tests/test_web_views.py`, `tests/test_web_app.py`, `tests/test_web_static.py`, `tests/js/lib.test.mjs`; additions to `tests/test_db.py` (new), `tests/test_overlay.py`, `tests/test_replay.py`.

Execution split: Tasks 1–5 (Python) can go to one implementer in order; Tasks 6–8 (browser) to a second, in order; Task 9 is the orchestrator's.

---

### Task 1: Small refactors the dashboard reuses

**Files:**
- Modify: `vigil/agent/render.py`, `vigil/agent/tools.py:245-254` (`calibrated`) and its call in `list_cameras_status`, `vigil/pipeline.py:197`, `vigil/replay.py` (`main`), `vigil/db.py`, `vigil/overlay.py`
- Test: `tests/test_db.py` (create), `tests/test_overlay.py`, `tests/test_replay.py`, `tests/test_render.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_db.py`:
```python
import sqlite3

import pytest

from vigil import db


def test_a_read_only_connection_reads_rows_but_cannot_write(tmp_path):
    path = tmp_path / "vigil.sqlite"
    db.connect(path).close()
    conn = db.connect_readonly(path)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM frames").fetchone()["n"] == 0
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM frames")
    finally:
        conn.close()


def test_a_read_only_connection_never_creates_a_database(tmp_path):
    with pytest.raises(FileNotFoundError):
        db.connect_readonly(tmp_path / "missing.sqlite")
    assert not (tmp_path / "missing.sqlite").exists()
```
Note: with `PRAGMA query_only=ON` SQLite raises `sqlite3.OperationalError: attempt to write a readonly database`.

Append to `tests/test_overlay.py` (it already imports `numpy as np`, `Image` and `Layer`/`draw_layers`; add any import it lacks):
```python
def test_without_a_legend_the_frame_keeps_its_size_even_with_layers():
    image = Image.new("RGB", (40, 30), (90, 90, 90))
    mask = np.zeros((30, 40), dtype=bool)
    mask[10:20, 10:20] = True

    out = draw_layers(image, [Layer(mask, (80, 200, 255), "plume")], legend=False)

    assert out.size == (40, 30)
    assert out.getpixel((15, 15)) != (90, 90, 90)
```

Append to `tests/test_replay.py` (add `from pathlib import Path` and `replay_dir` to the `vigil.replay` import):
```python
def test_an_episodes_replay_lives_in_its_own_folder_of_the_data_dir():
    assert replay_dir(Path("data"), EP55) == Path("data") / "replay" / "ep55"
```

Append to `tests/test_render.py` (add `table_header, table_rows, texts` to its `from vigil.agent.render import ...` line; `bulletin()` is the module's own helper):
```python
def test_the_public_table_helpers_give_the_markdown_tables_cells():
    b = bulletin()
    markdown = to_markdown(b, "es")

    assert "| " + " | ".join(table_header("es")) + " |" in markdown
    assert table_rows(b, "es")[0][2] == "6.951 ± 429 m"
    assert all(cell in markdown for cell in table_rows(b, "es")[0])
    assert texts(b, "en") == (b.headline_en, b.body_en, b.disclaimer_en)
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_db.py tests/test_overlay.py tests/test_replay.py tests/test_render.py`
Expected: FAIL (`connect_readonly`, `legend`, `replay_dir`, `table_header` do not exist).

- [ ] **Step 3: Implement**

`vigil/db.py`, after `connect`:
```python
def connect_readonly(path: str | Path) -> sqlite3.Connection:
    """A connection that cannot write, for readers such as the dashboard. The database must exist: this never
    creates one. Usable from another thread than the one that opened it (one request at a time)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA query_only=ON")
    return conn
```

`vigil/overlay.py`: add a keyword `legend: bool = True` to `draw_layers`, document it in the docstring ("`legend=False` draws no strip at all, for pages that show their own legend"), and end with:
```python
    rows = max(len(layers), min_legend_rows) if legend else 0
    return _add_legend(frame, layers, rows) if rows else frame
```

`vigil/replay.py`: add
```python
def replay_dir(data_dir: Path, episode: Episode) -> Path:
    """Where an episode's replay keeps its database, timeline, report and bulletins."""
    return data_dir / "replay" / f"ep{episode.key}"
```
and in `main` replace `out_dir = settings.data_dir / "replay" / f"ep{episode.key}"` with `out_dir = replay_dir(settings.data_dir, episode)`.

`vigil/agent/render.py`: rename `_texts` → `texts`, `_header` → `table_header`, `_rows` → `table_rows` (definitions and every use in the module). No behaviour change.

`vigil/agent/tools.py`: change `calibrated` to take the calibration:
```python
def calibrated(calibration: Calibration, camera_id: str, when: datetime) -> bool:
    """Whether a preset covers the camera at `when` and its references fix the view (a two-sample solve)."""
    preset = calibration.preset_for(camera_id, when)
    if preset is None:
        return False
    try:
        sample_geometry(calibration, camera_id, preset, samples=2)
    except ValueError:
        return False
    return True
```
Update its callers: in `list_cameras_status`, `"calibrated": calibrated(ctx.calibration, camera.id, ctx.now)`; in `vigil/pipeline.py`, `calibrated(ctx.calibration, camera.id, start)`. Search for any other caller (`grep -rn "calibrated(" vigil tests`) and update it. Import `Calibration` in `tools.py` if it is not imported yet.

- [ ] **Step 4: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: all pass (492 before this phase, plus the new ones).

- [ ] **Step 5: Commit**

```bash
git add vigil/db.py vigil/overlay.py vigil/replay.py vigil/agent/render.py vigil/agent/tools.py vigil/pipeline.py tests/test_db.py tests/test_overlay.py tests/test_replay.py tests/test_render.py
git commit -m "Add a read-only connection, legend-free overlays and the replay folder helper for the dashboard"
```

---

### Task 2: The dashboard's scene: cameras and frames at a clock

**Files:**
- Create: `vigil/web/__init__.py` (one docstring line), `vigil/web/views.py`
- Test: `tests/test_web_views.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_web_views.py`:
```python
import json
from datetime import timedelta

import pytest

from test_agent_tools import SOURCES, T0, add_frame, add_measurement, add_run, add_track, detection_ids
from test_metrics import kp_calibration
from vigil.ingest.store import FrameStore
from vigil.timeutil import to_iso
from vigil.web import views
from vigil.web.views import Scene

M = timedelta(minutes=1)


@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def scene(conn, tmp_path, clock=T0, episode=None, cameras=("kilauea-kp", "kilauea-k2")):
    return Scene(conn=conn, clock=clock, data_dir=tmp_path, sources=SOURCES, calibration=kp_calibration(),
                 volcano="kilauea", cameras=cameras, episode=episode)


def test_a_scene_needs_a_clock_with_a_time_zone(conn, tmp_path):
    with pytest.raises(ValueError, match="time zone"):
        scene(conn, tmp_path, clock=T0.replace(tzinfo=None))


def test_camera_status_reads_each_cameras_latest_frame_by_the_clock(conn, store, tmp_path):
    add_frame(conn, store, "kilauea-kp", -10)
    add_frame(conn, store, "kilauea-kp", 5, usable=False, reasons=["low_visibility"])  # after the clock
    add_frame(conn, store, "kilauea-k2", -3, usable=False, reasons=["night"])

    kp, k2 = views.camera_status(scene(conn, tmp_path))

    assert (kp["camera_id"], kp["condition"], kp["latest"]["minutes_ago"]) == ("kilauea-kp", "usable", 10.0)
    assert (kp["frames_last_hour"], kp["usable_last_hour"]) == (1, 1)
    assert kp["calibrated"] is True
    assert kp["position"]["lat"] == kp_calibration().cameras["kilauea-kp"].position.lat
    assert (k2["condition"], k2["reasons"], k2["calibrated"], k2["position"]) == ("night", ["night"], False, None)


@pytest.mark.parametrize("minutes, usable, reasons, expected", [
    (-5, 1, [], "usable"), (-5, None, [], "unchecked"), (-31, 1, [], "stale"), (-5, 0, ["night"], "night"),
    (-5, 0, ["low_visibility"], "fog"), (-5, 0, ["frozen"], "frozen"),
    (-5, 0, ["timestamp_mismatch"], "clock_mismatch"), (-5, 0, ["low_visibility", "night"], "night"),
    (-5, 0, [], "rejected")])
def test_a_cameras_condition_comes_from_its_latest_frame(minutes, usable, reasons, expected):
    assert views.condition(to_iso(T0 + minutes * M), usable, reasons, T0) == expected


def test_a_camera_without_frames_has_no_frames():
    assert views.condition(None, None, [], T0) == "no_frames"


def test_a_detection_appears_once_every_frame_its_sam_run_saw_was_captured(conn, store, tmp_path):
    a, b, c = (add_frame(conn, store, "kilauea-kp", minutes) for minutes in (-20, -10, 5))
    add_track(conn, add_run(conn, "kilauea-kp", "plume", [a, b]), [a, b])
    add_track(conn, add_run(conn, "kilauea-kp", "fountain", [b, c]), [b, c])  # its window ends after the clock

    now = views.latest_frames(scene(conn, tmp_path), "kilauea-kp")
    later = scene(conn, tmp_path, clock=T0 + 5 * M)

    assert now["latest"]["frame_id"] == b and now["tracked"]["frame_id"] == b
    assert [d["target"] for d in now["latest"]["detections"]] == ["plume"]
    assert views.latest_frames(later, "kilauea-kp")["latest"]["frame_id"] == c
    assert sorted(d["target"] for d in views.frame(later, b)["detections"]) == ["fountain", "plume"]


def test_a_visible_detection_carries_its_box_and_measurements(conn, store, tmp_path):
    a = add_frame(conn, store, "kilauea-kp", -10)
    track = add_track(conn, add_run(conn, "kilauea-kp", "plume", [a]), [a])
    add_measurement(conn, a, "top_altitude", 6951.5, 429.4, detection_id=detection_ids(conn, track)[0])

    (detection,) = views.latest_frames(scene(conn, tmp_path), "kilauea-kp")["latest"]["detections"]

    assert detection["box"] == [60, 60, 120, 150] and detection["target"] == "plume"
    assert detection["measurements"] == {"top_altitude": {"value": 6951.5, "sigma": 429.4, "unit": "m"}}


def test_a_camera_without_visible_detections_has_no_tracked_frame(conn, store, tmp_path):
    add_frame(conn, store, "kilauea-kp", -10)

    shown = views.latest_frames(scene(conn, tmp_path), "kilauea-kp")

    assert shown["tracked"] is None and shown["latest"]["detections"] == []


def test_a_camera_the_scene_does_not_show_is_unknown(conn, tmp_path):
    with pytest.raises(LookupError):
        views.latest_frames(scene(conn, tmp_path), "kilauea-v2")


def test_a_frame_captured_after_the_clock_does_not_exist(conn, store, tmp_path):
    later = add_frame(conn, store, "kilauea-kp", 5)

    assert views.frame(scene(conn, tmp_path), later) is None
    assert views.frame(scene(conn, tmp_path, clock=T0 + 5 * M), later)["captured_at"] == to_iso(T0 + 5 * M)


def test_the_frame_strip_lists_each_frame_since_with_its_verdict_and_visible_targets(conn, store, tmp_path):
    old, a, b, c = (add_frame(conn, store, "kilauea-kp", m, usable=m != -10) for m in (-90, -20, -10, 5))
    add_track(conn, add_run(conn, "kilauea-kp", "plume", [a, b]), [a])
    add_track(conn, add_run(conn, "kilauea-kp", "fountain", [b, c]), [b])  # closes after the clock

    strip = views.frame_strip(scene(conn, tmp_path), "kilauea-kp", T0 - 60 * M)

    assert strip == [{"frame_id": a, "captured_at": to_iso(T0 - 20 * M), "usable": True, "targets": ["plume"]},
                     {"frame_id": b, "captured_at": to_iso(T0 - 10 * M), "usable": False, "targets": []}]
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_views.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigil.web'`.

- [ ] **Step 3: Implement**

`vigil/web/__init__.py`:
```python
"""The dashboard: live and replayed episodes in the browser."""
```

`vigil/web/views.py`:
```python
"""What the dashboard shows: one database seen at one clock.

Live, the database is the pipeline's and the clock is now; in a replay it is the replay's database at the simulated
time. Every query here is bounded by the clock, so a replay shows only what existed then:
- frames captured by the clock, with their quality verdicts;
- detections, and the measurements made from them, of SAM runs whose every frame was captured by the clock (the
  run's window_end): SAM tracks a window as a whole, so a detection on an early frame depends on the later ones;
- bulletins and agent runs whose clock is not after it;
- HVO's values once HVO had given them: a height once its window has closed, a phase once its latest time has
  passed, and the replay's comparison with them only at the episode's end.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from vigil.agent.tools import STALE_AFTER, calibrated
from vigil.calibration import Calibration
from vigil.config import Camera, Sources
from vigil.episodes import Episode
from vigil.timeutil import parse_utc, to_iso

# A rejected frame's condition: its first reason in this order (vigil.gate's reasons).
CONDITIONS = (("night", "night"), ("low_visibility", "fog"), ("frozen", "frozen"),
              ("timestamp_mismatch", "clock_mismatch"), ("stale", "stale"))
_RUN = "JOIN tracks t ON t.id = d.track_id JOIN tracking_runs r ON r.id = t.run_id"
_FRAME = """SELECT f.id, f.camera_id, f.captured_at, f.path, f.width, f.height, q.usable, q.reasons FROM frames f
            LEFT JOIN frame_quality q ON q.frame_id = f.id"""


@dataclass(frozen=True)
class Scene:
    conn: sqlite3.Connection
    clock: datetime                 # UTC: nothing after it is shown
    data_dir: Path
    sources: Sources
    calibration: Calibration
    volcano: str
    cameras: tuple[str, ...]        # the cameras shown, in order
    episode: Episode | None = None  # the replayed episode; None live

    def __post_init__(self):
        if self.clock.tzinfo is None:
            raise ValueError("the dashboard's clock needs a time zone")

    @property
    def now(self) -> str:
        return to_iso(self.clock)

    def camera(self, camera_id: str) -> Camera:
        """A camera the scene shows; LookupError for any other."""
        if camera_id not in self.cameras:
            raise LookupError(f"camera {camera_id!r} is not shown here; the cameras are {', '.join(self.cameras)}")
        return next(camera for camera in self.sources.cameras if camera.id == camera_id)


def condition(captured_at: str | None, usable: int | None, reasons: list[str], clock: datetime) -> str:
    """A camera's condition from its latest frame: no_frames, stale, unchecked, usable, or why the frame was
    rejected (night, fog, frozen, clock_mismatch, stale, rejected)."""
    if captured_at is None:
        return "no_frames"
    if clock - parse_utc(captured_at) > STALE_AFTER:
        return "stale"
    if usable is None:
        return "unchecked"
    if usable:
        return "usable"
    return next((name for reason, name in CONDITIONS if reason in reasons), "rejected")


def _reasons(text: str | None) -> list[str]:
    return json.loads(text) if text else []


def camera_status(scene: Scene) -> list[dict[str, Any]]:
    """Each shown camera's latest frame by the clock, its last hour, whether it measures heights, and when SAM last
    saw each target on it."""
    now, hour_ago = scene.now, to_iso(scene.clock - timedelta(hours=1))
    out = []
    for camera_id in scene.cameras:
        camera = scene.camera(camera_id)
        latest = scene.conn.execute(
            """SELECT f.id, f.captured_at, q.usable, q.reasons FROM frames f
               LEFT JOIN frame_quality q ON q.frame_id = f.id
               WHERE f.camera_id = ? AND f.captured_at <= ? ORDER BY f.captured_at DESC LIMIT 1""",
            (camera_id, now)).fetchone()
        frames, usable = scene.conn.execute(
            """SELECT COUNT(*), COALESCE(SUM(q.usable), 0) FROM frames f LEFT JOIN frame_quality q ON q.frame_id = f.id
               WHERE f.camera_id = ? AND f.captured_at > ? AND f.captured_at <= ?""",
            (camera_id, hour_ago, now)).fetchone()
        seen = scene.conn.execute(
            f"""SELECT r.target, MAX(f.captured_at) FROM detections d JOIN frames f ON f.id = d.frame_id {_RUN}
                WHERE r.camera_id = ? AND r.window_end <= ? GROUP BY r.target""", (camera_id, now)).fetchall()
        reasons = _reasons(latest["reasons"]) if latest else []
        site = scene.calibration.cameras.get(camera_id)
        out.append({
            "camera_id": camera_id, "name": camera.name, "kind": camera.kind,
            "condition": condition(latest["captured_at"] if latest else None, latest["usable"] if latest else None,
                                   reasons, scene.clock),
            "reasons": reasons,
            "latest": None if latest is None else {
                "frame_id": latest["id"], "captured_at": latest["captured_at"],
                "minutes_ago": round((scene.clock - parse_utc(latest["captured_at"])).total_seconds() / 60, 1)},
            "frames_last_hour": frames, "usable_last_hour": usable,
            "calibrated": calibrated(scene.calibration, camera_id, scene.clock),
            "position": None if site is None else {
                "lat": site.position.lat, "lon": site.position.lon, "elev_m": site.position.elev_m,
                "sigma_m": site.position.sigma_m},
            "last_detection": {row[0]: row[1] for row in seen},
        })
    return out


def _detection_rows(scene: Scene, frame_ids: list[int]) -> list[sqlite3.Row]:
    """The detections on these frames whose run closed by the clock, largest first."""
    if not frame_ids:
        return []
    marks = ",".join("?" * len(frame_ids))
    return scene.conn.execute(
        f"""SELECT d.*, r.target FROM detections d {_RUN}
            WHERE d.frame_id IN ({marks}) AND r.window_end <= ? ORDER BY d.area_px DESC, d.id""",
        (*frame_ids, scene.now)).fetchall()


def detections(scene: Scene, frame_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """Per frame, its detections that exist at the clock, each with the measurements made from it."""
    rows = _detection_rows(scene, frame_ids)
    measured: dict[int, dict[str, Any]] = defaultdict(dict)
    if rows:
        marks = ",".join("?" * len(rows))
        for m in scene.conn.execute(
                f"SELECT detection_id, metric, value, sigma, unit FROM measurements WHERE detection_id IN ({marks})",
                [row["id"] for row in rows]):
            measured[m["detection_id"]][m["metric"]] = {"value": m["value"], "sigma": m["sigma"], "unit": m["unit"]}
    found: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        found[row["frame_id"]].append({
            "detection_id": row["id"], "target": row["target"],
            "box": [row["box_left"], row["box_top"], row["box_right"], row["box_bottom"]], "score": row["score"],
            "measurements": measured.get(row["id"], {})})
    return dict(found)


def _frame_row(scene: Scene, frame_id: int) -> sqlite3.Row | None:
    return scene.conn.execute(f"{_FRAME} WHERE f.id = ? AND f.captured_at <= ?", (frame_id, scene.now)).fetchone()


def _frame_json(scene: Scene, row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"frame_id": row["id"], "camera_id": row["camera_id"], "captured_at": row["captured_at"],
            "width": row["width"], "height": row["height"],
            "usable": None if row["usable"] is None else bool(row["usable"]), "reasons": _reasons(row["reasons"]),
            "detections": detections(scene, [row["id"]]).get(row["id"], [])}


def frame(scene: Scene, frame_id: int) -> dict[str, Any] | None:
    """A frame captured by the clock with its verdict and visible detections; None for any other."""
    return _frame_json(scene, _frame_row(scene, frame_id))


def latest_frames(scene: Scene, camera_id: str) -> dict[str, Any]:
    """The camera's newest frame by the clock, and its newest frame with a visible detection (SAM tracks an hour
    at a time, so the two differ while an hour is open)."""
    scene.camera(camera_id)
    latest = scene.conn.execute(f"{_FRAME} WHERE f.camera_id = ? AND f.captured_at <= ? "
                                "ORDER BY f.captured_at DESC LIMIT 1", (camera_id, scene.now)).fetchone()
    tracked = scene.conn.execute(
        f"""{_FRAME} WHERE f.id = (SELECT d.frame_id FROM detections d JOIN frames g ON g.id = d.frame_id {_RUN}
                                   WHERE g.camera_id = ? AND g.captured_at <= ? AND r.window_end <= ?
                                   ORDER BY g.captured_at DESC LIMIT 1)""",
        (camera_id, scene.now, scene.now)).fetchone()
    return {"camera_id": camera_id, "latest": _frame_json(scene, latest), "tracked": _frame_json(scene, tracked)}


def frame_strip(scene: Scene, camera_id: str, since: datetime) -> list[dict[str, Any]]:
    """The camera's frames from `since` to the clock, oldest first: each verdict and the targets SAM saw on it."""
    scene.camera(camera_id)
    span = (camera_id, to_iso(since), scene.now)
    rows = scene.conn.execute(
        """SELECT f.id, f.captured_at, q.usable FROM frames f LEFT JOIN frame_quality q ON q.frame_id = f.id
           WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ? ORDER BY f.captured_at, f.id""", span).fetchall()
    targets: dict[int, set[str]] = defaultdict(set)
    for frame_id, target in scene.conn.execute(
            f"""SELECT d.frame_id, r.target FROM detections d JOIN frames f ON f.id = d.frame_id {_RUN}
                WHERE f.camera_id = ? AND f.captured_at BETWEEN ? AND ? AND r.window_end <= ?""",
            (*span, scene.now)):
        targets[frame_id].add(target)
    return [{"frame_id": row["id"], "captured_at": row["captured_at"],
             "usable": None if row["usable"] is None else bool(row["usable"]),
             "targets": sorted(targets.get(row["id"], ()))} for row in rows]
```

- [ ] **Step 4: Run the tests, then the full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_views.py` then `.venv/Scripts/python.exe -m pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vigil/web/__init__.py vigil/web/views.py tests/test_web_views.py
git commit -m "Show cameras and frames as they stood at a clock, with SAM detections only once their run had closed"
```

---

### Task 3: The scene's series, bulletins, agent trace, replay state and frame images

**Files:**
- Modify: `vigil/web/views.py`
- Test: `tests/test_web_views.py`

- [ ] **Step 1: Write the failing tests**

Add to the imports of `tests/test_web_views.py`:
```python
import io

from PIL import Image

from test_replay import bulletin_at, top
from vigil.agent import render
from vigil.agent.bulletin import Evidence
from vigil.episodes import EP55, HEIGHT_HEADER
from vigil.timeutil import parse_utc
```

Append:
```python
def test_the_series_has_each_frames_highest_value_from_runs_closed_by_the_clock(conn, store, tmp_path):
    f1, f2, f3, f4 = (add_frame(conn, store, "kilauea-kp", m) for m in (-30, -20, -10, 5))
    run = add_run(conn, "kilauea-kp", "plume", [f1, f2, f3])
    first, second = add_track(conn, run, [f1, f2, f3]), add_track(conn, run, [f2], object_id="1")
    for frame_id, detection_id, value in zip((f1, f2, f3), detection_ids(conn, first), (5000, 5200, 5400)):
        add_measurement(conn, frame_id, "top_altitude", value, 300, detection_id=detection_id)
    add_measurement(conn, f2, "top_altitude", 6000, 400, detection_id=detection_ids(conn, second)[0])
    late = add_track(conn, add_run(conn, "kilauea-kp", "plume", [f3, f4]), [f3, f4])  # closes after the clock
    for frame_id, detection_id in zip((f3, f4), detection_ids(conn, late)):
        add_measurement(conn, frame_id, "top_altitude", 9000, 300, detection_id=detection_id)

    shown = views.series(scene(conn, tmp_path), "kilauea-kp", "plume", "top_altitude", T0 - 25 * M)

    assert shown["unit"] == "m" and shown["official"] == []
    assert [(p["frame_id"], p["value"], p["sigma"]) for p in shown["points"]] == [(f2, 6000, 400), (f3, 5400, 300)]


def test_an_official_height_shows_once_its_window_has_closed(conn, tmp_path):
    def official(clock):
        shown = views.series(scene(conn, tmp_path, clock=parse_utc(clock), episode=EP55), "kilauea-kp", "plume",
                             "top_altitude", EP55.start)
        return [check["official"] for check in shown["official"]]

    assert official("2026-10-17T15:10:58Z") == []
    assert official("2026-10-17T16:08:00Z") == ["25,000 ft a.s.l., 04:50-05:10", "17,000 ft a.s.l. at 06:02"]


def test_a_series_unit_follows_its_metric_even_when_empty(conn, tmp_path):
    for metric, unit in (("area", "m2"), ("drift_bearing", "deg"), ("top_height", "m")):
        assert views.series(scene(conn, tmp_path), "kilauea-kp", "plume", metric, T0 - 60 * M)["unit"] == unit


def test_bulletins_written_by_the_clock_come_newest_first_in_both_languages(conn, tmp_path):
    first = bulletin_at(conn, tmp_path, "2026-10-17T14:00:00Z",
                        measurements=[top(6964, 419, "2026-10-17T13:55:05Z")])
    second = bulletin_at(conn, tmp_path, "2026-10-17T15:00:00Z", level="degassing")
    bulletin_at(conn, tmp_path, "2026-10-17T16:00:00Z")  # after the clock

    shown = views.bulletins(scene(conn, tmp_path))

    assert [b["id"] for b in shown] == [second.id, first.id]
    old = shown[1]
    assert (old["en"]["level"], old["es"]["level"]) == ("Lava fountain", "Fuente de lava")
    assert old["en"]["when"] == "2026-10-17 14:00 UTC"  # the test volcano has no UTC offset
    assert old["en"]["header"] == render.table_header("en")
    assert old["es"]["rows"] == render.table_rows(first, "es") and old["es"]["rows"][0][2] == "6.964 ± 419 m"
    assert (old["en"]["headline"], old["es"]["body"]) == (first.headline_en, first.body_es)
    assert old["en"]["disclaimer"] == first.disclaimer_en and old["official_url"] == first.official_url
    assert old["wind"] is None and old["en"]["wind_text"] is None and old["verified"] is True
    assert len(views.bulletins(scene(conn, tmp_path), limit=1)) == 1


def test_a_bulletins_evidence_keeps_its_overlay_path_and_captions(conn, tmp_path):
    stored = bulletin_at(conn, tmp_path, "2026-10-17T14:00:00Z")
    evidence = Evidence(frame_id=29, target="plume", caption_en="Plume", caption_es="Columna",
                        camera_id="kilauea-kp", captured_at="2026-10-17T13:55:05Z",
                        overlay="bulletins/run1/frame29_plume.jpg")
    with conn:
        conn.execute("UPDATE bulletins SET body = ? WHERE id = ?",
                     (stored.model_copy(update={"evidence": [evidence]}).model_dump_json(), stored.id))

    (shown,) = views.bulletins(scene(conn, tmp_path))

    assert shown["evidence"] == [evidence.model_dump()]


def add_agent_run(conn, clock, steps=()):
    with conn:
        run_id = conn.execute(
            """INSERT INTO agent_runs (started_at, clock, volcano, task, model, status, turns, cost_usd)
               VALUES ('2026-10-30T00:00:00Z', ?, 'kilauea', 'Check Kilauea now', 'muse-spark-1.3', 'done', 2, 0.03)""",
            (clock,)).lastrowid
        for seq, step in enumerate(steps, 1):
            conn.execute(f"""INSERT INTO agent_steps (run_id, seq, created_at, {', '.join(step)})
                             VALUES (?, ?, '2026-10-30T00:00:00Z', {', '.join('?' * len(step))})""",
                         (run_id, seq, *step.values()))
    return run_id


def test_the_trace_shows_the_latest_run_by_the_clock_with_its_steps(conn, tmp_path):
    early = add_agent_run(conn, "2026-10-17T14:00:00Z")
    written = bulletin_at(conn, tmp_path, "2026-10-17T14:00:00Z")  # bulletin_at stores run 1: `early`
    run = add_agent_run(conn, "2026-10-17T15:00:00Z", steps=[
        {"turn": 1, "kind": "model", "text": "Checking the cameras.", "reasoning": "KPcam sees the column."},
        {"turn": 1, "kind": "tool", "tool_name": "list_cameras_status", "arguments": "{}",
         "result": '{"now": "2026-10-17T15:00:00Z"}', "ok": 1, "cost_usd": 0.0, "latency_ms": 12},
        {"turn": 2, "kind": "tool", "tool_name": "measure_track", "arguments": "{not json",
         "result": '{"error": "bad"}', "ok": 0}])
    add_agent_run(conn, "2026-10-17T16:00:00Z")  # after the clock

    shown = views.agent_trace(scene(conn, tmp_path))

    assert [r["run_id"] for r in shown["runs"]] == [run, early]
    assert shown["runs"][1]["bulletin_id"] == written.id and early == 1
    assert shown["run"]["run_id"] == run and shown["run"]["bulletin_id"] is None
    model, listed, failed = shown["steps"]
    assert (model["kind"], model["text"], model["reasoning"]) == ("model", "Checking the cameras.",
                                                                  "KPcam sees the column.")
    assert (listed["arguments"], listed["result"], listed["ok"]) == ({}, {"now": "2026-10-17T15:00:00Z"}, True)
    assert (failed["arguments"], failed["ok"]) == ("{not json", False)


def test_a_run_after_the_clock_cannot_be_traced(conn, tmp_path):
    later = add_agent_run(conn, "2026-10-17T16:00:00Z")

    with pytest.raises(LookupError):
        views.agent_trace(scene(conn, tmp_path), later)
    assert views.agent_trace(scene(conn, tmp_path)) == {"runs": [], "run": None, "steps": []}


def add_tick(conn, clock, **report):
    with conn:
        conn.execute("INSERT INTO replay_ticks (clock, report) VALUES (?, ?)",
                     (clock, json.dumps({"clock": clock, **report})))


def test_the_replay_state_holds_the_steps_and_official_phases_known_by_the_clock(conn, tmp_path):
    for clock in ("2026-10-17T14:55:00Z", "2026-10-17T15:00:00Z", "2026-10-17T15:05:00Z"):
        add_tick(conn, clock, assessed=3)

    shown = views.replay_state(scene(conn, tmp_path, episode=EP55), tmp_path / "replay" / "ep55")

    assert [tick["clock"] for tick in shown["ticks"]] == ["2026-10-17T14:55:00Z", "2026-10-17T15:00:00Z"]
    assert shown["official_phases"] == {"onset": ["2026-10-17T13:19:00Z", "2026-10-17T13:19:00Z"]}
    assert (shown["episode"], shown["start"], shown["end"], shown["step_minutes"], shown["results"]) == (
        "55", "2026-10-17T13:00:00Z", "2026-10-17T19:30:00Z", 5, None)


def test_the_replays_results_show_only_at_the_episodes_end(conn, tmp_path):
    folder = tmp_path / "replay" / "ep55"
    folder.mkdir(parents=True)
    comparison = {"heights": [["plume top (peak)", "04:50-05:10", "kilauea-kp", "25,000 ft", "6,964 ± 419 m",
                               "-656 m (-9 %)", "-1.6", "yes"]],
                  "ends": [], "drift": [], "bulletins": [], "activity": []}
    (folder / "timeline.json").write_text(json.dumps({"step_minutes": 5, "comparison": comparison, "phases": None,
                                                      "cost_usd": 1.03}), encoding="utf-8")

    before = views.replay_state(scene(conn, tmp_path, clock=EP55.end - M, episode=EP55), folder)
    at_end = views.replay_state(scene(conn, tmp_path, clock=EP55.end, episode=EP55), folder)

    assert before["results"] is None
    heights = next(t for t in at_end["results"]["tables"] if t["title"] == "Measurements against the official values")
    assert heights["header"] == HEIGHT_HEADER and heights["rows"] == comparison["heights"]
    assert at_end["results"]["cost_usd"] == 1.03 and len(at_end["official_phases"]) == 4


def test_a_frame_image_is_scaled_with_the_masks_of_its_visible_detections(conn, store, tmp_path):
    shown, later = add_frame(conn, store, "kilauea-kp", -5), add_frame(conn, store, "kilauea-kp", 5)
    add_track(conn, add_run(conn, "kilauea-kp", "plume", [shown]), [shown])  # box (60, 60, 120, 150)

    plain, drawn = (Image.open(io.BytesIO(views.frame_image(scene(conn, tmp_path), shown, width=320,
                                                              overlay=overlay))).convert("RGB")
                    for overlay in (False, True))

    assert plain.size == drawn.size == (320, 180)
    inside = (round(90 * 320 / 384), round(105 * 320 / 384))  # the box's middle, scaled
    assert drawn.getpixel(inside)[2] > plain.getpixel(inside)[2] + 40  # tinted towards the plume's blue
    assert Image.open(io.BytesIO(views.frame_image(scene(conn, tmp_path), shown, width=1280))).size == (384, 216)
    with pytest.raises(LookupError):
        views.frame_image(scene(conn, tmp_path), later, width=320)


def test_a_mask_of_a_run_that_closes_after_the_clock_is_not_drawn(conn, store, tmp_path):
    shown, later = add_frame(conn, store, "kilauea-kp", -5), add_frame(conn, store, "kilauea-kp", 5)
    add_track(conn, add_run(conn, "kilauea-kp", "plume", [shown, later]), [shown, later])

    plain = views.frame_image(scene(conn, tmp_path), shown, width=384, overlay=False)

    assert views.frame_image(scene(conn, tmp_path), shown, width=384) == plain
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_views.py`
Expected: FAIL (`series`, `bulletins`, `agent_trace`, `replay_state`, `frame_image` missing).

- [ ] **Step 3: Implement** (append to `vigil/web/views.py`; merge the imports into its import block)

```python
import io

import numpy as np
from PIL import Image

from vigil import masks
from vigil.agent import render
from vigil.agent.bulletin import COLORS, Bulletin
from vigil.episodes import DRIFT_HEADER, END_HEADER, HEIGHT_HEADER
from vigil.overlay import Layer, draw_layers
from vigil.phases import HEADER as PHASES_HEADER
from vigil.replay import ACTIVITY_HEADER, BULLETIN_HEADER, STEP

UNITS = {"area": "m2", "drift_bearing": "deg"}  # every other metric is in metres
JPEG_QUALITY = 82
RESULT_TABLES = (  # the replay's comparison with the official values, as report.md titles it
    ("What the bulletins quoted against the official values", BULLETIN_HEADER, "bulletins"),
    ("Activity against the official times", ACTIVITY_HEADER, "activity"),
    ("Measurements against the official values", HEIGHT_HEADER, "heights"),
    ("End of fountaining", END_HEADER, "ends"),
    ("Drift", DRIFT_HEADER, "drift"),
)


def series(scene: Scene, camera_id: str, target: str, metric: str, since: datetime) -> dict[str, Any]:
    """The camera's measurements of a target and metric from `since` to the clock: the highest detection of each
    frame, oldest first. In a replay, also the official values of that target and metric whose window has closed."""
    scene.camera(camera_id)
    rows = scene.conn.execute(
        f"""SELECT m.captured_at, m.frame_id, m.value, m.sigma FROM measurements m
            JOIN detections d ON d.id = m.detection_id {_RUN}
            WHERE m.camera_id = ? AND m.target = ? AND m.metric = ? AND m.captured_at BETWEEN ? AND ?
            AND r.window_end <= ? ORDER BY m.captured_at, m.value DESC""",
        (camera_id, target, metric, to_iso(since), scene.now, scene.now)).fetchall()
    best: dict[str, sqlite3.Row] = {}
    for row in rows:
        best.setdefault(row["captured_at"], row)
    official = [] if scene.episode is None else [
        {"quantity": check.quantity, "start": check.start, "end": check.end, "value_m": check.official_m,
         "official": check.official, "source": check.source, "upper_bound": check.upper_bound}
        for check in scene.episode.checks
        if (check.target, check.metric) == (target, metric) and parse_utc(check.end) <= scene.clock]
    return {"camera_id": camera_id, "target": target, "metric": metric, "unit": UNITS.get(metric, "m"),
            "points": [{"captured_at": row["captured_at"], "frame_id": row["frame_id"], "value": row["value"],
                        "sigma": row["sigma"]} for row in best.values()],
            "official": official}


def _language(b: Bulletin, lang: render.Lang) -> dict[str, Any]:
    headline, body, disclaimer = render.texts(b, lang)
    return {"headline": headline, "body": body, "disclaimer": disclaimer,
            "level": render.LEVELS[b.activity_level][0 if lang == "en" else 1],
            "when": render.local_time(b.clock, b.utc_offset_hours),
            "header": render.table_header(lang), "rows": render.table_rows(b, lang),
            "wind_text": render.wind_text(b, lang) if b.wind else None}


def bulletins(scene: Scene, limit: int = 20) -> list[dict[str, Any]]:
    """The volcano's bulletins written by the clock, newest first, in both languages with the published tables."""
    rows = scene.conn.execute("SELECT body FROM bulletins WHERE volcano = ? AND clock <= ? "
                              "ORDER BY clock DESC, id DESC LIMIT ?", (scene.volcano, scene.now, limit)).fetchall()
    out = []
    for row in rows:
        b = Bulletin.model_validate_json(row["body"])
        out.append({"id": b.id, "run_id": b.run_id, "clock": b.clock, "activity_level": b.activity_level,
                    "verified": b.verified, "official_agency": b.official_agency, "official_url": b.official_url,
                    "wind": b.wind, "evidence": [e.model_dump() for e in b.evidence], "notes": b.notes,
                    "en": _language(b, "en"), "es": _language(b, "es")})
    return out


def _parsed(text: str | None) -> Any:
    """A stored JSON text as data; the text itself if it is not JSON (Muse Spark may send broken arguments)."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def agent_trace(scene: Scene, run_id: int | None = None) -> dict[str, Any]:
    """The agent runs by the clock, newest first, and the steps of one: `run_id`, or the newest. LookupError for a
    run after the clock or of another volcano."""
    runs = [{"run_id": row["id"], "clock": row["clock"], "status": row["status"], "turns": row["turns"],
             "cost_usd": row["cost_usd"], "bulletin_id": row["bulletin_id"], "task": row["task"],
             "model": row["model"], "error": row["error"]}
            for row in scene.conn.execute(
                """SELECT r.*, (SELECT MAX(b.id) FROM bulletins b WHERE b.run_id = r.id) AS bulletin_id
                   FROM agent_runs r WHERE r.volcano = ? AND r.clock <= ? ORDER BY r.clock DESC, r.id DESC""",
                (scene.volcano, scene.now))]
    if run_id is None:
        run = runs[0] if runs else None
    else:
        run = next((r for r in runs if r["run_id"] == run_id), None)
        if run is None:
            raise LookupError(f"no agent run {run_id} by {scene.now}")
    steps = [] if run is None else [
        {"seq": row["seq"], "turn": row["turn"], "kind": row["kind"], "text": row["text"],
         "reasoning": row["reasoning"], "tool_name": row["tool_name"], "arguments": _parsed(row["arguments"]),
         "result": _parsed(row["result"]), "ok": None if row["ok"] is None else bool(row["ok"]),
         "cost_usd": row["cost_usd"], "latency_ms": row["latency_ms"]}
        for row in scene.conn.execute("SELECT * FROM agent_steps WHERE run_id = ? ORDER BY seq", (run["run_id"],))]
    return {"runs": runs, "run": run, "steps": steps}


def replay_state(scene: Scene, folder: Path) -> dict[str, Any]:
    """The replay's steps by the clock, HVO's phases whose latest time has passed, and, at the episode's end, the
    comparison with the official values from the replay's timeline.json in `folder`."""
    episode = scene.episode
    if episode is None:
        raise ValueError("a live scene has no replay")
    path = folder / "timeline.json"
    timeline = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    results = None
    if timeline is not None and scene.clock >= episode.end:
        comparison = timeline["comparison"]
        tables = [{"title": title, "header": header, "rows": comparison[key]} for title, header, key in RESULT_TABLES]
        if timeline.get("phases"):
            tables.append({"title": "Episode phases", "header": PHASES_HEADER, "rows": timeline["phases"]["rows"]})
        results = {"tables": tables, "cost_usd": timeline["cost_usd"]}
    return {
        "episode": episode.key, "volcano": episode.volcano, "cameras": list(episode.cameras),
        "start": to_iso(episode.start), "end": to_iso(episode.end),
        "step_minutes": timeline["step_minutes"] if timeline else STEP / timedelta(minutes=1),
        "ticks": [json.loads(row[0]) for row in scene.conn.execute(
            "SELECT report FROM replay_ticks WHERE clock <= ? ORDER BY clock", (scene.now,))],
        "official_phases": {phase: [to_iso(low), to_iso(high)] for phase, (low, high) in episode.phases.items()
                            if high <= scene.clock},
        "results": results,
    }


def frame_image(scene: Scene, frame_id: int, *, width: int, overlay: bool = True) -> bytes:
    """The frame as a JPEG at most `width` pixels wide (never enlarged), with the masks of its detections that exist
    at the clock tinted on it and no legend (the page has one). LookupError for a frame after the clock."""
    row = _frame_row(scene, frame_id)
    if row is None:
        raise LookupError(f"no frame {frame_id} captured by {scene.now}")
    scale = min(1.0, width / row["width"])
    size = (max(1, round(row["width"] * scale)), max(1, round(row["height"] * scale)))
    with Image.open(scene.data_dir / row["path"]) as image:
        image.draft("RGB", size)  # JPEG: decode at a fraction of the size, which is much faster
        picture = image.convert("RGB").resize(size, Image.LANCZOS)
    layers = []
    for d in _detection_rows(scene, [frame_id]) if overlay else []:
        left, top, right, bottom = (round(v * scale) for v in (d["box_left"], d["box_top"], d["box_right"],
                                                                d["box_bottom"]))
        w, h = max(1, right - left), max(1, bottom - top)
        box_mask = masks.decode(json.loads(d["mask_rle"]))
        small = np.asarray(Image.fromarray(box_mask).resize((w, h), Image.NEAREST), dtype=bool)
        full = np.zeros((size[1], size[0]), dtype=bool)
        full[top:top + h, left:left + w] = small[:size[1] - top, :size[0] - left]
        layers.append(Layer(full, COLORS[d["target"]], d["target"]))
    buffer = io.BytesIO()
    draw_layers(picture, layers, legend=False).save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()
```
Note: `STEP / timedelta(minutes=1)` is `5.0`; the test compares with `5`, which is equal. If `vigil.replay` turns out to import `vigil.web` (it must not), move the import of `STEP` and the headers inside the functions.

- [ ] **Step 4: Run the tests, then the full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_views.py` then `.venv/Scripts/python.exe -m pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add vigil/web/views.py tests/test_web_views.py
git commit -m "Give the dashboard its height series, bulletins, agent traces, replay state and frame images at a clock"
```

---

### Task 4: The FastAPI app and `vigil-web`

**Files:**
- Modify: `pyproject.toml`
- Create: `vigil/web/app.py`, `vigil/web/static/index.html` (a first version; Task 6 completes it)
- Test: `tests/test_web_app.py`

- [ ] **Step 1: Add the dependencies and install them**

In `pyproject.toml`, add to `dependencies`: `"fastapi>=0.115",` and `"uvicorn>=0.30",`; add the script `vigil-web = "vigil.web.app:main"`; add package data so a non-editable install (Phase 7's Docker image) ships the page:
```toml
[tool.setuptools.package-data]
"vigil.web" = ["static/*.html", "static/css/*.css", "static/js/*.js"]
```
Run: `.venv/Scripts/python.exe -m pip install -e ".[dev]"`
Expected: installs fastapi, starlette, uvicorn. Check: `.venv/Scripts/python.exe -c "import fastapi, uvicorn; print(fastapi.__version__)"`.

Before writing the app, check the current FastAPI docs through Context7 (`/websites/fastapi_tiangolo`): dependencies with `yield`, `Annotated[..., Depends()]`, `Literal` query parameters, `Response(media_type=...)`, `FileResponse`, `StaticFiles`, `TestClient`.

- [ ] **Step 2: Write the failing tests**

`tests/test_web_app.py`:
```python
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_agent_tools import T0, add_frame
from test_web_views import add_agent_run
from vigil import db
from vigil.episodes import EP55
from vigil.ingest.store import FrameStore
from vigil.settings import Settings
from vigil.timeutil import to_iso
from vigil.web.app import create_app

ROOT = Path(__file__).resolve().parent.parent
NOW = T0 + timedelta(days=13)  # the wall clock, 2026-10-30T15:00Z; T0 is 05:00 HST in episode 55
M = timedelta(minutes=1)


def settings(tmp_path):
    return Settings(data_dir=tmp_path, db_path=tmp_path / "vigil.sqlite",
                    sources_path=ROOT / "config" / "sources.yaml", prompts_path=ROOT / "config" / "prompts.yaml",
                    calibration_path=ROOT / "config" / "calibration.yaml", user_agent="test", daily_budget_usd=1.0)


def app_client(tmp_path):
    return TestClient(create_app(settings(tmp_path), now=lambda: NOW))


@pytest.fixture
def live(tmp_path):
    connection = db.connect(tmp_path / "vigil.sqlite")
    yield connection
    connection.close()


@pytest.fixture
def replayed(tmp_path):
    connection = db.connect(tmp_path / "replay" / "ep55" / "vigil.sqlite")
    yield connection
    connection.close()


@pytest.fixture
def client(tmp_path, live, replayed):
    return app_client(tmp_path)


AT = {"replay": "55", "at": to_iso(T0)}


def test_the_page_carries_the_notice_and_the_official_link(client):
    page = client.get("/")

    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "It does not replace official alerts or warnings." in page.text
    assert 'href="https://www.usgs.gov/volcanoes/kilauea"' in page.text
    assert "USGS Hawaiian Volcano Observatory (HVO)" in page.text and "{{" not in page.text


def test_config_names_the_volcano_its_cameras_and_the_replays_on_disk(client):
    config = client.get("/api/config").json()

    assert (config["volcano"]["name"], config["volcano"]["utc_offset_hours"]) == ("Kīlauea", -10)
    assert config["vent"]["lat"] == 19.40496
    assert config["live"] == {"cameras": ["kilauea-k2", "kilauea-kp", "kilauea-f1"], "available": True}
    assert [(r["episode"], r["start"], r["end"], r["step_minutes"]) for r in config["replays"]] == [
        ("55", "2026-10-17T13:00:00Z", "2026-10-17T19:30:00Z", 5)]
    assert config["disclaimer"]["es"].startswith("Lectura automática")
    assert config["now"] == to_iso(NOW)


def test_without_a_replay_database_config_lists_no_replay(tmp_path, live):
    assert app_client(tmp_path).get("/api/config").json()["replays"] == []


def test_live_answers_at_the_wall_clock(client, live, tmp_path):
    add_frame(live, FrameStore(live, tmp_path), "kilauea-kp", 0)  # 13 days before NOW

    cameras = client.get("/api/cameras").json()

    assert cameras["clock"] == to_iso(NOW)
    assert [(c["camera_id"], c["condition"]) for c in cameras["cameras"]] == [
        ("kilauea-k2", "no_frames"), ("kilauea-kp", "stale"), ("kilauea-f1", "no_frames")]


def test_a_replay_answers_at_its_simulated_clock(client, replayed, tmp_path):
    store = FrameStore(replayed, tmp_path)
    before, _ = add_frame(replayed, store, "kilauea-kp", -5), add_frame(replayed, store, "kilauea-kp", 5)

    shown = client.get("/api/frames/latest", params={**AT, "camera": "kilauea-kp"}).json()
    one = client.get(f"/api/frames/{before}", params=AT).json()

    assert (shown["clock"], shown["latest"]["frame_id"], one["frame"]["frame_id"]) == (to_iso(T0), before, before)
    cameras = client.get("/api/cameras", params=AT).json()["cameras"]
    assert [c["camera_id"] for c in cameras] == list(EP55.cameras)


@pytest.mark.parametrize("params, status", [
    ({"at": "2026-10-17T05:00:00"}, 422),                  # no UTC offset
    ({"at": to_iso(NOW + M)}, 422),                         # live, after now
    ({"replay": "55", "at": "2026-10-17T12:59:00Z"}, 422),  # before the episode
    ({"replay": "55", "at": "2026-10-17T19:31:00Z"}, 422),  # after it
    ({"replay": "54"}, 404)])                               # no such episode
def test_a_clock_the_scene_cannot_have_is_refused(client, params, status):
    assert client.get("/api/cameras", params=params).status_code == status


def test_an_episode_that_was_not_replayed_is_not_found(tmp_path, live):
    assert app_client(tmp_path).get("/api/cameras", params={"replay": "55"}).status_code == 404


def test_without_a_live_database_live_is_unavailable(tmp_path):
    client = app_client(tmp_path)

    assert client.get("/api/cameras").status_code == 503
    assert client.get("/api/config").json()["live"]["available"] is False
    assert not (tmp_path / "vigil.sqlite").exists()


def test_a_camera_or_frame_the_scene_does_not_show_is_not_found(client, replayed, tmp_path):
    later = add_frame(replayed, FrameStore(replayed, tmp_path), "kilauea-kp", 5)

    assert client.get("/api/frames/latest", params={"camera": "kilauea-v2"}).status_code == 404
    assert client.get(f"/api/frames/{later}", params=AT).status_code == 404
    assert client.get(f"/api/frames/{later}/image", params=AT).status_code == 404


def test_every_endpoint_answers_with_its_clock(client):
    for path, extra in (("/api/series", {"camera": "kilauea-kp", "target": "plume", "metric": "top_altitude"}),
                        ("/api/frames", {"camera": "kilauea-kp"}), ("/api/bulletins", {}),
                        ("/api/agent/trace", {}), ("/api/replay", {})):
        answer = client.get(path, params={**AT, **extra})
        assert answer.status_code == 200, path
        assert answer.json()["clock"] == to_iso(T0), path


def test_a_series_needs_a_known_target_and_metric(client):
    params = {**AT, "camera": "kilauea-kp", "target": "lava", "metric": "top_altitude"}
    assert client.get("/api/series", params=params).status_code == 422


def test_the_replay_endpoint_needs_a_replay(client):
    assert client.get("/api/replay").status_code == 404


def test_a_run_after_the_clock_cannot_be_traced(client, replayed):
    later = add_agent_run(replayed, "2026-10-17T16:00:00Z")
    assert client.get("/api/agent/trace", params={**AT, "run_id": later}).status_code == 404


def test_an_image_width_outside_the_allowed_range_is_refused(client):
    assert client.get("/api/frames/1/image", params={**AT, "width": 4000}).status_code == 422
```

- [ ] **Step 3: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_app.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigil.web.app'`.

- [ ] **Step 4: Implement**

`vigil/web/static/index.html` (first version; Task 6 replaces the body, keeping the notice):
```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Volcano Vigil · {{volcano_name}}</title>
</head>
<body>
<p class="notice" role="note"><strong class="notice-tag">Not an official alert</strong> {{notice_lead}}<a href="{{official_url}}" rel="noopener" target="_blank">{{official_agency}}</a>.</p>
</body>
</html>
```

`vigil/web/app.py`:
```python
"""The dashboard's web app: the live database or a replay's, always seen at one clock (vigil.web.views).

Every /api endpoint takes `replay`, an episode key (absent: live), and `at`, a time with its UTC offset. Live, `at`
defaults to now and may not be after it; in a replay it defaults to the episode's end and must fall inside the
episode. Model text reaches the browser only inside JSON, and the page inserts it as text, never as HTML. Every
page carries the disclaimer and the link to the official agency in its own markup.

    vigil-web --port 8000
"""

from __future__ import annotations

import argparse
import html
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from vigil import db
from vigil.agent.bulletin import DISCLAIMER_EN, DISCLAIMER_ES
from vigil.agent.tools import Metric
from vigil.calibration import load_calibration
from vigil.config import ConfigError, load_sources
from vigil.episodes import EPISODES
from vigil.prompts import Target
from vigil.replay import STEP, replay_dir
from vigil.settings import Settings
from vigil.timeutil import parse_utc, to_iso, utcnow
from vigil.web import views
from vigil.web.views import Scene

STATIC = Path(__file__).parent / "static"
LIVE_SPAN = timedelta(hours=24)  # how far back the live strips and series reach by default
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png"}


def media_file(data_dir: Path, path: str) -> Path | None:
    """A bulletin image under the data dir (an evidence overlay, inside a `bulletins` folder); None for anything
    else: frames, databases, pages, or a path that leaves the data dir."""
    root = data_dir.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or target.suffix.lower() not in MEDIA_SUFFIXES or not target.is_file():
        return None
    return target if "bulletins" in target.relative_to(root).parts[:-1] else None


def _clock(at: str | None, default: datetime) -> datetime:
    if at is None:
        return default
    try:
        return parse_utc(at)
    except ValueError as exc:
        raise HTTPException(422, f"at: {exc}") from exc


def create_app(settings: Settings | None = None, *, volcano: str = "kilauea",
               now: Callable[[], datetime] = utcnow) -> FastAPI:
    settings = settings or Settings.from_env()
    sources = load_sources(settings.sources_path)
    calibration = load_calibration(settings.calibration_path)
    if volcano not in sources.volcanoes:
        raise ConfigError(f"unknown volcano {volcano!r} in {settings.sources_path}")
    info = sources.volcanoes[volcano]
    live_cameras = tuple(c.id for c in sources.enabled_cameras() if c.volcano == volcano)
    words = {"name": info.name, "agency": info.official_agency, "url": info.official_url}
    disclaimer = {"en": DISCLAIMER_EN.format(**words), "es": DISCLAIMER_ES.format(**words)}
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    for key, value in {"volcano_name": info.name, "official_agency": info.official_agency,
                       "official_url": info.official_url,
                       "notice_lead": DISCLAIMER_EN.split("{agency}")[0].format(name=info.name)}.items():
        page = page.replace("{{" + key + "}}", html.escape(value))

    app = FastAPI(title="Volcano Vigil")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def scene(replay: str | None = None, at: str | None = None) -> Iterator[Scene]:
        if replay is None:
            clock = _clock(at, now())
            if clock > now():
                raise HTTPException(422, f"at {to_iso(clock)} is after now")
            path, cameras, episode = settings.db_path, live_cameras, None
            if not path.is_file():
                raise HTTPException(503, "no live database yet: run vigil-ingest")
        else:
            episode = EPISODES.get(replay)
            if episode is None:
                raise HTTPException(404, f"no episode {replay!r}")
            path, cameras = replay_dir(settings.data_dir, episode) / "vigil.sqlite", episode.cameras
            if not path.is_file():
                raise HTTPException(404, f"episode {episode.key} has not been replayed: run vigil-replay "
                                         f"--episode {episode.key}")
            clock = _clock(at, episode.end)
            if not episode.start <= clock <= episode.end:
                raise HTTPException(422, f"at {to_iso(clock)} is outside episode {episode.key} "
                                         f"({to_iso(episode.start)} to {to_iso(episode.end)})")
        conn = db.connect_readonly(path)
        try:
            yield Scene(conn=conn, clock=clock, data_dir=settings.data_dir, sources=sources, calibration=calibration,
                        volcano=episode.volcano if episode else volcano, cameras=cameras, episode=episode)
        finally:
            conn.close()

    Seen = Annotated[Scene, Depends(scene)]

    def since_or_default(seen: Scene, since: str | None) -> datetime:
        return _clock(since, seen.episode.start if seen.episode else seen.clock - LIVE_SPAN)

    def found(call, *args, **kwargs):
        try:
            return call(*args, **kwargs)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return page

    @app.get("/api/config")
    def config() -> dict:
        vent = calibration.vents.get(volcano)
        replays = []
        for episode in EPISODES.values():
            folder = replay_dir(settings.data_dir, episode)
            if episode.volcano == volcano and (folder / "vigil.sqlite").is_file():
                replays.append({"episode": episode.key, "start": to_iso(episode.start), "end": to_iso(episode.end),
                                "cameras": list(episode.cameras), "step_minutes": STEP / timedelta(minutes=1)})
        return {
            "volcano": {"id": volcano, "name": info.name, "official_agency": info.official_agency,
                        "official_url": info.official_url, "utc_offset_hours": info.utc_offset_hours,
                        "lat": info.lat, "lon": info.lon},
            "vent": None if vent is None else {"lat": vent.lat, "lon": vent.lon, "elev_m": vent.elev_m},
            "disclaimer": disclaimer,
            "live": {"cameras": list(live_cameras), "available": settings.db_path.is_file()},
            "replays": replays, "now": to_iso(now()),
        }

    @app.get("/api/cameras")
    def cameras(seen: Seen) -> dict:
        return {"clock": seen.now, "cameras": views.camera_status(seen)}

    @app.get("/api/frames/latest")  # before /api/frames/{frame_id}, which would take "latest" for an id
    def latest(seen: Seen, camera: str) -> dict:
        return {"clock": seen.now, **found(views.latest_frames, seen, camera)}

    @app.get("/api/frames")
    def strip(seen: Seen, camera: str, since: str | None = None) -> dict:
        start = since_or_default(seen, since)
        return {"clock": seen.now, "camera_id": camera, "since": to_iso(start),
                "frames": found(views.frame_strip, seen, camera, start)}

    @app.get("/api/frames/{frame_id}")
    def one_frame(seen: Seen, frame_id: int) -> dict:
        shown = views.frame(seen, frame_id)
        if shown is None:
            raise HTTPException(404, f"no frame {frame_id} captured by {seen.now}")
        return {"clock": seen.now, "frame": shown}

    @app.get("/api/frames/{frame_id}/image")
    def image(seen: Seen, frame_id: int, overlay: bool = True,
              width: Annotated[int, Query(ge=320, le=1920)] = 1280) -> Response:
        body = found(views.frame_image, seen, frame_id, width=width, overlay=overlay)
        return Response(body, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/series")
    def series(seen: Seen, camera: str, target: Target, metric: Metric, since: str | None = None) -> dict:
        start = since_or_default(seen, since)
        return {"clock": seen.now, "since": to_iso(start),
                **found(views.series, seen, camera, target, metric, start)}

    @app.get("/api/bulletins")
    def bulletins(seen: Seen, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> dict:
        return {"clock": seen.now, "bulletins": views.bulletins(seen, limit)}

    @app.get("/api/agent/trace")
    def trace(seen: Seen, run_id: int | None = None) -> dict:
        return {"clock": seen.now, **found(views.agent_trace, seen, run_id)}

    @app.get("/api/replay")
    def replay_state(seen: Seen) -> dict:
        if seen.episode is None:
            raise HTTPException(404, "pass replay=<episode> for a replay's state")
        return {"clock": seen.now, **views.replay_state(seen, replay_dir(settings.data_dir, seen.episode))}

    @app.get("/media/{path:path}")
    def media(path: str) -> FileResponse:
        target = media_file(settings.data_dir, path)
        if target is None:
            raise HTTPException(404, "not a bulletin image")
        return FileResponse(target)

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serve the dashboard: live and replayed episodes.")
    parser.add_argument("--host", default="127.0.0.1", help="interface to listen on (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    args = parser.parse_args(argv)
    uvicorn.run(create_app(), host=args.host, port=args.port)
```
Notes for the implementer:
- `test_a_replay_answers_at_its_simulated_clock` expects `/api/frames/{id}` to wrap the frame as `{"clock", "frame"}`; keep that shape.
- The media endpoint's tests are in Task 5; the endpoint is written here because it shares the app.
- `step_minutes` is `5.0`; the config test compares with `5`, which is equal.
- If FastAPI rejects `Literal` aliases imported from other modules as query types, use `Annotated[Target, Query()]`.

- [ ] **Step 5: Run the tests, then the full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_app.py` then `.venv/Scripts/python.exe -m pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml vigil/web/app.py vigil/web/static/index.html tests/test_web_app.py
git commit -m "Serve the dashboard's API with FastAPI, one clock per request, live or replayed"
```

---

### Task 5: Bulletin images through `/media`, and the frame image endpoint end to end

**Files:**
- Test: `tests/test_web_app.py` (the code is in Task 4; this task pins the file rules and the image route)

- [ ] **Step 1: Write the tests**

Append to `tests/test_web_app.py` (add `import io`, `from PIL import Image`, `from test_agent_tools import add_run, add_track, frame_jpeg` and `from vigil.web.app import media_file`):
```python
def test_media_serves_bulletin_images_and_nothing_else(client, tmp_path):
    folder = tmp_path / "replay" / "ep55" / "bulletins" / "run2"
    folder.mkdir(parents=True)
    (folder / "frame29_plume.jpg").write_bytes(frame_jpeg(1))
    (folder / "bulletin.html").write_text("<p>x</p>", encoding="utf-8")
    (tmp_path / "frames").mkdir(exist_ok=True)
    (tmp_path / "frames" / "raw.jpg").write_bytes(frame_jpeg(2))

    served = client.get("/media/replay/ep55/bulletins/run2/frame29_plume.jpg")

    assert served.status_code == 200 and served.headers["content-type"] == "image/jpeg"
    for path in ("frames/raw.jpg", "replay/ep55/bulletins/run2/bulletin.html", "replay/ep55/vigil.sqlite",
                 "replay/ep55/bulletins/run2/missing.jpg"):
        assert client.get(f"/media/{path}").status_code == 404, path


def test_a_media_path_cannot_leave_the_data_dir(tmp_path):
    data = tmp_path / "data"
    (data / "bulletins").mkdir(parents=True)
    (tmp_path / "bulletins").mkdir()
    (tmp_path / "bulletins" / "outside.jpg").write_bytes(frame_jpeg(3))

    assert media_file(data, "../bulletins/outside.jpg") is None
    assert media_file(data, "bulletins/../../bulletins/outside.jpg") is None


def test_the_image_route_sends_a_scaled_jpeg_with_its_masks(client, replayed, tmp_path):
    shown = add_frame(replayed, FrameStore(replayed, tmp_path), "kilauea-kp", -5)
    add_track(replayed, add_run(replayed, "kilauea-kp", "plume", [shown]), [shown])

    answer = client.get(f"/api/frames/{shown}/image", params={**AT, "width": 320})

    assert answer.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(answer.content)).size == (320, 180)
```

- [ ] **Step 2: Run them**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_app.py`
Expected: PASS if Task 4 followed the plan. If any fails, fix the app (not the test) and say what you changed.

- [ ] **Step 3: Measure the real image route** (no Meta API cost)

Run a short script against the real replay database: `create_app()` with the default settings and `TestClient`, then time `/api/frames/29/image?replay=55&at=2026-10-17T15:00:00Z` and `/api/frames/142/image?...` five times each. Expected: under 300 ms each (planning measured ~120 ms). Report the numbers.

- [ ] **Step 4: Run the full suite and commit**

```bash
git add tests/test_web_app.py
git commit -m "Pin which files the dashboard serves and the frame image route"
```

---

### Task 6: The page: notice, layout, tokens, helpers and the clock

**Files:**
- Modify: `vigil/web/static/index.html`
- Create: `vigil/web/static/css/app.css`, `vigil/web/static/js/lib.js`, `vigil/web/static/js/dom.js`, `vigil/web/static/js/api.js`, `vigil/web/static/js/main.js`
- Test: `tests/js/lib.test.mjs`, `tests/test_web_static.py`

- [ ] **Step 1: Write the failing tests**

`tests/js/lib.test.mjs`:
```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { age, bearing, destination, feet, localDate, localTime, number, plusMinus, ticks, zone } from "../../vigil/web/static/js/lib.js";

test("local time shifts by the volcano's offset, never the browser's zone", () => {
  assert.equal(localTime("2026-10-17T14:55:05Z", -10), "04:55");
  assert.equal(localTime("2026-10-17T14:55:05Z", -10, true), "04:55:05");
  assert.equal(localTime("2026-10-17T05:00:00Z", -10), "19:00");
  assert.equal(localDate("2026-10-17T05:00:00Z", -10), "2026-10-16");
  assert.equal(localTime("2026-10-17T14:55:05Z", 0), "14:55");
});

test("a time without its zone is refused", () => {
  assert.throws(() => localTime("2026-10-17T14:55:05", -10));
});

test("zones read like the bulletins'", () => {
  assert.equal(zone(-10), "UTC−10");
  assert.equal(zone(0), "UTC");
  assert.equal(zone(5.5), "UTC+5.5");
});

test("numbers and uncertainties print as the English bulletins print them", () => {
  assert.equal(number(6963.7), "6,964");
  assert.equal(number(3.25, 1), "3.3");
  assert.equal(plusMinus(6963.7, 419.4, "m"), "6,964 ± 419 m");
  assert.equal(plusMinus(224.44, 2.1, "deg"), "224.4° ± 2.1°");
  assert.equal(plusMinus(20215368, 1409392, "m2"), "20.2 ± 1.4 km²");
  assert.equal(feet(7620), 25000);
});

test("ages are relative to the scene's clock", () => {
  assert.equal(age("2026-10-17T14:59:40Z", "2026-10-17T15:00:00Z"), "just now");
  assert.equal(age("2026-10-17T14:48:00Z", "2026-10-17T15:00:00Z"), "12 min ago");
  assert.equal(age("2026-10-17T12:00:00Z", "2026-10-17T15:00:00Z"), "3 h ago");
  assert.equal(age("2026-10-14T15:00:00Z", "2026-10-17T15:00:00Z"), "3 d ago");
});

test("the replay's ticks match vigil.replay.ticks", () => {
  assert.deepEqual(ticks("2026-10-17T13:00:00Z", "2026-10-17T13:12:00Z", 5),
    ["2026-10-17T13:05:00Z", "2026-10-17T13:10:00Z", "2026-10-17T13:12:00Z"]);
});

test("a destination and a bearing on the sphere agree", () => {
  const [lat, lon] = destination(19.40496, -155.29022, 90, 1000);
  assert.ok(Math.abs(lat - 19.40496) < 1e-4);
  assert.ok(Math.abs(lon - -155.280685) < 2e-5);
  const [north] = destination(19.40496, -155.29022, 0, 1000);
  assert.ok(Math.abs(north - 19.413953) < 2e-5);
  const there = destination(19.492709, -155.385281, 137, 5000);
  assert.ok(Math.abs(bearing(19.492709, -155.385281, there[0], there[1]) - 137) < 0.01);
});
```

`tests/test_web_static.py`:
```python
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "vigil" / "web" / "static"


def test_the_page_scripts_never_write_html():
    scripts = list((STATIC / "js").glob("*.js"))
    assert scripts
    for script in scripts:
        text = script.read_text(encoding="utf-8")
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            assert sink not in text, f"{script.name} uses {sink}"


def test_the_notice_is_in_the_page_itself_not_added_by_a_script():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'class="notice"' in page and "{{notice_lead}}" in page and 'href="{{official_url}}"' in page


def test_leaflet_is_pinned_with_its_integrity_hashes():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert ('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" '
            'integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="') in page
    assert ('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" '
            'integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="') in page


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_javascript_helpers_pass_their_node_tests():
    result = subprocess.run([shutil.which("node"), "--test", str(ROOT / "tests" / "js" / "lib.test.mjs")],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_static.py`
Expected: FAIL (no scripts, no Leaflet tags, no `lib.js`).

- [ ] **Step 3: Write `lib.js`, `dom.js` and `api.js`**

`vigil/web/static/js/lib.js`:
```js
// Pure helpers. Times: a UTC instant is shifted by the volcano's offset and read in UTC, so the browser's own time
// zone never enters. Numbers: as the English bulletins print them (vigil.agent.render).

const pad = (n) => String(n).padStart(2, "0");
const iso = (ms) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");

function shifted(when, offsetHours) {
  if (!/(Z|[+-]\d\d:\d\d)$/.test(when)) throw new Error(`not a time with its zone: ${when}`);
  return new Date(Date.parse(when) + offsetHours * 3_600_000);
}

export function localTime(when, offsetHours, seconds = false) {
  const d = shifted(when, offsetHours);
  const hm = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  return seconds ? `${hm}:${pad(d.getUTCSeconds())}` : hm;
}

export function localDate(when, offsetHours) {
  const d = shifted(when, offsetHours);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

export function zone(offsetHours) {
  if (offsetHours === 0) return "UTC";
  return `UTC${offsetHours < 0 ? "−" : "+"}${Math.abs(offsetHours)}`;
}

export function number(value, decimals = 0) {
  return value.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export function plusMinus(value, sigma, unit) {
  if (unit === "deg") return `${number(value, 1)}° ± ${number(sigma, 1)}°`;
  if (unit === "m2") return `${number(value / 1e6, 1)} ± ${number(sigma / 1e6, 1)} km²`;
  return `${number(value)} ± ${number(sigma)} m`;
}

export const FOOT = 0.3048;
export const feet = (metres) => Math.round(metres / FOOT);

export function age(when, clock) {
  const minutes = (Date.parse(clock) - Date.parse(when)) / 60_000;
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${Math.floor(minutes)} min ago`;
  if (minutes < 48 * 60) return `${Math.floor(minutes / 60)} h ago`;
  return `${Math.floor(minutes / 1440)} d ago`;
}

export function ticks(start, end, stepMinutes) {
  const out = [], last = Date.parse(end), step = stepMinutes * 60_000;
  for (let t = Date.parse(start) + step; t < last; t += step) out.push(iso(t));
  return [...out, iso(last)];
}

const R = 6_371_008.8, rad = (d) => (d * Math.PI) / 180, deg = (r) => (r * 180) / Math.PI;

export function destination(lat, lon, bearingDeg, metres) {
  const d = metres / R, b = rad(bearingDeg), p1 = rad(lat), l1 = rad(lon);
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b));
  const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return [deg(p2), deg(l2)];
}

export function bearing(lat1, lon1, lat2, lon2) {
  const p1 = rad(lat1), p2 = rad(lat2), dl = rad(lon2 - lon1);
  const y = Math.sin(dl) * Math.cos(p2), x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return (deg(Math.atan2(y, x)) + 360) % 360;
}
```

`vigil/web/static/js/dom.js`: one helper that builds elements and only ever creates text nodes from strings.
```js
// Build DOM without HTML strings: every string child becomes a text node, so model text can never become markup.

export function el(tag, props = {}, ...children) {
  const node = tag.startsWith("svg:")
    ? document.createElementNS("http://www.w3.org/2000/svg", tag.slice(4))
    : document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.setAttribute("class", value);
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  append(node, children);
  return node;
}

function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function fill(node, ...children) {
  node.replaceChildren();
  append(node, children);
  return node;
}
```

`vigil/web/static/js/api.js`:
```js
// The dashboard's API: every call carries the scene (live, or a replay at its clock).

export class ApiError extends Error {}

export function sceneParams(state) {
  return state.mode === "replay" ? { replay: state.episode, at: state.clock } : {};
}

export async function get(path, params = {}, signal) {
  const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined));
  const response = await fetch(`${path}${query.size ? `?${query}` : ""}`, { signal });
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail ?? detail; } catch { /* not JSON */ }
    throw new ApiError(`${response.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }
  return response.json();
}

export function imageUrl(frameId, scene, { overlay = true, width = 1280 } = {}) {
  // scene: the clock the API answered with, so the image shows what the rest of the page shows
  const params = new URLSearchParams({ overlay, width });
  if (scene.replay) params.set("replay", scene.replay);
  params.set("at", scene.clock);
  return `/api/frames/${frameId}/image?${params}`;
}
```

- [ ] **Step 4: Write `index.html`**

Replace `vigil/web/static/index.html` with:
```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Volcano Vigil · {{volcano_name}}</title>
<meta name="description" content="An agent that watches the USGS webcams of {{volcano_name}} and turns frames into measurements and bilingual bulletins.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<link rel="stylesheet" href="/static/css/app.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script type="module" src="/static/js/main.js"></script>
</head>
<body>
<div class="top">
  <header class="bar">
    <div class="mark"><span class="mark-name">Volcano Vigil</span><span class="mark-place">{{volcano_name}} summit</span></div>
    <div class="modes" role="group" aria-label="Mode">
      <button type="button" class="mode" data-mode="live" aria-pressed="false">Live</button>
      <button type="button" class="mode" data-mode="replay" aria-pressed="false">Replay · Episode 55</button>
    </div>
    <div class="clock" id="clock">
      <span class="clock-local" id="clock-local">--:--</span>
      <span class="clock-zone" id="clock-zone"></span>
      <span class="clock-utc" id="clock-utc"></span>
    </div>
  </header>
  <p class="notice" role="note"><strong class="notice-tag">Not an official alert</strong> {{notice_lead}}<a href="{{official_url}}" rel="noopener" target="_blank">{{official_agency}}</a>.</p>
</div>

<main class="console">
  <section class="panel viewer" aria-label="Cameras">
    <div class="tabs" role="tablist" aria-label="Camera" id="camera-tabs"></div>
    <div class="frame-well" id="frame-well">
      <img id="frame-img" alt="">
      <p class="frame-empty" id="frame-empty" hidden></p>
    </div>
    <div class="frame-bar" id="frame-bar"></div>
    <div class="readout" id="readout"></div>
  </section>

  <section class="panel feed" aria-labelledby="feed-title">
    <div class="panel-inner">
      <div class="panel-head">
        <h2 id="feed-title">Bulletins</h2>
        <div class="seg aside" role="group" aria-label="Bulletin language">
          <button type="button" data-lang="en" aria-pressed="true">EN</button>
          <button type="button" data-lang="es" aria-pressed="false">ES</button>
        </div>
      </div>
      <ol class="bulletins" id="bulletins"></ol>
    </div>
  </section>

  <section class="panel drum" aria-labelledby="drum-title">
    <div class="panel-head">
      <h2 id="drum-title">Plume top above sea level</h2>
      <div class="legend aside" id="drum-legend"></div>
    </div>
    <div class="drum-figure" id="drum"></div>
    <details class="drum-table"><summary>Data table</summary><div id="drum-table"></div></details>
    <div id="results"></div>
  </section>

  <section class="panel map-panel" aria-labelledby="map-title">
    <div class="panel-head"><h2 id="map-title">Line of sight</h2></div>
    <div id="map" role="img" aria-label="Map of the cameras, the vent, the plume's measured side and the model wind"></div>
    <div class="map-legend" id="map-legend"></div>
  </section>

  <section class="panel trace" aria-labelledby="trace-title">
    <div class="panel-head">
      <h2 id="trace-title">Agent trace</h2>
      <label class="aside run-pick">Run <select id="run-select"></select></label>
    </div>
    <div class="trace-head" id="trace-head"></div>
    <ol class="steps" id="steps"></ol>
  </section>
</main>

<footer class="transport" id="transport" hidden>
  <div class="transport-buttons">
    <button type="button" class="icon-button" id="step-back" aria-label="Back 5 minutes">‹</button>
    <button type="button" class="icon-button play" id="play" aria-label="Play">▶</button>
    <button type="button" class="icon-button" id="step-forward" aria-label="Forward 5 minutes">›</button>
  </div>
  <div class="scrub">
    <input type="range" id="scrubber" min="0" max="0" value="0" aria-label="Simulated time">
    <p class="transport-status" id="transport-status"></p>
  </div>
  <label class="speed">Speed <select id="speed">
    <option value="2.5">2.5 min/s</option>
    <option value="5" selected>5 min/s</option>
    <option value="10">10 min/s</option>
  </select></label>
</footer>

<footer class="credits">
  Frames: U.S. Geological Survey, public domain. Heights and drift: SAM 3.1 masks on calibrated cameras; bulletins: Muse Spark (Meta). Wind: Open-Meteo. Map imagery: USGS The National Map.
</footer>
</body>
</html>
```

- [ ] **Step 5: Write `app.css`**

`vigil/web/static/css/app.css`. Write the tokens and the rules below as given; component details the later tasks need are listed with them. Keep every colour a token; no hex outside `:root`.
```css
/* Volcano Vigil. Dark only: the cameras are watched through the night and incandescence reads on black.
   One accent, lava. Plume, glow and HVO's values are data colours, stepped for the dark panels (validated with the
   dataviz palette checks); the --mask-* tokens are the evidence overlays' own colours (vigil.agent.bulletin.COLORS)
   and key only the masks drawn on the frames. Depth: hairlines only. Base unit 4px. */

:root {
  color-scheme: dark;
  --basalt: #100e0d;            /* the page: fresh lava's warm black */
  --basalt-1: #161311;          /* panels */
  --basalt-2: #1d1916;          /* raised: active tab, tooltips */
  --well: #0a0908;              /* insets: the frame, inputs, the drum's future */
  --notice: #1f1a11;            /* sulphur on basalt */
  --rule: rgba(236, 226, 212, 0.08);
  --rule-strong: rgba(236, 226, 212, 0.14);
  --steam: #ede4d6;             /* ink, primary */
  --ash: #b4aa9c;               /* secondary */
  --tephra: #8d8377;            /* labels, metadata */
  --cinder: #5a524a;            /* disabled, rejected frames */
  --lava: #f25820;              /* the accent: the clock, focus, play; also the fountain on dark surfaces */
  --plume: #259ed6;             /* the plume on dark surfaces */
  --plume-wash: rgba(37, 158, 214, 0.16);
  --glow: #b68c00;              /* glowing lava on dark surfaces; never beside the fountain in a chart */
  --lehua: #c3518d;             /* HVO's official values */
  --mask-plume: #50c8ff;        /* the colours the masks are drawn in on the frames */
  --mask-fountain: #ff5a1e;
  --mask-glow: #ffd200;
  --sulfur: #d8b04a;
  --font-sans: "IBM Plex Sans", system-ui, sans-serif;
  --font-cond: "IBM Plex Sans Condensed", "IBM Plex Sans", system-ui, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, monospace;
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px; --s6: 32px;
  --r-sm: 4px; --r-md: 6px;
  --ease: cubic-bezier(0.23, 1, 0.32, 1);
}

*, *::before, *::after { box-sizing: border-box; }
html { -webkit-font-smoothing: antialiased; text-size-adjust: 100%; }
body { margin: 0; background: var(--basalt); color: var(--steam); font: 400 14px/1.5 var(--font-sans); }
a { color: var(--steam); text-decoration-color: var(--rule-strong); text-underline-offset: 3px; }
a:hover { text-decoration-color: var(--steam); }
button, select, input { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--lava); outline-offset: 2px; border-radius: var(--r-sm); }
[hidden] { display: none !important; }
.mono, time { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.label { font: 600 11px/1.3 var(--font-cond); letter-spacing: 0.08em; text-transform: uppercase; color: var(--tephra); }

/* Top bar and notice stay together at the top. */
.top { position: sticky; top: 0; z-index: 1000; background: var(--basalt); }
.bar { display: flex; align-items: center; gap: var(--s5); min-height: 56px; padding: 0 var(--s5); border-bottom: 1px solid var(--rule); }
.mark { display: flex; align-items: baseline; gap: var(--s3); }
.mark-name { font: 600 15px/1 var(--font-cond); letter-spacing: 0.14em; text-transform: uppercase; }
.mark-place { color: var(--ash); font-size: 13px; }
.modes, .seg { display: inline-flex; padding: 2px; gap: 2px; background: var(--well); border: 1px solid var(--rule); border-radius: var(--r-md); }
.modes button, .seg button { border: 0; background: transparent; color: var(--ash); padding: 6px 12px; min-height: 32px; border-radius: var(--r-sm); cursor: pointer; font-size: 13px; transition: background-color 120ms var(--ease), color 120ms var(--ease); }
.modes button:hover, .seg button:hover { color: var(--steam); }
.modes button[aria-pressed="true"], .seg button[aria-pressed="true"] { background: var(--basalt-2); color: var(--steam); box-shadow: 0 0 0 1px var(--rule-strong); }
.modes button:disabled { color: var(--cinder); cursor: not-allowed; }
.clock { margin-left: auto; display: flex; align-items: baseline; gap: var(--s2); white-space: nowrap; }
.clock-local { font: 500 22px/1 var(--font-mono); letter-spacing: -0.01em; }
.clock[data-mode="replay"] .clock-local { color: var(--lava); }
.clock-zone, .clock-utc { font: 400 12px/1 var(--font-mono); color: var(--tephra); }
.notice { margin: 0; padding: 7px var(--s5); background: var(--notice); border-bottom: 1px solid rgba(216, 176, 74, 0.25); font-size: 12.5px; line-height: 1.45; color: var(--steam); text-wrap: pretty; }
.notice-tag { font: 600 11px/1 var(--font-cond); letter-spacing: 0.08em; text-transform: uppercase; color: var(--sulfur); margin-right: var(--s2); }

/* The console: the frame leads; the bulletins sit beside it at the frame's height. */
.console { display: grid; gap: var(--s4); padding: var(--s4) var(--s5) var(--s6); max-width: 1680px; margin: 0 auto;
  grid-template-columns: minmax(0, 1fr) 400px; grid-template-areas: "viewer feed" "drum map" "trace trace"; }
.viewer { grid-area: viewer; } .feed { grid-area: feed; } .drum { grid-area: drum; } .map-panel { grid-area: map; } .trace { grid-area: trace; }
.panel { background: var(--basalt-1); border: 1px solid var(--rule); border-radius: var(--r-md); min-width: 0; }
.panel-head { display: flex; align-items: center; gap: var(--s3); min-height: 48px; padding: var(--s2) var(--s4); border-bottom: 1px solid var(--rule); }
.panel-head h2 { margin: 0; font: 600 13px/1.2 var(--font-cond); letter-spacing: 0.08em; text-transform: uppercase; color: var(--ash); }
.aside { margin-left: auto; }
.feed { position: relative; min-height: 420px; }
.feed > .panel-inner { position: absolute; inset: 0; display: flex; flex-direction: column; }
.panel[aria-busy="true"] .busy-dim { opacity: 0.55; transition: opacity 160ms var(--ease); }
.error-note { margin: var(--s3) var(--s4); color: var(--ash); font-size: 13px; }

@media (max-width: 1180px) {
  .console { grid-template-columns: minmax(0, 1fr); grid-template-areas: "viewer" "feed" "drum" "map" "trace"; padding: var(--s4); }
  .feed { min-height: 0; } .feed > .panel-inner { position: static; max-height: 640px; }
  .bar { padding: 0 var(--s4); gap: var(--s3); } .notice { padding: 6px var(--s4); }
}
@media (max-width: 640px) {
  .bar { flex-wrap: wrap; padding: var(--s2) var(--s4); row-gap: var(--s2); }
  .mark-place { display: none; } .clock { margin-left: 0; width: 100%; }
}
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition: none !important; animation: none !important; } }

/* Transport (replay only) and credits. */
.transport { position: sticky; bottom: 0; z-index: 1000; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: var(--s4); padding: var(--s3) var(--s5); background: rgba(16, 14, 13, 0.94); backdrop-filter: blur(6px); border-top: 1px solid var(--rule-strong); }
.transport-buttons { display: flex; gap: var(--s1); }
.icon-button { width: 40px; height: 40px; display: grid; place-items: center; border-radius: var(--r-md); background: var(--basalt-2); border: 1px solid var(--rule); color: var(--steam); cursor: pointer; font-size: 18px; line-height: 1; transition: transform 120ms var(--ease); }
.icon-button:active { transform: scale(0.97); }
.icon-button:disabled { color: var(--cinder); cursor: not-allowed; }
.icon-button.play { background: var(--lava); border-color: var(--lava); color: var(--basalt); }
.scrub { min-width: 0; }
.scrub input[type="range"] { width: 100%; accent-color: var(--lava); }
.transport-status { margin: 2px 0 0; font: 400 12px/1.4 var(--font-mono); color: var(--ash); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
select { background: var(--well); border: 1px solid var(--rule-strong); border-radius: var(--r-sm); padding: 6px 8px; font: 400 12px/1.2 var(--font-mono); min-height: 32px; }
.speed, .run-pick { display: flex; align-items: center; gap: var(--s2); font: 600 11px/1 var(--font-cond); letter-spacing: 0.08em; text-transform: uppercase; color: var(--tephra); }
@media (max-width: 640px) { .transport { grid-template-columns: auto minmax(0, 1fr); padding: var(--s2) var(--s4); } .speed { display: none; } }
.credits { padding: var(--s4) var(--s5) var(--s6); color: var(--tephra); font-size: 12px; max-width: 1680px; margin: 0 auto; }
```
Tasks 7 and 8 append the rules of their components to this file.

- [ ] **Step 6: Write `main.js`: state, clock, mode, transport, loading**

`vigil/web/static/js/main.js` owns the state and the loading; the panels are render functions in their own modules (Tasks 7 and 8) that main imports. In this task, create those modules as stubs that export the functions named below and do nothing, so the page runs; Tasks 7 and 8 fill them.

State:
```js
const state = {
  config: null,          // /api/config
  mode: "replay",        // "replay" | "live"
  episode: null,         // replay key, e.g. "55"
  clock: null,           // replay: the simulated time (ISO, Z). live: null, and the API answers at now
  ticks: [],             // the replay's grid: lib.ticks(start, end, step_minutes)
  camera: null,          // the selected camera id
  frameChoice: "tracked",// "tracked" | "latest"
  pinned: null,          // a frame id picked on the drum, until the clock or the camera changes
  lang: "en",            // bulletin language
  openBulletin: null,    // the bulletin id expanded in the feed (null: the newest)
  runId: null,           // the traced run (null: the newest by the clock)
  playing: false,
  speed: 5,              // simulated minutes per wall second
};
```
Behaviour:
- **Start.** Fetch `/api/config`. Read the hash (`#mode=replay&at=2026-10-17T15:00:00Z&camera=kilauea-kp&lang=es&run=3`). Mode: the hash's, else `replay` when `config.replays` is not empty, else `live`. Disable the mode button that cannot work (no replay on disk; `live.available` false). Replay: `episode = config.replays[0].episode`, `ticks = lib.ticks(start, end, step_minutes)`, clock = the hash's `at` snapped to the nearest tick, else `ticks[0]`. Camera: the hash's if shown, else the first camera of the scene's camera list that the cameras answer says is `calibrated`, else the first. Write the hash back with `history.replaceState` on every change.
- **Load.** `load()` increments a generation counter, aborts the previous `AbortController`, sets `aria-busy="true"` on every panel, and fetches in parallel with `api.get(..., sceneParams(state), signal)`: `/api/cameras`; `/api/frames/latest` for the selected camera and, if different, for the measuring camera (the first `calibrated` camera, for the map's drift); `/api/frames?camera=` for each camera of the scene (the drum's strips); `/api/series?camera=<measuring camera>&target=plume&metric=top_altitude`; `/api/bulletins`; `/api/agent/trace` (with `run_id` when set; on a 404 reset `runId` to null and fetch again without it); `/api/replay` in replay mode; `/api/frames/<pinned>` when a frame is pinned. Use `Promise.allSettled`. If the generation is stale when they settle, drop the results. Otherwise call each panel's render with its data or its error (a failed panel shows `.error-note` text and keeps the rest of the page working), then clear `aria-busy`. Every response carries `clock`: the scene for images is `{replay: state.episode or null, clock: <that clock>}`.
- **Clock display.** `#clock-local` = `lib.localTime(clock, offset)`, `#clock-zone` = `lib.zone(offset)` plus the local date when it is not today's in live mode, `#clock-utc` = `lib.localTime(clock, 0) + " UTC"`. `#clock[data-mode]` = the mode. In live mode the clock is the API's `clock`.
- **Mode switch.** Buttons `.mode[data-mode]` set `aria-pressed`. Replay shows `#transport`; live hides it, stops playing, and polls `load()` every 60 s (clear the interval when leaving live).
- **Transport.** `#scrubber` max = `ticks.length - 1`; `input` moves the clock to that tick after 120 ms without further input; `change` loads at once. `#step-back` / `#step-forward` move one tick (disabled at the ends). `#play` toggles playing (label ▶ / ❚❚ and `aria-label` Play / Pause): while playing, `await load()`, then wait `step_minutes / speed` seconds, then advance; stop at the last tick. `#speed` sets `speed`. Keyboard, when the focus is not in an input or select: Space toggles play, ← and → step. Changing the clock clears `pinned`.
- **Transport status** (`#transport-status`): from the newest tick report with `clock <= state.clock`: `"Step 05:00 · 6 frames checked · SAM tracked KPcam, K2cam, V1cam · bulletin #2"` (local times; list only what the report has: `assessed`, `tracked[].camera_id` as short names, `bulletin_id`, and `errors.length` as "· 1 error" when present).
- **Cross-panel actions** passed to the renderers as callbacks: `selectCamera(id)`, `setFrameChoice(choice)`, `pinFrame(frameId)`, `setLang(lang)`, `openBulletin(id)`, `traceRun(runId)` (sets `runId`, loads, then scrolls `#trace-title` into view).

Panel modules and the functions main calls (stubs now, filled in Tasks 7 and 8):
- `viewer.js`: `renderViewer(root, data, ctx)` where `data = {cameras, latest, pinnedFrame}`.
- `feed.js`: `renderFeed(root, data, ctx)` where `data = {bulletins}`.
- `trace.js`: `renderTrace(root, data, ctx)` where `data = {trace}`.
- `drum.js`: `renderDrum(root, data, ctx)` where `data = {series, strips, bulletins, replay}`.
- `map.js`: `renderMap(root, data, ctx)` where `data = {cameras, measuring, bulletins}`.
- `results.js`: `renderResults(root, data)` where `data = {replay}`.
`ctx` = `{state, config, scene, actions}`, where `scene = {replay, clock}` is the answered clock.

- [ ] **Step 7: Run the tests and look at the page**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_static.py` then the full suite. Expected: PASS.
Run `vigil-web --port 8765` in the background, take a headless Edge screenshot at 1440×2000 and at 390×1600 (command in "Facts"), and read the PNGs. Expected: the top bar, the notice with its link, the empty panels in their grid, the transport bar. Stop the server.

- [ ] **Step 8: Commit**

```bash
git add vigil/web/static/index.html vigil/web/static/css/app.css vigil/web/static/js/ tests/js/lib.test.mjs tests/test_web_static.py
git commit -m "Lay out the dashboard page with its notice, tokens, clock, replay transport and tested helpers"
```

---

### Task 7: The panels: cameras and frame, readout, bulletins, agent trace

**Files:**
- Modify: `vigil/web/static/js/viewer.js`, `feed.js`, `trace.js`, `vigil/web/static/css/app.css`

Rules for every panel: build DOM with `el()`/`fill()` from `dom.js` only; times through `lib.localTime(…, config.volcano.utc_offset_hours)` with `lib.zone(…)`; numbers through `lib.number`/`lib.plusMinus`; the camera's short name is its `name` up to the first ` (` (`"KPcam (wide view, plume height)"` → `KPcam`), with the full name as the `title`.

- [ ] **Step 1: The viewer** (`viewer.js`)

- **Camera tabs** (`#camera-tabs`, `role="tablist"`): one `<button role="tab" aria-selected>` per camera of `/api/cameras`, in its order: a condition dot `<span class="cond-dot" data-condition="…">`, the short name, and the condition as a word in mono (`usable`, `night`, `fog`, `frozen`, `stale`, `unchecked`, `no frames`, `clock mismatch`, `rejected`); `title` = full name plus "· last frame 12 min ago". Click → `actions.selectCamera(id)`. Arrow keys move between tabs.
- **Frame**: the frame shown is the pinned frame if any, else `tracked` when `frameChoice` is `"tracked"` and `tracked` exists, else `latest`. `#frame-img.src = api.imageUrl(frame.frame_id, ctx.scene)` (width 1280; 1920 when the well is wider than 1280 CSS px × devicePixelRatio). `alt` = `"<short name> frame <id>, <local time> <zone>"`. While the new image loads, keep the old one and set `aria-busy` on `#frame-well`; swap on `load`. No frame at all → hide the image and show `#frame-empty`: "No frame from <short name> by <local time>." 
- **Frame bar** (`#frame-bar`): left, a `.seg` with two buttons, "Last tracked HH:MM" and "Latest HH:MM" (each disabled when that frame is missing; hidden while a frame is pinned, which shows "Picked on the chart · back to latest" as a link-button that clears the pin); then the capture time `HH:MM:SS <zone>` and `HH:MM UTC`, the age against the scene clock (`lib.age`), and the verdict (`usable`, or the reasons joined); right, a key per target present on the frame: `<span class="key" data-target="plume">plume</span>` (labels: plume, lava fountain, glow). When the shown frame is `latest` and has no detections while the camera has a tracked frame, add the note "SAM tracks each hour once it closes."
- **Readout** (`#readout`), for the shown frame: take its first `plume` detection (detections come largest first).
  - With `measurements.top_altitude`: the hero. Label "Plume top above sea level"; value `lib.number(v)` in `.hero-value`, unit "m" in `.hero-unit`; below, in `.hero-sigma`, `"± <σ> m · <feet> ft"` (feet of the value). Then the facts row (`.facts`), each a `.label` over a mono value, only those present: "Above the vent" (`top_height`, plusMinus), "Plume side" (`drift_bearing`, `<v>°` and "of the sightline"), "Across the sightline" (`drift_offset`, plusMinus), "Area" (`area`, plusMinus in km²). Meta line: `"<short name> · frame <id> · <HH:MM:SS zone> · SAM 3.1 mask, calibrated camera"`.
  - Camera not `calibrated` (from `/api/cameras`): `.readout-note` "Heights are not measured on <short name>: its view is not calibrated yet. KPcam measures the plume." Keep the detected targets as a line: "SAM sees: lava fountain, plume".
  - Calibrated but no plume measurement on this frame: "No plume measured on this frame." plus the detected targets if any.
- **CSS** (append to `app.css`):
```css
.tabs { display: flex; gap: 2px; padding: var(--s1) var(--s2) 0; border-bottom: 1px solid var(--rule); overflow-x: auto; }
.tab { display: flex; align-items: center; gap: var(--s2); min-height: 44px; padding: 0 var(--s3); border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--ash); cursor: pointer; white-space: nowrap; }
.tab:hover { color: var(--steam); }
.tab[aria-selected="true"] { color: var(--steam); border-bottom-color: var(--lava); }
.tab-name { font-weight: 500; }
.tab-cond { font: 400 12px/1 var(--font-mono); color: var(--tephra); }
.cond-dot { width: 8px; height: 8px; border-radius: 50%; border: 1.5px solid var(--cinder); flex: none; }
.cond-dot[data-condition="usable"] { background: var(--steam); border-color: var(--steam); }
.cond-dot[data-condition="unchecked"] { border-color: var(--ash); }
.frame-well { position: relative; aspect-ratio: 16 / 9; background: var(--well); overflow: hidden; }
.frame-well img { display: block; width: 100%; height: 100%; object-fit: contain; transition: opacity 160ms var(--ease); }
.frame-well[aria-busy="true"] img { opacity: 0.6; }
.frame-empty { position: absolute; inset: 0; margin: 0; display: grid; place-items: center; padding: var(--s5); color: var(--tephra); text-align: center; }
.frame-bar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s2) var(--s4); padding: var(--s2) var(--s4); border-top: 1px solid var(--rule); font-size: 12px; color: var(--ash); }
.frame-bar .keys { margin-left: auto; display: flex; gap: var(--s3); }
.key { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ash); }
.key::before { content: ""; width: 14px; height: 3px; border-radius: 2px; background: var(--key, var(--ash)); }
.key[data-target="plume"] { --key: var(--mask-plume); } .key[data-target="fountain"] { --key: var(--mask-fountain); } .key[data-target="incandescence"] { --key: var(--mask-glow); }
.readout { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: end; gap: var(--s3) var(--s6); padding: var(--s4); border-top: 1px solid var(--rule); }
.hero { display: grid; gap: var(--s1); }
.hero-figure { display: flex; align-items: baseline; gap: var(--s2); }
.hero-value { font: 600 48px/1 var(--font-sans); letter-spacing: -0.02em; }
.hero-unit { font: 500 20px/1 var(--font-sans); color: var(--ash); }
.hero-sigma { font: 400 14px/1.3 var(--font-mono); color: var(--ash); }
.facts { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--s3) var(--s5); margin: 0; }
.facts div { display: grid; gap: 2px; } .facts dd { margin: 0; font: 400 13px/1.3 var(--font-mono); color: var(--steam); }
.readout-meta { grid-column: 1 / -1; margin: 0; font: 400 12px/1.4 var(--font-mono); color: var(--tephra); }
.readout-note { grid-column: 1 / -1; margin: 0; color: var(--ash); }
.link-button { background: none; border: 0; padding: 6px 0; color: var(--steam); text-decoration: underline; text-decoration-color: var(--rule-strong); text-underline-offset: 3px; cursor: pointer; font-size: 13px; }
.link-button:hover { text-decoration-color: var(--steam); }
@media (max-width: 640px) { .readout { grid-template-columns: minmax(0, 1fr); } .facts { justify-content: flex-start; } .hero-value { font-size: 40px; } }
```
(Use `<dl class="facts">` with `<div><dt class="label">…</dt><dd>…</dd></div>` per fact.)

- [ ] **Step 2: The bulletin feed** (`feed.js`)

- `#bulletins` lists the bulletins newest first. The expanded one is `state.openBulletin`, else the newest. Each `<li class="bulletin">` has a summary `<button class="b-summary" aria-expanded>`: the local time `HH:MM` (`.b-time`), the activity level as `<span class="level" data-level="fountaining">` with the level word in the chosen language (`b[lang].level`), and the headline (`b[lang].headline`). Click → `actions.openBulletin(id)`.
- The expanded body (`.b-body`), all text from `b[lang]`, inserted as text:
  1. the disclaimer (`.b-disclaimer`);
  2. the body split on blank lines into paragraphs;
  3. the measurements table (`.b-table`) from `header` and `rows`, when rows exist;
  4. the wind sentence (`wind_text`) when present (`.b-wind`);
  5. the evidence figures (`.b-evidence`): `<img src="/media/<overlay>" loading="lazy" alt="<caption>">` with the caption in the chosen language (`caption_en`/`caption_es`) and `"<camera short name>, HH:MM"`;
  6. the check line (`.b-check`, mono): verified → "✓ Every number checked against the stored measurements"; else "Some numbers could not be checked against the stored measurements"; then the `notes` as a small list when present;
  7. the source line: "Official source: " + link (`official_agency`, `official_url`, `target="_blank" rel="noopener"`);
  8. a `.link-button` "Agent trace of this bulletin" → `actions.traceRun(b.run_id)`.
- The EN/ES `.seg` in the panel head: `aria-pressed`, click → `actions.setLang(lang)`; set `lang` on each article (`lang="es"`).
- Empty: "No bulletin yet by HH:MM <zone>. The agent writes one every hour." In live mode: "No bulletin in the database yet."
- **CSS** (append):
```css
.bulletins { list-style: none; margin: 0; padding: 0; overflow-y: auto; min-height: 0; flex: 1; }
.bulletin + .bulletin { border-top: 1px solid var(--rule); }
.b-summary { display: grid; grid-template-columns: 48px minmax(0, 1fr); gap: 2px var(--s3); width: 100%; padding: var(--s3) var(--s4); border: 0; background: transparent; text-align: left; cursor: pointer; }
.b-summary:hover { background: rgba(236, 226, 212, 0.03); }
.b-time { grid-row: span 2; font: 500 13px/1.5 var(--font-mono); color: var(--ash); }
.b-headline { font-weight: 500; text-wrap: pretty; }
.bulletin[aria-current="true"] .b-headline { font-size: 15px; }
.level { display: inline-flex; align-items: center; gap: 6px; font: 600 11px/1.3 var(--font-cond); letter-spacing: 0.06em; text-transform: uppercase; color: var(--ash); }
.level::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--level, transparent); border: 1.5px solid var(--level, var(--cinder)); }
.level[data-level="fountaining"] { --level: var(--lava); } .level[data-level="incandescence"] { --level: var(--glow); }
.level[data-level="degassing"] { --level: var(--plume); } .level[data-level="quiet"] { --level: var(--ash); }
.b-body { padding: 0 var(--s4) var(--s4) calc(48px + var(--s3) + var(--s4)); }
.b-body p { margin: 0 0 var(--s3); text-wrap: pretty; }
.b-disclaimer { font-size: 12px; color: var(--ash); border-left: 2px solid var(--sulfur); padding-left: var(--s3); }
.b-table { width: 100%; border-collapse: collapse; margin: 0 0 var(--s3); font-size: 12px; }
.b-table th { text-align: left; padding: 4px 8px 4px 0; border-bottom: 1px solid var(--rule); font: 600 10.5px/1.2 var(--font-cond); letter-spacing: 0.06em; text-transform: uppercase; color: var(--tephra); }
.b-table td { padding: 5px 8px 5px 0; border-bottom: 1px solid var(--rule); vertical-align: top; color: var(--ash); }
.b-table td:nth-child(3) { font-family: var(--font-mono); color: var(--steam); white-space: nowrap; }
.b-wind { font-size: 13px; color: var(--ash); }
.b-evidence { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: var(--s2); margin: 0 0 var(--s3); }
.b-evidence figure { margin: 0; }
.b-evidence img { display: block; width: 100%; border-radius: var(--r-sm); outline: 1px solid rgba(255, 255, 255, 0.1); outline-offset: -1px; }
.b-evidence figcaption { margin-top: 4px; font-size: 11.5px; color: var(--ash); }
.b-check { font: 400 12px/1.4 var(--font-mono); color: var(--ash); }
.b-source { font-size: 13px; }
@media (max-width: 1180px) { .b-body { padding-left: var(--s4); } }
```

- [ ] **Step 3: The agent trace** (`trace.js`)

- `#run-select`: one `<option>` per run by the clock, `"HH:MM · run <id> · <status>"`, the traced run selected; change → `actions.traceRun(id)`.
- `#trace-head` (mono, ash): `"Run <id> at HH:MM <zone> · <status> · <turns> turns · $<cost 4 decimals> · <model>"`, then the task in steam text, then the error if any. With a `bulletin_id`, a `.link-button` "Open bulletin #<id>" → `actions.openBulletin(id)`.
- `#steps`, one `<li class="step">` per step with `.step-turn` ("T1") and the content:
  - model step with text: the text (`.step-say`). The run's last model step whose text parses as JSON is the bulletin draft: show "Final answer: the bulletin draft" and a `<details><summary>Draft JSON</summary><pre>` with `JSON.stringify(parsed, null, 2)`. Reasoning, when present: `<details><summary>Reasoning summary</summary><p>`.
  - tool step: `.step-call` with the function name (`.fn`) and its arguments as `name(key=value, …)`, each value `JSON.stringify`'d (if the arguments are not an object, show them raw); `.step-meta`: `ok` or `✕ error`, `latency_ms / 1000` s with one decimal, `$cost` with 4 decimals; the result in `<details><summary>Result</summary><pre>` pretty-printed.
- Empty: "No agent run by HH:MM <zone>."
- **CSS** (append):
```css
.trace-head { display: grid; gap: var(--s1); padding: var(--s3) var(--s4); border-bottom: 1px solid var(--rule); font: 400 12px/1.5 var(--font-mono); color: var(--ash); }
.trace-head .task { font: 400 14px/1.5 var(--font-sans); color: var(--steam); }
.steps { list-style: none; margin: 0; padding: var(--s1) var(--s4) var(--s4); }
.step { display: grid; grid-template-columns: 36px minmax(0, 1fr); gap: var(--s3); padding: var(--s2) 0; border-bottom: 1px solid var(--rule); }
.step-turn { font: 500 12px/1.6 var(--font-mono); color: var(--tephra); }
.step-say { margin: 0; text-wrap: pretty; }
.step-call { font: 400 12.5px/1.6 var(--font-mono); color: var(--ash); overflow-wrap: anywhere; }
.step-call .fn { color: var(--steam); font-weight: 500; }
.step-meta { font: 400 11.5px/1.6 var(--font-mono); color: var(--tephra); }
.step-meta .failed { color: var(--steam); font-weight: 500; }
details summary { cursor: pointer; color: var(--ash); font-size: 12px; padding: 2px 0; }
pre { margin: var(--s1) 0 0; max-height: 280px; overflow: auto; padding: var(--s2) var(--s3); background: var(--well); border: 1px solid var(--rule); border-radius: var(--r-sm); font: 400 11.5px/1.5 var(--font-mono); color: var(--ash); white-space: pre-wrap; overflow-wrap: anywhere; }
```

- [ ] **Step 4: Check**

Run the full suite (the no-HTML-sink test covers the new files). Start `vigil-web --port 8765`, screenshot the replay at `at=2026-10-17T15:00:00Z` (1440 wide) and at `at=2026-10-17T19:30:00Z`, and live; read the PNGs. Expected at 15:00Z: KPcam selected, its 14:55 frame with the plume mask, the hero `6,964 m` with `± 419 m`, bulletin #2 expanded in English with its table, the trace of run 2 with 5 turns. Fix what looks wrong; report what you saw.

- [ ] **Step 5: Commit**

```bash
git add vigil/web/static/js/viewer.js vigil/web/static/js/feed.js vigil/web/static/js/trace.js vigil/web/static/css/app.css
git commit -m "Show the camera frame with its masks and readout, the bilingual bulletins and the agent trace"
```

---

### Task 8: The drum, the line-of-sight map, the replay's results

**Files:**
- Modify: `vigil/web/static/js/drum.js`, `map.js`, `results.js`, `vigil/web/static/css/app.css`

The chart colours were validated while planning (see "Design direction"): plume `--plume`, HVO `--lehua`, fountain `--lava`. Do not add another hue to the drum.

- [ ] **Step 1: (done in planning) chart colours validated**

- [ ] **Step 2: The drum** (`drum.js`), an SVG drawn into `#drum`

- **Domain.** x: replay `[episode start, episode end]`; live `[clock − 24 h, clock]`. y: altitude 0 to `max(9000, ceil(max(value + σ) / 1000) × 1000)` m. Size: the container's width (re-render on resize with a `ResizeObserver`), plot height 220 px, then one 16 px strip row per camera, margins left 48, right 16, top 20, bottom 24.
- **Grid and axes** (`.drum-grid`, 1px hairlines, never dashed): y every 2,000 m labelled `0`, `2 km`, `4 km`, `6 km`, `8 km`; x every hour (replay) or every 3 h (live) labelled in local time `03:00`. A hairline at the vent's elevation (`config.vent.elev_m`) labelled `vent 1,080 m` at the right, above the line.
- **The future** (replay only): the area right of the clock filled `var(--well)`. Nothing is drawn there.
- **The series** (KPcam plume `top_altitude`, `series.points`): a σ band (`.drum-band`, polygon of value ± σ) and a 2px line (`.drum-line`); break both where two points are more than 30 min apart. A dot (r 4, 2px ring in the panel colour) on the last point only, with a direct label of its value "6,964 m" to its right when there is room.
- **HVO's values** (`series.official`, only those the API sent): a 1.5px `--lehua` line from `start` to `end` at `value_m`, a diamond (10px, `--lehua` fill, 2px ring in the panel colour) at the middle, and a direct label in ink (not in lehua) "HVO 7,620 m"; an upper bound (`upper_bound`) draws the diamond with a short downward tick and the label "HVO < 3,962 m".
- **HVO's phases** (`replay.official_phases`, only those sent): onset and end as vertical hairlines (steam, 35 % opacity) labelled "onset (HVO)" / "end (HVO)" at the top; peak as a faint band (steam, 5 % opacity) between its two times labelled "peak (HVO)".
- **Bulletins** by the clock: a small lava triangle (6px) at the top edge at each bulletin's clock; click → `actions.openBulletin(id)`; its `<title>` "Bulletin HH:MM · <level>".
- **The clock** (replay): a 1.5px lava vertical line at the clock with its local time on top.
- **Strips** (one row per camera of the scene, labelled with the short name at the left): each frame of `/api/frames` a 2 px wide, 10 px tall rect at its time; fill by what SAM saw: fountain → `--lava`; else plume → `--plume`; usable with nothing, or glow only → `--ash` at 50 %; rejected or unassessed → `--cinder`. (Glow is left out: beside the fountain it fails the colour-blind check.) A frame rect's `<title>`: "HH:MM:SS · usable · plume, lava fountain".
- **Hover and click.** A crosshair (vertical hairline) snaps to the nearest series point by time; the tooltip (an absolutely positioned `.tooltip` div, built with `el()`) leads with the value: "6,964 ± 419 m" (strong), then "22,848 ft above sea level", then "04:55:05 UTC−10 · frame 29". Same on keyboard: the SVG has `tabindex="0"`, ← and → move between points. Click (or Enter) → `actions.pinFrame(frame_id)` (pins that KPcam frame in the viewer and selects KPcam).
- **Legend** (`#drum-legend`, HTML): a line key "KPcam plume top ± σ", a diamond key "HVO (official)", a triangle key "Bulletin". Text in ink colours; the keys carry the colour.
- **Data table** (`#drum-table` inside the `<details>`): time (local), value ± σ, frame id, one row per point.
- **Empty**: "No plume measurements by HH:MM." (live: "No plume measurements in the last 24 hours.")

- [ ] **Step 3: The map** (`map.js`), Leaflet in `#map`

- Create the map once: `scrollWheelZoom: false`, `attributionControl: true`; tiles `https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}` with `maxZoom: 16` and attribution `'Imagery: <a href="https://www.usgs.gov/programs/national-geospatial-program/national-map">USGS The National Map</a>'` (a constant). Fit the bounds of the vent and the cameras with positions once, with 24 px padding.
- Leaflet treats string tooltip content as HTML: pass every tooltip as a DOM node built with `el()`.
- **Vent**: a circle marker (radius 6, 2px lava stroke, basalt fill), permanent tooltip "Vent".
- **Cameras** with a `position`: an `L.circle` of radius `sigma_m` (1px steam stroke at 45 % opacity, no fill), a dot (circle marker radius 4, steam fill), a tooltip "<short name> · position ±<sigma_m> m", and the sightline from the camera to the vent (1px steam at 45 %). Cameras without a position are not drawn; the legend says "V1cam: position not known well enough to draw" for each.
- **The plume's side**: from the measuring camera's newest visible plume detection that has `drift_bearing` and `drift_offset` (from its `/api/frames/latest`, `tracked` frame, first plume detection): a 3px plume-coloured line from the vent to `lib.destination(vent, drift_bearing, drift_offset)` with a small arrowhead (a polygon). Tooltip: "Plume side 224° · 2,628 ± 538 m across KPcam's line of sight · 04:55".
- **Wind**: from the newest bulletin by the clock with a `wind` (`wind.layer_mean`): a 2px steam line from the vent towards `toward_deg`, 600 m per m/s of `speed_ms`, with an arrowhead. Tooltip: "Model wind 3.3 m/s toward 151° · mean 1,080–6,964 m · model hour 05:00".
- **Legend** (`#map-legend`, HTML text): one row per drawn element with a key, plus the check from that bulletin's `wind.drift_check`: "The plume sits 73° from where the wind blows: consistent." (`consistent` true / false / null → "consistent" / "not consistent" / "too calm to tell"), and the sentence "One camera sees only the part of the drift across its line of sight."
- Redraw the layers (not the map) on every render.
- **CSS** (append):
```css
#map { height: 340px; background: var(--well); }
.leaflet-container { background: var(--well); font-family: var(--font-sans); }
.leaflet-tile-pane { filter: saturate(0.55) brightness(0.62) contrast(1.05); }
.leaflet-control-attribution { background: rgba(16, 14, 13, 0.8) !important; color: var(--tephra) !important; }
.leaflet-control-attribution a { color: var(--ash) !important; }
.leaflet-bar a { background: var(--basalt-2) !important; color: var(--steam) !important; border-color: var(--rule-strong) !important; }
.leaflet-tooltip.map-label { background: var(--basalt-2); border: 1px solid var(--rule-strong); border-radius: var(--r-sm); color: var(--steam); box-shadow: none; font: 400 12px/1.3 var(--font-mono); padding: 3px 6px; }
.leaflet-tooltip.map-label::before { display: none; }
.map-legend { display: grid; gap: 6px; padding: var(--s3) var(--s4); font-size: 12px; color: var(--ash); }
.map-legend .row { display: flex; gap: var(--s2); align-items: baseline; }
.map-legend .swatch { flex: none; width: 14px; height: 3px; border-radius: 2px; background: var(--swatch); transform: translateY(-3px); }
```
(Give tooltips `className: "map-label"`.)

- [ ] **Step 4: The results** (`results.js`) into `#results`

Only when `replay.results` is not null (the clock at the episode's end): a heading "Against the official values" and, per table, its title and a `.b-table`-styled table of `header` and `rows`, plus "Meta API cost of the replay: $1.03" from `cost_usd`. Otherwise empty.

- [ ] **Step 5: Drum and results CSS** (append)
```css
.drum-figure { position: relative; padding: var(--s2) var(--s4) var(--s3); }
.drum-figure svg { display: block; width: 100%; overflow: visible; }
.drum-figure svg text { font: 400 11px var(--font-mono); fill: var(--tephra); }
.drum-grid line { stroke: var(--rule); stroke-width: 1; shape-rendering: crispEdges; }
.drum-vent { stroke: var(--rule-strong); }
.drum-future { fill: var(--well); }
.drum-band { fill: var(--plume-wash); }
.drum-line { fill: none; stroke: var(--plume); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.drum-dot { fill: var(--plume); stroke: var(--basalt-1); stroke-width: 2; }
.drum-official { fill: none; stroke: var(--lehua); stroke-width: 1.5; }
.drum-diamond { fill: var(--lehua); stroke: var(--basalt-1); stroke-width: 2; }
.drum-phase { stroke: var(--steam); stroke-opacity: 0.35; }
.drum-peak { fill: var(--steam); fill-opacity: 0.05; }
.drum-cursor { stroke: var(--lava); stroke-width: 1.5; }
.drum-bulletin { fill: var(--lava); cursor: pointer; }
.drum-figure svg text.value { fill: var(--steam); font-weight: 500; }
.tooltip { position: absolute; pointer-events: none; z-index: 10; display: grid; gap: 2px; padding: 6px 8px; background: var(--basalt-2); border: 1px solid var(--rule-strong); border-radius: var(--r-sm); font: 400 12px/1.35 var(--font-mono); color: var(--ash); white-space: nowrap; }
.tooltip strong { color: var(--steam); font-weight: 500; }
.legend { display: flex; flex-wrap: wrap; gap: var(--s2) var(--s4); font-size: 12px; color: var(--ash); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.drum-table { padding: 0 var(--s4) var(--s3); }
.drum-table table, .results table { width: 100%; border-collapse: collapse; font-size: 12px; }
#results { padding: 0 var(--s4) var(--s4); }
#results h3 { margin: var(--s4) 0 var(--s2); font: 600 12px/1.2 var(--font-cond); letter-spacing: 0.08em; text-transform: uppercase; color: var(--ash); }
```

- [ ] **Step 6: Check**

Full suite. Then `vigil-web --port 8765` and screenshots: replay at `13:30Z` (onset line, little data), `15:00Z` (the peak: band and line rising, no HVO diamond yet), `16:10Z` (two HVO diamonds), `19:30Z` (everything plus the results), live; desktop 1440 and phone 390. Read them. Expected: no label collisions, the future blank, the diamonds appearing only after their windows close, the map with the sightlines, KPcam's ±500 m circle, the plume side towards the SW and the wind arrow towards the SE. Report what you saw and fixed.

- [ ] **Step 7: Commit**

```bash
git add vigil/web/static/js/drum.js vigil/web/static/js/map.js vigil/web/static/js/results.js vigil/web/static/css/app.css
git commit -m "Draw the plume record as a drum that inks up to the clock, the line-of-sight map and the replay's results"
```

---

### Task 9: Acceptance, polish and the roadmap (orchestrator)

- [ ] Run the full suite; record the count.
- [ ] Run `vigil-web` on the real data and review both modes with headless Edge screenshots at 1440 and 390 wide: replay at 13:05Z, 14:00Z, 15:00Z, 16:10Z, 19:00Z, 19:30Z; live. Check against the design direction (swap, squint, signature and token tests) and the leak rule: at each replay clock, no frame, mask, number, bulletin, run, HVO value or phase from after it. Fix what fails, in small commits.
- [ ] Verify by hand at 15:00Z that the hero, the bulletin table and the trace agree on 6,964 ± 419 m (frame 29, 04:55:05 HST).
- [ ] Tick Phase 6 in `docs/PLAN.md` (with what changed against the roadmap), update its module map (`web/app.py web/views.py web/static/`, "exists, phase 6"), the test count in "How to resume", and add the dashboard's facts.
- [ ] Append the execution notes to this plan.
- [ ] Push; update the status memory.

## Execution notes
