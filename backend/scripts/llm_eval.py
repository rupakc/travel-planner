"""LLM provider/model evaluation: run saved searches, then compare two runs.

Offline tool, run by hand; never in CI (it calls the real model and costs
money). ``run`` sends each saved request through the full search pipeline
(``TravelOrchestrator.stream_run``, the same code as ``POST /api/search``)
on the chosen provider/model and stores the final section outputs, per-call
token usage, latency and estimated cost as JSON. ``compare`` diffs two runs
per section (schema validity, item counts, required fields, verification
chips, cost) and writes a Markdown report.

    cd backend
    gcloud auth application-default login     # Gemini on Vertex AI (ADC)
    python3 scripts/llm_eval.py run --provider gemini --label gemini
    python3 scripts/llm_eval.py run --provider anthropic --label claude
    python3 scripts/llm_eval.py compare eval-runs/claude.json \\
        eval-runs/gemini.json --out eval-runs/claude-vs-gemini.md

Live link search (SerpAPI flights, Serper places) is off by default so both
runs measure the model alone; ``--keep-search-keys`` keeps it. The place
data is seeded into a throwaway ``DATA_DIR`` unless ``--data-dir`` is given.
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_DEFAULT_REQUESTS = _BACKEND / "tests" / "fixtures" / "llm_eval" / "requests.json"
_DEFAULT_OUT = _BACKEND / "eval-runs"
_DEFAULT_PROJECT = "voyager-prod-ohzkl"

# USD per 1M tokens (input, output). Thinking tokens bill as output. Gemini
# 3.8 Flash is $0.75 / $3.75 until 2026-12-31, then $1.50 / $7.50 — pass
# --prices to price a run at other rates.
PRICES = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.8-flash": (0.75, 3.75),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
}

# Where a section keeps its list of items, in order of preference.
_ITEM_KEYS = (
    "results",
    "days",
    "items",
    "destinations",
    "options",
    "categories",
    "issues",
    "checks",
    "tips",
    "phrases",
)
# Stream events that are not sections.
_NOT_SECTIONS = {"agent_status", "done", "confidence"}


# ── run ───────────────────────────────────────────────────────────────


def _configure_env(args) -> None:
    """Settings are read once at import: set everything before importing app."""
    os.environ["LLM_PROVIDER"] = args.provider
    os.environ["GCP_PROJECT"] = args.project
    os.environ["GCP_LOCATION"] = args.location
    for flag, var in (
        (args.model_agent, "GEMINI_MODEL_AGENT"),
        (args.model_chat, "GEMINI_MODEL_CHAT"),
        (args.thinking_agent, "GEMINI_THINKING_AGENT"),
        (args.thinking_chat, "GEMINI_THINKING_CHAT"),
    ):
        if flag:
            os.environ[var] = flag
    if not args.keep_search_keys:
        os.environ["SERPAPI_KEY"] = ""
        os.environ["SERPER_KEY"] = ""
    os.environ["BACKUP_BUCKET"] = ""
    os.environ["FARE_WATCH_ENABLED"] = "false"
    os.environ["DATA_DIR"] = args.data_dir or tempfile.mkdtemp(prefix="llm_eval_")
    sys.path.insert(0, str(_BACKEND))


def _seed() -> None:
    from app.db.database import create_tables
    from app.db.places_db import warm
    from app.db.seed_airports import seed as seed_airports
    from app.db.seed_nationalities import seed as seed_nationalities

    seed_airports()
    warm()
    seed_nationalities()
    create_tables()


def cost_usd(record: dict, prices: dict) -> float:
    pin, pout = prices.get(record.get("model"), (0.0, 0.0))
    out = record.get("output_tokens", 0) + record.get("thinking_tokens", 0)
    return (record.get("input_tokens", 0) * pin + out * pout) / 1_000_000


def _totals(usage: list[dict], prices: dict) -> dict:
    totals = Counter()
    for rec in usage:
        for key in ("input_tokens", "output_tokens", "thinking_tokens"):
            totals[key] += rec.get(key, 0)
    totals["calls"] = len(usage)
    return {**totals, "cost_usd": round(sum(cost_usd(r, prices) for r in usage), 5)}


async def _run_one(orchestrator, entry: dict, prices: dict) -> dict:
    from app.core import llm
    from app.schemas.request import TravelSearchRequest

    request = TravelSearchRequest(**entry["request"])
    sections: dict = {}
    arrived: dict = {}
    started = time.monotonic()
    with llm.record_usage() as usage:
        async for chunk in orchestrator.stream_run(request):
            for line in chunk.splitlines():
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[len("data: ") :])
                except ValueError:
                    continue
                kind = event.get("type")
                if kind in _NOT_SECTIONS or "data" not in event:
                    continue
                sections[kind] = event["data"]  # the last (enriched) version wins
                arrived[kind] = round(time.monotonic() - started, 2)
    return {
        "id": entry["id"],
        "note": entry.get("note", ""),
        "latency_s": round(time.monotonic() - started, 2),
        "section_latency_s": arrived,
        "sections": sections,
        "usage": usage,
        "totals": _totals(usage, prices),
    }


async def _run(args) -> Path:
    _configure_env(args)
    _seed()
    from app.agents.orchestrator import TravelOrchestrator
    from app.core import llm
    from app.core.config import settings

    prices = {
        **PRICES,
        **(json.loads(Path(args.prices).read_text()) if args.prices else {}),
    }
    entries = json.loads(Path(args.requests).read_text())
    if args.ids:
        wanted = set(args.ids.split(","))
        entries = [e for e in entries if e["id"] in wanted]
    orchestrator = TravelOrchestrator(agents_dir=settings.agents_dir)
    results = []
    for entry in entries:
        print(f"→ {entry['id']} …", flush=True)
        result = await _run_one(orchestrator, entry, prices)
        print(
            f"  {result['latency_s']}s, {result['totals']['calls']} calls, "
            f"${result['totals']['cost_usd']:.4f}",
            flush=True,
        )
        results.append(result)
    run = {
        "meta": {
            "label": args.label,
            "provider": llm.provider(),
            "model_agent": llm.model_for("agent"),
            "model_chat": llm.model_for("chat"),
            "thinking_agent": settings.gemini_thinking_agent,
            "thinking_chat": settings.gemini_thinking_chat,
            "search_keys": bool(args.keep_search_keys),
            "started": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "requests": results,
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{args.label}.json"
    path.write_text(json.dumps(run, indent=2, default=str))
    print(f"wrote {path}")
    return path


# ── compare ───────────────────────────────────────────────────────────


def item_list(data) -> list | None:
    """The section's main list of items, or None when it has none."""
    if not isinstance(data, dict):
        return None
    for key in _ITEM_KEYS:
        if isinstance(data.get(key), list):
            return data[key]
    for value in data.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
    return None


