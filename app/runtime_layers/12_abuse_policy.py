
ABUSE_SETTING_DEFAULTS = {
    "abuse_network_enabled": "1",
    "abuse_network_pps": "200000",
    "abuse_network_required_seconds": "270",
    "abuse_cpu_enabled": "1",
    "abuse_cpu_full_percent": "90",
    "abuse_cpu_required_seconds": "1800",
    "abuse_disk_enabled": "1",
    "abuse_disk_bps": str(200 * 1024 * 1024),
    "abuse_disk_iops": "5000",
    "abuse_disk_required_seconds": "900",
}

def _setting_bool(value, default=True):
    if value is None:
        return bool(default)
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}

@app.before_request
def _v480_refresh_abuse_runtime_settings():
    # Tiny primary-key reads only. This makes an Admin save visible immediately in
    # every Gunicorn worker without requiring a service restart.
    try:
        _apply_abuse_settings_to_runtime(get_abuse_settings())
    except Exception:
        app.logger.exception("Could not refresh abuse settings")

_refresh_fast_current_state_v470 = refresh_fast_current_state

_run_retention_v470 = run_retention

def run_retention(dry_run=False):
    stats = _run_retention_v470(dry_run=dry_run)
    cutoff = now_ts() - EVENT_RETENTION_DAYS * 86400
    conn = db()
    try:
        if dry_run:
            count = conn.execute("SELECT COUNT(*) FROM vm_abuse_events WHERE event_time<?", (cutoff,)).fetchone()[0]
            stats.setdefault("deleted", {})["vm_abuse_events"] = int(count or 0)
        else:
            deleted = _delete_in_batches(conn, "vm_abuse_events", "event_time<?", (cutoff,))
            stats.setdefault("deleted", {})["vm_abuse_events"] = int(deleted or 0)
            conn.commit()
        return stats
    finally:
        conn.close()

def dashboard_custom_time_card(target_ts, q="", sort_by="node", sort_order="asc"):
    target_value = _datetime_local_value(target_ts)
    return f"""
    <div class="card custom-time-card">
      <div class="table-title-row"><h3>Custom Snapshot Time</h3><div class="count-badges"><span>Retention <b>{HOURLY_RETENTION_DAYS} days</b></span><span>Mode <b>nearest real push</b></span></div></div>
      <form class="custom-time-form" method="get" action="{url_for('index')}">
        <input type="hidden" name="q" value="{escape(q, quote=True)}">
        <input type="hidden" name="sort" value="{escape(sort_by, quote=True)}">
        <input type="hidden" name="order" value="{escape(sort_order, quote=True)}">
        <label>Snapshot date and time
          <input type="datetime-local" name="at" value="{escape(target_value, quote=True)}" required>
        </label>
        <button type="submit">Open snapshot</button>
        {f'<a class="clear" href="{url_for("index", q=q, sort=sort_by, order=sort_order)}">Use live</a>' if target_ts else ''}
      </form>
      <div class="table-hint">This dashboard is a snapshot view, not a sum across a range. The monitor selects the nearest retained real agent push at or before the time entered, so CPU, RAM, PPS and disk remain coherent.</div>
    </div>
    """

def index_v480():
    period = clean_period(request.args.get("period", "5m"))
    q = (request.args.get("q") or "").strip()
    sort_by = clean_node_sort(request.args.get("sort", "node"))
    sort_order = clean_sort_order(request.args.get("order", "asc"))
    target_ts = _parse_datetime_local(request.args.get("at"))

    direct_vm = resolve_direct_vm_search(q)
    if direct_vm:
        return redirect(url_for(
            "vm_page", node=direct_vm["node"], vm_uuid=direct_vm["vm_uuid"],
            bridge=direct_vm["bridge"], iface=direct_vm["iface"], period=period,
        ))

    rows, start, end = get_node_rows(period, q, sort_by=sort_by, order=sort_order, target_ts=target_ts)
    content = f"""
    {range_card(period, start, end, q=q, endpoint="index")}
    {dashboard_custom_time_card(target_ts, q=q, sort_by=sort_by, sort_order=sort_order)}
    {node_table(rows, sort_by=sort_by, order=sort_order)}
    """
    return page("VirtInfra Monitor", content)

