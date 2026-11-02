import json
from datetime import timedelta
from typing import get_args

import httpx
import openai
import pytest
from PIL import Image
from pydantic import ValidationError

from conftest import NOW
from test_agent_loop import FAKE_TOOLS, SOURCES_YAML, Script
from test_alerts import make_alert
from test_agent_tools import (SIZE, T0, add_frame, add_measurement, add_run, add_track, context, detection_ids,
                              store)  # store is a fixture
from test_meta_client import make_client, turn_body
from vigil.agent.bulletin import (BULLETIN_FINISH, DISCLAIMER, DRAFT_FORMAT, DRAFT_SCHEMA, ActivityLevel, BulletinDraft,
                                  DraftEvidence, DraftMeasurement, Quote, Written, build_bulletin, draw_evidence,
                                  fountain_evidence, load_bulletin, main, quoted_numbers, run_wind, store_bulletin,
                                  supports, verify, write_bulletin)
from vigil.agent.loop import AgentRun
from vigil.alerts import store_alert
from vigil.config import CameraRule
from vigil.meta.client import MetaClient
from vigil.timeutil import to_iso


DRAFT = {  # the shape of Muse Spark's answer in the Phase 5 planning probe
    "activity_level": "degassing",
    "headline": "Lava fountain and a tall plume at Kīlauea",
    "body": "KPcam measured the plume top at 6,951 ± 429 m above sea level at 04:55.",
    "measurements": [{"camera_id": "kilauea-kp", "target": "plume", "metric": "top_altitude", "value": 6951,
                      "sigma": 429, "unit": "m", "frame_ids": [29]}],
    "evidence": [{"frame_id": 29, "target": "plume", "caption": "The plume at its peak."}],
}


def objects(schema):
    """Every object schema in `schema`, itself included."""
    if schema.get("type") == "object":
        yield schema
        for prop in schema["properties"].values():
            yield from objects(prop)
    elif schema.get("type") == "array":
        yield from objects(schema["items"])


def test_the_draft_format_is_strict_at_every_level():
    assert DRAFT_FORMAT == {"type": "json_schema", "name": "bulletin", "schema": DRAFT_SCHEMA, "strict": True}
    found = list(objects(DRAFT_SCHEMA))
    assert len(found) == 3
    for schema in found:
        assert schema["required"] == list(schema["properties"]) and schema["additionalProperties"] is False


def test_the_draft_format_has_the_draft_models_fields():
    assert list(DRAFT_SCHEMA["properties"]) == list(BulletinDraft.model_fields)
    items = {name: DRAFT_SCHEMA["properties"][name]["items"]["properties"] for name in ("measurements", "evidence")}
    assert list(items["measurements"]) == list(DraftMeasurement.model_fields)
    assert list(items["evidence"]) == list(DraftEvidence.model_fields)
    assert set(DRAFT_SCHEMA["properties"]) == {"activity_level", "headline", "body", "measurements", "evidence"}
    assert set(items["evidence"]) == {"frame_id", "target", "caption"}
    assert "Spanish" not in BULLETIN_FINISH and "English" in BULLETIN_FINISH
    assert DRAFT_SCHEMA["properties"]["activity_level"]["enum"] == list(get_args(ActivityLevel))
    assert items["measurements"]["metric"]["enum"] == ["top_height", "top_altitude", "area", "drift_offset",
                                                       "drift_bearing"]


def test_a_draft_parses_from_muse_sparks_json():
    draft = BulletinDraft.model_validate_json(json.dumps(DRAFT))

    assert draft.activity_level == "degassing"
    assert (draft.measurements[0].frame_ids, draft.measurements[0].value) == ([29], 6951)
    assert draft.evidence[0].caption == "The plume at its peak."


@pytest.mark.parametrize("change", [
    {"activity_level": "red_alert"},
    {"headline": ""},
    {"disclaimer": "Not official."},
    {"measurements": [{**DRAFT["measurements"][0], "frame_ids": []}]},
    {"measurements": [{**DRAFT["measurements"][0], "sigma": -1}]},
    {"measurements": [{**DRAFT["measurements"][0], "metric": "speed"}]},
])
def test_a_draft_outside_the_format_is_refused(change):
    with pytest.raises(ValidationError):
        BulletinDraft.model_validate({**DRAFT, **change})


def plume_frame(conn, store, minutes=-5, top_altitude=6950.9, sigma=429.4):
    """A KPcam frame `minutes` from the clock, with a tracked plume (box 60,60-120,150) and its measured top."""
    frame_id = add_frame(conn, store, "kilauea-kp", minutes)
    track_id = add_track(conn, add_run(conn, "kilauea-kp", "plume", [frame_id], phrase="steam"), [frame_id])
    add_measurement(conn, frame_id, "top_altitude", top_altitude, sigma, detection_id=detection_ids(conn, track_id)[0])
    return frame_id


def quoted(frame_id, **change):
    return DraftMeasurement.model_validate({**DRAFT["measurements"][0], "frame_ids": [frame_id], **change})


def shown(frame_id, **change):
    return DraftEvidence.model_validate({**DRAFT["evidence"][0], "frame_id": frame_id, **change})


def test_a_quoted_number_a_stored_measurement_supports_is_verified(conn, store, tmp_path):
    frame_id = plume_frame(conn, store)

    cited = verify(conn, quoted(frame_id), T0)

    assert cited.verified and cited.captured_at == "2026-10-17T14:55:00Z"


@pytest.mark.parametrize("change", [{"value": 7500}, {"sigma": 200}, {"metric": "top_height"},
                                    {"camera_id": "kilauea-k2"}, {"unit": "m2"}, {"frame_ids": [999]}])
