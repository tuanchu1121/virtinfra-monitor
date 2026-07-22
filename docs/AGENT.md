# VIRTINFRA AGENT

## Runtime path

```text
Service: virtinfra-agent.service
Source: /usr/local/lib/virtinfra-agent/agent.py
Environment: /etc/virtinfra-agent.env
State: /var/lib/virtinfra-agent/state.json
Runtime: /var/lib/virtinfra-agent/runtime.json
Doctor: /usr/local/sbin/virtinfra-agent-doctor
```

## Mặc định

```text
Local sample: 15 giây
Operational push: 300 giây
Consumption: được Monitor rollup từ cùng payload 5 phút
Bridge roles: public:br0,private:br1
```

## Cài thủ công

```bash
read -rsp 'Nhap VirtInfra Agent token: ' VIRTINFRA_TOKEN
echo

curl -fsSL https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/install-agent.sh | env VIRTINFRA_AGENT_API='https://monitor.example.com/push' VIRTINFRA_AGENT_TOKEN="$VIRTINFRA_TOKEN" BW_AGENT_BRIDGE_ROLES='public:br0,private:br1' bash

unset VIRTINFRA_TOKEN
```

## Kiểm tra

```bash
virtinfra-agent-doctor
systemctl status virtinfra-agent.service --no-pager -l
journalctl -u virtinfra-agent.service -n 300 --no-pager
```

## Consumption

Agent không còn gửi payload Consumption 2 giờ riêng. Dữ liệu VM và physical
trong `/push` 5 phút được Monitor ghi raw và tổng hợp thành hourly/daily rollup.
Nhờ đó VM, Node và Node Group dùng cùng một nguồn dữ liệu đã được chống trùng.

## Update

Chạy lại installer với API, token và bridge roles đúng. Không dùng `--reset-state` khi update bình thường.

## Gỡ, giữ state

```bash
curl -fsSL https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/uninstall-agent.sh | bash -s -- --keep-state
```

## Sửa Node identity hoặc state UUID mà không cài lại Agent

Đổi tên node mà Agent gửi lên Monitor:

```bash
curl -fsSL https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/fix-agent-uuid.sh \
| bash -s -- --node NEW-NODE-NAME
```

Xóa riêng state cũ của một VM UUID để Agent đọc lại UUID thật từ libvirt ở chu kỳ kế tiếp:

```bash
curl -fsSL https://raw.githubusercontent.com/tuanchu1121/virtinfra-monitor/main/fix-agent-uuid.sh \
| bash -s -- --purge-vm OLD-VM-UUID
```

Có thể thực hiện cả hai trong một lần:

```bash
bash ./fix-agent-uuid.sh --node NEW-NODE-NAME --purge-vm OLD-VM-UUID
```

Script sao lưu `/etc/virtinfra-agent.env`, `state.json` và `runtime.json`, chỉ xóa counter/payload liên quan UUID được chọn rồi restart `virtinfra-agent.service`. Script không sửa UUID trong libvirt và không cài lại Agent.

## Chấp nhận token Agent cũ trên Monitor

Thêm token cũ vào `/etc/default/bw-monitor`:

```bash
sudoedit /etc/default/bw-monitor
# BW_MONITOR_LEGACY_TOKENS='old-token-1,old-token-2'

systemctl restart bw-monitor.service
```

`/push` chấp nhận token chính và token legacy. Endpoint
`/push/bandwidth-consumption` đã retired và trả HTTP 410.


## Friendly operational logs

The Agent emits one neutral line after a successful five-minute delivery:

```text
virtinfra-agent cycle complete node=NODE delivery=ok interfaces=215 vms=215 host=1 load=normal collection=complete details=0 samples=good:215
```

Words such as `ERROR` and `unavailable` are reserved for delivery failures where the operational payload remains queued for retry. A successful delivery never prints `errors=N` or a `health warnings` line.

Bridge discovery is optional by default. Valid nodes may expose only one bridge, no `br1`, or a different topology. Missing configured bridge names are recorded as neutral Agent health notes and do not make the successful cycle partial.

```bash
BW_AGENT_BRIDGE_ROLES='public:br0,private:br1'
BW_AGENT_REQUIRED_BRIDGE_ROLES=''
```

To explicitly require bridge roles on a particular group of nodes:

```bash
BW_AGENT_REQUIRED_BRIDGE_ROLES='public,private'
```

This setting changes only bridge-health classification. It does not change VM metrics, bandwidth Consumption, the five-minute schedule, state files, gzip transport, or monitor payload compatibility.