app.view_functions["index"] = index_v480

def _abuse_type_label(event_type):
    return {"started":"ABUSE STARTED", "updated":"RULE CHANGED", "recovered":"RECOVERED"}.get(str(event_type), str(event_type).upper())

def _abuse_type_class(event_type):
    return "crit" if event_type == "started" else ("warn" if event_type == "updated" else "ok")

def _abuse_sort_link(label, key, tab, q, current_sort, current_order, limit):
    next_order = reverse_order(current_order) if current_sort == key else "desc"
    arrow = ""
    if current_sort == key:
        arrow = " ↓" if current_order == "desc" else " ↑"
    href = url_for("vm_abuse_page", tab=tab, q=q or None, sort=key, order=next_order, limit=limit)
    return f'<a class="sort-link" href="{escape(href, quote=True)}">{escape(label)}{arrow}</a>'

def _current_abuse_query(q, sort_by, order, limit):
    allowed = {
        "severity":"a.severity", "node":"a.node COLLATE NOCASE", "vm":"a.vm_uuid COLLATE NOCASE",
        "rx_pps":"a.rx_pps", "tx_pps":"a.tx_pps", "rx_peak":"a.rx_peak_pps", "tx_peak":"a.tx_peak_pps",
        "cpu":"a.cpu_full_percent", "vcpu":"a.vcpu_current", "diskr":"a.disk_read_bps",
        "diskw":"a.disk_write_bps", "iops":"(a.disk_read_iops+a.disk_write_iops)",
        "last_seen":"a.last_seen", "since":"a.abuse_since",
    }
    sort_by = sort_by if sort_by in allowed else "severity"
    order = clean_sort_order(order)
    params = [now_ts() - FAST_CURRENT_STALE_SECONDS]
    search_sql = ""
    if q:
        p = like_pattern(q)
        search_sql = """ AND (a.node LIKE ? OR a.vm_uuid LIKE ? OR EXISTS(
          SELECT 1 FROM node_bridge_addresses_latest b WHERE b.node=a.node
          AND (COALESCE(b.primary_ipv4,'') LIKE ? OR COALESCE(b.ipv4_json,'') LIKE ?)))"""
        params.extend([p,p,p,p])
    conn = db()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM vm_abuse_state a WHERE a.is_abuse=1 AND a.last_seen>=? {search_sql}", params).fetchone()[0]
        counts = conn.execute(f"""
          SELECT SUM(CASE WHEN a.network_rx_hit=1 OR a.network_tx_hit=1 THEN 1 ELSE 0 END),
                 SUM(CASE WHEN a.abuse_flags LIKE '%CPU_30M%' THEN 1 ELSE 0 END),
                 SUM(CASE WHEN a.abuse_flags LIKE '%DISK_15M%' THEN 1 ELSE 0 END)
          FROM vm_abuse_state a WHERE a.is_abuse=1 AND a.last_seen>=? {search_sql}
        """, params).fetchone()
        rows = conn.execute(f"""
          SELECT a.node,a.vm_uuid,a.last_seen,a.abuse_since,a.abuse_flags,a.severity,
                 a.rx_pps,a.tx_pps,a.rx_peak_pps,a.tx_peak_pps,
                 a.seconds_over_rx_pps,a.seconds_over_tx_pps,
                 a.cpu_full_percent,a.cpu_core_percent,a.vcpu_current,a.cpu_streak_seconds,
                 a.disk_read_bps,a.disk_write_bps,a.disk_read_iops,a.disk_write_iops,a.disk_streak_seconds,
                 COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest b WHERE b.node=a.node AND LOWER(role)='public' LIMIT 1),'')
          FROM vm_abuse_state a
          LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
          WHERE a.is_abuse=1 AND a.last_seen>=? AND COALESCE(vi.status,'active')!='hidden' {search_sql}
          ORDER BY {allowed[sort_by]} {order.upper()},a.last_seen DESC,a.node COLLATE NOCASE,a.vm_uuid COLLATE NOCASE
          LIMIT ?
        """, params + [limit]).fetchall()
        return rows, int(total or 0), tuple(int(x or 0) for x in (counts or (0,0,0))), sort_by, order
    finally:
        conn.close()