def test_a_quoted_number_nothing_stored_supports_is_not_verified(conn, store, tmp_path, change):
    frame_id = plume_frame(conn, store)

    cited = verify(conn, quoted(frame_id, **change), T0)

    assert (cited.verified, cited.captured_at) == (False, None)


def test_a_measurement_captured_after_the_clock_supports_nothing(conn, store, tmp_path):
    frame_id = plume_frame(conn, store, minutes=5)

    assert not verify(conn, quoted(frame_id), T0).verified


def stored_measurement(conn, store, metric, value, sigma, unit, minutes=-5):
    frame_id = add_frame(conn, store, "kilauea-kp", minutes)
    track_id = add_track(conn, add_run(conn, "kilauea-kp", "plume", [frame_id], phrase="steam"), [frame_id])
    add_measurement(conn, frame_id, metric, value, sigma, detection_id=detection_ids(conn, track_id)[0], unit=unit)
    return frame_id


@pytest.mark.parametrize("metric, unit, stored, quoted_value, stored_sigma, quoted_sigma, verified", [
    ("top_altitude", "m", 6951, 6951.6, 429, 429, True),       # the tools round: under 1 m off is rounding
    ("top_altitude", "m", 300, 303, 20, 20, False),            # 1 % of 300 m is no longer allowed
    ("top_altitude", "m", 300, 300.6, 20, 20, True),
    ("top_altitude", "m", 6951, 6951, 429, 431, False),        # the value is right, the sigma is 2 m off
    ("drift_bearing", "deg", 5.05, 5.0, 2.0, 2.0, True),       # 0.05 deg: inside the 0.1 deg term
    ("drift_bearing", "deg", 5.2, 5.0, 2.0, 2.0, False),       # 0.2 deg: outside it
    ("drift_bearing", "deg", 5.0, 5.0, 2.0, 2.3, False),       # the sigma alone is off
    ("drift_bearing", "deg", 359.95, 0.0, 2.0, 2.0, True),     # bearings wrap around the circle
    ("drift_bearing", "deg", 0.04, 359.99, 2.0, 2.0, True),
    ("drift_bearing", "deg", 359.8, 0.0, 2.0, 2.0, False),
    ("area", "m2", 100000, 100000.8, 5000, 5000, True),
    ("area", "m2", 100000, 100800, 5000, 5000, False),         # 0.8 % is no longer allowed
    ("top_height", "m", 20.6, 20, 5, 5, True),
    ("area", "m2", 30.7, 30, 5, 5, True),
])
def test_a_quoted_number_is_verified_within_the_rounding_of_the_tools(
        conn, store, metric, unit, stored, quoted_value, stored_sigma, quoted_sigma, verified):
    frame_id = stored_measurement(conn, store, metric, stored, stored_sigma, unit)

    cited = verify(conn, quoted(frame_id, metric=metric, unit=unit, value=quoted_value, sigma=quoted_sigma), T0)

    assert cited.verified is verified


@pytest.mark.parametrize("text, expected", [
    ("at 6,951 ± 429 m above sea level", [(6951, 0.5, "length", "6,951 m"), (429, 0.5, "length", "429 m")]),
    ("an area of about 20.6 km²", [(20_600_000, 50_000, "area", "20.6 km²")]),
    ("rose 241 m", [(241, 0.5, "length", "241 m")]),
    ("a 1.2 km column", [(1200, 50, "length", "1.2 km")]),
    ("6.951 ± 0.429 km", [(6951, 0.5, "length", "6.951 km"), (429, 0.5, "length", "0.429 km")]),
    ("an area of 1,200 m2 and 3 square kilometres", [(1200, 50, "area", "1,200 m2"),
                                                      (3_000_000, 500_000, "area", "3 square kilometres")]),
    ("1.5 km2 and 80 m²", [(1_500_000, 50_000, "area", "1.5 km2"), (80, 5, "area", "80 m²")]),
    ("300 metres and 2 kilometers and 5 meters", [(300, 50, "length", "300 metres"),
                                                   (2000, 500, "length", "2 kilometers"),
                                                   (5, 0.5, "length", "5 meters")]),
    ("(6,951 m).", [(6951, 0.5, "length", "6,951 m")]),
    ("about 7,000 ± 400 m", [(7000, 500, "length", "7,000 m"), (400, 50, "length", "400 m")]),  # zeros are rounding
    ("6,950 m", [(6950, 5, "length", "6,950 m")]),
    ("7.0 km and 0.50 km", [(7000, 50, "length", "7.0 km"), (500, 5, "length", "0.50 km")]),  # a written decimal counts
    ("0 m", [(0, 0.5, "length", "0 m")]),
    ("a 1.6-km-high plume", [(1600, 50, "length", "1.6 km")]),  # Muse Spark's headlines hyphenate the unit
    ("a ~2,370-m plume and a 220-meter fountain", [(2370, 5, "length", "2,370 m"), (220, 5, "length", "220 meter")]),
    ("winds of 3.3 m/s", []),
    ("a 3.3-m/s wind and a 2-3 day lull", []),
    ("at 04:55 local time", []),
    ("a bearing of 224° and 12 minutes", []),
    ("a plume near 720 ft", []),
    ("about 6,951 above the sea", []),
    ("12 km/h or 12 kilometres per hour or 4 meters per second", []),
    ("5 mph, 5 mm", []),
])
def test_the_lengths_and_areas_written_in_a_text_are_found(text, expected):
    found = quoted_numbers(text)

    assert [(q.value, q.half_step, q.dimension, q.written) for q in found] == expected


