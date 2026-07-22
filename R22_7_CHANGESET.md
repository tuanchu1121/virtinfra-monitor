# R22.7 Change Set

Version: `50.5.9-prod-r22.12.2-preflight-contract-hotfix`

## Scope

- VM Consumption render path reads only `vm_consumption_hourly` and `vm_consumption_daily`.
- Removes raw `node_stats` edge scans from VM list/totals SQL.
- Uses a fixed number of hourly buckets ending with the live current-hour bucket.
- Full local days use daily rows; partial local days use hourly rows.
- Keeps Node and Group Consumption on the existing node 5m/hourly/daily pipeline.
- No database migration, new table, Agent change, ingest change, retention change, RX/TX formula change, API change, or timeout increase.

## Expected behavior

- VM totals are hour-resolution. The current hour is partial until more 5-minute pushes arrive.
- The oldest boundary is aligned to an hour, so a rolling range is not minute-exact.
- Global filtering, sorting, count and pagination still operate across every visible VM before `LIMIT`.
