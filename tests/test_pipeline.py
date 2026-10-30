from datetime import datetime, timedelta, timezone

import pytest

from test_agent_loop import SOURCES_YAML
from test_agent_tools import T0, add_frame, add_run, context, store  # store is a fixture
from vigia import tracking
from vigia.agent.bulletin import Written
from vigia.agent.loop import AgentRun
from vigia.meta.ledger import BudgetExceeded
from vigia.metrics import MeasureReport
from vigia.pipeline import Pipeline, PipelineConfig, floor_time, main
from vigia.timeutil import to_iso
from vigia.tracking import RunSummary, TrackingReport

START = T0 - timedelta(hours=2)  # 13:00Z: the pipeline starts here
H = timedelta(hours=1)
M = timedelta(minutes=1)


class Fakes:
    """Tracking, measuring and the agent, recording their calls and storing the rows the pipeline looks for."""

    def __init__(self):
        self.tracked, self.measured, self.agent_clocks = [], [], []
        self.budget_spent = False

    def track(self, client, conn, data_dir, camera, prompts, start, end):
        if self.budget_spent:
            raise BudgetExceeded("daily budget $5.00 would be exceeded")
        self.tracked.append((camera.id, start, end))
        frame_ids = [frame.id for frame in tracking.usable_frames(conn, data_dir, camera.id, start, end)]
        run_id = add_run(conn, camera.id, "plume", frame_ids)
        return TrackingReport(camera.id, len(frame_ids),
                              runs=[RunSummary(run_id, "plume", "steam", 1, len(frame_ids), start, end)])

    def measure(self, conn, calibration, camera_id, start, end):
        self.measured.append((camera_id, start, end))
        return MeasureReport(camera_id, measured=2)

    def write(self, client, ctx, volcano_id, out_dir, **agent):
        self.agent_clocks.append(ctx.now)
        with ctx.conn:
            run_id = ctx.conn.execute(
                "INSERT INTO agent_runs (started_at, clock, volcano, task, model, status) "
                "VALUES ('2026-10-28T00:00:00Z', ?, ?, 'task', 'muse-spark-1.3', 'done')",
                (to_iso(ctx.now), volcano_id)).lastrowid
        return Written(AgentRun(run_id, "done", 1, 0.0, "{}", None), None, "no bulletin in this test")


@pytest.fixture
def fakes():
    return Fakes()


def pipeline(conn, tmp_path, fakes, *, client="a Meta client", **config):
    base = context(conn, tmp_path, client=client, now=START)
    config = {"volcano": "kilauea", "cameras": ("kilauea-kp", "kilauea-k2"), "bulletin_dir": tmp_path / "bulletins",
              **config}
    return Pipeline(base, PipelineConfig(**config), track=fakes.track, measure=fakes.measure, write=fakes.write)


def frames(conn, store, camera_id, hour, count=6, every=10, usable=True):
    """`count` frames of the camera, `every` minutes apart from `hour` hours after the pipeline's start."""
    first = int((START - T0) / M) + 60 * hour
    return [add_frame(conn, store, camera_id, first + every * i, usable=usable) for i in range(count)]


def test_a_step_gives_every_recent_frame_without_a_verdict_one(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 1, count=2, usable=None)

    report = pipeline(conn, tmp_path, fakes, client=None).step(START + 2 * H)

    assert report.assessed == 2
    assert conn.execute("SELECT COUNT(*) FROM frame_quality").fetchone()[0] == 2
    assert fakes.tracked == [] and fakes.agent_clocks == []  # without a client nothing calls SAM or Muse Spark


def test_each_closed_hour_is_tracked_once_per_camera(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0)
    frames(conn, store, "kilauea-k2", 0)
    runner = pipeline(conn, tmp_path, fakes)

    report = runner.step(START + H + 5 * M)
    runner.step(START + H + 10 * M)

    end = START + H - timedelta(seconds=1)
    assert fakes.tracked == [("kilauea-kp", START, end), ("kilauea-k2", START, end)]
    assert [(w["camera_id"], w["start"], w["end"]) for w in report.tracked] == [
        ("kilauea-kp", to_iso(START), to_iso(end)), ("kilauea-k2", to_iso(START), to_iso(end))]
    assert report.tracked[0]["runs"][0]["detections"] == 6


