## 50.3.2-prod-r1-github-desktop-operations-guide

- Kept the complete `50.3.1` Consumption route fix and runtime behavior unchanged.
- Added `START_HERE_VI.md` as the production operator entry point.
- Added a detailed GitHub Desktop publish guide covering root-tree replacement, commit, push, raw-version verification, conflicts and source rollback.
- Added a complete Vietnamese command handbook for Monitor install/update, Agent manual/Ansible deployment, maintenance, Consumption checks, PostgreSQL, backup/restore, domain/TLS, diagnostics and troubleshooting.
- Documented safe token handling, bridge-role verification, Agent state behavior and production rollback boundaries.

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
- Fix the PostgreSQL Top VM historical-period query by replacing the SQLite-only `HAVING total` alias with the full aggregate expression.
- Extend live PostgreSQL regression coverage to Top VM 10m/30m/1h and the timezone POST workflow.

## 50.2.0-prod-r1-virtinfra-hardening

- Renamed the public product to VirtInfra Monitor and the node collector to VirtInfra Agent.
- Added canonical VirtInfra Agent service, paths, doctor and compatibility migration from bwagent.
- Added UTC and Asia/Ho_Chi_Minh display-timezone selection without rewriting stored timestamps.
- Canonicalized custom snapshot URLs to absolute Unix timestamps across timezone switches.
- Fixed hidden Node/VM leakage through Dashboard and Storage search paths.
- Added PostgreSQL-backed cross-worker page-cache invalidation for Hide/Restore.
- Corrected database sizing UI: PostgreSQL data is separate from reusable WAL reserve; removed SQLite SHM wording.
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
