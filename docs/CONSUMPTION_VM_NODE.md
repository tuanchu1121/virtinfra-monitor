# Consumption architecture

**Release:** `50.5.9-prod-r22.12.3-slim-current-only`

R21 introduced high-cardinality network aggregation from page render time to the accepted five-minute `/push` transaction. Dashboard snapshots, Agent cadence and all non-Consumption features remain unchanged.

## Active ingestion path

```text
Agent sample every 15 seconds
        |
        v
One durable /push every 300 seconds
        |
        +-- recent raw VM interface data
        +-- recent raw Physical interface data
        +-- vm_consumption_hourly / vm_consumption_daily
        +-- node_consumption_5m
        +-- node_consumption_hourly / node_consumption_daily
```

All rollups use incremental `INSERT ... ON CONFLICT ... DO UPDATE`. Exact HTTP retries are rejected by `push_receipts` before the same deltas can be added twice. Guest traffic direction remains normalized as guest RX = host tap TX and guest TX = host tap RX.

The retired Agent-side two-hour endpoint `/push/bandwidth-consumption` remains registered only for safe upgrades and returns HTTP 410. `node_bandwidth_consumption_2h` is dormant compatibility storage and is not part of the active read or write path.

## Node-level pipeline

The Node rollup rows contain both Physical and All-VM totals:

- Physical Public RX/TX
- Physical Private RX/TX
- All-VM Public RX/TX
- All-VM Private RX/TX
- separate Physical/VM coverage counters
- VM reporting count and latest ingestion

Node, Node Group and Consumption Summary may read only:

- `node_consumption_5m` for incomplete five-minute edges;
- `node_consumption_hourly` for complete hours;
- `node_consumption_daily` for complete days;
- low-cardinality Node inventory and Node Group metadata.

Their render SQL is guarded against `node_stats`, `vm_consumption_hourly`, `vm_consumption_daily`, legacy per-Node VM tables and `vm_uuid`. Group totals are computed from the already-fetched Node dataset, so opening Node Group does not launch a second database aggregation.

### Hybrid 24-hour example

For an unaligned range such as 15:23 yesterday through 15:23 today:

```text
15:23–16:00 yesterday  -> node_consumption_5m
16:00–15:00 today      -> node_consumption_hourly
15:00–15:23 today      -> node_consumption_5m
```

At 350 Nodes, the complete-hour portion reads roughly `350 × 23 = 8,050` rows instead of scaling with VM × NIC × sample count.

## VM pipeline

VM Consumption remains separate and never scans raw VM/NIC history while rendering. Each canonical `vm_consumption_hourly` row now carries:

- the existing full-hour RX/TX totals;
- twelve packed five-minute RX slots;
- twelve packed five-minute TX slots;
- a twelve-bit sample-presence mask.

A rolling request ends at the latest closed five-minute bucket. For example, a 24-hour request made at 19:32 reads the exact range 19:30 yesterday through 19:30 today:

```text
19:30–20:00 yesterday  -> packed slots in the first hourly row
20:00–19:00 today      -> compact hourly/daily totals
19:00–19:30 today      -> packed slots in the last hourly row
```

Only the two partial hour edges inspect array elements. Complete hours and days keep using the existing compact totals. There is no `vm_consumption_5m` table and no `node_stats`, `usage` or raw NIC query when the VM table is opened.

The slot arrays are updated inside the existing hourly `INSERT ... ON CONFLICT` statement, so row cardinality and statement count do not increase. Exact HTTP retries remain blocked by `push_receipts`. The wider hourly row does increase heap/WAL volume; operators should watch database growth after rollout.

Rows created before migration 017 do not contain packed slots. During the bounded warm-up period, only the still-unpacked residual of an edge hour is proportionally estimated. Exact five-minute edges replace that estimate as new pushes arrive. No production raw-history backfill runs automatically.

A dedicated `bw-monitor-vm-consumption-snapshot.service` now runs the VM aggregate pipeline outside Gunicorn. For each supported range and settled five-minute boundary it materializes one compact row per visible VM into `vm_consumption_snapshot_rows`. The tables are `UNLOGGED` because they are disposable derived cache; canonical data remains in the hourly/daily rollups and packed slots.

The default `24H` generation is built first, followed by `1H`, `2H`, `6H`, `12H`, `2D` and `7D`. Each range commits independently. PostgreSQL advisory transaction locks guarantee one builder per period across the timer, installer and any crash-recovery refresh.

The VM web request no longer calls `_v5058c_vm_ctes`. It performs only:

```text
select latest ready generation
        -> current Node/VM visibility and Group filter
        -> separate COUNT(*) over compact snapshot rows
        -> ORDER BY metric
        -> LIMIT / OFFSET
```

There is no `COUNT(*) OVER()`, no inventory join repeated inside a web-request rollup aggregation and no rebuild when sort or page changes. Search and coverage operate on roughly one row per VM. A missing UNLOGGED cache after an unclean PostgreSQL restart triggers an advisory-locked asynchronous rebuild instead of falling back to the legacy heavy request query.

## Request reuse and cache

One compact Node dataset is still computed for a normalized range and reused by Node, Group and Summary. VM sorting, paging, Group/Node scope and search reuse the shared PostgreSQL aggregate generation. The snapshot worker waits for a short settled-boundary delay so normal Agent delivery jitter is included before a generation is frozen.

## Observed difference

Observed difference is Physical minus All-VM traffic for the same range. It can include host traffic, protocol overhead or incomplete coverage and is not a billing value.

## Maintenance

There is no separate Clear Consumption action. `Clear All Monitoring Data` removes raw metrics and all Consumption rollups together while preserving Node/VM inventory, Node Groups, flags, hidden state, users and settings. Routine cleanup retains node-level five-minute edges for 48 hours and visible hourly/daily history for seven days.

The Maintenance card uses PostgreSQL planner row estimates instead of exact `COUNT(*)` scans on large per-VM rollups.

## Performance proof

`tools/validate-consumption-query-plans.py` loads the exact production SQL builder, seeds 350 Nodes in a disposable PostgreSQL database and executes:

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ...
```

The validator fails if the plan scans a per-VM relation or if the SQL contains `vm_uuid`. Live-plan output is generated on demand with `--output`; historical plan artifacts are not shipped in the production package.
