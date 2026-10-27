# Phase 1: AshCam, SAM Prompt Tuning, Overlay Legend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill exact-timestamp frames from the USGS AshCam archive (episode 55 KP/K2/V1), decide whether AshCam should also feed live polling, choose SAM 3.1 phrases per target and camera kind (`config/prompts.yaml`), and move the overlay legend into a strip below the frame.

**Architecture:** The frame-storage half of `Ingestor` moves into a shared `FrameStore` (`vigia/ingest/store.py`), so the live `M.jpg` poller and the new AshCam client (`vigia/ingest/ashcam.py`) store frames the same way: SHA-256 de-duplication, files under `data/frames/`, rows in `frames`. AshCam frames carry `timestamp_source='ashcam'`. Prompt tuning is a script over episode 55 frames whose verdicts land in `docs/research/prompt_tuning.md` and whose winning phrases land in `config/prompts.yaml`, read by `vigia/prompts.py`. Every Meta call still goes through `MetaClient`.

**Tech Stack:** Python 3.12, httpx (`MockTransport` in tests), Pillow, numpy, pydantic, PyYAML, pytest, SAM 3.1 through `MetaClient`.

**Spec:** Phase 1 of [docs/PLAN.md](../../PLAN.md).

---

## Facts this plan relies on (checked live on 2026-10-27)

- AshCam index: `GET https://volcview.wr.usgs.gov/ashcam-api/imageApi/webcam?webcamCode=<code>&startTimestamp=<epoch>&endTimestamp=<epoch>&order=ASC&limit=0` returns `{images, webcam, meta}`. Each image has `imageTimestamp` (Unix seconds, UTC), `md5` and `imageUrl` (note the `webcams//` double slash). The list comes back **newest first** despite `order=ASC`.
- AshCam files are **byte-identical** to the public `M.jpg` of the same capture (same SHA-256 and MD5; checked on K2cam and KPcam), and `imageTimestamp` equals the capture time in the camera's `js.js`. So SHA-256 de-duplication works across both sources.
- One sample at 16:48 UTC: the newest AshCam frame was 1 min old (V1), 2 min (K2), 3 min (KP; 5-min cadence) and 9 min (F1). The newest `M.jpg` captures were 8–13 min old. F1's `M.jpg` capture of 16:48:13 had **no** AshCam frame within ±60 s: F1 is archived sparsely.
- Episode 55 frames already on disk: `data/raw/usgs_ep55/ashcam/<code>/<code>-<epoch>.jpg` (KP 78, K2 195, V1 195, V2 194, V3 195) and the F1 still `data/raw/usgs_ep55/20261017060125M_F1.jpg`.
- `datetime.fromisoformat` (3.12) parses `2026-10-17T13:00Z` and `2026-10-17T03:19-10:00`; a string without offset parses as naive.
- SAM image calls cost $0.0025 each.

## File structure

| File | Responsibility |
|---|---|
| `vigia/timeutil.py` (modify) | add `parse_utc`: ISO-8601 with explicit offset → UTC |
| `vigia/ingest/store.py` (create) | `FrameStore`, `IngestResult`: validate, de-dup, write and index frames; per-camera polling state |
| `vigia/ingest/fetch.py` (modify) | `Ingestor` keeps only the HTTP side (conditional GET, Last-Modified) and uses `FrameStore`; `describe_error` |
| `vigia/ingest/ashcam.py` (create) | `AshcamClient` (list, fetch with MD5 check), `backfill()`, `BackfillReport`, `AshcamIngestor` (live, Task 13), `vigia-backfill` CLI |
| `vigia/ingest/worker.py` (modify) | build `Ingestor` with a `FrameStore`; `SourceRouter` (Task 13) |
| `vigia/config.py` (modify) | `Camera.ashcam_code`, `CameraKind`, `Camera.live_source` (Task 13) |
| `config/sources.yaml` (modify) | `ashcam_code` for the 8 USGS cameras; `live_source` (Task 13) |
| `vigia/overlay.py` (modify) | legend strip below the frame; `min_legend_rows` |
| `vigia/imaging.py` (create) | `load_for_upload`: EXIF rotation, size cap, JPEG bytes (moved out of the smoke test) |
| `vigia/prompts.py` (create) | `Prompts`, `load_prompts`: SAM phrases per target and camera kind |
| `config/prompts.yaml` (create) | the chosen phrases |
| `scripts/measure_ashcam_latency.py` (create) | AshCam vs `M.jpg` freshness measurement |
| `scripts/tune_prompts.py` (create) | SAM phrase comparison on episode 55 frames |
| `scripts/smoke_test.py` (modify) | use `FrameStore`, `vigia.imaging`, `min_legend_rows` |
| `tests/fixtures/ashcam_index_kp.json` (create) | trimmed copy of the real KP index (3 frames, 04:50–05:00 HST) |
| `tests/test_timeutil.py`, `tests/test_store.py`, `tests/test_ashcam.py`, `tests/test_imaging.py`, `tests/test_prompts.py` (create) | tests |
| `tests/test_ingest.py`, `tests/test_worker.py`, `tests/test_config.py`, `tests/test_overlay.py` (modify) | tests |
| `docs/research/ashcam_latency.md`, `docs/research/prompt_tuning.md` (create) | evidence and decisions |

Scripts follow the `scripts/smoke_test.py` precedent: they are thin wrappers over tested package code, checked with a dry or short run, and have no unit tests of their own.

Run every test command from the repo root. Commit messages follow the repo style (imperative, sentence case) and carry **no** `Co-Authored-By` trailer.

---

### Task 1: `parse_utc` for explicit-offset timestamps

**Files:**
- Modify: `vigia/timeutil.py`
- Create: `tests/test_timeutil.py`

- [x] **Step 1: Write the failing tests**

```python
from datetime import datetime, timezone

import pytest

from vigia.timeutil import parse_utc, to_iso


def test_parse_utc_reads_a_z_suffix_without_seconds():
    assert parse_utc("2026-10-17T13:00Z") == datetime(2026, 10, 17, 13, 0, tzinfo=timezone.utc)


def test_parse_utc_converts_other_offsets_to_utc():
    parsed = parse_utc("2026-10-17T03:19-10:00")

    assert parsed == datetime(2026, 10, 17, 13, 19, tzinfo=timezone.utc)
    assert parsed.tzinfo == timezone.utc


def test_parse_utc_reads_back_what_to_iso_writes():
    moment = datetime(2026, 10, 17, 14, 50, 5, tzinfo=timezone.utc)

    assert parse_utc(to_iso(moment)) == moment


def test_parse_utc_rejects_a_time_without_offset():
    with pytest.raises(ValueError, match="offset"):
        parse_utc("2026-10-17T13:00")
```

- [x] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_timeutil.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_utc'`

- [x] **Step 3: Implement**

Append to `vigia/timeutil.py`:

```python
def parse_utc(value: str) -> datetime:
    """Parse an ISO-8601 time that states its offset ('2026-10-17T13:00Z', '...-10:00') into UTC."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError(f"time {value!r} has no UTC offset; end it with Z (UTC) or e.g. -10:00 (HST)")
    return dt.astimezone(timezone.utc)
```

- [x] **Step 4: Run them to see them pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_timeutil.py -v`
Expected: 4 passed

- [x] **Step 5: Commit**

```bash
git add vigia/timeutil.py tests/test_timeutil.py
git commit -m "Parse ISO times with an explicit UTC offset"
```

---

### Task 2: Extract `FrameStore` from `Ingestor`

The live poller and the AshCam client must store frames identically. Move validation, de-duplication, file writing, the `frames` insert and the `camera_state` update out of `Ingestor` into `FrameStore`. Behaviour of `Ingestor` does not change: the existing `tests/test_ingest.py` assertions are the safety net.

**Files:**
- Create: `vigia/ingest/store.py`, `tests/test_store.py`
- Modify: `vigia/ingest/fetch.py`, `vigia/ingest/worker.py`, `scripts/smoke_test.py`, `tests/test_ingest.py`, `tests/test_worker.py`

- [x] **Step 1: Write the failing store tests** (`tests/test_store.py`)

```python
from datetime import datetime, timedelta, timezone

import pytest

from conftest import NOW, make_jpeg
from vigia.ingest.store import FrameStore

CAPTURED = datetime(2026, 10, 17, 14, 50, 5, tzinfo=timezone.utc)


@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def add(store, body, captured_at=CAPTURED, source="ashcam", camera_id="kilauea-kp"):
    return store.add(camera_id, body, captured_at=captured_at, timestamp_source=source, fetched_at=NOW)


def test_add_writes_the_file_and_returns_the_new_frame_id(store, conn, tmp_path):
    body = make_jpeg()

    frame_id = add(store, body)

    row = conn.execute("SELECT * FROM frames WHERE id = ?", (frame_id,)).fetchone()
    assert (row["captured_at"], row["timestamp_source"]) == ("2026-10-17T14:50:05Z", "ashcam")
    assert (tmp_path / row["path"]).read_bytes() == body


def test_add_returns_none_for_bytes_the_camera_already_has(store):
    body = make_jpeg()
    add(store, body)

    assert add(store, body, captured_at=CAPTURED + timedelta(minutes=5)) is None


def test_add_rejects_a_body_that_is_not_an_image(store):
    with pytest.raises(ValueError, match="image"):
        add(store, b"<html>not found</html>")


def test_has_capture_matches_camera_time_and_timestamp_source(store):
    add(store, make_jpeg())

    assert store.has_capture("kilauea-kp", CAPTURED, "ashcam")
    assert not store.has_capture("kilauea-kp", CAPTURED, "http_last_modified")
    assert not store.has_capture("kilauea-k2", CAPTURED, "ashcam")


def test_latest_capture_is_the_newest_frame_from_that_source(store):
    add(store, make_jpeg(color=(200, 80, 40)), captured_at=CAPTURED)
    add(store, make_jpeg(color=(40, 200, 80)), captured_at=CAPTURED + timedelta(minutes=5))
    add(store, make_jpeg(color=(80, 40, 200)), captured_at=CAPTURED + timedelta(hours=1), source="http_last_modified")

    assert store.latest_capture("kilauea-kp", "ashcam") == CAPTURED + timedelta(minutes=5)
    assert store.latest_capture("kilauea-k2", "ashcam") is None
```

- [x] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigia.ingest.store'`

- [x] **Step 3: Create `vigia/ingest/store.py`**

