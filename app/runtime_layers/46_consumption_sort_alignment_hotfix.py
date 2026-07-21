# Release: 50.5.9-prod-r22.8-consumption-sort-alignment-hotfix
# Focused Consumption hotfix:
# - authorize every Node sort key already rendered by the R22 table
# - make text sorts default to ascending order
# - remove COUNT(*) OVER() from the common unfiltered VM sort path
# - push Node Group scope into VM rollup and inventory CTEs before aggregation
# - add deterministic Node/Group sorting and fixed column alignment
# No ingest, schema, formula, endpoint, payload, retention or non-Consumption
# behavior is changed.

V5080_RELEASE = "50.5.9-prod-r22.8-consumption-sort-alignment-hotfix"

# Layer 44 already implements these values in Python. Layer 39's allow-list was
# not extended when the columns were added, so requests silently fell back to
# physical_public_total. Keep the map useful to the legacy SQL wrapper too.
V5058C_NODE_SORTS.update({
    "vm_count": "vm_count",
    "vm_public_rx": "vm_public_rx",
    "vm_public_tx": "vm_public_tx",
    "vm_public_total": "vm_public_total",
    "public_difference": "public_difference",
    "vm_private_rx": "vm_private_rx",
    "vm_private_tx": "vm_private_tx",
    "vm_private_total": "vm_private_total",
    "private_difference": "private_difference",
})

V5080_TEXT_SORTS = {"uuid", "node", "group", "name"}
V5080_GROUP_SORTS = {
    "group", "nodes", "vms",
    "physical_public_rx", "physical_public_tx", "physical_public_total",
    "vm_public_rx", "vm_public_tx", "vm_public_total", "public_difference",
    "physical_private_rx", "physical_private_tx", "physical_private_total",
    "vm_private_rx", "vm_private_tx", "vm_private_total", "private_difference",
    "coverage", "latest_sample",
}

def _v5058c_sort_link(label, key, tab, common, current_sort, current_order, grouped=False):
    if key == current_sort:
        next_order = "asc" if current_order == "desc" else "desc"
    else:
        next_order = "asc" if key in V5080_TEXT_SORTS else "desc"
    args = dict(common)
    args.update({"tab": tab, "sort": key, "order": next_order, "page": 1})
    arrow = ""
    if key == current_sort:
        arrow = " ↓" if current_order == "desc" else " ↑"
    cls = "sort-link active" if key == current_sort else "sort-link"
    if grouped:
        cls += " grouped"
    return '<a class="%s" href="%s">%s%s</a>' % (
        cls,
        escape(url_for("bandwidth_consumption_page", **args), quote=True),
        escape(label), arrow,
    )

# Apply the selected Group before per-bridge/per-VM aggregation. The previous
# wrapper filtered vm_rows after all hourly/daily rows and all NIC config had
# already been grouped, which made every sort click pay the full-system cost.
_v5080_vm_source_sql_base = _v5058c_vm_source_sql

def _v5080_group_scope_sql(alias):
    gid = _r21_selected_group_id()
    sql = (
        " EXISTS (SELECT 1 FROM node_group_memberships vsgm "
        "JOIN node_groups vsg ON vsg.id=vsgm.group_id "
        "WHERE vsgm.node=%s.node AND vsg.is_active=1" % alias
    )
    params = []
    if gid:
        sql += " AND vsg.id=?"
        params.append(gid)
    return sql + ")", params

def _v5058c_vm_source_sql(start, end, selected_node=""):
    sql, params = _v5080_vm_source_sql_base(start, end, selected_node)
    scope_sql, scope_params = _v5080_group_scope_sql("vsrc")
    return "SELECT vsrc.* FROM (%s) vsrc WHERE %s" % (sql, scope_sql), list(params) + scope_params

