#!/usr/bin/env python3
"""Backfill R22 Consumption rollups without importing the Flask application.

This is an update/recovery utility, not a render-path dependency. It rebuilds
compact node-level edge/hour/day rows from retained raw data and canonical
per-VM rollups while the web and maintenance workers are stopped.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any

from maintenance_native import advisory_xact_lock, dedicated_connection

ROLLUP_LOCK = "virtinfra-consumption-backfill-r22"
MAX_BACKFILL_HOURS = 24 * 8
RAW_EDGE_HOURS = 48

def local_day_start(timestamp: int, offset_seconds: int) -> int:
    return (((int(timestamp) + int(offset_seconds)) // 86400) * 86400 - int(offset_seconds))

def _backfill_impl(hours: int) -> dict[str, Any]:
    """Rebuild recent node-level pre-aggregates from retained source data.

    Render requests never call this function. GROUP BY vm_uuid is deliberately
    limited to this stopped-service recovery path when compacting canonical
    per-VM rollups into one row per node/time bucket.
    """
    hours = max(1, min(MAX_BACKFILL_HOURS, int(hours)))
    now = int(time.time())
    cutoff = now - hours * 3600
    raw_cutoff = max(cutoff, now - RAW_EDGE_HOURS * 3600)
    timezone_offset = int(os.environ.get("BW_RETENTION_TZ_OFFSET_SECONDS", "25200") or 25200)
    public_bridge = str(os.environ.get("BW_PUBLIC_BRIDGE") or "br0").strip()
    private_bridge = str(os.environ.get("BW_PRIVATE_BRIDGE") or "br1").strip()
    first_day = local_day_start(cutoff, timezone_offset)

    conn = dedicated_connection(
        application_name="virtinfra-consumption-rollup-r22",
        statement_timeout_ms=30 * 60 * 1000,
        lock_timeout_ms=5000,
    )
    counts: dict[str, int] = {}
    try:
        with conn.transaction():
            with conn.cursor() as cursor:
                advisory_xact_lock(cursor, ROLLUP_LOCK)

                # Physical node-level 5-minute edge rows from retained raw data.
                cursor.execute(
                    """
                    WITH compact AS (
                      SELECT p.bucket::bigint AS bucket_start,p.node,
                        SUM(CASE WHEN LOWER(COALESCE(p.role,''))='public' THEN p.rx_delta ELSE 0 END)::bigint public_rx,
                        SUM(CASE WHEN LOWER(COALESCE(p.role,''))='public' THEN p.tx_delta ELSE 0 END)::bigint public_tx,
                        SUM(CASE WHEN LOWER(COALESCE(p.role,''))='private' THEN p.rx_delta ELSE 0 END)::bigint private_rx,
                        SUM(CASE WHEN LOWER(COALESCE(p.role,''))='private' THEN p.tx_delta ELSE 0 END)::bigint private_tx,
                        LEAST(300,MAX(COALESCE(p.interval_seconds,300)))::bigint coverage,
                        COUNT(DISTINCT COALESCE(p.last_push,p.time))::bigint samples,
                        MAX(COALESCE(p.last_push,p.time))::bigint last_push
                      FROM node_physical_net_stats p
                      WHERE p.time >= %s
                      GROUP BY p.bucket,p.node
                    )
                    INSERT INTO node_consumption_5m(
                      bucket_start,node,physical_public_rx_bytes,physical_public_tx_bytes,
                      physical_private_rx_bytes,physical_private_tx_bytes,
                      physical_coverage_seconds,physical_sample_count,last_push)
                    SELECT bucket_start,node,public_rx,public_tx,private_rx,private_tx,coverage,samples,last_push
                    FROM compact
                    ON CONFLICT(bucket_start,node) DO UPDATE SET
                      physical_public_rx_bytes=EXCLUDED.physical_public_rx_bytes,
                      physical_public_tx_bytes=EXCLUDED.physical_public_tx_bytes,
                      physical_private_rx_bytes=EXCLUDED.physical_private_rx_bytes,
                      physical_private_tx_bytes=EXCLUDED.physical_private_tx_bytes,
                      physical_coverage_seconds=EXCLUDED.physical_coverage_seconds,
                      physical_sample_count=EXCLUDED.physical_sample_count,
                      last_push=GREATEST(node_consumption_5m.last_push,EXCLUDED.last_push)
                    """,
                    (raw_cutoff,),
                )
                counts["physical_5m_rows"] = max(0, int(cursor.rowcount or 0))

                # VM node-level 5-minute edge rows from retained raw NIC data.
                # Host-tap direction is inverted to the guest perspective.
                cursor.execute(
                    """
                    WITH compact AS (
                      SELECT ns.bucket::bigint AS bucket_start,ns.node,
                        SUM(CASE WHEN ns.bridge=%s THEN ns.tx_delta ELSE 0 END)::bigint public_rx,
                        SUM(CASE WHEN ns.bridge=%s THEN ns.rx_delta ELSE 0 END)::bigint public_tx,
                        SUM(CASE WHEN ns.bridge=%s THEN ns.tx_delta ELSE 0 END)::bigint private_rx,
                        SUM(CASE WHEN ns.bridge=%s THEN ns.rx_delta ELSE 0 END)::bigint private_tx,
                        LEAST(300,MAX(COALESCE(ns.interval_seconds,300)))::bigint coverage,
                        COUNT(DISTINCT ns.last_push)::bigint samples,
                        COUNT(DISTINCT ns.vm_uuid)::bigint vm_count,
                        MAX(ns.last_push)::bigint last_push
                      FROM node_stats ns
                      WHERE ns.last_push >= %s
                      GROUP BY ns.bucket,ns.node
                    )
                    INSERT INTO node_consumption_5m(
                      bucket_start,node,vm_public_rx_bytes,vm_public_tx_bytes,
                      vm_private_rx_bytes,vm_private_tx_bytes,
                      vm_coverage_seconds,vm_sample_count,vm_count,last_push)
                    SELECT bucket_start,node,public_rx,public_tx,private_rx,private_tx,
                           coverage,samples,vm_count,last_push
                    FROM compact
                    ON CONFLICT(bucket_start,node) DO UPDATE SET
                      vm_public_rx_bytes=EXCLUDED.vm_public_rx_bytes,
                      vm_public_tx_bytes=EXCLUDED.vm_public_tx_bytes,
                      vm_private_rx_bytes=EXCLUDED.vm_private_rx_bytes,
                      vm_private_tx_bytes=EXCLUDED.vm_private_tx_bytes,
                      vm_coverage_seconds=EXCLUDED.vm_coverage_seconds,
                      vm_sample_count=EXCLUDED.vm_sample_count,
                      vm_count=EXCLUDED.vm_count,
                      last_push=GREATEST(node_consumption_5m.last_push,EXCLUDED.last_push)
                    """,
                    (public_bridge, public_bridge, private_bridge, private_bridge, raw_cutoff),
                )
                counts["vm_node_5m_rows"] = max(0, int(cursor.rowcount or 0))

                # Rebuild physical hourly columns from physical raw history that
                # is still retained. VM columns on the same rows are untouched.
                cursor.execute(
                    """
                    WITH per_bucket AS (
                      SELECT (((p.time::bigint+%s)/3600)*3600-%s)::bigint hour_start,
                        p.node,p.bucket,
                        SUM(CASE WHEN LOWER(COALESCE(p.role,''))='public' THEN p.rx_delta ELSE 0 END)::bigint public_rx,
                        SUM(CASE WHEN LOWER(COALESCE(p.role,''))='public' THEN p.tx_delta ELSE 0 END)::bigint public_tx,
                        SUM(CASE WHEN LOWER(COALESCE(p.role,''))='private' THEN p.rx_delta ELSE 0 END)::bigint private_rx,
                        SUM(CASE WHEN LOWER(COALESCE(p.role,''))='private' THEN p.tx_delta ELSE 0 END)::bigint private_tx,
                        MAX(COALESCE(p.interval_seconds,300))::bigint coverage,
                        MAX(COALESCE(p.last_push,p.time))::bigint last_push
                      FROM node_physical_net_stats p WHERE p.time >= %s
                      GROUP BY 1,p.node,p.bucket
                    ), compact AS (
                      SELECT hour_start,node,SUM(public_rx)::bigint public_rx,SUM(public_tx)::bigint public_tx,
                        SUM(private_rx)::bigint private_rx,SUM(private_tx)::bigint private_tx,
                        LEAST(3600,SUM(coverage))::bigint coverage,COUNT(*)::bigint samples,MAX(last_push)::bigint last_push
                      FROM per_bucket GROUP BY hour_start,node
                    )
                    INSERT INTO node_consumption_hourly(
                      hour_start,node,physical_public_rx_bytes,physical_public_tx_bytes,
                      physical_private_rx_bytes,physical_private_tx_bytes,
                      coverage_seconds,sample_count,physical_coverage_seconds,physical_sample_count,last_push)
                    SELECT hour_start,node,public_rx,public_tx,private_rx,private_tx,
                           coverage,samples,coverage,samples,last_push FROM compact
                    ON CONFLICT(hour_start,node) DO UPDATE SET
                      physical_public_rx_bytes=EXCLUDED.physical_public_rx_bytes,
                      physical_public_tx_bytes=EXCLUDED.physical_public_tx_bytes,
                      physical_private_rx_bytes=EXCLUDED.physical_private_rx_bytes,
                      physical_private_tx_bytes=EXCLUDED.physical_private_tx_bytes,
                      coverage_seconds=EXCLUDED.coverage_seconds,sample_count=EXCLUDED.sample_count,
                      physical_coverage_seconds=EXCLUDED.physical_coverage_seconds,
                      physical_sample_count=EXCLUDED.physical_sample_count,
                      last_push=GREATEST(node_consumption_hourly.last_push,EXCLUDED.last_push)
                    """,
                    (timezone_offset, timezone_offset, raw_cutoff),
                )
                counts["physical_hourly_rows"] = max(0, int(cursor.rowcount or 0))

                # Compact canonical per-VM hourly history into VM columns on the
                # same node-level hourly rows. This query is recovery-only.
                cursor.execute(
                    """
                    WITH compact AS (
                      SELECT hour_start,node,
                        SUM(CASE WHEN bridge=%s THEN tx_bytes ELSE 0 END)::bigint public_rx,
                        SUM(CASE WHEN bridge=%s THEN rx_bytes ELSE 0 END)::bigint public_tx,
                        SUM(CASE WHEN bridge=%s THEN tx_bytes ELSE 0 END)::bigint private_rx,
                        SUM(CASE WHEN bridge=%s THEN rx_bytes ELSE 0 END)::bigint private_tx,
                        LEAST(3600,COALESCE(MAX(sample_count),0)*300)::bigint coverage,
                        COALESCE(MAX(sample_count),0)::bigint samples,
                        COUNT(DISTINCT vm_uuid)::bigint vm_count,MAX(last_push)::bigint last_push
                      FROM vm_consumption_hourly WHERE hour_start >= %s
                      GROUP BY hour_start,node
                    )
                    INSERT INTO node_consumption_hourly(
                      hour_start,node,vm_public_rx_bytes,vm_public_tx_bytes,
                      vm_private_rx_bytes,vm_private_tx_bytes,
                      vm_coverage_seconds,vm_sample_count,vm_count,last_push)
                    SELECT hour_start,node,public_rx,public_tx,private_rx,private_tx,
                           coverage,samples,vm_count,last_push FROM compact
                    ON CONFLICT(hour_start,node) DO UPDATE SET
                      vm_public_rx_bytes=EXCLUDED.vm_public_rx_bytes,
                      vm_public_tx_bytes=EXCLUDED.vm_public_tx_bytes,
                      vm_private_rx_bytes=EXCLUDED.vm_private_rx_bytes,
                      vm_private_tx_bytes=EXCLUDED.vm_private_tx_bytes,
                      vm_coverage_seconds=EXCLUDED.vm_coverage_seconds,
                      vm_sample_count=EXCLUDED.vm_sample_count,vm_count=EXCLUDED.vm_count,
                      last_push=GREATEST(node_consumption_hourly.last_push,EXCLUDED.last_push)
                    """,
                    (public_bridge, public_bridge, private_bridge, private_bridge, cutoff),
                )
                counts["vm_node_hourly_rows"] = max(0, int(cursor.rowcount or 0))

                # Physical daily columns are derived from compact node hourly
                # rows, never from per-VM tables.
                cursor.execute(
                    """
                    WITH compact AS (
                      SELECT (((hour_start+%s)/86400)*86400-%s)::bigint day_start,node,
                        SUM(physical_public_rx_bytes)::bigint public_rx,
                        SUM(physical_public_tx_bytes)::bigint public_tx,
                        SUM(physical_private_rx_bytes)::bigint private_rx,
                        SUM(physical_private_tx_bytes)::bigint private_tx,
                        LEAST(86400,SUM(physical_coverage_seconds))::bigint coverage,
                        SUM(physical_sample_count)::bigint samples,MAX(last_push)::bigint last_push
                      FROM node_consumption_hourly WHERE hour_start >= %s
                      GROUP BY 1,node
                    )
                    INSERT INTO node_consumption_daily(
                      day_start,node,physical_public_rx_bytes,physical_public_tx_bytes,
                      physical_private_rx_bytes,physical_private_tx_bytes,
                      coverage_seconds,sample_count,physical_coverage_seconds,physical_sample_count,last_push)
                    SELECT day_start,node,public_rx,public_tx,private_rx,private_tx,
                           coverage,samples,coverage,samples,last_push FROM compact
                    ON CONFLICT(day_start,node) DO UPDATE SET
                      physical_public_rx_bytes=EXCLUDED.physical_public_rx_bytes,
                      physical_public_tx_bytes=EXCLUDED.physical_public_tx_bytes,
                      physical_private_rx_bytes=EXCLUDED.physical_private_rx_bytes,
                      physical_private_tx_bytes=EXCLUDED.physical_private_tx_bytes,
                      coverage_seconds=EXCLUDED.coverage_seconds,sample_count=EXCLUDED.sample_count,
                      physical_coverage_seconds=EXCLUDED.physical_coverage_seconds,
                      physical_sample_count=EXCLUDED.physical_sample_count,
                      last_push=GREATEST(node_consumption_daily.last_push,EXCLUDED.last_push)
                    """,
                    (timezone_offset, timezone_offset, first_day),
                )
                counts["physical_daily_rows"] = max(0, int(cursor.rowcount or 0))

                cursor.execute(
                    """
                    WITH compact AS (
                      SELECT day_start,node,
                        SUM(CASE WHEN bridge=%s THEN tx_bytes ELSE 0 END)::bigint public_rx,
                        SUM(CASE WHEN bridge=%s THEN rx_bytes ELSE 0 END)::bigint public_tx,
                        SUM(CASE WHEN bridge=%s THEN tx_bytes ELSE 0 END)::bigint private_rx,
                        SUM(CASE WHEN bridge=%s THEN rx_bytes ELSE 0 END)::bigint private_tx,
                        LEAST(86400,COALESCE(MAX(sample_count),0)*300)::bigint coverage,
                        COALESCE(MAX(sample_count),0)::bigint samples,
                        COUNT(DISTINCT vm_uuid)::bigint vm_count,MAX(last_push)::bigint last_push
                      FROM vm_consumption_daily WHERE day_start >= %s
                      GROUP BY day_start,node
                    )
                    INSERT INTO node_consumption_daily(
                      day_start,node,vm_public_rx_bytes,vm_public_tx_bytes,
                      vm_private_rx_bytes,vm_private_tx_bytes,
                      vm_coverage_seconds,vm_sample_count,vm_count,last_push)
                    SELECT day_start,node,public_rx,public_tx,private_rx,private_tx,
                           coverage,samples,vm_count,last_push FROM compact
                    ON CONFLICT(day_start,node) DO UPDATE SET
                      vm_public_rx_bytes=EXCLUDED.vm_public_rx_bytes,
                      vm_public_tx_bytes=EXCLUDED.vm_public_tx_bytes,
                      vm_private_rx_bytes=EXCLUDED.vm_private_rx_bytes,
                      vm_private_tx_bytes=EXCLUDED.vm_private_tx_bytes,
                      vm_coverage_seconds=EXCLUDED.vm_coverage_seconds,
                      vm_sample_count=EXCLUDED.vm_sample_count,vm_count=EXCLUDED.vm_count,
                      last_push=GREATEST(node_consumption_daily.last_push,EXCLUDED.last_push)
                    """,
                    (public_bridge, public_bridge, private_bridge, private_bridge, first_day),
                )
                counts["vm_node_daily_rows"] = max(0, int(cursor.rowcount or 0))

        return {"ok": True, "hours": hours, "raw_edge_hours": min(hours, RAW_EDGE_HOURS), **counts}
    finally:
        conn.close()

BACKFILL_STATUS_KEY = "consumption_backfill_status_r22"
BACKFILL_STATES = ("pending", "running", "completed", "completed_with_gaps", "failed")

def _write_backfill_status(payload: dict[str, Any]) -> None:
    value = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    conn = dedicated_connection(
        application_name="virtinfra-consumption-backfill-status-r22",
        statement_timeout_ms=30_000,
        lock_timeout_ms=5_000,
    )
    try:
        with conn.transaction():
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO admin_settings(key,value,updated_at)
                    VALUES (%s,%s,%s)
                    ON CONFLICT(key) DO UPDATE SET
                      value=EXCLUDED.value,
                      updated_at=EXCLUDED.updated_at
                    """,
                    (BACKFILL_STATUS_KEY, value, int(time.time())),
                )
    finally:
        conn.close()

