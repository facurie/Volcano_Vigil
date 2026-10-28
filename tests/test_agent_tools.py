import io
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx
import numpy as np
import pytest
from PIL import Image
from pydantic import AwareDatetime, Field

from test_gate import ANSWER, encode, flat, sharp, spark_api
from test_meta_client import FakeApi, make_client, response_body
from test_metrics import kp_calibration
from test_sam import IMAGE_OUTPUT, OBJ_0
from test_tracking import FakeMeta, needs_ffmpeg
from vigia import masks
from vigia.agent.tools import (TOOLS, Args, FrameArgs, HistoryArgs, NoArgs, RecentFramesArgs, SegmentArgs, Tool,
                               ToolContext, ToolError, Toolbox, TrackArgs, TrackIdArgs, assess_frame, get_history,
                               get_recent_frames, list_cameras_status, measure_track, segment_frame, strict_schema,
                               track_window_tool)
from vigia.config import Camera, Sources, Volcano
from vigia.ingest.store import FrameStore
from vigia.meta.ledger import BudgetExceeded
from vigia.prompts import Prompts
from vigia.timeutil import to_iso
from vigia.wind import WindService

NOW = datetime(2026, 10, 28, 18, 0, tzinfo=timezone.utc)   # wall clock: Oct 17 is history for Open-Meteo
T0 = datetime(2026, 10, 17, 15, 0, 0, tzinfo=timezone.utc)  # the agent's clock: 05:00 HST in episode 55
SIZE = (384, 216)                                           # the frame size kp_calibration() expects


def cam(camera_id, enabled=False):
    return Camera(id=camera_id, name=camera_id, volcano="kilauea", url=f"https://example.org/{camera_id}.jpg",
                  license="Public Domain", attribution="U.S. Geological Survey", enabled=enabled)


SOURCES = Sources(
    volcanoes={"kilauea": Volcano(name="Kilauea", country="United States",
                                  official_agency="USGS Hawaiian Volcano Observatory (HVO)",
                                  official_url="https://www.usgs.gov/volcanoes/kilauea", lat=19.405, lon=-155.29)},
    cameras=[cam("kilauea-kp", enabled=True), cam("kilauea-k2", enabled=True), cam("kilauea-v1"), cam("kilauea-v2")],
)
PROMPTS = Prompts(plume={"visible": ["steam"]}, fountain={"visible": ["lava fountain"]})


def context(conn, tmp_path, *, client=None, now=T0, open_meteo=None):
    """Tools over the test database at clock `now`; Open-Meteo answers `open_meteo` or fails with HTTP 500."""
    def answer(request):
        return httpx.Response(200, json=open_meteo) if open_meteo is not None else httpx.Response(500)
    winds = WindService(conn, httpx.Client(transport=httpx.MockTransport(answer)), SOURCES, now=lambda: NOW)
    return ToolContext(conn=conn, data_dir=tmp_path, sources=SOURCES, calibration=kp_calibration(),
                       prompts=PROMPTS, winds=winds, now=now, client=client)


@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def frame_jpeg(n, size=SIZE):
    """A JPEG unique to n: its bits as white squares along the top edge."""
    image = Image.new("RGB", size, (90, 90, 90))
    for bit in range(12):
        if n >> bit & 1:
            image.paste((255, 255, 255), (bit * 16, 0, bit * 16 + 16, 16))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def add_frame(conn, store, camera_id, minutes, usable=True, reasons=(), size=SIZE):
    """A frame `minutes` from the agent's clock, with a quality verdict (usable=None: none yet)."""
    captured_at = T0 + timedelta(minutes=minutes)
    frame_id = store.add(camera_id, frame_jpeg(minutes + 1000, size), captured_at=captured_at,
                         timestamp_source="ashcam", fetched_at=captured_at)
    if usable is not None:
        with conn:
            conn.execute(
                """INSERT INTO frame_quality (frame_id, assessed_at, usable, decided_by, local_decision, reasons,
                                              brightness, contrast, edge_density, glow_fraction)
                   VALUES (?, '2026-10-28T00:00:00Z', ?, 'local', ?, ?, 100, 40, 0.1, 0)""",
                (frame_id, int(usable), "pass" if usable else "reject", json.dumps(list(reasons))))
    return frame_id


