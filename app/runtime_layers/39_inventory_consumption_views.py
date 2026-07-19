# 50.5.8 low-I/O identity cleanup. Lookup rows are not historical data and
# follow the same VM/node purge lifecycle as the bounded current tables.
# ---------------------------------------------------------------------------
_v5058_purge_vm_data_base = purge_vm_data

def purge_vm_data(conn, node, vm_uuid, refresh_snapshots=True):
    result = _v5058_purge_vm_data_base(
        conn, node, vm_uuid, refresh_snapshots=refresh_snapshots
    )
    deleted = _delete_count(
        conn,
        "DELETE FROM vm_nic_identity_lookup WHERE node=? AND vm_uuid=?",
        (node, vm_uuid),
    )
    if isinstance(result, dict):
        result["vm_nic_identity_lookup"] = deleted
    return result

_v5058_purge_node_data_base = purge_node_data

def purge_node_data(conn, node):
    result = dict(_v5058_purge_node_data_base(conn, node) or {})
    result["vm_nic_identity_lookup"] = _delete_count(
        conn, "DELETE FROM vm_nic_identity_lookup WHERE node=?", (node,)
    )
    result["node_nic_identity_lookup"] = _delete_count(
        conn, "DELETE FROM node_nic_identity_lookup WHERE node=?", (node,)
    )
    return result

MONITORING_DATA_TABLES = tuple(dict.fromkeys(tuple(MONITORING_DATA_TABLES) + (
    "vm_nic_identity_lookup", "node_nic_identity_lookup",
)))
V48102_RESET_APP_TABLES = tuple(dict.fromkeys(tuple(V48102_RESET_APP_TABLES) + (
    "vm_nic_identity_lookup", "node_nic_identity_lookup",
)))


# ---------------------------------------------------------------------------
# 50.5.8-r3 Consumption VM/Node view
# ---------------------------------------------------------------------------
# Scope is intentionally limited to the Consumption read path. Existing Agent
# collection, /push, Abuse, Dashboard, Storage I/O, Node Health, retention,
# maintenance and the legacy idempotent 2-hour accounting endpoint stay
# unchanged. VM rows reuse bandwidth_hourly/bandwidth_daily. Physical rows use
# exact retained physical samples for short ranges and the existing compact
# 2-hour node accounting for long ranges. No new per-VM history is created.

V5058C_PERIODS = {
    "1h": ("1H", 3600),
    "2h": ("2H", 2 * 3600),
    "6h": ("6H", 6 * 3600),
    "12h": ("12H", 12 * 3600),
    "24h": ("24H", 24 * 3600),
    "2d": ("2D", 2 * 86400),
    "7d": ("7D", 7 * 86400),
}
V5058C_LIMITS = (100, 200, 500)
V5058C_VM_SORTS = {
    "uuid": "vm_uuid",
    "node": "node",
    "public_rx": "public_rx",
    "public_tx": "public_tx",
    "public_total": "public_total",
    "private_rx": "private_rx",
    "private_tx": "private_tx",
    "private_total": "private_total",
    "coverage": "coverage_percent",
    "latest_sample": "latest_sample",
}
V5058C_NODE_SORTS = {
    "node": "node",
    "physical_public_rx": "physical_public_rx",
    "physical_public_tx": "physical_public_tx",
    "physical_public_total": "physical_public_total",
    "physical_private_rx": "physical_private_rx",
    "physical_private_tx": "physical_private_tx",
    "physical_private_total": "physical_private_total",
    "coverage": "coverage_percent",
    "latest_sample": "latest_sample",
}


def _v5058c_period(value):
    value = str(value or "24h").strip().lower()
    return value if value in V5058C_PERIODS else "24h"


def _v5058c_tab(value):
    value = str(value or "vm").strip().lower()
    return value if value in {"vm", "node"} else "vm"


def _v5058c_limit(value):
    value = safe_int(value, 100)
    return value if value in V5058C_LIMITS else 100


def _v5058c_coverage(value):
    value = str(value or "all").strip().lower()
    return value if value in {"all", "complete", "partial", "no_data"} else "all"


def _v5058c_sort(value, tab):
    allowed = V5058C_NODE_SORTS if tab == "node" else V5058C_VM_SORTS
    default = "physical_public_total" if tab == "node" else "public_total"
    value = str(value or default).strip().lower()
    return value if value in allowed else default


def _v5058c_order(value):
    return "asc" if str(value or "desc").strip().lower() == "asc" else "desc"


def _v5058c_bytes(value):
    value = max(0, safe_int(value, 0))
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    scaled = float(value)
    unit = units[0]
    for unit in units:
        if scaled < 1024.0 or unit == units[-1]:
            break
        scaled /= 1024.0
    if unit == "B":
        return "%d B" % value
    return "%.2f %s" % (scaled, unit)


