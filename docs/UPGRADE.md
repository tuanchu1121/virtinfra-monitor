# Update an existing installation

Release: `50.5.9-prod-r21-consumption-ingest-preaggregation-hotfix`
Use this path only when VirtInfra Monitor is already installed. The updater requires both `/etc/default/bw-monitor` and `/etc/default/bw-monitor-postgres`.

```bash
virtinfra-monitorctl update
```

Or:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/update.sh \
| bash
```

Before application files are replaced, the updater runs the installed PostgreSQL backup tool. R19 then refuses an update while a maintenance worker is active and briefly stops the web, retention, backup, inventory-cleanup and health-watch services so schema/backfill work cannot deadlock with live traffic. It preserves:

- the `bw_monitor_postgres_data` volume;
- PostgreSQL credentials and port;
- Admin credentials and session secret;
- Agent token and accepted transition tokens;
- domain, TLS, Gunicorn and optional Redis settings;
- all current and historical monitoring data.

After updating from a pre-R18 release, every existing browser session must sign in again because sessions are now bound to the account's current password, role and enabled state.

After update:

```bash
virtinfra-monitorctl version
virtinfra-monitorctl status
virtinfra-monitorctl health
virtinfra-monitorctl doctor
virtinfra-monitorctl db-check
```

Change domain through the updater:

```bash
virtinfra-monitorctl domain set monitor.example.com ops@example.com
virtinfra-monitorctl domain remove 203.0.113.10 8080
```

The fresh installer deliberately refuses an existing installation. Do not use `install.sh` as an update command.
