"""Live check ("Search the web now"): one user-initiated Gemini call with
Google Search grounding for one of the user's watches.

The prompt is built here from the stored watch (never free text from the
client); the answer, its sources and the searches it ran go back to that
user once. Google's Search grounding terms forbid storing, caching or
analysing grounded results and running them without a user's prompt, so
nothing here is persisted, cached, compared with a baseline or fed to
alerts — watches and alerts stay on SerpAPI (docs/Trip-Planning-Features.md,
"Live web check and Near me").

Pure helpers (no network): prompt building and quote parsing.
"""

import re
from datetime import date

KINDS = ("flight", "hotel", "activity", "trip")
DISCLAIMER = (
    "From a live web search just now. Prices change quickly — check the "
    "provider before booking. Not used for your price alerts."
)

_FIELD_CAP = 120
_MAX_TRIP_PARTS = 8
_MAX_QUOTES = 10

SYSTEM = (
    "Today is {today}. You check current travel prices on the web for the "
    "user who asked. Use Google Search. Quote only prices you found in the "
    "search results, copied exactly with their currency; never estimate or "
    "invent a price. If you find no current price, say so."
)
_FORMAT = (
    "\n\nAnswer in plain text: first two or three sentences summarising what "
    "you found, then up to 6 bullet lines, one per price you found, each "
    "exactly in this form:\n- <website or seller>, <what the price covers>: "
    "<ISO currency code> <amount>\nUse digits for the amount with a dot for "
    "decimals, for example: - Booking.com, 3 nights for 2 adults: EUR 412.00"
)


def _f(value, cap: int = _FIELD_CAP) -> str:
    """One line of stored text for the prompt: no newlines / pipes, capped."""
    text = " ".join(str(value or "").replace("|", " ").split())
    return text[:cap]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _int(value, default: int = 1) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if n > 0 else default


def _nights(start, end) -> int | None:
    try:
        n = (date.fromisoformat(str(end)) - date.fromisoformat(str(start))).days
    except ValueError:
        return None
    return n if n > 0 else None


def _flight(watch: dict) -> str:
    route = (
        f"{_f(watch.get('origin_label'))} ({_f(watch.get('origin_code'), 4)}) to "
        f"{_f(watch.get('destination_label'))} "
        f"({_f(watch.get('destination_code'), 4)})"
    )
    ret = watch.get("return_date")
    when = (
        f"round trip departing {_f(watch.get('departure_date'), 10)}, returning "
        f"{_f(ret, 10)}"
        if ret
        else f"one-way on {_f(watch.get('departure_date'), 10)}"
    )
    n = _int(watch.get("num_travelers"))
    cabin = _f(watch.get("cabin") or "economy", 20)
    return (
        f"What are the current {cabin} fares for flights from {route}, {when}, "
        f"for {_plural(n, 'traveller')}? Give total prices for all travellers "
        "where the sites show them."
    )


def _hotel(watch: dict) -> str:
    s = watch.get("subject") or {}
    ci, co = _f(s.get("check_in"), 10), _f(s.get("check_out"), 10)
    nights = _nights(ci, co)
    stay = f"{_plural(nights, 'night')}, " if nights else ""
    return (
        f"What does the hotel {_f(s.get('name') or watch.get('title'))} in "
        f"{_f(s.get('city'))} cost right now for check-in {ci} and check-out "
        f"{co} ({stay}{_plural(_int(s.get('adults')), 'adult')}, "
        f"{_plural(_int(s.get('rooms')), 'room')})? Give the total for the "
        "stay where the sites show it."
    )


def _activity(watch: dict) -> str:
    s = watch.get("subject") or {}
    name = s.get("listing_title") or s.get("name") or watch.get("title")
    when = f" on {_f(s.get('date'), 10)}" if s.get("date") else ""
    currency = _f(s.get("currency") or watch.get("currency") or "", 3)
    n = _int(s.get("travellers"))
    people = "1 person" if n == 1 else f"{n} people"
    return (
        f"What does the activity {_f(name)} in {_f(s.get('city'))} cost right "
        f"now{when} for {people} on GetYourGuide, Viator or the operator's own "
        "site?" + (f" Prices in {currency} if available." if currency else "")
    )


