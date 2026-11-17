"""Paid third-party API budgets (``api_budget``) and the Tripadvisor
location-ID cache (``tripadvisor_location_ids``).

``api_budget`` is one row per provider: the units used so far against a
hard cap. A caller *reserves* the most units a call can bill before making
it and *settles* afterwards, refunding what was not billed. Reservations run
inside ``BEGIN IMMEDIATE`` (one writer at a time, across threads and
processes), so concurrent callers can never take more than the cap between
them. The warn / exhausted markers are set once per cap value with a
conditional UPDATE, so exactly one caller sees each transition.

``tripadvisor_location_ids`` keeps ONLY Tripadvisor location IDs (integers)
per destination: Tripadvisor's caching policy forbids storing any other
content (names, ratings, reviews, photos), but allows caching the Location
ID to make the app faster. Both are user-data tables, so the VM backup
(``vm_backup.export_user_tables``: every non-place table) keeps them; the
budget must survive a lost disk because the free tier is per account, for
its lifetime.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from .database import _db_path, get_connection

WARN_RATIO = 0.8


def create_api_budget_tables() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS api_budget (
                provider      TEXT PRIMARY KEY,
                used          INTEGER NOT NULL DEFAULT 0,
                cap           INTEGER NOT NULL,
                warned_at     TEXT,
                exhausted_at  TEXT,
                updated_at    TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tripadvisor_location_ids (
                place_key     TEXT PRIMARY KEY,
                location_ids  TEXT NOT NULL,
                created_at    TEXT NOT NULL
            );
        """)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def warn_at(cap: int) -> int:
    """The usage that triggers the early warning (80 % of the cap)."""
    return max(1, int(cap * WARN_RATIO)) if cap > 0 else 0


@contextmanager
def _immediate() -> Iterator[sqlite3.Connection]:
    """A write transaction taken up front (BEGIN IMMEDIATE): the read and
    the update below it can't interleave with another writer's."""
    conn = sqlite3.connect(str(_db_path()), isolation_level=None, timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def _row(conn: sqlite3.Connection, provider: str, cap: int) -> sqlite3.Row:
    """The provider's row, created on first use. A changed cap (the owner
    raised it after adding payment details) re-arms both markers."""
    conn.execute(
        "INSERT OR IGNORE INTO api_budget (provider, used, cap, updated_at) "
        "VALUES (?, 0, ?, ?)",
        (provider, cap, _now()),
    )
    row = conn.execute(
        "SELECT * FROM api_budget WHERE provider = ?", (provider,)
    ).fetchone()
    if row["cap"] != cap:
        conn.execute(
            "UPDATE api_budget SET cap = ?, warned_at = NULL, exhausted_at = NULL, "
            "updated_at = ? WHERE provider = ?",
            (cap, _now(), provider),
        )
        row = conn.execute(
            "SELECT * FROM api_budget WHERE provider = ?", (provider,)
        ).fetchone()
    return row


def reserve(provider: str, want: int, cap: int) -> int:
    """Reserve up to ``want`` units; returns how many were granted (0 at
    the cap). Never lets ``used`` pass ``cap``."""
    if want <= 0:
        return 0
    with _immediate() as conn:
        row = _row(conn, provider, cap)
        grant = max(0, min(want, cap - row["used"]))
        if grant:
            conn.execute(
                "UPDATE api_budget SET used = used + ?, updated_at = ? "
                "WHERE provider = ?",
                (grant, _now(), provider),
            )
        return grant


def settle(provider: str, reserved: int, billed: int, cap: int) -> dict:
    """Refund ``reserved - billed`` units, then report the usage and which
    markers this call crossed first: ``{"used", "cap", "events"}`` where
    events ⊆ ["warn", "exhausted"]; each fires once per cap value."""
    refund = max(0, reserved - max(0, billed))
    events: list[str] = []
    with _immediate() as conn:
        _row(conn, provider, cap)
        if refund:
            conn.execute(
                "UPDATE api_budget SET used = MAX(0, used - ?), updated_at = ? "
                "WHERE provider = ?",
                (refund, _now(), provider),
            )
        used = conn.execute(
            "SELECT used FROM api_budget WHERE provider = ?", (provider,)
        ).fetchone()["used"]
        if used >= warn_at(cap):
            cur = conn.execute(
                "UPDATE api_budget SET warned_at = ? "
                "WHERE provider = ? AND warned_at IS NULL",
                (_now(), provider),
            )
            if cur.rowcount == 1:
                events.append("warn")
        if used >= cap:
            cur = conn.execute(
                "UPDATE api_budget SET exhausted_at = ? "
                "WHERE provider = ? AND exhausted_at IS NULL",
                (_now(), provider),
            )
            if cur.rowcount == 1:
                events.append("exhausted")
    return {"used": used, "cap": cap, "events": events}


def status(provider: str, cap: int) -> dict:
    """Read-only usage for /health and the admin page."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT used, warned_at, exhausted_at FROM api_budget WHERE provider = ?",
            (provider,),
        ).fetchone()
    used = row["used"] if row else 0
    return {
        "used": used,
        "cap": cap,
        "warn_at": warn_at(cap),
        "paused": used >= cap,
        "exhausted_at": row["exhausted_at"] if row else None,
    }


# ── Tripadvisor location IDs (the only Tripadvisor data ever stored) ─────────


def get_location_ids(place_key: str) -> list[int] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT location_ids FROM tripadvisor_location_ids WHERE place_key = ?",
            (place_key,),
        ).fetchone()
    if not row:
        return None
    try:
        ids = [int(i) for i in json.loads(row["location_ids"])]
    except (TypeError, ValueError):
        return None
    return ids or None


def save_location_ids(place_key: str, ids: list[int]) -> None:
    clean = [int(i) for i in ids]
    if not clean:
        return
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO tripadvisor_location_ids (place_key, location_ids, created_at) "
            "VALUES (?, ?, ?) ON CONFLICT(place_key) DO UPDATE SET "
            "location_ids = excluded.location_ids, created_at = excluded.created_at",
            (place_key, json.dumps(clean), _now()),
        )
