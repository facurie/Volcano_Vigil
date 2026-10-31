import io
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from test_agent_tools import T0, add_frame, add_run, add_track, frame_jpeg
from test_web_views import add_agent_run
from vigil import db
from vigil.episodes import EP55
from vigil.ingest.store import FrameStore
from vigil.settings import Settings
from vigil.timeutil import to_iso
from vigil.web.app import create_app, media_file

ROOT = Path(__file__).resolve().parent.parent
NOW = T0 + timedelta(days=13)  # the wall clock, 2026-10-30T15:00Z; T0 is 05:00 HST in episode 55
M = timedelta(minutes=1)


def settings(tmp_path):
    return Settings(data_dir=tmp_path, db_path=tmp_path / "vigil.sqlite",
                    sources_path=ROOT / "config" / "sources.yaml", prompts_path=ROOT / "config" / "prompts.yaml",
                    calibration_path=ROOT / "config" / "calibration.yaml", user_agent="test", daily_budget_usd=1.0)


def app_client(tmp_path):
    return TestClient(create_app(settings(tmp_path), now=lambda: NOW))


@pytest.fixture
def live(tmp_path):
    connection = db.connect(tmp_path / "vigil.sqlite")
    yield connection
    connection.close()


@pytest.fixture
def replayed(tmp_path):
    connection = db.connect(tmp_path / "replay" / "ep55" / "vigil.sqlite")
    yield connection
    connection.close()


@pytest.fixture
def client(tmp_path, live, replayed):
    return app_client(tmp_path)


AT = {"replay": "55", "at": to_iso(T0)}


def test_the_page_carries_the_notice_and_the_official_link(client):
    page = client.get("/")

    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "It does not replace official alerts or warnings." in page.text
    assert 'href="https://www.usgs.gov/volcanoes/kilauea"' in page.text
    assert "USGS Hawaiian Volcano Observatory (HVO)" in page.text and "{{" not in page.text


def test_config_names_the_volcano_its_cameras_and_the_replays_on_disk(client):
    config = client.get("/api/config").json()

    assert (config["volcano"]["name"], config["volcano"]["utc_offset_hours"]) == ("Kīlauea", -10)
    assert config["vent"]["lat"] == 19.40496
    assert config["live"] == {"cameras": ["kilauea-k2", "kilauea-kp", "kilauea-f1"], "available": True}
    assert [(r["episode"], r["start"], r["end"], r["step_minutes"]) for r in config["replays"]] == [
        ("55", "2026-10-17T13:00:00Z", "2026-10-17T19:30:00Z", 5)]
    assert config["disclaimer"]["es"].startswith("Lectura automática")
    assert config["now"] == to_iso(NOW)


def test_without_a_replay_database_config_lists_no_replay(tmp_path, live):
    assert app_client(tmp_path).get("/api/config").json()["replays"] == []


def test_live_answers_at_the_wall_clock(client, live, tmp_path):
    add_frame(live, FrameStore(live, tmp_path), "kilauea-kp", 0)  # 13 days before NOW

    cameras = client.get("/api/cameras").json()

    assert cameras["clock"] == to_iso(NOW)
    assert [(c["camera_id"], c["condition"]) for c in cameras["cameras"]] == [
        ("kilauea-k2", "no_frames"), ("kilauea-kp", "stale"), ("kilauea-f1", "no_frames")]


def test_a_replay_answers_at_its_simulated_clock(client, replayed, tmp_path):
    store = FrameStore(replayed, tmp_path)
    before, _ = add_frame(replayed, store, "kilauea-kp", -5), add_frame(replayed, store, "kilauea-kp", 5)

    shown = client.get("/api/frames/latest", params={**AT, "camera": "kilauea-kp"}).json()
    one = client.get(f"/api/frames/{before}", params=AT).json()

    assert (shown["clock"], shown["latest"]["frame_id"], one["frame"]["frame_id"]) == (to_iso(T0), before, before)
    cameras = client.get("/api/cameras", params=AT).json()["cameras"]
    assert [c["camera_id"] for c in cameras] == list(EP55.cameras)


@pytest.mark.parametrize("params, status", [
    ({"at": "2026-10-17T05:00:00"}, 422),                  # no UTC offset
    ({"at": to_iso(NOW + M)}, 422),                         # live, after now
    ({"replay": "55", "at": "2026-10-17T12:59:00Z"}, 422),  # before the episode
    ({"replay": "55", "at": "2026-10-17T19:31:00Z"}, 422),  # after it
    ({"replay": "54"}, 404)])                               # no such episode
