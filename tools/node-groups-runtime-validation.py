#!/usr/bin/env python3
"""End-to-end Node Groups validation with a disposable SQLite DB-API shim.

Production remains PostgreSQL-only. The shim exercises Flask routes, role
migration, CRUD, inheritance and UI wiring without touching any live service.
PostgreSQL-specific migration syntax is validated separately by tests/CI.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
import sqlite3
import sys
import tempfile
import types

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_700_000_000


def install_sqlite_shim(db_path: Path) -> None:
    module = types.ModuleType("bw_pg")
    module.Error = sqlite3.Error
    module.IntegrityError = sqlite3.IntegrityError
    module.OperationalError = sqlite3.OperationalError
    module.Binary = sqlite3.Binary

    def connect(path=None, timeout=30, **_kwargs):
        conn = sqlite3.connect(str(db_path), timeout=timeout)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.create_function("hashtextextended", 2, lambda value, seed: abs(hash((value, seed))) % (2**31))
        conn.create_function("pg_advisory_lock", 1, lambda _value: 1)
        conn.create_function("pg_advisory_unlock", 1, lambda _value: 1)
        conn.create_function("pg_try_advisory_lock", 1, lambda _value: 1)
        conn.create_function("pg_try_advisory_xact_lock", 1, lambda _value: 1)
        return conn

    module.connect = connect
    module.database_stats = lambda *_a, **_k: {
        "database_size_bytes": 0,
        "wal_size_bytes": 0,
        "shm_size_bytes": 0,
    }
    module.healthcheck = lambda *_a, **_k: True
    sys.modules["bw_pg"] = module


def session_as(client, username: str, role: str, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess.clear()
        sess.update({
            "admin_authenticated": role in {"admin", "super_admin"},
            "admin_username": username if role in {"admin", "super_admin"} else "",
            "dashboard_authenticated": True,
            "dashboard_username": username,
            "dashboard_role": role,
            "dashboard_user_id": user_id,
            "csrf_token": "fixed-csrf",
        })


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="virtinfra-node-groups-") as temp:
        db_path = Path(temp) / "runtime.sqlite3"
        os.environ.update({
            "BW_MONITOR_DB": str(db_path),
            "BW_ADMIN_USERNAME": "rootadmin",
            "BW_ADMIN_PASSWORD_HASH": "",
            "BW_ADMIN_SECRET_KEY": "node-groups-validation-secret",
            "BW_MONITOR_TOKEN": "validation-token",
            "BW_START_BACKGROUND_THREADS": "0",
        })
        install_sqlite_shim(db_path)
        sys.path.insert(0, str(ROOT / "app"))
        import app as app_module
        import node_groups as ng

        app_module.app.logger.disabled = True
        app_module.now_ts = lambda: NOW
        app_module.set_admin_setting("admin_username", "rootadmin")
        app_module.set_admin_setting("admin_password_hash", app_module.generate_password_hash("Password123!"))

        conn = app_module.db()
        try:
            # Re-run the one-time namespace migration against a real legacy role.
            conn.execute("DELETE FROM admin_settings WHERE key=?", (ng.ROLE_MIGRATION_KEY,))
            conn.execute("DELETE FROM dashboard_users")
            conn.execute(
                "INSERT INTO dashboard_users(username,password_hash,role,is_active,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                ("legacy-root", app_module.generate_password_hash("Password123!"), "admin", 1, NOW, NOW),
            )
            for node in ("node-vn", "node-jp", "node-sg"):
                conn.execute(
                    "INSERT INTO node_inventory(node,first_seen,last_push,status,hidden_at,deleted_at) VALUES (?,?,?,'active',NULL,NULL)",
                    (node, NOW, NOW),
                )
            for node, vm_uuid in (("node-vn", "vm-1"), ("node-jp", "vm-2"), ("node-sg", "vm-3")):
                conn.execute(
                    "INSERT INTO vm_inventory(node,vm_uuid,first_seen,last_seen,last_iface,last_bridge,status,hidden_at,deleted_at) "
                    "VALUES (?,?,?,?,?,'br0','active',NULL,NULL)",
                    (node, vm_uuid, NOW, NOW, "vnet-" + vm_uuid[-1]),
                )
            conn.commit()
        finally:
            conn.close()

        ng.ensure_schema()
        ng.ensure_schema()
        conn = app_module.db()
        try:
            assert conn.execute("SELECT role FROM dashboard_users WHERE username='legacy-root'").fetchone()[0] == "super_admin"
            assert conn.execute("SELECT value FROM admin_settings WHERE key=?", (ng.ROLE_MIGRATION_KEY,)).fetchone()[0] == "completed"
            conn.execute(
                "INSERT INTO dashboard_users(username,password_hash,role,is_active,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                ("new-admin", app_module.generate_password_hash("Password123!"), "admin", 1, NOW, NOW),
            )
            conn.execute(
                "INSERT INTO dashboard_users(username,password_hash,role,is_active,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                ("viewer", app_module.generate_password_hash("Password123!"), "viewer", 1, NOW, NOW),
            )
            conn.commit()
        finally:
            conn.close()
        ng.ensure_schema()
        conn = app_module.db()
        try:
            assert conn.execute("SELECT role FROM dashboard_users WHERE username='new-admin'").fetchone()[0] == "admin"
            system = conn.execute("SELECT id,name,is_active,is_system FROM node_groups WHERE is_system=1").fetchone()
            assert system[1:] == ("Ungrouped", 1, 1)
            assert conn.execute("SELECT COUNT(*) FROM node_group_memberships").fetchone()[0] == 3
            user_ids = {row[0]: row[1] for row in conn.execute("SELECT username,id FROM dashboard_users").fetchall()}
        finally:
            conn.close()

        client = app_module.app.test_client()
        session_as(client, "legacy-root", "admin", user_ids["legacy-root"])
        # Stale pre-migration session role must resolve the DB role and retain full access.
        response = client.get("/admin/api-keys")
        assert response.status_code == 200, response.status_code

        # A node first seen after migration is assigned to Ungrouped by the
        # post-commit push hook, without creating any VM-to-group relation.
        conn = app_module.db()
        try:
            conn.execute(
                "INSERT INTO node_inventory(node,first_seen,last_push,status,hidden_at,deleted_at) "
                "VALUES ('node-new',?,?, 'active',NULL,NULL)",
                (NOW, NOW),
            )
            conn.commit()
        finally:
            conn.close()
        original_push = ng._BASE["push_view"]
        try:
            ng._BASE["push_view"] = lambda: app_module.jsonify(ok=True)
            with app_module.app.test_request_context("/push", method="POST", json={"node": "node-new"}):
                push_response = app_module.app.make_response(ng.push())
                assert push_response.status_code == 200
        finally:
            ng._BASE["push_view"] = original_push
        conn = app_module.db()
        try:
            new_membership = conn.execute(
                "SELECT ng.name FROM node_group_memberships gm JOIN node_groups ng ON ng.id=gm.group_id WHERE gm.node='node-new'"
            ).fetchone()
            assert new_membership == ("Ungrouped",)
        finally:
            conn.close()

        # CRUD and immutable Ungrouped safety.
        response = client.post("/admin/node-groups/create", data={
            "csrf_token": "fixed-csrf", "name": "Vietnam", "description": "VN region", "country_code": "vn",
        })
        assert response.status_code == 302
        conn = app_module.db()
        try:
            vn_id = conn.execute("SELECT id FROM node_groups WHERE name='Vietnam'").fetchone()[0]
        finally:
            conn.close()
        assert client.post("/admin/node-groups/update", data={
            "csrf_token": "fixed-csrf", "group_id": vn_id, "name": "Vietnam DC", "description": "VN", "country_code": "vn",
        }).status_code == 302
        assert client.post("/admin/node-groups/action", data={
            "csrf_token": "fixed-csrf", "group_id": vn_id, "action": "hide",
        }).status_code == 302
        assert client.post("/admin/node-groups/action", data={
            "csrf_token": "fixed-csrf", "group_id": vn_id, "action": "restore",
        }).status_code == 302
        assert client.post("/admin/node-groups/action", data={
            "csrf_token": "fixed-csrf", "group_id": system[0], "action": "delete",
        }).status_code == 400
        assert client.post("/admin/node-groups/update", data={
            "csrf_token": "fixed-csrf", "group_id": system[0], "name": "Other", "description": "", "country_code": "",
        }).status_code == 400

        # Bulk assignment and inherited VM group.
        response = client.post("/admin/bulk_nodes", data={
            "csrf_token": "fixed-csrf", "action": "assign_group", "group_id": vn_id,
            "nodes": ["node-vn", "node-jp"],
        })
        assert response.status_code == 302
        conn = app_module.db()
        try:
            assigned = conn.execute("SELECT node,group_id FROM node_group_memberships WHERE node IN ('node-vn','node-jp') ORDER BY node").fetchall()
            assert assigned == [("node-jp", vn_id), ("node-vn", vn_id)]
            history_events = {row[0] for row in conn.execute("SELECT event FROM node_group_membership_history").fetchall()}
            assert {"node_group_created", "node_group_updated", "node_group_hidden", "node_group_restored", "node_group_assigned"}.issubset(history_events)
        finally:
            conn.close()
        assert client.post("/admin/node-groups/action", data={
            "csrf_token": "fixed-csrf", "group_id": vn_id, "action": "delete",
        }).status_code == 409

        nodes_html = client.get(f"/admin?section=nodes&group={vn_id}").get_data(as_text=True)
        assert "node-vn" in nodes_html and "node-jp" in nodes_html and "node-sg" not in nodes_html
        vms_html = client.get(f"/admin?section=vms&group={vn_id}").get_data(as_text=True)
        assert "vm-1" in vms_html and "vm-2" in vms_html and "vm-3" not in vms_html
        assert "Vietnam DC" in vms_html

        # VM group follows its node location, with no VM-to-group relationship.
        conn = app_module.db()
        try:
            conn.execute("DELETE FROM vm_inventory WHERE node='node-vn' AND vm_uuid='vm-1'")
            conn.execute(
                "INSERT INTO vm_inventory(node,vm_uuid,first_seen,last_seen,last_iface,last_bridge,status,hidden_at,deleted_at) "
                "VALUES ('node-sg','vm-1',?,?,?,'br0','active',NULL,NULL)",
                (NOW, NOW, "vnet-migrated"),
            )
            conn.commit()
        finally:
            conn.close()
        vms_html = client.get(f"/admin?section=vms&group={vn_id}").get_data(as_text=True)
        assert "vm-1" not in vms_html
        ungrouped_html = client.get(f"/admin?section=vms&group={system[0]}").get_data(as_text=True)
        assert "vm-1" in ungrouped_html

        # Exercise the remaining audit events and successful delete path.
        assert client.post("/admin/node-groups/create", data={
            "csrf_token": "fixed-csrf", "name": "Japan", "description": "JP", "country_code": "jp",
        }).status_code == 302
        conn = app_module.db()
        try:
            jp_id = conn.execute("SELECT id FROM node_groups WHERE name='Japan'").fetchone()[0]
        finally:
            conn.close()
        assert client.post("/admin/node-groups/assign", data={
            "csrf_token": "fixed-csrf", "group_id": jp_id, "nodes": ["node-jp"],
        }).status_code == 302
        assert client.post("/admin/node-groups/assign", data={
            "csrf_token": "fixed-csrf", "group_id": system[0], "nodes": ["node-jp"],
        }).status_code == 302
        assert client.post("/admin/node-groups/action", data={
            "csrf_token": "fixed-csrf", "group_id": jp_id, "action": "delete",
        }).status_code == 302
        conn = app_module.db()
        try:
            history_events = {row[0] for row in conn.execute("SELECT event FROM node_group_membership_history").fetchall()}
            assert {
                "node_group_created", "node_group_updated", "node_group_hidden",
                "node_group_restored", "node_group_deleted", "node_group_assigned",
                "node_group_moved", "node_group_removed",
            }.issubset(history_events)
            assert conn.execute("SELECT 1 FROM node_groups WHERE id=?", (jp_id,)).fetchone() is None
        finally:
            conn.close()

        # All requested pages expose exactly one filter; no filter is added to Abuse Settings.
        # Consumption data providers are stubbed only to bypass PostgreSQL-only casts in this disposable shim.
        stubs = {
            "_v5058c_visible_nodes": lambda: [],
            "_v5058c_vm_rows": lambda *_a, **_k: ([], 0, 1, 1),
            "_v5058c_node_rows": lambda *_a, **_k: ([], 0, 1, 1),
            "_v5058c_vm_totals": lambda *_a, **_k: {"vm_public_rx": 0, "vm_public_tx": 0, "vm_private_rx": 0, "vm_private_tx": 0},
            "_v5058c_node_totals": lambda *_a, **_k: {"physical_public_rx": 0, "physical_public_tx": 0, "physical_private_rx": 0, "physical_private_tx": 0},
        }
        for name, value in stubs.items():
            setattr(app_module, name, value)
        ng._BASE.update({
            "consumption_visible_nodes": stubs["_v5058c_visible_nodes"],
            "consumption_vm_rows": stubs["_v5058c_vm_rows"],
            "consumption_node_rows": stubs["_v5058c_node_rows"],
            "consumption_vm_totals": stubs["_v5058c_vm_totals"],
            "consumption_node_totals": stubs["_v5058c_node_totals"],
        })
        filter_paths = [
            "/", "/top", "/health/nodes", "/storage", "/bandwidth-consumption", "/abuse/vms",
            "/admin?section=nodes", "/admin?section=vms",
        ]
        for path in filter_paths:
            response = client.get(path)
            assert response.status_code == 200, (path, response.status_code)
            assert response.get_data(as_text=True).count('name="group"') == 1, path
        assert 'name="group"' not in client.get("/admin/abuse").get_data(as_text=True)

        # Explicit Group=All must render byte-for-byte the same HTML as omitting
        # the group parameter. This catches accidental query/link/layout drift.
        for path in filter_paths:
            joiner = "&" if "?" in path else "?"
            baseline_html = client.get(path).get_data(as_text=True)
            all_html = client.get(path + joiner + "group=all").get_data(as_text=True)
            assert all_html == baseline_html, path

        # Group=All delegates to untouched baseline data functions. Restore the
        # originals immediately so later page-render checks still exercise the
        # real baseline implementation and tuple shapes.
        original_delegates = {
            name: ng._BASE[name]
            for name in ("get_node_rows", "get_node_health_rows", "get_top_vm_rows")
        }
        try:
            sentinel_nodes = ([('node-vn',)], 100, 200)
            ng._BASE["get_node_rows"] = lambda *_a, **_k: sentinel_nodes
            with app_module.app.test_request_context("/?group=all"):
                assert ng.get_node_rows("5m") is sentinel_nodes
            sentinel_health = [('node-vn',)]
            ng._BASE["get_node_health_rows"] = lambda *_a, **_k: sentinel_health
            with app_module.app.test_request_context("/health/nodes"):
                assert ng.get_node_health_rows() is sentinel_health
            sentinel_top = ([('node-vn', 'vm-1')], 100, 100, 100)
            ng._BASE["get_top_vm_rows"] = lambda *_a, **_k: sentinel_top
            with app_module.app.test_request_context("/top?group=all"):
                assert ng.get_top_vm_rows("5m") is sentinel_top
        finally:
            ng._BASE.update(original_delegates)

        # Restricted Admin may manage nodes/groups/users but not dangerous controls or Super Admin accounts.
        session_as(client, "new-admin", "admin", user_ids["new-admin"])
        assert client.get("/admin?section=groups").status_code == 200
        assert client.get("/admin?section=nodes").status_code == 200
        assert client.get("/admin/api-keys").status_code == 403
        assert client.get("/admin/theme").status_code == 403
        assert client.get("/admin?section=maintenance").status_code == 403
        assert client.post("/admin/database-maintenance", data={"csrf_token": "fixed-csrf"}).status_code == 403
        assert client.post("/admin/users/action", data={
            "csrf_token": "fixed-csrf", "user_id": user_ids["legacy-root"], "action": "disable",
        }).status_code == 403
        assert client.post("/admin/users/create", data={
            "csrf_token": "fixed-csrf", "username": "managed-viewer",
            "password": "Password123!", "role": "viewer",
        }).status_code == 302
        assert client.post("/admin/users/create", data={
            "csrf_token": "fixed-csrf", "username": "managed-admin",
            "password": "Password123!", "role": "admin",
        }).status_code == 302
        assert client.post("/admin/users/create", data={
            "csrf_token": "fixed-csrf", "username": "forbidden-super",
            "password": "Password123!", "role": "super_admin",
        }).status_code == 403
        conn = app_module.db()
        try:
            managed_roles = dict(conn.execute(
                "SELECT username,role FROM dashboard_users WHERE username IN ('managed-viewer','managed-admin')"
            ).fetchall())
            assert managed_roles == {"managed-viewer": "viewer", "managed-admin": "admin"}
        finally:
            conn.close()

        # Viewer retains read-only monitoring and group filters, with no Admin access.
        session_as(client, "viewer", "viewer", user_ids["viewer"])
        assert client.get("/top").status_code == 200
        assert client.get("/admin?section=groups").status_code == 302

        # Route map: preserve every baseline rule, including duplicate Flask
        # registrations, and allow exactly four additive Node Group endpoints.
        route_rows = sorted([
            {
                "rule": str(rule),
                "endpoint": rule.endpoint,
                "methods": sorted(method for method in rule.methods if method not in {"HEAD", "OPTIONS"}),
            }
            for rule in app_module.app.url_map.iter_rules()
        ], key=lambda item: (item["rule"], item["endpoint"], item["methods"]))
        baseline_rows = json.loads((ROOT / "audit/node-groups/BASELINE_ROUTES.json").read_text(encoding="utf-8"))
        key = lambda item: (item["rule"], item["endpoint"], tuple(item["methods"]))
        current_counter = Counter(key(item) for item in route_rows)
        baseline_counter = Counter(key(item) for item in baseline_rows)
        missing = baseline_counter - current_counter
        additions = current_counter - baseline_counter
        assert not missing, sorted(missing.elements())
        expected_additions = Counter({
            ("/admin/node-groups/action", "admin_node_groups_action", ("POST",)): 1,
            ("/admin/node-groups/assign", "admin_node_groups_assign", ("POST",)): 1,
            ("/admin/node-groups/create", "admin_node_groups_create", ("POST",)): 1,
            ("/admin/node-groups/update", "admin_node_groups_update", ("POST",)): 1,
        })
        assert additions == expected_additions, sorted(additions.elements())
        route_output = os.environ.get("NODE_GROUPS_ROUTE_OUTPUT", "").strip()
        if route_output:
            Path(route_output).write_text(json.dumps(route_rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({
            "role_migration_idempotent": "PASS",
            "super_admin_preserved": "PASS",
            "node_group_crud": "PASS",
            "ungrouped_protection": "PASS",
            "occupied_group_delete_block": "PASS",
            "new_node_ungrouped": "PASS",
            "bulk_assign": "PASS",
            "vm_inheritance": "PASS",
            "audit_events": "PASS",
            "page_filters": "PASS",
            "group_all_html_equivalence": "PASS",
            "group_all_delegation": "PASS",
            "admin_permission_boundary": "PASS",
            "admin_user_management": "PASS",
            "viewer_read_only": "PASS",
            "route_contract": "PASS",
            "route_count": len(route_rows),
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
