#!/usr/bin/env bash
# Bootstrap script — run once to set up GCP infrastructure prerequisites.
# Requires: gcloud CLI authenticated, billing account ID.
set -euo pipefail

# ─── Config ───────────────────────────────────────────────────────────────────
BILLING_ACCOUNT="${BILLING_ACCOUNT:-}"
PROJECT_NAME="${PROJECT_NAME:-travel-planner}"
REGION="${REGION:-europe-west1}"

if [[ -z "$BILLING_ACCOUNT" ]]; then
  echo "Usage: BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX bash bootstrap.sh"
  exit 1
fi

PROJECT_ID="${PROJECT_NAME}-prod"
TF_STATE_BUCKET="${PROJECT_ID}-tf-state"

echo "=== Bootstrap: $PROJECT_ID ==="

# ─── Create project ───────────────────────────────────────────────────────────
if ! gcloud projects describe "$PROJECT_ID" &>/dev/null; then
  gcloud projects create "$PROJECT_ID" --name="$PROJECT_NAME"
fi
gcloud config set project "$PROJECT_ID"
gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"

# ─── Enable APIs ──────────────────────────────────────────────────────────────
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  iam.googleapis.com \
  cloudresourcemanager.googleapis.com \
  compute.googleapis.com \
  monitoring.googleapis.com \
  logging.googleapis.com

# ─── Terraform state bucket ───────────────────────────────────────────────────
if ! gcloud storage buckets describe "gs://$TF_STATE_BUCKET" &>/dev/null; then
  gcloud storage buckets create "gs://$TF_STATE_BUCKET" \
    --project="$PROJECT_ID" \
    --location="$REGION" \
    --uniform-bucket-level-access
  gcloud storage buckets update "gs://$TF_STATE_BUCKET" --versioning
fi

# ─── GitHub Actions service account ──────────────────────────────────────────
SA_EMAIL="github-actions-sa@${PROJECT_ID}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "$SA_EMAIL" &>/dev/null; then
  gcloud iam service-accounts create github-actions-sa \
    --display-name="GitHub Actions Deployer" \
    --project="$PROJECT_ID"
fi

for role in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser roles/editor roles/storage.admin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="$role" \
    --quiet
done

# Download key
KEY_FILE="github-sa-key.json"
gcloud iam service-accounts keys create "$KEY_FILE" \
  --iam-account="$SA_EMAIL" \
  --project="$PROJECT_ID"

echo ""
echo "=== Bootstrap complete ==="
echo ""
echo "Add these GitHub repository secrets:"
echo "  GCP_PROJECT_ID    = $PROJECT_ID"
echo "  GCP_SA_KEY        = (content of $KEY_FILE)"
echo "  TF_STATE_BUCKET   = $TF_STATE_BUCKET"
echo "  GCP_BILLING_ACCOUNT = $BILLING_ACCOUNT"
echo ""
echo "Then run: bash infrastructure/scripts/populate-secrets.sh"
echo "And push to main to deploy."
