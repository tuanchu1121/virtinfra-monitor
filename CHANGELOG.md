# VirtInfra Monitor Changelog

## 50.5.9-prod-r22.12.1-preflight-contract-hotfix

- Fixed the R22.12 legacy contract preflight so the internal VM snapshot sort allow-list is not mistaken for a public sort contract.
- Approved the additive migration 019 in the feature-migration exclusion set without changing its SQL.
- No runtime, schema, UI, API or Agent behavior changes.

# 50.5.9-prod-r22.12.1-preflight-contract-hotfix

- Moved high-cardinality VM Consumption aggregation completely outside web requests.
- Added PostgreSQL `UNLOGGED` shared snapshots with one compact row per VM, period and five-minute generation.
- Added `bw-monitor-vm-consumption-snapshot.timer`; the worker builds `24H` first, then short and long ranges, using a cross-process PostgreSQL advisory lock.
- VM page requests now run only a snapshot `COUNT`, filtered `ORDER BY`, `LIMIT` and `OFFSET`; they do not build rollup CTEs and do not use `COUNT(*) OVER()`.
- Preserved canonical `vm_consumption_hourly`, `vm_consumption_daily`, packed five-minute slots, rolling windows, RX/TX formulas, UI, routes and Agent payload.
- Added settled-boundary refresh to avoid freezing a generation before normal Agent delivery jitter has arrived.
- Snapshot warm-up is asynchronous during install/update; the web service is not blocked by seven aggregate builds.
- Full backups exclude derived snapshot data, while restore restarts the timer and queues a rebuild.
- Clear Monitoring, Nuclear Reset and Node purge remove matching derived snapshot rows.

# 50.5.9-prod-r22.11-vm-slot-boundary-coverage-hotfix

- Fixed the R22.10 five-minute slot off-by-one: Agent `data_time` is treated as the end of the sampled interval.
- A push at `19:30` now belongs to `19:25-19:30`; a push at `20:00` belongs to slot 11 of the `19:00` hourly row.
- Added metadata-only migration `018_vm_consumption_slot_boundary_semantics.sql` with lazy v2 slot replacement; no bulk rewrite or raw-history backfill.
- Exact reads ignore shifted R22.10 masks, while hourly totals/sample counts provide bounded compatibility coverage during warm-up.
- Preserved raw-free rolling VM Consumption, global sort behavior, UI, Agent payload, RX/TX formulas, retention, RBAC, Backup/Restore and Nuclear.

# 50.5.9-prod-r22.6-consumption-vm-timeout-hotfix

- Added Super Admin-only selective Configuration Backup and Restore.
- Added protected pre-restore snapshots and checksum-verified archives.
- Reworked Nuclear Reset to preserve only current super_admin, current Nuclear job and one audit.
- Added optional Configuration/Full Emergency backup or strong no-backup reset.
- Added pending Node-to-Group mapping restore and Top VM 2,000-row option.

# 50.5.9-prod-r22.6-consumption-vm-timeout-hotfix

- Fixed update failure `ERROR: invalid relation type` when R21/R22 databases expose `bandwidth_hourly` and `bandwidth_daily` as compatibility views.
- `002_timescale.sql` now checks PostgreSQL `relkind` and converts only real or partitioned tables to Timescale hypertables.
- Existing views are skipped with a NOTICE; no data or schema contract is changed.
- Failed-update recovery now restarts `bw-monitor-backup.timer` together with the other quiesced timers.

# Changelog

## 50.5.9-prod-r22.6-consumption-vm-timeout-hotfix

- Consolidated Consumption business logic into canonical runtime Layer 44; Layer 45 is now a compatibility marker with no routes, functions or ingest/query implementation.
- Preserved the R21 data contract: Node, Node Group and Summary read only `node_consumption_5m`, `node_consumption_hourly` and `node_consumption_daily`; VM Consumption remains independent; RX/TX formulas and Agent payload are unchanged.
- Added raw-retention-aware Node range planning. Raw five-minute edges are clipped to available retention while the requested interval remains the coverage denominator, so 3D–7D queries no longer silently claim complete data for missing edges.
- Fixed VM Consumption caching so Group, Node, search, coverage, sort, page, page size and visibility generation are part of the cache identity.
- Replaced Top VM RAM/disk candidate sorting with PostgreSQL global sorting over existing bounded current/snapshot tables. Visibility and Group filters run before `ORDER BY`; `LIMIT` runs last; NULL values sort last with deterministic Node/UUID ties.
- Added regression execution with more than 1,500 VMs, including low-network global RAM/disk winners, hidden Nodes and Group filtering. No `vm_top_current`, dual-write or new Maintenance pipeline was introduced.
- Rejects normal `/push` payload timestamps more than the configured future-skew limit and prevents later-arriving older samples from rewinding VM/interface/Node/disk current tables.
- Treats a missing or invalid `vms` metrics section as partial collection and preserves existing VM current metrics instead of replacing them with zero/empty state. A present empty list remains a valid complete empty sample.
- Records Consumption backfill state and progress in the existing settings/status path with `running`, `completed`, `completed_with_gaps` and `failed` outcomes; the supported state contract also includes `pending`.
- Updates the updater to snapshot installed source and service configuration in addition to the PostgreSQL backup before replacing application code.
- Adds live PostgreSQL integration coverage and disposable 300-Node/60,000-VM benchmark tooling. These tests skip cleanly when `BW_TEST_DATABASE_URL` is not supplied.

