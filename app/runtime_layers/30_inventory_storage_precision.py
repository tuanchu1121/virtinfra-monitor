# v48.13.4 admin inventory status filters
# ---------------------------------------------------------------------------

V48134_VERSION = "48.13.4"
V48134_ADMIN_STATUS = {"all", "active", "hidden", "stale"}


def _v48134_clean_admin_status(value):
    value = str(value or "all").strip().lower()
    return value if value in V48134_ADMIN_STATUS else "all"


def _v48134_status_sql(alias, last_col, status):
    cutoff = now_ts() - VM_STALE_SECONDS
    hidden = f"(COALESCE({alias}.status,'active')='hidden' OR {alias}.deleted_at IS NOT NULL)"
    if status == "hidden":
        return hidden, []
    if status == "active":
        return f"NOT {hidden} AND COALESCE({alias}.{last_col},0)>=?", [cutoff]
    if status == "stale":
        return f"NOT {hidden} AND COALESCE({alias}.{last_col},0)<?", [cutoff]
    return "1=1", []


def _v48134_admin_pager(section, q, status, page_no, max_page, per_page):
    if max_page <= 1:
        return ""
    common = {"section": section, "q": q or None, "status": status, "per_page": per_page}
    prev_url = url_for("admin_page", **common, page=max(1, page_no - 1))
    next_url = url_for("admin_page", **common, page=min(max_page, page_no + 1))
    prev_cls = "disabled" if page_no <= 1 else ""
    next_cls = "disabled" if page_no >= max_page else ""
    return f'<div class="pagination"><a class="btn {prev_cls}" href="{escape(prev_url,quote=True)}">← Previous</a><span>Page <b>{page_no}</b> / <b>{max_page}</b></span><a class="btn {next_cls}" href="{escape(next_url,quote=True)}">Next →</a></div>'


