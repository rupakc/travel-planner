#!/usr/bin/env bash
# Voyager pull deployer (runs on the VM every minute via voyager-deploy.timer).
#
#   1. Resolve the `prod` tag of both images to digests (GHCR, anonymous: one
#      token, cached for 4 min, and two HEAD requests). Nothing new and all
#      containers running → done (no pull, no cosign, no compose; one
#      `docker ps`). A 429 from GHCR backs off (Retry-After, else
#      exponentially, up to 30 min).
#   2. Verify each new digest's cosign keyless signature: it must come from
#      this repo's deploy workflow on refs/heads/main. Anything else is refused.
#   3. App: pull by digest, wait up to 90 s for open SSE streams to end
#      (drain), pin it in images.env (previous one kept), `compose up -d app`,
#      check the container really runs the new image, wait for healthy
#      (240 s); otherwise the previous digest goes back at once (no drain).
#   4. Caddy image (SPA + Caddyfile + Caddy runtime), never restarting Caddy
#      for content:
#      - copy /srv and the Caddyfile out of the image (docker create + cp,
#        never run) into $EDGE_DIR/releases/<digest>, check them (regular
#        files and directories only, index.html and its assets present), and
#        switch the symlinks current → new, prev1 → old current, prev2 → old
#        prev1. Caddy serves the SPA from /edge/current/srv and /assets/* from
#        current, prev1 and prev2 (browsers holding an older index.html).
#      - Caddyfile changed → adapt + validate it (throwaway container, real
#        SITE_HOST/ACME_EMAIL), then load it through the admin API: graceful,
#        open connections (SSE) keep running. Failure → old config stays,
#        symlinks switched back.
#      - Caddy *runtime* changed (label io.voyager.caddy-runtime: base image,
#        binary, user; see caddy-runtime-id.sh) → drain, recreate the
#        container, check it, roll back to the previous runtime + release on
#        failure (and hold that runtime). A held runtime is never recreated
#        onto: a new image with it ships only its SPA/Caddyfile, on the
#        current runtime.
#   5. Converge (only when compose.yaml/site.env/app.env/images.env changed,
#      or `docker ps` shows a service not running): `compose up -d`; when that
#      would recreate Caddy (its compose config hash changed), drain first.
#
# Failures. Content that fails a check (SPA, Caddyfile), an app that never
# gets healthy and a Caddy runtime that fails its checks are HELD (never
# deployed automatically; a newer digest/runtime ends the hold). Anything
# that looks like infrastructure (pull, docker create/cp, compose, a full
# disk, Caddy not answering) holds nothing: that digest is retried after
# 5 min. Emails and repeated error logs: at most one an hour per kind.
#
# images.env: APP_IMAGE / PREV_APP_IMAGE, CADDY_IMAGE / PREV_CADDY_IMAGE (the
# runtime compose runs; changes only on runtime changes), CADDY_CONTENT_IMAGE
# / PREV_CADDY_CONTENT_IMAGE (where the live SPA + Caddyfile came from).
#
# An image built by an OLDER deploy run than the running one (label
# io.voyager.build = the workflow's run number) is refused, and so is one
# whose label (or the live one's) can't be read: moving `prod` back, or
# re-running an old workflow run, can't downgrade production. Use a rollback
# option or --allow-downgrade on purpose.
#
# Usage: deploy.sh [--rollback | --rollback-edge | --rollback-caddy] [--allow-downgrade]
#   --rollback        app → previous digest (held)
#   --rollback-edge   swap SPA + Caddyfile releases current ⇄ prev1, no restart;
#                     the release left is held, the one returned to released
#                     (running it again undoes it)
#   --rollback-caddy  Caddy runtime → previous image (its runtime held), drain + recreate
#   --window          accepted and ignored (Caddy no longer waits for a window)
# Config: /etc/voyager/deploy.env (optional overrides of the defaults below).
set -euo pipefail

CONFIG="${VOYAGER_DEPLOY_CONFIG:-/etc/voyager/deploy.env}"
# shellcheck source=/dev/null
[[ -f "$CONFIG" ]] && . "$CONFIG"

REPO="${REPO:-rupakc/travel-planner}"
REGISTRY="${REGISTRY:-ghcr.io}"
APP_REPO="${APP_REPO:-$REGISTRY/rupakc/travel-planner-app}"
CADDY_REPO="${CADDY_REPO:-$REGISTRY/rupakc/travel-planner-caddy}"
TAG="${TAG:-prod}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/voyager}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-voyager}"
# Pinned by digest (v2.4.1): the verifier itself must not float
COSIGN_IMAGE="${COSIGN_IMAGE:-ghcr.io/sigstore/cosign/cosign:v2.4.1@sha256:b03690aa52bfe94054187142fba24dc54137650682810633901767d8a3e15b31}"
CERT_IDENTITY="${CERT_IDENTITY:-https://github.com/$REPO/.github/workflows/deploy.yml@refs/heads/main}"
CERT_ISSUER="${CERT_ISSUER:-https://token.actions.githubusercontent.com}"
# ≥ the app's health start_period (180 s) + margin: a place-data reseed on
# pd-standard must not be mistaken for a failed deploy
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-240}"
# Edge: releases on the host, mounted read-only into Caddy at /edge
EDGE_DIR="${EDGE_DIR:-/var/lib/voyager/edge}"
EDGE_MOUNT=/edge
EDGE_MAX_MB="${EDGE_MAX_MB:-200}"
# Before recreating Caddy or the app: wait this long for open SSE streams
DRAIN_TIMEOUT="${DRAIN_TIMEOUT:-90}"
CADDY_HEALTH_TIMEOUT="${CADDY_HEALTH_TIMEOUT:-60}"
# An infrastructure failure retries the same digest after this long
RETRY_SECONDS="${RETRY_SECONDS:-300}"
# Fixed addresses on the compose network (compose.yaml)
APP_STREAMS_URL="${APP_STREAMS_URL:-http://172.30.0.10:8001/internal/streams}"
CADDY_IP="${CADDY_IP:-172.30.0.20}"
# Seconds between polls (tests: 0)
POLL="${POLL:-3}"
# Token cache, back-offs, retry stamps, log/mail rate limits (tmpfs)
STATE_DIR="${STATE_DIR:-/run/voyager-deploy}"

IMAGES_ENV="$COMPOSE_DIR/images.env"
SITE_ENV="$COMPOSE_DIR/site.env"
# Held digests, never deployed automatically: content that failed its checks,
# an app that failed its health check, ones an operator rolled back from. A
# newer digest isn't on the list, so publishing one ends the hold. To
# release a digest by hand, delete its line.
FAILED="$COMPOSE_DIR/failed-digests"
# Held Caddy runtimes (io.voyager.caddy-runtime values): ones that failed
# their checks after a recreate, or an operator rolled back from. Images
# with a held runtime deliver only their SPA/Caddyfile, on the current runtime.
HELD_RUNTIMES="$COMPOSE_DIR/held-runtimes"
# Digests refused as downgrades (or without a readable build label):
# remembered so they aren't verified and pulled again every minute.
# --allow-downgrade ignores the list.
REFUSED="$COMPOSE_DIR/refused-digests"
LOCK="${LOCK:-/run/voyager-deploy.lock}"

log() { echo "voyager-deploy: $*" >&2; logger -t voyager-deploy -- "$*" 2>/dev/null || true; }
die() { log "ERROR: $*"; exit 1; }

