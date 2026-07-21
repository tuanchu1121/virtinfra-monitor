#!/usr/bin/env python3
"""Prove R22 Node/Group/Summary plans stay on node-level rollups.

Requires a disposable PostgreSQL DSN in BW_TEST_DATABASE_URL. The validator
creates TEMP tables, seeds 350 nodes, runs EXPLAIN (ANALYZE, BUFFERS, FORMAT
JSON) against the exact SQL builder loaded from the application, and rejects
any per-VM relation or vm_uuid grouping in the render plan.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {
    "node_stats",
    "vm_consumption_hourly",
    "vm_consumption_daily",
    "node_vm_consumption_hourly",
    "node_vm_consumption_daily",
}


def install_sqlite_shim(path: Path) -> None:
    module = types.ModuleType("bw_pg")
    module.Error = sqlite3.Error
    module.IntegrityError = sqlite3.IntegrityError
    module.OperationalError = sqlite3.OperationalError
    module.Binary = sqlite3.Binary

    def connect(_path=None, timeout=30, **_kwargs):
        conn = sqlite3.connect(str(path), timeout=timeout)
        conn.create_function("hashtextextended", 2, lambda value, seed: abs(hash((value, seed))) % (2**31))
        conn.create_function("pg_advisory_lock", 1, lambda _value: 1)
        conn.create_function("pg_advisory_unlock", 1, lambda _value: 1)
        conn.create_function("pg_try_advisory_lock", 1, lambda _value: 1)
        conn.create_function("pg_try_advisory_xact_lock", 1, lambda _value: 1)
        return conn

    module.connect = connect
    module.database_stats = lambda *_a, **_k: {"database_size_bytes": 0, "wal_size_bytes": 0, "shm_size_bytes": 0}
    module.healthcheck = lambda *_a, **_k: True
    sys.modules["bw_pg"] = module


def load_exact_node_sql(start: int, end: int) -> tuple[str, list[Any]]:
    with tempfile.TemporaryDirectory(prefix="r22-plan-sql-") as temp:
        os.environ.pop("BW_DATABASE_URL", None)
        os.environ.pop("BW_POSTGRES_DSN", None)
        os.environ.update({
            "BW_MONITOR_DB": str(Path(temp) / "runtime.sqlite3"),
            "BW_ADMIN_SECRET_KEY": "r22-plan-validator",
            "BW_MONITOR_TOKEN": "r22-plan-validator-token",
            "BW_START_BACKGROUND_THREADS": "0",
        })
        install_sqlite_shim(Path(temp) / "runtime.sqlite3")
        sys.path.insert(0, str(ROOT / "app"))
        import app as app_module  # type: ignore
        return app_module._r21_node_dataset_sql(start, end)


def seed_disposable_database(conn, start: int, end: int, nodes: int) -> None:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout='120s'")
        cur.execute("SET lock_timeout='5s'")
        cur.execute("""
          CREATE TEMP TABLE node_consumption_5m(
            bucket_start bigint NOT NULL,node text NOT NULL,
            physical_public_rx_bytes bigint NOT NULL DEFAULT 0,physical_public_tx_bytes bigint NOT NULL DEFAULT 0,
            physical_private_rx_bytes bigint NOT NULL DEFAULT 0,physical_private_tx_bytes bigint NOT NULL DEFAULT 0,
            vm_public_rx_bytes bigint NOT NULL DEFAULT 0,vm_public_tx_bytes bigint NOT NULL DEFAULT 0,
            vm_private_rx_bytes bigint NOT NULL DEFAULT 0,vm_private_tx_bytes bigint NOT NULL DEFAULT 0,
            physical_coverage_seconds bigint NOT NULL DEFAULT 0,vm_coverage_seconds bigint NOT NULL DEFAULT 0,
            vm_count bigint NOT NULL DEFAULT 0,last_push bigint NOT NULL DEFAULT 0,
            PRIMARY KEY(bucket_start,node));
          CREATE TEMP TABLE node_consumption_hourly(LIKE node_consumption_5m INCLUDING DEFAULTS);
          ALTER TABLE node_consumption_hourly RENAME COLUMN bucket_start TO hour_start;
          ALTER TABLE node_consumption_hourly ADD PRIMARY KEY(hour_start,node);
          CREATE TEMP TABLE node_consumption_daily(LIKE node_consumption_5m INCLUDING DEFAULTS);
          ALTER TABLE node_consumption_daily RENAME COLUMN bucket_start TO day_start;
          ALTER TABLE node_consumption_daily ADD PRIMARY KEY(day_start,node);
          CREATE TEMP TABLE node_inventory(node text PRIMARY KEY,status text,last_push bigint,deleted_at bigint);
          CREATE TEMP TABLE node_groups(id bigint PRIMARY KEY,is_active integer);
          CREATE TEMP TABLE node_group_memberships(node text PRIMARY KEY,group_id bigint);
          CREATE TEMP TABLE node_bridge_addresses_latest(node text,role text,primary_ipv4 text);
          CREATE TEMP TABLE node_physical_net_latest(node text,role text);

          -- Sentinel per-VM relations exist, but a compliant plan must not scan them.
          CREATE TEMP TABLE node_stats(node text,vm_uuid text,bridge text,last_push bigint);
          CREATE TEMP TABLE vm_consumption_hourly(hour_start bigint,node text,vm_uuid text,bridge text,rx_bytes bigint,tx_bytes bigint);
          CREATE TEMP TABLE vm_consumption_daily(day_start bigint,node text,vm_uuid text,bridge text,rx_bytes bigint,tx_bytes bigint);
        """)
        cur.execute("INSERT INTO node_groups VALUES (1,1)")
        cur.execute(
            "INSERT INTO node_inventory(node,status,last_push,deleted_at) "
            "SELECT 'node-'||to_char(i,'FM000'),'active',%s,NULL FROM generate_series(1,%s) i",
            (end, nodes),
        )
        cur.execute(
            "INSERT INTO node_group_memberships(node,group_id) "
            "SELECT 'node-'||to_char(i,'FM000'),1 FROM generate_series(1,%s) i",
            (nodes,),
        )
        cur.execute(
            "INSERT INTO node_bridge_addresses_latest(node,role,primary_ipv4) "
            "SELECT 'node-'||to_char(i,'FM000'),'public','192.0.2.'||((i-1)%%254+1)::text "
            "FROM generate_series(1,%s) i",
            (nodes,),
        )
        cur.execute(
            "INSERT INTO node_physical_net_latest(node,role) "
            "SELECT 'node-'||to_char(i,'FM000'),role FROM generate_series(1,%s) i "
            "CROSS JOIN (VALUES('public'),('private')) r(role)",
            (nodes,),
        )

        hour0 = (start // 3600) * 3600
        hour1 = ((end + 3599) // 3600) * 3600
        day0 = (start // 86400) * 86400
        day1 = ((end + 86399) // 86400) * 86400
        bucket0 = (start // 300) * 300
        bucket1 = ((end + 299) // 300) * 300
        cur.execute(
            "INSERT INTO node_consumption_hourly "
            "SELECT h,'node-'||to_char(i,'FM000'),100,50,20,10,90,40,15,5,3600,3600,200,h+3599 "
            "FROM generate_series(%s,%s,3600) h CROSS JOIN generate_series(1,%s) i",
            (hour0, hour1, nodes),
        )
        cur.execute(
            "INSERT INTO node_consumption_daily "
            "SELECT d,'node-'||to_char(i,'FM000'),2400,1200,480,240,2160,960,360,120,86400,86400,200,d+86399 "
            "FROM generate_series(%s,%s,86400) d CROSS JOIN generate_series(1,%s) i",
            (day0, day1, nodes),
        )
        cur.execute(
            "INSERT INTO node_consumption_5m "
            "SELECT b,'node-'||to_char(i,'FM000'),10,5,2,1,9,4,1,1,300,300,200,b+299 "
            "FROM generate_series(%s,%s,300) b CROSS JOIN generate_series(1,%s) i",
            (bucket0, bucket1, nodes),
        )
        cur.execute("ANALYZE node_consumption_5m; ANALYZE node_consumption_hourly; ANALYZE node_consumption_daily")


def walk_plan(node: Any, relations: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        if "Relation Name" in node:
            relations.append({
                "relation": node.get("Relation Name"),
                "node_type": node.get("Node Type"),
                "actual_rows": node.get("Actual Rows", 0),
                "actual_loops": node.get("Actual Loops", 0),
                "shared_hit_blocks": node.get("Shared Hit Blocks", 0),
                "shared_read_blocks": node.get("Shared Read Blocks", 0),
            })
        for value in node.values():
            walk_plan(value, relations)
    elif isinstance(node, list):
        for value in node:
            walk_plan(value, relations)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=os.environ.get("BW_TEST_DATABASE_URL", ""))
    parser.add_argument("--nodes", type=int, default=350)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if not args.dsn:
        raise SystemExit("BW_TEST_DATABASE_URL or --dsn is required and must point to a disposable PostgreSQL database")

    # Deliberately unaligned 24-hour window: two raw 5-minute edges and hourly middle.
    start = 1_721_456_620  # fixed epoch, not aligned to an hour
    end = start + 86400
    sql, params = load_exact_node_sql(start, end)
    lowered = sql.lower()
    forbidden_sql = sorted(name for name in FORBIDDEN if name in lowered)
    if forbidden_sql or "vm_uuid" in lowered:
        raise SystemExit(f"forbidden render SQL: relations={forbidden_sql}, vm_uuid={'vm_uuid' in lowered}")

    import psycopg
    with psycopg.connect(args.dsn, autocommit=False) as conn:
        seed_disposable_database(conn, start, end, max(1, args.nodes))
        explain_sql = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql.replace("?", "%s")
        with conn.cursor() as cur:
            cur.execute(explain_sql, params)
            raw = cur.fetchone()[0]
        plan_root = raw[0] if isinstance(raw, list) else raw
        relations: list[dict[str, Any]] = []
        walk_plan(plan_root, relations)
        seen = sorted({str(item["relation"]) for item in relations})
        forbidden_plan = sorted(FORBIDDEN.intersection(seen))
        if forbidden_plan:
            raise SystemExit(f"forbidden relations in EXPLAIN plan: {forbidden_plan}")
        conn.rollback()

    allowed_data = {"node_consumption_5m", "node_consumption_hourly", "node_consumption_daily"}
    data_relations = sorted(allowed_data.intersection(seen))
    if not data_relations:
        raise SystemExit("EXPLAIN plan did not scan any node Consumption rollup")

    report = {
        "ok": True,
        "release": "50.5.9-prod-r22.7-vm-consumption-rollup-only",
        "window_seconds": end - start,
        "seeded_nodes": args.nodes,
        "sql_reused_by": ["node_rows", "node_totals", "group_rows", "summary", "physical_totals", "vm_totals", "difference"],
        "forbidden_relations": sorted(FORBIDDEN),
        "forbidden_relations_seen": forbidden_plan,
        "contains_vm_uuid": "vm_uuid" in lowered,
        "relations_seen": seen,
        "relation_scans": relations,
        "planning_time_ms": plan_root.get("Planning Time", 0),
        "execution_time_ms": plan_root.get("Execution Time", 0),
        "plan": plan_root,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
