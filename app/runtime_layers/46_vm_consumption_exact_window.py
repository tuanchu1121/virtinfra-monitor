# Release: 50.5.9-prod-r22.8-vm-consumption-exact-window-sort-alignment
#
# R22.8 keeps the complete R22.7 runtime as its base and replaces only the
# final VM Consumption read path.  Agent payloads, /push ingest, rollup writes,
# Node/Group/Summary Consumption, retention, formulas and public APIs remain
# unchanged.
#
# VM ranges follow the proven 50.5.9 hybrid plan:
#   * complete local days  -> vm_consumption_daily
#   * complete local hours -> vm_consumption_hourly
#   * only the two partial-hour edges -> node_stats
# Raw rows are bounded by both the Timescale bucket and last_push predicates.

V5061_RELEASE = "50.5.9-prod-r22.8-vm-consumption-exact-window-sort-alignment"

def _r228_group_id():
    try:
        return safe_int(_r20_node_groups.selected_group_id(), 0)
    except Exception:
        return 0

def _r228_scope_sql(alias, selected_node=""):
    """Return a combined early Node + active Group scope predicate."""
    selected_node = str(selected_node or "").strip()
    group_id = _r228_group_id()
    sql = ""
    params = []
    if selected_node:
        sql += " AND %s.node=?" % alias
        params.append(selected_node)
    # Active Group membership is also the canonical visibility boundary.  Do
    # not let an explicit Node selector bypass the selected Group or revive a
    # Node that belongs only to a hidden Group.
    sql += (
        " AND EXISTS ("
        "SELECT 1 FROM node_group_memberships r228_gm "
        "JOIN node_groups r228_g ON r228_g.id=r228_gm.group_id "
        "WHERE r228_gm.node=%s.node AND r228_g.is_active=1" % alias
    )
    if group_id:
        sql += " AND r228_g.id=?"
        params.append(group_id)
    return sql + ")", params

def _r228_ceil_hour(value):
    value = safe_int(value, 0)
    base = local_hour_start(value)
    return base if value == base else base + 3600

def _r228_vm_raw_branch(start, end, selected_node=""):
    """Read only a partial-hour edge from raw five-minute VM rows.

    last_push preserves the existing exact range semantics.  bucket supplies
    the hypertable/chunk pruning predicate so an edge cannot reopen the whole
    retained node_stats history.
    """
    start = safe_int(start, 0)
    end = safe_int(end, 0)
    if end <= start:
        return "", []
    bucket_start = bucket_for(start)
    bucket_end = bucket_for(max(start, end - 1)) + CACHE_BUCKET_SECONDS
    scope_sql, scope_params = _r228_scope_sql("ns", selected_node)
    sql = """
      SELECT ns.node,ns.vm_uuid,ns.bridge,
             COALESCE(SUM(ns.rx_delta),0)::bigint AS rx_bytes,
             COALESCE(SUM(ns.tx_delta),0)::bigint AS tx_bytes,
             COUNT(DISTINCT ns.last_push)::bigint AS sample_count,
             COALESCE(MAX(ns.last_push),0)::bigint AS last_push
        FROM node_stats ns
       WHERE ns.bucket>=? AND ns.bucket<?
         AND ns.last_push>=? AND ns.last_push<?%s
       GROUP BY ns.node,ns.vm_uuid,ns.bridge
    """ % scope_sql
    return sql, [bucket_start, bucket_end, start, end] + scope_params

def _r228_vm_hourly_branch(start, end, selected_node=""):
    start = safe_int(start, 0)
    end = safe_int(end, 0)
    if end <= start:
        return "", []
    scope_sql, scope_params = _r228_scope_sql("h", selected_node)
    sql = """
      SELECT h.node,h.vm_uuid,h.bridge,h.rx_bytes,h.tx_bytes,h.sample_count,h.last_push
        FROM vm_consumption_hourly h
       WHERE h.hour_start>=? AND h.hour_start<?%s
    """ % scope_sql
    return sql, [start, end] + scope_params

def _r228_vm_daily_branch(start, end, selected_node=""):
    start = safe_int(start, 0)
    end = safe_int(end, 0)
    if end <= start:
        return "", []
    scope_sql, scope_params = _r228_scope_sql("d", selected_node)
    sql = """
      SELECT d.node,d.vm_uuid,d.bridge,d.rx_bytes,d.tx_bytes,d.sample_count,d.last_push
        FROM vm_consumption_daily d
       WHERE d.day_start>=? AND d.day_start<?%s
    """ % scope_sql
    return sql, [start, end] + scope_params