def is_valid(data) -> bool:
    """A usable section: a dict without an error whose items (if any) are dicts."""
    if not isinstance(data, dict) or data.get("error"):
        return False
    items = item_list(data)
    return items is None or all(isinstance(i, dict) for i in items)


def required_fields(data) -> set[str]:
    """Fields every item of the baseline section carries — the de facto schema."""
    items = [i for i in item_list(data) or [] if isinstance(i, dict)]
    if not items:
        return set()
    return set.intersection(*(set(i) for i in items))


def compare_section(a, b) -> dict:
    a_items, b_items = item_list(a), item_list(b)
    need = required_fields(a) if is_valid(a) else set()
    missing = Counter()
    for item in b_items or []:
        if isinstance(item, dict):
            missing.update(need - set(item))
    top_missing = sorted(
        k
        for k in (a or {})
        if k != "verification" and isinstance(b, dict) and k not in b
    )
    return {
        "valid": (is_valid(a), is_valid(b)),
        "items": (
            len(a_items) if a_items is not None else None,
            len(b_items) if b_items is not None else None,
        ),
        "missing_fields": dict(missing),
        "missing_top_level": top_missing if is_valid(a) and is_valid(b) else [],
        "verification": (_level(a), _level(b)),
        "error": (_error(a), _error(b)),
    }