def _trip(watch: dict) -> str:
    s = watch.get("subject") or {}
    dep, ret = _f(s.get("departure_date"), 10), _f(s.get("return_date"), 10)
    n = _int(s.get("travellers"))
    city = _f(s.get("city")) or "the destination"
    parts = []
    for comp in (s.get("components") or [])[:_MAX_TRIP_PARTS]:
        if not isinstance(comp, dict):
            continue
        kind, label = comp.get("type"), _f(comp.get("label"))
        if kind == "flight":
            fare = comp.get("subject") or {}
            if fare.get("origin_label") and fare.get("destination_label"):
                parts.append(
                    f"flights from {_f(fare['origin_label'])} to "
                    f"{_f(fare['destination_label'])}"
                )
            else:
                parts.append(f"flights to {city}")
        elif kind == "hotel" and label:
            parts.append(f"the hotel {label}")
        elif kind == "activity" and label:
            parts.append(f"the activity {label}")
    wanted = "; ".join(parts) or f"flights and a hotel in {city}"
    return (
        f"For a trip to {city} from {dep} to {ret} for "
        f"{_plural(n, 'traveller')}, what do these cost right now: {wanted}? "
        "Give a price for each part you can find."
    )


def expired(kind: str, watch: dict, today: date) -> bool:
    """True for a watch marked expired, or whose date (departure for a
    fare watch, ``expires_on`` — check-in / activity date / departure — for
    a price watch) is before ``today``: nothing left to price."""
    if watch.get("status") == "expired":
        return True
    raw = watch.get("departure_date" if kind == "flight" else "expires_on")
    try:
        return date.fromisoformat(str(raw)[:10]) < today
    except ValueError:
        return False


_BUILDERS = {"flight": _flight, "hotel": _hotel, "activity": _activity, "trip": _trip}


def build_prompt(kind: str, watch: dict, *, today: str) -> tuple[str, str]:
    """(system, prompt) for a watch row (fare_watches for ``flight``,
    price_watches otherwise)."""
    return SYSTEM.format(today=today), _BUILDERS[kind](watch) + _FORMAT


# ── Sources and quotes ────────────────────────────────────────────────────────


def sources_from(chunks: list[dict]) -> tuple[list[dict], dict[int, int]]:
    """(sources, chunk index → source index): web chunks with a link, once
    per link. Links are Google's grounding redirects: used as returned."""
    sources: list[dict] = []
    index: dict[int, int] = {}
    by_uri: dict[str, int] = {}
    for i, c in enumerate(chunks):
        uri = c.get("uri")
        if c.get("kind") != "web" or not isinstance(uri, str):
            continue
        if not uri.startswith(("https://", "http://")):
            continue
        if uri not in by_uri:
            by_uri[uri] = len(sources)
            sources.append({"title": c.get("title") or uri, "uri": uri})
        index[i] = by_uri[uri]
    return sources, index


_BULLET = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+(?P<rest>.+)$")
# ISO 4217 codes we accept: three capitals alone ("TAP", "NYC") are not money
CURRENCIES = frozenset(
    "USD EUR GBP CHF JPY CNY HKD TWD KRW SGD MYR THB IDR PHP VND INR LKR NPR "
    "PKR BDT AUD NZD CAD MXN BRL ARS CLP COP PEN UYU SEK NOK DKK ISK PLN CZK "
    "HUF RON BGN TRY ILS AED SAR QAR KWD BHD OMR JOD EGP MAD TND ZAR KES NGN "
    "GHS TZS UGX MUR".split()
)
# Only unambiguous symbols ("$" and "¥" could be several currencies)
_SYMBOLS = {
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
    "US$": "USD",
    "C$": "CAD",
    "CA$": "CAD",
    "A$": "AUD",
    "AU$": "AUD",
    "NZ$": "NZD",
    "S$": "SGD",
    "HK$": "HKD",
}
_SYMBOL_RE = "|".join(re.escape(s) for s in sorted(_SYMBOLS, key=len, reverse=True))
# 1,234.56 (comma thousands, dot decimals) or 1234.5; never touching other
# digits or separators, and not followed by a space-separated thousands
# group ("1 234", also with no-break spaces): "1.234,56" / "412,50" /
# "1 234" match nothing rather than a wrong number
_AMOUNT = (
    r"(?<![\d.,])(?P<{n}>\d{{1,3}}(?:,\d{{3}})+(?:\.\d{{1,2}})?|\d+(?:\.\d{{1,2}})?)"
    r"(?![.,]?\d)(?![\s  ]\d{{3}}(?!\d))"
)
_PRICE = re.compile(
    rf"(?:(?<![A-Za-z])(?P<pre>[A-Z]{{3}}|{_SYMBOL_RE})\s?{_AMOUNT.format(n='amt')})"
    rf"|(?:{_AMOUNT.format(n='amt2')}\s?(?P<post>[A-Z]{{3}})\b(?!\s?\d))"
)


