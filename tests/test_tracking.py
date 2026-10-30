import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np
import pytest

from conftest import make_jpeg
from test_meta_client import make_client, response_body, sse
from test_sam import OBJ_0
from vigia import db, masks, tracking
from vigia.config import Camera
from vigia.ingest.store import FrameStore
from vigia.prompts import Prompts
from vigia.settings import Settings
from vigia.timeutil import to_iso
from vigia.tracking import detection_mask, main, track_window, unassessed_frames, usable_frames
from vigia.video import probe as real_probe

T0 = datetime(2026, 10, 17, 18, 0, 2, tzinfo=timezone.utc)


@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def add_frame(store, conn, minutes, usable=True, size=(64, 48), camera_id="kilauea-k2"):
    """Store a frame `minutes` after T0 with a quality verdict (usable=None: no verdict yet)."""
    frame_id = store.add(camera_id, make_jpeg(color=(10 + 3 * minutes, 80, 40), size=size),
                         captured_at=T0 + timedelta(minutes=minutes), timestamp_source="ashcam", fetched_at=T0)
    if usable is not None:
        conn.execute(
            """INSERT INTO frame_quality (frame_id, assessed_at, usable, decided_by, local_decision, reasons,
                                          brightness, contrast, edge_density, glow_fraction)
               VALUES (?, '2026-10-28T00:00:00Z', ?, 'local', ?, '[]', 100, 40, 0.1, 0)""",
            (frame_id, int(usable), "pass" if usable else "reject"),
        )
        conn.commit()
    return frame_id


def test_the_database_has_tracking_tables(conn):
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert {"tracking_runs", "tracks", "detections"} <= tables


def test_usable_frames_keeps_the_cameras_usable_frames_in_the_window_oldest_first(store, conn, tmp_path):
    later, first, middle = (add_frame(store, conn, minutes) for minutes in (4, 0, 2))
    add_frame(store, conn, 6, usable=False)
    add_frame(store, conn, 8, usable=None)
    add_frame(store, conn, 10)  # after the window
    add_frame(store, conn, 2, camera_id="kilauea-kp")

    frames = usable_frames(conn, tmp_path, "kilauea-k2", T0, T0 + timedelta(minutes=9))

    assert [f.id for f in frames] == [first, middle, later]
    assert frames[0].captured_at == T0
    assert frames[0].path.is_file() and (frames[0].width, frames[0].height) == (64, 48)


def test_unassessed_frames_counts_frames_without_a_verdict(store, conn):
    add_frame(store, conn, 0)
    add_frame(store, conn, 2, usable=None)
    add_frame(store, conn, 4, usable=None)

    assert unassessed_frames(conn, "kilauea-k2", T0, T0 + timedelta(minutes=5)) == 2


def test_detection_mask_places_the_box_mask_in_the_frame():
    box_mask = np.zeros((3, 4), dtype=bool)
    box_mask[1, 1:3] = True
    detection = {"id": 1, "box_left": 10, "box_top": 5, "box_right": 14, "box_bottom": 8,
                 "mask_rle": json.dumps(masks.encode(box_mask))}

    full = detection_mask(detection, width=20, height=10)

    assert full.shape == (10, 20) and full.sum() == 2
    assert full[6, 11] and full[6, 12]


def test_detection_mask_refuses_a_mask_that_does_not_fit_its_box():
    detection = {"id": 7, "box_left": 0, "box_top": 0, "box_right": 4, "box_bottom": 4,
                 "mask_rle": json.dumps(masks.encode(np.ones((3, 4), dtype=bool)))}

    with pytest.raises(ValueError, match="detection 7"):
        detection_mask(detection, width=10, height=10)


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

K2 = Camera(id="kilauea-k2", name="K2cam", volcano="kilauea", url="https://example.org/K2.jpg",
            license="Public Domain", attribution="U.S. Geological Survey")
PROMPTS = Prompts(plume={"visible": ["steam"]}, fountain={"visible": ["lava fountain"]})
UPLOADED = {"id": "file-1", "object": "file", "bytes": 1000, "created_at": 1793000000,
            "filename": "window.mp4", "purpose": "user_data"}
SERVER_ERROR = {"error": {"message": "boom", "type": "server_error", "param": None, "code": None}}


class FakeMeta:
    """The Files API plus streamed SAM video answers, one output text per phrase; records every request."""

    def __init__(self, outputs, failing=()):
        self.outputs = outputs
        self.failing = failing
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/v1/files":
            return httpx.Response(200, json=UPLOADED)
        if request.method == "DELETE":
            return httpx.Response(200, json={"id": "file-1", "object": "file", "deleted": True})
        phrase = json.loads(request.content)["input"][0]["content"][0]["text"]
        if phrase in self.failing:
            return httpx.Response(500, json=SERVER_ERROR)
        final = response_body("sam-3.1", "", {"video_frames_processed": 50})
        events = [{"type": "response.created", "sequence_number": 0,
                   "response": {**final, "status": "in_progress", "output": []}}]
        if self.outputs[phrase]:
            events.append({"type": "response.output_text.delta", "sequence_number": 1, "item_id": "msg_1",
                           "output_index": 0, "content_index": 0, "delta": self.outputs[phrase], "logprobs": []})
        events.append({"type": "response.completed", "sequence_number": 2, "response": final})
        return httpx.Response(200, content=sse(events), headers={"content-type": "text/event-stream"})

    def calls(self):
        return [(request.method, request.url.path) for request in self.requests]


