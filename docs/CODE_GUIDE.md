# Code guide

## Runtime source

```text
app/app.py                         small WSGI entrypoint
app/runtime_loader.py              ordered runtime loader and source reader
app/runtime_layers/00_*.py..43_*.py UI, routes, Abuse Engine, storage, API and compatibility layers
app/bw_pg.py                       psycopg 3 pool plus isolated compatibility adapter
app/maintenance.py                queued maintenance/purge worker
app/retention.py                  bounded 2-day raw / 7-day hourly retention runner
```

The compatibility adapter lets the mature application logic move to PostgreSQL without running a second database or rewriting the UI in one risky cutover. It translates only the database API/SQL forms used by this application. Persistent rows are PostgreSQL-only.

## Agent

```text
deploy/agent/agent.py
```

Do not change the 15-second local sampler or 300-second durable push defaults without updating Abuse-cycle semantics, retention, tests and documentation together.

## Database deployment

```text
postgres/docker-compose.yml
postgres/sql/001_bootstrap.sql
postgres/sql/002_timescale.sql
postgres/sql/003_native_indexes.sql
```

## Tests

```text
tests/test_v50_contract.py
tests/test_v50_postgres_integration.py
```

Run `./preflight.sh` before every release. The live integration test requires a disposable PostgreSQL database because it drops the public schema.
