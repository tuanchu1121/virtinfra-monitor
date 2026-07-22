# R22.11 Change Set

Release: `50.5.9-prod-r22.11-vm-slot-boundary-coverage-hotfix`

## Fixed

- Treats agent `data_time` as the end of the five-minute sampled interval.
- A push at `19:30` now maps to slot `19:25-19:30`.
- A push at `20:00` now maps to slot 11 of the `19:00` hourly row.
- Latest-sample timestamps now use the end of each slot.
- Existing R22.10 shifted arrays are ignored by exact reads and lazily replaced when an hourly row receives its first corrected v2 slot.
- No bulk rewrite or raw-history backfill is performed.

## Unchanged

- RX/TX delta formulas, agent payload, routes, UI, retention, sort, Backup/Restore/Nuclear and raw-free VM Consumption reads.
