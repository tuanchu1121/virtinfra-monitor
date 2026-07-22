import re
#
# - Guest Used is estimated from libvirt balloon stats: available - usable.
# - Host RSS stays visible as a separate host-side metric.
# - Assigned RAM stays visible as the VM allocation.
# - Missing balloon stats are shown as N/A; RSS is never relabelled as guest use.
# - Every VM table that displays RAM can sort Guest %, Guest GiB, Host RSS,
#   and Assigned RAM independently without adding another wide table column.
V48103_VERSION = "48.10.3"
V48103_RAM_SORT_KEYS = {"ram", "ramguest", "ramused", "ramrss", "ramassigned"}

# Add the two balloon fields that the Agent already sends but the bounded current
# cache did not retain in v48.10.2. The wrapper runs once per worker process.
_db_v48103_base = db
_v48103_schema_ready = False

def db():
    global _v48103_schema_ready
    conn = _db_v48103_base()
    if not _v48103_schema_ready:
        for table in ("vm_current_fast", "vm_latest_metrics"):
            for column in ("ram_unused_kib", "ram_usable_kib"):
                try:
                    ensure_column(conn, table, column, "INTEGER NOT NULL DEFAULT 0")
                except dbapi.OperationalError as exc:
                    # Multiple Gunicorn workers can race on first boot. A second
                    # worker may observe the column only after its own PRAGMA.
                    if "duplicate column" not in str(exc).lower():
                        raise
        conn.commit()
        _v48103_schema_ready = True
    return conn

_refresh_fast_current_state_v48103_base = refresh_fast_current_state

def vm_guest_ram_metrics(current_kib=0, rss_kib=0, available_kib=0, unused_kib=0, usable_kib=0):
    """Return conservative guest/host/allocation RAM metrics.

    available - usable is an estimate of memory that the guest cannot readily
    reclaim. A zero value for both usable and unused is treated as missing data,
    not as 100% guest usage, because older/misconfigured balloon drivers report
    absent keys as zero through the current Agent compatibility layer.
    """
    assigned = max(0.0, safe_float(current_kib, 0.0))
    rss = max(0.0, safe_float(rss_kib, 0.0))
    available = max(0.0, safe_float(available_kib, 0.0))
    unused = max(0.0, safe_float(unused_kib, 0.0))
    usable = max(0.0, safe_float(usable_kib, 0.0))
    has_guest = bool(
        available > 0
        and (usable > 0 or unused > 0)
        and usable <= available * 1.05
    )
    guest_total = available if has_guest else 0.0
    guest_used = max(0.0, min(guest_total, guest_total - usable)) if has_guest else 0.0
    guest_pct = (guest_used * 100.0 / guest_total) if guest_total > 0 else 0.0
    return {
        "has_guest": has_guest,
        "guest_total_kib": guest_total,
        "guest_used_kib": guest_used,
        "guest_used_pct": pct_clamp(guest_pct),
        "assigned_kib": assigned,
        "rss_kib": rss,
        "available_kib": available,
        "unused_kib": unused,
        "usable_kib": usable,
    }

def _v48103_ram_level(pct, has_guest=True):
    if not has_guest:
        return "na"
    if pct >= 95:
        return "critical"
    if pct >= 85:
        return "hot"
    if pct >= 70:
        return "warm"
    return "normal"

def fmt_vm_ram_block(current_kib=0, rss_kib=0, available_kib=0, unused_kib=0, usable_kib=0, compact=False):
    """Render VM RAM without turning every list row into a telemetry wall.

    Compact tables show only the operator-facing essentials:
      Guest Used / Assigned, Guest Used %, and Host RSS.
    The VM detail card keeps the explicit Guest/Host/Assigned labels and the
    balloon-stat status. RSS is never substituted for missing guest usage.
    """
    m = vm_guest_ram_metrics(current_kib, rss_kib, available_kib, unused_kib, usable_kib)
    level = _v48103_ram_level(m["guest_used_pct"], m["has_guest"])
    assigned = fmt_kib(m["assigned_kib"]) if m["assigned_kib"] > 0 else "-"
    rss = fmt_kib(m["rss_kib"]) if m["rss_kib"] > 0 else "-"

    if compact:
        display_total_kib = m["assigned_kib"] if m["assigned_kib"] > 0 else m["guest_total_kib"]
        display_total = fmt_kib(display_total_kib) if display_total_kib > 0 else "-"
        if m["has_guest"]:
            used = fmt_kib(m["guest_used_kib"])
            primary = (
                f'<b class="ram-guest-value">{used} / {display_total}</b>'
                f'<small class="ram-guest-label">{m["guest_used_pct"]:.1f}% used</small>'
            )
            meter = f'<span class="ram-meter"><i style="width:{min(100.0,m["guest_used_pct"]):.1f}%"></i></span>'
        else:
            primary = (
                f'<b class="ram-guest-value">N/A / {display_total}</b>'
                '<small class="ram-guest-label">guest stats unavailable</small>'
            )
            meter = '<span class="ram-meter ram-meter-na"><i style="width:0%"></i></span>'
        return (
            f'<div class="vm-ram-block vm-ram-compact ram-{level}">{primary}{meter}'
            f'<small class="ram-host-line">RSS <b>{rss}</b></small></div>'
        )

    if m["has_guest"]:
        used = fmt_kib(m["guest_used_kib"])
        total = fmt_kib(m["guest_total_kib"])
        primary = (
            '<small class="ram-detail-kicker">GUEST USED</small>'
            f'<b class="ram-guest-value">{used} / {total}</b>'
            f'<small class="ram-guest-label">{m["guest_used_pct"]:.1f}% used</small>'
        )
        meter = f'<span class="ram-meter"><i style="width:{min(100.0,m["guest_used_pct"]):.1f}%"></i></span>'
        status = '<small class="ram-stat-status ok">Balloon stats OK</small>'
    else:
        primary = (
            '<small class="ram-detail-kicker">GUEST USED</small>'
            '<b class="ram-guest-value">N/A</b>'
            '<small class="ram-guest-label">guest stats unavailable</small>'
        )
        meter = '<span class="ram-meter ram-meter-na"><i style="width:0%"></i></span>'
        status = '<small class="ram-stat-status na">Host metrics only · balloon usable/unused missing</small>'
    return (
        f'<div class="vm-ram-block vm-ram-detail ram-{level}">{primary}{meter}'
        f'<small class="ram-host-line">HOST RSS <b>{rss}</b> · ASSIGNED <b>{assigned}</b></small>{status}</div>'
    )

