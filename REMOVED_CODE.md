# Removed code inventory

| File | Baseline line | Symbol | Type | Evidence | Validation | Risk |
|---|---:|---|---|---|---|---|
| `app/app.py` | 16 | `sys` | Unused import | No AST load, exact repository reference, alias, decorator, callback, or dynamic lookup | Function AST, route, HTML/API contract, compile, full regression suite | Low |
| `app/bw_pg.py` | 16 | `contextmanager` | Unused import | No AST load or repository reference; standard-library import has no registration effect | SQL compatibility tests, compile, full regression suite | Low |
| `app/bw_pg.py` | 65 | `_RE_QMARK` | Unused private constant | No direct or indirect repository reference; no string-based lookup found | SQL translation tests, compile, full regression suite | Low |
| `tests/test_v50_contract.py` | 3 | `re` | Unused import | No AST load in the test module | Full regression suite | Low |
| `tests/test_v50_postgres_integration.py` | 9 | `json` | Unused import | No AST load in the integration module | Module collection and regression suite | Low |
| `tools/storage-v2-status.py` | 7 | `sys` | Unused import | No AST load or dynamic lookup | Compile and shell/tool contract tests | Low |
| `tools/validate-storage-v2.py` | 9 | `defaultdict` | Unused import | No AST load or dynamic lookup | Compile and storage contract tests | Low |
| `tools/validate-storage-v2.py` | 10 | `timezone` | Unused imported name | `datetime` is loaded; `timezone` is never loaded | Compile and storage contract tests | Low |

No function, route, class, SQL statement, migration, feature branch, callback, wrapper, or runtime file was deleted.
