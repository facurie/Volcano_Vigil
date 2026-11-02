"""Mirror an episode's replay to a public Hugging Face dataset, and restore it from there.

The replay shows frames from the USGS AshCam archive, which keeps them for about 31 days, plus the replay's own
outputs: its database, timeline, report and bulletins. `push` uploads exactly those, laid out as they sit in the
data dir, together with a dataset card. `pull` puts them back where the dashboard looks for them. A server pulls
at every start, and files already up to date are not downloaded again.

    vigil-mirror push --episode 55 --repo facurie/volcano-vigil-ep55
    vigil-mirror pull --episode 55 --repo facurie/volcano-vigil-ep55
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
import tempfile
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi, snapshot_download

from vigil import db
from vigil.agent.bulletin import DISCLAIMER
from vigil.config import Volcano, load_sources
from vigil.episodes import EPISODES, Episode
from vigil.replay import replay_dir
from vigil.settings import Settings
from vigil.timeutil import to_iso

log = logging.getLogger(__name__)

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

> {DISCLAIMER.format(**words)}

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


def _patterns(episode: Episode) -> list[str]:
    """The dataset paths that belong to the episode's mirror."""
    return ["frames/**", f"replay/ep{episode.key}/**"]


def push(api: HfApi, data_dir: Path, episode: Episode, volcano: Volcano, repo_id: str) -> int:
    """Upload the episode's mirror to the public dataset `repo_id`, creating the dataset if needed. Mirrored files
    that the episode no longer has are deleted from the dataset. Returns how many files were uploaded."""
    with tempfile.TemporaryDirectory() as tmp:
        staged = stage(data_dir, episode, volcano, Path(tmp))
        api.create_repo(repo_id, repo_type="dataset", private=False, exist_ok=True)
        api.upload_folder(repo_id=repo_id, repo_type="dataset", folder_path=tmp,
                          commit_message=f"Mirror episode {episode.key}: {len(staged)} files",
                          delete_patterns=_patterns(episode))
    return len(staged)


def pull(data_dir: Path, episode: Episode, repo_id: str, *,
         download: Callable[..., Any] = snapshot_download) -> Path:
    """Restore the episode's mirror from the dataset `repo_id` into the data dir; returns the replay's database.
    Files already up to date are not downloaded again. If the Hub cannot be reached but an earlier pull left the
    database, the failure is logged and that copy is kept; without a copy it is raised."""
    database = replay_dir(data_dir, episode) / DB_NAME
    try:
        download(repo_id=repo_id, repo_type="dataset", local_dir=data_dir, allow_patterns=_patterns(episode))
    except Exception as exc:  # any Hub or network failure: the copy on disk, if there is one, still serves
        if not database.is_file():
            raise
        log.warning("episode %s: could not refresh the mirror from %s (%s); keeping the copy in %s",
                    episode.key, repo_id, exc, data_dir)
    if not database.is_file():
        raise FileNotFoundError(f"{repo_id} has no {database.relative_to(data_dir).as_posix()}")
    return database


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Mirror an episode's replay to a public Hugging Face dataset "
                                                 "(push), or restore it into the data dir (pull).")
    parser.add_argument("action", choices=["push", "pull"])
    parser.add_argument("--episode", required=True, help="episode key, e.g. 55")
    parser.add_argument("--repo", required=True, help="dataset id, e.g. facurie/volcano-vigil-ep55")
    args = parser.parse_args(argv)
    episode = EPISODES.get(args.episode)
    if episode is None:
        parser.error(f"no episode {args.episode!r}; known: {', '.join(EPISODES)}")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    if args.action == "push":
        volcano = load_sources(settings.sources_path).volcanoes[episode.volcano]
        count = push(HfApi(), settings.data_dir, episode, volcano, args.repo)
        print(f"episode {episode.key}: {count} files pushed to https://huggingface.co/datasets/{args.repo}")
    else:
        print(f"episode {episode.key} restored: {pull(settings.data_dir, episode, args.repo)}")


if __name__ == "__main__":
    main()