def _v48103_ram_sort_value(current_kib, rss_kib, available_kib, unused_kib, usable_kib, key):
    m = vm_guest_ram_metrics(current_kib, rss_kib, available_kib, unused_kib, usable_kib)
    if key in {"ram", "ramguest"}:
        return m["has_guest"], m["guest_used_pct"]
    if key == "ramused":
        return m["has_guest"], m["guest_used_kib"]
    if key == "ramrss":
        return m["rss_kib"] > 0, m["rss_kib"]
    if key == "ramassigned":
        return m["assigned_kib"] > 0, m["assigned_kib"]
    return True, 0.0

def _v48103_sort_ram_rows(rows, sort_by, order, extractor, tie_extractor=None):
    valid, missing = [], []
    for row in rows:
        current, rss, available, unused, usable = extractor(row)
        has_value, value = _v48103_ram_sort_value(current, rss, available, unused, usable, sort_by)
        target = valid if has_value else missing
        target.append((value, row))
    reverse = clean_sort_order(order) == "desc"
    if tie_extractor is None:
        tie_extractor = lambda _row: 0
    valid.sort(key=lambda item: (item[0], tie_extractor(item[1])), reverse=reverse)
    return [row for _value, row in valid] + [row for _value, row in missing]

def _v48103_fetch_ram_map(keys, live=True, bucket=0):
    """Fetch only the VM keys already present in the rendered table, in chunks."""
    result = {}
    pairs = sorted({(str(n), str(v)) for n, v in keys if n and v})
    if not pairs:
        return result
    conn = db()
    try:
        for pos in range(0, len(pairs), 250):
            chunk = pairs[pos:pos + 250]
            where = " OR ".join("(node=? AND vm_uuid=?)" for _ in chunk)
            params = [value for pair in chunk for value in pair]
            if live:
                sql = f"""
                    SELECT node,vm_uuid,ram_current_kib,ram_rss_kib,ram_available_kib,
                           ram_unused_kib,ram_usable_kib
                    FROM vm_current_fast WHERE {where}
                """
                rows = conn.execute(sql, params).fetchall()
            else:
                sql = f"""
                    SELECT p.node,p.vm_uuid,p.ram_current_kib,p.ram_rss_kib,
                           p.ram_available_kib,p.ram_unused_kib,p.ram_usable_kib
                    FROM vm_perf_stats p
                    JOIN (
                        SELECT node,vm_uuid,MAX(time) AS max_time
                        FROM vm_perf_stats
                        WHERE bucket=? AND ({where})
                        GROUP BY node,vm_uuid
                    ) latest
                      ON latest.node=p.node AND latest.vm_uuid=p.vm_uuid AND latest.max_time=p.time
                    WHERE p.bucket=?
                """
                rows = conn.execute(sql, [bucket] + params + [bucket]).fetchall()
            for row in rows:
                result[(str(row[0]), str(row[1]))] = tuple(safe_float(v, 0) for v in row[2:7])
    finally:
        conn.close()
    return result

def _v48103_augment_rows_with_ram(rows, period, selected_bucket, key_indexes):
    live = _request_target_ts() is None and clean_period(period) == "5m"
    keys = [(row[key_indexes[0]], row[key_indexes[1]]) for row in rows]
    ram_map = _v48103_fetch_ram_map(keys, live=live, bucket=selected_bucket)
    augmented = []
    for row in rows:
        key = (str(row[key_indexes[0]]), str(row[key_indexes[1]]))
        current, rss, available, unused, usable = ram_map.get(
            key,
            (
                safe_float(row[key_indexes[3]], 0),
                safe_float(row[key_indexes[2]], 0),
                0.0, 0.0, 0.0,
            ),
        )
        # Existing tuple already contains current/rss. Append only the three
        # fields that were absent from the v48.10.2 table contract.
        augmented.append(tuple(row) + (available, unused, usable))
    return augmented

