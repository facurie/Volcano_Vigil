import io
import json
import sqlite3
from datetime import timedelta

import pytest
from PIL import Image

from test_alerts import make_alert
from test_agent_tools import SOURCES, T0, add_frame, add_measurement, add_run, add_track, detection_ids
from test_metrics import kp_calibration
from test_replay import bulletin_at, top
from vigil.agent import render
from vigil.alerts import store_alert
from vigil.agent.bulletin import DISCLAIMER, Evidence
from vigil.episodes import EP55, HEIGHT_HEADER
from vigil.ingest.store import FrameStore
from vigil.timeutil import parse_utc, to_iso
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


def test_a_cameras_last_detection_counts_only_runs_closed_by_the_clock(conn, store, tmp_path):
    a, b, c, d = (add_frame(conn, store, "kilauea-kp", minutes) for minutes in (-20, -10, -5, 5))
    add_track(conn, add_run(conn, "kilauea-kp", "plume", [a, b]), [a, b])
    add_track(conn, add_run(conn, "kilauea-kp", "fountain", [c, d]), [c])  # its window ends after the clock

    def last_detection(clock):
        return views.camera_status(scene(conn, tmp_path, clock=clock, cameras=("kilauea-kp",)))[0]["last_detection"]

    assert last_detection(T0) == {"plume": to_iso(T0 - 10 * M)}
    assert last_detection(T0 + 5 * M) == {"plume": to_iso(T0 - 10 * M), "fountain": to_iso(T0 - 5 * M)}


def test_the_tracked_frame_waits_for_its_sam_run_to_close(conn, store, tmp_path):
    a, b = add_frame(conn, store, "kilauea-kp", -10), add_frame(conn, store, "kilauea-kp", 5)
    add_track(conn, add_run(conn, "kilauea-kp", "plume", [a, b]), [a, b])  # the only run closes after the clock

    now = views.latest_frames(scene(conn, tmp_path), "kilauea-kp")
    later = views.latest_frames(scene(conn, tmp_path, clock=T0 + 5 * M), "kilauea-kp")

    assert now["tracked"] is None and now["latest"]["frame_id"] == a
    assert later["tracked"]["frame_id"] == b


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


def test_the_series_has_each_frames_highest_value_from_runs_closed_by_the_clock(conn, store, tmp_path):
    f1, f2, f3, f4 = (add_frame(conn, store, "kilauea-kp", m) for m in (-30, -20, -10, 5))
    run = add_run(conn, "kilauea-kp", "plume", [f1, f2, f3])
    first, second = add_track(conn, run, [f1, f2, f3]), add_track(conn, run, [f2], object_id="1")
    for frame_id, detection_id, value in zip((f1, f2, f3), detection_ids(conn, first), (5000, 5200, 5400)):
        add_measurement(conn, frame_id, "top_altitude", value, 300, detection_id=detection_id)
    add_measurement(conn, f2, "top_altitude", 6000, 400, detection_id=detection_ids(conn, second)[0])
    late = add_track(conn, add_run(conn, "kilauea-kp", "plume", [f3, f4]), [f3, f4])  # closes after the clock
    for frame_id, detection_id in zip((f3, f4), detection_ids(conn, late)):
        add_measurement(conn, frame_id, "top_altitude", 9000, 300, detection_id=detection_id)

    shown = views.series(scene(conn, tmp_path), "kilauea-kp", "plume", "top_altitude", T0 - 25 * M)

    assert shown["unit"] == "m" and shown["official"] == []
    assert [(p["frame_id"], p["value"], p["sigma"]) for p in shown["points"]] == [(f2, 6000, 400), (f3, 5400, 300)]


def test_an_official_height_shows_once_its_window_has_closed(conn, tmp_path):
    def official(clock):
        shown = views.series(scene(conn, tmp_path, clock=parse_utc(clock), episode=EP55), "kilauea-kp", "plume",
                             "top_altitude", EP55.start)
        return [check["official"] for check in shown["official"]]

    assert official("2026-10-17T15:10:58Z") == []
    assert official("2026-10-17T16:08:00Z") == ["25,000 ft a.s.l., 04:50-05:10", "17,000 ft a.s.l. at 06:02"]


