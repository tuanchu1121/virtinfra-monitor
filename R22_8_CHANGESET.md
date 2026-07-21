# R22.8 Change Set

Release: `50.5.9-prod-r22.8-consumption-sort-alignment-hotfix`

## Scope

Focused Consumption-only hotfix. No database schema, migration, Agent payload,
ingest formula, API endpoint, retention, Backup/Restore, Nuclear Reset, Top VM,
Storage I/O, Abuse, authentication, or non-Consumption UI behavior is changed.

## Fixes

1. Node sort validation now accepts every column rendered by the R22 Node table:
   VMs, All VM Public/Private RX/TX/Total, Public Diff, and Private Diff.
2. Text columns start with ascending order on the first click; numeric columns
   start descending. Repeated clicks toggle deterministically.
3. Node sorting uses stable Node-name tie ordering.
4. Node Group Consumption now supports deterministic sort links for counts,
   physical/VM traffic, differences, coverage, and latest sample.
5. The common VM sort path no longer uses `COUNT(*) OVER()`. The visible VM
   count is cached separately, allowing PostgreSQL to use a bounded top-N sort.
6. Selected Node Group scope is applied before VM per-bridge/per-VM and NIC
   configuration aggregation.
7. VM table receives a fixed colgroup. Node and Group VMs count columns are
   centered, while Public Diff and Private Diff remain right-aligned with
   tabular numerals.

## Compatibility

- Route count remains 83.
- Existing sort query parameter names remain unchanged.
- Existing URLs and endpoint names remain unchanged.
- Existing RX/TX guest-perspective normalization is unchanged.
- Existing hourly/daily VM rollup-only architecture is unchanged.
