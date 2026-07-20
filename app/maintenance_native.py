"""PostgreSQL-native maintenance primitives for VirtInfra Monitor.

This module is intentionally independent from Flask ``app.py``.  Maintenance
workers can import it without triggering application startup, inventory cleanup,
route registration, cache warm-up, or Gunicorn-side database writes.
"""
from __future__ import annotations

import os
import time
from collections.abc import Iterable
from typing import Any

import psycopg
from psycopg import sql

DEFAULT_DSN = "postgresql://bw_monitor@127.0.0.1:5432/bw_monitor"
MAINTENANCE_GLOBAL_LOCK = "virtinfra-monitor:maintenance:global"
MAINTENANCE_ENQUEUE_LOCK = "virtinfra-monitor:maintenance:enqueue"
NODE_LOCK_PREFIX = "virtinfra-push:"

# Tables containing monitoring state/history.  Dashboard users, Admin settings,
# account-login history, API credentials and maintenance queue/history survive a
# normal monitoring reset.
MONITORING_TABLES: tuple[str, ...] = (
    "vm_iface_current",
    "vm_current_fast",
    "node_current_fast",
    "vm_abuse_state",
    "vm_abuse_events",
    "vm_abuse_incidents",
    "vm_disk_current",
    "node_storage_current",
    "vm_disk_summary_current",
    "node_storage_mount_summary_current",
    "vm_latest_metrics",
    "node_host_latest",
    "node_filesystem_latest",
    "node_physical_net_latest",
    "node_bridge_addresses_latest",
    "agent_health_latest",
    "vm_location_latest",
    "vm_node_presence",
    "vm_migration_events",
    "node_missed_events",
    "push_receipts",
    "node_push_snapshots",
    "bandwidth_daily",
    "bandwidth_hourly",
    "usage",
    "node_stats",
    "vm_perf_stats",
    "node_host_stats",
    "node_filesystem_stats",
    "node_physical_net_stats",
    "agent_health_stats",
    "node_bandwidth_consumption_2h",
    "node_consumption_hourly",
    "node_consumption_daily",
    "node_vm_consumption_hourly",
    "node_vm_consumption_daily",
    "vm_chart_5m",
    "vm_raw_detail_5m",
    "node_chart_5m",
    "node_logs",
    "retention_runs",
)

# Inventory and Node Group configuration are preserved by ordinary monitoring
# cleanup. Purging one node still deletes its current membership through the
# node_inventory foreign key. Only the explicit Nuclear Reset includes these
# tables in its destructive allow-list.
INVENTORY_TABLES: tuple[str, ...] = ("vm_inventory", "node_inventory")
NODE_GROUP_CONFIGURATION_TABLES: tuple[str, ...] = (
    "node_group_memberships",
    "node_group_membership_history",
    "node_groups",
)

# A nuclear operational reset preserves dashboard users, Admin settings,
# schema metadata, the durable maintenance queue and permanent nuclear audit.
RESET_APP_TABLES: tuple[str, ...] = tuple(dict.fromkeys(
    NODE_GROUP_CONFIGURATION_TABLES + MONITORING_TABLES + INVENTORY_TABLES + (
        "abuse_policy_versions",
        "account_logs",
        "api_access_logs",
        "api_key_events",
        "api_keys",
    )
))

API_LOG_TABLES: tuple[str, ...] = ("api_access_logs", "api_key_events")
API_DATA_TABLES: tuple[str, ...] = ("api_access_logs", "api_key_events", "api_keys")


def database_dsn() -> str:
    return (
        os.environ.get("BW_DATABASE_URL")
        or os.environ.get("BW_POSTGRES_DSN")
        or os.environ.get("DATABASE_URL")
        or DEFAULT_DSN
    )