```python
"""Ingest persistence shared by every frame source.

A frame must be a complete JPEG or PNG. It is dropped when the camera already
has the same bytes (SHA-256); otherwise it is written under
`<data_dir>/frames/<camera>/<UTC day>/` and recorded in the `frames` table.
The outcome of each poll is kept per camera in `camera_state`.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from PIL import Image

from vigia.timeutil import parse_utc, to_iso

log = logging.getLogger(__name__)

Status = Literal["new", "duplicate", "not_modified", "error"]

_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png"}


@dataclass(frozen=True)
class IngestResult:
    camera_id: str
    status: Status
    frame_id: int | None = None
    error: str | None = None


class FrameStore:
    def __init__(self, conn: sqlite3.Connection, data_dir: str | Path):
        self._conn = conn
        self._data_dir = Path(data_dir)

    def add(
        self,
        camera_id: str,
        body: bytes,
        *,
        captured_at: datetime,
        timestamp_source: str,
        fetched_at: datetime,
    ) -> int | None:
        """Store a frame and return its id, or None if the camera already has these bytes.

        Raises ValueError if the body is not a complete JPEG or PNG image.
        """
        extension, width, height = _decode_image(body)
        sha256 = hashlib.sha256(body).hexdigest()
        if self._is_known(camera_id, sha256):
            return None
        rel_path = self._write(camera_id, captured_at, sha256, extension, body)
        cursor = self._conn.execute(
            """INSERT INTO frames (camera_id, captured_at, timestamp_source, fetched_at,
                                   sha256, path, bytes, width, height)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (camera_id, to_iso(captured_at), timestamp_source, to_iso(fetched_at),
             sha256, rel_path, len(body), width, height),
        )
        self._conn.commit()
        log.info("camera %s: new frame %s (%s)", camera_id, rel_path, timestamp_source)
        return cursor.lastrowid

    def has_capture(self, camera_id: str, captured_at: datetime, timestamp_source: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM frames WHERE camera_id = ? AND captured_at = ? AND timestamp_source = ?",
            (camera_id, to_iso(captured_at), timestamp_source),
        ).fetchone()
        return row is not None

    def latest_capture(self, camera_id: str, timestamp_source: str) -> datetime | None:
        row = self._conn.execute(
            "SELECT MAX(captured_at) AS latest FROM frames WHERE camera_id = ? AND timestamp_source = ?",
            (camera_id, timestamp_source),
        ).fetchone()
        return parse_utc(row["latest"]) if row["latest"] else None

    def validators(self, camera_id: str) -> tuple[str | None, str | None]:
        """The ETag and Last-Modified the camera's server last sent, to send back as conditions."""
        row = self._conn.execute(
            "SELECT etag, last_modified FROM camera_state WHERE camera_id = ?", (camera_id,)
        ).fetchone()
        return (row["etag"], row["last_modified"]) if row else (None, None)

    def record_check(
        self,
        camera_id: str,
        checked_at: datetime,
        status: Status,
        frame_id: int | None = None,
        error: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> IngestResult:
        """Update the camera's polling state with the outcome of one check."""
        checked = to_iso(checked_at)
        self._conn.execute("INSERT OR IGNORE INTO camera_state (camera_id) VALUES (?)", (camera_id,))
        self._conn.execute(
            """UPDATE camera_state SET
                   last_checked_at = :checked,
                   last_status = :status,
                   last_error = :error,
                   last_new_frame_at = CASE WHEN :status = 'new' THEN :checked ELSE last_new_frame_at END,
                   consecutive_errors = CASE WHEN :status = 'error' THEN consecutive_errors + 1 ELSE 0 END,
                   consecutive_unchanged = CASE
                       WHEN :status = 'new' THEN 0
                       WHEN :status IN ('duplicate', 'not_modified') THEN consecutive_unchanged + 1
                       ELSE consecutive_unchanged END,
                   etag = COALESCE(:etag, etag),
                   last_modified = COALESCE(:last_modified, last_modified)
               WHERE camera_id = :camera_id""",
            {"checked": checked, "status": status, "error": error, "etag": etag,
             "last_modified": last_modified, "camera_id": camera_id},
        )
        self._conn.commit()
        return IngestResult(camera_id, status, frame_id=frame_id, error=error)

    def _is_known(self, camera_id: str, sha256: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM frames WHERE camera_id = ? AND sha256 = ?", (camera_id, sha256)
        ).fetchone()
        return row is not None

    def _write(self, camera_id: str, captured_at: datetime, sha256: str, extension: str, body: bytes) -> str:
        rel_path = (
            f"frames/{camera_id}/{captured_at:%Y-%m-%d}/"
            f"{captured_at:%Y%m%dT%H%M%SZ}_{sha256[:8]}{extension}"
        )
        target = self._data_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        partial.write_bytes(body)
        os.replace(partial, target)
        return rel_path


def _decode_image(body: bytes) -> tuple[str, int, int]:
    """Fully decode the body to reject HTML error pages and truncated JPEGs."""
    try:
        with Image.open(io.BytesIO(body)) as img:
            img.load()
            image_format, width, height = img.format, img.width, img.height
    except Exception as exc:  # Pillow raises several unrelated types for bad data
        raise ValueError(f"not a valid image: {exc}") from exc
    if image_format not in _EXTENSIONS:
        raise ValueError(f"unsupported image format: {image_format}")
    return _EXTENSIONS[image_format], width, height
```

- [x] **Step 4: Run the store tests to see them pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_store.py -v`
Expected: 5 passed

- [x] **Step 5: Point the ingest tests at the new constructor**

In `tests/test_ingest.py` replace the import line and fixture:

```python
from vigia.ingest.fetch import Ingestor
from vigia.ingest.store import FrameStore
```

```python
@pytest.fixture
def ingestor(conn, server, tmp_path):
    return Ingestor(FrameStore(conn, tmp_path), http=server.client(), now=lambda: NOW)
```

In `tests/test_worker.py` replace `from vigia.ingest.fetch import IngestResult` with `from vigia.ingest.store import IngestResult`.

Run: `.venv/Scripts/python.exe -m pytest tests/test_ingest.py -v`
Expected: FAIL (`Ingestor.__init__()` takes a store now in the tests but not yet in the code)

- [x] **Step 6: Rewrite `vigia/ingest/fetch.py` on top of `FrameStore`**

```python
"""Download one camera image, timestamp it, drop duplicates, and store it.

Capture time comes from the HTTP Last-Modified header when the server sends
one; otherwise the fetch time is used. `timestamp_source` records which, so the
quality filter can later cross-check against the timestamp burned into the
image.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

import httpx

from vigia.config import Camera
from vigia.ingest.store import FrameStore, IngestResult
from vigia.timeutil import parse_http_date, utcnow

log = logging.getLogger(__name__)


class Ingestor:
    def __init__(self, store: FrameStore, http: httpx.Client, now: Callable[[], datetime] = utcnow):
        self._store = store
        self._http = http
        self._now = now

    def ingest(self, camera: Camera) -> IngestResult:
        fetched_at = self._now()
        try:
            response = self._http.get(camera.url, headers=self._conditional_headers(camera.id))
            if response.status_code == 304:
                return self._store.record_check(camera.id, fetched_at, "not_modified")
            response.raise_for_status()
            validators = {"etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified")}
            captured_at = parse_http_date(validators["last_modified"])
            timestamp_source = "http_last_modified" if captured_at else "fetched_at"
            frame_id = self._store.add(camera.id, response.content, captured_at=captured_at or fetched_at,
                                       timestamp_source=timestamp_source, fetched_at=fetched_at)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("camera %s: %s", camera.id, describe_error(exc))
            return self._store.record_check(camera.id, fetched_at, "error", error=describe_error(exc))
        status = "new" if frame_id is not None else "duplicate"
        return self._store.record_check(camera.id, fetched_at, status, frame_id=frame_id, **validators)

    def _conditional_headers(self, camera_id: str) -> dict[str, str]:
        etag, last_modified = self._store.validators(camera_id)
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        return headers


def describe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: {exc}"
```

- [x] **Step 7: Update the two other `Ingestor` callers**

`vigia/ingest/worker.py`: replace the import `from vigia.ingest.fetch import IngestResult, Ingestor` with

```python
from vigia.ingest.fetch import Ingestor
from vigia.ingest.store import FrameStore, IngestResult
```

and in `main()` replace `worker = Worker(Ingestor(conn, settings.data_dir, http), sources.cameras)` with

```python
        worker = Worker(Ingestor(FrameStore(conn, settings.data_dir), http), sources.cameras)
```

`scripts/smoke_test.py`: add `from vigia.ingest.store import FrameStore` after the `vigia.ingest.fetch` import, and in `fetch_live_frame` replace `Ingestor(conn, settings.data_dir, http)` with `Ingestor(FrameStore(conn, settings.data_dir), http)`.

- [x] **Step 8: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 62 passed (53 before + 4 timeutil + 5 store)

- [x] **Step 9: Commit**

```bash
git add vigia/ingest/store.py vigia/ingest/fetch.py vigia/ingest/worker.py scripts/smoke_test.py tests/test_store.py tests/test_ingest.py tests/test_worker.py
git commit -m "Extract FrameStore so every frame source stores frames the same way"
```

---

### Task 3: `ashcam_code` on cameras

**Files:**
- Modify: `vigia/config.py`, `config/sources.yaml`, `tests/test_config.py`

- [x] **Step 1: Write the failing tests** (append to `tests/test_config.py`; add `from pathlib import Path` to its imports)

```python
REPO = Path(__file__).resolve().parent.parent


def test_ashcam_code_is_optional(tmp_path):
    text = VALID.replace("    enabled: true\n    poll_minutes: 5",
                         "    enabled: true\n    poll_minutes: 5\n    ashcam_code: kilauea-v1-cam")

    sources = load_sources(write(tmp_path, text))

    assert sources.cameras[0].ashcam_code == "kilauea-v1-cam"
    assert sources.cameras[1].ashcam_code is None


def test_committed_sources_keep_sgc_disabled_and_name_every_usgs_archive():
    sources = load_sources(REPO / "config" / "sources.yaml")

    assert [c.id for c in sources.cameras if c.volcano == "nevado-del-ruiz" and c.enabled] == []
    assert [c.id for c in sources.cameras if c.volcano == "kilauea" and not c.ashcam_code] == []
```

- [x] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: FAIL: `ashcam_code` is not a field (`AttributeError`), and the committed file lists Kīlauea cameras without one

- [x] **Step 3: Add the field**

In `vigia/config.py`, add after `kind`:

```python
    ashcam_code: str | None = None  # USGS AshCam archive code, e.g. kilauea-kp-cam
```

and extend the module docstring's last sentence:

```python
"""Camera and volcano definitions loaded from a YAML sources file.

