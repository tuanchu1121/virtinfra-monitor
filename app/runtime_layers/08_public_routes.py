@app.route("/login", methods=["GET", "POST"])
def dashboard_login():
    next_url = safe_next_url(request.args.get("next") or request.form.get("next") or url_for("index"))
    error = ""

    if dashboard_allowed():
        return redirect(next_url)

    bootstrap_dashboard_admin_from_settings()
    if not admin_is_configured() and dashboard_user_count() == 0:
        return redirect(url_for("admin_setup"))

    username_value = clean_username(request.form.get("username") or "")
    if request.method == "POST":
        password = request.form.get("password") or ""
        user = get_dashboard_user(username_value)
        if not user:
            log_account_event("login_failed", username=username_value, realm="dashboard", detail="unknown user")
            error = "Invalid username or password."
        else:
            user_id, username, password_hash, role, is_active, created_at, updated_at, last_login = user
            role = clean_role(role)
            if not is_active:
                log_account_event("login_failed", username=username, realm="dashboard", role=role, detail="disabled user")
                error = "This user is disabled."
            elif not check_password_hash(password_hash, password):
                log_account_event("login_failed", username=username, realm="dashboard", role=role, detail="bad password")
                error = "Invalid username or password."
            else:
                session.clear()
                session["dashboard_authenticated"] = True
                session["dashboard_user_id"] = int(user_id)
                session["dashboard_username"] = username
                session["dashboard_role"] = role
                if role == "admin":
                    session["admin_authenticated"] = True
                    session["admin_username"] = username
                session["csrf_token"] = secrets.token_urlsafe(32)
                update_dashboard_user_login(user_id)
                log_account_event("login_success", username=username, realm="dashboard", role=role)
                return redirect(next_url)

    error_html = f'<div class="error-box">{escape(error)}</div>' if error else ""
    no_users_note = ""
    if dashboard_user_count() == 0:
        no_users_note = f'<div class="admin-note">No dashboard users exist yet. Login to Admin first and create users.</div>'
    content = f"""
    <div class="card login-card">
        <h3>Dashboard Login</h3>
        {error_html}
        {no_users_note}
        <form method="post" action="{url_for('dashboard_login')}">
            <input type="hidden" name="next" value="{escape(next_url, quote=True)}">
            <label>Username</label>
            <input name="username" value="{escape(username_value)}" autocomplete="username" autofocus>
            <label>Password</label>
            <input name="password" type="password" autocomplete="current-password">
            <button type="submit">Login</button>
        </form>
    </div>
    """
    return page("Dashboard Login", content)

@app.route("/logout")
def dashboard_logout():
    username = dashboard_username()
    role = dashboard_role()
    if username:
        log_account_event("logout", username=username, realm="dashboard", role=role)
    session.clear()
    return redirect(url_for("dashboard_login"))

@app.route("/")
def index():
    period = clean_period(request.args.get("period", "5m"))
    q = (request.args.get("q") or "").strip()
    sort_by = clean_node_sort(request.args.get("sort", "node"))
    sort_order = clean_sort_order(request.args.get("order", "asc"))

    # UUID or unique VM-interface searches should open the VM itself, not only
    # reduce the dashboard to the node that contains that VM.
    direct_vm = resolve_direct_vm_search(q)
    if direct_vm:
        return redirect(url_for(
            "vm_page",
            node=direct_vm["node"],
            vm_uuid=direct_vm["vm_uuid"],
            bridge=direct_vm["bridge"],
            iface=direct_vm["iface"],
            period=period,
        ))

    rows, start, end = get_node_rows(period, q, sort_by=sort_by, order=sort_order)

    content = f"""
    {range_card(period, start, end, q=q, endpoint="index")}
    {node_table(rows, sort_by=sort_by, order=sort_order)}
    """
    return page("VirtInfra Monitor", content)

@app.route("/health/nodes")
def node_health_page():
    q = (request.args.get("q") or "").strip()
    sort_by = clean_node_health_sort(request.args.get("sort", "status"))
    sort_order = clean_sort_order(request.args.get("order", "asc"))
    rows = get_node_health_rows(q=q, sort_by=sort_by, order=sort_order)
    end = now_ts()
    start = end - 86400
    search_action = url_for("node_health_page")
    content = f"""
    <div class="card top-card">
        <div class="top-grid">
            <div>
                <div class="label">Updated</div>
                <div class="value">{fmt_full(end)}</div>
            </div>
            <div>
                <div class="label">Timezone</div>
                <div class="value">{display_timezone_name()}</div>
            </div>
            <div>
                <div class="label">Health Rule</div>
                <div class="value">≤12m green / 12-25m yellow / &gt;25m red</div>
            </div>
        </div>
        <form class="search" method="get" action="{search_action}">
            <input type="hidden" name="sort" value="{escape(sort_by)}">
            <input type="hidden" name="order" value="{escape(sort_order)}">
            <input name="q" value="{escape(q)}" placeholder="Search node / IP / MAC / VM UUID / interface">
            <button type="submit">Search</button>
            {f'<a class="clear" href="{url_for("node_health_page", sort=sort_by, order=sort_order)}">Clear</a>' if q else ''}
        </form>
    </div>
    {node_health_table(rows, q=q, sort_by=sort_by, order=sort_order)}
    """
    return page("Node Health", content)

@app.route("/health/nodes/<path:node>/misses")
def node_missed_detail_page(node):
    history = get_node_missed_history(node, request.args.get("limit", 500))
    current_cycles = history["current_cycles"]
    rows_html = ""

    if current_cycles > 0 and history["last_push"]:
        missed_from = history["last_push"] + STATUS_PUSH_SECONDS
        current_duration = max(0, now_ts() - missed_from)
        rows_html += f"""
        <tr class="warn">
            <td><span class="health-pill warning">CURRENT</span></td>
            <td>{fmt_full(history["last_push"])}</td>
            <td>{fmt_full(missed_from)}</td>
            <td>-</td>
            <td><b>{current_cycles}</b></td>
            <td>{human_age(current_duration)}</td>
            <td>live</td>
        </tr>
        """

    for (
        event_id, last_good_push, missed_from, recovered_at,
        cycles, gap_seconds, source,
    ) in history["events"]:
        rows_html += f"""
        <tr>
            <td><span class="health-pill healthy">RECOVERED</span></td>
            <td>{fmt_full(last_good_push)}</td>
            <td>{fmt_full(missed_from)}</td>
            <td>{fmt_full(recovered_at)}</td>
            <td><b>{safe_int(cycles, 0)}</b></td>
            <td>{human_age(gap_seconds)}</td>
            <td>{escape(source or "live")}</td>
        </tr>
        """

    if not rows_html:
        rows_html = '<tr><td colspan="7" class="empty">No recorded missed cycles</td></tr>'

    public_ip_html = (
        f'<small class="node-ipv4" title="Public IPv4">{escape(history["public_ipv4"])}</small>'
        if history["public_ipv4"] else ""
    )
    back_href = url_for("node_health_page")
    content = f"""
    <div class="card page-title-card">
        <div class="breadcrumb"><a href="{escape(back_href, quote=True)}">Node Health</a> / Missed cycles</div>
        <div class="page-title-row">
            <div class="node-name-cell">
                <h3>{escape(node)}</h3>
                {public_ip_html}
            </div>
            <div class="count-badges">
                <span>Total cycles <b>{history["total_cycles"]}</b></span>
                <span>Incidents <b>{history["total_incidents"]}</b></span>
                <span>Current <b>{history["current_cycles"]}</b></span>
                <span>Recovered cycles <b>{history["completed_cycles"]}</b></span>
            </div>
        </div>
    </div>

    <div class="card">
        <div class="table-title-row">
            <h3>Missed-cycle history</h3>
            <div class="count-badges">
                <span>Last push <b>{fmt_full(history["last_push"])}</b></span>
                <span>Last recovery <b>{fmt_full(history["last_recovered"])}</b></span>
            </div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>STATUS</th>
                    <th>LAST GOOD PUSH</th>
                    <th>MISSED FROM</th>
                    <th>RECOVERED AT</th>
                    <th>CYCLES</th>
                    <th>GAP</th>
                    <th>SOURCE</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
        <div class="table-hint">
            Existing history is backfilled from available raw 5-minute snapshots.
            New recovery events are stored persistently even after the node returns Online.
        </div>
    </div>
    """
    return page(f"Missed Cycles - {node}", content)

