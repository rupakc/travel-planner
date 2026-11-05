"""Hotel price watches: the ``hotel`` price source.

A traveller watches a hotel from the search results ("Lumen Hotel", Lisbon,
10–14 Dec, 2 adults). ``create`` matches that name to a live Google Hotels
property (``hotel_prices.find_properties`` + ``match_property``) and takes
the baseline from the property look by ``property_token`` — the same look
every later ``check`` makes, so the first check never shows a phantom drop
from the search-list price. A spec that already carries a
``property_token`` (the traveller picked a suggestion) is priced directly.

No confident match, or no rates for the dates → ``NoLivePrice`` with up to
three priced Google Hotels properties to watch instead, and the AI estimate
the page showed (``estimate_total``), labelled as an estimate. Estimates are
never watched and never alert.

Prices are USD totals for the whole stay and all rooms (after taxes and
fees), with the nightly rate as ``unit_price``.

Spec: ``{name, city, check_in, check_out, adults, rooms?=1,
property_token?, estimate_total?}``.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from ...db.database import airport_city
from .. import fare_watch, hotel_prices
from ..fare_watch import date_range
from ..hotel_prices import HotelOffer, HotelPrice
from ..price_watch import (
    CreatedWatch,
    InvalidSpec,
    NoLivePrice,
    PriceObservation,
    format_price,
)

NO_LIVE_PRICE_MESSAGE = "We couldn't find live prices for this hotel on Google Hotels."
SOURCE_NAME = hotel_prices.SOURCE  # "google_hotels"

MAX_NAME = 200
MAX_CITY = 120
MAX_TOKEN = 300
MAX_NIGHTS = 30
MAX_ADULTS = 16
MAX_ROOMS = 8
SUGGESTIONS = 3


# ── Spec ──────────────────────────────────────────────────────────────────────


def _text(spec: dict, key: str, cap: int, what: str) -> str:
    value = spec.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidSpec(f"Tell us the hotel's {what}.")
    value = " ".join(value.split())
    if len(value) > cap:
        raise InvalidSpec(f"That hotel {what} is too long.")
    return value


def _date(spec: dict, key: str, what: str) -> date:
    value = spec.get(key)
    if not value:
        raise InvalidSpec("Tell us your check-in and check-out dates.")
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise InvalidSpec(f"The {what} date isn't a valid date (YYYY-MM-DD).") from None


def _count(spec: dict, key: str, default: int | None, top: int, what: str) -> int:
    value = spec.get(key, default)
    if isinstance(value, bool):
        value = None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, int) or not 1 <= value <= top:
        raise InvalidSpec(f"The number of {what} must be between 1 and {top}.")
    return value


def _clean(spec: dict) -> dict:
    """The validated spec (``InvalidSpec`` with a user-facing reason)."""
    if not isinstance(spec, dict):
        raise InvalidSpec("Tell us which hotel to watch.")
    name = _text(spec, "name", MAX_NAME, "name")
    # the search form stores an airport code ("LIS"): watch the city
    city = airport_city(_text(spec, "city", MAX_CITY, "city"))
    ci = _date(spec, "check_in", "check-in")
    co = _date(spec, "check_out", "check-out")
    nights = (co - ci).days
    if nights < 1:
        raise InvalidSpec("Check-out must be after check-in.")
    if nights > MAX_NIGHTS:
        raise InvalidSpec(f"We can watch stays of up to {MAX_NIGHTS} nights.")
    if ci <= fare_watch.utcnow().date():
        raise InvalidSpec("Check-in is too soon to watch this hotel's price.")
    adults = _count(spec, "adults", None, MAX_ADULTS, "adults")
    rooms = _count(spec, "rooms", 1, MAX_ROOMS, "rooms")
    if rooms > adults:
        raise InvalidSpec("Each room needs at least one adult.")
    token = spec.get("property_token")
    if token is not None and (
        not isinstance(token, str) or not token.strip() or len(token) > MAX_TOKEN
    ):
        raise InvalidSpec("That Google Hotels property isn't valid.")
    estimate = spec.get("estimate_total")
    if (
        isinstance(estimate, bool)
        or not isinstance(estimate, (int, float))
        or not 0 < estimate <= 1_000_000
    ):
        estimate = None  # only shown next to "no live price": never blocks a watch
    plan_id = spec.get("plan_id")
    return {
        "name": name,
        "city": city,
        "check_in": ci.isoformat(),
        "check_out": co.isoformat(),
        "nights": nights,
        "adults": adults,
        "rooms": rooms,
        "property_token": token.strip() if token else None,
        "estimate_total": float(estimate) if estimate is not None else None,
        "plan_id": plan_id if isinstance(plan_id, int) else None,
    }


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain.lower()).split())


# ── Wording ───────────────────────────────────────────────────────────────────


def usd(amount: float) -> str:
    """A USD amount as the UI's formatPrice shows it ("$70", "$88.50", "$1,234")."""
    return format_price(amount, "USD")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def subtitle(check_in: str, check_out: str, adults: int, rooms: int) -> str:
    """'10–14 Dec · 2 guests · 1 room'. Google Hotels prices adults only, so
    every traveller in the party is a guest."""
    return " · ".join(
        [
            date_range(check_in, check_out),
            _plural(adults, "guest"),
            _plural(rooms, "room"),
        ]
    )