def _v5058c_visible_vm_cte(selected_node=""):
    gid = _r21_selected_group_id()
    node_filter = " AND l.node=?" if selected_node else ""
    group_filter = ""
    params = []
    if selected_node:
        params.append(selected_node)
    if gid:
        group_filter = " AND g.id=?"
        params.append(gid)
    params.extend([PUBLIC_BRIDGE, PRIVATE_BRIDGE])
    sql = """
      scoped_location AS (
        SELECT l.vm_uuid,l.node
          FROM vm_location_latest l
          JOIN node_inventory ni ON ni.node=l.node
          JOIN vm_inventory vi ON vi.node=l.node AND vi.vm_uuid=l.vm_uuid
         WHERE COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL
           AND COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL%s
           AND EXISTS (
             SELECT 1 FROM node_group_memberships gm
             JOIN node_groups g ON g.id=gm.group_id
              WHERE gm.node=l.node AND g.is_active=1%s
           )
      ),
      node_meta AS (
        SELECT ni.node,
               COALESCE(MAX(CASE WHEN LOWER(COALESCE(ba.role,''))='public' THEN ba.primary_ipv4 END),'') AS node_ip
          FROM node_inventory ni
          JOIN (SELECT DISTINCT node FROM scoped_location) sl ON sl.node=ni.node
          LEFT JOIN node_bridge_addresses_latest ba ON ba.node=ni.node
         GROUP BY ni.node
      ),
      vm_iface_config AS (
        SELECT i.node,i.vm_uuid,
               MAX(CASE WHEN i.bridge=? THEN 1 ELSE 0 END)::integer AS public_configured,
               MAX(CASE WHEN i.bridge=? THEN 1 ELSE 0 END)::integer AS private_configured
          FROM vm_iface_current i
          JOIN scoped_location sl ON sl.node=i.node AND sl.vm_uuid=i.vm_uuid
         GROUP BY i.node,i.vm_uuid
      ),
      visible_vm AS (
        SELECT l.vm_uuid,l.vm_uuid AS vm_name,l.node,
               COALESCE(nm.node_ip,'') AS node_ip,
               COALESCE(cfg.public_configured,0) AS public_configured,
               COALESCE(cfg.private_configured,0) AS private_configured
          FROM scoped_location l
          LEFT JOIN node_meta nm ON nm.node=l.node
          LEFT JOIN vm_iface_config cfg ON cfg.node=l.node AND cfg.vm_uuid=l.vm_uuid
      )
    """ % (node_filter, group_filter)
    return sql, params

# The default sort path has no search/coverage predicate. Its total is exactly
# the visible inventory count, so COUNT(*) OVER() needlessly widens and retains
# the complete aggregated result during every sort. Cache the compact count and
# let PostgreSQL use a top-N sort for the requested page.
def _v5080_visible_vm_count(selected_node=""):
    gid = _r21_selected_group_id()
    try:
        generation = safe_int(_v48140_cache_generation(), 0)
    except Exception:
        generation = 0
    key = ("vm-visible-count", gid, selected_node or "", generation)

    def compute():
        where = [
            "COALESCE(ni.status,'active')!='hidden'", "ni.deleted_at IS NULL",
            "COALESCE(vi.status,'active')!='hidden'", "vi.deleted_at IS NULL",
            "g.is_active=1",
        ]
        params = []
        if selected_node:
            where.append("l.node=?")
            params.append(selected_node)
        if gid:
            where.append("g.id=?")
            params.append(gid)
        conn = db()
        try:
            row = conn.execute(
                """SELECT COUNT(*)
                     FROM vm_location_latest l
                     JOIN node_inventory ni ON ni.node=l.node
                     JOIN vm_inventory vi ON vi.node=l.node AND vi.vm_uuid=l.vm_uuid
                     JOIN node_group_memberships gm ON gm.node=l.node
                     JOIN node_groups g ON g.id=gm.group_id
                    WHERE %s""" % " AND ".join(where),
                params,
            ).fetchone()
            return max(0, safe_int(row[0] if row else 0, 0))
        finally:
            conn.close()

    return _r21_cached(key, compute)

_v5080_vm_rows_fallback = _v5058c_vm_rows

