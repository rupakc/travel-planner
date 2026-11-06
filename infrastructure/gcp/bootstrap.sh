#!/usr/bin/env bash
# Voyager on GCP — one-time, idempotent bootstrap of the lean VM deployment
# (docs/superpowers/specs/2026-11-06-gcp-lean-deploy-design.md, Option A).
#
#   infrastructure/gcp/bootstrap.sh --dry-run PROJECT_ID BILLING_ACCOUNT ALERT_EMAIL
#   infrastructure/gcp/bootstrap.sh           PROJECT_ID BILLING_ACCOUNT ALERT_EMAIL
#   infrastructure/gcp/bootstrap.sh --update-host PROJECT_ID BILLING_ACCOUNT ALERT_EMAIL
#
# Example: voyager-prod-ohzkl 010A0B-F39593-14A899 you@example.com
#
# Creates (skipping anything that already exists):
#   project (only if missing) + billing link (only if unlinked)
#   APIs: compute, iap, oslogin, secretmanager, monitoring, storage, fcm,
#         billingbudgets, aiplatform — plus the plumbing gcloud needs for the
#         rest: iam (service account, custom roles), cloudresourcemanager (IAM
#         bindings), cloudbilling (billing link)
#   service account vm-runtime (the VM) with two custom least-privilege roles:
#   Gemini prompts only (aiplatform.endpoints.predict) and FCM send only
#   (cloudmessaging.messages.create); objectUser on the bucket, secretAccessor
#   per secret
#   static IPv4 (Standard tier), firewall 80/443 + IAP-only 22
#   e2-micro VM in us-east1, Debian 13, 30 GB pd-standard, Shielded VM,
#   OS Login, cloud-platform scope (least privilege is in IAM)
#   daily snapshot schedule (keep 7, storage location us-east1)
#   backup bucket (us-east1, uniform access, PAP, no soft delete, capped
#   versioning, 30-day noncurrent lifecycle)
#   Secret Manager secrets, created EMPTY (you add versions; see the runbook)
#   budget "Voyager total (alerts)": ₹2,300/month (pre-tax), 50/90/100 % +
#   forecast alerts; "Voyager Gemini spend cap": ₹1,800/month hard cap on
#   Gemini Enterprise Agent Platform (Vertex AI). Skipped when they exist.
#   uptime check on https://<host>/health matching "backup_ok":true + email alert
#
# Never: a load balancer, NAT, Cloud Run, Artifact Registry, IPv6, logging
# agents, no CI identity in GCP (CI signs with Sigstore and pushes to GHCR;
# the VM pulls). Existing resources are never modified, except IAM bindings
# and custom-role permissions, which are re-asserted.
#
# --dry-run prints every command and calls nothing (no gcloud needed).
#
# Needs gcloud's `beta` component (notification channels have no GA command
# yet); a real run checks for it first and stops with the install command.
# Billing calls use the project as their quota project
# (CLOUDSDK_BILLING_QUOTA_PROJECT), not the account's default project.
# --update-host only refreshes the VM's host bundle metadata (after changes
#   to deploy/gcp); then on the VM: sudo google_metadata_script_runner startup
set -euo pipefail