def test_a_series_unit_follows_its_metric_even_when_empty(conn, tmp_path):
    for metric, unit in (("area", "m2"), ("drift_bearing", "deg"), ("top_height", "m")):
        assert views.series(scene(conn, tmp_path), "kilauea-kp", "plume", metric, T0 - 60 * M)["unit"] == unit


def test_bulletins_written_by_the_clock_come_newest_first_with_the_published_tables(conn, tmp_path):
    first = bulletin_at(conn, tmp_path, "2026-10-17T14:00:00Z",
                        measurements=[top(6964, 419, "2026-10-17T13:55:05Z")])
    second = bulletin_at(conn, tmp_path, "2026-10-17T15:00:00Z", level="degassing")
    bulletin_at(conn, tmp_path, "2026-10-17T16:00:00Z")  # after the clock

    shown = views.bulletins(scene(conn, tmp_path))

    assert [b["id"] for b in shown] == [second.id, first.id]
    old = shown[1]
    assert old["level"] == "Lava fountain"
    assert old["when"] == "2026-10-17 14:00 UTC"  # the test volcano has no UTC offset
    assert old["header"] == render.TABLE_HEADER
    assert old["rows"] == render.table_rows(first) and old["rows"][0][2] == "6,964 ± 419 m"
    assert (old["headline"], old["body"]) == (first.headline, first.body)
    assert old["disclaimer"] == first.disclaimer and old["official_url"] == first.official_url
    assert old["wind"] is None and old["wind_text"] is None and old["verified"] is True
    assert "en" not in old and "es" not in old
    assert len(views.bulletins(scene(conn, tmp_path), limit=1)) == 1


def test_a_bulletin_shows_the_disclaimer_the_code_gives_now(conn, tmp_path):
    stored = bulletin_at(conn, tmp_path, "2026-10-17T14:00:00Z")
    old = stored.model_copy(update={"disclaimer": "Automated reading by Vigía Andino."})
    with conn:
        conn.execute("UPDATE bulletins SET body = ? WHERE id = ?", (old.model_dump_json(), stored.id))

    (shown,) = views.bulletins(scene(conn, tmp_path))

    words = {"name": stored.volcano_name, "agency": stored.official_agency, "url": stored.official_url}
    assert shown["disclaimer"] == DISCLAIMER.format(**words)


def test_a_bulletins_evidence_keeps_its_overlay_path_and_captions(conn, tmp_path):
    stored = bulletin_at(conn, tmp_path, "2026-10-17T14:00:00Z")
    evidence = Evidence(frame_id=29, target="plume", caption="Plume",
                        camera_id="kilauea-kp", captured_at="2026-10-17T13:55:05Z",
                        overlay="bulletins/run1/frame29_plume.jpg")
    with conn:
        conn.execute("UPDATE bulletins SET body = ? WHERE id = ?",
                     (stored.model_copy(update={"evidence": [evidence]}).model_dump_json(), stored.id))

    (shown,) = views.bulletins(scene(conn, tmp_path))

    assert shown["evidence"] == [evidence.model_dump()]


def add_agent_run(conn, clock, steps=()):
    with conn:
        run_id = conn.execute(
            """INSERT INTO agent_runs (started_at, clock, volcano, task, model, status, turns, cost_usd)
               VALUES ('2026-10-30T00:00:00Z', ?, 'kilauea', 'Check Kilauea now', 'muse-spark-1.3', 'done', 2, 0.03)""",
            (clock,)).lastrowid
        for seq, step in enumerate(steps, 1):
            conn.execute(f"""INSERT INTO agent_steps (run_id, seq, created_at, {', '.join(step)})
                             VALUES (?, ?, '2026-10-30T00:00:00Z', {', '.join('?' * len(step))})""",
                         (run_id, seq, *step.values()))
    return run_id


