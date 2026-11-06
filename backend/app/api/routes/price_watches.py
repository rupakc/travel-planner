"""Price watches: watch a hotel's, an activity's or a whole trip's price.

The kind (``hotel`` | ``activity`` | ``trip``) picks the registered price
source (``services.price_watch.get_source``); the kind-specific spec rides
under the kind's own key, e.g. ``{"kind": "hotel", "hotel": {...}}``
(a top-level ``plan_id`` is passed into the spec too).

Every route except the email unsubscribe link needs a signed-in user and
only ever sees that user's watches (404 for anyone else's).
"""

import html
import json
import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...core.auth import get_current_user
from ...core.config import settings
from ...core.rate_limit import rate_limit
from ...db import fare_watch_db, price_watch_db
from ...services import alert_email, fare_watch, price_watch
from ...services.price_watch import InvalidSpec, NoLivePrice

logger = logging.getLogger(__name__)
router = APIRouter()

_HIDDEN = ("user_id", "lease_until", "last_error", "match_key", "reference_looks")
MAX_SPEC_BYTES = 8_000
NO_LIVE_PRICES = "Price watch needs live prices, which aren't set up on this server."
UNKNOWN_KIND = "We can't watch prices of this kind yet."


class _Spec(BaseModel):
    """The kind and its spec: ``{"kind": "hotel", "hotel": {...}}``."""

    model_config = ConfigDict(extra="allow")

    kind: str = Field(..., min_length=1, max_length=20, pattern=r"^[a-z_]+$")
    plan_id: int | None = None

    def spec(self) -> dict:
        raw = (self.model_extra or {}).get(self.kind)
        spec = dict(raw) if isinstance(raw, dict) else {}
        if self.plan_id is not None:
            spec.setdefault("plan_id", self.plan_id)
        return spec


class PriceWatchCreate(_Spec):
    alert_mode: Literal["any_drop", "below_target"] = "any_drop"
    target_price: float | None = Field(None, gt=0, le=1_000_000)
    # The currency the target was typed in: a below-target watch whose live
    # price is in another currency is refused (422 target_currency_mismatch)
    target_currency: str | None = Field(None, min_length=1, max_length=8)
    email_enabled: bool = False

    @model_validator(mode="after")
    def _target_for_target_mode(self) -> "PriceWatchCreate":
        if self.alert_mode == "below_target" and self.target_price is None:
            raise ValueError("Set a target price to be told when it's below it")
        return self


class PriceWatchUpdate(BaseModel):
    status: Literal["active", "paused"] | None = None
    alert_mode: Literal["any_drop", "below_target"] | None = None
    target_price: float | None = Field(None, gt=0, le=1_000_000)
    email_enabled: bool | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def serialize(watch: dict, **extra) -> dict:
    out = {k: v for k, v in watch.items() if k not in _HIDDEN}
    out["problem"] = price_watch.friendly_problem(watch.get("last_error"))
    base, target = watch.get("baseline_price"), watch.get("target_price")
    out["already_below_target"] = (
        watch.get("alert_mode") == "below_target"
        and base is not None
        and target is not None
        and base <= target
    )
    out["link"] = (watch.get("last_observation") or {}).get("link")
    out["history"] = price_watch_db.get_history(watch["id"])
    out.update(extra)
    return out


def _owned(watch_id: int, user: dict) -> dict:
    watch = price_watch_db.get_watch_for_user(watch_id, user["id"])
    if watch is None:
        raise HTTPException(status_code=404, detail="Price watch not found")
    return watch


def _require_live_prices() -> None:
    if not settings.serpapi_key:
        raise HTTPException(status_code=503, detail=NO_LIVE_PRICES)


def _source(kind: str) -> price_watch.PriceSource:
    source = price_watch.get_source(kind)
    if source is None:
        raise HTTPException(status_code=422, detail=UNKNOWN_KIND)
    return source


def _spec(body: _Spec) -> dict:
    spec = body.spec()
    if len(json.dumps(spec, default=str)) > MAX_SPEC_BYTES:
        raise HTTPException(status_code=422, detail="That request is too large.")
    return spec


def _invalid(exc: InvalidSpec) -> HTTPException:
    """422 with the source's message — or the status it asks for (a trip
    watch's plan that isn't the caller's is a 404)."""
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _limit_error() -> HTTPException:
    return HTTPException(status_code=409, detail=price_watch.limit_message())


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


def _busy(now, reason: str = "global") -> HTTPException:
    detail = (
        "You've used your share of today's live price checks — try again tomorrow."
        if reason == "user"
        else "We've used today's live price checks — try again tomorrow."
    )
    return HTTPException(
        status_code=429,
        detail=detail,
        headers={"Retry-After": str(price_watch.seconds_to_next_utc_day(now))},
    )


def _no_live_price(result: NoLivePrice) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": result.message,
            "code": "no_live_price",
            "message": result.message,
            "suggestions": result.suggestions[:3],
            "estimate": result.estimate,
        },
    )


