# Báo cáo kiểm thử VirtInfra Monitor 50.5.9 r1

**Release:** `50.5.9-prod-r1-ui-responsive-theme-chart-gaps`  
**Ngày đóng gói:** 2026-07-18  
**Baseline trực tiếp:** `50.5.8-prod-r5-professional-ui-storage-hotfix`

## Mục tiêu release

Đây là full-source production release cho lớp giao diện responsive, Theme Auto/Light/Dark và chart ngắt đúng tại vùng mất dữ liệu. Release giữ nguyên toàn bộ backend, Agent, SQL, route, endpoint, query parameter, form field/action, sort key và behavior của baseline, ngoại trừ metadata phiên bản.

Release vẫn chứa đầy đủ các phần đã có trong baseline:

- Inventory cleanup worker/timer chống deadlock.
- `/push` deadlock retry và batch cleanup `SKIP LOCKED`.
- Agent v15 gửi metric chuẩn mỗi 5 phút, không gửi payload Consumption riêng mỗi 2 giờ.
- VM/Node Consumption và physical hourly/daily rollup.
- Storage filtered-node hotfix bổ sung `LEFT JOIN node_inventory ni`.
- UI Dashboard, Node Detail, VM Detail, Top VM, VM Abuse và Consumption đã căn chỉnh.
- `guestfs-*` chỉ bị ẩn tại presentation layer.
- Chart dùng timestamp thật và không nối qua vùng mất sample.
- Retained/Real Snapshot mặc định đóng.

## Thay đổi mới riêng của 50.5.9 r1

1. Đổi release identity thành `50.5.9-prod-r1-ui-responsive-theme-chart-gaps`.
2. Theme control được gom trong một khu vực có nhãn `Theme`:
   - Auto mặc định;
   - Light;
   - Dark;
   - style preset vẫn nằm trong cùng cụm điều khiển.
3. Snapshot collapse bổ sung accessibility:
   - `aria-expanded`;
   - `aria-controls`;
   - đồng bộ trạng thái khi `<details>` toggle;
   - `focus-visible` rõ ràng.
4. Thêm contract snapshot/test khóa:
   - route và endpoint;
   - `app.view_functions` override;
   - query parameter;
   - form parameter;
   - `url_for` endpoint;
   - sort map;
   - Agent byte-for-byte;
   - PostgreSQL SQL byte-for-byte.

Không có thay đổi công thức hoặc nghiệp vụ mới trong 50.5.9 r1.

## Contract-equivalence

So với baseline r5:

- Route decorators: **72**, không đổi.
- Runtime view-function overrides: **60**, không đổi.
- Query parameter literal contract: không đổi.
- Form parameter literal contract: không đổi.
- `url_for()` endpoint literal contract: không đổi.
- Sort-map contract: không đổi.
- Agent `deploy/agent/agent.py` SHA-256:
  `d637ec4fa0de2e07622402e3da60ae54ccf2d3f84f046de2141c813ee3b58081`, byte-for-byte giống baseline.
- Toàn bộ `postgres/sql/*.sql`: byte-for-byte giống baseline.

Các khác biệt trong `app/app.py` sau khi chuẩn hóa release metadata chỉ nằm ở:

- ARIA cho hai snapshot collapse;
- thứ tự/nhãn presentation của Theme select;
- script đồng bộ `aria-expanded`;
- CSS `focus-visible`;
- injection script presentation-only.

## Test đã chạy

### Full PostgreSQL-native preflight

Kết quả:

```text
PASS: VirtInfra Monitor v50 PostgreSQL Native preflight
```

Preflight exit code: `0`.

Preflight bao gồm:

- release identity;
- source checksum manifest;
- secret/generated-file scan;
- Bash syntax;
- Python compile;
- YAML parse;
- v50 product contract;
- native COPY ingest;
- selected snapshot correctness;
- PostgreSQL LIKE compatibility;
- PostgreSQL-native maintenance;
- safe FIFO queue/canonical VM detail;
- Storage V2/multi-NIC;
- Agent v15 Consumption path;
- Consumption auth/UI/deadlock contracts;
- Theme contracts;
- 50.5.9 UI/chart-gap contract;
- route/query/form/sort/Agent/SQL equivalence;
- installer flow.

### Full pytest suite

```text
78 passed, 1 skipped in 30.30s
```

Skipped test là live PostgreSQL integration không có disposable DSN.

### Targeted 50.5.9 tests

```text
6 passed  UI, Theme, snapshot, chart gaps, guestfs và Storage join
3 passed  route/query/form/sort/Agent/SQL equivalence
```

