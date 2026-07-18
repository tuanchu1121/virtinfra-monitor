# Báo cáo kiểm thử 50.6.0 Node Groups preview

Baseline: `50.5.9-prod-r3-ui-alignment-overflow-hotfix-production-slim`.

## Đã triển khai

- Schema PostgreSQL riêng: `node_groups`, `node_group_memberships`, `node_group_membership_history`.
- Quan hệ membership chỉ dùng exact `node_name`, không dùng IP.
- Admin menu: Overview, Nodes, Node Groups, VMs, Maintenance.
- CRUD Group, ISO country code, Enabled, Hidden, Default.
- Admin Nodes: Group column, Assign/Move/Remove theo tên Node.
- Admin VMs: Group kế thừa từ Node, không có quan hệ VM → Group.
- Shared renderer thêm cờ nhỏ 16×12 cạnh các link Node trên giao diện.
- Installer copy module, migration và SVG local vào `/opt/bw-monitor`.
- Agent, payload push, API cũ, metric formula, retention và queue không bị sửa.

## Cờ local

Release chứa sẵn `JP`, `US`, `SG`, `VN` trong `app/static/flags/4x3/` và MIT license/notice. Mã khác fallback `🌐` cho đến khi thêm SVG tương ứng. Do môi trường build không thể materialize trọn archive upstream, đây chưa phải bộ SVG 4x3 đầy đủ của `flag-icons`.

## Chưa hoàn tất so với specification đầy đủ

- Group/Node filter server-side trên toàn bộ Dashboard, Top VM, Abuse, Storage và Consumption cũ.
- Group Consumption theo lịch sử membership tại từng bucket.
- Toàn bộ bộ cờ ISO từ upstream.
- Visual test trên production PostgreSQL/session thật.

Vì các mục trên chưa hoàn tất, package này là **preview source**, không nên deploy production như bản hoàn chỉnh.

## Kiểm tra

- Python compile: PASS.
- Bash syntax: PASS.
- Targeted schema/static checks: PASS.
- Existing test collection: 91 tests, 1 PostgreSQL integration skipped.
- Một test route MAC chạy riêng: PASS.
- Full suite chưa hoàn tất trong giới hạn runtime của môi trường build.
- Không deploy, không restart production.
