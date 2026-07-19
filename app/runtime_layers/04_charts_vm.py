def chart_step_seconds(period):
    """Expected native resolution. Queries now return retained real buckets only."""
    period = clean_period(period)
    return CACHE_BUCKET_SECONDS if period_seconds(period) <= RAW_RETENTION_DAYS * 86400 else 3600

def vm_period_links(current, node, vm_uuid, bridge, iface):
    links = []
    for period in PERIODS:
        href = url_for(
            "vm_page",
            node=node,
            vm_uuid=vm_uuid,
            bridge=bridge,
            iface=iface,
            period=period,
        )
        cls = "active" if period == current else ""
        links.append(f'<a class="{cls}" href="{escape(href, quote=True)}">{escape(period_label(period))}</a>')
    return "".join(links)

def query_vm_chart(node, vm_uuid, period, bridge="", iface=""):
    """Return exact retained VM network buckets with whole-window averages and local peaks."""
    start, end = range_for_period(period)
    params = [node, vm_uuid, start, end]
    extra_sql = ""
    if bridge:
        extra_sql += " AND bridge=?"; params.append(bridge)
    if iface:
        extra_sql += " AND iface=?"; params.append(iface)
    conn = db()
    try:
        raw_rows = conn.execute(f"""
            SELECT bucket,
                   SUM(MAX(rx_delta,0)), SUM(MAX(tx_delta,0)), SUM(MAX(rx_delta,0)+MAX(tx_delta,0)),
                   SUM(MAX(rx_packets_delta,0)), SUM(MAX(tx_packets_delta,0)),
                   SUM(MAX(rx_drop_delta,0)), SUM(MAX(tx_drop_delta,0)),
                   SUM(MAX(rx_error_delta,0)), SUM(MAX(tx_error_delta,0)),
                   MAX(last_push), MAX(COALESCE(interval_seconds,?)),
                   MAX(COALESCE(rx_mbps_peak,0)), MAX(COALESCE(tx_mbps_peak,0)),
                   MAX(COALESCE(rx_pps_peak,0)), MAX(COALESCE(tx_pps_peak,0)),
                   SUM(COALESCE(network_sample_count,0)), SUM(COALESCE(network_sample_expected,0)),
                   MAX(COALESCE(network_sample_max_gap_seconds,0)),
                   SUM(COALESCE(seconds_over_pps,0)), SUM(COALESCE(seconds_over_mbps,0)),
                   MAX(CASE UPPER(COALESCE(network_sample_quality,'LEGACY')) WHEN 'POOR' THEN 3 WHEN 'DEGRADED' THEN 2 WHEN 'GOOD' THEN 1 ELSE 0 END)
            FROM node_stats
            WHERE node=? AND vm_uuid=? AND bucket>=? AND bucket<? {extra_sql}
            GROUP BY bucket ORDER BY bucket
        """, [CACHE_BUCKET_SECONDS] + params).fetchall()
    finally:
        conn.close()
    rows = []
    for r in raw_rows:
        interval = max(1, int(r[11] or CACHE_BUCKET_SECONDS))
        rx, tx = int(r[1] or 0), int(r[2] or 0)
        rxp, txp = int(r[4] or 0), int(r[5] or 0)
        rxd, txd, rxe, txe = int(r[6] or 0), int(r[7] or 0), int(r[8] or 0), int(r[9] or 0)
        rows.append({
            "bucket": int(r[0]), "label": fmt_chart_label(r[0], interval),
            "rx": rx, "tx": tx, "total": int(r[3] or 0),
            "rx_mbps": rx*8.0/interval/1000000.0, "tx_mbps": tx*8.0/interval/1000000.0,
            "mbps": (rx+tx)*8.0/interval/1000000.0,
            "rx_mbps_peak": float(r[12] or 0), "tx_mbps_peak": float(r[13] or 0),
            "peak_mbps": max(float(r[12] or 0), float(r[13] or 0)),
            "rx_packets": rxp, "tx_packets": txp, "packets": rxp+txp,
            "rx_pps": rxp/interval, "tx_pps": txp/interval, "pps": (rxp+txp)/interval,
            "rx_pps_peak": float(r[14] or 0), "tx_pps_peak": float(r[15] or 0),
            "peak_pps": max(float(r[14] or 0), float(r[15] or 0)),
            "rx_packet_size_avg": rx/float(rxp) if rxp else 0.0,
            "tx_packet_size_avg": tx/float(txp) if txp else 0.0,
            "sample_count": int(r[16] or 0), "sample_expected": int(r[17] or 0),
            "sample_max_gap_seconds": float(r[18] or 0),
            "seconds_over_pps": int(r[19] or 0), "seconds_over_mbps": int(r[20] or 0),
            "sample_quality": network_quality_from_rank(r[21]),
            "rx_drops": rxd, "tx_drops": txd, "drops": rxd+txd,
            "rx_errors": rxe, "tx_errors": txe, "errors": rxe+txe,
            "last_push": int(r[10] or 0), "interval_seconds": interval,
        })
    gaps = [rows[i]["bucket"]-rows[i-1]["bucket"] for i in range(1, len(rows)) if rows[i]["bucket"]>rows[i-1]["bucket"]]
    step = min(gaps) if gaps else chart_step_seconds(period)
    return rows, start, end, step

