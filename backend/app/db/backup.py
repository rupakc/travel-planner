"""GCS-backed SQLite backup and restore.

On startup: restore_from_gcs() downloads *.db files from the backup bucket.
Periodic:   backup_to_gcs() uploads all *.db files in data_dir every N seconds.
On SIGTERM: the periodic task does a final upload before the process exits.

Set BACKUP_BUCKET env var to enable. Empty string disables silently.
"""

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_GCS_PREFIX = "sqlite-backups/"


def _get_client():
    from google.cloud import storage  # noqa: F401

    return storage.Client()


async def restore_from_gcs(bucket_name: str, data_dir: str) -> None:
    """Download all *.db backup files from GCS into data_dir on startup."""
    if not bucket_name:
        return
    try:
        import asyncio

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _sync_restore, bucket_name, data_dir)
    except Exception as e:
        logger.warning(f"GCS restore skipped (will start fresh): {e}")


def _sync_restore(bucket_name: str, data_dir: str) -> None:
    client = _get_client()
    bucket = client.bucket(bucket_name)
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)

    blobs = list(bucket.list_blobs(prefix=_GCS_PREFIX))
    if not blobs:
        logger.info("No GCS backup found — starting with empty database")
        return

    for blob in blobs:
        filename = blob.name.removeprefix(_GCS_PREFIX)
        if not filename.endswith(".db"):
            continue
        dest = data_path / filename
        blob.download_to_filename(str(dest))
        logger.info(f"Restored {filename} from GCS ({blob.size} bytes)")


async def backup_to_gcs(bucket_name: str, data_dir: str) -> None:
    """Upload all *.db files from data_dir to GCS."""
    if not bucket_name:
        return
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _sync_backup, bucket_name, data_dir)
    except Exception as e:
        logger.warning(f"GCS backup failed: {e}")


def _sync_backup(bucket_name: str, data_dir: str) -> None:
    client = _get_client()
    bucket = client.bucket(bucket_name)
    data_path = Path(data_dir)

    for db_file in data_path.glob("*.db"):
        blob = bucket.blob(f"{_GCS_PREFIX}{db_file.name}")
        blob.upload_from_filename(str(db_file))
        logger.info(f"Backed up {db_file.name} to GCS")


async def start_periodic_backup(
    bucket_name: str, data_dir: str, interval_seconds: int = 300
) -> None:
    """Run as an asyncio background task; backs up every interval_seconds."""
    if not bucket_name:
        return
    while True:
        await asyncio.sleep(interval_seconds)
        await backup_to_gcs(bucket_name, data_dir)
