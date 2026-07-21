
V48133_VERSION = "48.13.3"
V48133_DISK_SORT_KEYS = {"diskallocated", "diskassigned", "diskallocpct", "diskcount"}

# R22: Top VM global sort reads only the existing bounded current/snapshot
# tables.  Filtering and ORDER BY happen in PostgreSQL before LIMIT, so RAM
# and disk rankings are no longer limited to a network-selected 1,000-row
# candidate set.  No second current-state table or dual-write path is added.
_get_top_vm_rows_v48133_base = get_top_vm_rows

_R22_RAM_VALID = """(
    COALESCE({a}.ram_available_kib,0)>0
    AND (COALESCE({a}.ram_usable_kib,0)>0 OR COALESCE({a}.ram_unused_kib,0)>0)
    AND COALESCE({a}.ram_usable_kib,0)<=COALESCE({a}.ram_available_kib,0)*1.05
)"""

def _r22_ram_sort_expressions(alias="c"):
    valid = _R22_RAM_VALID.format(a=alias)
    guest_used = (
        f"CASE WHEN {valid} THEN "
        f"MAX(COALESCE({alias}.ram_available_kib,0)-COALESCE({alias}.ram_usable_kib,0),0) END"
    )
    guest_pct = (
        f"CASE WHEN {valid} THEN "
        f"MAX(COALESCE({alias}.ram_available_kib,0)-COALESCE({alias}.ram_usable_kib,0),0)"
        f"*100.0/COALESCE({alias}.ram_available_kib,1) END"
    )
    return {
        "ram": guest_pct,
        "ramguest": guest_pct,
        "ramused": guest_used,
        "ramrss": f"NULLIF(COALESCE({alias}.ram_rss_kib,0),0)",
        "ramassigned": f"NULLIF(COALESCE({alias}.ram_current_kib,0),0)",
    }

def _r22_disk_sort_expressions(alias="d"):
    present = (
        f"({alias}.node IS NOT NULL AND (COALESCE({alias}.disk_count,0)>0 "
        f"OR COALESCE({alias}.allocated_bytes,0)>0 OR COALESCE({alias}.assigned_bytes,0)>0))"
    )
    return {
        "diskallocated": f"CASE WHEN {present} THEN COALESCE({alias}.allocated_bytes,0) END",
        "diskassigned": f"CASE WHEN {present} THEN COALESCE({alias}.assigned_bytes,0) END",
        "diskallocpct": (
            f"CASE WHEN {present} AND COALESCE({alias}.assigned_bytes,0)>0 "
            f"THEN COALESCE({alias}.allocated_bytes,0)*1.0/{alias}.assigned_bytes END"
        ),
        "diskcount": f"CASE WHEN {present} THEN COALESCE({alias}.disk_count,0) END",
    }

def _r22_top_order_expression(sort_by, live=True):
    alias = "c" if live else "b"
    values = {
        "total": f"{alias}.total_bytes" if live else "b.total",
        "rx": f"{alias}.rx_bytes" if live else "b.rx",
        "tx": f"{alias}.tx_bytes" if live else "b.tx",
        "public": (
            f"({alias}.public_rx_bytes+{alias}.public_tx_bytes)" if live else "b.public_total"
        ),
        "private": (
            f"({alias}.private_rx_bytes+{alias}.private_tx_bytes)" if live else "b.private_total"
        ),
        "mbps": f"{alias}.total_mbps" if live else "b.avg_mbps",
        "peakmbps": f"{alias}.total_peak_mbps" if live else "b.peak_mbps",
        "pps": f"{alias}.total_pps" if live else "b.avg_pps",
        "peakpps": f"{alias}.total_peak_pps" if live else "b.peak_pps",
        "sample": (
            f"CASE UPPER(COALESCE({alias}.sample_quality,'LEGACY')) "
            "WHEN 'POOR' THEN 3 WHEN 'DEGRADED' THEN 2 WHEN 'GOOD' THEN 1 ELSE 0 END"
            if live else "b.sample_quality_rank"
        ),
        "drops": f"{alias}.drops" if live else "b.drops",
        "errors": f"{alias}.errors" if live else "b.errors",
        "cpu": f"{alias}.cpu_core_percent" if live else "b.core_cpu_percent",
        "cpufull": f"{alias}.cpu_full_percent" if live else "b.cpu_percent",
        "vcpu": f"{alias}.vcpu_current" if live else "b.vcpu_current",
        "diskr": f"{alias}.disk_read_bps" if live else "b.disk_read_bps",
        "diskw": f"{alias}.disk_write_bps" if live else "b.disk_write_bps",
        "last_push": f"{alias}.last_seen" if live else "b.last_push",
        "node": f"{alias}.node COLLATE NOCASE",
        "vm": f"{alias}.vm_uuid COLLATE NOCASE",
    }
    values.update(_r22_ram_sort_expressions(alias))
    values.update(_r22_disk_sort_expressions("d"))
    return values[sort_by]

def _r22_top_visibility_sql(node_expr, group_id):
    sql = f"""
      AND EXISTS (
            SELECT 1
              FROM node_group_memberships r22gm
              JOIN node_groups r22g ON r22g.id=r22gm.group_id
             WHERE r22gm.node={node_expr}
               AND r22g.is_active=1
      )
    """
    params = []
    if safe_int(group_id, 0) > 0:
        sql += f"""
          AND EXISTS (
                SELECT 1
                  FROM node_group_memberships r22sgm
                  JOIN node_groups r22sg ON r22sg.id=r22sgm.group_id
                 WHERE r22sgm.node={node_expr}
                   AND r22sg.is_active=1
                   AND r22sg.id=?
          )
        """
        params.append(safe_int(group_id, 0))
    return sql, params

