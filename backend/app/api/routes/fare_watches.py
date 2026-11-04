"""Fare watches: watch a trip's live fare and get told when it drops.

Every route except the email unsubscribe link needs a signed-in user and
only ever sees that user's watches (404 for anyone else's).
"""

import html
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, ValidationError, model_validator

from ...core.auth import get_current_user
from ...core.config import settings
from ...core.rate_limit import rate_limit
from ...db import fare_watch_db
from ...db.plans_db import get_plan
from ...schemas.request import TravelSearchRequest
from ...services import alert_email, fare_watch
from ...services.serp_flights import _google_flights_url

router = APIRouter()

_HIDDEN = ("user_id", "lease_until", "last_error")  # last_error → "problem"
MULTI_CITY = "Fare watch works for single-destination trips for now"
NO_LIVE_FARES = (
    "Fare watch needs live flight prices, which aren't set up on this server."
)


class TripFields(BaseModel):
    origin: str | None = Field(None, max_length=200)
    destination: str | None = Field(None, max_length=200)
    destinations: list[str] | None = None
    departure_date: date | None = None
    return_date: date | None = None
    num_travelers: int = Field(1, ge=1, le=20)


class FareWatchCreate(TripFields):
    plan_id: int | None = None
    alert_mode: Literal["any_drop", "below_target"] = "any_drop"
    target_price: float | None = Field(None, gt=0, le=1_000_000)
    flexible_days: Literal[0, 3] = 0
    email_enabled: bool = False

    @model_validator(mode="after")
    def _target_for_target_mode(self) -> "FareWatchCreate":
        if self.alert_mode == "below_target" and self.target_price is None:
            raise ValueError("Set a target price to be told when it's below it")
        return self


class FareWatchUpdate(BaseModel):
    status: Literal["active", "paused"] | None = None
    alert_mode: Literal["any_drop", "below_target"] | None = None
    target_price: float | None = Field(None, gt=0, le=1_000_000)
    flexible_days: Literal[0, 3] | None = None
    email_enabled: bool | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def serialize(watch: dict, **extra) -> dict:
    out = {k: v for k, v in watch.items() if k not in _HIDDEN}
    out["problem"] = fare_watch.friendly_problem(watch.get("last_error"))
    out["history"] = fare_watch_db.get_history(watch["id"])
    out["booking_url"] = _google_flights_url(
        watch["origin_code"],
        watch["destination_code"],
        watch["departure_date"],
        watch.get("return_date"),
    )
    out.update(extra)
    return out


def _owned(watch_id: int, user: dict) -> dict:
    watch = fare_watch_db.get_watch_for_user(watch_id, user["id"])
    if watch is None:
        raise HTTPException(status_code=404, detail="Fare watch not found")
    return watch


def _require_live_fares() -> None:
    if not settings.serpapi_key:
        raise HTTPException(status_code=503, detail=NO_LIVE_FARES)


def _limit_reached(user: dict) -> bool:
    return fare_watch_db.count_active(user["id"]) >= (
        settings.fare_watch_max_active_per_user
    )


def _limit_error() -> HTTPException:
    n = settings.fare_watch_max_active_per_user
    return HTTPException(
        status_code=409,
        detail=f"You're already watching {n} fares — pause or remove one "
        "to watch another.",
    )


def _check_email_allowed(user: dict) -> None:
    if not alert_email.email_available():
        raise HTTPException(
            status_code=422, detail="Email alerts aren't available on this server."
        )
    if not user.get("email"):
        raise HTTPException(
            status_code=422,
            detail="Add an email address in Preferences to get email alerts.",
        )


