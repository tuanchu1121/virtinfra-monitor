def clean_top_sort(sort_by):
    allowed = {"total", "rx", "tx", "public", "private", "mbps", "peakmbps", "pps", "peakpps", "sample", "drops", "errors", "cpu", "cpufull", "vcpu", "ram", "diskr", "diskw", "last_push", "node", "vm"}
    return sort_by if sort_by in allowed else "total"


def clean_top_scope(scope):
    allowed = {"all", "public", "private"}
    return scope if scope in allowed else "all"


def clean_abuse_sort(sort_by):
    allowed = {
        "severity", "node", "vm", "total", "avg_mbps", "peak_mbps",
        "avg_pps", "peak_pps", "cpu", "core_cpu", "ram", "last_push",
        "drops", "errors",
    }
    return sort_by if sort_by in allowed else "severity"


def clean_top_node_sort(sort_by):
    allowed = {
        "node", "last_seen", "snapshot", "vm", "load", "uptime", "cpu", "ram",
        "public_pps", "private_pps", "public", "private", "total",
        "diskr", "diskw", "drops", "errors", "source",
    }
    return sort_by if sort_by in allowed else "cpu"



def expected_samples_for_period(period):
    return max(1, int(math.ceil(period_seconds(period) / float(CACHE_BUCKET_SECONDS))))


def fmt_optional_percent(value, has_data=True):
    return fmt_percent(value) if has_data else "-"


def fmt_optional_rate(value, has_data=True):
    return human_rate(value) if has_data else "-"


def fmt_optional_human(value, has_data=True):
    return human(value) if has_data else "-"


def top_node_period_links(current, q="", sort_by="cpu", order="desc", limit=100):
    links = []
    for period in PERIODS:
        href = url_for(
            "top_node_page",
            period=period,
            q=q,
            sort=sort_by,
            order=order,
            limit=limit,
        )
        cls = "active" if period == current else ""
        links.append(f'<a class="{cls}" href="{escape(href, quote=True)}">{escape(period_label(period))}</a>')
    return "".join(links)


def top_period_links(current, q="", sort_by="total", order="desc", scope="all", limit=100):
    links = []
    for period in PERIODS:
        href = url_for(
            "top_page",
            period=period,
            q=q,
            sort=sort_by,
            order=order,
            scope=scope,
            limit=limit,
        )
        cls = "active" if period == current else ""
        links.append(f'<a class="{cls}" href="{escape(href, quote=True)}">{escape(period_label(period))}</a>')
    return "".join(links)


def clean_node_health_sort(sort_by):
    allowed = {"node", "status", "last_push", "age", "missed", "vm", "interfaces", "total"}
    return sort_by if sort_by in allowed else "status"


def node_health_sort_header(label, key, q, current_sort, current_order):
    current_sort = clean_node_health_sort(current_sort)
    current_order = clean_sort_order(current_order)
    default_order = {
        "node": "asc",
        "status": "asc",
        "last_push": "desc",
        "age": "asc",
        "missed": "asc",
        "vm": "desc",
        "interfaces": "desc",
        "total": "desc",
    }.get(key, "asc")
    next_order = reverse_order(current_order) if current_sort == key else default_order
    arrow = ""
    if current_sort == key:
        arrow = " ↓" if current_order == "desc" else " ↑"
    href = url_for(
        "node_health_page",
        q=q,
        sort=key,
        order=next_order,
    )
    return f'<a class="sort-link" href="{escape(href, quote=True)}">{escape(label)}{arrow}</a>'


