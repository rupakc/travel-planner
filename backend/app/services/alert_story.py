"""Price story read model and the cached advisor tip (Task 4).

``build_story`` is pure (no network, no LLM): it reads a watch and its stored
history only. Rules: docs/Alerts-API.md; golden cases:
tests/fixtures/alerts/story_cases.json.
"""

import math
from datetime import UTC, datetime, timedelta

from ..agents.pricing_advisor_agent import PricingAdvisorAgent
from ..core import llm
from ..core.config import settings
from ..core.errors import ApiError
from ..db import alerts_db
from ..schemas.request import TravelSearchRequest
from . import price_rules, price_watch

MAX_POINTS = 90
HISTORY_TYPICAL_MIN_POINTS = 6
STALE_DAYS = 3
ADVICE_TTL = timedelta(hours=24)


def _step(kind: str) -> price_rules.Step:
    """Flights use FARE_STEP; other kinds ask their registered price source."""
    if kind == "flight":
        return price_rules.FARE_STEP
    source = price_watch.get_source(kind)
    if source is None:
        price_watch.register_builtin_sources()
        source = price_watch.get_source(kind)
    return price_watch.step_for(source) if source else price_rules.DEFAULT_STEP


def _parse(ts) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _iso(ts) -> str | None:
    dt = _parse(ts)
    return (
        dt.strftime("%Y-%m-%dT%H:%M:%S.%f").rstrip("0").rstrip(".") + "Z"
        if dt
        else None
    )


def _num(v: float) -> float:
    return round(float(v), 2)


def typical_from_points(prices: list[float]) -> dict | None:
    """Nearest-rank p25/p75 of the observed prices, with at least 6 points."""
    n = len(prices)
    if n < HISTORY_TYPICAL_MIN_POINTS:
        return None
    s = sorted(prices)
    return {
        "low": s[math.ceil(0.25 * n) - 1],
        "high": s[math.ceil(0.75 * n) - 1],
        "source": "history",
    }


def verdict(price: float | None, typical: dict | None) -> str | None:
    if price is None or not typical:
        return None
    lo, hi = typical["low"], typical["high"]
    if price < lo:
        return "great"
    if price <= lo + 0.25 * (hi - lo):
        return "good"
    if price <= hi:
        return "typical"
    return "high"


def _observed_points(kind: str, history: list[dict]) -> list[dict]:
    out = []
    for h in history:
        price = h.get("price")
        if price is None:
            continue
        if kind != "flight":
            obs = h.get("observed")
            if isinstance(obs, dict) and (
                obs.get("status") == "unavailable" or obs.get("observed") is False
            ):
                continue
        at = _iso(h.get("checked_at"))
        if at:
            out.append({"at": at, "price": _num(price)})
    return out[-MAX_POINTS:] if len(out) > MAX_POINTS else out


def _estimate(kind: str, watch: dict) -> dict | None:
    if kind == "flight":
        return None
    subject = watch.get("subject") or {}
    for key in ("estimate_total", "estimate_price"):
        v = subject.get(key)
        if isinstance(v, int | float) and not isinstance(v, bool) and v > 0:
            return {"price": _num(v), "source": "ai_estimate"}
    return None