NODE_CHART_MAX_POINTS = max(60, min(480, int(os.environ.get("BW_NODE_CHART_MAX_POINTS", "240"))))

def _node_retained_buckets(conn, node, period):
    """Return real retained buckets in the requested range from the compact index.

    Falling back to node_stats keeps pre-index installations readable. This query
    touches one compact row per push, not every VM row in the period.
    """
    start, end = range_for_period(period)
    rows = conn.execute(
        """
        SELECT bucket
        FROM node_push_snapshots
        WHERE node=? AND bucket>=? AND bucket<?
        ORDER BY bucket
        """,
        (node, start, end),
    ).fetchall()
    if not rows:
        rows = conn.execute(
            """
            SELECT DISTINCT bucket
            FROM node_stats
            WHERE node=? AND bucket>=? AND bucket<?
            ORDER BY bucket
            """,
            (node, start, end),
        ).fetchall()
    return [int(row[0]) for row in rows if row and int(row[0] or 0) > 0]

def _sample_real_buckets(bucket_ids, max_points=NODE_CHART_MAX_POINTS):
    """Evenly select real push buckets without averaging or inventing zeroes."""
    ids = list(dict.fromkeys(int(v) for v in bucket_ids if int(v or 0) > 0))
    if len(ids) <= max_points:
        return ids
    if max_points <= 1:
        return [ids[-1]]
    chosen = []
    last_index = len(ids) - 1
    for i in range(max_points):
        idx = round(i * last_index / (max_points - 1))
        value = ids[idx]
        if not chosen or chosen[-1] != value:
            chosen.append(value)
    return chosen

def _sql_in_placeholders(values):
    return ",".join("?" for _ in values) or "NULL"

