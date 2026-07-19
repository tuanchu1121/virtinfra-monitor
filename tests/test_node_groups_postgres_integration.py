#!/usr/bin/env python3
"""Live PostgreSQL migration test for additive Node Groups schema.

BW_TEST_DATABASE_URL must point to a disposable database. This module drops and
recreates the public schema and must never target production.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DSN = os.environ.get("BW_TEST_DATABASE_URL", "").strip()
if not DSN:
    pytest.skip("BW_TEST_DATABASE_URL is not set", allow_module_level=True)

import psycopg


def migration_sql(name: str) -> str:
    return "\n".join(
        line for line in (ROOT / "postgres/sql" / name).read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("\\")
    )


def reset_minimal_schema(conn) -> None:
    conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
    conn.execute("CREATE SCHEMA public")
    conn.execute("GRANT ALL ON SCHEMA public TO PUBLIC")
    conn.execute("""
        CREATE TABLE admin_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at BIGINT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE dashboard_users (
            id BIGSERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            is_active SMALLINT NOT NULL DEFAULT 1,
            created_at BIGINT NOT NULL,
            updated_at BIGINT NOT NULL,
            last_login BIGINT
        )
    """)
    conn.execute("""
        CREATE TABLE node_inventory (
            node TEXT PRIMARY KEY,
            first_seen BIGINT,
            last_push BIGINT,
            status TEXT,
            hidden_at BIGINT,
            deleted_at BIGINT
        )
    """)


def test_node_groups_postgresql_migration_is_idempotent_and_safe():
    schema_sql = migration_sql("011_node_groups.sql")
    safety_sql = migration_sql("012_node_groups_r6_safety.sql")
    with psycopg.connect(DSN, autocommit=True) as conn:
        reset_minimal_schema(conn)
        conn.execute("""
            INSERT INTO dashboard_users(username,password_hash,role,is_active,created_at,updated_at)
            VALUES ('legacy-admin','x','admin',1,1,1)
        """)
        conn.execute("INSERT INTO node_inventory(node,status) VALUES ('node-a','active'),('node-b','active')")

        conn.execute(schema_sql, prepare=False)
        conn.execute(safety_sql, prepare=False)
        conn.execute(schema_sql, prepare=False)
        conn.execute(safety_sql, prepare=False)

        assert conn.execute(
            "SELECT role FROM dashboard_users WHERE username='legacy-admin'"
        ).fetchone()[0] == "super_admin"
        assert conn.execute(
            "SELECT value FROM admin_settings WHERE key='node_groups_role_migration_v1'"
        ).fetchone()[0] == "completed"
        system = conn.execute(
            "SELECT id,name,is_active,is_system FROM node_groups WHERE is_system=1"
        ).fetchone()
        assert system[1:] == ("Ungrouped", 1, 1)
        assert conn.execute("SELECT COUNT(*) FROM node_group_memberships").fetchone()[0] == 2
        original_membership = conn.execute(
            "SELECT group_id FROM node_group_memberships WHERE node='node-a'"
        ).fetchone()[0]
        conn.execute("INSERT INTO node_inventory(node,status) VALUES ('node-new','active')")
        assert conn.execute(
            "SELECT ng.name FROM node_group_memberships gm JOIN node_groups ng ON ng.id=gm.group_id WHERE gm.node='node-new'"
        ).fetchone() == ("Ungrouped",)
        conn.execute(safety_sql, prepare=False)
        assert conn.execute(
            "SELECT group_id FROM node_group_memberships WHERE node='node-a'"
        ).fetchone()[0] == original_membership
        assert conn.execute(
            "SELECT COUNT(*) FROM node_group_memberships WHERE node='node-a'"
        ).fetchone()[0] == 1

        # A future restricted Admin remains Admin after an idempotent rerun.
        conn.execute("""
            INSERT INTO dashboard_users(username,password_hash,role,is_active,created_at,updated_at)
            VALUES ('future-admin','x','admin',1,2,2)
        """)
        conn.execute(schema_sql, prepare=False)
        conn.execute(safety_sql, prepare=False)
        assert conn.execute(
            "SELECT role FROM dashboard_users WHERE username='future-admin'"
        ).fetchone()[0] == "admin"

        # Node deletion cascades membership cleanup.
        conn.execute("DELETE FROM node_inventory WHERE node='node-b'")
        assert conn.execute(
            "SELECT COUNT(*) FROM node_group_memberships WHERE node='node-b'"
        ).fetchone()[0] == 0

        # Group deletion cannot cascade into nodes or memberships.
        group_id = conn.execute("""
            INSERT INTO node_groups(name,description,country_code,is_active,is_system,created_at,updated_at)
            VALUES ('Occupied','','vn',1,0,3,3) RETURNING id
        """).fetchone()[0]
        conn.execute("UPDATE node_group_memberships SET group_id=%s WHERE node='node-a'", (group_id,))
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute("DELETE FROM node_groups WHERE id=%s", (group_id,))
        assert conn.execute("SELECT 1 FROM node_groups WHERE id=%s", (group_id,)).fetchone() == (1,)
