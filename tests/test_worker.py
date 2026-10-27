from datetime import timedelta

from conftest import NOW
from vigia.config import Camera
from vigia.ingest.store import IngestResult
from vigia.ingest.worker import SourceRouter, Worker


def cam(camera_id, enabled=True, poll_minutes=5):
    return Camera(
        id=camera_id, name=camera_id, volcano="kilauea", url=f"https://example.org/{camera_id}.jpg",
        license="Public Domain", attribution="USGS", enabled=enabled, poll_minutes=poll_minutes,
    )


class RecordingIngestor:
    def __init__(self, failing=()):
        self.calls = []
        self.failing = set(failing)

    def ingest(self, camera):
        self.calls.append(camera.id)
        if camera.id in self.failing:
            raise RuntimeError("boom")
        return IngestResult(camera.id, "new")


def test_only_enabled_cameras_are_polled():
    ingestor = RecordingIngestor()
    worker = Worker(ingestor, [cam("a"), cam("sgc", enabled=False)])

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
