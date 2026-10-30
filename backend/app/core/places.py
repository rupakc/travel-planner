"""Place-name reference data shared by the airports DB and the static tables."""

import json
import re
import unicodedata
from pathlib import Path

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
# Indian states and union territories (ISO 3166-2:IN) → GeoNames admin1 name
_INDIAN_STATES = {
    "an": "andaman and nicobar", "ap": "andhra pradesh",
    "ar": "arunachal pradesh", "as": "assam", "br": "bihar", "ch": "chandigarh",
    "ct": "chhattisgarh", "cg": "chhattisgarh",
    "dh": "dadra and nagar haveli and daman and diu", "dl": "delhi",
    "ga": "goa", "gj": "gujarat", "hp": "himachal pradesh", "hr": "haryana",
    "jh": "jharkhand", "jk": "jammu and kashmir", "ka": "karnataka",
    "kl": "kerala", "la": "ladakh", "ld": "lakshadweep", "mh": "maharashtra",
    "ml": "meghalaya", "mn": "manipur", "mp": "madhya pradesh", "mz": "mizoram",
    "nl": "nagaland", "od": "odisha", "pb": "punjab", "py": "puducherry",
    "rj": "rajasthan", "sk": "sikkim", "tg": "telangana", "ts": "telangana",
    "tn": "tamil nadu", "tr": "tripura", "up": "uttar pradesh",
    "ut": "uttarakhand", "wb": "west bengal",
}  # fmt: skip
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
        ("IN", _INDIAN_STATES),
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
    **{name: (code, "IN") for code, name in _INDIAN_STATES.items()},
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


# ── Curated hints, aliases and exonyms: backend/app/db/data/hints.json ────
# (loaded once; folded keys; see its "_about" entry and the schema test).
_HINTS_FILE = Path(__file__).resolve().parents[1] / "db" / "data" / "hints.json"


def _load_hints() -> dict:
    with open(_HINTS_FILE, encoding="utf-8") as f:
        return json.load(f)


_HINTS = _load_hints()


def _airport_table(name: str) -> dict[str, tuple[str, tuple[str, ...]]]:
    return {k: (v[0], tuple(v[1])) for k, v in _HINTS[name].items()}


# Other spellings of a city (folded) → the city's name in the airports seed.
CITY_ALIASES: dict[str, str] = dict(_HINTS["city_aliases"])
# Other names people type for a country (folded) → ISO alpha-2 code: the one
# alias map for the airports DB and the static reference tables.
COUNTRY_ALIASES: dict[str, str] = dict(_HINTS["country_aliases"])
# Country abbreviations that are also scheduled airport codes (KSA Kosrae,
# PRC Prescott, ROK Rockhampton, ROC Rochester): a country only as a
# qualifier ("Riyadh, KSA", "Beijing PRC"); typed alone they stay codes.
QUALIFIER_COUNTRY_ALIASES: dict[str, str] = dict(_HINTS["qualifier_country_aliases"])
# Tourist islands and island groups → (ISO country, scheduled airports).
ISLAND_AIRPORTS = _airport_table("islands")
# Landmarks, parks, resorts and airportless countries → (country, airports).
DESTINATION_AIRPORTS = _airport_table("destinations")
# Regions that are not first-level divisions → (country, airports).
REGION_HINTS = _airport_table("regions")
# Exonyms whose own-name namesakes would win → GeoNames place id or
# "ambiguous" (each id is checked against the seeded data by a test).
EXONYMS: dict[str, int | str] = dict(_HINTS["exonyms"])
# Names whose St / Saint variants must not borrow a hint ("Saint John", New
# Brunswick, is not St John, USVI).
SAINT_EXCEPTIONS: frozenset[str] = frozenset(_HINTS["saint_exceptions"])


# ── Non-town features (islands, parks, mountains…): their short names ─────

