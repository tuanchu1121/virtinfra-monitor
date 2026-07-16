from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app" / "app.py").read_text(encoding="utf-8")
RUNNER = (ROOT / "app" / "maintenance.py").read_text(encoding="utf-8")
NATIVE = (ROOT / "app" / "maintenance_native.py").read_text(encoding="utf-8")
RETENTION = (ROOT / "app" / "retention.py").read_text(encoding="utf-8")
INSTALLER = (ROOT / "deploy" / "postgres" / "install-postgres-native.sh").read_text(encoding="utf-8")
MIGRATION = (ROOT / "postgres" / "sql" / "006_postgres_native_maintenance.sql").read_text(encoding="utf-8")


def _last_function_source(source: str, name: str) -> str:
    module = ast.parse(source)
    nodes = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == name]
    assert nodes, name
    node = nodes[-1]
    lines = source.splitlines()
    return "\n".join(lines[node.lineno - 1 : node.end_lineno])


def test_maintenance_ui_removes_misleading_controls():
    card = _last_function_source(APP, "database_maintenance_card")
    live_card = _last_function_source(APP, "_v490_live_cache_card")
    assert "Checkpoint" not in card
    assert "CLEAR LIVE 5M" not in card
    assert 'return ""' in live_card
    assert "Run online VACUUM" in card
    assert "DELETE AND VACUUM" in card
    assert "TRUNCATE" in card
    assert "Online VACUUM after clear" not in card
    assert 'app.view_functions["admin_clear_live_cache"]' in APP


def test_queue_uses_postgresql_advisory_lock_and_hard_guard():
    enqueue = _last_function_source(APP, "enqueue_maintenance_job")
    assert "pg_advisory_xact_lock" in enqueue
    assert "MAINTENANCE_ENQUEUE_LOCK" in enqueue
    assert '"checkpoint"' not in enqueue
    assert '"clear_live_cache"' not in enqueue
    assert "uq_maintenance_jobs_one_active" in MIGRATION
    assert "WHERE status IN ('queued', 'running')" in MIGRATION


def test_import_time_cleanup_is_disabled_for_workers():
    assert 'BW_MAINTENANCE_IMPORT' in APP
    assert 'os.environ["BW_MAINTENANCE_IMPORT"] = "1"' in RUNNER
    assert 'os.environ["BW_MAINTENANCE_IMPORT"] = "1"' in RETENTION


def test_vacuum_is_online_dedicated_and_unbounded_by_web_timeout():
    execute = _last_function_source(RUNNER, "execute_action")
    assert 'if action == "vacuum"' in execute
    assert "stop_service" not in execute.split('if action == "vacuum"', 1)[1].split('if action == "delete_compact"', 1)[0]
    assert "maintenance_native.vacuum_analyze" in RUNNER
    assert 'autocommit=True' in NATIVE
    assert 'statement_timeout_ms=0' in NATIVE
    assert 'VACUUM (ANALYZE)' in NATIVE


def test_destructive_resets_use_complete_truncate_registries():
    required_monitoring = {
        "vm_abuse_incidents",
        "vm_disk_summary_current",
        "node_storage_mount_summary_current",
        "node_bandwidth_consumption_2h",
        "vm_chart_5m",
        "vm_raw_detail_5m",
        "node_chart_5m",
    }
    for table in required_monitoring:
        assert f'"{table}"' in NATIVE
    assert "TRUNCATE TABLE" in NATIVE
    assert "RESTART IDENTITY" in NATIVE
    execute = _last_function_source(RUNNER, "execute_action")
    assert "maintenance_native.clear_monitoring_data()" in execute
    assert "maintenance_native.reset_app_data()" in execute


def test_purge_and_push_share_the_same_node_lock_namespace():
    assert 'NODE_LOCK_PREFIX = "virtinfra-push:"' in NATIVE
    assert "maintenance_native.NODE_LOCK_PREFIX + node" in RUNNER
    push = _last_function_source(APP, "push")
    assert 'f"virtinfra-push:{node}"' in push


def test_installer_deploys_and_applies_native_maintenance():
    assert 'app/maintenance_native.py' in (ROOT / "install.sh").read_text(encoding="utf-8")
    assert 'maintenance_native.py" "$APP_DIR/maintenance_native.py' in INSTALLER
    assert '006_postgres_native_maintenance.sql' in INSTALLER
    assert 'Apply PostgreSQL-native maintenance guards' in INSTALLER