def query_node_chart(node, period, q="", vm_status="active"):
    """Return at most NODE_CHART_MAX_POINTS real node buckets.

    The old implementation grouped every VM row in the legacy long-range window for
    several charts, which could make /node pages time out. This version first
    samples real retained push buckets from node_push_snapshots, then reads only
    those buckets. No value is averaged and no fake zero bucket is created.
    """
    start, end = range_for_period(period)
    conn = db()
    try:
        bucket_ids = _sample_real_buckets(_node_retained_buckets(conn, node, period))
        if not bucket_ids:
            return [], start, end, chart_step_seconds(period)
        placeholders = _sql_in_placeholders(bucket_ids)
        params = [PUBLIC_BRIDGE, PRIVATE_BRIDGE, node] + bucket_ids
        search_sql = ""
        if q:
            search_sql = " AND (ns.vm_uuid LIKE ? OR ns.iface LIKE ? OR ns.node LIKE ?)"
            p = like_pattern(q)
            params.extend([p, p, p])
        raw_rows = conn.execute(f"""
            SELECT
                ns.bucket,
                SUM(CASE WHEN ns.bridge=? THEN ns.rx_delta+ns.tx_delta ELSE 0 END),
                SUM(CASE WHEN ns.bridge=? THEN ns.rx_delta+ns.tx_delta ELSE 0 END),
                SUM(ns.rx_delta), SUM(ns.tx_delta), SUM(ns.rx_delta+ns.tx_delta),
                MAX(ns.last_push)
            FROM node_stats ns
            LEFT JOIN vm_inventory vi ON vi.node=ns.node AND vi.vm_uuid=ns.vm_uuid
            WHERE ns.node=? AND ns.bucket IN ({placeholders})
              AND COALESCE(vi.status, 'active')!='hidden'
              {search_sql}
            GROUP BY ns.bucket
            ORDER BY ns.bucket
        """, params).fetchall()
    finally:
        conn.close()
    rows = [{
        "bucket": int(r[0]), "label": fmt_chart_label(r[0], CACHE_BUCKET_SECONDS),
        "public": int(r[1] or 0), "private": int(r[2] or 0),
        "rx": int(r[3] or 0), "tx": int(r[4] or 0), "total": int(r[5] or 0),
        "last_push": int(r[6] or 0),
    } for r in raw_rows]
    gaps = [rows[i]["bucket"] - rows[i-1]["bucket"] for i in range(1, len(rows))]
    step = min((g for g in gaps if g > 0), default=chart_step_seconds(period))
    return rows, start, end, step

def sample_chart_rows(rows, max_points=360):
    rows = list(rows or [])
    if len(rows) <= max_points:
        return rows
    stride = max(1, int(math.ceil(len(rows) / float(max_points))))
    sampled = rows[::stride]
    if rows and sampled[-1] is not rows[-1]:
        sampled.append(rows[-1])
    return sampled

NODE_SNAPSHOT_ROWS_PER_PAGE = 50

def node_chart_raw_sort_header(label, key, node, period, q, current_sort, current_order, table_sort, table_order):
    current_sort = clean_node_chart_sort(current_sort)
    current_order = clean_sort_order(current_order)
    next_order = reverse_order(current_order) if current_sort == key else "desc"
    href = url_for(
        "node_page",
        node=node,
        period=period,
        q=q,
        sort=table_sort,
        order=table_order,
        chart_sort=key,
        chart_order=next_order,
        raw_page=1,
        raw_limit=NODE_SNAPSHOT_ROWS_PER_PAGE,
        net=clean_node_net_mode(request.args.get("net", "both")),
    ) + "#real-snapshot-samples"
    arrow = " ↓" if current_sort == key and current_order == "desc" else (" ↑" if current_sort == key else "")
    return f'<a class="sort-link" href="{escape(href, quote=True)}">{escape(label)}{arrow}</a>'