# A feature's name without a generic part is a primary name too ("Kakadu
# National Park" → "kakadu", "Mount Everest" → "everest", "Isola
# Stromboli" → "stromboli", "Annapurna I" → "annapurna"), in English and
# the other languages GeoNames names features in. "Death Valley" and
# "Rocky Mountains" keep their whole names.
_FEATURE_PREFIXES = (
    "mount ", "mt ", "lake ", "ko ", "koh ", "isle of ", "pulau ",
    "isola ", "isla ", "ilha ", "ile ", "insel ", "gunung ", "mont ", "monte ",
    "monti ", "cerro ", "pico ", "pic ", "piz ", "lago ", "lac ", "laguna ",
    "parque nacional ", "parc national ", "nationalpark ", "national park ",
    "zona arqueologica ",
)  # fmt: skip
_FEATURE_SUFFIXES = (
    " national park",
    " national reserve",
    " game reserve",
    " nature reserve",
    " nationalpark",
    " islands",
    " island",
    " insel",
    " atoll",
    " peninsula",
    " peak",
    " see",
)
# "de", "del", "de la"… after a prefix ("Parc national de la Vanoise")
_CONNECTORS = ("de la ", "de los ", "de las ", "del ", "de ", "des ", "du ",
               "da ", "do ", "dos ", "di ", "della ", "dei ")  # fmt: skip
_ROMAN_SUFFIX_RE = re.compile(r" (i|ii|iii|iv|v)$")


def feature_short_names(folded: str) -> set[str]:
    """The folded feature name without a generic prefix (and a following
    "de", "di"…), a generic suffix or a trailing Roman numeral (empty when
    it has none, or nothing is left)."""
    short = set()
    for prefix in _FEATURE_PREFIXES:
        if folded.startswith(prefix):
            rest = folded[len(prefix) :]
            for connector in _CONNECTORS:
                if rest.startswith(connector):
                    rest = rest[len(connector) :]
                    break
            if rest.strip():
                short.add(rest)
    for suffix in _FEATURE_SUFFIXES:
        if folded.endswith(suffix) and folded[: -len(suffix)].strip():
            short.add(folded[: -len(suffix)])
    roman = _ROMAN_SUFFIX_RE.sub("", folded)
    if roman != folded and roman.strip():
        short.add(roman)
    return short


# ── Airports a place owns (shared by the data generator and the runtime) ──

# Words an airport name adds to the place it names ("La Palma Airport"): the
# one list for the generator's name-derived display and runtime name matches.
AIRPORT_NAME_WORDS = frozenset(
    {"airport", "international", "regional", "aerodrome", "airfield"}
)

# Words that alone never identify a place inside an airport name.
GENERIC_PLACE_WORDS = frozenset(
    "airport international regional national municipal domestic airfield "
    "aerodrome field airstrip airpark county city town de del la le el al "
    "san santa saint st new port north south east west central island lake "
    "river airbase air base".split()
)
_NON_WORD_RE = re.compile(r"[^\w ]")

# A same-country airport this close is the place's own, whatever its name.
OWN_AIRPORT_KM = 25

# Airports never linked to places: reachable only via a third country
# (Ercan, northern Cyprus: flights only via Turkey).
NEVER_LINK: frozenset[str] = frozenset({"ECN"})


def words_in(folded_name: str, folded_text: str) -> bool:
    """The folded name occurs as whole words in the folded text, and is not
    made only of generic airport/geography words."""
    if not folded_name or set(folded_name.split()) <= GENERIC_PLACE_WORDS:
        return False
    words = " ".join(_NON_WORD_RE.sub(" ", folded_text).split())
    return f" {folded_name} " in f" {words} "


def is_named_airport(place: str, airport_city: str, airport_name: str) -> bool:
    """The airport is named for the place (all folded): its display city is
    the place or its name contains the place name. The suburb rule's "own"
    (never distance alone: Pontevedra, Buenos Aires is near EZE, not its
    own airport's town)."""
    return airport_city == place or words_in(place, airport_name)


def is_own_airport(
    place: str,
    airport_city: str,
    airport_name: str,
    same_country: bool,
    distance_km: float,
) -> bool:
    """An airport is a place's own (all names folded) when its display city
    is the place, its name contains the place name ("Basel" for BSL in
    France), or it is in the same country within ``OWN_AIRPORT_KM``."""
    return (
        airport_city == place
        or words_in(place, airport_name)
        or (same_country and distance_km <= OWN_AIRPORT_KM)
    )


# "BER — Berlin, Germany" (the UI's airport label): the code prefix.
CODE_PREFIX_RE = re.compile(r"^\s*([A-Za-z]{3})\s*(?:[—–]|\s-)\s*")
