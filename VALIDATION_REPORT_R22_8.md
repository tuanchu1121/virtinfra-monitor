# Validation Report R22.8

**Release:** `50.5.9-prod-r22.8-vm-consumption-exact-window-sort-alignment`

## Scope validated

- R22.7 remains the base runtime.
- Layer 46 is the final VM Consumption read/UI override.
- Agent, ingest, schema, retention and Node/Group/Summary pipelines are unchanged.
- Daily/hourly/raw-edge boundaries do not overlap.
- Raw edges use both `bucket` and `last_push` bounds.
- Combined Node and Group scope is applied before source aggregation.
- All-VM UUID segments are merged across active Nodes; Group scope remains current-scope attributed.
- Coverage uses the weakest configured bridge.
- Every displayed VM metric sorts before pagination.
- Query timestamps retain R22.7 cache normalization and the Node dropdown obeys Group scope.
- Runtime manifest line ranges and hashes are canonical.
- Release archive checksum and archive integrity are verified during packaging.

## Offline test status

The repository test files were run in three isolated groups to avoid an environment-specific monolithic pytest shutdown stall. On the final source, **219 tests passed and 3 PostgreSQL integration tests were skipped** because no disposable DSN was configured.

The R22.8 focused contract and generated-SQL parameter binding checks passed for 1H, 2H and 7D ranges, including All VM, Group, explicit Node and combined Node+Group scopes.

The monolithic `preflight.sh` wrapper repeatedly stopped returning output after many nested validation subprocesses in this container. The same remaining source contracts, installer flows, shell checks and canonical-tree checks passed when executed directly with hard timeouts. This report does not mislabel that runner behavior as a source PASS.

## Not claimed

No live `EXPLAIN (ANALYZE, BUFFERS)` or production-size PostgreSQL benchmark is claimed when `BW_TEST_DATABASE_URL` is not set. Production latency and WAL behavior must be observed during a controlled rollout.
