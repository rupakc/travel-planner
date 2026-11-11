"""XP ledger, badges, levels and streaks. Server-observed events only."""

from datetime import UTC, date, datetime
from functools import lru_cache

from ..db import game_db
from ..db.database import get_connection
from .rules import Rules, load_rules


@lru_cache(maxsize=1)
def get_rules() -> Rules:
    return load_rules()


def level_for(xp: int, rules: Rules) -> int:
    level = 1
    for i, m in enumerate(rules.levels.min_xp):
        if xp >= m:
            level = i + 1
    return level


def _empty(xp: int) -> dict:
    return {"xp": xp, "awards": [], "badges": [], "level_up": None}


def award(
    user_id: str,
    rule: str,
    idem_key: str,
    *,
    meta: dict | None = None,
    now: datetime | None = None,
) -> dict:
    rules = get_rules()
    r = rules.rules[rule]  # KeyError for unknown rules
    now = now or datetime.now(UTC)
    if r.once:
        idem_key = f"{rule}:{user_id}"
    ts = game_db.iso(now)
    day_start = game_db.iso(now.replace(hour=0, minute=0, second=0, microsecond=0))
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        before = game_db.total_xp(conn, user_id)
        if game_db.count_rule(conn, user_id, rule, day_start) >= r.daily_cap:
            return _empty(before)
        if not game_db.insert_ledger(conn, user_id, rule, r.points, idem_key, meta, ts):
            return _empty(before)
        after = before + r.points
        earned = []
        done = game_db.count_rule(conn, user_id, rule)
        for bid, b in rules.badges.items():
            if b.rule != rule:
                continue
            row = game_db.get_badge(conn, user_id, bid)
            already = row["earned_at"] if row else None
            progress = min(b.target, done)
            at = already or (ts if progress >= b.target else None)
            game_db.upsert_badge(conn, user_id, bid, progress, b.target, at, ts)
            if at and not already:
                earned.append({"id": bid, "earned_at": at})
    lv_from, lv_to = level_for(before, rules), level_for(after, rules)
    return {
        "xp": after,
        "awards": [{"rule": rule, "points": r.points}],
        "badges": earned,
        "level_up": {"from": lv_from, "to": lv_to} if lv_to > lv_from else None,
    }


def summary(user_id: str, *, hidden: bool) -> dict:
    rules = get_rules()
    mins = rules.levels.min_xp
    with get_connection() as conn:
        xp = game_db.total_xp(conn, user_id)
        badges = game_db.list_badges(conn, user_id)
        recent = game_db.recent(conn, user_id)
        streak_rows = {k: game_db.get_streak(conn, user_id, k) for k in rules.streaks}
    level = level_for(xp, rules)
    streaks = {}
    for kind, row in streak_rows.items():
        streaks[kind] = (
            {
                "current": row["current"],
                "longest": row["longest"],
                "last_day": row["last_day"],
                "freezes": row["freezes"],
            }
            if row
            else {
                "current": 0,
                "longest": 0,
                "last_day": None,
                "freezes": rules.streaks[kind].freeze_per_week,
            }
        )
    return {
        "xp": xp,
        "level": level,
        "level_min_xp": mins[level - 1],
        "next_level_xp": mins[level] if level < len(mins) else None,
        "badges": [
            {
                "id": b["badge_id"],
                "progress": b["progress"],
                "target": b["target"],
                "earned_at": b["earned_at"],
            }
            for b in badges
        ],
        "streaks": streaks,
        "recent": recent,
        "hidden": hidden,
    }


def catalog() -> dict:
    rules = get_rules()
    return {
        "version": rules.version,
        "rules": [
            {"id": k, "points": v.points, "daily_cap": v.daily_cap, "once": v.once}
            for k, v in rules.rules.items()
        ],
        "badges": [
            {
                "id": k,
                "rule": v.rule,
                "target": v.target,
                "tier": v.tier,
                "icon": v.icon,
            }
            for k, v in rules.badges.items()
        ],
        "levels": [
            {"level": i + 1, "min_xp": m} for i, m in enumerate(rules.levels.min_xp)
        ],
    }


def _week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def touch_streak(user_id: str, kind: str, day: date) -> dict:
    per_week = get_rules().streaks[kind].freeze_per_week
    now = game_db.iso(datetime.now(UTC))
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = game_db.get_streak(conn, user_id, kind)
        s = (
            dict(row)
            if row
            else {
                "current": 0,
                "longest": 0,
                "last_day": None,
                "freezes": per_week,
                "freeze_week": None,
            }
        )
        last = date.fromisoformat(s["last_day"]) if s["last_day"] else None
        if last and day <= last:
            return _streak_view(s)
        if s["freeze_week"] != _week(day):
            s["freezes"] = per_week
            s["freeze_week"] = _week(day)
        if last is None:
            s["current"] = 1
        else:
            missed = (day - last).days - 1
            if missed == 0:
                s["current"] += 1
            elif missed <= s["freezes"]:
                s["freezes"] -= missed
                s["current"] += 1
            else:
                s["current"] = 1
        s["longest"] = max(s["longest"], s["current"])
        s["last_day"] = day.isoformat()
        game_db.save_streak(conn, user_id, kind, s, now)
    return _streak_view(s)


def _streak_view(s: dict) -> dict:
    return {k: s[k] for k in ("current", "longest", "last_day", "freezes")}
