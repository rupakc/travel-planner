#!/usr/bin/env bash
# Host-level checks of the VM kit, in a throwaway Debian 13 container (the
# VM's OS; iptables-nft by default):
#   1. the governor's rules against real iptables, every tier, plus atomic
#      rejection (iptables_harness.py);
#   2. `systemd-analyze verify` of the systemd units.
#
# From the repo root:
#   docker run --rm --cap-add NET_ADMIN -v "$PWD:/src:ro" debian:trixie \
#     bash /src/deploy/gcp/tests/host_checks.sh
# (CI job "host-checks"; on a Linux host first: sudo modprobe -a ip_set
#  ip_set_hash_ip xt_set xt_hashlimit xt_multiport)
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends iptables ipset python3 systemd >/dev/null

echo "== governor rules on real iptables"
python3 /src/deploy/gcp/tests/iptables_harness.py

echo "== systemd-analyze verify"
install -d /opt/voyager
install -m 0755 /src/deploy/gcp/host/governor.py /src/deploy/gcp/host/deploy.sh \
  /src/deploy/gcp/host/window.sh /opt/voyager/
# docker (unit and binary), which the kit depends on, is missing here
printf '#!/bin/sh\nexit 0\n' >/usr/bin/docker && chmod +x /usr/bin/docker
printf '[Unit]\nDescription=stub docker\n[Service]\nExecStart=/bin/true\n' \
  >/etc/systemd/system/docker.service
cp /src/deploy/gcp/host/systemd/voyager*.service /src/deploy/gcp/host/systemd/voyager*.timer \
  /etc/systemd/system/
cd /etc/systemd/system
systemd-analyze verify voyager*.service voyager*.timer
echo "systemd units OK"
