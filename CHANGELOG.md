# 50.6.0-prod-r1-node-groups-country-flags

Baseline trực tiếp: `50.5.9-prod-r2-ui-layout-polish-only`.

## Thay đổi riêng của r3

- Theme: gộp Auto, Light, Dark và toàn bộ theme đã cấu hình vào một ô `Theme`; giao diện không còn ô `Style`. Giữ nguyên các localStorage key cũ để không làm mất lựa chọn của trình duyệt.
- Dashboard Nodes: căn cùng trục header và số liệu, cân lại phần cuối bảng, giữ `INTERFACE` trong khung và không để nội dung tràn qua viền khi cuộn.
- Top VM: giữ cách hiển thị Node/UUID của code cũ; căn giữa CPU, RAM và Allocated/Assigned; đặt ba progress bar cùng chiều dài 136 px và cùng tâm cột.
- VM Consumption và Node Consumption: thêm colgroup trình bày cố định để hai tầng header khớp tuyệt đối với body; thu gọn ô Search và cân lại toolbar.
- Node Health: bọc bảng trong vùng cuộn nội bộ, tăng inset cột Node và cân lại tám cột hiện có.
- Tất cả bảng rộng: chỉ vùng `.table-wrap` cuộn ngang; body không tràn ngang, cell và phần tử con bị giới hạn trong viền bảng.
- Không thêm tính năng mới, không đổi route, endpoint, query parameter, sort key, form action, payload, SQL, công thức, retention, queue, Abuse, Agent hay luồng push.

# 50.5.9-prod-r2-ui-layout-polish-only

Baseline trực tiếp: `50.5.9-prod-r1-ui-responsive-theme-chart-gaps`.

## Thay đổi riêng của r2

- Chỉ bổ sung một lớp CSS presentation cuối cùng, không thêm JavaScript, route, endpoint, form, query parameter, sort key, SQL, API hay luồng backend mới.
- Dashboard: dành đủ chiều rộng cho `STATUS` và `SNAPSHOT`, loại bỏ hiện tượng chữ đè nhau; giữ nguyên 18 cột và thứ tự hiện tại.
- Top VM: thu gọn cột `#`, Node, UUID và IFACES; căn giữa CPU/RAM/Disk Capacity; giữ `ALLOC · ASSIGNED · % · SLOTS` trên một hàng.
- VM Consumption: nới VM/UUID và Node/IP, cân lại sáu cột Public/Private, Coverage và Latest Sample; toolbar vẫn dùng nguyên form/action/parameter.
- Node Consumption: cân lại Node/IP, Physical Public/Private, Coverage, Latest Sample và grid toolbar không có Node filter.
- Node Health: tăng khoảng cách mép trái cho Node/IP và cân lại tám cột hiện có.
- Không thêm tính năng kéo thả, resize, ẩn/hiện cột hoặc cấu hình layout.

## Phần kế thừa nguyên vẹn từ r1

- Theme Auto/Light/Dark, chart gap segmentation, snapshot collapse và presentation filter `guestfs-*`.
- Inventory deadlock cleanup worker/timer và `/push` deadlock retry.
- Agent v15, five-minute metrics, Consumption rollups và Storage filtered-node hotfix.
- Abuse, CPU/RAM/network/PPS/disk formula, retention, queue, authentication và API contract.

# 50.5.8-prod-r3-consumption-vm-node

- Replaced only the effective Consumption page with separate **VM Consumption** and **Node Consumption** tabs.
- Added the fixed ranges `1H`, `2H`, `6H`, `12H`, `24H`, `2D`, and `7D`; the default is `24H` and the page uses the monitor's existing timezone without adding a timezone selector.
- Added four range-aware overview cards: Physical Public, Physical Private, VM Public, and VM Private, each with RX, TX, and Total.
- VM rows reuse existing `bandwidth_hourly` and `bandwidth_daily` data, normalize tap direction to the guest perspective, aggregate across migrations by UUID, and do not create a second VM history table.
- VM search supports UUID, current node, node public IP, and VM MAC while displaying only UUID and Node / Node IP.
- Node rows show aggregate Physical Public and Physical Private RX/TX/Total from existing physical history and compact 2-hour accounting; no Difference or fixed Card 1/Card 2 columns are shown.
- Added server-side sorting, pagination, Coverage filtering, and `100 / 200 / 500` row limits above the table. Default sorting is VM Public Total descending or Node Physical Public Total descending.
- Agent collection, `/push`, `/push/bandwidth-consumption`, Abuse, Dashboard, Top VM, Storage I/O, Node Health, retention, maintenance, database write paths, and five-minute scheduling are unchanged.