def window(store, conn, count=3, size=(640, 668)):
    """`count` usable frames, 2 minutes apart from T0, twice the size of the 320x334 SAM sample."""
    return [add_frame(store, conn, 2 * i, size=size) for i in range(count)]


def track(fake, conn, tmp_path, prompts=PROMPTS, **kwargs):
    return track_window(make_client(fake, conn), conn, tmp_path, K2, prompts, T0, T0 + timedelta(hours=1),
                        max_height=334, **kwargs)


@needs_ffmpeg
def test_track_window_stores_runs_tracks_and_detections_in_frame_pixels(store, conn, tmp_path):
    ids = window(store, conn)
    fake = FakeMeta({"steam": f"<0f>{OBJ_0}\n<2f>{OBJ_0}\n", "lava fountain": ""})

    report = track(fake, conn, tmp_path)

    assert report.video_size == (320, 334)
    plume, fountain = report.runs
    assert (plume.target, plume.tracks, plume.detections) == ("plume", 1, 2)
    assert (plume.first_seen, plume.last_seen) == (T0, T0 + timedelta(minutes=4))
    assert (fountain.target, fountain.tracks, fountain.first_seen) == ("fountain", 0, None)
    run = conn.execute("SELECT * FROM tracking_runs WHERE id = ?", (plume.run_id,)).fetchone()
    assert json.loads(run["frame_ids"]) == ids
    rows = conn.execute("SELECT * FROM detections ORDER BY frame_id").fetchall()
    assert [row["frame_id"] for row in rows] == [ids[0], ids[2]]
    first = rows[0]
    assert (first["box_left"], first["box_top"], first["box_right"], first["box_bottom"]) == (422, 456, 542, 510)
    assert first["area_px"] == 4 * 1539
    assert first["score"] == pytest.approx(0.96)
    assert detection_mask(first, width=640, height=668).sum() == 4 * 1539


@pytest.fixture
def probed(monkeypatch):
    """The frame counts of the videos track_window probes."""
    counts = []

    def spy(video):
        info = real_probe(video)
        counts.append(info.frames)
        return info

    monkeypatch.setattr(tracking, "probe", spy)
    return counts


@needs_ffmpeg
def test_a_lead_in_puts_earlier_frames_before_the_window_and_stores_only_the_windows_part(store, conn, tmp_path, probed):
    add_frame(store, conn, -4, size=(640, 668))
    add_frame(store, conn, -2, size=(640, 668))
    ids = window(store, conn)
    fake = FakeMeta({"steam": f"<0f>{OBJ_0}\n<1f>{OBJ_0}\n<2f>{OBJ_0}\n<4f>{OBJ_0}\n", "lava fountain": ""})

    report = track(fake, conn, tmp_path, lead_in=2)

    assert probed == [5]
    plume = report.runs[0]
    assert (plume.tracks, plume.detections) == (1, 2)
    assert (plume.first_seen, plume.last_seen) == (T0, T0 + timedelta(minutes=4))
    run = conn.execute("SELECT * FROM tracking_runs WHERE id = ?", (plume.run_id,)).fetchone()
    assert json.loads(run["frame_ids"]) == ids
    assert (run["window_start"], run["window_end"]) == (to_iso(T0), to_iso(T0 + timedelta(minutes=4)))
    rows = conn.execute("SELECT * FROM detections ORDER BY frame_id").fetchall()
    assert [row["frame_id"] for row in rows] == [ids[0], ids[2]]


@needs_ffmpeg
def test_a_lead_in_longer_than_the_earlier_frames_uses_what_exists(store, conn, tmp_path, probed):
    add_frame(store, conn, -2, size=(640, 668))
    add_frame(store, conn, -2 - 24 * 60, size=(640, 668))  # a day before: out of reach
    window(store, conn)

    track(FakeMeta({"steam": "", "lava fountain": ""}), conn, tmp_path, lead_in=10)

    assert probed == [4]


@needs_ffmpeg
def test_a_lead_in_frame_of_another_size_is_left_out(store, conn, tmp_path, probed):
    add_frame(store, conn, -4, size=(320, 334))
    add_frame(store, conn, -2, size=(640, 668))
    window(store, conn)

    track(FakeMeta({"steam": "", "lava fountain": ""}), conn, tmp_path, lead_in=2)

    assert probed == [4]


@needs_ffmpeg
def test_a_lead_in_skips_frames_that_are_not_usable(store, conn, tmp_path, probed):
    add_frame(store, conn, -4, size=(640, 668), usable=False)
    window(store, conn)

    track(FakeMeta({"steam": "", "lava fountain": ""}), conn, tmp_path, lead_in=2)

    assert probed == [3]


