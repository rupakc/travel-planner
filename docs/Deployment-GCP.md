# Deployment on GCP (e2-micro VM)

The production setup for Voyager: one always-free **e2-micro VM** in `us-east1` running the app container and Caddy, with SQLite on the VM's persistent disk. The design and its reviews are in `docs/superpowers/specs/2026-11-06-gcp-lean-deploy-design.md`.

**Monthly cost:** hosting ≈ $4 (the static IPv4 address is $3.65; the VM, the 30 GB disk and egress up to 200 GiB are free; snapshots cost cents). Gemini is extra, capped at ₹1,800 a month by a spend cap. The egress governor on the VM keeps hosting from growing under abuse.

| Piece | Where |
|---|---|
| Project | `voyager-prod-ohzkl` (billing account `010A0B-F39593-14A899`, in INR) |
| VM | `voyager-vm`, e2-micro, `us-east1-b`, Debian 13, 30 GB pd-standard, Shielded VM, OS Login, IPv4 only (Standard tier) |
| Site | `https://<a-b-c-d>.sslip.io` (from the static IP). Your own domain later |
| Images | `ghcr.io/rupakc/travel-planner-app` and `-caddy`, signed by `deploy.yml` |
| Data | `/var/lib/voyager/data/airports.db` on the VM's disk (authoritative) |
| Backups | user tables → `gs://voyager-prod-ohzkl-voyager-backup/sqlite-backups/airports.db` (when changed, every 5 min) + daily disk snapshots (keep 7) |
| Secrets | Secret Manager, read into memory at container start |
| Files on the VM | `/opt/voyager` (compose, `app.env`, `site.env`, `images.env`, `governor.py`, `deploy.sh`), `/etc/voyager/governor.env` |

```
Browser / Android ──HTTPS──► voyager-vm (e2-micro)
                              ├─ caddy  : TLS, SPA, /api + /health → app (SSE flushed)
                              ├─ app    : FastAPI + SQLite on the disk, Gemini via the VM's service account
                              └─ host   : egress governor (every minute), deployer (every minute),
                                          weekly reboot window (Sun 04:00 Berlin), unattended-upgrades (03:30 Berlin)
GitHub: merge to main → CI ∥ build + scan → sign (cosign) → GHCR `prod` tag ──(pulled by the VM)
```

---

## 1. Before you start

- `gcloud` CLI installed and signed in as the account that owns the project (`gcloud auth login`), with the **`beta` component**: notification channels have no GA command yet (alerting policies and uptime checks use GA commands, so `alpha` isn't needed). The script checks this first and stops before changing anything; install it with `gcloud components install beta --quiet`. A gcloud installed with apt/dnf has no component manager; see [Managing gcloud CLI components](https://cloud.google.com/sdk/docs/components).
- You don't need to change gcloud's default project. As soon as the project exists, the script sets `CLOUDSDK_BILLING_QUOTA_PROJECT=voyager-prod-ohzkl` (unless you already set it), so billing, budget and monitoring calls bill their quota to this project. Without it they used the account's default quota project and failed with *does not have permission to access billingAccounts* (first run, 2026-11-06).
- Check that nothing else on the billing account uses the free tier: one free e2-micro, 30 GB of standard disk and 200 GiB of Standard-tier egress are free **per billing account**, not per project.
- The project `voyager-prod-ohzkl` exists with billing linked and `aiplatform.googleapis.com` enabled. The two budgets also exist already: **"Voyager total (alerts)"** (₹2,300, email alerts) and **"Voyager Gemini spend cap"** (₹1,800, a hard cap on Agent Platform). The bootstrap script finds them by name and doesn't duplicate them.

## 2. Bootstrap (together, once)

Preview every command first. The dry run prints the commands and calls nothing:

```bash
infrastructure/gcp/bootstrap.sh --dry-run voyager-prod-ohzkl 010A0B-F39593-14A899 you@example.com
```

Then run it for real (it is idempotent: re-running skips whatever exists):

```bash
infrastructure/gcp/bootstrap.sh voyager-prod-ohzkl 010A0B-F39593-14A899 you@example.com
```

It enables the APIs and creates:

- the `vm-runtime` service account, with two **custom roles** and per-resource grants: `voyagerGeminiInvoker` (only `aiplatform.endpoints.predict`, which authorises Gemini prompt requests), `voyagerFcmSender` (only `cloudmessaging.messages.create`), `objectUser` on the backup bucket only, and `secretAccessor` on each secret;
- the static IP and the firewall: 80/443 open, 22 only from IAP; the default network's SSH/RDP-from-anywhere rules are deleted;
- the bucket and the empty secrets;
- the snapshot schedule, attached to the VM's boot disk;
- the VM, and the uptime check with its alert.

CI has no identity in GCP: it pushes to GHCR and signs with Sigstore.

During rollout, check the narrow Gemini role with one real search. If Vertex answers `403 PERMISSION_DENIED`, the call needs another permission: add it to `GEMINI_PERMS` and re-run the script. Don't fall back to `roles/aiplatform.user`. The VM starts provisioning itself straight away (section 4); the app waits for its secrets.

Optional overrides via environment: `ZONE`, `BUCKET`, `SITE_HOST` (your own domain), `ACME_EMAIL`, `BUDGET_CURRENCY`/`TOTAL_BUDGET`/`AI_SPEND_CAP` (used only when a budget is missing), `CLOUDSDK_BILLING_QUOTA_PROJECT`.

The host bundle (`deploy/gcp` without its tests, sent as instance metadata) is built with `COPYFILE_DISABLE=1` and without extended attributes or AppleDouble files (`--no-mac-metadata --no-xattrs` on macOS, `--no-xattrs` with GNU tar), from a sorted file list. Built on a Mac it used to carry `com.apple.provenance` as `LIBARCHIVE.xattr` headers, which Debian's tar warned about on every boot.

**Spend cap fallback.** If the script can't create the spend cap through the Budget API (it has no gcloud flag yet), create it in the console: Billing → Budgets & alerts → Create budget → **Spend cap enforcement**, name "Voyager Gemini spend cap", project `voyager-prod-ohzkl`, service *Gemini Enterprise Agent Platform* (`C7E2-9256-1C43`), amount ₹1,800. When the cap trips, Gemini calls fail until the 1st (or until you lift it on the budget's page), and the rest of the app keeps working.