# 50.5.8-prod-r2-friendly-agent-logs

- Agent success logging is now a single neutral `cycle complete ... delivery=ok` line.
- Missing bridges are optional by default and no longer increase `agent_health.errors`.
- Added `BW_AGENT_REQUIRED_BRIDGE_ROLES` for installations that intentionally require specific bridge roles.
- Actual delivery failures retain payload/bucket state and are the only normal path that emits `ERROR`.
- No changes to metrics, Consumption, gzip, API payload, database, UI, state files, or five-minute scheduling.

# 50.5.8-prod-r1-low-io-compatible

- In-place upgrade from 50.5.7; no UI, API, metric formula, 5-minute schedule, retention or queue behavior changes.
- Adds backward-compatible gzip request bodies for Agent v14 while accepting plain JSON from existing agents.
- Moves MAC search indexing to write-on-change identity lookup tables and removes MAC indexes from hot metric rows.
- Removes volatile current-state indexes that were rewritten every push, adds a partial active-Abuse index, and applies HOT/autovacuum table settings.
- Adds configurable PostgreSQL max/min WAL sizing while retaining WAL compression and 15-minute checkpoint smoothing.
- Fixes PostgreSQL integration-test collection to skip cleanly when BW_TEST_DATABASE_URL is absent.

## 50.5.7-prod-r3-mac-push-hotfix

- Fixed the MAC bridge UPSERT table reference that caused all `/push` requests to roll back in the initial MAC release.
- Persisted each VM virtual NIC MAC from the existing libvirt Agent payload in `vm_iface_current` without enabling legacy raw `usage` writes.
- Persisted the physical uplink MAC associated with the public/private `br0` and `br1` roles in `node_physical_net_latest`; the existing bridge-device MAC remains available separately in `node_bridge_addresses_latest`.
- Added normalized MAC search across Dashboard, Node Health, Top VM direct lookup and Admin inventory. Colon, hyphen, Cisco dotted and compact MAC forms resolve to the same canonical address.
- Added a VM Network Identity card showing Interface, MAC, VM UUID, Node, Bridge and last-seen time for every current NIC.
- Added physical-uplink MAC badges to Node detail and additive migration `008_mac_identity_search.sql`.
- Existing Agents require no reinstall. Empty MAC fields populate on the next accepted Agent push.

## 50.5.7-prod-r1-safe-queue-canonical-vm

- Replaced the one-row Maintenance gate with a PostgreSQL FIFO queue. Multiple routine jobs can wait; one dispatcher atomically claims one `starting/running` worker with `FOR UPDATE SKIP LOCKED`.
- Added 30-second worker heartbeats, a one-minute systemd watchdog, stale-unit recovery, queued-job cancellation and automatic dispatch of the next job.
- Automatically cancels retired `clear_live_cache` and `checkpoint` rows so old jobs cannot block Maintenance or retention after upgrade.
- Rebuilt the nuclear operational reset as a two-step flow: Admin password, read-only preview, server-enforced 15-second safety delay, expiring one-time phrase, empty-queue enforcement, verified PostgreSQL backup, short allow-listed TRUNCATE phase, `/livez` plus `/healthz` checks and permanent success/failure audit after backup.
- Nuclear reset now preserves `maintenance_jobs` and `maintenance_nuclear_audit`; it never erases its own execution trail and it cannot wait behind another job.
- Fixed Dashboard UUID resolution so the freshest current Node wins over stale `vm_location_latest` records and a direct UUID search no longer inherits one old bridge/interface.
- Fixed VM detail CPU where normalized Full CPU was divided by vCPU a second time, such as 100% on a 7-vCPU VM being displayed as 14.3%.
- Live 5-minute VM and Node detail now read CPU, RAM, network, host and storage from the same bounded current tables as Dashboard/Top VM. Historical RAM uses the same exact retained bucket as CPU/network/disk.
- Aligned multi-NIC historical peak/sample semantics with current Top VM, and made guest-assigned disk capacity the primary value while host allocation remains a separate field.
- Added canonical plus legacy Agent token validation through `BW_MONITOR_LEGACY_TOKENS` for both `/push` and `/push/bandwidth-consumption`, plus reset acceptance epochs that acknowledge but ignore old local retry payloads, so old Agents can continue without reinstalling or resurrecting cleared data.
- Added `fix-agent-uuid.sh` to change the Agent node identity or purge stale state for one VM UUID without reinstalling the Agent.
- Added migration `007_safe_maintenance_queue.sql`, dispatcher/watchdog systemd units and regression coverage for queue, nuclear safety, UUID resolver, CPU, RAM, disk, multi-NIC and Agent repair behavior.

