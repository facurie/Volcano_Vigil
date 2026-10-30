import json
from typing import get_args

import pytest
from PIL import Image
from pydantic import ValidationError

from conftest import NOW
from test_agent_tools import (SIZE, T0, add_frame, add_measurement, add_run, add_track, context, detection_ids,
                              store)  # store is a fixture
from vigia.agent.bulletin import (DRAFT_FORMAT, DRAFT_SCHEMA, ActivityLevel, BulletinDraft, DraftEvidence,
                                  DraftMeasurement, build_bulletin, draw_evidence, load_bulletin, run_wind,
                                  store_bulletin, verify)
from vigia.timeutil import to_iso


DRAFT = {  # the shape of Muse Spark's answer in the Phase 5 planning probe
    "activity_level": "fountaining",
    "headline_en": "Lava fountain and a tall plume at Kīlauea",
    "headline_es": "Fuente de lava y una columna alta en el Kīlauea",
    "body_en": "KPcam measured the plume top at 6,951 ± 429 m above sea level at 04:55.",
    "body_es": "KPcam midió el tope de la columna a 6.951 ± 429 m sobre el nivel del mar a las 04:55.",
    "measurements": [{"camera_id": "kilauea-kp", "target": "plume", "metric": "top_altitude", "value": 6951,
                      "sigma": 429, "unit": "m", "frame_ids": [29]}],
    "evidence": [{"frame_id": 29, "target": "plume", "caption_en": "The plume at its peak.",
                  "caption_es": "La columna en su máximo."}],
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
    assert DRAFT_SCHEMA["properties"]["activity_level"]["enum"] == list(get_args(ActivityLevel))
    assert items["measurements"]["metric"]["enum"] == ["top_height", "top_altitude", "area", "drift_offset",
                                                       "drift_bearing"]


def test_a_draft_parses_from_muse_sparks_json():
    draft = BulletinDraft.model_validate_json(json.dumps(DRAFT))

    assert draft.activity_level == "fountaining"
    assert (draft.measurements[0].frame_ids, draft.measurements[0].value) == ([29], 6951)
    assert draft.evidence[0].caption_es == "La columna en su máximo."


@pytest.mark.parametrize("change", [
    {"activity_level": "red_alert"},
    {"headline_en": ""},
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
    assert "does not replace official alerts" in bulletin.disclaimer_en
    assert bulletin.disclaimer_en.endswith("https://www.usgs.gov/volcanoes/kilauea")
    assert "No reemplaza las alertas" in bulletin.disclaimer_es
    assert bulletin.evidence[0].overlay == f"bulletins/run3/frame{frame_id}_plume.jpg"
    assert bulletin.notes == ["1 of 2 quoted number(s) match no stored measurement"]
    assert bulletin.wind is None and bulletin.headline_es == DRAFT["headline_es"]


def test_evidence_after_the_clock_or_beyond_three_frames_is_left_out(conn, store, tmp_path):
    early, late = plume_frame(conn, store), add_frame(conn, store, "kilauea-kp", 5)
    draft = BulletinDraft.model_validate({**DRAFT, "measurements": [],
                                          "evidence": [shown(i).model_dump() for i in (late, early, early, early)]})

    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 3, draft, tmp_path / "bulletins")

    assert [e.frame_id for e in bulletin.evidence] == [early, early]
    assert bulletin.notes == [f"evidence frame {late} left out: no such frame captured by 2026-10-17T15:00:00Z",
                              "1 evidence frame(s) beyond 3 left out"]


def test_a_stored_bulletin_loads_back_with_its_id(conn, tmp_path):
    draft = BulletinDraft.model_validate({**DRAFT, "evidence": []})
    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 3, draft, tmp_path / "bulletins")

    stored = store_bulletin(conn, bulletin)

    assert stored.id == 1 and load_bulletin(conn, 1) == stored
    row = conn.execute("SELECT * FROM bulletins").fetchone()
    assert (row["run_id"], row["activity_level"], row["verified"], row["clock"]) == (
        3, "fountaining", 0, "2026-10-17T15:00:00Z")
    with pytest.raises(KeyError):
        load_bulletin(conn, 2)
