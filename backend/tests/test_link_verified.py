"""Evidence flag `link_verified` set by hotel and place enrichment."""

from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.agents.hotels_agent import HotelsAgent
from app.services.places_url_resolver import resolve_top_places


def _agent(search_url):
    agent = HotelsAgent.__new__(HotelsAgent)
    agent._destination = "Tokyo, Japan"
    agent._search_url = search_url
    return agent


class TestHotelLinkVerified:
    @pytest.mark.asyncio
    async def test_matched_is_true_and_url_replaced(self):
        agent = _agent(
            AsyncMock(return_value="https://www.booking.com/hotel/jp/x.html")
        )
        data = {"results": [{"name": "Hotel X", "source": "booking.com"}]}
        out = await agent._enrich_urls(data)
        hotel = out["results"][0]
        assert hotel["link_verified"] is True
        assert hotel["booking_url"] == "https://www.booking.com/hotel/jp/x.html"

    @pytest.mark.asyncio
    async def test_unmatched_after_both_searches_is_false(self):
        search = AsyncMock(return_value=None)
        agent = _agent(search)
        out = await agent._enrich_urls({"results": [{"name": "Hotel X"}]})
        assert out["results"][0]["link_verified"] is False
        assert search.await_count == 2

    @pytest.mark.asyncio
    async def test_official_website_fallback_counts_as_true(self):
        agent = _agent(AsyncMock(side_effect=[None, "https://hotelx.jp/"]))
        out = await agent._enrich_urls({"results": [{"name": "Hotel X"}]})
        assert out["results"][0]["link_verified"] is True

    @pytest.mark.asyncio
    async def test_official_website_fallback_replaces_booking_url(self):
        agent = _agent(AsyncMock(side_effect=[None, "https://hotelx.jp/"]))
        data = {"results": [{"name": "Hotel X", "booking_url": "https://old"}]}
        out = await agent._enrich_urls(data)
        assert out["results"][0]["booking_url"] == "https://hotelx.jp/"

    @pytest.mark.asyncio
    async def test_nameless_and_beyond_cap_have_no_flag(self):
        agent = _agent(
            AsyncMock(return_value="https://www.booking.com/hotel/jp/x.html")
        )
        hotels = [{"name": ""}] + [{"name": f"H{i}"} for i in range(agent._MAX_ENRICH)]
        out = await agent._enrich_urls({"results": hotels})
        assert "link_verified" not in out["results"][0]
        assert out["results"][agent._MAX_ENRICH - 1]["link_verified"] is True
        assert "link_verified" not in out["results"][-1]


class TestPlaceLinkVerified:
    @pytest.mark.asyncio
    async def test_resolved_true_unresolved_absent(self):
        resolver = AsyncMock()
        resolver.resolve = AsyncMock(
            side_effect=[
                ("https://www.tripadvisor.com/Attraction-x", "Senso-ji Temple"),
                None,
            ]
        )
        data = {"results": [{"name": "Senso-ji Temple"}, {"name": "Meiji Shrine"}]}
        out = await resolve_top_places(resolver, data, "Tokyo")
        assert out["results"][0]["link_verified"] is True
        assert "link_verified" not in out["results"][1]


class TestModelSuppliedFlagStripped:
    @pytest.mark.asyncio
    async def test_hotels_run_strips_flag_incl_nameless_and_beyond_cap(self):
        from app.schemas.request import TravelSearchRequest

        agent = HotelsAgent.__new__(HotelsAgent)
        hotels = [{"name": "", "link_verified": True}] + [
            {"name": f"H{i}", "link_verified": True} for i in range(20)
        ]
        agent.execute = AsyncMock(return_value={"results": hotels})
        req = TravelSearchRequest.model_construct(
            origin="NYC",
            destination="Tokyo",
            departure_date=date(2026, 4, 1),
            return_date=date(2026, 4, 8),
            nationality="American",
        )
        out = await agent.run(req)
        assert all("link_verified" not in h for h in out["results"])

    @pytest.mark.asyncio
    async def test_places_run_strips_flag_and_static_info_url_unflagged(self):
        from unittest.mock import patch

        from app.agents.places_agent import PlacesAgent
        from app.schemas.request import TravelSearchRequest

        agent = PlacesAgent.__new__(PlacesAgent)
        agent.execute = AsyncMock(
            return_value={
                "results": [{"name": "Senso-ji Temple", "link_verified": True}]
            }
        )
        req = TravelSearchRequest.model_construct(
            origin="NYC",
            destination="Tokyo",
            departure_date=date(2026, 4, 1),
            return_date=date(2026, 4, 8),
            nationality="American",
        )
        with patch("app.agents.places_agent.settings") as s:
            s.serper_key = ""
            out = await agent.run(req)
        place = out["results"][0]
        # static TripAdvisor fallback sets info_url but is not evidence
        assert place["info_url"].startswith("https://www.tripadvisor.com/Search")
        assert "link_verified" not in place


# ── Name-matched evidence (final-review fix wave) ─────────────────────