def get_node_health_rows(q="", sort_by="status", order="asc"):
    """Fast Node Health read.

    Important:
    - Do not backfill missed history inside an HTTP request.
    - Do not scan millions of node_stats rows for the 24-hour total.
    - Read 24-hour traffic from bandwidth_hourly and current VM/interface
      counts from the latest compact node_push_snapshots row.
    """
    auto_cleanup_inventory()
    sort_by = clean_node_health_sort(sort_by)
    order = clean_sort_order(order)
    day_start = now_ts() - 86400
    hour_start = local_hour_start(day_start)
    node_visible_after = now_ts() - NODE_AUTO_DELETE_SECONDS

    last_push_expr = "COALESCE(ni.last_push, ls.last_push, total24.stat_last_push, 0)"
    status_expr = f"""
        CASE
          WHEN {last_push_expr} >= strftime('%s','now') - {STALE_GREEN_SECONDS} THEN 0
          WHEN {last_push_expr} >= strftime('%s','now') - {STALE_YELLOW_SECONDS} THEN 1
          ELSE 2
        END
    """
    missed_expr = f"""
        CAST(
          MAX(
            0,
            strftime('%s','now') - {last_push_expr} - {STATUS_PUSH_SECONDS}
          )
          / {STATUS_PUSH_SECONDS}
          AS INTEGER
        )
    """

    order_map = {
        "node": "n.node COLLATE NOCASE",
        "status": status_expr,
        "last_push": last_push_expr,
        "age": last_push_expr,
        "missed": f"(COALESCE(mh.completed_missed_cycles, 0) + ({missed_expr}))",
        "vm": "COALESCE(inv_vm.vm_count_inventory, ls.vm_count, 0)",
        "interfaces": "COALESCE(ls.iface_count, 0)",
        "total": "COALESCE(total24.total_24h, 0)",
    }
    order_sql = order_map[sort_by]
    sql_order = reverse_order(order) if sort_by == "age" else order

    params = [hour_start]
    search_sql = ""
    if q:
        p = like_pattern(q)
        normalized_mac = normalize_mac_address(q)
        search_sql = """
          AND (
                n.node LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM node_bridge_addresses_latest bai
                    WHERE bai.node=n.node
                      AND (
                            COALESCE(bai.primary_ipv4, '') LIKE ?
                            OR COALESCE(bai.ipv4_json, '[]') LIKE ?
                            OR COALESCE(bai.primary_ipv6, '') LIKE ?
                            OR COALESCE(bai.ipv6_json, '[]') LIKE ?
                            OR COALESCE(bai.bridge, '') LIKE ?
                            OR COALESCE(bai.mac, '') LIKE ?
                            OR (?<>'' AND LOWER(COALESCE(bai.mac,''))=LOWER(?))
                          )
                )
                OR EXISTS (
                    SELECT 1
                    FROM vm_inventory svi
                    WHERE svi.node=n.node
                      AND (
                            svi.vm_uuid LIKE ?
                            OR COALESCE(svi.last_iface, '') LIKE ?
                            OR COALESCE(svi.last_bridge, '') LIKE ?
                          )
                )
                OR EXISTS (
                    SELECT 1
                    FROM vm_location_latest svl
                    WHERE svl.node=n.node
                      AND (
                            svl.vm_uuid LIKE ?
                            OR COALESCE(svl.last_iface, '') LIKE ?
                            OR COALESCE(svl.last_bridge, '') LIKE ?
                          )
                )
                OR EXISTS (
                    SELECT 1
                    FROM vm_node_presence svp
                    WHERE svp.node=n.node
                      AND (
                            svp.vm_uuid LIKE ?
                            OR COALESCE(svp.last_iface, '') LIKE ?
                            OR COALESCE(svp.last_bridge, '') LIKE ?
                          )
                )
                OR EXISTS (
                    SELECT 1
                    FROM vm_iface_current svi_mac
                    WHERE svi_mac.node=n.node
                      AND (
                            svi_mac.vm_uuid LIKE ?
                            OR COALESCE(svi_mac.iface,'') LIKE ?
                            OR COALESCE(svi_mac.mac,'') LIKE ?
                            OR (?<>'' AND LOWER(COALESCE(svi_mac.mac,''))=LOWER(?))
                          )
                )
                OR EXISTS (
                    SELECT 1
                    FROM vm_latest_metrics svm
                    WHERE svm.node=n.node
                      AND (
                            svm.vm_uuid LIKE ?
                            OR COALESCE(svm.iface, '') LIKE ?
                            OR COALESCE(svm.bridge, '') LIKE ?
                          )
                )
                OR EXISTS (
                    SELECT 1
                    FROM node_physical_net_latest snp
                    WHERE snp.node=n.node
                      AND (
                            COALESCE(snp.iface, '') LIKE ?
                            OR COALESCE(snp.bridge, '') LIKE ?
                            OR COALESCE(snp.role, '') LIKE ?
                            OR COALESCE(snp.mac, '') LIKE ?
                            OR (?<>'' AND LOWER(COALESCE(snp.mac,''))=LOWER(?))
                          )
                )
              )
        """
        params.extend([
            p,
            p, p, p, p, p, p, normalized_mac, normalized_mac,
            p, p, p,
            p, p, p,
            p, p, p,
            p, p, p, normalized_mac, normalized_mac,
            p, p, p,
            p, p, p, p, normalized_mac, normalized_mac,
        ])
    params.append(node_visible_after)

    sql = f"""
    WITH total24 AS (
        SELECT
            bh.node,
            MAX(bh.last_push) AS stat_last_push,
            SUM(bh.rx_bytes + bh.tx_bytes) AS total_24h
        FROM bandwidth_hourly bh
        LEFT JOIN vm_inventory vi
          ON vi.node = bh.node
         AND vi.vm_uuid = bh.vm_uuid
        WHERE bh.hour_start >= ?
          AND COALESCE(vi.status, 'active') != 'hidden'
          AND vi.deleted_at IS NULL
        GROUP BY bh.node
    ),
    latest_snapshot_key AS (
        SELECT node, MAX(bucket) AS bucket
        FROM node_push_snapshots
        GROUP BY node
    ),
    latest_snapshot AS (
        SELECT
            s.node,
            s.last_push,
            s.vm_count,
            s.iface_count
        FROM node_push_snapshots s
        JOIN latest_snapshot_key k
          ON k.node=s.node
         AND k.bucket=s.bucket
    ),
    inv_vm AS (
        SELECT node, COUNT(DISTINCT vm_uuid) AS vm_count_inventory
        FROM vm_inventory
        WHERE COALESCE(status, 'active') != 'hidden'
          AND deleted_at IS NULL
        GROUP BY node
    ),
    bridge_ip AS (
        SELECT
            node,
            MAX(CASE WHEN LOWER(role)='public' THEN primary_ipv4 ELSE '' END) AS public_ipv4,
            MAX(CASE WHEN LOWER(role)='public' THEN ipv4_json ELSE '[]' END) AS public_ipv4_json
        FROM node_bridge_addresses_latest
        GROUP BY node
    ),
    miss_hist AS (
        SELECT
            node,
            COALESCE(SUM(missed_cycles), 0) AS completed_missed_cycles,
            COUNT(*) AS miss_incidents
        FROM node_missed_events
        WHERE recovered_at >= strftime('%s','now') - 86400
        GROUP BY node
    ),
    miss_last AS (
        SELECT
            e.node,
            e.missed_from AS last_missed_from,
            e.recovered_at AS last_recovered_at,
            e.missed_cycles AS last_missed_cycles
        FROM node_missed_events e
        JOIN (
            SELECT node, MAX(id) AS max_id
            FROM node_missed_events
            WHERE recovered_at >= strftime('%s','now') - 86400
            GROUP BY node
        ) latest_event
          ON latest_event.max_id=e.id
    ),
    node_names AS (
        SELECT node FROM node_inventory
        UNION
        SELECT node FROM latest_snapshot
        UNION
        SELECT node FROM total24
    )
    SELECT
        n.node,
        {last_push_expr} AS last_push,
        COALESCE(inv_vm.vm_count_inventory, ls.vm_count, 0) AS vm_count,
        COALESCE(ls.iface_count, 0) AS iface_count,
        COALESCE(total24.total_24h, 0) AS total_24h,
        COALESCE(ni.status, 'active') AS inv_status,
        COALESCE(bip.public_ipv4, '') AS public_ipv4,
        {missed_expr} AS current_missed_cycles,
        COALESCE(mh.completed_missed_cycles, 0) AS completed_missed_cycles,
        COALESCE(mh.miss_incidents, 0) AS miss_incidents,
        COALESCE(ml.last_missed_from, 0) AS last_missed_from,
        COALESCE(ml.last_recovered_at, 0) AS last_recovered_at,
        COALESCE(ml.last_missed_cycles, 0) AS last_missed_cycles
    FROM node_names n
    LEFT JOIN node_inventory ni
      ON ni.node = n.node
    LEFT JOIN latest_snapshot ls
      ON ls.node = n.node
    LEFT JOIN total24
      ON total24.node = n.node
    LEFT JOIN inv_vm
      ON inv_vm.node = n.node
    LEFT JOIN bridge_ip bip
      ON bip.node = n.node
    LEFT JOIN miss_hist mh
      ON mh.node = n.node
    LEFT JOIN miss_last ml
      ON ml.node = n.node
    WHERE (ni.node IS NULL OR (COALESCE(ni.status, 'active') != 'hidden' AND ni.deleted_at IS NULL))
      {search_sql}
      AND {last_push_expr} >= ?
    ORDER BY
      {order_sql} {sql_order.upper()},
      n.node COLLATE NOCASE ASC
    """
    conn = db()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()

