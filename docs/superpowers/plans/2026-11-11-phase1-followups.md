# Phase 1 follow-ups (accounts + game engine)

Deferred items from the Phase 1 run (plan `2026-11-11-phase1-accounts-game.md`). Each was reviewed and judged safe to ship without the fix. Grouped by area, most important first.

## Owner actions (before turning features on)

- **Sign-up is off until you opt in.** Native sign-up needs `SIGNUP_ENABLED=true` plus email delivery (SMTP). OAuth sign-up turns on per provider once its credentials are set. See `docs/Deployment-GCP.md` → "Sign-in providers and email".
- **Credentials to provide:** Google, GitHub, Facebook and Apple OAuth (client IDs/secrets; Apple Services ID, team ID, key ID, private key), SMTP host/user/password/sender. Register `<PUBLIC_BASE_URL>/api/auth/oauth/<provider>/callback` in each console. Run `infrastructure/gcp/bootstrap.sh` before adopting the new `SECRET_MANAGER_SECRETS` list.
- **Existing users and password reset.** Reset mail goes only to a verified address (or a pending sign-up). Admin-created users with an unverified email must confirm it once ("Send link") before self-service reset works. Consider an in-app prompt to confirm the address.
- **Mobile apps:** confirm the Android and iOS `/config` parsers ignore unknown keys (`auth`, `features.accounts`, `features.game`) and render `user.email: null`.

## Security hardening

- Rule-3 auto-link: a victim who clicks an unsolicited verify link gives an attacker's untrusted-identity account a verified email; their later trusted Google sign-in would auto-link into it. Refuse auto-link into an account with no trusted identity.
- Native ID-token sign-in accepts a missing `nonce` (Apple, Google). Make it required once the mobile apps ship (Phases 7/8).
- Apple native sign-in without `authorization_code` stores no revocable secret; consider requiring the code (App Store review expects revoke on delete).
- JWKS: an unknown `kid` refetch can be spammed (no negative cache); network failures map to `provider_error`, not `provider_unavailable`; `nonce=None` skips the nonce check.
- Invite mode: an existing-email sign-up leaves the invite unconsumed, so an invite holder can probe whether an address is registered.
- Legacy JWTs without `uid` resolve by username until they expire (≤ 24 h after the sessions deploy).
- Avatar provider import trusts the declared Content-Type; multipart is parsed before the auth check.

## Correctness and robustness

- New rate-limit buckets (`account`, `oauth`, `refresh`) answer the legacy `429 {"detail"}` without `error_code: "rate_limited"`.
- An OAuth account with no provider email (or an untrusted one while SMTP is off) stays `email_unverified` for AI with no way out.
- Non-atomic sequences: change-password + bump + revoke; `put_onboarding` read-modify-write; `unlink_identity` count + delete (two concurrent unlinks can leave a password-less account with no sign-in).
- id-token route: `profile.display_name` and `_signed_in` sit outside the error guard (500 possible); in `complete`, a DB lock timeout shows as `400 signup_token_invalid`; a `409 email_changed` consumes the link.
- Account deletion: a `LastAdminError` after a client disconnect logs "Task exception was never retrieved".
- Avatar decodes queue in the shared default executor (6 threads); use a dedicated one.
- `vm_backup` re-uploads the user tables almost every 5 minutes (`ai_usage_daily`, `last_login_at` change constantly); exclude volatile tables.
- Daily AI quota also applies per IP to anonymous callers (dev only; production requires sign-in); document or drop.
- One `tp_oauth` cookie per browser: two concurrent starts collide (`code_invalid`).
- Game rules are cached per process (an edit at the same path needs a restart).

## Web app

- `/config` failure is cached as empty for the page load, hiding account editing, settings sync and the game until reload; retry once.
- AuthContext: the mount-time `/auth/me` has no staleness guard; the spinner can stick if another tab stores a token while it is in flight.
- Router-state notices replay on reload and the "signed out" notice is never cleared; a dead-token link error loses its toast.
- Only the last held game award is kept within the 15 s replay window.
- `tp_oauth_method` is never cleared; ChooseUsername display-name `maxLength` is 60 (contract 1–50); `has_password` defaults differ between Security and Data sections.
- ProfileSection reads `email_verified` from AuthContext, which `PUT /auth/email` doesn't update until reload.
- Settings: card narrower than the others; the time-zone select shows the device zone while the stored value is null; edits debounce 1 s (an immediate export shows the old value); pending debounced edits are lost on sign-out; a shared device can push user A's language/theme up to user B.
- AccountPage can't tell loading from unavailable; a 500/offline leaves only Profile with no retry.
- Account menu lacks arrow-key navigation; edit controls pop in after load.
- Tests to add: settings language device-up-sync and consent mirroring; quota limit-reached and non-404 cases; delete 409/400 errors; resend 429 `retryAfter`; onboarding step clamp > 5.

## Code health

- Private helpers used across modules: `users_db._hash/_delete_user_rows/_holder_blocks`, `invites_db._hash`, `account._display_name`, `alert_email._POLICY/_sender/_mail_domain`, `feedback_db._row_to_dict`. Promote to public helpers (e.g. a `core/accounts_helpers` module).
- `PASSWORD_DETAIL` lives in `routes/auth.py`; `auth.py` lazily imports `signup.address_allowed`. Move both next to `core/passwords` / a shared email module.
- Email `_LOCALES` is hand-maintained and not checked against the SPA's language list.
- Telemetry `game_award.rule`, `badge_earned.badge`, `auth_result.code` are free-form ids (could be enums).
- `docs/API-Reference.md` endpoint table doesn't list the account endpoints (it links `Accounts-API.md`).
- Agent error sections show raw SDK text when no model key is configured (predates Phase 1).
