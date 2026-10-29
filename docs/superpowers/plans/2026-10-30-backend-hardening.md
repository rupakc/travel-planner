# Backend Hardening: Exact Reference Lookups + Rate Limiting — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** (1) Reference-table lookups (visa, destination scores, emergency numbers, anything using `_match_destination` / `_find_dest_key` in `backend/app/agents/static_results.py`) match only the right row, so "Verified" labels and Travel Ease scores can't come from a wrong row. (2) Expensive endpoints are rate-limited per user (or per client IP when anonymous) with a clear 429 + `Retry-After`, and the frontend shows a friendly message.

**Architecture:** A shared normaliser turns a destination string ("Barcelona, Spain", "BCN — Barcelona, Spain", "tokyo") into candidate place tokens (city, country) and lookups compare whole tokens against table keys and the city→country map — no substring matching in either direction. A small in-process sliding-window limiter (`backend/app/core/rate_limit.py`) is applied as a FastAPI dependency on expensive routes; limits come from settings; cache hits still count (simplicity) but limits are generous.

**Spec:** Follow-ups from the 2026-10-29 reviews ("fuzzy static lookups", "no rate limiting anywhere"). Design choices are Claude's (user delegated).

## Design (binding)

Lookups:
- `normalise_place(destination) -> {"city": str|None, "country": str|None, "tokens": set[str]}`: lowercase; strip an IATA prefix like "BCN — "; split on commas; first segment = city (or country if it is itself a known country key); last segment = country when ≥2 segments; tokens = whole words/phrases of those segments.
- A table key matches when it equals the normalised city, the normalised country, or the country mapped from the city via the existing city→country map (merge the two duplicated maps in `_find_dest_key` and `_match_destination` into ONE module-level map). Never `key in dest` / `dest in key`.
- Nationality matching for `_VISA_TABLE`: exact match of the normalised nationality (lowercase, trimmed; accept the demonym forms already used in the table) — no substring (`tbl_nat in nat` is removed).
- Behaviour for every currently-correct input must not change: build a regression test over all existing table keys and a list of realistic inputs (city, "City, Country", "IATA — City, Country", country alone, mixed case) asserting the same row as before; plus negative tests that used to match wrongly (e.g. a destination containing a table key as a substring of another word, "Indian" vs "American Indian"-style nationality substrings, short keys like "uk" inside "ukraine", "india" inside "indiana", "niger" inside "nigeria").

Rate limiting:
- Sliding-window counter per key `user:<username>` or `ip:<client host>`; in-memory, thread-safe enough for asyncio (single process); old timestamps pruned.
- Settings (pydantic-settings, env overridable): `rate_limit_enabled: bool = True`, and per-bucket limits: `search` 10/10min (POST /api/search, /api/search/sync), `chat` 30/10min (POST /api/chat), `compare` 30/10min (POST /api/compare/destination), `discover` 10/10min, `light_ai` 60/10min (POST /api/stress-test, /api/{flights,hotels,activities}/filtered and other single-agent POST routes in main.py that call an LLM).
- Over the limit → HTTP 429, JSON `{"detail": "Too many requests — please wait N seconds and try again."}`, header `Retry-After: N`.
- Tests: conftest disables limiting by default (env `RATE_LIMIT_ENABLED=false`) so existing tests are unaffected; dedicated tests enable it via settings override and assert 429 + Retry-After after N+1 calls, separate users don't share buckets, window expiry (inject a clock).
- Frontend: wherever these calls surface errors — `frontend/src/workers/sseWorker.js` / `services/api.js` streamSearch error path, chat worker, compare (`compareErrorReason` already shows string `detail`), axios helpers — a 429 shows the server's `detail` string (no raw JSON). Add/extend unit tests where a helper exists.
- Docs: CLAUDE.md (API section note), docs/API-Reference.md (429 behaviour + limits), docs/Configuration.md (settings).

Non-goals: distributed rate limiting, per-plan quotas, changing table contents.

## Global Constraints
- No new dependencies. Backend `python3 -m pytest -q` + ruff (CI config); frontend vitest/eslint/build if touched. Never call network/LLM in tests.

---

### Task 1: Exact reference lookups
Files: `backend/app/agents/static_results.py`, new `backend/tests/test_static_lookups.py`.
- [ ] Regression snapshot test first (current behaviour on realistic inputs), negative tests, then implement, full suite, commit `fix(static): exact place and nationality matching for reference tables`.

### Task 2: Rate limiting
Files: new `backend/app/core/rate_limit.py`, `backend/app/core/config.py`, route modules / `main.py` wiring, `backend/tests/conftest.py`, new `backend/tests/test_rate_limit.py`, frontend error surfacing, docs.
- [ ] Tests first, implement, full suites, commit `feat(api): per-user rate limits on AI endpoints`.
