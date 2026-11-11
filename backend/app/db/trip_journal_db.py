"""Trip journal entries and place ratings/visits (one row set per plan)."""

from datetime import UTC, datetime

from .database import get_connection

JOURNAL_LIMIT = 500
PLACES_LIMIT = 1000

_PLACE_FIELDS = ("name", "kind", "visited", "stars", "note", "day", "lat", "lng")


class LimitReached(Exception):
    """Raised when a plan already holds the maximum number of rows."""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _entry(row) -> dict:
    return dict(row)


def _place(row) -> dict:
    d = dict(row)
    d["visited"] = bool(d["visited"])
    return d


def add_entry(
    plan_id: int, client_id: str, body: str, day: str | None, mood: str | None
) -> tuple[dict, bool]:
    """Insert an entry; a repeated client_id returns the existing row, False."""
    now = _now()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM trip_journal WHERE plan_id = ? AND client_id = ?",
            (plan_id, client_id),
        ).fetchone()
        if row:
            return _entry(row), False
        count = conn.execute(
            "SELECT COUNT(*) FROM trip_journal WHERE plan_id = ?", (plan_id,)
        ).fetchone()[0]
        if count >= JOURNAL_LIMIT:
            raise LimitReached
        cur = conn.execute(
            "INSERT INTO trip_journal "
            "(plan_id, client_id, day, body, mood, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (plan_id, client_id, day, body, mood, now, now),
        )
        row = conn.execute(
            "SELECT * FROM trip_journal WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return _entry(row), True


def update_entry(plan_id: int, entry_id: int, fields: dict) -> dict | None:
    """Update body/day/mood (keys present in `fields`); None if not found."""
    cols = [k for k in ("body", "day", "mood") if k in fields]
    with get_connection() as conn:
        if cols:
            sets = ", ".join(f"{c} = ?" for c in cols)
            conn.execute(
                f"UPDATE trip_journal SET {sets}, updated_at = ? "  # nosec B608
                "WHERE plan_id = ? AND id = ?",
                (*[fields[c] for c in cols], _now(), plan_id, entry_id),
            )
        row = conn.execute(
            "SELECT * FROM trip_journal WHERE plan_id = ? AND id = ?",
            (plan_id, entry_id),
        ).fetchone()
    return _entry(row) if row else None


def delete_entry(plan_id: int, entry_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM trip_journal WHERE plan_id = ? AND id = ?",
            (plan_id, entry_id),
        )
    return cur.rowcount > 0


def list_entries(plan_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trip_journal WHERE plan_id = ? "
            "ORDER BY day IS NULL, day, created_at, id",
            (plan_id,),
        ).fetchall()
    return [_entry(r) for r in rows]


def upsert_place(plan_id: int, place_key: str, fields: dict) -> tuple[dict, bool]:
    """Insert or update a place; keys absent from `fields` keep their value.

    Returns (row, newly_visited). `name` and `kind` are required on insert."""
    now = _now()
    with get_connection() as conn:
        old = conn.execute(
            "SELECT * FROM trip_ratings WHERE plan_id = ? AND place_key = ?",
            (plan_id, place_key),
        ).fetchone()
        if old is None:
            count = conn.execute(
                "SELECT COUNT(*) FROM trip_ratings WHERE plan_id = ?", (plan_id,)
            ).fetchone()[0]
            if count >= PLACES_LIMIT:
                raise LimitReached
            data = {
                "name": "",
                "kind": "other",
                "visited": False,
                "stars": None,
                "note": None,
                "day": None,
                "lat": None,
                "lng": None,
            }
            was_visited = False
            visited_at = None
        else:
            data = _place(old)
            was_visited = data["visited"]
            visited_at = data["visited_at"]
        for k in _PLACE_FIELDS:
            if k in fields:
                data[k] = fields[k]
        newly = bool(data["visited"]) and not was_visited
        if newly:
            visited_at = now
        elif not data["visited"]:
            visited_at = None
        conn.execute(
            "INSERT INTO trip_ratings (plan_id, place_key, name, kind, visited, "
            "stars, note, day, lat, lng, visited_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(plan_id, place_key) DO UPDATE SET name=excluded.name, "
            "kind=excluded.kind, visited=excluded.visited, stars=excluded.stars, "
            "note=excluded.note, day=excluded.day, lat=excluded.lat, "
            "lng=excluded.lng, visited_at=excluded.visited_at, "
            "updated_at=excluded.updated_at",
            (
                plan_id,
                place_key,
                data["name"],
                data["kind"],
                int(data["visited"]),
                data["stars"],
                data["note"],
                data["day"],
                data["lat"],
                data["lng"],
                visited_at,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM trip_ratings WHERE plan_id = ? AND place_key = ?",
            (plan_id, place_key),
        ).fetchone()
    return _place(row), newly


def get_place(plan_id: int, place_key: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM trip_ratings WHERE plan_id = ? AND place_key = ?",
            (plan_id, place_key),
        ).fetchone()
    return _place(row) if row else None


def delete_place(plan_id: int, place_key: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM trip_ratings WHERE plan_id = ? AND place_key = ?",
            (plan_id, place_key),
        )
    return cur.rowcount > 0


def list_places(plan_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trip_ratings WHERE plan_id = ? "
            "ORDER BY day IS NULL, day, COALESCE(visited_at, updated_at), place_key",
            (plan_id,),
        ).fetchall()
    return [_place(r) for r in rows]
