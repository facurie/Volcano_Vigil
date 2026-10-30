import json
from typing import get_args

import pytest
from pydantic import ValidationError

from vigia.agent.bulletin import (DRAFT_FORMAT, DRAFT_SCHEMA, ActivityLevel, BulletinDraft, DraftEvidence,
                                  DraftMeasurement)

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
