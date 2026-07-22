# R16 Validation Report

Release: `50.5.9-prod-r16-operations-node-flag-scope-hotfix`

## Scope

- Dashboard monitoring behavior and layout are unchanged except for a role-aware `Operations` navigation entry placed after `VM Abuse`.
- Viewer does not see Operations and direct administration access remains forbidden.
- Admin is the routine infrastructure operator. Super Admin retains destructive whole-system, API and security authority.
- Existing `/admin` URLs, forms, query parameters, queue actions and redirects are retained.
- Operations pages use one consistent hero and section navigation shell.
- Node Group flags decorate only visible Node identity links. They are never injected into VM UUIDs, 5m–7d ranges, Both/Public/Private selectors, metric labels or sort controls.
- The R15 maintenance Queue Boolean migration is retained unchanged.

## Protected behavior

- 83 Flask routes retained.
- Agent and PostgreSQL SQL trees unchanged after release-string normalization.
- Static CSS, SVG and flag assets unchanged.
- CPU, RAM, network, PPS, disk, Abuse, Consumption and retention formulas unchanged.
- Auto refresh remains 30 seconds.

## Validation results

- Full pytest: `144 passed, 1 skipped`.
- The skipped suite requires a disposable PostgreSQL DSN through `BW_TEST_DATABASE_URL`.
- Shell syntax: PASS.
- YAML syntax: PASS.
- Manifest exact coverage and fresh hashes: PASS.
- Installer fresh/update split: PASS.
- Installer manifest traversal rejection: PASS.
- Windows/GitHub Desktop copy mode: PASS.
- Node Groups runtime user-flow validation: PASS.
- Operations role matrix and Node flag scope regression: PASS.

The monolithic preflight reached the installer validation stage before the execution environment timeout. Every remaining installer, manifest, Windows-mode and documentation contract was then executed independently and passed.
