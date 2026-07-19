# v48.8.3 admin-only abuse deletion, richer disk policy, readable FIFO queue
# ---------------------------------------------------------------------------

ABUSE_SETTING_DEFAULTS.update({
    "abuse_disk_read_bps": "0",
    "abuse_disk_write_bps": "0",
})
ABUSE_DISK_READ_BPS = 0.0
ABUSE_DISK_WRITE_BPS = 0.0


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
    global ABUSE_CPU_FULL_PERCENT, ABUSE_CPU_REQUIRED_SECONDS
    global ABUSE_DISK_READ_BPS, ABUSE_DISK_WRITE_BPS
    global ABUSE_DISK_BPS, ABUSE_DISK_IOPS, ABUSE_DISK_REQUIRED_SECONDS
    ABUSE_NETWORK_PPS = cfg["network_pps"] if cfg["network_enabled"] else 10**18
    ABUSE_NETWORK_REQUIRED_SECONDS = cfg["network_required_seconds"] if cfg["network_enabled"] else 10**9
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




def _disk_policy_text(cfg):
    rules = []
    if cfg.get("disk_read_bps", 0) > 0:
        rules.append(f"read ≥ {human_rate(cfg['disk_read_bps'])}")
    if cfg.get("disk_write_bps", 0) > 0:
        rules.append(f"write ≥ {human_rate(cfg['disk_write_bps'])}")
    if cfg.get("disk_bps", 0) > 0:
        rules.append(f"read + write ≥ {human_rate(cfg['disk_bps'])}")
    if cfg.get("disk_iops", 0) > 0:
        rules.append(f"total ≥ {cfg['disk_iops']:,.0f} IOPS")
    return " or ".join(rules) if rules else "no disk threshold enabled"


def _abuse_flag_labels(flags, cfg):
    result = []
    values = {x for x in str(flags or "").split(",") if x}
    if "NETWORK_RX_PPS_5M" in values:
        result.append(f"RX PPS ≥ {cfg['network_pps']:,.0f}")
    if "NETWORK_TX_PPS_5M" in values:
        result.append(f"TX PPS ≥ {cfg['network_pps']:,.0f}")
    if "CPU_30M" in values:
        result.append(f"CPU ≥ {cfg['cpu_full_percent']:.1f}%")
    if "DISK_15M" in values:
        result.append("Disk: " + _disk_policy_text(cfg))
    return result or ["-"]


def _abuse_admin_counts():
    conn = db()
    try:
        current = safe_int(conn.execute("SELECT COUNT(*) FROM vm_abuse_state WHERE is_abuse=1 AND last_seen>=?", (now_ts()-FAST_CURRENT_STALE_SECONDS,)).fetchone()[0], 0)
        total = safe_int(conn.execute("SELECT COUNT(*) FROM vm_abuse_events").fetchone()[0], 0)
        started = safe_int(conn.execute("SELECT COUNT(*) FROM vm_abuse_events WHERE event_type='started'").fetchone()[0], 0)
        recovered = safe_int(conn.execute("SELECT COUNT(*) FROM vm_abuse_events WHERE event_type='recovered'").fetchone()[0], 0)
        return current, total, started, recovered
    finally:
        conn.close()


def abuse_settings_admin_card():
    cfg = get_abuse_settings()
    msg = (request.args.get("abusemsg") or "").strip()[:700]
    current, total, started, recovered = _abuse_admin_counts()
    return f"""{_abuse_page_style()}
    <style>
      .abuse-setting-box .setting-help{{font-size:11px;color:#6b7280;font-weight:500;line-height:1.45}}
      .abuse-admin-actions{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px}}
      .abuse-policy-summary{{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:8px;margin:12px 0}}
      .abuse-policy-summary>div{{border:1px solid #e5e7eb;border-radius:9px;padding:10px;background:#fff}}
      .abuse-policy-summary small{{display:block;color:#6b7280}}
      html[data-theme=dark] .abuse-policy-summary>div{{background:#111827;border-color:#334155}}
      @media(max-width:800px){{.abuse-policy-summary{{grid-template-columns:repeat(2,minmax(120px,1fr))}}}}
    </style>
    <div class="card" id="abuse-policy-admin">
      <div class="table-title-row"><h3>VM Abuse Management</h3><div class="count-badges"><span>Policy <b>dynamic</b></span><span>Restart <b>not required</b></span><span>Agent <b>payload unchanged</b></span></div></div>
      {f'<div class="success-box">{escape(msg)}</div>' if msg else ''}
      <div class="admin-note"><b>Only Admin can delete abuse logs.</b> Viewer users can inspect Current Abuse and History, but no Clear button is rendered there. CPU and disk policy changes apply on the monitor immediately. The network PPS threshold is returned to Agent v10 on the next push, while the agent keeps sending the same metric payload.</div>
      <div class="abuse-policy-summary"><div><small>Current abuse</small><b>{current}</b></div><div><small>Saved events</small><b>{total}</b></div><div><small>Started</small><b>{started}</b></div><div><small>Recovered</small><b>{recovered}</b></div></div>
      <form method="post" action="{url_for('admin_abuse_settings')}">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="action" value="save">
        <div class="abuse-settings-grid">
          <div class="abuse-setting-box">
            <h4>Network PPS</h4>
            <label class="enable-line"><input type="checkbox" name="network_enabled" {'checked' if cfg['network_enabled'] else ''}> Enable network abuse</label>
            <label>RX or TX PPS threshold<input type="number" name="network_pps" min="1000" max="100000000" step="1000" value="{cfg['network_pps']:.0f}"></label>
            <div class="setting-help">A VM matches when either receive PPS or send PPS stays above this threshold.</div>
            <label>Required seconds in each 5-minute window<input type="number" name="network_required_seconds" min="15" max="300" step="15" value="{cfg['network_required_seconds']}"></label>
          </div>
          <div class="abuse-setting-box">
            <h4>CPU</h4>
            <label class="enable-line"><input type="checkbox" name="cpu_enabled" {'checked' if cfg['cpu_enabled'] else ''}> Enable CPU abuse</label>
            <label>CPU Full % of assigned vCPU<input type="number" name="cpu_full_percent" min="1" max="100" step="0.1" value="{cfg['cpu_full_percent']:.1f}"></label>
            <div class="setting-help">CPU Full% is normalized by assigned vCPU. Example: 360 Core% on 4 vCPU equals 90 Full%.</div>
            <label>Required consecutive minutes<input type="number" name="cpu_required_minutes" min="5" max="1440" step="5" value="{cfg['cpu_required_seconds']//60}"></label>
          </div>
          <div class="abuse-setting-box">
            <h4>Disk I/O</h4>
            <label class="enable-line"><input type="checkbox" name="disk_enabled" {'checked' if cfg['disk_enabled'] else ''}> Enable disk abuse</label>
            <label>Read threshold MiB/s <small>(0 = disabled)</small><input type="number" name="disk_read_mibps" min="0" max="100000" step="1" value="{cfg['disk_read_bps']/1024/1024:.0f}"></label>
            <label>Write threshold MiB/s <small>(0 = disabled)</small><input type="number" name="disk_write_mibps" min="0" max="100000" step="1" value="{cfg['disk_write_bps']/1024/1024:.0f}"></label>
            <label>Total read + write MiB/s <small>(0 = disabled)</small><input type="number" name="disk_mibps" min="0" max="100000" step="1" value="{cfg['disk_bps']/1024/1024:.0f}"></label>
            <label>Total read + write IOPS <small>(0 = disabled)</small><input type="number" name="disk_iops" min="0" max="10000000" step="100" value="{cfg['disk_iops']:.0f}"></label>
            <div class="setting-help">Disk uses OR logic between every non-zero threshold above.</div>
            <label>Required consecutive minutes<input type="number" name="disk_required_minutes" min="5" max="1440" step="5" value="{cfg['disk_required_seconds']//60}"></label>
          </div>
        </div>
        <div class="abuse-admin-actions"><button type="submit">Save Abuse Policy</button><a class="btn" href="{url_for('admin_abuse_page')}">Manage Abuse History</a><a class="btn" href="{url_for('vm_abuse_page')}">Open Viewer Page</a></div>
      </form>
      <form method="post" action="{url_for('admin_abuse_settings')}" onsubmit="return confirm('Reset all abuse thresholds to defaults?')" style="margin-top:8px">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="action" value="reset"><button class="btn" type="submit">Reset defaults</button>
      </form>
    </div>"""


