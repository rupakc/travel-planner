"""Drop moments and the savings tally (Phase 3, Task 5).

Pure helpers over a notification's ``data`` and the stored ``alert_savings``
rows. Honesty rules: only observed prices count (an estimate never alerts,
never counts toward savings and never awards XP) and currencies are never
converted: the USD tally counts USD watches only, other currencies are listed
separately. Wording is always "caught a drop of $X", never "you saved".
"""

import json
import math

from ..db import alerts_db
from ..db.database import get_connection

TARGET_KINDS = frozenset(
    {"fare_target", "hotel_target", "activity_target", "trip_target"}
)
DROP_KINDS = frozenset(
    {
        "fare_drop",
        "fare_low_level",
        "hotel_drop",
        "activity_drop",
        "trip_drop",
    }
)
MILESTONES = [50, 200, 1000]
_ESTIMATE_WORDS = ("estimate", "ai_estimate")


def _num(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    return float(v)


def _is_estimate_marker(v) -> bool:
    return isinstance(v, str) and v.lower() in _ESTIMATE_WORDS


def _observed(watch_kind: str, watch: dict, data: dict) -> bool:
    """False when the alerted price is (or rests on) an estimate."""
    if data.get("observed") is False or data.get("estimate"):
        return False
    if any(_is_estimate_marker(data.get(k)) for k in ("source", "status")):
        return False
    for part in data.get("components") or []:
        if isinstance(part, dict) and (
            part.get("live") is False or _is_estimate_marker(part.get("status"))
        ):
            return False
    if watch_kind == "trip":
        comps = (watch.get("subject") or {}).get("components") or []
        if comps and not any(c.get("live") for c in comps if isinstance(c, dict)):
            return False
    last = watch.get("last_observation") or {}
    if isinstance(last, dict) and (
        _is_estimate_marker(last.get("status"))
        or _is_estimate_marker(last.get("source"))
    ):
        return False
    return True


def drop_facts(watch_kind: str, watch: dict, note: dict) -> dict | None:
    """``{from, to, amount, pct, currency, target_hit, observed}`` for a drop or
    target note with an observed price, else ``None`` (expired, error,
    estimates and notes without a price never produce a drop)."""
    kind = note.get("kind")
    if kind not in TARGET_KINDS and kind not in DROP_KINDS:
        return None
    data = note.get("data") or {}
    to, frm = _num(data.get("price")), _num(data.get("previous_price"))
    if to is None or frm is None or not _observed(watch_kind, watch, data):
        return None
    amount = round(max(0.0, frm - to), 2)
    pct = round(100.0 * amount / frm, 1) if frm > 0 else 0.0
    currency = "USD" if watch_kind == "flight" else (watch.get("currency") or "USD")
    return {
        "from": frm,
        "to": to,
        "amount": amount,
        "pct": pct,
        "currency": currency,
        "target_hit": kind in TARGET_KINDS,
        "observed": True,
    }


def record(watch_kind: str, watch: dict, row: dict) -> bool:
    """Write the notification's ``alert_savings`` row (idempotent per
    notification). ``True`` when a new row was written."""
    drop = (row.get("data") or {}).get("drop")
    if not drop or not drop.get("observed"):
        return False
    return alerts_db.insert_saving(
        {
            "user_id": row["user_id"],
            "watch_kind": watch_kind,
            "watch_id": watch["id"],
            "notification_id": row["id"],
            "from_price": drop.get("from"),
            "to_price": drop.get("to"),
            "baseline": watch.get("baseline_price"),
            "currency": drop.get("currency"),
            "target_hit": drop.get("target_hit"),
            "created_at": row.get("created_at"),
        }
    )


def compute_savings(rows: list[dict], watches_active: int) -> dict:
    """The ``Savings`` object from per-notification rows (the shape of
    ``savings_cases.json``). Pure."""
    watches: dict[tuple[str, int], dict] = {}
    since = None
    for r in rows:
        if not r.get("observed", True):
            continue
        since = r["at"] if since is None or r["at"] < since else since
        base, price = _num(r.get("baseline")), _num(r.get("alerted_price"))
        w = watches.setdefault(
            (r["kind"], r["watch_id"]),
            {
                "kind": r["kind"],
                "watch_id": r["watch_id"],
                "title": r.get("title") or "",
                "currency": r.get("currency") or "USD",
                "baseline": base,
                "lowest": None,
                "target": False,
            },
        )
        if price is not None and (w["lowest"] is None or price < w["lowest"]):
            w["lowest"] = price
        w["target"] = w["target"] or bool(r.get("target_hit"))
    caught_watches = []
    for w in watches.values():
        if w["baseline"] is None or w["lowest"] is None:
            continue
        caught = round(max(0.0, w["baseline"] - w["lowest"]), 2)
        if caught > 0:
            caught_watches.append({**w, "caught": caught})
    total = 0.0
    by_currency: dict[str, float] = {}
    for w in caught_watches:
        if w["currency"] == "USD":
            total += w["caught"]
        else:
            by_currency[w["currency"]] = (
                by_currency.get(w["currency"], 0.0) + w["caught"]
            )
    total = round(total, 2)
    best = None
    if caught_watches:
        top = min(
            caught_watches,
            key=lambda w: (w["currency"] != "USD", -w["caught"], w["watch_id"]),
        )
        best = {
            "kind": top["kind"],
            "watch_id": top["watch_id"],
            "title": top["title"],
            "caught": top["caught"],
            "currency": top["currency"],
        }
    nxt = next((m for m in MILESTONES if m > total), None)
    progress = 100 if nxt is None else math.floor(100 * total / nxt)
    return {
        "total_usd": total,
        "by_currency": {c: round(v, 2) for c, v in by_currency.items() if v > 0},
        "drops_caught": len(caught_watches),
        "targets_hit": sum(1 for w in caught_watches if w["target"]),
        "watches_active": watches_active,
        "best": best,
        "milestones": list(MILESTONES),
        "next_milestone": nxt,
        "progress_pct": progress,
        "since": since,
    }


def _title_for(kind: str, wid: int, user_id: str, note_id: int) -> tuple[str, bool]:
    """(title, watch_deleted): the live watch's title, else the alert's own."""
    from ..db import fare_watch_db, price_watch_db
    from . import fare_watch

    try:
        if kind == "flight":
            w = fare_watch_db.get_watch_for_user(wid, user_id)
            if w:
                return fare_watch.route_label(w), False
        else:
            w = price_watch_db.get_watch_for_user(wid, user_id)
            if w:
                return w["title"], False
    except Exception:  # a label must never break the tally
        pass
    title = ""
    with get_connection() as conn:
        n = conn.execute(
            "SELECT data FROM notifications WHERE id = ?", (note_id,)
        ).fetchone()
    if n:
        try:
            d = json.loads(n["data"] or "{}")
            title = d.get("title") or d.get("route") or ""
        except ValueError:
            pass
    return title, True


def summary(user_id: str) -> dict:
    """The caller's ``Savings`` (stored rows plus the active-watch count)."""
    from ..db import fare_watch_db, price_watch_db

    stored = alerts_db.savings_rows(user_id)
    titles: dict[tuple[str, int], tuple[str, bool]] = {}
    rows = []
    for s in stored:
        key = (s["watch_kind"], s["watch_id"])
        if key not in titles:
            titles[key] = _title_for(*key, user_id, s["notification_id"])
        title, deleted = titles[key]
        rows.append(
            {
                "kind": s["watch_kind"],
                "watch_id": s["watch_id"],
                "title": title,
                "currency": s["currency"] or "USD",
                "baseline": s["baseline"],
                "alerted_price": s["to_price"],
                "notification_id": s["notification_id"],
                "at": s["created_at"],
                "target_hit": s["target_hit"],
                "observed": True,  # estimates are never recorded
                "watch_deleted": deleted,
            }
        )
    active = fare_watch_db.count_active(user_id) + price_watch_db.count_active(user_id)
    return compute_savings(rows, active)
