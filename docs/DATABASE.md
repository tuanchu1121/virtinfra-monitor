# POSTGRESQL 17 + TIMESCALEDB

## Runtime

```text
Container: bw-timescaledb
Database: bw_monitor
User: bw_monitor
Host bind: 127.0.0.1:55432
Docker volume: bw_monitor_postgres_data
```

PostgreSQL/TimescaleDB là nguồn dữ liệu duy nhất.

## Kiểm tra nhanh

```bash
virtinfra-monitorctl db-check
```

```bash
virtinfra-monitorctl psql
```

## Container

```bash
docker ps --filter name=bw-timescaledb
```

```bash
docker inspect -f '{{.State.Health.Status}}' bw-timescaledb
```

```bash
docker logs --tail 300 bw-timescaledb
```

## Volume

```bash
docker volume inspect bw_monitor_postgres_data
```

Không xóa volume này khi chưa có backup đã verify.

## Database size

```bash
virtinfra-monitorctl psql -c "SELECT pg_size_pretty(pg_database_size(current_database())) AS database_size;"
```

## Hypertables

```bash
virtinfra-monitorctl psql -c "SELECT hypertable_name,num_chunks FROM timescaledb_information.hypertables ORDER BY hypertable_name;"
```

## Consumption tables

| Table | Grain | Purpose | Retention |
|---|---|---|---:|
| `node_stats` | VM interface / five-minute bucket | Recent raw VM network detail | 48 hours |
| `node_physical_net_stats` | Physical interface / five-minute bucket | Recent raw physical network detail | 48 hours |
| `bandwidth_hourly` | VM + bridge + hour | Fast per-VM rolling queries | 7 days |
| `bandwidth_daily` | VM + bridge + day | Fast 2D–7D per-VM queries | 7 days |
| `node_consumption_hourly` | Node + hour | Physical Public/Private totals | 7 days |
| `node_consumption_daily` | Node + day | Physical daily totals | 7 days |
| `node_vm_consumption_hourly` | Node + hour | Total of every VM on one Node | 7 days |
| `node_vm_consumption_daily` | Node + day | Daily total of every VM on one Node | 7 days |
| `node_bandwidth_consumption_2h` | Node + legacy two-hour bucket | Dormant upgrade compatibility only; no new Agent writes | legacy |

The active data path is the normal five-minute `/push`. The retired
`/push/bandwidth-consumption` endpoint returns HTTP 410 and does not write data.
Node and Node Group pages compare compact Physical totals with compact All-VM
totals without scanning the high-cardinality per-VM tables for every request.

## VACUUM online

```bash
virtinfra-monitorctl vacuum
```

Routine VACUUM giúp tái sử dụng dead tuples. Không dùng `VACUUM FULL` trong giờ production.

## Backup/restore

```bash
virtinfra-monitorctl backup
```

```bash
virtinfra-monitorctl restore --from /var/backups/bw-monitor/YYYYMMDD-HHMMSS --yes
```


## Storage V2 exact 5-minute history

> Storage V2 requires the pinned Community image `timescale/timescaledb:2.27.2-pg17`. Do not use the `-oss` tag because V2 depends on Timescale background retention and compression policy APIs.


The current release uses three Timescale hypertables without changing the existing current-state, Abuse, Storage I/O or Consumption tables:

| Table | Purpose | Retention |
|---|---|---:|
| `vm_chart_5m` | One compact VM chart row for every real 5-minute push | 7 days |
| `vm_raw_detail_5m` | N-interface raw counters, bridge/role mapping and sample diagnostics | 48 hours |
| `node_chart_5m` | Exact node/host chart point for every real 5-minute push | 7 days |

The existing compressed payload on `node_push_snapshots` remains the authoritative historical source for N-disk Storage I/O. This avoids duplicating every disk into another high-volume table while preserving the current Storage pages.

The V2 chart readers are enabled by default on a fresh installation. The previous chart readers stay available as a code fallback:

```bash
virtinfra-monitorctl storage-v2
virtinfra-monitorctl rollback-storage-v2
```

The rollback command only sets `VIRTINFRA_READ_CHART_V2=0` and restarts `bw-monitor.service`. It does not delete V2 rows or restore the database.

The migration is idempotent and installs background Timescale retention jobs. The V2 retention path does not use a periodic multi-million-row delete for these three tables.