@app.route("/top/nodes")
def top_node_page():
    period = clean_period(request.args.get("period", "5m"))
    q = (request.args.get("q") or "").strip()
    sort_by = clean_top_node_sort(request.args.get("sort", "cpu"))
    sort_order = clean_sort_order(request.args.get("order", "desc"))
    limit = max(10, min(500, safe_int(request.args.get("limit"), 100)))
    rows, start, end, limit = get_top_node_rows(period, q=q, sort_by=sort_by, order=sort_order, limit=limit)

    content = f"""
    <div class="card top-card">
        <div class="top-grid">
            <div>
                <div class="label">Updated</div>
                <div class="value">{fmt_full(end)}</div>
            </div>
            <div>
                <div class="label">Timezone</div>
                <div class="value">{display_timezone_name()}</div>
            </div>
            <div>
                <div class="label">Selected Snapshot</div>
                <div class="value">{fmt_full(start) if int(start or 0) == int(end or 0) else (fmt_range(start) + ' <span class="arrow">→</span> ' + fmt_range(end))}</div>
            </div>
        </div>
        <div class="label period-label">Period</div>
        <div class="periods">{top_node_period_links(period, q=q, sort_by=sort_by, order=sort_order, limit=limit)}</div>
        <form class="search" method="get" action="{url_for('top_node_page')}">
            <input type="hidden" name="period" value="{escape(period)}">
            <input type="hidden" name="sort" value="{escape(sort_by)}">
            <input type="hidden" name="order" value="{escape(sort_order)}">
            <input name="q" value="{escape(q)}" placeholder="Search node / IP / MAC / VM UUID / interface">
            <input name="limit" value="{limit}" style="max-width:100px; min-width:80px" placeholder="Limit">
            <button type="submit">Search</button>
            {f'<a class="clear" href="{url_for("top_node_page", period=period, sort=sort_by, order=sort_order, limit=limit)}">Clear</a>' if q else ''}
        </form>
    </div>
    {top_node_table(rows, period, q, sort_by, sort_order, limit)}
    """
    return page("Top Node", content)

def _abuse_rss_percent(rss_kib, assigned_kib):
    assigned = float(assigned_kib or 0)
    if assigned <= 0:
        return 0.0
    return max(0.0, float(rss_kib or 0) * 100.0 / assigned)

def _abuse_reason(label, value, level="crit"):
    return metric_pill(f"{escape(label)} {escape(value)}", level)

def _abuse_sort_value(row, sort_by):
    if sort_by == "node":
        return (row.get("node") or "").lower()
    if sort_by == "vm":
        return (row.get("vm_uuid") or "").lower()
    key_map = {
        "severity": "severity", "total": "total", "avg_mbps": "avg_mbps",
        "peak_mbps": "peak_mbps", "avg_pps": "avg_pps", "peak_pps": "peak_pps",
        "cpu": "cpu_percent", "core_cpu": "core_cpu_percent", "ram": "ram_pct",
        "last_push": "last_push", "drops": "drops", "errors": "errors",
    }
    return float(row.get(key_map.get(sort_by, "severity")) or 0)

def get_vm_abuse_rows(q="", sort_by="severity", order="desc", limit=200):
    """Return current abuse candidates from the latest real bucket of every node.

    The implementation deliberately uses two small independent queries and merges
    them in Python. It avoids the fragile positional-parameter UNION query that
    caused /abuse/vms to return Internal Server Error in v48.6.1.
    """
    auto_cleanup_inventory()
    sort_by = clean_abuse_sort(sort_by)
    order = clean_sort_order(order)
    limit = max(10, min(1000, safe_int(limit, 200)))
    conn = db()
    try:
        network_rows = conn.execute("""
            WITH latest_net AS (
                SELECT node, MAX(bucket) AS bucket
                FROM node_stats
                GROUP BY node
            )
            SELECT
                ns.node,
                ns.vm_uuid,
                COUNT(DISTINCT ns.bridge || ':' || ns.iface) AS iface_count,
                SUM(CASE WHEN ns.bridge=? THEN COALESCE(ns.rx_delta,0)+COALESCE(ns.tx_delta,0) ELSE 0 END) AS public_total,
                SUM(CASE WHEN ns.bridge=? THEN COALESCE(ns.rx_delta,0)+COALESCE(ns.tx_delta,0) ELSE 0 END) AS private_total,
                SUM(COALESCE(ns.rx_delta,0)+COALESCE(ns.tx_delta,0)) AS total,
                SUM((COALESCE(ns.rx_delta,0)+COALESCE(ns.tx_delta,0))*8.0 /
                    MAX(COALESCE(ns.interval_seconds,1),1) / 1000000.0) AS avg_mbps,
                MAX(MAX(COALESCE(ns.rx_mbps_peak,0),COALESCE(ns.tx_mbps_peak,0))) AS peak_mbps,
                SUM(COALESCE(ns.rx_packets_delta,0)+COALESCE(ns.tx_packets_delta,0))*1.0 /
                    MAX(MAX(COALESCE(ns.interval_seconds,?)),1) AS avg_pps,
                MAX(MAX(COALESCE(ns.rx_pps_peak,0),COALESCE(ns.tx_pps_peak,0))) AS peak_pps,
                SUM(COALESCE(ns.rx_drop_delta,0)+COALESCE(ns.tx_drop_delta,0)) AS drops,
                SUM(COALESCE(ns.rx_error_delta,0)+COALESCE(ns.tx_error_delta,0)) AS errors,
                SUM(COALESCE(ns.network_sample_count,0)) AS sample_count,
                SUM(COALESCE(ns.network_sample_expected,0)) AS sample_expected,
                MAX(COALESCE(ns.network_sample_max_gap_seconds,0)) AS sample_max_gap,
                MAX(CASE UPPER(COALESCE(ns.network_sample_quality,'LEGACY'))
                    WHEN 'POOR' THEN 3 WHEN 'DEGRADED' THEN 2 WHEN 'GOOD' THEN 1 ELSE 0 END) AS sample_quality_rank,
                MAX(ns.last_push) AS last_push
            FROM node_stats ns
            JOIN latest_net ln ON ln.node=ns.node AND ln.bucket=ns.bucket
            LEFT JOIN node_inventory ni ON ni.node=ns.node
            LEFT JOIN vm_inventory vi ON vi.node=ns.node AND vi.vm_uuid=ns.vm_uuid
            WHERE (ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))
              AND COALESCE(vi.status,'active')!='hidden'
            GROUP BY ns.node, ns.vm_uuid
        """, (PUBLIC_BRIDGE, PRIVATE_BRIDGE, CACHE_BUCKET_SECONDS)).fetchall()

        perf_rows = conn.execute("""
            WITH latest_perf AS (
                SELECT node, MAX(bucket) AS bucket
                FROM vm_perf_stats
                GROUP BY node
            )
            SELECT
                p.node,
                p.vm_uuid,
                MAX(COALESCE(p.cpu_percent,0)) AS cpu_percent,
                MAX(COALESCE(p.vcpu_current,0)) AS vcpu_current,
                MAX(COALESCE(p.ram_rss_kib,0)) AS ram_rss_kib,
                MAX(COALESCE(p.ram_current_kib,0)) AS ram_current_kib,
                MAX(COALESCE(p.disk_read_delta,0)*1.0/MAX(COALESCE(p.interval_seconds,?),1)) AS disk_read_bps,
                MAX(COALESCE(p.disk_write_delta,0)*1.0/MAX(COALESCE(p.interval_seconds,?),1)) AS disk_write_bps,
                MAX(p.time) AS last_push
            FROM vm_perf_stats p
            JOIN latest_perf lp ON lp.node=p.node AND lp.bucket=p.bucket
            LEFT JOIN node_inventory ni ON ni.node=p.node
            LEFT JOIN vm_inventory vi ON vi.node=p.node AND vi.vm_uuid=p.vm_uuid
            WHERE (ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))
              AND COALESCE(vi.status,'active')!='hidden'
            GROUP BY p.node, p.vm_uuid
        """, (CACHE_BUCKET_SECONDS, CACHE_BUCKET_SECONDS)).fetchall()

        ip_rows = conn.execute("""
            SELECT node,
                   MAX(CASE WHEN LOWER(role)='public' THEN primary_ipv4 ELSE '' END) AS public_ipv4,
                   MAX(CASE WHEN LOWER(role)='private' THEN primary_ipv4 ELSE '' END) AS private_ipv4
            FROM node_bridge_addresses_latest
            GROUP BY node
        """).fetchall()
    finally:
        conn.close()

    merged = {}
    for row in network_rows:
        key = (str(row[0] or ""), str(row[1] or ""))
        merged[key] = {
            "node": key[0], "vm_uuid": key[1], "iface_count": int(row[2] or 0),
            "public_total": int(row[3] or 0), "private_total": int(row[4] or 0),
            "total": int(row[5] or 0), "avg_mbps": float(row[6] or 0),
            "peak_mbps": float(row[7] or 0), "avg_pps": float(row[8] or 0),
            "peak_pps": float(row[9] or 0), "drops": int(row[10] or 0),
            "errors": int(row[11] or 0), "sample_count": int(row[12] or 0),
            "sample_expected": int(row[13] or 0), "sample_max_gap": float(row[14] or 0),
            "sample_quality_rank": int(row[15] or 0), "last_push": int(row[16] or 0),
            "cpu_percent": 0.0, "vcpu_current": 0, "core_cpu_percent": 0.0,
            "ram_rss_kib": 0.0, "ram_current_kib": 0.0, "ram_pct": 0.0,
            "disk_read_bps": 0.0, "disk_write_bps": 0.0,
            "public_ipv4": "", "private_ipv4": "",
        }

    for row in perf_rows:
        key = (str(row[0] or ""), str(row[1] or ""))
        item = merged.setdefault(key, {
            "node": key[0], "vm_uuid": key[1], "iface_count": 0,
            "public_total": 0, "private_total": 0, "total": 0,
            "avg_mbps": 0.0, "peak_mbps": 0.0, "avg_pps": 0.0, "peak_pps": 0.0,
            "drops": 0, "errors": 0, "sample_count": 0, "sample_expected": 0,
            "sample_max_gap": 0.0, "sample_quality_rank": 0, "last_push": 0,
            "public_ipv4": "", "private_ipv4": "",
        })
        item["cpu_percent"] = float(row[2] or 0)
        item["vcpu_current"] = int(row[3] or 0)
        item["core_cpu_percent"] = vm_core_cpu_percent(item["cpu_percent"], item["vcpu_current"])
        item["ram_rss_kib"] = float(row[4] or 0)
        item["ram_current_kib"] = float(row[5] or 0)
        item["ram_pct"] = _abuse_rss_percent(item["ram_rss_kib"], item["ram_current_kib"])
        item["disk_read_bps"] = float(row[6] or 0)
        item["disk_write_bps"] = float(row[7] or 0)
        item["last_push"] = max(int(item.get("last_push") or 0), int(row[8] or 0))

    node_ips = {str(r[0] or ""): (str(r[1] or ""), str(r[2] or "")) for r in ip_rows}
    q_lower = (q or "").strip().lower()
    result = []
    for item in merged.values():
        item["public_ipv4"], item["private_ipv4"] = node_ips.get(item["node"], ("", ""))
        if q_lower:
            haystack = " ".join([
                item.get("node", ""), item.get("vm_uuid", ""),
                item.get("public_ipv4", ""), item.get("private_ipv4", ""),
            ]).lower()
            if q_lower not in haystack:
                continue

        reasons = []
        severity_parts = []
        if item["avg_mbps"] >= ABUSE_AVG_MBPS > 0:
            reasons.append(_abuse_reason("AVG Mbps", f"{item['avg_mbps']:.2f}"))
            severity_parts.append(item["avg_mbps"] / ABUSE_AVG_MBPS)
        if item["peak_mbps"] >= ABUSE_PEAK_MBPS > 0:
            reasons.append(_abuse_reason("PEAK Mbps", f"{item['peak_mbps']:.2f}"))
            severity_parts.append(item["peak_mbps"] / ABUSE_PEAK_MBPS)
        if item["avg_pps"] >= ABUSE_AVG_PPS > 0:
            reasons.append(_abuse_reason("AVG PPS", fmt_pps_value(item["avg_pps"])))
            severity_parts.append(item["avg_pps"] / ABUSE_AVG_PPS)
        if item["peak_pps"] >= ABUSE_PEAK_PPS > 0:
            reasons.append(_abuse_reason("PEAK PPS", fmt_pps_value(item["peak_pps"])))
            severity_parts.append(item["peak_pps"] / ABUSE_PEAK_PPS)
        # cpu_percent is normalized across the VM's assigned vCPUs. 90% means
        # the VM is using about 90% of its total assigned CPU capacity.
        if item.get("cpu_percent", 0) >= ABUSE_CPU_FULL_PERCENT > 0:
            reasons.append(_abuse_reason("CPU Full", f"{item['cpu_percent']:.1f}%"))
            severity_parts.append(item["cpu_percent"] / ABUSE_CPU_FULL_PERCENT)
        if item.get("ram_pct", 0) >= ABUSE_RAM_RSS_PERCENT > 0:
            reasons.append(_abuse_reason("RAM RSS", f"{item['ram_pct']:.1f}%"))
            severity_parts.append(item["ram_pct"] / ABUSE_RAM_RSS_PERCENT)
        if not reasons:
            continue
        item["reasons"] = reasons
        item["severity"] = max(severity_parts) if severity_parts else 1.0
        result.append(item)

    reverse = order == "desc"
    result.sort(
        key=lambda item: (_abuse_sort_value(item, sort_by), item.get("total", 0), item.get("node", ""), item.get("vm_uuid", "")),
        reverse=reverse,
    )
    return result[:limit], len(result), limit