## 3. Secrets

The secrets are created empty, and you add the values. They go from your terminal to Secret Manager and never touch the VM's disk, the repo or a log. Use `printf` (no trailing newline) and `read -s` (no shell history):

```bash
P=voyager-prod-ohzkl
openssl rand -base64 48 | tr -d '\n' | gcloud secrets versions add jwt-secret-key --data-file=- --project=$P
read -rs V; printf '%s' "$V" | gcloud secrets versions add admin-password --data-file=- --project=$P; unset V
read -rs V; printf '%s' "$V" | gcloud secrets versions add serpapi-key    --data-file=- --project=$P; unset V   # optional
read -rs V; printf '%s' "$V" | gcloud secrets versions add serper-key     --data-file=- --project=$P; unset V   # optional
read -rs V; printf '%s' "$V" | gcloud secrets versions add smtp-password  --data-file=- --project=$P; unset V   # optional
```

There is no Anthropic key in production: Gemini on Vertex AI uses the VM's service account (`LLM_PROVIDER=gemini`, `GCP_PROJECT`, `GCP_LOCATION=global` in `app.env`).

- `jwt-secret-key` is required: the app refuses to start without it.
- The app runs as uid 10001 and Caddy as uid 10002. Both drop all capabilities, and only the app container can reach the metadata server: the governor's `VOYAGER-GUARD` chain blocks Caddy.
- A secret with no version is simply skipped.
- After changing a secret, restart the app: `sudo docker compose -f /opt/voyager/compose.yaml --project-directory /opt/voyager restart app` (or wait for the next deploy).

**Email (optional).** For the governor, deploy and alert emails, set the non-secret SMTP settings as instance metadata (`voyager-smtp-host`, `voyager-smtp-port`, `voyager-smtp-username`, `voyager-smtp-from`). Also set `SMTP_HOST` etc. in `/opt/voyager/app.env` for the app's alert emails. Port 25 is blocked on GCE; use 587.

**Firebase (push).** Add Firebase to `voyager-prod-ohzkl` in the Firebase console and register the Android app there. Download its new `google-services.json` for the Android build, whose `PROD_BASE_URL` must be the site URL. The VM sends pushes with its own service account (`FCM_USE_ADC=true`), so there is no key file.

## 4. First boot and first deploy

**Images.** Merge to `main` (or re-run the *Deploy* workflow) so that `deploy.yml` publishes the first signed images. Then, **once**, make both GHCR packages public (GitHub → Packages → `travel-planner-app` / `travel-planner-caddy` → Package settings → Change visibility → Public), so the VM can pull them without credentials.

**Watch the VM provision itself:**

```bash
gcloud compute ssh voyager-vm --zone=us-east1-b --tunnel-through-iap -- \
  sudo journalctl -u google-startup-scripts -f
```

`first-boot.sh` installs Docker Engine and the compose plugin, configures zram swap and unattended-upgrades, unpacks the host bundle from instance metadata into `/opt/voyager`, and writes the data-disk marker `/var/lib/voyager/data/.voyager-data-disk`. It also installs the systemd units, runs the first deploy, and then starts `voyager.service` with `--no-block` (the script runs inside `google-startup-scripts.service`, so it never waits on another unit). The unit must be **active** even though the first deploy, not the unit, started the containers: only an active unit runs its `ExecStop` (graceful stop and backup flush) at shutdown. If the first deploy fails, the unit's start is skipped (no `images.env` yet) and `deploy.sh` starts it once a later deploy lands. The unit's `compose up`, `deploy.sh` and `first-boot.sh`'s own `compose up` all hold `/run/voyager-deploy.lock`, so they never run at the same time. Each later boot re-runs it, which is harmless, and applies any changed `compose.yaml`/`app.env` with `compose up -d`. It fails closed: when required metadata (`voyager-bucket`, `voyager-site-host`, `voyager-acme-email`, `voyager-alert-email`, the bundle) is missing or the metadata server errors, it stops rather than write empty settings such as `BACKUP_BUCKET=`. `/opt/voyager/app.env` is required by compose.

**Disk benchmark (rollout step 3).** pd-standard is slow (about 3.6 MiB/s). Benchmark it; if image pulls and the first reseed are painful, switch to a 10 GB pd-balanced boot disk (about +$1/month).

```bash
sudo apt-get install -y fio && sudo fio --name=t --filename=/var/lib/voyager/fio.tmp --size=256M \
  --rw=randrw --bs=4k --direct=1 --runtime=30 --time_based && sudo rm /var/lib/voyager/fio.tmp
```

**Check the unit.** After the first boot has finished (and after every reboot):

```bash
gcloud compute ssh voyager-vm --zone=us-east1-b --tunnel-through-iap -- systemctl is-active voyager
```

It must print `active`. On the first boot of 2026-11-06 it printed `inactive` although the containers were up, so a shutdown would have skipped the graceful stop and the backup flush. If you see `inactive` and `/opt/voyager/images.env` exists, run `sudo systemctl start voyager` (a no-op `compose up -d`); if it is `failed`, see `journalctl -u voyager`. CI checks this with `deploy/gcp/tests/first_boot_sim.sh` (job `host-checks`).

**Smoke test.** Then check:

- `https://<host>/health` shows `"backup_ok":true`.
- Log in, run a search (the results stream) and send a chat message.
- Run a watch check (Alerts → Check now) and send a push to a real phone.
- Reboot: `sudo systemctl reboot`. Afterwards `systemctl is-active voyager` prints `active` again.
- Run both restore drills (section 7) and the governor test (section 8).
- Deploy during an active search: Caddy holds new requests while the app restarts, but open streams end.

