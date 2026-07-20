#!/usr/bin/env python3
"""Backfill recent physical Consumption rollups without importing Flask runtime."""

from __future__ import annotations

import argparse
import json
import os
import time

from maintenance_native import advisory_xact_lock, dedicated_connection

ROLLUP_LOCK = "virtinfra-consumption-backfill"


def local_day_start(ts: int, offset: int) -> int:
    return ((int(ts) + int(offset)) // 86400) * 86400 - int(offset)


def backfill(hours: int) -> dict[str, object]:
    hours = max(1, min(24 * 8, int(hours)))
    now = int(time.time())
    cutoff = now - hours * 3600
    offset = int(os.environ.get("BW_RETENTION_TZ_OFFSET_SECONDS", "25200") or 25200)
    first_day = local_day_start(cutoff, offset)

    conn = dedicated_connection(
        application_name="virtinfra-consumption-rollup",
        statement_timeout_ms=20 * 60 * 1000,
        lock_timeout_ms=5_000,
    )
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                advisory_xact_lock(cur, ROLLUP_LOCK)
                cur.execute(
                    """
                    WITH per_bucket AS (
                      SELECT
                        (((CAST(p.time AS BIGINT)+%s)/3600)*3600-%s)::bigint AS hour_start,
                        p.node,p.bucket,
                        SUM(CASE WHEN LOWER(COALESCE(p.role,''))='public' THEN p.rx_delta ELSE 0 END)::bigint AS public_rx,
                        SUM(CASE WHEN LOWER(COALESCE(p.role,''))='public' THEN p.tx_delta ELSE 0 END)::bigint AS public_tx,
                        SUM(CASE WHEN LOWER(COALESCE(p.role,''))='private' THEN p.rx_delta ELSE 0 END)::bigint AS private_rx,
                        SUM(CASE WHEN LOWER(COALESCE(p.role,''))='private' THEN p.tx_delta ELSE 0 END)::bigint AS private_tx,
                        MAX(COALESCE(p.interval_seconds,300))::bigint AS coverage_seconds,
                        MAX(COALESCE(p.last_push,p.time))::bigint AS last_push
                      FROM node_physical_net_stats p
                      WHERE p.time>=%s
                      GROUP BY 1,p.node,p.bucket
                    ), hourly AS (
                      SELECT hour_start,node,
                        SUM(public_rx)::bigint public_rx,SUM(public_tx)::bigint public_tx,
                        SUM(private_rx)::bigint private_rx,SUM(private_tx)::bigint private_tx,
                        LEAST(3600,SUM(coverage_seconds))::bigint coverage_seconds,
                        COUNT(*)::bigint sample_count,MAX(last_push)::bigint last_push
                      FROM per_bucket GROUP BY hour_start,node
                    )
                    INSERT INTO node_consumption_hourly(
                      hour_start,node,
                      physical_public_rx_bytes,physical_public_tx_bytes,
                      physical_private_rx_bytes,physical_private_tx_bytes,
                      coverage_seconds,sample_count,last_push
                    )
                    SELECT hour_start,node,public_rx,public_tx,private_rx,private_tx,
                           coverage_seconds,sample_count,last_push FROM hourly
                    ON CONFLICT(hour_start,node) DO UPDATE SET
                      physical_public_rx_bytes=excluded.physical_public_rx_bytes,
                      physical_public_tx_bytes=excluded.physical_public_tx_bytes,
                      physical_private_rx_bytes=excluded.physical_private_rx_bytes,
                      physical_private_tx_bytes=excluded.physical_private_tx_bytes,
                      coverage_seconds=excluded.coverage_seconds,
                      sample_count=excluded.sample_count,
                      last_push=excluded.last_push
                    """,
                    (offset, offset, cutoff),
                )
                hourly_rows = max(0, int(cur.rowcount or 0))
                cur.execute(
                    """
                    WITH daily AS (
                      SELECT (((hour_start+%s)/86400)*86400-%s)::bigint AS day_start,node,
                        SUM(physical_public_rx_bytes)::bigint public_rx,
                        SUM(physical_public_tx_bytes)::bigint public_tx,
                        SUM(physical_private_rx_bytes)::bigint private_rx,
                        SUM(physical_private_tx_bytes)::bigint private_tx,
                        LEAST(86400,SUM(coverage_seconds))::bigint coverage_seconds,
                        SUM(sample_count)::bigint sample_count,
                        MAX(last_push)::bigint last_push
                      FROM node_consumption_hourly
                      WHERE hour_start>=%s
                      GROUP BY 1,node
                    )
                    INSERT INTO node_consumption_daily(
                      day_start,node,
                      physical_public_rx_bytes,physical_public_tx_bytes,
                      physical_private_rx_bytes,physical_private_tx_bytes,
                      coverage_seconds,sample_count,last_push
                    )
                    SELECT day_start,node,public_rx,public_tx,private_rx,private_tx,
                           coverage_seconds,sample_count,last_push FROM daily
                    ON CONFLICT(day_start,node) DO UPDATE SET
                      physical_public_rx_bytes=excluded.physical_public_rx_bytes,
                      physical_public_tx_bytes=excluded.physical_public_tx_bytes,
                      physical_private_rx_bytes=excluded.physical_private_rx_bytes,
                      physical_private_tx_bytes=excluded.physical_private_tx_bytes,
                      coverage_seconds=excluded.coverage_seconds,
                      sample_count=excluded.sample_count,
                      last_push=excluded.last_push
                    """,
                    (offset, offset, first_day),
                )
                daily_rows = max(0, int(cur.rowcount or 0))
        return {"ok": True, "hours": hours, "hourly_rows": hourly_rows, "daily_rows": daily_rows}
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=48)
    args = parser.parse_args()
    print(json.dumps(backfill(args.hours), sort_keys=True, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
