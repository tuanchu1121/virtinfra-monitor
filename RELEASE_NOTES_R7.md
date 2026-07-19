# VirtInfra Monitor 50.5.9 prod-r7

Release: `50.5.9-prod-r7-production-minimal-rbac-visibility-ui-hotfix`

Baseline: `50.5.9-prod-r6-node-groups-admin-bulk-management-retention-safe-maintenance-hotfix`.

## Included fixes

- Capability-scoped Admin access to Overview, users, themes, account/node logs, system health, Nodes, VMs and Node Groups, while privileged database/queue/retention surfaces remain backend-forbidden.
- Admin management of Viewer/Admin accounts without any ability to create, elevate, reset, disable, delete or edit a Super Admin.
- Session-bound Change My Password for Viewer, Admin and Super Admin; only `dashboard_users.password_hash` and `updated_at` for the current user are changed.
- One active-group visibility rule across Dashboard, Top VM, Node Health, Storage, Consumption, VM Abuse, monitoring search and Node/VM detail navigation.
- Hidden groups remain fully visible and movable in Admin, with `GROUP HIDDEN` separate from live Agent state.
- Fixed `move_all_ungrouped`, one Node Groups search field (group/node/IP), shared RAM severity and 30-second refresh.
- Direct Admin Node/VM row actions, aligned columns, Node sorting and no Node/VM bulk selection UI.
- Node Group icon limited to Node/Group context; empty image alternative text prevents country-code prefixes on broken assets.
- Correct Node Groups Consumption mapping for Group, Nodes, VMs, RX, TX, Total, CPU, RAM and Disk with filter-preserving sorting.

## Explicitly unchanged

No API route/payload, database schema, Agent ingest, queue architecture, purge worker, retention, maintenance, Abuse policy/event logic, metric formula, theme system or frontend framework was changed. No production deployment, restart or destructive maintenance was performed.

