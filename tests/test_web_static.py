import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "vigil" / "web" / "static"


def test_the_page_scripts_never_write_html():
    scripts = list((STATIC / "js").glob("*.js"))
    assert scripts
    for script in scripts:
        text = script.read_text(encoding="utf-8")
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            assert sink not in text, f"{script.name} uses {sink}"


def test_the_notice_is_in_the_page_itself_not_added_by_a_script():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'class="notice"' in page and "{{notice_lead}}" in page and 'href="{{official_url}}"' in page


def test_the_alert_banner_sits_in_the_sticky_top_under_the_notice():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    top = page[page.index('<div class="top">'):page.index("</div>", page.index('class="notice"'))]

    assert 'id="alert-banner"' in top and top.index('class="notice"') < top.index('id="alert-banner"')


def test_leaflet_is_pinned_with_its_integrity_hashes():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert ('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" '
            'integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="') in page
    assert ('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" '
            'integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="') in page


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_javascript_helpers_pass_their_node_tests():
    result = subprocess.run([shutil.which("node"), "--test", str(ROOT / "tests" / "js" / "lib.test.mjs")],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
