"""SAM 3.1 phrases per target and camera kind, from config/prompts.yaml.

SAM segments one noun phrase per request, so every phrase listed for a target
is a separate call. The phrases were chosen on episode 55 frames with
scripts/tune_prompts.py; the evidence is in docs/research/prompt_tuning.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vigia.config import CameraKind, ConfigError

Target = Literal["plume", "fountain", "incandescence"]
Phrase = Annotated[str, Field(min_length=1)]


class Prompts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plume: dict[CameraKind, list[Phrase]] = {}
    fountain: dict[CameraKind, list[Phrase]] = {}
    incandescence: dict[CameraKind, list[Phrase]] = {}

    def phrases(self, target: Target, kind: CameraKind) -> list[str]:
        """The phrases to send for `target` on a camera of `kind`, best first; empty if none."""
        return list(getattr(self, target).get(kind, []))


def load_prompts(path: str | Path) -> Prompts:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    try:
        return Prompts.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc
