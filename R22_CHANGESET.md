# R22 Change Set

## Behavior fixed

- Consumption runtime no longer depends on Layer 45 overriding Layer 44.
- VM Consumption cache entries are isolated by Group, Node, search, coverage, sort, direction, page, size and visibility generation.
- Node/Group/Summary range planning no longer requests five-minute rows older than their retention boundary; coverage remains based on the complete requested interval.
- Top VM RAM and disk-capacity rankings are global across every eligible VM, not a network-selected 1,000-row candidate set.
- All existing Top VM sort keys use SQL ordering before `LIMIT`, with stable ties and missing values last.
- Missing VM metric sections preserve existing current VM state instead of clearing it.
- Older late-arriving samples cannot rewind current Node/VM/interface state.
- Excessively future-dated normal pushes are rejected.
- Consumption backfill status and gaps are persistent and visible through the existing status path.
- Update creates a source/config snapshot in addition to the PostgreSQL backup.

## Behavior intentionally unchanged

- UI layout and templates
- route paths, endpoint names and API contracts
- Agent payload and cadence
- CPU, RAM, RX, TX, PPS, disk and storage formulas
- public/private bridge classification
- Node/Group/Summary use of only Node rollups
- independent VM Consumption pipeline
- Dashboard, Abuse VM, Storage I/O, Node Health and VM detail behavior
- RBAC role model
- Maintenance Queue, purge, retention, backup, restore and nuclear-reset behavior
- database migrations `001` through `015`

## Principal implementation files

- `app/runtime_layers/44_consumption_node_vm_rollup.py`
- `app/runtime_layers/45_consumption_ingest_preaggregation.py`
- `app/runtime_layers/29_storage_integration.py`
- `app/node_groups.py`
- `app/consumption_rollup.py`
- `app/runtime_layers/10_ingest_push.py`
- `app/runtime_layers/37_native_copy_ingest.py`
- `deploy/postgres/provision-postgres-native.sh`

## Validation and tooling files

- `tests/test_r22_hardening.py`
- `tests/test_v50_postgres_integration.py`
- `tools/benchmark-r22-top-vm.py`
- `tools/validate-consumption-query-plans.py`
- `preflight.sh`
- `VALIDATION_REPORT_R22.md`
- `BENCHMARK_REPORT_R22.md`
- `QUERY_PLAN_REPORT_R22.md`
- `docs/R22_MIGRATION_ROLLBACK.md`
