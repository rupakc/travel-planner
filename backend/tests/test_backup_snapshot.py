"""The GCS backup must capture WAL-only commits (regression: feedback rows
written since the last checkpoint were missing from uploaded backups)."""

import sqlite3

from app.db.backup import _snapshot_db


def test_snapshot_includes_wal_only_data(tmp_path):
    db = tmp_path / "live.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("CREATE TABLE feedback (id INTEGER PRIMARY KEY, msg TEXT)")
    for i in range(25):
        conn.execute("INSERT INTO feedback (msg) VALUES (?)", (f"fb{i}",))
    conn.commit()
    # No checkpoint has run — the raw main file would miss these rows
    snap = _snapshot_db(db)
    try:
        got = (
            sqlite3.connect(snap).execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        )
        assert got == 25
    finally:
        snap.unlink()
    conn.close()
