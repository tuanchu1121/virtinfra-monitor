\set ON_ERROR_STOP on

-- R21 Consumption ingest-time pre-aggregation.
-- Canonical per-VM tables are renamed in-place to preserve all existing data.
DO $$
BEGIN
    IF to_regclass('public.vm_consumption_hourly') IS NULL
       AND to_regclass('public.bandwidth_hourly') IS NOT NULL THEN
        ALTER TABLE public.bandwidth_hourly RENAME TO vm_consumption_hourly;
    END IF;
    IF to_regclass('public.vm_consumption_daily') IS NULL
       AND to_regclass('public.bandwidth_daily') IS NOT NULL THEN
        ALTER TABLE public.bandwidth_daily RENAME TO vm_consumption_daily;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS vm_consumption_hourly (
    hour_start BIGINT NOT NULL,
    node TEXT NOT NULL,
    vm_uuid TEXT NOT NULL,
    bridge TEXT NOT NULL,
    rx_bytes BIGINT NOT NULL DEFAULT 0,
    tx_bytes BIGINT NOT NULL DEFAULT 0,
    rx_packets BIGINT NOT NULL DEFAULT 0,
    tx_packets BIGINT NOT NULL DEFAULT 0,
    rx_drops BIGINT NOT NULL DEFAULT 0,
    tx_drops BIGINT NOT NULL DEFAULT 0,
    rx_errors BIGINT NOT NULL DEFAULT 0,
    tx_errors BIGINT NOT NULL DEFAULT 0,
    sample_count BIGINT NOT NULL DEFAULT 0,
    last_push BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (hour_start,node,vm_uuid,bridge)
);
CREATE TABLE IF NOT EXISTS vm_consumption_daily (
    day_start BIGINT NOT NULL,
    node TEXT NOT NULL,
    vm_uuid TEXT NOT NULL,
    bridge TEXT NOT NULL,
    rx_bytes BIGINT NOT NULL DEFAULT 0,
    tx_bytes BIGINT NOT NULL DEFAULT 0,
    rx_packets BIGINT NOT NULL DEFAULT 0,
    tx_packets BIGINT NOT NULL DEFAULT 0,
    rx_drops BIGINT NOT NULL DEFAULT 0,
    tx_drops BIGINT NOT NULL DEFAULT 0,
    rx_errors BIGINT NOT NULL DEFAULT 0,
    tx_errors BIGINT NOT NULL DEFAULT 0,
    sample_count BIGINT NOT NULL DEFAULT 0,
    last_push BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (day_start,node,vm_uuid,bridge)
);

ALTER TABLE node_consumption_hourly
    ADD COLUMN IF NOT EXISTS vm_public_rx_bytes BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vm_public_tx_bytes BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vm_private_rx_bytes BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vm_private_tx_bytes BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS physical_coverage_seconds BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vm_coverage_seconds BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS physical_sample_count BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vm_sample_count BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vm_count BIGINT NOT NULL DEFAULT 0;
ALTER TABLE node_consumption_daily
    ADD COLUMN IF NOT EXISTS vm_public_rx_bytes BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vm_public_tx_bytes BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vm_private_rx_bytes BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vm_private_tx_bytes BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS physical_coverage_seconds BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vm_coverage_seconds BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS physical_sample_count BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vm_sample_count BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vm_count BIGINT NOT NULL DEFAULT 0;

-- Preserve the established physical coverage counters during the migration.
UPDATE node_consumption_hourly
   SET physical_coverage_seconds=GREATEST(physical_coverage_seconds,coverage_seconds),
       physical_sample_count=GREATEST(physical_sample_count,sample_count)
 WHERE physical_coverage_seconds=0 OR physical_sample_count=0;
UPDATE node_consumption_daily
   SET physical_coverage_seconds=GREATEST(physical_coverage_seconds,coverage_seconds),
       physical_sample_count=GREATEST(physical_sample_count,sample_count)
 WHERE physical_coverage_seconds=0 OR physical_sample_count=0;

CREATE TABLE IF NOT EXISTS node_consumption_5m (
    bucket_start BIGINT NOT NULL,
    node TEXT NOT NULL,
    physical_public_rx_bytes BIGINT NOT NULL DEFAULT 0,
    physical_public_tx_bytes BIGINT NOT NULL DEFAULT 0,
    physical_private_rx_bytes BIGINT NOT NULL DEFAULT 0,
    physical_private_tx_bytes BIGINT NOT NULL DEFAULT 0,
    vm_public_rx_bytes BIGINT NOT NULL DEFAULT 0,
    vm_public_tx_bytes BIGINT NOT NULL DEFAULT 0,
    vm_private_rx_bytes BIGINT NOT NULL DEFAULT 0,
    vm_private_tx_bytes BIGINT NOT NULL DEFAULT 0,
    physical_coverage_seconds BIGINT NOT NULL DEFAULT 0,
    vm_coverage_seconds BIGINT NOT NULL DEFAULT 0,
    physical_sample_count BIGINT NOT NULL DEFAULT 0,
    vm_sample_count BIGINT NOT NULL DEFAULT 0,
    vm_count BIGINT NOT NULL DEFAULT 0,
    last_push BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket_start,node)
);

