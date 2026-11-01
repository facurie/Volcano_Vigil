import dataclasses
import subprocess
from datetime import datetime, timedelta, timezone

import httpx
import openai
import pytest

from test_agent_loop import SOURCES_YAML
from test_agent_tools import SIZE, SOURCES, T0, add_frame, add_run, context, store  # store is a fixture
from test_metrics import kp_calibration
from vigil import tracking
from vigil.agent.bulletin import Written
from vigil.agent.loop import AgentRun
from vigil.calibration import CameraCalibration, Preset, Site
from vigil.meta.ledger import BudgetExceeded
from vigil.metrics import MeasureReport
from vigil.pipeline import Pipeline, PipelineConfig, floor_time, main
from vigil.timeutil import to_iso
from vigil.tracking import RunSummary, TrackingReport

START = T0 - timedelta(hours=2)  # 13:00Z: the pipeline starts here
H = timedelta(hours=1)
M = timedelta(minutes=1)


class Fakes:
    """Tracking, measuring and the agent, recording their calls and storing the rows the pipeline looks for."""

    def __init__(self):
        self.tracked, self.measured, self.agent_clocks, self.events = [], [], [], []
        self.targets = []         # the targets each tracking call was given
        self.lead_ins = []        # the lead-in each tracking call was given
        self.agent_status = "done"
        self.budget_spent = False
        self.raises = {}          # camera id -> exception its tracking raises
        self.stores_runs = True   # False: tracking returns without storing a run
        self.measure_error = None

    def track(self, client, conn, data_dir, camera, prompts, start, end, targets=tracking.TARGETS, lead_in=0):
        if self.budget_spent:
            raise BudgetExceeded("daily budget $5.00 would be exceeded")
        self.tracked.append((camera.id, start, end))
        self.targets.append(tuple(targets))
        self.lead_ins.append(lead_in)
        self.events.append(f"track {camera.id}")
        if camera.id in self.raises:
            raise self.raises[camera.id]
        frame_ids = [frame.id for frame in tracking.usable_frames(conn, data_dir, camera.id, start, end)]
        if not self.stores_runs:
            return TrackingReport(camera.id, len(frame_ids))
        return TrackingReport(camera.id, len(frame_ids), runs=[
            RunSummary(add_run(conn, camera.id, target, frame_ids), target, target, 1, len(frame_ids), start, end)
            for target in targets])

    def measure(self, conn, calibration, camera_id, start, end):
        self.measured.append((camera_id, start, end))
        if self.measure_error:
            raise self.measure_error
        return MeasureReport(camera_id, measured=2)

    def write(self, client, ctx, volcano_id, out_dir, **agent):
        self.agent_clocks.append(ctx.now)
        self.events.append("write")
        with ctx.conn:
            run_id = ctx.conn.execute(
                "INSERT INTO agent_runs (started_at, clock, volcano, task, model, status) "
                "VALUES ('2026-10-28T00:00:00Z', ?, ?, 'task', 'muse-spark-1.3', ?)",
                (to_iso(ctx.now), volcano_id, self.agent_status)).lastrowid
        return Written(AgentRun(run_id, self.agent_status, 1, 0.0, "{}", None), None, "no bulletin in this test")


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
    assert fakes.targets == [("plume", "fountain")] * 2  # the targets the prompts have phrases for


def test_a_window_is_led_in_with_the_frames_it_lacks_to_the_billed_minimum(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0, count=6)

    pipeline(conn, tmp_path, fakes).step(START + H + 5 * M)

    assert fakes.lead_ins == [44]  # 50 billed frames minus the window's 6


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


