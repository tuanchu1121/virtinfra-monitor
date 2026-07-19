# Validation Report: Node Groups hotfix

## Release

- Release: `50.5.9-prod-r5-node-groups-hotfix-additive`
- Baseline: `50.5.9-prod-r4-dead-code-cleanup`
- Baseline manifest: **173/173 files verified before modification**
- Baseline `app/app.py` SHA256: `5ae42e595990d0cc8b885d7be2e9ebf1e02ccdf2a33841c56b910994e44715d7`
- Baseline `app/app.py` lines: `36432`
- Final `app/app.py` lines: `36442`
- Baseline prefix preserved byte-for-byte: **TRUE**
- Bytes appended to `app/app.py`: **558**
- Production deployment/restart: **NOT PERFORMED**
- Rollback source: **separate rollback package**, not embedded in production manifest

## Runtime implementation strategy

The existing append-only runtime remains intact. The hotfix appends one loader at the end of `app/app.py`, after all previous runtime replacements have registered, and installs `app/node_groups.py`. The module captures the final baseline functions/view objects before replacing only the endpoints and helpers that require Node Group filtering or the role split.

- Baseline routes: **75**
- Final routes: **79**
- New routes: **4 POST-only Node Group management routes**
- Existing endpoint names, methods and route rules: **unchanged**
- Existing migrations `001` through `010`: **byte-identical**
- Metric tables/formulas, Agent payload/cadence, retention, queue and Abuse Engine: **unchanged**

## Behavior equivalence

- Omitted `group` and `group=all` delegate to the captured baseline implementation.
- Deterministic HTML equality for Group=All/no-group: **PASS**.
- Old cards, table headers, buttons, filters, navigation entries and inline style blocks: **preserved**.
- Existing monitoring calculations are not reimplemented for the default path.

## Node Groups behavior

- Immutable system group `Ungrouped`: **PASS**.
- Existing and newly observed nodes receive membership: **PASS**.
- One node belongs to one group through a primary-key membership: **PASS**.
- VM group is inherited from current node only: **PASS**.
- Group with members cannot be deleted: **PASS**.
- Node deletion cascades membership only; group deletion cannot delete nodes: **PASS**.
- Audit events and actor/node/old/new group/timestamp fields: **PASS**.

## Role migration and permissions

- One-time `admin` → `super_admin` migration marker: `node_groups_role_migration_v1`.
- Migration idempotency: **PASS**.
- Existing administrator remains fully privileged: **PASS**.
- New `admin` can manage Viewer/Admin, Nodes, VMs and Node Groups: **PASS**.
- New `admin` is denied Maintenance, API Keys, Theme, Retention, reset and dangerous settings: **PASS**.
- Viewer remains read-only and may use Node Group filters: **PASS**.

## Flag assets

- Local 4x3 SVG files: **257**.
- CSS mappings: **0**.
- Zero-byte/invalid packaged SVGs: **0**.
- Runtime CDN/network/npm dependency: **none**.
- MIT license and source provenance retained.

## UI validation

- Structural deterministic HTML comparison: **9/9 baseline pages PASS**.
- Chromium geometry/overflow check: **10/10 pages PASS** at desktop, tablet and mobile widths.
- New page included: Admin → Node Groups.
- No new document horizontal overflow detected.

## PostgreSQL validation

- `postgres/sql/011_node_groups.sql` applied twice against disposable PostgreSQL 17: **PASS**.
- Role migration, restricted future admin role, membership cascade and group delete restriction: **PASS**.
- Existing full TimescaleDB application integration was not executed in this build container because the TimescaleDB extension package is unavailable. This is recorded as an environment limitation, not reported as a pass.

## Final command results

- Full source preflight with live integration intentionally skipped: **PASS, exit 0**.
- Full pytest without live DSN: **104 passed, 2 skipped in 45.93s, exit 0**.
- Node Groups PostgreSQL integration with disposable PostgreSQL 17 DSN: **1 passed, exit 0**.
- Canonical production-slim manifest: **460/460 files PASS**.

## Production-slim packaging

Raw before/after HTML snapshots are retained in the full source archive but intentionally omitted from this production-slim tree. Summary JSON/Markdown evidence, route maps, tests and all runtime assets remain included.

## Acceptance decision

**ACCEPTED FOR SOURCE PACKAGING.** All changes allowed by the request are additive and the baseline path is demonstrably preserved. No production deployment or service restart was performed.
