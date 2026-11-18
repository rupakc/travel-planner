"""Client of the Voyager crawler's private read API (``/v1``).

Contract: the crawler repo's ``docs/Crawler-API.md`` (frozen, additive only).
App-side design: ``docs/Crawler-Data.md``.

Rules this module keeps:

* **Off unless configured.** ``CRAWLER_ENABLED=true`` plus ``CRAWLER_API_URL``
  and ``CRAWLER_API_TOKEN``; otherwise every call returns ``None`` at once and
  nothing is sent.
* **Never raises.** Any timeout, connection error, TLS error, non-JSON body,
  401 or 5xx returns ``None`` and opens the circuit breaker: for
  ``CRAWLER_BREAKER_S`` (60 s) later calls return ``None`` without touching
  the network, so a dead crawler costs one short timeout, not one per agent.
  A ``429`` opens it for ``Retry-After`` (≤ 60 s). ``400``/``404`` are
  answers about the request, not about the crawler's health: ``None``, no
  breaker.
* **Short timeouts** (``CRAWLER_TIMEOUT_S``, 1.5 s) and a small in-process TTL
  cache (``CRAWLER_CACHE_TTL_S``, 15 min; also for empty answers).
* **Pinned TLS.** The crawler serves a self-signed certificate for its
  internal IP; the client trusts only that certificate (``CRAWLER_CA_PEM``,
  the secret ``crawler-api-tls-cert``, or ``CRAWLER_CA_FILE``). A PEM with two
  certificates (current + next) is accepted during a rotation.

Tests install an ``httpx.MockTransport`` on ``_transport`` (conftest refuses
any real network).
"""

from __future__ import annotations

import logging
import ssl
import time
from typing import Any

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)

# Tests replace this with an httpx.MockTransport (never real network)
_transport: httpx.AsyncBaseTransport | None = None

_CACHE_MAX = 2048
_cache: dict[tuple, tuple[float, Any]] = {}
_breaker_until = 0.0
# Outcome of the last real request: True ok, False failed, None none yet
_last_ok: bool | None = None
_ssl_ctx: ssl.SSLContext | None = None
_ssl_key: tuple | None = None


def configured() -> bool:
    """The feature is on: flag set and a URL and a token configured."""
    return bool(
        settings.crawler_enabled
        and settings.crawler_api_url.strip()
        and settings.crawler_api_token.strip()
    )


def reset() -> None:
    """Forget cached answers, the breaker and the TLS context (tests, config
    changes)."""
    global _breaker_until, _last_ok, _ssl_ctx, _ssl_key
    _cache.clear()
    _breaker_until = 0.0
    _last_ok = None
    _ssl_ctx = None
    _ssl_key = None


def breaker_open() -> bool:
    return time.monotonic() < _breaker_until


def _trip(seconds: float | None = None) -> None:
    global _breaker_until, _last_ok
    _last_ok = False
    wait = settings.crawler_breaker_s if seconds is None else seconds
    _breaker_until = time.monotonic() + max(1.0, float(wait))


def _verify():
    """The TLS verification for httpx: the pinned certificate when one is
    configured, else the system CAs (``True``)."""
    global _ssl_ctx, _ssl_key
    pem = settings.crawler_ca_pem.strip()
    path = settings.crawler_ca_file.strip()
    if not pem and not path:
        return True
    key = (pem, path)
    if _ssl_ctx is not None and _ssl_key == key:
        return _ssl_ctx
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    # Trust ONLY the pinned certificate(s): no public CA
    ctx.load_verify_locations(cadata=pem + "\n" if pem else None, cafile=path or None)
    # The pinned certificate is a self-signed leaf: let it anchor the chain
    ctx.verify_flags |= getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0)
    strict = getattr(ssl, "VERIFY_X509_STRICT", 0)
    if strict:
        ctx.verify_flags &= ~strict
    _ssl_ctx, _ssl_key = ctx, key
    return ctx


def _cache_get(key: tuple):
    hit = _cache.get(key)
    if hit is None:
        return False, None
    expires, value = hit
    if time.monotonic() >= expires:
        _cache.pop(key, None)
        return False, None
    return True, value


