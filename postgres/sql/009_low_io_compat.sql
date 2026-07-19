\set ON_ERROR_STOP on

-- 50.5.8 low-I/O compatible profile.
-- This migration is additive for data and removes only secondary indexes whose
-- indexed values change on every 5-minute current-state update. Primary keys,
-- historical indexes, API contracts and metric tables are unchanged.

CREATE TABLE IF NOT EXISTS public.vm_nic_identity_lookup (
    node TEXT NOT NULL,
    vm_uuid TEXT NOT NULL,
    bridge TEXT NOT NULL,
    iface TEXT NOT NULL,
    mac TEXT NOT NULL DEFAULT '',
    first_seen BIGINT NOT NULL,
    changed_at BIGINT NOT NULL,
    PRIMARY KEY (node, vm_uuid, bridge, iface)
);

CREATE TABLE IF NOT EXISTS public.node_nic_identity_lookup (
    node TEXT NOT NULL,
    role TEXT NOT NULL,
    bridge TEXT NOT NULL DEFAULT '',
    iface TEXT NOT NULL DEFAULT '',
    mac TEXT NOT NULL DEFAULT '',
    first_seen BIGINT NOT NULL,
    changed_at BIGINT NOT NULL,
    PRIMARY KEY (node, role)
);

INSERT INTO public.vm_nic_identity_lookup(
    node,vm_uuid,bridge,iface,mac,first_seen,changed_at
)
SELECT node,vm_uuid,bridge,iface,mac,last_seen,last_seen
FROM public.vm_iface_current
WHERE COALESCE(mac,'')<>''
ON CONFLICT(node,vm_uuid,bridge,iface) DO UPDATE SET
    mac=excluded.mac,
    changed_at=excluded.changed_at
WHERE public.vm_nic_identity_lookup.mac IS DISTINCT FROM excluded.mac;

INSERT INTO public.node_nic_identity_lookup(
    node,role,bridge,iface,mac,first_seen,changed_at
)
SELECT node,role,bridge,iface,mac,last_seen,last_seen
FROM public.node_physical_net_latest
WHERE COALESCE(mac,'')<>''
ON CONFLICT(node,role) DO UPDATE SET
    bridge=excluded.bridge,
    iface=excluded.iface,
    mac=excluded.mac,
    changed_at=excluded.changed_at
WHERE (
    public.node_nic_identity_lookup.bridge,
    public.node_nic_identity_lookup.iface,
    public.node_nic_identity_lookup.mac
) IS DISTINCT FROM (
    excluded.bridge,excluded.iface,excluded.mac
);

-- Remove lookup indexes from hot metric rows. Search now uses the stable
-- identity lookup tables maintained only when identity changes.
DROP INDEX CONCURRENTLY IF EXISTS public.idx_vm_iface_current_mac;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_node_physical_net_latest_mac;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vm_nic_identity_lookup_mac
    ON public.vm_nic_identity_lookup(mac) WHERE mac<>'';
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_node_nic_identity_lookup_mac
    ON public.node_nic_identity_lookup(mac) WHERE mac<>'';

-- last_seen and live metric sort values change every push. Keeping them in
-- secondary indexes prevents HOT updates and multiplies WAL/index writes.
DROP INDEX CONCURRENTLY IF EXISTS public.idx_vm_latest_node_seen;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_node_physical_net_latest_seen;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_vm_current_fast_seen;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_vm_current_fast_node_seen;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_vm_iface_current_node_bridge;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_node_current_fast_seen;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vm_iface_current_node_bridge
    ON public.vm_iface_current(node,bridge);

DROP INDEX CONCURRENTLY IF EXISTS public.idx_vm_disk_current_seen;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_vm_disk_current_storage;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_node_storage_current_seen;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_node_storage_current_load;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_v48140_vmdisk_alloc;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_v48140_vmdisk_write_iops;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_v48140_mount_write_iops;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_v48140_mount_write;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_v48140_mount_util;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_v48140_mount_used;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_v48140_mount_seen;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_v48140_disk_role_seen_vm;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_v48140_storage_node_mount_seen;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vm_disk_current_mount
    ON public.vm_disk_current(role,mount,node,vm_uuid);

-- Current Abuse needs a fast active list, not a full-table index rewritten for
-- every non-abusing VM. Keep a partial index containing only active rows.
DROP INDEX CONCURRENTLY IF EXISTS public.idx_vm_abuse_active;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_vm_abuse_policy_revision;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_vm_abuse_progress;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vm_abuse_active
    ON public.vm_abuse_state(severity DESC,last_seen DESC,node,vm_uuid)
    WHERE is_abuse=1;

-- Reserve page space for HOT chains and make vacuum react to bounded current
-- tables before dead tuples accumulate. These settings do not rewrite tables
-- and do not change any value returned by the application.
ALTER TABLE IF EXISTS public.vm_current_fast SET (
    fillfactor=75,
    autovacuum_vacuum_scale_factor=0.02,
    autovacuum_vacuum_threshold=1000,
    autovacuum_analyze_scale_factor=0.05,
    autovacuum_analyze_threshold=1000
);
ALTER TABLE IF EXISTS public.vm_iface_current SET (
    fillfactor=75,
    autovacuum_vacuum_scale_factor=0.02,
    autovacuum_vacuum_threshold=2000,
    autovacuum_analyze_scale_factor=0.05,
    autovacuum_analyze_threshold=2000
);
ALTER TABLE IF EXISTS public.vm_latest_metrics SET (
    fillfactor=75,
    autovacuum_vacuum_scale_factor=0.02,
    autovacuum_vacuum_threshold=1000,
    autovacuum_analyze_scale_factor=0.05,
    autovacuum_analyze_threshold=1000
);
ALTER TABLE IF EXISTS public.vm_abuse_state SET (
    fillfactor=80,
    autovacuum_vacuum_scale_factor=0.02,
    autovacuum_vacuum_threshold=1000,
    autovacuum_analyze_scale_factor=0.05,
    autovacuum_analyze_threshold=1000
);
ALTER TABLE IF EXISTS public.vm_disk_current SET (
    fillfactor=75,
    autovacuum_vacuum_scale_factor=0.02,
    autovacuum_vacuum_threshold=2000,
    autovacuum_analyze_scale_factor=0.05,
    autovacuum_analyze_threshold=2000
);
ALTER TABLE IF EXISTS public.vm_disk_summary_current SET (
    fillfactor=75,
    autovacuum_vacuum_scale_factor=0.02,
    autovacuum_vacuum_threshold=1000,
    autovacuum_analyze_scale_factor=0.05,
    autovacuum_analyze_threshold=1000
);
ALTER TABLE IF EXISTS public.node_current_fast SET (fillfactor=80);
ALTER TABLE IF EXISTS public.node_physical_net_latest SET (fillfactor=80);
ALTER TABLE IF EXISTS public.node_storage_current SET (fillfactor=80);
ALTER TABLE IF EXISTS public.node_storage_mount_summary_current SET (fillfactor=80);

INSERT INTO bw_meta.schema_migrations(version, description)
VALUES (
    '009_low_io_compat',
    'Gzip-compatible ingest, write-on-change MAC lookup, HOT-friendly current tables and low-churn indexes'
)
ON CONFLICT (version) DO UPDATE SET description=excluded.description;

ANALYZE public.vm_current_fast,
        public.vm_iface_current,
        public.vm_latest_metrics,
        public.vm_abuse_state,
        public.vm_disk_current,
        public.vm_disk_summary_current,
        public.node_physical_net_latest,
        public.vm_nic_identity_lookup,
        public.node_nic_identity_lookup;