def _offer_subtitle(o: HotelOffer, nights: int) -> str:
    """'4★ · 4.6/5 (1,405 reviews) · $100 a night · total for 4 nights' (the
    suggestion's price is the stay's total)."""
    parts = []
    if o.hotel_class:
        parts.append(f"{o.hotel_class}★")
    if o.overall_rating:
        parts.append(
            f"{o.overall_rating:g}/5"
            + (f" ({o.reviews:,} reviews)" if o.reviews else "")
        )
    if o.rate_per_night is not None:
        parts.append(f"{usd(o.rate_per_night)} a night")
    parts.append(f"total for {_plural(nights, 'night')}")
    return " · ".join(parts)


# ── Live looks ────────────────────────────────────────────────────────────────


async def _price(token: str, s: dict, api_key: str) -> tuple[HotelPrice, int]:
    args = (s["check_in"], s["check_out"], s["adults"])
    calls = 0 if hotel_prices.price_is_cached(token, *args, s["rooms"]) else 1
    try:
        price = await hotel_prices.price_property(
            token, *args, api_key, rooms=s["rooms"]
        )
    except Exception as exc:
        exc.calls = calls  # type: ignore[attr-defined]
        raise
    return price, calls


_TAX_KEYS = (
    "extracted_lowest",
    "extracted_after_taxes_fees",
    "lowest",
    "after_taxes_fees",
    "extracted_before_taxes_fees",
)


def _taxes_included(raw: dict) -> bool | None:
    """Whether the look's price includes taxes and fees: the first rate field
    hotel_prices prices from (same order) tells; None when unknown."""
    for block in (raw.get("total_rate"), raw.get("rate_per_night")):
        if not isinstance(block, dict):
            continue
        for key in _TAX_KEYS:
            value = block.get(key)
            if value and not isinstance(value, bool):
                return key != "extracted_before_taxes_fees"
    return None


def _observed(price: HotelPrice, s: dict) -> dict:
    """What history and the UI keep of one look (JSON-safe, compact)."""
    raw = price.observed or {}
    return {
        "name": raw.get("name"),
        "property_token": raw.get("property_token"),
        "currency": raw.get("currency", hotel_prices.CURRENCY),
        "check_in": s["check_in"],
        "check_out": s["check_out"],
        "nights": s["nights"],
        "adults": s["adults"],
        "rooms": s["rooms"],
        "nightly": price.nightly,
        "total": price.total,
        "taxes_included": _taxes_included(raw),
    }


def _observation(price: HotelPrice, s: dict, calls: int) -> PriceObservation:
    if not price.available or price.total is None:
        return PriceObservation(
            price=None,
            status="unavailable",
            source=SOURCE_NAME,
            link=price.link,
            observed=_observed(price, s),
            calls=calls,
        )
    return PriceObservation(
        price=price.total,
        unit_price=price.nightly,
        source=SOURCE_NAME,
        link=price.link,
        observed=_observed(price, s),
        calls=calls,
    )


def _suggestion(o: HotelOffer, s: dict) -> dict:
    return {
        "title": o.name,
        "subtitle": _offer_subtitle(o, s["nights"]),
        "price": o.total_rate,
        "nightly": o.rate_per_night,
        "currency": o.currency,
        "link": o.link,
        "spec": {
            "name": o.name,
            "city": s["city"],
            "check_in": s["check_in"],
            "check_out": s["check_out"],
            "adults": s["adults"],
            "rooms": s["rooms"],
            "property_token": o.property_token,
        },
    }


def _estimate(s: dict) -> dict | None:
    if s["estimate_total"] is None:
        return None
    return {
        "price": s["estimate_total"],
        "source": "ai_estimate",
        "label": "AI estimate",
    }