def capture_times(conn, frame_ids):
    return [conn.execute("SELECT captured_at FROM frames WHERE id = ?", (i,)).fetchone()[0] for i in frame_ids]


def add_run(conn, camera_id, target, frame_ids, phrase=None):
    times = capture_times(conn, frame_ids)
    with conn:
        return conn.execute(
            """INSERT INTO tracking_runs (camera_id, target, phrase, window_start, window_end, frame_ids,
                                          video_width, video_height, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 384, 216, '2026-10-28T00:00:00Z')""",
            (camera_id, target, phrase or target, min(times), max(times), json.dumps(frame_ids))).lastrowid


def add_track(conn, run_id, frame_ids, box=(60, 60, 120, 150), object_id="0"):
    """A track of the run detected on every frame of `frame_ids` with a full-box mask; returns its id."""
    times = capture_times(conn, frame_ids)
    left, top, right, bottom = box
    mask = np.ones((bottom - top, right - left), dtype=bool)
    with conn:
        track_id = conn.execute(
            "INSERT INTO tracks (run_id, object_id, first_seen, last_seen, detections) VALUES (?, ?, ?, ?, ?)",
            (run_id, object_id, min(times), max(times), len(frame_ids))).lastrowid
        for frame_id in frame_ids:
            conn.execute(
                """INSERT INTO detections (track_id, frame_id, box_left, box_top, box_right, box_bottom, score,
                                           area_px, mask_rle) VALUES (?, ?, ?, ?, ?, ?, 0.8, ?, ?)""",
                (track_id, frame_id, *box, int(mask.sum()), json.dumps(masks.encode(mask))))
    return track_id


def detection_ids(conn, track_id):
    return [row[0] for row in conn.execute("SELECT id FROM detections WHERE track_id = ? ORDER BY id", (track_id,))]


def add_measurement(conn, frame_id, metric, value, sigma, *, detection_id, target="plume", unit="m"):
    with conn:
        conn.execute(
            """INSERT INTO measurements (detection_id, frame_id, camera_id, captured_at, target, metric, value,
                                         sigma, unit, preset, computed_at)
               SELECT ?, id, camera_id, captured_at, ?, ?, ?, ?, ?, 'fixed', '2026-10-28T00:00:00Z'
               FROM frames WHERE id = ?""",
            (detection_id, target, metric, value, sigma, unit, frame_id))


# --- the framework


class Example(Args):
    camera_id: str = Field(description="camera id")
    hours: float = Field(gt=0, le=24)
    target: Literal["plume", "fountain"]
    time: AwareDatetime | None = Field(default=None, description="UTC; null for now")


def test_strict_schema_requires_every_argument_and_types_nullable_ones_with_null():
    assert strict_schema(Example) == {
        "type": "object",
        "properties": {
            "camera_id": {"type": "string", "description": "camera id"},
            "hours": {"type": "number"},
            "target": {"type": "string", "enum": ["plume", "fountain"]},
            "time": {"type": ["string", "null"], "description": "UTC; null for now"},
        },
        "required": ["camera_id", "hours", "target", "time"],
        "additionalProperties": False,
    }


def test_every_tool_is_a_strict_function_with_a_valid_name():
    for tool in TOOLS:
        definition = tool.definition()
        assert definition["type"] == "function" and definition["strict"] is True
        assert re.fullmatch(r"[a-zA-Z0-9_-]+", definition["name"])
        parameters = definition["parameters"]
        assert parameters["additionalProperties"] is False
        assert parameters["required"] == list(parameters["properties"])


class EchoArgs(Args):
    n: int = Field(ge=1)
    when: AwareDatetime | None = None


def echo(ctx, args):
    if args.n == 13:
        raise ToolError("unlucky")
    if args.n == 99:
        raise RuntimeError("boom")
    return {"n": args.n, "when": None if args.when is None else to_iso(args.when)}


ECHO = Tool("echo", "Echo n.", EchoArgs, echo)


def test_a_valid_call_runs_the_tool(conn, tmp_path):
    box = Toolbox(context(conn, tmp_path), [ECHO])

    assert box.call("echo", '{"n": 2, "when": "2026-10-17T05:00:00-10:00"}') == (
        {"n": 2, "when": "2026-10-17T15:00:00Z"}, True)


