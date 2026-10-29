# Itinerary Polish: Accessibility + Re-check Edited Plan — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** (1) Close the accessibility gaps left in the itinerary editor and Results section headers. (2) Let users re-run the Trip Health Check against their edited itinerary.

**Spec:** Follow-ups from the 2026-10-29 reviews. Design choices are Claude's (user delegated).

## Design (binding)

Accessibility:
- Results `SectionHeader` (frontend/src/pages/ResultsPage.jsx) is a clickable `div`: make the collapse toggle keyboard-operable — a real `<button>` for the title/toggle area with `aria-expanded` and `aria-controls` pointing at the section body id; the VerificationBadge chip and any `actions` stay outside that button (no nested interactive elements); clicking the chip must not toggle (keep the existing stopPropagation).
- ItinerarySection (frontend/src/components/ItinerarySection.jsx): per-row action buttons get accessible names including the activity — `Edit <activity>`, `Add note to <activity>` / `Edit note for <activity>`, `Add <activity> to plan` / `Remove <activity> from plan` (visible text unchanged); the Removed list's Restore buttons `Restore <activity>`.
- VerificationBadge: add the missing Shift+Tab-from-container test.

Health Check re-run:
- When `layoutChangeCount > 0`, StressTestSection shows, next to the existing note, a button **"Re-check my edited plan"**. It POSTs to `/api/stress-test` with the current search request plus `itinerary` = the ARRANGED itinerary (arrangeItinerary with edits applied: each slot's activity/location/cost use `itinerary_edits` overrides; removed activities excluded), and `flights`/`visa`/`weather` from current results (strip `verification` objects before sending).
- While running: button disabled with spinner ("Re-checking…"). Result replaces the displayed findings in place (do not mutate `results.stress_test`; keep a separate `recheck` state holding `{data, forLayoutFingerprint}`), with the heading note "Checked against your edited itinerary". If the layout or edits change afterwards, show "Your plan changed since this check — re-check again" and the button again.
- Errors (incl. 429): show the server's string `detail` or "Couldn't re-check — try again", keep the previous findings.
- `recheck` state clears on new search / loaded plan / Reset.
- Pure helper `buildStressTestPayload(searchData, results, selections)` in `frontend/src/utils/` with unit tests (arranged days, edits applied, removed excluded, verification stripped, return_date normalised via existing `apiReturnDate`).
- Docs: docs/Frontend.md Health Check paragraph.

Non-goals: auto re-check, chat.

## Global Constraints
- No new dependencies. Frontend `NODE_OPTIONS=--experimental-require-module npx vitest run`, eslint `--max-warnings 0`, build. Component tests createRoot + act.

---

### Task 1: Accessibility fixes
Files: ResultsPage.jsx (SectionHeader), ItinerarySection.jsx (+test), VerificationBadge.test.jsx.
- [ ] Tests first (button roles/aria-expanded toggle via keyboard Enter/Space on the header button; accessible names; Shift+Tab test), implement, commit `fix(a11y): keyboard section toggles and named itinerary actions`.

### Task 2: Re-check edited plan
Files: new `frontend/src/utils/stressTestPayload.js` (+test), ResultsPage.jsx StressTestSection + state, `frontend/src/services/api.js` (`recheckStressTest(payload, token)`), docs.
- [ ] Tests first, implement, commit `feat(itinerary): re-check the Health Check against your edited plan`.
