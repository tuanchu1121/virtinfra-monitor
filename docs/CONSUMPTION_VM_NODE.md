# Consumption VM/Node

Release: `50.5.9-prod-r18-user-rbac-session-hardening-hotfix`

## Scope

This release changes the effective `/bandwidth-consumption` implementation, adds additive physical rollups, updates the Agent from v14 to v15, and moves inventory expiry out of web requests. Abuse, CPU/RAM/Disk formulas, Storage I/O, API authentication, queue logic, monitoring retention tiers, timezone behavior and the established five-minute `/push` payload remain unchanged.

The Monitor must be upgraded before Agent v15 is rolled out. Old Agents remain accepted during the transition through the legacy compatibility endpoint, but Agent v15 no longer creates or sends a separate two-hour Consumption payload.

## Data flow

Agent v15 continues to sample locally and sends one durable operational payload every five minutes. The Monitor derives Consumption from those accepted deltas in the same PostgreSQL transaction:

- VM traffic continues to populate `bandwidth_hourly` and `bandwidth_daily`;
- physical traffic populates `node_consumption_hourly` and `node_consumption_daily`;
- a duplicate `/push` cannot add the same rollup twice because `push_receipts` is checked in the same transaction;
- the old `node_bandwidth_consumption_2h` table remains a read-only fallback for history written before Agent v15 rollout.

The `2H` button remains a rolling display range. It is not an Agent delivery schedule.

## Overview cards

The page always shows four totals for the selected range:

- Physical Public: RX, TX, Total
- Physical Private: RX, TX, Total
- VM Public: RX, TX, Total
- VM Private: RX, TX, Total

Supported rolling ranges are `1H`, `2H`, `6H`, `12H`, `24H`, `2D` and `7D`; the default is `24H`. The application continues to use its existing fixed timezone and does not add a timezone selector.

Summary totals are cached for 60 seconds by range and explicit node scope. Search, Coverage filters, sorting and pagination affect only the table.

## Fast rolling queries

For VM history, complete days use `bandwidth_daily`, complete hours use `bandwidth_hourly`, and only the two incomplete hour edges read retained five-minute rows.

For physical history, complete hours use `node_consumption_hourly`; only incomplete hour edges read `node_physical_net_stats`. Older pre-rollout history may use non-overlapping legacy two-hour rows. This removes the previous full raw 24-hour scan.

## VM Consumption

Columns:

- VM / UUID with copy action
- Node / Node IP
- Public RX, TX, Total
- Private RX, TX, Total
- Coverage
- Latest Sample

Search supports VM name/identifier, UUID field, MAC, Node and Node IP. MAC is search-only and VM IP is not shown. The table defaults to Public Total descending and supports server-side sorting plus `100`, `200` or `500` rows per page.

Host tap direction is normalized for display:

- guest RX = host tap TX
- guest TX = host tap RX

No duplicate VM Consumption history table is created.

## Node Consumption

Columns:

- Node / Node IP
- Physical Public RX, TX, Total
- Physical Private RX, TX, Total
- Coverage
- Latest Sample

All physical NICs with the same configured role are aggregated. There are no fixed Card 1/Card 2 or Difference columns.

## Inventory cleanup and deadlock protection

`auto_cleanup_inventory()` is retained only as a compatibility no-op for old callers. Dashboard, Top VM, Node Health, Abuse, Admin and auto-refresh routes no longer run inventory UPDATE statements.

`bw-monitor-inventory-cleanup.timer` runs the real cleanup around minutes `02`, `12`, `22`, `32`, `42` and `52`, offset from normal five-minute push boundaries. The worker:

- changes active VMs older than three days to stale;
- changes active/stale/missing VMs older than fifteen days to deleted;
- changes nodes older than seven days to deleted;
- preserves manually hidden rows;
- processes ordered batches with `FOR UPDATE SKIP LOCKED`;
- uses one PostgreSQL advisory lock so cleanup jobs cannot overlap;
- retries deadlock SQLSTATE `40P01` with bounded jitter.

The `/push` route also retries the complete transaction up to three times for a residual PostgreSQL deadlock. Failed attempts are rolled back before retry.
