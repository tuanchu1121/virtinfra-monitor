# HƯỚNG DẪN ĐẦY ĐỦ CHO REPO MỚI `virtinfra-monitor`

> Release: `50.4.9-prod-r1-professional-theme-suite`
>
> Repo chuẩn duy nhất: `tuanchu1121/virtinfra-monitor`
>
> Tài liệu này dành cho người mới, đi từ lúc tạo repository, đưa source bằng GitHub Desktop, kiểm tra source trên GitHub, cài Monitor, cài Agent, update, backup, kiểm tra lỗi và rollback chart reader.

---

## 1. Những thứ cần chuẩn bị

Trên máy Windows:

- tài khoản GitHub đã đăng nhập;
- GitHub Desktop;
- file ZIP release này;
- quyền tạo hoặc ghi vào repository `tuanchu1121/virtinfra-monitor`.

Trên máy Monitor:

- Debian 12+ hoặc Ubuntu 22.04+;
- quyền `root`;
- tối thiểu nên có 4 vCPU, 8 GB RAM và SSD/NVMe;
- cổng TCP 80/443 mở nếu dùng domain HTTPS;
- domain đã trỏ A/AAAA về IP Monitor nếu dùng domain.

Trên KVM node:

- quyền `root`;
- `libvirt`/`virsh` đang hoạt động;
- node truy cập được URL `/push` của Monitor.

---

## 2. Tạo repository mới trên GitHub

Mở GitHub trên trình duyệt:

1. Chọn **New repository**.
2. Owner: `tuanchu1121`.
3. Repository name: `virtinfra-monitor`.
4. Chọn **Public** nếu muốn dùng trực tiếp các lệnh `curl` không cần GitHub token.
5. Không cần thêm README, `.gitignore` hoặc License vì release đã có đầy đủ.
6. Chọn **Create repository**.

Repo chuẩn sau khi tạo:

```text
https://github.com/tuanchu1121/virtinfra-monitor
```

---

## 3. Đưa full source lên bằng GitHub Desktop

### Cách an toàn nhất

1. Giải nén file:

```text
virtinfra-monitor-50.4.9-prod-r1-professional-theme-suite.zip
```

2. Mở GitHub Desktop.
3. Chọn **File → Clone repository**.
4. Chọn repository `tuanchu1121/virtinfra-monitor`.
5. Chọn thư mục local rồi bấm **Clone**.
6. Trong GitHub Desktop chọn:

```text
Repository → Show in Explorer
```

7. Mở thư mục release vừa giải nén.
8. Copy **toàn bộ nội dung bên trong** thư mục release vào root repository vừa clone.

Đúng:

```text
virtinfra-monitor\
├── app\
├── deploy\
├── postgres\
├── tests\
├── tools\
├── install.sh
├── install-agent.sh
├── update.sh
├── VERSION
└── SHA256SUMS
```

Sai:

```text
virtinfra-monitor\
└── virtinfra-monitor-50.4.9-prod-r1-professional-theme-suite\
    ├── app\
    ├── deploy\
    └── install.sh
```

Không xóa thư mục ẩn:

```text
.git
```

### Commit và Push

Trong GitHub Desktop:

```text
Summary:
Release 50.4.4 manifest + Consumption UI fix
```

Sau đó:

```text
Commit to main
→ Push origin
```

---

## 4. Kiểm tra GitHub đã nhận đủ source

Mở:

```text
https://github.com/tuanchu1121/virtinfra-monitor
```

Phải thấy tối thiểu:

```text
app/app.py
app/bw_pg.py
app/storage_v2.py
postgres/docker-compose.yml
postgres/sql/004_storage_v2.sql
deploy/postgres/install-postgres-native.sh
install.sh
install-agent.sh
VERSION
SHA256SUMS
```

Kiểm tra version từ Linux hoặc PowerShell có `curl`:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/VERSION
```

Kết quả phải là:

```text
50.4.9-prod-r1-professional-theme-suite
```

Kiểm tra hai file Storage V2:

```bash
curl -fsSI \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/app/storage_v2.py

curl -fsSI \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/postgres/sql/004_storage_v2.sql
```

Hai lệnh phải trả HTTP `200`.

---

## 5. Cài Monitor mới bằng domain HTTPS

Ví dụ domain production:

```text
virtinfra-monitor.duckdns.org
```

Đảm bảo domain đã trỏ về IP server và TCP 80/443 đang mở.

Chạy bằng `root`:

```bash
apt-get update
apt-get install -y curl ca-certificates tar

curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/install.sh \
| bash -s -- \
--domain virtinfra-monitor.duckdns.org \
--email winterboy1121@gmail.com
```

Installer sẽ tự:

- cài dependency;
- cài Docker;
- dựng PostgreSQL 17 + TimescaleDB;
- chạy migration;
- cài Flask/Gunicorn;
- cấu hình Nginx;
- xin chứng chỉ Let's Encrypt;
- tạo Admin password;
- tạo Agent token;
- cài systemd service/timer;
- chạy health check.

Sau khi cài, mở:

```text
https://virtinfra-monitor.duckdns.org
```

Xem URL và credential:

```bash
virtinfra-monitorctl urls
virtinfra-monitorctl credentials
```

Credential cũng nằm tại:

```text
/root/bw-monitor-credentials.env
```

File này chỉ root đọc được. Không đưa file này lên GitHub.

---

## 6. Cài Monitor mới bằng IP

Ví dụ IP Monitor là `203.0.113.10`:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/install.sh \
| bash -s -- \
--public-ip 203.0.113.10 \
--port 8080
```

Mở:

```text
http://203.0.113.10:8080
```

---

## 7. Kiểm tra Monitor sau cài

Chạy lần lượt:

```bash
virtinfra-monitorctl version
virtinfra-monitorctl status
virtinfra-monitorctl health
virtinfra-monitorctl doctor
virtinfra-monitorctl db-check
virtinfra-monitorctl storage-v2
virtinfra-monitorctl urls
```

Version phải là:

```text
50.4.9-prod-r1-professional-theme-suite
```

Storage V2 cần thấy:

```text
vm_chart_5m
vm_raw_detail_5m
node_chart_5m
```

Xem log Monitor:

```bash
virtinfra-monitorctl logs monitor 300
```

Theo dõi realtime:

```bash
virtinfra-monitorctl follow monitor
```

---

## 8. Lấy Agent token

Trên Monitor:

```bash
virtinfra-monitorctl credentials
```

Hoặc:

```bash
cat /root/bw-monitor-credentials.env
```

Lấy giá trị Agent token nhưng không đăng token lên GitHub, ticket công khai hoặc ảnh chụp màn hình.

---

## 9. Cài Agent trên KVM node

Dùng HTTPS nếu Monitor đã có domain và TLS.

```bash
read -rsp 'Nhap VirtInfra Agent token: ' BW_TOKEN
echo

curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/install-agent.sh \
| env \
VIRTINFRA_AGENT_API='https://virtinfra-monitor.duckdns.org/push' \
VIRTINFRA_AGENT_TOKEN="$BW_TOKEN" \
BW_AGENT_BRIDGE_ROLES='public:br0,private:br1' \
bash

unset BW_TOKEN
```

Quan trọng:

```text
Dùng:
https://virtinfra-monitor.duckdns.org/push

Không dùng:
http://virtinfra-monitor.duckdns.org/push
```

Nếu HTTP bị Nginx chuyển sang HTTPS, pre-check có thể gặp `301`. Dùng thẳng HTTPS là đúng và tránh một vòng redirect không cần thiết.

Nếu node chỉ có public bridge:

```bash
BW_AGENT_BRIDGE_ROLES='public:br0'
```

Nếu tên bridge khác:

```bash
BW_AGENT_BRIDGE_ROLES='public:vmbr0,private:vmbr1'
```

Không hardcode theo ví dụ nếu hạ tầng dùng tên bridge khác.

---

## 10. Kiểm tra Agent

```bash
systemctl status virtinfra-agent.service --no-pager

virtinfra-agent-doctor

journalctl \
-u virtinfra-agent.service \
-n 200 \
--no-pager
```

Xem config:

```bash
cat /etc/virtinfra-agent.env
```

Không gửi công khai nội dung token.

Agent chuẩn:

```text
Local sample: 15 giây
Metric push: 5 phút
Consumption: 2 giờ
```

---

## 11. Update Monitor sau này

