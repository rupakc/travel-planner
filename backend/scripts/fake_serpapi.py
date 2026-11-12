"""A local fake SerpAPI for tests, dev and E2E (never the real service).

    python -m scripts.fake_serpapi --port 8765 [--drop-after N]

Serves ``/search.json`` (and ``/search``) from ``tests/fixtures/serpapi/``,
routed by the ``engine`` query parameter:

- ``google_flights``: ``flights/return_leg.json`` when ``departure_token`` is
  given, else ``flights/outbound.json``
- ``google_hotels``: ``hotels/property_details_browns.json`` when
  ``property_token`` is given, else ``hotels/city_search_lisbon.json``
- ``google``: ``activities/gyg_belem_tower_recheck.json``

``GET /__calls`` returns ``{"total": n, "by_engine": {...}}``. The API key is
never read, stored or logged. With ``--drop-after N`` every search after the
first N serves prices 12 % lower (numeric ``price``/``lowest_price``/
``extracted_*`` fields, ``$`` strings and the flight price history), so an
end-to-end run sees a real drop.
"""

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "serpapi"
DROP_FACTOR = 0.88

_ROUTES = {
    "google_flights": (
        "flights",
        "outbound.json",
        "departure_token",
        "return_leg.json",
    ),
    "google_hotels": (
        "hotels",
        "city_search_lisbon.json",
        "property_token",
        "property_details_browns.json",
    ),
    "google": ("activities", "gyg_belem_tower_recheck.json", None, None),
}
_PRICE_KEYS = {"price", "lowest_price"}
_STR_PRICE_KEYS = {
    "price",
    "lowest",
    "display_price",
    "before_taxes_fees",
    "after_taxes_fees",
}
_DOLLARS = re.compile(r"\$(\d+(?:,\d{3})*(?:\.\d+)?)")


def _scale_str(text: str, factor: float) -> str:
    def sub(m: re.Match) -> str:
        v = float(m.group(1).replace(",", "")) * factor
        return "$" + f"{round(v):,}"

    return _DOLLARS.sub(sub, text)


def scale_prices(obj, factor: float, key: str = ""):
    """A copy of ``obj`` with every price field multiplied by ``factor``."""
    if isinstance(obj, dict):
        return {k: scale_prices(v, factor, k) for k, v in obj.items()}
    if isinstance(obj, list):
        if key == "price_history":
            return [
                [p[0], round(p[1] * factor)]
                if isinstance(p, list) and len(p) == 2
                else p
                for p in obj
            ]
        return [scale_prices(v, factor, key) for v in obj]
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)) and (
        key in _PRICE_KEYS or key.startswith("extracted_")
    ):
        return round(obj * factor)
    if isinstance(obj, str) and (key in _STR_PRICE_KEYS or key in ("snippet", "title")):
        return _scale_str(obj, factor)
    return obj


class FakeSerpAPI:
    """State shared by the handler: fixtures, call counter, drop mode."""

    def __init__(self, drop_after: int | None = None, fixtures: Path = FIXTURES):
        self.drop_after = drop_after
        self.fixtures = fixtures
        self.lock = threading.Lock()
        self.total = 0
        self.by_engine: dict[str, int] = {}

    def calls(self) -> dict:
        with self.lock:
            return {"total": self.total, "by_engine": dict(self.by_engine)}

    def answer(self, params: dict[str, str]) -> tuple[int, dict]:
        engine = params.get("engine", "")
        route = _ROUTES.get(engine)
        if route is None:
            return 400, {"error": f"unsupported engine {engine!r}"}
        folder, default, token_key, token_file = route
        name = token_file if token_key and params.get(token_key) else default
        with self.lock:
            self.total += 1
            self.by_engine[engine] = self.by_engine.get(engine, 0) + 1
            n = self.total
        data = json.loads((self.fixtures / folder / name).read_text())
        if self.drop_after is not None and n > self.drop_after:
            data = scale_prices(data, DROP_FACTOR)
        return 200, data


def make_handler(state: FakeSerpAPI):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: dict) -> None:
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path == "/__calls":
                return self._send(200, state.calls())
            if url.path in ("/search.json", "/search"):
                params = {k: v[0] for k, v in parse_qs(url.query).items()}
                status, body = state.answer(params)
                return self._send(status, body)
            self._send(404, {"error": "not found"})

        def log_message(self, *args):  # never log the query (it has the key)
            return

    return Handler


def make_server(port: int = 0, drop_after: int | None = None, host: str = "127.0.0.1"):
    """Build (not start) a server; ``server.state`` is the FakeSerpAPI."""
    state = FakeSerpAPI(drop_after)
    server = ThreadingHTTPServer((host, port), make_handler(state))
    server.state = state  # type: ignore[attr-defined]
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--drop-after", type=int, default=None)
    args = ap.parse_args()
    server = make_server(args.port, args.drop_after)
    print(f"fake SerpAPI on http://127.0.0.1:{args.port}/search.json", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