def _resolve(trip: TripFields) -> TravelSearchRequest:
    """The trip as a search request with resolved airport codes."""
    if not (trip.origin and trip.destination and trip.departure_date):
        raise HTTPException(
            status_code=422,
            detail="Origin, destination and departure date are required.",
        )
    try:
        req = TravelSearchRequest(
            origin=trip.origin,
            destination=trip.destination,
            destinations=trip.destinations,
            departure_date=trip.departure_date,
            return_date=trip.return_date,
            num_travelers=trip.num_travelers,
            nationality="",
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if req.is_multi_city:
        raise HTTPException(status_code=422, detail=MULTI_CITY)
    for typed, code in (
        (trip.origin, req.origin_iata),
        (trip.destination, req.destination_iata),
    ):
        if not code:
            raise HTTPException(
                status_code=422, detail=f"We couldn't find an airport for “{typed}”."
            )
    return req


def _trip_from_plan(plan_id: int, user: dict) -> TripFields:
    plan = get_plan(plan_id)
    if not plan or plan["username"] != user["username"]:
        raise HTTPException(status_code=404, detail="Plan not found")
    data = plan.get("search_data") or {}
    try:
        return TripFields(
            origin=data.get("origin"),
            destination=data.get("destination"),
            destinations=data.get("destinations"),
            departure_date=data.get("departure_date"),
            return_date=data.get("return_date") or None,
            num_travelers=data.get("num_travelers") or 1,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail="This plan's trip details are incomplete."
        ) from exc


def _seconds_to_next_utc_day(now: datetime) -> int:
    nxt = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    return int((nxt.replace(tzinfo=now.tzinfo) - now).total_seconds())


# ── Routes ────────────────────────────────────────────────────────────────────


def _unsubscribe_target(token: str) -> tuple[int | None, dict | None]:
    watch_id = alert_email.read_unsubscribe_token(token)
    if watch_id is None:
        return None, None
    return watch_id, fare_watch_db.get_watch(watch_id)


_BAD_LINK = ("This link isn't valid", "It may have been copied incompletely.")


@router.get("/fare-watches/unsubscribe", response_class=HTMLResponse)
def unsubscribe_confirm(token: str = Query("")):
    """The link in alert emails: a confirmation page only. Link scanners and
    prefetchers follow every GET, so the change itself needs the POST."""
    watch_id, watch = _unsubscribe_target(token)
    if watch_id is None:
        return HTMLResponse(_page(*_BAD_LINK), status_code=400)
    if watch is None:
        return HTMLResponse(
            _page("Nothing to stop", "That fare watch no longer exists.")
        )
    route = fare_watch.route_label(watch)
    action = html.escape(f"/api/fare-watches/unsubscribe?token={token}")
    form = (
        f'<form method="post" action="{action}" style="margin:0 0 16px">'
        "<button type='submit' style='background:#0284c7;color:#fff;border:0;"
        "border-radius:999px;padding:10px 18px;font-weight:600;font-size:14px;"
        "cursor:pointer'>Stop emails for this fare</button></form>"
    )
    return HTMLResponse(
        _page(
            f"Stop emails about {route}?",
            "We'll keep watching this fare in the app; only the emails stop. "
            "You can turn them back on any time.",
            form,
        )
    )


@router.post("/fare-watches/unsubscribe", response_class=HTMLResponse)
def unsubscribe(token: str = Query("")):
    """Turns email off for one watch, without login: the confirmation form
    above, or a mail client's RFC 8058 one-click POST
    ("List-Unsubscribe=One-Click")."""
    watch_id, watch = _unsubscribe_target(token)
    if watch_id is None:
        return HTMLResponse(_page(*_BAD_LINK), status_code=400)
    if watch is None:
        return HTMLResponse(
            _page("Nothing to stop", "That fare watch no longer exists.")
        )
    fare_watch_db.update_watch(watch_id, email_enabled=False)
    route = fare_watch.route_label(watch)
    return HTMLResponse(
        _page(
            "Done — we won't email you about this fare",
            f"Emails for {route} are off. We'll keep watching it in the app, "
            "where you can turn emails back on any time.",
        )
    )


def _page(title: str, body: str, form: str = "") -> str:
    link = html.escape(settings.app_base_url.rstrip("/") + "/alerts")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title, quote=False)}</title></head>"
        "<body style='font-family:system-ui,sans-serif;background:#f0f9ff;"
        "color:#0f172a;display:flex;min-height:100vh;align-items:center;"
        "justify-content:center;margin:0;padding:16px'>"
        "<main style='max-width:420px;background:#fff;border:1px solid #e2e8f0;"
        "border-radius:16px;padding:28px'>"
        f"<h1 style='font-size:20px;margin:0 0 8px'>{html.escape(title, quote=False)}</h1>"
        f"<p style='color:#475569;margin:0 0 16px'>{html.escape(body, quote=False)}</p>"
        f"{form}"
        f"<a href='{link}' style='color:#0284c7;font-weight:600'>Open your alerts</a>"
        "</main></body></html>"
    )


@router.get("/fare-watches")
def list_fare_watches(user: dict = Depends(get_current_user)):
    return [serialize(w) for w in fare_watch_db.list_watches(user["id"])]


@router.post("/fare-watches/match")
def match_fare_watch(trip: TripFields, user: dict = Depends(get_current_user)):
    """The user's watch for this search's trip, if any (no live lookups)."""
    try:
        req = _resolve(trip)
    except HTTPException:
        return {"watch": None}
    watch = fare_watch_db.find_watch(
        user["id"],
        req.origin_iata,
        req.destination_iata,
        str(req.departure_date),
        str(req.return_date) if req.return_date else None,
        req.num_travelers,
    )
    return {"watch": serialize(watch) if watch else None}


