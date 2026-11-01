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