def _v5058c_vm_rows(start, end, selected_node, q, coverage, sort_by, order, page_no, limit):
    # Search and coverage need the original exact COUNT path.
    if str(q or "").strip() or _v5058c_coverage(coverage) != "all":
        return _v5080_vm_rows_fallback(
            start, end, selected_node, q, coverage, sort_by, order, page_no, limit,
        )

    start, end = _r21_normalized_range(start, end)
    sort_by = sort_by if sort_by in V5058C_VM_SORTS else "public_total"
    order = _v5058c_order(order)
    page_no = max(1, safe_int(page_no, 1))
    limit = max(1, safe_int(limit, 100))
    gid = _r21_selected_group_id()
    try:
        generation = safe_int(_v48140_cache_generation(), 0)
    except Exception:
        generation = 0
    cache_key = (
        "vm-page-r228", start, end, gid, selected_node or "", sort_by, order,
        page_no, limit, generation,
    )

    def compute():
        effective_page = page_no
        total = _v5080_visible_vm_count(selected_node)
        max_page = max(1, int(_r20_math.ceil(total / float(limit))))
        if effective_page > max_page:
            effective_page = 1
        group_sql, group_params = _v5080_group_scope_sql("vm_rows")
        order_column = V5058C_VM_SORTS[sort_by]
        # Keep the secondary order deterministic without reversing every tie merely
        # because a numeric primary column is descending.
        tie_column = "node" if sort_by == "uuid" else "vm_uuid"
        tie_order = order.upper() if sort_by in V5080_TEXT_SORTS else "ASC"
        ctes, params = _v5058c_vm_ctes(start, end, selected_node)
        conn = db()
        try:
            raw = conn.execute(
                ctes + """
                  SELECT vm_uuid,node,node_ip,public_configured,private_configured,
                         public_rx,public_tx,public_total,
                         private_rx,private_tx,private_total,
                         coverage_percent,latest_sample
                    FROM vm_rows
                   WHERE %s
                   ORDER BY %s %s,%s %s
                   LIMIT ? OFFSET ?
                """ % (group_sql, order_column, order.upper(), tie_column, tie_order),
                params + group_params + [limit, (effective_page - 1) * limit],
            ).fetchall()
        finally:
            conn.close()
        return [tuple(row) for row in raw], total, effective_page, max_page

    return _r21_cached(cache_key, compute)

# Deterministic Node sorting. Text and numeric ties keep Node ascending, and all
# newly rendered columns are now accepted by _v5058c_sort().
def _v5080_node_sort_value(item, sort_by):
    pp = item["physical_public_rx"] + item["physical_public_tx"]
    vp = item["vm_public_rx"] + item["vm_public_tx"]
    pr = item["physical_private_rx"] + item["physical_private_tx"]
    vr = item["vm_private_rx"] + item["vm_private_tx"]
    return {
        "node": item["node"].lower(), "vm_count": item["vm_count"],
        "physical_public_rx": item["physical_public_rx"], "physical_public_tx": item["physical_public_tx"],
        "physical_public_total": pp, "vm_public_rx": item["vm_public_rx"],
        "vm_public_tx": item["vm_public_tx"], "vm_public_total": vp,
        "public_difference": pp - vp,
        "physical_private_rx": item["physical_private_rx"], "physical_private_tx": item["physical_private_tx"],
        "physical_private_total": pr, "vm_private_rx": item["vm_private_rx"],
        "vm_private_tx": item["vm_private_tx"], "vm_private_total": vr,
        "private_difference": pr - vr,
        "coverage": item["coverage_percent"], "latest_sample": item["latest_sample"],
    }.get(sort_by, pp)

def _v5058c_node_rows(start, end, q, coverage, sort_by, order, page_no, limit):
    rows = list(_r21_scoped_nodes(start, end))
    needle = str(q or "").strip().lower()
    if needle:
        rows = [item for item in rows if needle in item["node"].lower() or needle in item["node_ip"].lower()]
    coverage = _v5058c_coverage(coverage)
    if coverage == "complete":
        rows = [item for item in rows if item["latest_sample"] > 0 and item["coverage_percent"] >= 99.5]
    elif coverage == "partial":
        rows = [item for item in rows if item["latest_sample"] > 0 and item["coverage_percent"] < 99.5]
    elif coverage == "no_data":
        rows = [item for item in rows if item["latest_sample"] <= 0]

    rows.sort(key=lambda item: item["node"].lower())
    rows.sort(key=lambda item: _v5080_node_sort_value(item, sort_by), reverse=(_v5058c_order(order) == "desc"))
    total = len(rows)
    page_no = max(1, safe_int(page_no, 1)); limit = max(1, safe_int(limit, 100))
    max_page = max(1, int(_r20_math.ceil(total / float(limit))))
    if page_no > max_page:
        page_no = 1
    offset = (page_no - 1) * limit
    return [_r21_node_tuple(item) for item in rows[offset:offset + limit]], total, page_no, max_page

