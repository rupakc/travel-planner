# Addendum: everything auto-deploys within minutes (2026-11-06)

Addendum to the lean GCP design (`2026-11-06-gcp-lean-deploy-design.md`, §6 "Deploys"). It replaces the decision that Caddy changes wait for a weekly night window. Requirement: the backend, the SPA and Caddy all go live automatically within about 5 minutes of the deploy workflow finishing, with no regression in security.

## Problem

The SPA was baked into the Caddy image, so every frontend change produced a new Caddy digest. Recreating Caddy cuts every open connection, including SSE searches and chats that run for minutes, so the deployer staged new Caddy digests until Sunday 04:00 Berlin.

## Decisions

1. **Content is not the runtime.** The Caddy image still carries `/srv` (the SPA) and `/etc/caddy/Caddyfile`, but the VM serves neither from the container. `deploy.sh` copies them out of each verified image with `docker create` + `docker cp` (never started, `--network none`) into `/var/lib/voyager/edge/releases/<full sha256 hex>/`.
   - **Checks:** only regular files and directories (no symlinks, devices or FIFOs); `index.html` present and every `/assets/…` it references present; at most 200 MB.
   - **Normalised:** root-owned, `0644`/`0755`, plus `SOURCE`, `BUILD` and `.complete`.
   - **Directory name:** the full digest. It can't collide, and only a validated 64-hex string becomes a path.
2. **Atomic switch.** Relative symlinks `current`, `prev1` and `prev2` are replaced with `ln -s` to a temp name and then `mv -T` (rename). Caddy bind-mounts the whole directory read-only at `/edge`, never a single file (a file bind mount pins the inode and never sees a rename), and runs `--config /edge/current/Caddyfile`.
3. **Old assets stay servable: try_files across the last three releases.** The other option was a shared, age-pruned assets pool. Try_files was chosen because it needs no second store and no pruning-by-age rule, and it can't serve an asset no kept release contains. The `@asset` file matcher tries `/current/srv{path}`, `/prev1/srv{path}` and `/prev2/srv{path}` under `root /edge`. Hits are `immutable` for a year. Misses are an uncached `404` (before this change, a 404 also carried the one-year header). Three releases are kept and the rest deleted. An edge rollback swaps `current` and `prev1`, so the release left behind stays an asset fallback.
4. **Caddyfile hot reload.** When the release's Caddyfile differs from `current`'s:
   - it is adapted with `caddy adapt --validate` in a throwaway container (`--network none --read-only`, uid 10002, no capabilities, 128 MB, with the real `SITE_HOST`/`ACME_EMAIL` from `site.env`). This is never a second Caddy inside the 96 MB Caddy container.
   - The image used is the running runtime image (same Caddy, by label) for content updates, and the new image for runtime changes.
   - The JSON is posted to `/load` on the admin API (`127.0.0.1:2019`, inside the container) with busybox `wget`. Caddy applies `/load` atomically and gracefully: listeners are reused and open connections finish on the old config. A refusal leaves the old config; the symlinks go back, the digest is held and an email goes out.
   - After a switch, `deploy.sh` checks through Caddy (container IP, `--resolve`, `-k`) that `/` is byte-identical to the new `index.html` and its entry asset loads. A wrong answer rolls back; no answer at all (Caddy down) is left to the converge step.
5. **Runtime changes recreate, automatically.** Image label `io.voyager.caddy-runtime` = SHA-256 over the base image pinned by digest (the workflow resolves `caddy:2.10-alpine` and passes the pinned ref as the `CADDY_BASE` build arg, so the build uses exactly what is hashed) and the final stage of `caddy.Dockerfile` without comments and without the two content `COPY` lines (`deploy/gcp/caddy-runtime-id.sh`).
   - A different (or missing) label means: validate with the new image, drain, switch, recreate, then check health (admin API plus `/` and an asset).
   - On failure it goes back to the previous runtime and release, holds the digest and sends an email.
   - `CADDY_IMAGE` (what compose runs) changes only here. `CADDY_CONTENT_IMAGE` tracks the content.
