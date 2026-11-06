"""BACKUP_MODE=vm: the persistent disk is authoritative.

- restore from GCS only when the DB file is missing (stray -wal/-shm removed
  first), and only when the data dir carries the provisioning marker;
- never merge, never overwrite an existing DB;
- export only the user tables (no regenerable place data) into a scratch dir,
  upload only when the export's hash changed;
- status for /health.

No network: GCS is an in-memory fake.
"""

import sqlite3
from pathlib import Path

import pytest

from app.db import vm_backup
from app.db.seed_airports import PLACE_VERSION_KEY


class FakeBlob:
    def __init__(self, store: dict, name: str):
        self.store = store
        self.name = name
        self.metadata = None
        self.uploads = 0

    def exists(self):
        return self.name in self.store

    def reload(self):
        if self.name not in self.store:
            from google.cloud.exceptions import NotFound

            raise NotFound("missing")
        self.metadata = dict(self.store[self.name]["metadata"])

    def download_to_filename(self, dest):
        Path(dest).write_bytes(self.store[self.name]["data"])

    def upload_from_filename(self, src, content_type=None):
        self.store[self.name] = {
            "data": Path(src).read_bytes(),
            "metadata": dict(self.metadata or {}),
        }
        self.store.setdefault("_uploads", {"data": b"", "metadata": {}, "n": 0})
        self.store["_uploads"]["n"] += 1


class FakeBucket:
    def __init__(self, store):
        self.store = store

    def blob(self, name):
        return FakeBlob(self.store, name)


class FakeClient:
    def __init__(self, store=None, fail=False):
        self.store = {} if store is None else store
        self.fail = fail

    def bucket(self, name):
        if self.fail:
            raise ConnectionError("gcs down")
        return FakeBucket(self.store)


def uploads(client) -> int:
    return client.store.get("_uploads", {}).get("n", 0)


