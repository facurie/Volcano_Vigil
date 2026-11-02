# Phase 9: Fountain Calibration, English Only, Validation, README and Review — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** measure episode 55's fountain with a calibrated K2cam, publish everything in English only (bulletins, alerts, Telegram, dashboard, stored outputs), and finish the validation report, the README and a code review before the Nov 4 submission.

**Architecture:** K2cam gets its `ep55` preset from configuration alone: the Axis Q6318's datasheet field of view, a level-mount roll prior and the Puʻukoaʻe landmark, through the existing `vigil.calibration` Monte Carlo. The English-only change is one vertical slice per published object (bulletins, then alerts, then the dashboard toggle): monolingual models and texts, a one-time database migration (`PRAGMA user_version` 1) that drops the stored Spanish, and a re-render of the episode 55 replay's outputs before the mirror and the Space are updated.

**Tech stack:** Python 3.12, SQLite (3.45 locally, 3.40 in the Space image: both have `DROP COLUMN` and `RENAME COLUMN`), Pydantic, FastAPI, plain ES modules, pytest and node's test runner.

---

## Decisions and facts this plan rests on

**K2cam calibration (checked on real frames while planning, 2026-11-02).**
- K2cam is a 4K PTZ with no readout. Patrick et al. 2026 (doi:10.1186/s13617-026-00170-x) names HVO's one snapshot PTZ: "one is PTZ (Axis Q6318)"; K2cam is the only PTZ in the snapshot network, so it is that camera (an inference, stated as such).
- Axis lists the AXIS Q6318-LE's horizontal field of view as 58.5°–2.3° (31× zoom, 3840×2160): https://www.axis.com/products/axis-q6318-le. Zooming only narrows it.
- Phase 3's USGS 3DEP skyline fit with Puʻukoaʻe, made with no field-of-view prior, had two solutions: focal 2,122 px (HFOV 84.3°) or 3,479 px (57.8°). The hardware rules out 84.3°; 57.8° is within 1.2 % of the widest zoom, so the camera was at (or next to) its widest zoom.
- Trial solve (scratch, not committed): Puʻukoaʻe at pixel (2992, 1629) (GNIS 19.35528, −155.32235; EPQS 979 m), HFOV 58.5 ± 1.5°, roll 0 ± 1°, k1 0 ± 0.05 gives azimuth 188.8 ± 0.8°, tilt +7.07 ± 0.43°, focal 3,428 ± 103 px. Checks, neither of them a fit:
  - the vent projects to (1670, 1853); the fountain's axis is at x ≈ 1830 and its visible foot at row ≈ 1835. 160 px is 2.7° of bearing, what K2cam's ±75 m position allows at 1,678 m (±2.6°); 18 px below the foot is ~9 m of fountain hidden by the rampart in front of it;
  - the predicted sea horizon runs along rows 1571–1581 across x 2600–3840, just under the trade-cumulus base (~row 1560) and above the land skyline (~1630), as on KPcam.
- Adding the vent pixel as a reference makes it worse: its bearing depends on the camera's ±75 m, so the solver bends the focal length to 3,070 ± 242 px. The vent stays a check, as on KPcam.
- Barrel distortion is not measured. Its effect on the fountain (rows 1560–1840, near the centre column) is under 2 m; its effect on the datasheet's FOV-to-focal conversion is up to ~3 %, which the 1.5° sigma covers.
- **Freeze rule:** `config/calibration.yaml` is committed before any fountain height is computed, and never changed after the validation is generated.

