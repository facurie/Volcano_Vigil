import json
import subprocess
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import httpx
import openai
import pytest

from test_agent_tools import T0, context, frame_jpeg
from test_alerts import LARGE, SMALL, V1_ONLY, Fakes, make_alert, scene_jpeg
from test_bulletin import DRAFT
from test_meta_client import FakeApi, make_client
from vigil.alerts import AlertWatcher, store_alert
from vigil import db, replay
from vigil.agent.bulletin import BulletinDraft, CitedMeasurement, build_bulletin, store_bulletin
from vigil.episodes import EP55, QUIET_WINDOWS
from vigil.ingest.store import FrameStore
from vigil.meta.client import MetaClient
from vigil.phases import PHASES
from vigil.pipeline import StepReport
from vigil.replay import (ALERT_HEADER, OffGridError, activity_rows, alert_rows, bulletin_rows, feed, main,
                          quiet_report, replay_alerts, replay_dir, run_replay, ticks)
from vigil.timeutil import parse_utc, to_iso

M = timedelta(minutes=1)


@pytest.fixture
def source(tmp_path):
    """The database the episode's frames come from (live: data/vigil.sqlite)."""
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
    assert "| Time (local) | Activity | Headline | Numbers checked |" in report
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

    with pytest.raises(OffGridError, match=r"replay in .*delete that folder"):
        run_replay(source, context(conn, tmp_path), episode(T0, T0 + 30 * M), tmp_path / "replay", step=10 * M,
                   pipeline=fake)

    assert fake.calls == []


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigil.sqlite"))
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    return tmp_path / "data"


