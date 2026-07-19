# VirtInfra Monitor 50.5.9 prod-r4 dead-code cleanup

## Scope and safety result

This release performs a conservative Level-1 cleanup only. Runtime behavior, route registration, HTTP contracts, rendered pages, database schema, SQL files, Agent code, retention, maintenance, queueing, reset logic, feature flags, timers, services, and dependencies remain unchanged.

The source baseline contained 56,920 physical lines across the original 157 files. The same file set contains 56,913 lines after cleanup, for a net removal of 7 physical lines. Eight dead symbols or import bindings were removed; one removal narrowed an existing import line and therefore did not reduce the physical line count.

`app/app.py` changed from 36,433 to 36,432 lines. Its function-body AST fingerprint is identical before and after cleanup.

## Files modified for cleanup

- `app/app.py`
- `app/bw_pg.py`
- `tests/test_v50_contract.py`
- `tests/test_v50_postgres_integration.py`
- `tools/storage-v2-status.py`
- `tools/validate-storage-v2.py`

## Dead symbols removed

- `app/app.py`: unused standard-library binding `sys`.
- `app/bw_pg.py`: unused standard-library binding `contextmanager`.
- `app/bw_pg.py`: unused private compiled pattern `_RE_QMARK`.
- `tests/test_v50_contract.py`: unused standard-library binding `re`.
- `tests/test_v50_postgres_integration.py`: unused standard-library binding `json`.
- `tools/storage-v2-status.py`: unused standard-library binding `sys`.
- `tools/validate-storage-v2.py`: unused standard-library binding `defaultdict`.
- `tools/validate-storage-v2.py`: unused standard-library binding `timezone`; the `datetime` import was retained.

Each symbol was checked through AST load analysis, repository-wide exact-name search, dynamic-reference inventory, and regression tests. None of these imports has a registration or import-time side effect.

## Release metadata changes

The package identity was advanced to `50.5.9-prod-r4-dead-code-cleanup`. Version gates, installer release metadata, preflight checks, and the minimum user-facing release labels were updated. Historical runtime payload version strings and earlier feature markers were intentionally retained so API and stored-event behavior do not change.

## Runtime baseline

- Entrypoint and service map: `audit/RUNTIME_MAP.txt`
- Route maps: `audit/before-routes.json` and `audit/after-routes.json`
- Runtime response contracts: `audit/before-runtime-contract.json` and `audit/after-runtime-contract.json`
- Duplicate function inventory: `audit/DUPLICATE_FUNCTIONS.md`
- Dynamic reference inventory: `audit/DYNAMIC_REFERENCES.txt`
- Best-effort call graph: `audit/CALL_GRAPH.tsv`
- Import graph: `audit/IMPORT_GRAPH.tsv`
- Database schema fingerprint: `audit/SCHEMA_FINGERPRINT.txt`
- Baseline metrics: `audit/BASELINE_METRICS.txt`

The before/after comparison is identical for:

- 75 Flask routes, endpoint names, and methods.
- Main-page HTTP status, content type, length, and deterministic HTML hash.
- API HTTP status, content type, response length, deterministic hash, and JSON shape.
- Function-body AST fingerprint for `app/app.py`.
- PostgreSQL SQL-tree fingerprint.

The deterministic response capture freezes wall-clock time and uses a read-only fake database adapter only to permit route registration and empty-state rendering. The live PostgreSQL integration suite remains available through `BW_TEST_DATABASE_URL` and was skipped because no disposable test DSN was supplied.

## Validation commands

```bash
python3 -m compileall -q app deploy tools tests

while IFS= read -r file; do
    bash -n "$file"
done < <(
    find . -type f -name '*.sh' -print0 |
    sort -z |
    xargs -0 -n1 printf '%s\n'
)

python3 -m pytest -q --disable-warnings
```

Additional checks compare runtime contracts, function duplicates, dynamic references, schema hashes, line endings, and the exact release manifest.

## Intentionally retained

The following areas were reviewed but not modified because removal could not be proven safe enough:

- All 123 duplicate function names in `app/app.py`.
- Every wrapper chain and alias capture.
- Decorated routes and all `app.view_functions` replacement chains.
- `page`, `db`, current-state refresh, retention, purge, ingestion, table rendering, charting, consumption, storage, abuse, authentication, CSRF, session-secret, and PostgreSQL pool code.
- Feature-flag branches and compatibility paths.
- Public constants that may be consumed by operational scripts or external imports.
- Local assignments whose values are read by nested closures.
- Agent source and every SQL migration file.

The cleanup deliberately favors retaining questionable code over deleting a runtime dependency.
