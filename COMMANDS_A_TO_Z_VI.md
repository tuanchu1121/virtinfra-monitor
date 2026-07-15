# VirtInfra Monitor - Toàn bộ command triển khai và bảo trì từ A đến Z

> Release: `50.4.0-prod-r1-storage-v2`
>
> Chạy command Monitor bằng `root`. Với node KVM, chạy Agent bằng `root` để Agent đọc được libvirt, interface, disk và host metrics.

---

# DATABASE CONTRACT CỦA SOURCE HIỆN TẠI

```text
PostgreSQL 17 + TimescaleDB
Container: bw-timescaledb
Database: bw_monitor
Volume: bw_monitor_postgres_data
Host bind: 127.0.0.1:55432
Backup: pg_dump custom format
Restore: pg_restore
```

Không có database file cục bộ để backup, compact hoặc restore. Toàn bộ command database trong guide này đi qua PostgreSQL/TimescaleDB.

Xem kiến trúc đầy đủ tại [`SOURCE_OF_TRUTH_VI.md`](SOURCE_OF_TRUTH_VI.md).

# MỤC LỤC

1. Biến cần thay trước khi copy command
2. Deploy bản fix/update lên Monitor đang chạy
3. Cài Monitor mới bằng IP
4. Cài Monitor mới bằng domain HTTPS
5. Kiểm tra Monitor sau cài/update
6. Toàn bộ lệnh `virtinfra-monitorctl`
7. Cài Agent thủ công trên một node
8. Xác định bridge Public/Private trước khi cài Agent
9. Kiểm tra Agent đầy đủ
10. Update Agent thủ công
11. Reset state Agent khi thật sự cần
12. Gỡ Agent
13. Deploy/update Agent hàng loạt bằng Ansible
14. Kiểm tra Agent hàng loạt bằng Ansible
15. Consumption: kiểm tra dữ liệu, bucket và retention
16. Bảo trì hằng ngày, tuần và trước update
17. Log và theo dõi realtime
18. PostgreSQL/TimescaleDB
19. Backup
20. Restore
21. Domain, Nginx và TLS
22. Retention, VACUUM và dung lượng DB
23. Diagnostics bundle
24. Troubleshooting Monitor
25. Troubleshooting Agent
26. Rollback source và rollback dữ liệu
27. Các path production
28. Checklist bảo mật
29. Khối command nhanh để copy

---

# 1. Biến cần thay trước khi copy command

Trong tài liệu này:

```text
DOMAIN-CUA-M
```

thay bằng domain thật, ví dụ:

```text
monitor.example.com
```

```text
IP-MONITOR
```

thay bằng IP Monitor thật.

```text
TOKEN_AGENT
```

không ghi thẳng vào lịch sử shell. Dùng `read -rsp` như các ví dụ bên dưới.

Bridge mặc định:

```text
br0 = Public
br1 = Private
```

Nếu node dùng tên khác, thay đúng tên thật.

---

# 2. Deploy bản fix/update lên Monitor đang chạy

## 2.1 Kiểm tra GitHub đã có đúng version

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/VERSION
```

Kết quả mong đợi:

```text
50.4.0-prod-r1-storage-v2
```

## 2.2 Update chuẩn, có backup trước

```bash
virtinfra-monitorctl backup && \
virtinfra-monitorctl update && \
systemctl restart bw-monitor.service && \
virtinfra-monitorctl doctor && \
virtinfra-monitorctl version
```

Kiểm tra tiếp:

```bash
virtinfra-monitorctl status
virtinfra-monitorctl health
virtinfra-monitorctl urls
```

## 2.3 Update trực tiếp từ GitHub khi command update không kéo bản mới

```bash
export BW_GITHUB_REPO='tuanchu1121/bw-monitor-production.1'
export BW_GITHUB_REF='main'

curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/update.sh \
| bash

unset BW_GITHUB_REPO
unset BW_GITHUB_REF
```

Sau đó:

```bash
systemctl restart bw-monitor.service
virtinfra-monitorctl doctor
virtinfra-monitorctl version
```

## 2.4 Kiểm tra Monitor đang trỏ đúng repo/ref

```bash
grep -E '^BW_GITHUB_(REPO|REF)=' \
/etc/default/bw-monitor
```

Kỳ vọng:

```text
BW_GITHUB_REPO=tuanchu1121/bw-monitor-production.1
BW_GITHUB_REF=main
```

## 2.5 Mở giao diện sau update

```text
https://DOMAIN-CUA-M/
```

Trang Consumption:

```text
https://DOMAIN-CUA-M/bandwidth-consumption
```

Trên trình duyệt:

```text
Ctrl + F5
```

Bản `50.4.0` không đổi Agent protocol, payload, endpoint hoặc chu kỳ nên không bắt buộc update Agent chỉ để dùng Storage V2.

---

# 3. Cài Monitor mới bằng IP

Hệ điều hành hỗ trợ:

```text
Debian 12+
Ubuntu 22.04+
```

Cài dependency bootstrap:

```bash
apt-get update
apt-get install -y curl ca-certificates tar
```

Cài:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/install.sh \
| bash -s -- \
--public-ip IP-MONITOR \
--port 8080
```

Mở:

