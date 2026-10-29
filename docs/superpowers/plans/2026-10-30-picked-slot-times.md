# Times for Picked Itinerary Slots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Itinerary activities picked into My Plan (the "Plan" button → `selections.itinerary_slots`) carry their scheduled times, show them in the drawer, keep them correct after drag-and-drop moves, and export to the calendar/print at those times instead of fixed slot hours.

**Spec:** Follow-up surfaced on 2026-10-30. Choices are Claude's.

## Design (binding)
- Source of truth stays the scheduler (frontend/src/utils/schedule.js) over the arranged itinerary; picked entries store a snapshot `{ start_time, end_time, start_day_offset, end_day_offset, duration_hours }` taken from the scheduled slot at pick time (plus the existing fields).
- Keep them fresh: wherever `syncPlannedSlots` runs after layout changes (ResultsPage handlers), also refresh times from `scheduleDays(arrangeItinerary(...))`; also refresh when edits change? No — durations don't change with edits; only layout changes move times. Implement as `syncPlannedSlots(itinerarySlots, arranged, scheduledDays?)` or a sibling `syncPlannedSlotTimes(itinerarySlots, scheduledDays)`; pure + tested; return same array/objects when nothing changed.
- Drawer list (ResultsPage My Plan drawer itinerary slot rows, PlanViewModal slot list, SharePage itinerary_slots fallback): show "Day 2 · Afternoon · 13:30–16:00" when times exist (old saved plans without times render as today).
- Export/print fallback (planExport `planItineraryDays` itinerary_slots path, planPrint): when slots carry `start_time`/`end_time` (+ day offsets) use them; otherwise today's SLOT_HOURS behaviour (existing tests unchanged).
- ChatPage picks (no durations available) unchanged.
- Docs: Frontend.md one sentence.

## Global Constraints
No new deps; frontend vitest/eslint/build; backend untouched. Existing tests unchanged except where a picked-slot fixture now legitimately includes times (none expected).

---
### Task 1: Pick-time snapshot + sync helper (+tests)
### Task 2: Display + export/print fallback (+tests) + docs
