"""Per-trip snapshot of the plan's section results (offline pack source)."""

import json
from datetime import UTC, datetime

from .database import get_connection


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_snapshot(plan_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT data, updated_at FROM trip_snapshots WHERE plan_id = ?",
            (plan_id,),
        ).fetchone()
    if not row:
        return None
    data = json.loads(row["data"])
    data["as_of"] = row["updated_at"]
    return data


def put_snapshot(plan_id: int, data: dict) -> str:
    """Merge ``data`` into the stored object (a ``None`` value clears that
    key) and return the new ``as_of``."""
    as_of = _now()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT data FROM trip_snapshots WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        merged = json.loads(row["data"]) if row else {}
        merged.pop("as_of", None)
        for key, value in data.items():
            if key == "as_of":
                continue
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        conn.execute(
            "INSERT INTO trip_snapshots (plan_id, data, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(plan_id) DO UPDATE SET data = excluded.data, "
            "updated_at = excluded.updated_at",
            (plan_id, json.dumps(merged), as_of),
        )
    return as_of