def _v5058c_vm_source_sql(start, end, selected_node=""):
    """Build one exact rolling VM range without scanning raw full history."""
    start = safe_int(start, 0)
    end = safe_int(end, 0)
    if end <= start:
        return (
            "SELECT node,vm_uuid,bridge,rx_bytes,tx_bytes,sample_count,last_push "
            "FROM vm_consumption_hourly WHERE 1=0",
            [],
        )

    first_day = local_day_start(start)
    full_day_start = first_day if start == first_day else first_day + 86400
    full_day_end = local_day_start(end)
    branches = []
    params = []

    if full_day_start < full_day_end:
        sql, values = _r228_vm_daily_branch(
            full_day_start, full_day_end, selected_node,
        )
        if sql:
            branches.append(sql)
            params.extend(values)
        edge_ranges = ((start, full_day_start), (full_day_end, end))
    else:
        edge_ranges = ((start, end),)

    for edge_start, edge_end in edge_ranges:
        if edge_end <= edge_start:
            continue
        full_hour_start = _r228_ceil_hour(edge_start)
        full_hour_end = local_hour_start(edge_end)

        if full_hour_start >= full_hour_end:
            sql, values = _r228_vm_raw_branch(
                edge_start, edge_end, selected_node,
            )
            if sql:
                branches.append(sql)
                params.extend(values)
            continue

        if edge_start < full_hour_start:
            sql, values = _r228_vm_raw_branch(
                edge_start, full_hour_start, selected_node,
            )
            if sql:
                branches.append(sql)
                params.extend(values)

        sql, values = _r228_vm_hourly_branch(
            full_hour_start, full_hour_end, selected_node,
        )
        if sql:
            branches.append(sql)
            params.extend(values)

        if full_hour_end < edge_end:
            sql, values = _r228_vm_raw_branch(
                full_hour_end, edge_end, selected_node,
            )
            if sql:
                branches.append(sql)
                params.extend(values)

    if not branches:
        return (
            "SELECT node,vm_uuid,bridge,rx_bytes,tx_bytes,sample_count,last_push "
            "FROM vm_consumption_hourly WHERE 1=0",
            [],
        )
    return " UNION ALL ".join(branches), params

def _v5058c_visible_vm_cte(selected_node=""):
    """Return current visible VM inventory with Node/Group scope applied early."""
    scope_sql, scope_params = _r228_scope_sql("l", selected_node)
    sql = """
      node_meta AS (
        SELECT ni.node,
               COALESCE(MAX(CASE WHEN LOWER(COALESCE(ba.role,''))='public'
                                 THEN ba.primary_ipv4 END),'') AS node_ip
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
    """ % scope_sql
    return sql, [PUBLIC_BRIDGE, PRIVATE_BRIDGE] + scope_params

def _v5058c_visible_nodes():
    """List only active Nodes inside the currently selected Group."""
    group_id = _r228_group_id()
    group_sql = " AND r228_g.id=?" if group_id else ""
    params = [group_id] if group_id else []
    conn = db()
    try:
        return conn.execute("""
          SELECT ni.node,
                 COALESCE(MAX(CASE WHEN LOWER(COALESCE(ba.role,''))='public'
                                   THEN ba.primary_ipv4 END),'') AS public_ipv4
            FROM node_inventory ni
            JOIN node_group_memberships r228_gm ON r228_gm.node=ni.node
            JOIN node_groups r228_g ON r228_g.id=r228_gm.group_id
                                   AND r228_g.is_active=1
            LEFT JOIN node_bridge_addresses_latest ba ON ba.node=ni.node
           WHERE COALESCE(ni.status,'active')!='hidden'
             AND ni.deleted_at IS NULL%s
           GROUP BY ni.node
           ORDER BY LOWER(ni.node)
        """ % group_sql, params).fetchall()
    finally:
        conn.close()

