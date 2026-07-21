# R22.8 Change Set

Version: `50.5.9-prod-r22.8-vm-consumption-exact-window-sort-alignment`

## Base release

R22.8 is developed directly on top of R22.7. It does not replace the source with the older 50.5.9-r3 tree. All R22.7 maintenance, backup, RBAC, Node Group, retention, ingest and hardening behavior remains present.

## VM Consumption changes

- Restores the accurate hybrid range planner proven in 50.5.9 for the VM tab only.
- Complete local days read `vm_consumption_daily`.
- Complete local hours read `vm_consumption_hourly`.
- Only the two incomplete hour edges read `node_stats`.
- Raw edge SQL filters both `bucket` and `last_push`, preserving exact range semantics while enabling Timescale chunk pruning.
- Node and Node Group scope is applied together inside raw/hourly/daily source branches before aggregation; selecting a Node cannot bypass the selected Group.
- All-VM merges historical active-Node segments by `vm_uuid`; a Group view merges segments that remain inside its selected current scope.
- An explicit Node filter remains Node-attributed and includes only traffic recorded on that Node.
- Overall coverage uses the least-complete configured bridge. A complete private bridge can no longer hide missing public samples, or vice versa.
- Historical bridge data remains visible if a NIC was removed after the selected period.

## Sorting and UI

- VM UUID, Node, Public RX, Public TX, Public Total, Private RX, Private TX, Private Total, Coverage and Latest Sample all sort the complete filtered VM set.
- Aggregation, visibility, Group, Node, search and coverage filters run before `ORDER BY`.
- `LIMIT/OFFSET` remains the final operation, so sorting is system-wide rather than page-local.
- The R22.7 query-time normalization is preserved, allowing the bounded 5–15 second VM cache to reuse equivalent requests instead of missing on every second.
- The VM Node dropdown is restricted to active Nodes in the selected Group.
- Retains the 50.5.9 fixed-column Consumption layout and adds a final VM-only alignment contract for numeric columns, headers, coverage and latest sample.
- The VM information note now describes the exact daily/hourly/two-edge planner instead of the R22.7 rollup-only/current-hour behavior.

## Explicitly unchanged

- Agent source and payload.
- Five-minute Agent cadence.
- `/push` ingest and transactions.
- `vm_consumption_hourly` and `vm_consumption_daily` write behavior.
- Node, Node Group and Summary Consumption pipelines.
- RX/TX direction formulas.
- Database schema and migrations.
- Retention, Maintenance, Queue, Dashboard, Top VM, Abuse and Storage I/O.
