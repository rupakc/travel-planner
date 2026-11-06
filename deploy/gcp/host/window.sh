#!/usr/bin/env bash
# Weekly night window (Sunday 04:00 Europe/Berlin, voyager-window.timer):
# apply a staged Caddy image (it drops open connections), then reboot only
# if an upgrade asked for it. The app stops gracefully first (backup flush).
set -euo pipefail

log() { echo "voyager-window: $*" >&2; logger -t voyager-window -- "$*" 2>/dev/null || true; }

/opt/voyager/deploy.sh --window || log "deploy in window failed (see voyager-deploy logs)"
docker image prune -f >/dev/null 2>&1 || true

if [[ -f /run/reboot-required ]]; then
  log "reboot required by: $(tr '\n' ' ' </run/reboot-required.pkgs 2>/dev/null || echo '?')"
  systemctl stop voyager.service || true
  systemctl reboot
else
  log "no reboot required"
fi