V48104_VERSION = "48.10.4"
V48104_RAM_SORT_LABELS = {
    "ram": "Guest %",
    "ramguest": "Guest %",
    "ramused": "Used GiB",
    "ramrss": "Host RSS",
    "ramassigned": "Assigned",
}

def _v48104_ram_sort_header(main_link, option_links, current_sort, current_order):
    """Compact RAM header: one primary label plus a collapsed sort menu."""
    active = V48104_RAM_SORT_LABELS.get(current_sort, "Guest %")
    arrow = ""
    if current_sort in V48103_RAM_SORT_KEYS:
        arrow = " ↓" if clean_sort_order(current_order) == "desc" else " ↑"
    options = "".join(f'<div class="ram-sort-option">{link}</div>' for link in option_links)
    return (
        '<div class="ram-compact-head">'
        f'<div class="ram-main-sort">{main_link}</div>'
        '<details class="ram-sort-menu">'
        f'<summary title="Choose RAM sort">{escape(active)}{arrow} ▾</summary>'
        f'<div class="ram-sort-options">{options}</div>'
        '</details></div>'
    )

# ---- Top VM RAM sorting and display ---------------------------------------
_get_top_vm_rows_v48103_base = get_top_vm_rows

def clean_top_sort(sort_by):
    allowed = {
        "total", "rx", "tx", "public", "private", "mbps", "peakmbps",
        "pps", "peakpps", "sample", "drops", "errors", "cpu", "cpufull",
        "vcpu", "ram", "ramguest", "ramused", "ramrss", "ramassigned",
        "diskr", "diskw", "last_push", "node", "vm",
    }
    return sort_by if sort_by in allowed else "total"

def get_top_vm_rows(period, q="", sort_by="total", order="desc", scope="all", limit=100):
    requested_sort = clean_top_sort(sort_by)
    requested_order = clean_sort_order(order)
    requested_limit = max(10, min(1000, safe_int(limit, 100)))
    ram_sort = requested_sort in V48103_RAM_SORT_KEYS
    base_sort = "total" if ram_sort else requested_sort
    fetch_limit = 1000 if ram_sort else requested_limit
    rows, selected_bucket, latest_bucket, _base_limit = _get_top_vm_rows_v48103_base(
        period, q=q, sort_by=base_sort, order=requested_order,
        scope=scope, limit=fetch_limit,
    )
    rows = _v48103_augment_rows_with_ram(rows, period, selected_bucket, (0, 1, 24, 25))
    if ram_sort:
        rows = _v48103_sort_ram_rows(
            rows, requested_sort, requested_order,
            extractor=lambda r: (r[25], r[24], r[32], r[33], r[34]),
            tie_extractor=lambda r: safe_float(r[7], 0),
        )
    return rows[:requested_limit], selected_bucket, latest_bucket, requested_limit

def _v48103_top_ram_link(label, key, period, q, current_sort, current_order, scope, limit):
    return _v48102_top_sort_link(label, key, period, q, current_sort, current_order, scope, limit)

# ---- Per-node VM/interface table RAM sorting and display ------------------
_query_node_bridge_v48103_base = query_node_bridge

def clean_interface_sort(sort_by):
    allowed = {
        "rx", "tx", "total", "mbps", "peakmbps", "pps", "peakpps", "sample",
        "drops", "errors", "cpu", "vcpu", "ram", "ramguest", "ramused",
        "ramrss", "ramassigned", "diskr", "diskw",
    }
    return sort_by if sort_by in allowed else "total"

def query_node_bridge(node, period, bridge, q="", limit=1000, sort_by="total", order="desc", vm_status="active"):
    requested_sort = clean_interface_sort(sort_by)
    requested_order = clean_sort_order(order)
    requested_limit = max(1, min(5000, safe_int(limit, 1000)))
    ram_sort = requested_sort in V48103_RAM_SORT_KEYS
    base_sort = "total" if ram_sort else requested_sort
    fetch_limit = 5000 if ram_sort else requested_limit
    rows, selected_bucket, latest_bucket = _query_node_bridge_v48103_base(
        node, period, bridge, q=q, limit=fetch_limit,
        sort_by=base_sort, order=requested_order, vm_status=vm_status,
    )
    # The node table stores iface in row[0], so fetch RAM with the explicit
    # node argument rather than reusing the Top VM row-key helper.
    live = _request_target_ts() is None and clean_period(period) == "5m"
    ram_map = _v48103_fetch_ram_map([(node, r[1]) for r in rows], live=live, bucket=selected_bucket)
    normalized = []
    for row in rows:
        base = tuple(row[:31])
        current, rss, available, unused, usable = ram_map.get(
            (str(node), str(row[1])),
            (safe_float(row[24],0), safe_float(row[23],0), 0.0, 0.0, 0.0),
        )
        normalized.append(base + (available, unused, usable))
    rows = normalized
    if ram_sort:
        rows = _v48103_sort_ram_rows(
            rows, requested_sort, requested_order,
            extractor=lambda r: (r[24], r[23], r[31], r[32], r[33]),
            tie_extractor=lambda r: safe_float(r[4], 0),
        )
    return rows[:requested_limit], selected_bucket, latest_bucket

