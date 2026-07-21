# R22.10 Validation Report

## Functional contracts

- Rolling 1H/2H/6H/12H/24H/2D/7D windows preserve the exact selected duration and end on a closed five-minute bucket.
- A rolling 1H query reads at most two hourly rows per VM+bridge and no raw relation.
- Longer windows use packed edge slots plus compact hourly/daily totals.
- No `vm_consumption_5m` table or new index is created.
- Packed slots are merged inside the existing hourly UPSERT, not by a second UPDATE.
- Mixed pre-upgrade/new hourly rows preserve exact packed values and proportionally estimate only the unpacked residual.
- Node/Group and VM time normalization uses the same five-minute boundary.

## Test results

- Python compileall: PASS
- Consumption, ingest, Node Groups and modular runtime group: 90 passed
- v50.5.4 through v50.5.9 compatibility/hardening group: 84 passed
- R13 through R22 maintenance/RBAC/Backup/Nuclear group: 56 passed
- Installer fresh/update flow: PASS
- Installer manifest-path validation: PASS
- Windows GitHub Desktop bootstrap validation: PASS
- Source SHA256 verification: PASS after final packaging
- Extracted release ZIP focused verification: PASS after final packaging

The repository-wide monolithic pytest run is not claimed because legacy background-process tests can keep the process alive after assertions finish. Relevant groups were executed in separate processes. The combined preflight reached the standalone-repository stage before the outer timeout; its remaining contracts and installer checks were then run directly and passed.

## Production limitations

No disposable production-scale PostgreSQL/TimescaleDB DSN was available, so `EXPLAIN (ANALYZE, BUFFERS)` and real WAL/heap growth were not measured. The release removes raw VM/NIC reads by construction, but production latency and storage growth must still be observed.

## Upgrade behavior

Migration 017 is additive and idempotent. Existing rows are not rewritten with array defaults and no automatic raw-history backfill is performed. Historical partial edges use a bounded proportional compatibility estimate until enough new five-minute slots have accumulated.
