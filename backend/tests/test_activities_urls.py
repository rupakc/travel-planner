"""Unit tests for activity URL generation and Serper/SerpAPI resolver."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.agents.activities_agent import _build_search_url, _sanitize_query
from app.services.activity_url_resolver import (
    SerpAPIActivityResolver,
    SerperActivityResolver,
    _is_trusted,
    _pick_resolver,
    resolve_top,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_serper_cache():
    from app.core.cache import get_cache

    get_cache().clear()
    yield
    get_cache().clear()


def _make_serper_response(links: list[str]) -> dict:
    return {
        "organic": [
            {"title": f"Result {i}", "link": link} for i, link in enumerate(links)
        ]
    }


def _make_serpapi_response(links: list[str]) -> dict:
    return {
        "organic_results": [
            {"title": f"Result {i}", "link": link} for i, link in enumerate(links)
        ]
    }


def _make_activities(names_and_scores: list[tuple[str, float]]) -> list[dict]:
    return [
        {
            "name": name,
            "source": "getyourguide",
            "similarity_score": score,
            "booking_url": f"https://www.getyourguide.com/s/?q={name.replace(' ', '+')}+Tokyo",
        }
        for name, score in names_and_scores
    ]


# ── TestBuildSearchUrl ────────────────────────────────────────────────────────


class TestBuildSearchUrl:
    def test_getyourguide_template(self):
        url = _build_search_url("Tsukiji Food Tour", "Tokyo", "getyourguide")
        assert "getyourguide.com/s/?q=" in url
        assert "Tsukiji" in url
        assert "Tokyo" in url

    def test_viator_template(self):
        url = _build_search_url("Colosseum Tour", "Rome", "viator")
        assert "viator.com/searchResults/all?text=" in url
        assert "Colosseum" in url

    def test_klook_template(self):
        url = _build_search_url("Disneyland Day Pass", "Hong Kong", "klook")
        assert "klook.com/search/?query=" in url

    def test_tripadvisor_template(self):
        url = _build_search_url("Seine River Cruise", "Paris", "tripadvisor")
        assert "tripadvisor.com/Search?q=" in url

    def test_unknown_source_fallback(self):
        url = _build_search_url("Walking Tour", "Berlin", "unknown_platform")
        assert "google.com/search?q=" in url

    def test_null_source_fallback(self):
        url = _build_search_url("Walking Tour", "Berlin", None)
        assert "google.com/search?q=" in url

    def test_spaces_url_encoded(self):
        url = _build_search_url("Skip the Line Tour", "Paris", "viator")
        assert "+" in url or "%20" in url
        assert " " not in url

    def test_comma_in_destination_stripped(self):
        url = _build_search_url("Inca Trail Trek", "Cusco, Peru", "viator")
        assert "%2C" not in url
        assert "Cusco" in url
        assert "Peru" in url

    def test_ampersand_in_name_stripped(self):
        # "Street Art & Murals Tour" — & must not appear as %26
        url = _build_search_url(
            "Street Art & Murals Tour in La Boca", "Buenos Aires, Argentina", "viator"
        )
        assert "%26" not in url
        assert "&" not in url

    def test_colon_in_name_stripped(self):
        url = _build_search_url(
            "Literary Buenos Aires: Borges & Bookstore Tour",
            "Buenos Aires, Argentina",
            "viator",
        )
        query = url.split("?", 1)[1]  # check only the query string, not https://
        assert "%3A" not in query
        assert ":" not in query

    def test_accented_chars_normalized(self):
        # Cortázar → Cortazar, á → a
        url = _build_search_url(
            "Cortázar & Borges Literary Tour", "Buenos Aires, Argentina", "viator"
        )
        assert "%C3" not in url
        assert "Cort" in url  # "Cortazar" in URL

    def test_name_truncated_to_six_words(self):
        long_name = "One Two Three Four Five Six Seven Eight Nine Ten"
        url = _build_search_url(long_name, "Paris", "viator")
        # Should contain "One Two Three Four Five Six" but not "Seven"
        assert "Seven" not in url
        assert "Six" in url


# ── TestSanitizeQuery ─────────────────────────────────────────────────────────


class TestSanitizeQuery:
    def test_strips_accents(self):
        assert _sanitize_query("Cortázar") == "Cortazar"
        assert _sanitize_query("São Paulo") == "Sao Paulo"
        assert _sanitize_query("Ñoño") == "Nono"

    def test_replaces_ampersand(self):
        assert "&" not in _sanitize_query("Food & Wine Tour")
        assert "Food" in _sanitize_query("Food & Wine Tour")

    def test_replaces_colon(self):
        assert ":" not in _sanitize_query("Tour: Highlights")

    def test_strips_comma(self):
        assert "," not in _sanitize_query("Buenos Aires, Argentina")
        assert _sanitize_query("Buenos Aires, Argentina") == "Buenos Aires Argentina"

    def test_collapses_whitespace(self):
        assert _sanitize_query("a  b   c") == "a b c"

    def test_plain_text_unchanged(self):
        assert _sanitize_query("Inca Trail Tour") == "Inca Trail Tour"


# ── TestIsTrusted ─────────────────────────────────────────────────────────────


class TestIsTrusted:
    def test_getyourguide_trusted(self):
        assert _is_trusted("https://www.getyourguide.com/tokyo-l193/tour-t123")

    def test_viator_trusted(self):
        assert _is_trusted("https://www.viator.com/tours/Tokyo/Food-Tour/d334-12345")

    def test_tripadvisor_trusted(self):
        assert _is_trusted("https://www.tripadvisor.com/Attraction_Review-Tokyo.html")

    def test_reddit_not_trusted(self):
        assert not _is_trusted("https://www.reddit.com/r/travel/comments/abc")

    def test_empty_not_trusted(self):
        assert not _is_trusted("")

    def test_subdomain_trusted(self):
        assert _is_trusted("https://partner.getyourguide.com/en/activities/123")


# ── TestPickResolver ──────────────────────────────────────────────────────────


class TestPickResolver:
    def test_serper_preferred_over_serpapi(self):
        class FakeSettings:
            serper_key = "serper-key"
            serpapi_key = "serpapi-key"

        resolver = _pick_resolver(FakeSettings())
        assert isinstance(resolver, SerperActivityResolver)

    def test_falls_back_to_serpapi(self):
        class FakeSettings:
            serper_key = ""
            serpapi_key = "serpapi-key"

        resolver = _pick_resolver(FakeSettings())
        assert isinstance(resolver, SerpAPIActivityResolver)

    def test_returns_none_when_no_keys(self):
        class FakeSettings:
            serper_key = ""
            serpapi_key = ""

        assert _pick_resolver(FakeSettings()) is None


# ── TestSerperActivityResolver ────────────────────────────────────────────────


class TestSerperActivityResolver:
    @pytest.mark.asyncio
    async def test_returns_trusted_url(self):
        gyg_url = "https://www.getyourguide.com/tokyo-l193/tsukiji-tour-t123"
        mock_resp = httpx.Response(200, json=_make_serper_response([gyg_url]))

        with patch("app.services.activity_url_resolver._get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_gc.return_value = mock_client

            resolver = SerperActivityResolver("test-key")
            result = await resolver.resolve("Tsukiji Food Tour", "Tokyo")

        assert result == gyg_url

    @pytest.mark.asyncio
    async def test_skips_untrusted_returns_none(self):
        mock_resp = httpx.Response(
            200,
            json=_make_serper_response(
                ["https://reddit.com/r/travel", "https://medium.com/article"]
            ),
        )

        with patch("app.services.activity_url_resolver._get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_gc.return_value = mock_client

            resolver = SerperActivityResolver("test-key")
            result = await resolver.resolve("Mystery Tour", "Paris")

        assert result is None

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        mock_resp = httpx.Response(403, text="Forbidden")

        with patch("app.services.activity_url_resolver._get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_gc.return_value = mock_client

            resolver = SerperActivityResolver("bad-key")
            result = await resolver.resolve("Some Tour", "London")

        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        with patch("app.services.activity_url_resolver._get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_gc.return_value = mock_client

            resolver = SerperActivityResolver("test-key")
            result = await resolver.resolve("Some Tour", "Berlin")

        assert result is None


# ── TestResolveTop ────────────────────────────────────────────────────────────


class TestResolveTop:
    @pytest.mark.asyncio
    async def test_upgrades_top_activity_url(self):
        gyg_url = "https://www.getyourguide.com/tokyo-l193/tsukiji-tour-t123"
        activities = _make_activities(
            [("Tsukiji Outer Market Food Tour", 0.95), ("Low Score Activity", 0.2)]
        )
        data = {"results": activities}

        mock_resolver = AsyncMock()
        mock_resolver.resolve = AsyncMock(return_value=gyg_url)

        result = await resolve_top(mock_resolver, data, "Tokyo")

        assert result["results"][0]["booking_url"] == gyg_url
        # Low score activity's URL should be unchanged (not in top 5 by score but still processed)

    @pytest.mark.asyncio
    async def test_keeps_tier1_url_if_no_trusted_result(self):
        tier1_url = "https://www.getyourguide.com/s/?q=Colosseum+Tour+Rome&et=2"
        activities = [
            {
                "name": "Colosseum Skip the Line Tour",
                "source": "getyourguide",
                "similarity_score": 0.9,
                "booking_url": tier1_url,
            }
        ]
        data = {"results": activities}

        mock_resolver = AsyncMock()
        mock_resolver.resolve = AsyncMock(return_value=None)

        result = await resolve_top(mock_resolver, data, "Rome")

        assert result["results"][0]["booking_url"] == tier1_url

    @pytest.mark.asyncio
    async def test_deduplicates_same_url(self):
        same_url = "https://www.getyourguide.com/tokyo-l193/generic-page"
        activities = _make_activities(
            [
                ("Tsukiji Outer Market Food Tour", 0.95),
                ("Shibuya Food Walking Tour Experience", 0.90),
            ]
        )
        data = {"results": activities}

        mock_resolver = AsyncMock()
        mock_resolver.resolve = AsyncMock(return_value=same_url)

        result = await resolve_top(mock_resolver, data, "Tokyo")

        urls = [a["booking_url"] for a in result["results"]]
        assert urls.count(same_url) <= 1

    @pytest.mark.asyncio
    async def test_cache_prevents_duplicate_http_calls(self):
        gyg_url = "https://www.getyourguide.com/tokyo-l193/tour-t456"
        activities = _make_activities([("Tsukiji Outer Market Food Tour", 0.95)])
        data1 = {"results": [dict(activities[0])]}
        data2 = {"results": [dict(activities[0])]}

        mock_resolver = AsyncMock()
        mock_resolver.resolve = AsyncMock(return_value=gyg_url)

        await resolve_top(mock_resolver, data1, "Tokyo")
        await resolve_top(mock_resolver, data2, "Tokyo")

        assert mock_resolver.resolve.call_count == 1  # cached on second call

    @pytest.mark.asyncio
    async def test_empty_results_noop(self):
        data = {"results": []}
        mock_resolver = AsyncMock()
        mock_resolver.resolve = AsyncMock(return_value=None)

        result = await resolve_top(mock_resolver, data, "Tokyo")

        assert result == {"results": []}
        mock_resolver.resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_short_names(self):
        activities = [
            {
                "name": "Tour",  # < 10 chars
                "source": "viator",
                "similarity_score": 0.95,
                "booking_url": "https://www.viator.com/search?text=Tour+Tokyo",
            }
        ]
        data = {"results": activities}
        mock_resolver = AsyncMock()
        mock_resolver.resolve = AsyncMock(return_value=None)

        await resolve_top(mock_resolver, data, "Tokyo")

        mock_resolver.resolve.assert_not_called()


# ── Integration: enrich() on ActivitiesAgent ─────────────────────────────────


class TestActivitiesAgentEnrich:
    @pytest.mark.asyncio
    async def test_enrich_pops_destination_metadata(self):
        """_destination key must be removed from data before enrich() returns."""
        gyg_url = "https://www.getyourguide.com/tokyo-l193/tour-t789"
        data = {
            "results": _make_activities([("Tsukiji Outer Market Food Tour", 0.9)]),
            "_destination": "Tokyo",
        }

        with (
            patch("app.agents.activities_agent.settings") as mock_settings,
            patch("app.services.activity_url_resolver._get_client") as mock_gc,
        ):
            mock_settings.serper_key = "test-key"
            mock_settings.serpapi_key = ""

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                return_value=httpx.Response(200, json=_make_serper_response([gyg_url]))
            )
            mock_gc.return_value = mock_client

            from app.agents.activities_agent import ActivitiesAgent

            agent = ActivitiesAgent.__new__(ActivitiesAgent)
            result = await agent.enrich(data)

        assert "_destination" not in result
        assert result["results"][0]["booking_url"] == gyg_url