## 5. Migrating the old-prod users (decision §13.4)

The 2026-08-30 export is 886 MB, almost all of it a broken `sqlite_sequence` table. Strip it to the user tables on your laptop. The export is opened read-only, and the tool checks its hash before and after:

```bash
python3 infrastructure/gcp/migrate_old_prod.py --out /tmp/voyager-migration/airports.db
cat /tmp/voyager-migration/migration-report.md     # per-table counts must match
```

The dry run on 2026-11-06 migrated users 17, plans 11, preferences 8, taste signals 73 and feedback 2 (about 270 KB). `preferences.visited_destinations` is no longer in the schema and is dropped. Price watches, notifications and devices didn't exist then.

Put the file where restore-if-missing finds it. Restore happens only when the disk has no DB, so the order matters:

1. **Before the first boot** (the right time, right after bootstrap and before the first images are published): upload it, as below. The first start restores it.
2. **If the app already started** (it created an empty DB): run `sudo systemctl stop voyager` on the VM, upload the file, run `sudo rm -f /var/lib/voyager/data/airports.db*` (keep the marker), then `sudo systemctl start voyager`.

Upload:

```bash
gcloud storage cp /tmp/voyager-migration/airports.db \
  gs://voyager-prod-ohzkl-voyager-backup/sqlite-backups/airports.db
```

At start, the app sees no DB on the disk, restores this file and reseeds the place data. The old passwords keep working.

## 5a. Forgotten password or a new admin

There is no self-service reset; the operator sets a password on the VM. The tool asks for it twice with no echo, so it never appears in shell history, `ps` or a log, and nobody else (including an assistant) has to see it:

```bash
gcloud compute ssh voyager-vm --zone=us-east1-b --tunnel-through-iap --project=voyager-prod-ohzkl -- -t \
  sudo docker exec -it voyager-app-1 python -m app.set_password admin
```

- A reset also reactivates the account and skips the forced change on next login (you chose the password).
- New admin: `python -m app.set_password NEWNAME --create --admin`.
- Minimum length is the app's (8 characters). The change reaches the GCS backup within 5 minutes.

## 6. Day-to-day: deploys and rollback

- **Auto-deploy.** Every merge to `main` that passes all of CI moves the `prod` tags to images signed by `deploy.yml`. Each image is built and Trivy-scanned while CI runs (jobs `build-app`, `build-caddy`); only after CI and its own build passed is it signed and its `prod` tag moved (`promote-app`, `promote-caddy`), so every signed image has passed CI, and a failure of one image never holds back the other. An image whose inputs didn't change isn't rebuilt and its `prod` tag isn't moved (labels `io.voyager.app-inputs` / `io.voyager.caddy-inputs`, `deploy/ci/image-inputs-id.sh`), so a frontend-only merge never restarts the app (open chats survive) and a backend-only merge leaves the SPA alone. Pip's version ranges in `backend/requirements.txt` resolve at build time and are not part of that id: a **weekly refresh** (Mondays 04:17 UTC, the Deploy workflow on a schedule) rebuilds both images **without cache**, so dependency and base-image fixes flow; it restarts the app once a week after draining open streams. Each image records its last refresh in the label `io.voyager.fresh-at`, and any Deploy run, a push included, refreshes an image whose `prod` copy is over 8 days old or lacks the label. So a scheduled run that a queued push replaced (the concurrency group keeps only the newest pending run) still gets its refresh with the next push. **GitHub disables scheduled workflows after 60 days without repository activity** (it emails the owner): re-enable them with `gh workflow enable deploy.yml` and `gh workflow enable prod-scan.yml`, or in the Actions tab (select the workflow, "Enable workflow"). Until then, the next push still refreshes stale images, but nothing scans `prod` daily. A **daily scan** (`prod-scan.yml`) checks the two `prod` images with the same Trivy policy and fails visibly, without touching anything. Within a minute `voyager-deploy.timer` on the VM resolves `prod` to a digest and checks the cosign signature: it must come from `rupakc/travel-planner`'s `deploy.yml` on `refs/heads/main`. It then pulls by digest, waits up to 90 s for open SSE streams to end (the same drain as for Caddy, logged as `drain: …`; an automatic rollback doesn't wait), pins the digest in `/opt/voyager/images.env` (keeping the previous one), runs `docker compose up -d`, and waits up to 240 s for the app to report healthy (longer than the container's 180 s start period, so a slow reseed isn't mistaken for a failure). Each run also converges: `compose up -d` brings back anything that was stopped, e.g. by a Docker upgrade.
- **Automatic rollback.** If the new app isn't healthy, the previous digest goes back in. The bad digest is held in `/opt/voyager/failed-digests` and never retried. You get an email if SMTP is set. Before health counts, `deploy.sh` checks that the container really runs the new image's ID; if `compose up` failed or left the old container, the new digest is rolled back too.
- **Held vs retried.** Only deterministic failures hold something:
  - Held: content that fails its checks (SPA, Caddyfile validation, a Caddyfile Caddy refuses), and an app that never gets healthy (by digest, in `failed-digests`).
  - Held by runtime id: a Caddy runtime that fails its checks after a recreate, in `/opt/voyager/held-runtimes`.
  - Held as well: an SPA release that Caddy serves wrongly right after the switch (it is switched back).
  - Retried after 5 min, nothing held: infrastructure failures (pull, `docker create`/`cp`, `compose up`, a full disk, Caddy or its admin API not answering). A `compose up` that fails, or leaves the old container, twice in a row for the same digest holds it.
  - While the app only waits to retry, the edge still deploys. So a frontend release can go live **before** its app (the app waiting to retry, or held after a failed health check). Frontend changes must therefore work against the previous backend: feature-detect new endpoints or fields, and never assume an API change is live just because the SPA is.
  - The reverse holds too: the two images are built, scanned and promoted **independently** (a failed Caddy build or scan never holds back the app, and vice versa), so a new app can run behind the previous SPA for as long as the Caddy side is held or failing. Backend changes must keep serving the previous SPA: never remove or rename an endpoint, a field or its meaning in one step. Add the new one, ship the SPA that uses it, and remove the old one in a later merge.
  - Refused images (downgrades, no build label) are removed from the disk.
  - **Releasing a hold:** publish a new digest (merge a fix, or run Deploy by hand: `gh workflow run deploy.yml --ref main` rebuilds both images, `-f force=false` only what changed), or delete the digest's line in `/opt/voyager/failed-digests` (runtime ids: `/opt/voyager/held-runtimes`).
  - A build label that can't be read is refused (fail closed), never treated as "not a downgrade".
  - Emails and repeated error logs go out at most once an hour per kind.
