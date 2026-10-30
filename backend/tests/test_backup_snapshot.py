"""The GCS backup must capture WAL-only commits (regression: feedback rows
written since the last checkpoint were missing from uploaded backups)."""

import sqlite3
from pathlib import Path

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


# ── Regenerable place data is never backed up or merged ────────────────────


def _db_with_place_data(path, *, user_rows, version="v1"):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE feedback (id INTEGER PRIMARY KEY, msg TEXT);
        CREATE TABLE places (geonameid INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE place_names (name_folded TEXT, geonameid INTEGER, tier INTEGER);
        CREATE TABLE admin1 (code TEXT PRIMARY KEY, name TEXT, folded_name TEXT);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        """
    )
    conn.executemany("INSERT INTO feedback VALUES (?, ?)", user_rows)
    conn.execute("INSERT INTO places VALUES (1, 'Berlin')")
    conn.execute("INSERT INTO place_names VALUES ('berlin', 1, 0)")
    conn.execute("INSERT INTO admin1 VALUES ('DE.16', 'Berlin', 'berlin')")
    conn.execute("INSERT INTO meta VALUES ('place_data_version', ?)", (version,))
    conn.execute("INSERT INTO meta VALUES ('other', 'kept')")
    conn.commit()
    conn.close()


def _counts(path):
    conn = sqlite3.connect(path)
    try:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # nosec B608
            for t in ("feedback", "places", "place_names", "admin1", "meta")
        }
    finally:
        conn.close()


def test_snapshot_excludes_place_tables_and_version(tmp_path):
    db = tmp_path / "airports.db"
    _db_with_place_data(db, user_rows=[(1, "hi")])
    snap = _snapshot_db(db)
    try:
        assert _counts(snap) == {
            "feedback": 1,
            "places": 0,
            "place_names": 0,
            "admin1": 0,
            "meta": 1,
        }
        conn = sqlite3.connect(snap)
        assert conn.execute("SELECT key FROM meta").fetchall() == [("other",)]
        conn.close()
    finally:
        snap.unlink()
    # The live DB is untouched.
    assert _counts(db)["places"] == 1


def test_merge_skips_place_tables_and_version(tmp_path):
    from app.db.backup import _merge_gcs_into_local

    remote = tmp_path / "remote.db"
    _db_with_place_data(remote, user_rows=[(2, "remote")], version="old")
    conn = sqlite3.connect(remote)
    conn.execute("INSERT INTO places VALUES (2, 'Stale')")
    conn.execute("INSERT INTO meta VALUES ('remote-only', 'x')")
    conn.commit()
    conn.close()
    local = tmp_path / "local.db"
    _db_with_place_data(local, user_rows=[(1, "local")], version="new")

    class _Blob:
        def download_to_filename(self, dest):
            Path(dest).write_bytes(remote.read_bytes())

    _merge_gcs_into_local(_Blob(), local)
    conn = sqlite3.connect(local)
    try:
        assert conn.execute("SELECT id FROM feedback ORDER BY id").fetchall() == [
            (1,),
            (2,),
        ]
        assert conn.execute("SELECT geonameid FROM places").fetchall() == [(1,)]
        assert dict(conn.execute("SELECT key, value FROM meta").fetchall()) == {
            "place_data_version": "new",
            "other": "kept",
            "remote-only": "x",
        }
    finally:
        conn.close()


def test_merge_of_an_old_schema_backup_keeps_its_airport_rows(tmp_path):
    """A backup taken before the airports table gained region / type_rank /
    scheduled still merges: columns are named, not positional."""
    from app.db.backup import _merge_gcs_into_local

    remote = tmp_path / "remote.db"
    conn = sqlite3.connect(remote)
    conn.executescript("""
        CREATE TABLE airports (id INTEGER PRIMARY KEY, iata_code TEXT UNIQUE,
            icao_code TEXT, name TEXT, city TEXT, country TEXT,
            country_code TEXT, latitude REAL, longitude REAL);
        INSERT INTO airports VALUES (7, 'XWB', NULL, 'Webtown Airport',
            'Webtown', 'Freedonia', NULL, NULL, NULL);
    """)
    conn.commit()
    conn.close()
    local = tmp_path / "local.db"
    conn = sqlite3.connect(local)
    conn.executescript("""
        CREATE TABLE airports (id INTEGER PRIMARY KEY, iata_code TEXT UNIQUE,
            icao_code TEXT, name TEXT, city TEXT, country TEXT,
            country_code TEXT, latitude REAL, longitude REAL, region TEXT,
            type_rank INTEGER, scheduled INTEGER DEFAULT 1);
    """)
    conn.commit()
    conn.close()

    class _Blob:
        def download_to_filename(self, dest):
            Path(dest).write_bytes(remote.read_bytes())

    _merge_gcs_into_local(_Blob(), local)
    conn = sqlite3.connect(local)
    try:
        assert conn.execute(
            "SELECT iata_code, city, scheduled FROM airports"
        ).fetchall() == [("XWB", "Webtown", 1)]
    finally:
        conn.close()