def _r22_get_top_vm_rows_live(q, sort_by, order, scope, limit, group_id=0):
    params = [now_ts() - FAST_CURRENT_STALE_SECONDS]
    where_sql, visibility_params = _r22_top_visibility_sql("c.node", group_id)
    params.extend(visibility_params)
    if scope == "public":
        where_sql += " AND (c.public_rx_bytes+c.public_tx_bytes)>0"
    elif scope == "private":
        where_sql += " AND (c.private_rx_bytes+c.private_tx_bytes)>0"
    if q:
        pattern = like_pattern(q)
        where_sql += """ AND (
              c.node LIKE ? OR c.vm_uuid LIKE ?
              OR EXISTS (
                    SELECT 1 FROM vm_iface_current r22if
                     WHERE r22if.node=c.node AND r22if.vm_uuid=c.vm_uuid
                       AND (COALESCE(r22if.iface,'') LIKE ? OR COALESCE(r22if.mac,'') LIKE ?)
              )
              OR EXISTS (
                    SELECT 1 FROM node_bridge_addresses_latest r22ba
                     WHERE r22ba.node=c.node
                       AND (COALESCE(r22ba.primary_ipv4,'') LIKE ? OR COALESCE(r22ba.ipv4_json,'[]') LIKE ?)
              )
        )"""
        params.extend([pattern] * 6)
    order_expr = _r22_top_order_expression(sort_by, live=True)
    params.append(limit)
    conn = db()
    try:
        try:
            _v48140_reconcile_summaries_if_needed(conn)
        except Exception:
            app.logger.exception("R22 Top VM disk-summary reconciliation failed")
        rows = conn.execute(f"""
          SELECT c.node,c.vm_uuid,c.iface_count,
                 c.public_rx_bytes+c.public_tx_bytes,
                 c.private_rx_bytes+c.private_tx_bytes,
                 c.rx_bytes,c.tx_bytes,c.total_bytes,
                 CAST(c.total_pps*c.interval_seconds AS INTEGER),c.drops,c.errors,
                 c.total_mbps,c.total_peak_mbps,c.total_pps,c.total_peak_pps,
                 c.sample_count,c.sample_expected,c.sample_max_gap,
                 c.seconds_over_rx_pps+c.seconds_over_tx_pps,0,
                 CASE UPPER(COALESCE(c.sample_quality,'LEGACY'))
                   WHEN 'POOR' THEN 3 WHEN 'DEGRADED' THEN 2 WHEN 'GOOD' THEN 1 ELSE 0 END,
                 c.cpu_full_percent,c.vcpu_current,c.cpu_core_percent,
                 c.ram_rss_kib,c.ram_current_kib,c.disk_read_bps,c.disk_write_bps,
                 c.last_seen,c.interval_seconds,
                 COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest ba
                            WHERE ba.node=c.node AND LOWER(ba.role)='public'
                            ORDER BY ba.last_seen DESC LIMIT 1),''),
                 COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest ba
                            WHERE ba.node=c.node AND LOWER(ba.role)='private'
                            ORDER BY ba.last_seen DESC LIMIT 1),''),
                 COALESCE(c.ram_available_kib,0),COALESCE(c.ram_unused_kib,0),COALESCE(c.ram_usable_kib,0),
                 COALESCE(d.allocated_bytes,0),COALESCE(d.assigned_bytes,0),COALESCE(d.disk_count,0)
            FROM vm_current_fast c
            LEFT JOIN node_inventory ni ON ni.node=c.node
            LEFT JOIN vm_inventory vi ON vi.node=c.node AND vi.vm_uuid=c.vm_uuid
            LEFT JOIN vm_disk_summary_current d ON d.node=c.node AND d.vm_uuid=c.vm_uuid
           WHERE c.last_seen>=?
             AND (ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))
             AND (vi.vm_uuid IS NULL OR (COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL))
             {where_sql}
           ORDER BY {order_expr} {order.upper()} NULLS LAST,
                    c.node COLLATE NOCASE ASC,c.vm_uuid COLLATE NOCASE ASC
           LIMIT ?
        """, params).fetchall()
        latest = max([safe_int(row[28], 0) for row in rows] or [0])
        return rows, latest, latest, limit
    finally:
        conn.close()

