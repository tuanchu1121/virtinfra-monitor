# R22.5 Configuration Backup and Nuclear Hardening

Release: `50.5.9-prod-r22.5-configuration-backup-nuclear-hardening`

## Added

- Super Admin-only Configuration Backup and Restore in Maintenance.
- Selective backup for users/roles, API keys, safe theme/policy settings, Node Groups and stable Node-to-Group mappings.
- ZIP checksum verification, protection, download and deletion controls.
- Full Emergency Backup catalog with FIFO-queued Verify, streamed database dump download, Protect/Unprotect and Delete. No web restore is exposed.
- Protected safety Configuration Backup before every Configuration Restore.
- Optional protected Configuration Backup and optional protected Full Emergency Database Backup before Nuclear Reset.
- Strong no-backup Nuclear confirmation.
- Pending Node-to-Group restoration when Nodes reconnect after Nuclear Reset.
- Top VM 2,000-row option while preserving global PostgreSQL sort-before-limit behavior.

## Nuclear behavior

A successful Nuclear Reset deletes every public application data table and all prior queue/history rows. It preserves only:

- the active super_admin that initiated the reset;
- the current Nuclear maintenance job;
- one Nuclear audit row;
- PostgreSQL schema and migration metadata.

It recreates only `Ungrouped`, rotates the Flask application secret and advances both Agent acceptance epochs.

## Not restored by Configuration Restore

Node/VM inventory, metrics, Consumption, Storage I/O, Abuse events, logs, sessions, Maintenance Queue and backfill/runtime markers.

## Validation safety

- Full-backup listings use a lightweight verified fingerprint marker and never hash multi-GB dumps during page render.
- Protected full backups and the Configuration Backup catalog directory are excluded from scheduled backup retention cleanup.
- Destructive PostgreSQL integration requires both `BW_TEST_DATABASE_URL` and `BW_R225_DESTRUCTIVE_TEST=1`, and refuses database names without a test/CI marker.
