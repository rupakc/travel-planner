"""Localised share cards: every language renders, glyphs exist, raqm fallback."""

import io
import json

import pytest
from PIL import Image, ImageChops

from app.services import share_card, share_public
from app.services import share_card_i18n as i18n

LANGS = i18n.LANGS


def _snap(kind="plan", **kw):
    plan = {
        "name": "Trip",
        "search_data": {
            "destination": "Lisbon",
            "origin": "Paris",
            "departure_date": "2026-04-01",
            "return_date": "2026-04-07",
        },
        "selections": {"activities": [{"name": "a"}], "hotels": [{"name": "h"}]},
    }
    return share_public.build_snapshot(
        kind, {"dates": "month", "show_origin": True, **kw}, plan=plan
    )


def _img(png):
    return Image.open(io.BytesIO(png)).convert("RGB")


def _blank(img):
    return img.getbbox() is None or len(img.getcolors(maxcolors=1 << 20) or []) < 3


@pytest.mark.parametrize("lang", LANGS)
def test_card_renders_and_differs_from_english(lang):
    en = share_card.render(_snap(), "link", "en")
    png = share_card.render(_snap(), "link", lang)
    img = _img(png)
    assert img.size == (1200, 630) and not _blank(img)
    if lang == "en":
        assert png == en
    elif lang in share_card.COMPLEX_SCRIPTS and not share_card.raqm_available():
        assert png == en  # documented degrade
    else:
        assert ImageChops.difference(img, _img(en)).getbbox() is not None


@pytest.mark.parametrize("lang", LANGS)
def test_story_size_all_kinds(lang):
    for kind in ("plan", "recap"):
        img = _img(share_card.render(_snap(kind), "story", lang))
        assert img.size == (1080, 1920) and not _blank(img)


@pytest.mark.parametrize("lang", LANGS)
def test_every_catalogue_char_has_a_glyph(lang):
    """No tofu: each character the language can draw is in the font it uses."""
    t = json.dumps(i18n.STRINGS[lang], ensure_ascii=False)
    text = "".join(c for c in t if c not in '{}[]":,() \n')
    # placeholders/format letters are ASCII; native chars must be covered
    assert share_card.supported(text + "Voyager $1,234.50 0123456789", lang)


def test_bundled_subsets_match_coverage_file_and_catalogue():
    ttlib = pytest.importorskip("fontTools.ttLib")
    cov = share_card._coverage()
    for name, points in cov.items():
        font = ttlib.TTFont(share_card.FONT_DIR / name)
        assert set(font.getBestCmap()) == set(points)
    everything = {ord(c) for c in i18n.all_text() if c.strip()}
    union = set().union(*cov.values())
    assert everything <= union


def test_headlines_are_localised():
    snap = _snap()
    assert share_card.headline_for(snap, "es") == "7 días en Lisbon"
    assert share_card.headline_for(snap, "de") == "7 Tage in Lisbon"
    assert share_card.headline_for(snap, "fr") == "7 jours à Lisbon"
    assert share_card.headline_for(snap, "hi") == "Lisbon में 7 दिन"
    assert share_card.headline_for(snap, "zh") == "Lisbon 7 天"
    assert share_card.headline_for(snap, "bn") == "Lisbon-এ 7 দিন"
    assert share_card.headline_for(snap, "en") == "7 days in Lisbon"
    assert share_card.month_label("2026-04", "es") == "abril de 2026"
    assert share_card.month_label("2026-04", "zh") == "2026年4月"
    assert share_card.stat_text({"key": "hotels", "count": 2}, "de") == "2 Hotels"


def test_savings_quiz_status_headlines():
    sav = share_public.build_snapshot("savings", None, savings={"total_usd": 120})
    assert "$120" in share_card.headline_for(sav, "fr")
    quiz = share_public.build_snapshot(
        "quiz",
        None,
        quiz={"mode": "pack", "pack": "flags", "questions": [1] * 5, "correct": 4},
    )
    assert share_card.headline_for(quiz, "es") == "Quiz de banderas: 4/5"
    assert share_card.headline_for(quiz, "zh") == "国旗测验：4/5"


def test_undrawable_place_is_dropped_not_tofu():
    snap = _snap()
    snap["destination"] = "Ελλάδα"  # Greek: not in any bundled subset
    assert share_card.headline_for(snap, "es") == "Faltan 7 días"
    snap["owner_name"] = "Ελλάδα"
    img = _img(share_card.render(snap, "link", "es"))
    assert not _blank(img)


def test_unknown_lang_falls_back_to_english():
    assert share_card.render(_snap(), "link", "xx") == share_card.render(
        _snap(), "link", "en"
    )


def test_raqm_absent_degrades_hi_bn_to_english(monkeypatch):
    monkeypatch.setattr(share_card, "raqm_available", lambda: False)
    en = share_card.render(_snap(), "link", "en")
    for lang in ("hi", "bn"):
        assert share_card.effective_lang(lang) == "en"
        assert share_card.render(_snap(), "link", lang) == en
    # zh and Latin languages do not need raqm
    assert share_card.effective_lang("zh") == "zh"
    assert share_card.render(_snap(), "link", "zh") != en


def test_cache_key_includes_lang():
    share_card.invalidate("tl")
    a = share_card.get_card("tl", _snap(), "link", "es")
    b = share_card.get_card("tl", _snap(), "link", "de")
    assert a != b
    assert share_card.get_card("tl", _snap(), "link", "es") is a
    share_card.invalidate("tl")
    assert not [k for k in share_card._cache if k[0] == "tl"]
