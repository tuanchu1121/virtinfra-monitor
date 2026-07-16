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
if docker exec bw-timescaledb psql -U "${BW_PG_USER:-bw_monitor}" -d "${BW_PG_DATABASE:-bw_monitor}" -Atqc "SELECT current_setting('timescaledb.license', true)" >/tmp/bw-ts-license 2>/dev/null; then
  license=$(cat /tmp/bw-ts-license)
  [[ "$license" == "timescale" ]] && ok "TimescaleDB Community capabilities enabled" || bad "TimescaleDB license=$license; Storage V2 needs Community Edition, not -oss"
else bad "TimescaleDB license query failed"; fi
if docker exec bw-timescaledb psql -U "${BW_PG_USER:-bw_monitor}" -d "${BW_PG_DATABASE:-bw_monitor}" -Atqc "SELECT count(DISTINCT proname) FROM pg_proc WHERE proname IN ('add_retention_policy','add_compression_policy')" >/tmp/bw-ts-caps 2>/dev/null; then
  count=$(cat /tmp/bw-ts-caps); [[ "$count" -eq 2 ]] && ok "Timescale retention/compression APIs available" || bad "Timescale policy APIs: $count/2"
else bad "Timescale capability query failed"; fi
if docker exec bw-timescaledb psql -U "${BW_PG_USER:-bw_monitor}" -d "${BW_PG_DATABASE:-bw_monitor}" -Atqc "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_schema='public'" >/tmp/bw-hyper 2>/dev/null; then
  count=$(cat /tmp/bw-hyper); [[ "$count" -ge 8 ]] && ok "$count hypertables" || warn "only $count hypertables"
else bad "hypertable query failed"; fi
if docker exec bw-timescaledb psql -U "${BW_PG_USER:-bw_monitor}" -d "${BW_PG_DATABASE:-bw_monitor}" -Atqc "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_schema='public' AND hypertable_name IN ('vm_chart_5m','vm_raw_detail_5m','node_chart_5m')" >/tmp/bw-v2-hyper 2>/dev/null; then
  count=$(cat /tmp/bw-v2-hyper); [[ "$count" -eq 3 ]] && ok "Storage V2 has 3 hypertables" || bad "Storage V2 hypertables: $count/3"
else bad "Storage V2 hypertable query failed"; fi
if docker exec bw-timescaledb psql -U "${BW_PG_USER:-bw_monitor}" -d "${BW_PG_DATABASE:-bw_monitor}" -Atqc "SELECT count(*) FROM timescaledb_information.jobs WHERE hypertable_schema='public' AND hypertable_name IN ('vm_chart_5m','vm_raw_detail_5m','node_chart_5m') AND proc_name IN ('policy_retention','policy_compression')" >/tmp/bw-v2-jobs 2>/dev/null; then
  count=$(cat /tmp/bw-v2-jobs); [[ "$count" -ge 5 ]] && ok "Storage V2 retention/compression jobs: $count" || bad "Storage V2 background jobs: $count/5"
else bad "Storage V2 job query failed"; fi
port="${BW_PUBLIC_PORT:-8080}"
code=$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 2 --max-time 10 "http://127.0.0.1:$port/login" 2>/dev/null || echo 000)
case "$code" in 200|302) ok "local HTTP $code";; *) bad "local HTTP $code";; esac
[[ -f /opt/bw-monitor/bandwidth.db ]] && warn "legacy SQLite file exists but is NOT used by v50" || ok "no runtime SQLite database"
rm -f /tmp/bw-ts-ver /tmp/bw-ts-license /tmp/bw-ts-caps /tmp/bw-hyper /tmp/bw-v2-hyper /tmp/bw-v2-jobs
exit "$fail"
