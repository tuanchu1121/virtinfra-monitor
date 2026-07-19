import ast
import importlib.util
import sqlite3
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app" / "app.py").read_text(encoding="utf-8")
SOURCE = (ROOT / "app" / "node_groups.py").read_text(encoding="utf-8")
VERSION = "50.5.9-prod-r7-production-minimal-rbac-visibility-ui-hotfix"


def load_hotfix():
    spec = importlib.util.spec_from_file_location("node_groups_r7_contract", ROOT / "app" / "node_groups.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def function_source(name):
    tree = ast.parse(SOURCE)
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    return ast.get_source_segment(SOURCE, node)


def test_release_and_effective_runtime_wiring():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == VERSION
    assert "_node_groups_hotfix.install(_node_groups_module)" in APP
    install = function_source("install")
    for endpoint in (
        "admin_page", "admin_users_page", "admin_create_user", "admin_user_action",
        "admin_change_password", "node_page", "vm_page", "storage_io_page",
        "bandwidth_consumption_page",
    ):
        assert f'"{endpoint}"' in install
    assert '"_v490_admin_overview":admin_overview' in install


def test_admin_capabilities_are_allowlisted_without_privileged_maintenance():
    module = load_hotfix()
    allowed = module.ADMIN_ALLOWED_ENDPOINTS
    assert {"admin_users_page", "admin_theme_manager", "admin_logs_page", "admin_system_health_page"} <= allowed
    assert "admin_database_maintenance" not in allowed
    assert "admin_retention_settings" not in allowed
    assert "admin_api_keys_page" not in allowed
    users = function_source("admin_users_page")
    assert "Super Admin only" in users
    assert "if not is_super_admin()" not in users
    create = function_source("admin_create_user")
    assert "_manageable_roles()" in create
    action = function_source("admin_user_action")
    assert "Super Admin account is protected" in action
    assert "role not in _manageable_roles()" in action


def test_change_password_is_session_bound_and_role_preserving():
    change = function_source("admin_change_password")
    assert "current_dashboard_user()" in change
    assert "check_password_hash(user[2], current)" in change
    assert "UPDATE dashboard_users SET password_hash=?,updated_at=? WHERE id=?" in change
    assert "set_admin_credentials" not in change
    update_block = change.split("conn.execute", 1)[1].split("conn.commit", 1)[0]
    assert "role=" not in update_block
    assert "username=" not in update_block


def test_canonical_visibility_excludes_hidden_group_node_and_deleted_node(tmp_path):
    database = tmp_path / "visibility.sqlite"
    conn = sqlite3.connect(database)
    conn.executescript("""
      CREATE TABLE node_inventory(node TEXT PRIMARY KEY,status TEXT,deleted_at INTEGER);
      CREATE TABLE node_groups(id INTEGER PRIMARY KEY,is_active INTEGER);
      CREATE TABLE node_group_memberships(node TEXT PRIMARY KEY,group_id INTEGER);
      INSERT INTO node_groups VALUES(1,1),(2,0);
      INSERT INTO node_inventory VALUES('visible','active',NULL),('hidden-group','active',NULL),
        ('hidden-node','hidden',NULL),('deleted-node','active',123);
      INSERT INTO node_group_memberships VALUES('visible',1),('hidden-group',2),('hidden-node',1),('deleted-node',1);
    """)
    conn.commit(); conn.close()
    module = load_hotfix()
    module._M = SimpleNamespace(db=lambda: sqlite3.connect(database))
    assert module.get_visible_node_names() == {"visible"}
    assert module.get_visible_node_names(1) == {"visible"}
    assert module.get_visible_node_names(2) == set()


def test_monitoring_surfaces_use_active_group_visibility_and_detail_guards():
    for name in ("get_node_rows", "get_node_health_rows", "get_top_vm_rows"):
        assert "get_visible_node_names" in function_source(name)
    assert "monitoring_node_visible" in function_source("node_page")
    assert "monitoring_vm_visible" in function_source("vm_page")
    for name in ("_v48140_disk_search_clause", "_v5058c_visible_nodes", "_v48126_visible_nodes"):
        assert "is_active=1" in function_source(name)


def test_node_group_search_move_ram_and_refresh_contracts():
    page = function_source("node_groups_page")
    assert page.count('name="q"') == 1
    assert 'name="node_q"' not in page
    assert "Search group, node or IP" in page
    assert "setInterval(refresh,30000)" in page
    assert "clearInterval(window.__virtinfraNodeGroupsRefreshTimer)" in page
    detail = function_source("node_group_nodes")
    assert "metric_level(pct,80,90)" in detail
    bulk = function_source("admin_node_groups_bulk")
    assert "'move_all_ungrouped'" in bulk
    assert "target=system_group_id()" in bulk


def test_admin_node_vm_renderers_have_direct_actions_and_no_bulk_selectors():
    nodes = function_source("admin_nodes_section")
    vms = function_source("admin_vms_section")
    assert "node-select" not in nodes and "bulk-nodes-form" not in nodes
    assert "vm-select" not in vms and "bulk-vms-form" not in vms
    for label in ("Hide", "Restore", "Move", "Purge VMs", "Purge Node"):
        assert label in nodes
    for label in ("Hide", "Restore", "Purge VM"):
        assert label in vms
    assert nodes.split("body.append", 1)[1].split("if not body", 1)[0].count("<td") == 11
    assert "colspan=\"11\"" in nodes
    assert vms.split("body.append", 1)[1].split("if not body", 1)[0].count("<td") == 5
    assert "colspan=\"5\"" in vms
    assert "GROUP HIDDEN" in nodes and "GROUP HIDDEN" in vms


def test_icon_scope_consumption_and_refresh_contracts():
    assert "def _inject_node_flags" not in SOURCE
    flag = function_source("flag_html")
    assert 'alt="" aria-hidden="true"' in flag
    group_consumption = function_source("_consumption_group_page")
    for heading in ("NODE GROUP", "NODES", "VMS", "RX", "TX", "TOTAL", "CPU", "RAM", "DISK"):
        assert heading in group_consumption
    assert "colspan=\"9\"" in group_consumption
    assert "AUTO_REFRESH_MS = 30000" in APP
    assert "window.__virtinfraAutoRefreshTimer" in APP
    assert "clearInterval(window.__virtinfraAutoRefreshTimer)" in APP
    assert "BW_AUTO_REFRESH_MS = 5000" not in APP


def test_storage_clear_and_consumption_apply_reset_order_remain_correct():
    assert '<button type="submit">Search</button><a class="clear"' in APP
    apply_index = APP.rfind('<button type="submit">Apply</button>')
    reset_index = APP.find('<a class="clear"', apply_index)
    assert apply_index >= 0 and reset_index > apply_index
