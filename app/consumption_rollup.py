#!/usr/bin/env python3
"""Backfill compact Physical and All-VM-per-Node Consumption rollups."""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any

from maintenance_native import advisory_xact_lock, dedicated_connection

ROLLUP_LOCK = "virtinfra-consumption-backfill"
MAX_BACKFILL_HOURS = 24 * 8


def local_day_start(timestamp: int, offset_seconds: int) -> int:
    """Return the local-day boundary expressed as a UTC epoch timestamp."""
    return (
        ((int(timestamp) + int(offset_seconds)) // 86400) * 86400
        - int(offset_seconds)
    )


def backfill(hours: int) -> dict[str, Any]:
    """Rebuild recent compact Consumption rollups from retained source tables."""
    hours = max(1, min(MAX_BACKFILL_HOURS, int(hours)))
    now = int(time.time())
    cutoff = now - hours * 3600
    timezone_offset = int(
        os.environ.get("BW_RETENTION_TZ_OFFSET_SECONDS", "25200") or 25200
    )
    public_bridge = str(os.environ.get("BW_PUBLIC_BRIDGE") or "br0").strip()
    private_bridge = str(os.environ.get("BW_PRIVATE_BRIDGE") or "br1").strip()
    first_day = local_day_start(now - MAX_BACKFILL_HOURS * 3600, timezone_offset)

    conn = dedicated_connection(
        application_name="virtinfra-consumption-rollup",
        statement_timeout_ms=30 * 60 * 1000,
        lock_timeout_ms=5000,
    )
    try:
        with conn.transaction():
            with conn.cursor() as cursor:
                advisory_xact_lock(cursor, ROLLUP_LOCK)

                cursor.execute(
                    """
                    WITH per_bucket AS (
                      SELECT
                        (((CAST(p.time AS BIGINT) + %s) / 3600) * 3600 - %s)::bigint
                          AS hour_start,
                        p.node,
                        p.bucket,
                        SUM(CASE WHEN LOWER(COALESCE(p.role, '')) = 'public'
                                 THEN p.rx_delta ELSE 0 END)::bigint AS public_rx,
                        SUM(CASE WHEN LOWER(COALESCE(p.role, '')) = 'public'
                                 THEN p.tx_delta ELSE 0 END)::bigint AS public_tx,
                        SUM(CASE WHEN LOWER(COALESCE(p.role, '')) = 'private'
                                 THEN p.rx_delta ELSE 0 END)::bigint AS private_rx,
                        SUM(CASE WHEN LOWER(COALESCE(p.role, '')) = 'private'
                                 THEN p.tx_delta ELSE 0 END)::bigint AS private_tx,
                        MAX(COALESCE(p.interval_seconds, 300))::bigint
                          AS coverage_seconds,
                        MAX(COALESCE(p.last_push, p.time))::bigint AS last_push
                      FROM node_physical_net_stats p
                      WHERE p.time >= %s
                      GROUP BY 1, p.node, p.bucket
                    ), hourly AS (
                      SELECT
                        hour_start,
                        node,
                        SUM(public_rx)::bigint AS public_rx,
                        SUM(public_tx)::bigint AS public_tx,
                        SUM(private_rx)::bigint AS private_rx,
                        SUM(private_tx)::bigint AS private_tx,
                        LEAST(3600, SUM(coverage_seconds))::bigint AS coverage_seconds,
                        COUNT(*)::bigint AS sample_count,
                        MAX(last_push)::bigint AS last_push
                      FROM per_bucket
                      GROUP BY hour_start, node
                    )
                    INSERT INTO node_consumption_hourly (
                      hour_start,
                      node,
                      physical_public_rx_bytes,
                      physical_public_tx_bytes,
                      physical_private_rx_bytes,
                      physical_private_tx_bytes,
                      coverage_seconds,
                      sample_count,
                      last_push
                    )
                    SELECT
                      hour_start,
                      node,
                      public_rx,
                      public_tx,
                      private_rx,
                      private_tx,
                      coverage_seconds,
                      sample_count,
                      last_push
                    FROM hourly
                    ON CONFLICT (hour_start, node) DO UPDATE SET
                      physical_public_rx_bytes = EXCLUDED.physical_public_rx_bytes,
                      physical_public_tx_bytes = EXCLUDED.physical_public_tx_bytes,
                      physical_private_rx_bytes = EXCLUDED.physical_private_rx_bytes,
                      physical_private_tx_bytes = EXCLUDED.physical_private_tx_bytes,
                      coverage_seconds = EXCLUDED.coverage_seconds,
                      sample_count = EXCLUDED.sample_count,
                      last_push = EXCLUDED.last_push
                    """,
                    (timezone_offset, timezone_offset, cutoff),
                )
                physical_hourly_rows = max(0, int(cursor.rowcount or 0))

                cursor.execute(
                    """
                    WITH daily AS (
                      SELECT
                        (((hour_start + %s) / 86400) * 86400 - %s)::bigint
                          AS day_start,
                        node,
                        SUM(physical_public_rx_bytes)::bigint AS public_rx,
                        SUM(physical_public_tx_bytes)::bigint AS public_tx,
                        SUM(physical_private_rx_bytes)::bigint AS private_rx,
                        SUM(physical_private_tx_bytes)::bigint AS private_tx,
                        LEAST(86400, SUM(coverage_seconds))::bigint
                          AS coverage_seconds,
                        SUM(sample_count)::bigint AS sample_count,
                        MAX(last_push)::bigint AS last_push
                      FROM node_consumption_hourly
                      WHERE hour_start >= %s
                      GROUP BY 1, node
                    )
                    INSERT INTO node_consumption_daily (
                      day_start,
                      node,
                      physical_public_rx_bytes,
                      physical_public_tx_bytes,
                      physical_private_rx_bytes,
                      physical_private_tx_bytes,
                      coverage_seconds,
                      sample_count,
                      last_push
                    )
                    SELECT
                      day_start,
                      node,
                      public_rx,
                      public_tx,
                      private_rx,
                      private_tx,
                      coverage_seconds,
                      sample_count,
                      last_push
                    FROM daily
                    ON CONFLICT (day_start, node) DO UPDATE SET
                      physical_public_rx_bytes = EXCLUDED.physical_public_rx_bytes,
                      physical_public_tx_bytes = EXCLUDED.physical_public_tx_bytes,
                      physical_private_rx_bytes = EXCLUDED.physical_private_rx_bytes,
                      physical_private_tx_bytes = EXCLUDED.physical_private_tx_bytes,
                      coverage_seconds = EXCLUDED.coverage_seconds,
                      sample_count = EXCLUDED.sample_count,
                      last_push = EXCLUDED.last_push
                    """,
                    (timezone_offset, timezone_offset, first_day),
                )
                physical_daily_rows = max(0, int(cursor.rowcount or 0))

                # bandwidth_hourly/daily store host-tap direction. Convert to
                # guest perspective while compacting every VM into one Node row.
                cursor.execute(
                    """
                    WITH hourly AS (
                      SELECT
                        hour_start,
                        node,
                        SUM(CASE WHEN bridge = %s THEN tx_bytes ELSE 0 END)::bigint
                          AS public_rx,
                        SUM(CASE WHEN bridge = %s THEN rx_bytes ELSE 0 END)::bigint
                          AS public_tx,
                        SUM(CASE WHEN bridge = %s THEN tx_bytes ELSE 0 END)::bigint
                          AS private_rx,
                        SUM(CASE WHEN bridge = %s THEN rx_bytes ELSE 0 END)::bigint
                          AS private_tx,
                        LEAST(3600, COALESCE(MAX(sample_count), 0) * 300)::bigint
                          AS coverage_seconds,
                        COALESCE(MAX(sample_count), 0)::bigint AS sample_count,
                        COUNT(DISTINCT vm_uuid)::bigint AS vm_count,
                        MAX(last_push)::bigint AS last_push
                      FROM bandwidth_hourly
                      WHERE hour_start >= %s
                      GROUP BY hour_start, node
                    )
                    INSERT INTO node_vm_consumption_hourly (
                      hour_start,
                      node,
                      vm_public_rx_bytes,
                      vm_public_tx_bytes,
                      vm_private_rx_bytes,
                      vm_private_tx_bytes,
                      coverage_seconds,
                      sample_count,
                      vm_count,
                      last_push
                    )
                    SELECT
                      hour_start,
                      node,
                      public_rx,
                      public_tx,
                      private_rx,
                      private_tx,
                      coverage_seconds,
                      sample_count,
                      vm_count,
                      last_push
                    FROM hourly
                    ON CONFLICT (hour_start, node) DO UPDATE SET
                      vm_public_rx_bytes = EXCLUDED.vm_public_rx_bytes,
                      vm_public_tx_bytes = EXCLUDED.vm_public_tx_bytes,
                      vm_private_rx_bytes = EXCLUDED.vm_private_rx_bytes,
                      vm_private_tx_bytes = EXCLUDED.vm_private_tx_bytes,
                      coverage_seconds = EXCLUDED.coverage_seconds,
                      sample_count = EXCLUDED.sample_count,
                      vm_count = EXCLUDED.vm_count,
                      last_push = EXCLUDED.last_push
                    """,
                    (
                        public_bridge,
                        public_bridge,
                        private_bridge,
                        private_bridge,
                        cutoff,
                    ),
                )
                vm_node_hourly_rows = max(0, int(cursor.rowcount or 0))

                cursor.execute(
                    """
                    WITH daily AS (
                      SELECT
                        day_start,
                        node,
                        SUM(CASE WHEN bridge = %s THEN tx_bytes ELSE 0 END)::bigint
                          AS public_rx,
                        SUM(CASE WHEN bridge = %s THEN rx_bytes ELSE 0 END)::bigint
                          AS public_tx,
                        SUM(CASE WHEN bridge = %s THEN tx_bytes ELSE 0 END)::bigint
                          AS private_rx,
                        SUM(CASE WHEN bridge = %s THEN rx_bytes ELSE 0 END)::bigint
                          AS private_tx,
                        LEAST(86400, COALESCE(MAX(sample_count), 0) * 300)::bigint
                          AS coverage_seconds,
                        COALESCE(MAX(sample_count), 0)::bigint AS sample_count,
                        COUNT(DISTINCT vm_uuid)::bigint AS vm_count,
                        MAX(last_push)::bigint AS last_push
                      FROM bandwidth_daily
                      WHERE day_start >= %s
                      GROUP BY day_start, node
                    )
                    INSERT INTO node_vm_consumption_daily (
                      day_start,
                      node,
                      vm_public_rx_bytes,
                      vm_public_tx_bytes,
                      vm_private_rx_bytes,
                      vm_private_tx_bytes,
                      coverage_seconds,
                      sample_count,
                      vm_count,
                      last_push
                    )
                    SELECT
                      day_start,
                      node,
                      public_rx,
                      public_tx,
                      private_rx,
                      private_tx,
                      coverage_seconds,
                      sample_count,
                      vm_count,
                      last_push
                    FROM daily
                    ON CONFLICT (day_start, node) DO UPDATE SET
                      vm_public_rx_bytes = EXCLUDED.vm_public_rx_bytes,
                      vm_public_tx_bytes = EXCLUDED.vm_public_tx_bytes,
                      vm_private_rx_bytes = EXCLUDED.vm_private_rx_bytes,
                      vm_private_tx_bytes = EXCLUDED.vm_private_tx_bytes,
                      coverage_seconds = EXCLUDED.coverage_seconds,
                      sample_count = EXCLUDED.sample_count,
                      vm_count = EXCLUDED.vm_count,
                      last_push = EXCLUDED.last_push
                    """,
                    (
                        public_bridge,
                        public_bridge,
                        private_bridge,
                        private_bridge,
                        first_day,
                    ),
                )
                vm_node_daily_rows = max(0, int(cursor.rowcount or 0))

        return {
            "ok": True,
            "hours": hours,
            "physical_hourly_rows": physical_hourly_rows,
            "physical_daily_rows": physical_daily_rows,
            "vm_node_hourly_rows": vm_node_hourly_rows,
            "vm_node_daily_rows": vm_node_daily_rows,
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=48)
    args = parser.parse_args()
    print(
        json.dumps(backfill(args.hours), sort_keys=True, separators=(",", ":")),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
