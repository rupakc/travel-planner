"""Price alerts 2.0 routes (``/api/alerts/*``). Contract: docs/Alerts-API.md.
Each later task adds its own routes here."""

import json
import threading
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError

from ...core.ai_quota import daily_quota
from ...core.auth import get_current_user
from ...core.config import settings
from ...core.errors import ApiError
from ...core.rate_limit import rate_limit, require_ai_access
from ...core.trip_access import owned_trip
from ...db import (
    alerts_db,
    fare_watch_db,
    plans_db,
    price_watch_db,
    user_settings_db,
    users_db,
)
from ...services import (
    alert_delivery,
    alert_email,
    alert_moments,
    alert_story,
    alert_suggest,
    fare_watch,
    price_watch,
)
from ...services.price_watch import InvalidSpec

router = APIRouter()


def _prefs_view(user_id: str) -> dict:
    prefs = alerts_db.get_prefs(user_id)
    tz = user_settings_db.get_settings(user_id).get("timezone")
    prefs["timezone"] = tz if alert_delivery._zone(tz) else None
    prefs["quiet_hours_active"] = alert_delivery.quiet_active(prefs, tz)
    return prefs


@router.get("/alerts/preferences")
def get_preferences(user: dict = Depends(get_current_user)):
    return _prefs_view(user["id"])


@router.put("/alerts/preferences")
def put_preferences(body: dict = Body(...), user: dict = Depends(get_current_user)):
    patch = alert_delivery.validate_prefs(body)
    merged = alert_delivery.merge_prefs(alerts_db.get_prefs(user["id"]), patch)
    alerts_db.put_prefs(user["id"], merged)
    return _prefs_view(user["id"])


KINDS = ("flight", "hotel", "activity", "trip")


def _owned(kind: str, watch_id: int, user: dict) -> tuple[dict, list[dict]]:
    if kind not in KINDS:
        raise ApiError(422, "kind_invalid", "That kind of watch doesn't exist.")
    db = fare_watch_db if kind == "flight" else price_watch_db
    watch = db.get_watch_for_user(watch_id, user["id"])
    if watch is None or (kind != "flight" and watch.get("kind") != kind):
        raise ApiError(404, "watch_not_found", "Watch not found.")
    return watch, db.get_history(watch_id)


def _story(kind: str, watch: dict, history: list[dict], user: dict) -> dict:
    story = alert_story.build_story(
        kind,
        watch,
        history,
        live_prices=bool(settings.serpapi_key),
        now=alert_story._utcnow(),
    )
    story["caught"] = alert_story.caught_for(kind, watch["id"], user["id"])
    return story


@router.get("/alerts/watches/{kind}/{watch_id}/story")
async def watch_story(kind: str, watch_id: int, user: dict = Depends(get_current_user)):
    watch, history = _owned(kind, watch_id, user)
    return _story(kind, watch, history, user)


@router.post(
    "/alerts/watches/{kind}/{watch_id}/advice",
    dependencies=[
        Depends(require_ai_access),
        Depends(rate_limit("light_ai")),
        Depends(daily_quota("light_ai")),
    ],
)
async def watch_advice(
    kind: str, watch_id: int, user: dict = Depends(get_current_user)
):
    watch, history = _owned(kind, watch_id, user)
    if kind != "flight":
        raise ApiError(
            422, "advice_unsupported", "Tips are only available for flight watches."
        )
    story = _story(kind, watch, history, user)
    row = users_db.get_user_by_id(user["id"]) or {}
    return await alert_story.advice(watch, story, locale=row.get("locale"))


@router.get("/alerts/summary")
def savings_summary(user: dict = Depends(get_current_user)) -> dict:
    """The caller's savings tally ("caught a drop of $X")."""
    return alert_moments.summary(user["id"])


# ── BEGIN quick-watch (Task 7) ────────────────────────────────────────────────

_quick_lock = threading.Lock()  # a double tap must create one watch


class QuickWatchBody(BaseModel):
    kind: Literal["flight", "hotel", "activity", "trip"]
    title: str = Field(..., min_length=1, max_length=120)
    subtitle: str | None = Field(None, max_length=160)
    spec: dict
    plan_id: int | None = None
    surface: Literal["results", "chat", "trip", "suggest"]


def _spec_invalid(detail: str) -> ApiError:
    return ApiError(422, "spec_invalid", detail)


def _quick_flight(body: QuickWatchBody, user: dict, serialize) -> tuple[dict, bool]:
    from .fare_watches import TripFields, _resolve, _trip_from_plan

    try:
        trip = TripFields(**{**body.spec, "plan_id": None})
        plan_id = body.plan_id or body.spec.get("plan_id")
        if isinstance(plan_id, int) and not isinstance(plan_id, bool):
            trip = _trip_from_plan(plan_id, user)
        else:
            plan_id = None
        req = _resolve(trip)
    except (ValidationError, TypeError) as exc:
        raise _spec_invalid("That trip can't be watched.") from exc
    except HTTPException as exc:
        if exc.status_code == 404:
            raise ApiError(404, "trip_not_found", str(exc.detail)) from exc
        raise _spec_invalid(str(exc.detail)) from exc
    now = fare_watch.utcnow()
    if req.departure_date <= now.date():
        raise _spec_invalid("This trip departs too soon to watch its fare.")
    if req.return_date and req.return_date < req.departure_date:
        raise _spec_invalid("The return date is before the departure date.")
    dep = str(req.departure_date)
    ret = str(req.return_date) if req.return_date else None
    existing = fare_watch_db.find_watch(
        user["id"],
        req.origin_iata,
        req.destination_iata,
        dep,
        ret,
        req.num_travelers,
    )
    if existing and existing["status"] != "expired":
        return serialize(existing), True
    _require_room(user)
    watch = fare_watch_db.create_watch(
        user["id"],
        {
            "plan_id": plan_id,
            "origin_code": req.origin_iata,
            "destination_code": req.destination_iata,
            "origin_label": req.origin,
            "destination_label": req.destination,
            "departure_date": dep,
            "return_date": ret,
            "num_travelers": req.num_travelers,
            "alert_mode": "any_drop",
            "email_enabled": False,
            "pending_first_check": True,
        },
        now=now,
    )
    return serialize(watch), False