def node_chart_table(rows, node, period, q="", chart_sort="time", chart_order="desc", table_sort="total", table_order="desc"):
    chart_sort = clean_node_chart_sort(chart_sort)
    chart_order = clean_sort_order(chart_order)
    page_no = clean_page(request.args.get("raw_page", 1))
    limit = NODE_SNAPSHOT_ROWS_PER_PAGE

    key_map = {
        "time": lambda r: int(r["bucket"]),
        "public": lambda r: int(r["public"]),
        "private": lambda r: int(r["private"]),
        "rx": lambda r: int(r["rx"]),
        "tx": lambda r: int(r["tx"]),
        "total": lambda r: int(r["total"]),
    }
    all_rows = sorted(
        list(rows),
        key=key_map[chart_sort],
        reverse=(chart_order == "desc"),
    )

    total = len(all_rows)
    total_pages = max(1, int(math.ceil(total / float(limit))))
    page_no = min(page_no, total_pages)
    offset = (page_no - 1) * limit
    page_rows = all_rows[offset:offset + limit]

    body = "".join(
        f"<tr>"
        f"<td class='mono'>{fmt_full(r['bucket'])}</td>"
        f"<td>{human(r['public'])}</td>"
        f"<td>{human(r['private'])}</td>"
        f"<td>{human(r['rx'])}</td>"
        f"<td>{human(r['tx'])}</td>"
        f"<td><b>{human(r['total'])}</b></td>"
        f"</tr>"
        for r in page_rows
    )
    if not body:
        body = '<tr><td colspan="6" class="empty">No retained data in this period</td></tr>'

    headers = [
        node_chart_raw_sort_header(
            label,
            key,
            node,
            period,
            q,
            chart_sort,
            chart_order,
            table_sort,
            table_order,
        )
        for label, key in (
            ("TIME", "time"),
            ("PUBLIC", "public"),
            ("PRIVATE", "private"),
            ("RX", "rx"),
            ("TX", "tx"),
            ("TOTAL", "total"),
        )
    ]

    net_mode = clean_node_net_mode(request.args.get("net", "both"))

    def page_href(target):
        return url_for(
            "node_page",
            node=node,
            period=period,
            q=q,
            sort=table_sort,
            order=table_order,
            chart_sort=chart_sort,
            chart_order=chart_order,
            raw_page=target,
            raw_limit=limit,
            net=net_mode,
        ) + "#real-snapshot-samples"

    def page_link(label, target, active=False, disabled=False):
        if disabled:
            return f'<span class="page-link disabled">{escape(str(label))}</span>'
        cls = "page-link active" if active else "page-link"
        return f'<a class="{cls}" href="{escape(page_href(target), quote=True)}">{escape(str(label))}</a>'

    page_items = [
        page_link("Prev", max(1, page_no - 1), disabled=(page_no <= 1))
    ]
    page_set = {1, total_pages, page_no - 2, page_no - 1, page_no, page_no + 1, page_no + 2}
    page_set = sorted(p for p in page_set if 1 <= p <= total_pages)
    last_page = 0
    for target in page_set:
        if last_page and target - last_page > 1:
            page_items.append('<span class="page-gap">...</span>')
        page_items.append(page_link(target, target, active=(target == page_no)))
        last_page = target
    page_items.append(
        page_link("Next", min(total_pages, page_no + 1), disabled=(page_no >= total_pages))
    )

    start_row = 0 if total == 0 else offset + 1
    end_row = min(total, offset + limit)
    pager = f"""
    <div class="pagination">
        <div class="page-summary">
            Showing <b>{start_row}</b>-<b>{end_row}</b> of <b>{total}</b>
            · Page <b>{page_no}/{total_pages}</b>
        </div>
        <div class="page-links">{''.join(page_items)}</div>
    </div>
    """

    return f"""
    <div class="card node-chart-table" id="real-snapshot-samples">
        <div class="table-title-row">
            <h3>Real Snapshot Samples</h3>
            <div class="count-badges">
                <span>Displayed <b>{len(page_rows)}</b></span>
                <span>Total <b>{total}</b></span>
                <span>Rows/page <b>{limit}</b></span>
                <span>No averaging <b>enabled</b></span>
            </div>
        </div>
        <div class="table-wrap">
            <table>
                <thead><tr>{''.join(f'<th>{h}</th>' for h in headers)}</tr></thead>
                <tbody>{body}</tbody>
            </table>
        </div>
        {pager}
        <div class="table-hint">
            The table shows 50 real retained snapshots per page. For fast long-range pages,
            the app still selects at most {NODE_CHART_MAX_POINTS} real pushes; values are not averaged or zero-filled.
        </div>
    </div>
    """

def nice_ceiling(value):
    value = float(value or 0)
    if value <= 0:
        return 1
    exponent = math.floor(math.log10(value))
    fraction = value / (10 ** exponent)
    if fraction <= 1:
        nice = 1
    elif fraction <= 2:
        nice = 2
    elif fraction <= 5:
        nice = 5
    else:
        nice = 10
    return nice * (10 ** exponent)