def abuse_sort_header(label, key, q, current_sort, current_order, limit):
    current_sort = clean_abuse_sort(current_sort)
    current_order = clean_sort_order(current_order)
    default_order = "asc" if key in {"node", "vm"} else "desc"
    next_order = reverse_order(current_order) if current_sort == key else default_order
    arrow = ""
    if current_sort == key:
        arrow = " ↓" if current_order == "desc" else " ↑"
    href = url_for("vm_abuse_page", q=q, sort=key, order=next_order, limit=limit)
    return f'<a class="sort-link" href="{escape(href, quote=True)}">{escape(label)}{arrow}</a>'

def vm_abuse_table(rows, total_matches, q, sort_by, order, limit):
    h = lambda label, key: abuse_sort_header(label, key, q, sort_by, order, limit)
    body = ""
    for rank, item in enumerate(rows, 1):
        node = item["node"]
        vm_uuid = item["vm_uuid"]
        href = url_for("node_page", node=node, period="1h", q=vm_uuid)
        public_ip = compact_ipv4(item.get("public_ipv4"))
        ip_html = f'<small class="node-ipv4">{escape(public_ip)}</small>' if public_ip else ""
        sample = network_sample_badge(
            network_quality_from_rank(item.get("sample_quality_rank", 0)),
            item.get("sample_count", 0), item.get("sample_expected", 0), item.get("sample_max_gap", 0),
        )
        ram_html = fmt_ram_pair(item.get("ram_rss_kib"), item.get("ram_current_kib"))
        if item.get("ram_current_kib"):
            ram_html += f'<small class="metric-subline">{item.get("ram_pct", 0):.1f}% RSS</small>'
        body += f"""
        <tr>
            <td class="num">{rank}</td>
            <td class="mono"><div class="node-name-cell"><a href="{escape(href, quote=True)}"><b>{escape(node)}</b></a>{ip_html}</div></td>
            <td class="mono"><span class="uuid-cell"><a href="{escape(href, quote=True)}" title="{escape(vm_uuid)}">{escape(vm_uuid)}</a><button type="button" class="copy-btn" data-copy="{escape(vm_uuid)}" title="Copy UUID">⧉</button></span></td>
            <td><div class="abuse-reasons">{''.join(item.get('reasons', []))}</div></td>
            <td class="num"><b>{item.get('severity', 0):.2f}x</b></td>
            <td class="num">{human(item.get('total'))}</td>
            <td class="num">{item.get('avg_mbps', 0):.2f}</td>
            <td class="num"><b>{item.get('peak_mbps', 0):.2f}</b></td>
            <td class="num">{fmt_pps_value(item.get('avg_pps'))}</td>
            <td class="num"><b>{fmt_pps_value(item.get('peak_pps'))}</b></td>
            <td class="num sample-cell">{sample}</td>
            <td class="num"><b>{item.get('cpu_percent', 0):.1f}%</b><small class="metric-subline">{item.get('core_cpu_percent', 0):.1f}% core</small></td>
            <td class="num">{int(item.get('vcpu_current') or 0)}</td>
            <td class="num ram-cell">{ram_html}</td>
            <td class="num">{human_rate(item.get('disk_read_bps'))}</td>
            <td class="num">{human_rate(item.get('disk_write_bps'))}</td>
            <td class="num">{fmt_push(item.get('last_push'))}</td>
            <td class="num">{int(item.get('drops') or 0)}</td>
            <td class="num">{int(item.get('errors') or 0)}</td>
        </tr>"""
    if not body:
        body = '<tr><td colspan="19" class="empty">No VM currently exceeds the configured abuse thresholds</td></tr>'
    return f"""
    <div class="card vm-table-card abuse-card">
        <div class="table-title-row"><h3>VM Abuse</h3><div class="count-badges"><span>Matched <b>{total_matches}</b></span><span>Shown <b>{len(rows)}</b></span><span>Sort <b>{escape(sort_by)} {escape(order)}</b></span></div></div>
        <div class="table-wrap">
        <table class="table-abuse">
            <colgroup>
                <col class="ab-rank"><col class="ab-node"><col class="ab-uuid"><col class="ab-reason"><col class="ab-severity">
                <col class="ab-total"><col class="ab-rate"><col class="ab-rate"><col class="ab-pps"><col class="ab-pps"><col class="ab-sample">
                <col class="ab-cpu"><col class="ab-vcpu"><col class="ab-ram"><col class="ab-disk"><col class="ab-disk"><col class="ab-push"><col class="ab-small"><col class="ab-small">
            </colgroup>
            <thead><tr>
                <th>#</th><th>{h('NODE','node')}</th><th>{h('VM UUID','vm')}</th><th>ABUSE REASON</th><th class="num-head">{h('SEVERITY','severity')}</th>
                <th class="num-head">{h('TOTAL/5m','total')}</th><th class="num-head">{h('AVG Mbps','avg_mbps')}</th><th class="num-head">{h('PEAK Mbps','peak_mbps')}</th>
                <th class="num-head">{h('AVG PPS','avg_pps')}</th><th class="num-head">{h('PEAK PPS','peak_pps')}</th><th class="num-head">SAMPLE</th>
                <th class="num-head">{h('CPU Full%','cpu')}</th><th class="num-head">vCPU</th><th class="num-head">{h('RAM RSS%','ram')}</th>
                <th class="num-head">DISK R/s</th><th class="num-head">DISK W/s</th><th class="num-head">{h('PUSH','last_push')}</th><th class="num-head">{h('DROPS','drops')}</th><th class="num-head">{h('ERR','errors')}</th>
            </tr></thead>
            <tbody>{body}</tbody>
        </table>
        </div>
        <div class="table-hint">CPU Full% is utilization across all assigned vCPUs and triggers at {ABUSE_CPU_FULL_PERCENT:.1f}%. RAM uses RSS / assigned memory and triggers at {ABUSE_RAM_RSS_PERCENT:.1f}%. Network thresholds: AVG {ABUSE_AVG_MBPS:.0f} Mbps / {fmt_pps_value(ABUSE_AVG_PPS)}, PEAK {ABUSE_PEAK_MBPS:.0f} Mbps / {fmt_pps_value(ABUSE_PEAK_PPS)}.</div>
    </div>"""

