# Node Groups rollback

Rollback artifacts are intentionally shipped as a **separate package** so the
production source manifest never references a nested archive or embedded old
release.

1. Download and extract:
   `virtinfra-monitor-50.5.9-prod-r5-node-groups-hotfix-additive-rollback.zip`
2. Enter the extracted rollback directory.
3. Run:

```bash
sudo bash rollback-node-groups.sh
```

Optional non-default runtime path or health endpoint:

```bash
sudo bash rollback-node-groups.sh \
  --app-dir /opt/bw-monitor \
  --service bw-monitor.service \
  --health-base http://127.0.0.1:8080
```

The rollback package backs up the current runtime, stops the service only when
it is active, restores the r4 application source, preserves migrated
`super_admin` access through a compatibility wrapper, compiles, restarts and
checks `/livez` plus `/healthz`. If health checks fail it restores the
pre-rollback runtime backup. It does not delete Node Groups tables, metrics,
logs or historical records.
