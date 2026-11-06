#!/usr/bin/env bash
# Runs first-boot.sh for real (as root) with fake curl/docker/systemctl: the
# host bundle comes from bootstrap.sh's own builder, metadata and GHCR from
# the fake curl. Checks, on the first boot and on a later one:
#   - voyager.service ends up active (its ExecStop, the graceful stop and
#     backup flush, only runs at shutdown for an active unit);
#   - every start of a voyager unit is --no-block (the script runs inside
#     google-startup-scripts.service: a blocking start would deadlock boot);
#   - unpacking the bundle prints no tar warnings (e.g. macOS xattr headers).
# Writes to /opt, /etc and /var/lib: throwaway containers only (host_checks.sh).
set -euo pipefail

if [[ ! -f /.dockerenv && -z "${container:-}" ]] || ((EUID != 0)); then
  echo "first_boot_sim.sh: run as root in a throwaway container (host_checks.sh)" >&2
  exit 2
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
SIM="$(mktemp -d)"
trap 'rm -rf "$SIM"' EXIT
mkdir -p "$SIM/bin" "$SIM/work"
# Directories the Debian cloud image has and this slim container lacks
install -d /etc/sysctl.d /etc/default /etc/apt/apt.conf.d

# The bundle exactly as bootstrap.sh builds it (dry run: no gcloud needed)
BOOTSTRAP_WORK="$SIM/work" bash "$ROOT/infrastructure/gcp/bootstrap.sh" --dry-run \
  voyager-test 000000-000000-000000 ops@example.com >/dev/null 2>&1
[[ -s "$SIM/work/bundle.b64" ]] || { echo "FAIL bootstrap.sh built no bundle"; exit 1; }

cat >"$SIM/bin/curl" <<'EOF'
#!/usr/bin/env bash
url="${!#}" body="" code=200
case "$url" in
  */attributes/voyager-bundle) body="$(cat "$SIM/work/bundle.b64")" ;;
  */attributes/voyager-site-host) body=x.sslip.io ;;
  */attributes/voyager-acme-email | */attributes/voyager-alert-email) body=ops@example.com ;;
  */attributes/voyager-bucket) body=voyager-test-voyager-backup ;;
  */attributes/*) code=404 ;;
  */project/project-id) body=voyager-test ;;
  *token*) body='{"token":"t"}' ;;
  *travel-planner-app/manifests/prod*) printf 'Docker-Content-Digest: sha256:%064d\r\n' 1; exit 0 ;;
  *travel-planner-caddy/manifests/prod*) printf 'Docker-Content-Digest: sha256:%064d\r\n' 2; exit 0 ;;
  *) exit 1 ;;
esac
if [[ "$*" == *http_code* ]]; then printf '%s\n%s' "$body" "$code"; else printf '%s' "$body"; fi
EOF
cat >"$SIM/bin/docker" <<'EOF'
#!/usr/bin/env bash
case "$1 ${2:-}" in
  "compose version") exit 0 ;;
  compose*) [[ "$*" == *" ps -q app"* ]] && echo cid; exit 0 ;;
  "inspect "*) echo healthy ;;
esac
exit 0
EOF
# systemctl: records calls; starting voyager.service honours its
# ConditionPathExists (images.env) and then makes it active
cat >"$SIM/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
echo "$*" >>"$SIM/systemctl.log"
case "$1" in
  is-active) [[ -f "$SIM/voyager_active" ]] ;;
  start)
    if [[ " $* " == *" voyager"* && " $* " != *" --no-block "* ]]; then
      echo "BLOCKING systemctl $*" >>"$SIM/systemctl.log"; exit 99
    fi
    if [[ " $* " == *" voyager.service "* && -f /opt/voyager/images.env ]]; then
      touch "$SIM/voyager_active"
    fi ;;
esac
exit 0
EOF
printf '#!/bin/sh\nexit 0\n' >"$SIM/bin/logger"
chmod +x "$SIM/bin/"*
export SIM PATH="$SIM/bin:$PATH"

boot() {
  : >"$SIM/systemctl.log"
  rm -f "$SIM/voyager_active"  # a (re)boot: the unit starts out inactive
  if ! bash "$ROOT/deploy/gcp/host/first-boot.sh" 2>"$SIM/stderr"; then
    echo "FAIL $1: first-boot.sh exited non-zero"; cat "$SIM/stderr"; exit 1
  fi
  if grep -q '^tar: ' "$SIM/stderr"; then
    echo "FAIL $1: tar warnings while unpacking the bundle"; grep '^tar: ' "$SIM/stderr"; exit 1
  fi
  echo "ok   $1: first-boot.sh ran, bundle unpacked without tar warnings"
  if grep -q BLOCKING "$SIM/systemctl.log"; then
    echo "FAIL $1: blocking start of a voyager unit"; cat "$SIM/systemctl.log"; exit 1
  fi
  echo "ok   $1: voyager units only started with --no-block"
  [[ -f /opt/voyager/images.env ]] || { echo "FAIL $1: no images.env after the deploy"; exit 1; }
  if [[ ! -f "$SIM/voyager_active" ]]; then
    echo "FAIL $1: voyager.service not active (ExecStop would not run at shutdown)"
    cat "$SIM/systemctl.log"; exit 1
  fi
  echo "ok   $1: voyager.service active"
}

boot "first boot (no images.env yet)"
boot "later boot (images.env present)"
echo "first-boot simulation: ALL OK"
