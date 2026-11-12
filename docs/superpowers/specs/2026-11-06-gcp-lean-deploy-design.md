# Voyager on GCP for < $30/month — deployment design (v5, final for review)

Grounding: measured runtime profile (`scratchpad/gcp-plan/runtime-profile.md`), official prices fetched
2026-11-06 (`scratchpad/gcp-plan/pricing-facts.md`), four rounds of adversarial review
(`critique-cost-r1.md`, `critique-reliability-r1.md`, Rounds 1–4). Round 4: cost **APPROVE**, reliability
**APPROVE with conditions** — the conditions are folded in below (§2.2, §2.3, §12). §11/§12 list every
finding and its fix.

## 0. The idea in one paragraph
Run the existing app container on Google's **always-free e2-micro VM** with SQLite on its persistent
disk. Everything the app does today — durable writes, the in-process price-watch scheduler, push
delivery, 80-second AI streams — keeps working with small changes, and the bill is **flat ≈ $4/month**.
The usual ways a small deployment blows its budget (autoscaling compute, load balancers, NAT, image
scanning, log volume, egress floods) are each designed out or capped **on the box itself**, so the
guarantee doesn't depend on billing data that can lag a day.

(v1–v2 used Cloud Run scale-to-zero at ≈ $0.50/month. Reviews showed SQLite on vanishing, overlapping,
CPU-throttled instances needs fencing, commit-before-reply uploads, client retries and a brake — the
riskiest code in the app to save ≈ $3.50. It stays documented as Option B in §9.)

## 1. What the app needs (measured)
| Need | Measured | On an e2-micro (shared 2 vCPU, bursts; 1 GB RAM) |
|---|---|---|
| CPU | A search: 0.7–2.0 CPU-s over ~80 s | 3–10 concurrent searches sustained; spikes fit the burst |
| Memory | 117–145 MB idle, 209 MB peak; DB 45 MB | ≈ 600–750 MB peak with OS + Docker + Caddy; container memory limits + zram (no swapfile on the slow disk) |
| State | SQLite; user data ≈ 1 MB, place data ≈ 45 MB | On the persistent disk — the disk is the source of truth |
| Long requests | Search ~80 s, worst > 300 s | No platform timeout; Caddy streams SSE |
| Background | Watch tick (300 s), backup loop | Run in-process, always-on CPU |

## 2. Architecture (Option A — recommended)
```
Browser / Android ──HTTPS (IPv4 only)──► e2-micro VM, us-east1, Standard network tier
                                         Debian 13 · unattended-upgrades (+ one weekly night reboot window, Berlin time)
                                         Docker Engine + compose plugin, systemd-managed
                                          ├─ caddy  : TLS for your domain, SPA files, /api + /health → app,
                                          │           SSE flushing, persistent /data volume (certs)
                                          ├─ app    : FastAPI + SQLite (WAL) on the persistent disk
                                          └─ host   : egress governor (nftables + per-minute counter),
                                                      image-pull deployer (systemd timer), log rotation
        ├── backup: changed user tables → GCS (us-east1, free tier) via tmpfs export
        ├── PD snapshot schedule: daily, keep 7, storage location us-east1
        └── FCM push via the VM service account (ADC)
GitHub Actions (free): test → build → push to GHCR (public, free) → move the `prod` tag
VM pulls `prod` by digest (no inbound deploy access, no CI root on the box)
Secrets: Secret Manager → fetched at container start into memory (tmpfs), never on the disk
Monitoring: free uptime check + email alert; budget $10 with email alerts
```

### 2.1 Durability on a VM (fixes the Cloud Run-era backup code)
- New `BACKUP_MODE=vm`: **the local disk is authoritative.** Restore from GCS only if the DB file is
  missing (fresh disk), after deleting stray `-wal`/`-shm`. No startup merge, ever (merging would revive
  deleted watches, devices, plans and taste resets).
- Backup exports **only user tables** into tmpfs, uploads only when the export's hash changed, every
  5 min, plus once at clean shutdown (`--timeout-graceful-shutdown 5`, compose `stop_grace_period: 20s`).
- **Mount guard:** restore runs only if the data directory is the mounted persistent disk (never on an
  empty, unmounted path that could later overwrite GCS).
