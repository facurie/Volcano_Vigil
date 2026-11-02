"""Compare our Kilauea episode 55 measurements with the official USGS values: docs/VALIDATION.md.

Run vigil-measure for kilauea-kp and kilauea-k2 over 2026-10-17
13:00-19:30Z first. This script reads those measurements, the fountain
tracks' last detections and the plume drift, and writes the comparison with
errors and sigmas. The plume drift is also checked against Open-Meteo's model
wind (vigil.wind; the day is fetched once, then read from the database). The
fountaining alerts come from the replays' databases (vigil-replay --episode 55
and --quiet overflows), read only. The official values and their sources are
in docs/research/episode55.md: they are compared with, never fitted.

    python scripts/validate_ep55.py
"""

from __future__ import annotations

import argparse
from contextlib import closing
from pathlib import Path

import httpx
import numpy as np

from vigil import db
from vigil.calibration import load_calibration
from vigil.config import load_sources
from vigil.episodes import (DRIFT_HEADER, END_HEADER, EP55, HEIGHT_HEADER, OVERFLOWS, drift_rows, end_rows,
                            height_row, table)
from vigil.replay import ALERT_HEADER, alert_looks, alert_rows, replay_dir
from vigil.settings import Settings
from vigil.timeutil import parse_utc, to_iso, utcnow
from vigil.wind import WindService, compare_drift


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("docs/VALIDATION.md"))
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    conn = db.connect(settings.db_path)
    rows = [height_row(conn, check, EP55.local) for check in EP55.checks]
    ends = end_rows(conn, EP55)
    drifts = drift_rows(conn, EP55)
    with httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=30) as http:
        winds = wind_rows(conn, WindService(conn, http, load_sources(settings.sources_path)),
                          load_calibration(settings.calibration_path).vents["kilauea"].elev_m)
    conn.close()
    args.out.write_text(report(rows, ends, drifts, winds, alerts_section(settings.data_dir)), encoding="utf-8")
    print(f"wrote {args.out}")
    for row in rows:
        print(" | ".join(row))


def wind_rows(conn, winds: WindService, vent_elev: float) -> list[list[str]]:
    """Each plume frame's drift side against the model wind: the mean between the vent and the frame's
    plume top, and the wind at the top alone."""
    rows = []
    for camera_id in EP55.cameras:
        pairs = conn.execute(
            """SELECT side.captured_at, side.value, top.value FROM measurements side
               JOIN measurements top ON top.detection_id = side.detection_id AND top.metric = 'top_altitude'
               WHERE side.camera_id = ? AND side.metric = 'drift_bearing' AND side.captured_at BETWEEN ? AND ?
               ORDER BY side.captured_at""", (camera_id, to_iso(EP55.start), to_iso(EP55.end))).fetchall()
        if not pairs:
            continue
        mean_checks, top_checks = [], []
        for captured_at, side, top in pairs:
            profile = winds.profile("kilauea", parse_utc(captured_at))
            mean_checks.append(compare_drift(side, profile.layer_mean(vent_elev, top)))
            top_checks.append(compare_drift(side, profile.at(top)))
        angles = [check.angle_deg for check in mean_checks]
        rows.append([camera_id, str(len(pairs)),
                     f"{sum(check.consistent is True for check in mean_checks)} of {len(pairs)}",
                     f"{np.median(angles):.0f}° ({min(angles):.0f}-{max(angles):.0f}°)",
                     f"{sum(check.consistent is True for check in top_checks)} of {len(pairs)}"])
    return rows


def alerts_section(data_dir: Path) -> str:
    """The fountaining alerts' replay of episode 55 against the official times, and the overflow frames' count of
    false alarms; a replay that has not been run is said so."""
    episode = replay_dir(data_dir, EP55) / "vigil.sqlite"
    if episode.is_file():
        with closing(db.connect_readonly(episode)) as conn:
            onset_end = f"{table(ALERT_HEADER, alert_rows(conn, EP55))}\n\n{alert_looks(conn)}."
    else:
        onset_end = f"No replay of episode 55 in `{episode.as_posix()}`: run `vigil-replay --episode 55`."
    quiet = data_dir / "replay" / OVERFLOWS.key / "vigil.sqlite"
    if quiet.is_file():
        with closing(db.connect_readonly(quiet)) as conn:
            fired = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
            looks = alert_looks(conn)
        overflows = (f"Over the overflow frames before the episode, {to_iso(OVERFLOWS.start)} to "
                     f"{to_iso(OVERFLOWS.end)}, {fired} alerts fired: {looks}. {OVERFLOWS.activity}")
    else:
        overflows = f"No replay of the overflow frames in `{quiet.as_posix()}`: run `vigil-replay --quiet overflows`."
    return f"{onset_end}\n\n{overflows}"