def test_the_string_null_counts_as_null(conn, tmp_path):
    # Muse Spark sent "time": "null" in the planning probe
    assert Toolbox(context(conn, tmp_path), [ECHO]).call("echo", '{"n": 2, "when": "null"}') == (
        {"n": 2, "when": None}, True)


def test_the_clock_must_have_a_time_zone(conn, tmp_path):
    with pytest.raises(ValueError, match="time zone"):
        context(conn, tmp_path, now=datetime(2026, 10, 17, 15, 0))


def test_a_spent_run_budget_is_an_error_for_the_model_without_a_traceback(conn, tmp_path, caplog):
    def spend(ctx, args):
        raise BudgetExceeded("budget $0.30 of agent:1 would be exceeded")

    result, ok = Toolbox(context(conn, tmp_path), [Tool("spend", "Spend.", NoArgs, spend)]).call("spend", "{}")

    assert ok is False
    assert result == {"error": "the run's budget is spent: budget $0.30 of agent:1 would be exceeded"}
    assert caplog.records == []


@pytest.mark.parametrize("name, arguments, message", [
    ("nope", "{}", "unknown tool 'nope'"),
    ("echo", "{n: 2}", "not JSON"),
    ("echo", "[2]", "JSON object"),
    ("echo", '{"n": 0}', "n: Input should be greater than or equal to 1"),
    ("echo", '{"n": 2, "extra": 1}', "extra"),
    ("echo", '{"n": 2, "when": "2026-10-17T05:00"}', "when: Input should have timezone info"),
    ("echo", '{"n": 13}', "unlucky"),
    ("echo", '{"n": 99}', "echo failed: RuntimeError: boom"),
])
def test_a_bad_call_or_a_failing_tool_is_an_error_for_the_model(conn, tmp_path, name, arguments, message):
    result, ok = Toolbox(context(conn, tmp_path), [ECHO]).call(name, arguments)

    assert ok is False
    assert message in result["error"]


# --- list_cameras_status


def test_list_cameras_status_reports_each_cameras_latest_frame_as_of_the_clock(conn, store, tmp_path):
    kp_old = add_frame(conn, store, "kilauea-kp", -10)
    kp_latest = add_frame(conn, store, "kilauea-kp", -5)
    kp_future = add_frame(conn, store, "kilauea-kp", 5)                  # after the clock: unseen
    add_frame(conn, store, "kilauea-k2", -45, usable=False, reasons=["low_visibility"])
    add_frame(conn, store, "kilauea-v1", -2, usable=None)                # disabled, but it has frames
    add_track(conn, add_run(conn, "kilauea-kp", "plume", [kp_old, kp_latest, kp_future]),
              [kp_old, kp_latest, kp_future])

    result = list_cameras_status(context(conn, tmp_path), NoArgs())

    cameras = {c["camera_id"]: c for c in result["cameras"]}
    assert result["now"] == "2026-10-17T15:00:00Z"
    assert set(cameras) == {"kilauea-kp", "kilauea-k2", "kilauea-v1"}  # kilauea-v2: disabled and no frames
    kp = cameras["kilauea-kp"]
    assert (kp["status"], kp["calibrated"]) == ("usable", True)
    assert kp["latest_frame"] == {"frame_id": kp_latest, "captured_at": "2026-10-17T14:55:00Z", "minutes_ago": 5.0,
                                  "usable": True, "reasons": []}
    assert (kp["frames_last_hour"], kp["usable_last_hour"]) == (2, 2)
    assert kp["last_detection"] == {"plume": "2026-10-17T14:55:00Z"}
    assert (cameras["kilauea-k2"]["status"], cameras["kilauea-k2"]["calibrated"]) == ("stale", False)
    assert cameras["kilauea-v1"]["status"] == "unassessed"


# --- get_recent_frames


