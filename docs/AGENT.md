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
Consumption bucket: 2 giờ
Consumption jitter: tối đa 240 giây
Bridge roles: public:br0,private:br1
```

## Cài thủ công

```bash
read -rsp 'Nhap VirtInfra Agent token: ' VIRTINFRA_TOKEN
echo

curl -fsSL https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/install-agent.sh | env VIRTINFRA_AGENT_API='https://monitor.example.com/push' VIRTINFRA_AGENT_TOKEN="$VIRTINFRA_TOKEN" BW_AGENT_BRIDGE_ROLES='public:br0,private:br1' bash

unset VIRTINFRA_TOKEN
```

## Kiểm tra

```bash
virtinfra-agent-doctor
systemctl status virtinfra-agent.service --no-pager -l
journalctl -u virtinfra-agent.service -n 300 --no-pager
```

## Consumption

Agent cộng local và gửi một payload tổng theo node cho mỗi bucket 2 giờ. Payload gồm Physical Public/Private RX/TX và tổng VM Public/Private RX/TX. Không gửi UUID VM.

## Update

Chạy lại installer với API, token và bridge roles đúng. Không dùng `--reset-state` khi update bình thường.

## Gỡ, giữ state

```bash
curl -fsSL https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/uninstall-agent.sh | bash -s -- --keep-state
```
