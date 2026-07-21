# Validation Report R22.7

Release: `50.5.9-prod-r22.11-vm-slot-boundary-coverage-hotfix`

## Scope validated

- VM Consumption render SQL reads only `vm_consumption_hourly` and `vm_consumption_daily`.
- The VM render SQL contains no `FROM node_stats`, `FROM usage`, `rx_delta` or `tx_delta` branch.
- The selected period maps to a fixed number of hourly buckets and includes the live current-hour rollup.
- Complete local days use daily rows; partial local days use hourly rows without overlapping ranges.
- Guest RX/TX direction normalization is unchanged.
- Node and Node Group Consumption architecture is unchanged.
- Agent, ingest, schema, retention, API, Configuration Backup/Restore and Nuclear behavior are unchanged.

## Automated results

- Focused R22.7, R21, R20 and v50.5.8 Consumption contracts: 33 passed.
- Consumption plus Node Groups runtime group: 47 passed.
- Release/RBAC/Backup/Nuclear/installer/source compatibility group: 131 passed.
- Runtime source-cleanliness follow-up: 31 passed.
- Installer fresh/update flow: PASS.
- Installer manifest traversal validation: PASS.
- Python compileall: PASS.
- Dynamic source-window checks for 1H, 2H, 6H, 12H, 24H, 2D and 7D: PASS.

## Dynamic query-shape checks

- 1H through 24H produce one hourly source branch.
- 2D and 7D use hourly prefixes/suffixes plus daily rows for full local days.
- Every tested range selected exactly the requested number of hourly bucket slots.
- No tested VM source SQL referenced raw VM/NIC relations.

## Preflight runner note

The canonical preflight passed release identity, source checksum coverage, shell/Python/YAML syntax, modular runtime, source cleanliness and contracts through v50.5.6. The single long preflight invocation was stopped by the external execution limit while legacy tests were being isolated. The remaining release-critical groups were executed separately and passed, including FIFO queue, Node Groups, R22.5 Backup/Nuclear, R22.7 Consumption and installer flows.

## Environment limitation

Live `EXPLAIN (ANALYZE, BUFFERS)` and destructive PostgreSQL/TimescaleDB integration were not run because no disposable `BW_TEST_DATABASE_URL` was provided. Static SQL contracts, runtime import tests and installer contracts were run locally.