```text
http://IP-MONITOR:8080
```

Kiểm tra:

```bash
virtinfra-monitorctl version
virtinfra-monitorctl urls
virtinfra-monitorctl credentials
virtinfra-monitorctl doctor
virtinfra-monitorctl status
```

File credentials:

```text
/root/bw-monitor-credentials.env
```

Chỉ root được đọc.

---

# 4. Cài Monitor mới bằng domain HTTPS

## 4.1 Chuẩn bị DNS

Tạo A record:

```text
monitor.example.com → IP Monitor
```

Kiểm tra:

```bash
dig +short monitor.example.com A
```

Mở TCP 80 và 443 trên firewall/provider firewall.

## 4.2 Cài

```bash
apt-get update
apt-get install -y curl ca-certificates tar

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
```

Agent push URL:

```text
https://monitor.example.com/push
```

## 4.3 Cài và bật UFW qua installer

Ví dụ SSH port `1812`:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/install.sh \
| bash -s -- \
--domain monitor.example.com \
--email ops@example.com \
--firewall \
--ssh-port 1812
```

Không dùng `--firewall` khi chưa chắc SSH port đã đúng, tránh tự khóa SSH.

---

# 5. Kiểm tra Monitor sau cài/update

Chạy nguyên khối:

```bash
virtinfra-monitorctl version
virtinfra-monitorctl urls
virtinfra-monitorctl status
virtinfra-monitorctl health
virtinfra-monitorctl doctor
virtinfra-monitorctl db-check
```

Health local thủ công:

```bash
curl -fsS http://127.0.0.1:8080/livez
echo
curl -fsS http://127.0.0.1:8080/healthz
echo
```

Kiểm tra login local:

```bash
curl -I http://127.0.0.1:8080/login
```

HTTP `200` hoặc `302` là bình thường tùy route/session.

---

# 6. Toàn bộ lệnh virtinfra-monitorctl

Xem help:

```bash
virtinfra-monitorctl help
```

## Service và health

```bash
virtinfra-monitorctl status
virtinfra-monitorctl health
virtinfra-monitorctl doctor
virtinfra-monitorctl audit
virtinfra-monitorctl restart
```

## Database

```bash
virtinfra-monitorctl db-check
virtinfra-monitorctl psql
virtinfra-monitorctl vacuum
```

## Log

```bash
virtinfra-monitorctl logs monitor 300
virtinfra-monitorctl logs retention 300
virtinfra-monitorctl logs postgres 300
virtinfra-monitorctl logs all 300
```

Theo dõi realtime:

```bash
virtinfra-monitorctl follow monitor
```

```bash
virtinfra-monitorctl follow retention
```

```bash
virtinfra-monitorctl follow postgres
```

Thoát follow bằng:

```text
Ctrl + C
```

## Backup/restore

```bash
virtinfra-monitorctl backup
```

```bash
virtinfra-monitorctl restore \
--from /var/backups/bw-monitor/YYYYMMDD-HHMMSS \
--yes
```

## Maintenance

```bash
virtinfra-monitorctl retention
virtinfra-monitorctl vacuum
```

## Thông tin

```bash
virtinfra-monitorctl credentials
virtinfra-monitorctl urls
virtinfra-monitorctl version
```

## Update

```bash
virtinfra-monitorctl update
```

## Domain

```bash
virtinfra-monitorctl domain status
```

```bash
virtinfra-monitorctl domain set \
monitor.example.com \
ops@example.com
```

```bash
virtinfra-monitorctl domain remove \
IP-MONITOR \
8080
```

## Diagnostics

```bash
virtinfra-monitorctl diagnostics
```

---

# 7. Cài Agent thủ công trên một node

## 7.1 Kiểm tra dependency và libvirt

```bash
id
command -v python3
command -v virsh
command -v ip
command -v df
command -v systemctl
```

Kiểm tra libvirt:

```bash
virsh list --all
```

Nếu node dùng modular libvirt, service có thể là `virtqemud`. Agent chỉ cần `virsh` hoạt động.

## 7.2 Cài Agent theo cách khuyến nghị

Ví dụ:

```text
br0 = Public
br1 = Private
```

Chạy:

```bash
read -rsp 'Nhap VirtInfra Agent token: ' BW_TOKEN
echo

curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/install-agent.sh \
| env \
VIRTINFRA_AGENT_API='https://DOMAIN-CUA-M/push' \
VIRTINFRA_AGENT_TOKEN="$BW_TOKEN" \
BW_AGENT_BRIDGE_ROLES='public:br0,private:br1' \
bash

unset BW_TOKEN
```

Nếu Monitor chạy IP:

```bash
read -rsp 'Nhap VirtInfra Agent token: ' BW_TOKEN
echo

curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/install-agent.sh \
| env \
VIRTINFRA_AGENT_API='http://IP-MONITOR:8080/push' \
VIRTINFRA_AGENT_TOKEN="$BW_TOKEN" \
BW_AGENT_BRIDGE_ROLES='public:br0,private:br1' \
bash

unset BW_TOKEN
```

## 7.3 Cách dùng tham số trực tiếp

Không ghi token literal vào command. Vẫn nhập ẩn:

```bash
read -rsp 'Nhap VirtInfra Agent token: ' BW_TOKEN
echo

curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/install-agent.sh \
| bash -s -- \
--api 'https://DOMAIN-CUA-M/push' \
--token "$BW_TOKEN" \
--bridge-roles 'public:br0,private:br1'

unset BW_TOKEN
```

## 7.4 Tùy chỉnh sample/push khi thật sự cần

Mặc định production:

```text
sample = 15 giây
push = 300 giây
```

Không nên đổi nếu không có lý do rõ ràng.

Ví dụ giữ đúng mặc định:

```bash
read -rsp 'Nhap VirtInfra Agent token: ' BW_TOKEN
echo

curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/install-agent.sh \
| bash -s -- \
--api 'https://DOMAIN-CUA-M/push' \
--token "$BW_TOKEN" \
--sample-seconds 15 \
--push-seconds 300 \
--bridge-roles 'public:br0,private:br1'

unset BW_TOKEN
```

---

# 8. Xác định bridge Public/Private trước khi cài Agent

Liệt kê interface:

```bash
ip -br link
```

Liệt kê bridge:

```bash
ip -d link show type bridge
```

Hoặc:

```bash
bridge link
```

Xem VM đang nối vào bridge nào:

```bash
virsh list --name
```

Chọn một VM rồi:

```bash
virsh domiflist TEN-VM
```

Xem toàn bộ VM đang chạy:

```bash
for vm in $(virsh list --name); do
  echo "===== $vm ====="
  virsh domiflist "$vm"
done
```

Ví dụ:

```text
br0 = uplink/public
br1 = private network
```

thì dùng:

```text
public:br0,private:br1
```

Nếu node dùng:

```text
vmbr0 = Public
vmbr1 = Private
```

thì dùng:

```text
public:vmbr0,private:vmbr1
```

Nhiều bridge cùng role:

```text
public:br0,vmbr0,private:br1,vmbr1
```

Không gán cùng một bridge vào cả Public và Private.

---

# 9. Kiểm tra Agent đầy đủ

## 9.1 Doctor

```bash
virtinfra-agent-doctor
```

Doctor kiểm tra:

```text
Source Agent
Python compile
Service active/enabled
Mode file env 0600
API/sample/push/bridge role
virsh
Consumption pending/partial/last bucket
Recent journal
```

## 9.2 Service

```bash
systemctl is-active virtinfra-agent.service
systemctl is-enabled virtinfra-agent.service
```

Kỳ vọng:

```text
active
enabled
```

Chi tiết:

```bash
systemctl status \
virtinfra-agent.service \
--no-pager \
-l
```

## 9.3 Log

```bash
journalctl \
-u virtinfra-agent.service \
-n 200 \
--no-pager
```

Theo dõi realtime:

```bash
journalctl \
-fu virtinfra-agent.service
```

## 9.4 Kiểm tra config nhưng không in token

```bash
grep -E \
'^(VIRTINFRA_AGENT_API|VIRTINFRA_AGENT_SAMPLE_SECONDS|VIRTINFRA_AGENT_PUSH_SECONDS|BW_AGENT_BRIDGE_ROLES|BW_AGENT_BANDWIDTH_CONSUMPTION_ENABLED|BW_AGENT_BANDWIDTH_CONSUMPTION_JITTER_SECONDS)=' \
/etc/virtinfra-agent.env
```

Kỳ vọng:

```text
VIRTINFRA_AGENT_SAMPLE_SECONDS='15'
VIRTINFRA_AGENT_PUSH_SECONDS='300'
BW_AGENT_BANDWIDTH_CONSUMPTION_ENABLED='1'
BW_AGENT_BANDWIDTH_CONSUMPTION_JITTER_SECONDS='240'
```

## 9.5 Kiểm tra systemd hardening

```bash
systemctl show \
virtinfra-agent.service \
-p ProtectHome \
--value
```

Kỳ vọng:

```text
read-only
```

## 9.6 Kiểm tra state

```bash
ls -lah \
/var/lib/virtinfra-agent/
```

```bash
python3 -m json.tool \
/var/lib/virtinfra-agent/runtime.json \
| head -200
```

Không sửa tay `state.json` hoặc `runtime.json` khi service đang chạy.

## 9.7 Kiểm tra kết nối tới Monitor

```bash
curl -I \
--connect-timeout 10 \
--max-time 20 \
https://DOMAIN-CUA-M/login
```

Kiểm tra DNS:

```bash
getent hosts DOMAIN-CUA-M
```

Kiểm tra thời gian:

```bash
timedatectl status
```

---

# 10. Update Agent thủ công

Chạy lại đúng command cài. Installer sẽ stop Agent cũ, thay source, giữ state và start lại.

```bash
read -rsp 'Nhap VirtInfra Agent token: ' BW_TOKEN
echo

curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/install-agent.sh \
| env \
VIRTINFRA_AGENT_API='https://DOMAIN-CUA-M/push' \
VIRTINFRA_AGENT_TOKEN="$BW_TOKEN" \
BW_AGENT_BRIDGE_ROLES='public:br0,private:br1' \
bash