# ---- VM charts and VM detail RAM card ------------------------------------
def query_vm_perf_chart(node, vm_uuid, period):
    start, end = range_for_period(period)
    conn = db()
    try:
        raw = conn.execute("""
            SELECT bucket,cpu_percent,vcpu_current,ram_current_kib,ram_maximum_kib,ram_rss_kib,
                   ram_available_kib,ram_unused_kib,ram_usable_kib,
                   disk_read_delta,disk_write_delta,disk_read_reqs_delta,disk_write_reqs_delta,
                   time,COALESCE(interval_seconds,?)
            FROM vm_perf_stats
            WHERE node=? AND vm_uuid=? AND bucket>=? AND bucket<?
            ORDER BY bucket,time
        """, (CACHE_BUCKET_SECONDS,node,vm_uuid,start,end)).fetchall()
    finally:
        conn.close()
    by = {int(r[0]): r for r in raw}
    rows = []
    for bucket in sorted(by):
        r = by[bucket]
        interval = max(1, int(r[14] or CACHE_BUCKET_SECONDS))
        rd, wd = int(r[9] or 0), int(r[10] or 0)
        ram = vm_guest_ram_metrics(r[3], r[5], r[6], r[7], r[8])
        rows.append({
            "bucket": bucket, "label": fmt_chart_label(bucket, interval),
            "cpu_percent": float(r[1] or 0), "vcpu_current": int(r[2] or 0),
            "cpu_core_percent": vm_core_cpu_percent(r[1], r[2]),
            "ram_current_bytes": float(r[3] or 0) * 1024,
            "ram_maximum_bytes": float(r[4] or 0) * 1024,
            "ram_rss_bytes": float(r[5] or 0) * 1024,
            "ram_available_bytes": float(r[6] or 0) * 1024,
            "ram_unused_bytes": float(r[7] or 0) * 1024,
            "ram_usable_bytes": float(r[8] or 0) * 1024,
            "guest_used_bytes": ram["guest_used_kib"] * 1024 if ram["has_guest"] else 0,
            "guest_total_bytes": ram["guest_total_kib"] * 1024 if ram["has_guest"] else 0,
            "guest_used_percent": ram["guest_used_pct"] if ram["has_guest"] else 0,
            "guest_stats_available": 1 if ram["has_guest"] else 0,
            "disk_read_delta": rd, "disk_write_delta": wd,
            "disk_read_bps": rd / interval, "disk_write_bps": wd / interval,
            "disk_read_reqs": int(r[11] or 0), "disk_write_reqs": int(r[12] or 0),
            "last_push": int(r[13] or 0),
        })
    gaps = [rows[i]["bucket"]-rows[i-1]["bucket"] for i in range(1,len(rows)) if rows[i]["bucket"]>rows[i-1]["bucket"]]
    return rows, start, end, (min(gaps) if gaps else chart_step_seconds(period))

_vm_page_v48103_base = app.view_functions.get("vm_page", vm_page)

def vm_page_v48103():
    response = _vm_page_v48103_base()
    if not isinstance(response, Response) or response.status_code >= 400:
        return response
    node = (request.args.get("node") or "").strip()
    vm_uuid = (request.args.get("vm_uuid") or "").strip()
    if not node or not vm_uuid:
        return response
    row = _v48103_latest_ram(node, vm_uuid)
    if not row:
        return response
    block = fmt_vm_ram_block(row[0], row[1], row[2], row[3], row[4], compact=False)
    html = response.get_data(as_text=True)
    replacement = f'<div class="stat vm-ram-detail-stat">VM RAM{block}<small>Updated {fmt_push(row[5])}</small></div>'
    html, count = re.subn(
        r'<div class="stat">RAM<b>.*?</b><small>Available .*?</small></div>',
        replacement, html, count=1, flags=re.S,
    )
    if count:
        response.set_data(html)
    return response

app.view_functions["vm_page"] = vm_page_v48103

