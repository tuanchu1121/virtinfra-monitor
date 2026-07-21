#!/usr/bin/env python3
"""Benchmark R22 global Top VM sorting on PostgreSQL.

The default mode is read-only against the existing current tables. With
--synthetic, TEMP tables shadow production tables in the session and 60,000 VM
rows are generated without changing persistent data.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
from pathlib import Path
from typing import Any

SORTS = {
    "total": "c.total_bytes",
    "rx": "c.rx_bytes",
    "tx": "c.tx_bytes",
    "public": "c.public_rx_bytes+c.public_tx_bytes",
    "private": "c.private_rx_bytes+c.private_tx_bytes",
    "mbps": "c.total_mbps",
    "peakmbps": "c.total_peak_mbps",
    "pps": "c.total_pps",
    "peakpps": "c.total_peak_pps",
    "sample": "CASE UPPER(COALESCE(c.sample_quality,'LEGACY')) WHEN 'POOR' THEN 3 WHEN 'DEGRADED' THEN 2 WHEN 'GOOD' THEN 1 ELSE 0 END",
    "drops": "c.drops",
    "errors": "c.errors",
    "cpu": "c.cpu_core_percent",
    "cpufull": "c.cpu_full_percent",
    "vcpu": "c.vcpu_current",
    "ram": "CASE WHEN c.ram_available_kib>0 AND (c.ram_usable_kib>0 OR c.ram_unused_kib>0) AND c.ram_usable_kib<=c.ram_available_kib*1.05 THEN (c.ram_available_kib-c.ram_usable_kib)*100.0/c.ram_available_kib END",
    "ramguest": "CASE WHEN c.ram_available_kib>0 AND (c.ram_usable_kib>0 OR c.ram_unused_kib>0) AND c.ram_usable_kib<=c.ram_available_kib*1.05 THEN (c.ram_available_kib-c.ram_usable_kib)*100.0/c.ram_available_kib END",
    "ramused": "CASE WHEN c.ram_available_kib>0 AND (c.ram_usable_kib>0 OR c.ram_unused_kib>0) AND c.ram_usable_kib<=c.ram_available_kib*1.05 THEN c.ram_available_kib-c.ram_usable_kib END",
    "ramrss": "NULLIF(c.ram_rss_kib,0)",
    "ramassigned": "NULLIF(c.ram_current_kib,0)",
    "diskr": "c.disk_read_bps",
    "diskw": "c.disk_write_bps",
    "diskallocated": "CASE WHEN d.node IS NOT NULL THEN d.allocated_bytes END",
    "diskassigned": "CASE WHEN d.node IS NOT NULL THEN d.assigned_bytes END",
    "diskallocpct": "CASE WHEN d.node IS NOT NULL AND d.assigned_bytes>0 THEN d.allocated_bytes*1.0/d.assigned_bytes END",
    "diskcount": "CASE WHEN d.node IS NOT NULL THEN d.disk_count END",
    "last_push": "c.last_seen",
    "node": 'c.node COLLATE "C"',
    "vm": 'c.vm_uuid COLLATE "C"',
}


def seed_synthetic(conn, vm_count: int, node_count: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TEMP TABLE vm_current_fast(
              node text NOT NULL, vm_uuid text NOT NULL, last_seen bigint NOT NULL,
              public_rx_bytes bigint NOT NULL,public_tx_bytes bigint NOT NULL,
              private_rx_bytes bigint NOT NULL,private_tx_bytes bigint NOT NULL,
              rx_bytes bigint NOT NULL,tx_bytes bigint NOT NULL,total_bytes bigint NOT NULL,
              drops bigint NOT NULL,errors bigint NOT NULL,sample_quality text NOT NULL,
              total_mbps double precision NOT NULL,total_peak_mbps double precision NOT NULL,
              total_pps double precision NOT NULL,total_peak_pps double precision NOT NULL,
              cpu_full_percent double precision NOT NULL,cpu_core_percent double precision NOT NULL,
              vcpu_current integer NOT NULL,ram_current_kib bigint NOT NULL,ram_rss_kib bigint NOT NULL,
              ram_available_kib bigint NOT NULL,ram_unused_kib bigint NOT NULL,ram_usable_kib bigint NOT NULL,
              disk_read_bps double precision NOT NULL,disk_write_bps double precision NOT NULL,
              PRIMARY KEY(node,vm_uuid)
            );
            CREATE TEMP TABLE vm_disk_summary_current(
              node text NOT NULL,vm_uuid text NOT NULL,disk_count integer NOT NULL,
              allocated_bytes bigint NOT NULL,assigned_bytes bigint NOT NULL,
              PRIMARY KEY(node,vm_uuid)
            );
            CREATE TEMP TABLE node_inventory(node text PRIMARY KEY,status text,deleted_at bigint);
            CREATE TEMP TABLE vm_inventory(node text,vm_uuid text,status text,deleted_at bigint,PRIMARY KEY(node,vm_uuid));
            CREATE TEMP TABLE node_groups(id bigint PRIMARY KEY,is_active integer);
            CREATE TEMP TABLE node_group_memberships(node text PRIMARY KEY,group_id bigint);
            """
        )
        now = int(time.time())
        cur.execute("INSERT INTO node_groups VALUES (1,1)")
        cur.execute(
            "INSERT INTO node_inventory SELECT 'node-'||to_char(i,'FM000'),'active',NULL FROM generate_series(1,%s) i",
            (node_count,),
        )
        cur.execute(
            "INSERT INTO node_group_memberships SELECT 'node-'||to_char(i,'FM000'),1 FROM generate_series(1,%s) i",
            (node_count,),
        )
        cur.execute(
            """
            INSERT INTO vm_current_fast
            SELECT
              'node-'||to_char(mod(i-1,%s)+1,'FM000'),
              'vm-'||to_char(i,'FM000000'),%s,
              i*100,i*60,i*20,i*10,i*120,i*70,i*190,
              mod(i,7),mod(i,5),CASE mod(i,4) WHEN 0 THEN 'POOR' WHEN 1 THEN 'DEGRADED' WHEN 2 THEN 'GOOD' ELSE 'LEGACY' END,
              (i%%10000)/10.0,(i%%12000)/10.0,(i%%20000)/10.0,(i%%23000)/10.0,
              (i%%40000)/100.0,(i%%80000)/100.0,(i%%16)+1,
              1048576+(i%%64)*262144,786432+(i%%64)*131072,
              1048576+(i%%64)*262144,262144,524288,
              (i%%500000)/10.0,(i%%700000)/10.0
            FROM generate_series(1,%s) i
            """,
            (node_count, now, vm_count),
        )
        # Two deliberately low-network global winners prove sort independence.
        cur.execute(
            "UPDATE vm_current_fast SET total_bytes=1,rx_bytes=1,tx_bytes=0,ram_available_kib=67108864,ram_usable_kib=1024,ram_unused_kib=1024 WHERE vm_uuid='vm-000001'"
        )
        cur.execute(
            """
            INSERT INTO vm_disk_summary_current
            SELECT node,vm_uuid,1+mod(substring(vm_uuid from 4)::bigint,3),
                   1073741824+mod(substring(vm_uuid from 4)::bigint,100000)*1048576,
                   2147483648+mod(substring(vm_uuid from 4)::bigint,100000)*2097152
              FROM vm_current_fast
            """
        )
        cur.execute(
            "UPDATE vm_disk_summary_current SET allocated_bytes=1099511627776,assigned_bytes=2199023255552,disk_count=8 WHERE vm_uuid='vm-000002'"
        )
        cur.execute("ANALYZE vm_current_fast")
        cur.execute("ANALYZE vm_disk_summary_current")



