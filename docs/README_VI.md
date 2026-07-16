# Hướng dẫn đầy đủ VirtInfra Monitor v50

> Bộ hướng dẫn production mới:
>
> - [`../START_HERE_VI.md`](../START_HERE_VI.md)
> - [`../GITHUB_DESKTOP_VI.md`](../GITHUB_DESKTOP_VI.md)
> - [`../COMMANDS_A_TO_Z_VI.md`](../COMMANDS_A_TO_Z_VI.md)


VirtInfra Monitor v50 giữ nguyên toàn bộ giao diện và chức năng của code production cũ, nhưng runtime chỉ dùng **một PostgreSQL 17 + TimescaleDB database**. Không có database thứ hai để đồng bộ, không có dữ liệu chính trong Redis, không cần migrate dữ liệu cũ khi cài server mới.

## 1. Luồng thật của Agent

```text
Mỗi 15 giây
Agent đọc counter VM/network cục bộ
        │
        ▼
Gom trong cửa sổ 5 phút
        │
        ▼
Mỗi 300 giây
Gửi một payload bền vững tới /push
        │
        ▼
Monitor ghi current + history + Abuse state vào PostgreSQL
```

Agent có pending payload trên node. Nếu Monitor tạm lỗi, Agent retry đúng payload cũ. Monitor chống ghi trùng bằng `node + push_time`.

## 2. Retention đúng theo code cũ

```text
0 → 48 giờ
giữ mọi push thật 5 phút

48 giờ → 7 ngày
giữ một snapshot thật đã đồng bộ mỗi giờ

trên 7 ngày
xóa history/log/event cũ theo batch
```

Node/VM hiện tại, user, API key, cấu hình và active Abuse không bị retention xóa.

## 3. Database

```text
PostgreSQL 17
└─ TimescaleDB extension
   ├─ user / settings / API key
   ├─ node / VM inventory
   ├─ current metrics
   ├─ VM disk / node storage
   ├─ current Abuse / Abuse Events
   ├─ maintenance queue / audit log
   └─ history 5 phút / hourly / billing rollup
```

TimescaleDB nằm ngay trong PostgreSQL, không phải một database riêng. PostgreSQL chỉ bind ở `127.0.0.1:55432`, không mở ra Internet.

Redis mặc định tắt. Khi bật `--redis-cache`, Redis chỉ cache page ngắn hạn. Xóa Redis không mất Node, VM, Abuse, history, user hoặc cấu hình.

## 4. Cài Monitor mới bằng IP

```bash
apt-get update
apt-get install -y curl ca-certificates tar

curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/install.sh \
| bash -s -- \
--public-ip 45.92.158.124 \
--port 8080
```

Mở:

```text
http://45.92.158.124:8080
```

Kiểm tra:

```bash
virtinfra-monitorctl status
virtinfra-monitorctl doctor
virtinfra-monitorctl urls
```

Xem tài khoản và Agent token:

```bash
virtinfra-monitorctl credentials
```

## 5. Cài bằng domain + HTTPS

Tạo DNS trước:

```text
A  monitor.example.com  →  IP Monitor
```

Mở TCP 80 và 443, sau đó:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/install.sh \
| bash -s -- \
--domain monitor.example.com \
--email ops@example.com
```

Mở:

```text
https://monitor.example.com/
https://monitor.example.com/admin
https://monitor.example.com/enterprise
```

Agent endpoint:

```text
https://monitor.example.com/push
```

## 6. Cài Agent từ máy Ansible riêng

Repo trên máy Ansible:

```text
/.data/agent
```

```bash
cd /.data/agent
git pull --ff-only

read -rsp 'Nhập VirtInfra Agent token: ' BW_TOKEN
echo

bash ansible/deploy-agent.sh \
  -i ansible/test.txt \
  --api 'https://monitor.example.com/push' \
  --token "$BW_TOKEN" \
  --forks 20 \
  --serial 10

unset BW_TOKEN
```

Kiểm tra:

```bash
ansible all \
-i ansible/test.txt \
-m shell \
-a '
systemctl is-active virtinfra-agent.service
systemctl show virtinfra-agent.service -p ProtectHome --value
' \
--forks 20
```

Kết quả:

```text
active
read-only
```

## 7. Quản trị

```bash
virtinfra-monitorctl help
virtinfra-monitorctl status
virtinfra-monitorctl doctor
virtinfra-monitorctl audit
virtinfra-monitorctl db-check
virtinfra-monitorctl logs all 200
virtinfra-monitorctl follow monitor
virtinfra-monitorctl restart
virtinfra-monitorctl retention
virtinfra-monitorctl vacuum
virtinfra-monitorctl psql
virtinfra-monitorctl backup
virtinfra-monitorctl diagnostics
virtinfra-monitorctl update
```

## 8. Backup

```bash
virtinfra-monitorctl backup
```

Mỗi backup có:

```text
database.dump
PostgreSQL environment
Monitor environment
credentials
Nginx site nếu có
version
metadata
SHA256SUMS
```

Redis không cần backup vì không phải nguồn dữ liệu.

## 9. Restore

```bash
virtinfra-monitorctl restore \
--from /var/backups/bw-monitor/20260715-050000 \
--yes
```

Giữ config server mới, chỉ restore DB.

Restore cả config:

```bash
virtinfra-monitorctl restore \
--from /var/backups/bw-monitor/20260715-050000 \
--with-config \
--yes
```

## 10. Update

```bash
virtinfra-monitorctl update
```

Hoặc:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/update.sh \
| bash
```

## 11. Đổi IP sang domain

```bash
virtinfra-monitorctl domain set \
monitor.example.com \
ops@example.com
```

## 12. Đổi domain về IP

```bash
virtinfra-monitorctl domain remove \
45.92.158.124 \
8080
```

## 13. Path production

```text
App:                 /opt/bw-monitor
PostgreSQL env:      /etc/default/bw-monitor-postgres
Monitor env:         /etc/default/bw-monitor
Credentials:         /root/bw-monitor-credentials.env
Database volume:     bw_monitor_postgres_data
Backup:              /var/backups/bw-monitor
Nginx site:          /etc/nginx/sites-available/bw-monitor.conf
Systemd web alias:   virtinfra-monitor.service (compatibility unit: bw-monitor.service)
Retention timer:     bw-monitor-retention.timer
Backup timer:        bw-monitor-backup.timer
```

## 14. Khi có lỗi

```bash
virtinfra-monitorctl doctor
virtinfra-monitorctl logs all 300
virtinfra-monitorctl db-check

docker ps --filter name=bw-timescaledb
docker logs --tail 300 bw-timescaledb

systemctl status virtinfra-monitor.service --no-pager -l
journalctl -u virtinfra-monitor.service -n 300 --no-pager
```

Không xóa Docker volume khi chưa backup. Không đưa `/root/bw-monitor-credentials.env`, file env, inventory thật hoặc private key lên Git.
