# VirtInfra Monitor R21 Validation Report

**Release:** `50.5.9-prod-r21-consumption-ingest-preaggregation-hotfix`  
**Validation date:** 2026-07-21  
**Scope:** Consumption ingest, database migration, Node/Node Group/Summary read boundary, VM pipeline isolation, Maintenance, RBAC, route and packaging contracts.

## Result

R21 implements ingest-time Consumption pre-aggregation without changing Dashboard snapshots, Agent cadence or unrelated monitoring behavior.

- Every accepted normal five-minute `/push` incrementally UPSERTs canonical VM hourly/daily rollups and compact Node five-minute/hourly/daily rollups.
- Node, Node Group and Consumption Summary render from one cached Node dataset.
- Render SQL reads only `node_consumption_5m`, `node_consumption_hourly`, `node_consumption_daily` and low-cardinality Node metadata.
- VM history remains a separate daily/hourly/raw-edge pipeline and is not invoked by Node or Group tabs.
- No Flask route was added or removed. Runtime route count remains **83**.

## Ingest contract

Canonical active rollups:

```text
vm_consumption_hourly
vm_consumption_daily
node_consumption_5m
node_consumption_hourly
node_consumption_daily
```

The Node hourly/daily rows contain both Physical and All-VM totals, separate coverage/sample counters, VM reporting count and latest push. The writes use:

```sql
INSERT ... ON CONFLICT (...) DO UPDATE
```

The exact retry receipt `(node, push_time)` is committed in the same accepted push transaction, so an identical HTTP retry cannot add deltas twice.

## Hybrid Node query

For an unaligned 24-hour range the production SQL builder emits:

```text
first incomplete hour  -> node_consumption_5m
complete middle hours  -> node_consumption_hourly
final incomplete hour  -> node_consumption_5m
```

Complete days use `node_consumption_daily` for longer ranges. The same Node dataset is reused for Node rows, Node Group rows, Summary, Physical totals, All-VM totals and observed differences. Cache TTL is bounded to **5–15 seconds**, default **10 seconds**.

## PostgreSQL 17 EXPLAIN ANALYZE proof

Validator:

```text
tools/validate-consumption-query-plans.py
```

Recorded plan:

```text
EXPLAIN_ANALYZE_R21.json
```

Disposable PostgreSQL 17 test, 350 seeded Nodes, unaligned 24-hour range:

```text
Planning time:   2.455 ms
Execution time: 10.334 ms
Hourly rows:     8,050
First raw edge:  2,450 compact Node rows
Final raw edge:  1,750 compact Node rows
Forbidden per-VM relations seen: none
SQL contains vm_uuid: false
```

Relations observed by the plan:

```text
node_consumption_5m
node_consumption_hourly
node_inventory
node_groups
node_group_memberships
node_bridge_addresses_latest
node_physical_net_latest
```

The plan did **not** read:

```text
node_stats
vm_consumption_hourly
vm_consumption_daily
node_vm_consumption_hourly
node_vm_consumption_daily
```

## Migration validation

Migration `015_consumption_ingest_preaggregation.sql` was applied twice to a disposable PostgreSQL 17 database.

Verified final relation types:

```text
vm_consumption_hourly   table
vm_consumption_daily    table
node_consumption_5m     table
bandwidth_hourly        compatibility view
bandwidth_daily         compatibility view
```

The migration marker remained single and idempotent:

```text
015_consumption_ingest_preaggregation
```

A live test also exposed and fixed a bootstrap issue: PostgreSQL transactions must not use an exception from a missing canonical table as relation detection. Bootstrap now creates canonical VM tables safely before indexing; migration 015 later merges any legacy table and installs compatibility views.

## Regression validation

- Pytest collection: **173 tests**.
- The monolithic suite reached **100% green test execution**, but the historical test harness can retain a thread/connection after completion and not exit cleanly in some runs.
- Changed and load-bearing R19–R21/runtime/documentation tests were rerun in independent processes: **34 passed**.
- R21 Consumption tests: **11 passed**.
- RBAC runtime matrix: **30/30 passed**.
- Node Groups runtime matrix: all checks passed; route count **83**.
- Installer fresh/update split: passed.
- Installer manifest traversal protection: passed.
- Windows GitHub Desktop layout: passed.
- Python syntax, shell syntax and YAML validation: passed.
- Live Node Groups PostgreSQL integration: **2 passed**.

The full legacy PostgreSQL integration suite was not completed against the local PostgreSQL server because that server does not have the TimescaleDB extension installed. The R21 migration itself and the required real PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` proof were completed successfully on disposable databases. Production data was not used for validation.

## Maintenance behavior

- No separate Consumption clear action is exposed.
- `Clear All Monitoring Data` includes raw data and all canonical Consumption rollups.
- Node/VM inventory, Node Groups, flags, hidden state, users and settings remain preserved.
- Routine cleanup keeps compact Node five-minute edges for 48 hours and visible hourly/daily history for seven days.
- Maintenance row counts use PostgreSQL planner estimates rather than exact `COUNT(*)` scans on high-cardinality VM rollups.

## Compatibility boundaries

- Dashboard 5m/10m/15m snapshot behavior is unchanged.
- Agent still samples every 15 seconds and sends one durable payload every 300 seconds.
- `/push/bandwidth-consumption` remains retired with HTTP 410.
- `node_bandwidth_consumption_2h` and R20 Node-VM tables may remain as dormant upgrade compatibility objects, but the R21 Node/Group/Summary read path explicitly rejects them.
- No CPU, RAM, network, PPS, disk, Abuse, Storage I/O, Queue or RBAC formula was changed.

## Conclusion

R21 meets the requested complexity boundary:

```text
Node Consumption cost = Node × time buckets
```

rather than:

```text
VM × NIC × samples
```

The 24-hour Node middle range scales at approximately 350 Nodes × 23 complete hours in the measured unaligned example, while the two range edges read only compact Node-level five-minute rows.
