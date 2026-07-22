# R22.11 Validation Report

Release: `50.5.9-prod-r22.11-vm-slot-boundary-coverage-hotfix`

## Root cause

R22.10 treated the Agent push timestamp as the start of a five-minute interval. The Agent actually stamps the payload at collection time after calculating deltas from the previous committed payload. This shifted each packed slot one position to the right and moved exact-hour samples into the following hourly row. A complete rolling hour therefore exposed at most 11 of 12 masks.

## Fix

- Subtract one five-minute bucket before deriving `hour_start`, `day_start` and slot number.
- Use the same mapping in legacy and native COPY ingest paths.
- Use interval-end timestamps for the latest packed sample.
- Add `slot_5m_version`; old R22.10 arrays are ignored by exact reads and replaced lazily on the next write to that hourly row.
- Preserve old hourly totals and sample counts as the compatibility source during transition.
- Do not bulk-update historical rows and do not query raw VM/NIC history.

## Validation performed

- 80 focused Consumption, ingest, Node Groups, runtime and manifest tests passed.
- 101 RBAC, maintenance, Backup/Nuclear, UI and v50 compatibility tests passed.
- 144 remaining repository, Storage V2, documentation, theme, Node Groups, R13-R22 and slot-boundary tests passed in a combined follow-up run.
- Installer fresh/update split test passed.
- Installer manifest-path test passed.
- Node Groups runtime validation passed with 83 routes.
- RBAC runtime validation passed.
- Python compileall and shell syntax checks passed.

## Boundary cases locked by tests

- `19:30` maps to `19:25-19:30`, slot 5.
- `20:00` maps to `19:55-20:00`, slot 11 of hour 19.
- Midnight maps to the final slot of the previous local day.
- Existing R22.10 rows are not bulk-rewritten.

## Limitations

The monolithic preflight reached the standalone repository stage without assertion failures but exceeded the execution window; every remaining listed test was then run separately and passed. No production-size PostgreSQL/TimescaleDB DSN was available for `EXPLAIN ANALYZE`, WAL measurement or live migration timing. Migration 018 is metadata-only on supported PostgreSQL versions, but the short schema lock should still be applied during a normal update window.
