"""Real web search and fetch tools for agents that need live URLs."""

import asyncio
import logging
import time
import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS

logger = logging.getLogger(__name__)

_SEARCH_TIMEOUT = 8
_FETCH_TIMEOUT = 8
_MAX_SEARCH_RESULTS = 8
_MAX_CONCURRENT_SEARCHES = 4
_MIN_SEARCH_INTERVAL = 0.3

_search_semaphore: asyncio.Semaphore | None = None
_last_search_time = 0.0

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
}


def _get_semaphore() -> asyncio.Semaphore:
    global _search_semaphore
    if _search_semaphore is None:
        _search_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_SEARCHES)
    return _search_semaphore


TOOL_DEFINITIONS = [
    {
        "name": "web_search",
        "description": (
            "Search the web using DuckDuckGo. Returns a list of results with title, "
            "url, and snippet. Use this to find real booking URLs on platforms like "
            "booking.com, expedia.com, getyourguide.com, tripadvisor.com, klook.com, viator.com, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query string",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_fetch",
        "description": (
            "Fetch a web page and return its text content (HTML stripped). "
            "Use this to extract details from a specific URL found via web_search."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch",
                },
            },
            "required": ["url"],
        },
    },
]


async def execute_tool(name: str, input_data: dict) -> str:
    """Execute a tool and return string result."""
    if name == "web_search":
        return await _web_search(input_data.get("query", ""))
    elif name == "web_fetch":
        return await _web_fetch(input_data.get("url", ""))
    return f"Unknown tool: {name}"


def _ddgs_search(query: str, max_results: int) -> list:
    """Blocking DuckDuckGo search — each call gets its own DDGS instance."""
    return list(DDGS().text(query, max_results=max_results))


async def _web_search(query: str) -> str:
    """Run DuckDuckGo search with global rate limiting and retry."""
    if not query:
        return "Error: empty query"

    sem = _get_semaphore()
    max_retries = 2

    for attempt in range(1, max_retries + 1):
        async with sem:
            global _last_search_time
            now = time.monotonic()
            wait = _MIN_SEARCH_INTERVAL - (now - _last_search_time)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_search_time = time.monotonic()

            try:
                results = await asyncio.get_event_loop().run_in_executor(
                    None, _ddgs_search, query, _MAX_SEARCH_RESULTS
                )
                if not results:
                    return "No results found."
                lines = []
                for r in results:
                    lines.append(f"Title: {r.get('title', '')}")
                    lines.append(f"URL: {r.get('href', '')}")
                    lines.append(f"Snippet: {r.get('body', '')}")
                    lines.append("")
                return "\n".join(lines)
            except Exception as e:
                logger.warning(
                    f"Web search attempt {attempt}/{max_retries} failed for '{query[:80]}': {e}"
                )
                if attempt < max_retries:
                    await asyncio.sleep(1.5)
                    continue
                return f"Search error: {e}"

    return "Search error: exhausted retries"


async def _web_fetch(url: str) -> str:
    """Fetch a URL and return text content (max 4000 chars)."""
    if not url:
        return "Error: empty URL"
    try:
        async with httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT, follow_redirects=True, headers=_HEADERS
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            return text[:4000]
    except Exception as e:
        logger.warning(f"Web fetch failed for '{url}': {e}")
        return f"Fetch error: {e}"
