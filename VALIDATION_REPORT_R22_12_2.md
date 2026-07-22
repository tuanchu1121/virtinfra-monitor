# Validation Report R22.12.2

Release: `50.5.9-prod-r22.12.2-preflight-contract-hotfix`

## Result

The remaining legacy Node Groups migration-contract failure was removed without
changing production runtime or migration 019.

## Validation completed

- Node Groups static/contract tests: 12 passed; two runtime-only tests were
  deselected in the build container because Flask is unavailable there.
- R22.12.1 contract-equivalence and shared-snapshot tests: 11 passed.
- Installer fresh/update flow: passed.
- Installer manifest-path validation: passed.
- Python compile and shell syntax: passed.

## Runtime impact

None. This release changes legacy preflight/test metadata and release identity
only. It does not change runtime queries, PostgreSQL migration 019, Agent, UI or
API behavior.
