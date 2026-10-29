# Timed Itinerary (Minute-Level Scheduling) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Every itinerary activity shows an estimated start–end time and the travel time from the previous stop; days that don't fit are flagged; times follow the user's drag-and-drop edits and flow into Timeline, calendar export, print, share and the Health Check re-check.

**Spec:** Backlog #18. Facts: research-16-18-9.md (#18 section) in the scratchpad. Choices are Claude's.

## Design (binding)

Options weighed: (a) LLM emits times — rejected: stale as soon as the user moves an activity, and unverifiable; (b) **deterministic client-side scheduler applied after `arrangeItinerary`** — chosen: one source of truth that re-runs on every edit; positions/keys (`<day>-<time_of_day>`) unchanged, so edits/notes/plan picks/.ics UIDs keep working.

Scheduler (pure `frontend/src/utils/schedule.js`, unit-tested, node env):
- `scheduleDays(days, edits = {}) -> days'` (new objects) adding to each slot `start_time` "HH:MM", `end_time`, `transit_from_prev: { minutes, mode: 'walk'|'transit', km } | null`, and to each day `schedule_warnings: string[]`.
- Bucket anchors: morning 09:00, afternoon 13:30, evening 18:30; slots ordered by existing rank (time_of_day order, odd slots by slotRanks rule — reuse helpers from itineraryLayout.js).
- Duration: `duration_hours` (finite, 0.25–12) else defaults morning 3h / afternoon 3h / evening 2.5h; edits don't change duration.
- Transit between consecutive slots: if both have finite lat/lng → km = haversine × 1.3; walk if km ≤ 1.5 (4.5 km/h), else transit (20 km/h + 10 min); minutes rounded up to 5; first slot of a day has no transit. Missing coords → `transit_from_prev: null` but scheduling assumes a 20-min buffer.
- start = max(anchor, prev.end + transit/buffer); end = start + duration.
- Warnings: start pushed > 45 min past its anchor → "<Activity> starts at 14:20 — later than planned"; day ends after 23:00 → "Day N runs past 23:00". Days with no standard slots untouched.
- Shared haversine: extract `haversineKm` from TripMap.jsx into `frontend/src/utils/geo.js` (TripMap imports it).

Wiring (renderers use `scheduleDays(arrangeItinerary(...).days, edits)`):
- ItinerarySection: row shows "09:00–12:00" under the time-of-day label; between rows a muted transit line ("🚶 12 min walk · 0.9 km" / "🚇 ~25 min by transit" / nothing when unknown); a per-day amber "Tight schedule" chip listing warnings; a one-line note "Times are estimates based on typical durations and distances."
- TimelineView: show times in each slot card.
- planExport.js (.ics): use `start_time`/`end_time` when present (fallback SLOT_HOURS unchanged → existing tests stay green); planItineraryDays returns scheduled days.
- planPrint.js, SharePage.jsx, PlanViewModal.jsx: show "09:00–12:00" next to time_of_day.
- Stress-test re-check payload (utils/stressTestPayload.js from the polish branch): include start/end/transit; backend `stress_test_agent._summarize_itinerary` prints `HH:MM–HH:MM` and transit minutes when present (backend unit test).
- Prompts: `.agents/itinerary.md` and `backend/app/agents/itinerary_agent.py` — require `duration_hours` on every slot and `lat`/`lng` on every slot that names a specific place (no other changes); backend fallback itinerary unchanged.
- ChatPage unchanged.
- Docs: Frontend.md, Agent-System.md one line.

## Global Constraints
No new deps. Existing itineraryLayout / planExport / planPrint tests must pass unchanged. Frontend vitest/eslint/build; backend pytest/ruff.

---
### Task 1: geo.js extraction + schedule.js (+tests)
### Task 2: Renderers (ItinerarySection, TimelineView, planExport, planPrint, SharePage, PlanViewModal) + stress payload/backend summary
### Task 3: Prompt tweaks + docs
