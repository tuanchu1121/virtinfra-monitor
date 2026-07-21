# Consumption architecture

**Release:** `50.5.9-prod-r22.8-vm-consumption-exact-window-sort-alignment`

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

R22.8 keeps VM Consumption separate from Node/Group/Summary and uses the exact bounded hybrid planner from the 50.5.9 Consumption path:

- complete local days from `vm_consumption_daily`;
- complete hours outside those days from `vm_consumption_hourly`;
- only the two incomplete-hour edges from bounded `node_stats` rows;
- no full-range VM/NIC raw scan.

The raw edge predicates constrain both `bucket` and `last_push`. `bucket` gives TimescaleDB a partition-pruning key while `last_push` preserves the original accepted-sample time semantics. A one-hour range can therefore be entirely raw when both boundaries fall inside incomplete hours, but a multi-day range still reads raw only at its two short edges.

Node and Node Group scope is combined and pushed into all daily, hourly and raw branches before aggregation. An explicit Node selector cannot bypass the selected Group. All VM merges historical active-Node segments with the same `vm_uuid`; Group views merge segments inside the selected current scope. An explicit Node filter remains Node-attributed and includes only traffic generated on that Node.

Coverage is derived from the weakest configured public/private bridge rather than the strongest one. Removed current interfaces do not erase matching historical bridge traffic. Guest direction remains guest RX = host tap TX and guest TX = host tap RX.

Equivalent request timestamps are normalized by the existing R22.7 cache interval, so the bounded query cache can be reused. The Node selector lists only active Nodes inside the selected Group.

All displayed columns are sortable over the complete filtered result before `LIMIT/OFFSET`: VM UUID, Node, Public RX, Public TX, Public Total, Private RX, Private TX, Private Total, Coverage and Latest Sample. Deterministic Node/UUID tie-breakers keep pagination stable. The VM pipeline runs only when the VM tab is opened; Node and Group tabs do not call it.

## Request reuse and cache

One Node dataset is computed for a normalized range and reused for:

- Physical totals;
- All-VM totals;
- Node rows;
- Node Group rows;
- Summary;
- observed differences.

A short in-process cache is bounded to 5–15 seconds, default 10 seconds. Destructive actions and retention cleanup clear the cache generation.

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

The validator fails if the plan scans a per-VM relation or if the SQL contains `vm_uuid`. `EXPLAIN_ANALYZE_R21.json` remains the historical R21 baseline; R22 live-plan output is generated separately with `--output`.
