\set ON_ERROR_STOP on

-- 50.5.8-r4 additive schema only.
-- Consumption is rolled up from the established 5-minute /push transaction.
-- Inventory expiry uses small ordered SKIP LOCKED batches from a systemd timer.

CREATE TABLE IF NOT EXISTS node_consumption_hourly (
    hour_start BIGINT NOT NULL,
    node TEXT NOT NULL,
    physical_public_rx_bytes BIGINT NOT NULL DEFAULT 0,
    physical_public_tx_bytes BIGINT NOT NULL DEFAULT 0,
    physical_private_rx_bytes BIGINT NOT NULL DEFAULT 0,
    physical_private_tx_bytes BIGINT NOT NULL DEFAULT 0,
    coverage_seconds BIGINT NOT NULL DEFAULT 0,
    sample_count BIGINT NOT NULL DEFAULT 0,
    last_push BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (hour_start, node)
);

CREATE TABLE IF NOT EXISTS node_consumption_daily (
    day_start BIGINT NOT NULL,
    node TEXT NOT NULL,
    physical_public_rx_bytes BIGINT NOT NULL DEFAULT 0,
    physical_public_tx_bytes BIGINT NOT NULL DEFAULT 0,
    physical_private_rx_bytes BIGINT NOT NULL DEFAULT 0,
    physical_private_tx_bytes BIGINT NOT NULL DEFAULT 0,
    coverage_seconds BIGINT NOT NULL DEFAULT 0,
    sample_count BIGINT NOT NULL DEFAULT 0,
    last_push BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (day_start, node)
);

CREATE INDEX IF NOT EXISTS idx_node_consumption_hourly_node_time
    ON node_consumption_hourly (node, hour_start);
CREATE INDEX IF NOT EXISTS idx_node_consumption_daily_node_time
    ON node_consumption_daily (node, day_start);

-- Keep cleanup target discovery narrow. Healthy active rows are read by the
-- partial index but are only updated after crossing a configured cutoff.
CREATE INDEX IF NOT EXISTS idx_vm_inventory_cleanup_stale
    ON vm_inventory (last_seen, node, vm_uuid)
    WHERE status = 'active' AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_vm_inventory_cleanup_delete
    ON vm_inventory (last_seen, node, vm_uuid)
    WHERE status IN ('active', 'stale', 'missing') AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_node_inventory_cleanup_delete
    ON node_inventory (last_push, node)
    WHERE status IN ('active', 'stale', 'missing') AND deleted_at IS NULL;
