# SOURCE OF TRUTH VẬN HÀNH

> Release: `50.5.6-prod-r1-postgres-native-maintenance`

> Release: `50.5.6-prod-r1-postgres-native-maintenance`
>
> Tài liệu này được đối chiếu trực tiếp với `install.sh`, `deploy/postgres/*`, `deploy/agent/*`, `postgres/docker-compose.yml`, `app/app.py` và các test contract hiện tại.

## 1. Data plane hiện tại

VirtInfra Monitor dùng duy nhất:

```text
PostgreSQL 17
└─ TimescaleDB extension
```

Thông số mặc định:

```text
Container:       bw-timescaledb
Image:           timescale/timescaledb:2.27.2-pg17
Database:        bw_monitor
User:            bw_monitor
Host bind:       127.0.0.1:55432
Container port:  5432
Docker volume:   bw_monitor_postgres_data
PGDATA:          /var/lib/postgresql/data/pgdata
Database TZ:     UTC
```

Dữ liệu chính nằm trong Docker volume `bw_monitor_postgres_data`. Không có database file cục bộ nào cần copy, compact hoặc restore trực tiếp.

Kiểm tra volume:

```bash
docker volume inspect bw_monitor_postgres_data
```

Kiểm tra listener:

```bash
ss -lntp | grep ':55432'
```

Kỳ vọng PostgreSQL chỉ bind `127.0.0.1`.

## 2. Web stack

Domain mode:

```text
Internet
→ Nginx :80/:443
→ Gunicorn 127.0.0.1:8080
→ PostgreSQL 127.0.0.1:55432
```

IP mode:

```text
Internet
→ Gunicorn 0.0.0.0:8080
→ PostgreSQL 127.0.0.1:55432
```

Port web mặc định là `8080`, thay đổi bằng `--port`.

## 3. Service và timer được installer tạo

Web:

```text
bw-monitor.service
alias: virtinfra-monitor.service
```

Retention:

```text
bw-monitor-retention.service
bw-monitor-retention.timer
```

Lịch mặc định:

```text
00:20
06:20
12:20
18:20
RandomizedDelaySec tối đa 20 phút
```

Backup:

```text
bw-monitor-backup.service
bw-monitor-backup.timer
```

Lịch mặc định:

```text
02:20 hằng ngày
RandomizedDelaySec tối đa 15 phút
```

Health watchdog:

```text
virtinfra-monitor-health-watch.service
virtinfra-monitor-health-watch.timer
```

Chu kỳ mặc định:

```text
30 giây
```

Container:

```text
Docker service: docker.service
Database container: bw-timescaledb
```

## 4. Path production

Ứng dụng:

```text
/opt/bw-monitor
/opt/bw-monitor/app.py
/opt/bw-monitor/bw_pg.py
/opt/bw-monitor/maintenance.py
/opt/bw-monitor/retention.py
/opt/bw-monitor/start-monitor.sh
/opt/bw-monitor/venv
/opt/bw-monitor/DEPLOY_VERSION
```

Cấu hình:

```text
/etc/default/bw-monitor
/etc/default/bw-monitor-postgres
/root/bw-monitor-credentials.env
```

Backup:

```text
/var/backups/bw-monitor/YYYYMMDD-HHMMSS
```

Nginx:

```text
/etc/nginx/sites-available/bw-monitor.conf
/etc/nginx/sites-enabled/bw-monitor.conf
```

CLI:

```text
/usr/local/sbin/virtinfra-monitorctl
/usr/local/sbin/bw-monitorctl
/usr/local/sbin/virtinfra-monitor-doctor
/usr/local/sbin/bw-monitor-doctor
```

## 5. Environment Monitor

File:

```text
/etc/default/bw-monitor
```

Biến quan trọng:

```text
BW_DATABASE_URL
BW_POSTGRES_DSN
BW_MONITOR_TOKEN
BW_ADMIN_USERNAME
BW_ADMIN_PASSWORD_HASH
BW_ADMIN_SECRET_KEY
BW_PUBLIC_URL
BW_PUSH_URL
BW_DOMAIN
BW_PUBLIC_IP
BW_PUBLIC_PORT
BW_GITHUB_REPO
BW_GITHUB_REF
BW_RAW_RETENTION_DAYS
BW_HOURLY_RETENTION_DAYS
BW_PAGE_CACHE_ENABLED
BW_DB_POOL_MIN
BW_DB_POOL_MAX
BW_GUNICORN_BIND
BW_GUNICORN_WORKERS
BW_GUNICORN_THREADS
```

Không `cat` toàn bộ file này vào ticket/chat vì có secret.

Xem biến không nhạy cảm:

```bash
grep -E '^(BW_MONITOR_RELEASE|BW_PUBLIC_URL|BW_PUSH_URL|BW_DOMAIN|BW_PUBLIC_IP|BW_PUBLIC_PORT|BW_GITHUB_REPO|BW_GITHUB_REF|BW_RAW_RETENTION_DAYS|BW_HOURLY_RETENTION_DAYS|BW_GUNICORN_BIND|BW_GUNICORN_WORKERS|BW_GUNICORN_THREADS)=' /etc/default/bw-monitor
```

## 6. Environment PostgreSQL

File:

```text
/etc/default/bw-monitor-postgres
```

Biến quan trọng:

```text
BW_PG_PORT
BW_PG_USER
BW_PG_DATABASE
BW_PG_PASSWORD
BW_TIMESCALE_IMAGE
BW_PG_SHARED_BUFFERS
BW_PG_EFFECTIVE_CACHE_SIZE
BW_PG_MAINTENANCE_WORK_MEM
BW_PG_WORK_MEM
BW_PG_MAX_CONNECTIONS
```

Không đưa file này lên GitHub hoặc gửi công khai vì có password.

## 7. Retention hiện tại

Operational metrics:

```text
0 đến 48 giờ
→ giữ real push 5 phút

48 giờ đến 7 ngày
→ giữ một real push mỗi giờ

Quá 7 ngày
→ xóa history/log/event theo policy
```

Consumption:

```text
Bucket: 2 giờ
Retention: 7 ngày
Quá 7 ngày: xóa tự động
```

Timer retention chạy mỗi 6 giờ. `virtinfra-monitorctl retention` chạy ngay rồi follow log, bấm `Ctrl + C` sau khi job hoàn tất.

## 8. Consumption

Visible label:

```text
Consumption
```

Route:

```text
/bandwidth-consumption
```

Node detail:

```text
/bandwidth-consumption/node/<node>
```

Agent endpoint:

```text
/push/bandwidth-consumption
```

Table:

```text
node_bandwidth_consumption_2h
```

Mỗi row chứa:

```text
node
bucket_start
bucket_end
physical_public_rx_bytes
physical_public_tx_bytes
physical_private_rx_bytes
physical_private_tx_bytes
vm_public_rx_bytes
vm_public_tx_bytes
vm_private_rx_bytes
vm_private_tx_bytes
coverage_seconds
sample_count
estimated
agent_version
received_at
```

Không lưu UUID VM trong module này.

Public và Private tách riêng. Physical và tổng VM tách riêng. `TOTAL` chỉ là RX + TX trong cùng nhóm.

Monitor dùng khóa `(node, bucket_start)` và UPSERT, nên Agent retry không nhân đôi bucket.

Full reset tạo `bandwidth_consumption_accept_after`. Bucket cũ còn trong retry local được acknowledge nhưng bỏ qua, nên history đã reset không xuất hiện lại.

Hide Node làm node biến mất khỏi list, search, summary và detail nhưng không xóa history. Purge Node xóa history của node.

## 9. Agent runtime

Service:

```text
virtinfra-agent.service
```

Path:

```text
/usr/local/lib/virtinfra-agent/agent.py
/etc/virtinfra-agent.env
/var/lib/virtinfra-agent/state.json
/var/lib/virtinfra-agent/runtime.json
/usr/local/sbin/virtinfra-agent-doctor
```

Mặc định:

```text
Local sample: 15 giây
Operational push: 300 giây
Consumption bucket: 2 giờ
Consumption jitter: tối đa 240 giây
Bridge roles: public:br0,private:br1
```

Cập nhật Agent bình thường không dùng `--reset-state`.

## 10. Backup và restore

Backup dùng:

```text
pg_dump --format=custom
pg_restore --list
SHA256SUMS
```

Bundle tối thiểu:

```text
database.dump
database.list
metadata.txt
SHA256SUMS
```

Khi tồn tại, backup còn copy file env, credentials, Nginx config và deployed version.

Restore mặc định chỉ restore PostgreSQL/TimescaleDB data. `--with-config` mới restore config từ bundle.

Restore luôn tạo pre-restore backup trước khi thay database hiện tại.

## 11. Optional Redis

Redis chỉ được cài khi dùng:

```bash
--redis-cache
```

Redis chỉ là page cache tùy chọn. PostgreSQL vẫn là nguồn dữ liệu duy nhất.

## 12. Quy tắc vận hành

Được dùng online:

```bash
virtinfra-monitorctl backup
virtinfra-monitorctl db-check
virtinfra-monitorctl retention
virtinfra-monitorctl vacuum
```

Không chạy `VACUUM FULL` trong giờ production.

Không xóa `bw_monitor_postgres_data` khi chưa có backup đã verify.

Không mở port `55432` ra Internet.

Không commit credentials, env production, inventory thật, private key, Agent token, PostgreSQL dump hoặc backup bundle.