CREATE INDEX IF NOT EXISTS idx_vm_consumption_hourly_vm_time
    ON vm_consumption_hourly(vm_uuid,hour_start);
CREATE INDEX IF NOT EXISTS idx_vm_consumption_hourly_node_time
    ON vm_consumption_hourly(node,hour_start);
CREATE INDEX IF NOT EXISTS idx_vm_consumption_daily_vm_time
    ON vm_consumption_daily(vm_uuid,day_start);
CREATE INDEX IF NOT EXISTS idx_vm_consumption_daily_node_time
    ON vm_consumption_daily(node,day_start);
CREATE INDEX IF NOT EXISTS idx_node_consumption_5m_node_time
    ON node_consumption_5m(node,bucket_start);

-- Convert compact time-series tables to hypertables when TimescaleDB is available.
-- Dynamic SQL keeps this migration valid in disposable PostgreSQL test databases
-- that intentionally do not install the TimescaleDB extension.
DO $r21$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname='timescaledb') THEN
        EXECUTE $sql$SELECT create_hypertable('vm_consumption_hourly','hour_start',chunk_time_interval=>604800::bigint,if_not_exists=>TRUE,migrate_data=>TRUE)$sql$;
        EXECUTE $sql$SELECT create_hypertable('vm_consumption_daily','day_start',chunk_time_interval=>604800::bigint,if_not_exists=>TRUE,migrate_data=>TRUE)$sql$;
        EXECUTE $sql$SELECT create_hypertable('node_consumption_5m','bucket_start',chunk_time_interval=>86400::bigint,if_not_exists=>TRUE,migrate_data=>TRUE)$sql$;
    END IF;
END $r21$;

-- If application bootstrap created the canonical tables before this migration,
-- merge the pre-existing tables once, then replace the old names with views.
DO $$
DECLARE
    old_kind "char";
BEGIN
    SELECT c.relkind INTO old_kind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
     WHERE n.nspname='public' AND c.relname='bandwidth_hourly';
    IF old_kind IN ('r','p') THEN
        INSERT INTO vm_consumption_hourly SELECT * FROM bandwidth_hourly
        ON CONFLICT(hour_start,node,vm_uuid,bridge) DO UPDATE SET
          rx_bytes=EXCLUDED.rx_bytes,tx_bytes=EXCLUDED.tx_bytes,
          rx_packets=EXCLUDED.rx_packets,tx_packets=EXCLUDED.tx_packets,
          rx_drops=EXCLUDED.rx_drops,tx_drops=EXCLUDED.tx_drops,
          rx_errors=EXCLUDED.rx_errors,tx_errors=EXCLUDED.tx_errors,
          sample_count=EXCLUDED.sample_count,last_push=EXCLUDED.last_push;
        DROP TABLE bandwidth_hourly;
    END IF;
    SELECT c.relkind INTO old_kind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
     WHERE n.nspname='public' AND c.relname='bandwidth_daily';
    IF old_kind IN ('r','p') THEN
        INSERT INTO vm_consumption_daily SELECT * FROM bandwidth_daily
        ON CONFLICT(day_start,node,vm_uuid,bridge) DO UPDATE SET
          rx_bytes=EXCLUDED.rx_bytes,tx_bytes=EXCLUDED.tx_bytes,
          rx_packets=EXCLUDED.rx_packets,tx_packets=EXCLUDED.tx_packets,
          rx_drops=EXCLUDED.rx_drops,tx_drops=EXCLUDED.tx_drops,
          rx_errors=EXCLUDED.rx_errors,tx_errors=EXCLUDED.tx_errors,
          sample_count=EXCLUDED.sample_count,last_push=EXCLUDED.last_push;
        DROP TABLE bandwidth_daily;
    END IF;
END $$;

-- Read-only compatibility names for older reports and external SQL.
DO $$
BEGIN
    IF to_regclass('public.bandwidth_hourly') IS NULL THEN
        EXECUTE 'CREATE VIEW public.bandwidth_hourly AS SELECT * FROM public.vm_consumption_hourly';
    END IF;
    IF to_regclass('public.bandwidth_daily') IS NULL THEN
        EXECUTE 'CREATE VIEW public.bandwidth_daily AS SELECT * FROM public.vm_consumption_daily';
    END IF;
END $$;

INSERT INTO bw_meta.schema_migrations(version,description)
VALUES ('015_consumption_ingest_preaggregation','Node-only ingest-time Consumption pipeline and canonical VM rollups')
ON CONFLICT(version) DO NOTHING;
