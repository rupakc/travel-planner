"""Telemetry storage.

Raw events live in their own SQLite file (``$DATA_DIR/telemetry.db``, 90 days,
not backed up). Daily aggregates live in the main DB (``telemetry_daily``) and
are backed up with the other user tables.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .database import get_connection

_COLUMNS = (
    "ts",
    "received_at",
    "event",
    "session_id",
    "anon_id",
    "user_id",
    "platform",
    "app_version",
    "locale",
    "screen",
    "props",
)


def telemetry_db_path() -> Path:
    from ..core.config import settings

    p = Path(settings.data_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p / "telemetry.db"


@contextmanager
def _telemetry_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(telemetry_db_path()))
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_telemetry_tables() -> None:
    with _telemetry_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS telemetry_events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           INTEGER NOT NULL,
                received_at  INTEGER NOT NULL,
                event        TEXT    NOT NULL,
                session_id   TEXT    NOT NULL,
                anon_id      TEXT    NOT NULL,
                user_id      TEXT,
                platform     TEXT    NOT NULL,
                app_version  TEXT    NOT NULL,
                locale       TEXT    NOT NULL,
                screen       TEXT,
                props        TEXT    NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_telemetry_ts
                ON telemetry_events (ts);
            CREATE INDEX IF NOT EXISTS idx_telemetry_event_ts
                ON telemetry_events (event, ts);
        """)
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS telemetry_daily (
                day       TEXT    NOT NULL,
                event     TEXT    NOT NULL,
                platform  TEXT    NOT NULL,
                events    INTEGER NOT NULL,
                users     INTEGER NOT NULL,
                sessions  INTEGER NOT NULL,
                PRIMARY KEY (day, event, platform)
            );
            CREATE TABLE IF NOT EXISTS telemetry_daily_totals (
                day       TEXT    NOT NULL,
                platform  TEXT    NOT NULL,  -- '*' = all platforms
                users     INTEGER NOT NULL,
                sessions  INTEGER NOT NULL,
                events    INTEGER NOT NULL,
                PRIMARY KEY (day, platform)
            );
            CREATE TABLE IF NOT EXISTS telemetry_rollups (
                day      TEXT PRIMARY KEY,
                done_at  TEXT NOT NULL
            );
        """)


def insert_events(rows: list[dict]) -> int:
    """Insert cleaned event rows in one transaction; returns the count."""
    if not rows:
        return 0
    with _telemetry_connection() as conn:
        conn.executemany(
            f"INSERT INTO telemetry_events ({', '.join(_COLUMNS)}) "  # nosec B608
            f"VALUES ({', '.join(':' + c for c in _COLUMNS)})",
            [{c: r.get(c) for c in _COLUMNS} for r in rows],
        )
    return len(rows)


def rollup_day(day: str) -> int:
    """Aggregate one UTC day (``YYYY-MM-DD``) into ``telemetry_daily``.
    Idempotent: replaces that day's rows. Returns the number of rows written."""
    start = datetime.fromisoformat(day).replace(tzinfo=UTC)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int((start + timedelta(days=1)).timestamp() * 1000)
    with _telemetry_connection() as tconn:
        agg = tconn.execute(
            "SELECT event, platform, COUNT(*) AS events, "
            "COUNT(DISTINCT coalesce(user_id, anon_id)) AS users, "
            "COUNT(DISTINCT session_id) AS sessions "
            "FROM telemetry_events WHERE ts >= ? AND ts < ? "
            "GROUP BY event, platform",
            (start_ms, end_ms),
        ).fetchall()
        _tot = "COUNT(DISTINCT coalesce(user_id, anon_id)) AS users, COUNT(DISTINCT session_id) AS sessions, COUNT(*) AS events"
        totals = [
            (r["platform"], r["users"], r["sessions"], r["events"])
            for r in tconn.execute(
                f"SELECT platform, {_tot} FROM telemetry_events "  # nosec B608
                "WHERE ts >= ? AND ts < ? GROUP BY platform",
                (start_ms, end_ms),
            )
        ]
        allp = tconn.execute(
            f"SELECT {_tot} FROM telemetry_events WHERE ts >= ? AND ts < ?",  # nosec B608
            (start_ms, end_ms),
        ).fetchone()
        if allp["events"]:
            totals.append(("*", allp["users"], allp["sessions"], allp["events"]))
    with get_connection() as conn:
        conn.execute("DELETE FROM telemetry_daily WHERE day = ?", (day,))
        conn.execute("DELETE FROM telemetry_daily_totals WHERE day = ?", (day,))
        conn.executemany(
            "INSERT INTO telemetry_daily_totals "
            "(day, platform, users, sessions, events) VALUES (?, ?, ?, ?, ?)",
            [(day, *t) for t in totals],
        )
        conn.executemany(
            "INSERT INTO telemetry_daily (day, event, platform, events, users, sessions) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (day, r["event"], r["platform"], r["events"], r["users"], r["sessions"])
                for r in agg
            ],
        )
        conn.execute(
            "INSERT OR REPLACE INTO telemetry_rollups (day, done_at) VALUES (?, ?)",
            (day, datetime.now(UTC).isoformat()),
        )
    return len(agg)