@pytest.mark.parametrize("quote, stored, supported", [
    (Quote(6951, 0.5, "length", "6,951 m"), [("m", 6951.4)], True),
    (Quote(6951, 0.5, "length", "6,951 m"), [("m", 6953.0)], False),
    (Quote(6951, 0.5, "length", "6,951 m"), [("m", 6952.0)], True),     # 1 m of stored rounding on top of 0.5
    (Quote(6000, 0.5, "length", "6,000 m"), [("m", 6951.0), ("m", 429.0)], False),
    (Quote(7000, 500, "length", "7 km"), [("m", 6951.0)], True),        # 7 km covers 6.5 to 7.5 km
    (Quote(1200, 50, "length", "1.2 km"), [("m", 1300.0)], False),
    (Quote(429, 0.5, "length", "429 m"), [("m", 6951.0), ("m", 429.4)], True),
    (Quote(20_600_000, 50_000, "area", "20.6 km²"), [("m2", 20_640_000.0)], True),
    (Quote(20_600_000, 50_000, "area", "20.6 km²"), [("m", 20_600_000.0)], False),   # a length never supports an area
    (Quote(241, 0.5, "length", "241 m"), [("m2", 241.0), ("deg", 241.0)], False),
    (Quote(241, 0.5, "length", "241 m"), [], False),
])
def test_a_quoted_length_or_area_is_supported_by_a_checked_value_of_its_dimension_within_its_precision(
        quote, stored, supported):
    assert supports(quote, [(unit, value) for unit, value in stored]) is supported


def test_a_body_number_nothing_checked_supports_makes_the_bulletin_unverified_with_a_note(conn, store, tmp_path):
    frame_id = plume_frame(conn, store)
    draft = BulletinDraft.model_validate({
        **DRAFT, "body": "The plume top reached 6,951 ± 429 m at 04:55, with 6,000 m at the vent.",
        "measurements": [quoted(frame_id).model_dump()], "evidence": []})

    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 3, draft, tmp_path / "bulletins")

    assert bulletin.measurements[0].verified and not bulletin.text_checked and not bulletin.verified
    assert bulletin.notes == ["the text quotes 6,000 m, which no checked measurement supports"]


@pytest.mark.parametrize("body, text_checked", [
    ("The plume top reached about 7,000 ± 400 m.", True),    # 7,000 is good to 500 m, 400 to 50 m
    ("The plume top reached 6,950 ± 430 m.", True),
    ("The plume top reached 6,000 m.", False),               # 951 m off, and 6,000 is good to 500 m only
    ("The plume top reached 7.0 ± 0.4 km.", True),
    ("The plume top reached 7.5 ± 0.4 km.", False),          # 7.5 km is good to 50 m
    ("The plume top reached 7,000 ± 500 m.", False),         # 500 is good to 50 m: 429 is 71 off
])
def test_a_round_numbers_trailing_zeros_are_rounding_not_precision(conn, store, tmp_path, body, text_checked):
    frame_id = plume_frame(conn, store)
    draft = BulletinDraft.model_validate({**DRAFT, "body": body, "measurements": [quoted(frame_id).model_dump()],
                                          "evidence": []})

    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 3, draft, tmp_path / "bulletins")

    assert bulletin.text_checked is text_checked


def test_a_body_whose_numbers_are_all_supported_stays_verified(conn, store, tmp_path):
    frame_id = plume_frame(conn, store)
    draft = BulletinDraft.model_validate({**DRAFT, "headline": "A 6,951 m plume", "measurements": [
        quoted(frame_id).model_dump()], "evidence": []})

    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 3, draft, tmp_path / "bulletins")

    assert bulletin.text_checked and bulletin.verified and bulletin.notes == []


def test_a_body_number_with_no_cited_measurement_is_unverified(conn, tmp_path):
    draft = BulletinDraft.model_validate({**DRAFT, "measurements": [], "evidence": []})

    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 3, draft, tmp_path / "bulletins")

    assert not bulletin.verified
    assert bulletin.notes == ["the text quotes 6,951 m, which no checked measurement supports",
                              "the text quotes 429 m, which no checked measurement supports"]


def test_an_unverified_citation_does_not_support_the_body(conn, store, tmp_path):
    frame_id = plume_frame(conn, store)
    draft = BulletinDraft.model_validate({**DRAFT, "measurements": [quoted(frame_id, value=9000).model_dump()],
                                          "evidence": []})

    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 3, draft, tmp_path / "bulletins")

    assert not bulletin.text_checked
    assert bulletin.notes[0] == "1 of 1 quoted number(s) match no stored measurement"
    assert len(bulletin.notes) == 3  # that note, then 6,951 m and 429 m: an unverified citation supports neither


def test_a_bulletin_stored_before_the_text_was_checked_loads_as_checked(conn, tmp_path):
    draft = BulletinDraft.model_validate({**DRAFT, "body": "Quiet.", "measurements": [], "evidence": []})
    stored = store_bulletin(conn, build_bulletin(context(conn, tmp_path), "kilauea", 3, draft, tmp_path / "bulletins"))
    old = json.loads(conn.execute("SELECT body FROM bulletins").fetchone()["body"])
    del old["text_checked"]

    assert type(stored).model_validate(old).text_checked


def test_a_measurement_and_an_evidence_frame_captured_exactly_at_the_clock_are_used(conn, store, tmp_path):
    frame_id = plume_frame(conn, store, minutes=0)

    assert verify(conn, quoted(frame_id), T0).verified
    assert draw_evidence(conn, tmp_path, tmp_path / "bulletins" / "run1", shown(frame_id), T0) is not None


