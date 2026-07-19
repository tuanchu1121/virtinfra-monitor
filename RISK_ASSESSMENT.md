# Risk assessment

## Low

- Removing unreferenced standard-library imports.
- Removing the unreferenced private `_RE_QMARK` pattern.
- Updating release metadata and version-gate tests without changing runtime payload versions.
- Adding audit reports used to prove behavioral equivalence.
- Excluding embedded ZIP/tar.gz rollback artifacts from the production manifest because Git ignores these files and raw GitHub installation cannot retrieve them.

Controls: AST reference analysis, repository-wide search, deterministic route/HTML/API comparison, function-body fingerprint comparison, unchanged SQL fingerprint, syntax checks, and the regression suite.

## Medium

None performed.

Candidates in this category were retained, including apparently unused public constants, local variables captured by nested functions, old compatibility helpers, and historical implementation blocks.

## High

None performed.

No SQL, schema, migration, ingestion, retention, maintenance, queue, Agent, authentication, session, CSRF, renderer, feature-flag, or service/timer behavior was changed.

## Không thực hiện vì không đủ bằng chứng

- Deleting any of the 123 duplicate function-name chains in `app/app.py`.
- Flattening `page()` or any other wrapper chain.
- Removing old implementations referenced through aliases, route registration, decorators, closures, callbacks, or dynamic lookup.
- Removing compatibility exports from `bw_pg.py`.
- Removing public constants solely because in-repository static analysis did not find a read.
- Removing feature-flag branches that are currently disabled.
- Rewriting queries, renderers, or helper functions for style or compactness.

These areas remain untouched because a false positive could alter production behavior or break rollback compatibility.
