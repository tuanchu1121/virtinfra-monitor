# Test results — r7

Environment: Windows sandbox, Python 3.12.2, no installed Flask/pytest/psycopg packages and no PostgreSQL test DSN.

## Passed

- AST parse: all 43 Python files under `app/` and `tests/`.
- r7 focused contract harness: 9/9 tests.
- Admin Node/VM SQLite SQL contracts: 13/13 query/sort/search cases.
- Storage active-group clause contracts: 2/2 cases.
- Direct source-contract scripts: 9 passed (`v50`, repository, hardening, Storage V2, docs, Consumption auth/UI, theme manager and custom theme).
- Manifest exact-coverage/hash contract: recorded after final manifest generation.

## Blocked or skipped

- `python -m pytest -q`: blocked because pytest is not installed in the sandbox (`No module named pytest`).
- `python -m compileall -q app tests`: source parses successfully, but compileall cannot write `.pyc` temporary files from a shell process in this managed workspace (`FileNotFoundError`).
- `test_bandwidth_consumption_agent.py`: Windows-only environment failure because the Linux Agent contract imports `os.uname`; unrelated to r7 source changes.
- Flask runtime/client tests: blocked because Flask/Werkzeug are not installed in this sandbox.
- PostgreSQL integration: skipped because `BW_TEST_DATABASE_URL` is not set; the existing module uses module-level `pytest.skip`.

The archive should not be promoted solely from this sandbox result. Run the complete preflight and pytest suite in the normal Linux build/staging environment before production rollout.

