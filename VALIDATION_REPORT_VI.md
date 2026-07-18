# Báo cáo kiểm thử VirtInfra Monitor 50.5.9 r2

**Release:** `50.5.9-prod-r2-ui-layout-polish-only`  
**Ngày đóng gói:** 2026-07-18  
**Baseline trực tiếp:** `50.5.9-prod-r1-ui-responsive-theme-chart-gaps`

## Mục tiêu release

Đây là bản full source chỉ đánh bóng bố cục giao diện trên baseline r1. Không bổ sung tính năng mới và không thay đổi luồng hoạt động của Monitor.

Phạm vi giao diện được sửa:

- Dashboard Nodes: tách rõ `STATUS` và `SNAPSHOT`, cân lại chiều rộng 18 cột và khung Load.
- Top VM: thu gọn cột `#`, dàn ngang `ALLOC · ASSIGNED · % · SLOTS`, căn giữa CPU, RAM và Disk Capacity.
- VM Consumption: nới VM/UUID và Node/IP, thu gọn các cột RX/TX, cân Total, Coverage, Latest Sample và toolbar.
- Node Consumption: cân lại Node/IP, Physical Public/Private, Coverage, Latest Sample và toolbar riêng của tab Node.
- Node Health: thêm khoảng đệm cho cột Node và cân lại tám cột vận hành.

Không thêm kéo thả cột, resize cột, hide/show cột, API mới, route mới, query parameter mới hoặc JavaScript nghiệp vụ mới.

## Thay đổi runtime

Thay đổi runtime duy nhất của r2 là một lớp CSS presentation-only mới trong `app/app.py`:

```text
V5059R2_UI_CSS
<style id="v5059r2-layout-polish-only">
```

Lớp CSS được chèn sau CSS r1. Không thêm function, route, endpoint, SQL, form action, request handler, event listener hoặc timer mới.

Các file runtime khác chỉ đổi release identity từ r1 sang r2.

## Contract-equivalence với r1

Contract test đối chiếu với snapshot của r1 đã PASS:

- Route decorators: **72**, không đổi.
- Runtime `app.view_functions` overrides: **60**, không đổi.
- Request query keys: **45 nhóm**, không đổi.
- Form keys: **67 nhóm**, không đổi.
- `request.values` keys: **1 nhóm**, không đổi.
- `url_for()` endpoint groups: **49**, không đổi.
- Sort maps: **19**, không đổi.
- Agent `deploy/agent/agent.py` SHA-256:  
  `d637ec4fa0de2e07622402e3da60ae54ccf2d3f84f046de2141c813ee3b58081`
- PostgreSQL SQL tree SHA-256:  
  `0a56aa450c979b170ba431924e4bdc515fbcea45e81583cbe33b344f451d022c`

Agent và toàn bộ `postgres/sql/*.sql` giữ nguyên byte-for-byte so với r1.

## Test đã chạy

### Pytest

Toàn bộ các test function pytest được chạy theo từng file hoặc selector để tránh chi phí parse lặp của `app.py` trong một tiến trình dài:

```text
84 passed
1 skipped: live PostgreSQL integration không có BW_TEST_DATABASE_URL
```

Các nhóm chính đã PASS:

- native COPY ingest;
- selected snapshot correctness;
- PostgreSQL LIKE compatibility;
- PostgreSQL-native maintenance;
- MAC identity/search;
- safe queue và canonical VM detail;
- low-I/O compatibility;
- Agent log contract;
- Consumption và inventory cleanup;
- r1 route/query/form/sort/Agent/SQL equivalence;
- r1 Theme/chart-gap contract;
- r2 layout-only contract.

### Direct contract scripts

Các script contract dạng top-level assertion đã PASS:

- Agent v15 single five-minute delivery;
- Consumption authentication;
- Consumption UI contract;
- custom Theme runtime;
- documentation accuracy;
- repository contract;
- Storage V2/multi-NIC;
- Theme manager;
- v50 product contract;
- VirtInfra hardening.

`test_manifest_contract.py` được chạy trong final preflight sau khi tạo manifest.

### Syntax và parser

- Python `py_compile`: **PASS**.
- Bash `bash -n`: **PASS**.
- Existing accessibility JavaScript `node --check`: **PASS**.
- CSS r2 `tinycss2`: **97 top-level rules, 0 parse errors**.
- YAML parse: chạy trong final preflight.

### Installer và full preflight

Final PostgreSQL-native preflight:

```text
PASS: VirtInfra Monitor v50 PostgreSQL Native preflight
```

Preflight exit code: **0**.

Preflight đã kiểm tra release identity, checksum manifest, generated-file/secret scan, Bash syntax, Python compile, YAML parse, source contracts, installer flow và các targeted regression test. Live PostgreSQL integration được chủ động bỏ qua vì không có disposable DSN.

Installer/operations flow:

```text
PASS: v50 GitHub/new-server/domain/operations installer flow
```

### Package clean-extraction review

- Canonical source manifest: **168 files**, fresh hashes và exact coverage.
- ZIP clean extraction: manifest PASS, **15 targeted tests passed**, `app.py` compile PASS.
- TAR.GZ clean extraction: manifest PASS, **15 targeted tests passed**, `app.py` compile PASS.
- Canonical extracted ZIP/TAR trees: **169 files**, byte-identical khi bỏ cache test sinh ra.
- External archive `SHA256SUMS`: verified.

## Browser review đại diện

