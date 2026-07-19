from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE_GROUPS = ROOT / "app" / "node_groups.py"
MAINTENANCE = ROOT / "app" / "maintenance_native.py"
R6_SQL = ROOT / "postgres" / "sql" / "012_node_groups_r6_safety.sql"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeRuntime:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.session = {
            "admin_username": "root",
            "dashboard_username": "root",
            "dashboard_role": "super_admin",
        }
        self.request = SimpleNamespace(args={})
        self.events = []

    def db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def now_ts():
        return 1_700_000_000

    @staticmethod
    def get_dashboard_user(username):
        if username == "root":
            return (1, "root", "hash", "super_admin", 1, 1, 1, None)
        return None

    @staticmethod
    def dashboard_username():
        return "root"

    def log_account_event(self, *args, **kwargs):
        self.events.append((args, kwargs))


def make_sqlite_runtime(tmp_path: Path):
    db_path = tmp_path / "node-groups.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE node_inventory(
            node TEXT PRIMARY KEY,
            first_seen INTEGER NOT NULL,
            last_push INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            hidden_at INTEGER,
            deleted_at INTEGER
        );
        CREATE TABLE dashboard_users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            last_login INTEGER
        );
        CREATE TABLE admin_settings(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        );
        INSERT INTO dashboard_users(
            username,password_hash,role,is_active,created_at,updated_at
        ) VALUES ('legacy','x','admin',1,1,1);
        INSERT INTO node_inventory(node,first_seen,last_push,status)
        VALUES ('node-a',1,1,'active'),('node-b',1,1,'active');
        """
    )
    conn.commit()
    conn.close()
    module = load_module(NODE_GROUPS, "node_groups_r6_sqlite")
    runtime = FakeRuntime(db_path)
    module._M = runtime
    return module, runtime


def test_sqlite_schema_is_idempotent_preserves_membership_and_assigns_new_nodes(tmp_path):
    module, runtime = make_sqlite_runtime(tmp_path)
    module.ensure_schema()
    module.ensure_schema()
    conn = runtime.db()
    try:
        system = conn.execute(
            "SELECT id,name,is_active,is_system FROM node_groups WHERE is_system=1"
        ).fetchone()
        assert system[1:] == ("Ungrouped", 1, 1)
        assert conn.execute("SELECT COUNT(*) FROM node_group_memberships").fetchone()[0] == 2
        assert conn.execute(
            "SELECT role FROM dashboard_users WHERE username='legacy'"
        ).fetchone()[0] == "super_admin"
        custom_id = conn.execute(
            """INSERT INTO node_groups(
                   name,description,country_code,is_active,is_system,created_at,updated_at
               ) VALUES ('Japan','','jp',1,0,1,1)"""
        ).lastrowid
        conn.execute(
            "UPDATE node_group_memberships SET group_id=? WHERE node='node-a'",
            (custom_id,),
        )
        conn.commit()
    finally:
        conn.close()

    module.ensure_schema()
    conn = runtime.db()
    try:
        assert conn.execute(
            "SELECT group_id FROM node_group_memberships WHERE node='node-a'"
        ).fetchone() == (custom_id,)
        conn.execute(
            "INSERT INTO node_inventory(node,first_seen,last_push,status) VALUES ('node-new',2,2,'active')"
        )
        conn.commit()
        assert conn.execute(
            """SELECT g.name FROM node_group_memberships m
               JOIN node_groups g ON g.id=m.group_id WHERE m.node='node-new'"""
        ).fetchone() == ("Ungrouped",)
        assert conn.execute(
            "SELECT COUNT(*) FROM node_group_memberships WHERE node='node-new'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_bulk_move_and_remove_keep_one_membership_and_write_history(tmp_path):
    module, runtime = make_sqlite_runtime(tmp_path)
    module.ensure_schema()
    conn = runtime.db()
    try:
        group_id = conn.execute(
            """INSERT INTO node_groups(
                   name,description,country_code,is_active,is_system,created_at,updated_at
               ) VALUES ('Vietnam','','vn',1,0,1,1)"""
        ).lastrowid
        conn.commit()
    finally:
        conn.close()

    moved = module.assign_nodes(["node-a", "node-a", "node-b"], group_id, "root")
    assert moved == {"changed": 2, "assigned": 2, "moved": 0, "removed": 0}
    system_id = module.system_group_id()
    removed = module.assign_nodes(["node-a"], system_id, "root")
    assert removed["changed"] == 1 and removed["removed"] == 1

    conn = runtime.db()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM node_group_memberships WHERE node='node-a'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT group_id FROM node_group_memberships WHERE node='node-a'"
        ).fetchone() == (system_id,)
        events = [row[0] for row in conn.execute(
            "SELECT event FROM node_group_membership_history ORDER BY id"
        ).fetchall()]
        assert events.count("node_group_assigned") == 2
        assert events[-1] == "node_group_removed"
    finally:
        conn.close()


def test_expanded_numeric_sort_uses_raw_values_and_keeps_na_last(tmp_path):
    module = load_module(NODE_GROUPS, "node_groups_r6_sort")
    module._M = SimpleNamespace(
        health_state=lambda last: {100: "healthy", 200: "warning", 300: "down"}.get(last, "unknown")
    )
    # node, vm, load1, load5, load15, cpu, used, total, read, write, abuse, last, group, country
    rows = [
        ("b", 2, None, None, None, 90.0, None, 2000, None, 20.0, 1, 200, "G", ""),
        ("a", 10, 2.0, 1.0, 1.0, 10.0, 1000, 1500, 30.0, 10.0, 4, 100, "G", ""),
        ("c", 1, 8.0, 1.0, 1.0, 50.0, 500, 3000, 5.0, 30.0, 0, 300, "G", ""),
    ]
    assert [row[0] for row in module._sort_node_detail(rows, "load", "desc")] == ["c", "a", "b"]
    assert [row[0] for row in module._sort_node_detail(rows, "ram_used", "asc")] == ["c", "a", "b"]
    assert [row[0] for row in module._sort_node_detail(rows, "ram_total", "desc")] == ["c", "b", "a"]
    assert [row[0] for row in module._sort_node_detail(rows, "status", "asc")] == ["c", "b", "a"]


def test_group_status_sort_default_has_fixed_severity_and_name_tiebreak(tmp_path):
    module = load_module(NODE_GROUPS, "node_groups_r6_group_sort")
    rows = [
        {"id": 1, "name": "Zulu", "description": "", "node_count": 1, "vm_count": 1, "abuse_count": 0, "last_update": 1, "status": "warning"},
        {"id": 2, "name": "Alpha", "description": "", "node_count": 1, "vm_count": 1, "abuse_count": 0, "last_update": 1, "status": "warning"},
        {"id": 3, "name": "Offline", "description": "", "node_count": 1, "vm_count": 1, "abuse_count": 0, "last_update": 1, "status": "offline"},
        {"id": 4, "name": "Empty", "description": "", "node_count": 0, "vm_count": 0, "abuse_count": 0, "last_update": 0, "status": "empty"},
    ]
    module._node_group_summary_data = lambda: list(rows)
    module._M = SimpleNamespace(request=SimpleNamespace(args={"sort": "status", "order": "asc"}))
    assert [row["name"] for row in module._filtered_sorted_group_summaries()] == [
        "Offline", "Alpha", "Zulu", "Empty"
    ]


def test_retention_and_ordinary_cleanup_exclude_node_group_configuration():
    module = load_module(MAINTENANCE, "maintenance_native_r6")
    protected = {
        "node_groups", "node_group_memberships", "node_group_membership_history"
    }
    assert protected.isdisjoint(module.MONITORING_TABLES)
    assert protected.issubset(module.RESET_APP_TABLES)
    assert {"node_inventory", "vm_inventory"}.isdisjoint(module.MONITORING_TABLES)
    assert {"node_inventory", "vm_inventory"}.issubset(module.RESET_APP_TABLES)
    source = MAINTENANCE.read_text(encoding="utf-8")
    clear_body = source[source.index("def clear_monitoring_data"):source.index("def _recreate_ungrouped")]
    assert "truncate_tables(MONITORING_TABLES" in clear_body
    assert "node_group_memberships" in clear_body  # explicitly reported preserved
    reset_body = source[source.index("def reset_app_data"):source.index("def clear_api_logs")]
    assert "advisory_xact_lock" in reset_body
    assert "TRUNCATE TABLE" in reset_body
    assert "'Ungrouped'" in reset_body
    assert reset_body.index("TRUNCATE TABLE") < reset_body.index("'Ungrouped'") < reset_body.index("conn.commit()")


def test_r6_source_has_no_fixed_credentials_cdn_or_push_override():
    source_files = [
        path for path in ROOT.rglob("*")
        if path.is_file()
        and path.name != "SHA256SUMS"
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    ]
    for path in source_files:
        if path.suffix.lower() in {".py", ".md", ".txt", ".html", ".sh", ""}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert "Green" + "cloud" not in text, path
            assert "Green@" + "1234" not in text, path
    module = NODE_GROUPS.read_text(encoding="utf-8")
    replacements = module[module.index("view_replacements="):module.index("routes=[", module.index("view_replacements="))]
    assert '"push"' not in replacements
    assert "github.com" not in module and "cdnjs" not in module.lower()
    css = (ROOT / "app/static/flags/node-groups.css").read_text(encoding="utf-8")
    assert "url(http" not in css.lower() and "@import" not in css.lower()


def test_r6_migration_does_not_modify_metric_schema_or_existing_memberships():
    sql = R6_SQL.read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION virtinfra_assign_ungrouped_membership" in sql
    assert "ON CONFLICT (node) DO NOTHING" in sql
    assert "WHERE NOT EXISTS" in sql
    for table in ("usage", "node_stats", "vm_perf_stats", "vm_current_fast", "node_current_fast"):
        assert f"ALTER TABLE {table}" not in sql
        assert f"DROP TABLE {table}" not in sql
        assert f"TRUNCATE TABLE {table}" not in sql


def test_purge_node_fk_removes_only_current_membership_and_keeps_empty_group(tmp_path):
    module, runtime = make_sqlite_runtime(tmp_path)
    module.ensure_schema()
    conn = runtime.db()
    try:
        group_id = conn.execute(
            """INSERT INTO node_groups(
                   name,description,country_code,is_active,is_system,created_at,updated_at
               ) VALUES ('Purge Test','','',1,0,1,1)"""
        ).lastrowid
        conn.execute(
            "UPDATE node_group_memberships SET group_id=? WHERE node='node-a'",
            (group_id,),
        )
        conn.commit()
        conn.execute("DELETE FROM node_inventory WHERE node='node-a'")
        conn.commit()
        assert conn.execute(
            "SELECT 1 FROM node_group_memberships WHERE node='node-a'"
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM node_group_memberships WHERE node='node-b'"
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT name FROM node_groups WHERE id=?", (group_id,)
        ).fetchone() == ("Purge Test",)
        assert conn.execute(
            "SELECT COUNT(*) FROM node_group_memberships WHERE group_id=?", (group_id,)
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_sort_parameters_and_nuclear_table_order_are_allowlisted():
    node_groups_source = NODE_GROUPS.read_text(encoding="utf-8")
    assert 'allowed={\'node\',\'vms\',\'load\',\'cpu\',\'ram_used\',\'ram_total\',\'read\',\'write\',\'abuse\',\'updated\',\'status\'}' in node_groups_source
    maintenance = load_module(MAINTENANCE, "maintenance_native_r6_order")
    assert maintenance.NODE_GROUP_CONFIGURATION_TABLES == (
        "node_group_memberships",
        "node_group_membership_history",
        "node_groups",
    )