def _history_abuse_query(q, sort_by, order, limit):
    allowed = {
        "time":"e.event_time", "type":"e.event_type COLLATE NOCASE", "node":"e.node COLLATE NOCASE",
        "vm":"e.vm_uuid COLLATE NOCASE", "severity":"e.severity", "rx_pps":"e.rx_pps",
        "tx_pps":"e.tx_pps", "cpu":"e.cpu_full_percent", "disk":"(e.disk_read_bps+e.disk_write_bps)",
    }
    sort_by = sort_by if sort_by in allowed else "time"
    order = clean_sort_order(order)
    where = "WHERE 1=1"
    params = []
    if q:
        p = like_pattern(q)
        where += " AND (e.node LIKE ? OR e.vm_uuid LIKE ? OR e.abuse_flags LIKE ? OR e.event_type LIKE ?)"
        params.extend([p,p,p,p])
    conn = db()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM vm_abuse_events e {where}", params).fetchone()[0]
        rows = conn.execute(f"""
          SELECT e.id,e.event_time,e.event_type,e.node,e.vm_uuid,e.abuse_flags,e.severity,
                 e.rx_pps,e.tx_pps,e.rx_peak_pps,e.tx_peak_pps,e.seconds_over_rx_pps,e.seconds_over_tx_pps,
                 e.cpu_full_percent,e.cpu_core_percent,e.vcpu_current,e.cpu_streak_seconds,
                 e.disk_read_bps,e.disk_write_bps,e.disk_read_iops,e.disk_write_iops,e.disk_streak_seconds,
                 e.thresholds_json,e.detail,
                 COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest b WHERE b.node=e.node AND LOWER(role)='public' LIMIT 1),'')
          FROM vm_abuse_events e {where}
          ORDER BY {allowed[sort_by]} {order.upper()},e.id DESC LIMIT ?
        """, params + [limit]).fetchall()
        return rows, int(total or 0), sort_by, order
    finally:
        conn.close()

def _abuse_page_style():
    return """
    <style>
      .abuse-tabs{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.abuse-tabs a{padding:8px 13px;border:1px solid #d1d5db;border-radius:8px;background:#fff;color:#374151;font-weight:800;text-decoration:none}.abuse-tabs a.active{background:#111827;color:#fff;border-color:#111827}
      .abuse-policy{display:grid;grid-template-columns:repeat(3,minmax(220px,1fr));gap:10px;margin-top:12px}.abuse-policy>div{border:1px solid #e5e7eb;border-radius:9px;padding:11px;background:#f9fafb}.abuse-policy small{display:block;color:#6b7280;margin-top:4px}
      .abuse-fast-table{min-width:1960px;table-layout:fixed}.abuse-history-table{min-width:1880px;table-layout:fixed}.abuse-fast-table th,.abuse-fast-table td,.abuse-history-table th,.abuse-history-table td{vertical-align:middle}.abuse-fast-table td.num,.abuse-history-table td.num{text-align:right;font-variant-numeric:tabular-nums}.abuse-fast-table .uuid-col,.abuse-history-table .uuid-col{width:330px}.abuse-fast-table .node-col,.abuse-history-table .node-col{width:170px}.abuse-fast-table .reason-col,.abuse-history-table .reason-col{width:260px}.abuse-fast-table .time-col,.abuse-history-table .time-col{width:145px}.abuse-fast-table .rate-col,.abuse-history-table .rate-col{width:105px}.abuse-fast-table .small-col,.abuse-history-table .small-col{width:85px}
      .abuse-table-tools{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:10px}.event-badge{display:inline-block;padding:4px 8px;border-radius:999px;font-size:11px;font-weight:900}.event-badge.crit{background:#fee2e2;color:#991b1b}.event-badge.warn{background:#ffedd5;color:#9a3412}.event-badge.ok{background:#dcfce7;color:#166534}.clear-event-form{display:inline}.clear-event-form button{padding:5px 8px;font-size:11px}.custom-time-form{display:flex;gap:10px;align-items:end;flex-wrap:wrap}.custom-time-form label{display:grid;gap:5px;color:#6b7280;font-size:12px;font-weight:800}.custom-time-form input{min-width:220px}.custom-time-form button{height:40px}.abuse-settings-grid{display:grid;grid-template-columns:repeat(3,minmax(240px,1fr));gap:12px}.abuse-setting-box{border:1px solid #d1d5db;border-radius:10px;padding:13px;background:#f9fafb}.abuse-setting-box h4{margin:0 0 10px}.abuse-setting-box label{display:grid;gap:5px;margin-top:9px;font-size:12px;font-weight:800;color:#4b5563}.abuse-setting-box .enable-line{display:flex;grid-template-columns:none;align-items:center;gap:8px}.abuse-setting-box input[type=checkbox]{width:auto;min-width:0}.abuse-setting-box input[type=number]{width:100%}
      html[data-theme=dark] .abuse-tabs a{background:#1f2937;border-color:#475569;color:#e5e7eb}html[data-theme=dark] .abuse-tabs a.active{background:#2563eb;border-color:#3b82f6;color:#fff}html[data-theme=dark] .abuse-policy>div,html[data-theme=dark] .abuse-setting-box{background:#172033;border-color:#334155}
      @media(max-width:950px){.abuse-policy,.abuse-settings-grid{grid-template-columns:1fr}.custom-time-form{align-items:stretch}.custom-time-form input{width:100%}}
    </style>
    """