def node_health_summary(rows):
    total = len(rows)
    healthy = warning = down = 0
    for row in rows:
        state = health_state(row[1])
        if state == "healthy":
            healthy += 1
        elif state == "warning":
            warning += 1
        else:
            down += 1
    return total, healthy, warning, down


def node_health_table(rows, q="", sort_by="status", order="asc"):
    body = ""
    now = now_ts()
    for (
        node, last_push, vm_count, iface_count, total_24h, inv_status, public_ipv4,
        current_missed, completed_missed, miss_incidents,
        last_missed_from, last_recovered_at, last_missed_cycles,
    ) in rows:
        age = now - int(last_push or 0) if last_push else 0
        node_href = url_for("node_page", node=node, period="24h")
        public_ip = compact_ipv4(public_ipv4)

        current_missed = safe_int(current_missed, 0)
        completed_missed = safe_int(completed_missed, 0)
        miss_incidents = safe_int(miss_incidents, 0)
        total_missed = completed_missed + current_missed
        total_incidents = miss_incidents + (1 if current_missed > 0 else 0)

        tooltip_lines = [
            f"Missed cycles in last 24h: {total_missed}",
            f"Incidents: {total_incidents}",
            f"Current missed cycles: {current_missed}",
        ]
        if last_recovered_at:
            tooltip_lines.append(
                f"Last recovered incident: {fmt_full(last_missed_from)} → "
                f"{fmt_full(last_recovered_at)} ({safe_int(last_missed_cycles, 0)} cycles)"
            )
        elif total_missed == 0:
            tooltip_lines.append("No recorded missed cycles")
        miss_tooltip = "\n".join(tooltip_lines)
        miss_href = url_for("node_missed_detail_page", node=node)
        miss_class = "missed-cycles-link current" if current_missed > 0 else "missed-cycles-link"

        body += f"""
        <tr>
            <td class="mono">
                <div class="node-name-cell">
                    <a href="{escape(node_href, quote=True)}"><b>{escape(node)}</b></a>
                    {f'<small class="node-ipv4" title="Public IPv4">{escape(public_ip)}</small>' if public_ip else ''}
                </div>
            </td>
            <td>{health_badge(last_push)}</td>
            <td>{fmt_full(last_push)}</td>
            <td>{human_age(age) if last_push else '-'}</td>
            <td>
                <a class="{miss_class}"
                   href="{escape(miss_href, quote=True)}"
                   data-bw-tooltip="{escape(miss_tooltip, quote=True)}"
                   aria-label="{escape(miss_tooltip, quote=True)}">{total_missed}</a>
            </td>
            <td>{vm_count or 0}</td>
            <td>{iface_count or 0}</td>
            <td><b>{human(total_24h)}</b></td>
        </tr>
        """
    if not body:
        body = '<tr><td colspan="8" class="empty">No nodes</td></tr>'

    total, healthy, warning, down = node_health_summary(rows)
    headers = {
        "node": node_health_sort_header("NODE", "node", q, sort_by, order),
        "status": node_health_sort_header("STATUS", "status", q, sort_by, order),
        "last_push": node_health_sort_header("LAST PUSH", "last_push", q, sort_by, order),
        "age": node_health_sort_header("AGE", "age", q, sort_by, order),
        "missed": node_health_sort_header("MISSED 24H", "missed", q, sort_by, order),
        "vm": node_health_sort_header("VM", "vm", q, sort_by, order),
        "interfaces": node_health_sort_header("INTERFACES", "interfaces", q, sort_by, order),
        "total": node_health_sort_header("TOTAL 24H", "total", q, sort_by, order),
    }

    return f"""
    <div class="card">
        <div class="table-title-row">
            <h3>Node Health</h3>
            <div class="count-badges">
                <span>Total <b>{total}</b></span>
                <span>Healthy <b>{healthy}</b></span>
                <span>Warning <b>{warning}</b></span>
                <span>Down <b>{down}</b></span>
                <span>Sort <b>{escape(sort_by)} {escape(order)}</b></span>
            </div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>{headers['node']}</th>
                    <th>{headers['status']}</th>
                    <th>{headers['last_push']}</th>
                    <th>{headers['age']}</th>
                    <th>{headers['missed']}</th>
                    <th>{headers['vm']}</th>
                    <th>{headers['interfaces']}</th>
                    <th>{headers['total']}</th>
                </tr>
            </thead>
            <tbody>{body}</tbody>
        </table>
    </div>
    """