Every camera must declare its license and attribution. Cameras are disabled
unless explicitly enabled, so a source without permission can live in the
config without ever being fetched. USGS cameras also name their AshCam
archive (`ashcam_code`), from which `vigia-backfill` downloads past frames.
"""
```

- [x] **Step 4: Name the archive of every USGS camera in `config/sources.yaml`**

Add one line after each Kīlauea camera's `attribution:` line:

| camera id | line to add |
|---|---|
| kilauea-v1 | `    ashcam_code: kilauea-v1-cam` |
| kilauea-k2 | `    ashcam_code: kilauea-k2-cam` |
| kilauea-v2 | `    ashcam_code: kilauea-v2-cam` |
| kilauea-v3 | `    ashcam_code: kilauea-v3-cam` |
| kilauea-kw | `    ashcam_code: kilauea-kw-cam` |
| kilauea-b1 | `    ashcam_code: kilauea-b1-cam` |
| kilauea-kp | `    ashcam_code: kilauea-kp-cam` |
| kilauea-f1 | `    ashcam_code: kilauea-f1-cam` |

and add to the header comment:

```yaml
# `ashcam_code` names the camera in the USGS AshCam archive (about 31 days of
# frames with exact capture times); `vigia-backfill` downloads from it.
```

- [x] **Step 5: Run the tests to see them pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: 7 passed

- [x] **Step 6: Commit**

```bash
git add vigia/config.py config/sources.yaml tests/test_config.py
git commit -m "Name each USGS camera's AshCam archive in the sources config"
```

---

### Task 4: `AshcamClient`: list archived frames and fetch them with an MD5 check

**Files:**
- Create: `tests/fixtures/ashcam_index_kp.json`, `tests/test_ashcam.py`, `vigia/ingest/ashcam.py`

- [x] **Step 1: Save the trimmed real index** as `tests/fixtures/ashcam_index_kp.json` (3 KP frames from the real episode 55 index, newest first as the API returns them; `webcam` trimmed to its main fields; `meta` adjusted to the 3 frames):

```json
{
  "images": [
    {
      "imageId": 49796430,
      "md5": "fa85ba29afd10c7a4912e3382b9eb4c5",
      "webcamCode": "kilauea-kp-cam",
      "newestForWebcam": "N",
      "imageTimestamp": 1792249205,
      "imageDate": "Sat, 17 Oct 2026 15:00:05 +0000",
      "isNighttimeInd": "?",
      "interestingCode": "U",
      "imageUrl": "https://volcview.wr.usgs.gov/ashcam-api/images/webcams//kilauea-kp-cam/2026/289/kilauea-kp-cam-1792249205.jpg",
      "suninfo": null
    },
    {
      "imageId": 49796287,
      "md5": "17249a1ad6d2ce3330b1d7638d57dac4",
      "webcamCode": "kilauea-kp-cam",
      "newestForWebcam": "N",
      "imageTimestamp": 1792248905,
      "imageDate": "Sat, 17 Oct 2026 14:55:05 +0000",
      "isNighttimeInd": "?",
      "interestingCode": "U",
      "imageUrl": "https://volcview.wr.usgs.gov/ashcam-api/images/webcams//kilauea-kp-cam/2026/289/kilauea-kp-cam-1792248905.jpg",
      "suninfo": null
    },
    {
      "imageId": 49796233,
      "md5": "073fbbd1269772c6595c73bb397057bc",
      "webcamCode": "kilauea-kp-cam",
      "newestForWebcam": "N",
      "imageTimestamp": 1792248605,
      "imageDate": "Sat, 17 Oct 2026 14:50:05 +0000",
      "isNighttimeInd": "?",
      "interestingCode": "U",
      "imageUrl": "https://volcview.wr.usgs.gov/ashcam-api/images/webcams//kilauea-kp-cam/2026/289/kilauea-kp-cam-1792248605.jpg",
      "suninfo": null
    }
  ],
  "webcam": {
    "webcamCode": "kilauea-kp-cam",
    "webcamName": "kilauea-kp-cam",
    "latitude": 0,
    "longitude": 0,
    "elevationM": 0,
    "bearingDeg": 0,
    "hasImages": "Y",
    "imageTotal": 8438,
    "firstImageTimestamp": 1790455205,
    "lastImageTimestamp": 1793046908,
    "currentImageUrl": "https://volcview.wr.usgs.gov/ashcam-api/images/webcams/kilauea-kp-cam/current.jpg",
    "timezone": "UTC"
  },
  "meta": {
    "imageTotal": 3,
    "firstImageTimestamp": 1792248605,
    "lastImageTimestamp": 1792249205,
    "apiUrl": "https://volcview.wr.usgs.gov/ashcam-api/imageApi/webcam?webcamCode=kilauea-kp-cam&startTimestamp=1792248600&endTimestamp=1792249300&order=ASC&limit=0",
    "querySec": 0
  }
}
```

The tests replace each `md5` with the MD5 of a generated JPEG: no real image enters the repo.

- [x] **Step 2: Write the failing tests** (`tests/test_ashcam.py`)

```python
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from conftest import make_jpeg
from vigia.ingest.ashcam import AshcamClient, ChecksumMismatch

INDEX = Path(__file__).parent / "fixtures" / "ashcam_index_kp.json"
START = datetime(2026, 10, 17, 14, 50, tzinfo=timezone.utc)  # 04:50 HST
END = datetime(2026, 10, 17, 15, 1, tzinfo=timezone.utc)
COLORS = [(200, 80, 40), (40, 200, 80), (80, 40, 200)]


class FakeAshcam:
    """Serves the trimmed KP index with a distinct small JPEG per image, and records every request."""

    def __init__(self):
        self.index = json.loads(INDEX.read_text(encoding="utf-8"))
        self.bodies = {}
        for item, color in zip(self.index["images"], COLORS):
            body = make_jpeg(color=color)
            item["md5"] = hashlib.md5(body).hexdigest()
            self.bodies[item["imageUrl"]] = body
        self.list_status = 200
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/imageApi/webcam"):
            return httpx.Response(self.list_status, json=self.index)
        body = self.bodies.get(str(request.url))
        return httpx.Response(200, content=body) if body is not None else httpx.Response(404)

    def list_requests(self):
        return [r for r in self.requests if r.url.path.endswith("/imageApi/webcam")]

    def image_requests(self):
        return [r for r in self.requests if r.url.path.endswith(".jpg")]


@pytest.fixture
def archive():
    return FakeAshcam()


@pytest.fixture
def client(archive):
    return AshcamClient(httpx.Client(transport=httpx.MockTransport(archive)))


def test_list_images_asks_for_the_camera_and_window_in_epoch_seconds(client, archive):
    client.list_images("kilauea-kp-cam", START, END)

    [request] = archive.list_requests()
    assert request.url.path == "/ashcam-api/imageApi/webcam"
    assert dict(request.url.params) == {
        "webcamCode": "kilauea-kp-cam", "startTimestamp": "1792248600", "endTimestamp": "1792249260",
        "order": "ASC", "limit": "0",
    }


def test_list_images_returns_exact_capture_times_oldest_first(client):
    images = client.list_images("kilauea-kp-cam", START, END)

    assert [i.timestamp for i in images] == [
        datetime(2026, 10, 17, 14, 50, 5, tzinfo=timezone.utc),
        datetime(2026, 10, 17, 14, 55, 5, tzinfo=timezone.utc),
        datetime(2026, 10, 17, 15, 0, 5, tzinfo=timezone.utc),
    ]
    assert images[0].webcam_code == "kilauea-kp-cam"
    assert images[0].url.endswith("/kilauea-kp-cam-1792248605.jpg")


def test_list_images_raises_when_the_archive_fails(client, archive):
    archive.list_status = 503

    with pytest.raises(httpx.HTTPStatusError):
        client.list_images("kilauea-kp-cam", START, END)


def test_fetch_returns_the_image_when_its_md5_matches(client, archive):
    image = client.list_images("kilauea-kp-cam", START, END)[0]

    assert client.fetch(image) == archive.bodies[image.url]


def test_fetch_rejects_an_image_whose_md5_does_not_match(client, archive):
    image = client.list_images("kilauea-kp-cam", START, END)[0]
    archive.bodies[image.url] = b"truncated"

    with pytest.raises(ChecksumMismatch, match="MD5"):
        client.fetch(image)
```

- [x] **Step 3: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ashcam.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigia.ingest.ashcam'`

- [x] **Step 4: Create `vigia/ingest/ashcam.py`**

```python
"""USGS AshCam archive: list a webcam's archived frames and store them.

AshCam (https://volcview.wr.usgs.gov/ashcam-gui/webcam.html) keeps the USGS
volcano webcams' frames for about 31 days at their internal cadence (2 min;
KPcam 5 min). The index gives each frame's capture time as a Unix epoch and
its MD5. The files are byte-identical to the public M.jpg of the same capture,
so frames stored from here get exact timestamps (`timestamp_source =
'ashcam'`) and de-duplicate against live polling. The API is undocumented; it
was read from the AshCam GUI's JavaScript (docs/research/episode55.md, §6).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

API_URL = "https://volcview.wr.usgs.gov/ashcam-api"


class ChecksumMismatch(ValueError):
    """A downloaded AshCam frame does not match the MD5 listed in the index."""


@dataclass(frozen=True)
class AshcamImage:
    webcam_code: str
    timestamp: datetime  # UTC capture time
    url: str
    md5: str


class AshcamClient:
    def __init__(self, http: httpx.Client, api_url: str = API_URL):
        self._http = http
        self._api_url = api_url

    def list_images(self, webcam_code: str, start: datetime, end: datetime) -> list[AshcamImage]:
        """Archived frames captured between `start` and `end`, oldest first."""
        response = self._http.get(f"{self._api_url}/imageApi/webcam", params={
            "webcamCode": webcam_code,
            "startTimestamp": int(start.timestamp()),
            "endTimestamp": int(end.timestamp()),
            "order": "ASC",
            "limit": 0,  # no limit
        })
        response.raise_for_status()
        images = [_parse_image(item) for item in response.json()["images"]]
        return sorted(images, key=lambda image: image.timestamp)  # the API answers newest first

    def fetch(self, image: AshcamImage) -> bytes:
        """Download one frame; raises ChecksumMismatch if it differs from the index MD5."""
        response = self._http.get(image.url)
        response.raise_for_status()
        if hashlib.md5(response.content, usedforsecurity=False).hexdigest() != image.md5:
            raise ChecksumMismatch(f"MD5 mismatch for {image.url}")
        return response.content


def _parse_image(item: dict[str, Any]) -> AshcamImage:
    return AshcamImage(
        webcam_code=item["webcamCode"],
        timestamp=datetime.fromtimestamp(item["imageTimestamp"], timezone.utc),
        url=item["imageUrl"],
        md5=item["md5"],
    )
```

- [x] **Step 5: Run them to see them pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ashcam.py -v`
Expected: 5 passed

- [x] **Step 6: Commit**

```bash
git add vigia/ingest/ashcam.py tests/test_ashcam.py tests/fixtures/ashcam_index_kp.json
git commit -m "Add AshCam client that lists archived frames and checks their MD5"
```

---

### Task 5: `backfill()`: store a camera's archived frames

**Files:**
- Modify: `vigia/ingest/ashcam.py`, `tests/test_ashcam.py`

- [x] **Step 1: Write the failing tests** (append to `tests/test_ashcam.py`; extend its imports with `from vigia.config import Camera`, `from vigia.ingest.ashcam import backfill` and `from vigia.ingest.store import FrameStore`)

