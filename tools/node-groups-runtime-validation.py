#!/usr/bin/env python3
"""End-to-end Node Groups validation with a disposable SQLite DB-API shim.

Production remains PostgreSQL-only. The shim exercises Flask routes, role
migration, CRUD, inheritance and UI wiring without touching any live service.
PostgreSQL-specific migration syntax is validated separately by tests/CI.
"""
from __future__ import annotations

import json
import os
import re
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
    import app as app_module
    import node_groups as ng
    user = app_module.get_dashboard_user_by_id(user_id)
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
            "dashboard_auth_stamp": ng._user_auth_stamp(user),
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
        assert client.get("/admin?section=maintenance").status_code == 200
        assert client.post("/admin/database-maintenance", data={
            "csrf_token": "fixed-csrf", "action": "status",
        }).status_code in {200, 302}

        # A node first seen after migration is assigned to Ungrouped by the
        # database trigger. The hot ingestion endpoint remains the untouched
        # baseline view and carries no Node Group side effect.
        conn = app_module.db()
        try:
            conn.execute(
                "INSERT INTO node_inventory(node,first_seen,last_push,status,hidden_at,deleted_at) "
                "VALUES ('node-new',?,?, 'active',NULL,NULL)",
                (NOW, NOW),
            )
            conn.commit()
            new_membership = conn.execute(
                "SELECT ng.name FROM node_group_memberships gm JOIN node_groups ng ON ng.id=gm.group_id WHERE gm.node='node-new'"
            ).fetchone()
            assert new_membership == ("Ungrouped",)
        finally:
            conn.close()
        assert "push" not in {
            endpoint for endpoint, view in {
                key: value for key, value in app_module.app.view_functions.items()
            }.items() if view is getattr(ng, "push", None)
        }

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
        occupied = client.post("/admin/node-groups/action", data={
            "csrf_token": "fixed-csrf", "group_id": vn_id, "action": "delete",
        })
        assert occupied.status_code == 409
        assert occupied.get_data(as_text=True) == (
            "Cannot delete this group because it still contains nodes.\n"
            "Move or remove all nodes from the group first.\n"
        )

        # The new backend performs selected bulk remove/move transactionally.
        assert client.post("/admin/node-groups/bulk", data={
            "csrf_token": "fixed-csrf", "action": "remove_group",
            "selection_scope": "selected", "nodes": ["node-vn"],
        }).status_code == 302
        conn = app_module.db()
        try:
            assert conn.execute(
                "SELECT group_id FROM node_group_memberships WHERE node='node-vn'"
            ).fetchone() == (system[0],)
        finally:
            conn.close()
        assert client.post("/admin/node-groups/bulk", data={
            "csrf_token": "fixed-csrf", "action": "move_group",
            "selection_scope": "selected", "group_id": vn_id,
            "nodes": ["node-vn"],
        }).status_code == 302

        nodes_html = client.get(f"/admin?section=nodes&group={vn_id}").get_data(as_text=True)
        assert "node-vn" in nodes_html and "node-jp" in nodes_html and "node-sg" not in nodes_html
        vms_html = client.get(f"/admin?section=vms&group={vn_id}").get_data(as_text=True)
        assert "vm-1" in vms_html and "vm-2" in vms_html and "vm-3" not in vms_html
        assert "Vietnam DC" in vms_html

        def assert_table_alignment(document: str, class_name: str) -> None:
            table = re.search(
                rf'<table[^>]*class="[^"]*{re.escape(class_name)}[^"]*"[^>]*>(.*?)</table>',
                document, flags=re.I | re.S,
            )
            assert table, class_name
            fragment = table.group(1)
            header_count = len(re.findall(r'<th\b', fragment, flags=re.I))
            body = re.search(r'<tbody[^>]*>(.*?)</tbody>', fragment, flags=re.I | re.S)
            assert body and header_count > 0, class_name
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', body.group(1), flags=re.I | re.S)
            data_rows = [row for row in rows if '<td' in row.lower() and 'class="empty"' not in row.lower()]
            assert data_rows, class_name
            assert all(len(re.findall(r'<td\b', row, flags=re.I)) == header_count for row in data_rows), (
                class_name, header_count, [len(re.findall(r'<td\b', row, flags=re.I)) for row in data_rows]
            )

        assert_table_alignment(nodes_html, 'node-groups-admin-nodes')
        assert_table_alignment(vms_html, 'node-groups-admin-vms')
        assert 'selection_scope' in nodes_html and 'All matching nodes' in nodes_html
        assert 'sort=public_ip' not in nodes_html and 'sort=uuid' not in vms_html

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
        assert client.post("/admin/node-groups/bulk", data={
            "csrf_token": "fixed-csrf", "action": "move_all_ungrouped",
            "source_group_id": jp_id,
        }).status_code == 302
        conn = app_module.db()
        try:
            assert conn.execute("SELECT group_id FROM node_group_memberships WHERE node='node-jp'").fetchone() == (system[0],)
        finally:
            conn.close()
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

        # Group=All still delegates metric calculation to the untouched baseline,
        # then applies the active-group visibility predicate to the returned rows.
        original_delegates = {
            name: ng._BASE[name]
            for name in ("get_node_rows", "get_node_health_rows", "get_top_vm_rows")
        }
        original_effective = ng.effective_visible_nodes
        try:
            ng.effective_visible_nodes = lambda *_a, **_k: {"node-vn"}
            ng._BASE["get_node_rows"] = lambda *_a, **_k: ([("node-vn",), ("node-hidden",)], 100, 200)
            with app_module.app.test_request_context("/?group=all"):
                assert ng.get_node_rows("5m") == ([("node-vn",)], 100, 200)
            ng._BASE["get_node_health_rows"] = lambda *_a, **_k: [("node-vn",), ("node-hidden",)]
            with app_module.app.test_request_context("/health/nodes"):
                assert ng.get_node_health_rows() == [("node-vn",)]
            ng._BASE["get_top_vm_rows"] = lambda *_a, **_k: ([("node-vn", "vm-1"), ("node-hidden", "vm-x")], 100, 100, 100)
            with app_module.app.test_request_context("/top?group=all"):
                assert ng.get_top_vm_rows("5m") == ([("node-vn", "vm-1")], 100, 100, 100)
        finally:
            ng.effective_visible_nodes = original_effective
            ng._BASE.update(original_delegates)

        # Admin is the day-to-day operator. Operations, Queue, routine
        # retention/VACUUM and permanent Node/VM purge are available, while
        # destructive whole-system/API resets remain Super Admin only.
        session_as(client, "new-admin", "admin", user_ids["new-admin"])
        assert client.get("/admin?section=groups").status_code == 200
        assert client.get("/admin?section=nodes").status_code == 200
        assert client.get("/admin/api-keys").status_code == 403
        assert client.get("/admin/theme").status_code == 200
        assert client.get("/admin/logs?type=account").status_code == 200
        assert client.get("/admin/logs?type=node").status_code == 200
        assert client.get("/admin/system-health").status_code == 200
        assert client.get("/admin?section=maintenance").status_code == 200
        admin_dashboard = client.get("/").get_data(as_text=True)
        assert '>Operations</a>' in admin_dashboard
        admin_overview = client.get("/admin").get_data(as_text=True)
        assert 'Operations' in admin_overview and 'section=maintenance' in admin_overview
        admin_nodes_html = client.get("/admin?section=nodes").get_data(as_text=True)
        admin_vms_html = client.get("/admin?section=vms").get_data(as_text=True)
        assert "Purge node" in admin_nodes_html and "Purge all VMs" in admin_nodes_html
        assert "Purge VM" in admin_vms_html
        maintenance_html = client.get("/admin?section=maintenance").get_data(as_text=True)
        for routine_label in ("Run retention now", "Run online VACUUM", "Delete history"):
            assert routine_label in maintenance_html
        for destructive_label in ("Clear monitoring data", "Clear API logs", "Clear all API data"):
            assert destructive_label not in maintenance_html
        users_page = client.get("/admin/users")
        assert users_page.status_code == 200
        users_html = users_page.get_data(as_text=True)
        assert "legacy-root" not in users_html
        assert '<h2>Operations</h2>' in users_html and 'class="admin-tabs"' in users_html
        for shell_path in ("/admin/logs?type=account", "/admin/system-health", "/admin/theme", "/admin/password"):
            shell_response = client.get(shell_path)
            assert shell_response.status_code == 200, shell_path
            shell_html = shell_response.get_data(as_text=True)
            assert '<h2>Operations</h2>' in shell_html and 'class="admin-tabs"' in shell_html, shell_path
        original_admin_enqueue = app_module.enqueue_maintenance_job
        admin_jobs = []
        app_module.enqueue_maintenance_job = lambda action, parameters, actor: (admin_jobs.append((action, dict(parameters), actor)) or (601 + len(admin_jobs), "bw-monitor-maintenance@601.service"))
        try:
            for action_data in (
                {"action": "retention"},
                {"action": "delete_history", "confirm_text": "DELETE HISTORY", "days": "2"},
                {"action": "vacuum", "confirm_text": "VACUUM"},
            ):
                assert client.post("/admin/database-maintenance", data={
                    "csrf_token": "fixed-csrf", **action_data,
                }).status_code == 302
        finally:
            app_module.enqueue_maintenance_job = original_admin_enqueue
        assert [item[0] for item in admin_jobs] == ["retention", "delete_history", "vacuum"]
        for action_data in (
            {"action": "clear_monitoring_data", "confirm_text": "CLEAR ALL MONITORING DATA"},
            {"action": "clear_api_logs", "confirm_text": "CLEAR API LOGS"},
            {"action": "clear_api_data", "confirm_text": "CLEAR ALL API DATA"},
            {"action": "reset_app_data_preview", "admin_password": "Password123!"},
        ):
            assert client.post("/admin/database-maintenance", data={
                "csrf_token": "fixed-csrf", **action_data,
            }).status_code == 403
        original_cancel = app_module.maintenance_queue.cancel_queued_job
        original_wake = app_module.maintenance_queue.wake_dispatcher
        app_module.maintenance_queue.cancel_queued_job = lambda job_id, actor: False
        app_module.maintenance_queue.wake_dispatcher = lambda: (True, "")
        try:
            cancel_response = client.post("/admin/maintenance/cancel", data={
                "csrf_token": "fixed-csrf", "job_id": "99999",
            })
        finally:
            app_module.maintenance_queue.cancel_queued_job = original_cancel
            app_module.maintenance_queue.wake_dispatcher = original_wake
        assert cancel_response.status_code == 302, (
            cancel_response.status_code, cancel_response.get_data(as_text=True)
        )
        # Reversible inventory actions remain available to regular Admin.
        assert client.post("/admin/delete_node", data={
            "csrf_token": "fixed-csrf", "node": "node-vn", "mode": "soft",
        }).status_code == 302
        assert client.post("/admin/restore_node", data={
            "csrf_token": "fixed-csrf", "node": "node-vn",
        }).status_code == 302
        assert client.post("/admin/users/action", data={
            "csrf_token": "fixed-csrf", "user_id": user_ids["legacy-root"], "action": "disable",
        }).status_code == 404
        assert client.post("/admin/users/create", data={
            "csrf_token": "fixed-csrf", "username": "managed-viewer",
            "password": "Password123!", "role": "viewer",
        }).status_code == 302
        conn = app_module.db()
        try:
            super_before = conn.execute("SELECT password_hash FROM dashboard_users WHERE username='legacy-root'").fetchone()[0]
        finally:
            conn.close()
        changed = client.post("/admin/password", data={
            "csrf_token": "fixed-csrf", "current_password": "Password123!",
            "new_password": "AdminPassword456!", "confirm_password": "AdminPassword456!",
        })
        assert changed.status_code == 200
        conn = app_module.db()
        try:
            own_hash = conn.execute("SELECT password_hash FROM dashboard_users WHERE username='new-admin'").fetchone()[0]
            super_after = conn.execute("SELECT password_hash FROM dashboard_users WHERE username='legacy-root'").fetchone()[0]
        finally:
            conn.close()
        assert app_module.check_password_hash(own_hash, "AdminPassword456!")
        assert super_after == super_before
        # Super Admin nuclear reset is a two-step flow. The route must
        # verify the current Super Admin password, return to Maintenance and
        # enqueue only after the safety preview is confirmed.
        session_as(client, "legacy-root", "super_admin", user_ids["legacy-root"])
        assert client.get("/admin?section=maintenance").status_code == 200
        original_enqueue = app_module.enqueue_maintenance_job
        queued = []
        app_module.enqueue_maintenance_job = lambda action, parameters, actor: (queued.append((action, dict(parameters), actor)) or (77 + len(queued), "bw-monitor-maintenance@77.service"))
        try:
            assert client.post("/admin/database-maintenance", data={
                "csrf_token": "fixed-csrf", "action": "retention",
            }).status_code == 302
            for days in (2, 7):
                assert client.post("/admin/database-maintenance", data={
                    "csrf_token": "fixed-csrf", "action": "delete_history",
                    "confirm_text": "DELETE HISTORY", "days": str(days),
                }).status_code == 302
        finally:
            app_module.enqueue_maintenance_job = original_enqueue
        assert [(item[0], item[1].get("days")) for item in queued] == [
            ("retention", None), ("delete_history", 2), ("delete_history", 7),
        ]
        original_preview = app_module.maintenance_native.preview_reset_app_data
        original_pending = app_module._v5057_queue_has_pending_jobs
        original_nuclear_enqueue = app_module.maintenance_queue.enqueue_job
        nuclear_jobs = []
        app_module.maintenance_native.preview_reset_app_data = lambda: {
            "table_count": 12, "estimated_rows": 345, "estimated_bytes": 6789, "database_bytes": 9999,
        }
        app_module._v5057_queue_has_pending_jobs = lambda: None
        app_module.maintenance_queue.enqueue_job = lambda action, parameters, actor, exclusive=False: (
            nuclear_jobs.append((action, dict(parameters), actor, exclusive)) or (88, "bw-monitor-maintenance@88.service")
        )
        try:
            preview_response = client.post("/admin/database-maintenance", data={
                "csrf_token": "fixed-csrf", "action": "reset_app_data_preview",
                "admin_password": "Password123!",
            })
            assert preview_response.status_code == 302
            assert "section=maintenance" in preview_response.headers.get("Location", "")
            with client.session_transaction() as sess:
                preview_data = dict(sess["v5057_nuclear_preview"])
                preview_data["not_before"] = NOW
                sess["v5057_nuclear_preview"] = preview_data
            final_response = client.post("/admin/database-maintenance", data={
                "csrf_token": "fixed-csrf", "action": "reset_app_data",
                "preview_nonce": preview_data["nonce"], "admin_password": "Password123!",
                "confirm_text": "RESET VIRTINFRA " + preview_data["code"],
            })
            assert final_response.status_code == 302
            assert "section=maintenance" in final_response.headers.get("Location", "")
        finally:
            app_module.maintenance_native.preview_reset_app_data = original_preview
            app_module._v5057_queue_has_pending_jobs = original_pending
            app_module.maintenance_queue.enqueue_job = original_nuclear_enqueue
        assert nuclear_jobs and nuclear_jobs[0][0] == "reset_app_data" and nuclear_jobs[0][3] is True

        # Populate only the existing current caches. Summary/detail must not
        # scan metric history, must exclude hidden inventory, and must count a
        # Current Abuse VM once even when it has multiple flags.
        cfg = app_module.get_abuse_settings()
        conn = app_module.db()
        try:
            for node, seen, cpu, used, total, read_bps, write_bps in (
                ("node-vn", NOW - 20, 31.5, 800, 1000, 1200.0, 2300.0),
                ("node-jp", NOW - 10, 52.5, 900, 1100, 3400.0, 4500.0),
            ):
                conn.execute(
                    """INSERT OR REPLACE INTO node_current_fast(
                           node,last_seen,interval_seconds,load1,load5,load15,
                           cpu_percent,mem_used,mem_total,disk_read_bps,disk_write_bps
                       ) VALUES (?,?,300,?,?,?,?,?,?,?,?)""",
                    (node, seen, 12.4 if node == "node-jp" else 3.2, 10.8, 9.7,
                     cpu, used, total, read_bps, write_bps),
                )
            conn.execute(
                """INSERT OR REPLACE INTO vm_abuse_state(
                       node,vm_uuid,last_seen,is_abuse,abuse_flags,severity,
                       policy_revision,policy_applied_at,last_eval_bucket,engine_version
                   ) VALUES ('node-jp','vm-2',?,1,'CPU,DISK,CRITICAL',9,?,?,?,?)""",
                (NOW - 5, cfg["revision"], NOW, NOW, app_module.ABUSE_ENGINE_VERSION),
            )
            conn.execute(
                "INSERT INTO node_inventory(node,first_seen,last_push,status,hidden_at,deleted_at) VALUES ('node-hidden',?,?, 'hidden',?,NULL)",
                (NOW, NOW, NOW),
            )
            conn.execute(
                "INSERT INTO vm_inventory(node,vm_uuid,first_seen,last_seen,last_iface,last_bridge,status,hidden_at,deleted_at) VALUES ('node-hidden','vm-hidden',?,?,?,'br0','active',NULL,NULL)",
                (NOW, NOW, 'vnet-hidden'),
            )
            conn.commit()
        finally:
            conn.close()
        with app_module.app.test_request_context("/admin/node-groups/bulk"):
            app_module.session["dashboard_username"] = "legacy-root"
            app_module.session["dashboard_role"] = "super_admin"
            ng.assign_nodes(["node-hidden"], vn_id, "runtime-test")
        with app_module.app.test_request_context("/node-groups"):
            summaries = {row["id"]: row for row in ng._node_group_summary_data()}
        assert summaries[vn_id]["node_count"] == 1  # hidden node excluded
        assert summaries[vn_id]["vm_count"] == 0
        assert summaries[vn_id]["last_update"] == NOW - 20
        assert summaries[system[0]]["vm_count"] == 3
        assert summaries[system[0]]["abuse_count"] == 1
        assert summaries[system[0]]["status"] == "critical"

        # Monitoring page is additive, collapsed by default, lazy-loads node
        # detail, and exposes the current group summary without rendering abuse
        # event details in the group page.
        group_page = client.get("/node-groups")
        assert group_page.status_code == 200
        group_html = group_page.get_data(as_text=True)
        assert '<details class="node-group-monitor"' in group_html
        assert "sessionStorage" in group_html and "setInterval(refresh,30000)" in group_html
        assert group_html.count('name="q"') == 1 and 'name="node_q"' in group_html
        assert client.get("/node-groups/summary").status_code == 200
        detail = client.get(f"/node-groups/{vn_id}/nodes?sort=ram_total&order=desc")
        assert detail.status_code == 200
        detail_html = detail.get_data(as_text=True)
        assert "RAM USED" in detail_html and "ram-value" not in detail_html and "ram-warning" not in detail_html

        original_vm_ctes = app_module._v5058c_vm_ctes
        original_node_ctes = app_module._v5058c_node_ctes
        app_module._v5058c_vm_ctes = lambda *_a, **_k: (
            "WITH vm_rows(node,public_rx,public_tx,private_rx,private_tx) AS "
            "(SELECT '',0,0,0,0 WHERE 0) ", []
        )
        app_module._v5058c_node_ctes = lambda *_a, **_k: (
            "WITH node_rows(node,physical_public_rx,physical_public_tx,physical_private_rx,physical_private_tx) AS "
            "(SELECT '',0,0,0,0 WHERE 0) ", []
        )
        try:
            group_consumption = client.get('/bandwidth-consumption?tab=group&sort=physical_public&order=desc')
        finally:
            app_module._v5058c_vm_ctes = original_vm_ctes
            app_module._v5058c_node_ctes = original_node_ctes
        assert group_consumption.status_code == 200, (group_consumption.status_code, group_consumption.get_data(as_text=True)[:2000])
        group_consumption_html = group_consumption.get_data(as_text=True)
        assert 'v5058c-node-table' in group_consumption_html
        assert group_consumption_html.count('<th>') >= 7
        assert 'sort=physical_public' not in group_consumption_html
        session_as(client, "legacy-root", "super_admin", user_ids["legacy-root"])
        assert client.post("/admin/node-groups/action", data={
            "csrf_token": "fixed-csrf", "group_id": vn_id, "action": "hide",
        }).status_code == 302
        with app_module.app.test_request_context("/"):
            assert "node-vn" not in ng.effective_visible_nodes()
        assert client.get("/node/node-vn").status_code == 404
        hidden_admin = client.get("/admin?section=nodes&group=%s" % vn_id).get_data(as_text=True)
        assert "hidden by group" in hidden_admin
        assert client.post("/admin/node-groups/action", data={
            "csrf_token": "fixed-csrf", "group_id": vn_id, "action": "restore",
        }).status_code == 302

        # Node flags belong only to exact Node links. VM detail/UUID links and
        # sortable metric links must never inherit the Node Group flag.
        original_flag_lookup = ng._groups_for_node_links
        ng._groups_for_node_links = lambda nodes: {node: ("Vietnam DC", "vn") for node in nodes}
        try:
            with app_module.app.test_request_context('/'):
                decorated = ng._inject_node_flags(
                    '<a href="/node/node-vn"><b>node-vn</b></a>'
                    '<a href="/node/node-vn?period=5m">5m</a>'
                    '<a href="/node/node-vn?net=both">Both Cards</a>'
                    '<a href="/node/node-vn?net=public">Public Only</a>'
                    '<a href="/node/node-vn?sort=rx">RX</a>'
                    '<a href="/node/node-vn?sort=cpu">CPU Core%</a>'
                    '<a href="/node/node-vn">vm-uuid-should-not-be-flagged</a>'
                    '<a href="/node/node-vn/vm/vm-flag">vm-flag</a>'
                    '<a href="/vm?node=node-vn&amp;vm_uuid=vm-flag">vm-search</a>'
                    '<a href="/node/node-vn">← Back to node</a>'
                )
        finally:
            ng._groups_for_node_links = original_flag_lookup
        assert decorated.count("node-group-flag") == 1
        assert 'node-group-flag' in decorated.split('</a>', 1)[0]
        assert '<a href="/node/node-vn/vm/vm-flag">vm-flag</a>' in decorated
        assert '<a href="/node/node-vn?sort=rx">RX</a>' in decorated

        # Purge jobs hide their target immediately so monitoring/search cannot
        # keep presenting an item while the FIFO worker is still queued.
        conn = app_module.db()
        try:
            conn.execute(
                "INSERT INTO node_inventory(node,first_seen,last_push,status,hidden_at,deleted_at) "
                "VALUES ('node-purge',?,?, 'active',NULL,NULL)",
                (NOW, NOW),
            )
            conn.execute(
                "INSERT INTO vm_inventory(node,vm_uuid,first_seen,last_seen,last_iface,last_bridge,status,hidden_at,deleted_at) "
                "VALUES ('node-purge','vm-purge',?,?,?,'br0','active',NULL,NULL)",
                (NOW, NOW, 'vnet-purge'),
            )
            conn.commit()
        finally:
            conn.close()
        with app_module.app.test_request_context('/'):
            assert ng._monitoring_node_visible('node-purge')
            assert ng._monitoring_vm_visible('node-purge', 'vm-purge')
        original_purge_enqueue = app_module.enqueue_batched_purge_jobs
        purge_jobs = []
        def fake_purge_enqueue(action, items, actor):
            clean_items = list(items)
            purge_jobs.append((action, clean_items, actor))
            job_id = 901 + len(purge_jobs)
            parameters = {"vms": clean_items} if action == "purge_vms" else {"nodes": clean_items}
            conn = app_module.db()
            try:
                conn.execute(
                    """INSERT INTO maintenance_jobs(
                           id,created_at,action,parameters,status,requested_by,message,unit_name
                       ) VALUES (?,?,?,?,?,?,?,?)""",
                    (job_id, NOW, action, json.dumps(parameters), "queued", actor,
                     "Waiting in FIFO queue", f"bw-monitor-maintenance@{job_id}.service"),
                )
                conn.commit()
            finally:
                conn.close()
            return [(job_id, f"bw-monitor-maintenance@{job_id}.service", len(clean_items))]

        app_module.enqueue_batched_purge_jobs = fake_purge_enqueue
        session_as(client, "new-admin", "admin", user_ids["new-admin"])
        try:
            response = client.post('/admin/delete_vm', data={
                'csrf_token': 'fixed-csrf', 'node': 'node-purge',
                'vm_uuid': 'vm-purge', 'mode': 'purge',
            })
            assert response.status_code == 302
            assert 'section=maintenance' in response.headers.get('Location', '') and '#maintenance-queue' in response.headers.get('Location', '')
            conn = app_module.db()
            try:
                assert conn.execute(
                    "SELECT status FROM vm_inventory WHERE node='node-purge' AND vm_uuid='vm-purge'"
                ).fetchone() == ('hidden',)
            finally:
                conn.close()
            with app_module.app.test_request_context('/'):
                assert not ng._monitoring_vm_visible('node-purge', 'vm-purge')
            conn = app_module.db()
            try:
                conn.execute(
                    "UPDATE vm_inventory SET status='active',hidden_at=NULL WHERE node='node-purge' AND vm_uuid='vm-purge'"
                )
                conn.commit()
            finally:
                conn.close()
            with app_module.app.test_request_context('/'):
                assert ng._monitoring_vm_visible('node-purge', 'vm-purge')

            response = client.post('/admin/purge_node_vms', data={
                'csrf_token': 'fixed-csrf', 'node': 'node-purge',
            })
            assert response.status_code == 302
            assert 'section=maintenance' in response.headers.get('Location', '') and '#maintenance-queue' in response.headers.get('Location', '')
            conn = app_module.db()
            try:
                assert conn.execute(
                    "SELECT status FROM vm_inventory WHERE node='node-purge' AND vm_uuid='vm-purge'"
                ).fetchone() == ('hidden',)
                assert conn.execute(
                    "SELECT status FROM node_inventory WHERE node='node-purge'"
                ).fetchone() == ('active',)
                conn.execute(
                    "UPDATE vm_inventory SET status='active',hidden_at=NULL WHERE node='node-purge' AND vm_uuid='vm-purge'"
                )
                conn.commit()
            finally:
                conn.close()

            response = client.post('/admin/delete_node', data={
                'csrf_token': 'fixed-csrf', 'node': 'node-purge', 'mode': 'purge',
            })
            assert response.status_code == 302
            assert 'section=maintenance' in response.headers.get('Location', '') and '#maintenance-queue' in response.headers.get('Location', '')
            conn = app_module.db()
            try:
                assert conn.execute(
                    "SELECT status FROM node_inventory WHERE node='node-purge'"
                ).fetchone() == ('hidden',)
            finally:
                conn.close()
        finally:
            app_module.enqueue_batched_purge_jobs = original_purge_enqueue
        assert [job[0] for job in purge_jobs] == ['purge_vms', 'purge_node_vms', 'purge_nodes']
        queue_page = client.get('/admin?section=maintenance')
        assert queue_page.status_code == 200
        queue_html = queue_page.get_data(as_text=True)
        for job_id in (902, 903, 904):
            assert f'#{job_id}' in queue_html
        assert 'Purge VM' in queue_html and 'Purge all VMs on node' in queue_html and 'Purge node' in queue_html

        html_output = os.environ.get('NODE_GROUPS_HTML_OUTPUT', '').strip()
        if html_output:
            output_dir = Path(html_output)
            output_dir.mkdir(parents=True, exist_ok=True)
            pages = {
                'admin-overview': '/admin',
                'admin-nodes': '/admin?section=nodes',
                'admin-vms': '/admin?section=vms',
                'admin-maintenance': '/admin?section=maintenance',
                'node-groups': '/node-groups',
            }
            for name, path in pages.items():
                response = client.get(path)
                assert response.status_code == 200, (name, response.status_code)
                (output_dir / f'{name}.html').write_text(response.get_data(as_text=True), encoding='utf-8')
            original_vm_ctes = app_module._v5058c_vm_ctes
            original_node_ctes = app_module._v5058c_node_ctes
            app_module._v5058c_vm_ctes = lambda *_a, **_k: (
                "WITH vm_rows(node,public_rx,public_tx,private_rx,private_tx) AS "
                "(SELECT '',0,0,0,0 WHERE 0) ", []
            )
            app_module._v5058c_node_ctes = lambda *_a, **_k: (
                "WITH node_rows(node,physical_public_rx,physical_public_tx,physical_private_rx,physical_private_tx) AS "
                "(SELECT '',0,0,0,0 WHERE 0) ", []
            )
            try:
                response = client.get('/bandwidth-consumption?tab=group')
            finally:
                app_module._v5058c_vm_ctes = original_vm_ctes
                app_module._v5058c_node_ctes = original_node_ctes
            assert response.status_code == 200
            (output_dir / 'consumption-group.html').write_text(response.get_data(as_text=True), encoding='utf-8')

        # Viewer retains read-only monitoring and group filters, with no Admin access.
        session_as(client, "viewer", "viewer", user_ids["viewer"])
        viewer_dashboard = client.get("/").get_data(as_text=True)
        assert '>Operations</a>' not in viewer_dashboard
        assert client.get("/top").status_code == 200
        assert client.get("/node-groups").status_code == 200
        assert client.get("/admin?section=groups").status_code == 403
        assert client.post("/admin/node-groups/create", data={
            "csrf_token": "fixed-csrf", "name": "Denied",
        }).status_code == 403
        assert client.post("/admin/database-maintenance", data={
            "csrf_token": "fixed-csrf",
        }).status_code == 403

        # Route map: preserve every baseline rule, including duplicate Flask
        # registrations, and allow the eight additive Node Group endpoints.
        route_rows = sorted([
            {
                "rule": str(rule),
                "endpoint": rule.endpoint,
                "methods": sorted(method for method in rule.methods if method not in {"HEAD", "OPTIONS"}),
            }
            for rule in app_module.app.url_map.iter_rules()
        ], key=lambda item: (item["rule"], item["endpoint"], item["methods"]))
        baseline_rows = json.loads((ROOT / "tests/contracts/node_groups_baseline_routes.json").read_text(encoding="utf-8"))
        key = lambda item: (item["rule"], item["endpoint"], tuple(item["methods"]))
        current_counter = Counter(key(item) for item in route_rows)
        baseline_counter = Counter(key(item) for item in baseline_rows)
        missing = baseline_counter - current_counter
        additions = current_counter - baseline_counter
        assert not missing, sorted(missing.elements())
        expected_additions = Counter({
            ("/admin/node-groups/action", "admin_node_groups_action", ("POST",)): 1,
            ("/admin/node-groups/assign", "admin_node_groups_assign", ("POST",)): 1,
            ("/admin/node-groups/bulk", "admin_node_groups_bulk", ("POST",)): 1,
            ("/admin/node-groups/create", "admin_node_groups_create", ("POST",)): 1,
            ("/admin/node-groups/update", "admin_node_groups_update", ("POST",)): 1,
            ("/node-groups", "node_groups_page", ("GET",)): 1,
            ("/node-groups/summary", "node_groups_summary", ("GET",)): 1,
            ("/node-groups/<int:group_id>/nodes", "node_group_nodes", ("GET",)): 1,
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
            "move_all_ungrouped": "PASS",
            "vm_inheritance": "PASS",
            "audit_events": "PASS",
            "page_filters": "PASS",
            "group_all_html_equivalence": "PASS",
            "group_all_effective_visibility": "PASS",
            "admin_permission_boundary": "PASS",
            "maintenance_2d_7d_queue": "PASS",
            "super_admin_stealth": "PASS",
            "own_password_only": "PASS",
            "nuclear_super_admin_flow": "PASS",
            "hidden_group_effective_visibility": "PASS",
            "node_flag_exact_link_only": "PASS",
            "purge_immediate_visibility": "PASS",
            "viewer_read_only": "PASS",
            "push_view_untouched": "PASS",
            "node_groups_monitoring": "PASS",
            "admin_inventory_alignment_sort": "PASS",
            "consumption_group_alignment_sort": "PASS",
            "route_contract": "PASS",
            "route_count": len(route_rows),
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
