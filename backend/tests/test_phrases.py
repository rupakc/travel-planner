import csv
import json
from pathlib import Path

from app.services.phrases import phrases_for_country

_APP = Path(__file__).resolve().parent.parent / "app"
DATA = json.loads((_APP / "data" / "travel_phrases.json").read_text(encoding="utf-8"))
IDS = ["help", "call_police", "need_doctor", "take_me_to", "thank_you",
       "how_much", "where_toilet", "dont_understand"]
LANGS = ("ar bn cs da de el es fi fr he hi hr hu id is it ja km ko ms nl no pl pt "
         "ro ru sv sw th tl tr uk vi zh").split()


def test_phrase_ids_and_language_list():
    assert DATA["version"] == 1
    assert DATA["phrase_ids"] == IDS
    assert sorted(DATA["languages"]) == sorted(LANGS)


def test_every_language_has_all_ids_with_text():
    for code, lang in DATA["languages"].items():
        assert lang["name"].strip() and lang["script"]
        assert set(lang["phrases"]) == set(IDS), code
        for pid in IDS:
            assert lang["phrases"][pid]["text"].strip(), (code, pid)


def test_non_latin_scripts_have_romanization():
    for code, lang in DATA["languages"].items():
        for pid in IDS:
            rom = lang["phrases"][pid]["romanized"]
            if lang["script"] == "Latn":
                assert rom is None, (code, pid)
            else:
                assert rom and rom.strip(), (code, pid)


def test_every_country_maps_to_known_language_or_null():
    with open(_APP / "db" / "data" / "countries.csv", encoding="utf-8", newline="") as f:
        codes = {r["code"] for r in csv.DictReader(f)}
    assert set(DATA["countries"]) == codes
    for cc, lang in DATA["countries"].items():
        assert lang is None or lang in DATA["languages"], cc


def test_phrases_for_country():
    jp = phrases_for_country("JP")
    assert jp["language"] == "ja"
    assert jp["language_name"] == "日本語"
    assert [i["id"] for i in jp["items"]] == IDS
    assert jp["items"][0]["romanized"]
    assert phrases_for_country("GB") is None
    assert phrases_for_country("BR")["language"] == "pt"
    assert phrases_for_country("br")["language"] == "pt"
    assert phrases_for_country("zz") is None
    assert phrases_for_country("") is None
    assert phrases_for_country(None) is None


def test_thai_polite_particles():
    for pid, p in DATA["languages"]["th"]["phrases"].items():
        if pid == "help":
            continue
        assert p["text"].rstrip(":").endswith("ครับ/ค่ะ"), pid
        assert p["romanized"].rstrip(":").endswith("kráp/kâ"), pid


def test_neutral_choices():
    assert DATA["countries"]["SX"] is None
    assert DATA["languages"]["pt"]["phrases"]["where_toilet"]["text"] == "Onde ficam os sanitários?"