## 50.5.9-prod-r21-consumption-ingest-preaggregation-hotfix

- Redesigned Consumption around ingest-time pre-aggregation. Every accepted normal five-minute `/push` incrementally UPSERTs canonical per-VM hourly/daily rollups and compact node-level five-minute/hourly/daily rollups in the same transaction.
- Canonicalized the VM pipeline as `vm_consumption_hourly` and `vm_consumption_daily`, preserving existing rows through an idempotent in-place migration and read-only compatibility views for the former names.
- Added `node_consumption_5m` for only the two incomplete range edges. Complete hours and days are read from `node_consumption_hourly` and `node_consumption_daily`.
- Embedded Physical and All-VM totals together in the Node rollups so Node, Node Group and Consumption Summary never scan `node_stats`, never read per-VM rollups and never `GROUP BY vm_uuid` while rendering.
- Made one cached Node dataset per range the source for totals, Node rows, Group rows, Physical totals, VM totals and observed differences. Cache TTL is bounded to 5–15 seconds, default 10 seconds.
- Preserved the independent VM hybrid pipeline: daily for complete days, hourly for complete hours and raw VM rows only at incomplete edges. The VM pipeline is not invoked by Node or Group tabs.
- Added a real PostgreSQL 17 `EXPLAIN (ANALYZE, BUFFERS)` validator. With 350 seeded Nodes and an unaligned 24-hour range, the plan reads about 8,050 hourly Node rows plus compact Node-edge rows, with no per-VM relation and no `vm_uuid`.
- Replaced exact `COUNT(*)` scans in the Consumption maintenance card with planner estimates to keep Operations light on large VM rollups.
- Kept Dashboard snapshots, route count, Agent cadence/payload, CPU/RAM/network/disk calculations, Abuse, Storage I/O, Queue, RBAC, Node Groups and unrelated behavior unchanged.

## 50.5.9-prod-r20-consumption-node-vm-rollup-alignment-hotfix

- Added compact hourly and daily **All VM per Node** Consumption rollups, written from the accepted normal 5-minute push in the same database transaction as the existing raw/per-VM data.
- Extended **Consumption → Node** with Physical Public/Private, All VM Public/Private, observed differences, VM reporting count, coverage and latest ingestion without changing the Dashboard.
- Rebuilt **Consumption → Node Group** on the same compact Node rollups and gave Node/Node Group tables explicit fixed column contracts to eliminate header/body drift.
- Preserved the performance tiering used at large scale: raw data for partial-hour edges, hourly rollups for complete hours and daily rollups for complete days.
- Retired the legacy Agent-side 2-hour writer with HTTP 410 while retaining its route/table contract as dormant upgrade compatibility; normal `/push` is the only active ingestion path.
- Removed the separate Consumption clear operation from the rendered Maintenance UI. **Clear All Monitoring Data** now remains the single synchronized destructive action for raw data and every Consumption rollup.
- Extended Node, all-VM-on-Node and individual-VM purge lifecycles so compact Node VM totals cannot remain stale after inventory cleanup.
- Added migration `014_node_vm_consumption_rollups.sql`, standalone backfill support and R20 regression/runtime validation.
- Preserved 83 Flask routes, Dashboard snapshots, Agent cadence/payload, CPU/RAM/network/disk formulas, Abuse, Storage I/O, Queue, RBAC, Node Groups and retention behavior outside the Consumption scope.

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

## 50.5.9-prod-r22.6-consumption-vm-timeout-hotfix
- Default `/bandwidth-consumption` to the compact Node tab; per-VM aggregation is opt-in through `tab=vm`.
- Constrain raw VM edge reads by the Timescale `node_stats.bucket` partition column as well as `last_push`, enabling chunk exclusion and preventing full retained-history scans.
- Preserve VM/Node formulas, hourly/daily rollups, routes and response contracts.
