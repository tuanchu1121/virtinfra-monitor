# R22.12.2 Change Set

Release: `50.5.9-prod-r22.12.2-preflight-contract-hotfix`

## Scope

Server package preflight hotfix only. No Agent, runtime query, schema, UI or API behavior changes.

## Fixed

- The Node Groups legacy migration guard now excludes the additive
  `019_vm_consumption_shared_snapshot.sql` migration from the pre-R22
  byte-identical baseline.
- Migration 019 remains validated by snapshot-specific tests and the release
  `SHA256SUMS` manifest.

## Unchanged

- VM shared snapshot runtime and systemd worker
- Migration 019 contents
- Node and Group Consumption
- Agent v15 and ingest pipeline
- UI, API, sorting, rolling windows, RX/TX and coverage