def top_scope_links(period, q, sort_by, order, scope, limit):
    items = []
    for s, label in (("all", "All"), ("public", "Public only"), ("private", "Private only")):
        href = url_for("top_page", period=period, q=q, sort=sort_by, order=order, scope=s, limit=limit)
        cls = "active" if scope == s else ""
        items.append(f'<a class="{cls}" href="{escape(href, quote=True)}">{escape(label)}</a>')
    return "".join(items)


def top_sort_header(label, key, period, q, current_sort, current_order, scope, limit):
    current_sort = clean_top_sort(current_sort)
    current_order = clean_sort_order(current_order)
    default_order = "asc" if key in ("node", "vm") else "desc"
    next_order = reverse_order(current_order) if current_sort == key else default_order
    arrow = ""
    if current_sort == key:
        arrow = " ↓" if current_order == "desc" else " ↑"
    href = url_for(
        "top_page",
        period=period,
        q=q,
        sort=key,
        order=next_order,
        scope=scope,
        limit=limit,
    )
    return f'<a class="sort-link" href="{escape(href, quote=True)}">{escape(label)}{arrow}</a>'



def get_top_vm_rows(period, q="", sort_by="total", order="desc", scope="all", limit=100):
    auto_cleanup_inventory(); sort_by=clean_top_sort(sort_by); order=clean_sort_order(order); scope=clean_top_scope(scope); limit=max(10,min(1000,safe_int(limit,100)))
    conn=db()
    try:
        selected_bucket,latest_bucket=resolve_snapshot_bucket(conn,period,node=None)
        if not selected_bucket:return [],0,0,limit
        params=[CACHE_BUCKET_SECONDS,CACHE_BUCKET_SECONDS,selected_bucket,PUBLIC_BRIDGE,PRIVATE_BRIDGE,CACHE_BUCKET_SECONDS,CACHE_BUCKET_SECONDS,selected_bucket]
        extra_sql=""
        if scope=="public":extra_sql+=" AND ns.bridge=?";params.append(PUBLIC_BRIDGE)
        elif scope=="private":extra_sql+=" AND ns.bridge=?";params.append(PRIVATE_BRIDGE)
        if q:
            p=like_pattern(q);extra_sql+=""" AND (ns.node LIKE ? OR ns.vm_uuid LIKE ? OR ns.iface LIKE ? OR EXISTS (SELECT 1 FROM node_bridge_addresses_latest bai WHERE bai.node=ns.node AND (COALESCE(bai.primary_ipv4,'') LIKE ? OR COALESCE(bai.ipv4_json,'[]') LIKE ?)))""";params.extend([p,p,p,p,p])
        order_map={"total":"total","rx":"rx","tx":"tx","public":"public_total","private":"private_total","mbps":"avg_mbps","peakmbps":"peak_mbps","pps":"avg_pps","peakpps":"peak_pps","sample":"sample_quality_rank","drops":"drops","errors":"errors","cpu":"core_cpu_percent","cpufull":"cpu_percent","vcpu":"vcpu_current","ram":"ram_rss_kib","diskr":"disk_read_bps","diskw":"disk_write_bps","last_push":"last_push","node":"ns.node COLLATE NOCASE","vm":"ns.vm_uuid COLLATE NOCASE"}
        order_sql=order_map[sort_by];params.append(limit)
        rows=conn.execute(f"""
        WITH perf AS (
          SELECT node,vm_uuid,MAX(COALESCE(cpu_percent,0)) cpu_percent,MAX(COALESCE(vcpu_current,0)) vcpu_current,MAX(COALESCE(ram_rss_kib,0)) ram_rss_kib,MAX(COALESCE(ram_current_kib,0)) ram_current_kib,
          MAX(COALESCE(disk_read_delta,0)*1.0/MAX(COALESCE(interval_seconds,?),1)) disk_read_bps,MAX(COALESCE(disk_write_delta,0)*1.0/MAX(COALESCE(interval_seconds,?),1)) disk_write_bps
          FROM vm_perf_stats WHERE bucket=? GROUP BY node,vm_uuid)
        SELECT ns.node,ns.vm_uuid,COUNT(DISTINCT ns.bridge||':'||ns.iface) iface_count,
          SUM(CASE WHEN ns.bridge=? THEN ns.rx_delta+ns.tx_delta ELSE 0 END) public_total,SUM(CASE WHEN ns.bridge=? THEN ns.rx_delta+ns.tx_delta ELSE 0 END) private_total,
          SUM(ns.rx_delta) rx,SUM(ns.tx_delta) tx,SUM(ns.rx_delta+ns.tx_delta) total,SUM(ns.rx_packets_delta+ns.tx_packets_delta) packets,SUM(ns.rx_drop_delta+ns.tx_drop_delta) drops,SUM(ns.rx_error_delta+ns.tx_error_delta) errors,
          SUM((ns.rx_delta+ns.tx_delta)*8.0/MAX(COALESCE(ns.interval_seconds,1),1)/1000000.0) avg_mbps,
          MAX(MAX(COALESCE(ns.rx_mbps_peak,0),COALESCE(ns.tx_mbps_peak,0))) peak_mbps,
          SUM(ns.rx_packets_delta+ns.tx_packets_delta)*1.0/MAX(MAX(COALESCE(ns.interval_seconds,?)),1) avg_pps,
          MAX(MAX(COALESCE(ns.rx_pps_peak,0),COALESCE(ns.tx_pps_peak,0))) peak_pps,
          SUM(COALESCE(ns.network_sample_count,0)) sample_count,SUM(COALESCE(ns.network_sample_expected,0)) sample_expected,MAX(COALESCE(ns.network_sample_max_gap_seconds,0)) sample_max_gap_seconds,
          SUM(COALESCE(ns.seconds_over_pps,0)) seconds_over_pps,SUM(COALESCE(ns.seconds_over_mbps,0)) seconds_over_mbps,
          MAX(CASE UPPER(COALESCE(ns.network_sample_quality,'LEGACY')) WHEN 'POOR' THEN 3 WHEN 'DEGRADED' THEN 2 WHEN 'GOOD' THEN 1 ELSE 0 END) sample_quality_rank,
          MAX(COALESCE(p.cpu_percent,0)) cpu_percent,MAX(COALESCE(p.vcpu_current,0)) vcpu_current,
          MAX(CASE WHEN COALESCE(p.cpu_percent,0)<=100 THEN COALESCE(p.cpu_percent,0)*CASE WHEN COALESCE(p.vcpu_current,0)>0 THEN p.vcpu_current ELSE 1 END ELSE COALESCE(p.cpu_percent,0) END) core_cpu_percent,
          MAX(COALESCE(p.ram_rss_kib,0)) ram_rss_kib,MAX(COALESCE(p.ram_current_kib,0)) ram_current_kib,MAX(COALESCE(p.disk_read_bps,0)) disk_read_bps,MAX(COALESCE(p.disk_write_bps,0)) disk_write_bps,
          MAX(ns.last_push) last_push,MAX(COALESCE(ns.interval_seconds,?)) interval_seconds,
          COALESCE((SELECT bai.primary_ipv4 FROM node_bridge_addresses_latest bai WHERE bai.node=ns.node AND LOWER(bai.role)='public' ORDER BY bai.last_seen DESC LIMIT 1),'') public_ipv4,
          COALESCE((SELECT bai.primary_ipv4 FROM node_bridge_addresses_latest bai WHERE bai.node=ns.node AND LOWER(bai.role)='private' ORDER BY bai.last_seen DESC LIMIT 1),'') private_ipv4
        FROM node_stats ns LEFT JOIN node_inventory ni ON ni.node=ns.node LEFT JOIN vm_inventory vi ON vi.node=ns.node AND vi.vm_uuid=ns.vm_uuid LEFT JOIN perf p ON p.node=ns.node AND p.vm_uuid=ns.vm_uuid
        WHERE ns.bucket=? AND (ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL)) AND COALESCE(vi.status,'active')!='hidden' {extra_sql}
        GROUP BY ns.node,ns.vm_uuid
        HAVING SUM(COALESCE(ns.rx_delta,0)+COALESCE(ns.tx_delta,0))>0
        ORDER BY {order_sql} {order.upper()},total DESC,ns.node COLLATE NOCASE ASC,ns.vm_uuid COLLATE NOCASE ASC LIMIT ?
        """,params).fetchall()
        return rows,selected_bucket,latest_bucket,limit
    finally:conn.close()



