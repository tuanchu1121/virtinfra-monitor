# R22.5 Migration and Rollback

## Upgrade

1. Create or verify a normal emergency PostgreSQL backup when production policy requires it.
2. Copy the complete R22.5 release to the server.
3. Verify `SHA256SUMS`.
4. Run the local installer in update mode:

```bash
BW_BOOTSTRAP_ACTION=update bash install.sh
```

5. Confirm `/livez`, `/healthz`, service state, timers, Maintenance Queue and version.
6. Create one manual Configuration Backup and verify that it appears as `VERIFIED`.

Migration `016_configuration_backup_nuclear.sql` is additive. It creates the pending Node-to-Group mapping table, hardens Nuclear audit metadata and updates the Node inventory assignment trigger.

## Pre-production destructive rehearsal

On a disposable database clone only:

```bash
export BW_TEST_DATABASE_URL='postgresql://.../virtinfra_r225_test'
export BW_R225_DESTRUCTIVE_TEST=1
python3 -m pytest -q tests/test_r225_postgres_integration.py
```

Verify that Nuclear keeps only the initiating Super Admin/current job/one audit, and that Configuration Restore returns users, API keys, safe settings, Groups and pending mappings without monitoring data.

## Source rollback

If update fails before migration completes, restore the previous source snapshot and restart the service. Migration 016 is additive and may remain present without affecting R22.4 runtime.

```bash
systemctl stop bw-monitor.service
# restore the previous /opt/bw-monitor source snapshot
systemctl daemon-reload
systemctl start bw-monitor.service
systemctl start bw-monitor-maintenance-watchdog.timer bw-monitor-retention.timer \
  bw-monitor-backup.timer bw-monitor-inventory-cleanup.timer \
  virtinfra-monitor-health-watch.timer
```

Check:

```bash
curl -fsS http://127.0.0.1:8080/livez
curl -fsS http://127.0.0.1:8080/healthz
```

Do not attempt a web Full Database Restore. Full dumps are disaster-recovery artifacts and must be restored to a clone, migrated and validated before any database cutover.
