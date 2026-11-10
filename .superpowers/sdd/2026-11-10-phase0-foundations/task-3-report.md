# Task 3 report: telemetry API, config, maintenance, admin summary

Status: DONE. Branch `feat/p0-telemetry-api`, worktree `/Users/rupak/travel-planner/.claude/worktrees/agent-a99a032fb97b8c61b`.

## Base note
The named branch `worktree-agent-a3f9a87c636f1df59` still pointed at main (070a968); the Task 1+2 commits (up to e53629e) are on `feat/p0-telemetry-store`. I based my branch on e53629e.

## What was done
- `app/api/routes/telemetry.py`: `POST /api/telemetry` (404 when disabled; streamed 64 KB cap -> 413; gzip with 256 KB decompressed cap via bounded `zlib.decompressobj` -> 413; bad JSON/envelope/gzip/client block/over 100 events -> 422; per-event `clean_event`; event-level `screen` validated with registry `valid_id`, else NULL; `user_id` = `str(user["id"])`; insert via `asyncio.to_thread`; always 204 otherwise).
- `app/api/routes/client_config.py`: `GET /api/config`, `Cache-Control: max-age=300`, base URL from setting or request.
- `app/telemetry/maintenance.py`: `maintain_once(now)` (rolls up days after last rollup through yesterday UTC; first run backfills 7 days; catch-up capped at 120 days; prunes past retention; logs, never raises) and `telemetry_maintenance()` hourly loop; started/cancelled in the lifespan.
- `telemetry_db.summary(days)` + `GET /api/admin/telemetry/summary` (admin, `days` 1-90).
- Settings `telemetry_enabled`, `telemetry_retention_days`, `rate_limit_telemetry=600`, `public_base_url`. `_bucket_limit` is a getattr on `rate_limit_<bucket>`, so the setting is the mapping.
- registry: added public alias `valid_id`.
- Docs: Configuration.md, API-Reference.md.

## TDD
RED: `tests/test_telemetry_api.py` failed at collection (no `app.telemetry.maintenance`; routes absent). GREEN after implementation; two test-authoring bugs fixed (test expected set missed 11-07; `/auth/me` has no `id`).
Final: backend suite 5644 passed, 1 skipped, 1 xfailed; `ruff check backend/` clean, `ruff format --check` clean; `mkdocs build --strict` OK; `test_analytics.py` untouched and passing.

## Concerns
- Rolled-up day `users`/`sessions` in the summary are the max per-event distinct count (lower bound), since the rollup stores distinct counts per event. Documented. Today's numbers are exact.
- `top_screens` is read from raw events (screen_view `route`), bounded by 90-day retention.
- Tests share the session `client` data dir, so telemetry tables are cleared per test instead of redirecting `data_dir`.
