# Phase 6 follow-ups

Severity: minor unless noted. The final opus review found no blockers. Its should-fix items and several minors were fixed in the review-fix PR (T-1 window, `category`/`plan_id` on price drops, web bell links and icons for `trip_*` kinds, FCM no longer sees iOS tokens, stale timer, invalid timezone, send windows, day counts in text, APNs prune rule, stuck `sending` rows, export of `notify_log`).

## Needs the owner
- Apple key: `APNS_TEAM_ID`, `APNS_KEY_ID`, `APNS_KEY_P8` (or `APNS_KEY_FILE`), `APNS_BUNDLE_ID` (default `io.github.rupakc.travelplanner`), `APNS_SANDBOX` for TestFlight/debug builds. Until then APNs is inert; verify once with a real device on the sandbox host.
- FCM credentials are the existing ones; production has none today, so category pushes create in-app rows only.

## Deferred by ruling
- Live weather-change push (needs a polling budget; today's weather lines come from the stored snapshot).
- Web push (VAPID) for the SPA.
- `social` and `quiz` senders (categories exist and are stored; Phase 5 adds senders).
- On-device "near you" notifications are an app task (iOS/Android) using `GET /notifications/catalog` templates and `/nearby`; web has no geofencing.
- Morning-brief weather and tip lines are English-only (they come from the English snapshot and static tables).

## Minor
- `_candidates` in `trip_pushes.py` loads up to 500 full plans every 5 minutes; select only the needed columns and order by distance to today if users grow.
- The web Notifications section has no "use my timezone" button (the alerts prefs panel has one).
- `notify_db._now` uses `datetime.utcnow()` (deprecated).
- Android: confirm how the app handles taps on `trip_*` kinds and an empty `plan_id` before it adopts the contract.
- Add a `notify_log` daily analytics rollup (sent/held/dropped by category) if tuning of defaults is wanted.