def test_a_window_waits_until_it_has_settled(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0)
    runner = pipeline(conn, tmp_path, fakes)

    runner.step(START + H + 4 * M)
    assert fakes.tracked == []
    runner.step(START + H + 5 * M)
    assert len(fakes.tracked) == 1


def test_flushing_tracks_the_open_window_up_to_the_clock_and_never_past_it(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0, count=6, every=10)  # 13:00 to 13:50

    pipeline(conn, tmp_path, fakes, settle=timedelta(0), min_frames=3).step(START + 30 * M, flush=True)

    assert fakes.tracked == [("kilauea-kp", START, START + 30 * M)]


def test_a_window_with_too_few_usable_frames_is_not_tracked(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0, count=4)
    frames(conn, store, "kilauea-k2", 0, count=6, usable=False)

    pipeline(conn, tmp_path, fakes).step(START + 2 * H)

    assert fakes.tracked == []


def test_only_calibrated_cameras_are_measured(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0)
    frames(conn, store, "kilauea-k2", 0)

    report = pipeline(conn, tmp_path, fakes).step(START + H + 5 * M)

    assert fakes.measured == [("kilauea-kp", START, START + H - timedelta(seconds=1))]  # only KPcam is calibrated
    assert report.measured == 2


def test_the_agent_writes_at_each_full_hour_after_the_start(conn, tmp_path, fakes):
    runner = pipeline(conn, tmp_path, fakes)

    reports = [runner.step(START + minutes * M) for minutes in (30, 60, 65, 120)]

    assert fakes.agent_clocks == [START + H, START + 2 * H]
    assert reports[1].agent_run_id == 1 and reports[1].bulletin_id is None
    assert reports[1].errors == ["agent run 1: no bulletin in this test"]


def test_a_forced_agent_runs_once_per_clock_and_can_be_held_back(conn, tmp_path, fakes):
    runner = pipeline(conn, tmp_path, fakes)

    runner.step(START + 30 * M, agent=True)
    runner.step(START + 30 * M, agent=True)
    runner.step(START + H, agent=False)

    assert fakes.agent_clocks == [START + 30 * M]


def test_without_an_agent_schedule_no_agent_runs(conn, tmp_path, fakes):
    pipeline(conn, tmp_path, fakes, agent_every=None).step(START + 2 * H)

    assert fakes.agent_clocks == []


def test_a_spent_budget_stops_tracking_and_is_reported(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0)
    fakes.budget_spent = True

    report = pipeline(conn, tmp_path, fakes).step(START + H + 5 * M)

    assert fakes.tracked == [] and any("daily budget" in error for error in report.errors)


def test_floor_time_counts_from_the_unix_epoch():
    assert floor_time(datetime(2026, 10, 17, 14, 37, tzinfo=timezone.utc), H) == datetime(
        2026, 10, 17, 14, tzinfo=timezone.utc)


def test_a_report_reads_as_one_line_per_step(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0)

    report = pipeline(conn, tmp_path, fakes).step(START + H + 5 * M)

    assert report.as_json()["clock"] == to_iso(START + H + 5 * M)
    assert report.summary().startswith("2026-10-17T14:05:00Z: 0 frames assessed (0 usable); tracked kilauea-kp "
                                       "13:00-13:59 (6 detections); 2 detections measured")


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(SOURCES_YAML, encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigia.sqlite"))


@pytest.mark.parametrize("argv, message", [(["--volcano", "etna"], "etna"),
                                           (["--volcano", "kilauea"], "no enabled camera"),
                                           (["--volcano", "kilauea", "--interval", "0"], "--interval")])
def test_cli_refuses_what_it_cannot_run(cli_env, capsys, argv, message):
    with pytest.raises(SystemExit):
        main(argv)

    assert message in capsys.readouterr().err
