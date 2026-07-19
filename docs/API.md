# REST API

The existing scoped REST API is preserved. Create and manage keys from Admin.

Main scopes include:

```text
abuse:read
abuse_events:read
vm:read
node:read
bandwidth:read
```

API keys support Allowed IP/CIDR, expiry, enable/disable and per-minute rate limits. Agent `/push` authentication uses the separate `BW_MONITOR_TOKEN`; do not reuse scoped REST API keys as Agent tokens.

Check identity:

```bash
curl -H 'Authorization: Bearer API_KEY' \
https://monitor.example.com/api/v1/me
```

Current Abuse:

```bash
curl -H 'Authorization: Bearer API_KEY' \
'https://monitor.example.com/api/v1/abuse/vms?limit=500'
```
