# Báo cáo kiểm thử VirtInfra Monitor 50.6.0 r1

**Release:** `50.6.0-prod-r1-node-groups-additive`  
**Baseline trực tiếp:** `virtinfra-monitor-50.5.9-prod-r3-ui-alignment-overflow-hotfix-production-slim`  
**SHA-256 baseline:** `1d87021bc61aaeb82c2d5c8a9fe89085eea56ad58dcd167eb559de44e1b1590b`

## Nguyên tắc phát hành

Bản này được dựng lại trực tiếp từ baseline r3 slim, không kế thừa source của các bản Node Groups preview/r2 trước đó.

`app/app.py` giữ nguyên toàn bộ byte của baseline ở phần đầu file. Phần Node Groups chỉ được nối thêm ở cuối để cài module mới sau khi mọi implementation runtime cũ đã đăng ký xong.

Khi không chọn Group hoặc Node filter mới, các wrapper dữ liệu trả lại đúng object từ implementation cũ. Không đổi endpoint, payload, công thức hoặc luồng Agent hiện có.

## Phần được bổ sung

- Ba bảng PostgreSQL riêng: `node_groups`, `node_group_memberships`, `node_group_membership_history`.
- Admin menu: Overview, Nodes, Node Groups, VMs, Maintenance.
- CRUD Node Group với tên, mô tả, ISO country code, Enabled, Hidden và Default.
- Assign, Move, Remove Node bằng exact `node_name`; không dùng IP làm quan hệ.
- VM chỉ kế thừa Group từ Node; không có quan hệ VM → Group trực tiếp.
- Group/Node filter và cờ quốc gia nhỏ cạnh Node/VM trên giao diện monitor.
- Group Consumption tính từ physical Node counters; coverage dùng tổng valid/expected, không dùng trung bình phần trăm từng Node.
- API namespace mới và scope riêng:
  - `node_groups:read`
  - `node_groups:write`
  - `/api/v1/node-groups`
  - `/api/v1/node-groups/<id>`
  - `/api/v1/node-groups/<id>/nodes`
  - `/api/v1/node-groups/<id>/vms`
  - `/api/v1/node-groups/<id>/consumption`
  - `/api/v1/nodes/<node_name>/group`
  - `/api/v1/nodes/ungrouped`
- 271 SVG 4:3 từ `flag-icons`, được vendor local. UI khóa icon ở `16 × 12 px`.

## Contract không thay đổi

- Agent `deploy/agent/agent.py`: **byte-for-byte unchanged** so với baseline.
- Agent key/token, payload `/push`, cadence, retry và queue: **unchanged**.
- API endpoint và payload cũ: **unchanged**; Group dùng endpoint mới riêng.
- CPU, RAM, disk, network, PPS, Coverage và Abuse formula: **unchanged**.
- Retention, cleanup, maintenance queue, hide/restore/purge: **unchanged**.
- PostgreSQL migration cũ `001` đến `010`: **byte-for-byte unchanged**.
- Module runtime bảo vệ `bw_pg.py`, Storage V2, retention, maintenance, inventory cleanup và Consumption rollup: **byte-for-byte unchanged**.
- Không thêm `group_id` vào Node inventory, VM inventory hoặc bảng metric cũ.
- Không thay đổi Agent hoặc bắt Agent biết Node Group.

## Kiểm thử

### Pytest

```text
101 passed
```

Bao gồm ingest, snapshot, SQL compatibility, maintenance, MAC identity, queue, low-I/O, Consumption, UI r1/r2/r3 và Node Groups additive contract.

### Contract script

```text
11/11 PASS
```

Bao gồm Agent Consumption, auth, UI, theme, documentation, manifest, repository, Storage V2, v50 contract và hardening.

### Installer và source

- `tools/test-installer-flow.sh`: **PASS**.
- `tools/test-windows-github-desktop.sh`: **PASS**.
- Bash syntax toàn bộ shell script: **PASS**.
- Python compile cho app, Agent, tests và tools: **PASS**, 42 file.
- YAML workflow và Ansible parse: **PASS**.
- Canonical manifest đường dẫn `./...`: **PASS**, 434 source files.
- Không có cache, `pyc`, database dump hoặc secret pattern trong package.

### Preflight

Các stage của preflight đã được chạy độc lập và đều PASS. Lần chạy nguyên khối trong sandbox hoàn thành các stage đầu nhưng bị giới hạn thời gian của công cụ tại bước repository contract; do đó không ghi nhận nguyên khối preflight là PASS.

## PostgreSQL và visual review

- Live PostgreSQL integration: **SKIPPED**, không có `BW_TEST_DATABASE_URL` trỏ tới database disposable.
- Visual review trên session production và dữ liệu thật: **NOT VERIFIED VISUALLY**.
- Không deploy và không restart production trong quá trình build.

## Lưu ý Group Consumption

Group Consumption của khoảng thời gian đang xem dùng membership hiện tại của Node để gom physical Node counters. Bảng membership history vẫn được lưu cho audit và thay đổi Group về sau, nhưng release này chưa phân bổ lại từng bucket lịch sử theo `valid_from/valid_to`.

## Cờ local

Database chỉ lưu ISO code uppercase như `JP`, `US`, `SG`. Runtime render file lowercase như `/static/flags/4x3/jp.svg`. Nếu SVG không tồn tại, giao diện fallback emoji quốc gia hoặc `🌐 Global`. Runtime không phụ thuộc GitHub, npm, CDN hoặc upstream.
