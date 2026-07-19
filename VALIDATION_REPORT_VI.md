# Báo cáo kiểm thử VirtInfra Monitor 50.5.9 r3

**Release:** `50.5.9-prod-r3-ui-alignment-overflow-hotfix`  
**Baseline:** `50.5.9-prod-r2-ui-layout-polish-only`

## Phạm vi sửa

Bản này chỉ sửa lớp trình bày và điều khiển giao diện đã thảo luận:

- Dashboard Nodes: căn lại header/số liệu và giữ cột `INTERFACE` trong khung.
- Top VM: giữ Node/UUID theo cách hiển thị cũ; CPU, RAM và Storage bar cùng chiều dài, cùng tâm.
- VM Consumption và Node Consumption: colgroup cố định, header hai tầng khớp body, ô Search gọn hơn.
- Node Health: tăng inset cột Node và thêm vùng cuộn nội bộ.
- Theme: một ô duy nhất chứa Auto, Light, Dark và toàn bộ theme đã cấu hình; bỏ ô Style khỏi UI thực tế.
- Bảng rộng: body không cuộn ngang, chỉ `.table-wrap` được cuộn và nội dung không tràn qua viền card.

Không thêm tính năng kéo thả, resize, ẩn/hiện cột hoặc cấu hình layout.

## Kiểm tra contract

- Route, endpoint, HTTP method, query parameter, form field/action và sort contract: **PASS**.
- Agent `deploy/agent/agent.py` so với baseline r2: **byte-for-byte unchanged**.
- PostgreSQL SQL so với contract baseline: **byte-for-byte unchanged**.
- Không thêm route hoặc câu lệnh `CREATE/SELECT/INSERT/UPDATE/DELETE` trong lớp r3.
- Consumption body, sort link, pagination và dữ liệu vẫn được giao cho implementation r2 hiện có; r3 chỉ chèn `colgroup` vào HTML đã render.
- Node Health vẫn gọi nguyên renderer cũ rồi chỉ bọc bảng bằng `.table-wrap`.
- LocalStorage key theme cũ được giữ nguyên để tương thích trình duyệt đang dùng.

## Test tự động

Kết quả suite pytest không có live PostgreSQL:

```text
91 passed, 1 skipped
```

`1 skipped` là PostgreSQL integration vì không có `BW_TEST_DATABASE_URL` trỏ tới database disposable.

Các kiểm tra riêng của r3:

```text
7 passed
```

Bao gồm:

- release identity;
- một Theme select duy nhất;
- Consumption colgroup và toolbar;
- ba resource bar Top VM có cùng chiều dài;
- Dashboard/Node Health alignment;
- table overflow containment;
- không đăng ký route hoặc SQL mới.

## Syntax, parser và final preflight

- `app/app.py` Python `py_compile`: **PASS**.
- Unified Theme JavaScript `node --check`: **PASS**.
- CSS r3 `tinycss2`: **90 top-level rules, 0 parse errors**.
- Bash syntax cho toàn bộ shell script: **PASS**.
- YAML workflow và Ansible: **PASS**.
- One-command installer/operations flow: **PASS**.
- Canonical source manifest với đường dẫn `./...`: **PASS, 156 source files**.
- `./preflight.sh --use-current-python --skip-live`: **PASS**.

## Browser fixture review

Đã render Chromium bằng đúng ba lớp CSS cuối `V5058R5_UI_CSS`, `V5059R2_UI_CSS`, `V5059R3_UI_CSS` với cấu trúc đại diện cho:

- Theme control;
- Dashboard Nodes;
- Top VM;
- VM Consumption;
- Node Consumption;
- Node Health.

Ma trận:

```text
2 themes × 3 viewport × 3 zoom = 18 cases
Themes: Light, Dark
Viewport: 1366, 1920, 2048 px
Zoom: 100%, 125%, 150%
Failed: 0/18
```

Các assertion browser:

- body horizontal overflow bằng 0;
- mọi `.table-wrap` nằm trong card;
- Consumption header con khớp đúng biên cột body;
- CPU/RAM/Storage track có cùng chiều rộng và cùng tâm cell;
- Dashboard Interface không vượt biên table/wrapper;
- Node Health có inset trái đúng;
- chỉ có một `#unified-theme-select` và không có nhãn Style.

Các fixture, ảnh chụp và kết quả browser review đã được dùng trong quá trình kiểm thử nhưng **không được đưa vào gói production slim**. Thư mục `docs/visual-review/` được loại khỏi archive để tránh làm tăng dung lượng; việc này không thay đổi source runtime.

## Giới hạn visual review

**NOT VERIFIED AGAINST THE LIVE AUTHENTICATED APPLICATION**

Fixture không kết nối PostgreSQL thật, không dùng session production và không đại diện cho dữ liệu production đầy đủ. Không deploy và không restart production trong quá trình tạo release.

## Phần không thay đổi

- API endpoint và payload.
- Agent collection, queue, push cadence và retry.
- Database schema, migration và SQL nghiệp vụ.
- CPU, RAM, network, PPS, disk, Coverage và Abuse formula.
- Search, filter, pagination, refresh và sort behavior.
- Retention, maintenance, queue, hide/restore/purge.
- Consumption rollup, cache và timezone behavior.

## Đóng gói production slim

Gói production slim loại trừ duy nhất các thành phần không cần cho runtime:

```text
docs/visual-review/
__pycache__/
.pytest_cache/
*.pyc
*.pyo
```

Ngoài `SHA256SUMS` và nội dung báo cáo kiểm thử được cập nhật để phản ánh gói slim, các file source runtime còn lại giữ nguyên byte-for-byte so với release r3 đầy đủ.
