#!/usr/bin/env python3
"""Render deterministic HTML snapshots without a live PostgreSQL service.

This is a UI regression harness only. It injects a SQLite-compatible DB-API
shim, seeds the same tiny inventory, freezes application time, and stores the
requested page responses for baseline/current structural comparison.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3
import sys
import types

PAGES = {
    "admin-overview": "/admin?section=overview",
    "admin-nodes": "/admin?section=nodes",
    "admin-vms": "/admin?section=vms",
    "admin-maintenance": "/admin?section=maintenance",
    "dashboard": "/",
    "top-vm": "/top",
    "node-health": "/health/nodes",
    "storage-io": "/storage",
    "consumption": "/bandwidth-consumption",
    "vm-abuse": "/abuse/vms",
}
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    db_path = output / "snapshot.sqlite3"
    db_path.unlink(missing_ok=True)

    os.environ.update({
        "BW_MONITOR_DB": str(db_path),
        "BW_ADMIN_USERNAME": "admin",
        "BW_ADMIN_PASSWORD_HASH": "",
        "BW_ADMIN_SECRET_KEY": "node-groups-ui-regression-fixed-secret",
        "BW_MONITOR_TOKEN": "snapshot-token",
        "BW_START_BACKGROUND_THREADS": "0",
    })
    install_sqlite_shim(db_path)
    sys.path.insert(0, str(source / "app"))
    import app as app_module

    app_module.app.logger.disabled = True
    app_module.now_ts = lambda: NOW
    try:
        import node_groups as node_groups_module
    except ImportError:
        node_groups_module = None

    conn = app_module.db()
    try:
        role = "super_admin" if node_groups_module else "admin"
        conn.execute(
            "INSERT OR REPLACE INTO dashboard_users(id,username,password_hash,role,is_active,created_at,updated_at) "
            "VALUES (1,'admin',?,?,1,?,?)",
            (app_module.generate_password_hash("Password123!"), role, NOW, NOW),
        )
        for node in ("node-vn", "node-jp"):
            conn.execute(
                "INSERT OR REPLACE INTO node_inventory(node,status,last_push,deleted_at,first_seen) "
                "VALUES (?,'active',?,NULL,?)",
                (node, NOW, NOW),
            )
        for node, vm_uuid, iface in (("node-vn", "vm-1", "vnet1"), ("node-jp", "vm-2", "vnet2")):
            conn.execute(
                "INSERT OR REPLACE INTO vm_inventory(node,vm_uuid,status,last_seen,deleted_at,last_bridge,last_iface,first_seen) "
                "VALUES (?,?,'active',?,NULL,'br0',?,?)",
                (node, vm_uuid, NOW, iface, NOW),
            )
        conn.commit()
    finally:
        conn.close()

    app_module.set_admin_setting("admin_username", "admin")
    app_module.set_admin_setting("admin_password_hash", app_module.generate_password_hash("Password123!"))
    if node_groups_module:
        node_groups_module.ensure_schema()

    # Consumption uses PostgreSQL-only CTE casts. UI snapshots replace data
    # providers only; the production renderer, controls, table and CSS remain.
    stubs = {
        "_v5058c_visible_nodes": lambda: [],
        "_v5058c_vm_rows": lambda *_a, **_k: ([], 0, 1, 1),
        "_v5058c_node_rows": lambda *_a, **_k: ([], 0, 1, 1),
        "_v5058c_vm_totals": lambda *_a, **_k: {
            "vm_public_rx": 0, "vm_public_tx": 0,
            "vm_private_rx": 0, "vm_private_tx": 0,
        },
        "_v5058c_node_totals": lambda *_a, **_k: {
            "physical_public_rx": 0, "physical_public_tx": 0,
            "physical_private_rx": 0, "physical_private_tx": 0,
        },
    }
    for name, value in stubs.items():
        setattr(app_module, name, value)
    if node_groups_module:
        node_groups_module._BASE.update({
            "consumption_visible_nodes": stubs["_v5058c_visible_nodes"],
            "consumption_vm_rows": stubs["_v5058c_vm_rows"],
            "consumption_node_rows": stubs["_v5058c_node_rows"],
            "consumption_vm_totals": stubs["_v5058c_vm_totals"],
            "consumption_node_totals": stubs["_v5058c_node_totals"],
        })

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess.update({
            "admin_authenticated": True,
            "admin_username": "admin",
            "dashboard_authenticated": True,
            "dashboard_username": "admin",
            "dashboard_role": "super_admin" if node_groups_module else "admin",
            "dashboard_user_id": 1,
            "csrf_token": "fixed-csrf-token",
        })
    pages = dict(PAGES)
    if node_groups_module:
        pages["admin-node-groups"] = "/admin?section=groups"
        if "node_groups_page" in app_module.app.view_functions:
            pages["node-groups"] = "/node-groups"
    for name, path in pages.items():
        response = client.get(path)
        if response.status_code != 200:
            raise SystemExit(f"{path}: HTTP {response.status_code}")
        (output / f"{name}.html").write_text(response.get_data(as_text=True), encoding="utf-8")
    db_path.unlink(missing_ok=True)
    print(f"saved {len(pages)} HTML snapshots to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