unset BW_TOKEN
```

Sau update:

```bash
virtinfra-agent-doctor
systemctl status virtinfra-agent.service --no-pager -l
```

Không dùng:

```text
--reset-state
```

trong update bình thường, vì sẽ xóa counter/runtime hiện tại và làm bucket Consumption đầu tiên bị partial lại.

---

# 11. Reset state Agent khi thật sự cần

Chỉ dùng khi state JSON bị hỏng, counter sai không thể tự hồi phục hoặc đã được xác nhận cần baseline mới.

Cảnh báo:

```text
Xóa state hiện tại
Mất pending payload chưa gửi
Consumption bucket hiện tại sẽ bắt đầu lại
Bucket đầu sau reset có thể Partial/Incomplete
```

Command:

```bash
read -rsp 'Nhap VirtInfra Agent token: ' BW_TOKEN
echo

curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/install-agent.sh \
| bash -s -- \
--api 'https://DOMAIN-CUA-M/push' \
--token "$BW_TOKEN" \
--bridge-roles 'public:br0,private:br1' \
--reset-state

unset BW_TOKEN
```

---

# 12. Gỡ Agent

## 12.1 Gỡ nhưng giữ state

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/uninstall-agent.sh \
| bash -s -- \
--keep-state
```

State giữ tại:

```text
/var/lib/virtinfra-agent/
```

## 12.2 Gỡ sạch cả state

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/uninstall-agent.sh \
| bash
```

Kiểm tra:

```bash
systemctl status virtinfra-agent.service --no-pager -l || true
ls -ld /usr/local/lib/virtinfra-agent /var/lib/virtinfra-agent 2>/dev/null || true
```

---

# 13. Deploy/update Agent hàng loạt bằng Ansible

## 13.1 Cài Ansible trên máy điều khiển

Debian/Ubuntu:

```bash
apt-get update
apt-get install -y \
ansible \
git \
python3
```

## 13.2 Repo trên máy Ansible

Ví dụ:

```bash
mkdir -p /.data
cd /.data
```

Nếu chưa clone:

```bash
git clone \
https://github.com/tuanchu1121/bw-monitor-production.1.git \
agent
```

Nếu đã có:

```bash
cd /.data/agent
git pull --ff-only origin main
```

## 13.3 Inventory

Ví dụ file:

```text
/.data/agent/test.txt
```

Nội dung:

```ini
[agents]
192.0.2.10 ansible_port=1812
192.0.2.11 ansible_port=1812

[agents:vars]
ansible_user=root
ansible_python_interpreter=/usr/bin/python3
```

## 13.4 Test SSH/Ansible

```bash
cd /.data/agent

ansible all \
-i test.txt \
-m ping \
-f 20
```

## 13.5 Deploy/update tất cả node

```bash
cd /.data/agent

git pull --ff-only origin main

read -rsp 'Nhap VirtInfra Agent token: ' BW_TOKEN
echo

bash ansible/deploy-agent.sh \
-i test.txt \
--api 'https://DOMAIN-CUA-M/push' \
--token "$BW_TOKEN" \
--forks 20 \
--serial 10

unset BW_TOKEN
```

## 13.6 Chỉ deploy một node hoặc một group

Ví dụ group:

```bash
bash ansible/deploy-agent.sh \
-i test.txt \
--api 'https://DOMAIN-CUA-M/push' \
--token "$BW_TOKEN" \
--limit 'EPYC_SG' \
--forks 20 \
--serial 10
```

Một IP:

```bash
bash ansible/deploy-agent.sh \
-i test.txt \
--api 'https://DOMAIN-CUA-M/push' \
--token "$BW_TOKEN" \
--limit '192.0.2.10' \
--forks 5 \
--serial 1
```

---

# 14. Kiểm tra Agent hàng loạt bằng Ansible

## 14.1 Active/enabled

```bash
cd /.data/agent

ansible all \
-i test.txt \
-m shell \
-a '
systemctl is-active virtinfra-agent.service
systemctl is-enabled virtinfra-agent.service
' \
-f 20
```

## 14.2 Kiểm tra cấu hình Consumption và bridge

```bash
ansible all \
-i test.txt \
-m shell \
-a '
grep -E "^(VIRTINFRA_AGENT_API|VIRTINFRA_AGENT_SAMPLE_SECONDS|VIRTINFRA_AGENT_PUSH_SECONDS|BW_AGENT_BRIDGE_ROLES|BW_AGENT_BANDWIDTH_CONSUMPTION_ENABLED|BW_AGENT_BANDWIDTH_CONSUMPTION_JITTER_SECONDS)=" /etc/virtinfra-agent.env
' \
-f 20
```

## 14.3 Chạy doctor trên toàn bộ node

```bash
ansible all \
-i test.txt \
-m shell \
-a 'virtinfra-agent-doctor' \
-f 10
```

## 14.4 Xem log node lỗi

```bash
ansible all \
-i test.txt \
--limit '192.0.2.10' \
-m shell \
-a '
journalctl -u virtinfra-agent.service -n 200 --no-pager
'
```

## 14.5 Gỡ Agent hàng loạt, giữ state

```bash
cd /.data/agent