def vm_abuse_page_v480():
    tab = (request.args.get("tab") or "current").strip().lower()
    if tab not in {"current","history"}:
        tab = "current"
    q = (request.args.get("q") or "").strip()
    limit = max(10, min(1000, safe_int(request.args.get("limit"), 200)))
    cfg = get_abuse_settings()
    default_sort = "severity" if tab == "current" else "time"
    sort_by = (request.args.get("sort") or default_sort).strip()
    order = clean_sort_order(request.args.get("order", "desc"))
    current_href = url_for("vm_abuse_page", tab="current", q=q or None, limit=limit)
    history_href = url_for("vm_abuse_page", tab="history", q=q or None, limit=limit)
    policy = f"""
      <div class="abuse-policy">
        <div><b>Network {'ON' if cfg['network_enabled'] else 'OFF'}</b><small>RX or TX ≥ {cfg['network_pps']:,.0f} PPS for {cfg['network_required_seconds']}s. Agent v10 syncs this threshold automatically after a push.</small></div>
        <div><b>CPU {'ON' if cfg['cpu_enabled'] else 'OFF'}</b><small>CPU Full ≥ {cfg['cpu_full_percent']:.1f}% for {cfg['cpu_required_seconds']//60} minutes.</small></div>
        <div><b>Disk {'ON' if cfg['disk_enabled'] else 'OFF'}</b><small>Total ≥ {human_rate(cfg['disk_bps'])} or {cfg['disk_iops']:,.0f} IOPS for {cfg['disk_required_seconds']//60} minutes.</small></div>
      </div>
    """
    search = f"""
      <form class="search" method="get" action="{url_for('vm_abuse_page')}">
        <input type="hidden" name="tab" value="{tab}"><input type="hidden" name="sort" value="{escape(sort_by,quote=True)}"><input type="hidden" name="order" value="{escape(order,quote=True)}">
        <input name="q" value="{escape(q,quote=True)}" placeholder="Search node / IPv4 / VM UUID / reason">
        <input name="limit" type="number" min="10" max="1000" value="{limit}" style="max-width:105px;min-width:90px"><button type="submit">Search</button>
        {f'<a class="clear" href="{url_for("vm_abuse_page",tab=tab,limit=limit)}">Clear search</a>' if q else ''}
      </form>
    """
    tabs = f'<div class="abuse-tabs"><a class="{"active" if tab=="current" else ""}" href="{escape(current_href,quote=True)}">Current Abuse</a><a class="{"active" if tab=="history" else ""}" href="{escape(history_href,quote=True)}">Abuse History / Logs</a></div>'

    if tab == "current":
        rows,total,counts,sort_by,order = _current_abuse_query(q,sort_by,order,limit)
        body=""
        for rank,r in enumerate(rows,1):
            flags={x for x in str(r[4] or "").split(",") if x}
            labels=_abuse_flag_labels(r[4],cfg)
            reasons="".join(metric_pill(escape(x),"crit") for x in labels)
            href=url_for("vm_page",node=r[0],vm_uuid=r[1],period="1h")
            ip=compact_ipv4(r[21])
            body += f"""
            <tr><td class="num">{rank}</td><td><div class="node-name-cell"><a href="{escape(href,quote=True)}"><b>{escape(r[0])}</b></a>{f'<small class="node-ipv4">{escape(ip)}</small>' if ip else ''}</div></td>
            <td class="mono uuid-col"><span class="uuid-cell"><a href="{escape(href,quote=True)}">{escape(r[1])}</a><button type="button" class="copy-btn" data-copy="{escape(r[1],quote=True)}">⧉</button></span></td>
            <td><div class="abuse-reasons">{reasons}</div></td><td class="num"><b>{safe_float(r[5],0):.2f}x</b></td>
            <td class="num">{fmt_pps_value(r[6])}<small class="metric-subline">{safe_int(r[10],0)}s high</small></td><td class="num">{fmt_pps_value(r[7])}<small class="metric-subline">{safe_int(r[11],0)}s high</small></td>
            <td class="num">{fmt_pps_value(r[8])}</td><td class="num">{fmt_pps_value(r[9])}</td><td class="num"><b>{safe_float(r[12],0):.1f}%</b><small class="metric-subline">{safe_int(r[15],0)//60}m</small></td>
            <td class="num">{safe_int(r[14],0)}</td><td class="num">{human_rate(r[16])}</td><td class="num">{human_rate(r[17])}</td><td class="num">{safe_float(r[18],0)+safe_float(r[19],0):.1f}</td>
            <td class="num">{fmt_push(r[2])}</td><td class="num">{fmt_full(r[3]) if r[3] else '-'}</td></tr>"""
        if not body: body='<tr><td colspan="16" class="empty">No VM currently satisfies a sustained abuse rule</td></tr>'
        h=lambda label,key:_abuse_sort_link(label,key,"current",q,sort_by,order,limit)
        table=f"""
        <div class="card vm-table-card"><div class="abuse-table-tools"><div><h3 style="margin:0">Current VM Abuse</h3><div class="table-hint">{total} matching VM. Current state is fast and reads only vm_abuse_state.</div></div><div class="count-badges"><span>Network <b>{counts[0]}</b></span><span>CPU <b>{counts[1]}</b></span><span>Disk <b>{counts[2]}</b></span></div></div>
        <div class="table-wrap"><table class="abuse-fast-table"><colgroup><col style="width:48px"><col class="node-col"><col class="uuid-col"><col class="reason-col"><col class="small-col"><col class="rate-col"><col class="rate-col"><col class="rate-col"><col class="rate-col"><col class="rate-col"><col class="small-col"><col class="rate-col"><col class="rate-col"><col class="rate-col"><col class="time-col"><col class="time-col"></colgroup><thead><tr>
        <th>#</th><th>{h('NODE','node')}</th><th>{h('VM UUID','vm')}</th><th>REASON</th><th>{h('SEVERITY','severity')}</th><th>{h('RX PPS','rx_pps')}</th><th>{h('TX PPS','tx_pps')}</th><th>{h('RX PEAK','rx_peak')}</th><th>{h('TX PEAK','tx_peak')}</th><th>{h('CPU FULL%','cpu')}</th><th>{h('vCPU','vcpu')}</th><th>{h('DISK R/s','diskr')}</th><th>{h('DISK W/s','diskw')}</th><th>{h('IOPS','iops')}</th><th>{h('LAST PUSH','last_seen')}</th><th>{h('ABUSE SINCE','since')}</th></tr></thead><tbody>{body}</tbody></table></div></div>"""
    else:
        rows,total,sort_by,order = _history_abuse_query(q,sort_by,order,limit)
        body=""
        for r in rows:
            try: event_cfg=json.loads(r[22] or "{}")
            except Exception: event_cfg={}
            merged_cfg=dict(cfg); merged_cfg.update({k:v for k,v in event_cfg.items() if k in merged_cfg})
            labels=_abuse_flag_labels(r[5],merged_cfg)
            reasons="".join(metric_pill(escape(x),"crit" if r[2] != "recovered" else "ok") for x in labels)
            href=url_for("vm_page",node=r[3],vm_uuid=r[4],period="1h")
            ip=compact_ipv4(r[24])
            body += f"""
            <tr><td><input form="abuse-clear-selected" type="checkbox" name="event_ids" value="{safe_int(r[0],0)}"></td><td class="num">{safe_int(r[0],0)}</td><td>{fmt_full(r[1])}</td><td><span class="event-badge {_abuse_type_class(r[2])}">{escape(_abuse_type_label(r[2]))}</span></td>
            <td><div class="node-name-cell"><a href="{escape(href,quote=True)}"><b>{escape(r[3])}</b></a>{f'<small class="node-ipv4">{escape(ip)}</small>' if ip else ''}</div></td><td class="mono uuid-col"><a href="{escape(href,quote=True)}">{escape(r[4])}</a></td><td><div class="abuse-reasons">{reasons}</div></td>
            <td class="num">{safe_float(r[6],0):.2f}x</td><td class="num">{fmt_pps_value(r[7])}</td><td class="num">{fmt_pps_value(r[8])}</td><td class="num">{safe_float(r[13],0):.1f}%</td><td class="num">{human_rate(safe_float(r[17],0)+safe_float(r[18],0))}</td><td>{escape(r[23] or '-')}</td>
            <td><form class="clear-event-form" method="post" action="{url_for('clear_abuse_events')}" onsubmit="return confirm('Permanently delete this abuse log record?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="mode" value="selected"><input type="hidden" name="event_ids" value="{safe_int(r[0],0)}"><input type="hidden" name="return_q" value="{escape(q,quote=True)}"><button class="btn-danger" type="submit">Clear</button></form></td></tr>"""
        if not body: body='<tr><td colspan="14" class="empty">No saved abuse events</td></tr>'
        h=lambda label,key:_abuse_sort_link(label,key,"history",q,sort_by,order,limit)
        table=f"""
        <div class="card vm-table-card"><div class="abuse-table-tools"><div><h3 style="margin:0">Abuse History / Event Log</h3><div class="table-hint">{total} persistent records. Clear permanently deletes the selected database records.</div></div>
        <form id="abuse-clear-selected" method="post" action="{url_for('clear_abuse_events')}" onsubmit="return confirm('Permanently delete selected abuse log records?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="mode" value="selected"><input type="hidden" name="return_q" value="{escape(q,quote=True)}"><button class="btn-danger" type="submit">Clear selected</button></form>
        <form method="post" action="{url_for('clear_abuse_events')}" onsubmit="return confirm('Permanently delete ALL abuse history matching the current search?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="mode" value="matching"><input type="hidden" name="q" value="{escape(q,quote=True)}"><button class="btn-danger" type="submit">Clear all matching</button></form></div>
        <div class="table-wrap"><table class="abuse-history-table"><colgroup><col style="width:45px"><col style="width:70px"><col class="time-col"><col style="width:125px"><col class="node-col"><col class="uuid-col"><col class="reason-col"><col class="small-col"><col class="rate-col"><col class="rate-col"><col class="rate-col"><col class="rate-col"><col style="width:220px"><col style="width:80px"></colgroup><thead><tr>
        <th></th><th>ID</th><th>{h('TIME','time')}</th><th>{h('EVENT','type')}</th><th>{h('NODE','node')}</th><th>{h('VM UUID','vm')}</th><th>REASON</th><th>{h('SEVERITY','severity')}</th><th>{h('RX PPS','rx_pps')}</th><th>{h('TX PPS','tx_pps')}</th><th>{h('CPU','cpu')}</th><th>{h('DISK','disk')}</th><th>DETAIL</th><th>ACTION</th></tr></thead><tbody>{body}</tbody></table></div></div>"""

    content=f"""{_abuse_page_style()}<div class="card top-card"><div class="overview-head"><h3>VM Abuse</h3><div class="overview-meta"><span>Current query <b>bounded state table</b></span><span>History retention <b>7 days</b></span></div></div>{tabs}{policy}{search}</div>{table}"""
    return page("VM Abuse",content)

