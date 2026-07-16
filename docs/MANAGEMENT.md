# Management CLI

`virtinfra-monitorctl` is installed at `/usr/local/sbin/virtinfra-monitorctl`.

```bash
virtinfra-monitorctl help
```

Core commands:

```bash
virtinfra-monitorctl status
virtinfra-monitorctl doctor
virtinfra-monitorctl audit
virtinfra-monitorctl db-check
virtinfra-monitorctl urls
virtinfra-monitorctl credentials
virtinfra-monitorctl version
```

Logs:

```bash
virtinfra-monitorctl logs monitor 300
virtinfra-monitorctl logs retention 300
virtinfra-monitorctl logs postgres 300
virtinfra-monitorctl logs all 300
virtinfra-monitorctl follow monitor
virtinfra-monitorctl follow postgres
```

Database and maintenance:

```bash
virtinfra-monitorctl psql
virtinfra-monitorctl retention
virtinfra-monitorctl vacuum
virtinfra-monitorctl backup
virtinfra-monitorctl restore --from PATH --yes
```

Deployment:

```bash
virtinfra-monitorctl update
virtinfra-monitorctl domain status
virtinfra-monitorctl domain set monitor.example.com ops@example.com
virtinfra-monitorctl domain remove 203.0.113.10 8080
```

The `vacuum` command runs online PostgreSQL `VACUUM/ANALYZE`; it is not a file rewrite operation.

## Admin Maintenance actions

The Admin Maintenance page uses one serialized systemd worker. PostgreSQL advisory locks plus a partial unique index prevent two active jobs from being created by concurrent Gunicorn requests.

| Action | Online? | What it does | Preserves |
|---|---:|---|---|
| Run retention now | Yes | Applies the normal 0–2 day 5-minute, day 3–7 hourly, older-than-7-day deletion policy | Current/latest state, inventory, users, settings, API keys |
| Delete history | Yes | Deletes history older than 1, 3 or 7 days in committed batches | Current/latest state, inventory, users, settings |
| Delete history + VACUUM | Yes | Runs the same deletion, then online `VACUUM (ANALYZE)` | Same as Delete history |
| VACUUM ANALYZE | Yes | Reclaims dead tuples for reuse and refreshes planner statistics with no maintenance statement timeout | All rows |
| Clear monitoring data | Brief stop | Atomically truncates monitoring history, current caches, inventory, node logs and Abuse rows | Dashboard users, Admin settings, account logs, API keys/logs, maintenance history |
| Reset ALL app data + queue | Brief stop | Atomically truncates monitoring data, inventory, Abuse policy history, account logs, API keys/logs and old maintenance rows | Dashboard users, Admin settings, schema metadata |
| Clear API logs | Yes | Truncates API request logs and API management events | API keys and Agent token |
| Clear all API data | Yes | Truncates external API keys and API logs | Agent `BW_MONITOR_TOKEN` |
| Purge VM/node | Yes, per-node lock | Permanently removes the selected object and its retained history | Other nodes and VMs |

`CLEAR LIVE 5M` was removed from the main Maintenance page because it only empties rebuildable current caches, causes a temporary blank dashboard and can trigger a synchronized repopulation spike. `Checkpoint` was removed because PostgreSQL manages checkpoints automatically and the old button did not force one.

Normal VACUUM is not `VACUUM FULL`: it remains online and generally does not shrink the physical database file. Full destructive resets use `TRUNCATE`, so a post-reset VACUUM is unnecessary.

