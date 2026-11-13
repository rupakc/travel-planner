"""Localised price-alert wording for push, email and the weekly digest.

Each alert note keeps its English ``title`` / ``body`` exactly as before (the
in-app row, old SPA and the mobile apps read those). Alongside, the builders
store a small structured *spec* in ``data["i18n"]``; ``localise`` renders it
in the recipient's language when that is not English, and falls back to the
stored English whenever anything is missing or fails.

A spec is a string/number, or a dict with one of: ``k`` (+ ``p`` params, which
may themselves be specs; ``p.n`` picks the ``_one`` / ``_other`` template),
``date`` (ISO), ``dates`` ([dep, ret]), ``join`` (+ ``sep``), ``cap``.
"""

from datetime import date

from .alert_text_catalog import TEMPLATES

DEFAULT_LOCALE = "en"

_MONTHS = {
    "es": "ene feb mar abr may jun jul ago sep oct nov dic".split(),
    "de": "Jan Feb Mär Apr Mai Jun Jul Aug Sep Okt Nov Dez".split(),
    "fr": "janv. févr. mars avr. mai juin juil. août sept. oct. nov. déc.".split(),
    "hi": "जन॰ फ़र॰ मार्च अप्रैल मई जून जुल॰ अग॰ सित॰ अक्तू॰ नव॰ दिस॰".split(),
    "zh": [f"{m}月" for m in range(1, 13)],
    "bn": "জানু ফেব মার্চ এপ্রিল মে জুন জুলাই আগস্ট সেপ্টেম্বর অক্টোবর নভেম্বর ডিসেম্বর".split(),
}


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _loc(locale: str | None) -> str:
    base = (locale or DEFAULT_LOCALE).replace("_", "-").split("-")[0].lower()
    return base if base in TEMPLATES else DEFAULT_LOCALE


# ── Spec builders (used where notes are composed) ─────────────────────────────


def S(key: str, **params) -> dict:
    return {"k": key, "p": params}


def D(iso: str) -> dict:
    return {"date": iso}


def DR(dep: str, ret: str | None) -> dict:
    return {"dates": [dep, ret]}


def J(*parts, sep: str = " ") -> dict:
    return {"join": [p for p in parts if p not in (None, "")], "sep": sep}


def CAP(part) -> dict:
    return {"cap": part}


def note_text(title, body) -> dict:
    """The ``data["i18n"]`` value for a note."""
    return {"title": title, "body": body}


# ── Rendering ─────────────────────────────────────────────────────────────────


def _day(d: date, loc: str) -> str:
    if loc == "en":
        return f"{d.day} {d:%b}"
    mon = _MONTHS[loc][d.month - 1]
    return f"{mon}{d.day}日" if loc == "zh" else f"{d.day} {mon}"


def _range(dep: str, ret: str | None, loc: str) -> str:
    if loc == "en":
        from .fare_watch import date_range

        return date_range(dep, ret)
    a = date.fromisoformat(dep)
    if not ret:
        return _day(a, loc)
    b = date.fromisoformat(ret)
    if a.year != b.year:
        return f"{_day(a, loc)} {a.year} – {_day(b, loc)} {b.year}"
    return f"{_day(a, loc)} – {_day(b, loc)}"


def render(spec, locale: str | None) -> str:
    loc = _loc(locale)
    if spec is None:
        return ""
    if not isinstance(spec, dict):
        return str(spec)
    if "k" in spec:
        params = {k: render(v, loc) for k, v in (spec.get("p") or {}).items()}
        key, n = spec["k"], (spec.get("p") or {}).get("n")
        if n is not None and f"{key}_other" in TEMPLATES[DEFAULT_LOCALE]:
            key = f"{key}_{'one' if n == 1 else 'other'}"
        tpl = TEMPLATES[loc].get(key) or TEMPLATES[DEFAULT_LOCALE][key]
        return tpl.format_map(_Safe(params))
    if "date" in spec:
        return _day(date.fromisoformat(spec["date"]), loc)
    if "dates" in spec:
        return _range(spec["dates"][0], spec["dates"][1], loc)
    if "join" in spec:
        return spec.get("sep", " ").join(
            x for x in (render(p, loc) for p in spec["join"]) if x
        )
    if "cap" in spec:
        s = render(spec["cap"], loc)
        return s[:1].upper() + s[1:]
    return ""


def t(key: str, locale: str | None, **params) -> str:
    """One chrome string (email labels etc.); English when the key is unknown."""
    return render(S(key, **params), locale)


def localise(note: dict, locale: str | None) -> tuple[str, str]:
    """``(title, body)`` for the recipient; stored English unless the locale is
    not English and the note carries a spec that renders."""
    title, body = note.get("title") or "", note.get("body") or ""
    if _loc(locale) == DEFAULT_LOCALE:
        return title, body
    spec = (note.get("data") or {}).get("i18n")
    if not isinstance(spec, dict):
        return title, body
    try:
        return render(spec["title"], locale), render(spec["body"], locale)
    except Exception:  # noqa: BLE001
        return title, body