## 50.5.6-prod-r1-postgres-native-maintenance

- Rebuilt Admin Maintenance around PostgreSQL-native operations instead of legacy compatibility no-ops.
- Removed the misleading `Checkpoint` and `CLEAR LIVE 5M` controls from the main Maintenance page.
- Added a dedicated `maintenance_native.py` module so VACUUM and destructive resets do not depend on Flask request code.
- Made normal `VACUUM (ANALYZE)` fully online on a dedicated autocommit connection with `statement_timeout=0`; Gunicorn and Agent ingestion remain available.
- Made `Delete history + VACUUM` stay online from start to finish.
- Replaced row-by-row full resets with atomic `TRUNCATE ... RESTART IDENTITY CASCADE`, including Abuse incidents, disk summaries, Consumption and Storage V2 history.
- Added PostgreSQL advisory locking and a partial unique index so only one queued/running maintenance job can exist across all Gunicorn workers.
- Made targeted node/VM purge use the same per-node advisory-lock namespace as `/push`, preventing purge-versus-ingest races for the same node.
- Prevented maintenance and retention imports from running startup inventory cleanup or backfill side effects.
- Preserved dashboard users and Admin settings according to each reset level, and documented exactly what every action deletes or preserves.
- Kept the 50.5.5 native `CREATE TABLE ... (LIKE ...)` SQL compatibility fix, the 50.5.4 selected-snapshot correctness changes and the 50.5.2 native COPY ingest path.
- Added migration `006_postgres_native_maintenance.sql` and regression coverage for queue locking, online VACUUM, complete reset registries and Maintenance UI contracts.

# Changelog

## 50.5.2-prod-r1-native-copy-ingest

- Replaced JSONB recordset ingestion on the primary `/push` path with Psycopg native `COPY FROM STDIN` stages for VM network, VM performance, presence, current tables, disk current and Abuse state batches.
- Merged network and VM performance into `vm_latest_metrics` once per VM using PostgreSQL `MERGE`, preserving partial-source fields without sentinel values.
- Preserved Asia/Ho_Chi_Minh hourly/daily bandwidth bucket boundaries in the set-based writer.
- Added a lean write-index profile that keeps lookup/default-rank indexes and removes high-churn metric-sort btrees from bounded current tables.
- Added per-stage `push_perf` timings for presence, COPY, merge, latest, disk current, current/Abuse and commit.
- Agent payload, API routes, Dashboard, Abuse, Consumption, retention and Storage V2 defaults remain compatible with 50.5.0.

## 50.5.0-prod-r1-batched-ingest

- Replaced common VM presence/location N+1 writes with set-based PostgreSQL operations.
- Batched `vm_iface_current`, `vm_current_fast`, `node_current_fast`, and authoritative abuse-state UPSERTs through one JSONB recordset statement per table.
- Persisted balloon RAM fields in the main current UPSERT, removing two extra UPDATEs per VM.
- Replaced destructive disk-summary rebuilds with differential UPSERT plus stale-row deletion.
- Disabled Storage V2 dual-write/read/raw defaults while keeping the feature flags and existing V2 data available.
- Added `tools/ingest-performance-status.sh` for active-query and write-churn diagnostics.
- Preserved Agent payload, abuse policy semantics, migration confirmation, dashboard routes, Consumption, and legacy history readers.

## 50.4.9-prod-r1-professional-theme-suite

