# R22.9 Consumption Sort Regression Hotfix

## Root cause
R22.8 replaced the canonical VM Consumption read path. A normal sort could run a full visible-VM count plus a second full rollup aggregation/sort, while repeated active-group EXISTS checks were added to source and inventory CTEs even when no Group was selected.

## Fix
- Restore the exact R22.7 cached VM hourly/daily query path.
- Do not redefine VM source, visible inventory, count, or row query functions.
- Keep the missing Node sort allow-list entries.
- Keep deterministic Node and Group sorting over the compact Node rollup dataset.
- Keep Consumption-local alignment for VMs, VMs count, Public Diff and Private Diff.

## Unchanged
No schema, migration, ingest, agent, formula, API, retention, Backup/Restore, Nuclear, Top VM, Storage I/O, Abuse, auth, or non-Consumption UI changes.