Đã render bằng Chromium các fixture đại diện dùng đúng class, cấu trúc cột và CSS cuối cùng của r2 cho:

- Dashboard;
- Top VM;
- VM Consumption;
- Node Consumption;
- Node Health.

Ma trận kiểm tra:

```text
5 trang × 3 viewport × 3 mức zoom = 45 trường hợp
Viewport: 1366, 1920, 2048 px
Zoom: 100%, 125%, 150%
Body horizontal overflow: 0/45
Dashboard STATUS/SNAPSHOT overlap: 0/9
```

Ảnh Light/Dark tại 1920 px và JSON kết quả nằm trong:

```text
docs/visual-review/50.5.9-r2/
```

### Giới hạn visual review

**NOT VERIFIED AGAINST THE LIVE AUTHENTICATED APPLICATION**

Fixture review không kết nối PostgreSQL thật, không dùng session đăng nhập production và không phải screenshot từ deployment thật. Vì vậy cần kiểm tra staging/production có kiểm soát với dữ liệu thực trước rollout rộng.

## Live integration chưa chạy

- Không chạy PostgreSQL/TimescaleDB integration vì không có `BW_TEST_DATABASE_URL` trỏ tới database disposable.
- Không deploy production.
- Không restart service production.
- Không thay đổi database production.

## Những phần không thay đổi

- API endpoint, request payload và response payload.
- Flask route, endpoint name và HTTP method.
- Query parameter, sort key, sort direction và URL contract.
- Form action, method, input name, hidden field và CSRF.
- Search, filter, pagination, limit và refresh behavior.
- Agent collection, Agent queue và Agent push.
- Database schema và SQL nghiệp vụ.
- CPU, RAM, network, PPS, disk và Abuse formula.
- Severity, policy revision, retention, maintenance và queue.
- Hide, Restore và Purge behavior.
- Consumption data, rollup, cache và SQL.
- Chart-gap behavior đã có trong r1.

## Danh sách chính xác file thay đổi so với r1

### Runtime và release identity

- `VERSION`
- `app/app.py`
- `app/retention.py`
- `deploy/postgres/install-postgres-native.sh`
- `preflight.sh`
- `tools/test-installer-flow.sh`

Trong nhóm trên, chỉ `app/app.py` có CSS layout mới. Các file còn lại chỉ cập nhật release identity hoặc validation expectation.

### Test

- `tests/test_v5052_native_copy_ingest.py`
- `tests/test_v5054_snapshot_detail_correctness.py`
- `tests/test_v5055_sql_compat_hotfix.py`
- `tests/test_v5057_mac_identity_search.py`
- `tests/test_v5057_safe_queue_canonical_vm.py`
- `tests/test_v5058_r4_consumption_inventory.py`
- `tests/test_v5059_r1_ui_responsive_theme_chart_gaps.py`
- `tests/test_v5059_r2_ui_layout_polish_only.py` (mới)
- `tests/test_v50_contract.py`
- `tests/test_virtinfra_hardening.py`

Các test cũ chỉ đổi expected release identity. Test r2 mới khóa phạm vi CSS-only và các selector layout đã yêu cầu.

### Tài liệu và metadata

- `CHANGELOG.md`
- `COMMANDS_A_TO_Z_VI.md`
- `GITHUB_DESKTOP_VI.md`
- `README.md`
- `SOURCE_OF_TRUTH_VI.md`
- `START_HERE_VI.md`
- `VALIDATION_REPORT_VI.md`
- `docs/CONSUMPTION_VM_NODE.md`
- `docs/LOW_IO_UPGRADE.md`
- `docs/PUBLISHING.md`
- `docs/README_VI.md`
- `docs/STORAGE_V2_ARCHITECTURE.md`
- `docs/STORAGE_V2_AUDIT.md`
- `docs/STORAGE_V2_COMPATIBILITY_MATRIX.md`
- `docs/STORAGE_V2_DEPLOYMENT.md`
- `SHA256SUMS`

### Visual-review artifacts mới

- `docs/visual-review/50.5.9-r2/README.md`
- `docs/visual-review/50.5.9-r2/dashboard-1920-dark.png`
- `docs/visual-review/50.5.9-r2/dashboard-1920-light.png`
- `docs/visual-review/50.5.9-r2/topvm-1920-dark.png`
- `docs/visual-review/50.5.9-r2/topvm-1920-light.png`
- `docs/visual-review/50.5.9-r2/consumption-vm-1920-dark.png`
- `docs/visual-review/50.5.9-r2/consumption-vm-1920-light.png`
- `docs/visual-review/50.5.9-r2/consumption-node-1920-dark.png`
- `docs/visual-review/50.5.9-r2/consumption-node-1920-light.png`
- `docs/visual-review/50.5.9-r2/node-health-1920-dark.png`
- `docs/visual-review/50.5.9-r2/node-health-1920-light.png`
- `docs/visual-review/50.5.9-r2/layout-matrix.json`
- `docs/visual-review/50.5.9-r2/representative-results.json`

## Khuyến nghị triển khai

1. Backup source, environment và database theo quy trình hiện có.
2. Triển khai Monitor trên staging hoặc một cửa sổ có kiểm soát.
3. Kiểm tra Dashboard, Top VM, VM/Node Consumption và Node Health bằng dữ liệu thật ở Light/Dark.
4. Kiểm tra riêng STATUS/SNAPSHOT, compound headers và horizontal scrolling của table wrapper.
5. Theo dõi HTTP 500, Gunicorn và PostgreSQL sau khi cập nhật.