- Protects the original dashboard `Auto`, `Light`, and `Dark` modes. Admin theme settings no longer overwrite their CSS or default behavior.
- Replaces the single shared palette with an admin-only custom theme library stored in PostgreSQL `admin_settings` under `custom_theme_library_v2`.
- Publishes only enabled custom themes to a separate dashboard selector. Each browser keeps its own custom choice while retaining its original core mode preference.
- Adds create, edit, publish/hide, duplicate, delete, and reset workflows for custom themes. Disabled or deleted selections automatically fall back to the user's core Auto/Dark/Light choice.
- Adds seven built-in monitoring-style templates: VirtInfra Ocean, Grafana Inspired, Zabbix Inspired, Datadog Inspired, Prometheus Inspired, NOC High Contrast, and Dense Operations.
- Adds typography, table density, card spacing, border radius, shadow, chart line width, palette, RX/TX, and semantic-state controls per custom theme.
- Keeps Agent, push APIs, Abuse, Storage V2, Consumption, retention, and existing dashboard data behavior unchanged.

## 50.4.6-prod-r1-theme-manager

- Added an Admin `Theme Manager` page at `/admin/theme` for application-wide palette management.
- Added five built-in production presets: Neutral Blue, Slate Indigo, Emerald, Graphite and Warm Amber.
- Added independent Light and Dark palettes for background, panel, soft panel, header, text, muted text, border and accent colors.
- Added shared RX, TX, Success, Warning and Danger colors used across charts, controls and status components.
- Preserved the existing per-browser Auto, Dark and Light switch while allowing Admin to choose the default appearance for new browsers.
- Stored the complete theme configuration in PostgreSQL `admin_settings`; saving applies immediately and invalidates the page cache without restarting the service.
- Added strict six-digit hexadecimal validation and a one-click reset to the Neutral Blue default.
- Added a live preview and an Admin overview card showing the active theme.
- Preserved all routes, metrics, Agent protocol, Abuse logic, Consumption logic, Storage V2 and existing functional behavior.

## 50.4.4-prod-r1-manifest-consumption-ui-fix

- Fixed the root `SHA256SUMS` manifest shipped with 50.4.3, which still contained hashes from an earlier source state and caused installer/update verification to fail.
- Kept the 50.4.3 Consumption UI refresh: Public and Private IPs under each node with copy buttons, clearer Physical/VM Public/Private sections, and stronger RX/TX/TOTAL color separation.
- Kept the Consumption authentication fix using the canonical `TOKEN` for `/push/bandwidth-consumption`.
- Made `tools/build-dist.sh` regenerate and verify the canonical source manifest before packaging.
- Made release audit refresh the manifest before preflight, and made preflight verify manifest hashes and exact file coverage.
- Added a manifest contract test so missing, stale or extra manifest entries fail validation before release.

## 50.4.3-prod-r1-consumption-ui-refresh

- Kept the 50.4.2 Consumption authentication hotfix so `/push/bandwidth-consumption` continues using the canonical `TOKEN` and no longer throws `NameError: API_TOKEN`.
- Refreshed the main `Consumption` page layout to make each node clearer and easier to scan.
- Added Public IP and Private IP directly under each node name, each with its own copy button.
- Pulled the latest public/private node IPs directly from `node_bridge_addresses_latest` while preserving existing search, filters and hidden-node behavior.
- Restyled Physical Public, Physical Private, VM Public and VM Private metric groups with clearer color separation and more prominent RX/TX/TOTAL values.
- Preserved the existing route, payload, aggregation logic, retention and database schema.

## 50.4.2-prod-r1-consumption-auth-fix

- Fixed `/push/bandwidth-consumption` returning HTTP 500 because the route referenced the undefined legacy name `API_TOKEN`.
- Reused the canonical `TOKEN` value already used by `/push`, preserving the same `X-Token` authentication contract for both Agent endpoints.
- Added an always-on AST regression test that fails preflight if the Consumption route references `API_TOKEN`, omits `TOKEN`, or stops reading the `X-Token` header.
- Added live integration assertions for rejected and accepted Consumption tokens when a disposable PostgreSQL test database is available.
- Kept the Agent payload, endpoint, bucket format, Consumption calculations, database schema, UI, retention and all existing routes unchanged.

## 50.4.1-prod-r1-standalone-repo

