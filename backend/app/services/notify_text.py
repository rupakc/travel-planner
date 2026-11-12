"""Notification text, served to apps (``GET /notifications/catalog``) and used
by the server senders. T1 stub: English only; T2 fills the other six languages
and keeps these signatures. Placeholders are ``{name}`` format fields."""

DEFAULT_LOCALE = "en"

TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "trip_t30": "{destination} is 30 days away. Check your visa and entry rules.",
        "trip_t7": "One week to {destination}. Time to pack.",
        "trip_t1": "Tomorrow you fly to {destination}. Check in and review the weather.",
        "trip_morning": "Good morning from {destination}. Open Today for your plan.",
        "nearby_arrival": "You're near {place}: {item} is {minutes} min away",
    },
}


def _locale(locale: str | None) -> str:
    base = (locale or DEFAULT_LOCALE).replace("_", "-").split("-")[0].lower()
    return base if base in TEMPLATES else DEFAULT_LOCALE


def catalog(locale: str | None) -> dict:
    """``{"locale", "templates"}``; an unknown locale falls back to English."""
    loc = _locale(locale)
    return {"locale": loc, "templates": dict(TEMPLATES[loc])}


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return ""


def render(key: str, locale: str | None, **params) -> str:
    """Fill template ``key``; a missing param renders empty, an unknown key or
    locale falls back (key -> ``KeyError``, locale -> English)."""
    loc = _locale(locale)
    tpl = TEMPLATES[loc].get(key) or TEMPLATES[DEFAULT_LOCALE][key]
    return tpl.format_map(_Safe(params))
