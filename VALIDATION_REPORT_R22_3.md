# Validation Report R22.3

Release: `50.5.9-prod-r22.4-preflight-contract-hotfix`

## Focused validation

- Python compileall: PASS
- R22.3 backup/queue regression tests: 5 PASS
- Canonical Consumption, queue, installer and R22 hardening focused set: 48 PASS
- Runtime manifest, route/static contract and source cleanliness focused set: PASS
- Existing `./database.dump` and `./database.list` manifest compatibility: PASS
- Parent traversal manifest rejection: PASS
- Consumption route contains no synchronous DELETE: PASS
- Consumption cleanup enqueues `retention` with `scope=consumption`: PASS

## Broader suite

The repository-wide run completed with 172 passed and 1 skipped. Remaining failures/errors were either unavailable-runtime dependencies (`flask`, `psycopg`) in the validation container or a pre-existing PostgreSQL SQL-tree hash contract that also fails on the unmodified R22.2 archive.

## Production requirement

Run the updater on a clone/backup first, then verify:

1. Consumption cleanup appears in Maintenance Queue and reaches DONE.
2. A manual backup produces a valid `SHA256SUMS`.
3. Nuclear reset preview and confirmation can verify the mandatory backup before any destructive phase.
