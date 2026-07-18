# VirtInfra Monitor 50.5.8 Low-I/O Upgrade

## Upgrade type

`50.6.0-prod-r2-node-groups-update-detection-fix` is an **in-place upgrade** from the existing PostgreSQL-native VirtInfra Monitor release. It is not a clean-install-only branch.

The package can also perform a fresh installation, but the intended production path is:

1. Back up the existing monitor and PostgreSQL database.
2. Upgrade the monitor first.
3. Verify plain JSON pushes from existing Agents.
4. Roll out Agent v15 gradually to enable gzip transport.

The upgrade preserves the existing database, users, settings, UI routes, API endpoints, payload fields, metric formulas, five-minute sampling boundaries, abuse logic, canonical VM behavior, maintenance queue and retention policy.

## What changes below the application surface

- The monitor accepts both plain JSON and gzip-compressed Agent request bodies.
- Agent v15 sends gzip level 1 when payloads exceed the configured threshold.
- Agent v15 retries once with plain JSON when an older monitor returns HTTP 400 or 415, so rollback remains possible.
- VM and node MAC search indexes move to write-on-change identity lookup tables.
- High-churn current-state indexes containing frequently updated columns are removed or replaced with stable-key indexes.
- Hot current tables receive fillfactor and per-table autovacuum settings intended to improve HOT update reuse.
- PostgreSQL maximum and minimum WAL sizing are configurable while the existing WAL compression and checkpoint smoothing remain enabled.

## What does not change

- Agent collection and push remain on the existing five-minute wall-clock boundaries.
- There is no push jitter, bucket waiting or asynchronous queue between the Agent and PostgreSQL.
- Dashboard, Top VM, Node Health, Selected Snapshot, VM detail, Abuse and Admin screens retain their current behavior.
- CPU, RAM, network, PPS, disk and bandwidth formulas are unchanged.
- Existing uncompressed Agents remain accepted.
- Existing API clients require no changes.

## Upgrade sequence

Run the normal backup before changing production:

```bash
virtinfra-monitorctl backup
```

Confirm the newest backup and checksum:

```bash
LATEST="$(find /var/backups/bw-monitor -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"
echo "$LATEST"
cd "$LATEST"
sha256sum -c SHA256SUMS
```

Deploy the monitor release first using the normal update path. Do not deploy Agent v15 before the monitor is accepting gzip requests.

After the monitor is healthy, roll out Agent v15 in controlled batches. Existing Agents can remain online during this process.

## Verification

Monitor service:

```bash
systemctl is-active bw-monitor.service
journalctl -u bw-monitor.service --since '-10 minutes' --no-pager | tail -200
```

Confirm recent pushes are successful and no gzip or SQL errors are present:

```bash
journalctl -u bw-monitor.service --since '-10 minutes' --no-pager \
  | grep -E 'POST /push|Content-Encoding|Traceback|psycopg| 500 ' || true
```

Verify low-I/O schema objects:

```sql
SELECT to_regclass('public.vm_nic_identity_lookup');
SELECT to_regclass('public.node_nic_identity_lookup');

SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename IN (
    'vm_iface_current',
    'vm_current_fast',
    'node_physical_net_latest',
    'vm_nic_identity_lookup',
    'node_nic_identity_lookup'
)
ORDER BY tablename, indexname;
```

Observe HOT update and dead-tuple behavior after several five-minute cycles:

```sql
SELECT
    relname,
    n_live_tup,
    n_dead_tup,
    n_tup_upd,
    n_tup_hot_upd,
    ROUND(100.0 * n_tup_hot_upd / NULLIF(n_tup_upd, 0), 2) AS hot_percent,
    last_autovacuum,
    autovacuum_count
FROM pg_stat_user_tables
WHERE relname IN (
    'vm_iface_current',
    'vm_current_fast',
    'node_current_fast',
    'node_physical_net_latest',
    'vm_disk_current'
)
ORDER BY relname;
```

## Rollback

The migration is additive for identity tables and non-destructive for metric data. Rolling back application code does not require dropping the new lookup tables.

Agent v15 automatically retries plain JSON after an HTTP 400 or 415 from an older monitor. This prevents a monitor rollback from stopping Agent pushes.

A rollback to older application code may recreate the previous high-churn indexes during startup. That restores the older performance profile but does not alter metric values or historical data.

Do not manually drop tables during rollback. Restore the prior application release and configuration, restart the monitor, then verify `/push` before taking any further database action.
