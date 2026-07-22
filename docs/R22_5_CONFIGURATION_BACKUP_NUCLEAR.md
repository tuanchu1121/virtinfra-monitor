# R22.5 Configuration Backup, Restore and True Nuclear Reset

## Scope

R22.5 adds a Super Admin-only Backup & Restore section to Maintenance. It does not change Agent payloads, metric formulas, Top VM sorting, Consumption queries or monitoring retention.

## Configuration Backup

A Configuration Backup is a checksum-verified ZIP containing only administrator-managed configuration:

- dashboard users, password hashes, roles and active state;
- API key identifiers, hashes, scopes, allowlists, status and expiry;
- whitelisted theme and Abuse-policy settings;
- user-created Node Group definitions;
- stable Node-to-Group assignments.

It excludes Node/VM inventory, current metrics, history, Consumption, Storage I/O, Abuse events, logs, sessions, Maintenance Queue, backfill state, cache state and Agent acceptance markers.

Archives are stored in `/var/backups/bw-monitor/configuration`, mode `0600`, with a manifest covering `configuration.json` and `metadata.json`. Protected archives cannot be deleted until explicitly unprotected.

## Configuration Restore

Restore is available only for verified Configuration Backups. The operator may select Users, API keys, Theme & policies, Node Groups and Node-to-Group mapping.

Safety rules:

- the current active `super_admin` is never deleted, disabled, demoted or assigned a restored password;
- a protected safety Configuration Backup is created before every restore;
- all selected sections restore in one PostgreSQL transaction;
- `admin_settings` is restored by an explicit allowlist, never by whole-table import;
- the Flask application secret rotates when Users are restored, invalidating existing sessions;
- Nodes that do not yet exist are written to `pending_node_group_restore` and assigned when their next inventory insert arrives;
- monitoring data is never restored.

## Full Emergency Database Backup

Full PostgreSQL backups remain disaster-recovery artifacts. The web interface provides queued Verify, streamed Download database dump, Protect/Unprotect and Delete. It intentionally provides no direct full-database Restore button.

The backup list uses a lightweight verified fingerprint and does not rehash multi-gigabyte dumps on every Maintenance page view. Protected full backups and the entire Configuration Backup catalog directory are excluded from scheduled cleanup.

## True Nuclear Reset

True Nuclear Reset is available only to the current active `super_admin` and requires password reauthentication, a read-only preview, a 15-second safety delay, a six-digit code and an exact confirmation phrase.

Backup choices:

- protected Configuration Backup, enabled by default;
- protected Full Emergency Database Backup, optional;
- no backup, requiring `RESET VIRTINFRA WITHOUT BACKUP <code>`.

A successful reset truncates every public application data table and removes every application account and previous Maintenance row except:

- the current active `super_admin` row;
- the currently running Nuclear job;
- one Nuclear audit row;
- schema and migration metadata in `bw_meta`.

It recreates only `Ungrouped`, rotates `app_secret_key`, and advances both Agent acceptance epochs so pre-reset queued samples cannot repopulate old state.

If a requested backup fails verification, no table is reset. If data reset commits but service restart or health verification fails, the Nuclear audit records `reset_done_service_failed` rather than implying that data survived.

## Permissions

`viewer` and `admin` cannot see or invoke Configuration Backup, Configuration Restore, Full Emergency Backup management or Nuclear Reset. Direct endpoint calls return HTTP 403. Every action requires the current Super Admin password and writes an account audit event.

## Destructive integration test

Run only against a disposable PostgreSQL database whose name contains `test`, `ci`, `r225` or `tmp`:

```bash
export BW_TEST_DATABASE_URL='postgresql://.../virtinfra_r225_test'
export BW_R225_DESTRUCTIVE_TEST=1
python3 -m pytest -q tests/test_r225_postgres_integration.py
```

The test drops and recreates the database's `public` and `bw_meta` schemas. Never point it at production.
