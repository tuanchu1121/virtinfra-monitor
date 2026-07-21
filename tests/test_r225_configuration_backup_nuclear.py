from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
sys.path.insert(0, str(APP))

import configuration_backup as cb
import emergency_backup as eb


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_selective_configuration_backup_roundtrip_without_database(tmp_path, monkeypatch):
    monkeypatch.setenv("BW_CONFIGURATION_BACKUP_ROOT", str(tmp_path))
    payload = {
        "users": [{"username": "root", "password_hash": "hash", "role": "super_admin", "is_active": 1}],
        "api_keys": [{"key_id": "api_1", "secret_hash": "hash"}],
        "settings": [{"key": "simple_theme_settings_v4", "value": "{}", "updated_at": 1}],
        "groups": [{"name": "VN", "description": "Vietnam", "country_code": "VN", "is_active": 1}],
        "node_group_mapping": [{"node": "node-1", "group_name": "VN"}],
        "exported_by": "root",
    }
    monkeypatch.setattr(cb, "_export_configuration", lambda actor: payload)
    result = cb.create_configuration_backup("root", reason="test", protect=True)
    assert result["status"] == "verified"
    assert result["protected"] is True
    assert result["configuration"]["node_group_mapping"][0]["node"] == "node-1"
    listed = cb.list_configuration_backups()
    assert len(listed) == 1 and listed[0]["status"] == "verified"
    with pytest.raises(PermissionError):
        cb.delete_configuration_backup(result["backup_id"])
    cb.set_configuration_backup_protected(result["backup_id"], False)
    cb.delete_configuration_backup(result["backup_id"])
    assert not (tmp_path / result["backup_id"]).exists()


def test_configuration_archive_rejects_unexpected_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("BW_CONFIGURATION_BACKUP_ROOT", str(tmp_path))
    name = "config-20260721T000000Z-abcdef123456.zip"
    with zipfile.ZipFile(tmp_path / name, "w") as archive:
        archive.writestr("configuration.json", "{}")
        archive.writestr("metadata.json", json.dumps({"format": cb.FORMAT_NAME, "format_version": 1}))
        archive.writestr("MANIFEST.sha256", "0" * 64 + "  configuration.json\n" + "0" * 64 + "  metadata.json\n")
        archive.writestr("../escape", "bad")
    with pytest.raises(ValueError, match="unexpected"):
        cb.verify_configuration_backup(name)


def test_safe_settings_are_whitelisted_not_runtime_state():
    assert "simple_theme_settings_v4" in cb.SAFE_SETTING_KEYS
    assert "abuse_cpu_full_percent" in cb.SAFE_SETTING_KEYS
    assert "abuse_ram_rss_percent" in cb.SAFE_SETTING_KEYS
    assert "abuse_ram_required_seconds" in cb.SAFE_SETTING_KEYS
    forbidden = {
        "app_secret_key",
        "operational_push_accept_after",
        "bandwidth_consumption_accept_after",
        "consumption_backfill_status_r22",
        "page_cache_generation",
    }
    assert not (forbidden & cb.SAFE_SETTING_KEYS)


def test_queue_and_worker_support_new_actions():
    queue = read(APP / "maintenance_queue.py")
    worker = read(APP / "maintenance.py")
    for action in ("configuration_backup", "configuration_restore", "full_backup", "full_backup_verify"):
        assert f'"{action}"' in queue
        assert f'action == "{action}"' in worker or f'"{action}"' in worker
    assert "create_configuration_backup" in worker
    assert "restore_configuration_backup" in worker
    assert "skipped_by_super_admin" in worker


def test_true_nuclear_preserves_only_current_identity_job_and_audit():
    native = read(APP / "maintenance_native.py")
    assert 'preserved_tables = {"dashboard_users", "maintenance_jobs", "maintenance_nuclear_audit"}' in native
    assert "existing - preserved_tables" in native
    assert "DELETE FROM public.dashboard_users WHERE id<>%s" in native
    assert "DELETE FROM public.maintenance_jobs WHERE id<>%s" in native
    assert "TRUNCATE TABLE public.maintenance_nuclear_audit" in native
    assert '"app_secret_key": secrets.token_urlsafe(64)' in native
    assert "operational_push_accept_after" in native
    assert "bandwidth_consumption_accept_after" in native
    assert "finalize_nuclear_audit" in native


