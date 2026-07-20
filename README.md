# VirtInfra Monitor

**Release:** `50.5.9-prod-r17-operations-single-shell-hotfix`

VirtInfra Monitor is a PostgreSQL 17 and TimescaleDB monitoring platform for KVM/libvirt nodes and virtual machines. PostgreSQL is the authoritative datastore for inventory, users, settings, current metrics, historical metrics, Abuse events, Storage I/O and Consumption.

## Deployment model

The release has two explicit entry points:

- `install.sh` is fresh-install only. It refuses to overwrite an existing application directory, PostgreSQL configuration, container or data volume.
- `update.sh` is update-only. It requires an existing installation, preserves configuration and credentials, and creates a PostgreSQL backup before replacing application code.

There is no automatic install-to-update fallback.

## Operations boundary

- `viewer` keeps the existing read-only monitoring dashboard and does not see the **Operations** navigation entry.
- `admin` is the day-to-day operator: Node Groups, Node/VM Hide/Restore/Purge, Queue monitoring/cancel, retention, bounded history cleanup and online VACUUM.
- `super_admin` has every Admin capability plus API management, Super Admin account control, Clear Monitoring Data, Clear API Data and Nuclear Reset.
- UI visibility and backend authorization use the same role boundary; direct forged requests remain denied.


## Fresh installation

Supported operating systems: Debian 12+ and Ubuntu 22.04+ with systemd. Run as root.

### Public IP

```bash
apt-get update
apt-get install -y curl ca-certificates tar

curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/install.sh \
| bash -s -- \
--public-ip 203.0.113.10 \
--port 8080
```

### Domain and HTTPS

Point the domain to the Monitor server and allow TCP 80/443 first.

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/install.sh \
| bash -s -- \
--domain monitor.example.com \
--email ops@example.com
```

Generated credentials are stored with root-only permissions in:

```text
/root/bw-monitor-credentials.env
```

## Update

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/update.sh \
| bash
```

The updater preserves:

- the `bw_monitor_postgres_data` Docker volume;
- `/etc/default/bw-monitor` and `/etc/default/bw-monitor-postgres` settings;
- Admin credentials, Agent token, domain/TLS settings and current data;
- PostgreSQL backup/restore and rollback controls needed for update safety.

Change domain through the update path:

```bash
virtinfra-monitorctl domain set monitor.example.com ops@example.com
virtinfra-monitorctl domain remove 203.0.113.10 8080
```

## Runtime architecture

```text
virtinfra-agent.service
    local sample every 15 seconds
    durable push every 300 seconds
            |
            v
Nginx or public IP -> Gunicorn + Flask -> PostgreSQL 17 + TimescaleDB
```

Core retention contracts:

- `vm_chart_5m` and `node_chart_5m`: exact five-minute points for seven days;
- `vm_raw_detail_5m`: per-interface raw detail for 48 hours;
- `node_bandwidth_consumption_2h`: compatibility Consumption history used by existing readers;
- `/bandwidth-consumption`: VM and physical Public/Private RX/TX views;
- `VIRTINFRA_READ_CHART_V2` and `VIRTINFRA_RAW_V2`: controlled Storage V2 readers and raw detail switches.

The application keeps the existing CPU, RAM, network, PPS, disk, bandwidth, Abuse, retention and queue calculations unchanged.

## Administration and maintenance

- `admin` can manage Viewer/Admin accounts, themes, logs, system health, Node Groups, Nodes, VMs and routine maintenance.
- `super_admin` additionally controls Super Admin accounts and destructive/Nuclear Reset operations.
- Maintenance requests enter a PostgreSQL-backed FIFO queue. The dispatcher starts one systemd worker at a time and the one-minute watchdog retries queued work if an immediate wake fails.
- Manual history deletion supports 1, 2, 3 and 7 days. Automatic retention remains the existing 2-day raw and 7-day hourly policy.

Queue diagnostics:

```bash
systemctl status bw-monitor-maintenance-watchdog.timer --no-pager -l
systemctl status bw-monitor-maintenance-dispatch.service --no-pager -l
journalctl -u bw-monitor-maintenance-dispatch.service -n 100 --no-pager
journalctl -u 'bw-monitor-maintenance@*.service' -n 100 --no-pager
```

## Operations

```bash
virtinfra-monitorctl status
virtinfra-monitorctl health
virtinfra-monitorctl doctor
virtinfra-monitorctl db-check
virtinfra-monitorctl logs all 200
virtinfra-monitorctl follow monitor
virtinfra-monitorctl backup
virtinfra-monitorctl restore --from /var/backups/bw-monitor/TIMESTAMP --yes
virtinfra-monitorctl retention
virtinfra-monitorctl vacuum
virtinfra-monitorctl storage-v2
virtinfra-monitorctl rollback-storage-v2
virtinfra-monitorctl update
```

Services and timers:

```text
bw-monitor.service
bw-monitor-retention.timer
bw-monitor-backup.timer
virtinfra-monitor-health-watch.timer
bw-monitor-inventory-cleanup.timer
virtinfra-agent.service
```

PostgreSQL is exposed only on `127.0.0.1:55432`. The container is `bw-timescaledb`.

## Agent

The Agent uses:

```text
virtinfra-agent.service
/etc/virtinfra-agent.env
/usr/local/lib/virtinfra-agent
/var/lib/virtinfra-agent
```

Install one Agent:

```bash
bash install-agent.sh \
  --api 'https://monitor.example.com/push' \
  --token 'YOUR_AGENT_TOKEN'
```

Ansible deployment is documented in [`docs/ANSIBLE.md`](docs/ANSIBLE.md).

## Repository layout

```text
app/                 Flask runtime and data access
postgres/            PostgreSQL/TimescaleDB compose and schema
postgres/sql/        idempotent schema files
deploy/postgres/     fresh installer, updater, services and management tools
deploy/agent/        Agent source and installer
ansible/             Agent deployment automation
tests/               runtime and release contracts
tools/               validation and packaging
```

## Validation

```bash
./preflight.sh
./tools/release-audit.sh
```

Live integration requires a disposable database:

```bash
BW_TEST_DATABASE_URL='postgresql://user:pass@127.0.0.1:5432/bw_monitor_test' \
./preflight.sh --use-current-python
```

## Documentation

- [`COMMANDS_A_TO_Z_VI.md`](COMMANDS_A_TO_Z_VI.md)
- [`docs/INSTALL.md`](docs/INSTALL.md)
- [`docs/UPGRADE.md`](docs/UPGRADE.md)
- [`docs/MANAGEMENT.md`](docs/MANAGEMENT.md)
- [`docs/DATABASE.md`](docs/DATABASE.md)
- [`docs/BACKUP_RESTORE.md`](docs/BACKUP_RESTORE.md)
- [`docs/AGENT.md`](docs/AGENT.md)
- [`docs/ANSIBLE.md`](docs/ANSIBLE.md)
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)
- [`SECURITY.md`](SECURITY.md)