```python
@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def kp_camera():
    return Camera(id="kilauea-kp", name="KPcam", volcano="kilauea", url="https://example.org/KPcam/images/M.jpg",
                  license="Public Domain", attribution="U.S. Geological Survey", ashcam_code="kilauea-kp-cam")


def stored(conn):
    return conn.execute("SELECT * FROM frames ORDER BY captured_at").fetchall()


def test_backfill_stores_each_frame_with_its_exact_ashcam_time(client, store, archive, conn, tmp_path):
    report = backfill(client, store, kp_camera(), START, END)

    rows = stored(conn)
    assert (report.listed, report.new) == (3, 3)
    assert [r["captured_at"] for r in rows] == ["2026-10-17T14:50:05Z", "2026-10-17T14:55:05Z", "2026-10-17T15:00:05Z"]
    assert {r["timestamp_source"] for r in rows} == {"ashcam"}
    assert {(tmp_path / r["path"]).read_bytes() for r in rows} == set(archive.bodies.values())
    assert report.frame_ids == [r["id"] for r in rows]


def test_backfill_skips_frames_it_already_stored_without_downloading_them(client, store, archive):
    backfill(client, store, kp_camera(), START, END)
    downloads = len(archive.image_requests())

    report = backfill(client, store, kp_camera(), START, END)

    assert (report.new, report.skipped) == (0, 3)
    assert len(archive.image_requests()) == downloads


def test_backfill_keeps_going_after_a_bad_download(client, store, archive):
    oldest = archive.index["images"][2]["imageUrl"]
    archive.bodies[oldest] = b"truncated"

    report = backfill(client, store, kp_camera(), START, END)

    assert report.new == 2
    assert len(report.errors) == 1 and "MD5" in report.errors[0]


def test_backfill_counts_repeated_bytes_as_duplicates(client, store, archive):
    newest, middle = archive.index["images"][:2]
    archive.bodies[middle["imageUrl"]] = archive.bodies[newest["imageUrl"]]
    middle["md5"] = newest["md5"]

    report = backfill(client, store, kp_camera(), START, END)

    assert (report.new, report.duplicate) == (2, 1)


def test_backfill_needs_an_ashcam_code(client, store):
    camera = kp_camera().model_copy(update={"ashcam_code": None})

    with pytest.raises(ValueError, match="ashcam_code"):
        backfill(client, store, camera, START, END)
```

- [x] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ashcam.py -v`
Expected: FAIL with `ImportError: cannot import name 'backfill'`

- [x] **Step 3: Implement** — in `vigia/ingest/ashcam.py` replace the imports with:

```python
from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from vigia.config import Camera
from vigia.ingest.fetch import describe_error
from vigia.ingest.store import FrameStore
from vigia.timeutil import utcnow

log = logging.getLogger(__name__)
```

and append after `AshcamClient`:

```python
@dataclass
class BackfillReport:
    listed: int = 0
    new: int = 0
    skipped: int = 0  # already stored from AshCam, so not downloaded again
    duplicate: int = 0  # bytes the camera already had (a frozen camera repeats its frame)
    errors: list[str] = field(default_factory=list)
    frame_ids: list[int] = field(default_factory=list)  # new frames, oldest first

    def summary(self) -> str:
        return (f"{self.listed} listed, {self.new} new, {self.skipped} already stored, "
                f"{self.duplicate} duplicate, {len(self.errors)} failed")


def backfill(
    client: AshcamClient,
    store: FrameStore,
    camera: Camera,
    start: datetime,
    end: datetime,
    now: Callable[[], datetime] = utcnow,
) -> BackfillReport:
    """Store every archived frame of `camera` captured between `start` and `end`.

    Frames already stored from AshCam are skipped without downloading them, so
    a window can be backfilled again. A failed download is reported and the
    rest continue; a failure to list the window raises.
    """
    if not camera.ashcam_code:
        raise ValueError(f"camera {camera.id} has no ashcam_code")
    report = BackfillReport()
    for image in client.list_images(camera.ashcam_code, start, end):
        report.listed += 1
        if store.has_capture(camera.id, image.timestamp, "ashcam"):
            report.skipped += 1
            continue
        try:
            frame_id = store.add(camera.id, client.fetch(image), captured_at=image.timestamp,
                                 timestamp_source="ashcam", fetched_at=now())
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("camera %s: %s", camera.id, describe_error(exc))
            report.errors.append(describe_error(exc))
            continue
        if frame_id is None:
            report.duplicate += 1
        else:
            report.new += 1
            report.frame_ids.append(frame_id)
    return report
```

- [x] **Step 4: Run them to see them pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ashcam.py -v`
Expected: 10 passed

- [x] **Step 5: Commit**

```bash
git add vigia/ingest/ashcam.py tests/test_ashcam.py
git commit -m "Backfill a camera's archived AshCam frames with exact timestamps"
```

---

### Task 6: `vigia-backfill` CLI

**Files:**
- Modify: `vigia/ingest/ashcam.py`, `pyproject.toml`, `tests/test_ashcam.py`

- [x] **Step 1: Write the failing tests** (append to `tests/test_ashcam.py`; add `from vigia.ingest.ashcam import main`)

```python
SOURCES = """
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
  - id: kilauea-s2
    name: S2cam
    volcano: kilauea
    url: https://example.org/S2cam/images/M.jpg
    license: Public Domain
    attribution: U.S. Geological Survey
"""
WINDOW = ["--start", "2026-10-17T13:00Z", "--end", "2026-10-17T19:30Z"]


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(SOURCES, encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigia.sqlite"))


def test_cli_refuses_a_camera_without_an_ashcam_code(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--camera", "kilauea-s2", *WINDOW])

    assert "ashcam_code" in capsys.readouterr().err


def test_cli_refuses_an_unknown_camera(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--camera", "etna-1", *WINDOW])

    assert "etna-1" in capsys.readouterr().err


def test_cli_refuses_times_without_an_offset(cli_env):
    with pytest.raises(SystemExit):
        main(["--camera", "kilauea-kp", "--start", "2026-10-17T13:00", "--end", "2026-10-17T19:30Z"])


def test_cli_refuses_an_empty_window(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--camera", "kilauea-kp", "--start", "2026-10-17T19:30Z", "--end", "2026-10-17T13:00Z"])

    assert "before" in capsys.readouterr().err
```

- [x] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ashcam.py -v`
Expected: FAIL with `ImportError: cannot import name 'main'`

- [x] **Step 3: Implement** — in `vigia/ingest/ashcam.py` add the imports `import argparse` and

```python
from vigia import db
from vigia.config import Camera, load_sources
from vigia.settings import Settings
from vigia.timeutil import parse_utc, utcnow
```

(replacing the narrower `vigia.config` and `vigia.timeutil` imports), and append:

```python
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download a camera's archived frames from USGS AshCam.")
    parser.add_argument("--camera", action="append", required=True,
                        help="camera id from the sources file; repeat it for several cameras")
    parser.add_argument("--start", type=parse_utc, required=True, help="first capture time, e.g. 2026-10-17T13:00Z")
    parser.add_argument("--end", type=parse_utc, required=True, help="last capture time, e.g. 2026-10-17T19:30Z")
    args = parser.parse_args(argv)
    if args.start >= args.end:
        parser.error("--start must be before --end")

    settings = Settings.from_env()
    cameras = {c.id: c for c in load_sources(settings.sources_path).cameras}
    for camera_id in args.camera:
        if camera_id not in cameras:
            parser.error(f"unknown camera {camera_id!r} in {settings.sources_path}")
        if not cameras[camera_id].ashcam_code:
            parser.error(f"camera {camera_id!r} has no ashcam_code in {settings.sources_path}")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    conn = db.connect(settings.db_path)
    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": settings.user_agent}) as http:
        client, store = AshcamClient(http), FrameStore(conn, settings.data_dir)
        for camera_id in args.camera:
            try:
                report = backfill(client, store, cameras[camera_id], args.start, args.end)
            except (httpx.HTTPError, ValueError) as exc:
                print(f"{camera_id}: could not list the archive ({describe_error(exc)})")
                continue
            print(f"{camera_id}: {report.summary()}")


if __name__ == "__main__":
    main()
```

In `pyproject.toml` `[project.scripts]` add:

```toml
vigia-backfill = "vigia.ingest.ashcam:main"
```

- [x] **Step 4: Run them to see them pass, then the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ashcam.py -v` → 14 passed
Run: `.venv/Scripts/python.exe -m pytest` → 78 passed

- [x] **Step 5: Register the console script**

Run: `.venv/Scripts/python.exe -m pip install -e ".[dev]" -q` then `.venv/Scripts/vigia-backfill.exe --help`
Expected: usage text listing `--camera`, `--start`, `--end`

- [x] **Step 6: Commit**

```bash
git add vigia/ingest/ashcam.py pyproject.toml tests/test_ashcam.py
git commit -m "Add vigia-backfill CLI to download archived frames for a time window"
```

---

### Task 7: Backfill episode 55 (KP, K2, V1)

Live network run, ~241 MB (78 + 195 + 195 frames). Run it in the background.

- [x] **Step 1: Run the backfill**

Run: `.venv/Scripts/vigia-backfill.exe --camera kilauea-kp --camera kilauea-k2 --camera kilauea-v1 --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z`
Expected last lines:

```
kilauea-kp: 78 listed, 78 new, 0 already stored, 0 duplicate, 0 failed
kilauea-k2: 195 listed, 195 new, 0 already stored, 0 duplicate, 0 failed
kilauea-v1: 195 listed, 195 new, 0 already stored, 0 duplicate, 0 failed
```

- [x] **Step 2: Verify timestamps and bytes**

Run:

```bash
.venv/Scripts/python.exe -c "
import hashlib, sqlite3
c = sqlite3.connect('data/vigia.sqlite')
for row in c.execute(\"SELECT camera_id, COUNT(*), MIN(captured_at), MAX(captured_at) FROM frames WHERE timestamp_source='ashcam' AND captured_at BETWEEN '2026-10-17T13:00:00Z' AND '2026-10-17T19:30:00Z' GROUP BY camera_id\"): print(row)
sha = c.execute(\"SELECT sha256 FROM frames WHERE camera_id='kilauea-kp' AND captured_at='2026-10-17T14:50:05Z'\").fetchone()[0]
raw = hashlib.sha256(open('data/raw/usgs_ep55/ashcam/kilauea-kp-cam/kilauea-kp-cam-1792248605.jpg','rb').read()).hexdigest()
print('KP 04:50:05 HST matches the raw copy:', sha == raw)
"
```

Expected: `('kilauea-k2', 195, '2026-10-17T13:00:02Z', '2026-10-17T19:28:02Z')`, `('kilauea-kp', 78, '2026-10-17T13:00:06Z', '2026-10-17T19:25:09Z')`, `('kilauea-v1', 195, '2026-10-17T13:01:04Z', '2026-10-17T19:29:02Z')` and `... matches the raw copy: True`.

