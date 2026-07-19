# Diff Summary: Node Groups additive hotfix

## Baseline preservation

- `app/app.py` baseline prefix: byte-identical.
- `app/app.py` modification: one 10-line loader block appended at EOF.
- Original function order and wrapper chains: unchanged.
- Existing SQL migrations `001`–`010`: unchanged.
- Existing routes: unchanged; four new POST routes added.

## Runtime additions

- `app/node_groups.py`: additive schema/runtime/UI/permission module.
- `postgres/sql/011_node_groups.sql`: additive database migration.
- `app/static/vendor/flag-icons/`: local flag CSS, MIT license, source note and 257 SVG files.

## Narrow existing-file edits

- `app/bw_pg.py`: add `node_groups` to the small `lastrowid` table allow-list.
- Install/update/preflight scripts: install and validate the new module, assets and migration.
- Existing release-identity tests/docs: update release string only, except contract tests expanded for Node Groups.

## Explicitly untouched

- Agent source and payload.
- CPU/RAM/disk/network/PPS/bandwidth calculations.
- Retention, maintenance queue and reset behavior.
- Existing endpoint paths/methods/payloads.
- Existing CSS blocks, theme colors, card/table layout and responsive rules.
- PostgreSQL metric schema and migrations `001`–`010`.

## Route delta

- Before: 75
- After: 79
- Added: `/admin/node-groups/create`, `/admin/node-groups/update`, `/admin/node-groups/action`, `/admin/node-groups/assign`.

## Rollback packaging

The r4 source backup and rollback script are shipped in a separate rollback ZIP. No old-release archive or rollback directory is embedded in the production source tree.
