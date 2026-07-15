# Đưa VirtInfra Monitor lên GitHub bằng GitHub Desktop

> Dùng cho release `50.4.4-prod-r1-manifest-consumption-ui-fix`.

> Source of truth vận hành: [`SOURCE_OF_TRUTH_VI.md`](SOURCE_OF_TRUTH_VI.md).
>
> Release này dùng PostgreSQL 17 + TimescaleDB làm nguồn dữ liệu duy nhất. GitHub chỉ chứa source và manifest, không chứa data volume, env production hoặc database dump.

Mục tiêu là đưa **toàn bộ source ở root release** lên đúng root repo:

```text
https://github.com/tuanchu1121/virtinfra-monitor
```

Không tạo thêm một lớp thư mục release ở bên trong repo.

---

## 1. Chuẩn bị

Trước khi copy source:

1. Mở GitHub Desktop.
2. Chọn đúng repository `virtinfra-monitor`.
3. Chọn branch `main`.
4. Bấm:

```text
Fetch origin
```

Nếu có nút:

```text
Pull origin
```

thì bấm `Pull origin` trước.

Không nên chép source mới khi local repo đang chưa đồng bộ với GitHub.

---

## 2. Tìm đúng thư mục repo local

Trong GitHub Desktop:

```text
Repository
→ Show in Explorer
```

Windows Explorer sẽ mở root repo local.

Root đúng phải đang có các file/thư mục như:

```text
.git/
.github/
app/
ansible/
deploy/
docs/
README.md
VERSION
install.sh
update.sh
```

`.git` là thư mục ẩn. Không xóa, không thay thế và không copy nó từ nơi khác.

---

## 3. Giải nén release

Giải nén file ZIP release ra một thư mục riêng, ví dụ:

```text
D:\Downloads\virtinfra-monitor-50.4.4-prod-r1-manifest-consumption-ui-fix\
```

Mở thư mục đó. Bên trong phải thấy trực tiếp:

```text
README.md
START_HERE_VI.md
GITHUB_DESKTOP_VI.md
COMMANDS_A_TO_Z_VI.md
VERSION
install.sh
update.sh
app\
deploy\
ansible\
docs\
```

Nếu chỉ thấy thêm một thư mục cùng tên release, mở tiếp thư mục đó. Mục tiêu là chọn **nội dung bên trong**, không chọn cả lớp thư mục bao ngoài.

---

## 4. Copy source vào repo local

Trong thư mục release:

```text
Ctrl + A
Ctrl + C
```

Qua cửa sổ root repo local:

```text
Ctrl + V
```

Khi Windows hỏi file trùng:

```text
Replace the files in the destination
```

Không xóa `.git`.

Các inventory local như:

```text
ansible/test.txt
ansible/production.ini
```

đã được `.gitignore` bỏ qua. Tuy nhiên vẫn nên giữ một bản backup riêng trước khi thay source.

---

## 5. Kiểm tra Changes trong GitHub Desktop

Quay lại GitHub Desktop. Tab `Changes` phải xuất hiện nhiều file thay đổi.

Kiểm tra nhanh:

```text
VERSION
README.md
START_HERE_VI.md
GITHUB_DESKTOP_VI.md
COMMANDS_A_TO_Z_VI.md
CHANGELOG.md
SHA256SUMS
```

Không được thấy các file bí mật như:

```text
.env
credentials.env
bw-monitor-credentials.env
ansible/test.txt
private key
*.pem
*.key
*.dump
```

Nếu thấy token hoặc mật khẩu trong Changes, bỏ file đó khỏi commit ngay.

---

## 6. Commit

Ở ô `Summary` nhập:

```text
Release 50.4.4 manifest + Consumption UI fix
```

Description có thể ghi:

```text
Keep Consumption route fix and add complete GitHub Desktop, deployment, Agent, maintenance, backup, restore and troubleshooting documentation.
```

Bấm:

```text
Commit to main
```

---

## 7. Push lên GitHub

Sau khi commit:

```text
Push origin
```

Đợi GitHub Desktop báo hoàn tất.

---

## 8. Kiểm tra GitHub đã nhận đúng release

Trên bất kỳ Linux server nào:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/VERSION
```

Phải trả về:

```text
50.4.4-prod-r1-manifest-consumption-ui-fix
```

Kiểm tra file installer:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/update.sh \
| head
```

Kiểm tra manifest:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/SHA256SUMS \
| head
```

---

## 9. Update Monitor sau khi Push

Chạy trên Monitor:

```bash
virtinfra-monitorctl backup && \
virtinfra-monitorctl update && \
systemctl restart bw-monitor.service && \
virtinfra-monitorctl doctor && \
virtinfra-monitorctl version
```

Phải ra:

```text
50.4.4-prod-r1-manifest-consumption-ui-fix
```

Kiểm tra:

```bash
virtinfra-monitorctl status
virtinfra-monitorctl health
virtinfra-monitorctl urls
```

---

## 10. Nếu GitHub Desktop báo push bị từ chối

Nguyên nhân thường là GitHub có commit mới hơn local.

Làm theo thứ tự:

```text
Fetch origin
→ Pull origin
```

Nếu có conflict:

1. Mở từng file conflict.
2. Chọn nội dung đúng của release mới.
3. Đánh dấu resolved.
4. Commit merge.
5. `Push origin` lại.

Không bấm force push lên `main` khi chưa hiểu rõ commit nào sẽ bị ghi đè.

---

## 11. Nếu copy nhầm cả thư mục release vào repo

Sai:

```text
repo-root/
└── virtinfra-monitor-50.4.4-prod-r1-manifest-consumption-ui-fix/
    ├── app/
    ├── deploy/
    └── install.sh
```

Đúng:

```text
repo-root/
├── app/
├── deploy/
├── install.sh
├── update.sh
└── VERSION
```

Nếu copy sai:

1. Xóa thư mục release bị lồng.
2. Mở thư mục release đó.
3. Copy toàn bộ **nội dung bên trong** ra root repo.
4. Commit lại.

---

## 12. Rollback source bằng GitHub Desktop

Khi commit mới gây lỗi code:

```text
History
→ chọn commit release mới
→ chuột phải
→ Revert changes in commit
→ Push origin
```

Sau đó trên Monitor:

```bash
virtinfra-monitorctl backup
virtinfra-monitorctl update
virtinfra-monitorctl doctor
virtinfra-monitorctl version
```

`Revert commit` chỉ rollback source trên GitHub. Nếu cần rollback dữ liệu PostgreSQL, dùng backup/restore theo `COMMANDS_A_TO_Z_VI.md`.

---

## 13. Kiểm tra trước khi Push bằng Linux hoặc WSL

Trong root repo:

```bash
bash ./preflight.sh --skip-live
```

Hoặc đầy đủ release audit:

```bash
bash ./tools/release-audit.sh --skip-live
```

Kết quả cuối cần có:

```text
PASS: VirtInfra Monitor v50 PostgreSQL Native preflight
PASS: VirtInfra Monitor v50 release audit
```

GitHub Desktop trên Windows có thể lưu file `.sh` ở mode `0644`. Installer của release đã xử lý trường hợp này bằng cách gọi script qua `bash` và normalize mode sau khi tải.
