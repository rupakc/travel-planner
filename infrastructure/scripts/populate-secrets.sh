#!/usr/bin/env bash
# Populate Secret Manager secrets.
# Run after bootstrap.sh and after terraform apply has created the secret shells.
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project)}"

echo "=== Populating secrets in project: $PROJECT_ID ==="

set_secret() {
  local name="$1"
  local value="$2"
  echo -n "$value" | gcloud secrets versions add "$name" \
    --data-file=- \
    --project="$PROJECT_ID"
  echo "  ✓ $name"
}

# ANTHROPIC_API_KEY
read -rsp "ANTHROPIC_API_KEY: " ANTHROPIC_API_KEY; echo
set_secret "anthropic-api-key" "$ANTHROPIC_API_KEY"

# JWT_SECRET_KEY
echo ""
echo "Generating JWT_SECRET_KEY..."
JWT_SECRET=$(openssl rand -hex 32)
set_secret "jwt-secret-key" "$JWT_SECRET"
echo "  (auto-generated; no need to record it)"

# ADMIN_PASSWORD
read -rsp "ADMIN_PASSWORD (initial admin account password): " ADMIN_PASSWORD; echo
set_secret "admin-password" "$ADMIN_PASSWORD"

echo ""
echo "=== All secrets populated ==="
echo "Push to main to trigger deployment."
