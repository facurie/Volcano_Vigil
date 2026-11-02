import logging
import shutil
import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import make_jpeg
from vigil import db
from vigil.config import Volcano
from vigil.episodes import EPISODES
from vigil.ingest.store import FrameStore
from vigil.mirror import dataset_card, episode_files, main, pull, push, stage
from vigil.replay import replay_dir
from vigil.timeutil import parse_utc

EP = EPISODES["55"]
KILAUEA = Volcano(name="Kīlauea", country="United States (Hawaiʻi)",
                  official_agency="USGS Hawaiian Volcano Observatory (HVO)",
                  official_url="https://www.usgs.gov/volcanoes/kilauea", lat=19.405, lon=-155.290,
                  utc_offset_hours=-10)
T0 = parse_utc("2026-10-17T14:55:05Z")


@pytest.fixture
def data(tmp_path):
    """A data dir with a small episode 55 replay: two frames in the replay's database, one frame only the live
    database has, the replay's timeline and one bulletin image."""
    data = tmp_path / "data"
    with closing(db.connect(replay_dir(data, EP) / "vigil.sqlite")) as conn:
        store = FrameStore(conn, data)
        store.add("kilauea-kp", make_jpeg((200, 80, 40)), captured_at=T0, timestamp_source="ashcam", fetched_at=T0)
        store.add("kilauea-k2", make_jpeg((40, 200, 80)), captured_at=T0 + timedelta(minutes=1),
                  timestamp_source="ashcam", fetched_at=T0)
    with closing(db.connect(data / "vigil.sqlite")) as live:
        later = parse_utc("2026-10-31T20:00:00Z")
        FrameStore(live, data).add("kilauea-kp", make_jpeg((80, 40, 200)), captured_at=later,
                                   timestamp_source="ashcam", fetched_at=later)
    folder = replay_dir(data, EP)
    (folder / "timeline.json").write_text("{}", encoding="utf-8")
    (folder / "bulletins" / "run1").mkdir(parents=True)
    (folder / "bulletins" / "run1" / "frame1_plume.jpg").write_bytes(make_jpeg())
    return data


def replay_frames(data):
    with closing(sqlite3.connect(replay_dir(data, EP) / "vigil.sqlite")) as conn:
        return [row[0] for row in conn.execute("SELECT path FROM frames ORDER BY captured_at")]


def test_episode_files_are_the_replays_frames_then_the_rest_of_its_folder(data):
    files = episode_files(data, EP)

    assert files == [*replay_frames(data), "replay/ep55/bulletins/run1/frame1_plume.jpg", "replay/ep55/timeline.json"]


def test_episode_files_leave_out_the_database_and_its_journal(data):
    (replay_dir(data, EP) / "vigil.sqlite-wal").write_bytes(b"")

    assert not [path for path in episode_files(data, EP) if "vigil.sqlite" in path]


def test_a_missing_frame_stops_the_mirror(data):
    (data / replay_frames(data)[0]).unlink()

    with pytest.raises(FileNotFoundError, match="missing"):
        episode_files(data, EP)


def test_an_episode_never_replayed_cannot_be_mirrored(tmp_path):
    with pytest.raises(FileNotFoundError, match="vigil-replay"):
        episode_files(tmp_path, EP)


def test_stage_lays_the_files_out_as_in_the_data_dir(data, tmp_path):
    out = tmp_path / "out"

    staged = stage(data, EP, KILAUEA, out)

    assert staged == [*episode_files(data, EP), "replay/ep55/vigil.sqlite", "README.md"]
    for path in episode_files(data, EP):
        assert (out / path).read_bytes() == (data / path).read_bytes()