# fresh_stamp KEY SECS → true if the stamp KEY is younger than SECS
fresh_stamp() {
  local f="$STATE_DIR/stamp-$1"
  [[ -f "$f" ]] && (($(date +%s) - $(stat -c %Y "$f") < $2))
}
stamp() { touch "$STATE_DIR/stamp-$1" 2>/dev/null || true; }
key() { printf '%s' "$1" | cksum | cut -d' ' -f1; }

# log_once KEY MSG — log MSG only when it differs from the last one for KEY
# (the timer runs every minute: a held digest must not log 1,440 times a day)
log_once() {
  local f="$STATE_DIR/note-$1"
  [[ "$(cat "$f" 2>/dev/null)" == "$2" ]] && return 0
  printf '%s' "$2" >"$f" 2>/dev/null || true
  log "$2"
}

# log_rl KEY MSG — at most once an hour per KEY (repeated infra errors)
log_rl() {
  fresh_stamp "log-$1" 3600 && return 0
  stamp "log-$1"
  log "$2"
}

# notify SUBJECT BODY — email (governor's SMTP path), at most one an hour per
# subject; best effort
notify() {
  local k
  k="mail-$(key "$1")"
  if fresh_stamp "$k" 3600; then
    log "(not emailing again within the hour: $1)"
    return 0
  fi
  stamp "$k"
  if [[ -x "$COMPOSE_DIR/governor.py" ]]; then
    "$COMPOSE_DIR/governor.py" mail --subject "$1" --body "$2" || true
  fi
}

compose() {
  docker compose --project-directory "$COMPOSE_DIR" \
    --env-file "$SITE_ENV" --env-file "$IMAGES_ENV" \
    -f "$COMPOSE_DIR/compose.yaml" "$@"
}

# get_var FILE KEY → value of KEY=... (empty if absent)
get_var() {
  [[ -f "$1" ]] || return 0
  sed -n "s/^$2=//p" "$1" | tail -n1
}

listed() { [[ -n "$2" ]] && grep -qxF "$2" "$1" 2>/dev/null; }
hold() { listed "$FAILED" "$1" || echo "$1" >>"$FAILED"; }
unhold() {
  [[ -f "$FAILED" ]] || return 0
  grep -vxF "$1" "$FAILED" >"$FAILED.new" || true
  mv -f "$FAILED.new" "$FAILED"
}
hold_runtime() { [[ -z "$1" ]] || listed "$HELD_RUNTIMES" "$1" || echo "$1" >>"$HELD_RUNTIMES"; }
runtime_held() { listed "$HELD_RUNTIMES" "$1"; }
refuse() { listed "$REFUSED" "$1" || echo "$1" >>"$REFUSED"; }

# retry_later REF WHY — an infrastructure failure: hold nothing, try this
# digest again after RETRY_SECONDS (logged at most once an hour)
retry_later() {
  stamp "retry-$(key "$1")"
  log_rl "retry-$(key "$1")" "$2: retrying $1 in ${RETRY_SECONDS}s (nothing held)"
}
# strike REF → count consecutive compose/image failures of REF; true at the
# second (then the count restarts): a failure that repeats is the image's
# own, and the digest gets held instead of flipping every RETRY_SECONDS
strike() {
  local f n
  f="$STATE_DIR/strikes-$(key "$1")"
  n=$(($(cat "$f" 2>/dev/null || echo 0) + 1))
  if ((n >= 2)); then
    rm -f "$f"
    return 0
  fi
  echo "$n" >"$f"
  return 1
}
clear_strikes() { rm -f "$STATE_DIR/strikes-$(key "$1")"; }
waiting_retry() {
  fresh_stamp "retry-$(key "$1")" "$RETRY_SECONDS" || return 1
  log_once "wait-$(key "$1")" "waiting to retry $1 after an infrastructure failure"
}

# step FN ARGS… — run FN in a subshell with errexit really on (bash ignores
# `set -e` inside anything called from if/&&/|| context), status in STEP_RC.
# Steps persist their state in images.env, which is read back afterwards.
STEP_RC=0
# The deploy steps are named explicitly so they're plain calls (and visible
# to shellcheck); anything else runs as given.
step() {
  set +e
  (
    set -e
    case "$1" in
      ensure_edge) ensure_edge ;;
      first_deploy) first_deploy "$2" "$3" ;;
      deploy_app) deploy_app "$2" ;;
      deploy_edge) deploy_edge "$2" ;;
      *) "$@" ;;
    esac
  )
  STEP_RC=$?
  set -e
  load_images
}