def _v5058c_vm_ctes(start, end, selected_node=""):
    """Build exact VM rows and merge historical Node segments by UUID.

    All-VM and Group views sum every in-scope historical segment of a UUID and
    display its current Node.  An explicit Node filter remains Node-attributed:
    both history and current inventory are restricted to that Node.
    """
    start = safe_int(start, 0)
    end = safe_int(end, 0)
    source_sql, source_params = _v5058c_vm_source_sql(
        start, end, selected_node,
    )
    visible_sql, visible_params = _v5058c_visible_vm_cte(selected_node)
    expected_samples = max(
        1,
        int(math.ceil(max(1, end - start) / float(CACHE_BUCKET_SECONDS))),
    )
    sql = """
      WITH source AS (%s),
      source_per_bridge AS (
        SELECT node,vm_uuid,bridge,
               COALESCE(SUM(rx_bytes),0)::bigint AS host_rx,
               COALESCE(SUM(tx_bytes),0)::bigint AS host_tx,
               COALESCE(SUM(sample_count),0)::bigint AS samples,
               COALESCE(MAX(last_push),0)::bigint AS latest_sample
          FROM source
         GROUP BY node,vm_uuid,bridge
      ),
      rolled_bridge AS (
        SELECT vm_uuid,bridge,
               COALESCE(SUM(host_rx),0)::bigint AS host_rx,
               COALESCE(SUM(host_tx),0)::bigint AS host_tx,
               LEAST(?,COALESCE(SUM(samples),0))::bigint AS samples,
               COALESCE(MAX(latest_sample),0)::bigint AS latest_sample
          FROM source_per_bridge
         GROUP BY vm_uuid,bridge
      ),
      vm_agg AS (
        SELECT vm_uuid,
               COALESCE(SUM(CASE WHEN bridge=? THEN host_tx ELSE 0 END),0)::bigint AS public_rx,
               COALESCE(SUM(CASE WHEN bridge=? THEN host_rx ELSE 0 END),0)::bigint AS public_tx,
               COALESCE(SUM(CASE WHEN bridge=? THEN host_tx ELSE 0 END),0)::bigint AS private_rx,
               COALESCE(SUM(CASE WHEN bridge=? THEN host_rx ELSE 0 END),0)::bigint AS private_tx,
               COALESCE(MAX(CASE WHEN bridge=? THEN samples ELSE 0 END),0)::bigint AS public_samples,
               COALESCE(MAX(CASE WHEN bridge=? THEN samples ELSE 0 END),0)::bigint AS private_samples,
               COALESCE(MAX(latest_sample),0)::bigint AS latest_sample
          FROM rolled_bridge
         GROUP BY vm_uuid
      ),
      %s,
      vm_joined AS (
        SELECT v.vm_uuid,v.vm_name,v.node,v.node_ip,
               CASE WHEN v.public_configured=1 OR COALESCE(a.public_samples,0)>0
                         OR COALESCE(a.public_rx,0)>0 OR COALESCE(a.public_tx,0)>0
                    THEN 1 ELSE 0 END::integer AS public_configured,
               CASE WHEN v.private_configured=1 OR COALESCE(a.private_samples,0)>0
                         OR COALESCE(a.private_rx,0)>0 OR COALESCE(a.private_tx,0)>0
                    THEN 1 ELSE 0 END::integer AS private_configured,
               COALESCE(a.public_rx,0)::bigint AS public_rx,
               COALESCE(a.public_tx,0)::bigint AS public_tx,
               COALESCE(a.private_rx,0)::bigint AS private_rx,
               COALESCE(a.private_tx,0)::bigint AS private_tx,
               COALESCE(a.public_samples,0)::bigint AS public_samples,
               COALESCE(a.private_samples,0)::bigint AS private_samples,
               COALESCE(a.latest_sample,0)::bigint AS latest_sample
          FROM visible_vm v
          LEFT JOIN vm_agg a ON a.vm_uuid=v.vm_uuid
      ),
      vm_rows AS (
        SELECT vm_uuid,vm_name,node,node_ip,
               public_configured,private_configured,
               public_rx,public_tx,(public_rx+public_tx)::bigint AS public_total,
               private_rx,private_tx,(private_rx+private_tx)::bigint AS private_total,
               LEAST(100.0,
                 CASE
                   WHEN public_configured=1 AND private_configured=1
                     THEN LEAST(public_samples,private_samples)*100.0/?
                   WHEN public_configured=1 THEN public_samples*100.0/?
                   WHEN private_configured=1 THEN private_samples*100.0/?
                   ELSE 0.0
                 END
               ) AS coverage_percent,
               latest_sample
          FROM vm_joined
      )
    """ % (source_sql, visible_sql)
    params = list(source_params)
    params.append(expected_samples)
    params.extend([
        PUBLIC_BRIDGE, PUBLIC_BRIDGE,
        PRIVATE_BRIDGE, PRIVATE_BRIDGE,
        PUBLIC_BRIDGE, PRIVATE_BRIDGE,
    ])
    params.extend(visible_params)
    params.extend([expected_samples, expected_samples, expected_samples])
    return sql, params