- [x] **Step 3: Re-run to prove it is idempotent**

Run the Step 1 command again.
Expected: `78 listed, 0 new, 78 already stored, ...` (and 195/195 for the others), with no image downloads.

Nothing to commit (data is git-ignored).

---

### Task 8: Measure AshCam latency against `M.jpg`

**Files:**
- Create: `scripts/measure_ashcam_latency.py`

- [x] **Step 1: Write the script**

```python
"""Measure how fresh the USGS AshCam archive is next to the public M.jpg images.

Both sources serve the same JPEG for a capture. Every --interval seconds, for
each camera, this records the newest capture each source offers:
  - AshCam: the capture time (Unix epoch) of the newest archived frame;
  - M.jpg: the capture time in the sibling js.js file,
    e.g. var datetime = "2026-10-27 06:40:03 (HST)";
A capture first seen after a source's first poll has latency = time seen -
capture time. At the end it prints, per camera and source, the new captures,
the median and maximum latency and the median spacing between captures as a
markdown table, and saves every observation to data/latency/<UTC time>.json.

    python scripts/measure_ashcam_latency.py --minutes 40
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from datetime import datetime, timedelta, timezone

import httpx

from vigia.config import Camera, load_sources
from vigia.ingest.ashcam import AshcamClient
from vigia.settings import Settings
from vigia.timeutil import to_iso, utcnow

HST = timezone(timedelta(hours=-10))
JS_DATETIME = re.compile(r'var datetime\s*=\s*"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) \(HST\)"')
DEFAULT_CAMERAS = ["kilauea-kp", "kilauea-k2", "kilauea-f1", "kilauea-v1"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camera", action="append", help=f"camera id (default: {', '.join(DEFAULT_CAMERAS)})")
    parser.add_argument("--minutes", type=float, default=40)
    parser.add_argument("--interval", type=float, default=30, help="seconds between polls")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    wanted = args.camera or DEFAULT_CAMERAS
    cameras = [c for c in load_sources(settings.sources_path).cameras if c.id in wanted]
    log: dict[str, list[dict]] = {f"{c.id} {s}": [] for c in cameras for s in ("ashcam", "mjpg")}
    started = utcnow()
    deadline = time.monotonic() + args.minutes * 60
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": settings.user_agent}) as http:
        ashcam = AshcamClient(http)
        while True:
            for camera in cameras:
                for source, newest in (("ashcam", lambda: newest_ashcam(ashcam, camera)),
                                       ("mjpg", lambda: newest_mjpg(http, camera))):
                    try:
                        captured = newest()
                    except (httpx.HTTPError, ValueError) as exc:
                        print(f"{camera.id} {source}: {type(exc).__name__}: {exc}")
                        continue
                    rows = log[f"{camera.id} {source}"]
                    if captured and all(r["captured"] != captured for r in rows):
                        rows.append({"captured": captured, "seen": utcnow(), "baseline": not rows})
            if time.monotonic() >= deadline:
                break
            time.sleep(args.interval)

    out = settings.data_dir / "latency" / f"{started:%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({key: [{k: to_iso(v) if isinstance(v, datetime) else v for k, v in r.items()}
                                     for r in rows] for key, rows in log.items()}, indent=2), encoding="utf-8")
    print(f"\nPolled every {args.interval:g} s from {to_iso(started)} to {to_iso(utcnow())}; raw log in {out}\n")
    print(report(log))


def newest_ashcam(client: AshcamClient, camera: Camera) -> datetime | None:
    now = utcnow()
    images = client.list_images(camera.ashcam_code, now - timedelta(minutes=30), now)
    return images[-1].timestamp if images else None


def newest_mjpg(http: httpx.Client, camera: Camera) -> datetime:
    response = http.get(camera.url.rsplit("/", 1)[0] + "/js.js")
    response.raise_for_status()
    match = JS_DATETIME.search(response.text)
    if not match:
        raise ValueError(f"no capture time in js.js for {camera.id}")
    local = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=HST)
    return local.astimezone(timezone.utc)


def report(log: dict[str, list[dict]]) -> str:
    lines = ["| camera | source | new captures | median latency (min) | max latency (min) | median spacing (min) |",
             "|---|---|---|---|---|---|"]
    for key, rows in log.items():
        camera_id, source = key.split()
        latencies = [(r["seen"] - r["captured"]).total_seconds() / 60 for r in rows if not r["baseline"]]
        captures = sorted(r["captured"] for r in rows)
        spacing = [(b - a).total_seconds() / 60 for a, b in zip(captures, captures[1:])]
        lines.append(f"| {camera_id} | {source} | {len(latencies)} | {_fmt(latencies, statistics.median)} "
                     f"| {_fmt(latencies, max)} | {_fmt(spacing, statistics.median)} |")
    return "\n".join(lines)


def _fmt(values: list[float], stat) -> str:
    return f"{stat(values):.1f}" if values else "–"


if __name__ == "__main__":
    main()
```

- [x] **Step 2: Check it with a short run**

Run: `.venv/Scripts/python.exe scripts/measure_ashcam_latency.py --minutes 1 --interval 20`
Expected: no tracebacks; a table with one row per camera and source (counts may be 0 in one minute).

- [x] **Step 3: Start the full measurement in the background** (it finishes while Tasks 9–12 run)

Run (background): `.venv/Scripts/python.exe scripts/measure_ashcam_latency.py --minutes 40 > data/latency/run.log 2>&1` (create `data/latency/` first).

- [x] **Step 4: Commit the script**

```bash
git add scripts/measure_ashcam_latency.py
git commit -m "Add script that measures AshCam freshness against the live M.jpg"
```

The results and the decision are written in Task 13.

---

### Task 9: Overlay legend in a strip below the frame

The smoke-test overlays showed the corner legend hiding the burned-in HST timestamp. The legend moves to a strip appended below the image, so no image pixel is ever covered. Frames rendered for one video must share a size, hence `min_legend_rows`.

**Files:**
- Modify: `vigia/overlay.py`, `tests/test_overlay.py`, `scripts/smoke_test.py`

- [x] **Step 1: Rewrite `tests/test_overlay.py`**

```python
import numpy as np
import pytest
from PIL import Image

from vigia.overlay import Layer, draw_layers

SIZE = (400, 300)  # width, height
INSIDE = (220, 170)  # x, y: inside the mask, away from its outline
OUTSIDE = (380, 280)
RED_ON_GRAY = (178, 50, 50)  # gray 100 blended 50/50 with pure red


def gray_image(value=100):
    return Image.new("RGB", SIZE, (value, value, value))


def square_mask(shape=(300, 400), top=150, left=200, size=40):
    mask = np.zeros(shape, dtype=bool)
    mask[top:top + size, left:left + size] = True
    return mask


def layer(color=(255, 0, 0), label="plume", **mask_args):
    return Layer(mask=square_mask(**mask_args), color=color, label=label)


def test_mask_pixels_are_tinted_with_the_layer_color():
    out = draw_layers(gray_image(), [layer()], alpha=0.5)

    assert out.getpixel(INSIDE) == RED_ON_GRAY


def test_pixels_outside_every_mask_are_unchanged():
    out = draw_layers(gray_image(), [layer()])

    assert out.getpixel(OUTSIDE) == (100, 100, 100)


def test_legend_goes_in_a_strip_below_the_image_and_covers_none_of_it():
    out = draw_layers(gray_image(), [layer(top=0, left=0)], alpha=0.5)

    assert out.width == SIZE[0] and out.height > SIZE[1]
    frame = np.asarray(out)[:SIZE[1]]
    assert (frame[~square_mask(top=0, left=0)] == 100).all()  # burned-in text in any corner stays visible
    assert out.getpixel((5, 8)) == RED_ON_GRAY  # where a corner legend used to go


def test_legend_shows_each_layer_color():
    layers = [layer(color=(255, 0, 0), label="plume"), layer(color=(0, 255, 0), label="fountain", top=20, left=20)]

    out = draw_layers(gray_image(), layers)

    strip = np.asarray(out)[SIZE[1]:].reshape(-1, 3)
    assert {(255, 0, 0), (0, 255, 0)} <= {tuple(int(v) for v in pixel) for pixel in strip}


def test_min_legend_rows_give_every_frame_of_a_video_the_same_size():
    two_layers = [layer(), layer(color=(0, 255, 0), top=20, left=20)]

    sizes = {draw_layers(gray_image(), layers, min_legend_rows=2).size for layers in ([], [layer()], two_layers)}

    assert len(sizes) == 1


def test_without_layers_the_image_keeps_its_size():
    assert draw_layers(gray_image(), []).size == SIZE


def test_input_image_is_not_modified():
    image = gray_image()

    draw_layers(image, [layer(color=(0, 255, 0), label="steam")])

    assert image.getpixel(INSIDE) == (100, 100, 100)


def test_mask_with_a_different_shape_than_the_image_is_rejected():
    with pytest.raises(ValueError, match="shape"):
        draw_layers(gray_image(), [layer(shape=(10, 10), top=0, left=0, size=3)])
```