def test_the_wind_check_is_the_runs_last_get_wind_result_with_a_drift(conn):
    checked = {"volcano": "kilauea", "model_hour": "2026-10-17T15:00:00Z", "layer_mean": {"toward_deg": 151},
               "drift_check": {"angle_deg": 73.3, "consistent": True}, "levels": [{"pressure_hpa": 850}]}
    steps = [("get_wind", checked, 1), ("get_wind", {"volcano": "kilauea", "levels": []}, 1),
             ("get_wind", {"error": "bad"}, 0), ("echo", {"drift_check": "not wind"}, 1)]
    with conn:
        for seq, (name, result, ok) in enumerate(steps, 1):
            conn.execute("INSERT INTO agent_steps (run_id, seq, turn, kind, created_at, tool_name, result, ok) "
                         "VALUES (7, ?, 1, 'tool', '2026-10-28T00:00:00Z', ?, ?, ?)", (seq, name, json.dumps(result), ok))

    assert run_wind(conn, 7) == {key: value for key, value in checked.items() if key != "levels"}
    assert run_wind(conn, 8) is None


def test_run_wind_picks_the_last_successful_result(conn):
    def wind(angle):
        return {"volcano": "kilauea", "drift_check": {"angle_deg": angle, "consistent": True}}
    steps = [(wind(10), 1), (wind(20), 1), (wind(30), 0)]
    with conn:
        for seq, (result, ok) in enumerate(steps, 1):
            conn.execute("INSERT INTO agent_steps (run_id, seq, turn, kind, created_at, tool_name, result, ok) "
                         "VALUES (7, ?, 1, 'tool', '2026-10-28T00:00:00Z', 'get_wind', ?, ?)",
                         (seq, json.dumps(result), ok))

    assert run_wind(conn, 7) == wind(20)


def test_an_evidence_frame_is_drawn_with_its_targets_masks(conn, store, tmp_path):
    frame_id = plume_frame(conn, store)

    evidence = draw_evidence(conn, tmp_path, tmp_path / "bulletins" / "run1", shown(frame_id), T0)

    assert evidence.overlay == f"bulletins/run1/frame{frame_id}_plume.jpg"
    assert (evidence.camera_id, evidence.captured_at) == ("kilauea-kp", "2026-10-17T14:55:00Z")
    with Image.open(tmp_path / evidence.overlay) as drawn:
        rgb = drawn.convert("RGB")
    assert rgb.width == SIZE[0] and rgb.height > SIZE[1]  # the legend strip goes below the frame
    inside, outside = rgb.getpixel((90, 100)), rgb.getpixel((300, 100))
    assert inside[2] > outside[2] + 40  # the plume's colour is blue-cyan


def test_a_large_evidence_frame_is_drawn_1280_pixels_wide(conn, store, tmp_path):
    frame_id = add_frame(conn, store, "kilauea-kp", -5, size=(2560, 1440))
    add_track(conn, add_run(conn, "kilauea-kp", "plume", [frame_id]), [frame_id])

    evidence = draw_evidence(conn, tmp_path, tmp_path / "bulletins" / "run1", shown(frame_id), T0)

    with Image.open(tmp_path / evidence.overlay) as drawn:
        assert drawn.width == 1280


def test_build_bulletin_checks_the_draft_and_adds_the_official_source_and_disclaimer(conn, store, tmp_path):
    frame_id = plume_frame(conn, store)
    draft = BulletinDraft.model_validate({
        **DRAFT, "measurements": [quoted(frame_id).model_dump(), quoted(frame_id, value=9000).model_dump()],
        "evidence": [shown(frame_id).model_dump()]})

    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 3, draft, tmp_path / "bulletins",
                              wall_clock=lambda: NOW)

    assert (bulletin.run_id, bulletin.volcano, bulletin.clock, bulletin.created_at) == (
        3, "kilauea", "2026-10-17T15:00:00Z", to_iso(NOW))
    assert [m.verified for m in bulletin.measurements] == [True, False] and not bulletin.verified
    assert (bulletin.official_agency, bulletin.official_url) == ("USGS Hawaiian Volcano Observatory (HVO)",
                                                                 "https://www.usgs.gov/volcanoes/kilauea")
    assert bulletin.disclaimer == DISCLAIMER.format(name="Kilauea", agency="USGS Hawaiian Volcano Observatory (HVO)",
                                                    url="https://www.usgs.gov/volcanoes/kilauea")
    assert "does not replace official alerts" in bulletin.disclaimer
    assert bulletin.disclaimer.endswith("https://www.usgs.gov/volcanoes/kilauea")
    assert bulletin.evidence[0].overlay == f"bulletins/run3/frame{frame_id}_plume.jpg"
    assert bulletin.notes == ["1 of 2 quoted number(s) match no stored measurement"]
    assert bulletin.wind is None and bulletin.headline == DRAFT["headline"]


def test_evidence_after_the_clock_or_beyond_three_frames_is_left_out(conn, store, tmp_path):
    early, late = plume_frame(conn, store), add_frame(conn, store, "kilauea-kp", 5)
    draft = BulletinDraft.model_validate({**DRAFT, "body": "Quiet.", "measurements": [],
                                          "evidence": [shown(i).model_dump() for i in (late, early, early, early)]})

    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 3, draft, tmp_path / "bulletins")

    assert [e.frame_id for e in bulletin.evidence] == [early, early]
    assert bulletin.notes == [f"evidence frame {late} left out: no such frame captured by 2026-10-17T15:00:00Z",
                              "1 evidence frame(s) beyond 3 left out"]


def test_evidence_whose_image_cannot_be_read_is_left_out_with_its_own_note(conn, store, tmp_path):
    gone, kept = plume_frame(conn, store, minutes=-6), plume_frame(conn, store, minutes=-5)
    (tmp_path / conn.execute("SELECT path FROM frames WHERE id = ?", (gone,)).fetchone()["path"]).unlink()
    draft = BulletinDraft.model_validate({**DRAFT, "body": "Quiet.", "measurements": [],
                                          "evidence": [shown(gone).model_dump(), shown(kept).model_dump()]})

    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 3, draft, tmp_path / "bulletins")

    assert [e.frame_id for e in bulletin.evidence] == [kept]
    assert bulletin.notes == [f"evidence frame {gone} left out: its image could not be read"]


