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
