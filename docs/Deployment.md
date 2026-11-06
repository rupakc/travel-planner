# Deployment

## Production: one e2-micro VM on GCP

Production runs on a single always-free **e2-micro VM** in `us-east1` (project `voyager-prod-ohzkl`). Caddy terminates TLS and serves the SPA, the app container runs FastAPI with SQLite on the VM's persistent disk, and Gemini on Vertex AI is called with the VM's service account. Hosting costs about $4 a month; Gemini is capped by a spend cap.

- **Runbook:** [Deployment on GCP](Deployment-GCP.md) covers bootstrap, secrets, first boot, the data migration, deploys and rollback, restore drills, the egress governor and cost watch.
- **Design:** `docs/superpowers/specs/2026-11-06-gcp-lean-deploy-design.md`.
- **Files:**

| Path | What |
|---|---|
| `deploy/gcp/compose.yaml` | app + caddy, images pinned by digest, memory limits, log rotation, health checks |
| `deploy/gcp/Caddyfile`, `deploy/gcp/caddy.Dockerfile` | TLS, SPA caching, `/api` + `/health` proxy (SSE-safe); the Caddy image bakes in the built SPA |
| `deploy/gcp/app.env.example` | non-secret app settings on the VM |
| `deploy/gcp/host/` | `first-boot.sh` (provisioning), `deploy.sh` (signed-digest deployer with rollback), `governor.py` (egress governor), `window.sh`, systemd units |
| `infrastructure/gcp/bootstrap.sh` | idempotent gcloud bootstrap (`--dry-run`, `--update-host`) |
| `infrastructure/gcp/migrate_old_prod.py` | strips the 2026-08-30 export to the users and their data |
| `.github/workflows/deploy.yml` | on every green merge to `main`: build, push to GHCR, sign with cosign, move `prod` |

The VM pulls; CI never has access to it.

### History

The first production ran on Cloud Run (Terraform + a push deploy workflow) from 2026-05 until it was decommissioned on **2026-08-30**. That Terraform, its scripts and the old workflow were removed in the VM deployment change; git history keeps them.

---

## Running locally

```bash
./start.sh                       # dev servers on :8001 and :5174
# or
docker compose up --build        # containers on :8001 and :8080
```

See [Setup and Installation](Setup-and-Installation.md). The documentation site is published separately by `docs.yml` (see [Testing and CI](Testing-and-CI.md#workflows)).

---

## Deploying elsewhere

Any host that can run the containers works. Requirements:

- **One backend process.** Rate limits and the SQLite file are per-process. Give it a persistent volume for `DATA_DIR`. On a single VM like ours, set `BACKUP_MODE=vm` with a `BACKUP_BUCKET` and a marker file (`DATA_DIR/.voyager-data-disk`). On a host with an ephemeral disk, the legacy `BACKUP_MODE=cloudrun` restores at every start and merges.
- **Secrets.** `JWT_SECRET_KEY` is required (`python -m app.entrypoint` refuses to start without it) and so is `ADMIN_PASSWORD`. LLM credentials depend on the provider. `SERPAPI_KEY` and `SERPER_KEY` are optional. They come from the environment, or from Secret Manager through `SECRET_MANAGER_SECRETS`.
- **Origins.** Set `CORS_ORIGINS` to the frontend's origin. Serve the SPA and `/api` from the same origin, as Caddy here or nginx in `frontend/`.
- **Behind a proxy.** Set `FORWARDED_ALLOW_IPS` to the proxy's address or network (never `*`), so rate limits key on real client IPs. In production set `ALLOW_ANONYMOUS_AI=false`.
- **SSE.** The proxy must not buffer or compress `text/event-stream`. The app sends a keepalive every 15 s.
- **Fare and price watches** run inside the backend process when `SERPAPI_KEY` is set. Keep **one** worker. Size `FARE_WATCH_DAILY_CALL_BUDGET` to your SerpAPI plan.
- **Alert emails** need `SMTP_*` and `APP_BASE_URL` set to the public URL, whose host must proxy `/api`.
