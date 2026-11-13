"""Localised price-alert text: push, email, digest (English stays as stored)."""

import html
import re

import pytest

from app.core.config import settings
from app.services import alert_delivery, alert_digest, alert_email, alert_text
from app.services.alert_text import DR, D, S, localise, render
from app.services.alert_text_catalog import TEMPLATES
from app.services.fare_watch import (
    _error_note,
    _expired_note,
    evaluate,
)
from app.services.price_sources import activity as act
from app.services.price_watch import PriceObservation
from tests.test_fare_watch_rules import NOW, _check
from tests.test_fare_watch_rules import _watch as _fare_watch
from tests.test_price_source_activity import TestCompose as _ActCompose
from tests.test_price_source_hotel import LUMEN_SUBJECT, watch_for
from tests.test_price_source_hotel import SOURCE as HOTEL

LANGS = ["en", "es", "de", "fr", "hi", "zh", "bn"]
OTHER = [x for x in LANGS if x != "en"]
_FIELDS = re.compile(r"\{(\w+)\}")


def test_catalog_has_every_key_and_placeholder_in_every_language():
    en = TEMPLATES["en"]
    assert set(TEMPLATES) == set(LANGS)
    for lang in OTHER:
        assert set(TEMPLATES[lang]) == set(en), lang
        for key, tpl in en.items():
            assert set(_FIELDS.findall(TEMPLATES[lang][key])) == set(
                _FIELDS.findall(tpl)
            ), (lang, key)


def _notes():
    """One note per wording path (fare x5, expired, error, hotel x3, activity)."""
    out = []
    w = _fare_watch(target_price=480.0, alert_mode="below_target")
    out += evaluate(w, _check(470.0, price_level="low"), NOW)
    out += evaluate(_fare_watch(), _check(454.0), NOW)
    out += evaluate(_fare_watch(), _check(454.0, price_level="low"), NOW)
    out += [_expired_note(_fare_watch()), _error_note(_fare_watch())]
    obs = PriceObservation(
        price=352.0, unit_price=88.0, source="g", observed={"taxes_included": True}
    )
    hw = watch_for({**LUMEN_SUBJECT, "name": "Lumen Hotel"}, title="Lumen Hotel")
    out.append(HOTEL.compose("hotel_drop", hw, obs, 398.0))
    hw["target_price"] = 360.0
    out.append(HOTEL.compose("hotel_target", hw, obs, 398.0))
    hw2 = watch_for({**LUMEN_SUBJECT, "rooms": 2, "adults": 3})
    out.append(HOTEL.compose("hotel_drop", hw2, obs, 398.0))
    return out


def test_english_spec_renders_exactly_the_stored_english():
    notes = _notes()
    assert len(notes) >= 8
    for n in notes:
        spec = n["data"]["i18n"]
        assert render(spec["title"], "en") == n["title"], n["kind"]
        assert render(spec["body"], "en") == n["body"], n["kind"]
        assert localise(n, "en") == (n["title"], n["body"])
        assert localise(n, None) == (n["title"], n["body"])


@pytest.mark.parametrize("lang", OTHER)
def test_every_note_localises_and_keeps_its_facts(lang):
    for n in _notes():
        title, body = localise(n, lang)
        assert (title, body) != (n["title"], n["body"]), (lang, n["kind"])
        # money and unlocalised names survive translation
        for money in re.findall(r"[$]\d[\d,]*", n["title"]):
            assert money in title, (lang, n["kind"], title)
        assert "{" not in title + body


def test_activity_note_localises():
    t = _ActCompose()
    w = t._w()
    obs = PriceObservation(price=9.9, unit_price=9.9, source="x")
    note = act.SOURCE.compose("activity_drop", w, obs, 11.63)
    assert render(note["data"]["i18n"]["title"], "en") == note["title"]
    assert render(note["data"]["i18n"]["body"], "en") == note["body"]
    assert "Belém walking tour" in localise(note, "fr")[0]
    assert localise(note, "fr")[0] != note["title"]


def test_dates_are_localised_per_language():
    assert render(DR("2026-12-01", "2026-12-08"), "en") == "1–8 Dec"
    assert render(D("2026-03-05"), "es") == "5 mar"
    assert render(D("2026-03-05"), "zh") == "3月5日"
    assert render(DR("2026-12-28", "2027-01-04"), "de") == "28 Dez 2026 – 4 Jan 2027"


def test_unknown_locale_and_missing_spec_fall_back_to_english():
    note = {"title": "T", "body": "B", "data": {}}
    assert localise(note, "de") == ("T", "B")
    assert localise({"title": "T", "body": "B", "data": {"i18n": {"x": 1}}}, "de") == (
        "T",
        "B",
    )
    assert render(S("g_title", n=3), "xx") == "3 prices dropped"


