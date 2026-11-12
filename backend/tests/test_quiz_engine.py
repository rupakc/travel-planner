import csv
from datetime import date
from pathlib import Path

import pytest

from app.game.quiz import engine

DATA = Path(__file__).resolve().parents[1] / "app" / "db" / "data" / "countries.csv"


def _iso_codes() -> set[str]:
    with open(DATA, encoding="utf-8", newline="") as f:
        return {r["code"] for r in csv.DictReader(f)}


def test_bank_minimums_and_valid_codes():
    b = engine.load_bank()
    assert len(b["countries"]) >= 80
    assert len(b["landmarks"]) >= 40
    assert len(b["dishes"]) >= 40
    codes = [c["code"] for c in b["countries"]]
    assert len(codes) == len(set(codes))
    assert set(codes) <= _iso_codes()
    for c in b["countries"]:
        assert len(c["code"]) == 2 and c["code"].isupper()
        assert c["name"].strip() and c["capital"].strip()
        assert c["region"] in {"eu", "af", "as", "am", "oc"}


def test_bank_unique_labels_and_references():
    b = engine.load_bank()
    for key in ("name", "capital"):
        vals = [c[key] for c in b["countries"]]
        assert len(vals) == len(set(vals)), key
    for group in ("landmarks", "dishes"):
        names = [e["name"] for e in b[group]]
        assert len(names) == len(set(names)), group
        for e in b[group]:
            assert e["country"] in b["by_code"], e
    assert len({c["region"] for c in b["countries"]}) == 5


def test_known_capitals_spot_check():
    by = engine.load_bank()["by_code"]
    expected = {
        "AU": "Canberra", "BR": "Brasília", "CA": "Ottawa", "TR": "Ankara",
        "CH": "Bern", "NZ": "Wellington", "NG": "Abuja", "IN": "New Delhi",
        "US": "Washington, D.C.", "TZ": "Dodoma", "MA": "Rabat", "KZ": "Astana",
    }  # fmt: skip
    for code, cap in expected.items():
        assert by[code]["capital"] == cap


def test_every_pack_has_enough_distractors():
    b = engine.load_bank()
    sizes = engine.pack_sizes()
    assert set(sizes) == set(engine.PACKS)
    for n in sizes.values():
        assert n >= engine.QUESTIONS_PER_QUIZ
    assert len(b["countries"]) > engine.OPTIONS_PER_QUESTION


@pytest.mark.parametrize("pack", [*engine.PACKS, "daily"])
def test_questions_well_formed(pack):
    for n in range(40):
        qs = engine.build_questions(pack, f"seed{n}")
        assert len(qs) == 5
        for i, q in enumerate(qs):
            assert q["index"] == i
            ids = [o["id"] for o in q["options"]]
            assert ids == list(engine.OPTION_IDS)
            labels = [o["label"] for o in q["options"]]
            assert len(set(labels)) == 4
            assert q["answer"] in ids
            assert "answer" not in engine.public(q)


def _answer_label(q):
    return next(o["label"] for o in q["options"] if o["id"] == q["answer"])


def test_answers_are_actually_right():
    b = engine.load_bank()
    capitals = {c["name"]: c["capital"] for c in b["countries"]}
    countries_by_capital = {c["capital"]: c["name"] for c in b["countries"]}
    by_code = b["by_code"]
    lm = {e["name"]: by_code[e["country"]]["name"] for e in b["landmarks"]}
    dish = {e["name"]: by_code[e["country"]]["name"] for e in b["dishes"]}
    flags = {engine.flag_emoji(c["code"]): c["name"] for c in b["countries"]}
    seen = set()
    for n in range(150):
        for q in engine.build_questions("daily", f"s{n}") + engine.build_questions(
            ["flags", "capitals", "landmarks", "cuisine"][n % 4], f"p{n}"
        ):
            p, ans = q["prompt"], _answer_label(q)
            seen.add(q["kind"])
            if q["kind"] == "flag":
                assert flags[p["flag"]] == ans
            elif q["kind"] == "capital_of":
                assert capitals[p["country"]] == ans
                assert by_code[p["code"]]["name"] == p["country"]
            elif q["kind"] == "country_of_capital":
                assert countries_by_capital[p["capital"]] == ans
            elif q["kind"] == "landmark_country":
                assert lm[p["landmark"]] == ans
            else:
                assert dish[p["dish"]] == ans
    assert seen == {
        "flag", "capital_of", "country_of_capital", "landmark_country", "dish_country",
    }  # fmt: skip


def test_deterministic_by_seed_and_daily_by_date():
    a = engine.build_questions("flags", "x")
    assert a == engine.build_questions("flags", "x")
    assert a != engine.build_questions("flags", "y")
    d1 = engine.build_questions("daily", engine.daily_seed(date(2026, 11, 12)))
    assert d1 == engine.build_questions("daily", engine.daily_seed(date(2026, 11, 12)))
    assert d1 != engine.build_questions("daily", engine.daily_seed(date(2026, 11, 13)))


def test_no_repeated_entity_in_a_quiz():
    for n in range(100):
        qs = engine.build_questions("daily", f"r{n}")
        keys = [
            q["prompt"].get("flag") or q["prompt"].get("landmark")
            or q["prompt"].get("dish") or q["prompt"].get("code")
            or q["prompt"].get("capital")
            for q in qs
        ]  # fmt: skip
        assert len(set(keys)) == 5


def test_option_order_not_biased_to_one_slot():
    slots = {engine.build_questions("flags", f"o{n}")[0]["answer"] for n in range(60)}
    assert slots == set(engine.OPTION_IDS)


def test_unknown_pack():
    with pytest.raises(ValueError):
        engine.build_questions("etiquette", "x")


def test_points():
    assert engine.points_for(False, 0) == 0
    assert engine.points_for(True, 0) == 150
    assert engine.points_for(True, 7500) == 125
    assert engine.points_for(True, 15000) == 100
    assert engine.points_for(True, 99999) == 100
    assert engine.points_for(True, -5) == 150


def test_flag_emoji():
    assert engine.flag_emoji("JP") == "\U0001f1ef\U0001f1f5"
