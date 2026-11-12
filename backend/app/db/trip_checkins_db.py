"""Trip check-ins: one row per (trip, day)."""

from datetime import UTC, datetime

from .database import get_connection


def add(plan_id: int, day: str, city: str | None, country_code: str | None) -> bool:
    """Record a check-in; True when created, False when the day was already there."""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO trip_checkins "
            "(plan_id, day, city, country_code, created_at) VALUES (?,?,?,?,?)",
            (plan_id, day, city, country_code, now),
        )
        return cur.rowcount > 0


def get(plan_id: int, day: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT day, city, country_code FROM trip_checkins "
            "WHERE plan_id = ? AND day = ?",
            (plan_id, day),
        ).fetchone()
    return dict(row) if row else None


def list_days(plan_id: int) -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT day FROM trip_checkins WHERE plan_id = ? ORDER BY day",
            (plan_id,),
        ).fetchall()
    return [r["day"] for r in rows]
