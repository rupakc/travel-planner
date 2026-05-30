import logging

from ..schemas.request import TravelSearchRequest
from .base_agent import BaseAgent
from .loader import load_agent_definition
from .web_tools import execute_tool

logger = logging.getLogger(__name__)


class ContentImportAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "content_import"))

    async def run_from_url(self, url: str) -> dict:
        """Fetch a travel content URL and extract structured trip planning data."""
        logger.info(f"ContentImportAgent: fetching {url}")
        page_content = await execute_tool("web_fetch", {"url": url})

        if page_content.startswith("Fetch error:") or page_content.startswith("Error:"):
            logger.warning(
                f"ContentImportAgent: fetch failed for {url}: {page_content}"
            )
            return {
                "error": "Could not extract travel content from the provided URL",
                "source_url": url,
            }

        prompt = (
            f"Source URL: {url}\n\n"
            f"Page content:\n{page_content}\n\n"
            "Extract all travel planning information from the content above and return "
            "structured JSON following the schema in your instructions."
        )
        result = await self.execute(prompt)

        # Always ensure source_url is present in the response
        if "source_url" not in result:
            result["source_url"] = url

        return result

    async def run(self, request: TravelSearchRequest) -> dict:
        """Standard run interface — not applicable for this agent."""
        return {"error": "Use run_from_url() for this agent"}
