"""Keep the live state across restarts of a Hugging Face Docker Space, whose disk is lost whenever it restarts.

The state goes to a private Hugging Face bucket: the frames and the bulletins as files, and the database as one
self-contained copy. They are saved in that order, so a saved row never points at a file the bucket lacks. `restore`
runs at every start; `run` saves every few minutes and once more when it is stopped. A restart therefore costs at
most the last interval of work, and the Meta API cost ledger, a table of the database, keeps the daily cap across
restarts.

    vigil-persist restore --bucket facurie/vigil-state
    vigil-persist run --bucket facurie/vigil-state --interval 300
"""

from __future__ import annotations

import argparse
import logging
import signal
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi

from vigil.mirror import snapshot_database
from vigil.settings import Settings

log = logging.getLogger(__name__)

FOLDERS = ("frames", "bulletins")  # saved as files, before the database
DB_KEY = "db/vigil.sqlite"


def _uri(bucket: str, *parts: str) -> str:
    return "/".join(["hf://buckets", bucket, *parts])


def backup(api: Any, data_dir: Path, db_path: Path, bucket: str) -> None:
    """Save the frames and bulletins under `data_dir` and then the database at `db_path` to `bucket`. A frame still
    being written (`*.part`) is skipped. Only changed files are transferred, and files deleted here stay in the
    bucket. The database is copied with SQLite's backup, which is safe while other processes write to it."""
    for name in FOLDERS:
        if (data_dir / name).is_dir():
            api.sync_bucket(str(data_dir / name), _uri(bucket, name), quiet=True, exclude=["*.part"])
    if db_path.is_file():
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / db_path.name
            snapshot_database(db_path, copy)
            api.batch_bucket_files(bucket, add=[(copy, DB_KEY)])


def restore(api: Any, data_dir: Path, db_path: Path, bucket: str) -> bool:
    """Put what `backup` saved back under `data_dir` and at `db_path`. Returns False when the bucket holds no
    database yet, which is the very first start. Any failure to read the bucket is raised, so a service never runs
    on an empty database while a good copy exists."""
    saved = {item.path for item in api.list_bucket_tree(bucket, recursive=False)}
    for name in FOLDERS:
        if name in saved:
            api.sync_bucket(_uri(bucket, name), str(data_dir / name), quiet=True)
    if "db" not in saved:
        return False
    db_path.parent.mkdir(parents=True, exist_ok=True)
    api.download_bucket_files(bucket, [(DB_KEY, db_path)], raise_on_missing_files=True)
    return True


def run(api: Any, data_dir: Path, db_path: Path, bucket: str, interval: float, stop: threading.Event, *,
        save: Callable[..., None] = backup) -> None:
    """Save every `interval` seconds until `stop` is set, and once more after that. A failed save is logged and the
    next one is tried: the network may be down for a while."""

    def attempt() -> None:
        try:
            save(api, data_dir, db_path, bucket)
        except Exception:
            log.exception("could not save the state to %s; trying again in %s s", bucket, interval)

    while True:
        attempt()
        if stop.wait(interval):
            break
    attempt()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Save the live state to a Hugging Face bucket (backup, run) and "
                                                 "put it back (restore).")
    parser.add_argument("action", choices=["restore", "backup", "run"])
    parser.add_argument("--bucket", required=True, help="bucket id, e.g. facurie/vigil-state")
    parser.add_argument("--interval", type=float, default=300.0, help="seconds between saves for `run` (default 300)")
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be positive")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    api = HfApi()
    if args.action == "restore":
        restored = restore(api, settings.data_dir, settings.db_path, args.bucket)
        print(f"state restored from {args.bucket}" if restored else f"{args.bucket} holds no state yet: first start")
    elif args.action == "backup":
        backup(api, settings.data_dir, settings.db_path, args.bucket)
        print(f"state saved to {args.bucket}")
    else:
        stop = threading.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.set())
        run(api, settings.data_dir, settings.db_path, args.bucket, args.interval, stop)


if __name__ == "__main__":
    main()
