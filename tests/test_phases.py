import json
from dataclasses import replace
from datetime import timedelta

import httpx

from test_agent_tools import SOURCES, T0, add_frame, add_run, add_track, context, store  # store is a fixture
from test_meta_client import SPARK_USAGE, make_client, response_body
from test_tracking import UPLOADED, needs_ffmpeg
from vigia.episodes import EP55
from vigia.phases import PHASES, ask_phases, cross_check, sam_phases

M = timedelta(minutes=1)
HEIGHTS = [10, 20, 40, 60, 70, 72, 70, 66, 62, 58, 40, 20]  # running medians: 20 30 40 60 70 70 70 66 62 58 49 40


def fountain(conn, store, camera_id, minutes, height):
    """A frame `minutes` from 15:00Z on which a fountain `height` pixels tall was tracked."""
    frame_id = add_frame(conn, store, camera_id, minutes)
    add_track(conn, add_run(conn, camera_id, "fountain", [frame_id]), [frame_id], box=(60, 150 - height, 120, 150))
    return frame_id


def test_sam_phases_read_the_fountains_height_through_the_episode(conn, store):
    for i, height in enumerate(HEIGHTS):
        fountain(conn, store, "kilauea-k2", 2 * i, height)

    assert sam_phases(conn, "kilauea-k2", T0, T0 + 30 * M) == {
        "onset": "2026-10-17T15:00:00Z", "peak": "2026-10-17T15:08:00Z",  # the first highest running median
        "decline": "2026-10-17T15:16:00Z", "end": "2026-10-17T15:22:00Z"}  # first under 90 % of it; last


def test_sam_phases_without_a_fountain_are_empty(conn):
    assert sam_phases(conn, "kilauea-k2", T0, T0 + 30 * M) == dict.fromkeys(PHASES)


def test_cross_check_sets_each_reading_against_the_official_window(conn, store):
    fountain(conn, store, "kilauea-v1", -35, 10)  # 14:25: the first fountain on any camera
    for i, height in enumerate(HEIGHTS):
        fountain(conn, store, "kilauea-k2", 2 * i - 20, height)  # 14:40 to 15:02
    episode = replace(EP55, start=T0 - 60 * M, end=T0 + 60 * M, phases={
        "onset": (T0 - 30 * M,) * 2, "peak": (T0, T0 + 10 * M), "decline": (T0 + 10 * M, T0 + 30 * M),
        "end": (T0 + 40 * M,) * 2})
    spark = {"onset": {"seen": True, "time": "2026-10-17T14:20:00Z"},
             "peak": {"seen": True, "time": "2026-10-17T16:42:00Z"},
             "decline": {"seen": False, "time": None}, "end": {"seen": True, "time": "2026-10-17T15:45:00Z"}}

    result = cross_check(conn, episode, spark)

    assert result["rows"] == [
        ["onset", "04:30", "04:40 (+10 min)", "kilauea-v1: 04:25 (-5 min)", "04:20 (-10 min)"],
        ["peak", "05:00-05:10", "04:48 (-12 min)", "-", "06:42 (+92 min)"],
        ["decline", "05:10-05:30", "04:56 (-14 min)", "-", "-"],
        ["end", "05:40", "05:02 (-38 min)", "kilauea-k2: 05:02 (-38 min)", "05:45 (+5 min)"]]
    assert result["camera_id"] == "kilauea-k2" and result["muse_spark"] == spark
    assert result["sam"]["peak"] == "2026-10-17T14:48:00Z"
    assert result["sam_any_camera"]["onset"] == {"time": "2026-10-17T14:25:00Z", "camera_id": "kilauea-v1"}


def test_cross_check_without_muse_spark_says_it_was_not_asked(conn):
    assert [row[4] for row in cross_check(conn, EP55, None)["rows"]] == ["not asked"] * 4


def phase(second, seen=True, printed=""):
    return {"seen": seen, "video_second": second, "printed_time": printed, "description": "A fountain."}


ANSWER = {"onset": phase(0.5, printed="2026-10-17 05:02:00 HST"), "peak": phase(1.0), "decline": phase(2.4, seen=False),
          "end": phase(99), "summary": "A short fountain."}


class FakeVideoApi:
    """The Files API and one Muse Spark answer; records every request."""

    def __init__(self, answer):
        self.answer, self.requests = answer, []

    def __call__(self, request):
        self.requests.append(request)
        if request.url.path == "/v1/files":
            return httpx.Response(200, json=UPLOADED)
        if request.method == "DELETE":
            return httpx.Response(200, json={"id": "file-1", "object": "file", "deleted": True})
        return httpx.Response(200, json=response_body("muse-spark-1.3", json.dumps(self.answer), SPARK_USAGE))


@needs_ffmpeg
def test_ask_phases_maps_each_named_video_second_to_its_frames_capture_time(conn, store, tmp_path):
    for i in range(6):  # 15:00 to 15:10, every 2 minutes
        add_frame(conn, store, "kilauea-k2", 2 * i)
    api = FakeVideoApi(ANSWER)
    camera = context(conn, tmp_path).camera("kilauea-k2")

    result = ask_phases(make_client(api, conn), conn, tmp_path, camera, SOURCES.volcanoes["kilauea"], T0,
                        T0 + 10 * M)

    assert (result["camera_id"], result["frames"], result["fps"], result["summary"]) == (
        "kilauea-k2", 6, 2.0, "A short fountain.")
    assert result["onset"] == {**ANSWER["onset"], "time": "2026-10-17T15:02:00Z"}  # second 0.5 at 2 fps: frame 1
    assert result["peak"]["time"] == "2026-10-17T15:04:00Z"
    assert result["decline"]["time"] is None
    assert result["end"]["time"] == "2026-10-17T15:10:00Z"  # a second past the clip: its last frame
    sent = json.loads(api.requests[1].content)
    assert sent["input"][0]["content"][1] == {"type": "input_video", "file_id": "file-1"}
    prompt = sent["input"][0]["content"][0]["text"]
    assert "6 frames, captured about every 2 minutes from 15:00 to 15:10 (UTC)" in prompt
    assert "about 4 minutes x t after the first" in prompt
    assert api.requests[-1].method == "DELETE"