def _advice_code(
    *, points, target, step, verdict_, lowest, latest, live_prices, days_ago, now
) -> dict:
    def out(code, **params):
        return {"code": code, "params": params}

    if not points:
        return out("pending")
    if not live_prices and days_ago is not None and days_ago > STALE_DAYS:
        return out("checks_paused", days=days_ago)
    if target is not None:
        if latest <= target:
            return out("below_target", by=_num(target - latest))
        if latest - target <= step(target):
            return out("near_target", gap=_num(latest - target))
    if latest == lowest and len(points) >= 3:
        return out("at_lowest")
    if verdict_ in ("great", "good"):
        return out("below_typical")
    if verdict_ == "typical":
        return out("within_typical")
    if verdict_ == "high":
        return out("above_typical")
    last5 = [p["price"] for p in points[-5:]]
    if len(last5) == 5 and max(last5) - min(last5) <= 0.01 * min(last5):
        d0, d1 = _parse(points[-5]["at"]), _parse(points[-1]["at"])
        return out("steady", days=int((d1 - d0).total_seconds() // 86400))
    return out("few_checks", n=len(points))


def build_story(
    kind: str, watch: dict, history: list[dict], *, live_prices: bool, now: datetime
) -> dict:
    points = _observed_points(kind, history)
    latest = points[-1] if points else None
    lowest = None
    for p in points:  # the newest of equal lows
        if lowest is None or p["price"] <= lowest["price"]:
            lowest = p

    if kind == "flight":
        lo, hi = watch.get("google_typical_low"), watch.get("google_typical_high")
        typical = (
            {"low": _num(lo), "high": _num(hi), "source": "google"}
            if lo is not None and hi is not None
            else None
        )
    else:
        typical = typical_from_points([p["price"] for p in points])
        if typical:
            typical = {
                **typical,
                "low": _num(typical["low"]),
                "high": _num(typical["high"]),
            }

    checked = _parse(watch.get("last_checked_at")) or (
        _parse(latest["at"]) if latest else None
    )
    days_ago = (
        max(0, int((now - checked).total_seconds() // 86400)) if checked else None
    )
    stale = (not live_prices) and days_ago is not None and days_ago > STALE_DAYS

    v = None if stale else verdict(latest["price"] if latest else None, typical)
    mode = watch.get("alert_mode") or "any_drop"
    target = watch.get("target_price") if mode == "below_target" else None
    target = _num(target) if target is not None else None

    advice = _advice_code(
        points=points,
        target=target,
        step=_step(kind),
        verdict_=v,
        lowest=lowest["price"] if lowest else None,
        latest=latest["price"] if latest else None,
        live_prices=live_prices,
        days_ago=days_ago,
        now=now,
    )
    baseline = watch.get("baseline_price")
    return {
        "kind": kind,
        "watch_id": watch.get("id"),
        "currency": "USD" if kind == "flight" else (watch.get("currency") or "USD"),
        "mode": mode,
        "target": target,
        "points": points,
        "baseline": _num(baseline) if baseline is not None else None,
        "latest": latest,
        "lowest": lowest,
        "typical": typical,
        "verdict": v,
        "advice": advice,
        "checked_at": _iso(watch.get("last_checked_at"))
        or (latest["at"] if latest else None),
        "checked_days_ago": days_ago,
        "next_check_at": _iso(watch.get("next_check_at")),
        "pending_first_check": bool(watch.get("pending_first_check", False)),
        "estimate": _estimate(kind, watch),
        "caught": None,
        "live_prices": live_prices,
    }


def caught_for(kind: str, watch_id: int, user_id: str) -> float | None:
    """max(0, baseline - lowest alerted observed price) from alert_savings."""
    rows = [
        r
        for r in alerts_db.savings_rows(user_id)
        if r["watch_kind"] == kind
        and r["watch_id"] == watch_id
        and r.get("to_price") is not None
        and r.get("baseline") is not None
    ]
    if not rows:
        return None
    return _num(max(0.0, rows[0]["baseline"] - min(r["to_price"] for r in rows)))


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _stamp(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


async def advice(watch: dict, story: dict, *, locale: str | None = None) -> dict:
    """The advisor tip for a flight watch: cached 24 h in ``alert_advice``,
    built from the stored latest/lowest/typical only (no SerpAPI)."""
    now = _utcnow()
    kind, watch_id = story["kind"], watch["id"]
    cached = alerts_db.get_advice(kind, watch_id)
    gen = _parse(cached["generated_at"]) if cached else None
    if cached and gen and now - gen < ADVICE_TTL:
        return {
            "tip": cached["tip"],
            "source": "ai",
            "generated_at": _iso(cached["generated_at"]),
            "cached": True,
        }

    if not story.get("points"):
        raise ApiError(
            422, "advice_no_data", "There is no price history to advise on yet."
        )
    typical = story.get("typical")
    if typical:
        avg = (typical["low"] + typical["high"]) / 2
    elif story.get("latest"):
        avg = story["latest"]["price"]
    else:
        avg = story["lowest"]["price"] if story.get("lowest") else None
    try:
        request = TravelSearchRequest(
            origin=watch["origin_code"],
            destination=watch["destination_code"],
            departure_date=watch["departure_date"],
            return_date=watch.get("return_date"),
            nationality="Not specified",
            num_travelers=watch.get("num_travelers") or 1,
            locale=locale
            if locale in ("en", "es", "de", "fr", "hi", "zh", "bn")
            else None,
        )
    except Exception:
        raise ApiError(422, "spec_invalid", "This watch can't be advised on.") from None

    agent = PricingAdvisorAgent(agents_dir=settings.agents_dir)
    result = await agent.run(request, avg_price=avg)
    if not isinstance(result, dict) or result.get("error"):
        code = (result or {}).get("error_code") if isinstance(result, dict) else None
        if code in (llm.SPEND_CAP_CODE, llm.BILLING_CODE):
            raise ApiError(503, code, result.get("error") or "AI limit reached.")
        raise ApiError(502, "advice_failed", "We couldn't get a tip right now.")
    tip = (
        result.get("recommendation_detail")
        or result.get("recommendation")
        or result.get("price_status_label")
    )
    if not isinstance(tip, str) or not tip.strip():
        raise ApiError(502, "advice_failed", "We couldn't get a tip right now.")
    stamp = _stamp(now)
    alerts_db.put_advice(kind, watch_id, tip.strip(), stamp)
    return {"tip": tip.strip(), "source": "ai", "generated_at": stamp, "cached": False}
