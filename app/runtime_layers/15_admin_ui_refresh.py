# live 5-minute cache clearing.

V490_VERSION = "48.9.0"
V490_LIVE_CACHE_TABLES = (
    "node_current_fast",
    "vm_current_fast",
    "vm_iface_current",
    "node_physical_net_latest",
    "node_host_latest",
    "node_filesystem_latest",
    "vm_disk_current",
    "node_storage_current",
    "agent_health_latest",
    "vm_latest_metrics",
)

def clear_live_5m_cache():
    """Clear only current/latest metric caches, preserving retained history."""
    conn = db()
    deleted = {}
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for table in V490_LIVE_CACHE_TABLES:
            if table not in existing:
                deleted[table] = 0
                continue
            count = safe_int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
            conn.execute(f"DELETE FROM {table}")
            deleted[table] = count
        conn.commit()
        return {"deleted": deleted, "rows": sum(deleted.values())}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

_enqueue_maintenance_job_v484 = enqueue_maintenance_job

def enqueue_maintenance_job(action, parameters, actor):
    if (action or "").strip().lower() != "clear_live_cache":
        return _enqueue_maintenance_job_v484(action, parameters, actor)

    runner = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maintenance.py")
    if not os.path.isfile(runner):
        raise RuntimeError(f"Maintenance runner is missing: {runner}")
    systemctl = shutil.which("systemctl")
    if not systemctl:
        raise RuntimeError("systemctl is not installed")
    template_path = "/etc/systemd/system/bw-monitor-maintenance@.service"
    if not os.path.isfile(template_path):
        raise RuntimeError(f"Maintenance service template is missing: {template_path}")

    conn = db()
    try:
        stale_before = now_ts() - 24 * 3600
        conn.execute("""
            UPDATE maintenance_jobs
            SET status='error', finished_at=?, message='Recovered stale queued/running maintenance job'
            WHERE status IN ('queued','running') AND created_at<?
        """, (now_ts(), stale_before))
        active_count = safe_int(conn.execute(
            "SELECT COUNT(*) FROM maintenance_jobs WHERE status IN ('queued','running')"
        ).fetchone()[0], 0)
        if active_count >= MAX_ACTIVE_MAINTENANCE_JOBS:
            raise RuntimeError(f"Maintenance queue is full ({active_count} active jobs)")
        cur = conn.execute("""
            INSERT INTO maintenance_jobs(created_at, action, parameters, status, requested_by, message)
            VALUES (?, 'clear_live_cache', ?, 'queued', ?, 'Waiting for maintenance worker')
        """, (now_ts(), json.dumps(parameters or {}, separators=(",", ":")), actor or "admin"))
        job_id = int(cur.lastrowid)
        unit_name = f"bw-monitor-maintenance@{job_id}.service"
        conn.execute("UPDATE maintenance_jobs SET unit_name=? WHERE id=?", (unit_name, job_id))
        conn.commit()
    finally:
        conn.close()

    proc = subprocess.run(
        [systemctl, "--no-block", "start", unit_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=20,
        check=False,
    )
    if proc.returncode != 0:
        msg = (proc.stdout or "systemctl start failed").strip()[:1000]
        conn = db()
        try:
            conn.execute(
                "UPDATE maintenance_jobs SET status='error', finished_at=?, message=? WHERE id=?",
                (now_ts(), msg, job_id),
            )
            conn.commit()
        finally:
            conn.close()
        raise RuntimeError(msg)
    return job_id, unit_name

_maintenance_action_label_v484 = _maintenance_action_label
_maintenance_friendly_message_v484 = _maintenance_friendly_message

def _maintenance_action_label(action):
    if action == "clear_live_cache":
        return "Clear live 5m cache"
    return _maintenance_action_label_v484(action)

def _maintenance_friendly_message(action, status, message):
    if action == "clear_live_cache" and status == "ok":
        try:
            data = json.loads(str(message or "{}"))
            rows = safe_int(((data or {}).get("clear") or {}).get("rows"), 0)
            return f"Live 5m cache cleared · {rows:,} row(s)"
        except Exception:
            return "Live 5m cache cleared"
    return _maintenance_friendly_message_v484(action, status, message)

@app.route("/admin/live-cache/clear", methods=["POST"])
def admin_clear_live_cache():
    deny = require_admin()
    if deny:
        return deny
    if (request.form.get("confirm_text") or "").strip() != "CLEAR LIVE 5M":
        return redirect(url_for("admin_page", section="maintenance", dberr="Confirmation text must be CLEAR LIVE 5M"))
    actor = dashboard_username() or get_admin_username()
    try:
        job_id, _unit = enqueue_maintenance_job("clear_live_cache", {}, actor)
        log_account_event(
            "maintenance_queued", username=actor, realm="admin", role="admin",
            detail=f"action=clear_live_cache; job_id={job_id}",
        )
        return redirect(url_for(
            "admin_page", section="maintenance",
            dbmsg=f"Live 5m cache clear queued as job #{job_id}. Active agents may repopulate fresh data on their next push."
        ) + "#maintenance-queue")
    except Exception as exc:
        app.logger.exception("Could not queue live 5m cache clear")
        return redirect(url_for("admin_page", section="maintenance", dberr=str(exc)[:700]))

# ---------- compact, aligned VM Abuse viewer ----------

def _v490_metric_pair(label_a, value_a, label_b, value_b, sub_a="", sub_b=""):
    return f"""
    <div class="metric-pair">
      <div><span>{escape(label_a)}</span><b>{value_a}</b>{f'<small>{escape(sub_a)}</small>' if sub_a else ''}</div>
      <div><span>{escape(label_b)}</span><b>{value_b}</b>{f'<small>{escape(sub_b)}</small>' if sub_b else ''}</div>
    </div>"""

def _v490_abuse_current_page(q, sort_by, order, limit, cfg):
    rows, total, counts, sort_by, order = _current_abuse_query_v484(q, sort_by, order, limit)

    def h(label, key):
        next_order = reverse_order(order) if sort_by == key else "desc"
        arrow = " ↓" if sort_by == key and order == "desc" else (" ↑" if sort_by == key else "")
        href = url_for("vm_abuse_page", tab="current", q=q or None, sort=key, order=next_order, limit=limit)
        return f'<a class="sort-link" href="{escape(href, quote=True)}">{escape(label)}{arrow}</a>'

    body = ""
    for rank, r in enumerate(rows, 1):
        labels = _abuse_flag_labels(r[4], cfg)
        reasons = "".join(metric_pill(escape(x), "crit") for x in labels)
        href = url_for("vm_page", node=r[0], vm_uuid=r[1], period="1h")
        ip = compact_ipv4(r[21])
        network = _v490_metric_pair(
            "RX AVG", f"{safe_float(r[22],0):.2f} Mbps",
            "TX AVG", f"{safe_float(r[23],0):.2f} Mbps",
            f"{fmt_pps_value(r[6])} PPS", f"{fmt_pps_value(r[7])} PPS",
        )
        peak = _v490_metric_pair(
            "RX PEAK", f"{fmt_pps_value(r[8])} PPS",
            "TX PEAK", f"{fmt_pps_value(r[9])} PPS",
            f"{safe_int(r[10],0)}s high", f"{safe_int(r[11],0)}s high",
        )
        cpu = f"""<div class="metric-stack"><b>{safe_float(r[12],0):.1f}%</b><span>{safe_int(r[14],0)} vCPU</span><small>{safe_int(r[15],0)//60}m sustained</small></div>"""
        disk_iops = safe_float(r[18],0) + safe_float(r[19],0)
        disk = _v490_metric_pair(
            "READ", human_rate(r[16]), "WRITE", human_rate(r[17]),
            f"{disk_iops:,.1f} total IOPS", f"{safe_int(r[20],0)//60}m sustained",
        )
        timeline = f"""<div class="timeline-cell"><b>{fmt_full(r[3]) if r[3] else '-'}</b><small>Started</small><span>{fmt_push(r[2])}</span><small>Last push</small></div>"""
        body += f"""
        <tr>
          <td class="rank-cell">{rank}</td>
          <td class="identity-cell">
            <div class="node-line"><a href="{escape(href,quote=True)}"><b>{escape(r[0])}</b></a>{f'<span>{escape(ip)}</span>' if ip else ''}</div>
            <div class="uuid-line"><a class="mono" href="{escape(href,quote=True)}">{escape(r[1])}</a><button type="button" class="copy-btn" data-copy="{escape(r[1],quote=True)}">⧉</button></div>
          </td>
          <td class="reason-cell"><div class="severity-line"><b>{safe_float(r[5],0):.2f}x</b><span>severity</span></div><div class="abuse-reasons">{reasons}</div></td>
          <td>{network}</td>
          <td>{peak}</td>
          <td>{cpu}</td>
          <td>{disk}</td>
          <td>{timeline}</td>
        </tr>"""
    if not body:
        body = '<tr><td colspan="8" class="empty">No VM currently satisfies a sustained abuse rule</td></tr>'

    current_href = url_for("vm_abuse_page", tab="current", q=q or None, sort=sort_by, order=order, limit=limit)
    history_href = url_for("vm_abuse_page", tab="history", q=q or None, limit=limit)
    search = f"""
    <form class="search compact-search" method="get" action="{url_for('vm_abuse_page')}">
      <input type="hidden" name="tab" value="current"><input type="hidden" name="sort" value="{escape(sort_by,quote=True)}"><input type="hidden" name="order" value="{escape(order,quote=True)}">
      <input name="q" value="{escape(q,quote=True)}" placeholder="Search node, IPv4 or VM UUID">
      <select name="limit"><option value="100" {'selected' if limit==100 else ''}>100 rows</option><option value="200" {'selected' if limit==200 else ''}>200 rows</option><option value="500" {'selected' if limit==500 else ''}>500 rows</option></select>
      <button type="submit">Search</button>{f'<a class="clear" href="{url_for("vm_abuse_page",tab="current",limit=limit)}">Reset</a>' if q else ''}
    </form>"""
    tabs = f'<div class="abuse-tabs"><a class="active" href="{escape(current_href,quote=True)}">Current Abuse</a><a href="{escape(history_href,quote=True)}">History / Logs</a></div>'
    table = f"""
    <div class="card abuse-current-card">
      <div class="section-head"><div><h3>Current VM Abuse</h3><p>Only sustained rules are shown. The query reads the bounded current-state table, not raw history.</p></div>
      <div class="count-badges"><span>All <b>{total}</b></span><span>PPS <b>{counts[0]}</b></span><span>AVG Mbps <b>{counts[1]}</b></span><span>CPU <b>{counts[2]}</b></span><span>Disk <b>{counts[3]}</b></span></div></div>
      <div class="table-wrap"><table class="abuse-v490-table"><colgroup><col class="c-rank"><col class="c-id"><col class="c-reason"><col class="c-network"><col class="c-peak"><col class="c-cpu"><col class="c-disk"><col class="c-time"></colgroup>
      <thead><tr><th>#</th><th>{h('NODE / VM','node')}</th><th>{h('REASON / SEVERITY','severity')}</th><th><div>NETWORK AVG</div><small>{h('RX Mbps','rx_mbps')} · {h('TX Mbps','tx_mbps')}</small></th><th><div>PEAK / DURATION</div><small>{h('RX PPS','rx_peak')} · {h('TX PPS','tx_peak')}</small></th><th>{h('CPU','cpu')}</th><th>{h('DISK','iops')}</th><th>{h('TIMELINE','last_seen')}</th></tr></thead>
      <tbody>{body}</tbody></table></div>
    </div>"""
    policy = _public_abuse_policy(cfg)
    return f"""
    <div class="card page-hero"><div><span class="eyebrow">ABUSE MONITORING</span><h2>VM Abuse</h2><p>Directional network, normalized CPU and sustained disk detection.</p></div><div class="hero-meta"><span>Retention <b>7 days</b></span><span>Delete <b>Admin only</b></span></div></div>
    <div class="card abuse-toolbar">{tabs}{search}</div>
    <details class="card policy-fold"><summary>Current policy</summary>{policy}</details>
    {table}"""

def vm_abuse_page_v490():
    tab = (request.args.get("tab") or "current").strip().lower()
    if tab == "history":
        return vm_abuse_page_v483()
    q = (request.args.get("q") or "").strip()
    sort_by = (request.args.get("sort") or "severity").strip().lower()
    order = clean_sort_order(request.args.get("order", "desc"))
    limit = max(10, min(1000, safe_int(request.args.get("limit"), 200)))
    cfg = get_abuse_settings()
    content = _v490_abuse_current_page(q, sort_by, order, limit, cfg)
    return page("VM Abuse", content)

app.view_functions["vm_abuse_page"] = vm_abuse_page_v490

# ---------- sectioned, faster and less cluttered Admin ----------

def _v490_admin_stats():
    conn = db()
    try:
        nodes = safe_int(conn.execute("SELECT COUNT(*) FROM node_inventory").fetchone()[0], 0)
        vms = safe_int(conn.execute("SELECT COUNT(*) FROM vm_inventory").fetchone()[0], 0)
        hidden_nodes = safe_int(conn.execute("SELECT COUNT(*) FROM node_inventory WHERE COALESCE(status,'active')='hidden' OR deleted_at IS NOT NULL").fetchone()[0], 0)
        hidden_vms = safe_int(conn.execute("SELECT COUNT(*) FROM vm_inventory WHERE COALESCE(status,'active')='hidden' OR deleted_at IS NOT NULL").fetchone()[0], 0)
        queue = safe_int(conn.execute("SELECT COUNT(*) FROM maintenance_jobs WHERE status IN ('queued','running')").fetchone()[0], 0)
        abuse = safe_int(conn.execute("SELECT COUNT(*) FROM vm_abuse_state WHERE is_abuse=1").fetchone()[0], 0)
        return {"nodes":nodes,"vms":vms,"hidden_nodes":hidden_nodes,"hidden_vms":hidden_vms,"queue":queue,"abuse":abuse}
    finally:
        conn.close()

def _v490_admin_nav(active):
    items = [
        ("overview", "Overview"), ("nodes", "Nodes"), ("vms", "VMs"), ("maintenance", "Maintenance"),
    ]
    links = []
    for key, label in items:
        cls = "active" if active == key else ""
        links.append(f'<a class="{cls}" href="{url_for("admin_page",section=key)}">{escape(label)}</a>')
    links.append(f'<a href="{url_for("admin_abuse_page")}">Abuse</a>')
    links.append(f'<a href="{url_for("admin_users_page")}">Users</a>')
    links.append(f'<a href="{url_for("admin_logs_page",type="account")}">Logs</a>')
    return '<nav class="admin-tabs">' + ''.join(links) + '</nav>'

def _v490_pager(section, q, page_no, max_page, per_page):
    if max_page <= 1:
        return ""
    prev_url = url_for("admin_page", section=section, q=q or None, page=max(1,page_no-1), per_page=per_page)
    next_url = url_for("admin_page", section=section, q=q or None, page=min(max_page,page_no+1), per_page=per_page)
    prev_cls = "disabled" if page_no <= 1 else ""
    next_cls = "disabled" if page_no >= max_page else ""
    return f'<div class="pagination"><a class="btn {prev_cls}" href="{escape(prev_url,quote=True)}">← Previous</a><span>Page <b>{page_no}</b> / <b>{max_page}</b></span><a class="btn {next_cls}" href="{escape(next_url,quote=True)}">Next →</a></div>'

def _v490_admin_nodes(q, page_no, per_page):
    where = ""
    params = []
    if q:
        p = like_pattern(q)
        where = """WHERE (ni.node LIKE ? OR EXISTS (SELECT 1 FROM node_bridge_addresses_latest b WHERE b.node=ni.node AND (COALESCE(b.primary_ipv4,'') LIKE ? OR COALESCE(b.ipv4_json,'[]') LIKE ?)) OR EXISTS (SELECT 1 FROM vm_inventory v WHERE v.node=ni.node AND (v.vm_uuid LIKE ? OR COALESCE(v.last_iface,'') LIKE ? OR COALESCE(v.last_bridge,'') LIKE ?)))"""
        params = [p,p,p,p,p,p]
    conn = db()
    try:
        total = safe_int(conn.execute(f"SELECT COUNT(*) FROM node_inventory ni {where}", params).fetchone()[0],0)
        max_page = max(1, math.ceil(total/per_page))
        page_no = max(1,min(page_no,max_page))
        rows = conn.execute(f"""
          WITH bridge_ip AS (
            SELECT node,MAX(CASE WHEN LOWER(role)='public' THEN primary_ipv4 ELSE '' END) public_ipv4,
                        MAX(CASE WHEN LOWER(role)='private' THEN primary_ipv4 ELSE '' END) private_ipv4
            FROM node_bridge_addresses_latest GROUP BY node
          ), vm_count AS (
            SELECT node,COUNT(DISTINCT vm_uuid) vm_count FROM vm_inventory
            WHERE COALESCE(status,'active')!='hidden' AND deleted_at IS NULL GROUP BY node
          )
          SELECT ni.node,ni.status,ni.last_push,ni.deleted_at,COALESCE(vc.vm_count,0),COALESCE(b.public_ipv4,''),COALESCE(b.private_ipv4,'')
          FROM node_inventory ni LEFT JOIN bridge_ip b ON b.node=ni.node LEFT JOIN vm_count vc ON vc.node=ni.node
          {where} ORDER BY ni.node COLLATE NOCASE LIMIT ? OFFSET ?
        """, params+[per_page,(page_no-1)*per_page]).fetchall()
        return rows,total,page_no,max_page
    finally:
        conn.close()

def _v490_admin_vms(q, page_no, per_page):
    where = ""
    params = []
    if q:
        p = like_pattern(q)
        where = """WHERE (vi.node LIKE ? OR vi.vm_uuid LIKE ? OR COALESCE(vi.last_iface,'') LIKE ? OR COALESCE(vi.last_bridge,'') LIKE ? OR EXISTS (SELECT 1 FROM node_bridge_addresses_latest b WHERE b.node=vi.node AND (COALESCE(b.primary_ipv4,'') LIKE ? OR COALESCE(b.ipv4_json,'[]') LIKE ?)))"""
        params = [p,p,p,p,p,p]
    conn = db()
    try:
        total = safe_int(conn.execute(f"SELECT COUNT(*) FROM vm_inventory vi {where}",params).fetchone()[0],0)
        max_page = max(1, math.ceil(total/per_page))
        page_no = max(1,min(page_no,max_page))
        rows = conn.execute(f"""
          WITH bridge_ip AS (
            SELECT node,MAX(CASE WHEN LOWER(role)='public' THEN primary_ipv4 ELSE '' END) public_ipv4,
                        MAX(CASE WHEN LOWER(role)='private' THEN primary_ipv4 ELSE '' END) private_ipv4
            FROM node_bridge_addresses_latest GROUP BY node
          )
          SELECT vi.node,vi.vm_uuid,vi.status,vi.last_seen,vi.last_bridge,vi.last_iface,vi.deleted_at,COALESCE(b.public_ipv4,''),COALESCE(b.private_ipv4,'')
          FROM vm_inventory vi LEFT JOIN bridge_ip b ON b.node=vi.node {where}
          ORDER BY vi.node COLLATE NOCASE,CASE WHEN COALESCE(vi.status,'active')='hidden' THEN 1 ELSE 0 END,vi.last_seen DESC
          LIMIT ? OFFSET ?
        """, params+[per_page,(page_no-1)*per_page]).fetchall()
        return rows,total,page_no,max_page
    finally:
        conn.close()

def _v490_action_menu(forms):
    return f'<details class="action-menu"><summary>Actions</summary><div>{forms}</div></details>'

def _v490_admin_overview(stats):
    s = get_database_maintenance_stats()
    cards = [
        ("Nodes", f"{stats['nodes']:,}", f"{stats['hidden_nodes']:,} hidden", url_for("admin_page",section="nodes")),
        ("VMs", f"{stats['vms']:,}", f"{stats['hidden_vms']:,} hidden", url_for("admin_page",section="vms")),
        ("Current abuse", f"{stats['abuse']:,}", "Open policy and history", url_for("admin_abuse_page")),
        ("Queue", f"{stats['queue']:,}", "Waiting or running", url_for("admin_page",section="maintenance")),
        ("PostgreSQL data", human(s['db_size']), f"WAL reserve {human(s['wal_size'])}", url_for("admin_page",section="maintenance")),
    ]
    html = ''.join(f'<a class="admin-kpi" href="{escape(href,quote=True)}"><span>{escape(label)}</span><b>{escape(value)}</b><small>{escape(sub)}</small></a>' for label,value,sub,href in cards)
    quick = [
        ("Abuse policy", "Thresholds, duration and saved events", url_for("admin_abuse_page")),
        ("User management", "Viewer and admin accounts", url_for("admin_users_page")),
        ("Account logs", "Authentication and admin activity", url_for("admin_logs_page",type="account")),
        ("Node logs", "Node-side events and changes", url_for("admin_logs_page",type="node")),
        ("System health", "Database, service and data freshness", url_for("admin_system_health_page")),
        ("Change password", "Update the Admin password", url_for("admin_change_password")),
    ]
    quick_html = ''.join(f'<a class="quick-link-card" href="{escape(href,quote=True)}"><b>{escape(label)}</b><span>{escape(desc)}</span><i>→</i></a>' for label,desc,href in quick)
    return f"""
    <div class="admin-kpis">{html}</div>
    <div class="card"><div class="section-head"><div><h3>Admin tools</h3><p>Choose one area instead of loading every management table at once.</p></div></div><div class="quick-link-grid">{quick_html}</div></div>
    <details class="card admin-fold"><summary>System health details</summary><div class="fold-content">{monitor_system_health_card()}</div></details>
    """

def _v490_admin_nodes_section(q, page_no, per_page):
    rows,total,page_no,max_page = _v490_admin_nodes(q,page_no,per_page)
    body=""
    for node,status,last_push,deleted_at,vm_count,pub,priv in rows:
        hidden=(status=='hidden') or bool(deleted_at)
        forms = admin_form(url_for('admin_delete_node'),'Hide',{'node':node,'mode':'soft'},danger=True,confirm='Hide node from dashboard? Raw usage is kept.')
        forms += admin_form(url_for('admin_restore_node'),'Restore',{'node':node},danger=False,confirm='Restore node to dashboard?')
        forms += admin_form(url_for('admin_purge_node_vms'),'Purge VMs',{'node':node},danger=True,confirm='Purge every VM and VM history under this node?')
        forms += admin_form(url_for('admin_delete_node'),'Purge node',{'node':node,'mode':'purge'},danger=True,confirm='Permanently purge this node and all monitoring data?')
        body += f"""<tr class="{'stale-row' if hidden else ''}"><td><input class="node-select" form="bulk-nodes-form" type="checkbox" name="nodes" value="{escape(node,quote=True)}"></td><td><b>{escape(node)}</b><small class="row-sub">{escape(status or 'active')}</small></td><td class="mono">{escape(compact_ipv4(pub) or '-')}</td><td class="mono">{escape(compact_ipv4(priv) or '-')}</td><td class="num"><b>{safe_int(vm_count,0)}</b></td><td>{fmt_full(last_push)}</td><td>{_v490_action_menu(forms)}</td></tr>"""
    if not body: body='<tr><td colspan="7" class="empty">No nodes match this filter</td></tr>'
    return f"""
    <div class="card"><div class="section-head"><div><h3>Node management</h3><p>{total:,} matching node(s). Bulk purge uses one exclusive job with internal batches of {MAX_PURGE_ITEMS_PER_JOB}.</p></div></div>
    <form class="search" method="get"><input type="hidden" name="section" value="nodes"><input name="q" value="{escape(q,quote=True)}" placeholder="Search node, IP, MAC, VM, bridge or interface"><select name="per_page"><option value="100" {'selected' if per_page==100 else ''}>100 rows</option><option value="200" {'selected' if per_page==200 else ''}>200 rows</option></select><button>Search</button>{f'<a class="clear" href="{url_for("admin_page",section="nodes")}">Reset</a>' if q else ''}</form>
    <form id="bulk-nodes-form" method="post" action="{url_for('admin_bulk_nodes')}" onsubmit="return confirm('Apply selected node action?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><div class="bulk-bar compact-bulk"><label><input type="checkbox" onclick="document.querySelectorAll('.node-select').forEach(cb=>cb.checked=this.checked)"> Select page</label><select name="action"><option value="hide">Hide</option><option value="restore">Restore</option><option value="purge_vms">Purge all VMs</option><option value="purge">Purge node</option></select><button class="btn-danger">Apply</button></div></form>
    <div class="table-wrap"><table class="admin-clean-table"><thead><tr><th></th><th>NODE / STATUS</th><th>PUBLIC IP</th><th>PRIVATE IP</th><th>VM</th><th>LAST PUSH</th><th>ACTION</th></tr></thead><tbody>{body}</tbody></table></div>{_v490_pager('nodes',q,page_no,max_page,per_page)}</div>"""

def _v490_admin_vms_section(q,page_no,per_page):
    rows,total,page_no,max_page=_v490_admin_vms(q,page_no,per_page)
    body=""; stale_before=now_ts()-VM_STALE_SECONDS
    for node,vm_uuid,status,last_seen,bridge,iface,deleted_at,pub,priv in rows:
        hidden=(last_seen or 0)<stale_before or deleted_at or status=='hidden'
        forms=admin_form(url_for('admin_delete_vm'),'Hide',{'node':node,'vm_uuid':vm_uuid,'mode':'soft'},danger=True,confirm='Hide VM from dashboard? Raw usage is kept.')
        forms+=admin_form(url_for('admin_restore_vm'),'Restore',{'node':node,'vm_uuid':vm_uuid},danger=False,confirm='Restore VM to dashboard?')
        forms+=admin_form(url_for('admin_delete_vm'),'Purge VM',{'node':node,'vm_uuid':vm_uuid,'mode':'purge'},danger=True,confirm='Permanently purge this VM and all history?')
        value=escape(f"{node}\t{vm_uuid}",quote=True)
        body+=f"""<tr class="{'stale-row' if hidden else ''}"><td><input class="vm-select" form="bulk-vms-form" type="checkbox" name="vms" value="{value}"></td><td><b>{escape(node)}</b><small class="row-sub">{escape(compact_ipv4(pub) or '-')}</small></td><td class="mono"><span class="uuid-cell">{escape(vm_uuid)}<button type="button" class="copy-btn" data-copy="{escape(vm_uuid,quote=True)}">⧉</button></span></td><td><b>{escape(status or 'active')}</b><small class="row-sub">{fmt_push(last_seen)}</small></td><td>{escape(bridge or '-')}<small class="row-sub">{escape(iface or '-')}</small></td><td>{_v490_action_menu(forms)}</td></tr>"""
    if not body: body='<tr><td colspan="6" class="empty">No VMs match this filter</td></tr>'
    return f"""
    <div class="card"><div class="section-head"><div><h3>VM management</h3><p>{total:,} matching VM(s). Results are paginated so Admin stays responsive with tens of thousands of VMs.</p></div></div>
    <form class="search" method="get"><input type="hidden" name="section" value="vms"><input name="q" value="{escape(q,quote=True)}" placeholder="Search node, IP, MAC, VM UUID, bridge or interface"><select name="per_page"><option value="100" {'selected' if per_page==100 else ''}>100 rows</option><option value="200" {'selected' if per_page==200 else ''}>200 rows</option><option value="500" {'selected' if per_page==500 else ''}>500 rows</option></select><button>Search</button>{f'<a class="clear" href="{url_for("admin_page",section="vms")}">Reset</a>' if q else ''}</form>
    <form id="bulk-vms-form" method="post" action="{url_for('admin_bulk_vms')}" onsubmit="return confirm('Apply selected VM action?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><div class="bulk-bar compact-bulk"><label><input type="checkbox" onclick="document.querySelectorAll('.vm-select').forEach(cb=>cb.checked=this.checked)"> Select page</label><select name="action"><option value="hide">Hide</option><option value="restore">Restore</option><option value="purge">Purge</option></select><button class="btn-danger">Apply</button></div></form>
    <div class="table-wrap"><table class="admin-clean-table"><thead><tr><th></th><th>NODE</th><th>VM UUID</th><th>STATUS / LAST SEEN</th><th>BRIDGE / IFACE</th><th>ACTION</th></tr></thead><tbody>{body}</tbody></table></div>{_v490_pager('vms',q,page_no,max_page,per_page)}</div>"""

def _v490_live_cache_card():
    """The old CLEAR LIVE 5M rescue control is intentionally hidden.

    Clearing current caches does not reduce ongoing CPU/storage work and causes
    a needless empty-dashboard interval followed by a synchronized repopulation
    spike. Targeted purge and normal stale-row cleanup are the supported tools.
    """
    return ""

def admin_page_v490():
    deny=require_admin()
    if deny: return deny
    section=(request.args.get('section') or 'overview').strip().lower()
    if section not in {'overview','nodes','vms','maintenance'}: section='overview'
    q=(request.args.get('q') or '').strip()
    page_no=max(1,safe_int(request.args.get('page'),1))
    per_page=max(25,min(500,safe_int(request.args.get('per_page'),200)))
    dbmsg=(request.args.get('dbmsg') or '').strip()[:700]
    dberr=(request.args.get('dberr') or '').strip()[:700]
    stats=_v490_admin_stats()
    if section=='overview': section_html=_v490_admin_overview(stats)
    elif section=='nodes': section_html=_v490_admin_nodes_section(q,page_no,per_page)
    elif section=='vms': section_html=_v490_admin_vms_section(q,page_no,per_page)
    else: section_html=_v490_live_cache_card()+database_maintenance_card(dbmsg,dberr)
    content=f"""
    <div class="card admin-hero"><div><span class="eyebrow">CONTROL CENTER</span><h2>Administration</h2><p>Inventory, policy, users and maintenance are separated into focused sections.</p></div><div class="admin-user-actions"><a class="btn" href="{url_for('index')}">Dashboard</a><a class="btn" href="{url_for('admin_logout')}">Logout</a></div></div>
    {_v490_admin_nav(section)}
    {section_html}
    """
    return page('Admin',content)

app.view_functions['admin_page']=admin_page_v490

# ---------- global visual refresh ----------
_page_v484 = page

V490_GLOBAL_CSS = r"""
<style id="v490-theme">
:root{--bg:#f4f7fb;--panel:#fff;--panel-soft:#f8fafc;--line:#e5eaf1;--text:#142033;--muted:#667085;--brand:#2563eb;--brand-2:#1d4ed8;--danger:#dc2626;--shadow:0 10px 30px rgba(15,23,42,.055)}
*{box-sizing:border-box}body{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif!important;background:var(--bg)!important;color:var(--text)!important;letter-spacing:-.005em}header{position:sticky;top:0;z-index:80;padding:13px 24px!important;background:rgba(15,23,42,.96)!important;backdrop-filter:blur(14px);box-shadow:0 1px 0 rgba(255,255,255,.08)}header h2{margin:0;font-size:18px}.brand{font-weight:850;letter-spacing:-.03em}.wrap{max-width:1880px;margin:0 auto;padding:24px!important}.main-nav{display:flex;gap:5px;flex-wrap:wrap}.main-nav a{padding:8px 11px;border-radius:8px;color:#cbd5e1!important;text-decoration:none;font-size:13px;font-weight:750}.main-nav a:hover{background:rgba(255,255,255,.1);color:#fff!important}.card{background:var(--panel)!important;border:1px solid var(--line)!important;border-radius:15px!important;box-shadow:var(--shadow)!important;padding:18px!important;margin-bottom:16px!important}.card h2,.card h3,.card h4{letter-spacing:-.025em}.card h2{margin:0;font-size:25px}.card h3{font-size:17px;margin-bottom:11px}.label,.table-hint,.admin-note,.breadcrumb{color:var(--muted)!important}.table-wrap{border-color:var(--line)!important;border-radius:12px!important;background:var(--panel);overflow:auto}.table-wrap table{border-collapse:separate;border-spacing:0;width:100%}th{background:#f7f9fc!important;color:#475467!important;font-size:11px!important;letter-spacing:.055em;font-weight:850!important;padding:11px 12px!important}td{padding:11px 12px!important;border-bottom:1px solid #edf0f4!important;font-size:13px}tr:last-child td{border-bottom:0!important}tbody tr:hover{background:#f8fbff!important}.sort-link{text-decoration:none!important;color:#344054!important}.sort-link:hover{color:var(--brand)!important}.btn,button,.search button,.bulk-bar button{border-radius:9px!important;min-height:36px;padding:8px 12px!important;font-weight:800!important;font-size:12px!important;box-shadow:none!important}.btn,button:not(.btn-danger):not(.copy-btn){border:1px solid #d7deea;background:#fff;color:#344054}.search button,button[type=submit]:not(.btn-danger){background:var(--brand)!important;border-color:var(--brand)!important;color:#fff!important}.btn-danger{background:#fff1f2!important;color:#b42318!important;border:1px solid #fecdd3!important}.btn-danger:hover{background:#ffe4e6!important}.search,.bulk-bar{gap:8px!important;align-items:center}.search input,.search select,input,select{border-radius:9px!important;border:1px solid #d7deea!important;background:#fff;min-height:38px;padding:8px 10px!important}.periods,.scope-links{display:flex;gap:6px;flex-wrap:wrap}.periods a,.scope-links a{border-radius:9px!important;padding:7px 11px!important;margin:0!important;border-color:#dbe2ec!important}.periods a.active,.scope-links a.active{background:var(--brand)!important;border-color:var(--brand)!important}.count-badges{gap:6px!important}.count-badges span,.overview-meta span{border-radius:999px!important;padding:6px 10px!important;background:#f8fafc!important;border-color:#e5eaf1!important}.section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:12px}.section-head h3{margin:0 0 4px}.section-head p{margin:0;color:var(--muted);font-size:12px;line-height:1.55}.page-hero,.admin-hero{display:flex;justify-content:space-between;align-items:center;gap:20px;background:linear-gradient(135deg,#fff 0%,#f5f9ff 100%)!important}.page-hero p,.admin-hero p{margin:6px 0 0;color:var(--muted)}.eyebrow{display:block;color:var(--brand);font-size:10px;font-weight:900;letter-spacing:.14em;margin-bottom:5px}.hero-meta,.admin-user-actions{display:flex;gap:8px;flex-wrap:wrap}.hero-meta span,.status-chip{padding:7px 10px;border-radius:999px;background:#eff6ff;border:1px solid #bfdbfe;color:#1e40af;font-size:11px}.abuse-toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}.abuse-toolbar .abuse-tabs{margin:0}.compact-search{margin:0!important}.policy-fold>summary,.admin-fold>summary{cursor:pointer;font-weight:850;list-style:none}.policy-fold>summary::-webkit-details-marker,.admin-fold>summary::-webkit-details-marker{display:none}.policy-fold>summary:after,.admin-fold>summary:after{content:'+';float:right;color:var(--brand)}.policy-fold[open]>summary:after,.admin-fold[open]>summary:after{content:'−'}.policy-fold .abuse-policy{margin-top:15px}.abuse-v490-table{min-width:1480px;table-layout:fixed}.abuse-v490-table .c-rank{width:48px}.abuse-v490-table .c-id{width:300px}.abuse-v490-table .c-reason{width:265px}.abuse-v490-table .c-network{width:210px}.abuse-v490-table .c-peak{width:210px}.abuse-v490-table .c-cpu{width:125px}.abuse-v490-table .c-disk{width:210px}.abuse-v490-table .c-time{width:170px}.abuse-v490-table th small{display:block;margin-top:4px;font-size:10px;letter-spacing:0;text-transform:none}.rank-cell{text-align:center;color:#98a2b3;font-weight:850}.identity-cell{overflow:hidden}.node-line{display:flex;gap:8px;align-items:center;margin-bottom:7px}.node-line span{font-size:11px;color:var(--muted);background:#f2f4f7;border-radius:6px;padding:3px 6px}.uuid-line{display:flex;align-items:center;gap:6px;min-width:0}.uuid-line>a{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#475467!important;font-size:11px}.severity-line{display:flex;align-items:baseline;gap:6px;margin-bottom:7px}.severity-line b{font-size:18px;color:#b42318}.severity-line span{font-size:10px;color:var(--muted);text-transform:uppercase}.metric-pair{display:grid;grid-template-columns:1fr 1fr;gap:8px}.metric-pair>div{min-width:0}.metric-pair span{display:block;color:var(--muted);font-size:9px;font-weight:850;letter-spacing:.07em}.metric-pair b{display:block;margin-top:3px;font-size:12px;white-space:nowrap}.metric-pair small,.metric-stack small,.timeline-cell small{display:block;color:var(--muted);font-size:10px;margin-top:3px}.metric-stack b{display:block;font-size:17px}.metric-stack span{display:block;font-size:11px;color:#475467}.timeline-cell b,.timeline-cell span{display:block;font-size:11px}.timeline-cell small{margin:2px 0 6px}.abuse-reasons{gap:4px!important}.abuse-reasons .metric-pill{font-size:10px!important;padding:3px 6px!important}.admin-tabs{display:flex;gap:6px;overflow:auto;padding:5px;background:#eaf0f8;border:1px solid #dbe3ef;border-radius:12px;margin:0 0 16px}.admin-tabs a{white-space:nowrap;padding:9px 13px;border-radius:8px;color:#475467!important;text-decoration:none;font-size:12px;font-weight:850}.admin-tabs a:hover{background:rgba(255,255,255,.7)}.admin-tabs a.active{background:#fff;color:var(--brand)!important;box-shadow:0 1px 4px rgba(15,23,42,.08)}.admin-kpis{display:grid;grid-template-columns:repeat(5,minmax(145px,1fr));gap:10px;margin-bottom:16px}.admin-kpi{display:block;text-decoration:none!important;color:inherit!important;background:#fff;border:1px solid var(--line);border-radius:13px;padding:15px;box-shadow:var(--shadow)}.admin-kpi span,.admin-kpi small{display:block;color:var(--muted);font-size:11px}.admin-kpi b{display:block;font-size:23px;margin:5px 0 3px}.admin-kpi:hover{border-color:#93c5fd;transform:translateY(-1px)}.quick-link-grid{display:grid;grid-template-columns:repeat(3,minmax(180px,1fr));gap:10px}.quick-link-card{position:relative;display:block;text-decoration:none!important;color:inherit!important;border:1px solid var(--line);border-radius:11px;padding:14px;background:#fbfcfe}.quick-link-card b,.quick-link-card span{display:block}.quick-link-card span{margin-top:4px;color:var(--muted);font-size:11px}.quick-link-card i{position:absolute;right:13px;top:14px;color:var(--brand);font-style:normal}.fold-content>.card{box-shadow:none!important;margin:14px 0 0!important}.admin-clean-table{min-width:1040px}.admin-clean-table .row-sub{display:block;color:var(--muted);font-size:10px;margin-top:4px}.action-menu{position:relative}.action-menu summary{display:inline-flex;cursor:pointer;padding:6px 9px;border:1px solid #d7deea;border-radius:8px;background:#fff;font-weight:800;font-size:11px}.action-menu>div{position:static;min-width:145px;margin-top:6px;padding:7px;background:#fff;border:1px solid var(--line);border-radius:10px;box-shadow:0 8px 20px rgba(15,23,42,.10)}.action-menu form{display:block!important;margin:4px 0!important}.action-menu button{width:100%;text-align:left}.compact-bulk{padding:9px 0!important;margin:0!important}.pagination{display:flex;justify-content:flex-end;align-items:center;gap:9px;margin-top:12px;color:var(--muted);font-size:12px}.pagination .disabled{pointer-events:none;opacity:.45}.info-strip{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.info-strip span{padding:7px 9px;border-radius:8px;background:#f8fafc;border:1px solid var(--line);font-size:11px}.danger-inline{display:flex;gap:9px;align-items:end;flex-wrap:wrap;margin-top:12px}.danger-inline label{display:grid;gap:5px;color:var(--muted);font-size:11px}.live-cache-card{border-color:#fed7aa!important;background:linear-gradient(135deg,#fff,#fffaf5)!important}.db-danger{border-radius:12px!important}.queue-summary>div{border-radius:11px!important}.queue-table{min-width:1040px!important}.queue-table td{font-size:12px}.theme-switch{border-radius:9px!important}
html[data-theme=dark]{--bg:#07101d;--panel:#0f1b2c;--panel-soft:#132238;--line:#22324a;--text:#e7edf7;--muted:#94a3b8;--shadow:0 12px 32px rgba(0,0,0,.22)}html[data-theme=dark] body{background:var(--bg)!important;color:var(--text)!important}html[data-theme=dark] .card,html[data-theme=dark] .admin-kpi{background:var(--panel)!important;border-color:var(--line)!important}html[data-theme=dark] th{background:#142238!important;color:#b6c2d3!important}html[data-theme=dark] td{border-bottom-color:#1d2b40!important}html[data-theme=dark] tbody tr:hover{background:#132238!important}html[data-theme=dark] .page-hero,html[data-theme=dark] .admin-hero{background:linear-gradient(135deg,#0f1b2c,#10233d)!important}html[data-theme=dark] .admin-tabs{background:#0b1728;border-color:#22324a}html[data-theme=dark] .admin-tabs a.active,html[data-theme=dark] .quick-link-card,html[data-theme=dark] .action-menu summary,html[data-theme=dark] .action-menu>div{background:#132238!important;border-color:#2b3d57!important;color:#e7edf7!important}html[data-theme=dark] .admin-tabs a:hover{background:#132238}html[data-theme=dark] .node-line span,html[data-theme=dark] .info-strip span{background:#132238;border-color:#22324a}html[data-theme=dark] .live-cache-card{background:linear-gradient(135deg,#241b13,#172033)!important;border-color:#7c4a1d!important}html[data-theme=dark] input,html[data-theme=dark] select{background:#0b1728!important;color:#e7edf7!important;border-color:#2b3d57!important}
@media(max-width:1100px){.admin-kpis{grid-template-columns:repeat(3,minmax(140px,1fr))}.quick-link-grid{grid-template-columns:repeat(2,minmax(170px,1fr))}}@media(max-width:760px){.wrap{padding:14px!important}.page-hero,.admin-hero{align-items:flex-start;flex-direction:column}.admin-kpis{grid-template-columns:repeat(2,minmax(130px,1fr))}.quick-link-grid{grid-template-columns:1fr}.abuse-toolbar{align-items:stretch}.compact-search{width:100%}.compact-search input{min-width:100%}.metric-pair{grid-template-columns:1fr}.admin-tabs{margin-left:-2px;margin-right:-2px}}
</style>
"""

def page(title, content):
    response = _page_v484(title, content)
    try:
        html = response.get_data(as_text=True)
        endpoint = (request.endpoint or "page").replace("_", "-")
        html = html.replace("</head>", V490_GLOBAL_CSS + "</head>", 1)
        html = html.replace("<body>", f'<body class="app-v490 endpoint-{escape(endpoint,quote=True)}">', 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.9.0 visual layer")
    return response

