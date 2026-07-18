#!/usr/bin/env bash
set -Eeuo pipefail
echo '=== VERSION ==='; cat /opt/bw-monitor/DEPLOY_VERSION
echo '=== SERVICES ==='; systemctl status bw-monitor.service bw-monitor-retention.timer docker --no-pager -l || true
echo '=== CONTAINER ==='; docker ps --filter name=bw-timescaledb --no-trunc
echo '=== DATABASE ==='; /opt/bw-monitor/db-check.sh
echo '=== LOCAL HTTP ==='; set -a; . /etc/default/bw-monitor; set +a; curl -I --max-time 10 "http://127.0.0.1:${BW_PUBLIC_PORT:-8080}/login" || true
echo '=== LISTENERS ==='; ss -lntp | grep -E ':(80|443|8080|55432)\b' || true
echo '=== DISK ==='; df -hT / /opt /var/lib/docker /var/backups 2>/dev/null || true
echo '=== RECENT ERRORS ==='; journalctl -u bw-monitor.service -p warning -n 100 --no-pager || true
