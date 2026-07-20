from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
LAYER = APP / "runtime_layers/44_consumption_node_vm_rollup.py"
MIGRATION = ROOT / "postgres/sql/014_node_vm_consumption_rollups.sql"
RELEASE = "50.5.9-prod-r20-consumption-node-vm-rollup-alignment-hotfix"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_release_and_final_runtime_layer_identity() -> None:
    assert text(ROOT / "VERSION").strip() == RELEASE
    manifest = json.loads(text(APP / "runtime_layers/manifest.json"))
    assert manifest[-1]["file"] == LAYER.name
    assert f'RELEASE="{RELEASE}"' in text(ROOT / "deploy/postgres/provision-postgres-native.sh")


def test_additive_node_vm_rollup_schema_is_small_and_indexed() -> None:
    sql = text(MIGRATION)
    assert "CREATE TABLE IF NOT EXISTS node_vm_consumption_hourly" in sql
    assert "CREATE TABLE IF NOT EXISTS node_vm_consumption_daily" in sql
    assert "PRIMARY KEY (hour_start, node)" in sql
    assert "PRIMARY KEY (day_start, node)" in sql
    assert "idx_node_vm_consumption_hourly_node_time" in sql
    assert "idx_node_vm_consumption_daily_node_time" in sql
    assert "vm_uuid" not in sql
    assert not any(word in sql.upper() for word in ("DROP TABLE", "TRUNCATE TABLE", "ALTER TABLE"))


def test_normal_push_writes_compact_rollup_in_same_copy_transaction() -> None:
    source = text(LAYER)
    assert "_r20_iface_copy_base = _v5052_write_interface_copy_batch" in source
    assert "FROM pg_temp.vi5052_iface_stage GROUP BY hour_start,node" in source
    assert "FROM pg_temp.vi5052_iface_stage GROUP BY day_start,node" in source
    # Guest perspective is the inverse of the host tap direction.
    assert "bridge=? THEN tx_delta ELSE 0 END)::bigint vm_public_rx" in source
    assert "bridge=? THEN rx_delta ELSE 0 END)::bigint vm_public_tx" in source
    assert "ON CONFLICT(hour_start,node) DO UPDATE" in source
    assert "ON CONFLICT(day_start,node) DO UPDATE" in source


def test_node_queries_keep_raw_hourly_daily_tiering() -> None:
    source = text(LAYER)
    for name in (
        "_r20_physical_raw", "_r20_physical_hourly", "_r20_physical_daily",
        "_r20_vm_node_raw", "_r20_vm_node_hourly", "_r20_vm_node_daily",
        "_r20_tiered_source",
    ):
        assert f"def {name}" in source
    assert "node_vm_consumption_hourly" in source
    assert "node_vm_consumption_daily" in source
    assert "UNION ALL" in source
    assert "LIMIT ? OFFSET ?" in source


def test_node_and_group_tables_share_fixed_alignment_contract() -> None:
    source = text(LAYER)
    for header in ("PHYSICAL PUBLIC", "ALL VM PUBLIC", "PHYSICAL PRIVATE", "ALL VM PRIVATE"):
        assert source.count(header) >= 2
    for header in ("PUBLIC DIFF", "PRIVATE DIFF", "COVERAGE", "LATEST"):
        assert header in source
    for sortable in ("Public Diff", "Private Diff", "Coverage", "Latest Sample"):
        assert sortable in source
    assert "v5060-node-table" in source
    assert "v5060-group-table" in source
    assert source.count("<colgroup>") >= 2
    assert "table-layout:fixed!important" in source
    assert "font-variant-numeric:tabular-nums" in source
    assert "all_group_rows(visibility=\"active\")" in source
    assert "ng_visible.is_active=1" in source


def test_node_group_and_dashboard_scope_are_preserved() -> None:
    source = text(LAYER)
    assert 'app.view_functions["bandwidth_consumption_page"]' in source
    assert 'app.view_functions["dashboard"]' not in source
    assert "dashboard_page" not in source
    assert "@app.route" not in source
    # Existing endpoint remains registered, so the route map does not grow.
    assert 'app.view_functions["push_bandwidth_consumption"]' in source


def test_legacy_two_hour_ingest_is_retired_without_route_breakage() -> None:
    source = text(LAYER)
    assert "legacy_2h_accounting_retired" in source
    assert "}),410" in source or "}), 410" in source
    assert "Use normal 5-minute /push" in source


def test_clear_all_and_purge_lifecycle_cover_new_rollups() -> None:
    maintenance = text(APP / "maintenance_native.py")
    source = text(LAYER)
    action = text(APP / "runtime_layers/34_bandwidth_consumption.py")
    for table in ("node_vm_consumption_hourly", "node_vm_consumption_daily"):
        assert f'"{table}"' in maintenance
        assert table in source
        assert f"DELETE FROM {table}" in source
    assert "def purge_vm_data" in source
    assert "_r20_rebuild_node_vm_rollups" in source
    assert "def purge_all_vms_for_node" in source
    assert "Consumption has no separate clear button" in source
    assert "Use Clear All Monitoring Data" in action


def test_installer_and_backfill_support_migration_014() -> None:
    installer = text(ROOT / "deploy/postgres/provision-postgres-native.sh")
    bootstrap = text(ROOT / "install.sh")
    rollup = text(APP / "consumption_rollup.py")
    assert "014_node_vm_consumption_rollups.sql" in installer
    assert "014_node_vm_consumption_rollups.sql" in bootstrap
    assert '< "$APP_DIR/postgres/sql/014_node_vm_consumption_rollups.sql"' in installer
    assert "node_vm_consumption_hourly" in rollup
    assert "node_vm_consumption_daily" in rollup
    assert "app.py" not in rollup
    assert "dedicated_connection" in rollup
