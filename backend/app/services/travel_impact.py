"""Google Travel Impact Model (TIM): per-flight CO2e estimates, added to flight
results after the flights section has streamed (``FlightsAgent.enrich``).

What this module encodes (docs/Travel-Impact-Model.md has the full list):

- **Exact flights only.** TIM estimates a single scheduled flight (carrier +
  flight number + airports + date). A result gets ``emissions`` only when every
  leg is a non-stop flight with a parseable flight number; a connecting leg
  carries only its first segment's number, and a partial estimate would read as
  the whole trip's, so those results get none.
- **Never blocks the flights section.** One batched call per result set, a
  short timeout, and any failure leaves the results as they were.
- **Daily cap.** Flights sent to TIM count against ``TIM_DAILY_CAP`` per UTC
  day (``api_budget`` row ``google_tim:<date>``); at the cap nothing is sent.
  Answers are cached per flight and date for 24 h, and cache hits don't count.
- **Key in a header.** The key goes in ``X-Goog-Api-Key``, never in a URL or a
  log line.
- **Licence.** TIM data is CC BY-SA 4.0. Every estimate carries ``source`` and
  ``attribution_url`` so the UI can credit it.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

import httpx
from cachetools import TTLCache

from ..core.config import settings
from ..db import api_budget_db

logger = logging.getLogger(__name__)

PROVIDER = "google_tim"
ENDPOINT = (
    "https://travelimpactmodel.googleapis.com/v1/flights:computeFlightEmissions"
)
SOURCE = "Google Travel Impact Model"
ATTRIBUTION_URL = "https://travelimpactmodel.org"
TIMEOUT_S = 8.0
# The API accepts a list of flights per request; results sets are ~10-30 legs,
# so one request is the norm. Chunk defensively anyway.
MAX_PER_REQUEST = 1000
CLASSES = ("economy", "premiumEconomy", "business", "first")
_CLASS_KEYS = {
    "economy": "economy",
    "premium_economy": "premiumEconomy",
    "premiumeconomy": "premiumEconomy",
    "business": "business",
    "first": "first",
}

# Tests replace this with an httpx.MockTransport; None = the real network.
_transport: httpx.AsyncBaseTransport | None = None
# (carrier, number, origin, destination, date) -> TIM flightEmissions entry or
# None (TIM has no estimate for that flight; cached too, so it isn't re-asked)
_cache: TTLCache = TTLCache(maxsize=5000, ttl=24 * 3600)

_FLIGHT_NO = re.compile(r"^\s*([A-Z0-9]{2})\s*0*(\d{1,4})\s*$")
_IATA = re.compile(r"^[A-Z]{3}$")
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def configured() -> bool:
    return bool(settings.tim_api_key)


def enabled() -> bool:
    return bool(settings.tim_enabled) and configured() and cap() > 0


def cap() -> int:
    return max(0, int(settings.tim_daily_cap))


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _provider_today() -> str:
    return f"{PROVIDER}:{_today()}"


def status() -> dict:
    s = api_budget_db.status(_provider_today(), cap())
    return {
        "configured": configured(),
        "enabled": enabled(),
        "used_today": s["used"],
        "cap": s["cap"],
        "paused": bool(s["cap"]) and s["paused"],
    }


def _leg_key(leg: dict) -> tuple | None:
    """The TIM lookup key of one leg, or None when the leg can't be estimated
    exactly (connection, missing or odd flight number, airports, date)."""
    if not isinstance(leg, dict):
        return None
    if (leg.get("stops") or 0) != 0 or leg.get("layovers"):
        return None
    m = _FLIGHT_NO.match(str(leg.get("flight_number") or "").upper())
    origin = str(leg.get("origin") or "").upper()
    dest = str(leg.get("destination") or "").upper()
    d = _DATE.match(str(leg.get("departure_date") or ""))
    if not m or not d or not _IATA.match(origin) or not _IATA.match(dest):
        return None
    return (m.group(1), int(m.group(2)), origin, dest, d.group(0))


def _legs(result: dict) -> list[dict] | None:
    """The legs of a result: outbound (+ return), or the flat legacy shape."""
    if not isinstance(result, dict):
        return None
    if isinstance(result.get("outbound"), dict):
        legs = [result["outbound"]]
        if isinstance(result.get("return"), dict):
            legs.append(result["return"])
        return legs
    if result.get("flight_number"):
        return [result]
    return None


def _body(key: tuple) -> dict:
    carrier, number, origin, dest, date = key
    y, m, d = (int(x) for x in date.split("-"))
    return {
        "origin": origin,
        "destination": dest,
        "operatingCarrierCode": carrier,
        "flightNumber": number,
        "departureDate": {"year": y, "month": m, "day": d},
    }


def _entry_key(entry: dict) -> tuple | None:
    f = entry.get("flight") or {}
    dd = f.get("departureDate") or {}
    try:
        date = f"{int(dd['year']):04d}-{int(dd['month']):02d}-{int(dd['day']):02d}"
        return (
            str(f["operatingCarrierCode"]).upper(),
            int(f["flightNumber"]),
            str(f["origin"]).upper(),
            str(f["destination"]).upper(),
            date,
        )
    except (KeyError, TypeError, ValueError):
        return None


async def _fetch(keys: list[tuple]) -> tuple[dict[tuple, dict], str | None]:
    """Ask TIM for ``keys``; returns ({key: entry}, model version). Raises on
    transport/HTTP errors (the caller swallows them)."""
    found: dict[tuple, dict] = {}
    version = None
    async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=_transport) as client:
        for i in range(0, len(keys), MAX_PER_REQUEST):
            chunk = keys[i : i + MAX_PER_REQUEST]
            resp = await client.post(
                ENDPOINT,
                headers={"X-Goog-Api-Key": settings.tim_api_key},
                json={"flights": [_body(k) for k in chunk]},
            )
            resp.raise_for_status()
            data = resp.json()
            mv = data.get("modelVersion") or {}
            if mv:
                version = ".".join(
                    str(mv.get(p, 0)) for p in ("major", "minor", "patch")
                ) + (f" ({mv['dated']})" if mv.get("dated") else "")
            for entry in data.get("flightEmissions") or []:
                k = _entry_key(entry)
                if k is not None:
                    found[k] = entry
    return found, version


def _cabin_key(cabin: str | None) -> str:
    return _CLASS_KEYS.get(str(cabin or "economy").lower().replace(" ", "_"), "economy")


def _summarise(entries: list[dict], cabin: str, version: str | None) -> dict | None:
    by_class: dict[str, int] = {}
    for c in CLASSES:
        grams = [((e.get("emissionsGramsPerPax") or {}).get(c)) for e in entries]
        if all(isinstance(g, (int, float)) for g in grams):
            by_class[c] = round(sum(grams) / 1000)
    if cabin not in by_class:
        return None
    buckets = [e.get("contrailsImpactBucket") for e in entries if e.get("contrailsImpactBucket")]
    return {
        "kg_co2e_per_pax": by_class[cabin],
        "cabin": cabin,
        "by_class": by_class,
        "contrails_bucket": buckets[0] if buckets else None,
        "legs": len(entries),
        "model_version": version,
        "source": SOURCE,
        "attribution_url": ATTRIBUTION_URL,
        "licence": "CC BY-SA 4.0",
    }


async def annotate(data: dict, cabin: str | None = None) -> dict:
    """Add ``emissions`` to each result of a flights section whose legs TIM can
    estimate. Returns ``data`` (mutated); never raises."""
    if not enabled() or not isinstance(data, dict):
        return data
    results = data.get("results")
    if not isinstance(results, list) or not results:
        return data
    try:
        plans: list[tuple[dict, list[tuple]]] = []
        for r in results:
            legs = _legs(r)
            if not legs:
                continue
            keys = [_leg_key(leg) for leg in legs]
            if all(keys):
                plans.append((r, keys))
        if not plans:
            return data
        wanted = sorted({k for _, ks in plans for k in ks if k not in _cache})
        version = _cache.get(("__version__",))
        if wanted:
            granted = api_budget_db.reserve(_provider_today(), len(wanted), cap())
            if granted < len(wanted):
                logger.info(
                    "tim_cap: %d of %d flights sent (daily cap %d)",
                    granted, len(wanted), cap(),
                )
            ask = wanted[:granted]
            if ask:
                found, v = await _fetch(ask)
                if v:
                    version = v
                    _cache[("__version__",)] = v
                for k in ask:
                    _cache[k] = found.get(k)
        cabin_key = _cabin_key(cabin)
        for r, keys in plans:
            if any(k not in _cache or _cache[k] is None for k in keys):
                continue
            summary = _summarise([_cache[k] for k in keys], cabin_key, version)
            if summary:
                r["emissions"] = summary
    except Exception as exc:  # emissions are a bonus; never break flights
        logger.warning("tim_failed: %s", type(exc).__name__)
    return data
