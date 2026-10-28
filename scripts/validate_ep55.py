"""Compare our Kīlauea episode 55 measurements with the official USGS values: docs/VALIDATION.md.

Run vigia-measure for kilauea-kp and kilauea-k2 over 2026-10-17
13:00-19:30Z first. This script reads those measurements, the fountain
tracks' last detections and the plume drift, and writes the comparison with
errors and sigmas. The official values and their sources are in
docs/research/episode55.md: they are compared with, never fitted.

    python scripts/validate_ep55.py
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path

import numpy as np

from vigia import db
from vigia.settings import Settings
from vigia.timeutil import parse_utc, utcnow

FT = 0.3048
HST = timezone(timedelta(hours=-10))
EPISODE = ("2026-10-17T13:00:00Z", "2026-10-17T19:30:00Z")
OFFICIAL_END = "2026-10-17T19:03:00Z"  # 9:03 a.m. HST, VAN 2026/H489 (the eruption table says 9:06)
OFFICIAL_DRIFT_DEG = 225.0             # "MOV: SW" (VONA 2026/67), winds from the NE below 20,000 ft


@dataclass(frozen=True)
class Check:
    quantity: str
    camera_id: str
    target: str
    metric: str          # top_height: above the vent; top_altitude: above sea level
    start: str           # UTC window of our frames, inclusive
    end: str
    aggregate: str       # max: our highest frame in the window; mean: the window's average
    official_m: float
    official: str        # as HVO stated it
    source: str
    upper_bound: bool = False  # HVO said "under" this value


CHECKS = [
    Check("fountain height (peak)", "kilauea-k2", "fountain", "top_height", "2026-10-17T14:50:00Z",
          "2026-10-17T15:10:59Z", "max", 720 * FT, "720 ft, 04:50-05:10", "HVO Daily Update, Oct 17"),
    Check("fountain height", "kilauea-k2", "fountain", "top_height", "2026-10-17T15:57:00Z",
          "2026-10-17T16:07:59Z", "mean", 650 * FT, "about 650 ft at 06:02", "HVO message 06:02 HST"),
    Check("fountain height", "kilauea-k2", "fountain", "top_height", "2026-10-17T16:55:00Z",
          "2026-10-17T17:05:59Z", "mean", 500 * FT, "500 ft by 07:00", "HVO Daily Update, Oct 17"),
    Check("fountain height", "kilauea-k2", "fountain", "top_height", "2026-10-17T17:55:00Z",
          "2026-10-17T18:05:59Z", "mean", 300 * FT, "about 300 ft by 08:00", "HVO Daily Update, Oct 17"),
    Check("plume top (peak)", "kilauea-kp", "plume", "top_altitude", "2026-10-17T14:50:00Z",
          "2026-10-17T15:10:59Z", "max", 25000 * FT, "25,000 ft a.s.l., 04:50-05:10",
          "VONA 2026/67 (webcam); HVO Daily Update"),
    Check("plume top", "kilauea-kp", "plume", "top_altitude", "2026-10-17T15:57:00Z", "2026-10-17T16:07:59Z",
          "mean", 17000 * FT, "17,000 ft a.s.l. at 06:02", "HVO message 06:02 HST"),
    Check("plume top", "kilauea-kp", "plume", "top_altitude", "2026-10-17T17:25:00Z", "2026-10-17T17:35:59Z",
          "mean", 13000 * FT, "under 13,000 ft a.s.l. by 07:30", "HVO Daily Update, Oct 17", upper_bound=True),
]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("docs/VALIDATION.md"))
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    conn = db.connect(settings.db_path)
    rows = [height_row(conn, check) for check in CHECKS]
    ends = end_rows(conn)
    drifts = drift_rows(conn)
    conn.close()
    args.out.write_text(report(rows, ends, drifts), encoding="utf-8")
    print(f"wrote {args.out}")
    for row in rows:
        print(" | ".join(row))


def per_frame(conn, check: Check) -> list[tuple[str, float, float]]:
    """(capture time, value, sigma) per frame in the window: the highest detection on each frame."""
    found = conn.execute(
        """SELECT captured_at, value, sigma FROM measurements
           WHERE camera_id = ? AND target = ? AND metric = ? AND captured_at BETWEEN ? AND ?
           ORDER BY captured_at, value DESC""",
        (check.camera_id, check.target, check.metric, check.start, check.end)).fetchall()
    best = {}
    for captured_at, value, sigma in found:
        best.setdefault(captured_at, (captured_at, value, sigma))
    return list(best.values())


def height_row(conn, check: Check) -> list[str]:
    frames = per_frame(conn, check)
    window = f"{hst(check.start)}-{hst(check.end)}"
    official = f"{check.official} ({check.official_m:,.0f} m)"
    if not frames:
        return [check.quantity, window, check.camera_id, official, "no measurement", "", "", ""]
    values = np.array([f[1] for f in frames])
    sigmas = np.array([f[2] for f in frames])
    if check.aggregate == "max":
        i = int(values.argmax())
        value, sigma, how = values[i], sigmas[i], f"max of {len(frames)} frames, at {hst(frames[i][0])}"
    else:
        value, sigma = values.mean(), float(np.sqrt((sigmas ** 2).mean()))
        how = f"mean of {len(frames)} frames (spread {values.std():.0f} m)"
    error = value - check.official_m
    if check.upper_bound:
        verdict = "yes" if value - 2 * sigma <= check.official_m else "no"
        error_text = "within the bound" if value <= check.official_m else f"{error:+,.0f} m above it"
        z_text = f"{error / sigma:+.1f}" if value > check.official_m else "-"
    else:
        verdict = "yes" if abs(error) <= 2 * sigma else "no"
        error_text = f"{error:+,.0f} m ({100 * error / check.official_m:+.0f} %)"
        z_text = f"{error / sigma:+.1f}"
    ours = f"{value:,.0f} ± {sigma:,.0f} m ({value / FT:,.0f} ft); {how}"
    return [check.quantity, window, check.camera_id, official, ours, error_text, z_text, verdict]


def end_rows(conn) -> list[list[str]]:
    rows = []
    for camera_id, last in conn.execute(
            """SELECT r.camera_id, MAX(t.last_seen) FROM tracks t JOIN tracking_runs r ON r.id = t.run_id
               WHERE r.target = 'fountain' AND r.window_start >= ? AND r.window_end <= ?
               GROUP BY r.camera_id ORDER BY r.camera_id""", EPISODE):
        if last is None:
            continue
        minutes = (parse_utc(last) - parse_utc(OFFICIAL_END)).total_seconds() / 60
        rows.append([camera_id, hst(last, seconds=True), "09:03", f"{minutes:+.1f} min"])
    return rows


def drift_rows(conn) -> list[list[str]]:
    rows = []
    for camera_id in ("kilauea-kp", "kilauea-k2"):
        bearings = np.array([value for (value,) in conn.execute(
            """SELECT value FROM measurements WHERE camera_id = ? AND metric = 'drift_bearing'
               AND captured_at BETWEEN ? AND ?""", (camera_id, *EPISODE))])
        if not bearings.size:
            continue
        sides, counts = np.unique(np.round(bearings).astype(int), return_counts=True)
        main_side = int(sides[counts.argmax()])
        off = (main_side - OFFICIAL_DRIFT_DEG + 180) % 360 - 180
        share = ", ".join(f"{side}°: {count}" for side, count in zip(sides, counts))
        rows.append([camera_id, str(bearings.size), share, f"{main_side}° ({off:+.0f}° from SW)",
                     "yes" if abs(off) <= 90 else "no"])
    return rows


def hst(utc: str, seconds: bool = False) -> str:
    return parse_utc(utc).astimezone(HST).strftime("%H:%M:%S" if seconds else "%H:%M")


def table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join(lines + ["| " + " | ".join(row) + " |" for row in rows])


def report(rows: list[list[str]], ends: list[list[str]], drifts: list[list[str]]) -> str:
    agree = sum(row[-1] == "yes" for row in rows)
    return f"""# Validation: Kīlauea episode 55 (2026-10-17)

