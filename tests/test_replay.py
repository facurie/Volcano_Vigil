import json
import subprocess
from dataclasses import replace
from datetime import timedelta

import pytest

from test_agent_tools import T0, context, frame_jpeg
from test_bulletin import DRAFT
from vigia import db, replay
from vigia.agent.bulletin import BulletinDraft, CitedMeasurement, build_bulletin, store_bulletin
from vigia.episodes import EP55
from vigia.ingest.store import FrameStore
from vigia.phases import PHASES
from vigia.pipeline import StepReport
from vigia.replay import activity_rows, bulletin_rows, feed, main, run_replay, ticks
from vigia.timeutil import parse_utc, to_iso

M = timedelta(minutes=1)


@pytest.fixture
def source(tmp_path):
    """The database the episode's frames come from (live: data/vigia.sqlite)."""
    connection = db.connect(tmp_path / "source.sqlite")
    yield connection
    connection.close()


def add(source, tmp_path, camera_id, minutes):
    """A frame in the source database `minutes` from 15:00Z; returns its id."""
    captured_at = T0 + minutes * M
    return FrameStore(source, tmp_path).add(camera_id, frame_jpeg(minutes + 2000), captured_at=captured_at,
                                            timestamp_source="ashcam", fetched_at=captured_at)


class FakePipeline:
    """Records each step, and the newest frame the replay's database held when it ran."""

    def __init__(self, conn):
        self.conn, self.calls = conn, []

    def step(self, now, *, flush=False, agent=None):
        latest = self.conn.execute("SELECT MAX(captured_at) FROM frames").fetchone()[0]
        self.calls.append((now, flush, agent, latest))
        return StepReport(now, assessed=1)


def episode(start, end):
    return replace(EP55, start=start, end=end, cameras=("kilauea-kp",))


def test_ticks_step_to_the_end_and_stop_on_it():
    assert ticks(T0, T0 + 12 * M, 5 * M) == [T0 + 5 * M, T0 + 10 * M, T0 + 12 * M]


def test_feed_copies_the_frames_captured_by_the_clock_with_their_ids(source, conn, tmp_path):
    kp, k2, later, v1 = (add(source, tmp_path, camera, minutes) for camera, minutes in (
        ("kilauea-kp", -10), ("kilauea-k2", -5), ("kilauea-kp", 5), ("kilauea-v1", -5)))
    cameras, start = ("kilauea-kp", "kilauea-k2"), T0 - 60 * M

    assert feed(source, conn, cameras, start, T0) == {"kilauea-kp": 1, "kilauea-k2": 1}
    assert [row[0] for row in conn.execute("SELECT id FROM frames ORDER BY id")] == [kp, k2]
    assert feed(source, conn, cameras, start, T0) == {}
    assert feed(source, conn, cameras, start, T0 + 5 * M) == {"kilauea-kp": 1}


def test_the_replay_steps_the_pipeline_on_the_simulated_clock_and_nothing_after_it_exists(source, conn, tmp_path):
    for minutes in range(-28, 11, 4):  # 14:32 to 15:08
        add(source, tmp_path, "kilauea-kp", minutes)
    fake = FakePipeline(conn)

    timeline = run_replay(source, context(conn, tmp_path), episode(T0 - 30 * M, T0 + 12 * M), tmp_path / "replay",
                          step=10 * M, pipeline=fake)

    clocks = [T0 - 20 * M, T0 - 10 * M, T0, T0 + 10 * M, T0 + 12 * M]
    assert [call[0] for call in fake.calls] == clocks
    assert all(parse_utc(latest) <= now for now, _, _, latest in fake.calls)
    assert [call[1:3] for call in fake.calls] == [(False, None)] * 4 + [(True, True)]
    assert [tick["clock"] for tick in timeline["ticks"]] == [to_iso(clock) for clock in clocks]
    assert timeline["ticks"][0]["new_frames"] == {"kilauea-kp": 3}
    assert json.loads((tmp_path / "replay" / "timeline.json").read_text(encoding="utf-8")) == timeline
    assert (tmp_path / "replay" / "report.md").read_text(encoding="utf-8").startswith("# Replay of episode 55")


def test_an_interrupted_replay_resumes_after_its_last_stored_tick(source, conn, tmp_path):
    with conn:
        for clock in (T0 - 20 * M, T0 - 10 * M):
            conn.execute("INSERT INTO replay_ticks (clock, report) VALUES (?, ?)",
                         (to_iso(clock), json.dumps({"clock": to_iso(clock)})))
    fake = FakePipeline(conn)

    timeline = run_replay(source, context(conn, tmp_path), episode(T0 - 30 * M, T0 + 12 * M), tmp_path / "replay",
                          step=10 * M, pipeline=fake)

    assert [call[0] for call in fake.calls] == [T0, T0 + 10 * M, T0 + 12 * M]
    assert len(timeline["ticks"]) == 5