@router.post("/fare-watches", dependencies=[Depends(rate_limit("light_ai"))])
async def create_fare_watch(
    body: FareWatchCreate, user: dict = Depends(get_current_user)
):
    _require_live_fares()
    trip = _trip_from_plan(body.plan_id, user) if body.plan_id else body
    req = _resolve(trip)
    now = fare_watch.utcnow()
    if req.departure_date <= now.date():
        raise HTTPException(
            status_code=422, detail="This trip departs too soon to watch its fare."
        )
    if req.return_date and req.return_date < req.departure_date:
        raise HTTPException(
            status_code=422, detail="The return date is before the departure date."
        )
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
        return serialize(existing, already_watching=True)
    if body.email_enabled:
        _check_email_allowed(user)
    if _limit_reached(user):
        raise _limit_error()

    watch = fare_watch_db.create_watch(
        user["id"],
        {
            "plan_id": body.plan_id,
            "origin_code": req.origin_iata,
            "destination_code": req.destination_iata,
            "origin_label": req.origin,
            "destination_label": req.destination,
            "departure_date": dep,
            "return_date": ret,
            "num_travelers": req.num_travelers,
            "flexible_days": body.flexible_days,
            "alert_mode": body.alert_mode,
            "target_price": body.target_price,
            "email_enabled": body.email_enabled,
        },
        now=now,
        lease_until=now + fare_watch.LEASE,  # ours until the baseline check ends
    )
    # Baseline now when today's budget allows; otherwise the scheduler takes
    # it (the watch is due immediately).
    await fare_watch.check_watch(
        watch["id"], now=now, api_key=settings.serpapi_key, manual=True
    )
    return serialize(fare_watch_db.get_watch(watch["id"]), already_watching=False)


@router.get("/fare-watches/{watch_id}")
def get_fare_watch(watch_id: int, user: dict = Depends(get_current_user)):
    return serialize(_owned(watch_id, user))


@router.patch("/fare-watches/{watch_id}")
def update_fare_watch(
    watch_id: int, body: FareWatchUpdate, user: dict = Depends(get_current_user)
):
    watch = _owned(watch_id, user)
    now = fare_watch.utcnow()
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    mode = changes.get("alert_mode", watch["alert_mode"])
    target = changes.get("target_price", watch.get("target_price"))
    if mode == "below_target" and target is None:
        raise HTTPException(
            status_code=422, detail="Set a target price to be told when it's below it"
        )
    if changes.get("email_enabled"):
        _check_email_allowed(user)
    fields: dict = {
        k: changes[k]
        for k in ("alert_mode", "target_price", "flexible_days", "email_enabled")
        if k in changes
    }
    status = changes.get("status")
    if status == "paused" and watch["status"] in ("active", "error"):
        fields["status"] = "paused"
    elif status == "active" and watch["status"] != "active":
        if watch["status"] == "expired":
            raise HTTPException(
                status_code=409, detail="This trip has departed, so its watch ended."
            )
        if _limit_reached(user):
            raise _limit_error()
        fields["status"] = "active"
        if watch["status"] == "error":  # "Retry": check again right away
            fields.update(failure_count=0, last_error=None)
            fields["next_check_at"] = now.isoformat()
    if fields:
        fields["updated_at"] = now.isoformat()
        watch = fare_watch_db.update_watch(watch_id, **fields)
    return serialize(watch)


@router.delete("/fare-watches/{watch_id}")
def delete_fare_watch(watch_id: int, user: dict = Depends(get_current_user)):
    _owned(watch_id, user)
    fare_watch_db.delete_watch(watch_id, user["id"])
    return {"deleted": True}


@router.post(
    "/fare-watches/{watch_id}/check",
    dependencies=[Depends(rate_limit("light_ai"))],
)
async def check_fare_watch_now(watch_id: int, user: dict = Depends(get_current_user)):
    """ "Check now": one live look, subject to the daily SerpAPI budget."""
    watch = _owned(watch_id, user)
    _require_live_fares()
    if watch["status"] == "expired":
        raise HTTPException(
            status_code=409, detail="This trip has departed, so its watch ended."
        )
    now = fare_watch.utcnow()
    if not fare_watch_db.claim_watch(watch_id, now, now + fare_watch.LEASE):
        raise HTTPException(
            status_code=409,
            detail="We're checking this fare right now — give it a moment.",
        )
    outcome = await fare_watch.check_watch(
        watch_id, now=now, api_key=settings.serpapi_key, manual=True
    )
    if outcome.status == "budget_exhausted":
        wait = _seconds_to_next_utc_day(now)
        detail = (
            "You've used your share of today's live fare checks — your watches "
            "will be checked again tomorrow."
            if outcome.reason == "user"
            else "We've used today's live fare checks — we'll check again tomorrow."
        )
        raise HTTPException(
            status_code=429, detail=detail, headers={"Retry-After": str(wait)}
        )
    return serialize(
        fare_watch_db.get_watch(watch_id),
        check_status=outcome.status,
        notification=(
            {k: v for k, v in outcome.notification.items() if k != "user_id"}
            if outcome.notification
            else None
        ),
    )