def _r22_get_top_vm_rows_history(period, q, sort_by, order, scope, limit, group_id=0):
    auto_cleanup_inventory()
    conn = db()
    try:
        selected_bucket, latest_bucket = resolve_snapshot_bucket(conn, period, node=None)
        if not selected_bucket:
            return [], 0, 0, limit
        try:
            _v48140_reconcile_summaries_if_needed(conn)
        except Exception:
            app.logger.exception("R22 historical Top VM disk-summary reconciliation failed")

        # Keep the historical snapshot formulas and scope semantics unchanged;
        # only visibility, complete metric enrichment, SQL ordering and LIMIT
        # placement are hardened.
        params = [
            CACHE_BUCKET_SECONDS, CACHE_BUCKET_SECONDS, selected_bucket,
            PUBLIC_BRIDGE, PRIVATE_BRIDGE,
            CACHE_BUCKET_SECONDS, CACHE_BUCKET_SECONDS, selected_bucket,
        ]
        source_where = ""
        if scope == "public":
            source_where += " AND ns.bridge=?"
            params.append(PUBLIC_BRIDGE)
        elif scope == "private":
            source_where += " AND ns.bridge=?"
            params.append(PRIVATE_BRIDGE)
        if q:
            pattern = like_pattern(q)
            source_where += """ AND (
                ns.node LIKE ? OR ns.vm_uuid LIKE ? OR ns.iface LIKE ?
                OR EXISTS (
                    SELECT 1 FROM node_bridge_addresses_latest r22ba
                     WHERE r22ba.node=ns.node
                       AND (COALESCE(r22ba.primary_ipv4,'') LIKE ? OR COALESCE(r22ba.ipv4_json,'[]') LIKE ?)
                )
            )"""
            params.extend([pattern] * 5)
        visibility_sql, visibility_params = _r22_top_visibility_sql("b.node", group_id)
        params.extend(visibility_params)
        order_expr = _r22_top_order_expression(sort_by, live=False)
        params.append(limit)
        rows = conn.execute(f"""
          WITH perf AS (
            SELECT node,vm_uuid,
                   MAX(COALESCE(cpu_percent,0)) cpu_percent,
                   MAX(COALESCE(vcpu_current,0)) vcpu_current,
                   MAX(COALESCE(ram_rss_kib,0)) ram_rss_kib,
                   MAX(COALESCE(ram_current_kib,0)) ram_current_kib,
                   MAX(COALESCE(ram_available_kib,0)) ram_available_kib,
                   MAX(COALESCE(ram_unused_kib,0)) ram_unused_kib,
                   MAX(COALESCE(ram_usable_kib,0)) ram_usable_kib,
                   MAX(COALESCE(disk_read_delta,0)*1.0/MAX(COALESCE(interval_seconds,?),1)) disk_read_bps,
                   MAX(COALESCE(disk_write_delta,0)*1.0/MAX(COALESCE(interval_seconds,?),1)) disk_write_bps
              FROM vm_perf_stats
             WHERE bucket=?
             GROUP BY node,vm_uuid
          ), base AS (
            SELECT ns.node,ns.vm_uuid,
                   COUNT(DISTINCT ns.bridge||':'||ns.iface) iface_count,
                   SUM(CASE WHEN ns.bridge=? THEN ns.rx_delta+ns.tx_delta ELSE 0 END) public_total,
                   SUM(CASE WHEN ns.bridge=? THEN ns.rx_delta+ns.tx_delta ELSE 0 END) private_total,
                   SUM(ns.rx_delta) rx,SUM(ns.tx_delta) tx,SUM(ns.rx_delta+ns.tx_delta) total,
                   SUM(ns.rx_packets_delta+ns.tx_packets_delta) packets,
                   SUM(ns.rx_drop_delta+ns.tx_drop_delta) drops,
                   SUM(ns.rx_error_delta+ns.tx_error_delta) errors,
                   SUM((ns.rx_delta+ns.tx_delta)*8.0/MAX(COALESCE(ns.interval_seconds,1),1)/1000000.0) avg_mbps,
                   MAX(MAX(COALESCE(ns.rx_mbps_peak,0),COALESCE(ns.tx_mbps_peak,0))) peak_mbps,
                   SUM(ns.rx_packets_delta+ns.tx_packets_delta)*1.0/MAX(MAX(COALESCE(ns.interval_seconds,?)),1) avg_pps,
                   MAX(MAX(COALESCE(ns.rx_pps_peak,0),COALESCE(ns.tx_pps_peak,0))) peak_pps,
                   SUM(COALESCE(ns.network_sample_count,0)) sample_count,
                   SUM(COALESCE(ns.network_sample_expected,0)) sample_expected,
                   MAX(COALESCE(ns.network_sample_max_gap_seconds,0)) sample_max_gap_seconds,
                   SUM(COALESCE(ns.seconds_over_pps,0)) seconds_over_pps,
                   SUM(COALESCE(ns.seconds_over_mbps,0)) seconds_over_mbps,
                   MAX(CASE UPPER(COALESCE(ns.network_sample_quality,'LEGACY'))
                         WHEN 'POOR' THEN 3 WHEN 'DEGRADED' THEN 2 WHEN 'GOOD' THEN 1 ELSE 0 END) sample_quality_rank,
                   MAX(COALESCE(p.cpu_percent,0)) cpu_percent,
                   MAX(COALESCE(p.vcpu_current,0)) vcpu_current,
                   MAX(CASE WHEN COALESCE(p.cpu_percent,0)<=100
                            THEN COALESCE(p.cpu_percent,0)*CASE WHEN COALESCE(p.vcpu_current,0)>0 THEN p.vcpu_current ELSE 1 END
                            ELSE COALESCE(p.cpu_percent,0) END) core_cpu_percent,
                   MAX(COALESCE(p.ram_rss_kib,0)) ram_rss_kib,
                   MAX(COALESCE(p.ram_current_kib,0)) ram_current_kib,
                   MAX(COALESCE(p.ram_available_kib,0)) ram_available_kib,
                   MAX(COALESCE(p.ram_unused_kib,0)) ram_unused_kib,
                   MAX(COALESCE(p.ram_usable_kib,0)) ram_usable_kib,
                   MAX(COALESCE(p.disk_read_bps,0)) disk_read_bps,
                   MAX(COALESCE(p.disk_write_bps,0)) disk_write_bps,
                   MAX(ns.last_push) last_push,
                   MAX(COALESCE(ns.interval_seconds,?)) interval_seconds,
                   COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest ba
                              WHERE ba.node=ns.node AND LOWER(ba.role)='public'
                              ORDER BY ba.last_seen DESC LIMIT 1),'') public_ipv4,
                   COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest ba
                              WHERE ba.node=ns.node AND LOWER(ba.role)='private'
                              ORDER BY ba.last_seen DESC LIMIT 1),'') private_ipv4
              FROM node_stats ns
              LEFT JOIN perf p ON p.node=ns.node AND p.vm_uuid=ns.vm_uuid
             WHERE ns.bucket=? {source_where}
             GROUP BY ns.node,ns.vm_uuid
            HAVING SUM(COALESCE(ns.rx_delta,0)+COALESCE(ns.tx_delta,0))>0
          )
          SELECT b.node,b.vm_uuid,b.iface_count,b.public_total,b.private_total,
                 b.rx,b.tx,b.total,b.packets,b.drops,b.errors,b.avg_mbps,b.peak_mbps,b.avg_pps,b.peak_pps,
                 b.sample_count,b.sample_expected,b.sample_max_gap_seconds,b.seconds_over_pps,b.seconds_over_mbps,
                 b.sample_quality_rank,b.cpu_percent,b.vcpu_current,b.core_cpu_percent,
                 b.ram_rss_kib,b.ram_current_kib,b.disk_read_bps,b.disk_write_bps,
                 b.last_push,b.interval_seconds,b.public_ipv4,b.private_ipv4,
                 b.ram_available_kib,b.ram_unused_kib,b.ram_usable_kib,
                 COALESCE(d.allocated_bytes,0),COALESCE(d.assigned_bytes,0),COALESCE(d.disk_count,0)
            FROM base b
            LEFT JOIN node_inventory ni ON ni.node=b.node
            LEFT JOIN vm_inventory vi ON vi.node=b.node AND vi.vm_uuid=b.vm_uuid
            LEFT JOIN vm_disk_summary_current d ON d.node=b.node AND d.vm_uuid=b.vm_uuid
           WHERE (ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))
             AND (vi.vm_uuid IS NULL OR (COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL))
             {visibility_sql}
           ORDER BY {order_expr} {order.upper()} NULLS LAST,
                    b.node COLLATE NOCASE ASC,b.vm_uuid COLLATE NOCASE ASC
           LIMIT ?
        """, params).fetchall()
        return rows, selected_bucket, latest_bucket, limit
    finally:
        conn.close()

def _r22_get_top_vm_rows_global(period, q="", sort_by="total", order="desc", scope="all", limit=100, group_id=0):
    requested_sort = clean_top_sort(str(sort_by or "").strip().lower())
    requested_order = clean_sort_order(order)
    requested_scope = clean_top_scope(scope)
    requested_limit = max(10, min(1000, safe_int(limit, 100)))
    history = _request_target_ts() is not None or clean_period(period) != "5m"
    if history:
        return _r22_get_top_vm_rows_history(
            period, q, requested_sort, requested_order, requested_scope,
            requested_limit, group_id=group_id,
        )
    return _r22_get_top_vm_rows_live(
        q, requested_sort, requested_order, requested_scope,
        requested_limit, group_id=group_id,
    )

def get_top_vm_rows(period, q="", sort_by="total", order="desc", scope="all", limit=100):
    return _r22_get_top_vm_rows_global(
        period, q=q, sort_by=sort_by, order=order, scope=scope,
        limit=limit, group_id=0,
    )

def _v48133_disk_sort_link(label, key, period, q, current_sort, current_order, scope, limit):
    active = current_sort == key
    next_order = "asc" if active and clean_sort_order(current_order) == "desc" else "desc"
    arrow = " ↓" if active and clean_sort_order(current_order) == "desc" else (" ↑" if active else "")
    params = {
        "period": period,
        "q": q,
        "sort": key,
        "order": next_order,
        "scope": scope,
        "limit": limit,
    }
    at = (request.args.get("at") or "").strip()
    if at:
        params["at"] = at
    return f'<a class="sort-link disk-cap-sort-link" href="{escape(url_for("top_page", **params), quote=True)}">{escape(label)}{arrow}</a>'

