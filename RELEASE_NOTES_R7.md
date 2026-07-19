# Release Notes

Release: `50.5.9-prod-r7-rbac-node-groups-node-vm-ui-refresh-hotfix-r1`

Archive: `virtinfra-monitor-50.5.9-prod-r7-rbac-node-groups-node-vm-ui-refresh-hotfix-r1-production-slim.zip`

## Scope

This is a production hotfix built directly from the r6 installer-manifest-fixture-fix worktree. It does not port code from another release and does not change the metric schema, agent protocol, ingest cadence, queue architecture, retention policy, maintenance behavior, abuse formulas or monitoring calculations.

## Fixed

- Admin can use User Management, personal Theme Settings, Account Logs, Node Logs and System Health.
- Admin cannot see or directly access Queue, PostgreSQL Data, privileged maintenance, retention or database controls.
- Admin can manage Viewer and Admin accounts but receives a non-disclosing response for Super Admin records.
- Change Password verifies the current password and changes only the logged-in account without changing its role.
- Hidden Node Groups and inherited Node/VM inventory disappear from normal monitoring, search, details, Storage, Consumption and VM Abuse while remaining manageable in Admin.
- Move all to Ungrouped no longer asks for a target group.
- Node and VM Hide, Restore and Purge use direct row actions and the existing purge queue.
- Admin Nodes and Admin VMs no longer contain Selected/All matching bulk selectors.
- Admin Nodes has safe sorting for Node, Group, Public IP, Status, Last Push, VM count, CPU, RAM, Disk and Network.
- Admin VMs has safe sorting for Node, Group, UUID, Status/Seen and Bridge/Interface.
- Node Group icons appear with Node identity only, not VM UUID or metric headers.
- Node Groups uses one search field for group, node and IP; Node Group RAM uses existing severity helpers.
- Storage keeps Search followed by Clear. Consumption keeps Apply followed by Reset.
- Node Group Consumption has fixed eight-column mapping and raw-value sorting.
- Monitoring auto-refresh is 30 seconds. Maintenance Queue refresh remains independent.

## Validation

- Python compile: PASS.
- Targeted Node Groups/RBAC tests: 25 passed.
- Full pytest: 117 passed, 1 skipped, exit code 0.
- The skipped test requires an explicit disposable PostgreSQL integration DSN.
- Scoped UI render checks passed for column counts, obsolete selector removal, icon placement, control order and 30-second refresh.

## Operational note

Purge removes the selected monitoring data through the existing queue. If a VM still exists on the hypervisor and the agent reports it again, the existing discovery flow may create it again. Use Hide for inventory that still exists but should remain absent from normal monitoring.
