# iOS Phase 3-6 follow-ups

Source: the iOS build ledger (`.superpowers/sdd/2026-11-11-ios-app/progress.md` in `rupakc/travel-planner-ios`). Phases 3 (alerts 2.0), 4 (share links 2.0), 5 (Social, Play) and 6 (notifications, near-you) are adopted on iOS; this lists what was deferred, grouped by area. Plan: `2026-11-13-ios-phase3-6-adoption.md`.

## Owner-blocked (Wave 7, skipped by directive)
- Apple signing, TestFlight and App Store listing need the owner's Apple developer account.
- APNs push stays inert (no key); Firebase is configured for Android only. Local reminders and the near-you notifier work without it.
- No release build or distribution until the above exist.

## Product gaps
- Trips UI: deferred in the first wave. Read the additive notes in `docs/Trips-API.md` when adopting: non-Latin place keys get an 8-hex hash suffix, new `404 offline_pack_disabled`, place `visited_at` never clears (use `visited`).
- No Recap screen, so the Recap share entry is not built (`ShareTarget.recap` exists).
- `SuggestionsSheet` (Phase 3) has no entry point yet.
- No quick-watch or alerts-tab create path beyond the data layer and Watch taps; fare-calendar re-plan and "Watch these dates" not built.
- Social: no forget-save UI, no avatars, home country cannot be cleared (contract has no null), opponent picker accepts a typed handle only.
- Settings lacks delete account, data export, logout-all, sessions, avatar, `hide_game`, units and server settings sync.
- Near you: Android shipped personalized near-you text (#116, non-grounded v1 `/nearby`, generic fallback); iOS not yet. The device "Near me suggestions" switch UI is unconfirmed; throttle is in-memory; no purge of `nearby-` state at sign-out; `nearby_notif_post` telemetry not added.
- Import (T23): no map in review, Picker for unplaced spots, no import-failure telemetry event.
- Search/plan: cheaper hotels shows top 3 only (no section replace, no "Show only what fits"); Undo is a card button; Re-check sends the itinerary only; PlanDetail itinerary draft; plan notes edited in a sheet; share token path unescaped, remix intent lost after sign-in, AppRouter clears `sharedToken` on `.tab`.
- Stats: chart accessibility descriptor, `dismissResetNotice` never called, analytics window fixed at 30 days; reminders use device-local time.
- Plans cache and detail files stay on disk after sign-out (read-guarded per user); offline detail only for plans opened online.
- Hidden Explore modes keep streams alive; changing language rebuilds the auth gate and drops form input; 401 uses the generic login copy.

## i18n (English-only pending keys)
- Strings in `i18n/pending/en/` (social, play, share, sections.commerce, pace/validation, onboarding 9 keys, T30/T35/T36/T37 strings) are English in other languages until a web PR promotes them; hub history and open-matches copy shows English in de/hi.
- `ai_limit` / `ai_billing` catalogue keys are missing (web has none); iOS falls back to the backend detail text. A small web `mobile.json` PR would fix it.
- Home airport is saved as `current_residence` (no home-airport field).

## Backend and contract asks to this repo
- Freeze the Play resumed-session answers shape and the `GET /play/history` wrapper in `docs/Social-API.md`.
- Quick-watch `404` handling on iOS relies on detail text; add a stable `code` (R17). `ErrorMapping` drops codes on 403/404; an additive `code` is needed on those.
- Wanted: home-country null/clear in the profile contract; `live_prices_off` (503) path is untested on iOS.

## UI and snapshots
- iPhone Explore tab renders blank in hosted snapshots (verify on device); iPhone/iPad shell snapshots were dropped (T20).
- `PasteButton` is blank in hosted snapshots (real on device).
- Share canvas heights are measured constants pinned to the CI simulator; some snapshots keep a blank canvas tail (packing about 242 pt, loading/error states).
- AX5 snapshot names render at the accessibility1 cap (names misleading); AX5 VButton group label sizes differ (German "Ablehnen" vs "Annehmen"); plan-se-de-xxxl time range wraps at the en dash and Teilen/Export pills differ in height.
- Faint tick on selected `VChip` ends (picks-se-dark); Import example pills wrap tight; tight 10 pt gap in the "Create a profile" card; SlotRow Move/Edit/Plan buttons stack with large gaps at SE width.
- Snapshot precision tolerance hides small changes (accent curve and border changes produced no diffs): tighten, re-record and view.
- `FeatureSettings` keeps its own `WrapLayout` copy; `playField()` duplicates `prefsField`; remaining `Capsule().strokeBorder` uses should move to `borderedSurface`; `SectionCard` accent stripe is a flat bar vs web's curved left border.
- Disabled Share button readability (fixed in #47; keep an eye on other disabled styles).

## Tests and infra
- App-hosted Keychain test (real SecItem with an entitlement) not written; SPM test bundles cannot carry entitlements. ConsentCard real-gate test gap (`TimeZone.current` vs `core.zoneIdentifier`).
- `PaletteTests` 240 s CoreUI stall recurred three times; a guard landed in #64, watch for recurrence. `Nearby test_neverPersisted` flaked twice (fixed in #49, #51).
- `ui-smoke` runner flakes (simulator warm-up timeouts, `LaunchTests` hangs, runs cancelled without steps) need reruns; a retry that reboots or erases the simulator on warm-up timeout was not built (watchdog is 600 s).
- Generated L10n `Keys.swift` / `xcstrings` conflict on every rebase (consider a merge driver or regenerate-on-CI).
- Stub backend gaps: `phase4.py` lacks legacy `DELETE /plans/{id}/share` and `legacy_plan_shares`; response shapes were guessed in places.
- Minor: `ChatThreadStore` `hasSwitched`/`isReady` design; unsaved in-memory threads lost on quit; the tee-flush race and FontRegistry readiness signal.