def test_get_recent_frames_lists_the_newest_frames_with_verdicts_and_detections(conn, store, tmp_path):
    older, earlier, later = (add_frame(conn, store, "kilauea-kp", m) for m in (-90, -50, -30))
    rejected = add_frame(conn, store, "kilauea-kp", -20, usable=False, reasons=["low_visibility"])
    add_frame(conn, store, "kilauea-kp", 3)  # after the clock
    add_track(conn, add_run(conn, "kilauea-kp", "plume", [earlier, later]), [earlier, later])

    result = get_recent_frames(context(conn, tmp_path), RecentFramesArgs(camera_id="kilauea-kp", hours=1))

    assert (result["frames"], result["usable"], result["unassessed"]) == (3, 2, 0)
    assert result["rejected_by_reason"] == {"low_visibility": 1}
    assert [f["frame_id"] for f in result["recent"]] == [rejected, later, earlier]
    assert result["recent"][0]["reasons"] == ["low_visibility"]
    assert result["recent"][1]["detections"] == {"plume": 1}


def test_an_unknown_camera_is_a_tool_error(conn, tmp_path):
    with pytest.raises(ToolError, match="list_cameras_status"):
        get_recent_frames(context(conn, tmp_path), RecentFramesArgs(camera_id="etna-1", hours=1))


# --- get_history


def test_get_history_gives_the_series_up_to_the_clock_with_its_extremes(conn, store, tmp_path):
    frames = [add_frame(conn, store, "kilauea-kp", m) for m in (-30, -20, -10, 5)]
    for i, (frame_id, value) in enumerate(zip(frames, (5000, 6900, 6500, 7500))):
        add_measurement(conn, frame_id, "top_altitude", value, 300, detection_id=i)
    add_measurement(conn, frames[1], "top_altitude", 2000, 50, detection_id=10)  # a lower detection, same frame

    result = get_history(context(conn, tmp_path), HistoryArgs(camera_id="kilauea-kp", metric="top_altitude",
                                                              target="plume", hours=1))

    assert (result["frames"], result["unit"]) == (3, "m")
    assert [p["value"] for p in result["points"]] == [5000, 6900, 6500]
    assert result["max"] == {"captured_at": "2026-10-17T14:40:00Z", "frame_id": frames[1], "value": 6900, "sigma": 300}
    assert result["latest"]["value"] == 6500


def test_a_bearing_history_has_no_extremes(conn, store, tmp_path):
    frames = [add_frame(conn, store, "kilauea-kp", m) for m in (-20, -10)]
    for i, (frame_id, value) in enumerate(zip(frames, (359.0, 1.0))):
        add_measurement(conn, frame_id, "drift_bearing", value, 5, detection_id=i, unit="deg")

    result = get_history(context(conn, tmp_path), HistoryArgs(camera_id="kilauea-kp", metric="drift_bearing",
                                                              target="plume", hours=1))

    assert "max" not in result and "min" not in result
    assert (result["frames"], result["unit"], result["latest"]["value"]) == (2, "deg", 1.0)
    assert [p["value"] for p in result["points"]] == [359.0, 1.0]


def test_a_long_history_is_thinned_but_keeps_its_ends(conn, store, tmp_path):
    frames = [add_frame(conn, store, "kilauea-kp", -2 * i) for i in range(60, 0, -1)]
    for i, frame_id in enumerate(frames):
        add_measurement(conn, frame_id, "top_altitude", 1000 + i, 10, detection_id=i)

    result = get_history(context(conn, tmp_path), HistoryArgs(camera_id="kilauea-kp", metric="top_altitude",
                                                              target="plume", hours=3))

    assert (result["frames"], len(result["points"])) == (60, 40)
    assert (result["points"][0]["value"], result["points"][-1]["value"]) == (1000, 1059)


def test_a_camera_without_measurements_has_an_empty_history_and_a_hint(conn, tmp_path):
    result = get_history(context(conn, tmp_path), HistoryArgs(camera_id="kilauea-kp", metric="top_height",
                                                              target="fountain", hours=6))

    assert result["points"] == []
    assert "measure_track" in result["note"]


DAY = datetime(2026, 10, 17, 22, 0, 5, tzinfo=timezone.utc)  # 12:00 HST: the night check stays out of the way


def add_image(store, image, captured_at=DAY):
    return store.add("kilauea-kp", encode(image), captured_at=captured_at, timestamp_source="ashcam",
                     fetched_at=captured_at)


