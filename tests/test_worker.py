from datetime import timedelta

import httpx
import pytest

from conftest import NOW, make_jpeg
from test_ashcam import FakeAshcam, kp_camera
from vigil.config import Camera
from vigil.ingest.store import FrameStore, IngestResult
from vigil.ingest.worker import Fallback, SourceRouter, Worker, build_router, main
from vigil.timeutil import utcnow


def cam(camera_id, enabled=True, poll_minutes=5):
    return Camera(
        id=camera_id, name=camera_id, volcano="kilauea", url=f"https://example.org/{camera_id}.jpg",
        license="Public Domain", attribution="USGS", enabled=enabled, poll_minutes=poll_minutes,
    )


class RecordingIngestor:
    def __init__(self, failing=(), status="new"):
        self.calls = []
        self.failing = set(failing)
        self.status = status

    def ingest(self, camera):
        self.calls.append(camera.id)
        if camera.id in self.failing:
            raise RuntimeError("boom")
        return IngestResult(camera.id, self.status, error="HTTP 503" if self.status == "error" else None)


def test_only_enabled_cameras_are_polled():
    ingestor = RecordingIngestor()
    worker = Worker(ingestor, [cam("a"), cam("off", enabled=False)])

    worker.run_once(NOW)

    assert ingestor.calls == ["a"]


def test_camera_is_not_polled_again_before_its_interval():
    ingestor = RecordingIngestor()
    worker = Worker(ingestor, [cam("a", poll_minutes=5)])

    worker.run_once(NOW)
    worker.run_once(NOW + timedelta(minutes=4))

    assert ingestor.calls == ["a"]


def test_camera_is_polled_again_once_its_interval_elapses():
    ingestor = RecordingIngestor()
    worker = Worker(ingestor, [cam("a", poll_minutes=5), cam("b", poll_minutes=10)])

    worker.run_once(NOW)
    worker.run_once(NOW + timedelta(minutes=5))

    assert ingestor.calls == ["a", "b", "a"]


def test_unexpected_exception_in_one_camera_does_not_stop_the_others():
    ingestor = RecordingIngestor(failing={"a"})
    worker = Worker(ingestor, [cam("a"), cam("b")])

    results = worker.run_once(NOW)

    assert ingestor.calls == ["a", "b"]
    assert [(r.camera_id, r.status) for r in results] == [("a", "error"), ("b", "new")]


def test_seconds_until_next_due_reflects_the_soonest_camera():
    worker = Worker(RecordingIngestor(), [cam("a", poll_minutes=5), cam("b", poll_minutes=2)])

    worker.run_once(NOW)

    assert worker.seconds_until_next_due(NOW + timedelta(seconds=30)) == 90


def test_router_sends_each_camera_to_the_ingestor_of_its_live_source():
    by_url, by_ashcam = RecordingIngestor(), RecordingIngestor()
    router = SourceRouter({"url": by_url, "ashcam": by_ashcam})

    router.ingest(cam("a"))
    router.ingest(cam("b").model_copy(update={"live_source": "ashcam"}))

    assert (by_url.calls, by_ashcam.calls) == (["a"], ["b"])


def test_fallback_keeps_the_primary_result_when_it_works():
    primary, backup = RecordingIngestor(), RecordingIngestor()

    result = Fallback(primary, backup).ingest(cam("kp"))

    assert result.status == "new"
    assert (primary.calls, backup.calls) == (["kp"], [])


def test_fallback_polls_the_backup_when_the_primary_reports_an_error():
    primary, backup = RecordingIngestor(status="error"), RecordingIngestor()

    result = Fallback(primary, backup).ingest(cam("kp"))

    assert result.status == "new"
    assert (primary.calls, backup.calls) == (["kp"], ["kp"])


def test_fallback_polls_the_backup_when_the_primary_raises():
    primary, backup = RecordingIngestor(failing={"kp"}), RecordingIngestor()

    result = Fallback(primary, backup).ingest(cam("kp"))

    assert result.status == "new"
    assert backup.calls == ["kp"]


def test_cameras_on_ashcam_are_fed_from_their_image_url_while_the_archive_is_down(conn, server, tmp_path):
    archive = FakeAshcam()
    archive.list_status = 503
    camera = kp_camera().model_copy(update={"live_source": "ashcam"})
    server.add(camera.url, body=make_jpeg(), headers={"Last-Modified": "Tue, 27 Oct 2026 18:00:05 GMT"})
    http = httpx.Client(transport=httpx.MockTransport(
        lambda request: archive(request) if request.url.host == "volcview.wr.usgs.gov" else server.handle(request)))

    result = build_router(FrameStore(conn, tmp_path), http).ingest(camera)

    assert result.status == "new"
    [frame] = conn.execute("SELECT timestamp_source FROM frames").fetchall()
    assert frame["timestamp_source"] == "http_last_modified"


def test_the_router_reaches_back_as_far_as_its_lookback_for_ashcam_cameras(conn, tmp_path):
    archive = FakeAshcam()
    camera = kp_camera().model_copy(update={"live_source": "ashcam"})
    router = build_router(FrameStore(conn, tmp_path), httpx.Client(transport=httpx.MockTransport(archive)),
                          lookback=timedelta(hours=24))

    before = utcnow()
    router.ingest(camera)
    after = utcnow()

    start = int(archive.list_requests()[0].url.params["startTimestamp"])
    assert int((before - timedelta(hours=24)).timestamp()) <= start <= int((after - timedelta(hours=24)).timestamp())


def test_the_router_reaches_back_one_hour_by_default(conn, tmp_path):
    archive = FakeAshcam()
    camera = kp_camera().model_copy(update={"live_source": "ashcam"})
    router = build_router(FrameStore(conn, tmp_path), httpx.Client(transport=httpx.MockTransport(archive)))

    before = utcnow()
    router.ingest(camera)
    after = utcnow()

    start = int(archive.list_requests()[0].url.params["startTimestamp"])
    assert int((before - timedelta(hours=1)).timestamp()) <= start <= int((after - timedelta(hours=1)).timestamp())


CLI_SOURCES = """
volcanoes:
  kilauea:
    name: Kīlauea
    country: United States
    official_agency: USGS Hawaiian Volcano Observatory
    official_url: https://www.usgs.gov/volcanoes/kilauea
cameras:
  - id: kilauea-kp
    name: KPcam
    volcano: kilauea
    url: https://example.org/KPcam/images/M.jpg
    license: Public Domain
    attribution: U.S. Geological Survey
    ashcam_code: kilauea-kp-cam
    live_source: ashcam
    enabled: true
"""


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(CLI_SOURCES, encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigil.sqlite"))


def test_cli_passes_its_lookback_to_the_router(cli_env, monkeypatch):
    seen = {}

    def fake_router(store, http, lookback):
        seen["lookback"] = lookback
        return RecordingIngestor()

    monkeypatch.setattr("vigil.ingest.worker.build_router", fake_router)

    main(["--once", "--lookback-hours", "24"])

    assert seen["lookback"] == timedelta(hours=24)


def test_cli_refuses_a_lookback_that_is_not_positive(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--once", "--lookback-hours", "0"])

    assert "--lookback-hours" in capsys.readouterr().err
