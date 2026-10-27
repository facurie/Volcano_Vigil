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


def _parse_image(item: dict[str, Any]) -> AshcamImage:
    return AshcamImage(
        webcam_code=item["webcamCode"],
        timestamp=datetime.fromtimestamp(item["imageTimestamp"], timezone.utc),
        url=item["imageUrl"],
        md5=item["md5"],
    )
