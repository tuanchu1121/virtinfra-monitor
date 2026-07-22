# R22.9 Validation Report

## Root-cause verification

R22.8 redefined the VM source, visible-inventory and VM row query functions. A normal unfiltered sort could execute a separate full visible-VM COUNT plus a second rollup aggregation/sort, while active Node Group EXISTS checks were injected into multiple CTE layers even when no Group was selected.

R22.9 is based on R22.7. Its final layer does not define `_v5058c_vm_rows`, `_v5058c_vm_source_sql`, `_v5058c_visible_vm_cte`, or a visible-VM count query. The R22.7 cached hourly/daily VM path remains authoritative.

## Validation results

- Python compileall: PASS
- Focused Consumption, Node Groups and modular runtime tests: 60 passed
- Route/RBAC/UI/maintenance/Backup/Nuclear/ingest compatibility tests: 100 passed
- Installer fresh/update flow: PASS
- Installer manifest path validation: PASS
- Runtime Node Group route and rendered Consumption validation: PASS
- Source SHA256 verification: PASS

## Scope

No schema, migration, agent, ingest, formula, API, retention, Backup/Restore, Nuclear, Top VM, Storage I/O, Abuse, authentication, or non-Consumption UI change.

No live production TimescaleDB DSN was available for `EXPLAIN ANALYZE`; production latency should still be confirmed after update.