def admin_abuse_settings_v483():
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
        f"cpu={cfg['cpu_full_percent']};cpu_seconds={cfg['cpu_required_seconds']};"
        f"disk_read={cfg['disk_read_bps']};disk_write={cfg['disk_write_bps']};"
        f"disk_total={cfg['disk_bps']};disk_iops={cfg['disk_iops']};disk_seconds={cfg['disk_required_seconds']}"
    )
    log_account_event("abuse_settings_updated", username=actor, realm="admin", role="admin", detail=detail[:1000])
    msg = "Abuse policy saved. CPU and disk are effective immediately. Agent v10 receives the network PPS threshold in its next push response; allow one complete 5-minute sample window for a clean network decision."
    return redirect(url_for("admin_abuse_page", msg=msg))


app.view_functions["admin_abuse_settings"] = admin_abuse_settings_v483


def _merge_event_abuse_cfg(current_cfg, event_cfg):
    merged = dict(current_cfg)
    if not isinstance(event_cfg, dict):
        event_cfg = {}
    merged.update({k: v for k, v in event_cfg.items() if k in merged})
    # Older event rows did not store separate read/write thresholds. Keep them
    # disabled for historical display instead of borrowing today's policy.
    if "disk_read_bps" not in event_cfg:
        merged["disk_read_bps"] = 0.0
    if "disk_write_bps" not in event_cfg:
        merged["disk_write_bps"] = 0.0
    return merged


def _public_abuse_policy(cfg):
    return f"""
      <div class="abuse-policy">
        <div><b>Network {'ON' if cfg['network_enabled'] else 'OFF'}</b><small>RX or TX ≥ {cfg['network_pps']:,.0f} PPS for {cfg['network_required_seconds']}s in a 5-minute sample window.</small></div>
        <div><b>CPU {'ON' if cfg['cpu_enabled'] else 'OFF'}</b><small>CPU Full ≥ {cfg['cpu_full_percent']:.1f}% for {cfg['cpu_required_seconds']//60} consecutive minutes.</small></div>
        <div><b>Disk {'ON' if cfg['disk_enabled'] else 'OFF'}</b><small>{escape(_disk_policy_text(cfg))} for {cfg['disk_required_seconds']//60} consecutive minutes.</small></div>
      </div>
    """


