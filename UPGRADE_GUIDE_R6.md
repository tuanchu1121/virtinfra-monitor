# Upgrade Guide: r5 to r6

Archive: `virtinfra-monitor-50.5.9-prod-r6-node-groups-admin-bulk-management-retention-safe-maintenance-hotfix-production-slim.zip`

## Preconditions

1. Use a staging monitor first.
2. Back up `/opt/bw-monitor` and the PostgreSQL database.
3. Confirm the current service is healthy:

```bash
curl -fsS http://127.0.0.1:8080/livez
curl -fsS http://127.0.0.1:8080/healthz
systemctl status bw-monitor.service --no-pager
```

4. Verify the release manifest from the extracted release root:

```bash
sha256sum -c SHA256SUMS
```

## Staging installation

From the extracted release root:

```bash
sudo bash deploy/postgres/install-postgres-native.sh --update
```

The operator-triggered update copies the application and local flag assets, applies migrations 011 and 012 idempotently, then restarts the staging service using the existing installer behavior.

## Validation after staging update

```bash
curl -fsS http://127.0.0.1:8080/livez
curl -fsS http://127.0.0.1:8080/healthz
systemctl status bw-monitor.service --no-pager
journalctl -u bw-monitor.service -n 150 --no-pager
```

Check:

- Monitoring navigation order.
- Node Groups page summary and lazy expand.
- Admin bulk add/move/remove.
- Admin receives HTTP 403 for Maintenance endpoints.
- Super Admin can open Maintenance.
- Existing nodes/groups/memberships remain intact.
- New node inventory rows enter Ungrouped.

## Direct migration inspection

Do not run against production unless the normal change process has approved it. The additive SQL is:

```text
postgres/sql/012_node_groups_r6_safety.sql
```

It may be run repeatedly without dropping or rebuilding the database.