# ---- Node aggregate VM RAM card and charts -------------------------------
def query_node_perf_chart(node, period, q=""):
    start, end = range_for_period(period)
    conn = db()
    try:
        bucket_ids = _sample_real_buckets(_node_retained_buckets(conn, node, period))
        if not bucket_ids:
            return [], start, end, chart_step_seconds(period)
        placeholders = _sql_in_placeholders(bucket_ids)
        params = [CACHE_BUCKET_SECONDS,CACHE_BUCKET_SECONDS,node] + bucket_ids
        search_sql = ""
        if q:
            search_sql = " AND (vps.vm_uuid LIKE ? OR vps.node LIKE ?)"
            p = like_pattern(q)
            params.extend([p,p])
        raw = conn.execute(f"""
            SELECT vps.bucket,
                   SUM(CASE WHEN COALESCE(vps.cpu_percent,0)<=100 THEN COALESCE(vps.cpu_percent,0)*MAX(COALESCE(vps.vcpu_current,1),1) ELSE COALESCE(vps.cpu_percent,0) END),
                   MAX(CASE WHEN COALESCE(vps.cpu_percent,0)<=100 THEN COALESCE(vps.cpu_percent,0)*MAX(COALESCE(vps.vcpu_current,1),1) ELSE COALESCE(vps.cpu_percent,0) END),
                   SUM(COALESCE(vps.ram_rss_kib,0)),SUM(COALESCE(vps.ram_current_kib,0)),
                   SUM(CASE WHEN COALESCE(vps.ram_available_kib,0)>0 AND (COALESCE(vps.ram_usable_kib,0)>0 OR COALESCE(vps.ram_unused_kib,0)>0) AND COALESCE(vps.ram_usable_kib,0)<=COALESCE(vps.ram_available_kib,0)*1.05 THEN MAX(COALESCE(vps.ram_available_kib,0)-COALESCE(vps.ram_usable_kib,0),0) ELSE 0 END),
                   SUM(CASE WHEN COALESCE(vps.ram_available_kib,0)>0 AND (COALESCE(vps.ram_usable_kib,0)>0 OR COALESCE(vps.ram_unused_kib,0)>0) AND COALESCE(vps.ram_usable_kib,0)<=COALESCE(vps.ram_available_kib,0)*1.05 THEN COALESCE(vps.ram_available_kib,0) ELSE 0 END),
                   SUM(CASE WHEN COALESCE(vps.ram_available_kib,0)>0 AND (COALESCE(vps.ram_usable_kib,0)>0 OR COALESCE(vps.ram_unused_kib,0)>0) AND COALESCE(vps.ram_usable_kib,0)<=COALESCE(vps.ram_available_kib,0)*1.05 THEN 1 ELSE 0 END),
                   SUM(COALESCE(vps.disk_read_delta,0)*1.0/MAX(COALESCE(vps.interval_seconds,?),1)),
                   SUM(COALESCE(vps.disk_write_delta,0)*1.0/MAX(COALESCE(vps.interval_seconds,?),1)),MAX(vps.time)
            FROM vm_perf_stats vps
            LEFT JOIN vm_inventory vi ON vi.node=vps.node AND vi.vm_uuid=vps.vm_uuid
            WHERE vps.node=? AND vps.bucket IN ({placeholders}) AND COALESCE(vi.status,'active')!='hidden' {search_sql}
            GROUP BY vps.bucket ORDER BY vps.bucket
        """, params).fetchall()
    finally:
        conn.close()
    rows = [{
        "bucket":int(r[0]),"label":fmt_chart_label(r[0],CACHE_BUCKET_SECONDS),
        "total_cpu_percent":float(r[1] or 0),"max_cpu_percent":float(r[2] or 0),
        "ram_rss_bytes":float(r[3] or 0)*1024,"ram_current_bytes":float(r[4] or 0)*1024,
        "guest_used_bytes":float(r[5] or 0)*1024,"guest_total_bytes":float(r[6] or 0)*1024,
        "guest_stats_count":int(r[7] or 0),"disk_read_bps":float(r[8] or 0),
        "disk_write_bps":float(r[9] or 0),"last_push":int(r[10] or 0),
    } for r in raw]
    gaps=[rows[i]["bucket"]-rows[i-1]["bucket"] for i in range(1,len(rows))]
    return rows,start,end,min((g for g in gaps if g>0),default=chart_step_seconds(period))

