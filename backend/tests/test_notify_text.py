import string

from app.services import notify_text

LANGS = ("en", "es", "de", "fr", "hi", "zh", "bn")


def _fields(t):
    return {f for _, f, _, _ in string.Formatter().parse(t) if f}


def test_all_languages_have_every_key_and_placeholders():
    en = notify_text.TEMPLATES["en"]
    assert set(notify_text.TEMPLATES) == set(LANGS)
    for lang in LANGS:
        tpl = notify_text.TEMPLATES[lang]
        assert set(tpl) == set(en), lang
        for k, v in tpl.items():
            assert _fields(v) == _fields(en[k]), (lang, k)


def test_render_and_fallback():
    assert "Tokyo" in notify_text.render("trip_t7", "de-DE", destination="Tokyo")
    assert notify_text.catalog("xx")["locale"] == "en"