def test_super_admin_only_ui_and_strong_no_backup_confirmation():
    layer = read(APP / "runtime_layers" / "38_agent_maintenance_canonical_routes.py")
    assert "Forbidden: super_admin role required" in layer
    assert "RESTORE CONFIGURATION" in layer
    assert "RESET VIRTINFRA WITHOUT BACKUP" in layer
    assert "Create protected Configuration Backup" in layer
    assert "Create Full Emergency Database Backup" in layer
    assert "configuration_backup_download" in layer
    assert "full_backup_verify" in layer
    assert "Full Emergency Backup verification job" in layer
    queue_ui = read(APP / "runtime_layers" / "13_admin_abuse_queue.py")
    assert "sensitive_queue_actions" in queue_ui
    assert 'clean_role(dashboard_role()) != "super_admin"' in queue_ui
    assert "full_backup_download" in layer
    assert "full_backup_protect" in layer
    assert "full_backup_delete" in layer
    assert "No direct web restore" in layer or "no direct web restore" in layer
    assert "current super_admin" in layer
    assert layer.index('if status == "verified":') < layer.index('protect_action = "configuration_backup_unprotect"')


def test_migration_adds_pending_mapping_and_unique_nuclear_audit():
    migration = read(ROOT / "postgres" / "sql" / "016_configuration_backup_nuclear.sql")
    assert "pending_node_group_restore" in migration
    assert "configuration-restore" in migration
    assert "uq_maintenance_nuclear_audit_job" in migration
    assert "backup_status" in migration
    assert "016_configuration_backup_nuclear" in migration



def test_full_emergency_backup_catalog_verify_protect_and_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("BW_BACKUP_ROOT", str(tmp_path))
    backup_id = "20260721-120000"
    folder = tmp_path / backup_id
    folder.mkdir()
    dump = b"postgres-custom-dump"
    catalog = b"; Archive created at 2026-07-21\n; TOC Entries: 2\n"
    (folder / "database.dump").write_bytes(dump)
    (folder / "database.list").write_bytes(catalog)
    (folder / "metadata.txt").write_text("release=r22.5\nhostname=test\n", encoding="utf-8")
    import hashlib
    manifest = (
        f"{hashlib.sha256(dump).hexdigest()}  database.dump\n"
        f"{hashlib.sha256(catalog).hexdigest()}  database.list\n"
        f"{hashlib.sha256((folder / 'metadata.txt').read_bytes()).hexdigest()}  metadata.txt\n"
    )
    (folder / "SHA256SUMS").write_text(manifest, encoding="ascii")
    verified = eb.verify_emergency_backup(backup_id)
    assert verified["status"] == "verified"
    assert verified["dump_bytes"] == len(dump)
    assert eb.emergency_dump_path(backup_id) == folder / "database.dump"
    eb.set_emergency_backup_protected(backup_id, True)
    assert eb.list_emergency_backups()[0]["protected"] is True
    with pytest.raises(PermissionError):
        eb.delete_emergency_backup(backup_id)
    eb.set_emergency_backup_protected(backup_id, False)
    eb.delete_emergency_backup(backup_id)
    assert not folder.exists()


def test_protected_full_backups_and_configuration_catalog_are_excluded_from_scheduled_cleanup():
    backup_script = read(ROOT / "deploy" / "postgres" / "backup.sh")
    assert '[[ "$(basename -- "$old_backup")" == "configuration" ]] && continue' in backup_script
    assert '[[ -e "$old_backup/.protected" ]] && continue' in backup_script
    worker = read(APP / "maintenance.py")
    assert "create_verified_pre_nuclear_backup(protect=True)" in worker

def test_installer_deploys_module_and_migration():
    bootstrap = read(ROOT / "install.sh")
    provision = read(ROOT / "deploy" / "postgres" / "provision-postgres-native.sh")
    preflight = read(ROOT / "preflight.sh")
    for text in (bootstrap, provision, preflight):
        assert "configuration_backup.py" in text
        assert "emergency_backup.py" in text
        assert "016_configuration_backup_nuclear.sql" in text


def test_top_vm_supports_2000_rows_without_pagination():
    ui = read(APP / "runtime_layers" / "14_abuse_metrics_ui.py")
    query = read(APP / "runtime_layers" / "29_storage_integration.py")
    assert 'option value="2000"' in ui
    assert "min(2000" in ui
    assert "min(2000" in query


def test_preflight_isolates_legacy_validators_and_accepts_only_complete_success():
    helper = read(ROOT / "tools" / "run-isolated-validation.py")
    preflight = read(ROOT / "preflight.sh")
    assert "start_new_session=True" in helper
    assert "os.killpg" in helper
    assert "FAILURE_MARKERS" in helper
    assert "run-isolated-validation.py" in preflight
    assert "run_contract tests/test_bandwidth_consumption_agent.py" in preflight
