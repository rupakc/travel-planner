import asyncio
import json
import logging
import re

import anthropic

from .loader import AgentDefinition

logger = logging.getLogger(__name__)

_MAX_RETRIES = 4
_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 8192
_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        from ..core.config import settings

        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


class BaseAgent:
    def __init__(self, definition: AgentDefinition):
        self.definition = definition

    async def execute(self, prompt: str) -> dict:
        """Execute agent via direct Anthropic API and return parsed JSON."""
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                client = _get_client()
                system = (
                    self.definition.system_prompt
                    + "\n\nReturn ONLY valid JSON. No prose, no tool calls, no markdown."
                )
                response = await client.messages.create(
                    model=_MODEL,
                    max_tokens=_MAX_TOKENS,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                result_text = response.content[0].text if response.content else ""
            except Exception as e:
                logger.warning(
                    f"Agent {self.definition.name} attempt {attempt}/{_MAX_RETRIES} "
                    f"failed: {e}"
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(0.5)
                    continue
                return {"error": str(e)}

            parsed = self._parse_json(result_text)
            if parsed:
                return parsed

            logger.warning(
                f"Agent {self.definition.name} attempt {attempt}/{_MAX_RETRIES} "
                f"returned empty/unparseable result: {result_text[:200]}"
            )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(0.5)
                continue

        return {
            "error": f"Agent returned no parseable result after {_MAX_RETRIES} attempts"
        }

    def _parse_json(self, text: str) -> dict:
        """Parse JSON from agent output with 3 fallback strategies."""
        if not text:
            return {}

        # Strategy 1: Direct parse
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract JSON code block
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Strategy 3: Find first {...} block
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning(
            f"Agent {self.definition.name} could not parse JSON from output: {text[:200]}"
        )
        return {}


class ToolAgent(BaseAgent):
    """Agent that generates results via Haiku, then can enrich URLs separately.

    execute() returns the fast Haiku result immediately.
    enrich() runs web searches for real URLs — called in the background by
    the orchestrator AFTER the initial result has been streamed.
    """

    async def enrich(self, data: dict) -> dict:
        """Run URL enrichment on already-returned data. Called by orchestrator."""
        if data.get("error"):
            return data
        return await self._enrich_urls(data)

    async def _enrich_urls(self, data: dict) -> dict:
        """Override in subclasses to search for real URLs."""
        return data


class _URLSearchMixin:
    """Shared logic for searching real URLs via web search."""

    _JUNK_DOMAINS = {
        "bing.com/aclick",
        "googleadservices.com",
        "ad.doubleclick.net",
        "wikipedia.org",
        "pinterest.com",
        "pinterest.co",
        "tiktok.com",
        "youtube.com",
        "youtu.be",
        "facebook.com",
        "instagram.com",
        "twitter.com",
        "x.com",
        "reddit.com",
        "quora.com",
        "medium.com",
        "amazon.com",
        "ebay.com",
    }

    @classmethod
    def _is_clean_url(cls, url: str) -> bool:
        if not url or not url.startswith("http"):
            return False
        if url.endswith(".pdf"):
            return False
        return not any(d in url for d in cls._JUNK_DOMAINS)

    _STOP_WORDS = frozenset(
        {
            "the",
            "and",
            "for",
            "tour",
            "tours",
            "with",
            "from",
            "hotel",
            "hotels",
            "book",
            "booking",
            "tickets",
            "city",
            "best",
            "top",
            "guide",
            "travel",
            "trip",
            "official",
            "site",
            "website",
            "new",
            "york",
            "los",
            "angeles",
            "san",
            "francisco",
            "airline",
            "airlines",
            "international",
            "airways",
            "air",
            "lines",
        }
    )

    @staticmethod
    async def _search_url(query: str, match_name: str = "") -> str | None:
        """Search and return the best matching URL.

        Matching uses word overlap on distinctive words (common/stop words
        filtered out). Requires >=50% of distinctive name words to appear
        in the result title, with a floor of 2 absolute matches.
        """
        from .web_tools import execute_tool

        result = await execute_tool("web_search", {"query": query})
        lines = result.split("\n")
        pairs = []
        i = 0
        while i < len(lines):
            title = url = ""
            if lines[i].startswith("Title: "):
                title = lines[i][7:].strip().lower()
            if i + 1 < len(lines) and lines[i + 1].startswith("URL: "):
                url = lines[i + 1][5:].strip()
            if title and _URLSearchMixin._is_clean_url(url):
                pairs.append((title, url))
            i += 1

        if not pairs:
            return None

        if not match_name:
            return pairs[0][1]

        import re

        clean = re.sub(r"[^a-zA-Z0-9\s]", " ", match_name).lower()
        all_words = {w for w in clean.split() if len(w) > 2}
        name_words = all_words - _URLSearchMixin._STOP_WORDS
        if not name_words:
            name_words = all_words

        # For short names (1-2 words), require all to match.
        # For longer names, require at least half.
        if len(name_words) <= 2:
            min_matches = len(name_words)
        else:
            min_matches = max(2, len(name_words) // 2)

        best_url = None
        best_score = 0
        for title, url in pairs:
            title_text = re.sub(r"[^a-zA-Z0-9\s]", " ", title).lower()
            title_words = {w for w in title_text.split() if len(w) > 2}
            score = len(name_words & title_words)
            if score > best_score:
                best_score = score
                best_url = url

        if best_url and best_score >= min_matches:
            return best_url

        # Fallback: check URL path for distinctive name words
        for title, url in pairs:
            url_path = re.sub(r"[^a-zA-Z0-9\s]", " ", url).lower()
            path_words = {w for w in url_path.split() if len(w) > 2}
            path_score = len(name_words & path_words)
            if path_score >= min_matches:
                return url

        # No good match found — return None so caller can try alternatives
        return None

    @staticmethod
    async def _batch_search(query: str) -> list[tuple[str, str]]:
        """Run a single search and return list of (title, url) pairs."""
        from .web_tools import execute_tool

        result = await execute_tool("web_search", {"query": query})
        pairs = []
        lines = result.split("\n")
        i = 0
        while i < len(lines):
            title = url = ""
            if lines[i].startswith("Title: "):
                title = lines[i][7:].strip().lower()
            if i + 1 < len(lines) and lines[i + 1].startswith("URL: "):
                url = lines[i + 1][5:].strip()
            if title and _URLSearchMixin._is_clean_url(url):
                pairs.append((title, url))
            i += 1
        return pairs