class HotelSource:
    """Watches one Google Hotels property for one stay."""

    kind = "hotel"

    def match_key(self, spec: dict) -> str:
        s = _clean(spec)
        return "|".join(
            [
                _fold(s["name"]),
                _fold(s["city"]),
                s["check_in"],
                s["check_out"],
                str(s["adults"]),
                str(s["rooms"]),
            ]
        )

    async def create(
        self, spec: dict, user: dict, api_key: str
    ) -> CreatedWatch | NoLivePrice:
        s = _clean(spec)
        calls = 0
        offers: list[HotelOffer] = []
        token = s["property_token"]
        if token is None:
            stay = (s["check_in"], s["check_out"], s["adults"])
            calls += (
                0
                if hotel_prices.find_is_cached(s["name"], s["city"], *stay, s["rooms"])
                else 1
            )
            try:
                offers = await hotel_prices.find_properties(
                    s["name"], s["city"], *stay, api_key, rooms=s["rooms"]
                )
            except Exception as exc:
                exc.calls = calls  # type: ignore[attr-defined]
                raise
            match = hotel_prices.match_property(s["name"], offers, s["city"])
            if match is None:
                return self._no_live_price(s, offers, calls)
            token = match.property_token
            offers = [o for o in offers if o.property_token != token]

        try:
            price, spent = await _price(token, s, api_key)
        except Exception as exc:
            exc.calls = calls + getattr(exc, "calls", 1)  # type: ignore[attr-defined]
            raise
        calls += spent
        baseline = _observation(price, s, calls)
        if baseline.status != "ok":
            return self._no_live_price(s, offers, calls)
        name = (price.observed or {}).get("name") or s["name"]
        if s["estimate_total"] is not None:
            baseline.observed["estimate_total"] = s["estimate_total"]
        # "Not this one?": the other priced properties the search found
        alternatives = hotel_prices.suggestions(
            offers, SUGGESTIONS, s["name"], s["city"]
        )
        if alternatives:
            baseline.observed["alternatives"] = [
                _suggestion(o, s) for o in alternatives
            ]
        return CreatedWatch(
            subject={
                "name": name,
                "requested_name": s["name"],
                "city": s["city"],
                "property_token": token,
                "check_in": s["check_in"],
                "check_out": s["check_out"],
                "adults": s["adults"],
                "rooms": s["rooms"],
            },
            baseline=baseline,
            title=name,
            subtitle=subtitle(s["check_in"], s["check_out"], s["adults"], s["rooms"]),
            expires_on=s["check_in"],
            plan_id=s["plan_id"],
        )

    def _no_live_price(self, s: dict, offers: list[HotelOffer], calls: int):
        picks = hotel_prices.suggestions(offers, SUGGESTIONS, s["name"], s["city"])
        return NoLivePrice(
            message=NO_LIVE_PRICE_MESSAGE,
            suggestions=[_suggestion(o, s) for o in picks],
            estimate=_estimate(s),
            calls=calls,
        )

    async def check(self, watch: dict, api_key: str) -> PriceObservation:
        subject = watch["subject"]
        s = {
            "check_in": subject["check_in"],
            "check_out": subject["check_out"],
            "nights": (
                date.fromisoformat(subject["check_out"])
                - date.fromisoformat(subject["check_in"])
            ).days,
            "adults": int(subject["adults"]),
            "rooms": int(subject.get("rooms") or 1),
        }
        price, calls = await _price(subject["property_token"], s, api_key)
        return _observation(price, s, calls)

    def estimate_calls(self, watch: dict) -> int:
        return 1

    def compose(
        self, kind: str, watch: dict, obs: PriceObservation, ref: float
    ) -> dict:
        subject = watch["subject"]
        ci, co = subject["check_in"], subject["check_out"]
        nights = (date.fromisoformat(co) - date.fromisoformat(ci)).days
        adults = int(subject["adults"])
        rooms = int(subject.get("rooms") or 1)
        name, p = watch["title"], obs.price
        if kind == "hotel_target":
            title = (
                f"🏨 {name} is now {usd(p)} — below your "
                f"{usd(watch['target_price'])} target"
            )
        else:
            title = f"🏨 {name} dropped to {usd(p)} for {date_range(ci, co)} (−{usd(ref - p)})"
        guests = _plural(adults, "guest") + (
            f" in {_plural(rooms, 'room')}" if rooms > 1 else ""
        )
        stay = f"{_plural(nights, 'night')}, {guests}"
        nightly = obs.unit_price
        if nightly is not None and rooms > 1:
            per_room = f"{_plural(rooms, 'room')} × {usd(nightly / rooms)} a night"
            body = f"That's {usd(nightly)} a night ({per_room}) for {stay}"
        elif nightly is not None:
            body = f"That's {usd(nightly)} a night for {stay}"
        else:
            body = f"That's the total for {stay}"
        taxes = (obs.observed or {}).get("taxes_included")
        body += {
            True: " on Google Hotels, taxes and fees included.",
            False: " on Google Hotels, before taxes and fees.",
        }.get(taxes, " on Google Hotels.")
        lowest = watch.get("lowest_price")
        if lowest is None or p < lowest:
            body += " The lowest we've seen since you started watching."
        return {
            "kind": kind,
            "title": title,
            "body": body,
            "data": {
                "nightly": obs.unit_price,
                "check_in": ci,
                "check_out": co,
                "nights": nights,
                "adults": adults,
                "rooms": rooms,
            },
        }


SOURCE = HotelSource()
