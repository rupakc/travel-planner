"""GCS-backed SQLite backup and restore — generation-safe, merge-on-conflict.

Startup:  restore_from_gcs() downloads the current *.db files and records the
          GCS object generation for each file.

Periodic: backup_to_gcs() is called every interval_seconds.  Before uploading
          it checks whether GCS has advanced to a newer generation since our
          restore — which happens when the old instance completed its SIGTERM
          backup after we already started.  In that case the newer GCS data is
          merged into the local DB (INSERT OR IGNORE) so no rows are lost, and
          the merged result is then uploaded.  This prevents a newly-deployed
          instance from overwriting the retiring instance's final backup with
          its older restore snapshot.

SIGTERM:  backup_to_gcs(force=True) is called from the FastAPI lifespan
          cleanup.  force=True skips the generation check and always uploads
          the current local state — the dying instance always wins the race
          because it holds the authoritative data right up to shutdown.

GCS bucket versioning (enabled via Terraform) provides an additional safety
net: even if a bad upload occurs the previous 10 object versions can be
recovered manually.

Set BACKUP_BUCKET env var to enable.  Empty string disables silently.
"""

import asyncio
import logging
import sqlite3
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_GCS_PREFIX = "sqlite-backups/"

# GCS object generation recorded at the time of our last restore (or upload).
# If the GCS generation has changed since we restored, another instance wrote
# a newer backup and we must not overwrite it blindly.
_restore_generation: dict[str, int] = {}

# Wall-clock time when this process started.  Used to implement a "startup
# window" during which we skip periodic backups if GCS is ahead (the old
# instance is likely still in the middle of its SIGTERM backup).
_process_start: float = time.time()
_STARTUP_WINDOW_S: float = 150.0  # seconds — safely covers deployment overlap


def _get_client():
    from google.cloud import storage

    return storage.Client()


# ── Restore ────────────────────────────────────────────────────────────────────


async def restore_from_gcs(bucket_name: str, data_dir: str) -> None:
    """Download all *.db backup files from GCS into data_dir on startup."""
    if not bucket_name:
        return
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _sync_restore, bucket_name, data_dir)
    except Exception as e:
        logger.warning("GCS restore skipped (will start fresh): %s", e)


def _sync_restore(bucket_name: str, data_dir: str) -> None:
    global _restore_generation
    client = _get_client()
    bucket = client.bucket(bucket_name)
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)

    blobs = [b for b in bucket.list_blobs(prefix=_GCS_PREFIX) if b.name.endswith(".db")]
    if not blobs:
        logger.info("No GCS backup found — starting with empty database")
        return

    for blob in blobs:
        filename = blob.name.removeprefix(_GCS_PREFIX)
        dest = data_path / filename
        blob.download_to_filename(str(dest))
        _restore_generation[filename] = blob.generation
        logger.info(
            "Restored %s from GCS (%s bytes, gen=%s)",
            filename,
            blob.size,
            blob.generation,
        )


# ── Backup ─────────────────────────────────────────────────────────────────────


async def backup_to_gcs(
    bucket_name: str, data_dir: str, *, force: bool = False
) -> None:
    """Upload local *.db files to GCS.

    force=True  — always upload regardless of GCS generation (used for SIGTERM
                  backups; the dying instance holds the most authoritative data).
    force=False — generation-safe: merges any newer GCS data before uploading
                  to avoid overwriting a newer backup with a stale restore.
    """
    if not bucket_name:
        return
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _sync_backup, bucket_name, data_dir, force)
    except Exception as e:
        logger.warning("GCS backup failed: %s", e)


def _sync_backup(bucket_name: str, data_dir: str, force: bool) -> None:
    from google.cloud.exceptions import NotFound

    global _restore_generation
    client = _get_client()
    bucket = client.bucket(bucket_name)
    data_path = Path(data_dir)
    elapsed = time.time() - _process_start

    for db_file in data_path.glob("*.db"):
        name = db_file.name
        blob = bucket.blob(f"{_GCS_PREFIX}{name}")

        if not force:
            # Check whether GCS has been updated since we last restored.
            try:
                blob.reload()
                gcs_gen = blob.generation
            except NotFound:
                gcs_gen = None  # first-ever upload; safe to proceed

            our_gen = _restore_generation.get(name)

            if gcs_gen is not None and gcs_gen != our_gen:
                # GCS is ahead — another instance (the retiring one) uploaded
                # after our restore.
                if elapsed < _STARTUP_WINDOW_S:
                    # Still in the startup window.  The old instance may still
                    # be in the middle of its SIGTERM backup.  Defer.
                    logger.info(
                        "%s: GCS gen=%s, our restore gen=%s, elapsed=%.0fs "
                        "(within startup window) — deferring backup",
                        name,
                        gcs_gen,
                        our_gen,
                        elapsed,
                    )
                    continue

                # Outside the startup window — old instance has definitely
                # finished.  Merge its final backup into our local DB so we
                # don't lose any rows it wrote, then upload the merged result.
                logger.info(
                    "%s: GCS gen=%s > restore gen=%s (%.0fs since start) "
                    "— merging GCS data before upload",
                    name,
                    gcs_gen,
                    our_gen,
                    elapsed,
                )
                _merge_gcs_into_local(blob, db_file)
                _restore_generation[name] = gcs_gen
                # Fall through to upload the merged DB.

        # Upload the local (possibly just merged) file.
        blob.upload_from_filename(str(db_file))
        blob.reload()  # refresh generation after upload
        _restore_generation[name] = blob.generation
        logger.info("Backed up %s to GCS (gen=%s)", name, blob.generation)


def _merge_gcs_into_local(blob, local_path: Path) -> None:
    """Download blob to a temp file and INSERT OR IGNORE all its rows into local_path.

    INSERT OR IGNORE means:
    - Rows that exist only in GCS are added to local (we gain the old instance's data).
    - Rows that exist only locally are kept (we keep data written since our restore).
    - Conflicts (same primary key in both) favour the local version.

    This is safe for all tables in our schema: users, feedback, plans, preferences,
    airports, nationalities all use globally-unique primary keys (UUIDs or IATA codes),
    so genuine conflicts are extremely rare.
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            blob.download_to_filename(str(tmp_path))
            conn = sqlite3.connect(str(local_path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(f"ATTACH DATABASE '{tmp_path}' AS gcs_db")

            tables = conn.execute(
                "SELECT name FROM gcs_db.sqlite_master WHERE type='table'"
            ).fetchall()

            merged_total = 0
            for (table,) in tables:
                try:
                    cur = conn.execute(
                        f"INSERT OR IGNORE INTO main.{table} SELECT * FROM gcs_db.{table}"
                    )
                    merged_total += cur.rowcount
                except Exception as exc:
                    logger.warning("Merge skipped table %s: %s", table, exc)

            conn.commit()
            conn.execute("DETACH DATABASE gcs_db")
            conn.close()
            logger.info(
                "Merged GCS backup into %s (%d new rows)", local_path.name, merged_total
            )
        finally:
            tmp_path.unlink(missing_ok=True)
    except Exception as e:
        logger.warning("GCS merge failed for %s: %s", local_path.name, e)


# ── Periodic task ──────────────────────────────────────────────────────────────


async def start_periodic_backup(
    bucket_name: str, data_dir: str, interval_seconds: int = 60
) -> None:
    """Asyncio background task: backs up every interval_seconds (force=False)."""
    if not bucket_name:
        return
    while True:
        await asyncio.sleep(interval_seconds)
        await backup_to_gcs(bucket_name, data_dir)  # force=False: generation-safe
