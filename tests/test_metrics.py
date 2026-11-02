import hashlib
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from conftest import make_jpeg, make_textured_jpeg
from vigil import db, masks
from vigil.calibration import (Calibration, CameraCalibration, Framing, FramingReference, Geometry, HorizonPixel, Preset,
                               Site, VentPixel)
from vigil.geometry import View, direction, horizon_dip, local_en, on_vent_plane, sight
from vigil.ingest.store import FrameStore
from vigil.metrics import main, measure_mask, measure_window
from vigil.timeutil import to_iso

T0 = datetime(2026, 10, 17, 15, 0, 5, tzinfo=timezone.utc)


# --- one detection, on a camera 1 km south of the vent and 100 m above it


def geometry(samples=400):
    """A level camera at 1200 m looking north at a vent 1000 m away and 100 m below; f = 1000 px."""
    n = samples
    view = View(np.zeros(n), np.zeros(n), np.zeros(n), np.full(n, 1000.0), 960.0, 540.0)
    vent = np.repeat(sight(0.0, 1000.0, -100.0)[None], n, axis=0)
    return Geometry("test-cam", "test", view, np.full(n, 1200.0), vent, np.full(n, 1100.0), np.full(n, 0.13),
                    np.zeros(n))


def block(rows, cols):
    return np.ones((rows, cols), dtype=bool)


def by_metric(results):
    return {m.metric: m for m in results}


def test_the_top_of_a_fountain_300_m_above_the_vent_is_measured_with_sigma():
    # 300 m above the vent is 200 m above the camera: row 540 - 1000 * 0.2 = 340
    results = by_metric(measure_mask(geometry(), block(60, 20), left=950, top=340, target="fountain",
                                     rng=np.random.default_rng(0)))

    assert results["top_height"].value == pytest.approx(300.07, abs=0.01)
    assert results["top_altitude"].value == pytest.approx(1400.07, abs=0.01)
    assert results["top_height"].unit == "m"
    assert 3 < results["top_height"].sigma < 10   # 3 px of mask edge (3 m) and 5 degrees of lean (5 m)


def test_a_plume_leans_more_than_a_fountain():
    def sigma(target):
        found = by_metric(measure_mask(geometry(), block(60, 20), 950, 340, target, np.random.default_rng(0)))
        return found["top_height"].sigma

    assert sigma("plume") > 1.5 * sigma("fountain")


def test_a_mask_cut_off_by_the_top_of_the_frame_has_no_top():
    results = by_metric(measure_mask(geometry(), block(60, 20), 950, 1, "plume", np.random.default_rng(0)))

    assert "top_height" not in results and "top_altitude" not in results
    assert "area" in results


def test_area_counts_pixels_on_the_vent_plane():
    results = by_metric(measure_mask(geometry(), block(10, 20), 950, 400, "fountain", np.random.default_rng(0)))

    # a level camera looks square at the plane 1000 m away: 200 pixels of (1000 m / 1000 px) squared
    assert results["area"].value == pytest.approx(200, rel=1e-3)
    assert results["area"].unit == "m2"


def test_the_tops_and_the_rng_do_not_depend_on_the_area():
    # recorded before the area was measured band by band: the top heights stay bit-identical
    rng = np.random.default_rng(7)

    results = by_metric(measure_mask(geometry(), block(60, 20), 950, 340, "plume", rng))

    assert results["top_height"].value == 300.0682780580605
    assert results["top_height"].sigma == 10.94611354788139
    assert results["top_altitude"].value == 1400.0682780580605
    assert results["top_altitude"].sigma == 10.94611354788139
    assert rng.random() == 0.4481984561802025  # the area drew no random numbers