def dedicated_connection(
    *,
    autocommit: bool = False,
    application_name: str = "virtinfra-maintenance",
    statement_timeout_ms: int = 0,
    lock_timeout_ms: int = 60_000,
) -> psycopg.Connection:
    """Open a non-pooled PostgreSQL connection for maintenance work."""
    conn = psycopg.connect(database_dsn(), autocommit=autocommit, connect_timeout=15)
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'UTC'")
        cur.execute("SELECT set_config('application_name', %s, false)", (application_name,))
        cur.execute(
            "SELECT set_config('statement_timeout', %s, false)",
            (f"{max(0, int(statement_timeout_ms))}ms",),
        )
        cur.execute(
            "SELECT set_config('lock_timeout', %s, false)",
            (f"{max(0, int(lock_timeout_ms))}ms",),
        )
        cur.execute(
            "SELECT set_config('idle_in_transaction_session_timeout', '10min', false)"
        )
    if not autocommit:
        conn.commit()
    return conn


def advisory_xact_lock(cur: psycopg.Cursor, key: str) -> None:
    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))


def advisory_node_lock(cur: psycopg.Cursor, node: str) -> None:
    advisory_xact_lock(cur, NODE_LOCK_PREFIX + str(node or "").strip())


def _existing_public_tables(cur: psycopg.Cursor) -> set[str]:
    cur.execute(
        """
        SELECT tablename
        FROM pg_catalog.pg_tables
        WHERE schemaname = 'public'
        """
    )
    return {str(row[0]) for row in cur.fetchall()}


def _table_stats(cur: psycopg.Cursor, tables: Iterable[str]) -> dict[str, dict[str, int]]:
    names = tuple(dict.fromkeys(str(name) for name in tables if str(name)))
    if not names:
        return {}
    cur.execute(
        """
        SELECT c.relname,
               COALESCE(s.n_live_tup, 0)::bigint,
               pg_total_relation_size(c.oid)::bigint
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r','p')
          AND c.relname = ANY(%s)
        """,
        (list(names),),
    )
    return {
        str(name): {"estimated_rows": int(rows or 0), "bytes_before": int(size or 0)}
        for name, rows, size in cur.fetchall()
    }


def truncate_tables(
    tables: Iterable[str],
    *,
    action: str,
    restart_identity: bool = True,
) -> dict[str, Any]:
    """Atomically truncate an explicit, allow-listed set of public tables."""
    requested = tuple(dict.fromkeys(str(name) for name in tables if str(name)))
    started = int(time.time())
    conn = dedicated_connection(
        application_name=f"virtinfra-maintenance:{action}",
        statement_timeout_ms=0,
        lock_timeout_ms=120_000,
    )
    try:
        with conn.cursor() as cur:
            advisory_xact_lock(cur, MAINTENANCE_GLOBAL_LOCK)
            existing = _existing_public_tables(cur)
            selected = tuple(name for name in requested if name in existing)
            missing = tuple(name for name in requested if name not in existing)
            before = _table_stats(cur, selected)
            if selected:
                statement = sql.SQL("TRUNCATE TABLE {} {} CASCADE").format(
                    sql.SQL(", ").join(
                        sql.SQL("public.{}" ).format(sql.Identifier(name))
                        for name in selected
                    ),
                    sql.SQL("RESTART IDENTITY") if restart_identity else sql.SQL("CONTINUE IDENTITY"),
                )
                cur.execute(statement)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

    estimated_rows = sum(item["estimated_rows"] for item in before.values())
    bytes_before = sum(item["bytes_before"] for item in before.values())
    return {
        "engine": "postgresql",
        "action": action,
        "tables_truncated": list(selected),
        "tables_missing": list(missing),
        "table_count": len(selected),
        "estimated_rows_removed": estimated_rows,
        "bytes_before": bytes_before,
        "started_at": started,
        "finished_at": int(time.time()),
        "method": "TRUNCATE RESTART IDENTITY CASCADE",
    }


def set_reset_acceptance_epochs(epoch: int | None = None) -> dict[str, int]:
    epoch = max(0, int(epoch or time.time()))
    values = {
        "operational_push_accept_after": epoch,
        "bandwidth_consumption_accept_after": epoch,
    }
    conn = dedicated_connection(
        application_name="virtinfra-maintenance:reset-epochs",
        statement_timeout_ms=30_000,
        lock_timeout_ms=15_000,
    )
    try:
        with conn.cursor() as cur:
            for key, value in values.items():
                cur.execute(
                    """
                    INSERT INTO public.admin_settings(key,value,updated_at)
                    VALUES (%s,%s,%s)
                    ON CONFLICT(key) DO UPDATE SET
                        value=EXCLUDED.value,updated_at=EXCLUDED.updated_at
                    """,
                    (key, str(value), epoch),
                )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return values