Cách đơn giản:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/update.sh \
| bash
```

Hoặc:

```bash
virtinfra-monitorctl update
```

Update giữ lại:

- PostgreSQL data;
- Timescale data;
- Admin account;
- Admin password hash;
- Agent token;
- API key;
- secret key;
- domain/TLS;
- settings;
- current history.

Sau update:

```bash
virtinfra-monitorctl version
virtinfra-monitorctl health
virtinfra-monitorctl doctor
virtinfra-monitorctl db-check
```

---

## 12. Backup trước thay đổi lớn

```bash
virtinfra-monitorctl backup
```

Liệt kê backup:

```bash
ls -lah /var/backups/bw-monitor/
```

Không xóa Docker volume PostgreSQL khi chưa có backup.

---

## 13. Rollback chart reader V2

Chỉ dùng khi chart V2 có lỗi nhưng Monitor vẫn chạy:

```bash
virtinfra-monitorctl rollback-storage-v2
```

Lệnh này:

- không xóa bảng V2;
- không xóa data;
- không đổi Agent;
- chỉ đưa chart reader về compatibility reader.

Kiểm tra lại:

```bash
virtinfra-monitorctl health
virtinfra-monitorctl storage-v2
```

---

## 14. Các lỗi thường gặp

### Lỗi repository incomplete

Ví dụ:

```text
Downloaded repository is incomplete. Missing:
  - app/storage_v2.py
  - postgres/sql/004_storage_v2.sql
```

Kiểm tra:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/VERSION
```

Sau đó kiểm tra hai file:

```bash
curl -fsSI \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/app/storage_v2.py

curl -fsSI \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/postgres/sql/004_storage_v2.sql
```

Nếu không phải HTTP 200, source chưa được copy đúng root repo hoặc chưa Push origin.

### Lỗi `301` khi cài Agent

Đổi API từ:

```text
http://domain/push
```

sang:

```text
https://domain/push
```

### Lỗi `404` khi tải installer

Kiểm tra:

- repo có đúng tên `virtinfra-monitor`;
- branch có đúng `main`;
- file nằm ở root repo;
- repo Public hoặc đã cấu hình GitHub token cho repo Private.

### Lỗi checksum

Chạy lại release audit trước khi Push:

```bash
bash tools/release-audit.sh --use-current-python --skip-live
```

Sau đó Commit và Push lại file `SHA256SUMS` mới.

### Domain không xin được SSL

Kiểm tra:

```bash
getent ahosts virtinfra-monitor.duckdns.org

ss -lntp | grep -E ':80|:443'

ufw status
```

Domain phải trỏ đúng IP và cổng 80/443 phải truy cập được từ Internet.

---

## 15. Lệnh kiểm tra nhanh hằng ngày

```bash
virtinfra-monitorctl status
virtinfra-monitorctl health
virtinfra-monitorctl db-check
virtinfra-monitorctl storage-v2
virtinfra-monitorctl logs all 200
```

Trên node:

```bash
virtinfra-agent-doctor
systemctl is-active virtinfra-agent.service
```

---

## 16. Repo chuẩn và URL chuẩn

Repo:

```text
tuanchu1121/virtinfra-monitor
```

Monitor installer:

```text
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/install.sh
```

Monitor updater:

```text
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/update.sh
```

Agent installer:

```text
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/install-agent.sh
```

Agent uninstaller:

```text
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/uninstall-agent.sh
```

Version:

```text
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/VERSION
```

---

## 17. Checklist trước khi đưa production

```text
[ ] Repo đúng: tuanchu1121/virtinfra-monitor
[ ] Branch đúng: main
[ ] VERSION trả đúng 50.4.9-prod-r1-professional-theme-suite
[ ] app/storage_v2.py trả HTTP 200
[ ] postgres/sql/004_storage_v2.sql trả HTTP 200
[ ] install.sh nằm ở root repo
[ ] SHA256SUMS đã được Push
[ ] Domain trỏ đúng IP
[ ] TCP 80/443 mở
[ ] Monitor doctor PASS
[ ] PostgreSQL/TimescaleDB PASS
[ ] Storage V2 có đủ hypertable/policy
[ ] Agent dùng HTTPS
[ ] Agent token không bị lộ
[ ] Bridge role đúng với từng node
[ ] Dashboard nhận node
[ ] Chart có điểm 5 phút
[ ] Consumption bắt đầu có bucket sau chu kỳ 2 giờ
[ ] Backup đầu tiên đã tạo
```

