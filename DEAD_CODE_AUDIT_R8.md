# R8 conservative dead-code audit

Release: `50.5.9-prod-r8-safe-dead-code-prune`

## Result

The audit runs to a fixed point. A function implementation is removed only when all conditions below are true:

1. A later top-level binding replaces the implementation.
2. The old function object is unreachable after the complete runtime loads.
3. The old implementation is not called during import/bootstrap.
4. The definition has no decorator and no evaluated default/annotation with a call-side effect.
5. The symbol is not loaded between this definition and its replacement.
6. The final Flask route map, endpoint bindings, hooks, static assets and final callable source fingerprints remain unchanged.

Removed: **26 old implementations / 1,208 physical lines** across two audit rounds. A third audit round found zero additional safe candidates.

## Removed implementations

| Round | File | Local line at audit | Symbol | Lines | Proof |
|---:|---|---:|---|---:|---|
| 1 | `app/runtime_layers/12_abuse_policy.py` | 558 | `abuse_settings_admin_card` | 10 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/12_abuse_policy.py` | 76 | `get_agent_runtime_config` | 7 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/13_admin_abuse_queue.py` | 71 | `_insert_abuse_event` | 41 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/12_abuse_policy.py` | 158 | `refresh_fast_current_state` | 48 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/14_abuse_metrics_ui.py` | 1037 | `vm_period_links` | 8 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/14_abuse_metrics_ui.py` | 113 | `get_agent_runtime_config` | 10 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/14_abuse_metrics_ui.py` | 222 | `refresh_fast_current_state` | 105 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/14_abuse_metrics_ui.py` | 329 | `abuse_settings_admin_card` | 65 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/18_operations_reset.py` | 133 | `top_vm_table` | 94 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/19_guest_ram.py` | 428 | `interface_table` | 62 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/19_guest_ram.py` | 42 | `refresh_fast_current_state` | 22 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/19_guest_ram.py` | 325 | `top_vm_table` | 55 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/09_admin_routes.py` | 948 | `purge_vm_data` | 81 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/30_inventory_storage_precision.py` | 707 | `_v48133_storage_disk_table` | 12 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/30_inventory_storage_precision.py` | 838 | `_v48133_storage_node_table` | 10 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/26_abuse_intelligence.py` | 486 | `refresh_fast_current_state` | 182 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/36_batched_ingest.py` | 52 | `process_node_vm_presence` | 124 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/32_performance_runtime.py` | 348 | `ingest_disk_io_current` | 3 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/27_abuse_dashboard.py` | 1298 | `_v48129_vm_detail_cpu_stat` | 12 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/04_charts_vm.py` | 502 | `vm_chart_svg` | 84 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/41_ui_layout_r2.py` | 494 | `_v5049_theme_selector_html` | 19 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 1 | `app/runtime_layers/41_ui_layout_r2.py` | 515 | `_v5049_runtime_theme_script` | 34 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 2 | `app/runtime_layers/12_abuse_policy.py` | 88 | `_abuse_state_map` | 17 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 2 | `app/runtime_layers/12_abuse_policy.py` | 107 | `_insert_abuse_event` | 39 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 2 | `app/runtime_layers/14_abuse_metrics_ui.py` | 140 | `_insert_abuse_event` | 50 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |
| 2 | `app/runtime_layers/26_abuse_intelligence.py` | 468 | `_v48126_ram_hit` | 14 | Overwritten, unreachable after load, not called during import, no decorator/default side effect, no intervening load |

## Intentionally retained

- Decorated route implementations, even when a later handler replaces the endpoint.
- Any old function retained by `app.view_functions`, Flask hooks, wrapper aliases, closures, defaults or registries.
- Any implementation called during import or schema/bootstrap initialization.
- Compatibility branches, migrations, SQL, Agent protocol, feature flags and operational scripts.
- **158 captured historical implementations** and **14 historical implementations observed executing during import**.

This is a conservative cleanup, not a behavior rewrite.
