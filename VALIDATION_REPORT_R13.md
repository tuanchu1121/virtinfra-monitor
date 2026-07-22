# VirtInfra Monitor R13 Validation Report

## Change boundary

This release intentionally changes only two browser refresh constants from 5,000 ms to 30,000 ms and repairs stale validation references. No monitoring formula, API contract, route, SQL migration, Agent payload, database schema or static UI asset is modified for this refresh change.

The retained Admin/Maintenance correctness hotfix remains limited to permission boundaries, own-password updates, FIFO Queue visibility, Maintenance/Nuclear behavior, effective Node Group visibility, purge visibility, move-all-to-Ungrouped and exact Node-only flag injection.

## Runtime equivalence

- Flask routes: 83 before and 83 after, with identical paths, endpoint names and HTTP methods.
- Agent source tree: unchanged.
- PostgreSQL SQL/migration tree: unchanged.
- Static UI assets: unchanged.
- Core application differences after normalizing the release string: only the two requested refresh values and their explanatory comment.

## User-flow checks

The isolated runtime validation passed the following user-facing flows:

- Admin and Super Admin permission boundaries
- Viewer read-only access
- Current-user password change without modifying Super Admin
- Maintenance Queue, 2-day/7-day actions and dispatcher diagnostics
- Nuclear two-step Super Admin confirmation
- Node Group hide/restore effective visibility
- Move all Nodes to Ungrouped
- Node/VM purge immediate visibility and rollback on enqueue failure
- Node-only flag injection without VM UUID or metric-header flags
- Existing filters, forms, navigation and route count

## Retention behavior

The effective runtime retention function was executed against isolated data containing multiple five-minute samples at day 1, day 3, day 6 and day 8:

- Day 1 retained every five-minute sample with the `raw` tier.
- Day 3 retained exactly one real sample for the tested local hour with the `hourly` tier.
- Day 6 retained exactly one real sample for the tested local hour with the `hourly` tier.
- Day 8 was removed from both the snapshot index and metric table.

The effective core history policy returned by runtime is:

- Raw window: 2 days
- Hourly window: 7 days
- Raw resolution: 300 seconds
- Hourly resolution: 3,600 seconds
- History maximum: 7 days

Retention selects one coherent real Agent snapshot per Node/local hour for core metric-history tables between day 2 and day 7. It does not calculate a synthetic hourly average.

Dedicated existing policies remain unchanged:

- Storage V2 VM/Node chart tables retain exact five-minute rows for 7 days.
- Storage V2 per-interface raw detail retains 48 hours.
- Consumption compatibility history uses 2-hour buckets for 7 days.
- Abuse/log/history cleanup remains bounded to 7 days according to the existing wrappers.
- Current Node/VM inventory, users, settings and API keys are preserved.

## UI validation

Deterministic HTML comparison passed on 12 pages. Inline styles, cards, headers, buttons, filters, navigation and table wrappers were preserved.

Chromium checks passed on the same 12 pages at:

- Desktop: 1440×1000
- Tablet: 1024×900
- Mobile: 390×844

The checks covered document overflow, card containment, table wrapper behavior, button geometry and navigation containment.

## Automated checks

- Full pytest: 132 passed, 1 skipped
- Route/runtime validation: PASS
- Python compilation: PASS
- Shell syntax: PASS
- YAML parsing: PASS
- Documentation accuracy: PASS
- Installer fresh/update flow: PASS
- Manifest path traversal protection: PASS
- Windows/GitHub Desktop packaging mode: PASS
- SHA-256 source manifest exact coverage: PASS
- ZIP integrity and extracted manifest verification: required before release handoff

The skipped test is the disposable live PostgreSQL integration because `BW_TEST_DATABASE_URL` was not provided. Static PostgreSQL contracts, SQL migrations, compatibility logic and isolated runtime tests still passed.