def _v48133_top_disk_capacity(allocated, assigned, count):
    allocated = max(0, safe_int(allocated, 0))
    assigned = max(0, safe_int(assigned, 0))
    count = max(0, safe_int(count, 0))
    if count <= 0 and allocated <= 0 and assigned <= 0:
        return '<div class="top-disk-capacity top-disk-na"><b>N/A</b><small>No customer disk data</small></div>'
    pct = allocated * 100.0 / assigned if assigned > 0 else 0.0
    level = ""
    if pct >= 90:
        level = " disk-cap-critical"
    elif pct >= 75:
        level = " disk-cap-hot"
    elif pct >= 50:
        level = " disk-cap-warm"
    return (
        f'<div class="top-disk-capacity{level}">'
        f'<b>{_disk_io_bytes(allocated)} <span>/ {_disk_io_bytes(assigned)}</span></b>'
        f'<div class="disk-cap-meter"><i style="width:{min(100.0, max(0.0, pct)):.1f}%"></i></div>'
        f'<small>{pct:.1f}% · {count} slot{"s" if count != 1 else ""}</small>'
        f'</div>'
    )

V48133_TOP_CSS = r'''
<style id="v48134-top-disk-capacity">
body.app-v490.endpoint-top-page .table-top-vm{min-width:2185px!important;table-layout:fixed!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-rank{width:30px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-node{width:135px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-uuid{width:290px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-ifaces{width:48px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-public,body.app-v490.endpoint-top-page .table-top-vm col.top-private{width:78px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-total{width:88px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-mbps{width:72px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-peakmbps{width:76px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-pps{width:78px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-peakpps{width:82px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-sample{width:96px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-cpu{width:112px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-vcpu{width:44px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-ram{width:168px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-diskcap{width:190px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-diskr,body.app-v490.endpoint-top-page .table-top-vm col.top-diskw{width:86px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-push{width:58px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-drops{width:46px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-errors{width:42px!important}
body.app-v490.endpoint-top-page .table-top-vm th,body.app-v490.endpoint-top-page .table-top-vm td{padding-left:8px!important;padding-right:8px!important}
body.app-v490.endpoint-top-page .table-top-vm .rank-cell{font-size:10px!important;padding-left:3px!important;padding-right:3px!important}
body.app-v490.endpoint-top-page .table-top-vm .uuid-cell>a{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.disk-cap-compact-head{display:grid;gap:4px;justify-items:center}.disk-cap-compact-head>div{font-weight:950;white-space:nowrap;font-size:10px}.disk-cap-compact-head small{display:flex;gap:3px;align-items:center;justify-content:center;white-space:nowrap}.disk-cap-sort-link{font-size:8.5px!important;padding:1px!important}
.top-disk-capacity{min-width:0;text-align:left}.top-disk-capacity>b{display:block;font-size:11px;line-height:1.15;white-space:nowrap}.top-disk-capacity>b span{font-size:9px;color:#667085}.top-disk-capacity .disk-cap-meter{height:5px;margin-top:6px}.top-disk-capacity small{display:block;margin-top:4px;font-size:8px;color:#667085;white-space:nowrap}.top-disk-na{text-align:center}.top-disk-na b{color:#98a2b3}
html[data-theme=dark] .top-disk-capacity>b span,html[data-theme=dark] .top-disk-capacity small{color:#9fb0c4}
</style>
'''

def top_vm_table(rows, period, q, sort_by, order, scope, limit):
    body = ""
    for rank, row in enumerate(rows, 1):
        (
            node, vm_uuid, iface_count, public_total, private_total, rx, tx, total,
            packets, drops, errors, avg_mbps, peak_mbps, avg_pps, peak_pps,
            sample_count, sample_expected, sample_max_gap, seconds_over_pps, seconds_over_mbps,
            sample_quality_rank, cpu_full_percent, vcpu_current, cpu_core_percent,
            ram_rss_kib, ram_current_kib, disk_read_bps, disk_write_bps,
            last_push, interval_seconds, public_ipv4, private_ipv4,
            ram_available_kib, ram_unused_kib, ram_usable_kib,
            disk_allocated_bytes, disk_assigned_bytes, disk_count,
        ) = row
        row_at = (request.args.get("at") or "").strip()
        node_href = url_for("node_page", node=node, period=period, q=vm_uuid, **({"at": row_at} if row_at else {}))
        vm_href = url_for("vm_page", node=node, vm_uuid=vm_uuid, period=period, **({"at": row_at} if row_at else {}))
        public_ip = compact_ipv4(public_ipv4)
        ip_lines = f'<small class="node-ipv4" title="Public IPv4">{escape(public_ip)}</small>' if public_ip else ""
        sample = network_sample_badge(network_quality_from_rank(sample_quality_rank), sample_count, sample_expected, sample_max_gap)
        core_value = max(0.0, safe_float(cpu_core_percent, 0.0))
        full_value = max(0.0, safe_float(cpu_full_percent, 0.0))
        cpu_level = _v48102_cpu_level(full_value)
        cpu_bar = min(100.0, full_value)
        ram_html = fmt_vm_ram_block(ram_current_kib, ram_rss_kib, ram_available_kib, ram_unused_kib, ram_usable_kib, compact=True)
        disk_cap_html = _v48133_top_disk_capacity(disk_allocated_bytes, disk_assigned_bytes, disk_count)
        body += f"""
        <tr>
          <td class="num rank-cell">{rank}</td>
          <td class="mono"><div class="node-name-cell"><a href="{escape(node_href,quote=True)}"><b>{escape(node)}</b></a>{ip_lines}</div></td>
          <td class="mono"><span class="uuid-cell"><a href="{escape(vm_href,quote=True)}" title="{escape(vm_uuid)}">{escape(vm_uuid)}</a><button type="button" class="copy-btn" data-copy="{escape(vm_uuid)}" title="Copy UUID">⧉</button></span></td>
          <td class="num">{iface_count or 0}</td><td class="num">{human(public_total)}</td><td class="num">{human(private_total)}</td><td class="num"><b>{human(total)}</b></td>
          <td class="num">{float(avg_mbps or 0):.2f}</td><td class="num"><b>{float(peak_mbps or 0):.2f}</b></td><td class="num">{fmt_pps_value(avg_pps)}</td><td class="num"><b>{fmt_pps_value(peak_pps)}</b></td><td class="num sample-cell">{sample}</td>
          <td class="num cpu-dual-cell cpu-{cpu_level}"><b class="cpu-core-value">{core_value:.1f}%</b><small class="cpu-full-value">{full_value:.1f}% FULL</small><span class="cpu-meter"><i style="width:{cpu_bar:.1f}%"></i></span></td>
          <td class="num">{int(vcpu_current or 0)}</td><td class="num ram-cell">{ram_html}</td><td class="disk-cap-cell">{disk_cap_html}</td><td class="num">{human_rate(disk_read_bps)}</td><td class="num">{human_rate(disk_write_bps)}</td><td class="num">{fmt_push(last_push)}</td><td class="num">{int(drops or 0)}</td><td class="num">{int(errors or 0)}</td>
        </tr>"""
    if not body:
        body = '<tr><td colspan="21" class="empty">No VM data at this selected snapshot</td></tr>'
    h = lambda label, key: top_sort_header(label, key, period, q, sort_by, order, scope, limit)
    cpu_core_sort = _v48102_top_sort_link("CORE%", "cpu", period, q, sort_by, order, scope, limit)
    cpu_full_sort = _v48102_top_sort_link("FULL%", "cpufull", period, q, sort_by, order, scope, limit)
    ram_header = _v48104_ram_sort_header(
        _v48103_top_ram_link("RAM", "ram", period, q, sort_by, order, scope, limit),
        [
            _v48103_top_ram_link("Guest %", "ram", period, q, sort_by, order, scope, limit),
            _v48103_top_ram_link("Used GiB", "ramused", period, q, sort_by, order, scope, limit),
            _v48103_top_ram_link("Host RSS", "ramrss", period, q, sort_by, order, scope, limit),
            _v48103_top_ram_link("Assigned", "ramassigned", period, q, sort_by, order, scope, limit),
        ], sort_by, order,
    )
    disk_header = (
        '<div class="disk-cap-compact-head"><div>ALLOCATED / ASSIGNED</div><small>'
        + _v48133_disk_sort_link("ALLOC", "diskallocated", period, q, sort_by, order, scope, limit)
        + '<span> · </span>'
        + _v48133_disk_sort_link("ASSIGNED", "diskassigned", period, q, sort_by, order, scope, limit)
        + '<span> · </span>'
        + _v48133_disk_sort_link("%", "diskallocpct", period, q, sort_by, order, scope, limit)
        + '<span> · </span>'
        + _v48133_disk_sort_link("SLOTS", "diskcount", period, q, sort_by, order, scope, limit)
        + '</small></div>'
    )
    return V48133_TOP_CSS + f"""
    <div class="card vm-table-card top-vm-v48102 top-vm-v48103 top-vm-v48133">
      <div class="table-title-row"><h3>Top VM Across All Nodes</h3><div class="count-badges"><span>Rows <b>{len(rows)}</b></span><span>Scope <b>{escape(scope)}</b></span><span>Refresh <b>5s partial</b></span><span>Sort <b>{escape(sort_by)} {escape(order)}</b></span></div></div>
      <div class="table-wrap"><table class="table-top-vm"><colgroup><col class="top-rank"><col class="top-node"><col class="top-uuid"><col class="top-ifaces"><col class="top-public"><col class="top-private"><col class="top-total"><col class="top-mbps"><col class="top-peakmbps"><col class="top-pps"><col class="top-peakpps"><col class="top-sample"><col class="top-cpu"><col class="top-vcpu"><col class="top-ram"><col class="top-diskcap"><col class="top-diskr"><col class="top-diskw"><col class="top-push"><col class="top-drops"><col class="top-errors"></colgroup>
      <thead><tr><th>#</th><th>{h('NODE','node')}</th><th>{h('VM UUID','vm')}</th><th>IFACES</th><th class="num-head">{h('PUBLIC','public')}</th><th class="num-head">{h('PRIVATE','private')}</th><th class="num-head">{h('TOTAL','total')}</th><th class="num-head">{h('AVG Mbps','mbps')}</th><th class="num-head">{h('PEAK Mbps','peakmbps')}</th><th class="num-head">{h('AVG PPS','pps')}</th><th class="num-head">{h('PEAK PPS','peakpps')}</th><th class="num-head">{h('SAMPLE','sample')}</th><th class="num-head cpu-dual-head"><div>CPU</div><small>{cpu_core_sort}<span> · </span>{cpu_full_sort}</small></th><th class="num-head">{h('vCPU','vcpu')}</th><th class="num-head ram-compact-sort-head">{ram_header}</th><th class="num-head disk-capacity-sort-head">{disk_header}</th><th class="num-head">{h('DISK R/s','diskr')}</th><th class="num-head">{h('DISK W/s','diskw')}</th><th class="num-head">{h('PUSH','last_push')}</th><th class="num-head">{h('DROPS','drops')}</th><th class="num-head">{h('ERR','errors')}</th></tr></thead><tbody>{body}</tbody></table></div>
      <div class="table-hint">RAM shows <b>Guest Used / Assigned</b>. Disk capacity shows total <b>Host Allocated / Assigned</b> across customer disks. Click the UUID to open per-disk capacity and I/O details.</div>
    </div>"""