def test_a_camera_whose_preset_cannot_fix_a_view_is_not_measured(conn, store, tmp_path, fakes):
    # K2cam's episode 55 preset has an image size but no references (docs/research/calibration_ep55.md)
    calibration = kp_calibration()
    k2 = CameraCalibration(volcano="kilauea", position=Site(lat=19.42, lon=-155.2889, elev_m=1245),
                           presets=[Preset(name="ep55", valid_from="2026-10-17T00:00:00Z", image_size=SIZE)])
    base = dataclasses.replace(context(conn, tmp_path, client="a Meta client", now=START), calibration=(
        calibration.model_copy(update={"cameras": {**calibration.cameras, "kilauea-k2": k2}})))
    runner = Pipeline(base, PipelineConfig(volcano="kilauea", cameras=("kilauea-kp", "kilauea-k2"),
                                           bulletin_dir=tmp_path / "bulletins"),
                      track=fakes.track, measure=fakes.measure, write=fakes.write)
    frames(conn, store, "kilauea-kp", 0)
    frames(conn, store, "kilauea-k2", 0)

    report = runner.step(START + H + 5 * M)

    assert [camera for camera, _, _ in fakes.measured] == ["kilauea-kp"]
    assert not any("cannot fix a view" in error for error in report.errors)


def test_the_agent_writes_at_each_full_hour_after_the_start(conn, tmp_path, fakes):
    runner = pipeline(conn, tmp_path, fakes, settle=timedelta(0))

    reports = [runner.step(START + minutes * M) for minutes in (30, 60, 65, 120)]

    assert fakes.agent_clocks == [START + H, START + 2 * H]
    assert reports[1].agent_run_id == 1 and reports[1].bulletin_id is None
    assert reports[1].errors == ["agent run 1: no bulletin in this test"]


def test_the_agent_waits_for_the_hour_just_ended_to_be_tracked(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0)
    runner = pipeline(conn, tmp_path, fakes)

    runner.step(START + H)
    assert fakes.events == []
    runner.step(START + H + 5 * M)

    assert fakes.events == ["track kilauea-kp", "write"]
    assert fakes.agent_clocks == [START + H + 5 * M]


def test_the_agent_of_another_volcano_does_not_hold_this_ones_back(conn, tmp_path, fakes):
    with conn:
        conn.execute("INSERT INTO agent_runs (started_at, clock, volcano, task, model, status) "
                     "VALUES ('2026-10-28T00:00:00Z', ?, 'etna', 'task', 'muse-spark-1.3', 'done')",
                     (to_iso(START + H),))

    pipeline(conn, tmp_path, fakes, settle=timedelta(0)).step(START + H)
    pipeline(conn, tmp_path, fakes, settle=timedelta(0)).step(START + H, agent=True)

    assert fakes.agent_clocks == [START + H]  # the second step finds this volcano's own run at that clock


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
                                       "13:00-13:59 (12 detections); 2 detections measured")


@pytest.mark.parametrize("error", [ValueError("bad frames"), RuntimeError("video has 3 frames"),
                                   subprocess.CalledProcessError(1, "ffmpeg"), OSError("frame file is missing"),
                                   openai.APIError("upload failed", request=httpx.Request("POST", "http://x"),
                                                   body=None)])
def test_a_window_that_fails_does_not_stop_the_step(conn, store, tmp_path, fakes, error):
    frames(conn, store, "kilauea-kp", 0)
    frames(conn, store, "kilauea-k2", 0)
    fakes.raises["kilauea-kp"] = error

    report = pipeline(conn, tmp_path, fakes).step(START + H + 5 * M)

    end = START + H - timedelta(seconds=1)
    assert fakes.tracked == [("kilauea-kp", START, end), ("kilauea-k2", START, end)]
    assert [w["camera_id"] for w in report.tracked] == ["kilauea-k2"]
    assert any(message.startswith("kilauea-kp 2026-10-17T13:00:00Z: ") for message in report.errors)
    assert fakes.agent_clocks == [START + H + 5 * M]


def test_a_window_with_no_run_is_tried_three_times_and_then_given_up(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0)
    fakes.stores_runs = False
    runner = pipeline(conn, tmp_path, fakes)

    reports = [runner.step(START + H + minutes * M) for minutes in (5, 10, 15, 20)]

    assert len(fakes.tracked) == 3
    gave_up = "kilauea-kp 2026-10-17T13:00:00Z: gave up after 3 attempts"
    assert [gave_up in report.errors for report in reports] == [False, False, True, False]