def test_area_of_a_square_high_above_the_vent_is_its_true_size():
    # a camera 1 km from the vent tilted 47 degrees up; a 300 m x 400 m rectangle on the vent plane, 1.0 to 1.4 km
    # above the vent, seen at 42 to 52 degrees, where a pixel covers about 4 m2 against 1 m2 at the vent's distance
    n = 100
    view = View(np.zeros(n), np.full(n, 47.0), np.zeros(n), np.full(n, 1000.0), 960.0, 540.0)
    vent = np.repeat(sight(0.0, 1000.0, -100.0)[None], n, axis=0)
    tilted = Geometry("test-cam", "test", view, np.full(n, 1200.0), vent, np.full(n, 1100.0), np.full(n, 0.13),
                      np.zeros(n))
    cols, rows = np.meshgrid(np.arange(600, 1320), np.arange(240, 840))
    pixels = np.stack([cols.ravel(), rows.ravel()], -1)[None].astype(float)
    one = View(view.yaw[:1], view.pitch[:1], view.roll[:1], view.focal[:1], view.cx, view.cy)
    _, across, rise = on_vent_plane(one, pixels, vent[:1])
    height = rise[0] + 100.0  # above the vent
    inside = (np.abs(across[0]) <= 150) & (height >= 1000) & (height <= 1400)
    mask = np.zeros(cols.shape, dtype=bool)
    mask[rows.ravel()[inside] - 240, cols.ravel()[inside] - 600] = True
    assert mask.sum() > 5000

    area = by_metric(measure_mask(tilted, mask, 600, 240, "plume", np.random.default_rng(0)))["area"].value

    assert area == pytest.approx(300 * 400, rel=0.02)
    old = mask.sum() * (np.linalg.norm(sight(0.0, 1000.0, -100.0)) / 1000) ** 2
    assert abs(old - 300 * 400) > 0.5 * 300 * 400  # one scale for the whole mask is far off


@pytest.mark.parametrize("left, offset_sign, bearing", [(1060, 1, 90.0), (821, -1, 270.0)],
                         ids=["right of the vent", "left of the vent"])
def test_a_plume_drifting_across_the_line_of_sight_gives_its_side(left, offset_sign, bearing):
    results = by_metric(measure_mask(geometry(), block(40, 40), left, 300, "plume", np.random.default_rng(0)))

    assert np.sign(results["drift_offset"].value) == offset_sign
    assert abs(results["drift_offset"].value) == pytest.approx(120, abs=1)  # centroid 120 px from the vent column
    assert (results["drift_bearing"].value, results["drift_bearing"].unit) == (bearing, "deg")


def test_fountains_get_no_drift():
    results = by_metric(measure_mask(geometry(), block(40, 40), 1060, 300, "fountain", np.random.default_rng(0)))

    assert "drift_offset" not in results


def test_an_empty_mask_gives_nothing():
    assert measure_mask(geometry(), np.zeros((5, 5), dtype=bool), 0, 0, "plume", np.random.default_rng(0)) == []


# --- detections in the database


KP = Site(lat=19.492709, lon=-155.385281, elev_m=2034, sigma_m=500, sigma_elev_m=15)
VENT = Site(lat=19.40496, lon=-155.29022, elev_m=1080, sigma_m=10, sigma_elev_m=5)
SIZE = (384, 216)
TRUE = View(np.array([146.6]), np.array([3.8]), np.array([0.7]), np.array([305.0]), 192, 108)


def kp_calibration(valid_from="2026-10-17T00:00:00Z", image_size=SIZE, references=True, framing=None):
    east, north = local_en(VENT.lat, VENT.lon, KP.lat, KP.lon)
    vent_px = TRUE.project(sight(east, north, VENT.elev_m - KP.elev_m)[None, None])[0, 0]
    horizon = [TRUE.project(direction(a, -horizon_dip(KP.elev_m))[None, None])[0, 0] for a in (125, 145, 165)]
    preset = Preset(name="fixed", valid_from=valid_from, image_size=image_size,
                    vent_pixel=VentPixel(pixel=tuple(vent_px)) if references else None,
                    horizon=[HorizonPixel(pixel=tuple(p)) for p in horizon] if references else [], framing=framing)
    camera = CameraCalibration(volcano="kilauea", position=KP, presets=[preset])
    return Calibration(vents={"kilauea": VENT}, cameras={"kilauea-kp": camera})


@pytest.fixture
def store(conn, tmp_path):
    return FrameStore(conn, tmp_path)