def get_node_metric_overview(node, period, q="", vm_status="active"):
    status_sql = "AND COALESCE(vi.status, 'active') != 'hidden'"
    conn = db()
    try:
        selected_bucket, _latest_bucket = resolve_snapshot_bucket(conn, period, node=node)
        net_bucket = resolve_table_snapshot_bucket(conn, "node_stats", node, selected_bucket)
        perf_bucket = resolve_table_snapshot_bucket(conn, "vm_perf_stats", node, selected_bucket)
        if not selected_bucket:
            return None
        net_params=[node,net_bucket]; net_search=""
        if q:
            p=like_pattern(q); net_search=" AND (ns.vm_uuid LIKE ? OR ns.iface LIKE ? OR ns.node LIKE ?)"; net_params.extend([p,p,p])
        net = conn.execute(f"""
            SELECT COUNT(DISTINCT ns.vm_uuid),SUM(COALESCE(ns.rx_packets_delta,0)+COALESCE(ns.tx_packets_delta,0)),
                   SUM(COALESCE(ns.rx_drop_delta,0)+COALESCE(ns.tx_drop_delta,0)),SUM(COALESCE(ns.rx_error_delta,0)+COALESCE(ns.tx_error_delta,0)),
                   MAX(COALESCE(ns.interval_seconds,?)),MAX(ns.last_push)
            FROM node_stats ns LEFT JOIN vm_inventory vi ON vi.node=ns.node AND vi.vm_uuid=ns.vm_uuid
            WHERE ns.node=? AND ns.bucket=? {status_sql} {net_search}
        """, [CACHE_BUCKET_SECONDS]+net_params).fetchone() if net_bucket else (0,0,0,0,CACHE_BUCKET_SECONDS,selected_bucket)
        perf_params=[node,perf_bucket]; perf_search=""
        if q:
            p=like_pattern(q); perf_search=" AND (vp.vm_uuid LIKE ? OR vp.node LIKE ?)"; perf_params.extend([p,p])
        perf = conn.execute(f"""
            SELECT COUNT(DISTINCT vp.vm_uuid),
                   SUM(CASE WHEN COALESCE(vp.cpu_percent,0)<=100 THEN COALESCE(vp.cpu_percent,0)*CASE WHEN COALESCE(vp.vcpu_current,0)>0 THEN vp.vcpu_current ELSE 1 END ELSE COALESCE(vp.cpu_percent,0) END),
                   MAX(CASE WHEN COALESCE(vp.cpu_percent,0)<=100 THEN COALESCE(vp.cpu_percent,0)*CASE WHEN COALESCE(vp.vcpu_current,0)>0 THEN vp.vcpu_current ELSE 1 END ELSE COALESCE(vp.cpu_percent,0) END),
                   SUM(CASE WHEN COALESCE(vp.ram_available_kib,0)>0 AND (COALESCE(vp.ram_usable_kib,0)>0 OR COALESCE(vp.ram_unused_kib,0)>0) AND COALESCE(vp.ram_usable_kib,0)<=COALESCE(vp.ram_available_kib,0)*1.05 THEN MAX(COALESCE(vp.ram_available_kib,0)-COALESCE(vp.ram_usable_kib,0),0) ELSE 0 END),
                   SUM(CASE WHEN COALESCE(vp.ram_available_kib,0)>0 AND (COALESCE(vp.ram_usable_kib,0)>0 OR COALESCE(vp.ram_unused_kib,0)>0) AND COALESCE(vp.ram_usable_kib,0)<=COALESCE(vp.ram_available_kib,0)*1.05 THEN COALESCE(vp.ram_available_kib,0) ELSE 0 END),
                   SUM(COALESCE(vp.ram_rss_kib,0)),SUM(COALESCE(vp.ram_current_kib,0)),
                   SUM(CASE WHEN COALESCE(vp.ram_available_kib,0)>0 AND (COALESCE(vp.ram_usable_kib,0)>0 OR COALESCE(vp.ram_unused_kib,0)>0) AND COALESCE(vp.ram_usable_kib,0)<=COALESCE(vp.ram_available_kib,0)*1.05 THEN 1 ELSE 0 END),
                   SUM(COALESCE(vp.disk_read_delta,0)*1.0/MAX(COALESCE(vp.interval_seconds,?),1)),
                   SUM(COALESCE(vp.disk_write_delta,0)*1.0/MAX(COALESCE(vp.interval_seconds,?),1)),MAX(vp.time)
            FROM vm_perf_stats vp LEFT JOIN vm_inventory vi ON vi.node=vp.node AND vi.vm_uuid=vp.vm_uuid
            WHERE vp.node=? AND vp.bucket=? {status_sql} {perf_search}
        """, [CACHE_BUCKET_SECONDS,CACHE_BUCKET_SECONDS]+perf_params).fetchone() if perf_bucket else (0,0,0,0,0,0,0,0,0,0,selected_bucket)
        net_vm,packets,drops,errors,interval_seconds,net_last=net
        perf_vm,total_cpu,max_cpu,guest_used,guest_total,ram_rss,ram_current,guest_count,disk_read,disk_write,perf_last=perf
        interval=max(1,int(interval_seconds or CACHE_BUCKET_SECONDS))
        return (max(int(net_vm or 0),int(perf_vm or 0)),float(packets or 0)/interval,int(drops or 0),int(errors or 0),float(total_cpu or 0),float(max_cpu or 0),int(guest_used or 0),int(guest_total or 0),int(ram_rss or 0),int(ram_current or 0),int(guest_count or 0),float(disk_read or 0),float(disk_write or 0),max(int(net_last or 0),int(perf_last or 0),int(selected_bucket or 0)))
    finally:
        conn.close()

def node_metric_cards(row):
    if not row:
        row=(0,0,0,0,0,0,0,0,0,0,0,0,0,0)
    (vm_count,total_pps,drops,errors,total_cpu,max_cpu,guest_used,guest_total,ram_rss,ram_current,guest_count,disk_read,disk_write,last_seen)=row
    guest_pct=(float(guest_used)*100.0/float(guest_total)) if guest_total else 0.0
    guest_text=f"{fmt_kib(guest_used)} / {fmt_kib(guest_total)} · {guest_pct:.1f}%" if guest_total else "N/A"
    return f"""
    <div class="card overview-card"><div class="overview-head"><h3>Node VM Metrics</h3><div class="overview-meta"><span>Source <b>exact VM snapshot</b></span><span>Last Metric <b>{fmt_push(last_seen)}</b></span><span>VM <b>{int(vm_count or 0)}</b></span></div></div><div class="grid">
      <div class="stat">PPS<b>{fmt_pps_value(total_pps)}</b></div><div class="stat">CPU TOTAL / MAX VM<b>{fmt_percent(total_cpu)} / {fmt_percent(max_cpu)}</b><small>100% = 1 full core</small></div>
      <div class="stat">VM GUEST USED<b>{guest_text}</b><small>Balloon coverage {int(guest_count or 0)}/{int(vm_count or 0)} VM</small></div><div class="stat">VM HOST RSS / ASSIGNED<b>{fmt_ram_pair(ram_rss,ram_current)}</b><small>Host-side RSS is not guest application usage</small></div>
      <div class="stat">Disk Read<b>{human_rate(disk_read)}</b></div><div class="stat">Disk Write<b>{human_rate(disk_write)}</b></div><div class="stat">Drops / ERR<b>{int(drops or 0)} / {int(errors or 0)}</b></div>
    </div><div class="table-hint">Guest Used sums only VMs with valid balloon available/usable data. RSS and Assigned remain separate capacity metrics.</div></div>"""