V5080_CONSUMPTION_ALIGNMENT_CSS = r'''<style id="v5080-consumption-sort-alignment">
body.endpoint-bandwidth-consumption-page .v5058c-vm-table{min-width:1420px!important;table-layout:fixed!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table col.c-vm{width:320px}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table col.c-node{width:190px}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table col.c-metric{width:112px}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table col.c-cover{width:92px}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table col.c-latest{width:145px}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table th,body.endpoint-bandwidth-consumption-page .v5058c-vm-table td{box-sizing:border-box;vertical-align:middle!important}
body.endpoint-bandwidth-consumption-page .v5060-node-table thead tr:first-child th:nth-child(2),
body.endpoint-bandwidth-consumption-page .v5060-group-table thead tr:first-child th:nth-child(2),
body.endpoint-bandwidth-consumption-page .v5060-group-table thead tr:first-child th:nth-child(3){text-align:center!important}
body.endpoint-bandwidth-consumption-page .v5060-node-table tbody td:nth-child(2),
body.endpoint-bandwidth-consumption-page .v5060-group-table tbody td:nth-child(2),
body.endpoint-bandwidth-consumption-page .v5060-group-table tbody td:nth-child(3){text-align:center!important;font-variant-numeric:tabular-nums}
body.endpoint-bandwidth-consumption-page .v5060-node-table thead tr:first-child th:nth-child(5),
body.endpoint-bandwidth-consumption-page .v5060-node-table thead tr:first-child th:nth-child(8),
body.endpoint-bandwidth-consumption-page .v5060-group-table thead tr:first-child th:nth-child(6),
body.endpoint-bandwidth-consumption-page .v5060-group-table thead tr:first-child th:nth-child(9){text-align:center!important;white-space:normal!important;line-height:1.25}
body.endpoint-bandwidth-consumption-page .v5060-node-table tbody td:nth-child(9),
body.endpoint-bandwidth-consumption-page .v5060-node-table tbody td:nth-child(16),
body.endpoint-bandwidth-consumption-page .v5060-group-table tbody td:nth-child(10),
body.endpoint-bandwidth-consumption-page .v5060-group-table tbody td:nth-child(17){text-align:right!important;font-variant-numeric:tabular-nums;font-weight:750}
body.endpoint-bandwidth-consumption-page .sort-link{display:inline-flex;align-items:center;justify-content:center;gap:2px}
body.endpoint-bandwidth-consumption-page th:first-child .sort-link{justify-content:flex-start}
</style>'''

_v5080_vm_table_base = _v5058c_vm_table

def _v5058c_vm_table(rows, common, sort_by, order):
    html = _v5080_vm_table_base(rows, common, sort_by, order)
    marker = '<table class="v5058c-table v5058c-vm-table">'
    cols = ('<colgroup><col class="c-vm"><col class="c-node">'
            + '<col class="c-metric">'*6
            + '<col class="c-cover"><col class="c-latest"></colgroup>')
    if marker in html and "<colgroup>" not in html:
        html = html.replace(marker, marker + cols, 1)
    return V5080_CONSUMPTION_ALIGNMENT_CSS + html

_v5080_node_table_base = _v5058c_node_table

def _v5058c_node_table(rows, common, sort_by, order):
    return V5080_CONSUMPTION_ALIGNMENT_CSS + _v5080_node_table_base(rows, common, sort_by, order)

def _v5080_group_sort_value(item, sort_by):
    return {
        "group": item["name"].lower(), "nodes": item["nodes"], "vms": item["vm_count"],
        "physical_public_rx": item["pp_rx"], "physical_public_tx": item["pp_tx"],
        "physical_public_total": item["pp_total"], "vm_public_rx": item["vp_rx"],
        "vm_public_tx": item["vp_tx"], "vm_public_total": item["vp_total"],
        "public_difference": item["public_diff"],
        "physical_private_rx": item["pr_rx"], "physical_private_tx": item["pr_tx"],
        "physical_private_total": item["pr_total"], "vm_private_rx": item["vr_rx"],
        "vm_private_tx": item["vr_tx"], "vm_private_total": item["vr_total"],
        "private_difference": item["private_diff"], "coverage": item["coverage"],
        "latest_sample": item["latest"],
    }.get(sort_by, item["name"].lower())

