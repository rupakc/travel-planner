# Phase 0 follow-ups (deferred during execution)

Collected from the Phase 0 execution ledger. Each item is assigned to a later phase or left open; pick it up in that phase's plan.

- Task 1-2: minor (deferred): int props unbounded (clamp to ±2**53)
- Task 1-2: minor (deferred): uuid.UUID accepts non-canonical forms; store str(UUID(v))
- Task 1-2: minor (deferred): rollup_day raises ValueError on malformed day (internal caller only)
- Task 4: minor (deferred): dark theme-color #121a2b duplicated literal in index.html/test vs tokens.dark.white
- Task 4: minor (deferred): dark field rule catches input[type=file|submit|button|reset]
- Task 4: minor (deferred): ThemeContext imports whole tokens.json (~15KB) for one value
- Task 4: minor (deferred): vitest-environment comment not on line 1
- Task 7: minor (deferred): zh-TW/HK/MO/Hant detected as Simplified; skip to next preference
- Task 7: minor (deferred): zh nav.alerts 提醒 → 价格提醒
- Task 7: minor (deferred): es/fr nav.admin English loanword
- Task 7: minor (deferred): catalog test forbids _zero and ties to Node CLDR version; add comment
- Task 3: minor (deferred): unsupported Content-Encoding → 422 (415 conventional); gzip trailing data ignored
- Task 3: minor (deferred): to_thread maintenance continues after cancel; comment
- Task 3: minor (deferred): live 'today' figures double-count sign-in mid-day; docstring says exact
- Task 3: minor (deferred): _MAX_CATCHUP_DAYS 120 > retention 90
- Task 3: minor (deferred): retention ≤7 days would let trailing re-roll wipe aggregates — clamp window to retention or validate retention ≥ 8
- Task 3: minor (deferred): new telemetry tests emit a starlette TestClient import DeprecationWarning (check if pre-existing pattern)
- Task 8f: minor (deferred): es tours.topPick "Top" → "Destacado"
- Task 8h: minor (deferred): admin.tab-Users/Feedback data-tid capitals
- Task 6: minor (deferred): verify CSS vars in SVG attrs (Sparkline) with an Alerts screenshot with history
- Task 6: minor (deferred → Phase 2): Results top bar slate gradient and Feedback pill read as light bands in dark
- Task 5: minor (deferred): 413 drops whole batch (max_batch 50, acceptable)
- Task 8i: minor (deferred → Phase 4 sharing): download fallback weak (data: window.open blocked); use toBlob+objectURL / navigator.share({files}) / inline img — Phase 4 rebuilds share cards anyway
- Task 5: minor (deferred): vite.config builds '+' then client sanitises to '_' — write '_' directly; add test for requeue of failed hide-flush events; no flush rescheduled after hide-flush failure
- Task 10: minor (deferred → T12): PRIVACY_POLICY_URL is a GitHub blob URL (404 until merge; self-hosters) — revisit with custom domain / /privacy route in Phase 1
- Task 11: minor (deferred): SPA always sends locale incl. en (backend treats as absent); docs could list which SPA calls send it
- Task 11: minor (deferred): free-time detection English-only (no slot category enum); live-model obedience to locale unverified → run llm_eval with locale=de before Phase 2 UI relies on it
- Task 8j: minor (deferred → later cleanup): dead chat enum.* keys; whatChanged joins with ", " in all languages (use Intl.ListFormat later); generatePlanName / cost breakdown labels English (stored names stay as generated)
- Task 9 zh: minor (deferred): TripDialogBody builds {{tail}} with ASCII punctuation → half-width in zh
- Ruling: minor 4 (lazy English namespaces) deferred to Phase 2 perf work — ~120 KB raw acceptable now
- Native-speaker review for hi, zh and bn (Task 9 reports flag specific strings).
- Dark-mode contrast of the muted hint, footer and nav text; mode tabs wrap on phones in de and bn; the Feedback pill overlaps form labels on phones (UX pass).
- "Travel Planner" vs "Voyager" naming (login heading).
- llm_eval run with locale=de: language obedience plus enrichment and verification hit rates.
- Lazy-load the English namespaces (about 120 KB raw).
- Policy link: PRIVACY_POLICY_URL points to a GitHub blob; switch it to a /privacy route or the custom domain.