app.view_functions["vm_abuse_page"] = vm_abuse_page_v480

@app.route("/abuse/vms/clear", methods=["POST"])
def clear_abuse_events():
    deny=require_admin()
    if deny: return deny
    mode=(request.form.get("mode") or "selected").strip().lower()
    q=(request.form.get("q") or request.form.get("return_q") or "").strip()
    conn=db()
    try:
        if mode == "matching":
            params=[]; where=""
            if q:
                p=like_pattern(q); where=" WHERE node LIKE ? OR vm_uuid LIKE ? OR abuse_flags LIKE ? OR event_type LIKE ?"; params=[p,p,p,p]
            cur=conn.execute(f"DELETE FROM vm_abuse_events{where}",params)
        else:
            ids=sorted({safe_int(x,0) for x in request.form.getlist("event_ids") if safe_int(x,0)>0})
            if not ids: return redirect(url_for("vm_abuse_page",tab="history",q=q or None))
            placeholders=",".join("?" for _ in ids); cur=conn.execute(f"DELETE FROM vm_abuse_events WHERE id IN ({placeholders})",ids)
        deleted=max(0,safe_int(cur.rowcount,0)); conn.commit()
    finally: conn.close()
    actor=dashboard_username() or get_admin_username()
    log_account_event("abuse_history_cleared",username=actor,realm="admin",role="admin",detail=f"mode={mode};deleted={deleted};q={q}"[:500])
    return redirect(url_for("vm_abuse_page",tab="history",q=q or None))

