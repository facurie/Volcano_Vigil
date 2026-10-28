"""Measure the local quality checks on stored frames, to calibrate their thresholds.

For each camera and time window, every stored frame gets the local
measurements of vigia.quality (edge density, contrast, glow, difference from
the camera's previous frame), the sun's elevation at its volcano and the
decision under the current thresholds. Results go to
data/calibration/<UTC time>/:
  - stats.csv: one row per frame;
  - summary.md: decision counts and value ranges per camera and window;
  - <camera>_<window start>_<decision>.jpg: contact sheets of up to 24
    frames, captioned with the HST time, edge density and glow, to check the
    decisions by eye.

    python scripts/calibrate_quality.py --camera kilauea-kp --camera kilauea-k2 --camera kilauea-v1 \\
        --window 2026-10-17T13:00Z/2026-10-17T19:30Z --window 2026-10-26T22:00Z/2026-10-27T02:00Z
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from vigia import db
from vigia.config import Camera, Sources, load_sources
from vigia.quality import check_local, difference, fingerprint, measure
from vigia.settings import Settings
from vigia.sun import solar_elevation
from vigia.timeutil import parse_utc, to_iso, utcnow

HST = timezone(timedelta(hours=-10))
FIELDS = ["camera_id", "window", "captured_at", "hst", "path", "sun_elevation", "brightness", "contrast",
          "edge_density", "glow_fraction", "change", "decision", "reasons"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camera", action="append", required=True, help="camera id; repeat for several")
    parser.add_argument("--window", action="append", required=True, type=parse_window,
                        help="START/END with offsets, e.g. 2026-10-17T13:00Z/2026-10-17T19:30Z; repeat for several")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    sources = load_sources(settings.sources_path)
    cameras = {c.id: c for c in sources.cameras}
    unknown = [camera_id for camera_id in args.camera if camera_id not in cameras]
    if unknown:
        parser.error(f"unknown camera(s): {', '.join(unknown)}")
    conn = db.connect(settings.db_path)
    out = settings.data_dir / "calibration" / f"{utcnow():%Y%m%dT%H%M%SZ}"
    out.mkdir(parents=True)

    rows = []
    for camera_id in args.camera:
        for start, end in args.window:
            window_rows = measure_window(conn, settings.data_dir, sources, cameras[camera_id], start, end)
            rows += window_rows
            for decision, group in grouped(window_rows).items():
                sheet = contact_sheet(settings.data_dir, group)
                sheet.save(out / f"{camera_id}_{start:%Y%m%dT%H%M}_{decision}.jpg", quality=85)
    with open(out / "stats.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (out / "summary.md").write_text(summary(rows), encoding="utf-8")
    print(f"{len(rows)} frames measured; results in {out}")


def parse_window(text: str) -> tuple[datetime, datetime]:
    start, _, end = text.partition("/")
    return parse_utc(start), parse_utc(end)


def measure_window(conn, data_dir: Path, sources: Sources, camera: Camera,
                   start: datetime, end: datetime) -> list[dict]:
    """Measurements and local decisions for the camera's stored frames in [start, end], oldest first."""
    volcano = sources.volcanoes[camera.volcano]
    before = conn.execute(
        "SELECT path FROM frames WHERE camera_id = ? AND captured_at < ? ORDER BY captured_at DESC LIMIT 1",
        (camera.id, to_iso(start))).fetchone()
    previous = fingerprint(open_rgb(data_dir / before["path"])) if before else None
    rows = []
    for frame in conn.execute(
            "SELECT * FROM frames WHERE camera_id = ? AND captured_at BETWEEN ? AND ? ORDER BY captured_at",
            (camera.id, to_iso(start), to_iso(end))).fetchall():
        image = open_rgb(data_dir / frame["path"])
        stats, current = measure(image), fingerprint(image)
        captured_at = parse_utc(frame["captured_at"])
        sun = (solar_elevation(captured_at, volcano.lat, volcano.lon)
               if volcano.lat is not None and volcano.lon is not None else None)
        change = difference(previous, current) if previous is not None else None
        verdict = check_local(stats, kind=camera.kind, captured_at=captured_at, sun_elevation=sun, change=change)
        previous = current
        rows.append({"camera_id": camera.id, "window": to_iso(start), "captured_at": frame["captured_at"],
                     "hst": captured_at.astimezone(HST).strftime("%Y-%m-%d %H:%M"), "path": frame["path"],
                     "sun_elevation": sun, **asdict(stats), "change": change,
                     "decision": verdict.decision, "reasons": " ".join(verdict.reasons)})
    return rows


def open_rgb(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB")


def grouped(rows: list[dict]) -> dict[str, list[dict]]:
    groups = defaultdict(list)
    for row in rows:
        groups[row["decision"]].append(row)
    return groups


def contact_sheet(data_dir: Path, rows: list[dict], limit: int = 24, columns: int = 4, width: int = 400) -> Image.Image:
    picks = rows if len(rows) <= limit else [rows[round(i * (len(rows) - 1) / (limit - 1))] for i in range(limit)]
    font = ImageFont.load_default(size=18)
    cells = []
    for row in picks:
        thumb = open_rgb(data_dir / row["path"])
        thumb.thumbnail((width, width))
        cell = Image.new("RGB", (width, thumb.height + 24), (25, 25, 25))
        cell.paste(thumb, (0, 24))
        caption = f"{row['hst'][11:]} e={row['edge_density']:.3f} g={100 * row['glow_fraction']:.2f}%"
        ImageDraw.Draw(cell).text((4, 2), caption, fill=(255, 255, 0), font=font)
        cells.append(cell)
    cell_h = max(cell.height for cell in cells)
    sheet = Image.new("RGB", (width * columns, cell_h * -(-len(cells) // columns)))
    for i, cell in enumerate(cells):
        sheet.paste(cell, ((i % columns) * width, (i // columns) * cell_h))
    return sheet


def summary(rows: list[dict]) -> str:
    lines = ["# Local quality checks", "",
             "| camera | window start (UTC) | frames | pass | uncertain | reject (reasons) | edge density | glow % |",
             "|---|---|---|---|---|---|---|---|"]
    windows = defaultdict(list)
    for row in rows:
        windows[(row["camera_id"], row["window"])].append(row)
    for (camera_id, window), group in windows.items():
        decisions = Counter(row["decision"] for row in group)
        reasons = Counter(reason for row in group if row["decision"] == "reject" for reason in row["reasons"].split())
        edges = [row["edge_density"] for row in group]
        glows = [100 * row["glow_fraction"] for row in group]
        rejected = ", ".join(f"{reason} {count}" for reason, count in sorted(reasons.items())) or "-"
        lines.append(f"| {camera_id} | {window} | {len(group)} | {decisions['pass']} | {decisions['uncertain']} "
                     f"| {decisions['reject']} ({rejected}) | {min(edges):.3f}-{max(edges):.3f} "
                     f"| {min(glows):.3f}-{max(glows):.3f} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
