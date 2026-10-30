"""Draw a camera's SAM tracks over its frames: an MP4 and a contact sheet.

Every tracking run of the camera whose window lies between --start and --end
is drawn on the frames it covered: plume masks cyan, fountains orange,
incandescence magenta, each labelled with its target, track and score in the
legend strip. Frames are drawn at most 1280 px wide. Output goes to
data/tracks/<camera>_<start>/: overlay.mp4 (10 fps) and contact_sheet.jpg
(12 frames, captioned with the HST time).

    python scripts/render_tracks.py --camera kilauea-k2 --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import defaultdict
from datetime import timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from vigil import db
from vigil.overlay import Layer, draw_layers
from vigil.settings import Settings
from vigil.timeutil import parse_utc, to_iso
from vigil.tracking import VIDEO_FPS, detection_mask
from vigil.video import assemble

HST = timezone(timedelta(hours=-10))
COLORS = {"plume": (0, 200, 255), "fountain": (255, 120, 0), "incandescence": (255, 0, 160)}
MAX_WIDTH = 1280


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--start", type=parse_utc, required=True)
    parser.add_argument("--end", type=parse_utc, required=True)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    conn = db.connect(settings.db_path)
    runs = conn.execute(
        "SELECT * FROM tracking_runs WHERE camera_id = ? AND window_start >= ? AND window_end <= ?",
        (args.camera, to_iso(args.start), to_iso(args.end)),
    ).fetchall()
    if not runs:
        raise SystemExit(f"no tracking runs for {args.camera} between {to_iso(args.start)} and {to_iso(args.end)}")
    run_ids = [run["id"] for run in runs]
    frame_ids = sorted({frame_id for run in runs for frame_id in json.loads(run["frame_ids"])})
    frames = conn.execute(f"SELECT * FROM frames WHERE id IN ({','.join('?' * len(frame_ids))}) "
                          "ORDER BY captured_at", frame_ids).fetchall()
    by_frame = defaultdict(list)
    for detection in conn.execute(
            f"""SELECT d.*, t.object_id, r.target FROM detections d
                JOIN tracks t ON t.id = d.track_id JOIN tracking_runs r ON r.id = t.run_id
                WHERE r.id IN ({','.join('?' * len(run_ids))})""", run_ids):
        by_frame[detection["frame_id"]].append(detection)
    rows = max((len(detections) for detections in by_frame.values()), default=0)

    out = settings.data_dir / "tracks" / f"{args.camera}_{args.start:%Y%m%dT%H%MZ}"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        rendered = []
        for i, frame in enumerate(frames):
            with Image.open(settings.data_dir / frame["path"]) as raw:
                image = raw.convert("RGB")
            scale = min(1.0, MAX_WIDTH / image.width)
            size = (round(image.width * scale), round(image.height * scale))
            layers = [Layer(mask=resized(detection_mask(d, frame["width"], frame["height"]), size),
                            color=COLORS[d["target"]], label=f"{d['target']} #{d['object_id']} {d['score'] or 0:.2f}")
                      for d in by_frame.get(frame["id"], [])]
            path = Path(tmp) / f"{i:05d}.jpg"
            draw_layers(image.resize(size), layers, min_legend_rows=rows).save(path, quality=90)
            rendered.append((frame, path))
        assemble([path for _, path in rendered], out / "overlay.mp4", fps=VIDEO_FPS)
        contact_sheet(rendered).save(out / "contact_sheet.jpg", quality=88)
    detections = sum(len(v) for v in by_frame.values())
    print(f"{len(frames)} frames, {detections} detections from {len(runs)} runs; results in {out}")


def resized(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return np.asarray(Image.fromarray(mask).resize(size, Image.NEAREST), dtype=bool)


def contact_sheet(rendered: list, count: int = 12, columns: int = 3, width: int = 640) -> Image.Image:
    picks = rendered if len(rendered) <= count else [
        rendered[round(i * (len(rendered) - 1) / (count - 1))] for i in range(count)]
    font = ImageFont.load_default(size=20)
    cells = []
    for frame, path in picks:
        with Image.open(path) as image:
            thumb = image.convert("RGB")
        thumb.thumbnail((width, width))
        cell = Image.new("RGB", (width, thumb.height + 28), (25, 25, 25))
        cell.paste(thumb, (0, 28))
        hst = parse_utc(frame["captured_at"]).astimezone(HST)
        ImageDraw.Draw(cell).text((6, 4), f"{hst:%Y-%m-%d %H:%M} HST", fill=(240, 240, 240), font=font)
        cells.append(cell)
    cell_h = max(cell.height for cell in cells)
    sheet = Image.new("RGB", (width * columns, cell_h * -(-len(cells) // columns)))
    for i, cell in enumerate(cells):
        sheet.paste(cell, ((i % columns) * width, (i // columns) * cell_h))
    return sheet


if __name__ == "__main__":
    main()