def test_an_evidence_folder_outside_the_data_dir_fails_without_writing_a_file(conn, store, tmp_path):
    frame_id = plume_frame(conn, store)
    outside = tmp_path.parent / f"{tmp_path.name}_outside"

    with pytest.raises(ValueError):
        draw_evidence(conn, tmp_path, outside, shown(frame_id), T0)

    assert not outside.exists()


def test_a_stored_bulletin_loads_back_with_its_id(conn, tmp_path):
    draft = BulletinDraft.model_validate({**DRAFT, "evidence": []})
    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 3, draft, tmp_path / "bulletins")

    stored = store_bulletin(conn, bulletin)

    assert stored.id == 1 and load_bulletin(conn, 1) == stored
    row = conn.execute("SELECT * FROM bulletins").fetchone()
    assert (row["run_id"], row["activity_level"], row["verified"], row["clock"]) == (
        3, "degassing", 0, "2026-10-17T15:00:00Z")
    assert conn.execute("SELECT headline FROM bulletins").fetchone()[0] == DRAFT["headline"]
    with pytest.raises(KeyError):
        load_bulletin(conn, 2)


QUIET = {**DRAFT, "activity_level": "no_view", "measurements": [], "evidence": []}


def write(conn, tmp_path, api, **options):
    return write_bulletin(make_client(api, conn), context(conn, tmp_path), "kilauea", tmp_path / "bulletins",
                          tools=FAKE_TOOLS, wall_clock=lambda: NOW, sleep=lambda seconds: None, **options)


def test_the_agent_writes_the_bulletin_in_its_format_and_it_is_stored_and_published(conn, store, tmp_path):
    frame_id = plume_frame(conn, store)
    draft = {**DRAFT, "measurements": [quoted(frame_id).model_dump()], "evidence": [shown(frame_id).model_dump()]}
    api = Script(turn_body([("echo", '{"n": 1}')], text="Measuring.", rid="resp_1"),
                 turn_body([], text=json.dumps(draft)))

    written = write(conn, tmp_path, api)

    assert written.problem is None and written.bulletin.id == 1 and written.bulletin.verified
    assert [request["text"] for request in api.requests] == [{"format": DRAFT_FORMAT}] * 2
    assert all(request["instructions"].endswith(BULLETIN_FINISH) for request in api.requests)
    assert load_bulletin(conn, 1) == written.bulletin
    folder = tmp_path / "bulletins" / f"run{written.run.run_id}"
    assert (folder / "bulletin.html").exists() and (folder / f"frame{frame_id}_plume.jpg").exists()


@pytest.mark.parametrize("answer", ["The plume is high.", json.dumps({**QUIET, "headline": ""}),
                                    json.dumps({**QUIET, "activity_level": "red_alert"})])
def test_a_final_answer_that_is_not_a_bulletin_stores_nothing(conn, tmp_path, answer):
    written = write(conn, tmp_path, Script(turn_body([], text=answer)))

    assert written.bulletin is None and written.problem.startswith("the final answer is not a bulletin")
    assert written.run.status == "done"
    assert conn.execute("SELECT COUNT(*) FROM bulletins").fetchone()[0] == 0


def test_a_failed_run_writes_no_bulletin(conn, tmp_path):
    failure = httpx.Response(500, json={"error": {"message": "boom", "type": "server_error", "param": None,
                                                  "code": None}})

    written = write(conn, tmp_path, Script(*[failure] * 3))  # the first try and two retries

    assert written.bulletin is None and written.problem.startswith("the agent run ended with error")


def test_a_run_over_its_budget_writes_no_bulletin(conn, tmp_path):
    written = write_bulletin(make_client(Script(), conn), context(conn, tmp_path), "kilauea", tmp_path / "bulletins",
                             tools=FAKE_TOOLS, budget_usd=0.001, wall_clock=lambda: NOW)

    assert written.bulletin is None and written.problem.startswith("the agent run ended with budget")


def test_a_run_out_of_turns_still_gives_its_bulletin(conn, tmp_path):
    api = Script(turn_body([("echo", '{"n": 1}')], text=json.dumps(QUIET)))  # it still calls a tool on its last turn

    written = write_bulletin(make_client(api, conn), context(conn, tmp_path), "kilauea", tmp_path / "bulletins",
                             tools=FAKE_TOOLS, max_turns=1, wall_clock=lambda: NOW)

    assert written.run.status == "max_turns" and written.bulletin is not None


