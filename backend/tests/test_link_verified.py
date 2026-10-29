"""Evidence flag `link_verified` set by hotel and place enrichment."""

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
            side_effect=["https://www.tripadvisor.com/Attraction-x", None]
        )
        data = {"results": [{"name": "Senso-ji Temple"}, {"name": "Meiji Shrine"}]}
        out = await resolve_top_places(resolver, data, "Tokyo")
        assert out["results"][0]["link_verified"] is True
        assert "link_verified" not in out["results"][1]