def report(rows: list[list[str]], ends: list[list[str]], drifts: list[list[str]], winds: list[list[str]],
           alerts: str) -> str:
    agree = sum(row[-1] == "yes" for row in rows)
    measured = sum(row[4] != "no measurement" for row in rows)
    return f"""# Validation: Kīlauea episode 55 (2026-10-17)

Generated by `scripts/validate_ep55.py` on {utcnow():%Y-%m-%d %H:%M} UTC from the measurements in
`data/vigil.sqlite`. Official values and their sources: [episode55.md](research/episode55.md).
Calibration: `config/calibration.yaml`, with the evidence in
[calibration_ep55.md](research/calibration_ep55.md).

**Method.** SAM 3.1 tracks the fountain on K2cam and the plume on KPcam (Phase 2). KPcam's view is
calibrated from nine Moon positions, K2cam's from its lens datasheet and the Puʻukoaʻe cone on its
skyline ([calibration_ep55.md](research/calibration_ep55.md)). Each mask's highest pixel is placed on
the vertical plane through the north vent, square to the camera's line of sight, with the camera's
solved azimuth, tilt, roll, focal length and lens distortion (`vigil/geometry.py`).
Fountain heights are above the vent (1,080 ± 5 m); plume tops are above sea level. Each value is the
nominal solution of a 1,000-sample Monte Carlo over the camera and vent positions, refraction, every
calibration pixel, the mask edge (±3 px) and a lean along the line of sight (5° fountains, 10°
plumes); σ is one standard deviation of the samples. The official values were never used to fit
anything.

**Rows.** A "max" row takes our highest frame inside HVO's stated window; a "mean" row averages our
frames within 5 minutes of the stated time, with σ the RMS of their sigmas (calibration errors do not
average out). "Agrees" means within 2σ, or under the bound for an "under" value.

## Heights: {agree} of {measured} measured rows agree ({len(rows) - measured} not measured)

{table(HEIGHT_HEADER, rows)}

HVO's own reports of the fountain's decline disagree with each other: "about 500 feet (150 m)" in its
message of 07:47 HST, and "about 300 feet (100 m) high by 8:00 a.m." in the daily update
([episode55.md](research/episode55.md)). The 08:00 row compares with the daily update.

A fountain top is the highest pixel of the `lava fountain` mask; at night it can include spray and the
glow lit on the plume just above the jet. A plume top is the highest point of the whole `steam` mask,
which downwind of the vent can be cloud from earlier, higher injection rather than the column. Both
are explained in [calibration_ep55.md](research/calibration_ep55.md).

## End of fountaining

The last frame on which SAM still tracks the fountain, against HVO's end at 09:03 HST (VAN 2026/H489;
the eruption table says 09:06). The cameras capture every 2 minutes.

{table(END_HEADER, ends)}

## Drift direction

HVO: the plume drifted to the southwest (VONA 2026/67 "MOV: SW"; winds below 20,000 ft from the
northeast). One camera sees only the drift's component across its line of sight, so each frame gives
the bearing of that side: KPcam looks southeast (134°), so its right-hand side points to 224°, almost
exactly southwest. K2cam looks south (185°); its right-hand side points to 275°.

{table(DRIFT_HEADER, drifts)}

## Drift against the forecast wind

Open-Meteo's model wind over the vent (Historical Forecast API, the hour nearest each frame, 850-300 hPa)
against the side of the line of sight each frame's plume was measured on (`vigil/wind.py`). A plume drifts
with the wind of the layer it fills, so the wind is averaged between the vent (1,080 m) and that frame's
plume top. The angle is between the measured side and where that mean wind blows; under 90° the wind
pushes the plume to the side it was seen on. The wind at the plume top alone is shown for contrast. The
model has the low-level wind from the north to north-northwest, while HVO reported it from the northeast.
K2cam looks south, almost along where that model wind blows, so its angles sit near 90° and say little.

{table(["Camera", "Frames", "Consistent with the layer-mean wind", "Angle to it: median (range)",
        "Consistent with the wind at the top"], winds)}

## Fountaining alerts (replay)

The alerts' watcher (`vigil/alerts.py`) replayed on a one-minute clock over the episode's frames: when it
first saw the fountain at episode size and last saw it, and when it raised each alert, against HVO's onset
and end and HVO's public notices. HVO dates the onset to 03:19 from tremor and tilt; the fountain shows on
V1cam from 03:03 ([alerts_calibration.md](research/alerts_calibration.md)).

{alerts}

## Limitations

- **One episode.** Every number here comes from episode 55; episode 56 will be the first test the
  calibration and the alerts' thresholds were not made on.
- **Official values are rounded reports,** in feet and without uncertainties ("about 650 ft", "under
  13,000 ft"), so an error of a few percent is within their own rounding.
- **Camera positions are estimates:** KPcam ±500 m (±3.6 % on distance), K2cam ±75 m (±4.5 %). Both are in
  the sigmas.
- **K2cam's lens is an inference.** Its model comes from HVO's list of cameras and its zoom is taken as the
  widest, which the 3DEP skyline supports; its distortion is not measured. A view zoomed in by 10 % would
  make every fountain height 10 % too high.
- **Tops are mask tops.** A plume top can be cloud downwind of the vent (the 07:30 row); a fountain top at
  night can include spray and glow. The lean along the line of sight is assumed (5° fountains, 10° plumes),
  not measured.
- **One camera sees only the drift's across-track side,** not its full direction.
- **The model wind disagrees with HVO below the plume:** Open-Meteo has the low-level wind from the north
  to north-northwest, HVO from the northeast.
"""


if __name__ == "__main__":
    main()