def top_vm_table(rows, period, q, sort_by, order, scope, limit):
    body = ""
    rank = 1
    for (
        node, vm_uuid, iface_count, public_total, private_total, rx, tx, total,
        packets, drops, errors, avg_mbps, peak_mbps, avg_pps, peak_pps,
        sample_count, sample_expected, sample_max_gap, seconds_over_pps, seconds_over_mbps,
        sample_quality_rank, cpu_percent, vcpu_current, core_cpu_percent,
        ram_rss_kib, ram_current_kib, disk_read_bps, disk_write_bps,
        last_push, interval_seconds, public_ipv4, private_ipv4,
    ) in rows:
        _row_at = (request.args.get("at") or "").strip()
        href = url_for("node_page", node=node, period=period, q=vm_uuid, **({"at": _row_at} if _row_at else {}))
        public_ip = compact_ipv4(public_ipv4)
        ip_lines = f'<small class="node-ipv4" title="Public IPv4">{escape(public_ip)}</small>' if public_ip else ""
        sample = network_sample_badge(network_quality_from_rank(sample_quality_rank), sample_count, sample_expected, sample_max_gap)
        ram_pct = (float(ram_rss_kib or 0) * 100.0 / float(ram_current_kib or 1)) if ram_current_kib else 0.0
        ram_html = fmt_ram_pair(ram_rss_kib, ram_current_kib)
        if ram_current_kib:
            ram_html += f'<small class="metric-subline">{ram_pct:.1f}% RSS</small>'
        body += f"""
        <tr>
            <td class="num">{rank}</td>
            <td class="mono"><div class="node-name-cell"><a href="{escape(href, quote=True)}"><b>{escape(node)}</b></a>{ip_lines}</div></td>
            <td class="mono"><span class="uuid-cell"><a href="{escape(href, quote=True)}" title="{escape(vm_uuid)}">{escape(vm_uuid)}</a><button type="button" class="copy-btn" data-copy="{escape(vm_uuid)}" title="Copy UUID">⧉</button></span></td>
            <td class="num">{iface_count or 0}</td>
            <td class="num">{human(public_total)}</td>
            <td class="num">{human(private_total)}</td>
            <td class="num"><b>{human(total)}</b></td>
            <td class="num">{float(avg_mbps or 0):.2f}</td>
            <td class="num"><b>{float(peak_mbps or 0):.2f}</b></td>
            <td class="num">{fmt_pps_value(avg_pps)}</td>
            <td class="num"><b>{fmt_pps_value(peak_pps)}</b></td>
            <td class="num sample-cell">{sample}</td>
            <td class="num"><b>{fmt_vm_cpu(cpu_percent, vcpu_current)}</b><small class="metric-subline">{float(cpu_percent or 0):.1f}% full</small></td>
            <td class="num">{int(vcpu_current or 0)}</td>
            <td class="num ram-cell">{ram_html}</td>
            <td class="num">{human_rate(disk_read_bps)}</td>
            <td class="num">{human_rate(disk_write_bps)}</td>
            <td class="num">{fmt_push(last_push)}</td>
            <td class="num">{int(drops or 0)}</td>
            <td class="num">{int(errors or 0)}</td>
        </tr>"""
        rank += 1
    if not body:
        body = '<tr><td colspan="20" class="empty">No VM data at this selected snapshot</td></tr>'
    h = lambda label, key: top_sort_header(label, key, period, q, sort_by, order, scope, limit)
    return f"""
    <div class="card vm-table-card">
        <div class="table-title-row"><h3>Top VM Across All Nodes</h3><div class="count-badges"><span>Rows <b>{len(rows)}</b></span><span>Scope <b>{escape(scope)}</b></span><span>Mode <b>fast current / exact history</b></span><span>Sort <b>{escape(sort_by)} {escape(order)}</b></span></div></div>
        <div class="table-wrap">
        <table class="table-top-vm">
            <colgroup>
                <col class="top-rank"><col class="top-node"><col class="top-uuid"><col class="top-ifaces">
                <col class="top-public"><col class="top-private"><col class="top-total">
                <col class="top-mbps"><col class="top-peakmbps"><col class="top-pps"><col class="top-peakpps">
                <col class="top-sample"><col class="top-cpu"><col class="top-vcpu"><col class="top-ram">
                <col class="top-diskr"><col class="top-diskw"><col class="top-push"><col class="top-drops"><col class="top-errors">
            </colgroup>
            <thead><tr>
                <th>#</th><th>{h('NODE','node')}</th><th>{h('VM UUID','vm')}</th><th>IFACES</th>
                <th class="num-head">{h('PUBLIC','public')}</th><th class="num-head">{h('PRIVATE','private')}</th><th class="num-head">{h('TOTAL','total')}</th>
                <th class="num-head">{h('AVG Mbps','mbps')}</th><th class="num-head">{h('PEAK Mbps','peakmbps')}</th>
                <th class="num-head">{h('AVG PPS','pps')}</th><th class="num-head">{h('PEAK PPS','peakpps')}</th><th class="num-head">{h('SAMPLE','sample')}</th>
                <th class="num-head">{h('CPU Core%','cpu')}</th><th class="num-head">{h('vCPU','vcpu')}</th><th class="num-head">{h('RAM','ram')}</th>
                <th class="num-head">{h('DISK R/s','diskr')}</th><th class="num-head">{h('DISK W/s','diskw')}</th><th class="num-head">{h('PUSH','last_push')}</th>
                <th class="num-head">{h('DROPS','drops')}</th><th class="num-head">{h('ERR','errors')}</th>
            </tr></thead>
            <tbody>{body}</tbody>
        </table>
        </div>
        <div class="table-hint">PEAK comes from local sampling on the node. PostgreSQL receives one summary per node every five minutes.</div>
    </div>"""

