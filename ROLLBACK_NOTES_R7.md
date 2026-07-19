# Rollback Notes: r7 to r6

Rollback target: the exact r6 installer-manifest-fixture-fix source previously used by the installation.

This hotfix adds no database table or column. Rollback is source-first and does not require deleting Node Groups, memberships, metrics, abuse data, accounting data or PostgreSQL volumes.

## Safe rollback

```bash
set -Eeuo pipefail

APP_DIR=/opt/bw-monitor
SERVICE=bw-monitor.service
R6_DIR=/root/virtinfra-monitor-r6-installer-manifest-fixture-fix
BACKUP="/root/virtinfra-r7-source-backup-$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$BACKUP"
cp -a "$APP_DIR"/. "$BACKUP"/

test -f "$R6_DIR/app/app.py"
test -f "$R6_DIR/app/node_groups.py"

systemctl stop "$SERVICE"
cp -a "$R6_DIR"/app/. "$APP_DIR"/
python3 -m compileall -q "$APP_DIR"
systemctl start "$SERVICE"

for _ in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:8080/livez >/dev/null \
     && curl -fsS --max-time 3 http://127.0.0.1:8080/healthz >/dev/null; then
    echo ROLLBACK_OK
    exit 0
  fi
  sleep 2
done

echo 'Rollback health check failed; restoring r7 source backup' >&2
systemctl stop "$SERVICE"
cp -a "$BACKUP"/. "$APP_DIR"/
python3 -m compileall -q "$APP_DIR"
systemctl start "$SERVICE"
exit 1
```

Do not run destructive maintenance, remove the PostgreSQL volume or downgrade role records during this source rollback.