def _v48133_vm_disks(node, vm_uuid):
    """Return per-disk capacity and I/O for the selected VM snapshot."""
    period = clean_period(request.args.get("period", "5m"))
    conn = db()
    try:
        payload, selected_bucket, latest_bucket = _v5054_selected_storage_payload(conn, node, period)
        if payload:
            seen = safe_int(payload.get("t"), selected_bucket)
            rows = []
            for item in payload.get("d") or []:
                if not isinstance(item, (list, tuple)) or len(item) < 14:
                    continue
                (
                    payload_vm_uuid, target, source, mount, storage_device,
                    storage_block, storage_fstype, capacity_bytes,
                    allocation_bytes, physical_bytes, read_bps, write_bps,
                    read_iops, write_iops,
                ) = item[:14]
                if str(payload_vm_uuid or "") != vm_uuid:
                    continue
                rows.append((
                    str(target or ""), str(source or ""), str(mount or ""),
                    str(storage_device or ""), str(storage_block or ""),
                    str(storage_fstype or ""),
                    max(0, safe_int(capacity_bytes, 0)),
                    max(0, safe_int(allocation_bytes, 0)),
                    max(0, safe_int(physical_bytes, 0)),
                    max(0.0, safe_float(read_bps, 0.0)),
                    max(0.0, safe_float(write_bps, 0.0)),
                    max(0.0, safe_float(read_iops, 0.0)),
                    max(0.0, safe_float(write_iops, 0.0)),
                    seen,
                ))
            rows.sort(key=lambda r: (0 if r[0] == "vda" else 1 if r[0] == "vdb" else 2, r[0].lower(), r[1].lower()))
            return rows

        # Do not present current disk rates as historical data. Current-table
        # fallback is permitted only for the newest 5-minute page.
        live_request = _request_target_ts() is None and period == "5m" and selected_bucket == latest_bucket
        if not live_request or not table_columns(conn, "vm_disk_current"):
            return []
        return conn.execute("""
            SELECT target,source,mount,storage_device,storage_block,storage_fstype,
                   capacity_bytes,allocation_bytes,physical_bytes,
                   read_bps,write_bps,read_iops,write_iops,last_seen
            FROM vm_disk_current
            WHERE node=? AND vm_uuid=? AND role='customer'
            ORDER BY CASE target WHEN 'vda' THEN 0 WHEN 'vdb' THEN 1 ELSE 2 END,
                     target COLLATE NOCASE, source COLLATE NOCASE
        """, (node, vm_uuid)).fetchall()
    finally:
        conn.close()

def _v48133_disk_level(pct):
    if pct >= 90:
        return "critical"
    if pct >= 75:
        return "hot"
    if pct >= 50:
        return "warm"
    return "ok"

