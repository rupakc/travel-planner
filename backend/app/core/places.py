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


# Full region names (accent-folded) → (region code, ISO country). US states
# come from _US_STATES; "victoria" here is the Australian state.
_REGION_NAMES: dict[str, tuple[str, str]] = {
    **{name: (code, "US") for code, name in _US_STATES.items()},
    "alberta": ("ab", "CA"), "british columbia": ("bc", "CA"),
    "manitoba": ("mb", "CA"), "new brunswick": ("nb", "CA"),
    "newfoundland and labrador": ("nl", "CA"), "nova scotia": ("ns", "CA"),
    "northwest territories": ("nt", "CA"), "nunavut": ("nu", "CA"),
    "ontario": ("on", "CA"), "prince edward island": ("pe", "CA"),
    "quebec": ("qc", "CA"), "saskatchewan": ("sk", "CA"), "yukon": ("yt", "CA"),
    "new south wales": ("nsw", "AU"), "victoria": ("vic", "AU"),
    "queensland": ("qld", "AU"), "western australia": ("wa", "AU"),
    "south australia": ("sa", "AU"), "tasmania": ("tas", "AU"),
    "northern territory": ("nt", "AU"),
    "australian capital territory": ("act", "AU"),
    "acre": ("ac", "BR"), "alagoas": ("al", "BR"), "amapa": ("ap", "BR"),
    "amazonas": ("am", "BR"), "bahia": ("ba", "BR"), "ceara": ("ce", "BR"),
    "distrito federal": ("df", "BR"), "espirito santo": ("es", "BR"),
    "goias": ("go", "BR"), "maranhao": ("ma", "BR"), "mato grosso": ("mt", "BR"),
    "mato grosso do sul": ("ms", "BR"), "minas gerais": ("mg", "BR"),
    "para": ("pa", "BR"), "paraiba": ("pb", "BR"), "parana": ("pr", "BR"),
    "pernambuco": ("pe", "BR"), "piaui": ("pi", "BR"),
    "rio de janeiro": ("rj", "BR"), "rio grande do norte": ("rn", "BR"),
    "rio grande do sul": ("rs", "BR"), "rondonia": ("ro", "BR"),
    "roraima": ("rr", "BR"), "santa catarina": ("sc", "BR"),
    "sao paulo": ("sp", "BR"), "sergipe": ("se", "BR"), "tocantins": ("to", "BR"),
}  # fmt: skip


def stated_region(stated: str) -> tuple[str, frozenset[str]] | None:
    """The region a folded last segment names, as (region code, ISO codes of
    the countries it can be in): "wa" → ("wa", {US, AU}), "western australia"
    → ("wa", {AU}), "washington" → ("wa", {US}). None for anything else."""
    if stated in _REGION_CODES:
        return stated, _REGION_CODES[stated]
    if stated in _REGION_NAMES:
        code, country = _REGION_NAMES[stated]
        return code, frozenset({country})
    return None


# Region code (lowercase) → ISO alpha-2 codes of every country that uses it:
# US states, Canadian provinces/territories, Australian states/territories and
# Brazilian states. "wa" → {"US", "AU"}: Washington or Western Australia.
_REGION_CODES: dict[str, frozenset[str]] = _region_codes()


# Letters NFKD does not decompose into a base letter + combining mark, word
# separators ("St. Louis", "Winston-Salem", "Sant·Joan") and apostrophe and
# quote variants, which are dropped ("Xi’an" → "xian").
_TRANSLITERATE = str.maketrans(
    {"ß": "ss", "ø": "o", "æ": "ae", "œ": "oe", "ł": "l", "đ": "d", "ı": "i",
     "þ": "th", "ð": "d", "ə": "e", "ɛ": "e", "ħ": "h", "ƶ": "z",
     ".": " ", "·": " ",
     "'": None, "’": None, "‘": None, "ʼ": None, "ʻ": None, "`": None,
     "ʹ": None, "“": None, "”": None}
)  # fmt: skip


def _fold_char(ch: str) -> str:
    """Drop combining marks and invisible format characters (ZWNJ, LRM);
    every dash (hyphen, en/em dash, …) separates words."""
    if unicodedata.combining(ch):
        return ""
    category = unicodedata.category(ch)
    if category == "Cf":
        return ""
    if category == "Pd":
        return " "
    return ch


def fold_place(text: str) -> str:
    """Accent-free, lower-case, single-spaced form of a place name for
    matching: "  São Paulo" → "sao paulo", "Straße" → "strasse",
    "St. Louis" → "st louis", "Winston-Salem" → "winston salem",
    "St. John's" → "st johns". The runtime lookups and the offline data
    generator share this one definition."""
    lowered = (text or "").lower().translate(_TRANSLITERATE)
    decomposed = unicodedata.normalize("NFKD", lowered)
    return " ".join("".join(map(_fold_char, decomposed)).split())


_SAINT_PREFIXES = ("st ", "st. ", "saint ")


def saint_variants(folded: str) -> set[str]:
    """A folded city name plus its other St / St. / Saint spellings
    ("st louis" → {"st louis", "st. louis", "saint louis"})."""
    for prefix in _SAINT_PREFIXES:
        if folded.startswith(prefix):
            rest = folded[len(prefix) :]
            return {p + rest for p in _SAINT_PREFIXES}
    return {folded}


# Other spellings of a city (folded) → the city's name in the airports seed.
CITY_ALIASES: dict[str, str] = {
    "washington": "Washington D.C.",
    "washington dc": "Washington D.C.",
    "washington d c": "Washington D.C.",
    "washington d.c.": "Washington D.C.",
    "washington d.c": "Washington D.C.",
    "dc": "Washington D.C.",
    "new york city": "New York",
    "nyc": "New York",
    "saigon": "Ho Chi Minh City",
    "bombay": "Mumbai",
}