def _price(text: str) -> tuple[float, str, int, int] | None:
    """(amount, ISO code, start, end) of the first price in ``text`` with a
    known currency: ``EUR 412``, ``412.50 EUR``, ``€98``, ``US$1,045``.
    Ambiguous amounts (comma decimals, space or dot thousands) and
    three-letter words that aren't currencies are skipped, never guessed."""
    for m in _PRICE.finditer(text):
        if m["pre"]:
            code, raw = _SYMBOLS.get(m["pre"], m["pre"]), m["amt"]
        else:
            code, raw = m["post"], m["amt2"]
        if code not in CURRENCIES:
            continue
        amount = float(raw.replace(",", ""))
        if 0 < amount < 10_000_000:
            return amount, code, m.start(), m.end()
    return None


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[*_`]+", "", text or "").split())


_MIN_SEGMENT = 12


def _cited(
    token: tuple[int, int],
    token_text: str,
    line: str,
    supports: list[dict],
    index: dict[int, int],
) -> int | None:
    """The source a grounding support gives this price. With byte offsets
    (Vertex omits ``start`` when it is 0), the segment must cover the price
    token's bytes; without them, its text must be part of the line, contain
    the price and be at least 12 characters. A segment like "EUR" or "3"
    never cites."""
    norm_line, norm_token = _norm(line), _norm(token_text)
    for s in supports:
        start, end = s.get("start"), s.get("end")
        if isinstance(end, int):
            start = start if isinstance(start, int) else 0
            covers = start <= token[0] and end >= token[1]
        else:
            seg = _norm(s.get("text") or "")
            covers = len(seg) >= _MIN_SEGMENT and norm_token in seg and seg in norm_line
        if not covers:
            continue
        for chunk in s.get("chunks") or []:
            if chunk in index:
                return index[chunk]
    return None


def _quote_line(rest: str) -> tuple[str, tuple[float, str, int, int]] | None:
    """(label, price) of a bullet's text ``Seller, what: EUR 412``: the
    first price after the first ": ", labelled by everything before the
    last ": " ahead of it ("Flight: TAP, 1 stop: USD 512")."""
    first = rest.find(": ")
    if first <= 0:
        return None
    price = _price(rest[first + 2 :])
    if price is None:
        return None
    at = first + 2 + price[2]
    label = _norm(rest[: rest.rfind(": ", 0, at)])
    if not label:
        return None
    return label, (price[0], price[1], at, first + 2 + price[3])


def parse_quotes(text: str, supports: list[dict], index: dict[int, int]) -> list[dict]:
    """Prices from the answer's bullet lines (``- Seller, what: EUR 412``),
    each with the index of the source a grounding support cites for that
    price. A line without a parseable price or a citing source is left out:
    amounts are copied from the grounded text, never inferred. Offsets are
    UTF-8 bytes, as Vertex reports them."""
    quotes: list[dict] = []
    offset = 0
    for line in (text or "").splitlines(keepends=True):
        line_start = offset
        offset += len(line.encode())
        body = line.rstrip("\r\n")
        m = _BULLET.match(body)
        if not m:
            continue
        parsed = _quote_line(m["rest"])
        if parsed is None:
            continue
        label, (amount, code, a, b) = parsed
        rest_at = m.start("rest")
        tok_start = line_start + len(body[: rest_at + a].encode())
        tok_end = line_start + len(body[: rest_at + b].encode())
        token_text = m["rest"][a:b]
        source = _cited((tok_start, tok_end), token_text, body, supports, index)
        if source is None:
            continue
        quotes.append(
            {
                "label": label[:_FIELD_CAP],
                "amount": amount,
                "currency": code,
                "source_index": source,
            }
        )
        if len(quotes) >= _MAX_QUOTES:
            break
    return quotes