def test_the_task_recalls_the_last_bulletin_before_the_clock_only(conn, tmp_path):
    draft = BulletinDraft.model_validate(QUIET)
    for volcano, clock, headline in (("kilauea", "2026-10-17T14:00:00Z", "Fountain rising"),
                                     ("mauna-loa", "2026-10-17T14:30:00Z", "Elsewhere"),
                                     ("kilauea", "2026-10-17T15:00:00Z", "At the clock"),
                                     ("kilauea", "2026-10-17T16:00:00Z", "From later")):
        bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 1, draft, tmp_path / "bulletins")
        store_bulletin(conn, bulletin.model_copy(update={"volcano": volcano, "clock": clock, "headline": headline,
                                                         "activity_level": "fountaining"}))
    api = Script(turn_body([], text=json.dumps(QUIET)))

    write(conn, tmp_path, api)

    task = api.requests[0]["input"][0]["content"]
    assert task.startswith("Check Kilauea now")
    assert task.endswith("\nYour previous bulletin, at 2026-10-17 14:00 UTC, reported fountaining: Fountain rising")


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(SOURCES_YAML, encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigil.sqlite"))
    return tmp_path


def fake_meta(monkeypatch, api):
    def from_env(ledger):  # the CLI's own ledger, so its database connection is the only one
        sdk = openai.OpenAI(base_url="https://api.meta.ai/v1", api_key="test-key", max_retries=0,
                            http_client=httpx.Client(transport=httpx.MockTransport(api)))
        return MetaClient(sdk, ledger)

    monkeypatch.setattr("vigil.agent.bulletin.MetaClient.from_env", from_env)


def test_cli_prints_the_trace_and_the_bulletin(cli_env, monkeypatch, capsys):
    fake_meta(monkeypatch, Script(turn_body([("list_cameras_status", "{}")], rid="resp_1"),
                                  turn_body([], text=json.dumps(QUIET))))

    main(["--volcano", "kilauea", "--at", "2026-10-17T05:00-10:00"])

    out = capsys.readouterr().out
    assert "at 2026-10-17T15:00:00Z (kilauea): done after 2 turns" in out
    assert out.count("# Lava fountain and a tall plume at Kīlauea") == 1 and "Fuente" not in out
    assert "Kilauea · 2026-10-17 05:00 (UTC-10) · Activity: No usable view" in out
    assert (cli_env / "data" / "bulletins" / "run1" / "bulletin.html").exists()


def test_cli_exits_with_an_error_when_no_bulletin_comes_back(cli_env, monkeypatch, capsys):
    fake_meta(monkeypatch, Script(turn_body([], text="No JSON here.")))

    with pytest.raises(SystemExit) as exit_info:
        main(["--volcano", "kilauea", "--at", "2026-10-17T05:00-10:00"])

    assert exit_info.value.code == 1
    assert "no bulletin: the final answer is not a bulletin" in capsys.readouterr().out


# --- the fountaining level needs a fountain that something stored confirms

M = timedelta(minutes=1)
RULES = {"kilauea-v1": CameraRule(fountain_area=0.06, ambiguous_area=0.03),
         "kilauea-k2": CameraRule(fountain_area=0.01, ambiguous_area=0.005)}
BIG, SMALL = (60, 60, 120, 150), (60, 60, 90, 90)  # 5,400 px (6.5 % of a 384 x 216 frame) and 900 px (1.1 %)
FOUNTAIN = {**DRAFT, "activity_level": "fountaining", "body": "A lava fountain plays at the vent.",
            "measurements": [], "evidence": []}
NOTHING = "nothing stored confirms a lava fountain in the last hour"


def put_alert(conn, kind, minutes, **fields):
    """An alert raised `minutes` from the clock."""
    return store_alert(conn, make_alert(kind, clock=to_iso(T0 + minutes * M), **fields))


def put_look(conn, store, camera_id, minutes, *, clock=None, episode=1):
    """An alert look at a frame captured `minutes` from the clock, made at `clock` minutes (default: then)."""
    frame_id = add_frame(conn, store, camera_id, minutes)
    made = T0 + (minutes if clock is None else clock) * M
    with conn:
        conn.execute("INSERT INTO alert_checks (frame_id, camera_id, captured_at, clock, glow, size, episode) "
                     "VALUES (?, ?, ?, ?, 0.1, 'large', ?)",
                     (frame_id, camera_id, to_iso(T0 + minutes * M), to_iso(made), episode))
    return frame_id


def put_fountain_track(conn, store, camera_id, minutes, box=BIG, target="fountain"):
    """A SAM track of `target` on a frame captured `minutes` from the clock, with a full-box mask."""
    frame_id = add_frame(conn, store, camera_id, minutes)
    add_track(conn, add_run(conn, camera_id, target, [frame_id], phrase="lava fountain"), [frame_id], box=box)
    return frame_id


def evidence_at(conn, now=T0, rules=RULES):
    return fountain_evidence(conn, "kilauea", rules, now)


def task_of(api):
    return api.requests[0]["input"][0]["content"]


def test_with_nothing_stored_no_fountain_is_confirmed(conn):
    assert evidence_at(conn) is None


def test_an_onset_as_the_latest_alert_confirms_a_fountain_however_old(conn):
    put_alert(conn, "onset", -300)

    assert "the alert watcher reported fountaining at 2026-10-17T10:00:00Z" in evidence_at(conn)


@pytest.mark.parametrize("alerts", [
    pytest.param([("onset", -300), ("end", -10)], id="ended"),
    pytest.param([("onset", 1)], id="onset-after-the-clock"),
    pytest.param([("end", -300)], id="only-an-end"),
])
def test_an_ended_or_later_onset_confirms_no_fountain(conn, alerts):
    for kind, minutes in alerts:
        put_alert(conn, kind, minutes)

    assert evidence_at(conn) is None


def test_an_onset_raised_exactly_at_the_clock_counts_and_another_volcanos_does_not(conn):
    put_alert(conn, "onset", 0, volcano="mauna-loa")
    assert evidence_at(conn) is None

    put_alert(conn, "onset", 0)
    assert evidence_at(conn) is not None


def test_an_end_raised_after_the_clock_does_not_turn_an_onset_off_yet(conn):
    put_alert(conn, "onset", -300)
    put_alert(conn, "end", 5)

    assert evidence_at(conn) is not None
    assert evidence_at(conn, now=T0 + 5 * M) is None


@pytest.mark.parametrize("captured, clock, episode, confirmed", [
    pytest.param(-10, -9, 1, True, id="recent-episode-size-look"),
    pytest.param(0, 0, 1, True, id="at-the-clock"),
    pytest.param(-59, -58, 1, True, id="just-inside-the-hour"),
    pytest.param(-60, -59, 1, False, id="exactly-an-hour-old"),
    pytest.param(-90, -89, 1, False, id="older-than-an-hour"),
    pytest.param(-10, -9, 0, False, id="not-episode-size"),
    pytest.param(-10, 5, 1, False, id="made-after-the-clock"),
    pytest.param(5, 5, 1, False, id="captured-after-the-clock"),
])
def test_an_episode_size_alert_look_in_the_last_hour_confirms_a_fountain(conn, store, captured, clock, episode,
                                                                         confirmed):
    put_look(conn, store, "kilauea-v1", captured, clock=clock, episode=episode)

    found = evidence_at(conn)

    assert (found is not None) is confirmed
    if confirmed:
        assert "kilauea-v1" in found and to_iso(T0 + captured * M) in found


@pytest.mark.parametrize("camera, minutes, box, target, confirmed", [
    pytest.param("kilauea-v1", -10, BIG, "fountain", True, id="large-tracked-fountain"),
    pytest.param("kilauea-v1", -10, SMALL, "fountain", False, id="too-small-for-the-camera"),
    pytest.param("kilauea-k2", -10, SMALL, "fountain", True, id="small-is-enough-for-k2"),
    pytest.param("kilauea-kp", -10, BIG, "fountain", False, id="camera-with-no-rule"),
    pytest.param("kilauea-v1", -10, BIG, "plume", False, id="not-a-fountain-track"),
    pytest.param("kilauea-v1", -59, BIG, "fountain", True, id="just-inside-the-hour"),
    pytest.param("kilauea-v1", -60, BIG, "fountain", False, id="exactly-an-hour-old"),
    pytest.param("kilauea-v1", 5, BIG, "fountain", False, id="frame-after-the-clock"),
])
def test_a_large_tracked_fountain_in_the_last_hour_confirms_a_fountain(conn, store, camera, minutes, box, target,
                                                                       confirmed):
    put_fountain_track(conn, store, camera, minutes, box, target)

    found = evidence_at(conn)

    assert (found is not None) is confirmed
    if confirmed:
        assert camera in found and to_iso(T0 + minutes * M) in found and "% of the frame" in found


def test_a_tracking_run_that_ended_after_the_clock_confirms_nothing(conn, store):
    put_fountain_track(conn, store, "kilauea-v1", -10)
    with conn:
        conn.execute("UPDATE tracking_runs SET window_end = ?", (to_iso(T0 + M),))

    assert evidence_at(conn) is None
    assert evidence_at(conn, now=T0 + M) is not None


def test_without_rules_only_the_alerts_confirm_a_fountain(conn, store):
    put_fountain_track(conn, store, "kilauea-v1", -10)
    assert evidence_at(conn, rules={}) is None

    put_look(conn, store, "kilauea-k2", -5)
    assert "kilauea-k2" in evidence_at(conn, rules={})


def test_the_alert_comes_first_in_the_evidence(conn, store):
    put_fountain_track(conn, store, "kilauea-v1", -10)
    put_look(conn, store, "kilauea-k2", -5)
    put_alert(conn, "onset", -3)

    assert "the alert watcher reported fountaining" in evidence_at(conn)


def test_a_database_without_the_alerts_tables_counts_as_no_alerts(conn, store):
    put_fountain_track(conn, store, "kilauea-v1", -10)
    with conn:
        conn.execute("DROP TABLE alerts")
        conn.execute("DROP TABLE alert_checks")

    assert "kilauea-v1" in evidence_at(conn)
    assert evidence_at(conn, rules={}) is None


def test_the_task_tells_the_agent_that_nothing_confirms_a_fountain(conn, tmp_path):
    api = Script(turn_body([], text=json.dumps(QUIET)))

    write(conn, tmp_path, api)

    assert NOTHING in task_of(api) and "incandescence" in task_of(api)


def test_the_task_tells_the_agent_what_confirms_the_fountain(conn, tmp_path):
    put_alert(conn, "onset", -3)
    api = Script(turn_body([], text=json.dumps(QUIET)))

    write(conn, tmp_path, api)

    assert "the alert watcher reported fountaining at 2026-10-17T14:57:00Z" in task_of(api)
    assert NOTHING not in task_of(api)


def test_the_task_puts_the_fountain_check_before_the_previous_bulletin(conn, tmp_path):
    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 1, BulletinDraft.model_validate(QUIET),
                              tmp_path / "bulletins")
    store_bulletin(conn, bulletin.model_copy(update={"clock": "2026-10-17T14:00:00Z"}))
    api = Script(turn_body([], text=json.dumps(QUIET)))

    write(conn, tmp_path, api)

    assert task_of(api).index(NOTHING) < task_of(api).index("Your previous bulletin")


