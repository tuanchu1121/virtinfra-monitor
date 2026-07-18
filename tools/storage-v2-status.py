#!/usr/bin/env python3
"""Read-only Storage V2 status for VirtInfra Monitor."""
from __future__ import annotations
import argparse
import json
import os
import psycopg
from psycopg.rows import dict_row


def dsn() -> str:
    value = (os.environ.get("BW_DATABASE_URL") or os.environ.get("BW_POSTGRES_DSN") or "").strip()
    if not value:
        raise SystemExit("BW_DATABASE_URL/BW_POSTGRES_DSN is required")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args()
    with psycopg.connect(dsn(), row_factory=dict_row) as conn:
        capabilities = conn.execute("""
            SELECT current_setting('timescaledb.license', true) AS license,
                   EXISTS (SELECT 1 FROM pg_proc WHERE proname='add_retention_policy') AS has_retention_policy,
                   EXISTS (SELECT 1 FROM pg_proc WHERE proname='add_compression_policy') AS has_compression_policy
        """).fetchone()
        tables = conn.execute("""
            SELECT c.relname AS table_name,
                   pg_total_relation_size(c.oid) AS total_bytes,
                   COALESCE(s.n_live_tup,0)::bigint AS estimated_rows,
                   COALESCE(s.n_dead_tup,0)::bigint AS dead_rows
            FROM pg_class c
            LEFT JOIN pg_stat_user_tables s ON s.relid=c.oid
            WHERE c.oid IN (to_regclass('public.vm_chart_5m'),
                            to_regclass('public.vm_raw_detail_5m'),
                            to_regclass('public.node_chart_5m'))
            ORDER BY c.relname
        """).fetchall()
        hypertables = conn.execute("""
            SELECT hypertable_name,num_chunks,compression_enabled
            FROM timescaledb_information.hypertables
            WHERE hypertable_schema='public'
              AND hypertable_name IN ('vm_chart_5m','vm_raw_detail_5m','node_chart_5m')
            ORDER BY hypertable_name
        """).fetchall()
        jobs = conn.execute("""
            SELECT j.hypertable_name,j.proc_name,j.schedule_interval,j.scheduled,
                   s.last_run_status,s.last_run_started_at
            FROM timescaledb_information.jobs j
            LEFT JOIN timescaledb_information.job_stats s ON s.job_id=j.job_id
            WHERE j.hypertable_schema='public'
              AND j.hypertable_name IN ('vm_chart_5m','vm_raw_detail_5m','node_chart_5m')
            ORDER BY j.hypertable_name,j.proc_name
        """).fetchall()
        migrations = conn.execute("""
            SELECT version,applied_at,description
            FROM bw_meta.schema_migrations
            WHERE version='004_storage_v2'
        """).fetchall()
    expected_jobs = {
        ("vm_chart_5m", "policy_retention"),
        ("vm_chart_5m", "policy_compression"),
        ("vm_raw_detail_5m", "policy_retention"),
        ("node_chart_5m", "policy_retention"),
        ("node_chart_5m", "policy_compression"),
    }
    actual_jobs = {(str(r["hypertable_name"]), str(r["proc_name"])) for r in jobs}
    flags = {
        "VIRTINFRA_STORAGE_V2": os.environ.get("VIRTINFRA_STORAGE_V2", "1"),
        "VIRTINFRA_READ_CHART_V2": os.environ.get("VIRTINFRA_READ_CHART_V2", "1"),
        "VIRTINFRA_RAW_V2": os.environ.get("VIRTINFRA_RAW_V2", "1"),
        "VIRTINFRA_PUSH_OBSERVABILITY": os.environ.get("VIRTINFRA_PUSH_OBSERVABILITY", "1"),
    }
    capability_ok = bool(capabilities) and capabilities["license"] == "timescale" and bool(capabilities["has_retention_policy"]) and bool(capabilities["has_compression_policy"])
    result = {
        "ok": capability_ok and len(hypertables) == 3 and bool(migrations) and expected_jobs.issubset(actual_jobs),
        "capabilities": capabilities,
        "flags": flags,
        "tables": tables,
        "hypertables": hypertables,
        "jobs": jobs,
        "missing_jobs": sorted([f"{h}/{p}" for h, p in expected_jobs - actual_jobs]),
        "migrations": migrations,
    }
    if args.json:
        print(json.dumps(result, default=str, ensure_ascii=False, indent=2))
    else:
        print("Storage V2:", "PASS" if result["ok"] else "FAIL")
        print(f"  Timescale license={capabilities['license']} retention_api={capabilities['has_retention_policy']} compression_api={capabilities['has_compression_policy']}")
        for key, value in flags.items():
            print(f"  {key}={value}")
        for row in tables:
            print(f"  {row['table_name']}: rows~{row['estimated_rows']} dead~{row['dead_rows']} bytes={row['total_bytes']}")
        for row in hypertables:
            print(f"  hypertable {row['hypertable_name']}: chunks={row['num_chunks']} compression={row['compression_enabled']}")
        for row in jobs:
            print(f"  job {row['hypertable_name']}/{row['proc_name']}: scheduled={row['scheduled']} last={row['last_run_status']}")
        for item in result["missing_jobs"]:
            print(f"  MISSING job {item}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
