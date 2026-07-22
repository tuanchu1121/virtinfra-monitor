# VirtInfra Monitor R19 Validation Report

Release: `50.5.9-prod-r19-production-readiness-audit-hotfix`

## Audit scope

The R18 GitHub-root-ready tree was reviewed across runtime loading, route/RBAC/session behavior, Theme UI, Maintenance/Queue, Consumption retention, PostgreSQL update flow, installer/updater integrity, Agent authentication and release packaging.

## Confirmed R18 defects corrected

1. Custom and preset themes could be selected but later overwritten by the core theme controller after PJAX navigation or automatic refresh. The selector listener also referenced the original DOM element after content replacement.
2. `Clear All Monitoring Data` omitted `node_consumption_hourly` and `node_consumption_daily`, leaving current physical Node Consumption history behind.
3. Maintenance displayed legacy `node_bandwidth_consumption_2h` as the primary Consumption store, producing misleading `MISSING` values after the legacy table was empty.
4. Update migration/backfill ran while the old web and cleanup processes were active. The backfill imported the complete Flask runtime, reproducing schema DDL and causing PostgreSQL deadlocks under load.
5. A missing `BW_MONITOR_TOKEN` silently fell back to the weak value `123456` in source-level/manual deployments.

## Implemented corrections

- One delegated Theme controller now survives PJAX replacement and preserves Custom selection when the core refresh code calls `applyTheme()`.
- Monitoring reset and Nuclear Reset allow-lists now include hourly and daily Node Consumption rollups.
- Consumption Maintenance stats/actions cover hourly, daily and legacy compatibility storage, with accurate labels and confirmation text.
- The updater refuses to start while a maintenance worker is running, temporarily stops web/timers/cleanup services before source/schema replacement, and restarts them best-effort if update fails.
- `consumption_rollup.py` now uses a dedicated PostgreSQL connection and advisory transaction lock without importing `app.py`.
- Agent authentication fails closed when no monitor token is configured.

## Validation

- Python syntax and runtime manifest hashes: PASS
- Shell syntax: PASS
- Flask route count: 83, unchanged
- Node Groups runtime matrix: PASS
- RBAC/session runtime matrix: 30/30 PASS
- Targeted R19 regression tests: PASS
- Existing source regression suite: PASS
- Installer/update simulation: PASS
- Manifest exact coverage and archive extraction comparison: PASS

Live PostgreSQL integration is intentionally skipped unless `BW_TEST_DATABASE_URL` points to a disposable database.

## Remaining non-blocking production work

- Login-specific rate limiting/Fail2ban remains external to the application.
- The historical modular runtime still contains compatibility DDL in `db()` during each worker's first initialization. R19 serializes update work and removes the backfill import path, but a future controlled refactor should move all remaining DDL into migrations.
- The append-only runtime layer chain remains technical debt. It should not be flattened without comprehensive behavioral equivalence testing.
