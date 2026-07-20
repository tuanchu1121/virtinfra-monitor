\set ON_ERROR_STOP on

-- R20 additive Node-level VM Consumption rollups.
-- One row per Node/hour or Node/day keeps 24h/7d Node and Node Group views
-- independent from the high-cardinality per-VM rollup tables.

CREATE TABLE IF NOT EXISTS node_vm_consumption_hourly (
    hour_start BIGINT NOT NULL,
    node TEXT NOT NULL,
    vm_public_rx_bytes BIGINT NOT NULL DEFAULT 0,
    vm_public_tx_bytes BIGINT NOT NULL DEFAULT 0,
    vm_private_rx_bytes BIGINT NOT NULL DEFAULT 0,
    vm_private_tx_bytes BIGINT NOT NULL DEFAULT 0,
    coverage_seconds BIGINT NOT NULL DEFAULT 0,
    sample_count BIGINT NOT NULL DEFAULT 0,
    vm_count BIGINT NOT NULL DEFAULT 0,
    last_push BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (hour_start, node)
);

CREATE TABLE IF NOT EXISTS node_vm_consumption_daily (
    day_start BIGINT NOT NULL,
    node TEXT NOT NULL,
    vm_public_rx_bytes BIGINT NOT NULL DEFAULT 0,
    vm_public_tx_bytes BIGINT NOT NULL DEFAULT 0,
    vm_private_rx_bytes BIGINT NOT NULL DEFAULT 0,
    vm_private_tx_bytes BIGINT NOT NULL DEFAULT 0,
    coverage_seconds BIGINT NOT NULL DEFAULT 0,
    sample_count BIGINT NOT NULL DEFAULT 0,
    vm_count BIGINT NOT NULL DEFAULT 0,
    last_push BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (day_start, node)
);

CREATE INDEX IF NOT EXISTS idx_node_vm_consumption_hourly_node_time
    ON node_vm_consumption_hourly (node, hour_start);
CREATE INDEX IF NOT EXISTS idx_node_vm_consumption_daily_node_time
    ON node_vm_consumption_daily (node, day_start);
