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

# Changelog

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
