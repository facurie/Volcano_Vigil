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

import argparse
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from vigil import db
from vigil.config import Camera, load_sources
from vigil.ingest.fetch import describe_error
from vigil.ingest.store import FrameStore, IngestResult
from vigil.settings import Settings
from vigil.timeutil import parse_utc, utcnow

log = logging.getLogger(__name__)

API_URL = "https://volcview.wr.usgs.gov/ashcam-api"


class ChecksumMismatch(ValueError):
    """A downloaded AshCam frame does not match the MD5 listed in the index."""


class IndexFormatError(ValueError):
    """The AshCam index is not in the format this client was written for (the API is undocumented)."""


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
        try:
            images = [_parse_image(item) for item in response.json()["images"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise IndexFormatError(f"unexpected AshCam index format ({type(exc).__name__}: {exc})") from exc
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


class AshcamIngestor:
    """Live polling through AshCam: store every frame archived since the newest one stored.

    A poll reaches back at most `lookback`: the first poll stores that window, and a longer gap
    (after downtime) needs a longer lookback (`vigil-ingest --lookback-hours`) or `vigil-backfill`.
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
