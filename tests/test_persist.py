import fnmatch
import logging
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from vigil import db
from vigil.persist import backup, main, restore, run

BUCKET = "facurie/vigil-state"
ROOT = f"hf://buckets/{BUCKET}/"


class FakeBucket:
    """The Hub's bucket API in memory: a bucket is a dict of path -> bytes, and `calls` lists the methods called."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.calls: list[str] = []
        self.fail: Exception | None = None

    def _enter(self, name):
        self.calls.append(name)
        if self.fail:
            raise self.fail

    def sync_bucket(self, source, dest, *, quiet=False, exclude=None):
        self._enter("sync_bucket")
        assert quiet, "the real sync_bucket prints a plan on every call: pass quiet=True"
        if source.startswith(ROOT):  # bucket -> local
            prefix = source.removeprefix(ROOT) + "/"
            for key, content in self.files.items():
                if key.startswith(prefix):
                    target = Path(dest) / key.removeprefix(prefix)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
        else:  # local -> bucket
            prefix = dest.removeprefix(ROOT)
            for path in Path(source).rglob("*"):
                if path.is_file() and not any(fnmatch.fnmatch(path.name, pattern) for pattern in exclude or ()):
                    self.files[f"{prefix}/{path.relative_to(source).as_posix()}"] = path.read_bytes()

    def batch_bucket_files(self, bucket_id, *, add):
        self._enter("batch_bucket_files")
        for source, key in add:
            self.files[key] = Path(source).read_bytes()

    def download_bucket_files(self, bucket_id, files, *, raise_on_missing_files=False):
        """Like the real API: a missing file is skipped silently unless `raise_on_missing_files` is set."""
        self._enter("download_bucket_files")
        for key, target in files:
            if key not in self.files:
                if raise_on_missing_files:
                    raise FileNotFoundError(key)
                continue
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            Path(target).write_bytes(self.files[key])

    def list_bucket_tree(self, bucket_id, *, recursive=None):
        """Like the real API: `recursive=False` lists the top-level folders, anything else lists every file with its
        full path."""
        self._enter("list_bucket_tree")
        if recursive is False:
            return [SimpleNamespace(path=name) for name in sorted({key.split("/")[0] for key in self.files})]
        return [SimpleNamespace(path=key) for key in sorted(self.files)]


@pytest.fixture
def data(tmp_path):
    """A data dir as the live services leave it: a frame, a bulletin image, a file of the replay and a database
    that has spent $0.42."""
    data = tmp_path / "data"
    (data / "frames" / "kilauea-kp" / "2026-11-01").mkdir(parents=True)
    (data / "frames" / "kilauea-kp" / "2026-11-01" / "a.jpg").write_bytes(b"frame")
    (data / "bulletins" / "run1").mkdir(parents=True)
    (data / "bulletins" / "run1" / "bulletin.html").write_bytes(b"<p>bulletin</p>")
    (data / "replay" / "ep55").mkdir(parents=True)
    (data / "replay" / "ep55" / "timeline.json").write_bytes(b"{}")
    with closing(db.connect(data / "vigil.sqlite")) as conn:
        conn.execute("INSERT INTO api_calls (called_at, model, purpose, cost_usd, ok) "
                     "VALUES ('2026-11-01T20:00:00Z', 'sam-3.1', 'segment', 0.42, 1)")
        conn.commit()
    return data


def spent(database):
    with closing(sqlite3.connect(database)) as conn:
        return conn.execute("SELECT SUM(cost_usd) FROM api_calls").fetchone()[0]


def test_backup_saves_the_frames_the_bulletins_and_the_database_but_not_the_replay(data):
    bucket = FakeBucket()

    backup(bucket, data, data / "vigil.sqlite", BUCKET)

    assert sorted(bucket.files) == ["bulletins/run1/bulletin.html", "db/vigil.sqlite",
                                    "frames/kilauea-kp/2026-11-01/a.jpg"]


def test_backup_leaves_out_a_frame_that_is_still_being_written(data):
    bucket = FakeBucket()
    (data / "frames" / "kilauea-kp" / "2026-11-01" / "b.jpg.part").write_bytes(b"half a frame")

    backup(bucket, data, data / "vigil.sqlite", BUCKET)

    assert "frames/kilauea-kp/2026-11-01/b.jpg.part" not in bucket.files
    assert "frames/kilauea-kp/2026-11-01/a.jpg" in bucket.files


def test_the_saved_database_is_one_self_contained_copy_with_the_ledger(data, tmp_path):
    bucket = FakeBucket()

    backup(bucket, data, data / "vigil.sqlite", BUCKET)

    saved = tmp_path / "saved.sqlite"
    saved.write_bytes(bucket.files["db/vigil.sqlite"])
    with closing(sqlite3.connect(saved)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert spent(saved) == 0.42


def test_backup_saves_the_files_before_the_database(data):
    bucket = FakeBucket()

    backup(bucket, data, data / "vigil.sqlite", BUCKET)

    assert bucket.calls == ["sync_bucket", "sync_bucket", "batch_bucket_files"]


def test_restore_brings_back_what_backup_saved(data, tmp_path):
    bucket = FakeBucket()
    backup(bucket, data, data / "vigil.sqlite", BUCKET)
    fresh = tmp_path / "fresh"

    restored = restore(bucket, fresh, fresh / "vigil.sqlite", BUCKET)

    assert restored is True
    assert (fresh / "frames" / "kilauea-kp" / "2026-11-01" / "a.jpg").read_bytes() == b"frame"
    assert (fresh / "bulletins" / "run1" / "bulletin.html").read_bytes() == b"<p>bulletin</p>"
    assert spent(fresh / "vigil.sqlite") == 0.42


def test_restore_of_an_empty_bucket_is_a_first_start(tmp_path):
    fresh = tmp_path / "fresh"

    restored = restore(FakeBucket(), fresh, fresh / "vigil.sqlite", BUCKET)

    assert restored is False
    assert not (fresh / "vigil.sqlite").exists()


def test_restore_fails_when_the_bucket_lists_a_database_it_cannot_download(tmp_path):
    bucket = FakeBucket()
    bucket.files = {"db/other": b""}  # the root lists `db`, but `db/vigil.sqlite` is absent

    with pytest.raises(FileNotFoundError):
        restore(bucket, tmp_path, tmp_path / "vigil.sqlite", BUCKET)


def test_restore_fails_when_the_bucket_cannot_be_reached(tmp_path):
    bucket = FakeBucket()
    bucket.fail = OSError("network is unreachable")

    with pytest.raises(OSError, match="unreachable"):
        restore(bucket, tmp_path, tmp_path / "vigil.sqlite", BUCKET)


class Saver:
    """A stand-in for `backup` that counts its calls, sets `stop` on the second one and fails on those in `failing`."""

    def __init__(self, stop, failing=()):
        self.stop, self.failing, self.calls = stop, set(failing), 0

    def __call__(self, api, data_dir, db_path, bucket):
        self.calls += 1
        if self.calls == 2:
            self.stop.set()
        if self.calls in self.failing:
            raise OSError("boom")


def test_run_saves_every_interval_and_once_more_when_stopped(tmp_path):
    stop = threading.Event()
    save = Saver(stop)

    run(None, tmp_path, tmp_path / "vigil.sqlite", BUCKET, 0.01, stop, save=save)

    assert save.calls == 3


def test_run_goes_on_after_a_failed_save(tmp_path, caplog):
    stop = threading.Event()
    save = Saver(stop, failing={1})

    with caplog.at_level(logging.ERROR):
        run(None, tmp_path, tmp_path / "vigil.sqlite", BUCKET, 0.01, stop, save=save)

    assert save.calls == 3
    assert "boom" in caplog.text


def test_cli_refuses_an_interval_that_is_not_positive(capsys):
    with pytest.raises(SystemExit):
        main(["run", "--bucket", BUCKET, "--interval", "0"])

    assert "--interval" in capsys.readouterr().err