@needs_ffmpeg
def test_track_window_uploads_the_window_once_and_deletes_it(store, conn, tmp_path):
    window(store, conn)
    fake = FakeMeta({"steam": "", "lava fountain": ""})

    track(fake, conn, tmp_path)

    assert fake.calls() == [("POST", "/v1/files"), ("POST", "/v1/responses"), ("POST", "/v1/responses"),
                            ("DELETE", "/v1/files/file-1")]
    assert [row["purpose"] for row in conn.execute("SELECT purpose FROM api_calls ORDER BY id")] == [
        "track:plume", "track:fountain"]


@needs_ffmpeg
def test_track_window_refuses_a_window_it_already_tracked_unless_redo(store, conn, tmp_path):
    window(store, conn)
    track(FakeMeta({"steam": f"<0f>{OBJ_0}\n", "lava fountain": ""}), conn, tmp_path)
    again = FakeMeta({"steam": "", "lava fountain": ""})

    with pytest.raises(ValueError, match="already tracked"):
        track(again, conn, tmp_path)
    assert again.requests == []

    track(again, conn, tmp_path, redo=True)
    assert conn.execute("SELECT COUNT(*) FROM tracking_runs").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0] == 0


@needs_ffmpeg
def test_a_failed_phrase_is_reported_and_the_others_go_on(store, conn, tmp_path):
    window(store, conn)
    fake = FakeMeta({"lava fountain": ""}, failing={"steam"})

    report = track(fake, conn, tmp_path)

    assert [run.phrase for run in report.runs] == ["lava fountain"]
    assert len(report.errors) == 1 and "steam" in report.errors[0]
    assert fake.calls()[-1] == ("DELETE", "/v1/files/file-1")


def test_track_window_needs_usable_frames(store, conn, tmp_path):
    add_frame(store, conn, 0, usable=False)

    with pytest.raises(ValueError, match="no usable frames"):
        track(FakeMeta({}), conn, tmp_path)


def test_track_window_refuses_frames_of_different_sizes(store, conn, tmp_path):
    add_frame(store, conn, 0, size=(640, 668))
    add_frame(store, conn, 2, size=(320, 334))
    fake = FakeMeta({})

    with pytest.raises(ValueError, match="sizes"):
        track(fake, conn, tmp_path)
    assert fake.requests == []


def test_a_phrase_listed_for_two_targets_is_refused_before_any_request(store, conn, tmp_path):
    window(store, conn)
    fake = FakeMeta({"steam": ""})
    twice = Prompts(plume={"visible": ["steam"]}, fountain={"visible": ["steam"]})

    with pytest.raises(ValueError, match="more than one target"):
        track(fake, conn, tmp_path, prompts=twice)
    assert fake.requests == []


@needs_ffmpeg
def test_a_run_that_cannot_be_stored_is_reported_and_the_others_go_on(store, conn, tmp_path):
    window(store, conn)
    fake = FakeMeta({"steam": f"<5f>{OBJ_0}\n", "lava fountain": ""})  # frame 5 is outside the 3-frame video

    report = track(fake, conn, tmp_path)

    assert [run.phrase for run in report.runs] == ["lava fountain"]
    assert len(report.errors) == 1 and "steam" in report.errors[0]
    assert conn.execute("SELECT COUNT(*) FROM tracking_runs WHERE phrase = 'steam'").fetchone()[0] == 0
    assert fake.calls()[-1] == ("DELETE", "/v1/files/file-1")


SOURCES_YAML = """
volcanoes:
  kilauea:
    name: Kīlauea
    country: United States
    official_agency: USGS Hawaiian Volcano Observatory
    official_url: https://www.usgs.gov/volcanoes/kilauea
    lat: 19.405
    lon: -155.29
cameras:
  - id: kilauea-k2
    name: K2cam
    volcano: kilauea
    url: https://example.org/K2cam/images/M.jpg
    license: Public Domain
    attribution: U.S. Geological Survey
"""
WINDOW = ["--start", "2026-10-17T18:00Z", "--end", "2026-10-17T19:00Z"]


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(SOURCES_YAML, encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigia.sqlite"))
    return tmp_path / "data"


def test_cli_refuses_a_window_under_the_billed_minimum(cli_env, capsys):
    conn = db.connect(cli_env / "vigia.sqlite")
    store = FrameStore(conn, cli_env)
    add_frame(store, conn, 0)
    add_frame(store, conn, 2, usable=None)
    conn.close()

    with pytest.raises(SystemExit):
        main(["--camera", "kilauea-k2", *WINDOW])

    err = capsys.readouterr().err
    assert "1 usable frames" in err and "50" in err and "vigia-quality" in err


def test_cli_refuses_an_unknown_camera(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--camera", "etna-1", *WINDOW])

    assert "etna-1" in capsys.readouterr().err


def test_cli_refuses_an_empty_window(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--camera", "kilauea-k2", "--start", "2026-10-17T19:00Z", "--end", "2026-10-17T18:00Z"])

    assert "before" in capsys.readouterr().err


def test_settings_name_the_prompts_file(monkeypatch):
    monkeypatch.setenv("PROMPTS_PATH", "elsewhere/prompts.yaml")

    assert Settings.from_env().prompts_path == Path("elsewhere/prompts.yaml")
