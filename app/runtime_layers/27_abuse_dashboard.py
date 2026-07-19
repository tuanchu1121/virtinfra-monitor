V48127_VERSION = "48.12.7"

def _v48127_filter_values():
    values = _v48126_filter_values()
    values["sort"] = (request.args.get("sort") or ("severity" if (request.args.get("tab") or "current") == "current" else "occurrences")).strip().lower()
    values["order"] = (request.args.get("order") or "desc").strip().lower()
    if values["order"] not in {"asc", "desc"}:
        values["order"] = "desc"
    values["status"] = (request.args.get("status") or "all").strip().lower()
    if values["status"] not in {"all", "open", "closed"}:
        values["status"] = "all"
    return values

def _v48128_url(tab, values, **changes):
    args = dict(values)
    args.update(changes)
    args["tab"] = tab
    allowed = {"q", "node", "type", "min_severity", "range", "limit", "page", "sort", "order", "status", "tab"}
    clean = {}
    for key, value in args.items():
        if key not in allowed:
            continue
        if value in (None, "", 0, "all"):
            continue
        clean[key] = value
    return url_for("vm_abuse_page", **clean)

def _v48127_sort_link(tab, values, key, label, default="desc"):
    active = values.get("sort") == key
    current_order = values.get("order", default)
    next_order = "asc" if active and current_order == "desc" else "desc"
    if not active:
        next_order = default
    arrow = ""
    if active:
        arrow = " ↑" if current_order == "asc" else " ↓"
    href = _v48128_url(tab, values, sort=key, order=next_order, page=1)
    return f'<a class="sort-link" href="{escape(href, quote=True)}">{escape(label)}{arrow}</a>'

def _v48127_tabs(active):
    items = (("current", "Current Abuse"), ("events", "Abuse Events"))
    return '<div class="abuse-tabs abuse-tabs-v48128">' + ''.join(
        f'<a class="{"active" if active == key else ""}" href="{url_for("vm_abuse_page", tab=key)}">{label}</a>'
        for key, label in items
    ) + '</div>'

def _v48127_filter_form(tab, values, nodes):
    node_options = '<option value="">All nodes</option>' + ''.join(
        f'<option value="{escape(node, quote=True)}" {"selected" if node == values["node"] else ""}>{escape(node)}</option>'
        for node in nodes
    )
    type_options = ''.join(
        f'<option value="{key}" {"selected" if key == values["type"] else ""}>{label}</option>'
        for key, label in (("all", "All abuse types"), ("network", "Network"), ("cpu", "CPU"), ("ram", "RAM"), ("disk", "Disk"))
    )
    hidden = (
        f'<input type="hidden" name="tab" value="{escape(tab, quote=True)}">'
        f'<input type="hidden" name="sort" value="{escape(values["sort"], quote=True)}">'
        f'<input type="hidden" name="order" value="{escape(values["order"], quote=True)}">'
    )
    extra = ""
    limits = (50, 100, 200, 500) if tab == "current" else (50, 100, 200)
    if tab == "events":
        range_options = ''.join(
            f'<option value="{key}" {"selected" if key == values["range"] else ""}>{label}</option>'
            for key, label in (("1h", "Last 1h"), ("6h", "Last 6h"), ("24h", "Last 24h"), ("2d", "Last 2d"), ("7d", "Last 7d"))
        )
        status_options = ''.join(
            f'<option value="{key}" {"selected" if key == values["status"] else ""}>{label}</option>'
            for key, label in (("all", "All states"), ("open", "Active now"), ("closed", "Recovered"))
        )
        extra = f'<select name="range">{range_options}</select><select name="status">{status_options}</select>'
    limit_options = ''.join(
        f'<option value="{number}" {"selected" if number == values["limit"] else ""}>{number} / page</option>'
        for number in limits
    )
    return f"""
    <form class="search compact-search abuse-filter-v48128" method="get" action="{url_for('vm_abuse_page')}">
      {hidden}
      <input name="q" value="{escape(values['q'], quote=True)}" placeholder="Search node / VM UUID / abuse type">
      <select name="node">{node_options}</select>
      <select name="type">{type_options}</select>
      <input type="number" name="min_severity" min="0" step="0.1" value="{values['min_severity'] or ''}" placeholder="Min severity">
      {extra}
      <select name="limit">{limit_options}</select>
      <button type="submit">Filter</button>
      <a class="clear" href="{url_for('vm_abuse_page', tab=tab)}">Reset</a>
    </form>"""

def _v48127_current_rows(values):
    cfg = get_abuse_settings()
    where = [
        "a.is_abuse=1", "a.last_seen>=?", "a.policy_revision=?", "a.engine_version=?",
        _v48126_visible_sql("ni", "vi"), _v48126_type_condition("a", values["type"]), "a.severity>=?",
    ]
    params = [now_ts() - FAST_CURRENT_STALE_SECONDS, cfg["revision"], ABUSE_ENGINE_VERSION, values["min_severity"]]
    if values["node"]:
        where.append("a.node=?")
        params.append(values["node"])
    if values["q"]:
        pattern = like_pattern(values["q"])
        where.append("(a.node LIKE ? OR a.vm_uuid LIKE ? OR a.abuse_flags LIKE ?)")
        params.extend([pattern, pattern, pattern])

    sort = values.get("sort") or "severity"
    order = values.get("order") or "desc"
    plain_map = {
        "node": "a.node COLLATE NOCASE",
        "uuid": "a.vm_uuid COLLATE NOCASE",
        "severity": "a.severity",
        "network": "MAX(COALESCE(a.rx_mbps,0),COALESCE(a.tx_mbps,0))",
        "pps": "MAX(COALESCE(a.rx_peak_pps,0),COALESCE(a.tx_peak_pps,0))",
        "cpu": "COALESCE(a.cpu_full_percent,0)",
        "ram": "MAX(COALESCE(a.ram_guest_used_percent,-1),COALESCE(a.ram_rss_percent,-1))",
        "disk": "COALESCE(a.disk_read_bps,0)+COALESCE(a.disk_write_bps,0)",
        "last_seen": "a.last_seen",
    }
    if sort == "duration":
        order_sql = f"a.abuse_since {'ASC' if order == 'desc' else 'DESC'}"
    else:
        expression = plain_map.get(sort, plain_map["severity"])
        order_sql = f"{expression} {'ASC' if order == 'asc' else 'DESC'}"
    where_sql = " AND ".join(where)
    offset = (values["page"] - 1) * values["limit"]
    conn = db()
    try:
        total = safe_int(conn.execute(f"""SELECT COUNT(*) FROM vm_abuse_state a
            LEFT JOIN node_inventory ni ON ni.node=a.node
            LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
            WHERE {where_sql}""", params).fetchone()[0], 0)
        rows = conn.execute(f"""
            SELECT a.node,a.vm_uuid,a.abuse_since,a.last_seen,a.abuse_flags,a.severity,
                   a.rx_mbps,a.tx_mbps,a.rx_pps,a.tx_pps,a.rx_peak_pps,a.tx_peak_pps,
                   a.cpu_full_percent,a.cpu_core_percent,a.vcpu_current,
                   a.ram_rss_percent,a.ram_guest_used_percent,a.ram_usable_percent,a.ram_streak_seconds,
                   a.disk_read_bps,a.disk_write_bps,a.disk_read_iops,a.disk_write_iops,
                   COALESCE(b.primary_ipv4,'')
            FROM vm_abuse_state a
            LEFT JOIN node_inventory ni ON ni.node=a.node
            LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
            LEFT JOIN node_bridge_addresses_latest b ON b.node=a.node AND b.bridge=?
            WHERE {where_sql}
            ORDER BY {order_sql},a.node COLLATE NOCASE,a.vm_uuid COLLATE NOCASE
            LIMIT ? OFFSET ?
        """, [PUBLIC_BRIDGE] + params + [values["limit"], offset]).fetchall()
        counts = {}
        for key in ("network", "cpu", "ram", "disk"):
            counts[key] = safe_int(conn.execute(f"""SELECT COUNT(*) FROM vm_abuse_state a
              LEFT JOIN node_inventory ni ON ni.node=a.node
              LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
              WHERE a.is_abuse=1 AND a.last_seen>=? AND a.policy_revision=? AND a.engine_version=?
                AND {_v48126_visible_sql('ni','vi')} AND {_v48126_type_condition('a', key)}""",
              (now_ts()-FAST_CURRENT_STALE_SECONDS, cfg["revision"], ABUSE_ENGINE_VERSION)).fetchone()[0], 0)
        return rows, total, counts
    finally:
        conn.close()

def _v48127_current_page(values):
    cfg = get_abuse_settings()
    rows, total, counts = _v48127_current_rows(values)
    body = ""
    rank_start = (values["page"] - 1) * values["limit"]
    for index, row in enumerate(rows, 1):
        node, uuid, started, last_seen, flags, severity, rxm, txm, rxp, txp, rxpk, txpk, cpu, core, vcpu, rss_pct, guest_pct, usable_pct, ram_streak, dr, dw, dri, dwi, ip = row
        href = url_for("node_page", node=node, period="1h", q=uuid)
        ram_main = f"Guest {guest_pct:.1f}%" if safe_float(guest_pct, -1) >= 0 else f"RSS {safe_float(rss_pct, 0):.1f}%"
        ram_sub = f"Usable {usable_pct:.1f}%" if safe_float(usable_pct, -1) >= 0 else "Guest stats N/A"
        body += f"""<tr>
          <td class="rank-cell">{rank_start + index}</td>
          <td class="identity-cell"><div class="node-line"><a href="{escape(href, quote=True)}"><b>{escape(node)}</b></a>{f'<span>{escape(compact_ipv4(ip))}</span>' if ip else ''}</div><div class="uuid-line"><a class="mono" href="{escape(href, quote=True)}">{escape(uuid)}</a><button type="button" class="copy-btn" data-copy="{escape(uuid, quote=True)}" title="Copy UUID">⧉</button></div></td>
          <td><div class="severity-line"><b>{safe_float(severity,0):.2f}x</b><span>{escape(_v48126_primary_type(flags))}</span></div><div class="abuse-reasons">{_v48126_reason_badges(flags,cfg)}</div></td>
          <td><div class="metric-pair"><div><span>RX AVG</span><b>{safe_float(rxm,0):.2f} Mbps</b><small>{fmt_pps_value(rxp)} PPS</small></div><div><span>TX AVG</span><b>{safe_float(txm,0):.2f} Mbps</b><small>{fmt_pps_value(txp)} PPS</small></div></div></td>
          <td><div class="metric-pair"><div><span>RX PEAK</span><b>{fmt_pps_value(rxpk)} PPS</b></div><div><span>TX PEAK</span><b>{fmt_pps_value(txpk)} PPS</b></div></div></td>
          <td><div class="metric-stack"><b>{safe_float(cpu,0):.1f}%</b><span>{safe_float(core,0):.1f}% core</span><small>{safe_int(vcpu,0)} vCPU</small></div></td>
          <td><div class="metric-stack"><b>{ram_main}</b><span>{ram_sub}</span><small>{_v48126_duration(ram_streak)} streak</small></div></td>
          <td><div class="metric-pair"><div><span>READ</span><b>{human_rate(dr)}</b><small>{safe_float(dri,0):,.0f} IOPS</small></div><div><span>WRITE</span><b>{human_rate(dw)}</b><small>{safe_float(dwi,0):,.0f} IOPS</small></div></div></td>
          <td><div class="timeline-cell"><b>{fmt_full(started) if started else '-'}</b><small>Started · {_v48126_duration(safe_int(last_seen,0)-safe_int(started,last_seen))}</small></div></td>
          <td><div class="timeline-cell"><b>{fmt_full(last_seen)}</b><small>{fmt_push(last_seen)}</small></div></td>
        </tr>"""
    if not body:
        body = '<tr><td colspan="10" class="empty">No visible VM matches the selected Current Abuse filters</td></tr>'
    pages = max(1, math.ceil(total / values["limit"]))
    headers = (
        '<th>#</th>'
        f'<th>{_v48127_sort_link("current", values, "node", "NODE / VM", "asc")}</th>'
        f'<th>{_v48127_sort_link("current", values, "severity", "REASON / SEVERITY")}</th>'
        f'<th>{_v48127_sort_link("current", values, "network", "NETWORK AVG")}</th>'
        f'<th>{_v48127_sort_link("current", values, "pps", "PPS PEAK")}</th>'
        f'<th>{_v48127_sort_link("current", values, "cpu", "CPU")}</th>'
        f'<th>{_v48127_sort_link("current", values, "ram", "RAM")}</th>'
        f'<th>{_v48127_sort_link("current", values, "disk", "DISK")}</th>'
        f'<th>{_v48127_sort_link("current", values, "duration", "ABUSE SINCE")}</th>'
        f'<th>{_v48127_sort_link("current", values, "last_seen", "LAST SEEN")}</th>'
    )
    return f"""
    <div class="abuse-kpis-v48126"><div><span>Filtered</span><b>{total}</b></div><div><span>Network</span><b>{counts['network']}</b></div><div><span>CPU</span><b>{counts['cpu']}</b></div><div><span>RAM</span><b>{counts['ram']}</b></div><div><span>Disk</span><b>{counts['disk']}</b></div></div>
    <div class="card"><div class="section-head"><div><h3>Current Abuse</h3><p>Live sustained Abuse only. Click a column heading to sort like the classic table.</p></div><div class="count-badges"><span>Matched <b>{total}</b></span><span>Page <b>{values['page']}/{pages}</b></span><span>Policy <b>v{cfg['revision']}</b></span></div></div>
    <div class="table-wrap"><table class="abuse-current-v48128"><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>{_v48126_pagination('current', values, total)}</div>"""

def _v48127_event_where(values):
    cutoff = now_ts() - _v48126_range_seconds(values["range"])
    where = [
        "(i.status='open' OR COALESCE(i.ended_at,i.last_event_at)>=?)",
        _v48126_visible_sql("ni", "vi"),
        _v48126_type_condition("i", values["type"]),
        "i.max_severity>=?",
    ]
    params = [cutoff, values["min_severity"]]
    if values["node"]:
        where.append("i.node=?")
        params.append(values["node"])
    if values["status"] in {"open", "closed"}:
        where.append("i.status=?")
        params.append(values["status"])
    if values["q"]:
        pattern = like_pattern(values["q"])
        where.append("(i.node LIKE ? OR i.vm_uuid LIKE ? OR i.abuse_flags LIKE ? OR i.primary_type LIKE ?)")
        params.extend([pattern, pattern, pattern, pattern])
    return where, params