@app.route("/abuse/vms")
def vm_abuse_page():
    q = (request.args.get("q") or "").strip()
    sort_by = clean_abuse_sort(request.args.get("sort", "severity"))
    sort_order = clean_sort_order(request.args.get("order", "desc"))
    limit = max(10, min(1000, safe_int(request.args.get("limit"), 200)))
    try:
        rows, total_matches, limit = get_vm_abuse_rows(q=q, sort_by=sort_by, order=sort_order, limit=limit)
        network_count = sum(1 for r in rows if r.get("avg_mbps",0) >= ABUSE_AVG_MBPS or r.get("peak_mbps",0) >= ABUSE_PEAK_MBPS or r.get("avg_pps",0) >= ABUSE_AVG_PPS or r.get("peak_pps",0) >= ABUSE_PEAK_PPS)
        cpu_count = sum(1 for r in rows if r.get("cpu_percent",0) >= ABUSE_CPU_FULL_PERCENT)
        ram_count = sum(1 for r in rows if r.get("ram_pct",0) >= ABUSE_RAM_RSS_PERCENT)
        content = f"""
        <div class="card top-card abuse-summary-card">
            <div class="overview-head"><h3>Current VM Abuse</h3><div class="overview-meta"><span>Source <b>latest real snapshot per node</b></span><span>Timezone <b>{display_timezone_name()}</b></span></div></div>
            <div class="traffic-grid abuse-grid">
                <div class="traffic-box traffic-box-main"><div class="traffic-title">Matched</div><div class="traffic-total">{total_matches}</div></div>
                <div class="traffic-box"><div class="traffic-title">Network</div><div class="traffic-total">{network_count}</div></div>
                <div class="traffic-box"><div class="traffic-title">CPU ≥ {ABUSE_CPU_FULL_PERCENT:.0f}%</div><div class="traffic-total">{cpu_count}</div></div>
                <div class="traffic-box"><div class="traffic-title">RAM ≥ {ABUSE_RAM_RSS_PERCENT:.0f}%</div><div class="traffic-total">{ram_count}</div></div>
            </div>
            <form class="search" method="get" action="{url_for('vm_abuse_page')}">
                <input type="hidden" name="sort" value="{escape(sort_by)}">
                <input type="hidden" name="order" value="{escape(sort_order)}">
                <input name="q" value="{escape(q)}" placeholder="Search node / IPv4 / VM UUID">
                <input name="limit" value="{limit}" style="max-width:100px; min-width:80px" placeholder="Limit">
                <button type="submit">Search</button>
                {f'<a class="clear" href="{url_for("vm_abuse_page", sort=sort_by, order=sort_order, limit=limit)}">Clear</a>' if q else ''}
            </form>
        </div>
        {vm_abuse_table(rows, total_matches, q, sort_by, sort_order, limit)}
        """
        return page("VM Abuse", content)
    except Exception as exc:
        app.logger.exception("VM Abuse page failed")
        content = f"""
        <div class="card"><h3>VM Abuse</h3><div class="error-box"><b>VM Abuse query failed:</b> {escape(type(exc).__name__)}: {escape(str(exc))}</div><div class="table-hint">Check journalctl -u bw-monitor -n 100 --no-pager for the full traceback.</div></div>
        """
        return page("VM Abuse", content), 500

@app.route("/top")
def top_page():
    period = clean_period(request.args.get("period", "5m"))
    q = (request.args.get("q") or "").strip()
    sort_by = clean_top_sort(request.args.get("sort", "total"))
    sort_order = clean_sort_order(request.args.get("order", "desc"))
    scope = clean_top_scope(request.args.get("scope", "all"))
    limit = max(10, min(1000, safe_int(request.args.get("limit"), 100)))
    rows, start, end, limit = get_top_vm_rows(period, q=q, sort_by=sort_by, order=sort_order, scope=scope, limit=limit)

    content = f"""
    <div class="card top-card">
        <div class="top-grid">
            <div>
                <div class="label">Latest Available</div>
                <div class="value">{fmt_full(end)}</div>
            </div>
            <div>
                <div class="label">Timezone</div>
                <div class="value">{display_timezone_name()}</div>
            </div>
            <div>
                <div class="label">Selected Snapshot</div>
                <div class="value">{fmt_full(start)}</div>
            </div>
        </div>
        <div class="label period-label">Snapshot lookback</div>
        <div class="periods">{top_period_links(period, q=q, sort_by=sort_by, order=sort_order, scope=scope, limit=limit)}</div>
        <div class="label period-label">Scope</div>
        <div class="scope-links">{top_scope_links(period, q, sort_by, sort_order, scope, limit)}</div>
        <form class="search" method="get" action="{url_for('top_page')}">
            <input type="hidden" name="period" value="{escape(period)}">
            <input type="hidden" name="sort" value="{escape(sort_by)}">
            <input type="hidden" name="order" value="{escape(sort_order)}">
            <input type="hidden" name="scope" value="{escape(scope)}">
            <input name="q" value="{escape(q)}" placeholder="Search node / IPv4 / MAC / VM UUID / interface">
            <input name="limit" value="{limit}" style="max-width:100px; min-width:80px" placeholder="Limit">
            <button type="submit">Search</button>
            {f'<a class="clear" href="{url_for("top_page", period=period, sort=sort_by, order=sort_order, scope=scope, limit=limit)}">Clear</a>' if q else ''}
        </form>
    </div>
    {top_vm_table(rows, period, q, sort_by, sort_order, scope, limit)}
    """
    return page("Top VM", content)

def query_node_network_health_chart(node, period, q=""):
    start, end = range_for_period(period)
    conn = db()
    try:
        bucket_ids = _sample_real_buckets(_node_retained_buckets(conn, node, period))
        if not bucket_ids:
            return [], start, end, chart_step_seconds(period)
        placeholders = _sql_in_placeholders(bucket_ids)
        params = [CACHE_BUCKET_SECONDS, node] + bucket_ids
        search_sql = ""
        if q:
            search_sql = " AND (ns.vm_uuid LIKE ? OR ns.iface LIKE ? OR ns.node LIKE ?)"
            p = like_pattern(q)
            params.extend([p, p, p])
        raw = conn.execute(f"""
            SELECT ns.bucket,
                   SUM(COALESCE(ns.rx_packets_delta,0)),
                   SUM(COALESCE(ns.tx_packets_delta,0)),
                   SUM(COALESCE(ns.rx_drop_delta,0)+COALESCE(ns.tx_drop_delta,0)),
                   SUM(COALESCE(ns.rx_error_delta,0)+COALESCE(ns.tx_error_delta,0)),
                   MAX(ns.last_push), MAX(COALESCE(ns.interval_seconds,?))
            FROM node_stats ns
            LEFT JOIN vm_inventory vi ON vi.node=ns.node AND vi.vm_uuid=ns.vm_uuid
            WHERE ns.node=? AND ns.bucket IN ({placeholders})
              AND COALESCE(vi.status,'active')!='hidden' {search_sql}
            GROUP BY ns.bucket ORDER BY ns.bucket
        """, params).fetchall()
    finally:
        conn.close()
    rows=[]
    for r in raw:
        interval=max(1,int(r[6] or CACHE_BUCKET_SECONDS)); rxp=int(r[1] or 0); txp=int(r[2] or 0)
        rows.append({"bucket":int(r[0]),"label":fmt_chart_label(r[0],interval),"rx_pps":rxp/interval,"tx_pps":txp/interval,"pps":(rxp+txp)/interval,"drops":int(r[3] or 0),"errors":int(r[4] or 0),"last_push":int(r[5] or 0)})
    gaps=[rows[i]["bucket"]-rows[i-1]["bucket"] for i in range(1,len(rows))]
    return rows,start,end,min((g for g in gaps if g>0),default=chart_step_seconds(period))

