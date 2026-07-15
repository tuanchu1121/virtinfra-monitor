\set ON_ERROR_STOP on

-- VirtInfra Monitor 50.4.0 storage V2.
-- Fresh-deployment schema: exact 5-minute chart points for 7 days, short raw
-- interface detail for 48 hours, and exact 5-minute physical-node chart points.
-- Existing current, Abuse, Storage I/O, Consumption and compatibility history
-- tables are intentionally left unchanged.

-- Storage V2 relies on Community Edition background retention and compression.
-- Fail before creating partial V2 objects when an Apache-only (-oss) image is
-- supplied, so the installer never reports a half-configured production state.
DO $$
DECLARE
    ts_license TEXT := current_setting('timescaledb.license', TRUE);
BEGIN
    IF ts_license IS DISTINCT FROM 'timescale' THEN
        RAISE EXCEPTION
            'Storage V2 requires TimescaleDB Community Edition (timescaledb.license=timescale); found %. Use timescale/timescaledb:2.27.2-pg17, not the -oss image.',
            COALESCE(ts_license, '<unset>');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'add_retention_policy') THEN
        RAISE EXCEPTION 'Storage V2 requires add_retention_policy(), but the function is unavailable.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'add_compression_policy') THEN
        RAISE EXCEPTION 'Storage V2 requires add_compression_policy(), but the function is unavailable.';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS vm_chart_5m (
    bucket BIGINT NOT NULL,
    node TEXT NOT NULL,
    vm_uuid TEXT NOT NULL,
    last_push BIGINT NOT NULL,
    interval_seconds INTEGER NOT NULL DEFAULT 300,
    iface_count INTEGER NOT NULL DEFAULT 0,

    public_rx_bytes BIGINT NOT NULL DEFAULT 0,
    public_tx_bytes BIGINT NOT NULL DEFAULT 0,
    private_rx_bytes BIGINT NOT NULL DEFAULT 0,
    private_tx_bytes BIGINT NOT NULL DEFAULT 0,
    rx_bytes BIGINT NOT NULL DEFAULT 0,
    tx_bytes BIGINT NOT NULL DEFAULT 0,
    total_bytes BIGINT NOT NULL DEFAULT 0,

    public_rx_packets BIGINT NOT NULL DEFAULT 0,
    public_tx_packets BIGINT NOT NULL DEFAULT 0,
    private_rx_packets BIGINT NOT NULL DEFAULT 0,
    private_tx_packets BIGINT NOT NULL DEFAULT 0,
    rx_packets BIGINT NOT NULL DEFAULT 0,
    tx_packets BIGINT NOT NULL DEFAULT 0,
    total_packets BIGINT NOT NULL DEFAULT 0,

    public_rx_mbps DOUBLE PRECISION NOT NULL DEFAULT 0,
    public_tx_mbps DOUBLE PRECISION NOT NULL DEFAULT 0,
    private_rx_mbps DOUBLE PRECISION NOT NULL DEFAULT 0,
    private_tx_mbps DOUBLE PRECISION NOT NULL DEFAULT 0,
    rx_mbps DOUBLE PRECISION NOT NULL DEFAULT 0,
    tx_mbps DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_mbps DOUBLE PRECISION NOT NULL DEFAULT 0,

    public_rx_pps DOUBLE PRECISION NOT NULL DEFAULT 0,
    public_tx_pps DOUBLE PRECISION NOT NULL DEFAULT 0,
    private_rx_pps DOUBLE PRECISION NOT NULL DEFAULT 0,
    private_tx_pps DOUBLE PRECISION NOT NULL DEFAULT 0,
    rx_pps DOUBLE PRECISION NOT NULL DEFAULT 0,
    tx_pps DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_pps DOUBLE PRECISION NOT NULL DEFAULT 0,

    public_peak_mbps DOUBLE PRECISION NOT NULL DEFAULT 0,
    private_peak_mbps DOUBLE PRECISION NOT NULL DEFAULT 0,
    rx_peak_mbps DOUBLE PRECISION NOT NULL DEFAULT 0,
    tx_peak_mbps DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_peak_mbps DOUBLE PRECISION NOT NULL DEFAULT 0,
    public_peak_pps DOUBLE PRECISION NOT NULL DEFAULT 0,
    private_peak_pps DOUBLE PRECISION NOT NULL DEFAULT 0,
    rx_peak_pps DOUBLE PRECISION NOT NULL DEFAULT 0,
    tx_peak_pps DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_peak_pps DOUBLE PRECISION NOT NULL DEFAULT 0,

    sample_count BIGINT NOT NULL DEFAULT 0,
    sample_expected BIGINT NOT NULL DEFAULT 0,
    sample_max_gap DOUBLE PRECISION NOT NULL DEFAULT 0,
    sample_quality TEXT NOT NULL DEFAULT 'LEGACY',
    seconds_over_pps BIGINT NOT NULL DEFAULT 0,
    seconds_over_mbps BIGINT NOT NULL DEFAULT 0,
    seconds_over_rx_pps BIGINT NOT NULL DEFAULT 0,
    seconds_over_tx_pps BIGINT NOT NULL DEFAULT 0,
    drops BIGINT NOT NULL DEFAULT 0,
    errors BIGINT NOT NULL DEFAULT 0,

    cpu_full_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
    cpu_core_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
    vcpu_current INTEGER NOT NULL DEFAULT 0,
    ram_current_kib BIGINT NOT NULL DEFAULT 0,
    ram_maximum_kib BIGINT NOT NULL DEFAULT 0,
    ram_rss_kib BIGINT NOT NULL DEFAULT 0,
    ram_available_kib BIGINT NOT NULL DEFAULT 0,
    ram_unused_kib BIGINT NOT NULL DEFAULT 0,
    ram_usable_kib BIGINT NOT NULL DEFAULT 0,
    disk_read_bps DOUBLE PRECISION NOT NULL DEFAULT 0,
    disk_write_bps DOUBLE PRECISION NOT NULL DEFAULT 0,
    disk_read_iops DOUBLE PRECISION NOT NULL DEFAULT 0,
    disk_write_iops DOUBLE PRECISION NOT NULL DEFAULT 0,

    -- Compact interface detail is retained with the chart row so the existing
    -- bridge/interface selector can still reconstruct exact 5-minute charts for
    -- the full 7-day window after raw-detail retention has expired.
    interfaces_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (bucket, node, vm_uuid)
);