- Made `tuanchu1121/virtinfra-monitor` the canonical and default repository everywhere.
- Removed every runtime, installer, updater, Agent bootstrap, publishing and documentation reference to the previous repository.
- Updated `install.sh`, `update.sh`, `install-agent.sh`, `uninstall-agent.sh`, `virtinfra-monitorctl`, PostgreSQL installer and GitHub publishing defaults.
- Added `CANONICAL_REPOSITORY` as an explicit repository contract.
- Added a release test that fails if the previous repository name appears anywhere in the source tree.
- Added a complete Vietnamese beginner guide for creating the new repository, publishing with GitHub Desktop, installing Monitor, installing Agent, updating, verifying and troubleshooting.
- Preserved all Storage V2, Dashboard, Abuse, Storage I/O, Consumption, API, route and Agent behavior from 50.4.0.

## 50.4.1-prod-r1-standalone-repo

- Preserved all existing Flask routes, HTML/CSS, chart rendering, API responses, Agent protocol, Authentication, Abuse behavior, Storage I/O and Consumption behavior.
- Added `vm_chart_5m`, an exact 5-minute Timescale hypertable for VM network, CPU, RAM and aggregate disk chart metrics with 7-day retention.
- Switched the pinned PostgreSQL 17 image from the Apache-only `-oss` tag to TimescaleDB Community Edition and added fail-closed capability checks for retention/compression policy APIs.
- Added `vm_raw_detail_5m`, a 48-hour Timescale hypertable for N-interface raw detail, while retaining the existing compressed storage snapshot path for N-disk history.
- Added `node_chart_5m` for exact 5-minute host/node charts with 7-day retention.
- Reused the existing bounded current/latest tables for Dashboard, Top VM, Node Health, current inventory and current Abuse instead of creating duplicate latest caches.
- Added transaction-scoped V2 writes, stable retry keys, batched `executemany()` operations and sanitized push timing/row-count logs.
- Switched existing VM/node chart helpers to the V2 readers by default without changing route, HTML, CSS, chart library, JSON key or timestamp behavior.
- Kept the previous chart readers available through `VIRTINFRA_READ_CHART_V2=0` for fast code rollback without database restore.
- Added idempotent Timescale schema/policy installation, storage health checks, `virtinfra-monitorctl storage-v2`, `virtinfra-monitorctl rollback-storage-v2`, validation and read-only benchmark tools.
- Added a full route/table/read-write audit, compatibility matrix, architecture guide and production deployment guide.
- Added N-NIC, public/private, null/missing field, stable retry key and V2 row-contract regression tests.

## 50.3.1-prod-r1-consumption-route-fix

- Renamed the visible navigation/page label from `Bandwidth Consumption` to `Consumption`.
- Fixed the `/bandwidth-consumption` Internal Server Error caused by an unescaped literal `%` in a CSS rule inside an old-style Python `%` formatted HTML block.
- Kept the existing route, endpoint, table, Agent payload and retention schema unchanged for safe in-place upgrades.
- Added a route-render regression contract so this formatting failure cannot silently return.

## 50.2.3-prod-r1-dashboard-snapshot-fix

- Fixed Dashboard period-slot selection so `5m` is the latest retained snapshot, `10m` is the previous 5-minute snapshot, `15m` is the third snapshot, and later buttons continue in the same sequence.
- Changed Dashboard `Selected Snapshot` to show the retained bucket actually used by the query instead of a theoretical wall-clock request point.
- Kept custom date/time selection absolute and continued selecting the nearest retained real push at or before the chosen time.
- Added regression checks for Dashboard slot semantics and Selected Snapshot rendering.

## 50.2.2-prod-r1-original-time-restore

- Removed the runtime UTC/HCM timezone switch and restored the original fixed `Asia/Ho_Chi_Minh` display.
- Restored original period-button semantics: `5m` is latest, `10m` is the previous 5-minute snapshot, `15m` is the third snapshot, and so on.
- Applied the same slot semantics to Dashboard, Top VM and Storage I/O.
- Kept existing `@epoch` snapshot links readable for backward compatibility without rewriting new local-time URLs.


## 50.2.2-prod-r1-original-time-restore

- Add the session CSRF token to the Display Timezone form.
- Fix the PostgreSQL Top VM historical-period query by replacing the non-PostgreSQL `HAVING total` alias with the full aggregate expression.
- Extend live PostgreSQL regression coverage to Top VM 10m/30m/1h and the timezone POST workflow.

