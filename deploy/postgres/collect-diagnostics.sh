#!/usr/bin/env bash
set -Eeuo pipefail
OUT="/root/bw-monitor-diagnostics-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
chmod 0700 "$OUT"
(cat /opt/bw-monitor/DEPLOY_VERSION || true) > "$OUT/version.txt" 2>&1
(systemctl status bw-monitor.service bw-monitor-retention.timer docker --no-pager -l || true) > "$OUT/services.txt" 2>&1
(journalctl -u bw-monitor.service -n 500 --no-pager || true) > "$OUT/monitor.log" 2>&1
(docker ps --no-trunc; docker logs --tail 300 bw-timescaledb 2>&1 || true) > "$OUT/docker.txt" 2>&1
(/opt/bw-monitor/db-check.sh || true) > "$OUT/database.txt" 2>&1
(ss -lntp || true; df -hT || true; free -h || true) > "$OUT/system.txt" 2>&1
for f in /etc/default/bw-monitor /etc/default/bw-monitor-postgres; do
  [[ -f "$f" ]] || continue
  sed -E "s#^(BW_MONITOR_TOKEN|BW_ADMIN_PASSWORD_HASH|BW_ADMIN_SECRET_KEY|BW_DATABASE_URL|BW_PG_PASSWORD)=.*#\1='<redacted>'#" "$f" > "$OUT/$(basename "$f").redacted"
done
tar -C /root -czf "$OUT.tar.gz" "$(basename "$OUT")"
sha256sum "$OUT.tar.gz" > "$OUT.tar.gz.sha256"
rm -rf "$OUT"
echo "$OUT.tar.gz"
