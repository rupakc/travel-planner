#!/usr/bin/env bash
# Voyager VM provisioning: the GCE `startup-script` (runs on every boot,
# idempotent). Debian 13 (trixie), e2-micro, one 30 GB pd-standard disk.
#
# Reads from instance metadata (set by infrastructure/gcp/bootstrap.sh):
#   voyager-bundle       base64 tar.gz of deploy/gcp (compose, host scripts, units)
#   voyager-site-host    e.g. 34-23-1-2.sslip.io (later: your domain)
#   voyager-acme-email   Let's Encrypt account email
#   voyager-bucket       GCS backup bucket name
#   voyager-alert-email  where governor/deployer emails go
#   voyager-smtp-host / -port / -username / -from   (optional; the password is
#                        the Secret Manager secret smtp-password, never metadata)
#
# Installs Docker Engine + compose plugin (Docker's apt repo), zram swap,
# unattended-upgrades (security + Docker, nightly 03:30 Berlin; reboots only
# in the Sunday 04:00 Berlin window), the systemd units, and starts the first
# deploy. Secrets are never written to this disk.
set -euo pipefail

MD="http://metadata.google.internal/computeMetadata/v1/instance/attributes"
# md KEY → optional attribute ("" when absent). A metadata *error* (not a
# 404) aborts: a transient failure must never write empty settings.
md() {
  local out code
  out="$(curl -sS -w '\n%{http_code}' -H "Metadata-Flavor: Google" "$MD/$1")" ||
    { log "metadata server unreachable reading $1"; exit 1; }
  code="${out##*$'\n'}"
  case "$code" in
    200) printf '%s' "${out%$'\n'*}" ;;
    404) ;;
    *) log "metadata read of $1 failed (HTTP $code)"; exit 1 ;;
  esac
}
# need KEY → required attribute; aborts when absent or empty
need() {
  local v
  v="$(md "$1")"
  [[ -n "$v" ]] || { log "required metadata $1 is missing; refusing to continue"; exit 1; }
  printf '%s' "$v"
}
log() { echo "voyager-first-boot: $*" >&2; logger -t voyager-first-boot -- "$*" || true; }

OPT=/opt/voyager
DATA=/var/lib/voyager/data
STAMP=/var/lib/voyager/.provisioned
MARKER="$DATA/.voyager-data-disk"
export DEBIAN_FRONTEND=noninteractive

install_packages() {
  if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    return
  fi
  log "installing packages"
  apt-get update -q
  apt-get install -yq ca-certificates curl gnupg jq ipset iptables iproute2 \
    zram-tools unattended-upgrades apt-listchanges python3
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  local codename arch
  # shellcheck source=/dev/null
  codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
  arch="$(dpkg --print-architecture)"
  echo "deb [arch=$arch signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $codename stable" \
    >/etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
    docker-compose-plugin
}

configure_docker() {
  install -d /etc/docker
  cat >/etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "5" },
  "ipv6": false,
  "live-restore": false
}
JSON
  systemctl enable docker
  systemctl restart docker
}

configure_memory() {
  # zram instead of a swapfile: no disk thrash at 22 IOPS, no snapshot churn
  cat >/etc/default/zramswap <<'EOF'
ALGO=lz4
SIZE=512
PRIORITY=100
EOF
  echo "vm.swappiness=10" >/etc/sysctl.d/90-voyager.conf
  sysctl -q --system || true
  systemctl enable zramswap
  systemctl restart zramswap || log "zramswap failed to start (continuing)"
}

configure_upgrades() {
  cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
  cat >/etc/apt/apt.conf.d/52voyager-unattended <<'EOF'
// Debian security updates come from 50unattended-upgrades; add Docker's repo
Unattended-Upgrade::Origins-Pattern { "origin=Docker,label=Docker CE"; };
// Reboots happen only in the weekly window (voyager-window.timer)
Unattended-Upgrade::Automatic-Reboot "false";
EOF
  install -d /etc/systemd/system/apt-daily-upgrade.timer.d
  install -m 0644 "$OPT/host/systemd/apt-daily-upgrade-voyager.conf" \
    /etc/systemd/system/apt-daily-upgrade.timer.d/voyager.conf
}

unpack_bundle() {
  local bundle tmp
  bundle="$(need voyager-bundle)"
  tmp="$(mktemp -d)"
  echo "$bundle" | base64 -d | tar -xz -C "$tmp"
  install -d -m 0755 "$OPT" "$OPT/host"
  install -m 0644 "$tmp/compose.yaml" "$OPT/compose.yaml"
  install -m 0755 "$tmp/host/governor.py" "$OPT/governor.py"
  install -m 0755 "$tmp/host/deploy.sh" "$OPT/deploy.sh"
  install -m 0755 "$tmp/host/window.sh" "$OPT/window.sh"
  rm -rf "$OPT/host/systemd"
  cp -r "$tmp/host/systemd" "$OPT/host/systemd"
  [[ -f "$OPT/app.env" ]] || install -m 0644 "$tmp/app.env.example" "$OPT/app.env"
  rm -rf "$tmp"
}

