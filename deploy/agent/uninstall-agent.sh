#!/usr/bin/env bash
set -Eeuo pipefail
KEEP_STATE=0
while (($#)); do case "$1" in --keep-state) KEEP_STATE=1; shift;; -h|--help) echo 'Usage: uninstall-agent.sh [--keep-state]'; exit 0;; *) echo "Unknown option: $1" >&2; exit 1;; esac; done
[[ $(id -u) -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }
for unit in virtinfra-agent.service bwagent.service bwagent.timer bw-agent.service bw-agent.timer; do systemctl disable --now "$unit" >/dev/null 2>&1 || true; systemctl kill --kill-who=all --signal=KILL "$unit" >/dev/null 2>&1 || true; done
pkill -KILL -f '/usr/local/lib/(virtinfra-agent|bwagent)/agent.py' 2>/dev/null || true
rm -f /etc/systemd/system/virtinfra-agent.service /etc/systemd/system/bwagent.service /etc/systemd/system/bwagent.timer /etc/systemd/system/bw-agent.service /etc/systemd/system/bw-agent.timer /etc/virtinfra-agent.env /etc/bwagent.env /etc/default/bwagent /etc/sysconfig/bwagent /usr/local/sbin/virtinfra-agent-doctor /usr/local/sbin/bwagent-doctor /usr/local/sbin/bwagent-load-check /usr/local/sbin/bw-agent-load-check
rm -rf /usr/local/lib/virtinfra-agent /usr/local/lib/bwagent /opt/bwagent /opt/bw-agent /var/log/bwagent
((KEEP_STATE)) || rm -rf /var/lib/virtinfra-agent /var/lib/bw-agent /var/lib/bwagent
systemctl daemon-reload; systemctl reset-failed >/dev/null 2>&1 || true
echo 'VirtInfra Agent removed successfully.'
((KEEP_STATE==0)) || echo 'State preserved at /var/lib/virtinfra-agent.'
