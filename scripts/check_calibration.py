"""Check a camera preset's calibration: the solved view, each reference's misfit, and an overlay.

Solves the preset in force at --at (config/calibration.yaml) with its Monte
Carlo and prints the view (azimuth, tilt, roll, focal length, distortion and
the field of view across the middle row, each with sigma) and, for every
reference, where it was picked and where the solved view puts it. Then draws
on the camera's stored frame nearest --at:
- each reference as picked (yellow cross) and as solved (magenta circle);
- the sea horizon (cyan) and the vent (red);
- a height scale above the vent (white): every 1,000 m above sea level, or
  every 50 m above the vent for a camera within 5 km of it.
The overlay goes to data/calibration/<camera>_<preset>_<frame time>.jpg.

    python scripts/check_calibration.py --camera kilauea-kp --at 2026-10-17T17:00Z
"""

from __future__ import annotations

import argparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from vigia import db
from vigia.calibration import load_calibration, sample_geometry
from vigia.geometry import REFRACTION_K, View, direction, horizon_dip, local_en, sight
from vigia.settings import Settings
from vigia.timeutil import parse_utc, to_iso


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--at", type=parse_utc, required=True, help="a capture time the preset covers")
    parser.add_argument("--samples", type=int, default=1000)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    calibration = load_calibration(settings.calibration_path)
    preset = calibration.preset_for(args.camera, args.at)
    if preset is None:
        raise SystemExit(f"no preset of {args.camera} covers {to_iso(args.at)}")
    camera = calibration.cameras[args.camera]
    try:
        geometry = sample_geometry(calibration, args.camera, preset, args.samples)
    except ValueError as exc:
        raise SystemExit(f"preset {preset.name}: {exc}")
    view = geometry.view
    nominal = View(view.yaw[:1], view.pitch[:1], view.roll[:1], view.focal[:1], view.cx, view.cy, view.k1[:1])
    edges = np.repeat(np.array([[[0.0, view.cy], [2 * view.cx, view.cy]]]), len(view.yaw), axis=0)
    left, right = view.ray(edges)[0].T
    hfov = (right - left) % 360  # the field of view across the middle row, distortion included
    print(f"{args.camera} / {preset.name}: RMS misfit {geometry.rms_px[0]:.2f} px")
    for name, values, unit in [("azimuth", view.yaw, "deg"), ("tilt", view.pitch, "deg"), ("roll", view.roll, "deg"),
                               ("focal", view.focal, "px"), ("k1", view.k1, ""), ("hfov", hfov, "deg")]:
        print(f"  {name:8s} {values[0]:9.3f} ± {values[1:].std():.3f} {unit}")

    origin = camera.position
    vent = calibration.vents[camera.volcano]

    def seen(site) -> np.ndarray:
        east, north = local_en(site.lat, site.lon, origin.lat, origin.lon)
        return nominal.project(sight(east, north, site.elev_m - origin.elev_m)[None, None])[0, 0]

    marks = [("vent", preset.vent_pixel.pixel, seen(vent))] if preset.vent_pixel else []
    marks += [(mark.name, mark.pixel, seen(mark)) for mark in preset.landmarks]
    marks += [(body.name, body.pixel, nominal.project(direction(body.az_deg, body.el_deg)[None, None])[0, 0])
              for body in preset.celestial]
    dip = float(horizon_dip(origin.elev_m, REFRACTION_K))
    for i, pick in enumerate(preset.horizon):
        azimuth, _ = nominal.ray(np.array([[pick.pixel]], dtype=float))
        marks.append((f"horizon {i + 1}", pick.pixel, nominal.project(direction(azimuth, -dip))[0, 0]))
    print("  reference          picked (col, row)      solved (col, row)      misfit")
    for name, picked, solved in marks:
        print(f"  {name:16s} ({picked[0]:7.1f}, {picked[1]:7.1f})  ({solved[0]:7.1f}, {solved[1]:7.1f})  "
              f"{np.hypot(*(np.asarray(picked) - solved)):6.1f} px")

    conn = db.connect(settings.db_path)
    frame = conn.execute(
        """SELECT * FROM frames WHERE camera_id = ? AND width = ? AND height = ?
           ORDER BY ABS(julianday(captured_at) - julianday(?)) LIMIT 1""",
        (args.camera, *preset.image_size, to_iso(args.at))).fetchone()
    conn.close()
    if frame is None:
        raise SystemExit(f"no stored {preset.image_size[0]}x{preset.image_size[1]} frame of {args.camera}")
    with Image.open(settings.data_dir / frame["path"]) as raw:
        image = raw.convert("RGB")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=max(14, image.width // 160))
    size = max(6, image.width // 300)
    for name, picked, solved in marks:
        x, y = picked
        draw.line([(x - size, y), (x + size, y)], fill=(255, 255, 0), width=2)
        draw.line([(x, y - size), (x, y + size)], fill=(255, 255, 0), width=2)
        draw.ellipse([solved[0] - size, solved[1] - size, solved[0] + size, solved[1] + size],
                     outline=(255, 0, 255), width=2)
        draw.text((x + size, y - 3 * size), name, fill=(255, 255, 0), font=font)
    azimuths = left[0] + np.linspace(0, hfov[0], 400)  # only across the frame: past its edges the lens folds back
    line = nominal.project(direction(azimuths, -dip)[None])[0]
    draw.line([tuple(p) for p in line if np.isfinite(p).all()], fill=(0, 255, 255), width=2)
    east, north = local_en(vent.lat, vent.lon, origin.lat, origin.lon)
    distance = float(np.hypot(east, north))
    ticks = ([(h - vent.elev_m, f"{h:,.0f} m a.s.l.") for h in range(2000, 11000, 1000)] if distance > 5000
             else [(h, f"{h} m") for h in range(0, 501, 50)])
    for height, label in ticks:
        x, y = nominal.project(sight(east, north, vent.elev_m + height - origin.elev_m)[None, None])[0, 0]
        if np.isfinite(x) and 0 <= y < image.height:
            draw.line([(x - 2 * size, y), (x + 2 * size, y)], fill=(255, 255, 255), width=2)
            draw.text((x + 3 * size, y - size), label, fill=(255, 255, 255), font=font)
    vx, vy = nominal.project(sight(east, north, vent.elev_m - origin.elev_m)[None, None])[0, 0]
    draw.ellipse([vx - size, vy - size, vx + size, vy + size], outline=(255, 0, 0), width=3)
    out = settings.data_dir / "calibration" / f"{args.camera}_{preset.name}_{frame['captured_at'][:16].replace(':', '')}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, quality=90)
    print(f"overlay: {out}")


if __name__ == "__main__":
    main()
