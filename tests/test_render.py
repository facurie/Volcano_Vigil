from typing import get_args

from vigil.agent.bulletin import ActivityLevel, Bulletin, CitedMeasurement, Evidence
from vigil.agent.render import (LEVELS, METRICS, TABLE_HEADER, TARGETS, local_time, number, publish, table_rows, to_html,
                               to_markdown)
from vigil.agent.tools import Metric
from vigil.prompts import Target

WIND = {"volcano": "kilauea", "model_hour": "2026-10-17T15:00:00Z", "source": "Open-Meteo Historical Forecast API",
        "altitude_m": 6951, "layer_mean": {"bottom_m": 1080, "top_m": 6951, "from_deg": 331, "toward_deg": 151,
                                           "speed_ms": 3.3},
        "drift_check": {"measured_side_deg": 224.4, "wind_toward_deg": 151, "angle_deg": 73.3, "consistent": True}}


def bulletin(**change):
    measured = dict(camera_id="kilauea-kp", target="plume", frame_ids=[29])
    base = Bulletin(
        id=4, run_id=3, volcano="kilauea", volcano_name="Kīlauea", utc_offset_hours=-10,
        clock="2026-10-17T15:00:00Z", created_at="2026-10-28T18:00:00Z", activity_level="fountaining",
        headline="Lava fountain and a tall plume",
        body="KPcam measured the plume top.\n\nThe wind pushes it southwest.",
        measurements=[
            CitedMeasurement(**measured, metric="top_altitude", value=6951, sigma=429, unit="m", verified=True,
                             captured_at="2026-10-17T14:55:05Z"),
            CitedMeasurement(**measured, metric="drift_bearing", value=224.4, sigma=2.1, unit="deg",
                             verified=False)],
        evidence=[Evidence(frame_id=29, target="plume", caption="The plume at its peak.",
                           camera_id="kilauea-kp",
                           captured_at="2026-10-17T14:55:05Z", overlay="bulletins/run3/frame29_plume.jpg")],
        wind=WIND, official_agency="USGS Hawaiian Volcano Observatory (HVO)",
        official_url="https://www.usgs.gov/volcanoes/kilauea",
        disclaimer="It does not replace official alerts or warnings.",
        notes=["1 of 2 quoted number(s) match no stored measurement"])
    return base.model_copy(update=change)


def test_every_level_target_and_metric_has_a_label():
    assert set(LEVELS) == set(get_args(ActivityLevel))
    assert set(TARGETS) == set(get_args(Target)) and set(METRICS) == set(get_args(Metric))


def test_times_are_shown_in_the_volcanos_local_time():
    assert local_time("2026-10-17T14:55:05Z", -10) == "2026-10-17 04:55 (UTC-10)"
    assert local_time("2026-10-17T14:55:05Z", None) == "2026-10-17 14:55 UTC"


def test_numbers_use_english_separators():
    assert number(6951) == "6,951"
    assert number(3.3, 1) == "3.3"


def test_the_markdown_has_the_headline_numbers_wind_evidence_and_source():
    text = to_markdown(bulletin(), image_root="../../")

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


def test_a_calm_wind_is_not_judged():
    calm = {**WIND, "drift_check": {**WIND["drift_check"], "consistent": None}}

    assert "too calm to tell" in to_markdown(bulletin(wind=calm))


def test_the_html_page_is_one_english_article_and_escapes_the_models_text():
    page = to_html(bulletin(headline="<script>alert(1)</script>"))

    assert "<script>alert" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert page.count("<article") == 1 and '<html lang="en">' in page
    assert page.count('class="disclaimer"') == 1
    assert "<p>The wind pushes it southwest.</p>" in page
    assert '<a href="https://www.usgs.gov/volcanoes/kilauea">' in page
    assert '<img src="bulletins/run3/frame29_plume.jpg" alt="The plume at its peak.">' in page


def test_publish_writes_the_pages_where_the_overlays_resolve(tmp_path):
    folder = publish(bulletin(), tmp_path, tmp_path / "bulletins")

    assert folder == tmp_path / "bulletins" / "run3"
    assert sorted(path.name for path in folder.iterdir()) == ["bulletin.html", "bulletin.md"]
    assert "](../../bulletins/run3/frame29_plume.jpg)" in (folder / "bulletin.md").read_text(encoding="utf-8")
    assert 'src="../../bulletins/run3/frame29_plume.jpg"' in (folder / "bulletin.html").read_text(encoding="utf-8")


def test_publish_removes_the_bilingual_pages_of_an_older_version(tmp_path):
    folder = tmp_path / "bulletins" / "run3"
    folder.mkdir(parents=True)
    for name in ("bulletin.en.md", "bulletin.es.md"):
        (folder / name).write_text("old", encoding="utf-8")

    publish(bulletin(), tmp_path, tmp_path / "bulletins")

    assert sorted(path.name for path in folder.iterdir()) == ["bulletin.html", "bulletin.md"]


HOSTILE = '<b>&"x" onerror="alert(1)'
ESCAPED = "&lt;b&gt;&amp;&quot;x&quot; onerror=&quot;alert(1)"


def test_every_text_the_model_wrote_is_escaped_in_the_html():
    measured = dict(camera_id=HOSTILE, target="plume", frame_ids=[29])
    page = to_html(bulletin(
        body=HOSTILE, notes=[HOSTILE],
        measurements=[CitedMeasurement(**measured, metric="top_altitude", value=6951, sigma=429, unit="m",
                                       verified=True)],
        evidence=[Evidence(frame_id=29, target="plume", caption=HOSTILE,
                           camera_id="kilauea-kp", captured_at="2026-10-17T14:55:05Z",
                           overlay="bulletins/run3/frame29_plume.jpg")]))

    assert "<b>" not in page and 'onerror="alert' not in page
    assert f"<p>{ESCAPED}</p>" in page
    assert f'alt="{ESCAPED}"' in page
    assert f"<figcaption>{ESCAPED} (kilauea-kp," in page
    assert f"<td>{ESCAPED}</td>" in page
    assert f"<li>{ESCAPED}</li>" in page


def test_a_pipe_or_a_newline_in_a_cell_does_not_break_the_markdown_table():
    measured = CitedMeasurement(camera_id="a|b\nc", target="plume", metric="area", value=10, sigma=1, unit="m2",
                                verified=True, frame_ids=[29])

    text = to_markdown(bulletin(measurements=[measured]))

    row = next(line for line in text.splitlines() if "a\\|b c" in line)
    assert row.count("|") - row.count("\\|") == 7


def test_the_public_table_helpers_give_the_markdown_tables_cells():
    b = bulletin()
    markdown = to_markdown(b)

    assert "| " + " | ".join(TABLE_HEADER) + " |" in markdown
    assert table_rows(b)[0][2] == "6,951 ± 429 m"
    assert all(cell in markdown for cell in table_rows(b)[0])
