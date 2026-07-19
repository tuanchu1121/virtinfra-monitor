# R9 safe runtime-history cleanup

Release: `50.5.9-prod-r9-safe-runtime-history-prune`

## Scope

This cleanup removes source and repository history that is not part of the active application. It does not alter monitoring formulas, API payloads, database schema, migrations, retention, queueing, authentication, Agent behavior or rendered static assets.

## Runtime result

- Runtime layers before cleanup: 35,241 physical lines.
- Runtime layers after cleanup: 31,305 physical lines.
- Net runtime reduction: 3,936 lines, approximately 11.2%.
- Removed 75 superseded top-level implementations.
- Reduced one superseded decorated route body to a registration-only stub; its final handler remains unchanged.
- Removed historical release-banner comments, separator-only comments and repeated blank runs.

A function was removed only when all of the following were true:

1. A later binding replaced it.
2. Its function object was not live after full application startup.
3. It was not executed during bootstrap.
4. Any earlier function referencing the same global name resolves the later binding at request time.
5. No required module-level registration depended on its implementation body.

## Repository and documentation result

- Removed generated Python bytecode and pytest cache directories.
- Removed obsolete call graphs, patch payloads, screenshot payloads and superseded release reports.
- Replaced large Node Groups audit payloads with compact contracts in `tests/contracts/`.
- Removed stale release identifiers from current operational documentation.
- Consolidated the changelog to the current maintained release contract.
- Retained installation, upgrade, rollback, database, Agent, API, Storage, Consumption, security and operations documentation.

## Deliberately retained historical bindings

A final audit still identifies 117 earlier definitions. They were not deleted because they remain live function objects, execute during bootstrap, provide Flask registration side effects, or are reachable through wrappers, aliases and compatibility bindings. Removing them would no longer satisfy exact runtime equivalence.

## Explicitly preserved

- 83 Flask routes and their endpoint/method contract.
- Every final module-global callable.
- Flask view functions, hooks and error handlers.
- Agent source and PostgreSQL SQL tree.
- Static assets and local flag assets.
- CPU, RAM, network, PPS, disk and bandwidth calculations.
- Abuse policy evaluation, current-state cycles and incident history.
- Safe FIFO queue, retention and maintenance behavior.
- Node Groups integration and role boundaries as implemented by the input release.

## Not changed

This release is cleanup, not a business-logic repair. Existing functional defects or permission-policy decisions are not silently changed in the cleanup package.
