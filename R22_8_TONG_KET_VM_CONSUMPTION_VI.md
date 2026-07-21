# Tổng kết R22.8 VM Consumption

## Nền source

Bản này được phát triển trực tiếp trên **R22.7 mới nhất**. Không quay source về 50.5.9 và không loại bỏ các hardening, quyền, Node Groups, Maintenance, Top VM, backup hay các chức năng đã có trong R22.7.

Cơ chế VM Consumption của 50.5.9 chỉ được dùng làm mẫu cho cách chia khoảng thời gian chính xác và cách trình bày bảng.

## Cơ chế VM Consumption mới

VM Consumption dùng một kế hoạch kết hợp có giới hạn:

```text
Ngày tròn                 -> vm_consumption_daily
Giờ tròn còn lại          -> vm_consumption_hourly
Hai mép giờ chưa tròn     -> node_stats, chỉ đúng đoạn mép
```

Ví dụ một khoảng 7 ngày không quét raw toàn bộ 7 ngày. Nó lấy các ngày tròn từ daily, các giờ tròn còn lại từ hourly và chỉ đọc raw ở hai đoạn chưa tròn giờ.

Raw edge được lọc đồng thời bằng:

```text
bucket
last_push
```

`bucket` giúp TimescaleDB loại các chunk không liên quan. `last_push` giữ đúng semantics dữ liệu accepted sample hiện tại.

## Độ chính xác đã sửa

- Giữ nguyên công thức RX/TX hiện tại.
- Guest RX vẫn bằng host tap TX; Guest TX vẫn bằng host tap RX.
- Không cộng chồng daily, hourly và raw.
- All VM cộng các segment lịch sử cùng `vm_uuid` trên các Node active; Group cộng các segment còn nằm trong scope Group đang chọn.
- Khi lọc một Node, số liệu vẫn chỉ tính phần traffic phát sinh trên Node đó.
- Coverage dùng bridge được cấu hình có coverage thấp nhất, không dùng bridge đầy đủ nhất để che mất bridge đang thiếu dữ liệu.
- NIC đã bị gỡ khỏi inventory hiện tại không làm mất traffic lịch sử tương ứng.

## Lọc và sắp xếp

Node và Node Group được kết hợp rồi đẩy xuống từng nhánh daily/hourly/raw trước khi aggregate. Chọn Node không thể bỏ qua Group đang chọn; dropdown Node cũng chỉ hiện các Node active trong Group đó. Group nhỏ không còn bắt buộc tổng hợp toàn hệ thống rồi mới lọc.

Tất cả chỉ số sau được sort trên **toàn bộ tập VM đã lọc**, sau đó mới phân trang:

- VM UUID
- Node
- Public RX
- Public TX
- Public Total
- Private RX
- Private TX
- Private Total
- Coverage
- Latest Sample

Có tie-break theo Node và UUID để các trang không nhảy thứ tự khi hai VM có cùng giá trị. Mốc query được chuẩn hóa theo TTL R22.7 nên cache 5–15 giây có thể tái sử dụng kết quả, không miss theo từng giây.

## Căn chỉnh giao diện

- Bảng VM dùng fixed layout để tránh cột co giãn thất thường.
- Cột số căn phải thống nhất.
- Header và dữ liệu cùng độ rộng.
- Text dài được ellipsis, không đẩy bảng tràn khỏi khung.
- Giữ nguyên giao diện tổng thể, filter, form, endpoint và luồng thao tác hiện tại.

## Những phần không thay đổi

- Không sửa Agent.
- Không tăng tác vụ hoặc request trên Agent.
- Không đổi `/push` và ingest.
- Không thêm hoặc đổi database schema.
- Không đổi retention.
- Không đổi Node Consumption, Node Group Consumption hoặc Summary pipeline.
- Không đổi công thức network.
- Không đổi API endpoint hoặc payload.
- Không đổi Top VM, Dashboard, Storage I/O, Maintenance, backup hay RBAC ngoài phạm vi VM Consumption.

## Phạm vi source thay đổi chính

- Thêm `app/runtime_layers/46_vm_consumption_exact_window.py` làm runtime layer cuối trên R22.7.
- Cập nhật ghi chú UI trong `app/runtime_layers/39_inventory_consumption_views.py`.
- Cập nhật runtime manifest, version, README, changelog và tài liệu Consumption.
- Thêm `tests/test_r22_8_vm_consumption_exact_window.py`.
- Cập nhật các contract test có khóa cứng layer/version cuối.

## Giới hạn cần hiểu đúng

Đây không phải cơ chế cumulative checkpoint “mép gần trừ mép xa”. Source hiện tại không có bảng checkpoint tích lũy và bản này cố ý không đổi schema hoặc Agent.

Khoảng 1H chính xác có thể đọc raw tối đa một giờ khi cả khoảng nằm trong các mép chưa hoàn chỉnh. Khoảng dài vẫn chỉ đọc raw ở hai mép, không quét raw toàn khoảng.

Không có benchmark PostgreSQL production thật trong gói nếu `BW_TEST_DATABASE_URL` không được cung cấp. Contract, syntax, manifest, SQL parameter binding và test logic được kiểm tra offline; hiệu năng tuyệt đối trên dữ liệu production vẫn cần quan sát sau rollout có kiểm soát.

## Rollback

Layer 46 là lớp cuối độc lập. Rollback an toàn là cài lại nguyên gói R22.7 trước đó. Không cần rollback Agent hoặc migration database vì bản R22.8 không đổi hai phần này.
