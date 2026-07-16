#!/usr/bin/env bash
set -Eeuo pipefail
DB_CONTAINER="${DB_CONTAINER:-bw-timescaledb}"
DB_USER="${DB_USER:-bw_monitor}"
DB_NAME="${DB_NAME:-bw_monitor}"

echo "== Runtime flags =="
grep -E '^VIRTINFRA_(STORAGE_V2|READ_CHART_V2|RAW_V2)=' /etc/default/bw-monitor || true

echo
echo "== Active database work =="
docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -P pager=off -c "
SELECT pid,state,wait_event_type,wait_event,now()-xact_start transaction_age,
       now()-query_start query_age,left(regexp_replace(query,E'[[:space:]]+',' ','g'),180) query
FROM pg_stat_activity
WHERE datname=current_database() AND pid<>pg_backend_pid() AND state<>'idle'
ORDER BY xact_start NULLS LAST;"

echo
echo "== Highest write churn =="
docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -P pager=off -c "
SELECT relname,n_live_tup,n_dead_tup,n_tup_ins,n_tup_upd,n_tup_hot_upd,n_tup_del,
       autovacuum_count,last_autovacuum
FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 20;"