- [x] **Step 2: Run them to see the new ones fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_overlay.py -v`
Expected: `test_legend_goes_in_a_strip...`, `test_legend_shows_each_layer_color` and `test_min_legend_rows...` FAIL (corner legend; no strip; unexpected keyword `min_legend_rows`); the other 5 pass.

- [x] **Step 3: Implement** — replace `draw_layers` and `_draw_legend` in `vigia/overlay.py`, keeping `Layer` and `_edge` as they are:

```python
"""Draw segmentation masks, outlines and boxes on a frame, with a legend strip below it."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont

_LEGEND_BG = (25, 25, 25)
_LEGEND_FG = (240, 240, 240)
_PAD = 4
```

```python
def draw_layers(
    image: Image.Image,
    layers: Sequence[Layer],
    alpha: float = 0.45,
    *,
    min_legend_rows: int = 0,
) -> Image.Image:
    """Return a new RGB image with each layer's mask tinted and outlined.

    Labels go in a legend strip below the frame, one row per layer, so they
    never hide burned-in text (timestamps, PTZ readouts) or the top of a plume.
    `min_legend_rows` reserves rows even when there are fewer layers, so every
    frame rendered for one video gets the same size. With no layers and no
    reserved rows the output keeps the input's size.
    """
    pixels = np.asarray(image.convert("RGB"), dtype=np.float32).copy()
    height, width = pixels.shape[:2]
    for layer in layers:
        if layer.mask.shape != (height, width):
            raise ValueError(f"mask shape {layer.mask.shape} does not match image shape {(height, width)}")
        color = np.array(layer.color, dtype=np.float32)
        pixels[layer.mask] = (1 - alpha) * pixels[layer.mask] + alpha * color
        pixels[_edge(layer.mask)] = color

    frame = Image.fromarray(pixels.round().astype(np.uint8))
    draw = ImageDraw.Draw(frame)
    for layer in layers:
        if layer.box:
            draw.rectangle(layer.box, outline=layer.color, width=max(1, height // 400))
    rows = max(len(layers), min_legend_rows)
    return _add_legend(frame, layers, rows) if rows else frame


def _add_legend(frame: Image.Image, layers: Sequence[Layer], rows: int) -> Image.Image:
    """Return the frame with a legend strip of `rows` rows appended below it."""
    font = ImageFont.load_default(size=max(12, frame.height // 40))
    ascent, descent = font.getmetrics()
    swatch = ascent + descent
    line_h = swatch + _PAD
    out = Image.new("RGB", (frame.width, frame.height + rows * line_h + _PAD), _LEGEND_BG)
    out.paste(frame, (0, 0))
    draw = ImageDraw.Draw(out)
    for i, layer in enumerate(layers):
        top = frame.height + _PAD + i * line_h
        draw.rectangle((_PAD, top, _PAD + swatch, top + swatch), fill=layer.color)
        draw.text((3 * _PAD + swatch, top), layer.label, fill=_LEGEND_FG, font=font)
    return out
```

- [x] **Step 4: Run them to see them pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_overlay.py -v`
Expected: 8 passed

- [x] **Step 5: Keep the smoke test's video frames one size** — in `scripts/smoke_test.py` `track_video`, replace `draw_layers(frame, layers).save(target, quality=90)` with

```python
        draw_layers(frame, layers, min_legend_rows=len(ids)).save(target, quality=90)
```

- [x] **Step 6: Check visually on a real frame**

Run:

```bash
.venv/Scripts/python.exe -c "
import numpy as np
from PIL import Image
from vigia.overlay import Layer, draw_layers
img = Image.open('data/raw/usgs_ep55/ashcam/kilauea-v1-cam/kilauea-v1-cam-1792256342.jpg')
m = np.zeros((img.height, img.width), bool); m[230:570, 1300:1600] = True
draw_layers(img, [Layer(m, (255, 120, 0), 'lava fountain #0 0.89'), Layer(m, (0, 200, 255), 'steam #0 0.75')]).save('data/legend_check.jpg')
"
```

Open `data/legend_check.jpg`: the `2026-10-17 06:59:01 HST` stamp (top left) and the `P: 29, T: +0.00, Z: 29 1.0` readout (bottom right) are fully visible; the two-row legend sits below the frame.

- [x] **Step 7: Run the suite and commit**

Run: `.venv/Scripts/python.exe -m pytest` → 81 passed

```bash
git add vigia/overlay.py tests/test_overlay.py scripts/smoke_test.py
git commit -m "Draw the overlay legend in a strip below the frame"
```

---

### Task 10: Share the upload preprocessing (`vigia/imaging.py`)

Prompt tuning (and the Phase 2 quality gate) send frames the way the smoke test does: EXIF rotation applied, longest side capped at 2048 px, JPEG. Move that helper into the package.

**Files:**
- Create: `vigia/imaging.py`, `tests/test_imaging.py`
- Modify: `scripts/smoke_test.py`

- [x] **Step 1: Write the failing tests** (`tests/test_imaging.py`)

```python
import io

from PIL import Image

from vigia.imaging import load_for_upload


def test_load_for_upload_caps_the_longest_side_and_encodes_jpeg(tmp_path):
    path = tmp_path / "wide.png"
    Image.new("RGB", (4096, 1024), (90, 90, 90)).save(path)

    image, jpeg = load_for_upload(path, max_side=2048)

    assert image.size == (2048, 512)
    with Image.open(io.BytesIO(jpeg)) as sent:
        assert (sent.format, sent.size) == ("JPEG", (2048, 512))


def test_load_for_upload_keeps_small_frames_at_full_size(tmp_path):
    path = tmp_path / "small.jpg"
    Image.new("RGB", (640, 480)).save(path)

    image, _ = load_for_upload(path)

    assert image.size == (640, 480)


def test_load_for_upload_applies_the_exif_rotation(tmp_path):
    path = tmp_path / "portrait.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90° clockwise to display
    Image.new("RGB", (400, 300)).save(path, exif=exif)

    image, _ = load_for_upload(path)

    assert image.size == (300, 400)
```

- [x] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_imaging.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigia.imaging'`

- [x] **Step 3: Create `vigia/imaging.py`**

```python
"""Prepare frames for the Meta Model API."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps

MAX_SIDE_PX = 2048  # larger frames are downscaled before upload; SAM masks refer to the sent image


def load_for_upload(path: str | Path, max_side: int = MAX_SIDE_PX) -> tuple[Image.Image, bytes]:
    """Load a frame as displayed (EXIF rotation applied), cap its longest side and encode it as JPEG.

    Returns the image that was encoded too, so masks can be drawn on it.
    """
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
    image.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return image, buffer.getvalue()
```

- [x] **Step 4: Run them to see them pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_imaging.py -v`
Expected: 3 passed

- [x] **Step 5: Use it in the smoke test** — in `scripts/smoke_test.py` delete `MAX_SIDE_PX` and the `load_for_upload` function, drop `import io` and change `from PIL import Image, ImageOps` to `from PIL import Image`, and add `from vigia.imaging import load_for_upload`.

Run: `.venv/Scripts/python.exe scripts/smoke_test.py --dry-run --skip-video`
Expected: `Results in data/smoke/<timestamp>` with no traceback (it polls the live camera once).

- [x] **Step 6: Run the suite and commit**

Run: `.venv/Scripts/python.exe -m pytest` → 84 passed

```bash
git add vigia/imaging.py tests/test_imaging.py scripts/smoke_test.py
git commit -m "Move upload preprocessing into vigia.imaging"
```

---

### Task 11: SAM phrase book (`vigia/prompts.py`)

**Files:**
- Create: `vigia/prompts.py`, `tests/test_prompts.py`
- Modify: `vigia/config.py`

- [x] **Step 1: Write the failing tests** (`tests/test_prompts.py`)

```python
import textwrap

import pytest

from vigia.config import ConfigError
from vigia.prompts import load_prompts

VALID = """
plume:
  visible: [steam plume, steam]
fountain:
  visible: [lava fountain]
  thermal: [hot spot]
incandescence:
  visible: [glowing lava]
"""


def write(tmp_path, text):
    path = tmp_path / "prompts.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_phrases_are_listed_per_target_and_camera_kind_in_order(tmp_path):
    prompts = load_prompts(write(tmp_path, VALID))

    assert prompts.phrases("plume", "visible") == ["steam plume", "steam"]
    assert prompts.phrases("fountain", "thermal") == ["hot spot"]


def test_a_camera_kind_without_phrases_gets_none(tmp_path):
    prompts = load_prompts(write(tmp_path, VALID))

    assert prompts.phrases("plume", "thermal") == []


def test_unknown_target_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="lahar"):
        load_prompts(write(tmp_path, VALID + "lahar:\n  visible: [muddy water]\n"))


def test_unknown_camera_kind_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="infrared"):
        load_prompts(write(tmp_path, VALID.replace("thermal:", "infrared:")))


def test_empty_phrase_is_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_prompts(write(tmp_path, VALID.replace("[lava fountain]", "['']")))
```

- [x] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prompts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vigia.prompts'`

- [x] **Step 3: Name the camera kinds in `vigia/config.py`** — after `class ConfigError` add

```python
CameraKind = Literal["visible", "thermal"]
```

and change `Camera.kind` to `kind: CameraKind = "visible"`.

- [x] **Step 4: Create `vigia/prompts.py`**

```python
"""SAM 3.1 phrases per target and camera kind, from config/prompts.yaml.

SAM segments one noun phrase per request, so every phrase listed for a target
is a separate call. The phrases were chosen on episode 55 frames with
scripts/tune_prompts.py; the evidence is in docs/research/prompt_tuning.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vigia.config import CameraKind, ConfigError

Target = Literal["plume", "fountain", "incandescence"]
Phrase = Annotated[str, Field(min_length=1)]


class Prompts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plume: dict[CameraKind, list[Phrase]] = {}
    fountain: dict[CameraKind, list[Phrase]] = {}
    incandescence: dict[CameraKind, list[Phrase]] = {}

    def phrases(self, target: Target, kind: CameraKind) -> list[str]:
        """The phrases to send for `target` on a camera of `kind`, best first; empty if none."""
        return list(getattr(self, target).get(kind, []))


def load_prompts(path: str | Path) -> Prompts:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    try:
        return Prompts.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc
```