def clear_monitoring_data() -> dict[str, Any]:
    result = truncate_tables(MONITORING_TABLES, action="clear_monitoring_data")
    result["acceptance_epochs"] = set_reset_acceptance_epochs()
    result["preserved"] = [
        "dashboard_users",
        "admin_settings",
        "account_logs",
        "api_keys",
        "api_key_events",
        "api_access_logs",
        "maintenance_jobs",
        "bw_meta",
        "node_inventory",
        "vm_inventory",
        "node_groups",
        "node_group_memberships",
        "node_group_membership_history",
    ]
    return result


def _recreate_ungrouped() -> int:
    now = int(time.time())
    conn = dedicated_connection(
        application_name="virtinfra-maintenance:recreate-ungrouped",
        statement_timeout_ms=30_000,
        lock_timeout_ms=15_000,
    )
    try:
        with conn.cursor() as cur:
            advisory_xact_lock(cur, MAINTENANCE_GLOBAL_LOCK)
            cur.execute("""
                INSERT INTO public.node_groups(
                    name,description,country_code,is_active,is_system,
                    created_at,updated_at,hidden_at
                )
                SELECT 'Ungrouped',
                       'Default group for nodes without an explicit assignment',
                       '',1,1,%s,%s,NULL
                WHERE NOT EXISTS (
                    SELECT 1 FROM public.node_groups WHERE is_system=1
                )
                RETURNING id
            """, (now, now))
            row = cur.fetchone()
            if row:
                group_id = int(row[0])
            else:
                cur.execute("SELECT id FROM public.node_groups WHERE is_system=1 ORDER BY id LIMIT 1")
                group_id = int(cur.fetchone()[0])
        conn.commit()
        return group_id
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def reset_app_data() -> dict[str, Any]:
    """Atomically perform the explicit Nuclear Reset and recreate Ungrouped.

    Ordinary retention/cleanup never calls this function. Node Group rows are
    included only in this explicit allow-list, and the immutable system group
    is recreated before the destructive transaction commits.
    """
    action = "reset_app_data"
    started = int(time.time())
    conn = dedicated_connection(
        application_name="virtinfra-maintenance:reset-app-data",
        statement_timeout_ms=0,
        lock_timeout_ms=120_000,
    )
    try:
        with conn.cursor() as cur:
            advisory_xact_lock(cur, MAINTENANCE_GLOBAL_LOCK)
            existing = _existing_public_tables(cur)
            selected = tuple(name for name in RESET_APP_TABLES if name in existing)
            missing = tuple(name for name in RESET_APP_TABLES if name not in existing)
            before = _table_stats(cur, selected)
            if selected:
                statement = sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(
                        sql.SQL("public.{}").format(sql.Identifier(name))
                        for name in selected
                    )
                )
                cur.execute(statement)
            now = int(time.time())
            cur.execute(
                """
                INSERT INTO public.node_groups(
                    name,description,country_code,is_active,is_system,
                    created_at,updated_at,hidden_at
                ) VALUES (
                    'Ungrouped',
                    'Default group for nodes without an explicit assignment',
                    '',1,1,%s,%s,NULL
                )
                RETURNING id
                """,
                (now, now),
            )
            ungrouped_group_id = int(cur.fetchone()[0])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

    result = {
        "engine": "postgresql",
        "action": action,
        "tables_truncated": list(selected),
        "tables_missing": list(missing),
        "table_count": len(selected),
        "estimated_rows_removed": sum(item["estimated_rows"] for item in before.values()),
        "bytes_before": sum(item["bytes_before"] for item in before.values()),
        "started_at": started,
        "finished_at": int(time.time()),
        "method": "TRUNCATE RESTART IDENTITY CASCADE",
        "ungrouped_group_id": ungrouped_group_id,
    }
    result["acceptance_epochs"] = set_reset_acceptance_epochs()
    result["preserved"] = [
        "dashboard_users",
        "admin_settings",
        "maintenance_jobs",
        "maintenance_nuclear_audit",
        "bw_meta",
    ]
    return result