def _v48134_admin_nodes(q, status, page_no, per_page):
    status = _v48134_clean_admin_status(status)
    status_sql, params = _v48134_status_sql("ni", "last_push", status)
    where = [status_sql]
    if q:
        p = like_pattern(q)
        normalized_mac = normalize_mac_address(q)
        where.append("""(
            ni.node LIKE ?
            OR EXISTS (
                SELECT 1 FROM node_bridge_addresses_latest b
                 WHERE b.node=ni.node
                   AND (
                        COALESCE(b.primary_ipv4,'') LIKE ?
                        OR COALESCE(b.ipv4_json,'[]') LIKE ?
                        OR COALESCE(b.mac,'') LIKE ?
                        OR (?<>'' AND LOWER(COALESCE(b.mac,''))=LOWER(?))
                   )
            )
            OR EXISTS (
                SELECT 1 FROM vm_inventory v
                 WHERE v.node=ni.node
                   AND (
                        v.vm_uuid LIKE ?
                        OR COALESCE(v.last_iface,'') LIKE ?
                        OR COALESCE(v.last_bridge,'') LIKE ?
                   )
            )
            OR EXISTS (
                SELECT 1 FROM vm_iface_current i
                 WHERE i.node=ni.node
                   AND (
                        i.vm_uuid LIKE ?
                        OR COALESCE(i.iface,'') LIKE ?
                        OR COALESCE(i.bridge,'') LIKE ?
                   )
            )
            OR EXISTS (
                SELECT 1 FROM vm_nic_identity_lookup l
                JOIN vm_iface_current i
                  ON i.node=l.node AND i.vm_uuid=l.vm_uuid
                 AND i.bridge=l.bridge AND i.iface=l.iface AND i.mac=l.mac
                 WHERE l.node=ni.node
                   AND (l.mac LIKE ? OR (?<>'' AND l.mac=?))
            )
            OR EXISTS (
                SELECT 1 FROM node_physical_net_latest pn
                 WHERE pn.node=ni.node
                   AND (
                        COALESCE(pn.iface,'') LIKE ?
                        OR COALESCE(pn.bridge,'') LIKE ?
                   )
            )
            OR EXISTS (
                SELECT 1 FROM node_nic_identity_lookup l
                JOIN node_physical_net_latest pn
                  ON pn.node=l.node AND pn.role=l.role AND pn.mac=l.mac
                 WHERE l.node=ni.node
                   AND (l.mac LIKE ? OR (?<>'' AND l.mac=?))
            )
        )""")
        params.extend([
            p,
            p, p, p, normalized_mac, normalized_mac,
            p, p, p,
            p, p, p,
            p, normalized_mac, normalized_mac,
            p, p,
            p, normalized_mac, normalized_mac,
        ])
    where_sql = "WHERE " + " AND ".join(where)
    conn = db()
    try:
        total = safe_int(conn.execute(f"SELECT COUNT(*) FROM node_inventory ni {where_sql}", params).fetchone()[0], 0)
        max_page = max(1, math.ceil(total / per_page))
        page_no = max(1, min(page_no, max_page))
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
          {where_sql}
          ORDER BY CASE WHEN COALESCE(ni.status,'active')='hidden' OR ni.deleted_at IS NOT NULL THEN 1 ELSE 0 END,
                   ni.node COLLATE NOCASE
          LIMIT ? OFFSET ?
        """, params + [per_page, (page_no - 1) * per_page]).fetchall()
        return rows, total, page_no, max_page
    finally:
        conn.close()


def _v48134_admin_vms(q, status, page_no, per_page):
    status = _v48134_clean_admin_status(status)
    status_sql, params = _v48134_status_sql("vi", "last_seen", status)
    where = [status_sql]
    if q:
        p = like_pattern(q)
        normalized_mac = normalize_mac_address(q)
        where.append("""(
            vi.node LIKE ?
            OR vi.vm_uuid LIKE ?
            OR COALESCE(vi.last_iface,'') LIKE ?
            OR COALESCE(vi.last_bridge,'') LIKE ?
            OR EXISTS (
                SELECT 1 FROM node_bridge_addresses_latest b
                 WHERE b.node=vi.node
                   AND (
                        COALESCE(b.primary_ipv4,'') LIKE ?
                        OR COALESCE(b.ipv4_json,'[]') LIKE ?
                        OR COALESCE(b.mac,'') LIKE ?
                        OR (?<>'' AND LOWER(COALESCE(b.mac,''))=LOWER(?))
                   )
            )
            OR EXISTS (
                SELECT 1 FROM vm_iface_current i
                 WHERE i.node=vi.node AND i.vm_uuid=vi.vm_uuid
                   AND (
                        COALESCE(i.iface,'') LIKE ?
                        OR COALESCE(i.bridge,'') LIKE ?
                   )
            )
            OR EXISTS (
                SELECT 1 FROM vm_nic_identity_lookup l
                JOIN vm_iface_current i
                  ON i.node=l.node AND i.vm_uuid=l.vm_uuid
                 AND i.bridge=l.bridge AND i.iface=l.iface AND i.mac=l.mac
                 WHERE l.node=vi.node AND l.vm_uuid=vi.vm_uuid
                   AND (l.mac LIKE ? OR (?<>'' AND l.mac=?))
            )
        )""")
        params.extend([
            p, p, p, p,
            p, p, p, normalized_mac, normalized_mac,
            p, p,
            p, normalized_mac, normalized_mac,
        ])
    where_sql = "WHERE " + " AND ".join(where)
    conn = db()
    try:
        total = safe_int(conn.execute(f"SELECT COUNT(*) FROM vm_inventory vi {where_sql}", params).fetchone()[0], 0)
        max_page = max(1, math.ceil(total / per_page))
        page_no = max(1, min(page_no, max_page))
        rows = conn.execute(f"""
          WITH bridge_ip AS (
            SELECT node,MAX(CASE WHEN LOWER(role)='public' THEN primary_ipv4 ELSE '' END) public_ipv4,
                        MAX(CASE WHEN LOWER(role)='private' THEN primary_ipv4 ELSE '' END) private_ipv4
            FROM node_bridge_addresses_latest GROUP BY node
          )
          SELECT vi.node,vi.vm_uuid,vi.status,vi.last_seen,vi.last_bridge,vi.last_iface,vi.deleted_at,COALESCE(b.public_ipv4,''),COALESCE(b.private_ipv4,'')
          FROM vm_inventory vi LEFT JOIN bridge_ip b ON b.node=vi.node
          {where_sql}
          ORDER BY CASE WHEN COALESCE(vi.status,'active')='hidden' OR vi.deleted_at IS NOT NULL THEN 1 ELSE 0 END,
                   vi.node COLLATE NOCASE,vi.last_seen DESC
          LIMIT ? OFFSET ?
        """, params + [per_page, (page_no - 1) * per_page]).fetchall()
        return rows, total, page_no, max_page
    finally:
        conn.close()


def _v48134_status_options(selected):
    labels = (("all", "All status"), ("active", "Active"), ("hidden", "Hidden"), ("stale", "Stale"))
    return "".join(f'<option value="{key}"{" selected" if selected == key else ""}>{label}</option>' for key, label in labels)


def _v48134_admin_nodes_section(q, status, page_no, per_page):
    rows, total, page_no, max_page = _v48134_admin_nodes(q, status, page_no, per_page)
    body = ""
    cutoff = now_ts() - VM_STALE_SECONDS
    for node, row_status, last_push, deleted_at, vm_count, pub, priv in rows:
        is_hidden = row_status == "hidden" or bool(deleted_at)
        is_stale = not is_hidden and safe_int(last_push, 0) < cutoff
        display_status = "hidden" if is_hidden else ("stale" if is_stale else "active")
        forms = admin_form(url_for('admin_delete_node'), 'Hide', {'node': node, 'mode': 'soft'}, danger=True, confirm='Hide node from dashboard? Raw usage is kept.')
        forms += admin_form(url_for('admin_restore_node'), 'Restore', {'node': node}, danger=False, confirm='Restore node to dashboard?')
        forms += admin_form(url_for('admin_purge_node_vms'), 'Purge VMs', {'node': node}, danger=True, confirm='Purge every VM and VM history under this node?')
        forms += admin_form(url_for('admin_delete_node'), 'Purge node', {'node': node, 'mode': 'purge'}, danger=True, confirm='Permanently purge this node and all monitoring data?')
        body += f'''<tr class="{'stale-row' if is_hidden or is_stale else ''}"><td><input class="node-select" form="bulk-nodes-form" type="checkbox" name="nodes" value="{escape(node,quote=True)}"></td><td><b>{escape(node)}</b><small class="row-sub">{escape(display_status)}</small></td><td class="mono">{escape(compact_ipv4(pub) or '-')}</td><td class="mono">{escape(compact_ipv4(priv) or '-')}</td><td class="num"><b>{safe_int(vm_count,0)}</b></td><td>{fmt_full(last_push)}</td><td>{_v490_action_menu(forms)}</td></tr>'''
    if not body:
        body = '<tr><td colspan="7" class="empty">No nodes match this filter</td></tr>'
    return f'''
    <div class="card"><div class="section-head"><div><h3>Node management</h3><p>{total:,} matching node(s). Filter active, hidden or stale inventory without loading everything.</p></div></div>
    <form class="search" method="get"><input type="hidden" name="section" value="nodes"><input name="q" value="{escape(q,quote=True)}" placeholder="Search node, IP, MAC, VM, bridge or interface"><select name="status">{_v48134_status_options(status)}</select><select name="per_page"><option value="100" {'selected' if per_page==100 else ''}>100 rows</option><option value="200" {'selected' if per_page==200 else ''}>200 rows</option><option value="500" {'selected' if per_page==500 else ''}>500 rows</option></select><button>Filter</button><a class="clear" href="{url_for('admin_page',section='nodes')}">Reset</a></form>
    <form id="bulk-nodes-form" method="post" action="{url_for('admin_bulk_nodes')}" onsubmit="return confirm('Apply selected node action?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><div class="bulk-bar compact-bulk"><label><input type="checkbox" onclick="document.querySelectorAll('.node-select').forEach(cb=>cb.checked=this.checked)"> Select page</label><select name="action"><option value="hide">Hide</option><option value="restore">Restore</option><option value="purge_vms">Purge all VMs</option><option value="purge">Purge node</option></select><button class="btn-danger">Apply</button></div></form>
    <div class="table-wrap"><table class="admin-clean-table"><thead><tr><th></th><th>NODE / STATUS</th><th>PUBLIC IP</th><th>PRIVATE IP</th><th>VM</th><th>LAST PUSH</th><th>ACTION</th></tr></thead><tbody>{body}</tbody></table></div>{_v48134_admin_pager('nodes',q,status,page_no,max_page,per_page)}</div>'''


def _v48134_admin_vms_section(q, status, page_no, per_page):
    rows, total, page_no, max_page = _v48134_admin_vms(q, status, page_no, per_page)
    body = ""
    cutoff = now_ts() - VM_STALE_SECONDS
    for node, vm_uuid, row_status, last_seen, bridge, iface, deleted_at, pub, priv in rows:
        is_hidden = row_status == "hidden" or bool(deleted_at)
        is_stale = not is_hidden and safe_int(last_seen, 0) < cutoff
        display_status = "hidden" if is_hidden else ("stale" if is_stale else "active")
        forms = admin_form(url_for('admin_delete_vm'), 'Hide', {'node': node, 'vm_uuid': vm_uuid, 'mode': 'soft'}, danger=True, confirm='Hide VM from dashboard? Raw usage is kept.')
        forms += admin_form(url_for('admin_restore_vm'), 'Restore', {'node': node, 'vm_uuid': vm_uuid}, danger=False, confirm='Restore VM to dashboard?')
        forms += admin_form(url_for('admin_delete_vm'), 'Purge VM', {'node': node, 'vm_uuid': vm_uuid, 'mode': 'purge'}, danger=True, confirm='Permanently purge only this UUID from every VM-scoped table?')
        value = escape(f"{node}\t{vm_uuid}", quote=True)
        body += f'''<tr class="{'stale-row' if is_hidden or is_stale else ''}"><td><input class="vm-select" form="bulk-vms-form" type="checkbox" name="vms" value="{value}"></td><td><b>{escape(node)}</b><small class="row-sub">{escape(compact_ipv4(pub) or '-')}</small></td><td class="mono"><span class="uuid-cell">{escape(vm_uuid)}<button type="button" class="copy-btn" data-copy="{escape(vm_uuid,quote=True)}">⧉</button></span></td><td><b>{escape(display_status)}</b><small class="row-sub">{fmt_push(last_seen)}</small></td><td>{escape(bridge or '-')}<small class="row-sub">{escape(iface or '-')}</small></td><td>{_v490_action_menu(forms)}</td></tr>'''
    if not body:
        body = '<tr><td colspan="6" class="empty">No VMs match this filter</td></tr>'
    return f'''
    <div class="card"><div class="section-head"><div><h3>VM management</h3><p>{total:,} matching VM(s). Status filter separates active, hidden and stale inventory.</p></div></div>
    <form class="search" method="get"><input type="hidden" name="section" value="vms"><input name="q" value="{escape(q,quote=True)}" placeholder="Search node, IP, MAC, VM UUID, bridge or interface"><select name="status">{_v48134_status_options(status)}</select><select name="per_page"><option value="100" {'selected' if per_page==100 else ''}>100 rows</option><option value="200" {'selected' if per_page==200 else ''}>200 rows</option><option value="500" {'selected' if per_page==500 else ''}>500 rows</option></select><button>Filter</button><a class="clear" href="{url_for('admin_page',section='vms')}">Reset</a></form>
    <form id="bulk-vms-form" method="post" action="{url_for('admin_bulk_vms')}" onsubmit="return confirm('Apply selected VM action?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><div class="bulk-bar compact-bulk"><label><input type="checkbox" onclick="document.querySelectorAll('.vm-select').forEach(cb=>cb.checked=this.checked)"> Select page</label><select name="action"><option value="hide">Hide</option><option value="restore">Restore</option><option value="purge">Purge</option></select><button class="btn-danger">Apply</button></div></form>
    <div class="table-wrap"><table class="admin-clean-table"><thead><tr><th></th><th>NODE / IP</th><th>VM UUID</th><th>STATUS / SEEN</th><th>BRIDGE / IFACE</th><th>ACTION</th></tr></thead><tbody>{body}</tbody></table></div>{_v48134_admin_pager('vms',q,status,page_no,max_page,per_page)}</div>'''


def admin_page_v48134():
    deny = require_admin()
    if deny:
        return deny
    section = (request.args.get('section') or 'overview').strip().lower()
    if section not in {'overview', 'nodes', 'vms', 'maintenance'}:
        section = 'overview'
    q = (request.args.get('q') or '').strip()
    status = _v48134_clean_admin_status(request.args.get('status'))
    page_no = max(1, safe_int(request.args.get('page'), 1))
    per_page = max(25, min(500, safe_int(request.args.get('per_page'), 200)))
    dbmsg = (request.args.get('dbmsg') or '').strip()[:700]
    dberr = (request.args.get('dberr') or '').strip()[:700]
    stats = _v490_admin_stats()
    if section == 'overview':
        section_html = _v490_admin_overview(stats)
    elif section == 'nodes':
        section_html = _v48134_admin_nodes_section(q, status, page_no, per_page)
    elif section == 'vms':
        section_html = _v48134_admin_vms_section(q, status, page_no, per_page)
    else:
        section_html = _v490_live_cache_card() + database_maintenance_card(dbmsg, dberr)
    content = f'''
    <div class="card admin-hero"><div><span class="eyebrow">CONTROL CENTER</span><h2>Administration</h2><p>Inventory, policy, users and maintenance are separated into focused sections.</p></div><div class="admin-user-actions"><a class="btn" href="{url_for('index')}">Dashboard</a><a class="btn" href="{url_for('admin_logout')}">Logout</a></div></div>
    {_v490_admin_nav(section)}
    {section_html}
    '''
    return page('Admin', content)


app.view_functions['admin_page'] = admin_page_v48134

# ---------------------------------------------------------------------------
# v48.13.5 filesystem-root precision and capacity-bar polish
# ---------------------------------------------------------------------------

V48135_VERSION = "48.13.5"
V48135_BUILD = "r2"


def _v48135_base_device(device):
    value = str(device or "").strip()
    return value.split("[", 1)[0] if "[" in value else value


def _v48135_mount_rank(mount):
    mount = str(mount or "").rstrip("/") or "/"
    return (0 if mount == "/" else 1, mount.count("/"), len(mount), mount)


def _v48135_real_filesystem_rows(rows):
    """Collapse service-sandbox bind aliases but preserve real /home mounts."""
    chosen = {}
    for row in rows or []:
        if not row:
            continue
        values = tuple(row)
        mount = str(values[0] or "").rstrip("/") or "/"
        device = str(values[1] or "").strip()
        if mount.startswith(("/run", "/sys", "/proc", "/dev")):
            continue
        # findmnt renders sandbox/bind aliases as /dev/X[/etc].  These are not
        # separate storage backends and should never occupy their own row.
        if "[" in device and device.endswith("]"):
            continue
        base_device = _v48135_base_device(device)
        key = base_device or ("mount:" + mount)
        rank = _v48135_mount_rank(mount)
        old = chosen.get(key)
        if old is None or rank < old[0]:
            chosen[key] = (rank, values)
    result = [item[1] for item in chosen.values()]
    result.sort(key=lambda row: _v48135_mount_rank(row[0]))
    return result


_get_node_filesystems_snapshot_v48135_base = get_node_filesystems_snapshot


def get_node_filesystems_snapshot(node, period):
    return _v48135_real_filesystem_rows(_get_node_filesystems_snapshot_v48135_base(node, period))


def node_filesystem_table(rows):
    rows = _v48135_real_filesystem_rows(rows)
    body = ""
    for (
        mount, device, fstype, size, used, avail, use_percent, fs_last_seen,
        read_bps, write_bps, read_iops, write_iops, util_percent, io_last_seen,
    ) in rows:
        pct = max(0.0, safe_float(use_percent, 0.0))
        cls = "warn" if pct >= 85 else ""
        io_seen = max(0, safe_int(io_last_seen, 0))
        io_missing = io_seen <= 0
        body += f'''
        <tr class="{cls}">
          <td class="mono"><b>{escape(mount or '-')}</b></td>
          <td class="mono"><b>{escape(_v48135_base_device(device) or '-')}</b><small class="row-sub">{escape(fstype or '-')}</small></td>
          <td>{_disk_io_capacity(used, size, 'used / size')}</td>
          <td class="num">{human(avail)}</td>
          <td class="num">{'-' if io_missing else human_rate(read_bps)}</td>
          <td class="num"><b>{'-' if io_missing else human_rate(write_bps)}</b></td>
          <td class="num">{'-' if io_missing else _disk_io_iops(read_iops)}</td>
          <td class="num"><b>{'-' if io_missing else _disk_io_iops(write_iops)}</b></td>
          <td class="num"><b>{'-' if io_missing else f'{safe_float(util_percent,0):.1f}%'}</b></td>
          <td class="num">{fmt_push(max(safe_int(fs_last_seen,0), io_seen))}</td>
        </tr>'''
    if not body:
        body = '<tr><td colspan="10" class="empty">No real filesystem data yet</td></tr>'
    return f'''
    <style id="v48135-node-filesystem-bars">
      .node-filesystem-v48135{{min-width:1450px;table-layout:fixed}}
      .node-filesystem-v48135 th:nth-child(1){{width:150px}}.node-filesystem-v48135 th:nth-child(2){{width:270px}}
      .node-filesystem-v48135 th:nth-child(3){{width:280px}}.node-filesystem-v48135 th:nth-child(4){{width:115px}}
      .node-filesystem-v48135 th:nth-child(n+5){{width:110px}}.node-filesystem-v48135 td{{vertical-align:middle}}
      .node-filesystem-v48135 td.num,.node-filesystem-v48135 th:nth-child(n+4){{text-align:right;white-space:nowrap}}
      .node-filesystem-v48135 .disk-capacity{{min-width:220px}}
    </style>
    <div class="card">
      <div class="table-title-row"><div><h3>Node Filesystems</h3><div class="table-hint">Only real filesystem roots are shown. Capacity, Read/Write, IOPS and Util all come from the same selected retained Agent snapshot; older snapshots without a retained Storage payload show I/O as N/A.</div></div></div>
      <div class="table-wrap"><table class="node-filesystem-v48135"><thead><tr>
        <th>Mount</th><th>Device / FS</th><th>USED / SIZE</th><th>Avail</th><th>Read</th><th>Write</th><th>R IOPS</th><th>W IOPS</th><th>Util</th><th>Last</th>
      </tr></thead><tbody>{body}</tbody></table></div>
    </div>'''


V48135_TOP_FIX_CSS = r'''
<style id="v48135-top-disk-meter-fix">
body.app-v490.endpoint-top-page .top-disk-capacity .disk-cap-meter{display:block;height:6px;margin-top:6px;border-radius:999px;background:#e4e7ec;overflow:hidden}
body.app-v490.endpoint-top-page .top-disk-capacity .disk-cap-meter i{display:block;height:100%;border-radius:inherit;background:#12b76a}
body.app-v490.endpoint-top-page .top-disk-capacity.disk-cap-warm .disk-cap-meter i{background:#fdb022}
body.app-v490.endpoint-top-page .top-disk-capacity.disk-cap-hot .disk-cap-meter i{background:#f79009}
body.app-v490.endpoint-top-page .top-disk-capacity.disk-cap-critical .disk-cap-meter i{background:#f04438}
body.app-v490.endpoint-top-page .disk-capacity-sort-head{background:rgba(18,183,106,.035)}
html[data-theme=dark] body.app-v490.endpoint-top-page .top-disk-capacity .disk-cap-meter{background:#334155}
</style>
'''

_top_vm_table_v48135_base = top_vm_table


def top_vm_table(rows, period, q, sort_by, order, scope, limit):
    return V48135_TOP_FIX_CSS + _top_vm_table_v48135_base(rows, period, q, sort_by, order, scope, limit)


def _v48135_vm_disk_total_overview(rows):
    if not rows:
        return ""
    assigned = sum(max(0, safe_int(row[6], 0)) for row in rows)
    allocated = sum(max(0, safe_int(row[7], 0)) for row in rows)
    physical = sum(max(0, safe_int(row[8], 0)) for row in rows)
    pct = allocated * 100.0 / assigned if assigned > 0 else 0.0
    level = _v48133_disk_level(pct)
    return f'''
      <div class="stat vm-disk-total-overview disk-level-{level}">
        <div class="vm-disk-stat-label">VM DISK</div>
        <b>{_disk_io_bytes(allocated)} / {_disk_io_bytes(assigned)}</b>
        <small>{pct:.1f}% allocated · {len(rows)} disk{'s' if len(rows)!=1 else ''}</small>
        <span class="vm-disk-overview-meter"><i style="width:{min(100.0,max(0.0,pct)):.1f}%"></i></span>
        <small class="vm-disk-storage-line">Physical {_disk_io_bytes(physical)} · Host allocated / assigned</small>
      </div>'''


V48135_VM_CSS = r'''
<style id="v48135-vm-disk-total-polish">
.vm-disk-total-overview{min-width:230px}.vm-disk-total-overview>b{display:block;margin-top:5px!important;font-size:15px!important;white-space:nowrap}
.vm-disk-total-overview>small{display:block;margin-top:4px!important}.vm-disk-total-overview .vm-disk-overview-meter{display:block;height:7px;margin-top:8px;border-radius:999px;background:#e4e7ec;overflow:hidden}
.vm-disk-total-overview .vm-disk-overview-meter i{display:block;height:100%;background:#12b76a;border-radius:inherit}.vm-disk-total-overview.disk-level-warm i{background:#fdb022}.vm-disk-total-overview.disk-level-hot i{background:#f79009}.vm-disk-total-overview.disk-level-critical i{background:#f04438}
.vm-disk-detail-grid{grid-template-columns:repeat(auto-fit,minmax(430px,1fr))}.vm-disk-panel{box-shadow:0 1px 2px rgba(16,24,40,.04)}
html[data-theme=dark] .vm-disk-total-overview .vm-disk-overview-meter{background:#334155}
</style>
'''

# Use the original VM renderer as the base so the v48.13.5 insertion is not
# dependent on a previous response-regex wrapper having succeeded.
_vm_page_v48135_base = _vm_page_v48133_base or app.view_functions.get("vm_page")


def vm_page_v48135():
    response = _vm_page_v48135_base()
    try:
        if not hasattr(response, "get_data"):
            return response
        node = (request.args.get("node") or "").strip()
        vm_uuid = (request.args.get("vm_uuid") or "").strip()
        if not node or not vm_uuid:
            return response
        rows = _v48133_vm_disks(node, vm_uuid)
        if not rows:
            return response
        html = response.get_data(as_text=True)
        total_card = _v48135_vm_disk_total_overview(rows)
        details = _v48133_vm_disk_io_card(rows)
        chart_marker = '<div class="vm-charts-grid">'
        chart_pos = html.find(chart_marker)
        if chart_pos >= 0:
            before = html[:chart_pos]
            overview_close = before.rfind('</div></div>')
            if overview_close >= 0 and 'vm-disk-total-overview' not in before:
                before = before[:overview_close] + total_card + before[overview_close:]
            html = before + details + html[chart_pos:]
        elif 'id="virtual-disk-io"' not in html:
            html += details
        html = html.replace('</head>', V48133_VM_CSS + V48135_VM_CSS + '</head>', 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.13.5-r2 VM disk panel UI")
    return response


if _vm_page_v48135_base is not None:
    app.view_functions["vm_page"] = vm_page_v48135


def _v48135_storage_disk_table(conn, values, start_ts):
    """One customer disk per visually distinct row; never group vda/vdb."""
    sort_map = {
        "node":"d.node","uuid":"d.vm_uuid","disk":"d.target","mount":"d.mount",
        "allocated":"d.allocation_bytes","assigned":"d.capacity_bytes",
        "allocpct":"CASE WHEN d.capacity_bytes>0 THEN 1.0*d.allocation_bytes/d.capacity_bytes ELSE -1 END",
        "read":"d.read_bps","write":"d.write_bps","readiops":"d.read_iops","writeiops":"d.write_iops","seen":"d.last_seen",
    }
    if values["sort"] not in sort_map:
        values["sort"] = "writeiops"
    where = ["d.role='customer'", "d.last_seen>=?"]
    params = [start_ts]
    if values.get("node"):
        where.append("d.node=?"); params.append(values["node"])
    if values.get("mount"):
        where.append("d.mount=?"); params.append(values["mount"])
    if values.get("q"):
        p = like_pattern(values["q"])
        where.append(f"(d.node LIKE ? OR d.vm_uuid LIKE ? OR d.target LIKE ? OR d.source LIKE ? OR d.mount LIKE ? OR d.storage_device LIKE ? OR {_v48133_public_ip_sql('d')} LIKE ?)")
        params.extend([p] * 7)
    where_sql = " AND ".join(where)
    total = safe_int(conn.execute(f"SELECT COUNT(*) FROM vm_disk_current d WHERE {where_sql}", params).fetchone()[0], 0)
    pages = max(1, int(math.ceil(total / float(values["limit"]))))
    values["page"] = min(values["page"], pages)
    offset = (values["page"] - 1) * values["limit"]
    direction = "ASC" if values["order"] == "asc" else "DESC"
    rows = conn.execute(f'''
      SELECT d.node,{_v48133_public_ip_sql('d')} AS public_ipv4,d.vm_uuid,d.target,d.source,d.mount,
             d.storage_device,d.storage_block,d.storage_fstype,d.capacity_bytes,d.allocation_bytes,d.physical_bytes,
             d.read_bps,d.write_bps,d.read_iops,d.write_iops,d.last_seen
      FROM vm_disk_current d WHERE {where_sql}
      ORDER BY {sort_map[values['sort']]} {direction},d.node,d.vm_uuid,d.target,d.source
      LIMIT ? OFFSET ?
    ''', params + [values["limit"], offset]).fetchall()
    body = []
    for node,public_ip,vm_uuid,target,source,mount,device,block,fstype,assigned,allocated,physical,rb,wb,ri,wi,seen in rows:
        ip = compact_ipv4(public_ip)
        node_href = url_for("node_page", node=node, period=values["period"])
        vm_href = url_for("vm_page", node=node, vm_uuid=vm_uuid, period=values["period"])
        dev = device or (("/dev/" + block) if block else "-")
        ip_line = f'<span class="storage-node-ip">{escape(ip)}<button type="button" class="copy-btn" data-copy="{escape(ip)}" title="Copy IP">⧉</button></span>' if ip else ''
        body.append(f'''
        <tr class="storage-single-disk-row">
          <td class="storage-node-cell"><a href="{escape(node_href,quote=True)}"><b>{escape(node)}</b></a>{ip_line}</td>
          <td class="storage-uuid-cell"><a href="{escape(vm_href,quote=True)}"><b class="mono">{escape(vm_uuid)}</b></a><button type="button" class="copy-btn" data-copy="{escape(vm_uuid)}" title="Copy UUID">⧉</button></td>
          <td><div class="storage-disk-card"><div class="storage-disk-card-head"><b>{escape(target or '-')}</b><span>{escape(mount or '-')}</span></div><div class="storage-disk-card-device">{escape(dev)}</div><code title="{escape(source or '-',quote=True)}">{escape(source or '-')}</code><small>{escape(fstype or '-')} · Physical {_disk_io_bytes(physical)}</small></div></td>
          <td>{_disk_io_capacity(allocated,assigned)}</td>
          <td class="num">{_disk_io_rate(rb)}</td><td class="num"><b>{_disk_io_rate(wb)}</b></td><td class="num">{_disk_io_iops(ri)}</td><td class="num"><b>{_disk_io_iops(wi)}</b></td><td class="num"><small>{fmt_push(seen)}</small></td>
        </tr>''')
    if not body:
        body = ['<tr><td colspan="9" class="empty">No customer disk sample in this lookback</td></tr>']
    h = lambda label,key: _storage_sort_header(values,label,key)
    return f'''
    <style id="v48135-storage-one-disk-row">
      .storage-single-disk-row td{{padding-top:12px!important;padding-bottom:12px!important;vertical-align:middle}}
      .storage-disk-card{{border:1px solid #dbe3ef;border-radius:11px;padding:10px 11px;background:#fff;min-width:0}}
      .storage-disk-card-head{{display:flex;align-items:center;justify-content:space-between;gap:10px}}.storage-disk-card-head b{{font-size:14px}}.storage-disk-card-head span{{font-size:10px;font-weight:900;color:#475467}}
      .storage-disk-card-device{{margin-top:5px;font-size:10px;font-weight:800;color:#667085}}.storage-disk-card code{{display:block;margin-top:6px;font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#667085}}.storage-disk-card small{{display:block;margin-top:5px;color:#98a2b3;font-size:9px}}
      html[data-theme=dark] .storage-disk-card{{background:#0f1b2c;border-color:#31445e}}html[data-theme=dark] .storage-disk-card-head span,html[data-theme=dark] .storage-disk-card-device,html[data-theme=dark] .storage-disk-card code{{color:#9fb0c4}}
    </style>
    <div class="card storage-table-card"><div class="table-title-row"><div><h3>VM Disks</h3><div class="table-hint">One disk per row. vda, vdb and every customer disk remain individually visible and sortable.</div></div></div>
      <div class="table-wrap"><table class="storage-disk-detail-table"><thead><tr>
        <th>{h('NODE','node')}</th><th>{h('VM UUID','uuid')}</th><th><div>ONE VIRTUAL DISK</div><small>{h('DISK','disk')} · {h('STORAGE','mount')}</small></th>
        <th><div>ALLOCATED / ASSIGNED</div><small>{h('ALLOC','allocated')} · {h('ASSIGNED','assigned')} · {h('%','allocpct')}</small></th>
        <th>{h('READ','read')}</th><th>{h('WRITE','write')}</th><th>{h('R IOPS','readiops')}</th><th>{h('W IOPS','writeiops')}</th><th>{h('SEEN','seen')}</th>
      </tr></thead><tbody>{''.join(body)}</tbody></table></div>{_storage_pager(values,total)}</div>'''


_v48133_storage_disk_table = _v48135_storage_disk_table


def _v48135_storage_node_table(conn, values, start_ts):
    """Render only real filesystem roots and dedupe sandbox aliases."""
    where = [
        "s.last_seen>=?",
        "(ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))",
    ]
    params = [start_ts]
    if values.get("node"):
        where.append("s.node=?"); params.append(values["node"])
    if values.get("mount"):
        where.append("s.mount=?"); params.append(values["mount"])
    if values.get("q"):
        p = like_pattern(values["q"])
        where.append(f"(s.node LIKE ? OR s.mount LIKE ? OR s.device LIKE ? OR s.block LIKE ? OR s.raid_level LIKE ? OR s.fstype LIKE ? OR {_v48133_public_ip_sql('s')} LIKE ?)")
        params.extend([p] * 7)
    rows = conn.execute(f'''
      SELECT s.node,{_v48133_public_ip_sql('s')} AS public_ipv4,s.mount,s.device,s.block,s.raid_level,s.fstype,
             s.size,s.used,s.avail,s.use_percent,s.read_bps,s.write_bps,s.read_iops,s.write_iops,s.util_percent,s.last_seen,
             (SELECT COUNT(*) FROM vm_disk_current d WHERE d.node=s.node AND d.mount=s.mount AND d.role='customer') AS disk_count,
             (SELECT COUNT(DISTINCT d.vm_uuid) FROM vm_disk_current d WHERE d.node=s.node AND d.mount=s.mount AND d.role='customer') AS vm_count
      FROM node_storage_current s WHERE {' AND '.join(where)}
    ''', params).fetchall()
    # Remove old bind-alias rows immediately, before the next Agent push cleans
    # them from node_storage_current.
    chosen = {}
    for row in rows:
        node,ip,mount,device,*rest = row
        if str(mount or "").startswith(("/run","/sys","/proc","/dev")):
            continue
        if "[" in str(device or "") and str(device).endswith("]"):
            continue
        key = (str(node), _v48135_base_device(device) or ("mount:" + str(mount)))
        rank = _v48135_mount_rank(mount)
        old = chosen.get(key)
        if old is None or rank < old[0]:
            chosen[key] = (rank, row)
    rows = [v[1] for v in chosen.values()]
    metric = {
        "node":lambda r:str(r[0]).lower(), "mount":lambda r:str(r[2]).lower(), "size":lambda r:safe_float(r[7],0),
        "used":lambda r:safe_float(r[8],0), "usepct":lambda r:safe_float(r[10],0), "read":lambda r:safe_float(r[11],0),
        "write":lambda r:safe_float(r[12],0), "readiops":lambda r:safe_float(r[13],0), "writeiops":lambda r:safe_float(r[14],0),
        "util":lambda r:safe_float(r[15],0), "seen":lambda r:safe_float(r[16],0),
    }
    if values["sort"] not in metric:
        values["sort"] = "writeiops"
    rows.sort(key=metric[values["sort"]], reverse=values["order"]!="asc")
    total = len(rows)
    pages = max(1, int(math.ceil(total / float(values["limit"]))))
    values["page"] = min(values["page"], pages)
    rows = rows[(values["page"]-1)*values["limit"]:values["page"]*values["limit"]]
    body = []
    for node,public_ip,mount,device,block,raid,fs,size,used,avail,usep,rb,wb,ri,wi,util,seen,disk_count,vm_count in rows:
        filter_href = _storage_io_url(values, view="disks", node=node, mount=mount, sort="writeiops", order="desc", page=1)
        node_href = url_for("node_page", node=node, period=values["period"])
        ip = compact_ipv4(public_ip)
        ip_line = f'<span class="storage-node-ip">{escape(ip)}<button type="button" class="copy-btn" data-copy="{escape(ip)}" title="Copy IP">⧉</button></span>' if ip else ''
        body.append(f'''<tr><td class="storage-node-cell"><a href="{escape(node_href,quote=True)}"><b>{escape(node)}</b></a>{ip_line}</td>
          <td class="storage-backend"><a href="{escape(filter_href,quote=True)}"><b>{escape(mount or '-')}</b></a><span>{escape(_v48135_base_device(device) or '-')} · {escape(raid or 'hardware/unknown RAID')} · {escape(fs or '-')}</span></td>
          <td>{_disk_io_capacity(used,size,'used / size')}</td><td class="num">{_disk_io_rate(rb)}</td><td class="num"><b>{_disk_io_rate(wb)}</b></td><td class="num">{_disk_io_iops(ri)}</td><td class="num"><b>{_disk_io_iops(wi)}</b></td><td class="num"><b>{safe_float(util,0):.1f}%</b></td><td class="num"><b>{vm_count}</b><small class="storage-count-sub">{disk_count} disks</small></td><td class="num"><small>{fmt_push(seen)}</small></td></tr>''')
    if not body:
        body = ['<tr><td colspan="10" class="empty">No real node storage sample in this lookback</td></tr>']
    h = lambda label,key: _storage_sort_header(values,label,key)
    return f'''<div class="card storage-table-card"><div class="table-title-row"><div><h3>Storage Node</h3><div class="table-hint">Only real filesystem roots are shown. `/home` stays separate from `/` when it is a distinct LVM, RAID or block filesystem.</div></div></div>
      <div class="table-wrap"><table class="storage-node-table"><thead><tr><th>{h('NODE','node')}</th><th>{h('MOUNT / DEVICE','mount')}</th><th><div>USED / SIZE</div><small>{h('USED','used')} · {h('SIZE','size')} · {h('%','usepct')}</small></th><th>{h('READ','read')}</th><th>{h('WRITE','write')}</th><th>{h('R IOPS','readiops')}</th><th>{h('W IOPS','writeiops')}</th><th>{h('UTIL','util')}</th><th>VM / DISKS</th><th>{h('SEEN','seen')}</th></tr></thead><tbody>{''.join(body)}</tbody></table></div>{_storage_pager(values,total)}</div>'''


_v48133_storage_node_table = _v48135_storage_node_table

# ---------------------------------------------------------------------------
# v48.13.6 grouped Storage I/O, working Top VM disk sort and /home visibility
# ---------------------------------------------------------------------------

V48136_VERSION = "48.13.6"
V48136_BUILD = "r1"


# The previous Top VM renderer already generated the three links, but the
# request sanitizer discarded their keys and silently fell back to TOTAL.
_clean_top_sort_v48136_base = clean_top_sort


def clean_top_sort(sort_by):
    value = str(sort_by or "").strip().lower()
    if value in V48133_DISK_SORT_KEYS:
        return value
    return _clean_top_sort_v48136_base(value)


V48136_STORAGE_CSS = r'''
<style id="v48136-storage-grouped-ui">
.storage-view-mode{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:8px}.storage-view-mode span{font-size:10px;color:#667085}.storage-view-mode b{font-size:10px;color:#344054}
.storage-group-table{width:100%;min-width:1650px;table-layout:fixed}.storage-group-table th:nth-child(1){width:205px}.storage-group-table th:nth-child(2){width:295px}.storage-group-table th:nth-child(3){width:640px}.storage-group-table th:nth-child(4){width:240px}.storage-group-table th:nth-child(n+5){width:105px}.storage-group-table td{vertical-align:middle}.storage-group-table td.num{text-align:right;white-space:nowrap}
.storage-vm-group-row>td,.storage-node-group-row>td{padding-top:15px!important;padding-bottom:15px!important}.storage-vm-group-row+tr td,.storage-node-group-row+tr td{border-top:2px solid #dbe3ef!important}
.storage-group-id>a{display:block}.storage-group-id .storage-node-ip{display:flex;align-items:center;gap:4px}.storage-group-uuid .uuid-cell{display:flex;align-items:center;gap:7px}.storage-group-uuid .uuid-cell>a{display:block;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.storage-group-uuid small{display:block;margin-top:7px;color:#667085}
.storage-child-stack{display:grid;gap:9px}.storage-child-item{display:grid;grid-template-columns:minmax(190px,1.25fr) minmax(190px,1fr) minmax(250px,1.35fr);gap:12px;align-items:center;border:1px solid #dbe3ef;border-radius:12px;padding:10px 12px;background:#fff;box-shadow:0 1px 2px rgba(16,24,40,.035)}
.storage-child-main{min-width:0}.storage-child-title{display:flex;align-items:center;gap:8px}.storage-child-title b{font-size:14px}.storage-child-title span{font-size:10px;font-weight:900;color:#475467;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.storage-child-main code{display:block;margin-top:6px;font-size:9px;color:#667085;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.storage-child-main small{display:block;margin-top:5px;font-size:9px;color:#98a2b3}.storage-child-cap .disk-capacity{min-width:0}.storage-child-metrics{display:grid;grid-template-columns:repeat(4,minmax(54px,1fr));gap:7px}.storage-child-metric{min-width:0;border-left:1px solid #eaecf0;padding-left:8px}.storage-child-metric span{display:block;font-size:8px;font-weight:900;color:#667085}.storage-child-metric b{display:block;margin-top:3px;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.storage-child-footer{grid-column:1/-1;display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding-top:7px;border-top:1px dashed #eaecf0;font-size:9px;color:#667085}.storage-child-footer a{font-weight:900}.storage-filtered-banner{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px;padding:9px 12px;border:1px solid #b2ddff;background:#eff8ff;border-radius:10px;font-size:10px;color:#175cd3}.storage-filtered-banner b{font-size:11px}.storage-filtered-banner a{font-weight:900}
.storage-node-child-item{grid-template-columns:minmax(220px,1.15fr) minmax(210px,1fr) minmax(290px,1.45fr)}.storage-node-child-main a{font-size:14px;font-weight:950}.storage-node-child-main span{display:block;margin-top:5px;font-size:9px;color:#667085;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.storage-node-child-main small{display:block;margin-top:5px;font-size:9px;color:#98a2b3}.storage-node-child-metrics{grid-template-columns:repeat(5,minmax(52px,1fr))}.storage-total-inline small{display:block;margin-top:4px;color:#667085;font-size:8px}
html[data-theme=dark] .storage-vm-group-row+tr td,html[data-theme=dark] .storage-node-group-row+tr td{border-top-color:#31445e!important}html[data-theme=dark] .storage-child-item{background:#0f1b2c;border-color:#31445e}html[data-theme=dark] .storage-child-title span,html[data-theme=dark] .storage-child-main code,html[data-theme=dark] .storage-child-main small,html[data-theme=dark] .storage-child-footer,html[data-theme=dark] .storage-node-child-main span,html[data-theme=dark] .storage-node-child-main small,html[data-theme=dark] .storage-group-uuid small,html[data-theme=dark] .storage-view-mode span,html[data-theme=dark] .storage-total-inline small{color:#9fb0c4}html[data-theme=dark] .storage-child-metric{border-left-color:#31445e}html[data-theme=dark] .storage-child-footer{border-top-color:#31445e}html[data-theme=dark] .storage-filtered-banner{background:#102a43;border-color:#175cd3;color:#b2ddff}
@media(max-width:1250px){.storage-child-item,.storage-node-child-item{grid-template-columns:1fr 1fr}.storage-child-metrics,.storage-node-child-metrics{grid-column:1/-1}.storage-group-table{min-width:1420px}}
</style>
'''


def _v48136_disk_child_html(node, vm_uuid, disk_row, period):
    (
        target, source, mount, device, block, fstype,
        assigned, allocated, read_bps, write_bps,
        read_iops, write_iops, last_seen,
    ) = disk_row
    dev = device or (("/dev/" + block) if block else "-")
    filter_href = _storage_io_url(
        _storage_io_params(), view="disks", node=node, mount=mount or "",
        q=vm_uuid, period=period, sort="writeiops", order="desc", page=1,
    )
    return f'''
      <div class="storage-child-item">
        <div class="storage-child-main">
          <div class="storage-child-title"><b>{escape(target or '-')}</b><span>{escape(mount or '-')} · {escape(dev)}</span></div>
          <code title="{escape(source or '-',quote=True)}">{escape(source or '-')}</code>
          <small>{escape(fstype or '-')} · sample {fmt_push(last_seen)}</small>
        </div>
        <div class="storage-child-cap">{_disk_io_capacity(allocated,assigned)}</div>
        <div class="storage-child-metrics">
          <div class="storage-child-metric"><span>READ</span><b>{_disk_io_rate(read_bps)}</b></div>
          <div class="storage-child-metric"><span>WRITE</span><b>{_disk_io_rate(write_bps)}</b></div>
          <div class="storage-child-metric"><span>R IOPS</span><b>{_disk_io_iops(read_iops)}</b></div>
          <div class="storage-child-metric"><span>W IOPS</span><b>{_disk_io_iops(write_iops)}</b></div>
        </div>
        <div class="storage-child-footer"><span>Storage <b>{escape(mount or '-')}</b></span><span>Device <b>{escape(dev)}</b></span><a href="{escape(filter_href,quote=True)}">Open this storage</a></div>
      </div>'''


def _v48136_storage_disk_group_table(conn, values, start_ts):
    groups, details, total = _v48133_storage_disk_groups(conn, values, start_ts)
    body = []
    for node, vm_uuid, public_ip, disk_count, assigned, allocated, rb, wb, ri, wi, seen in groups:
        ip = compact_ipv4(public_ip)
        node_href = url_for("node_page", node=node, period=values["period"], q=vm_uuid)
        vm_href = url_for("vm_page", node=node, vm_uuid=vm_uuid, period=values["period"])
        ip_line = f'<span class="storage-node-ip">{escape(ip)}<button type="button" class="copy-btn" data-copy="{escape(ip)}" title="Copy IP">⧉</button></span>' if ip else ''
        children = ''.join(
            _v48136_disk_child_html(node, vm_uuid, row, values["period"])
            for row in details.get((str(node), str(vm_uuid)), [])
        )
        body.append(f'''
        <tr class="storage-vm-group-row">
          <td class="storage-group-id storage-node-cell"><a href="{escape(node_href,quote=True)}"><b>{escape(node)}</b></a>{ip_line}</td>
          <td class="storage-group-uuid"><span class="uuid-cell"><a href="{escape(vm_href,quote=True)}" title="{escape(vm_uuid,quote=True)}"><b class="mono">{escape(vm_uuid)}</b></a><button type="button" class="copy-btn" data-copy="{escape(vm_uuid)}" title="Copy UUID">⧉</button></span><small>{safe_int(disk_count,0)} customer disk{'s' if safe_int(disk_count,0)!=1 else ''}</small></td>
          <td><div class="storage-child-stack">{children}</div></td>
          <td>{_disk_io_capacity(allocated,assigned,'total allocated / assigned')}</td>
          <td class="num">{_disk_io_rate(rb)}</td><td class="num"><b>{_disk_io_rate(wb)}</b></td>
          <td class="num">{_disk_io_iops(ri)}</td><td class="num"><b>{_disk_io_iops(wi)}</b></td><td class="num"><small>{fmt_push(seen)}</small></td>
        </tr>''')
    if not body:
        body = ['<tr><td colspan="9" class="empty">No customer disk sample in this lookback</td></tr>']
    h = lambda label,key: _storage_sort_header(values,label,key)
    return f'''
    {V48136_STORAGE_CSS}
    <div class="card storage-table-card">
      <div class="table-title-row"><div><h3>VM Disks</h3><div class="table-hint">All view groups every customer disk under its VM UUID. Select a storage mount to switch to one-disk-per-row troubleshooting.</div><div class="storage-view-mode"><b>VIEW: GROUPED BY UUID</b><span>One VM row, all vda/vdb/vdc inside</span></div></div></div>
      <div class="table-wrap"><table class="storage-group-table storage-vm-group-table"><thead><tr>
        <th>{h('NODE','node')}</th><th>{h('VM UUID','uuid')}</th><th><div>VIRTUAL DISKS</div><small>{h('COUNT','diskcount')}</small></th>
        <th><div>TOTAL ALLOCATED / ASSIGNED</div><small>{h('ALLOC','allocated')} · {h('ASSIGNED','assigned')} · {h('%','allocpct')}</small></th>
        <th>{h('READ','read')}</th><th>{h('WRITE','write')}</th><th>{h('R IOPS','readiops')}</th><th>{h('W IOPS','writeiops')}</th><th>{h('SEEN','seen')}</th>
      </tr></thead><tbody>{''.join(body)}</tbody></table></div>{_storage_pager(values,total)}
    </div>'''


_v48136_storage_disk_filtered_base = _v48133_storage_disk_table




def _v48136_real_storage_rows(conn, values, start_ts):
    where = ["s.last_seen>=?"]
    params = [start_ts]
    if values.get("node"):
        where.append("s.node=?")
        params.append(values["node"])
    if values.get("mount"):
        where.append("s.mount=?")
        params.append(values["mount"])
    if values.get("q"):
        p = like_pattern(values["q"])
        where.append(f"(s.node LIKE ? OR s.mount LIKE ? OR s.device LIKE ? OR s.block LIKE ? OR s.raid_level LIKE ? OR s.fstype LIKE ? OR {_v48133_public_ip_sql('s')} LIKE ?)")
        params.extend([p] * 7)
    rows = conn.execute(f'''
      SELECT s.node,{_v48133_public_ip_sql('s')} AS public_ipv4,s.mount,s.device,s.block,s.raid_level,s.fstype,
             s.size,s.used,s.avail,s.use_percent,s.read_bps,s.write_bps,s.read_iops,s.write_iops,s.util_percent,s.last_seen,
             (SELECT COUNT(*) FROM vm_disk_current d WHERE d.node=s.node AND d.mount=s.mount AND d.role='customer') AS disk_count,
             (SELECT COUNT(DISTINCT d.vm_uuid) FROM vm_disk_current d WHERE d.node=s.node AND d.mount=s.mount AND d.role='customer') AS vm_count
      FROM node_storage_current s WHERE {' AND '.join(where)}
    ''', params).fetchall()
    chosen = {}
    for row in rows:
        node, _ip, mount, device, *_ = row
        mount = str(mount or "").rstrip("/") or "/"
        device = str(device or "")
        if mount.startswith(("/run", "/sys", "/proc", "/dev")):
            continue
        if "[" in device and device.endswith("]"):
            continue
        key = (str(node), _v48135_base_device(device) or ("mount:" + mount))
        rank = _v48135_mount_rank(mount)
        old = chosen.get(key)
        if old is None or rank < old[0]:
            chosen[key] = (rank, row)
    return [item[1] for item in chosen.values()]


def _v48136_node_mount_child(values, row):
    node, _public_ip, mount, device, block, raid, fs, size, used, avail, usep, rb, wb, ri, wi, util, seen, disk_count, vm_count = row
    dev = _v48135_base_device(device) or (("/dev/" + block) if block else "-")
    filter_href = _storage_io_url(values, view="disks", node=node, mount=mount or "", q="", sort="writeiops", order="desc", page=1)
    return f'''
      <div class="storage-child-item storage-node-child-item">
        <div class="storage-node-child-main"><a href="{escape(filter_href,quote=True)}">{escape(mount or '-')}</a><span>{escape(dev)} · {escape(raid or 'hardware/unknown RAID')} · {escape(fs or '-')}</span><small>{safe_int(vm_count,0)} VMs · {safe_int(disk_count,0)} disks · seen {fmt_push(seen)}</small></div>
        <div class="storage-child-cap">{_disk_io_capacity(used,size,'used / size')}</div>
        <div class="storage-child-metrics storage-node-child-metrics">
          <div class="storage-child-metric"><span>READ</span><b>{_disk_io_rate(rb)}</b></div>
          <div class="storage-child-metric"><span>WRITE</span><b>{_disk_io_rate(wb)}</b></div>
          <div class="storage-child-metric"><span>R IOPS</span><b>{_disk_io_iops(ri)}</b></div>
          <div class="storage-child-metric"><span>W IOPS</span><b>{_disk_io_iops(wi)}</b></div>
          <div class="storage-child-metric"><span>UTIL</span><b>{safe_float(util,0):.1f}%</b></div>
        </div>
      </div>'''


def _v48136_storage_node_group_table(conn, values, start_ts):
    rows = _v48136_real_storage_rows(conn, values, start_ts)
    grouped = {}
    for row in rows:
        grouped.setdefault(str(row[0]), []).append(row)
    groups = []
    for node, mounts in grouped.items():
        mounts.sort(key=lambda r: _v48135_mount_rank(r[2]))
        ip = next((compact_ipv4(r[1]) for r in mounts if compact_ipv4(r[1])), "")
        size = sum(max(0, safe_int(r[7], 0)) for r in mounts)
        used = sum(max(0, safe_int(r[8], 0)) for r in mounts)
        rb = sum(max(0.0, safe_float(r[11], 0)) for r in mounts)
        wb = sum(max(0.0, safe_float(r[12], 0)) for r in mounts)
        ri = sum(max(0.0, safe_float(r[13], 0)) for r in mounts)
        wi = sum(max(0.0, safe_float(r[14], 0)) for r in mounts)
        util = max([max(0.0, safe_float(r[15], 0)) for r in mounts] or [0.0])
        seen = max([safe_int(r[16], 0) for r in mounts] or [0])
        disk_count = sum(max(0, safe_int(r[17], 0)) for r in mounts)
        vm_count = len({str(d[0]) + "\x1f" + str(d[1]) for d in conn.execute("SELECT DISTINCT node,vm_uuid FROM vm_disk_current WHERE node=? AND role='customer'", (node,)).fetchall()})
        groups.append((node, ip, mounts, size, used, rb, wb, ri, wi, util, seen, disk_count, vm_count))
    metric = {
        "node": lambda g: g[0].lower(), "mount": lambda g: str(g[2][0][2] if g[2] else "").lower(),
        "size": lambda g: g[3], "used": lambda g: g[4], "usepct": lambda g: (g[4] / g[3]) if g[3] else 0,
        "read": lambda g: g[5], "write": lambda g: g[6], "readiops": lambda g: g[7],
        "writeiops": lambda g: g[8], "util": lambda g: g[9], "seen": lambda g: g[10],
    }
    if values["sort"] not in metric:
        values["sort"] = "writeiops"
    groups.sort(key=metric[values["sort"]], reverse=values["order"] != "asc")
    total = len(groups)
    pages = max(1, int(math.ceil(total / float(values["limit"]))))
    values["page"] = min(values["page"], pages)
    groups = groups[(values["page"]-1)*values["limit"]:values["page"]*values["limit"]]
    body = []
    for node, ip, mounts, size, used, rb, wb, ri, wi, util, seen, disk_count, vm_count in groups:
        node_href = url_for("node_page", node=node, period=values["period"])
        ip_line = f'<span class="storage-node-ip">{escape(ip)}<button type="button" class="copy-btn" data-copy="{escape(ip)}" title="Copy IP">⧉</button></span>' if ip else ''
        children = ''.join(_v48136_node_mount_child(values, row) for row in mounts)
        body.append(f'''
        <tr class="storage-node-group-row">
          <td class="storage-group-id storage-node-cell"><a href="{escape(node_href,quote=True)}"><b>{escape(node)}</b></a>{ip_line}<small class="storage-count-sub">{len(mounts)} filesystems</small></td>
          <td><div class="storage-child-stack">{children}</div></td>
          <td>{_disk_io_capacity(used,size,'total used / size')}</td>
          <td class="num">{_disk_io_rate(rb)}</td><td class="num"><b>{_disk_io_rate(wb)}</b></td><td class="num">{_disk_io_iops(ri)}</td><td class="num"><b>{_disk_io_iops(wi)}</b></td><td class="num"><b>{util:.1f}%</b></td><td class="num storage-total-inline"><b>{vm_count}</b><small>{disk_count} disks</small></td><td class="num"><small>{fmt_push(seen)}</small></td>
        </tr>''')
    if not body:
        body = ['<tr><td colspan="10" class="empty">No real node storage sample in this lookback</td></tr>']
    h = lambda label,key: _storage_sort_header(values,label,key)
    return f'''
    {V48136_STORAGE_CSS}
    <div class="card storage-table-card">
      <div class="table-title-row"><div><h3>Storage Node</h3><div class="table-hint">All view groups every real filesystem under its node. A separate LVM or RAID-backed /home remains a separate child storage.</div><div class="storage-view-mode"><b>VIEW: GROUPED BY NODE</b><span>One node row, all /, /home, /home2 and /home3 inside</span></div></div></div>
      <div class="table-wrap"><table class="storage-group-table storage-node-group-table"><thead><tr>
        <th>{h('NODE','node')}</th><th><div>FILESYSTEMS / STORAGE</div><small>{h('MOUNT','mount')}</small></th><th><div>TOTAL USED / SIZE</div><small>{h('USED','used')} · {h('SIZE','size')} · {h('%','usepct')}</small></th>
        <th>{h('READ','read')}</th><th>{h('WRITE','write')}</th><th>{h('R IOPS','readiops')}</th><th>{h('W IOPS','writeiops')}</th><th>{h('HOT UTIL','util')}</th><th>VM / DISKS</th><th>{h('SEEN','seen')}</th>
      </tr></thead><tbody>{''.join(body)}</tbody></table></div>{_storage_pager(values,total)}
    </div>'''


_v48136_storage_node_filtered_base = _v48133_storage_node_table



# ---------------------------------------------------------------------------
