import pytest

from test_agent_tools import add_frame, add_measurement, add_run, add_track, detection_ids, store  # store: fixture
from vigil.episodes import EP55, EPISODES, drift_rows, end_rows, height_row, local_time, table
from vigil.timeutil import parse_utc


def measured(conn, store, camera_id, minutes, target, metric, value, sigma, unit="m"):
    """A frame `minutes` from 15:00Z with one tracked detection and one measurement of it; returns the frame id."""
    frame_id = add_frame(conn, store, camera_id, minutes)
    track_id = add_track(conn, add_run(conn, camera_id, target, [frame_id]), [frame_id])
    add_measurement(conn, frame_id, metric, value, sigma, detection_id=detection_ids(conn, track_id)[0],
                    target=target, unit=unit)
    return frame_id


def test_episode_55_states_hvos_values_in_metres_and_utc():
    assert EPISODES["55"] is EP55
    assert (EP55.volcano, EP55.cameras, EP55.timelapse_camera) == (
        "kilauea", ("kilauea-kp", "kilauea-k2", "kilauea-v1"), "kilauea-k2")
    peak = EP55.checks[4]
    assert (peak.quantity, peak.camera_id, peak.metric, peak.aggregate) == (
        "plume top (peak)", "kilauea-kp", "top_altitude", "max")
    assert peak.official_m == pytest.approx(7620)
    assert EP55.phases["onset"] == (parse_utc("2026-10-17T13:19:00Z"),) * 2
    assert EP55.phases["peak"] == (parse_utc("2026-10-17T14:50:00Z"), parse_utc("2026-10-17T15:10:00Z"))
    assert EP55.phases["end"] == (parse_utc("2026-10-17T19:03:00Z"),) * 2
    assert local_time("2026-10-17T14:55:05Z", EP55.local, seconds=True) == "04:55:05"


def test_a_max_row_takes_the_highest_frame_in_hvos_window(conn, store):
    measured(conn, store, "kilauea-kp", -10, "plume", "top_altitude", 6500, 300)
    measured(conn, store, "kilauea-kp", -5, "plume", "top_altitude", 6951, 429)
    measured(conn, store, "kilauea-kp", 15, "plume", "top_altitude", 9000, 400)  # 05:15: outside the window

    row = height_row(conn, EP55.checks[4], EP55.local)

    assert row == ["plume top (peak)", "04:50-05:10", "kilauea-kp", "25,000 ft a.s.l., 04:50-05:10 (7,620 m)",
                   "6,951 ± 429 m (22,805 ft); max of 2 frames, at 04:55", "-669 m (-9 %)", "-1.6", "yes"]


def test_an_upper_bound_row_agrees_under_the_bound(conn, store):
    measured(conn, store, "kilauea-kp", 150, "plume", "top_altitude", 3800, 100)  # 07:30 HST

    row = height_row(conn, EP55.checks[6], EP55.local)

    assert row[4].startswith("3,800 ± 100 m") and row[5:] == ["within the bound", "-", "yes"]


def test_a_window_without_measurements_has_none(conn):
    assert height_row(conn, EP55.checks[0], EP55.local)[4:] == ["no measurement", "", "", ""]


def test_end_rows_set_the_last_fountain_detection_against_hvos_end(conn, store):
    frames = [add_frame(conn, store, "kilauea-k2", minutes) for minutes in (200, 242)]  # 18:20 and 19:02
    add_track(conn, add_run(conn, "kilauea-k2", "fountain", frames), frames)

    assert end_rows(conn, EP55) == [["kilauea-k2", "09:02:00", "09:03", "-1.0 min"]]


def test_drift_rows_count_the_frames_on_each_side(conn, store):
    for minutes, side in ((-10, 224.4), (-5, 224.4), (0, 230.2)):
        measured(conn, store, "kilauea-kp", minutes, "plume", "drift_bearing", side, 2.1, unit="deg")

    assert drift_rows(conn, EP55) == [["kilauea-kp", "3", "224°: 2, 230°: 1", "224° (-1° from SW)", "yes"]]


def test_table_writes_a_markdown_table():
    assert table(["A", "B"], [["1", "2"]]) == "| A | B |\n|---|---|\n| 1 | 2 |"
