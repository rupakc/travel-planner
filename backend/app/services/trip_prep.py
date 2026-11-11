"""Trip preparation checklist (contract "Prep checklist").

``build_items`` is pure; ``prep_summary`` / ``prep_payload`` read the stored
state and the trip snapshot.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from ..agents.static_results import _resolve_dest_currency, find_visa_row
from ..db import trip_prep_db, trip_snapshot_db
from .trip_phase import trip_dates

DEFAULT_VISA_LEAD_DAYS = 21
VISA_BUFFER_DAYS = 7
READY_AWARD_KEY = "trip_ready_award"

# (id, days before the start)
_ORDER = (
    ("visa", None),
    ("passport", 30),
    ("bookings", 30),
    ("insurance", 14),
    ("documents", 7),
    ("stress_test", 7),
    ("sim", 3),
    ("money", 3),
    ("packing", 1),
    ("emergency_card", 1),
    ("checkin", 1),
    ("offline_pack", 1),
)
ITEM_IDS = tuple(i for i, _ in _ORDER)
AUTO_ITEMS = frozenset({"offline_pack"})

_NUM = re.compile(
    r"(\d+)(?:\s*(?:-|–|to)\s*(\d+))?\s*"
    r"(business\s+days?|working\s+days?|weeks?|days?|months?)?",
    re.I,
)


def visa_lead_days(processing_time: str | None, visa_type: str | None) -> int | None:
    """Days before the start to begin the visa; ``None`` for visa-free."""
    if _is_visa_free(visa_type, processing_time):
        return None
    best: tuple[int, str] | None = None
    for m in _NUM.finditer(processing_time or ""):
        n = int(m.group(2) or m.group(1))
        if best is None or n > best[0]:
            best = (n, (m.group(3) or "days").lower())
    if best is None:
        return DEFAULT_VISA_LEAD_DAYS
    n, unit = best
    if unit.startswith("week"):
        days = n * 7
    elif unit.startswith("month"):
        days = n * 30
    elif unit.startswith(("business", "working")):
        days = (n * 14 + 9) // 10  # ceil(n * 1.4)
    else:
        days = n
    return days + VISA_BUFFER_DAYS


def _is_visa_free(visa_type, processing_time=None) -> bool:
    t = re.sub(r"[\s_]+", "-", str(visa_type or "").strip().lower())
    return t == "visa-free"


def local_currency(destination: str | None) -> dict | None:
    """Local currency (``{name, code, symbol}``) from the static tables."""
    if not destination:
        return None
    return _resolve_dest_currency(destination)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _destination(plan: dict) -> str | None:
    sd = _dict(plan.get("search_data"))
    dest = sd.get("destination")
    if not dest:
        dests = sd.get("destinations")
        dest = dests[0] if isinstance(dests, list) and dests else None
    return dest if isinstance(dest, str) and dest else None


def _has_flight(sel: dict) -> bool:
    return bool(sel.get("flight") or sel.get("flights"))


def _has_itinerary(sel: dict) -> bool:
    return any(
        sel.get(k) for k in ("itinerary_slots", "itinerary", "comprehensive_itinerary")
    )


def _count_pack_items(value) -> int:
    if isinstance(value, list):
        return len(value)
    if not isinstance(value, dict):
        return 0
    cats = value.get("categories")
    if isinstance(cats, list):
        return sum(len(_dict(c).get("items") or []) for c in cats)
    items = value.get("items")
    return len(items) if isinstance(items, list) else 0


def _visa_facts(plan: dict, snapshot: dict | None) -> dict:
    snap = _dict(_dict(snapshot).get("visa"))
    row, source = None, None
    if snap.get("visa_type"):
        row, source = snap, "ai"
    else:
        sd = _dict(plan.get("search_data"))
        dest, nat = _destination(plan), sd.get("nationality")
        if dest and nat:
            row = find_visa_row(nat, dest)
            source = "static" if row else None
    row = row or {}
    return {
        "visa_type": row.get("visa_type"),
        "max_stay_days": row.get("max_stay_days"),
        "processing_time": row.get("processing_time"),
        "official_url": row.get("official_url"),
        "source": source,
    }


def _currency_code(plan: dict, snapshot: dict | None) -> str | None:
    cur = _dict(_dict(_dict(snapshot).get("forex")).get("local_currency"))
    if cur.get("code"):
        return cur["code"]
    cur = local_currency(_destination(plan)) or {}
    return cur.get("code")


def _sim_name(sel: dict) -> str | None:
    sim = sel.get("sim")
    if not isinstance(sim, dict):
        return None
    return sim.get("plan_name") or sim.get("name") or sim.get("provider")


def build_items(
    plan: dict, snapshot: dict | None, state: dict[str, dict], today: date
) -> list[dict]:
    start, _ = trip_dates(plan)
    sel = _dict(plan.get("selections"))
    snapshot = snapshot if isinstance(snapshot, dict) else {}

    visa = _visa_facts(plan, snapshot)
    visa_free = _is_visa_free(visa["visa_type"])
    lead = visa_lead_days(visa["processing_time"], visa["visa_type"])
    pack_src = sel.get("packing_list") or snapshot.get("packing_list")

    na = {
        "visa": visa_free,
        "stress_test": not _has_itinerary(sel),
        "checkin": not _has_flight(sel),
    }
    facts = {
        "visa": visa,
        "bookings": {
            "flight": _has_flight(sel),
            "hotel": bool(sel.get("hotel")),
        },
        "stress_test": {
            "score": _dict(_dict(state.get("stress_test")).get("meta")).get("score")
        },
        "sim": {"plan_name": _sim_name(sel)},
        "money": {"currency": _currency_code(plan, snapshot)},
        "packing": {"items": _count_pack_items(pack_src)},
        "offline_pack": {"saved_at": _dict(state.get("offline_pack")).get("done_at")},
    }

    items = []
    for item_id, offset in _ORDER:
        if item_id == "visa":
            offset = lead if lead is not None else DEFAULT_VISA_LEAD_DAYS
        due = start - timedelta(days=offset) if start else None
        if na.get(item_id):
            status = "na"
        elif _dict(state.get(item_id)).get("done"):
            status = "done"
        else:
            status = "todo"
        items.append(
            {
                "id": item_id,
                "status": status,
                "auto": item_id in AUTO_ITEMS,
                "due": due.isoformat() if due else None,
                "overdue": bool(due and status == "todo" and due < today),
                "facts": facts.get(item_id, {}),
            }
        )
    return items


def _totals(items: list[dict]) -> dict:
    total = sum(1 for i in items if i["status"] != "na")
    done = sum(1 for i in items if i["status"] == "done")
    return {
        "done": done,
        "total": total,
        "percent": 100 * done // total if total else 0,
        "complete": total > 0 and done == total,
    }


def prep_payload(plan: dict, today: date) -> dict:
    plan_id = plan["id"]
    items = build_items(
        plan,
        trip_snapshot_db.get_snapshot(plan_id),
        trip_prep_db.get_state(plan_id),
        today,
    )
    return {"items": items, **_totals(items)}


def prep_summary(plan: dict, today: date) -> dict:
    """The ``Trip.prep`` object; zeros for a trip without a start date."""
    start, _ = trip_dates(plan)
    if start is None:
        return {"done": 0, "total": 0, "percent": 0, "complete": False}
    return _totals(prep_payload(plan, today)["items"])