def vm_abuse_page_v483():
    tab = (request.args.get("tab") or "current").strip().lower()
    if tab not in {"current", "history"}:
        tab = "current"
    q = (request.args.get("q") or "").strip()
    limit = max(10, min(1000, safe_int(request.args.get("limit"), 200)))
    cfg = get_abuse_settings()
    default_sort = "severity" if tab == "current" else "time"
    sort_by = (request.args.get("sort") or default_sort).strip()
    order = clean_sort_order(request.args.get("order", "desc"))
    current_href = url_for("vm_abuse_page", tab="current", q=q or None, limit=limit)
    history_href = url_for("vm_abuse_page", tab="history", q=q or None, limit=limit)
    tabs = f'<div class="abuse-tabs"><a class="{"active" if tab=="current" else ""}" href="{escape(current_href,quote=True)}">Current Abuse</a><a class="{"active" if tab=="history" else ""}" href="{escape(history_href,quote=True)}">Abuse History / Logs</a></div>'
    search = f"""
      <form class="search" method="get" action="{url_for('vm_abuse_page')}">
        <input type="hidden" name="tab" value="{tab}"><input type="hidden" name="sort" value="{escape(sort_by,quote=True)}"><input type="hidden" name="order" value="{escape(order,quote=True)}">
        <input name="q" value="{escape(q,quote=True)}" placeholder="Search node / IPv4 / VM UUID / reason">
        <input name="limit" type="number" min="10" max="1000" value="{limit}" style="max-width:105px;min-width:90px"><button type="submit">Search</button>
        {f'<a class="clear" href="{url_for("vm_abuse_page",tab=tab,limit=limit)}">Clear search</a>' if q else ''}
      </form>
    """

    if tab == "current":
        rows, total, counts, sort_by, order = _current_abuse_query(q, sort_by, order, limit)
        body = ""
        for rank, r in enumerate(rows, 1):
            labels = _abuse_flag_labels(r[4], cfg)
            reasons = "".join(metric_pill(escape(x), "crit") for x in labels)
            href = url_for("vm_page", node=r[0], vm_uuid=r[1], period="1h")
            ip = compact_ipv4(r[21])
            body += f"""
            <tr><td class="num">{rank}</td><td><div class="node-name-cell"><a href="{escape(href,quote=True)}"><b>{escape(r[0])}</b></a>{f'<small class="node-ipv4">{escape(ip)}</small>' if ip else ''}</div></td>
            <td class="mono uuid-col"><span class="uuid-cell"><a href="{escape(href,quote=True)}">{escape(r[1])}</a><button type="button" class="copy-btn" data-copy="{escape(r[1],quote=True)}">⧉</button></span></td>
            <td><div class="abuse-reasons">{reasons}</div></td><td class="num"><b>{safe_float(r[5],0):.2f}x</b></td>
            <td class="num">{fmt_pps_value(r[6])}<small class="metric-subline">{safe_int(r[10],0)}s high</small></td><td class="num">{fmt_pps_value(r[7])}<small class="metric-subline">{safe_int(r[11],0)}s high</small></td>
            <td class="num">{fmt_pps_value(r[8])}</td><td class="num">{fmt_pps_value(r[9])}</td><td class="num"><b>{safe_float(r[12],0):.1f}%</b><small class="metric-subline">{safe_int(r[15],0)//60}m</small></td>
            <td class="num">{safe_int(r[14],0)}</td><td class="num">{human_rate(r[16])}</td><td class="num">{human_rate(r[17])}</td><td class="num">{safe_float(r[18],0)+safe_float(r[19],0):.1f}</td>
            <td class="num">{fmt_push(r[2])}</td><td class="num">{fmt_full(r[3]) if r[3] else '-'}</td></tr>"""
        if not body:
            body = '<tr><td colspan="16" class="empty">No VM currently satisfies a sustained abuse rule</td></tr>'
        h = lambda label,key: _abuse_sort_link(label,key,"current",q,sort_by,order,limit)
        table = f"""
        <div class="card vm-table-card"><div class="abuse-table-tools"><div><h3 style="margin:0">Current VM Abuse</h3><div class="table-hint">{total} matching VM. This page is read-only for viewer users and reads only the bounded current-state table.</div></div><div class="count-badges"><span>Network <b>{counts[0]}</b></span><span>CPU <b>{counts[1]}</b></span><span>Disk <b>{counts[2]}</b></span></div></div>
        <div class="table-wrap"><table class="abuse-fast-table"><colgroup><col style="width:48px"><col class="node-col"><col class="uuid-col"><col class="reason-col"><col class="small-col"><col class="rate-col"><col class="rate-col"><col class="rate-col"><col class="rate-col"><col class="rate-col"><col class="small-col"><col class="rate-col"><col class="rate-col"><col class="rate-col"><col class="time-col"><col class="time-col"></colgroup><thead><tr>
        <th>#</th><th>{h('NODE','node')}</th><th>{h('VM UUID','vm')}</th><th>REASON</th><th>{h('SEVERITY','severity')}</th><th>{h('RX PPS','rx_pps')}</th><th>{h('TX PPS','tx_pps')}</th><th>{h('RX PEAK','rx_peak')}</th><th>{h('TX PEAK','tx_peak')}</th><th>{h('CPU FULL%','cpu')}</th><th>{h('vCPU','vcpu')}</th><th>{h('DISK R/s','diskr')}</th><th>{h('DISK W/s','diskw')}</th><th>{h('IOPS','iops')}</th><th>{h('LAST PUSH','last_seen')}</th><th>{h('ABUSE SINCE','since')}</th></tr></thead><tbody>{body}</tbody></table></div></div>"""
    else:
        rows, total, sort_by, order = _history_abuse_query(q, sort_by, order, limit)
        body = ""
        for r in rows:
            try:
                event_cfg = json.loads(r[22] or "{}")
            except Exception:
                event_cfg = {}
            merged_cfg = _merge_event_abuse_cfg(cfg, event_cfg)
            labels = _abuse_flag_labels(r[5], merged_cfg)
            reasons = "".join(metric_pill(escape(x), "crit" if r[2] != "recovered" else "ok") for x in labels)
            href = url_for("vm_page", node=r[3], vm_uuid=r[4], period="1h")
            ip = compact_ipv4(r[24])
            body += f"""
            <tr><td class="num">{safe_int(r[0],0)}</td><td>{fmt_full(r[1])}</td><td><span class="event-badge {_abuse_type_class(r[2])}">{escape(_abuse_type_label(r[2]))}</span></td>
            <td><div class="node-name-cell"><a href="{escape(href,quote=True)}"><b>{escape(r[3])}</b></a>{f'<small class="node-ipv4">{escape(ip)}</small>' if ip else ''}</div></td><td class="mono uuid-col"><a href="{escape(href,quote=True)}">{escape(r[4])}</a></td><td><div class="abuse-reasons">{reasons}</div></td>
            <td class="num">{safe_float(r[6],0):.2f}x</td><td class="num">{fmt_pps_value(r[7])}</td><td class="num">{fmt_pps_value(r[8])}</td><td class="num">{safe_float(r[13],0):.1f}%</td><td class="num">{human_rate(safe_float(r[17],0)+safe_float(r[18],0))}</td><td>{escape(r[23] or '-')}</td></tr>"""
        if not body:
            body = '<tr><td colspan="12" class="empty">No saved abuse events</td></tr>'
        h = lambda label,key: _abuse_sort_link(label,key,"history",q,sort_by,order,limit)
        table = f"""
        <div class="card vm-table-card"><div class="abuse-table-tools"><div><h3 style="margin:0">Abuse History / Event Log</h3><div class="table-hint">{total} persistent records. Viewer access is read-only. Deletion is available only under Admin → Abuse Management.</div></div></div>
        <div class="table-wrap"><table class="abuse-history-table" style="min-width:1690px"><colgroup><col style="width:70px"><col class="time-col"><col style="width:125px"><col class="node-col"><col class="uuid-col"><col class="reason-col"><col class="small-col"><col class="rate-col"><col class="rate-col"><col class="rate-col"><col class="rate-col"><col style="width:260px"></colgroup><thead><tr>
        <th>ID</th><th>{h('TIME','time')}</th><th>{h('EVENT','type')}</th><th>{h('NODE','node')}</th><th>{h('VM UUID','vm')}</th><th>REASON</th><th>{h('SEVERITY','severity')}</th><th>{h('RX PPS','rx_pps')}</th><th>{h('TX PPS','tx_pps')}</th><th>{h('CPU','cpu')}</th><th>{h('DISK','disk')}</th><th>DETAIL</th></tr></thead><tbody>{body}</tbody></table></div></div>"""

    content = f"""{_abuse_page_style()}<div class="card top-card"><div class="overview-head"><h3>VM Abuse</h3><div class="overview-meta"><span>Current query <b>bounded state table</b></span><span>History retention <b>7 days</b></span><span>Delete <b>Admin only</b></span></div></div>{tabs}{_public_abuse_policy(cfg)}{search}</div>{table}"""
    return page("VM Abuse", content)