def test_assess_frame_asks_muse_spark_about_a_frame_the_local_checks_passed(conn, store, tmp_path):
    frame_id = add_image(store, sharp())
    api = spark_api()
    ctx = context(conn, tmp_path, client=make_client(api, conn), now=DAY + timedelta(minutes=5))

    result = assess_frame(ctx, FrameArgs(frame_id=frame_id))

    assert len(api.requests) == 1
    assert (result["usable"], result["decided_by"], result["activity"]) == (True, "spark", "steaming")
    assert result["description"] == ANSWER["description_en"]
    assert result["printed_ptz"] == {"pan": 29.0, "tilt": 0.0, "zoom_raw": 29.0, "zoom": 1.0}
    assert result["camera_id"] == "kilauea-kp" and result["captured_at"] == "2026-10-17T22:00:05Z"


def test_assess_frame_reuses_a_muse_spark_verdict(conn, store, tmp_path):
    frame_id = add_image(store, sharp())
    api = spark_api()
    ctx = context(conn, tmp_path, client=make_client(api, conn), now=DAY + timedelta(minutes=5))

    assess_frame(ctx, FrameArgs(frame_id=frame_id))
    again = assess_frame(ctx, FrameArgs(frame_id=frame_id))

    assert len(api.requests) == 1 and again["decided_by"] == "spark"


def test_assess_frame_does_not_ask_about_a_frame_the_local_checks_rejected(conn, store, tmp_path):
    frame_id = add_image(store, flat(150))  # fog: no edges
    api = spark_api()
    ctx = context(conn, tmp_path, client=make_client(api, conn), now=DAY + timedelta(minutes=5))

    result = assess_frame(ctx, FrameArgs(frame_id=frame_id))

    assert api.requests == []
    assert result["usable"] is False and "low_visibility" in result["reasons"]


def test_a_frame_after_the_clock_does_not_exist_for_the_agent(conn, store, tmp_path):
    frame_id = add_image(store, sharp())

    with pytest.raises(ToolError, match=f"no frame {frame_id}"):
        assess_frame(context(conn, tmp_path, now=DAY - timedelta(minutes=1)), FrameArgs(frame_id=frame_id))


def test_segment_frame_returns_sams_objects_in_the_frames_pixels(conn, store, tmp_path):
    # a 4096 px frame is sent at 2048 px, so SAM's boxes double on the way back
    frame_id = store.add("kilauea-kp", frame_jpeg(1, size=(4096, 4096)), captured_at=T0 - timedelta(minutes=5),
                         timestamp_source="ashcam", fetched_at=T0)
    api = FakeApi(lambda r: httpx.Response(200, json=response_body("sam-3.1", IMAGE_OUTPUT, {"images_processed": 1})))

    result = segment_frame(context(conn, tmp_path, client=make_client(api, conn)),
                           SegmentArgs(frame_id=frame_id, phrase="steam"))

    assert api.json_body()["input"][0]["content"][0] == {"type": "input_text", "text": "steam"}
    assert (result["phrase"], result["objects_found"]) == ("steam", 2)
    best = result["objects"][0]
    assert best == {"object_id": "0", "score": 0.96, "box": [422, 456, 542, 510], "top_row": 456,
                    "area_fraction": 0.00037}
    assert result["objects"][1]["score"] == 0.5


def test_segment_frame_cannot_see_a_frame_after_the_clock(conn, store, tmp_path):
    frame_id = add_frame(conn, store, "kilauea-kp", 5)
    api = FakeApi(lambda r: httpx.Response(200, json=response_body("sam-3.1", IMAGE_OUTPUT, {"images_processed": 1})))

    with pytest.raises(ToolError, match=f"no frame {frame_id} captured by"):
        segment_frame(context(conn, tmp_path, client=make_client(api, conn)),
                      SegmentArgs(frame_id=frame_id, phrase="steam"))

    assert api.requests == []


def test_segment_frame_needs_a_meta_client(conn, store, tmp_path):
    frame_id = add_frame(conn, store, "kilauea-kp", -5)

    with pytest.raises(ToolError, match="Meta client"):
        segment_frame(context(conn, tmp_path), SegmentArgs(frame_id=frame_id, phrase="steam"))


# --- track_window and measure_track


