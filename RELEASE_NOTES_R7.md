# Release notes R7

Release: `50.5.9-prod-r7-modular-runtime-refactor`

This release separates the historical 36,449-line runtime from `app/app.py` into 44 ordered modules. It does not intentionally change monitoring calculations, endpoints, payloads, database schema, retention or maintenance behavior.

Validation completed for Python syntax, shell syntax, full pytest, route-map equivalence and installer staging. Live PostgreSQL integration still requires a disposable database through `BW_TEST_DATABASE_URL`.
