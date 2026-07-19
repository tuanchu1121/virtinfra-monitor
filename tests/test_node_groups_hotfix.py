from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from runtime_source import read_app_source

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "app" / "node_groups.py"
MIGRATION = ROOT / "postgres" / "sql" / "011_node_groups.sql"
R6_MIGRATION = ROOT / "postgres" / "sql" / "012_node_groups_r6_safety.sql"
RUNTIME_TOOL = ROOT / "tools" / "node-groups-runtime-validation.py"
EXPECTED_RELEASE = "50.5.9-prod-r8-safe-dead-code-prune"


@pytest.fixture(scope="module")
def runtime_result(tmp_path_factory):
    output = tmp_path_factory.mktemp("node-groups") / "routes.json"
    env = dict(__import__("os").environ)
    env["NODE_GROUPS_ROUTE_OUTPUT"] = str(output)
    proc = subprocess.run(
        [sys.executable, str(RUNTIME_TOOL)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.strip().startswith("{")]
    assert lines, proc.stdout
    return json.loads(lines[-1]), json.loads(output.read_text(encoding="utf-8"))


def _manifest_entries() -> dict[str, str]:
    entries = {}
    for raw in (ROOT / "audit/node-groups/BASELINE_SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if raw.strip():
            digest, name = raw.split(None, 1)
            entries[name.lstrip("*./")] = digest
    return entries


def _route_key(item):
    return item["rule"], item["endpoint"], tuple(item["methods"])


def test_release_identity():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == EXPECTED_RELEASE
    assert f'RELEASE="{EXPECTED_RELEASE}"' in (ROOT / "deploy/postgres/install-postgres-native.sh").read_text(encoding="utf-8")


def test_r6_changes_only_the_effective_r5_loader_and_required_baseline_sections():
    data = read_app_source()
    marker = "# VirtInfra Monitor 50.5.9 prod-r5 - additive Node Groups hotfix"
    assert data.count(marker) == 1
    connector = data[data.index(marker):]
    assert "class _NodeGroupsModuleProxy:" in connector
    assert "_node_groups_module = _node_groups_sys.modules.get(__name__)" in connector
    assert "_node_groups_hotfix.install(_node_groups_module)" in connector
    assert "Green" + "cloud" not in data
    assert "Green@" + "1234" not in data
    assert "2-hour Node Accounting Storage" in data
    assert "accounting/RETENTION7 controls live only under Maintenance" in data


def test_existing_postgresql_migrations_are_byte_identical():
    baseline = _manifest_entries()
    for path in sorted((ROOT / "postgres/sql").glob("0[0-1][0-9]_*.sql")):
        if path.name in {"011_node_groups.sql", "012_node_groups_r6_safety.sql"}:
            continue
        rel = path.relative_to(ROOT).as_posix()
        assert rel in baseline, rel
        assert hashlib.sha256(path.read_bytes()).hexdigest() == baseline[rel], rel


def test_additive_postgresql_migration_contract():
    sql = MIGRATION.read_text(encoding="utf-8")
    for table in ("node_groups", "node_group_memberships", "node_group_membership_history"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "REFERENCES node_inventory(node) ON DELETE CASCADE" in sql
    assert "REFERENCES node_groups(id) ON DELETE RESTRICT" in sql
    assert "WHERE is_system = 1" in sql
    assert "'Ungrouped'" in sql
    assert "node_groups_role_migration_v1" in sql
    assert "UPDATE dashboard_users" in sql and "SET role = 'super_admin'" in sql
    assert "WHERE role = 'admin'" in sql
    assert "ON CONFLICT(key) DO NOTHING" in sql
    assert not re.search(r"\b(?:ALTER|DROP|TRUNCATE)\s+TABLE\s+(?:usage|node_stats|vm_perf_stats|vm_current_fast)\b", sql, re.I)


def test_r6_safety_migration_is_additive_idempotent_and_decouples_push():
    sql = R6_MIGRATION.read_text(encoding="utf-8")
    assert "CREATE INDEX IF NOT EXISTS idx_node_group_memberships_node" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_node_group_memberships_group_id" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_node_groups_hidden" in sql
    assert "CREATE OR REPLACE FUNCTION virtinfra_assign_ungrouped_membership" in sql
    assert "CREATE TRIGGER trg_node_inventory_assign_ungrouped" in sql
    assert "ON CONFLICT (node) DO NOTHING" in sql
    assert "WHERE NOT EXISTS" in sql
    assert not re.search(r"\b(?:DROP|TRUNCATE)\s+TABLE\b", sql, re.I)
    module = MODULE.read_text(encoding="utf-8")
    assert '"push":' not in module[module.index("view_replacements="):]
    assert '"push_view"' not in module

def test_node_group_audit_event_contract():
    text = MODULE.read_text(encoding="utf-8")
    for event in (
        "node_group_created", "node_group_updated", "node_group_hidden",
        "node_group_restored", "node_group_deleted", "node_group_assigned",
        "node_group_moved", "node_group_removed",
    ):
        assert event in text
    for field in ("actor", "node", "old_group_name", "new_group_name", "created_at"):
        assert field in text


def test_runtime_role_crud_assignment_inheritance_and_filters(runtime_result):
    result, _routes = runtime_result
    expected = {
        "role_migration_idempotent", "super_admin_preserved", "node_group_crud",
        "ungrouped_protection", "occupied_group_delete_block", "new_node_ungrouped",
        "bulk_assign", "vm_inheritance", "audit_events", "page_filters",
        "group_all_html_equivalence", "group_all_delegation",
        "admin_permission_boundary", "super_admin_stealth", "viewer_read_only",
        "push_view_untouched", "node_groups_monitoring", "route_contract",
    }
    assert {key for key, value in result.items() if value == "PASS"} == expected
    assert result["route_count"] == 83


def test_route_map_preserves_baseline_and_adds_only_node_group_routes(runtime_result):
    _result, current = runtime_result
    baseline = json.loads((ROOT / "audit/node-groups/BASELINE_ROUTES.json").read_text(encoding="utf-8"))
    current_counter = Counter(_route_key(item) for item in current)
    baseline_counter = Counter(_route_key(item) for item in baseline)
    assert not (baseline_counter - current_counter)
    assert current_counter - baseline_counter == Counter({
        ("/admin/node-groups/action", "admin_node_groups_action", ("POST",)): 1,
        ("/admin/node-groups/assign", "admin_node_groups_assign", ("POST",)): 1,
        ("/admin/node-groups/bulk", "admin_node_groups_bulk", ("POST",)): 1,
        ("/admin/node-groups/create", "admin_node_groups_create", ("POST",)): 1,
        ("/admin/node-groups/update", "admin_node_groups_update", ("POST",)): 1,
        ("/node-groups", "node_groups_page", ("GET",)): 1,
        ("/node-groups/summary", "node_groups_summary", ("GET",)): 1,
        ("/node-groups/<int:group_id>/nodes", "node_group_nodes", ("GET",)): 1,
    })


def test_ui_regression_contract_passes():
    report = json.loads((ROOT / "audit/node-groups/UI_REGRESSION.json").read_text(encoding="utf-8"))
    assert set(report) == {
        "admin-maintenance", "admin-node-groups", "admin-overview", "admin-nodes",
        "admin-vms", "dashboard", "top-vm", "node-health", "storage-io",
        "consumption", "vm-abuse",
    }
    assert all(page["passed"] is True for page in report.values())


def test_browser_ui_regression_passes_desktop_tablet_and_mobile():
    report = json.loads((ROOT / "audit/node-groups/UI_BROWSER_REGRESSION.json").read_text(encoding="utf-8"))
    assert set(report) == {
        "admin-maintenance", "admin-node-groups", "admin-overview", "admin-nodes",
        "admin-vms", "dashboard", "node-groups", "top-vm", "node-health",
        "storage-io", "consumption", "vm-abuse",
    }
    assert all(
        viewport["passed"] is True
        for page in report.values()
        for viewport in page.values()
    )


def test_local_flag_icons_are_vendored_without_runtime_network_dependency():
    root = ROOT / "app/static/flags"
    flags = list(root.glob("*.svg"))
    assert len(flags) >= 240
    for required in ("neutral.svg", "vn.svg", "jp.svg", "sg.svg"):
        assert (root / required).is_file()
    css = (root / "node-groups.css").read_text(encoding="utf-8")
    assert "https://" not in css and "http://" not in css and "//cdn" not in css
    assert "width:20px" in css and "height:15px" in css and "margin-right:6px" in css
    module = MODULE.read_text(encoding="utf-8")
    assert 'static/flags' in module
    assert 'width="20" height="15"' in module


def test_installer_copies_and_applies_additive_files():
    installer = (ROOT / "deploy/postgres/install-postgres-native.sh").read_text(encoding="utf-8")
    bootstrap = (ROOT / "install.sh").read_text(encoding="utf-8")
    for marker in (
        "app/node_groups.py", "postgres/sql/011_node_groups.sql",
        "postgres/sql/012_node_groups_r6_safety.sql",
        "app/static/flags/node-groups.css",
        "app/static/flags/neutral.svg",
        "app/static/flags/vn.svg",
    ):
        assert marker in bootstrap
    assert 'install -m 0644 "$APP_SRC/node_groups.py"' in installer
    assert 'find "$APP_SRC/static/flags"' in installer
    assert '< "$APP_DIR/postgres/sql/011_node_groups.sql"' in installer
    assert '< "$APP_DIR/postgres/sql/012_node_groups_r6_safety.sql"' in installer


def test_no_runtime_cdn_or_npm_dependency():
    text = MODULE.read_text(encoding="utf-8")
    assert "github.com/lipis" not in text
    assert "cdn" not in text.lower()
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "npm" not in requirements.lower()