# ── images.env ────────────────────────────────────────────────────────────
APP="" PREV_APP="" CADDY="" PREV_CADDY="" CONTENT="" PREV_CONTENT=""
load_images() {
  APP="$(get_var "$IMAGES_ENV" APP_IMAGE)"
  PREV_APP="$(get_var "$IMAGES_ENV" PREV_APP_IMAGE)"
  CADDY="$(get_var "$IMAGES_ENV" CADDY_IMAGE)"
  PREV_CADDY="$(get_var "$IMAGES_ENV" PREV_CADDY_IMAGE)"
  CONTENT="$(get_var "$IMAGES_ENV" CADDY_CONTENT_IMAGE)"
  PREV_CONTENT="$(get_var "$IMAGES_ENV" PREV_CADDY_CONTENT_IMAGE)"
}
save_images() { # atomic: the old file stays if anything fails (e.g. disk full)
  local tmp
  tmp="$(mktemp "$COMPOSE_DIR/.images.XXXXXX")" || return 1
  if ! {
    echo "# Written by deploy.sh — digests verified with cosign" &&
      echo "APP_IMAGE=$APP" &&
      echo "CADDY_IMAGE=$CADDY" &&
      echo "PREV_APP_IMAGE=$PREV_APP" &&
      echo "PREV_CADDY_IMAGE=$PREV_CADDY" &&
      echo "CADDY_CONTENT_IMAGE=$CONTENT" &&
      echo "PREV_CADDY_CONTENT_IMAGE=$PREV_CONTENT" &&
      echo "UPDATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } >"$tmp" || ! chmod 0644 "$tmp" || ! mv -f "$tmp" "$IMAGES_ENV"; then
    rm -f "$tmp"
    log "could not write $IMAGES_ENV (disk full?)"
    return 1
  fi
  sync -f "$IMAGES_ENV" 2>/dev/null || sync
}

# ── Registry (anonymous) ──────────────────────────────────────────────────
BACKOFF="$STATE_DIR/backoff" # "<until epoch> <level>"

# backing_off → true while a GHCR 429 back-off is running
backing_off() {
  local until
  until="$(cut -d' ' -f1 "$BACKOFF" 2>/dev/null || true)"
  [[ "$until" =~ ^[0-9]+$ ]] && (($(date +%s) < until))
}

# back_off RETRY_AFTER — start/extend the back-off after a 429
back_off() {
  local level wait
  level="$(cut -d' ' -f2 "$BACKOFF" 2>/dev/null || true)"
  [[ "$level" =~ ^[0-9]+$ ]] || level=0
  wait=$((60 << level))
  ((wait <= 1800)) || wait=1800
  if [[ "$1" =~ ^[0-9]+$ ]] && (($1 > wait)); then wait=$1; fi
  echo "$(($(date +%s) + wait)) $((level < 5 ? level + 1 : 5))" >"$BACKOFF"
  log "GHCR rate limit (429): backing off for ${wait}s"
}

# http FILE_PREFIX CURL_ARGS… → status code; headers in FILE_PREFIX.h, body in .b
http() {
  local p="$1"
  shift
  curl -sS --max-time 20 -D "$p.h" -o "$p.b" -w '%{http_code}' "$@" 2>/dev/null || true
}

retry_after() { tr -d '\r' <"$1.h" | sed -n 's/^[Rr]etry-[Aa]fter: *\([0-9]*\).*/\1/p' | tail -n1; }

# registry_token [fresh] → anonymous pull token for both repos (cached 4 min)
registry_token() {
  local f="$STATE_DIR/token" code
  if [[ "${1:-}" != fresh && -s "$f" ]] && (($(date +%s) - $(stat -c %Y "$f") < 240)); then
    cat "$f"
    return 0
  fi
  code="$(http "$STATE_DIR/tok" \
    "https://$REGISTRY/token?scope=repository:${APP_REPO#"$REGISTRY"/}:pull&scope=repository:${CADDY_REPO#"$REGISTRY"/}:pull")"
  if [[ "$code" == 429 ]]; then
    back_off "$(retry_after "$STATE_DIR/tok")"
    return 1
  fi
  [[ "$code" == 200 ]] || { log_rl registry "registry token: HTTP $code"; return 1; }
  if ! jq -r '.token // empty' <"$STATE_DIR/tok.b" >"$f.new" 2>/dev/null || [[ ! -s "$f.new" ]]; then
    log_rl registry "registry token: no token in the answer"
    return 1
  fi
  mv -f "$f.new" "$f"
  cat "$f"
}

# resolve_digest REPO → sha256:… of the `prod` tag's manifest (index)
resolve_digest() {
  local repo="$1" path token code digest try
  path="${repo#"$REGISTRY"/}"
  for try in cached fresh; do
    token="$(registry_token "$try")" || return 1
    code="$(http "$STATE_DIR/head" -I \
      -H "Authorization: Bearer $token" \
      -H "Accept: application/vnd.oci.image.index.v1+json" \
      -H "Accept: application/vnd.docker.distribution.manifest.list.v2+json" \
      -H "Accept: application/vnd.oci.image.manifest.v1+json" \
      -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
      "https://$REGISTRY/v2/$path/manifests/$TAG")"
    [[ "$code" == 401 && "$try" == cached ]] && continue
    break
  done
  if [[ "$code" == 429 ]]; then
    back_off "$(retry_after "$STATE_DIR/head")"
    return 1
  fi
  [[ "$code" == 200 ]] || { log_rl registry "manifest $path:$TAG: HTTP $code"; return 1; }
  digest="$(tr -d '\r' <"$STATE_DIR/head.h" | sed -n 's/^[Dd]ocker-[Cc]ontent-[Dd]igest: *//p' | tail -n1)"
  [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || { log_rl registry "bad digest for $path:$TAG: '$digest'"; return 1; }
  echo "$digest"
}

# ── Images ────────────────────────────────────────────────────────────────
digest_hex() {
  local h="${1##*@sha256:}"
  [[ "$h" =~ ^[0-9a-f]{64}$ ]] || { log "not a digest reference: $1"; return 1; }
  echo "$h"
}

# verified REF → cosign keyless check. A failure (bad signature, or Sigstore
# unreachable) is retried after 10 min, not every minute.
verified() {
  local ref="$1" k
  k="verify-$(key "$ref")"
  if fresh_stamp "$k" 600; then
    log_once "$k" "signature check of $ref failed recently: retrying after 10 min"
    return 1
  fi
  log "verifying $ref"
  if docker run --rm --network host "$COSIGN_IMAGE" verify \
    --certificate-identity "$CERT_IDENTITY" \
    --certificate-oidc-issuer "$CERT_ISSUER" \
    "$ref" >/dev/null 2>&1; then
    rm -f "$STATE_DIR/stamp-$k"
    return 0
  fi
  stamp "$k"
  log "signature check FAILED for $ref: refusing it"
  return 1
}

pull() {
  log "pulling $1"
  docker pull -q "$1" >/dev/null 2>&1
}

# label IMAGE KEY → the image's label value ("" if unset); fails if the image
# can't be inspected
label() {
  local v
  [[ -n "$1" ]] || return 1
  v="$(docker image inspect -f "{{ index .Config.Labels \"$2\" }}" "$1" 2>/dev/null)" || return 1
  [[ "$v" == "<no value>" ]] && v=""
  printf '%s\n' "$v"
}
# build_of IMAGE → its io.voyager.build number; fails unless it is one
build_of() {
  local b
  b="$(label "$1" io.voyager.build)" || return 1
  [[ "$b" =~ ^[0-9]+$ ]] || return 1
  echo "$b"
}
image_id() { docker image inspect -f '{{.Id}}' "$1" 2>/dev/null; }

# runs SERVICE REF → the service's container exists and runs exactly REF
runs() {
  local cid have want
  cid="$(compose ps -q "$1" 2>/dev/null)" || return 1
  [[ -n "$cid" ]] || return 1
  have="$(docker inspect -f '{{.Image}}' "$cid" 2>/dev/null)" || return 1
  want="$(image_id "$2")" || return 1
  [[ -n "$want" && "$have" == "$want" ]]
}

# rm_image REF [KEEP…] — remove a no longer needed image (best effort)
rm_image() {
  local ref="$1" k
  shift
  [[ -n "$ref" ]] || return 0
  for k in "$@"; do [[ "$ref" != "$k" ]] || return 0; done
  docker image rm "$ref" >/dev/null 2>&1 || true
}
# drop_caddy_image REF — a Caddy image nothing refers to any more
drop_caddy_image() { rm_image "$1" "$CADDY" "$PREV_CADDY" "$CONTENT"; }

# ── Drain ─────────────────────────────────────────────────────────────────
# drain [WHAT] — before recreating Caddy or the app (either cuts every open
# SSE stream): wait up to DRAIN_TIMEOUT for the app's open streams to end
drain() {
  local deadline=$((SECONDS + DRAIN_TIMEOUT)) n what="${1:-Caddy}"
  while :; do
    n="$(curl -fsS --max-time 3 "$APP_STREAMS_URL" 2>/dev/null | jq -r '.active_streams // empty' 2>/dev/null || true)"
    if [[ ! "$n" =~ ^[0-9]+$ ]]; then
      log "drain: open-stream count unavailable; recreating $what now"
      return 0
    fi
    if ((n == 0)); then
      log "drain: no open streams"
      return 0
    fi
    if ((SECONDS >= deadline)); then
      log "drain: $n stream(s) still open after ${DRAIN_TIMEOUT}s; recreating $what anyway"
      return 0
    fi
    sleep "$POLL"
  done
}

# ── App ───────────────────────────────────────────────────────────────────
app_health() {
  local cid status
  cid="$(compose ps -q app 2>/dev/null || true)"
  [[ -n "$cid" ]] || { echo missing; return; }
  status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo missing)"
  echo "$status"
}

wait_healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) status
  while :; do # check first, then wait: one check even with a 0 s timeout
    status="$(app_health)"
    [[ "$status" == healthy ]] && return 0
    ((SECONDS < deadline)) || break
    sleep 5
  done
  log "app health after ${HEALTH_TIMEOUT}s: $(app_health)"
  return 1
}

# app_up REF → why it isn't up ("" = up and healthy): compose, image, health
app_up() {
  if ! compose up -d --no-deps app >/dev/null; then
    echo compose
  elif ! runs app "$1"; then
    echo image
  elif ! wait_healthy; then
    echo unhealthy
  fi
}

