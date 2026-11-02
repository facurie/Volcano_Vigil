# Phase 8: Fountaining Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Volcano Vigil says, within minutes, when lava fountaining starts and stops at Kīlauea's summit. Each change is an ES/EN alert with the frame and its SAM mask, the detection time, the disclaimer and the link to HVO. The alert is stored in the database, shown as a banner on the dashboard (live and in replay, bounded by the clock) and posted to a public Telegram channel. The alerts must stay silent through the 29 h of overflows before episode 55.

**Architecture:**
- **New module `vigil/alerts.py`.** It holds an `AlertWatcher` that runs every minute as its own process (`vigil-alerts`), next to ingest and the pipeline, so hourly tracking never delays it.
- **Each step has three stages:**
  1. Free local checks (`vigil.quality`) skip dark, foggy and stale frames and say whether lava is visible.
  2. SAM 3.1 image mode (`lava fountain`, $0.0025) looks at a frame when a look is due.
  3. Muse Spark compares the frame with the camera's frame from 30 min earlier, but only for borderline sizes and to confirm an onset.
- **State machine per volcano** (`quiet` → `fountaining` → `quiet`): the newest row of the `alerts` table holds it, so a restart or a replay resume keeps it.
- **Telegram:** `vigil/telegram.py` posts through the Bot API and never logs or raises the token.
- **Replay:** `vigil-replay` runs the same watcher on a 1-minute simulated clock, over episode 55 and over the overflow window (`--quiet overflows`).
- **Dashboard:** `/api/alerts` and a banner under the sticky notice.

**Tech stack:** Python 3.12, httpx (Telegram Bot API, multipart `sendPhoto`), the existing `MetaClient` (`segment_image`, `ask_json`), SQLite, Pillow/numpy, FastAPI, plain ES modules.

---

## Decisions (with the user, 2026-11-01)