def point_xy(rows, idx, key, x0, y0, plot_w, plot_h, max_v):
    if len(rows) == 1:
        x = x0 + plot_w / 2
    else:
        x = x0 + (idx * plot_w / (len(rows) - 1))
    y = y0 + plot_h - ((rows[idx][key] / max_v) * plot_h if max_v else 0)
    return x, y

def make_points(rows, key, x0, y0, plot_w, plot_h, max_v):
    if not rows:
        return ""
    if len(rows) == 1:
        x = x0 + plot_w / 2
        y = y0 + plot_h - ((rows[0][key] / max_v) * plot_h if max_v else 0)
        return f"{x:.1f},{y:.1f}"

    points = []
    for i, row in enumerate(rows):
        x = x0 + (i * plot_w / (len(rows) - 1))
        y = y0 + plot_h - ((row[key] / max_v) * plot_h if max_v else 0)
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)

def vm_raw_sort_header(label, key, node, vm_uuid, bridge, iface, period, current_sort, current_order):
    current_sort=clean_chart_table_sort(current_sort); current_order=clean_sort_order(current_order)
    next_order=reverse_order(current_order) if current_sort==key else "desc"
    href=url_for("vm_page",node=node,vm_uuid=vm_uuid,bridge=bridge,iface=iface,period=period,raw_sort=key,raw_order=next_order,raw_page=1,raw_limit=max(25,min(200,safe_int(request.args.get("raw_limit"),100))))
    arrow=" ↓" if current_sort==key and current_order=="desc" else (" ↑" if current_sort==key else "")
    return f'<a class="sort-link" href="{escape(href,quote=True)}">{escape(label)}{arrow}</a>'

def vm_chart_table(rows, node, vm_uuid, bridge, iface, period, raw_sort="time", raw_order="desc"):
    raw_sort=clean_chart_table_sort(raw_sort); raw_order=clean_sort_order(raw_order)
    page_no=clean_page(request.args.get("raw_page",1)); limit=max(25,min(200,safe_int(request.args.get("raw_limit"),100)))
    key_map={
        "time":lambda r:int(r["bucket"]), "rx":lambda r:int(r["rx"]), "tx":lambda r:int(r["tx"]), "total":lambda r:int(r["total"]),
        "mbps":lambda r:float(r.get("mbps",0)), "peakmbps":lambda r:float(r.get("peak_mbps",0)),
        "pps":lambda r:float(r.get("pps",0)), "peakpps":lambda r:float(r.get("peak_pps",0)),
        "sample":lambda r:network_sample_quality_rank(r.get("sample_quality")),
        "drops":lambda r:int(r.get("drops",0)), "errors":lambda r:int(r.get("errors",0)),
    }
    all_rows=sorted(list(rows),key=key_map[raw_sort],reverse=(raw_order=="desc")); total=len(all_rows); pages=max(1,int(math.ceil(total/float(limit)))); page_no=min(page_no,pages); page_rows=all_rows[(page_no-1)*limit:page_no*limit]
    body=""
    for r in page_rows:
        sample=network_sample_badge(r.get("sample_quality"),r.get("sample_count"),r.get("sample_expected"),r.get("sample_max_gap_seconds"))
        body += f"<tr><td class='mono'>{fmt_full(r['bucket'])}</td><td>{r.get('mbps',0):.2f}</td><td><b>{r.get('peak_mbps',0):.2f}</b></td><td>{fmt_pps_value(r.get('pps',0))}</td><td><b>{fmt_pps_value(r.get('peak_pps',0))}</b></td><td>{sample}</td><td>{human(r['rx'])}</td><td>{human(r['tx'])}</td><td><b>{human(r['total'])}</b></td><td>{int(r.get('drops',0))}</td><td>{int(r.get('errors',0))}</td></tr>"
    if not body: body='<tr><td colspan="11" class="empty">No retained data in this period</td></tr>'
    labels=(('TIME','time'),('AVG Mbps','mbps'),('PEAK Mbps','peakmbps'),('AVG PPS','pps'),('PEAK PPS','peakpps'),('SAMPLE','sample'),('RX','rx'),('TX','tx'),('TOTAL','total'),('DROPS','drops'),('ERR','errors'))
    headers=[vm_raw_sort_header(lbl,key,node,vm_uuid,bridge,iface,period,raw_sort,raw_order) for lbl,key in labels]
    def link(label,target,disabled=False):
        if disabled:return f'<span class="page-link disabled">{label}</span>'
        href=url_for("vm_page",node=node,vm_uuid=vm_uuid,bridge=bridge,iface=iface,period=period,raw_sort=raw_sort,raw_order=raw_order,raw_page=target,raw_limit=limit)
        return f'<a class="page-link" href="{escape(href,quote=True)}">{label}</a>'
    pager=f'<div class="pagination"><div class="page-summary">Showing <b>{0 if total==0 else (page_no-1)*limit+1}</b>-<b>{min(total,page_no*limit)}</b> of <b>{total}</b></div><div class="page-links">{link("Prev",max(1,page_no-1),page_no<=1)}<span class="page-link active">{page_no}/{pages}</span>{link("Next",min(pages,page_no+1),page_no>=pages)}</div></div>'
    return f"""<div class="card small-chart vm-raw-table"><h3>Retained Network Snapshots</h3><table><thead><tr>{''.join(f'<th>{h}</th>' for h in headers)}</tr></thead><tbody>{body}</tbody></table>{pager}<div class="table-hint">AVG uses exact whole-window counters. PEAK is the highest local sample. No 15-second rows are stored in the database.</div></div>"""