def add_detection(conn, store, minutes, target="fountain", box=(60, 140, 70, 150), size=SIZE, jpeg=None):
    captured_at = T0 + timedelta(minutes=minutes)
    frame_id = store.add("kilauea-kp", jpeg or make_jpeg(color=(10 + minutes, 80, 40), size=size),
                         captured_at=captured_at, timestamp_source="ashcam", fetched_at=captured_at)
    left, top, right, bottom = box
    mask = block(bottom - top, right - left)
    with conn:
        run_id = conn.execute(
            """INSERT INTO tracking_runs (camera_id, target, phrase, window_start, window_end, frame_ids,
                                          video_width, video_height, created_at)
               VALUES ('kilauea-kp', ?, ?, ?, ?, ?, ?, ?, '2026-10-28T00:00:00Z')""",
            (target, target, to_iso(captured_at), to_iso(captured_at), json.dumps([frame_id]), *size)).lastrowid
        track_id = conn.execute(
            "INSERT INTO tracks (run_id, object_id, first_seen, last_seen, detections) VALUES (?, '0', ?, ?, 1)",
            (run_id, to_iso(captured_at), to_iso(captured_at))).lastrowid
        return conn.execute(
            """INSERT INTO detections (track_id, frame_id, box_left, box_top, box_right, box_bottom, score,
                                       area_px, mask_rle) VALUES (?, ?, ?, ?, ?, ?, 0.8, ?, ?)""",
            (track_id, frame_id, *box, int(mask.sum()), json.dumps(masks.encode(mask)))).lastrowid


def stored(conn, detection_id):
    return {row["metric"]: row for row in conn.execute(
        "SELECT * FROM measurements WHERE detection_id = ?", (detection_id,))}


def window(conn, calibration, **kwargs):
    return measure_window(conn, calibration, "kilauea-kp", T0 - timedelta(minutes=1), T0 + timedelta(hours=1),
                          samples=50, **kwargs)


def test_measure_window_stores_each_metric_of_each_detection(conn, store):
    fountain = add_detection(conn, store, 0)
    plume = add_detection(conn, store, 5, target="plume", box=(80, 60, 120, 150))

    report = window(conn, kp_calibration())

    assert (report.measured, report.values, report.errors) == (2, 3 + 5, [])
    row = stored(conn, fountain)["top_height"]
    assert (row["camera_id"], row["captured_at"], row["target"], row["unit"], row["preset"]) == (
        "kilauea-kp", "2026-10-17T15:00:05Z", "fountain", "m", "fixed")
    assert row["sigma"] > 0
    assert set(stored(conn, plume)) == {"top_height", "top_altitude", "area", "drift_offset", "drift_bearing"}


def test_measured_detections_are_skipped_unless_redo(conn, store):
    detection = add_detection(conn, store, 0)
    calibration = kp_calibration()
    window(conn, calibration)

    again = window(conn, calibration)
    redone = window(conn, calibration, redo=True)

    assert (again.measured, again.skipped) == (0, 1)
    assert (redone.measured, redone.skipped) == (1, 0)
    assert conn.execute("SELECT COUNT(*) FROM measurements WHERE detection_id = ?", (detection,)).fetchone()[0] == 3


def test_detections_outside_every_preset_are_counted_not_measured(conn, store):
    add_detection(conn, store, 0)

    report = window(conn, kp_calibration(valid_from="2026-10-18T00:00:00Z"))

    assert (report.measured, report.uncalibrated) == (0, 1)


def test_a_frame_of_another_size_is_reported(conn, store):
    add_detection(conn, store, 0, size=(320, 240))

    report = window(conn, kp_calibration())

    assert report.measured == 0
    assert "320x240" in report.errors[0]


def test_a_preset_that_cannot_be_solved_is_reported_once(conn, store):
    add_detection(conn, store, 0)
    add_detection(conn, store, 5)

    report = window(conn, kp_calibration(references=False))

    assert report.measured == 0
    assert len(report.errors) == 1 and "preset fixed" in report.errors[0]


def test_the_same_seed_gives_the_same_sigmas(conn, store):
    detection = add_detection(conn, store, 0)
    window(conn, kp_calibration())
    first = stored(conn, detection)["top_height"]["sigma"]

    window(conn, kp_calibration(), redo=True)

    assert stored(conn, detection)["top_height"]["sigma"] == first


def kp_framing(tmp_path, seed=1):
    data = make_textured_jpeg(seed=seed, size=SIZE)
    (tmp_path / "refs").mkdir(exist_ok=True)
    (tmp_path / "refs/kp.jpg").write_bytes(data)
    return Framing(references=[FramingReference(path="refs/kp.jpg", sha256=hashlib.sha256(data).hexdigest())],
                   rows_from=0.5, skip_columns=(0.45, 0.55))


