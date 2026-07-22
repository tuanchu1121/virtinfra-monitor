# R22.12 Validation Report

Release: `50.5.9-prod-r22.12-vm-consumption-shared-snapshot`

## Source verification performed

- Python compilation passed for the new runtime layer and worker.
- Bash syntax passed for provisioning, backup, restore and snapshot systemd integration.
- Focused VM snapshot, R22.11 boundary, runtime-manifest and source-cleanliness contracts passed.
- The preceding focused Consumption/ingest/runtime suite passed before final packaging; final artifact checks repeat the new snapshot and manifest contracts.

## Locked contracts

- Effective `_v5058c_vm_rows()` reads `vm_consumption_snapshot_rows` only for metrics.
- It contains no `_v5058c_vm_ctes`, `vm_consumption_hourly`, `vm_consumption_daily`, raw history or `COUNT(*) OVER()`.
- The background builder remains based on canonical hourly/daily rollups and packed five-minute slots.
- Snapshot tables are UNLOGGED and do not alter canonical rollup tables.
- Installer warm-up is asynchronous.
- Backup excludes derived snapshot table data and restore rewarms it.

## Not claimed

No live production-scale `EXPLAIN ANALYZE`, wall-clock benchmark, WAL measurement or 60,000-VM database run was available in this build environment. The release removes the known expensive pipeline from the web request by construction, but the background refresh duration and database resource envelope must be measured on production-like data after deployment.