def prune(before_ms: int) -> int:
    """Delete raw events older than ``before_ms``; returns the count."""
    with _telemetry_connection() as conn:
        return conn.execute(
            "DELETE FROM telemetry_events WHERE ts < ?", (before_ms,)
        ).rowcount


def summary(days: int, now: datetime | None = None) -> dict:
    """Admin overview: per-day users/sessions/events for the last ``days`` UTC
    days (rolled-up days from ``telemetry_daily``, today live from raw events),
    top events and top screens. Users and sessions are exact distinct counts
    across all events and platforms (``telemetry_daily_totals`` rows ``'*'``)."""
    now = now or datetime.now(UTC)
    today = now.date()
    first = today - timedelta(days=days - 1)
    first_ms = int(
        datetime(first.year, first.month, first.day, tzinfo=UTC).timestamp() * 1000
    )
    today_ms = int(
        datetime(today.year, today.month, today.day, tzinfo=UTC).timestamp() * 1000
    )
    with get_connection() as conn:
        daily = conn.execute(
            "SELECT day, users, sessions, events FROM telemetry_daily_totals "
            "WHERE platform = '*' AND day >= ? AND day < ? ORDER BY day",
            (first.isoformat(), today.isoformat()),
        ).fetchall()
        top_events = conn.execute(
            "SELECT event, SUM(events) AS events FROM telemetry_daily "
            "WHERE day >= ? AND day < ? GROUP BY event",
            (first.isoformat(), today.isoformat()),
        ).fetchall()
    with _telemetry_connection() as conn:
        live = conn.execute(
            "SELECT COUNT(*) AS events, "
            "COUNT(DISTINCT coalesce(user_id, anon_id)) AS users, "
            "COUNT(DISTINCT session_id) AS sessions "
            "FROM telemetry_events WHERE ts >= ?",
            (today_ms,),
        ).fetchone()
        live_events = conn.execute(
            "SELECT event, COUNT(*) AS events FROM telemetry_events "
            "WHERE ts >= ? GROUP BY event",
            (today_ms,),
        ).fetchall()
        screens = conn.execute(
            "SELECT json_extract(props, '$.route') AS route, COUNT(*) AS views "
            "FROM telemetry_events WHERE event = 'screen_view' AND ts >= ? "
            "AND json_extract(props, '$.route') IS NOT NULL "
            "GROUP BY route ORDER BY views DESC, route LIMIT 20",
            (first_ms,),
        ).fetchall()
    out_days = [
        {
            "day": r["day"],
            "users": r["users"],
            "sessions": r["sessions"],
            "events": r["events"],
        }
        for r in daily
    ]
    if live["events"]:
        out_days.append(
            {
                "day": today.isoformat(),
                "users": live["users"],
                "sessions": live["sessions"],
                "events": live["events"],
            }
        )
    totals: dict[str, int] = {r["event"]: r["events"] for r in top_events}
    for r in live_events:
        totals[r["event"]] = totals.get(r["event"], 0) + r["events"]
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:20]
    return {
        "days": out_days,
        "top_events": [{"event": e, "events": n} for e, n in ranked],
        "top_screens": [{"route": r["route"], "views": r["views"]} for r in screens],
    }
