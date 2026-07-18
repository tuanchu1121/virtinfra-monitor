# VIRTINFRA MONITOR: TÀI LIỆU VẬN HÀNH

> Release `50.6.0-prod-r1-node-groups-country-flags`

Runtime hiện tại dùng PostgreSQL 17 + TimescaleDB làm nguồn dữ liệu duy nhất.

## Bắt đầu

- [`../START_HERE_VI.md`](../START_HERE_VI.md)
- [`../SOURCE_OF_TRUTH_VI.md`](../SOURCE_OF_TRUTH_VI.md)
- [`../GITHUB_DESKTOP_VI.md`](../GITHUB_DESKTOP_VI.md)
- [`../COMMANDS_A_TO_Z_VI.md`](../COMMANDS_A_TO_Z_VI.md)

## Cài đặt và update

- [`INSTALL.md`](INSTALL.md)
- [`UPGRADE.md`](UPGRADE.md)
- [`DOMAIN.md`](DOMAIN.md)
- [`PUBLISHING.md`](PUBLISHING.md)

## Vận hành

- [`MANAGEMENT.md`](MANAGEMENT.md)
- [`OPERATIONS.md`](OPERATIONS.md)
- [`QUICK_COMMANDS.md`](QUICK_COMMANDS.md)
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)
- [`AUDIT.md`](AUDIT.md)

## Database

- [`DATABASE.md`](DATABASE.md)
- [`BACKUP_RESTORE.md`](BACKUP_RESTORE.md)

## Agent và Ansible

- [`AGENT.md`](AGENT.md)
- [`ANSIBLE.md`](ANSIBLE.md)

## API và code

- [`API.md`](API.md)
- [`CODE_GUIDE.md`](CODE_GUIDE.md)

## Contract nhanh

```text
Database: PostgreSQL 17 + TimescaleDB
Container: bw-timescaledb
Volume: bw_monitor_postgres_data
PostgreSQL bind: 127.0.0.1:55432
Web service: bw-monitor.service
Retention timer: bw-monitor-retention.timer
Backup timer: bw-monitor-backup.timer
Health timer: virtinfra-monitor-health-watch.timer
Agent service: virtinfra-agent.service
Consumption: bucket 2 giờ, giữ 7 ngày, không lưu UUID VM
```


## Hướng dẫn cho người mới

- [Hướng dẫn đầy đủ cho repo mới](../HUONG_DAN_REPO_MOI_VI.md)