def _backfill_progress(hours: int, started_at: int) -> tuple[int, int, int]:
    now = int(time.time())
    cutoff = now - hours * 3600
    raw_cutoff = max(cutoff, now - RAW_EDGE_HOURS * 3600)
    expected_raw = max(0, (now - raw_cutoff + 299) // 300)
    expected_hourly = max(1, hours)
    expected_daily = max(1, (hours + 23) // 24 + 1)
    expected = expected_raw + expected_hourly + expected_daily
    conn = dedicated_connection(
        application_name="virtinfra-consumption-backfill-progress-r22",
        statement_timeout_ms=60_000,
        lock_timeout_ms=5_000,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(DISTINCT bucket_start) FROM node_consumption_5m WHERE bucket_start >= %s",
                (raw_cutoff,),
            )
            raw_done = int((cursor.fetchone() or (0,))[0] or 0)
            cursor.execute(
                "SELECT COUNT(DISTINCT hour_start) FROM node_consumption_hourly WHERE hour_start >= %s",
                (cutoff,),
            )
            hourly_done = int((cursor.fetchone() or (0,))[0] or 0)
            cursor.execute(
                "SELECT COUNT(DISTINCT day_start) FROM node_consumption_daily WHERE day_start >= %s",
                (local_day_start(cutoff, int(os.environ.get("BW_RETENTION_TZ_OFFSET_SECONDS", "25200") or 25200)),),
            )
            daily_done = int((cursor.fetchone() or (0,))[0] or 0)
            cursor.execute(
                """
                SELECT COUNT(*)
                  FROM node_consumption_hourly
                 WHERE hour_start >= %s
                   AND (COALESCE(physical_coverage_seconds,0)<=0 OR COALESCE(vm_coverage_seconds,0)<=0)
                """,
                (cutoff,),
            )
            gap_rows = int((cursor.fetchone() or (0,))[0] or 0)
        return expected, raw_done + hourly_done + daily_done, gap_rows
    finally:
        conn.close()

def backfill(hours: int) -> dict[str, Any]:
    hours = max(1, min(MAX_BACKFILL_HOURS, int(hours)))
    started_at = int(time.time())
    range_start = started_at - hours * 3600
    running = {
        "state": "running",
        "started_at": started_at,
        "finished_at": 0,
        "range_start": range_start,
        "range_end": started_at,
        "expected_buckets": min(hours, RAW_EDGE_HOURS) * 12 + hours + max(1, (hours + 23) // 24 + 1),
        "processed_buckets": 0,
        "processed_rows": 0,
        "skipped_rows": 0,
        "last_error": "",
    }
    _write_backfill_status(running)
    try:
        result = _backfill_impl(hours)
        expected, processed, gap_rows = _backfill_progress(hours, started_at)
        finished_at = int(time.time())
        processed_rows = sum(
            int(value or 0)
            for key, value in result.items()
            if key.endswith("_rows")
        )
        missing_buckets = max(0, expected - processed)
        state = "completed_with_gaps" if gap_rows > 0 or missing_buckets > 0 else "completed"
        status = {
            **running,
            "state": state,
            "finished_at": finished_at,
            "expected_buckets": expected,
            "processed_buckets": processed,
            "processed_rows": processed_rows,
            "skipped_rows": gap_rows + missing_buckets,
        }
        _write_backfill_status(status)
        return {**result, "backfill_status": status}
    except Exception as exc:
        failed = {
            **running,
            "state": "failed",
            "finished_at": int(time.time()),
            "last_error": str(exc)[:2000],
        }
        try:
            _write_backfill_status(failed)
        except Exception:
            pass
        raise

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=168)
    args = parser.parse_args()
    print(json.dumps(backfill(args.hours), sort_keys=True, separators=(",", ":")), flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
