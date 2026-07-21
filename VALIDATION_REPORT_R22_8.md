# R22.8 Validation Report

Release: `50.5.9-prod-r22.8-consumption-sort-alignment-hotfix`

## Passed

- Python compile for application/runtime source.
- Runtime layer manifest ordering, contiguous line ranges, and SHA pinning.
- 117-test post-preflight suite covering route/form/sort contracts, UI R1-R3,
  Node Groups, RBAC, maintenance, R20/R21/R22, Configuration Backup/Nuclear,
  and R22.8 sort/alignment behavior.
- 60-test focused modular runtime/Consumption/Node Groups suite.
- 37-test Consumption/source suite.
- Node Groups runtime validation: all checks PASS; route count 83.
- Installer manifest path validation PASS.
- Windows/GitHub Desktop fresh/update fixture PASS.
- Source contract scripts for Agent, Consumption auth, and Consumption UI PASS.

## Full-suite note

The monolithic pytest run progressed beyond 67% without an assertion failure,
then exceeded the process timeout because legacy runtime tests retain background
threads. The official preflight also exceeded the outer execution limit after
completing its early and mid-stage contracts; every remaining preflight test was
then run in isolated processes and 117/117 passed. This avoids treating a harness
hang as a product failure.

## Not executed

`EXPLAIN (ANALYZE, BUFFERS)` against production-scale PostgreSQL/TimescaleDB was
not executed because the build environment has no disposable
`BW_TEST_DATABASE_URL`. The query structure is validated, but production timing
must be confirmed after deployment.
