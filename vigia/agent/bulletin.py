"""Bulletins: what the agent tells the public about a volcano, in English and Spanish, with its evidence.

Muse Spark writes a draft as the final answer of an agent run, in the strict JSON format DRAFT_FORMAT: a
descriptive activity level (what the cameras show, never an alert level), a headline and a body in each
language, the measurements the body quotes and the frames that show them. The code adds what must never depend
on the model: the volcano's official agency and link, the disclaimer, the wind check as the get_wind tool
returned it, an overlay of each evidence frame with its masks, and a check of every quoted number against the
stored measurements up to the agent's clock (a number nothing stored supports is marked unverified). Bulletins
are stored in the `bulletins` table; vigia.agent.render turns them into Markdown and HTML.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from vigia.agent.tools import Metric
from vigia.prompts import Target

ActivityLevel = Literal["no_view", "quiet", "degassing", "incandescence", "fountaining"]
Unit = Literal["m", "m2", "deg"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftMeasurement(_Strict):
    camera_id: str
    target: Target
    metric: Metric
    value: float
    sigma: float = Field(ge=0)
    unit: Unit
    frame_ids: list[int] = Field(min_length=1)


class DraftEvidence(_Strict):
    frame_id: int
    target: Target
    caption_en: str
    caption_es: str


class BulletinDraft(_Strict):
    """What Muse Spark writes."""

    activity_level: ActivityLevel
    headline_en: str = Field(min_length=1)
    headline_es: str = Field(min_length=1)
    body_en: str = Field(min_length=1)
    body_es: str = Field(min_length=1)
    measurements: list[DraftMeasurement]
    evidence: list[DraftEvidence]


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _enum(literal: Any) -> dict[str, Any]:
    return {"type": "string", "enum": list(get_args(literal))}


DRAFT_SCHEMA = _object({
    "activity_level": _enum(ActivityLevel),
    "headline_en": {"type": "string"},
    "headline_es": {"type": "string"},
    "body_en": {"type": "string"},
    "body_es": {"type": "string"},
    "measurements": {"type": "array", "items": _object({
        "camera_id": {"type": "string"}, "target": _enum(Target), "metric": _enum(Metric),
        "value": {"type": "number"}, "sigma": {"type": "number"}, "unit": _enum(Unit),
        "frame_ids": {"type": "array", "items": {"type": "integer"}}})},
    "evidence": {"type": "array", "items": _object({
        "frame_id": {"type": "integer"}, "target": _enum(Target),
        "caption_en": {"type": "string"}, "caption_es": {"type": "string"}})},
})
DRAFT_FORMAT = {"type": "json_schema", "name": "bulletin", "schema": DRAFT_SCHEMA, "strict": True}
