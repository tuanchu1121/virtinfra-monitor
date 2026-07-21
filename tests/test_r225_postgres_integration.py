from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

DSN = os.environ.get("BW_TEST_DATABASE_URL", "").strip()
DESTRUCTIVE = os.environ.get("BW_R225_DESTRUCTIVE_TEST", "") == "1"
if not DSN:
    pytest.skip("BW_TEST_DATABASE_URL is not set", allow_module_level=True)
if not DESTRUCTIVE:
    pytest.skip("BW_R225_DESTRUCTIVE_TEST=1 is required", allow_module_level=True)

import psycopg

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def _exec_script(conn, text: str) -> None:
    sql = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("\\"))
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def _setup_database(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        name = str(cur.fetchone()[0]).lower()
        if not any(marker in name for marker in ("test", "ci", "r225", "tmp")):
            raise RuntimeError(f"Refusing destructive R22.5 test on database {name!r}")
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
        cur.execute("CREATE SCHEMA public")
        cur.execute("DROP SCHEMA IF EXISTS bw_meta CASCADE")
        cur.execute("CREATE SCHEMA bw_meta")
        cur.execute("""
            CREATE TABLE bw_meta.schema_migrations(
                version TEXT PRIMARY KEY,
                description TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE public.dashboard_users(
                id BIGSERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                is_active SMALLINT NOT NULL,
                created_at BIGINT NOT NULL,
                updated_at BIGINT NOT NULL,
                last_login BIGINT
            );
            CREATE TABLE public.maintenance_jobs(
                id BIGSERIAL PRIMARY KEY,
                created_at BIGINT NOT NULL,
                started_at BIGINT,
                finished_at BIGINT,
                action TEXT NOT NULL,
                parameters TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'queued',
                requested_by TEXT,
                message TEXT,
                unit_name TEXT,
                heartbeat_at BIGINT,
                progress INTEGER NOT NULL DEFAULT 0,
                attempt INTEGER NOT NULL DEFAULT 0,
                cancel_requested BOOLEAN NOT NULL DEFAULT FALSE
            );
            CREATE TABLE public.maintenance_nuclear_audit(
                id BIGSERIAL PRIMARY KEY,
                job_id BIGINT,
                requested_by TEXT NOT NULL,
                created_at BIGINT NOT NULL,
                backup_path TEXT NOT NULL,
                backup_sha256 TEXT NOT NULL,
                release_version TEXT NOT NULL,
                result_json TEXT NOT NULL
            );
            CREATE TABLE public.admin_settings(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at BIGINT NOT NULL
            );
            CREATE TABLE public.api_keys(
                id BIGSERIAL PRIMARY KEY,
                key_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                secret_hash TEXT NOT NULL,
                scopes_json TEXT NOT NULL DEFAULT '[]',
                allowed_ips_json TEXT NOT NULL DEFAULT '[]',
                is_active SMALLINT NOT NULL DEFAULT 1,
                created_at BIGINT NOT NULL,
                created_by TEXT NOT NULL DEFAULT '',
                expires_at BIGINT,
                last_used_at BIGINT,
                last_used_ip TEXT NOT NULL DEFAULT '',
                use_count BIGINT NOT NULL DEFAULT 0,
                revoked_at BIGINT,
                revoked_by TEXT NOT NULL DEFAULT '',
                rotated_from_key_id TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE public.node_groups(
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                country_code VARCHAR(2) NOT NULL DEFAULT '',
                is_active SMALLINT NOT NULL DEFAULT 1,
                is_system SMALLINT NOT NULL DEFAULT 0,
                created_at BIGINT NOT NULL,
                updated_at BIGINT NOT NULL,
                hidden_at BIGINT
            );
            CREATE UNIQUE INDEX uq_node_groups_name_ci ON public.node_groups((LOWER(name)));
            CREATE TABLE public.node_inventory(
                node TEXT PRIMARY KEY,
                public_ip TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE public.node_group_memberships(
                node TEXT PRIMARY KEY REFERENCES public.node_inventory(node) ON DELETE CASCADE,
                group_id BIGINT NOT NULL REFERENCES public.node_groups(id) ON DELETE RESTRICT,
                assigned_at BIGINT NOT NULL,
                assigned_by TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE public.node_group_membership_history(
                id BIGSERIAL PRIMARY KEY,
                event TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT '',
                node TEXT,
                old_group_id BIGINT,
                old_group_name TEXT NOT NULL DEFAULT '',
                new_group_id BIGINT,
                new_group_name TEXT NOT NULL DEFAULT '',
                created_at BIGINT NOT NULL
            );
            CREATE TABLE public.metric_history(
                id BIGSERIAL PRIMARY KEY,
                sample_time BIGINT NOT NULL,
                value BIGINT NOT NULL
            );
        """)
    conn.commit()
    _exec_script(conn, (ROOT / "postgres/sql/016_configuration_backup_nuclear.sql").read_text(encoding="utf-8"))


def test_configuration_restore_and_true_nuclear_on_disposable_postgres(tmp_path, monkeypatch):
    monkeypatch.setenv("BW_DATABASE_URL", DSN)
    monkeypatch.setenv("BW_CONFIGURATION_BACKUP_ROOT", str(tmp_path / "config"))
    sys.path.insert(0, str(APP))
    import maintenance_native
    import configuration_backup
    importlib.reload(maintenance_native)
    importlib.reload(configuration_backup)

    with psycopg.connect(DSN) as conn:
        _setup_database(conn)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO public.dashboard_users(username,password_hash,role,is_active,created_at,updated_at)
                VALUES ('root','root-hash','super_admin',1,1,1),('operator','operator-hash','admin',1,1,1);
                INSERT INTO public.maintenance_jobs(action,status,created_at,parameters,requested_by)
                VALUES ('reset_app_data','running',1,'{}','root'),('retention','ok',1,'{}','root');
                INSERT INTO public.admin_settings(key,value,updated_at)
                VALUES ('simple_theme_settings_v4','{"preset":"dark"}',1),('page_cache_generation','99',1);
                INSERT INTO public.api_keys(key_id,name,secret_hash,scopes_json,allowed_ips_json,is_active,created_at,created_by)
                VALUES ('key1','Key 1','secret-hash','["read"]','[]',1,1,'root');
                INSERT INTO public.node_groups(name,description,country_code,is_active,is_system,created_at,updated_at)
                VALUES ('Ungrouped','system','',1,1,1,1),('VN','Vietnam','VN',1,0,1,1);
                INSERT INTO public.node_inventory(node,public_ip) VALUES ('node-1','192.0.2.1');
                INSERT INTO public.node_group_memberships(node,group_id,assigned_at,assigned_by)
                SELECT 'node-1',id,1,'root' FROM public.node_groups WHERE name='VN';
                INSERT INTO public.metric_history(sample_time,value) VALUES (1,123);
            """)
        conn.commit()

    backup = configuration_backup.create_configuration_backup("root", reason="integration", protect=True)
    reset = maintenance_native.reset_app_data(
        actor_user_id=1,
        actor_username="root",
        current_job_id=1,
        backup_status="verified",
        backup_kind="configuration",
        backup_path=backup["path"],
        backup_sha256=backup["sha256"],
    )
    assert "metric_history" in reset["tables_truncated"]

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT username FROM public.dashboard_users ORDER BY id")
        assert cur.fetchall() == [("root",)]
        cur.execute("SELECT id,action FROM public.maintenance_jobs")
        assert cur.fetchall() == [(1, "reset_app_data")]
        cur.execute("SELECT COUNT(*) FROM public.maintenance_nuclear_audit")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT name FROM public.node_groups")
        assert cur.fetchall() == [("Ungrouped",)]
        cur.execute("SELECT COUNT(*) FROM public.metric_history")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT key FROM public.admin_settings ORDER BY key")
        assert {row[0] for row in cur.fetchall()} == {
            "app_secret_key", "bandwidth_consumption_accept_after", "operational_push_accept_after"
        }

    restored = configuration_backup.restore_configuration_backup(
        backup["backup_id"], actor_user_id=1, actor_username="root"
    )
    assert restored["restored"]["users"] == 1
    assert restored["restored"]["api_keys"] == 1
    assert restored["restored"]["groups"] == 1

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT username,role FROM public.dashboard_users ORDER BY username")
        assert cur.fetchall() == [("operator", "admin"), ("root", "super_admin")]
        cur.execute("SELECT key FROM public.admin_settings ORDER BY key")
        keys = {row[0] for row in cur.fetchall()}
        assert "simple_theme_settings_v4" in keys
        assert "page_cache_generation" not in keys
        cur.execute("SELECT COUNT(*) FROM public.pending_node_group_restore WHERE node='node-1' AND group_name='VN'")
        assert cur.fetchone()[0] == 1
        cur.execute("INSERT INTO public.node_inventory(node,public_ip) VALUES ('node-1','192.0.2.1')")
        cur.execute("""
            SELECT g.name
              FROM public.node_group_memberships m
              JOIN public.node_groups g ON g.id=m.group_id
             WHERE m.node='node-1'
        """)
        assert cur.fetchone()[0] == "VN"
        cur.execute("SELECT COUNT(*) FROM public.pending_node_group_restore WHERE node='node-1'")
        assert cur.fetchone()[0] == 0
        conn.commit()
