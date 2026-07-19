# BẮT ĐẦU TẠI ĐÂY - VirtInfra Monitor

> Release: `50.5.9-prod-r7-rbac-node-groups-node-vm-ui-refresh-hotfix-r1`

> Release: `50.5.9-prod-r3-ui-alignment-overflow-hotfix`
>
> Bản này giữ nguyên toàn bộ chức năng, route, giao diện, Agent, Abuse, Storage I/O và Consumption hiện tại; đồng thời bổ sung Storage V2 với chart đúng từng điểm 5 phút trong 7 ngày, raw interface 48 giờ, Timescale retention và rollback reader nhanh.

## Database contract của bản này

```text
PostgreSQL 17 + TimescaleDB là nguồn dữ liệu duy nhất
Container: bw-timescaledb
Volume: bw_monitor_postgres_data
Loopback: 127.0.0.1:55432
Backup: pg_dump custom format
Restore: pg_restore
```

Không có command vận hành theo database file cục bộ.

Đọc [`SOURCE_OF_TRUTH_VI.md`](SOURCE_OF_TRUTH_VI.md) trước khi sửa kiến trúc, path hoặc command.

Đây là đường đi chuẩn cho production:

```text
ZIP release
   ↓
GitHub Desktop
   ↓
Commit to main
   ↓
Push origin
   ↓
Monitor: backup → update → doctor → verify version
   ↓
Agent: cài/update thủ công hoặc Ansible
   ↓
Kiểm tra service, log, DB, Consumption và retention
```

## 1. Tài liệu nên mở theo thứ tự

1. [`SOURCE_OF_TRUTH_VI.md`](SOURCE_OF_TRUTH_VI.md)
   - Kiến trúc, service, timer, path, PostgreSQL/TimescaleDB, Agent và Consumption đúng theo source.

2. [`GITHUB_DESKTOP_VI.md`](GITHUB_DESKTOP_VI.md)
   - Cách đưa bản ZIP này lên repo bằng GitHub Desktop.
   - Cách copy đúng root repo, không làm mất `.git`.
   - Cách Commit, Push và kiểm tra GitHub đã nhận đúng bản.

3. [`COMMANDS_A_TO_Z_VI.md`](COMMANDS_A_TO_Z_VI.md)
   - Cài Monitor mới bằng IP hoặc domain HTTPS.
   - Update/fix Monitor đang chạy.
   - Cài, update, kiểm tra và gỡ Agent thủ công.
   - Deploy/update Agent hàng loạt bằng Ansible.
   - Toàn bộ command bảo trì, backup, restore, DB, retention, log và troubleshooting.

4. [`README.md`](README.md)
   - Kiến trúc và chức năng của sản phẩm.

5. [`docs/STORAGE_V2_DEPLOYMENT.md`](docs/STORAGE_V2_DEPLOYMENT.md)
   - Kiến trúc chart 5 phút 7 ngày, raw 48 giờ, kiểm tra, validation, benchmark và rollback.

## 2. Luồng nhanh nhất để triển khai bản này

### Bước A - Đưa source lên GitHub

Giải nén ZIP. Trong thư mục giải nén sẽ có các file như:

```text
README.md
START_HERE_VI.md
GITHUB_DESKTOP_VI.md
COMMANDS_A_TO_Z_VI.md
VERSION
install.sh
update.sh
app/
deploy/
ansible/
docs/
```

Mở repo local trong GitHub Desktop:

```text
Repository
→ Show in Explorer
```

Copy **toàn bộ nội dung bên trong** thư mục release vào root repo local. Không copy nguyên thư mục release thành một thư mục con. Không xóa thư mục ẩn `.git`.

Trong GitHub Desktop:

```text
Summary:
Release 50.4.4 manifest + Consumption UI fix

Commit to main
→ Push origin
```

