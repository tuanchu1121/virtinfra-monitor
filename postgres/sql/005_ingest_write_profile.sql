\set ON_ERROR_STOP on

-- Remove legacy metric-sort btrees that are rewritten on nearly every Agent
-- push. Primary keys, node/seen lookups, active-Abuse rank, default Storage
-- write-IOPS and allocated-capacity indexes remain intact.
DROP INDEX CONCURRENTLY IF EXISTS idx_v50_vm_current_total_pps;
DROP INDEX CONCURRENTLY IF EXISTS idx_v50_vm_current_total_mbps;
DROP INDEX CONCURRENTLY IF EXISTS idx_v50_vm_current_disk_read_iops;
DROP INDEX CONCURRENTLY IF EXISTS idx_v50_vm_current_disk_read;
DROP INDEX CONCURRENTLY IF EXISTS idx_v50_vm_current_disk_write;
DROP INDEX CONCURRENTLY IF EXISTS idx_v50_vm_current_disk_write_iops;
DROP INDEX CONCURRENTLY IF EXISTS idx_vm_current_fast_cpu_core;
DROP INDEX CONCURRENTLY IF EXISTS idx_vm_current_fast_cpu_full;
DROP INDEX CONCURRENTLY IF EXISTS idx_vm_current_fast_ram_rss;
DROP INDEX CONCURRENTLY IF EXISTS idx_vm_current_fast_ram_assigned;
DROP INDEX CONCURRENTLY IF EXISTS idx_vm_latest_cpu;
DROP INDEX CONCURRENTLY IF EXISTS idx_vm_latest_pps;

DROP INDEX CONCURRENTLY IF EXISTS idx_vm_abuse_policy_severity;
DROP INDEX CONCURRENTLY IF EXISTS idx_vm_abuse_policy_cpu;
DROP INDEX CONCURRENTLY IF EXISTS idx_vm_abuse_policy_disk_read;
DROP INDEX CONCURRENTLY IF EXISTS idx_vm_abuse_policy_disk_write;
DROP INDEX CONCURRENTLY IF EXISTS idx_vm_abuse_mbps_active;
DROP INDEX CONCURRENTLY IF EXISTS idx_vm_abuse_state_ram;

DROP INDEX CONCURRENTLY IF EXISTS idx_v48140_vmdisk_assigned;
DROP INDEX CONCURRENTLY IF EXISTS idx_v48140_vmdisk_ratio;
DROP INDEX CONCURRENTLY IF EXISTS idx_v48140_vmdisk_slots;
DROP INDEX CONCURRENTLY IF EXISTS idx_v48140_vmdisk_write;
DROP INDEX CONCURRENTLY IF EXISTS idx_v48140_vmdisk_read_iops;
DROP INDEX CONCURRENTLY IF EXISTS idx_v48140_vmdisk_read;
DROP INDEX CONCURRENTLY IF EXISTS idx_v48140_vmdisk_seen;

INSERT INTO bw_meta.schema_migrations(version, description)
VALUES ('005_ingest_write_profile', 'Drop high-churn low-value current metric sort indexes')
ON CONFLICT (version) DO UPDATE SET description=excluded.description;

ANALYZE vm_current_fast, vm_latest_metrics, vm_abuse_state,
        vm_disk_summary_current, vm_disk_current;