def make_db(path: Path, users=("alice",), places=3):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,
                            username TEXT UNIQUE NOT NULL);
        CREATE INDEX idx_users_name ON users(username);
        CREATE TABLE plans (id TEXT PRIMARY KEY, username TEXT, body TEXT);
        CREATE TABLE places (geonameid INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE place_names (name_folded TEXT, geonameid INTEGER, tier INTEGER);
        CREATE INDEX idx_place_names_folded ON place_names(name_folded);
        CREATE TABLE admin1 (code TEXT PRIMARY KEY, name TEXT, folded_name TEXT);
        CREATE TABLE features (geonameid INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE feature_names (name_folded TEXT, geonameid INTEGER, tier INTEGER);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        """
    )
    conn.executemany("INSERT INTO users (username) VALUES (?)", [(u,) for u in users])
    conn.execute("INSERT INTO plans VALUES ('p1', 'alice', '{}')")
    conn.executemany(
        "INSERT INTO places VALUES (?, ?)", [(i, f"P{i}") for i in range(places)]
    )
    conn.execute("INSERT INTO meta VALUES (?, 'v9')", (PLACE_VERSION_KEY,))
    conn.execute("INSERT INTO meta VALUES ('other', 'kept')")
    conn.commit()
    conn.close()


@pytest.fixture
def disk(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / vm_backup.MARKER_NAME).write_text("provisioned\n")
    return d


# ── Mount guard ─────────────────────────────────────────────────────────────


def test_mount_guard_refuses_a_dir_without_the_marker(tmp_path):
    with pytest.raises(vm_backup.MountGuardError):
        vm_backup.check_mount_guard(str(tmp_path))


def test_mount_guard_refuses_a_missing_dir(tmp_path):
    with pytest.raises(vm_backup.MountGuardError):
        vm_backup.check_mount_guard(str(tmp_path / "nope"))


def test_mount_guard_accepts_the_marker(disk):
    vm_backup.check_mount_guard(str(disk))


def test_unmounted_dir_never_restores(tmp_path):
    client = FakeClient({vm_backup.BACKUP_OBJECT: {"data": b"x", "metadata": {}}})
    with pytest.raises(vm_backup.MountGuardError):
        vm_backup.restore_if_missing("b", str(tmp_path), client=client)
    assert not (tmp_path / "airports.db").exists()


# ── Restore only if missing ─────────────────────────────────────────────────


def test_existing_db_is_never_overwritten(disk, tmp_path):
    make_db(disk / "airports.db", users=("local",))
    remote = tmp_path / "remote.db"
    make_db(remote, users=("remote", "newer"))
    client = FakeClient(
        {vm_backup.BACKUP_OBJECT: {"data": remote.read_bytes(), "metadata": {}}}
    )
    assert vm_backup.restore_if_missing("b", str(disk), client=client) == "present"
    names = [
        r[0]
        for r in sqlite3.connect(disk / "airports.db").execute(
            "SELECT username FROM users"
        )
    ]
    assert names == ["local"]


def test_missing_db_is_restored_and_stray_wal_shm_removed(disk, tmp_path):
    (disk / "airports.db-wal").write_bytes(b"stale wal frames")
    (disk / "airports.db-shm").write_bytes(b"stale shm")
    src = tmp_path / "src.db"
    make_db(src, users=("alice", "bob"))
    export = tmp_path / "export.db"
    vm_backup.export_user_tables(src, export)
    client = FakeClient(
        {vm_backup.BACKUP_OBJECT: {"data": export.read_bytes(), "metadata": {}}}
    )
    assert vm_backup.restore_if_missing("b", str(disk), client=client) == "restored"
    assert not (disk / "airports.db-wal").exists()
    assert not (disk / "airports.db-shm").exists()
    conn = sqlite3.connect(disk / "airports.db")
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    # No leftover temp download next to the DB
    assert sorted(p.name for p in disk.iterdir()) == sorted(
        ["airports.db", vm_backup.MARKER_NAME]
    )


def test_missing_db_and_no_backup_starts_fresh(disk):
    assert vm_backup.restore_if_missing("b", str(disk), client=FakeClient()) == (
        "no-backup"
    )
    assert not (disk / "airports.db").exists()


def test_missing_db_and_gcs_error_refuses_to_start(disk):
    with pytest.raises(vm_backup.RestoreError):
        vm_backup.restore_if_missing("b", str(disk), client=FakeClient(fail=True))


def test_no_bucket_means_no_restore(disk):
    assert vm_backup.restore_if_missing("", str(disk), client=None) == "disabled"


# ── Export ─────────────────────────────────────────────────────────────────


def test_export_holds_user_tables_only(tmp_path):
    src = tmp_path / "live.db"
    make_db(src)
    out = tmp_path / "out" / "export.db"
    out.parent.mkdir()
    digest = vm_backup.export_user_tables(src, out)
    assert len(digest) == 64
    conn = sqlite3.connect(out)
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"users", "plans", "meta"} <= tables
    assert not tables & {"places", "place_names", "admin1", "features", "feature_names"}
    assert dict(conn.execute("SELECT key, value FROM meta")) == {"other": "kept"}
    indexes = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }
    assert "idx_users_name" in indexes
    assert "idx_place_names_folded" not in indexes
    # AUTOINCREMENT counter survives (ids are never reused after a restore)
    seq = dict(conn.execute("SELECT name, seq FROM sqlite_sequence"))
    assert seq["users"] == 1
    # The live DB is untouched
    assert sqlite3.connect(src).execute("SELECT COUNT(*) FROM places").fetchone()[0]


def test_export_includes_wal_only_commits(tmp_path):
    src = tmp_path / "live.db"
    make_db(src)
    conn = sqlite3.connect(src)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("INSERT INTO users (username) VALUES ('wal-only')")
    conn.commit()  # no checkpoint; connection kept open
    out = tmp_path / "e.db"
    vm_backup.export_user_tables(src, out)
    got = sqlite3.connect(out).execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert got == 2
    conn.close()


def test_export_hash_is_stable_and_tracks_user_changes(tmp_path):
    src = tmp_path / "live.db"
    make_db(src)
    h1 = vm_backup.export_user_tables(src, tmp_path / "a.db")
    h2 = vm_backup.export_user_tables(src, tmp_path / "b.db")
    assert h1 == h2
    # Place data changes do not count as user changes
    conn = sqlite3.connect(src)
    conn.execute("INSERT INTO places VALUES (999, 'New')")
    conn.execute("UPDATE meta SET value='v10' WHERE key=?", (PLACE_VERSION_KEY,))
    conn.commit()
    assert vm_backup.export_user_tables(src, tmp_path / "c.db") == h1
    conn.execute("DELETE FROM plans")
    conn.commit()
    conn.close()
    assert vm_backup.export_user_tables(src, tmp_path / "d.db") != h1


# ── Backup cycle ────────────────────────────────────────────────────────────


def test_backup_uploads_only_when_the_export_changed(disk, tmp_path):
    make_db(disk / "airports.db")
    client = FakeClient()
    state = vm_backup.BackupState(started_at=0.0)
    scratch = tmp_path / "tmpfs"
    scratch.mkdir()
    r1 = vm_backup.backup_once("b", str(disk), str(scratch), state, client, now=10)
    r2 = vm_backup.backup_once("b", str(disk), str(scratch), state, client, now=20)
    assert (r1, r2) == ("uploaded", "unchanged")
    assert uploads(client) == 1
    assert state.last_success == 20
    stored = client.store[vm_backup.BACKUP_OBJECT]
    assert stored["metadata"]["sha256"] == state.last_hash
    conn = sqlite3.connect(disk / "airports.db")
    conn.execute("INSERT INTO users (username) VALUES ('carol')")
    conn.commit()
    conn.close()
    assert (
        vm_backup.backup_once("b", str(disk), str(scratch), state, client, now=30)
        == "uploaded"
    )
    assert uploads(client) == 2
    # The export never lingers in the scratch dir
    assert list(scratch.iterdir()) == []


def test_a_restart_with_unchanged_data_does_not_reupload(disk, tmp_path):
    make_db(disk / "airports.db")
    client = FakeClient()
    vm_backup.backup_once(
        "b", str(disk), str(tmp_path), vm_backup.BackupState(0.0), client, now=1
    )
    fresh = vm_backup.BackupState(0.0)  # new process: hash unknown in memory
    assert (
        vm_backup.backup_once("b", str(disk), str(tmp_path), fresh, client, now=2)
        == "unchanged"
    )
    assert uploads(client) == 1


def test_deleted_rows_stay_deleted_after_a_backup_cycle(disk, tmp_path):
    """No merge: a row deleted locally never comes back from GCS."""
    make_db(disk / "airports.db", users=("alice", "bob"))
    client = FakeClient()
    state = vm_backup.BackupState(0.0)
    vm_backup.backup_once("b", str(disk), str(tmp_path), state, client, now=1)
    conn = sqlite3.connect(disk / "airports.db")
    conn.execute("DELETE FROM users WHERE username='bob'")
    conn.commit()
    conn.close()
    vm_backup.backup_once("b", str(disk), str(tmp_path), state, client, now=2)
    names = [
        r[0]
        for r in sqlite3.connect(disk / "airports.db").execute(
            "SELECT username FROM users"
        )
    ]
    assert names == ["alice"]


def test_backup_failure_is_recorded_not_raised(disk, tmp_path):
    make_db(disk / "airports.db")
    state = vm_backup.BackupState(0.0)
    r = vm_backup.backup_once(
        "b", str(disk), str(tmp_path), state, FakeClient(fail=True), now=5
    )
    assert r == "failed"
    assert state.last_error
    assert state.last_success is None


def test_no_db_yet_is_skipped(disk, tmp_path):
    state = vm_backup.BackupState(0.0)
    assert (
        vm_backup.backup_once("b", str(disk), str(tmp_path), state, FakeClient(), 1)
        == "skipped"
    )


# ── Status for /health ─────────────────────────────────────────────────────


def test_status_ok_while_fresh_and_not_ok_after_failure_or_staleness():
    s = vm_backup.BackupState(started_at=1000.0)
    assert vm_backup.status_of(s, interval=300, now=1100)["ok"] is True
    # Never succeeded and past 3 intervals → not ok
    assert vm_backup.status_of(s, interval=300, now=1000 + 901)["ok"] is False
    s.last_success = 2000.0
    st = vm_backup.status_of(s, interval=300, now=2100)
    assert st["ok"] is True and st["age_s"] == 100
    s.last_error = "boom"
    assert vm_backup.status_of(s, interval=300, now=2100)["ok"] is False


async def test_startup_refuses_an_unmarked_dir_even_without_a_bucket(tmp_path):
    with pytest.raises(vm_backup.MountGuardError):
        await vm_backup.startup("", str(tmp_path))


def test_real_schema_round_trip_reseeds_place_data(client, disk, tmp_path, monkeypatch):
    """Export the app's real DB, restore it on a fresh disk, run the normal
    startup seed: user rows are back and the place data is rebuilt."""
    from app.core.config import settings
    from app.db.database import get_connection
    from app.db.seed_airports import seed
    from app.db.users_db import create_user

    create_user("roundtrip-user", "pw-123456789")
    live = Path(settings.data_dir) / "airports.db"
    export = tmp_path / "export.db"
    vm_backup.export_user_tables(live, export)
    assert export.stat().st_size < live.stat().st_size / 4
    client = FakeClient(
        {vm_backup.BACKUP_OBJECT: {"data": export.read_bytes(), "metadata": {}}}
    )
    assert vm_backup.restore_if_missing("b", str(disk), client=client) == "restored"
    monkeypatch.setattr(settings, "data_dir", str(disk))
    assert seed() is True  # no place-data version in the backup → reseeded
    with get_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM users WHERE username='roundtrip-user'"
        ).fetchone()
        assert conn.execute("SELECT COUNT(*) FROM places").fetchone()[0] > 1000


def test_missing_export_dir_is_a_recorded_failure_not_a_crash(disk, tmp_path):
    make_db(disk / "airports.db")
    state = vm_backup.BackupState(0.0)
    r = vm_backup.backup_once(
        "b", str(disk), str(tmp_path / "gone"), state, FakeClient(), now=1
    )
    assert r == "failed" and state.last_error


async def test_backup_loop_survives_unexpected_exceptions(monkeypatch):
    import asyncio

    calls = []

    def flaky(*args):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("tmpfs full")
        return "unchanged"

    monkeypatch.setattr(vm_backup, "backup_once", flaky)
    monkeypatch.setattr(vm_backup, "_state", vm_backup.BackupState(0.0))
    task = asyncio.create_task(vm_backup._loop("b", "/d", "/t", 0.01))
    await asyncio.sleep(0.1)
    assert len(calls) >= 2 and not task.done()
    assert vm_backup._state.last_error and "tmpfs full" in vm_backup._state.last_error
    task.cancel()
