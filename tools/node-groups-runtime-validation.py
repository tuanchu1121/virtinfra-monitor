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
from html.parser import HTMLParser
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


class _TableShapeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self._table = None
        self._section = ""
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self._table = {"headers": [], "rows": []}
        elif self._table is not None and tag in {"thead", "tbody"}:
            self._section = tag
        elif self._table is not None and tag == "tr":
            self._row = []
        elif self._row is not None and tag in {"th", "td"}:
            self._cell = {"tag": tag, "colspan": int(attrs.get("colspan") or 1), "text": ""}
            self._row.append(self._cell)

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"] += data

    def handle_endtag(self, tag):
        if tag in {"th", "td"}:
            self._cell = None
        elif tag == "tr" and self._row is not None:
            target = "headers" if self._section == "thead" else "rows"
            self._table[target].append(self._row)
            self._row = None
        elif tag in {"thead", "tbody"}:
            self._section = ""
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


def assert_table_shape(html: str, expected_headers: list[str]) -> None:
    parser = _TableShapeParser()
    parser.feed(html)
    expected = [value.upper() for value in expected_headers]
    for table in parser.tables:
        headers = [
            " ".join(cell["text"].split()).removesuffix(" ↑").removesuffix(" ↓").upper()
            for row in table["headers"] for cell in row
        ]
        if headers == expected:
            expected_width = len(expected)
            for row in table["rows"]:
                width = sum(cell["colspan"] for cell in row)
                assert width == expected_width, (headers, width, row)
            return
    raise AssertionError(("table not found", expected, [
        [" ".join(cell["text"].split()).upper() for row in table["headers"] for cell in row]
        for table in parser.tables
    ]))


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
            for node, address in (("node-vn", "203.0.113.10"), ("node-jp", "203.0.113.20"), ("node-sg", "203.0.113.30")):
                conn.execute(
                    """INSERT INTO node_bridge_addresses_latest(
                           node,role,bridge,last_seen,primary_ipv4,primary_ipv6,
                           ipv4_json,ipv6_json,operstate,carrier,mtu,mac
                       ) VALUES (?, 'public', 'br0', ?, ?, '', ?, '[]', 'up', 1, 1500, '')""",
                    (node, NOW, address, json.dumps([address])),
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

        group_search = client.get("/admin?section=groups&group_q=203.0.113.10").get_data(as_text=True)
        assert "Vietnam DC" in group_search
        assert group_search.count('name="group_q"') == 1

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
            "_v5058c_vm_ctes": lambda *_a, **_k: (
                "WITH vm_rows(node,public_rx,public_tx,private_rx,private_tx) AS "
                "(VALUES ('node-vn',100,200,10,20),('node-jp',300,400,30,40),('node-sg',500,600,50,60)) ",
                [],
            ),
            "_v5058c_node_ctes": lambda *_a, **_k: (
                "WITH node_rows(node,physical_public_rx,physical_public_tx,physical_private_rx,physical_private_tx) AS "
                "(VALUES ('node-vn',1000,2000,100,200),('node-jp',3000,4000,300,400),('node-sg',5000,6000,500,600)) ",
                [],
            ),
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

        group_consumption = client.get("/bandwidth-consumption?tab=group&period=24h&sort=rx&order=desc")
        assert group_consumption.status_code == 200
        group_consumption_html = group_consumption.get_data(as_text=True)
        assert_table_shape(group_consumption_html, [
            "NODE GROUP", "NODES", "VMS", "RX", "TX", "TOTAL", "PHYSICAL", "VM",
        ])
        assert group_consumption_html.index(">Apply</button>") < group_consumption_html.index(">Reset</a>")
        for key in ("group", "nodes", "vms", "rx", "tx", "total", "physical", "vm"):
            assert f"sort={key}" in group_consumption_html

        # Explicit Group=All must render byte-for-byte the same HTML as omitting
        # the group parameter. This catches accidental query/link/layout drift.
        for path in filter_paths:
            joiner = "&" if "?" in path else "?"
            baseline_html = client.get(path).get_data(as_text=True)
            all_html = client.get(path + joiner + "group=all").get_data(as_text=True)
            assert all_html == baseline_html, path

        # Group=All and omitted Group both use the same active-group visibility
        # source. Hidden groups are intentionally excluded by the new contract.
        for path in filter_paths:
            joiner = "&" if "?" in path else "?"
            baseline_html = client.get(path).get_data(as_text=True)
            all_html = client.get(path + joiner + "group=all").get_data(as_text=True)
            assert all_html == baseline_html, path

        # Restricted Admin may manage nodes/groups/users but not dangerous controls or Super Admin accounts.
        session_as(client, "new-admin", "admin", user_ids["new-admin"])
        assert client.get("/admin?section=groups").status_code == 200
        assert client.get("/admin?section=nodes").status_code == 200
        assert client.get("/admin/api-keys").status_code == 403
        assert client.get("/admin/theme").status_code == 200
        assert client.get("/admin/logs?type=account").status_code == 200
        assert client.get("/admin/logs?type=node").status_code == 200
        assert client.get("/admin/system-health").status_code == 200
        assert client.get("/admin?section=maintenance").status_code == 403
        assert client.post("/admin/database-maintenance", data={"csrf_token": "fixed-csrf"}).status_code == 403
        assert client.post("/admin/users/action", data={
            "csrf_token": "fixed-csrf", "user_id": user_ids["legacy-root"], "action": "disable",
        }).status_code == 404
        users_html = client.get("/admin/users")
        assert users_html.status_code == 200
        assert "legacy-root" not in users_html.get_data(as_text=True)
        assert client.post("/admin/users/create", data={
            "csrf_token": "fixed-csrf", "username": "managed-viewer",
            "password": "Password123!", "role": "viewer",
        }).status_code == 302
        assert client.post("/admin/users/create", data={
            "csrf_token": "fixed-csrf", "username": "forbidden-super",
            "password": "Password123!", "role": "super_admin",
        }).status_code == 400

        admin_overview = client.get("/admin?section=overview").get_data(as_text=True)
        assert "User management" in admin_overview
        assert "PostgreSQL data" not in admin_overview
        assert ">Queue<" not in admin_overview

        admin_nodes_html = client.get("/admin?section=nodes").get_data(as_text=True)
        admin_vms_html = client.get("/admin?section=vms").get_data(as_text=True)
        for marker in ("node-select", "vm-select", "selection_scope", "All Matching", "Selected Nodes", "Selected VMs"):
            assert marker not in admin_nodes_html + admin_vms_html, marker
        assert_table_shape(admin_nodes_html, [
            "NODE / STATUS", "NODE GROUP", "PUBLIC IP", "PRIVATE IP", "VM",
            "CPU", "RAM", "DISK I/O", "NETWORK", "LAST PUSH", "ACTION",
        ])
        assert_table_shape(admin_vms_html, [
            "NODE / IP", "NODE GROUP", "VM UUID", "STATUS / SEEN", "BRIDGE / IFACE", "ACTION",
        ])
        assert "node-group-flag" not in admin_vms_html

        conn = app_module.db()
        try:
            before_admin = conn.execute(
                "SELECT password_hash,role FROM dashboard_users WHERE username='new-admin'"
            ).fetchone()
            before_super = conn.execute(
                "SELECT password_hash,role FROM dashboard_users WHERE username='legacy-root'"
            ).fetchone()
        finally:
            conn.close()
        password_response = client.post("/admin/password", data={
            "csrf_token": "fixed-csrf",
            "current_password": "Password123!",
            "new_password": "NewPassword456!",
            "confirm_password": "NewPassword456!",
        })
        assert password_response.status_code == 200
        assert "Your password has been updated." in password_response.get_data(as_text=True)
        conn = app_module.db()
        try:
            after_admin = conn.execute(
                "SELECT password_hash,role FROM dashboard_users WHERE username='new-admin'"
            ).fetchone()
            after_super = conn.execute(
                "SELECT password_hash,role FROM dashboard_users WHERE username='legacy-root'"
            ).fetchone()
        finally:
            conn.close()
        assert before_admin[0] != after_admin[0]
        assert after_admin[1] == "admin"
        assert before_super == after_super
        assert app_module.check_password_hash(after_admin[0], "NewPassword456!")

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
                           cpu_percent,mem_used,mem_total,disk_read_bps,disk_write_bps,total_bytes
                       ) VALUES (?,?,300,?,?,?,?,?,?,?,?,?)""",
                    (node, seen, 12.4 if node == "node-jp" else 3.2, 10.8, 9.7,
                     cpu, used, total, read_bps, write_bps,
                     1800000 if node == "node-jp" else 900000),
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

        # Admin Nodes exposes and sorts current CPU/RAM/Disk/Network from the
        # single node_current_fast join. All four descending sorts place the
        # higher raw value first; formatted text is never used as the key.
        for sort_key in ("cpu", "ram", "disk", "network"):
            sorted_html = client.get(
                f"/admin?section=nodes&sort={sort_key}&order=desc"
            ).get_data(as_text=True)
            assert sorted_html.index("node-jp") < sorted_html.index("node-vn"), sort_key
            assert f"sort={sort_key}" in sorted_html

        # Monitoring page is additive, collapsed by default, lazy-loads node
        # detail, and exposes the current group summary without rendering abuse
        # event details in the group page.
        group_page = client.get("/node-groups")
        assert group_page.status_code == 200
        group_html = group_page.get_data(as_text=True)
        assert '<details class="node-group-monitor"' in group_html
        assert group_html.count('name="q"') == 1
        assert 'name="node_q"' not in group_html
        assert "Vietnam DC" in client.get("/node-groups?q=203.0.113.10").get_data(as_text=True)
        assert "sessionStorage" in group_html and "setInterval(refresh,30000)" in group_html
        assert client.get("/node-groups/summary").status_code == 200
        detail = client.get(f"/node-groups/{vn_id}/nodes?sort=ram_total&order=desc")
        assert detail.status_code == 200
        detail_html = detail.get_data(as_text=True)
        assert "RAM USED" in detail_html
        assert "metric-pill" in detail_html
        assert_table_shape(detail_html, [
            "NODE", "VM COUNT", "LOAD 1 / 5 / 15", "CPU", "RAM USED / TOTAL",
            "DISK READ", "DISK WRITE", "ABUSE VM", "LAST UPDATE", "STATUS",
        ])

        vm_detail = client.get("/vm?node=node-sg&vm_uuid=vm-3&period=5m")
        assert vm_detail.status_code == 200
        vm_detail_html = vm_detail.get_data(as_text=True)
        for bad in (
            "DERX", "DETX", "DETOTAL", "DEAVG Mbps", "DEPEAK Mbps",
            "DEAVG PPS", "DEPEAK PPS", "DESAMPLE", "DECPU Core%",
            "DEvCPU", "DERAM", "DEDISK R/s", "DEDISK W/s", "DEDROPS", "DEERR",
        ):
            assert bad not in vm_detail_html, bad
        assert "node-group-flag" not in vm_detail_html

        # Hidden groups disappear from monitoring and search/detail guards, but
        # remain fully manageable from Admin with a separate Group Hidden state.
        assert client.post("/admin/node-groups/action", data={
            "csrf_token": "fixed-csrf", "group_id": vn_id, "action": "hide",
        }).status_code == 302
        conn = app_module.db()
        try:
            hidden_state = conn.execute("SELECT is_active FROM node_groups WHERE id=?", (vn_id,)).fetchone()
            hidden_members = conn.execute("SELECT node FROM node_group_memberships WHERE group_id=? ORDER BY node", (vn_id,)).fetchall()
        finally:
            conn.close()
        with app_module.app.test_request_context("/"):
            hidden_visible = ng.visible_node_names()
        assert hidden_state == (0,), (hidden_state, hidden_members, hidden_visible)
        assert "node-vn" not in hidden_visible, (hidden_members, hidden_visible)
        assert "node-hidden" not in hidden_visible, (hidden_members, hidden_visible)
        assert "node-jp" in hidden_visible, (hidden_members, hidden_visible)
        assert client.get("/node/node-vn").status_code == 404
        assert client.get("/vm?node=node-vn&vm_uuid=vm-1&period=5m").status_code == 404
        hidden_nodes_html = client.get("/admin?section=nodes&q=node-vn").get_data(as_text=True)
        hidden_vms_html = client.get("/admin?section=vms&q=vm-1").get_data(as_text=True)
        assert "node-vn" in hidden_nodes_html and "GROUP HIDDEN" in hidden_nodes_html.upper()
        assert "vm-1" in hidden_vms_html
        assert client.post("/admin/node-groups/action", data={
            "csrf_token": "fixed-csrf", "group_id": vn_id, "action": "restore",
        }).status_code == 302
        with app_module.app.test_request_context("/"):
            assert app_module.monitoring_node_visible("node-vn") is True

        # Direct row actions hide and restore without bulk selection. Purges are
        # queued by the existing maintenance architecture and report Queued.
        assert client.post("/admin/delete_node", data={
            "csrf_token": "fixed-csrf", "node": "node-sg", "mode": "soft",
        }).status_code == 302
        conn = app_module.db()
        try:
            assert conn.execute("SELECT status FROM node_inventory WHERE node='node-sg'").fetchone() == ("hidden",)
        finally:
            conn.close()
        assert client.get("/node/node-sg").status_code == 404
        assert client.post("/admin/restore_node", data={
            "csrf_token": "fixed-csrf", "node": "node-sg",
        }).status_code == 302

        assert client.post("/admin/delete_vm", data={
            "csrf_token": "fixed-csrf", "node": "node-sg", "vm_uuid": "vm-3", "mode": "soft",
        }).status_code == 302
        conn = app_module.db()
        try:
            assert conn.execute(
                "SELECT status FROM vm_inventory WHERE node='node-sg' AND vm_uuid='vm-3'"
            ).fetchone() == ("hidden",)
        finally:
            conn.close()
        assert client.get("/vm?node=node-sg&vm_uuid=vm-3&period=5m").status_code == 404
        assert client.post("/admin/restore_vm", data={
            "csrf_token": "fixed-csrf", "node": "node-sg", "vm_uuid": "vm-3",
        }).status_code == 302

        queued_calls = []
        original_enqueue = app_module.enqueue_batched_purge_jobs
        app_module.enqueue_batched_purge_jobs = lambda action, items, actor: (
            queued_calls.append((action, items, actor)) or [(321, "test-unit", len(items))]
        )
        try:
            purge_node = client.post("/admin/delete_node", data={
                "csrf_token": "fixed-csrf", "node": "node-sg", "mode": "purge",
            })
            assert purge_node.status_code == 302 and "Queued" in purge_node.location
            purge_vms = client.post("/admin/purge_node_vms", data={
                "csrf_token": "fixed-csrf", "node": "node-sg",
            })
            assert purge_vms.status_code == 302 and "Queued" in purge_vms.location
        finally:
            app_module.enqueue_batched_purge_jobs = original_enqueue
        assert queued_calls[0][0] == "purge_nodes" and queued_calls[0][1] == ["node-sg"]
        assert queued_calls[1][0] == "purge_node_vms" and queued_calls[1][1] == ["node-sg"]

        # Move-all has an explicit source and implicit Ungrouped target. It must
        # never require a target selector or touch nodes outside the source.
        move_all = client.post("/admin/node-groups/bulk", data={
            "csrf_token": "fixed-csrf", "action": "move_all_ungrouped",
            "source_group_id": vn_id,
        })
        assert move_all.status_code == 302
        conn = app_module.db()
        try:
            moved_rows = conn.execute(
                "SELECT node,group_id FROM node_group_memberships WHERE node IN ('node-hidden','node-vn') ORDER BY node"
            ).fetchall()
            assert moved_rows == [("node-hidden", system[0]), ("node-vn", system[0])]
            assert conn.execute(
                "SELECT group_id FROM node_group_memberships WHERE node='node-jp'"
            ).fetchone() == (system[0],)
            assert conn.execute(
                "SELECT group_id FROM node_group_memberships WHERE node='node-sg'"
            ).fetchone() == (system[0],)
            assert conn.execute(
                "SELECT COUNT(*) FROM node_group_membership_history WHERE event='node_group_removed' AND old_group_id=?",
                (vn_id,),
            ).fetchone()[0] >= 2
        finally:
            conn.close()

        # Viewer retains read-only monitoring and group filters, with no Admin access.
        session_as(client, "viewer", "viewer", user_ids["viewer"])
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
            "vm_inheritance": "PASS",
            "audit_events": "PASS",
            "page_filters": "PASS",
            "group_all_html_equivalence": "PASS",
            "group_all_delegation": "PASS",
            "admin_permission_boundary": "PASS",
            "super_admin_stealth": "PASS",
            "viewer_read_only": "PASS",
            "push_view_untouched": "PASS",
            "node_groups_monitoring": "PASS",
            "rbac_admin_tools": "PASS",
            "self_password_scope": "PASS",
            "admin_tables_direct_actions": "PASS",
            "admin_nodes_current_metric_sort": "PASS",
            "hidden_group_visibility": "PASS",
            "node_vm_visibility_actions": "PASS",
            "move_all_ungrouped": "PASS",
            "node_group_search_ip": "PASS",
            "consumption_group_alignment": "PASS",
            "vm_detail_label_cleanup": "PASS",
            "auto_refresh_30s": "PASS",
            "route_contract": "PASS",
            "route_count": len(route_rows),
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
