#!/usr/bin/env bash
# Runs first-boot.sh for real (as root) with fake curl/docker/systemctl: the
# host bundle comes from bootstrap.sh's own builder, metadata and GHCR from
# the fake curl. Checks, on the first boot and on a later one:
#   - voyager.service ends up active (its ExecStop, the graceful stop and
#     backup flush, only runs at shutdown for an active unit);
#   - every start of a voyager unit is --no-block (the script runs inside
#     google-startup-scripts.service: a blocking start would deadlock boot);
#   - unpacking the bundle prints no tar warnings (e.g. macOS xattr headers);
#   - net.ipv4.ip_forward stays 1 (incident 2026-11-06): the GCE image ships
#     /etc/sysctl.d/60-gce-network-security.conf with ip_forward=0 and Docker
#     sets 1 only when dockerd starts, so a full sysctl reload under a running
#     Docker cut every container off. Checked after the first boot, after a
#     re-run on the live VM (`google_metadata_script_runner startup` after
#     --update-host, no reboot: the incident), after a reboot, and after a
#     later full reload (systemd-sysctl, a package upgrade).
# /proc/sys is read-only in an unprivileged container, so the kernel's
# sysctls are a fake tree under $SIM/proc/sys, driven by a fake sysctl that
# applies files the way procps does (--system: /etc/sysctl.d, /run/sysctl.d,
# /usr/local/lib/sysctl.d, /usr/lib/sysctl.d, /lib/sysctl.d by file name,
# first directory wins a name; /etc/sysctl.conf last) and a fake
# `systemctl start|restart docker` that sets ip_forward=1 like dockerd.
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
# ...and the file the real GCE Debian image ships (the incident's trigger)
printf '%s\n' '# Turns off IP forwarding (GCE image default)' 'net.ipv4.ip_forward=0' \
  >/etc/sysctl.d/60-gce-network-security.conf

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
# ConditionPathExists (images.env) and then makes it active; (re)starting
# docker sets ip_forward=1, as dockerd does
cat >"$SIM/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
echo "$*" >>"$SIM/systemctl.log"
if [[ "$1" == start || "$1" == restart ]] && [[ " $* " == *" docker "* ]]; then
  echo 1 >"$SIM/proc/sys/net/ipv4/ip_forward"
fi
case "$1" in
  is-active)  # voyager.service per the marker; anything else is running
    if [[ " $* " == *" voyager.service "* ]]; then [[ -f "$SIM/voyager_active" ]]; else exit 0; fi ;;
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
# sysctl: procps semantics against the fake tree $SIM/proc/sys. Logs each
# call, and whether 99-voyager-docker.conf existed at the time.
cat >"$SIM/bin/sysctl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
have99=no; [[ -f /etc/sysctl.d/99-voyager-docker.conf ]] && have99=yes
echo "sysctl $* (99-voyager-docker.conf: $have99)" >>"$SIM/sysctl.log"
set_key() {
  local f="$SIM/proc/sys/${1//.//}"
  mkdir -p "$(dirname "$f")"; printf '%s\n' "$2" >"$f"
}
apply_file() {
  local line k v
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" || "$line" == [\#\;]* ]] && continue
    k="${line%%=*}" v="${line#*=}"
    k="${k%"${k##*[![:space:]]}"}" v="${v#"${v%%[![:space:]]*}"}"
    set_key "${k#-}" "$v"
  done <"$1"
}
files=() system=0
while (($#)); do
  case "$1" in
    -q) ;;
    --system) system=1 ;;
    -p) files+=("${2:-/etc/sysctl.conf}"); shift ;;
    -p*) files+=("${1#-p}") ;;
    -w) set_key "${2%%=*}" "${2#*=}"; shift ;;
    *) echo "fake sysctl: unsupported argument $1" >&2; exit 2 ;;
  esac
  shift
