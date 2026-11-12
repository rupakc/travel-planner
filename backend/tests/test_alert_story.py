"""Price story read model: the shared golden cases and the pure helpers."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.services import alert_story

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
CASES = json.loads(
    (Path(__file__).parent / "fixtures/alerts/story_cases.json").read_text()
)


def _iso(days_ago):
    return (NOW - timedelta(days=days_ago)).isoformat()


def _inputs(i):
    kind = i["kind"]
    watch = {
        "id": 1,
        "currency": i["currency"],
        "alert_mode": "below_target" if i["target"] is not None else "any_drop",
        "target_price": i["target"],
        "last_checked_at": _iso(i["checked_days_ago"])
        if i["checked_days_ago"] is not None
        else None,
        "pending_first_check": i["pending_first_check"],
        "subject": {},
    }
    if i["estimate"]:
        watch["subject"] = {"estimate_total": i["estimate"]["price"]}
    if i["google_typical"]:
        watch["google_typical_low"], watch["google_typical_high"] = i["google_typical"]
    history = [
        {"checked_at": _iso(p["days_ago"]), "price": p["price"]} for p in i["points"]
    ]
    if kind != "flight":
        for h in history:
            h["observed"] = {"status": "ok"}
    return kind, watch, history


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_story_golden(case):
    kind, watch, history = _inputs(case["input"])
    story = alert_story.build_story(
        kind, watch, history, live_prices=case["input"]["live_prices"], now=NOW
    )
    exp = case["expected"]
    assert story["typical"] == exp["typical"]
    assert story["verdict"] == exp["verdict"]
    assert story["advice"] == exp["advice"]
    assert (story["lowest"] or {}).get("price") == exp["lowest"]
    assert (story["latest"] or {}).get("price") == exp["latest"]
    assert story["checked_days_ago"] == case["input"]["checked_days_ago"]


def test_story_without_key_says_paused():
    case = next(c for c in CASES if c["name"] == "no_key_stale_9_days")
    kind, watch, history = _inputs(case["input"])
    s = alert_story.build_story(kind, watch, history, live_prices=False, now=NOW)
    assert s["advice"] == {"code": "checks_paused", "params": {"days": 9}}
    assert s["verdict"] is None
    assert s["typical"] is not None


def test_points_capped_at_90_oldest_first():
    history = [{"checked_at": _iso(120 - i), "price": 100.0 + i} for i in range(120)]
    watch = {"id": 1, "last_checked_at": _iso(0)}
    s = alert_story.build_story("flight", watch, history, live_prices=True, now=NOW)
    assert len(s["points"]) == 90
    assert s["points"][0]["price"] == 130.0 and s["points"][-1]["price"] == 219.0
    ats = [p["at"] for p in s["points"]]
    assert ats == sorted(ats) and ats[0].endswith("Z")


def test_estimate_story_has_no_verdict():
    watch = {
        "id": 1,
        "currency": "USD",
        "subject": {"estimate_total": 180.0},
        "pending_first_check": False,
    }
    s = alert_story.build_story("hotel", watch, [], live_prices=True, now=NOW)
    assert s["estimate"] == {"price": 180.0, "source": "ai_estimate"}
    assert s["verdict"] is None and s["latest"] is None and s["points"] == []
    assert s["advice"]["code"] == "pending"


def test_unavailable_looks_are_not_points():
    history = [
        {"checked_at": _iso(1), "price": None, "observed": {"status": "unavailable"}},
        {"checked_at": _iso(0), "price": 90.0, "observed": {"status": "ok"}},
    ]
    s = alert_story.build_story(
        "hotel",
        {"id": 1, "last_checked_at": _iso(0)},
        history,
        live_prices=True,
        now=NOW,
    )
    assert [p["price"] for p in s["points"]] == [90.0]


def test_typical_and_verdict_helpers():
    assert alert_story.typical_from_points([1, 2, 3]) is None
    assert alert_story.verdict(None, {"low": 1, "high": 2}) is None
    assert alert_story.verdict(5, None) is None