CREATE TABLE IF NOT EXISTS vm_raw_detail_5m (
    bucket BIGINT NOT NULL,
    node TEXT NOT NULL,
    vm_uuid TEXT NOT NULL,
    bridge TEXT NOT NULL,
    iface TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'other',
    last_push BIGINT NOT NULL,
    interval_seconds INTEGER NOT NULL DEFAULT 300,
    rx_delta BIGINT NOT NULL DEFAULT 0,
    tx_delta BIGINT NOT NULL DEFAULT 0,
    rx_packets_delta BIGINT NOT NULL DEFAULT 0,
    tx_packets_delta BIGINT NOT NULL DEFAULT 0,
    rx_drop_delta BIGINT NOT NULL DEFAULT 0,
    tx_drop_delta BIGINT NOT NULL DEFAULT 0,
    rx_error_delta BIGINT NOT NULL DEFAULT 0,
    tx_error_delta BIGINT NOT NULL DEFAULT 0,
    rx_mbps_peak DOUBLE PRECISION NOT NULL DEFAULT 0,
    tx_mbps_peak DOUBLE PRECISION NOT NULL DEFAULT 0,
    rx_pps_peak DOUBLE PRECISION NOT NULL DEFAULT 0,
    tx_pps_peak DOUBLE PRECISION NOT NULL DEFAULT 0,
    rx_packet_size_avg DOUBLE PRECISION NOT NULL DEFAULT 0,
    tx_packet_size_avg DOUBLE PRECISION NOT NULL DEFAULT 0,
    network_sample_count BIGINT NOT NULL DEFAULT 0,
    network_sample_expected BIGINT NOT NULL DEFAULT 0,
    network_sample_max_gap_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
    seconds_over_pps BIGINT NOT NULL DEFAULT 0,
    seconds_over_mbps BIGINT NOT NULL DEFAULT 0,
    seconds_over_rx_pps BIGINT NOT NULL DEFAULT 0,
    seconds_over_tx_pps BIGINT NOT NULL DEFAULT 0,
    network_sample_quality TEXT NOT NULL DEFAULT 'LEGACY',
    PRIMARY KEY (bucket, node, vm_uuid, bridge, iface)
);

CREATE TABLE IF NOT EXISTS node_chart_5m (
    bucket BIGINT NOT NULL,
    node TEXT NOT NULL,
    last_push BIGINT NOT NULL,
    interval_seconds INTEGER NOT NULL DEFAULT 300,
    vm_count INTEGER NOT NULL DEFAULT 0,
    iface_count INTEGER NOT NULL DEFAULT 0,
    public_bytes BIGINT NOT NULL DEFAULT 0,
    private_bytes BIGINT NOT NULL DEFAULT 0,
    total_bytes BIGINT NOT NULL DEFAULT 0,
    public_packets BIGINT NOT NULL DEFAULT 0,
    private_packets BIGINT NOT NULL DEFAULT 0,
    total_packets BIGINT NOT NULL DEFAULT 0,
    drops BIGINT NOT NULL DEFAULT 0,
    errors BIGINT NOT NULL DEFAULT 0,
    load1 DOUBLE PRECISION NOT NULL DEFAULT 0,
    load5 DOUBLE PRECISION NOT NULL DEFAULT 0,
    load15 DOUBLE PRECISION NOT NULL DEFAULT 0,
    cpu_count INTEGER NOT NULL DEFAULT 0,
    cpu_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
    mem_total BIGINT NOT NULL DEFAULT 0,
    mem_available BIGINT NOT NULL DEFAULT 0,
    mem_used BIGINT NOT NULL DEFAULT 0,
    swap_total BIGINT NOT NULL DEFAULT 0,
    swap_used BIGINT NOT NULL DEFAULT 0,
    disk_read_bps DOUBLE PRECISION NOT NULL DEFAULT 0,
    disk_write_bps DOUBLE PRECISION NOT NULL DEFAULT 0,
    uptime_seconds BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket, node)
);

