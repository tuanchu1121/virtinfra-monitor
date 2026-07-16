# VirtInfra Agent

The complete Agent source is `deploy/agent/agent.py`.

Exact defaults:

```text
local network sample: 15 seconds
Monitor push:         300 seconds
```

The Agent keeps a durable pending payload. On failure it retries the exact pending payload before building a new one. The Monitor de-duplicates by Node and push time.

Install one node:

```bash
read -rsp 'VirtInfra Agent token: ' BW_TOKEN
echo

curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/install-agent.sh \
| env \
VIRTINFRA_AGENT_API='https://monitor.example.com/push' \
VIRTINFRA_AGENT_TOKEN="$BW_TOKEN" \
bash

unset BW_TOKEN
```

Check:

```bash
systemctl status virtinfra-agent.service --no-pager -l
journalctl -u virtinfra-agent.service -n 200 --no-pager
systemctl show virtinfra-agent.service -p ProtectHome --value
```

Expected `ProtectHome=read-only`. This lets the service inspect `/home` while preserving systemd hardening.
## Compact Bandwidth Consumption accounting

The same Agent process also maintains an isolated node-level accounting accumulator. It reuses the RX/TX deltas already collected for the normal 5-minute payload, so it does not add another `virsh` scan and does not create requests per VM.

Every completed local 2-hour bucket sends one compact request containing only:

```text
Physical Public RX/TX
Physical Private RX/TX
Aggregate VM Public RX/TX
Aggregate VM Private RX/TX
```

VM UUIDs are not included. Host-side tap/vnet directions are normalized to the guest perspective before aggregation, allowing Physical RX to be compared with VM RX and Physical TX with VM TX. The accumulator and retry list are persisted in `/var/lib/virtinfra-agent/runtime.json`.

Normal operation adds 12 compact requests per node per day. Deterministic jitter spreads completed-bucket sends across the first four minutes after the boundary. The existing 15-second sampling and 5-minute operational `/push` remain unchanged.

