#!/usr/bin/env bash
set -Eeuo pipefail
set -a; . /etc/default/bw-monitor-postgres; set +a
docker exec bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$BW_PG_USER" -d "$BW_PG_DATABASE" <<'SQL'
\pset pager off
SELECT current_database() database, current_user db_user, pg_size_pretty(pg_database_size(current_database())) database_size;
SELECT extname,extversion FROM pg_extension WHERE extname IN ('timescaledb','plpgsql') ORDER BY extname;
SELECT hypertable_name,num_dimensions,num_chunks FROM timescaledb_information.hypertables WHERE hypertable_schema='public' ORDER BY hypertable_name;
SELECT relname,n_live_tup,n_dead_tup,last_autovacuum,last_autoanalyze FROM pg_stat_user_tables ORDER BY n_dead_tup DESC,relname LIMIT 30;
SELECT relname,pg_size_pretty(pg_total_relation_size(relid)) total_size,n_live_tup,n_dead_tup FROM pg_stat_user_tables WHERE relname IN ('vm_chart_5m','vm_raw_detail_5m','node_chart_5m') ORDER BY relname;
SELECT j.job_id,j.hypertable_name,j.proc_name,j.schedule_interval,j.scheduled,s.last_run_status,s.last_successful_finish FROM timescaledb_information.jobs j LEFT JOIN timescaledb_information.job_stats s USING(job_id) WHERE j.hypertable_schema='public' AND j.hypertable_name IN ('vm_chart_5m','vm_raw_detail_5m','node_chart_5m') ORDER BY j.hypertable_name,j.proc_name;
SELECT version,applied_at,description FROM bw_meta.schema_migrations ORDER BY applied_at,version;
SQL