bash ansible/remove-agent.sh \
-i test.txt \
--forks 20 \
--keep-state
```

## 14.6 Gỡ sạch Agent hàng loạt

```bash
bash ansible/remove-agent.sh \
-i test.txt \
--forks 20
```

---

# 15. Consumption: kiểm tra dữ liệu, bucket và retention

## 15.1 Hành vi đúng

Agent hiện tại:

```text
15 giây: sample local
5 phút: /push operational
2 giờ: /push/bandwidth-consumption
```

Mỗi bucket chỉ có tổng theo node:

```text
Physical Public RX/TX
Physical Private RX/TX
Aggregate VM Public RX/TX
Aggregate VM Private RX/TX
```

Không có UUID VM.

## 15.2 Sau khi cài Agent mới

Lần đầu Agent lấy baseline. Dữ liệu Consumption không xuất hiện ngay.

Ví dụ cài lúc `13:20`:

```text
13:20 → bắt đầu baseline/partial
14:00 → kết thúc phần bucket hiện tại
14:00–14:04 → có thể gửi do jitter
16:00–16:04 → bucket 14:00–16:00 đầy đủ đầu tiên
```

Bucket đầu có thể hiện:

```text
Partial
Incomplete Coverage
```

Đây là bình thường.

## 15.3 Kiểm tra Agent Consumption state

```bash
virtinfra-agent-doctor
```

Hoặc:

```bash
python3 - <<'PY'
import json
from pathlib import Path
p=Path('/var/lib/virtinfra-agent/runtime.json')
d=json.loads(p.read_text())
s=d.get('bandwidth_consumption') or {}
print('pending=', len(s.get('pending') or []))
print('partial_buckets=', len(s.get('buckets') or {}))
print('last_sent_bucket=', s.get('last_sent_bucket'))
PY
```

## 15.4 Kiểm tra bảng trên Monitor

```bash
virtinfra-monitorctl psql
```

Trong `psql`:

```sql
SELECT
    COUNT(*) AS rows,
    COUNT(DISTINCT node) AS nodes,
    to_timestamp(MIN(bucket_start)) AS oldest,
    to_timestamp(MAX(bucket_end)) AS newest,
    to_timestamp(MAX(received_at)) AS last_received
FROM node_bandwidth_consumption_2h;
```

Thoát:

```text
\q
```

## 15.5 Xem 20 bucket mới nhất

```sql
SELECT
    node,
    to_timestamp(bucket_start) AS bucket_start,
    to_timestamp(bucket_end) AS bucket_end,
    coverage_seconds,
    sample_count,
    estimated,
    to_timestamp(received_at) AS received_at
FROM node_bandwidth_consumption_2h
ORDER BY bucket_start DESC, node
LIMIT 20;
```

## 15.6 Xem dung lượng bảng

```sql
SELECT
    pg_size_pretty(
        pg_total_relation_size(
            'node_bandwidth_consumption_2h'
        )
    ) AS total_size;
```

## 15.7 Kiểm tra node nào mới gửi

```sql
SELECT
    node,
    COUNT(*) AS buckets,
    to_timestamp(MAX(bucket_end)) AS newest_bucket,
    to_timestamp(MAX(received_at)) AS last_received
FROM node_bandwidth_consumption_2h
GROUP BY node
ORDER BY MAX(received_at) DESC;
```

## 15.8 Cleanup

Dữ liệu quá 7 ngày được retention tự xóa.

Chạy retention thủ công:

```bash
virtinfra-monitorctl retention
```

Command sẽ theo dõi journal retention. Thoát bằng `Ctrl + C` sau khi thấy hoàn tất.

Trong Admin cũng có:

```text
Consumption
→ Run cleanup now
→ Clear history
```

`Reset ALL app data + queue` cũng xóa dữ liệu Consumption và đặt acceptance epoch để retry cũ từ Agent không làm dữ liệu sống lại.

---

# 16. Bảo trì hằng ngày, tuần và trước update

## 16.1 Hằng ngày

```bash
virtinfra-monitorctl doctor
virtinfra-monitorctl status
virtinfra-monitorctl health
```

Kiểm tra timer:

```bash
systemctl list-timers --all \
| grep -E 'bw-monitor|virtinfra'
```

Kiểm tra lỗi gần nhất:

```bash
journalctl \
-u bw-monitor.service \
-p warning \
-n 100 \
--no-pager
```

## 16.2 Hằng tuần

```bash
virtinfra-monitorctl db-check
virtinfra-monitorctl backup
```

Liệt kê backup:

```bash
find /var/backups/bw-monitor \
-mindepth 1 \
-maxdepth 1 \
-type d \
-printf '%TY-%Tm-%Td %TH:%TM %p\n' \
| sort
```

Kiểm tra dung lượng:

```bash
df -hT

