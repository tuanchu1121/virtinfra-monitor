V48102_VERSION = "48.10.2"

# Everything operational may be removed by the explicit nuclear reset. Keep
# only the users, current Admin settings and the schema so the operator can
# still log in after the dashboard has been emptied.
V48102_RESET_APP_TABLES = (
    "vm_iface_current",
    "vm_current_fast",
    "node_current_fast",
    "vm_abuse_state",
    "vm_abuse_events",
    "vm_disk_current",
    "node_storage_current",
    "abuse_policy_versions",
    "vm_latest_metrics",
    "node_host_latest",
    "node_filesystem_latest",
    "node_physical_net_latest",
    "node_bridge_addresses_latest",
    "agent_health_latest",
    "vm_location_latest",
    "vm_node_presence",
    "vm_inventory",
    "node_inventory",
    "vm_migration_events",
    "node_missed_events",
    "push_receipts",
    "node_push_snapshots",
    "vm_consumption_daily",
    "vm_consumption_hourly",
    "usage",
    "node_stats",
    "vm_perf_stats",
    "node_host_stats",
    "node_filesystem_stats",
    "node_physical_net_stats",
    "agent_health_stats",
    "node_logs",
    "retention_runs",
    "account_logs",
)

def reset_all_app_data():
    """Delete every operational row while preserving login and Admin config.

    The maintenance worker calls this while bw-monitor.service is stopped. Each
    table is committed separately so a large historical database never creates
    one enormous rollback journal. maintenance_jobs is intentionally handled by
    the runner because it must keep the currently executing row alive until the
    reset has completed successfully.
    """
    result = {
        "tables": {},
        "total_deleted": 0,
        "preserved": ["admin_settings", "dashboard_users", "maintenance_jobs"],
    }
    for table in V48102_RESET_APP_TABLES:
        conn = db()
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                result["tables"][table] = {"status": "missing", "deleted": 0}
                continue
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(f'DELETE FROM "{table}"')
            deleted = max(0, safe_int(cur.rowcount, 0))
            conn.commit()
            result["tables"][table] = {"status": "ok", "deleted": deleted}
            result["total_deleted"] += deleted
        except BaseException:
            try:
                conn.rollback()
            except BaseException:
                pass
            raise
        finally:
            conn.close()

    conn = db()
    try:
        has_sequence = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
        ).fetchone()
        if has_sequence:
            placeholders = ",".join("?" for _ in V48102_RESET_APP_TABLES)
            conn.execute(
                f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})",
                tuple(V48102_RESET_APP_TABLES),
            )
        conn.execute("PRAGMA optimize")
        conn.commit()
    finally:
        conn.close()
    return result

def _v48102_top_sort_link(label, key, period, q, current_sort, current_order, scope, limit):
    next_order = reverse_order(current_order) if current_sort == key else "desc"
    arrow = " ↓" if current_sort == key and current_order == "desc" else (" ↑" if current_sort == key else "")
    kwargs = {
        "period": period,
        "q": q,
        "sort": key,
        "order": next_order,
        "scope": scope,
        "limit": limit,
    }
    at = request.args.get("at")
    if at:
        kwargs["at"] = at
    href = url_for("top_page", **kwargs)
    active = " active" if current_sort == key else ""
    return f'<a class="cpu-sort-link{active}" href="{escape(href, quote=True)}">{escape(label)}{arrow}</a>'

def _v48102_cpu_level(full_percent):
    value = safe_float(full_percent, 0.0)
    if value >= 90:
        return "hot"
    if value >= 70:
        return "warm"
    if value >= 40:
        return "busy"
    return "normal"

def _v48102_minutes_progress(current_cycles, required_cycles):
    current_minutes = max(0, safe_int(current_cycles, 0)) * 5
    required_minutes = max(1, safe_int(required_cycles, 1)) * 5
    return f"{current_minutes}/{required_minutes} min"