def test_a_window_that_keeps_failing_is_given_up_too(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0)
    fakes.raises["kilauea-kp"] = RuntimeError("video has 3 frames")
    runner = pipeline(conn, tmp_path, fakes)

    reports = [runner.step(START + H + minutes * M) for minutes in (5, 10, 15, 20)]

    assert len(fakes.tracked) == 3
    assert reports[2].errors[-1] == "kilauea-kp 2026-10-17T13:00:00Z: gave up after 3 attempts"
    assert reports[3].errors == []


def test_a_failed_measuring_is_reported_and_the_step_goes_on(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0)
    fakes.measure_error = ValueError("no preset covers the view")

    report = pipeline(conn, tmp_path, fakes).step(START + H + 5 * M)

    assert "kilauea-kp 2026-10-17T13:00:00Z: no preset covers the view" in report.errors
    assert len(report.tracked) == 1 and fakes.agent_clocks == [START + H + 5 * M]


def test_a_tracking_with_no_runs_is_not_measured(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0)
    fakes.stores_runs = False

    report = pipeline(conn, tmp_path, fakes).step(START + H + 5 * M)

    assert len(report.tracked) == 1 and fakes.measured == []


def test_the_open_window_of_a_flush_ends_with_its_hour(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0)

    pipeline(conn, tmp_path, fakes).step(START + H + 3 * M, flush=True)

    assert fakes.tracked == [("kilauea-kp", START, START + H - timedelta(seconds=1))]


def test_a_window_with_exactly_the_minimum_of_frames_is_tracked(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0, count=5)

    pipeline(conn, tmp_path, fakes).step(START + H + 5 * M)

    assert len(fakes.tracked) == 1


def test_frames_older_than_the_lookback_are_not_assessed(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 1, count=1, usable=None)  # 14:00Z
    frames(conn, store, "kilauea-kp", 3, count=1, usable=None)  # 16:00Z

    report = pipeline(conn, tmp_path, fakes, client=None).step(START + 5 * H)  # looks back to 15:00Z

    assert report.assessed == 1
    assert conn.execute("SELECT COUNT(*) FROM frame_quality").fetchone()[0] == 1


