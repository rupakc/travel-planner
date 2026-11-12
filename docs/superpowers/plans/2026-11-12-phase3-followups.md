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
