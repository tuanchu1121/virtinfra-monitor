# 50.5.8-r4 fast Consumption + deadlock-safe inventory cleanup
# This layer is intentionally isolated. It does not change Abuse thresholds,
# CPU/RAM/Disk formulas, Storage I/O, queue behavior, retention tiers, API
# payloads or the 5-minute Agent push cadence.

import threading as _v5058r4_threading
import random as _v5058r4_random

V5058R4_RELEASE = "50.5.9-prod-r3-ui-alignment-overflow-hotfix"
V5058R4_SUMMARY_CACHE_TTL = 60
V5058R4_INVENTORY_BATCH = max(50, min(2000, safe_int(os.environ.get("BW_INVENTORY_CLEANUP_BATCH", "500"), 500)))
V5058R4_INVENTORY_MAX_BATCHES = max(1, min(1000, safe_int(os.environ.get("BW_INVENTORY_CLEANUP_MAX_BATCHES", "200"), 200)))
V5058R4_ROLLUP_RETENTION_SECONDS = 8 * 86400

_v5058r4_schema_ready = False
_v5058r4_schema_lock = _v5058r4_threading.RLock()
_v5058r4_db_base = db

def _v5058r4_ensure_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS node_consumption_hourly (
      hour_start INTEGER NOT NULL,
      node TEXT NOT NULL,
      physical_public_rx_bytes INTEGER NOT NULL DEFAULT 0,
      physical_public_tx_bytes INTEGER NOT NULL DEFAULT 0,
      physical_private_rx_bytes INTEGER NOT NULL DEFAULT 0,
      physical_private_tx_bytes INTEGER NOT NULL DEFAULT 0,
      coverage_seconds INTEGER NOT NULL DEFAULT 0,
      sample_count INTEGER NOT NULL DEFAULT 0,
      last_push INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(hour_start,node)
    );
    CREATE TABLE IF NOT EXISTS node_consumption_daily (
      day_start INTEGER NOT NULL,
      node TEXT NOT NULL,
      physical_public_rx_bytes INTEGER NOT NULL DEFAULT 0,
      physical_public_tx_bytes INTEGER NOT NULL DEFAULT 0,
      physical_private_rx_bytes INTEGER NOT NULL DEFAULT 0,
      physical_private_tx_bytes INTEGER NOT NULL DEFAULT 0,
      coverage_seconds INTEGER NOT NULL DEFAULT 0,
      sample_count INTEGER NOT NULL DEFAULT 0,
      last_push INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(day_start,node)
    );
    CREATE INDEX IF NOT EXISTS idx_node_consumption_hourly_node_time
      ON node_consumption_hourly(node,hour_start);
    CREATE INDEX IF NOT EXISTS idx_node_consumption_daily_node_time
      ON node_consumption_daily(node,day_start);
    """)
    conn.commit()

def db():
    global _v5058r4_schema_ready
    conn = _v5058r4_db_base()
    if not _v5058r4_schema_ready:
        with _v5058r4_schema_lock:
            if not _v5058r4_schema_ready:
                _v5058r4_ensure_schema(conn)
                _v5058r4_schema_ready = True
    return conn

def _v5058r4_rollup_physical_consumption(conn, node, data_time, interval_seconds, physical_interfaces):
    """Add one accepted 5-minute physical sample to server-side rollups.

    The caller is the established /push transaction, so push_receipts provides
    idempotency and a failed transaction rolls back raw data and rollups together.
    """
    totals = {
        "public_rx": 0, "public_tx": 0,
        "private_rx": 0, "private_tx": 0,
    }
    valid_rows = 0
    for item in physical_interfaces or []:
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
        valid_rows += 1
        totals[role + "_rx"] += max(0, safe_int(item.get("rx_delta"), 0))
        totals[role + "_tx"] += max(0, safe_int(item.get("tx_delta"), 0))
    if not valid_rows:
        return False

    interval = max(1, min(3600, safe_int(interval_seconds, CACHE_BUCKET_SECONDS)))
    hour_start = local_hour_start(data_time)
    day_start = local_day_start(data_time)
    values = (
        node,
        totals["public_rx"], totals["public_tx"],
        totals["private_rx"], totals["private_tx"],
        interval, 1, data_time,
    )
    conn.execute("""
      INSERT INTO node_consumption_hourly(
        hour_start,node,
        physical_public_rx_bytes,physical_public_tx_bytes,
        physical_private_rx_bytes,physical_private_tx_bytes,
        coverage_seconds,sample_count,last_push
      ) VALUES (?,?,?,?,?,?,?,?,?)
      ON CONFLICT(hour_start,node) DO UPDATE SET
        physical_public_rx_bytes=node_consumption_hourly.physical_public_rx_bytes+excluded.physical_public_rx_bytes,
        physical_public_tx_bytes=node_consumption_hourly.physical_public_tx_bytes+excluded.physical_public_tx_bytes,
        physical_private_rx_bytes=node_consumption_hourly.physical_private_rx_bytes+excluded.physical_private_rx_bytes,
        physical_private_tx_bytes=node_consumption_hourly.physical_private_tx_bytes+excluded.physical_private_tx_bytes,
        coverage_seconds=LEAST(3600,node_consumption_hourly.coverage_seconds+excluded.coverage_seconds),
        sample_count=node_consumption_hourly.sample_count+excluded.sample_count,
        last_push=GREATEST(node_consumption_hourly.last_push,excluded.last_push)
    """, (hour_start,) + values)
    conn.execute("""
      INSERT INTO node_consumption_daily(
        day_start,node,
        physical_public_rx_bytes,physical_public_tx_bytes,
        physical_private_rx_bytes,physical_private_tx_bytes,
        coverage_seconds,sample_count,last_push
      ) VALUES (?,?,?,?,?,?,?,?,?)
      ON CONFLICT(day_start,node) DO UPDATE SET
        physical_public_rx_bytes=node_consumption_daily.physical_public_rx_bytes+excluded.physical_public_rx_bytes,
        physical_public_tx_bytes=node_consumption_daily.physical_public_tx_bytes+excluded.physical_public_tx_bytes,
        physical_private_rx_bytes=node_consumption_daily.physical_private_rx_bytes+excluded.physical_private_rx_bytes,
        physical_private_tx_bytes=node_consumption_daily.physical_private_tx_bytes+excluded.physical_private_tx_bytes,
        coverage_seconds=LEAST(86400,node_consumption_daily.coverage_seconds+excluded.coverage_seconds),
        sample_count=node_consumption_daily.sample_count+excluded.sample_count,
        last_push=GREATEST(node_consumption_daily.last_push,excluded.last_push)
    """, (day_start,) + values)
    return True

def backfill_node_consumption_rollups(hours=48):
    """Rebuild recent node hourly/daily rollups from retained 5-minute samples."""
    hours = max(1, min(24 * 8, safe_int(hours, 48)))
    cutoff = now_ts() - hours * 3600
    offset = RETENTION_TZ_OFFSET_SECONDS
    conn = db()
    try:
        locked = conn.execute(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(?,0))",
            ("virtinfra-consumption-backfill",),
        ).fetchone()
        if not locked or not bool(locked[0]):
            conn.rollback()
            return {"ok": True, "skipped": True, "reason": "lock_busy"}
        conn.execute("SET LOCAL lock_timeout = '5s'")
        conn.execute("SET LOCAL statement_timeout = '20min'")
        hourly = conn.execute("""
          WITH per_bucket AS (
            SELECT
              (((CAST(p.time AS BIGINT)+?)/3600)*3600-?)::bigint AS hour_start,
              p.node,p.bucket,
              SUM(CASE WHEN LOWER(COALESCE(p.role,''))='public' THEN p.rx_delta ELSE 0 END)::bigint AS public_rx,
              SUM(CASE WHEN LOWER(COALESCE(p.role,''))='public' THEN p.tx_delta ELSE 0 END)::bigint AS public_tx,
              SUM(CASE WHEN LOWER(COALESCE(p.role,''))='private' THEN p.rx_delta ELSE 0 END)::bigint AS private_rx,
              SUM(CASE WHEN LOWER(COALESCE(p.role,''))='private' THEN p.tx_delta ELSE 0 END)::bigint AS private_tx,
              MAX(COALESCE(p.interval_seconds,300))::bigint AS coverage_seconds,
              MAX(COALESCE(p.last_push,p.time))::bigint AS last_push
            FROM node_physical_net_stats p
            WHERE p.time>=?
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
        """, (offset, offset, cutoff)).rowcount
        first_day = local_day_start(cutoff)
        daily = conn.execute("""
          WITH daily AS (
            SELECT (((hour_start+?)/86400)*86400-?)::bigint AS day_start,node,
              SUM(physical_public_rx_bytes)::bigint public_rx,
              SUM(physical_public_tx_bytes)::bigint public_tx,
              SUM(physical_private_rx_bytes)::bigint private_rx,
              SUM(physical_private_tx_bytes)::bigint private_tx,
              LEAST(86400,SUM(coverage_seconds))::bigint coverage_seconds,
              SUM(sample_count)::bigint sample_count,
              MAX(last_push)::bigint last_push
            FROM node_consumption_hourly
            WHERE hour_start>=?
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
        """, (offset, offset, first_day)).rowcount
        conn.commit()
        return {"ok": True, "hours": hours, "hourly_rows": max(0, hourly), "daily_rows": max(0, daily)}
    finally:
        conn.close()

def _v5058r4_deadlock(exc):
    return getattr(exc, "sqlstate", "") == "40P01" or "deadlock detected" in str(exc).lower()

def _v5058r4_cleanup_batch(sql, params, retries=3):
    for attempt in range(max(1, retries)):
        conn = db()
        try:
            conn.execute("SET LOCAL lock_timeout = '2s'")
            conn.execute("SET LOCAL statement_timeout = '30s'")
            cursor = conn.execute(sql, params)
            changed = max(0, int(cursor.rowcount or 0))
            conn.commit()
            return changed
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            if not _v5058r4_deadlock(exc) or attempt + 1 >= retries:
                raise
            time.sleep(0.10 + _v5058r4_random.random() * 0.40)
        finally:
            conn.close()
    return 0

def run_inventory_cleanup_batches(batch_size=None, max_batches=None):
    """Expire inventory in short deterministic batches without blocking /push."""
    batch_size = max(50, min(2000, safe_int(batch_size, V5058R4_INVENTORY_BATCH)))
    max_batches = max(1, min(1000, safe_int(max_batches, V5058R4_INVENTORY_MAX_BATCHES)))
    ts = now_ts()
    stale_cutoff = ts - VM_STALE_SECONDS
    delete_cutoff = ts - VM_AUTO_DELETE_SECONDS
    node_cutoff = ts - NODE_AUTO_DELETE_SECONDS
    result = {"ok": True, "vm_stale": 0, "vm_deleted": 0, "node_deleted": 0, "batches": 0}

    lock_conn = db()
    try:
        row = lock_conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(?,0))",
            ("virtinfra-inventory-cleanup",),
        ).fetchone()
        if not row or not bool(row[0]):
            return {"ok": True, "skipped": True, "reason": "already_running"}

        statements = (
            ("vm_stale", """
              WITH targets AS (
                SELECT node,vm_uuid FROM vm_inventory
                WHERE status='active' AND deleted_at IS NULL
                  AND last_seen<? AND last_seen>=?
                ORDER BY last_seen,node,vm_uuid
                FOR UPDATE SKIP LOCKED LIMIT ?
              )
              UPDATE vm_inventory v
                 SET status='stale',hidden_at=COALESCE(v.hidden_at,?)
                FROM targets t
               WHERE v.node=t.node AND v.vm_uuid=t.vm_uuid
            """, (stale_cutoff, delete_cutoff, batch_size, ts)),
            ("vm_deleted", """
              WITH targets AS (
                SELECT node,vm_uuid FROM vm_inventory
                WHERE status IN ('active','stale','missing')
                  AND status!='hidden' AND deleted_at IS NULL AND last_seen<?
                ORDER BY last_seen,node,vm_uuid
                FOR UPDATE SKIP LOCKED LIMIT ?
              )
              UPDATE vm_inventory v
                 SET status='deleted',deleted_at=COALESCE(v.deleted_at,?)
                FROM targets t
               WHERE v.node=t.node AND v.vm_uuid=t.vm_uuid
            """, (delete_cutoff, batch_size, ts)),
            ("node_deleted", """
              WITH targets AS (
                SELECT node FROM node_inventory
                WHERE status IN ('active','stale','missing')
                  AND status!='hidden' AND deleted_at IS NULL AND last_push<?
                ORDER BY last_push,node
                FOR UPDATE SKIP LOCKED LIMIT ?
              )
              UPDATE node_inventory n
                 SET status='deleted',deleted_at=COALESCE(n.deleted_at,?)
                FROM targets t
               WHERE n.node=t.node
            """, (node_cutoff, batch_size, ts)),
        )
        for key, sql, params in statements:
            for _ in range(max_batches):
                changed = _v5058r4_cleanup_batch(sql, params)
                result[key] += changed
                result["batches"] += 1
                if changed < batch_size:
                    break

        # Rollups are isolated from current push rows, so bounded retention here
        # cannot contend with active vm_inventory updates.
        cutoff = ts - V5058R4_ROLLUP_RETENTION_SECONDS
        conn = db()
        try:
            conn.execute("DELETE FROM node_consumption_hourly WHERE hour_start<?", (cutoff,))
            conn.execute("DELETE FROM node_consumption_daily WHERE day_start<?", (local_day_start(cutoff),))
            conn.commit()
        finally:
            conn.close()
        return result
    finally:
        try:
            lock_conn.execute(
                "SELECT pg_advisory_unlock(hashtextextended(?,0))",
                ("virtinfra-inventory-cleanup",),
            )
            lock_conn.commit()
        except Exception:
            pass
        lock_conn.close()

# ----- Fast, rolling-window Consumption readers --------------------------------

def _v5058r4_ceil_hour(ts):
    base = local_hour_start(ts)
    return base if safe_int(ts, 0) == base else base + 3600

def _v5058r4_vm_raw_branch(start, end, selected_node=""):
    if end <= start:
        return "", []
    node_clause = " AND ns.node=?" if selected_node else ""
    sql = """
      SELECT ns.node,ns.vm_uuid,ns.bridge,
             COALESCE(SUM(ns.rx_delta),0)::bigint AS rx_bytes,
             COALESCE(SUM(ns.tx_delta),0)::bigint AS tx_bytes,
             COUNT(DISTINCT ns.bucket)::bigint AS sample_count,
             COALESCE(MAX(ns.last_push),0)::bigint AS last_push
        FROM node_stats ns
       WHERE ns.last_push>=? AND ns.last_push<?%s
       GROUP BY ns.node,ns.vm_uuid,ns.bridge
    """ % node_clause
    params = [start, end]
    if selected_node:
        params.append(selected_node)
    return sql, params

def _v5058r4_vm_hourly_branch(start, end, selected_node=""):
    if end <= start:
        return "", []
    node_clause = " AND node=?" if selected_node else ""
    sql = """
      SELECT node,vm_uuid,bridge,rx_bytes,tx_bytes,sample_count,last_push
        FROM bandwidth_hourly
       WHERE hour_start>=? AND hour_start<?%s
    """ % node_clause
    params = [start, end]
    if selected_node:
        params.append(selected_node)
    return sql, params

def _v5058r4_vm_daily_branch(start, end, selected_node=""):
    if end <= start:
        return "", []
    node_clause = " AND node=?" if selected_node else ""
    sql = """
      SELECT node,vm_uuid,bridge,rx_bytes,tx_bytes,sample_count,last_push
        FROM bandwidth_daily
       WHERE day_start>=? AND day_start<?%s
    """ % node_clause
    params = [start, end]
    if selected_node:
        params.append(selected_node)
    return sql, params

def _v5058c_vm_source_sql(start, end, selected_node=""):
    """Use daily/full-hour rollups and raw 5-minute rows only at true edges."""
    start = safe_int(start, 0)
    end = safe_int(end, 0)
    if end <= start:
        return "SELECT node,vm_uuid,bridge,rx_bytes,tx_bytes,sample_count,last_push FROM bandwidth_hourly WHERE 1=0", []

    first_day = local_day_start(start)
    full_day_start = first_day if start == first_day else first_day + 86400
    full_day_end = local_day_start(end)
    branches, params = [], []

    if full_day_start < full_day_end:
        sql, values = _v5058r4_vm_daily_branch(full_day_start, full_day_end, selected_node)
        branches.append(sql); params.extend(values)
        edges = [(start, full_day_start), (full_day_end, end)]
    else:
        edges = [(start, end)]

    for edge_start, edge_end in edges:
        if edge_end <= edge_start:
            continue
        full_hour_start = _v5058r4_ceil_hour(edge_start)
        full_hour_end = local_hour_start(edge_end)
        if full_hour_start >= full_hour_end:
            sql, values = _v5058r4_vm_raw_branch(edge_start, edge_end, selected_node)
            branches.append(sql); params.extend(values)
            continue
        if edge_start < full_hour_start:
            sql, values = _v5058r4_vm_raw_branch(edge_start, full_hour_start, selected_node)
            branches.append(sql); params.extend(values)
        sql, values = _v5058r4_vm_hourly_branch(full_hour_start, full_hour_end, selected_node)
        branches.append(sql); params.extend(values)
        if full_hour_end < edge_end:
            sql, values = _v5058r4_vm_raw_branch(full_hour_end, edge_end, selected_node)
            branches.append(sql); params.extend(values)
    return " UNION ALL ".join(branches), params

def _v5058c_visible_vm_cte(selected_node=""):
    node_filter = " AND l.node=?" if selected_node else ""
    params = [PUBLIC_BRIDGE, PRIVATE_BRIDGE]
    if selected_node:
        params.append(selected_node)
    sql = """
      node_meta AS (
        SELECT ni.node,
               COALESCE(MAX(CASE WHEN LOWER(COALESCE(ba.role,''))='public' THEN ba.primary_ipv4 END),'') AS node_ip
          FROM node_inventory ni
          LEFT JOIN node_bridge_addresses_latest ba ON ba.node=ni.node
         WHERE COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL
         GROUP BY ni.node
      ),
      vm_iface_config AS (
        SELECT node,vm_uuid,
               MAX(CASE WHEN bridge=? THEN 1 ELSE 0 END)::integer AS public_configured,
               MAX(CASE WHEN bridge=? THEN 1 ELSE 0 END)::integer AS private_configured
          FROM vm_iface_current
         GROUP BY node,vm_uuid
      ),
      visible_vm AS (
        SELECT l.vm_uuid,l.vm_uuid AS vm_name,l.node,
               COALESCE(nm.node_ip,'') AS node_ip,
               COALESCE(cfg.public_configured,0) AS public_configured,
               COALESCE(cfg.private_configured,0) AS private_configured
          FROM vm_location_latest l
          JOIN node_inventory ni ON ni.node=l.node
          JOIN vm_inventory vi ON vi.node=l.node AND vi.vm_uuid=l.vm_uuid
          LEFT JOIN node_meta nm ON nm.node=l.node
          LEFT JOIN vm_iface_config cfg ON cfg.node=l.node AND cfg.vm_uuid=l.vm_uuid
         WHERE COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL
           AND COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL%s
      )
    """ % node_filter
    return sql, params

def _v5058c_vm_ctes(start, end, selected_node=""):
    source_sql, source_params = _v5058c_vm_source_sql(start, end, selected_node)
    visible_sql, visible_params = _v5058c_visible_vm_cte(selected_node)
    expected_samples = max(1, int(math.ceil(max(1, end - start) / float(CACHE_BUCKET_SECONDS))))
    sql = """
      WITH source AS (%s),
      per_bridge AS (
        SELECT node,vm_uuid,bridge,
               COALESCE(SUM(rx_bytes),0)::bigint host_rx,
               COALESCE(SUM(tx_bytes),0)::bigint host_tx,
               LEAST(?,COALESCE(SUM(sample_count),0))::bigint samples,
               COALESCE(MAX(last_push),0)::bigint latest_sample
          FROM source GROUP BY node,vm_uuid,bridge
      ),
      vm_agg AS (
        SELECT node,vm_uuid,
               COALESCE(SUM(CASE WHEN bridge=? THEN host_tx ELSE 0 END),0)::bigint public_rx,
               COALESCE(SUM(CASE WHEN bridge=? THEN host_rx ELSE 0 END),0)::bigint public_tx,
               COALESCE(SUM(CASE WHEN bridge=? THEN host_tx ELSE 0 END),0)::bigint private_rx,
               COALESCE(SUM(CASE WHEN bridge=? THEN host_rx ELSE 0 END),0)::bigint private_tx,
               COALESCE(MAX(samples),0)::bigint coverage_samples,
               COALESCE(MAX(latest_sample),0)::bigint latest_sample
          FROM per_bridge GROUP BY node,vm_uuid
      ),
      %s,
      vm_rows AS (
        SELECT v.vm_uuid,v.vm_name,v.node,v.node_ip,
               v.public_configured,v.private_configured,
               COALESCE(a.public_rx,0)::bigint public_rx,
               COALESCE(a.public_tx,0)::bigint public_tx,
               COALESCE(a.public_rx,0)::bigint+COALESCE(a.public_tx,0)::bigint public_total,
               COALESCE(a.private_rx,0)::bigint private_rx,
               COALESCE(a.private_tx,0)::bigint private_tx,
               COALESCE(a.private_rx,0)::bigint+COALESCE(a.private_tx,0)::bigint private_total,
               LEAST(100.0,COALESCE(a.coverage_samples,0)*100.0/?) coverage_percent,
               COALESCE(a.latest_sample,0)::bigint latest_sample
          FROM visible_vm v
          LEFT JOIN vm_agg a ON a.node=v.node AND a.vm_uuid=v.vm_uuid
      )
    """ % (source_sql, visible_sql)
    params = list(source_params)
    params.append(expected_samples)
    params.extend([PUBLIC_BRIDGE, PUBLIC_BRIDGE, PRIVATE_BRIDGE, PRIVATE_BRIDGE])
    params.extend(visible_params)
    params.append(expected_samples)
    return sql, params

def _v5058c_search_clause(tab, q):
    q = str(q or "").strip()
    if not q:
        return "", []
    like = "%" + q + "%"
    if tab == "node":
        return " AND (LOWER(node) LIKE LOWER(?) OR LOWER(node_ip) LIKE LOWER(?))", [like, like]
    normalized_mac = normalize_mac_address(q)
    mac_exact_sql = " OR mil.mac=?" if normalized_mac else ""
    params = [like, like, like, like, like]
    if normalized_mac:
        params.append(normalized_mac)
    return """
      AND (
        LOWER(vm_name) LIKE LOWER(?) OR LOWER(vm_uuid) LIKE LOWER(?)
        OR LOWER(node) LIKE LOWER(?) OR LOWER(node_ip) LIKE LOWER(?)
        OR EXISTS(
          SELECT 1 FROM vm_nic_identity_lookup mil
           WHERE mil.node=vm_rows.node AND mil.vm_uuid=vm_rows.vm_uuid
             AND (LOWER(COALESCE(mil.mac,'')) LIKE LOWER(?)%s)
        )
      )
    """ % mac_exact_sql, params

def _v5058r4_cached_totals(kind, start, end, selected_node, compute):
    seconds = max(1, safe_int(end, 0) - safe_int(start, 0))
    cache_end = (safe_int(end, 0) // 60) * 60
    cache_start = cache_end - seconds
    key = "v5058r4:summary:%s:%s:%s:%s" % (kind, cache_start, cache_end, selected_node or "*")
    try:
        cached = _v48140_cache_get(key)
        if cached:
            data = json.loads(cached)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    data = compute(cache_start, cache_end, selected_node)
    try:
        _v48140_cache_set(key, json.dumps(data, separators=(",", ":")), V5058R4_SUMMARY_CACHE_TTL)
    except Exception:
        pass
    return data

def _v5058r4_vm_totals_uncached(start, end, selected_node=""):
    ctes, params = _v5058c_vm_ctes(start, end, selected_node)
    conn = db()
    try:
        row = conn.execute(ctes + """
          SELECT COALESCE(SUM(public_rx),0),COALESCE(SUM(public_tx),0),
                 COALESCE(SUM(private_rx),0),COALESCE(SUM(private_tx),0)
            FROM vm_rows
        """, params).fetchone()
        return {
            "vm_public_rx": safe_int(row[0] if row else 0, 0),
            "vm_public_tx": safe_int(row[1] if row else 0, 0),
            "vm_private_rx": safe_int(row[2] if row else 0, 0),
            "vm_private_tx": safe_int(row[3] if row else 0, 0),
        }
    finally:
        conn.close()

def _v5058c_vm_totals(start, end, selected_node=""):
    return _v5058r4_cached_totals("vm", start, end, selected_node, _v5058r4_vm_totals_uncached)

def _v5058c_vm_rows(start, end, selected_node, q, coverage, sort_by, order, page_no, limit):
    ctes, params = _v5058c_vm_ctes(start, end, selected_node)
    search_sql, search_params = _v5058c_search_clause("vm", q)
    where_sql = " WHERE 1=1" + search_sql + _v5058c_coverage_clause(coverage)
    order_column = V5058C_VM_SORTS[sort_by]
    tie_order = "ASC" if sort_by in {"uuid", "node"} and order == "asc" else "DESC"
    page_no = max(1, page_no)

    def fetch(offset):
        conn = db()
        try:
            return conn.execute(
                ctes + """
                  SELECT vm_uuid,node,node_ip,public_configured,private_configured,
                         public_rx,public_tx,public_total,
                         private_rx,private_tx,private_total,
                         coverage_percent,latest_sample,COUNT(*) OVER() AS total_count
                    FROM vm_rows
                """ + where_sql + " ORDER BY %s %s,vm_uuid %s LIMIT ? OFFSET ?" % (
                    order_column, order.upper(), tie_order,
                ), params + search_params + [limit, offset],
            ).fetchall()
        finally:
            conn.close()

    raw_rows = fetch((page_no - 1) * limit)
    if not raw_rows and page_no > 1:
        page_no = 1
        raw_rows = fetch(0)
    total = safe_int(raw_rows[0][-1] if raw_rows else 0, 0)
    max_page = max(1, int(math.ceil(total / float(max(1, limit)))))
    rows = [tuple(row[:-1]) for row in raw_rows]
    return rows, total, page_no, max_page

def _v5058r4_node_raw_branch(start, end, selected_node=""):
    return _v5058c_raw_node_branch(start, end, selected_node)

def _v5058r4_node_hourly_branch(start, end, selected_node=""):
    node_clause = " AND h.node=?" if selected_node else ""
    sql = """
      SELECT h.node,
             h.physical_public_rx_bytes::bigint physical_public_rx,
             h.physical_public_tx_bytes::bigint physical_public_tx,
             h.physical_private_rx_bytes::bigint physical_private_rx,
             h.physical_private_tx_bytes::bigint physical_private_tx,
             h.coverage_seconds::bigint coverage_seconds,
             h.last_push::bigint latest_sample
        FROM node_consumption_hourly h
       WHERE h.hour_start>=? AND h.hour_start<?%s
    """ % node_clause
    params = [start, end]
    if selected_node:
        params.append(selected_node)
    return sql, params

def _v5058r4_node_legacy_fallback(start, end, selected_node=""):
    node_clause = " AND b.node=?" if selected_node else ""
    sql = """
      SELECT b.node,
             b.physical_public_rx_bytes::bigint physical_public_rx,
             b.physical_public_tx_bytes::bigint physical_public_tx,
             b.physical_private_rx_bytes::bigint physical_private_rx,
             b.physical_private_tx_bytes::bigint physical_private_tx,
             b.coverage_seconds::bigint coverage_seconds,
             b.received_at::bigint latest_sample
        FROM node_bandwidth_consumption_2h b
       WHERE b.bucket_start>=? AND b.bucket_end<=?%s
         AND NOT EXISTS (
           SELECT 1 FROM node_consumption_hourly h
            WHERE h.node=b.node AND h.hour_start>=b.bucket_start AND h.hour_start<b.bucket_end
         )
    """ % node_clause
    params = [start, end]
    if selected_node:
        params.append(selected_node)
    return sql, params

def _v5058c_node_source_sql(start, end, selected_node=""):
    """Use compact server hourly rows, exact raw edges and legacy-only fallback."""
    start = safe_int(start, 0); end = safe_int(end, 0)
    if end <= start:
        return "SELECT node,0::bigint physical_public_rx,0::bigint physical_public_tx,0::bigint physical_private_rx,0::bigint physical_private_tx,0::bigint coverage_seconds,0::bigint latest_sample FROM node_inventory WHERE 1=0", []
    full_start = _v5058r4_ceil_hour(start)
    full_end = local_hour_start(end)
    branches, params = [], []
    if full_start >= full_end:
        return _v5058r4_node_raw_branch(start, end, selected_node)
    if start < full_start:
        sql, values = _v5058r4_node_raw_branch(start, full_start, selected_node)
        branches.append(sql); params.extend(values)
    sql, values = _v5058r4_node_hourly_branch(full_start, full_end, selected_node)
    branches.append(sql); params.extend(values)
    sql, values = _v5058r4_node_legacy_fallback(full_start, full_end, selected_node)
    branches.append(sql); params.extend(values)
    if full_end < end:
        sql, values = _v5058r4_node_raw_branch(full_end, end, selected_node)
        branches.append(sql); params.extend(values)
    return " UNION ALL ".join(branches), params

def _v5058c_node_ctes(start, end, selected_node=""):
    source_sql, source_params = _v5058c_node_source_sql(start, end, selected_node)
    node_filter = " AND ni.node=?" if selected_node else ""
    expected_seconds = max(1, end - start)
    sql = """
      WITH source_parts AS (%s),
      node_agg AS (
        SELECT node,
               COALESCE(SUM(physical_public_rx),0)::bigint physical_public_rx,
               COALESCE(SUM(physical_public_tx),0)::bigint physical_public_tx,
               COALESCE(SUM(physical_private_rx),0)::bigint physical_private_rx,
               COALESCE(SUM(physical_private_tx),0)::bigint physical_private_tx,
               LEAST(?,COALESCE(SUM(coverage_seconds),0))::bigint coverage_seconds,
               COALESCE(MAX(latest_sample),0)::bigint latest_sample
          FROM source_parts GROUP BY node
      ),
      node_meta AS (
        SELECT ni.node,
               COALESCE(MAX(CASE WHEN LOWER(COALESCE(ba.role,''))='public' THEN ba.primary_ipv4 END),'') node_ip,
               MAX(CASE WHEN LOWER(COALESCE(pn.role,''))='public' THEN 1 ELSE 0 END)::integer public_configured,
               MAX(CASE WHEN LOWER(COALESCE(pn.role,''))='private' THEN 1 ELSE 0 END)::integer private_configured,
               MAX(CASE WHEN LOWER(COALESCE(ba.role,''))='public' THEN 1 ELSE 0 END)::integer public_addressed,
               MAX(CASE WHEN LOWER(COALESCE(ba.role,''))='private' THEN 1 ELSE 0 END)::integer private_addressed
          FROM node_inventory ni
          LEFT JOIN node_bridge_addresses_latest ba ON ba.node=ni.node
          LEFT JOIN node_physical_net_latest pn ON pn.node=ni.node
         WHERE COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL%s
         GROUP BY ni.node
      ),
      node_rows AS (
        SELECT m.node,m.node_ip,
               GREATEST(m.public_configured,m.public_addressed) public_configured,
               GREATEST(m.private_configured,m.private_addressed) private_configured,
               COALESCE(a.physical_public_rx,0)::bigint physical_public_rx,
               COALESCE(a.physical_public_tx,0)::bigint physical_public_tx,
               COALESCE(a.physical_public_rx,0)::bigint+COALESCE(a.physical_public_tx,0)::bigint physical_public_total,
               COALESCE(a.physical_private_rx,0)::bigint physical_private_rx,
               COALESCE(a.physical_private_tx,0)::bigint physical_private_tx,
               COALESCE(a.physical_private_rx,0)::bigint+COALESCE(a.physical_private_tx,0)::bigint physical_private_total,
               LEAST(100.0,COALESCE(a.coverage_seconds,0)*100.0/?) coverage_percent,
               COALESCE(a.latest_sample,0)::bigint latest_sample
          FROM node_meta m LEFT JOIN node_agg a ON a.node=m.node
      )
    """ % (source_sql, node_filter)
    params = list(source_params)
    params.append(expected_seconds)
    if selected_node:
        params.append(selected_node)
    params.append(expected_seconds)
    return sql, params

def _v5058r4_node_totals_uncached(start, end, selected_node=""):
    ctes, params = _v5058c_node_ctes(start, end, selected_node)
    conn = db()
    try:
        row = conn.execute(ctes + """
          SELECT COALESCE(SUM(physical_public_rx),0),COALESCE(SUM(physical_public_tx),0),
                 COALESCE(SUM(physical_private_rx),0),COALESCE(SUM(physical_private_tx),0)
            FROM node_rows
        """, params).fetchone()
        return {
            "physical_public_rx": safe_int(row[0] if row else 0, 0),
            "physical_public_tx": safe_int(row[1] if row else 0, 0),
            "physical_private_rx": safe_int(row[2] if row else 0, 0),
            "physical_private_tx": safe_int(row[3] if row else 0, 0),
        }
    finally:
        conn.close()

def _v5058c_node_totals(start, end, selected_node=""):
    return _v5058r4_cached_totals("node", start, end, selected_node, _v5058r4_node_totals_uncached)

def _v5058c_node_rows(start, end, q, coverage, sort_by, order, page_no, limit):
    ctes, params = _v5058c_node_ctes(start, end)
    search_sql, search_params = _v5058c_search_clause("node", q)
    where_sql = " WHERE 1=1" + search_sql + _v5058c_coverage_clause(coverage)
    order_column = V5058C_NODE_SORTS[sort_by]
    tie_order = "ASC" if sort_by == "node" and order == "asc" else "DESC"
    page_no = max(1, page_no)

    def fetch(offset):
        conn = db()
        try:
            return conn.execute(
                ctes + """
                  SELECT node,node_ip,public_configured,private_configured,
                         physical_public_rx,physical_public_tx,physical_public_total,
                         physical_private_rx,physical_private_tx,physical_private_total,
                         coverage_percent,latest_sample,COUNT(*) OVER() total_count
                    FROM node_rows
                """ + where_sql + " ORDER BY %s %s,node %s LIMIT ? OFFSET ?" % (
                    order_column, order.upper(), tie_order,
                ), params + search_params + [limit, offset],
            ).fetchall()
        finally:
            conn.close()

    raw_rows = fetch((page_no - 1) * limit)
    if not raw_rows and page_no > 1:
        page_no = 1
        raw_rows = fetch(0)
    total = safe_int(raw_rows[0][-1] if raw_rows else 0, 0)
    max_page = max(1, int(math.ceil(total / float(max(1, limit)))))
    rows = [tuple(row[:-1]) for row in raw_rows]
    return rows, total, page_no, max_page

def _v5058c_visible_nodes():
    conn = db()
    try:
        return conn.execute("""
          SELECT ni.node,
                 COALESCE(MAX(CASE WHEN LOWER(COALESCE(ba.role,''))='public' THEN ba.primary_ipv4 END),'') public_ipv4
            FROM node_inventory ni
            LEFT JOIN node_bridge_addresses_latest ba ON ba.node=ni.node
           WHERE COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL
           GROUP BY ni.node ORDER BY LOWER(ni.node)
        """).fetchall()
    finally:
        conn.close()

# Include additive rollups in existing purge/reset paths without changing any
# established table or endpoint behavior.
_v5058r4_purge_node_data_base = purge_node_data

def purge_node_data(conn, node):
    result = dict(_v5058r4_purge_node_data_base(conn, node) or {})
    result["node_group_membership_history"] = _delete_count(conn, "DELETE FROM node_group_membership_history WHERE node=?", (node,))
    result["node_consumption_hourly"] = _delete_count(conn, "DELETE FROM node_consumption_hourly WHERE node=?", (node,))
    result["node_consumption_daily"] = _delete_count(conn, "DELETE FROM node_consumption_daily WHERE node=?", (node,))
    return result

MONITORING_DATA_TABLES = tuple(dict.fromkeys(tuple(MONITORING_DATA_TABLES) + (
    "node_consumption_hourly", "node_consumption_daily",
)))
V48102_RESET_APP_TABLES = tuple(dict.fromkeys(tuple(V48102_RESET_APP_TABLES) + (
    "node_consumption_hourly", "node_consumption_daily",
)))

# Last-resort protection for residual PostgreSQL deadlocks between simultaneous
# cross-node migration updates. The request body is cached once so the original
# /push implementation can be rerun as one complete transaction. No partial
# payload is committed because PostgreSQL aborts the failed transaction.
_v5058r4_push_view_base = app.view_functions.get("push")

def push_v5058r4_deadlock_retry():
    if _v5058r4_push_view_base is None:
        return {"error": "push_unavailable"}, 503
    request.get_data(cache=True, as_text=False)
    attempts = max(1, min(5, safe_int(os.environ.get("BW_PUSH_DEADLOCK_RETRIES", "3"), 3)))
    for attempt in range(attempts):
        try:
            return _v5058r4_push_view_base()
        except Exception as exc:
            if not _v5058r4_deadlock(exc) or attempt + 1 >= attempts:
                raise
            delay = 0.10 + _v5058r4_random.random() * 0.40
            app.logger.warning(
                "push_deadlock_retry attempt=%s/%s delay_ms=%s detail=%s",
                attempt + 1, attempts, int(delay * 1000), str(exc)[:300],
            )
            time.sleep(delay)
    return {"error": "push_retry_exhausted"}, 503

if _v5058r4_push_view_base is not None:
    app.view_functions["push"] = push_v5058r4_deadlock_retry

