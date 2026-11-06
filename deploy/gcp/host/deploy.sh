#!/usr/bin/env bash
# Voyager pull deployer (runs on the VM every 5 min via voyager-deploy.timer).
#
#   1. Resolve the `prod` tag of each image to a digest (GHCR, anonymous).
#   2. Verify the digest's cosign keyless signature: it must come from this
#      repo's deploy workflow on refs/heads/main. Anything else is refused.
#   3. Pull by digest (new layers land before anything stops).
#   4. Pin the digest in images.env (previous one kept for rollback),
#      `docker compose up -d`, poll the app's health for up to 120 s.
#   5. Unhealthy → put the previous digest back and bring it up again.
#
# The app deploys as soon as a new signed digest appears. Caddy changes drop
# every open connection (SSE included), so a new Caddy digest is only
# verified and pre-pulled here and applied in the weekly night window
# (--window), or at once when no Caddy is running yet (first boot).
#
# Usage: deploy.sh [--window] [--rollback]
# Config: /etc/voyager/deploy.env (optional overrides of the defaults below).
set -euo pipefail

CONFIG=/etc/voyager/deploy.env
# shellcheck source=/dev/null
[[ -f "$CONFIG" ]] && . "$CONFIG"

REPO="${REPO:-rupakc/travel-planner}"
REGISTRY="${REGISTRY:-ghcr.io}"
APP_REPO="${APP_REPO:-$REGISTRY/rupakc/travel-planner-app}"
CADDY_REPO="${CADDY_REPO:-$REGISTRY/rupakc/travel-planner-caddy}"
TAG="${TAG:-prod}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/voyager}"
# Pinned by digest (v2.4.1): the verifier itself must not float
COSIGN_IMAGE="${COSIGN_IMAGE:-ghcr.io/sigstore/cosign/cosign:v2.4.1@sha256:b03690aa52bfe94054187142fba24dc54137650682810633901767d8a3e15b31}"
CERT_IDENTITY="${CERT_IDENTITY:-https://github.com/$REPO/.github/workflows/deploy.yml@refs/heads/main}"
CERT_ISSUER="${CERT_ISSUER:-https://token.actions.githubusercontent.com}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"

IMAGES_ENV="$COMPOSE_DIR/images.env"
# Digests that failed their health check: never retried automatically
FAILED="$COMPOSE_DIR/failed-digests"
LOCK=/run/voyager-deploy.lock

log() { echo "voyager-deploy: $*" >&2; logger -t voyager-deploy -- "$*" 2>/dev/null || true; }
die() { log "ERROR: $*"; exit 1; }

compose() {
  docker compose --project-directory "$COMPOSE_DIR" \
    --env-file "$COMPOSE_DIR/site.env" --env-file "$IMAGES_ENV" \
    -f "$COMPOSE_DIR/compose.yaml" "$@"
}

# get_var FILE KEY → value of KEY=... (empty if absent)
get_var() {
  [[ -f "$1" ]] || return 0
  sed -n "s/^$2=//p" "$1" | tail -n1
}

# write_images APP CADDY PREV_APP PREV_CADDY PENDING_CADDY (atomic)
write_images() {
  local tmp
  tmp="$(mktemp "$COMPOSE_DIR/.images.XXXXXX")"
  {
    echo "# Written by deploy.sh — digests verified with cosign"
    echo "APP_IMAGE=$1"
    echo "CADDY_IMAGE=$2"
    echo "PREV_APP_IMAGE=$3"
    echo "PREV_CADDY_IMAGE=$4"
    echo "PENDING_CADDY_IMAGE=$5"
    echo "UPDATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } >"$tmp"
  chmod 0644 "$tmp"
  mv -f "$tmp" "$IMAGES_ENV"
  sync -f "$IMAGES_ENV" 2>/dev/null || sync
}

# resolve_digest REPO TAG → sha256:… of the tag's manifest (index) on GHCR
resolve_digest() {
  local repo="$1" tag="$2" path token digest
  path="${repo#"$REGISTRY"/}"
  token="$(curl -fsS "https://$REGISTRY/token?scope=repository:$path:pull" | jq -r .token)"
  [[ -n "$token" && "$token" != null ]] || die "no registry token for $path"
  digest="$(curl -fsSI \
    -H "Authorization: Bearer $token" \
    -H "Accept: application/vnd.oci.image.index.v1+json" \
    -H "Accept: application/vnd.docker.distribution.manifest.list.v2+json" \
    -H "Accept: application/vnd.oci.image.manifest.v1+json" \
    -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
    "https://$REGISTRY/v2/$path/manifests/$tag" |
    tr -d '\r' | sed -n 's/^[Dd]ocker-[Cc]ontent-[Dd]igest: *//p')"
  [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || die "bad digest for $path:$tag: '$digest'"
  echo "$digest"
}

verify() {
  local ref="$1"
  log "verifying $ref"
  docker run --rm --network host "$COSIGN_IMAGE" verify \
    --certificate-identity "$CERT_IDENTITY" \
    --certificate-oidc-issuer "$CERT_ISSUER" \
    "$ref" >/dev/null 2>&1 || return 1
}

app_health() {
  local cid status
  cid="$(compose ps -q app 2>/dev/null || true)"
  [[ -n "$cid" ]] || { echo missing; return; }
  status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo missing)"
  echo "$status"
}

