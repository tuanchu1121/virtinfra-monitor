# Test results R7 modular runtime

Release: `50.5.9-prod-r7-modular-runtime-refactor`

- Python compile: PASS
- Shell syntax: PASS
- YAML syntax: PASS
- Full pytest: `121 passed, 1 skipped`
- Modular architecture tests: `4 passed`
- Runtime Node Groups validation: PASS
- Flask route-map comparison: `83/83` routes unchanged
- Installer flow: PASS
- Installer manifest path safety: PASS
- Windows/GitHub Desktop mode: PASS
- SHA256 manifest: PASS, exact coverage for 790 files
- Live PostgreSQL integration: not run because no disposable `BW_TEST_DATABASE_URL` was supplied
