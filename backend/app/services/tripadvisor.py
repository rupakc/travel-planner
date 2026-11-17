"""Tripadvisor Terra (Discover package): live, on-demand ratings for the
top attractions around a destination.

Terms this module encodes (docs/Tripadvisor.md has the full list):

- **No storage of content.** Only Location IDs are kept (``api_budget_db``,
  per destination) — the one attribute Tripadvisor's caching policy lets us
  cache, solely for speed. Names, ratings, rankings and links go straight
  from Terra's response to the caller; nothing else is cached, logged or
  persisted, and nothing here touches an LLM.
- **Hard budget.** Every call first reserves the most billable entities it
  can bill (nearby: one per location returned, so the ``size`` sent;
  multi-get: one per ID asked for), then refunds what wasn't billed (fewer
  results; 4xx/5xx are free; a connection that never opened is free; a
  timeout after sending is kept, since it may have been billed). The
  reservation can shrink the request (``size``/IDs) so usage stops exactly
  at the cap; at the cap the feature is paused.
- **Owner notice.** Crossing 80 % and reaching the cap each log one
  ``tripadvisor_budget`` WARNING and, when SMTP is configured, email the
  admin address (``ADMIN_EMAIL``, else the seeded admin's email).
- **Rate limits.** Terra allows 1 request/s on search/nearby; calls here are
  spaced at least 1 s apart, and only ever made for a signed-in user's
  click (never from background jobs, search streaming or chat).
"""

from __future__ import annotations

import asyncio
import logging
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any
from urllib.parse import urlparse

import httpx

from ..core.config import settings
from ..core.places import fold_place
from ..db import api_budget_db

logger = logging.getLogger(__name__)

PROVIDER = "tripadvisor"
TIMEOUT_S = 10.0
NEARBY_MIN_INTERVAL_S = 1.0
# Tests replace this with an httpx.MockTransport; None = the real network.
_transport: httpx.AsyncBaseTransport | None = None
_nearby_lock = asyncio.Lock()
_last_nearby = 0.0
_background: set[asyncio.Task] = set()


class Paused(Exception):
    """The budget cap is reached: no call was made."""


class TerraError(Exception):
    def __init__(self, status: int | None) -> None:
        super().__init__(f"terra status {status}")
        self.status = status


def configured() -> bool:
    return bool(settings.tripadvisor_api_key)


def enabled() -> bool:
    return bool(settings.tripadvisor_enabled) and configured()


def cap() -> int:
    return max(0, int(settings.tripadvisor_budget_cap))


def budget_status() -> dict:
    s = api_budget_db.status(PROVIDER, cap())
    return {
        "enabled": enabled(),
        "configured": configured(),
        "used": s["used"],
        "cap": s["cap"],
        "warn_at": s["warn_at"],
        "paused": s["paused"],
        "exhausted_at": s["exhausted_at"],
    }


def budget_ok() -> bool:
    """For the /health uptime match: False from the 80 % mark on, so the
    owner hears about it before the free allowance runs out."""
    s = api_budget_db.status(PROVIDER, cap())
    return s["used"] < s["warn_at"] if s["cap"] > 0 else True


def page_size() -> int:
    return max(1, min(20, int(settings.tripadvisor_page_size)))


def place_key(place: Any) -> str:
    if getattr(place, "geonameid", None):
        return f"g:{place.geonameid}"
    return f"n:{fold_place(place.name)}|{place.country_code}"


# ── Owner notice ──────────────────────────────────────────────────────────────


def _admin_address() -> str | None:
    if settings.admin_email:
        return settings.admin_email
    try:
        from ..db.users_db import get_user_by_username

        user = get_user_by_username(settings.admin_username)
    except Exception:
        return None
    return (user or {}).get("email") or None