**English only (the user's decision of 2026-11-02).**
- Models become monolingual: `Bulletin.headline/body/disclaimer`, `Evidence.caption`, `BulletinDraft.headline/body`, `DraftEvidence.caption`, `Alert.headline/text/disclaimer`. `DISCLAIMER_EN` becomes `DISCLAIMER`; `DISCLAIMER_ES`, `NOTE_ES` and every Spanish label go.
- **What happens to the Spanish already stored:** it is dropped. `db.connect` runs a one-time migration (`PRAGMA user_version` 0 → 1, inside `BEGIN IMMEDIATE`, so several processes starting together migrate once):
  - `bulletins`: `DROP COLUMN headline_es`, `RENAME COLUMN headline_en TO headline`;
  - every stored JSON with bilingual texts (bulletin bodies, alert bodies, the agent's final drafts in `agent_runs.final_text` and `agent_steps.text`) goes through `db.english_only`: `x_en` becomes `x`, `x_es` is dropped, evidence items too. The English text stays verbatim.
- Readers stay strict (no legacy parsing). So: the Space opens its live database once with `db.connect` before the dashboard starts (`deploy/start.sh`), and the episode 55 mirror is pushed migrated **before** the Space runs the new code.
- Published files: a bulletin is `bulletin.html` + `bulletin.md`; `publish` deletes the old `bulletin.en.md`/`bulletin.es.md`. The episode 55 replay's bulletins, `timeline.json` and `report.md` are regenerated from the migrated database at no Meta API cost (every replay tick and alert tick is stored, and `spark_phases.json` exists).
- The two replay alerts already posted to the Telegram channel (messages 3–4, bilingual) are left alone; re-posting them in English is the user's call (Task 11).

**Money.** No task calls the Meta API. The first English-only bulletin is written by the live Space in its normal hourly run, inside its existing $5 daily cap.

## File map

| File | Change |
|---|---|
| `config/calibration.yaml` | K2cam `ep55` preset: FOV, roll and distortion priors, Puʻukoaʻe |
| `docs/research/calibration_ep55.md` | K2cam section rewritten with the evidence |
| `scripts/validate_ep55.py` | method text, alerts section, limitations; regenerates `docs/VALIDATION.md` |
| `vigil/db.py` | new bulletins column, `english_only`, `SCHEMA_VERSION`, `_migrate` |
| `vigil/agent/bulletin.py` | monolingual draft, schema, prompt and bulletin; `DISCLAIMER` |
| `vigil/agent/render.py` | English only; `bulletin.md`; legacy files removed |
| `vigil/alerts.py`, `vigil/telegram.py` | English texts, caption, replay note, test message |
| `vigil/web/views.py`, `vigil/web/app.py` | flat English bulletins and alerts; one disclaimer |
| `vigil/web/static/{index.html,js/*.js}` | no language toggle |
| `vigil/replay.py`, `vigil/mirror.py`, `vigil/space.py`, `vigil/gate.py`, `scripts/smoke_test.py`, `.interface-design/system.md` | remaining Spanish |
| `scripts/republish_bulletins.py` | re-renders a database's stored bulletins |
| `deploy/start.sh` | migrate the live database before the dashboard starts |
| `README.md`, `docs/PLAN.md`, `DATA_SOURCES.md` | final text |

---

### Task 1: Calibrate K2cam for episode 55 (orchestrator, inline: it needs judgment on images)

**Files:**
- Modify: `config/calibration.yaml` (the `kilauea-k2` preset `ep55`)
- Modify: `docs/research/calibration_ep55.md` (section "K2cam")

- [ ] **Step 1: Confirm Puʻukoaʻe's pixel and the framing on three clear daytime frames.** Crop x 2900–3100, rows 1580–1680 at 4× from the K2 frames nearest 2026-10-17T17:00Z, 18:00Z and 19:00Z (`data/vigil.sqlite`, `camera_id='kilauea-k2'`). The summit of the hump must sit within 3 px of (2992, 1629) on all three; if it moves, stop and re-check the framing before going on.

- [ ] **Step 2: Write the preset** (replace the current `ep55` entry):

```yaml
      - name: ep55
        valid_from: "2026-10-17T00:00:00Z"
        valid_until: "2026-10-18T00:00:00Z"
        image_size: [3840, 2160]
        fov:
          hfov_deg: 58.5
          sigma_deg: 1.5
          source: >-
            Widest zoom of the AXIS Q6318-LE, 58.5-2.3 deg (https://www.axis.com/products/axis-q6318-le). K2cam is
            HVO's one snapshot PTZ camera, which Patrick et al. 2026 (doi:10.1186/s13617-026-00170-x) name as an
            Axis Q6318. Phase 3's 3DEP skyline fit, made without this prior, had a solution at 57.8 deg (the other,
            84.3 deg, is wider than the lens), so the camera was at its widest zoom. The sigma covers the unmeasured
            barrel distortion (up to ~3 % on the focal length) and the spread between units.
        roll:
          deg: 0.0
          sigma_deg: 1.0
          source: A pan-tilt-zoom camera on a level mount; the far skyline is level within 0.3 deg across the frame.
        distortion:
          k1: 0.0
          sigma: 0.05
          source: Not measured; a zoom lens at its wide end bends little, and the fountain sits near the centre column.
        landmarks:
          - name: Puʻukoaʻe
            pixel: [2992, 1629]
            sigma_px: [3.0, 3.0]
            lat: 19.35528
            lon: -155.32235
            elev_m: 979
            sigma_m: 50
            sigma_elev_m: 10
            source: GNIS summit point; ground elevation from USGS EPQS. The hump on the right-hand skyline, 8.0 km away at 206 deg.
        note: >-
          PTZ without a readout; the framing held through episode 55 (frames register within 4 px). The vent is a
          check, not a reference: its bearing depends on the camera's estimated position (+/-75 m at 1,678 m).
```

- [ ] **Step 3: Check it.** Run `.venv/Scripts/python.exe scripts/check_calibration.py --camera kilauea-k2 --at 2026-10-17T18:00Z`. Expected: azimuth ≈ 188.8°, tilt ≈ +7.1°, focal ≈ 3,430 ± 100 px, all 1,000 samples converge. Open the overlay in `data/calibration/` and record:
  - where the vent lands against the fountain's axis and visible foot;
  - where the predicted sea horizon runs against the cumulus base and the land skyline;
  - the 50 m height scale above the vent: its ticks must be evenly spaced and stand vertically over the vent.
  Do **not** compute or look at any fountain height yet.

- [ ] **Step 4: Rewrite the K2cam section of `docs/research/calibration_ep55.md`** with: the hardware and its source; why the 84.3° solution is impossible; the references and priors; the solved view with sigmas; the two checks with their numbers; the limitations (the model is an inference; zoom assumed widest; distortion unmeasured; position ±75 m = ±4.5 % on distance). Also update the Monte Carlo inputs table (K2cam's FOV, roll, distortion, Puʻukoaʻe rows).

- [ ] **Step 5: Run the suite and commit the calibration before any measurement.**

```bash
.venv/Scripts/python.exe -m pytest
git add config/calibration.yaml docs/research/calibration_ep55.md
git commit -m "Calibrate K2cam for episode 55 from its lens datasheet and Puʻukoaʻe, so the fountain can be measured"
```

### Task 2: Measure the fountain and write the final validation report (orchestrator, inline)

**Files:**
- Modify: `scripts/validate_ep55.py`
- Regenerate: `docs/VALIDATION.md`

- [ ] **Step 1: Measure K2cam's episode 55 detections** (free, local):

```bash
.venv/Scripts/vigil-measure.exe --camera kilauea-k2 --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z
```

Expected: a summary with K2's fountain, plume and glow detections measured and 0 uncalibrated. Masks cut off by the frame's top edge get no top (`metrics.CUT_OFF_ROWS`).

- [ ] **Step 2: Update the report text in `scripts/validate_ep55.py`.**
  - Method paragraph: K2cam is calibrated from its lens datasheet and Puʻukoaʻe (link the research note), KPcam from the Moon.
  - Replace "A "no measurement" row has no calibrated camera yet." with a sentence on what a fountain top is (the highest pixel of the `lava fountain` mask, on the vertical plane through the vent; spray and the plume's glow can raise it at night).
  - Add a `## Fountaining alerts (replay)` section: open `data/replay/ep55/vigil.sqlite` with `db.connect_readonly` and print `alert_rows(conn, EP55)` under `ALERT_HEADER` (both in `vigil/replay.py`), plus one line with the overflow window's result read from `data/replay/overflows/vigil.sqlite`: `SELECT COUNT(*) FROM alerts` (expected 0) and the number of SAM looks (`SELECT COUNT(*) FROM alert_checks`). Skip a section with a one-line note if its database is missing.
  - Add a `## Limitations` section (static text): camera positions estimated (KP ±500 m, K2 ±75 m); K2's model inferred and zoom assumed widest; lens distortion unmeasured on K2; plume tops are the mask's highest point and can be downwind cloud (the 07:30 row); fountain tops at night include spray and glow; one camera sees only the drift's across-track component; the model wind's low levels disagree with HVO's; one episode only; official values are rounded reports, not measurements with sigmas.

- [ ] **Step 3: Regenerate and read it.**

```bash
.venv/Scripts/python.exe scripts/validate_ep55.py
```

Expected: the four fountain rows now carry a value ± σ, an error and z; read every row and check units (m and ft), local times and the agree column by hand against `docs/research/episode55.md`. Do not touch the calibration whatever the result.

- [ ] **Step 4: Commit.**

```bash
git add scripts/validate_ep55.py docs/VALIDATION.md
git commit -m "Validate episode 55's fountain heights from K2cam and finish the validation report with alerts and limitations"
```

### Task 3: Bulletins in English only, stored Spanish dropped (implementer)

**Files:**
- Modify: `vigil/db.py`, `vigil/agent/bulletin.py`, `vigil/agent/render.py`, `vigil/web/views.py` (`bulletins` only), `vigil/web/static/js/feed.js`, `vigil/web/static/js/drum.js`, `vigil/replay.py` (`report_markdown`), `vigil/alerts.py`, `vigil/web/app.py`, `vigil/mirror.py` (import rename only)
- Test: `tests/test_db.py`, `tests/test_bulletin.py`, `tests/test_render.py`, `tests/test_web_views.py`, `tests/test_replay.py`

- [ ] **Step 1: Write the failing migration tests** in `tests/test_db.py`:

```python
import json

LEGACY_BULLETINS = """CREATE TABLE bulletins (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, volcano TEXT NOT NULL, clock TEXT NOT NULL,
    created_at TEXT NOT NULL, activity_level TEXT NOT NULL, headline_en TEXT NOT NULL, headline_es TEXT NOT NULL,
    verified INTEGER NOT NULL, body TEXT NOT NULL)"""
BILINGUAL = {"id": 1, "headline_en": "Lava fountain", "headline_es": "Fuente de lava", "body_en": "It fountains.",
             "body_es": "Hay fuente.", "disclaimer_en": "Not official.", "disclaimer_es": "No oficial.",
             "evidence": [{"frame_id": 29, "caption_en": "The fountain.", "caption_es": "La fuente."}],
             "measurements": [{"frame_ids": [29], "value": 220.0}]}


def test_english_only_keeps_each_english_text_under_its_plain_name_and_drops_the_spanish():
    assert db.english_only(BILINGUAL) == {
        "id": 1, "headline": "Lava fountain", "body": "It fountains.", "disclaimer": "Not official.",
        "evidence": [{"frame_id": 29, "caption": "The fountain."}], "measurements": [{"frame_ids": [29], "value": 220.0}]}
    assert db.english_only({"headline_en": "Seen", "text_en": "At 03:07.", "text_es": "A las 03:07."}) == {
        "headline": "Seen", "text": "At 03:07."}
    assert db.english_only({"headline": "Already English"}) == {"headline": "Already English"}


def test_a_database_from_before_phase_9_loses_its_spanish_once(tmp_path):
    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.execute(LEGACY_BULLETINS)
    old.execute("INSERT INTO bulletins VALUES (1, 1, 'kilauea', '2026-10-17T15:00:00Z', '2026-10-17T15:01:00Z', "
                "'fountaining', 'Lava fountain', 'Fuente de lava', 1, ?)", (json.dumps(BILINGUAL),))
    old.commit()
    old.close()

    conn = db.connect(path)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(bulletins)")]
        assert "headline" in columns and "headline_en" not in columns and "headline_es" not in columns
        assert json.loads(conn.execute("SELECT body FROM bulletins").fetchone()[0]) == db.english_only(BILINGUAL)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    finally:
        conn.close()
    db.connect(path).close()  # a second open finds nothing left to migrate


def test_the_agents_stored_drafts_lose_their_spanish_but_other_text_is_untouched(conn):
    draft = json.dumps({"headline_en": "Plume", "headline_es": "Columna", "body_en": "Tall.", "body_es": "Alta."})
    with conn:
        conn.execute("INSERT INTO agent_runs (id, started_at, clock, volcano, task, model, status, final_text) "
                     "VALUES (1, 'x', 'x', 'kilauea', 't', 'm', 'done', ?)", (draft,))
        conn.executemany("INSERT INTO agent_steps (run_id, seq, turn, kind, created_at, text) VALUES (1, ?, 1, 'model', 'x', ?)",
                         [(1, "Looking at KPcam_es\" first."), (2, draft)])
        conn.execute("PRAGMA user_version = 0")
    db._migrate(conn)

    assert json.loads(conn.execute("SELECT final_text FROM agent_runs").fetchone()[0]) == {"headline": "Plume", "body": "Tall."}
    texts = [row[0] for row in conn.execute("SELECT text FROM agent_steps ORDER BY seq")]
    assert texts[0] == "Looking at KPcam_es\" first." and json.loads(texts[1]) == {"headline": "Plume", "body": "Tall."}


def test_a_new_database_starts_at_the_current_schema_version(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert "headline_es" not in {row[1] for row in conn.execute("PRAGMA table_info(bulletins)")}
```

- [ ] **Step 2: Run them; they fail** (`AttributeError: module 'vigil.db' has no attribute 'english_only'`).

Run: `.venv/Scripts/python.exe -m pytest tests/test_db.py`

- [ ] **Step 3: Implement in `vigil/db.py`.** In `SCHEMA`, the bulletins table's two headline columns become one: `headline       TEXT    NOT NULL,`. Then add:

```python
import json
from typing import Any

SCHEMA_VERSION = 1  # PRAGMA user_version of a database _migrate has brought up to date
BILINGUAL = ("headline", "body", "text", "caption", "disclaimer")  # texts stored as x_en and x_es until Phase 9
BILINGUAL_JSON = (("bulletins", "body"), ("alerts", "body"), ("agent_runs", "final_text"), ("agent_steps", "text"))


def english_only(record: dict[str, Any]) -> dict[str, Any]:
    """A stored bulletin, alert or bulletin draft as published from Phase 9 on. Until then each of its texts came in
    English (x_en) and Spanish (x_es): x_en becomes x and x_es is dropped, in its evidence items too."""
    out = dict(record)
    for name in BILINGUAL:
        if f"{name}_en" in out:
            out[name] = out.pop(f"{name}_en")
        out.pop(f"{name}_es", None)
    if isinstance(out.get("evidence"), list):
        out["evidence"] = [english_only(item) if isinstance(item, dict) else item for item in out["evidence"]]
    return out


def _english_only_texts(conn: sqlite3.Connection) -> None:
    """Version 1: everything published is in English, so the Spanish stored before is dropped."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(bulletins)")}
    if "headline_es" in columns:
        conn.execute("ALTER TABLE bulletins DROP COLUMN headline_es")
        conn.execute("ALTER TABLE bulletins RENAME COLUMN headline_en TO headline")
    for table, column in BILINGUAL_JSON:
        rows = conn.execute(f"SELECT id, {column} FROM {table} WHERE instr({column}, '_es\"') > 0").fetchall()
        for row_id, text in rows:
            try:
                record = json.loads(text)
            except ValueError:
                continue  # model commentary, not a stored record
            if isinstance(record, dict):
                conn.execute(f"UPDATE {table} SET {column} = ? WHERE id = ?",
                             (json.dumps(english_only(record), ensure_ascii=False, separators=(",", ":")), row_id))


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring a database written by older code up to SCHEMA_VERSION, in one write transaction, so processes that open
    it at the same time migrate it once."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
            _english_only_texts(conn)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
```

and call `_migrate(conn)` in `connect()` right after `conn.executescript(SCHEMA)`. (`connect_readonly` never migrates.)

- [ ] **Step 4: Run `tests/test_db.py`; it passes.**

- [ ] **Step 5: Make bulletins monolingual — update the tests first.** In `tests/test_render.py`, `tests/test_bulletin.py`, `tests/test_web_views.py` and `tests/test_replay.py`, every bulletin fixture uses `headline=`, `body=`, `disclaimer=`, evidence `caption=` (no `_en`, no `_es`), drafts use `headline`, `body`, evidence `caption`. Replace the bilingual assertions:
  - `test_render.py`: `number(6951)` is `"6,951"` and `number(3.3, 1)` is `"3.3"`; `to_markdown(bulletin(), image_root="../../")` keeps every English assertion of the current English test; delete the Spanish markdown test and the Spanish calm-wind assertion; the HTML test asserts one `<article>` (`page.count("<article") == 1`), one `class="disclaimer"` and `'<html lang="en">'`; the publish test expects `["bulletin.html", "bulletin.md"]`; add:

```python
def test_publish_removes_the_bilingual_pages_of_an_older_version(tmp_path):
    folder = tmp_path / "bulletins" / "run3"
    folder.mkdir(parents=True)
    for name in ("bulletin.en.md", "bulletin.es.md"):
        (folder / name).write_text("old", encoding="utf-8")

    publish(bulletin(), tmp_path, tmp_path / "bulletins")

    assert sorted(path.name for path in folder.iterdir()) == ["bulletin.html", "bulletin.md"]
```

  - `test_bulletin.py`: the draft schema's properties are exactly `{"activity_level", "headline", "body", "measurements", "evidence"}` and evidence items' are `{"frame_id", "target", "caption"}`; add `assert "Spanish" not in BULLETIN_FINISH and "English" in BULLETIN_FINISH`; the built bulletin's `disclaimer == DISCLAIMER.format(...)`; the stored row is read back with `SELECT headline FROM bulletins`.
  - `test_web_views.py` (bulletins): a bulletin dict has `headline`, `body`, `disclaimer`, `level` (`"Lava fountain"`), `when`, `header` (`render.TABLE_HEADER`), `rows` (`render.table_rows(first)`, with `"6,964 ± 419 m"`), `wind_text`, and neither `"en"` nor `"es"`; the disclaimer is `DISCLAIMER.format(...)` even when the stored one says Vigía Andino; evidence items carry `caption`.
  - `test_replay.py`: the report's bulletins table header is `| Time (local) | Activity | Headline | Numbers checked |`.

  Run them: they fail.

- [ ] **Step 6: Implement.**
  - `vigil/agent/render.py`: English only. `LEVELS`, `TARGETS`, `METRICS` map to one string each (the current English labels); `TABLE_HEADER = ["What", "Camera", "Value", "Captured", "Frames", "Checked"]`; drop `Lang`, `_pick`, `WORDS`, `texts`, `table_header`; `number(value, decimals=0)` returns `f"{value:,.{decimals}f}"`; `quantity(m)`, `wind_text(b)`, `table_rows(b)` lose their `lang` argument and keep the English wording exactly; `to_markdown(b, *, image_root="")` and `to_html(b, *, image_root="")` produce the current English output (HTML: one `<article>` inside `<html lang="en">`, the `article+article` rule dropped from `STYLE`); `publish` writes `bulletin.html` and `bulletin.md` and then `(folder / name).unlink(missing_ok=True)` for `LEGACY_FILES = ("bulletin.en.md", "bulletin.es.md")`. Module docstring: "Bulletins as Markdown and HTML, and the files a bulletin is published as."
  - `vigil/agent/bulletin.py`: `DISCLAIMER_EN` is renamed `DISCLAIMER` (update the imports in `vigil/alerts.py`, `vigil/web/app.py`, `vigil/web/views.py`, `vigil/mirror.py`; leave `DISCLAIMER_ES` defined for now, Task 5 deletes it); `DraftEvidence.caption`, `BulletinDraft.headline/body`, `Bulletin.headline/body/disclaimer`; `DRAFT_SCHEMA` to match; `build_bulletin` sets `disclaimer=DISCLAIMER.format(**names)`; `store_bulletin` inserts into `headline`; `write_bulletin` selects `headline` for the previous bulletin; the CLI prints `to_markdown(written.bulletin)` once; the module docstring drops Spanish. The prompt becomes:

```python
BULLETIN_FINISH = """\
Finish with a bulletin for the public, in English, as the JSON your answer format describes:
- activity_level: what the cameras show now. It describes, it never sets an alert level: no_view (no camera can see \
the vent: cloud, fog, darkness or no fresh frames), quiet (a clear view with no plume, glow or fountain), degassing \
(a gas or steam plume and no glowing lava), incandescence (glowing lava but no fountain), fountaining (a lava \
fountain).
- headline: one sentence. body: three to six sentences on what each useful camera shows, the measurements with \
± sigma, units and local times, the drift against the wind, and what could not be measured and why. Write the \
body's numbers as people read them, rounded to what the sigma supports: 6,951 ± 429 m, an area of about 20.6 km², \
3.3 m/s.
- measurements: every number the body quotes from measure_track or get_history, exactly as the tool returned it \
(value and sigma), with its camera, target, metric, unit and the frame ids it came from. Quote per-frame values \
(latest or max), not means.
- evidence: one to three frames that best show what you describe, each with the target whose mask to draw and a \
short caption.
- drift_bearing is the side of the camera's line of sight the plume sits on, not the direction it travels.
Do not write a disclaimer or the official source: every bulletin gets them."""
```

  - `vigil/web/views.py`: `bulletins()` returns, per bulletin, the current non-language keys plus `headline`, `body`, `disclaimer` (`DISCLAIMER.format(...)`, with the comment about Vigía Andino kept), `level` (`render.LEVELS[...]`), `when`, `header` (`render.TABLE_HEADER`), `rows` (`render.table_rows(b)`), `wind_text`; delete `_language`; the docstring says "with the published tables".
  - `vigil/web/static/js/feed.js`: drop `const t = b[state.lang]` and read `b.level`, `b.headline`, `b.disclaimer`, `b.body`, `b.rows`, `b.header`, `b.wind_text`, and `e.caption` for evidence; drop the `lang` attribute on the `<li>` (the page is `lang="en"`); keep the language buttons' wiring untouched for now (Task 5 removes it).
  - `vigil/web/static/js/drum.js` line 204: `b.level`.
  - `vigil/replay.py` `report_markdown`: drop the `Titular` column and `headline_es`; read `b["headline"]`.

- [ ] **Step 7: Run the whole suite; it passes.** `.venv/Scripts/python.exe -m pytest` (the node tests included).

- [ ] **Step 8: Commit.**

```bash
git add vigil/db.py vigil/agent/bulletin.py vigil/agent/render.py vigil/web/views.py vigil/web/static/js/feed.js vigil/web/static/js/drum.js vigil/replay.py vigil/alerts.py vigil/web/app.py vigil/mirror.py tests/test_db.py tests/test_bulletin.py tests/test_render.py tests/test_web_views.py tests/test_replay.py
git commit -m "Write bulletins in English only and drop the Spanish stored before, as the user decided"
```

### Task 4: Alerts and Telegram in English only (implementer)

**Files:**
- Modify: `vigil/alerts.py`, `vigil/telegram.py`, `vigil/db.py` (nothing new: the migration already rewrites `alerts.body`; add a test), `vigil/web/views.py` (`alerts` only), `vigil/web/static/js/alerts.js`
- Test: `tests/test_alerts.py`, `tests/test_telegram.py`, `tests/test_web_views.py`, `tests/test_db.py`

- [ ] **Step 1: Update the tests first.**
  - `tests/test_alerts.py`: `alert_texts` returns exactly `{"headline", "text"}`; the onset test keeps its English assertions (on `texts["headline"]`, `texts["text"]`) and loses the Spanish ones; same for the end test and the two-cameras test (`alert.text`); the caption test becomes:

```python
@pytest.mark.parametrize("kind", ["onset", "end"])
def test_the_caption_has_the_text_the_note_and_the_official_link_within_telegrams_limit(kind):
    alert = make_alert(kind)
    text = caption(alert, prefix="REPLAY of episode 55 (2026-10-17): not a live alert.")

    for part in (alert.headline, alert.text, NOTE, "USGS Hawaiian Volcano Observatory (HVO): https://www.usgs.gov/volcanoes/kilauea"):
        assert part in text
    assert "REPETICIÓN" not in text and "Lectura" not in text
    assert len(text) <= CAPTION_MAX
```

    (keep whatever `make_alert` already builds, with its fields renamed to `headline`, `text`, `disclaimer`; check the official link string against `make_alert` and adjust the literal if it differs). The replay-post test asserts the note is `REPLAY_NOTE.format(...)` with no Spanish, e.g. `assert "REPETICIÓN" not in posted`.
  - `tests/test_telegram.py`: the test message has no Spanish (`"Mensaje" not in TEST_MESSAGE` and `"Estado oficial" not in TEST_MESSAGE`) and still names the agency and URL.
  - `tests/test_web_views.py` (alerts): each alert dict has `headline`, `text`, `disclaimer` and neither `"en"` nor `"es"`; update the expected key set (line ~352) accordingly.
  - `tests/test_db.py`: add

```python
def test_a_stored_alert_loses_its_spanish_in_the_migration(conn):
    body = {"id": 1, "headline_en": "Seen", "headline_es": "Visto", "text_en": "At 03:07.", "text_es": "A las 03:07.",
            "disclaimer_en": "Not official.", "disclaimer_es": "No oficial."}
    with conn:
        conn.execute("INSERT INTO frames (id, camera_id, captured_at, timestamp_source, fetched_at, sha256, path, "
                     "bytes, width, height) VALUES (1, 'kilauea-v1', 'x', 'ashcam', 'x', 'h', 'p', 1, 1, 1)")
        conn.execute("INSERT INTO alerts (id, volcano, kind, clock, created_at, camera_id, frame_id, captured_at, "
                     "seen_at, body) VALUES (1, 'kilauea', 'onset', 'x', 'x', 'kilauea-v1', 1, 'x', 'x', ?)",
                     (json.dumps(body),))
        conn.execute("PRAGMA user_version = 0")
    db._migrate(conn)

    assert json.loads(conn.execute("SELECT body FROM alerts").fetchone()[0]) == {
        "id": 1, "headline": "Seen", "text": "At 03:07.", "disclaimer": "Not official."}
```

  Run them; the alert, Telegram and view tests fail (the db test passes already: the migration covers `alerts.body`).

- [ ] **Step 2: Implement.**
  - `vigil/alerts.py`: `HEADLINES` and `TEXTS` map each kind to its English string only; `NOTE_EN` becomes `NOTE`, `NOTE_ES` goes; `Alert` has `headline`, `text`, `disclaimer` (no `_en`/`_es`); `_names(names)` always joins with "and"; `alert_texts` returns `{"headline": ..., "text": ...}`; `caption` is `[prefix, ""]` + `[alert.headline, alert.text, NOTE, "", f"{alert.official_agency}: {alert.official_url}"]`; `_raise` passes `disclaimer=DISCLAIMER.format(**names)`; `REPLAY_NOTE = "REPLAY of episode {key} ({date}): not a live alert."`; module docstring: "each change an alert (the alerts table) with its text, the frame with its mask, …"; `post_replay` reads `headline` where it read `headline_en`.
  - `vigil/telegram.py`: `TEST_MESSAGE = ("Volcano Vigil test message: the alert channel works. It is not an alert.\n\nOfficial status: {agency}: {url}")`.
  - `vigil/web/views.py` `alerts()`: replace the `"en"`/`"es"` dicts with `"headline": a.headline, "text": a.text, "disclaimer": a.disclaimer`.
  - `vigil/web/static/js/alerts.js`: `shown.headline`; drop the `lang` attribute.

- [ ] **Step 3: Run the whole suite; it passes.**

- [ ] **Step 4: Commit.**

```bash
git add vigil/alerts.py vigil/telegram.py vigil/web/views.py vigil/web/static/js/alerts.js tests/test_alerts.py tests/test_telegram.py tests/test_web_views.py tests/test_db.py
git commit -m "Write fountaining alerts and Telegram captions in English only"
```

### Task 5: No language toggle, and the last Spanish (implementer)

**Files:**
- Modify: `vigil/web/static/index.html`, `vigil/web/static/js/feed.js`, `vigil/web/static/js/main.js`, `vigil/web/app.py`, `vigil/agent/bulletin.py` (delete `DISCLAIMER_ES`), `vigil/gate.py`, `vigil/mirror.py`, `vigil/space.py`, `scripts/smoke_test.py`, `deploy/start.sh`, `.interface-design/system.md`
- Test: `tests/test_web_app.py`, `tests/test_web_static.py`, `tests/test_gate.py`, `tests/test_mirror.py`, `tests/test_space.py`, `tests/test_deploy.py`

- [ ] **Step 1: Update the tests first.**
  - `tests/test_web_static.py`: add

```python
def test_the_page_has_no_language_toggle():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "data-lang" not in page and "Bulletin language" not in page
    for script in (STATIC / "js").glob("*.js"):
        text = script.read_text(encoding="utf-8")
        assert "state.lang" not in text and "setLang" not in text, script.name
```

  - `tests/test_web_app.py` (~line 73): `config["disclaimer"]` is one string starting "Automated, experimental reading"; no `"es"`.
  - `tests/test_gate.py`: the gate schema's properties hold `description_en` and not `description_es`; the prompt asks for a description "in English" (`"Spanish" not in GATE_PROMPT` — use the module's actual prompt constant name); drop `description_es` from the test's `ANSWER`.
  - `tests/test_mirror.py`: the dataset card says each bulletin is "in English" and does not contain "Spanish".
  - `tests/test_space.py`: the Space card's `short_description` contains no "ES/EN".
  - `tests/test_deploy.py`: `start.sh` opens the live database with `db.connect` before `vigil-web` starts:

```python
def test_the_live_database_is_migrated_before_the_dashboard_starts():
    script = (ROOT / "deploy" / "start.sh").read_text(encoding="utf-8")
    assert script.index("db.connect(") < script.index("vigil-web --host")
```

    (use the file's existing `ROOT`/path constant.)
  - `grep -rn "DISCLAIMER_ES\|_es\b\|Spanish" vigil tests scripts` must come back empty except comments describing the migration in `vigil/db.py` and its tests.

- [ ] **Step 2: Implement.**
  - `index.html`: delete the `<div class="seg aside" role="group" aria-label="Bulletin language">…</div>` block (keep `panel-head` and its `<h2>`).
  - `feed.js`: delete the `[data-lang]` loop. `main.js`: delete `lang` from `state`, `setLang`, the `lang` hash part and the `hash.get("lang")` line. Remove now-unused CSS for `.seg.aside` only if nothing else uses it (`grep -n "seg" vigil/web/static/css/app.css vigil/web/static/index.html`).
  - `vigil/web/app.py`: `config["disclaimer"] = DISCLAIMER.format(**words)` (one string); check `grep -n "disclaimer" vigil/web/static/js/*.js` for readers of `config.disclaimer` and update them.
  - `vigil/agent/bulletin.py`: delete `DISCLAIMER_ES`.
  - `vigil/gate.py`: prompt item 4 ends "…and describe the scene in English."; drop `description_es` from `GATE_SCHEMA`. `scripts/smoke_test.py`: print only the English description.
  - `vigil/mirror.py` card: "`replay/ep{key}/bulletins/run<N>/`: each bulletin (Markdown and HTML) with its evidence images."
  - `vigil/space.py`: `short_description: Kīlauea webcams to measurements and bulletins`.
  - `deploy/start.sh`, right after the `vigil-mirror pull` line:

```bash
# Bring the live database's schema up to date (vigil/db.py) before the dashboard, which only reads, opens it.
python -c 'from vigil import db; from vigil.settings import Settings; db.connect(Settings.from_env().db_path).close()' || exit 1
```

  - `.interface-design/system.md`: remove the EN/ES toggle from the component list.

- [ ] **Step 3: Run the whole suite; it passes.**

- [ ] **Step 4: Commit.**

```bash
git add vigil/web/static/index.html vigil/web/static/js/feed.js vigil/web/static/js/main.js vigil/web/app.py vigil/agent/bulletin.py vigil/gate.py vigil/mirror.py vigil/space.py scripts/smoke_test.py deploy/start.sh .interface-design/system.md tests/test_web_app.py tests/test_web_static.py tests/test_gate.py tests/test_mirror.py tests/test_space.py tests/test_deploy.py
git commit -m "Drop the dashboard's language toggle and the last Spanish, and migrate the live database before the dashboard starts"
```

(Add `vigil/web/static/css/app.css` if it changed.)

### Task 6: Review Tasks 3–5 (reviewer)

- [ ] **Step 1:** Send the `reviewer` agent Tasks 3–5's text, BASE (the commit before Task 3) and HEAD. Ask it to check also: that every stored bilingual shape the migration rewrites is covered by a test; that the dashboard's replay of a migrated episode 55 database loads (build a scene on a copy of `data/replay/ep55/vigil.sqlite` migrated with `db.connect`, call `views.bulletins` and `views.alerts`); that no published path still emits Spanish.
- [ ] **Step 2:** Send CHANGES_REQUIRED findings to the same implementer with SendMessage; re-review.

### Task 7: Re-render the stored outputs and refresh the mirror (orchestrator, inline)

**Files:**
- Create: `scripts/republish_bulletins.py`

- [ ] **Step 1: Back up the local databases** (git-ignored):

```bash
mkdir -p data/backup/pre-phase9
cp data/vigil.sqlite data/backup/pre-phase9/vigil.sqlite
cp data/replay/ep55/vigil.sqlite data/backup/pre-phase9/ep55.sqlite
```

- [ ] **Step 2: Write `scripts/republish_bulletins.py`:**

```python
"""Re-render every bulletin stored in a database into its published folder (vigil.agent.render.publish), for
example after the bulletins became English only:

    python scripts/republish_bulletins.py --db data/replay/ep55/vigil.sqlite --out data/replay/ep55/bulletins
"""

from __future__ import annotations

import argparse
from contextlib import closing
from pathlib import Path

from vigil import db
from vigil.agent.bulletin import load_bulletin
from vigil.agent.render import publish
from vigil.settings import Settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="the bulletins folder, inside the data dir")
    args = parser.parse_args(argv)
    data_dir = Settings.from_env().data_dir
    with closing(db.connect(args.db)) as conn:
        ids = [row[0] for row in conn.execute("SELECT id FROM bulletins ORDER BY id")]
        for bulletin_id in ids:
            print(publish(load_bulletin(conn, bulletin_id), data_dir, args.out))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Measure K2cam in the replay database too** (so the replay's drum and comparison show the fountain; free):

```bash
DB_PATH=data/replay/ep55/vigil.sqlite .venv/Scripts/vigil-measure.exe --camera kilauea-k2 --start 2026-10-17T13:00Z --end 2026-10-17T19:30Z
```

- [ ] **Step 4: Re-render and regenerate** (no Meta API call: every tick is stored and `spark_phases.json` exists; check first that `replay_ticks` holds 78 rows and `alert_ticks` 390, as now, and afterwards that `api_calls` still holds 243 rows, $1.3739):

```bash
.venv/Scripts/python.exe scripts/republish_bulletins.py --db data/replay/ep55/vigil.sqlite --out data/replay/ep55/bulletins
.venv/Scripts/vigil-replay.exe --episode 55
grep -rl "_es\"\|Titular\|REPETICIÓN" data/replay/ep55 --include=*.json --include=*.md --include=*.html   # expect nothing
```

Also migrate and republish the live local database's bulletins (`--db data/vigil.sqlite --out data/bulletins`).

- [ ] **Step 5: Check the replay in the local dashboard** (`vigil-web`, headless Edge at `#mode=replay&at=2026-10-17T15:00:00Z` and at the end): the bulletin feed in English, no toggle, the K2 fountain on the drum, the comparison tables with fountain rows.

- [ ] **Step 6: Push the mirror** (public dataset, files only; deletes the old `bulletin.en.md`/`.es.md`):

```bash
.venv/Scripts/vigil-mirror.exe push --episode 55 --repo facurie/volcano-vigil-ep55
```

- [ ] **Step 7: Commit the script.**

```bash
git add scripts/republish_bulletins.py
git commit -m "Add a script that re-renders stored bulletins, used to republish episode 55 in English"
```

### Task 8: Final README and docs (orchestrator, inline)

**Files:** `README.md`, `DATA_SOURCES.md` (only if it mentions Spanish), `docs/PLAN.md` (goal line: "cited English bulletins")

- [ ] **Step 1: Read the Space's ledger** (DEPLOY.md, "Operate") for the live spend to date: `SELECT ROUND(SUM(cost_usd), 2), MIN(called_at) FROM api_calls`.
- [ ] **Step 2: Rewrite the README** with:
  - the pitch in English-only terms; the live URL and the Telegram channel;
  - an updated mermaid diagram: ingest (AshCam / M.jpg) → SQLite → quality gate → SAM 3.1 video tracking → geometry and metrics → Muse Spark agent → checked bulletins; the alerts watcher (local checks → SAM image → Muse Spark confirmation) → alerts → dashboard banner and Telegram; Open-Meteo wind; the replay feeding the same pipeline; the dashboard;
  - "How Meta's models are used": SAM 3.1 video tracking and image looks, Muse Spark gate, agent with nine tools, phases from video, onset confirmation;
  - the validation headline numbers from `docs/VALIDATION.md` (plume peak, 06:02, fountain rows, end, drift, alerts) with a link;
  - how to run: install, `.env`, every `vigil-*` command with a one-line purpose, `vigil-web`, the replay, the tests;
  - "Built during the hackathon" (keep), the disclaimer callout (keep), credits (USGS public domain, Open-Meteo CC BY 4.0, GNIS/3DEP, JPL Horizons, Axis datasheet), and a cost report: per phase from `docs/PLAN.md`'s Budget and the Space's ledger total.
- [ ] **Step 3: Commit.** `git commit -m "Finish the README: diagram, live links, validation, how to run, credits and cost"`.

### Task 9: Code review pass and fixes (reviewers + implementer)

- [ ] **Step 1:** Load `superpowers:requesting-code-review`. Dispatch three `reviewer` agents in parallel, read-only, each over one area of the whole codebase at HEAD, each told the project's accuracy rules (UTC-aware times, nothing after the clock, units, escaping, money through `MetaClient`) and to report only verified defects with a failing scenario:
  1. measurement chain: `geometry.py`, `calibration.py`, `metrics.py`, `wind.py`, `episodes.py`, `scripts/validate_ep55.py`;
  2. agent, bulletins, alerts, pipeline, replay: `agent/*.py`, `alerts.py`, `pipeline.py`, `replay.py`, `phases.py`, `telegram.py`, `db.py`;
  3. ingest, web, deploy: `ingest/*.py`, `gate.py`, `quality.py`, `tracking.py`, `web/*.py`, `web/static/js/*.js`, `persist.py`, `mirror.py`, `space.py`, `deploy/`.
- [ ] **Step 2:** Triage with `superpowers:receiving-code-review`: fix real defects (TDD, one commit each, through an implementer); write down the rejected ones with the reason in the execution notes.

### Task 10: Deploy and verify (orchestrator, inline)

- [ ] **Step 1:** Copy the bucket's database before the migration: `.venv/Scripts/hf.exe buckets cp hf://buckets/facurie/vigil-state/db/vigil.sqlite data/backup/pre-phase9/space.sqlite`.
- [ ] **Step 2:** Push the commits (`git push origin main`), then deploy: `.venv/Scripts/vigil-space.exe deploy --repo facurie/volcano-vigil`.
- [ ] **Step 3:** Verify from the Space log and the public URL: the services start; `/api/bulletins` returns `headline` and no `"es"`; `/api/alerts` the same; the replay at the end shows the fountain rows; the next hourly bulletin is English and verified (read it from `/api/bulletins` after the hour).

### Task 11: Wrap up (orchestrator)

- [ ] Tick Phase 9's boxes in `docs/PLAN.md`; update the "Facts" (calibration, validation, English only) and the Budget line; append execution notes to this plan; commit and push.
- [ ] Update the memory (`volcano-vigil-status.md`, and `user-profile.md`: bulletins are English only now).
- [ ] Ask the user whether to re-post the episode 55 replay alerts in English to the Telegram channel (and delete messages 3–4) for the Phase 10 video.

---

## Execution notes

Session 13, 2026-11-02, 15:00–20:00 UTC. All tasks done except Task 11's last step, which is the user's call. Suite: 717 → 794 tests. Meta API spend: $0.

**Task 1 (K2cam).** As planned: azimuth 188.82 ± 0.81°, tilt +7.07 ± 0.43°, focal 3,428 ± 103 px. Checks, from the SAM fountain boxes of episode 55: the vent lands 3 px below the fountain's foot (row 1850, the boxes' median lowest row) and 166 px (2.8°) left of its axis (column 1836), one sigma of the camera's ±75 m position. Puʻukoaʻe's pixel holds within 2 px on the 07:00, 08:00 and 09:00 HST frames. Deviation from the freeze rule's letter, recorded honestly: the check overlay (Step 3) draws a 50 m scale over the vent, and at 08:00 HST the fountain stands against it, so a height was visible before the commit. Nothing in the preset was changed after that; it is exactly what Step 2 wrote. The plan's worry that two agent-tool tests assume K2cam uncalibrated was wrong: those tests use a synthetic calibration.

**Task 2 (validation).** 5 of 7 rows agree. Fountain: peak 241 ± 14 m against 219 m (+10 %), 06:02 181 ± 13 against 198 (−9 %), 07:00 150 ± 13 against 152 (−2 %), 08:00 129 ± 12 against 91 (+41 %, z 3.0). HVO's own reports of the decline disagree (500 ft at 07:47 in a message, 300 ft by 08:00 in the daily update), which the report says; the comparison rows were not changed. Our series stays at 100–140 m until about 08:50 and drops to 53 m at 09:00. vigil-measure and the script ran from a detached worktree at 69ce90c (`PYTHONPATH` does not beat the editable install; running from the worktree's folder does), so the implementer's edits in progress never touched the databases.

**Tasks 3–5 (English only)**, one implementer, commits 4a3314c, 7b8fcff, fba8679. Review (Task 6): CHANGES_REQUIRED for one important finding: the stored gate answers (`frame_quality.spark_answer`) kept `description_es`, which ships in the public mirror. Fixed by migration step 2 (da3e04d); `SCHEMA_VERSION` is 3 because Telegram's backoff added `alerts.last_attempt_at` as step 3. The reviewer migrated a copy of the real databases from 6 processes at once without trouble.

**Task 7 (stored outputs).** Backups of every local database are in `data/backup/pre-phase9/` (and the Space's, taken just before the deploy). The four local databases are at version 3 with no Spanish left (also scanned for Spanish words). The episode 55 bulletins were re-rendered, K2cam measured in the replay database (385 detections), and `vigil-replay --episode 55` regenerated `timeline.json` and `report.md` with no Meta API call (still 243 calls, $1.3739). The mirror went from 542 to 536 files, with no `.en.md`/`.es.md` left. Re-checked with the stricter rules below, the 7 replay bulletins cite 41 measurements, all verified, and write 75 lengths and areas, all supported.

**Task 8 (README).** Rewritten; also `DATA_SOURCES.md` gained the calibration references (USGS vent release, EPQS/3DEP, GNIS, JPL Horizons, Axis, Patrick et al., OpenStreetMap).

**Task 9 (review).** Three area reviews (`reviewer`, read-only) plus the Task 6 review. Fixed (16 commits):
- measurement: area measured on the vent plane band by band (it was 30–60 % low for K2cam plumes 2–5 km up; top heights bit-identical, pinned by a test), the agent's wind never reads a model hour after its clock, a drift at exactly 90° is "not consistent" everywhere, and the report's drift text names the line of sight to the vent, not the optical axis;
- bulletins: the headline's and body's lengths and areas are now checked against the verified measurements (hyphenated "1.6-km-high" included; a round number's trailing zeros count as rounding), the cited-number tolerance is the tools' rounding only, bearings compare on the circle, and the badge says "every height and area";
- replay: an official value is compared only with a quoted measurement captured inside its window (the 07:30 row used to take the 08:00 bulletin's 07:55 number);
- live robustness: Telegram retries back off 1, 2, 4, 8 minutes, a non-object reply is a TelegramError, an agent run left `running` for 30 min counts as failed, a missing frame file no longer aborts the pipeline step;
- docstrings that promised more than the code (gate staleness, persist, AshCam retries, `/media/`, the loop's budget), "bilingual" in the page and package descriptions, two vacuous test assertions.
- Not fixed, with reasons: `on_vent_plane`'s `across` with a lean (no caller uses it); a `ValueError` from a pixel 80° off the vent (impossible with these fields of view); AshCam does not retry a failed frame once a later one is stored (documented; a persistent checksum failure would loop); `/media/` ignores the replay clock (documented; the UI never links a future image); a late agent run standing in for the next hour, SAM streams that fail after starting logged at $0 (billing unverified), a duplicate Telegram post after a timeout that Telegram accepted, a frame marked seen when the alerts' budget runs out, a corrupt `spark_phases.json`: all rare, noted.

**Extra.** The viewer's readout showed "No plume measured" on K2cam, whose plume runs off the frame, although its fountain is measured; it now shows the fountain top above the vent (0ddc8de), e.g. 224 ± 14 m at 04:58 and 149 ± 13 m at 06:58 HST.

**Task 10 (deploy).** b3ed1aa deployed after the mirror push.