def _v5058c_relative(ts):
    ts = max(0, safe_int(ts, 0))
    if not ts:
        return "No data"
    age = max(0, now_ts() - ts)
    if age < 60:
        return "%ss ago" % age
    if age < 3600:
        return "%sm ago" % max(1, age // 60)
    if age < 86400:
        return "%sh ago" % max(1, age // 3600)
    return "%sd ago" % max(1, age // 86400)


def _v5058c_day_bounds(start, end):
    """Return complete local-day range and partial hourly edge ranges."""
    start = safe_int(start, 0)
    end = safe_int(end, 0)
    first_day = local_day_start(start)
    full_start = start if start == first_day else first_day + 86400
    full_end = local_day_start(end)
    if end <= start:
        return 0, 0, []
    edges = []
    if full_start >= full_end:
        edges.append((start, end))
        return 0, 0, edges
    if start < full_start:
        edges.append((start, min(full_start, end)))
    if full_end < end:
        edges.append((max(full_end, start), end))
    return full_start, full_end, edges


def _v5058c_vm_source_sql(start, end, selected_node=""):
    """Build a compact hourly+daily source without overlapping full days."""
    full_start, full_end, edges = _v5058c_day_bounds(start, end)
    branches = []
    params = []
    node_clause = " AND node=?" if selected_node else ""

    if full_start and full_end and full_start < full_end:
        branches.append("""
            SELECT node,vm_uuid,bridge,rx_bytes,tx_bytes,sample_count,last_push
              FROM bandwidth_daily
             WHERE day_start>=? AND day_start<?%s
        """ % node_clause)
        params.extend([full_start, full_end])
        if selected_node:
            params.append(selected_node)

    for edge_start, edge_end in edges:
        if edge_end <= edge_start:
            continue
        hour_start = local_hour_start(edge_start)
        branches.append("""
            SELECT node,vm_uuid,bridge,rx_bytes,tx_bytes,sample_count,last_push
              FROM bandwidth_hourly
             WHERE hour_start>=? AND hour_start<?%s
        """ % node_clause)
        params.extend([hour_start, edge_end])
        if selected_node:
            params.append(selected_node)

    if not branches:
        branches.append("""
            SELECT node,vm_uuid,bridge,rx_bytes,tx_bytes,sample_count,last_push
              FROM bandwidth_hourly
             WHERE 1=0
        """)
    return " UNION ALL ".join(branches), params


def _v5058c_visible_vm_cte(selected_node=""):
    node_filter = " AND l.node=?" if selected_node else ""
    params = [PUBLIC_BRIDGE, PRIVATE_BRIDGE]
    if selected_node:
        params.append(selected_node)
    sql = """
        visible_vm AS (
            SELECT
                l.vm_uuid,
                l.node,
                COALESCE((
                    SELECT ba.primary_ipv4
                      FROM node_bridge_addresses_latest ba
                     WHERE ba.node=l.node AND LOWER(COALESCE(ba.role,''))='public'
                     ORDER BY ba.last_seen DESC
                     LIMIT 1
                ),'') AS node_ip,
                CASE WHEN EXISTS(
                    SELECT 1 FROM vm_iface_current ic
                     WHERE ic.node=l.node AND ic.vm_uuid=l.vm_uuid AND ic.bridge=?
                ) THEN 1 ELSE 0 END AS public_configured,
                CASE WHEN EXISTS(
                    SELECT 1 FROM vm_iface_current ic
                     WHERE ic.node=l.node AND ic.vm_uuid=l.vm_uuid AND ic.bridge=?
                ) THEN 1 ELSE 0 END AS private_configured
              FROM vm_location_latest l
              JOIN node_inventory ni ON ni.node=l.node
              JOIN vm_inventory vi ON vi.node=l.node AND vi.vm_uuid=l.vm_uuid
             WHERE COALESCE(ni.status,'active')!='hidden'
               AND ni.deleted_at IS NULL
               AND COALESCE(vi.status,'active')!='hidden'
               AND vi.deleted_at IS NULL
               %s
        )
    """ % node_filter
    return sql, params


def _v5058c_vm_ctes(start, end, selected_node=""):
    source_sql, source_params = _v5058c_vm_source_sql(start, end, selected_node)
    visible_sql, visible_params = _v5058c_visible_vm_cte(selected_node)
    expected_samples = max(1, int(math.ceil(max(1, end - start) / float(CACHE_BUCKET_SECONDS))))
    sql = """
        WITH source AS (
            %s
        ),
        per_bridge AS (
            SELECT vm_uuid,bridge,
                   COALESCE(SUM(rx_bytes),0)::bigint AS host_rx,
                   COALESCE(SUM(tx_bytes),0)::bigint AS host_tx,
                   COALESCE(SUM(sample_count),0)::bigint AS samples,
                   COALESCE(MAX(last_push),0)::bigint AS latest_sample
              FROM source
             GROUP BY vm_uuid,bridge
        ),
        vm_agg AS (
            SELECT vm_uuid,
                   COALESCE(SUM(CASE WHEN bridge=? THEN host_tx ELSE 0 END),0)::bigint AS public_rx,
                   COALESCE(SUM(CASE WHEN bridge=? THEN host_rx ELSE 0 END),0)::bigint AS public_tx,
                   COALESCE(SUM(CASE WHEN bridge=? THEN host_tx ELSE 0 END),0)::bigint AS private_rx,
                   COALESCE(SUM(CASE WHEN bridge=? THEN host_rx ELSE 0 END),0)::bigint AS private_tx,
                   COALESCE(MAX(samples),0)::bigint AS coverage_samples,
                   COALESCE(MAX(latest_sample),0)::bigint AS latest_sample
              FROM per_bridge
             GROUP BY vm_uuid
        ),
        %s,
        vm_rows AS (
            SELECT v.vm_uuid,v.node,v.node_ip,
                   v.public_configured,v.private_configured,
                   COALESCE(a.public_rx,0)::bigint AS public_rx,
                   COALESCE(a.public_tx,0)::bigint AS public_tx,
                   COALESCE(a.public_rx,0)::bigint+COALESCE(a.public_tx,0)::bigint AS public_total,
                   COALESCE(a.private_rx,0)::bigint AS private_rx,
                   COALESCE(a.private_tx,0)::bigint AS private_tx,
                   COALESCE(a.private_rx,0)::bigint+COALESCE(a.private_tx,0)::bigint AS private_total,
                   LEAST(100.0,COALESCE(a.coverage_samples,0)*100.0/?) AS coverage_percent,
                   COALESCE(a.latest_sample,0)::bigint AS latest_sample
              FROM visible_vm v
              LEFT JOIN vm_agg a ON a.vm_uuid=v.vm_uuid
        )
    """ % (source_sql, visible_sql)
    params = list(source_params)
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
    params = [like, like, like, like]
    if normalized_mac:
        params.append(normalized_mac)
    return """
        AND (
            LOWER(vm_uuid) LIKE LOWER(?)
            OR LOWER(node) LIKE LOWER(?)
            OR LOWER(node_ip) LIKE LOWER(?)
            OR EXISTS(
                SELECT 1 FROM vm_nic_identity_lookup mil
                 WHERE mil.vm_uuid=vm_rows.vm_uuid
                   AND (LOWER(COALESCE(mil.mac,'')) LIKE LOWER(?)%s)
            )
        )
    """ % mac_exact_sql, params


def _v5058c_coverage_clause(value):
    value = _v5058c_coverage(value)
    if value == "complete":
        return " AND latest_sample>0 AND coverage_percent>=99.5"
    if value == "partial":
        return " AND latest_sample>0 AND coverage_percent<99.5"
    if value == "no_data":
        return " AND latest_sample<=0"
    return ""


def _v5058c_vm_totals(start, end, selected_node=""):
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


def _v5058c_vm_rows(start, end, selected_node, q, coverage, sort_by, order, page_no, limit):
    ctes, params = _v5058c_vm_ctes(start, end, selected_node)
    search_sql, search_params = _v5058c_search_clause("vm", q)
    coverage_sql = _v5058c_coverage_clause(coverage)
    where_sql = " WHERE 1=1" + search_sql + coverage_sql
    conn = db()
    try:
        total = safe_int(conn.execute(
            ctes + "SELECT COUNT(*) FROM vm_rows" + where_sql,
            params + search_params,
        ).fetchone()[0], 0)
        max_page = max(1, int(math.ceil(total / float(max(1, limit)))))
        page_no = min(max(1, page_no), max_page)
        offset = (page_no - 1) * limit
        order_column = V5058C_VM_SORTS[sort_by]
        tie_order = "ASC" if sort_by in {"uuid", "node"} and order == "asc" else "DESC"
        rows = conn.execute(
            ctes + """
            SELECT vm_uuid,node,node_ip,public_configured,private_configured,
                   public_rx,public_tx,public_total,
                   private_rx,private_tx,private_total,
                   coverage_percent,latest_sample
              FROM vm_rows
            """ + where_sql + " ORDER BY %s %s,vm_uuid %s LIMIT ? OFFSET ?" % (
                order_column, order.upper(), tie_order,
            ),
            params + search_params + [limit, offset],
        ).fetchall()
        return rows, total, page_no, max_page
    finally:
        conn.close()


def _v5058c_raw_node_branch(start, end, selected_node=""):
    if end <= start:
        return "", []
    node_clause = " AND p.node=?" if selected_node else ""
    sql = """
        SELECT p.node,
               COALESCE(SUM(CASE WHEN LOWER(COALESCE(p.role,''))='public' THEN p.rx_delta ELSE 0 END),0)::bigint AS physical_public_rx,
               COALESCE(SUM(CASE WHEN LOWER(COALESCE(p.role,''))='public' THEN p.tx_delta ELSE 0 END),0)::bigint AS physical_public_tx,
               COALESCE(SUM(CASE WHEN LOWER(COALESCE(p.role,''))='private' THEN p.rx_delta ELSE 0 END),0)::bigint AS physical_private_rx,
               COALESCE(SUM(CASE WHEN LOWER(COALESCE(p.role,''))='private' THEN p.tx_delta ELSE 0 END),0)::bigint AS physical_private_tx,
               COALESCE(MAX(p.interval_seconds),0)::bigint AS coverage_seconds,
               COALESCE(MAX(p.last_push),0)::bigint AS latest_sample
          FROM node_physical_net_stats p
         WHERE p.time>=? AND p.time<?%s
         GROUP BY p.node,p.bucket
    """ % node_clause
    params = [start, end]
    if selected_node:
        params.append(selected_node)
    return sql, params


def _v5058c_node_source_sql(start, end, selected_node=""):
    """Use exact raw samples to 24H, then compact 2H accounting plus raw edges."""
    seconds = max(0, end - start)
    if seconds <= 86400:
        raw_sql, raw_params = _v5058c_raw_node_branch(start, end, selected_node)
        return raw_sql, raw_params

    bucket_start = _v5030_local_bucket_start(start)
    if bucket_start < start:
        bucket_start += V5030_BW_BUCKET_SECONDS
    tail_start = _v5030_local_bucket_start(end)
    parts = []
    params = []
    node_clause = " AND b.node=?" if selected_node else ""

    if bucket_start < tail_start:
        parts.append("""
            SELECT b.node,
                   COALESCE(SUM(b.physical_public_rx_bytes),0)::bigint AS physical_public_rx,
                   COALESCE(SUM(b.physical_public_tx_bytes),0)::bigint AS physical_public_tx,
                   COALESCE(SUM(b.physical_private_rx_bytes),0)::bigint AS physical_private_rx,
                   COALESCE(SUM(b.physical_private_tx_bytes),0)::bigint AS physical_private_tx,
                   COALESCE(SUM(b.coverage_seconds),0)::bigint AS coverage_seconds,
                   COALESCE(MAX(b.received_at),0)::bigint AS latest_sample
              FROM node_bandwidth_consumption_2h b
             WHERE b.bucket_start>=? AND b.bucket_end<=?%s
             GROUP BY b.node
        """ % node_clause)
        params.extend([bucket_start, tail_start])
        if selected_node:
            params.append(selected_node)

    if start < bucket_start:
        edge_sql, edge_params = _v5058c_raw_node_branch(start, min(bucket_start, end), selected_node)
        if edge_sql:
            parts.append(edge_sql)
            params.extend(edge_params)
    if tail_start < end:
        edge_sql, edge_params = _v5058c_raw_node_branch(max(tail_start, start), end, selected_node)
        if edge_sql:
            parts.append(edge_sql)
            params.extend(edge_params)

    if not parts:
        raw_sql, raw_params = _v5058c_raw_node_branch(start, end, selected_node)
        return raw_sql, raw_params
    return " UNION ALL ".join(parts), params


def _v5058c_node_ctes(start, end, selected_node=""):
    source_sql, source_params = _v5058c_node_source_sql(start, end, selected_node)
    node_filter = " AND ni.node=?" if selected_node else ""
    params = list(source_params)
    if selected_node:
        params.append(selected_node)
    expected_seconds = max(1, end - start)
    sql = """
        WITH source_parts AS (
            %s
        ),
        node_agg AS (
            SELECT node,
                   COALESCE(SUM(physical_public_rx),0)::bigint AS physical_public_rx,
                   COALESCE(SUM(physical_public_tx),0)::bigint AS physical_public_tx,
                   COALESCE(SUM(physical_private_rx),0)::bigint AS physical_private_rx,
                   COALESCE(SUM(physical_private_tx),0)::bigint AS physical_private_tx,
                   COALESCE(SUM(coverage_seconds),0)::bigint AS coverage_seconds,
                   COALESCE(MAX(latest_sample),0)::bigint AS latest_sample
              FROM source_parts
             GROUP BY node
        ),
        node_rows AS (
            SELECT ni.node,
                   COALESCE((
                       SELECT ba.primary_ipv4
                         FROM node_bridge_addresses_latest ba
                        WHERE ba.node=ni.node AND LOWER(COALESCE(ba.role,''))='public'
                        ORDER BY ba.last_seen DESC LIMIT 1
                   ),'') AS node_ip,
                   CASE WHEN EXISTS(
                       SELECT 1 FROM node_physical_net_latest pn
                        WHERE pn.node=ni.node AND LOWER(COALESCE(pn.role,''))='public'
                   ) OR EXISTS(
                       SELECT 1 FROM node_bridge_addresses_latest ba
                        WHERE ba.node=ni.node AND LOWER(COALESCE(ba.role,''))='public'
                   ) THEN 1 ELSE 0 END AS public_configured,
                   CASE WHEN EXISTS(
                       SELECT 1 FROM node_physical_net_latest pn
                        WHERE pn.node=ni.node AND LOWER(COALESCE(pn.role,''))='private'
                   ) OR EXISTS(
                       SELECT 1 FROM node_bridge_addresses_latest ba
                        WHERE ba.node=ni.node AND LOWER(COALESCE(ba.role,''))='private'
                   ) THEN 1 ELSE 0 END AS private_configured,
                   COALESCE(a.physical_public_rx,0)::bigint AS physical_public_rx,
                   COALESCE(a.physical_public_tx,0)::bigint AS physical_public_tx,
                   COALESCE(a.physical_public_rx,0)::bigint+COALESCE(a.physical_public_tx,0)::bigint AS physical_public_total,
                   COALESCE(a.physical_private_rx,0)::bigint AS physical_private_rx,
                   COALESCE(a.physical_private_tx,0)::bigint AS physical_private_tx,
                   COALESCE(a.physical_private_rx,0)::bigint+COALESCE(a.physical_private_tx,0)::bigint AS physical_private_total,
                   LEAST(100.0,COALESCE(a.coverage_seconds,0)*100.0/?) AS coverage_percent,
                   COALESCE(a.latest_sample,0)::bigint AS latest_sample
              FROM node_inventory ni
              LEFT JOIN node_agg a ON a.node=ni.node
             WHERE COALESCE(ni.status,'active')!='hidden'
               AND ni.deleted_at IS NULL
               %s
        )
    """ % (source_sql, node_filter)
    params.insert(len(source_params), expected_seconds)
    return sql, params


def _v5058c_node_totals(start, end, selected_node=""):
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


def _v5058c_node_rows(start, end, q, coverage, sort_by, order, page_no, limit):
    ctes, params = _v5058c_node_ctes(start, end)
    search_sql, search_params = _v5058c_search_clause("node", q)
    coverage_sql = _v5058c_coverage_clause(coverage)
    where_sql = " WHERE 1=1" + search_sql + coverage_sql
    conn = db()
    try:
        total = safe_int(conn.execute(
            ctes + "SELECT COUNT(*) FROM node_rows" + where_sql,
            params + search_params,
        ).fetchone()[0], 0)
        max_page = max(1, int(math.ceil(total / float(max(1, limit)))))
        page_no = min(max(1, page_no), max_page)
        offset = (page_no - 1) * limit
        order_column = V5058C_NODE_SORTS[sort_by]
        tie_order = "ASC" if sort_by == "node" and order == "asc" else "DESC"
        rows = conn.execute(
            ctes + """
            SELECT node,node_ip,public_configured,private_configured,
                   physical_public_rx,physical_public_tx,physical_public_total,
                   physical_private_rx,physical_private_tx,physical_private_total,
                   coverage_percent,latest_sample
              FROM node_rows
            """ + where_sql + " ORDER BY %s %s,node %s LIMIT ? OFFSET ?" % (
                order_column, order.upper(), tie_order,
            ),
            params + search_params + [limit, offset],
        ).fetchall()
        return rows, total, page_no, max_page
    finally:
        conn.close()


def _v5058c_visible_nodes():
    conn = db()
    try:
        return conn.execute("""
            SELECT ni.node,
                   COALESCE((
                       SELECT ba.primary_ipv4
                         FROM node_bridge_addresses_latest ba
                        WHERE ba.node=ni.node AND LOWER(COALESCE(ba.role,''))='public'
                        ORDER BY ba.last_seen DESC LIMIT 1
                   ),'') AS public_ipv4
              FROM node_inventory ni
             WHERE COALESCE(ni.status,'active')!='hidden'
               AND ni.deleted_at IS NULL
             ORDER BY LOWER(ni.node)
        """).fetchall()
    finally:
        conn.close()


def _v5058c_summary_card(title, prefix, totals, tone):
    rx = safe_int(totals.get(prefix + "_rx"), 0)
    tx = safe_int(totals.get(prefix + "_tx"), 0)
    return """
      <div class="card v5058c-summary %s">
        <div class="v5058c-summary-title">%s</div>
        <div class="v5058c-summary-values">
          <div><span>RX</span><b>%s</b></div>
          <div><span>TX</span><b>%s</b></div>
          <div class="total"><span>TOTAL</span><b>%s</b></div>
        </div>
      </div>
    """ % (tone, escape(title), _v5058c_bytes(rx), _v5058c_bytes(tx), _v5058c_bytes(rx + tx))


def _v5058c_metric_cell(value, configured=True, tone=""):
    if not configured:
        return '<span class="v5058c-na">Not configured</span>'
    return '<span class="v5058c-number %s">%s</span>' % (tone, _v5058c_bytes(value))


def _v5058c_coverage_cell(percent, latest):
    latest = safe_int(latest, 0)
    percent = max(0.0, min(100.0, safe_float(percent, 0.0)))
    if not latest:
        return '<span class="status neutral">No data</span>'
    cls = "ok" if percent >= 99.5 else "warn"
    return '<span class="status %s">%.1f%%</span>' % (cls, percent)


def _v5058c_latest_cell(ts):
    ts = safe_int(ts, 0)
    if not ts:
        return '<span class="v5058c-muted">No data</span>'
    return '<b class="v5058c-time">%s</b><small>%s</small>' % (
        escape(fmt_full(ts)), escape(_v5058c_relative(ts)),
    )


def _v5058c_common_args(tab, period, q, selected_node, coverage, limit, sort_by, order):
    result = {
        "tab": tab,
        "period": period,
        "q": q or None,
        "coverage": coverage if coverage != "all" else None,
        "limit": limit,
        "sort": sort_by,
        "order": order,
    }
    if tab == "vm" and selected_node:
        result["node"] = selected_node
    return result


def _v5058c_sort_link(label, key, tab, common, current_sort, current_order, grouped=False):
    next_order = "asc" if key == current_sort and current_order == "desc" else "desc"
    args = dict(common)
    args.update({"sort": key, "order": next_order, "page": 1})
    arrow = ""
    if key == current_sort:
        arrow = " ↓" if current_order == "desc" else " ↑"
    cls = "sort-link active" if key == current_sort else "sort-link"
    if grouped:
        cls += " grouped"
    return '<a class="%s" href="%s">%s%s</a>' % (
        cls,
        escape(url_for("bandwidth_consumption_page", **args), quote=True),
        escape(label), arrow,
    )


def _v5058c_pager(total, page_no, max_page, limit, common):
    def link(label, target, active=False, disabled=False):
        if disabled:
            return '<span class="page-link disabled">%s</span>' % escape(str(label))
        args = dict(common)
        args["page"] = target
        href = url_for("bandwidth_consumption_page", **args)
        return '<a class="page-link%s" href="%s">%s</a>' % (
            " active" if active else "", escape(href, quote=True), escape(str(label)),
        )

    items = [link("‹", max(1, page_no - 1), disabled=page_no <= 1)]
    page_set = {1, max_page, page_no - 1, page_no, page_no + 1}
    page_set = sorted(p for p in page_set if 1 <= p <= max_page)
    last = 0
    for number in page_set:
        if last and number - last > 1:
            items.append('<span class="page-gap">…</span>')
        items.append(link(number, number, active=number == page_no))
        last = number
    items.append(link("›", min(max_page, page_no + 1), disabled=page_no >= max_page))
    start_row = 0 if total <= 0 else (page_no - 1) * limit + 1
    end_row = min(total, page_no * limit)
    return """
      <div class="v5058c-pager">
        <div class="page-links">%s</div>
        <div class="page-summary">%s to %s of %s %s</div>
      </div>
    """ % (
        "".join(items), f"{start_row:,}", f"{end_row:,}", f"{total:,}",
        "Nodes" if common.get("tab") == "node" else "VMs",
    )


def _v5058c_vm_table(rows, common, sort_by, order):
    h = lambda label, key: _v5058c_sort_link(label, key, "vm", common, sort_by, order)
    body = []
    for row in rows:
        (vm_uuid, node, node_ip, public_configured, private_configured,
         public_rx, public_tx, public_total,
         private_rx, private_tx, private_total,
         coverage_percent, latest_sample) = row
        vm_href = url_for("vm_page", node=node, vm_uuid=vm_uuid, period="5m")
        node_href = url_for("node_page", node=node, period="5m")
        body.append("""
          <tr>
            <td class="v5058c-uuid"><span class="uuid-cell"><a class="mono" href="%s" title="%s">%s</a><button type="button" class="copy-btn" data-copy="%s" title="Copy UUID">⧉</button></span></td>
            <td class="v5058c-node"><a href="%s"><b>%s</b></a><small>%s</small></td>
            <td>%s</td><td>%s</td><td class="v5058c-total">%s</td>
            <td>%s</td><td>%s</td><td class="v5058c-total">%s</td>
            <td>%s</td><td class="v5058c-latest">%s</td>
          </tr>
        """ % (
            escape(vm_href, quote=True), escape(vm_uuid, quote=True), escape(vm_uuid), escape(vm_uuid, quote=True),
            escape(node_href, quote=True), escape(node), escape(compact_ipv4(node_ip) or "-"),
            _v5058c_metric_cell(public_rx, bool(public_configured), "public"),
            _v5058c_metric_cell(public_tx, bool(public_configured), "public"),
            _v5058c_metric_cell(public_total, bool(public_configured)),
            _v5058c_metric_cell(private_rx, bool(private_configured), "private"),
            _v5058c_metric_cell(private_tx, bool(private_configured), "private"),
            _v5058c_metric_cell(private_total, bool(private_configured)),
            _v5058c_coverage_cell(coverage_percent, latest_sample),
            _v5058c_latest_cell(latest_sample),
        ))
    if not body:
        body.append('<tr><td colspan="10" class="empty">No VM matches the selected filters.</td></tr>')
    return """
      <div class="table-wrap v5058c-table-wrap">
        <table class="v5058c-table v5058c-vm-table">
          <thead>
            <tr>
              <th rowspan="2">%s</th><th rowspan="2">%s</th>
              <th colspan="3" class="v5058c-public-head">PUBLIC</th>
              <th colspan="3" class="v5058c-private-head">PRIVATE</th>
              <th rowspan="2">%s</th><th rowspan="2">%s</th>
            </tr>
            <tr>
              <th>%s</th><th>%s</th><th>%s</th>
              <th>%s</th><th>%s</th><th>%s</th>
            </tr>
          </thead>
          <tbody>%s</tbody>
        </table>
      </div>
    """ % (
        h("VM / UUID", "uuid"), h("Node / Node IP", "node"),
        h("Coverage", "coverage"), h("Latest Sample", "latest_sample"),
        h("RX", "public_rx"), h("TX", "public_tx"), h("Total", "public_total"),
        h("RX", "private_rx"), h("TX", "private_tx"), h("Total", "private_total"),
        "".join(body),
    )


def _v5058c_node_table(rows, common, sort_by, order):
    h = lambda label, key: _v5058c_sort_link(label, key, "node", common, sort_by, order)
    body = []
    for row in rows:
        (node, node_ip, public_configured, private_configured,
         public_rx, public_tx, public_total,
         private_rx, private_tx, private_total,
         coverage_percent, latest_sample) = row
        node_href = url_for("node_page", node=node, period="5m")
        body.append("""
          <tr>
            <td class="v5058c-node"><a href="%s"><b>%s</b></a><small>%s</small></td>
            <td>%s</td><td>%s</td><td class="v5058c-total">%s</td>
            <td>%s</td><td>%s</td><td class="v5058c-total">%s</td>
            <td>%s</td><td class="v5058c-latest">%s</td>
          </tr>
        """ % (
            escape(node_href, quote=True), escape(node), escape(compact_ipv4(node_ip) or "-"),
            _v5058c_metric_cell(public_rx, bool(public_configured), "public"),
            _v5058c_metric_cell(public_tx, bool(public_configured), "public"),
            _v5058c_metric_cell(public_total, bool(public_configured)),
            _v5058c_metric_cell(private_rx, bool(private_configured), "private"),
            _v5058c_metric_cell(private_tx, bool(private_configured), "private"),
            _v5058c_metric_cell(private_total, bool(private_configured)),
            _v5058c_coverage_cell(coverage_percent, latest_sample),
            _v5058c_latest_cell(latest_sample),
        ))
    if not body:
        body.append('<tr><td colspan="9" class="empty">No node matches the selected filters.</td></tr>')
    return """
      <div class="table-wrap v5058c-table-wrap">
        <table class="v5058c-table v5058c-node-table">
          <thead>
            <tr>
              <th rowspan="2">%s</th>
              <th colspan="3" class="v5058c-public-head">PHYSICAL PUBLIC</th>
              <th colspan="3" class="v5058c-private-head">PHYSICAL PRIVATE</th>
              <th rowspan="2">%s</th><th rowspan="2">%s</th>
            </tr>
            <tr>
              <th>%s</th><th>%s</th><th>%s</th>
              <th>%s</th><th>%s</th><th>%s</th>
            </tr>
          </thead>
          <tbody>%s</tbody>
        </table>
      </div>
    """ % (
        h("Node / Node IP", "node"), h("Coverage", "coverage"), h("Latest Sample", "latest_sample"),
        h("RX", "physical_public_rx"), h("TX", "physical_public_tx"), h("Total", "physical_public_total"),
        h("RX", "physical_private_rx"), h("TX", "physical_private_tx"), h("Total", "physical_private_total"),
        "".join(body),
    )


def bandwidth_consumption_page_v5058c():
    tab = _v5058c_tab(request.args.get("tab"))
    period = _v5058c_period(request.args.get("period"))
    _period_label, seconds = V5058C_PERIODS[period]
    end = now_ts()
    start = end - seconds
    q = str(request.args.get("q") or "").strip()[:255]
    selected_node = str(request.args.get("node") or "").strip()[:255] if tab == "vm" else ""
    coverage = _v5058c_coverage(request.args.get("coverage"))
    limit = _v5058c_limit(request.args.get("limit"))
    page_no = max(1, safe_int(request.args.get("page"), 1))
    sort_by = _v5058c_sort(request.args.get("sort"), tab)
    order = _v5058c_order(request.args.get("order"))

    # Search and coverage only filter the table. Range and explicit node scope
    # control the overview totals. This avoids pretending that physical traffic
    # can be assigned to one searched UUID.
    summary_node = selected_node if tab == "vm" else ""
    totals = {}
    totals.update(_v5058c_node_totals(start, end, summary_node))
    totals.update(_v5058c_vm_totals(start, end, summary_node))

    common = _v5058c_common_args(
        tab, period, q, selected_node, coverage, limit, sort_by, order,
    )
    if tab == "node":
        rows, total, page_no, max_page = _v5058c_node_rows(
            start, end, q, coverage, sort_by, order, page_no, limit,
        )
        table_html = _v5058c_node_table(rows, common, sort_by, order)
    else:
        rows, total, page_no, max_page = _v5058c_vm_rows(
            start, end, selected_node, q, coverage, sort_by, order, page_no, limit,
        )
        table_html = _v5058c_vm_table(rows, common, sort_by, order)

    period_links = []
    for key, (label, _period_seconds) in V5058C_PERIODS.items():
        args = dict(common)
        args.update({"period": key, "page": 1})
        period_links.append('<a class="%s" href="%s">%s</a>' % (
            "active" if key == period else "",
            escape(url_for("bandwidth_consumption_page", **args), quote=True),
            escape(label),
        ))

    vm_tab_url = url_for("bandwidth_consumption_page", tab="vm", period=period, limit=limit)
    node_tab_url = url_for("bandwidth_consumption_page", tab="node", period=period, limit=limit)
    refresh_args = dict(common)
    refresh_args["_nocache"] = 1
    refresh_url = url_for("bandwidth_consumption_page", **refresh_args)

    node_options = ['<option value="">All Nodes</option>']
    if tab == "vm":
        for node_name, node_ip in _v5058c_visible_nodes():
            label = str(node_name)
            if node_ip:
                label += " · " + compact_ipv4(node_ip)
            node_options.append('<option value="%s"%s>%s</option>' % (
                escape(node_name, quote=True),
                " selected" if node_name == selected_node else "",
                escape(label),
            ))

    coverage_options = []
    for value, label in (
        ("all", "All Coverage"),
        ("complete", "Complete"),
        ("partial", "Partial"),
        ("no_data", "No data"),
    ):
        coverage_options.append('<option value="%s"%s>%s</option>' % (
            value, " selected" if value == coverage else "", label,
        ))
    limit_options = "".join(
        '<option value="%s"%s>%s</option>' % (
            item, " selected" if item == limit else "", item,
        ) for item in V5058C_LIMITS
    )

    toolbar = """
      <form class="v5058c-toolbar" method="get" action="%s">
        <input type="hidden" name="tab" value="%s">
        <input type="hidden" name="period" value="%s">
        <input type="hidden" name="sort" value="%s">
        <input type="hidden" name="order" value="%s">
        <div class="v5058c-search"><input name="q" value="%s" placeholder="%s"><span>⌕</span></div>
        %s
        <select name="coverage">%s</select>
        <label class="v5058c-show"><span>Show</span><select name="limit">%s</select></label>
        <button type="submit">Apply</button>
        <a class="clear" href="%s">Reset</a>
      </form>
    """ % (
        url_for("bandwidth_consumption_page"), escape(tab, quote=True), escape(period, quote=True),
        escape(sort_by, quote=True), escape(order, quote=True), escape(q, quote=True),
        "Search by Node or Node IP..." if tab == "node" else "Search by VM name, UUID, MAC, Node or Node IP...",
        ('<select name="node">%s</select>' % "".join(node_options)) if tab == "vm" else "",
        "".join(coverage_options), limit_options,
        escape(url_for("bandwidth_consumption_page", tab=tab, period=period, limit=100), quote=True),
    )

    pager = _v5058c_pager(total, page_no, max_page, limit, common)
    content = """
    <style id="v5058c-consumption-ui">
      .v5058c-shell{padding:16px!important}.v5058c-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;flex-wrap:wrap}.v5058c-head h2{margin:0}.v5058c-head p{margin:5px 0 0;color:var(--muted,#667085);font-size:12px}.v5058c-range{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}.v5058c-range-block>span{display:block;margin-bottom:6px;color:var(--muted,#667085);font-size:10px;font-weight:800}.v5058c-periods{display:flex;gap:6px;flex-wrap:wrap}.v5058c-periods a{min-width:46px;padding:8px 11px;border:1px solid var(--line,#dfe5ec);border-radius:8px;text-align:center;text-decoration:none;font-size:12px;font-weight:800}.v5058c-periods a.active{background:var(--brand,#2563eb);border-color:var(--brand,#2563eb);color:#fff!important}.v5058c-refresh{display:inline-flex;align-items:center;justify-content:center;width:38px;height:38px;border:1px solid var(--line,#dfe5ec);border-radius:9px;text-decoration:none;font-size:20px}
      .v5058c-tabs{display:flex;gap:6px;margin:16px 0 10px;border-bottom:1px solid var(--line,#dfe5ec)}.v5058c-tabs a{padding:9px 14px;text-decoration:none;color:var(--muted,#667085);font-size:12px;font-weight:800;border-bottom:2px solid transparent}.v5058c-tabs a.active{color:var(--brand,#2563eb);border-bottom-color:var(--brand,#2563eb)}
      .v5058c-summary-grid{display:grid;grid-template-columns:repeat(4,minmax(190px,1fr));gap:10px;margin-bottom:14px}.v5058c-summary{margin:0!important;padding:14px!important;box-shadow:none!important}.v5058c-summary-title{font-size:13px;font-weight:850;margin-bottom:11px}.v5058c-summary-values{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;align-items:end}.v5058c-summary-values span{display:block;color:var(--muted,#667085);font-size:10px}.v5058c-summary-values b{display:block;margin-top:4px;font-size:16px;white-space:nowrap;font-variant-numeric:tabular-nums}.v5058c-summary.public .v5058c-summary-values b{color:#45a9ff}.v5058c-summary.private .v5058c-summary-values b{color:#bd7cff}.v5058c-summary-values .total{padding-left:10px;border-left:1px solid var(--line,#dfe5ec)}.v5058c-summary-values .total b{color:var(--text,#111827)!important;font-weight:900}
      .v5058c-toolbar{display:grid;grid-template-columns:minmax(280px,1.6fr) minmax(170px,.8fr) minmax(160px,.7fr) auto auto auto;gap:10px;align-items:center;margin-bottom:12px}.v5058c-search{position:relative}.v5058c-search input{width:100%%;padding-right:38px!important}.v5058c-search span{position:absolute;right:13px;top:50%%;transform:translateY(-50%%);color:var(--muted,#667085);font-size:20px;pointer-events:none}.v5058c-show{display:flex;align-items:center;gap:8px;white-space:nowrap}.v5058c-show>span{font-size:11px;color:var(--muted,#667085)}.v5058c-show select{min-width:90px}.v5058c-toolbar .clear{min-height:38px;display:inline-flex;align-items:center;justify-content:center;padding:8px 13px;border:1px solid var(--line,#dfe5ec);border-radius:9px;text-decoration:none;font-size:12px;font-weight:800}
      .v5058c-table-wrap{border-radius:10px!important}.v5058c-table{min-width:1380px;table-layout:auto}.v5058c-node-table{min-width:1220px}.v5058c-table th{text-align:center!important;vertical-align:middle}.v5058c-table th:first-child,.v5058c-table th:nth-child(2){text-align:left!important}.v5058c-table td{text-align:right;white-space:nowrap;vertical-align:middle}.v5058c-table td:first-child,.v5058c-table td:nth-child(2){text-align:left}.v5058c-node-table td:first-child{text-align:left}.v5058c-public-head,.v5058c-public-head a{color:#45a9ff!important}.v5058c-private-head,.v5058c-private-head a{color:#bd7cff!important}.v5058c-number{font-variant-numeric:tabular-nums}.v5058c-number.public{color:#45a9ff}.v5058c-number.private{color:#bd7cff}.v5058c-total .v5058c-number{font-weight:850;color:var(--text,#111827)}.v5058c-na{color:var(--muted,#667085);font-size:10px}.v5058c-node a,.v5058c-uuid a{display:block}.v5058c-node small,.v5058c-latest small{display:block;margin-top:4px;color:var(--muted,#667085);font-size:10px}.v5058c-uuid .uuid-cell{display:flex;align-items:center;gap:6px;max-width:325px}.v5058c-uuid .uuid-cell>a{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.v5058c-time{font-size:11px}.v5058c-muted{color:var(--muted,#667085)}
      .v5058c-pager{display:flex;justify-content:space-between;align-items:center;gap:14px;margin-top:12px;flex-wrap:wrap}.v5058c-pager .page-links{display:flex;gap:5px;align-items:center}.v5058c-pager .page-link{min-width:34px;height:34px;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line,#dfe5ec);border-radius:7px;text-decoration:none;font-size:12px}.v5058c-pager .page-link.active{background:var(--brand,#2563eb);border-color:var(--brand,#2563eb);color:#fff!important}.v5058c-pager .page-link.disabled{opacity:.45}.v5058c-pager .page-summary{font-size:11px;color:var(--muted,#667085)}.v5058c-note{margin-top:10px;color:var(--muted,#667085);font-size:10px}
      html[data-theme="dark"] .v5058c-summary-values .total b,html[data-theme="dark"] .v5058c-total .v5058c-number{color:#f4f7fb!important}
      @media(max-width:1280px){.v5058c-summary-grid{grid-template-columns:repeat(2,minmax(190px,1fr))}.v5058c-toolbar{grid-template-columns:minmax(280px,1fr) repeat(2,minmax(150px,.5fr)) auto auto}.v5058c-toolbar .v5058c-show{grid-column:auto}}
      @media(max-width:800px){.v5058c-summary-grid{grid-template-columns:1fr}.v5058c-toolbar{display:flex;flex-direction:column;align-items:stretch}.v5058c-show{justify-content:space-between}.v5058c-head{display:block}.v5058c-range{margin-top:14px}.v5058c-summary-values b{font-size:14px}}
    </style>
    <div class="card v5058c-shell">
      <div class="v5058c-head">
        <div><h2>Consumption</h2><p>Network traffic consumption overview. Physical and aggregate VM traffic are separated for Public and Private networks.</p></div>
        <div class="v5058c-range"><div class="v5058c-range-block"><span>TIME RANGE</span><div class="v5058c-periods">%s</div></div><a class="v5058c-refresh" href="%s" title="Refresh">↻</a></div>
      </div>
      <div class="v5058c-tabs"><a class="%s" href="%s">VM Consumption</a><a class="%s" href="%s">Node Consumption</a></div>
      <div class="v5058c-summary-grid">%s%s%s%s</div>
      %s
      %s
      %s
      <div class="v5058c-note">Data follows the monitor's existing timezone and refresh cycle. VM RX/TX is normalized to the guest perspective. Search and pagination do not change the four overview totals.</div>
    </div>
    """ % (
        "".join(period_links), escape(refresh_url, quote=True),
        "active" if tab == "vm" else "", escape(vm_tab_url, quote=True),
        "active" if tab == "node" else "", escape(node_tab_url, quote=True),
        _v5058c_summary_card("Physical Public", "physical_public", totals, "public"),
        _v5058c_summary_card("Physical Private", "physical_private", totals, "private"),
        _v5058c_summary_card("VM Public", "vm_public", totals, "public"),
        _v5058c_summary_card("VM Private", "vm_private", totals, "private"),
        toolbar, table_html, pager,
    )
    return page("Consumption", content)


# Replace only the effective Consumption page implementation. All existing
# endpoints and writers remain registered and unchanged.
app.view_functions["bandwidth_consumption_page"] = bandwidth_consumption_page_v5058c
_v48140_cached_endpoint("bandwidth_consumption_page", V48140_PAGE_CACHE_TTL)

# ---------------------------------------------------------------------------
