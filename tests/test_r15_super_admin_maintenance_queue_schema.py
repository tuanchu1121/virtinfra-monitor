from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def test_r15_boolean_queue_migration_contract_remains_available() -> None:
    groups = (APP / "node_groups.py").read_text(encoding="utf-8")
    canonical = (APP / "runtime_layers/38_agent_maintenance_canonical_routes.py").read_text(encoding="utf-8")
    assert '"admin_database_maintenance"' in groups.split("ADMIN_ALLOWED_ENDPOINTS", 1)[1].split("}", 1)[0]
    assert '"admin_cancel_maintenance_v5057"' in groups.split("ADMIN_ALLOWED_ENDPOINTS", 1)[1].split("}", 1)[0]
    assert '"admin_purge_node_vms"' in groups.split("ADMIN_ALLOWED_ENDPOINTS", 1)[1].split("}", 1)[0]
    assert 'SUPER_ADMIN_ONLY_MAINTENANCE_ACTIONS' in groups
    assert '"clear_monitoring_data"' in groups and '"reset_app_data"' in groups
    assert 'if role != "super_admin"' in canonical
    assert 'str(row[3] or "") != "super_admin"' in canonical


def test_queue_schema_is_boolean_for_new_and_existing_installations() -> None:
    bootstrap = (APP / "runtime_layers/00_bootstrap_database.py").read_text(encoding="utf-8")
    migration = (ROOT / "postgres/sql/013_maintenance_queue_boolean.sql").read_text(encoding="utf-8")
    provision = (ROOT / "deploy/postgres/provision-postgres-native.sh").read_text(encoding="utf-8")
    assert "cancel_requested BOOLEAN NOT NULL DEFAULT FALSE" in bootstrap
    assert "cancel_requested INTEGER NOT NULL DEFAULT 0" not in bootstrap
    assert "ALTER COLUMN cancel_requested TYPE BOOLEAN" in migration
    assert "USING (COALESCE(cancel_requested, 0) <> 0)" in migration
    assert "013_maintenance_queue_boolean.sql" in provision
    assert '[[ "$QUEUE_CANCEL_TYPE" == "boolean" ]]' in provision
    assert "schema-self-test" in provision and "ROLLBACK;" in provision


def test_dispatcher_is_reloaded_without_stopping_active_job_workers() -> None:
    provision = (ROOT / "deploy/postgres/provision-postgres-native.sh").read_text(encoding="utf-8")
    assert "systemctl stop bw-monitor-maintenance-dispatch.service" in provision
    assert "systemctl restart bw-monitor-maintenance-watchdog.timer" in provision
    assert "systemctl --no-block start bw-monitor-maintenance-dispatch.service" in provision
    assert "systemctl stop 'bw-monitor-maintenance@" not in provision
