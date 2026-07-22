# R22.4 Preflight Contract Hotfix

## Fixed

- Replaced the stale aggregate PostgreSQL SQL-tree assertion inherited from v50.5.9-r1.
- Preflight now validates each protected SQL migration against the approved per-file SHA256 contract.
- The approved R22.1 `002_timescale.sql` view-safety fix remains pinned and protected.

## Runtime impact

None. This release changes validation logic and release identity only. Application routes, UI, API, database schema, agent payload, metric formulas, retention behavior and maintenance operations are unchanged from R22.3.
