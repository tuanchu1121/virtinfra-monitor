\set ON_ERROR_STOP on

-- R22.12: shared, request-independent VM Consumption aggregate snapshots.
-- UNLOGGED keeps refresh WAL low. A PostgreSQL restart may truncate these
-- cache tables; the dedicated timer rebuilds them without touching canonical
-- hourly/daily rollups.
CREATE UNLOGGED TABLE IF NOT EXISTS public.vm_consumption_snapshot_batches (
    period_key TEXT NOT NULL,
    window_start BIGINT NOT NULL,
    window_end BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'building',
    row_count BIGINT NOT NULL DEFAULT 0,
    started_at BIGINT NOT NULL,
    completed_at BIGINT,
    error_text TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (period_key, window_end),
    CHECK (status IN ('building','ready','failed'))
);

CREATE INDEX IF NOT EXISTS idx_vm_consumption_snapshot_batches_ready
    ON public.vm_consumption_snapshot_batches(period_key, status, window_end DESC);

CREATE UNLOGGED TABLE IF NOT EXISTS public.vm_consumption_snapshot_rows (
    period_key TEXT NOT NULL,
    window_start BIGINT NOT NULL,
    window_end BIGINT NOT NULL,
    node TEXT NOT NULL,
    vm_uuid TEXT NOT NULL,
    vm_name TEXT NOT NULL DEFAULT '',
    node_ip TEXT NOT NULL DEFAULT '',
    public_configured INTEGER NOT NULL DEFAULT 0,
    private_configured INTEGER NOT NULL DEFAULT 0,
    public_rx BIGINT NOT NULL DEFAULT 0,
    public_tx BIGINT NOT NULL DEFAULT 0,
    public_total BIGINT NOT NULL DEFAULT 0,
    private_rx BIGINT NOT NULL DEFAULT 0,
    private_tx BIGINT NOT NULL DEFAULT 0,
    private_total BIGINT NOT NULL DEFAULT 0,
    coverage_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
    latest_sample BIGINT NOT NULL DEFAULT 0,
    built_at BIGINT NOT NULL,
    PRIMARY KEY (period_key, window_end, node, vm_uuid)
);

-- The primary key supports snapshot selection and early selected-node pushdown.
-- Keep secondary indexes intentionally small. Sorting 60k aggregate rows is
-- cheaper than maintaining one index for every UI sort on every refresh.
CREATE INDEX IF NOT EXISTS idx_vm_consumption_snapshot_rows_uuid
    ON public.vm_consumption_snapshot_rows(period_key, window_end, vm_uuid);

CREATE INDEX IF NOT EXISTS idx_vm_consumption_snapshot_rows_coverage
    ON public.vm_consumption_snapshot_rows(period_key, window_end, coverage_percent, latest_sample);

COMMENT ON TABLE public.vm_consumption_snapshot_rows IS
    'Derived VM Consumption cache only. Canonical data remains vm_consumption_hourly/daily and packed 5-minute slots.';

INSERT INTO bw_meta.schema_migrations(version,description)
VALUES (
    '019_vm_consumption_shared_snapshot',
    'Build shared VM Consumption aggregate snapshots outside web requests'
)
ON CONFLICT(version) DO NOTHING;
