

def local_hour_start(ts):
    return ((int(ts) + RETENTION_TZ_OFFSET_SECONDS) // 3600) * 3600 - RETENTION_TZ_OFFSET_SECONDS


def local_day_start(ts):
    return ((int(ts) + RETENTION_TZ_OFFSET_SECONDS) // 86400) * 86400 - RETENTION_TZ_OFFSET_SECONDS


def add_bandwidth_rollup(conn, data_time, node, vm_uuid, bridge,
                         rx_delta, tx_delta, rx_packets_delta, tx_packets_delta,
                         rx_drop_delta, tx_drop_delta, rx_error_delta, tx_error_delta):
    hour_start = local_hour_start(data_time)
    day_start = local_day_start(data_time)
    values = (
        node, vm_uuid, bridge,
        rx_delta, tx_delta, rx_packets_delta, tx_packets_delta,
        rx_drop_delta, tx_drop_delta, rx_error_delta, tx_error_delta,
        data_time,
    )
    conn.execute("""
        INSERT INTO bandwidth_hourly(
            hour_start, node, vm_uuid, bridge,
            rx_bytes, tx_bytes, rx_packets, tx_packets,
            rx_drops, tx_drops, rx_errors, tx_errors,
            sample_count, last_push
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(hour_start, node, vm_uuid, bridge)
        DO UPDATE SET
            rx_bytes=bandwidth_hourly.rx_bytes + excluded.rx_bytes,
            tx_bytes=bandwidth_hourly.tx_bytes + excluded.tx_bytes,
            rx_packets=bandwidth_hourly.rx_packets + excluded.rx_packets,
            tx_packets=bandwidth_hourly.tx_packets + excluded.tx_packets,
            rx_drops=bandwidth_hourly.rx_drops + excluded.rx_drops,
            tx_drops=bandwidth_hourly.tx_drops + excluded.tx_drops,
            rx_errors=bandwidth_hourly.rx_errors + excluded.rx_errors,
            tx_errors=bandwidth_hourly.tx_errors + excluded.tx_errors,
            sample_count=bandwidth_hourly.sample_count + 1,
            last_push=MAX(bandwidth_hourly.last_push, excluded.last_push)
    """, (hour_start,) + values)
    conn.execute("""
        INSERT INTO bandwidth_daily(
            day_start, node, vm_uuid, bridge,
            rx_bytes, tx_bytes, rx_packets, tx_packets,
            rx_drops, tx_drops, rx_errors, tx_errors,
            sample_count, last_push
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(day_start, node, vm_uuid, bridge)
        DO UPDATE SET
            rx_bytes=bandwidth_daily.rx_bytes + excluded.rx_bytes,
            tx_bytes=bandwidth_daily.tx_bytes + excluded.tx_bytes,
            rx_packets=bandwidth_daily.rx_packets + excluded.rx_packets,
            tx_packets=bandwidth_daily.tx_packets + excluded.tx_packets,
            rx_drops=bandwidth_daily.rx_drops + excluded.rx_drops,
            tx_drops=bandwidth_daily.tx_drops + excluded.tx_drops,
            rx_errors=bandwidth_daily.rx_errors + excluded.rx_errors,
            tx_errors=bandwidth_daily.tx_errors + excluded.tx_errors,
            sample_count=bandwidth_daily.sample_count + 1,
            last_push=MAX(bandwidth_daily.last_push, excluded.last_push)
    """, (day_start,) + values)


def _delete_in_batches(conn, table, where_sql, params, batch_rows=RETENTION_BATCH_ROWS):
    total = 0
    while True:
        cur = conn.execute(f"""
            DELETE FROM {table}
            WHERE rowid IN (
                SELECT rowid FROM {table}
                WHERE {where_sql}
                LIMIT ?
            )
        """, tuple(params) + (int(batch_rows),))
        changed = max(0, int(cur.rowcount or 0))
        conn.commit()
        total += changed
        if changed < batch_rows:
            break
    return total


def _rollup_and_delete_legacy_usage(conn, raw_cutoff):
    """Atomically roll legacy usage into billing tables, one local hour at a time.

    Each hour chunk is added to hourly/daily totals and deleted from usage in the
    same PostgreSQL transaction. A crash therefore cannot leave a committed rollup
    without the matching raw deletion, and reruns cannot double count it.
    """
    total_deleted = 0
    while True:
        row = conn.execute(
            "SELECT MIN(time) FROM usage WHERE time<?", (int(raw_cutoff),)
        ).fetchone()
        oldest = safe_int(row[0], 0) if row else 0
        if oldest <= 0:
            break

        hour_start = local_hour_start(oldest)
        chunk_end = min(int(raw_cutoff), int(hour_start) + 3600)
        if chunk_end <= oldest:
            chunk_end = min(int(raw_cutoff), oldest + 1)

        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("""
                INSERT INTO bandwidth_hourly(
                    hour_start, node, vm_uuid, bridge,
                    rx_bytes, tx_bytes, rx_packets, tx_packets,
                    rx_drops, tx_drops, rx_errors, tx_errors,
                    sample_count, last_push
                )
                SELECT ?, node, vm_uuid, COALESCE(NULLIF(bridge,''), '-'),
                       SUM(MAX(rx_delta,0)), SUM(MAX(tx_delta,0)),
                       SUM(MAX(rx_packets_delta,0)), SUM(MAX(tx_packets_delta,0)),
                       SUM(MAX(rx_drop_delta,0)), SUM(MAX(tx_drop_delta,0)),
                       SUM(MAX(rx_error_delta,0)), SUM(MAX(tx_error_delta,0)),
                       COUNT(*), MAX(time)
                FROM usage
                WHERE time>=? AND time<?
                GROUP BY node, vm_uuid, COALESCE(NULLIF(bridge,''), '-')
                ON CONFLICT(hour_start, node, vm_uuid, bridge)
                DO UPDATE SET
                    rx_bytes=bandwidth_hourly.rx_bytes + excluded.rx_bytes,
                    tx_bytes=bandwidth_hourly.tx_bytes + excluded.tx_bytes,
                    rx_packets=bandwidth_hourly.rx_packets + excluded.rx_packets,
                    tx_packets=bandwidth_hourly.tx_packets + excluded.tx_packets,
                    rx_drops=bandwidth_hourly.rx_drops + excluded.rx_drops,
                    tx_drops=bandwidth_hourly.tx_drops + excluded.tx_drops,
                    rx_errors=bandwidth_hourly.rx_errors + excluded.rx_errors,
                    tx_errors=bandwidth_hourly.tx_errors + excluded.tx_errors,
                    sample_count=bandwidth_hourly.sample_count + excluded.sample_count,
                    last_push=MAX(bandwidth_hourly.last_push, excluded.last_push)
            """, (hour_start, hour_start, chunk_end))

            day_start = local_day_start(hour_start)
            conn.execute("""
                INSERT INTO bandwidth_daily(
                    day_start, node, vm_uuid, bridge,
                    rx_bytes, tx_bytes, rx_packets, tx_packets,
                    rx_drops, tx_drops, rx_errors, tx_errors,
                    sample_count, last_push
                )
                SELECT ?, node, vm_uuid, COALESCE(NULLIF(bridge,''), '-'),
                       SUM(MAX(rx_delta,0)), SUM(MAX(tx_delta,0)),
                       SUM(MAX(rx_packets_delta,0)), SUM(MAX(tx_packets_delta,0)),
                       SUM(MAX(rx_drop_delta,0)), SUM(MAX(tx_drop_delta,0)),
                       SUM(MAX(rx_error_delta,0)), SUM(MAX(tx_error_delta,0)),
                       COUNT(*), MAX(time)
                FROM usage
                WHERE time>=? AND time<?
                GROUP BY node, vm_uuid, COALESCE(NULLIF(bridge,''), '-')
                ON CONFLICT(day_start, node, vm_uuid, bridge)
                DO UPDATE SET
                    rx_bytes=bandwidth_daily.rx_bytes + excluded.rx_bytes,
                    tx_bytes=bandwidth_daily.tx_bytes + excluded.tx_bytes,
                    rx_packets=bandwidth_daily.rx_packets + excluded.rx_packets,
                    tx_packets=bandwidth_daily.tx_packets + excluded.tx_packets,
                    rx_drops=bandwidth_daily.rx_drops + excluded.rx_drops,
                    tx_drops=bandwidth_daily.tx_drops + excluded.tx_drops,
                    rx_errors=bandwidth_daily.rx_errors + excluded.rx_errors,
                    tx_errors=bandwidth_daily.tx_errors + excluded.tx_errors,
                    sample_count=bandwidth_daily.sample_count + excluded.sample_count,
                    last_push=MAX(bandwidth_daily.last_push, excluded.last_push)
            """, (day_start, hour_start, chunk_end))

            cur = conn.execute(
                "DELETE FROM usage WHERE time>=? AND time<?",
                (hour_start, chunk_end),
            )
            changed = max(0, int(cur.rowcount or 0))
            conn.commit()
            total_deleted += changed
        except Exception:
            conn.rollback()
            raise
    return total_deleted



def delete_history_older_than(days):
    """Delete old detailed metrics while preserving billing/latest state."""
    allowed_days = {1, 3, 7}
    days = safe_int(days, 0)
    if days not in allowed_days:
        raise ValueError("Unsupported history age")
    cutoff = bucket_for(now_ts() - days * 86400)
    deleted = {}
    conn = db()
    try:
        # Legacy filesystem rows may have bucket=0. Populate it before filtering.
        conn.execute("""
            UPDATE node_filesystem_stats
            SET bucket=(CAST(time AS INTEGER) / ?) * ?
            WHERE COALESCE(bucket,0)=0
        """, (CACHE_BUCKET_SECONDS, CACHE_BUCKET_SECONDS))
        conn.commit()
        deleted["usage"] = _rollup_and_delete_legacy_usage(conn, cutoff)
        for table in ("node_stats", "vm_perf_stats", "node_host_stats", "node_physical_net_stats", "agent_health_stats", "node_filesystem_stats"):
            deleted[table] = _delete_in_batches(conn, table, "bucket<?", (cutoff,))
        deleted["node_push_snapshots"] = _delete_in_batches(conn, "node_push_snapshots", "bucket<?", (cutoff,))
        deleted["push_receipts"] = _delete_in_batches(conn, "push_receipts", "received_at<?", (cutoff,))
        conn.execute("PRAGMA optimize")
        conn.commit()
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except dbapi.Error:
            pass
        return {"days": days, "cutoff": cutoff, "deleted": deleted, "total_deleted": sum(safe_int(v, 0) for v in deleted.values())}
    finally:
        conn.close()


def run_retention(dry_run=False):
    """Apply exact-snapshot tiering and preserve exact billing totals.

    raw: every real 5-minute push for the latest 48 hours
    hourly: one real push per local hour from 48 hours through day 7
    older than 7 days: historical metric, bandwidth and log/event rows are deleted
    current state, inventory, users, settings and API keys are preserved.
    """
    started = now_ts()
    raw_cutoff = bucket_for(started - RAW_RETENTION_DAYS * 86400)
    hourly_cutoff = bucket_for(started - HOURLY_RETENTION_DAYS * 86400)
    stats = {"raw_cutoff": raw_cutoff, "hourly_cutoff": hourly_cutoff, "deleted": {}}
    conn = db()
    try:
        run_id = None
        if not dry_run:
            cur = conn.execute("""
                INSERT INTO retention_runs(started_at, status, raw_cutoff, hourly_cutoff, detail)
                VALUES (?, 'running', ?, ?, '')
            """, (started, raw_cutoff, hourly_cutoff))
            run_id = cur.lastrowid
            conn.commit()

        # Backfill the compact node/bucket index once when upgrading from an
        # older release. New pushes already populate node_push_snapshots, so
        # rescanning every VM/interface metric table on every retention run
        # would be wasteful at large scale.
        marker = conn.execute(
            "SELECT value FROM admin_settings WHERE key='retention_snapshot_backfill_v48125'"
        ).fetchone()
        snapshot_backfill_needed = not marker or str(marker[0] or "") != "1"
        stats["snapshot_backfill_needed"] = bool(snapshot_backfill_needed)
        if not dry_run and snapshot_backfill_needed:
            for table, last_col in (
                ("node_stats", "last_push"),
                ("vm_perf_stats", "last_push"),
                ("node_host_stats", "last_push"),
                ("node_physical_net_stats", "last_push"),
                ("agent_health_stats", "last_push"),
            ):
                conn.execute(f"""
                    INSERT OR IGNORE INTO node_push_snapshots(
                        node, bucket, push_time, last_push, vm_count, iface_count,
                        inventory_complete, retention_tier
                    )
                    SELECT node, bucket, MAX({last_col}), MAX({last_col}), 0, 0, 0, 'raw'
                    FROM {table}
                    WHERE bucket>0
                    GROUP BY node, bucket
                """)
            # Old filesystem rows did not have bucket populated.
            while True:
                cur = conn.execute("""
                    UPDATE node_filesystem_stats
                    SET bucket=(CAST(time AS INTEGER) / ?) * ?
                    WHERE rowid IN (
                        SELECT rowid FROM node_filesystem_stats
                        WHERE COALESCE(bucket, 0)=0
                        LIMIT ?
                    )
                """, (CACHE_BUCKET_SECONDS, CACHE_BUCKET_SECONDS, RETENTION_BATCH_ROWS))
                changed = max(0, int(cur.rowcount or 0))
                conn.commit()
                if changed < RETENTION_BATCH_ROWS:
                    break

        # Legacy usage is rolled up and deleted later, one local-hour chunk
        # per atomic transaction. This preserves live v47+ totals and prevents
        # duplicate billing if the retention process is interrupted.

        # Build an accurate temporary snapshot source for both --run and
        # --dry-run. This makes the very first dry-run correct even when an old
        # installation has not populated node_push_snapshots yet.
        conn.execute("DROP TABLE IF EXISTS temp.retention_snapshot_source")
        conn.execute("""
            CREATE TEMP TABLE retention_snapshot_source(
                node TEXT NOT NULL,
                bucket INTEGER NOT NULL,
                inventory_complete INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(node, bucket)
            ) WITHOUT ROWID
        """)
        conn.execute("""
            INSERT OR REPLACE INTO retention_snapshot_source(node, bucket, inventory_complete)
            SELECT node, bucket, MAX(inventory_complete)
            FROM node_push_snapshots
            WHERE bucket>0
            GROUP BY node, bucket
        """)
        # A dry-run must remain accurate on a pre-v48.12.5 database. Normal
        # recurring runs trust the compact snapshot index after the one-time
        # migration marker has been committed.
        if dry_run or snapshot_backfill_needed:
            for source_table in (
                "node_stats", "vm_perf_stats", "node_host_stats",
                "node_physical_net_stats", "agent_health_stats",
            ):
                conn.execute(f"""
                    INSERT OR IGNORE INTO retention_snapshot_source(node, bucket, inventory_complete)
                    SELECT node, bucket, 0
                    FROM {source_table}
                    WHERE bucket>0
                    GROUP BY node, bucket
                """)

        conn.execute("DROP TABLE IF EXISTS temp.retention_keep_buckets")
        conn.execute("""
            CREATE TEMP TABLE retention_keep_buckets(
                node TEXT NOT NULL,
                bucket INTEGER NOT NULL,
                tier TEXT NOT NULL,
                PRIMARY KEY(node, bucket)
            ) WITHOUT ROWID
        """)
        hour_div = 3600
        conn.execute(f"""
            INSERT OR IGNORE INTO retention_keep_buckets(node, bucket, tier)
            SELECT node, COALESCE(MIN(CASE WHEN inventory_complete=1 THEN bucket END), MIN(bucket)), 'hourly'
            FROM retention_snapshot_source
            WHERE bucket>=? AND bucket<?
            GROUP BY node, ((bucket + {RETENTION_TZ_OFFSET_SECONDS}) / {hour_div})
        """, (hourly_cutoff, raw_cutoff))
        # v48: metric snapshots older than HOURLY_RETENTION_DAYS are deleted.
        # Exact bandwidth billing in bandwidth_daily remains untouched.
        keep_count = conn.execute("SELECT COUNT(*) FROM retention_keep_buckets").fetchone()[0]
        stats["kept_sparse_buckets"] = int(keep_count or 0)

        if dry_run:
            for table in (
                "node_stats", "vm_perf_stats", "node_host_stats",
                "node_physical_net_stats", "agent_health_stats", "node_filesystem_stats",
            ):
                bucket_expr = (
                    "CASE WHEN COALESCE(t.bucket,0)>0 THEN t.bucket "
                    "ELSE (CAST(t.time AS INTEGER) / %d) * %d END"
                    % (CACHE_BUCKET_SECONDS, CACHE_BUCKET_SECONDS)
                    if table == "node_filesystem_stats" else "t.bucket"
                )
                count = conn.execute(f"""
                    SELECT COUNT(*) FROM {table} t
                    WHERE {bucket_expr}<?
                      AND NOT EXISTS (
                          SELECT 1 FROM retention_keep_buckets k
                          WHERE k.node=t.node AND k.bucket={bucket_expr}
                      )
                """, (raw_cutoff,)).fetchone()[0]
                stats["deleted"][table] = int(count or 0)
            stats["deleted"]["usage"] = int(conn.execute(
                "SELECT COUNT(*) FROM usage WHERE time<?", (raw_cutoff,)
            ).fetchone()[0] or 0)
            stats["deleted"]["bandwidth_hourly"] = int(conn.execute(
                "SELECT COUNT(*) FROM bandwidth_hourly WHERE hour_start<?", (hourly_cutoff,)
            ).fetchone()[0] or 0)
            return stats

        conn.execute("""
            UPDATE node_push_snapshots
            SET retention_tier='raw'
            WHERE bucket>=?
        """, (raw_cutoff,))
        conn.execute("""
            UPDATE node_push_snapshots
            SET retention_tier=(
                SELECT k.tier FROM retention_keep_buckets k
                WHERE k.node=node_push_snapshots.node
                  AND k.bucket=node_push_snapshots.bucket
            )
            WHERE bucket<?
              AND EXISTS (
                SELECT 1 FROM retention_keep_buckets k
                WHERE k.node=node_push_snapshots.node
                  AND k.bucket=node_push_snapshots.bucket
              )
        """, (raw_cutoff,))
        conn.commit()

        for table in (
            "node_stats", "vm_perf_stats", "node_host_stats",
            "node_physical_net_stats", "agent_health_stats", "node_filesystem_stats",
        ):
            stats["deleted"][table] = _delete_in_batches(
                conn, table,
                "bucket<? AND NOT EXISTS (SELECT 1 FROM retention_keep_buckets k WHERE k.node=" + table + ".node AND k.bucket=" + table + ".bucket)",
                (raw_cutoff,),
            )

        stats["deleted"]["usage"] = _rollup_and_delete_legacy_usage(
            conn, raw_cutoff
        )
        stats["deleted"]["node_push_snapshots"] = _delete_in_batches(
            conn, "node_push_snapshots",
            "bucket<? AND NOT EXISTS (SELECT 1 FROM retention_keep_buckets k WHERE k.node=node_push_snapshots.node AND k.bucket=node_push_snapshots.bucket)",
            (raw_cutoff,),
        )
        stats["deleted"]["push_receipts"] = _delete_in_batches(
            conn, "push_receipts", "received_at<?", (raw_cutoff,)
        )
        # Both hourly and daily bandwidth history follow the same hard 7-day
        # retention window. Current counters and inventory remain untouched.
        stats["deleted"]["bandwidth_hourly"] = _delete_in_batches(
            conn, "bandwidth_hourly", "hour_start<?", (hourly_cutoff,)
        )

        if snapshot_backfill_needed:
            conn.execute("""
                INSERT INTO admin_settings(key,value,updated_at)
                VALUES('retention_snapshot_backfill_v48125','1',?)
                ON CONFLICT(key) DO UPDATE SET value='1',updated_at=excluded.updated_at
            """, (now_ts(),))
        conn.execute("PRAGMA optimize")
        conn.commit()
        finished = now_ts()
        if run_id:
            conn.execute("""
                UPDATE retention_runs
                SET finished_at=?, status='ok', detail=?
                WHERE id=?
            """, (finished, json.dumps(stats, separators=(",", ":")), run_id))
            conn.commit()
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except dbapi.Error:
            pass
        stats["finished_at"] = finished
        return stats
    except Exception as exc:
        try:
            conn.rollback()
            conn.execute("""
                INSERT INTO retention_runs(started_at, finished_at, status, raw_cutoff, hourly_cutoff, detail)
                VALUES (?, ?, 'error', ?, ?, ?)
            """, (started, now_ts(), raw_cutoff, hourly_cutoff, str(exc)[:1000]))
            conn.commit()
        except Exception:
            pass
        raise
    finally:
        conn.close()


@app.route("/push", methods=["POST"])
def push():
    push_started = time.perf_counter()
    if not valid_agent_token(request.headers.get("X-Token", "")):
        log_node_event("bad_token", node="", status_code=401, detail="invalid X-Token")
        return {"error": "unauthorized"}, 401

    try:
        data = read_agent_json_request()
    except ValueError as exc:
        log_node_event("bad_payload", node="", status_code=400, detail=str(exc))
        return {"error": "bad_payload", "detail": str(exc)}, 400

    data_time = safe_int(data.get("time"), now_ts())
    node = str(data.get("node") or "").strip()
    if not node:
        log_node_event("bad_payload", node="", status_code=400, detail="missing required field: node")
        return {"error": "bad_payload", "detail": "node is required"}, 400

    # A destructive operational reset advances a preserved acceptance epoch.
    # Acknowledge older Agent-local retry payloads without writing them back.
    if V5057_OPERATIONAL_PUSH_ACCEPT_AFTER and data_time < V5057_OPERATIONAL_PUSH_ACCEPT_AFTER:
        return {
            "ok": True,
            "ignored": True,
            "reason": "before reset epoch",
            "accept_after": V5057_OPERATIONAL_PUSH_ACCEPT_AFTER,
        }, 200

    interval_seconds = max(1, min(3600, safe_int(data.get("interval"), CACHE_BUCKET_SECONDS)))
    bucket = bucket_for(data_time)

    interfaces = data.get("interfaces") or []
    if not isinstance(interfaces, list):
        log_node_event("bad_payload", node=node, status_code=400, detail="interfaces is not a list")
        return {"error": "bad_payload", "detail": "interfaces must be a list"}, 400

    vms = data.get("vms") or []
    if not isinstance(vms, list):
        vms = []

    vm_inventory_payload = data.get("vm_inventory") or []
    if not isinstance(vm_inventory_payload, list):
        vm_inventory_payload = []
    inventory_complete = data.get("inventory_complete") is True

    node_host = data.get("node_host") or {}
    if not isinstance(node_host, dict):
        node_host = {}

    physical_interfaces = data.get("physical_interfaces") or []
    if not isinstance(physical_interfaces, list):
        physical_interfaces = []

    bridge_addresses = data.get("bridge_addresses") or []
    if not isinstance(bridge_addresses, list):
        bridge_addresses = []

    # Backward-compatible fallback for an agent that embeds bridge addresses
    # only in physical_interfaces.
    if not bridge_addresses:
        seen_roles = set()
        for phys in physical_interfaces:
            if not isinstance(phys, dict):
                continue
            role = str(phys.get("role") or "").strip().lower()
            bridge = str(phys.get("bridge") or "").strip()
            if not role or not bridge or role in seen_roles:
                continue
            seen_roles.add(role)
            bridge_addresses.append({
                "role": role,
                "bridge": bridge,
                "ipv4": phys.get("bridge_ipv4") or [],
                "ipv6": phys.get("bridge_ipv6") or [],
                "primary_ipv4": phys.get("bridge_primary_ipv4") or "",
                "primary_ipv6": phys.get("bridge_primary_ipv6") or "",
            })

    agent_health = data.get("agent_health") or {}
    if not isinstance(agent_health, dict):
        agent_health = {}

    snapshot_vm_uuids = set()
    for source in (interfaces, vms, vm_inventory_payload):
        for item in source:
            if isinstance(item, dict):
                value = str(item.get("vm_uuid") or item.get("uuid") or "").strip()
            else:
                value = str(item or "").strip()
            if value and value != "-":
                snapshot_vm_uuids.add(value)
    snapshot_vm_count = len(snapshot_vm_uuids)
    push_parse_ms = (time.perf_counter() - push_started) * 1000.0
    storage_v2_stats = storage_v2.WriteStats(enabled=storage_v2.STORAGE_V2_ENABLED)
    native_iface_stats = {"rows": 0, "copy_ms": 0.0, "merge_ms": 0.0}
    native_vm_stats = {"rows": 0, "copy_ms": 0.0, "merge_ms": 0.0}
    native_latest_ms = 0.0
    presence_stats = {"rows": 0, "copy_ms": 0.0, "merge_ms": 0.0}
    disk_current_ms = 0.0
    current_abuse_ms = 0.0
    commit_ms = 0.0

    conn = db()
    try:
        # Keep different nodes parallel, but never let two payloads for the same
        # node acquire PostgreSQL row locks in opposite order. This protects the
        # web workers from deadlocks without changing Agent sampling or push cadence.
        conn.execute("SET LOCAL lock_timeout = '60s'")
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
            (f"virtinfra-push:{node}",),
        )
        receipt = conn.execute("""
            INSERT OR IGNORE INTO push_receipts(node, push_time, bucket, received_at)
            VALUES (?, ?, ?, ?)
        """, (node, data_time, bucket, now_ts()))
        if int(receipt.rowcount or 0) == 0:
            conn.commit()
            return {"ok": True, "duplicate": True, "bucket": bucket, "version": data.get("version", 1), "agent_config": get_agent_runtime_config()}

        previous_push_row = conn.execute(
            "SELECT last_push FROM node_inventory WHERE node=?",
            (node,),
        ).fetchone()
        previous_push = safe_int((previous_push_row or [0])[0], 0)
        if previous_push and data_time > previous_push:
            record_recovered_miss_event(
                conn, node, previous_push, data_time, source="live"
            )

        conn.execute("""
            INSERT INTO node_push_snapshots(
                node, bucket, push_time, last_push, vm_count, iface_count,
                inventory_complete, retention_tier
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'raw')
            ON CONFLICT(node, bucket)
            DO UPDATE SET
                push_time=MAX(node_push_snapshots.push_time, excluded.push_time),
                last_push=MAX(node_push_snapshots.last_push, excluded.last_push),
                vm_count=excluded.vm_count,
                iface_count=excluded.iface_count,
                inventory_complete=MAX(node_push_snapshots.inventory_complete, excluded.inventory_complete),
                retention_tier='raw'
        """, (
            node, bucket, data_time, data_time, snapshot_vm_count, len(interfaces),
            1 if inventory_complete else 0,
        ))

        conn.execute("""
            INSERT INTO node_inventory(node, first_seen, last_push, status, hidden_at, deleted_at)
            VALUES (?, ?, ?, 'active', NULL, NULL)
            ON CONFLICT(node)
            DO UPDATE SET
                last_push = MAX(node_inventory.last_push, excluded.last_push),
                status = CASE
                    WHEN node_inventory.status = 'hidden' THEN 'hidden'
                    ELSE 'active'
                END,
                hidden_at = CASE
                    WHEN node_inventory.status = 'hidden' THEN node_inventory.hidden_at
                    ELSE NULL
                END,
                deleted_at = NULL
        """, (node, data_time, data_time))

        seen_vm_locations = {}
        for item in interfaces:
            if not isinstance(item, dict):
                continue
            seen_uuid = str(item.get("vm_uuid") or "-").strip()
            if seen_uuid and seen_uuid != "-" and seen_uuid not in seen_vm_locations:
                seen_vm_locations[seen_uuid] = {
                    "iface": str(item.get("iface") or "-"),
                    "bridge": str(item.get("bridge") or "-"),
                }
        for item in bridge_addresses:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            bridge = str(item.get("bridge") or "").strip()
            if not role:
                if bridge == PUBLIC_BRIDGE:
                    role = "public"
                elif bridge == PRIVATE_BRIDGE:
                    role = "private"
            if role not in ("public", "private"):
                continue
            if not bridge:
                bridge = PUBLIC_BRIDGE if role == "public" else PRIVATE_BRIDGE

            ipv4 = clean_ip_sequence(item.get("ipv4"))
            primary_ipv4 = str(item.get("primary_ipv4") or (ipv4[0] if ipv4 else ""))[:128]
            primary_ipv6 = ""
            ipv6 = []

            conn.execute("""
                INSERT INTO node_bridge_addresses_latest(
                    node, role, bridge, last_seen,
                    primary_ipv4, primary_ipv6, ipv4_json, ipv6_json,
                    operstate, carrier, mtu, mac
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(node, role)
                DO UPDATE SET
                    bridge=excluded.bridge,
                    last_seen=MAX(node_bridge_addresses_latest.last_seen, excluded.last_seen),
                    primary_ipv4=excluded.primary_ipv4,
                    primary_ipv6=excluded.primary_ipv6,
                    ipv4_json=excluded.ipv4_json,
                    ipv6_json=excluded.ipv6_json,
                    operstate=excluded.operstate,
                    carrier=excluded.carrier,
                    mtu=excluded.mtu,
                    mac=CASE
                        WHEN excluded.mac<>'' THEN excluded.mac
                        ELSE node_bridge_addresses_latest.mac
                    END
            """, (
                node, role, bridge, data_time,
                primary_ipv4, primary_ipv6,
                json.dumps(ipv4, separators=(",", ":")),
                json.dumps(ipv6, separators=(",", ":")),
                str(item.get("operstate") or "")[:32],
                1 if safe_int(item.get("carrier"), 0) else 0,
                max(0, safe_int(item.get("mtu"), 0)),
                str(item.get("mac") or "")[:64],
            ))

        for item in physical_interfaces:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            bridge = str(item.get("bridge") or "").strip()
            if not role:
                if bridge == PUBLIC_BRIDGE:
                    role = "public"
                elif bridge == PRIVATE_BRIDGE:
                    role = "private"
            if role not in ("public", "private"):
                continue
            if not bridge:
                bridge = PUBLIC_BRIDGE if role == "public" else PRIVATE_BRIDGE
            iface = str(item.get("iface") or "-").strip() or "-"
            rx_delta = max(0, safe_int(item.get("rx_delta"), 0))
            tx_delta = max(0, safe_int(item.get("tx_delta"), 0))
            rx_packets_delta = max(0, safe_int(item.get("rx_packets_delta"), 0))
            tx_packets_delta = max(0, safe_int(item.get("tx_packets_delta"), 0))
            rx_drop_delta = max(0, safe_int(item.get("rx_drop_delta"), 0))
            tx_drop_delta = max(0, safe_int(item.get("tx_drop_delta"), 0))
            rx_error_delta = max(0, safe_int(item.get("rx_error_delta"), 0))
            tx_error_delta = max(0, safe_int(item.get("tx_error_delta"), 0))

            rx_mbps = (rx_delta * 8.0 / interval_seconds / 1000000.0) if interval_seconds > 0 else 0.0
            tx_mbps = (tx_delta * 8.0 / interval_seconds / 1000000.0) if interval_seconds > 0 else 0.0
            rx_pps = (rx_packets_delta / float(interval_seconds)) if interval_seconds > 0 else 0.0
            tx_pps = (tx_packets_delta / float(interval_seconds)) if interval_seconds > 0 else 0.0

            flags = []
            if rx_drop_delta or tx_drop_delta:
                flags.append("NIC_DROP")
            if rx_error_delta or tx_error_delta:
                flags.append("NIC_ERROR")
            alert_level = "warn" if flags else "ok"
            alert_flags = ",".join(flags)

            conn.execute("""
                INSERT INTO node_physical_net_stats(
                    time, bucket, node, role, bridge, iface, interval_seconds,
                    rx_delta, tx_delta, rx_packets_delta, tx_packets_delta,
                    rx_drop_delta, tx_drop_delta, rx_error_delta, tx_error_delta,
                    last_push
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                data_time, bucket, node, role, bridge, iface, interval_seconds,
                rx_delta, tx_delta, rx_packets_delta, tx_packets_delta,
                rx_drop_delta, tx_drop_delta, rx_error_delta, tx_error_delta,
                data_time,
            ))

            conn.execute("""
                INSERT INTO node_physical_net_latest(
                    node, role, bridge, iface, last_seen, interval_seconds,
                    rx_mbps, tx_mbps, rx_pps, tx_pps,
                    rx_delta, tx_delta, rx_packets_delta, tx_packets_delta,
                    rx_drop_delta, tx_drop_delta, rx_error_delta, tx_error_delta,
                    alert_level, alert_flags, mac
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(node, role)
                DO UPDATE SET
                    bridge=excluded.bridge,
                    iface=excluded.iface,
                    last_seen=MAX(node_physical_net_latest.last_seen, excluded.last_seen),
                    interval_seconds=excluded.interval_seconds,
                    rx_mbps=excluded.rx_mbps,
                    tx_mbps=excluded.tx_mbps,
                    rx_pps=excluded.rx_pps,
                    tx_pps=excluded.tx_pps,
                    rx_delta=excluded.rx_delta,
                    tx_delta=excluded.tx_delta,
                    rx_packets_delta=excluded.rx_packets_delta,
                    tx_packets_delta=excluded.tx_packets_delta,
                    rx_drop_delta=excluded.rx_drop_delta,
                    tx_drop_delta=excluded.tx_drop_delta,
                    rx_error_delta=excluded.rx_error_delta,
                    tx_error_delta=excluded.tx_error_delta,
                    alert_level=excluded.alert_level,
                    alert_flags=excluded.alert_flags,
                    mac=CASE
                        WHEN excluded.mac<>'' THEN excluded.mac
                        ELSE node_physical_net_latest.mac
                    END
            """, (
                node, role, bridge, iface, data_time, interval_seconds,
                rx_mbps, tx_mbps, rx_pps, tx_pps,
                rx_delta, tx_delta, rx_packets_delta, tx_packets_delta,
                rx_drop_delta, tx_drop_delta, rx_error_delta, tx_error_delta,
                alert_level, alert_flags,
                normalize_mac_address(item.get("mac")),
            ))
            physical_mac = normalize_mac_address(item.get("mac"))
            if physical_mac:
                conn.execute("""
                    INSERT INTO node_nic_identity_lookup(
                        node,role,bridge,iface,mac,first_seen,changed_at
                    ) VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(node,role) DO UPDATE SET
                        bridge=excluded.bridge,iface=excluded.iface,mac=excluded.mac,
                        changed_at=excluded.changed_at
                    WHERE (node_nic_identity_lookup.bridge,
                           node_nic_identity_lookup.iface,
                           node_nic_identity_lookup.mac)
                      IS DISTINCT FROM (excluded.bridge,excluded.iface,excluded.mac)
                """, (node, role, bridge, iface, physical_mac, data_time, data_time))

        # v50.5.8-r4: derive Physical Consumption from the accepted 5-minute
        # payload in the same transaction. This replaces the Agent-side 2-hour
        # delivery path without changing the established /push payload.
        _v5058r4_rollup_physical_consumption(
            conn, node, data_time, interval_seconds, physical_interfaces
        )

        for vm_item in vms:
            if not isinstance(vm_item, dict):
                continue
            seen_uuid = str(vm_item.get("vm_uuid") or "-").strip()
            if seen_uuid and seen_uuid != "-" and seen_uuid not in seen_vm_locations:
                seen_vm_locations[seen_uuid] = {"iface": "-", "bridge": "-"}
        for inv_item in vm_inventory_payload:
            if isinstance(inv_item, dict):
                seen_uuid = str(inv_item.get("vm_uuid") or inv_item.get("uuid") or "-").strip()
                inv_iface = str(inv_item.get("iface") or "-")
                inv_bridge = str(inv_item.get("bridge") or "-")
            else:
                seen_uuid = str(inv_item or "-").strip()
                inv_iface = "-"
                inv_bridge = "-"
            if seen_uuid and seen_uuid != "-" and seen_uuid not in seen_vm_locations:
                seen_vm_locations[seen_uuid] = {"iface": inv_iface, "bridge": inv_bridge}
        presence_stats = process_node_vm_presence(
            conn, node, seen_vm_locations, data_time,
            inventory_complete=inventory_complete,
        ) or presence_stats
        auto_purge_migrated_vms(conn)

        native_iface_stats = _v5052_write_interface_copy_batch(
            conn, node, data_time, bucket, interval_seconds, interfaces
        )

        native_vm_stats = _v5052_write_vm_copy_batch(
            conn, node, data_time, bucket, interval_seconds, vms
        )
        native_latest_started = time.perf_counter()
        _v5052_merge_latest_metrics(conn, node, data_time)
        native_latest_ms = (time.perf_counter() - native_latest_started) * 1000.0


        if node_host:
            load1 = float(node_host.get("load1") or 0)
            load5 = float(node_host.get("load5") or 0)
            load15 = float(node_host.get("load15") or 0)
            host_cpu_percent = max(0.0, min(100.0, float(node_host.get("cpu_percent") or 0)))
            cpu_count = max(0, safe_int(node_host.get("cpu_count") or node_host.get("cpu_cores"), 0))
            mem_total = max(0, safe_int(node_host.get("mem_total"), 0))
            mem_available = max(0, safe_int(node_host.get("mem_available"), 0))
            mem_used = max(0, safe_int(node_host.get("mem_used"), 0))
            if mem_used <= 0 and mem_total > 0:
                mem_used = max(0, mem_total - mem_available)
            swap_total = max(0, safe_int(node_host.get("swap_total"), 0))
            swap_used = max(0, safe_int(node_host.get("swap_used"), 0))
            disk_read_delta = max(0, safe_int(node_host.get("disk_read_delta"), 0))
            disk_write_delta = max(0, safe_int(node_host.get("disk_write_delta"), 0))
            disk_read_bps = float(node_host.get("disk_read_bps") or (disk_read_delta / float(interval_seconds) if interval_seconds > 0 else 0.0))
            disk_write_bps = float(node_host.get("disk_write_bps") or (disk_write_delta / float(interval_seconds) if interval_seconds > 0 else 0.0))
            uptime_seconds = max(0, safe_int(node_host.get("uptime_seconds"), 0))

            flags = []
            if host_cpu_percent >= 90:
                flags.append("HOST_CPU_CRITICAL")
            elif host_cpu_percent >= 80:
                flags.append("HOST_CPU_HIGH")
            if mem_total > 0 and mem_available / float(mem_total) < 0.10:
                flags.append("LOW_RAM")
            if swap_total > 0 and swap_used / float(swap_total) > 0.50:
                flags.append("SWAP_HIGH")
            alert_level = "warn" if flags else "ok"
            alert_flags = ",".join(flags)

            conn.execute("""
                INSERT INTO node_host_stats(
                    time, bucket, node, interval_seconds,
                    load1, load5, load15, cpu_count, cpu_percent,
                    mem_total, mem_available, mem_used,
                    swap_total, swap_used,
                    disk_read_delta, disk_write_delta, disk_read_bps, disk_write_bps,
                    uptime_seconds, last_push
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                data_time, bucket, node, interval_seconds,
                load1, load5, load15, cpu_count, host_cpu_percent,
                mem_total, mem_available, mem_used,
                swap_total, swap_used,
                disk_read_delta, disk_write_delta, disk_read_bps, disk_write_bps,
                uptime_seconds, data_time,
            ))

            conn.execute("""
                INSERT INTO node_host_latest(
                    node, last_seen, interval_seconds,
                    load1, load5, load15, cpu_count, cpu_percent,
                    mem_total, mem_available, mem_used,
                    swap_total, swap_used,
                    disk_read_bps, disk_write_bps, disk_read_delta, disk_write_delta,
                    uptime_seconds, alert_level, alert_flags
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(node)
                DO UPDATE SET
                    last_seen=MAX(node_host_latest.last_seen, excluded.last_seen),
                    interval_seconds=excluded.interval_seconds,
                    load1=excluded.load1,
                    load5=excluded.load5,
                    load15=excluded.load15,
                    cpu_count=excluded.cpu_count,
                    cpu_percent=excluded.cpu_percent,
                    mem_total=excluded.mem_total,
                    mem_available=excluded.mem_available,
                    mem_used=excluded.mem_used,
                    swap_total=excluded.swap_total,
                    swap_used=excluded.swap_used,
                    disk_read_bps=excluded.disk_read_bps,
                    disk_write_bps=excluded.disk_write_bps,
                    disk_read_delta=excluded.disk_read_delta,
                    disk_write_delta=excluded.disk_write_delta,
                    uptime_seconds=excluded.uptime_seconds,
                    alert_level=excluded.alert_level,
                    alert_flags=excluded.alert_flags
            """, (
                node, data_time, interval_seconds,
                load1, load5, load15, cpu_count, host_cpu_percent,
                mem_total, mem_available, mem_used,
                swap_total, swap_used,
                disk_read_bps, disk_write_bps, disk_read_delta, disk_write_delta,
                uptime_seconds, alert_level, alert_flags,
            ))

            fs_rows = node_host.get("filesystems") or data.get("filesystems") or []
            if isinstance(fs_rows, list):
                seen_mounts = []
                for fs in fs_rows:
                    if not isinstance(fs, dict):
                        continue
                    mount = str(fs.get("mount") or "").strip()
                    if not mount:
                        continue
                    device = str(fs.get("device") or "-")[:255]
                    fstype = str(fs.get("fstype") or "-")[:64]
                    size = max(0, safe_int(fs.get("size"), 0))
                    used = max(0, safe_int(fs.get("used"), 0))
                    avail = max(0, safe_int(fs.get("avail"), 0))
                    use_percent = float(fs.get("use_percent") or ((used / float(size)) * 100.0 if size > 0 else 0.0))
                    if use_percent >= 95:
                        pass
                    seen_mounts.append(mount)
                    conn.execute("""
                        INSERT INTO node_filesystem_stats(
                            time, node, mount, device, fstype, size, used, avail, use_percent, last_push, bucket
                        )
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """, (data_time, node, mount, device, fstype, size, used, avail, use_percent, data_time, bucket))
                    conn.execute("""
                        INSERT INTO node_filesystem_latest(
                            node, mount, device, fstype, size, used, avail, use_percent, last_seen
                        )
                        VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(node, mount)
                        DO UPDATE SET
                            device=excluded.device,
                            fstype=excluded.fstype,
                            size=excluded.size,
                            used=excluded.used,
                            avail=excluded.avail,
                            use_percent=excluded.use_percent,
                            last_seen=excluded.last_seen
                    """, (node, mount, device, fstype, size, used, avail, use_percent, data_time))

        if agent_health:
            timings = agent_health.get("timings") or {}
            counts = agent_health.get("counts") or {}
            errors = agent_health.get("errors") or []
            if not isinstance(timings, dict):
                timings = {}
            if not isinstance(counts, dict):
                counts = {}
            if not isinstance(errors, list):
                errors = [str(errors)] if errors else []
            errors = [str(x)[:300] for x in errors[:20]]
            errors_json = json.dumps(errors, separators=(",", ":"))
            error_count = len(errors)
            duration_ms = max(0, safe_int(agent_health.get("duration_ms"), 0))
            virsh_list_ms = max(0, safe_int(timings.get("virsh_list_ms"), 0))
            vm_network_ms = max(0, safe_int(timings.get("vm_network_ms"), 0))
            vm_perf_ms = max(0, safe_int(timings.get("vm_perf_ms"), 0))
            node_host_ms = max(0, safe_int(timings.get("node_host_ms"), 0))
            physical_network_ms = max(0, safe_int(timings.get("physical_network_ms"), 0))
            api_push_ms = max(0, safe_int(timings.get("api_push_ms"), 0))
            vm_names_count = max(0, safe_int(counts.get("vm_names"), 0))
            interface_count = max(0, safe_int(counts.get("interfaces"), len(interfaces)))
            vms_count = max(0, safe_int(counts.get("vms"), len(vms)))
            physical_count = max(0, safe_int(counts.get("physical_interfaces"), len(physical_interfaces)))
            agent_version = max(0, safe_int(agent_health.get("version", data.get("version", 0)), 0))
            flags = []
            if error_count:
                flags.append("AGENT_ERROR")
            if duration_ms >= 120000:
                flags.append("AGENT_SLOW_CRITICAL")
            elif duration_ms >= 60000:
                flags.append("AGENT_SLOW")
            alert_level = "warn" if flags else "ok"
            alert_flags = ",".join(flags)

            conn.execute("""
                INSERT INTO agent_health_stats(
                    time, bucket, node, version, interval_seconds,
                    duration_ms, virsh_list_ms, vm_network_ms, vm_perf_ms, node_host_ms, physical_network_ms, api_push_ms,
                    vm_names, interfaces, vms, physical_interfaces, error_count, errors_json, last_push
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                data_time, bucket, node, agent_version, interval_seconds,
                duration_ms, virsh_list_ms, vm_network_ms, vm_perf_ms, node_host_ms, physical_network_ms, api_push_ms,
                vm_names_count, interface_count, vms_count, physical_count, error_count, errors_json, data_time,
            ))

            conn.execute("""
                INSERT INTO agent_health_latest(
                    node, last_seen, version, interval_seconds,
                    duration_ms, virsh_list_ms, vm_network_ms, vm_perf_ms, node_host_ms, physical_network_ms, api_push_ms,
                    vm_names, interfaces, vms, physical_interfaces, error_count, errors_json,
                    alert_level, alert_flags
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(node)
                DO UPDATE SET
                    last_seen=MAX(agent_health_latest.last_seen, excluded.last_seen),
                    version=excluded.version,
                    interval_seconds=excluded.interval_seconds,
                    duration_ms=excluded.duration_ms,
                    virsh_list_ms=excluded.virsh_list_ms,
                    vm_network_ms=excluded.vm_network_ms,
                    vm_perf_ms=excluded.vm_perf_ms,
                    node_host_ms=excluded.node_host_ms,
                    physical_network_ms=excluded.physical_network_ms,
                    api_push_ms=excluded.api_push_ms,
                    vm_names=excluded.vm_names,
                    interfaces=excluded.interfaces,
                    vms=excluded.vms,
                    physical_interfaces=excluded.physical_interfaces,
                    error_count=excluded.error_count,
                    errors_json=excluded.errors_json,
                    alert_level=excluded.alert_level,
                    alert_flags=excluded.alert_flags
            """, (
                node, data_time, agent_version, interval_seconds,
                duration_ms, virsh_list_ms, vm_network_ms, vm_perf_ms, node_host_ms, physical_network_ms, api_push_ms,
                vm_names_count, interface_count, vms_count, physical_count, error_count, errors_json,
                alert_level, alert_flags,
            ))

        disk_current_started = time.perf_counter()
        ingest_disk_io_current(conn, node, data_time, interval_seconds, vms, node_host)
        disk_current_ms = (time.perf_counter() - disk_current_started) * 1000.0
        current_abuse_started = time.perf_counter()
        refresh_fast_current_state(conn, node, data_time, interval_seconds, interfaces, vms, node_host, inventory_complete)
        current_abuse_ms = (time.perf_counter() - current_abuse_started) * 1000.0
        try:
            storage_v2_stats = storage_v2.write_storage_v2(
                conn,
                node=node,
                bucket=bucket,
                data_time=data_time,
                interval_seconds=interval_seconds,
                interfaces=interfaces,
                public_bridge=PUBLIC_BRIDGE,
                private_bridge=PRIVATE_BRIDGE,
            )
        except Exception:
            app.logger.exception("storage_v2_write_failed node=%s bucket=%s", node, bucket)
            raise
        commit_started = time.perf_counter()
        conn.commit()
        commit_ms = (time.perf_counter() - commit_started) * 1000.0
    finally:
        conn.close()

    vm_count = len({str(item.get("vm_uuid") or "-") for item in interfaces if isinstance(item, dict)})
    detail = f"bucket={bucket};vms={len(vms)};physical={len(physical_interfaces)};bridges={len(bridge_addresses)};inventory_complete={1 if inventory_complete else 0}"
    if agent_health:
        detail += f";duration_ms={safe_int(agent_health.get('duration_ms'), 0)}"
    log_node_event("push_ok", node=node, status_code=200, vm_count=vm_count, iface_count=len(interfaces), detail=detail)
    if storage_v2.OBSERVABILITY_ENABLED:
        total_ms = (time.perf_counter() - push_started) * 1000.0
        app.logger.info(
            "push_perf node=%s bucket=%s total_ms=%.2f parse_ms=%.2f "
            "presence_copy_ms=%.2f presence_merge_ms=%.2f "
            "iface_copy_ms=%.2f iface_merge_ms=%.2f vm_copy_ms=%.2f vm_merge_ms=%.2f latest_ms=%.2f "
            "disk_current_ms=%.2f current_abuse_ms=%.2f "
            "chart_write_ms=%.2f raw_write_ms=%.2f node_write_ms=%.2f commit_ms=%.2f "
            "rows_presence=%s rows_iface=%s rows_vm=%s rows_chart=%s rows_raw=%s rows_node=%s",
            node, bucket, total_ms, push_parse_ms,
            presence_stats.get("copy_ms", 0.0), presence_stats.get("merge_ms", 0.0),
            native_iface_stats.get("copy_ms", 0.0), native_iface_stats.get("merge_ms", 0.0),
            native_vm_stats.get("copy_ms", 0.0), native_vm_stats.get("merge_ms", 0.0), native_latest_ms,
            disk_current_ms, current_abuse_ms,
            storage_v2_stats.chart_write_ms, storage_v2_stats.raw_write_ms,
            storage_v2_stats.node_write_ms, commit_ms,
            presence_stats.get("rows", 0), native_iface_stats.get("rows", 0), native_vm_stats.get("rows", 0),
            storage_v2_stats.chart_rows, storage_v2_stats.raw_rows, storage_v2_stats.node_rows,
        )
    return {"ok": True, "count": len(interfaces), "vms": len(vms), "physical": len(physical_interfaces), "bridges": len(bridge_addresses), "inventory_complete": inventory_complete, "version": data.get("version", 1), "agent_config": get_agent_runtime_config()}



# ---------------------------------------------------------------------------
