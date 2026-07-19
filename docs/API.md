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

## Node Groups API

Release `50.6.0-prod-r1-node-groups-additive` adds a separate namespace. Existing API routes and existing JSON fields are not modified.

New scopes:

```text
node_groups:read
node_groups:write
```

Read endpoints require `node_groups:read`:

```text
GET /api/v1/node-groups
GET /api/v1/node-groups/<group_id>
GET /api/v1/node-groups/<group_id>/nodes
GET /api/v1/node-groups/<group_id>/vms
GET /api/v1/node-groups/<group_id>/consumption?period=24h
GET /api/v1/nodes/<url-encoded-node-name>/group
GET /api/v1/nodes/ungrouped
```

Write endpoints require `node_groups:write`:

```text
POST   /api/v1/node-groups
PATCH  /api/v1/node-groups/<group_id>
DELETE /api/v1/node-groups/<group_id>
PUT    /api/v1/nodes/<url-encoded-node-name>/group
DELETE /api/v1/nodes/<url-encoded-node-name>/group
```

Create a Group:

```bash
curl -X POST \
  -H 'Authorization: Bearer API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"name":"Tokyo Group","description":"Tokyo KVM nodes","country_code":"JP","enabled":true}' \
  https://monitor.example.com/api/v1/node-groups
```

Assign or move a Node using its exact name:

```bash
curl -X PUT \
  -H 'Authorization: Bearer API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"group_id":3}' \
  'https://monitor.example.com/api/v1/nodes/KNode-1/group'
```

Remove the membership:

```bash
curl -X DELETE \
  -H 'Authorization: Bearer API_KEY' \
  'https://monitor.example.com/api/v1/nodes/KNode-1/group'
```

The Node path is URL-decoded and matched exactly against `node_inventory.node`. IP addresses are never used to assign a Group. VM responses under the new namespace inherit Group membership through their Node; no VM membership object exists.
