# R17 Validation Report

Release: `50.5.9-prod-r17-operations-single-shell-hotfix`

## Scope

- Fixes only the duplicated Operations presentation shell discovered after R16 deployment.
- Removes stacked legacy Admin hero/navigation blocks at the final render boundary.
- Inserts exactly one canonical Operations hero and one canonical Operations tab navigation.
- Keeps the retention policy strip and all page-specific content intact.
- Preserves Dashboard behavior, routes, forms, query parameters, Queue actions, redirects, RBAC, Node Group handling and Node-only icon scope.

## Validation results

- Full pytest: `145 passed, 1 skipped`.
- The skipped suite requires a disposable PostgreSQL DSN through `BW_TEST_DATABASE_URL`.
- Operations single-shell regression: PASS.
- Node flag scope regression: PASS.
- Python compile: PASS.
- Runtime layer hash manifest: PASS.

## Expected rendered structure

```text
Operations hero
Operations tabs
Retention policy strip, where applicable
Page content
```

There must be no second `CONTROL CENTER`, `Administration`, Operations hero or Operations tab block.