du -sh \
/var/backups/bw-monitor \
/var/lib/docker \
/opt/bw-monitor \
2>/dev/null
```

## 16.3 Trước mọi update

```bash
virtinfra-monitorctl backup
virtinfra-monitorctl version
virtinfra-monitorctl doctor
```

Sau đó mới:

```bash
virtinfra-monitorctl update
virtinfra-monitorctl doctor
virtinfra-monitorctl version
```

## 16.4 Sau update

```bash
virtinfra-monitorctl status
virtinfra-monitorctl health
virtinfra-monitorctl logs monitor 200
```

Mở UI và `Ctrl + F5`.

---

# 17. Log và theo dõi realtime

Monitor:

```bash
journalctl \
-u bw-monitor.service \
-n 300 \
--no-pager
```

```bash
journalctl \
-fu bw-monitor.service
```

Retention:

```bash
journalctl \
-u bw-monitor-retention.service \
-n 300 \
--no-pager
```

PostgreSQL:

```bash
docker logs \
--tail 300 \
bw-timescaledb
```

Theo dõi PostgreSQL:

```bash
docker logs \
-f \
--tail 100 \
bw-timescaledb
```

Nginx:

```bash
journalctl \
-u nginx \
-n 200 \
--no-pager
```

```bash
tail -n 200 \
/var/log/nginx/error.log
```

Agent:

```bash
journalctl \
-u virtinfra-agent.service \
-n 300 \
--no-pager
```

---

# 18. PostgreSQL/TimescaleDB

## 18.1 Kiểm tra tổng quan

```bash
virtinfra-monitorctl db-check
```

## 18.2 Container

```bash
docker ps \
--filter name=bw-timescaledb
```

```bash
docker inspect \
bw-timescaledb \
--format '{{json .State.Health}}'
```

## 18.3 Mở psql

```bash
virtinfra-monitorctl psql
```

## 18.4 Kích thước DB

```sql
SELECT
    current_database(),
    pg_size_pretty(
        pg_database_size(
            current_database()
        )
    ) AS database_size;
```

## 18.5 Bảng lớn nhất

```sql
SELECT
    schemaname,
    relname,
    pg_size_pretty(
        pg_total_relation_size(
            quote_ident(schemaname) || '.' || quote_ident(relname)
        )
    ) AS total_size
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(
    quote_ident(schemaname) || '.' || quote_ident(relname)
) DESC
LIMIT 30;
```

## 18.6 Dead tuples/autovacuum

```sql
SELECT
    relname,
    n_live_tup,
    n_dead_tup,
    last_autovacuum,
    last_autoanalyze
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC
LIMIT 30;
```

## 18.7 VACUUM chuẩn

```bash
virtinfra-monitorctl vacuum
```

Đây là online `VACUUM/ANALYZE`, không rewrite toàn bộ file DB.

Không chạy tùy tiện:

```text
VACUUM FULL
```

vì có thể khóa bảng và cần thêm disk tạm.

---

# 19. Backup

## 19.1 Tạo backup

```bash
virtinfra-monitorctl backup
```

Kết quả trả về path, ví dụ:

```text
/var/backups/bw-monitor/20260715-193000
```

## 19.2 Xem nội dung

```bash
BACKUP='/var/backups/bw-monitor/20260715-193000'

ls -lah "$BACKUP"
```

Có:

```text
database.dump
database.list
metadata.txt
SHA256SUMS
protected config copies
```

## 19.3 Verify checksum

```bash
BACKUP='/var/backups/bw-monitor/20260715-193000'