1. **Calibration spend approved, up to $1.00.** Spent: $0.7505 (291 SAM images and 4 Muse Spark calls, tag `probe:alerts` in the local ledger).
2. **V1cam is ingested live for alerts only.** A new camera flag `track: false` keeps V1 out of the pipeline's hourly SAM windows. The pipeline still gives V1 frames local verdicts (no Muse Spark), so the dashboard shows their condition. V1 is the only camera that saw episode 55's fountain in time: K2 only from 04:10–04:22 HST, KP only the plume rising from 03:45.
3. **Alerts get $0.75/day reserved inside the $5 cap.** The pipeline's ledger stops at $5 − $0.75 = $4.25 of the day's total. The alerts' calls run under a per-UTC-day tag `alerts:<date>` with a $0.75 budget.
4. **The acceptance follows the visible fountain, not HVO's 03:19 onset** (the user chose "Visible fountaining").
   - On V1cam, a fountain far larger than anything in the overflow frames appears at **03:03 HST**. HVO's onset (03:19) is defined by tremor, tilt and the doubling of that same north-vent fountain.
   - **New acceptance:**
     - the episode 55 onset alert fires between 03:03 (the first frame that shows the fountain) and 03:43 (HVO's notice);
     - zero alerts fire on the 29 h of overflow frames;
     - the end alert fires between 09:03 and 09:15 HST (HVO's end notice came at 09:11).
   - **Wording:** the text says "lava fountaining seen", never "episode declared", and it names HVO as the one that declares episodes.
5. **Design refinement (raise it at plan approval).** Muse Spark confirms **every** onset before it goes public, not only borderline sizes.
   - Size thresholds are shares of the frame, so they belong to one PTZ framing. Zoomed in further than V1's 9.4–9.6×, an overflow dome could pass the threshold.
   - Muse Spark told overflow domes from the fountain on 4 of 4 frame pairs, for about $0.006 per onset.
   - It is asked once per candidate onset, so the cost is negligible.

## Facts this plan relies on (measured while planning, 2026-11-01)

Raw results are in `data/calibration/alerts/` (git-ignored): `probe_*.jsonl`, `local_stats.csv`, the probe scripts and two contact sheets. Task 1 writes them up in `docs/research/alerts_calibration.md`.

- **Frames backfilled from AshCam** (free) for Oct 16 08:00Z – Oct 17 12:59Z: V1 863, K2 863, KP 345 and F1 116, now in `data/vigil.sqlite`. With episode 55 (13:00–19:30Z), the database holds 35.5 h of V1 and K2 at 2-min cadence. AshCam drops these frames around Nov 16.
- **V1cam's framing:**
  - P 8778 / 8.9× until about 21:00 HST Oct 16, then P 9321 / 9.4× until 03:47 HST Oct 17.
  - Episode 55 then switches to 1.4× at 03:49 and 1.0× at 04:43.
  - Live on 2026-11-01 08:09 HST: P 9594 / 9.6×, the cone close up, the same kind of view.
- **Local signals cannot tell overflows from the episode:**
  - V1's whole-frame glow fraction has a median of 0.026 on the overflow nights (p95 0.26, max 0.59) and 0.29 in the onset hour (max 0.52).
  - It rises steadily from 0.075 at 02:49 HST to 0.30 at 03:19 HST, with no step at the onset.
  - After the end (09:03, daylight) it stays at 0.03–0.05, because the flows are still hot.
  - On quiet days the median is 0.0003 (p95 0.0067).
  - So the local check is only a gate ("is lava visible?", "is the view clear?").
- **SAM 3.1 `lava fountain`, image mode** (area is the mask's share of the frame):

  | Set | Frames | With a fountain | Area | Score |
  |---|---|---|---|---|
  | V1 overflow night Oct 16 (8.9×), every 12 min | 40 | 0 | | |
  | V1 overflow night Oct 17, 21:00–03:00 HST (9.4×), every 4 min | 90 | 50 | 0.0021–0.0329 | 0.50–0.77 |
  | K2 overflow night Oct 17, 18:00–03:00 HST, every 16 min | 34 | 0 | | |
  | V1 episode 55, 03:01–04:49 HST, every frame | 55 | 51 | 0.0155–0.7374 | 0.51–0.91 |
  | K2 episode 55, 03:02–04:50 HST, every 4 min | 28 | 9 (from 04:10, steady from 04:22) | 0.0039–0.0228 | 0.50–0.87 |
  | V1 end, 08:47–09:29 HST | 22 | 8 (last at 09:01:05) | 0.009–0.020 | 0.81–0.90 |
  | K2 end, 08:46–09:28 HST | 22 | 9 (last at 09:02:01) | 0.0007–0.004 | 0.66–0.87 |

  - Scores do not separate overflow domes from the fountain; area does. Every overflow sighting on V1 covers ≤ 0.033 of the frame.
  - From 03:03 HST, the episode's fountain covers 0.137 or more until the zoom-out at 03:49:
    - 03:03: 0.23; 03:05: 0.44 (those two boxes take in the flows below);
    - 03:07–03:15: 0.14–0.18;
    - 03:17–03:45: 0.20–0.40;
    - 03:47: 0.74.
  - Isolated misses during the episode: 03:01 (before the fountain), 03:11, 03:29 and 04:11.
  - **V1 thresholds:** `fountain_area` 0.06 (×1.8 above the largest overflow, ×2.3 below the smallest episode sighting) and `ambiguous_area` 0.03.
  - **K2 thresholds:** `fountain_area` 0.01 and `ambiguous_area` 0.005. K2 had no overflow sighting; its episode fountain covers 0.016–0.023 from 04:22.
  - **The end is crisp:** V1 sees nothing on the 14 frames from 09:03:02, and K2 sees nothing on the 13 frames from 09:04:02.
  - **Latency:** a SAM image call takes 1.5 s median (6.9 s with V1's big episode masks, parsing included).
- **Muse Spark on frame pairs 30 min apart** (V1, 1280 px images, `COMPARE_PROMPT` below): $0.0058 and ~6 s per call.
  - 22:19→22:49 HST and 00:41→01:11 HST (overflows): `overflow_or_dome`, `larger_than_before: false`.
  - 02:37→03:07 and 02:55→03:25: `sustained_fountain`, `larger_than_before: true`.
- **The rule, simulated on these results** (looks every 8 min while lava is visible, the next frame looked at right after an episode-size sighting, Muse Spark confirms):
  - **Onset:** the alert is raised between 03:06 and 03:22 HST, depending on where the 8-min cadence falls; all inside [03:03, 03:43].
  - **End:** looks every 6 min while fountaining, plus a re-look on the next frame after a miss. The alert comes between 09:07 and 09:11 HST.
- **Cost estimates:**
  - **Live:** ~180 looks on a day of overflows (V1 every 8 min through the night, heartbeats every 30 min by day, K2 mostly heartbeats), so ~$0.45. An eruption day adds ~120 looks at 6 min, so ~$0.75. That fits the $0.75/day reserve.
  - **Replays (Task 15):** overflows ~260 looks plus a few Muse Spark calls, ~$0.70; episode 55 ~140 looks, ~$0.36.
- **Telegram Bot API** (Context7, `/websites/core_telegram_bots_api`):
  - Requests go to `https://api.telegram.org/bot<token>/METHOD`, so **the token is in every URL**. httpx logs every request URL at INFO, so the CLIs must raise the `httpx` logger to WARNING, and errors must be redacted.
  - Replies are `{"ok": bool, "result": …, "description": …, "error_code": …}`.
  - `sendPhoto` takes multipart/form-data with the photo up to 10 MB and a caption of **0–1024 characters**.
  - `getChat` and `getChatMember` accept `chat_id` as `@channelusername`.
  - A `ChatMemberAdministrator` has `can_post_messages` (channels only).
- **Code facts:**
  - `detection_mask(row, width, height)` (`vigil/tracking.py:117`) reads `box_left/top/right/bottom` and `mask_rle`, so `alert_checks` uses the same column names.
  - `load_for_upload` caps frames at 2048 px.
  - `quality.measure` reduces to ≤ 256-px blocks, so the glow fraction is the same on the 2048-px copy.
  - `check_local(stats, kind=…, captured_at=…, sun_elevation=…, change=…, now=…)`.
  - `db.connect_readonly` does not run the schema, so the mirrored ep55 database lacks the new tables until it is re-pushed; the dashboard must tolerate that.
  - Tests construct `Settings(...)` by keyword (`tests/test_web_app.py:24`), so new fields need defaults.
  - **Never let a test read `.env`:** `Settings.from_env` calls `load_dotenv()`, and the developer's `.env` will hold the real Telegram token. Tests patch `vigil.settings.load_dotenv`.

## File map

| File | What changes |
|---|---|
| `docs/research/alerts_calibration.md` | New: the calibration above (Task 1) and the replay results (Task 15) |
| `vigil/config.py`, `config/sources.yaml` | `Camera.track`; V1 `enabled: true, track: false` (Task 2) |
| `vigil/pipeline.py` | Untracked cameras get local verdicts only and no SAM window; the CLI ledger keeps the reserve (Tasks 2–3) |
| `vigil/settings.py`, `.env.example` | `alerts_path`, `alert_reserve_usd`, `telegram_token`, `telegram_chat` (Task 3) |
| `config/alerts.yaml` | New: the alert cameras and their thresholds (Task 4) |
| `vigil/db.py` | Tables `alert_checks`, `alerts`, `alert_ticks` (Task 4) |
| `vigil/alerts.py` | New: config, sightings, texts, `Alert`, the watcher, posting, the CLI `vigil-alerts` (Tasks 4–7, 9) |
| `vigil/telegram.py` | New: the Bot API client and the CLI `vigil-telegram` (Task 8) |
| `pyproject.toml` | Scripts `vigil-alerts`, `vigil-telegram` |
| `deploy/start.sh`, `Dockerfile`, `vigil/persist.py`, `docs/DEPLOY.md` | Supervise `vigil-alerts`, `ALERT_RESERVE_USD`, save `alerts/` (Task 10) |
| `vigil/episodes.py`, `vigil/replay.py` | `Episode.notices`, `QuietWindow`, `replay_alerts`, `alert_rows`, `--quiet` (Task 13) |
| `vigil/web/views.py`, `vigil/web/app.py`, `vigil/web/static/{index.html,css/app.css,js/alerts.js,js/lib.js,js/main.js}` | `/api/alerts`, the banner, alert overlays in `/media/`, the results table (Task 14) |
| Tests | `tests/test_alerts.py`, `tests/test_telegram.py`, `tests/test_settings.py` (new); `test_pipeline.py`, `test_replay.py`, `test_web_views.py`, `test_web_app.py`, `test_deploy.py`, `test_persist.py`, `tests/js/lib.test.mjs` |

Order: Tasks 1–12 put live alerts on the Space (the episode 56 window opens Nov 2); Tasks 13–16 add the replay, the dashboard banner and the acceptance runs.

---

### Task 1: The calibration note (orchestrator, $0)

**Files:**
- Create: `docs/research/alerts_calibration.md`

- [ ] **Step 1: Write the note** from "Facts this plan relies on" above, with these sections:
  1. **Frames.** What was backfilled, the V1 presets, and HVO's account of the overflows (`episode55.md` §3: south-vent overflows continuous from 05:56 HST Oct 16; north vent intermittent from 18:11, continuous from 23:35; west vent from 22:49, continuous from 02:23; small dome fountains; onset 03:19 by tremor, deflation and the north-vent fountain doubling while under 30 m; notice at 03:43).
  2. **Local signals.** The glow table and why they are only a gate.
  3. **SAM `lava fountain`.** The probe table, the V1 onset sequence minute by minute, and the thresholds with their margins.
  4. **Muse Spark pairs.** The 4-row table with `COMPARE_PROMPT` quoted.
  5. **What the rule does.** The simulated onset (03:06–03:22) and end (09:07–09:11), and the user's decision on the acceptance with the reason.
  6. **Cost.** The probes ($0.7505) and the live estimate.
  7. **Limits:**
     - one night of overflows and one episode, with the thresholds set on the same frames the replays run on; episode 56 is the first out-of-sample test;
     - the thresholds are shares of the frame, so they belong to a framing, which is why Muse Spark confirms every onset;
     - K2 alone would alert about 67 min late at night;
     - a camera that is blind and one turned away can end an episode early (see Task 7).

  Link `data/calibration/alerts/` as the raw results (git-ignored) and the plan. Link it from `docs/research/` siblings only where they mention alerts (none yet).

- [ ] **Step 2: Commit**

```bash
git add docs/research/alerts_calibration.md
git commit -m "Record how SAM, Muse Spark and local signals tell the overflows from episode 55's fountain"
```

---

### Task 2: Cameras ingested for alerts only (`track: false`)

**Files:**
- Modify: `vigil/config.py` (class `Camera`)
- Modify: `vigil/pipeline.py:140-151` (`_assess`), `vigil/pipeline.py:172-175` (`_track_windows`), module docstring
- Modify: `config/sources.yaml` (camera `kilauea-v1`)
- Test: `tests/test_pipeline.py`, `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline.py`:

```python
def untracked_v1(conn, tmp_path, fakes, **config):
    """A pipeline over K2 and V1, where V1 is ingested for the alerts only (track: false)."""
    sources = SOURCES.model_copy(update={"cameras": [
        camera.model_copy(update={"track": False}) if camera.id == "kilauea-v1" else camera
        for camera in SOURCES.cameras]})
    base = dataclasses.replace(context(conn, tmp_path, client="a Meta client", now=START), sources=sources)
    config = {"volcano": "kilauea", "cameras": ("kilauea-k2", "kilauea-v1"), "bulletin_dir": tmp_path / "bulletins",
              "agent_every": None, **config}
    return Pipeline(base, PipelineConfig(**config), track=fakes.track, measure=fakes.measure, write=fakes.write)


def test_a_camera_that_is_not_tracked_gets_local_verdicts_and_no_sam_window(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-k2", 0)
    v1 = frames(conn, store, "kilauea-v1", 0, usable=None)

    # spark="all" would ask Muse Spark about every frame the local checks pass; the client here is a string, so
    # any call for V1 would fail
    report = untracked_v1(conn, tmp_path, fakes, spark="all").step(START + 2 * H)

    assert report.assessed == len(v1)
    rows = conn.execute(f"SELECT decided_by FROM frame_quality WHERE frame_id IN ({','.join('?' * len(v1))})",
                        v1).fetchall()
    assert [row["decided_by"] for row in rows] == ["local"] * len(v1)
    assert [camera for camera, _, _ in fakes.tracked] == ["kilauea-k2"]
```

Add the import `from test_agent_tools import SOURCES` to the existing `from test_agent_tools import …` line.

Append to `tests/test_config.py`:

```python
def test_a_camera_is_tracked_unless_it_says_otherwise_and_v1_is_ingested_for_alerts_only():
    sources = load_sources(ROOT / "config" / "sources.yaml")
    cameras = {camera.id: camera for camera in sources.cameras}

    assert cameras["kilauea-k2"].track and cameras["kilauea-kp"].track
    assert cameras["kilauea-v1"].enabled and not cameras["kilauea-v1"].track
```

If `tests/test_config.py` has no `ROOT`, add `ROOT = Path(__file__).resolve().parent.parent` (and `from pathlib import Path`). Use its existing import of `load_sources`, or add `from vigil.config import load_sources`.

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pipeline.py tests/test_config.py -k "not_tracked or ingested_for_alerts"`
Expected: FAIL, because `Camera` has no field `track` (pydantic `model_copy(update=…)` sets an unknown attribute, and the pipeline then asks Muse Spark on the string client: `AttributeError: 'str' object has no attribute 'ask_json'`).

- [ ] **Step 3: Implement**

In `vigil/config.py`, class `Camera`, after `enabled`:

```python
    track: bool = True  # the pipeline tracks it hourly with SAM video; False: ingested for the alerts only
```

In `vigil/pipeline.py`, docstring step 1 and 2, add "(a camera with `track: false` gets local verdicts only and is never tracked: it is ingested for the alerts)". Then `_assess`:

```python
    def _assess(self, ctx: ToolContext, report: StepReport) -> None:
        gate = QualityGate(ctx.conn, ctx.data_dir, ctx.sources, ctx.client)
        spark = self.config.spark if ctx.client is not None else "never"
        try:
            for camera in self._cameras:
                result = gate.assess_range(camera.id, ctx.now - self.config.lookback, ctx.now,
                                           spark=spark if camera.track else "never")
                report.assessed += len(result.verdicts)
                report.usable += sum(verdict.usable for verdict in result.verdicts)
                report.errors += result.errors
        except BudgetExceeded as exc:
            report.errors.append(f"quality gate stopped: {exc}")
```

and in `_track_windows`:

```python
    def _track_windows(self, ctx: ToolContext, report: StepReport, flush: bool) -> None:
        for camera in self._cameras:
            if not camera.track:
                continue
            for start, end in self._windows(ctx.now, flush):
```

In `config/sources.yaml`, camera `kilauea-v1`: set `enabled: true` and add after it:

```yaml
    track: false        # ingested for the fountaining alerts (config/alerts.yaml), never tracked hourly
```

Update the header comment of `sources.yaml` with one line: "`track: false` keeps a camera out of the pipeline's hourly SAM tracking (it still gets free local verdicts)."

- [ ] **Step 3b: Check the dependants of `enabled` cameras.** `vigil/web/app.py:73` (`live_cameras`) now includes V1, which is wanted: the dashboard shows its frames. `vigil/ingest/worker.py:84` ingests V1 through AshCam. `vigil/agent/tools.py:219` lists it. No code change is needed.

- [ ] **Step 4: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: all pass (597 + 2). If a test counts enabled cameras in `config/sources.yaml`, update its expectation to include V1 and say so in the commit message.

- [ ] **Step 5: Commit**

```bash
git add vigil/config.py vigil/pipeline.py config/sources.yaml tests/test_pipeline.py tests/test_config.py
git commit -m "Ingest V1cam for alerts only: the pipeline gives it local verdicts and never tracks it hourly"
```

---

### Task 3: Settings for alerts and Telegram, and the pipeline's share of the cap

**Files:**
- Modify: `vigil/settings.py`, `vigil/pipeline.py:279` (`main`), `.env.example`
- Create: `tests/test_settings.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings.py`:

```python
from pathlib import Path

import pytest

from vigil.settings import Settings


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """Never read the developer's .env: it holds real keys, and a failing assertion would print them."""
    monkeypatch.setattr("vigil.settings.load_dotenv", lambda: None)
    for name in ("ALERTS_PATH", "ALERT_RESERVE_USD", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DAILY_BUDGET_USD"):
        monkeypatch.delenv(name, raising=False)


def test_alerts_and_telegram_settings_have_defaults_and_no_token():
    settings = Settings.from_env()

    assert settings.alerts_path == Path("config/alerts.yaml")
    assert settings.alert_reserve_usd == 0.75
    assert settings.telegram_token is None and settings.telegram_chat is None
    assert settings.pipeline_budget_usd == 5.0 - 0.75


def test_alerts_and_telegram_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("ALERT_RESERVE_USD", "0.5")
    monkeypatch.setenv("DAILY_BUDGET_USD", "4")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@volcano_vigil")

    settings = Settings.from_env()

    assert (settings.alert_reserve_usd, settings.pipeline_budget_usd) == (0.5, 3.5)
    assert (settings.telegram_token, settings.telegram_chat) == ("123:abc", "@volcano_vigil")


def test_the_pipeline_never_gets_a_negative_budget(monkeypatch):
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.5")

    assert Settings.from_env().pipeline_budget_usd == 0.0
```

Append to `tests/test_pipeline.py`:

```python
def test_cli_leaves_the_alerts_their_reserve_of_the_daily_cap(cli_env, monkeypatch):
    sources = cli_env / "sources.yaml"
    sources.write_text(SOURCES_YAML.replace(
        "cameras: []",
        "cameras:\n  - {id: kilauea-k2, name: K2cam, volcano: kilauea, url: 'https://example.org/k2.jpg',\n"
        "     license: Public Domain, attribution: USGS, enabled: true}"), encoding="utf-8")
    monkeypatch.setattr("vigil.settings.load_dotenv", lambda: None)
    monkeypatch.setenv("DAILY_BUDGET_USD", "5")
    monkeypatch.setenv("ALERT_RESERVE_USD", "0.75")
    caps = []

    class Stop(Exception):
        pass

    def from_env(ledger):
        caps.append(ledger.daily_budget_usd)
        raise Stop

    monkeypatch.setattr("vigil.pipeline.MetaClient.from_env", from_env)

    with pytest.raises(Stop):
        main(["--volcano", "kilauea", "--once"])

    assert caps == [4.25]
```

(`cli_env` and `SOURCES_YAML` already exist in `tests/test_pipeline.py`. Check that `cli_env` sets `SOURCES_PATH` to `cli_env / "sources.yaml"`; if it uses another name, write to that path.)

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings.py tests/test_pipeline.py -k "settings or reserve"`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'alerts_path'`.

- [ ] **Step 3: Implement**

`vigil/settings.py`:

```python
@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    sources_path: Path
    prompts_path: Path
    calibration_path: Path
    user_agent: str
    daily_budget_usd: float
    alerts_path: Path = Path("config/alerts.yaml")
    alert_reserve_usd: float = 0.75   # of the daily cap, kept for the fountaining alerts (vigil.alerts)
    telegram_token: str | None = None  # the alert bot's token: a secret, never printed
    telegram_chat: str | None = None   # the public channel: @name or its numeric id

    @property
    def pipeline_budget_usd(self) -> float:
        """What the pipeline may spend in a UTC day: the cap less the alerts' reserve."""
        return max(0.0, self.daily_budget_usd - self.alert_reserve_usd)

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        data_dir = Path(os.getenv("DATA_DIR", "data"))
        return cls(
            data_dir=data_dir,
            db_path=Path(os.getenv("DB_PATH", str(data_dir / "vigil.sqlite"))),
            sources_path=Path(os.getenv("SOURCES_PATH", "config/sources.yaml")),
            prompts_path=Path(os.getenv("PROMPTS_PATH", "config/prompts.yaml")),
            calibration_path=Path(os.getenv("CALIBRATION_PATH", "config/calibration.yaml")),
            user_agent=os.getenv("HTTP_USER_AGENT", DEFAULT_USER_AGENT),
            daily_budget_usd=float(os.getenv("DAILY_BUDGET_USD", "5.00")),
            alerts_path=Path(os.getenv("ALERTS_PATH", "config/alerts.yaml")),
            alert_reserve_usd=float(os.getenv("ALERT_RESERVE_USD", "0.75")),
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat=os.getenv("TELEGRAM_CHAT_ID") or None,
        )
```

`vigil/pipeline.py` `main`: replace `CostLedger(conn, settings.daily_budget_usd)` with `CostLedger(conn, settings.pipeline_budget_usd)`, and add a comment: `# the alerts keep their reserve of the cap (vigil-alerts)`.

`.env.example`, after `DAILY_BUDGET_USD`:

```
# Of that cap, this much is kept for the fountaining alerts (vigil-alerts); the pipeline stops at the rest.
ALERT_RESERVE_USD=0.75
ALERTS_PATH=config/alerts.yaml

# --- Telegram (vigil-alerts posts each alert to a public channel) ---
# The bot's token from @BotFather: a secret. The channel: @username, or its numeric id.
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add vigil/settings.py vigil/pipeline.py .env.example tests/test_settings.py tests/test_pipeline.py
git commit -m "Keep part of the daily cap for the alerts and read the Telegram bot settings"
```

---

### Task 4: Alert config, SAM sightings and the new tables

**Files:**
- Create: `config/alerts.yaml`, `vigil/alerts.py` (first part), `tests/test_alerts.py`
- Modify: `vigil/db.py` (SCHEMA)
- Test: `tests/test_alerts.py`, `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_alerts.py`:

```python
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from vigil.alerts import AlertConfig, CameraRule, Sighting, best_sighting, load_alert_config, size_of
from vigil.config import ConfigError
from vigil.meta.sam import SamObject

ROOT = Path(__file__).resolve().parent.parent
RULE = CameraRule(fountain_area=0.06, ambiguous_area=0.03)


def obj(width, height, score=0.8, left=10, top=10):
    """A SAM object whose box-sized mask is full."""
    return SamObject("0", None, (left, top, left + width, top + height), score, np.ones((height, width), dtype=bool))


def test_the_committed_alert_config_watches_v1_and_k2_with_the_calibrated_thresholds():
    config = load_alert_config(ROOT / "config" / "alerts.yaml")

    assert config.cameras == {"kilauea-v1": CameraRule(fountain_area=0.06, ambiguous_area=0.03),
                              "kilauea-k2": CameraRule(fountain_area=0.01, ambiguous_area=0.005)}


def test_an_ambiguous_band_above_the_fountain_threshold_is_refused(tmp_path):
    path = tmp_path / "alerts.yaml"
    path.write_text("cameras:\n  kilauea-v1: {fountain_area: 0.03, ambiguous_area: 0.06}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="ambiguous_area"):
        load_alert_config(path)


def test_the_best_sighting_is_the_top_score_moved_to_the_frames_pixels():
    # the frame is 4096x2304 and was sent at 2048x1152, so boxes double on the way back
    objects = [obj(100, 50, score=0.55), obj(200, 100, score=0.9, left=300, top=200), obj(400, 400, score=0.3)]

    sighting = best_sighting(objects, sent=(2048, 1152), frame=(4096, 2304))

    assert sighting.score == pytest.approx(0.9)
    assert sighting.box == (600, 400, 1000, 600)
    assert sighting.mask.shape == (200, 400) and sighting.mask.all()
    assert sighting.area == pytest.approx(200 * 100 / (2048 * 1152))


def test_objects_under_sams_floor_are_no_sighting():
    assert best_sighting([obj(400, 400, score=0.49)], sent=(1920, 1080), frame=(1920, 1080)) is None
    assert best_sighting([], sent=(1920, 1080), frame=(1920, 1080)) is None


@pytest.mark.parametrize("area, size", [(0.0329, "small"), (0.03, "ambiguous"), (0.059, "ambiguous"),
                                        (0.06, "large"), (0.137, "large")])
def test_a_sightings_size_follows_the_cameras_thresholds(area, size):
    sighting = Sighting(0.8, area, (0, 0, 1, 1), np.ones((1, 1), dtype=bool))

    assert size_of(sighting, RULE) == size


def test_no_sighting_is_size_none():
    assert size_of(None, RULE) == "none"
```

Append to `tests/test_db.py`:

```python
def test_the_schema_has_the_alert_tables(conn):
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert {"alert_checks", "alerts", "alert_ticks"} <= tables
    columns = {row[1] for row in conn.execute("PRAGMA table_info(alert_checks)")}
    assert {"box_left", "box_top", "box_right", "box_bottom", "mask_rle", "size", "episode", "spark"} <= columns
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_alerts.py tests/test_db.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigil.alerts'`.

- [ ] **Step 3: Implement**

Create `config/alerts.yaml`:

```yaml
# Fountaining alerts (vigil.alerts): the cameras the watcher looks at and, for each, the share of the frame a SAM
# 'lava fountain' mask must cover to count as an episode-size fountain (fountain_area). Between ambiguous_area and
# fountain_area, Muse Spark compares the frame with the camera's frame from 30 minutes earlier. Every onset is
# confirmed by Muse Spark before it is raised.
# Set on 2026-11-01 from the Oct 16-17 overflow frames and episode 55, before any replay of the alerts ran, and
# never tuned to HVO's times (docs/research/alerts_calibration.md). The shares belong to each camera's framing.
cameras:
  kilauea-v1:            # zoomed on the cone (8.9-9.6x): overflow domes and cascades <= 0.033, ep55's fountain >= 0.137
    fountain_area: 0.06
    ambiguous_area: 0.03
  kilauea-k2:            # 1.7 km away: no fountain on 34 overflow-night frames; ep55's fountain 0.016-0.023 from 04:22
    fountain_area: 0.01
    ambiguous_area: 0.005
```

Create `vigil/alerts.py` with the docstring, imports and constants it ends up needing, plus the first part:

```python
"""Fountaining alerts: watch the alert cameras' new frames and say when lava fountaining starts and when it stops.

At every step (every minute live, every simulated minute in a replay), for each camera in config/alerts.yaml:
1. Local checks, free (vigil.quality): a dark, foggy or stale frame is skipped.
2. SAM 3.1 looks for a 'lava fountain' on a frame when a look is due: every QUIET_EVERY while lava is visible (the
   frame's glow fraction reaches LAVA_GLOW), every HEARTBEAT when it is not, every ACTIVE_EVERY while the volcano is
   fountaining, and on the very next frame after an episode-size sighting or, while fountaining, after a miss.
3. A sighting is episode-size when its mask covers at least the camera's fountain_area of the frame. On V1cam the
   overflows before episode 55 never covered more than 0.033 of the frame, and the episode's fountain 0.137 or more
   (docs/research/alerts_calibration.md). Between ambiguous_area and fountain_area, Muse Spark compares the frame
   with the camera's frame from COMPARE_AGO earlier.
4. Onset, while the volcano is quiet: two consecutive episode-size sightings on one camera, at most PAIR_WITHIN
   apart, and Muse Spark's word that the fountain is sustained and larger than before (asked once, unless it
   already confirmed one of the two). End, while fountaining: every camera that saw this episode's fountain has
   missed it on its last two looks or has not looked for BLIND_AFTER, and at least one has missed it twice.
Each look is a row of alert_checks, and each change an alert (the alerts table) with its texts in English and
Spanish, the frame with its mask, the disclaimer and the link to the official agency. The state lives in the alerts
table, so a restart or a resumed replay keeps it. Nothing in a step looks past `now`. The live loop also posts new
alerts to Telegram (vigil.telegram); a replay never does.

    vigil-alerts --volcano kilauea
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from vigil.config import ConfigError
from vigil.meta.sam import SamObject, fit_mask

MIN_SCORE = 0.5  # SAM's floor: overflow and fountain sightings both scored 0.50-0.91, so the size decides
Size = Literal["none", "small", "ambiguous", "large"]


class CameraRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fountain_area: float = Field(gt=0, le=1)   # share of the frame from which a sighting is episode-size
    ambiguous_area: float = Field(gt=0, le=1)  # from here up to fountain_area, Muse Spark decides

    @model_validator(mode="after")
    def _ordered(self) -> CameraRule:
        if self.ambiguous_area >= self.fountain_area:
            raise ValueError("ambiguous_area must be below fountain_area")
        return self


class AlertConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cameras: dict[str, CameraRule]


def load_alert_config(path: str | Path) -> AlertConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    try:
        return AlertConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc


@dataclass(frozen=True)
class Sighting:
    score: float
    area: float                     # the mask's pixels as a share of the frame
    box: tuple[int, int, int, int]  # left, top, right, bottom: half-open, in the frame's pixels
    mask: np.ndarray                # bool, box-sized, in the frame's pixels


def best_sighting(objects: list[SamObject], sent: tuple[int, int], frame: tuple[int, int]) -> Sighting | None:
    """SAM's highest-scoring object of at least MIN_SCORE, moved from the image sent (width, height) to the frame's
    pixels; None if there is none."""
    kept = [obj for obj in objects if (obj.score or 0.0) >= MIN_SCORE]
    if not kept:
        return None
    obj = max(kept, key=lambda o: o.score or 0.0)
    sx, sy = frame[0] / sent[0], frame[1] / sent[1]
    left, top, right, bottom = obj.box
    box = (round(left * sx), round(top * sy), max(round(right * sx), round(left * sx) + 1),
           max(round(bottom * sy), round(top * sy) + 1))
    mask = fit_mask(obj.mask, box[3] - box[1], box[2] - box[0])
    return Sighting(float(obj.score or 0.0), obj.area_px / (sent[0] * sent[1]), box, mask)


def size_of(sighting: Sighting | None, rule: CameraRule) -> Size:
    if sighting is None:
        return "none"
    if sighting.area >= rule.fountain_area:
        return "large"
    return "ambiguous" if sighting.area >= rule.ambiguous_area else "small"
```

Append to `SCHEMA` in `vigil/db.py`, before the closing `"""`:

```sql
CREATE TABLE IF NOT EXISTS alert_checks (    -- one SAM look at one frame by the fountaining alerts (vigil.alerts)
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    frame_id    INTEGER NOT NULL REFERENCES frames (id),
    camera_id   TEXT    NOT NULL,
    captured_at TEXT    NOT NULL,  -- UTC capture time of the frame
    clock       TEXT    NOT NULL,  -- UTC time of the watcher's step: now live, the simulated time in a replay
    glow        REAL    NOT NULL,  -- the frame's glow fraction (vigil.quality)
    score       REAL,              -- SAM's best 'lava fountain' object; this and the box and mask NULL for none
    area        REAL,              -- its mask's share of the frame
    box_left    INTEGER,           -- half-open box in the frame's own pixels
    box_top     INTEGER,
    box_right   INTEGER,
    box_bottom  INTEGER,
    mask_rle    TEXT,              -- JSON COCO RLE of the box-sized mask
    size        TEXT    NOT NULL,  -- none | small | ambiguous | large
    spark       TEXT,              -- Muse Spark's comparison (JSON) when it was asked
    episode     INTEGER NOT NULL,  -- 1 if the look counts as an episode-size fountain
    UNIQUE (frame_id)
);
CREATE INDEX IF NOT EXISTS idx_alert_checks_camera ON alert_checks (camera_id, captured_at);

CREATE TABLE IF NOT EXISTS alerts (          -- one change of a volcano's fountaining state (vigil.alerts)
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    volcano       TEXT    NOT NULL,
    kind          TEXT    NOT NULL,  -- onset | end
    clock         TEXT    NOT NULL,  -- UTC time the watcher raised it
    created_at    TEXT    NOT NULL,  -- UTC wall clock
    camera_id     TEXT    NOT NULL,  -- the camera whose frame shows the change
    frame_id      INTEGER NOT NULL REFERENCES frames (id),
    captured_at   TEXT    NOT NULL,  -- UTC capture time of that frame
    seen_at       TEXT    NOT NULL,  -- onset: the first episode-size sighting; end: the fountain's last sighting
    body          TEXT    NOT NULL,  -- the whole alert as JSON (vigil.alerts.Alert)
    sent_at       TEXT,              -- UTC, when Telegram took it; NULL if not posted
    send_attempts INTEGER NOT NULL DEFAULT 0,
    send_error    TEXT               -- the last Telegram failure
);
CREATE INDEX IF NOT EXISTS idx_alerts_clock ON alerts (volcano, clock);

CREATE TABLE IF NOT EXISTS alert_ticks (     -- one step of a replay's fountaining alerts (vigil.replay)
    clock  TEXT PRIMARY KEY,  -- UTC simulated time
    report TEXT NOT NULL      -- JSON: the watcher's step report
);
```

- [ ] **Step 4: Run the tests and the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_alerts.py tests/test_db.py`, then `.venv/Scripts/python.exe -m pytest`.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add config/alerts.yaml vigil/alerts.py vigil/db.py tests/test_alerts.py tests/test_db.py
git commit -m "Size SAM's lava-fountain sightings against per-camera thresholds set on the overflow frames"
```

---

### Task 5: The alert record, its texts, its frame and its Telegram caption

**Files:**
- Modify: `vigil/alerts.py`
- Test: `tests/test_alerts.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_alerts.py`; add the imports at the top)

```python
from vigil import db, masks
from vigil.alerts import (CAPTION_MAX, NOTE_EN, NOTE_ES, Alert, alert_texts, caption, draw_alert_frame,
                          duration_text, load_alert, store_alert)
from vigil.config import Volcano

KILAUEA = Volcano(name="Kīlauea", country="United States (Hawaiʻi)",
                  official_agency="USGS Hawaiian Volcano Observatory (HVO)",
                  official_url="https://www.usgs.gov/volcanoes/kilauea", lat=19.405, lon=-155.29, utc_offset_hours=-10)


def test_onset_texts_give_both_sightings_in_local_time_and_utc_in_both_languages():
    texts = alert_texts("onset", KILAUEA, camera="V1cam", captured_at="2026-10-17T13:07:02Z",
                        seen_at="2026-10-17T13:05:02Z", seen_by="V1cam")

    assert texts["headline_en"] == "Lava fountaining seen at the summit of Kīlauea"
    assert texts["headline_es"] == "Fuente de lava visible en la cumbre del Kīlauea"
    assert "at 03:05 and again at 03:07 local time (13:07 UTC, 2026-10-17)" in texts["text_en"]
    assert "a las 03:05 y de nuevo a las 03:07, hora local (13:07 UTC, 2026-10-17)" in texts["text_es"]
    assert "Only USGS Hawaiian Volcano Observatory (HVO) declares" in texts["text_en"]


def test_end_texts_name_the_cameras_the_last_sighting_and_how_long_it_lasted():
    texts = alert_texts("end", KILAUEA, camera="K2cam", captured_at="2026-10-17T19:08:02Z",
                        seen_at="2026-10-17T19:02:01Z", seen_by="K2cam", onset_at="2026-10-17T13:05:02Z",
                        cameras=("V1cam", "K2cam"))

    assert "No lava fountain on V1cam and K2cam since 09:02 local time, when K2cam last showed one" in texts["text_en"]
    assert "Ninguna fuente de lava en V1cam y K2cam desde las 09:02" in texts["text_es"]
    assert "5 h 57 min" in texts["text_en"] and "5 h 57 min" in texts["text_es"]


@pytest.mark.parametrize("minutes, text", [(7, "7 min"), (60, "1 h 00 min"), (357, "5 h 57 min")])
def test_durations_read_in_hours_and_minutes(minutes, text):
    assert duration_text(timedelta(minutes=minutes)) == text


def make_alert(kind="onset", **fields):
    texts = alert_texts(kind, KILAUEA, camera="V1cam", captured_at="2026-10-17T13:07:02Z",
                        seen_at="2026-10-17T13:05:02Z", seen_by="V1cam",
                        onset_at="2026-10-17T13:05:02Z" if kind == "end" else None,
                        cameras=("V1cam", "K2cam") if kind == "end" else ())
    values = {"volcano": "kilauea", "volcano_name": "Kīlauea", "utc_offset_hours": -10, "kind": kind,
              "clock": "2026-10-17T13:08:00Z", "created_at": "2026-11-01T20:00:00Z", "camera_id": "kilauea-v1",
              "camera_name": "V1cam", "frame_id": 1, "captured_at": "2026-10-17T13:07:02Z",
              "seen_at": "2026-10-17T13:05:02Z", "seen_by": "V1cam", "overlay": "alerts/x/frame1.jpg",
              "official_agency": KILAUEA.official_agency, "official_url": KILAUEA.official_url,
              "disclaimer_en": "Automated … does not replace official alerts …",
              "disclaimer_es": "Lectura automática … No reemplaza las alertas …", **texts}
    return Alert(**{**values, **fields})


@pytest.mark.parametrize("kind", ["onset", "end"])
def test_the_caption_has_both_languages_the_notes_and_the_official_link_within_telegrams_limit(kind):
    alert = make_alert(kind)

    text = caption(alert, prefix="REPLAY of episode 55 (2026-10-17): not a live alert. / REPETICIÓN del episodio 55: "
                                 "no es una alerta en vivo.")

    assert len(text) <= CAPTION_MAX
    for part in (alert.headline_en, alert.text_en, NOTE_EN, alert.headline_es, alert.text_es, NOTE_ES,
                 "https://www.usgs.gov/volcanoes/kilauea"):
        assert part in text


def test_an_alert_is_stored_with_its_id_and_read_back(conn):
    stored = store_alert(conn, make_alert())

    assert stored.id is not None
    assert load_alert(conn, stored.id) == stored
    row = conn.execute("SELECT kind, seen_at, sent_at, send_attempts FROM alerts").fetchone()
    assert tuple(row) == ("onset", "2026-10-17T13:05:02Z", None, 0)


def look_row(box, mask):
    """What draw_alert_frame reads from an alert_checks row."""
    left, top, right, bottom = box
    return {"id": 1, "box_left": left, "box_top": top, "box_right": right, "box_bottom": bottom,
            "mask_rle": json.dumps(masks.encode(mask))}


def test_the_alert_frame_is_scaled_to_the_overlay_width_with_the_fountain_tinted(tmp_path):
    (tmp_path / "frames").mkdir()
    Image.new("RGB", (2560, 1440), (20, 20, 20)).save(tmp_path / "frames" / "f.jpg")
    frame = {"id": 7, "path": "frames/f.jpg", "width": 2560, "height": 1440}
    look = look_row((1000, 400, 1400, 900), np.ones((500, 400), dtype=bool))

    overlay = draw_alert_frame(tmp_path, frame, look, tmp_path / "alerts" / "20261017T1308Z_onset")

    assert overlay == "alerts/20261017T1308Z_onset/frame7.jpg"
    with Image.open(tmp_path / overlay) as drawn:
        assert drawn.width == 1280
        inside, outside = drawn.getpixel((600, 320)), drawn.getpixel((100, 100))
    assert inside[0] > outside[0] + 50  # tinted with the fountain's colour


def test_an_end_frame_is_drawn_without_a_mask(tmp_path):
    (tmp_path / "frames").mkdir()
    Image.new("RGB", (640, 360), (20, 20, 20)).save(tmp_path / "frames" / "f.jpg")

    overlay = draw_alert_frame(tmp_path, {"id": 8, "path": "frames/f.jpg", "width": 640, "height": 360},
                               {"id": 2, "mask_rle": None}, tmp_path / "alerts" / "x")

    with Image.open(tmp_path / overlay) as drawn:
        assert drawn.size == (640, 360)
```

(`conn` is the conftest fixture.)

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_alerts.py`
Expected: FAIL with `ImportError: cannot import name 'CAPTION_MAX'`.

- [ ] **Step 3: Implement** (add to `vigil/alerts.py`; new imports: `dataclasses`, `sqlite3`, `from collections.abc import Mapping`, `from datetime import timedelta`, `from typing import Any`, `from PIL import Image`, `from vigil.agent.bulletin import COLORS, OVERLAY_WIDTH`, `from vigil.config import Volcano`, `from vigil.overlay import Layer, draw_layers`, `from vigil.timeutil import parse_utc`, `from vigil.tracking import detection_mask`)

```python
PHRASE = "lava fountain"
CAPTION_MAX = 1024  # Telegram's limit on a photo's caption
Kind = Literal["onset", "end"]

HEADLINES = {
    "onset": ("Lava fountaining seen at the summit of {name}", "Fuente de lava visible en la cumbre del {name}"),
    "end": ("Lava fountaining has stopped at the summit of {name}",
            "Terminaron las fuentes de lava en la cumbre del {name}"),
}
TEXTS = {
    "onset": (
        "{camera} shows a lava fountain far larger than the overflows before it: at {seen} and again at {when} "
        "local time ({utc} UTC, {date}). Only {agency} declares an eruptive episode.",
        "{camera} muestra una fuente de lava mucho mayor que los desbordes previos: a las {seen} y de nuevo a las "
        "{when}, hora local ({utc} UTC, {date}). Solo {agency} declara un episodio eruptivo."),
    "end": (
        "No lava fountain on {cameras} since {seen} local time, when {seen_by} last showed one; confirmed at {when} "
        "({utc} UTC, {date}). It had lasted {duration} since it was first seen at {onset}.",
        "Ninguna fuente de lava en {cameras} desde las {seen}, hora local, cuando {seen_by} mostró una por última "
        "vez; confirmado a las {when} ({utc} UTC, {date}). Duró {duration} desde que se vio por primera vez a las "
        "{onset}."),
}
NOTE_EN = "Automated, experimental reading of public webcams by Volcano Vigil. It does not replace official alerts."
NOTE_ES = ("Lectura automática y experimental de cámaras públicas hecha por Volcano Vigil. No reemplaza las alertas "
           "oficiales.")


class Alert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    volcano: str
    volcano_name: str
    utc_offset_hours: float | None
    kind: Kind
    clock: str           # UTC, when the watcher raised it
    created_at: str      # UTC wall clock
    camera_id: str       # the camera whose frame shows the change
    camera_name: str
    frame_id: int
    captured_at: str     # UTC capture time of that frame
    seen_at: str         # onset: the first episode-size sighting; end: the fountain's last sighting
    seen_by: str         # the camera of that sighting
    headline_en: str
    headline_es: str
    text_en: str
    text_es: str
    overlay: str         # the frame with its mask, relative to the data dir
    official_agency: str
    official_url: str
    disclaimer_en: str
    disclaimer_es: str


def _local(utc: str, offset_hours: float | None) -> str:
    return f"{parse_utc(utc) + timedelta(hours=offset_hours or 0):%H:%M}"


def duration_text(span: timedelta) -> str:
    minutes = round(span / timedelta(minutes=1))
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


def _names(names: tuple[str, ...], lang: str) -> str:
    if len(names) < 2:
        return "".join(names)
    return f"{', '.join(names[:-1])} {'and' if lang == 'en' else 'y'} {names[-1]}"


def alert_texts(kind: Kind, volcano: Volcano, *, camera: str, captured_at: str, seen_at: str, seen_by: str,
                onset_at: str | None = None, cameras: tuple[str, ...] = ()) -> dict[str, str]:
    """The headline and text in English and Spanish, written by the code from stored times only."""
    offset = volcano.utc_offset_hours
    words = {"name": volcano.name, "camera": camera, "seen": _local(seen_at, offset),
             "when": _local(captured_at, offset), "utc": captured_at[11:16], "date": captured_at[:10],
             "agency": volcano.official_agency, "seen_by": seen_by,
             "onset": _local(onset_at, offset) if onset_at else "",
             "duration": duration_text(parse_utc(seen_at) - parse_utc(onset_at)) if onset_at else ""}
    (head_en, head_es), (text_en, text_es) = HEADLINES[kind], TEXTS[kind]
    return {"headline_en": head_en.format(**words), "headline_es": head_es.format(**words),
            "text_en": text_en.format(**words, cameras=_names(cameras, "en")),
            "text_es": text_es.format(**words, cameras=_names(cameras, "es"))}


def caption(alert: Alert, prefix: str = "") -> str:
    """The Telegram caption: both languages, the notes and the official link (at most CAPTION_MAX characters)."""
    lines = [prefix, ""] if prefix else []
    lines += [alert.headline_en, alert.text_en, NOTE_EN, "", alert.headline_es, alert.text_es, NOTE_ES, "",
              f"{alert.official_agency}: {alert.official_url}"]
    return "\n".join(lines)


def store_alert(conn: sqlite3.Connection, alert: Alert) -> Alert:
    """Insert the alert; returns it with its id."""
    with conn:
        alert_id = conn.execute(
            """INSERT INTO alerts (volcano, kind, clock, created_at, camera_id, frame_id, captured_at, seen_at, body)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, '')""",
            (alert.volcano, alert.kind, alert.clock, alert.created_at, alert.camera_id, alert.frame_id,
             alert.captured_at, alert.seen_at)).lastrowid
        stored = alert.model_copy(update={"id": alert_id})
        conn.execute("UPDATE alerts SET body = ? WHERE id = ?", (stored.model_dump_json(), alert_id))
    return stored


def load_alert(conn: sqlite3.Connection, alert_id: int) -> Alert:
    row = conn.execute("SELECT body FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if row is None:
        raise KeyError(f"no alert {alert_id}")
    return Alert.model_validate_json(row["body"])


def draw_alert_frame(data_dir: Path, frame: Mapping[str, Any], look: Mapping[str, Any] | None, folder: Path) -> str:
    """The frame at most OVERLAY_WIDTH wide, with the look's fountain mask tinted when it has one, saved in `folder`
    (inside the data dir); returns its path relative to the data dir."""
    with Image.open(data_dir / frame["path"]) as source:
        image = source.convert("RGB")
    layers = []
    if look is not None and look["mask_rle"] is not None:
        layers.append(Layer(detection_mask(look, frame["width"], frame["height"]), COLORS["fountain"],
                            f"fountain: {PHRASE}"))
    scale = min(1.0, OVERLAY_WIDTH / image.width)
    if scale < 1:
        size = (round(image.width * scale), round(image.height * scale))
        image = image.resize(size, Image.Resampling.LANCZOS)
        layers = [dataclasses.replace(layer, mask=np.asarray(
            Image.fromarray(layer.mask).resize(size, Image.Resampling.NEAREST), dtype=bool)) for layer in layers]
    path = folder / f"frame{frame['id']}.jpg"
    relative = path.relative_to(data_dir).as_posix()  # before writing: a folder outside the data dir leaves no file
    folder.mkdir(parents=True, exist_ok=True)
    draw_layers(image, layers).save(path, quality=85)
    return relative
```

If `draw_layers` with layers adds a legend strip below the frame, the overlay is taller than `1280 × 720`. The test only checks the width and a tinted pixel inside the mask, so that is fine; it matches the bulletins' evidence overlays.

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_alerts.py`
Expected: PASS. If a caption exceeds 1024 characters, shorten the template wording, never the notes or the link, and say so in the commit.

- [ ] **Step 5: Commit**

```bash
git add vigil/alerts.py tests/test_alerts.py
git commit -m "Write each fountaining alert in English and Spanish from stored times, with its frame and caption"
```

---

### Task 6: The watcher's looks (when SAM looks, and what it stores)

**Files:**
- Modify: `vigil/alerts.py`
- Test: `tests/test_alerts.py`

- [ ] **Step 1: Write the failing tests** (append; add the imports)

```python
import httpx

from test_agent_tools import SOURCES, context
from test_meta_client import FakeApi, make_client
from vigil.alerts import AlertWatcher, LAVA_GLOW
from vigil.ingest.store import FrameStore
from vigil.meta.ledger import BudgetExceeded

T0 = datetime(2026, 10, 17, 13, 0, tzinfo=timezone.utc)   # 03:00 HST: night at Kīlauea
DAY = datetime(2026, 10, 17, 22, 0, tzinfo=timezone.utc)  # 12:00 HST
M = timedelta(minutes=1)
CONFIG = AlertConfig(cameras={"kilauea-v1": RULE, "kilauea-k2": RULE})
SIZE = (384, 216)
LARGE, AMBIGUOUS, SMALL = (200, 100), (100, 30), (40, 20)  # 0.24, 0.036 and 0.0096 of a 384x216 frame
SUSTAINED = {"fountain_visible": True, "larger_than_before": True, "looks_like": "sustained_fountain",
             "reason": "much larger"}
OVERFLOW = {"fountain_visible": True, "larger_than_before": False, "looks_like": "overflow_or_dome",
            "reason": "same as before"}


def scene_jpeg(seed, lava=True):
    """A frame with detail, dark enough never to look hot, and a block of lava's colour when `lava`."""
    pixels = np.random.default_rng(seed).integers(0, 120, (SIZE[1], SIZE[0], 3), dtype=np.uint8)
    if lava:
        pixels[80:180, 120:260] = (255, 120, 20)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, format="JPEG")
    return buffer.getvalue()


class Fakes:
    """SAM and Muse Spark for the watcher: SAM answers per frame id, Muse Spark with one answer."""

    def __init__(self):
        self.sam = {}           # frame id -> (width, height) of a full-box sighting; others show nothing
        self.looked = []        # frame ids SAM looked at, in order
        self.tags = []          # the tag of the client each look used
        self.answer = SUSTAINED
        self.asked = []         # minutes between the two frames of each Muse Spark comparison
        self.raises = None      # an exception SAM raises

    def segment(self, client, frame_id, jpeg):
        if self.raises is not None:
            raise self.raises
        self.looked.append(frame_id)
        self.tags.append(client.tag)
        width, height = self.sam.get(frame_id, (0, 0))
        return [obj(width, height)] if width else []

    def compare(self, client, earlier, now, minutes):
        self.asked.append(minutes)
        return self.answer


@pytest.fixture
def fakes():
    return Fakes()


def add(store, camera_id, when, lava=True):
    seed = int(when.timestamp()) // 60 * 10 + {"kilauea-v1": 1, "kilauea-k2": 2}[camera_id]
    return store.add(camera_id, scene_jpeg(seed, lava), captured_at=when, timestamp_source="ashcam", fetched_at=when)


def series(store, camera_id, start, first, last, every=2, lava=True):
    """Frames every `every` minutes from `first` to `last` minutes after `start`: {minute: frame id}."""
    return {minute: add(store, camera_id, start + minute * M, lava) for minute in range(first, last + 1, every)}


def watcher(conn, tmp_path, fakes, config=CONFIG, now=T0):
    client = make_client(FakeApi(lambda request: httpx.Response(500)), conn, budget=5.0)
    return AlertWatcher(context(conn, tmp_path, client=client, now=now), "kilauea", config, tmp_path / "alerts",
                        budget_usd=0.75, segment=fakes.segment, compare=fakes.compare)


def run(w, start, first, last):
    """Step the watcher every minute from `first` to `last` minutes after `start`; the reports."""
    return [w.step(start + minute * M) for minute in range(first, last + 1)]


V1_ONLY = AlertConfig(cameras={"kilauea-v1": RULE})


def looked_minutes(frames, fakes):
    by_id = {frame_id: minute for minute, frame_id in frames.items()}
    return [by_id[frame_id] for frame_id in fakes.looked]


def test_while_lava_is_visible_sam_looks_every_eight_minutes(conn, store, tmp_path, fakes):
    frames = series(store, "kilauea-v1", T0, 0, 30)
    fakes.sam = {frame_id: SMALL for frame_id in frames.values()}

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 30)

    assert looked_minutes(frames, fakes) == [0, 8, 16, 24]
    sizes = [row["size"] for row in conn.execute("SELECT size FROM alert_checks ORDER BY captured_at")]
    assert sizes == ["small"] * 4


def test_a_clear_day_with_no_lava_gets_a_look_every_half_hour(conn, store, tmp_path, fakes):
    frames = series(store, "kilauea-v1", DAY, 0, 62, lava=False)

    run(watcher(conn, tmp_path, fakes, V1_ONLY, now=DAY), DAY, 0, 62)

    assert looked_minutes(frames, fakes) == [0, 30, 60]


def test_a_dark_night_frame_is_never_sent_to_sam(conn, store, tmp_path, fakes):
    series(store, "kilauea-v1", T0, 0, 40, lava=False)  # night, no glow: the local checks reject it

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 40)

    assert fakes.looked == []


def test_an_episode_size_sighting_gets_the_very_next_frame_looked_at(conn, store, tmp_path, fakes):
    frames = series(store, "kilauea-v1", T0, 0, 12)
    fakes.sam = {frames[8]: LARGE}
    fakes.answer = OVERFLOW  # so no alert changes the cadence

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 12)

    assert looked_minutes(frames, fakes)[:3] == [0, 8, 10]


def test_a_step_never_sees_a_frame_captured_after_its_clock(conn, store, tmp_path, fakes):
    frames = series(store, "kilauea-v1", T0, 0, 20)

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 7)

    assert looked_minutes(frames, fakes) == [0]
    assert conn.execute("SELECT MAX(captured_at) FROM alert_checks").fetchone()[0] <= "2026-10-17T13:07:00Z"


def test_a_first_step_does_not_look_at_frames_older_than_ten_minutes(conn, store, tmp_path, fakes):
    frames = series(store, "kilauea-v1", T0, -40, 0)

    watcher(conn, tmp_path, fakes, V1_ONLY).step(T0)

    assert looked_minutes(frames, fakes) == [-8, 0]  # frames from 10 minutes back only, then the 8-minute cadence


def test_a_look_is_stored_with_its_box_mask_and_size_and_reported(conn, store, tmp_path, fakes):
    frame_id = add(store, "kilauea-v1", T0)
    fakes.sam = {frame_id: SMALL}

    report = watcher(conn, tmp_path, fakes, V1_ONLY).step(T0)

    row = conn.execute("SELECT * FROM alert_checks").fetchone()
    assert (row["frame_id"], row["camera_id"], row["clock"], row["size"], row["episode"]) == (
        frame_id, "kilauea-v1", "2026-10-17T13:00:00Z", "small", 0)
    assert (row["box_left"], row["box_top"], row["box_right"], row["box_bottom"]) == (10, 10, 50, 30)
    assert row["glow"] >= LAVA_GLOW and row["score"] == pytest.approx(0.8)
    assert report.looks == [{"camera_id": "kilauea-v1", "frame_id": frame_id, "captured_at": "2026-10-17T13:00:00Z",
                             "size": "small", "episode": False}]


def test_the_alerts_spend_under_a_tag_of_the_simulated_utc_day(conn, store, tmp_path, fakes):
    add(store, "kilauea-v1", T0)

    watcher(conn, tmp_path, fakes, V1_ONLY).step(T0)

    assert fakes.tags == ["alerts:2026-10-17"]


def test_a_spent_budget_stops_the_step_and_says_so(conn, store, tmp_path, fakes):
    add(store, "kilauea-v1", T0)
    fakes.raises = BudgetExceeded("budget $0.75 of alerts:2026-10-17 would be exceeded")

    report = watcher(conn, tmp_path, fakes, V1_ONLY).step(T0)

    assert report.errors == ["alerts stopped: budget $0.75 of alerts:2026-10-17 would be exceeded"]


def test_without_a_meta_client_nothing_is_looked_at(conn, store, tmp_path, fakes):
    add(store, "kilauea-v1", T0)
    w = AlertWatcher(context(conn, tmp_path, now=T0), "kilauea", V1_ONLY, tmp_path / "alerts", budget_usd=0.75,
                     segment=fakes.segment, compare=fakes.compare)

    report = w.step(T0)

    assert fakes.looked == [] and report.errors == ["no Meta client: SAM cannot look for a fountain"]
```

The `store` fixture is `FrameStore(conn, tmp_path)` in `tests/test_agent_tools.py`. Import it as the pipeline tests do: `from test_agent_tools import store  # a fixture`.

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_alerts.py -k "look or tag or budget or client or clock or older"`
Expected: FAIL with `ImportError: cannot import name 'AlertWatcher'`.

- [ ] **Step 3: Implement** (add to `vigil/alerts.py`; new imports: `json`, `logging`, `from collections.abc import Callable`, `from dataclasses import field`, `from datetime import datetime`, `import openai`, `from vigil import masks`, `from vigil.agent.tools import ToolContext`, `from vigil.config import Camera`, `from vigil.imaging import load_for_upload`, `from vigil.meta.client import MetaClient`, `from vigil.meta.ledger import BudgetExceeded`, `from vigil.quality import ImageStats, check_local, measure`, `from vigil.sun import solar_elevation`, `from vigil.timeutil import to_iso, utcnow`)

```python
log = logging.getLogger(__name__)

QUIET_EVERY = timedelta(minutes=8)    # a look while quiet and lava is visible
HEARTBEAT = timedelta(minutes=30)     # a look while quiet and no lava is visible, e.g. on a clear day
ACTIVE_EVERY = timedelta(minutes=6)   # a look while fountaining
SLACK = timedelta(minutes=1)          # frames come every ~2 min, seconds early or late
LOOKBACK = timedelta(minutes=10)      # a step looks at frames this recent, so a restart never looks at history
LAVA_GLOW = 0.003                     # glow fraction from which lava is visible; quiet days on V1: median 0.0003
State = Literal["quiet", "fountaining"]
Segment = Callable[[MetaClient, int, bytes], list[SamObject]]
Compare = Callable[[MetaClient, bytes, bytes, int], dict[str, Any]]


def sam_segment(client: MetaClient, frame_id: int, jpeg: bytes) -> list[SamObject]:
    return client.segment_image(jpeg, PHRASE, purpose="segment")


@dataclass
class AlertReport:
    clock: datetime
    looks: list[dict[str, Any]] = field(default_factory=list)   # camera_id, frame_id, captured_at, size, episode
    alerts: list[dict[str, Any]] = field(default_factory=list)  # id, kind, camera_id, captured_at
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"clock": to_iso(self.clock), "looks": self.looks, "alerts": self.alerts, "errors": self.errors}

    def summary(self) -> str:
        parts = [f"{to_iso(self.clock)}: {len(self.looks)} looks"]
        parts += [f"{look['camera_id']} {look['captured_at'][11:19]} {look['size']}" for look in self.looks]
        parts += [f"ALERT {a['kind']} #{a['id']} ({a['camera_id']} {a['captured_at'][11:19]})" for a in self.alerts]
        return "; ".join(parts) + "".join(f"\n  failed: {error}" for error in self.errors)


class AlertWatcher:
    """The fountaining alerts of one volcano's alert cameras. Each step sets its own clock; `base.now` is unused."""

    def __init__(self, base: ToolContext, volcano: str, config: AlertConfig, out_dir: Path, *, budget_usd: float,
                 segment: Segment = sam_segment, compare: Compare | None = None,
                 wall_clock: Callable[[], datetime] = utcnow):
        self.base, self.volcano, self.config, self.out_dir = base, volcano, config, out_dir
        self.budget_usd = budget_usd  # per UTC day of the clock, under the tag alerts:<date>
        self._segment, self._compare, self._wall_clock = segment, compare, wall_clock
        self._seen: dict[str, str] = {}  # camera id -> capture time of the newest frame considered in this run

    @property
    def cameras(self) -> tuple[str, ...]:
        return tuple(self.config.cameras)

    def step(self, now: datetime) -> AlertReport:
        report = AlertReport(now)
        if self.base.client is None:
            report.errors.append("no Meta client: SAM cannot look for a fountain")
            return report
        ctx = dataclasses.replace(self.base, now=now)
        client = self.base.client.tagged(f"alerts:{now:%Y-%m-%d}", self.budget_usd)
        try:
            for camera_id, rule in self.config.cameras.items():
                self._watch(ctx, client, ctx.camera(camera_id), rule, report)
        except BudgetExceeded as exc:
            report.errors.append(f"alerts stopped: {exc}")
        return report

    def state(self, now: datetime) -> tuple[State, sqlite3.Row | None]:
        """The volcano's state at `now`, and the onset alert that started it (None while quiet)."""
        row = self.base.conn.execute(
            "SELECT * FROM alerts WHERE volcano = ? AND clock <= ? ORDER BY clock DESC, id DESC LIMIT 1",
            (self.volcano, to_iso(now))).fetchone()
        return ("fountaining", row) if row is not None and row["kind"] == "onset" else ("quiet", None)

    def _watch(self, ctx: ToolContext, client: MetaClient, camera: Camera, rule: CameraRule,
               report: AlertReport) -> None:
        since = max(to_iso(ctx.now - LOOKBACK), self._seen.get(camera.id, ""))
        frames = ctx.conn.execute(
            "SELECT * FROM frames WHERE camera_id = ? AND captured_at > ? AND captured_at <= ? ORDER BY captured_at",
            (camera.id, since, to_iso(ctx.now))).fetchall()
        for frame in frames:
            self._seen[camera.id] = frame["captured_at"]
            try:
                self._consider(ctx, client, camera, rule, frame, report)
            except (openai.APIError, ValueError, OSError) as exc:  # SAM failed, an unreadable image, a bad answer
                report.errors.append(f"{camera.id} frame {frame['id']}: {type(exc).__name__}: {exc}"[:300])

    def _looks(self, ctx: ToolContext, camera_id: str, n: int) -> list[sqlite3.Row]:
        """The camera's last n looks by the clock, newest first."""
        return ctx.conn.execute(
            "SELECT * FROM alert_checks WHERE camera_id = ? AND captured_at <= ? AND clock <= ? "
            "ORDER BY captured_at DESC LIMIT ?", (camera_id, to_iso(ctx.now), to_iso(ctx.now), n)).fetchall()

    def _follow_up(self, ctx: ToolContext, last: sqlite3.Row, state: State, onset: sqlite3.Row | None) -> bool:
        """True if the camera's next frame needs a look at once: after an episode-size sighting while quiet (Task 7
        adds: after a miss on a camera that saw this episode's fountain)."""
        return state == "quiet" and bool(last["episode"])

    def _consider(self, ctx: ToolContext, client: MetaClient, camera: Camera, rule: CameraRule,
                  frame: sqlite3.Row, report: AlertReport) -> None:
        state, onset = self.state(ctx.now)
        captured = parse_utc(frame["captured_at"])
        last = self._looks(ctx, camera.id, 1)
        if last and frame["captured_at"] <= last[0]["captured_at"]:
            return
        since = captured - parse_utc(last[0]["captured_at"]) if last else None
        follow_up = bool(last) and self._follow_up(ctx, last[0], state, onset)
        every = ACTIVE_EVERY if state == "fountaining" else QUIET_EVERY
        if not follow_up and since is not None and since < every - SLACK:
            return
        image, jpeg = load_for_upload(ctx.data_dir / frame["path"])
        stats = measure(image)
        volcano = ctx.sources.volcanoes[camera.volcano]
        sun = (solar_elevation(captured, volcano.lat, volcano.lon)
               if volcano.lat is not None and volcano.lon is not None else None)
        local = check_local(stats, kind=camera.kind, captured_at=captured, sun_elevation=sun, change=None,
                            now=ctx.now)
        if local.decision == "reject":
            return
        lava = stats.glow_fraction >= LAVA_GLOW
        heartbeat = since is None or since >= HEARTBEAT - SLACK
        if state == "quiet" and not (follow_up or lava or heartbeat):
            return
        self._look(ctx, client, camera, rule, frame, image, jpeg, stats, state, onset, report)

    def _look(self, ctx: ToolContext, client: MetaClient, camera: Camera, rule: CameraRule, frame: sqlite3.Row,
              image: Image.Image, jpeg: bytes, stats: ImageStats, state: State, onset: sqlite3.Row | None,
              report: AlertReport) -> None:
        sighting = best_sighting(self._segment(client, frame["id"], jpeg), image.size,
                                 (frame["width"], frame["height"]))
        size = size_of(sighting, rule)
        answer, episode = None, size == "large"
        look_id = self._store_look(ctx, frame, stats, sighting, size, answer, episode)
        report.looks.append({"camera_id": camera.id, "frame_id": frame["id"], "captured_at": frame["captured_at"],
                             "size": size, "episode": episode})

    def _store_look(self, ctx: ToolContext, frame: sqlite3.Row, stats: ImageStats, sighting: Sighting | None,
                    size: Size, answer: dict[str, Any] | None, episode: bool) -> int:
        box = sighting.box if sighting is not None else (None, None, None, None)
        with ctx.conn:
            return ctx.conn.execute(
                """INSERT INTO alert_checks (frame_id, camera_id, captured_at, clock, glow, score, area, box_left,
                       box_top, box_right, box_bottom, mask_rle, size, spark, episode)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (frame["id"], frame["camera_id"], frame["captured_at"], to_iso(ctx.now), stats.glow_fraction,
                 None if sighting is None else sighting.score, None if sighting is None else sighting.area, *box,
                 None if sighting is None else json.dumps(masks.encode(sighting.mask)), size,
                 None if answer is None else json.dumps(answer, ensure_ascii=False), int(episode))).lastrowid
```

`look_id` and `answer` are unused until Task 7. Keep them: Task 7 extends `_look`.

- [ ] **Step 4: Run the tests and the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_alerts.py`, then `.venv/Scripts/python.exe -m pytest`.
Expected: PASS. If the lava-block test frames do not pass `check_local` at night (glow under `night_glow`, edges under `fog_edges`), print `measure(Image.open(io.BytesIO(scene_jpeg(1))))` and fix the test image, never the thresholds.

- [ ] **Step 5: Commit**

```bash
git add vigil/alerts.py tests/test_alerts.py
git commit -m "Look for a lava fountain with SAM on each alert camera's frames when a look is due"
```

---

### Task 7: Onset and end

**Files:**
- Modify: `vigil/alerts.py`
- Test: `tests/test_alerts.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
def episode(conn, store, tmp_path, fakes, *, large_from, none_from=None, k2=None, config=V1_ONLY, last=None):
    """V1 frames every 2 min from -40 to `last` minutes; SAM sees an episode-size fountain from `large_from` and
    nothing from `none_from`; K2 sightings per minute from `k2` ({minute: size or None}). The frames by camera."""
    last = last if last is not None else (none_from + 10 if none_from is not None else large_from + 10)
    v1 = series(store, "kilauea-v1", T0, -40, last)
    for minute, frame_id in v1.items():
        if minute >= large_from and (none_from is None or minute < none_from):
            fakes.sam[frame_id] = LARGE
        elif minute < large_from:
            fakes.sam[frame_id] = SMALL
    frames = {"kilauea-v1": v1}
    if k2 is not None:
        frames["kilauea-k2"] = series(store, "kilauea-k2", T0, -40, last)
        for minute, size in k2.items():
            if size is not None:
                fakes.sam[frames["kilauea-k2"][minute]] = size
    w = watcher(conn, tmp_path, fakes, config)
    run(w, T0, 0, last)
    return frames


def alerts_of(conn):
    return conn.execute("SELECT kind, camera_id, captured_at, seen_at, clock FROM alerts ORDER BY clock").fetchall()


def test_two_consecutive_episode_size_sightings_confirmed_by_muse_spark_raise_the_onset(conn, store, tmp_path, fakes):
    frames = episode(conn, store, tmp_path, fakes, large_from=6)

    # looks at 0 (small), 8 (large), the next frame 10 (large): Muse Spark compares 10 with the frame 30 min before
    assert [tuple(row) for row in alerts_of(conn)] == [
        ("onset", "kilauea-v1", "2026-10-17T13:10:00Z", "2026-10-17T13:08:00Z", "2026-10-17T13:10:00Z")]
    assert fakes.asked == [30]
    alert = load_alert(conn, 1)
    assert alert.seen_by == "kilauea-v1" and (tmp_path / alert.overlay).is_file()
    assert alert.disclaimer_en.startswith("Automated, experimental reading") and "usgs.gov" in alert.disclaimer_en


def test_overflow_size_sightings_all_night_raise_nothing_and_never_ask_muse_spark(conn, store, tmp_path, fakes):
    frames = series(store, "kilauea-v1", T0, -40, 120)
    fakes.sam = {frame_id: SMALL for frame_id in frames.values()}

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 120)

    assert alerts_of(conn) == [] and fakes.asked == []


def test_muse_spark_saying_overflow_holds_the_onset_back(conn, store, tmp_path, fakes):
    fakes.answer = OVERFLOW

    episode(conn, store, tmp_path, fakes, large_from=6)

    assert alerts_of(conn) == []
    assert conn.execute("SELECT episode FROM alert_checks WHERE spark IS NOT NULL").fetchone()["episode"] == 0


def test_an_ambiguous_size_is_settled_by_muse_spark_and_counts_toward_the_onset(conn, store, tmp_path, fakes):
    v1 = series(store, "kilauea-v1", T0, -40, 12)
    fakes.sam = {v1[0]: SMALL, v1[8]: AMBIGUOUS, v1[10]: LARGE}

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 12)

    assert fakes.asked == [30]  # once for the ambiguous look; it already confirmed the pair
    assert [row["kind"] for row in alerts_of(conn)] == ["onset"]


def test_one_episode_size_sighting_alone_raises_nothing(conn, store, tmp_path, fakes):
    v1 = series(store, "kilauea-v1", T0, -40, 20)
    fakes.sam = {v1[8]: LARGE}  # the next frame shows nothing

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 20)

    assert alerts_of(conn) == [] and fakes.asked == []


def test_two_misses_in_a_row_on_the_camera_that_saw_it_end_the_episode(conn, store, tmp_path, fakes):
    episode(conn, store, tmp_path, fakes, large_from=6, none_from=34, last=44)

    # onset at 10; looks every 6 min: 16, 22, 28 (sightings), 34 (miss), then the next frame 36 (miss)
    rows = [tuple(row) for row in alerts_of(conn)]
    assert rows[1] == ("end", "kilauea-v1", "2026-10-17T13:36:00Z", "2026-10-17T13:28:00Z", "2026-10-17T13:36:00Z")
    end = load_alert(conn, 2)
    # the test volcano has no UTC offset, so "local time" is UTC here
    assert "since 13:28 local time" in end.text_en and "It had lasted 20 min" in end.text_en


def test_a_single_miss_during_the_episode_does_not_end_it(conn, store, tmp_path, fakes):
    v1 = series(store, "kilauea-v1", T0, -40, 40)
    fakes.sam = {frame_id: (LARGE if minute >= 6 else SMALL) for minute, frame_id in v1.items()}
    fakes.sam[v1[22]] = (0, 0)

    run(watcher(conn, tmp_path, fakes, V1_ONLY), T0, 0, 40)

    assert [row["kind"] for row in alerts_of(conn)] == ["onset"]
    assert looked_minutes(v1, fakes)[4:7] == [16, 22, 24]  # the miss gets the next frame looked at at once


def test_a_camera_that_still_sees_the_fountain_holds_the_end_back(conn, store, tmp_path, fakes):
    k2 = {minute: LARGE for minute in range(0, 61, 2)}  # K2 keeps seeing it all along

    episode(conn, store, tmp_path, fakes, large_from=6, none_from=34, k2=k2, config=CONFIG, last=60)

    assert [row["kind"] for row in alerts_of(conn)] == ["onset"]


def test_a_camera_that_never_saw_the_fountain_cannot_end_it(conn, store, tmp_path, fakes):
    k2 = {minute: None for minute in range(-40, 41, 2)}  # K2 sees nothing all along (night saturation)

    episode(conn, store, tmp_path, fakes, large_from=6, k2=k2, config=CONFIG, last=40)

    assert [row["kind"] for row in alerts_of(conn)] == ["onset"]


def test_a_camera_that_has_gone_blind_does_not_hold_the_end_back(conn, store, tmp_path, fakes):
    # K2 sees the fountain until minute 20, then its frames stop (fog rejects them, or the camera is down); V1 sees
    # it from 6 to 48 and nothing from 50
    v1 = series(store, "kilauea-v1", T0, -40, 70)
    k2 = series(store, "kilauea-k2", T0, -40, 20)
    fakes.sam = {**{frame_id: (LARGE if m >= 6 else SMALL) for m, frame_id in v1.items() if m < 50},
                 **{frame_id: LARGE for m, frame_id in k2.items() if m >= 0}}

    run(watcher(conn, tmp_path, fakes, CONFIG), T0, 0, 70)

    kinds = [row["kind"] for row in alerts_of(conn)]
    assert kinds == ["onset", "end"]
    end = conn.execute("SELECT * FROM alerts WHERE kind = 'end'").fetchone()
    assert end["camera_id"] == "kilauea-v1" and end["seen_at"] >= "2026-10-17T13:40:00Z"


def test_the_alerts_state_survives_a_new_watcher(conn, store, tmp_path, fakes):
    episode(conn, store, tmp_path, fakes, large_from=6, last=12)

    fresh = watcher(conn, tmp_path, fakes, V1_ONLY)

    assert fresh.state(T0 + 12 * M)[0] == "fountaining"
    assert fresh.state(T0 + 9 * M)[0] == "quiet"  # bounded by the clock: the onset was raised at 13:10
```

`Fakes.segment` returns `[]` for `(0, 0)`, because `width` is 0.

In `test_a_camera_that_still_sees_the_fountain_holds_the_end_back`, K2 sees the fountain from minute 0. So K2 raises the onset (looks at 0 and 2), and V1's two misses at 34 and 36 cannot end it while K2's last looks are sightings. In `test_a_camera_that_has_gone_blind_does_not_hold_the_end_back`, the onset is K2's too. V1 misses at 50+ and K2's last look (about minute 20) is older than `BLIND_AFTER`, so V1 ends the episode.

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_alerts.py -k "onset or end or episode or spark or miss or blind or overflow or survives"`
Expected: FAIL: no alerts are raised yet (`assert [] == [...]`).

- [ ] **Step 3: Implement** (add to `vigil/alerts.py`; new imports: `from vigil.agent.bulletin import DISCLAIMER_EN, DISCLAIMER_ES`)

```python
PAIR_WITHIN = timedelta(minutes=10)   # two sightings this close are consecutive
COMPARE_AGO = timedelta(minutes=30)   # Muse Spark compares a frame with the camera's frame this much earlier
COMPARE_SPAN = timedelta(hours=2)     # ... found within this span; after a gap, with the oldest frame in it
BLIND_AFTER = timedelta(minutes=20)   # a camera that has not looked for this long cannot hold the end back

COMPARE_PROMPT = (
    "These two frames come from the same USGS webcam at the summit of Kilauea, {minutes} minutes apart: the first "
    "is the earlier one, the second is now. Between eruptive episodes, lava overflows the vents and can form low "
    "dome fountains and lava cascades a few metres high. An episode begins when a lava fountain at a vent becomes "
    "sustained and grows much taller and wider than those overflows. Report only what you can see. Is there a lava "
    "fountain in the second frame, and is it clearly taller and wider than anything in the first frame?"
)
COMPARE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fountain_visible": {"type": "boolean"},
        "larger_than_before": {"type": "boolean"},
        "looks_like": {"type": "string",
                       "enum": ["no_fountain", "overflow_or_dome", "sustained_fountain", "unclear"]},
        "reason": {"type": "string"},
    },
    "additionalProperties": False,
}
COMPARE_SCHEMA["required"] = list(COMPARE_SCHEMA["properties"])


def spark_compare(client: MetaClient, earlier: bytes, now: bytes, minutes: int) -> dict[str, Any]:
    """Muse Spark's comparison of two frames of one camera (validated on 4 pairs, docs/research/alerts_calibration.md)."""
    return client.ask_json(prompt=COMPARE_PROMPT.format(minutes=minutes), images=[earlier, now],
                           schema_name="fountain_check", schema=COMPARE_SCHEMA, purpose="compare")


def sustained(answer: dict[str, Any]) -> bool:
    return answer.get("looks_like") == "sustained_fountain" and bool(answer.get("larger_than_before"))


def short_name(camera: Camera) -> str:
    """'V1cam' for 'V1cam (Halemaʻumaʻu vents, PTZ)'."""
    return camera.name.split(" (")[0]
```

In `AlertWatcher.__init__`, change the default to `compare: Compare = spark_compare`. Replace `_follow_up` and extend `_look`, and add the rest:

```python
    def _follow_up(self, ctx: ToolContext, last: sqlite3.Row, state: State, onset: sqlite3.Row | None) -> bool:
        """True if the camera's next frame needs a look at once: after an episode-size sighting while quiet, or
        after a miss on a camera that saw this episode's fountain."""
        if state == "quiet":
            return bool(last["episode"])
        return last["size"] == "none" and self._saw(ctx, last["camera_id"], onset)

    def _saw(self, ctx: ToolContext, camera_id: str, onset: sqlite3.Row | None) -> bool:
        return onset is not None and ctx.conn.execute(
            "SELECT 1 FROM alert_checks WHERE camera_id = ? AND size != 'none' AND captured_at >= ? "
            "AND captured_at <= ? AND clock <= ? LIMIT 1",
            (camera_id, onset["seen_at"], to_iso(ctx.now), to_iso(ctx.now))).fetchone() is not None

    def _look(self, ctx, client, camera, rule, frame, image, jpeg, stats, state, onset, report) -> None:
        sighting = best_sighting(self._segment(client, frame["id"], jpeg), image.size,
                                 (frame["width"], frame["height"]))
        size = size_of(sighting, rule)
        answer, episode = None, size == "large"
        if state == "quiet" and size == "ambiguous":
            answer = self._ask(ctx, client, camera, frame, report)
            episode = answer is not None and sustained(answer)
        look_id = self._store_look(ctx, frame, stats, sighting, size, answer, episode)
        report.looks.append({"camera_id": camera.id, "frame_id": frame["id"], "captured_at": frame["captured_at"],
                             "size": size, "episode": episode})
        if state == "quiet" and episode:
            self._onset(ctx, client, camera, frame, look_id, answer, report)
        elif state == "fountaining" and size == "none":
            self._end(ctx, camera, frame, onset, report)

    def _ask(self, ctx: ToolContext, client: MetaClient, camera: Camera, frame: sqlite3.Row,
             report: AlertReport) -> dict[str, Any] | None:
        """Muse Spark's comparison of the frame with the camera's newest frame at least COMPARE_AGO older (or, after a
        gap, its oldest frame of the last COMPARE_SPAN); None if there is none or the call failed."""
        captured = parse_utc(frame["captured_at"])
        earlier = ctx.conn.execute(
            "SELECT * FROM frames WHERE camera_id = ? AND captured_at BETWEEN ? AND ? ORDER BY captured_at DESC LIMIT 1",
            (camera.id, to_iso(captured - COMPARE_SPAN), to_iso(captured - COMPARE_AGO))).fetchone()
        if earlier is None:
            earlier = ctx.conn.execute(
                "SELECT * FROM frames WHERE camera_id = ? AND captured_at >= ? AND captured_at < ? "
                "ORDER BY captured_at LIMIT 1",
                (camera.id, to_iso(captured - COMPARE_SPAN), frame["captured_at"])).fetchone()
        if earlier is None:
            report.errors.append(f"{camera.id} frame {frame['id']}: no earlier frame for Muse Spark to compare with")
            return None
        minutes = round((captured - parse_utc(earlier["captured_at"])) / timedelta(minutes=1))
        images = [load_for_upload(ctx.data_dir / row["path"], max_side=1280)[1] for row in (earlier, frame)]
        try:
            return self._compare(client, images[0], images[1], minutes)
        except (openai.APIError, ValueError, KeyError) as exc:
            report.errors.append(f"{camera.id} frame {frame['id']}: Muse Spark failed: {type(exc).__name__}: {exc}"[:300])
            return None

    def _onset(self, ctx: ToolContext, client: MetaClient, camera: Camera, frame: sqlite3.Row, look_id: int,
               answer: dict[str, Any] | None, report: AlertReport) -> None:
        """Raise the onset if this episode-size look and the camera's previous one are consecutive, once Muse Spark
        has confirmed one of them (it is asked now if it has not)."""
        looks = self._looks(ctx, camera.id, 2)  # this look, then the one before it
        if len(looks) < 2 or not looks[1]["episode"]:
            return
        if parse_utc(looks[0]["captured_at"]) - parse_utc(looks[1]["captured_at"]) > PAIR_WITHIN:
            return
        if answer is None and looks[1]["spark"] is None:
            answer = self._ask(ctx, client, camera, frame, report)
            if answer is None:
                return  # asked again with the next frame, which is a follow-up
            confirmed = sustained(answer)
            with ctx.conn:
                ctx.conn.execute("UPDATE alert_checks SET spark = ?, episode = ? WHERE id = ?",
                                 (json.dumps(answer, ensure_ascii=False), int(confirmed), look_id))
            if not confirmed:
                return
        self._raise(ctx, "onset", camera, frame, looks[0], seen_at=looks[1]["captured_at"],
                    seen_by=short_name(camera), report=report)

    def _end(self, ctx: ToolContext, camera: Camera, frame: sqlite3.Row, onset: sqlite3.Row,
             report: AlertReport) -> None:
        """Raise the end if every camera that saw this episode's fountain missed it on its last two looks or has not
        looked for BLIND_AFTER, and at least one missed it twice."""
        now = to_iso(ctx.now)
        seen = [row[0] for row in ctx.conn.execute(
            "SELECT DISTINCT camera_id FROM alert_checks WHERE size != 'none' AND captured_at >= ? "
            "AND captured_at <= ? AND clock <= ? ORDER BY camera_id", (onset["seen_at"], now, now))]
        if camera.id not in seen:
            return
        sightings, missed_twice = [], False
        for camera_id in seen:
            looks = self._looks(ctx, camera_id, 2)
            sightings.append(ctx.conn.execute(
                "SELECT camera_id, captured_at FROM alert_checks WHERE camera_id = ? AND size != 'none' "
                "AND captured_at <= ? AND clock <= ? ORDER BY captured_at DESC LIMIT 1",
                (camera_id, now, now)).fetchone())
            if len(looks) == 2 and all(look["size"] == "none" for look in looks):
                missed_twice = True
            elif looks and ctx.now - parse_utc(looks[0]["captured_at"]) <= BLIND_AFTER:
                return
        if not missed_twice:
            return
        last = max(sightings, key=lambda row: row["captured_at"])
        look = self._looks(ctx, camera.id, 1)[0]
        self._raise(ctx, "end", camera, frame, look, seen_at=last["captured_at"],
                    seen_by=short_name(ctx.camera(last["camera_id"])), report=report, onset=onset,
                    cameras=tuple(seen))

    def _raise(self, ctx: ToolContext, kind: Kind, camera: Camera, frame: sqlite3.Row, look: sqlite3.Row, *,
               seen_at: str, seen_by: str, report: AlertReport, onset: sqlite3.Row | None = None,
               cameras: tuple[str, ...] = ()) -> None:
        volcano = ctx.sources.volcanoes[self.volcano]
        overlay = draw_alert_frame(ctx.data_dir, frame, look, self.out_dir / f"{ctx.now:%Y%m%dT%H%MZ}_{kind}")
        texts = alert_texts(kind, volcano, camera=short_name(camera), captured_at=frame["captured_at"],
                            seen_at=seen_at, seen_by=seen_by,
                            onset_at=None if onset is None else onset["seen_at"],
                            cameras=tuple(short_name(ctx.camera(camera_id)) for camera_id in cameras))
        names = {"name": volcano.name, "agency": volcano.official_agency, "url": volcano.official_url}
        alert = store_alert(ctx.conn, Alert(
            volcano=self.volcano, volcano_name=volcano.name, utc_offset_hours=volcano.utc_offset_hours, kind=kind,
            clock=to_iso(ctx.now), created_at=to_iso(self._wall_clock()), camera_id=camera.id,
            camera_name=short_name(camera), frame_id=frame["id"], captured_at=frame["captured_at"],
            seen_at=seen_at, seen_by=seen_by, overlay=overlay, official_agency=volcano.official_agency,
            official_url=volcano.official_url, disclaimer_en=DISCLAIMER_EN.format(**names),
            disclaimer_es=DISCLAIMER_ES.format(**names), **texts))
        report.alerts.append({"id": alert.id, "kind": kind, "camera_id": camera.id,
                              "captured_at": frame["captured_at"]})
        log.info("alert %s: %s on %s at %s", alert.id, kind, camera.id, frame["captured_at"])
```

Notes for the implementer:
- The test cameras are named after their ids (`cam()` in `tests/test_agent_tools.py`), so `short_name` returns `kilauea-v1` there.
- The onset's `seen_at` is the first of the two consecutive episode-size looks. The end's `seen_at` is the fountain's last sighting on any camera.
- **The blind rule** reads "the camera's newest look is older than BLIND_AFTER". A camera whose frames are all rejected locally (fog) stops being looked at, so it goes blind after 20 min.

- [ ] **Step 4: Run the tests and the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_alerts.py`, then `.venv/Scripts/python.exe -m pytest`.
Expected: PASS. Each expected minute in the tests follows from the cadence (8 min quiet, 6 min fountaining, the next frame after an episode-size look or a miss). If one differs, trace it by hand before changing anything. **Never weaken an expectation to get green.**

- [ ] **Step 5: Commit**

```bash
git add vigil/alerts.py tests/test_alerts.py
git commit -m "Raise an onset on two consecutive episode-size fountains confirmed by Muse Spark, and an end on two misses"
```

---

### Task 8: Telegram (`vigil/telegram.py`, `vigil-telegram`)

**Files:**
- Create: `vigil/telegram.py`, `tests/test_telegram.py`
- Modify: `pyproject.toml` (`vigil-telegram = "vigil.telegram:main"`)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_telegram.py`:

```python
import json
import logging

import httpx
import pytest

from vigil.telegram import CAPTION_MAX, Telegram, TelegramError, main

TOKEN = "123456:SECRET-token"


def bot(handler, chat="@volcano_vigil"):
    return Telegram(httpx.Client(transport=httpx.MockTransport(handler)), TOKEN, chat)


def ok(result):
    return httpx.Response(200, json={"ok": True, "result": result})


def test_a_photo_is_posted_as_multipart_with_the_chat_and_the_caption():
    seen = []

    def handler(request):
        seen.append(request)
        return ok({"message_id": 42})

    message_id = bot(handler).send_photo(b"\xff\xd8jpeg", "Lava fountaining seen")

    assert message_id == 42
    request = seen[0]
    assert request.url.path == f"/bot{TOKEN}/sendPhoto"
    body = request.content
    assert b'name="chat_id"' in body and b"@volcano_vigil" in body
    assert b'name="caption"' in body and b"Lava fountaining seen" in body
    assert b'name="photo"; filename="alert.jpg"' in body and b"\xff\xd8jpeg" in body


def test_a_caption_over_telegrams_limit_is_refused_before_any_request():
    def handler(request):
        raise AssertionError("no request expected")

    with pytest.raises(ValueError, match="1024"):
        bot(handler).send_photo(b"jpeg", "x" * (CAPTION_MAX + 1))


def test_an_api_error_says_what_failed_without_the_token():
    def handler(request):
        return httpx.Response(401, json={"ok": False, "error_code": 401, "description": "Unauthorized"})

    with pytest.raises(TelegramError) as raised:
        bot(handler).send_message("hello")

    assert "sendMessage: 401 Unauthorized" in str(raised.value)
    assert TOKEN not in str(raised.value) and raised.value.__cause__ is None


def test_a_network_error_never_carries_the_token():
    def handler(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    with pytest.raises(TelegramError) as raised:
        bot(handler).send_message("hello")

    assert TOKEN not in str(raised.value) and "<token>" in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__  # `from None`: no URL in a traceback


def test_check_says_who_posts_where_and_whether_it_may():
    answers = {"getMe": {"id": 7, "username": "volcano_vigil_bot"},
               "getChat": {"id": -1001, "title": "Volcano Vigil", "type": "channel"},
               "getChatMember": {"status": "administrator", "can_post_messages": True}}

    def handler(request):
        return ok(answers[request.url.path.rsplit("/", 1)[1]])

    assert bot(handler).check() == {"bot": "@volcano_vigil_bot", "chat": "Volcano Vigil", "chat_id": -1001,
                                    "type": "channel", "status": "administrator", "can_post": True}


def test_a_member_that_is_not_an_admin_may_not_post():
    answers = {"getMe": {"id": 7, "username": "b"}, "getChat": {"id": -1, "title": "c", "type": "channel"},
               "getChatMember": {"status": "left"}}

    result = bot(lambda request: ok(answers[request.url.path.rsplit("/", 1)[1]])).check()

    assert result["can_post"] is False


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr("vigil.settings.load_dotenv", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@volcano_vigil")
    monkeypatch.setenv("SOURCES_PATH", "config/sources.yaml")


def test_cli_check_prints_the_summary_and_never_the_token(env, monkeypatch, capsys):
    monkeypatch.setattr(Telegram, "check", lambda self: {"bot": "@b", "chat": "Volcano Vigil", "chat_id": -1001,
                                                         "type": "channel", "status": "administrator",
                                                         "can_post": True})

    main(["check"])

    out = capsys.readouterr().out
    assert "@b posts to Volcano Vigil (-1001, channel): administrator, may post: yes" in out
    assert TOKEN not in out
    assert logging.getLogger("httpx").level == logging.WARNING  # its request lines would print the token


def test_cli_test_posts_a_message_that_says_it_is_not_an_alert(env, monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(Telegram, "send_message", lambda self, text: sent.append(text) or 9)

    main(["test"])

    assert "not an alert" in sent[0] and "no es una alerta" in sent[0]
    assert "https://www.usgs.gov/volcanoes/kilauea" in sent[0]
    assert "message 9" in capsys.readouterr().out


def test_cli_needs_the_token_and_the_channel(monkeypatch, capsys):
    monkeypatch.setattr("vigil.settings.load_dotenv", lambda: None)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    with pytest.raises(SystemExit):
        main(["check"])

    assert "TELEGRAM_BOT_TOKEN" in capsys.readouterr().err
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_telegram.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigil.telegram'`.

- [ ] **Step 3: Implement** `vigil/telegram.py`:

```python
"""Telegram: post the fountaining alerts to a public channel through a bot (https://core.telegram.org/bots/api).

The bot's token is a secret, and the Bot API puts it in the URL of every request. So this module never logs a
request, it takes the token out of every error it raises, and its CLI raises the httpx logger to WARNING (httpx
logs each request's URL at INFO).

    vigil-telegram check   # the token works, and the bot may post in the channel
    vigil-telegram test    # post a message that says it is a test, not an alert
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

import httpx

from vigil.config import load_sources
from vigil.settings import Settings

API = "https://api.telegram.org"
CAPTION_MAX = 1024  # characters in a photo's caption (Bot API, sendPhoto)
TEST_MESSAGE = ("Volcano Vigil test message: the alert channel works. It is not an alert.\n"
                "Mensaje de prueba de Volcano Vigil: el canal de alertas funciona. No es una alerta.\n\n"
                "Official status / Estado oficial: {agency}: {url}")


class TelegramError(RuntimeError):
    """A Bot API call failed. The message never holds the token."""


class Telegram:
    def __init__(self, http: httpx.Client, token: str, chat: str, api: str = API):
        self._http, self._token, self.chat, self._api = http, token, chat, api

    def _call(self, method: str, *, data: dict[str, Any] | None = None, files: dict[str, Any] | None = None) -> Any:
        try:
            response = self._http.post(f"{self._api}/bot{self._token}/{method}", data=data, files=files, timeout=30)
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramError(self._redact(f"{method}: {type(exc).__name__}: {exc}")) from None
        if not body.get("ok"):
            raise TelegramError(self._redact(f"{method}: {body.get('error_code')} {body.get('description')}"))
        return body["result"]

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "<token>")

    def send_photo(self, photo: bytes, caption: str) -> int:
        """Post a JPEG with its caption; returns the message id."""
        if len(caption) > CAPTION_MAX:
            raise ValueError(f"a caption has at most {CAPTION_MAX} characters; this one has {len(caption)}")
        result = self._call("sendPhoto", data={"chat_id": self.chat, "caption": caption},
                            files={"photo": ("alert.jpg", photo, "image/jpeg")})
        return result["message_id"]

    def send_message(self, text: str) -> int:
        return self._call("sendMessage", data={"chat_id": self.chat, "text": text})["message_id"]

    def check(self) -> dict[str, Any]:
        """Who the bot is, which chat it posts to, and whether it may post there."""
        me = self._call("getMe")
        chat = self._call("getChat", data={"chat_id": self.chat})
        member = self._call("getChatMember", data={"chat_id": self.chat, "user_id": me["id"]})
        return {"bot": f"@{me['username']}", "chat": chat.get("title") or chat.get("username") or str(chat["id"]),
                "chat_id": chat["id"], "type": chat["type"], "status": member["status"],
                "can_post": member["status"] == "creator" or bool(member.get("can_post_messages"))}


def describe(check: dict[str, Any]) -> str:
    return (f"{check['bot']} posts to {check['chat']} ({check['chat_id']}, {check['type']}): {check['status']}, "
            f"may post: {'yes' if check['can_post'] else 'no'}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Check the Telegram bot that posts the fountaining alerts, or post "
                                                 "a test message to its channel.")
    parser.add_argument("action", choices=["check", "test"])
    parser.add_argument("--volcano", default="kilauea", help="whose official agency the test message links to")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if not settings.telegram_token or not settings.telegram_chat:
        parser.error("set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (in .env locally, as Space secrets on the Space)")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its request lines would print the token
    with httpx.Client() as http:
        telegram = Telegram(http, settings.telegram_token, settings.telegram_chat)
        try:
            if args.action == "check":
                print(describe(telegram.check()))
            else:
                volcano = load_sources(settings.sources_path).volcanoes[args.volcano]
                message_id = telegram.send_message(TEST_MESSAGE.format(agency=volcano.official_agency,
                                                                       url=volcano.official_url))
                print(f"posted the test as message {message_id} to {settings.telegram_chat}")
        except TelegramError as exc:
            raise SystemExit(f"Telegram: {exc}") from None
```

Add `vigil-telegram = "vigil.telegram:main"` to `[project.scripts]`, then run `.venv/Scripts/python.exe -m pip install -e ".[dev]"`. No `vigil-*.exe` may be running: the Windows install fails with WinError 32 otherwise; see the memory note.

- [ ] **Step 4: Run the tests and the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_telegram.py`, then `.venv/Scripts/python.exe -m pytest`.
Expected: PASS. `test_the_entry_point_runs_the_existing_clis_with_the_projects_arguments` still passes, since start.sh does not use `vigil-telegram`.

- [ ] **Step 5: Commit**

```bash
git add vigil/telegram.py tests/test_telegram.py pyproject.toml
git commit -m "Post to a Telegram channel through a bot without ever logging or raising its token"
```

---

### Task 9: The live loop `vigil-alerts`, posting and replay posts

**Files:**
- Modify: `vigil/alerts.py` (`send_pending`, `post_replay`, `main`), `pyproject.toml` (`vigil-alerts = "vigil.alerts:main"`)
- Test: `tests/test_alerts.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
from vigil.alerts import MAX_SEND_ATTEMPTS, main, send_pending
from vigil.telegram import TelegramError


class FakeTelegram:
    def __init__(self, fail=False):
        self.posts, self.fail = [], fail

    def send_photo(self, photo, text):
        if self.fail:
            raise TelegramError("sendPhoto: 500 Internal Server Error")
        self.posts.append((photo, text))
        return len(self.posts)


def stored(conn, tmp_path, clock="2026-11-02T13:08:00Z"):
    (tmp_path / "alerts" / "x").mkdir(parents=True, exist_ok=True)
    (tmp_path / "alerts" / "x" / "frame1.jpg").write_bytes(b"\xff\xd8jpeg")
    return store_alert(conn, make_alert(clock=clock, overlay="alerts/x/frame1.jpg"))


NOW = datetime(2026, 11, 2, 13, 9, tzinfo=timezone.utc)


def test_a_new_alert_is_posted_once_with_its_frame_and_caption(conn, tmp_path):
    alert = stored(conn, tmp_path)
    telegram = FakeTelegram()

    assert send_pending(conn, telegram, tmp_path, NOW) == []
    assert send_pending(conn, telegram, tmp_path, NOW) == []

    assert telegram.posts == [(b"\xff\xd8jpeg", caption(alert))]
    assert conn.execute("SELECT sent_at FROM alerts").fetchone()[0] == "2026-11-02T13:09:00Z"


def test_a_failed_post_is_tried_again_and_given_up_after_five_attempts(conn, tmp_path):
    stored(conn, tmp_path)
    telegram = FakeTelegram(fail=True)

    errors = [send_pending(conn, telegram, tmp_path, NOW) for _ in range(MAX_SEND_ATTEMPTS + 2)]

    assert [len(e) for e in errors] == [1] * MAX_SEND_ATTEMPTS + [0, 0]
    row = conn.execute("SELECT sent_at, send_attempts, send_error FROM alerts").fetchone()
    assert (row[0], row[1]) == (None, MAX_SEND_ATTEMPTS) and "500" in row[2]


def test_an_alert_older_than_two_hours_is_never_posted(conn, tmp_path):
    stored(conn, tmp_path, clock="2026-11-02T10:00:00Z")
    telegram = FakeTelegram()

    send_pending(conn, telegram, tmp_path, NOW)

    assert telegram.posts == []


def test_cli_refuses_an_alert_camera_that_is_not_enabled(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("vigil.settings.load_dotenv", lambda: None)
    sources = tmp_path / "sources.yaml"
    sources.write_text(
        "volcanoes:\n  kilauea: {name: Kilauea, country: US, official_agency: HVO, official_url: 'https://x'}\n"
        "cameras:\n  - {id: kilauea-k2, name: K2cam, volcano: kilauea, url: 'https://x/k2.jpg',\n"
        "     license: PD, attribution: USGS, enabled: true}\n", encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("ALERTS_PATH", str(ROOT / "config" / "alerts.yaml"))  # watches kilauea-v1 too

    with pytest.raises(SystemExit):
        main(["--volcano", "kilauea", "--once"])

    assert "kilauea-v1" in capsys.readouterr().err
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_alerts.py -k "posted or post or cli"`
Expected: FAIL with `ImportError: cannot import name 'MAX_SEND_ATTEMPTS'`.

- [ ] **Step 3: Implement** (add to `vigil/alerts.py`; new imports: `argparse`, `sys`, `time`, `from contextlib import closing`, `import httpx`, `from vigil import db`, `from vigil.agent.loop import context_from_settings`, `from vigil.config import load_sources`, `from vigil.episodes import EPISODES`, `from vigil.meta.ledger import CostLedger`, `from vigil.settings import Settings`, `from vigil.telegram import Telegram, TelegramError, describe`)

Check for an import cycle first. `vigil.episodes` imports only `timeutil` and numpy. `vigil.replay` will import `vigil.alerts` (Task 13), and `vigil.alerts` must not import `vigil.replay`: for the replay database path, use `data_dir / "replay" / f"ep{key}" / "vigil.sqlite"` directly, as `replay_dir` does.

```python
SEND_WITHIN = timedelta(hours=2)  # an alert older than this is never posted (after a long outage, say)
MAX_SEND_ATTEMPTS = 5
REPLAY_NOTE = "REPLAY of episode {key} ({date}): not a live alert. / REPETICIÓN del episodio {key}: no es una alerta en vivo."


def send_pending(conn: sqlite3.Connection, telegram: Telegram, data_dir: Path, now: datetime) -> list[str]:
    """Post the alerts raised in the last SEND_WITHIN that are not posted yet, oldest first; returns the failures. A
    failed post is tried again on later steps, MAX_SEND_ATTEMPTS times in all."""
    errors = []
    rows = conn.execute(
        "SELECT id, body FROM alerts WHERE sent_at IS NULL AND send_attempts < ? AND clock >= ? ORDER BY clock, id",
        (MAX_SEND_ATTEMPTS, to_iso(now - SEND_WITHIN))).fetchall()
    for row in rows:
        alert = Alert.model_validate_json(row["body"])
        try:
            telegram.send_photo((data_dir / alert.overlay).read_bytes(), caption(alert))
        except (TelegramError, OSError) as exc:
            with conn:
                conn.execute("UPDATE alerts SET send_attempts = send_attempts + 1, send_error = ? WHERE id = ?",
                             (str(exc)[:300], row["id"]))
            errors.append(f"alert {row['id']} not posted: {exc}"[:300])
            continue
        with conn:
            conn.execute("UPDATE alerts SET sent_at = ?, send_error = NULL WHERE id = ?", (to_iso(now), row["id"]))
    return errors


def post_replay(data_dir: Path, key: str, telegram: Telegram) -> list[int]:
    """Post an episode's replayed alerts, each marked as a replay (for demos); returns the message ids."""
    path = data_dir / "replay" / f"ep{key}" / "vigil.sqlite"
    with closing(db.connect_readonly(path)) as conn:
        alerts = [Alert.model_validate_json(row[0]) for row in conn.execute("SELECT body FROM alerts ORDER BY clock")]
    prefix = REPLAY_NOTE.format(key=key, date=EPISODES[key].start.date().isoformat())
    return [telegram.send_photo((data_dir / alert.overlay).read_bytes(), caption(alert, prefix)) for alert in alerts]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Watch a volcano's alert cameras (config/alerts.yaml) for lava "
                                                 "fountaining starting and stopping, and post each change to "
                                                 "Telegram. Run vigil-ingest alongside it.")
    parser.add_argument("--volcano", required=True, help="volcano id from the sources file, e.g. kilauea")
    parser.add_argument("--interval", type=float, default=1, help="minutes between steps (default 1)")
    parser.add_argument("--once", action="store_true", help="run one step and exit")
    parser.add_argument("--post-replay", metavar="EPISODE", choices=sorted(EPISODES),
                        help="post that episode's replayed alerts to Telegram, marked as a replay, and exit")
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be positive")
    settings = Settings.from_env()
    sources = load_sources(settings.sources_path)
    if args.volcano not in sources.volcanoes:
        parser.error(f"unknown volcano {args.volcano!r} in {settings.sources_path}")
    config = load_alert_config(settings.alerts_path)
    enabled = {camera.id for camera in sources.enabled_cameras() if camera.volcano == args.volcano}
    missing = [camera_id for camera_id in config.cameras if camera_id not in enabled]
    if missing:
        parser.error(f"alert cameras not enabled for {args.volcano} in {settings.sources_path}: {', '.join(missing)}")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its request lines would print the Telegram token
    with closing(db.connect(settings.db_path)) as conn, httpx.Client() as telegram_http, \
            httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=30) as http:
        telegram = (Telegram(telegram_http, settings.telegram_token, settings.telegram_chat)
                    if settings.telegram_token and settings.telegram_chat else None)
        if args.post_replay:
            if telegram is None:
                parser.error("set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to post")
            print(f"posted messages {post_replay(settings.data_dir, args.post_replay, telegram)}")
            return
        if telegram is None:
            log.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set: alerts are stored but not posted")
        else:
            try:
                log.info("Telegram: %s", describe(telegram.check()))
            except TelegramError as exc:
                log.warning("Telegram check failed (posts are still tried): %s", exc)
        client = MetaClient.from_env(CostLedger(conn, settings.daily_budget_usd))
        watcher = AlertWatcher(context_from_settings(settings, conn, http, utcnow(), client, sources), args.volcano,
                               config, settings.data_dir / "alerts", budget_usd=settings.alert_reserve_usd)
        while True:
            try:
                report = watcher.step(utcnow())
                if telegram is not None:
                    report.errors += send_pending(conn, telegram, settings.data_dir, utcnow())
                if report.looks or report.alerts or report.errors:
                    print(report.summary(), flush=True)
            except Exception:
                if args.once:
                    raise
                log.exception("the step failed; the next one tries again")
            if args.once:
                return
            time.sleep(args.interval * 60)
```

Add `vigil-alerts = "vigil.alerts:main"` to `[project.scripts]` and reinstall with `pip install -e ".[dev]"`.

- [ ] **Step 4: Run the tests and the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_alerts.py`, then `.venv/Scripts/python.exe -m pytest`.
Expected: PASS.

- [ ] **Step 5: Smoke run, $0.** Run `.venv/Scripts/vigil-alerts.exe --volcano kilauea --once` locally with an empty `TELEGRAM_*`.
  - It must print the Telegram warning and one step, and exit.
  - Without new V1/K2 frames in the last 10 min it makes no SAM call.
  - Check `api_calls` for `alerts:` purposes: there must be none, unless frames from the last 10 min existed (then ≤ 2 looks, ≤ $0.005).

- [ ] **Step 6: Commit**

```bash
git add vigil/alerts.py tests/test_alerts.py pyproject.toml
git commit -m "Run the fountaining alerts every minute and post each new alert to Telegram once"
```

---

### Task 10: Deploy wiring

**Files:**
- Modify: `deploy/start.sh`, `Dockerfile`, `vigil/persist.py:31`, `docs/DEPLOY.md`
- Test: `tests/test_deploy.py`, `tests/test_persist.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_deploy.py`:
- `test_the_entry_point_runs_the_existing_clis_with_the_projects_arguments`: add `assert "supervise vigil-alerts --volcano kilauea &" in script`.
- `test_the_services_stop_before_the_last_save_so_nothing_writes_during_it`: add `assert 'kill "$ingest_pid" "$pipeline_pid" "$alerts_pid"' in stop and 'wait "$ingest_pid" "$pipeline_pid" "$alerts_pid"' in stop`.
- `test_the_image_carries_the_daily_budget_and_the_dirs_every_service_shares`: add `assert "ALERT_RESERVE_USD=0.75" in dockerfile`.

In `tests/test_persist.py`, fixture `data`: add

```python
    (data / "alerts" / "20261102T1310Z_onset").mkdir(parents=True)
    (data / "alerts" / "20261102T1310Z_onset" / "frame1.jpg").write_bytes(b"alert")
```

Add `"alerts/20261102T1310Z_onset/frame1.jpg"` to the expected list in `test_backup_saves_the_frames_the_bulletins_and_the_database_but_not_the_replay`. Rename the test to `…_the_bulletins_the_alerts_and_the_database_but_not_the_replay`, and check the restore test still lists what it restores.

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deploy.py tests/test_persist.py`
Expected: FAIL on the new assertions.

- [ ] **Step 3: Implement**

`deploy/start.sh`, after `pipeline_pid=$!`:

```bash
supervise vigil-alerts --volcano kilauea &
alerts_pid=$!
```

and in `stop()`:

```bash
  kill "$ingest_pid" "$pipeline_pid" "$alerts_pid" 2>/dev/null
  wait "$ingest_pid" "$pipeline_pid" "$alerts_pid"
```

Update the header comment so the alerts are named among the live services.

`Dockerfile` ENV block: add `ALERT_RESERVE_USD=0.75 \` after `DAILY_BUDGET_USD=5 \`.

`vigil/persist.py`: `FOLDERS = ("frames", "bulletins", "alerts")  # saved as files, before the database`. Update the module docstring's "the frames and the bulletins" to "the frames, the bulletins and the alerts' frames".

`docs/DEPLOY.md`, new section "Fountaining alerts and Telegram":
- What runs: `vigil-alerts --volcano kilauea`, every minute, supervised.
- Its spend: tag `alerts:<date>`, at most $0.75/day; the pipeline stops at $4.25.
- The secrets: `TELEGRAM_BOT_TOKEN` is a Space secret, `TELEGRAM_CHAT_ID` a Space variable.
- How to see its log lines: `vigil-space logs`, or the run-log SSE endpoint already in the runbook; grep `Telegram:` and `ALERT`.
- How to read the alerts: `SELECT id, kind, clock, captured_at, sent_at, send_error FROM alerts` on the bucket's copy of the database.
- The extra catch-up time at start: V1 adds ~720 frames per 24 h, so ~5 min at ~0.4 s per frame.

- [ ] **Step 4: Run the suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add deploy/start.sh Dockerfile vigil/persist.py docs/DEPLOY.md tests/test_deploy.py tests/test_persist.py
git commit -m "Run the fountaining alerts on the Space and save their frames with the state"
```

---

### Task 11: The Telegram bot and channel (user + orchestrator, $0)

The user's own Telegram account is needed. The orchestrator guides in Spanish and **never reads `.env` and never sees the token**.

- [ ] **Step 1: The bot (user).** In Telegram, open **@BotFather** → `/newbot` → name `Volcano Vigil` → a username ending in `bot` (e.g. `volcano_vigil_bot`). BotFather replies with the token. Keep it private.
- [ ] **Step 2: The channel (user).**
  - New Channel, named `Volcano Vigil · Kīlauea`, with the description: "Automated, experimental fountaining alerts from USGS webcams. Not official: see USGS HVO, https://www.usgs.gov/volcanoes/kilauea".
  - Make it **Public**, with a link such as `t.me/volcano_vigil_kilauea`.
- [ ] **Step 3: The bot as admin (user).** Open the channel, then Administrators → Add Admin → search for the bot → enable **Post messages** → Save.
- [ ] **Step 4: Local settings (user).** Add to `.env` `TELEGRAM_BOT_TOKEN=<token>` and `TELEGRAM_CHAT_ID=@volcano_vigil_kilauea`.
- [ ] **Step 5: Check (orchestrator).** Run `.venv/Scripts/vigil-telegram.exe check`.
  - Expected: `@volcano_vigil_bot posts to Volcano Vigil · Kīlauea (-100…, channel): administrator, may post: yes`.
  - Write down the numeric chat id. It is not a secret.
- [ ] **Step 6: Test message (orchestrator).** Run `.venv/Scripts/vigil-telegram.exe test`. The user confirms that it arrived on the channel.
- [ ] **Step 7: Space settings.**
  - **User:** on https://huggingface.co/spaces/facurie/volcano-vigil/settings → Variables and secrets → New secret, add `TELEGRAM_BOT_TOKEN` with the token.
  - **Orchestrator:** add the public variable with `.venv/Scripts/python.exe -c "from huggingface_hub import HfApi; HfApi().add_space_variable('facurie/volcano-vigil', 'TELEGRAM_CHAT_ID', '@volcano_vigil_kilauea')"`.
- [ ] **Step 8: Record (orchestrator).** In `docs/DEPLOY.md`, note the channel's public link, the bot's username and the numeric chat id. Commit: `git add docs/DEPLOY.md && git commit -m "Name the public Telegram channel and bot that post the fountaining alerts"`.

---

### Task 12: First deploy with live alerts (orchestrator; starts the approved alert spend)

- [ ] **Step 1:** Run the suite. Then `git push`, and `.venv/Scripts/vigil-space.exe deploy --repo facurie/volcano-vigil`.
- [ ] **Step 2:** Follow the run log (runbook command) until all of these are seen:
  - `vigil-persist restore` OK;
  - the catch-up including `kilauea-v1` frames;
  - `Telegram: @… posts to … may post: yes`;
  - the first `vigil-alerts` step lines once a V1/K2 frame of the last 10 min exists.
- [ ] **Step 3:** After about an hour, read the bucket's database copy (runbook):
  - `SELECT purpose, COUNT(*), SUM(cost_usd) FROM api_calls WHERE purpose LIKE 'alerts:%' GROUP BY 1`. Expect at most ~8 looks per hour per camera, since V1 checks every 8 min while lava is visible, and K2 every 30 min by day.
  - `SELECT size, COUNT(*) FROM alert_checks GROUP BY 1`.
  - Check that `vigil-pipeline` still runs (bulletins every hour).
- [ ] **Step 4:** Open https://facurie-volcano-vigil.hf.space. V1cam must appear among the live cameras with a condition: the pipeline's local verdicts. No alert is expected today; overflows are fine.

---

### Task 13: The replay runs the alerts (`replay_alerts`, `--quiet overflows`, the alert rows)

**Files:**
- Modify: `vigil/episodes.py` (`Episode.notices`, `QuietWindow`, `QUIET_WINDOWS`), `vigil/replay.py`
- Test: `tests/test_replay.py`, `tests/test_episodes.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_episodes.py`:

```python
from vigil.episodes import EP55, QUIET_WINDOWS


def test_episode_55_knows_hvos_onset_and_end_notices():
    assert to_iso(EP55.notices["onset"]) == "2026-10-17T13:43:00Z"  # VAN 2026/H488, 03:43 HST
    assert to_iso(EP55.notices["end"]) == "2026-10-17T19:11:00Z"    # VAN 2026/H489, 09:11 HST


def test_the_overflow_window_ends_where_episode_55s_frames_start():
    window = QUIET_WINDOWS["overflows"]

    assert (to_iso(window.start), to_iso(window.end)) == ("2026-10-16T08:00:00Z", "2026-10-17T13:00:00Z")
    assert window.end == EP55.start and window.volcano == "kilauea"
```

(Import `to_iso` if the file lacks it.)

Append to `tests/test_replay.py`:

```python
from test_alerts import LARGE, SMALL, V1_ONLY, Fakes, make_alert, scene_jpeg
from test_meta_client import FakeApi, make_client
from vigil.alerts import AlertWatcher, store_alert
from vigil.replay import ALERT_HEADER, alert_rows, replay_alerts


def alert_source(tmp_path):
    """A source database with V1 frames every 2 min from 40 min before T0 to 30 min after it."""
    source = db.connect(tmp_path / "source.sqlite")
    store = FrameStore(source, tmp_path)
    ids = {}
    for minute in range(-40, 31, 2):
        when = T0 + minute * M
        ids[minute] = store.add("kilauea-v1", scene_jpeg(minute + 1000), captured_at=when,
                                timestamp_source="ashcam", fetched_at=when)
    return source, ids


def alert_watcher(conn, tmp_path, fakes):
    client = make_client(FakeApi(lambda request: httpx.Response(500)), conn, budget=5.0)
    return AlertWatcher(context(conn, tmp_path, client=client, now=T0), "kilauea", V1_ONLY, tmp_path / "alerts",
                        budget_usd=0.75, segment=fakes.segment, compare=fakes.compare)


def test_the_alerts_replay_on_a_one_minute_clock_and_never_see_past_it(conn, tmp_path):
    source, ids = alert_source(tmp_path)
    fakes = Fakes()
    fakes.sam = {frame_id: (LARGE if minute >= 6 else SMALL) for minute, frame_id in ids.items()}

    replay_alerts(source, alert_watcher(conn, tmp_path, fakes), T0, T0 + 20 * M)

    clocks = [row[0] for row in conn.execute("SELECT clock FROM alert_ticks ORDER BY clock")]
    assert clocks == [to_iso(T0 + minute * M) for minute in range(1, 21)]
    first_fed = conn.execute("SELECT MIN(captured_at) FROM frames").fetchone()[0]
    assert first_fed == to_iso(T0 - 30 * M)  # the warm-up, for Muse Spark's comparison
    assert conn.execute("SELECT COUNT(*) FROM alert_checks WHERE captured_at > clock").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM alerts WHERE captured_at > clock").fetchone()[0] == 0
    assert [row[0] for row in conn.execute("SELECT kind FROM alerts")] == ["onset"]


def test_an_interrupted_alerts_replay_resumes_after_its_last_tick(conn, tmp_path):
    source, _ = alert_source(tmp_path)
    with conn:
        conn.execute("INSERT INTO alert_ticks (clock, report) VALUES (?, '{}')", (to_iso(T0 + M),))

    ran = replay_alerts(source, alert_watcher(conn, tmp_path, Fakes()), T0, T0 + 3 * M)

    assert ran == 2

    assert conn.execute("SELECT COUNT(*) FROM alert_ticks").fetchone()[0] == 3


def test_alert_rows_set_the_alerts_against_hvos_times_and_notices(conn):
    store_alert(conn, make_alert("onset", clock="2026-10-17T13:10:00Z", captured_at="2026-10-17T13:09:02Z",
                                 seen_at="2026-10-17T13:07:02Z", seen_by="V1cam"))
    store_alert(conn, make_alert("end", clock="2026-10-17T19:09:00Z", captured_at="2026-10-17T19:08:02Z",
                                 seen_at="2026-10-17T19:02:01Z", seen_by="K2cam"))

    rows = alert_rows(conn, EP55)

    assert ALERT_HEADER == ["Event", "Seen (local)", "Camera", "Official (local)", "Seen vs official",
                            "Alert (local)", "Alert vs official", "HVO notice (local)", "Alert vs notice"]
    assert rows == [["fountaining started", "03:07", "V1cam", "03:19", "-12 min", "03:10", "-9 min", "03:43", "-33 min"],
                    ["fountaining stopped", "09:02", "K2cam", "09:03", "-1 min", "09:09", "+6 min", "09:11", "-2 min"]]


def test_alert_rows_without_alerts_say_none(conn):
    rows = alert_rows(conn, EP55)

    assert [row[:2] for row in rows] == [["fountaining started", "none"], ["fountaining stopped", "none"]]


def test_cli_knows_the_quiet_windows(capsys):
    with pytest.raises(SystemExit):
        main(["--quiet", "nowhere"])

    assert "overflows" in capsys.readouterr().err
```

(`T0`, `M`, `context`, `FrameStore`, `db`, `to_iso`, `EP55`, `main` and `pytest` are already imported in `tests/test_replay.py`; add `import httpx`. The local `T0` there is `test_agent_tools.T0`, 15:00Z Oct 17, at night, so the lava frames pass. With `ALERT_STEP` of 1 min, the first test runs ticks 1–20, and the onset comes from the looks at 8 (large, no pair yet) and 10 (the follow-up), compared with frame −20.)

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_replay.py tests/test_episodes.py -k "alert or notice or quiet or overflow"`
Expected: FAIL with `ImportError: cannot import name 'ALERT_HEADER'`.

- [ ] **Step 3: Implement**

`vigil/episodes.py`: add the field `notices: dict[str, datetime] = field(default_factory=dict)  # HVO's onset and end notices (VAN), UTC`, last in `Episode` (`from dataclasses import dataclass, field`). In `EP55`:

```python
    notices={"onset": parse_utc("2026-10-17T13:43:00Z"),  # VAN 2026/H488, 03:43 HST
             "end": parse_utc("2026-10-17T19:11:00Z")},   # VAN 2026/H489, 09:11 HST
```

and after `EPISODES`:

```python
@dataclass(frozen=True)
class QuietWindow:
    """Frames with no eruptive episode in them, to test the fountaining alerts on: any alert here is a false alarm."""
    key: str
    volcano: str
    start: datetime
    end: datetime
    activity: str  # what the official record says was going on


OVERFLOWS = QuietWindow(
    key="overflows", volcano="kilauea",
    start=parse_utc("2026-10-16T08:00:00Z"), end=parse_utc("2026-10-17T13:00:00Z"),
    activity=("The 29 hours before episode 55 (22:00 HST Oct 15 to 03:00 HST Oct 17): overflows from the south vent "
              "(continuous from 05:56 HST Oct 16), the north vent (intermittent from 18:11, continuous from 23:35) "
              "and the west vent (from 22:49, continuous from 02:23), with small dome fountains; episode 55 began "
              "at 03:19 HST (HVO Daily Update, Oct 17)."),
)
QUIET_WINDOWS = {OVERFLOWS.key: OVERFLOWS}
```

`vigil/replay.py`: imports `from vigil.alerts import Alert, AlertWatcher, load_alert_config` and `from vigil.episodes import QUIET_WINDOWS, QuietWindow`. Add `"alerts"` to the docstring, and:

```python
ALERT_STEP = timedelta(minutes=1)
WARMUP = timedelta(minutes=30)  # frames fed before the window, for Muse Spark's comparisons
ALERT_HEADER = ["Event", "Seen (local)", "Camera", "Official (local)", "Seen vs official", "Alert (local)",
                "Alert vs official", "HVO notice (local)", "Alert vs notice"]


def replay_alerts(source: sqlite3.Connection, watcher: AlertWatcher, start: datetime, end: datetime, *,
                  step: timedelta = ALERT_STEP) -> int:
    """Run the fountaining alerts from start to end on a simulated clock: every `step` copy the alert cameras' frames
    captured by then (from WARMUP before the start) into the watcher's database and run one watcher step. Each step's
    report goes to alert_ticks, so an interrupted run resumes; returns the steps run."""
    conn = watcher.base.conn
    done = {row[0] for row in conn.execute("SELECT clock FROM alert_ticks")}
    fed, ran = start - WARMUP, 0
    for tick in ticks(start, end, step):
        if to_iso(tick) in done:
            continue
        feed(source, conn, watcher.cameras, fed, tick)
        fed = tick
        report = watcher.step(tick)
        with conn:
            conn.execute("INSERT INTO alert_ticks (clock, report) VALUES (?, ?)",
                         (to_iso(tick), json.dumps(report.as_json())))
        ran += 1
        if report.alerts or report.errors:
            log.info("%s", report.summary())
    return ran


def _minutes(later: str, earlier: datetime) -> str:
    return f"{(parse_utc(later) - earlier) / timedelta(minutes=1):+.0f} min"


def alert_rows(conn: sqlite3.Connection, episode: Episode) -> list[list[str]]:
    """The first onset and end alerts of the episode against the official times and HVO's notices."""
    rows = []
    for kind, event in (("onset", "fountaining started"), ("end", "fountaining stopped")):
        official, notice = episode.phases[kind][0], episode.notices[kind]
        official_text = local_time(to_iso(official), episode.local)
        notice_text = local_time(to_iso(notice), episode.local)
        row = conn.execute("SELECT body FROM alerts WHERE volcano = ? AND kind = ? AND clock >= ? "
                           "ORDER BY clock, id LIMIT 1", (episode.volcano, kind, to_iso(episode.start))).fetchone()
        if row is None:
            rows.append([event, "none", "", official_text, "", "", "", notice_text, ""])
            continue
        alert = Alert.model_validate_json(row["body"])
        rows.append([event, local_time(alert.seen_at, episode.local), alert.seen_by, official_text,
                     _minutes(alert.seen_at, official), local_time(alert.clock, episode.local),
                     _minutes(alert.clock, official), notice_text, _minutes(alert.clock, notice)])
    return rows


def alert_looks(conn: sqlite3.Connection) -> str:
    """One line on what the alerts looked at: SAM's looks by size and Muse Spark's comparisons."""
    sizes = dict(conn.execute("SELECT size, COUNT(*) FROM alert_checks GROUP BY size").fetchall())
    asked = conn.execute("SELECT COUNT(*) FROM alert_checks WHERE spark IS NOT NULL").fetchone()[0]
    parts = ", ".join(f"{size} {sizes.get(size, 0)}" for size in ("none", "small", "ambiguous", "large"))
    return f"{sum(sizes.values())} SAM looks ({parts}); Muse Spark compared {asked} frames"
```

`_minutes` prints `-12 min`, `+6 min`; `local_time` is `vigil.episodes.local_time` (HH:MM in the episode's zone).

In `run_replay`, add the parameter `alerts: AlertWatcher | None = None`. After the tick loop and before `_spark_phases`:

```python
    if alerts is not None:
        replay_alerts(source, alerts, episode.start, episode.end)
```

In `build_timeline`, add `"alerts": [json.loads(row[0]) for row in conn.execute("SELECT body FROM alerts WHERE volcano = ? ORDER BY clock, id", (episode.volcano,))]` and, in `comparison`, `"alerts": alert_rows(conn, episode)`. In `report_markdown`, after the activity section:

```python
        "## Fountaining alerts", "",
        "The alerts' watcher replayed on a one-minute clock (vigil.alerts): when it first saw the fountain at "
        "episode size and when it last saw it, and when it raised each alert.", "",
        table(ALERT_HEADER, comparison["alerts"]), "",
```

Build the looks line from the database, not the timeline: `report_markdown` gets the timeline only, so add `timeline["alert_looks"] = alert_looks(conn)` in `build_timeline` and print it under the table.

Add `quiet_report(conn, window)`:

```python
def quiet_report(conn: sqlite3.Connection, window: QuietWindow) -> str:
    """report.md of a quiet window: every alert here is a false alarm."""
    alerts = [Alert.model_validate_json(row[0]) for row in conn.execute("SELECT body FROM alerts ORDER BY clock")]
    cost = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM api_calls").fetchone()[0]
    lines = [f"# Fountaining alerts over the {window.key} frames", "", window.activity, "",
             f"From {to_iso(window.start)} to {to_iso(window.end)} on a one-minute clock. {alert_looks(conn)}. "
             f"Meta API cost: ${cost:.2f}.", "",
             f"**Alerts raised: {len(alerts)}** (expected none).", ""]
    if alerts:
        lines += [table(["Kind", "Clock (UTC)", "Camera", "Frame (UTC)"],
                        [[a.kind, a.clock, a.camera_name, a.captured_at] for a in alerts]), ""]
    return "\n".join(lines)
```

`main`: replace `--episode` with a required mutually exclusive group, and add `--no-alerts`:

```python
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--episode", choices=sorted(EPISODES), help="which episode")
    target.add_argument("--quiet", choices=sorted(QUIET_WINDOWS),
                        help="a window with no episode: run only the fountaining alerts, which must stay silent")
    parser.add_argument("--no-alerts", action="store_true", help="do not run the fountaining alerts over the episode")
```

After building `settings`, handle `--quiet` first:

```python
    if args.quiet:
        window = QUIET_WINDOWS[args.quiet]
        config = load_alert_config(settings.alerts_path)
        out_dir = settings.data_dir / "replay" / window.key
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        with closing(db.connect(settings.db_path)) as source:
            marks = ",".join("?" * len(config.cameras))
            stored = source.execute(f"SELECT COUNT(*) FROM frames WHERE camera_id IN ({marks}) AND captured_at "
                                    "BETWEEN ? AND ?", (*config.cameras, to_iso(window.start), to_iso(window.end)))
            if not stored.fetchone()[0]:
                parser.error(f"{settings.db_path} has no frames of the {window.key} window; backfill them")
            with closing(db.connect(out_dir / "vigil.sqlite")) as conn, \
                    httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=30) as http:
                client = MetaClient.from_env(CostLedger(conn, settings.daily_budget_usd))
                watcher = AlertWatcher(context_from_settings(settings, conn, http, window.start, client),
                                       window.volcano, config, out_dir / "alerts",
                                       budget_usd=settings.alert_reserve_usd)
                replay_alerts(source, watcher, window.start, window.end)
                (out_dir / "report.md").write_text(quiet_report(conn, window), encoding="utf-8")
        print((out_dir / "report.md").read_text(encoding="utf-8"))
        return
```

For episodes, build the watcher the same way inside the existing `with` block, with `out_dir / "alerts"` and the episode's volcano, unless `args.no_alerts`. Pass it as `run_replay(..., alerts=watcher)`.

- [ ] **Step 4: Run the tests and the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_replay.py tests/test_episodes.py`, then `.venv/Scripts/python.exe -m pytest`.
Expected: PASS. The existing replay tests pass `alerts=None` by default, and their timelines now carry `"alerts": []` and comparison rows that say "none".

- [ ] **Step 5: Commit**

```bash
git add vigil/episodes.py vigil/replay.py tests/test_replay.py tests/test_episodes.py
git commit -m "Replay the fountaining alerts on a one-minute clock over an episode or a window with no episode"
```

---

### Task 14: The dashboard banner and the alerts table

**Files:**
- Modify: `vigil/web/views.py`, `vigil/web/app.py` (`media_file`, `/api/alerts`), `vigil/web/static/index.html`, `vigil/web/static/css/app.css`, `vigil/web/static/js/lib.js`, `vigil/web/static/js/main.js`
- Create: `vigil/web/static/js/alerts.js`
- Test: `tests/test_web_views.py`, `tests/test_web_app.py`, `tests/test_web_static.py`, `tests/js/lib.test.mjs`

Read `.interface-design/system.md` first. The banner is a word plus the fountain's colour (`--lava`), never an alert-level colour scheme. It sits under the sticky notice, so the disclaimer and the HVO link stay next to it.

- [ ] **Step 1: Write the failing tests**

`tests/test_web_views.py` (its helper is `scene(conn, tmp_path, clock=T0, episode=None, cameras=…)`):

```python
import sqlite3

from test_alerts import make_alert
from vigil.alerts import store_alert


def test_alerts_show_only_those_raised_by_the_clock_and_the_state_they_leave(conn, tmp_path):
    store_alert(conn, make_alert("onset", clock="2026-10-17T13:10:00Z"))
    store_alert(conn, make_alert("end", clock="2026-10-17T19:09:00Z"))

    before = views.alerts(scene(conn, tmp_path, clock=parse_utc("2026-10-17T13:09:59Z")))
    during = views.alerts(scene(conn, tmp_path, clock=parse_utc("2026-10-17T15:00:00Z")))
    after = views.alerts(scene(conn, tmp_path, clock=parse_utc("2026-10-17T19:30:00Z")))

    assert (before["state"], before["alerts"]) == ("quiet", [])
    assert during["state"] == "fountaining" and [a["kind"] for a in during["alerts"]] == ["onset"]
    assert after["state"] == "quiet" and [a["kind"] for a in after["alerts"]] == ["end", "onset"]
    shown = during["alerts"][0]
    assert set(shown) >= {"id", "kind", "clock", "captured_at", "seen_at", "seen_by", "camera_id", "overlay",
                          "official_agency", "official_url", "en", "es"}
    assert set(shown["en"]) == {"headline", "text", "disclaimer"}


def test_a_database_from_before_the_alerts_has_none(tmp_path):
    old = sqlite3.connect(tmp_path / "old.sqlite")
    old.execute("CREATE TABLE frames (id INTEGER)")
    old.row_factory = sqlite3.Row

    assert views.alerts(scene(old, tmp_path)) == {"state": "quiet", "alerts": []}


def test_the_replays_results_list_the_alerts_table_when_the_timeline_has_one(conn, tmp_path):
    folder = tmp_path / "replay" / "ep55"
    folder.mkdir(parents=True)
    row = ["fountaining started", "03:07", "V1cam", "03:19", "-12 min", "03:10", "-9 min", "03:43", "-33 min"]
    comparison = {"heights": [], "ends": [], "drift": [], "bulletins": [], "activity": [], "alerts": [row]}
    (folder / "timeline.json").write_text(json.dumps({"step_minutes": 5, "comparison": comparison, "phases": None,
                                                      "cost_usd": 1.4}), encoding="utf-8")

    shown = views.replay_state(scene(conn, tmp_path, clock=EP55.end, episode=EP55), folder)

    table = next(t for t in shown["results"]["tables"] if t["title"] == "Fountaining alerts against the official times")
    assert table["rows"] == [row]
```

(`test_the_replays_results_show_only_at_the_episodes_end` already covers an older timeline without `alerts`: it must keep passing.)

`tests/test_web_app.py`:

```python
def test_alerts_endpoint_answers_with_the_state_live_and_in_replay(client):
    live = client.get("/api/alerts")
    replay = client.get("/api/alerts", params=AT)

    assert live.status_code == 200 and live.json()["state"] == "quiet" and live.json()["alerts"] == []
    assert replay.status_code == 200 and replay.json()["clock"] == to_iso(T0)


def test_media_serves_alert_frames_too(tmp_path):
    data = tmp_path / "data"
    (data / "alerts" / "x").mkdir(parents=True)
    (data / "alerts" / "x" / "frame1.jpg").write_bytes(b"jpeg")
    (data / "replay" / "ep55" / "alerts" / "y").mkdir(parents=True)
    (data / "replay" / "ep55" / "alerts" / "y" / "frame2.jpg").write_bytes(b"jpeg")

    assert media_file(data, "alerts/x/frame1.jpg") is not None
    assert media_file(data, "replay/ep55/alerts/y/frame2.jpg") is not None
    assert media_file(data, "frames/kilauea-v1/a.jpg") is None
```

`tests/test_web_static.py`:

```python
def test_the_alert_banner_sits_in_the_sticky_top_under_the_notice():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    top = page[page.index('<div class="top">'):page.index("</div>", page.index('class="notice"'))]

    assert 'id="alert-banner"' in top and top.index('class="notice"') < top.index('id="alert-banner"')
```

`tests/js/lib.test.mjs` (add `bannerAlert` to the import):

```javascript
test("the banner shows the onset while fountaining, and an end for six hours", () => {
  const onset = { kind: "onset", clock: "2026-10-17T13:10:00Z" };
  const end = { kind: "end", clock: "2026-10-17T19:09:00Z" };
  assert.equal(bannerAlert([onset], "fountaining", "2026-10-17T15:00:00Z"), onset);
  assert.equal(bannerAlert([end, onset], "quiet", "2026-10-17T19:30:00Z"), end);
  assert.equal(bannerAlert([end, onset], "quiet", "2026-10-18T01:10:00Z"), null);
  assert.equal(bannerAlert([], "quiet", "2026-10-17T15:00:00Z"), null);
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_views.py tests/test_web_app.py tests/test_web_static.py`
Expected: FAIL with `AttributeError: module 'vigil.web.views' has no attribute 'alerts'`, among others.

- [ ] **Step 3: Implement**

`vigil/web/views.py`:

```python
from vigil.alerts import Alert
from vigil.replay import ACTIVITY_HEADER, ALERT_HEADER, BULLETIN_HEADER, STEP

RESULT_TABLES = (  # the replay's comparison with the official values, as report.md titles it
    ("What the bulletins quoted against the official values", BULLETIN_HEADER, "bulletins"),
    ("Activity against the official times", ACTIVITY_HEADER, "activity"),
    ("Fountaining alerts against the official times", ALERT_HEADER, "alerts"),
    ("Measurements against the official values", HEIGHT_HEADER, "heights"),
    ("End of fountaining", END_HEADER, "ends"),
    ("Drift", DRIFT_HEADER, "drift"),
)


def alerts(scene: Scene, limit: int = 10) -> dict[str, Any]:
    """The volcano's fountaining alerts raised by the clock, newest first, and the state they leave it in. A database
    from before the alerts existed has none."""
    try:
        rows = scene.conn.execute("SELECT body FROM alerts WHERE volcano = ? AND clock <= ? "
                                  "ORDER BY clock DESC, id DESC LIMIT ?", (scene.volcano, scene.now, limit)).fetchall()
    except sqlite3.OperationalError:  # no such table: a replay mirrored before Phase 8
        return {"state": "quiet", "alerts": []}
    out = []
    for row in rows:
        a = Alert.model_validate_json(row["body"])
        out.append({"id": a.id, "kind": a.kind, "clock": a.clock, "captured_at": a.captured_at, "seen_at": a.seen_at,
                    "seen_by": a.seen_by, "camera_id": a.camera_id, "frame_id": a.frame_id, "overlay": a.overlay,
                    "official_agency": a.official_agency, "official_url": a.official_url,
                    "en": {"headline": a.headline_en, "text": a.text_en, "disclaimer": a.disclaimer_en},
                    "es": {"headline": a.headline_es, "text": a.text_es, "disclaimer": a.disclaimer_es}})
    return {"state": "fountaining" if out and out[0]["kind"] == "onset" else "quiet", "alerts": out}
```

In `replay_state`, build the tables only for keys the timeline has: `for title, header, key in RESULT_TABLES if key in comparison`.

`vigil/web/app.py`: in `media_file`, change the last line to

```python
    folders = target.relative_to(root).parts[:-1]
    return target if "bulletins" in folders or "alerts" in folders else None
```

and update its docstring ("a bulletin's evidence overlay or an alert's frame"). Add the endpoint after `/api/bulletins`:

```python
    @app.get("/api/alerts")
    def alerts(seen: Seen) -> dict:
        return {"clock": seen.now, **views.alerts(seen)}
```

`index.html`: inside `<div class="top">`, right after the notice `<p>`:

```html
  <div class="alert-banner" id="alert-banner" role="status" aria-live="polite" hidden></div>
```

`lib.js`:

```javascript
// The alert the banner shows: the onset while the volcano is fountaining, or the newest end for `hours` after it.
export function bannerAlert(alerts, state, clock, hours = 6) {
  const newest = alerts[0];
  if (!newest) return null;
  if (state === "fountaining") return newest;
  return newest.kind === "end" && Date.parse(clock) - Date.parse(newest.clock) <= hours * 3_600_000 ? newest : null;
}
```

`js/alerts.js`:

```javascript
// The fountaining banner under the notice. Alert texts are the code's, not a model's, but they still reach the DOM
// only as text (el/fill).

import { el, fill } from "./dom.js";
import * as lib from "./lib.js";

export function renderAlert(root, data, ctx) {
  const { state, config } = ctx;
  const shown = data.error ? null : lib.bannerAlert(data.alerts ?? [], data.state, ctx.scene.clock);
  root.hidden = shown === null;
  if (shown === null) {
    fill(root);
    return;
  }
  const offset = config.volcano.utc_offset_hours;
  const t = shown[state.lang];
  const safeUrl = /^https?:\/\//.test(shown.official_url);
  fill(root,
    el("span", { class: "alert-tag", dataset: { kind: shown.kind } },
      shown.kind === "onset" ? "Fountaining seen" : "Fountaining stopped"),
    el("span", { class: "alert-time mono" }, `${lib.localTime(shown.seen_at, offset)} ${lib.zone(offset)}`),
    el("span", { class: "alert-text", lang: state.lang }, t.headline),
    el("a", { href: `/media/${shown.overlay.split("/").map(encodeURIComponent).join("/")}`, target: "_blank",
      rel: "noopener" }, "Frame"),
    safeUrl ? el("a", { href: shown.official_url, target: "_blank", rel: "noopener" },
      `Official status: ${shown.official_agency}`) : null);
}
```

`main.js` `load()`:
- add `const alerts = call("/api/alerts");`;
- append `"alerts"` to `names` and `alerts` to the `Promise.allSettled([...])` list in the same position;
- add `data.alerts` to the `answered` list.

In `paint()`, import `renderAlert` from `./alerts.js` and add:

```javascript
  draw(document.getElementById("alert-banner"), renderAlert, ["alerts"], () => value("alerts"));
```

`app.css` (tokens only; no hex outside `:root`):

```css
/* The fountaining banner under the notice: a word and a time in the fountain's colour, never an alert level. */
.alert-banner { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--s1) var(--s3); padding: 7px var(--s5); background: var(--basalt-2); border-bottom: 1px solid var(--rule-strong); font-size: 13px; line-height: 1.45; color: var(--steam); }
.alert-banner[hidden] { display: none; }
.alert-tag { font: 600 11px/1 var(--font-cond); letter-spacing: 0.08em; text-transform: uppercase; color: var(--lava); }
.alert-tag[data-kind="end"] { color: var(--ash); }
.alert-banner a { color: var(--ash); }
```

and, in the `@media (max-width: 640px)` block next to `.notice`: `.alert-banner { padding: 6px var(--s4); }`.

- [ ] **Step 4: Run the tests, the suite and a screenshot**

Run: `.venv/Scripts/python.exe -m pytest`. Expected: all pass, the node tests included.

Then start `vigil-web` locally and take headless Edge screenshots at 1440 and 500 px (recreate `shot.sh` in the scratchpad: Edge `--headless=new` with its own `--user-data-dir`, launched through powershell.exe). Shoot the ep55 replay at 03:30 HST (banner "Fountaining seen"), at 09:20 HST ("Fountaining stopped") and at 03:00 HST (no banner). Before Task 15 has run, make the replay show alerts by running Task 15's ep55 replay first, or store two alerts in a scratch copy of the replay database.

- [ ] **Step 5: Commit**

```bash
git add vigil/web tests/test_web_views.py tests/test_web_app.py tests/test_web_static.py tests/js/lib.test.mjs
git commit -m "Show the fountaining alert as a banner under the notice, bounded by the clock, and its table in the replay"
```

---

### Task 15: The acceptance replays (orchestrator; ask the user before spending ~$1.10)

- [ ] **Step 1: Cost estimate to the user.** Overflows ~260 SAM looks plus a few Muse Spark calls, ~$0.70; episode 55's alerts pass ~140 looks plus 1–2 Muse Spark calls, ~$0.36. Each goes to its own replay database's ledger, under `alerts:<date>` with $0.75 per simulated day. **Wait for the OK.**
- [ ] **Step 2: Overflows.** `.venv/Scripts/vigil-replay.exe --quiet overflows`.
  - **Acceptance:** `data/replay/overflows/report.md` says **Alerts raised: 0**.
  - Record its looks line (sizes) and its cost.
  - If an alert fires, **stop**: inspect the alert's frame and looks, and bring it to the user. Never tune `config/alerts.yaml` to the result without saying so; the thresholds were set before this run.
- [ ] **Step 3: Episode 55.** `.venv/Scripts/vigil-replay.exe --episode 55`. Every pipeline tick is already done and the Muse Spark phases are cached, so only the alerts pass spends. Acceptance, from `report.md` "Fountaining alerts":
  - **onset:** "Seen" between 03:03 and 03:43 HST and "Alert" no later than 03:43; the plan's simulation gives 03:06–03:22;
  - **end:** "Seen" (last sighting) between 09:01 and 09:03 and "Alert" between 09:03 and 09:15;
  - no other alert in the window.
- [ ] **Step 4:** Look at both alert frames: `data/replay/ep55/alerts/*/frame*.jpg`. The onset must show the fountain tinted; the end must show no fountain.
- [ ] **Step 5: Write up.** Append a "Replays" section to `docs/research/alerts_calibration.md`: both tables, the looks lines, the costs and the frames' description. Commit: `git add docs/research/alerts_calibration.md && git commit -m "Record that the alerts stayed silent on the overflows and caught episode 55's start and end"`.
- [ ] **Step 6: Mirror and redeploy.**
  - Run `.venv/Scripts/vigil-mirror.exe push --episode 55 --repo facurie/volcano-vigil-ep55`. It now carries the alerts tables, the 30 warm-up frames and `replay/ep55/alerts/`.
  - Then `vigil-space deploy`.
  - Check the Space's replay at 03:30 HST: the banner shows.
- [ ] **Step 7: Telegram demo (optional, user's call).** `.venv/Scripts/vigil-alerts.exe --volcano kilauea --post-replay 55` posts the two replayed alerts with the "REPLAY … not a live alert" line, for the Phase 10 video. Ask before posting to the public channel.

---

### Task 16: Roadmap, docs and memory (orchestrator)

- [ ] **Step 1: PLAN.md Phase 8.**
  - Tick the boxes with what was built.
  - Rewrite the acceptance line to the decision: "the onset alert fires between the first frame that shows the fountain (03:03) and HVO's notice (03:43)", with the reason and a link to `alerts_calibration.md`.
  - Add the measured onset and end times.
  - Add the module map rows: `alerts.py`, `telegram.py` and `config/alerts.yaml`.
  - Update the budget line with the probes ($0.75), the replays and the live alerts spend.
  - Update the "Risks" row on overflows with the result.
  - Update the test count in "How to resume".
- [ ] **Step 2: Execution notes.** Append them at the end of this plan: deviations, review findings, numbers.
- [ ] **Step 3: Memory.** Update `volcano-vigil-status.md`: Phase 8 done, the channel, the secrets' names, V1 live, the costs, and the next step (Phase 9).
- [ ] **Step 4: Commit and push.** `git add docs/PLAN.md docs/superpowers/plans/2026-11-01-phase-8-alerts.md && git commit -m "Mark Phase 8 done: fountaining alerts live on the Space and on Telegram" && git push`.

---

## Acceptance (Phase 8)

1. `vigil-replay --quiet overflows` raises **no alert** over the 29 h of Oct 16–17 overflow frames.
2. On the episode 55 replay:
   - the **onset** alert's first sighting is between 03:03 and 03:43 HST, and the alert comes no later than 03:43 (HVO's notice);
   - the **end** alert's last sighting is 09:01–09:03, and the alert comes between 09:03 and 09:15 (HVO's end notice was at 09:11).
3. The dashboard shows the banner in replay only from the alert's clock on, and live when an alert exists. The disclaimer and the HVO link sit next to it.
4. The test message arrives on the public Telegram channel (`vigil-telegram test`), and the Space's log shows `Telegram: … may post: yes`.
5. Live on the Space before Nov 2 HST: `vigil-alerts` runs under the supervisor, V1 is ingested and gets local verdicts, the alerts spend ≤ $0.75/day, and the pipeline stops at $4.25.

## Risks and open points

| Risk | Mitigation |
|---|---|
| Thresholds set and tested on the same night and episode | Stated in the research note; Muse Spark confirms every onset; episode 56 is the first out-of-sample test |
| HVO re-aims V1 (another zoom) | Zoomed out: later alerts, never false ones; zoomed in: Muse Spark's confirmation. K2 covers the end |
| A blind camera plus one turned away end an episode early | Known limit (Task 7 note); the end alert names the cameras and the last sighting, so a reader can judge |
| The token leaks into logs | Requests are never logged (httpx at WARNING in both CLIs), errors are redacted, tests pin both |
| The alerts' budget runs out on a long eruption day | $0.75/day covers ~300 looks; the report says "alerts stopped" in the log; the pipeline's share is unaffected |
| AshCam drops the Oct 16–17 frames around Nov 16 | They are in the local database and `data/frames/`; run Task 15 before then |
| V1 catch-up lengthens the Space's start by ~5 min | Noted in DEPLOY.md; the watcher only looks at the last 10 min, so a catch-up never fires old alerts |

## Execution notes

### Execution notes (2026-11-01, session 12)

**Commits.**

| Task | Commits |
|---|---|
| Plan | 7b0f3f8 |
| 1 | 024067e |
| 2 | f1fd708 |
| 3 | efb8fae |
| 4 | 76ba520, and c86a345 for the review |
| 5 | 51fac8e |
| 6–7 | af184d8, 4bdc101, and 8ba2d13 for the review |
| 8 | 8947ef7, plus e4e758c |
| 9 | 7d733ff, and dd94617 for the review |
| 10 | 541384e, and 29942ef for the review |
| 11 | no code: the bot and the channel (the user), `vigil-telegram check` and `test`, the Space secret (the user) and variable |
| 12 | the deploy of 5fef62c, which already held Tasks 13–14 |
| 13 | 8716666, and 5fef62c for the review |
| 14 | 15aa2b8, and 7901493 and 5e81fa5 for the review |
| 15 | 0a21bc5 (the write-up); the mirror push |
| Relay | 8148e82 (the code), 7f2340b and the commit after it (the runbook); the Worker and the Space variable `TELEGRAM_API_URL` |

The suite went from 597 to 717 tests.

**Deviations from the plan.**
- **Two plan tests contradicted the plan's code** and were fixed: `(0.0329, "small")` is "ambiguous" with `ambiguous_area` 0.03 (it became `0.0299`, plus `(0.0329, "ambiguous")`), and the Telegram test message says "No es una alerta" with a capital N.
- **Review of Tasks 6–7** (the watcher; no logic bug, but):
  - most clock bounds were unpinned: deleting any of them left the tests green. Tests now insert looks and frames after the clock, as a resumed replay leaves them; the implementer killed 17 mutants, the reviewer 20;
  - **the plan's end text was false for a blind camera:** "No lava fountain on K2cam and V1cam since …" while K2 had last looked 30 min earlier and seen the fountain. The end alert now names only the cameras that missed it twice;
  - a quiet ambiguous look is stored before Muse Spark is asked, so a failed call never pays SAM twice;
  - `step()` works in UTC (the budget tag and the alert folder took the clock's own zone) and refuses a naive clock;
  - SAM and Muse Spark failures, `PAIR_WITHIN`, `SLACK` and the `_seen` cursor got tests.
- **Review of Task 9:** `send_pending` posts oldest first (pinned: after an outage an end must never come before its onset) and counts a refused caption or a bad stored body as an attempt instead of failing every step.
- **Review of Task 13:** the alerts replay is tested over a database that already holds every frame (the real case inside `run_replay`) and after an interrupted tick; `_minutes` rounds before printing, so it never prints `-0 min`.
- **Task 10 before Task 9** left `test_the_entry_point_runs_the_existing_clis_with_the_projects_arguments` red for one commit (541384e), until Task 9 added the `vigil-alerts` script.
- **`vigil-telegram check` crashed on the Windows console** printing "Kīlauea" (cp1252); it reconfigures stdout like the other CLIs (e4e758c).
- **Hugging Face blocks `api.telegram.org` from Spaces.** The first start logged `Telegram check failed … getMe: ConnectTimeout … handshake operation timed out`; forum threads from 2026 say the block is intended. The user chose a Cloudflare Worker relay on their free account: the code reads it from `TELEGRAM_API_URL` (8148e82), and the Worker's code, its limits and the steps are in `docs/DEPLOY.md`. The Worker is `https://vigil-telegram.facundorn3.workers.dev`. Its new `workers.dev` subdomain failed the TLS handshake for about 20 minutes until Cloudflare issued the certificate. Then it answered 404 to `GET /` and to another bot's `getMe`, and `vigil-telegram check` through it said `may post: yes`. The local test message had already arrived. After the redeploy of d3e7999, the Space's log said at 00:46:53Z on Nov 2: `vigil.alerts: Telegram: @volcano_vigil_bot posts to Volcano Vigil · Kīlauea (-1004340718752, channel): administrator, may post: yes`, so acceptance point 4 holds on the Space too.
- **The overflows were closer to the threshold than the probes said:** one V1 dome at 02:19 HST Oct 17 covered 0.054 of the frame (probes: ≤ 0.033), against the 0.06 threshold. Muse Spark called it `overflow_or_dome`. The thresholds were not changed.
- **The end alert came at 09:11**, the late edge of the simulated 09:07–09:11: V1 missed at 09:03 and 09:05, but K2's last look with a sighting (09:02, 0.0007 of the frame) held the end back until K2's misses at 09:08 and 09:10.

**Numbers.**
- Replays: overflows 0 alerts, 259 SAM looks, 1 Muse Spark call, $0.65; episode 55 onset seen 03:07 and raised 03:10, end last seen 09:02 and raised 09:11, 134 looks, 1 Muse Spark call, $0.34.
- The live Space's first alerts step (23:41Z) looked at K2's 23:32Z frame: no fountain. The V1 catch-up at the first start took about 10 minutes, as the plan expected.
- The mirror now holds 542 files (the alerts tables, 30 warm-up frames and the two alert frames).
- Task 15 Step 7: the two replayed episode 55 alerts were posted from this machine to the channel as messages 3 and 4, each headed "REPLAY of episode 55 (2026-10-17): not a live alert" (message 2 is the test message).
- Dashboard screenshots (1440 and 500 px) of the episode 55 replay: no banner at 03:05, "Fountaining seen 03:07" at 03:30, "Fountaining stopped 09:02" at 09:20; the banner's frame link serves the alert's image and `/media/frames/…` stays refused.