# deploy_app NEW → 0 nothing to do or deployed; 1 refused/failed; 3 only
# waiting to retry an earlier infrastructure failure (the edge still runs)
deploy_app() {
  local new="$1" old="$APP" old_prev="$PREV_APP" nb cb why
  [[ "$new" != "$APP" ]] || return 0
  if listed "$FAILED" "$new"; then
    log_once app-held "skipping $new: held (failed its health check, or rolled back from)"
    return 0
  fi
  if ((!ALLOW_DOWNGRADE)) && listed "$REFUSED" "$new"; then
    log_once app-refused "skipping $new: refused (downgrade or no build label; use --allow-downgrade)"
    return 0
  fi
  waiting_retry "$new" && return 3
  verified "$new" || return 1
  pull "$new" || { retry_later "$new" "pull failed"; return 1; }
  if ! nb="$(build_of "$new")"; then
    log "refusing $new: no readable io.voyager.build label"
    refuse "$new"
    rm_image "$new" "$APP" "$PREV_APP"
    return 1
  fi
  if ((!ALLOW_DOWNGRADE)); then
    if ! cb="$(build_of "$APP")"; then
      retry_later "$new" "cannot read the running app's build label ($APP)"
      return 1
    fi
    if ((nb < cb)); then
      log "refusing $new: built before the running app (use --allow-downgrade)"
      refuse "$new"
      rm_image "$new" "$APP" "$PREV_APP"
      return 0
    fi
  fi
  # New app pulled and checked: let open streams finish before it restarts
  drain app
  PREV_APP="$APP" APP="$new"
  save_images || { retry_later "$new" "images.env not written"; return 1; }
  log "deploying app=$APP"
  why="$(app_up "$APP")"
  if [[ -z "$why" ]]; then
    log "app healthy"
    clear_strikes "$new"
    rm_image "$old_prev" "$APP" "$PREV_APP"
    return 0
  fi
  log "app deploy failed ($why): rolling back to $old"
  APP="$old" PREV_APP="$old_prev"
  save_images || log "could not write images.env back (disk full?)"
  local back
  back="$(app_up "$APP")"
  if [[ "$why" == unhealthy ]]; then
    hold "$new"
    rm_image "$new" "$APP" "$PREV_APP"
    notify "[voyager] deploy rolled back" "New app $new failed its health check; ${back:-ok}: $old is running again."
  elif strike "$new"; then
    hold "$new"
    notify "[voyager] app deploy held" "compose could not start $new twice in a row ($why); held in $FAILED. $old is back (${back:-ok})."
  else
    retry_later "$new" "docker could not start it ($why)"
    notify "[voyager] app deploy failed (docker)" "compose could not start $new ($why); $old is back (${back:-ok}). It is retried in ${RETRY_SECONDS}s."
  fi
  return 1
}

# ── Edge: releases ────────────────────────────────────────────────────────
# release_id REF → the release directory name: the image's full digest (hex
# only, checked), so it can't collide and can't name anything but a release
release_id() { digest_hex "$1"; }

# link NAME → the release path NAME points at (releases/<id>), or ""
link() { readlink "$EDGE_DIR/$1" 2>/dev/null || true; }

# relink NAME TARGET — atomic symlink switch (relative target, rename over)
relink() {
  local tmp="$EDGE_DIR/.$1.$$"
  if [[ -z "$2" ]]; then
    rm -f "$EDGE_DIR/$1"
    return
  fi
  ln -sfn "$2" "$tmp" && mv -T -f "$tmp" "$EDGE_DIR/$1"
}

SAVED_LINKS=()
save_links() { SAVED_LINKS=("$(link current)" "$(link prev1)" "$(link prev2)"); }
restore_links() {
  if ! { relink prev2 "${SAVED_LINKS[2]}" && relink prev1 "${SAVED_LINKS[1]}" &&
    relink current "${SAVED_LINKS[0]}"; }; then
    log "could not restore the edge symlinks"
  fi
}

# switch_to ID — current → ID; the old current becomes prev1, prev1 prev2
switch_to() {
  local cur prev1
  cur="$(link current)" prev1="$(link prev1)"
  if [[ "$cur" != "releases/$1" ]]; then
    if [[ -n "$prev1" ]]; then relink prev2 "$prev1" || return 1; fi
    if [[ -n "$cur" ]]; then relink prev1 "$cur" || return 1; fi
  fi
  relink current "releases/$1"
}

# edge_ok → current points at a complete release
edge_ok() {
  local c="$EDGE_DIR/current"
  [[ -L "$c" && -f "$c/srv/index.html" && -f "$c/Caddyfile" && -f "$c/.complete" ]]
}

