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

## Operations Maintenance actions

Admin and Super Admin use the same Operations shell. Routine Queue actions are available to Admin operators; destructive whole-system/API reset actions are visible and callable only by Super Admin. The Maintenance page is a PostgreSQL FIFO queue. Routine jobs may wait in ID order, while a partial unique index permits only one `starting/running` worker. The dispatcher claims with `FOR UPDATE SKIP LOCKED`; the worker writes a heartbeat every 30 seconds and the systemd watchdog checks the queue every minute. A queued job may be cancelled before execution.

| Action | Online? | What it does | Preserves |
|---|---:|---|---|
| Run retention now | Yes | Applies the normal 0–2 day 5-minute, day 3–7 hourly, older-than-7-day deletion policy | Current/latest state, inventory, users, settings, API keys |
| Delete history | Yes | Deletes history older than 1, 2, 3 or 7 days in committed batches | Current/latest state, inventory, users, settings |
| Delete history + VACUUM | Yes | Runs the same deletion, then online `VACUUM (ANALYZE)` | Same as Delete history |
| VACUUM ANALYZE | Yes | Reclaims dead tuples for reuse and refreshes planner statistics with no maintenance statement timeout | All rows |
| Clear monitoring data (Super Admin) | Brief stop | Atomically truncates monitoring history, current caches, inventory, node logs and Abuse rows | Dashboard users, Admin settings, account logs, API keys/logs, Maintenance history |
| Nuclear operational reset (Super Admin) | Brief stop after backup | Truncates the explicit operational/API/account allow-list only after preview and verified backup | Dashboard users, Admin settings, schema metadata, Maintenance history and permanent nuclear audit |
| Clear API logs (Super Admin) | Yes | Truncates API request logs and API management events | API keys and Agent token |
| Clear all API data (Super Admin) | Yes | Truncates external API keys and API logs | Agent `BW_MONITOR_TOKEN` and legacy Agent tokens |
| Purge VM/node | Yes, per-node lock | Permanently removes the selected object and its retained history | Other nodes and VMs |

### Nuclear reset safety

The reset cannot be queued behind other work. The queue must be empty at preview time and again at final confirmation. The flow requires:

1. Current Admin password.
2. Read-only table/row/size preview.
3. A server-enforced 15-second review delay, then a six-digit phrase that expires after five minutes.
4. Current Admin password again.
5. A successful backup containing `database.dump`, a non-empty `pg_restore` catalog and a verified `SHA256SUMS`.
6. A short service stop for the allow-listed `TRUNCATE`.
7. `/livez` and `/healthz` checks after restart.
8. A permanent success/failure row in `maintenance_nuclear_audit` after the backup succeeds, including restart and health-check outcome.

If backup or verification fails, the worker stops before `TRUNCATE`. `maintenance_jobs` and `maintenance_nuclear_audit` are never included in the nuclear allow-list.

A monitoring clear or nuclear reset also advances `operational_push_accept_after` and `bandwidth_consumption_accept_after` in preserved Admin settings. Old payloads still queued in an Agent runtime file receive HTTP 200 with `ignored=true`, but cannot recreate data from before the reset epoch.

### Queue diagnostics

```bash
systemctl status bw-monitor-maintenance-watchdog.timer --no-pager
systemctl start bw-monitor-maintenance-dispatch.service
journalctl -u bw-monitor-maintenance-dispatch.service -n 200 --no-pager
journalctl -u 'bw-monitor-maintenance@*' -n 300 --no-pager
```

`CLEAR LIVE 5M` remains removed because it empties rebuildable current caches and creates a synchronized refill spike. `Checkpoint` remains removed because PostgreSQL manages checkpoints automatically.

Normal VACUUM is not `VACUUM FULL`: it remains online and generally does not shrink the physical database file. Full destructive resets use `TRUNCATE`, so a post-reset VACUUM is unnecessary.
