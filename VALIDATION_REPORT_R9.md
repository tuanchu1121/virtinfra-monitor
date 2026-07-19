# R9 validation report

Release: `50.5.9-prod-r9-safe-runtime-history-prune`

## Equivalence checks

The cleaned source is compared with the input release through normalized Python bytecode that excludes filenames and line-number metadata while retaining opcodes, constants, names, arguments, closures and nested code objects.

Validated unchanged:

- Module-global live callables.
- Flask view-function bindings.
- Flask route map.
- Before-request, after-request, teardown and URL-processing hooks.
- Error-handler bindings.
- Complete live runtime code-object multiset.
- Agent SHA-256.
- PostgreSQL migration-tree SHA-256.
- Static-asset tree SHA-256.

## Regression result

- Full pytest: **126 passed, 1 skipped**.
- The skipped case is the disposable live PostgreSQL integration because `BW_TEST_DATABASE_URL` was not supplied.
- All non-live preflight sections passed, including ingest, selected snapshots, maintenance, safe FIFO queue, Storage V2, multi-NIC, Consumption, themes, UI contracts and Node Groups.
- Installer staging, manifest traversal rejection and Windows/GitHub Desktop compatibility passed.
- `SHA256SUMS` has exact coverage for the canonical source tree.

## Regression coverage

The release runs:

- Python compilation.
- Shell syntax validation.
- Full pytest regression.
- Source contract scripts.
- Node Groups runtime and UI contracts.
- Storage V2 and multi-NIC regression.
- Installer staging and manifest-path security.
- Windows/GitHub Desktop package validation.
- Exact SHA256SUMS coverage.

The live PostgreSQL integration test requires a disposable `BW_TEST_DATABASE_URL`; when it is not provided, that test is explicitly skipped rather than treated as a pass.

## Deployment position

The package is source-only. It does not deploy, restart services or mutate a production database during validation. Use a canary or staging instance, preserve the current source backup and follow `ROLLBACK_INSTRUCTIONS.md` for rollback.
