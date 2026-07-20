
# New dynamic policy keys. Existing PostgreSQL schemas are upgraded in-place below.
ABUSE_SETTING_DEFAULTS.update({
    "abuse_network_mbps_enabled": "1",
    "abuse_network_avg_mbps": "800",
    "abuse_network_mbps_required_seconds": "300",
})

ABUSE_NETWORK_AVG_MBPS = 800.0
ABUSE_NETWORK_MBPS_REQUIRED_SECONDS = 300

def _v484_migrate_schema():
    conn = db()
    try:
        # Current state keeps directional average Mbps and independent streaks.
        for column, ddl in {
            "network_rx_mbps_hit": "INTEGER NOT NULL DEFAULT 0",
            "network_tx_mbps_hit": "INTEGER NOT NULL DEFAULT 0",
            "network_rx_mbps_streak_seconds": "INTEGER NOT NULL DEFAULT 0",
            "network_tx_mbps_streak_seconds": "INTEGER NOT NULL DEFAULT 0",
            "rx_mbps": "REAL NOT NULL DEFAULT 0",
            "tx_mbps": "REAL NOT NULL DEFAULT 0",
        }.items():
            ensure_column(conn, "vm_abuse_state", column, ddl)

        # Event rows retain the exact bandwidth values that caused the event.
        for column, ddl in {
            "rx_mbps": "REAL NOT NULL DEFAULT 0",
            "tx_mbps": "REAL NOT NULL DEFAULT 0",
            "network_rx_mbps_streak_seconds": "INTEGER NOT NULL DEFAULT 0",
            "network_tx_mbps_streak_seconds": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            ensure_column(conn, "vm_abuse_events", column, ddl)

        conn.commit()
    finally:
        conn.close()

_v484_migrate_schema()

def get_abuse_settings(conn=None):
    own = conn is None
    if own:
        conn = db()
    try:
        keys = tuple(ABUSE_SETTING_DEFAULTS)
        placeholders = ",".join("?" for _ in keys)
        rows = conn.execute(
            f"SELECT key,value,updated_at FROM admin_settings WHERE key IN ({placeholders})",
            keys,
        ).fetchall()
        values = dict(ABUSE_SETTING_DEFAULTS)
        revision = 0
        for key, value, updated_at in rows:
            values[str(key)] = str(value)
            revision = max(revision, safe_int(updated_at, 0))
        return {
            "network_enabled": _setting_bool(values["abuse_network_enabled"], True),
            "network_pps": max(1000.0, safe_float(values["abuse_network_pps"], 200000.0)),
            "network_required_seconds": max(15, min(300, safe_int(values["abuse_network_required_seconds"], 270))),
            "network_mbps_enabled": _setting_bool(values["abuse_network_mbps_enabled"], True),
            "network_avg_mbps": max(0.0, min(1000000.0, safe_float(values["abuse_network_avg_mbps"], 800.0))),
            "network_mbps_required_seconds": max(300, min(86400, safe_int(values["abuse_network_mbps_required_seconds"], 300))),
            "cpu_enabled": _setting_bool(values["abuse_cpu_enabled"], True),
            "cpu_full_percent": max(1.0, min(100.0, safe_float(values["abuse_cpu_full_percent"], 90.0))),
            "cpu_required_seconds": max(300, min(86400, safe_int(values["abuse_cpu_required_seconds"], 1800))),
            "disk_enabled": _setting_bool(values["abuse_disk_enabled"], True),
            "disk_read_bps": max(0.0, safe_float(values.get("abuse_disk_read_bps"), 0.0)),
            "disk_write_bps": max(0.0, safe_float(values.get("abuse_disk_write_bps"), 0.0)),
            "disk_bps": max(0.0, safe_float(values["abuse_disk_bps"], 200.0 * 1024 * 1024)),
            "disk_iops": max(0.0, safe_float(values["abuse_disk_iops"], 5000.0)),
            "disk_required_seconds": max(300, min(86400, safe_int(values["abuse_disk_required_seconds"], 900))),
            "revision": revision,
        }
    finally:
        if own:
            conn.close()

def _apply_abuse_settings_to_runtime(cfg):
    global ABUSE_NETWORK_PPS, ABUSE_NETWORK_REQUIRED_SECONDS
    global ABUSE_NETWORK_AVG_MBPS, ABUSE_NETWORK_MBPS_REQUIRED_SECONDS
    global ABUSE_CPU_FULL_PERCENT, ABUSE_CPU_REQUIRED_SECONDS
    global ABUSE_DISK_READ_BPS, ABUSE_DISK_WRITE_BPS
    global ABUSE_DISK_BPS, ABUSE_DISK_IOPS, ABUSE_DISK_REQUIRED_SECONDS

    ABUSE_NETWORK_PPS = cfg["network_pps"] if cfg["network_enabled"] else 10**18
    ABUSE_NETWORK_REQUIRED_SECONDS = cfg["network_required_seconds"] if cfg["network_enabled"] else 10**9
    ABUSE_NETWORK_AVG_MBPS = cfg["network_avg_mbps"] if cfg["network_mbps_enabled"] and cfg["network_avg_mbps"] > 0 else 10**18
    ABUSE_NETWORK_MBPS_REQUIRED_SECONDS = cfg["network_mbps_required_seconds"] if cfg["network_mbps_enabled"] and cfg["network_avg_mbps"] > 0 else 10**9
    ABUSE_CPU_FULL_PERCENT = cfg["cpu_full_percent"] if cfg["cpu_enabled"] else 10**9
    ABUSE_CPU_REQUIRED_SECONDS = cfg["cpu_required_seconds"] if cfg["cpu_enabled"] else 10**9

    if cfg["disk_enabled"]:
        ABUSE_DISK_READ_BPS = cfg["disk_read_bps"]
        ABUSE_DISK_WRITE_BPS = cfg["disk_write_bps"]
        ABUSE_DISK_BPS = cfg["disk_bps"]
        ABUSE_DISK_IOPS = cfg["disk_iops"]
        ABUSE_DISK_REQUIRED_SECONDS = cfg["disk_required_seconds"]
    else:
        ABUSE_DISK_READ_BPS = 0.0
        ABUSE_DISK_WRITE_BPS = 0.0
        ABUSE_DISK_BPS = 0.0
        ABUSE_DISK_IOPS = 0.0
        ABUSE_DISK_REQUIRED_SECONDS = 10**9

def _abuse_state_map(conn, node):
    rows = conn.execute("""
        SELECT node,vm_uuid,last_seen,is_abuse,abuse_since,abuse_flags,severity,
               network_rx_hit,network_tx_hit,cpu_streak_seconds,disk_streak_seconds,
               rx_pps,tx_pps,rx_peak_pps,tx_peak_pps,seconds_over_rx_pps,seconds_over_tx_pps,
               cpu_full_percent,cpu_core_percent,vcpu_current,
               disk_read_bps,disk_write_bps,disk_read_iops,disk_write_iops,
               COALESCE(network_rx_mbps_hit,0),COALESCE(network_tx_mbps_hit,0),
               COALESCE(network_rx_mbps_streak_seconds,0),COALESCE(network_tx_mbps_streak_seconds,0),
               COALESCE(rx_mbps,0),COALESCE(tx_mbps,0)
        FROM vm_abuse_state WHERE node=?
    """, (node,)).fetchall()
    keys = [
        "node","vm_uuid","last_seen","is_abuse","abuse_since","abuse_flags","severity",
        "network_rx_hit","network_tx_hit","cpu_streak_seconds","disk_streak_seconds",
        "rx_pps","tx_pps","rx_peak_pps","tx_peak_pps","seconds_over_rx_pps","seconds_over_tx_pps",
        "cpu_full_percent","cpu_core_percent","vcpu_current",
        "disk_read_bps","disk_write_bps","disk_read_iops","disk_write_iops",
        "network_rx_mbps_hit","network_tx_mbps_hit",
        "network_rx_mbps_streak_seconds","network_tx_mbps_streak_seconds",
        "rx_mbps","tx_mbps",
    ]
    return {str(r[1]): dict(zip(keys, r)) for r in rows}

# Use the original bounded current-state writer directly, then add the dynamic
# AVG Mbps streak before creating event records. This avoids scanning history.

def admin_abuse_settings_v484():
    deny = require_admin()
    if deny:
        return deny
    action = (request.form.get("action") or "save").strip().lower()
    now = now_ts()
    conn = db()
    try:
        if action == "reset":
            values = dict(ABUSE_SETTING_DEFAULTS)
        else:
            network_pps = max(1000.0, min(100000000.0, safe_float(request.form.get("network_pps"), 200000)))
            network_seconds = max(15, min(300, safe_int(request.form.get("network_required_seconds"), 270)))
            network_avg_mbps = max(0.0, min(1000000.0, safe_float(request.form.get("network_avg_mbps"), 800)))
            network_mbps_minutes = max(5, min(1440, safe_int(request.form.get("network_mbps_required_minutes"), 5)))
            cpu_percent = max(1.0, min(100.0, safe_float(request.form.get("cpu_full_percent"), 90)))
            cpu_minutes = max(5, min(1440, safe_int(request.form.get("cpu_required_minutes"), 30)))
            disk_read_mibps = max(0.0, min(100000.0, safe_float(request.form.get("disk_read_mibps"), 0)))
            disk_write_mibps = max(0.0, min(100000.0, safe_float(request.form.get("disk_write_mibps"), 0)))
            disk_mibps = max(0.0, min(100000.0, safe_float(request.form.get("disk_mibps"), 200)))
            disk_iops = max(0.0, min(10000000.0, safe_float(request.form.get("disk_iops"), 5000)))
            disk_minutes = max(5, min(1440, safe_int(request.form.get("disk_required_minutes"), 15)))
            values = {
                "abuse_network_enabled": "1" if request.form.get("network_enabled") else "0",
                "abuse_network_pps": str(network_pps),
                "abuse_network_required_seconds": str(network_seconds),
                "abuse_network_mbps_enabled": "1" if request.form.get("network_mbps_enabled") else "0",
                "abuse_network_avg_mbps": str(network_avg_mbps),
                "abuse_network_mbps_required_seconds": str(network_mbps_minutes * 60),
                "abuse_cpu_enabled": "1" if request.form.get("cpu_enabled") else "0",
                "abuse_cpu_full_percent": str(cpu_percent),
                "abuse_cpu_required_seconds": str(cpu_minutes * 60),
                "abuse_disk_enabled": "1" if request.form.get("disk_enabled") else "0",
                "abuse_disk_read_bps": str(disk_read_mibps * 1024 * 1024),
                "abuse_disk_write_bps": str(disk_write_mibps * 1024 * 1024),
                "abuse_disk_bps": str(disk_mibps * 1024 * 1024),
                "abuse_disk_iops": str(disk_iops),
                "abuse_disk_required_seconds": str(disk_minutes * 60),
            }
        for key, value in values.items():
            conn.execute("""INSERT INTO admin_settings(key,value,updated_at) VALUES(?,?,?)
                            ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                         (key, str(value), now))
        conn.commit()
        cfg = get_abuse_settings(conn)
        _apply_abuse_settings_to_runtime(cfg)
    finally:
        conn.close()

    actor = dashboard_username() or get_admin_username()
    detail = (
        f"action={action};network_pps={cfg['network_pps']};network_seconds={cfg['network_required_seconds']};"
        f"network_avg_mbps={cfg['network_avg_mbps']};network_mbps_seconds={cfg['network_mbps_required_seconds']};"
        f"cpu={cfg['cpu_full_percent']};cpu_seconds={cfg['cpu_required_seconds']};"
        f"disk_read={cfg['disk_read_bps']};disk_write={cfg['disk_write_bps']};"
        f"disk_total={cfg['disk_bps']};disk_iops={cfg['disk_iops']};disk_seconds={cfg['disk_required_seconds']}"
    )
    log_account_event("abuse_settings_updated", username=actor, realm="admin", role="admin", detail=detail[:1000])
    msg = "Abuse policy saved. AVG Mbps, CPU and Disk apply immediately on the monitor. Agent v10 receives a changed PPS threshold on its next push."
    return redirect(url_for("admin_abuse_page", msg=msg))

app.view_functions["admin_abuse_settings"] = admin_abuse_settings_v484

# Fast current Abuse viewer with directional AVG Mbps and sortable columns.

def _current_abuse_query_v484(q, sort_by, order, limit):
    allowed = {
        "severity":"a.severity", "node":"a.node COLLATE NOCASE", "vm":"a.vm_uuid COLLATE NOCASE",
        "rx_mbps":"a.rx_mbps", "tx_mbps":"a.tx_mbps",
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
          SELECT SUM(CASE WHEN a.abuse_flags LIKE '%NETWORK_%' THEN 1 ELSE 0 END),
                 SUM(CASE WHEN a.abuse_flags LIKE '%AVG_MBPS%' THEN 1 ELSE 0 END),
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
                 COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest b WHERE b.node=a.node AND LOWER(role)='public' LIMIT 1),''),
                 COALESCE(a.rx_mbps,0),COALESCE(a.tx_mbps,0),
                 COALESCE(a.network_rx_mbps_streak_seconds,0),COALESCE(a.network_tx_mbps_streak_seconds,0)
          FROM vm_abuse_state a
          LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
          WHERE a.is_abuse=1 AND a.last_seen>=? AND COALESCE(vi.status,'active')!='hidden' {search_sql}
          ORDER BY {allowed[sort_by]} {order.upper()},a.last_seen DESC,a.node COLLATE NOCASE,a.vm_uuid COLLATE NOCASE
          LIMIT ?
        """, params + [limit]).fetchall()
        return rows, int(total or 0), tuple(int(x or 0) for x in (counts or (0,0,0,0))), sort_by, order
    finally:
        conn.close()

def vm_abuse_page_v484():
    tab = (request.args.get("tab") or "current").strip().lower()
    if tab == "history":
        # Existing history page remains read-only for Viewer users. The labels
        # below understand the new Mbps flags and saved threshold JSON.
        return vm_abuse_page_v483()

    q = (request.args.get("q") or "").strip()
    sort_by = (request.args.get("sort") or "severity").strip().lower()
    order = clean_sort_order(request.args.get("order", "desc"))
    limit = max(10, min(1000, safe_int(request.args.get("limit"), 200)))
    cfg = get_abuse_settings()
    rows,total,counts,sort_by,order = _current_abuse_query_v484(q,sort_by,order,limit)

    def h(label, key):
        next_order = reverse_order(order) if sort_by == key else "desc"
        arrow = " ↓" if sort_by == key and order == "desc" else (" ↑" if sort_by == key else "")
        href = url_for("vm_abuse_page", tab="current", q=q or None, sort=key, order=next_order, limit=limit)
        return f'<a class="sort-link" href="{escape(href,quote=True)}">{escape(label)}{arrow}</a>'

    body = ""
    for rank,r in enumerate(rows,1):
        labels = _abuse_flag_labels(r[4], cfg)
        reasons = "".join(metric_pill(escape(x),"crit") for x in labels)
        href = url_for("vm_page",node=r[0],vm_uuid=r[1],period="1h")
        ip = compact_ipv4(r[21])
        body += f"""
        <tr>
          <td class="num">{rank}</td>
          <td><div class="node-name-cell"><a href="{escape(href,quote=True)}"><b>{escape(r[0])}</b></a>{f'<small class="node-ipv4">{escape(ip)}</small>' if ip else ''}</div></td>
          <td class="mono uuid-col"><span class="uuid-cell"><a href="{escape(href,quote=True)}">{escape(r[1])}</a><button type="button" class="copy-btn" data-copy="{escape(r[1],quote=True)}">⧉</button></span></td>
          <td><div class="abuse-reasons">{reasons}</div></td>
          <td class="num"><b>{safe_float(r[5],0):.2f}x</b></td>
          <td class="num"><b>{safe_float(r[22],0):.2f}</b><small class="metric-subline">{safe_int(r[24],0)//60}m streak</small></td>
          <td class="num"><b>{safe_float(r[23],0):.2f}</b><small class="metric-subline">{safe_int(r[25],0)//60}m streak</small></td>
          <td class="num">{fmt_pps_value(r[6])}<small class="metric-subline">{safe_int(r[10],0)}s high</small></td>
          <td class="num">{fmt_pps_value(r[7])}<small class="metric-subline">{safe_int(r[11],0)}s high</small></td>
          <td class="num">{fmt_pps_value(r[8])}</td><td class="num">{fmt_pps_value(r[9])}</td>
          <td class="num"><b>{safe_float(r[12],0):.1f}%</b><small class="metric-subline">{safe_int(r[15],0)//60}m</small></td>
          <td class="num">{safe_int(r[14],0)}</td><td class="num">{human_rate(r[16])}</td><td class="num">{human_rate(r[17])}</td>
          <td class="num">{safe_float(r[18],0)+safe_float(r[19],0):.1f}</td><td class="num">{fmt_push(r[2])}</td><td class="num">{fmt_full(r[3]) if r[3] else '-'}</td>
        </tr>"""
    if not body:
        body = '<tr><td colspan="18" class="empty">No VM currently satisfies a sustained abuse rule</td></tr>'

    current_href = url_for("vm_abuse_page",tab="current",q=q or None,sort=sort_by,order=order,limit=limit)
    history_href = url_for("vm_abuse_page",tab="history",q=q or None,limit=limit)
    search = f"""<form class="search" method="get" action="{url_for('vm_abuse_page')}"><input type="hidden" name="tab" value="current"><input type="hidden" name="sort" value="{escape(sort_by,quote=True)}"><input type="hidden" name="order" value="{escape(order,quote=True)}"><input name="q" value="{escape(q,quote=True)}" placeholder="Search node / IPv4 / VM UUID"><input name="limit" type="number" min="10" max="1000" value="{limit}" style="max-width:105px;min-width:90px"><button type="submit">Search</button>{f'<a class="clear" href="{url_for("vm_abuse_page",tab="current",limit=limit)}">Clear search</a>' if q else ''}</form>"""
    tabs = f'<div class="abuse-tabs"><a class="active" href="{escape(current_href,quote=True)}">Current Abuse</a><a href="{escape(history_href,quote=True)}">Abuse History / Logs</a></div>'
    policy = _public_abuse_policy(cfg)

    table = f"""
    <div class="card vm-table-card">
      <div class="abuse-table-tools"><div><h3 style="margin:0">Current VM Abuse</h3><div class="table-hint">Fast bounded-state query. AVG Mbps is directional and uses consecutive full push windows.</div></div>
      <div class="count-badges"><span>Network <b>{counts[0]}</b></span><span>AVG Mbps <b>{counts[1]}</b></span><span>CPU <b>{counts[2]}</b></span><span>Disk <b>{counts[3]}</b></span></div></div>
      <div class="table-wrap"><table class="abuse-fast-table" style="min-width:2210px"><thead><tr>
        <th>#</th><th>{h('NODE','node')}</th><th>{h('VM UUID','vm')}</th><th>REASON</th><th>{h('SEVERITY','severity')}</th>
        <th>{h('RX AVG Mbps','rx_mbps')}</th><th>{h('TX AVG Mbps','tx_mbps')}</th>
        <th>{h('RX PPS','rx_pps')}</th><th>{h('TX PPS','tx_pps')}</th><th>{h('RX PEAK PPS','rx_peak')}</th><th>{h('TX PEAK PPS','tx_peak')}</th>
        <th>{h('CPU FULL%','cpu')}</th><th>{h('vCPU','vcpu')}</th><th>{h('DISK R/s','diskr')}</th><th>{h('DISK W/s','diskw')}</th><th>{h('IOPS','iops')}</th><th>{h('LAST PUSH','last_seen')}</th><th>{h('ABUSE SINCE','since')}</th>
      </tr></thead><tbody>{body}</tbody></table></div>
    </div>"""
    content = f"""{_abuse_page_style()}<div class="card top-card"><div class="overview-head"><h3>VM Abuse</h3><div class="overview-meta"><span>Current query <b>bounded state table</b></span><span>History retention <b>7 days</b></span><span>Delete <b>Admin only</b></span></div></div>{tabs}{policy}{search}</div>{table}"""
    return page("VM Abuse",content)

app.view_functions["vm_abuse_page"] = vm_abuse_page_v484

# Custom snapshot helpers. The same `at` parameter now anchors Dashboard,
# Top Node, Top VM, Node detail and VM detail.

_range_for_period_v483 = range_for_period
_resolve_snapshot_bucket_v483 = resolve_snapshot_bucket
_get_node_rows_v483 = get_node_rows
_get_top_vm_rows_v483 = get_top_vm_rows
_query_node_bridge_v483 = query_node_bridge
_get_vm_latest_metric_v483 = get_vm_latest_metric
_get_vm_directional_current_v483 = get_vm_directional_current
_range_card_v483 = range_card
_dashboard_custom_time_card_v483 = dashboard_custom_time_card
_vm_period_links_v483 = vm_period_links
_top_node_page_v483 = top_node_page
_top_page_v483 = top_page

def _request_target_ts():
    try:
        return _parse_datetime_local(request.args.get("at"))
    except RuntimeError:
        return None

def range_for_period(period):
    target = _request_target_ts()
    if target is None:
        return _range_for_period_v483(period)
    end = int(target)
    return end - period_seconds(clean_period(period)), end

def resolve_snapshot_bucket(conn, period, node=None):
    target = _request_target_ts()
    if target is None:
        return _resolve_snapshot_bucket_v483(conn, period, node=node)

    target_bucket = bucket_for(target)
    if node:
        latest_row = conn.execute("SELECT MAX(bucket) FROM node_push_snapshots WHERE node=?", (node,)).fetchone()
        selected_row = conn.execute("SELECT MAX(bucket) FROM node_push_snapshots WHERE node=? AND bucket<=?", (node,target_bucket)).fetchone()
    else:
        latest_row = conn.execute("SELECT MAX(bucket) FROM node_push_snapshots").fetchone()
        selected_row = conn.execute("SELECT MAX(bucket) FROM node_push_snapshots WHERE bucket<=?", (target_bucket,)).fetchone()
    latest = safe_int((latest_row or [0])[0],0)
    selected = safe_int((selected_row or [0])[0],0)

    if selected <= 0:
        union_sql = _snapshot_bucket_candidates_sql(node_scoped=bool(node))
        bind = [node,node,node,node] if node else []
        row = conn.execute(f"SELECT MAX(bucket) FROM ({union_sql}) WHERE bucket<=?", bind+[target_bucket]).fetchone()
        selected = safe_int((row or [0])[0],0)
        if latest <= 0:
            row = conn.execute(f"SELECT MAX(bucket) FROM ({union_sql})", bind).fetchone()
            latest = safe_int((row or [0])[0],0)
    if selected <= 0:
        return 0, latest
    return selected, latest

def _custom_snapshot_control(endpoint, target_ts=None, title="Custom Snapshot Time", **params):
    target_ts = target_ts if target_ts is not None else _request_target_ts()
    hidden = []
    for key,value in params.items():
        if value is None or key == "at":
            continue
        hidden.append(f'<input type="hidden" name="{escape(str(key),quote=True)}" value="{escape(str(value),quote=True)}">')
    live_params = {k:v for k,v in params.items() if v is not None and k != "at"}
    target_value = _datetime_local_value(target_ts)
    return f"""
    <div class="card custom-time-card">
      <div class="table-title-row"><h3>{escape(title)}</h3><div class="count-badges"><span>Retention <b>{HOURLY_RETENTION_DAYS} days</b></span><span>Mode <b>real retained data</b></span></div></div>
      <form class="custom-time-form" method="get" action="{url_for(endpoint, **({k:v for k,v in live_params.items() if k in {'node'}}))}">
        {''.join(hidden)}
        <label>Date and time<input type="datetime-local" name="at" value="{escape(target_value,quote=True)}" required></label>
        <button type="submit">Open time</button>
        {f'<a class="clear" href="{escape(url_for(endpoint, **live_params),quote=True)}">Use live</a>' if target_ts else ''}
      </form>
      <div class="table-hint">Snapshot tables use the nearest retained real push at or before this time. Charts on Node and VM pages use the selected period ending at this time.</div>
    </div>"""

def dashboard_custom_time_card(target_ts, q="", sort_by="node", sort_order="asc"):
    # range_card below now renders the shared picker, avoiding two identical cards.
    return ""

def range_card(period, start, end, q="", endpoint="index", node=None, vm_status="active", net="both"):
    base = _range_card_v483(period,start,end,q=q,endpoint=endpoint,node=node,vm_status=vm_status,net=net)
    if endpoint not in {"index","node_page"}:
        return base
    params = {"period":period,"q":q or None}
    if endpoint == "node_page":
        params.update({"node":node,"net":net})
    return base + _custom_snapshot_control(endpoint, _request_target_ts(), **params)

def get_node_rows(period, q="", sort_by="node", order="asc", target_ts=None):
    if target_ts is None:
        target_ts = _request_target_ts()
    if target_ts is not None or clean_period(period) != "5m":
        return _get_node_rows_v483(period,q=q,sort_by=sort_by,order=order,target_ts=target_ts)

    # Fast live 5m query now prefers actual physical NIC counters whenever the
    # agent reported them. VM taps remain a clearly labelled fallback only.
    sort_by = clean_node_sort(sort_by)
    order = clean_sort_order(order)
    order_map = {
        "node":"node COLLATE NOCASE","last_push":"live_last_seen","snapshot":"selected_bucket",
        "vm":"vm_count","load":"load1","uptime":"uptime_seconds","cpu":"cpu_percent",
        "ram":"ram_percent","diskr":"disk_read_bps","diskw":"disk_write_bps",
        "public":"public_total","private":"private_total","total":"node_total",
        "pps":"node_pps_sort","public_pps":"public_pps_sort","private_pps":"private_pps_sort",
        "drops":"net_drops","errors":"net_errors","source":"net_source COLLATE NOCASE",
    }
    stale_after = now_ts() - FAST_CURRENT_STALE_SECONDS
    params = [stale_after, stale_after]
    search_sql = ""
    if q:
        p = like_pattern(q)
        normalized_mac = normalize_mac_address(q)
        search_sql = """ AND (
          n.node LIKE ?
          OR EXISTS(SELECT 1 FROM vm_current_fast v WHERE v.node=n.node AND v.vm_uuid LIKE ?)
          OR EXISTS(
               SELECT 1 FROM node_bridge_addresses_latest b
                WHERE b.node=n.node AND (
                     b.primary_ipv4 LIKE ? OR b.ipv4_json LIKE ?
                     OR b.primary_ipv6 LIKE ? OR b.ipv6_json LIKE ?
                     OR b.bridge LIKE ? OR b.mac LIKE ?
                     OR (?<>'' AND b.mac=?)
                )
          )
          OR EXISTS(
               SELECT 1 FROM vm_nic_identity_lookup l
               JOIN vm_iface_current i
                 ON i.node=l.node AND i.vm_uuid=l.vm_uuid
                AND i.bridge=l.bridge AND i.iface=l.iface AND i.mac=l.mac
                WHERE l.node=n.node AND (
                     i.vm_uuid LIKE ? OR i.iface LIKE ? OR i.bridge LIKE ?
                     OR l.mac LIKE ? OR (?<>'' AND l.mac=?)
                )
          )
          OR EXISTS(
               SELECT 1 FROM node_nic_identity_lookup l
               JOIN node_physical_net_latest pn
                 ON pn.node=l.node AND pn.role=l.role AND pn.mac=l.mac
                WHERE l.node=n.node AND (
                     pn.iface LIKE ? OR pn.bridge LIKE ? OR pn.role LIKE ?
                     OR l.mac LIKE ? OR (?<>'' AND l.mac=?)
                )
          )
        )"""
        params.extend([
            p,p,
            p,p,p,p,p,p,normalized_mac,normalized_mac,
            p,p,p,p,normalized_mac,normalized_mac,
            p,p,p,p,normalized_mac,normalized_mac,
        ])
    conn = db()
    try:
        rows = conn.execute(f"""
        WITH phys_role AS (
          SELECT node,LOWER(role) role,GROUP_CONCAT(DISTINCT iface) ifaces,
                 SUM(rx_delta+tx_delta) total,SUM(rx_packets_delta+tx_packets_delta) packets,
                 SUM(rx_drop_delta+tx_drop_delta) drops,SUM(rx_error_delta+tx_error_delta) errors,
                 MAX(interval_seconds) interval_seconds
          FROM node_physical_net_latest WHERE last_seen>=? AND LOWER(role) IN ('public','private')
          GROUP BY node,LOWER(role)
        ), phys AS (
          SELECT node,
             MAX(CASE WHEN role='public' THEN 1 ELSE 0 END) public_present,
             MAX(CASE WHEN role='private' THEN 1 ELSE 0 END) private_present,
             SUM(CASE WHEN role='public' THEN total ELSE 0 END) public_total,
             SUM(CASE WHEN role='private' THEN total ELSE 0 END) private_total,
             SUM(CASE WHEN role='public' THEN packets ELSE 0 END) public_packets,
             SUM(CASE WHEN role='private' THEN packets ELSE 0 END) private_packets,
             SUM(CASE WHEN role='public' THEN drops ELSE 0 END) public_drops,
             SUM(CASE WHEN role='private' THEN drops ELSE 0 END) private_drops,
             SUM(CASE WHEN role='public' THEN errors ELSE 0 END) public_errors,
             SUM(CASE WHEN role='private' THEN errors ELSE 0 END) private_errors,
             MAX(CASE WHEN role='public' THEN interval_seconds ELSE 0 END) public_interval,
             MAX(CASE WHEN role='private' THEN interval_seconds ELSE 0 END) private_interval,
             MAX(CASE WHEN role='public' THEN ifaces END) public_ifaces,
             MAX(CASE WHEN role='private' THEN ifaces END) private_ifaces
          FROM phys_role GROUP BY node
        ), base AS (
          SELECT n.node,n.last_seen live_last_seen,n.last_seen selected_bucket,'current' retention_tier,
             n.vm_count,n.iface_count,
             CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_total,0) ELSE n.public_bytes END public_total,
             CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_total,0) ELSE n.private_bytes END private_total,
             CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_total,0) ELSE n.public_bytes END +
             CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_total,0) ELSE n.private_bytes END node_total,
             CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_packets,0) ELSE n.public_packets END public_packets,
             CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_packets,0) ELSE n.private_packets END private_packets,
             CASE WHEN COALESCE(p.public_present,0)=1 THEN MAX(COALESCE(p.public_interval,0),1) ELSE MAX(n.interval_seconds,1) END public_interval,
             CASE WHEN COALESCE(p.private_present,0)=1 THEN MAX(COALESCE(p.private_interval,0),1) ELSE MAX(n.interval_seconds,1) END private_interval,
             CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_packets,0) ELSE n.public_packets END +
             CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_packets,0) ELSE n.private_packets END node_packets,
             MAX(COALESCE(p.public_interval,0),COALESCE(p.private_interval,0),n.interval_seconds,1) node_interval,
             CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_drops,0) ELSE 0 END +
             CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_drops,0) ELSE 0 END +
             CASE WHEN COALESCE(p.public_present,0)=0 AND COALESCE(p.private_present,0)=0 THEN n.drops ELSE 0 END net_drops,
             CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_errors,0) ELSE 0 END +
             CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_errors,0) ELSE 0 END +
             CASE WHEN COALESCE(p.public_present,0)=0 AND COALESCE(p.private_present,0)=0 THEN n.errors ELSE 0 END net_errors,
             CASE WHEN n.cpu_count>0 OR n.mem_total>0 THEN 1 ELSE 0 END host_present,
             n.load1,n.load5,n.load15,n.cpu_count,n.cpu_percent,
             CASE WHEN n.mem_total>0 THEN n.mem_used*100.0/n.mem_total ELSE 0 END ram_percent,
             n.disk_read_bps,n.disk_write_bps,n.uptime_seconds,
             CASE WHEN COALESCE(p.public_present,0)=1 AND COALESCE(p.private_present,0)=1 THEN 'NIC'
                  WHEN COALESCE(p.public_present,0)=1 OR COALESCE(p.private_present,0)=1 THEN 'MIXED'
                  ELSE 'VM' END net_source,
             COALESCE(p.public_ifaces,'-') public_ifaces,COALESCE(p.private_ifaces,'-') private_ifaces,
             (CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_packets,0) ELSE n.public_packets END)*1.0/
               MAX(CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_interval,0) ELSE n.interval_seconds END,1) public_pps_sort,
             (CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_packets,0) ELSE n.private_packets END)*1.0/
               MAX(CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_interval,0) ELSE n.interval_seconds END,1) private_pps_sort,
             (CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_packets,0) ELSE n.public_packets END +
              CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_packets,0) ELSE n.private_packets END)*1.0/
               MAX(COALESCE(p.public_interval,0),COALESCE(p.private_interval,0),n.interval_seconds,1) node_pps_sort,
             COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest b WHERE b.node=n.node AND LOWER(role)='public' LIMIT 1),'') public_ipv4,
             COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest b WHERE b.node=n.node AND LOWER(role)='private' LIMIT 1),'') private_ipv4
          FROM node_current_fast n
          LEFT JOIN node_inventory ni ON ni.node=n.node
          LEFT JOIN phys p ON p.node=n.node
          WHERE n.last_seen>=? AND (ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL)) {search_sql}
        )
        SELECT node,live_last_seen,selected_bucket,retention_tier,vm_count,iface_count,
               public_total,private_total,node_total,public_packets,private_packets,public_interval,private_interval,
               node_packets,node_interval,net_drops,net_errors,host_present,load1,load5,load15,cpu_count,cpu_percent,ram_percent,
               disk_read_bps,disk_write_bps,uptime_seconds,net_source,public_ifaces,private_ifaces,
               public_pps_sort,private_pps_sort,node_pps_sort,public_ipv4,private_ipv4
        FROM base ORDER BY {order_map[sort_by]} {order.upper()},node COLLATE NOCASE
        """, params).fetchall()
        latest = max([safe_int(r[1],0) for r in rows] or [now_ts()])
        return rows,latest,latest
    finally:
        conn.close()

def query_node_bridge(node, period, bridge, q="", limit=1000, sort_by="total", order="desc", vm_status="active"):
    if _request_target_ts() is not None:
        return _query_node_bridge_history(node,period,bridge,q=q,limit=limit,sort_by=sort_by,order=order,vm_status=vm_status)
    return _query_node_bridge_v483(node,period,bridge,q=q,limit=limit,sort_by=sort_by,order=order,vm_status=vm_status)

def get_top_vm_rows(period, q="", sort_by="total", order="desc", scope="all", limit=100):
    if _request_target_ts() is not None:
        return _get_top_vm_rows_history(period,q=q,sort_by=sort_by,order=order,scope=scope,limit=limit)
    return _get_top_vm_rows_v483(period,q=q,sort_by=sort_by,order=order,scope=scope,limit=limit)

def _v5054_vm_snapshot_overview(node, vm_uuid, period, bridge="", iface=""):
    """Build one coherent VM overview from one exact retained push bucket.

    The selected Node snapshot is the source of truth. Network, CPU, RAM and
    aggregate disk metrics are never borrowed from the current tables or from a
    neighbouring bucket when an older period/custom time is selected.
    """
    period = clean_period(period)
    node = str(node or "").strip()
    vm_uuid = str(vm_uuid or "").strip()
    bridge = str(bridge or "").strip()
    iface = str(iface or "").strip()
    if not node or not vm_uuid:
        return None

    conn = db()
    try:
        selected_bucket, latest_bucket = resolve_snapshot_bucket(conn, period, node=node)
        if selected_bucket <= 0:
            return None

        net_where = ["node=?", "vm_uuid=?", "bucket=?"]
        net_params = [node, vm_uuid, selected_bucket]
        if bridge:
            net_where.append("bridge=?")
            net_params.append(bridge)
        if iface:
            net_where.append("iface=?")
            net_params.append(iface)

        net = conn.execute(f"""
            SELECT
                COUNT(*),
                MAX(last_push),
                MAX(COALESCE(interval_seconds, ?)),
                COALESCE(SUM(rx_delta), 0),
                COALESCE(SUM(tx_delta), 0),
                COALESCE(SUM(rx_packets_delta), 0),
                COALESCE(SUM(tx_packets_delta), 0),
                COALESCE(SUM(rx_drop_delta + tx_drop_delta), 0),
                COALESCE(SUM(rx_error_delta + tx_error_delta), 0),
                COALESCE(SUM(rx_mbps_peak), 0),
                COALESCE(SUM(tx_mbps_peak), 0),
                COALESCE(SUM(rx_pps_peak), 0),
                COALESCE(SUM(tx_pps_peak), 0),
                MAX(COALESCE(network_sample_count, 0)),
                MAX(COALESCE(network_sample_expected, 0)),
                MAX(COALESCE(network_sample_max_gap_seconds, 0)),
                MAX(COALESCE(seconds_over_pps, 0)),
                MAX(COALESCE(seconds_over_mbps, 0)),
                MAX(CASE UPPER(COALESCE(network_sample_quality, 'LEGACY'))
                    WHEN 'POOR' THEN 3
                    WHEN 'DEGRADED' THEN 2
                    WHEN 'GOOD' THEN 1
                    ELSE 0 END),
                MAX(COALESCE(iface, '')),
                MAX(COALESCE(bridge, ''))
            FROM node_stats
            WHERE {' AND '.join(net_where)}
        """, [CACHE_BUCKET_SECONDS] + net_params).fetchone()

        perf = conn.execute("""
            SELECT
                COUNT(*),
                MAX(last_push),
                MAX(COALESCE(interval_seconds, ?)),
                MAX(COALESCE(cpu_percent, 0)),
                MAX(COALESCE(vcpu_current, 0)),
                MAX(COALESCE(ram_current_kib, 0)),
                MAX(COALESCE(ram_maximum_kib, 0)),
                MAX(COALESCE(ram_rss_kib, 0)),
                MAX(COALESCE(ram_available_kib, 0)),
                MAX(COALESCE(disk_read_delta, 0) * 1.0 /
                    GREATEST(COALESCE(interval_seconds, ?), 1)),
                MAX(COALESCE(disk_write_delta, 0) * 1.0 /
                    GREATEST(COALESCE(interval_seconds, ?), 1))
            FROM vm_perf_stats
            WHERE node=? AND vm_uuid=? AND bucket=?
        """, (
            CACHE_BUCKET_SECONDS, CACHE_BUCKET_SECONDS, CACHE_BUCKET_SECONDS,
            node, vm_uuid, selected_bucket,
        )).fetchone()

        net_count = safe_int((net or [0])[0], 0)
        perf_count = safe_int((perf or [0])[0], 0)
        if net_count <= 0 and perf_count <= 0:
            return None

        net_interval = max(1, safe_int((net or [0, 0, CACHE_BUCKET_SECONDS])[2], CACHE_BUCKET_SECONDS))
        perf_interval = max(1, safe_int((perf or [0, 0, CACHE_BUCKET_SECONDS])[2], CACHE_BUCKET_SECONDS))
        interval = max(net_interval, perf_interval)
        rx_bytes = safe_int((net or [0] * 4)[3], 0)
        tx_bytes = safe_int((net or [0] * 5)[4], 0)
        rx_packets = safe_int((net or [0] * 6)[5], 0)
        tx_packets = safe_int((net or [0] * 7)[6], 0)
        quality = network_quality_from_rank(safe_int((net or [0] * 19)[18], 0))
        net_seen = safe_int((net or [0, 0])[1], 0)
        perf_seen = safe_int((perf or [0, 0])[1], 0)

        result = {
            "selected_bucket": selected_bucket,
            "latest_bucket": latest_bucket,
            "last_push": max(net_seen, perf_seen, selected_bucket),
            "interval_seconds": interval,
            "iface": str((net or [""] * 20)[19] or iface or ""),
            "bridge": str((net or [""] * 21)[20] or bridge or ""),
            "rx_bytes": rx_bytes,
            "tx_bytes": tx_bytes,
            "rx_packets": rx_packets,
            "tx_packets": tx_packets,
            "drops": safe_int((net or [0] * 8)[7], 0),
            "errors": safe_int((net or [0] * 9)[8], 0),
            "rx_mbps": rx_bytes * 8.0 / net_interval / 1000000.0 if net_count else 0.0,
            "tx_mbps": tx_bytes * 8.0 / net_interval / 1000000.0 if net_count else 0.0,
            "rx_mbps_peak": safe_float((net or [0] * 10)[9], 0),
            "tx_mbps_peak": safe_float((net or [0] * 11)[10], 0),
            "rx_pps": rx_packets * 1.0 / net_interval if net_count else 0.0,
            "tx_pps": tx_packets * 1.0 / net_interval if net_count else 0.0,
            "rx_pps_peak": safe_float((net or [0] * 12)[11], 0),
            "tx_pps_peak": safe_float((net or [0] * 13)[12], 0),
            "rx_packet_size_avg": rx_bytes * 1.0 / rx_packets if rx_packets else 0.0,
            "tx_packet_size_avg": tx_bytes * 1.0 / tx_packets if tx_packets else 0.0,
            "sample_count": safe_int((net or [0] * 14)[13], 0),
            "sample_expected": safe_int((net or [0] * 15)[14], 0),
            "sample_max_gap": safe_float((net or [0] * 16)[15], 0),
            "seconds_over_pps": safe_int((net or [0] * 17)[16], 0),
            "seconds_over_mbps": safe_int((net or [0] * 18)[17], 0),
            "sample_quality": quality,
            "cpu_percent": safe_float((perf or [0] * 4)[3], 0),
            "vcpu_current": safe_int((perf or [0] * 5)[4], 0),
            "ram_current_kib": safe_int((perf or [0] * 6)[5], 0),
            "ram_maximum_kib": safe_int((perf or [0] * 7)[6], 0),
            "ram_rss_kib": safe_int((perf or [0] * 8)[7], 0),
            "ram_available_kib": safe_int((perf or [0] * 9)[8], 0),
            "disk_read_bps": safe_float((perf or [0] * 10)[9], 0),
            "disk_write_bps": safe_float((perf or [0] * 11)[10], 0),
        }
        result["total_bytes"] = result["rx_bytes"] + result["tx_bytes"]
        result["packets"] = result["rx_packets"] + result["tx_packets"]
        return result
    finally:
        conn.close()

def _historical_vm_latest_metric(node, vm_uuid, target_ts):
    """Compatibility wrapper retained for custom-time callers."""
    return _v5054_vm_snapshot_overview(
        node,
        vm_uuid,
        clean_period(request.args.get("period", "5m")),
        bridge=(request.args.get("bridge") or "").strip(),
        iface=(request.args.get("iface") or "").strip(),
    )

def _v5054_vm_snapshot_metric_tuple(snapshot):
    if not snapshot:
        return None
    return (
        snapshot["last_push"], snapshot["interval_seconds"],
        snapshot["iface"], snapshot["bridge"],
        snapshot["rx_mbps"], snapshot["tx_mbps"],
        snapshot["rx_pps"], snapshot["tx_pps"],
        snapshot["rx_mbps_peak"], snapshot["tx_mbps_peak"],
        snapshot["rx_pps_peak"], snapshot["tx_pps_peak"],
        snapshot["rx_packet_size_avg"], snapshot["tx_packet_size_avg"],
        snapshot["sample_count"], snapshot["sample_expected"],
        snapshot["sample_max_gap"], snapshot["seconds_over_pps"],
        snapshot["seconds_over_mbps"], snapshot["sample_quality"],
        snapshot["drops"], snapshot["errors"],
        snapshot["cpu_percent"], snapshot["vcpu_current"],
        snapshot["ram_current_kib"], snapshot["ram_maximum_kib"],
        snapshot["ram_rss_kib"], snapshot["ram_available_kib"],
        snapshot["disk_read_bps"], snapshot["disk_write_bps"],
    )

def get_vm_latest_metric(node, vm_uuid):
    period = clean_period(request.args.get("period", "5m"))
    snapshot = _v5054_vm_snapshot_overview(
        node,
        vm_uuid,
        period,
        bridge=(request.args.get("bridge") or "").strip(),
        iface=(request.args.get("iface") or "").strip(),
    )
    if snapshot:
        return _v5054_vm_snapshot_metric_tuple(snapshot)
    if _request_target_ts() is None and period == "5m":
        return _get_vm_latest_metric_v483(node, vm_uuid)
    return None

def get_vm_directional_current(node, vm_uuid):
    period = clean_period(request.args.get("period", "5m"))
    if _request_target_ts() is not None or period != "5m":
        return {}
    return _get_vm_directional_current_v483(node, vm_uuid)

def top_node_page_v484():
    period=clean_period(request.args.get("period","1h")); q=(request.args.get("q") or "").strip()
    sort_by=clean_top_node_sort(request.args.get("sort","cpu")); sort_order=clean_sort_order(request.args.get("order","desc")); limit=max(10,min(500,safe_int(request.args.get("limit"),100)))
    rows,start,end,limit=get_top_node_rows(period,q=q,sort_by=sort_by,order=sort_order,limit=limit)
    at=_request_target_ts()
    content=f"""
    <div class="card top-card"><div class="top-grid"><div><div class="label">Updated</div><div class="value">{fmt_full(end)}</div></div><div><div class="label">Timezone</div><div class="value">{display_timezone_name()}</div></div><div><div class="label">Selected Snapshot</div><div class="value">{fmt_full(start)}</div></div></div>
    <div class="label period-label">Period</div><div class="periods">{top_node_period_links(period,q=q,sort_by=sort_by,order=sort_order,limit=limit)}</div>
    <form class="search" method="get" action="{url_for('top_node_page')}"><input type="hidden" name="period" value="{escape(period)}"><input type="hidden" name="sort" value="{escape(sort_by)}"><input type="hidden" name="order" value="{escape(sort_order)}">{f'<input type="hidden" name="at" value="{escape(_datetime_local_value(at),quote=True)}">' if at else ''}<input name="q" value="{escape(q)}" placeholder="Search node / IP / MAC / VM UUID / interface"><input name="limit" value="{limit}" style="max-width:100px;min-width:80px"><button type="submit">Search</button></form></div>
    {_custom_snapshot_control('top_node_page',at,period=period,q=q or None,sort=sort_by,order=sort_order,limit=limit)}
    {top_node_table(rows,period,q,sort_by,sort_order,limit)}"""
    return page("Top Node",content)

def top_page_v484():
    period=clean_period(request.args.get("period","5m")); q=(request.args.get("q") or "").strip(); sort_by=clean_top_sort(request.args.get("sort","total")); sort_order=clean_sort_order(request.args.get("order","desc")); scope=clean_top_scope(request.args.get("scope","all")); limit=max(10,min(1000,safe_int(request.args.get("limit"),100)))
    direct_vm=resolve_direct_vm_search(q) if q else None
    if direct_vm:
        return redirect(url_for(
            "vm_page",
            node=direct_vm["node"],
            vm_uuid=direct_vm["vm_uuid"],
            bridge="",
            iface="",
            period=period,
        ))
    rows,start,end,limit=get_top_vm_rows(period,q=q,sort_by=sort_by,order=sort_order,scope=scope,limit=limit); at=_request_target_ts()
    content=f"""
    <div class="card top-card"><div class="top-grid"><div><div class="label">Latest Available</div><div class="value">{fmt_full(end)}</div></div><div><div class="label">Timezone</div><div class="value">{display_timezone_name()}</div></div><div><div class="label">Selected Snapshot</div><div class="value">{fmt_full(start)}</div></div></div>
    <div class="label period-label">Snapshot lookback</div><div class="periods">{top_period_links(period,q=q,sort_by=sort_by,order=sort_order,scope=scope,limit=limit)}</div><div class="label period-label">Scope</div><div class="scope-links">{top_scope_links(period,q,sort_by,sort_order,scope,limit)}</div>
    <form class="search" method="get" action="{url_for('top_page')}"><input type="hidden" name="period" value="{escape(period)}"><input type="hidden" name="sort" value="{escape(sort_by)}"><input type="hidden" name="order" value="{escape(sort_order)}"><input type="hidden" name="scope" value="{escape(scope)}">{f'<input type="hidden" name="at" value="{escape(_datetime_local_value(at),quote=True)}">' if at else ''}<input name="q" value="{escape(q)}" placeholder="Search node / IPv4 / MAC / VM UUID / interface"><select name="limit" aria-label="Row limit"><option value="100" {'selected' if limit==100 else ''}>100 rows</option><option value="200" {'selected' if limit==200 else ''}>200 rows</option><option value="500" {'selected' if limit==500 else ''}>500 rows</option><option value="1000" {'selected' if limit==1000 else ''}>1000 rows</option></select><button type="submit">Search</button></form></div>
    {_custom_snapshot_control('top_page',at,period=period,q=q or None,sort=sort_by,order=sort_order,scope=scope,limit=limit)}
    {top_vm_table(rows,period,q,sort_by,sort_order,scope,limit)}"""
    return page("Top VM",content)

app.view_functions["top_node_page"] = top_node_page_v484
app.view_functions["top_page"] = top_page_v484

# Preserve the custom timestamp while sorting on pages that use shared headers.
def node_sort_header(label,key,period,q,current_sort,current_order,vm_status="active"):
    current_sort=clean_node_sort(current_sort); current_order=clean_sort_order(current_order); default_order="asc" if key=="node" else "desc"; next_order=reverse_order(current_order) if current_sort==key else default_order
    arrow=" ↓" if current_sort==key and current_order=="desc" else (" ↑" if current_sort==key else "")
    kwargs={"period":period,"q":q,"sort":key,"order":next_order}; at=request.args.get("at");
    if at: kwargs["at"]=at
    return f'<a class="sort-link" href="{escape(url_for("index",**kwargs),quote=True)}">{escape(label)}{arrow}</a>'

def sort_header(label,key,node,period,q,current_sort,current_order,vm_status="active"):
    current_sort=clean_interface_sort(current_sort); current_order=clean_sort_order(current_order); next_order=reverse_order(current_order) if current_sort==key else "desc"; arrow=" ↓" if current_sort==key and current_order=="desc" else (" ↑" if current_sort==key else "")
    kwargs={"node":node,"period":period,"q":q,"sort":key,"order":next_order,"net":clean_node_net_mode(request.args.get("net","both"))}; at=request.args.get("at");
    if at: kwargs["at"]=at
    return f'<a class="sort-link" href="{escape(url_for("node_page",**kwargs),quote=True)}">{escape(label)}{arrow}</a>'

def top_sort_header(label,key,period,q,current_sort,current_order,scope,limit):
    current_sort=clean_top_sort(current_sort); current_order=clean_sort_order(current_order); next_order=reverse_order(current_order) if current_sort==key else "desc"; arrow=" ↓" if current_sort==key and current_order=="desc" else (" ↑" if current_sort==key else "")
    kwargs={"period":period,"q":q,"sort":key,"order":next_order,"scope":scope,"limit":limit}; at=request.args.get("at");
    if at: kwargs["at"]=at
    return f'<a class="sort-link" href="{escape(url_for("top_page",**kwargs),quote=True)}">{escape(label)}{arrow}</a>'

def top_node_sort_header(label,key,period,q,current_sort,current_order,limit):
    current_sort=clean_top_node_sort(current_sort); current_order=clean_sort_order(current_order); default_order="asc" if key=="node" else "desc"; next_order=reverse_order(current_order) if current_sort==key else default_order; arrow=" ↓" if current_sort==key and current_order=="desc" else (" ↑" if current_sort==key else "")
    kwargs={"period":period,"q":q,"sort":key,"order":next_order,"limit":limit}; at=request.args.get("at");
    if at: kwargs["at"]=at
    return f'<a class="sort-link" href="{escape(url_for("top_node_page",**kwargs),quote=True)}">{escape(label)}{arrow}</a>'

# Apply latest policy in this worker after the v48.8.4 overrides are defined.
try:
    _apply_abuse_settings_to_runtime(get_abuse_settings())
except Exception:
    app.logger.exception("Could not initialize v48.8.4 abuse settings")

# selected custom timestamp while switching periods/scopes.

def _at_param():
    value = (request.args.get("at") or "").strip()
    return value or None

def period_links(current, endpoint="index", node=None, q="", vm_status="active", net="both"):
    links = []
    at = _at_param()
    for period in PERIODS:
        params = {"period": period}
        if q:
            params["q"] = q
        if at:
            params["at"] = at
        if endpoint == "node_page":
            params["net"] = clean_node_net_mode(net)
            href = url_for("node_page", node=node, **params)
        else:
            href = url_for("index", **params)
        cls = "active" if period == current else ""
        links.append(f'<a class="{cls}" href="{escape(href,quote=True)}">{escape(period_label(period))}</a>')
    return "".join(links)

def top_node_period_links(current, q="", sort_by="cpu", order="desc", limit=100):
    links = []
    at = _at_param()
    for period in PERIODS:
        params = {"period":period,"q":q,"sort":sort_by,"order":order,"limit":limit}
        if at:
            params["at"] = at
        href = url_for("top_node_page", **params)
        cls = "active" if period == current else ""
        links.append(f'<a class="{cls}" href="{escape(href,quote=True)}">{escape(period_label(period))}</a>')
    return "".join(links)

def top_period_links(current, q="", sort_by="total", order="desc", scope="all", limit=100):
    links = []
    at = _at_param()
    for period in PERIODS:
        params = {"period":period,"q":q,"sort":sort_by,"order":order,"scope":scope,"limit":limit}
        if at:
            params["at"] = at
        href = url_for("top_page", **params)
        cls = "active" if period == current else ""
        links.append(f'<a class="{cls}" href="{escape(href,quote=True)}">{escape(period_label(period))}</a>')
    return "".join(links)

def top_scope_links(period, q, sort_by, order, scope, limit):
    items = []
    at = _at_param()
    for s, label in (("all", "All"), ("public", "Public only"), ("private", "Private only")):
        params = {"period":period,"q":q,"sort":sort_by,"order":order,"scope":s,"limit":limit}
        if at:
            params["at"] = at
        href = url_for("top_page", **params)
        cls = "active" if scope == s else ""
        items.append(f'<a class="{cls}" href="{escape(href,quote=True)}">{escape(label)}</a>')
    return "".join(items)

def vm_period_links(current, node, vm_uuid, bridge, iface):
    links = []
    at_text = _at_param()
    at_ts = _request_target_ts()
    for period in PERIODS:
        params = {"node":node,"vm_uuid":vm_uuid,"bridge":bridge,"iface":iface,"period":period}
        if at_text:
            params["at"] = at_text
        href = url_for("vm_page", **params)
        cls = "active" if period == current else ""
        links.append(f'<a class="{cls}" href="{escape(href,quote=True)}">{escape(period_label(period))}</a>')
    live_params = {"node":node,"vm_uuid":vm_uuid,"bridge":bridge,"iface":iface,"period":current}
    compact = f"""<form class="custom-time-form" style="display:flex;flex-basis:100%;margin-top:10px" method="get" action="{url_for('vm_page')}">
      <input type="hidden" name="node" value="{escape(node,quote=True)}"><input type="hidden" name="vm_uuid" value="{escape(vm_uuid,quote=True)}"><input type="hidden" name="bridge" value="{escape(bridge,quote=True)}"><input type="hidden" name="iface" value="{escape(iface,quote=True)}"><input type="hidden" name="period" value="{escape(current,quote=True)}">
      <label>Custom end time<input type="datetime-local" name="at" value="{escape(_datetime_local_value(at_ts),quote=True)}" required></label><button type="submit">Open time</button>{f'<a class="clear" href="{escape(url_for("vm_page",**live_params),quote=True)}">Use live</a>' if at_ts else ''}</form>"""
    return "".join(links) + compact

