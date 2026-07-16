# PostgreSQL and TimescaleDB design

## One source of truth

All persistent runtime data is in one PostgreSQL database. TimescaleDB is loaded as a PostgreSQL extension. Redis, when enabled, is only a reconstructable page cache.

## Current and history paths

Current-state pages use bounded tables such as:

```text
node_inventory
vm_inventory
vm_current_fast
vm_latest_metrics
vm_perf_latest
vm_disk_current
node_storage_current
vm_abuse_state
```

Dashboard, Top VM, Current Abuse and Storage pages do not need to scan all historical samples.

Time-series/history tables include:

```text
node_stats
vm_perf_stats
node_host_stats
node_filesystem_stats
node_physical_net_stats
agent_health_stats
node_push_snapshots
bandwidth_hourly
bandwidth_daily
node_bandwidth_consumption_2h
```

Fresh installation converts supported history tables into Timescale hypertables with integer Unix-time partitioning. BRIN indexes support time pruning while existing B-tree indexes support exact Node/UUID lookups.

## Ingest behavior

One Agent payload represents a real 300-second window. The Monitor transaction:

1. validates the push token;
2. de-duplicates `node + push_time`;
3. updates inventory and current projections;
4. writes synchronized history rows;
5. updates storage/disk state;
6. evaluates Abuse state/events;
7. commits once.

## Retention

The application retention implementation remains authoritative:

- 0–48 hours: every real 5-minute push;
- 48 hours–7 days: one real synchronized snapshot/hour;
- older than 7 days: bounded deletion;
- current and control data are preserved.

## Connection pooling

`app/bw_pg.py` uses psycopg 3 and `psycopg_pool.ConnectionPool`. Configure in `/etc/default/bw-monitor`:

```text
BW_DB_POOL_MIN
BW_DB_POOL_MAX
BW_DB_POOL_TIMEOUT
BW_DB_STATEMENT_TIMEOUT_MS
BW_DB_LOCK_TIMEOUT_MS
BW_DB_IDLE_TX_TIMEOUT_MS
```

## PostgreSQL tuning

The installer chooses conservative host-RAM-based values for shared buffers, effective cache size, maintenance memory, work memory, workers and Timescale background workers. The Docker Compose service uses:

- WAL compression;
- long, smooth checkpoints;
- SSD-oriented random-page cost and I/O concurrency;
- JIT disabled for predictable dashboard queries;
- loopback-only database port;
- bounded container logs.

Measure production behavior before changing values.

## Inspect

```bash
virtinfra-monitorctl db-check
virtinfra-monitorctl psql
```

Useful SQL:

```sql
SELECT pg_size_pretty(pg_database_size(current_database()));
SELECT * FROM timescaledb_information.hypertables;
SELECT relname, n_live_tup, n_dead_tup
FROM pg_stat_user_tables
ORDER BY n_live_tup DESC;
```
## Node-only Bandwidth Consumption table

`node_bandwidth_consumption_2h` stores one row per node and completed local 2-hour bucket. The row contains eight counters only: Physical Public/Private RX/TX and aggregate VM Public/Private RX/TX, plus coverage and receive metadata. It does not store VM UUIDs.

At 200 nodes the normal ingest rate is 2,400 rows/day and the strict 7-day working set is about 16,800 rows. The table is intentionally a normal PostgreSQL table rather than a hypertable because the bounded working set is tiny.

The primary key `(node, bucket_start)` makes Agent retries idempotent. `Reset ALL app data + queue` clears the table and advances `bandwidth_consumption_accept_after`, causing pre-reset retry buckets to be acknowledged and ignored.

