"""SerpAPI Google Flights integration.

Provides real flight data as a drop-in replacement for the AI-based flights
agent. Falls back gracefully — callers catch SerpAPIError and use the AI path.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

from ..core.cache import get_cache
from ..schemas.request import TravelSearchRequest

logger = logging.getLogger(__name__)

_SERP_URL = "https://serpapi.com/search"

# Module-level shared client — one connection pool for the process lifetime
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=12.0)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ── Exceptions ────────────────────────────────────────────────────────────────


class SerpAPIError(Exception):
    def __init__(self, msg: str, quota_exceeded: bool = False) -> None:
        super().__init__(msg)
        self.quota_exceeded = quota_exceeded


# ── Internal helpers ──────────────────────────────────────────────────────────


def _build_params(
    api_key: str,
    request: TravelSearchRequest,
    filters: dict | None,
    departure_token: str | None = None,
) -> dict:
    is_round_trip = request.return_date is not None
    origin_id = request.origin_iata or request.origin
    dest_id = request.destination_iata or request.destination

    params: dict[str, Any] = {
        "engine": "google_flights",
        "api_key": api_key,
        "departure_id": origin_id,
        "arrival_id": dest_id,
        "outbound_date": str(request.departure_date),
        "type": "1" if is_round_trip else "2",
        "adults": str(request.num_travelers),
        "currency": "USD",
        "hl": "en",
    }

    if is_round_trip:
        params["return_date"] = str(request.return_date)

    if departure_token:
        params["departure_token"] = departure_token

    if filters:
        max_stops = filters.get("max_stops")
        if max_stops is not None:
            # SerpAPI stops: 0=any, 1=nonstop, 2=≤1stop, 3=≤2stops
            params["stops"] = str(max_stops + 1)

        max_price = filters.get("max_price_usd")
        if max_price is not None:
            params["max_price"] = str(int(max_price))

        dep_e = filters.get("departure_time_earliest")
        dep_l = filters.get("departure_time_latest")
        if dep_e or dep_l:
            h_start = int((dep_e or "00:00").split(":")[0])
            h_end = int((dep_l or "23:00").split(":")[0])
            params["outbound_times"] = f"{h_start},{h_end}"

    return params


def _map_leg(flights_arr: list, layovers: list, date_str: str) -> dict:
    if not flights_arr:
        return {}
    first = flights_arr[0]
    last = flights_arr[-1]
    leg_duration = sum(leg.get("duration", 0) for leg in flights_arr)
    layover_duration = sum(lv.get("duration", 0) for lv in (layovers or []))
    return {
        "airline": first.get("airline"),
        "flight_number": first.get("flight_number"),
        "origin": first.get("departure_airport", {}).get("id"),
        "destination": last.get("arrival_airport", {}).get("id"),
        "departure_date": date_str,
        "departure_time": (first.get("departure_airport", {}).get("time") or "")[-5:]
        or None,
        "arrival_time": (last.get("arrival_airport", {}).get("time") or "")[-5:]
        or None,
        "duration_minutes": leg_duration + layover_duration,
        "stops": len(flights_arr) - 1,
        "layovers": [
            {
                "city": lv.get("name"),
                "airport": lv.get("id"),
                "duration_hours": round((lv.get("duration") or 0) / 60, 1),
            }
            for lv in (layovers or [])
        ],
    }


def _google_flights_url(
    origin: str, destination: str, dep_date: str, ret_date: str | None
) -> str:
    base = f"https://www.google.com/flights#flt={origin}.{destination}.{dep_date}"
    if ret_date:
        base += f"*{destination}.{origin}.{ret_date}"
    return base + ";c:USD;e:1;sd:1;t:f"


def _map_result(
    serp_item: dict,
    trip_type: str,
    outbound_leg: dict,
    dep_date: str,
    ret_date: str | None,
    origin: str,
    destination: str,
) -> dict:
    return_leg = None
    if trip_type == "round_trip":
        return_leg = _map_leg(
            serp_item.get("flights", []),
            serp_item.get("layovers", []),
            ret_date or "",
        )

    first_flight = (serp_item.get("flights") or [{}])[0]
    carbon = serp_item.get("carbon_emissions", {}) or {}

    return {
        "price_usd": float(serp_item.get("price", 0)),
        "trip_type": trip_type,
        "outbound": outbound_leg,
        "return": return_leg,
        "booking_url": _google_flights_url(origin, destination, dep_date, ret_date),
        "source": "google_flights",
        "carbon_emissions_grams": carbon.get("this_flight"),
        "often_delayed": first_flight.get("often_delayed_by_over_30_min", False),
    }


def _pick_diverse_outbounds(items: list, n: int = 3) -> list:
    """Pick up to n diverse outbound options: cheapest, earliest, latest departure."""
    if not items:
        return []

    seen_tokens: set[str] = set()
    candidates = []

    def dep_time(item: dict) -> str:
        flights = item.get("flights") or []
        if not flights:
            return ""
        return (flights[0].get("departure_airport") or {}).get("time") or ""

    def add(item: dict) -> bool:
        token = item.get("departure_token", "")
        if token in seen_tokens:
            return False
        seen_tokens.add(token)
        candidates.append(item)
        return True

    # Cheapest (SerpAPI sorts best_flights by value, first = best price/quality)
    add(items[0])

    if len(items) > 1:
        # Earliest departure
        earliest = min(items, key=lambda x: dep_time(x))
        add(earliest)

    if len(items) > 2:
        # Latest departure
        latest = max(items, key=lambda x: dep_time(x))
        add(latest)

    return candidates[:n]


def _post_filter_arrival(results: list, filters: dict | None) -> list:
    if not filters:
        return results
    arr_e = filters.get("arrival_time_earliest")
    arr_l = filters.get("arrival_time_latest")
    if not arr_e and not arr_l:
        return results

    filtered = []
    for r in results:
        arr = (r.get("outbound") or {}).get("arrival_time") or ""
        if arr_e and arr < arr_e:
            continue
        if arr_l and arr > arr_l:
            continue
        filtered.append(r)
    return filtered


async def _call(params: dict) -> dict:
    """Make one SerpAPI request. Raises SerpAPIError on HTTP error or timeout."""
    t0 = time.monotonic()
    try:
        resp = await _get_client().get(_SERP_URL, params=params)
    except httpx.TimeoutException as exc:
        raise SerpAPIError(f"SerpAPI timeout: {exc}") from exc
    except httpx.RequestError as exc:
        raise SerpAPIError(f"SerpAPI request error: {exc}") from exc

    elapsed_ms = (time.monotonic() - t0) * 1000

    if resp.status_code == 429:
        raise SerpAPIError("SerpAPI quota exceeded", quota_exceeded=True)
    if resp.status_code >= 400:
        raise SerpAPIError(f"SerpAPI HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    n_results = len(data.get("best_flights", [])) + len(data.get("other_flights", []))
    logger.info("SerpAPI response: %d results in %.0fms", n_results, elapsed_ms)
    return data


# ── Public API ────────────────────────────────────────────────────────────────


async def search(
    api_key: str,
    request: TravelSearchRequest,
    filters: dict | None = None,
) -> dict:
    """Fetch flights from SerpAPI Google Flights.

    Returns the same dict shape as FlightsAgent.run(): {"results": [...]}
    Raises SerpAPIError on API failure (caller falls back to AI agent).
    """
    origin_id = request.origin_iata or request.origin
    dest_id = request.destination_iata or request.destination
    dep_date = str(request.departure_date)
    ret_date = str(request.return_date) if request.return_date else None

    # Cache key — deterministic from search params
    filters_key = tuple(sorted((filters or {}).items()))
    cache_key = f"serp:{origin_id}:{dest_id}:{dep_date}:{ret_date}:{hash(filters_key)}"
    cache = get_cache()
    if cache_key in cache:
        logger.info("SerpAPI cache hit for %s→%s", origin_id, dest_id)
        return cache[cache_key]

    base_params = _build_params(api_key, request, filters)

    if not request.return_date:
        # ── One-way: single call ────────────────────────────────────────
        data = await _call(base_params)
        items = data.get("best_flights", []) + data.get("other_flights", [])
        trip_type = "one_way"
        results = []
        for item in items[:12]:
            leg = _map_leg(item.get("flights", []), item.get("layovers", []), dep_date)
            results.append(
                _map_result(item, trip_type, leg, dep_date, None, origin_id, dest_id)
            )
    else:
        # ── Round-trip: call 1 (outbounds) + 3 parallel calls (returns) ─
        data1 = await _call(base_params)
        all_outbounds = data1.get("best_flights", []) + data1.get("other_flights", [])

        if not all_outbounds:
            return {"results": []}

        diverse = _pick_diverse_outbounds(all_outbounds, n=3)

        async def fetch_returns(outbound_item: dict) -> tuple[dict, list]:
            token = outbound_item.get("departure_token")
            if not token:
                return outbound_item, []
            params2 = _build_params(api_key, request, filters, departure_token=token)
            try:
                data2 = await _call(params2)
                returns = data2.get("best_flights", []) + data2.get("other_flights", [])
                return outbound_item, returns
            except SerpAPIError:
                return outbound_item, []

        batch = await asyncio.gather(*[fetch_returns(ob) for ob in diverse])

        trip_type = "round_trip"
        results = []
        for outbound_item, return_items in batch:
            ob_leg = _map_leg(
                outbound_item.get("flights", []),
                outbound_item.get("layovers", []),
                dep_date,
            )
            for ret_item in return_items[:4]:
                results.append(
                    _map_result(
                        ret_item,
                        trip_type,
                        ob_leg,
                        dep_date,
                        ret_date,
                        origin_id,
                        dest_id,
                    )
                )

        # Sort by combined price, cap at 12
        results.sort(key=lambda r: r.get("price_usd") or 9999)
        results = results[:12]

    results = _post_filter_arrival(results, filters)
    payload = {"results": results}
    cache[cache_key] = payload
    return payload


async def search_multi_city(
    api_key: str,
    request: TravelSearchRequest,
    filters: dict | None = None,
) -> dict:
    """Fetch one-way flights for EVERY leg of a multi-city journey.

    Runs a parallel one-way search per leg (origin → city1, city1 → city2, …,
    last city → origin) and returns:
        {"trip_type": "multi_city", "legs": [...], "results": [flattened]}
    Each flight result is tagged with leg_index / leg_from / leg_to / leg_date.
    Raises SerpAPIError if no leg can be resolved or every leg fails.
    """
    from ..db.database import lookup_city_iata

    legs = request.flight_legs or []
    if not legs:
        raise SerpAPIError("Not a multi-city request")

    cache = get_cache()
    filters_key = tuple(sorted((filters or {}).items()))
    leg_key = "|".join(f"{lg['from']}>{lg['to']}@{lg['date']}" for lg in legs)
    cache_key = f"serp-mc:{leg_key}:{request.num_travelers}:{hash(filters_key)}"
    if cache_key in cache:
        logger.info("SerpAPI multi-city cache hit")
        return cache[cache_key]

    # Resolve every endpoint to IATA codes; origin may already carry one.
    origin_code = request.origin_iata or lookup_city_iata(request.origin)

    def resolve(city: str) -> str | None:
        if city == request.origin:
            return origin_code
        return lookup_city_iata(city)

    async def fetch_leg(index: int, leg: dict) -> dict:
        dep_id = resolve(leg["from"])
        arr_id = resolve(leg["to"])
        label = f"{leg['from']} → {leg['to']}"
        if not dep_id or not arr_id:
            return {"leg_index": index, "label": label, "error": "unresolved city"}
        params: dict[str, Any] = {
            "engine": "google_flights",
            "api_key": api_key,
            "departure_id": dep_id,
            "arrival_id": arr_id,
            "outbound_date": str(leg["date"]),
            "type": "2",
            "adults": str(request.num_travelers),
            "currency": "USD",
            "hl": "en",
        }
        if filters and filters.get("max_stops") is not None:
            params["stops"] = str(filters["max_stops"] + 1)
        if filters and filters.get("max_price_usd") is not None:
            params["max_price"] = str(int(filters["max_price_usd"]))
        try:
            data = await _call(params)
        except SerpAPIError as exc:
            logger.warning("Multi-city leg %d (%s) failed: %s", index, label, exc)
            return {"leg_index": index, "label": label, "error": str(exc)}
        items = data.get("best_flights", []) + data.get("other_flights", [])
        results = []
        for item in items[:5]:
            mapped = _map_result(
                item,
                "one_way",
                _map_leg(
                    item.get("flights", []), item.get("layovers", []), str(leg["date"])
                ),
                str(leg["date"]),
                None,
                dep_id.split(",")[0],
                arr_id.split(",")[0],
            )
            mapped.update(
                {
                    "leg_index": index,
                    "leg_from": leg["from"],
                    "leg_to": leg["to"],
                    "leg_date": str(leg["date"]),
                    "city": leg["to"],
                }
            )
            results.append(mapped)
        return {
            "leg_index": index,
            "label": label,
            "date": str(leg["date"]),
            "from": leg["from"],
            "to": leg["to"],
            "results": results,
        }

    fetched = await asyncio.gather(*[fetch_leg(i, leg) for i, leg in enumerate(legs)])

    if all(lg.get("error") or not lg.get("results") for lg in fetched):
        raise SerpAPIError("All multi-city legs failed or returned no results")

    flattened = [r for lg in fetched for r in lg.get("results", [])]
    payload = {"trip_type": "multi_city", "legs": fetched, "results": flattened}
    cache[cache_key] = payload
    return payload
