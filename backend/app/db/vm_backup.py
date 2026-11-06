"""Backups for a single always-on VM (``BACKUP_MODE=vm``).

The persistent disk is the source of truth; GCS only holds a copy for when
the disk itself is lost:

- **Restore only if missing.** At start, the DB is downloaded from GCS only
  when ``airports.db`` does not exist (a fresh disk). Stray ``-wal`` /
  ``-shm`` files are deleted first so SQLite can't replay old frames into
  the restored file. An existing DB is never touched, and nothing is ever
  merged (a merge would bring back deleted watches, devices, plans and
  taste resets).
- **Mount guard.** Restore and backup run only when ``DATA_DIR`` carries the
  marker file written when the disk was provisioned. An unmounted or
  mistyped path would otherwise look like "DB missing", restore a stale copy
  into the wrong place and later overwrite the good backup.
- **User tables only.** Every few minutes the tables that aren't
  regenerable place data are exported into a scratch directory (a tmpfs in
  production, so nothing hits the slow disk) and uploaded only when the
  export's SHA-256 differs from the last upload. The hash is kept in the
  object's metadata, so a restart with unchanged data uploads nothing.
- **Visible.** :func:`status` feeds ``/health`` (``backup_ok``), which the
  uptime check content-matches.

A restored DB has no place data and no place-data version, so the normal
startup seed rebuilds it.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .seed_airports import PLACE_TABLES, PLACE_VERSION_KEY

logger = logging.getLogger(__name__)

DB_NAME = "airports.db"
BACKUP_OBJECT = "sqlite-backups/airports.db"
MARKER_NAME = ".voyager-data-disk"
HASH_KEY = "sha256"
STALE_INTERVALS = 3  # /health turns not-ok after this many missed cycles


class MountGuardError(RuntimeError):
    """DATA_DIR is not the provisioned persistent disk."""


class RestoreError(RuntimeError):
    """The DB is missing and the backup could not be fetched."""


@dataclass
class BackupState:
    started_at: float
    last_success: float | None = None
    last_upload: float | None = None
    last_hash: str | None = None
    last_error: str | None = None
    uploads: int = 0
    _remote_hash_checked: bool = field(default=False, repr=False)


_state: BackupState | None = None
_interval: int = 300


def _get_client():
    from google.cloud import storage

    return storage.Client()


# ── Mount guard / restore ───────────────────────────────────────────────────


def check_mount_guard(data_dir: str) -> None:
    marker = Path(data_dir) / MARKER_NAME
    if not marker.is_file():
        raise MountGuardError(
            f"{data_dir} has no {MARKER_NAME}: refusing to use it as the data "
            "disk (is the persistent disk mounted?)"
        )


def restore_if_missing(bucket_name: str, data_dir: str, *, client=None) -> str:
    """Returns "disabled", "present", "restored" or "no-backup".

    Raises MountGuardError when DATA_DIR isn't the marked disk, and
    RestoreError when the DB is missing and GCS can't be read (starting
    empty would later overwrite the real backup).
    """
    if not bucket_name:
        return "disabled"
    check_mount_guard(data_dir)
    data = Path(data_dir)
    db = data / DB_NAME
    if db.exists():
        return "present"
    for suffix in ("-wal", "-shm", "-journal"):
        stray = data / f"{DB_NAME}{suffix}"
        if stray.exists():
            logger.warning("Removing stray %s before restore", stray.name)
            stray.unlink()
    try:
        client = client or _get_client()
        blob = client.bucket(bucket_name).blob(BACKUP_OBJECT)
        if not blob.exists():
            logger.info("No backup in gs://%s: starting fresh", bucket_name)
            return "no-backup"
        fd, tmp_name = tempfile.mkstemp(prefix=".restore-", dir=data)
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            blob.download_to_filename(str(tmp))
            _verify_sqlite(tmp)
            os.replace(tmp, db)
        finally:
            tmp.unlink(missing_ok=True)
    except Exception as exc:
        raise RestoreError(f"restore from gs://{bucket_name} failed: {exc}") from exc
    logger.info("Restored %s from gs://%s/%s", DB_NAME, bucket_name, BACKUP_OBJECT)
    return "restored"


def _verify_sqlite(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute("PRAGMA quick_check").fetchone()
        if not row or row[0] != "ok":
            raise RestoreError(f"downloaded backup failed quick_check: {row}")
    finally:
        conn.close()


# ── Export ─────────────────────────────────────────────────────────────────


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def export_user_tables(db_path: Path | str, out_path: Path | str) -> str:
    """Write every non-place table (schema, indexes, rows, AUTOINCREMENT
    counters) of ``db_path`` to a new SQLite file ``out_path``, from one
    consistent read snapshot. Returns the SHA-256 of the logical content
    (schema + rows), which doesn't depend on SQLite's file layout."""
    out = Path(out_path)
    tmp = out.with_name(out.name + ".part")
    tmp.unlink(missing_ok=True)
    skip = set(PLACE_TABLES)
    digest = hashlib.sha256()
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(tmp))
    try:
        src.execute("BEGIN")  # one snapshot for every table (WAL reader)
        objects = src.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
            "ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 "
            "ELSE 2 END, name"
        ).fetchall()
        tables = [o for o in objects if o[0] == "table" and o[1] not in skip]
        others = [o for o in objects if o[0] != "table" and o[2] not in skip]
        dst.execute("BEGIN")
        for _type, name, _tbl, sql in tables:
            dst.execute(sql)
            digest.update(b"T\0" + sql.encode() + b"\0")
            query = f"SELECT * FROM {_q(name)}"  # nosec B608 — sqlite_master names
            params: tuple = ()
            if name == "meta":
                query += " WHERE key != ?"
                params = (PLACE_VERSION_KEY,)
            cur = src.execute(query, params)
            ncols = len(cur.description)
            insert = f"INSERT INTO {_q(name)} VALUES ({', '.join('?' * ncols)})"  # nosec B608
            while rows := cur.fetchmany(500):
                for row in rows:
                    digest.update(repr(row).encode() + b"\n")
                dst.executemany(insert, rows)
        for _type, _name, _tbl, sql in others:
            dst.execute(sql)
            digest.update(b"O\0" + sql.encode() + b"\0")
        has_seq = src.execute(
            "SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'"
        ).fetchone()
        if has_seq:
            seq = [
                r
                for r in src.execute(
                    "SELECT name, seq FROM sqlite_sequence ORDER BY name"
                )
                if r[0] not in skip
            ]
            if dst.execute(
                "SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'"
            ).fetchone():
                dst.execute("DELETE FROM sqlite_sequence")
                dst.executemany("INSERT INTO sqlite_sequence VALUES (?, ?)", seq)
            digest.update(repr(seq).encode())
        dst.commit()
        src.rollback()
    except BaseException:
        dst.close()
        tmp.unlink(missing_ok=True)
        raise
    finally:
        src.close()
    dst.close()
    os.replace(tmp, out)
    return digest.hexdigest()


# ── Backup cycle ────────────────────────────────────────────────────────────


def backup_once(
    bucket_name: str,
    data_dir: str,
    export_dir: str,
    state: BackupState,
    client=None,
    now: float | None = None,
) -> str:
    """One cycle: export, compare hashes, upload if changed. Returns
    "uploaded", "unchanged", "skipped" (no DB yet) or "failed"; never raises."""
    now = time.time() if now is None else now
    db = Path(data_dir) / DB_NAME
    if not db.exists():
        return "skipped"
    fd, name = tempfile.mkstemp(prefix="voyager-export-", suffix=".db", dir=export_dir)
    os.close(fd)
    export = Path(name)
    try:
        check_mount_guard(data_dir)
        digest = export_user_tables(db, export)
        client = client or _get_client()
        blob = client.bucket(bucket_name).blob(BACKUP_OBJECT)
        if state.last_hash is None and not state._remote_hash_checked:
            state._remote_hash_checked = True
            try:
                blob.reload()
                state.last_hash = (blob.metadata or {}).get(HASH_KEY)
            except Exception:  # noqa: BLE001 — no object yet / unreadable
                state.last_hash = None
        if digest == state.last_hash:
            result = "unchanged"
        else:
            blob.metadata = {HASH_KEY: digest}
            blob.upload_from_filename(str(export), content_type="application/x-sqlite3")
            state.last_hash = digest
            state.last_upload = now
            state.uploads += 1
            result = "uploaded"
            logger.info(
                "Backed up user tables to gs://%s (%s)", bucket_name, digest[:12]
            )
        state.last_success = now
        state.last_error = None
        return result
    except Exception as exc:  # noqa: BLE001 — reported via /health
        state.last_error = f"{type(exc).__name__}: {exc}"
        logger.warning("GCS backup failed: %s", state.last_error)
        return "failed"
    finally:
        export.unlink(missing_ok=True)
        Path(str(export) + ".part").unlink(missing_ok=True)


# ── Status ─────────────────────────────────────────────────────────────────


def status_of(state: BackupState, *, interval: int, now: float) -> dict:
    since = state.last_success if state.last_success is not None else state.started_at
    fresh = now - since <= STALE_INTERVALS * interval
    return {
        "mode": "vm",
        "ok": state.last_error is None and fresh,
        "last_success": state.last_success,
        "age_s": None if state.last_success is None else int(now - state.last_success),
        "uploads": state.uploads,
        "error": state.last_error,
    }


def status() -> dict | None:
    """Backup status for /health, or None when VM backups aren't running."""
    if _state is None:
        return None
    return status_of(_state, interval=_interval, now=time.time())


