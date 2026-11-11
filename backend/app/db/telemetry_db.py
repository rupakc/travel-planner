"""Telemetry storage.

Raw events live in their own SQLite file (``$DATA_DIR/telemetry.db``, 90 days,
not backed up). Daily aggregates live in the main DB (``telemetry_daily``) and
are backed up with the other user tables.
"""

import logging
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .database import get_connection

logger = logging.getLogger(__name__)

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


# False when the tables could not be created at startup (corrupt or
# unwritable telemetry.db): telemetry then runs as if TELEMETRY_ENABLED=false.
_available = True


def set_available(value: bool) -> None:
    global _available
    _available = value


def store_available() -> bool:
    return _available


def telemetry_active() -> bool:
    """Telemetry is on: enabled in settings and its store opened at startup."""
    from ..core.config import settings

    return settings.telemetry_enabled and _available


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
        # Lets prune() hand freed pages back to the disk. SQLite applies it
        # only to a file with no tables yet, and only before WAL is switched
        # on, so it must come first; a no-op on existing files.
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
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
            CREATE INDEX IF NOT EXISTS idx_telemetry_received
                ON telemetry_events (received_at);
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


# --- global disk guard ------------------------------------------------------
# Per-caller rate limits don't bound the total: before every insert, the batch
# is dropped (the route still answers 204) once telemetry.db + its WAL exceed
# TELEMETRY_MAX_DB_MB or today's (UTC, by received_at) stored rows reach
# TELEMETRY_MAX_EVENTS_PER_DAY. The size and the day count are re-read about
# once a minute; inserts in between are counted in memory.

_GUARD_REFRESH_S = 60.0
_WARN_INTERVAL_S = 3600.0
_guard_lock = threading.Lock()
_guard: dict = {}


def reset_ingest_guard() -> None:
    """Forget the cached size/count (and the warning clock); tests."""
    with _guard_lock:
        _guard.clear()


def _file_bytes(path: Path) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _store_bytes() -> int:
    db = telemetry_db_path()
    return _file_bytes(db) + _file_bytes(db.with_name(db.name + "-wal"))


def _utc_day_start_ms(now_s: float) -> int:
    d = datetime.fromtimestamp(now_s, UTC)
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)


def _count_today(day_start_ms: int) -> int:
    with _telemetry_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM telemetry_events WHERE received_at >= ?",
            (day_start_ms,),
        ).fetchone()[0]


def _over_cap(now_s: float) -> str | None:
    """Why ingest is paused (``"size"`` / ``"daily"``), or None. Caller holds
    ``_guard_lock``."""
    from ..core.config import settings

    day = _utc_day_start_ms(now_s)
    stale = now_s - _guard.get("checked", float("-inf")) >= _GUARD_REFRESH_S
    if stale or _guard.get("day") != day:
        _guard.update(
            checked=now_s, day=day, bytes=_store_bytes(), count=_count_today(day)
        )
    if _guard["bytes"] > settings.telemetry_max_db_mb * 1024 * 1024:
        return "size"
    if _guard["count"] >= settings.telemetry_max_events_per_day:
        return "daily"
    return None


def insert_events_guarded(rows: list[dict]) -> int:
    """``insert_events`` behind the global disk guard: returns the count
    stored, 0 when the batch was dropped (one warning per hour at most)."""
    if not rows:
        return 0
    now_s = time.time()
    with _guard_lock:
        reason = _over_cap(now_s)
        if reason:
            if now_s - _guard.get("warned", float("-inf")) >= _WARN_INTERVAL_S:
                _guard["warned"] = now_s
                logger.warning(
                    "telemetry ingest paused: %s cap reached, dropping batches",
                    "size" if reason == "size" else "daily event",
                )
            return 0
        _guard["count"] += len(rows)
    return insert_events(rows)


def rollup_day(day: str) -> int:
    """Aggregate one UTC day (``YYYY-MM-DD``) into ``telemetry_daily``.
    Idempotent: replaces that day's rows, and writes nothing when they (and
    the ``telemetry_rollups`` marker) are already current. Returns the number
    of per-event rows for the day."""
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
    new_daily = sorted(
        (r["event"], r["platform"], r["events"], r["users"], r["sessions"]) for r in agg
    )
    new_totals = sorted(totals)
    with get_connection() as conn:
        # Unchanged day (the hourly trailing-window re-roll, usually): write
        # nothing, so the backed-up user tables keep their digest.
        done = conn.execute(
            "SELECT 1 FROM telemetry_rollups WHERE day = ?", (day,)
        ).fetchone()
        old_daily = sorted(
            tuple(r)
            for r in conn.execute(
                "SELECT event, platform, events, users, sessions "
                "FROM telemetry_daily WHERE day = ?",
                (day,),
            )
        )
        old_totals = sorted(
            tuple(r)
            for r in conn.execute(
                "SELECT platform, users, sessions, events "
                "FROM telemetry_daily_totals WHERE day = ?",
                (day,),
            )
        )
        if done and old_daily == new_daily and old_totals == new_totals:
            return len(agg)
        conn.execute("DELETE FROM telemetry_daily WHERE day = ?", (day,))
        conn.execute("DELETE FROM telemetry_daily_totals WHERE day = ?", (day,))
        conn.executemany(
            "INSERT INTO telemetry_daily_totals "
            "(day, platform, users, sessions, events) VALUES (?, ?, ?, ?, ?)",
            [(day, *t) for t in new_totals],
        )
        conn.executemany(
            "INSERT INTO telemetry_daily (day, event, platform, events, users, sessions) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(day, *r) for r in new_daily],
        )
        conn.execute(
            "INSERT OR REPLACE INTO telemetry_rollups (day, done_at) VALUES (?, ?)",
            (day, datetime.now(UTC).isoformat()),
        )
    return len(agg)


def prune(before_ms: int) -> int:
    """Delete raw events older than ``before_ms``, then return the freed
    pages to the disk (``auto_vacuum=INCREMENTAL``); returns the count."""
    with _telemetry_connection() as conn:
        n = conn.execute(
            "DELETE FROM telemetry_events WHERE ts < ?", (before_ms,)
        ).rowcount
        conn.commit()
        if n:
            conn.execute("PRAGMA incremental_vacuum").fetchall()
        return n


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
    week_start = today - timedelta(days=6)
    week_ms = int(
        datetime(
            week_start.year, week_start.month, week_start.day, tzinfo=UTC
        ).timestamp()
        * 1000
    )
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
        users_7d = conn.execute(
            "SELECT COUNT(DISTINCT coalesce(user_id, anon_id)) AS n "
            "FROM telemetry_events WHERE ts >= ?",
            (week_ms,),
        ).fetchone()["n"]
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
        # Distinct users over the trailing 7 UTC days (today included), from raw
        # events. Additive: the previous SPA ignores it.
        "users_7d": users_7d,
    }
