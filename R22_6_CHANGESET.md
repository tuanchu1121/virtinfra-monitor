# VirtInfra Monitor R22.6 Change Set

Version: `50.5.9-prod-r22.6-consumption-vm-timeout-hotfix`

## Fixed

- `/bandwidth-consumption` now lands on Node Consumption by default. The compact Node 5-minute/hourly/daily rollup pipeline is used unless `tab=vm` is explicitly selected.
- VM Consumption raw edge queries now constrain both `node_stats.bucket` and `node_stats.last_push`. `bucket` is the Timescale hypertable partition column, so this enables chunk exclusion and prevents scans across the full retained VM/NIC history.

## Preserved

- VM and Node RX/TX formulas.
- VM hourly/daily pipeline.
- Node/Group/Summary rollup architecture.
- Routes, request parameters, response layout, agent payload and database schema.
- Configuration Backup/Restore and hardened Nuclear Reset from R22.5.

## Production symptom addressed

`psycopg.errors.QueryCanceled: canceling statement due to statement timeout` while opening `/bandwidth-consumption` or VM Consumption.
