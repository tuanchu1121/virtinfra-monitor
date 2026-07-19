# Diff Summary

Baseline: `50.5.9-prod-r6-node-groups-admin-bulk-management-retention-safe-maintenance-hotfix`

Release: `50.5.9-prod-r7-rbac-node-groups-node-vm-ui-refresh-hotfix-r1`

## Source changes

Before release reports and checksum regeneration:

- Tracked files changed: 25
- Tracked lines added: 1,508
- Tracked lines removed: 255
- New release-document lines: 173
- No runtime file was deleted.
- No database migration was added or changed.
- No API endpoint, agent payload, metric formula, abuse threshold, queue architecture or retention policy was changed.

The largest diff is `app/node_groups.py`, because the final active r6 Node Groups implementation is corrected in place for RBAC, visibility, direct Admin renderers, sorting and Consumption presentation. The original `app/app.py` monolith is not refactored.

## Runtime behavior intentionally changed

- Admin capability access and Super Admin stealth/protection.
- Own-account Change Password behavior.
- Hidden Node Group visibility across monitoring.
- Move all nodes to Ungrouped.
- Direct Node/VM management actions and return navigation.
- Admin Node/VM table columns, sorting and selector removal.
- Node-only group icon placement.
- Node Groups search/RAM presentation and Node Group Consumption mapping.
- Monitoring auto-refresh from 5 seconds to 30 seconds.

## Preserved behavior

- Existing endpoints and payloads.
- Agent ingest and durable retry.
- CPU, RAM, disk, network, PPS, bandwidth and Consumption formulas.
- VM Abuse detection, severity and event lifecycle.
- Maintenance queue and purge jobs.
- Retention and accounting behavior.
- PostgreSQL schema and existing Node Group data.
