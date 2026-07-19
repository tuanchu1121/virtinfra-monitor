# Rollback Notes: r6 to r5

Rollback source release: `virtinfra-monitor-50.5.9-prod-r6-node-groups-admin-bulk-management-retention-safe-maintenance-hotfix-production-slim.zip`

Rollback is source-first. Do not restore or delete the database automatically.

## Safe rollback sequence

1. Keep the current r6 source backup.
2. Restore the exact r5 schema-import-fix source into `/opt/bw-monitor`.
3. Compile before restart.
4. Restart only the monitor service.
5. Verify `/livez` and `/healthz`.
6. If health checks fail, restore the r6 source backup.

Example:

```bash
set -Eeuo pipefail

APP_DIR=/opt/bw-monitor
SERVICE=bw-monitor.service
R5_DIR=/root/virtinfra-monitor-r5-schema-import-fix
BACKUP=/root/virtinfra-r6-source-backup-$(date -u +%Y%m%dT%H%M%SZ)

mkdir -p "$BACKUP"
cp -a "$APP_DIR"/. "$BACKUP"/

test -f "$R5_DIR/app/app.py"
test -f "$R5_DIR/app/node_groups.py"

systemctl stop "$SERVICE"
install -m 0644 "$R5_DIR/app/app.py" "$APP_DIR/app.py"
install -m 0644 "$R5_DIR/app/node_groups.py" "$APP_DIR/node_groups.py"
install -m 0644 "$R5_DIR/app/maintenance_native.py" "$APP_DIR/maintenance_native.py"
python3 -m py_compile "$APP_DIR/app.py" "$APP_DIR/node_groups.py" "$APP_DIR/maintenance_native.py"
systemctl start "$SERVICE"

for _ in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:8080/livez >/dev/null \
     && curl -fsS --max-time 3 http://127.0.0.1:8080/healthz >/dev/null; then
    echo ROLLBACK_OK
    exit 0
  fi
  sleep 2
done

echo 'Rollback health check failed; restoring r6 source backup' >&2
systemctl stop "$SERVICE"
cp -a "$BACKUP"/. "$APP_DIR"/
python3 -m py_compile "$APP_DIR/app.py" "$APP_DIR/node_groups.py" "$APP_DIR/maintenance_native.py"
systemctl start "$SERVICE"
exit 1
```

## Database handling

Do not drop Node Group tables and do not downgrade role data. Migration 012 adds only indexes and an idempotent trigger. Leaving it in place is compatible with r5 because membership writes use `ON CONFLICT`/single-node uniqueness. No metrics, logs or accounting data should be deleted during rollback.