done
if ((system)); then
  declare -A seen=()
  names=()
  for d in /etc/sysctl.d /run/sysctl.d /usr/local/lib/sysctl.d /usr/lib/sysctl.d /lib/sysctl.d; do
    for f in "$d"/*.conf; do
      [[ -f "$f" ]] || continue
      n="$(basename "$f")"
      [[ -n "${seen[$n]:-}" ]] && continue
      seen[$n]="$f"; names+=("$n")
    done
  done
  if ((${#names[@]})); then
    while IFS= read -r n; do apply_file "${seen[$n]}"; done < <(printf '%s\n' "${names[@]}" | sort)
  fi
  [[ -f /etc/sysctl.conf ]] && apply_file /etc/sysctl.conf
fi
for f in "${files[@]}"; do apply_file "$f"; done
EOF
printf '#!/bin/sh\nexit 0\n' >"$SIM/bin/logger"
chmod +x "$SIM/bin/"*
export SIM PATH="$SIM/bin:$PATH"
mkdir -p "$SIM/proc/sys/net/ipv4"

ip_forward() { cat "$SIM/proc/sys/net/ipv4/ip_forward" 2>/dev/null || echo unset; }

# kernel_boot — what the VM does before the startup script runs:
# systemd-sysctl applies every sysctl file, then dockerd (when installed and
# enabled) starts and sets ip_forward=1
kernel_boot() {
  sysctl -q --system
  if [[ -f /etc/docker/daemon.json ]]; then systemctl start docker; fi
}

# run_first_boot LABEL MODE — MODE boot: a (re)boot, the unit starts out
# inactive; MODE rerun: `google_metadata_script_runner startup` on the live
# VM (no reboot: the kernel and voyager.service keep their state)
run_first_boot() {
  : >"$SIM/systemctl.log"
  : >"$SIM/sysctl.log"
  if [[ "$2" == boot ]]; then
    rm -f "$SIM/voyager_active"
    kernel_boot
    : >"$SIM/sysctl.log"
  fi
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
  check_ip_forward "$1"
}

check_ip_forward() {
  if [[ "$(ip_forward)" != 1 ]]; then
    echo "FAIL $1: net.ipv4.ip_forward is $(ip_forward), not 1 (containers lose all routing)"
    cat "$SIM/sysctl.log"; exit 1
  fi
  if grep -q -- '--system' "$SIM/sysctl.log"; then
    echo "FAIL $1: first-boot.sh ran a full 'sysctl --system'"; cat "$SIM/sysctl.log"; exit 1
  fi
  if grep -q '99-voyager-docker.conf: no' "$SIM/sysctl.log"; then
    echo "FAIL $1: sysctl applied before 99-voyager-docker.conf was written"
    cat "$SIM/sysctl.log"; exit 1
  fi
  if ! grep -qx 'net.ipv4.ip_forward=1' /etc/sysctl.d/99-voyager-docker.conf; then
    echo "FAIL $1: 99-voyager-docker.conf does not set net.ipv4.ip_forward=1"; exit 1
  fi
  echo "ok   $1: net.ipv4.ip_forward stays 1 (no full sysctl reload, 99-voyager-docker.conf first)"
}

# zram_restarts N LABEL — zramswap restarted N times on the last run
zram_restarts() {
  local n
  n="$(grep -cx 'restart zramswap' "$SIM/systemctl.log" || true)"
  if [[ "$n" == "$1" ]]; then echo "ok   $2"; else
    echo "FAIL $2: zramswap restarted $n times"; cat "$SIM/systemctl.log"; exit 1
  fi
}

run_first_boot "first boot (no images.env yet)" boot
zram_restarts 1 "first boot: zramswap configured and restarted"
run_first_boot "re-run on the live VM (--update-host, the 2026-11-06 incident)" rerun
zram_restarts 0 "re-run, config unchanged: zramswap not restarted (no swapoff on the live VM)"
run_first_boot "later boot (images.env present)" boot
zram_restarts 0 "later boot, config unchanged: zramswap not restarted"
# A full reload later (systemd-sysctl restart, a package upgrade) under the
# running Docker: 99-voyager-docker.conf must still win over the image's 60-
sysctl -q --system
if [[ "$(ip_forward)" != 1 ]]; then
  echo "FAIL full sysctl reload after provisioning: ip_forward is $(ip_forward)"; exit 1
fi
echo "ok   full sysctl reload after provisioning: net.ipv4.ip_forward still 1"
echo "first-boot simulation: ALL OK"
