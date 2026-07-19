# Node Groups PostgreSQL Migration Report

Migration file: `postgres/sql/011_node_groups.sql`

## Added objects

- `node_groups`
- `node_group_memberships`
- `node_group_membership_history`
- Supporting unique and lookup indexes

## Safety properties

- No existing metric/history table is altered.
- Existing migrations `001` through `010` are byte-identical to baseline.
- Membership references `node_inventory(node)` with `ON DELETE CASCADE`.
- Membership references `node_groups(id)` with `ON DELETE RESTRICT`.
- `Ungrouped` is created as the single system group.
- Existing nodes are backfilled into `Ungrouped` idempotently.
- Legacy role migration runs once using `node_groups_role_migration_v1`.

## Validation

- PostgreSQL 17 disposable database: PASS.
- Migration applied repeatedly: PASS.
- Existing `admin` migrated to `super_admin`: PASS.
- A later-created `admin` remains `admin`: PASS.
- Node deletion removes membership: PASS.
- Group deletion while referenced is rejected: PASS.

TimescaleDB-specific full application integration was not run because the build container does not provide the TimescaleDB extension. The migration itself does not depend on TimescaleDB objects.
