"""Activity price watches: the "from" price of one GetYourGuide or Viator
listing, as Google search results show it (``activity_prices``).

Spec (``{"kind": "activity", "activity": {...}}``)::

    {name, city, date?, travellers? (1–20, default 1), listing_url?,
     estimate_price?}

- ``name`` / ``city``: the activity as the AI suggested it.
- ``date``: the itinerary day, when known — checking stops then; without
  one a watch runs for ``DEFAULT_DAYS``.
- ``listing_url``: a specific listing to watch (a suggestion the traveller
  picked); otherwise the name is matched to a listing.
- ``estimate_price``: the AI's per-person estimate, shown (labelled) when
  nothing live matches. Never watched.

Honesty: only specific activity pages are watched — a category or
attraction page's "from" price is the cheapest of many products, so it is
offered as nothing and its specific listings are suggested instead. Prices
stay in the listing's own currency; a check that finds another currency is
``unavailable``, never compared. The watched price is the per-person "from"
price × travellers (``unit_price`` is per person).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from datetime import date, timedelta

from ...db import price_watch_db
from ...db.database import airport_city
from .. import activity_prices as ap
from .. import fare_watch, price_rules
from ..activity_prices import ActivityListing
from ..price_watch import (
    CreatedWatch,
    InvalidSpec,
    NoLivePrice,
    PriceObservation,
    format_price,
)

KIND = "activity"
DEFAULT_DAYS = 180  # watch length when the activity has no date
MAX_TRAVELLERS = 20
MAX_NAME = 200
MAX_CITY = 100
NO_LIVE_PRICE = (
    "We couldn't find a live price for this activity on GetYourGuide or Viator."
)
PROVIDER_NAMES = {"getyourguide": "GetYourGuide", "viator": "Viator"}


# ── Spec ──────────────────────────────────────────────────────────────────────


def _fold(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in norm if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^\w]+", " ", plain).split())


def _text(spec: dict, key: str, limit: int, missing: str) -> str:
    value = spec.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidSpec(missing)
    value = " ".join(value.split())
    if len(value) > limit:
        raise InvalidSpec(f"That activity {key} is too long.")
    return value


def parse_spec(spec: dict) -> dict:
    """The spec, validated and tidied; raises ``InvalidSpec``."""
    if not isinstance(spec, dict):
        raise InvalidSpec("Tell us which activity to watch.")
    out = {
        "name": _text(spec, "name", MAX_NAME, "Tell us which activity to watch."),
        # the search form stores an airport code ("LIS"): watch the city
        "city": airport_city(
            _text(spec, "city", MAX_CITY, "Tell us which city it's in.")
        ),
    }

    travellers = spec.get("travellers", 1)
    if travellers is None:
        travellers = 1
    if (
        not isinstance(travellers, int)
        or isinstance(travellers, bool)
        or not 1 <= travellers <= MAX_TRAVELLERS
    ):
        raise InvalidSpec(f"Travellers must be between 1 and {MAX_TRAVELLERS}.")
    out["travellers"] = travellers

    raw_date = spec.get("date")
    out["date"] = None
    if raw_date:
        try:
            day = date.fromisoformat(str(raw_date))
        except ValueError:
            raise InvalidSpec("That activity date isn't a valid date.") from None
        if day <= fare_watch.utcnow().date():
            raise InvalidSpec(
                "That activity is today or already over, so there's no price to watch."
            )
        out["date"] = day.isoformat()

    url = spec.get("listing_url")
    out["listing_url"] = None
    if url:
        if not isinstance(url, str) or ap.page_kind(url) != "activity":
            raise InvalidSpec(
                "We can only watch a specific GetYourGuide or Viator activity."
            )
        out["listing_url"] = ap.normalise_url(url)

    estimate = spec.get("estimate_price")
    out["estimate_price"] = None
    if estimate is not None:
        if (
            not isinstance(estimate, int | float)
            or isinstance(estimate, bool)
            or estimate <= 0
        ):
            raise InvalidSpec("That estimated price isn't a price.")
        out["estimate_price"] = float(estimate)
    return out


# ── Wording ───────────────────────────────────────────────────────────────────


def _people(n: int) -> str:
    return f"{n} traveller" if n == 1 else f"{n} travellers"


def _provider(provider: str) -> str:
    return PROVIDER_NAMES.get(provider, provider)


def _subtitle(listing: ActivityListing, travellers: int) -> str:
    """Provider · travellers. No price: it would freeze the creation-time
    one (cards and emails show the latest look's)."""
    return f"{_provider(listing.provider)} · {_people(travellers)}"


def _same_name(a: str, b: str) -> bool:
    return _fold(a or "") == _fold(b or "")


def _suggestion(listing: ActivityListing, spec: dict) -> dict:
    rating = (
        f"★ {listing.rating:g}"
        + (f" ({listing.reviews:,})" if listing.reviews else "")
        + " · "
        if listing.rating
        else ""
    )
    price = format_price(listing.price_from, listing.currency)
    return {
        "title": listing.title,
        "subtitle": f"{_provider(listing.provider)} · {rating}from {price} per person",
        "price": listing.price_from,
        "currency": listing.currency,
        "price_label": "per person",
        "provider": listing.provider,
        "rating": listing.rating,
        "reviews": listing.reviews,
        "link": listing.url,
        "spec": {
            "name": spec["name"],
            "city": spec["city"],
            "date": spec["date"],
            "travellers": spec["travellers"],
            "listing_url": listing.url,
        },
    }


# ── Source ────────────────────────────────────────────────────────────────────


class ActivitySource:
    kind = KIND
    max_create_calls = 2  # the GetYourGuide and Viator searches
    step = price_rules.ACTIVITY_STEP  # max(1, 5 %) in the listing currency

    def match_key(self, spec: dict) -> str:
        """normalised name|city|travellers — plus the listing URL for a
        picked suggestion, which is its own subject (the card that offered
        it stays unwatched). The date only sets ``expires_on``: it moves
        with the itinerary, so it never splits one activity into two."""
        s = parse_spec(spec)
        parts = [_fold(s["name"]), _fold(s["city"]), str(s["travellers"])]
        if s["listing_url"]:
            parts.append(s["listing_url"])
        return "|".join(parts)

    def estimate_calls(self, watch: dict) -> int:
        return 1

    # Create ────────────────────────────────────────────────────────────────

    async def create(
        self, spec: dict, user: dict, api_key: str
    ) -> CreatedWatch | NoLivePrice:
        s = parse_spec(spec)
        queries = [
            ap.build_query(s["name"], s["city"], p) for p in ("getyourguide", "viator")
        ]
        cached = {q: ap.is_cached(q) for q in queries}

        def spent() -> int:
            return sum(1 for q in queries if not cached[q] and ap.is_cached(q))

        try:
            return await self._match(s, api_key, spent)
        except Exception as exc:
            exc.calls = spent()  # settle the shared budget to what was spent
            raise

    async def _match(self, s: dict, api_key: str, spent) -> CreatedWatch | NoLivePrice:
        if s["listing_url"]:
            listings, chosen = await self._picked(s, api_key)
        else:
            listings = await ap.find_listings(s["name"], s["city"], api_key)
            chosen = ap.match_listing(s["name"], listings, s["city"])

        if chosen is not None and not chosen.is_category:
            price = await ap.price_listing(chosen, chosen.query, api_key)
            if price.available and price.currency == chosen.currency:
                return self._created(s, chosen, price, spent())
        return self._no_live_price(s, listings, spent())

    async def _picked(
        self, s: dict, api_key: str
    ) -> tuple[list[ActivityListing], ActivityListing | None]:
        """A picked suggestion: re-read the query that listed it — cached
        queries first (a GetYourGuide search can list a Viator page), then
        its own provider's query."""
        own = ap.build_query(s["name"], s["city"], ap.provider_of(s["listing_url"]))
        built = [
            ap.build_query(s["name"], s["city"], p) for p in ("getyourguide", "viator")
        ]
        queries = [q for q in built if ap.is_cached(q)]
        if own not in queries:
            queries.append(own)
        listings: list[ActivityListing] = []
        for query in queries:
            listings = await ap.search_listings(query, api_key)
            chosen = next((x for x in listings if x.url == s["listing_url"]), None)
            if chosen is not None:
                return listings, chosen
        return listings, None

    def existing_watch(self, user_id: str, created: CreatedWatch) -> dict | None:
        """The user's live watch of the same listing for the same number of
        travellers, however it was found (matched or picked)."""
        url = ap.normalise_url(created.subject["listing_url"])
        travellers = created.subject["travellers"]
        for watch in price_watch_db.list_watches(user_id, KIND):
            subject = watch.get("subject") or {}
            if (
                watch["status"] != "expired"
                and subject.get("travellers") == travellers
                and ap.normalise_url(subject.get("listing_url") or "") == url
            ):
                return watch
        return None

    def _created(
        self, s: dict, listing: ActivityListing, price: ap.ActivityPrice, calls: int
    ) -> CreatedWatch:
        listing = _with_price(listing, price)
        subject = {
            "name": s["name"],
            "city": s["city"],
            "listing_url": listing.url,
            "listing_title": listing.title,
            "provider": listing.provider,
            "query": listing.query,
            "travellers": s["travellers"],
            "currency": listing.currency,
            "date": s["date"],
        }
        expires = (
            s["date"]
            or (fare_watch.utcnow().date() + timedelta(days=DEFAULT_DAYS)).isoformat()
        )
        return CreatedWatch(
            subject=subject,
            baseline=_observation(listing, price, s["travellers"], calls),
            title=listing.title,
            subtitle=_subtitle(listing, s["travellers"]),
            expires_on=expires,
            currency=listing.currency,
        )

    def _no_live_price(
        self, s: dict, listings: list[ActivityListing], calls: int
    ) -> NoLivePrice:
        specific = [
            x for x in listings if not x.is_category and x.url != s["listing_url"]
        ]
        estimate = None
        if s["estimate_price"]:
            estimate = {
                "price": s["estimate_price"],
                "source": "ai_estimate",
                "currency": "USD",
                "label": "per person",
            }
        return NoLivePrice(
            message=NO_LIVE_PRICE,
            suggestions=[_suggestion(x, s) for x in ap.suggestions(specific, 3)],
            estimate=estimate,
            calls=calls,
        )

    # Check ─────────────────────────────────────────────────────────────────

    async def check(self, watch: dict, api_key: str) -> PriceObservation:
        subject = watch["subject"]
        query = subject["query"]
        currency = subject.get("currency") or watch.get("currency") or "USD"
        calls = 0 if ap.is_cached(query) else 1
        stored = ActivityListing(
            provider=subject["provider"],
            url=subject["listing_url"],
            title=subject.get("listing_title") or subject["name"],
            price_from=0.0,
            currency=currency,
            is_usd=currency == "USD",
            rating=None,
            reviews=None,
            snippet="",
            page_kind="activity",
            query=query,
        )
        price = await ap.price_listing(stored, query, api_key)
        source = stored.source
        base = {"source": source, "observed_at": price.observed}
        if not price.available:
            return _unavailable(stored, calls, {**base, "reason": price.reason})
        if price.currency != currency:
            return _unavailable(
                stored,
                calls,
                {
                    **base,
                    "reason": "currency_changed",
                    "seen_currency": price.currency,
                    "seen_price": price.price_from,
                },
            )
        found = next(
            (x for x in await ap.search_listings(query, api_key) if x.url == price.url),
            stored,
        )
        return _observation(
            _with_price(found, price), price, subject["travellers"], calls
        )

    # Wording ───────────────────────────────────────────────────────────────

    def compose(
        self, kind: str, watch: dict, obs: PriceObservation, ref: float
    ) -> dict:
        subject = watch["subject"]
        travellers = subject.get("travellers") or 1
        currency = subject.get("currency") or watch.get("currency") or "USD"

        def money(amount: float) -> str:
            return format_price(amount, currency)

        unit = obs.unit_price if obs.unit_price is not None else obs.price / travellers
        ref_unit = ref / travellers
        ai_name = subject.get("name") or watch["title"]
        listing = subject.get("listing_title") or ai_name
        # The traveller must see what is really watched: the listing, with
        # their own name for it in the body when the two differ.
        differs = not _same_name(ai_name, listing)
        name = listing if differs else ai_name
        provider = _provider(subject.get("provider", ""))
        if kind.endswith("_target"):
            title = f"🎟️ {name} is under your target: from {money(unit)} per person"
            lead = (
                f"Your target was {money(watch['target_price'])}."
                if watch.get("target_price") is not None
                else ""
            )
        else:
            title = (
                f"🎟️ {name} is now from {money(unit)} per person "
                f"(−{money(ref_unit - unit)})"
            )
            lead = ""
        if travellers > 1:
            total = (
                f"That's {money(obs.price)} for {_people(travellers)}, "
                f"down from {money(ref)}."
            )
        else:
            total = f"Down from {money(ref_unit)} per person."
        honesty = f"Price as shown in Google results for {provider}."
        yours = f"Watching it for your ‘{ai_name}’." if differs else ""
        body = " ".join(x for x in (yours, lead, total, honesty) if x)
        return {
            "kind": kind,
            "title": title,
            "body": body,
            "data": {
                "unit_price": unit,
                "currency": currency,
                "travellers": travellers,
                "provider": subject.get("provider"),
                "listing_title": subject.get("listing_title"),
            },
        }


def _with_price(listing: ActivityListing, price: ap.ActivityPrice) -> ActivityListing:
    """The listing as this look saw it (a title-matched re-check can move the
    URL / title)."""
    return replace(
        listing,
        url=price.url,
        title=price.title or listing.title,
        price_from=price.price_from,
        currency=price.currency,
        is_usd=price.is_usd,
    )


def _observation(
    listing: ActivityListing, price: ap.ActivityPrice, travellers: int, calls: int
) -> PriceObservation:
    unit = listing.price_from
    return PriceObservation(
        price=round(unit * travellers, 2),
        unit_price=unit,
        source=listing.source,
        link=listing.url,
        observed={
            "rating": listing.rating,
            "reviews": listing.reviews,
            "source": listing.source,
            "observed_at": price.observed,
            "listing_title": listing.title,
            "provider": listing.provider,
            "currency": listing.currency,
            "travellers": travellers,
            "matched_by": price.matched_by,
        },
        calls=calls,
    )


def _unavailable(
    listing: ActivityListing, calls: int, observed: dict
) -> PriceObservation:
    return PriceObservation(
        price=None,
        status="unavailable",
        source=listing.source,
        link=listing.url,
        observed={
            **observed,
            "listing_title": listing.title,
            "provider": listing.provider,
        },
        calls=calls,
    )


SOURCE = ActivitySource()