def test_the_finish_asks_for_fountaining_only_when_the_task_says_a_fountain_is_confirmed():
    assert "only when the task says" in BULLETIN_FINISH and "confirmed" in BULLETIN_FINISH


def test_a_draft_that_says_fountaining_with_nothing_to_confirm_it_goes_back_once(conn, tmp_path):
    api = Script(turn_body([], text=json.dumps(FOUNTAIN), rid="resp_1"),
                 turn_body([], text=json.dumps({**FOUNTAIN, "activity_level": "incandescence"}), rid="resp_2"))

    written = write(conn, tmp_path, api)

    assert written.run.status == "done" and written.run.turns == 2
    assert (written.bulletin.activity_level, written.bulletin.level_checked) == ("incandescence", True)
    sent_back = api.requests[1]["input"][-1]
    assert sent_back["role"] == "user" and "fountaining" in sent_back["content"] and NOTHING in sent_back["content"]
    check = conn.execute("SELECT text FROM agent_steps WHERE kind = 'check'").fetchone()
    assert check["text"] == sent_back["content"]


def test_a_second_fountaining_draft_is_stored_as_incandescence_with_a_note(conn, tmp_path):
    api = Script(turn_body([], text=json.dumps(FOUNTAIN), rid="resp_1"),
                 turn_body([], text=json.dumps(FOUNTAIN), rid="resp_2"))

    written = write(conn, tmp_path, api)

    bulletin = written.bulletin
    assert len(api.requests) == 2  # one retry only
    assert (bulletin.activity_level, bulletin.level_checked, bulletin.verified) == ("incandescence", False, False)
    assert bulletin.notes == ["Muse Spark called this fountaining, but nothing stored by 2026-10-17T15:00:00Z "
                              "confirms a lava fountain: the level shows glowing lava"]
    assert load_bulletin(conn, bulletin.id) == bulletin
    row = conn.execute("SELECT activity_level, verified FROM bulletins").fetchone()
    assert (row["activity_level"], row["verified"]) == ("incandescence", 0)


