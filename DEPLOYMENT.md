# Deployment Guide

This app deploys to GCP using Terraform and GitHub Actions. After the initial bootstrap, every push to `main` triggers a full CI → build → deploy pipeline.

## Prerequisites

- GCP account with billing enabled
- `gcloud` CLI authenticated (`gcloud auth login`)
- `terraform` >= 1.6
- `docker`
- `gh` CLI (optional, for repo setup)

## Step 1 — Fork / push to GitHub

Push this repo to GitHub. The CI/CD workflows in `.github/workflows/` require a GitHub repository.

## Step 2 — Run bootstrap

```bash
bash infrastructure/scripts/bootstrap.sh
```

This script:
1. Creates the GCP project
2. Enables APIs
3. Creates a GCS bucket for Terraform state
4. Creates the GitHub Actions service account and downloads a key to `github-sa-key.json`

After it completes, note the `GCP_PROJECT_ID` and `TF_STATE_BUCKET` values it prints.

## Step 3 — Add GitHub Secrets

In your GitHub repository → Settings → Secrets and variables → Actions, add:

| Secret | Value |
|---|---|
| `GCP_PROJECT_ID` | Your GCP project ID (printed by bootstrap.sh) |
| `GCP_SA_KEY` | Content of `github-sa-key.json` (base64 NOT needed — paste raw JSON) |
| `TF_STATE_BUCKET` | Terraform state bucket name (printed by bootstrap.sh) |
| `GCP_BILLING_ACCOUNT` | Your GCP billing account ID (`XXXXXX-XXXXXX-XXXXXX`) |
| `ADMIN_EMAIL` | Email address for monitoring alerts |

## Step 4 — Populate Secret Manager

```bash
bash infrastructure/scripts/populate-secrets.sh
```

This prompts you for:
- `ANTHROPIC_API_KEY`
- `JWT_SECRET_KEY` (generate with `openssl rand -hex 32`)
- `ADMIN_PASSWORD` (initial admin password — you'll be forced to change it on first login)

And stores them in Secret Manager in your GCP project.

## Step 5 — Deploy

```bash
git push origin main
```

GitHub Actions will:
1. Lint → test → security scan
2. Build and push Docker images to Artifact Registry
3. Run `terraform apply` to provision all infrastructure
4. Print `Frontend URL` and `Backend URL` in the workflow output

## Step 6 — Verify

| Check | How |
|---|---|
| App is accessible | Open the Frontend URL in a browser |
| Admin login works | Login with username `admin` and the password you set in Step 4 |
| Forced password change | Create a new user from Admin panel → log in → verify redirect to change-password |
| Search works | Run a trip search and watch results stream in |
| Feedback widget | Submit feedback → check Admin panel → Feedback tab |
| Health endpoint | `curl https://<backend-url>/health` → `{"status":"ok"}` |
| Monitoring | GCP Console → Monitoring → Dashboards → "Travel Planner — Production" |
| Uptime alert | GCP Console → Monitoring → Alerting → verify the 3 alert policies exist |

## Updating

Any push to `main` runs the full pipeline. To deploy a specific commit without changing code, re-run the deploy workflow manually from GitHub Actions → Deploy → Run workflow.

## Estimated Cost

With `min-instances=0` and ~25 users:

| Resource | Monthly Cost |
|---|---|
| Cloud Run backend + frontend | ~€0 (within free tier) |
| Artifact Registry (~2 GB) | ~€0.20 |
| Cloud Storage (backup) | ~€0.03 |
| Secret Manager | ~€0.06 |
| **Total** | **< €1/month** |

If traffic grows, set `min_instance_count = 1` in `modules/backend_service/main.tf` for ~€6-8/month additional.
