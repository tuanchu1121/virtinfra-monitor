# Release: 50.5.9-prod-r22.12.1-preflight-contract-hotfix
#
# Definitive VM Consumption read-path hotfix.
#
# Canonical hourly/daily rollups and packed five-minute slots remain the source
# of truth. A dedicated worker aggregates them once per five-minute boundary
# into an UNLOGGED shared snapshot. Web requests only count/filter/sort the
# compact one-row-per-VM snapshot and never rebuild the rollup CTE pipeline.

import json as _r2212_json
import math as _r2212_math
import os as _r2212_os
import threading as _r2212_threading
import time as _r2212_time

import node_groups as _r2212_node_groups

R2212_RELEASE = "50.5.9-prod-r22.12.1-preflight-contract-hotfix"
R2212_SLOT_SECONDS = max(60, safe_int(CACHE_BUCKET_SECONDS, 300))
R2212_MAX_STALE_SECONDS = max(
    R2212_SLOT_SECONDS,
    min(3600, safe_int(_r2212_os.environ.get("BW_VM_SNAPSHOT_MAX_STALE_SECONDS", "300"), 300)),
)
R2212_KEEP_GENERATIONS = max(
    2,
    min(24, safe_int(_r2212_os.environ.get("BW_VM_SNAPSHOT_KEEP_GENERATIONS", "4"), 4)),
)
R2212_SETTLE_SECONDS = max(
    30,
    min(240, safe_int(_r2212_os.environ.get("BW_VM_SNAPSHOT_SETTLE_SECONDS", "90"), 90)),
)
# Build the default 24H page first, then short windows, then the larger 2D/7D
# windows. Each period commits independently, so one slow long-range refresh
# cannot delay the common page from becoming ready.
R2212_BUILD_PERIODS = tuple(
    key for key in ("24h", "1h", "2h", "6h", "12h", "2d", "7d")
    if key in V5058C_PERIODS
)
R2212_BUILD_LOCK_PREFIX = "virtinfra:vm-consumption-snapshot:"

_r2212_async_lock = _r2212_threading.RLock()
_r2212_async_running = set()