def test_the_trace_shows_the_latest_run_by_the_clock_with_its_steps(conn, tmp_path):
    early = add_agent_run(conn, "2026-10-17T14:00:00Z")
    written = bulletin_at(conn, tmp_path, "2026-10-17T14:00:00Z")  # bulletin_at stores run 1: `early`
    run = add_agent_run(conn, "2026-10-17T15:00:00Z", steps=[
        {"turn": 1, "kind": "model", "text": "Checking the cameras.", "reasoning": "KPcam sees the column."},
        {"turn": 1, "kind": "tool", "tool_name": "list_cameras_status", "arguments": "{}",
         "result": '{"now": "2026-10-17T15:00:00Z"}', "ok": 1, "cost_usd": 0.0, "latency_ms": 12},
        {"turn": 2, "kind": "tool", "tool_name": "measure_track", "arguments": "{not json",
         "result": '{"error": "bad"}', "ok": 0}])
    add_agent_run(conn, "2026-10-17T16:00:00Z")  # after the clock

    shown = views.agent_trace(scene(conn, tmp_path))

    assert [r["run_id"] for r in shown["runs"]] == [run, early]
    assert shown["runs"][1]["bulletin_id"] == written.id and early == 1
    assert shown["run"]["run_id"] == run and shown["run"]["bulletin_id"] is None
    model, listed, failed = shown["steps"]
    assert (model["kind"], model["text"], model["reasoning"]) == ("model", "Checking the cameras.",
                                                                  "KPcam sees the column.")
    assert (listed["arguments"], listed["result"], listed["ok"]) == ({}, {"now": "2026-10-17T15:00:00Z"}, True)
    assert (failed["arguments"], failed["ok"]) == ("{not json", False)


def test_a_run_after_the_clock_cannot_be_traced(conn, tmp_path):
    later = add_agent_run(conn, "2026-10-17T16:00:00Z")

    with pytest.raises(LookupError):
        views.agent_trace(scene(conn, tmp_path), later)
    assert views.agent_trace(scene(conn, tmp_path)) == {"runs": [], "run": None, "steps": []}


def add_tick(conn, clock, **report):
    with conn:
        conn.execute("INSERT INTO replay_ticks (clock, report) VALUES (?, ?)",
                     (clock, json.dumps({"clock": clock, **report})))


def test_the_replay_state_holds_the_steps_and_official_phases_known_by_the_clock(conn, tmp_path):
    for clock in ("2026-10-17T14:55:00Z", "2026-10-17T15:00:00Z", "2026-10-17T15:05:00Z"):
        add_tick(conn, clock, assessed=3)

    shown = views.replay_state(scene(conn, tmp_path, episode=EP55), tmp_path / "replay" / "ep55")

    assert [tick["clock"] for tick in shown["ticks"]] == ["2026-10-17T14:55:00Z", "2026-10-17T15:00:00Z"]
    assert shown["official_phases"] == {"onset": ["2026-10-17T13:19:00Z", "2026-10-17T13:19:00Z"]}
    assert (shown["episode"], shown["start"], shown["end"], shown["step_minutes"], shown["results"]) == (
        "55", "2026-10-17T13:00:00Z", "2026-10-17T19:30:00Z", 5, None)


def test_the_replays_results_show_only_at_the_episodes_end(conn, tmp_path):
    folder = tmp_path / "replay" / "ep55"
    folder.mkdir(parents=True)
    comparison = {"heights": [["plume top (peak)", "04:50-05:10", "kilauea-kp", "25,000 ft", "6,964 ± 419 m",
                               "-656 m (-9 %)", "-1.6", "yes"]],
                  "ends": [], "drift": [], "bulletins": [], "activity": []}
    (folder / "timeline.json").write_text(json.dumps({"step_minutes": 5, "comparison": comparison, "phases": None,
                                                      "cost_usd": 1.03}), encoding="utf-8")

    before = views.replay_state(scene(conn, tmp_path, clock=EP55.end - M, episode=EP55), folder)
    at_end = views.replay_state(scene(conn, tmp_path, clock=EP55.end, episode=EP55), folder)

    assert before["results"] is None
    heights = next(t for t in at_end["results"]["tables"] if t["title"] == "Measurements against the official values")
    assert heights["header"] == HEIGHT_HEADER and heights["rows"] == comparison["heights"]
    assert at_end["results"]["cost_usd"] == 1.03 and len(at_end["official_phases"]) == 4


