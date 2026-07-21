# Validation Report R22.5

Release: `50.5.9-prod-r22.5-configuration-backup-nuclear-hardening`

## Completed in the build environment

- Full non-live preflight: PASS.
- 166 pytest cases executed by preflight across 25 isolated groups: PASS.
- Static/script contracts for repository, Storage V2, documentation, Agent Consumption, auth, UI and themes: PASS.
- Runtime source manifest: 46 ordered layers, hash pinned, 32,997 combined lines.
- Runtime route validation: 83 routes, PASS.
- Runtime RBAC validation: 30/30 checks, PASS.
- Node Groups runtime validation: 27/27 checks, PASS.
- Installer flow: PASS.
- Safe manifest-path installer test: PASS.
- Python and shell syntax: PASS.
- SHA256 source manifest exact coverage: PASS.

## R22.5-specific coverage

- Configuration ZIP creation, checksum verification, protection and deletion.
- Archive traversal and unexpected-entry rejection.
- Safe `admin_settings` allowlist, including theme and Abuse CPU/RAM/network/disk policy settings while excluding secrets and runtime markers.
- Super Admin-only UI and backend contract.
- FIFO Configuration Backup, Configuration Restore, Full Backup and Full Backup Verify actions.
- Full Backup listing without rehashing multi-GB dumps during page rendering.
- Protected Full Backup and Configuration catalog retention exclusions.
- Dynamic true Nuclear table coverage and protected identity/job/audit contract.
- Strong no-backup confirmation and Nuclear preview contract.
- Top VM 2,000-row option with existing global sort-before-limit behavior.
- Migration 016 contract and pending Node-to-Group restoration trigger.
- Isolated validation runner for legacy tests that leave background threads alive after assertions complete.

## Live destructive PostgreSQL test

Not executed in this build container because no disposable PostgreSQL/TimescaleDB DSN was available. The packaged test requires both:

```bash
BW_TEST_DATABASE_URL='postgresql://.../virtinfra_r225_test'
BW_R225_DESTRUCTIVE_TEST=1
```

It refuses database names without a test/CI marker and deliberately drops/recreates `public` and `bw_meta`. Run it only against a disposable clone.

## Known limitations

- Configuration archives contain password hashes and API-key hashes. Files are mode `0600` under a root-only directory but are not additionally encrypted by the application.
- Full Emergency Database Restore is intentionally not exposed in the web UI.
- Pending Node-to-Group restore uses the monitor's stable Node identity string. A Node returning with a different identity remains in `Ungrouped`.