def _v48133_vm_disk_overview_cards(rows):
    """One compact Overview card per customer disk, matching CPU/RAM language."""
    cards = []
    for target,source,mount,device,block,fstype,assigned,allocated,physical,rb,wb,ri,wi,seen in rows:
        assigned = max(0, safe_int(assigned, 0))
        allocated = max(0, safe_int(allocated, 0))
        pct = allocated * 100.0 / assigned if assigned > 0 else 0.0
        level = _v48133_disk_level(pct)
        dev = device or (("/dev/" + block) if block else "-")
        cards.append(
            f'<div class="stat vm-overview-disk-stat disk-level-{level}">'
            f'<div class="vm-disk-stat-label">DISK {escape(target or "-")}</div>'
            f'<b>{_disk_io_bytes(allocated)} / {_disk_io_bytes(assigned)}</b>'
            f'<small>{pct:.1f}% allocated</small>'
            f'<span class="vm-disk-overview-meter"><i style="width:{min(100.0,max(0.0,pct)):.1f}%"></i></span>'
            f'<small class="vm-disk-storage-line">{escape(mount or "-")} · {escape(dev)}</small>'
            f'<small class="vm-disk-live-line">R {_disk_io_rate(rb)} · W {_disk_io_rate(wb)} · IOPS {_disk_io_iops(ri)} / {_disk_io_iops(wi)}</small>'
            f'</div>'
        )
    return "".join(cards)

V48133_VM_CSS = r'''
<style id="v48134-vm-disk-detail">
.vm-overview-disk-stat{min-width:225px}.vm-disk-stat-label{font-size:10px;font-weight:950;color:#667085;letter-spacing:.055em}.vm-overview-disk-stat>b{display:block;margin-top:5px!important;font-size:15px!important;white-space:nowrap}.vm-overview-disk-stat>small{display:block;margin-top:4px!important}.vm-disk-overview-meter{display:block;height:6px;margin-top:8px;border-radius:999px;background:#e4e7ec;overflow:hidden}.vm-disk-overview-meter i{display:block;height:100%;border-radius:inherit;background:#12b76a}.disk-level-warm .vm-disk-overview-meter i{background:#fdb022}.disk-level-hot .vm-disk-overview-meter i{background:#f79009}.disk-level-critical .vm-disk-overview-meter i{background:#f04438}.vm-disk-storage-line{color:#667085!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.vm-disk-live-line{color:#475467!important;font-size:9px!important;line-height:1.35!important}
.vm-disk-detail-card{margin-top:16px}.vm-disk-detail-card .table-title-row{margin-bottom:13px}.vm-disk-panel-capacity span,.vm-disk-panel-metrics span,.vm-disk-panel-meta span{display:block;color:#667085;font-size:9px;font-weight:900;letter-spacing:.055em}.vm-disk-detail-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(410px,1fr));gap:12px}.vm-disk-panel{border:1px solid #dbe3ef;border-radius:13px;padding:14px;background:#fff;min-width:0}.vm-disk-panel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.vm-disk-panel-head span{font-size:9px;color:#667085;font-weight:900;letter-spacing:.07em}.vm-disk-panel-head h4{font-size:18px;margin:3px 0 0}.vm-disk-storage-badge{text-align:right;min-width:0}.vm-disk-storage-badge b,.vm-disk-storage-badge small{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.vm-disk-storage-badge b{font-size:12px}.vm-disk-storage-badge small{margin-top:3px;color:#667085;font-size:9px}.vm-disk-panel-capacity{margin-top:13px}.vm-disk-panel-capacity b{display:block;margin-top:4px;font-size:15px}.vm-disk-panel-capacity small{display:block;margin-top:3px;color:#667085;font-size:10px}.vm-disk-panel-metrics{display:grid;grid-template-columns:repeat(4,minmax(80px,1fr));gap:8px;margin-top:13px}.vm-disk-panel-metrics>div{padding:10px;border-radius:9px;background:#f8fafc;border:1px solid #edf0f4}.vm-disk-panel-metrics b{display:block;margin-top:4px;font-size:12px;white-space:nowrap}.vm-disk-panel-meta{display:grid;grid-template-columns:minmax(180px,2fr) repeat(3,minmax(90px,1fr));gap:9px;margin-top:12px;padding-top:12px;border-top:1px solid #edf0f4}.vm-disk-panel-meta b,.vm-disk-panel-meta code{display:block;margin-top:4px;font-size:10px}.vm-disk-panel-meta code{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#475467}.vm-disk-panel.disk-level-hot,.vm-disk-panel.disk-level-critical{border-color:#fed7aa}.vm-disk-panel.disk-level-critical{border-color:#fda29b}
html[data-theme=dark] .vm-disk-stat-label,html[data-theme=dark] .vm-disk-storage-line,html[data-theme=dark] .vm-disk-storage-badge small,html[data-theme=dark] .vm-disk-panel-capacity small,html[data-theme=dark] .vm-disk-panel-metrics span,html[data-theme=dark] .vm-disk-panel-meta span{color:#9fb0c4!important}html[data-theme=dark] .vm-disk-overview-meter{background:#334155}html[data-theme=dark] .vm-disk-panel-metrics>div{background:#132238;border-color:#31445e}html[data-theme=dark] .vm-disk-panel{background:#0f1b2c;border-color:#31445e}html[data-theme=dark] .vm-disk-panel-meta{border-top-color:#31445e}html[data-theme=dark] .vm-disk-panel-meta code{color:#d0d9e7}
@media(max-width:900px){.vm-disk-detail-grid{grid-template-columns:1fr}.vm-disk-panel-metrics{grid-template-columns:1fr 1fr}.vm-disk-panel-meta{grid-template-columns:1fr 1fr}}
</style>
'''

_vm_page_v48133_base = app.view_functions.get("vm_page")