def _search_text(*pairs: tuple[str, str]) -> str:
    return "\n".join(f"Title: {t}\nURL: {u}" for t, u in pairs)


class TestHotelNameMatchExcludesDestination:
    @pytest.mark.asyncio
    async def test_generic_city_name_does_not_match_city_listing(self):
        from unittest.mock import patch

        agent = HotelsAgent.__new__(HotelsAgent)
        agent._destination = "Berlin"
        listing = _search_text(
            (
                "Hotels in Berlin - Book Now",
                "https://www.booking.com/city/de/berlin.html",
            )
        )
        with patch(
            "app.agents.web_tools.execute_tool", AsyncMock(return_value=listing)
        ):
            out = await agent._enrich_urls({"results": [{"name": "Hotel Berlin"}]})
        hotel = out["results"][0]
        assert hotel["link_verified"] is False
        assert "booking_url" not in hotel

    @pytest.mark.asyncio
    async def test_distinctive_hotel_name_matches(self):
        from unittest.mock import patch

        agent = HotelsAgent.__new__(HotelsAgent)
        agent._destination = "Berlin, Germany"
        url = "https://www.booking.com/hotel/de/adlon-kempinski.html"
        listing = _search_text(("Hotel Adlon Kempinski Berlin – Booking.com", url))
        with patch(
            "app.agents.web_tools.execute_tool", AsyncMock(return_value=listing)
        ):
            out = await agent._enrich_urls(
                {"results": [{"name": "Hotel Adlon Kempinski Berlin"}]}
            )
        hotel = out["results"][0]
        assert hotel["link_verified"] is True
        assert hotel["booking_url"] == url


class TestActivityNameMatchedEvidence:
    @pytest.mark.asyncio
    async def test_title_without_name_upgrades_url_without_flag(self):
        from app.core.cache import get_cache
        from app.services.activity_url_resolver import resolve_top

        get_cache().clear()
        url = "https://www.getyourguide.com/tokyo-l193/sumo-show-t9"
        resolver = AsyncMock()
        resolver.resolve = AsyncMock(return_value=(url, "Tokyo Sumo Show with Dinner"))
        data = {
            "results": [
                {"name": "Tsukiji Outer Market Food Tour", "similarity_score": 0.9}
            ]
        }
        out = await resolve_top(resolver, data, "Tokyo")
        item = out["results"][0]
        assert item["booking_url"] == url
        assert "link_verified" not in item
        assert item["link_checked"] is True

    @pytest.mark.asyncio
    async def test_title_with_name_sets_flag(self):
        from app.core.cache import get_cache
        from app.services.activity_url_resolver import resolve_top

        get_cache().clear()
        url = "https://www.getyourguide.com/tokyo-l193/tsukiji-t1"
        resolver = AsyncMock()
        resolver.resolve = AsyncMock(
            return_value=(url, "Tokyo: Tsukiji Outer Market Food and Sushi Tour")
        )
        data = {
            "results": [
                {"name": "Tsukiji Outer Market Food Tour", "similarity_score": 0.9}
            ]
        }
        out = await resolve_top(resolver, data, "Tokyo")
        item = out["results"][0]
        assert item["booking_url"] == url
        assert item["link_verified"] is True
        assert item["link_checked"] is True

    @pytest.mark.asyncio
    async def test_only_searched_items_marked_checked(self):
        from app.core.cache import get_cache
        from app.services.activity_url_resolver import resolve_top

        get_cache().clear()
        resolver = AsyncMock()
        resolver.resolve = AsyncMock(return_value=None)
        data = {
            "results": [
                {"name": "Tsukiji Outer Market Food Tour", "similarity_score": 0.9},
                {"name": "Unscored Activity Name"},
            ]
        }
        out = await resolve_top(resolver, data, "Tokyo")
        assert out["results"][0]["link_checked"] is True
        assert "link_verified" not in out["results"][0]
        assert "link_checked" not in out["results"][1]


class TestPlaceNameMatchedEvidence:
    @pytest.mark.asyncio
    async def test_title_without_name_upgrades_url_without_flag(self):
        url = "https://www.tripadvisor.com/Attractions-g1-Tokyo.html"
        resolver = AsyncMock()
        resolver.resolve = AsyncMock(
            return_value=(url, "THE 15 BEST Things to Do in Tokyo")
        )
        data = {"results": [{"name": "Senso-ji Temple"}]}
        out = await resolve_top_places(resolver, data, "Tokyo")
        place = out["results"][0]
        assert place["info_url"] == url
        assert "link_verified" not in place
        assert place["link_checked"] is True

    @pytest.mark.asyncio
    async def test_title_with_name_sets_flag_and_short_names_unchecked(self):
        url = "https://www.tripadvisor.com/Attraction-sensoji"
        resolver = AsyncMock()
        resolver.resolve = AsyncMock(
            return_value=(url, "Senso-ji Temple (Asakusa) - Tripadvisor")
        )
        data = {"results": [{"name": "Senso-ji Temple"}, {"name": "Zoo"}]}
        out = await resolve_top_places(resolver, data, "Tokyo")
        assert out["results"][0]["link_verified"] is True
        assert out["results"][0]["link_checked"] is True
        assert "link_checked" not in out["results"][1]


