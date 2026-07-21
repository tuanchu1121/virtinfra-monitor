\set ON_ERROR_STOP on

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE OR REPLACE FUNCTION public.bw_unix_now()
RETURNS BIGINT
LANGUAGE SQL
STABLE
PARALLEL SAFE
AS $$
    SELECT EXTRACT(EPOCH FROM clock_timestamp())::bigint
$$;

-- The Agent samples locally every 15 seconds and sends one durable payload every
-- 300 seconds. Raw metric chunks are one day, keeping active chunks compact while
-- the application's exact 2-day raw / 7-day hourly retention remains authoritative.
DO $$
DECLARE
    r record;
    relation_kind "char";
BEGIN
    FOR r IN
        SELECT * FROM (VALUES
            ('usage', 'time', 86400::bigint),
            ('node_stats', 'bucket', 86400::bigint),
            ('vm_perf_stats', 'time', 86400::bigint),
            ('node_host_stats', 'time', 86400::bigint),
            ('node_filesystem_stats', 'time', 86400::bigint),
            ('node_physical_net_stats', 'time', 86400::bigint),
            ('agent_health_stats', 'time', 86400::bigint),
            ('node_push_snapshots', 'bucket', 86400::bigint),
            ('bandwidth_hourly', 'hour_start', 604800::bigint),
            ('bandwidth_daily', 'day_start', 2592000::bigint)
        ) AS x(table_name, time_column, chunk_seconds)
    LOOP
        relation_kind := NULL;
        SELECT c.relkind
          INTO relation_kind
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
           AND c.relname = r.table_name;

        -- R21+ keeps bandwidth_hourly/bandwidth_daily as compatibility views.
        -- to_regclass() also resolves views, but create_hypertable() accepts only
        -- real or partitioned tables. Skip views/materialized views safely so
        -- update remains idempotent after migration 015.
        IF relation_kind IN ('r', 'p') THEN
            PERFORM create_hypertable(
                'public.' || r.table_name,
                r.time_column,
                chunk_time_interval => r.chunk_seconds,
                if_not_exists => TRUE,
                migrate_data => TRUE
            );
            PERFORM set_integer_now_func(
                'public.' || r.table_name,
                'public.bw_unix_now',
                replace_if_exists => TRUE
            );
        ELSIF relation_kind IS NOT NULL THEN
            RAISE NOTICE 'relation public.% has relkind %, skipping hypertable conversion',
                r.table_name,
                relation_kind;
        END IF;
    END LOOP;
END $$;

INSERT INTO bw_meta.schema_migrations(version, description)
VALUES ('002_timescale', 'Timescale hypertables for 5-minute metric/history tables')
ON CONFLICT (version) DO NOTHING;