def _v48127_event_groups(values):
    values["limit"] = min(values["limit"], 200)
    where, params = _v48127_event_where(values)
    where_sql = " AND ".join(where)
    now = now_ts()
    duration_expr = f"CASE WHEN i.status='open' THEN MAX(0,{now}-i.started_at) ELSE MAX(0,COALESCE(i.duration_seconds,COALESCE(i.ended_at,i.last_event_at)-i.started_at)) END"
    aggregate_map = {
        "occurrences": "occurrences",
        "active": "active_count",
        "duration": "total_duration",
        "longest": "longest_duration",
        "severity": "max_severity",
        "last_seen": "last_seen",
        "node": "node COLLATE NOCASE",
        "uuid": "vm_uuid COLLATE NOCASE",
    }
    sort = values.get("sort") or "occurrences"
    order = values.get("order") or "desc"
    sort_expr = aggregate_map.get(sort, "occurrences")
    order_sql = f"{sort_expr} {'ASC' if order == 'asc' else 'DESC'}"
    offset = (values["page"] - 1) * values["limit"]
    conn = db()
    try:
        total = safe_int(conn.execute(f"""
          SELECT COUNT(*) FROM (
            SELECT i.node,i.vm_uuid
            FROM vm_abuse_incidents i
            LEFT JOIN node_inventory ni ON ni.node=i.node
            LEFT JOIN vm_inventory vi ON vi.node=i.node AND vi.vm_uuid=i.vm_uuid
            WHERE {where_sql}
            GROUP BY i.node,i.vm_uuid
          ) grouped
        """, params).fetchone()[0], 0)
        rows = conn.execute(f"""
          SELECT i.node AS node,i.vm_uuid AS vm_uuid,
                 COUNT(*) AS occurrences,
                 SUM(CASE WHEN i.status='open' THEN 1 ELSE 0 END) AS active_count,
                 SUM({duration_expr}) AS total_duration,
                 MAX({duration_expr}) AS longest_duration,
                 MAX(i.max_severity) AS max_severity,
                 MAX(COALESCE(i.ended_at,i.last_event_at,i.started_at)) AS last_seen,
                 GROUP_CONCAT(i.abuse_flags, ',') AS all_flags,
                 GROUP_CONCAT(i.primary_type, ',') AS all_types
          FROM vm_abuse_incidents i
          LEFT JOIN node_inventory ni ON ni.node=i.node
          LEFT JOIN vm_inventory vi ON vi.node=i.node AND vi.vm_uuid=i.vm_uuid
          WHERE {where_sql}
          GROUP BY i.node,i.vm_uuid
          ORDER BY {order_sql},i.node COLLATE NOCASE,i.vm_uuid COLLATE NOCASE
          LIMIT ? OFFSET ?
        """, params + [values["limit"], offset]).fetchall()

        details = defaultdict(list)
        if rows:
            pairs = [(str(row[0]), str(row[1])) for row in rows]
            placeholders = ",".join(["(?,?)"] * len(pairs))
            pair_params = [item for pair in pairs for item in pair]
            detail_rows = conn.execute(f"""
              SELECT i.id,i.node,i.vm_uuid,i.started_at,i.ended_at,i.duration_seconds,
                     i.max_severity,i.abuse_flags,i.primary_type,i.event_count,i.last_event_at,i.status
              FROM vm_abuse_incidents i
              LEFT JOIN node_inventory ni ON ni.node=i.node
              LEFT JOIN vm_inventory vi ON vi.node=i.node AND vi.vm_uuid=i.vm_uuid
              WHERE {where_sql}
                AND (i.node,i.vm_uuid) IN ({placeholders})
              ORDER BY i.node COLLATE NOCASE,i.vm_uuid COLLATE NOCASE,i.started_at DESC,i.id DESC
            """, params + pair_params).fetchall()
            for detail in detail_rows:
                details[(str(detail[1]), str(detail[2]))].append(detail)
        return rows, total, details
    finally:
        conn.close()

def _v48127_event_detail_table(items):
    now = now_ts()
    cfg = get_abuse_settings()
    body = ""
    for index, row in enumerate(items, 1):
        iid, node, uuid, started, ended, duration, maxsev, flags, ptype, event_count, last_event, status = row
        effective_end = now if status == "open" else safe_int(ended or last_event, started)
        effective_duration = max(0, effective_end - safe_int(started, 0))
        state = '<span class="status-chip status-active">ACTIVE</span>' if status == "open" else '<span class="status-chip status-recovered">RECOVERED</span>'
        body += f"""<tr>
          <td>{index}</td><td>{state}</td><td>{fmt_full(started)}</td>
          <td>{'<b>Active now</b>' if status == 'open' else fmt_full(effective_end)}</td>
          <td><b>{_v48126_duration(effective_duration)}</b></td>
          <td><b>{safe_float(maxsev,0):.2f}x</b></td>
          <td><div class="abuse-reasons">{_v48126_reason_badges(flags,cfg)}</div></td>
          <td class="num">{safe_int(event_count,0)}</td>
        </tr>"""
    if not body:
        body = '<tr><td colspan="8" class="empty">No occurrence details</td></tr>'
    return f"""<div class="event-occurrence-wrap"><table class="event-occurrence-table"><thead><tr><th>#</th><th>STATE</th><th>STARTED</th><th>ENDED</th><th>DURATION</th><th>MAX SEVERITY</th><th>REASON</th><th>RAW EVENTS</th></tr></thead><tbody>{body}</tbody></table></div>"""

def _v48127_events_page(values):
    rows, total, details = _v48127_event_groups(values)
    cfg = get_abuse_settings()
    body = ""
    rank_start = (values["page"] - 1) * values["limit"]
    for index, row in enumerate(rows, 1):
        node, uuid, occurrences, active_count, total_duration, longest_duration, max_severity, last_seen, all_flags, all_types = row
        key = (str(node), str(uuid))
        detail_id = f"abuse-events-{rank_start + index}"
        href = url_for("node_page", node=node, period="1h", q=uuid)
        primary = _v48126_primary_type(all_flags or all_types or "")
        repeat_label = f"{safe_int(occurrences,0)} times"
        if safe_int(occurrences, 0) == 1:
            repeat_label = "1 time"
        body += f"""<tr class="event-vm-row" data-event-target="{detail_id}" tabindex="0">
          <td class="rank-cell">{rank_start + index}</td>
          <td class="identity-cell"><div class="node-line"><a href="{escape(href, quote=True)}"><b>{escape(str(node))}</b></a></div><div class="uuid-line"><a class="mono" href="{escape(href, quote=True)}">{escape(str(uuid))}</a><button type="button" class="copy-btn" data-copy="{escape(str(uuid), quote=True)}" title="Copy UUID">⧉</button></div></td>
          <td><span class="repeat-count-v48128">{repeat_label}</span>{f'<small class="row-sub active-text">{safe_int(active_count,0)} active now</small>' if safe_int(active_count,0) else '<small class="row-sub">Recovered</small>'}</td>
          <td><b>{_v48126_duration(total_duration)}</b></td>
          <td>{_v48126_duration(longest_duration)}</td>
          <td><b>{safe_float(max_severity,0):.2f}x</b></td>
          <td><span class="type-chip type-{escape(primary)}">{escape(primary.upper())}</span><div class="abuse-reasons compact-reasons-v48128">{_v48126_reason_badges(all_flags,cfg)}</div></td>
          <td>{fmt_full(last_seen)}</td>
          <td><button type="button" class="btn event-toggle-v48128" data-event-toggle="{detail_id}">View {safe_int(occurrences,0)} occurrence{'s' if safe_int(occurrences,0)!=1 else ''}</button></td>
        </tr>
        <tr id="{detail_id}" class="event-detail-row-v48128" hidden><td colspan="9">{_v48127_event_detail_table(details.get(key, []))}</td></tr>"""
    if not body:
        body = '<tr><td colspan="9" class="empty">No visible VM Abuse event matches the selected filters</td></tr>'
    pages = max(1, math.ceil(total / values["limit"]))
    headers = (
        '<th>#</th>'
        f'<th>{_v48127_sort_link("events", values, "node", "NODE / VM", "asc")}</th>'
        f'<th>{_v48127_sort_link("events", values, "occurrences", "ABUSE COUNT")}</th>'
        f'<th>{_v48127_sort_link("events", values, "duration", "TOTAL DURATION")}</th>'
        f'<th>{_v48127_sort_link("events", values, "longest", "LONGEST")}</th>'
        f'<th>{_v48127_sort_link("events", values, "severity", "MAX SEVERITY")}</th>'
        '<th>PRIMARY / REASONS</th>'
        f'<th>{_v48127_sort_link("events", values, "last_seen", "LAST ABUSE")}</th>'
        '<th>DETAIL</th>'
    )
    return f"""
    <div class="card"><div class="section-head"><div><h3>Abuse Events by VM</h3><p>One row per VM. Abuse Count is the number of separate STARTED → RECOVERED occurrences in the selected window. Click the row or View button for exact start and end times.</p></div><div class="count-badges"><span>VM matched <b>{total}</b></span><span>Window <b>{escape(values['range'])}</b></span><span>Retention <b>7 days</b></span><span>Page <b>{values['page']}/{pages}</b></span></div></div>
    <div class="table-wrap"><table class="abuse-events-v48128"><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>{_v48126_pagination('events', values, total)}</div>"""

def vm_abuse_page_v48127():
    tab = (request.args.get("tab") or "current").strip().lower()
    if tab in {"history", "incidents", "summary", "events", "raw", "raw-events"}:
        tab = "events"
    if tab not in {"current", "events"}:
        tab = "current"
    values = _v48127_filter_values()
    if tab == "events":
        values["limit"] = min(values["limit"], 200)
    if tab == "current" and values["sort"] not in {"node", "uuid", "severity", "network", "pps", "cpu", "ram", "disk", "duration", "last_seen"}:
        values["sort"] = "severity"
    if tab == "events" and values["sort"] not in {"node", "uuid", "occurrences", "active", "duration", "longest", "severity", "last_seen"}:
        values["sort"] = "occurrences"
    nodes = _v48126_visible_nodes()
    cfg = get_abuse_settings()
    content = f"""<div class="card page-hero"><div><span class="eyebrow">VM ABUSE</span><h2>Abuse Monitor</h2><p>Current Abuse for live action, Abuse Events for repeat history. No ranking or raw-event clutter on the dashboard.</p></div><div class="hero-meta"><span>Policy <b>v{cfg['revision']}</b></span><span>Engine <b>{ABUSE_ENGINE_VERSION}</b></span><span>Retention <b>7 days</b></span></div></div>
    <div class="card abuse-toolbar abuse-toolbar-v48128">{_v48127_tabs(tab)}{_v48127_filter_form(tab, values, nodes)}</div>
    <details class="card policy-fold"><summary>Current policy</summary>{_public_abuse_policy(cfg)}</details>"""
    if tab == "current":
        content += _v48127_current_page(values)
    else:
        content += _v48127_events_page(values)
    return page("VM Abuse", content)

app.view_functions["vm_abuse_page"] = vm_abuse_page_v48127

V48127_UI_CSS = r"""
<style id="v48127-simple-abuse-ui">
.abuse-toolbar-v48128{display:grid!important;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:14px}.abuse-tabs-v48128{display:grid!important;grid-template-columns:1fr 1fr;min-width:330px;margin:0!important}.abuse-tabs-v48128 a{text-align:center;white-space:nowrap}.abuse-filter-v48128{justify-content:flex-end!important;margin:0!important}.abuse-filter-v48128 input[name=q]{min-width:260px}
.abuse-current-v48128{min-width:1900px;table-layout:fixed}.abuse-current-v48128 th:nth-child(1){width:48px}.abuse-current-v48128 th:nth-child(2){width:290px}.abuse-current-v48128 th:nth-child(3){width:270px}.abuse-current-v48128 th:nth-child(4),.abuse-current-v48128 th:nth-child(5){width:210px}.abuse-current-v48128 th:nth-child(6){width:125px}.abuse-current-v48128 th:nth-child(7){width:170px}.abuse-current-v48128 th:nth-child(8){width:220px}.abuse-current-v48128 th:nth-child(9),.abuse-current-v48128 th:nth-child(10){width:170px}
.abuse-events-v48128{min-width:1460px;table-layout:fixed}.abuse-events-v48128 th:nth-child(1){width:48px}.abuse-events-v48128 th:nth-child(2){width:300px}.abuse-events-v48128 th:nth-child(3){width:125px}.abuse-events-v48128 th:nth-child(4),.abuse-events-v48128 th:nth-child(5){width:140px}.abuse-events-v48128 th:nth-child(6){width:120px}.abuse-events-v48128 th:nth-child(7){width:270px}.abuse-events-v48128 th:nth-child(8){width:170px}.abuse-events-v48128 th:nth-child(9){width:150px}.event-vm-row{cursor:pointer}.event-vm-row:hover{background:#f6f9ff!important}.repeat-count-v48128{display:inline-flex;align-items:center;justify-content:center;min-width:62px;padding:6px 9px;border-radius:999px;background:#fff1f2;border:1px solid #fecdd3;color:#b42318;font-size:12px;font-weight:900}.active-text{color:#b42318!important;font-weight:800}.compact-reasons-v48128{margin-top:6px;max-height:48px;overflow:hidden}.event-detail-row-v48128>td{padding:0 14px 14px!important;background:#f8fafc!important}.event-occurrence-wrap{border:1px solid #dbe4ef;border-radius:12px;background:#fff;overflow:auto;box-shadow:inset 0 1px 0 rgba(255,255,255,.7)}.event-occurrence-table{min-width:1050px;width:100%;border-collapse:separate;border-spacing:0}.event-occurrence-table th{background:#edf3fb!important}.event-occurrence-table td{background:#fff!important}.status-active{background:#fee2e2!important;color:#b91c1c!important;border-color:#fecaca!important}.status-recovered{background:#dcfce7!important;color:#166534!important;border-color:#bbf7d0!important}.event-toggle-v48128{white-space:nowrap}.event-detail-row-v48128[hidden]{display:none!important}
html[data-theme=dark] .event-vm-row:hover{background:#0d1c2d!important}html[data-theme=dark] .event-detail-row-v48128>td{background:#07111b!important}html[data-theme=dark] .event-occurrence-wrap,html[data-theme=dark] .event-occurrence-table td{background:#0a1624!important;border-color:#2b4260!important}html[data-theme=dark] .event-occurrence-table th{background:#10243a!important}
@media(max-width:1300px){.abuse-toolbar-v48128{grid-template-columns:1fr}.abuse-tabs-v48128{min-width:0;width:100%;max-width:460px}.abuse-filter-v48128{justify-content:flex-start!important}}
@media(max-width:760px){.abuse-tabs-v48128{max-width:none}.abuse-filter-v48128 input[name=q]{min-width:100%;width:100%}}
</style>
"""

V48127_UI_JS = r"""
<script id="v48127-simple-abuse-interactions">
(function(){
  function toggle(id){
    var row=document.getElementById(id);if(!row)return;
    var opening=row.hasAttribute('hidden');
    if(opening)row.removeAttribute('hidden');else row.setAttribute('hidden','');
    document.querySelectorAll('[data-event-toggle="'+id+'"]').forEach(function(btn){
      var count=(btn.textContent.match(/\d+/)||[''])[0];
      btn.textContent=(opening?'Hide ':'View ')+count+' occurrence'+(count==='1'?'':'s');
    });
  }
  document.addEventListener('click',function(e){
    var button=e.target.closest('[data-event-toggle]');
    if(button){e.preventDefault();e.stopPropagation();toggle(button.getAttribute('data-event-toggle'));return;}
    var row=e.target.closest('.event-vm-row[data-event-target]');
    if(row && !e.target.closest('a,button,input,select'))toggle(row.getAttribute('data-event-target'));
  });
  document.addEventListener('keydown',function(e){
    var row=e.target.closest&&e.target.closest('.event-vm-row[data-event-target]');
    if(row&&(e.key==='Enter'||e.key===' ')){e.preventDefault();toggle(row.getAttribute('data-event-target'));}
  });
})();
</script>
"""

_page_v48127_base = page