def test_track_window_returns_stored_tracks_that_cover_the_window_without_calling_sam(conn, store, tmp_path):
    frames = [add_frame(conn, store, "kilauea-kp", m) for m in range(-55, 30, 5)]  # the last 5 after the clock
    track = add_track(conn, add_run(conn, "kilauea-kp", "plume", frames, phrase="steam"), frames)

    result = track_window_tool(context(conn, tmp_path), TrackArgs(
        camera_id="kilauea-kp", start=T0 - timedelta(hours=1), end=T0 + timedelta(hours=1), target="plume"))

    assert (result["cached"], result["end"], result["usable_frames"]) == (True, "2026-10-17T15:00:00Z", 12)
    assert result["tracks"] == [{"track_id": track, "phrase": "steam", "object_id": "0", "detections": 12,
                                 "first_seen": "2026-10-17T14:05:00Z", "last_seen": "2026-10-17T15:00:00Z",
                                 "mean_score": 0.8, "max_area_px": 5400}]


def test_track_window_refuses_to_track_too_few_frames(conn, store, tmp_path):
    for m in (-15, -10, -5):
        add_frame(conn, store, "kilauea-kp", m)

    with pytest.raises(ToolError, match="only 3 usable frames"):
        track_window_tool(context(conn, tmp_path), TrackArgs(
            camera_id="kilauea-kp", start=T0 - timedelta(hours=1), end=T0, target="plume"))


def test_track_window_refuses_windows_over_three_hours(conn, tmp_path):
    with pytest.raises(ToolError, match="3 hours"):
        track_window_tool(context(conn, tmp_path), TrackArgs(
            camera_id="kilauea-kp", start=T0 - timedelta(hours=4), end=T0, target="plume"))


@needs_ffmpeg
def test_track_window_tracks_an_untracked_window_with_the_targets_phrases(conn, store, tmp_path):
    for m in range(-50, 1, 5):  # 11 frames
        add_frame(conn, store, "kilauea-kp", m, size=(640, 668))
    fake = FakeMeta({"steam": f"<0f>{OBJ_0}\n<10f>{OBJ_0}\n"})

    result = track_window_tool(context(conn, tmp_path, client=make_client(fake, conn)), TrackArgs(
        camera_id="kilauea-kp", start=T0 - timedelta(hours=1), end=T0, target="plume"))

    assert (result["cached"], result["usable_frames"]) == (False, 11)
    assert [track["detections"] for track in result["tracks"]] == [2]
    assert [row[0] for row in conn.execute("SELECT phrase FROM tracking_runs")] == ["steam"]


def test_measure_track_measures_the_track_up_to_the_clock(conn, store, tmp_path):
    frames = [add_frame(conn, store, "kilauea-kp", m) for m in (-10, -5, 5)]
    track = add_track(conn, add_run(conn, "kilauea-kp", "plume", frames), frames, box=(80, 60, 120, 150))

    result = measure_track(context(conn, tmp_path), TrackIdArgs(track_id=track))

    assert (result["camera_id"], result["target"], result["last"]) == ("kilauea-kp", "plume", "2026-10-17T14:55:00Z")
    assert set(result["metrics"]) == {"top_height", "top_altitude", "area", "drift_offset", "drift_bearing"}
    top = result["metrics"]["top_altitude"]
    assert (top["frames"], top["unit"], top["latest"]["frame_id"]) == (2, "m", frames[1])
    assert top["latest"]["sigma"] > 0
    assert sum(result["metrics"]["drift_bearing"]["frames_per_side"].values()) == 2
    assert conn.execute("SELECT COUNT(DISTINCT frame_id) FROM measurements").fetchone()[0] == 2  # not the later one


def test_a_track_of_an_uncalibrated_camera_cannot_be_measured(conn, store, tmp_path):
    frames = [add_frame(conn, store, "kilauea-k2", -5)]
    track = add_track(conn, add_run(conn, "kilauea-k2", "fountain", frames), frames)

    with pytest.raises(ToolError, match="kilauea-k2 is not calibrated"):
        measure_track(context(conn, tmp_path), TrackIdArgs(track_id=track))


def test_a_track_seen_only_after_the_clock_cannot_be_measured(conn, store, tmp_path):
    frames = [add_frame(conn, store, "kilauea-kp", 5)]
    track = add_track(conn, add_run(conn, "kilauea-kp", "plume", frames), frames)

    with pytest.raises(ToolError, match="no detections by 2026-10-17T15:00:00Z"):
        measure_track(context(conn, tmp_path), TrackIdArgs(track_id=track))