Generated by `scripts/validate_ep55.py` on {utcnow():%Y-%m-%d %H:%M} UTC from the measurements in
`data/vigia.sqlite`. Official values and their sources: [episode55.md](research/episode55.md).
Calibration: `config/calibration.yaml`, with the evidence in
[calibration_ep55.md](research/calibration_ep55.md).

**Method.** SAM 3.1 tracks the fountain on K2cam and the plume on KPcam (Phase 2). Each mask's highest
pixel is placed on the vertical plane through the north vent, square to the camera's line of sight,
with the camera's solved azimuth, tilt, roll, focal length and lens distortion (`vigia/geometry.py`).
Fountain heights are above the vent (1,080 ± 5 m); plume tops are above sea level. Each value is the
nominal solution of a 1,000-sample Monte Carlo over the camera and vent positions, refraction, every
calibration pixel, the mask edge (±3 px) and a lean along the line of sight (5° fountains, 10°
plumes); σ is one standard deviation of the samples. The official values were never used to fit
anything.

**Rows.** A "max" row takes our highest frame inside HVO's stated window; a "mean" row averages our
frames within 5 minutes of the stated time, with σ the RMS of their sigmas (calibration errors do not
average out). "Agrees" means within 2σ, or under the bound for an "under" value.

## Heights: {agree} of {len(rows)} agree

{table(["Quantity", "Window (HST)", "Camera", "Official", "Ours", "Error", "z", "Agrees"], rows)}

## End of fountaining

The last frame on which SAM still tracks the fountain, against HVO's end at 09:03 HST (VAN 2026/H489;
the eruption table says 09:06). The cameras capture every 2 minutes.

{table(["Camera", "Last fountain detection (HST)", "Official end (HST)", "Difference"], ends)}

## Drift direction

HVO: the plume drifted to the southwest (VONA 2026/67 "MOV: SW"; winds below 20,000 ft from the
northeast). One camera sees only the drift's component across its line of sight, so each frame gives
the bearing of that side: KPcam looks southeast (134°), so its right-hand side points to 224°, almost
exactly southwest. K2cam looks south (185°); its right-hand side points to 275°.

{table(["Camera", "Frames", "Across-track side (frames)", "Most frames", "Consistent with SW"], drifts)}
"""


if __name__ == "__main__":
    main()