def test_a_frame_image_is_scaled_with_the_masks_of_its_visible_detections(conn, store, tmp_path):
    shown, later = add_frame(conn, store, "kilauea-kp", -5), add_frame(conn, store, "kilauea-kp", 5)
    add_track(conn, add_run(conn, "kilauea-kp", "plume", [shown]), [shown])  # box (60, 60, 120, 150)

    plain, drawn = (Image.open(io.BytesIO(views.frame_image(scene(conn, tmp_path), shown, width=320,
                                                              overlay=overlay))).convert("RGB")
                    for overlay in (False, True))

    assert plain.size == drawn.size == (320, 180)
    inside = (round(90 * 320 / 384), round(105 * 320 / 384))  # the box's middle, scaled
    assert drawn.getpixel(inside)[2] > plain.getpixel(inside)[2] + 40  # tinted towards the plume's blue
    assert Image.open(io.BytesIO(views.frame_image(scene(conn, tmp_path), shown, width=1280))).size == (384, 216)
    with pytest.raises(LookupError):
        views.frame_image(scene(conn, tmp_path), later, width=320)


def test_a_mask_of_a_run_that_closes_after_the_clock_is_not_drawn(conn, store, tmp_path):
    shown, later = add_frame(conn, store, "kilauea-kp", -5), add_frame(conn, store, "kilauea-kp", 5)
    add_track(conn, add_run(conn, "kilauea-kp", "plume", [shown, later]), [shown, later])

    plain = views.frame_image(scene(conn, tmp_path), shown, width=384, overlay=False)

    assert views.frame_image(scene(conn, tmp_path), shown, width=384) == plain


def test_a_frame_whose_file_is_gone_has_no_image(conn, store, tmp_path):
    gone = add_frame(conn, store, "kilauea-kp", -5)
    (tmp_path / conn.execute("SELECT path FROM frames WHERE id = ?", (gone,)).fetchone()[0]).unlink()

    with pytest.raises(LookupError, match="file"):
        views.frame_image(scene(conn, tmp_path), gone, width=320)


def test_alerts_show_only_those_raised_by_the_clock_and_the_state_they_leave(conn, tmp_path):
    store_alert(conn, make_alert("onset", clock="2026-10-17T13:10:00Z"))
    store_alert(conn, make_alert("end", clock="2026-10-17T19:09:00Z"))

    before = views.alerts(scene(conn, tmp_path, clock=parse_utc("2026-10-17T13:09:59Z")))
    during = views.alerts(scene(conn, tmp_path, clock=parse_utc("2026-10-17T15:00:00Z")))
    after = views.alerts(scene(conn, tmp_path, clock=parse_utc("2026-10-17T19:30:00Z")))

    assert (before["state"], before["alerts"]) == ("quiet", [])
    assert during["state"] == "fountaining" and [a["kind"] for a in during["alerts"]] == ["onset"]
    assert after["state"] == "quiet" and [a["kind"] for a in after["alerts"]] == ["end", "onset"]
    shown = during["alerts"][0]
    assert set(shown) >= {"id", "kind", "clock", "captured_at", "seen_at", "seen_by", "camera_id", "overlay",
                          "official_agency", "official_url", "headline", "text", "disclaimer"}
    assert "en" not in shown and "es" not in shown


def test_a_database_from_before_the_alerts_has_none(tmp_path):
    old = sqlite3.connect(tmp_path / "old.sqlite")
    old.execute("CREATE TABLE frames (id INTEGER)")
    old.row_factory = sqlite3.Row

    assert views.alerts(scene(old, tmp_path)) == {"state": "quiet", "alerts": []}


def test_the_replays_results_list_the_alerts_table_when_the_timeline_has_one(conn, tmp_path):
    folder = tmp_path / "replay" / "ep55"
    folder.mkdir(parents=True)
    row = ["fountaining started", "03:07", "V1cam", "03:19", "-12 min", "03:10", "-9 min", "03:43", "-33 min"]
    comparison = {"heights": [], "ends": [], "drift": [], "bulletins": [], "activity": [], "alerts": [row]}
    (folder / "timeline.json").write_text(json.dumps({"step_minutes": 5, "comparison": comparison, "phases": None,
                                                      "cost_usd": 1.4}), encoding="utf-8")

    shown = views.replay_state(scene(conn, tmp_path, clock=EP55.end, episode=EP55), folder)

    table = next(t for t in shown["results"]["tables"] if t["title"] == "Fountaining alerts against the official times")
    assert table["rows"] == [row]