DRY_RUN=0
UPDATE_HOST=0
while [[ $# -gt 0 && "$1" == --* ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --update-host) UPDATE_HOST=1 ;;
    -h | --help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done
[[ $# -eq 3 ]] || { echo "usage: $0 [--dry-run|--update-host] PROJECT_ID BILLING_ACCOUNT ALERT_EMAIL" >&2; exit 2; }

PROJECT_ID="$1"
BILLING_ACCOUNT="$2"
ALERT_EMAIL="$3"

REGION="${REGION:-us-east1}"
ZONE="${ZONE:-us-east1-b}"
VM="${VM:-voyager-vm}"
IP_NAME="${IP_NAME:-voyager-ip}"
BUCKET="${BUCKET:-$PROJECT_ID-voyager-backup}"
ACME_EMAIL="${ACME_EMAIL:-$ALERT_EMAIL}"
# Amounts are in the billing account's currency. The voyager billing account
# is in INR: ₹2,300 ≈ \$27 total alerts, ₹1,800 ≈ \$21 Gemini hard cap.
# Both budgets already exist there (created in the console, 2026-11-06); they
# are found by display name and never duplicated.
BUDGET_CURRENCY="${BUDGET_CURRENCY:-INR}"
TOTAL_BUDGET="${TOTAL_BUDGET:-2300}"
AI_SPEND_CAP="${AI_SPEND_CAP:-1800}"
TOTAL_BUDGET_NAME="${TOTAL_BUDGET_NAME:-Voyager total (alerts)}"
AI_CAP_NAME="${AI_CAP_NAME:-Voyager Gemini spend cap}"
# Gemini Enterprise Agent Platform (formerly Vertex AI), from
# https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps
AI_SERVICE_ID="${AI_SERVICE_ID:-C7E2-9256-1C43}"
# No anthropic-api-key: production uses Gemini on Vertex AI via the VM's SA
SECRETS=(jwt-secret-key admin-password serpapi-key serper-key smtp-password)
RUNTIME_SA="vm-runtime@$PROJECT_ID.iam.gserviceaccount.com"
# Custom roles (least privilege). Gemini generateContent/streamGenerateContent
# on publishers/google/models/* are authorised by aiplatform.endpoints.predict
# ("Make prompt requests", docs.cloud.google.com/vertex-ai/generative-ai/docs/
# access-control); the app calls nothing else on Vertex. FCM HTTP v1 send
# needs cloudmessaging.messages.create.
GEMINI_ROLE="voyagerGeminiInvoker"
GEMINI_PERMS="aiplatform.endpoints.predict"
FCM_ROLE="voyagerFcmSender"
FCM_PERMS="cloudmessaging.messages.create"
IAP_RANGE="35.235.240.0/20"

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# BOOTSTRAP_WORK (tests): keep the work files (host bundle, JSON) there
if [[ -n "${BOOTSTRAP_WORK:-}" ]]; then
  WORK="$BOOTSTRAP_WORK"
  mkdir -p "$WORK"
else
  WORK="$(mktemp -d)"
  trap 'rm -rf "$WORK"' EXIT
fi

say() { printf '\n==> %s\n' "$*"; }

# run CMD... — executes, or prints it in dry-run mode
run() {
  if ((DRY_RUN)); then
    # stderr, so callers' >/dev/null never hides a printed command
    { printf '  %q' "$@"; printf '\n'; } >&2
  else
    "$@"
  fi
}

# exists CMD... — true if the describe-style command succeeds; dry-run: false
exists() {
  ((DRY_RUN)) && return 1
  "$@" >/dev/null 2>&1
}

g() { run gcloud --project="$PROJECT_ID" --quiet "$@"; }
gx() { exists gcloud --project="$PROJECT_ID" "$@"; }

host_bundle() {
  # deploy/gcp without tests, as base64 tar.gz for instance metadata.
  # An explicit, C-sorted file list: the same order on every machine. No
  # extended attributes or AppleDouble files: macOS tags files with
  # com.apple.provenance, which bsdtar stores as LIBARCHIVE.xattr.* headers
  # and Debian's GNU tar then warns about on every extraction.
  local src="$ROOT/deploy/gcp" list="$WORK/bundle.list"
  local -a flags
  (cd "$src" && find . -type f ! -path './tests/*' ! -path '*/__pycache__/*' \
    ! -name '.DS_Store' ! -name '._*' | LC_ALL=C sort) >"$list"
  if tar --version 2>/dev/null | grep -q 'GNU tar'; then
    flags=(--no-xattrs --no-acls --owner=0 --group=0 --numeric-owner)
  else # bsdtar (macOS)
    flags=(--no-mac-metadata --no-xattrs --no-acls --uid 0 --gid 0 --numeric-owner)
  fi
  COPYFILE_DISABLE=1 tar "${flags[@]}" -C "$src" -czf "$WORK/bundle.tgz" -T "$list"
  base64 <"$WORK/bundle.tgz" | tr -d '\n' >"$WORK/bundle.b64"
  local size
  size="$(wc -c <"$WORK/bundle.b64")"
  ((size < 250000)) || { echo "host bundle too large for metadata: $size bytes" >&2; exit 1; }
  echo "$WORK/bundle.b64"
}

# preflight — a real run needs gcloud's beta component (notification
# channels); fail before changing anything, never install it silently
preflight() {
  ((DRY_RUN)) && return 0
  command -v gcloud >/dev/null || { echo "gcloud CLI not found" >&2; exit 1; }
  local installed missing=()
  if installed="$(gcloud components list --only-local-state --format='value(id)' 2>/dev/null)"; then
    grep -qx beta <<<"$installed" || missing+=(beta)
  elif ! CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud beta monitoring channels --help </dev/null >/dev/null 2>&1; then
    # Component manager disabled (apt/dnf install): probe the command group
    missing+=(beta)
  fi
  if ((${#missing[@]})); then
    cat >&2 <<EOF
gcloud is missing the component(s): ${missing[*]}. Install, then re-run:
  gcloud components install ${missing[*]} --quiet
(gcloud from apt/dnf has no component manager: see
 https://cloud.google.com/sdk/docs/components for the package to install)
EOF
    exit 1
  fi
}

# Billing (budgets) and other user-billed calls go to the account's default
# quota project unless told otherwise, and fail with "does not have
# permission to access billingAccounts" when that is some other project.
# Use this project from the moment it exists (unless the caller set one).
quota_project() {
  export CLOUDSDK_BILLING_QUOTA_PROJECT="${CLOUDSDK_BILLING_QUOTA_PROJECT:-$PROJECT_ID}"
  echo "  quota project: $CLOUDSDK_BILLING_QUOTA_PROJECT (CLOUDSDK_BILLING_QUOTA_PROJECT)"
}

project() {
  say "Project $PROJECT_ID and billing"
  if gx projects describe "$PROJECT_ID"; then
    echo "  project exists"
  else
    run gcloud projects create "$PROJECT_ID" --name="Voyager"
  fi
  quota_project
  # The quota project must have the API enabled before any billing call
  g services enable cloudbilling.googleapis.com
  local linked=""
  if ((!DRY_RUN)); then
    linked="$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingAccountName)' 2>/dev/null || true)"
  fi
  if [[ "$linked" == "billingAccounts/$BILLING_ACCOUNT" ]]; then
    echo "  billing already linked"
  else
    run gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"
  fi
}

apis() {
  say "APIs"
  g services enable \
    compute.googleapis.com iap.googleapis.com oslogin.googleapis.com \
    secretmanager.googleapis.com monitoring.googleapis.com storage.googleapis.com \
    fcm.googleapis.com billingbudgets.googleapis.com aiplatform.googleapis.com \
    iam.googleapis.com \
    cloudresourcemanager.googleapis.com cloudbilling.googleapis.com
}

# custom_role ID TITLE PERMS — create, or reset its permissions to exactly PERMS
custom_role() {
  if gx iam roles describe "$1"; then
    g iam roles update "$1" --permissions="$3" >/dev/null
  else
    g iam roles create "$1" --title="$2" --permissions="$3" --stage=GA \
      --description="Least privilege for the Voyager VM (bootstrap.sh)"
  fi
}

service_accounts() {
  say "Service accounts"
  gx iam service-accounts describe "$RUNTIME_SA" ||
    g iam service-accounts create vm-runtime --display-name="Voyager VM runtime"
  # Project-level: only the two custom roles. Storage and secrets are
  # granted per resource below, never project-wide.
  custom_role "$GEMINI_ROLE" "Voyager Gemini invoker" "$GEMINI_PERMS"
  custom_role "$FCM_ROLE" "Voyager FCM sender" "$FCM_PERMS"
  local role
  for role in "$GEMINI_ROLE" "$FCM_ROLE"; do
    g projects add-iam-policy-binding "$PROJECT_ID" \
      --member="serviceAccount:$RUNTIME_SA" \
      --role="projects/$PROJECT_ID/roles/$role" --condition=None >/dev/null
  done
}

network() {
  say "Static IPv4 (Standard tier) and firewall"
  gx compute addresses describe "$IP_NAME" --region="$REGION" ||
    g compute addresses create "$IP_NAME" --region="$REGION" --network-tier=STANDARD
  gx compute firewall-rules describe voyager-web ||
    g compute firewall-rules create voyager-web --network=default \
      --direction=INGRESS --allow=tcp:80,tcp:443 --source-ranges=0.0.0.0/0 \
      --target-tags=voyager-web --description="Caddy: HTTP(S)"
  gx compute firewall-rules describe voyager-iap-ssh ||
    g compute firewall-rules create voyager-iap-ssh --network=default \
      --direction=INGRESS --allow=tcp:22 --source-ranges="$IAP_RANGE" \
      --target-tags=voyager-web --description="SSH only through IAP"
  # The default network allows SSH/RDP from anywhere: remove those
  local rule
  for rule in default-allow-ssh default-allow-rdp; do
    if ((DRY_RUN)) || gx compute firewall-rules describe "$rule"; then
      g compute firewall-rules delete "$rule"
    fi
  done
}

static_ip() {
  if ((DRY_RUN)); then
    echo "203.0.113.10"
  else
    gcloud --project="$PROJECT_ID" compute addresses describe "$IP_NAME" \
      --region="$REGION" --format='value(address)'
  fi
}

site_host() {
  local ip
  ip="$(static_ip)"
  echo "${SITE_HOST:-${ip//./-}.sslip.io}"
}

bucket() {
  say "Backup bucket gs://$BUCKET"
  gx storage buckets describe "gs://$BUCKET" ||
    g storage buckets create "gs://$BUCKET" --location="$REGION" \
      --default-storage-class=STANDARD --uniform-bucket-level-access \
      --public-access-prevention --soft-delete-duration=0
  cat >"$WORK/lifecycle.json" <<'JSON'
{"rule": [
  {"action": {"type": "Delete"}, "condition": {"isLive": false, "numNewerVersions": 100}},
  {"action": {"type": "Delete"}, "condition": {"isLive": false, "daysSinceNoncurrentTime": 30}}
]}
JSON
  g storage buckets update "gs://$BUCKET" --versioning --clear-soft-delete \
    --lifecycle-file="$WORK/lifecycle.json"
  g storage buckets add-iam-policy-binding "gs://$BUCKET" \
    --member="serviceAccount:$RUNTIME_SA" --role=roles/storage.objectUser >/dev/null
}

secrets() {
  say "Secret Manager secrets (created EMPTY: add versions yourself)"
  local s
  for s in "${SECRETS[@]}"; do
    gx secrets describe "$s" ||
      g secrets create "$s" --replication-policy=user-managed --locations="$REGION"
    g secrets add-iam-policy-binding "$s" \
      --member="serviceAccount:$RUNTIME_SA" --role=roles/secretmanager.secretAccessor >/dev/null
  done
}

snapshots() {
  say "Snapshot schedule: daily, keep 7, us-east1"
  gx compute resource-policies describe voyager-daily --region="$REGION" ||
    g compute resource-policies create snapshot-schedule voyager-daily \
      --region="$REGION" --daily-schedule --start-time=02:00 \
      --max-retention-days=7 --on-source-disk-delete=keep-auto-snapshots \
      --storage-location="$REGION"
}

metadata_args() {
  local host="$1" bundle="$2"
  printf '%s\n' \
    "--metadata=enable-oslogin=TRUE,voyager-site-host=$host,voyager-acme-email=$ACME_EMAIL,voyager-bucket=$BUCKET,voyager-alert-email=$ALERT_EMAIL" \
    "--metadata-from-file=startup-script=$ROOT/deploy/gcp/host/first-boot.sh,voyager-bundle=$bundle"
}

vm() {
  say "VM $VM (e2-micro, Debian 13, 30 GB pd-standard)"
  local host bundle line
  local -a md
  host="$(site_host)"
  bundle="$(host_bundle)"
  md=()
  while IFS= read -r line; do md+=("$line"); done < <(metadata_args "$host" "$bundle")
  if gx compute instances describe "$VM" --zone="$ZONE"; then
    echo "  VM exists (use --update-host to refresh its host bundle)"
  else
    g compute instances create "$VM" --zone="$ZONE" --machine-type=e2-micro \
      --network-interface="network=default,address=$IP_NAME,network-tier=STANDARD,stack-type=IPV4_ONLY" \
      --image-family=debian-13 --image-project=debian-cloud \
      --boot-disk-size=30GB --boot-disk-type=pd-standard --boot-disk-device-name="$VM" \
      --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
      --service-account="$RUNTIME_SA" --scopes=cloud-platform \
      --tags=voyager-web "${md[@]}"
  fi
  # Snapshot schedules belong to disks, not instances. The boot disk is named
  # after the VM; attach the schedule unless it already is.
  local policies=""
  if ((!DRY_RUN)); then
    policies="$(gcloud --project="$PROJECT_ID" compute disks describe "$VM" \
      --zone="$ZONE" --format='value(resourcePolicies)')"
  fi
  if [[ "$policies" == *voyager-daily* ]]; then
    echo "  snapshot schedule already attached to disk $VM"
  else
    g compute disks add-resource-policies "$VM" --zone="$ZONE" \
      --resource-policies=voyager-daily
  fi
  echo "  site: https://$host"
}

update_host() {
  say "Refreshing host bundle metadata on $VM"
  local host bundle line
  local -a md
  host="$(site_host)"
  bundle="$(host_bundle)"
  md=()
  while IFS= read -r line; do md+=("$line"); done < <(metadata_args "$host" "$bundle")
  g compute instances add-metadata "$VM" --zone="$ZONE" "${md[@]}"
  echo "  then: gcloud compute ssh $VM --zone=$ZONE --tunnel-through-iap -- sudo google_metadata_script_runner startup"
}

budgets() {
  say "Budgets: $TOTAL_BUDGET $BUDGET_CURRENCY total (pre-tax) + $AI_SPEND_CAP $BUDGET_CURRENCY spend cap on Agent Platform"
  local existing="" number
  if ((!DRY_RUN)); then
    # Fail closed: a listing error must never look like "no budgets"
    existing="$(gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" \
      --format='value(displayName)')" || {
      echo "  !! cannot list budgets on $BILLING_ACCOUNT; refusing to create any (duplicates)" >&2
      exit 1
    }
    number="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
  else
    number="PROJECT_NUMBER"
  fi
  if grep -qxF "$TOTAL_BUDGET_NAME" <<<"$existing"; then
    echo "  '$TOTAL_BUDGET_NAME' exists: left as is"
  else
    run gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" \
      --display-name="$TOTAL_BUDGET_NAME" --budget-amount="$TOTAL_BUDGET$BUDGET_CURRENCY" \
      --filter-projects="projects/$number" --calendar-period=month \
      --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 \
      --threshold-rule=percent=1.0 --threshold-rule=percent=1.0,basis=forecasted-spend
  fi
  if grep -qxF "$AI_CAP_NAME" <<<"$existing"; then
    echo "  '$AI_CAP_NAME' exists: left as is"
    return
  fi
  # Spend caps have no gcloud flag (2026-11): Cloud Billing Budget API,
  # Budget.spendCap.inputState=CONFIGURED. One project + one service, monthly;
  # alerts at 50/80/100 % are fixed. Amount in the billing account's currency.
  cat >"$WORK/ai-cap.json" <<JSON
{
  "displayName": "$AI_CAP_NAME",
  "budgetFilter": {
    "projects": ["projects/$number"],
    "services": ["services/$AI_SERVICE_ID"],
    "calendarPeriod": "MONTH"
  },
  "amount": {"specifiedAmount": {"currencyCode": "$BUDGET_CURRENCY", "units": "$AI_SPEND_CAP"}},
  "spendCap": {"inputState": "CONFIGURED"}
}
JSON
  if ((DRY_RUN)); then
    echo "  POST https://billingbudgets.googleapis.com/v1/billingAccounts/$BILLING_ACCOUNT/budgets"
    sed 's/^/    /' "$WORK/ai-cap.json"
    return
  fi
  if ! curl -fsS -X POST \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    -H "x-goog-user-project: $PROJECT_ID" -H "Content-Type: application/json" \
    --data @"$WORK/ai-cap.json" \
    "https://billingbudgets.googleapis.com/v1/billingAccounts/$BILLING_ACCOUNT/budgets" >/dev/null; then
    cat >&2 <<EOF
  !! Could not create the spend cap through the API. Console fallback:
     Billing → Budgets & alerts → Create budget → "Spend cap enforcement",
     name "$AI_CAP_NAME", project $PROJECT_ID, service "Gemini Enterprise
     Agent Platform" ($AI_SERVICE_ID), target amount $AI_SPEND_CAP $BUDGET_CURRENCY → Finish.
EOF
  fi
}

uptime() {
  say "Uptime check on /health (content match \"backup_ok\":true) + email alert"
  local host channel check
  host="$(site_host)"
  channel=""
  check=""
  if ((!DRY_RUN)); then
    channel="$(gcloud --project="$PROJECT_ID" beta monitoring channels list \
      --filter="labels.email_address=\"$ALERT_EMAIL\"" --format='value(name)' | head -n1)"
    check="$(gcloud --project="$PROJECT_ID" monitoring uptime list-configs \
      --filter='displayName="voyager-health"' --format='value(name)' | head -n1)"
    check="${check##*/}"
  fi
  if [[ -z "$channel" ]]; then
    g beta monitoring channels create --type=email --display-name="Voyager ops" \
      --channel-labels="email_address=$ALERT_EMAIL"
    if ((DRY_RUN)); then
      channel="projects/$PROJECT_ID/notificationChannels/CHANNEL_ID"
    else
      channel="$(gcloud --project="$PROJECT_ID" beta monitoring channels list \
        --filter="labels.email_address=\"$ALERT_EMAIL\"" --format='value(name)' | head -n1)"
    fi
  fi
  if [[ -z "$check" ]]; then
    g monitoring uptime create voyager-health --resource-type=uptime-url \
      --resource-labels="host=$host,project_id=$PROJECT_ID" --protocol=https \
      --path=/health --port=443 --period=5 --timeout=10 \
      --matcher-type=contains-string --matcher-content='"backup_ok":true'
    if ((DRY_RUN)); then
      check="CHECK_ID"
    else
      check="$(gcloud --project="$PROJECT_ID" monitoring uptime list-configs \
        --filter='displayName="voyager-health"' --format='value(name)' | head -n1)"
      check="${check##*/}"
    fi
  fi
  if ((!DRY_RUN)) && gcloud --project="$PROJECT_ID" monitoring policies list \
    --filter='displayName="voyager-down"' --format='value(name)' | grep -q .; then
    echo "  alert policy exists"
    return
  fi
  cat >"$WORK/policy.json" <<JSON
{
  "displayName": "voyager-down",
  "combiner": "OR",
  "conditions": [{
    "displayName": "/health failing or backup not ok for 10 min",
    "conditionThreshold": {
      "filter": "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.label.check_id=\"$check\" AND resource.type=\"uptime_url\"",
      "aggregations": [{
        "alignmentPeriod": "300s",
        "perSeriesAligner": "ALIGN_NEXT_OLDER",
        "crossSeriesReducer": "REDUCE_COUNT_FALSE",
        "groupByFields": ["resource.label.host"]
      }],
      "comparison": "COMPARISON_GT",
      "thresholdValue": 1,
      "duration": "600s"
    }
  }],
  "notificationChannels": ["$channel"]
}
JSON
  g monitoring policies create --policy-from-file="$WORK/policy.json"
}


main() {
  ((DRY_RUN)) && echo "# DRY RUN: nothing is called; commands are printed"
  if ((UPDATE_HOST)); then
    update_host
    return
  fi
  preflight
  project
  apis
  service_accounts
  network
  bucket
  secrets
  snapshots
  vm
  budgets
  uptime
  say "Done. Next (docs/Deployment-GCP.md):"
  cat <<EOF
  1. Add secret versions (values never pass through this script):
       printf '%s' "\$(openssl rand -base64 48)" | gcloud secrets versions add jwt-secret-key --data-file=- --project=$PROJECT_ID
       read -rs PW; printf '%s' "\$PW" | gcloud secrets versions add admin-password --data-file=- --project=$PROJECT_ID
       ... serpapi-key, serper-key, smtp-password (optional ones may stay empty)
  2. Add Firebase to $PROJECT_ID (console), download google-services.json for Android.
  3. Watch first boot: gcloud compute ssh $VM --zone=$ZONE --tunnel-through-iap -- sudo journalctl -u google-startup-scripts -f
  4. Open https://$(site_host)
EOF
}

main
