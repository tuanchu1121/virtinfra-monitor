# Node Groups schema import hotfix

## Root cause

`deploy/postgres/install-postgres-native.sh` loads `/opt/bw-monitor/app.py` with
`importlib.util.module_from_spec()` followed by `spec.loader.exec_module(module)`.
That loading pattern does not automatically insert the temporary module name
`bw_monitor_schema` into `sys.modules`.

The original additive Node Groups connector ended with:

```python
_node_groups_hotfix.install(_node_groups_sys.modules[__name__])
```

This raised `KeyError: 'bw_monitor_schema'` during initial schema creation.

## Fix

The connector now uses the normal module object when present. For direct
`exec_module()` loading without `sys.modules` registration, it uses a small
live proxy that forwards attribute reads and writes to the executing app.py
globals dictionary.

Normal Gunicorn/Flask imports preserve their original module identity and
runtime behavior. The proxy is only selected for the installer/maintenance
import pattern that previously failed.

## Database impact

None. No existing SQL, migration, metric schema, retention data or PostgreSQL
volume is removed or rewritten by this hotfix.
