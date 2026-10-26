import textwrap

import pytest

from vigia.config import ConfigError, load_sources

VALID = """
volcanoes:
  kilauea:
    name: Kīlauea
    country: United States
    official_agency: USGS Hawaiian Volcano Observatory
    official_url: https://www.usgs.gov/volcanoes/kilauea
cameras:
  - id: kilauea-v1
    name: V1cam
    volcano: kilauea
    url: https://example.org/V1cam/M.jpg
    license: Public Domain
    attribution: U.S. Geological Survey
    enabled: true
    poll_minutes: 5
  - id: kilauea-k2
    name: K2cam
    volcano: kilauea
    url: https://example.org/K2cam/M.jpg
    license: Public Domain
    attribution: U.S. Geological Survey
"""


def write(tmp_path, text):
    path = tmp_path / "sources.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_load_sources_parses_volcanoes_and_cameras(tmp_path):
    sources = load_sources(write(tmp_path, VALID))

    assert sources.volcanoes["kilauea"].official_url == "https://www.usgs.gov/volcanoes/kilauea"
    assert [c.id for c in sources.cameras] == ["kilauea-v1", "kilauea-k2"]
    assert sources.cameras[0].poll_minutes == 5


def test_cameras_are_disabled_unless_explicitly_enabled(tmp_path):
    sources = load_sources(write(tmp_path, VALID))

    assert sources.cameras[1].enabled is False
    assert [c.id for c in sources.enabled_cameras()] == ["kilauea-v1"]


def test_camera_without_license_is_rejected(tmp_path):
    text = VALID.replace("    license: Public Domain\n    attribution: U.S. Geological Survey\n    enabled: true", "    attribution: U.S. Geological Survey\n    enabled: true")
    with pytest.raises(ConfigError, match="license"):
        load_sources(write(tmp_path, text))


def test_camera_with_unknown_volcano_is_rejected(tmp_path):
    text = VALID.replace("volcano: kilauea\n    url: https://example.org/K2cam", "volcano: etna\n    url: https://example.org/K2cam")
    with pytest.raises(ConfigError, match="etna"):
        load_sources(write(tmp_path, text))


def test_duplicate_camera_ids_are_rejected(tmp_path):
    text = VALID.replace("id: kilauea-k2", "id: kilauea-v1")
    with pytest.raises(ConfigError, match="kilauea-v1"):
        load_sources(write(tmp_path, text))
