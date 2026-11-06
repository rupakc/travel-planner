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
                              └─ host   : egress governor (every minute), deployer (every 5 min),
                                          weekly window (Sun 04:00 Berlin), unattended-upgrades (03:30 Berlin)
GitHub: merge to main → CI → build, sign (cosign) → GHCR `prod` tag ──(pulled by the VM)
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

- **Auto-deploy.** Every merge to `main` that passes all of CI publishes images signed by `deploy.yml` and moves their `prod` tags. Within 5 minutes `voyager-deploy.timer` on the VM resolves `prod` to a digest and checks the cosign signature: it must come from `rupakc/travel-planner`'s `deploy.yml` on `refs/heads/main`. It then pulls by digest, pins the digest in `/opt/voyager/images.env` (keeping the previous one), runs `docker compose up -d`, and waits up to 240 s for the app to report healthy (longer than the container's 180 s start period, so a slow reseed isn't mistaken for a failure). Each run also converges: `compose up -d` brings back anything that was stopped, e.g. by a Docker upgrade.
- **Automatic rollback.** If the new app isn't healthy, the previous digest goes back in. The bad digest is held in `/opt/voyager/failed-digests` and never retried. You get an email if SMTP is set.
- **Manual rollback** to the previous app digest: `sudo /opt/voyager/deploy.sh --rollback`. The digest you rolled back from is **held**: it goes into `/opt/voyager/failed-digests`, so the 5-minute timer doesn't redeploy it while `prod` still points there. Publishing a newer digest ends the hold, because only the listed digests are skipped. To release a held digest by hand, delete its line.
- **No silent downgrades.** An image built by an older deploy run than the running one (label `io.voyager.build`) is refused, even if `prod` points at it. That covers a moved tag and a re-run of an old workflow. To deploy it on purpose: `sudo /opt/voyager/deploy.sh --allow-downgrade`.
- **Caddy** image changes drop open connections, so they are only verified and pre-pulled. They are applied in the weekly window (Sunday 04:00 Berlin). To apply one now: `sudo /opt/voyager/deploy.sh --window`.
- **Logs.** Docker keeps 10 MB × 5 per container on the VM; there is no Cloud Logging agent and so no ingestion bill.
  - `sudo docker compose -f /opt/voyager/compose.yaml --project-directory /opt/voyager logs -f app`
  - `journalctl -u voyager-deploy -u voyager-governor`
- **Host scripts changed** (`deploy/gcp/**`): re-run `infrastructure/gcp/bootstrap.sh --update-host …`, then on the VM run `sudo google_metadata_script_runner startup`. It returns as soon as the bundle is unpacked and `compose up -d` has applied the changes; units are started with `--no-block`, so it never waits on itself.
- **Schema changes stay additive.** A rollback must never meet a DB it can't read.

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

## 10. Cost watch

- **Budgets** (pre-tax, in INR): "Voyager total (alerts)" at ₹2,300 sends email at 50/90/100 % and on forecast; "Voyager Gemini spend cap" at ₹1,800 pauses Gemini when reached. Billing data can lag a day; the on-box governor doesn't.
- **Monthly check:** in Billing → Reports, filter on the project. Expect about $3.65 for the IP, cents for snapshots, $0 for egress and Gemini as used. Also check `governor.py status`, and in GCS that the bucket holds a few MB with no soft-deleted bytes.
- **Never add:** a load balancer, Cloud NAT, Cloud Run, Artifact Registry (image scanning), a logging agent, external IPv6, or a second VM.
- **SerpAPI** (free plan, 250 searches/month): `FARE_WATCH_DAILY_CALL_BUDGET=6` in `app.env`.