- **Manual rollback** to the previous app digest: `sudo /opt/voyager/deploy.sh --rollback`. The digest you rolled back from is **held**: it goes into `/opt/voyager/failed-digests`, so the timer doesn't redeploy it while `prod` still points there. Publishing a newer digest ends the hold, because only the listed digests are skipped. To release a held digest by hand, delete its line.
- **No silent downgrades.** An image built by an older deploy run than the running one (label `io.voyager.build`) is refused, even if `prod` points at it. That covers a moved tag and a re-run of an old workflow. To deploy it on purpose: `sudo /opt/voyager/deploy.sh --allow-downgrade`.
- **Caddy image (SPA + Caddyfile + Caddy runtime): also automatic, within a minute.** There is no weekly window for it anymore (`--window` is accepted and ignored). For each new signed Caddy digest `deploy.sh`:
  - copies `/srv` and the Caddyfile out of the image (`docker create` + `docker cp`; the image never runs) into `/var/lib/voyager/edge/releases/<full digest>/`. It refuses symlinks, devices and anything else that isn't a regular file or directory, an `index.html` that loads a missing `/assets/…` file, and more than 200 MB. Files become root-owned `0644`/`0755`.
  - switches the relative symlinks `current → new`, `prev1 → old current`, `prev2 → old prev1` (atomic rename). Caddy mounts `/var/lib/voyager/edge` read-only at `/edge`, serves the SPA from `/edge/current/srv` and looks `/assets/*` up in `current`, `prev1` and `prev2`, so a browser still holding an older `index.html` gets its lazy chunks. A missing asset is an uncached `404`. Three releases are kept; older ones are deleted.
  - **SPA only changed:** nothing restarts. It checks through Caddy that `/` is the new `index.html` and one of its assets loads; otherwise it switches back.
  - **Caddyfile changed:** it adapts and validates the new Caddyfile in a throwaway container (no network, read-only, real `SITE_HOST`/`ACME_EMAIL`), then loads it through Caddy's admin API (`127.0.0.1:2019` inside the container). That's graceful: open connections, SSE included, keep running. If Caddy refuses it, Caddy keeps its old config, the symlinks go back, the digest is held and you get an email.
  - **Caddy runtime changed** (the label `io.voyager.caddy-runtime`, a hash of the pinned base image digest and the runtime lines of `caddy.Dockerfile`; see `deploy/gcp/caddy-runtime-id.sh`): it waits up to 90 s for open SSE streams to end (the app's `GET /internal/streams`, reachable only on the compose network), recreates the container, and checks Caddy without needing a valid certificate: the container runs the new image, the admin API answers, `/edge/current/srv/index.html` is readable, and plain HTTP gets the site's redirect to HTTPS. HTTPS must serve the release's `/` and an asset: a wrong answer always fails. No HTTPS answer at all is accepted only if HTTPS gave no answer before the change either (probed first; e.g. no certificate yet) or on a first deploy. The same rule applies to a converge recreate and to `--rollback-caddy`. The previous image is deleted only after the new runtime passes. If the checks fail, it rolls back to the previous image and release, holds that **runtime id** in `/opt/voyager/held-runtimes` and emails you. Later images with a held runtime still ship their SPA and Caddyfile, on the current runtime; only a new runtime id is recreated onto. Expect this when the upstream `caddy:2.11-alpine` image is rebuilt (roughly monthly) or `caddy.Dockerfile`'s runtime part changes.
  - A changed `compose.yaml` for Caddy (after `--update-host`) is also applied with the drain first: the converge step compares compose's config hash with the running container's.
  - `images.env`: `CADDY_IMAGE`/`PREV_CADDY_IMAGE` is the runtime compose runs and changes only on runtime changes; `CADDY_CONTENT_IMAGE`/`PREV_CADDY_CONTENT_IMAGE` is where the live SPA and Caddyfile came from. Every digest, content-only ones included, is cosign-verified, and downgrades are refused as for the app (`io.voyager.build`; for content, compared with the live release's `BUILD` file).
- **Timing.** The deploy workflow takes about 3.5–4.5 min: CI's slowest jobs (`test-backend`, `test-deploy-kit`, `host-checks`) take ≈ 2–3.2 min each, the build jobs (≈ 1–2 min each) run alongside them, and each promote job (cosign sign + verify, then the tag moves) adds ≈ 40–60 s. The VM then notices within ≈ 60 s (`voyager-deploy.timer`: every 60 s, ±5 s). An SPA/Caddyfile change is live ≈ 30–60 s later (cosign ≈ 10–20 s plus pulling only the small SPA layer, since the runtime layers are shared). An app change takes ≈ 1–4 min more (pull, drain of open streams up to 90 s, health check). Merge to live, estimated from the job times of the 2026-11-06/07 runs (before this change: 7–9 min, measured 8 min 53 s):
  - Frontend-only (`frontend/`, the Caddyfile): only the Caddy image is rebuilt; the app isn't touched (no restart). **≈ 4.5–6 min.**
  - Backend-only (`backend/`, `.agents/`): only the app; the SPA isn't touched. **≈ 5.5–8.5 min**, ≈ 6 typical (no open streams, healthy at the first 30 s health check).
  - Both: **≈ 6–9 min.**
  - Neither (docs, tests, workflows): nothing is built and `prod` doesn't move; CI only.
  - A new base image digest (`python:3.12-slim`; `caddy:2.11-alpine`, `node:20-alpine`) counts as a change of that image.
  - On the VM, a run with nothing new costs one cached anonymous GHCR token (refreshed every 4 min), two `HEAD` requests and one `docker ps`: no pull, no cosign, no compose. Converge (`compose up -d`) runs only when `compose.yaml`, `site.env`, `app.env` or `images.env` changed, or a service isn't running. A GHCR `429` backs off (`Retry-After`, else 1, 2, 4 … up to 30 min). A failed signature check is retried after 10 min, not every minute.
- **Rollbacks, by part:**
  - App: `sudo /opt/voyager/deploy.sh --rollback` (as before).
  - SPA + Caddyfile: `sudo /opt/voyager/deploy.sh --rollback-edge`. It swaps `current` and `prev1` (no restart; the Caddyfile is reloaded if it differs), holds the digest you left and releases the one you return to. It's a toggle: running it again undoes it.
  - Caddy runtime: `sudo /opt/voyager/deploy.sh --rollback-caddy`. It checks the live Caddyfile against the previous image, drains, recreates and holds. If the Caddyfile doesn't fit the old runtime, run `--rollback-edge` first.
  - `--rollback-caddy` holds the runtime id you left (`/opt/voyager/held-runtimes`), so a frontend-only merge afterwards ships its SPA on the old runtime instead of recreating Caddy onto the one you rolled back from.
  - Held digests are in `/opt/voyager/failed-digests`, held runtimes in `/opt/voyager/held-runtimes`, refused downgrades in `/opt/voyager/refused-digests`. Delete a line to release one.
  - If `/var/lib/voyager/edge` is lost and can't be rebuilt, app deploys and `--rollback` keep working; Caddy is left alone and you get one email an hour. The live content image is kept until it is replaced, so the rebuild needs no registry.
- **Logs.** Docker keeps 10 MB × 5 per container on the VM; there is no Cloud Logging agent and so no ingestion bill.
  - `sudo docker compose -f /opt/voyager/compose.yaml --project-directory /opt/voyager logs -f app`
  - `journalctl -u voyager-deploy -u voyager-governor` (deploys log `SPA live: release …`, `Caddyfile reloaded (graceful)`, `drain: …`, `Caddy healthy on the new runtime …`)
  - `ls -l /var/lib/voyager/edge/` shows which release `current`, `prev1` and `prev2` point at; `cat /var/lib/voyager/edge/current/SOURCE` shows its image.
- **Host scripts changed** (`deploy/gcp/**`): re-run `infrastructure/gcp/bootstrap.sh --update-host …`, then on the VM run `sudo google_metadata_script_runner startup`. It returns as soon as the bundle is unpacked and `compose up -d` has applied the changes; units are started with `--no-block`, so it never waits on itself. **Afterwards check IPv4 forwarding:** `cat /proc/sys/net/ipv4/ip_forward` must print `1`, and `curl -m 10 https://<host>/health` must answer. If it prints `0`, see [Troubleshooting](#11-troubleshooting).
- **Schema changes stay additive.** A rollback must never meet a DB it can't read.

## Offline pack and the journey flag

- **Service worker.** The offline pack's service worker is `/sw.js`, served by Caddy with `Cache-Control: no-cache` so a new deploy is picked up on the next load. It is registered only when a user saves an offline pack, caches the app shell and the hashed `/assets/*` files listed in `/sw-assets.json`, and never intercepts `/api/*`. Trip data lives in the browser's IndexedDB, not on the VM.
- **Kill switch.** Set `OFFLINE_PACK_ENABLED=false` in `app.env` and restart the app. `GET /api/config` then reports `features.offline_pack: false`, and each client unregisters the worker, deletes the `voyager-*` caches and removes saved packs on its next load. Set it back to `true` to allow packs again.
- **`JOURNEY_UI_ENABLED`.** Off by default. While it is `false` the SPA shows the classic search-first app and the new paths (`/trips`, `/explore`, `/play`, `/you`) fall back to `/`. The trips API is served either way, so flipping the flag needs only an app restart, never a rebuild.

## 7. Backups and restore drills

The disk is authoritative (`BACKUP_MODE=vm`):

- The app restores from GCS **only** when `airports.db` is missing and the data-disk marker is present. It never merges.
- Every 5 minutes it exports the user tables to tmpfs and uploads them only when their SHA-256 changed. It flushes once more on a clean shutdown.
- `/health` reports `backup_ok`. The uptime check alerts you when that is false, or when the site is down, for 10 minutes.
- Daily disk snapshots (kept 7 days, stored in us-east1) are crash-consistent copies of the whole disk.

**Which copy to restore from.** GCS holds the user tables at most about 5 minutes old; a disk snapshot can be up to 24 hours old.

- When the **disk is lost**, prefer GCS: start from a fresh disk with the marker and no DB, and the app restores from GCS.
- When you do restore a **snapshot** (the OS or Docker state is broken), the snapshot's DB is older than GCS, and the next changed export would overwrite the newer GCS copy. GCS keeps up to 100 noncurrent versions for 30 days, so nothing is lost, but restore in this order:
  1. Stop the app on the restored VM: `sudo systemctl stop voyager`.
  2. Download the current object: `gcloud storage cp gs://voyager-prod-ohzkl-voyager-backup/sqlite-backups/airports.db /tmp/gcs.db`.
  3. Replace the snapshot's DB with it as uid 10001: `sudo rm -f /var/lib/voyager/data/airports.db*`, `sudo install -o 10001 -g 10001 -m 0644 /tmp/gcs.db /var/lib/voyager/data/airports.db`. Or simply delete the snapshot's DB and let restore-if-missing fetch it.
  4. Start the app: `sudo systemctl start voyager`. It reseeds the place data.

**Drill A, fresh disk from GCS** (about 5 min of data at risk). Then log in and check the plan counts:

```bash
sudo systemctl stop voyager
sudo mv /var/lib/voyager/data/airports.db /var/lib/voyager/data/airports.db.drill   # keep the marker!
sudo rm -f /var/lib/voyager/data/airports.db-wal /var/lib/voyager/data/airports.db-shm
sudo systemctl start voyager            # restores from GCS, reseeds place data
```

**Drill B, new VM from a snapshot.** Create a disk from the newest snapshot of `voyager-vm` and boot a temporary VM from it, with no static IP, an ephemeral address and the same service account. Check `/health` over IAP port forwarding, then delete the temporary VM and disk.

After a **real** snapshot restore, the governor's counter is up to 24 hours old. Raise it to Monitoring's month-to-date `sent_bytes_count` for the VM (Metrics Explorer), or to a safe 150 GiB:

```bash
sudo /opt/voyager/governor.py seed --gib 150
```

**Refusals you may see:**
- `has no .voyager-data-disk` means the data directory isn't the provisioned disk (a wrong mount). Fix the mount; never just create the marker on an empty directory.
- `restore … failed` means the DB is missing and GCS couldn't be read. The app won't start empty over a good backup; fix access and restart.

## 8. Egress governor

Egress on the Standard tier is free up to 200 GiB a month per billing account, then $0.085/GiB. The governor enforces this on the VM itself (`/opt/voyager/governor.py`, every minute, rules in Docker's `DOCKER-USER` chain).

How the rules are applied:

- The governor owns `DOCKER-USER`; don't add rules of your own there.
- Its rules are replaced in **one `iptables-restore` transaction**, validated first. A rejected ruleset leaves the previous rules in force and sends one email ("egress governor rules FAILED to apply", and another when they apply again). The `voyager-governor` unit then fails, so it shows in `systemctl --failed`.
- CI runs the real rules against iptables-nft on Debian 13 for every tier (job `host-checks`).
- Every tick first checks `/proc/sys/net/ipv4/ip_forward`, before it reads the egress state, so a corrupt `state.json` can't stop the check. The check keeps its own small state in `/var/lib/voyager/governor/ip_forward.json`. If forwarding is `0`, the governor sets it back to `1` and logs an error, so a reset costs at most about a minute of downtime. Emails:
  - after a successful restore: "net.ipv4.ip_forward was reset to 0; restored to 1", at most one a day;
  - when the restore fails: "could NOT be restored", sent at once on the first failure even if a restore email went out shortly before, then repeated at most once a day, plus one email when forwarding is back to `1`.

  See [Troubleshooting](#11-troubleshooting).
- Applying the rules also sets the `FORWARD` policy to `DROP` when it isn't already. Docker sets `DROP` only when it turns forwarding on itself, and with `99-voyager-docker.conf` forwarding is already on at boot. Only the built-in policy is changed; Docker's own chains are left alone. Check with `sudo iptables -S FORWARD | head -1`, which must print `-P FORWARD DROP`.

| Month-to-date egress (billing month, 00:00 America/Los_Angeles) | Action |
|---|---|
| always | each client IP: ≈ 4 Mbit/s and ≈ 3 GiB per 24 h; whole NIC shaped to 50 Mbit/s |
| 150 GiB | email warning; NIC shaped to 20 Mbit/s |
| 200 GiB | ports 80/443 **closed** until the month resets; email |

One IP needs over 60 days to use the whole allowance, so a single abuser can't close the site. The counter counts every byte the VM sends, including free Google traffic, so it errs towards closing early. It survives reboots.

```bash
sudo /opt/voyager/governor.py status            # month, tier, GiB used
sudo ipset save voyager_perip | sort -k8 -n | tail   # top talkers (bytes in the last 24 h)
sudo /opt/voyager/governor.py reopen --extra-gib 20   # reopen; closes again 20 GiB later (≈ $1.70 overage)
sudo /opt/voyager/governor.py close             # close now (by hand)
```

**Rollout test** (rollout step 5):

1. Lower the threshold: `echo GOVERNOR_CLOSE_GIB=0.001 | sudo tee -a /etc/voyager/governor.env`, then wait a minute.
2. Confirm from **outside** (your laptop) that `curl -m 10 https://<host>/health` fails.
3. Confirm the email and the uptime alert arrive.
4. Remove the line from `/etc/voyager/governor.env` and run `sudo /opt/voyager/governor.py apply`. Check that `status` shows `open` and the site answers again.

## 9. Domain

The site starts on `<a-b-c-d>.sslip.io`. The certificates live in the persistent `caddy_data` volume, so restarts don't hit Let's Encrypt's duplicate limit. To move to your own domain:

1. Add an A record pointing at the static IP. Add **no AAAA record**: IPv6 egress would be Premium tier, outside the free 200 GiB.
2. `gcloud compute instances add-metadata voyager-vm --zone=us-east1-b --metadata=voyager-site-host=your.domain`
3. On the VM: `sudo google_metadata_script_runner startup`. This rewrites `site.env` and `app.env`'s URLs; restart Caddy in a quiet moment.
4. Update the Android `PROD_BASE_URL` and the uptime check's host.

### Moving to a custom domain

Everything absolute comes from `PUBLIC_BASE_URL` (else `APP_BASE_URL`), so the move is configuration only:

1. DNS: an A record to the static IP, no AAAA (as above).
2. Set `voyager-site-host` (step 2 above) and run the startup script on the VM: it rewrites `SITE_HOST` for Caddy and `APP_BASE_URL`/`CORS_ORIGINS` in `app.env`. If you set `PUBLIC_BASE_URL` in `app.env`, change it too. Restart the app.
3. Provider consoles: add the new redirect URI `https://<domain>/api/auth/oauth/<p>/callback` for every provider (keep the old one until the old host is retired), and update Apple's domain and return URL. Email links follow the new base automatically.
4. Mobile deep links (Phases 7 and 8): the iOS `apple-app-site-association` and Android `assetlinks.json` files are served from the new domain's `/.well-known/`. Universal and app links only work on a domain you own.
5. Keep the old `<ip>.sslip.io` host answering with a redirect to the new domain for a while so old emails, shares and bookmarks still work. Pending verify and reset links issued before the move point at the old host; they expire in 30 minutes.

**Known limitation: Google does not accept `sslip.io`.** Google OAuth rejects redirect URIs on public-suffix domains such as `sslip.io`, so Google sign-in becomes available only after the move to a custom domain. GitHub, Facebook, Apple (needs a verified domain) and email sign-in are unaffected. Until then the Google button shows "coming soon".

## Sign-in providers and email

Providers are config-gated: add the credentials, restart the app, and the provider turns on with no client update. The redirect (callback) URI to register in each provider's console is `<PUBLIC_BASE_URL>/api/auth/oauth/<p>/callback`, where `<p>` is `google`, `github`, `facebook` or `apple`, for example `https://34-23-1-2.sslip.io/api/auth/oauth/github/callback`. Client IDs go in `/opt/voyager/app.env` (uncomment the lines in `app.env.example`); secrets go in Secret Manager (`google-client-secret`, `github-client-secret`, `facebook-app-secret`, `apple-private-key`, created empty by the bootstrap) with the same `printf`/`read -s` pattern as section 3.

- **GitHub**: Settings → Developer settings → OAuth Apps → New. Callback URL as above. Set `GITHUB_CLIENT_ID` and `github-client-secret`.
- **Facebook**: developers.facebook.com → create an app with Facebook Login, add the callback under Valid OAuth Redirect URIs. Set `FACEBOOK_APP_ID` and `facebook-app-secret`. Facebook's email is untrusted unless `FACEBOOK_EMAIL_TRUSTED=true`.
- **Google**: Google Cloud console → APIs & Services → Credentials → OAuth client ID (Web). Needs a custom domain (see the limitation above). Add the iOS and Android client IDs to `GOOGLE_NATIVE_CLIENT_IDS` for the native apps.
- **Apple**: in the Apple developer account create an App ID with Sign in with Apple, then a **Services ID** (this is `APPLE_SERVICES_ID`; enable Sign in with Apple, set the verified domain and the callback URL above, which Apple calls with a form POST). Create a **Key** with Sign in with Apple enabled: its Key ID is `APPLE_KEY_ID`, the downloaded `.p8` contents go in the `apple-private-key` secret, and your Team ID is `APPLE_TEAM_ID`. Add the app bundle IDs to `APPLE_NATIVE_CLIENT_IDS`.
- **SMTP**: sign-up verification and password reset need working email. Set the app's `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USERNAME`, `SMTP_FROM` in `app.env` and the `smtp-password` secret (section 3). Without SMTP, `GET /api/config` reports `signup_available: false` and the sign-up and reset forms are hidden. Sign-up also needs `SIGNUP_ENABLED=true`: setting SMTP alone (for example for fare alerts) enables password reset but never opens public sign-up.
- **`SIGNUP_MODE`**: `open` (default) or `invite`. In invite mode, create codes with `POST /api/admin/invites` (admin only); each code has a use limit and an expiry.

## 10. Cost watch

- **Budgets** (pre-tax, in INR): "Voyager total (alerts)" at ₹2,300 sends email at 50/90/100 % and on forecast; "Voyager Gemini spend cap" at ₹1,800 pauses Gemini when reached. Billing data can lag a day; the on-box governor doesn't.
- **Monthly check:** in Billing → Reports, filter on the project. Expect about $3.65 for the IP, cents for snapshots, $0 for egress and Gemini as used. Also check `governor.py status`, and in GCS that the bucket holds a few MB with no soft-deleted bytes.
- **Never add:** a load balancer, Cloud NAT, Cloud Run, Artifact Registry (image scanning), a logging agent, external IPv6, or a second VM.
- **SerpAPI** (free plan, 250 searches/month): `FARE_WATCH_DAILY_CALL_BUDGET=6` in `app.env`.

## 11. Troubleshooting

### Site down, app stuck starting: `net.ipv4.ip_forward` is 0

**Symptoms.** The site doesn't answer on 80/443, the uptime check fires, and the app container hangs in its entrypoint because it can't reach the metadata server or Secret Manager. Docker itself looks healthy.

**Check:**

```bash
cat /proc/sys/net/ipv4/ip_forward      # must print 1
journalctl -u voyager-governor | grep ip_forward
ls /etc/sysctl.d/                      # 99-voyager-docker.conf must be there
```

**Fix by hand** (the governor does this within a minute):

```bash
sudo sysctl -w net.ipv4.ip_forward=1
```

**Why it happens.** Docker needs IPv4 forwarding for its published ports (DNAT) and for the containers' own outbound traffic. It turns forwarding on only when `dockerd` starts. The GCE Debian image ships `/etc/sysctl.d/60-gce-network-security.conf` with `net.ipv4.ip_forward=0`, so any full sysctl reload under a running Docker turns forwarding off again. That includes `sysctl --system` and a restart of `systemd-sysctl`, for example by a package upgrade.

**Incident 2026-11-06, about 17:15 UTC (about 10 minutes down).** Re-running the startup script after `--update-host` reached `sysctl --system` in `first-boot.sh` (`configure_memory`). That reload re-applied the image's `ip_forward=0`. Docker was already running, and the re-run doesn't restart it, so forwarding stayed off: the app couldn't fetch its secrets, and inbound traffic was dropped. The hot-fix on the VM was `/etc/sysctl.d/99-voyager-docker.conf` (`net.ipv4.ip_forward=1`) plus `sysctl --system`.

What prevents it now:

- `first-boot.sh` writes `/etc/sysctl.d/99-voyager-docker.conf` before anything applies sysctl settings. The file sorts after `60-…`, so it wins at boot and on every reload.
- `first-boot.sh` applies only its own files (`sysctl -p <file>`) and never runs `sysctl --system`.
- `/etc/apt/apt.conf.d/99-voyager-ipfwd`, also written by `first-boot.sh`, is a `DPkg::Post-Invoke` hook. After every dpkg run, unattended upgrades included, it re-applies only `99-voyager-docker.conf`. That covers a package postinst that applies just the image's `60-…` file, which bypasses the file ordering.
- The governor's per-minute guard sets forwarding back to `1` and emails you (section 8). It also keeps the `FORWARD` policy at `DROP`.
- CI's `first_boot_sim.sh` (job `host-checks`) installs the image's `60-gce-network-security.conf`. It then runs a first boot, a re-run on the live VM and a reboot, and checks after each that forwarding stays `1`. It also runs a real `apt-get` in which a simulated postinst applies the `60-…` file alone, and checks that the hook restores `1`.

### Deploys: the SPA, Caddy or the deployer

- **New SPA not showing.** `journalctl -u voyager-deploy -n 50`. `skipping Caddy … held` means a digest failed a check: the email and the log say why. Release it by deleting its line in `/opt/voyager/failed-digests`, or merge a fix (a newer digest ends the hold). `release: …` lines name the check that refused the image (symlink, missing asset, size).
- **`Caddyfile … does not validate`.** The new Caddyfile failed `caddy adapt --validate` with the real `SITE_HOST`; nothing was switched. Fix it in `deploy/gcp/Caddyfile`. To test on the VM by hand: `sudo docker run --rm --network none -e SITE_HOST=… -e ACME_EMAIL=… -v /var/lib/voyager/edge:/edge:ro --entrypoint caddy <CADDY_IMAGE> adapt --config /edge/current/Caddyfile --adapter caddyfile --validate`.
- **Caddy won't start, `/edge/current/Caddyfile: no such file`.** The edge directory is missing or broken. Run `sudo /opt/voyager/deploy.sh`: before anything else it rebuilds `current` from the image pinned in `images.env`, with no registry needed. It refuses to touch Caddy if it can't, and emails you.
- **`GHCR back-off until …`.** GHCR answered `429`. The deployer only converges until the back-off ends. To clear it at once: `sudo rm /run/voyager-deploy/backoff`.
- **A merge didn't reach the VM.** Look at the Deploy run. `promote-app` / `promote-caddy` skipped: `ci` or that image's build job failed (a failed Trivy scan fails the build job; bump the base or the dependency, or, for an accepted finding, add it to `.trivyignore` with a reason). The other image is promoted regardless. `main moved on to …`: a newer merge will publish instead. `app unchanged (inputs …)` / `caddy unchanged`: that image's inputs equal the `prod` image's, so nothing was built and `prod` stayed, by design. `prod moved to … while this run kept …`: `prod` changed under the run (only possible by hand); re-run the workflow. `could not read main's HEAD`: GitHub didn't answer `git ls-remote`; re-run.
- **Prod scan failed** (`prod-scan.yml`). A fixed CRITICAL vulnerability is live. Merge the fix (e.g. a base image bump), or if it's in the base image or a pip dependency, run Deploy by hand: the forced rebuild picks up the newest base and dependencies.
- **A deploy recreated Caddy unexpectedly.** Look for `Caddy runtime changed (… → …)` (a new base image digest or `caddy.Dockerfile` runtime change) or `compose config of Caddy changed` (a new `compose.yaml`). Both drain open streams first, for up to 90 s.

### Rollout of auto-deploy on the existing VM (once)

The VM still runs the old deployer, with the SPA baked into the Caddy image and a weekly Caddy window. Order matters:

1. **Merge, and wait for the Deploy workflow.** The old deployer deploys the new app (it has `/internal/streams`) and only stages the new Caddy image (`new Caddy staged for the night window`). The new image is safe even if the old Sunday window applies it under the old `compose.yaml`: without the edge mount, `/edge/current` in the image points at its own SPA and Caddyfile.
2. `infrastructure/gcp/bootstrap.sh --update-host voyager-prod-ohzkl 010A0B-F39593-14A899 <alert email>`.
3. On the VM: `sudo google_metadata_script_runner startup`. `first-boot.sh` unpacks the kit under the deploy lock (so a timer run never mixes old and new files), creates `/var/lib/voyager/edge` (root, `0755`), restarts `voyager-deploy.timer` on its new 60 s schedule and runs the new `deploy.sh`. Expected in `journalctl -u google-startup-scripts -u voyager-deploy`:
   - `edge: no current release; extracting it from …` (the running image's SPA, kept as an asset fallback)
   - `verifying …`, `pulling …`, then `Caddy runtime changed ( → <id>): recreating Caddy`
   - `drain: no open streams` (or `… still open after 90s; recreating Caddy anyway`)
   - `Caddy healthy on the new runtime: release …`
4. **Downtime:** one Caddy recreate, about 2–5 s of refused connections. Open streams are drained first for up to 90 s. Certificates stay in `caddy_data`. The app isn't restarted by the update. If you ran `--update-host` before the new image was published, Caddy is recreated once for the new `compose.yaml`, still serving the old SPA, and once more when the first labelled image arrives.
5. Check: `sudo cat /opt/voyager/images.env` has `CADDY_CONTENT_IMAGE=`; `ls -l /var/lib/voyager/edge` shows `current`; `systemctl list-timers voyager-deploy.timer` shows a 1-minute cadence; `cat /proc/sys/net/ipv4/ip_forward` prints `1`; `curl -m 10 https://<host>/health` answers. Then merge a frontend-only change and watch `SPA live: release …` with no Caddy restart (`docker ps` shows Caddy's uptime unchanged).