wait_healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) status
  while ((SECONDS < deadline)); do
    status="$(app_health)"
    [[ "$status" == healthy ]] && return 0
    sleep 5
  done
  log "app health after ${HEALTH_TIMEOUT}s: $(app_health)"
  return 1
}

notify() {
  # Same SMTP path as the governor (best effort)
  if [[ -x "$COMPOSE_DIR/governor.py" ]]; then
    "$COMPOSE_DIR/governor.py" mail --subject "$1" --body "$2" || true
  fi
}

main() {
  local window=0 rollback=0
  for arg in "$@"; do
    case "$arg" in
      --window) window=1 ;;
      --rollback) rollback=1 ;;
      *) die "unknown argument: $arg" ;;
    esac
  done

  exec 9>"$LOCK"
  flock -n 9 || { log "another deploy is running"; exit 0; }

  local cur_app cur_caddy prev_app prev_caddy pending
  cur_app="$(get_var "$IMAGES_ENV" APP_IMAGE)"
  cur_caddy="$(get_var "$IMAGES_ENV" CADDY_IMAGE)"
  prev_app="$(get_var "$IMAGES_ENV" PREV_APP_IMAGE)"
  prev_caddy="$(get_var "$IMAGES_ENV" PREV_CADDY_IMAGE)"
  pending="$(get_var "$IMAGES_ENV" PENDING_CADDY_IMAGE)"

  if ((rollback)); then
    [[ -n "$prev_app" ]] || die "no previous app digest to roll back to"
    log "manual rollback: $cur_app → $prev_app"
    write_images "$prev_app" "$cur_caddy" "$cur_app" "$prev_caddy" "$pending"
    compose up -d app
    wait_healthy || die "rolled-back app is not healthy either"
    exit 0
  fi

  local new_app new_caddy
  new_app="$APP_REPO@$(resolve_digest "$APP_REPO" "$TAG")"
  new_caddy="$CADDY_REPO@$(resolve_digest "$CADDY_REPO" "$TAG")"

  # ── Caddy: stage, apply only in the window (or when none runs yet) ──
  local next_caddy="$cur_caddy" next_prev_caddy="$prev_caddy" next_pending="$pending"
  if [[ "$new_caddy" != "$cur_caddy" ]]; then
    if [[ "$new_caddy" != "$pending" ]]; then
      verify "$new_caddy" || die "signature check FAILED for $new_caddy: refusing it"
      docker pull -q "$new_caddy" >/dev/null
      next_pending="$new_caddy"
    fi
    if [[ -z "$cur_caddy" ]] || ((window)); then
      next_prev_caddy="$cur_caddy"
      next_caddy="$new_caddy"
      next_pending=""
    else
      log "new Caddy staged for the night window: $new_caddy"
    fi
  else
    next_pending=""
  fi

  # ── App ──
  local next_app="$cur_app" next_prev_app="$prev_app"
  if [[ "$new_app" != "$cur_app" ]] && grep -qxF "$new_app" "$FAILED" 2>/dev/null; then
    log "skipping $new_app: it failed its health check before"
    new_app="$cur_app"
  fi
  if [[ "$new_app" != "$cur_app" ]]; then
    verify "$new_app" || die "signature check FAILED for $new_app: refusing it"
    log "pulling $new_app"
    docker pull -q "$new_app" >/dev/null
    next_prev_app="$cur_app"
    next_app="$new_app"
  fi

  if [[ "$next_app" == "$cur_app" && "$next_caddy" == "$cur_caddy" ]]; then
    [[ "$next_pending" == "$pending" ]] ||
      write_images "$cur_app" "$cur_caddy" "$prev_app" "$prev_caddy" "$next_pending"
    exit 0
  fi

  write_images "$next_app" "$next_caddy" "$next_prev_app" "$next_prev_caddy" "$next_pending"
  log "deploying app=$next_app caddy=$next_caddy"
  compose up -d --remove-orphans

  if wait_healthy; then
    log "deploy healthy"
    docker image prune -f >/dev/null 2>&1 || true
    exit 0
  fi

  # ── Automatic rollback ──
  [[ "$next_app" == "$cur_app" ]] || echo "$next_app" >>"$FAILED"
  if [[ -n "$cur_app" ]]; then
    log "deploy UNHEALTHY: rolling back to $cur_app"
    write_images "$cur_app" "$cur_caddy" "$prev_app" "$prev_caddy" "$next_pending"
    compose up -d --remove-orphans
    if wait_healthy; then
      notify "[voyager] deploy rolled back" "New app $next_app failed its health check; $cur_app is running again."
    else
      notify "[voyager] deploy FAILED, rollback unhealthy" "Both $next_app and $cur_app are unhealthy. Check: docker compose logs app"
    fi
  else
    notify "[voyager] first deploy unhealthy" "$next_app is not healthy and there is nothing to roll back to."
  fi
  exit 1
}

main "$@"