def _quick_price(body: QuickWatchBody, user: dict, serialize) -> tuple[dict, bool]:
    source = price_watch.get_source(body.kind)
    if source is None:
        raise _spec_invalid("We can't watch prices of this kind yet.")
    spec = dict(body.spec)
    if body.plan_id is not None:
        spec.setdefault("plan_id", body.plan_id)
    from .price_watches import MAX_SPEC_BYTES

    if len(json.dumps(spec, default=str)) > MAX_SPEC_BYTES:
        raise _spec_invalid("That request is too large.")
    try:
        key = source.match_key(spec)
        if (
            body.kind == "trip"
        ):  # the plan must be the caller's (as the first look needs)
            plan = plans_db.get_plan(int(spec["plan_id"]))
            if not plan or plan.get("username") != user.get("username"):
                raise ApiError(404, "trip_not_found", "Plan not found")
    except InvalidSpec as exc:
        raise _spec_invalid(str(exc)) from exc
    existing = price_watch_db.find_watch(user["id"], body.kind, key) if key else None
    if existing and existing["status"] != "expired":
        return serialize(existing), True
    _require_room(user)
    watch = price_watch.record_pending(
        source, spec, user, body.title, body.subtitle, spec.get("plan_id")
    )
    return serialize(watch), False


def _require_room(user: dict) -> None:
    if price_watch.limit_reached(user["id"]):
        raise ApiError(409, "watch_limit", price_watch.limit_message())


@router.post("/alerts/quick-watch")
def quick_watch(body: QuickWatchBody, user: dict = Depends(get_current_user)):
    """One-tap watch: a pending row, no live look (the scheduler makes the
    first one, which is the baseline and never alerts)."""
    if not settings.serpapi_key:
        raise ApiError(
            503,
            "live_prices_off",
            "Price watches need live prices, which aren't set up.",
        )
    from . import fare_watches, price_watches

    serialize = (
        fare_watches.serialize if body.kind == "flight" else price_watches.serialize
    )
    make = _quick_flight if body.kind == "flight" else _quick_price
    with _quick_lock:
        watch, existing = make(body, user, serialize)
    return JSONResponse(
        status_code=200 if existing else 201,
        content=jsonable_encoder(
            {"kind": body.kind, "watch": watch, "existing": existing}
        ),
    )


# ── END quick-watch ───────────────────────────────────────────────────────────


# ── BEGIN digest unsubscribe (Task 10) ────────────────────────────────────────


def _digest_page(title: str, body: str, form: str = "", status: int = 200):
    from .fare_watches import html_page

    return HTMLResponse(html_page(title, body, form), status_code=status)


@router.get("/alerts/digest/unsubscribe", response_class=HTMLResponse)
def digest_unsubscribe_confirm(token: str = Query("")):
    """Confirmation page only: link scanners follow every GET."""
    if alert_email.read_digest_unsubscribe_token(token) is None:
        return _digest_page(
            "This link isn't valid", "It may have been copied incompletely.", "", 400
        )
    import html

    action = html.escape(f"/api/alerts/digest/unsubscribe?token={token}")
    form = (
        f'<form method="post" action="{action}" style="margin:0 0 16px">'
        "<button type='submit' style='background:#0284c7;color:#fff;border:0;"
        "border-radius:999px;padding:10px 18px;font-weight:600;font-size:14px;"
        "cursor:pointer'>Stop the weekly digest</button></form>"
    )
    return _digest_page(
        "Stop the weekly digest?",
        "Your watches keep running; only the weekly summary stops.",
        form,
    )


@router.post("/alerts/digest/unsubscribe", response_class=HTMLResponse)
def digest_unsubscribe(token: str = Query("")):
    """Turns the digest off without login (also the RFC 8058 one-click POST)."""
    user_id = alert_email.read_digest_unsubscribe_token(token)
    if user_id is None:
        return _digest_page(
            "This link isn't valid", "It may have been copied incompletely.", "", 400
        )
    prefs = alerts_db.get_prefs(user_id)
    prefs["digest_weekly"] = False
    alerts_db.put_prefs(user_id, prefs)
    return _digest_page(
        "Done: no more weekly digests",
        "You can turn the digest back on any time in your alert settings.",
    )


# ── END digest unsubscribe ────────────────────────────────────────────────────

# ── BEGIN suggestions (Task 9) ────────────────────────────────────────────────


@router.get("/alerts/suggestions")
def watch_suggestions(plan_id: int, user: dict = Depends(get_current_user)) -> dict:
    """Watches worth setting up for a saved plan (local: no SerpAPI call)."""
    plan = owned_trip(plan_id, user)
    return {
        "suggestions": alert_suggest.suggestions(plan, user),
        "live_prices": bool(settings.serpapi_key),
    }


# ── END suggestions ───────────────────────────────────────────────────────────