def test_a_fountaining_draft_on_the_last_turn_is_not_sent_back_but_is_demoted(conn, tmp_path):
    api = Script(turn_body([], text=json.dumps(FOUNTAIN)))

    written = write(conn, tmp_path, api, max_turns=1)

    assert len(api.requests) == 1
    assert (written.bulletin.activity_level, written.bulletin.level_checked) == ("incandescence", False)


@pytest.mark.parametrize("level", ["no_view", "quiet", "degassing", "incandescence"])
def test_a_draft_below_fountaining_is_not_sent_back(conn, tmp_path, level):
    api = Script(turn_body([], text=json.dumps({**FOUNTAIN, "activity_level": level})))

    written = write(conn, tmp_path, api)

    assert len(api.requests) == 1
    bulletin = written.bulletin
    assert (bulletin.activity_level, bulletin.level_checked, bulletin.notes) == (level, True, [])


def test_a_fountaining_draft_with_a_confirming_alert_stands(conn, tmp_path):
    put_alert(conn, "onset", -3)
    api = Script(turn_body([], text=json.dumps(FOUNTAIN)))

    written = write(conn, tmp_path, api)

    assert len(api.requests) == 1
    assert (written.bulletin.activity_level, written.bulletin.level_checked, written.bulletin.notes) == (
        "fountaining", True, [])


def test_a_large_tracked_fountain_confirms_only_with_the_alert_rules(conn, store, tmp_path):
    put_fountain_track(conn, store, "kilauea-v1", -10)

    with_rules = write(conn, tmp_path, Script(turn_body([], text=json.dumps(FOUNTAIN))), alert_rules=RULES)
    without = write(conn, tmp_path, Script(turn_body([], text=json.dumps(FOUNTAIN)),
                                           turn_body([], text=json.dumps(FOUNTAIN))))

    assert with_rules.bulletin.activity_level == "fountaining"
    assert without.bulletin.activity_level == "incandescence"


def test_build_bulletin_leaves_a_confirmed_fountaining_alone_and_demotes_the_rest(conn, tmp_path):
    draft = BulletinDraft.model_validate(FOUNTAIN)
    ctx = context(conn, tmp_path)

    demoted = build_bulletin(ctx, "kilauea", 3, draft, tmp_path / "bulletins", alert_rules=RULES)
    put_alert(conn, "onset", 1)  # raised after the clock: not yet
    still = build_bulletin(ctx, "kilauea", 3, draft, tmp_path / "bulletins", alert_rules=RULES)
    put_alert(conn, "onset", -2)
    kept = build_bulletin(ctx, "kilauea", 3, draft, tmp_path / "bulletins", alert_rules=RULES)

    assert [b.activity_level for b in (demoted, still, kept)] == ["incandescence", "incandescence", "fountaining"]
    assert [b.level_checked for b in (demoted, still, kept)] == [False, False, True]
    assert kept.verified and kept.notes == [] and not demoted.verified
    assert demoted.headline == FOUNTAIN["headline"] and demoted.body == FOUNTAIN["body"]


def test_a_bulletin_stored_before_the_level_was_checked_loads_as_checked(conn, tmp_path):
    draft = BulletinDraft.model_validate({**DRAFT, "body": "Quiet.", "measurements": [], "evidence": []})
    stored = store_bulletin(conn, build_bulletin(context(conn, tmp_path), "kilauea", 3, draft, tmp_path / "bulletins"))
    old = json.loads(conn.execute("SELECT body FROM bulletins").fetchone()["body"])
    del old["level_checked"]

    assert type(stored).model_validate(old).level_checked


def test_cli_gives_the_bulletin_the_alert_cameras_rules(cli_env, monkeypatch):
    (cli_env / "alerts.yaml").write_text("cameras:\n  kilauea-k2: {fountain_area: 0.5, ambiguous_area: 0.1}\n",
                                         encoding="utf-8")
    monkeypatch.setenv("ALERTS_PATH", str(cli_env / "alerts.yaml"))
    fake_meta(monkeypatch, Script())
    given = {}

    def fake_write(client, ctx, volcano_id, out_dir, **options):
        given.update(options)
        return Written(AgentRun(1, "error", 0, 0.0, "", "stopped"), None, "stopped")

    monkeypatch.setattr("vigil.agent.bulletin.write_bulletin", fake_write)
    monkeypatch.setattr("vigil.agent.bulletin.trace", lambda conn, run_id: "")

    with pytest.raises(SystemExit):
        main(["--volcano", "kilauea", "--at", "2026-10-17T05:00-10:00"])

    assert given["alert_rules"] == {"kilauea-k2": CameraRule(fountain_area=0.5, ambiguous_area=0.1)}