def _target_currency_mismatch(result) -> JSONResponse:
    """The live price is in another currency than the typed target: nothing
    is created; the client asks again in that currency (the retry reuses the
    cached look, so it costs no live call)."""
    currency = result.currency or "USD"
    price = result.baseline.price
    message = (
        f"This is priced in {currency} (now "
        f"{price_watch.format_price(price, currency)}). "
        f"Enter your target in {currency}."
    )
    return JSONResponse(
        status_code=422,
        content={
            "detail": message,
            "code": "target_currency_mismatch",
            "message": message,
            "currency": currency,
            "price": price,
            "unit_price": result.baseline.unit_price,
        },
    )


# ── Unsubscribe (no login: the link in alert emails) ──────────────────────────


def _unsubscribe_target(token: str) -> tuple[int | None, dict | None]:
    watch_id = alert_email.read_unsubscribe_token(
        token, alert_email.PRICE_UNSUB_PURPOSE
    )
    if watch_id is None:
        return None, None
    return watch_id, price_watch_db.get_watch(watch_id)


_BAD_LINK = ("This link isn't valid", "It may have been copied incompletely.")
_GONE = ("Nothing to stop", "That price watch no longer exists.")


@router.get("/price-watches/unsubscribe", response_class=HTMLResponse)
def unsubscribe_confirm(token: str = Query("")):
    """Confirmation page only: link scanners follow every GET."""
    from .fare_watches import html_page

    watch_id, watch = _unsubscribe_target(token)
    if watch_id is None:
        return HTMLResponse(html_page(*_BAD_LINK), status_code=400)
    if watch is None:
        return HTMLResponse(html_page(*_GONE))
    action = html.escape(f"/api/price-watches/unsubscribe?token={token}")
    form = (
        f'<form method="post" action="{action}" style="margin:0 0 16px">'
        "<button type='submit' style='background:#0284c7;color:#fff;border:0;"
        "border-radius:999px;padding:10px 18px;font-weight:600;font-size:14px;"
        "cursor:pointer'>Stop emails for this price</button></form>"
    )
    return HTMLResponse(
        html_page(
            f"Stop emails about {watch['title']}?",
            "We'll keep watching this price in the app; only the emails stop. "
            "You can turn them back on any time.",
            form,
        )
    )


@router.post("/price-watches/unsubscribe", response_class=HTMLResponse)
def unsubscribe(token: str = Query("")):
    """Turns email off for one price watch (the form above, or a mail
    client's RFC 8058 one-click POST)."""
    from .fare_watches import html_page

    watch_id, watch = _unsubscribe_target(token)
    if watch_id is None:
        return HTMLResponse(html_page(*_BAD_LINK), status_code=400)
    if watch is None:
        return HTMLResponse(html_page(*_GONE))
    price_watch_db.update_watch(watch_id, email_enabled=False)
    return HTMLResponse(
        html_page(
            "Done — we won't email you about this price",
            f"Emails for {watch['title']} are off. We'll keep watching it in the "
            "app, where you can turn emails back on any time.",
        )
    )


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/price-watches")
def list_price_watches(
    kind: str | None = Query(None, max_length=20),
    user: dict = Depends(get_current_user),
):
    return [serialize(w) for w in price_watch_db.list_watches(user["id"], kind)]


@router.post("/price-watches/match")
def match_price_watch(body: _Spec, user: dict = Depends(get_current_user)):
    """The user's watch for this hotel / activity / plan, if any (no live
    lookups)."""
    source = price_watch.get_source(body.kind)
    if source is None:
        return {"watch": None}
    try:
        key = source.match_key(_spec(body))
    except (InvalidSpec, HTTPException):  # unusable or oversized: not watched
        return {"watch": None}
    watch = price_watch_db.find_watch(user["id"], body.kind, key) if key else None
    return {"watch": serialize(watch) if watch else None}


def _settle(day: str, held: int, spent: int, user_id: str) -> None:
    """Settle a create's hold to what the match spent: only gives calls back
    (the hold is the kind's worst case; a source that spends more is logged
    and charged the hold)."""
    if spent > held:
        logger.warning(
            "Price watch create spent %d calls, more than its hold of %d", spent, held
        )
    if spent >= held:
        return
    fare_watch_db.adjust_calls(
        day,
        spent - held,
        user_id=user_id,
        budget=settings.fare_watch_daily_call_budget,
        user_cap=fare_watch.user_daily_cap(),
    )