def test_a_preset_with_framing_measures_only_frames_that_keep_it(conn, store, tmp_path):
    kept = add_detection(conn, store, 0, jpeg=make_textured_jpeg(seed=1, size=SIZE))
    moved = add_detection(conn, store, 5, jpeg=make_textured_jpeg(seed=1, size=SIZE, shift=(0, 12)))

    report = window(conn, kp_calibration(framing=kp_framing(tmp_path)), data_dir=tmp_path)

    assert (report.measured, report.unconfirmed, report.errors) == (1, 1, [])
    assert stored(conn, kept) and not stored(conn, moved)
    assert "1 on frames whose framing is not confirmed" in report.summary()


def test_redo_drops_the_values_of_a_frame_whose_framing_is_no_longer_confirmed(conn, store, tmp_path):
    detection = add_detection(conn, store, 0, jpeg=make_textured_jpeg(seed=1, size=SIZE))
    assert window(conn, kp_calibration(framing=kp_framing(tmp_path)), data_dir=tmp_path).measured == 1
    assert stored(conn, detection)

    other = kp_framing(tmp_path, seed=2)  # a reference this frame does not match
    report = window(conn, kp_calibration(framing=other), data_dir=tmp_path, redo=True)

    assert (report.measured, report.unconfirmed, report.errors) == (0, 1, [])
    assert not stored(conn, detection)


def test_a_preset_with_framing_measures_nothing_without_the_data_dir(conn, store, tmp_path):
    add_detection(conn, store, 0, jpeg=make_textured_jpeg(seed=1, size=SIZE))

    report = window(conn, kp_calibration(framing=kp_framing(tmp_path)))

    assert (report.measured, report.unconfirmed) == (0, 1)
    assert report.errors == ["preset fixed: its framing cannot be checked without the frames' data dir"]


def test_a_missing_reference_frame_is_reported_once(conn, store, tmp_path):
    framing = kp_framing(tmp_path)
    (tmp_path / "refs/kp.jpg").unlink()
    add_detection(conn, store, 0, jpeg=make_textured_jpeg(seed=1, size=SIZE))
    add_detection(conn, store, 5, jpeg=make_textured_jpeg(seed=1, size=SIZE, shift=(0, 1)))

    report = window(conn, kp_calibration(framing=framing), data_dir=tmp_path)

    assert (report.measured, report.unconfirmed) == (0, 2)
    assert len(report.errors) == 1 and "refs/kp.jpg" in report.errors[0]


def test_the_summary_without_unconfirmed_detections_is_unchanged(conn, store):
    add_detection(conn, store, 0)

    assert window(conn, kp_calibration()).summary() == (
        "kilauea-kp: 1 detections measured (3 values), 0 measured before, 0 on frames without a calibration")


CALIBRATION_YAML = """
vents:
  kilauea: {lat: 19.40496, lon: -155.29022, elev_m: 1080}
cameras:
  kilauea-kp:
    volcano: kilauea
    position: {lat: 19.492709, lon: -155.385281, elev_m: 2034}
    presets:
      - {name: later, valid_from: "2026-10-20T00:00:00Z", image_size: [384, 216]}
"""


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    path = tmp_path / "calibration.yaml"
    path.write_text(CALIBRATION_YAML, encoding="utf-8")
    monkeypatch.setenv("CALIBRATION_PATH", str(path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigil.sqlite"))
    return tmp_path / "data"


def test_cli_reports_the_window(cli_env, capsys):
    conn = db.connect(cli_env / "vigil.sqlite")
    add_detection(conn, FrameStore(conn, cli_env), 0)  # Oct 17, before the only preset (Oct 20)
    conn.close()

    main(["--camera", "kilauea-kp", "--start", "2026-10-17T13:00Z", "--end", "2026-10-17T19:30Z"])

    assert "0 detections measured" in capsys.readouterr().out


def test_cli_refuses_a_camera_without_calibration(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--camera", "kilauea-v1", "--start", "2026-10-17T13:00Z", "--end", "2026-10-17T19:30Z"])

    assert "kilauea-v1" in capsys.readouterr().err
