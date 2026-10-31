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
