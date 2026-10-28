import io
import json
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np
import pytest
from PIL import Image, ImageDraw

from test_meta_client import SPARK_USAGE, FakeApi, make_client, response_body
from vigia.config import Camera, Sources, Volcano
from vigia.gate import GATE_SCHEMA, QualityGate, parse_ptz, read_answer
from vigia.ingest.store import FrameStore
from vigia.quality import Thresholds

DAY = datetime(2026, 10, 17, 22, 0, 5, tzinfo=timezone.utc)    # 12:00 HST, sun at +61 degrees
NIGHT = datetime(2026, 10, 17, 13, 0, 5, tzinfo=timezone.utc)  # 03:00 HST, sun at -47 degrees
SOURCES = Sources(
    volcanoes={"kilauea": Volcano(name="Kīlauea", country="United States", official_agency="USGS HVO",
                                  official_url="https://www.usgs.gov/volcanoes/kilauea", lat=19.405, lon=-155.29)},
    cameras=[
        Camera(id="kilauea-v1", name="V1cam", volcano="kilauea", url="https://example.org/V1.jpg",
               license="Public Domain", attribution="U.S. Geological Survey"),
        Camera(id="kilauea-f1", name="F1cam", volcano="kilauea", url="https://example.org/F1.jpg",
               license="Public Domain", attribution="U.S. Geological Survey", kind="thermal"),
    ],
)
ANSWER = {
    "usable": True, "view": "clear", "usable_reason": "The vent and the plume are in clear view.",
    "printed_timestamp_text": "2026-10-17 12:00:01 HST", "printed_timestamp_iso": "2026-10-17T12:00:01-10:00",
    "printed_camera_label": "USGS", "printed_ptz_text": "P: 29, T: +0.00, Z: 29 1.0",
    "visible_features": ["crater", "vent", "steam"], "activity": "steaming",
    "description_en": "A steam plume rises from the vent.",
    "description_es": "Un penacho de vapor sale del respiradero.",
}
HAZY = Thresholds(clear_edges=1.01)  # every daytime frame with detail counts as hazy


def encode(image, fmt="JPEG"):
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def sharp(seed=0):
    """A frame full of detail, like a clear view."""
    return Image.fromarray(np.random.default_rng(seed).integers(0, 256, (240, 320, 3), dtype=np.uint8))


def flat(level):
    return Image.new("RGB", (320, 240), (level, level, level))


def glowing():
    image = Image.new("RGB", (320, 240), (0, 0, 0))
    ImageDraw.Draw(image).rectangle((120, 80, 199, 159), fill=(255, 120, 20))
    return image


@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def add(store, image, captured_at, camera_id="kilauea-v1", fmt="JPEG"):
    return store.add(camera_id, encode(image, fmt), captured_at=captured_at, timestamp_source="ashcam",
                     fetched_at=captured_at)


def spark_api(answer=ANSWER):
    return FakeApi(lambda r: httpx.Response(200, json=response_body("muse-spark-1.3", json.dumps(answer), SPARK_USAGE)))


def gate(conn, tmp_path, api=None, **kwargs):
    client = make_client(api, conn) if api is not None else None
    return QualityGate(conn, tmp_path, SOURCES, client, **kwargs)


def stored(conn, frame_id):
    return conn.execute("SELECT * FROM frame_quality WHERE frame_id = ?", (frame_id,)).fetchone()


def test_a_clear_frame_is_usable_without_asking_muse_spark(conn, store, tmp_path):
    api = spark_api()
    frame_id = add(store, sharp(), DAY)

    verdict = gate(conn, tmp_path, api).assess(frame_id)

    assert (verdict.usable, verdict.decided_by, verdict.reasons) == (True, "local", ())
    assert api.requests == []
    row = stored(conn, frame_id)
    assert (row["usable"], row["local_decision"], row["spark_view"]) == (1, "pass", None)
    assert row["sun_elevation_deg"] == pytest.approx(61.04, abs=0.01)