def test_a_clock_the_scene_cannot_have_is_refused(client, params, status):
    assert client.get("/api/cameras", params=params).status_code == status


def test_an_episode_that_was_not_replayed_is_not_found(tmp_path, live):
    assert app_client(tmp_path).get("/api/cameras", params={"replay": "55"}).status_code == 404


def test_without_a_live_database_live_is_unavailable(tmp_path):
    client = app_client(tmp_path)

    assert client.get("/api/cameras").status_code == 503
    assert client.get("/api/config").json()["live"]["available"] is False
    assert not (tmp_path / "vigil.sqlite").exists()


def test_a_camera_or_frame_the_scene_does_not_show_is_not_found(client, replayed, tmp_path):
    later = add_frame(replayed, FrameStore(replayed, tmp_path), "kilauea-kp", 5)

    assert client.get("/api/frames/latest", params={"camera": "kilauea-v2"}).status_code == 404
    assert client.get(f"/api/frames/{later}", params=AT).status_code == 404
    assert client.get(f"/api/frames/{later}/image", params=AT).status_code == 404


def test_every_endpoint_answers_with_its_clock(client):
    for path, extra in (("/api/series", {"camera": "kilauea-kp", "target": "plume", "metric": "top_altitude"}),
                        ("/api/frames", {"camera": "kilauea-kp"}), ("/api/bulletins", {}),
                        ("/api/agent/trace", {}), ("/api/replay", {})):
        answer = client.get(path, params={**AT, **extra})
        assert answer.status_code == 200, path
        assert answer.json()["clock"] == to_iso(T0), path


def test_a_series_needs_a_known_target_and_metric(client):
    params = {**AT, "camera": "kilauea-kp", "target": "lava", "metric": "top_altitude"}
    assert client.get("/api/series", params=params).status_code == 422


def test_the_replay_endpoint_needs_a_replay(client):
    assert client.get("/api/replay").status_code == 404


def test_a_run_after_the_clock_cannot_be_traced(client, replayed):
    later = add_agent_run(replayed, "2026-10-17T16:00:00Z")
    assert client.get("/api/agent/trace", params={**AT, "run_id": later}).status_code == 404


def test_an_image_width_outside_the_allowed_range_is_refused(client):
    assert client.get("/api/frames/1/image", params={**AT, "width": 4000}).status_code == 422


def test_media_serves_bulletin_images_and_nothing_else(client, tmp_path):
    folder = tmp_path / "replay" / "ep55" / "bulletins" / "run2"
    folder.mkdir(parents=True)
    (folder / "frame29_plume.jpg").write_bytes(frame_jpeg(1))
    (folder / "bulletin.html").write_text("<p>x</p>", encoding="utf-8")
    (tmp_path / "frames").mkdir(exist_ok=True)
    (tmp_path / "frames" / "raw.jpg").write_bytes(frame_jpeg(2))

    served = client.get("/media/replay/ep55/bulletins/run2/frame29_plume.jpg")

    assert served.status_code == 200 and served.headers["content-type"] == "image/jpeg"
    for path in ("frames/raw.jpg", "replay/ep55/bulletins/run2/bulletin.html", "replay/ep55/vigil.sqlite",
                 "replay/ep55/bulletins/run2/missing.jpg"):
        assert client.get(f"/media/{path}").status_code == 404, path


def test_a_media_path_cannot_leave_the_data_dir(tmp_path):
    data = tmp_path / "data"
    (data / "bulletins").mkdir(parents=True)
    (tmp_path / "bulletins").mkdir()
    (tmp_path / "bulletins" / "outside.jpg").write_bytes(frame_jpeg(3))

    assert media_file(data, "../bulletins/outside.jpg") is None
    assert media_file(data, "bulletins/../../bulletins/outside.jpg") is None


def test_the_image_route_sends_a_scaled_jpeg_with_its_masks(client, replayed, tmp_path):
    shown = add_frame(replayed, FrameStore(replayed, tmp_path), "kilauea-kp", -5)
    add_track(replayed, add_run(replayed, "kilauea-kp", "plume", [shown]), [shown])

    answer = client.get(f"/api/frames/{shown}/image", params={**AT, "width": 320})

    assert answer.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(answer.content)).size == (320, 180)