DO $$
BEGIN
    PERFORM create_hypertable(
        'public.vm_chart_5m', 'bucket',
        chunk_time_interval => 10800::bigint,
        if_not_exists => TRUE,
        migrate_data => TRUE
    );
    PERFORM set_integer_now_func('public.vm_chart_5m', 'public.bw_unix_now', replace_if_exists => TRUE);

    PERFORM create_hypertable(
        'public.vm_raw_detail_5m', 'bucket',
        chunk_time_interval => 10800::bigint,
        if_not_exists => TRUE,
        migrate_data => TRUE
    );
    PERFORM set_integer_now_func('public.vm_raw_detail_5m', 'public.bw_unix_now', replace_if_exists => TRUE);

    PERFORM create_hypertable(
        'public.node_chart_5m', 'bucket',
        chunk_time_interval => 21600::bigint,
        if_not_exists => TRUE,
        migrate_data => TRUE
    );
    PERFORM set_integer_now_func('public.node_chart_5m', 'public.bw_unix_now', replace_if_exists => TRUE);
END $$;

-- Query-driven indexes only. The primary key already supports time pruning and
-- retry idempotency; these indexes serve per-VM and per-node chart lookups.
CREATE INDEX IF NOT EXISTS idx_v5040_vm_chart_vm_time
    ON vm_chart_5m (node, vm_uuid, bucket DESC);
CREATE INDEX IF NOT EXISTS idx_v5040_vm_chart_node_time
    ON vm_chart_5m (node, bucket DESC);
CREATE INDEX IF NOT EXISTS idx_v5040_vm_raw_vm_time
    ON vm_raw_detail_5m (node, vm_uuid, bucket DESC);
CREATE INDEX IF NOT EXISTS idx_v5040_vm_raw_node_time
    ON vm_raw_detail_5m (node, bucket DESC);
CREATE INDEX IF NOT EXISTS idx_v5040_vm_raw_bridge_time
    ON vm_raw_detail_5m (node, bridge, bucket DESC);
CREATE INDEX IF NOT EXISTS idx_v5040_node_chart_node_time
    ON node_chart_5m (node, bucket DESC);

-- Chart data is immutable after retry/upsert settlement. Compress only data older
-- than 48 hours, while the short raw-detail hypertable is simply retired by
-- chunk retention. The SQL remains idempotent on repeated installer/update runs.
ALTER TABLE vm_chart_5m SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'node,vm_uuid',
    timescaledb.compress_orderby = 'bucket DESC'
);
ALTER TABLE node_chart_5m SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'node',
    timescaledb.compress_orderby = 'bucket DESC'
);

DO $$
BEGIN
    PERFORM add_retention_policy(
        'public.vm_chart_5m',
        drop_after => 604800::bigint,
        schedule_interval => INTERVAL '1 hour',
        if_not_exists => TRUE
    );
    PERFORM add_retention_policy(
        'public.vm_raw_detail_5m',
        drop_after => 172800::bigint,
        schedule_interval => INTERVAL '1 hour',
        if_not_exists => TRUE
    );
    PERFORM add_retention_policy(
        'public.node_chart_5m',
        drop_after => 604800::bigint,
        schedule_interval => INTERVAL '1 hour',
        if_not_exists => TRUE
    );
    PERFORM add_compression_policy(
        'public.vm_chart_5m',
        compress_after => 172800::bigint,
        schedule_interval => INTERVAL '1 hour',
        if_not_exists => TRUE
    );
    PERFORM add_compression_policy(
        'public.node_chart_5m',
        compress_after => 172800::bigint,
        schedule_interval => INTERVAL '1 hour',
        if_not_exists => TRUE
    );
END $$;

INSERT INTO bw_meta.schema_migrations(version, description)
VALUES (
    '004_storage_v2',
    'Exact 5-minute VM/node chart hypertables, 48-hour raw interface detail, retention and compression policies'
)
ON CONFLICT (version) DO NOTHING;

ANALYZE vm_chart_5m, vm_raw_detail_5m, node_chart_5m;
