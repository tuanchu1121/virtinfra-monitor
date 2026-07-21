# VirtInfra Monitor R22 Validation Report

## Release

`50.5.9-prod-r22-consumption-hardening-global-sort`

## Scope delivered

R22 was implemented as a hardening release, not an application rewrite:

- canonical Consumption business runtime in Layer 44
- Layer 45 reduced to a compatibility marker with no business functions or routes
- Node raw-retention edge clipping with coverage calculated against the full requested range
- VM Consumption cache isolation by Group, Node, search, sort, pagination and visibility generation
- PostgreSQL global Top VM sorting over existing current tables, before `LIMIT`
- deterministic `NULLS LAST` and Node/VM UUID tie ordering
- future payload timestamp guard
- protection against missing VM metric sections and out-of-order current-state rewinds
- persistent backfill status through the existing Maintenance/System status path
- PostgreSQL plus installed-source/config snapshots before update
- live PostgreSQL integration and 300-Node/60,000-VM benchmark tooling

## Explicitly not introduced

- `vm_top_current`
- Top VM dual-write
- a second current-state source
- new Agent payload fields or cadence
- new Maintenance job or screen
- changed CPU, RAM, RX, TX, PPS, Disk I/O or Storage formulas
- changed public/private bridge classification
- a new SQL migration

## Validation completed in the build environment

### Release and source integrity

- `SHA256SUMS`: exact coverage for 752 source files
- Python syntax: PASS
- shell syntax: PASS
- YAML syntax: PASS
- modular runtime architecture: PASS
- runtime source-cleanliness contract: PASS
- duplicate route registration: none detected
- runtime route count: 83

### Functional and regression validation

- isolated PostgreSQL-native preflight with `--skip-live`: PASS
- pytest collection: 177 tests
- all 177 collected non-live tests passed when executed in isolated files/processes
- PostgreSQL-only Node Group module: skipped cleanly because no disposable DSN was supplied
- 11 standalone source/installer/UI/Agent contract programs: PASS
- Node Group runtime validation: all 27 named checks PASS, route count 83
- RBAC runtime validation: all 30 named checks PASS
- installer flow: PASS
- installer manifest path traversal protection: PASS
- Windows/GitHub Desktop bootstrap compatibility: PASS
- complete release audit: PASS

### R22-specific execution checks

`tests/test_r22_hardening.py` executed the real Top VM SQL path against 1,503 VM rows and verified:

- the highest-RAM VM ranks first even when its network usage is nearly zero
- the largest-disk VM ranks first even when its network usage is nearly zero
- hidden/inactive Nodes do not appear
- Group filtering occurs before sorting
- ordering is performed over the complete eligible set before `LIMIT`
- no `vm_top_current`, dual-write or Top VM Maintenance job was introduced
- benchmark tooling covers every existing Top VM sort key

### Runtime permission checks

- viewer remains read-only
- admin remains limited by the existing role contract
- super admin protections remain active
- admin cannot create or modify super-admin authority improperly
- password/role changes revoke sessions correctly
- Maintenance and destructive-operation boundaries remain unchanged

## Validation requiring disposable PostgreSQL 17 + TimescaleDB

The build environment did not provide a PostgreSQL server, container runtime or disposable `BW_TEST_DATABASE_URL`. Therefore the following are included but honestly reported as **not executed**:

- migrations `001` through `015` against a real PostgreSQL/TimescaleDB instance
- duplicate/retry/concurrent duplicate constraints against real transactions
- forced partial-ingest rollback against real PostgreSQL
- missing VM payload and out-of-order current-state integration
- future timestamp rejection through Flask plus PostgreSQL
- VM movement history from Node A to Node B on real rollup tables
- Node/Group/Summary `EXPLAIN (ANALYZE, BUFFERS, WAL)`
- synthetic 300-Node/60,000-VM global Top VM benchmark
- R20/R21 upgrade and database rollback rehearsal on a cloned production-sized database

The PostgreSQL modules use module-level `pytest.skip(..., allow_module_level=True)` when the disposable DSN is absent. A skip is not represented as a pass.

## Known limitations

- Local compatibility-database execution proves ranking semantics and regression behavior, but cannot prove production PostgreSQL latency, WAL volume or lock behavior.
- Existing Top VM page-size limits and UI remain unchanged. R22 fixes ranking correctness, not page design.
- Backfill gap status reports missing retained coverage; it does not manufacture data already removed by retention.
- Production deployment remains blocked until the included live integration and benchmark commands pass on representative PostgreSQL/TimescaleDB hardware.
