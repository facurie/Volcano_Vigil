# Phase 7: Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Volcano Vigil runs on a public HTTPS URL: live ingest of KPcam, K2cam and F1cam, the live pipeline (quality gate, hourly SAM tracking, hourly bulletin) under a $3/day cap, and the episode 55 replay restored from a public Hugging Face dataset, so it no longer depends on AshCam's 31-day archive.

**Architecture:**
- **Server:** one Hugging Face Docker Space on the free `cpu-basic` hardware (2 vCPU, 16 GB), visibility "protected": the code is private and the app is public. The account `facurie` has PRO, which is what allows creating a Docker Space.
- **One container, several processes:** `deploy/start.sh` restores the state, starts the dashboard (`vigil-web`, port 7860), catches up on missed frames, and then supervises `vigil-ingest` and `vigil-pipeline` next to a state saver (`vigil-persist run`).
- **State survives restarts:** a Space's disk is lost whenever it restarts. `vigil/persist.py` saves the live database (one self-contained copy), the frames and the bulletins to a private Hugging Face bucket every 5 minutes and once more when the Space stops, and restores them at every start. The Meta API cost ledger is a table of that database, so the daily cap holds across restarts.
- **Episode mirror:** `vigil/mirror.py` stages the replay's frames, database, timeline, report and bulletins exactly as they sit under `data/` and pushes them to the public dataset `facurie/volcano-vigil-ep55`. The Space pulls them at every start.
- **Shipping code:** `vigil-space deploy` uploads `git archive HEAD` to the Space repository, with the Space's front matter on top of the README. The Hub builds the Dockerfile.

**Tech stack:** Python 3.12, `huggingface_hub` 2.4.0 (`HfApi.create_repo`, `upload_folder`, `snapshot_download`, `sync_bucket`, `batch_bucket_files`, `download_bucket_files`, `list_bucket_tree`), `python:3.12-slim` with ffmpeg, Hugging Face Docker Spaces and Storage Buckets.

---

## Decisions (with the user)

