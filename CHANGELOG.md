# Changelog

## 50.5.9-prod-r11-functional-correctness-maintenance-hotfix

### Administration and RBAC

- Admin can open User Management, Theme Settings, Account Logs, Node Logs, System Health and the Maintenance/Queue page.
- Admin can manage Viewer and Admin accounts, but Super Admin accounts remain invisible and protected.
- Change Password now updates only the currently authenticated account. It no longer changes the global/Super Admin credential.
- Routine maintenance is available to Admin. Destructive reset and Nuclear Reset remain Super Admin only.

### Node Groups and inventory

- Hiding a Node Group now applies effective visibility to its Nodes and inherited VMs across monitoring pages without deleting stored metrics.
- Admin inventory shows `hidden by group` while preserving the Node or VM's own inventory state for safe restore.
- Fixed `Move all to Ungrouped` returning `Select a Node Group`.
- Node and VM inventory tables have aligned headers/cells and sortable columns.
- Removed the `Selected nodes / All matching nodes` scope control; bulk actions operate only on checked rows.
- Node Groups uses one search field for group name, Node name and Node IP, refreshes every 15 seconds and reuses existing RAM percentage thresholds for warning/critical color.

### Purge, Queue and Maintenance

- Node/VM purge targets are hidden immediately after a FIFO job is accepted, preventing stale search/monitoring results while the worker is waiting.
- Purge queue failures restore the previous inventory state and return a visible error.
- Maintenance jobs now treat `starting` as active consistently.
- Dispatcher wake failures are written into the queued job message; the watchdog retries every minute.
- Manual history deletion accepts 1, 2, 3 and 7 days.
- Nuclear Reset verifies the active Super Admin account and returns to the Maintenance/Queue panel after preview, execution or error.

### UI correctness

- Global live-page refresh changes from 5 seconds to 30 seconds. Node Groups refresh remains independent at 15 seconds.
- Node Group flags are injected only into exact Node links, not VM UUIDs, VM detail metrics or sortable column labels.
- Node Group Consumption has fixed seven-column alignment and sorting for group, Node/VM counts and Public/Private totals.
- Existing Storage and Consumption toolbar order is preserved: `Search` then `Clear`, and `Apply` then `Reset`.

### Compatibility boundary

- Flask route count, endpoint names, Agent payload, API payload, PostgreSQL schema, SQL migrations and static assets are unchanged.
- CPU, RAM, network Mbps/PPS, disk throughput/IOPS, bandwidth Consumption, Abuse, snapshot, retention and queue calculation formulas are unchanged.
- Fresh installation remains `install.sh`; update and backup preservation remain isolated in `update.sh`.
