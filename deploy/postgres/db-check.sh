#!/usr/bin/env bash
set -Eeuo pipefail
set -a; . /etc/default/bw-monitor-postgres; set +a
docker exec bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$BW_PG_USER" -d "$BW_PG_DATABASE" <<'SQL'
\pset pager off
SELECT current_database() database, current_user db_user, pg_size_pretty(pg_database_size(current_database())) database_size;
SELECT extname,extversion FROM pg_extension WHERE extname IN ('timescaledb','plpgsql') ORDER BY extname;
SELECT hypertable_name,num_dimensions,num_chunks FROM timescaledb_information.hypertables WHERE hypertable_schema='public' ORDER BY hypertable_name;
SELECT relname,n_live_tup,n_dead_tup,last_autovacuum,last_autoanalyze FROM pg_stat_user_tables ORDER BY n_dead_tup DESC,relname LIMIT 30;
SELECT version,applied_at,description FROM bw_meta.schema_migrations ORDER BY applied_at,version;
SQL