def _v48102_current_abuse_page(q, sort_by, order, limit):
    rows, total, counts, sort_by, order, cfg = _v4810_current_abuse_query(q, sort_by, order, limit)

    def h(label, key):
        next_order = reverse_order(order) if sort_by == key else "desc"
        arrow = " ↓" if sort_by == key and order == "desc" else (" ↑" if sort_by == key else "")
        href = url_for(
            "vm_abuse_page", tab="current", q=q or None,
            sort=key, order=next_order, limit=limit,
        )
        return f'<a class="sort-link" href="{escape(href, quote=True)}">{escape(label)}{arrow}</a>'

    body = ""
    for rank, r in enumerate(rows, 1):
        labels = _abuse_flag_labels(r[4], cfg)
        reasons = "".join(metric_pill(escape(x), "crit") for x in labels)
        href = url_for("vm_page", node=r[0], vm_uuid=r[1], period="1h")
        ip = compact_ipv4(r[21])
        network = _v4810_metric_pair(
            "RX AVG", f"{safe_float(r[22], 0):.2f} Mbps",
            "TX AVG", f"{safe_float(r[23], 0):.2f} Mbps",
            _v48102_minutes_progress(r[28], cfg["network_mbps_required_cycles"]),
            _v48102_minutes_progress(r[29], cfg["network_mbps_required_cycles"]),
        )
        pps_sync = "synced" if safe_int(r[30], 0) else "waiting"
        peak = _v4810_metric_pair(
            "RX PEAK", f"{fmt_pps_value(r[8])} PPS",
            "TX PEAK", f"{fmt_pps_value(r[9])} PPS",
            f"{safe_int(r[10], 0)}s high · {pps_sync}",
            f"{safe_int(r[11], 0)}s high · {pps_sync}",
        )
        cpu = (
            f'<div class="metric-stack abuse-cpu-stack"><b>{safe_float(r[12],0):.1f}%</b>'
            f'<span>{safe_int(r[14],0)} vCPU</span>'
            f'<small>{_v48102_minutes_progress(r[26], cfg["cpu_required_cycles"])} sustained</small></div>'
        )
        disk_iops = safe_float(r[18], 0) + safe_float(r[19], 0)
        disk = _v4810_metric_pair(
            "READ", human_rate(r[16]), "WRITE", human_rate(r[17]),
            f"{disk_iops:,.1f} IOPS",
            _v48102_minutes_progress(r[27], cfg["disk_required_cycles"]),
        )
        timeline = (
            f'<div class="timeline-cell"><b>{fmt_full(r[3]) if r[3] else "-"}</b>'
            f'<small>Started</small><span>{fmt_push(r[2])}</span>'
            f'<small>Last push · policy v{safe_int(r[32],0)}</small></div>'
        )
        body += f"""
        <tr>
          <td class="rank-cell">{rank}</td>
          <td class="identity-cell"><div class="node-line"><a href="{escape(href,quote=True)}"><b>{escape(r[0])}</b></a>{f'<span>{escape(ip)}</span>' if ip else ''}</div><div class="uuid-line"><a class="mono" href="{escape(href,quote=True)}">{escape(r[1])}</a><button type="button" class="copy-btn" data-copy="{escape(r[1],quote=True)}">⧉</button></div></td>
          <td class="reason-cell"><div class="severity-line"><b>{safe_float(r[5],0):.2f}x</b><span>severity</span></div><div class="abuse-reasons">{reasons}</div></td>
          <td>{network}</td><td>{peak}</td><td>{cpu}</td><td>{disk}</td><td>{timeline}</td>
        </tr>"""
    if not body:
        body = '<tr><td colspan="8" class="empty">No VM currently satisfies the active policy revision</td></tr>'

    current_href = url_for("vm_abuse_page", tab="current", q=q or None, sort=sort_by, order=order, limit=limit)
    history_href = url_for("vm_abuse_page", tab="history", q=q or None, limit=limit)
    search = f"""<form class="search compact-search" method="get" action="{url_for('vm_abuse_page')}"><input type="hidden" name="tab" value="current"><input type="hidden" name="sort" value="{escape(sort_by,quote=True)}"><input type="hidden" name="order" value="{escape(order,quote=True)}"><input name="q" value="{escape(q,quote=True)}" placeholder="Search node, IPv4 or VM UUID"><select name="limit"><option value="100" {'selected' if limit==100 else ''}>100 rows</option><option value="200" {'selected' if limit==200 else ''}>200 rows</option><option value="500" {'selected' if limit==500 else ''}>500 rows</option><option value="1000" {'selected' if limit==1000 else ''}>1000 rows</option></select><button type="submit">Search</button>{f'<a class="clear" href="{url_for("vm_abuse_page",tab="current",limit=limit)}">Reset</a>' if q else ''}</form>"""
    tabs = f'<div class="abuse-tabs"><a class="active" href="{escape(current_href,quote=True)}">Current Abuse</a><a href="{escape(history_href,quote=True)}">History / Logs</a></div>'
    disk_header = f'<div>DISK</div><small>{h("READ","diskr")}<span> · </span>{h("WRITE","diskw")}</small>'
    table = f"""
    <div class="card abuse-current-card abuse-v48102-card">
      <div class="section-head"><div><h3>Current VM Abuse</h3><p>Policy v{cfg['revision']} · exact five-minute windows · bounded current-state query.</p></div><div class="count-badges"><span>All <b>{total}</b></span><span>PPS <b>{counts[0]}</b></span><span>AVG Mbps <b>{counts[1]}</b></span><span>CPU <b>{counts[2]}</b></span><span>Disk <b>{counts[3]}</b></span></div></div>
      <div class="table-wrap"><table class="abuse-v490-table abuse-v48102-table"><colgroup><col class="c-rank"><col class="c-id"><col class="c-reason"><col class="c-network"><col class="c-peak"><col class="c-cpu"><col class="c-disk"><col class="c-time"></colgroup><thead><tr><th>#</th><th>{h('NODE / VM','node')}</th><th>{h('REASON / SEVERITY','severity')}</th><th><div>NETWORK AVG</div><small>{h('RX Mbps','rx_mbps')} · {h('TX Mbps','tx_mbps')}</small></th><th><div>PPS PEAK / WINDOW</div><small>{h('RX PPS','rx_peak')} · {h('TX PPS','tx_peak')}</small></th><th>{h('CPU','cpu')}</th><th>{disk_header}</th><th>{h('TIMELINE','last_seen')}</th></tr></thead><tbody>{body}</tbody></table></div>
      <div class="table-hint">Sustained progress is displayed in minutes. The engine still evaluates exact complete five-minute windows internally. Click <b>READ</b> or <b>WRITE</b> in the Disk header to sort that direction independently.</div>
    </div>"""
    return f"""<div class="card page-hero" data-engine="{escape(ABUSE_ENGINE_VERSION,quote=True)}"><div><span class="eyebrow">ABUSE MONITORING</span><h2>VM Abuse</h2><p>Directional network, CPU and disk signals from the current bounded state table.</p></div><div class="hero-meta"><span>Policy <b>v{cfg['revision']}</b></span><span>Refresh <b>5s partial</b></span><span>Delete <b>Admin only</b></span></div></div><div class="card abuse-toolbar">{tabs}{search}</div><details class="card policy-fold"><summary>Current policy</summary>{_public_abuse_policy(cfg)}</details>{table}"""

