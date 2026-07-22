# Validation Report R22.6

- 69 focused regression and contract tests: PASS
- Consumption R20/R21/R22 architecture tests: PASS
- Route/source cleanliness contracts: PASS
- Node Groups, Configuration Backup and Nuclear contracts: PASS
- Installer flow: PASS
- Installer manifest path safety: PASS
- Python application compile: PASS
- Source SHA256 manifest: PASS

The monolithic legacy pytest run reached 70% without assertion failures, then was stopped because a pre-existing background process kept the test process alive. Validation therefore relies on isolated focused groups rather than claiming a false full-suite completion.

Live PostgreSQL `EXPLAIN ANALYZE` was not run in the build container because no production-scale TimescaleDB clone was available. The query correction directly constrains the hypertable partition key used by Timescale chunk exclusion.
