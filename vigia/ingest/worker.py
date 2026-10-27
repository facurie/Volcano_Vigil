"""Polling loop: fetch each enabled camera on its own interval, from its live source.

Cameras on the AshCam archive fall back to their public image URL whenever the
archive fails, so they keep getting frames (every 10 min instead of 2).

Run it standalone with `vigia-ingest` (or `python -m vigia.ingest.worker`);
`--once` polls every enabled camera a single time and exits.
"""

from __future__ import annotations

import argparse
import logging
import threading
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Protocol

import httpx

from vigia import db
from vigia.config import Camera, load_sources
from vigia.ingest.ashcam import AshcamClient, AshcamIngestor
from vigia.ingest.fetch import Ingestor
from vigia.ingest.store import FrameStore, IngestResult
from vigia.settings import Settings
from vigia.timeutil import utcnow

log = logging.getLogger(__name__)

# Upper bound on a single sleep, so Ctrl+C and stop requests are handled promptly.
_MAX_WAIT_SECONDS = 5.0


class SupportsIngest(Protocol):
    def ingest(self, camera: Camera) -> IngestResult: ...


class SourceRouter:
    """Send each camera to the ingestor of its `live_source`."""

    def __init__(self, ingestors: dict[str, SupportsIngest]):
        self._ingestors = ingestors

    def ingest(self, camera: Camera) -> IngestResult:
        return self._ingestors[camera.live_source].ingest(camera)


class Fallback:
    """Poll a camera through `backup` whenever `primary` fails for it."""

    def __init__(self, primary: SupportsIngest, backup: SupportsIngest):
        self._primary = primary
        self._backup = backup

    def ingest(self, camera: Camera) -> IngestResult:
        try:
            result = self._primary.ingest(camera)
        except Exception:  # whatever breaks in the primary source, the camera keeps its frames
            log.exception("camera %s: primary source failed; using the backup", camera.id)
        else:
            if result.status != "error":
                return result
            log.warning("camera %s: primary source failed (%s); using the backup", camera.id, result.error)
        return self._backup.ingest(camera)


def build_router(store: FrameStore, http: httpx.Client) -> SourceRouter:
    """The live ingestor of each source; AshCam cameras fall back to their image URL."""
    by_url = Ingestor(store, http)
    return SourceRouter({"url": by_url, "ashcam": Fallback(AshcamIngestor(AshcamClient(http), store), by_url)})


class Worker:
    def __init__(self, ingestor: SupportsIngest, cameras: Iterable[Camera]):
        self._ingestor = ingestor
        self._cameras = [c for c in cameras if c.enabled]
        self._next_due: dict[str, datetime] = {}

    def run_once(self, now: datetime | None = None) -> list[IngestResult]:
        """Poll every camera that is due at `now`."""
        now = now or utcnow()
        results = []
        for camera in self._cameras:
            due = self._next_due.get(camera.id)
            if due is not None and now < due:
                continue
            try:
                result = self._ingestor.ingest(camera)
            except Exception as exc:  # one broken camera must not stop the others
                log.exception("camera %s: unexpected failure", camera.id)
                result = IngestResult(camera.id, "error", error=f"{type(exc).__name__}: {exc}")
            self._next_due[camera.id] = now + timedelta(minutes=camera.poll_minutes)
            results.append(result)
        return results

    def seconds_until_next_due(self, now: datetime) -> float:
        if any(c.id not in self._next_due for c in self._cameras):
            return 0.0
        soonest = min(self._next_due.values())
        return max(0.0, (soonest - now).total_seconds())

    def run_forever(self, stop: threading.Event) -> None:
        log.info("polling %d camera(s): %s", len(self._cameras), ", ".join(c.id for c in self._cameras))
        while not stop.is_set():
            self.run_once()
            stop.wait(min(_MAX_WAIT_SECONDS, self.seconds_until_next_due(utcnow())))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Poll the enabled webcams and store new frames.")
    parser.add_argument("--once", action="store_true", help="poll every enabled camera once and exit")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    sources = load_sources(settings.sources_path)
    conn = db.connect(settings.db_path)
    headers = {"User-Agent": settings.user_agent}
    with httpx.Client(timeout=30, follow_redirects=True, headers=headers) as http:
        worker = Worker(build_router(FrameStore(conn, settings.data_dir), http), sources.cameras)
        if args.once:
            for result in worker.run_once():
                print(f"{result.camera_id}: {result.status}" + (f" ({result.error})" if result.error else ""))
            return
        try:
            worker.run_forever(threading.Event())
        except KeyboardInterrupt:
            log.info("stopped")


if __name__ == "__main__":
    main()
