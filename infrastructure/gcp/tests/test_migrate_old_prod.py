"""Old-prod migration on a synthetic export shaped like the real one (old
column sets, a bloated sqlite_sequence, place/airport tables to drop).
Run: python3 -m pytest infrastructure/gcp/tests -q"""

import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "migrate_old_prod.py"
_spec = importlib.util.spec_from_file_location("migrate_old_prod", _PATH)
mig = importlib.util.module_from_spec(_spec)
sys.modules["migrate_old_prod"] = mig
_spec.loader.exec_module(mig)


def make_export(path: Path, *, seq_rows=5000):
    c = sqlite3.connect(path)
    c.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL, email TEXT, password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0, is_first_login INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT);
        CREATE TABLE plans (id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            name TEXT, search_data TEXT, selections TEXT, created_at TEXT,
            updated_at TEXT, share_token TEXT);
        CREATE TABLE preferences (username TEXT PRIMARY KEY, budget_category TEXT,
            nationality TEXT, current_residence TEXT, residence_permits TEXT,
            existing_visas TEXT, interests TEXT, num_travelers INTEGER,
            updated_at TEXT, visited_destinations TEXT, adults INTEGER,
            children INTEGER, seniors INTEGER, infants INTEGER,
            accessibility_needs TEXT);
        CREATE TABLE taste_signals (id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT, signal_type TEXT, value TEXT, weight REAL, created_at TEXT);
        CREATE TABLE feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT,
            page TEXT, rating INTEGER, category TEXT, message TEXT, metadata TEXT,
            created_at TEXT);
        CREATE TABLE airports (id INTEGER PRIMARY KEY AUTOINCREMENT,
            iata_code TEXT UNIQUE NOT NULL, name TEXT);
        CREATE TABLE nationalities (id INTEGER PRIMARY KEY, nationality TEXT);
        """
    )
    for i in range(3):
        c.execute(
            "INSERT INTO users (username, email, password_hash, is_admin, created_at)"
            " VALUES (?, ?, ?, ?, '2026-01-01')",
            (f"user{i}", f"u{i}@example.test", f"$2b$12$hash{i}", int(i == 0)),
        )
    c.execute("INSERT INTO plans VALUES (7,'user1','Tokyo','{}','{}','t','t',NULL)")
    c.execute(
        "INSERT INTO preferences (username, nationality, visited_destinations)"
        " VALUES ('user1', 'German', '[\"Paris\"]')"
    )
    c.executemany(
        "INSERT INTO taste_signals (username, signal_type, value, weight)"
        " VALUES ('user1', 'like', ?, 1.0)",
        [(f"v{i}",) for i in range(4)],
    )
    c.execute("INSERT INTO feedback (username, page, rating) VALUES ('user2','x',5)")
    c.execute("INSERT INTO airports (iata_code, name) VALUES ('BER', 'Berlin')")
    # The real export's 41.9 M sqlite_sequence rows, in miniature
    c.executemany(
        "INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)",
        [("users", i % 7) for i in range(seq_rows)] + [("taste_signals", 40)],
    )
    c.commit()
    c.close()


@pytest.fixture
def export(tmp_path):
    p = tmp_path / "export" / "airports.db"
    p.parent.mkdir()
    make_export(p)
    return p


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_migration_keeps_users_and_their_data_only(export, tmp_path):
    before = sha(export)
    out = tmp_path / "out" / "airports.db"
    report = mig.migrate(export, out)
    assert sha(export) == before  # export never modified
    assert not Path(str(export) + "-shm").exists()  # immutable: no sidecars
    c = sqlite3.connect(out)
    tables = {
        r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"users", "plans", "preferences", "taste_signals", "feedback"} <= tables
    assert "airports" not in tables and "nationalities" not in tables
    assert c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
    assert c.execute(
        "SELECT password_hash, is_admin FROM users WHERE username='user0'"
    ).fetchone() == ("$2b$12$hash0", 1)
    # Current schema (recent_searches exists, empty: not in the export)
    assert c.execute("SELECT COUNT(*) FROM recent_searches").fetchone()[0] == 0
    # sqlite_sequence collapsed to one row per table, at the true maximum
    seq = dict(c.execute("SELECT name, seq FROM sqlite_sequence"))
    assert seq["users"] == 6 and seq["taste_signals"] == 40
    assert seq["plans"] == 7  # max id when the export had no counter row
    assert c.execute("SELECT COUNT(*) FROM sqlite_sequence").fetchone()[0] == len(seq)
    t = {row["table"]: row for row in report["tables"]}
    assert t["users"]["old_rows"] == t["users"]["new_rows"] == 3
    assert t["taste_signals"]["new_rows"] == 4
    assert t["recent_searches"]["status"] == "absent in export"
    assert t["preferences"]["dropped_columns"] == {"visited_destinations": 1}
    assert report["ok"] is True
    assert report["export_sha256_before"] == report["export_sha256_after"] == before


def test_report_files_hold_counts_not_user_data(export, tmp_path):
    out = tmp_path / "o" / "airports.db"
    mig.main(["--export", str(export), "--out", str(out)])
    md = (out.parent / "migration-report.md").read_text()
    js = json.loads((out.parent / "migration-report.json").read_text())
    assert "users" in md and js["ok"] is True
    assert "u1@example.test" not in md and "hash" not in md.replace("sha256", "")


def test_refuses_to_overwrite_existing_output(export, tmp_path):
    out = tmp_path / "airports.db"
    out.write_text("x")
    with pytest.raises(SystemExit):
        mig.main(["--export", str(export), "--out", str(out)])


def test_refuses_the_export_as_output(export):
    with pytest.raises(SystemExit):
        mig.main(["--export", str(export), "--out", str(export)])


def test_count_mismatch_fails(export, tmp_path, monkeypatch):
    real = mig._count

    def lying(conn, schema, table):
        n = real(conn, schema, table)
        return n + 1 if (schema, table) == ("old", "plans") else n

    monkeypatch.setattr(mig, "_count", lying)
    report = mig.migrate(export, tmp_path / "m" / "airports.db")
    assert report["ok"] is False
    with pytest.raises(SystemExit):
        mig.main(
            ["--export", str(export), "--out", str(tmp_path / "n" / "airports.db")]
        )
