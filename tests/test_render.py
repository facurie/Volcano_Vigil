from typing import get_args

from vigia.agent.bulletin import ActivityLevel, Bulletin, CitedMeasurement, Evidence
from vigia.agent.render import LEVELS, METRICS, TARGETS, local_time, number, publish, to_html, to_markdown
from vigia.agent.tools import Metric
from vigia.prompts import Target

WIND = {"volcano": "kilauea", "model_hour": "2026-10-17T15:00:00Z", "source": "Open-Meteo Historical Forecast API",
        "altitude_m": 6951, "layer_mean": {"bottom_m": 1080, "top_m": 6951, "from_deg": 331, "toward_deg": 151,
                                           "speed_ms": 3.3},
        "drift_check": {"measured_side_deg": 224.4, "wind_toward_deg": 151, "angle_deg": 73.3, "consistent": True}}


def bulletin(**change):
    measured = dict(camera_id="kilauea-kp", target="plume", frame_ids=[29])
    base = Bulletin(
        id=4, run_id=3, volcano="kilauea", volcano_name="Kīlauea", utc_offset_hours=-10,
        clock="2026-10-17T15:00:00Z", created_at="2026-10-28T18:00:00Z", activity_level="fountaining",
        headline_en="Lava fountain and a tall plume", headline_es="Fuente de lava y una columna alta",
        body_en="KPcam measured the plume top.\n\nThe wind pushes it southwest.",
        body_es="KPcam midió el tope de la columna.\n\nEl viento la empuja al suroeste.",
        measurements=[
            CitedMeasurement(**measured, metric="top_altitude", value=6951, sigma=429, unit="m", verified=True,
                             captured_at="2026-10-17T14:55:05Z"),
            CitedMeasurement(**measured, metric="drift_bearing", value=224.4, sigma=2.1, unit="deg",
                             verified=False)],
        evidence=[Evidence(frame_id=29, target="plume", caption_en="The plume at its peak.",
                           caption_es="La columna en su máximo.", camera_id="kilauea-kp",
                           captured_at="2026-10-17T14:55:05Z", overlay="bulletins/run3/frame29_plume.jpg")],
        wind=WIND, official_agency="USGS Hawaiian Volcano Observatory (HVO)",
        official_url="https://www.usgs.gov/volcanoes/kilauea",
        disclaimer_en="It does not replace official alerts or warnings.",
        disclaimer_es="No reemplaza las alertas ni los avisos oficiales.",
        notes=["1 of 2 quoted number(s) match no stored measurement"])
    return base.model_copy(update=change)


def test_every_level_target_and_metric_has_a_label_in_each_language():
    assert set(LEVELS) == set(get_args(ActivityLevel))
    assert set(TARGETS) == set(get_args(Target)) and set(METRICS) == set(get_args(Metric))


def test_times_are_shown_in_the_volcanos_local_time():
    assert local_time("2026-10-17T14:55:05Z", -10) == "2026-10-17 04:55 (UTC-10)"
    assert local_time("2026-10-17T14:55:05Z", None) == "2026-10-17 14:55 UTC"


def test_numbers_use_each_languages_separators():
    assert (number(6951, "en"), number(6951, "es")) == ("6,951", "6.951")
    assert (number(3.3, "en", 1), number(3.3, "es", 1)) == ("3.3", "3,3")


def test_the_english_markdown_has_the_headline_numbers_wind_evidence_and_source():
    text = to_markdown(bulletin(), "en", image_root="../../")

    assert text.startswith("# Lava fountain and a tall plume\n")
    assert "Kīlauea · 2026-10-17 05:00 (UTC-10) · Activity: Lava fountain" in text
    assert "> **It does not replace official alerts or warnings.**" in text
    assert "| plume: top above sea level | kilauea-kp | 6,951 ± 429 m | 2026-10-17 04:55 (UTC-10) | 29 | yes |" in text
    assert "| plume: side of the line of sight | kilauea-kp | 224° ± 2° | – | 29 | no |" in text
    assert "from 331° toward 151° at 3.3 m/s" in text and "73° from where the wind blows: consistent." in text
    assert "![The plume at its peak.](../../bulletins/run3/frame29_plume.jpg)" in text
    assert "- 1 of 2 quoted number(s) match no stored measurement" in text
    assert text.endswith("Official source: [USGS Hawaiian Volcano Observatory (HVO)]"
                         "(https://www.usgs.gov/volcanoes/kilauea)\n")


def test_the_spanish_markdown_speaks_spanish():
    text = to_markdown(bulletin(), "es")

    assert text.startswith("# Fuente de lava y una columna alta\n")
    assert "Actividad: Fuente de lava" in text and "> **No reemplaza las alertas ni los avisos oficiales.**" in text
    assert "| columna: tope sobre el nivel del mar | kilauea-kp | 6.951 ± 429 m |" in text and "| sí |" in text
    assert "a 3,3 m/s" in text and "coherente" in text
    assert "Fuente oficial: [USGS Hawaiian Volcano Observatory (HVO)]" in text


def test_a_calm_wind_is_not_judged():
    calm = {**WIND, "drift_check": {**WIND["drift_check"], "consistent": None}}

    assert "too calm to tell" in to_markdown(bulletin(wind=calm), "en")
    assert "demasiado calmo para juzgar" in to_markdown(bulletin(wind=calm), "es")


def test_the_html_page_has_both_languages_and_escapes_the_models_text():
    page = to_html(bulletin(headline_en="<script>alert(1)</script>"))

    assert "<script>alert" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert '<article lang="en">' in page and '<article lang="es">' in page
    assert page.count('class="disclaimer"') == 2
    assert "<p>The wind pushes it southwest.</p>" in page
    assert '<a href="https://www.usgs.gov/volcanoes/kilauea">' in page
    assert '<img src="bulletins/run3/frame29_plume.jpg" alt="The plume at its peak.">' in page


def test_publish_writes_the_pages_where_the_overlays_resolve(tmp_path):
    folder = publish(bulletin(), tmp_path, tmp_path / "bulletins")

    assert folder == tmp_path / "bulletins" / "run3"
    assert sorted(path.name for path in folder.iterdir()) == ["bulletin.en.md", "bulletin.es.md", "bulletin.html"]
    assert "](../../bulletins/run3/frame29_plume.jpg)" in (folder / "bulletin.en.md").read_text(encoding="utf-8")
    assert 'src="../../bulletins/run3/frame29_plume.jpg"' in (folder / "bulletin.html").read_text(encoding="utf-8")
