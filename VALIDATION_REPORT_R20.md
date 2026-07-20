# VirtInfra Monitor R20 Validation Report

## Release

`50.5.9-prod-r20-consumption-node-vm-rollup-alignment-hotfix`

## Scope

R20 is an additive Consumption-only hotfix developed from the verified R19 GitHub root-ready source. It does not alter the Dashboard, Agent collection cadence, `/push` payload, CPU/RAM/network/PPS/disk formulas, Abuse, Storage I/O, Queue, RBAC or the existing Node Group administration flow.

The release adds compact hourly/daily totals of all VM traffic per Node and uses those totals to compare Physical Node traffic with VM traffic in the Node and Node Group Consumption views.

## Implemented changes

- Added `node_vm_consumption_hourly` and `node_vm_consumption_daily` through migration `014_node_vm_consumption_rollups.sql`.
- Merged one compact per-Node VM total from the already accepted native COPY stage in the same PostgreSQL transaction as the existing normal five-minute push.
- Preserved guest perspective: guest RX is host-tap TX, and guest TX is host-tap RX.
- Preserved raw/hourly/daily tiered queries for 1h through 7d ranges.
- Added Physical, All VM and observed difference columns to Consumption → Node.
- Rebuilt Consumption → Node Group with the same metric order.
- Added explicit fixed `colgroup` contracts: 18 columns for Node and 19 columns for Node Group.
- Retired the legacy two-hour ingestion writer with HTTP 410; no new route was added and the dormant table remains only for safe upgrades.
- Removed the rendered separate Clear Consumption form. Clear All Monitoring Data covers the new tables.
- Rebuilds compact Node VM totals after individual VM purge and deletes them after Node/all-VM purge.
- Added standalone recent backfill without importing the Flask application.

## Compatibility boundaries

- Flask route count remains **83**.
- Dashboard HTML/routes and 5m/10m/15m snapshot semantics are unchanged.
- Normal Agent `/push` remains the only active Consumption ingestion path.
- Existing per-VM `bandwidth_hourly` and `bandwidth_daily` tables remain authoritative for VM drill-down.
- Existing Physical `node_consumption_hourly` and `node_consumption_daily` tables remain authoritative for Physical Node traffic.
- Node Group visibility and hidden-state rules remain active in Consumption.

## Validation performed

- Runtime route/Node Group validation, including rendered table column-count checks.
- RBAC/session runtime matrix.
- Runtime manifest/hash/contiguity validation.
- Consumption R19/R20 regression tests.
- Native COPY ingest and direction contract tests.
- Node Group, maintenance, purge and Queue tests.
- UI/theme/layout regression tests.
- Installer/update flow and Windows GitHub Desktop layout tests.
- Python, shell and YAML syntax validation.
- SHA256 source-manifest verification and archive extraction verification.

Current source-tree validation results:

- **164 pytest cases passed** across isolated non-live suites.
- **10 executable contract scripts passed**.
- **RBAC/session runtime matrix: 30/30 passed**.
- **Node Groups/runtime/route matrix: passed; route count 83**.
- **2 live PostgreSQL integration modules skipped** because `BW_TEST_DATABASE_URL` was not set.

The repository historically keeps a process/thread open when every pytest file is launched in one monolithic process. Canonical validation therefore runs isolated suites/processes; all isolated suites completed successfully.

## Live integration boundary

The PostgreSQL integration suites require `BW_TEST_DATABASE_URL` pointing to a disposable PostgreSQL database. They are skipped when that variable is unavailable; they are not executed against a production database.
