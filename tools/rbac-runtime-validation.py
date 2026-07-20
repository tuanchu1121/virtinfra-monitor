#!/usr/bin/env python3
"""Disposable runtime validation for R18 user/RBAC/session hardening."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import types

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_700_000_000
PASSWORD = "Password123!"


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


def main() -> int:
    results: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="virtinfra-r18-rbac-") as temp:
        db_path = Path(temp) / "runtime.sqlite3"
        os.environ.update({
            "BW_MONITOR_DB": str(db_path),
            "BW_ADMIN_USERNAME": "rootadmin",
            "BW_ADMIN_PASSWORD_HASH": "",
            "BW_ADMIN_SECRET_KEY": "r18-rbac-validation-secret",
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
        app_module.set_admin_setting("admin_password_hash", app_module.generate_password_hash(PASSWORD))
        ng.ensure_schema()

        def reset_users(rows):
            conn = app_module.db()
            try:
                conn.execute("DELETE FROM dashboard_users")
                for username, role, active, password in rows:
                    conn.execute(
                        "INSERT INTO dashboard_users(username,password_hash,role,is_active,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                        (username, app_module.generate_password_hash(password), role, active, NOW, NOW),
                    )
                conn.commit()
                return {row[0]: row[1] for row in conn.execute("SELECT username,id FROM dashboard_users")}
            finally:
                conn.close()

        def session_as(client, username: str, role: str, user_id: int, csrf: str = "fixed-csrf") -> None:
            user = app_module.get_dashboard_user_by_id(user_id)
            with client.session_transaction() as sess:
                sess.clear()
                sess.update({
                    "dashboard_authenticated": True,
                    "dashboard_user_id": user_id,
                    "dashboard_username": username,
                    "dashboard_role": role,
                    "dashboard_auth_stamp": ng._user_auth_stamp(user),
                    "csrf_token": csrf,
                })
                if role in {"admin", "super_admin"}:
                    sess["admin_authenticated"] = True
                    sess["admin_username"] = username

        def user_state(username: str):
            row = app_module.get_dashboard_user(username)
            return None if row is None else (str(row[3]), int(row[4]), str(row[2]))

        def mark(name: str, condition: bool) -> None:
            if not condition:
                raise AssertionError(name)
            results[name] = "PASS"

        # Last Super Admin and self-service safety.
        ids = reset_users([("root", "super_admin", 1, PASSWORD), ("op", "admin", 1, PASSWORD)])
        client = app_module.app.test_client()
        session_as(client, "root", "super_admin", ids["root"])
        response = client.post("/admin/users/action", data={
            "csrf_token": "fixed-csrf", "user_id": ids["root"], "action": "change_role", "role": "admin",
        })
        mark("last_super_admin_downgrade_block", response.status_code == 400 and user_state("root")[0] == "super_admin")
        response = client.post("/admin/users/action", data={
            "csrf_token": "fixed-csrf", "user_id": ids["root"], "action": "reset_password", "new_password": "NewPassword123!",
        })
        mark("self_admin_reset_block", response.status_code == 400)

        ids = reset_users([("root", "super_admin", 1, PASSWORD), ("op", "admin", 1, PASSWORD)])
        client = app_module.app.test_client()
        session_as(client, "op", "admin", ids["op"])
        response = client.post("/admin/users/action", data={
            "csrf_token": "fixed-csrf", "user_id": ids["op"], "action": "change_role", "role": "viewer",
        })
        mark("admin_self_downgrade_block", response.status_code == 400 and user_state("op")[0] == "admin")

        # Create is insert-only and cannot overwrite hidden Super Admin accounts.
        ids = reset_users([("root", "super_admin", 1, PASSWORD), ("op", "admin", 1, PASSWORD), ("peer", "admin", 1, PASSWORD)])
        old_root = user_state("root")
        client = app_module.app.test_client()
        session_as(client, "op", "admin", ids["op"])
        response = client.post("/admin/users/create", data={
            "csrf_token": "fixed-csrf", "username": "root", "password": "HijackPassword123!", "role": "admin",
        })
        mark("duplicate_superadmin_create_block", response.status_code == 409 and user_state("root") == old_root)
        old_peer = user_state("peer")
        response = client.post("/admin/users/create", data={
            "csrf_token": "fixed-csrf", "username": "peer", "password": "ChangedPassword123!", "role": "viewer",
        })
        mark("duplicate_user_create_block", response.status_code == 409 and user_state("peer") == old_peer)

        # Invalid and unauthorized role assignment is rejected.
        response = client.post("/admin/users/create", data={
            "csrf_token": "fixed-csrf", "username": "badrole", "password": PASSWORD, "role": "garbage",
        })
        mark("invalid_role_rejected", response.status_code == 400 and user_state("badrole") is None)
        response = client.post("/admin/users/create", data={
            "csrf_token": "fixed-csrf", "username": "new-super", "password": PASSWORD, "role": "super_admin",
        })
        mark("admin_cannot_create_superadmin", response.status_code == 403 and user_state("new-super") is None)

        # Admin cannot target a Super Admin by guessed ID.
        response = client.post("/admin/users/action", data={
            "csrf_token": "fixed-csrf", "user_id": ids["root"], "action": "reset_password", "new_password": "AnotherPassword123!",
        })
        mark("admin_direct_superadmin_manage_block", response.status_code == 404)

        # Super Admin UI and backend can create/promote Super Admin safely.
        client = app_module.app.test_client()
        session_as(client, "root", "super_admin", ids["root"])
        html = client.get("/admin/users").get_data(as_text=True)
        mark("superadmin_role_controls_visible", html.count('value="super_admin"') >= 3)
        response = client.post("/admin/users/action", data={
            "csrf_token": "fixed-csrf", "user_id": ids["peer"], "action": "change_role", "role": "super_admin",
        })
        mark("superadmin_can_promote", response.status_code == 302 and user_state("peer")[0] == "super_admin")

        # Password reset never mutates role, even with a legacy R17 role field.
        response = client.post("/admin/users/action", data={
            "csrf_token": "fixed-csrf", "user_id": ids["op"], "action": "reset_password",
            "new_password": "ResetPassword123!", "role": "viewer",
        })
        mark("password_reset_role_unchanged", response.status_code == 302 and user_state("op")[0] == "admin")

        # Last Super Admin disable/delete guards remain active.
        ids = reset_users([("root", "super_admin", 1, PASSWORD), ("op", "admin", 1, PASSWORD)])
        client = app_module.app.test_client()
        session_as(client, "root", "super_admin", ids["root"])
        disable = client.post("/admin/users/action", data={
            "csrf_token": "fixed-csrf", "user_id": ids["root"], "action": "disable",
        })
        delete = client.post("/admin/users/action", data={
            "csrf_token": "fixed-csrf", "user_id": ids["root"], "action": "delete",
        })
        mark("last_superadmin_disable_delete_block", disable.status_code == 400 and delete.status_code == 400)

        # /admin/setup is initial-install only, never a public emergency takeover.
        ids = reset_users([("op", "admin", 1, PASSWORD)])
        anonymous = app_module.app.test_client()
        setup_get = anonymous.get("/admin/setup")
        setup_post = anonymous.post("/admin/setup", data={
            "username": "attacker", "password": "AttackerPass123!", "confirm": "AttackerPass123!",
        })
        mark("emergency_setup_takeover_block", setup_get.status_code == 403 and setup_post.status_code == 403 and user_state("attacker") is None)

        # Session revocation follows password, role, disable and delete changes.
        ids = reset_users([("root", "super_admin", 1, PASSWORD), ("op", "admin", 1, PASSWORD), ("view", "viewer", 1, PASSWORD)])
        victim = app_module.app.test_client()
        session_as(victim, "op", "admin", ids["op"])
        actor = app_module.app.test_client()
        session_as(actor, "root", "super_admin", ids["root"])
        actor.post("/admin/users/action", data={
            "csrf_token": "fixed-csrf", "user_id": ids["op"], "action": "reset_password", "new_password": "ResetPassword123!",
        })
        mark("password_reset_revokes_session", victim.get("/admin").status_code == 302)

        viewer = app_module.app.test_client()
        session_as(viewer, "view", "viewer", ids["view"])
        app_module.set_dashboard_user_status(ids["view"], 0)
        mark("disable_revokes_dashboard_session", viewer.get("/").status_code == 302)

        ids = reset_users([("root", "super_admin", 1, PASSWORD), ("view", "viewer", 1, PASSWORD)])
        viewer = app_module.app.test_client()
        session_as(viewer, "view", "viewer", ids["view"])
        app_module.delete_dashboard_user(ids["view"])
        mark("delete_revokes_dashboard_session", viewer.get("/").status_code == 302)

        ids = reset_users([("root", "super_admin", 1, PASSWORD), ("view", "viewer", 1, PASSWORD)])
        viewer = app_module.app.test_client()
        session_as(viewer, "view", "viewer", ids["view"])
        conn = app_module.db()
        try:
            conn.execute("UPDATE dashboard_users SET role='admin',updated_at=? WHERE id=?", (NOW + 1, ids["view"]))
            conn.commit()
        finally:
            conn.close()
        mark("role_change_requires_relogin", viewer.get("/").status_code == 302)

        # Admin sees only actions the backend accepts.
        ids = reset_users([("root", "super_admin", 1, PASSWORD), ("op", "admin", 1, PASSWORD)])
        client = app_module.app.test_client()
        session_as(client, "op", "admin", ids["op"])
        maintenance = client.get("/admin?section=maintenance").get_data(as_text=True)
        mark("admin_consumption_cleanup_visible_clear_hidden", 'name="action" value="cleanup"' in maintenance and 'name="action" value="clear"' not in maintenance)
        cleanup = client.post("/admin/bandwidth-consumption", data={
            "csrf_token": "fixed-csrf", "action": "cleanup",
        })
        mark("admin_consumption_cleanup_backend_allowed", cleanup.status_code == 302)
        clear = client.post("/admin/bandwidth-consumption", data={
            "csrf_token": "fixed-csrf", "action": "clear", "confirm_text": "CLEAR BANDWIDTH HISTORY",
        })
        mark("admin_consumption_clear_backend_block", clear.status_code == 403)
        conn = app_module.db()
        try:
            conn.execute(
                """
                INSERT INTO account_logs(
                    time, realm, event, username, role,
                    source_ip, user_agent, path, detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (NOW, "admin", "rbac_audit_sample", "op", "admin", "-", "-", "/admin/logs", "runtime test"),
            )
            conn.commit()
        finally:
            conn.close()
        logs = client.get("/admin/logs").get_data(as_text=True)
        mark("admin_logs_read_only", "/admin/logs/clear" not in logs and "Admin access is read-only for audit logs" in logs)
        table = re.search(r'<table[^>]*>(.*?)</table>', logs, flags=re.I | re.S)
        header_count = len(re.findall(r'<th\b', table.group(1), flags=re.I)) if table else 0
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table.group(1), flags=re.I | re.S) if table else []
        data_rows = [row for row in rows if "rbac_audit_sample" in row]
        mark("admin_logs_table_alignment", bool(data_rows) and len(re.findall(r'<td\b', data_rows[0], flags=re.I)) == header_count)
        mark("admin_system_health_api_read", client.get("/admin/api/system-health").status_code == 200)

        # Viewer and CSRF boundaries.
        ids = reset_users([("root", "super_admin", 1, PASSWORD), ("view", "viewer", 1, PASSWORD)])
        viewer = app_module.app.test_client()
        session_as(viewer, "view", "viewer", ids["view"])
        mark("viewer_operations_forbidden", viewer.get("/admin").status_code == 403)
        super_client = app_module.app.test_client()
        session_as(super_client, "root", "super_admin", ids["root"])
        mark("csrf_required", super_client.post("/admin/users/create", data={
            "username": "csrf-user", "password": PASSWORD, "role": "viewer",
        }).status_code == 403)

        # Real login paths issue stamped sessions; own password change keeps the
        # current browser valid while invalidating every other browser.
        ids = reset_users([("root", "super_admin", 1, PASSWORD), ("op", "admin", 1, PASSWORD), ("view", "viewer", 1, PASSWORD)])
        login_client = app_module.app.test_client()
        login = login_client.post("/login", data={"username": "op", "password": PASSWORD, "next": "/admin"})
        mark("admin_dashboard_login_issues_valid_session", login.status_code == 302 and login_client.get("/admin").status_code == 200)
        viewer_login = app_module.app.test_client()
        viewer_login.post("/login", data={"username": "view", "password": PASSWORD, "next": "/"})
        mark("viewer_login_stays_read_only", viewer_login.get("/").status_code == 200 and viewer_login.get("/admin").status_code == 403)

        own = app_module.app.test_client()
        admin_login = own.post("/admin/login", data={"username": "root", "password": PASSWORD, "next": "/admin"})
        with own.session_transaction() as sess:
            own_csrf = sess["csrf_token"]
        changed = own.post("/admin/password", data={
            "csrf_token": own_csrf,
            "current_password": PASSWORD,
            "new_password": "OwnNewPassword123!",
            "confirm_password": "OwnNewPassword123!",
        })
        mark("own_password_change_refreshes_session", admin_login.status_code == 302 and changed.status_code == 200 and own.get("/admin").status_code == 200)

        # Initial setup remains available only when no dashboard user exists.
        reset_users([])
        app_module.set_admin_setting("admin_password_hash", "")
        fresh = app_module.app.test_client()
        setup_get = fresh.get("/admin/setup")
        setup_post = fresh.post("/admin/setup", data={
            "username": "fresh-root", "password": PASSWORD, "confirm": PASSWORD,
        })
        mark("initial_setup_still_works", setup_get.status_code == 200 and setup_post.status_code == 302 and user_state("fresh-root")[0] == "super_admin" and fresh.get("/admin").status_code == 200)

        # Legacy hard-coded audit calls record the real actor role.
        fresh.get("/admin/logout")
        conn = app_module.db()
        try:
            logout_role = conn.execute(
                "SELECT role FROM account_logs WHERE event='logout' AND username='fresh-root' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        mark("superadmin_audit_role_correct", bool(logout_role) and logout_role[0] == "super_admin")

    print(json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
