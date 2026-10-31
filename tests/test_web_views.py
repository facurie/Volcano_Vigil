import json
from datetime import timedelta

import pytest

from test_agent_tools import SOURCES, T0, add_frame, add_measurement, add_run, add_track, detection_ids
from test_metrics import kp_calibration
from vigil.ingest.store import FrameStore
from vigil.timeutil import to_iso
from vigil.web import views
from vigil.web.views import Scene

M = timedelta(minutes=1)


@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def scene(conn, tmp_path, clock=T0, episode=None, cameras=("kilauea-kp", "kilauea-k2")):
    return Scene(conn=conn, clock=clock, data_dir=tmp_path, sources=SOURCES, calibration=kp_calibration(),
                 volcano="kilauea", cameras=cameras, episode=episode)


def test_a_scene_needs_a_clock_with_a_time_zone(conn, tmp_path):
    with pytest.raises(ValueError, match="time zone"):
        scene(conn, tmp_path, clock=T0.replace(tzinfo=None))


def test_camera_status_reads_each_cameras_latest_frame_by_the_clock(conn, store, tmp_path):
    add_frame(conn, store, "kilauea-kp", -10)
    add_frame(conn, store, "kilauea-kp", 5, usable=False, reasons=["low_visibility"])  # after the clock
    add_frame(conn, store, "kilauea-k2", -3, usable=False, reasons=["night"])

    kp, k2 = views.camera_status(scene(conn, tmp_path))

    assert (kp["camera_id"], kp["condition"], kp["latest"]["minutes_ago"]) == ("kilauea-kp", "usable", 10.0)
    assert (kp["frames_last_hour"], kp["usable_last_hour"]) == (1, 1)
    assert kp["calibrated"] is True
    assert kp["position"]["lat"] == kp_calibration().cameras["kilauea-kp"].position.lat
    assert (k2["condition"], k2["reasons"], k2["calibrated"], k2["position"]) == ("night", ["night"], False, None)


@pytest.mark.parametrize("minutes, usable, reasons, expected", [
    (-5, 1, [], "usable"), (-5, None, [], "unchecked"), (-31, 1, [], "stale"), (-5, 0, ["night"], "night"),
    (-5, 0, ["low_visibility"], "fog"), (-5, 0, ["frozen"], "frozen"),
    (-5, 0, ["timestamp_mismatch"], "clock_mismatch"), (-5, 0, ["low_visibility", "night"], "night"),
    (-5, 0, [], "rejected")])
def test_a_cameras_condition_comes_from_its_latest_frame(minutes, usable, reasons, expected):
    assert views.condition(to_iso(T0 + minutes * M), usable, reasons, T0) == expected


def test_a_camera_without_frames_has_no_frames():
    assert views.condition(None, None, [], T0) == "no_frames"


def test_a_detection_appears_once_every_frame_its_sam_run_saw_was_captured(conn, store, tmp_path):
    a, b, c = (add_frame(conn, store, "kilauea-kp", minutes) for minutes in (-20, -10, 5))
    add_track(conn, add_run(conn, "kilauea-kp", "plume", [a, b]), [a, b])
    add_track(conn, add_run(conn, "kilauea-kp", "fountain", [b, c]), [b, c])  # its window ends after the clock

    now = views.latest_frames(scene(conn, tmp_path), "kilauea-kp")
    later = scene(conn, tmp_path, clock=T0 + 5 * M)

    assert now["latest"]["frame_id"] == b and now["tracked"]["frame_id"] == b
    assert [d["target"] for d in now["latest"]["detections"]] == ["plume"]
    assert views.latest_frames(later, "kilauea-kp")["latest"]["frame_id"] == c
    assert sorted(d["target"] for d in views.frame(later, b)["detections"]) == ["fountain", "plume"]


def test_a_visible_detection_carries_its_box_and_measurements(conn, store, tmp_path):
    a = add_frame(conn, store, "kilauea-kp", -10)
    track = add_track(conn, add_run(conn, "kilauea-kp", "plume", [a]), [a])
    add_measurement(conn, a, "top_altitude", 6951.5, 429.4, detection_id=detection_ids(conn, track)[0])

    (detection,) = views.latest_frames(scene(conn, tmp_path), "kilauea-kp")["latest"]["detections"]

    assert detection["box"] == [60, 60, 120, 150] and detection["target"] == "plume"
    assert detection["measurements"] == {"top_altitude": {"value": 6951.5, "sigma": 429.4, "unit": "m"}}


def test_a_camera_without_visible_detections_has_no_tracked_frame(conn, store, tmp_path):
    add_frame(conn, store, "kilauea-kp", -10)

    shown = views.latest_frames(scene(conn, tmp_path), "kilauea-kp")

    assert shown["tracked"] is None and shown["latest"]["detections"] == []


def test_a_camera_the_scene_does_not_show_is_unknown(conn, tmp_path):
    with pytest.raises(LookupError):
        views.latest_frames(scene(conn, tmp_path), "kilauea-v2")


def test_a_frame_captured_after_the_clock_does_not_exist(conn, store, tmp_path):
    later = add_frame(conn, store, "kilauea-kp", 5)

    assert views.frame(scene(conn, tmp_path), later) is None
    assert views.frame(scene(conn, tmp_path, clock=T0 + 5 * M), later)["captured_at"] == to_iso(T0 + 5 * M)


def test_the_frame_strip_lists_each_frame_since_with_its_verdict_and_visible_targets(conn, store, tmp_path):
    old, a, b, c = (add_frame(conn, store, "kilauea-kp", m, usable=m != -10) for m in (-90, -20, -10, 5))
    add_track(conn, add_run(conn, "kilauea-kp", "plume", [a, b]), [a])
    add_track(conn, add_run(conn, "kilauea-kp", "fountain", [b, c]), [b])  # closes after the clock

    strip = views.frame_strip(scene(conn, tmp_path), "kilauea-kp", T0 - 60 * M)

    assert strip == [{"frame_id": a, "captured_at": to_iso(T0 - 20 * M), "usable": True, "targets": ["plume"]},
                     {"frame_id": b, "captured_at": to_iso(T0 - 10 * M), "usable": False, "targets": []}]