@router.post("/price-watches", dependencies=[Depends(rate_limit("light_ai"))])
async def create_price_watch(
    body: PriceWatchCreate, user: dict = Depends(get_current_user)
):
    _require_live_prices()
    source = _source(body.kind)
    spec = _spec(body)
    try:
        key = source.match_key(spec)
    except InvalidSpec as exc:
        raise _invalid(exc) from exc
    if key:
        existing = price_watch_db.find_watch(user["id"], body.kind, key)
        if existing and existing["status"] != "expired":
            return serialize(existing, already_watching=True)
    if body.email_enabled:
        _check_email_allowed(user)
    if price_watch.limit_reached(user["id"]):
        raise _limit_error()

    now = fare_watch.utcnow()
    day = now.date().isoformat()
    # Matching spends live calls we can't know in advance: hold the kind's
    # worst case now (refused when today's budget or the owner's share can't
    # cover it), then give back what it didn't spend.
    held = price_watch.create_hold(source)
    if not fare_watch_db.reserve_calls(
        day,
        held,
        settings.fare_watch_daily_call_budget,
        user_id=user["id"],
        user_cap=fare_watch.user_daily_cap(),
    ):
        raise _busy(now)
    try:
        result = await source.create(spec, user, settings.serpapi_key)
    except InvalidSpec as exc:
        # Nothing spent unless the source says so (exc.calls)
        _settle(day, held, price_watch.calls_spent(exc, 0), user["id"])
        raise _invalid(exc) from exc
    except Exception as exc:
        # Unknown spend keeps the hold unless the source says (exc.calls)
        _settle(day, held, price_watch.calls_spent(exc, held), user["id"])
        if getattr(exc, "quota_exceeded", False):
            raise _busy(now) from exc
        logger.warning(
            "Price watch create (%s) failed: %s", body.kind, type(exc).__name__
        )
        raise HTTPException(
            status_code=502, detail="We couldn't reach live prices right now."
        ) from exc
    spent = result.calls if isinstance(result, NoLivePrice) else result.baseline.calls
    _settle(day, held, spent, user["id"])

    if isinstance(result, NoLivePrice):
        return _no_live_price(result)
    if result.baseline.status != "ok" or result.baseline.price is None:
        return _no_live_price(
            NoLivePrice(message="It isn't available for these dates right now.")
        )
    existing_for = getattr(source, "existing_watch", None)
    existing = existing_for(user["id"], result) if existing_for else None
    if existing:  # the same subject found another way (e.g. a picked listing)
        return serialize(existing, already_watching=True)
    if (
        body.alert_mode == "below_target"
        and body.target_currency
        and body.target_currency.strip().upper() != (result.currency or "USD").upper()
    ):
        return _target_currency_mismatch(result)
    if date.fromisoformat(result.expires_on) <= now.date():
        raise HTTPException(
            status_code=422, detail="This is too soon to watch its price."
        )
    watch = price_watch.record_created(
        user["id"],
        body.kind,
        result,
        match_key=key,
        alert_mode=body.alert_mode,
        target_price=body.target_price,
        email_enabled=body.email_enabled,
        now=now,
    )
    return serialize(watch, already_watching=False)


@router.get("/price-watches/{watch_id}")
def get_price_watch(watch_id: int, user: dict = Depends(get_current_user)):
    return serialize(_owned(watch_id, user))


@router.patch("/price-watches/{watch_id}")
def update_price_watch(
    watch_id: int, body: PriceWatchUpdate, user: dict = Depends(get_current_user)
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
        for k in ("alert_mode", "target_price", "email_enabled")
        if k in changes
    }
    status = changes.get("status")
    if status == "paused" and watch["status"] in ("active", "error"):
        fields["status"] = "paused"
    elif status == "active" and watch["status"] != "active":
        if watch["status"] == "expired":
            raise HTTPException(
                status_code=409, detail="This watch has ended, so it can't resume."
            )
        if price_watch.limit_reached(user["id"]):
            raise _limit_error()
        fields["status"] = "active"
        if watch["status"] == "error":  # "Retry": check again right away
            fields.update(failure_count=0, unavailable_count=0, last_error=None)
            fields["next_check_at"] = now.isoformat()
    if fields:
        fields["updated_at"] = now.isoformat()
        watch = price_watch_db.update_watch(watch_id, **fields)
    return serialize(watch)


@router.delete("/price-watches/{watch_id}")
def delete_price_watch(watch_id: int, user: dict = Depends(get_current_user)):
    _owned(watch_id, user)
    price_watch_db.delete_watch(watch_id, user["id"])
    return {"deleted": True}


@router.post(
    "/price-watches/{watch_id}/check",
    dependencies=[Depends(rate_limit("light_ai"))],
)
async def check_price_watch_now(watch_id: int, user: dict = Depends(get_current_user)):
    """ "Check now": one live look (never the 30-minute cache; the answer
    refreshes it), subject to the daily SerpAPI budget and the owner's share."""
    watch = _owned(watch_id, user)
    _require_live_prices()
    if watch["status"] == "expired":
        raise HTTPException(status_code=409, detail="This watch has ended.")
    now = fare_watch.utcnow()
    if not price_watch_db.claim_watch(watch_id, now, now + price_watch.LEASE):
        raise HTTPException(
            status_code=409,
            detail="We're checking this price right now — give it a moment.",
        )
    outcome = await price_watch.check_watch(
        watch_id, now=now, api_key=settings.serpapi_key, manual=True, fresh=True
    )
    if outcome.status == "budget_exhausted":
        raise _busy(now, outcome.reason or "global")
    current = price_watch_db.get_watch(watch_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Price watch not found")
    return serialize(
        current,
        check_status=outcome.status,
        notification=(
            {k: v for k, v in outcome.notification.items() if k != "user_id"}
            if outcome.notification
            else None
        ),
    )
