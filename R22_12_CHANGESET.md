# R22.12 Change Set

Release: `50.5.9-prod-r22.12.2-preflight-contract-hotfix`

## Production problem

VM Consumption still executed the complete hourly/daily aggregation, visibility joins, `COUNT(*) OVER()`, global sort and pagination inside the web request. On large installations the first request could exceed PostgreSQL `statement_timeout` even though the source no longer read raw history.

## Definitive read-path change

- Added `vm_consumption_snapshot_batches` and `vm_consumption_snapshot_rows` as PostgreSQL `UNLOGGED` derived cache tables.
- Added runtime Layer 48 and `app/vm_consumption_snapshot.py`.
- Added a systemd oneshot service and five-minute timer.
- The worker aggregates canonical `vm_consumption_hourly`, `vm_consumption_daily` and packed five-minute slots once per period/generation.
- VM web requests only select a ready generation, apply current scope/visibility/search/coverage, execute a separate compact count, sort, limit and offset.
- Removed rollup CTE construction and `COUNT(*) OVER()` from the effective VM request function.
- Missing cache never falls back to the expensive legacy request pipeline. It queues an advisory-locked asynchronous rebuild.

## Production safeguards

- `24H` builds first; each period commits independently.
- Cross-process PostgreSQL advisory locks prevent duplicate builders.
- A settled-boundary delay reduces incomplete generations caused by normal Agent delivery jitter.
- Install/update queues warm-up asynchronously instead of blocking on seven builds.
- Keeps four generations per period by default.
- Full database backups exclude derived snapshot data; restore queues a fresh rebuild.
- Clear Monitoring, Nuclear Reset and Node purge remove derived rows.

## Unchanged

- UI, routes and API payloads.
- Agent and ingestion cadence.
- RX/TX direction and formulas.
- Canonical hourly/daily rollup schema and packed slots.
- Rolling-window semantics.
- Node, Node Group and Summary pipelines.
- Retention, Abuse, Storage, RBAC and maintenance queue behavior.