# prune — keep the releases current/prev1/prev2 point at, delete the rest
prune() {
  local keep d
  keep=" $(link current) $(link prev1) $(link prev2) "
  for d in "$EDGE_DIR"/releases/*/; do
    [[ -d "$d" ]] || continue
    d="${d%/}"
    [[ "$keep" == *" releases/${d##*/} "* ]] || rm -rf -- "$d"
  done
  rm -rf -- "$EDGE_DIR"/.staging/* 2>/dev/null || true
}

# check_release DIR — what an image put in /srv and the Caddyfile is served
# by Caddy (as uid 10002) and never executed. Refuse anything that could
# point outside the release: only regular files and directories.
check_release() {
  local dir="$1" bad ref mb
  [[ -d "$dir/srv" && ! -L "$dir/srv" ]] || { log "release: no /srv directory"; return 1; }
  [[ -f "$dir/Caddyfile" && ! -L "$dir/Caddyfile" ]] || { log "release: no regular Caddyfile"; return 1; }
  bad="$(find "$dir/srv" ! -type f ! -type d -print -quit)" || return 1
  [[ -z "$bad" ]] || { log "release: refusing non-regular file ${bad#"$dir"/} (symlink/device/fifo)"; return 1; }
  [[ -f "$dir/srv/index.html" ]] || { log "release: no srv/index.html"; return 1; }
  mb="$(du -sm "$dir/srv" | cut -f1)" || return 1
  ((mb <= EDGE_MAX_MB)) || { log "release: srv is ${mb} MB (> ${EDGE_MAX_MB} MB)"; return 1; }
  # Every asset index.html loads must be there (a broken build, not a 404 later)
  while IFS= read -r ref; do
    [[ -n "$ref" ]] || continue
    [[ "$ref" != *..* ]] || { log "release: bad asset path $ref"; return 1; }
    [[ -f "$dir/srv$ref" ]] || { log "release: index.html loads missing $ref"; return 1; }
  done < <(grep -oE '(src|href)="/assets/[^"?#]+' "$dir/srv/index.html" | sed 's/^[a-z]*="//' || true)
}

# finish_release TMP REL REF BUILD — normalise and move into place
finish_release() {
  local tmp="$1" rel="$2"
  { ((EUID != 0)) || chown -R 0:0 "$tmp"; } &&
    find "$tmp/srv" -type d -exec chmod 0755 {} + &&
    find "$tmp/srv" -type f -exec chmod 0644 {} + &&
    echo "$3" >"$tmp/SOURCE" &&
    echo "$4" >"$tmp/BUILD" &&
    chmod 0644 "$tmp/Caddyfile" "$tmp/SOURCE" "$tmp/BUILD" &&
    touch "$tmp/.complete" &&
    chmod 0755 "$tmp" &&
    rm -rf -- "$rel" &&
    mv -T "$tmp" "$rel"
}

# extract_release REF ID BUILD → 0 ok; 1 the content failed its checks
# (hold); 2 infrastructure (docker create/cp, disk): retry later
extract_release() {
  local ref="$1" id="$2" rel="$EDGE_DIR/releases/$2" tmp cid rc
  [[ -f "$rel/.complete" ]] && return 0 # already there (e.g. a rollback)
  install -d -m 0755 "$EDGE_DIR" "$EDGE_DIR/releases" || return 2
  install -d -m 0700 "$EDGE_DIR/.staging" || return 2
  rm -rf -- "$EDGE_DIR"/.staging/* || return 2
  tmp="$(mktemp -d "$EDGE_DIR/.staging/$id.XXXXXX")" || return 2
  if ! cid="$(docker create --pull never --network none "$ref" 2>/dev/null)"; then
    rm -rf -- "$tmp"
    log "docker create $ref failed"
    return 2
  fi
  rc=0
  docker cp "$cid:/srv" "$tmp/srv" >/dev/null 2>&1 &&
    docker cp "$cid:/etc/caddy/Caddyfile" "$tmp/Caddyfile" >/dev/null 2>&1 || rc=2
  docker rm -f "$cid" >/dev/null 2>&1 || true
  if ((rc)); then
    rm -rf -- "$tmp"
    log "docker cp out of $ref failed"
    return 2
  fi
  if ! check_release "$tmp"; then
    rm -rf -- "$tmp"
    log "release from $ref refused"
    return 1
  fi
  if ! finish_release "$tmp" "$rel" "$ref" "$3"; then
    rm -rf -- "$tmp" "$rel"
    log "writing release $id failed (disk full?)"
    return 2
  fi
}

# ── Edge: Caddy ───────────────────────────────────────────────────────────
caddy_cid() { compose ps -q caddy 2>/dev/null || true; }

# adapt IMAGE ID → 0 ok; 1 the Caddyfile is invalid (hold); 2 the check
# couldn't run (retry). Adapts + validates releases/ID/Caddyfile with IMAGE's
# Caddy in a throwaway container (no network, read-only, own memory limit:
# never a second Caddy inside the 96 MB Caddy container), with the real site
# values, into releases/ID/caddy.json (what reload posts).
adapt() {
  local image="$1" rel="$EDGE_DIR/releases/$2" out rc=0
  out="$(mktemp "$EDGE_DIR/.staging/adapt.XXXXXX")" || return 2
  docker run --rm --pull never --network none --read-only \
    --tmpfs /data:mode=1777 --tmpfs /config:mode=1777 --tmpfs /tmp:mode=1777 \
    --user 10002:10002 --cap-drop ALL --security-opt no-new-privileges:true --memory 128m \
    -e "SITE_HOST=$(get_var "$SITE_ENV" SITE_HOST)" -e "ACME_EMAIL=$(get_var "$SITE_ENV" ACME_EMAIL)" \
    -v "$EDGE_DIR:$EDGE_MOUNT:ro" --entrypoint caddy "$image" \
    adapt --config "$EDGE_MOUNT/releases/$2/Caddyfile" --adapter caddyfile --validate \
    >"$out" 2>"$out.err" || rc=$?
  if ((rc == 1)); then # caddy's own error exit; docker's are 125-127, 137…
    log "Caddyfile of release $2 does not validate with $image: $(tail -n3 "$out.err" | tr '\n' ' ')"
    rm -f "$out" "$out.err"
    return 1
  fi
  if ((rc)); then
    log_rl adapt "could not run caddy adapt in $image (exit $rc): $(tail -n1 "$out.err")"
    rm -f "$out" "$out.err"
    return 2
  fi
  rm -f "$out.err"
  if ! { chmod 0644 "$out" && mv -f "$out" "$rel/caddy.json"; }; then
    rm -f "$out"
    return 2
  fi
}

# caddy_admin → Caddy's container runs and its admin API answers
caddy_admin() {
  local cid
  cid="$(caddy_cid)"
  [[ -n "$cid" ]] && docker exec "$cid" wget -q -O /dev/null -T 5 http://127.0.0.1:2019/config/ >/dev/null 2>&1
}

# reload ID → 0 loaded; 1 Caddy refused the config (it keeps the old one);
# 2 Caddy/admin API not reachable. Loads releases/ID/caddy.json through the
# admin API inside the container (127.0.0.1:2019, busybox wget). Graceful:
# listeners are reused, open connections finish on the old config.
reload() {
  caddy_admin || return 2
  docker exec "$(caddy_cid)" wget -q -O /dev/null -T 30 \
    --header 'Content-Type: application/json' \
    --post-file "$EDGE_MOUNT/releases/$1/caddy.json" http://127.0.0.1:2019/load >/dev/null 2>&1 || return 1
}

# fetch PATH OUT → HTTP code of https://SITE_HOST/PATH straight from the Caddy
# container (compose IP: no DNAT, not subject to the governor's rules; -k: a
# local check of what is served, not of the certificate); 000 = no answer
fetch() {
  local host
  host="$(get_var "$SITE_ENV" SITE_HOST)"
  curl -sk --max-time 10 --resolve "$host:443:$CADDY_IP" -o "$2" -w '%{http_code}' \
    "https://$host$1" 2>/dev/null || true
}

# served ID → 0 Caddy serves ID's index.html and one of its assets; 1 it
# answers wrongly; 2 Caddy doesn't answer HTTPS at all
served() {
  local srv="$EDGE_DIR/releases/$1/srv" out code asset
  out="$(mktemp)" || return 2
  code="$(fetch / "$out")"
  if [[ "$code" == 000 ]]; then rm -f "$out"; return 2; fi
  if [[ "$code" != 200 ]] || ! cmp -s "$out" "$srv/index.html"; then
    log "Caddy check: / answered $code$([[ "$code" != 200 ]] || echo ', not the new index.html')"
    rm -f "$out"
    return 1
  fi
  asset="$(grep -oE 'src="/assets/[^"?#]+' "$srv/index.html" | head -n1 | sed 's/^src="//' || true)"
  if [[ -n "$asset" ]]; then
    code="$(fetch "$asset" "$out")"
    if [[ "$code" != 200 ]]; then
      log "Caddy check: $asset answered $code"
      rm -f "$out"
      return 1
    fi
  fi
  rm -f "$out"
}

# caddy_site_up → plain HTTP to Caddy (no certificate needed) answers with
# the site's redirect to https://SITE_HOST/: the site config is loaded
caddy_site_up() {
  local host hdr code
  host="$(get_var "$SITE_ENV" SITE_HOST)"
  hdr="$(mktemp)" || return 1
  code="$(curl -s --max-time 5 -o /dev/null -D "$hdr" -w '%{http_code}' -H "Host: $host" \
    "http://$CADDY_IP/" 2>/dev/null || true)"
  if [[ "$code" == 30[178] ]] && tr -d '\r' <"$hdr" | grep -qi "^location: https://$host/"; then
    rm -f "$hdr"
    return 0
  fi
  rm -f "$hdr"
  return 1
}

# https_baseline → 1 if HTTPS through Caddy gives NO answer right now (e.g.
# no certificate yet), else 0. Probed before a recreate: only then may the
# new container also give no HTTPS answer and still count as healthy.
https_baseline() {
  local id rc=0
  id="$(link current)"
  id="${id#releases/}"
  [[ -n "$id" ]] || { echo 1; return 0; }
  served "$id" >/dev/null 2>&1 || rc=$?
  if ((rc == 2)); then
    # Once more: a single slow or dropped probe must not loosen the check
    sleep "$POLL"
    rc=0
    served "$id" >/dev/null 2>&1 || rc=$?
  fi
  if ((rc == 2)); then echo 1; else echo 0; fi
}

# caddy_healthy ID REF [NO_TLS_OK] — after a (re)create: the container runs
# REF, its admin API answers, it can read /edge/current/srv/index.html,
# plain HTTP gets the site's redirect, and HTTPS serves ID's index.html and
# an asset. A WRONG HTTPS answer is always unhealthy; NO HTTPS answer is
# accepted only with NO_TLS_OK=1 (first deploy, or HTTPS gave no answer
# before the change either).
caddy_healthy() {
  local deadline=$((SECONDS + CADDY_HEALTH_TIMEOUT)) cid rc=0 no_tls_ok="${3:-0}"
  while :; do
    cid="$(caddy_cid)"
    if [[ -n "$cid" ]] && runs caddy "$2" && caddy_admin &&
      docker exec "$cid" test -r "$EDGE_MOUNT/current/srv/index.html" >/dev/null 2>&1 &&
      caddy_site_up; then
      rc=0
      served "$1" || rc=$?
      ((rc == 0)) && return 0
      if ((rc == 2 && no_tls_ok)); then
        log "warning: no HTTPS answer from Caddy (no certificate yet?), as before the change"
        return 0
      fi
    fi
    ((SECONDS < deadline)) || break
    sleep "$POLL"
  done
  local what=""
  if ((rc == 1)); then
    what=": wrong HTTPS answer"
  elif ((rc == 2)); then
    what=": no HTTPS answer"
  fi
  log "Caddy not healthy after ${CADDY_HEALTH_TIMEOUT}s$what"
  return 1
}

# caddy_stale → Caddy is running but compose would recreate it (its config
# hash, image included, differs from the running container's)
caddy_stale() {
  local cid want have
  cid="$(caddy_cid)"
  [[ -n "$cid" ]] || return 1
  [[ "$(docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null)" == true ]] || return 1
  want="$(compose config --hash caddy 2>/dev/null | awk '$1 == "caddy" {print $2}')"
  have="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.config-hash" }}' "$cid" 2>/dev/null || true)"
  [[ -n "$want" && -n "$have" && "$want" != "$have" ]]
}

# ensure_edge — every run, before anything else: the live Caddy image must
# have its release on disk (migration from the image-baked SPA, or a lost
# /var/lib/voyager/edge). Local only when the image is still there (the
# content image is kept until it is replaced); else re-pulled by its pinned,
# verified digest.
ensure_edge() {
  [[ -n "$CADDY" ]] || return 0 # first deploy builds the edge
  edge_ok && return 0
  local src="${CONTENT:-$CADDY}" id b
  log "edge: no current release; extracting it from $src"
  docker image inspect "$src" >/dev/null 2>&1 || pull "$src" || return 1
  id="$(release_id "$src")" || return 1
  b="$(build_of "$src" || true)"
  extract_release "$src" "$id" "$b" || return 1
  switch_to "$id" || return 1
  CONTENT="$src"
  save_images
}

# refuse_edge NEW WHY — hold a Caddy digest whose content failed its checks
refuse_edge() {
  hold "$1"
  notify "[voyager] Caddy deploy refused" "$1: $2. The previous release keeps running; the digest is held in $FAILED."
}

# edge_failed NEW RC WHAT — 1 (content) → hold + email; 2 → retry later
edge_failed() {
  if (($2 == 1)); then refuse_edge "$1" "$3"; else retry_later "$1" "$3 (infrastructure)"; fi
}

# deploy_edge NEW → 0 nothing to do or deployed; 1 refused/failed
deploy_edge() {
  local new="$1" id nb cb new_rt cur_rt rc
  [[ "$new" != "$CONTENT" ]] || return 0
  if listed "$FAILED" "$new"; then
    log_once caddy-held "skipping Caddy $new: held (failed its checks, or rolled back from)"
    return 0
  fi
  if ((!ALLOW_DOWNGRADE)) && listed "$REFUSED" "$new"; then
    log_once caddy-refused "skipping Caddy $new: refused (downgrade or no build label; use --allow-downgrade)"
    return 0
  fi
  waiting_retry "$new" && return 1
  verified "$new" || return 1
  pull "$new" || { retry_later "$new" "pull failed"; return 1; }
  if ! nb="$(build_of "$new")"; then
    log "refusing Caddy $new: no readable io.voyager.build label"
    refuse "$new"
    drop_caddy_image "$new"
    return 1
  fi
  if ((!ALLOW_DOWNGRADE)); then
    # The live release's build: its BUILD file, else the label of the image
    # it came from (CONTENT, kept on disk); never another image's
    cb="$(cat "$EDGE_DIR/current/BUILD" 2>/dev/null || true)"
    if [[ ! "$cb" =~ ^[0-9]+$ ]] && ! cb="$(build_of "$CONTENT")"; then
      retry_later "$new" "cannot tell which build the live release is"
      return 1
    fi
    if ((nb < cb)); then
      log "refusing Caddy $new: built before the live release (use --allow-downgrade)"
      refuse "$new"
      drop_caddy_image "$new"
      return 0
    fi
  fi
  id="$(release_id "$new")"
  rc=0
  extract_release "$new" "$id" "$nb" || rc=$?
  if ((rc)); then
    edge_failed "$new" "$rc" "its SPA/Caddyfile could not be taken out of the image"
    prune
    return 1
  fi
  new_rt="$(label "$new" io.voyager.caddy-runtime)" || { retry_later "$new" "cannot inspect it"; return 1; }
  cur_rt="$(label "$CADDY" io.voyager.caddy-runtime || true)"
  if [[ -n "$new_rt" && "$new_rt" == "$cur_rt" ]]; then
    deploy_content "$new" "$id"
  elif runtime_held "$new_rt"; then
    log_once "rt-held-$(key "$new_rt")" "Caddy runtime ${new_rt:0:12} is held: shipping only the SPA/Caddyfile of new images, on the current runtime"
    deploy_content "$new" "$id"
  else
    deploy_runtime "$new" "$id" "$new_rt"
  fi
}

# deploy_content NEW ID — on the running Caddy runtime: switch the SPA,
# reload the Caddyfile only if it changed. No restart, no dropped connection.
deploy_content() {
  local new="$1" id="$2" changed=0 old_id rc=0 left
  old_id="$(link current)"
  old_id="${old_id#releases/}"
  cmp -s "$EDGE_DIR/current/Caddyfile" "$EDGE_DIR/releases/$id/Caddyfile" || changed=1
  # Validated with the running runtime: that's the Caddy that will load it
  if ((changed)); then
    adapt "$CADDY" "$id" || rc=$?
    if ((rc)); then
      edge_failed "$new" "$rc" "its Caddyfile does not validate with the running Caddy"
      prune
      return 1
    fi
  fi
  save_links
  if ! switch_to "$id"; then
    restore_links
    retry_later "$new" "could not switch the edge symlinks"
    return 1
  fi
  if ((changed)); then
    reload "$id" || rc=$?
    if ((rc)); then
      restore_links
      if ((rc == 1)); then
        log "Caddyfile reload REFUSED: Caddy keeps the old config; release switched back"
        refuse_edge "$new" "the admin API refused its Caddyfile (Caddy kept the old config)"
      else
        retry_later "$new" "Caddy's admin API is not reachable"
      fi
      prune
      return 1
    fi
    log "Caddyfile reloaded (graceful)"
  fi
  served "$id" || rc=$?
  if ((rc == 1)); then
    restore_links
    if ((changed)) && [[ -n "$old_id" ]]; then
      if ! { adapt "$CADDY" "$old_id" && reload "$old_id"; }; then
        log "could not reload the previous Caddyfile"
      fi
    fi
    # Caddy answers, but wrongly, with this release (and its Caddyfile) in
    # place: the content's fault. Held, or it would flip live every retry.
    refuse_edge "$new" "Caddy did not serve its index.html and assets after the switch (switched back)"
    prune
    return 1
  fi
  ((rc == 0)) || log "Caddy did not answer the post-switch check (not running?); the converge step starts it"
  left="$CONTENT"
  PREV_CONTENT="$CONTENT" CONTENT="$new"
  if ! save_images; then
    log "release $id is live but images.env was not written; the next run records it"
    return 1
  fi
  log "SPA live: release $id from $new$( ((changed)) && echo ' (Caddyfile reloaded)')"
  prune
  # Keep the live content image (a lost edge directory is rebuilt offline)
  drop_caddy_image "$left"
}

# deploy_runtime NEW ID RUNTIME — new Caddy runtime (or none known yet:
# migration): validate with the NEW image, drain, recreate, check, roll back
# (holding that runtime) on failure
deploy_runtime() {
  local new="$1" id="$2" rt="$3" o_caddy="$CADDY" o_prev="$PREV_CADDY" o_content="$CONTENT" o_prev_content="$PREV_CONTENT" rc=0 why=""
  adapt "$new" "$id" || rc=$?
  if ((rc)); then
    edge_failed "$new" "$rc" "its Caddyfile does not validate with its own Caddy"
    prune
    return 1
  fi
  log "Caddy runtime changed ($(label "$CADDY" io.voyager.caddy-runtime 2>/dev/null | cut -c1-12) → ${rt:0:12}): recreating Caddy"
  save_links
  # No HTTPS answer is acceptable afterwards only if there was none before
  local no_tls_ok
  no_tls_ok="$(https_baseline)"
  drain
  if ! switch_to "$id"; then
    restore_links
    retry_later "$new" "could not switch the edge symlinks"
    return 1
  fi
  PREV_CADDY="$CADDY" CADDY="$new" PREV_CONTENT="$CONTENT" CONTENT="$new"
  if ! save_images; then
    restore_links
    retry_later "$new" "images.env not written"
    return 1
  fi
  if ! compose up -d --no-deps caddy >/dev/null; then
    why=compose
  elif ! runs caddy "$new"; then
    why=image # compose left the old container: docker, not the runtime
  elif ! caddy_healthy "$id" "$new" "$no_tls_ok"; then
    why=unhealthy
  fi
  if [[ -z "$why" ]]; then
    log "Caddy healthy on the new runtime: release $id from $new"
    clear_strikes "$new"
    prune
    # Only now, with the new runtime proven, may the one before PREV go
    rm_image "$o_prev" "$CADDY" "$PREV_CADDY" "$CONTENT"
    drop_caddy_image "$o_content"
    return 0
  fi
  log "Caddy deploy failed ($why) on $new: rolling back to $o_caddy"
  restore_links
  CADDY="$o_caddy" PREV_CADDY="$o_prev" CONTENT="$o_content" PREV_CONTENT="$o_prev_content"
  save_images || log "could not write images.env back (disk full?)"
  compose up -d --no-deps caddy >/dev/null || log "compose up caddy (rollback) failed"
  local back=ok
  caddy_healthy "${SAVED_LINKS[0]#releases/}" "$CADDY" "$no_tls_ok" || back="NOT healthy either"
  if [[ "$why" == unhealthy ]]; then
    hold_runtime "$rt"
    rm_image "$new" "$CADDY" "$PREV_CADDY" "$CONTENT"
    notify "[voyager] Caddy deploy rolled back" "New Caddy runtime ${rt:0:12} ($new) failed its checks and is held in $HELD_RUNTIMES; $o_caddy is back ($back). Images with that runtime now ship only their SPA/Caddyfile."
  elif strike "$new"; then
    hold "$new"
    notify "[voyager] Caddy deploy held" "compose could not recreate Caddy on $new twice in a row ($why); held in $FAILED. $o_caddy is back ($back)."
  else
    retry_later "$new" "compose could not recreate Caddy ($why)"
    notify "[voyager] Caddy deploy failed (docker)" "compose could not recreate Caddy on $new ($why); $o_caddy is back ($back). It is retried in ${RETRY_SECONDS}s."
  fi
  prune
  return 1
}

# ── First deploy (fresh VM) ───────────────────────────────────────────────
first_deploy() {
  local new_app="$1" new_caddy="$2" id nb rc=0
  verified "$new_app" || return 1
  verified "$new_caddy" || return 1
  pull "$new_app" || { log "first deploy: pull of $new_app failed"; return 1; }
  pull "$new_caddy" || { log "first deploy: pull of $new_caddy failed"; return 1; }
  nb="$(build_of "$new_caddy")" || { log "first deploy: $new_caddy has no build label"; return 1; }
  id="$(release_id "$new_caddy")"
  extract_release "$new_caddy" "$id" "$nb" || rc=$?
  if ((rc == 1)); then
    hold "$new_caddy"
    notify "[voyager] first deploy refused" "$new_caddy: its SPA/Caddyfile failed the checks."
  fi
  ((rc == 0)) || return 1
  switch_to "$id" || return 1
  APP="$new_app" CADDY="$new_caddy" CONTENT="$new_caddy"
  save_images || return 1
  log "deploying app=$APP caddy=$CADDY"
  if ! compose up -d --remove-orphans >/dev/null; then
    # No images.env: the next run starts the first deploy over
    rm -f "$IMAGES_ENV"
    log "first deploy: compose up failed"
    return 1
  fi
  if ! runs app "$APP" || ! wait_healthy; then
    hold "$new_app"
    notify "[voyager] first deploy unhealthy" "$new_app is not healthy and there is nothing to roll back to."
    return 1
  fi
  # Fresh VM: no certificate yet, so no HTTPS answer is fine (a wrong one isn't)
  caddy_healthy "$id" "$CADDY" 1 ||
    notify "[voyager] first deploy: Caddy not answering" "Check: docker compose logs caddy"
  log "first deploy healthy"
}

# ── Rollbacks (operator) ──────────────────────────────────────────────────
rollback_app() {
  [[ -n "$PREV_APP" ]] || die "no previous app digest to roll back to"
  log "manual rollback: $APP → $PREV_APP (holding $APP)"
  # Hold the digest we left, or the timer would redeploy it within a minute
  # while `prod` still points at it
  hold "$APP"
  local cur="$APP"
  APP="$PREV_APP" PREV_APP="$cur"
  save_images || die "could not write images.env"
  docker image inspect "$APP" >/dev/null 2>&1 || pull "$APP" || die "pull of $APP failed"
  local why
  why="$(app_up "$APP")"
  [[ -z "$why" ]] || die "rolled-back app is not up ($why)"
}

rollback_edge() {
  local cur prev changed=0 to left
  edge_ok || die "the edge directory is broken; run deploy.sh without options first"
  cur="$(link current)" prev="$(link prev1)"
  [[ -n "$prev" && -f "$EDGE_DIR/$prev/.complete" ]] || die "no previous SPA release to roll back to"
  cmp -s "$EDGE_DIR/$cur/Caddyfile" "$EDGE_DIR/$prev/Caddyfile" || changed=1
  if ((changed)); then
    adapt "$CADDY" "${prev#releases/}" || die "the previous release's Caddyfile does not validate with the running Caddy"
  fi
  to="$(cat "$EDGE_DIR/$prev/SOURCE" 2>/dev/null || echo "$PREV_CONTENT")"
  left="$CONTENT"
  log "manual SPA rollback: ${cur#releases/} → ${prev#releases/} (holding $left)"
  # Swap current and prev1: the release we leave stays an asset fallback for
  # browsers that already loaded its index.html. Running this again swaps
  # back, so the release returned to is released from the hold.
  save_links
  if ! { relink prev1 "$cur" && relink current "$prev"; }; then
    restore_links
    die "could not switch the edge symlinks"
  fi
  if ((changed)) && ! reload "${prev#releases/}"; then
    restore_links
    die "Caddy refused the previous Caddyfile (or isn't reachable); nothing changed"
  fi
  hold "$left"
  unhold "$to"
  CONTENT="$to" PREV_CONTENT="$left"
  save_images || die "release switched but images.env not written"
  log "SPA rolled back to release ${prev#releases/}$( ((changed)) && echo ' (Caddyfile reloaded)')"
}

rollback_caddy() {
  [[ -n "$PREV_CADDY" ]] || die "no previous Caddy runtime to roll back to"
  docker image inspect "$PREV_CADDY" >/dev/null 2>&1 || pull "$PREV_CADDY" || die "pull of $PREV_CADDY failed"
  edge_ok || die "the edge directory is broken; run deploy.sh without options first"
  local id rt cur="$CADDY"
  id="$(link current)"
  id="${id#releases/}"
  adapt "$PREV_CADDY" "$id" ||
    die "the live Caddyfile does not validate with $PREV_CADDY: run --rollback-edge first"
  rt="$(label "$CADDY" io.voyager.caddy-runtime || true)"
  log "manual Caddy rollback: $CADDY → $PREV_CADDY (holding runtime ${rt:0:12})"
  # Hold the runtime we leave: new images with it ship only their content
  if [[ -n "$rt" ]]; then hold_runtime "$rt"; else hold "$CADDY"; fi
  CADDY="$PREV_CADDY" PREV_CADDY="$cur"
  save_images || die "could not write images.env"
  local no_tls_ok
  no_tls_ok="$(https_baseline)"
  drain
  compose up -d --no-deps caddy >/dev/null || die "compose up caddy failed"
  caddy_healthy "$id" "$CADDY" "$no_tls_ok" || die "rolled-back Caddy is not healthy either"
}

# ── Converge ──────────────────────────────────────────────────────────────
CONVERGE_STAMP="$STATE_DIR/converge"

# config_hash → hash of everything compose reads from disk
config_hash() {
  local f
  for f in "$COMPOSE_DIR/compose.yaml" "$SITE_ENV" "$COMPOSE_DIR/app.env" "$IMAGES_ENV"; do
    printf '%s\n' "$f"
    cat "$f" 2>/dev/null || true
  done | sha256sum | cut -c1-64
}

# services_up → one `docker ps`: app and caddy both running
services_up() {
  local ps
  ps="$(docker ps -a --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" \
    --format '{{.Label "com.docker.compose.service"}} {{.State}}' 2>/dev/null)" || return 1
  grep -qx 'app running' <<<"$ps" && grep -qx 'caddy running' <<<"$ps"
}

# converge — bring back anything stopped and apply a changed compose.yaml /
# app.env / site.env. Skipped (one `docker ps`) when nothing changed and
# both services run. Caddy first, drained, when compose would recreate it.
converge() {
  [[ -n "$APP" && -n "$CADDY" ]] || return 0
  local h
  h="$(config_hash)"
  if [[ "$(cat "$CONVERGE_STAMP" 2>/dev/null)" == "$h" ]] && services_up; then
    return 0
  fi
  rm -f "$CONVERGE_STAMP"
  if ((EDGE_BROKEN)); then
    # Never (re)start Caddy without its release
    compose up -d --no-deps app >/dev/null || log_rl converge "compose up app (converge) failed"
    return 0
  fi
  if caddy_stale; then
    log "compose config of Caddy changed: draining, then recreating it"
    local no_tls_ok
    no_tls_ok="$(https_baseline)"
    drain
    if compose up -d --no-deps caddy >/dev/null; then
      caddy_healthy "$(link current | sed 's|^releases/||')" "$CADDY" "$no_tls_ok" ||
        notify "[voyager] Caddy unhealthy after a config change" "Check: docker compose logs caddy"
    else
      log "compose up caddy failed"
    fi
  fi
  if compose up -d --remove-orphans >/dev/null; then
    echo "$h" >"$CONVERGE_STAMP" 2>/dev/null || true
  else
    log_rl converge "compose up (converge) failed"
  fi
}

# ensure_unit — queue a start of voyager.service when it isn't active (the
# first deploy runs compose itself, and the unit's start is skipped while
# images.env is missing). Only an active unit gets its ExecStop (graceful
# stop + backup flush) at shutdown. --no-block: the unit's ExecStart waits
# for this script's lock, so waiting here would deadlock.
ensure_unit() {
  [[ -f "$IMAGES_ENV" ]] || return 0
  command -v systemctl >/dev/null || return 0
  systemctl is-active --quiet voyager.service && return 0
  systemctl start --no-block voyager.service 2>/dev/null ||
    log "could not queue a start of voyager.service"
}

ALLOW_DOWNGRADE=0
EDGE_BROKEN=0
main() {
  local mode=deploy
  for arg in "$@"; do
    case "$arg" in
      --window) log "--window: no longer needed (Caddy deploys automatically); running a normal deploy" ;;
      --rollback) mode=rollback-app ;;
      --rollback-edge) mode=rollback-edge ;;
      --rollback-caddy) mode=rollback-caddy ;;
      --allow-downgrade) ALLOW_DOWNGRADE=1 ;;
      *) die "unknown argument: $arg" ;;
    esac
  done

  exec 9>"$LOCK"
  flock -n 9 || { log "another deploy is running"; exit 0; }
  install -d -m 0700 "$STATE_DIR"

  load_images
  step ensure_edge
  if ((STEP_RC)); then
    # The app (and its rollbacks) must not depend on the edge
    EDGE_BROKEN=1
    log_rl edge "could not rebuild $EDGE_DIR/current from ${CONTENT:-$CADDY}; not touching Caddy"
    notify "[voyager] edge release missing" "deploy.sh could not rebuild $EDGE_DIR/current from ${CONTENT:-$CADDY}; Caddy was left as it is. App deploys continue."
  fi

  case "$mode" in
    rollback-app) rollback_app; ensure_unit; exit 0 ;;
    rollback-edge) rollback_edge; exit 0 ;;
    rollback-caddy) rollback_caddy; ensure_unit; exit 0 ;;
  esac

  if backing_off; then
    log_once backoff "GHCR back-off until $(date -u -d "@$(cut -d' ' -f1 "$BACKOFF")" +%H:%M:%SZ 2>/dev/null || echo later): not polling"
    converge
    ensure_unit
    exit 0
  fi

  local app_digest caddy_digest
  if ! app_digest="$(resolve_digest "$APP_REPO")" || ! caddy_digest="$(resolve_digest "$CADDY_REPO")"; then
    converge
    ensure_unit
    exit 1
  fi
  rm -f "$BACKOFF"

  local new_app="$APP_REPO@$app_digest" new_caddy="$CADDY_REPO@$caddy_digest" rc=0
  if [[ -z "$APP" || -z "$CADDY" ]]; then
    step first_deploy "$new_app" "$new_caddy"
    ensure_unit
    exit "$STEP_RC"
  fi

  # App first (the new SPA may call new endpoints), then the edge
  step deploy_app "$new_app"
  rc=$STEP_RC
  # 3: the app only waits to retry an infrastructure failure; the edge goes on
  if ((rc == 3)); then rc=0; fi
  if ((rc == 0 && !EDGE_BROKEN)); then
    step deploy_edge "$new_caddy"
    rc=$STEP_RC
  fi
  converge
  ensure_unit
  exit "$rc"
}

main "$@"