def _notice_message(event: str, used: int, total: int, to: str) -> EmailMessage:
    from .alert_email import _POLICY, _mail_domain, _sender

    if event == "exhausted":
        subject = "Tripadvisor ratings paused: API budget reached"
        body = (
            f"The app has used {used} of its {total} Tripadvisor billable "
            "entities and has paused Tripadvisor ratings.\n\n"
            "To resume: add payment details in the Tripadvisor Terra dashboard, "
            "then raise TRIPADVISOR_BUDGET_CAP in the app's settings and restart "
            "the app.\n"
        )
    else:
        subject = "Tripadvisor API budget at 80%"
        body = (
            f"The app has used {used} of its {total} Tripadvisor billable "
            "entities. Ratings pause automatically at the cap.\n\n"
            "If you want them to continue past it, add payment details in the "
            "Tripadvisor Terra dashboard and raise TRIPADVISOR_BUDGET_CAP.\n"
        )
    msg = EmailMessage(policy=_POLICY)
    msg["Subject"] = subject
    msg["From"] = _sender()
    msg["To"] = to
    msg["Date"] = formatdate(localtime=False, usegmt=True)
    msg["Message-ID"] = make_msgid(domain=_mail_domain())
    msg.set_content(body)
    return msg


async def _email_owner(event: str, used: int, total: int) -> None:
    if not settings.smtp_host:
        return
    to = _admin_address()
    if not to:
        return
    try:
        from .alert_email import send_message

        await asyncio.to_thread(send_message, _notice_message(event, used, total, to))
        logger.info("tripadvisor_budget notice emailed (%s)", event)
    except Exception as exc:  # never fail the user's request over this
        logger.warning("tripadvisor_budget notice email failed: %s", type(exc).__name__)


def _announce(settled: dict) -> None:
    for event in settled["events"]:
        level = "exhausted" if event == "exhausted" else "warn"
        logger.warning(
            "tripadvisor_budget level=%s used=%d cap=%d",
            level,
            settled["used"],
            settled["cap"],
        )
        task = asyncio.get_running_loop().create_task(
            _email_owner(event, settled["used"], settled["cap"])
        )
        _background.add(task)
        task.add_done_callback(_background.discard)


# ── Terra calls ───────────────────────────────────────────────────────────────


async def _billed_get(
    path: str, params: dict, want: int, count, shrink
) -> tuple[dict, int]:
    """Reserve ``want`` units, call ``path`` with ``shrink(params, granted)``,
    settle on what Terra bills (``count(body)``). Raises Paused / TerraError."""
    granted = api_budget_db.reserve(PROVIDER, want, cap())
    if granted <= 0:
        _announce(api_budget_db.settle(PROVIDER, 0, 0, cap()))
        raise Paused()
    billed = granted  # unknown outcome = assume billed (never undercount)
    try:
        async with httpx.AsyncClient(
            base_url=settings.tripadvisor_base_url.rstrip("/"),
            timeout=TIMEOUT_S,
            transport=_transport,
            headers={
                "X-API-Key": settings.tripadvisor_api_key,
                "Accept": "application/json",
            },
        ) as client:
            try:
                r = await client.get(
                    path, params={**shrink(params, granted), "version": 1}
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                billed = 0  # never reached Terra
                raise TerraError(None) from exc
            except httpx.HTTPError as exc:
                raise TerraError(None) from exc
        if r.status_code >= 400:
            billed = 0  # 4xx/5xx are not billed
            logger.warning(
                "tripadvisor_call path=%s status=%d", _route(path), r.status_code
            )
            raise TerraError(r.status_code)
        try:
            body = r.json()
        except ValueError as exc:
            raise TerraError(r.status_code) from exc
        billed = min(granted, count(body))
        logger.info(
            "tripadvisor_call path=%s status=%d billed=%d",
            _route(path),
            r.status_code,
            billed,
        )
        return body, granted
    finally:
        _announce(api_budget_db.settle(PROVIDER, granted, billed, cap()))


def _route(path: str) -> str:
    """The path without IDs, for logs."""
    return "/locations/nearby" if path.endswith("nearby") else "/locations"


def _data(body: Any) -> list:
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, list) else []