app.view_functions["vm_abuse_page"] = vm_abuse_page_v483


def _admin_abuse_sort_link(label, key, q, event_type, current_sort, current_order, per_page):
    next_order = reverse_order(current_order) if current_sort == key else "desc"
    arrow = ""
    if current_sort == key:
        arrow = " ↓" if current_order == "desc" else " ↑"
    href = url_for("admin_abuse_page", q=q or None, event_type=event_type or None, sort=key, order=next_order, per_page=per_page)
    return f'<a class="sort-link" href="{escape(href,quote=True)}">{escape(label)}{arrow}</a>'


def _admin_abuse_history_query(q, event_type, sort_by, order, page_no, per_page):
    allowed = {
        "time":"e.event_time", "type":"e.event_type COLLATE NOCASE", "node":"e.node COLLATE NOCASE",
        "vm":"e.vm_uuid COLLATE NOCASE", "severity":"e.severity", "rx_pps":"e.rx_pps",
        "tx_pps":"e.tx_pps", "cpu":"e.cpu_full_percent", "disk":"(e.disk_read_bps+e.disk_write_bps)",
    }
    sort_by = sort_by if sort_by in allowed else "time"
    order = clean_sort_order(order)
    where = ["1=1"]
    params = []
    if q:
        p = like_pattern(q)
        where.append("(e.node LIKE ? OR e.vm_uuid LIKE ? OR e.abuse_flags LIKE ? OR e.event_type LIKE ? OR e.detail LIKE ?)")
        params.extend([p,p,p,p,p])
    if event_type in {"started", "updated", "recovered"}:
        where.append("e.event_type=?")
        params.append(event_type)
    where_sql = " WHERE " + " AND ".join(where)
    conn = db()
    try:
        total = safe_int(conn.execute(f"SELECT COUNT(*) FROM vm_abuse_events e{where_sql}", params).fetchone()[0], 0)
        max_page = max(1, math.ceil(total / per_page))
        page_no = max(1, min(page_no, max_page))
        offset = (page_no - 1) * per_page
        rows = conn.execute(f"""
          SELECT e.id,e.event_time,e.event_type,e.node,e.vm_uuid,e.abuse_flags,e.severity,
                 e.rx_pps,e.tx_pps,e.rx_peak_pps,e.tx_peak_pps,e.seconds_over_rx_pps,e.seconds_over_tx_pps,
                 e.cpu_full_percent,e.cpu_core_percent,e.vcpu_current,e.cpu_streak_seconds,
                 e.disk_read_bps,e.disk_write_bps,e.disk_read_iops,e.disk_write_iops,e.disk_streak_seconds,
                 e.thresholds_json,e.detail
          FROM vm_abuse_events e{where_sql}
          ORDER BY {allowed[sort_by]} {order.upper()},e.id DESC LIMIT ? OFFSET ?
        """, params + [per_page, offset]).fetchall()
        return rows, total, page_no, max_page, sort_by, order
    finally:
        conn.close()