def test_fog_and_dark_night_frames_are_rejected_without_asking_muse_spark(conn, store, tmp_path):
    api = spark_api()
    fog = add(store, flat(150), DAY)
    night = add(store, flat(6), NIGHT)
    checker = gate(conn, tmp_path, api)

    assert checker.assess(fog).reasons == ("low_visibility",)
    assert checker.assess(night).reasons == ("night",)
    assert api.requests == []
    assert json.loads(stored(conn, night)["reasons"]) == ["night"]


def test_a_night_frame_with_glowing_lava_is_usable(conn, store, tmp_path):
    frame_id = add(store, glowing(), NIGHT)

    verdict = gate(conn, tmp_path).assess(frame_id)

    assert verdict.usable
    assert verdict.stats.glow_fraction > 0.05


def test_muse_spark_decides_a_hazy_frame_and_reads_its_timestamp_and_ptz(conn, store, tmp_path):
    api = spark_api()
    frame_id = add(store, sharp(), DAY)

    verdict = gate(conn, tmp_path, api, thresholds=HAZY).assess(frame_id)

    assert (verdict.local.decision, verdict.usable, verdict.decided_by) == ("uncertain", True, "spark")
    assert api.json_body()["text"]["format"]["schema"] == GATE_SCHEMA
    row = stored(conn, frame_id)
    assert row["printed_time"] == "2026-10-17T22:00:01Z"
    assert json.loads(row["printed_ptz"]) == {"pan": 29.0, "tilt": 0.0, "zoom_raw": 29.0, "zoom": 1.0}
    assert json.loads(row["spark_answer"]) == ANSWER
    [call] = conn.execute("SELECT purpose FROM api_calls").fetchall()
    assert call["purpose"] == "gate:assess"


def test_muse_spark_can_reject_a_hazy_frame(conn, store, tmp_path):
    frame_id = add(store, sharp(), DAY)
    answer = ANSWER | {"usable": False, "view": "obscured_by_cloud_or_fog"}

    verdict = gate(conn, tmp_path, spark_api(answer), thresholds=HAZY).assess(frame_id)

    assert (verdict.usable, verdict.decided_by) == (False, "spark")
    assert stored(conn, frame_id)["spark_view"] == "obscured_by_cloud_or_fog"


def test_a_hazy_frame_muse_spark_did_not_see_is_not_used(conn, store, tmp_path):
    frame_id = add(store, sharp(), DAY)

    verdict = gate(conn, tmp_path, thresholds=HAZY).assess(frame_id, spark="never")

    assert (verdict.local.decision, verdict.usable, verdict.decided_by) == ("uncertain", False, "local")


def test_spark_all_also_checks_frames_that_passed_but_never_rejected_ones(conn, store, tmp_path):
    api = spark_api()
    clear = add(store, sharp(), DAY)
    fog = add(store, flat(150), DAY + timedelta(minutes=2))
    checker = gate(conn, tmp_path, api)

    checker.assess(clear, spark="all")
    checker.assess(fog, spark="all")

    assert len(api.requests) == 1
    assert stored(conn, clear)["decided_by"] == "spark"


def test_a_printed_time_far_from_the_capture_time_makes_the_frame_unusable(conn, store, tmp_path):
    frame_id = add(store, sharp(), DAY)
    answer = ANSWER | {"printed_timestamp_iso": "2026-10-17T10:00:01-10:00"}

    verdict = gate(conn, tmp_path, spark_api(answer), thresholds=HAZY).assess(frame_id)

    assert (verdict.usable, verdict.reasons) == (False, ("low_visibility", "timestamp_mismatch"))


def test_a_frame_needing_muse_spark_without_a_client_is_an_error(conn, store, tmp_path):
    frame_id = add(store, sharp(), DAY)

    with pytest.raises(RuntimeError, match="spark='never'"):
        gate(conn, tmp_path, thresholds=HAZY).assess(frame_id)