def _level(data) -> str | None:
    if isinstance(data, dict) and isinstance(data.get("verification"), dict):
        return data["verification"].get("level")
    return None


def _error(data) -> str | None:
    if data is None:
        return "missing"
    if isinstance(data, dict) and data.get("error"):
        return str(data["error"])[:80]
    return None


def compare_runs(run_a: dict, run_b: dict) -> dict:
    by_id_b = {r["id"]: r for r in run_b["requests"]}
    rows = []
    for req_a in run_a["requests"]:
        req_b = by_id_b.get(req_a["id"])
        if req_b is None:
            continue
        names = sorted(set(req_a["sections"]) | set(req_b["sections"]))
        rows.append(
            {
                "id": req_a["id"],
                "latency_s": (req_a["latency_s"], req_b["latency_s"]),
                "cost_usd": (req_a["totals"]["cost_usd"], req_b["totals"]["cost_usd"]),
                "tokens": (req_a["totals"], req_b["totals"]),
                "sections": {
                    n: compare_section(
                        req_a["sections"].get(n), req_b["sections"].get(n)
                    )
                    for n in names
                },
            }
        )
    return {"a": run_a["meta"], "b": run_b["meta"], "requests": rows}


def _fmt_pair(pair, fmt="{}") -> str:
    return " → ".join("—" if v is None else fmt.format(v) for v in pair)


def _usage_by_label(run: dict) -> dict:
    per = defaultdict(Counter)
    for req in run["requests"]:
        for rec in req["usage"]:
            c = per[rec.get("label", "?")]
            c["calls"] += 1
            for k in ("input_tokens", "output_tokens", "thinking_tokens"):
                c[k] += rec.get(k, 0)
    return per


def render_report(diff: dict, run_a: dict, run_b: dict) -> str:
    a, b = diff["a"], diff["b"]
    lines = [
        f"# LLM eval: {a['label']} → {b['label']}",
        "",
        f"- **A** `{a['label']}`: {a['provider']} · agent `{a['model_agent']}` · "
        f"chat `{a['model_chat']}` · thinking {a.get('thinking_agent')}/{a.get('thinking_chat')}",
        f"- **B** `{b['label']}`: {b['provider']} · agent `{b['model_agent']}` · "
        f"chat `{b['model_chat']}` · thinking {b.get('thinking_agent')}/{b.get('thinking_chat')}",
        "",
        "## Per search",
        "",
        "| Request | Cost (USD) | Latency (s) | Calls | Output+thinking tokens |",
        "|---|---|---|---|---|",
    ]
    for row in diff["requests"]:
        ta, tb = row["tokens"]
        lines.append(
            f"| {row['id']} | {_fmt_pair(row['cost_usd'], '{:.4f}')} | "
            f"{_fmt_pair(row['latency_s'])} | {ta['calls']} → {tb['calls']} | "
            f"{ta['output_tokens'] + ta['thinking_tokens']} → "
            f"{tb['output_tokens'] + tb['thinking_tokens']} |"
        )
    n = max(len(diff["requests"]), 1)
    cost_a = sum(r["cost_usd"][0] for r in diff["requests"]) / n
    cost_b = sum(r["cost_usd"][1] for r in diff["requests"]) / n
    lines += ["", f"Mean cost per search: **${cost_a:.4f} → ${cost_b:.4f}**", ""]

    # Section summary across requests
    summary = defaultdict(
        lambda: {
            "valid": [0, 0],
            "items": [[], []],
            "levels": [Counter(), Counter()],
            "n": 0,
            "missing": Counter(),
        }
    )
    for row in diff["requests"]:
        for name, sec in row["sections"].items():
            s = summary[name]
            s["n"] += 1
            for side in (0, 1):
                s["valid"][side] += int(sec["valid"][side])
                if sec["items"][side] is not None:
                    s["items"][side].append(sec["items"][side])
                if sec["verification"][side]:
                    s["levels"][side][sec["verification"][side]] += 1
            s["missing"].update(sec["missing_fields"])
    lines += [
        "## Per section (all requests)",
        "",
        "| Section | Valid | Mean items | Verification | B items missing A's fields |",
        "|---|---|---|---|---|",
    ]
    for name in sorted(summary):
        s = summary[name]
        means = [f"{sum(v) / len(v):.1f}" if v else "—" for v in s["items"]]
        levels = [
            ", ".join(f"{k} {v}" for k, v in sorted(c.items())) or "—"
            for c in s["levels"]
        ]
        missing = ", ".join(f"{k} ×{v}" for k, v in s["missing"].most_common(5)) or "—"
        lines.append(
            f"| {name} | {s['valid'][0]}/{s['n']} → {s['valid'][1]}/{s['n']} | "
            f"{means[0]} → {means[1]} | {levels[0]} → {levels[1]} | {missing} |"
        )

    problems = []
    for row in diff["requests"]:
        for name, sec in sorted(row["sections"].items()):
            if sec["valid"][0] and not sec["valid"][1]:
                problems.append(
                    f"- `{row['id']}` / **{name}**: B invalid ({sec['error'][1]})"
                )
            elif sec["missing_top_level"]:
                problems.append(
                    f"- `{row['id']}` / **{name}**: B lacks "
                    + ", ".join(f"`{k}`" for k in sec["missing_top_level"])
                )
    lines += ["", "## Regressions (valid in A, not in B)", ""]
    lines += problems or ["None."]

    lines += [
        "",
        "## Tokens by call label (totals over all requests)",
        "",
        "| Label | Calls | Input | Output | Thinking |",
        "|---|---|---|---|---|",
    ]
    ua, ub = _usage_by_label(run_a), _usage_by_label(run_b)
    for label in sorted(set(ua) | set(ub)):
        ca, cb = ua.get(label, Counter()), ub.get(label, Counter())
        lines.append(
            f"| {label} | {ca['calls']} → {cb['calls']} | "
            f"{ca['input_tokens']} → {cb['input_tokens']} | "
            f"{ca['output_tokens']} → {cb['output_tokens']} | "
            f"{ca['thinking_tokens']} → {cb['thinking_tokens']} |"
        )
    return "\n".join(lines) + "\n"


