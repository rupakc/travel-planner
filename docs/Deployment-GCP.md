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

- `gcloud` CLI installed and signed in as the account that owns the project (`gcloud auth login`).
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

It enables the APIs, creates the `vm-runtime` service account (Vertex AI user, FCM sender, `objectUser` on the backup bucket only, `secretAccessor` on each secret), the static IP, the firewall (80/443 open, 22 only from IAP; the default network's SSH/RDP-from-anywhere rules are deleted), the bucket, the empty secrets, the snapshot schedule, the VM, the uptime check with its alert, and Workload Identity Federation for this repository. The VM starts provisioning itself straight away (section 4); the app waits for its secrets.

Optional overrides via environment: `ZONE`, `BUCKET`, `SITE_HOST` (your own domain), `ACME_EMAIL`, `BUDGET_CURRENCY`/`TOTAL_BUDGET`/`AI_SPEND_CAP` (used only when a budget is missing).

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

`first-boot.sh` installs Docker Engine and the compose plugin, configures zram swap and unattended-upgrades, unpacks the host bundle from instance metadata into `/opt/voyager`, and writes the data-disk marker `/var/lib/voyager/data/.voyager-data-disk`. It also installs the systemd units and runs the first deploy. Each later boot re-runs it, which is harmless.

**Disk benchmark (rollout step 3).** pd-standard is slow (about 3.6 MiB/s). Benchmark it; if image pulls and the first reseed are painful, switch to a 10 GB pd-balanced boot disk (about +$1/month).

```bash
sudo apt-get install -y fio && sudo fio --name=t --filename=/var/lib/voyager/fio.tmp --size=256M \
  --rw=randrw --bs=4k --direct=1 --runtime=30 --time_based && sudo rm /var/lib/voyager/fio.tmp
```

**Smoke test.** Then check:

- `https://<host>/health` shows `"backup_ok":true`.
- Log in, run a search (the results stream) and send a chat message.
- Run a watch check (Alerts → Check now) and send a push to a real phone.
- Reboot: `sudo systemctl reboot`.
- Run both restore drills (section 7) and the governor test (section 8).
- Deploy during an active search: Caddy holds new requests while the app restarts, but open streams end.

## 5. Migrating the old-prod users (decision §13.4)

The 2026-08-30 export is 886 MB, almost all of it a broken `sqlite_sequence` table. Strip it to the user tables on your laptop. The export is opened read-only, and the tool checks its hash before and after:

```bash
python3 infrastructure/gcp/migrate_old_prod.py --out /tmp/voyager-migration/airports.db
cat /tmp/voyager-migration/migration-report.md     # per-table counts must match
```

The dry run on 2026-11-06 migrated users 17, plans 11, preferences 8, taste signals 73 and feedback 2 (about 270 KB). `preferences.visited_destinations` is no longer in the schema and is dropped. Price watches, notifications and devices didn't exist then.

Put the file where restore-if-missing finds it, **before the app first starts** (or stop the app and delete `airports.db` first):

```bash
gcloud storage cp /tmp/voyager-migration/airports.db \
  gs://voyager-prod-ohzkl-voyager-backup/sqlite-backups/airports.db
```

At start, the app sees no DB on the disk, restores this file and reseeds the place data. The old passwords keep working.

## 6. Day-to-day: deploys and rollback

- **Auto-deploy.** Every merge to `main` that passes all of CI publishes images signed by `deploy.yml` and moves their `prod` tags. Within 5 minutes `voyager-deploy.timer` on the VM resolves `prod` to a digest and checks the cosign signature: it must come from `rupakc/travel-planner`'s `deploy.yml` on `refs/heads/main`. It then pulls by digest, pins the digest in `/opt/voyager/images.env` (keeping the previous one), runs `docker compose up -d`, and waits up to 120 s for the app to report healthy.
- **Automatic rollback.** If the new app isn't healthy, the previous digest goes back in. The bad digest is recorded in `/opt/voyager/failed-digests` and never retried. You get an email if SMTP is set.
- **Manual rollback** to the previous app digest: `sudo /opt/voyager/deploy.sh --rollback`.
- **Caddy** image changes drop open connections, so they are only verified and pre-pulled. They are applied in the weekly window (Sunday 04:00 Berlin). To apply one now: `sudo /opt/voyager/deploy.sh --window`.
- **Logs.** Docker keeps 10 MB × 5 per container on the VM; there is no Cloud Logging agent and so no ingestion bill.
  - `sudo docker compose -f /opt/voyager/compose.yaml --project-directory /opt/voyager logs -f app`
  - `journalctl -u voyager-deploy -u voyager-governor`
- **Host scripts changed** (`deploy/gcp/**`): re-run `infrastructure/gcp/bootstrap.sh --update-host …`, then on the VM run `sudo google_metadata_script_runner startup`.
- **Schema changes stay additive.** A rollback must never meet a DB it can't read.

## 7. Backups and restore drills

The disk is authoritative (`BACKUP_MODE=vm`):

- The app restores from GCS **only** when `airports.db` is missing and the data-disk marker is present. It never merges.
- Every 5 minutes it exports the user tables to tmpfs and uploads them only when their SHA-256 changed. It flushes once more on a clean shutdown.
- `/health` reports `backup_ok`. The uptime check alerts you when that is false, or when the site is down, for 10 minutes.
- Daily disk snapshots (kept 7 days, stored in us-east1) are crash-consistent copies of the whole disk.

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

Egress on the Standard tier is free up to 200 GiB a month per billing account, then $0.085/GiB. The governor enforces this on the VM itself (`/opt/voyager/governor.py`, every minute, rules in Docker's `DOCKER-USER` chain):

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