## 50.2.0-prod-r1-virtinfra-hardening

- Renamed the public product to VirtInfra Monitor and the node collector to VirtInfra Agent.
- Added canonical VirtInfra Agent service, paths, doctor and compatibility migration from bwagent.
- Added UTC and Asia/Ho_Chi_Minh display-timezone selection without rewriting stored timestamps.
- Canonicalized custom snapshot URLs to absolute Unix timestamps across timezone switches.
- Fixed hidden Node/VM leakage through Dashboard and Storage search paths.
- Added PostgreSQL-backed cross-worker page-cache invalidation for Hide/Restore.
- Corrected database sizing UI: PostgreSQL data is separate from reusable WAL reserve; removed obsolete local-database size wording.
- Made Current Abuse fit normal desktop widths.
- Added /livez, /healthz, a local systemd watchdog, Nginx upstream hardening and Gunicorn /dev/shm heartbeats.
- Serialized same-node ingestion and performance-summary bootstrap with PostgreSQL advisory locks.
- Corrected age-based snapshot selection to use the full requested period.

## 50.0.4-prod-r1-one-command

- Fixed Abuse Policy save/create on PostgreSQL. `abuse_policy_versions` is keyed by `revision` and is no longer incorrectly treated as an `id`-serial table.
- Made legacy `BEGIN` and `BEGIN IMMEDIATE` compatibility statements transaction no-ops under psycopg, removing duplicate transaction warnings while preserving commit/rollback semantics.
- Added static and live PostgreSQL regression coverage for creating an Abuse policy version.

## 50.0.3-prod-r1-one-command

- Fix PostgreSQL `GroupingError` on the Node Health dashboard caused by grouping the computed physical-network role by the conflicting input column name.
- Group the normalized physical-network role by output position (`GROUP BY np.node, 2`), which is valid on PostgreSQL and remains compatible with the legacy query shape.
- Add a regression contract so the incompatible `GROUP BY np.node, role` form cannot return.
- Stage installs from the canonical `SHA256SUMS` manifest, so stale v48/v49 files left by Windows Explorer or GitHub Desktop are ignored.
- Verify every canonical source file before installing.
- Keep the release preflight strict while making the one-command bootstrap resilient to dirty merged repositories.
- Preserve support for non-executable `.sh` files published from Windows.

## 50.0.1-prod-r1-one-command

- Fixed one-command GitHub installation when a release is published from Windows GitHub Desktop and shell files do not retain the Linux executable bit.
- Replaced executable-mode completeness checks with explicit required-file validation.
- Normalized shell modes after GitHub tarball extraction while invoking all source scripts explicitly through `bash`.
- Hardened preflight, release audit, wrappers, management helpers and GitHub Actions against file-mode differences.
- Added a release test that simulates every `.sh` file being published as mode `0644`.

## 50.0.0-prod-r1-postgres-native

- Preserved the complete production UI, Agent protocol, Abuse Engine, storage/disk views, Admin workflow and scoped REST API.
- Replaced the runtime database with PostgreSQL 17 + TimescaleDB as the single source of truth.
- Added psycopg 3 connection pooling and an isolated compatibility/data-access layer so the mature application behavior remains intact without a second database.
- Kept exact Agent behavior: 15-second local sampling and one durable 300-second push.
- Kept exact retention: every real 5-minute push for 48 hours, one synchronized real snapshot/hour through 7 days, then bounded deletion.
- Added Timescale hypertables for supported history tables, integer-time partitioning, compact BRIN indexes and current-state sort indexes.
- Made Redis an optional page cache only, disabled by default and never authoritative.
- Added GitHub one-command fresh installation by public IP or domain with Nginx and Let's Encrypt.
- Added PostgreSQL backup/restore, doctor, audit, DB check, diagnostics, retention/backup timers and `bw-monitorctl`.
- Added full Agent/Monitor Ansible playbooks. Root SSH nodes no longer require sudo.
- Added static product contracts, live PostgreSQL application integration tests, CI and release archive tooling.
- Fresh-install release. Legacy database data is intentionally not imported.

## Lineage

v50 is built from the complete v48.12.9-r4 through v48.14/v49 UI and Agent feature lineage. The v50 runtime deliberately removes the transitional multi-store architecture and ships one PostgreSQL/TimescaleDB data plane.