6. **Drain.** New app endpoint `GET /internal/streams` → `{"active_streams": n}`, counted in `core/sse.guarded_stream`.
   - It isn't under `/api` or `/health`, so Caddy never routes it, and a request carrying any forwarding header gets a 404. It exposes a single number.
   - `deploy.sh` polls it on the compose network (`172.30.0.10:8001`) every 3 s for up to 90 s, then recreates anyway. If the count can't be read (an old app), it recreates at once.
   - The converge step uses the same drain when compose would recreate Caddy for a changed `compose.yaml` (compose config hash vs the container's `com.docker.compose.config-hash` label).
7. **Security kept.**
   - Every digest, content-only included, is cosign-verified against the `deploy.yml@refs/heads/main` identity before it is pulled.
   - Downgrades are refused (`io.voyager.build`, compared with the live release's `BUILD`) and remembered in `refused-digests`, so they aren't re-verified every minute.
   - Holds (`failed-digests`) apply to Caddy digests as to the app.
   - No new ports; the admin API stays on loopback inside the container; extracted files are never executed; Caddy stays non-root with no capabilities.
8. **Faster, cheap polling.** The timer runs every 60 s (`RandomizedDelaySec=5s`, `AccuracySec=1s`).
   - One anonymous GHCR token covers both repositories and is cached for 4 min (re-fetched on a `401`). A run with nothing new is two `HEAD`s: no pull, no cosign.
   - A `429` backs off (`Retry-After`, else 60 s × 2ⁿ, capped at 30 min, in `/run/voyager-deploy/backoff`). A failed signature check is retried after 10 min. "Held" and "refused" notes are logged once, not every minute.
9. **Smaller pulls.** `caddy.Dockerfile` puts the runtime `RUN` layer before the content `COPY`s, so those layers are cached and identical across releases. A frontend change downloads only the SPA layer. Content-only images are removed once their files are extracted; the runtime and previous runtime images are kept for rollback.
10. **The window.** `--window` is accepted and ignored. `voyager-window.timer` stays, repurposed: Sunday 04:00 Berlin, reboot only if `/run/reboot-required` (unchanged behaviour for reboots).
11. **Migration safety.**
    - The image's own `/edge/current` points at its baked `/srv` and Caddyfile, so a new image still serves its SPA under the old `compose.yaml` (for instance if the old deployer's Sunday window applies it before `--update-host`).
    - `first-boot.sh` unpacks the kit under the deploy lock (no mixed old/new files) and then runs `deploy.sh`.
    - Before any network call, `deploy.sh` rebuilds a missing `current` from the pinned image. An old `images.env` has no `CADDY_CONTENT_IMAGE` and an unlabelled runtime, so the first new image takes the runtime path: one drained recreate, which also applies the new compose definition. Certificates stay in `caddy_data`.

## Timing (measured on 2026-11-06 runs, estimated on the VM)

| Step | Time |
|---|---|
| Deploy workflow (CI ≈ 4.5 min → publish ≈ 1.5 min) | ≈ 6 min |
| VM notices `prod` moved | ≤ 65 s |
| SPA/Caddyfile: verify + SPA layer pull + extract + switch | ≈ 30–60 s |
| App: pull + health (Docker health interval 30 s) | ≈ 1–4 min |
| **Merge → live** | **≈ 7–9 min** (1–3 min after the workflow) |

## Proposals (not done; they would save minutes but touch CI gates)

The first two were done on 2026-11-07 (branch `perf/faster-deploy`): `build` runs in parallel with CI and Trivy-scans the shipped images by digest before signing; `promote` moves `prod` after CI; unchanged images (`io.voyager.app-inputs` / `io.voyager.caddy-inputs`) are not rebuilt. See [Testing and CI](../../Testing-and-CI.md#deployyml).


- `build-and-scan` builds and Trivy-scans the legacy nginx `frontend/` image, which isn't deployed, and waits for every test job. Scanning the Caddy image that ships instead (and the app image `publish` builds, by digest) would be more useful and could run in `publish` after the push and before moving `prod`, saving about 1 min.
- The app image gets a new digest on every merge (revision label), so the app restarts, cutting its SSE streams, even on frontend-only merges. A content label for the app (like the Caddy runtime id) would skip those restarts. The same drain could also run before app recreates.
- `start_interval: 5s` on the app's healthcheck (Docker ≥ 25) would shorten the health wait from about 30 s to about 5 s. Left out: changing the app service would restart the app during the migration.

## Review fixes (2026-11-07)

- **Errexit that works.** Bash ignores `set -e` in functions called from `if`/`||`/`&&`. Every deploy step now runs through `step FN`: in plain context, in a subshell with `set -e`, with its status in a variable, and images.env is read back afterwards. Every pull, `docker create`/`cp`, `compose up` and write is also checked explicitly.
- **Fail closed.** An unreadable or non-numeric build label (on the new image, or the live one's, falling back from the release's `BUILD` to the runtime image's label) refuses instead of skipping the downgrade check. After `compose up`, the container's image ID must equal the intended digest's before health counts.
- **Holds vs retries.**
  - Holds: content/validation failures and an admin-API refusal (by digest), an unhealthy app (by digest), and an unhealthy Caddy runtime (by **runtime id**, `held-runtimes`; also written by `--rollback-caddy`).
  - Retried after 5 min, nothing held: infrastructure failures, and an SPA that Caddy doesn't serve after the switch.
  - An image with a held runtime ships its content on the current runtime when its Caddyfile validates there; nothing is ever recreated onto a held runtime.
- **Containment.** A broken edge directory never blocks app deploys or app/Caddy rollbacks. Emails and repeated infrastructure errors go out at most once an hour per kind. The live content image is kept until it is replaced, at the cost of one SPA layer of disk, so a lost edge directory is rebuilt offline.
- **Cheap no-change run.** Converge runs only when the hash of `compose.yaml`/`site.env`/`app.env`/`images.env` changed or one `docker ps` shows a service not running.
- **Minors.**
  - `.staging` is 0700.
  - `window.sh` no longer prunes images; `deploy.sh` removes old app and Caddy images by digest, keeping current and previous. A failed runtime image is removed.
  - Caddy health: running image ID, admin API, readable `/edge/current/srv/index.html` and plain-HTTP redirect; HTTPS only warns.
  - `--rollback-edge` is a toggle (it releases the hold of the release it returns to).
  - `caddy.Dockerfile` notes that the runtime id hashes lines, not the contents of COPYed host files.

## Re-review fixes (2026-11-07)

- **HTTPS is part of Caddy health.** A wrong HTTPS answer is always unhealthy. No HTTPS answer is tolerated only when HTTPS gave no answer before the change too (`https_baseline`, probed before the recreate) or on a first deploy. This applies to runtime deploys, converge recreates and `--rollback-caddy`. The previous runtime image is removed only after the new one passes.
- **No flip-flopping.** An SPA that Caddy serves wrongly after a successful switch/reload is held (email once). A runtime or app `compose up` that fails, or leaves the old container, twice in a row for the same digest is held.
- **Minors.** While the app step only waits to retry, the edge step still runs. Refused images (downgrade, no build label) are removed. An unknown live build falls back to the label of the image the live release came from, else the deploy retries; it never uses another image's label.
