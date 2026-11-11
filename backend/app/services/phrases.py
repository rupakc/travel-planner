"""Offline travel phrases per country, from ``app/data/travel_phrases.json``."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_FILE = Path(__file__).resolve().parent.parent / "data" / "travel_phrases.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(_FILE.read_text(encoding="utf-8"))


def phrases_for_country(code: str) -> dict | None:
    """``{language, language_name, items}`` for the country's main language, else None."""
    if not isinstance(code, str):
        return None
    data = _data()
    lang_code = data["countries"].get(code.strip().upper())
    lang = data["languages"].get(lang_code) if lang_code else None
    if not lang:
        return None
    items = []
    for pid in data["phrase_ids"]:
        p = lang["phrases"][pid]
        items.append({"id": pid, "text": p["text"], "romanized": p["romanized"]})
    return {"language": lang_code, "language_name": lang["name"], "items": items}