def top_node_sort_header(label, key, period, q, current_sort, current_order, limit):
    current_sort = clean_top_node_sort(current_sort)
    current_order = clean_sort_order(current_order)
    default_order = "asc" if key == "node" else "desc"
    next_order = reverse_order(current_order) if current_sort == key else default_order
    arrow = ""
    if current_sort == key:
        arrow = " ↓" if current_order == "desc" else " ↑"
    href = url_for(
        "top_node_page",
        period=period,
        q=q,
        sort=key,
        order=next_order,
        limit=limit,
    )
    return f'<a class="sort-link" href="{escape(href, quote=True)}">{escape(label)}{arrow}</a>'


def get_top_node_rows(period, q="", sort_by="cpu", order="desc", limit=100):
    sort_by = clean_top_node_sort(sort_by)
    order = clean_sort_order(order)
    limit = max(10, min(500, safe_int(limit, 100)))
    mapping = {
        "node": "node", "last_seen": "last_push", "snapshot": "snapshot",
        "vm": "vm", "load": "load", "uptime": "uptime", "cpu": "cpu",
        "ram": "ram", "public_pps": "public_pps", "private_pps": "private_pps",
        "public": "public", "private": "private", "total": "total",
        "diskr": "diskr", "diskw": "diskw", "drops": "drops",
        "errors": "errors", "source": "source",
    }
    rows, start, end = get_node_rows(
        period, q, sort_by=mapping.get(sort_by, "cpu"), order=order
    )
    return rows[:limit], start, end, limit