def test_the_staged_database_is_one_self_contained_file(data, tmp_path):
    out = tmp_path / "out"

    stage(data, EP, KILAUEA, out)

    copy = out / "replay" / "ep55" / "vigil.sqlite"
    assert sorted(path.name for path in copy.parent.iterdir() if path.name.startswith("vigil.sqlite")) == [
        "vigil.sqlite"]
    with closing(sqlite3.connect(copy)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == 2


def test_the_dataset_card_credits_the_sources_and_carries_the_disclaimer():
    card = dataset_card(EP, KILAUEA, frame_count=468)

    assert card.startswith("---\nlicense: cc-by-4.0\n")
    assert "468 frames" in card
    assert "U.S. Geological Survey" in card and "public domain" in card.lower()
    assert "Open-Meteo" in card and "CC BY 4.0" in card
    assert "does not replace official alerts" in card
    assert "each bulletin (Markdown and HTML)" in card and "Spanish" not in card
    assert "https://www.usgs.gov/volcanoes/kilauea" in card
    assert "2026-10-17T13:00:00Z" in card and "2026-10-17T19:30:00Z" in card


REPO = "facurie/volcano-vigil-ep55"


class FakeApi:
    """Records what `push` asks of the Hub, and the files the folder held when it was uploaded."""

    def __init__(self):
        self.created, self.uploads = [], []

    def create_repo(self, repo_id, **kwargs):
        self.created.append((repo_id, kwargs))

    def upload_folder(self, **kwargs):
        folder = kwargs["folder_path"]
        files = sorted(path.relative_to(folder).as_posix() for path in Path(folder).rglob("*") if path.is_file())
        self.uploads.append({**kwargs, "files": files})


def test_push_creates_the_public_dataset_and_uploads_the_staged_episode(data):
    api = FakeApi()

    count = push(api, data, EP, KILAUEA, REPO)

    assert api.created == [(REPO, {"repo_type": "dataset", "private": False, "exist_ok": True})]
    [upload] = api.uploads
    assert upload["repo_id"] == REPO and upload["repo_type"] == "dataset"
    assert upload["delete_patterns"] == ["frames/**", "replay/ep55/**"]
    assert upload["files"] == sorted([*episode_files(data, EP), "replay/ep55/vigil.sqlite", "README.md"])
    assert count == len(upload["files"])


def copying_download(source):
    """A stand-in for snapshot_download that copies a staged mirror into local_dir."""
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        shutil.copytree(source, kwargs["local_dir"], dirs_exist_ok=True)
        return str(kwargs["local_dir"])

    return download, calls


def test_pull_restores_the_mirror_where_the_dashboard_looks(data, tmp_path):
    staged = tmp_path / "staged"
    stage(data, EP, KILAUEA, staged)
    download, calls = copying_download(staged)
    fresh = tmp_path / "fresh"

    database = pull(fresh, EP, REPO, download=download)

    assert database == replay_dir(fresh, EP) / "vigil.sqlite"
    assert calls == [{"repo_id": REPO, "repo_type": "dataset", "local_dir": fresh,
                      "allow_patterns": ["frames/**", "replay/ep55/**"]}]
    for path in episode_files(fresh, EP):
        assert (fresh / path).read_bytes() == (data / path).read_bytes()


def test_pull_keeps_the_copy_it_has_when_the_hub_cannot_be_reached(data, caplog):
    def unreachable(**kwargs):
        raise OSError("network is unreachable")

    with caplog.at_level(logging.WARNING):
        database = pull(data, EP, REPO, download=unreachable)

    assert database == replay_dir(data, EP) / "vigil.sqlite"
    assert "network is unreachable" in caplog.text


def test_pull_fails_without_a_copy_when_the_hub_cannot_be_reached(tmp_path):
    def unreachable(**kwargs):
        raise OSError("network is unreachable")

    with pytest.raises(OSError):
        pull(tmp_path, EP, REPO, download=unreachable)


def test_pull_fails_when_the_dataset_lacks_the_episode(tmp_path):
    with pytest.raises(FileNotFoundError, match="replay/ep55/vigil.sqlite"):
        pull(tmp_path, EP, REPO, download=lambda **kwargs: str(kwargs["local_dir"]))


def test_cli_refuses_an_unknown_episode(capsys):
    with pytest.raises(SystemExit):
        main(["push", "--episode", "99", "--repo", REPO])

    assert "no episode '99'" in capsys.readouterr().err
