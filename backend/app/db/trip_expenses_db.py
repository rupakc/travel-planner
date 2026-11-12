"""Per-trip expense rows (amounts in integer minor units)."""

from datetime import UTC, datetime

from ..core.config import settings
from .database import get_connection

_COLS = "id, client_id, amount_minor, currency, category, note, spent_on, created_at, updated_at"


class ExpenseLimitError(Exception):
    """The trip already holds the maximum number of expenses."""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(row) -> dict:
    return dict(row)


def add(
    plan_id: int,
    client_id: str,
    amount_minor: int,
    currency: str,
    category: str,
    note: str | None,
    spent_on: str,
) -> tuple[dict, bool]:
    """Insert one expense, idempotent on ``(plan_id, client_id)``: a repeated
    client_id returns the existing row with ``created`` False."""
    now = _now()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            f"SELECT {_COLS} FROM trip_expenses WHERE plan_id = ? AND client_id = ?",  # nosec B608
            (plan_id, client_id),
        ).fetchone()
        if existing:
            return _row(existing), False
        count = conn.execute(
            "SELECT COUNT(*) FROM trip_expenses WHERE plan_id = ?", (plan_id,)
        ).fetchone()[0]
        if count >= settings.trip_max_expenses:
            raise ExpenseLimitError
        cur = conn.execute(
            "INSERT INTO trip_expenses (plan_id, client_id, amount_minor, currency, "
            "category, note, spent_on, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                plan_id,
                client_id,
                amount_minor,
                currency,
                category,
                note,
                spent_on,
                now,
                now,
            ),
        )
        row = conn.execute(
            f"SELECT {_COLS} FROM trip_expenses WHERE id = ?",  # nosec B608
            (cur.lastrowid,),
        ).fetchone()
    return _row(row), True


def get(plan_id: int, expense_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT {_COLS} FROM trip_expenses WHERE plan_id = ? AND id = ?",  # nosec B608
            (plan_id, expense_id),
        ).fetchone()
    return _row(row) if row else None


def update(plan_id: int, expense_id: int, fields: dict) -> dict | None:
    """Apply ``fields`` (any of amount_minor, currency, category, note,
    spent_on); returns the new row or None when it is not on this trip."""
    allowed = ("amount_minor", "currency", "category", "note", "spent_on")
    sets = [k for k in fields if k in allowed]
    with get_connection() as conn:
        if sets:
            # Column names come from the fixed allow-list above.
            conn.execute(
                "UPDATE trip_expenses SET "  # nosec B608
                + ", ".join(f"{k} = ?" for k in sets)
                + ", updated_at = ? WHERE plan_id = ? AND id = ?",
                (*[fields[k] for k in sets], _now(), plan_id, expense_id),
            )
        row = conn.execute(
            f"SELECT {_COLS} FROM trip_expenses WHERE plan_id = ? AND id = ?",  # nosec B608
            (plan_id, expense_id),
        ).fetchone()
    return _row(row) if row else None


def delete(plan_id: int, expense_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM trip_expenses WHERE plan_id = ? AND id = ?",
            (plan_id, expense_id),
        )
    return cur.rowcount > 0


def list_for(plan_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT {_COLS} FROM trip_expenses WHERE plan_id = ? "  # nosec B608
            "ORDER BY spent_on DESC, id DESC",
            (plan_id,),
        ).fetchall()
    return [_row(r) for r in rows]