def test_cli_refuses_an_episode_with_no_stored_frames_and_leaves_no_replay_database(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--episode", "55"])

    assert "has no frames of episode 55" in capsys.readouterr().err
    assert not (cli_env / "replay").exists()


def test_cli_turns_a_replay_on_another_grid_into_a_usage_error(cli_env, capsys):
    with db.connect(cli_env / "vigil.sqlite") as source:
        FrameStore(source, cli_env).add("kilauea-kp", frame_jpeg(1), captured_at=EP55.start + 30 * M,
                                        timestamp_source="ashcam", fetched_at=EP55.start + 30 * M)
    with db.connect(cli_env / "replay" / "ep55" / "vigil.sqlite") as stored:
        stored.execute("INSERT INTO replay_ticks (clock, report) VALUES (?, '{}')", (to_iso(EP55.start + 7 * M),))

    with pytest.raises(SystemExit):
        main(["--episode", "55", "--no-video"])

    err = capsys.readouterr().err
    assert "ep55" in err and "delete that folder" in err


def test_an_episodes_replay_lives_in_its_own_folder_of_the_data_dir():
    assert replay_dir(Path("data"), EP55) == Path("data") / "replay" / "ep55"


def alert_source(tmp_path):
    """A source database with V1 frames every 2 min from 40 min before T0 to 30 min after it."""
    source = db.connect(tmp_path / "source.sqlite")
    store = FrameStore(source, tmp_path)
    ids = {}
    for minute in range(-40, 31, 2):
        when = T0 + minute * M
        ids[minute] = store.add("kilauea-v1", scene_jpeg(minute + 1000), captured_at=when,
                                timestamp_source="ashcam", fetched_at=when)
    return source, ids


def alert_watcher(conn, tmp_path, fakes):
    client = make_client(FakeApi(lambda request: httpx.Response(500)), conn, budget=5.0)
    return AlertWatcher(context(conn, tmp_path, client=client, now=T0), "kilauea", V1_ONLY, tmp_path / "alerts",
                        budget_usd=0.75, segment=fakes.segment, compare=fakes.compare)


def test_the_alerts_replay_on_a_one_minute_clock_and_never_see_past_it(conn, tmp_path):
    source, ids = alert_source(tmp_path)
    fakes = Fakes()
    fakes.sam = {frame_id: (LARGE if minute >= 6 else SMALL) for minute, frame_id in ids.items()}

    replay_alerts(source, alert_watcher(conn, tmp_path, fakes), T0, T0 + 20 * M)

    clocks = [row[0] for row in conn.execute("SELECT clock FROM alert_ticks ORDER BY clock")]
    assert clocks == [to_iso(T0 + minute * M) for minute in range(1, 21)]
    first_fed = conn.execute("SELECT MIN(captured_at) FROM frames").fetchone()[0]
    assert first_fed == to_iso(T0 - 30 * M)  # the warm-up, for Muse Spark's comparison
    assert conn.execute("SELECT COUNT(*) FROM alert_checks WHERE captured_at > clock").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM alerts WHERE captured_at > clock").fetchone()[0] == 0
    assert [row[0] for row in conn.execute("SELECT kind FROM alerts")] == ["onset"]


def test_an_interrupted_alerts_replay_resumes_after_its_last_tick(conn, tmp_path):
    source, _ = alert_source(tmp_path)
    with conn:
        conn.execute("INSERT INTO alert_ticks (clock, report) VALUES (?, '{}')", (to_iso(T0 + M),))

    ran = replay_alerts(source, alert_watcher(conn, tmp_path, Fakes()), T0, T0 + 3 * M)

    assert ran == 2

    assert conn.execute("SELECT COUNT(*) FROM alert_ticks").fetchone()[0] == 3


def test_alert_rows_set_the_alerts_against_hvos_times_and_notices(conn):
    store_alert(conn, make_alert("onset", clock="2026-10-17T13:10:00Z", captured_at="2026-10-17T13:09:02Z",
                                 seen_at="2026-10-17T13:07:02Z", seen_by="V1cam"))
    store_alert(conn, make_alert("end", clock="2026-10-17T19:09:00Z", captured_at="2026-10-17T19:08:02Z",
                                 seen_at="2026-10-17T19:02:01Z", seen_by="K2cam"))

    rows = alert_rows(conn, EP55)

    assert ALERT_HEADER == ["Event", "Seen (local)", "Camera", "Official (local)", "Seen vs official",
                            "Alert (local)", "Alert vs official", "HVO notice (local)", "Alert vs notice"]
    assert rows == [["fountaining started", "03:07", "V1cam", "03:19", "-12 min", "03:10", "-9 min", "03:43", "-33 min"],
                    ["fountaining stopped", "09:02", "K2cam", "09:03", "-1 min", "09:09", "+6 min", "09:11", "-2 min"]]


def test_alert_rows_without_alerts_say_none(conn):
    rows = alert_rows(conn, EP55)

    assert [row[:2] for row in rows] == [["fountaining started", "none"], ["fountaining stopped", "none"]]


def test_cli_knows_the_quiet_windows(capsys):
    with pytest.raises(SystemExit):
        main(["--quiet", "nowhere"])

    assert "overflows" in capsys.readouterr().err


def test_the_alerts_replay_over_a_database_that_already_holds_the_frames_adds_none(conn, tmp_path):
    source, _ = alert_source(tmp_path)
    feed(source, conn, V1_ONLY.cameras, T0 - 30 * M, T0 + 3 * M)  # as the pipeline replay left them, same ids
    before = conn.execute("SELECT id, sha256 FROM frames ORDER BY id").fetchall()

    replay_alerts(source, alert_watcher(conn, tmp_path, Fakes()), T0, T0 + 3 * M)

    assert [tuple(row) for row in conn.execute("SELECT id, sha256 FROM frames ORDER BY id")] == [tuple(r) for r in before]
    assert conn.execute("SELECT COUNT(*) FROM alert_ticks").fetchone()[0] == 3


def test_cli_refuses_a_quiet_window_with_no_stored_frames_and_leaves_no_replay_database(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--quiet", "overflows"])

    assert "has no frames of the overflows window" in capsys.readouterr().err
    assert not (cli_env / "replay").exists()


def test_a_quiet_window_report_counts_the_alerts_as_false_alarms(conn):
    window = QUIET_WINDOWS["overflows"]
    assert "**Alerts raised: 0** (expected none)." in quiet_report(conn, window)

    store_alert(conn, make_alert("onset", clock="2026-10-17T01:00:00Z", captured_at="2026-10-17T00:59:00Z"))

    report = quiet_report(conn, window)
    assert "**Alerts raised: 1** (expected none)." in report and "| onset | 2026-10-17T01:00:00Z |" in report


def test_the_alerts_never_see_past_the_clock_in_a_database_that_already_holds_every_frame(conn, tmp_path):
    source, ids = alert_source(tmp_path)
    feed(source, conn, V1_ONLY.cameras, T0 - 30 * M, T0 + 30 * M)  # as inside run_replay, after the pipeline loop
    fakes = Fakes()
    fakes.sam = {frame_id: (LARGE if minute >= 6 else SMALL) for minute, frame_id in ids.items()}

    replay_alerts(source, alert_watcher(conn, tmp_path, fakes), T0, T0 + 20 * M)

    assert conn.execute("SELECT COUNT(*) FROM alert_checks").fetchone()[0] > 0
    assert conn.execute("SELECT COUNT(*) FROM alert_checks WHERE captured_at > clock").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM alerts WHERE captured_at > clock").fetchone()[0] == 0
    assert [row[0] for row in conn.execute("SELECT kind FROM alerts")] == ["onset"]


def test_an_alerts_replay_cut_short_mid_run_resumes_without_repeating_an_alert(conn, tmp_path):
    source, ids = alert_source(tmp_path)
    fakes = Fakes()
    fakes.sam = {frame_id: LARGE for frame_id in ids.values()}
    replay_alerts(source, alert_watcher(conn, tmp_path, fakes), T0, T0 + 12 * M)
    alerts_before = conn.execute("SELECT id, clock FROM alerts").fetchall()
    with conn:  # the run died after the watcher's step at +8 but before it stored the tick
        conn.execute("DELETE FROM alert_ticks WHERE clock >= ?", (to_iso(T0 + 8 * M),))

    ran = replay_alerts(source, alert_watcher(conn, tmp_path, fakes), T0, T0 + 20 * M)

    assert ran == 13  # ticks 8 to 20
    assert [tuple(row) for row in conn.execute("SELECT id, clock FROM alerts")] == [tuple(r) for r in alerts_before]
    assert conn.execute("SELECT COUNT(*) FROM alert_ticks").fetchone()[0] == 20
    assert conn.execute("SELECT COUNT(*) FROM (SELECT frame_id FROM alert_checks GROUP BY frame_id "
                        "HAVING COUNT(*) > 1)").fetchone()[0] == 0


def test_run_replay_runs_the_alerts_and_puts_them_in_the_timeline(conn, tmp_path):
    source, ids = alert_source(tmp_path)
    fakes = Fakes()
    fakes.sam = {frame_id: (LARGE if minute >= 6 else SMALL) for minute, frame_id in ids.items()}

    timeline = run_replay(source, context(conn, tmp_path), episode(T0, T0 + 20 * M), tmp_path / "replay", step=10 * M,
                          pipeline=FakePipeline(conn), alerts=alert_watcher(conn, tmp_path, fakes), spark_video=False)

    assert [alert["kind"] for alert in timeline["alerts"]] == ["onset"]
    onset, end = timeline["comparison"]["alerts"]
    assert onset[0] == "fountaining started" and onset[1] != "none" and onset[2] == timeline["alerts"][0]["seen_by"]
    assert end[:2] == ["fountaining stopped", "none"]
    assert "SAM looks" in timeline["alert_looks"]
    assert "## Fountaining alerts" in (tmp_path / "replay" / "report.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("seconds, text", [(-680, "-11 min"), (-12, "+0 min"), (12, "+0 min"), (360, "+6 min")])
def test_alert_times_are_whole_minutes_and_never_minus_zero(seconds, text):
    assert replay._minutes(to_iso(T0 + timedelta(seconds=seconds)), T0) == text


def test_cli_refuses_an_episode_and_a_quiet_window_together(capsys):
    with pytest.raises(SystemExit):
        main(["--episode", "55", "--quiet", "overflows"])

    assert "not allowed with" in capsys.readouterr().err


def test_cli_replays_a_quiet_window_and_writes_its_report(cli_env, monkeypatch, capsys):
    monkeypatch.setattr("vigil.settings.load_dotenv", lambda: None)
    sdk = openai.OpenAI(base_url="https://api.meta.ai/v1", api_key="test-key", max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))))
    monkeypatch.setattr(MetaClient, "from_env", staticmethod(lambda ledger: MetaClient(sdk, ledger)))
    window = QUIET_WINDOWS["overflows"]
    with closing(db.connect(cli_env / "vigil.sqlite")) as stored:
        for minutes in (5, 15):
            when = window.start + minutes * M
            FrameStore(stored, cli_env).add("kilauea-v1", scene_jpeg(minutes, lava=False), captured_at=when,
                                            timestamp_source="ashcam", fetched_at=when)

    main(["--quiet", "overflows"])

    report = (cli_env / "replay" / "overflows" / "report.md").read_text(encoding="utf-8")
    assert "**Alerts raised: 0** (expected none)." in report
    assert report in capsys.readouterr().out