def vm_page_v48133():
    response = _vm_page_v48133_base()
    try:
        if not hasattr(response, "get_data"):
            return response
        node = (request.args.get("node") or "").strip()
        vm_uuid = (request.args.get("vm_uuid") or "").strip()
        if not node or not vm_uuid:
            return response
        rows = _v48133_vm_disks(node, vm_uuid)
        if not rows:
            return response
        html = response.get_data(as_text=True)
        if 'id="virtual-disk-io"' in html:
            return response
        cards = _v48133_vm_disk_overview_cards(rows)
        details = _v48133_vm_disk_io_card(rows)
        pattern = re.compile(
            r'(<div class="card"><h3>Overview</h3><div class="grid">)(.*?)(</div></div>\s*)(<div class="vm-charts-grid">)',
            re.S,
        )
        html, count = pattern.subn(lambda m: m.group(1) + m.group(2) + cards + m.group(3) + details + m.group(4), html, count=1)
        if not count:
            html = html.replace('<div class="vm-charts-grid">', details + '<div class="vm-charts-grid">', 1)
        html = html.replace('</head>', V48133_VM_CSS + '</head>', 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.13.4 VM disk details")
    return response

if _vm_page_v48133_base is not None:
    app.view_functions["vm_page"] = vm_page_v48133

_get_node_filesystems_snapshot_v48133_base = get_node_filesystems_snapshot

def get_node_filesystems_snapshot(node, period):
    """Return capacity and I/O from the same selected retained Agent push."""
    period = clean_period(period)
    conn = db()
    try:
        payload, selected_bucket, latest_bucket = _v5054_selected_storage_payload(conn, node, period)
        if payload:
            seen = safe_int(payload.get("t"), selected_bucket)
            rows = []
            for item in payload.get("s") or []:
                if not isinstance(item, (list, tuple)) or len(item) < 14:
                    continue
                (
                    mount, device, block, raid_level, fstype,
                    size, used, avail, use_percent,
                    read_bps, write_bps, read_iops, write_iops, util_percent,
                ) = item[:14]
                mount = str(mount or "").strip()
                if not mount:
                    continue
                rows.append((
                    mount,
                    str(device or (("/dev/" + str(block)) if block else "")),
                    str(fstype or ""),
                    max(0, safe_int(size, 0)),
                    max(0, safe_int(used, 0)),
                    max(0, safe_int(avail, 0)),
                    max(0.0, safe_float(use_percent, 0.0)),
                    seen,
                    max(0.0, safe_float(read_bps, 0.0)),
                    max(0.0, safe_float(write_bps, 0.0)),
                    max(0.0, safe_float(read_iops, 0.0)),
                    max(0.0, safe_float(write_iops, 0.0)),
                    max(0.0, safe_float(util_percent, 0.0)),
                    seen,
                ))
            if rows:
                return sorted(rows, key=lambda r: (-safe_float(r[6], 0), str(r[0]).lower()))

        # Compatibility fallback for snapshots created before retained Storage
        # payloads existed. Capacity remains historical; I/O is deliberately N/A
        # instead of borrowing current rates from another time.
        fs_bucket = selected_bucket if table_columns(conn, "node_filesystem_stats") else 0
        if fs_bucket:
            rows = conn.execute("""
                SELECT mount,device,fstype,size,used,avail,use_percent,last_push,
                       0,0,0,0,0,0
                FROM node_filesystem_stats
                WHERE node=? AND bucket=?
                ORDER BY use_percent DESC,mount COLLATE NOCASE
            """, (node, fs_bucket)).fetchall()
            if rows:
                return rows

        # Only the live/latest page may use current tables as a final fallback.
        live_request = _request_target_ts() is None and period == "5m" and selected_bucket == latest_bucket
        if live_request and table_columns(conn, "node_storage_current"):
            return conn.execute("""
                SELECT mount,device,fstype,size,used,avail,use_percent,last_seen,
                       read_bps,write_bps,read_iops,write_iops,util_percent,last_seen
                FROM node_storage_current
                WHERE node=?
                ORDER BY use_percent DESC,mount COLLATE NOCASE
            """, (node,)).fetchall()
        return []
    finally:
        conn.close()

def _v48133_public_ip_sql(alias="d"):
    return f"COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest b WHERE b.node={alias}.node AND LOWER(b.role)='public' ORDER BY b.last_seen DESC LIMIT 1),'')"

def _v48133_storage_filter_options(conn, values):
    nodes = [r[0] for r in conn.execute("""
        SELECT node FROM (
          SELECT DISTINCT node FROM vm_disk_current WHERE role='customer'
          UNION SELECT DISTINCT node FROM node_storage_current
        ) ORDER BY node COLLATE NOCASE
    """).fetchall()]
    mount_params = []
    mount_where = ""
    if values.get("node"):
        mount_where = " WHERE node=?"
        mount_params.append(values["node"])
    mounts = [r[0] for r in conn.execute(f"""
        SELECT mount FROM (
          SELECT DISTINCT node,mount FROM vm_disk_current WHERE role='customer' AND mount!=''
          UNION SELECT DISTINCT node,mount FROM node_storage_current WHERE mount!=''
        ){mount_where} ORDER BY mount COLLATE NOCASE
    """, mount_params).fetchall()]
    node_options = ['<option value="">All nodes</option>']
    for item in nodes:
        selected = " selected" if item == values.get("node") else ""
        node_options.append(f'<option value="{escape(item,quote=True)}"{selected}>{escape(item)}</option>')
    mount_options = ['<option value="">All storage</option>']
    for item in mounts:
        selected = " selected" if item == values.get("mount") else ""
        mount_options.append(f'<option value="{escape(item,quote=True)}"{selected}>{escape(item)}</option>')
    return "".join(node_options), "".join(mount_options)

V48133_STORAGE_CSS = r'''
<style id="v48134-storage-integrated">
.storage-search-bar{display:grid;grid-template-columns:minmax(340px,1.9fr) minmax(150px,.7fr) minmax(150px,.7fr) 78px auto auto;gap:9px;align-items:end}.storage-search-bar label{display:grid;gap:5px;font-size:10px;font-weight:900;color:#667085}.storage-search-bar input,.storage-search-bar select{min-height:41px}.storage-search-bar .storage-search-input{font-size:13px;padding-left:38px}.storage-search-wrap{position:relative}.storage-search-wrap:before{content:'⌕';position:absolute;left:13px;bottom:9px;font-size:20px;color:#667085;z-index:2}.storage-search-wrap input{width:100%}.storage-search-bar button,.storage-search-bar .clear{min-height:41px;display:flex;align-items:center;justify-content:center}
.storage-disk-detail-table{min-width:1740px;table-layout:fixed}.storage-disk-detail-table th:nth-child(1){width:180px}.storage-disk-detail-table th:nth-child(2){width:300px}.storage-disk-detail-table th:nth-child(3){width:420px}.storage-disk-detail-table th:nth-child(4){width:255px}.storage-disk-detail-table th:nth-child(n+5){width:116px}.storage-disk-detail-table td{vertical-align:middle}.storage-disk-detail-table td.num{text-align:right;white-space:nowrap}.storage-disk-detail-table tr.storage-vm-start td{border-top:2px solid #dbe3ef!important}.storage-disk-detail-table tr.storage-vm-start:first-child td{border-top:0!important}.storage-disk-detail-table tr.storage-vm-cont td{background:#fbfcfe}
.storage-node-cell>a,.storage-node-cell>b,.storage-node-ip{display:block}.storage-node-ip{margin-top:5px;font-size:10px;color:#667085}.storage-node-ip .copy-btn{margin-left:5px;transform:scale(.86)}.storage-uuid-cell small{display:block;margin-top:7px;color:#667085}.storage-one-disk{min-width:0}.storage-disk-title{display:flex;align-items:baseline;gap:8px;min-width:0}.storage-disk-title b{font-size:13px}.storage-disk-title span{font-size:10px;color:#667085;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.storage-one-disk code{display:block;margin-top:6px;font-size:9px;color:#667085;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.storage-one-disk small{display:block;margin-top:5px;color:#98a2b3;font-size:9px}.storage-node-table{min-width:1640px;table-layout:fixed}.storage-node-table th:nth-child(1){width:200px}.storage-node-table th:nth-child(2){width:315px}.storage-node-table th:nth-child(3){width:260px}.storage-node-table th:nth-child(n+4){width:120px}.storage-node-table td.num{text-align:right;white-space:nowrap}.storage-count-sub{display:block;margin-top:4px;color:#667085}
html[data-theme=dark] .storage-node-ip,html[data-theme=dark] .storage-uuid-cell small,html[data-theme=dark] .storage-disk-title span,html[data-theme=dark] .storage-one-disk code,html[data-theme=dark] .storage-one-disk small,html[data-theme=dark] .storage-count-sub{color:#9fb0c4}html[data-theme=dark] .storage-disk-detail-table tr.storage-vm-start td{border-top-color:#31445e!important}html[data-theme=dark] .storage-disk-detail-table tr.storage-vm-cont td{background:#101d30}
@media(max-width:1100px){.storage-search-bar{grid-template-columns:1fr 1fr}}
</style>
'''

def storage_io_page_v48133():
    values=_storage_io_params()
    if values["view"] == "backends":
        values["view"]="nodes"
    if values["view"] not in {"disks","nodes"}:
        values["view"]="disks"
    start_ts,end_ts=range_for_period(values["period"])
    conn=db()
    try:
        ensure_disk_io_schema(conn)
        node_options,mount_options=_v48133_storage_filter_options(conn,values)
        table=_v48133_storage_node_table(conn,values,start_ts) if values["view"]=="nodes" else _v48133_storage_disk_table(conn,values,start_ts)
    finally:
        conn.close()
    clear_href=url_for("storage_io_page",view=values["view"],period=values["period"])
    disk_tab=_storage_io_url(values,view="disks",sort="writeiops",order="desc",page=1)
    node_tab=_storage_io_url(values,view="nodes",sort="writeiops",order="desc",page=1)
    content=(
        STORAGE_IO_CSS+V48133_STORAGE_CSS
        +'<div class="card storage-hero"><div><span class="eyebrow">DISK MONITOR</span><h2>Storage I/O</h2><p>See node mount load, then drill into the exact VM and every disk attached to its UUID.</p></div>'
        +f'<div class="storage-tabs"><a class="{"active" if values["view"]=="disks" else ""}" href="{escape(disk_tab,quote=True)}">VM Disks</a><a class="{"active" if values["view"]=="nodes" else ""}" href="{escape(node_tab,quote=True)}">Storage Node</a></div></div>'
        +'<div class="card storage-toolbar">'
        +f'<div><div class="label">Latest sample lookback</div><div class="storage-periods">{_storage_period_links(values)}</div></div>'
        +f'<form class="storage-search-bar" method="get" action="{url_for("storage_io_page")}">'
        +f'<input type="hidden" name="view" value="{escape(values["view"],quote=True)}"><input type="hidden" name="period" value="{escape(values["period"],quote=True)}"><input type="hidden" name="sort" value="{escape(values["sort"],quote=True)}"><input type="hidden" name="order" value="{escape(values["order"],quote=True)}">'
        +f'<label class="storage-search-wrap">SEARCH<input class="storage-search-input" name="q" value="{escape(values["q"],quote=True)}" placeholder="Search node, IP, UUID, disk, path or mount"></label>'
        +f'<label>NODE<select name="node">{node_options}</select></label><label>STORAGE<select name="mount">{mount_options}</select></label>'
        +f'<label>ROWS<input name="limit" value="{values["limit"]}" inputmode="numeric"></label><button type="submit">Search</button><a class="clear" href="{escape(clear_href,quote=True)}">Clear</a></form>'
        +f'<div class="storage-note">Selected window: <b>{escape(values["period"])}</b> · latest samples from <b>{fmt_full(start_ts)}</b> to <b>{fmt_full(end_ts)}</b>. Capacity is current; Read/Write and IOPS are current sample rates.</div>'
        +'</div>'+table
    )
    return page("Storage I/O",content)

app.view_functions["storage_io_page"] = storage_io_page_v48133

def purge_vm_data(conn, node, vm_uuid, refresh_snapshots=True):
    """Purge exactly one UUID from every VM-scoped dataset.

    No broad DELETE is used: other VMs' Current Abuse and Abuse Events remain
    visible.  The UUID is removed across all node copies so Dashboard, Top VM,
    Storage I/O and historical 5m searches cannot leave ghost rows.
    """
    vm_uuid=str(vm_uuid or "").strip()
    node=str(node or "").strip()
    if not vm_uuid:
        raise ValueError("Missing VM UUID")
    ensure_disk_io_schema(conn)
    affected_nodes={str(r[0]) for r in conn.execute("""
      SELECT DISTINCT node FROM (
        SELECT node FROM vm_inventory WHERE vm_uuid=:u
        UNION SELECT node FROM vm_node_presence WHERE vm_uuid=:u
        UNION SELECT node FROM vm_current_fast WHERE vm_uuid=:u
        UNION SELECT node FROM vm_iface_current WHERE vm_uuid=:u
        UNION SELECT node FROM vm_latest_metrics WHERE vm_uuid=:u
        UNION SELECT node FROM vm_perf_stats WHERE vm_uuid=:u
        UNION SELECT node FROM node_stats WHERE vm_uuid=:u
        UNION SELECT node FROM usage WHERE vm_uuid=:u
        UNION SELECT node FROM vm_abuse_state WHERE vm_uuid=:u
        UNION SELECT node FROM vm_abuse_events WHERE vm_uuid=:u
        UNION SELECT node FROM vm_abuse_incidents WHERE vm_uuid=:u
        UNION SELECT node FROM vm_disk_current WHERE vm_uuid=:u
      ) WHERE node IS NOT NULL AND TRIM(node)!=''
    """,{"u":vm_uuid}).fetchall()}
    if node:
        affected_nodes.add(node)
    deleted={}
    uuid_tables=(
        "vm_iface_current","vm_current_fast","vm_abuse_state","vm_abuse_events","vm_abuse_incidents",
        "usage","node_stats","vm_perf_stats","vm_latest_metrics","vm_consumption_hourly","vm_consumption_daily",
        "vm_node_presence","vm_inventory","vm_disk_current",
    )
    for table in uuid_tables:
        deleted[table]=_delete_count(conn,f"DELETE FROM {table} WHERE vm_uuid=?",(vm_uuid,))
    deleted["vm_migration_events"]=_delete_count(conn,"DELETE FROM vm_migration_events WHERE vm_uuid=?",(vm_uuid,))
    deleted["vm_location_latest"]=_delete_count(conn,"DELETE FROM vm_location_latest WHERE vm_uuid=?",(vm_uuid,))
    for affected in sorted(affected_nodes):
        if refresh_snapshots:
            _refresh_node_snapshot_vm_counts(conn,affected)
        conn.execute("""
          UPDATE node_current_fast
          SET vm_count=(SELECT COUNT(*) FROM vm_current_fast v WHERE v.node=node_current_fast.node),
              iface_count=(SELECT COUNT(*) FROM vm_iface_current i WHERE i.node=node_current_fast.node)
          WHERE node=?
        """,(affected,))
    deleted["affected_nodes"]=len(affected_nodes)
    return deleted
