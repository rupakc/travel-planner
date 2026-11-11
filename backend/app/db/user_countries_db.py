"""Countries a traveller has been to (check-ins and recaps)."""

from datetime import UTC, datetime
from typing import Literal

from .database import get_connection


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_countries(
    user_id: str,
    codes: list[str],
    plan_id: int,
    source: Literal["checkin", "recap"],
) -> list[str]:
    """Add countries; returns only the codes that were not there before."""
    added: list[str] = []
    now = _now()
    with get_connection() as conn:
        for code in dict.fromkeys(c.upper() for c in codes if c):
            cur = conn.execute(
                "INSERT OR IGNORE INTO user_countries "
                "(user_id, country_code, first_plan_id, source, visited_at) "
                "VALUES (?,?,?,?,?)",
                (user_id, code, plan_id, source, now),
            )
            if cur.rowcount:
                added.append(code)
    return added


def list_countries(user_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM user_countries WHERE user_id = ? "
            "ORDER BY visited_at, country_code",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]
