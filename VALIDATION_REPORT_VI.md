# Báo cáo kiểm thử VirtInfra Monitor 50.6.0 r2

**Release:** `50.6.0-prod-r2-node-groups-update-detection-fix`  
**Baseline:** `50.6.0-prod-r1-node-groups-country-flags`

## Phạm vi release

- Giữ đầy đủ Node Groups, VM kế thừa Group, Group/Node filter, Group Consumption và 271 SVG flag local từ r1.
- Sửa detection của `--update`: không còn yêu cầu đồng thời `/etc/default/bw-monitor` và `/etc/default/bw-monitor-postgres`.
- Existing runtime được xác nhận bằng `app.py`, runtime env và systemd service.
- Nếu thiếu `bw-monitor-postgres`, credential được khôi phục từ DSN hiện có hoặc container `bw-timescaledb`; updater không tự sinh password mới cho database đang chạy.
- External PostgreSQL DSN bị từ chối thay vì âm thầm chuyển sang bundled local container.
- `node_groups.py` được kiểm tra syntax trong `ExecStartPre`.

## Node Groups và cờ local

- Membership chỉ dùng exact Node name, không dùng IP.
- VM không có membership riêng và chỉ kế thừa Group từ Node.
- Admin có Overview, Nodes, Node Groups, VMs và Maintenance.
- Cờ `flag-icons 7.5.0` được vendor local: 271 SVG 4:3, icon UI khóa 16 × 12 px.
- Runtime không phụ thuộc GitHub, npm, CDN hoặc upstream.

## Kiểm thử đã hoàn thành

- Manifest canonical: **PASS**, 435 source files, đường dẫn `./...`.
- Python compile cho `app.py` và `node_groups.py`: **PASS**.
- Bash syntax cho installer/update: **PASS**.
- Core + hardening + UI r3 + Node Groups + updater tests: **25 passed**.
- Ingest/snapshot/SQL/maintenance tests: **26 passed**.
- MAC/queue/low-I/O/agent/Consumption tests: **43 passed**.
- UI/contract/Node Groups/updater batch: **41 passed**.
- Installer flow: **PASS**.
- Windows GitHub Desktop flow: **PASS**.
- Missing-PG_ENV recovery smoke test: **PASS**.
- Standalone repository, Storage V2, docs, Agent Consumption, auth, theme and manifest contracts: **PASS**.

Các nhóm test trên có phần chồng lặp nên không cộng thành một tổng duy nhất. Full pytest trong một process không được dùng làm kết quả chính vì bộ test AST lớn giữ nhiều bản sao `app.py` trong cùng process; các suite được chạy tách biệt và đã hoàn thành như liệt kê.

## Chưa xác minh

- Live PostgreSQL integration: **SKIPPED**, không có `BW_TEST_DATABASE_URL` trỏ tới database disposable.
- Visual review trên session production và dữ liệu thật: **NOT VERIFIED VISUALLY**.

Không deploy và không restart production trong quá trình tạo release.