- [x] **Step 5: Run them to see them pass, then the suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prompts.py -v` → 5 passed
Run: `.venv/Scripts/python.exe -m pytest` → 89 passed

- [x] **Step 6: Commit**

```bash
git add vigia/prompts.py vigia/config.py tests/test_prompts.py
git commit -m "Load SAM phrases per target and camera kind"
```

---

### Task 12: Tune SAM phrases on episode 55 frames

Budget: 57 SAM image calls × $0.0025 = **$0.14**.

| frame | file | kind | targets |
|---|---|---|---|
| `kp_0450_night` (peak, plume lit by the fountain) | `ashcam/kilauea-kp-cam/kilauea-kp-cam-1792248605.jpg` | visible | plume, fountain, incandescence |
| `kp_0602_dawn` (official 17,000 ft) | `ashcam/kilauea-kp-cam/kilauea-kp-cam-1792252808.jpg` | visible | plume |
| `k2_0500_night` (peak, incandescent fountain) | `ashcam/kilauea-k2-cam/kilauea-k2-cam-1792249204.jpg` | visible | fountain, incandescence |
| `k2_0700_day` (official 500 ft fountain) | `ashcam/kilauea-k2-cam/kilauea-k2-cam-1792256403.jpg` | visible | plume, fountain |
| `v1_0659_day` (smoke-test frame) | `ashcam/kilauea-v1-cam/kilauea-v1-cam-1792256342.jpg` | visible | plume, fountain |
| `f1_0601_thermal` | `20261017060125M_F1.jpg` | thermal | fountain, incandescence |

Candidates: plume = `steam` (smoke-test winner), `volcanic plume` (smoke-test baseline that returned the fountain), `steam plume`, `white plume`, `eruption column`, `gas plume`, `volcanic gas plume`, `ash cloud`, `volcanic eruption plume` (suggested by Muse Spark in the smoke test); fountain = `lava fountain`, `fountain of lava`, `glowing lava`; incandescence = `incandescent lava`, `glow`.

**Files:**
- Create: `scripts/tune_prompts.py`, `docs/research/prompt_tuning.md`, `config/prompts.yaml`
- Modify: `tests/test_prompts.py`

- [x] **Step 1: Write the script**

```python
"""Choose SAM 3.1 phrases for volcanic plumes, lava fountains and incandescence.

Every candidate phrase for a target runs on the episode 55 frames where that
target is visible. Per frame it saves one overlay per phrase and a contact
sheet of them all; results.json and summary.md list, per phrase, the objects
found, the best score, the mask area and how high the mask reaches. Judge the
contact sheets, record the verdicts in docs/research/prompt_tuning.md and the
chosen phrases in config/prompts.yaml.

    python scripts/tune_prompts.py --dry-run   # list the calls and their cost
    python scripts/tune_prompts.py             # 57 SAM image calls, about $0.14
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from vigia import db
from vigia.imaging import load_for_upload
from vigia.meta.client import MetaClient
from vigia.meta.ledger import CostLedger
from vigia.meta.pricing import cost_usd
from vigia.meta.sam import SamObject
from vigia.overlay import Layer, draw_layers
from vigia.settings import Settings
from vigia.timeutil import to_iso, utcnow

EP55 = Path("data/raw/usgs_ep55")
ASHCAM = EP55 / "ashcam"

CANDIDATES = {
    "plume": ["steam", "volcanic plume", "steam plume", "white plume", "eruption column", "gas plume",
              "volcanic gas plume", "ash cloud", "volcanic eruption plume"],
    "fountain": ["lava fountain", "fountain of lava", "glowing lava"],
    "incandescence": ["incandescent lava", "glow"],
}
COLORS = {"plume": (0, 200, 255), "fountain": (255, 120, 0), "incandescence": (255, 0, 160)}


@dataclass(frozen=True)
class Frame:
    name: str
    path: Path
    kind: str  # camera kind: visible | thermal
    targets: tuple[str, ...]


FRAMES = [
    Frame("kp_0450_night", ASHCAM / "kilauea-kp-cam" / "kilauea-kp-cam-1792248605.jpg", "visible",
          ("plume", "fountain", "incandescence")),
    Frame("kp_0602_dawn", ASHCAM / "kilauea-kp-cam" / "kilauea-kp-cam-1792252808.jpg", "visible", ("plume",)),
    Frame("k2_0500_night", ASHCAM / "kilauea-k2-cam" / "kilauea-k2-cam-1792249204.jpg", "visible",
          ("fountain", "incandescence")),
    Frame("k2_0700_day", ASHCAM / "kilauea-k2-cam" / "kilauea-k2-cam-1792256403.jpg", "visible", ("plume", "fountain")),
    Frame("v1_0659_day", ASHCAM / "kilauea-v1-cam" / "kilauea-v1-cam-1792256342.jpg", "visible", ("plume", "fountain")),
    Frame("f1_0601_thermal", EP55 / "20261017060125M_F1.jpg", "thermal", ("fountain", "incandescence")),
]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="list the calls and their cost, call nothing")
    args = parser.parse_args(argv)

    calls = [(frame, target, phrase) for frame in FRAMES for target in frame.targets for phrase in CANDIDATES[target]]
    print(f"{len(calls)} SAM image calls on {len(FRAMES)} frames, "
          f"estimated ${len(calls) * cost_usd('sam-3.1', {'images_processed': 1}):.4f}")
    if args.dry_run:
        for frame, target, phrase in calls:
            print(f"  {frame.name} [{frame.path.exists() and 'ok' or 'MISSING'}] {target}: {phrase}")
        return

    settings = Settings.from_env()
    started = utcnow()
    run_dir = settings.data_dir / "tuning" / f"{started:%Y%m%dT%H%M%SZ}"
    conn = db.connect(settings.db_path)
    client = MetaClient.from_env(CostLedger(conn, settings.daily_budget_usd))
    results = []
    for frame in FRAMES:
        image, jpeg = load_for_upload(frame.path)
        out = run_dir / frame.name
        out.mkdir(parents=True)
        tiles = []
        for target in frame.targets:
            for phrase in CANDIDATES[target]:
                objects = client.segment_image(jpeg, phrase, purpose="tune:segment")
                layers = [Layer(mask=o.full_mask(image.width, image.height), color=COLORS[target],
                                label=f"{phrase} #{o.object_id} {o.score or 0:.2f}") for o in objects]
                overlay = draw_layers(image, layers)
                overlay.save(out / f"{target}_{phrase.replace(' ', '_')}.jpg", quality=90)
                row = measure(frame, target, phrase, objects, image.size)
                results.append(row)
                tiles.append((f"{phrase}: {row['objects']} obj, best {row['best_score'] or 0:.2f}", overlay))
                print(f"[{frame.name}] {target} / {phrase}: {row['objects']} object(s), best {row['best_score']}")
        contact_sheet(tiles).save(out / "contact_sheet.jpg", quality=88)
    (run_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (run_dir / "summary.md").write_text(summary(results, conn, started), encoding="utf-8")
    print(f"\nResults in {run_dir}")


def measure(frame: Frame, target: str, phrase: str, objects: list[SamObject], size: tuple[int, int]) -> dict:
    width, height = size
    best = max(objects, key=lambda o: o.score or 0, default=None)
    return {
        "frame": frame.name, "kind": frame.kind, "target": target, "phrase": phrase, "objects": len(objects),
        "best_score": round(best.score or 0, 3) if best else None,
        "area_pct": round(100 * sum(o.area_px for o in objects) / (width * height), 2),
        "top_pct": round(100 * min(o.box[1] for o in objects) / height, 1) if objects else None,
        "boxes": [list(o.box) for o in objects],
        "scores": [o.score for o in objects],
    }


def contact_sheet(tiles: list[tuple[str, Image.Image]], columns: int = 4, width: int = 480) -> Image.Image:
    """Tile the overlays, each under a caption bar with its phrase and result."""
    font = ImageFont.load_default(size=16)
    caption_h = 24
    cells = []
    for caption, image in tiles:
        thumb = image.resize((width, round(image.height * width / image.width)))
        cell = Image.new("RGB", (width, thumb.height + caption_h), (25, 25, 25))
        cell.paste(thumb, (0, caption_h))
        ImageDraw.Draw(cell).text((6, 4), caption, fill=(240, 240, 240), font=font)
        cells.append(cell)
    cell_h = max(c.height for c in cells)
    sheet = Image.new("RGB", (width * columns, cell_h * -(-len(cells) // columns)))
    for i, cell in enumerate(cells):
        sheet.paste(cell, ((i % columns) * width, (i // columns) * cell_h))
    return sheet


def summary(results: list[dict], conn, started) -> str:
    lines = [f"# SAM prompt tuning {to_iso(started)}", "",
             "`top %` is how far down the frame the highest mask starts (0 = top edge).", "",
             "| frame | target | phrase | objects | best score | mask area % | top % |",
             "|---|---|---|---|---|---|---|"]
    lines += [f"| {r['frame']} | {r['target']} | {r['phrase']} | {r['objects']} | {r['best_score'] or '–'} "
              f"| {r['area_pct']} | {r['top_pct'] if r['top_pct'] is not None else '–'} |" for r in results]
    cost = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) AS c, COUNT(*) AS n FROM api_calls "
                        "WHERE purpose = 'tune:segment' AND called_at >= ?", (to_iso(started),)).fetchone()
    return "\n".join(lines + ["", f"Cost: {cost['n']} calls, ${cost['c']:.4f}", ""])


if __name__ == "__main__":
    main()
```

- [x] **Step 2: Dry run**

Run: `.venv/Scripts/python.exe scripts/tune_prompts.py --dry-run`
Expected: `57 SAM image calls on 6 frames, estimated $0.1425` and 57 lines, all `[ok]`.

- [x] **Step 3: Commit the script**

```bash
git add scripts/tune_prompts.py
git commit -m "Add SAM prompt tuning script over episode 55 frames"
```

- [x] **Step 4: Live run**

Run: `.venv/Scripts/python.exe scripts/tune_prompts.py`
Expected: `Results in data/tuning/<timestamp>`, cost line ≈ $0.14 in `summary.md`.

- [x] **Step 5: Judge the contact sheets** — open `data/tuning/<timestamp>/<frame>/contact_sheet.jpg` for all 6 frames. For each (frame, phrase) write a verdict:
  - **✓** the mask is the intended target (plume: the gas/ash column above the vent including its top; fountain: the lava jet; incandescence: glowing lava);
  - **~** the target plus something else, or only part of it (state which);
  - **✗** the wrong object (state which: e.g. the fountain for a plume phrase, meteorological cloud);
  - **–** nothing found.

- [x] **Step 6: Choose phrases** with this rule, per target and camera kind:
  1. Rank phrases by the number of ✓ over the frames where the target is visible, then by the lowest best score among those ✓.
  2. Keep the top phrase. Add a second phrase only if it gets ✓ on a frame where the first does not (for example, night versus day).
  3. A phrase that ever returns the fountain for `plume` (or the plume for `fountain`) is not chosen.
  4. A target and kind with no ✓ gets no phrases (an empty list is valid).

- [x] **Step 7: Write `docs/research/prompt_tuning.md`** with these sections: *Method* (frames table above, candidates, cost from `summary.md`, run directory); *Results* (one table per target: phrase × frame cells with verdict and score, e.g. `✓ 0.82`); *Choice* (the phrases per target and kind and why, per the Step 6 rule); *Caveats* (single frames per condition; SAM results vary slightly between runs; what Phase 2 should watch for).

- [x] **Step 8: Write `config/prompts.yaml`** in this format, with the phrases chosen in Step 6:

```yaml
# SAM 3.1 noun phrases per target and camera kind, best first. SAM takes one
# phrase per request, so each phrase listed is one more segmentation or
# tracking call. Chosen on episode 55 frames by scripts/tune_prompts.py; the
# evidence is in docs/research/prompt_tuning.md.

plume:
  visible: [<phrases>]
fountain:
  visible: [<phrases>]
  thermal: [<phrases>]
incandescence:
  visible: [<phrases>]
  thermal: [<phrases>]
```

- [x] **Step 9: Guard the committed file** — append to `tests/test_prompts.py` (add `from pathlib import Path`):

```python
REPO = Path(__file__).resolve().parent.parent


def test_committed_prompts_cover_plumes_and_fountains_on_visible_cameras():
    prompts = load_prompts(REPO / "config" / "prompts.yaml")

    assert prompts.phrases("plume", "visible")
    assert prompts.phrases("fountain", "visible")
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_prompts.py -v` → 6 passed

- [x] **Step 10: Commit**

```bash
git add config/prompts.yaml docs/research/prompt_tuning.md tests/test_prompts.py
git commit -m "Choose SAM phrases per target from episode 55 tuning"
```

---

### Task 13: Live source decision, and AshCam live polling if it wins

- [x] **Step 1: Read the measurement** — `data/latency/run.log` from Task 8.

- [x] **Step 2: Write `docs/research/ashcam_latency.md`**: when and how it was measured; the results table; the byte-identity and timestamp facts from the top of this plan; and the decision per camera with this rule: **a camera polls AshCam live when its median AshCam latency is ≤ 5 min and AshCam's spacing is no longer than `M.jpg`'s; otherwise it keeps `M.jpg`.**

- [x] **Step 3: Commit the decision**

```bash
git add docs/research/ashcam_latency.md
git commit -m "Record AshCam latency measurement and the live source decision"
```

If no camera qualifies, stop this task here. Otherwise continue.

- [x] **Step 4: Write the failing config tests** (append to `tests/test_config.py`)

```python
def test_live_source_defaults_to_the_image_url(tmp_path):
    assert load_sources(write(tmp_path, VALID)).cameras[0].live_source == "url"


def test_live_polling_through_ashcam_needs_an_ashcam_code(tmp_path):
    text = VALID.replace("    enabled: true\n    poll_minutes: 5",
                         "    enabled: true\n    poll_minutes: 5\n    live_source: ashcam")

    with pytest.raises(ConfigError, match="ashcam_code"):
        load_sources(write(tmp_path, text))
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: the two new tests FAIL (`live_source` unknown)

- [x] **Step 5: Add `live_source` to `Camera`** in `vigia/config.py`, after `ashcam_code`:

```python
    live_source: Literal["url", "ashcam"] = "url"  # where the live poller gets new frames

    @model_validator(mode="after")
    def _ashcam_needs_a_code(self) -> Camera:
        if self.live_source == "ashcam" and not self.ashcam_code:
            raise ValueError(f"camera {self.id} polls AshCam live but has no ashcam_code")
        return self
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -v` → all pass

- [x] **Step 6: Write the failing live-ingestor tests** (append to `tests/test_ashcam.py`; import `AshcamIngestor` and `timedelta`)

```python
LIVE_NOW = datetime(2026, 10, 17, 15, 1, tzinfo=timezone.utc)


@pytest.fixture
def live(client, store):
    return AshcamIngestor(client, store, now=lambda: LIVE_NOW, lookback=timedelta(minutes=15))


def camera_state(conn):
    return conn.execute("SELECT * FROM camera_state WHERE camera_id = 'kilauea-kp'").fetchone()


def test_first_live_poll_stores_the_lookback_window(live, archive, conn):
    result = live.ingest(kp_camera())

    [listing] = archive.list_requests()
    assert listing.url.params["startTimestamp"] == str(int((LIVE_NOW - timedelta(minutes=15)).timestamp()))
    assert listing.url.params["endTimestamp"] == str(int(LIVE_NOW.timestamp()))
    newest = conn.execute("SELECT id FROM frames ORDER BY captured_at DESC LIMIT 1").fetchone()
    assert (result.status, result.frame_id) == ("new", newest["id"])
    assert camera_state(conn)["last_status"] == "new"


def test_later_live_polls_start_after_the_newest_stored_frame(live, archive):
    live.ingest(kp_camera())

    live.ingest(kp_camera())

    assert archive.list_requests()[-1].url.params["startTimestamp"] == str(1792249205 + 1)


def test_live_poll_without_new_frames_is_not_modified(live, conn):
    live.ingest(kp_camera())

    result = live.ingest(kp_camera())

    assert result.status == "not_modified"
    assert camera_state(conn)["consecutive_unchanged"] == 1


def test_live_poll_records_an_archive_outage_as_an_error(live, archive, conn):
    archive.list_status = 503

    result = live.ingest(kp_camera())

    assert result.status == "error" and "503" in result.error
    assert camera_state(conn)["consecutive_errors"] == 1
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_ashcam.py -v`
Expected: FAIL with `ImportError: cannot import name 'AshcamIngestor'`

- [x] **Step 7: Implement `AshcamIngestor`** in `vigia/ingest/ashcam.py`: add `timedelta` to the `datetime` import, `IngestResult` to the `vigia.ingest.store` import, and after `backfill()`:

```python
class AshcamIngestor:
    """Live polling through AshCam: store every frame archived since the newest one stored.

    A poll reaches back at most `lookback`: the first poll stores that window,
    and a longer gap (after downtime) is left to `vigia-backfill`.
    """

    def __init__(
        self,
        client: AshcamClient,
        store: FrameStore,
        now: Callable[[], datetime] = utcnow,
        lookback: timedelta = timedelta(hours=1),
    ):
        self._client = client
        self._store = store
        self._now = now
        self._lookback = lookback

    def ingest(self, camera: Camera) -> IngestResult:
        checked_at = self._now()
        start = checked_at - self._lookback
        latest = self._store.latest_capture(camera.id, "ashcam")
        if latest:
            start = max(start, latest + timedelta(seconds=1))
        try:
            report = backfill(self._client, self._store, camera, start, checked_at, now=self._now)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("camera %s: %s", camera.id, describe_error(exc))
            return self._store.record_check(camera.id, checked_at, "error", error=describe_error(exc))
        if report.frame_ids:
            return self._store.record_check(camera.id, checked_at, "new", frame_id=report.frame_ids[-1])
        if report.errors:
            return self._store.record_check(camera.id, checked_at, "error", error=report.errors[-1])
        return self._store.record_check(camera.id, checked_at, "not_modified")
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_ashcam.py -v` → all pass

- [x] **Step 8: Write the failing router test** (append to `tests/test_worker.py`; import `SourceRouter` from `vigia.ingest.worker`)

```python
def test_router_sends_each_camera_to_the_ingestor_of_its_live_source():
    by_url, by_ashcam = RecordingIngestor(), RecordingIngestor()
    router = SourceRouter({"url": by_url, "ashcam": by_ashcam})

    router.ingest(cam("a"))
    router.ingest(cam("b").model_copy(update={"live_source": "ashcam"}))

    assert (by_url.calls, by_ashcam.calls) == (["a"], ["b"])
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_worker.py -v`
Expected: FAIL with `ImportError: cannot import name 'SourceRouter'`

- [x] **Step 9: Implement the router and wire it** — in `vigia/ingest/worker.py` add after `SupportsIngest`:

```python
class SourceRouter:
    """Send each camera to the ingestor of its `live_source`."""

    def __init__(self, ingestors: dict[str, SupportsIngest]):
        self._ingestors = ingestors

    def ingest(self, camera: Camera) -> IngestResult:
        return self._ingestors[camera.live_source].ingest(camera)
```

import `from vigia.ingest.ashcam import AshcamClient, AshcamIngestor`, and in `main()` replace the `worker = Worker(...)` line with:

```python
        store = FrameStore(conn, settings.data_dir)
        router = SourceRouter({"url": Ingestor(store, http), "ashcam": AshcamIngestor(AshcamClient(http), store)})
        worker = Worker(router, sources.cameras)
```

Update the module docstring's first line to: `"""Polling loop: fetch each enabled camera on its own interval, from its live source."""`

- [x] **Step 10: Switch the qualifying cameras** — in `config/sources.yaml` add `    live_source: ashcam` to each camera the Step 2 decision selected, and extend the header comment: `# \`live_source: ashcam\` polls the archive instead of M.jpg: 2-min frames with exact capture times.`

- [x] **Step 11: Run the suite and one live poll**

Run: `.venv/Scripts/python.exe -m pytest` → all pass
Run: `.venv/Scripts/vigia-ingest.exe --once`
Expected: one line per enabled camera; AshCam cameras report `new` (first poll stores the last hour) without errors.

- [x] **Step 12: Commit**

```bash
git add vigia/config.py vigia/ingest/ashcam.py vigia/ingest/worker.py config/sources.yaml tests/test_config.py tests/test_ashcam.py tests/test_worker.py
git commit -m "Poll AshCam live for cameras where it is fresher than M.jpg"
```

---

### Task 14: Docs, roadmap, push, memory

**Files:**
- Modify: `README.md`, `DATA_SOURCES.md`, `docs/PLAN.md`

- [x] **Step 1: README** — under *Running it* add:

```bash
vigia-backfill --camera kilauea-kp --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z
                                   # download archived frames (USGS AshCam, ~31 days kept)
```

and in *Status* add `- [x] AshCam archive backfill with exact capture times` and `- [x] SAM 3.1 phrases tuned per target on episode 55 frames`; rename the overlay line to `- [x] Mask overlay renderer with a legend strip below the frame`. If Task 13 switched cameras to AshCam, also update the ingest worker line to mention it.

- [x] **Step 2: DATA_SOURCES.md** — in the AshCam row, state that its files are byte-identical to `M.jpg`, that `vigia-backfill` uses it, and (if Task 13 applied) which cameras poll it live.

- [x] **Step 3: docs/PLAN.md** — tick the four Phase 1 checkboxes; add `store.py`, `imaging.py` and `prompts.py` to the module map as existing; add the AshCam byte-identity/latency and the chosen phrases to *Facts the plan depends on*; update *Spent so far* in *Budget* with the tuning cost.

- [x] **Step 4: Final verification**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: all pass, 0 failures.

- [x] **Step 5: Commit and push**

```bash
git add README.md DATA_SOURCES.md docs/PLAN.md
git commit -m "Mark Phase 1 done: AshCam backfill, prompt tuning, legend strip"
git push origin main
```

- [x] **Step 6: Update the project memory** (`vigia-andino-status`): Phase 1 done, the live-source decision, the chosen phrases, the test count, the spend, and "next: Phase 2 (quality gate, timelapse tracking)".

---

## Execution notes (2026-10-27)

All 14 tasks were executed inline on `main`. The suite went from 53 to 98 tests. Deviations from the steps above:

1. **SAM mask resolution (Task 12, Step 4).** The first live run crashed on its first call: a 1081×680 px plume box came with a 1024×644 mask raster. SAM sends large masks at reduced resolution, and `meta_sam_parser` keeps the raster's own size.
   - `vigia/meta/sam.py` now scales each raster to its box (nearest neighbour). A failing test came first, reusing the docs' 27×60 raster on a box twice its size.
   - Documented in META_API_NOTES §4. Commit `4b45ed7`.
   - The aborted run cost one call.
2. **Fountain follow-up (Task 12, Steps 5–6).** `lava fountain` and `glowing lava` tied, so the script gained a `--frame` option and a `v1_0459_night` frame with glowing flows all around the fountain. That added 3 calls.
   - Tuning total: 61 calls, $0.1525.
   - The rule's tie-break favoured `glowing lava` by 0.01. We chose `lava fountain`; the reasons are in `docs/research/prompt_tuning.md`.
3. **Module run.** A self-review found that `python -m vigia.ingest.ashcam` raised `NameError`: the `__main__` guard ran before `_parse_image` was defined. The console script was not affected. Fixed in `012d0ed`.
4. **Task 13 order.** The `live_source`, `AshcamIngestor` and `SourceRouter` steps were written test-first while the 40-minute latency measurement ran. They were committed after the decision (`3aed311`, then `e35b5b9`).
   - Decision: KPcam, K2cam and V1cam use AshCam; F1cam keeps `M.jpg`.
   - The first live poll stored the last hour from AshCam: K2 29 frames, KP 12. One K2 capture was skipped as a byte-identical duplicate of an `M.jpg` frame stored earlier the same day.
