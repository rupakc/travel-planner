"""Quiz engine: a deterministic question builder and scoring. Pure (no I/O
beyond loading the committed bank), so a quiz makes no AI call and the same
(pack, seed) always yields the same questions, options and option order."""

import json
import random
from datetime import date
from functools import lru_cache
from pathlib import Path

BANK_PATH = Path(__file__).with_name("bank.json")
QUESTIONS_PER_QUIZ = 5
OPTIONS_PER_QUESTION = 4
OPTION_IDS = ("a", "b", "c", "d")
BASE_POINTS = 100
SPEED_BONUS_MAX = 50
SPEED_WINDOW_MS = 15_000

PACKS = ("flags", "capitals", "landmarks", "cuisine")
# question kinds each pack draws from
PACK_KINDS = {
    "flags": ("flag",),
    "capitals": ("capital_of", "country_of_capital"),
    "landmarks": ("landmark_country",),
    "cuisine": ("dish_country",),
}
# the daily quiz: one of each pack's kinds, plus one more at random
_DAILY_KINDS = ("flag", "capital", "landmark_country", "dish_country")


@lru_cache(maxsize=1)
def load_bank() -> dict:
    bank = json.loads(BANK_PATH.read_text(encoding="utf-8"))
    bank["by_code"] = {c["code"]: c for c in bank["countries"]}
    return bank


def pack_sizes() -> dict[str, int]:
    b = load_bank()
    return {
        "flags": len(b["countries"]),
        "capitals": len(b["countries"]),
        "landmarks": len(b["landmarks"]),
        "cuisine": len(b["dishes"]),
    }


def flag_emoji(code: str) -> str:
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code.upper())


def daily_seed(day: date) -> str:
    return f"daily:{day.isoformat()}"


def points_for(correct: bool, elapsed_ms: int) -> int:
    """100 for a correct answer plus up to 50 for speed, linear over 15 s."""
    if not correct:
        return 0
    left = max(0.0, 1.0 - max(0, elapsed_ms) / SPEED_WINDOW_MS)
    return BASE_POINTS + round(SPEED_BONUS_MAX * left)


def _distractors(rng, pool: list[dict], answer: dict, region_of) -> list[dict]:
    """Three wrong entries, preferring the answer's region (harder, fairer)."""
    others = [e for e in pool if e["code"] != answer["code"]]
    same = [e for e in others if region_of(e) == region_of(answer)]
    rest = [e for e in others if region_of(e) != region_of(answer)]
    rng.shuffle(same)
    rng.shuffle(rest)
    return (same + rest)[: OPTIONS_PER_QUESTION - 1]


def _finish(rng, kind: str, prompt: dict, right: dict, wrong: list[dict]) -> dict:
    """Shuffle the four options and give them opaque ids (the id reveals
    nothing about the answer); ``answer`` is the correct option id."""
    opts = [right, *wrong]
    rng.shuffle(opts)
    options, answer = [], ""
    for oid, o in zip(OPTION_IDS, opts, strict=True):
        opt = {"id": oid, "label": o["label"]}
        if o.get("code"):
            opt["code"] = o["code"]
        options.append(opt)
        if o is right:
            answer = oid
    return {"kind": kind, "prompt": prompt, "options": options, "answer": answer}


def _country_opt(c: dict) -> dict:
    return {"code": c["code"], "label": c["name"]}


def _build_one(rng, kind: str, answer_country: dict, bank: dict, item=None) -> dict:
    countries = bank["countries"]
    region = lambda c: c["region"]  # noqa: E731
    if kind == "flag":
        prompt = {"template": "flag", "flag": flag_emoji(answer_country["code"])}
        wrong = _distractors(rng, countries, answer_country, region)
        return _finish(
            rng,
            kind,
            prompt,
            _country_opt(answer_country),
            [_country_opt(c) for c in wrong],
        )
    if kind == "capital_of":
        prompt = {
            "template": "capital_of",
            "country": answer_country["name"],
            "code": answer_country["code"],
        }
        wrong = _distractors(rng, countries, answer_country, region)
        return _finish(
            rng,
            kind,
            prompt,
            {"label": answer_country["capital"]},
            [{"label": c["capital"]} for c in wrong],
        )
    if kind == "country_of_capital":
        prompt = {
            "template": "country_of_capital",
            "capital": answer_country["capital"],
        }
        wrong = _distractors(rng, countries, answer_country, region)
        return _finish(
            rng,
            kind,
            prompt,
            _country_opt(answer_country),
            [_country_opt(c) for c in wrong],
        )
    key = "landmark" if kind == "landmark_country" else "dish"
    prompt = {"template": kind, key: item["name"]}
    wrong = _distractors(rng, countries, answer_country, region)
    return _finish(
        rng,
        kind,
        prompt,
        _country_opt(answer_country),
        [_country_opt(c) for c in wrong],
    )


def _pick(rng, kind: str, bank: dict, used: set) -> tuple[dict, dict | None]:
    """An entity for ``kind`` not yet used in this quiz: (country, item)."""
    if kind in ("flag", "capital_of", "country_of_capital"):
        pool = [c for c in bank["countries"] if ("c", c["code"]) not in used]
        c = rng.choice(pool)
        used.add(("c", c["code"]))
        return c, None
    items = bank["landmarks"] if kind == "landmark_country" else bank["dishes"]
    tag = "l" if kind == "landmark_country" else "d"
    pool = [i for i in items if (tag, i["name"]) not in used]
    item = rng.choice(pool)
    used.add((tag, item["name"]))
    return bank["by_code"][item["country"]], item


def build_questions(
    pack: str, seed: str, count: int = QUESTIONS_PER_QUIZ
) -> list[dict]:
    """The quiz for ``pack`` (a pack id or ``"daily"``) and ``seed``. Each
    question: ``{index, kind, prompt, options, answer}``; strip ``answer``
    with :func:`public` before sending."""
    bank = load_bank()
    rng = random.Random(f"{pack}|{seed}")
    if pack == "daily":
        slots = list(_DAILY_KINDS) + [rng.choice(_DAILY_KINDS)]
        rng.shuffle(slots)
        slots = slots[:count]
    elif pack in PACK_KINDS:
        kinds = PACK_KINDS[pack]
        slots = [kinds[i % len(kinds)] for i in range(count)]
        rng.shuffle(slots)
    else:
        raise ValueError(f"unknown pack {pack}")
    used: set = set()
    out = []
    for i, slot in enumerate(slots):
        kind = (
            rng.choice(("capital_of", "country_of_capital"))
            if slot == "capital"
            else slot
        )
        country, item = _pick(rng, kind, bank, used)
        q = _build_one(rng, kind, country, bank, item)
        out.append({"index": i, **q})
    return out


def public(q: dict) -> dict:
    return {k: v for k, v in q.items() if k != "answer"}