def _r20_group_page():
    period = _v5058c_period(request.args.get("period")); _label, seconds = V5058C_PERIODS[period]
    end = now_ts(); start = end - seconds; selected = _r21_selected_group_id()
    sort_by = str(request.args.get("sort") or "group").strip().lower()
    if sort_by not in V5080_GROUP_SORTS:
        sort_by = "group"
    order = _v5058c_order(request.args.get("order") or ("asc" if sort_by == "group" else "desc"))

    grouped = {}
    for item in _r21_node_dataset(start, end):
        gid = item["group_id"]
        if selected and gid != selected:
            continue
        bucket = grouped.setdefault(gid, {"nodes": 0, "vm_count": 0, "coverage_sum": 0.0, "latest": 0})
        bucket["nodes"] += 1; bucket["vm_count"] += item["vm_count"]
        bucket["coverage_sum"] += item["coverage_percent"]
        bucket["latest"] = max(bucket["latest"], item["latest_sample"])
        for key in ("physical_public_rx", "physical_public_tx", "vm_public_rx", "vm_public_tx",
                    "physical_private_rx", "physical_private_tx", "vm_private_rx", "vm_private_tx"):
            bucket[key] = bucket.get(key, 0) + item[key]

    items = []
    for group in _r20_node_groups.all_group_rows(visibility="active"):
        gid, name, _desc, country, _active, _system, _nodes, _vms, *_rest = group
        gid = safe_int(gid, 0)
        if selected and gid != selected:
            continue
        data = grouped.get(gid, {})
        pp_rx = data.get("physical_public_rx", 0); pp_tx = data.get("physical_public_tx", 0)
        vp_rx = data.get("vm_public_rx", 0); vp_tx = data.get("vm_public_tx", 0)
        pr_rx = data.get("physical_private_rx", 0); pr_tx = data.get("physical_private_tx", 0)
        vr_rx = data.get("vm_private_rx", 0); vr_tx = data.get("vm_private_tx", 0)
        nodes = data.get("nodes", 0); latest = data.get("latest", 0)
        items.append({
            "gid": gid, "name": str(name), "country": country, "nodes": nodes,
            "vm_count": data.get("vm_count", 0), "pp_rx": pp_rx, "pp_tx": pp_tx,
            "pp_total": pp_rx + pp_tx, "vp_rx": vp_rx, "vp_tx": vp_tx,
            "vp_total": vp_rx + vp_tx, "public_diff": pp_rx + pp_tx - vp_rx - vp_tx,
            "pr_rx": pr_rx, "pr_tx": pr_tx, "pr_total": pr_rx + pr_tx,
            "vr_rx": vr_rx, "vr_tx": vr_tx, "vr_total": vr_rx + vr_tx,
            "private_diff": pr_rx + pr_tx - vr_rx - vr_tx,
            "coverage": data.get("coverage_sum", 0.0) / nodes if nodes else 0.0,
            "latest": latest,
        })

    items.sort(key=lambda item: item["name"].lower())
    items.sort(key=lambda item: _v5080_group_sort_value(item, sort_by), reverse=(order == "desc"))
    common = {"tab": "group", "period": period, "group": selected or None, "sort": sort_by, "order": order}
    h = lambda label, key: _v5058c_sort_link(label, key, "group", common, sort_by, order)

    rows = []
    for item in items:
        href = url_for("bandwidth_consumption_page", tab="node", period=period, group=item["gid"])
        values = (item["pp_rx"], item["pp_tx"], item["pp_total"], item["vp_rx"], item["vp_tx"], item["vp_total"])
        private_values = (item["pr_rx"], item["pr_tx"], item["pr_total"], item["vr_rx"], item["vr_tx"], item["vr_total"])
        cells = ''.join('<td>%s</td>' % _v5058c_bytes(value) for value in values)
        cells += '<td class="v5060-diff %s">%s</td>' % (
            "positive" if item["public_diff"] > 0 else "negative" if item["public_diff"] < 0 else "",
            _r20_signed_bytes(item["public_diff"]),
        )
        cells += ''.join('<td>%s</td>' % _v5058c_bytes(value) for value in private_values)
        cells += '<td class="v5060-diff %s">%s</td>' % (
            "positive" if item["private_diff"] > 0 else "negative" if item["private_diff"] < 0 else "",
            _r20_signed_bytes(item["private_diff"]),
        )
        rows.append(
            '<tr><td class="v5060-group"><a href="%s"><b>%s%s</b></a></td>'
            '<td>%s</td><td>%s</td>%s<td>%s</td><td class="v5058c-latest">%s</td></tr>' % (
                escape(href, quote=True), _r20_node_groups.flag_html(item["country"]), escape(item["name"]),
                f'{item["nodes"]:,}', f'{item["vm_count"]:,}', cells,
                _v5058c_coverage_cell(item["coverage"], item["latest"]), _v5058c_latest_cell(item["latest"]),
            )
        )

    body = ''.join(rows) or '<tr><td colspan="19" class="empty">No Node Group consumption in this range.</td></tr>'
    periods = ''.join(
        '<a class="%s" href="%s">%s</a>' % (
            'active' if key == period else '',
            url_for("bandwidth_consumption_page", tab="group", period=key, group=selected or None, sort=sort_by, order=order),
            escape(value[0]),
        ) for key, value in V5058C_PERIODS.items()
    )
    tabs = '<div class="v5058c-tabs"><a href="%s">VM Consumption</a><a href="%s">Node Consumption</a><a class="active" href="%s">Node Group</a></div>' % (
        url_for("bandwidth_consumption_page", tab="vm", period=period),
        url_for("bandwidth_consumption_page", tab="node", period=period),
        url_for("bandwidth_consumption_page", tab="group", period=period, sort=sort_by, order=order),
    )
    cols = '<colgroup><col class="c-id"><col class="c-count"><col class="c-count">' + '<col class="c-metric">'*6 + '<col class="c-diff">' + '<col class="c-metric">'*6 + '<col class="c-diff"><col class="c-cover"><col class="c-latest"></colgroup>'
    second = ''.join([
        '<th>%s</th>' % h("RX", "physical_public_rx"), '<th>%s</th>' % h("TX", "physical_public_tx"), '<th>%s</th>' % h("TOTAL", "physical_public_total"),
        '<th>%s</th>' % h("RX", "vm_public_rx"), '<th>%s</th>' % h("TX", "vm_public_tx"), '<th>%s</th>' % h("TOTAL", "vm_public_total"),
        '<th>%s</th>' % h("RX", "physical_private_rx"), '<th>%s</th>' % h("TX", "physical_private_tx"), '<th>%s</th>' % h("TOTAL", "physical_private_total"),
        '<th>%s</th>' % h("RX", "vm_private_rx"), '<th>%s</th>' % h("TX", "vm_private_tx"), '<th>%s</th>' % h("TOTAL", "vm_private_total"),
    ])
    table = '''<div class="v5058c-table-wrap table-wrap"><table class="v5058c-table v5058c-node-table v5060-group-table">%s<thead><tr><th rowspan="2">%s</th><th rowspan="2">%s</th><th rowspan="2">%s</th><th colspan="3">PHYSICAL PUBLIC</th><th colspan="3">ALL VM PUBLIC</th><th rowspan="2">%s</th><th colspan="3">PHYSICAL PRIVATE</th><th colspan="3">ALL VM PRIVATE</th><th rowspan="2">%s</th><th rowspan="2">%s</th><th rowspan="2">%s</th></tr><tr>%s</tr></thead><tbody>%s</tbody></table></div>''' % (
        cols, h("NODE GROUP", "group"), h("NODES", "nodes"), h("VMS", "vms"),
        h("PUBLIC DIFF", "public_difference"), h("PRIVATE DIFF", "private_difference"),
        h("COVERAGE", "coverage"), h("LATEST", "latest_sample"), second, body,
    )
    content = '''%s%s<div class="card v5058c-shell"><div class="v5058c-head"><div><h2>Consumption</h2><p>Node Group totals reuse the node-only ingest-time rollups. No VM/NIC aggregation runs while rendering this tab.</p></div><div class="v5058c-range"><div class="v5058c-range-block"><span>TIME RANGE</span><div class="v5058c-periods">%s</div></div></div></div>%s<form class="v5058c-toolbar" method="get"><input type="hidden" name="tab" value="group"><input type="hidden" name="period" value="%s"><input type="hidden" name="sort" value="%s"><input type="hidden" name="order" value="%s">%s<button type="submit">Apply</button><a class="clear" href="%s">Reset</a></form>%s</div>''' % (
        V5060_CONSUMPTION_CSS, V5080_CONSUMPTION_ALIGNMENT_CSS, periods, tabs, period,
        escape(sort_by, quote=True), escape(order, quote=True), _r20_node_groups._group_select(selected),
        url_for("bandwidth_consumption_page", tab="group", period=period), table,
    )
    return page("Consumption", _r20_node_groups._CONSUMPTION_STYLE + content)

# Keep the Node Group wrapper module pointed at the final effective functions.
for _v5080_name, _v5080_value in {
    "_v5058c_sort_link": _v5058c_sort_link,
    "_v5058c_vm_rows": _v5058c_vm_rows,
    "_v5058c_node_rows": _v5058c_node_rows,
    "_v5058c_vm_table": _v5058c_vm_table,
    "_v5058c_node_table": _v5058c_node_table,
}.items():
    setattr(_r20_node_groups, _v5080_name, _v5080_value)
