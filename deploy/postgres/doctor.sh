#!/usr/bin/env bash
set -u
fail=0
ok(){ printf '[OK] %s\n' "$*"; }
bad(){ printf '[FAIL] %s\n' "$*"; fail=1; }
warn(){ printf '[WARN] %s\n' "$*"; }
[[ -r /etc/default/bw-monitor ]] || bad "missing /etc/default/bw-monitor"
[[ -r /etc/default/bw-monitor-postgres ]] || bad "missing /etc/default/bw-monitor-postgres"
if [[ -r /etc/default/bw-monitor ]]; then set -a; . /etc/default/bw-monitor; set +a; fi
if [[ -r /etc/default/bw-monitor-postgres ]]; then set -a; . /etc/default/bw-monitor-postgres; set +a; fi
systemctl is-active --quiet docker && ok "docker active" || bad "docker inactive"
docker inspect -f '{{.State.Health.Status}}' bw-timescaledb 2>/dev/null | grep -qx healthy && ok "TimescaleDB healthy" || bad "TimescaleDB not healthy"
systemctl is-active --quiet bw-monitor.service && ok "bw-monitor active" || bad "bw-monitor inactive"
systemctl is-active --quiet bw-monitor-retention.timer && ok "retention timer active" || bad "retention timer inactive"
if docker exec bw-timescaledb psql -U "${BW_PG_USER:-bw_monitor}" -d "${BW_PG_DATABASE:-bw_monitor}" -Atqc "SELECT extversion FROM pg_extension WHERE extname='timescaledb'" >/tmp/bw-ts-ver 2>/dev/null; then
  ok "TimescaleDB extension $(cat /tmp/bw-ts-ver)"
else bad "TimescaleDB extension query failed"; fi
if docker exec bw-timescaledb psql -U "${BW_PG_USER:-bw_monitor}" -d "${BW_PG_DATABASE:-bw_monitor}" -Atqc "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_schema='public'" >/tmp/bw-hyper 2>/dev/null; then
  count=$(cat /tmp/bw-hyper); [[ "$count" -ge 8 ]] && ok "$count hypertables" || warn "only $count hypertables"
else bad "hypertable query failed"; fi
port="${BW_PUBLIC_PORT:-8080}"
code=$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 2 --max-time 10 "http://127.0.0.1:$port/login" 2>/dev/null || echo 000)
case "$code" in 200|302) ok "local HTTP $code";; *) bad "local HTTP $code";; esac
[[ -f /opt/bw-monitor/bandwidth.db ]] && warn "legacy SQLite file exists but is NOT used by v50" || ok "no runtime SQLite database"
rm -f /tmp/bw-ts-ver /tmp/bw-hyper
exit "$fail"
