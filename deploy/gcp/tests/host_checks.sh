#!/usr/bin/env bash
# Host-level checks of the VM kit, in a throwaway Debian 13 container (the
# VM's OS; iptables-nft by default):
#   1. the governor's rules against real iptables, every tier, plus atomic
#      rejection (iptables_harness.py);
#   2. deploy.sh end to end with fake docker/curl/systemctl (test_deploy.py);
#   3. first-boot.sh for real with fake curl/docker/systemctl/sysctl, on a
#      first boot, a re-run on the live VM (--update-host) and a reboot:
#      voyager.service ends up active, only --no-block starts, no tar
#      warnings from the bundle, and net.ipv4.ip_forward stays 1 although the
#      GCE image's 60-gce-network-security.conf sets 0 (first_boot_sim.sh);
#   4. `systemd-analyze verify` of the systemd units.
#
# From the repo root:
#   docker run --rm --cap-add NET_ADMIN -v "$PWD:/src:ro" debian:trixie \
#     bash /src/deploy/gcp/tests/host_checks.sh
# (CI job "host-checks"; on a Linux host first: sudo modprobe -a ip_set
#  ip_set_hash_ip xt_set xt_hashlimit xt_multiport)
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends iptables ipset python3 python3-pytest systemd jq >/dev/null

echo "== governor rules on real iptables"
python3 /src/deploy/gcp/tests/iptables_harness.py

echo "== deployer (deploy.sh with fake docker/curl/systemctl: app + edge)"
python3 -m pytest -q -p no:cacheprovider /src/deploy/gcp/tests/test_deploy.py

echo "== first-boot simulation (first-boot.sh with fake curl/docker/systemctl/sysctl)"
bash /src/deploy/gcp/tests/first_boot_sim.sh

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