def page(title, content):
    response = _page_v48127_base(title, content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace("</head>", V48127_UI_CSS + "</head>", 1)
        html = html.replace("</body>", V48127_UI_JS + "</body>", 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.12.7 simplified Abuse UI")
    return response

# exact event minutes, and synchronized Admin cleanup.
V48128_VERSION = "48.12.8"

def _v48128_minutes(seconds):
    seconds = max(0, safe_int(seconds, 0))
    if seconds == 0:
        return 0
    return max(1, int(round(seconds / 60.0)))

def _v48128_low_usable_ratio(threshold, actual):
    """Bound inverse RAM severity to an intuitive 1.00x..2.00x range.

    Old code used threshold / max(actual, 0.1), which turned 5% / 0.1%
    into 50x and made a single inverse metric dominate the whole table.
    New meaning: 1x at the threshold, 2x at zero usable memory.
    """
    threshold = max(0.0, safe_float(threshold, 0.0))
    actual = max(0.0, safe_float(actual, 0.0))
    if threshold <= 0 or actual > threshold:
        return 0.0
    return min(2.0, max(1.0, 1.0 + ((threshold - actual) / threshold)))

# Authoritative RAM-hit override. refresh_fast_current_state resolves this
# global at runtime, so future Agent pushes immediately use the bounded ratio.
def _v48126_ram_hit(cfg, metrics):
    if not cfg.get("ram_effective_enabled"):
        return False, []
    ratios = []
    if cfg["ram_rss_percent"] > 0 and metrics["rss_percent"] >= cfg["ram_rss_percent"]:
        ratios.append(metrics["rss_percent"] / cfg["ram_rss_percent"])
    if cfg["ram_guest_used_percent"] > 0 and metrics["guest_used_percent"] >= cfg["ram_guest_used_percent"]:
        ratios.append(metrics["guest_used_percent"] / cfg["ram_guest_used_percent"])
    if (
        cfg["ram_low_usable_percent"] > 0 and metrics["guest_valid"]
        and metrics["usable_percent"] <= cfg["ram_low_usable_percent"]
    ):
        ratios.append(_v48128_low_usable_ratio(cfg["ram_low_usable_percent"], metrics["usable_percent"]))
    return bool(ratios), ratios

def _v48128_severity_components(record, cfg):
    flags = set(_api_parse_flags(record.get("abuse_flags", "")))
    parts = []

    def add(label, actual, threshold, inverse=False):
        actual = safe_float(actual, 0.0)
        threshold = safe_float(threshold, 0.0)
        if threshold <= 0:
            return
        ratio = _v48128_low_usable_ratio(threshold, actual) if inverse else actual / threshold
        if ratio >= 1.0:
            parts.append((ratio, label, actual, threshold, inverse))

    if "NETWORK_RX_PPS" in flags:
        add("RX PPS", record.get("rx_pps"), cfg.get("network_pps"))
    if "NETWORK_TX_PPS" in flags:
        add("TX PPS", record.get("tx_pps"), cfg.get("network_pps"))
    if "NETWORK_RX_AVG_MBPS" in flags:
        add("RX AVG Mbps", record.get("rx_mbps"), cfg.get("network_avg_mbps"))
    if "NETWORK_TX_AVG_MBPS" in flags:
        add("TX AVG Mbps", record.get("tx_mbps"), cfg.get("network_avg_mbps"))
    if "CPU_SUSTAINED" in flags:
        add("CPU Full", record.get("cpu_full_percent"), cfg.get("cpu_full_percent"))
    if "RAM_SUSTAINED" in flags:
        add("RAM Host RSS", record.get("ram_rss_percent"), cfg.get("ram_rss_percent"))
        add("RAM Guest Used", record.get("ram_guest_used_percent"), cfg.get("ram_guest_used_percent"))
        usable = safe_float(record.get("ram_usable_percent"), -1)
        if usable >= 0:
            add("RAM Low Usable", usable, cfg.get("ram_low_usable_percent"), inverse=True)
    if "DISK_SUSTAINED" in flags:
        read_bps = safe_float(record.get("disk_read_bps"), 0)
        write_bps = safe_float(record.get("disk_write_bps"), 0)
        read_iops = safe_float(record.get("disk_read_iops"), 0)
        write_iops = safe_float(record.get("disk_write_iops"), 0)
        add("Disk Read", read_bps, cfg.get("disk_read_bps"))
        add("Disk Write", write_bps, cfg.get("disk_write_bps"))
        add("Disk Total", read_bps + write_bps, cfg.get("disk_bps"))
        add("Disk IOPS", read_iops + write_iops, cfg.get("disk_iops"))
    parts.sort(key=lambda item: item[0], reverse=True)
    return parts

def _v48128_ratio_block(record, cfg):
    parts = _v48128_severity_components(record, cfg)
    stored = max(0.0, safe_float(record.get("severity"), 0.0))
    if not parts:
        return f'<div class="severity-line"><b>{stored:.2f}x</b><span>stored ratio</span></div><small class="ratio-help">No active-rule component available</small>'
    ratio, label, actual, threshold, inverse = parts[0]
    if inverse:
        formula = f"{label}: usable {actual:.2f}% vs low threshold {threshold:.2f}%"
    elif "Mbps" in label:
        formula = f"{label}: {actual:.2f} / {threshold:.2f} Mbps"
    elif "PPS" in label or "IOPS" in label:
        formula = f"{label}: {actual:,.2f} / {threshold:,.2f}"
    elif "Disk" in label:
        formula = f"{label}: {human_rate(actual)} / {human_rate(threshold)}"
    else:
        formula = f"{label}: {actual:.2f}% / {threshold:.2f}%"
    return (
        f'<div class="severity-line"><b>{ratio:.2f}x</b><span>{escape(label)}</span></div>'
        f'<small class="ratio-help" title="{escape(formula, quote=True)}">{escape(formula)}</small>'
    )

def _v48128_group_sort_header(title, options, current_sort, current_order):
    active_label = next((label for label, key, _link in options if key == current_sort), options[0][0])
    arrow = ""
    if any(key == current_sort for _label, key, _link in options):
        arrow = " ↓" if current_order == "desc" else " ↑"
    option_html = "".join(f'<div class="ram-sort-option">{link}</div>' for _label, _key, link in options)
    return (
        '<div class="ram-compact-head">'
        f'<div class="ram-main-sort">{escape(title)}</div>'
        '<details class="ram-sort-menu">'
        f'<summary title="Choose sort metric">{escape(active_label)}{arrow} ▾</summary>'
        f'<div class="ram-sort-options">{option_html}</div>'
        '</details></div>'
    )

def _v48128_filter_values():
    values = _v48127_filter_values()
    return values

def _v48128_filter_form(tab, values, nodes):
    node_options = '<option value="">All nodes</option>' + ''.join(
        f'<option value="{escape(node, quote=True)}" {"selected" if node == values["node"] else ""}>{escape(node)}</option>'
        for node in nodes
    )
    type_options = ''.join(
        f'<option value="{key}" {"selected" if key == values["type"] else ""}>{label}</option>'
        for key, label in (("all", "All abuse types"), ("network", "Network"), ("cpu", "CPU"), ("ram", "RAM"), ("disk", "Disk"))
    )
    limits = (50, 100, 200, 500) if tab == "current" else (50, 100, 200)
    limit_options = ''.join(
        f'<option value="{number}" {"selected" if number == values["limit"] else ""}>{number} / page</option>'
        for number in limits
    )
    common = f"""
      <input type="hidden" name="tab" value="{escape(tab, quote=True)}">
      <input name="q" value="{escape(values['q'], quote=True)}" placeholder="Search node / VM UUID / abuse type">
      <select name="node">{node_options}</select>
      <select name="type">{type_options}</select>
      <input type="number" name="min_severity" min="0" step="0.1" value="{values['min_severity'] or ''}" placeholder="Min ratio">
    """
    if tab == "events":
        range_options = ''.join(
            f'<option value="{key}" {"selected" if key == values["range"] else ""}>{label}</option>'
            for key, label in (("1h", "Last 1h"), ("6h", "Last 6h"), ("24h", "Last 24h"), ("2d", "Last 2d"), ("7d", "Last 7d"))
        )
        status_options = ''.join(
            f'<option value="{key}" {"selected" if key == values["status"] else ""}>{label}</option>'
            for key, label in (("all", "All states"), ("open", "Active now"), ("closed", "Recovered"))
        )
        sort_options = ''.join(
            f'<option value="{key}" {"selected" if key == values["sort"] else ""}>Sort: {label}</option>'
            for key, label in (("occurrences", "Abuse count"), ("duration", "Total minutes"), ("longest", "Longest minutes"), ("severity", "Max ratio"), ("last_seen", "Last abuse"), ("node", "Node / VM"))
        )
        order_options = ''.join(
            f'<option value="{key}" {"selected" if key == values["order"] else ""}>{label}</option>'
            for key, label in (("desc", "Descending"), ("asc", "Ascending"))
        )
        extra = f'<select name="range">{range_options}</select><select name="status">{status_options}</select><select name="sort">{sort_options}</select><select name="order">{order_options}</select>'
    else:
        extra = f'<input type="hidden" name="sort" value="{escape(values["sort"], quote=True)}"><input type="hidden" name="order" value="{escape(values["order"], quote=True)}">'
    return f"""
    <form class="search compact-search abuse-filter-v48128 abuse-filter-v48128" method="get" action="{url_for('vm_abuse_page')}">
      {common}{extra}
      <select name="limit">{limit_options}</select>
      <button type="submit">Filter</button>
      <a class="clear" href="{url_for('vm_abuse_page', tab=tab)}">Reset</a>
    </form>"""

def _v48128_current_rows(values):
    cfg = get_abuse_settings()
    where = [
        "a.is_abuse=1", "a.last_seen>=?", "a.policy_revision=?", "a.engine_version=?",
        _v48126_visible_sql("ni", "vi"), _v48126_type_condition("a", values["type"]), "a.severity>=?",
    ]
    params = [now_ts() - FAST_CURRENT_STALE_SECONDS, cfg["revision"], ABUSE_ENGINE_VERSION, values["min_severity"]]
    if values["node"]:
        where.append("a.node=?")
        params.append(values["node"])
    if values["q"]:
        pattern = like_pattern(values["q"])
        where.append("(a.node LIKE ? OR a.vm_uuid LIKE ? OR a.abuse_flags LIKE ?)")
        params.extend([pattern, pattern, pattern])

    sort = values.get("sort") or "severity"
    order = values.get("order") or "desc"
    sort_map = {
        "node": "a.node COLLATE NOCASE", "uuid": "a.vm_uuid COLLATE NOCASE", "type": "a.abuse_flags COLLATE NOCASE",
        "severity": "a.severity", "rx_mbps": "COALESCE(a.rx_mbps,0)", "tx_mbps": "COALESCE(a.tx_mbps,0)",
        "rx_pps": "COALESCE(a.rx_pps,0)", "tx_pps": "COALESCE(a.tx_pps,0)",
        "rx_peak": "COALESCE(a.rx_peak_pps,0)", "tx_peak": "COALESCE(a.tx_peak_pps,0)",
        "cpu": "COALESCE(a.cpu_full_percent,0)", "cpucore": "COALESCE(a.cpu_core_percent,0)",
        "ram": "COALESCE(a.ram_guest_used_percent,-1)",
        "ramused": "CASE WHEN COALESCE(a.ram_guest_used_percent,-1)>=0 THEN MAX(0,COALESCE(a.ram_available_kib,0)-COALESCE(a.ram_usable_kib,0)) ELSE -1 END",
        "ramrss": "COALESCE(a.ram_rss_kib,0)", "ramassigned": "COALESCE(a.ram_current_kib,0)",
        "diskr": "COALESCE(a.disk_read_bps,0)", "diskw": "COALESCE(a.disk_write_bps,0)",
        "readiops": "COALESCE(a.disk_read_iops,0)", "writeiops": "COALESCE(a.disk_write_iops,0)",
        "last_seen": "a.last_seen",
    }
    if sort == "duration":
        order_sql = f"a.abuse_since {'ASC' if order == 'desc' else 'DESC'}"
    else:
        expression = sort_map.get(sort, sort_map["severity"])
        order_sql = f"{expression} {'ASC' if order == 'asc' else 'DESC'}"
    where_sql = " AND ".join(where)
    offset = (values["page"] - 1) * values["limit"]
    conn = db()
    try:
        total = safe_int(conn.execute(f"""SELECT COUNT(*) FROM vm_abuse_state a
            LEFT JOIN node_inventory ni ON ni.node=a.node
            LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
            WHERE {where_sql}""", params).fetchone()[0], 0)
        rows = conn.execute(f"""
            SELECT a.node,a.vm_uuid,a.abuse_since,a.last_seen,a.abuse_flags,a.severity,
                   a.rx_mbps,a.tx_mbps,a.rx_pps,a.tx_pps,a.rx_peak_pps,a.tx_peak_pps,
                   a.cpu_full_percent,a.cpu_core_percent,a.vcpu_current,
                   a.ram_rss_percent,a.ram_guest_used_percent,a.ram_usable_percent,a.ram_streak_seconds,
                   a.ram_current_kib,a.ram_rss_kib,a.ram_available_kib,a.ram_usable_kib,
                   a.disk_read_bps,a.disk_write_bps,a.disk_read_iops,a.disk_write_iops,
                   COALESCE(b.primary_ipv4,'')
            FROM vm_abuse_state a
            LEFT JOIN node_inventory ni ON ni.node=a.node
            LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
            LEFT JOIN node_bridge_addresses_latest b ON b.node=a.node AND b.bridge=?
            WHERE {where_sql}
            ORDER BY {order_sql},a.node COLLATE NOCASE,a.vm_uuid COLLATE NOCASE
            LIMIT ? OFFSET ?
        """, [PUBLIC_BRIDGE] + params + [values["limit"], offset]).fetchall()
        counts = {}
        for key in ("network", "cpu", "ram", "disk"):
            counts[key] = safe_int(conn.execute(f"""SELECT COUNT(*) FROM vm_abuse_state a
              LEFT JOIN node_inventory ni ON ni.node=a.node
              LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
              WHERE a.is_abuse=1 AND a.last_seen>=? AND a.policy_revision=? AND a.engine_version=?
                AND {_v48126_visible_sql('ni','vi')} AND {_v48126_type_condition('a', key)}""",
              (now_ts()-FAST_CURRENT_STALE_SECONDS, cfg["revision"], ABUSE_ENGINE_VERSION)).fetchone()[0], 0)
        return rows, total, counts
    finally:
        conn.close()

def _v48128_current_page(values):
    cfg = get_abuse_settings()
    rows, total, counts = _v48128_current_rows(values)
    body = ""
    rank_start = (values["page"] - 1) * values["limit"]
    for index, row in enumerate(rows, 1):
        (
            node, uuid, started, last_seen, flags, stored_severity,
            rxm, txm, rxp, txp, rxpk, txpk, cpu, core, vcpu,
            rss_pct, guest_pct, usable_pct, ram_streak,
            ram_current, ram_rss, ram_available, ram_usable,
            dr, dw, dri, dwi, ip,
        ) = row
        href = url_for("node_page", node=node, period="1h", q=uuid)
        rec = {
            "abuse_flags": flags, "severity": stored_severity,
            "rx_mbps": rxm, "tx_mbps": txm, "rx_pps": rxp, "tx_pps": txp,
            "cpu_full_percent": cpu, "ram_rss_percent": rss_pct,
            "ram_guest_used_percent": guest_pct, "ram_usable_percent": usable_pct,
            "disk_read_bps": dr, "disk_write_bps": dw,
            "disk_read_iops": dri, "disk_write_iops": dwi,
        }
        ram_html = fmt_vm_ram_block(ram_current, ram_rss, ram_available, 0, ram_usable, compact=True)
        body += f"""<tr>
          <td class="rank-cell">{rank_start + index}</td>
          <td class="identity-cell"><div class="node-line"><a href="{escape(href, quote=True)}"><b>{escape(node)}</b></a>{f'<span>{escape(compact_ipv4(ip))}</span>' if ip else ''}</div><div class="uuid-line"><a class="mono" href="{escape(href, quote=True)}">{escape(uuid)}</a><button type="button" class="copy-btn" data-copy="{escape(uuid, quote=True)}" title="Copy UUID">⧉</button></div></td>
          <td><div class="abuse-reasons">{_v48126_reason_badges(flags,cfg)}</div></td>
          <td class="ratio-cell-v48128">{_v48128_ratio_block(rec,cfg)}</td>
          <td><div class="metric-pair"><div><span>RX AVG</span><b>{safe_float(rxm,0):.2f} Mbps</b></div><div><span>TX AVG</span><b>{safe_float(txm,0):.2f} Mbps</b></div></div></td>
          <td><div class="metric-pair"><div><span>RX AVG</span><b>{fmt_pps_value(rxp)} PPS</b></div><div><span>TX AVG</span><b>{fmt_pps_value(txp)} PPS</b></div></div></td>
          <td><div class="metric-pair"><div><span>RX PEAK</span><b>{fmt_pps_value(rxpk)} PPS</b></div><div><span>TX PEAK</span><b>{fmt_pps_value(txpk)} PPS</b></div></div></td>
          <td class="cpu-polished-cell">{_v48105_cpu_usage_block(core,cpu,vcpu,"Full / assigned vCPU",compact=True)}</td>
          <td class="ram-cell">{ram_html}</td>
          <td><div class="metric-pair"><div><span>READ</span><b>{human_rate(dr)}</b><small>{safe_float(dri,0):,.0f} IOPS</small></div><div><span>WRITE</span><b>{human_rate(dw)}</b><small>{safe_float(dwi,0):,.0f} IOPS</small></div></div></td>
          <td><div class="timeline-cell"><b>{fmt_full(started) if started else '-'}</b><small>{_v48126_duration(safe_int(last_seen,0)-safe_int(started,last_seen))} active</small></div></td>
          <td><div class="timeline-cell"><b>{fmt_full(last_seen)}</b><small>{fmt_push(last_seen)}</small></div></td>
        </tr>"""
    if not body:
        body = '<tr><td colspan="12" class="empty">No visible VM matches the selected Current Abuse filters</td></tr>'
    pages = max(1, math.ceil(total / values["limit"]))
    h = lambda label, key, default="desc": _v48127_sort_link("current", values, key, label, default)
    ram_header = _v48104_ram_sort_header(
        h("RAM", "ram"),
        [h("Guest %", "ram"), h("Used GiB", "ramused"), h("Host RSS", "ramrss"), h("Assigned", "ramassigned")],
        values["sort"], values["order"],
    )
    disk_header = _v48128_group_sort_header("DISK", [
        ("Read", "diskr", h("Read", "diskr")), ("Write", "diskw", h("Write", "diskw")),
        ("Read IOPS", "readiops", h("Read IOPS", "readiops")), ("Write IOPS", "writeiops", h("Write IOPS", "writeiops")),
    ], values["sort"], values["order"])
    headers = (
        '<th>#</th>'
        f'<th>{h("NODE / VM","node","asc")}</th>'
        f'<th>{h("REASON","type","asc")}</th>'
        f'<th>{h("MAX RATIO","severity")}</th>'
        f'<th><div>NETWORK AVG</div><small>{h("RX Mbps","rx_mbps")} · {h("TX Mbps","tx_mbps")}</small></th>'
        f'<th><div>PPS AVG</div><small>{h("RX PPS","rx_pps")} · {h("TX PPS","tx_pps")}</small></th>'
        f'<th><div>PPS PEAK</div><small>{h("RX PEAK","rx_peak")} · {h("TX PEAK","tx_peak")}</small></th>'
        f'<th><div>CPU</div><small>{h("FULL%","cpu")} · {h("CORE%","cpucore")}</small></th>'
        f'<th class="ram-compact-sort-head">{ram_header}</th>'
        f'<th class="ram-compact-sort-head">{disk_header}</th>'
        f'<th>{h("ABUSE TIME","duration")}</th>'
        f'<th>{h("LAST SEEN","last_seen")}</th>'
    )
    return f"""
    <div class="abuse-kpis-v48126"><div><span>Filtered</span><b>{total}</b></div><div><span>Network</span><b>{counts['network']}</b></div><div><span>CPU</span><b>{counts['cpu']}</b></div><div><span>RAM</span><b>{counts['ram']}</b></div><div><span>Disk</span><b>{counts['disk']}</b></div></div>
    <div class="card"><div class="section-head"><div><h3>Current Abuse</h3><p>Top-VM-style table. Every metric has its own sort. MAX RATIO is the largest active-rule threshold ratio, not a weighted score.</p></div><div class="count-badges"><span>Matched <b>{total}</b></span><span>Page <b>{values['page']}/{pages}</b></span><span>Policy <b>v{cfg['revision']}</b></span></div></div>
    <div class="table-wrap"><table class="abuse-current-v48128"><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>
    <div class="table-hint"><b>MAX RATIO</b> = the highest current metric ÷ its configured threshold among active rules. Low-usable RAM uses a bounded 1.00x–2.00x inverse scale, so near-zero usable RAM no longer appears as 50x. Use the metric headers to sort directly.</div>
    {_v48126_pagination('current', values, total)}</div>"""

def _v48128_event_detail_table(items):
    now = now_ts()
    cfg = get_abuse_settings()
    body = ""
    for index, row in enumerate(items, 1):
        iid, node, uuid, started, ended, duration, maxsev, flags, ptype, event_count, last_event, status = row
        effective_end = now if status == "open" else safe_int(ended or last_event, started)
        effective_duration = max(0, effective_end - safe_int(started, 0))
        minutes = _v48128_minutes(effective_duration)
        state = '<span class="status-chip status-active">ACTIVE</span>' if status == "open" else '<span class="status-chip status-recovered">RECOVERED</span>'
        body += f"""<tr>
          <td>{index}</td><td>{state}</td><td>{fmt_full(started)}</td>
          <td>{'<b>Active now</b>' if status == 'open' else fmt_full(effective_end)}</td>
          <td><b>{minutes:,} min</b><small class="row-sub">{_v48126_duration(effective_duration)}</small></td>
          <td><b>{safe_float(maxsev,0):.2f}x</b></td>
          <td><div class="abuse-reasons">{_v48126_reason_badges(flags,cfg)}</div></td>
          <td class="num">{safe_int(event_count,0)}</td>
        </tr>"""
    if not body:
        body = '<tr><td colspan="8" class="empty">No occurrence details</td></tr>'
    return f"""<div class="event-occurrence-wrap"><table class="event-occurrence-table"><thead><tr><th>#</th><th>STATE</th><th>STARTED</th><th>ENDED</th><th>DURATION / MINUTES</th><th>MAX RATIO</th><th>REASON</th><th>RAW EVENTS</th></tr></thead><tbody>{body}</tbody></table></div>"""

def _v48128_events_page(values):
    rows, total, details = _v48127_event_groups(values)
    cfg = get_abuse_settings()
    body = ""
    rank_start = (values["page"] - 1) * values["limit"]
    for index, row in enumerate(rows, 1):
        node, uuid, occurrences, active_count, total_duration, longest_duration, max_severity, last_seen, all_flags, all_types = row
        key = (str(node), str(uuid))
        detail_id = f"abuse-events-{rank_start + index}"
        href = url_for("node_page", node=node, period="1h", q=uuid)
        primary = _v48126_primary_type(all_flags or all_types or "")
        repeat_label = "1 time" if safe_int(occurrences,0) == 1 else f"{safe_int(occurrences,0)} times"
        total_minutes = _v48128_minutes(total_duration)
        longest_minutes = _v48128_minutes(longest_duration)
        body += f"""<tr class="event-vm-row" data-event-target="{detail_id}" tabindex="0">
          <td class="rank-cell">{rank_start + index}</td>
          <td class="identity-cell"><div class="node-line"><a href="{escape(href, quote=True)}"><b>{escape(str(node))}</b></a></div><div class="uuid-line"><a class="mono" href="{escape(href, quote=True)}">{escape(str(uuid))}</a><button type="button" class="copy-btn" data-copy="{escape(str(uuid), quote=True)}" title="Copy UUID">⧉</button></div></td>
          <td><span class="repeat-count-v48128">{repeat_label}</span>{f'<small class="row-sub active-text">{safe_int(active_count,0)} active now</small>' if safe_int(active_count,0) else '<small class="row-sub">Recovered</small>'}</td>
          <td><b>{total_minutes:,} min</b><small class="row-sub">{_v48126_duration(total_duration)}</small></td>
          <td><b>{longest_minutes:,} min</b><small class="row-sub">{_v48126_duration(longest_duration)}</small></td>
          <td><b>{safe_float(max_severity,0):.2f}x</b></td>
          <td><span class="type-chip type-{escape(primary)}">{escape(primary.upper())}</span><div class="abuse-reasons compact-reasons-v48128">{_v48126_reason_badges(all_flags,cfg)}</div></td>
          <td>{fmt_full(last_seen)}</td>
          <td><button type="button" class="btn event-toggle-v48128" data-event-toggle="{detail_id}">View {safe_int(occurrences,0)} occurrence{'s' if safe_int(occurrences,0)!=1 else ''}</button></td>
        </tr>
        <tr id="{detail_id}" class="event-detail-row-v48128" hidden><td colspan="9">{_v48128_event_detail_table(details.get(key, []))}</td></tr>"""
    if not body:
        body = '<tr><td colspan="9" class="empty">No visible VM Abuse event matches the selected filters</td></tr>'
    pages = max(1, math.ceil(total / values["limit"]))
    headers = (
        '<th>#</th>'
        f'<th>{_v48127_sort_link("events", values, "node", "NODE / VM", "asc")}</th>'
        f'<th>{_v48127_sort_link("events", values, "occurrences", "ABUSE COUNT")}</th>'
        f'<th>{_v48127_sort_link("events", values, "duration", "TOTAL MINUTES")}</th>'
        f'<th>{_v48127_sort_link("events", values, "longest", "LONGEST MINUTES")}</th>'
        f'<th>{_v48127_sort_link("events", values, "severity", "MAX RATIO")}</th>'
        '<th>PRIMARY / REASONS</th>'
        f'<th>{_v48127_sort_link("events", values, "last_seen", "LAST ABUSE")}</th>'
        '<th>DETAIL</th>'
    )
    return f"""
    <div class="card"><div class="section-head"><div><h3>Abuse Events by VM</h3><p>One row per VM. Count, total minutes, longest minutes, max ratio and last abuse are all sortable. Expand a VM for every exact start/end occurrence.</p></div><div class="count-badges"><span>VM matched <b>{total}</b></span><span>Window <b>{escape(values['range'])}</b></span><span>Retention <b>7 days</b></span><span>Page <b>{values['page']}/{pages}</b></span></div></div>
    <div class="table-wrap"><table class="abuse-events-v48128"><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>{_v48126_pagination('events', values, total)}</div>"""

# Keep Admin raw-event cleanup and the derived incident table consistent.
def clear_abuse_events_v48128():
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
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("BEGIN IMMEDIATE")
        if mode == "all":
            if confirm_text != "CLEAR ALL ABUSE LOGS":
                conn.rollback()
                return redirect(url_for("admin_abuse_page", err="Confirmation text did not match."))
            cur = conn.execute("DELETE FROM vm_abuse_events")
            conn.execute("DELETE FROM vm_abuse_incidents")
        elif mode == "matching":
            if confirm_text != "CLEAR MATCHING":
                conn.rollback()
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
            _v48126_rebuild_incidents(conn)
        else:
            ids = sorted({safe_int(x,0) for x in request.form.getlist("event_ids") if safe_int(x,0)>0})
            if not ids:
                conn.rollback()
                return redirect(url_for("admin_abuse_page", msg="No abuse event was selected."))
            placeholders = ",".join("?" for _ in ids)
            cur = conn.execute(f"DELETE FROM vm_abuse_events WHERE id IN ({placeholders})", ids)
            _v48126_rebuild_incidents(conn)
        deleted = max(0, safe_int(cur.rowcount, 0))
        conn.commit()
    finally:
        conn.close()
    actor = dashboard_username() or get_admin_username()
    log_account_event("abuse_history_cleared", username=actor, realm="admin", role="admin", detail=f"mode={mode};deleted={deleted};incidents=synchronized;q={q};event_type={event_type}"[:700])
    return redirect(url_for("admin_abuse_page", msg=f"Deleted {deleted} raw event record(s) and synchronized Abuse Events."))

app.view_functions["clear_abuse_events"] = clear_abuse_events_v48128

@app.route("/admin/abuse-vm-data/clear", methods=["POST"])
def clear_vm_abuse_data_v48128():
    deny = require_admin()
    if deny:
        return deny
    node = (request.form.get("node") or "").strip()
    vm_uuid = (request.form.get("vm_uuid") or "").strip()
    confirm_text = (request.form.get("confirm_text") or "").strip()
    reset_current = request.form.get("reset_current") == "1"
    if not node or not vm_uuid:
        return redirect(url_for("admin_abuse_page", err="Node and VM UUID are required."))
    if confirm_text != "CLEAR VM ABUSE DATA":
        return redirect(url_for("admin_abuse_page", err="Confirmation text did not match."))
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        raw_deleted = max(0, safe_int(conn.execute("DELETE FROM vm_abuse_events WHERE node=? AND vm_uuid=?", (node, vm_uuid)).rowcount, 0))
        incident_deleted = max(0, safe_int(conn.execute("DELETE FROM vm_abuse_incidents WHERE node=? AND vm_uuid=?", (node, vm_uuid)).rowcount, 0))
        current_deleted = 0
        if reset_current:
            current_deleted = max(0, safe_int(conn.execute("DELETE FROM vm_abuse_state WHERE node=? AND vm_uuid=?", (node, vm_uuid)).rowcount, 0))
        conn.commit()
    finally:
        conn.close()
    actor = dashboard_username() or get_admin_username()
    log_account_event("vm_abuse_data_cleared", username=actor, realm="admin", role="admin", detail=f"node={node};vm={vm_uuid};raw={raw_deleted};incidents={incident_deleted};reset_current={reset_current}"[:700])
    return redirect(url_for("admin_abuse_page", msg=f"Cleared Abuse data for {vm_uuid}: {raw_deleted} raw event(s), {incident_deleted} occurrence(s)" + ("; current state reset." if reset_current else ".")))

_admin_abuse_page_v48128_base = app.view_functions.get("admin_abuse_page")

def admin_abuse_page_v48128():
    response = _admin_abuse_page_v48128_base()
    try:
        html = response.get_data(as_text=True)
        old_hint = 'Clear deletes only saved event records from <b>vm_abuse_events</b>. It does not hide or reset a VM that is currently over threshold; Current Abuse remains truthful and will generate new events on future state transitions.'
        new_hint = 'Clear deletes raw records from <b>vm_abuse_events</b> and synchronizes the derived <b>vm_abuse_incidents</b> table used by Dashboard → Abuse Events. It does not reset a VM that is currently over threshold; Current Abuse remains truthful.'
        html = html.replace(old_hint, new_hint)
        marker = '<div class="card vm-table-card">\n      <div class="table-title-row"><h3>Abuse History Cleanup</h3>'
        direct_card = f'''<div class="card admin-abuse-direct-v48128"><div class="table-title-row"><div><h3>Clear one VM Abuse data</h3><div class="table-hint">Deletes the selected VM's raw Abuse history and grouped Abuse Events. Current state is preserved unless explicitly reset.</div></div></div><form class="bulk-bar" method="post" action="{url_for('clear_vm_abuse_data_v48128')}" onsubmit="return confirm('Permanently clear Abuse data for this VM?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><label>Node<input name="node" required placeholder="EPYC2SG"></label><label>VM UUID<input name="vm_uuid" required placeholder="VM UUID"></label><label>Type <b>CLEAR VM ABUSE DATA</b><input name="confirm_text" required placeholder="CLEAR VM ABUSE DATA"></label><label class="enable-line"><input type="checkbox" name="reset_current" value="1"> Also reset current Abuse state/streak</label><button class="btn-danger" type="submit">Clear VM Abuse data</button></form><div class="table-hint"><b>Reset current</b> is temporary if the VM is still over policy: it will be evaluated again from the next accepted Agent cycles.</div></div>'''
        html = html.replace(marker, direct_card + marker, 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.12.8 Admin Abuse management layer")
    return response

app.view_functions["admin_abuse_page"] = admin_abuse_page_v48128

def vm_abuse_page_v48128():
    tab = (request.args.get("tab") or "current").strip().lower()
    if tab in {"history", "incidents", "summary", "events", "raw", "raw-events"}:
        tab = "events"
    if tab not in {"current", "events"}:
        tab = "current"
    values = _v48128_filter_values()
    if tab == "events":
        values["limit"] = min(values["limit"], 200)
    current_sorts = {"node", "uuid", "type", "severity", "rx_mbps", "tx_mbps", "rx_pps", "tx_pps", "rx_peak", "tx_peak", "cpu", "cpucore", "ram", "ramused", "ramrss", "ramassigned", "diskr", "diskw", "readiops", "writeiops", "duration", "last_seen"}
    event_sorts = {"node", "uuid", "occurrences", "active", "duration", "longest", "severity", "last_seen"}
    if tab == "current" and values["sort"] not in current_sorts:
        values["sort"] = "severity"
    if tab == "events" and values["sort"] not in event_sorts:
        values["sort"] = "occurrences"
    nodes = _v48126_visible_nodes()
    cfg = get_abuse_settings()
    content = f"""<div class="card page-hero"><div><span class="eyebrow">VM ABUSE</span><h2>Abuse Monitor</h2><p>Current Abuse uses a Top-VM-style sortable metric table. Abuse Events groups repeat occurrences and shows exact minutes.</p></div><div class="hero-meta"><span>Policy <b>v{cfg['revision']}</b></span><span>Engine <b>{ABUSE_ENGINE_VERSION}</b></span><span>Retention <b>7 days</b></span></div></div>
    <div class="card abuse-toolbar abuse-toolbar-v48128">{_v48127_tabs(tab)}{_v48128_filter_form(tab, values, nodes)}</div>
    <details class="card policy-fold"><summary>Current policy</summary>{_public_abuse_policy(cfg)}</details>"""
    content += _v48128_current_page(values) if tab == "current" else _v48128_events_page(values)
    return page("VM Abuse", content)

app.view_functions["vm_abuse_page"] = vm_abuse_page_v48128

V48128_UI_CSS = r"""
<style id="v48128-abuse-table-ui">
.abuse-current-v48128{min-width:2540px;table-layout:fixed}.abuse-current-v48128 th:nth-child(1){width:48px}.abuse-current-v48128 th:nth-child(2){width:285px}.abuse-current-v48128 th:nth-child(3){width:260px}.abuse-current-v48128 th:nth-child(4){width:235px}.abuse-current-v48128 th:nth-child(5),.abuse-current-v48128 th:nth-child(6),.abuse-current-v48128 th:nth-child(7){width:205px}.abuse-current-v48128 th:nth-child(8){width:150px}.abuse-current-v48128 th:nth-child(9){width:190px}.abuse-current-v48128 th:nth-child(10){width:220px}.abuse-current-v48128 th:nth-child(11),.abuse-current-v48128 th:nth-child(12){width:175px}
.ratio-cell-v48128{min-width:220px}.ratio-help{display:block;margin-top:5px;color:var(--muted,#667085);font-size:9px;white-space:normal;line-height:1.35}.abuse-events-v48128{min-width:1500px;table-layout:fixed}.abuse-events-v48128 th:nth-child(1){width:48px}.abuse-events-v48128 th:nth-child(2){width:300px}.abuse-events-v48128 th:nth-child(3){width:130px}.abuse-events-v48128 th:nth-child(4),.abuse-events-v48128 th:nth-child(5){width:155px}.abuse-events-v48128 th:nth-child(6){width:120px}.abuse-events-v48128 th:nth-child(7){width:270px}.abuse-events-v48128 th:nth-child(8){width:170px}.abuse-events-v48128 th:nth-child(9){width:155px}.abuse-filter-v48128 select[name=sort]{min-width:165px}.admin-abuse-direct-v48128 .bulk-bar{display:grid!important;grid-template-columns:minmax(170px,1fr) minmax(240px,1.4fr) minmax(260px,1.5fr) minmax(220px,1fr) auto!important;align-items:end!important}.admin-abuse-direct-v48128 .enable-line{align-self:center!important;margin-bottom:9px!important}.admin-abuse-direct-v48128 input[type=checkbox]{width:16px!important;height:16px!important;min-height:0!important}
html[data-theme=dark] .resource-primary{color:#f8fafc}html[data-theme=dark] .resource-context b{color:#e2e8f0}html[data-theme=dark] .resource-context span,html[data-theme=dark] .resource-foot{color:#94a3b8!important}html[data-theme=dark] .resource-warm .resource-primary,html[data-theme=dark] .resource-warm .resource-context b{color:#fedf89}html[data-theme=dark] .resource-hot .resource-primary,html[data-theme=dark] .resource-hot .resource-context b,html[data-theme=dark] .resource-critical .resource-primary,html[data-theme=dark] .resource-critical .resource-context b{color:#fecdca}
@media(max-width:1450px){.admin-abuse-direct-v48128 .bulk-bar{grid-template-columns:repeat(2,minmax(240px,1fr))!important}.admin-abuse-direct-v48128 .bulk-bar button{width:max-content}}
@media(max-width:760px){.admin-abuse-direct-v48128 .bulk-bar{grid-template-columns:1fr!important}.abuse-filter-v48128 select[name=sort]{min-width:100%}}
</style>
"""

_page_v48128_base = page

def page(title, content):
    response = _page_v48128_base(title, content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace("</head>", V48128_UI_CSS + "</head>", 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.12.8 Abuse table UI")
    return response

def _v48128_normalize_existing_ram_ratios():
    """One-time migration for retained v48.12.6/v48.12.7 50x-style RAM ratios."""
    marker = "v48128_ram_ratio_normalized"
    conn = db()
    try:
        row = conn.execute("SELECT value FROM admin_settings WHERE key=?", (marker,)).fetchone()
        if row and str(row[0] or "") == "1":
            return
        conn.execute("BEGIN IMMEDIATE")
        cfg = get_abuse_settings(conn)
        changed = 0
        state_rows = conn.execute("""
          SELECT node,vm_uuid,abuse_flags,severity,rx_pps,tx_pps,rx_mbps,tx_mbps,
                 cpu_full_percent,ram_rss_percent,ram_guest_used_percent,ram_usable_percent,
                 disk_read_bps,disk_write_bps,disk_read_iops,disk_write_iops
          FROM vm_abuse_state WHERE abuse_flags LIKE '%RAM_SUSTAINED%'
        """).fetchall()
        keys = ("node","vm_uuid","abuse_flags","severity","rx_pps","tx_pps","rx_mbps","tx_mbps",
                "cpu_full_percent","ram_rss_percent","ram_guest_used_percent","ram_usable_percent",
                "disk_read_bps","disk_write_bps","disk_read_iops","disk_write_iops")
        for row in state_rows:
            rec = dict(zip(keys, row))
            parts = _v48128_severity_components(rec, cfg)
            if parts:
                new_value = max(part[0] for part in parts)
                if abs(new_value - safe_float(rec.get("severity"), 0)) > 0.0001:
                    conn.execute("UPDATE vm_abuse_state SET severity=? WHERE node=? AND vm_uuid=?", (new_value, rec["node"], rec["vm_uuid"]))
                    changed += 1

        event_rows = conn.execute("""
          SELECT id,abuse_flags,severity,rx_pps,tx_pps,rx_mbps,tx_mbps,cpu_full_percent,
                 ram_rss_percent,ram_guest_used_percent,ram_usable_percent,
                 disk_read_bps,disk_write_bps,disk_read_iops,disk_write_iops,thresholds_json
          FROM vm_abuse_events WHERE abuse_flags LIKE '%RAM_SUSTAINED%'
        """).fetchall()
        event_keys = ("id","abuse_flags","severity","rx_pps","tx_pps","rx_mbps","tx_mbps","cpu_full_percent",
                      "ram_rss_percent","ram_guest_used_percent","ram_usable_percent",
                      "disk_read_bps","disk_write_bps","disk_read_iops","disk_write_iops","thresholds_json")
        event_changed = 0
        for row in event_rows:
            rec = dict(zip(event_keys, row))
            event_cfg = dict(cfg)
            try:
                stored_cfg = json.loads(rec.get("thresholds_json") or "{}")
                if isinstance(stored_cfg, dict):
                    event_cfg.update(stored_cfg)
            except Exception:
                pass
            parts = _v48128_severity_components(rec, event_cfg)
            if parts:
                new_value = max(part[0] for part in parts)
                if abs(new_value - safe_float(rec.get("severity"), 0)) > 0.0001:
                    conn.execute("UPDATE vm_abuse_events SET severity=? WHERE id=?", (new_value, safe_int(rec["id"], 0)))
                    event_changed += 1
        if event_changed:
            _v48126_rebuild_incidents(conn)
        conn.execute("""INSERT INTO admin_settings(key,value,updated_at) VALUES(?,?,?)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                     (marker, "1", now_ts()))
        conn.commit()
        if changed or event_changed:
            app.logger.info("v48.12.8 normalized RAM ratios: current=%s events=%s", changed, event_changed)
    except Exception:
        conn.rollback()
        app.logger.exception("Could not normalize legacy RAM ratios for v48.12.8")
    finally:
        conn.close()

try:
    _v48128_normalize_existing_ram_ratios()
except Exception:
    app.logger.exception("Could not run v48.12.8 ratio migration")

# exact active duration, explicit per-metric sorting, and complete cleanup.
V48129_VERSION = "48.12.9"
V48129_BUILD = "r4"

def _v48129_minutes_text(seconds):
    seconds = max(0, safe_int(seconds, 0))
    minutes = max(1, int(round(seconds / 60.0))) if seconds else 0
    return f"{minutes:,} min"

def _v48129_level(pct):
    value = max(0.0, safe_float(pct, 0.0))
    if value >= 95.0:
        return "critical"
    if value >= 85.0:
        return "hot"
    if value >= 70.0:
        return "warm"
    return "normal"

def _v48129_rule_chip(kind, label, title=""):
    kind = kind if kind in {"network", "cpu", "ram", "disk", "time", "neutral"} else "neutral"
    title_attr = f' title="{escape(title, quote=True)}"' if title else ""
    return (
        f'<span class="abuse-rule-chip chip-{kind}"{title_attr}>'
        f'{escape(str(label))}</span>'
    )

def _v48129_flag_set(flags):
    return set(_v4810_canonical_flags(flags))

def _v48129_reason_chips(flags, cfg, record=None):
    """Render stable, color-coded policy chips.

    Current rows receive the metric record and therefore get the exact active
    RAM/Disk sub-condition when it is knowable. Incident rows can still render
    policy-accurate generic chips from their retained flag union.
    """
    values = _v48129_flag_set(flags)
    record = record or {}
    chips = []

    pps_minutes = max(1, int(math.ceil(safe_int(cfg.get("network_required_seconds"), 270) / 60.0)))
    mbps_minutes = max(1, int(math.ceil(safe_int(cfg.get("network_mbps_required_seconds"), 300) / 60.0)))
    cpu_minutes = max(1, int(math.ceil(safe_int(cfg.get("cpu_required_seconds"), 1800) / 60.0)))
    ram_minutes = max(1, int(math.ceil(safe_int(cfg.get("ram_required_seconds"), 600) / 60.0)))
    disk_minutes = max(1, int(math.ceil(safe_int(cfg.get("disk_required_seconds"), 900) / 60.0)))

    if "NETWORK_RX_PPS" in values:
        chips.append(_v48129_rule_chip("network", f"RX PPS ≥ {safe_float(cfg.get('network_pps'),0):,.0f}/s · {pps_minutes} min"))
    if "NETWORK_TX_PPS" in values:
        chips.append(_v48129_rule_chip("network", f"TX PPS ≥ {safe_float(cfg.get('network_pps'),0):,.0f}/s · {pps_minutes} min"))
    if "NETWORK_RX_AVG_MBPS" in values:
        chips.append(_v48129_rule_chip("network", f"RX AVG ≥ {safe_float(cfg.get('network_avg_mbps'),0):,.0f} Mbps · {mbps_minutes} min"))
    if "NETWORK_TX_AVG_MBPS" in values:
        chips.append(_v48129_rule_chip("network", f"TX AVG ≥ {safe_float(cfg.get('network_avg_mbps'),0):,.0f} Mbps · {mbps_minutes} min"))

    if "CPU_SUSTAINED" in values:
        chips.append(_v48129_rule_chip("cpu", f"CPU Full ≥ {safe_float(cfg.get('cpu_full_percent'),0):.1f}% · {cpu_minutes} min"))

    if "RAM_SUSTAINED" in values:
        ram_added = False
        rss = safe_float(record.get("ram_rss_percent"), -1)
        guest = safe_float(record.get("ram_guest_used_percent"), -1)
        usable = safe_float(record.get("ram_usable_percent"), -1)
        rss_limit = safe_float(cfg.get("ram_rss_percent"), 0)
        guest_limit = safe_float(cfg.get("ram_guest_used_percent"), 0)
        usable_limit = safe_float(cfg.get("ram_low_usable_percent"), 0)
        if rss_limit > 0 and rss >= rss_limit:
            chips.append(_v48129_rule_chip("ram", f"RAM Host RSS ≥ {rss_limit:.1f}% · {ram_minutes} min"))
            ram_added = True
        if guest_limit > 0 and guest >= guest_limit:
            chips.append(_v48129_rule_chip("ram", f"RAM Guest ≥ {guest_limit:.1f}% · {ram_minutes} min"))
            ram_added = True
        if usable_limit > 0 and usable >= 0 and usable <= usable_limit:
            chips.append(_v48129_rule_chip("ram", f"RAM Usable ≤ {usable_limit:.1f}% · {ram_minutes} min"))
            ram_added = True
        if not ram_added:
            chips.append(_v48129_rule_chip("ram", f"RAM sustained · {ram_minutes} min"))

    if "DISK_SUSTAINED" in values:
        disk_added = False
        read_bps = safe_float(record.get("disk_read_bps"), 0)
        write_bps = safe_float(record.get("disk_write_bps"), 0)
        read_iops = safe_float(record.get("disk_read_iops"), 0)
        write_iops = safe_float(record.get("disk_write_iops"), 0)
        read_limit = safe_float(cfg.get("disk_read_bps"), 0)
        write_limit = safe_float(cfg.get("disk_write_bps"), 0)
        total_limit = safe_float(cfg.get("disk_bps"), 0)
        iops_limit = safe_float(cfg.get("disk_iops"), 0)
        if read_limit > 0 and read_bps >= read_limit:
            chips.append(_v48129_rule_chip("disk", f"Disk Read ≥ {human_rate(read_limit)} · {disk_minutes} min"))
            disk_added = True
        if write_limit > 0 and write_bps >= write_limit:
            chips.append(_v48129_rule_chip("disk", f"Disk Write ≥ {human_rate(write_limit)} · {disk_minutes} min"))
            disk_added = True
        if total_limit > 0 and read_bps + write_bps >= total_limit:
            chips.append(_v48129_rule_chip("disk", f"Disk Total ≥ {human_rate(total_limit)} · {disk_minutes} min"))
            disk_added = True
        if iops_limit > 0 and read_iops + write_iops >= iops_limit:
            chips.append(_v48129_rule_chip("disk", f"Disk IOPS ≥ {iops_limit:,.0f} · {disk_minutes} min"))
            disk_added = True
        if not disk_added:
            chips.append(_v48129_rule_chip("disk", f"Disk sustained · {disk_minutes} min"))

    return "".join(chips) or _v48129_rule_chip("neutral", "Policy match")

def _v48129_ratio_details(record, cfg):
    parts = _v48128_severity_components(record, cfg)
    stored = max(0.0, safe_float(record.get("severity"), 0.0))
    if not parts:
        return stored, "Stored ratio", "No active component is available"
    ratio, label, actual, threshold, inverse = parts[0]
    if inverse:
        detail = f"{label}: usable {actual:.2f}% vs low threshold {threshold:.2f}%"
    elif "Mbps" in label:
        detail = f"{label}: {actual:.2f} / {threshold:.2f} Mbps"
    elif "PPS" in label or "IOPS" in label:
        detail = f"{label}: {actual:,.2f} / {threshold:,.2f}"
    elif "Disk" in label:
        detail = f"{label}: {human_rate(actual)} / {human_rate(threshold)}"
    else:
        detail = f"{label}: {actual:.2f}% / {threshold:.2f}%"
    return ratio, label, detail

def _v48129_reason_cell(record, cfg, started):
    ratio, _ratio_label, _detail = _v48129_ratio_details(record, cfg)
    primary = _v48126_primary_type(record.get("abuse_flags", ""))
    return (
        '<div class="reason-severity-v48129">'
        f'<div class="severity-line severity-{escape(primary)}"><b>{ratio:.2f}x</b><span>SEVERITY</span></div>'
        f'<div class="abuse-rule-chips">{_v48129_reason_chips(record.get("abuse_flags", ""), cfg, record)}</div>'
        '</div>'
    )

def _v48129_metric_abuse_time(started, kind, active, title_prefix="Active since"):
    if not active:
        return ""
    duration = max(0, now_ts() - safe_int(started, now_ts()))
    label = "Abusing " + _v48126_duration(duration)
    title = f"{title_prefix} {fmt_full(started)}"
    return (
        f'<small class="metric-abuse-time metric-abuse-time-{escape(kind)}" '
        f'title="{escape(title, quote=True)}">{escape(label)}</small>'
    )

def _v48129_abuse_groups(flags):
    values = _v48129_flag_set(flags)
    return {
        "network_avg": bool(values & {"NETWORK_RX_AVG_MBPS", "NETWORK_TX_AVG_MBPS"}),
        "network_pps": bool(values & {"NETWORK_RX_PPS", "NETWORK_TX_PPS"}),
        "cpu": "CPU_SUSTAINED" in values,
        "ram": "RAM_SUSTAINED" in values,
        "disk": "DISK_SUSTAINED" in values,
    }

def _v48129_cpu_block(core_percent, full_percent, vcpu, streak_seconds=0, required_seconds=0, selected="cpu", abuse_time=""):
    core = max(0.0, safe_float(core_percent, 0.0))
    full = max(0.0, safe_float(full_percent, 0.0))
    level = _v48129_level(full)
    sort_metric = "Core %" if selected == "cpucore" else "Full %"
    streak_minutes = max(0, safe_int(streak_seconds, 0)) // 60
    required_minutes = max(1, safe_int(required_seconds, 0) // 60)
    return f"""
    <div class="resource-block cpu-resource resource-{level}" title="Sorted by {escape(sort_metric, quote=True)}">
      <b class="resource-primary cpu-core-value">{core:.1f}%</b>
      <div class="resource-context"><b>{full:.1f}% full</b><span> · {streak_minutes}/{required_minutes} min sustained</span></div>
      <span class="resource-meter"><i style="width:{min(100.0,full):.1f}%"></i></span>
      {abuse_time}
      <small class="resource-foot">{max(0,safe_int(vcpu,0))} vCPU</small>
    </div>"""

def _v48129_ram_values(current_kib, rss_kib, available_kib, usable_kib, guest_pct):
    assigned = max(0.0, safe_float(current_kib, 0.0))
    rss = max(0.0, safe_float(rss_kib, 0.0))
    available = max(0.0, safe_float(available_kib, 0.0))
    usable = max(0.0, safe_float(usable_kib, 0.0))
    guest_valid = safe_float(guest_pct, -1) >= 0
    used = max(0.0, available - usable) if guest_valid else 0.0
    pct = pct_clamp(safe_float(guest_pct, 0.0)) if guest_valid else -1.0
    return assigned, rss, used, pct, guest_valid

def _v48129_ram_block(current_kib, rss_kib, available_kib, usable_kib, guest_pct, selected="ram", abuse_time=""):
    assigned, rss, used, guest, guest_valid = _v48129_ram_values(
        current_kib, rss_kib, available_kib, usable_kib, guest_pct
    )
    rss_pct = (rss * 100.0 / assigned) if assigned > 0 else 0.0
    used_pct = (used * 100.0 / assigned) if assigned > 0 and guest_valid else 0.0
    bar_pct = used_pct if guest_valid else rss_pct
    level = _v48129_level(bar_pct)
    sort_labels = {
        "ram": "Guest %", "ramused": "Used GiB", "ramrss": "Host RSS", "ramassigned": "Assigned",
    }
    sort_metric = sort_labels.get(selected, "Guest %")
    used_label = fmt_kib(used) if guest_valid else "N/A"
    assigned_label = fmt_kib(assigned) if assigned > 0 else "N/A"
    guest_label = f"{guest:.1f}% used" if guest_valid else "Guest usage N/A"
    rss_label = fmt_kib(rss) if rss > 0 else "N/A"
    return f"""
    <div class="resource-block ram-resource resource-{level}" title="Sorted by {escape(sort_metric, quote=True)}">
      <b class="resource-primary ram-used-value">{used_label} / {assigned_label}</b>
      <div class="resource-context"><b>{guest_label}</b></div>
      <span class="resource-meter"><i style="width:{min(100.0,max(0.0,bar_pct)):.1f}%"></i></span>
      {abuse_time}
      <small class="resource-foot">RSS {rss_label}</small>
    </div>"""

def _v48129_group_header(title, options, values):
    links = []
    for label, key, default in options:
        links.append(_v48127_sort_link("current", values, key, label, default))
    return f'<div class="metric-sort-head"><div>{escape(title)}</div><small>{" · ".join(links)}</small></div>'

def _v48129_current_rows(values):
    cfg = get_abuse_settings()
    where = [
        "a.is_abuse=1", "a.last_seen>=?", "a.policy_revision=?", "a.engine_version=?",
        _v48126_visible_sql("ni", "vi"), _v48126_type_condition("a", values["type"]), "a.severity>=?",
    ]
    params = [now_ts() - FAST_CURRENT_STALE_SECONDS, cfg["revision"], ABUSE_ENGINE_VERSION, values["min_severity"]]
    if values["node"]:
        where.append("a.node=?")
        params.append(values["node"])
    if values["q"]:
        pattern = like_pattern(values["q"])
        where.append("(a.node LIKE ? OR a.vm_uuid LIKE ? OR a.abuse_flags LIKE ?)")
        params.extend([pattern, pattern, pattern])

    sort = values.get("sort") or "severity"
    order = values.get("order") or "desc"
    sort_map = {
        "node": "a.node COLLATE NOCASE", "uuid": "a.vm_uuid COLLATE NOCASE", "type": "a.abuse_flags COLLATE NOCASE",
        "severity": "a.severity", "rx_mbps": "COALESCE(a.rx_mbps,0)", "tx_mbps": "COALESCE(a.tx_mbps,0)",
        "rx_peak": "COALESCE(a.rx_peak_pps,0)", "tx_peak": "COALESCE(a.tx_peak_pps,0)",
        "cpu": "COALESCE(a.cpu_full_percent,0)", "cpucore": "COALESCE(a.cpu_core_percent,0)",
        "ram": "COALESCE(a.ram_guest_used_percent,-1)",
        "ramused": "CASE WHEN COALESCE(a.ram_guest_used_percent,-1)>=0 THEN MAX(0,COALESCE(a.ram_available_kib,0)-COALESCE(a.ram_usable_kib,0)) ELSE -1 END",
        "ramrss": "COALESCE(a.ram_rss_kib,0)", "ramassigned": "COALESCE(a.ram_current_kib,0)",
        "diskr": "COALESCE(a.disk_read_bps,0)", "diskw": "COALESCE(a.disk_write_bps,0)",
        "readiops": "COALESCE(a.disk_read_iops,0)", "writeiops": "COALESCE(a.disk_write_iops,0)",
        "last_seen": "a.last_seen",
    }
    if sort == "duration":
        order_sql = f"a.abuse_since {'ASC' if order == 'desc' else 'DESC'}"
    else:
        expression = sort_map.get(sort, sort_map["severity"])
        order_sql = f"{expression} {'ASC' if order == 'asc' else 'DESC'}"
    where_sql = " AND ".join(where)
    offset = (values["page"] - 1) * values["limit"]
    conn = db()
    try:
        total = safe_int(conn.execute(f"""SELECT COUNT(*) FROM vm_abuse_state a
            LEFT JOIN node_inventory ni ON ni.node=a.node
            LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
            WHERE {where_sql}""", params).fetchone()[0], 0)
        rows = conn.execute(f"""
            SELECT a.node,a.vm_uuid,a.abuse_since,a.last_seen,a.abuse_flags,a.severity,
                   a.rx_mbps,a.tx_mbps,a.rx_pps,a.tx_pps,a.rx_peak_pps,a.tx_peak_pps,
                   a.seconds_over_rx_pps,a.seconds_over_tx_pps,
                   COALESCE(a.network_rx_mbps_streak_seconds,0),COALESCE(a.network_tx_mbps_streak_seconds,0),
                   a.cpu_full_percent,a.cpu_core_percent,a.vcpu_current,a.cpu_streak_seconds,
                   a.ram_rss_percent,a.ram_guest_used_percent,a.ram_usable_percent,a.ram_streak_seconds,
                   a.ram_current_kib,a.ram_rss_kib,a.ram_available_kib,a.ram_usable_kib,
                   a.disk_read_bps,a.disk_write_bps,a.disk_read_iops,a.disk_write_iops,a.disk_streak_seconds,
                   COALESCE(b.primary_ipv4,'')
            FROM vm_abuse_state a
            LEFT JOIN node_inventory ni ON ni.node=a.node
            LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
            LEFT JOIN node_bridge_addresses_latest b ON b.node=a.node AND b.bridge=?
            WHERE {where_sql}
            ORDER BY {order_sql},a.node COLLATE NOCASE,a.vm_uuid COLLATE NOCASE
            LIMIT ? OFFSET ?
        """, [PUBLIC_BRIDGE] + params + [values["limit"], offset]).fetchall()
        counts = {}
        for key in ("network", "cpu", "ram", "disk"):
            counts[key] = safe_int(conn.execute(f"""SELECT COUNT(*) FROM vm_abuse_state a
              LEFT JOIN node_inventory ni ON ni.node=a.node
              LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
              WHERE a.is_abuse=1 AND a.last_seen>=? AND a.policy_revision=? AND a.engine_version=?
                AND {_v48126_visible_sql('ni','vi')} AND {_v48126_type_condition('a', key)}""",
              (now_ts()-FAST_CURRENT_STALE_SECONDS, cfg["revision"], ABUSE_ENGINE_VERSION)).fetchone()[0], 0)
        return rows, total, counts
    finally:
        conn.close()

def _v48129_current_page(values):
    cfg = get_abuse_settings()
    rows, total, counts = _v48129_current_rows(values)
    body = ""
    rank_start = (values["page"] - 1) * values["limit"]
    for index, row in enumerate(rows, 1):
        (
            node, uuid, started, last_seen, flags, stored_severity,
            rxm, txm, rxp, txp, rxpk, txpk, rx_high, tx_high, rx_mbps_streak, tx_mbps_streak,
            cpu, core, vcpu, cpu_streak, rss_pct, guest_pct, usable_pct, ram_streak,
            ram_current, ram_rss, ram_available, ram_usable,
            dr, dw, dri, dwi, disk_streak, ip,
        ) = row
        href = url_for("node_page", node=node, period="1h", q=uuid)
        record = {
            "abuse_flags": flags, "severity": stored_severity,
            "rx_mbps": rxm, "tx_mbps": txm, "rx_pps": rxp, "tx_pps": txp,
            "cpu_full_percent": cpu, "ram_rss_percent": rss_pct,
            "ram_guest_used_percent": guest_pct, "ram_usable_percent": usable_pct,
            "disk_read_bps": dr, "disk_write_bps": dw,
            "disk_read_iops": dri, "disk_write_iops": dwi,
        }
        network_need = max(1, safe_int(cfg.get("network_mbps_required_seconds"), 300))
        pps_need = max(1, safe_int(cfg.get("network_required_seconds"), 270))
        abuse_groups = _v48129_abuse_groups(flags)
        network_avg_time = _v48129_metric_abuse_time(started, "network", abuse_groups["network_avg"])
        network_pps_time = _v48129_metric_abuse_time(started, "network", abuse_groups["network_pps"])
        cpu_time = _v48129_metric_abuse_time(started, "cpu", abuse_groups["cpu"])
        ram_time = _v48129_metric_abuse_time(started, "ram", abuse_groups["ram"])
        disk_time = _v48129_metric_abuse_time(started, "disk", abuse_groups["disk"])
        body += f"""<tr>
          <td class="rank-cell">{rank_start + index}</td>
          <td class="identity-cell"><div class="node-line"><a href="{escape(href, quote=True)}"><b>{escape(node)}</b></a>{f'<span>{escape(compact_ipv4(ip))}</span>' if ip else ''}</div><div class="uuid-line"><a class="mono" href="{escape(href, quote=True)}">{escape(uuid)}</a><button type="button" class="copy-btn" data-copy="{escape(uuid, quote=True)}" title="Copy UUID">⧉</button></div></td>
          <td class="reason-cell-v48129">{_v48129_reason_cell(record,cfg,started)}</td>
          <td><div class="metric-pair metric-pair-rich"><div><span>RX AVG</span><b>{safe_float(rxm,0):.2f} Mbps</b><small>{_v48126_duration(rx_mbps_streak)} / {_v48126_duration(network_need)} sustained</small></div><div><span>TX AVG</span><b>{safe_float(txm,0):.2f} Mbps</b><small>{_v48126_duration(tx_mbps_streak)} / {_v48126_duration(network_need)} sustained</small></div></div>{network_avg_time}</td>
          <td><div class="metric-pair metric-pair-rich"><div><span>RX PEAK</span><b>{fmt_pps_value(rxpk)} PPS</b><small>{safe_int(rx_high,0)}/300s high · need {pps_need}s</small></div><div><span>TX PEAK</span><b>{fmt_pps_value(txpk)} PPS</b><small>{safe_int(tx_high,0)}/300s high · need {pps_need}s</small></div></div>{network_pps_time}</td>
          <td>{_v48129_cpu_block(core,cpu,vcpu,cpu_streak,cfg.get('cpu_required_seconds',1800),values.get('sort'),cpu_time)}</td>
          <td>{_v48129_ram_block(ram_current,ram_rss,ram_available,ram_usable,guest_pct,values.get('sort'),ram_time)}</td>
          <td><div class="metric-pair metric-pair-rich"><div class="{'selected' if values.get('sort') in {'diskr','readiops'} else ''}"><span>READ</span><b>{human_rate(dr)}</b><small>{safe_float(dri,0):,.0f} IOPS</small></div><div class="{'selected' if values.get('sort') in {'diskw','writeiops'} else ''}"><span>WRITE</span><b>{human_rate(dw)}</b><small>{safe_float(dwi,0):,.0f} IOPS</small></div></div>{disk_time}</td>
          <td><div class="timeline-cell"><b>{fmt_full(last_seen)}</b><small>{fmt_push(last_seen)}</small></div></td>
        </tr>"""
    if not body:
        body = '<tr><td colspan="9" class="empty">No visible VM matches the selected Current Abuse filters</td></tr>'
    pages = max(1, math.ceil(total / values["limit"]))
    h = lambda label, key, default="desc": _v48127_sort_link("current", values, key, label, default)
    ram_header = _v48128_group_sort_header("RAM", [
        ("Guest %", "ram", h("Guest %", "ram")), ("Used GiB", "ramused", h("Used GiB", "ramused")),
        ("Host RSS", "ramrss", h("Host RSS", "ramrss")), ("Assigned", "ramassigned", h("Assigned", "ramassigned")),
    ], values["sort"], values["order"])
    headers = (
        '<th>#</th>'
        f'<th>{h("NODE / VM","node","asc")}</th>'
        f'<th>{h("REASON / SEVERITY","severity")}</th>'
        f'<th>{_v48129_group_header("NETWORK AVG", [("RX Mbps","rx_mbps","desc"),("TX Mbps","tx_mbps","desc")], values)}</th>'
        f'<th>{_v48129_group_header("PPS PEAK / WINDOW", [("RX PPS","rx_peak","desc"),("TX PPS","tx_peak","desc")], values)}</th>'
        f'<th>{_v48129_group_header("CPU", [("Full %","cpu","desc"),("Core %","cpucore","desc")], values)}</th>'
        f'<th class="ram-compact-sort-head">{ram_header}</th>'
        f'<th>{_v48129_group_header("DISK", [("Read","diskr","desc"),("Write","diskw","desc"),("Read IOPS","readiops","desc"),("Write IOPS","writeiops","desc")], values)}</th>'
        f'<th>{h("LAST SEEN","last_seen")}</th>'
    )
    return f"""
    <div class="abuse-kpis-v48126"><div><span>Filtered</span><b>{total}</b></div><div><span>Network</span><b>{counts['network']}</b></div><div><span>CPU</span><b>{counts['cpu']}</b></div><div><span>RAM</span><b>{counts['ram']}</b></div><div><span>Disk</span><b>{counts['disk']}</b></div></div>
    <div class="card"><div class="section-head"><div><h3>Current VM Abuse</h3><p>Top-VM-style operations table. Every sub-metric is sortable. CPU/RAM bars are normalized against the VM's assigned resources.</p></div><div class="count-badges"><span>All <b>{total}</b></span><span>Page <b>{values['page']}/{pages}</b></span><span>Policy <b>v{cfg['revision']}</b></span></div></div>
    <div class="table-wrap"><table class="abuse-current-v48129"><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>
    <div class="table-hint"><b>REASON / SEVERITY:</b> ratio is the largest active metric ÷ configured threshold. Colored chips identify Network, CPU, RAM, Disk and the exact active duration. The ratio is not a weighted score.</div>
    {_v48126_pagination('current', values, total)}</div>"""

def _v48129_event_detail_table(items):
    now = now_ts()
    cfg = get_abuse_settings()
    body = ""
    for index, row in enumerate(items, 1):
        iid, node, uuid, started, ended, duration, maxsev, flags, ptype, event_count, last_event, status = row
        effective_end = now if status == "open" else safe_int(ended or last_event, started)
        effective_duration = max(0, effective_end - safe_int(started, 0))
        state = '<span class="status-chip status-active">ACTIVE</span>' if status == "open" else '<span class="status-chip status-recovered">RECOVERED</span>'
        body += f"""<tr>
          <td>{index}</td><td>{state}</td><td>{fmt_full(started)}</td>
          <td>{'<b>Active now</b>' if status == 'open' else fmt_full(effective_end)}</td>
          <td><b>{_v48129_minutes_text(effective_duration)}</b><small class="row-sub">{_v48126_duration(effective_duration)}</small></td>
          <td><b>{safe_float(maxsev,0):.2f}x</b></td>
          <td><div class="abuse-rule-chips">{_v48129_reason_chips(flags,cfg)}{_v48129_rule_chip('time', ('Active ' if status=='open' else 'Duration ') + _v48126_duration(effective_duration))}</div></td>
          <td class="num">{safe_int(event_count,0)}</td>
        </tr>"""
    if not body:
        body = '<tr><td colspan="8" class="empty">No occurrence details</td></tr>'
    return f"""<div class="event-occurrence-wrap"><table class="event-occurrence-table"><thead><tr><th>#</th><th>STATE</th><th>STARTED</th><th>ENDED</th><th>DURATION / MINUTES</th><th>MAX RATIO</th><th>REASON / DURATION</th><th>RAW EVENTS</th></tr></thead><tbody>{body}</tbody></table></div>"""

def _v48129_events_page(values):
    rows, total, details = _v48127_event_groups(values)
    cfg = get_abuse_settings()
    body = ""
    rank_start = (values["page"] - 1) * values["limit"]
    for index, row in enumerate(rows, 1):
        node, uuid, occurrences, active_count, total_duration, longest_duration, max_severity, last_seen, all_flags, all_types = row
        key = (str(node), str(uuid))
        detail_id = f"abuse-events-v48129-{rank_start + index}"
        href = url_for("node_page", node=node, period="1h", q=uuid)
        primary = _v48126_primary_type(all_flags or all_types or "")
        repeat_label = "1 time" if safe_int(occurrences,0) == 1 else f"{safe_int(occurrences,0)} times"
        total_minutes = _v48128_minutes(total_duration)
        longest_minutes = _v48128_minutes(longest_duration)
        body += f"""<tr class="event-vm-row" data-event-target="{detail_id}" tabindex="0">
          <td class="rank-cell">{rank_start + index}</td>
          <td class="identity-cell"><div class="node-line"><a href="{escape(href, quote=True)}"><b>{escape(str(node))}</b></a></div><div class="uuid-line"><a class="mono" href="{escape(href, quote=True)}">{escape(str(uuid))}</a><button type="button" class="copy-btn" data-copy="{escape(str(uuid), quote=True)}" title="Copy UUID">⧉</button></div></td>
          <td><span class="repeat-count-v48128">{repeat_label}</span>{f'<small class="row-sub active-text">{safe_int(active_count,0)} active now</small>' if safe_int(active_count,0) else '<small class="row-sub">Recovered</small>'}</td>
          <td><b>{total_minutes:,} min</b><small class="row-sub">{_v48126_duration(total_duration)}</small></td>
          <td><b>{longest_minutes:,} min</b><small class="row-sub">{_v48126_duration(longest_duration)}</small></td>
          <td><b>{safe_float(max_severity,0):.2f}x</b><small class="row-sub">MAX RATIO</small></td>
          <td><div class="event-primary-line"><span class="type-chip type-{escape(primary)}">{escape(primary.upper())}</span></div><div class="abuse-rule-chips compact-rule-chips">{_v48129_reason_chips(all_flags,cfg)}</div></td>
          <td>{fmt_full(last_seen)}</td>
          <td><button type="button" class="btn event-toggle-v48128" data-event-toggle="{detail_id}">View {safe_int(occurrences,0)} occurrence{'s' if safe_int(occurrences,0)!=1 else ''}</button></td>
        </tr>
        <tr id="{detail_id}" class="event-detail-row-v48128" hidden><td colspan="9">{_v48129_event_detail_table(details.get(key, []))}</td></tr>"""
    if not body:
        body = '<tr><td colspan="9" class="empty">No visible VM Abuse event matches the selected filters</td></tr>'
    pages = max(1, math.ceil(total / values["limit"]))
    headers = (
        '<th>#</th>'
        f'<th>{_v48127_sort_link("events", values, "node", "NODE / VM", "asc")}</th>'
        f'<th>{_v48127_sort_link("events", values, "occurrences", "ABUSE COUNT")}</th>'
        f'<th>{_v48127_sort_link("events", values, "duration", "TOTAL MINUTES")}</th>'
        f'<th>{_v48127_sort_link("events", values, "longest", "LONGEST MINUTES")}</th>'
        f'<th>{_v48127_sort_link("events", values, "severity", "MAX RATIO")}</th>'
        '<th>PRIMARY / REASONS</th>'
        f'<th>{_v48127_sort_link("events", values, "last_seen", "LAST ABUSE")}</th>'
        '<th>DETAIL</th>'
    )
    return f"""
    <div class="card"><div class="section-head"><div><h3>Abuse Events by VM</h3><p>One row per VM. Sort by repeat count, total minutes, longest occurrence, max ratio or last Abuse. Expand a VM for exact start/end times.</p></div><div class="count-badges"><span>VM matched <b>{total}</b></span><span>Window <b>{escape(values['range'])}</b></span><span>Retention <b>7 days</b></span><span>Page <b>{values['page']}/{pages}</b></span></div></div>
    <div class="table-wrap"><table class="abuse-events-v48129"><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>{_v48126_pagination('events', values, total)}</div>"""

# Complete Admin cleanup contract. History cleanup never silently leaves the
# derived incident table behind; current state has its own explicit reset.
def clear_abuse_events_v48129():
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
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("BEGIN IMMEDIATE")
        if mode == "all":
            if confirm_text != "CLEAR ALL ABUSE LOGS":
                conn.rollback()
                return redirect(url_for("admin_abuse_page", err="Confirmation text did not match."))
            cur = conn.execute("DELETE FROM vm_abuse_events")
            conn.execute("DELETE FROM vm_abuse_incidents")
        elif mode == "matching":
            if confirm_text != "CLEAR MATCHING":
                conn.rollback()
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
            _v48126_rebuild_incidents(conn)
        else:
            ids = sorted({safe_int(x,0) for x in request.form.getlist("event_ids") if safe_int(x,0)>0})
            if not ids:
                conn.rollback()
                return redirect(url_for("admin_abuse_page", msg="No abuse event was selected."))
            placeholders = ",".join("?" for _ in ids)
            cur = conn.execute(f"DELETE FROM vm_abuse_events WHERE id IN ({placeholders})", ids)
            _v48126_rebuild_incidents(conn)
        deleted = max(0, safe_int(cur.rowcount, 0))
        conn.commit()
    finally:
        conn.close()
    actor = dashboard_username() or get_admin_username()
    log_account_event("abuse_history_cleared", username=actor, realm="admin", role="admin", detail=f"v48129;mode={mode};deleted={deleted};incidents=synchronized;q={q};event_type={event_type}"[:700])
    return redirect(url_for("admin_abuse_page", msg=f"Deleted {deleted} raw event record(s) and synchronized Abuse Events by VM."))

app.view_functions["clear_abuse_events"] = clear_abuse_events_v48129

@app.route("/admin/abuse-data/reset-all-v48129", methods=["POST"])
def reset_all_abuse_data_v48129():
    deny = require_admin()
    if deny:
        return deny
    if (request.form.get("confirm_text") or "").strip() != "RESET ALL ABUSE DATA":
        return redirect(url_for("admin_abuse_page", err="Confirmation text did not match."))
    conn = db()
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("BEGIN IMMEDIATE")
        raw = max(0, safe_int(conn.execute("DELETE FROM vm_abuse_events").rowcount, 0))
        incidents = max(0, safe_int(conn.execute("DELETE FROM vm_abuse_incidents").rowcount, 0))
        current = max(0, safe_int(conn.execute("DELETE FROM vm_abuse_state").rowcount, 0))
        conn.commit()
    finally:
        conn.close()
    actor = dashboard_username() or get_admin_username()
    log_account_event("all_abuse_data_reset", username=actor, realm="admin", role="admin", detail=f"raw={raw};incidents={incidents};current={current}"[:700])
    return redirect(url_for("admin_abuse_page", msg=f"Reset all Abuse data: {raw} raw event(s), {incidents} occurrence(s), {current} current state row(s). Active offenders will be evaluated again from new Agent cycles."))

@app.route("/admin/abuse-vm-data/manage-v48129", methods=["POST"])
def manage_vm_abuse_data_v48129():
    deny = require_admin()
    if deny:
        return deny
    node = (request.form.get("node") or "").strip()
    vm_uuid = (request.form.get("vm_uuid") or "").strip()
    if not node or not vm_uuid:
        return redirect(url_for("admin_abuse_page", err="Node and VM UUID are required."))
    if (request.form.get("confirm_text") or "").strip() != "CLEAR VM ABUSE DATA":
        return redirect(url_for("admin_abuse_page", err="Confirmation text did not match."))
    delete_raw = request.form.get("delete_raw") == "1"
    delete_incidents = request.form.get("delete_incidents") == "1"
    reset_current = request.form.get("reset_current") == "1"
    if not any((delete_raw, delete_incidents, reset_current)):
        return redirect(url_for("admin_abuse_page", err="Select at least one VM Abuse data type to clear."))
    conn = db()
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("BEGIN IMMEDIATE")
        raw = max(0, safe_int(conn.execute("DELETE FROM vm_abuse_events WHERE node=? AND vm_uuid=?", (node, vm_uuid)).rowcount, 0)) if delete_raw else 0
        incidents = max(0, safe_int(conn.execute("DELETE FROM vm_abuse_incidents WHERE node=? AND vm_uuid=?", (node, vm_uuid)).rowcount, 0)) if delete_incidents else 0
        current = max(0, safe_int(conn.execute("DELETE FROM vm_abuse_state WHERE node=? AND vm_uuid=?", (node, vm_uuid)).rowcount, 0)) if reset_current else 0
        conn.commit()
    finally:
        conn.close()
    actor = dashboard_username() or get_admin_username()
    log_account_event("vm_abuse_data_managed", username=actor, realm="admin", role="admin", detail=f"node={node};vm={vm_uuid};raw={raw};incidents={incidents};current={current}"[:700])
    return redirect(url_for("admin_abuse_page", msg=f"Cleared {vm_uuid}: raw={raw}, Abuse Events={incidents}, current={current}."))

_admin_abuse_page_v48129_base = app.view_functions.get("admin_abuse_page")

def admin_abuse_page_v48129():
    response = _admin_abuse_page_v48129_base()
    try:
        html = response.get_data(as_text=True)
        start = html.find('<div class="card admin-abuse-direct-v48128">')
        end = html.find('<div class="card vm-table-card">', start if start >= 0 else 0)
        manage_card = f'''
        <div class="card admin-abuse-data-map-v48129">
          <div class="table-title-row"><div><h3>Abuse data controls</h3><div class="table-hint">Current Abuse, Raw History and Abuse Events by VM are separate datasets. History cleanup synchronizes both history tables; current state is reset only by an explicit action.</div></div></div>
          <div class="abuse-data-map-grid">
            <div><small>CURRENT ABUSE</small><b>vm_abuse_state</b><span>Truthful live state and sustained streaks</span></div>
            <div><small>RAW HISTORY</small><b>vm_abuse_events</b><span>STARTED / UPDATED / RECOVERED transitions</span></div>
            <div><small>ABUSE EVENTS BY VM</small><b>vm_abuse_incidents</b><span>Grouped start → end occurrences and minutes</span></div>
          </div>
        </div>
        <div class="card admin-abuse-direct-v48129">
          <div class="table-title-row"><div><h3>Clear one VM Abuse data</h3><div class="table-hint">Choose exactly which datasets to clear for one Node + VM UUID.</div></div></div>
          <form class="vm-abuse-manage-grid" method="post" action="{url_for('manage_vm_abuse_data_v48129')}" onsubmit="return confirm('Permanently clear the selected Abuse datasets for this VM?')">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}">
            <label>Node<input name="node" required placeholder="EPYC2SG"></label>
            <label>VM UUID<input name="vm_uuid" required placeholder="VM UUID"></label>
            <label>Type <b>CLEAR VM ABUSE DATA</b><input name="confirm_text" required placeholder="CLEAR VM ABUSE DATA"></label>
            <div class="abuse-clear-options">
              <label><input type="checkbox" name="delete_raw" value="1" checked> Delete Raw History</label>
              <label><input type="checkbox" name="delete_incidents" value="1" checked> Delete Abuse Events by VM</label>
              <label><input type="checkbox" name="reset_current" value="1"> Reset Current Abuse + streak</label>
            </div>
            <button class="btn-danger" type="submit">Clear selected VM data</button>
          </form>
          <div class="table-hint">Reset Current is temporary when the VM still exceeds policy. The engine will evaluate it again from subsequent accepted Agent cycles.</div>
        </div>
        <div class="card reset-all-abuse-v48129">
          <div class="table-title-row"><div><h3>Reset all Abuse data</h3><div class="table-hint">Deletes Current Abuse, Raw History and all grouped Abuse Events. Metrics, Node/VM inventory, API keys and Agent data are not deleted.</div></div></div>
          <form class="reset-all-abuse-form" method="post" action="{url_for('reset_all_abuse_data_v48129')}" onsubmit="return confirm('Reset ALL Abuse state and history? Active offenders can reappear after their sustained window.')">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}">
            <label>Type <b>RESET ALL ABUSE DATA</b><input name="confirm_text" required placeholder="RESET ALL ABUSE DATA"></label>
            <button class="btn-danger" type="submit">Reset all Abuse data</button>
          </form>
        </div>
        '''
        if start >= 0 and end > start:
            html = html[:start] + manage_card + html[end:]
        else:
            marker = '<div class="card vm-table-card">'
            html = html.replace(marker, manage_card + marker, 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.12.9 Admin Abuse controls")
    return response

app.view_functions["admin_abuse_page"] = admin_abuse_page_v48129

def vm_abuse_page_v48129():
    tab = (request.args.get("tab") or "current").strip().lower()
    if tab in {"history", "incidents", "summary", "events", "raw", "raw-events"}:
        tab = "events"
    if tab not in {"current", "events"}:
        tab = "current"
    values = _v48128_filter_values()
    if tab == "events":
        values["limit"] = min(values["limit"], 200)
    current_sorts = {"node", "uuid", "type", "severity", "rx_mbps", "tx_mbps", "rx_peak", "tx_peak", "cpu", "cpucore", "ram", "ramused", "ramrss", "ramassigned", "diskr", "diskw", "readiops", "writeiops", "duration", "last_seen"}
    event_sorts = {"node", "uuid", "occurrences", "active", "duration", "longest", "severity", "last_seen"}
    if tab == "current" and values["sort"] not in current_sorts:
        values["sort"] = "severity"
    if tab == "events" and values["sort"] not in event_sorts:
        values["sort"] = "occurrences"
    nodes = _v48126_visible_nodes()
    cfg = get_abuse_settings()
    content = f"""<div class="card page-hero"><div><span class="eyebrow">VM ABUSE</span><h2>Abuse Monitor</h2><p>Current Abuse is a full operations table. Abuse Events groups repeat occurrences by VM with exact start, end and duration.</p></div><div class="hero-meta"><span>Policy <b>v{cfg['revision']}</b></span><span>Engine <b>{ABUSE_ENGINE_VERSION}</b></span><span>Retention <b>7 days</b></span></div></div>
    <div class="card abuse-toolbar abuse-toolbar-v48128">{_v48127_tabs(tab)}{_v48128_filter_form(tab, values, nodes)}</div>
    <details class="card policy-fold"><summary>Current policy</summary>{_public_abuse_policy(cfg)}</details>"""
    content += _v48129_current_page(values) if tab == "current" else _v48129_events_page(values)
    return page("VM Abuse", content)

app.view_functions["vm_abuse_page"] = vm_abuse_page_v48129

V48129_UI_CSS = r"""
<style id="v48129-operations-abuse-ui">
/* Current Abuse: one balanced, operations-first table. */
.abuse-current-v48129{min-width:2180px;table-layout:fixed}.abuse-current-v48129 th:nth-child(1){width:48px}.abuse-current-v48129 th:nth-child(2){width:300px}.abuse-current-v48129 th:nth-child(3){width:390px}.abuse-current-v48129 th:nth-child(4){width:250px}.abuse-current-v48129 th:nth-child(5){width:270px}.abuse-current-v48129 th:nth-child(6){width:215px}.abuse-current-v48129 th:nth-child(7){width:305px}.abuse-current-v48129 th:nth-child(8){width:250px}.abuse-current-v48129 th:nth-child(9){width:180px}
.abuse-current-v48129 td{vertical-align:middle!important}.metric-sort-head>div{font-size:10.5px;font-weight:950;letter-spacing:.02em}.metric-sort-head small{display:flex!important;gap:4px;align-items:center;justify-content:center;flex-wrap:wrap;margin-top:5px}.metric-sort-head .sort-link{padding:2px 4px!important;border-radius:5px;white-space:nowrap}.metric-sort-head .sort-link:hover{background:#eaf2ff}.metric-pair-rich>div{min-width:0}.metric-pair-rich b{font-size:13px!important;white-space:nowrap}.metric-pair-rich small{display:block!important;margin-top:5px!important;line-height:1.25!important;white-space:normal!important}.metric-pair-rich .selected{outline:1px solid #84adff;outline-offset:4px;border-radius:6px}
.reason-severity-v48129{display:flex;flex-direction:column;align-items:flex-start;gap:8px}.reason-severity-v48129 .severity-line{margin:0}.reason-severity-v48129 .severity-line b{font-size:20px}.reason-severity-v48129 .severity-line span{font-size:10px;font-weight:900;letter-spacing:.05em}.severity-network b{color:#1570ef!important}.severity-cpu b{color:#d92d20!important}.severity-ram b{color:#7f56d9!important}.severity-disk b{color:#dc6803!important}.abuse-rule-chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.abuse-rule-chip{display:inline-flex;align-items:center;min-height:25px;padding:4px 8px;border-radius:8px;border:1px solid;font-size:10px;font-weight:850;line-height:1.2;white-space:normal}.chip-network{background:#eff8ff;border-color:#84caff;color:#175cd3}.chip-cpu{background:#fff1f3;border-color:#fda29b;color:#b42318}.chip-ram{background:#f9f5ff;border-color:#d6bbfb;color:#6941c6}.chip-disk{background:#fff6ed;border-color:#fdba74;color:#b54708}.chip-time{background:#fffaeb;border-color:#fec84b;color:#93370d}.chip-neutral{background:#f2f4f7;border-color:#d0d5dd;color:#344054}.ratio-source{display:block!important;max-width:360px;color:#667085!important;font-size:9.5px!important;line-height:1.35;white-space:normal;overflow-wrap:anywhere}
.resource-block{min-width:0;display:flex;flex-direction:column;justify-content:center;text-align:center;padding:2px 0}.resource-primary{display:block;font-size:18px;line-height:1.05;white-space:nowrap;color:#101828}.resource-context{display:flex;justify-content:center;align-items:baseline;gap:0;margin-top:5px;font-size:9.5px;line-height:1.15;white-space:nowrap}.resource-context b{font-size:9.5px;color:#344054}.resource-context span{color:#667085}.resource-meter{display:block;height:5px;margin-top:8px;border-radius:999px;background:#e4e7ec;overflow:hidden}.resource-meter i{display:block;height:100%;border-radius:inherit;background:#12b76a}.resource-foot{display:block!important;margin-top:5px!important;font-size:9px!important;color:#475467!important;text-align:right;white-space:nowrap!important}.resource-warm .resource-meter i{background:#fdb022}.resource-hot .resource-meter i{background:#f79009}.resource-critical .resource-meter i{background:#f04438}.resource-warm .resource-primary,.resource-warm .resource-context b{color:#b54708}.resource-hot .resource-primary,.resource-hot .resource-context b,.resource-critical .resource-primary,.resource-critical .resource-context b{color:#b42318}.ram-resource .resource-primary{font-size:15px}.ram-resource .resource-context{margin-top:6px}.ram-resource .resource-foot{text-align:left}
.abuse-events-v48129{min-width:1530px;table-layout:fixed}.abuse-events-v48129 th:nth-child(1){width:48px}.abuse-events-v48129 th:nth-child(2){width:300px}.abuse-events-v48129 th:nth-child(3){width:130px}.abuse-events-v48129 th:nth-child(4),.abuse-events-v48129 th:nth-child(5){width:155px}.abuse-events-v48129 th:nth-child(6){width:125px}.abuse-events-v48129 th:nth-child(7){width:310px}.abuse-events-v48129 th:nth-child(8){width:175px}.abuse-events-v48129 th:nth-child(9){width:160px}.compact-rule-chips{margin-top:7px;max-height:58px;overflow:hidden}.event-primary-line{display:flex;align-items:center}.event-occurrence-table .abuse-rule-chips{min-width:360px}
/* Admin Abuse data controls. */
.abuse-data-map-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.abuse-data-map-grid>div{display:flex;flex-direction:column;gap:4px;padding:12px;border:1px solid var(--line,#e5e7eb);border-radius:10px;background:var(--surface,#fff)}.abuse-data-map-grid small{font-weight:900;color:#667085}.abuse-data-map-grid b{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.abuse-data-map-grid span{font-size:11px;color:#667085}.vm-abuse-manage-grid{display:grid;grid-template-columns:minmax(170px,1fr) minmax(240px,1.35fr) minmax(260px,1.45fr) minmax(300px,1.5fr) auto;gap:10px;align-items:end}.abuse-clear-options{display:grid;gap:6px;padding:8px 10px;border:1px solid var(--line,#e5e7eb);border-radius:9px}.abuse-clear-options label{display:flex!important;align-items:center;gap:7px;margin:0!important}.abuse-clear-options input[type=checkbox]{width:16px!important;height:16px!important;min-height:0!important}.reset-all-abuse-v48129{border-color:#fda29b!important;background:linear-gradient(135deg,#fff7f7,#fff)!important}.reset-all-abuse-v48129 h3{color:#b42318}.reset-all-abuse-form{display:grid;grid-template-columns:minmax(260px,1fr) auto;gap:10px;align-items:end}.reset-all-abuse-form button{height:42px}
html[data-theme=dark] .metric-sort-head .sort-link:hover{background:#172554}html[data-theme=dark] .chip-network{background:#0b2545;border-color:#175cd3;color:#b2ddff}html[data-theme=dark] .chip-cpu{background:#35151a;border-color:#b42318;color:#fecdca}html[data-theme=dark] .chip-ram{background:#24153d;border-color:#7f56d9;color:#e9d7fe}html[data-theme=dark] .chip-disk{background:#351c0c;border-color:#dc6803;color:#fedf89}html[data-theme=dark] .chip-time{background:#35290b;border-color:#b54708;color:#fedf89}html[data-theme=dark] .chip-neutral{background:#1f2937;border-color:#475467;color:#d0d5dd}html[data-theme=dark] .resource-meter{background:#26374f}html[data-theme=dark] .resource-values .selected,html[data-theme=dark] .ram-resource-grid .selected{background:#102a46;box-shadow:inset 0 0 0 1px #31577e}html[data-theme=dark] .resource-values span,html[data-theme=dark] .ram-resource-grid span,html[data-theme=dark] .resource-block>small,html[data-theme=dark] .ratio-source{color:#94a3b8!important}html[data-theme=dark] .abuse-data-map-grid>div{background:#0a1624;border-color:#2b4260}html[data-theme=dark] .abuse-data-map-grid small,html[data-theme=dark] .abuse-data-map-grid span{color:#94a3b8}html[data-theme=dark] .reset-all-abuse-v48129{background:linear-gradient(135deg,#2a1518,#101827)!important;border-color:#b42318!important}
@media(max-width:1450px){.vm-abuse-manage-grid{grid-template-columns:repeat(2,minmax(240px,1fr))}.vm-abuse-manage-grid button{width:max-content}.abuse-data-map-grid{grid-template-columns:1fr}}
@media(max-width:760px){.vm-abuse-manage-grid,.reset-all-abuse-form{grid-template-columns:1fr}.vm-abuse-manage-grid button,.reset-all-abuse-form button{width:100%}.abuse-rule-chip{white-space:normal}}

/* r4: keep severity compact and place active duration under the metric that is actually abusing. */
.metric-abuse-time{display:block!important;width:max-content;max-width:100%;margin:7px auto 0;padding:3px 7px;border:1px solid;border-radius:999px;font-size:9px!important;font-weight:900!important;line-height:1.15;white-space:nowrap!important}
.metric-abuse-time-network{background:#eff8ff;border-color:#84caff;color:#175cd3!important}.metric-abuse-time-cpu{background:#fff1f3;border-color:#fda29b;color:#b42318!important}.metric-abuse-time-ram{background:#f9f5ff;border-color:#d6bbfb;color:#6941c6!important}.metric-abuse-time-disk{background:#fff6ed;border-color:#fdba74;color:#b54708!important}
.reason-severity-v48129{gap:7px}.reason-severity-v48129 .abuse-rule-chips{max-width:100%}.reason-severity-v48129 .ratio-source{display:none!important}
.vm-detail-cpu-stat{display:flex!important;flex-direction:column;justify-content:center}.vm-detail-cpu-stat .vm-detail-stat-label{font-size:11px;font-weight:850;color:var(--muted,#667085);text-transform:uppercase;letter-spacing:.03em}.vm-detail-cpu-stat>b{margin-top:4px}.vm-detail-cpu-stat .resource-meter{width:100%;margin-top:8px}.vm-detail-cpu-stat small{margin-top:6px!important}.vm-detail-cpu-meter{height:6px}
html[data-theme=dark] .metric-abuse-time-network{background:#0b2545;border-color:#175cd3;color:#b2ddff!important}html[data-theme=dark] .metric-abuse-time-cpu{background:#35151a;border-color:#b42318;color:#fecdca!important}html[data-theme=dark] .metric-abuse-time-ram{background:#24153d;border-color:#7f56d9;color:#e9d7fe!important}html[data-theme=dark] .metric-abuse-time-disk{background:#351c0c;border-color:#dc6803;color:#fedf89!important}html[data-theme=dark] .vm-detail-cpu-stat .vm-detail-stat-label{color:#94a3b8}
</style>
"""

_page_v48129_base = page

def page(title, content):
    response = _page_v48129_base(title, content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace("</head>", V48129_UI_CSS + NODE_FILESYSTEM_IO_CSS + "</head>", 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.12.9 operations Abuse UI")
    return response