@app.route("/admin/abuse", endpoint="admin_abuse_page")
def admin_abuse_page_v483():
    deny = require_admin()
    if deny:
        return deny
    q = (request.args.get("q") or "").strip()
    event_type = (request.args.get("event_type") or "").strip().lower()
    if event_type not in {"", "started", "updated", "recovered"}:
        event_type = ""
    sort_by = (request.args.get("sort") or "time").strip()
    order = clean_sort_order(request.args.get("order", "desc"))
    per_page = max(25, min(250, safe_int(request.args.get("per_page"), 100)))
    page_no = max(1, safe_int(request.args.get("page"), 1))
    rows, total, page_no, max_page, sort_by, order = _admin_abuse_history_query(q, event_type, sort_by, order, page_no, per_page)
    msg = (request.args.get("msg") or "").strip()[:700]
    err = (request.args.get("err") or "").strip()[:700]
    cfg = get_abuse_settings()
    body = ""
    for r in rows:
        try:
            event_cfg = json.loads(r[22] or "{}")
        except Exception:
            event_cfg = {}
        merged_cfg = _merge_event_abuse_cfg(cfg, event_cfg)
        labels = _abuse_flag_labels(r[5], merged_cfg)
        reasons = "".join(metric_pill(escape(x), "crit" if r[2] != "recovered" else "ok") for x in labels)
        href = url_for("vm_page", node=r[3], vm_uuid=r[4], period="1h")
        body += f"""
        <tr><td><input form="admin-abuse-clear-selected" type="checkbox" class="abuse-event-select" name="event_ids" value="{safe_int(r[0],0)}"></td>
        <td class="num">{safe_int(r[0],0)}</td><td>{fmt_full(r[1])}</td><td><span class="event-badge {_abuse_type_class(r[2])}">{escape(_abuse_type_label(r[2]))}</span></td>
        <td><a href="{escape(href,quote=True)}"><b>{escape(r[3])}</b></a></td><td class="mono uuid-col"><a href="{escape(href,quote=True)}">{escape(r[4])}</a></td>
        <td><div class="abuse-reasons">{reasons}</div></td><td class="num">{safe_float(r[6],0):.2f}x</td><td class="num">{fmt_pps_value(r[7])}</td><td class="num">{fmt_pps_value(r[8])}</td>
        <td class="num">{safe_float(r[13],0):.1f}%</td><td class="num">{human_rate(safe_float(r[17],0)+safe_float(r[18],0))}</td><td>{escape(r[23] or '-')}</td>
        <td><form method="post" action="{url_for('clear_abuse_events')}" onsubmit="return confirm('Permanently delete this abuse event?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="mode" value="selected"><input type="hidden" name="event_ids" value="{safe_int(r[0],0)}"><button class="btn-danger" type="submit">Clear</button></form></td></tr>"""
    if not body:
        body = '<tr><td colspan="14" class="empty">No abuse history matches this filter</td></tr>'
    h = lambda label,key: _admin_abuse_sort_link(label,key,q,event_type,sort_by,order,per_page)
    base_args = {"q": q or None, "event_type": event_type or None, "sort": sort_by, "order": order, "per_page": per_page}
    prev_link = url_for("admin_abuse_page", **base_args, page=max(1,page_no-1))
    next_link = url_for("admin_abuse_page", **base_args, page=min(max_page,page_no+1))
    content = f"""
    {_abuse_page_style()}
    <style>
      .admin-abuse-head{{display:flex;gap:10px;justify-content:space-between;align-items:center;flex-wrap:wrap}}
      .admin-abuse-danger{{border:1px solid #fecaca;background:#fff7f7;border-radius:10px;padding:12px;margin-top:12px}}
      .admin-abuse-danger .bulk-bar{{margin:0}}
      .pagination{{display:flex;gap:8px;align-items:center;justify-content:flex-end;margin-top:10px}}
      html[data-theme=dark] .admin-abuse-danger{{background:#25171b;border-color:#7f1d1d}}
    </style>
    <div class="card"><div class="admin-abuse-head"><div><h3 style="margin:0">Abuse Management</h3><div class="table-hint">Policy configuration and destructive history cleanup are restricted to Admin.</div></div><div><a class="btn" href="{url_for('admin_page')}">Back to Admin</a> <a class="btn" href="{url_for('vm_abuse_page')}">Open read-only Abuse page</a></div></div>{f'<div class="success-box">{escape(msg)}</div>' if msg else ''}{f'<div class="error-box">{escape(err)}</div>' if err else ''}</div>
    {abuse_settings_admin_card()}
    <div class="card vm-table-card">
      <div class="table-title-row"><h3>Abuse History Cleanup</h3><div class="count-badges"><span>Matched <b>{total}</b></span><span>Page <b>{page_no}/{max_page}</b></span><span>Retention <b>7 days</b></span></div></div>
      <form class="search" method="get" action="{url_for('admin_abuse_page')}"><input name="q" value="{escape(q,quote=True)}" placeholder="Search node / VM UUID / reason / detail"><select name="event_type"><option value="" {'selected' if not event_type else ''}>All events</option><option value="started" {'selected' if event_type=='started' else ''}>Started</option><option value="updated" {'selected' if event_type=='updated' else ''}>Updated</option><option value="recovered" {'selected' if event_type=='recovered' else ''}>Recovered</option></select><select name="per_page"><option value="50" {'selected' if per_page==50 else ''}>50 / page</option><option value="100" {'selected' if per_page==100 else ''}>100 / page</option><option value="250" {'selected' if per_page==250 else ''}>250 / page</option></select><button type="submit">Filter</button><a class="clear" href="{url_for('admin_abuse_page')}">Clear filter</a></form>
      <div class="admin-abuse-danger">
        <form id="admin-abuse-clear-selected" class="bulk-bar" method="post" action="{url_for('clear_abuse_events')}" onsubmit="return confirm('Permanently delete selected abuse event records?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="mode" value="selected"><label><input type="checkbox" onclick="document.querySelectorAll('.abuse-event-select').forEach(cb=>cb.checked=this.checked)"> Select page</label><button class="btn-danger" type="submit">Clear selected</button></form>
        <form class="bulk-bar" method="post" action="{url_for('clear_abuse_events')}" onsubmit="return confirm('Permanently delete every abuse record matching the active filter?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="mode" value="matching"><input type="hidden" name="q" value="{escape(q,quote=True)}"><input type="hidden" name="event_type" value="{escape(event_type,quote=True)}"><label>Type <b>CLEAR MATCHING</b><input name="confirm_text" placeholder="CLEAR MATCHING" required></label><button class="btn-danger" type="submit">Clear all matching</button></form>
        <form class="bulk-bar" method="post" action="{url_for('clear_abuse_events')}" onsubmit="return confirm('Permanently delete ALL saved abuse history? Current active state is not deleted.')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="mode" value="all"><label>Type <b>CLEAR ALL ABUSE LOGS</b><input name="confirm_text" placeholder="CLEAR ALL ABUSE LOGS" required></label><button class="btn-danger" type="submit">Clear all history</button></form>
        <div class="table-hint">Clear deletes only saved event records from <b>vm_abuse_events</b>. It does not hide or reset a VM that is currently over threshold; Current Abuse remains truthful and will generate new events on future state transitions.</div>
      </div>
      <div class="table-wrap"><table class="abuse-history-table"><colgroup><col style="width:45px"><col style="width:70px"><col class="time-col"><col style="width:125px"><col class="node-col"><col class="uuid-col"><col class="reason-col"><col class="small-col"><col class="rate-col"><col class="rate-col"><col class="rate-col"><col class="rate-col"><col style="width:240px"><col style="width:80px"></colgroup><thead><tr><th></th><th>ID</th><th>{h('TIME','time')}</th><th>{h('EVENT','type')}</th><th>{h('NODE','node')}</th><th>{h('VM UUID','vm')}</th><th>REASON</th><th>{h('SEVERITY','severity')}</th><th>{h('RX PPS','rx_pps')}</th><th>{h('TX PPS','tx_pps')}</th><th>{h('CPU','cpu')}</th><th>{h('DISK','disk')}</th><th>DETAIL</th><th>ACTION</th></tr></thead><tbody>{body}</tbody></table></div>
      <div class="pagination"><a class="btn" href="{escape(prev_link,quote=True)}" {'aria-disabled="true"' if page_no<=1 else ''}>← Previous</a><span>Page <b>{page_no}</b> of <b>{max_page}</b></span><a class="btn" href="{escape(next_link,quote=True)}" {'aria-disabled="true"' if page_no>=max_page else ''}>Next →</a></div>
    </div>
    """
    return page("Abuse Management", content)


