"""Place-name reference data shared by the airports DB and the static tables."""

import re
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


# Other names people type for a country (folded) → ISO alpha-2 code. The one
# alias map for the airports DB and the static reference tables; official
# names come from the dataset (airports) and the tables themselves.
COUNTRY_ALIASES: dict[str, str] = {
    "uk": "GB", "united kingdom": "GB", "britain": "GB", "great britain": "GB",
    "england": "GB", "scotland": "GB", "wales": "GB", "northern ireland": "GB",
    "usa": "US", "america": "US", "united states": "US",
    "united states of america": "US", "uae": "AE",
    "united arab emirates": "AE", "holland": "NL", "the netherlands": "NL",
    "korea": "KR", "south korea": "KR", "republic of korea": "KR",
    "czechia": "CZ", "czech republic": "CZ", "turkiye": "TR",
    "burma": "MM", "ivory coast": "CI", "swaziland": "SZ",
    "macedonia": "MK", "east timor": "TL", "cabo verde": "CV",
    "russian federation": "RU", "viet nam": "VN", "the bahamas": "BS",
    "the gambia": "GM", "republic of ireland": "IE", "dr congo": "CD",
    "drc": "CD",
}  # fmt: skip


# Tourist islands and island groups (folded name) → (ISO country, their
# scheduled airports, best first). Checked before place resolution: the
# island is not a town, or a namesake town would win ("Bali" → Bari).
ISLAND_AIRPORTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "crete": ("GR", ("HER", "CHQ")),
    "santorini": ("GR", ("JTR",)),
    "rhodes": ("GR", ("RHO",)),
    "corfu": ("GR", ("CFU",)),
    "kos": ("GR", ("KGS",)),
    "zakynthos": ("GR", ("ZTH",)),
    "zante": ("GR", ("ZTH",)),
    "kefalonia": ("GR", ("EFL",)),
    "cephalonia": ("GR", ("EFL",)),
    "sicily": ("IT", ("CTA", "PMO", "TPS")),
    "sardinia": ("IT", ("CAG", "OLB", "AHO")),
    "corsica": ("FR", ("AJA", "BIA", "FSC")),
    "mallorca": ("ES", ("PMI",)),
    "majorca": ("ES", ("PMI",)),
    "menorca": ("ES", ("MAH",)),
    "minorca": ("ES", ("MAH",)),
    "tenerife": ("ES", ("TFS", "TFN")),
    "gran canaria": ("ES", ("LPA",)),
    "lanzarote": ("ES", ("ACE",)),
    "fuerteventura": ("ES", ("FUE",)),
    "madeira": ("PT", ("FNC",)),
    "azores": ("PT", ("PDL", "TER")),
    "maui": ("US", ("OGG",)),
    "oahu": ("US", ("HNL",)),
    "big island": ("US", ("KOA", "ITO")),
    "kauai": ("US", ("LIH",)),
    "galapagos": ("EC", ("GPS", "SCY")),
    "galapagos islands": ("EC", ("GPS", "SCY")),
    "bali": ("ID", ("DPS",)),
    "lombok": ("ID", ("LOP",)),
    "zanzibar": ("TZ", ("ZNZ",)),
    "bora bora": ("PF", ("BOB",)),
    "tahiti": ("PF", ("PPT",)),
    "moorea": ("PF", ("MOZ", "PPT")),
    "langkawi": ("MY", ("LGK",)),
    "penang": ("MY", ("PEN",)),
    "koh samui": ("TH", ("USM",)),
    "ko samui": ("TH", ("USM",)),
    "koh phangan": ("TH", ("USM",)),
    "koh tao": ("TH", ("USM",)),
    "phi phi": ("TH", ("HKT", "KBV")),
    "boracay": ("PH", ("MPH", "KLO")),
    "palawan": ("PH", ("PPS",)),
    "jeju": ("KR", ("CJU",)),
    "jeju island": ("KR", ("CJU",)),
    "okinawa": ("JP", ("OKA",)),
    "easter island": ("CL", ("IPC",)),
    "isle of skye": ("GB", ("INV",)),
    "whitsundays": ("AU", ("PPP", "HTI")),
}

# Landmarks, parks and resorts (folded name) → (ISO country, the scheduled
# airports travellers use, best first): the name is not a large town, or a
# namesake elsewhere would win, or the nearest airport is not the usual one.
DESTINATION_AIRPORTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "machu picchu": ("PE", ("CUZ",)),
    "petra": ("JO", ("AQJ", "AMM")),
    "uluru": ("AU", ("AYQ",)),
    "ayers rock": ("AU", ("AYQ",)),
    "yosemite": ("US", ("FAT",)),
    "yosemite national park": ("US", ("FAT",)),
    "grand canyon": ("US", ("FLG", "LAS", "PHX")),
    "yellowstone": ("US", ("JAC", "BZN", "WYS")),
    "zion": ("US", ("SGU", "LAS")),
    "zion national park": ("US", ("SGU", "LAS")),
    "lake tahoe": ("US", ("RNO",)),
    "napa valley": ("US", ("STS", "SFO", "OAK")),
    "key west": ("US", ("EYW",)),
    "chamonix": ("FR", ("GVA",)),
    "zermatt": ("CH", ("ZRH", "GVA")),
    "interlaken": ("CH", ("ZRH", "BRN", "GVA")),
    "hallstatt": ("AT", ("SZG", "LNZ")),
    "banff": ("CA", ("YYC",)),
    "lake louise": ("CA", ("YYC",)),
    "jasper": ("CA", ("YEG",)),
    "whistler": ("CA", ("YVR",)),
    "manali": ("IN", ("KUU",)),
    "taj mahal": ("IN", ("AGR", "DEL")),
    "kyoto": ("JP", ("KIX", "ITM")),
    "goa": ("IN", ("GOI", "GOX")),
    "queenstown": ("NZ", ("ZQN",)),
    "leon": ("MX", ("BJX",)),
    "angkor wat": ("KH", ("SAI",)),
    "angkor": ("KH", ("SAI",)),
    "ha long bay": ("VN", ("HPH", "HAN")),
    "halong bay": ("VN", ("HPH", "HAN")),
    "bagan": ("MM", ("NYU",)),
    "everest base camp": ("NP", ("LUA", "KTM")),
    "serengeti": ("TZ", ("JRO",)),
    "masai mara": ("KE", ("NBO",)),
    "maasai mara": ("KE", ("NBO",)),
    "kruger national park": ("ZA", ("MQP",)),
    "cinque terre": ("IT", ("PSA", "GOA")),
    "amalfi coast": ("IT", ("NAP",)),
    "amalfi": ("IT", ("NAP",)),
    "positano": ("IT", ("NAP",)),
    "capri": ("IT", ("NAP",)),
    "lake como": ("IT", ("MXP", "LIN", "BGY")),
    "dolomites": ("IT", ("VRN", "BZO")),
    "cappadocia": ("TR", ("NAV", "ASR")),
    "pamukkale": ("TR", ("DNZ",)),
    "iguazu falls": ("AR", ("IGR", "IGU")),
    "torres del paine": ("CL", ("PNT", "PUQ")),
    "giza": ("EG", ("SPX", "CAI")),
    "pyramids of giza": ("EG", ("SPX", "CAI")),
    "cotswolds": ("GB", ("BHX", "LHR")),
    "lake district": ("GB", ("MAN",)),
}


# ── Airports a place owns (shared by the data generator and the runtime) ──

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
