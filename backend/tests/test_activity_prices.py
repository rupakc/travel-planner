"""Observed activity prices from Google results (GetYourGuide / Viator).

All tests are offline: SerpAPI responses come from sanitized fixtures recorded
live on 2026-11-04 (tests/fixtures/serpapi/activities/) or small inline dicts.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.cache import get_cache
from app.services import activity_prices as ap
from app.services.activity_prices import (
    ActivityListing,
    find_listings,
    match_listing,
    normalise_url,
    page_kind,
    parse_listings,
    parse_price,
    price_listing,
    suggestions,
)
from app.services.serp_flights import SerpAPIError

FIXTURES = Path(__file__).parent / "fixtures" / "serpapi" / "activities"
API_KEY = "sk-test-secret-key"
GYG_QUERY = "Belem Tower tour Lisbon getyourguide"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture(autouse=True)
def _clear_cache():
    get_cache().clear()
    yield
    get_cache().clear()


def _mock_client(*responses):
    """Patch the shared SerpAPI client; each response is a dict (200) or an
    httpx.Response / exception."""
    side = []
    for r in responses:
        side.append(httpx.Response(200, json=r) if isinstance(r, dict) else r)
    client = AsyncMock()
    client.get = AsyncMock(side_effect=side)
    return client, patch(
        "app.services.serp_flights.get_serp_client", return_value=client
    )


def _item(
    link, title="Some tour", price=None, currency="$", extensions=None, snippet=""
):
    top = {}
    if price is not None:
        top["detected_extensions"] = {"price": price, "currency": currency}
    if extensions is not None:
        top["extensions"] = extensions
    item = {"position": 1, "link": link, "title": title, "snippet": snippet}
    if top:
        item["rich_snippet"] = {"top": top}
    return item


def _listing(**kw) -> ActivityListing:
    base = dict(
        provider="getyourguide",
        url="https://www.getyourguide.com/lisbon-l42/small-group-walking-tour-of-belem-t78184",
        title="Small Group Walking Tour of Belém",
        price_from=33.46,
        currency="USD",
        is_usd=True,
        rating=4.9,
        reviews=80,
        snippet="",
        page_kind="activity",
        query=GYG_QUERY,
        position=5,
    )
    base.update(kw)
    return ActivityListing(**base)


# ── URL normalisation, hosts, page kinds ─────────────────────────────────────


class TestUrls:
    def test_drops_query_fragment_and_trailing_slash(self):
        assert (
            normalise_url(
                "HTTP://WWW.GetYourGuide.com/lisbon-l42/x-t1/?ranking_uuid=a#reviews"
            )
            == "https://www.getyourguide.com/lisbon-l42/x-t1"
        )

    def test_drops_locale_prefix(self):
        assert normalise_url(
            "https://www.getyourguide.com/en-au/lisbon-l42/tuk-tuk-t430393/"
        ) == normalise_url("https://www.getyourguide.com/lisbon-l42/tuk-tuk-t430393")
        assert (
            normalise_url(
                "https://www.viator.com/en-CA/tours/Lisbon/Belem-Walk/d538-88037P242"
            )
            == "https://www.viator.com/tours/Lisbon/Belem-Walk/d538-88037P242"
        )

    def test_keeps_path_case(self):
        assert "/tours/Lisbon/" in normalise_url(
            "https://www.viator.com/tours/Lisbon/Belem/d538-1P1"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.tripadvisor.com/Attraction_Review-g189158-d524074",
            "https://www.booking.com/attractions/pt/x.html",
            "https://getyourguide.com.evil.example/lisbon-l42/x-t1/",
            "https://notgetyourguide.com/lisbon-l42/x-t1/",
            "",
            "not a url",
        ],
    )
    def test_other_hosts_are_not_providers(self, url):
        assert ap.provider_of(url) is None

    def test_provider_hosts(self):
        assert ap.provider_of("https://www.getyourguide.com/a-t1/") == "getyourguide"
        assert ap.provider_of("https://getyourguide.com/a-t1/") == "getyourguide"
        assert ap.provider_of("https://www.viator.com/tours/X/y/d1-2P3") == "viator"

    @pytest.mark.parametrize(
        "url,kind",
        [
            (
                "https://www.getyourguide.com/lisbon-l42/small-group-walking-tour-of-belem-t78184/",
                "activity",
            ),
            (
                "https://www.getyourguide.com/en-au/lisbon-l42/tuk-tuk-t430393/",
                "activity",
            ),
            (
                "https://www.getyourguide.com/jeronimos-monastery-l3594/entry-tickets-tc123/",
                "category",
            ),
            (
                "https://www.getyourguide.com/en-au/jeronimos-monastery-l3594/",
                "category",
            ),
            (
                "https://www.getyourguide.com/es-es/destinations/biblioteca-joanina-l180368/",
                "category",
            ),
            ("https://www.getyourguide.com/lisbon-grand-tours-s815446/", None),
            ("https://www.getyourguide.com/", None),
            (
                "https://www.viator.com/tours/Lisbon/Belem-Walking-Tour/d538-5581413P1",
                "activity",
            ),
            (
                "https://www.viator.com/en-IE/Lisbon-attractions/Belem-Tower-Torre-de-Belem/d538-a805",
                "category",
            ),
            (
                "https://www.viator.com/Lisbon-tours/Day-Trips-and-Excursions/d538-g5",
                "category",
            ),
            ("https://www.viator.com/Belem/d50282", "category"),
            ("https://www.viator.com/sv-SE/blog/Best-Things-To-Do/l101563", None),
            ("https://www.tripadvisor.com/Attraction_Review-g1-d2", None),
        ],
    )
    def test_page_kind(self, url, kind):
        assert page_kind(url) == kind


# ── Price parsing ────────────────────────────────────────────────────────────


class TestParsePrice:
    def test_detected_extensions_dollar(self):
        assert parse_price(_item("u", price=11.63, currency="$")) == (11.63, "USD")

    @pytest.mark.parametrize(
        "symbol,code",
        [("€", "EUR"), ("A$", "AUD"), ("£", "GBP"), ("US$", "USD"), ("C$", "CAD")],
    )
    def test_detected_extensions_other_currencies(self, symbol, code):
        assert parse_price(_item("u", price=25.34, currency=symbol)) == (25.34, code)

    def test_unknown_symbol_kept_raw(self):
        assert parse_price(_item("u", price=100.0, currency="Kč")) == (100.0, "Kč")

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Starting from $11.63", (11.63, "USD")),
            ("From US$9.90", (9.9, "USD")),
            ("from €11", (11.0, "EUR")),
            ("Starting from A$1,025.50", (1025.5, "AUD")),
            ("from € 11,50", (11.5, "EUR")),
        ],
    )
    def test_extensions_text(self, text, expected):
        assert parse_price(_item("u", extensions=["4.3(59,566)", text])) == expected

    def test_snippet_fallback(self):
        item = _item("u", snippet="Small group tour. From $45 per person. Book now.")
        assert parse_price(item) == (45.0, "USD")

    def test_snippet_off(self):
        item = _item("u", snippet="From $45 per person")
        assert parse_price(item, use_snippet=False) is None

    def test_per_group_snippet_price_ignored(self):
        item = _item("u", snippet="Private transfer ... From$28 per group ...")
        assert parse_price(item) is None

    @pytest.mark.parametrize(
        "item",
        [
            _item("u"),
            _item("u", extensions=["4.4(3)"]),
            _item("u", snippet="Free cancellation available"),
            _item("u", price=0, currency="$"),
            _item("u", price="n/a", currency="$"),
            {"link": "u", "rich_snippet": {"top": {"detected_extensions": None}}},
        ],
    )
    def test_missing_or_bad_price(self, item):
        assert parse_price(item) is None

    def test_bottom_rich_snippet(self):
        item = {
            "link": "u",
            "rich_snippet": {
                "bottom": {"detected_extensions": {"price": 20.0, "currency": "$"}}
            },
        }
        assert parse_price(item) == (20.0, "USD")


# ── parse_listings on recorded responses ─────────────────────────────────────


class TestParseListings:
    def test_gyg_fixture_priced_only_and_kinds(self):
        listings = parse_listings(_fixture("gyg_belem_tower"), GYG_QUERY)
        urls = [x.url for x in listings]
        # unpriced UNESCO category + unpriced private tour are dropped
        assert len(listings) == 7
        assert not any("unesco-sites" in u for u in urls)
        assert not any("king-christ" in u for u in urls)
        # activity pages first, search order kept within each kind
        kinds = [x.page_kind for x in listings]
        assert kinds == ["activity"] * 3 + ["category"] * 4
        first = listings[0]
        assert first.provider == "getyourguide"
        assert first.url == (
            "https://www.getyourguide.com/lisbon-l42/"
            "jeronimos-monastery-entry-ticket-with-audio-guide-t1374987"
        )
        assert first.price_from == 22.87
        assert first.currency == "USD" and first.is_usd
        assert first.rating == 4.0 and first.reviews == 501
        assert first.query == GYG_QUERY
        assert first.is_category is False
        tower = next(x for x in listings if "belem-tower-l3590" in x.url)
        assert tower.price_from == 11.63 and tower.is_category

    def test_viator_fixture_has_no_priced_listing(self):
        assert parse_listings(_fixture("viator_belem_tower"), "q") == []

    def test_no_priced_fixture_only_wrong_place_category(self):
        listings = parse_listings(_fixture("gyg_no_priced"), "q")
        # booking.com / tripadvisor / supplier pages excluded; one € category left
        assert len(listings) == 1
        only = listings[0]
        assert only.page_kind == "category"
        assert only.currency == "EUR" and only.is_usd is False
        assert "palacio-nacional-de-ajuda" in only.url

    def test_category_snippet_prices_are_not_page_prices(self):
        data = {
            "organic_results": [
                _item(
                    "https://www.viator.com/Lisbon-attractions/Belem-Tower/d538-a805",
                    snippet="Belem Tower Exterior Tour 2 hours from €30",
                ),
                _item(
                    "https://www.viator.com/tours/Lisbon/Belem-Walk/d538-1P2",
                    snippet="Walk Belém. From $45 per person.",
                ),
            ]
        }
        listings = parse_listings(data, "q")
        assert [(x.page_kind, x.price_from) for x in listings] == [("activity", 45.0)]

    def test_non_provider_hosts_with_price_excluded(self):
        data = {
            "organic_results": [
                _item("https://www.klook.com/activity/1-belem/", price=10.0),
                _item("https://www.getyourguide.com/lisbon-l42/belem-t9/", price=12.0),
            ]
        }
        assert [x.provider for x in parse_listings(data, "q")] == ["getyourguide"]

    def test_duplicate_urls_collapse(self):
        data = {
            "organic_results": [
                _item("https://www.getyourguide.com/lisbon-l42/belem-t9/", price=12.0),
                _item(
                    "https://www.getyourguide.com/en-au/lisbon-l42/belem-t9/?x=1",
                    price=19.0,
                    currency="A$",
                ),
            ]
        }
        listings = parse_listings(data, "q")
        assert len(listings) == 1 and listings[0].price_from == 12.0

    def test_garbage_shapes(self):
        assert parse_listings({}, "q") == []
        assert parse_listings({"organic_results": None}, "q") == []
        assert parse_listings({"organic_results": ["x", None, {"link": 5}]}, "q") == []


# ── Matching ─────────────────────────────────────────────────────────────────


class TestMatchListing:
    def test_picks_activity_page(self):
        listings = parse_listings(_fixture("gyg_belem_tower"), GYG_QUERY)
        m = match_listing("Small group walking tour of Belém", listings, city="Lisbon")
        assert m is not None and m.url.endswith(
            "small-group-walking-tour-of-belem-t78184"
        )
        assert not m.is_category

    def test_accent_insensitive(self):
        listings = parse_listings(_fixture("gyg_belem_tower"), GYG_QUERY)
        m = match_listing(
            "Jeronimos Monastery skip the line entry", listings, city="Lisbon"
        )
        assert m is not None and m.url.endswith("t1374987")

    def test_category_only_when_nothing_better_and_flagged(self):
        listings = parse_listings(_fixture("gyg_belem_tower"), GYG_QUERY)
        m = match_listing("Belém Tower", listings, city="Lisbon")
        # no activity page names the tower; the tower's category page is flagged
        assert m is not None and m.is_category
        assert "belem-tower-l3590" in m.url

    def test_activity_beats_category_with_same_words(self):
        listings = [
            _listing(
                url="https://www.getyourguide.com/x-l1/belem-tower-tc1",
                title="The best Belem Tower tours",
                page_kind="category",
            ),
            _listing(
                url="https://www.getyourguide.com/lisbon-l42/belem-tower-entry-t5",
                title="Belem Tower Entry Ticket",
                page_kind="activity",
            ),
        ]
        assert match_listing("Belem Tower", listings).page_kind == "activity"

    @pytest.mark.parametrize(
        "name",
        [
            "Belém Tower tour",  # 'Day Trips from Belém' etc.: tower never in an activity title
            "Lisbon Oceanarium",
            "Sintra Pena Palace day trip",
            "Fado night in Alfama",
        ],
    )
    def test_near_misses_do_not_match_activity_pages(self, name):
        listings = [
            x
            for x in parse_listings(_fixture("gyg_belem_tower"), GYG_QUERY)
            if not x.is_category
        ]
        assert match_listing(name, listings, city="Lisbon") is None

    def test_threshold_boundaries(self):
        # 3 distinctive words → 2 needed (0.67 ≥ 0.6) …
        listing = _listing(title="Jeronimos Monastery Ticket")
        assert (
            match_listing("Jeronimos Monastery cloister visit", [listing]) is None
        )  # 2/4 = 0.5
        assert (
            match_listing("Jeronimos Monastery cloister", [listing]) is not None
        )  # 2/3
        # … 1-2 distinctive words need every word
        assert match_listing("Jeronimos Cloister", [listing]) is None
        assert match_listing("Jeronimos Monastery", [listing]) is not None

    def test_title_crowded_with_other_places_is_rejected(self):
        tuk = _listing(title="Lisbon: Belém Tuk Tuk Tour: Jerónimos, MAAT & Tower ...")
        assert match_listing("Belém Tower", [tuk], city="Lisbon") is None
        entry = _listing(
            title="Lisbon: Belém Tower Skip-the-Line Entry Ticket with Audio Guide"
        )
        assert match_listing("Belém Tower", [entry], city="Lisbon") is entry

    def test_city_words_never_count(self):
        listing = _listing(title="Lisbon: Tuk Tuk Tour")
        assert match_listing("Lisbon cathedral", [listing], city="Lisbon") is None

    def test_generic_only_name_never_matches(self):
        assert (
            match_listing("City walking tour", [_listing(title="City Walking Tour")])
            is None
        )

    def test_tie_break_prefers_tighter_title_then_reviews(self):
        broad = _listing(
            url="https://www.getyourguide.com/a-t1",
            title="Belem Tower and Jeronimos Ticket",
            reviews=999,
        )
        assert match_listing("Belem Tower", [broad]) is broad  # acceptable alone
        tight = _listing(
            url="https://www.getyourguide.com/a-t2",
            title="Belem Tower Entry",
            reviews=10,
        )
        assert match_listing("Belem Tower", [broad, tight]).url.endswith("a-t2")
        twin = _listing(
            url="https://www.getyourguide.com/a-t3",
            title="Belem Tower Entry",
            reviews=500,
        )
        assert match_listing("Belem Tower", [tight, twin]).url.endswith("a-t3")

    def test_empty(self):
        assert match_listing("Belem Tower", []) is None
        assert match_listing("", [_listing()]) is None


def test_suggestions_prefers_activity_pages_and_caps():
    listings = parse_listings(_fixture("gyg_belem_tower"), GYG_QUERY)
    s = suggestions(listings)
    assert len(s) == 3 and all(not x.is_category for x in s)
    assert suggestions(listings, n=5)[3].is_category
    assert suggestions([], n=3) == []
    cats = [x for x in listings if x.is_category]
    assert suggestions(cats, n=2) == cats[:2]


# ── find_listings (network mocked) ───────────────────────────────────────────


class TestFindListings:
    async def test_gyg_confident_match_skips_viator(self):
        client, p = _mock_client(_fixture("gyg_belem_tower"))
        with p:
            listings = await find_listings(
                "Small group walking tour of Belém", "Lisbon", API_KEY
            )
        assert client.get.await_count == 1
        params = client.get.await_args.kwargs["params"]
        assert params["engine"] == "google"
        assert params["q"] == "Small group walking tour of Belém Lisbon getyourguide"
        assert params["api_key"] == API_KEY
        assert params["gl"] == "us" and params["hl"] == "en"
        assert len(listings) == 7

    async def test_falls_back_to_viator_when_gyg_has_no_activity_match(self):
        viator = {
            "organic_results": [
                _item(
                    "https://www.viator.com/en-CA/tours/Lisbon/Belem-Tower-Entry/d538-1P2?mcid=1",
                    title="Belém Tower Skip-the-line Entry",
                    extensions=["From US$14.20"],
                )
            ]
        }
        client, p = _mock_client(_fixture("gyg_belem_tower"), viator)
        with p:
            listings = await find_listings("Belém Tower", "Lisbon", API_KEY)
        assert client.get.await_count == 2
        assert (
            client.get.await_args.kwargs["params"]["q"] == "Belém Tower Lisbon viator"
        )
        v = [x for x in listings if x.provider == "viator"]
        assert (
            len(v) == 1
            and v[0].price_from == 14.2
            and v[0].query == "Belém Tower Lisbon viator"
        )
        assert (
            v[0].url == "https://www.viator.com/tours/Lisbon/Belem-Tower-Entry/d538-1P2"
        )
        # activity pages from both queries sort before category pages
        assert listings[0].page_kind == "activity"
        assert match_listing("Belém Tower", listings, city="Lisbon") == v[0]

    async def test_no_priced_listing_anywhere(self):
        client, p = _mock_client(
            _fixture("gyg_no_priced"), _fixture("viator_belem_tower")
        )
        with p:
            listings = await find_listings(
                "Biblioteca Nacional de Portugal reading room", "Lisbon", API_KEY
            )
        assert client.get.await_count == 2
        assert (
            match_listing(
                "Biblioteca Nacional de Portugal reading room", listings, city="Lisbon"
            )
            is None
        )

    async def test_serpapi_no_results_error_is_empty(self):
        empty = {"error": "Google hasn't returned any results for this query."}
        client, p = _mock_client(empty, empty)
        with p:
            assert await find_listings("Nothing", "Nowhere", API_KEY) == []

    @pytest.mark.parametrize(
        "resp,quota",
        [
            (httpx.Response(429, text="rate"), True),
            (httpx.Response(401, json={"error": "Invalid API key"}), False),
            (httpx.Response(500, text="boom"), False),
            (httpx.TimeoutException("slow"), False),
            (httpx.ConnectError("down"), False),
        ],
    )
    async def test_errors_raise_serpapi_error(self, resp, quota):
        _, p = _mock_client(resp)
        with p, pytest.raises(SerpAPIError) as exc:
            await find_listings("Belem Tower", "Lisbon", API_KEY)
        assert exc.value.quota_exceeded is quota
        assert API_KEY not in str(exc.value)

    async def test_error_with_key_in_body_does_not_leak(self):
        _, p = _mock_client(httpx.Response(400, text=f"bad request api_key={API_KEY}"))
        with p, pytest.raises(SerpAPIError) as exc:
            await find_listings("Belem Tower", "Lisbon", API_KEY)
        assert API_KEY not in str(exc.value)

    async def test_cache_reused_and_key_has_no_api_key(self):
        client, p = _mock_client(_fixture("gyg_belem_tower"))
        with p:
            a = await find_listings(
                "Small group walking tour of Belém", "Lisbon", API_KEY
            )
            b = await find_listings(
                "Small group walking tour of Belém", "Lisbon", "another-key"
            )
        assert client.get.await_count == 1
        assert a == b
        keys = [k for k in get_cache().keys() if str(k).startswith("activity_prices:")]
        assert len(keys) == 1
        assert API_KEY not in keys[0] and "another-key" not in keys[0]
        assert "small group walking tour of belém lisbon getyourguide" in keys[0]

    async def test_errors_are_not_cached(self):
        client, p = _mock_client(
            httpx.Response(500, text="x"), _fixture("gyg_belem_tower")
        )
        with p:
            with pytest.raises(SerpAPIError):
                await find_listings(
                    "Small group walking tour of Belém", "Lisbon", API_KEY
                )
            assert (
                len(
                    await find_listings(
                        "Small group walking tour of Belém", "Lisbon", API_KEY
                    )
                )
                == 7
            )
        assert client.get.await_count == 2


# ── price_listing (re-check) ─────────────────────────────────────────────────


class TestPriceListing:
    async def test_recheck_finds_moved_listing_by_url(self):
        listings = parse_listings(_fixture("gyg_belem_tower"), GYG_QUERY)
        stored = listings[0]
        assert stored.url.endswith("t1374987") and stored.position == 1
        client, p = _mock_client(_fixture("gyg_belem_tower_recheck"))
        with p:
            price = await price_listing(stored, GYG_QUERY, API_KEY)
        assert client.get.await_args.kwargs["params"]["q"] == GYG_QUERY
        assert price.available is True
        assert price.price_from == 22.87 and price.currency == "USD" and price.is_usd
        assert price.url == stored.url
        assert price.matched_by == "url"
        assert price.position == 6
        assert price.source == "getyourguide_via_google"
        assert price.observed.endswith("+00:00")

    async def test_recheck_listing_present_without_price_is_unavailable(self):
        stored = _listing()  # t78184 lost its price snippet in the re-check
        _, p = _mock_client(_fixture("gyg_belem_tower_recheck"))
        with p:
            price = await price_listing(stored, GYG_QUERY, API_KEY)
        assert price.available is False and price.price_from is None
        assert price.reason == "no_price"

    async def test_recheck_absent_listing_is_unavailable(self):
        stored = _listing(
            url="https://www.getyourguide.com/lisbon-l42/lisbon-belem-tuk-tuk-tour-jeronimos-maat-tower-views-t931107",
            title="Lisbon: Belém Tuk Tuk Tour: Jerónimos, MAAT & Tower ...",
        )
        _, p = _mock_client(_fixture("gyg_belem_tower_recheck"))
        with p:
            price = await price_listing(stored, GYG_QUERY, API_KEY)
        # a different tuk-tuk tour is in the results; titles are not close enough
        assert price.available is False and price.reason == "not_found"
        assert price.price_from is None and price.url == stored.url

    async def test_recheck_same_provider_near_identical_title(self):
        stored = _listing(
            url="https://www.getyourguide.com/lisbon-l42/old-slug-t111",
            title="Belem Cristo Rei Historical Part of Lisbon City",
        )
        _, p = _mock_client(_fixture("gyg_belem_tower_recheck"))
        with p:
            price = await price_listing(stored, GYG_QUERY, API_KEY)
        assert price.available is True and price.matched_by == "title"
        assert price.url.endswith(
            "belem-cristo-rei-historical-part-of-lisbon-city-t536629"
        )
        assert price.price_from == 140.06

    async def test_recheck_title_fallback_needs_same_provider_and_activity_page(self):
        data = {
            "organic_results": [
                _item(
                    "https://www.viator.com/tours/Lisbon/Belem-Cristo/d538-9P1",
                    title="Belem Cristo Rei Historical Part of Lisbon City",
                    price=99.0,
                ),
                _item(
                    "https://www.getyourguide.com/belem-l1/belem-cristo-tc5/",
                    title="Belem Cristo Rei Historical Part of Lisbon City",
                    price=5.0,
                ),
            ]
        }
        stored = _listing(
            url="https://www.getyourguide.com/lisbon-l42/old-slug-t111",
            title="Belem Cristo Rei Historical Part of Lisbon City",
        )
        _, p = _mock_client(data)
        with p:
            price = await price_listing(stored, GYG_QUERY, API_KEY)
        assert price.available is False and price.reason == "not_found"

    async def test_recheck_non_usd_price_kept_and_flagged(self):
        stored = _listing(
            url="https://www.getyourguide.com/lisbon-l42/from-lisbon-belem-historic-sightseeing-tour-by-tuk-tuk-t430393",
            title="Lisbon: Belem Sightseeing TukTuk Tour With Pickup ...",
        )
        _, p = _mock_client(_fixture("gyg_belem_tower_recheck"))
        with p:
            price = await price_listing(stored, GYG_QUERY, API_KEY)
        assert price.available and price.price_from == 77.48
        assert price.currency == "AUD" and price.is_usd is False

    async def test_recheck_viator_source(self):
        stored = _listing(
            provider="viator",
            url="https://www.viator.com/tours/Lisbon/Belem/d538-1P1",
            title="Belem walk",
        )
        data = {
            "organic_results": [
                _item(
                    "https://www.viator.com/en-GB/tours/Lisbon/Belem/d538-1P1?x=1",
                    price=30.0,
                )
            ]
        }
        _, p = _mock_client(data)
        with p:
            price = await price_listing(stored, "q viator", API_KEY)
        assert (
            price.available
            and price.source == "viator_via_google"
            and price.price_from == 30.0
        )

    async def test_recheck_error_raises(self):
        _, p = _mock_client(httpx.Response(503, text="x"))
        with p, pytest.raises(SerpAPIError):
            await price_listing(_listing(), GYG_QUERY, API_KEY)

    async def test_recheck_uses_cache(self):
        client, p = _mock_client(_fixture("gyg_belem_tower_recheck"))
        with p:
            a = await price_listing(_listing(), GYG_QUERY, API_KEY)
            b = await price_listing(_listing(), GYG_QUERY, API_KEY)
        assert client.get.await_count == 1
        assert a.observed == b.observed  # observation time is the fetch time


def test_fixtures_carry_no_api_key_or_serpapi_links():
    for path in FIXTURES.glob("*.json"):
        text = path.read_text()
        assert "api_key" not in text, path.name
        assert "serpapi.com/search" not in text, path.name