def clear_abuse_events_v483():
    deny = require_admin()
    if deny:
        return deny
    mode = (request.form.get("mode") or "selected").strip().lower()
    q = (request.form.get("q") or "").strip()
    event_type = (request.form.get("event_type") or "").strip().lower()
    confirm_text = (request.form.get("confirm_text") or "").strip()
    conn = db()
    deleted = 0
    try:
        if mode == "all":
            if confirm_text != "CLEAR ALL ABUSE LOGS":
                return redirect(url_for("admin_abuse_page", err="Confirmation text did not match."))
            cur = conn.execute("DELETE FROM vm_abuse_events")
        elif mode == "matching":
            if confirm_text != "CLEAR MATCHING":
                return redirect(url_for("admin_abuse_page", q=q or None, event_type=event_type or None, err="Confirmation text did not match."))
            where = ["1=1"]
            params = []
            if q:
                p = like_pattern(q)
                where.append("(node LIKE ? OR vm_uuid LIKE ? OR abuse_flags LIKE ? OR event_type LIKE ? OR detail LIKE ?)")
                params.extend([p,p,p,p,p])
            if event_type in {"started", "updated", "recovered"}:
                where.append("event_type=?")
                params.append(event_type)
            cur = conn.execute("DELETE FROM vm_abuse_events WHERE " + " AND ".join(where), params)
        else:
            ids = sorted({safe_int(x,0) for x in request.form.getlist("event_ids") if safe_int(x,0)>0})
            if not ids:
                return redirect(url_for("admin_abuse_page", msg="No abuse event was selected."))
            placeholders = ",".join("?" for _ in ids)
            cur = conn.execute(f"DELETE FROM vm_abuse_events WHERE id IN ({placeholders})", ids)
        deleted = max(0, safe_int(cur.rowcount, 0))
        conn.commit()
    finally:
        conn.close()
    actor = dashboard_username() or get_admin_username()
    log_account_event("abuse_history_cleared", username=actor, realm="admin", role="admin", detail=f"mode={mode};deleted={deleted};q={q};event_type={event_type}"[:700])
    return redirect(url_for("admin_abuse_page", msg=f"Deleted {deleted} abuse history record(s)."))


app.view_functions["clear_abuse_events"] = clear_abuse_events_v483


def _maintenance_action_label(action):
    return {
        "retention":"Retention cleanup", "checkpoint":"WAL checkpoint", "vacuum":"VACUUM database",
        "delete_history":"Delete old history", "delete_compact":"Delete + optimize",
        "clear_monitoring_data":"Clear monitoring data", "reset_app_data":"Reset all app data + queue", "purge_nodes":"Purge node",
        "purge_node_vms":"Purge all VM on node", "purge_vms":"Purge VM",
    }.get(str(action or ""), str(action or "-").replace("_", " ").title())


def _maintenance_target_summary(action, raw_parameters):
    try:
        params = json.loads(raw_parameters or "{}")
    except Exception:
        return "Invalid parameters"
    if action in {"purge_nodes", "purge_node_vms"}:
        nodes = [str(x) for x in (params.get("nodes") or [])]
        return f"{len(nodes)} node(s): " + ", ".join(nodes[:3]) + ("…" if len(nodes)>3 else "")
    if action == "purge_vms":
        items = params.get("vms") or []
        labels = [f"{str(x.get('vm_uuid',''))[:12]}…@{x.get('node','-')}" for x in items if isinstance(x,dict)]
        return f"{len(labels)} VM(s): " + ", ".join(labels[:3])
    if action in {"delete_history", "delete_compact"}:
        return f"Older than {safe_int(params.get('days'),7)} day(s)"
    if action == "clear_monitoring_data":
        return "Full monitoring reset" + (" + VACUUM" if params.get("compact") else "")
    if action == "reset_app_data":
        return "All operational data, logs and maintenance queue" + (" + VACUUM" if params.get("compact") else "")
    return "Database maintenance"


def _maintenance_elapsed(started_at, finished_at, created_at, status):
    now = now_ts()
    if status == "queued":
        seconds = max(0, now - safe_int(created_at, now))
        prefix = "Waiting "
    elif status == "running":
        seconds = max(0, now - safe_int(started_at or created_at, now))
        prefix = "Running "
    else:
        seconds = max(0, safe_int(finished_at or now, now) - safe_int(started_at or created_at, now))
        prefix = ""
    if seconds < 60:
        value = f"{seconds}s"
    elif seconds < 3600:
        value = f"{seconds//60}m {seconds%60}s"
    else:
        value = f"{seconds//3600}h {(seconds%3600)//60}m"
    return prefix + value


