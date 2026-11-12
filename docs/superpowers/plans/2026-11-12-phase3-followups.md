# Phase 3 follow-ups (from the Task 21 browser run)

Severity: minor unless noted. None blocks the release.

- Drawer "Watch price" button (My Plan card) still shows the un-watched eye-off state for a hotel that is already watched via one-tap; the results card shows "Watching". Make the drawer card read the same watch state.
- Alerts header: after Deal hunter is earned, the track still says "Next badge: Deal hunter, 1 of 1". Show the all-done line when the badge is earned.
- Drop moment shows "+15 XP" (the deal_drop award) while the notification's `game.xp` is 25 (award plus badge). Decide which number the card should show; today the card omits the badge bonus.
- `SavingsShareCard` picks light/dark from `prefers-color-scheme`, not the app theme toggle, so the PNG can mismatch the page.
- A hotel watch whose property cannot be found shows both "Getting today's price" and "Sold out for your dates" (pending_first_check true while the check says unavailable). Prefer the unavailable state only.
- Price story chart: keyboard scrubbing supports the arrow keys only; Home/End do nothing. Add them (jump to first/latest check).
- `/api/config` is served with `max-age=300`, so after a server restart without `SERPAPI_KEY` the SPA keeps `live_prices: true` for up to 5 minutes (by design; noted for the runbook).
- The first automatic drop card after a load was once skipped while `tp_drop_seen` already held the id (not reproduced; later loads showed the card every time). Watch for it.
- Not covered end to end: a hotel/activity drop (the fake serves the hotel fixture at one price).

## From the final review and task reviews

Severity in brackets.

- [low] Several drops for one user dispatched in the same scheduler pass, before the first kicked flush has claimed anything, can each go out as a separate push seconds apart (`alert_delivery` grouping relies on `sent_at`).
- [low] `push._locks` is keyed by event loop and each `flush` pass runs in a new loop, so entries accumulate (about 24 a day, cleared by the weekly reboot). Use a `WeakKeyDictionary`.
- [low] `alert_outbox` and `alert_digests` are never pruned; the 180-day notification prune leaves their rows (saving-title lookups then fall back to an empty title).
- [low] `alert_digest.build_digest` labels the week from the UTC `now` while the claim uses the local ISO week (cosmetic, zones far east of UTC).
- [low] `POST /api/alerts/quick-watch` is not gated on `price_alerts_v2_enabled`.
- [note for owner] With v2 on, re-check cadence is daily; legacy was every 12 h. Decide whether that is the intended trade for the SerpAPI budget.
- [low] A grouped push's `data.kind` is the last row's kind, so the Android channel and priority follow it (T6).
- [low] A crash after claiming an outbox row loses it, and a send failure after the digest claim loses that week's digest (claim-before-send, no retry).
- [low] `alerts_db` uses `datetime.utcnow()` (deprecated); price_watch kind default is `hotel` (T1).
- [low] `_is_legacy` does one query per outbox item (T6); N+1 saving-title lookup (T5).
- [low] Advice cache is not keyed by locale; `now()` is not injectable in `alert_story` (T4).
- [low] Quick-watch: `_pending_spec` is in `serialize`, `_pending_expiry` accepts a past date, the first look is not de-duplicated, and tests use a fake source with kind `hotel` (T7).
- [low] `alert_schedule._starved` swallows a `TypeError` silently; a duplicate assert in a restored test (T8).
- [low] Digest: missing tests noted in T10 review.
- [low] Savings share card: round the total, focus trap/restore in the dialog, canvas text wrap, hard-coded tick values (T13).
- [low] Price story: the slider thumb hit area is under the 44 px tap target (T11); Prefs: quiet-hours notice wording and focus styles (T16).
- [low] The `es` Deal-hunter badge name needs a native check (T5); redundant `SHELL_NS` listing (T2).
- [low] `fare_cheaper_date` no longer counts as a caught drop (fixed in #161); no follow-up needed.

## Owner must provide

- A `SERPAPI_KEY` in `app.env` for live prices. None is set in prod today, so `features.live_prices` stays false and one-tap watching and suggestions stay hidden until it is.
- Optional SMTP settings for the weekly digest email.
- Android and iOS clients to adopt `docs/Alerts-API.md`.
