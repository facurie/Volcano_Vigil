"""Mirror an episode's replay to a public Hugging Face dataset, and restore it from there.

The replay shows frames from the USGS AshCam archive, which keeps them for about 31 days, plus the replay's own
outputs: its database, timeline, report and bulletins. `push` uploads exactly those, laid out as they sit in the
data dir, together with a dataset card. `pull` puts them back where the dashboard looks for them. A server pulls
at every start, and files already up to date are not downloaded again.

    vigil-mirror push --episode 55 --repo facurie/volcano-vigil-ep55
    vigil-mirror pull --episode 55 --repo facurie/volcano-vigil-ep55
"""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from vigil import db
from vigil.agent.bulletin import DISCLAIMER_EN
from vigil.config import Volcano
from vigil.episodes import Episode
from vigil.replay import replay_dir
from vigil.timeutil import to_iso

DB_NAME = "vigil.sqlite"


def episode_files(data_dir: Path, episode: Episode) -> list[str]:
    """Everything the episode's replay needs besides its database, as POSIX paths relative to the data dir: first
    the frames its database lists, then the rest of its replay folder (timeline, report, bulletins). Raises
    FileNotFoundError if the replay's database or one of its frames is missing."""
    folder = replay_dir(data_dir, episode)
    database = folder / DB_NAME
    if not database.is_file():
        raise FileNotFoundError(f"{database} does not exist: run vigil-replay --episode {episode.key} first")
    with closing(db.connect_readonly(database)) as conn:
        frames = [row[0] for row in conn.execute("SELECT path FROM frames ORDER BY captured_at, id")]
    missing = [path for path in frames if not (data_dir / path).is_file()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} frame(s) of episode {episode.key} are missing, e.g. {missing[0]}")
    rest = sorted(path.relative_to(data_dir).as_posix() for path in folder.rglob("*")
                  if path.is_file() and not path.name.startswith(DB_NAME))
    return frames + rest


def snapshot_database(source: Path, target: Path) -> None:
    """Copy a SQLite database into `target` as one self-contained file. SQLite's backup folds in a writer's journal,
    so this is safe while other processes write to `source`, and the copy is switched to a rollback journal, so no
    `-wal` or `-shm` file travels with it. `vigil/persist.py` uses it too."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(db.connect_readonly(source)) as original, closing(sqlite3.connect(target)) as copy:
        original.backup(copy)
        copy.execute("PRAGMA journal_mode=DELETE")


def stage(data_dir: Path, episode: Episode, volcano: Volcano, out: Path) -> list[str]:
    """Lay out in `out` what `push` uploads: the episode's files, a copy of its replay database and the dataset
    card. The copy is made with SQLite's backup, so a writer's journal is folded in, and is switched to a rollback
    journal, so it is one self-contained file. Returns the staged paths."""
    files = episode_files(data_dir, episode)
    for path in files:
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(data_dir / path, target)
    database = (replay_dir(Path(), episode) / DB_NAME).as_posix()
    snapshot_database(data_dir / database, out / database)
    frame_count = sum(path.startswith("frames/") for path in files)
    (out / "README.md").write_text(dataset_card(episode, volcano, frame_count), encoding="utf-8")
    return files + [database, "README.md"]


def dataset_card(episode: Episode, volcano: Volcano, frame_count: int) -> str:
    """The dataset's README: what it holds, where it comes from, its licenses and the disclaimer."""
    words = {"name": volcano.name, "agency": volcano.official_agency, "url": volcano.official_url}
    key = episode.key
    return f"""---
license: cc-by-4.0
pretty_name: Volcano Vigil, {volcano.name} episode {key} replay
tags:
- volcano
- webcam
- segmentation
size_categories:
- n<1K
---

# Volcano Vigil: {volcano.name} episode {key}

The webcam frames and the replay that the Volcano Vigil dashboard shows for {volcano.name}'s episode {key}, from
{to_iso(episode.start)} to {to_iso(episode.end)} (UTC). The dashboard's server downloads this dataset when it
starts, because the USGS AshCam archive keeps frames for only about 31 days.

> {DISCLAIMER_EN.format(**words)}

## Contents

- `frames/<camera>/<date>/*.jpg`: {frame_count} frames from {", ".join(episode.cameras)}, from the USGS AshCam
  archive. Their exact capture times are in the database.
- `replay/ep{key}/vigil.sqlite`: the replay's SQLite database. It holds the frames, the quality verdicts, the SAM 3.1
  tracks and masks (COCO RLE), the measurements with their σ, the winds, the Muse Spark agent's runs and steps, and
  the bulletins.
- `replay/ep{key}/timeline.json`, `report.md`, `spark_phases.json`: the replay's timeline and its comparison with
  the official values.
- `replay/ep{key}/bulletins/run<N>/`: each bulletin in English and Spanish (Markdown and HTML) with its evidence
  images.

## Sources and licenses

- Frames: U.S. Geological Survey, Hawaiian Volcano Observatory webcams. Public domain; credit "U.S. Geological
  Survey".
- Winds in the database: Open-Meteo (https://open-meteo.com), CC BY 4.0.
- Everything else (masks, measurements, bulletins, timeline): Volcano Vigil, CC BY 4.0.
"""