class TestNameMatchHelper:
    def test_thresholds_and_exclusion(self):
        from app.services.name_match import name_matches_title

        assert name_matches_title("Senso-ji Temple", "Senso-ji Temple, Asakusa")
        assert not name_matches_title("Senso-ji Temple", "Meiji Shrine")
        assert not name_matches_title(
            "Hotel Berlin", "Hotels in Berlin", exclude=("Berlin",)
        )
        assert name_matches_title(
            "Park Hyatt Tokyo", "Park Hyatt Tokyo – Official", exclude=("Tokyo",)
        )


# ── Exclusion applies before the generic-word fallback ────────────────


class TestExcludeBeforeFallback:
    def test_city_plus_generic_hotel_word_never_matches(self):
        from app.services.name_match import distinctive_words, name_matches_title

        assert distinctive_words("New York Hotel", exclude=("New York",)) == set()
        assert not name_matches_title(
            "New York Hotel", "Best Hotel Deals", exclude=("New York",)
        )

    def test_distinctive_hotel_still_matches_with_destination_excluded(self):
        from app.services.name_match import name_matches_title

        assert name_matches_title(
            "Hotel Adlon Kempinski",
            "Hotel Adlon Kempinski Berlin – Official Site",
            exclude=("Berlin",),
        )

    def test_generic_words_alone_are_not_distinctive(self):
        from app.services.name_match import distinctive_words

        assert distinctive_words("The City Museum Tour") == set()
        # place-name stop words still fall back when nothing is excluded
        assert distinctive_words("New York") == {"new", "york"}

    @pytest.mark.asyncio
    async def test_hotel_new_york_vs_generic_deals_page(self):
        from unittest.mock import patch

        agent = HotelsAgent.__new__(HotelsAgent)
        agent._destination = "New York"
        page = _search_text(("Best Hotel Deals", "https://www.expedia.com/deals"))
        with patch("app.agents.web_tools.execute_tool", AsyncMock(return_value=page)):
            out = await agent._enrich_urls({"results": [{"name": "New York Hotel"}]})
        assert out["results"][0]["link_verified"] is False


class TestResolverDestinationExclusion:
    @pytest.mark.asyncio
    async def test_city_tour_vs_city_listing_upgrades_without_flag(self):
        from app.core.cache import get_cache
        from app.services.activity_url_resolver import resolve_top

        get_cache().clear()
        url = "https://www.getyourguide.com/berlin-l17/"
        resolver = AsyncMock()
        resolver.resolve = AsyncMock(
            return_value=(url, "Top Berlin Tours | GetYourGuide")
        )
        data = {"results": [{"name": "Berlin City Tour", "similarity_score": 0.9}]}
        out = await resolve_top(resolver, data, "Berlin")
        item = out["results"][0]
        assert item["booking_url"] == url
        assert "link_verified" not in item
        assert item["link_checked"] is True

    @pytest.mark.asyncio
    async def test_distinctive_activity_matches(self):
        from app.core.cache import get_cache
        from app.services.activity_url_resolver import resolve_top

        get_cache().clear()
        url = "https://www.getyourguide.com/berlin-l17/pergamon-t5"
        resolver = AsyncMock()
        resolver.resolve = AsyncMock(
            return_value=(url, "Berlin: Pergamon Museum Guided Tour with Tickets")
        )
        data = {
            "results": [
                {"name": "Pergamon Museum Guided Tour", "similarity_score": 0.9}
            ]
        }
        out = await resolve_top(resolver, data, "Berlin")
        assert out["results"][0]["link_verified"] is True

    @pytest.mark.asyncio
    async def test_multi_city_item_city_is_excluded(self):
        from app.core.cache import get_cache
        from app.services.activity_url_resolver import resolve_top

        get_cache().clear()
        url = "https://www.getyourguide.com/munich-l26/"
        resolver = AsyncMock()
        resolver.resolve = AsyncMock(
            return_value=(url, "Munich City Tours | GetYourGuide")
        )
        data = {
            "results": [
                {
                    "name": "Munich City Tour",
                    "city": "Munich",
                    "similarity_score": 0.9,
                }
            ]
        }
        out = await resolve_top(resolver, data, "Berlin")
        assert "link_verified" not in out["results"][0]

    @pytest.mark.asyncio
    async def test_place_city_listing_not_flagged(self):
        url = "https://www.tripadvisor.com/Attractions-g187323-Berlin.html"
        resolver = AsyncMock()
        resolver.resolve = AsyncMock(
            return_value=(url, "Museum Island Berlin - Things to Do - Tripadvisor")
        )
        data = {"results": [{"name": "Berlin Museum"}]}
        out = await resolve_top_places(resolver, data, "Berlin")
        assert out["results"][0]["info_url"] == url
        assert "link_verified" not in out["results"][0]