### JavaScript và CSS

- `node --check` cho script accessibility mới: **PASS**.
- `tinycss2` parse lớp CSS UI mới: **PASS**, 120 top-level rules.
- Python `py_compile`: **PASS**.
- Bash `bash -n`: **PASS**.
- YAML parse: **PASS**.

### Packaging/installer

- Installer flow: **PASS**.
- Windows GitHub Desktop compatibility: **PASS**.
- Canonical source manifest: **154 files**, fresh hashes và exact coverage.

## Visual review

**NOT VERIFIED VISUALLY**

Môi trường có Chromium nhưng không có PostgreSQL disposable chứa dữ liệu đại diện và session đăng nhập để render chính xác Dashboard, Node Detail, VM Detail, Top VM, VM Abuse, Consumption, System Status và Admin ở các viewport yêu cầu.

Do đó release này không tuyên bố đã browser-review thực tế tại:

- 1920×1080 Light/Dark;
- 2048×1152 Light/Dark;
- 1366×768;
- zoom 125%;
- zoom 150%.

Static CSS/HTML contract và overflow-wrapper markers đã được kiểm tra, nhưng cần staging review trước production.

## Live integration chưa chạy

- Không chạy route thật với Gunicorn/Nginx.
- Không chạy PostgreSQL/TimescaleDB integration vì thiếu `BW_TEST_DATABASE_URL` trỏ tới database disposable.
- Không deploy.
- Không restart production service.
- Không thay đổi production database.

## Những phần không thay đổi

- Agent collection và Agent push.
- API endpoint và response/request payload.
- Flask route/endpoint name.
- Query parameter, form action, input name và CSRF.
- Sort key, sort direction, filter, search và pagination behavior.
- SQL nghiệp vụ và database schema.
- CPU, RAM, network, PPS, disk và Abuse formula.
- Severity, policy revision, retention, maintenance và queue.
- Hide/Restore/Purge behavior.
- Consumption data, rollup, cache và SQL.

## Danh sách chính xác file thay đổi so với baseline r5

### Runtime/metadata

- `VERSION`
- `app/app.py`
- `app/retention.py`
- `deploy/postgres/install-postgres-native.sh`
- `preflight.sh`

### Test/contract

- `tests/test_v5059_r1_ui_responsive_theme_chart_gaps.py` (thay cho test r5)
- `tests/test_v5059_r1_contract_equivalence.py` (mới)
- `tests/contracts/v5059_r1_runtime_contract.json` (mới)
- `tests/test_v50_contract.py`
- `tests/test_v5052_native_copy_ingest.py`
- `tests/test_v5054_snapshot_detail_correctness.py`
- `tests/test_v5055_sql_compat_hotfix.py`
- `tests/test_v5057_mac_identity_search.py`
- `tests/test_v5057_safe_queue_canonical_vm.py`
- `tests/test_v5058_r4_consumption_inventory.py`
- `tests/test_virtinfra_hardening.py`
- `tools/test-installer-flow.sh`

Các test cũ ở nhóm trên chỉ đổi expected release identity.

### Tài liệu/release identity

- `CHANGELOG.md`
- `README.md`
- `START_HERE_VI.md`
- `SOURCE_OF_TRUTH_VI.md`
- `COMMANDS_A_TO_Z_VI.md`
- `GITHUB_DESKTOP_VI.md`
- `docs/README_VI.md`
- `docs/LOW_IO_UPGRADE.md`
- `docs/PUBLISHING.md`
- `docs/CONSUMPTION_VM_NODE.md`
- `docs/STORAGE_V2_ARCHITECTURE.md`
- `docs/STORAGE_V2_AUDIT.md`
- `docs/STORAGE_V2_COMPATIBILITY_MATRIX.md`
- `docs/STORAGE_V2_DEPLOYMENT.md`
- `VALIDATION_REPORT_VI.md`
- `SHA256SUMS`

## Khuyến nghị triển khai

1. Backup source/env/database theo quy trình hiện có.
2. Triển khai Monitor trước.
3. Kiểm tra staging hoặc production có kiểm soát tại các viewport/Theme yêu cầu.
4. Kiểm tra riêng:
   - Dashboard;
   - Node/VM detail;
   - Top VM;
   - VM Abuse;
   - Consumption;
   - `/storage?view=nodes&mount=...`;
   - snapshot collapse và chart gaps.
5. Theo dõi `/push`, Gunicorn, PostgreSQL deadlock và response 500 trước khi rollout rộng.
