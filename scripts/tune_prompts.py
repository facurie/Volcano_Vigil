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