def get_node_host_period(node, period):
    """Return one exact host metric push for the selected lookback point."""
    period = clean_period(period)
    conn = db()
    try:
        selected_bucket, _latest_bucket = resolve_snapshot_bucket(conn, period, node=node)
        host_bucket = resolve_table_snapshot_bucket(conn, "node_host_stats", node, selected_bucket)
        if not host_bucket:
            return None

        row = conn.execute("""
            SELECT
                time,
                COALESCE(interval_seconds, ?),
                load1, load5, load15,
                cpu_count, cpu_percent,
                mem_total, mem_available, mem_used,
                swap_total, swap_used,
                disk_read_bps, disk_write_bps,
                disk_read_delta, disk_write_delta,
                uptime_seconds
            FROM node_host_stats
            WHERE node=? AND bucket=?
            ORDER BY time DESC, id DESC
            LIMIT 1
        """, (CACHE_BUCKET_SECONDS, node, host_bucket)).fetchone()
        if not row:
            return None

        (last_seen, interval_seconds, load1, load5, load15, cpu_count, cpu_percent,
         mem_total, mem_available, mem_used, swap_total, swap_used,
         disk_read_bps, disk_write_bps, disk_read_delta, disk_write_delta,
         uptime_seconds) = row
        return (
            int(last_seen or host_bucket), int(interval_seconds or CACHE_BUCKET_SECONDS),
            float(load1 or 0), float(load5 or 0), float(load15 or 0),
            int(cpu_count or 0), float(cpu_percent or 0),
            int(mem_total or 0), int(mem_available or 0), int(mem_used or 0),
            int(swap_total or 0), int(swap_used or 0),
            float(disk_read_bps or 0), float(disk_write_bps or 0),
            int(disk_read_delta or 0), int(disk_write_delta or 0),
            int(uptime_seconds or 0), 'ok', '', 1,
        )
    finally:
        conn.close()

def get_node_filesystems_snapshot(node, period):
    conn = db()
    try:
        # Keep the original retained filesystem snapshot semantics for capacity,
        # then enrich each mount with the latest physical block I/O sample. This
        # does not change Node Health/Top VM history and avoids duplicating a
        # high-volume per-filesystem I/O history table.
        ensure_disk_io_schema(conn)
        selected_bucket, _latest_bucket = resolve_snapshot_bucket(conn, period, node=node)
        if not selected_bucket:
            return []
        row = conn.execute("""
            SELECT time
            FROM node_filesystem_stats
            WHERE node=? AND time BETWEEN ? AND ?
            GROUP BY time
            ORDER BY ABS(time - ?) ASC, time DESC
            LIMIT 1
        """, (node, selected_bucket - CACHE_BUCKET_SECONDS, selected_bucket + CACHE_BUCKET_SECONDS, selected_bucket)).fetchone()
        snapshot_time = int((row or [0])[0] or 0)
        if not snapshot_time:
            return []
        return conn.execute("""
            SELECT
                f.mount, f.device, f.fstype, f.size, f.used, f.avail,
                f.use_percent, f.last_push,
                COALESCE(s.read_bps, 0), COALESCE(s.write_bps, 0),
                COALESCE(s.read_iops, 0), COALESCE(s.write_iops, 0),
                COALESCE(s.util_percent, 0), COALESCE(s.last_seen, 0)
            FROM node_filesystem_stats f
            LEFT JOIN node_storage_current s
              ON s.node=f.node AND s.mount=f.mount
            WHERE f.node=? AND f.time=?
            ORDER BY f.use_percent DESC, f.mount COLLATE NOCASE ASC
        """, (node, snapshot_time)).fetchall()
    finally:
        conn.close()

def query_node_host_chart(node, period):
    """Exact physical-host samples on sampled real retained push buckets."""
    start,end=range_for_period(period)
    conn=db()
    try:
        bucket_ids=_sample_real_buckets(_node_retained_buckets(conn,node,period))
        if not bucket_ids:
            return [],start,end,chart_step_seconds(period)
        placeholders=_sql_in_placeholders(bucket_ids)
        raw=conn.execute(f"""
            SELECT bucket, load1, load5, load15, cpu_percent,
                   mem_total, mem_used, mem_available, swap_total, swap_used,
                   disk_read_bps, disk_write_bps, time
            FROM node_host_stats
            WHERE node=? AND bucket IN ({placeholders})
            ORDER BY bucket, time
        """,[node]+bucket_ids).fetchall()
    finally:
        conn.close()
    by={int(r[0]):r for r in raw}
    rows=[]
    for bucket in sorted(by):
        r=by[bucket]
        rows.append({"bucket":bucket,"label":fmt_chart_label(bucket,CACHE_BUCKET_SECONDS),"load1":float(r[1] or 0),"load5":float(r[2] or 0),"load15":float(r[3] or 0),"host_cpu_percent":float(r[4] or 0),"mem_total_bytes":float(r[5] or 0),"mem_used_bytes":float(r[6] or 0),"mem_available_bytes":float(r[7] or 0),"swap_total_bytes":float(r[8] or 0),"swap_used_bytes":float(r[9] or 0),"host_disk_read_bps":float(r[10] or 0),"host_disk_write_bps":float(r[11] or 0),"last_push":int(r[12] or 0)})
    gaps=[rows[i]["bucket"]-rows[i-1]["bucket"] for i in range(1,len(rows))]
    return rows,start,end,min((g for g in gaps if g>0),default=chart_step_seconds(period))

def fmt_uptime(seconds):
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "-"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"

def percent_of(used, total):
    used = float(used or 0)
    total = float(total or 0)
    if total <= 0:
        return "-"
    return fmt_percent((used / total) * 100.0)

def metric_level(value, warn, crit):
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return "ok"
    if v >= float(crit):
        return "crit"
    if v >= float(warn):
        return "warn"
    return "ok"

def metric_pill(value_html, level="ok", title=""):
    level = level if level in ("ok", "warn", "crit") else "ok"
    title_attr = f' title="{escape(str(title), quote=True)}"' if title else ""
    return f'<span class="metric-pill metric-{level}"{title_attr}>{value_html}</span>'

def ram_used_percent_value(mem_used, mem_total):
    mem_total = float(mem_total or 0)
    if mem_total <= 0:
        return 0.0
    return max(0.0, min(100.0, float(mem_used or 0) * 100.0 / mem_total))

def load_percent_value(load1, cpu_count):
    cpu_count = safe_int(cpu_count, 0)
    if cpu_count <= 0:
        return 0.0
    return max(0.0, float(load1 or 0) * 100.0 / float(cpu_count))

def node_host_cards(row, period):
    if not row:
        return f"""
        <div class="card overview-card">
            <div class="overview-head">
                <h3>Node Host Health</h3>
                <div class="overview-meta"><span>Source <b>not reported</b></span></div>
            </div>
            <div class="empty">No host metrics yet. Deploy agent v3 on this node to collect physical host CPU/RAM/disk/filesystem data.</div>
        </div>
        """
    (last_seen, covered_seconds, load1, load5, load15, cpu_count, cpu_percent, mem_total, mem_available, mem_used,
     swap_total, swap_used, disk_read_bps, disk_write_bps, disk_read_delta, disk_write_delta,
     uptime_seconds, alert_level, alert_flags, sample_count) = row
    flags = escape(alert_flags or "-")
    ram_pct = ram_used_percent_value(mem_used, mem_total)
    load_pct = load_percent_value(load1, cpu_count)
    cpu_level = metric_level(cpu_percent, 70, 85)
    ram_level = metric_level(ram_pct, 80, 90)
    cores = safe_int(cpu_count, 0)
    if cores > 0:
        # Host load thresholds requested by UI:
        # green <60%, orange 60% to <90%, red >=90% of CPU core count.
        load_level = metric_level(load_pct, 60, 90)
        load_note = f"{cores} cores · {load_pct:.1f}% of core count"
        load_value_html = metric_pill(
            f"{float(load1 or 0):.2f} / {float(load5 or 0):.2f} / {float(load15 or 0):.2f}",
            load_level,
            load_note,
        )
    else:
        # Never classify an unknown-core snapshot by arbitrary absolute load.
        # Older retained snapshots may predate the cpu_count field.
        load_note = "CPU core count is missing in this retained snapshot"
        load_value_html = (
            f'<span class="metric-pill metric-unknown" title="{escape(load_note, quote=True)}">'
            f'{float(load1 or 0):.2f} / {float(load5 or 0):.2f} / {float(load15 or 0):.2f}'
            f'</span>'
        )
    swap_pct = ram_used_percent_value(swap_used, swap_total)
    swap_level = metric_level(swap_pct, 50, 80) if swap_total else "ok"
    return f"""
    <div class="card overview-card">
        <div class="overview-head">
            <h3>Node Host Health</h3>
            <div class="overview-meta">
                <span>Source <b>exact push snapshot</b></span>
                <span>Interval <b>{int((covered_seconds or 0) / 60)}m</b></span>
                <span>Snapshot <b>{fmt_push(last_seen)}</b></span>
                <span>Uptime <b>{fmt_uptime(uptime_seconds)}</b></span>
                <span>Flags <b>{flags}</b></span>
            </div>
        </div>
        <div class="grid">
            <div class="stat">Load 1/5/15<b>{load_value_html}</b><small>{escape(load_note)}</small></div>
            <div class="stat">Host CPU<b>{metric_pill(fmt_percent(cpu_percent), cpu_level, "warn >=70%, critical >=85%")}</b></div>
            <div class="stat">Host RAM<b>{metric_pill(f"{human(mem_used)} / {human(mem_total)}", ram_level, "warn >=80%, critical >=90%")}</b><small>Available {human(mem_available)} · Used {fmt_percent(ram_pct)}</small></div>
            <div class="stat">Swap<b>{metric_pill(f"{human(swap_used)} / {human(swap_total)}", swap_level, "warn >=50%, critical >=80%")}</b><small>Used {percent_of(swap_used, swap_total)}</small></div>
            <div class="stat">Disk Read<b>{human_rate(disk_read_bps)}</b></div>
            <div class="stat">Disk Write<b>{human_rate(disk_write_bps)}</b></div>
        </div>
    </div>
    """