def test_frames_after_the_clock_are_not_assessed(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 1, count=2, every=30, usable=None)  # 14:00Z and 14:30Z

    report = pipeline(conn, tmp_path, fakes, client=None).step(START + H + 15 * M)

    assert report.assessed == 1
    assert conn.execute("SELECT COUNT(*) FROM frame_quality").fetchone()[0] == 1


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(SOURCES_YAML, encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigil.sqlite"))


@pytest.mark.parametrize("argv, message", [(["--volcano", "etna"], "etna"),
                                           (["--volcano", "kilauea"], "no enabled camera"),
                                           (["--volcano", "kilauea", "--interval", "0"],
                                            "--interval must be positive"),
                                           (["--volcano", "kilauea", "--agent-every", "-5"],
                                            "--agent-every must not be negative")])
def test_cli_refuses_what_it_cannot_run(cli_env, capsys, argv, message):
    with pytest.raises(SystemExit):
        main(argv)

    assert message in capsys.readouterr().err


def test_a_window_with_only_the_plume_run_is_tracked_again_for_the_missing_targets(conn, store, tmp_path, fakes):
    ids = frames(conn, store, "kilauea-kp", 0)
    add_run(conn, "kilauea-kp", "plume", ids)
    frames(conn, store, "kilauea-k2", 0)
    runner = pipeline(conn, tmp_path, fakes)

    runner.step(START + H + 5 * M)
    runner.step(START + H + 10 * M)

    assert [(camera, targets) for (camera, _, _), targets in zip(fakes.tracked, fakes.targets)] == [
        ("kilauea-kp", ("fountain",)), ("kilauea-k2", ("plume", "fountain"))]  # incandescence has no phrases


def test_a_target_that_keeps_missing_is_given_up_too(conn, store, tmp_path, fakes):
    ids = frames(conn, store, "kilauea-kp", 0)
    add_run(conn, "kilauea-kp", "plume", ids)
    fakes.stores_runs = False
    runner = pipeline(conn, tmp_path, fakes, cameras=("kilauea-kp",))

    reports = [runner.step(START + H + minutes * M) for minutes in (5, 10, 15, 20)]

    assert len(fakes.tracked) == 3 and fakes.targets == [("fountain",)] * 3
    assert reports[2].errors[0] == "kilauea-kp 2026-10-17T13:00:00Z: gave up after 3 attempts"


def agent_run(conn, clock, status, volcano="kilauea"):
    with conn:
        conn.execute("INSERT INTO agent_runs (started_at, clock, volcano, task, model, status) "
                     "VALUES ('2026-10-28T00:00:00Z', ?, ?, 'task', 'muse-spark-1.3', ?)",
                     (to_iso(clock), volcano, status))


def test_a_run_that_ended_in_error_does_not_count_as_the_hours_bulletin(conn, tmp_path, fakes):
    agent_run(conn, START + H + 2 * M, "error")

    pipeline(conn, tmp_path, fakes, settle=timedelta(0)).step(START + H + 5 * M)

    assert fakes.agent_clocks == [START + H + 5 * M]


def test_two_failed_runs_in_an_hour_stop_the_agent_and_say_so_once(conn, tmp_path, fakes):
    agent_run(conn, START + H + 1 * M, "error")
    agent_run(conn, START + H + 2 * M, "error")
    runner = pipeline(conn, tmp_path, fakes, settle=timedelta(0))

    reports = [runner.step(START + H + minutes * M) for minutes in (5, 10)]

    assert fakes.agent_clocks == []
    assert reports[0].errors == ["agent at 2026-10-17T14:00:00Z: gave up after 2 failed runs"]
    assert reports[1].errors == []


def test_a_finished_run_in_the_hour_stops_the_agent_even_after_a_failed_one(conn, tmp_path, fakes):
    agent_run(conn, START + H + 1 * M, "error")
    agent_run(conn, START + H + 2 * M, "done")

    pipeline(conn, tmp_path, fakes, settle=timedelta(0)).step(START + H + 5 * M)

    assert fakes.agent_clocks == []


def test_a_forced_agent_retries_a_failed_run_at_its_clock_and_gives_up_after_two(conn, tmp_path, fakes):
    fakes.agent_status = "error"
    runner = pipeline(conn, tmp_path, fakes)

    reports = [runner.step(START + 30 * M, agent=True) for _ in range(4)]

    assert fakes.agent_clocks == [START + 30 * M] * 2
    assert "agent at 2026-10-17T13:30:00Z: gave up after 2 failed runs" in reports[2].errors
    assert reports[3].errors == []


def untracked_v1(conn, tmp_path, fakes, **config):
    """A pipeline over K2 and V1, where V1 is ingested for the alerts only (track: false)."""
    sources = SOURCES.model_copy(update={"cameras": [
        camera.model_copy(update={"track": False}) if camera.id == "kilauea-v1" else camera
        for camera in SOURCES.cameras]})
    base = dataclasses.replace(context(conn, tmp_path, client="a Meta client", now=START), sources=sources)
    config = {"volcano": "kilauea", "cameras": ("kilauea-k2", "kilauea-v1"), "bulletin_dir": tmp_path / "bulletins",
              "agent_every": None, **config}
    return Pipeline(base, PipelineConfig(**config), track=fakes.track, measure=fakes.measure, write=fakes.write)


def test_a_camera_that_is_not_tracked_gets_local_verdicts_and_no_sam_window(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-k2", 0)
    v1 = frames(conn, store, "kilauea-v1", 0, usable=None)

    # spark="all" would ask Muse Spark about every frame the local checks pass; the client here is a string, so
    # any call for V1 would fail
    report = untracked_v1(conn, tmp_path, fakes, spark="all").step(START + 2 * H)

    assert report.assessed == len(v1)
    rows = conn.execute(f"SELECT decided_by FROM frame_quality WHERE frame_id IN ({','.join('?' * len(v1))})",
                        v1).fetchall()
    assert [row["decided_by"] for row in rows] == ["local"] * len(v1)
    assert [camera for camera, _, _ in fakes.tracked] == ["kilauea-k2"]
