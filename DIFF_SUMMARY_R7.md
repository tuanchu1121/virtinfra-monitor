# r7 diff summary

Baseline: `50.5.9-prod-r5-node-groups-hotfix-additive-schema-import-fix-production-slim`  
Target: `50.5.9-prod-r7-rbac-node-groups-node-vm-ui-refresh-hotfix`

## File summary

- Added: **270**
- Modified: **36**
- Deleted: **0**
- Text lines added: **20511**
- Text lines removed: **4418**
- Binary files changed: **0**

## Runtime scope

- Active RBAC, User Management and Change Password implementations.
- Canonical Node Group visibility and monitoring filters.
- Active Admin Nodes/VMs renderers and existing action endpoints.
- Node Group monitoring, Consumption presentation and scoped flag rendering.
- Existing 30-second monitoring refresh constant and route list.
- Additive Node Group safety migration and local flag assets.

## Explicitly preserved

Agent ingest and cadence, API payloads, metric formulas, Abuse thresholds and lifecycle, maintenance queue architecture, retention buckets and consumption formulas were not redesigned.

See `FILES_CHANGED_R7.txt` for the complete path list.