def _compare(args) -> Path:
    run_a = json.loads(Path(args.run_a).read_text())
    run_b = json.loads(Path(args.run_b).read_text())
    report = render_report(compare_runs(run_a, run_b), run_a, run_b)
    out = Path(args.out) if args.out else Path(args.run_b).with_suffix(".md")
    out.write_text(report)
    print(f"wrote {out}")
    return out


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run saved searches on one provider/model")
    run.add_argument("--provider", choices=("gemini", "anthropic"), default="gemini")
    run.add_argument("--label", required=True, help="run name (output file stem)")
    run.add_argument("--requests", default=str(_DEFAULT_REQUESTS))
    run.add_argument("--ids", help="comma-separated request ids (default: all)")
    run.add_argument("--out", default=str(_DEFAULT_OUT))
    run.add_argument("--project", default=_DEFAULT_PROJECT)
    run.add_argument("--location", default="global")
    run.add_argument("--model-agent")
    run.add_argument("--model-chat")
    run.add_argument("--thinking-agent", choices=("minimal", "low", "medium", "high"))
    run.add_argument("--thinking-chat", choices=("low", "medium", "high"))
    run.add_argument("--prices", help="JSON file {model: [in, out]} per 1M tokens")
    run.add_argument("--data-dir", help="seeded DATA_DIR to reuse")
    run.add_argument("--keep-search-keys", action="store_true")
    cmp_ = sub.add_parser("compare", help="diff two runs into a Markdown report")
    cmp_.add_argument("run_a", help="baseline run JSON")
    cmp_.add_argument("run_b", help="candidate run JSON")
    cmp_.add_argument("--out", help="report path (default: <run_b>.md)")
    args = parser.parse_args(argv)

    if args.cmd == "run":
        if os.environ.get("CI"):
            sys.exit("llm_eval run calls a paid model API — not in CI")
        asyncio.run(_run(args))
    else:
        _compare(args)


if __name__ == "__main__":
    main()