@app.route("/node/<path:node>")
def node_page(node):
    period = clean_period(request.args.get("period", "5m"))
    q = (request.args.get("q") or "").strip()
    sort_by = clean_interface_sort(request.args.get("sort", "total"))
    sort_order = clean_sort_order(request.args.get("order", "desc"))
    chart_sort = clean_node_chart_sort(request.args.get("chart_sort", "time"))
    chart_order = clean_sort_order(request.args.get("chart_order", "desc"))
    # Keep VM lifecycle handling internally, but remove VM status filter from UI.
    vm_status = "active"
    net_mode = clean_node_net_mode(request.args.get("net", "both"))

    public_rows, start, end = query_node_bridge(node, period, PUBLIC_BRIDGE, q=q, sort_by=sort_by, order=sort_order, vm_status=vm_status)
    private_rows, _, _ = query_node_bridge(node, period, PRIVATE_BRIDGE, q=q, sort_by=sort_by, order=sort_order, vm_status=vm_status)
    overview = get_node_overview(node, period, q=q, vm_status=vm_status)
    chart_rows, _, _, step = query_node_chart(node, period, q=q, vm_status=vm_status)
    node_net_rows, _, _, _ = query_node_network_health_chart(node, period, q=q)
    node_perf_rows, _, _, _ = query_node_perf_chart(node, period, q=q)
    node_metric_overview = get_node_metric_overview(node, period, q=q, vm_status=vm_status)
    node_host_period = get_node_host_period(node, period)
    node_filesystems = get_node_filesystems_snapshot(node, period)
    node_host_rows, _, _, _ = query_node_host_chart(node, period)
    recent_migrations = get_recent_vm_migrations(node, limit=10)
    chart_public = sum(r["public"] for r in chart_rows)
    chart_private = sum(r["private"] for r in chart_rows)
    chart_points = sum(1 for r in chart_rows if r["public"] > 0 or r["private"] > 0)

    interface_cards = []
    if net_mode in ("both", "public"):
        interface_cards.append(interface_table("Public", PUBLIC_BRIDGE, node, public_rows, period, q=q, sort_by=sort_by, order=sort_order, vm_status=vm_status))
    if net_mode in ("both", "private"):
        interface_cards.append(interface_table("Private", PRIVATE_BRIDGE, node, private_rows, period, q=q, sort_by=sort_by, order=sort_order, vm_status=vm_status))
    interface_cards_html = "".join(interface_cards)

    content = f"""
    <div class="card page-title-card">
        <div class="breadcrumb"><a href="{url_for('index', period=period, q=q)}">Dashboard</a> / Node</div>
        <div class="page-title-row">
            <h3>{escape(node)}</h3>
            <a href="{url_for('index', period=period, q=q)}">Back to dashboard</a>
        </div>
    </div>
    {range_card(period, start, end, q=q, endpoint="node_page", node=node, vm_status=vm_status, net=net_mode)}
    {overview_cards(overview, node, period)}
    {node_host_cards(node_host_period, period)}
    {node_filesystem_table(node_filesystems)}
    {vm_migration_table(recent_migrations)}
    {node_net_tabs(node, period, q, sort_by, sort_order, net_mode)}
    {node_metric_cards(node_metric_overview)}

    <div class="node-chart-section">
        <div class="card node-chart-head">
            <div class="table-title-row">
                <h3>Node Charts</h3>
                <div class="count-badges">
                    <span>Public <b>{human(chart_public)}</b></span>
                    <span>Private <b>{human(chart_private)}</b></span>
                    <span>Points <b>{chart_points}</b></span>
                    <span>Typical Gap <b>{int(step / 60)}m</b></span>
                </div>
            </div>
        </div>

        <div class="node-charts-grid">
            {vm_metric_chart_svg(node_host_rows, "Load / CPU", [
                {"key": "load1", "label": "Load 1m", "kind": "raw", "class": "metric1"},
                {"key": "load5", "label": "Load 5m", "kind": "raw", "class": "metric2"},
                {"key": "load15", "label": "Load 15m", "kind": "raw", "class": "metric3"},
                {"key": "host_cpu_percent", "label": "CPU %", "kind": "percent", "class": "metric4"},
            ], "Source: /proc/loadavg + /proc/stat on host node")}
            {vm_metric_chart_svg(node_host_rows, "RAM / Swap", [
                {"key": "mem_used_bytes", "label": "RAM Used", "kind": "bytes", "class": "metric1"},
                {"key": "mem_available_bytes", "label": "RAM Available", "kind": "bytes", "class": "metric2"},
                {"key": "swap_used_bytes", "label": "Swap Used", "kind": "bytes", "class": "metric3"},
            ], "Source: /proc/meminfo on host node")}
            {vm_metric_chart_svg(node_host_rows, "Disk IO", [
                {"key": "host_disk_read_bps", "label": "Read/s", "kind": "rate", "class": "metric1"},
                {"key": "host_disk_write_bps", "label": "Write/s", "kind": "rate", "class": "metric2"},
            ], "Source: /sys/class/block counters for mounted devices")}
            {node_chart_svg(chart_rows, "Traffic")}
            {vm_metric_chart_svg(node_net_rows, "Packet PPS", [
                {"key": "rx_pps", "label": "RX PPS", "kind": "pps", "class": "metric1"},
                {"key": "tx_pps", "label": "TX PPS", "kind": "pps", "class": "metric2"},
            ], "Source: node_stats packet counters")}
            {vm_metric_chart_svg(node_perf_rows, "VM CPU Core Usage", [
                {"key": "total_cpu_percent", "label": "Total VM CPU", "kind": "percent", "class": "metric1"},
                {"key": "max_cpu_percent", "label": "Max VM CPU", "kind": "percent", "class": "metric2"},
            ], "Source: aggregated vm_perf_stats · 100% = 1 full core")}
            {vm_metric_chart_svg(node_perf_rows, "VM RAM", [
                {"key": "guest_used_bytes", "label": "Guest Used", "kind": "bytes", "class": "metric1"},
                {"key": "ram_rss_bytes", "label": "Host RSS", "kind": "bytes", "class": "metric2"},
                {"key": "ram_current_bytes", "label": "Assigned", "kind": "bytes", "class": "metric3"},
            ], "Guest Used is summed only for VMs with valid balloon available/usable stats; Host RSS is host-side QEMU resident memory")}
            {vm_metric_chart_svg(node_perf_rows, "VM Disk IO", [
                {"key": "disk_read_bps", "label": "Read/s", "kind": "rate", "class": "metric1"},
                {"key": "disk_write_bps", "label": "Write/s", "kind": "rate", "class": "metric2"},
            ], "Source: aggregated block counters")}
        </div>
        {node_chart_table(chart_rows, node, period, q=q, chart_sort=chart_sort, chart_order=chart_order, table_sort=sort_by, table_order=sort_order)}
    </div>
    {interface_cards_html}
    """
    return page(f"Node {node}", content)

def get_vm_latest_metric(node, vm_uuid):
    conn = db()
    try:
        return conn.execute("""
            SELECT last_seen, interval_seconds, iface, bridge,
                rx_mbps, tx_mbps, rx_pps, tx_pps,
                rx_mbps_peak, tx_mbps_peak, rx_pps_peak, tx_pps_peak,
                rx_packet_size_avg, tx_packet_size_avg,
                network_sample_count, network_sample_expected, network_sample_max_gap_seconds,
                seconds_over_pps, seconds_over_mbps, network_sample_quality,
                rx_drop_delta + tx_drop_delta AS drops,
                rx_error_delta + tx_error_delta AS errors,
                cpu_percent, vcpu_current,
                ram_current_kib, ram_maximum_kib, ram_rss_kib, ram_available_kib,
                disk_read_bps, disk_write_bps
            FROM vm_latest_metrics WHERE node=? AND vm_uuid=?
        """, (node, vm_uuid)).fetchone()
    finally:
        conn.close()

