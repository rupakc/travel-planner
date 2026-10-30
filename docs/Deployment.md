# Deployment

Travel Planner is deployed on Google Cloud Platform. The backend and frontend each run as separate Cloud Run services. Infrastructure is managed with Terraform. Deployments are triggered by GitHub Actions.

---

## Overview

```
GitHub (push to main)
    │
    ▼
GitHub Actions CI/CD
    ├── Build + push backend Docker image → Artifact Registry
    ├── Build + push frontend Docker image → Artifact Registry
    ├── Run terraform plan + apply
    └── Cloud Run services updated with new image tags

Cloud Run (backend)          Cloud Run (frontend nginx)
    port 8001                    port 8080
    ├── FastAPI app              ├── Serves built React SPA
    ├── SQLite databases         └── Proxies /api/* to backend
    ├── GCS backup every 5m
    └── GCS restore on start
```

---

## Prerequisites

- GCP project with billing enabled
- `gcloud` CLI authenticated (`gcloud auth application-default login`)
- Terraform >= 1.5 installed
- GitHub repository with Actions enabled
- Anthropic API key

---

## Step 1: Bootstrap GCP

Before Terraform can run, a few manual one-time steps are needed to create the state bucket and enable APIs.

```bash
# Set your project
export PROJECT_ID=your-gcp-project-id
gcloud config set project $PROJECT_ID

# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  cloudresourcemanager.googleapis.com

# Create Terraform state bucket
gsutil mb -l europe-west1 gs://${PROJECT_ID}-tf-state

# Create SQLite backup bucket
gsutil mb -l europe-west1 gs://${PROJECT_ID}-db-backup
```

---

## Step 2: Populate secrets in Secret Manager

Terraform reads these secrets at plan/apply time and injects them into Cloud Run as environment variables. Create them before first Terraform run:

```bash
# Anthropic API key
echo -n "sk-ant-api03-..." | gcloud secrets create ANTHROPIC_API_KEY --data-file=-

# JWT secret (generate a strong one)
python3 -c "import secrets; print(secrets.token_hex(32))" | \
  gcloud secrets create JWT_SECRET_KEY --data-file=-

# Admin password
echo -n "YourSecureAdminPassword" | gcloud secrets create ADMIN_PASSWORD --data-file=-
```

---

## Step 3: Configure Terraform variables

Edit `infrastructure/terraform/terraform.tfvars`:

```hcl
project_id       = "your-gcp-project-id"
region           = "europe-west1"
backup_bucket    = "your-gcp-project-id-db-backup"
tf_state_bucket  = "your-gcp-project-id-tf-state"
```

---

## Step 4: Add GitHub Actions secrets

In your GitHub repository settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `GCP_PROJECT_ID` | Your GCP project ID |
| `GCP_SA_KEY` | JSON key for a GCP service account with Cloud Run Admin, Artifact Registry Writer, and Secret Manager Accessor roles |

---

## Step 5: First deployment

Push to `main`. GitHub Actions will:

1. Build the backend image and push to Artifact Registry
2. Build the frontend image and push to Artifact Registry
3. Run `terraform init` and `terraform apply` — this creates the Cloud Run services, sets environment variables from Secret Manager, and configures IAM
4. Both Cloud Run services are live

After the first deployment, get the service URLs:

```bash
cd infrastructure/terraform
terraform output backend_url
terraform output frontend_url
```

---

## Cloud Run configuration

**Backend service:**

| Setting | Value |
|---|---|
| Container port | 8001 |
| CPU | 2 vCPU |
| Memory | 2 GiB |
| Min instances | 1 (to avoid cold start delay) |
| Max instances | 10 |
| Startup probe | `GET /api/health/ready` |
| Timeout | 300s (needed for long SSE streams) |
| Concurrency | 80 |

**Frontend service:**

| Setting | Value |
|---|---|
| Container port | 8080 |
| CPU | 1 vCPU |
| Memory | 512 MiB |
| Min instances | 0 |
| Max instances | 5 |

The frontend nginx config proxies `/api/*` to the backend Cloud Run URL. The backend URL is baked into the nginx config at build time via a Docker build argument set by Terraform.

---

## SQLite backup/restore lifecycle

**On startup (Cloud Run container start):**

1. Application checks for existing database files in `DATA_DIR`
2. If any are missing or empty (fresh container), downloads from GCS backup bucket
3. Startup probe (`/api/health/ready`) passes only after databases are confirmed accessible
4. Cloud Run's startup probe retries until the probe passes, so the container does not receive traffic until restore is complete

**During runtime:**

- A background `asyncio` task runs every 5 minutes, uploading all four `.db` files to GCS
- Each upload is atomic — the file is written to a `.tmp` key and renamed, so a partial upload cannot corrupt the backup

**On shutdown (SIGTERM from Cloud Run):**

- Cloud Run sends SIGTERM 10 seconds before hard-killing the container
- A SIGTERM handler triggers an immediate GCS backup before the process exits
- This ensures the most recent data (up to the last 5 minutes) is preserved even on instance scale-down

---

## Monitoring and logging

**Cloud Logging:** All logs are in JSON format (set via `LOG_FORMAT=json`) and automatically ingested by Cloud Logging. Use the Log Explorer with filter `resource.type="cloud_run_revision"` to query logs.

**Key log fields (structlog):**

| Field | Description |
|---|---|
| `agent` | Which agent emitted the log |
| `phase` | 0, 1, or 2 |
| `duration_ms` | Agent call duration |
| `retry_count` | Number of retries before success |
| `user_id` | Authenticated user (hashed, not plain) |

**Cloud Run metrics:** CPU utilisation, request count, request latency, and container instance count are available in the Cloud Run console under "Metrics". Set up alerting policies for P99 latency > 40s or error rate > 1%.

---

## Rollback procedure

If a deployment introduces a regression:

**Option 1: GitHub Actions redeploy**

Revert the commit and push to `main`. GitHub Actions will rebuild and redeploy from the reverted code.

**Option 2: Cloud Run traffic split (fastest)**

Cloud Run keeps the previous revision. To instantly roll back without a build:

```bash
# Find the previous revision name
gcloud run revisions list --service travel-planner-backend --region europe-west1

# Route 100% traffic to the previous revision
gcloud run services update-traffic travel-planner-backend \
  --region europe-west1 \
  --to-revisions PREVIOUS_REVISION_NAME=100
```

Replace `PREVIOUS_REVISION_NAME` with the revision from the list output.

**Option 3: Database restore**

If you need to restore the SQLite databases to a previous state (e.g. after a bad migration):

```bash
# List available backups
gsutil ls gs://your-backup-bucket/

# Download a specific backup
gsutil cp gs://your-backup-bucket/users.db.backup ./users.db
```

Then restart the Cloud Run service with `gcloud run services update` to trigger a new container start, which will restore from the updated backup.
