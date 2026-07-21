# R22.3 Maintenance Queue + Backup Manifest Hotfix

Release: `50.5.9-prod-r22.4-preflight-contract-hotfix`

## Fixed

1. The **Run Consumption retention cleanup** control now submits a PostgreSQL FIFO maintenance job instead of deleting rows inside the web request.
2. The queued job uses the existing `retention` action with `scope=consumption`; no new queue schema or systemd template is introduced.
3. Scheduled/global retention now also covers `node_consumption_5m`, `node_consumption_hourly`, and `node_consumption_daily`.
4. Nuclear-reset backup verification accepts existing GNU `sha256sum` entries such as `./database.dump` and normalizes them to `database.dump`.
5. Path traversal, absolute paths, missing files, checksum mismatches, and conflicting normalized entries remain rejected.
6. New backups write bare manifest names to avoid recreating the compatibility condition.

## Unchanged

- UI layout and API contracts
- Agent payload and cadence
- Consumption formulas
- Maintenance queue schema and FIFO dispatcher
- Retention duration: Node raw 48 hours, hourly/daily rollups 7 days
- Nuclear reset requirement for a verified PostgreSQL custom-format backup