write_config() {
  local site acme bucket alert project
  # Required, fail closed: an empty BACKUP_BUCKET would silently turn
  # backups off, an empty ALERT_TO would hide the governor's emails
  site="$(need voyager-site-host)"
  acme="$(need voyager-acme-email)"
  bucket="$(need voyager-bucket)"
  alert="$(need voyager-alert-email)"
  project="$(curl -fsS -H "Metadata-Flavor: Google" \
    http://metadata.google.internal/computeMetadata/v1/project/project-id)" ||
    { log "cannot read the project id"; exit 1; }
  [[ -n "$project" ]] || { log "empty project id"; exit 1; }
  printf 'SITE_HOST=%s\nACME_EMAIL=%s\n' "$site" "$acme" >"$OPT/site.env"
  # app.env is operator-editable; only fill BACKUP_BUCKET / APP_BASE_URL in
  sed -i "s|^BACKUP_BUCKET=.*|BACKUP_BUCKET=$bucket|; s|^APP_BASE_URL=.*|APP_BASE_URL=https://$site|; s|^CORS_ORIGINS=.*|CORS_ORIGINS=[\"https://$site\"]|; s|^GCP_PROJECT=.*|GCP_PROJECT=$project|" "$OPT/app.env"
  install -d -m 0755 /etc/voyager
  {
    echo "# Written by first-boot.sh from instance metadata (no secrets)"
    echo "ALERT_TO=$alert"
    echo "SMTP_HOST=$(md voyager-smtp-host)"
    local port
    port="$(md voyager-smtp-port)"
    echo "SMTP_PORT=${port:-587}"
    echo "SMTP_USERNAME=$(md voyager-smtp-username)"
    echo "SMTP_FROM=$(md voyager-smtp-from)"
    echo "SMTP_PASSWORD_SECRET=smtp-password"
  } >/etc/voyager/governor.env.new
  # Keep operator edits (e.g. GOVERNOR_CLOSE_GIB during the rollout test)
  if [[ -f /etc/voyager/governor.env ]]; then
    grep '^GOVERNOR_' /etc/voyager/governor.env >>/etc/voyager/governor.env.new || true
  fi
  mv -f /etc/voyager/governor.env.new /etc/voyager/governor.env
}

prepare_data_dir() {
  install -d -m 0755 /var/lib/voyager "$DATA"
  # The app runs as uid 10001 (backend/Dockerfile)
  chown -R 10001:10001 "$DATA"
  if [[ ! -f "$STAMP" ]]; then
    # First provisioning of this disk: mark it as the data disk. A disk
    # restored from a snapshot already has both files.
    [[ -f "$MARKER" ]] || echo "voyager data disk, provisioned $(date -u +%FT%TZ)" >"$MARKER"
    date -u +%FT%TZ >"$STAMP"
  elif [[ ! -f "$MARKER" ]]; then
    log "WARNING: $MARKER is missing on a provisioned disk; the app will refuse to start"
  fi
}

install_units() {
  install -m 0644 "$OPT"/host/systemd/voyager*.service "$OPT"/host/systemd/voyager*.timer \
    /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable voyager-governor-rules.service voyager.service \
    voyager-governor.timer voyager-deploy.timer voyager-window.timer
  systemctl restart apt-daily-upgrade.timer || true
}

main() {
  install_packages
  install -d -m 0755 "$OPT"
  unpack_bundle
  write_config
  configure_upgrades
  configure_memory
  [[ -f /etc/docker/daemon.json ]] || configure_docker
  prepare_data_dir
  install_units
  systemctl start voyager-governor-rules.service
  systemctl start voyager-governor.timer voyager-deploy.timer voyager-window.timer
  # First deploy now (also brings up compose). Later runs (every boot, or
  # after --update-host) apply the possibly changed compose.yaml/app.env:
  # `up -d` recreates only the services whose config changed.
  if [[ ! -f "$OPT/images.env" ]]; then
    "$OPT/deploy.sh" || log "first deploy failed; the timer retries every 5 min"
  else
    docker compose --project-directory "$OPT" --env-file "$OPT/site.env" \
      --env-file "$OPT/images.env" -f "$OPT/compose.yaml" up -d --remove-orphans
    systemctl start voyager.service
  fi
  log "done"
}

main "$@"
