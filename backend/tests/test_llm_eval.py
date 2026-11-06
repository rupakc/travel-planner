"""The LLM eval harness (scripts/llm_eval.py): its pure compare/report code
and one faked run. The real ``run`` calls a paid API and never runs here."""

import importlib.util
import json
from pathlib import Path

import pytest

from app.core import llm

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "llm_eval.py"
_spec = importlib.util.spec_from_file_location("llm_eval", _SCRIPT)
llm_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(llm_eval)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "llm_eval"


def test_saved_requests_are_six_valid_searches():
    from app.schemas.request import TravelSearchRequest

    entries = json.loads((_FIXTURES / "requests.json").read_text())
    ids = [e["id"] for e in entries]
    assert ids == [
        "single-city",
        "multi-city",
        "family",
        "budget",
        "accessibility",
        "long-trip",
    ]
    for entry in entries:
        TravelSearchRequest(**entry["request"])


def _run(label, sections, usage):
    return {
        "meta": {
            "label": label,
            "provider": "x",
            "model_agent": "m",
            "model_chat": "c",
        },
        "requests": [
            {
                "id": "r1",
                "latency_s": 10.0,
                "sections": sections,
                "usage": usage,
                "totals": llm_eval._totals(usage, llm_eval.PRICES),
            }
        ],
    }


def test_compare_flags_missing_fields_errors_and_cost():
    usage_a = [
        {
            "label": "hotels",
            "model": "claude-haiku-4-5-20251001",
            "input_tokens": 1_000_000,
            "output_tokens": 0,
            "thinking_tokens": 0,
        }
    ]
    usage_b = [
        {
            "label": "hotels",
            "model": "gemini-3.5-flash-lite",
            "input_tokens": 1_000_000,
            "output_tokens": 0,
            "thinking_tokens": 0,
        }
    ]
    a = _run(
        "claude",
        {
            "hotels": {
                "results": [
                    {"name": "A", "price": 1, "tier": "luxury"},
                    {"name": "B", "price": 2, "tier": "budget"},
                ],
                "verification": {"level": "verified"},
            },
            "weather": {"days": [{"date": "d"}]},
        },
        usage_a,
    )
    b = _run(
        "gemini",
        {
            "hotels": {
                "results": [{"name": "A", "price": 1}],
                "verification": {"level": "partial"},
            },
            "weather": {"error": "timed out"},
        },
        usage_b,
    )

    diff = llm_eval.compare_runs(a, b)
    hotels = diff["requests"][0]["sections"]["hotels"]
    assert hotels["valid"] == (True, True)
    assert hotels["items"] == (2, 1)
    assert hotels["missing_fields"] == {"tier": 1}
    assert hotels["verification"] == ("verified", "partial")
    assert diff["requests"][0]["cost_usd"] == (1.0, 0.3)

    report = llm_eval.render_report(diff, a, b)
    assert "# LLM eval: claude → gemini" in report
    assert "`r1` / **weather**: B invalid (timed out)" in report
    assert "tier ×1" in report
    assert "$1.0000 → $0.3000" in report


def test_thinking_tokens_are_priced_as_output():
    rec = {
        "model": "gemini-3.5-flash-lite",
        "input_tokens": 0,
        "output_tokens": 500_000,
        "thinking_tokens": 500_000,
    }
    assert llm_eval.cost_usd(rec, llm_eval.PRICES) == pytest.approx(2.50)


async def test_run_one_collects_final_sections_and_usage():
    class FakeOrchestrator:
        async def stream_run(self, request):
            llm._log_usage(
                "hotels",
                "agent",
                llm.LLMResponse(
                    text="",
                    usage={"input_tokens": 10, "output_tokens": 5},
                ),
                0.0,
            )
            yield 'data: {"type": "hotels", "data": {"results": [1]}}\n\n'
            yield ": keepalive\n\n"
            yield 'data: {"type": "hotels", "data": {"results": [1, 2]}}\n\n'
            yield 'data: {"type": "done"}\n\n'

    entry = json.loads((_FIXTURES / "requests.json").read_text())[0]
    result = await llm_eval._run_one(FakeOrchestrator(), entry, llm_eval.PRICES)

    assert result["sections"] == {"hotels": {"results": [1, 2]}}
    assert result["totals"]["calls"] == 1
    assert result["usage"][0]["input_tokens"] == 10


def test_run_refuses_in_ci(monkeypatch):
    monkeypatch.setenv("CI", "true")
    with pytest.raises(SystemExit, match="not in CI"):
        llm_eval.main(["run", "--label", "x"])
