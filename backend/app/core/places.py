"""Place-name reference data shared by the airports DB and the static tables."""

import unicodedata

# US state code → state name
_US_STATES = {
    "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas",
    "ca": "california", "co": "colorado", "ct": "connecticut", "de": "delaware",
    "dc": "district of columbia", "fl": "florida", "ga": "georgia",
    "hi": "hawaii", "id": "idaho", "il": "illinois", "in": "indiana",
    "ia": "iowa", "ks": "kansas", "ky": "kentucky", "la": "louisiana",
    "me": "maine", "md": "maryland", "ma": "massachusetts", "mi": "michigan",
    "mn": "minnesota", "ms": "mississippi", "mo": "missouri", "mt": "montana",
    "ne": "nebraska", "nv": "nevada", "nh": "new hampshire", "nj": "new jersey",
    "nm": "new mexico", "ny": "new york", "nc": "north carolina",
    "nd": "north dakota", "oh": "ohio", "ok": "oklahoma", "or": "oregon",
    "pa": "pennsylvania", "ri": "rhode island", "sc": "south carolina",
    "sd": "south dakota", "tn": "tennessee", "tx": "texas", "ut": "utah",
    "vt": "vermont", "va": "virginia", "wa": "washington",
    "wv": "west virginia", "wi": "wisconsin", "wy": "wyoming",
}  # fmt: skip

_CANADIAN_PROVINCES = "ab bc mb nb nl ns nt nu on pe qc sk yt".split()
_AUSTRALIAN_STATES = "wa sa nt nsw vic qld tas act".split()
_BRAZILIAN_STATES = (
    "ac al ap am ba ce df es go ma mt ms mg pa pb pr pe pi rj rn rs ro rr sc sp se to"
).split()


def _region_codes() -> dict[str, frozenset[str]]:
    table: dict[str, set[str]] = {}
    for country, codes in (
        ("US", _US_STATES),
        ("CA", _CANADIAN_PROVINCES),
        ("AU", _AUSTRALIAN_STATES),
        ("BR", _BRAZILIAN_STATES),
    ):
        for code in codes:
            table.setdefault(code, set()).add(country)
    return {code: frozenset(countries) for code, countries in table.items()}


# Region code (lowercase) → ISO alpha-2 codes of every country that uses it:
# US states, Canadian provinces/territories, Australian states/territories and
# Brazilian states. "wa" → {"US", "AU"}: Washington or Western Australia.
_REGION_CODES: dict[str, frozenset[str]] = _region_codes()


# Letters NFKD does not decompose into a base letter + combining mark.
_TRANSLITERATE = str.maketrans(
    {"ß": "ss", "ø": "o", "æ": "ae", "œ": "oe", "ł": "l", "đ": "d", "ı": "i",
     "þ": "th", "ð": "d"}
)  # fmt: skip


def fold_place(text: str) -> str:
    """Accent-free, lower-case, single-spaced form of a place name for
    matching: "  São Paulo" → "sao paulo", "Straße" → "strasse"."""
    lowered = (text or "").lower().translate(_TRANSLITERATE)
    decomposed = unicodedata.normalize("NFKD", lowered)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.split())


# Other spellings of a city (folded) → the city's name in the airports seed.
CITY_ALIASES: dict[str, str] = {
    "washington": "Washington D.C.",
    "washington dc": "Washington D.C.",
    "washington d c": "Washington D.C.",
    "washington d.c.": "Washington D.C.",
    "washington d.c": "Washington D.C.",
    "dc": "Washington D.C.",
    "saint petersburg": "St. Petersburg",
    "st petersburg": "St. Petersburg",
    "new york city": "New York",
    "nyc": "New York",
    "saigon": "Ho Chi Minh City",
    "bombay": "Mumbai",
}