def test_speed_keeps_the_simulated_clock_at_most_that_many_times_faster_than_the_wall(source, conn, tmp_path):
    wall, slept = [0.0], []

    def sleep(seconds):
        slept.append(round(seconds, 6))
        wall[0] += seconds

    run_replay(source, context(conn, tmp_path), episode(T0, T0 + 30 * M), tmp_path / "replay", step=10 * M,
               speed=60, pipeline=FakePipeline(conn), sleep=sleep, monotonic=lambda: wall[0])

    assert slept == [10.0, 10.0]  # 10 simulated minutes at 60x: 10 s; the first step sets the origin


def bulletin_at(conn, tmp_path, clock, level="fountaining", measurements=()):
    draft = BulletinDraft.model_validate({**DRAFT, "activity_level": level, "measurements": [], "evidence": []})
    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 1, draft, tmp_path / "bulletins")
    return store_bulletin(conn, bulletin.model_copy(update={"clock": clock, "measurements": list(measurements)}))


def top(value, sigma, captured_at):
    return CitedMeasurement(camera_id="kilauea-kp", target="plume", metric="top_altitude", value=value, sigma=sigma,
                            unit="m", frame_ids=[29], verified=True, captured_at=captured_at)


def test_each_official_height_meets_the_first_bulletin_once_its_window_opens(conn, tmp_path):
    bulletin_at(conn, tmp_path, "2026-10-17T14:00:00Z", measurements=[top(5000, 300, "2026-10-17T13:55:05Z")])
    bulletin_at(conn, tmp_path, "2026-10-17T15:00:00Z", measurements=[top(6500, 350, "2026-10-17T14:45:05Z"),
                                                                     top(6951, 429, "2026-10-17T14:55:05Z")])
    bulletin_at(conn, tmp_path, "2026-10-17T16:00:00Z")

    rows = bulletin_rows(conn, EP55)

    assert rows[4] == ["plume top (peak)", "25,000 ft a.s.l., 04:50-05:10 (7,620 m)", "#2 at 05:00",
                       "6,951 ± 429 m at 04:55", "-669 m (-9 %)", "yes"]
    assert rows[0][2:4] == ["#2 at 05:00", "not quoted"]  # no bulletin quotes a fountain height
    assert rows[5][2:4] == ["#3 at 06:00", "not quoted"]
    assert rows[6][2:] == ["none", "", "", ""]  # no bulletin after 07:25


def test_activity_rows_say_when_fountaining_was_first_and_no_longer_reported(conn, tmp_path):
    for clock, level in (("2026-10-17T13:00:00Z", "degassing"), ("2026-10-17T14:00:00Z", "fountaining"),
                         ("2026-10-17T19:00:00Z", "fountaining"), ("2026-10-17T19:30:00Z", "degassing")):
        bulletin_at(conn, tmp_path, clock, level)

    assert activity_rows(conn, EP55) == [["fountaining first reported", "04:00", "03:19", "+41 min"],
                                         ["fountaining no longer reported", "09:30", "09:03", "+27 min"]]


def test_activity_rows_without_bulletins_say_never(conn):
    assert [row[1] for row in activity_rows(conn, EP55)] == ["never", "never"]


def test_cli_knows_only_the_stored_episodes(capsys):
    with pytest.raises(SystemExit):
        main(["--episode", "54"])

    assert "invalid choice" in capsys.readouterr().err


def test_the_replay_reuses_muse_sparks_stored_reading_of_the_timelapse(source, conn, tmp_path):
    stored = {phase: {"seen": False, "time": None} for phase in PHASES} | {"summary": "Nothing."}
    (tmp_path / "replay").mkdir()
    (tmp_path / "replay" / "spark_phases.json").write_text(json.dumps(stored), encoding="utf-8")

    timeline = run_replay(source, context(conn, tmp_path), episode(T0, T0 + 10 * M), tmp_path / "replay",
                          step=10 * M, pipeline=FakePipeline(conn))

    assert timeline["phases"]["muse_spark"] == stored
    assert [row[4] for row in timeline["phases"]["rows"]] == ["-"] * 4
    assert "## Episode phases" in (tmp_path / "replay" / "report.md").read_text(encoding="utf-8")


def test_without_a_client_or_a_stored_reading_muse_spark_is_not_asked(source, conn, tmp_path):
    timeline = run_replay(source, context(conn, tmp_path), episode(T0, T0 + 10 * M), tmp_path / "replay",
                          step=10 * M, pipeline=FakePipeline(conn))

    assert timeline["phases"]["muse_spark"] is None and timeline["phases"]["rows"][0][4] == "not asked"


