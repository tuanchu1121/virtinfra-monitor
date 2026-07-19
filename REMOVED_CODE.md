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

## R8 safe dead-code prune

| Round | File | Audit line | Symbol | Type | Evidence | Risk |
|---:|---|---:|---|---|---|---|
| 1 | `app/runtime_layers/12_abuse_policy.py` | 558 | `abuse_settings_admin_card` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/12_abuse_policy.py` | 76 | `get_agent_runtime_config` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/13_admin_abuse_queue.py` | 71 | `_insert_abuse_event` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/12_abuse_policy.py` | 158 | `refresh_fast_current_state` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/14_abuse_metrics_ui.py` | 1037 | `vm_period_links` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/14_abuse_metrics_ui.py` | 113 | `get_agent_runtime_config` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/14_abuse_metrics_ui.py` | 222 | `refresh_fast_current_state` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/14_abuse_metrics_ui.py` | 329 | `abuse_settings_admin_card` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/18_operations_reset.py` | 133 | `top_vm_table` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/19_guest_ram.py` | 428 | `interface_table` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/19_guest_ram.py` | 42 | `refresh_fast_current_state` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/19_guest_ram.py` | 325 | `top_vm_table` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/09_admin_routes.py` | 948 | `purge_vm_data` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/30_inventory_storage_precision.py` | 707 | `_v48133_storage_disk_table` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/30_inventory_storage_precision.py` | 838 | `_v48133_storage_node_table` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/26_abuse_intelligence.py` | 486 | `refresh_fast_current_state` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/36_batched_ingest.py` | 52 | `process_node_vm_presence` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/32_performance_runtime.py` | 348 | `ingest_disk_io_current` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/27_abuse_dashboard.py` | 1298 | `_v48129_vm_detail_cpu_stat` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/04_charts_vm.py` | 502 | `vm_chart_svg` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/41_ui_layout_r2.py` | 494 | `_v5049_theme_selector_html` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 1 | `app/runtime_layers/41_ui_layout_r2.py` | 515 | `_v5049_runtime_theme_script` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 2 | `app/runtime_layers/12_abuse_policy.py` | 88 | `_abuse_state_map` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 2 | `app/runtime_layers/12_abuse_policy.py` | 107 | `_insert_abuse_event` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 2 | `app/runtime_layers/14_abuse_metrics_ui.py` | 140 | `_insert_abuse_event` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
| 2 | `app/runtime_layers/26_abuse_intelligence.py` | 468 | `_v48126_ram_hit` | Superseded function implementation | Unreachable after load; not called during import; no decorator/default side effect; no intervening load | Low |