cd "$BACKUP"
sha256sum -c SHA256SUMS
```

## 19.4 Copy backup sang server khác

Ví dụ SSH port 1812:

```bash
rsync -avhP \
-e 'ssh -p 1812' \
/var/backups/bw-monitor/20260715-193000/ \
root@IP-BACKUP:/backup/virtinfra/20260715-193000/
```

Nên có ít nhất một bản backup ngoài server Monitor.

---

# 20. Restore

## 20.1 Restore chỉ database

Giữ config hiện tại của Monitor:

```bash
virtinfra-monitorctl restore \
--from /var/backups/bw-monitor/20260715-193000 \
--yes
```

## 20.2 Restore cả database và config

```bash
virtinfra-monitorctl restore \
--from /var/backups/bw-monitor/20260715-193000 \
--with-config \
--yes
```

Cẩn thận khi restore config sang server khác, vì domain/IP/port có thể là của server cũ.

## 20.3 Kiểm tra sau restore

```bash
virtinfra-monitorctl doctor
virtinfra-monitorctl status
virtinfra-monitorctl health
virtinfra-monitorctl db-check
virtinfra-monitorctl urls
```

Kiểm tra UI.

Restore tự tạo pre-restore backup tại:

```text
/var/backups/bw-monitor/pre-restore-YYYYMMDD-HHMMSS
```

---

# 21. Domain, Nginx và TLS

## 21.1 Xem trạng thái domain

```bash
virtinfra-monitorctl domain status
```

## 21.2 Chuyển IP sang domain HTTPS

DNS phải trỏ trước.

```bash
virtinfra-monitorctl domain set \
monitor.example.com \
ops@example.com
```

## 21.3 Chuyển domain về IP

```bash
virtinfra-monitorctl domain remove \
IP-MONITOR \
8080
```

## 21.4 Kiểm tra Nginx

```bash
nginx -t
systemctl status nginx --no-pager -l
```

## 21.5 Kiểm tra certificate

```bash
certbot certificates
systemctl status certbot.timer --no-pager -l
```

## 21.6 Kiểm tra HTTPS

```bash
curl -I \
https://monitor.example.com/login
```

## 21.7 DNS

```bash
dig +short monitor.example.com A
dig +short monitor.example.com AAAA
dig +short monitor.example.com CAA
```

---

# 22. Retention, VACUUM và dung lượng DB

Retention tự động giữ:

```text
0–48 giờ: 5 phút
48 giờ–7 ngày: hourly snapshot
>7 ngày: xóa history/log/event giới hạn
Consumption >7 ngày: xóa
```

Chạy retention thủ công:

```bash
virtinfra-monitorctl retention
```

Xem timer:

```bash
systemctl status \
bw-monitor-retention.timer \
--no-pager \
-l
```

```bash
systemctl list-timers --all \
| grep bw-monitor-retention
```

Chạy VACUUM/ANALYZE:

```bash
virtinfra-monitorctl vacuum
```

Lưu ý: sau `DELETE`, file PostgreSQL không nhất thiết giảm ngay trên `du`. PostgreSQL thường giữ phần trống để tái sử dụng. Đây không đồng nghĩa cleanup thất bại.

---

# 23. Diagnostics bundle

Tạo bundle đã che secret chính:

```bash
virtinfra-monitorctl diagnostics
```

Kết quả dạng:

```text
/root/bw-monitor-diagnostics-YYYYMMDD-HHMMSS.tar.gz
```

Checksum:

```text
/root/bw-monitor-diagnostics-YYYYMMDD-HHMMSS.tar.gz.sha256
```

Luôn xem lại bundle trước khi gửi ra ngoài.

---

# 24. Troubleshooting Monitor

## 24.1 Khối kiểm tra đầu tiên

```bash
virtinfra-monitorctl version
virtinfra-monitorctl doctor
virtinfra-monitorctl status
virtinfra-monitorctl health
virtinfra-monitorctl logs all 300
virtinfra-monitorctl db-check
```

## 24.2 Internal Server Error

Xem traceback:

```bash
virtinfra-monitorctl logs monitor 500
```

Hoặc:

```bash
journalctl \
-u bw-monitor.service \
-n 500 \
--no-pager
```

Theo dõi khi bấm lại trang lỗi:

```bash
journalctl \
-fu bw-monitor.service
```

Sau khi đã push bản fix lên GitHub:

```bash
virtinfra-monitorctl backup && \
virtinfra-monitorctl update && \
systemctl restart bw-monitor.service && \
virtinfra-monitorctl doctor && \
virtinfra-monitorctl version
```

## 24.3 Service web không chạy

```bash
systemctl status \
bw-monitor.service \
--no-pager \
-l
```

```bash
journalctl \
-u bw-monitor.service \
-n 300 \
--no-pager
```

Restart:

```bash
virtinfra-monitorctl restart
```

## 24.4 Local health lỗi

```bash
curl -v \
http://127.0.0.1:8080/livez
```

```bash
curl -v \
http://127.0.0.1:8080/healthz
```

## 24.5 PostgreSQL lỗi

```bash
docker ps -a \
--filter name=bw-timescaledb
```

```bash
docker logs \
--tail 500 \
bw-timescaledb
```

```bash
cat /etc/default/bw-monitor-postgres
```

Không paste password thật ra ticket/public chat.

## 24.6 Nginx Bad Gateway

```bash
nginx -t
systemctl status nginx --no-pager -l
journalctl -u nginx -n 300 --no-pager
```

Kiểm tra upstream:

```bash
curl -I \
http://127.0.0.1:8080/login
```

Nếu local hoạt động nhưng domain 502, tập trung Nginx/TLS. Nếu local cũng lỗi, tập trung service web/PostgreSQL.

## 24.7 Update không đổi version

Kiểm tra GitHub raw:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/VERSION
```

Kiểm tra config repo/ref:

```bash
grep -E '^BW_GITHUB_(REPO|REF)=' \
/etc/default/bw-monitor
```

Force update theo mục 2.3.

---

# 25. Troubleshooting Agent

## 25.1 Agent không active

```bash
systemctl status \
virtinfra-agent.service \
--no-pager \
-l
```

```bash
journalctl \
-u virtinfra-agent.service \
-n 300 \
--no-pager
```

```bash
virtinfra-agent-doctor
```

## 25.2 Agent không xuất hiện trên Monitor

Kiểm tra API URL không in token:

```bash
grep '^VIRTINFRA_AGENT_API=' \
/etc/virtinfra-agent.env
```

Kiểm tra DNS/TLS:

```bash
curl -I \
https://DOMAIN-CUA-M/login
```

Kiểm tra giờ:

```bash
timedatectl status
```

Kiểm tra service/log. Agent operational push mặc định 5 phút, nên node mới có thể cần chờ đến push tiếp theo.

## 25.3 Unauthorized/token sai

Không in token ra terminal. Cài/update lại Agent bằng token đúng từ:

```bash
virtinfra-monitorctl credentials
```

Command này chạy trên Monitor. Sau đó dùng token qua `read -rsp` trên node/Ansible controller.

## 25.4 `/home` không hiện storage

```bash
systemctl show \
virtinfra-agent.service \
-p ProtectHome \
--value
```

Phải là:

```text
read-only
```

Nếu không đúng, redeploy Agent.

## 25.5 Consumption chưa có dữ liệu

Kiểm tra:

```bash
virtinfra-agent-doctor
```

```bash
grep -E \
'^(BW_AGENT_BRIDGE_ROLES|BW_AGENT_BANDWIDTH_CONSUMPTION_ENABLED|BW_AGENT_BANDWIDTH_CONSUMPTION_JITTER_SECONDS)=' \
/etc/virtinfra-agent.env
```

```bash
timedatectl status
```

Dữ liệu chỉ gửi sau khi hoàn thành bucket 2 giờ, cộng jitter tối đa 240 giây. Bucket đầu sau cài có thể partial.

## 25.6 Bridge sai

```bash
ip -br link
bridge link
virsh domiflist TEN-VM
```

Cài/update Agent lại với `--bridge-roles` đúng.

---

# 26. Rollback source và rollback dữ liệu

## 26.1 Rollback source bằng GitHub Desktop

Trong GitHub Desktop:

```text
History
→ chọn commit lỗi
→ Revert changes in commit
→ Push origin
```

Trên Monitor:

```bash
virtinfra-monitorctl backup
virtinfra-monitorctl update
virtinfra-monitorctl doctor
virtinfra-monitorctl version
```

## 26.2 Rollback DB

Chỉ dùng khi cần đưa dữ liệu về backup trước đó:

```bash
virtinfra-monitorctl restore \
--from /var/backups/bw-monitor/YYYYMMDD-HHMMSS \
--yes
```

Không restore DB chỉ vì lỗi CSS/template nếu dữ liệu không bị ảnh hưởng.

---

# 27. Các path production

Monitor:

```text
/opt/bw-monitor
/etc/default/bw-monitor
/etc/default/bw-monitor-postgres
/root/bw-monitor-credentials.env
/var/backups/bw-monitor
/etc/nginx/sites-available/bw-monitor.conf
```

Service:

```text
bw-monitor.service
bw-monitor-retention.timer
virtinfra-monitor-health-watch.timer
```

PostgreSQL:

```text
Docker container: bw-timescaledb
Loopback port mặc định: 55432
Docker volume: bw_monitor_postgres_data
```

Agent:

```text
/usr/local/lib/virtinfra-agent/agent.py
/etc/virtinfra-agent.env
/var/lib/virtinfra-agent/state.json
/var/lib/virtinfra-agent/runtime.json
/etc/systemd/system/virtinfra-agent.service
/usr/local/sbin/virtinfra-agent-doctor
```

---

# 28. Checklist bảo mật

Không đưa lên GitHub:

```text
Token Agent
Admin password/hash
PostgreSQL password
/root/bw-monitor-credentials.env
/etc/default/bw-monitor
/etc/default/bw-monitor-postgres
/etc/virtinfra-agent.env
inventory thật
SSH private key
TLS private key
Database dump
Diagnostics bundle chưa review
```

Quyền file cần chú ý:

```bash
stat -c '%a %U:%G %n' \
/root/bw-monitor-credentials.env \
/etc/default/bw-monitor \
/etc/default/bw-monitor-postgres \
/etc/virtinfra-agent.env \
2>/dev/null
```

Các file secret nên là `0600 root:root`.

---

# 29. Khối command nhanh để copy

## Update Monitor chuẩn

```bash
virtinfra-monitorctl backup && \
virtinfra-monitorctl update && \
systemctl restart bw-monitor.service && \
virtinfra-monitorctl doctor && \
virtinfra-monitorctl version
```

## Kiểm tra Monitor

```bash
virtinfra-monitorctl status
virtinfra-monitorctl health
virtinfra-monitorctl doctor
virtinfra-monitorctl db-check
virtinfra-monitorctl logs all 300
```

## Cài/update Agent thủ công

```bash
read -rsp 'Nhap VirtInfra Agent token: ' BW_TOKEN
echo

curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/install-agent.sh \
| env \
VIRTINFRA_AGENT_API='https://DOMAIN-CUA-M/push' \
VIRTINFRA_AGENT_TOKEN="$BW_TOKEN" \
BW_AGENT_BRIDGE_ROLES='public:br0,private:br1' \
bash

unset BW_TOKEN

virtinfra-agent-doctor
```

## Kiểm tra Agent

```bash
virtinfra-agent-doctor
systemctl status virtinfra-agent.service --no-pager -l
journalctl -u virtinfra-agent.service -n 200 --no-pager
```

## Deploy/update Agent bằng Ansible

```bash
cd /.data/agent
git pull --ff-only origin main

read -rsp 'Nhap VirtInfra Agent token: ' BW_TOKEN
echo

bash ansible/deploy-agent.sh \
-i test.txt \
--api 'https://DOMAIN-CUA-M/push' \
--token "$BW_TOKEN" \
--forks 20 \
--serial 10

unset BW_TOKEN
```

## Backup

```bash
virtinfra-monitorctl backup
```

## Retention và VACUUM

```bash
virtinfra-monitorctl retention
```

```bash
virtinfra-monitorctl vacuum
```

## Diagnostics

```bash
virtinfra-monitorctl diagnostics
```

## Restore

```bash
virtinfra-monitorctl restore \
--from /var/backups/bw-monitor/YYYYMMDD-HHMMSS \
--yes
```
