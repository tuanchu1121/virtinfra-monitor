# R8 runtime equivalence report

Release: `50.5.9-prod-r8-safe-dead-code-prune`

Compared directly against `50.5.9-prod-r7-modular-runtime-refactor` using the repository's SQLite DB-API test shim with background workers disabled.

## Exact before/after result

- Flask URL rules: **83 / 83 identical**.
- Endpoint names and HTTP methods: **identical**.
- Final runtime global callables: **920 / 920 identical**, including normalized source hashes, defaults and keyword defaults.
- Flask hook functions: **6 / 6 identical** across before-request, after-request and template-context registries.
- Static/UI assets: **byte-for-byte identical**.
- Agent source and PostgreSQL migrations: unchanged and protected by existing hash/contract tests.
- Ordered runtime layers: **44 / 44 retained in the same execution order**.

The comparison intentionally focuses on the final reachable runtime graph. Historical definitions removed by R8 were not part of that final graph.

## Audit fixed point

- Round 1: 22 safe implementations, 1,088 lines.
- Round 2: 4 newly exposed safe implementations, 120 lines.
- Round 3: zero safe implementations.
- Total: **26 implementations / 1,208 lines removed**.

The cleanup retained 158 old function objects still captured by routes, wrappers, closures or registries, plus 14 historical implementations observed executing during import. They were not removed.
