\set ON_ERROR_STOP on

-- Lean current-state profile for ~20k+ VM deployments.
-- Keep lookup/filter indexes that are observed in hot paths. Global metric sort
-- indexes are intentionally omitted: bounded current tables are cheap to scan,
-- while maintaining one btree per changing metric multiplies every five-minute
-- write, WAL record and vacuum cycle.
CREATE INDEX IF NOT EXISTS idx_v50_vm_inventory_uuid_status
    ON vm_inventory (vm_uuid, status, last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_v50_node_inventory_status_push
    ON node_inventory (status, last_push DESC, node);
CREATE INDEX IF NOT EXISTS idx_v50_abuse_current_rank
    ON vm_abuse_state (is_abuse, severity DESC, last_seen DESC, node, vm_uuid);
CREATE INDEX IF NOT EXISTS idx_v50_storage_current_rank
    ON node_storage_current (last_seen DESC, write_iops DESC, write_bps DESC, node, mount);

-- BRIN stays tiny for append-ordered epoch columns and supports retention/range
-- scans without adding btree write amplification to every history sample.
CREATE INDEX IF NOT EXISTS idx_v50_usage_time_brin
    ON usage USING brin (time) WITH (pages_per_range=32);
CREATE INDEX IF NOT EXISTS idx_v50_node_stats_bucket_brin
    ON node_stats USING brin (bucket) WITH (pages_per_range=32);
CREATE INDEX IF NOT EXISTS idx_v50_vm_perf_time_brin
    ON vm_perf_stats USING brin (time) WITH (pages_per_range=32);
CREATE INDEX IF NOT EXISTS idx_v50_node_host_time_brin
    ON node_host_stats USING brin (time) WITH (pages_per_range=32);
CREATE INDEX IF NOT EXISTS idx_v50_node_fs_time_brin
    ON node_filesystem_stats USING brin (time) WITH (pages_per_range=32);
CREATE INDEX IF NOT EXISTS idx_v50_node_net_time_brin
    ON node_physical_net_stats USING brin (time) WITH (pages_per_range=32);
CREATE INDEX IF NOT EXISTS idx_v50_agent_health_time_brin
    ON agent_health_stats USING brin (time) WITH (pages_per_range=32);

INSERT INTO bw_meta.schema_migrations(version, description)
VALUES ('003_native_indexes', 'Lean current-state lookup indexes and compact BRIN history indexes')
ON CONFLICT (version) DO UPDATE SET description=excluded.description;

ANALYZE vm_current_fast, vm_abuse_state, vm_disk_current,
        node_storage_current, node_inventory, vm_inventory,
        usage, node_stats, vm_perf_stats, node_push_snapshots;
