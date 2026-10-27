"""Smoke test of Muse Spark and SAM 3.1 on real volcano imagery.

For a live Kīlauea webcam frame and an episode 55 (2026-10-17) frame:
  a) Muse Spark: is the frame usable (cloud, night)? Which timestamp is
     printed on it? What is visible?
  b) SAM 3.1: segment "lava fountain", "volcanic plume" and "steam" and save
     the masks overlaid on the frame.
Then:
  c) SAM 3.1 in video mode: track the lava fountain through a short clip cut
     from an episode 55 webcam timelapse.

Results go to data/smoke/<UTC timestamp>/ with a summary.md.

    python scripts/smoke_test.py --dry-run   # everything except Meta API calls
    python scripts/smoke_test.py             # needs MODEL_API_KEY in .env
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
from collections import defaultdict
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from vigia import db
from vigia.config import load_sources
from vigia.ingest.fetch import Ingestor
from vigia.meta.client import MetaClient
from vigia.meta.ledger import CostLedger
from vigia.meta.pricing import cost_usd
from vigia.meta.sam import SamObject
from vigia.overlay import Layer, draw_layers
from vigia.settings import Settings
from vigia.timeutil import to_iso, utcnow
from vigia.video import assemble, cut_clip, extract_frames, probe

PHRASES = {"lava fountain": (255, 120, 0), "volcanic plume": (0, 200, 255), "steam": (190, 0, 255)}
TRACK_COLORS = [(255, 120, 0), (0, 200, 255), (190, 0, 255), (0, 220, 120), (255, 60, 60), (255, 230, 0)]
MAX_SIDE_PX = 2048  # larger photos are downscaled before upload; masks refer to the sent image

EP55 = Path("data/raw/usgs_ep55")
DEFAULT_EP55_FRAME = EP55 / "ashcam" / "kilauea-v1-cam" / "kilauea-v1-cam-1792256342.jpg"  # 06:59 HST
DEFAULT_EP55_VIDEO = EP55 / "vlc-record-2026-10-19-14h15m07s-V1cam20261017M.avi-.mp4"

ASSESS_INSTRUCTIONS = (
    "You are the quality gate of a volcano webcam monitoring system. You look at one webcam frame "
    "and report only what is actually visible. Never infer activity that you cannot see."
)
ASSESS_PROMPT = (
    "Assess this volcano webcam frame.\n"
    "1. Is it usable for measuring a volcanic plume or lava fountain, or is the view blocked "
    "(cloud, fog, darkness, rain on the lens, glare, frozen or corrupted image)? Explain briefly.\n"
    "2. Transcribe any timestamp printed on the image exactly as written, and convert it to "
    "ISO 8601 keeping the printed time zone (leave the offset out if no zone is printed). "
    "Use empty strings if there is no readable timestamp. Also transcribe any camera label.\n"
    "3. List the visible features, classify the activity, and describe the scene in English and Spanish.\n"
    "4. Suggest short noun phrases for a text-prompted segmentation model to find what matters."
)
ASSESS_SCHEMA = {
    "type": "object",
    "properties": {
        "usable": {"type": "boolean"},
        "view": {"type": "string", "enum": [
            "clear", "partly_obscured", "obscured_by_cloud_or_fog", "night_dark", "night_with_glow",
            "rain_or_lens_water", "glare", "frozen_or_corrupted"]},
        "usable_reason": {"type": "string"},
        "printed_timestamp_text": {"type": "string"},
        "printed_timestamp_iso": {"type": "string"},
        "printed_camera_label": {"type": "string"},
        "visible_features": {"type": "array", "items": {"type": "string", "enum": [
            "crater", "crater_floor", "vent", "lava_lake", "lava_fountain", "incandescent_glow",
            "volcanic_plume", "steam", "gas_haze", "ash_cloud", "meteorological_cloud", "fog",
            "blue_sky", "night_sky", "people", "structures"]}},
        "activity": {"type": "string", "enum": [
            "no_visible_activity", "degassing", "steaming", "ash_emission", "lava_fountaining",
            "lava_lake_activity", "unclear"]},
        "description_en": {"type": "string"},
        "description_es": {"type": "string"},
        "suggested_sam_phrases": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}
ASSESS_SCHEMA["required"] = list(ASSESS_SCHEMA["properties"])


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    settings = Settings.from_env()
    started = utcnow()
    run_dir = settings.data_dir / "smoke" / started.strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True)
    conn = db.connect(settings.db_path)
    client = None if args.dry_run else MetaClient.from_env(CostLedger(conn, settings.daily_budget_usd))
    report = [f"# Smoke test {to_iso(started)}", "",
              f"Mode: {'DRY RUN (no Meta API calls)' if args.dry_run else 'live API calls'}", ""]

    live_path, live_row = fetch_live_frame(settings, conn, args.camera)
    report += [f"## Live frame: `{args.camera}`", "",
               f"Captured {live_row['captured_at']} ({live_row['timestamp_source']}), fetched {live_row['fetched_at']}, "
               f"{live_row['width']}x{live_row['height']}, `{live_row['path']}`", ""]
    report += analyze_image(client, live_path, run_dir / "live")

    report += [f"## Episode 55 frame: `{args.ep55_frame.name}`", ""]
    report += analyze_image(client, args.ep55_frame, run_dir / "ep55")

    if not args.skip_video:
        report += track_video(client, args, run_dir / "video")

    report += cost_section(conn, to_iso(started), args.dry_run)
    (run_dir / "summary.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"\nResults in {run_dir}")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="prepare everything but skip Meta API calls")
    parser.add_argument("--camera", default="kilauea-v1", help="enabled camera id from the sources file")
    parser.add_argument("--ep55-frame", type=Path, default=DEFAULT_EP55_FRAME)
    parser.add_argument("--ep55-video", type=Path, default=DEFAULT_EP55_VIDEO)
    parser.add_argument("--clip-start", type=float, default=14.0,
                        help="seconds into the timelapse (14 s: daylight fountain and plume)")
    parser.add_argument("--clip-seconds", type=float, default=10.0)
    parser.add_argument("--clip-fps", type=float, default=10.0, help="SAM bills per frame")
    parser.add_argument("--clip-height", type=int, default=720)
    parser.add_argument("--video-phrase", default="lava fountain")
    parser.add_argument("--skip-video", action="store_true")
    return parser.parse_args(argv)


def fetch_live_frame(settings: Settings, conn, camera_id: str) -> tuple[Path, dict]:
    """Fetch the camera through the ingest pipeline and return its latest stored frame."""
    camera = next((c for c in load_sources(settings.sources_path).cameras if c.id == camera_id), None)
    if camera is None or not camera.enabled:
        raise SystemExit(f"camera {camera_id!r} is not an enabled camera in {settings.sources_path}")
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": settings.user_agent}) as http:
        result = Ingestor(conn, settings.data_dir, http).ingest(camera)
    print(f"[live] {camera_id}: {result.status}" + (f" ({result.error})" if result.error else ""))
    row = conn.execute(
        "SELECT * FROM frames WHERE camera_id = ? ORDER BY captured_at DESC LIMIT 1", (camera_id,)
    ).fetchone()
    if row is None:
        raise SystemExit(f"no frame available for {camera_id}")
    return settings.data_dir / row["path"], dict(row)


def load_for_upload(path: Path) -> tuple[Image.Image, bytes]:
    """Apply EXIF rotation (SAM reports pixels as displayed) and cap the size."""
    image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    image.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return image, buffer.getvalue()


def analyze_image(client: MetaClient | None, path: Path, out: Path) -> list[str]:
    out.mkdir(parents=True)
    image, jpeg = load_for_upload(path)
    image.save(out / "frame.jpg", quality=92)
    lines = []

    if client is None:
        lines += ["### Muse Spark assessment", "", "Skipped (dry run).", ""]
    else:
        assessment = client.ask_json(prompt=ASSESS_PROMPT, images=[jpeg], schema_name="frame_assessment",
                                     schema=ASSESS_SCHEMA, instructions=ASSESS_INSTRUCTIONS, purpose="smoke:assess")
        (out / "assessment.json").write_text(json.dumps(assessment, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[{out.name}] assessment: usable={assessment['usable']} view={assessment['view']} "
              f"timestamp={assessment['printed_timestamp_text']!r}")
        lines += ["### Muse Spark assessment", "",
                  "| usable | view | printed timestamp | ISO | camera label | activity |",
                  "|---|---|---|---|---|---|",
                  f"| {assessment['usable']} | {assessment['view']} | {assessment['printed_timestamp_text']} "
                  f"| {assessment['printed_timestamp_iso']} | {assessment['printed_camera_label']} "
                  f"| {assessment['activity']} |", "",
                  f"Why: {assessment['usable_reason']}", "",
                  f"Visible: {', '.join(assessment['visible_features'])}", "",
                  f"EN: {assessment['description_en']}", "",
                  f"ES: {assessment['description_es']}", "",
                  f"Suggested SAM phrases: {', '.join(assessment['suggested_sam_phrases'])}", ""]

    lines += ["### SAM 3.1", "", "| phrase | objects | best score | mask area | overlay |", "|---|---|---|---|---|"]
    all_layers = []
    for phrase, color in PHRASES.items():
        slug = phrase.replace(" ", "_")
        if client is None:
            lines.append(f"| {phrase} | skipped (dry run, est. ${cost_usd('sam-3.1', {'images_processed': 1}):.4f}) | | | |")
            continue
        objects = client.segment_image(jpeg, phrase, purpose="smoke:segment")
        layers = [Layer(mask=o.full_mask(image.width, image.height), color=color,
                        label=f"{phrase} #{o.object_id} {o.score or 0:.2f}") for o in objects]
        draw_layers(image, layers).save(out / f"sam_{slug}.png")
        all_layers += layers
        (out / f"sam_{slug}.json").write_text(json.dumps([describe(o) for o in objects], indent=2), encoding="utf-8")
        area = sum(o.area_px for o in objects)
        best = max((o.score or 0 for o in objects), default=0)
        print(f"[{out.name}] SAM '{phrase}': {len(objects)} object(s), best score {best:.2f}")
        lines.append(f"| {phrase} | {len(objects)} | {best:.2f} | {area} px "
                     f"({100 * area / (image.width * image.height):.1f}%) | `{out.name}/sam_{slug}.png` |")
    if all_layers:
        draw_layers(image, all_layers).save(out / "sam_all.png")
    return lines + [""]


def track_video(client: MetaClient | None, args: argparse.Namespace, out: Path) -> list[str]:
    out.mkdir(parents=True)
    clip = cut_clip(args.ep55_video, out / "clip.mp4", start_s=args.clip_start, duration_s=args.clip_seconds,
                    fps=args.clip_fps, height=args.clip_height)
    info = probe(clip)
    estimate = cost_usd("sam-3.1", {"video_frames_processed": max(info.frames, 50)})
    lines = ["## SAM 3.1 video tracking", "",
             f"Clip: `{args.ep55_video.name}` from {args.clip_start:.0f} s, {info.frames} frames at "
             f"{info.fps:g} fps, {info.width}x{info.height}. Phrase: \"{args.video_phrase}\". "
             f"Estimated cost ${estimate:.4f}.", ""]
    if client is None:
        return lines + ["Skipped (dry run).", ""]

    file_id = client.upload_video(clip)
    try:
        objects = client.segment_video(file_id, args.video_phrase, purpose="smoke:track", expected_frames=info.frames)
    finally:
        client.delete_file(file_id)

    by_frame: dict[int, list[SamObject]] = defaultdict(list)
    for obj in objects:
        by_frame[obj.frame_index].append(obj)
    ids = sorted({o.object_id for o in objects}, key=lambda i: int(i))
    colors = {object_id: TRACK_COLORS[n % len(TRACK_COLORS)] for n, object_id in enumerate(ids)}

    rendered = []
    for index, frame_path in enumerate(extract_frames(clip, out / "frames")):
        frame = Image.open(frame_path).convert("RGB")
        layers = [Layer(mask=o.full_mask(frame.width, frame.height), color=colors[o.object_id],
                        label=f"{args.video_phrase} #{o.object_id} {o.score or 0:.2f}")
                  for o in by_frame.get(index, [])]
        target = out / "overlay" / frame_path.name
        target.parent.mkdir(exist_ok=True)
        draw_layers(frame, layers).save(target, quality=90)
        rendered.append(target)
    assemble(rendered, out / "overlay.mp4", fps=info.fps)
    contact_sheet(rendered, out / "contact_sheet.jpg")

    tracks = {object_id: [describe(o) for o in objects if o.object_id == object_id] for object_id in ids}
    (out / "tracks.json").write_text(json.dumps(tracks, indent=2), encoding="utf-8")
    print(f"[video] {len(ids)} track(s) over {len(by_frame)}/{info.frames} frames")
    lines += [f"{len(ids)} track(s); objects found in {len(by_frame)} of {info.frames} frames. "
              "Overlay: `video/overlay.mp4`, `video/contact_sheet.jpg`.", "",
              "| track | frames present | first-last | mean area px | max box height px |",
              "|---|---|---|---|---|"]
    for object_id in ids:
        own = [o for o in objects if o.object_id == object_id]
        heights = [o.box[3] - o.box[1] for o in own]
        lines.append(f"| #{object_id} | {len(own)} | {own[0].frame_index}-{own[-1].frame_index} "
                     f"| {sum(o.area_px for o in own) / len(own):.0f} | {max(heights)} |")
    return lines + [""]


def contact_sheet(frames: list[Path], dst: Path, count: int = 6, columns: int = 3, width: int = 480) -> None:
    picks = [frames[round(i * (len(frames) - 1) / (count - 1))] for i in range(count)] if len(frames) >= count else frames
    thumbs = [Image.open(p).convert("RGB") for p in picks]
    for thumb in thumbs:
        thumb.thumbnail((width, width))
    cell_w, cell_h = max(t.width for t in thumbs), max(t.height for t in thumbs)
    rows = -(-len(thumbs) // columns)
    sheet = Image.new("RGB", (cell_w * columns, cell_h * rows))
    for i, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((i % columns) * cell_w, (i // columns) * cell_h))
    sheet.save(dst, quality=90)


def describe(obj: SamObject) -> dict:
    return {"object_id": obj.object_id, "frame": obj.frame_index, "box": list(obj.box),
            "score": obj.score, "area_px": obj.area_px}


def cost_section(conn, since: str, dry_run: bool) -> list[str]:
    if dry_run:
        return ["## Cost", "", "No API calls were made (dry run).", ""]
    rows = conn.execute(
        """SELECT model, COUNT(*) AS n, SUM(cost_usd) AS cost, SUM(1 - ok) AS failed
           FROM api_calls WHERE called_at >= ? AND purpose LIKE 'smoke:%' GROUP BY model""", (since,)
    ).fetchall()
    lines = ["## Cost", "", "| model | calls | failed | cost (USD) |", "|---|---|---|---|"]
    lines += [f"| {r['model']} | {r['n']} | {r['failed']} | {r['cost']:.4f} |" for r in rows]
    total = sum(r["cost"] for r in rows)
    print(f"[cost] ${total:.4f}")
    return lines + ["", f"Total: ${total:.4f}", ""]


if __name__ == "__main__":
    main()
