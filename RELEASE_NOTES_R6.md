# VirtInfra Monitor 50.5.9 prod-r6 Release Notes

Release: `50.5.9-prod-r6-node-groups-admin-bulk-management-retention-safe-maintenance-hotfix`

Source baseline: `50.5.9-prod-r5-node-groups-hotfix-additive-schema-import-fix-production-slim`

## Scope

This release completes Node Groups management and monitoring while tightening retention, Maintenance, role and installation safety. It does not change Agent cadence, metric formulas, abuse thresholds, queue behavior, Consumption formulas or existing API payloads.

## Main changes

- Restores the stable login document and removes the legacy fixed credential hint from production source.
- Adds the monitoring navigation order: Dashboard, Node Groups, Top VM, Node Health, Storage I/O, Consumption and VM Abuse.
- Adds a collapsed-by-default Node Groups monitoring page with batch summaries and lazy node detail.
- Adds Node Group search, status/abuse/online filters and raw-value sorting.
- Adds Admin/Super Admin bulk add, move, remove and move-all-to-Ungrouped operations.
- Keeps every node in one current membership; remove means move to Ungrouped.
- Preserves Node Group configuration during ordinary retention, compact, VACUUM and accounting cleanup.
- Restricts Maintenance and Nuclear Reset to Super Admin at the backend.
- Moves 2-hour accounting and RETENTION7 controls into Maintenance.
- Removes the r5 `/push` view replacement. New node membership is created by an additive idempotent database trigger instead.
- Includes local `/static/flags` assets with a neutral fallback and no runtime network dependency.

## Database

Migration `postgres/sql/012_node_groups_r6_safety.sql` is additive and idempotent. It adds indexes and the node-inventory insert trigger that assigns only nodes without a membership to Ungrouped. No metric table is altered.

## Compatibility

- Existing groups and memberships are retained.
- Migration 012 does not repeat or modify the legacy role migration from migration 011.
- The local compatibility path uses an equivalent idempotent trigger in `app/node_groups.py`.
- PostgreSQL live integration skips cleanly unless `BW_TEST_DATABASE_URL` points to a disposable test database.

## Validation

- Python compile: PASS.
- Bash syntax: PASS for 45 shell scripts.
- Full pytest: 117 passed, 1 skipped, exit code 0 in 66.04 seconds.
- Skipped test: PostgreSQL integration because `BW_TEST_DATABASE_URL` was not set.
- No runtime source change was required for the earlier apparent pytest hang. Detached process supervision confirmed that pytest exits normally; the foreground command runner was the timeout source.

## Deployment safety

The package does not deploy, restart services or run a production migration automatically. Those actions occur only when an operator explicitly runs the installer or update command.

## Installer manifest fixture correction

- Updates `tools/test-installer-manifest-paths.sh` so its synthetic repository includes the four required r6 files:
  - `app/static/flags/node-groups.css`
  - `app/static/flags/neutral.svg`
  - `app/static/flags/vn.svg`
  - `postgres/sql/012_node_groups_r6_safety.sql`
- Fixes the false `Downloaded repository is incomplete` result during preflight and update validation.
- Does not modify application runtime, Node Groups behavior, database behavior, Agent behavior, UI or service configuration.
