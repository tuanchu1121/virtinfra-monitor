# Changelog

## 50.5.9-prod-r9-safe-runtime-history-prune

This release removes source-history residue without changing the active monitoring system.

### Runtime cleanup

- Removed 75 superseded top-level function implementations that were neither live after application startup nor executed during bootstrap.
- Retained the route decorator for `/api/v1/performance`; only its superseded body was reduced because the final handler is rebound later.
- Removed historical release-banner comments, separator-only comments and repeated blank lines from ordered runtime layers.
- Preserved the exact semantic bytecode of every function that remains live after startup.

### Repository cleanup

- Removed generated Python caches and pytest cache data.
- Removed old call graphs, patch files, route snapshots, screenshot payloads and superseded release reports.
- Replaced large Node Groups audit payloads with compact route, SQL-hash and UI-pass contracts under `tests/contracts/`.
- Consolidated documentation around the current PostgreSQL 17 and TimescaleDB architecture.

### Compatibility

The release preserves:

- Flask routes, endpoint names and HTTP methods.
- Agent payloads and authentication.
- PostgreSQL schema and migrations.
- CPU, RAM, network, PPS, disk and bandwidth calculations.
- Abuse detection, queueing, retention and maintenance behavior.
- Static assets, page structure and current theme behavior.

No production deployment, service restart or database mutation is performed while building this package.