def test_the_same_scene_under_a_new_timestamp_is_frozen(conn, store, tmp_path):
    first, second = sharp(), sharp()
    ImageDraw.Draw(second).rectangle((0, 0, 100, 8), fill=(255, 255, 255))  # only the printed time changed
    add(store, first, DAY, fmt="PNG")
    frozen = add(store, second, DAY + timedelta(minutes=2), fmt="PNG")

    verdict = gate(conn, tmp_path).assess(frozen)

    assert (verdict.usable, verdict.reasons, verdict.change) == (False, ("frozen",), 0.0)


def test_a_live_frame_older_than_30_minutes_is_stale(conn, store, tmp_path):
    frame_id = add(store, sharp(), DAY)

    verdict = gate(conn, tmp_path).assess(frame_id, now=DAY + timedelta(minutes=45))

    assert verdict.reasons == ("stale",)


def test_thermal_frames_are_not_judged_by_darkness(conn, store, tmp_path):
    frame_id = add(store, flat(6), NIGHT, camera_id="kilauea-f1")

    assert gate(conn, tmp_path).assess(frame_id).usable


def test_assess_range_skips_frames_already_assessed_unless_redo(conn, store, tmp_path):
    api = spark_api()
    ids = [add(store, sharp(seed), DAY + timedelta(minutes=2 * seed)) for seed in range(3)]
    checker = gate(conn, tmp_path, api, thresholds=HAZY)
    checker.assess(ids[0])

    report = checker.assess_range("kilauea-v1", DAY, DAY + timedelta(minutes=10))

    assert ([v.frame_id for v in report.verdicts], report.skipped) == (ids[1:], 1)
    assert len(api.requests) == 3
    assert len(checker.assess_range("kilauea-v1", DAY, DAY + timedelta(minutes=10), redo=True).verdicts) == 3


def test_assess_range_reports_a_failed_muse_spark_call_and_goes_on(conn, store, tmp_path):
    error = {"error": {"message": "overloaded", "type": "server_error", "param": None, "code": None}}
    api = FakeApi(lambda r: httpx.Response(503, json=error))
    ids = [add(store, sharp(seed), DAY + timedelta(minutes=2 * seed)) for seed in range(2)]

    report = gate(conn, tmp_path, api, thresholds=HAZY).assess_range("kilauea-v1", DAY, DAY + timedelta(minutes=5))

    assert (len(report.errors), report.verdicts) == (2, [])
    assert stored(conn, ids[0]) is None


def test_report_summary_counts_decisions(conn, store, tmp_path):
    add(store, sharp(), DAY)
    add(store, flat(150), DAY + timedelta(minutes=2))

    report = gate(conn, tmp_path).assess_range("kilauea-v1", DAY, DAY + timedelta(minutes=5))

    assert report.summary() == ("2 assessed, 1 usable, 1 rejected (low_visibility 1), 0 by Muse Spark, "
                                "0 already assessed, 0 failed")


@pytest.mark.parametrize("text, expected", [
    ("P: 29, T: +0.00, Z: 29 1.0", {"pan": 29.0, "tilt": 0.0, "zoom_raw": 29.0, "zoom": 1.0}),
    ("P: +178.54, T: -0.06, Z: 959 3.9", {"pan": 178.54, "tilt": -0.06, "zoom_raw": 959.0, "zoom": 3.9}),
    ("P: 9594, T: +0.00, Z: 9594 9.6", {"pan": 9594.0, "tilt": 0.0, "zoom_raw": 9594.0, "zoom": 9.6}),
])
def test_parse_ptz_reads_the_printed_readouts_of_usgs_ptz_cameras(text, expected):
    assert parse_ptz(text) == expected


@pytest.mark.parametrize("text", ["", "USGS", "P: 29"])
def test_parse_ptz_without_a_full_readout_is_none(text):
    assert parse_ptz(text) is None


def test_read_answer_converts_the_printed_time_to_utc():
    assert read_answer(ANSWER).printed_time == datetime(2026, 10, 17, 22, 0, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("iso", ["", "2026-10-17T12:00:01", "17/10/2026 12:00"])
def test_read_answer_without_a_zoned_printed_time_has_none(iso):
    assert read_answer(ANSWER | {"printed_timestamp_iso": iso}).printed_time is None