def verify_synthetic_winners(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT vm_uuid FROM vm_current_fast c
             ORDER BY CASE WHEN c.ram_available_kib>0
                                AND (c.ram_usable_kib>0 OR c.ram_unused_kib>0)
                                AND c.ram_usable_kib<=c.ram_available_kib*1.05
                           THEN c.ram_available_kib-c.ram_usable_kib END DESC NULLS LAST,
                      c.node COLLATE "C",c.vm_uuid COLLATE "C"
             LIMIT 1
            """
        )
        ram_winner = str(cur.fetchone()[0])
        cur.execute(
            """
            SELECT c.vm_uuid FROM vm_current_fast c
            LEFT JOIN vm_disk_summary_current d ON d.node=c.node AND d.vm_uuid=c.vm_uuid
             ORDER BY CASE WHEN d.node IS NOT NULL THEN d.assigned_bytes END DESC NULLS LAST,
                      c.node COLLATE "C",c.vm_uuid COLLATE "C"
             LIMIT 1
            """
        )
        disk_winner = str(cur.fetchone()[0])
    if ram_winner != "vm-000001":
        raise RuntimeError(f"synthetic RAM winner mismatch: {ram_winner}")
    if disk_winner != "vm-000002":
        raise RuntimeError(f"synthetic disk winner mismatch: {disk_winner}")
    return {"ram": ram_winner, "disk": disk_winner}

def plan_relations(node: Any, result: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        if node.get("Relation Name"):
            result.append(
                {
                    "relation": node.get("Relation Name"),
                    "node_type": node.get("Node Type"),
                    "actual_rows": node.get("Actual Rows", 0),
                    "loops": node.get("Actual Loops", 0),
                    "shared_hit_blocks": node.get("Shared Hit Blocks", 0),
                    "shared_read_blocks": node.get("Shared Read Blocks", 0),
                    "temp_read_blocks": node.get("Temp Read Blocks", 0),
                    "temp_written_blocks": node.get("Temp Written Blocks", 0),
                }
            )
        for value in node.values():
            plan_relations(value, result)
    elif isinstance(node, list):
        for value in node:
            plan_relations(value, result)


def benchmark(conn, repetitions: int, limit: int, group_id: int) -> dict[str, Any]:
    results: dict[str, Any] = {}
    forbidden = {"node_stats", "usage", "vm_perf_stats", "vm_consumption_hourly", "vm_consumption_daily"}
    for key, expression in SORTS.items():
        sql = f"""
          SELECT c.node,c.vm_uuid,c.total_bytes,c.ram_current_kib,
                 d.allocated_bytes,d.assigned_bytes,d.disk_count
            FROM vm_current_fast c
            LEFT JOIN node_inventory ni ON ni.node=c.node
            LEFT JOIN vm_inventory vi ON vi.node=c.node AND vi.vm_uuid=c.vm_uuid
            LEFT JOIN vm_disk_summary_current d ON d.node=c.node AND d.vm_uuid=c.vm_uuid
           WHERE (ni.node IS NULL OR (COALESCE(ni.status,'active')<>'hidden' AND ni.deleted_at IS NULL))
             AND (vi.vm_uuid IS NULL OR (COALESCE(vi.status,'active')<>'hidden' AND vi.deleted_at IS NULL))
             AND EXISTS (
                   SELECT 1 FROM node_group_memberships gm
                   JOIN node_groups g ON g.id=gm.group_id
                   WHERE gm.node=c.node AND g.is_active=1 AND (%s=0 OR g.id=%s)
             )
           ORDER BY {expression} DESC NULLS LAST,c.node COLLATE "C",c.vm_uuid COLLATE "C"
           LIMIT %s
        """
        timings = []
        final_plan = None
        for _ in range(repetitions):
            with conn.cursor() as cur:
                cur.execute("EXPLAIN (ANALYZE,BUFFERS,WAL,FORMAT JSON) " + sql, (group_id, group_id, limit))
                raw = cur.fetchone()[0]
            final_plan = raw[0] if isinstance(raw, list) else raw
            timings.append(float(final_plan.get("Execution Time", 0.0)))
        relations: list[dict[str, Any]] = []
        plan_relations(final_plan, relations)
        seen = {str(item["relation"]) for item in relations}
        bad = sorted(seen & forbidden)
        if bad:
            raise RuntimeError(f"{key}: history/raw relations in plan: {bad}")
        results[key] = {
            "p50_ms": statistics.median(timings),
            "p95_ms": sorted(timings)[max(0, math.ceil(len(timings) * 0.95) - 1)],
            "max_ms": max(timings),
            "planning_time_ms": float(final_plan.get("Planning Time", 0.0)),
            "relations": relations,
            "plan": final_plan,
        }
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=os.environ.get("BW_TEST_DATABASE_URL") or os.environ.get("BW_DATABASE_URL") or "")
    parser.add_argument("--synthetic", action="store_true", help="Use TEMP synthetic current tables; persistent data is untouched")
    parser.add_argument("--vms", type=int, default=60_000)
    parser.add_argument("--nodes", type=int, default=300)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--group-id", type=int, default=0)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if not args.dsn:
        raise SystemExit("--dsn or BW_TEST_DATABASE_URL/BW_DATABASE_URL is required")

    import psycopg

    with psycopg.connect(args.dsn, autocommit=False) as conn:
        conn.execute("SET LOCAL statement_timeout='180s'")
        conn.execute("SET LOCAL lock_timeout='5s'")
        synthetic_winners = {}
        if args.synthetic:
            seed_synthetic(conn, max(1, args.vms), max(1, args.nodes))
            synthetic_winners = verify_synthetic_winners(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM vm_current_fast")
            row_count = int(cur.fetchone()[0])
        results = benchmark(conn, max(1, args.repetitions), max(1, args.limit), max(0, args.group_id))
        conn.rollback()

    report = {
        "ok": True,
        "release": "50.5.9-prod-r22.4-preflight-contract-hotfix",
        "synthetic": bool(args.synthetic),
        "vm_rows": row_count,
        "target_vm_rows": args.vms if args.synthetic else None,
        "target_nodes": args.nodes if args.synthetic else None,
        "repetitions": max(1, args.repetitions),
        "limit": max(1, args.limit),
        "synthetic_winners": synthetic_winners,
        "sorts": results,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