def _maintenance_friendly_message(action, status, message):
    raw = str(message or "").strip()
    if status == "queued":
        return "Waiting for the serialized maintenance lock"
    if status == "running":
        return "Worker is processing this job"
    if status == "ok":
        try:
            data = json.loads(raw)
            if action in {"purge_nodes", "purge_node_vms", "purge_vms"}:
                result = data.get("result", data)
                return f"Completed {safe_int(result.get('count'),0)} item(s)"
            if action == "clear_monitoring_data":
                return "Monitoring data cleared successfully"
            if action == "reset_app_data":
                return "All operational data and maintenance queue cleared"
            if action == "vacuum":
                return "Database VACUUM completed"
            if action == "checkpoint":
                return "WAL checkpoint completed"
            if action == "retention":
                return "Retention cleanup completed"
            return "Completed successfully"
        except Exception:
            return "Completed successfully"
    return raw[:240] or "Job failed"


def database_maintenance_card(message="", error=""):
    s = get_database_maintenance_stats()
    jobs = get_maintenance_jobs(30)
    conn = db()
    try:
        status_rows = conn.execute("SELECT status,COUNT(*) FROM maintenance_jobs GROUP BY status").fetchall()
        status_counts = {str(k or "queued"): safe_int(v,0) for k,v in status_rows}
        queued_ids = [safe_int(r[0],0) for r in conn.execute("SELECT id FROM maintenance_jobs WHERE status='queued' ORDER BY id ASC").fetchall()]
    finally:
        conn.close()
    queue_pos = {job_id: idx+1 for idx,job_id in enumerate(queued_ids)}
    active_count = status_counts.get("queued",0) + status_counts.get("running",0)
    notice = f'<div class="error-box">{escape(error)}</div>' if error else (f'<div class="success-box">{escape(message)}</div>' if message else "")
    rows = ""
    for job_id, created_at, started_at, finished_at, action, parameters, status, requested_by, job_message, unit_name in jobs:
        status = (status or "queued").lower()
        label = {"queued":"WAITING", "running":"RUNNING", "ok":"DONE", "error":"FAILED"}.get(status,status.upper())
        icon = {"queued":"◷", "running":"◉", "ok":"✓", "error":"!"}.get(status,"•")
        cls = {"queued":"yellow", "running":"yellow", "ok":"active", "error":"red"}.get(status,"yellow")
        position = f'<small class="queue-pos">Queue #{queue_pos.get(job_id,"-")}</small>' if status=="queued" else ""
        friendly = _maintenance_friendly_message(action,status,job_message)
        target = _maintenance_target_summary(action,parameters)
        raw_detail = escape((job_message or "-")[:3500])
        rows += f"""<tr class="queue-row queue-{escape(status)}"><td class="num"><b>#{job_id}</b>{position}</td><td><b>{escape(_maintenance_action_label(action))}</b><small class="queue-sub">{escape(target)}</small></td><td><span class="vm-state {cls}">{icon} {escape(label)}</span></td><td>{fmt_full(created_at)}<small class="queue-sub">{escape(_maintenance_elapsed(started_at,finished_at,created_at,status))}</small></td><td>{escape(requested_by or '-')}</td><td><b>{escape(friendly)}</b><details><summary>Technical detail</summary><pre>{raw_detail}</pre><small class="mono">{escape(unit_name or '-')}</small></details></td></tr>"""
    if not rows:
        rows = '<tr><td colspan="6" class="empty">No maintenance jobs yet</td></tr>'
    refresh_href = url_for("admin_page", q=(request.args.get("q") or None)) + "#maintenance-queue"
    auto_script = """
    <script>
    (()=>{
      const cb=document.getElementById('queue-auto-refresh');
      if(!cb)return;
      const key='bw_queue_auto_refresh';
      cb.checked=localStorage.getItem(key)==='1';
      cb.addEventListener('change',()=>localStorage.setItem(key,cb.checked?'1':'0'));
      if(cb.checked)setTimeout(()=>{if(typeof bwNavigate==='function'){bwNavigate(window.location.href,{push:false,preserveScroll:true,silent:true});}else{location.reload();}},10000);
    })();
    </script>
    """
    return f"""
    <style>
      .queue-summary{{display:grid;grid-template-columns:repeat(5,minmax(120px,1fr));gap:8px;margin:12px 0}}.queue-summary>div{{border:1px solid #e5e7eb;border-radius:9px;padding:10px;background:#fff}}.queue-summary small,.queue-sub{{display:block;color:#6b7280;font-size:11px;margin-top:3px}}.queue-table{{min-width:1160px}}.queue-table td{{vertical-align:top}}.queue-table details{{margin-top:5px}}.queue-table summary{{cursor:pointer;color:#2563eb;font-size:11px}}.queue-table pre{{white-space:pre-wrap;max-width:650px;max-height:180px;overflow:auto;font-size:10px}}.queue-pos{{display:block;color:#b45309;margin-top:3px}}.queue-running{{background:rgba(59,130,246,.05)}}.queue-error{{background:rgba(239,68,68,.04)}}html[data-theme=dark] .queue-summary>div{{background:#111827;border-color:#334155}}@media(max-width:850px){{.queue-summary{{grid-template-columns:repeat(2,minmax(110px,1fr))}}}}
    </style>
    <div class="card" id="maintenance-queue">
      <div class="table-title-row"><h3>Maintenance & Purge Queue</h3><div class="count-badges"><span>Batch limit <b>{MAX_PURGE_ITEMS_PER_JOB}</b></span><span>Execution <b>single worker</b></span><span>Active <b>{active_count}</b></span></div></div>
      {notice}
      <div class="admin-note">Exactly <b>one maintenance job</b> may be active. Bulk purge selections stay inside one worker and are processed in internal batches of at most <b>{MAX_PURGE_ITEMS_PER_JOB}</b> items, preventing a systemd-unit stampede.</div>
      <div class="queue-summary"><div><small>Waiting</small><b>{status_counts.get('queued',0)}</b></div><div><small>Running</small><b>{status_counts.get('running',0)}</b></div><div><small>Completed</small><b>{status_counts.get('ok',0)}</b></div><div><small>Failed</small><b>{status_counts.get('error',0)}</b></div><div><small>PostgreSQL data</small><b>{human(s['db_size'])}</b></div></div>
      <div class="bulk-bar"><a class="btn" href="{escape(refresh_href,quote=True)}">Refresh queue</a><label><input type="checkbox" id="queue-auto-refresh"> Auto refresh every 10s</label><span class="table-hint">PostgreSQL data {human(s['db_size'])} · WAL reserved/recycled {human(s['wal_size'])} · reusable space {human(s['reusable_bytes'])}</span></div>
      <div class="bulk-bar">
        <form class="inline-form" method="post" action="{url_for('admin_database_maintenance')}" onsubmit="return confirm('Run bounded retention now? Latest 48 hours stay at 5-minute resolution; days 3-7 keep one real snapshot per hour; older history is deleted.')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="action" value="retention"><button class="btn" type="submit">Run 2d raw / 7d retention</button></form>
        <form class="inline-form" method="post" action="{url_for('admin_database_maintenance')}" onsubmit="return confirm('Request PostgreSQL checkpoint? Normally this is not required.')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="action" value="checkpoint"><button class="btn" type="submit">Checkpoint</button></form>
        <form class="inline-form" method="post" action="{url_for('admin_database_maintenance')}" onsubmit="return confirm('VACUUM briefly stops the dashboard and rewrites the database. Continue?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="action" value="vacuum"><label>Type <b>VACUUM</b><input name="confirm_text" autocomplete="off" placeholder="VACUUM" required></label><button class="btn" type="submit">VACUUM ANALYZE</button></form>
      </div>
      <div class="card db-danger" style="margin-top:14px;margin-bottom:14px"><h3>Delete old history and optimize PostgreSQL</h3><form class="bulk-bar" method="post" action="{url_for('admin_database_maintenance')}" onsubmit="return confirm('Delete old history and run PostgreSQL VACUUM ANALYZE?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="action" value="delete_compact"><label>Delete metrics older than <select name="days"><option value="1">1 day</option><option value="3">3 days</option><option value="7" selected>7 days</option></select></label><label>Type <b>DELETE AND OPTIMIZE</b><input name="confirm_text" autocomplete="off" placeholder="DELETE AND OPTIMIZE" required></label><button class="btn-danger" type="submit">Delete + optimize</button></form></div>
      <div class="card db-danger" style="margin-top:14px;margin-bottom:14px;border-color:#ef4444"><h3>Clear all monitoring data</h3><div class="admin-note">Deletes raw/history metrics, rollups, inventory, missed cycles, node logs, current/history abuse and every fast current-cache table. Users, Admin settings, account login logs and maintenance job records are preserved.</div><form class="bulk-bar" method="post" action="{url_for('admin_database_maintenance')}" onsubmit="return confirm('Permanently clear ALL monitoring data and current dashboard caches?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="action" value="clear_monitoring_data"><label>Type <b>CLEAR ALL MONITORING DATA</b><input name="confirm_text" autocomplete="off" placeholder="CLEAR ALL MONITORING DATA" required></label><label class="enable-line"><input type="checkbox" name="compact" value="1"> VACUUM after clear</label><button class="btn-danger" type="submit">Clear all monitoring data</button></form></div>
      <div class="card db-danger reset-all-card" style="margin-top:14px;margin-bottom:14px;border:2px solid #b91c1c"><h3>Reset ALL app data + queue</h3><div class="admin-note"><b>Nuclear operational reset.</b> Deletes every monitoring/current/history row, inventory, node/IP cache, abuse state/events, policy revision history, node logs, account login logs, and all maintenance queue/history records. It preserves only dashboard users, Admin settings and the database schema so you can still log in. The dashboard becomes empty until agents push fresh data.</div><form class="bulk-bar" method="post" action="{url_for('admin_database_maintenance')}" onsubmit="return confirm('This will make the dashboard operationally empty and clear the maintenance queue. Continue?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="action" value="reset_app_data"><label>Type <b>RESET ALL APP DATA</b><input name="confirm_text" autocomplete="off" placeholder="RESET ALL APP DATA" required></label><label class="enable-line"><input type="checkbox" name="compact" value="1" checked> VACUUM after reset</label><button class="btn-danger" type="submit">Reset app data + queue</button></form></div>
      <div class="table-wrap"><table class="queue-table"><thead><tr><th>JOB</th><th>ACTION / TARGET</th><th>STATUS</th><th>TIME</th><th>REQUESTED BY</th><th>RESULT / DETAIL</th></tr></thead><tbody>{rows}</tbody></table></div>
      <div class="table-hint">Latest 30 jobs are shown. Waiting time, run time and queue position are calculated live. Technical JSON and the systemd unit are folded under each row.</div>
    </div>{auto_script}
    """


# Apply the latest persisted policy once for this worker.
try:
    _apply_abuse_settings_to_runtime(get_abuse_settings())
except Exception:
    app.logger.exception("Could not initialize v48.8.3 abuse settings")


# Do NOT scan the whole historical usage table on normal startup.
# Large history tables can make blocking backfills look like a hang. Inventory is updated
# incrementally on every /push; old rows are filtered by last_push/last_seen logic.
if BACKFILL_CACHE_ON_START:
    rebuild_cache_if_empty()
if BACKFILL_INVENTORY_ON_START and os.environ.get("BW_MAINTENANCE_IMPORT", "0") != "1":
    rebuild_inventory_from_usage()
if os.environ.get("BW_MAINTENANCE_IMPORT", "0") != "1":
    auto_cleanup_inventory()




# ---------------------------------------------------------------------------