def _r228_vm_rows_uncached(
    start, end, selected_node, q, coverage,
    sort_by, order, page_no, limit,
):
    ctes, params = _v5058c_vm_ctes(start, end, selected_node)
    search_sql, search_params = _v5058c_search_clause("vm", q)
    where_sql = " WHERE 1=1" + search_sql + _v5058c_coverage_clause(coverage)
    order_column = V5058C_VM_SORTS[sort_by]
    direction = "ASC" if order == "asc" else "DESC"
    page_no = max(1, safe_int(page_no, 1))
    limit = max(1, safe_int(limit, 100))

    # Every visible VM is aggregated and filtered before ORDER BY. LIMIT/OFFSET
    # are deliberately last so every clickable metric sorts the full scope,
    # not merely the current page or a pre-limited candidate set.
    def fetch(offset):
        conn = db()
        try:
            return conn.execute(
                ctes + """
                  SELECT vm_uuid,node,node_ip,public_configured,private_configured,
                         public_rx,public_tx,public_total,
                         private_rx,private_tx,private_total,
                         coverage_percent,latest_sample,
                         COUNT(*) OVER() AS total_count
                    FROM vm_rows
                """ + where_sql + (
                    " ORDER BY %s %s,node ASC,vm_uuid ASC LIMIT ? OFFSET ?"
                    % (order_column, direction)
                ),
                params + search_params + [limit, offset],
            ).fetchall()
        finally:
            conn.close()

    raw_rows = fetch((page_no - 1) * limit)
    if not raw_rows and page_no > 1:
        page_no = 1
        raw_rows = fetch(0)
    total = safe_int(raw_rows[0][-1] if raw_rows else 0, 0)
    max_page = max(1, int(math.ceil(total / float(limit))))
    return [tuple(row[:-1]) for row in raw_rows], total, page_no, max_page

def _v5058c_vm_rows(
    start, end, selected_node, q, coverage,
    sort_by, order, page_no, limit,
):
    start, end = _r21_normalized_range(start, end)
    group_id = _r228_group_id()
    try:
        visibility_generation = safe_int(_v48140_cache_generation(), 0)
    except Exception:
        visibility_generation = 0
    key = (
        "r228-vm-exact", start, end, group_id, selected_node, q, coverage,
        sort_by, order, page_no, limit, visibility_generation,
    )
    return _r21_cached(
        key,
        lambda: _r228_vm_rows_uncached(
            start, end, selected_node, q, coverage,
            sort_by, order, page_no, limit,
        ),
    )

# Preserve the 50.5.9 fixed-column renderer and add a final VM-only alignment
# contract after the R22 layers.  No values, links or sort keys are rewritten.
_r228_vm_table_base = _v5058c_vm_table
R228_VM_ALIGNMENT_CSS = r'''<style id="r228-vm-consumption-alignment">
body.endpoint-bandwidth-consumption-page .v5058c-vm-table{min-width:1380px!important;table-layout:fixed!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table th,
body.endpoint-bandwidth-consumption-page .v5058c-vm-table td{vertical-align:middle!important;box-sizing:border-box}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table tbody td:nth-child(n+3):nth-child(-n+8){text-align:right!important;font-variant-numeric:tabular-nums lining-nums;white-space:nowrap}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table thead tr:nth-child(2) th,
body.endpoint-bandwidth-consumption-page .v5058c-vm-table thead tr:nth-child(2) .sort-link{justify-content:flex-end!important;text-align:right!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table .sort-link{gap:5px;white-space:nowrap!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table .v5058c-uuid,
body.endpoint-bandwidth-consumption-page .v5058c-vm-table .v5058c-node{text-align:left!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table tbody td:nth-child(9){text-align:center!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table tbody td:nth-child(10){text-align:right!important;padding-right:12px!important}
</style>'''

def _v5058c_vm_table(rows, common, sort_by, order):
    return R228_VM_ALIGNMENT_CSS + _r228_vm_table_base(
        rows, common, sort_by, order,
    )
