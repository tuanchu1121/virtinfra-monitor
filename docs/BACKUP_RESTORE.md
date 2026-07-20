# Backup and restore

## Backup

```bash
virtinfra-monitorctl backup
```

The backup uses PostgreSQL custom format with compression and validates the archive list. It also copies protected environment files, credentials, Nginx site, deployed version, metadata and SHA256 checksums.

Default path:

```text
/var/backups/bw-monitor/YYYYMMDD-HHMMSS/
```

Default local retention is 14 days. Keep an additional encrypted copy outside the Monitor server.

## Restore database only

```bash
virtinfra-monitorctl restore \
--from /var/backups/bw-monitor/20260715-050000 \
--yes
```

The restore tool:

1. verifies SHA256;
2. creates a pre-restore PostgreSQL dump;
3. stops the web service;
4. recreates the database;
5. enables TimescaleDB;
6. runs Timescale pre/post restore hooks;
7. restores with `pg_restore --exit-on-error`;
8. starts and health-checks the web service.

## Restore configuration too

```bash
virtinfra-monitorctl restore \
--from /var/backups/bw-monitor/20260715-050000 \
--with-config \
--yes
```

Review domain, IP, ports and credentials after restoring configuration to another server.