- Backup status (last success time) is reported in `/health`; a free uptime-check **content match**
  alerts if backups stop.
- SQLite WAL + `synchronous=NORMAL` on PD is crash-safe; nightly PD snapshots are crash-consistent
  copies of the whole disk. Worst case after losing the disk itself: ≤ 5 min of user changes.
- Restore drill before go-live: (a) fresh disk ← GCS; (b) new VM ← PD snapshot.

### 2.2 The cost guarantee, on the box
- **Egress governor (tiered, so no single abuser can take the site down for a month):**
  Standard-tier egress is free up to 200 GiB/month per billing account, then $0.085/GiB; the VM can
  send 1 Gbps. A systemd timer adds up per-minute TX deltas (reboot-safe, atomically persisted; after a
  disk restore it takes the larger of its total and Monitoring's `sent_bytes_count`). The month resets
  at **00:00 America/Los_Angeles** (Google's billing month). Rules live in Docker's **`DOCKER-USER`**
  chain (an INPUT rule would not stop DNAT'd traffic to Caddy) and are re-applied after Docker starts;
  closure is verified by a curl from outside during rollout.
  | Month-to-date egress | Action |
  |---|---|
  | always | per-source-IP bandwidth meter (nftables) + `tc` shaper ≈ 50 Mbit/s; top talkers logged |
  | 150 GiB | email warning (SMTP on 587, or a custom metric → free alert); shape to 20 Mbit/s |
  | 200 GiB (free allowance used) | shape to 10 Mbit/s; email |
  | 400 GiB (≈ $17 overage) | close 80/443 until the month resets or you reopen; email |
  Worst-case GCP bill ≈ $4 + $17 ≈ **$21 < $30**, and a single abusive IP is throttled long before.
- **IPv4 only:** a VM's external IPv6 is Premium tier (outside the 200 GiB). IPv6-only phones still
  reach IPv4 via carrier NAT64.
- **No Cloud Logging volume:** logs stay on the VM (Docker `json-file`, 10 MB × 5 per container);
  no logging agent → no ingestion bill; errors are visible via `docker logs` over IAP.
- **Fixed compute:** one VM; a flood makes the app slower, never pricier. App limits still apply:
  AI routes require sign-in in production, login rate limit, real-client-IP rate limits.

### 2.3 Deploys
- CI runs tests, builds `ghcr.io/rupakc/travel-planner-{app,caddy}`, and moves the `prod` tag only on a
  manual "promote" (not every merge).
- Images are **signed in CI** (cosign keyless / build provenance); only the manual promote job, behind a
  protected GitHub environment, can move the `prod` tag.
- On the VM a timer resolves `prod` to a digest every 5 min, **verifies the signature**, writes the
  digest into the compose env file and pulls by digest (new layers land before anything stops), then
  `up -d`, polls `/health`, and **rolls back to the previous digest automatically** if it fails. Caddy
  holds requests briefly (`lb_try_duration 30s`) during app restarts; Caddy itself changes rarely and
  only in the night window.
- Schema changes stay additive (all existing migrations are), so a rollback never meets an incompatible
  DB.

## 3. Monthly cost (official prices, us-east1)
| Item | Cost |
|---|---|
| e2-micro VM | **$0.00** (Always Free) |
| 30 GB pd-standard (boot + data, total ≤ 30 GB) | **$0.00** (Always Free) |
| Static external IPv4 (in use) | **$3.65** ($0.005/h) |
| Egress, Standard tier | **$0.00** (≤ 200 GiB, enforced on the box) |
| PD snapshots (regional us-east1, ~2–5 GB incremental) | ≈ $0.10–0.30 |
| GCS backup bucket | $0.00 (5 GB free in us-east1; soft delete off) |
| Secret Manager, uptime check, alerting, IAP, OS Login | $0.00 |
| GHCR, GitHub Actions | $0.00 |
| **Total GCP** | **≈ $3.75–3.95 / month** (≈ $4.50–4.70 incl. 19 % VAT) |
| Optional: faster pd-balanced 10 GB boot disk if the disk benchmark is poor | + ≈ $1.00 |
| Your own domain (outside GCP, e.g. `.de`/`.com`) | ≈ $0.80–1.20 / month |

Worst case under any traffic: ≈ $21 (the governor's 400 GiB hard stop); normal ≈ $4. Not GCP: Anthropic (set a monthly limit in
the Anthropic console) and SerpAPI (free plan, daily budget 8 calls).

## 4. Guardrails
1. Fixed compute + on-box egress governor + no log ingestion → the GCP bill cannot run away.
2. Budget $10 **before tax** (≈ $11.90 with VAT), email alerts at 50/90/100 % actual + forecast.
3. Uptime check (free) → email if the site is down 10 min (incl. a governor closing the ports).
4. No LB, NAT, Cloud SQL, Cloud Run, Artifact Registry, scanning, versioned objects, soft delete,
   or IPv6 egress.

## 5. Code & config changes
1. **Backup `vm` mode** (§2.1): disk-authoritative, restore-if-missing, no merge, user-table export in
   tmpfs, change counter, 5-min cadence; Cloud Run mode unchanged.
2. **Secrets at start:** small entrypoint fetches named secrets from Secret Manager with the VM's
   identity into process env; refuse to start with an empty `JWT_SECRET_KEY`.
3. **Proxy/IP:** uvicorn `--proxy-headers --forwarded-allow-ips=<compose network range>`; app port never
   published; login rate-limit bucket; `ALLOW_ANONYMOUS_AI=false` in prod.
4. **FCM via ADC** (VM service account, `cloud-platform` scope + IAM roles), key file as fallback;
   Android `google-services.json` from the new Firebase project; Android `prod` URL = your domain.
5. **Slim image** (drop unused `claude-agent-sdk`, `python-dotenv`); stable layer order.
6. **SSE hygiene:** 15 s keepalives in search Phase 1 and chat; cancel agent tasks when the client
   disconnects.
7. **`deploy/gcp/`:** `compose.yaml` (memory limits measured under load — start app 550 MB, caddy 96 MB; log rotation; health
   checks; restart policies), `Caddyfile`, Caddy image with the built SPA, host scripts (tiered egress
   governor, signed-digest deployer, zram), cloud-init for first boot.
8. **`infrastructure/gcp/bootstrap.sh`** (idempotent gcloud), **`.github/workflows/deploy.yml`**
   (test → build → GHCR; promote job), **`docs/Deployment-GCP.md`** runbook; remove the old Cloud Run
   Terraform/workflow so nobody applies it by mistake.

## 6. Infrastructure
- New project under **rupak97.4@gmail.com**; APIs: compute, iap, oslogin, secretmanager, monitoring,
  storage, fcm, billingbudgets (no Cloud Run, AR, scanning).
- VM: e2-micro, us-east1, Debian 13, 30 GB pd-standard, static IPv4 on **Standard** tier, no IPv6,
  Shielded VM, OS Login, `cloud-platform` scope with a dedicated **vm-runtime** service account
  (bucket `objectUser` on the backup bucket only, `secretAccessor` on its secrets, FCM send).
- Firewall: 80/443 from anywhere; 22 only from IAP (35.235.240.0/20). No inbound deploy path.
- Snapshot schedule: daily, keep 7, storage location us-east1.
- Bucket (us-east1): uniform access, public access prevention, soft delete off, versioning with a
  newer-versions cap, lifecycle 30 days.
- DNS: A record for your domain → the static IP (at your registrar; no Cloud DNS bill).

## 7. Rollout (with checks)
1. Confirm the billing account has nothing else using the free tiers.
2. `bootstrap.sh` with you (you paste secret values; I never see them).
3. **Disk benchmark** (`fio` on pd-standard); switch the boot disk to 10 GB pd-balanced (+$1) only if
   image pulls/backups are visibly slow.
4. Data: fresh start, or migrate old-prod users/plans (strip the 886 MB export to user tables offline,
   verify row counts per table, place on the disk before first start).
5. Promote the first image; smoke-test web, Android prod build, a search (SSE), a watch tick, a push,
   both restore drills, a reboot, a deploy during an active search, and the governor (lower its
   threshold temporarily, confirm ports close and the alert arrives, restore).
6. Watch billing for 48 h; hand over the runbook.

## 8. Decisions for you
1. **Option A (VM, ≈ $4 flat, simplest, recommended)** or Option B (Cloud Run, ≈ $0.50, complex).
2. **Region:** us-east1 (free VM; ~100–130 ms from Germany, invisible on 80-second AI streams). An EU VM
   would cost ≈ $10/month more.
3. **Domain:** buy one (≈ $10/year; recommended before the Android release bakes the URL in) — or start
   on a free `sslip.io` name and switch later.
4. **Data:** fresh start or migrate old-prod users/plans.
5. **Billing:** new project under rupak97.4@gmail.com; confirm nothing else bills on that account.

## 9. Option B — Cloud Run scale-to-zero (≈ $0.30–0.60/month), not recommended now
Viable if traffic becomes spiky/global. Needs: commit-before-reply user-table uploads through one
paced uploader (GCS ≤ 1 write/s per object), generation fencing that re-imports instead of going
read-only, client retry/idempotency on web + Android, alerts delivered only after durable commits, an
HTTP tick with in-app OIDC checks, a multi-metric brake that reopens automatically, no image scanning,
log exclusions, a Cloud Run spend cap.

## 10. Other options rejected
| Option | Monthly | Why not |
|---|---|---|
| e2-micro in europe-west1 (paid) | ≈ $10.4 | Pays to save ~100 ms on 80-second AI streams |
| Cloud Run min-instances=1 | ≈ $10–14 | Idle compute for a 2 %-CPU app |
| Cloud Run *instances* (Preview) | ≈ $6 | Preview, no SLA, no persistent disk |
| Firebase Hosting + Cloud Run | ≈ Option B | 60 s rewrite timeout breaks 80 s searches |
| Cloud SQL / Firestore | ≥ $7–10 / rewrite | For 1 MB of data |
| IPv6-only VM | ≈ $0.2 | Many networks still lack IPv6; IPv6 egress is Premium tier anyway |
| Load balancer for a domain | ≈ $18+ | Caddy does TLS for free |

## 11. Review findings → fixes (rounds 1–3)
| Round | Finding | Fix |
|---|---|---|
| 1–2 | Cloud Run: stale overwrites, fail-open restore, after-response uploads, OOM w/o SIGTERM, fencing outages, no client retries, 1 write/s GCS limit, brake as an off-switch | Design moved to a VM; Cloud Run kept as Option B with the full fix list |
| 1 | Image scanning $0.26/image | No Artifact Registry; GHCR |
| 1 | Budgets/spend caps lag and don't cap | On-box governor + fixed compute; budget only as a backstop |
| 3 | Egress past 200 GiB uncapped (1 Gbps) | Egress governor closes ports at 190 GiB + tc shaper + alert |
| 3 | Logging either uncapped or absent | Local rotated logs, no ingestion agent |
| 3 | IPv6 egress is Premium tier | IPv4 only |
| 3 | Snapshots not free, multi-region default | Regional us-east1, keep 7; ≈ $0.10–0.30 |
| 3 | Backup code restores over the disk at every start; merge revives deletions | `BACKUP_MODE=vm`: disk authoritative, restore-if-missing, no merge |
| 3 | pd-standard 30 GB is slow (3.6 MiB/s); 45 MB per-minute backup copies | User-table export in tmpfs, 5-min cadence, change counter; fio benchmark; optional pd-balanced |
| 3 | COS has no compose and doesn't auto-patch by default | Debian 12 + unattended-upgrades + weekly reboot window |
| 3 | Let's Encrypt duplicates/shared limits; sslip.io dependency | Persistent Caddy `/data`; own domain recommended |
| 3 | Memory ~600–750 MB peak on 1 GB | Container memory limits + swapfile |
| 3 | IAP SSH push deploy = CI gets root; missing OS Login API | Pull-based deploy by digest; manual promote |
| 3 | Narrow VM scopes break ADC; secrets must not hit the disk | `cloud-platform` + IAM; secrets fetched into memory |
| 3 | Deploy restarts kill streams; every merge deploys | Pull-before-stop, Caddy request holding, manual promote |
| 3 | GCS soft delete billed; 60 s loop = 43k ops/month | Soft delete off; change counter; 5-min cadence |
| 1–3 | VAT, per-account free tiers, Anthropic is the real cost | $10 budget incl. VAT; billing-account check; Anthropic limit |

## 12. Round 4 conditions → folded in
| Finding | Fix |
|---|---|
| Firewall INPUT rule wouldn't stop Docker-published ports | Governor rules in `DOCKER-USER`, re-applied after Docker starts; tested from outside |
| One client could close the site for the month | Tiered governor (shape at 150/200 GiB, close at 400 GiB ≈ $17), per-IP meter, top-talker log |
| Counter resets on reboot; month boundary | Persisted deltas; reset at 00:00 America/Los_Angeles; Monitoring cross-check after restore |
| No outbound port 25 for warnings | SMTP 587, or custom metric → free alert |
| `compose pull` re-reads the tag; image provenance | Pin by verified digest; cosign/provenance; protected promote job; auto-rollback on failed health |
| Unmounted data dir could trigger a stale restore | Mount guard |
| `data_version` misses same-connection writes | Hash of the export |
| Swapfile on pd-standard thrashes and bloats snapshots | zram |
| Debian 12 past regular security support | Debian 13 |
| Backup failures invisible | Backup status in `/health` + uptime content match |
| Budgets are pre-tax | $10 pre-tax (≈ $11.90 incl. VAT) |
| 450 MB app limit ≈ 4 searches | Limit measured under load during rollout (start 550 MB) |

## 13. Decisions (user, 2026-11-06)
1. **Option A** — always-free e2-micro VM.
2. **Region us-east1.**
3. **Free domain now** (`sslip.io` hostname from the static IP); own domain later (one Caddyfile line + Android `PROD_BASE_URL` update).
4. **Migrate old-prod users with their own data** (plans, preferences, taste signals, recent searches, feedback) from `~/gcp-decommission-export-20260830`; price watches/notifications did not exist then.
5. **New project under rupak97.4@gmail.com.**
6. **Auto-deploy:** a merge to `main` deploys automatically once every CI job passes (supersedes the manual promote in §2.3). The signed-digest pull, health check and automatic rollback stay.
7. **LLM provider: Anthropic → Gemini on Vertex AI ("Agent Platform"), authenticated with the VM's service account (ADC, no API key):**
   - specialist agents (all 13 + packing, pricing advisor, itinerary, stress test, chat routing/extraction, chat itinerary) → **Gemini 3.5 Flash-Lite** ($0.30 / $2.50 per 1M input/output, official price page 2026-11-06), thinking kept low;
   - chat conversational replies → **Gemini 3.8 Flash** ($0.75 / $3.75 until 2026-12-31, then $1.50 / $7.50).
   - Estimated ≈ $0.11 per full search vs ≈ $0.23 on Claude Haiku 4.5 (to be measured on real searches before switching).
8. **AI spend hard cap $20/month (VAT applies: personal account)** via a spend-cap budget on Agent Platform (Gemini); with ≈ $4–5 hosting the whole GCP bill stays < $30. When the cap trips, AI features pause until the next month; the app shows a friendly "AI limit reached for this month" message.

9. **Governor re-tuned for the $25 AI cap:** with $25 reserved for Gemini, hosting may not exceed ≈ $5, so the
   governor's hard stop moves from 400 GiB to **200 GiB (zero overage)**. To keep one abuser from closing the site,
   each source IP gets a **daily byte quota (≈ 3 GiB/day) and ≈ 4 Mbit/s** — a single IP would need > 60 days to
   reach 200 GiB; the 150 GiB warning email still fires first. Hosting worst case ≈ **$4.0 pre-tax**.

Budget summary after decisions: hosting ≤ ≈ $4.0 + Gemini ≤ $25 (hard cap) → **≤ ≈ $29 pre-tax, worst case**;
≈ $5–15 in a normal month (≈ 50–100 searches). Google budgets and caps are pre-tax: if 19 % VAT applies to
your account, the gross worst case is ≈ $34.5 — set the Gemini cap to **$20** to stay under $30 gross.

**Final cap (user, 2026-11-06): VAT is added → Gemini spend cap $20/month.** Worst case ≈ $4 + $20 = $24
pre-tax ≈ **$28.6 incl. 19 % VAT**. Governor stays at 200 GiB (zero overage).
