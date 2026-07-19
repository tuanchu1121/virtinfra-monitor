# R8 validation results

Release: `50.5.9-prod-r8-safe-dead-code-prune`

## Automated validation

- Python compile: PASS.
- Full pytest: **124 passed, 1 skipped**.
- Skipped test: live PostgreSQL integration because `BW_TEST_DATABASE_URL` was not provided.
- Modular runtime manifest: PASS, 44 ordered layers.
- Runtime equivalence: PASS, 83 routes and 920 final callables identical to R7.
- Flask hooks: PASS, 6 hook functions identical.
- Static/UI asset hashes: PASS, byte-for-byte identical.
- Shell syntax: PASS.
- YAML syntax: PASS.
- Installer flow: PASS.
- Installer safe-manifest-path test: PASS.
- Windows/GitHub Desktop compatibility test: PASS.
- `SHA256SUMS`: exact coverage for 796 source files.
- Node Groups runtime/UI/browser contracts: PASS.
- Agent, Consumption, Storage, maintenance, queue, theme and responsive UI contracts: PASS.
- Final dead-code audit: PASS, third round found zero additional safe candidates.

The monolithic preflight command exceeded the workspace command-duration cap after completing its earlier phases. Every remaining preflight command was then executed individually and passed. No production service, database or Agent was modified or restarted.