def test_feed_ignores_a_frame_captured_before_the_episode_starts(source, conn, tmp_path):
    add(source, tmp_path, "kilauea-kp", -61)
    inside = add(source, tmp_path, "kilauea-kp", -60)

    assert feed(source, conn, ("kilauea-kp",), T0 - 60 * M, T0) == {"kilauea-kp": 1}
    assert [row[0] for row in conn.execute("SELECT id FROM frames")] == [inside]


def test_without_an_agent_schedule_the_last_step_does_not_force_one(source, conn, tmp_path):
    fake = FakePipeline(conn)

    run_replay(source, context(conn, tmp_path), episode(T0, T0 + 20 * M), tmp_path / "replay", step=10 * M,
               agent_every=None, pipeline=fake)

    assert [call[1:3] for call in fake.calls] == [(False, None), (True, None)]


def test_a_bulletin_that_quoted_nothing_has_no_numbers_to_have_checked(source, conn, tmp_path):
    bulletin_at(conn, tmp_path, "2026-10-17T14:00:00Z")
    bulletin_at(conn, tmp_path, "2026-10-17T15:00:00Z", measurements=[top(6951, 429, "2026-10-17T14:55:05Z")])

    run_replay(source, context(conn, tmp_path), episode(T0, T0 + 10 * M), tmp_path / "replay", step=10 * M,
               pipeline=FakePipeline(conn))

    report = (tmp_path / "replay" / "report.md").read_text(encoding="utf-8")
    assert [line.split(" | ")[-1] for line in report.splitlines() if line.startswith(("| 04:00", "| 05:00"))] == [
        "- |", "yes |"]


@pytest.mark.parametrize("error", [OSError("frame file is gone"), RuntimeError("the video has 3 frames"),
                                   subprocess.CalledProcessError(1, "ffmpeg")])
def test_a_timelapse_that_cannot_be_read_does_not_stop_the_replay(source, conn, tmp_path, monkeypatch, error):
    def ask(*args, **kwargs):
        raise error

    monkeypatch.setattr(replay, "ask_phases", ask)

    timeline = run_replay(source, context(conn, tmp_path, client="a Meta client"), episode(T0, T0 + 10 * M),
                          tmp_path / "replay", step=10 * M, pipeline=FakePipeline(conn))

    assert timeline["phases"]["muse_spark"] is None
    assert not (tmp_path / "replay" / "spark_phases.json").exists()
    assert json.loads((tmp_path / "replay" / "timeline.json").read_text(encoding="utf-8")) == timeline


def test_muse_sparks_reading_is_asked_once_and_kept(source, conn, tmp_path, monkeypatch):
    answer = {phase: {"seen": False, "time": None} for phase in PHASES} | {"summary": "Nothing."}
    asked = []
    monkeypatch.setattr(replay, "ask_phases", lambda *args, **kwargs: asked.append(args) or answer)
    base, out = context(conn, tmp_path, client="a Meta client"), tmp_path / "replay"

    first = run_replay(source, base, episode(T0, T0 + 10 * M), out, step=10 * M, pipeline=FakePipeline(conn))
    second = run_replay(source, base, episode(T0, T0 + 10 * M), out, step=10 * M, pipeline=FakePipeline(conn))

    assert len(asked) == 1 and first["phases"]["muse_spark"] == second["phases"]["muse_spark"] == answer
    assert json.loads((out / "spark_phases.json").read_text(encoding="utf-8")) == answer


def test_a_replay_stored_on_another_grid_is_not_resumed(source, conn, tmp_path):
    with conn:
        conn.execute("INSERT INTO replay_ticks (clock, report) VALUES (?, '{}')", (to_iso(T0 + 7 * M),))
    fake = FakePipeline(conn)

    with pytest.raises(ValueError, match=r"replay in .*delete that folder"):
        run_replay(source, context(conn, tmp_path), episode(T0, T0 + 30 * M), tmp_path / "replay", step=10 * M,
                   pipeline=fake)

    assert fake.calls == []


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigia.sqlite"))
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    return tmp_path / "data"


def test_cli_refuses_an_episode_with_no_stored_frames_and_leaves_no_replay_database(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--episode", "55"])

    assert "has no frames of episode 55" in capsys.readouterr().err
    assert not (cli_env / "replay").exists()


def test_cli_turns_a_replay_on_another_grid_into_a_usage_error(cli_env, capsys):
    with db.connect(cli_env / "vigia.sqlite") as source:
        FrameStore(source, cli_env).add("kilauea-kp", frame_jpeg(1), captured_at=EP55.start + 30 * M,
                                        timestamp_source="ashcam", fetched_at=EP55.start + 30 * M)
    with db.connect(cli_env / "replay" / "ep55" / "vigia.sqlite") as stored:
        stored.execute("INSERT INTO replay_ticks (clock, report) VALUES (?, '{}')", (to_iso(EP55.start + 7 * M),))

    with pytest.raises(SystemExit):
        main(["--episode", "55", "--no-video"])

    err = capsys.readouterr().err
    assert "ep55" in err and "delete that folder" in err
