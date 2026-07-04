"""SQLite persistence for the Taste Graph — learned per-user travel preferences.

Every time a user saves or updates a plan, lightweight signals are extracted
from their selections (hotel tier, activity categories, flight style,
interests, destinations). The aggregated signals become a short natural-
language "taste context" injected into agent prompts on future searches.
"""

from .database import get_connection

# Signal types recorded per plan save
SIGNAL_TYPES = (
    "activity_category",
    "event_category",
    "hotel_tier",
    "flight_style",
    "interest",
    "destination",
    "pace",
)

_MAX_TOP_VALUES = 3


def create_taste_table() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS taste_signals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT    NOT NULL,
                signal_type TEXT    NOT NULL,
                value       TEXT    NOT NULL,
                weight      REAL    NOT NULL DEFAULT 1.0,
                created_at  TEXT    DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_taste_username
                ON taste_signals (username, signal_type);
        """)


def hotel_tier_from_star_rating(star_rating) -> str | None:
    try:
        stars = float(star_rating)
    except (TypeError, ValueError):
        return None
    if stars >= 4.5:
        return "luxury"
    if stars >= 4.0:
        return "premium"
    if stars >= 3.0:
        return "mid-range"
    return "budget"


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def extract_signals(search_data: dict, selections: dict) -> list[tuple[str, str]]:
    """Turn one saved plan into (signal_type, value) pairs.

    Selections come from arbitrary client JSON — every field access must
    tolerate missing keys and wrong types without raising.
    """
    signals: list[tuple[str, str]] = []
    search_data = _as_dict(search_data)
    selections = _as_dict(selections)

    interests = search_data.get("interests")
    for interest in interests if isinstance(interests, list) else []:
        if isinstance(interest, str) and interest.strip():
            signals.append(("interest", interest.strip().lower()))

    destination = search_data.get("destination")
    if isinstance(destination, str) and destination.strip():
        signals.append(("destination", destination.strip()))

    pace = search_data.get("pace")
    if pace in ("relaxed", "packed"):  # 'balanced' is the default — not a signal
        signals.append(("pace", pace))

    hotel = _as_dict(selections.get("hotel"))
    tier = hotel_tier_from_star_rating(hotel.get("star_rating"))
    if tier:
        signals.append(("hotel_tier", tier))

    flights = selections.get("flights")
    flight_list = [selections.get("flight")] + (
        flights if isinstance(flights, list) else []
    )
    for flight in flight_list:
        stops = _as_dict(_as_dict(flight).get("outbound")).get("stops")
        if stops is None:
            continue
        try:
            style = "non-stop" if int(stops) == 0 else "with stops (cheaper)"
            signals.append(("flight_style", style))
        except (TypeError, ValueError):
            pass

    activities = selections.get("activities")
    for activity in activities if isinstance(activities, list) else []:
        category = _as_dict(activity).get("category")
        if isinstance(category, str) and category.strip():
            signals.append(("activity_category", category.strip().lower()))

    events = selections.get("events")
    for event in events if isinstance(events, list) else []:
        category = _as_dict(event).get("category")
        if isinstance(category, str) and category.strip():
            signals.append(("event_category", category.strip().lower()))

    return signals


def record_signals(username: str, signals: list[tuple[str, str]]) -> None:
    if not signals:
        return
    with get_connection() as conn:
        conn.executemany(
            "INSERT INTO taste_signals (username, signal_type, value) VALUES (?,?,?)",
            [(username, t, v) for t, v in signals if t in SIGNAL_TYPES],
        )


def record_plan_signals(username: str, search_data: dict, selections: dict) -> None:
    """Convenience wrapper used by the plans routes.

    Taste capture is best-effort — it must never break a plan save.
    """
    try:
        record_signals(username, extract_signals(search_data, selections))
    except Exception:  # noqa: BLE001 — never fail the caller for taste capture
        import logging

        logging.getLogger(__name__).warning(
            "Taste signal capture failed for %s", username, exc_info=True
        )


def get_taste_profile(username: str) -> dict:
    """Aggregate signals: top values with counts per signal type."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT signal_type, value, SUM(weight) AS score, COUNT(*) AS n
            FROM taste_signals WHERE username = ?
            GROUP BY signal_type, value
            ORDER BY signal_type, score DESC
            """,
            (username,),
        ).fetchall()

    profile: dict[str, list[dict]] = {}
    total_signals = 0
    for row in rows:
        d = dict(row)
        total_signals += d["n"]
        profile.setdefault(d["signal_type"], []).append(
            {"value": d["value"], "count": d["n"]}
        )
    return {"signals": profile, "total_signals": total_signals}


def derive_taste_context(username: str) -> str | None:
    """Short natural-language taste summary for agent prompts, or None."""
    profile = get_taste_profile(username)["signals"]
    if not profile:
        return None

    def top(signal_type: str) -> list[str]:
        return [e["value"] for e in profile.get(signal_type, [])[:_MAX_TOP_VALUES]]

    parts = []
    tiers = top("hotel_tier")
    if tiers:
        parts.append(f"usually books {tiers[0]} hotels")
    styles = top("flight_style")
    if styles:
        parts.append(f"prefers {styles[0]} flights")
    categories = top("activity_category")
    if categories:
        parts.append(f"gravitates to {', '.join(categories)} activities")
    event_cats = top("event_category")
    if event_cats:
        parts.append(f"seeks out local {', '.join(event_cats)} events")
    interests = top("interest")
    if interests:
        parts.append(f"recurring interests: {', '.join(interests)}")
    paces = top("pace")
    if paces:
        parts.append(f"tends to plan {paces[0]}-pace trips")
    destinations = top("destination")
    if destinations:
        parts.append(f"has planned trips to {', '.join(destinations)}")

    if not parts:
        return None
    return "Learned traveler taste profile (from past saved plans): " + "; ".join(parts)


def clear_taste_profile(username: str) -> int:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM taste_signals WHERE username = ?", (username,))
        return cur.rowcount
