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

## i18n
- The pending English-only keys are translated in all 7 languages (web PRs #230, #231, #232; iOS PR #79); `i18n/pending` is empty (only `.gitkeep`).
- The translations need a native-speaker review (owner).
- `ai_limit` / `ai_billing` catalogue keys are still missing (web `frontend/src/i18n/locales/en/*.json` has none); iOS falls back to the backend detail text. A small web `mobile.json` PR would fix it.
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
- macOS runner capacity ("job was not acquired by Runner") cancels jobs with zero steps; fix: `gh run rerun --failed`.
- `ui-smoke` runner flakes (simulator warm-up timeouts, `LaunchTests` hangs, runs cancelled without steps) need reruns; a retry that reboots or erases the simulator on warm-up timeout was not built (watchdog is 600 s).
- Generated L10n `Keys.swift` / `xcstrings` conflict on every rebase (consider a merge driver or regenerate-on-CI).
- Stub backend gaps: `phase4.py` lacks legacy `DELETE /plans/{id}/share` and `legacy_plan_shares`; response shapes were guessed in places.
- Minor: `ChatThreadStore` `hasSwitched`/`isReady` design; unsaved in-memory threads lost on quit; the tee-flush race and FontRegistry readiness signal.

## Final review residuals (2026-11-19)
Source: the iOS final whole-branch review (written against iOS `38d0739`; B1, M1-M11 and the #80 follow-ups are fixed or in review). Each item re-checked against iOS `origin/main` (`372b32e`); paths are under `Packages/VoyagerKit/Sources/`. 18 of the 19 Minors are still open (Minor 3 is fixed).
- B1 (price story never loads): fixed in open PR #73 and on `origin/test/phase-smoke` (`FeatureAlerts/WatchCard.swift:43` starts the load); on `origin/main` `FeatureAlerts/Slots/WatchCardSlot.swift:17` still has the dead `.task`. Merge #73 before release.
- Minor 1: failed alert-prefs read becomes nil, so the poller skips quiet hours, `targets_only` and caps (`NotificationsCore/BackgroundTasks.swift:74`); return nil (wait) when `hasAlertsV2` and the read throws.
- Minor 2: hard-coded punctuation in localised strings (`FeatureAlerts/Story/PriceStoryView.swift:148`, `Savings/DropMomentCard.swift:45`, `Savings/DigestRow.swift:26,92` colours by `hasPrefix("−")`); use catalogue templates and colour by sign of the number.
- Minor 4: dead `.priceStory` route (`AppShell/AppRouter.swift:87`) falls to the `EmptyState` default (`AppShell/TabRoots.swift:120`); map to `AlertsRootView` or remove.
- Minor 5: "server push live" uses the account-wide device count, which includes Android (`NotificationsCore/ReminderPolicy.swift:26`, `BackgroundTasks.swift:75`); gate on this device's own APNs registration (Major once `features.apns` is on).
- Minor 6: cold-launch tap routes before `/config` loads (`NotificationsCore/BackgroundTasks.swift:167-168`, `clientConfig?.journeyAvailable ?? false`); wait for deferred start.
- Minor 7: sign-out race, an in-flight `refresh` can reschedule the old user's reminders after the purge (`NotificationsCore/TripReminderScheduler.swift:109-119`, `accountChanged` :129-131); re-check the user before `reschedule`.
- Minor 8: failed first catalogue fetch returns English for any locale (`VoyagerEnv/Phase6/NotificationCatalogCache.swift:41`); return bundled only for `.en`, else nil to use the localised fallback.
- Minor 9: Quiz category switch never shows and quiz rows are always dropped (`FeatureSettings/Notifications/NotificationSettingsModel.swift:46`, `NotificationsCore/BackgroundTasks.swift:69`; `hideGameSetting` is nil); treat nil as visible, let `403 game_hidden` hide it.
- Minor 10: shared card period shows raw `YYYY-MM` (`FeatureShare/Viewer/SharedCardBody.swift:41`); format as localised month and year.
- Minor 11: missing quiz session shows as a retryable error (`VoyagerData/Phase5/Phase5Repositories.swift:438`, matches "session" but the backend says "Quiz not found."); also match "quiz".
- Minor 12: Play hub reloads on every appear (`FeaturePlay/PlayHomeView.swift:35`, `H2H/H2HMatchView.swift:34`; `PlayHomeModel.load` :55 has no in-flight guard; `onAppear` is now gated by `needsRefresh`); guard with `didStart` and a generation counter.
- Minor 13: "See result" does nothing until the summary arrives (`FeaturePlay/Quiz/QuizModel.swift:166-172,197`); set `result` after the summary, or make `next()` wait.
- Minor 14: block from the feed fails silently and sends no `social_block` (`FeatureSocial/Feed/FeedModel.swift:217` `catch {}`, `Feed/IdeaActions.swift:53-56`); show the failure and emit `.socialBlock(on: true)`.
- Minor 15: profile editor offers game switches after `403 game_hidden` (`FeatureSocial/Profile/ProfileEditorModel.swift:79` ignores `env.play.isHiddenByServer`); treat it as hidden.
- Minor 16: "Create a profile" prompt stays after a profile is created (`FeatureSocial/Feed/FeedModel.swift:68-74,133`, `loadProfile` only in first `start()`); re-check in `load()` or on editor save.
- Minor 17: private profile joins the board but shows "unranked" forever (`FeaturePlay/Boards/BoardModel.swift:59-62,109-116`); explain the profile must be visible and link to the editor.
- Minor 18: untranslated Social errors `text_invalid`, `snapshot_too_large`, `handle_rate_limited` fall back to backend English (`FeatureSocial/Feed/IdeaFailure.swift:46-61`; `email_unverified` is now mapped; `social:errors.handle_rate_limited` exists); map them to existing keys.
- Minor 19: Preferences save 422s when the traveller total is above 20 (`FeaturePreferences/PreferencesModel.swift:90,101,159` caps per group only, backend `le=20`); cap the total in `setCount`.

Rulings and deferred:
- Like/save state can drift between the idea detail screen and the feed until a refresh (deferred).
- M7 caveat: once APNs push is live (`features.apns`), the local trip-reminder switch (`env.device.reminderOptIn`, checked at `NotificationsCore/TripReminderScheduler.swift:104`) will not silence server-sent trip rows; revisit with Wave 7.
- `reminderOptIn` defaults to false (`VoyagerEnv/DeviceSettings.swift:88`, `defaults.bool`): intentional opt-in.
- Intended behaviour, no change: Compare horizontal scroll at SE width, the AX5 VButton label cap, the "Getting today's price…" copy.
- iPad portrait: `AppShell/SidebarShell.swift` switches column visibility to `.doubleColumn` / `.detailOnly` in portrait (PR #73, not yet on `origin/main`). Rotating to landscape while `.detailOnly` keeps the detail-only view until the next selection; check on a device.