def vm_scope_text(bridge, iface):
    parts = []
    if bridge:
        if bridge == PUBLIC_BRIDGE:
            parts.append("Public")
        elif bridge == PRIVATE_BRIDGE:
            parts.append("Private")
        else:
            parts.append(bridge)
    if iface:
        parts.append(f"Interface {iface}")
    return " / ".join(parts) if parts else "All interfaces"

def health_state(last_push):
    state, _age, _missed = node_status_state(last_push)
    if state == "green":
        return "healthy"
    if state == "yellow":
        return "warning"
    return "down"

def health_badge(last_push):
    state = health_state(last_push)
    if state == "healthy":
        return '<span class="health-pill healthy">🟢 Online</span>'
    if state == "warning":
        return '<span class="health-pill warning">🟡 Missed</span>'
    return '<span class="health-pill down">🔴 Down</span>'

def human_age(seconds):
    seconds = max(0, int(seconds or 0))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h {minutes % 60}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"

def missed_cycles(last_push):
    if not last_push:
        return "-"
    age = now_ts() - int(last_push)
    # Agent cadence is 5 minutes. 0 means no missed cycle yet.
    return max(0, int((age - CACHE_BUCKET_SECONDS) // CACHE_BUCKET_SECONDS))

def missed_cycles_for_gap(previous_push, current_push):
    """Count complete scheduled cycles missed between two successful pushes."""
    previous_push = safe_int(previous_push, 0)
    current_push = safe_int(current_push, 0)
    if previous_push <= 0 or current_push <= previous_push:
        return 0
    gap = current_push - previous_push
    return max(0, int((gap - STATUS_PUSH_SECONDS) // STATUS_PUSH_SECONDS))

def record_recovered_miss_event(conn, node, previous_push, current_push, source="live"):
    """Persist one recovered outage, returning its missed-cycle count."""
    cycles = missed_cycles_for_gap(previous_push, current_push)
    if cycles <= 0:
        return 0

    conn.execute("""
        INSERT OR IGNORE INTO node_missed_events(
            node, last_good_push, missed_from, recovered_at,
            missed_cycles, gap_seconds, source, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        node,
        int(previous_push),
        int(previous_push) + STATUS_PUSH_SECONDS,
        int(current_push),
        cycles,
        int(current_push) - int(previous_push),
        (source or "live")[:32],
        now_ts(),
    ))
    return cycles

def ensure_node_missed_history_backfill():
    """One-time backfill from available raw 5-minute snapshots.

    Retention may thin older snapshots to hourly resolution, so only rows still
    marked raw are used. New incidents are persisted directly on every recovery.
    """
    marker_key = "node_missed_events_backfill_v1"
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        marker = conn.execute(
            "SELECT value FROM admin_settings WHERE key=?",
            (marker_key,),
        ).fetchone()
        if marker:
            conn.commit()
            return

        cutoff = now_ts() - RAW_RETENTION_DAYS * 86400
        gaps = conn.execute("""
            WITH ordered AS (
                SELECT
                    node,
                    push_time,
                    LAG(push_time) OVER (
                        PARTITION BY node
                        ORDER BY push_time
                    ) AS previous_push
                FROM node_push_snapshots
                WHERE bucket >= ?
                  AND retention_tier='raw'
            )
            SELECT node, previous_push, push_time
            FROM ordered
            WHERE previous_push IS NOT NULL
              AND push_time - previous_push >= ?
            ORDER BY node, push_time
        """, (cutoff, STATUS_PUSH_SECONDS * 2)).fetchall()

        for node, previous_push, current_push in gaps:
            record_recovered_miss_event(
                conn, node, previous_push, current_push, source="backfill"
            )

        conn.execute("""
            INSERT OR REPLACE INTO admin_settings(key, value, updated_at)
            VALUES (?, ?, ?)
        """, (
            marker_key,
            json.dumps({
                "cutoff": cutoff,
                "events_seen": len(gaps),
            }, separators=(",", ":")),
            now_ts(),
        ))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_node_missed_history(node, limit=500):
    """Return persistent completed events plus the current live gap.

    Historical backfill is intentionally not executed here. Browser requests
    must remain fast; new recovery events are recorded incrementally on /push.
    """
    limit = max(20, min(2000, safe_int(limit, 500)))
    cutoff_24h = now_ts() - 86400
    conn = db()
    try:
        live = conn.execute("""
            SELECT
                COALESCE(ni.last_push, 0),
                COALESCE(ba.primary_ipv4, '')
            FROM node_inventory ni
            LEFT JOIN node_bridge_addresses_latest ba
              ON ba.node=ni.node AND LOWER(ba.role)='public'
            WHERE ni.node=?
        """, (node,)).fetchone()

        last_push = safe_int((live or [0, ""])[0], 0)
        public_ipv4 = str((live or [0, ""])[1] or "")

        events = conn.execute("""
            SELECT
                id, last_good_push, missed_from, recovered_at,
                missed_cycles, gap_seconds, source
            FROM node_missed_events
            WHERE node=? AND recovered_at>=?
            ORDER BY recovered_at DESC, id DESC
            LIMIT ?
        """, (node, cutoff_24h, limit)).fetchall()

        totals = conn.execute("""
            SELECT
                COALESCE(SUM(missed_cycles), 0),
                COUNT(*),
                MAX(recovered_at)
            FROM node_missed_events
            WHERE node=? AND recovered_at>=?
        """, (node, cutoff_24h)).fetchone()
    finally:
        conn.close()

    completed_cycles = safe_int((totals or [0, 0, 0])[0], 0)
    completed_incidents = safe_int((totals or [0, 0, 0])[1], 0)
    last_recovered = safe_int((totals or [0, 0, 0])[2], 0)
    current_cycles = missed_cycles(last_push)
    current_cycles = safe_int(current_cycles, 0) if current_cycles != "-" else 0

    return {
        "node": node,
        "public_ipv4": compact_ipv4(public_ipv4),
        "last_push": last_push,
        "current_cycles": current_cycles,
        "completed_cycles": completed_cycles,
        "total_cycles": completed_cycles + current_cycles,
        "completed_incidents": completed_incidents,
        "total_incidents": completed_incidents + (1 if current_cycles > 0 else 0),
        "last_recovered": last_recovered,
        "events": events,
    }