def _rows(n):
    return [
        {"id": i, "kind": "fare_drop", "title": f"T{i}", "body": f"B{i}", "data": {}}
        for i in range(n)
    ]


def test_push_payload_english_is_unchanged_and_grouped_text_localises():
    rows = _rows(5)
    assert alert_delivery._push_payload(rows)[:2] == (
        "5 prices dropped",
        "T0; T1; T2 and 2 more",
    )
    assert alert_delivery._push_payload(rows, "en")[:2] == (
        "5 prices dropped",
        "T0; T1; T2 and 2 more",
    )
    title, body, _ = alert_delivery._push_payload(rows, "de")
    assert title == "5 Preise gefallen" and body.endswith("und 2 weitere")


def test_push_payload_single_note_localises():
    note = _notes()[1]
    note = {**note, "id": 1}
    title, body, data = alert_delivery._push_payload([note], "es")
    assert title != note["title"] and "$454" in title
    assert data["category"] == "price_drops"
    assert alert_delivery._push_payload([note])[:2] == (note["title"], note["body"])


@pytest.fixture
def _mail(monkeypatch):
    monkeypatch.setattr(settings, "app_base_url", "https://trip.test")
    monkeypatch.setattr(settings, "smtp_from", "Fare Alerts <alerts@trip.test>")


@pytest.mark.parametrize("lang", LANGS)
def test_fare_email_per_locale(_mail, lang):
    note = {**evaluate(_fare_watch(), _check(454.0), NOW)[0], "id": 1}
    msg = alert_email.build_message(note, _fare_watch(), "a@b.test", [], lang)
    text = msg.get_body(("plain",)).get_content()
    html = msg.get_body(("html",)).get_content()
    if lang == "en":
        assert msg["Subject"] == note["title"]
        assert "See flights:" in text and "Fares change fast" in html
        # identical to the no-locale rendering
        base = alert_email.build_message(note, _fare_watch(), "a@b.test", [])
        assert base.get_body(("plain",)).get_content() == text
    else:
        assert msg["Subject"] == alert_text.localise(note, lang)[0] != note["title"]
        assert "See flights" not in text and "See flights" not in html
        assert "Fares change fast" not in html
        assert TEMPLATES[lang]["e_fares_fast"] in html
    assert "$454" in text


@pytest.mark.parametrize("lang", LANGS)
def test_price_email_per_locale(_mail, lang):
    obs = PriceObservation(price=352.0, unit_price=88.0, source="g")
    hw = watch_for({**LUMEN_SUBJECT, "name": "Lumen Hotel"}, title="Lumen Hotel")
    note = {**HOTEL.compose("hotel_drop", hw, obs, 398.0), "id": 2}
    hw.update(id=7, subtitle="", currency="USD")
    msg = alert_email.build_price_message(
        {**note, "data": {**note["data"], "previous_price": 398.0, "price": 352.0}},
        hw,
        "a@b.test",
        [],
        lang,
    )
    text = msg.get_body(("plain",)).get_content()
    page = msg.get_body(("html",)).get_content()
    assert html.escape(TEMPLATES[lang]["e_hotel_eyebrow"]) in page
    assert TEMPLATES[lang]["e_stop"] in text
    if lang != "en":
        assert "Stop emails" not in text and "Hotel price watch" not in text


@pytest.mark.parametrize("lang", LANGS)
def test_digest_text_and_email_per_locale(_mail, lang):
    digest = {
        "week": "2026-W46",
        "watches": [
            {
                "title": "Lisbon",
                "latest": 100.0,
                "currency": "USD",
                "change_7d": -20.0,
                "spark": [120, 100],
            }
        ],
        "savings": {"total_usd": 1234},
    }
    title, body = alert_digest._title_body(digest, lang)
    if lang == "en":
        assert (title, body) == (
            "Your weekly price digest",
            "1 watch checked this week, $1,234 caught so far",
        )
        assert alert_digest._title_body(digest) == (title, body)
    else:
        assert title == TEMPLATES[lang]["d_title"] != "Your weekly price digest"
        assert "$1,234" in body and "caught so far" not in body
    msg = alert_email.build_digest_message(
        {"id": "u1", "email": "a@b.test"}, digest, lang
    )
    assert msg["Subject"] == TEMPLATES[lang]["d_subject"].format(week="2026-W46")
    text = msg.get_body(("plain",)).get_content()
    assert TEMPLATES[lang]["d_stop"] in text
