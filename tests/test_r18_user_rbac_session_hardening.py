from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "rbac-runtime-validation.py"
VERSION = "50.5.9-prod-r22-consumption-hardening-global-sort"


def test_release_identity() -> None:
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == VERSION
    assert VERSION in (ROOT / "app" / "node_groups.py").read_text(encoding="utf-8")


def test_rbac_runtime_matrix() -> None:
    proc = subprocess.run(
        [sys.executable, str(TOOL)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.strip().startswith("{")]
    assert lines, proc.stdout
    result = json.loads(lines[-1])
    expected = {
        "last_super_admin_downgrade_block",
        "self_admin_reset_block",
        "admin_self_downgrade_block",
        "duplicate_superadmin_create_block",
        "duplicate_user_create_block",
        "invalid_role_rejected",
        "admin_cannot_create_superadmin",
        "admin_direct_superadmin_manage_block",
        "superadmin_role_controls_visible",
        "superadmin_can_promote",
        "password_reset_role_unchanged",
        "last_superadmin_disable_delete_block",
        "emergency_setup_takeover_block",
        "password_reset_revokes_session",
        "disable_revokes_dashboard_session",
        "delete_revokes_dashboard_session",
        "role_change_requires_relogin",
        "admin_consumption_cleanup_visible_clear_hidden",
        "admin_consumption_cleanup_backend_allowed",
        "admin_consumption_clear_backend_block",
        "admin_logs_read_only",
        "admin_logs_table_alignment",
        "admin_system_health_api_read",
        "viewer_operations_forbidden",
        "csrf_required",
        "admin_dashboard_login_issues_valid_session",
        "viewer_login_stays_read_only",
        "own_password_change_refreshes_session",
        "initial_setup_still_works",
        "superadmin_audit_role_correct",
    }
    assert set(result) == expected
    assert all(value == "PASS" for value in result.values())


def test_no_schema_or_route_addition_for_r18() -> None:
    source = (ROOT / "app" / "node_groups.py").read_text(encoding="utf-8")
    assert "dashboard_auth_stamp" in source
    assert "Username already exists" in source
    assert "initial setup is disabled after the first user is created" in source
    assert "user_role_changed" in source
    assert "role_unchanged" in source
    assert "ALTER TABLE dashboard_users" not in source
