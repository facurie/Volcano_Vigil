import textwrap
from pathlib import Path

import pytest

from vigia.config import ConfigError, load_sources

REPO = Path(__file__).resolve().parent.parent

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


def test_ashcam_code_is_optional(tmp_path):
    text = VALID.replace("    enabled: true\n    poll_minutes: 5",
                         "    enabled: true\n    poll_minutes: 5\n    ashcam_code: kilauea-v1-cam")

    sources = load_sources(write(tmp_path, text))

    assert sources.cameras[0].ashcam_code == "kilauea-v1-cam"
    assert sources.cameras[1].ashcam_code is None


def test_live_source_defaults_to_the_image_url(tmp_path):
    assert load_sources(write(tmp_path, VALID)).cameras[0].live_source == "url"


def test_live_polling_through_ashcam_needs_an_ashcam_code(tmp_path):
    text = VALID.replace("    enabled: true\n    poll_minutes: 5",
                         "    enabled: true\n    poll_minutes: 5\n    live_source: ashcam")

    with pytest.raises(ConfigError, match="ashcam_code"):
        load_sources(write(tmp_path, text))


def test_committed_sources_keep_sgc_disabled_and_name_every_usgs_archive():
    sources = load_sources(REPO / "config" / "sources.yaml")

    assert [c.id for c in sources.cameras if c.volcano == "nevado-del-ruiz" and c.enabled] == []
    assert [c.id for c in sources.cameras if c.volcano == "kilauea" and not c.ashcam_code] == []


def placed(text, lat="19.405", lon="-155.29"):
    return text.replace("    official_url: https://www.usgs.gov/volcanoes/kilauea",
                        f"    official_url: https://www.usgs.gov/volcanoes/kilauea\n    lat: {lat}\n    lon: {lon}")


def test_volcano_position_is_optional(tmp_path):
    assert load_sources(write(tmp_path, VALID)).volcanoes["kilauea"].lat is None

    volcano = load_sources(write(tmp_path, placed(VALID))).volcanoes["kilauea"]

    assert (volcano.lat, volcano.lon) == (19.405, -155.29)


def test_volcano_latitude_out_of_range_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="lat"):
        load_sources(write(tmp_path, placed(VALID, lat="119.4")))


def test_committed_sources_place_every_volcano():
    sources = load_sources(REPO / "config" / "sources.yaml")

    assert [name for name, v in sources.volcanoes.items() if v.lat is None or v.lon is None] == []


def test_the_repo_sources_give_each_volcanos_local_time():
    sources = load_sources(REPO / "config" / "sources.yaml")

    assert sources.volcanoes["kilauea"].utc_offset_hours == -10      # HST, no daylight saving
    assert sources.volcanoes["nevado-del-ruiz"].utc_offset_hours == -5