def clear_api_logs() -> dict[str, Any]:
    return truncate_tables(API_LOG_TABLES, action="clear_api_logs")


def clear_api_data() -> dict[str, Any]:
    return truncate_tables(API_DATA_TABLES, action="clear_api_data")


def vacuum_analyze() -> dict[str, Any]:
    """Run online VACUUM (ANALYZE) with no statement timeout.

    VACUUM cannot execute inside a transaction block, hence the dedicated
    autocommit connection.  It does not stop Gunicorn and does not promise a
    smaller physical database file.
    """
    started = int(time.time())
    conn = dedicated_connection(
        autocommit=True,
        application_name="virtinfra-maintenance:vacuum",
        statement_timeout_ms=0,
        lock_timeout_ms=60_000,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database())")
            before = int(cur.fetchone()[0] or 0)
            cur.execute("VACUUM (ANALYZE)")
            cur.execute("SELECT pg_database_size(current_database())")
            after = int(cur.fetchone()[0] or 0)
    finally:
        conn.close()
    return {
        "engine": "postgresql",
        "db_bytes_before": before,
        "db_bytes_after": after,
        "physical_bytes_reclaimed": max(0, before - after),
        "started_at": started,
        "finished_at": int(time.time()),
        "online": True,
        "statement_timeout_ms": 0,
        "note": "VACUUM reclaims dead tuples for reuse; physical shrink is not expected.",
    }


def database_status() -> dict[str, Any]:
    conn = dedicated_connection(
        autocommit=True,
        application_name="virtinfra-maintenance:status",
        statement_timeout_ms=30_000,
        lock_timeout_ms=5_000,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_database_size(current_database())::bigint,
                       COALESCE((SELECT SUM(size)::bigint FROM pg_ls_waldir()), 0)
                """
            )
            db_bytes, wal_bytes = cur.fetchone()
            cur.execute(
                """
                SELECT COALESCE(SUM(n_live_tup),0)::bigint,
                       COALESCE(SUM(n_dead_tup),0)::bigint,
                       COUNT(*)::bigint
                FROM pg_stat_user_tables
                """
            )
            live_rows, dead_rows, table_count = cur.fetchone()
    finally:
        conn.close()
    return {
        "engine": "postgresql",
        "db_bytes": int(db_bytes or 0),
        "wal_bytes": int(wal_bytes or 0),
        "estimated_live_rows": int(live_rows or 0),
        "estimated_dead_rows": int(dead_rows or 0),
        "table_count": int(table_count or 0),
        "checked_at": int(time.time()),
    }


def preview_tables(tables: Iterable[str]) -> dict[str, Any]:
    """Return a read-only estimate for a destructive maintenance preview."""
    requested = tuple(dict.fromkeys(str(name) for name in tables if str(name)))
    conn = dedicated_connection(
        application_name="virtinfra-maintenance:preview",
        statement_timeout_ms=30_000,
        lock_timeout_ms=5_000,
    )
    try:
        with conn.cursor() as cur:
            existing = _existing_public_tables(cur)
            selected = tuple(name for name in requested if name in existing)
            stats = _table_stats(cur, selected)
            cur.execute("SELECT pg_database_size(current_database())")
            database_bytes = int(cur.fetchone()[0] or 0)
        conn.commit()
    finally:
        conn.close()
    return {
        "tables": stats,
        "table_count": len(selected),
        "estimated_rows": sum(item["estimated_rows"] for item in stats.values()),
        "estimated_bytes": sum(item["bytes_before"] for item in stats.values()),
        "database_bytes": database_bytes,
        "missing": [name for name in requested if name not in selected],
    }


def preview_reset_app_data() -> dict[str, Any]:
    result = preview_tables(RESET_APP_TABLES)
    result["preserved"] = [
        "dashboard_users",
        "admin_settings",
        "maintenance_jobs",
        "maintenance_nuclear_audit",
        "bw_meta",
    ]
    return result
