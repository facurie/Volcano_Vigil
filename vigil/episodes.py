"""Past eruptive episodes the replay can run, and the official values to compare its results with.

Episode 55 of Kīlauea's summit eruption, on 2026-10-17. The official values and their sources are in
docs/research/episode55.md; they are compared with, never fitted. scripts/validate_ep55.py writes
docs/VALIDATION.md from these rows, and vigil.replay compares a replay with them.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

from vigil.timeutil import parse_utc, to_iso

FT = 0.3048
HST = timezone(timedelta(hours=-10))
HEIGHT_HEADER = ["Quantity", "Window (HST)", "Camera", "Official", "Ours", "Error", "z", "Agrees"]
END_HEADER = ["Camera", "Last fountain detection (HST)", "Official end (HST)", "Difference"]
DRIFT_HEADER = ["Camera", "Frames", "Across-track side (frames)", "Most frames", "Consistent with SW"]


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


@dataclass(frozen=True)
class Episode:
    key: str
    volcano: str
    cameras: tuple[str, ...]  # the cameras the replay feeds, in the order the rows list them
    start: datetime           # UTC span of the stored frames
    end: datetime
    local: timezone           # the volcano's local time, for the rows
    timelapse_camera: str     # a fixed camera that shows the whole episode, for Muse Spark's reading of it
    checks: tuple[Check, ...]
    phases: dict[str, tuple[datetime, datetime]]  # onset, peak, decline, end: earliest and latest official UTC time
    drift_deg: float          # the official drift direction (towards)
    drift_name: str           # how the official source names it
    notices: dict[str, datetime] = field(default_factory=dict)  # HVO's onset and end notices (VAN), UTC


EP55 = Episode(
    key="55", volcano="kilauea", cameras=("kilauea-kp", "kilauea-k2", "kilauea-v1"),
    start=parse_utc("2026-10-17T13:00:00Z"), end=parse_utc("2026-10-17T19:30:00Z"), local=HST,
    timelapse_camera="kilauea-k2",
    checks=(
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
    ),
    phases={
        "onset": (parse_utc("2026-10-17T13:19:00Z"),) * 2,     # 3:19 a.m. HST
        "peak": (parse_utc("2026-10-17T14:50:00Z"), parse_utc("2026-10-17T15:10:00Z")),  # 720 ft, 04:50-05:10
        "decline": (parse_utc("2026-10-17T15:10:00Z"), parse_utc("2026-10-17T16:02:00Z")),  # 650 ft by 06:02
        "end": (parse_utc("2026-10-17T19:03:00Z"),) * 2,       # 9:03 a.m. HST, VAN 2026/H489 (the table: 9:06)
    },
    drift_deg=225.0,  # "MOV: SW" (VONA 2026/67), winds from the NE below 20,000 ft
    drift_name="SW",
    notices={"onset": parse_utc("2026-10-17T13:43:00Z"),  # VAN 2026/H488, 03:43 HST
             "end": parse_utc("2026-10-17T19:11:00Z")},   # VAN 2026/H489, 09:11 HST
)
EPISODES = {EP55.key: EP55}


@dataclass(frozen=True)
class QuietWindow:
    """Frames with no eruptive episode in them, to test the fountaining alerts on: any alert here is a false alarm."""
    key: str
    volcano: str
    start: datetime
    end: datetime
    activity: str  # what the official record says was going on


OVERFLOWS = QuietWindow(
    key="overflows", volcano="kilauea",
    start=parse_utc("2026-10-16T08:00:00Z"), end=parse_utc("2026-10-17T13:00:00Z"),
    activity=("The 29 hours before episode 55 (22:00 HST Oct 15 to 03:00 HST Oct 17): overflows from the south vent "
              "(continuous from 05:56 HST Oct 16), the north vent (intermittent from 18:11, continuous from 23:35) "
              "and the west vent (from 22:49, continuous from 02:23), with small dome fountains; episode 55 began "
              "at 03:19 HST (HVO Daily Update, Oct 17)."),
)
QUIET_WINDOWS = {OVERFLOWS.key: OVERFLOWS}


def local_time(utc: str, tz: timezone, seconds: bool = False) -> str:
    return parse_utc(utc).astimezone(tz).strftime("%H:%M:%S" if seconds else "%H:%M")


def table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join(lines + ["| " + " | ".join(row) + " |" for row in rows])


def per_frame(conn: sqlite3.Connection, check: Check) -> list[tuple[str, float, float]]:
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


def height_row(conn: sqlite3.Connection, check: Check, tz: timezone) -> list[str]:
    frames = per_frame(conn, check)
    window = f"{local_time(check.start, tz)}-{local_time(check.end, tz)}"
    official = f"{check.official} ({check.official_m:,.0f} m)"
    if not frames:
        return [check.quantity, window, check.camera_id, official, "no measurement", "", "", ""]
    values = np.array([f[1] for f in frames])
    sigmas = np.array([f[2] for f in frames])
    if check.aggregate == "max":
        i = int(values.argmax())
        value, sigma, how = values[i], sigmas[i], f"max of {len(frames)} frames, at {local_time(frames[i][0], tz)}"
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


def end_rows(conn: sqlite3.Connection, episode: Episode) -> list[list[str]]:
    official = episode.phases["end"][0]
    rows = []
    for camera_id, last in conn.execute(
            """SELECT r.camera_id, MAX(t.last_seen) FROM tracks t JOIN tracking_runs r ON r.id = t.run_id
               WHERE r.target = 'fountain' AND r.window_start >= ? AND r.window_end <= ?
               GROUP BY r.camera_id ORDER BY r.camera_id""", (to_iso(episode.start), to_iso(episode.end))):
        if last is None:
            continue
        minutes = (parse_utc(last) - official).total_seconds() / 60
        rows.append([camera_id, local_time(last, episode.local, seconds=True),
                     local_time(to_iso(official), episode.local), f"{minutes:+.1f} min"])
    return rows


def drift_rows(conn: sqlite3.Connection, episode: Episode) -> list[list[str]]:
    rows = []
    for camera_id in episode.cameras:
        bearings = np.array([value for (value,) in conn.execute(
            """SELECT value FROM measurements WHERE camera_id = ? AND metric = 'drift_bearing'
               AND captured_at BETWEEN ? AND ?""", (camera_id, to_iso(episode.start), to_iso(episode.end)))])
        if not bearings.size:
            continue
        sides, counts = np.unique(np.round(bearings).astype(int), return_counts=True)
        main_side = int(sides[counts.argmax()])
        off = (main_side - episode.drift_deg + 180) % 360 - 180
        share = ", ".join(f"{side}°: {count}" for side, count in zip(sides, counts))
        rows.append([camera_id, str(bearings.size), share, f"{main_side}° ({off:+.0f}° from {episode.drift_name})",
                     "yes" if abs(off) < 90 else "no"])
    return rows
