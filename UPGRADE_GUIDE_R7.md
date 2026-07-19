# Upgrade r5 to r7

Target release: `50.5.9-prod-r7-rbac-node-groups-node-vm-ui-refresh-hotfix`.

## Before upgrade

1. Confirm GitHub `main/VERSION` returns the exact target release.
2. Create an application/database backup:

```bash
sudo virtinfra-monitorctl backup
```

3. Confirm both existing installation environment files are present:

```bash
test -r /etc/default/bw-monitor
test -r /etc/default/bw-monitor-postgres
```

## Upgrade

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/update.sh \
| sudo bash
```

Equivalent installer mode:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/install.sh \
| sudo bash -s -- --update
```

The updater preserves the PostgreSQL volume, runtime environment, credentials, Node Groups, memberships, metrics, Abuse records and accounting data. A short web-service restart is required to load the new source.

## Verify

```bash
cat /opt/bw-monitor/DEPLOY_VERSION 2>/dev/null || true
systemctl is-active bw-monitor.service
curl -fsS http://127.0.0.1:8080/livez
curl -fsS http://127.0.0.1:8080/healthz
journalctl -u bw-monitor.service -n 150 --no-pager
```

Do not remove `bw_monitor_postgres_data` and do not run `docker compose down -v`.
