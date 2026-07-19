# Files changed — r7

Implementation:

- `app/app.py` — one shared 30-second monitoring refresh timer and final release marker.
- `app/node_groups.py` — final runtime RBAC, visibility, Admin Node/VM renderers, Node Groups, Storage, Consumption, Abuse filters and route guards.

Release identity/install validation:

- `VERSION`, `CHANGELOG.md`, `README.md`, `START_HERE_VI.md`, `SOURCE_OF_TRUTH_VI.md`, `GITHUB_DESKTOP_VI.md`, `COMMANDS_A_TO_Z_VI.md`.
- `deploy/postgres/install-postgres-native.sh`, `preflight.sh`, `tools/test-installer-flow.sh`.
- Existing version-contract tests updated to the r7 release identity.

New validation and operations documents:

- `tests/test_v5059_r7_production_hotfix.py`.
- `RUNTIME_MAPPING_R7.md`, `RELEASE_NOTES_R7.md`, `INSTALL_R7_NO_DOWNTIME.md`, `ROLLBACK_NOTES_R7.md`, `TEST_RESULTS_R7.md`.
- `SHA256SUMS` regenerated after all release files were finalized.

No database migration, API schema, Agent, queue, retention, maintenance or Abuse-engine file was changed.

