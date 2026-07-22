# R22.12.1 Change Set

Release: `50.5.9-prod-r22.12.2-preflight-contract-hotfix`

## Scope

Production-safe server package hotfix for the R22.12 installer preflight only.

## Fixed

1. The legacy runtime-contract scanner no longer treats the internal
   `R2212_VM_SORTS` allow-list as a newly exposed public sort contract.
2. The additive `019_vm_consumption_shared_snapshot.sql` migration is excluded
   from the pre-R22 protected SQL digest set. The migration remains protected by
   snapshot-specific tests and the release `SHA256SUMS` manifest.
3. The installer manifest-path fixture now includes the R22.12 snapshot runtime,
   snapshot worker module and migration 019, so installer preflight can complete.

## Unchanged

- VM shared snapshot runtime and systemd worker
- PostgreSQL migration 019 contents
- Node and Group Consumption
- rolling windows and packed five-minute slots
- UI, routes, forms and response payloads
- Agent and ingest pipeline
- statement timeout
- Maintenance, Backup/Restore, RBAC, Abuse and Storage I/O