# ---- Current Abuse table: RAM is informational and sortable only ----------
def _v48103_current_abuse_query(q, sort_by, order, limit):
    ram_guest_expr = "CASE WHEN COALESCE(c.ram_available_kib,0)>0 AND (COALESCE(c.ram_usable_kib,0)>0 OR COALESCE(c.ram_unused_kib,0)>0) AND COALESCE(c.ram_usable_kib,0)<=COALESCE(c.ram_available_kib,0)*1.05 THEN (COALESCE(c.ram_available_kib,0)-COALESCE(c.ram_usable_kib,0))*100.0/COALESCE(c.ram_available_kib,1) ELSE -1 END"
    ram_used_expr = "CASE WHEN COALESCE(c.ram_available_kib,0)>0 AND (COALESCE(c.ram_usable_kib,0)>0 OR COALESCE(c.ram_unused_kib,0)>0) AND COALESCE(c.ram_usable_kib,0)<=COALESCE(c.ram_available_kib,0)*1.05 THEN COALESCE(c.ram_available_kib,0)-COALESCE(c.ram_usable_kib,0) ELSE -1 END"
    allowed={
        "severity":"a.severity","node":"a.node COLLATE NOCASE","vm":"a.vm_uuid COLLATE NOCASE",
        "rx_mbps":"a.rx_mbps","tx_mbps":"a.tx_mbps","rx_pps":"a.rx_pps","tx_pps":"a.tx_pps",
        "rx_peak":"a.rx_peak_pps","tx_peak":"a.tx_peak_pps","cpu":"a.cpu_full_percent","vcpu":"a.vcpu_current",
        "diskr":"a.disk_read_bps","diskw":"a.disk_write_bps","iops":"(a.disk_read_iops+a.disk_write_iops)",
        "last_seen":"a.last_seen","since":"a.abuse_since","ram":ram_guest_expr,"ramguest":ram_guest_expr,
        "ramused":ram_used_expr,"ramrss":"COALESCE(c.ram_rss_kib,0)","ramassigned":"COALESCE(c.ram_current_kib,0)",
    }
    sort_by=sort_by if sort_by in allowed else "severity"; order=clean_sort_order(order); cfg=get_abuse_settings()
    ram_valid_expr = "CASE WHEN COALESCE(c.ram_available_kib,0)>0 AND (COALESCE(c.ram_usable_kib,0)>0 OR COALESCE(c.ram_unused_kib,0)>0) AND COALESCE(c.ram_usable_kib,0)<=COALESCE(c.ram_available_kib,0)*1.05 THEN 1 ELSE 0 END"
    validity_order = ""
    if sort_by in {"ram", "ramguest", "ramused"}:
        validity_order = ram_valid_expr + " DESC,"
    elif sort_by == "ramrss":
        validity_order = "CASE WHEN COALESCE(c.ram_rss_kib,0)>0 THEN 1 ELSE 0 END DESC,"
    elif sort_by == "ramassigned":
        validity_order = "CASE WHEN COALESCE(c.ram_current_kib,0)>0 THEN 1 ELSE 0 END DESC,"
    params=[now_ts()-FAST_CURRENT_STALE_SECONDS,cfg["revision"],ABUSE_ENGINE_VERSION]; search_sql=""
    if q:
        p=like_pattern(q); search_sql=""" AND (a.node LIKE ? OR a.vm_uuid LIKE ? OR EXISTS(SELECT 1 FROM node_bridge_addresses_latest b WHERE b.node=a.node AND (COALESCE(b.primary_ipv4,'') LIKE ? OR COALESCE(b.ipv4_json,'') LIKE ?)))"""; params.extend([p,p,p,p])
    conn=db()
    try:
        base_where="a.is_abuse=1 AND a.last_seen>=? AND a.policy_revision=? AND a.engine_version=?"
        total=safe_int(conn.execute(f"SELECT COUNT(*) FROM vm_abuse_state a WHERE {base_where} {search_sql}",params).fetchone()[0],0)
        counts=conn.execute(f"""SELECT SUM(CASE WHEN a.abuse_flags LIKE '%PPS%' THEN 1 ELSE 0 END),SUM(CASE WHEN a.abuse_flags LIKE '%AVG_MBPS%' THEN 1 ELSE 0 END),SUM(CASE WHEN a.abuse_flags LIKE '%CPU%' THEN 1 ELSE 0 END),SUM(CASE WHEN a.abuse_flags LIKE '%DISK%' THEN 1 ELSE 0 END) FROM vm_abuse_state a WHERE {base_where} {search_sql}""",params).fetchone()
        rows=conn.execute(f"""
          SELECT a.node,a.vm_uuid,a.last_seen,a.abuse_since,a.abuse_flags,a.severity,a.rx_pps,a.tx_pps,a.rx_peak_pps,a.tx_peak_pps,a.seconds_over_rx_pps,a.seconds_over_tx_pps,a.cpu_full_percent,a.cpu_core_percent,a.vcpu_current,a.cpu_streak_seconds,a.disk_read_bps,a.disk_write_bps,a.disk_read_iops,a.disk_write_iops,a.disk_streak_seconds,
                 COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest b WHERE b.node=a.node AND LOWER(role)='public' LIMIT 1),''),COALESCE(a.rx_mbps,0),COALESCE(a.tx_mbps,0),COALESCE(a.network_rx_mbps_streak_seconds,0),COALESCE(a.network_tx_mbps_streak_seconds,0),COALESCE(a.cpu_streak_cycles,0),COALESCE(a.disk_streak_cycles,0),COALESCE(a.network_rx_mbps_streak_cycles,0),COALESCE(a.network_tx_mbps_streak_cycles,0),COALESCE(a.network_pps_policy_synced,0),COALESCE(a.network_pps_reported_threshold,0),COALESCE(a.policy_revision,0),
                 COALESCE(c.ram_current_kib,0),COALESCE(c.ram_rss_kib,0),COALESCE(c.ram_available_kib,0),COALESCE(c.ram_unused_kib,0),COALESCE(c.ram_usable_kib,0)
          FROM vm_abuse_state a LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid LEFT JOIN vm_current_fast c ON c.node=a.node AND c.vm_uuid=a.vm_uuid
          WHERE {base_where} AND COALESCE(vi.status,'active')!='hidden' {search_sql}
          ORDER BY {validity_order} {allowed[sort_by]} {order.upper()},a.last_seen DESC,a.node COLLATE NOCASE,a.vm_uuid COLLATE NOCASE LIMIT ?
        """,params+[limit]).fetchall()
        return rows,total,tuple(safe_int(x,0) for x in (counts or (0,0,0,0))),sort_by,order,cfg
    finally:
        conn.close()