@app.route("/vm")
def vm_page():
    node = (request.args.get("node") or "").strip()
    vm_uuid = (request.args.get("vm_uuid") or "").strip()
    bridge = (request.args.get("bridge") or "").strip()
    iface = (request.args.get("iface") or "").strip()
    period = clean_period(request.args.get("period", "5m"))
    raw_sort = clean_chart_table_sort(request.args.get("raw_sort", "time"))
    raw_order = clean_sort_order(request.args.get("raw_order", "desc"))
    if not node or not vm_uuid:
        return Response("Missing node or vm_uuid\n", status=400, mimetype="text/plain")

    rows, start, end, step = query_vm_chart(node, vm_uuid, period, bridge=bridge, iface=iface)
    perf_rows, _a, _b, _c = query_vm_perf_chart(node, vm_uuid, period)
    chart_rx_total = sum(r["rx"] for r in rows)
    chart_tx_total = sum(r["tx"] for r in rows)
    chart_total = sum(r["total"] for r in rows)
    chart_packets_total = sum(r.get("packets", 0) for r in rows)
    chart_drops_total = sum(r.get("drops", 0) for r in rows)
    chart_errors_total = sum(r.get("errors", 0) for r in rows)
    non_zero_points = sum(1 for r in rows if r["total"] > 0 or r.get("packets", 0) > 0)
    perf_points = sum(1 for r in perf_rows if r.get("last_push", 0) > 0)
    chart_last_push = max(
        max((r["last_push"] for r in rows), default=0),
        max((r.get("last_push", 0) for r in perf_rows), default=0),
    )

    scope = vm_scope_text(bridge, iface)
    snapshot = _v5054_vm_snapshot_overview(node, vm_uuid, period, bridge=bridge, iface=iface)
    latest = _v5054_vm_snapshot_metric_tuple(snapshot)
    if latest is None and _request_target_ts() is None and period == "5m":
        latest = _get_vm_latest_metric_v483(node, vm_uuid)

    if latest:
        (
            _seen, _interval, _iface, _bridge, lm_rx_mbps, lm_tx_mbps, lm_rx_pps, lm_tx_pps,
            lm_rx_mbps_peak, lm_tx_mbps_peak, lm_rx_pps_peak, lm_tx_pps_peak,
            lm_rx_pkt_size, lm_tx_pkt_size, lm_samples, lm_expected, lm_max_gap,
            lm_over_pps, lm_over_mbps, lm_quality, lm_drops, lm_errors,
            lm_cpu, lm_vcpu, lm_ram_current, lm_ram_max, lm_ram_rss, lm_ram_available,
            lm_disk_read_bps, lm_disk_write_bps,
        ) = latest
    else:
        lm_rx_mbps = lm_tx_mbps = lm_rx_pps = lm_tx_pps = 0
        lm_rx_mbps_peak = lm_tx_mbps_peak = lm_rx_pps_peak = lm_tx_pps_peak = 0
        lm_rx_pkt_size = lm_tx_pkt_size = lm_max_gap = 0
        lm_samples = lm_expected = lm_over_pps = lm_over_mbps = lm_drops = lm_errors = 0
        lm_quality = "LEGACY"
        lm_cpu = lm_vcpu = lm_ram_current = lm_ram_max = lm_ram_rss = lm_ram_available = 0
        lm_disk_read_bps = lm_disk_write_bps = 0

    if snapshot:
        overview_rx_total = snapshot["rx_bytes"]
        overview_tx_total = snapshot["tx_bytes"]
        overview_total = snapshot["total_bytes"]
        overview_packets_total = snapshot["packets"]
        overview_drops_total = snapshot["drops"]
        overview_errors_total = snapshot["errors"]
        overview_last_push = snapshot["last_push"]
        selected_snapshot = snapshot["selected_bucket"]
    else:
        # Compatibility path for a live installation that has not produced its
        # first retained snapshot yet. Historical pages never borrow current data.
        live_request = _request_target_ts() is None and period == "5m"
        overview_rx_total = chart_rx_total if live_request else 0
        overview_tx_total = chart_tx_total if live_request else 0
        overview_total = chart_total if live_request else 0
        overview_packets_total = chart_packets_total if live_request else 0
        overview_drops_total = chart_drops_total if live_request else 0
        overview_errors_total = chart_errors_total if live_request else 0
        overview_last_push = chart_last_push if live_request else 0
        selected_snapshot = overview_last_push

    directional = get_vm_directional_current(node, vm_uuid)
    if directional:
        directional_value = (
            f"RX {int(directional.get('seconds_over_rx_pps', 0))}s / "
            f"TX {int(directional.get('seconds_over_tx_pps', 0))}s"
        )
        directional_note = "One direction must stay high for about 5 minutes"
    else:
        directional_value = "N/A"
        directional_note = "Directional streak counters are current-only"

    sample_badge = network_sample_badge(lm_quality, lm_samples, lm_expected, lm_max_gap)
    current_location = get_vm_current_location(vm_uuid)
    migration_notice = ""
    if current_location and current_location.get("node") and current_location.get("node") != node:
        current_node = current_location.get("node")
        latest_href = url_for(
            "vm_page", node=current_node, vm_uuid=vm_uuid,
            bridge="", iface="", period="5m",
        )
        migration_notice = f"""<div class="card warn-card"><h3>VM migrated</h3><p>This VM is currently reported on <b class="mono">{escape(current_node)}</b>. This page shows historical data for <b class="mono">{escape(node)}</b>.</p><p>Moved at <b>{fmt_full(current_location.get('moved_at'))}</b> · Previous node <b class="mono">{escape(current_location.get('previous_node') or '-')}</b> · Move count <b>{int(current_location.get('move_count') or 0)}</b></p><a href="{escape(latest_href, quote=True)}">Open current VM location</a></div>"""

    back_href = url_for("node_page", node=node, period=period, q=vm_uuid)
    content = f"""
    {migration_notice}
    <div class="card"><h3>VM Metrics</h3><a href="{escape(back_href, quote=True)}">← Back to node</a><div class="grid" style="margin-top:14px"><div class="stat">Node<b class="mono">{escape(node)}</b></div><div class="stat">VM UUID<b class="mono">{escape(vm_uuid)}</b></div><div class="stat">Scope<b>{escape(scope)}</b></div><div class="stat">Last Push<b>{fmt_push(overview_last_push)}</b></div></div></div>
    <div class="card top-card"><div class="top-grid"><div><div class="label">Selected Snapshot</div><div class="value">{fmt_full(selected_snapshot)}</div></div><div><div class="label">Timezone</div><div class="value">{display_timezone_name()}</div></div><div><div class="label">Chart Range</div><div class="value">{fmt_range(start)} <span class="arrow">→</span> {fmt_range(end)}</div></div></div><div class="label period-label">Period</div><div class="periods">{vm_period_links(period, node, vm_uuid, bridge, iface)}</div></div>
    <div class="card"><h3>Overview</h3><div class="grid">
      <div class="stat">RX / TX<b>{human(overview_rx_total)} / {human(overview_tx_total)}</b><small>Selected snapshot</small></div><div class="stat">TOTAL<b>{human(overview_total)}</b><small>Selected snapshot</small></div><div class="stat">Points<b>{non_zero_points}</b><small>Perf {perf_points}</small></div><div class="stat">Bucket Step<b>{int(step / 60)}m</b></div>
      <div class="stat">AVG RX/TX Mbps<b>{lm_rx_mbps:.2f} / {lm_tx_mbps:.2f}</b></div><div class="stat">PEAK RX/TX Mbps<b>{lm_rx_mbps_peak:.2f} / {lm_tx_mbps_peak:.2f}</b><small>Selected local sampler peak</small></div>
      <div class="stat">AVG RX/TX PPS<b>{fmt_pps_value(lm_rx_pps)} / {fmt_pps_value(lm_tx_pps)}</b></div><div class="stat">PEAK RX/TX PPS<b>{fmt_pps_value(lm_rx_pps_peak)} / {fmt_pps_value(lm_tx_pps_peak)}</b><small>Packets {int(overview_packets_total)}</small></div>
      <div class="stat">Sample Quality<b>{sample_badge}</b><small>{int(lm_samples)}/{int(lm_expected)} samples, max gap {float(lm_max_gap):.1f}s</small></div><div class="stat">PPS ≥ {ABUSE_NETWORK_PPS:,.0f}/s<b>{directional_value}</b><small>{directional_note}</small></div>
      <div class="stat">Avg Packet Size<b>{float(lm_rx_pkt_size):.0f} / {float(lm_tx_pkt_size):.0f} B</b><small>RX / TX</small></div><div class="stat">Drops / Errors<b>{int(overview_drops_total)} / {int(overview_errors_total)}</b><small>Selected snapshot</small></div>
      {_v48129_vm_detail_cpu_stat(lm_cpu, lm_vcpu)}<div class="stat">RAM<b>{fmt_ram_pair(lm_ram_rss, lm_ram_current)}</b><small>Available {fmt_kib(lm_ram_available)}</small></div><div class="stat">Disk Read / Write<b>{human_rate(lm_disk_read_bps)} / {human_rate(lm_disk_write_bps)}</b><small>Selected snapshot</small></div>
    </div></div>
    <div class="vm-charts-grid">
      {vm_metric_chart_svg(rows, "Average Mbps", [{"key":"rx_mbps","label":"RX AVG","kind":"mbps","class":"metric1"},{"key":"tx_mbps","label":"TX AVG","kind":"mbps","class":"metric2"}], "Exact counter delta divided by actual push interval")}
      {vm_metric_chart_svg(rows, "Peak Mbps", [{"key":"rx_mbps_peak","label":"RX PEAK","kind":"mbps","class":"metric1"},{"key":"tx_mbps_peak","label":"TX PEAK","kind":"mbps","class":"metric2"}], "Highest local sampler value; no 15-second rows stored")}
      {vm_metric_chart_svg(rows, "Average PPS", [{"key":"rx_pps","label":"RX AVG","kind":"pps","class":"metric1"},{"key":"tx_pps","label":"TX AVG","kind":"pps","class":"metric2"}], "Exact packet counter delta divided by actual interval")}
      {vm_metric_chart_svg(rows, "Peak PPS", [{"key":"rx_pps_peak","label":"RX PEAK","kind":"pps","class":"metric1"},{"key":"tx_pps_peak","label":"TX PEAK","kind":"pps","class":"metric2"}], "Highest local sampler value")}
      {vm_metric_chart_svg(rows, "Drops / Errors", [{"key":"drops","label":"Drops","kind":"count","class":"metric1"},{"key":"errors","label":"Errors","kind":"count","class":"metric2"}], "Exact counters", render_zero=True)}
      {vm_metric_chart_svg(perf_rows, "CPU Core Usage", [{"key":"cpu_core_percent","label":"CPU Core%","kind":"percent","class":"metric1"}], "100% = 1 full core")}
      {vm_metric_chart_svg(perf_rows, "VM RAM", [{"key":"guest_used_bytes","label":"Guest Used","kind":"bytes","class":"metric1"},{"key":"ram_rss_bytes","label":"Host RSS","kind":"bytes","class":"metric2"},{"key":"ram_current_bytes","label":"Assigned","kind":"bytes","class":"metric3"}], "Guest Used = balloon available - usable. Host RSS is QEMU resident memory on the node; Assigned is the VM allocation.")}
      {vm_metric_chart_svg(perf_rows, "Disk IO", [{"key":"disk_read_bps","label":"Read/s","kind":"rate","class":"metric1"},{"key":"disk_write_bps","label":"Write/s","kind":"rate","class":"metric2"}], "virsh domstats block counters")}
    </div>
    {vm_chart_table(rows, node, vm_uuid, bridge, iface, period, raw_sort=raw_sort, raw_order=raw_order)}"""
    return page(f"VM {vm_uuid}", content)

