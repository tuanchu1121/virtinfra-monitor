# Rollback r7 to the previous r5 source

Rollback is a source rollback. Do not delete or recreate the PostgreSQL database and do not remove Node Group tables.

## Procedure

1. Keep the verified previous r5 release archive available locally.
2. Back up the current runtime and database:

```bash
sudo virtinfra-monitorctl backup
sudo cp -a /opt/bw-monitor "/opt/bw-monitor.r7-backup.$(date -u +%Y%m%dT%H%M%SZ)"
```

3. Stop only the web service:

```bash
sudo systemctl stop bw-monitor.service
```

4. Restore the previous r5 application source into `/opt/bw-monitor` while preserving:

```text
/etc/default/bw-monitor
/etc/default/bw-monitor-postgres
/var/lib/bw-monitor
bw_monitor_postgres_data
```

5. Compile and start:

```bash
sudo /opt/bw-monitor/venv/bin/python -m py_compile \
  /opt/bw-monitor/app.py \
  /opt/bw-monitor/node_groups.py
sudo systemctl start bw-monitor.service
```

6. Verify:

```bash
curl -fsS http://127.0.0.1:8080/livez
curl -fsS http://127.0.0.1:8080/healthz
journalctl -u bw-monitor.service -n 150 --no-pager
```

If health checks fail, restore the `/opt/bw-monitor.r7-backup.*` copy and start the service again. Do not delete metrics, logs, Node Groups or membership history during rollback.
