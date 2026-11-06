#!/usr/bin/env bash
# Simulates deploy.sh end to end with fake docker/curl (no registry, no
# containers): first deploy, upgrade, manual rollback + hold, a newer digest
# ending the hold, automatic rollback of an unhealthy image, downgrade
# refusal. Linux only (flock); run by host_checks.sh in CI.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DEPLOY="$HERE/../host/deploy.sh"
SIM="$(mktemp -d)"
trap 'rm -rf "$SIM"' EXIT
mkdir -p "$SIM/bin" "$SIM/opt"
printf 'SITE_HOST=x.sslip.io\nACME_EMAIL=a@b.c\n' >"$SIM/opt/site.env"
: >"$SIM/opt/compose.yaml"

d() { printf 'sha256:%064d' "$1"; }  # fake digest number N
APP="ghcr.io/rupakc/travel-planner-app"

# State the fakes read: which digest `prod` points at, the build label of each
# digest, which digests come up unhealthy, and what compose last ran.
d 1 >"$SIM/prod_app"
d 900 >"$SIM/prod_caddy"
: >"$SIM/unhealthy"
: >"$SIM/builds"

cat >"$SIM/bin/curl" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *token*) echo '{"token":"t"}' ;;
  *travel-planner-app/manifests/prod*) printf 'Docker-Content-Digest: %s\r\n' "$(cat "$SIM/prod_app")" ;;
  *travel-planner-caddy/manifests/prod*) printf 'Docker-Content-Digest: %s\r\n' "$(cat "$SIM/prod_caddy")" ;;
  *) exit 1 ;;
esac
EOF
cat >"$SIM/bin/docker" <<'EOF'
#!/usr/bin/env bash
running() { sed -n 's/^APP_IMAGE=//p' "$SIM/opt/images.env" 2>/dev/null; }
case "$1" in
  run) exit 0 ;;                  # cosign verify: signature OK
  pull) exit 0 ;;
  compose)
    case "$*" in
      *" ps -q app"*) echo cid ;;
      *" up "*) running >"$SIM/up_with" ;;
    esac ;;
  inspect)                        # health of the running app
    if grep -qxF "$(running)" "$SIM/unhealthy"; then echo unhealthy; else echo healthy; fi ;;
  image)
    case "$2" in
      inspect) ref="${!#}"; awk -v r="$ref" '$1==r{print $2}' "$SIM/builds" ;;
      *) exit 0 ;;
    esac ;;
esac
EOF
printf '#!/bin/sh\nexit 0\n' >"$SIM/bin/logger"
chmod +x "$SIM/bin/"*

export SIM PATH="$SIM/bin:$PATH" COMPOSE_DIR="$SIM/opt" LOCK="$SIM/lock" \
  VOYAGER_DEPLOY_CONFIG="$SIM/none" HEALTH_TIMEOUT=0

build() { echo "$APP@$(d "$1") $2" >>"$SIM/builds"; }
run() { bash "$DEPLOY" "$@" 2>>"$SIM/log" || true; }
app() { sed -n 's/^APP_IMAGE=//p' "$SIM/opt/images.env"; }
expect() {
  if [[ "$(app)" == "$APP@$(d "$1")" ]]; then echo "ok   $2"; else
    echo "FAIL $2: running $(app), expected $(d "$1")"; cat "$SIM/log"; exit 1
  fi
}
held() {
  if grep -qxF "$APP@$(d "$1")" "$SIM/opt/failed-digests"; then echo "ok   $2"; else
    echo "FAIL $2"; exit 1
  fi
}

build 1 1; build 2 2; build 3 3; build 4 4
run;                                    expect 1 "first deploy"
d 2 >"$SIM/prod_app"; run;    expect 2 "upgrade to a new signed digest"
run --rollback;                         expect 1 "manual rollback to the previous digest"
held 2 "rolled-back digest is held"
run;                                    expect 1 "timer does not redeploy the held digest"
d 3 >"$SIM/prod_app"; run;    expect 3 "a newer digest ends the hold"
echo "$APP@$(d 4)" >"$SIM/unhealthy"
d 4 >"$SIM/prod_app"; run;    expect 3 "unhealthy digest rolled back automatically"
held 4 "unhealthy digest is held"
run;                                    expect 3 "held unhealthy digest not retried"
d 1 >"$SIM/prod_app"; run;    expect 3 "older build refused (prod moved back)"
run --allow-downgrade;                  expect 1 "--allow-downgrade deploys it on purpose"
echo "deploy simulation: ALL OK"
