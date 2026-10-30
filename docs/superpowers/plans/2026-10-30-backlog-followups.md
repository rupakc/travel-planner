# Backlog Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Close the three backlog items surfaced during earlier reviews: chat plan saves keep live link evidence, the stress-test re-check payload describes travel from the wrong stop on out-of-order days, and chat-triggered full plans bypass the search rate-limit bucket.

**Spec:** User request 2026-10-30 ("let's address the earlier backlog items"). Choices are Claude's.

## Facts (verified)
- `frontend/src/utils/verification.js` exports `stripLinkEvidence(selections)` (drops `link_verified` / `link_checked` from every selected item). `ResultsPage.jsx:2538` applies it before saving; `ChatPage.jsx` saves plans at ~593 (`POST/PUT /api/plans`) and ~636 without it.
- `frontend/src/utils/stressTestPayload.js` `editedItinerary` maps `scheduleDays(arranged.days, edits)` slots in *listed* order. `scheduleDays` (`utils/schedule.js`) times slots in rank order (morning → afternoon → evening, slotRanks rule), so for a day listed [afternoon B, morning A] B's `transit_from_prev` is from A although A is listed after B. The backend stress-test prompt prints "(N min … from previous stop)" in listed order. The on-screen list already handles this (review of PR #14, "fix 2").
- Rate limiting (`backend/app/core/rate_limit.py`): `rate_limit(bucket)` is a route dependency; buckets search 10 / chat 30 / compare 30 / discover 10 / light_ai 60 per `RATE_LIMIT_WINDOW_SECONDS`. `/api/chat` carries only the `chat` bucket. The chat agent decides mid-stream (regex trip-planning detection → `planning_start`) to run the full specialist set, which costs as much as a search.

## Design (binding)
1. **Chat saves:** both ChatPage save paths send `stripLinkEvidence(selections)`; selections in state are not mutated. Test: a selection carrying `link_verified`/`link_checked` is saved without them (mock fetch, assert body).
2. **Re-check payload order:** in `editedItinerary`, emit each day's slots in the same order `scheduleDays` timed them (reuse its ordering helper — export it from `schedule.js` rather than duplicating), so `transit_from_prev` always refers to the slot listed immediately before. Days already in order are unchanged (existing tests stay green). `recheckFingerprint` follows the same order (it uses `editedItinerary`). Tests: [afternoon B, morning A] → payload [A, B], B's transit is from A, A has no transit; in-order day unchanged.
3. **Chat-triggered plans charge the search bucket:**
   - Add to `rate_limit.py` a reusable `try_consume(bucket, key) -> int | None` (returns Retry-After seconds when over the limit, else None; honours `RATE_LIMIT_ENABLED`) used by the existing dependency too (no duplicated logic), and expose the caller key computation for a request/user.
   - The chat route passes the caller key into the chat agent (or a callback). At the moment the agent commits to a full multi-specialist plan (just before `planning_start` / the specialist fan-out), it calls `try_consume("search", key)`. Over the limit → do NOT run specialists; stream a friendly `delta` ("You've planned several full trips in the last few minutes — try again in about N minutes, or ask me a quick question meanwhile.") then `done`, no `error` event, no 429 (the SSE response has already started). Under the limit → unchanged behaviour.
   - Knowledge-only chat answers and single-section specialist calls (if any) keep costing only the chat bucket — only the full-plan fan-out charges search.
   - Tests (rate limiting enabled in these tests with small limits): full plan under limit runs and consumes one search token; over limit streams the friendly delta + done and runs no specialist (assert agents not called); plain Q&A doesn't consume search tokens; the search endpoint and chat full-plans share the same per-caller budget.
4. **Docs:** API-Reference rate-limit section, Chat-Assistant page, Configuration (if wording mentions buckets), CLAUDE.md rate-limit paragraph — one sentence each that chat-triggered full plans also count against the search bucket.

## Global Constraints
No new deps; backend pytest + ruff; frontend vitest + eslint + build; no network in tests.

---
### Task 1: Chat saves strip link evidence (+test)
### Task 2: Re-check payload in scheduled order (+tests)
### Task 3: Chat full plans charge the search bucket (+tests) + docs