def api_vm():
    node = (request.args.get("node") or "").strip()
    vm_uuid = (request.args.get("vm_uuid") or "").strip()
    bridge = (request.args.get("bridge") or "").strip()
    iface = (request.args.get("iface") or "").strip()
    period = clean_period(request.args.get("period", "1h"))

    if not node or not vm_uuid:
        return {"error": "missing node or vm_uuid"}, 400

    rows, start, end, step = query_vm_chart(node, vm_uuid, period, bridge=bridge, iface=iface)
    return jsonify({
        "node": node,
        "vm_uuid": vm_uuid,
        "bridge": bridge,
        "iface": iface,
        "scope": vm_scope_text(bridge, iface),
        "timezone": display_timezone_name(),
        "period": period,
        "bucket_step_seconds": step,
        "range_start": start,
        "range_end": end,
        "range_start_vn": fmt_full(start),
        "range_end_vn": fmt_full(end),
        "rx_bytes": sum(r["rx"] for r in rows),
        "tx_bytes": sum(r["tx"] for r in rows),
        "total_bytes": sum(r["total"] for r in rows),
        "packets": sum(r.get("packets", 0) for r in rows),
        "drops": sum(r.get("drops", 0) for r in rows),
        "errors": sum(r.get("errors", 0) for r in rows),
        "points": rows,
    })

def admin_node_rows(q=""):
    """Return admin node rows, including current public/private IPv4 addresses.

    The shared Admin search matches node name, any stored IPv4, VM UUID,
    bridge and interface, so searching for a VM also keeps its parent node row.
    """
    auto_cleanup_inventory()
    search_sql = ""
    params = []
    if q:
        p = like_pattern(q)
        search_sql = """
            WHERE (
                ni.node LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM node_bridge_addresses_latest bai
                    WHERE bai.node=ni.node
                      AND (
                            COALESCE(bai.primary_ipv4, '') LIKE ?
                            OR COALESCE(bai.ipv4_json, '[]') LIKE ?
                          )
                )
                OR EXISTS (
                    SELECT 1
                    FROM vm_inventory svi
                    WHERE svi.node=ni.node
                      AND (
                            svi.vm_uuid LIKE ?
                            OR COALESCE(svi.last_iface, '') LIKE ?
                            OR COALESCE(svi.last_bridge, '') LIKE ?
                          )
                )
            )
        """
        params.extend([p, p, p, p, p, p])

    conn = db()
    try:
        return conn.execute(f"""
            WITH bridge_ip AS (
                SELECT
                    node,
                    MAX(CASE WHEN LOWER(role)='public' THEN primary_ipv4 ELSE '' END) AS public_ipv4,
                    MAX(CASE WHEN LOWER(role)='private' THEN primary_ipv4 ELSE '' END) AS private_ipv4
                FROM node_bridge_addresses_latest
                GROUP BY node
            )
            SELECT
                ni.node,
                ni.status,
                ni.first_seen,
                ni.last_push,
                ni.deleted_at,
                COUNT(DISTINCT vi.vm_uuid) AS vm_count,
                COALESCE(bip.public_ipv4, '') AS public_ipv4,
                COALESCE(bip.private_ipv4, '') AS private_ipv4
            FROM node_inventory ni
            LEFT JOIN vm_inventory vi
              ON vi.node = ni.node
             AND COALESCE(vi.status, 'active') != 'hidden'
             AND vi.deleted_at IS NULL
            LEFT JOIN bridge_ip bip ON bip.node=ni.node
            {search_sql}
            GROUP BY
                ni.node, ni.status, ni.first_seen, ni.last_push, ni.deleted_at,
                bip.public_ipv4, bip.private_ipv4
            ORDER BY ni.node COLLATE NOCASE ASC
            LIMIT 1000
        """, params).fetchall()
    finally:
        conn.close()

def admin_vm_rows(q=""):
    """Return VM inventory with its parent node's current IPv4 addresses."""
    auto_cleanup_inventory()
    search_sql = ""
    params = []
    if q:
        p = like_pattern(q)
        search_sql = """
            WHERE (
                vi.node LIKE ?
                OR vi.vm_uuid LIKE ?
                OR COALESCE(vi.last_iface, '') LIKE ?
                OR COALESCE(vi.last_bridge, '') LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM node_bridge_addresses_latest bai
                    WHERE bai.node=vi.node
                      AND (
                            COALESCE(bai.primary_ipv4, '') LIKE ?
                            OR COALESCE(bai.ipv4_json, '[]') LIKE ?
                          )
                )
            )
        """
        params.extend([p, p, p, p, p, p])

    conn = db()
    try:
        return conn.execute(f"""
            WITH bridge_ip AS (
                SELECT
                    node,
                    MAX(CASE WHEN LOWER(role)='public' THEN primary_ipv4 ELSE '' END) AS public_ipv4,
                    MAX(CASE WHEN LOWER(role)='private' THEN primary_ipv4 ELSE '' END) AS private_ipv4
                FROM node_bridge_addresses_latest
                GROUP BY node
            )
            SELECT
                vi.node,
                vi.vm_uuid,
                vi.status,
                vi.last_seen,
                vi.last_bridge,
                vi.last_iface,
                vi.deleted_at,
                COALESCE(bip.public_ipv4, '') AS public_ipv4,
                COALESCE(bip.private_ipv4, '') AS private_ipv4
            FROM vm_inventory vi
            LEFT JOIN bridge_ip bip ON bip.node=vi.node
            {search_sql}
            ORDER BY
                vi.node COLLATE NOCASE ASC,
                CASE WHEN COALESCE(vi.status, 'active') = 'hidden' THEN 1 ELSE 0 END,
                CASE WHEN vi.deleted_at IS NULL THEN 0 ELSE 1 END,
                vi.last_seen ASC
            LIMIT 1000
        """, params).fetchall()
    finally:
        conn.close()

