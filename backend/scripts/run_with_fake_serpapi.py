"""Run the backend against a fake SerpAPI (see ``scripts/fake_serpapi.py``).

    python -m scripts.fake_serpapi --port 8765 &
    SERPAPI_KEY=fake FAKE_SERPAPI_URL=http://127.0.0.1:8765/search.json \
        python -m scripts.run_with_fake_serpapi --port 8001

Patches ``serp_flights.SERP_URL``, ``serp_flights._SERP_URL``,
``hotel_prices.SERP_URL``, ``activity_prices.SERP_URL`` and
``activity_url_resolver._SERPAPI_URL`` before importing
``app.main``, then starts uvicorn. The key is a dummy; the real SerpAPI is
never contacted.
"""

import argparse
import os

import uvicorn

from app.services import (
    activity_prices,
    activity_url_resolver,
    hotel_prices,
    serp_flights,
)


def patch(url: str) -> None:
    serp_flights.SERP_URL = url
    serp_flights._SERP_URL = url
    hotel_prices.SERP_URL = url
    activity_prices.SERP_URL = url
    activity_url_resolver._SERPAPI_URL = url


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    patch(os.environ.get("FAKE_SERPAPI_URL", "http://127.0.0.1:8765/search.json"))
    from app.main import app  # imported after the patch

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
