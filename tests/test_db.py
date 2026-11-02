import json
import sqlite3

import pytest

from vigil import db


def test_a_read_only_connection_reads_rows_but_cannot_write(tmp_path):
    path = tmp_path / "vigil.sqlite"
    db.connect(path).close()
    conn = db.connect_readonly(path)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM frames").fetchone()["n"] == 0
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM frames")
    finally:
        conn.close()


def test_a_read_only_connection_never_creates_a_database(tmp_path):
    with pytest.raises(FileNotFoundError):
        db.connect_readonly(tmp_path / "missing.sqlite")
    assert not (tmp_path / "missing.sqlite").exists()


def test_the_schema_has_the_alert_tables(conn):
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert {"alert_checks", "alerts", "alert_ticks"} <= tables
    columns = {row[1] for row in conn.execute("PRAGMA table_info(alert_checks)")}
    assert {"box_left", "box_top", "box_right", "box_bottom", "mask_rle", "size", "episode", "spark"} <= columns


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
