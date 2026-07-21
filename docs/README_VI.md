# Tài liệu VirtInfra Monitor

Release: `50.5.9-prod-r22.5-configuration-backup-nuclear-hardening`

Runtime dùng PostgreSQL 17 + TimescaleDB làm nguồn dữ liệu duy nhất.

## Cài mới và update

- [`INSTALL.md`](INSTALL.md): cài mới trên server sạch.
- [`UPGRADE.md`](UPGRADE.md): update installation đang hoạt động.
- [`DOMAIN.md`](DOMAIN.md): domain, Nginx và HTTPS.
- [`PUBLISHING.md`](PUBLISHING.md): đưa source lên GitHub.

`install.sh` không tự chuyển thành update. Khi đã có `/opt/bw-monitor`, cấu hình PostgreSQL, container hoặc volume hiện hữu, cài mới sẽ dừng. Mọi nâng cấp đi qua `update.sh`.

## Vận hành

- [`../COMMANDS_A_TO_Z_VI.md`](../COMMANDS_A_TO_Z_VI.md)
- [`MANAGEMENT.md`](MANAGEMENT.md)
- [`OPERATIONS.md`](OPERATIONS.md)
- [`QUICK_COMMANDS.md`](QUICK_COMMANDS.md)
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)
- [`AUDIT.md`](AUDIT.md)

## Database, Agent và API

- [`DATABASE.md`](DATABASE.md)
- [`BACKUP_RESTORE.md`](BACKUP_RESTORE.md)
- [`AGENT.md`](AGENT.md)
- [`ANSIBLE.md`](ANSIBLE.md)
- [`API.md`](API.md)
- [`CODE_GUIDE.md`](CODE_GUIDE.md)