def _r2212_normalized_end(value):
    return (safe_int(value, 0) // R2212_SLOT_SECONDS) * R2212_SLOT_SECONDS

def _r2212_stable_end(value=None):
    # Agent pushes can arrive seconds after the nominal five-minute boundary.
    # Build a settled boundary instead of freezing an incomplete snapshot too
    # early. Web accuracy remains at the existing five-minute cadence.
    base = safe_int(value if value is not None else now_ts(), 0)
    return _r2212_normalized_end(base - R2212_SETTLE_SECONDS)

def _r2212_period_key(start, end):
    seconds = max(R2212_SLOT_SECONDS, safe_int(end, 0) - safe_int(start, 0))
    for key, (_label, duration) in V5058C_PERIODS.items():
        if safe_int(duration, 0) == seconds:
            return key
    # The route only accepts V5058C_PERIODS. Keep a deterministic compatibility
    # fallback instead of allowing arbitrary cache cardinality.
    return "24h"

def _r2212_snapshot_ready(conn, period_key, window_end):
    row = conn.execute(
        """SELECT 1 FROM vm_consumption_snapshot_batches
             WHERE period_key=? AND window_end=? AND status='ready'""",
        (period_key, window_end),
    ).fetchone()
    return bool(row)

def _r2212_cleanup_generations(conn, period_key):
    keep = conn.execute(
        """SELECT window_end
             FROM vm_consumption_snapshot_batches
            WHERE period_key=? AND status='ready'
            ORDER BY window_end DESC
            LIMIT ?""",
        (period_key, R2212_KEEP_GENERATIONS),
    ).fetchall()
    if not keep:
        return
    cutoff = min(safe_int(row[0], 0) for row in keep)
    conn.execute(
        "DELETE FROM vm_consumption_snapshot_rows WHERE period_key=? AND window_end<?",
        (period_key, cutoff),
    )
    conn.execute(
        "DELETE FROM vm_consumption_snapshot_batches WHERE period_key=? AND window_end<?",
        (period_key, cutoff),
    )

def _r2212_build_snapshot(period_key, window_end=None):
    if period_key not in V5058C_PERIODS:
        raise ValueError("Unsupported VM snapshot period: %s" % period_key)
    seconds = safe_int(V5058C_PERIODS[period_key][1], 0)
    window_end = (
        _r2212_normalized_end(window_end)
        if window_end is not None
        else _r2212_stable_end()
    )
    window_start = window_end - seconds
    started_at = now_ts()
    conn = db()
    try:
        # This is a background cache refresh, never a web request. The request
        # statement timeout remains unchanged. Advisory transaction locking
        # guarantees one builder across all Gunicorn workers and the timer.
        conn.execute("SET LOCAL statement_timeout = '20min'")
        locked = conn.execute(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(?,0))",
            (R2212_BUILD_LOCK_PREFIX + period_key,),
        ).fetchone()
        if not locked or not bool(locked[0]):
            conn.rollback()
            return {"period": period_key, "window_end": window_end, "status": "locked"}
        if _r2212_snapshot_ready(conn, period_key, window_end):
            conn.rollback()
            return {"period": period_key, "window_end": window_end, "status": "ready"}

        conn.execute(
            """INSERT INTO vm_consumption_snapshot_batches(
                   period_key,window_start,window_end,status,row_count,
                   started_at,completed_at,error_text
               ) VALUES(?,?,?,'building',0,?,NULL,'')
               ON CONFLICT(period_key,window_end) DO UPDATE SET
                   window_start=excluded.window_start,status='building',row_count=0,
                   started_at=excluded.started_at,completed_at=NULL,error_text=''""",
            (period_key, window_start, window_end, started_at),
        )
        conn.execute(
            "DELETE FROM vm_consumption_snapshot_rows WHERE period_key=? AND window_end=?",
            (period_key, window_end),
        )

        ctes, params = _v5058c_vm_ctes(window_start, window_end, "")
        built_at = now_ts()
        conn.execute(
            ctes + """
              INSERT INTO vm_consumption_snapshot_rows(
                  period_key,window_start,window_end,node,vm_uuid,vm_name,node_ip,
                  public_configured,private_configured,
                  public_rx,public_tx,public_total,
                  private_rx,private_tx,private_total,
                  coverage_percent,latest_sample,built_at
              )
              SELECT ?,?,?,node,vm_uuid,COALESCE(vm_name,vm_uuid),COALESCE(node_ip,''),
                     public_configured,private_configured,
                     public_rx,public_tx,public_total,
                     private_rx,private_tx,private_total,
                     coverage_percent,latest_sample,?
                FROM vm_rows
            """,
            list(params) + [period_key, window_start, window_end, built_at],
        )
        row = conn.execute(
            """SELECT COUNT(*) FROM vm_consumption_snapshot_rows
                WHERE period_key=? AND window_end=?""",
            (period_key, window_end),
        ).fetchone()
        row_count = safe_int(row[0] if row else 0, 0)
        completed_at = now_ts()
        conn.execute(
            """UPDATE vm_consumption_snapshot_batches
                  SET status='ready',row_count=?,completed_at=?,error_text=''
                WHERE period_key=? AND window_end=?""",
            (row_count, completed_at, period_key, window_end),
        )
        _r2212_cleanup_generations(conn, period_key)
        conn.commit()
        return {
            "period": period_key,
            "window_start": window_start,
            "window_end": window_end,
            "row_count": row_count,
            "status": "built",
        }
    except Exception as exc:
        try:
            conn.rollback()
            conn.execute(
                """INSERT INTO vm_consumption_snapshot_batches(
                       period_key,window_start,window_end,status,row_count,
                       started_at,completed_at,error_text
                   ) VALUES(?,?,?,'failed',0,?,?,?)
                   ON CONFLICT(period_key,window_end) DO UPDATE SET
                       status='failed',completed_at=excluded.completed_at,
                       error_text=excluded.error_text""",
                (
                    period_key, window_start, window_end, started_at,
                    now_ts(), str(exc)[:1000],
                ),
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        conn.close()

def build_vm_consumption_snapshots(periods=None, window_end=None):
    requested = periods or R2212_BUILD_PERIODS
    result = []
    for period_key in requested:
        period_key = str(period_key or "").strip().lower()
        if period_key not in V5058C_PERIODS:
            continue
        try:
            result.append(_r2212_build_snapshot(period_key, window_end))
        except Exception as exc:
            result.append({"period": period_key, "status": "failed", "error": str(exc)[:1000]})
    return {"release": R2212_RELEASE, "snapshots": result}

def _r2212_async_build(period_key, window_end):
    token = (period_key, window_end)
    with _r2212_async_lock:
        if token in _r2212_async_running:
            return
        _r2212_async_running.add(token)

    def run():
        try:
            _r2212_build_snapshot(period_key, window_end)
        except Exception:
            app.logger.exception(
                "VM Consumption snapshot refresh failed period=%s end=%s",
                period_key, window_end,
            )
        finally:
            with _r2212_async_lock:
                _r2212_async_running.discard(token)

    _r2212_threading.Thread(
        target=run,
        name="vm-consumption-snapshot-%s" % period_key,
        daemon=True,
    ).start()

def _r2212_select_snapshot(conn, period_key, requested_end):
    row = conn.execute(
        """SELECT window_start,window_end,row_count,completed_at
             FROM vm_consumption_snapshot_batches
            WHERE period_key=? AND status='ready'
              AND window_end<=? AND window_end>=?
            ORDER BY window_end DESC
            LIMIT 1""",
        (period_key, requested_end, requested_end - R2212_MAX_STALE_SECONDS),
    ).fetchone()
    if row:
        return tuple(row)
    # Crash-safe fallback: UNLOGGED tables can be truncated by PostgreSQL after
    # an unclean restart. Do not revive the expensive request pipeline. Trigger
    # one advisory-locked asynchronous rebuild and return an empty page until
    # the shared snapshot is ready.
    _r2212_async_build(period_key, min(requested_end, _r2212_stable_end()))
    return None

def _r2212_search_where(q):
    q = str(q or "").strip()
    if not q:
        return "", []
    like = "%" + q + "%"
    normalized_mac = normalize_mac_address(q)
    mac_exact = " OR mil.mac=?" if normalized_mac else ""
    params = [like, like, like, like, like]
    if normalized_mac:
        params.append(normalized_mac)
    return """
      AND (
        LOWER(s.vm_name) LIKE LOWER(?) OR LOWER(s.vm_uuid) LIKE LOWER(?)
        OR LOWER(s.node) LIKE LOWER(?) OR LOWER(s.node_ip) LIKE LOWER(?)
        OR EXISTS(
          SELECT 1 FROM vm_nic_identity_lookup mil
           WHERE mil.node=s.node AND mil.vm_uuid=s.vm_uuid
             AND (LOWER(COALESCE(mil.mac,'')) LIKE LOWER(?)%s)
        )
      )
    """ % mac_exact, params

def _r2212_group_id():
    try:
        return max(0, safe_int(_r2212_node_groups.selected_group_id(), 0))
    except Exception:
        return 0

def _r2212_snapshot_where(period_key, window_end, selected_node, q, coverage):
    where = ["s.period_key=?", "s.window_end=?"]
    params = [period_key, window_end]
    if selected_node:
        where.append("s.node=?")
        params.append(selected_node)

    # Current visibility remains authoritative even between snapshot refreshes.
    # These are indexed EXISTS checks against compact inventory, not joins to
    # hourly/daily history and not part of the aggregate build pipeline.
    where.append("""EXISTS (
        SELECT 1 FROM node_inventory ni
         WHERE ni.node=s.node
           AND COALESCE(ni.status,'active')!='hidden'
           AND ni.deleted_at IS NULL
    )""")
    where.append("""EXISTS (
        SELECT 1 FROM vm_inventory vi
         WHERE vi.node=s.node AND vi.vm_uuid=s.vm_uuid
           AND COALESCE(vi.status,'active')!='hidden'
           AND vi.deleted_at IS NULL
    )""")

    # Preserve the current Node Groups behavior: even without a selected group,
    # VM Consumption only exposes nodes inherited by an active group.
    gid = _r2212_group_id()
    group_sql = """
      EXISTS (
        SELECT 1
          FROM node_group_memberships gm
          JOIN node_groups g ON g.id=gm.group_id
         WHERE gm.node=s.node AND g.is_active=1
    """
    if gid:
        group_sql += " AND g.id=?"
        params.append(gid)
    group_sql += ")"
    where.append(group_sql)

    search_sql, search_params = _r2212_search_where(q)
    params.extend(search_params)

    coverage = _v5058c_coverage(coverage)
    if coverage == "complete":
        where.extend(["s.latest_sample>0", "s.coverage_percent>=99.5"])
    elif coverage == "partial":
        where.extend(["s.latest_sample>0", "s.coverage_percent<99.5"])
    elif coverage == "no_data":
        where.append("s.latest_sample<=0")

    return " WHERE " + " AND ".join(where) + search_sql, params

R2212_VM_SORTS = {
    "uuid": "s.vm_uuid",
    "node": "s.node",
    "public_rx": "s.public_rx",
    "public_tx": "s.public_tx",
    "public_total": "s.public_total",
    "private_rx": "s.private_rx",
    "private_tx": "s.private_tx",
    "private_total": "s.private_total",
    "coverage": "s.coverage_percent",
    "latest_sample": "s.latest_sample",
}

def _v5058c_vm_rows(start, end, selected_node, q, coverage, sort_by, order, page_no, limit):
    period_key = _r2212_period_key(start, end)
    requested_end = _r2212_normalized_end(end)
    page_no = max(1, safe_int(page_no, 1))
    limit = max(1, safe_int(limit, 100))
    order = "asc" if str(order or "").lower() == "asc" else "desc"
    sort_by = sort_by if sort_by in R2212_VM_SORTS else "public_total"

    conn = db()
    try:
        snapshot = _r2212_select_snapshot(conn, period_key, requested_end)
        if not snapshot:
            return [], 0, 1, 1
        _window_start, snapshot_end, _row_count, _completed_at = snapshot
        if snapshot_end < requested_end:
            refresh_end = min(requested_end, _r2212_stable_end())
            if refresh_end > snapshot_end:
                _r2212_async_build(period_key, refresh_end)

        where_sql, params = _r2212_snapshot_where(
            period_key, snapshot_end, selected_node, q, coverage,
        )
        count_row = conn.execute(
            "SELECT COUNT(*) FROM vm_consumption_snapshot_rows s" + where_sql,
            params,
        ).fetchone()
        total = safe_int(count_row[0] if count_row else 0, 0)
        max_page = max(1, int(_r2212_math.ceil(total / float(limit))))
        page_no = min(page_no, max_page)
        offset = (page_no - 1) * limit
        order_column = R2212_VM_SORTS[sort_by]
        tie_order = "ASC" if sort_by in {"uuid", "node"} and order == "asc" else "DESC"
        rows = conn.execute(
            """SELECT s.vm_uuid,s.node,s.node_ip,
                      s.public_configured,s.private_configured,
                      s.public_rx,s.public_tx,s.public_total,
                      s.private_rx,s.private_tx,s.private_total,
                      s.coverage_percent,s.latest_sample
                 FROM vm_consumption_snapshot_rows s"""
            + where_sql
            + " ORDER BY %s %s,s.vm_uuid %s LIMIT ? OFFSET ?" % (
                order_column, order.upper(), tie_order,
            ),
            params + [limit, offset],
        ).fetchall()
        return [tuple(row) for row in rows], total, page_no, max_page
    finally:
        conn.close()