def top_node_table(rows, period, q, sort_by, order, limit):
    body = ""
    rank = 1
    for r in rows:
        (
            node, live_seen, snapshot, tier, vm_count, iface_count,
            public_total, private_total, node_total,
            public_packets, private_packets, public_interval, private_interval,
            node_packets, node_interval, drops, errors,
            host_present, load1, load5, load15, cpu_count, cpu_percent, ram_percent,
            disk_read, disk_write, uptime, source, pub_ifaces, pri_ifaces,
            pub_pps_sort, pri_pps_sort, node_pps_sort,
            public_ipv4, private_ipv4,
        ) = r
        _row_at = (request.args.get("at") or "").strip()
        href = url_for("node_page", node=node, period=period, **({"at": _row_at} if _row_at else {}))
        pub_pps = float(public_packets or 0) / max(1.0, float(public_interval or CACHE_BUCKET_SECONDS))
        pri_pps = float(private_packets or 0) / max(1.0, float(private_interval or CACHE_BUCKET_SECONDS))
        tier_cls = "active" if tier == "raw" else "yellow"
        load_html = dashboard_load_html(
            load1, load5, load15, cpu_count, host_present=bool(host_present)
        )
        body += f"""
        <tr>
            <td>{rank}</td>
            <td class="mono">
                <div class="node-name-cell">
                    <a href="{escape(href, quote=True)}"><b>{escape(node)}</b></a>
                    {f'<small class="node-ipv4" title="Public IPv4">{escape(compact_ipv4(public_ipv4))}</small>' if public_ipv4 else ''}
                </div>
            </td>
            <td>{status_badge(live_seen)}</td>
            <td class="mono">{fmt_full(snapshot)}</td>
            <td>{int(vm_count or 0)}</td>
            <td>{load_html}</td>
            <td>{fmt_uptime(uptime) if host_present else '-'}</td>
            <td>{fmt_percent(cpu_percent) if host_present else '-'}</td>
            <td>{fmt_percent(ram_percent) if host_present else '-'}</td>
            <td>{fmt_pps_value(pub_pps)}</td>
            <td>{fmt_pps_value(pri_pps)}</td>
            <td><b>{human(public_total)}</b></td>
            <td><b>{human(private_total)}</b></td>
            <td><b>{human(node_total)}</b></td>
            <td>{human_rate(disk_read) if host_present else '-'}</td>
            <td>{human_rate(disk_write) if host_present else '-'}</td>
            <td>{escape(str(source or '-'))}</td>
            <td>{int(drops or 0)}</td>
            <td>{int(errors or 0)}</td>
        </tr>
        """
        rank += 1
    if not body:
        body = '<tr><td colspan="19" class="empty">No retained node snapshot data</td></tr>'

    def h(label, key):
        return top_node_sort_header(label, key, period, q, sort_by, order, limit)

    return f"""
    <div class="card">
        <div class="table-title-row">
            <h3>Top Nodes · Exact Snapshot</h3>
            <div class="count-badges">
                <span>Rows <b>{len(rows)}</b></span>
                <span>Status <b>live</b></span>
                <span>Metrics <b>same snapshot</b></span>
            </div>
        </div>
        <table>
            <thead><tr>
                <th>#</th><th>{h('NODE','node')}</th><th>{h('STATUS','last_seen')}</th>
                <th>{h('SNAPSHOT','snapshot')}</th><th>{h('VM','vm')}</th>
                <th>{h('LOAD','load')}</th><th>{h('UPTIME','uptime')}</th>
                <th>{h('CPU','cpu')}</th><th>{h('RAM','ram')}</th>
                <th>{h('PUBLIC PPS','public_pps')}</th><th>{h('PRIVATE PPS','private_pps')}</th>
                <th>{h('PUBLIC','public')}</th><th>{h('PRIVATE','private')}</th><th>{h('TOTAL','total')}</th>
                <th>{h('DISK R/s','diskr')}</th><th>{h('DISK W/s','diskw')}</th>
                <th>{h('SRC','source')}</th><th>{h('DROPS','drops')}</th><th>{h('ERR','errors')}</th>
            </tr></thead>
            <tbody>{body}</tbody>
        </table>
        <div class="table-hint">No averages or period sums. Each row uses one retained push; status uses the newest heartbeat.</div>
    </div>
    """