def _cache_put(key: tuple, value, ttl: float) -> None:
    if len(_cache) >= _CACHE_MAX:
        now = time.monotonic()
        for k in [k for k, (exp, _) in _cache.items() if exp <= now]:
            _cache.pop(k, None)
        while len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
    _cache[key] = (time.monotonic() + ttl, value)


async def get_json(path: str, params: dict | None = None, *, ttl: float | None = None):
    """GET ``path`` (e.g. ``/v1/search``) and return the decoded JSON object,
    or ``None`` when the feature is off, the breaker is open or anything goes
    wrong. Never raises."""
    global _last_ok
    if not configured():
        return None
    clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
    key = (path, tuple(sorted((k, str(v)) for k, v in clean.items())))
    found, value = _cache_get(key)
    if found:
        return value
    if breaker_open():
        return None
    try:
        timeout = httpx.Timeout(settings.crawler_timeout_s)
        async with httpx.AsyncClient(
            base_url=settings.crawler_api_url.strip().rstrip("/"),
            transport=_transport,
            verify=_verify(),
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {settings.crawler_api_token.strip()}",
                "Accept": "application/json",
                "User-Agent": "voyager-app",
            },
            follow_redirects=True,
        ) as client:
            r = await client.get(path, params=clean)
    except Exception as e:  # timeout, connection, TLS, bad config: all "down"
        logger.warning("crawler_unavailable path=%s error=%s", path, type(e).__name__)
        _trip()
        return None
    status = r.status_code
    if status == 429:
        try:
            wait = min(60.0, float(r.headers.get("Retry-After", "60")))
        except ValueError:
            wait = 60.0
        logger.warning("crawler_rate_limited path=%s retry_after=%s", path, wait)
        _trip(wait)
        return None
    if status in (400, 404):
        _last_ok = True  # it answered: the request is the problem, not the API
        return None
    if status != 200:
        logger.warning("crawler_unavailable path=%s status=%s", path, status)
        _trip()
        return None
    try:
        data = r.json()
    except ValueError:
        logger.warning("crawler_bad_json path=%s", path)
        _trip()
        return None
    if not isinstance(data, dict):
        _trip()
        return None
    _last_ok = True
    _cache_put(key, data, settings.crawler_cache_ttl_s if ttl is None else ttl)
    return data


async def search(
    kind: str, q: str | None = None, *, limit: int = 100, pages: int = 1
) -> list[dict] | None:
    """Items of ``kind`` matching ``q`` (``/v1/search``), following up to
    ``pages`` pages. ``None`` when the crawler did not answer."""
    items: list[dict] = []
    cursor = None
    for _ in range(max(1, pages)):
        page = await get_json(
            "/v1/search",
            {"kind": kind, "q": q, "limit": limit, "cursor": cursor},
        )
        if page is None:
            return None if not items else items
        got = page.get("items")
        if isinstance(got, list):
            items.extend(i for i in got if isinstance(i, dict))
        cursor = page.get("next_cursor")
        if not cursor:
            break
    return items


async def observations(series: str, *, days: int = 14) -> list[dict] | None:
    """Points of one series over the last ``days`` days, oldest first."""
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    page = await get_json(
        "/v1/observations",
        {
            "series": series,
            # Hour-rounded so the cache key is stable within the hour
            "from": (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    if page is None:
        return None
    got = page.get("items")
    return [i for i in got if isinstance(i, dict)] if isinstance(got, list) else []


async def source_names() -> dict[str, str]:
    """``source_id`` → display name (``/v1/sources``, cached 6 h); ``{}``
    when unavailable."""
    page = await get_json("/v1/sources", ttl=6 * 3600)
    out: dict[str, str] = {}
    for s in (page or {}).get("items") or []:
        if isinstance(s, dict) and s.get("source_id") and s.get("name"):
            out[str(s["source_id"])] = str(s["name"])
    return out


async def health() -> dict:
    """``{"configured", "ok"}`` for ``/health``: one cached ``/v1/stats``
    call (60 s), never a stack of requests."""
    if not configured():
        return {"configured": False, "ok": False}
    stats = await get_json("/v1/stats", ttl=60)
    return {"configured": True, "ok": stats is not None}