1. **Live spend on the Space: the full pipeline, capped at `DAILY_BUDGET_USD=3`** (2026-10-31). The user approved this with the estimate below. It covers the quality gate (Muse Spark only for hazy frames), one SAM window per camera per hour, and the hourly agent bulletin.
2. **A Hugging Face Docker Space, not Oracle** (2026-11-01). The Oracle Cloud signup needs a credit card the user does not have. HF Docker Spaces "require a paid plan to create: PRO for personal accounts" (https://huggingface.co/docs/hub/spaces-overview). The user subscribed to PRO ($9/month) on 2026-11-01; `HfApi().whoami()` now reports `isPro: True`. Fallback if the Space cannot work: the user's PC with Tailscale Funnel, running the same image and `deploy/start.sh`.
3. **The code stays private until submission** (CLAUDE.md). The Space's visibility is "protected": "the running app is publicly accessible through its embed URL … Source code on the Hub: Private" (https://huggingface.co/docs/hub/spaces-overview). Protected visibility is a PRO feature. Task 10 checks both halves anonymously.
4. **One container with a small supervisor, not a compose stack.** A Space is one container with one public port. The processes are still separate (they reuse the CLIs that already exist, so no new orchestration code; SAM mask decoding is pure Python and takes minutes, and it stays off the web server's GIL), and `start.sh` restarts a service that exits.
5. **The state is saved to a private bucket by API calls, not by mounting it.** "The data written on disk is lost whenever your Docker Space restarts" (https://huggingface.co/docs/hub/spaces-sdks-docker). Storage Buckets can be mounted as volumes (https://huggingface.co/docs/hub/spaces-storage), but the docs do not say whether SQLite's WAL mode and renames work on a mount, and the cost ledger lives in the database. Saving through `sync_bucket` needs only whole-file transfers.
6. **Free hardware, and the user visits the URL every 24 h.** "If your Space runs on the default `cpu-basic` hardware, it will go to sleep if inactive for more than a set time (currently, 48 hours). Anyone visiting your Space will restart it automatically." (https://huggingface.co/docs/hub/spaces-gpus). The user opens the URL at least once a day, so it never sleeps. If a visit is missed, the Space restarts on the next one, restores its state and catches up on the last 24 h. `CPU Upgrade` ($0.03/hour, about $0.72/day) never sleeps; use it only with the user's OK.

## Facts this plan relies on (measured while planning, 2026-10-31 and 2026-11-01)

- **AshCam over the last 24 h** (index calls of about 1 s each):
  - K2 has 719 frames, KP 286 and F1 95; 48 h doubles these.
  - K2 frames are ~0.54 MB and take ~0.72 s each; KP frames are ~0.24 MB and take ~0.66 s.
  - A 24 h catch-up of K2 and KP is ~1,005 frames, ~460 MB and ~12 min in sequence (K2 ~8.6 min, KP ~3.1 min).
  - F1 polls `M.jpg` (`live_source: url`), so it has no catch-up.
- **Episode 55 replay to mirror:**
  - 468 frames from `data/replay/ep55/vigil.sqlite`: K2 195 (141.6 MB), KP 78 (48.3 MB), V1 195 (60.2 MB), so ~250 MB. Their `path` is relative to the data dir (`frames/kilauea-kp/2026-10-17/20261017T130006Z_ea8dc9ff.jpg`).
  - The replay folder adds `bulletins/run1..run7` (2.6 MB, evidence images and HTML/Markdown), `timeline.json` (84 KB), `report.md` and `spark_phases.json`.
  - The database is 3.9 MB in WAL mode. Any reader leaves `-wal`/`-shm` files beside it, so the mirror copies it with SQLite's backup into one rollback-journal file.
  - A scan of every text column found no local paths, e-mail addresses or keys.
  - The dashboard needs exactly these:
    - `views.frame_image` reads `data_dir / frames.path`;
    - `/media/` serves `replay/ep55/bulletins/...`;
    - `views.replay_state` reads `timeline.json`;
    - `/api/config` lists the replay once `replay/ep55/vigil.sqlite` exists.
- **What the live pipeline writes under the data dir:** `vigil.sqlite` (and its `-wal`/`-shm`), `frames/<camera>/<date>/` and `bulletins/run<N>/` (`vigil/pipeline.py:280`, `vigil/agent/bulletin.py:351`). Tracking writes its MP4s under `tempfile.TemporaryDirectory()` (`vigil/tracking.py:181`), and the lead-in reaches back 24 h. Those three are the state `persist.py` saves; `replay/` comes from the dataset.
- **Hugging Face:**
  - `huggingface_hub` 2.4.0 is installed in `.venv`, with the `hf` CLI. The user is logged in as `facurie`, and `isPro` is `True`.
  - Bucket API (signatures read from the installed package): `sync_bucket(source, dest, *, delete=False, …)` with `hf://buckets/<owner>/<name>/<path>` on either side; `batch_bucket_files(bucket_id, *, add=[(local, remote)], delete=[…])`; `download_bucket_files(bucket_id, files=[(remote, local)], raise_on_missing_files=False)`; `list_bucket_tree(bucket_id, prefix=None, *, recursive=None)`, which at the root returns `BucketFile`/`BucketFolder` objects with a `path`; `create_bucket(bucket_id, *, private=…, exist_ok=…)`.
  - `create_repo(…, repo_type="space", space_sdk="docker", visibility="protected")` is accepted: `visibility` takes `public`, `private` or `protected`.
  - A Docker Space needs `sdk: docker` and optionally `app_port` (default 7860) in its README front matter; the container runs as user 1000; secrets and variables reach it as environment variables at runtime; outbound requests are limited to ports 80, 443 and 8080 (https://huggingface.co/docs/hub/spaces-sdks-docker, https://huggingface.co/docs/hub/spaces-overview).
  - The hub's SSE endpoints `GET /api/spaces/{owner}/{name}/logs/{build|run}?tail=N` give the build and run logs, and `HfApi.get_space_runtime(repo).stage` gives `BUILDING`, `RUNNING`, `RUNTIME_ERROR` and so on.
  - `snapshot_download(local_dir=...)` keeps metadata in `<local_dir>/.cache/huggingface/` and skips files already up to date. It downloads to `*.incomplete` and then moves the file into place (huggingface_hub 2.4.0 `file_download.py`).
  - `upload_folder` honours a root `.gitignore` and splits big folders into several commits with hf_xet.
  - Reading a public dataset needs no token. That is inferred from the docs, and Task 8 checks it with an empty `HF_HOME`.
- **Pinned versions** (`pip freeze` of `.venv`, where all 556 tests pass): `openai==3.39.0` (pyproject only says `>=1.60`), `fastapi==0.162.0`, `starlette==1.10.0`, `uvicorn==0.54.0`, `numpy==2.5.4`, `pillow==13.0.0`, `pydantic==2.14.1`, `huggingface_hub==2.4.0`, … The image installs with these as pip constraints, so the Space does not pick up newer majors.
- **The pipeline in a container:** config is read from `config/` relative to the working directory, and static files are package data. Without `MODEL_API_KEY`, `MetaClient.from_env` raises `MissingApiKey`, so `vigil-pipeline` exits at once and the supervisor retries every 10 s until the secret is set.
- **Live cost estimate** (approved):
  - SAM: K2 3 phrases + KP 3 + F1 1 = $0.07 per usable hour, so ~$1/day.
  - Agent: ~$0.03–0.08 per run × 24, so ~$1.2/day.
  - Gate: up to ~$0.3 on a foggy afternoon.
  - Total ~$2–3/day, capped at $3. The first start adds ≤ $0.25 for the last 3 closed hours.
  - Mirror push, bucket and Space: $0 beyond the PRO subscription already paid.

## File map

| File | Action | Responsibility |
|---|---|---|
| `vigil/ingest/worker.py` | modify | `build_router(..., lookback=)`; `vigil-ingest --lookback-hours` |
| `vigil/ingest/ashcam.py` | modify | docstring of `AshcamIngestor` (a longer lookback catches up on downtime) |
| `tests/test_worker.py` | modify | lookback through the router and the CLI |
| `vigil/mirror.py` | create | `snapshot_database`, `episode_files`, `stage`, `dataset_card`, `push`, `pull`, `vigil-mirror` CLI |
| `tests/test_mirror.py` | create | staging, card, push and pull with fakes (no network) |
| `pyproject.toml` | modify | `huggingface_hub>=2.4` dependency; `vigil-mirror`, `vigil-persist` and `vigil-space` scripts |
| `vigil/persist.py` | create | `backup`, `restore`, `run`, `vigil-persist` CLI: the live state in a private bucket |
| `tests/test_persist.py` | create | the state round trip with an in-memory bucket |
| `vigil/space.py` | create | `space_readme`, `stage`, `deploy`, `vigil-space` CLI |
| `tests/test_space.py` | create | the Space card, staging and upload with fakes |
| `deploy/constraints.txt` | create | exact runtime versions for the image |
| `Dockerfile` | create | the image the Space builds |
| `.dockerignore` | create | keep `.env` and `data/` out of a build context |
| `deploy/start.sh` | create | the container's entry point: restore, dashboard, catch-up, supervised services |
| `tests/test_deploy.py` | create | invariants of the image and the entry point (budget, secrets, port, order, pins) |
| `docs/DEPLOY.md` | create | the runbook |
| `docs/PLAN.md`, `README.md`, `DATA_SOURCES.md` | modify | Task 11 |

Tasks 1–7 are code and docs (implementer + reviewer). Tasks 8–11 touch real systems and need the user (orchestrator).

---

### Task 1: Ingest catch-up window (`--lookback-hours`)

**Files:**
- Modify: `vigil/ingest/worker.py` (`build_router`, `main`, module docstring)
- Modify: `vigil/ingest/ashcam.py:142-147` (`AshcamIngestor` docstring)
- Test: `tests/test_worker.py`

Today `AshcamIngestor` reaches back at most 1 h (`lookback=timedelta(hours=1)`). On the Space, a restart after a longer outage must catch up by itself, and the very first start must fill the dashboard's 24 h strips. `build_router` gets a `lookback` parameter, and `vigil-ingest` a `--lookback-hours` flag (default 1, so local behaviour does not change).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_worker.py`. Also extend the imports at the top: `import pytest`, `from vigil.timeutil import utcnow`, and `main` from `vigil.ingest.worker`.

```python
def test_the_router_reaches_back_as_far_as_its_lookback_for_ashcam_cameras(conn, tmp_path):
    archive = FakeAshcam()
    camera = kp_camera().model_copy(update={"live_source": "ashcam"})
    router = build_router(FrameStore(conn, tmp_path), httpx.Client(transport=httpx.MockTransport(archive)),
                          lookback=timedelta(hours=24))

    before = utcnow()
    router.ingest(camera)
    after = utcnow()

    start = int(archive.list_requests()[0].url.params["startTimestamp"])
    assert int((before - timedelta(hours=24)).timestamp()) <= start <= int((after - timedelta(hours=24)).timestamp())


def test_the_router_reaches_back_one_hour_by_default(conn, tmp_path):
    archive = FakeAshcam()
    camera = kp_camera().model_copy(update={"live_source": "ashcam"})
    router = build_router(FrameStore(conn, tmp_path), httpx.Client(transport=httpx.MockTransport(archive)))

    before = utcnow()
    router.ingest(camera)
    after = utcnow()

    start = int(archive.list_requests()[0].url.params["startTimestamp"])
    assert int((before - timedelta(hours=1)).timestamp()) <= start <= int((after - timedelta(hours=1)).timestamp())


CLI_SOURCES = """
volcanoes:
  kilauea:
    name: Kīlauea
    country: United States
    official_agency: USGS Hawaiian Volcano Observatory
    official_url: https://www.usgs.gov/volcanoes/kilauea
cameras:
  - id: kilauea-kp
    name: KPcam
    volcano: kilauea
    url: https://example.org/KPcam/images/M.jpg
    license: Public Domain
    attribution: U.S. Geological Survey
    ashcam_code: kilauea-kp-cam
    live_source: ashcam
    enabled: true
"""


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(CLI_SOURCES, encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigil.sqlite"))


def test_cli_passes_its_lookback_to_the_router(cli_env, monkeypatch):
    seen = {}

    def fake_router(store, http, lookback):
        seen["lookback"] = lookback
        return RecordingIngestor()

    monkeypatch.setattr("vigil.ingest.worker.build_router", fake_router)

    main(["--once", "--lookback-hours", "24"])

    assert seen["lookback"] == timedelta(hours=24)


def test_cli_refuses_a_lookback_that_is_not_positive(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--once", "--lookback-hours", "0"])

    assert "--lookback-hours" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_worker.py -k "lookback"`
Expected: the router tests FAIL with `TypeError: build_router() got an unexpected keyword argument 'lookback'`, and the CLI tests FAIL on the unknown `--lookback-hours` argument (SystemExit in the first one, and no `--lookback-hours` in the error text of the second).

- [ ] **Step 3: Implement**

In `vigil/ingest/worker.py`:

```python
LOOKBACK = timedelta(hours=1)  # how far back an AshCam camera's poll fetches the frames it lacks, by default


def build_router(store: FrameStore, http: httpx.Client, lookback: timedelta = LOOKBACK) -> SourceRouter:
    """The live ingestor of each source; AshCam cameras fall back to their image URL. An AshCam camera's poll
    fetches every archived frame it lacks from at most `lookback` ago, so a restart catches up on that much
    downtime."""
    by_url = Ingestor(store, http)
    ashcam = AshcamIngestor(AshcamClient(http), store, lookback=lookback)
    return SourceRouter({"url": by_url, "ashcam": Fallback(ashcam, by_url)})
```

In `main`, add the flag after `--once`, check it after `parse_args`, and pass it:

```python
    parser.add_argument("--lookback-hours", type=float, default=LOOKBACK / timedelta(hours=1),
                        help="how far back an AshCam camera's poll fetches the frames it lacks, so a restart "
                             "catches up on that much downtime (default 1)")
    args = parser.parse_args(argv)
    if args.lookback_hours <= 0:
        parser.error("--lookback-hours must be positive")
```

```python
        router = build_router(FrameStore(conn, settings.data_dir), http, lookback=timedelta(hours=args.lookback_hours))
        worker = Worker(router, sources.cameras)
```

Add one sentence to the module docstring, after the `--once` sentence: "`--lookback-hours N` lets each AshCam camera's poll fetch the frames it lacks from up to N hours ago (default 1), so a server catches up on its downtime when it starts."

In `vigil/ingest/ashcam.py`, change the `AshcamIngestor` docstring's last sentence to: "A poll reaches back at most `lookback`: the first poll stores that window, and a longer gap (after downtime) needs a longer lookback (`vigil-ingest --lookback-hours`) or `vigil-backfill`."

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_worker.py tests/test_ashcam.py`
Expected: all pass.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv/Scripts/python.exe -m pytest`. Expected: green, 560 tests (556 + 4).

```bash
git add vigil/ingest/worker.py vigil/ingest/ashcam.py tests/test_worker.py
git commit -m "Let vigil-ingest reach back further than an hour so a server catches up after downtime"
```

---

### Task 2: Episode mirror: staging and dataset card

**Files:**
- Create: `vigil/mirror.py` (this task: `snapshot_database`, `episode_files`, `stage`, `dataset_card`)
- Test: `tests/test_mirror.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mirror.py`:

```python
import sqlite3
from contextlib import closing
from datetime import timedelta

import pytest

from conftest import make_jpeg
from vigil import db
from vigil.config import Volcano
from vigil.episodes import EPISODES
from vigil.ingest.store import FrameStore
from vigil.mirror import dataset_card, episode_files, stage
from vigil.replay import replay_dir
from vigil.timeutil import parse_utc

EP = EPISODES["55"]
KILAUEA = Volcano(name="Kīlauea", country="United States (Hawaiʻi)",
                  official_agency="USGS Hawaiian Volcano Observatory (HVO)",
                  official_url="https://www.usgs.gov/volcanoes/kilauea", lat=19.405, lon=-155.290,
                  utc_offset_hours=-10)
T0 = parse_utc("2026-10-17T14:55:05Z")


@pytest.fixture
def data(tmp_path):
    """A data dir with a small episode 55 replay: two frames in the replay's database, one frame only the live
    database has, the replay's timeline and one bulletin image."""
    data = tmp_path / "data"
    with closing(db.connect(replay_dir(data, EP) / "vigil.sqlite")) as conn:
        store = FrameStore(conn, data)
        store.add("kilauea-kp", make_jpeg((200, 80, 40)), captured_at=T0, timestamp_source="ashcam", fetched_at=T0)
        store.add("kilauea-k2", make_jpeg((40, 200, 80)), captured_at=T0 + timedelta(minutes=1),
                  timestamp_source="ashcam", fetched_at=T0)
    with closing(db.connect(data / "vigil.sqlite")) as live:
        later = parse_utc("2026-10-31T20:00:00Z")
        FrameStore(live, data).add("kilauea-kp", make_jpeg((80, 40, 200)), captured_at=later,
                                   timestamp_source="ashcam", fetched_at=later)
    folder = replay_dir(data, EP)
    (folder / "timeline.json").write_text("{}", encoding="utf-8")
    (folder / "bulletins" / "run1").mkdir(parents=True)
    (folder / "bulletins" / "run1" / "frame1_plume.jpg").write_bytes(make_jpeg())
    return data


def replay_frames(data):
    with closing(sqlite3.connect(replay_dir(data, EP) / "vigil.sqlite")) as conn:
        return [row[0] for row in conn.execute("SELECT path FROM frames ORDER BY captured_at")]


def test_episode_files_are_the_replays_frames_then_the_rest_of_its_folder(data):
    files = episode_files(data, EP)

    assert files == [*replay_frames(data), "replay/ep55/bulletins/run1/frame1_plume.jpg", "replay/ep55/timeline.json"]


def test_episode_files_leave_out_the_database_and_its_journal(data):
    (replay_dir(data, EP) / "vigil.sqlite-wal").write_bytes(b"")

    assert not [path for path in episode_files(data, EP) if "vigil.sqlite" in path]


def test_a_missing_frame_stops_the_mirror(data):
    (data / replay_frames(data)[0]).unlink()

    with pytest.raises(FileNotFoundError, match="missing"):
        episode_files(data, EP)


def test_an_episode_never_replayed_cannot_be_mirrored(tmp_path):
    with pytest.raises(FileNotFoundError, match="vigil-replay"):
        episode_files(tmp_path, EP)


def test_stage_lays_the_files_out_as_in_the_data_dir(data, tmp_path):
    out = tmp_path / "out"

    staged = stage(data, EP, KILAUEA, out)

    assert staged == [*episode_files(data, EP), "replay/ep55/vigil.sqlite", "README.md"]
    for path in episode_files(data, EP):
        assert (out / path).read_bytes() == (data / path).read_bytes()


def test_the_staged_database_is_one_self_contained_file(data, tmp_path):
    out = tmp_path / "out"

    stage(data, EP, KILAUEA, out)

    copy = out / "replay" / "ep55" / "vigil.sqlite"
    assert sorted(path.name for path in copy.parent.iterdir() if path.name.startswith("vigil.sqlite")) == [
        "vigil.sqlite"]
    with closing(sqlite3.connect(copy)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == 2


def test_the_dataset_card_credits_the_sources_and_carries_the_disclaimer():
    card = dataset_card(EP, KILAUEA, frame_count=468)

    assert card.startswith("---\nlicense: cc-by-4.0\n")
    assert "468 frames" in card
    assert "U.S. Geological Survey" in card and "public domain" in card.lower()
    assert "Open-Meteo" in card and "CC BY 4.0" in card
    assert "does not replace official alerts" in card
    assert "https://www.usgs.gov/volcanoes/kilauea" in card
    assert "2026-10-17T13:00:00Z" in card and "2026-10-17T19:30:00Z" in card
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mirror.py`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'vigil.mirror'`.

- [ ] **Step 3: Implement**

Create `vigil/mirror.py`:

```python
"""Mirror an episode's replay to a public Hugging Face dataset, and restore it from there.

The replay shows frames from the USGS AshCam archive, which keeps them for about 31 days, plus the replay's own
outputs: its database, timeline, report and bulletins. `push` uploads exactly those, laid out as they sit in the
data dir, together with a dataset card. `pull` puts them back where the dashboard looks for them. A server pulls
at every start, and files already up to date are not downloaded again.

    vigil-mirror push --episode 55 --repo facurie/volcano-vigil-ep55
    vigil-mirror pull --episode 55 --repo facurie/volcano-vigil-ep55
"""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from vigil import db
from vigil.agent.bulletin import DISCLAIMER_EN
from vigil.config import Volcano
from vigil.episodes import Episode
from vigil.replay import replay_dir
from vigil.timeutil import to_iso

DB_NAME = "vigil.sqlite"


def episode_files(data_dir: Path, episode: Episode) -> list[str]:
    """Everything the episode's replay needs besides its database, as POSIX paths relative to the data dir: first
    the frames its database lists, then the rest of its replay folder (timeline, report, bulletins). Raises
    FileNotFoundError if the replay's database or one of its frames is missing."""
    folder = replay_dir(data_dir, episode)
    database = folder / DB_NAME
    if not database.is_file():
        raise FileNotFoundError(f"{database} does not exist: run vigil-replay --episode {episode.key} first")
    with closing(db.connect_readonly(database)) as conn:
        frames = [row[0] for row in conn.execute("SELECT path FROM frames ORDER BY captured_at, id")]
    missing = [path for path in frames if not (data_dir / path).is_file()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} frame(s) of episode {episode.key} are missing, e.g. {missing[0]}")
    rest = sorted(path.relative_to(data_dir).as_posix() for path in folder.rglob("*")
                  if path.is_file() and not path.name.startswith(DB_NAME))
    return frames + rest


def snapshot_database(source: Path, target: Path) -> None:
    """Copy a SQLite database into `target` as one self-contained file. SQLite's backup folds in a writer's journal,
    so this is safe while other processes write to `source`, and the copy is switched to a rollback journal, so no
    `-wal` or `-shm` file travels with it. `vigil/persist.py` uses it too."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(db.connect_readonly(source)) as original, closing(sqlite3.connect(target)) as copy:
        original.backup(copy)
        copy.execute("PRAGMA journal_mode=DELETE")


def stage(data_dir: Path, episode: Episode, volcano: Volcano, out: Path) -> list[str]:
    """Lay out in `out` what `push` uploads: the episode's files, a copy of its replay database and the dataset
    card. The copy is made with SQLite's backup, so a writer's journal is folded in, and is switched to a rollback
    journal, so it is one self-contained file. Returns the staged paths."""
    files = episode_files(data_dir, episode)
    for path in files:
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(data_dir / path, target)
    database = (replay_dir(Path(), episode) / DB_NAME).as_posix()
    snapshot_database(data_dir / database, out / database)
    frame_count = sum(path.startswith("frames/") for path in files)
    (out / "README.md").write_text(dataset_card(episode, volcano, frame_count), encoding="utf-8")
    return files + [database, "README.md"]


def dataset_card(episode: Episode, volcano: Volcano, frame_count: int) -> str:
    """The dataset's README: what it holds, where it comes from, its licenses and the disclaimer."""
    words = {"name": volcano.name, "agency": volcano.official_agency, "url": volcano.official_url}
    key = episode.key
    return f"""---
license: cc-by-4.0
pretty_name: Volcano Vigil, {volcano.name} episode {key} replay
tags:
- volcano
- webcam
- segmentation
size_categories:
- n<1K
---

# Volcano Vigil: {volcano.name} episode {key}

The webcam frames and the replay that the Volcano Vigil dashboard shows for {volcano.name}'s episode {key}, from
{to_iso(episode.start)} to {to_iso(episode.end)} (UTC). The dashboard's server downloads this dataset when it
starts, because the USGS AshCam archive keeps frames for only about 31 days.

> {DISCLAIMER_EN.format(**words)}

## Contents

- `frames/<camera>/<date>/*.jpg`: {frame_count} frames from {", ".join(episode.cameras)}, from the USGS AshCam
  archive. Their exact capture times are in the database.
- `replay/ep{key}/vigil.sqlite`: the replay's SQLite database. It holds the frames, the quality verdicts, the SAM 3.1
  tracks and masks (COCO RLE), the measurements with their σ, the winds, the Muse Spark agent's runs and steps, and
  the bulletins.
- `replay/ep{key}/timeline.json`, `report.md`, `spark_phases.json`: the replay's timeline and its comparison with
  the official values.
- `replay/ep{key}/bulletins/run<N>/`: each bulletin in English and Spanish (Markdown and HTML) with its evidence
  images.

## Sources and licenses

- Frames: U.S. Geological Survey, Hawaiian Volcano Observatory webcams. Public domain; credit "U.S. Geological
  Survey".
- Winds in the database: Open-Meteo (https://open-meteo.com), CC BY 4.0.
- Everything else (masks, measurements, bulletins, timeline): Volcano Vigil, CC BY 4.0.
"""
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mirror.py`
Expected: 7 pass.

- [ ] **Step 5: Commit**

Run the full suite first (`.venv/Scripts/python.exe -m pytest`, green).

```bash
git add vigil/mirror.py tests/test_mirror.py
git commit -m "Stage an episode's replay with its frames and a dataset card so it can outlive AshCam's archive"
```

---

### Task 3: Episode mirror: push, pull and the `vigil-mirror` CLI

**Files:**
- Modify: `vigil/mirror.py` (add `push`, `pull`, `main`)
- Modify: `pyproject.toml` (dependency and script)
- Test: `tests/test_mirror.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mirror.py`. Extend the imports: `import logging`, `import shutil`, and `from vigil.mirror import main, pull, push` (merged into the existing `vigil.mirror` import).

```python
REPO = "facurie/volcano-vigil-ep55"


class FakeApi:
    """Records what `push` asks of the Hub, and the files the folder held when it was uploaded."""

    def __init__(self):
        self.created, self.uploads = [], []

    def create_repo(self, repo_id, **kwargs):
        self.created.append((repo_id, kwargs))

    def upload_folder(self, **kwargs):
        folder = kwargs["folder_path"]
        files = sorted(path.relative_to(folder).as_posix() for path in Path(folder).rglob("*") if path.is_file())
        self.uploads.append({**kwargs, "files": files})


def test_push_creates_the_public_dataset_and_uploads_the_staged_episode(data):
    api = FakeApi()

    count = push(api, data, EP, KILAUEA, REPO)

    assert api.created == [(REPO, {"repo_type": "dataset", "private": False, "exist_ok": True})]
    [upload] = api.uploads
    assert upload["repo_id"] == REPO and upload["repo_type"] == "dataset"
    assert upload["delete_patterns"] == ["frames/**", "replay/ep55/**"]
    assert upload["files"] == sorted([*episode_files(data, EP), "replay/ep55/vigil.sqlite", "README.md"])
    assert count == len(upload["files"])


def copying_download(source):
    """A stand-in for snapshot_download that copies a staged mirror into local_dir."""
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        shutil.copytree(source, kwargs["local_dir"], dirs_exist_ok=True)
        return str(kwargs["local_dir"])

    return download, calls


def test_pull_restores_the_mirror_where_the_dashboard_looks(data, tmp_path):
    staged = tmp_path / "staged"
    stage(data, EP, KILAUEA, staged)
    download, calls = copying_download(staged)
    fresh = tmp_path / "fresh"

    database = pull(fresh, EP, REPO, download=download)

    assert database == replay_dir(fresh, EP) / "vigil.sqlite"
    assert calls == [{"repo_id": REPO, "repo_type": "dataset", "local_dir": fresh,
                      "allow_patterns": ["frames/**", "replay/ep55/**"]}]
    for path in episode_files(fresh, EP):
        assert (fresh / path).read_bytes() == (data / path).read_bytes()


def test_pull_keeps_the_copy_it_has_when_the_hub_cannot_be_reached(data, caplog):
    def unreachable(**kwargs):
        raise OSError("network is unreachable")

    with caplog.at_level(logging.WARNING):
        database = pull(data, EP, REPO, download=unreachable)

    assert database == replay_dir(data, EP) / "vigil.sqlite"
    assert "network is unreachable" in caplog.text


def test_pull_fails_without_a_copy_when_the_hub_cannot_be_reached(tmp_path):
    def unreachable(**kwargs):
        raise OSError("network is unreachable")

    with pytest.raises(OSError):
        pull(tmp_path, EP, REPO, download=unreachable)


def test_pull_fails_when_the_dataset_lacks_the_episode(tmp_path):
    with pytest.raises(FileNotFoundError, match="replay/ep55/vigil.sqlite"):
        pull(tmp_path, EP, REPO, download=lambda **kwargs: str(kwargs["local_dir"]))


def test_cli_refuses_an_unknown_episode(capsys):
    with pytest.raises(SystemExit):
        main(["push", "--episode", "99", "--repo", REPO])

    assert "no episode '99'" in capsys.readouterr().err
```

Also add `from pathlib import Path` to the imports (used by `FakeApi`).

- [ ] **Step 2: Run the tests to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mirror.py`
Expected: FAIL at collection with `ImportError: cannot import name 'main' from 'vigil.mirror'`.

- [ ] **Step 3: Implement**

Add the imports to `vigil/mirror.py`: `argparse`, `logging`, `tempfile`, `from collections.abc import Callable`, `from typing import Any`, `from huggingface_hub import HfApi, snapshot_download`, `from vigil.config import Volcano, load_sources`, `from vigil.episodes import EPISODES, Episode` and `from vigil.settings import Settings`. Add `log = logging.getLogger(__name__)` under the imports. Then append:

```python
def _patterns(episode: Episode) -> list[str]:
    """The dataset paths that belong to the episode's mirror."""
    return ["frames/**", f"replay/ep{episode.key}/**"]


def push(api: HfApi, data_dir: Path, episode: Episode, volcano: Volcano, repo_id: str) -> int:
    """Upload the episode's mirror to the public dataset `repo_id`, creating the dataset if needed. Mirrored files
    that the episode no longer has are deleted from the dataset. Returns how many files were uploaded."""
    with tempfile.TemporaryDirectory() as tmp:
        staged = stage(data_dir, episode, volcano, Path(tmp))
        api.create_repo(repo_id, repo_type="dataset", private=False, exist_ok=True)
        api.upload_folder(repo_id=repo_id, repo_type="dataset", folder_path=tmp,
                          commit_message=f"Mirror episode {episode.key}: {len(staged)} files",
                          delete_patterns=_patterns(episode))
    return len(staged)


def pull(data_dir: Path, episode: Episode, repo_id: str, *,
         download: Callable[..., Any] = snapshot_download) -> Path:
    """Restore the episode's mirror from the dataset `repo_id` into the data dir; returns the replay's database.
    Files already up to date are not downloaded again. If the Hub cannot be reached but an earlier pull left the
    database, the failure is logged and that copy is kept; without a copy it is raised."""
    database = replay_dir(data_dir, episode) / DB_NAME
    try:
        download(repo_id=repo_id, repo_type="dataset", local_dir=data_dir, allow_patterns=_patterns(episode))
    except Exception as exc:  # any Hub or network failure: the copy on disk, if there is one, still serves
        if not database.is_file():
            raise
        log.warning("episode %s: could not refresh the mirror from %s (%s); keeping the copy in %s",
                    episode.key, repo_id, exc, data_dir)
    if not database.is_file():
        raise FileNotFoundError(f"{repo_id} has no {database.relative_to(data_dir).as_posix()}")
    return database


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Mirror an episode's replay to a public Hugging Face dataset "
                                                 "(push), or restore it into the data dir (pull).")
    parser.add_argument("action", choices=["push", "pull"])
    parser.add_argument("--episode", required=True, help="episode key, e.g. 55")
    parser.add_argument("--repo", required=True, help="dataset id, e.g. facurie/volcano-vigil-ep55")
    args = parser.parse_args(argv)
    episode = EPISODES.get(args.episode)
    if episode is None:
        parser.error(f"no episode {args.episode!r}; known: {', '.join(EPISODES)}")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    if args.action == "push":
        volcano = load_sources(settings.sources_path).volcanoes[episode.volcano]
        count = push(HfApi(), settings.data_dir, episode, volcano, args.repo)
        print(f"episode {episode.key}: {count} files pushed to https://huggingface.co/datasets/{args.repo}")
    else:
        print(f"episode {episode.key} restored: {pull(settings.data_dir, episode, args.repo)}")


if __name__ == "__main__":
    main()
```

In `pyproject.toml`:
- add `"huggingface_hub>=2.4",` to `dependencies`, after `"uvicorn>=0.30",`;
- add `vigil-mirror = "vigil.mirror:main"` to `[project.scripts]`, after `vigil-web`.

Then reinstall so the script exists: `.venv/Scripts/python.exe -m pip install -e ".[dev]"`.

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mirror.py`
Expected: 13 pass.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv/Scripts/python.exe -m pytest`. Expected: green, 573 tests (560 + 13).

```bash
git add vigil/mirror.py tests/test_mirror.py pyproject.toml
git commit -m "Push an episode's replay to a Hugging Face dataset and pull it back at startup"
```

---


### Task 4: Keep the live state across restarts (`vigil-persist`)

**Files:**
- Create: `vigil/persist.py`
- Modify: `pyproject.toml` (script)
- Test: `tests/test_persist.py`

A Space's disk is empty at every start. `backup` saves the frames and bulletins first and the database last, so a saved row never points at a file the bucket lacks. `restore` is the reverse, and it fails loudly when the bucket cannot be read: running on an empty database would let the next save overwrite the bucket's good copy and forget the day's Meta API spend. `snapshot_database` comes from `vigil/mirror.py` (Task 2).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_persist.py`:

```python
import logging
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from vigil import db
from vigil.persist import backup, main, restore, run

BUCKET = "facurie/vigil-state"
ROOT = f"hf://buckets/{BUCKET}/"


class FakeBucket:
    """The Hub's bucket API in memory: a bucket is a dict of path -> bytes, and `calls` lists the methods called."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.calls: list[str] = []
        self.fail: Exception | None = None

    def _enter(self, name):
        self.calls.append(name)
        if self.fail:
            raise self.fail

    def sync_bucket(self, source, dest):
        self._enter("sync_bucket")
        if source.startswith(ROOT):  # bucket -> local
            prefix = source.removeprefix(ROOT) + "/"
            for key, content in self.files.items():
                if key.startswith(prefix):
                    target = Path(dest) / key.removeprefix(prefix)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
        else:  # local -> bucket
            prefix = dest.removeprefix(ROOT)
            for path in Path(source).rglob("*"):
                if path.is_file():
                    self.files[f"{prefix}/{path.relative_to(source).as_posix()}"] = path.read_bytes()

    def batch_bucket_files(self, bucket_id, *, add):
        self._enter("batch_bucket_files")
        for source, key in add:
            self.files[key] = Path(source).read_bytes()

    def download_bucket_files(self, bucket_id, files):
        self._enter("download_bucket_files")
        for key, target in files:
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            Path(target).write_bytes(self.files[key])

    def list_bucket_tree(self, bucket_id):
        self._enter("list_bucket_tree")
        return [SimpleNamespace(path=name) for name in sorted({key.split("/")[0] for key in self.files})]


@pytest.fixture
def data(tmp_path):
    """A data dir as the live services leave it: a frame, a bulletin image, a file of the replay and a database
    that has spent $0.42."""
    data = tmp_path / "data"
    (data / "frames" / "kilauea-kp" / "2026-11-01").mkdir(parents=True)
    (data / "frames" / "kilauea-kp" / "2026-11-01" / "a.jpg").write_bytes(b"frame")
    (data / "bulletins" / "run1").mkdir(parents=True)
    (data / "bulletins" / "run1" / "bulletin.html").write_bytes(b"<p>bulletin</p>")
    (data / "replay" / "ep55").mkdir(parents=True)
    (data / "replay" / "ep55" / "timeline.json").write_bytes(b"{}")
    with closing(db.connect(data / "vigil.sqlite")) as conn:
        conn.execute("INSERT INTO api_calls (called_at, model, purpose, cost_usd, ok) "
                     "VALUES ('2026-11-01T20:00:00Z', 'sam-3.1', 'segment', 0.42, 1)")
        conn.commit()
    return data


def spent(database):
    with closing(sqlite3.connect(database)) as conn:
        return conn.execute("SELECT SUM(cost_usd) FROM api_calls").fetchone()[0]


def test_backup_saves_the_frames_the_bulletins_and_the_database_but_not_the_replay(data):
    bucket = FakeBucket()

    backup(bucket, data, data / "vigil.sqlite", BUCKET)

    assert sorted(bucket.files) == ["bulletins/run1/bulletin.html", "db/vigil.sqlite",
                                    "frames/kilauea-kp/2026-11-01/a.jpg"]


def test_the_saved_database_is_one_self_contained_copy_with_the_ledger(data, tmp_path):
    bucket = FakeBucket()

    backup(bucket, data, data / "vigil.sqlite", BUCKET)

    saved = tmp_path / "saved.sqlite"
    saved.write_bytes(bucket.files["db/vigil.sqlite"])
    with closing(sqlite3.connect(saved)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert spent(saved) == 0.42


def test_backup_saves_the_files_before_the_database(data):
    bucket = FakeBucket()

    backup(bucket, data, data / "vigil.sqlite", BUCKET)

    assert bucket.calls == ["sync_bucket", "sync_bucket", "batch_bucket_files"]


def test_restore_brings_back_what_backup_saved(data, tmp_path):
    bucket = FakeBucket()
    backup(bucket, data, data / "vigil.sqlite", BUCKET)
    fresh = tmp_path / "fresh"

    restored = restore(bucket, fresh, fresh / "vigil.sqlite", BUCKET)

    assert restored is True
    assert (fresh / "frames" / "kilauea-kp" / "2026-11-01" / "a.jpg").read_bytes() == b"frame"
    assert (fresh / "bulletins" / "run1" / "bulletin.html").read_bytes() == b"<p>bulletin</p>"
    assert spent(fresh / "vigil.sqlite") == 0.42


def test_restore_of_an_empty_bucket_is_a_first_start(tmp_path):
    fresh = tmp_path / "fresh"

    restored = restore(FakeBucket(), fresh, fresh / "vigil.sqlite", BUCKET)

    assert restored is False
    assert not (fresh / "vigil.sqlite").exists()


def test_restore_fails_when_the_bucket_cannot_be_reached(tmp_path):
    bucket = FakeBucket()
    bucket.fail = OSError("network is unreachable")

    with pytest.raises(OSError, match="unreachable"):
        restore(bucket, tmp_path, tmp_path / "vigil.sqlite", BUCKET)


class Saver:
    """A stand-in for `backup` that counts its calls, sets `stop` on the second one and fails on those in `failing`."""

    def __init__(self, stop, failing=()):
        self.stop, self.failing, self.calls = stop, set(failing), 0

    def __call__(self, api, data_dir, db_path, bucket):
        self.calls += 1
        if self.calls == 2:
            self.stop.set()
        if self.calls in self.failing:
            raise OSError("boom")


def test_run_saves_every_interval_and_once_more_when_stopped(tmp_path):
    stop = threading.Event()
    save = Saver(stop)

    run(None, tmp_path, tmp_path / "vigil.sqlite", BUCKET, 0.01, stop, save=save)

    assert save.calls == 3


def test_run_goes_on_after_a_failed_save(tmp_path, caplog):
    stop = threading.Event()
    save = Saver(stop, failing={1})

    with caplog.at_level(logging.ERROR):
        run(None, tmp_path, tmp_path / "vigil.sqlite", BUCKET, 0.01, stop, save=save)

    assert save.calls == 3
    assert "boom" in caplog.text


def test_cli_refuses_an_interval_that_is_not_positive(capsys):
    with pytest.raises(SystemExit):
        main(["run", "--bucket", BUCKET, "--interval", "0"])

    assert "--interval" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persist.py`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'vigil.persist'`.

- [ ] **Step 3: Implement**

Create `vigil/persist.py`:

```python
"""Keep the live state across restarts of a Hugging Face Docker Space, whose disk is lost whenever it restarts.

The state goes to a private Hugging Face bucket: the frames and the bulletins as files, and the database as one
self-contained copy. They are saved in that order, so a saved row never points at a file the bucket lacks. `restore`
runs at every start; `run` saves every few minutes and once more when it is stopped. A restart therefore costs at
most the last interval of work, and the Meta API cost ledger, a table of the database, keeps the daily cap across
restarts.

    vigil-persist restore --bucket facurie/vigil-state
    vigil-persist run --bucket facurie/vigil-state --interval 300
"""

from __future__ import annotations

import argparse
import logging
import signal
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi

from vigil.mirror import snapshot_database
from vigil.settings import Settings

log = logging.getLogger(__name__)

FOLDERS = ("frames", "bulletins")  # saved as files, before the database
DB_KEY = "db/vigil.sqlite"


def _uri(bucket: str, *parts: str) -> str:
    return "/".join(["hf://buckets", bucket, *parts])


def backup(api: Any, data_dir: Path, db_path: Path, bucket: str) -> None:
    """Save the frames and bulletins under `data_dir` and then the database at `db_path` to `bucket`. Only changed
    files are transferred, and files deleted here stay in the bucket. The database is copied with SQLite's backup,
    which is safe while other processes write to it."""
    for name in FOLDERS:
        if (data_dir / name).is_dir():
            api.sync_bucket(str(data_dir / name), _uri(bucket, name))
    if db_path.is_file():
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / db_path.name
            snapshot_database(db_path, copy)
            api.batch_bucket_files(bucket, add=[(copy, DB_KEY)])


def restore(api: Any, data_dir: Path, db_path: Path, bucket: str) -> bool:
    """Put what `backup` saved back under `data_dir` and at `db_path`. Returns False when the bucket holds no
    database yet, which is the very first start. Any failure to read the bucket is raised, so a service never runs
    on an empty database while a good copy exists."""
    saved = {item.path for item in api.list_bucket_tree(bucket)}
    for name in FOLDERS:
        if name in saved:
            api.sync_bucket(_uri(bucket, name), str(data_dir / name))
    if "db" not in saved:
        return False
    db_path.parent.mkdir(parents=True, exist_ok=True)
    api.download_bucket_files(bucket, [(DB_KEY, db_path)])
    return True


def run(api: Any, data_dir: Path, db_path: Path, bucket: str, interval: float, stop: threading.Event, *,
        save: Callable[..., None] = backup) -> None:
    """Save every `interval` seconds until `stop` is set, and once more after that. A failed save is logged and the
    next one is tried: the network may be down for a while."""

    def attempt() -> None:
        try:
            save(api, data_dir, db_path, bucket)
        except Exception:
            log.exception("could not save the state to %s; trying again in %s s", bucket, interval)

    while True:
        attempt()
        if stop.wait(interval):
            break
    attempt()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Save the live state to a Hugging Face bucket (backup, run) and "
                                                 "put it back (restore).")
    parser.add_argument("action", choices=["restore", "backup", "run"])
    parser.add_argument("--bucket", required=True, help="bucket id, e.g. facurie/vigil-state")
    parser.add_argument("--interval", type=float, default=300.0, help="seconds between saves for `run` (default 300)")
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be positive")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    api = HfApi()
    if args.action == "restore":
        restored = restore(api, settings.data_dir, settings.db_path, args.bucket)
        print(f"state restored from {args.bucket}" if restored else f"{args.bucket} holds no state yet: first start")
    elif args.action == "backup":
        backup(api, settings.data_dir, settings.db_path, args.bucket)
        print(f"state saved to {args.bucket}")
    else:
        stop = threading.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.set())
        run(api, settings.data_dir, settings.db_path, args.bucket, args.interval, stop)


if __name__ == "__main__":
    main()
```

In `pyproject.toml`, add `vigil-persist = "vigil.persist:main"` to `[project.scripts]`, after `vigil-mirror`. Then reinstall so the script exists: `.venv/Scripts/python.exe -m pip install -e ".[dev]"`.

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persist.py`
Expected: 9 pass.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv/Scripts/python.exe -m pytest`. Expected: green, 582 tests (573 + 9).

```bash
git add vigil/persist.py tests/test_persist.py pyproject.toml
git commit -m "Save the live state to a Hugging Face bucket and restore it at start, since a Space loses its disk on restart"
```

---

### Task 5: Deploy the committed tree as a Space (`vigil-space`)

**Files:**
- Create: `vigil/space.py`
- Modify: `pyproject.toml` (script)
- Test: `tests/test_space.py`

The Hub builds a Docker Space from its own git repository and reads the Space's configuration from the README's front matter. `deploy` takes `git archive HEAD` (committed files only, so `.env`, `data/` and the git-excluded briefs are never sent), puts the front matter on top of the README and uploads the tree. Files the new tree no longer has are deleted from the Space, so no stale module ends up in the image.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_space.py`:

```python
import io
import tarfile
from pathlib import Path

import pytest

from vigil.space import APP_PORT, main, space_readme, stage, deploy

REPO = "facurie/volcano-vigil"
FILES = {"README.md": "# Volcano Vigil\n", "Dockerfile": "FROM python:3.12-slim\n", "vigil/__init__.py": ""}


def archive(files):
    """What `git archive` prints: a tar of the files."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, text in files.items():
            content = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


class FakeApi:
    """Records what `deploy` asks of the Hub, and the files the folder held when it was uploaded."""

    def __init__(self):
        self.created, self.uploads = [], []

    def create_repo(self, repo_id, **kwargs):
        self.created.append((repo_id, kwargs))

    def upload_folder(self, **kwargs):
        folder = Path(kwargs["folder_path"])
        files = sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file())
        self.uploads.append({**kwargs, "files": files, "readme": (folder / "README.md").read_text(encoding="utf-8")})


def test_the_space_readme_declares_a_docker_space_on_the_apps_port():
    readme = space_readme("# Volcano Vigil\n")

    assert readme.startswith("---\ntitle: Volcano Vigil\n")
    assert "\nsdk: docker\n" in readme and f"\napp_port: {APP_PORT}\n" in readme
    assert readme.endswith("\n---\n\n# Volcano Vigil\n")


def test_stage_unpacks_the_archive_and_puts_the_front_matter_on_the_readme(tmp_path):
    staged = stage(archive(FILES), tmp_path)

    assert staged == ["Dockerfile", "README.md", "vigil/__init__.py"]
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == space_readme("# Volcano Vigil\n")
    assert (tmp_path / "Dockerfile").read_text(encoding="utf-8") == "FROM python:3.12-slim\n"


def test_stage_refuses_an_archive_that_would_write_outside_its_folder(tmp_path):
    with pytest.raises(tarfile.FilterError):
        stage(archive({"../evil.txt": "x", **FILES}), tmp_path / "out")


def test_deploy_creates_a_protected_docker_space_and_uploads_the_tree():
    api = FakeApi()

    count = deploy(api, REPO, archive(FILES), "abc1234def")

    assert api.created == [(REPO, {"repo_type": "space", "space_sdk": "docker", "visibility": "protected",
                                   "exist_ok": True})]
    [upload] = api.uploads
    assert upload["repo_id"] == REPO and upload["repo_type"] == "space"
    assert upload["delete_patterns"] == ["*"]
    assert upload["commit_message"] == "Deploy abc1234"
    assert upload["files"] == ["Dockerfile", "README.md", "vigil/__init__.py"]
    assert upload["readme"].startswith("---\n")
    assert count == 3


def test_the_cli_deploys_the_committed_tree(monkeypatch, capsys):
    api = FakeApi()
    monkeypatch.setattr("vigil.space.HfApi", lambda: api)
    monkeypatch.setattr("vigil.space.committed_tree", lambda: (archive(FILES), "abc1234def"))

    main(["deploy", "--repo", REPO])

    assert api.uploads[0]["commit_message"] == "Deploy abc1234"
    assert f"https://huggingface.co/spaces/{REPO}" in capsys.readouterr().out
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_space.py`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'vigil.space'`.

- [ ] **Step 3: Implement**

Create `vigil/space.py`:

```python
"""Deploy the committed tree as a Hugging Face Docker Space (docs/DEPLOY.md).

    vigil-space deploy --repo facurie/volcano-vigil

`git archive HEAD` sends committed files only, so `.env`, `data/` and the git-excluded briefs never leave this
machine. The Space is created "protected": its code is private and its app is public. Every deploy makes the Hub
rebuild the image and restart the Space; the live state comes back from its bucket (vigil/persist.py).
"""

from __future__ import annotations

import argparse
import io
import subprocess
import tarfile
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

APP_PORT = 7860  # the port vigil-web listens on (deploy/start.sh) and the Hub proxies to

CARD = f"""---
title: Volcano Vigil
emoji: 🌋
colorFrom: red
colorTo: gray
sdk: docker
app_port: {APP_PORT}
pinned: false
short_description: Kīlauea webcams to measurements and ES/EN bulletins
---

"""


def space_readme(readme: str) -> str:
    """The repository's README with the Space's configuration on top, where the Hub reads it."""
    return CARD + readme


def stage(archive: bytes, out: Path) -> list[str]:
    """Unpack a tar of the repository into `out` (refusing any member that would land outside it) and put the
    Space's front matter on its README. Returns the staged paths, sorted."""
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(out, filter="data")
    readme = out / "README.md"
    readme.write_text(space_readme(readme.read_text(encoding="utf-8")), encoding="utf-8")
    return sorted(path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file())


def deploy(api: HfApi, repo_id: str, archive: bytes, revision: str) -> int:
    """Create the Space if needed and upload the tree in `archive`, deleting what the tree no longer has. Returns
    how many files were uploaded."""
    with tempfile.TemporaryDirectory() as tmp:
        staged = stage(archive, Path(tmp))
        api.create_repo(repo_id, repo_type="space", space_sdk="docker", visibility="protected", exist_ok=True)
        api.upload_folder(repo_id=repo_id, repo_type="space", folder_path=tmp,
                          commit_message=f"Deploy {revision[:7]}", delete_patterns=["*"])
    return len(staged)


def committed_tree() -> tuple[bytes, str]:
    """`git archive HEAD` as tar bytes, and the commit it archives."""
    revision = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    archive = subprocess.run(["git", "archive", "--format=tar", "HEAD"], capture_output=True, check=True).stdout
    return archive, revision


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Deploy the committed tree (HEAD) as a Hugging Face Docker Space.")
    parser.add_argument("action", choices=["deploy"])
    parser.add_argument("--repo", required=True, help="Space id, e.g. facurie/volcano-vigil")
    args = parser.parse_args(argv)

    archive, revision = committed_tree()
    count = deploy(HfApi(), args.repo, archive, revision)
    print(f"{count} files of {revision[:7]} deployed to https://huggingface.co/spaces/{args.repo}")


if __name__ == "__main__":
    main()
```

In `pyproject.toml`, add `vigil-space = "vigil.space:main"` to `[project.scripts]`, after `vigil-persist`. Then reinstall: `.venv/Scripts/python.exe -m pip install -e ".[dev]"`.

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_space.py`
Expected: 5 pass.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv/Scripts/python.exe -m pytest`. Expected: green, 587 tests (582 + 5).

```bash
git add vigil/space.py tests/test_space.py pyproject.toml
git commit -m "Add vigil-space to deploy the committed tree as a protected Hugging Face Docker Space"
```

---

### Task 6: The image and the entry point

**Files:**
- Create: `deploy/constraints.txt`, `Dockerfile`, `.dockerignore`, `deploy/start.sh`
- Test: `tests/test_deploy.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_deploy.py`:

```python
"""The Space's image and entry point (docs/DEPLOY.md) keep the project's rules: the daily budget, secrets out of git
and the image, the state restored before anything runs, the port the Space card declares, and the dependency
versions the tests pass with."""

import re
import tomllib
from pathlib import Path

from vigil.space import APP_PORT

ROOT = Path(__file__).resolve().parent.parent


def text(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def pyproject():
    return tomllib.loads(text("pyproject.toml"))


def test_the_image_runs_as_an_unprivileged_user_and_copies_no_secrets_or_data():
    dockerfile = text("Dockerfile")

    assert dockerfile.startswith("# ") and "\nFROM python:3.12-slim\n" in dockerfile
    assert "ffmpeg" in dockerfile and "-c deploy/constraints.txt" in dockerfile
    assert "useradd --create-home --uid 1000 vigil" in dockerfile and "\nUSER vigil\n" in dockerfile
    assert not re.search(r"^COPY\s+(\.\s|\S*\.env\b|data\b)", dockerfile, re.MULTILINE)  # no `COPY . .`
    ignored = text(".dockerignore").split()
    assert {".env", ".env.*", "data/"} <= set(ignored)


def test_the_image_carries_the_daily_budget_and_the_dirs_every_service_shares():
    dockerfile = text("Dockerfile")

    assert "DAILY_BUDGET_USD=3" in dockerfile
    assert "DATA_DIR=/app/data" in dockerfile and "DB_PATH=/app/data/vigil.sqlite" in dockerfile
    assert "mkdir data && chown vigil:vigil data" in dockerfile


def test_the_dashboard_listens_on_the_port_the_space_card_declares():
    dockerfile, script = text("Dockerfile"), text("deploy", "start.sh")

    assert f"EXPOSE {APP_PORT}\n" in dockerfile
    assert 'CMD ["bash", "deploy/start.sh"]' in dockerfile
    assert f"vigil-web --host 0.0.0.0 --port {APP_PORT} &" in script


def test_the_state_is_restored_before_anything_runs_and_a_failed_restore_stops_the_start():
    script = text("deploy", "start.sh")

    order = ["vigil-persist restore", "vigil-mirror pull", "vigil-web", "vigil-ingest --once",
             "supervise vigil-ingest", "supervise vigil-pipeline", "vigil-persist run"]
    positions = [script.index(step) for step in order]
    assert positions == sorted(positions)
    for line in script.splitlines():
        if line.startswith(("vigil-persist restore", "vigil-mirror pull")):
            assert line.endswith("|| exit 1"), line


def test_the_entry_point_runs_the_existing_clis_with_the_projects_arguments():
    script = text("deploy", "start.sh")

    assert "vigil-mirror pull --episode 55 --repo facurie/volcano-vigil-ep55 || exit 1" in script
    assert "vigil-ingest --once --lookback-hours 24" in script
    assert "supervise vigil-ingest --lookback-hours 24 &" in script
    assert "supervise vigil-pipeline --volcano kilauea &" in script
    assert 'vigil-persist run --bucket "$BUCKET" --interval 300 &' in script
    commands = set(re.findall(r"^(?:supervise )?(vigil-[a-z]+)", script, re.MULTILINE))
    assert commands <= set(pyproject()["project"]["scripts"])


def test_the_state_is_saved_one_last_time_when_the_space_stops():
    script = text("deploy", "start.sh")

    assert "trap stop TERM INT" in script
    assert 'kill "$persist_pid"' in script and 'wait "$persist_pid"' in script


def test_every_runtime_dependency_is_pinned_for_the_image():
    def name(requirement):
        return re.split(r"[<>=!~\[ ;]", requirement, maxsplit=1)[0].lower().replace("_", "-")

    pins = {}
    for line in text("deploy", "constraints.txt").splitlines():
        if line and not line.startswith("#"):
            package, version = line.split("==")
            pins[name(package)] = version
    for requirement in pyproject()["project"]["dependencies"]:
        assert name(requirement) in pins, requirement
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deploy.py`
Expected: FAIL with `FileNotFoundError` for `Dockerfile`, `deploy/start.sh` and `deploy/constraints.txt`.

- [ ] **Step 3: Write the files**

`deploy/constraints.txt` is `pip freeze --exclude-editable` of `.venv` on 2026-10-31. Left out are test tools (pytest, iniconfig, pluggy, Pygments), colorama (Windows only) and git-filter-repo (not a project dependency):

```
# Exact versions of the runtime dependencies, from the venv where the test suite passes (2026-10-31). The image
# installs with these as pip constraints: `pip install -c deploy/constraints.txt .`. Refresh after an upgrade with
# `pip freeze --exclude-editable`, leaving out test tools, colorama and git-filter-repo.
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.15.1
certifi==2026.10.23
click==8.5.0
fastapi==0.162.0
filelock==4.2.6
fsspec==2026.9.0
h11==0.16.0
hf-xet==1.8.0
httpcore==1.0.9
httpcore2==2.16.0
httpx==0.28.1
httpx2==2.16.0
huggingface_hub==2.4.0
idna==3.20
jiter==0.18.0
meta-sam-parser==0.1.0
numpy==2.5.4
openai==3.39.0
opentelemetry-api==1.45.2
packaging==26.3
pillow==13.0.0
pydantic==2.14.1
pydantic_core==2.50.1
python-dotenv==1.2.4
PyYAML==6.0.3
sniffio==1.3.1
starlette==1.10.0
tqdm==4.70.1
truststore==0.10.5
typing-inspection==0.4.4
typing_extensions==4.16.0
uvicorn==0.54.0
```

Before relying on this list, run `.venv/Scripts/python.exe -m pip freeze --exclude-editable` and compare: if a package is in the freeze but not here (for example one added after 2026-10-31), add it with its version.

`Dockerfile`:

```dockerfile
# The Volcano Vigil image, built by the Hugging Face Docker Space (docs/DEPLOY.md).

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 vigil
WORKDIR /app

COPY deploy/constraints.txt deploy/constraints.txt
COPY pyproject.toml README.md LICENSE ./
COPY vigil vigil
RUN pip install --no-cache-dir -c deploy/constraints.txt .
COPY config config
COPY deploy/start.sh deploy/start.sh
RUN mkdir data && chown vigil:vigil data

USER vigil
ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    DB_PATH=/app/data/vigil.sqlite \
    DAILY_BUDGET_USD=3
EXPOSE 7860
CMD ["bash", "deploy/start.sh"]
```

`.dockerignore`:

```
# The Dockerfile copies only what it names, and this keeps secrets and data out of any build context too.
.env
.env.*
data/
.venv/
.git/
**/__pycache__/
tests/
docs/
```

`deploy/start.sh`:

```bash
#!/usr/bin/env bash
# The Space container's entry point (docs/DEPLOY.md): restore the state, start the dashboard, catch up on the frames
# missed while the Space was down, then run the live services next to the state saver.
set -uo pipefail

BUCKET=facurie/vigil-state

# The disk is empty at every start. If a restore fails, stop: the Hub restarts the Space, and no service ever runs
# on an empty database that the next save would put over the bucket's good copy, forgetting the day's spend.
vigil-persist restore --bucket "$BUCKET" || exit 1
vigil-mirror pull --episode 55 --repo facurie/volcano-vigil-ep55 || exit 1

vigil-web --host 0.0.0.0 --port 7860 &
web_pid=$!

# Frames from the last 24 h that AshCam still has, so the first hours the pipeline tracks are complete.
vigil-ingest --once --lookback-hours 24 || echo "catch-up failed; the ingest service below retries" >&2

# Run a service again whenever it exits (for example, the pipeline before MODEL_API_KEY is set).
supervise() {
  while true; do
    "$@"
    echo "$1 exited with status $?; restarting in 10 s" >&2
    sleep 10
  done
}
supervise vigil-ingest --lookback-hours 24 &
ingest_pid=$!
supervise vigil-pipeline --volcano kilauea &
pipeline_pid=$!
vigil-persist run --bucket "$BUCKET" --interval 300 &
persist_pid=$!

# On a stop, let the saver make its last save (SIGTERM) before anything else goes.
stop() {
  trap '' TERM INT
  kill "$persist_pid" 2>/dev/null && wait "$persist_pid"
  kill "$ingest_pid" "$pipeline_pid" "$web_pid" 2>/dev/null
  exit 0
}
trap stop TERM INT

wait "$web_pid"
echo "the dashboard exited with status $?; stopping the Space" >&2
exit 1
```

Check its syntax: `bash -n deploy/start.sh` prints nothing. The file keeps LF endings (`.gitattributes` has `* text=auto eol=lf`).

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deploy.py`
Expected: 7 pass.

- [ ] **Step 5: Build the image locally if Docker is running**

Run: `docker info --format '{{.ServerVersion}}'`. If it prints a version, run `docker build -t volcano-vigil-check .` from the repo root. Expected: the build ends with `naming to docker.io/library/volcano-vigil-check`. Then run `docker run --rm volcano-vigil-check vigil-persist --help`, which should print the usage. If Docker Desktop is not running, skip this step and say so in the report: the first build on the Hub in Task 10 is then the check.

- [ ] **Step 6: Run the full suite and commit**

Run: `.venv/Scripts/python.exe -m pytest`. Expected: green, 594 tests (587 + 7).

```bash
git add deploy/constraints.txt Dockerfile .dockerignore deploy/start.sh tests/test_deploy.py
git commit -m "Add the image and entry point the Space runs, with the state restored first and the budget kept out of git"
```

---

### Task 7: The runbook

**Files:**
- Create: `docs/DEPLOY.md`

- [ ] **Step 1: Write `docs/DEPLOY.md`**

`````markdown
# Deployment

Volcano Vigil runs as one Hugging Face Docker Space, `facurie/volcano-vigil`, on the free `cpu-basic` hardware
(2 vCPU, 16 GB). The address is in the README.

## Why this server

- Oracle Cloud's Always Free VM needs a credit card at signup, and the owner has none. Hugging Face Docker Spaces
  need a PRO subscription ($9/month), which the owner has.
- The Space's visibility is "protected": the code stays private and the app is public.
- A Space's disk is lost whenever it restarts. The live state is saved to a private bucket, `facurie/vigil-state`
  (`vigil/persist.py`), so the database, and with it the Meta API cost ledger and `DAILY_BUDGET_USD`, survive.

## What runs in the container (`deploy/start.sh`)

| Step | Command | Role |
|---|---|---|
| 1 | `vigil-persist restore` | Puts the saved database, frames and bulletins back. A failure stops the start (the Hub restarts the Space) |
| 2 | `vigil-mirror pull --episode 55 …` | Puts the episode 55 replay from its [Hugging Face dataset](https://huggingface.co/datasets/facurie/volcano-vigil-ep55) into the data dir, downloading only what changed |
| 3 | `vigil-web --host 0.0.0.0 --port 7860` | The dashboard, live and replay; it opens the databases read-only |
| 4 | `vigil-ingest --once --lookback-hours 24` | Catches up on the last 24 h of KPcam and K2cam from AshCam |
| 5 | `vigil-ingest --lookback-hours 24` | Polls KPcam and K2cam (AshCam) and F1cam (`M.jpg`); restarted if it exits |
| 6 | `vigil-pipeline --volcano kilauea` | Every 5 min: quality gate, one SAM window per camera per hour, measurements, an hourly bulletin. The only service that spends money; restarted if it exits |
| 7 | `vigil-persist run --interval 300` | Saves the state every 5 min and once more when the Space stops |

All of them run one image as uid 1000 with `DAILY_BUDGET_USD=3`, on the data dir `/app/data`. SQLite in WAL mode
lets them write and read at once. Secrets (`MODEL_API_KEY`, `HF_TOKEN`) are Space secrets, which reach the
processes as environment variables; they are never in git or in the image.

## First-time setup

1. **The bucket:** `.venv/Scripts/hf.exe buckets create vigil-state --private`.
2. **A token for the Space:** huggingface.co/settings/tokens → New token → type Write → name `vigil-space`. The
   Space uses it to read and write the bucket. Revoke it when the project is over.
3. **The Space:** `vigil-space deploy` (step 5) creates it as "protected" if it does not exist yet. To have it before
   the first code arrives (so the secrets can be set first), create it once with
   `HfApi().create_repo("facurie/volcano-vigil", repo_type="space", space_sdk="docker", visibility="protected", exist_ok=True)`.
4. **The secrets:** Space → Settings → Variables and secrets → New secret, twice:
   - `MODEL_API_KEY`: the value of that line in the local `.env`;
   - `HF_TOKEN`: the token of step 2.

   Phase 8 adds the Telegram token the same way.
5. **Deploy:** commit, then `.venv/Scripts/vigil-space.exe deploy --repo facurie/volcano-vigil`. The Hub builds the
   image (a few minutes) and starts it. Watch it with the commands under "Operate".

## Deploy a change

Commit, then run `vigil-space deploy --repo facurie/volcano-vigil`. It uploads `git archive HEAD`, never the working
tree, `.env` or `data/`, and deletes from the Space the files the tree no longer has. Each deploy rebuilds the image
and restarts the Space; the state comes back from the bucket (at most the last 5 minutes of work are lost).

## Operate

- **Visit the URL at least once every 24 hours.** Free hardware goes to sleep after 48 hours without visitors, which
  stops ingest and the pipeline. A visit wakes it, the state is restored and ingest catches up on up to 24 h; a gap
  longer than that is not filled by itself.
- Stage: `HfApi().get_space_runtime("facurie/volcano-vigil").stage` (`BUILDING`, `RUNNING`, `RUNTIME_ERROR`, …).
- Logs, `build` or `run` (the run log streams, so the command stops after 20 s without news):

  ```python
  # .venv/Scripts/python.exe -I - run <<'EOF'
  import sys
  import httpx
  from huggingface_hub import get_token

  url = f"https://huggingface.co/api/spaces/facurie/volcano-vigil/logs/{sys.argv[1]}"
  try:
      with httpx.stream("GET", url, params={"tail": 100}, headers={"Authorization": f"Bearer {get_token()}"},
                        timeout=20) as response:
          for line in response.iter_lines():
              print(line)
  except httpx.ReadTimeout:
      pass
  # EOF
  ```
- Today's Meta API spend (UTC day) and the frames per camera, from the bucket's copy of the database (at most
  5 minutes old):

  `.venv/Scripts/hf.exe buckets cp hf://buckets/facurie/vigil-state/db/vigil.sqlite <scratch>/ledger.sqlite`

  `.venv/Scripts/python.exe -I -c "import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); print(c.execute(\"SELECT ROUND(COALESCE(SUM(cost_usd), 0), 3) FROM api_calls WHERE substr(called_at, 1, 10) = date('now')\").fetchone()[0], c.execute('SELECT camera_id, COUNT(*), MAX(captured_at) FROM frames GROUP BY camera_id').fetchall())" <scratch>/ledger.sqlite`
- Stop everything at once (nothing spends while it is paused): `HfApi().pause_space("facurie/volcano-vigil")`.
  Resume with `HfApi().restart_space("facurie/volcano-vigil")`.
- After a new replay of episode 55: run `vigil-mirror push --episode 55 --repo facurie/volcano-vigil-ep55` locally,
  then redeploy. `vigil-mirror pull` fetches what changed.

## Costs

- Space and bucket: $0 beyond the PRO subscription ($9/month; PRO includes 1 TB of private storage).
- Meta Model API: the pipeline costs about $2–3 a day, capped at $3 a UTC day. Hitting the cap stops SAM, Muse Spark
  and bulletins until 00:00 UTC (14:00 HST); ingest and the dashboard go on.
- If the daily visit is ever missed or the 2 vCPU fall behind: `CPU Upgrade` costs $0.03/hour (about $0.72/day) and
  never sleeps. Switch to it only with the owner's OK.

## Risks

- **The Space sleeps** after 48 hours without visitors (see "Operate"), and the Hub may restart it at any time.
  Either way the state is restored; the work since the last save (5 minutes) is lost.
- **The restore fails** (for example, `HF_TOKEN` was revoked): the Space shows a runtime error and restarts instead
  of running on an empty database. Fix the secret.
- **AshCam** can change without notice, or may not answer from the Hub's network. Live ingest falls back to
  `M.jpg`, and the replay no longer needs AshCam.
- **A write token** sits in the Space's secrets. Revoke it after the judging.
`````

- [ ] **Step 2: Run the full suite and commit**

Run: `.venv/Scripts/python.exe -m pytest`. Expected: green (594).

```bash
git add docs/DEPLOY.md
git commit -m "Add the runbook for the Hugging Face Space"
```

---

### Task 8: Push the episode 55 mirror and check it restores (orchestrator, $0)

Needs: Tasks 2–3 committed, and `hf auth whoami` printing `facurie`.

- [ ] **Step 1: Push.** Run: `.venv/Scripts/vigil-mirror.exe push --episode 55 --repo facurie/volcano-vigil-ep55`. Expected: `episode 55: 510 files pushed to https://huggingface.co/datasets/facurie/volcano-vigil-ep55`. The 510 files are 468 frames, the replay folder's 40 other files (on 2026-10-31), the database and the README. Upload: ~255 MB.
- [ ] **Step 2: Restore anonymously into an empty data dir, as the Space will.** Use an empty `HF_HOME`, so no token is found:

```bash
S=<scratchpad>/mirror-check; rm -rf "$S"; mkdir -p "$S/hf"
HF_HOME="$S/hf" DATA_DIR="$S/data" DB_PATH="$S/data/vigil.sqlite" .venv/Scripts/vigil-mirror.exe pull --episode 55 --repo facurie/volcano-vigil-ep55
```

  Expected: `episode 55 restored: …/replay/ep55/vigil.sqlite`.
- [ ] **Step 3: Compare.**
  - Every file of `episode_files(Path("data"), EP55)` must have the same SHA-256 under `$S/data`.
  - The restored database must hold the same row counts in `frames` (468), `detections` (804), `measurements` (492), `bulletins` (7) and `replay_ticks` (78) as `data/replay/ep55/vigil.sqlite`.
  - Check this with a short Python snippet run with `-I`.
- [ ] **Step 4: Serve the restored copy.** Start `vigil-web --port 8765` with `DATA_DIR`/`DB_PATH` pointing at `$S/data`, in the background. Then:
  - `GET /api/config`: `replays[0].episode == "55"`;
  - `GET /api/frames/29/image?replay=55&at=2026-10-17T15:00:00Z`: 200 `image/jpeg`;
  - `GET /media/replay/ep55/bulletins/run2/frame29_plume.jpg`: 200.

  Stop the server and delete `$S`.
- [ ] **Step 5:** Open the dataset page and check that the card renders with the disclaimer and the licenses. Note the file count and size for the execution notes.

---

### Task 9: The bucket, the Space and the secrets (user + orchestrator, $0)

Needs: Tasks 4–5 committed.

- [ ] **Step 1: The bucket (orchestrator).** Run: `.venv/Scripts/hf.exe buckets create vigil-state --private`. Expected: it prints the bucket `facurie/vigil-state`.
- [ ] **Step 2: Check the persistence against the real bucket (orchestrator).** Save a throwaway state, restore it elsewhere, compare, and empty the bucket again, so the Space's first start is a true first start:

```bash
.venv/Scripts/python.exe -I - <<'EOF'
import tempfile, sqlite3
from contextlib import closing
from pathlib import Path
from huggingface_hub import HfApi
from vigil import db
from vigil.persist import backup, restore

BUCKET = "facurie/vigil-state"
api = HfApi()
with tempfile.TemporaryDirectory() as tmp:
    src, dst = Path(tmp, "src"), Path(tmp, "dst")
    (src / "frames" / "kilauea-kp" / "2026-11-01").mkdir(parents=True)
    (src / "frames" / "kilauea-kp" / "2026-11-01" / "a.jpg").write_bytes(b"frame")
    (src / "bulletins" / "run1").mkdir(parents=True)
    (src / "bulletins" / "run1" / "bulletin.html").write_bytes(b"<p>bulletin</p>")
    with closing(db.connect(src / "vigil.sqlite")) as conn:
        conn.execute("INSERT INTO api_calls (called_at, model, purpose, cost_usd, ok) "
                     "VALUES ('2026-11-01T20:00:00Z', 'sam-3.1', 'segment', 0.42, 1)")
        conn.commit()
    print("empty bucket restores as first start:", restore(api, dst, dst / "vigil.sqlite", BUCKET) is False)
    backup(api, src, src / "vigil.sqlite", BUCKET)
    print("restored:", restore(api, dst, dst / "vigil.sqlite", BUCKET))
    print("frame equal:", (dst / "frames/kilauea-kp/2026-11-01/a.jpg").read_bytes() == b"frame")
    print("bulletin equal:", (dst / "bulletins/run1/bulletin.html").read_bytes() == b"<p>bulletin</p>")
    with closing(sqlite3.connect(dst / "vigil.sqlite")) as conn:
        print("ledger:", conn.execute("SELECT SUM(cost_usd) FROM api_calls").fetchone()[0])
    files = [item.path for item in api.list_bucket_tree(BUCKET, recursive=True) if item.type == "file"]
    print("bucket held:", sorted(files))
    api.batch_bucket_files(BUCKET, delete=files)
    print("bucket left with:", [item.path for item in api.list_bucket_tree(BUCKET)])
EOF
```

  Expected: `empty bucket restores as first start: True`, `restored: True`, `frame equal: True`, `bulletin equal: True`, `ledger: 0.42`, the three files listed, and `bucket left with: []`. If the real `sync_bucket` or `list_bucket_tree` behaves differently from `FakeBucket` (for example, `sync_bucket` fails on an empty remote prefix, or `item.path` for a folder carries a trailing slash), stop and fix `vigil/persist.py` and `tests/test_persist.py` first.
- [ ] **Step 3: The token (the user).** huggingface.co/settings/tokens → New token → type **Write** → name `vigil-space` → copy it once.
- [ ] **Step 4: Create the Space (orchestrator).**

```bash
.venv/Scripts/python.exe -I -c "from huggingface_hub import HfApi; print(HfApi().create_repo('facurie/volcano-vigil', repo_type='space', space_sdk='docker', visibility='protected', exist_ok=True))"
```

  Expected: it prints `https://huggingface.co/spaces/facurie/volcano-vigil` with no HTTP 402 (PRO works).
- [ ] **Step 5: The secrets (the user).** In the Space → Settings → Variables and secrets → New secret:
  - `MODEL_API_KEY`: the value of `MODEL_API_KEY` in the local `.env`, which only the user opens;
  - `HF_TOKEN`: the token of Step 3.

  Nothing is printed or pasted into the chat.

---

### Task 10: First deploy and acceptance (user + orchestrator; starts the approved live spend)

Needs: Tasks 1–9 done, the suite green and everything committed (the Space gets HEAD).

- [ ] **Step 1: Deploy.** Run: `.venv/Scripts/vigil-space.exe deploy --repo facurie/volcano-vigil`. Expected: `N files of <sha> deployed to https://huggingface.co/spaces/facurie/volcano-vigil`.
- [ ] **Step 2: Wait for the build and the start.**

```bash
.venv/Scripts/python.exe -I - <<'EOF'
import time
from huggingface_hub import HfApi
api = HfApi()
for _ in range(60):
    stage = api.get_space_runtime("facurie/volcano-vigil").stage
    print(time.strftime("%H:%M:%S"), stage, flush=True)
    if stage in ("RUNNING", "RUNTIME_ERROR", "BUILD_ERROR", "CONFIG_ERROR"):
        break
    time.sleep(30)
EOF
```

  Expected: `RUNNING` within ~10 min. On any error stage, read the build or run log with the snippet in `docs/DEPLOY.md` and fix before going on.
- [ ] **Step 3: Follow the first start in the run log.** Expected, in order: `state restored …` or `… holds no state yet: first start`; `episode 55 restored: …`; the dashboard's startup; the catch-up polling K2 and KP (about 12 min, as measured above); then the supervised services and the first pipeline step. Frames are only as old as AshCam's latency by the end.
- [ ] **Step 4: Acceptance checks from here** (`U=https://facurie-volcano-vigil.hf.space`):
  - The code is private and the app is public, anonymously:
    - `curl -s -o /dev/null -w "%{http_code}" https://huggingface.co/spaces/facurie/volcano-vigil/raw/main/Dockerfile` is 401 or 404, not 200;
    - `curl -s -o /dev/null -w "%{http_code}" $U/api/config` is 200.
  - `curl -sS $U/api/config`: `live.available` is true, `replays[0].episode` is `"55"`, and `disclaimer.en` is present.
  - `curl -sS $U/api/cameras`: K2 and KP `latest.minutes_ago` < 10, F1 < 15 (this also shows that AshCam answers from the Hub's network), with conditions from the quality gate (not `unchecked`) once the pipeline's first step has run (≤ 5 min).
  - `curl -sS "$U/api/replay?replay=55"`: 78 ticks and the results tables.
  - `curl -sS -o /dev/null -w "%{http_code} %{content_type}" "$U/api/frames/29/image?replay=55&at=2026-10-17T15:00:00Z"`: `200 image/jpeg`.
  - The run log shows pipeline step summaries and no `failed:` lines, apart from windows a night or fog leaves empty.
  - After the next full hour plus the 5-min settle, `curl -sS $U/api/bulletins` lists a bulletin with `verified` true or with its unmatched numbers listed, and the page shows the disclaimer and the HVO link.
  - Today's spend (the `docs/DEPLOY.md` command on the bucket's copy of the database) is under $3, and the bucket holds `db/`, `frames/` and `bulletins/`.
- [ ] **Step 5: Screenshots.** Use headless Edge, as in Phase 6: the script `shot.sh` must be recreated in this session's scratchpad. Take the public URL in live mode and in replay mode at 05:00 HST (`#mode=replay&at=2026-10-17T15:00:00Z`), at 1440 px. Look at them: frames, masks, the drum, the map, the bulletins and the disclaimer banner.
- [ ] **Step 6: Restart test.** Note today's spend, the newest frame time per camera and the bulletin ids (Step 4's commands), then run `HfApi().restart_space("facurie/volcano-vigil")` and wait for `RUNNING` again. Check:
  - the run log starts with `state restored …`, not `first start`;
  - the site answers and `/api/bulletins` lists the same bulletins;
  - the spend is not lower than before (the ledger came back) and the frames before the restart are still listed;
  - ingest caught up on the frames captured while it restarted.
- [ ] **Step 7: Tell the user the daily routine:** open `https://facurie-volcano-vigil.hf.space` at least once every 24 hours, and note the hour of the first visit so the next ones keep inside the window.

---

### Task 11: Docs, roadmap and memory (orchestrator)

- [ ] **Step 1: `docs/PLAN.md`.**
  - The tech stack line already says "Deployment: Hugging Face Spaces (Docker)."; leave it.
  - Add a line to "How to resume" after the remote line: "7. Deployment: [DEPLOY.md](DEPLOY.md), with the Space's address and commands."
  - Replace the Phase 7 section with the text below. Fill the acceptance sentence in with what Task 10 measured: the URL, the frame ages, the first bulletin, the restart check and the spend.

```markdown
## Phase 7: Sat Oct 31. Deployment

Decided on 2026-11-01: a Hugging Face Docker Space (PRO), after Oracle Cloud turned out to need a credit card. Plan:
[2026-10-31-phase-7-deploy.md](superpowers/plans/2026-10-31-phase-7-deploy.md). Runbook: [DEPLOY.md](DEPLOY.md).

- [x] **Hugging Face Space (Docker), protected:**
  - One image from `python:3.12-slim` with ffmpeg, installed with the versions the tests pass with
    (`deploy/constraints.txt`).
  - Ingest, pipeline and the dashboard run as separate processes of one container, under a small supervisor
    (`deploy/start.sh`). They are not threads in one process: the CLIs already exist, and SAM mask decoding stays off
    the web server.
  - `MODEL_API_KEY` and `HF_TOKEN` are Space secrets, and `DAILY_BUDGET_USD=3` is in the image.
  - The code is private and the app is public ("protected" visibility).
- [x] **State that survives restarts:**
  - A Space loses its disk on every restart (confirmed in the docs). `vigil-persist` saves the database, the frames and
    the bulletins to a private bucket every 5 minutes and when the Space stops, and restores them at every start, so the
    cost ledger and the cap hold across restarts.
- [x] **Episode 55 data that does not depend on AshCam (required):**
  - The 468 replay frames (public domain) and the replay's outputs are mirrored on the public dataset
    [`facurie/volcano-vigil-ep55`](https://huggingface.co/datasets/facurie/volcano-vigil-ep55). The Space pulls them at
    every start.
  - On start, ingest catches up on the last 24 h from AshCam (`vigil-ingest --lookback-hours 24`).
  - Images never go into the git repo.

**Acceptance:** a public URL is live, with ingest running and the replay working. Done: <measured results>.
```

  - In the risk table, add the row: `| The free Space sleeps after 48 h without visitors, or the Hub restarts it | The owner opens the URL every 24 h; the state is saved every 5 minutes and restored at start ([DEPLOY.md](DEPLOY.md)) |`
  - In "Budget", add Phase 7's spend: $0 for the mirror, the bucket and the Space, plus the live pipeline's spend up to that point, read from the bucket's copy of the ledger.
- [ ] **Step 2: `README.md`.**
  - Under the first paragraph, add: `**Live:** https://facurie-volcano-vigil.hf.space (the dashboard; the episode 55 replay is under "Replay").`
  - In Status, tick "Wind comparison", "Muse Spark agent and bulletins" and "Episode 55 replay and validation", which Phases 4–5 finished. Replace "Dashboard and deployment" with two ticked items: "Dashboard, live and replay (`vigil-web`)" and "Deployment as a Hugging Face Docker Space ([DEPLOY.md](docs/DEPLOY.md)), with episode 55 mirrored on [Hugging Face](https://huggingface.co/datasets/facurie/volcano-vigil-ep55)".
- [ ] **Step 3: `DATA_SOURCES.md`.**
  - Change "A deployment fetches its own copies from the original sources." to "A deployment fetches its own copies from the original sources. The episode 55 replay's frames and outputs come from our public mirror, [facurie/volcano-vigil-ep55](https://huggingface.co/datasets/facurie/volcano-vigil-ep55), because AshCam keeps frames for only about 31 days."
  - Move the Open-Meteo row from "Planned" to "In use". It has been in use since Phase 4.
- [ ] **Step 4:** Append "## Execution notes" to this plan: what differed from the plan, the measured numbers (upload size, build time, catch-up time, first-step cost, the restart check) and anything learned.
- [ ] **Step 5:** Run the full suite (`.venv/Scripts/python.exe -m pytest -o addopts=""` for the count). Commit `docs/PLAN.md README.md DATA_SOURCES.md docs/superpowers/plans/2026-10-31-phase-7-deploy.md` by name: "Mark Phase 7 done: the dashboard runs as a Hugging Face Docker Space with its state saved to a bucket". Then `git push origin main`.
- [ ] **Step 6:** Update the memory note `volcano-vigil-status` with the Space's URL and repository, the bucket, the dataset, the secrets it holds (names only), the daily-visit routine, the decisions and the open risks (the Space sleeping, the 5-minute save window, the Phase 8 budget headroom under the $3 cap).

---

## Risks and open points

- **Phase 8's budget headroom.** The live pipeline uses most of the $3 cap on a busy day, and Phase 8's per-frame SAM confirmations will need room under it. Phase 8 should give the alerts their own tagged budget or raise the cap with the user's OK.
- **A missed daily visit.** The Space sleeps after 48 h; the next visit restarts it and ingest catches up on 24 h, so a gap over 24 h stays in the dashboard's history. `vigil-backfill` cannot run inside the Space. If it happens during the judging window, upgrading to `CPU Upgrade` (never sleeps) needs the owner's OK.
- **The 2 vCPU of `cpu-basic`.** Three Python processes share them, and SAM mask decoding is pure Python (about 11 min for 168 masks on this PC). If the pipeline falls behind the hour, the run log shows it; the same `CPU Upgrade` has 8 vCPU.
- **`sync_bucket` and `list_bucket_tree` semantics** are read from signatures and docs, not yet exercised. Task 9, Step 2 runs them against the real bucket before anything depends on them.
- **The first start's race** is avoided by the catch-up (`vigil-ingest --once`) that runs before the pipeline starts. After a restart the restored frames are only minutes behind, so at worst one window is tracked a few frames short.
- **The Hub's network.** AshCam, Open-Meteo and the Meta API must answer from it. Task 10, Step 4 shows it through the cameras' `minutes_ago`.

## Execution notes

### Execution notes (2026-11-01, session 10)

**Commits.**

| Task | Commits |
|---|---|
| Plan | 345d703 |
| 1 | e22481e |
| 2 | 2dd87e8 |
| 3 | b0dbac5 |
| 4 | c718887, and c918c0c and 8ffb0c6 for the review |
| 5 | d7ee124, and c918c0c for the review |
| 6 | a9fcccd, plus 73e53af |
| 7 | 6bb6c2d, plus 629ca8f |
| 8–10 | no code: the mirror, the bucket, the Space and its secrets, the first deploy of 629ca8f |

The suite went from 556 to 597 tests.

**Deviations from the plan.**
- **The bucket API**, probed against the real bucket before Task 4 was written:
  - `list_bucket_tree(bucket)` with `recursive` left at None returns every file with its full path (`db/vigil.sqlite`), not the top-level folders. With the plan's code, `restore` would have reported a first start on every restart, and the next save would have overwritten the good state and the day's ledger. `restore` passes `recursive=False`, and `FakeBucket` mimics both behaviours, so the round-trip test fails without it.
  - `sync_bucket` prints a sync plan on every call; it runs with `quiet=True`.
  - `download_bucket_files` skips a missing file silently by default; `restore` passes `raise_on_missing_files=True`.
  - `sync_bucket` from a prefix the bucket lacks prints "Nothing to sync." and returns.
- **Review fixes (Tasks 4–5):**
  - `stage` wrote the Space's front matter with CRLF on Windows; it now writes LF.
  - `backup` leaves out `*.jpg.part` files, which `FrameStore` renames once written.
  - `committed_tree` runs git at the repository root, whatever the current directory.
- **`deploy/start.sh`** (review of Task 6, then 73e53af):
  - `supervise` passes a TERM on to the service it runs.
  - `stop` stops ingest and the pipeline before the saver's last save, so the saved database and files agree. A dashboard that exits also gets that last save.
  - This was checked by running `start.sh` under Git Bash with stub services: the services stop, then the final save runs, then the dashboard stops, and nothing is left running. A crashing service restarts every 10 s.
- `HF_HUB_DISABLE_PROGRESS_BARS=1` is in the image, so the restore and the mirror pull do not fill the log.
- Docker Desktop was not running here, so the first build was the Hub's.
- **The first start tracks only from the pipeline's start hour.** Windows begin at `started_at`, so the "≤ $0.25 for the last 3 closed hours" never happened.
- **The bucket also holds the episode 55 frames**, about 250 MB more than needed, because the mirror puts them under `frames/`. This is harmless: `restore` downloads them once more at each start, in seconds.
- **"Protected" hides the Space's Hub page too** (401 anonymously), not only its code. Share `https://facurie-volcano-vigil.hf.space`.

**Measured.**
- **Mirror:**
  - 510 files, 256.6 MB. The push took 28 s.
  - An anonymous pull took 2 min 19 s from home and 22 s on the Space.
  - SHA-256 and row counts are identical: 468 frames, 804 detections, 492 measurements, 7 bulletins, 78 ticks.
- **Bucket round trip:** backup 6.4 s, restore 6.8 s.
- **Build:** about 40 s (queued 15:46:09Z, image pushed 15:46:46Z). The Space was RUNNING at 15:47:33Z.
- **First start:**
  - The restore found no state ("first start") in 13 s, and the mirror pull took 22 s.
  - The dashboard answered 37 s after the container started.
  - The catch-up took 10 min: K2 7 min, then KP and F1 3 min. Afterwards K2 and KP were 3 min old and F1 4 min, all "usable".
- **First pipeline steps:**
  - The first step assessed 122 frames (88 usable).
  - The 16:07Z step tracked K2 15:00–15:59 (53 detections) and wrote bulletin 1, verified. It took 8 min.
- **Spend in the first hour:** $0.1624.
  - Agent run 1: $0.1324, of which 7 turns $0.060, 4 `assess_frame` $0.037, 3 SAM windows (KP) $0.030 and 2 segmentations $0.005.
  - The pipeline's SAM windows (K2): $0.030.
- **Restart test:**
  - The dashboard answered 32 s after `restart_space`. The restore of 643 MB (1,488 files) took 28 s, and the mirror was already up to date (3 s).
  - The log said "state restored". Bulletin 1, the earlier frames and the ledger ($0.1624, 19 calls) came back.
  - The K2 frame captured during the restart was ingested.

**Learned.**
- **A live agent run costs about $0.13**, against the $0.03–0.08 estimate; it is close to the replay's $0.147 per bulletin. At that rate the pipeline spends about $3.5–4 a day, and the $3 cap stops calls late in the UTC day (about 09:00–14:00 HST). Phase 8 needs headroom anyway: raising the cap or writing bulletins less often is the owner's call.
- **On Windows, `pip install -e` fails while a `vigil-*.exe` runs** (WinError 32 on the script). It leaves a `~olcano_vigil-*.dist-info` folder and a broken install. Rerun it when nothing runs, and do not reinstall while another agent runs a CLI.
- **The Space's run log is an SSE stream that never idles.** A reader has to stop on wall time, not on a read timeout.
- **The cap is now $5 a UTC day** (2026-11-01, the owner's OK after these numbers). The hourly bulletins stay, and Phase 8's alerts get headroom.
