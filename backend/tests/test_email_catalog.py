import json
import re
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "app" / "i18n" / "emails"
LANGS = ["en", "es", "de", "fr", "hi", "zh", "bn"]


def _load(lang):
    return json.loads((DIR / f"{lang}.json").read_text(encoding="utf-8"))


def _ph(text):
    return sorted(re.findall(r"\{\{\w+\}\}", text))


def test_all_languages_present():
    assert sorted(p.stem for p in DIR.glob("*.json")) == sorted(LANGS)


def test_catalogs_match_english():
    en = _load("en")
    for lang in LANGS:
        cat = _load(lang)
        assert set(cat) == set(en), lang
        for key, value in cat.items():
            assert value.strip(), f"{lang}.{key} empty"
            assert _ph(value) == _ph(en[key]), f"{lang}.{key} placeholders"
