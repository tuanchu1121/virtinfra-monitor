# Changelog

## 50.5.9-prod-r19-production-readiness-audit-hotfix

- Fixed Custom/preset Theme application after PJAX navigation and 30-second refresh by using one delegated browser controller.
- Added current hourly/daily Node Consumption rollups to Clear Monitoring Data and Nuclear Reset.
- Replaced the misleading legacy 2-hour accounting card with accurate current rollup storage statistics and actions.
- Quiesced web, timers and cleanup services before update schema/backfill work; active maintenance jobs now block update.
- Rewrote Consumption backfill to use a standalone PostgreSQL connection instead of importing the complete Flask runtime.
- Removed the weak fallback Agent token and added production-readiness regression coverage.

## 50.5.9-prod-r18-user-rbac-session-hardening-hotfix

- Prevents the last enabled Super Admin from being downgraded, disabled or deleted.
- Blocks every user from changing their own role/status/account from User Management; own password changes remain on the Password page and require the current password.
- Makes Create User insert-only. A duplicate username now returns HTTP 409 and can no longer overwrite passwords, roles or Super Admin accounts.
- Separates password reset from role changes; legacy R17 reset forms can no longer mutate a role.
- Adds immediate session revocation after password, role, enabled-state or account deletion changes without adding a database column.
- Restricts `/admin/setup` to the true first-user setup path. A deployment with existing users but no enabled Super Admin must be recovered from the server console, not claimed from the web.
- Adds complete Super Admin create/promote controls while keeping regular Admin limited to Viewer/Admin accounts.
- Aligns Admin UI and backend permissions: routine Consumption cleanup is allowed, full Consumption clear is Super Admin-only, audit logs are read-only for Admin, and read-only System Health JSON is accessible.
- Corrects legacy hard-coded audit entries so actions performed by the acting Super Admin are recorded as `super_admin`.
- Preserves all monitoring routes, Agent/API payloads, metric formulas, Node Groups, Queue, retention and the R17 single Operations shell.

## 50.5.9-prod-r17-operations-single-shell-hotfix

- Fixed the duplicated Operations header and tab navigation caused by stacked legacy Admin and retention page wrappers.
- Final `/admin` rendering now removes every legacy/canonical Admin hero and Admin tab block, then inserts exactly one shared Operations shell.
- Preserved the retention policy strip, all page content, forms, query parameters, Queue actions, redirects, routes and monitoring behavior.
- Retained the R16 role-aware Operations entry, Admin/Super Admin permission split and Node-only flag scope.

## 50.5.9-prod-r16-operations-node-flag-scope-hotfix

- Added a role-aware **Operations** navigation item beside VM Abuse. Viewer sessions do not see it; Admin and Super Admin do.
- Standardized the existing `/admin` pages with one Operations hero and tab shell without changing routes, forms, query parameters, monitoring UI or metric calculations.
- Restored the operator model for regular Admin: Queue visibility/cancel, routine retention, 1/2/3/7-day cleanup, online VACUUM and permanent Node/VM purge through the existing FIFO worker path.
- Kept Clear Monitoring Data, API-data deletion, Nuclear Reset, API management and Super Admin account control restricted to Super Admin at both UI and backend layers.
- Fixed Node Group flag decoration so a flag appears only beside the visible Node identity. VM UUIDs, 5m–7d periods, Both/Public/Private selectors, RX/TX/TOTAL, Mbps/PPS, SAMPLE, CPU, vCPU, RAM, disk, drops, errors and other sort/filter labels are never decorated.
- Preserved the R15 Boolean Queue migration, 83 Flask routes, Agent/API payloads, dashboard behavior, 30-second refresh and all CPU/RAM/network/disk/Abuse/Consumption/retention formulas.

## 50.5.9-prod-r15-super-admin-maintenance-queue-schema-fix

- Restricted the complete Maintenance area, Queue controls, database operations and permanent Node/VM purge actions to `super_admin`.
- Regular `admin` accounts no longer see Maintenance KPI cards or permanent purge controls, and direct requests return HTTP 403.
- Preserved regular Admin Hide, Restore, Node Group and ordinary user-management behavior.
- Corrected new-install queue schema so `maintenance_jobs.cancel_requested` is PostgreSQL `BOOLEAN NOT NULL DEFAULT FALSE`.
- Added an idempotent migration that converts legacy numeric cancel flags to Boolean without deleting Queue history.
- Added an update-time Queue insert/rollback self-test so installation stops before deployment if Boolean insertion is incompatible.
- Reloaded the dispatcher and watchdog timer safely during update without stopping active per-job worker units.
- Preserved all monitoring formulas, API/Agent payloads, routes, UI layout and retention behavior.

## 50.5.9-prod-r13-conservative-refresh30-retention-verified

### Scope

- Preserves the current UI structure, Flask routes, endpoint names, request/response payloads, database schema, Agent protocol and all monitoring calculations.
- Keeps the conservative Admin, Maintenance, Queue, Node Group visibility, purge and password correctness fixes already present in the source.
- Changes only the browser live refresh interval from 5 seconds to 30 seconds, including Node Groups.
- Fixes the release preflight reference so it invokes the test file that is actually shipped.

### Retention verification

- Latest 48 hours retain every real five-minute Agent push.
- From 48 hours through day 7, one real retained snapshot per Node and local hour is preserved.
- Historical metric rows older than 7 days are deleted while current inventory/state remains preserved.
- The release includes an executable regression test that populates points across days 1, 3, 6 and 8 and verifies the effective retention function end to end.

### Compatibility boundary

- CPU, RAM, network Mbps/PPS, disk throughput/IOPS, Consumption, Abuse, snapshot selection, Queue batching and retention formulas are unchanged.
- Static UI assets are unchanged.
- Fresh installation remains `install.sh`; update with backup preservation remains `update.sh`.