async def _nearby(lat: float, lng: float) -> list[dict]:
    """Top-rated attractions around a point, in Terra's own order."""
    global _last_nearby
    async with _nearby_lock:  # Terra: 1 request/s on search + nearby
        wait = _last_nearby + NEARBY_MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            body, _ = await _billed_get(
                "/locations/nearby",
                {
                    "lat": round(lat, 5),
                    "lon": round(lng, 5),
                    "radius": min(8.0, max(0.5, float(settings.tripadvisor_radius_km))),
                    "unit": "KM",
                    "category": "ATTRACTION",
                },
                page_size(),
                lambda b: len(_data(b)),
                lambda p, n: {**p, "size": n},
            )
        finally:
            _last_nearby = time.monotonic()
    out = []
    for row in _data(body):
        loc = row.get("location") if isinstance(row, dict) else None
        if isinstance(loc, dict):
            out.append(loc)
    return out


async def _by_ids(ids: list[int]) -> list[dict]:
    """Multi-get: returned in the cached (original) order; unlicensed or
    vanished IDs are simply missing."""
    body, granted = await _billed_get(
        "/locations",
        {},
        len(ids),
        lambda b: len(_data(b)),
        lambda p, n: {"id": ",".join(str(i) for i in ids[:n])},
    )
    by_id = {loc.get("id"): loc for loc in _data(body) if isinstance(loc, dict)}
    return [by_id[i] for i in ids[:granted] if i in by_id]


# ── Display shape (a subset of fields, values as returned) ───────────────────


def _https(url: Any) -> str | None:
    if not isinstance(url, str):
        return None
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if p.scheme != "https" or not host:
        return None
    if "tripadvisor." not in host and not host.endswith("tacdn.com"):
        return None
    return url


def _first(items: Any) -> dict:
    return (
        items[0]
        if isinstance(items, list) and items and isinstance(items[0], dict)
        else {}
    )


def display_item(loc: dict) -> dict | None:
    """One location for the client, or None when it can't carry the
    required link back to Tripadvisor."""
    names = loc.get("names") if isinstance(loc.get("names"), list) else []
    name = next(
        (n.get("value") for n in names if isinstance(n, dict) and n.get("primary")),
        None,
    ) or _first(names).get("value")
    urls = (loc.get("urls") or {}).get("tripadvisor") or {}
    web_url = _https(urls.get("main"))
    if not name or not web_url:
        return None
    overall = (loc.get("traveler_ratings") or {}).get("overall") or {}
    return {
        "id": loc.get("id"),
        "name": name,
        "rating": overall.get("rating"),
        "rating_image_url": _https(overall.get("icon_url")),
        "num_reviews": overall.get("count"),
        "ranking": _first(loc.get("rankings")).get("display_text"),
        "category": _first(loc.get("categories")).get("display_name"),
        "web_url": web_url,
        "photos_url": _https(urls.get("photos")),
        "write_review_url": _https(urls.get("write_review")),
    }


def attribution() -> dict:
    return {"name": "Tripadvisor", "logo_url": settings.tripadvisor_logo_url}


async def attractions(place: Any) -> dict:
    """``{"status": "ok"|"empty"|"paused", "items": [...], "attribution"}``.
    Raises TerraError when Terra fails (nothing billed)."""
    if api_budget_db.status(PROVIDER, cap())["paused"]:
        return {"status": "paused", "items": [], "attribution": attribution()}
    key = place_key(place)
    try:
        ids = api_budget_db.get_location_ids(key)
        if ids:
            locations = await _by_ids(ids[: page_size()])
        else:
            locations = await _nearby(place.lat, place.lng)
            api_budget_db.save_location_ids(
                key, [loc["id"] for loc in locations if isinstance(loc.get("id"), int)]
            )
    except Paused:
        return {"status": "paused", "items": [], "attribution": attribution()}
    items = [i for i in (display_item(loc) for loc in locations) if i]
    return {
        "status": "ok" if items else "empty",
        "items": items,
        "attribution": attribution(),
    }
