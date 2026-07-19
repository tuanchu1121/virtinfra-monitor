# Upgrade Guide: r6 to r7

Release: `50.5.9-prod-r7-rbac-node-groups-node-vm-ui-refresh-hotfix-r1`

## Preconditions

1. Confirm the repository or extracted release reports the expected version:

```bash
cat VERSION
sha256sum -c SHA256SUMS
```

2. Back up the current source and PostgreSQL database:

```bash
sudo virtinfra-monitorctl backup
sudo cp -a /opt/bw-monitor "/var/backups/bw-monitor/source-before-r7-$(date -u +%Y%m%dT%H%M%SZ)"
```

3. Check current health:

```bash
curl -fsS http://127.0.0.1:8080/livez
curl -fsS http://127.0.0.1:8080/healthz
systemctl status bw-monitor.service --no-pager
```

## Upgrade from an extracted release

Run from the release root:

```bash
sudo bash deploy/postgres/install-postgres-native.sh --update
```

## Upgrade from GitHub

Only after the full release has been pushed to the repository root:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/update.sh \
| sudo bash
```

The update preserves the PostgreSQL volume and existing environment files. The monitor web service is restarted briefly to load the new source; agents keep their durable pending payload behavior.

## Post-upgrade verification

```bash
cat /opt/bw-monitor/DEPLOY_VERSION 2>/dev/null || true
curl -fsS http://127.0.0.1:8080/livez
curl -fsS http://127.0.0.1:8080/healthz
systemctl status bw-monitor.service --no-pager
journalctl -u bw-monitor.service -n 150 --no-pager
```

Check Admin RBAC, own-password change, hidden group visibility, Move all to Ungrouped, direct Node/VM actions, Admin table sorting and 30-second refresh on staging before production rollout.
