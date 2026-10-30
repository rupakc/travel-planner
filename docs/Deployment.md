# Deployment

## Current state: decommissioned

Travel Planner ran on Google Cloud Run until **2026-08-30**, when production was decommissioned (PR #1, "chore: decommission GCP deploy pipeline"):

- The GCP project was deleted, together with its Cloud Run services, Artifact Registry, Terraform state bucket, backup bucket and Secret Manager secrets. The old frontend and backend URLs no longer resolve.
- `.github/workflows/deploy.yml` is renamed **"Deploy (decommissioned)"**. Its `push` trigger was removed, so it runs only by hand (`workflow_dispatch`), and a run would fail because the project and secrets no longer exist.
- `infrastructure/` (bootstrap scripts and Terraform) is kept unchanged for reference.
- The backend still contains the GCS backup code (`backend/app/db/backup.py`); it does nothing unless `BACKUP_BUCKET` is set.

There is no hosted instance. To use the app, run it locally (see [Setup and Installation](Setup-and-Installation.md)):

```bash
./start.sh                       # dev servers on :8001 and :5174
# or
docker compose up --build        # containers on :8001 and :8080
```

The documentation site (https://rupakc.github.io/travel-planner/) is separate and still published by `docs.yml`; see [Testing and CI](Testing-and-CI.md#workflows).

---

## What the retained setup deploys

| Piece | Where |
|---|---|
| Backend image | `backend/Dockerfile` (python:3.12-slim, built from the repo root; copies `backend/` and `.agents/`; uvicorn on 8001, 1 worker) |
| Frontend image | `frontend/Dockerfile` (node:20-alpine build, nginx:alpine on 8080; `BACKEND_URL` templated into `nginx.conf.template`) |
| Cloud Run backend | `travel-planner-backend`, 2 vCPU / 2 GiB, **min = max = 1 instance** (the SQLite file and the in-process rate limiter assume a single process) |
| Cloud Run frontend | `travel-planner-frontend`, 1 vCPU / 512 MiB, 0–3 instances |
| Storage | `<project>-sqlite-backup` bucket for SQLite snapshots; `<project>-tf-state` for Terraform state |
| Secrets | Secret Manager: `anthropic-api-key`, `jwt-secret-key`, `admin-password`, `serpapi-key`, `serper-key` |
| Other modules | Artifact Registry, IAM, monitoring (uptime check on `/health`, alert policies, log metrics, dashboard), project APIs |

Terraform lives in `infrastructure/terraform/` (modules `artifact_registry`, `backend_service`, `frontend_service`, `iam`, `monitoring`, `project`, `secrets`, `storage`). The backend service sets `DATA_DIR=/tmp/data`, `AGENTS_DIR=/app/.agents`, `LOG_FORMAT=json`, `BACKUP_BUCKET` and `CORS_ORIGINS` (the frontend URL), and injects the secrets as environment variables.

Cloud Run's disk is ephemeral, which is why backups exist: on start the backend restores the database from the bucket, uploads a snapshot every 60 s and uploads once more on shutdown (see [Architecture](Architecture.md#backups-optional)).

---

## Redeploying to GCP

A redeploy creates a **new** project; nothing from the old one can be recovered from GCP. These steps follow the retained scripts and workflow; they have not been run since the decommissioning, so expect to fix drift (provider versions, API changes).

### 1. Bootstrap the project

You need the `gcloud` CLI, authenticated, and a billing account.

```bash
BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX bash infrastructure/scripts/bootstrap.sh
# optional: PROJECT_NAME=travel-planner REGION=europe-west1
```

`bootstrap.sh` creates the project `<PROJECT_NAME>-prod`, links billing, enables the Cloud Run, Artifact Registry, Secret Manager, Storage, IAM, Resource Manager, Compute, Monitoring and Logging APIs, creates the versioned `<project>-tf-state` bucket, and creates a `github-actions-sa` service account with deploy roles. It writes a key file, `github-sa-key.json`, to the current directory. Keep it out of git and delete it once it is stored as a secret.

### 2. Add the GitHub repository secrets

| Secret | Value |
|---|---|
| `GCP_PROJECT_ID` | The new project ID (`<PROJECT_NAME>-prod`) |
| `GCP_SA_KEY` | Contents of `github-sa-key.json` |
| `ANTHROPIC_API_KEY` | Anthropic key |
| `JWT_SECRET_KEY` | A random secret, for example `openssl rand -hex 32` |
| `ADMIN_PASSWORD` | Password for the seeded admin |
| `SERPAPI_KEY` | SerpAPI key (live flights, fare calendar) |
| `SERPER_KEY` | Serper key (Places to See, link resolution) |

The workflow's bootstrap job copies the last five into Secret Manager. (`infrastructure/scripts/populate-secrets.sh` does the same interactively, after Terraform has created the secret shells; you need one or the other, not both.) `bootstrap.sh` also prints `TF_STATE_BUCKET` and `GCP_BILLING_ACCOUNT`; the current workflow derives the state bucket from the project ID and does not read either.

Also check the `terraform` job's environment in `deploy.yml`: `TF_VAR_admin_email` is hard-coded and receives monitoring alerts. See `infrastructure/terraform/terraform.tfvars.example` for the Terraform variables (`project_id`, `region`, `admin_email`, `backend_image`, `frontend_image`, `frontend_url`).

### 3. Re-enable and run the workflow

Edit `.github/workflows/deploy.yml`: remove the DECOMMISSIONED banner, rename it, and, if you want automatic deploys again, restore the trigger:

```yaml
on:
  push:
    branches: [main]
  workflow_dispatch:
```

Then run it from the Actions tab (or push to `main`). Its three jobs:

1. **bootstrap**: enables the APIs, creates the Terraform state bucket and the `travel-planner` Artifact Registry repository if missing, and upserts the Secret Manager secrets from the GitHub secrets.
2. **push-images**: builds both images with Buildx (`docker buildx build -f backend/Dockerfile .` and `frontend/`), tagged with the commit SHA and `latest`, and pushes them to `europe-west1-docker.pkg.dev/<project>/travel-planner`.
3. **terraform**: `init` against the state bucket, `validate`, imports resources that exist in GCP but not in state, reads the frontend URL for `CORS_ORIGINS`, then `plan` and `apply`, and prints both service URLs.

On the very first apply the frontend does not exist yet, so CORS falls back to localhost; run the workflow a second time to pick up the frontend URL.

### 4. After the first deploy

- Sign in as `admin` with `ADMIN_PASSWORD` and create users from the Admin page; there is no self-registration.
- Check `GET /health` and `GET /health/agents` on the backend URL.
- The place data seeds itself on the first start (about 2 s). Backups leave the place tables out, so every restore reseeds them.

---

## Deploying elsewhere

Any host that can run the two containers works. Requirements:

- One backend process (rate limits and the SQLite file are per-process), with a persistent volume for `DATA_DIR`, or `BACKUP_BUCKET` and GCS credentials if the disk is ephemeral.
- `ANTHROPIC_API_KEY`, `JWT_SECRET_KEY` and `ADMIN_PASSWORD` set; `SERPAPI_KEY` and `SERPER_KEY` optional.
- `CORS_ORIGINS` set to the frontend's origin, and `BACKEND_URL` for the frontend container.
- If the backend sits behind a proxy, run uvicorn with `--proxy-headers` so anonymous rate limits key on real client IPs.

`docker-compose.yml` is a working single-host example (see [Setup and Installation](Setup-and-Installation.md#option-c-docker-compose)).