def vm_abuse_page_v48102():
    tab = (request.args.get("tab") or "current").strip().lower()
    if tab == "history":
        return vm_abuse_page_v483()
    q = (request.args.get("q") or "").strip()
    sort_by = (request.args.get("sort") or "severity").strip().lower()
    order = clean_sort_order(request.args.get("order", "desc"))
    limit = max(10, min(1000, safe_int(request.args.get("limit"), 200)))
    return page("VM Abuse", _v48102_current_abuse_page(q, sort_by, order, limit))

app.view_functions["vm_abuse_page"] = vm_abuse_page_v48102

def _v4810_progress_bar(current, required):
    """Admin progress bar also presents exact five-minute buckets as minutes."""
    current = max(0, safe_int(current, 0))
    required = max(1, safe_int(required, 1))
    pct = min(100.0, current * 100.0 / required)
    return (
        f'<div class="rule-progress"><span style="width:{pct:.1f}%"></span></div>'
        f'<small>{current * 5}/{required * 5} min</small>'
    )

V48102_UI_CSS = r"""
<style id="v48102-operational-ui">
/* Dense enough for operations, but no more washed-out micro-text. */
body.app-v490 .table-wrap thead th{position:sticky;top:0;z-index:4;box-shadow:0 1px 0 var(--line,#e5e7eb)}
body.app-v490 .table-wrap tbody tr:nth-child(even){background:rgba(15,23,42,.018)}
body.app-v490 .table-wrap tbody tr:hover{background:#eef6ff!important}
body.app-v490.endpoint-top-page .table-top-vm{min-width:1820px;table-layout:fixed}
body.app-v490.endpoint-top-page .table-top-vm th{font-size:10.5px!important;color:#344054!important}
body.app-v490.endpoint-top-page .table-top-vm td{font-size:12px!important;line-height:1.35;color:#1f2937}
body.app-v490.endpoint-top-page .table-top-vm .top-node{width:150px}
body.app-v490.endpoint-top-page .table-top-vm .top-uuid{width:290px}
body.app-v490.endpoint-top-page .table-top-vm .top-cpu{width:128px}
.cpu-dual-head>div{font-size:11px;font-weight:900;margin-bottom:4px}.cpu-dual-head small{display:flex!important;justify-content:center;gap:5px;align-items:center;white-space:nowrap}.cpu-sort-link{font-size:9.5px!important;letter-spacing:.02em;text-decoration:none!important;color:#667085!important;padding:2px 4px;border-radius:5px}.cpu-sort-link:hover,.cpu-sort-link.active{color:#175cd3!important;background:#eaf2ff}.cpu-dual-cell{padding-top:8px!important;padding-bottom:8px!important}.cpu-core-value{display:block;font-size:16px;line-height:1.05;color:#101828}.cpu-full-value{display:block!important;margin-top:4px!important;font-size:10px!important;font-weight:850;letter-spacing:.025em;color:#667085!important}.cpu-meter{display:block;height:4px;margin-top:6px;border-radius:999px;background:#e4e7ec;overflow:hidden}.cpu-meter i{display:block;height:100%;border-radius:inherit;background:#2e90fa}.cpu-warm .cpu-core-value,.cpu-warm .cpu-full-value{color:#b54708!important}.cpu-warm .cpu-meter i{background:#f79009}.cpu-hot .cpu-core-value,.cpu-hot .cpu-full-value{color:#b42318!important}.cpu-hot .cpu-meter i{background:#f04438}.cpu-busy .cpu-core-value{color:#175cd3}
body.app-v490.endpoint-vm-abuse-page .abuse-v48102-table{min-width:1540px!important;table-layout:fixed}
body.app-v490.endpoint-vm-abuse-page .abuse-v48102-table th{font-size:10.5px!important;color:#344054!important;line-height:1.3}
body.app-v490.endpoint-vm-abuse-page .abuse-v48102-table td{font-size:12px!important;line-height:1.4;color:#1f2937;vertical-align:middle}
body.app-v490.endpoint-vm-abuse-page .abuse-v48102-table .c-id{width:315px}.abuse-v48102-table .c-reason{width:285px}.abuse-v48102-table .c-network{width:225px}.abuse-v48102-table .c-peak{width:225px}.abuse-v48102-table .c-cpu{width:135px}.abuse-v48102-table .c-disk{width:225px}.abuse-v48102-table .c-time{width:185px}
.abuse-v48102-table th small{font-size:9.5px!important}.abuse-v48102-table th small .sort-link{display:inline-block;padding:2px 3px;border-radius:4px}.abuse-v48102-table th small .sort-link:hover{background:#eaf2ff}.abuse-v48102-table .metric-pair b{font-size:12.5px}.abuse-v48102-table .metric-pair small{font-size:10px;color:#667085}.abuse-v48102-table .metric-stack b{font-size:18px}.abuse-v48102-table .severity-line b{font-size:19px}.abuse-v48102-card .table-hint{margin-top:10px}.reset-all-card{background:linear-gradient(135deg,#fff7f7,#fff)!important}.reset-all-card h3{color:#b42318}.reset-all-card .btn-danger{font-weight:900!important}
html[data-theme=dark] body.app-v490 .table-wrap tbody tr:nth-child(even){background:rgba(255,255,255,.018)}html[data-theme=dark] body.app-v490 .table-wrap tbody tr:hover{background:#18304d!important}html[data-theme=dark] body.app-v490.endpoint-top-page .table-top-vm td,html[data-theme=dark] body.app-v490.endpoint-vm-abuse-page .abuse-v48102-table td{color:#e7edf7}html[data-theme=dark] .cpu-core-value{color:#f8fafc}html[data-theme=dark] .cpu-meter{background:#26374f}html[data-theme=dark] .reset-all-card{background:linear-gradient(135deg,#2a1518,#172033)!important;border-color:#ef4444!important}
@media(max-width:900px){body.app-v490.endpoint-top-page .table-top-vm td,body.app-v490.endpoint-vm-abuse-page .abuse-v48102-table td{font-size:11.5px!important}.cpu-core-value{font-size:15px}}
</style>
"""

_page_v48102_base = page

def page(title, content):
    # PJAX/fetch requests need only the replaceable content shell. The current
    # document already owns the global CSS and JavaScript, so this avoids
    # retransmitting and reparsing the entire application chrome every 5s.
    if request.headers.get("X-BW-Navigation", "").strip().lower() == "partial":
        endpoint = (request.endpoint or "page").replace("_", "-")
        return Response(
            f'<!doctype html><html><head><title>{escape(title)}</title></head>'
            f'<body class="app-v490 endpoint-{escape(endpoint, quote=True)}">'
            f'<div class="wrap" id="bw-content">{content}</div></body></html>',
            mimetype="text/html",
        )

    response = _page_v48102_base(title, content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace("</head>", V48102_UI_CSS + "</head>", 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.10.2 operational UI layer")
    return response

