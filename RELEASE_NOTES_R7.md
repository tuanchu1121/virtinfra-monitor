# VirtInfra Monitor 50.5.9 r7 release notes

Release: `50.5.9-prod-r7-rbac-node-groups-node-vm-ui-refresh-hotfix`

Baseline: `50.5.9-prod-r5-node-groups-hotfix-additive-schema-import-fix-production-slim`.

## Root causes fixed

- Admin capabilities were routed through a Super Admin-only allow-list, while Queue and PostgreSQL controls were rendered inside shared Overview content.
- Change Password still used the legacy global administrator credential instead of the authenticated `dashboard_users` record.
- Hidden Node Groups were removed only from selected dropdowns instead of a canonical monitoring visibility source.
- Node Group bulk `move_all_ungrouped` followed the target-required path and rejected a valid operation.
- Admin Nodes/VMs used broad HTML injection around legacy tables, producing duplicate selection controls, mismatched columns and fragile flag placement.
- Group flags were injected by broad text/HTML matching and reached VM UUIDs, VM detail controls and metric labels.
- Node Group Consumption header/body mapping and sort indexes had drifted.
- Monitoring pages retained five-second refresh intervals.

## Runtime fixes

- Capability-based Admin/Super Admin permissions with backend enforcement.
- Admin manages Viewer/Admin accounts only; Super Admin identities remain hidden and protected.
- Change Password verifies and updates only the authenticated account, preserving username and role.
- One canonical active-group visibility source is reused by Dashboard, Top VM, Node Health, Storage I/O, Consumption, VM Abuse, monitoring search and detail routes.
- Hidden groups remain manageable in Admin and Restore preserves membership.
- Move all nodes to Ungrouped no longer requires a target selection.
- Node Group search uses one input for group name, node name and current node IP data.
- Admin Nodes/VMs use direct row actions and no Selected/All Matching bulk selector.
- Admin Nodes adds current CPU, RAM, Disk I/O and Network columns/sorts from one `node_current_fast` join.
- Hide/Restore/Purge actions continue to use the existing endpoints and maintenance queue.
- Node Group flags render only with Node identity, never directly on VM UUIDs or metric labels.
- VM detail labels are restored without the erroneous `DE` prefix.
- Node Group Consumption uses aligned RX/TX/Total columns and raw numeric sorting; Apply precedes Reset.
- Monitoring auto-refresh is 30 seconds; Maintenance Queue keeps its dedicated behavior.

## Preserved behavior

No changes were made to Agent payloads or cadence, API payloads, metric formulas, Abuse thresholds/lifecycle, queue architecture, retention buckets, consumption formulas or maintenance architecture.

## Validation

- Python compile: PASS.
- Shell syntax: 45/45 PASS.
- Targeted Node Groups/RBAC/UI suite: 25 passed.
- Full pytest: 117 passed, 1 skipped, exit code 0.
- Structural UI regression: 11/11 pages PASS.
- Chromium regression: 12/12 pages PASS on desktop, tablet and mobile.
- Live PostgreSQL integration was skipped because `BW_TEST_DATABASE_URL` was not provided.

No production deployment, service restart or destructive maintenance was performed.