@app.route("/admin/abuse-settings", methods=["POST"])
def admin_abuse_settings():
    deny=require_admin()
    if deny: return deny
    action=(request.form.get("action") or "save").strip().lower()
    now=now_ts()
    conn=db()
    try:
        if action == "reset":
            values=dict(ABUSE_SETTING_DEFAULTS)
        else:
            network_pps=max(1000.0,min(100000000.0,safe_float(request.form.get("network_pps"),200000)))
            network_seconds=max(15,min(300,safe_int(request.form.get("network_required_seconds"),270)))
            cpu_percent=max(1.0,min(100.0,safe_float(request.form.get("cpu_full_percent"),90)))
            cpu_minutes=max(5,min(1440,safe_int(request.form.get("cpu_required_minutes"),30)))
            disk_mibps=max(0.0,min(100000.0,safe_float(request.form.get("disk_mibps"),200)))
            disk_iops=max(0.0,min(10000000.0,safe_float(request.form.get("disk_iops"),5000)))
            disk_minutes=max(5,min(1440,safe_int(request.form.get("disk_required_minutes"),15)))
            values={
              "abuse_network_enabled":"1" if request.form.get("network_enabled") else "0",
              "abuse_network_pps":str(network_pps),"abuse_network_required_seconds":str(network_seconds),
              "abuse_cpu_enabled":"1" if request.form.get("cpu_enabled") else "0",
              "abuse_cpu_full_percent":str(cpu_percent),"abuse_cpu_required_seconds":str(cpu_minutes*60),
              "abuse_disk_enabled":"1" if request.form.get("disk_enabled") else "0",
              "abuse_disk_bps":str(disk_mibps*1024*1024),"abuse_disk_iops":str(disk_iops),"abuse_disk_required_seconds":str(disk_minutes*60),
            }
        for key,value in values.items():
            conn.execute("""INSERT INTO admin_settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",(key,str(value),now))
        conn.commit(); cfg=get_abuse_settings(conn); _apply_abuse_settings_to_runtime(cfg)
    finally: conn.close()
    actor=dashboard_username() or get_admin_username()
    log_account_event("abuse_settings_updated",username=actor,realm="admin",role="admin",detail=f"action={action};network_pps={cfg['network_pps']};cpu={cfg['cpu_full_percent']};disk_bps={cfg['disk_bps']}"[:500])
    return redirect(url_for("admin_page",abusemsg="Abuse settings saved. Agent v10 receives the network PPS threshold in the next push response; allow one full 5-minute window before judging the new network rule."))

_admin_page_v470 = app.view_functions.get("admin_page")

def admin_page_v480():
    # The original admin_page now renders abuse_settings_admin_card() directly near the top.
    # Keep this wrapper only for endpoint compatibility.
    return _admin_page_v470()

app.view_functions["admin_page"] = admin_page_v480

