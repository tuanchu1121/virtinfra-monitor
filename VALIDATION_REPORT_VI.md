# Báo cáo kiểm thử VirtInfra Monitor r5

**Release:** `50.5.8-prod-r5-professional-ui-storage-hotfix`  
**Ngày đóng gói:** 2026-07-18

## Nền tảng của bản này

Bản r5 được tạo trực tiếp từ full source r4, vì vậy giữ nguyên:

- Inventory cleanup worker/timer chống deadlock.
- Agent v15 chỉ gửi luồng metric chuẩn mỗi 5 phút.
- Consumption VM/Node và physical hourly/daily rollup phía Monitor.
- Các chức năng Abuse, CPU, RAM, Disk, PPS, Storage, retention, API, token, Hide/Restore/Purge của r4.

## Thay đổi runtime mới

### Storage hotfix

Sửa HTTP 500 tại đường dẫn kiểu:

```text
/storage?view=nodes&mount=...
```

Nguyên nhân là query dùng alias `ni` trong `WHERE` nhưng thiếu:

```sql
LEFT JOIN node_inventory ni ON ni.node=s.node
```

Bản sửa chỉ thêm join bị thiếu và giữ nguyên filter, sort, pagination, dữ liệu I/O và behavior Hide node.

### Giao diện

- Cân lại Dashboard, Node Detail, VM Detail, Consumption, Top VM và VM Abuse.
- Giữ nguyên thứ tự cột và sort key.
- Tên node/VM, header và số liệu được làm rõ hơn; cột nhiều dữ liệu được rộng hơn, cột IFACES/vCPU/DROPS/ERR được thu gọn.
- Vùng bảng tự cuộn ngang trên màn hình nhỏ, không làm toàn trang tràn.
- Theme mode và preset chuyển thành hai select gọn ở góc phải header.
- `guestfs-*` bị ẩn trong HTML hiển thị; dữ liệu thu thập và database không bị xóa hoặc thay đổi.
- `Real Snapshot Samples` và `Retained Network Snapshots` đóng mặc định; sort/pagination sẽ tự mở lại.
- Bỏ dòng chú thích dài dưới chart VM RAM.
- Chart giữ điểm 0 thật nhưng ngắt polyline khi thiếu time bucket. Khoảng mất dữ liệu được để trắng thay vì nối điểm trước và sau.

## Kiểm thử đã chạy

### Full preflight

```text
PASS: VirtInfra Monitor v50 PostgreSQL Native preflight
```

Preflight đã kiểm tra:

- Release identity và full source tree.
- SHA256 manifest.
- Secret/generated-file scan.
- Bash syntax.
- Python compile.
- YAML parse.
- PostgreSQL compatibility helpers.
- Native COPY ingest.
- Snapshot detail correctness.
- Maintenance compatibility.
- Queue và canonical VM detail.
- Storage V2 và multi-NIC regression.
- Agent v15 Consumption path.
- Consumption authentication/UI/deadlock contracts.
- Theme runtime.
- Installer flow.

### Regression suite không cần PostgreSQL live

```text
59 passed, 1 skipped
```

### Contract riêng của r5

```text
6 passed
```

### Kiểm thử bổ sung

- Chart gap segmentation: PASS.
- Storage filtered SQL join bằng fake DB cursor: PASS.
- Toàn bộ shell scripts `bash -n`: PASS.
- `app/*.py` và Agent `py_compile`: PASS.

## Chưa thực hiện

- Không chạy route thật với Gunicorn/Nginx và database production.
- Không chạy live PostgreSQL integration vì không có `BW_TEST_DATABASE_URL` trỏ tới database disposable.
- Không triển khai, restart hoặc thay đổi production.

Khuyến nghị triển khai Monitor trước, kiểm tra `/storage`, Dashboard, Node/VM Detail và `/bandwidth-consumption`, sau đó mới cập nhật Agent theo từng nhóm nếu production vẫn đang dùng Agent cũ.
