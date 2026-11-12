"""Per-trip prep checklist state (``trip_prep`` rows: done flag + free meta)."""

import json
from datetime import UTC, datetime

from .database import get_connection


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _loads(raw) -> dict | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def get_state(plan_id: int) -> dict[str, dict]:
    """``{item_id: {"done": bool, "done_at": str | None, "meta": dict | None}}``."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT item_id, done_at, meta FROM trip_prep WHERE plan_id = ?",
            (plan_id,),
        ).fetchall()
    return {
        r["item_id"]: {
            "done": r["done_at"] is not None,
            "done_at": r["done_at"],
            "meta": _loads(r["meta"]),
        }
        for r in rows
    }


def set_done(plan_id: int, item_id: str, done: bool) -> None:
    now = _now()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO trip_prep (plan_id, item_id, done_at, updated_at) "
            "VALUES (?,?,?,?) ON CONFLICT(plan_id, item_id) DO UPDATE SET "
            "done_at = excluded.done_at, updated_at = excluded.updated_at",
            (plan_id, item_id, now if done else None, now),
        )


def set_meta(plan_id: int, item_id: str, meta: dict) -> None:
    now = _now()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO trip_prep (plan_id, item_id, meta, updated_at) "
            "VALUES (?,?,?,?) ON CONFLICT(plan_id, item_id) DO UPDATE SET "
            "meta = excluded.meta, updated_at = excluded.updated_at",
            (plan_id, item_id, json.dumps(meta), now),
        )


def get_meta(plan_id: int, item_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT meta FROM trip_prep WHERE plan_id = ? AND item_id = ?",
            (plan_id, item_id),
        ).fetchone()
    return _loads(row["meta"]) if row else None


def claim_marker(plan_id: int, key: str) -> bool:
    """Atomically create the marker row; True only for the caller that made it."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO trip_prep (plan_id, item_id, meta, updated_at) "
            "VALUES (?,?,?,?) ON CONFLICT(plan_id, item_id) DO NOTHING",
            (plan_id, key, json.dumps({"claimed": True}), _now()),
        )
        return cur.rowcount == 1


def release_marker(plan_id: int, key: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM trip_prep WHERE plan_id = ? AND item_id = ?", (plan_id, key)
        )
