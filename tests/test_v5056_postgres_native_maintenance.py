from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
from runtime_source import read_app_source
APP = read_app_source()
RUNNER = (ROOT / "app/maintenance.py").read_text(encoding="utf-8")
NATIVE = (ROOT / "app/maintenance_native.py").read_text(encoding="utf-8")
RETENTION = (ROOT / "app/retention.py").read_text(encoding="utf-8")
INSTALLER = (ROOT / "deploy/postgres/provision-postgres-native.sh").read_text(encoding="utf-8")


def last_function(source: str, name: str) -> str:
    module = ast.parse(source)
    nodes = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == name]
    assert nodes, name
    node = nodes[-1]
    lines = source.splitlines()
    return "\n".join(lines[node.lineno - 1 : node.end_lineno])


def test_maintenance_ui_keeps_native_online_controls_and_removes_live_delete():
    card = last_function(APP, "database_maintenance_card")
    live_card = last_function(APP, "_v490_live_cache_card")
    assert "Checkpoint" not in card
    assert "CLEAR LIVE 5M" not in card
    assert 'return ""' in live_card
    assert "Nuclear reset preview" in card or "Nuclear operational reset" in card
    assert 'app.view_functions["admin_clear_live_cache"]' in APP


def test_import_time_cleanup_is_disabled_for_workers():
    assert "BW_MAINTENANCE_IMPORT" in APP
    assert 'os.environ["BW_MAINTENANCE_IMPORT"] = "1"' in RUNNER
    assert 'os.environ["BW_MAINTENANCE_IMPORT"] = "1"' in RETENTION


def test_vacuum_is_online_dedicated_and_unbounded_by_web_timeout():
    execute = last_function(RUNNER, "execute_action")
    vacuum_branch = execute.split('if action == "vacuum"', 1)[1].split('if action == "delete_compact"', 1)[0]
    assert "stop_service" not in vacuum_branch
    assert "maintenance_native.vacuum_analyze" in RUNNER
    assert "autocommit=True" in NATIVE
    assert "statement_timeout_ms=0" in NATIVE
    assert "VACUUM (ANALYZE)" in NATIVE


def test_destructive_resets_use_explicit_complete_truncate_registries():
    for table in {
        "vm_abuse_incidents",
        "vm_disk_summary_current",
        "node_storage_mount_summary_current",
        "node_bandwidth_consumption_2h",
        "vm_chart_5m",
        "vm_raw_detail_5m",
        "node_chart_5m",
    }:
        assert f'"{table}"' in NATIVE
    assert "TRUNCATE TABLE" in NATIVE
    assert "RESTART IDENTITY" in NATIVE
    execute = last_function(RUNNER, "execute_action")
    assert "maintenance_native.clear_monitoring_data()" in execute
    assert "maintenance_native.reset_app_data()" in execute


def test_purge_and_push_share_the_same_node_lock_namespace():
    assert 'NODE_LOCK_PREFIX = "virtinfra-push:"' in NATIVE
    assert "maintenance_native.NODE_LOCK_PREFIX + node" in RUNNER
    push = last_function(APP, "push")
    assert 'f"virtinfra-push:{node}"' in push


def test_installer_keeps_native_maintenance_migration_before_safe_queue_migration():
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "app/maintenance_native.py" in install
    assert 'maintenance_native.py" "$APP_DIR/maintenance_native.py' in INSTALLER
    pos6 = INSTALLER.index("006_postgres_native_maintenance.sql")
    pos7 = INSTALLER.index("007_safe_maintenance_queue.sql")
    assert pos6 < pos7
