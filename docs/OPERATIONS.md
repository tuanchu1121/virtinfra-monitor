# Operations checklist

Daily/regular checks:

```bash
virtinfra-monitorctl doctor
virtinfra-monitorctl status
systemctl list-timers --all | grep bw-monitor
```

Weekly:

```bash
virtinfra-monitorctl db-check
virtinfra-monitorctl backup
find /var/backups/bw-monitor -maxdepth 1 -type d -printf '%TY-%Tm-%Td %p\n' | sort
```

Before update:

```bash
virtinfra-monitorctl backup
virtinfra-monitorctl update
virtinfra-monitorctl doctor
```

For support bundle:

```bash
virtinfra-monitorctl diagnostics
```

Review the archive before sharing it. The collector redacts environment secret values and does not include a database dump.

Maintenance queue health:

```bash
systemctl is-active bw-monitor-maintenance-watchdog.timer
systemctl start bw-monitor-maintenance-dispatch.service
journalctl -u bw-monitor-maintenance-dispatch.service -n 200 --no-pager
```

Before a nuclear operational reset, confirm a normal backup succeeds. The reset itself creates and verifies a new backup again before deleting data.