def vm_abuse_page_v48103():
    tab=(request.args.get("tab") or "current").strip().lower()
    if tab=="history": return vm_abuse_page_v483()
    q=(request.args.get("q") or "").strip(); sort_by=(request.args.get("sort") or "severity").strip().lower(); order=clean_sort_order(request.args.get("order","desc")); limit=max(10,min(1000,safe_int(request.args.get("limit"),200)))
    return page("VM Abuse",_v48103_current_abuse_page(q,sort_by,order,limit))

app.view_functions["vm_abuse_page"] = vm_abuse_page_v48103

V48103_UI_CSS = r"""
<style id="v48103-guest-ram-ui">
.ram-dual-head>div{font-size:11px;font-weight:900;margin-bottom:4px}.ram-dual-head small{display:flex!important;justify-content:center;gap:3px;align-items:center;white-space:nowrap}.ram-dual-head .sort-link,.ram-dual-head .cpu-sort-link{font-size:9px!important;letter-spacing:0;text-transform:none;padding:2px 3px;border-radius:4px}.vm-ram-block{min-width:150px;line-height:1.25}.ram-guest-value{display:block;font-size:13px;color:#101828}.ram-guest-label{display:block!important;margin-top:3px!important;font-size:9.5px!important;font-weight:900!important;letter-spacing:.035em;color:#344054!important}.ram-host-line{display:block!important;margin-top:5px!important;font-size:9.5px!important;color:#667085!important;white-space:nowrap}.ram-host-line b{font-size:9.5px!important;color:inherit}.ram-meter{display:block;height:4px;margin-top:5px;border-radius:999px;background:#e4e7ec;overflow:hidden}.ram-meter i{display:block;height:100%;border-radius:inherit;background:#12b76a}.ram-warm .ram-guest-value,.ram-warm .ram-guest-label{color:#b54708!important}.ram-warm .ram-meter i{background:#f79009}.ram-hot .ram-guest-value,.ram-hot .ram-guest-label{color:#b54708!important}.ram-hot .ram-meter i{background:#f79009}.ram-critical .ram-guest-value,.ram-critical .ram-guest-label{color:#b42318!important}.ram-critical .ram-meter i{background:#f04438}.ram-na .ram-guest-value,.ram-na .ram-guest-label{color:#667085!important}.ram-meter-na i{display:none}.ram-stat-status{display:block!important;margin-top:4px!important;font-size:9px!important}.ram-stat-status.ok{color:#027a48!important}.ram-stat-status.na{color:#667085!important}.vm-ram-detail-stat .vm-ram-block{margin-top:8px}.vm-ram-detail-stat>.vm-ram-block>.ram-guest-value{font-size:17px}.vm-ram-detail-stat>.vm-ram-block>.ram-host-line{font-size:10px!important}.top-vm-v48103 .top-ram{width:180px!important}.table-vm .col-ram{width:180px!important}.abuse-v48103-table{min-width:1740px!important}.abuse-v48103-table .c-ram{width:190px}.abuse-v48103-table .ram-host-line{white-space:normal}.abuse-v48103-table .vm-ram-block{min-width:165px}
html[data-theme=dark] .ram-guest-value{color:#f8fafc}html[data-theme=dark] .ram-guest-label{color:#cbd5e1!important}html[data-theme=dark] .ram-meter{background:#26374f}html[data-theme=dark] .ram-host-line{color:#94a3b8!important}
</style>
"""
_page_v48103_base = page

def page(title, content):
    response = _page_v48103_base(title, content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace("</head>", V48103_UI_CSS + "</head>", 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.10.3 guest RAM UI layer")
    return response

