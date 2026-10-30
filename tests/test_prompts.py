import textwrap
from pathlib import Path

import pytest

from vigil.config import ConfigError
from vigil.prompts import load_prompts

REPO = Path(__file__).resolve().parent.parent

VALID = """
plume:
  visible: [steam plume, steam]
fountain:
  visible: [lava fountain]
  thermal: [hot spot]
incandescence:
  visible: [glowing lava]
"""


def write(tmp_path, text):
    path = tmp_path / "prompts.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_phrases_are_listed_per_target_and_camera_kind_in_order(tmp_path):
    prompts = load_prompts(write(tmp_path, VALID))

    assert prompts.phrases("plume", "visible") == ["steam plume", "steam"]
    assert prompts.phrases("fountain", "thermal") == ["hot spot"]


def test_a_camera_kind_without_phrases_gets_none(tmp_path):
    prompts = load_prompts(write(tmp_path, VALID))

    assert prompts.phrases("plume", "thermal") == []


def test_unknown_target_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="lahar"):
        load_prompts(write(tmp_path, VALID + "lahar:\n  visible: [muddy water]\n"))


def test_unknown_camera_kind_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="infrared"):
        load_prompts(write(tmp_path, VALID.replace("thermal:", "infrared:")))


def test_empty_phrase_is_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_prompts(write(tmp_path, VALID.replace("[lava fountain]", "['']")))


def test_committed_prompts_cover_plumes_and_fountains_on_visible_cameras():
    prompts = load_prompts(REPO / "config" / "prompts.yaml")

    assert prompts.phrases("plume", "visible")
    assert prompts.phrases("fountain", "visible")