Kiểm tra GitHub đã nhận đúng version:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/VERSION
```

Kết quả phải là:

```text
50.5.9-prod-r3-ui-alignment-overflow-hotfix
```

### Bước B - Update Monitor đang chạy

Chạy trên server Monitor bằng `root`:

```bash
virtinfra-monitorctl backup && \
virtinfra-monitorctl update && \
systemctl restart bw-monitor.service && \
virtinfra-monitorctl doctor && \
virtinfra-monitorctl version
```

Kết quả version phải là:

```text
50.5.9-prod-r3-ui-alignment-overflow-hotfix
```

Kiểm tra thêm:

```bash
virtinfra-monitorctl status
virtinfra-monitorctl health
virtinfra-monitorctl urls
```

Mở trình duyệt và nhấn:

```text
Ctrl + F5
```

Trang `Consumption` vẫn dùng route kỹ thuật:

```text
https://DOMAIN-CUA-M/bandwidth-consumption
```

### Bước C - Agent

Bản `50.4.4` không thay đổi payload, endpoint, token hay chu kỳ của Agent. Node đang chạy VirtInfra Agent hiện tại không bắt buộc cài lại chỉ để dùng Storage V2.

Node chưa có Agent hoặc cần đồng bộ source Agent mới, dùng:

```bash
read -rsp 'Nhap VirtInfra Agent token: ' BW_TOKEN
echo

curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/install-agent.sh \
| env \
VIRTINFRA_AGENT_API='https://DOMAIN-CUA-M/push' \
VIRTINFRA_AGENT_TOKEN="$BW_TOKEN" \
BW_AGENT_BRIDGE_ROLES='public:br0,private:br1' \
bash

unset BW_TOKEN
```

Kiểm tra:

```bash
virtinfra-agent-doctor
systemctl status virtinfra-agent.service --no-pager -l
```

## 3. Các command quan trọng nhất

### Monitor

```bash
virtinfra-monitorctl version
virtinfra-monitorctl urls
virtinfra-monitorctl credentials
virtinfra-monitorctl status
virtinfra-monitorctl health
virtinfra-monitorctl doctor
virtinfra-monitorctl audit
virtinfra-monitorctl db-check
virtinfra-monitorctl logs all 300
virtinfra-monitorctl follow monitor
virtinfra-monitorctl restart
virtinfra-monitorctl backup
virtinfra-monitorctl retention
virtinfra-monitorctl vacuum
virtinfra-monitorctl diagnostics
virtinfra-monitorctl update
```

### Agent trên một node

```bash
virtinfra-agent-doctor
systemctl is-active virtinfra-agent.service
systemctl is-enabled virtinfra-agent.service
systemctl status virtinfra-agent.service --no-pager -l
journalctl -u virtinfra-agent.service -n 200 --no-pager
journalctl -fu virtinfra-agent.service
```

### PostgreSQL

```bash
virtinfra-monitorctl db-check
virtinfra-monitorctl psql
```

### Backup và restore

```bash
virtinfra-monitorctl backup
```

```bash
virtinfra-monitorctl restore \
--from /var/backups/bw-monitor/YYYYMMDD-HHMMSS \
--yes
```

## 4. Nguyên tắc production

Không commit các file sau lên GitHub:

```text
/root/bw-monitor-credentials.env
/etc/default/bw-monitor
/etc/default/bw-monitor-postgres
/etc/virtinfra-agent.env
ansible/test.txt
inventory thật
private key
SSH key
Token Agent
Database dump
```

Không dùng `--reset-state` khi update Agent bình thường.

Không xóa Docker volume PostgreSQL khi chưa có backup.

Không chạy `VACUUM FULL` trong giờ production. Command chuẩn là:

```bash
virtinfra-monitorctl vacuum
```

Không sửa trực tiếp DB nếu chức năng tương ứng đã có trong Admin/Maintenance.

## 5. Khi có lỗi, chạy khối này trước

```bash
virtinfra-monitorctl version
virtinfra-monitorctl doctor
virtinfra-monitorctl status
virtinfra-monitorctl health
virtinfra-monitorctl logs all 300
virtinfra-monitorctl db-check
```

Với Agent:

```bash
virtinfra-agent-doctor
systemctl status virtinfra-agent.service --no-pager -l
journalctl -u virtinfra-agent.service -n 300 --no-pager
```

Sau đó xem phần đúng lỗi trong [`COMMANDS_A_TO_Z_VI.md`](COMMANDS_A_TO_Z_VI.md).