# ── Lifespan hooks ─────────────────────────────────────────────────────────


async def startup(bucket_name: str, data_dir: str) -> str:
    """Mount guard + restore-if-missing, off the event loop. Raises (the
    app must not start) on a guard or restore failure."""
    check_mount_guard(data_dir)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, restore_if_missing, bucket_name, data_dir)


def start(bucket_name: str, data_dir: str, export_dir: str, interval: int):
    """Begin the periodic backup loop; returns its task (None if disabled)."""
    global _state, _interval
    if not bucket_name:
        return None
    _interval = interval
    _state = BackupState(started_at=time.time())
    return asyncio.create_task(_loop(bucket_name, data_dir, export_dir, interval))


async def _loop(bucket_name: str, data_dir: str, export_dir: str, interval: int):
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(interval)
        await loop.run_in_executor(
            None, backup_once, bucket_name, data_dir, export_dir, _state
        )


async def stop(task, bucket_name: str, data_dir: str, export_dir: str, timeout=10.0):
    """Clean shutdown: stop the loop and flush once (upload only if changed)."""
    if task is None or _state is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None, backup_once, bucket_name, data_dir, export_dir, _state
            ),
            timeout=timeout,
        )
        logger.info("Shutdown backup: %s", result)
    except TimeoutError:
        logger.warning("Shutdown backup timed out after %.0fs", timeout)
