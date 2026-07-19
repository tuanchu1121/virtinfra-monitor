# v48.13.3 storage integration and exact UUID purge
# ---------------------------------------------------------------------------

V48133_VERSION = "48.13.3"
V48133_DISK_SORT_KEYS = {"diskallocated", "diskassigned", "diskallocpct", "diskcount"}


def _v48133_disk_totals_for_pairs(pairs):
    clean = []
    seen = set()
    for node, vm_uuid in pairs or []:
        key = (str(node or ""), str(vm_uuid or ""))
        if key[0] and key[1] and key not in seen:
            seen.add(key)
            clean.append(key)
    if not clean:
        return {}
    conn = db()
    try:
        ensure_disk_io_schema(conn)
        keys = [node + "\x1f" + vm_uuid for node, vm_uuid in clean]
        placeholders = ",".join("?" for _ in keys)
        rows = conn.execute(f"""
            SELECT node,vm_uuid,
                   COALESCE(SUM(allocation_bytes),0),
                   COALESCE(SUM(capacity_bytes),0),
                   COUNT(*)
            FROM vm_disk_current
            WHERE role='customer'
              AND (node || char(31) || vm_uuid) IN ({placeholders})
            GROUP BY node,vm_uuid
        """, keys).fetchall()
        return {
            (str(r[0]), str(r[1])): (
                max(0, safe_int(r[2], 0)),
                max(0, safe_int(r[3], 0)),
                max(0, safe_int(r[4], 0)),
            )
            for r in rows
        }
    finally:
        conn.close()


_get_top_vm_rows_v48133_base = get_top_vm_rows


def get_top_vm_rows(period, q="", sort_by="total", order="desc", scope="all", limit=100):
    requested_sort = str(sort_by or "total").strip().lower()
    requested_order = clean_sort_order(order)
    requested_limit = max(10, min(1000, safe_int(limit, 100)))
    disk_sort = requested_sort in V48133_DISK_SORT_KEYS
    base_sort = "total" if disk_sort else requested_sort
    fetch_limit = 1000 if disk_sort else requested_limit
    rows, selected_bucket, latest_bucket, _ = _get_top_vm_rows_v48133_base(
        period, q=q, sort_by=base_sort, order=requested_order,
        scope=scope, limit=fetch_limit,
    )
    totals = _v48133_disk_totals_for_pairs([(r[0], r[1]) for r in rows])
    augmented = [tuple(r) + totals.get((str(r[0]), str(r[1])), (0, 0, 0)) for r in rows]
    if disk_sort:
        def metric(row):
            allocated = max(0.0, safe_float(row[35], 0.0))
            assigned = max(0.0, safe_float(row[36], 0.0))
            count = max(0.0, safe_float(row[37], 0.0))
            if requested_sort == "diskallocated":
                return allocated
            if requested_sort == "diskassigned":
                return assigned
            if requested_sort == "diskallocpct":
                return allocated / assigned if assigned > 0 else -1.0
            return count

        def sort_key(row):
            has_value = safe_int(row[37], 0) > 0 or safe_int(row[36], 0) > 0 or safe_int(row[35], 0) > 0
            value = metric(row)
            tie = safe_float(row[7], 0.0)
            if requested_order == "asc":
                return (0 if has_value else 1, value, tie)
            return (0 if has_value else 1, -value, -tie)

        augmented.sort(key=sort_key)
    return augmented[:requested_limit], selected_bucket, latest_bucket, requested_limit


def _v48133_disk_sort_link(label, key, period, q, current_sort, current_order, scope, limit):
    active = current_sort == key
    next_order = "asc" if active and clean_sort_order(current_order) == "desc" else "desc"
    arrow = " ↓" if active and clean_sort_order(current_order) == "desc" else (" ↑" if active else "")
    params = {
        "period": period,
        "q": q,
        "sort": key,
        "order": next_order,
        "scope": scope,
        "limit": limit,
    }
    at = (request.args.get("at") or "").strip()
    if at:
        params["at"] = at
    return f'<a class="sort-link disk-cap-sort-link" href="{escape(url_for("top_page", **params), quote=True)}">{escape(label)}{arrow}</a>'


def _v48133_top_disk_capacity(allocated, assigned, count):
    allocated = max(0, safe_int(allocated, 0))
    assigned = max(0, safe_int(assigned, 0))
    count = max(0, safe_int(count, 0))
    if count <= 0 and allocated <= 0 and assigned <= 0:
        return '<div class="top-disk-capacity top-disk-na"><b>N/A</b><small>No customer disk data</small></div>'
    pct = allocated * 100.0 / assigned if assigned > 0 else 0.0
    level = ""
    if pct >= 90:
        level = " disk-cap-critical"
    elif pct >= 75:
        level = " disk-cap-hot"
    elif pct >= 50:
        level = " disk-cap-warm"
    return (
        f'<div class="top-disk-capacity{level}">'
        f'<b>{_disk_io_bytes(allocated)} <span>/ {_disk_io_bytes(assigned)}</span></b>'
        f'<div class="disk-cap-meter"><i style="width:{min(100.0, max(0.0, pct)):.1f}%"></i></div>'
        f'<small>{pct:.1f}% · {count} slot{"s" if count != 1 else ""}</small>'
        f'</div>'
    )


V48133_TOP_CSS = r'''
<style id="v48134-top-disk-capacity">
body.app-v490.endpoint-top-page .table-top-vm{min-width:2185px!important;table-layout:fixed!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-rank{width:30px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-node{width:135px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-uuid{width:290px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-ifaces{width:48px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-public,body.app-v490.endpoint-top-page .table-top-vm col.top-private{width:78px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-total{width:88px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-mbps{width:72px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-peakmbps{width:76px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-pps{width:78px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-peakpps{width:82px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-sample{width:96px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-cpu{width:112px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-vcpu{width:44px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-ram{width:168px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-diskcap{width:190px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-diskr,body.app-v490.endpoint-top-page .table-top-vm col.top-diskw{width:86px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-push{width:58px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-drops{width:46px!important}
body.app-v490.endpoint-top-page .table-top-vm col.top-errors{width:42px!important}
body.app-v490.endpoint-top-page .table-top-vm th,body.app-v490.endpoint-top-page .table-top-vm td{padding-left:8px!important;padding-right:8px!important}
body.app-v490.endpoint-top-page .table-top-vm .rank-cell{font-size:10px!important;padding-left:3px!important;padding-right:3px!important}
body.app-v490.endpoint-top-page .table-top-vm .uuid-cell>a{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.disk-cap-compact-head{display:grid;gap:4px;justify-items:center}.disk-cap-compact-head>div{font-weight:950;white-space:nowrap;font-size:10px}.disk-cap-compact-head small{display:flex;gap:3px;align-items:center;justify-content:center;white-space:nowrap}.disk-cap-sort-link{font-size:8.5px!important;padding:1px!important}
.top-disk-capacity{min-width:0;text-align:left}.top-disk-capacity>b{display:block;font-size:11px;line-height:1.15;white-space:nowrap}.top-disk-capacity>b span{font-size:9px;color:#667085}.top-disk-capacity .disk-cap-meter{height:5px;margin-top:6px}.top-disk-capacity small{display:block;margin-top:4px;font-size:8px;color:#667085;white-space:nowrap}.top-disk-na{text-align:center}.top-disk-na b{color:#98a2b3}
html[data-theme=dark] .top-disk-capacity>b span,html[data-theme=dark] .top-disk-capacity small{color:#9fb0c4}
</style>
'''


def top_vm_table(rows, period, q, sort_by, order, scope, limit):
    body = ""
    for rank, row in enumerate(rows, 1):
        (
            node, vm_uuid, iface_count, public_total, private_total, rx, tx, total,
            packets, drops, errors, avg_mbps, peak_mbps, avg_pps, peak_pps,
            sample_count, sample_expected, sample_max_gap, seconds_over_pps, seconds_over_mbps,
            sample_quality_rank, cpu_full_percent, vcpu_current, cpu_core_percent,
            ram_rss_kib, ram_current_kib, disk_read_bps, disk_write_bps,
            last_push, interval_seconds, public_ipv4, private_ipv4,
            ram_available_kib, ram_unused_kib, ram_usable_kib,
            disk_allocated_bytes, disk_assigned_bytes, disk_count,
        ) = row
        row_at = (request.args.get("at") or "").strip()
        node_href = url_for("node_page", node=node, period=period, q=vm_uuid, **({"at": row_at} if row_at else {}))
        vm_href = url_for("vm_page", node=node, vm_uuid=vm_uuid, period=period, **({"at": row_at} if row_at else {}))
        public_ip = compact_ipv4(public_ipv4)
        ip_lines = f'<small class="node-ipv4" title="Public IPv4">{escape(public_ip)}</small>' if public_ip else ""
        sample = network_sample_badge(network_quality_from_rank(sample_quality_rank), sample_count, sample_expected, sample_max_gap)
        core_value = max(0.0, safe_float(cpu_core_percent, 0.0))
        full_value = max(0.0, safe_float(cpu_full_percent, 0.0))
        cpu_level = _v48102_cpu_level(full_value)
        cpu_bar = min(100.0, full_value)
        ram_html = fmt_vm_ram_block(ram_current_kib, ram_rss_kib, ram_available_kib, ram_unused_kib, ram_usable_kib, compact=True)
        disk_cap_html = _v48133_top_disk_capacity(disk_allocated_bytes, disk_assigned_bytes, disk_count)
        body += f"""
        <tr>
          <td class="num rank-cell">{rank}</td>
          <td class="mono"><div class="node-name-cell"><a href="{escape(node_href,quote=True)}"><b>{escape(node)}</b></a>{ip_lines}</div></td>
          <td class="mono"><span class="uuid-cell"><a href="{escape(vm_href,quote=True)}" title="{escape(vm_uuid)}">{escape(vm_uuid)}</a><button type="button" class="copy-btn" data-copy="{escape(vm_uuid)}" title="Copy UUID">⧉</button></span></td>
          <td class="num">{iface_count or 0}</td><td class="num">{human(public_total)}</td><td class="num">{human(private_total)}</td><td class="num"><b>{human(total)}</b></td>
          <td class="num">{float(avg_mbps or 0):.2f}</td><td class="num"><b>{float(peak_mbps or 0):.2f}</b></td><td class="num">{fmt_pps_value(avg_pps)}</td><td class="num"><b>{fmt_pps_value(peak_pps)}</b></td><td class="num sample-cell">{sample}</td>
          <td class="num cpu-dual-cell cpu-{cpu_level}"><b class="cpu-core-value">{core_value:.1f}%</b><small class="cpu-full-value">{full_value:.1f}% FULL</small><span class="cpu-meter"><i style="width:{cpu_bar:.1f}%"></i></span></td>
          <td class="num">{int(vcpu_current or 0)}</td><td class="num ram-cell">{ram_html}</td><td class="disk-cap-cell">{disk_cap_html}</td><td class="num">{human_rate(disk_read_bps)}</td><td class="num">{human_rate(disk_write_bps)}</td><td class="num">{fmt_push(last_push)}</td><td class="num">{int(drops or 0)}</td><td class="num">{int(errors or 0)}</td>
        </tr>"""
    if not body:
        body = '<tr><td colspan="21" class="empty">No VM data at this selected snapshot</td></tr>'
    h = lambda label, key: top_sort_header(label, key, period, q, sort_by, order, scope, limit)
    cpu_core_sort = _v48102_top_sort_link("CORE%", "cpu", period, q, sort_by, order, scope, limit)
    cpu_full_sort = _v48102_top_sort_link("FULL%", "cpufull", period, q, sort_by, order, scope, limit)
    ram_header = _v48104_ram_sort_header(
        _v48103_top_ram_link("RAM", "ram", period, q, sort_by, order, scope, limit),
        [
            _v48103_top_ram_link("Guest %", "ram", period, q, sort_by, order, scope, limit),
            _v48103_top_ram_link("Used GiB", "ramused", period, q, sort_by, order, scope, limit),
            _v48103_top_ram_link("Host RSS", "ramrss", period, q, sort_by, order, scope, limit),
            _v48103_top_ram_link("Assigned", "ramassigned", period, q, sort_by, order, scope, limit),
        ], sort_by, order,
    )
    disk_header = (
        '<div class="disk-cap-compact-head"><div>ALLOCATED / ASSIGNED</div><small>'
        + _v48133_disk_sort_link("ALLOC", "diskallocated", period, q, sort_by, order, scope, limit)
        + '<span> · </span>'
        + _v48133_disk_sort_link("ASSIGNED", "diskassigned", period, q, sort_by, order, scope, limit)
        + '<span> · </span>'
        + _v48133_disk_sort_link("%", "diskallocpct", period, q, sort_by, order, scope, limit)
        + '<span> · </span>'
        + _v48133_disk_sort_link("SLOTS", "diskcount", period, q, sort_by, order, scope, limit)
        + '</small></div>'
    )
    return V48133_TOP_CSS + f"""
    <div class="card vm-table-card top-vm-v48102 top-vm-v48103 top-vm-v48133">
      <div class="table-title-row"><h3>Top VM Across All Nodes</h3><div class="count-badges"><span>Rows <b>{len(rows)}</b></span><span>Scope <b>{escape(scope)}</b></span><span>Refresh <b>5s partial</b></span><span>Sort <b>{escape(sort_by)} {escape(order)}</b></span></div></div>
      <div class="table-wrap"><table class="table-top-vm"><colgroup><col class="top-rank"><col class="top-node"><col class="top-uuid"><col class="top-ifaces"><col class="top-public"><col class="top-private"><col class="top-total"><col class="top-mbps"><col class="top-peakmbps"><col class="top-pps"><col class="top-peakpps"><col class="top-sample"><col class="top-cpu"><col class="top-vcpu"><col class="top-ram"><col class="top-diskcap"><col class="top-diskr"><col class="top-diskw"><col class="top-push"><col class="top-drops"><col class="top-errors"></colgroup>
      <thead><tr><th>#</th><th>{h('NODE','node')}</th><th>{h('VM UUID','vm')}</th><th>IFACES</th><th class="num-head">{h('PUBLIC','public')}</th><th class="num-head">{h('PRIVATE','private')}</th><th class="num-head">{h('TOTAL','total')}</th><th class="num-head">{h('AVG Mbps','mbps')}</th><th class="num-head">{h('PEAK Mbps','peakmbps')}</th><th class="num-head">{h('AVG PPS','pps')}</th><th class="num-head">{h('PEAK PPS','peakpps')}</th><th class="num-head">{h('SAMPLE','sample')}</th><th class="num-head cpu-dual-head"><div>CPU</div><small>{cpu_core_sort}<span> · </span>{cpu_full_sort}</small></th><th class="num-head">{h('vCPU','vcpu')}</th><th class="num-head ram-compact-sort-head">{ram_header}</th><th class="num-head disk-capacity-sort-head">{disk_header}</th><th class="num-head">{h('DISK R/s','diskr')}</th><th class="num-head">{h('DISK W/s','diskw')}</th><th class="num-head">{h('PUSH','last_push')}</th><th class="num-head">{h('DROPS','drops')}</th><th class="num-head">{h('ERR','errors')}</th></tr></thead><tbody>{body}</tbody></table></div>
      <div class="table-hint">RAM shows <b>Guest Used / Assigned</b>. Disk capacity shows total <b>Host Allocated / Assigned</b> across customer disks. Click the UUID to open per-disk capacity and I/O details.</div>
    </div>"""


def _v48133_vm_disks(node, vm_uuid):
    """Return per-disk capacity and I/O for the selected VM snapshot."""
    period = clean_period(request.args.get("period", "5m"))
    conn = db()
    try:
        payload, selected_bucket, latest_bucket = _v5054_selected_storage_payload(conn, node, period)
        if payload:
            seen = safe_int(payload.get("t"), selected_bucket)
            rows = []
            for item in payload.get("d") or []:
                if not isinstance(item, (list, tuple)) or len(item) < 14:
                    continue
                (
                    payload_vm_uuid, target, source, mount, storage_device,
                    storage_block, storage_fstype, capacity_bytes,
                    allocation_bytes, physical_bytes, read_bps, write_bps,
                    read_iops, write_iops,
                ) = item[:14]
                if str(payload_vm_uuid or "") != vm_uuid:
                    continue
                rows.append((
                    str(target or ""), str(source or ""), str(mount or ""),
                    str(storage_device or ""), str(storage_block or ""),
                    str(storage_fstype or ""),
                    max(0, safe_int(capacity_bytes, 0)),
                    max(0, safe_int(allocation_bytes, 0)),
                    max(0, safe_int(physical_bytes, 0)),
                    max(0.0, safe_float(read_bps, 0.0)),
                    max(0.0, safe_float(write_bps, 0.0)),
                    max(0.0, safe_float(read_iops, 0.0)),
                    max(0.0, safe_float(write_iops, 0.0)),
                    seen,
                ))
            rows.sort(key=lambda r: (0 if r[0] == "vda" else 1 if r[0] == "vdb" else 2, r[0].lower(), r[1].lower()))
            return rows

        # Do not present current disk rates as historical data. Current-table
        # fallback is permitted only for the newest 5-minute page.
        live_request = _request_target_ts() is None and period == "5m" and selected_bucket == latest_bucket
        if not live_request or not table_columns(conn, "vm_disk_current"):
            return []
        return conn.execute("""
            SELECT target,source,mount,storage_device,storage_block,storage_fstype,
                   capacity_bytes,allocation_bytes,physical_bytes,
                   read_bps,write_bps,read_iops,write_iops,last_seen
            FROM vm_disk_current
            WHERE node=? AND vm_uuid=? AND role='customer'
            ORDER BY CASE target WHEN 'vda' THEN 0 WHEN 'vdb' THEN 1 ELSE 2 END,
                     target COLLATE NOCASE, source COLLATE NOCASE
        """, (node, vm_uuid)).fetchall()
    finally:
        conn.close()



def _v48133_disk_level(pct):
    if pct >= 90:
        return "critical"
    if pct >= 75:
        return "hot"
    if pct >= 50:
        return "warm"
    return "ok"


def _v48133_vm_disk_overview_cards(rows):
    """One compact Overview card per customer disk, matching CPU/RAM language."""
    cards = []
    for target,source,mount,device,block,fstype,assigned,allocated,physical,rb,wb,ri,wi,seen in rows:
        assigned = max(0, safe_int(assigned, 0))
        allocated = max(0, safe_int(allocated, 0))
        pct = allocated * 100.0 / assigned if assigned > 0 else 0.0
        level = _v48133_disk_level(pct)
        dev = device or (("/dev/" + block) if block else "-")
        cards.append(
            f'<div class="stat vm-overview-disk-stat disk-level-{level}">'
            f'<div class="vm-disk-stat-label">DISK {escape(target or "-")}</div>'
            f'<b>{_disk_io_bytes(allocated)} / {_disk_io_bytes(assigned)}</b>'
            f'<small>{pct:.1f}% allocated</small>'
            f'<span class="vm-disk-overview-meter"><i style="width:{min(100.0,max(0.0,pct)):.1f}%"></i></span>'
            f'<small class="vm-disk-storage-line">{escape(mount or "-")} · {escape(dev)}</small>'
            f'<small class="vm-disk-live-line">R {_disk_io_rate(rb)} · W {_disk_io_rate(wb)} · IOPS {_disk_io_iops(ri)} / {_disk_io_iops(wi)}</small>'
            f'</div>'
        )
    return "".join(cards)


def _v48133_vm_disk_io_card(rows):
    """Render one clean panel per customer disk with no repeated total strip."""
    if not rows:
        return ""
    panels = []
    latest = 0
    for target,source,mount,device,block,fstype,assigned,allocated,physical,rb,wb,ri,wi,seen in rows:
        assigned = max(0, safe_int(assigned, 0))
        allocated = max(0, safe_int(allocated, 0))
        physical = max(0, safe_int(physical, 0))
        pct = allocated * 100.0 / assigned if assigned > 0 else 0.0
        level = _v48133_disk_level(pct)
        latest = max(latest, safe_int(seen, 0))
        dev = device or (("/dev/" + block) if block else "-")
        panels.append(f'''
        <article class="vm-disk-panel disk-level-{level}">
          <div class="vm-disk-panel-head">
            <div><span>VIRTUAL DISK</span><h4>{escape(target or "-")}</h4></div>
            <div class="vm-disk-storage-badge"><b>{escape(mount or "-")}</b><small>{escape(dev)}</small></div>
          </div>
          <div class="vm-disk-panel-capacity">
            <div><span>ALLOCATED / ASSIGNED</span><b>{_disk_io_bytes(allocated)} / {_disk_io_bytes(assigned)}</b><small>{pct:.1f}% allocated</small></div>
            <span class="vm-disk-overview-meter"><i style="width:{min(100.0,max(0.0,pct)):.1f}%"></i></span>
          </div>
          <div class="vm-disk-panel-metrics">
            <div><span>READ</span><b>{_disk_io_rate(rb)}</b></div>
            <div><span>WRITE</span><b>{_disk_io_rate(wb)}</b></div>
            <div><span>READ IOPS</span><b>{_disk_io_iops(ri)}</b></div>
            <div><span>WRITE IOPS</span><b>{_disk_io_iops(wi)}</b></div>
          </div>
          <div class="vm-disk-panel-meta">
            <div><span>SOURCE</span><code title="{escape(source or '-', quote=True)}">{escape(source or '-')}</code></div>
            <div><span>FILESYSTEM</span><b>{escape(fstype or '-')}</b></div>
            <div><span>PHYSICAL</span><b>{_disk_io_bytes(physical)}</b></div>
            <div><span>LAST SAMPLE</span><b>{fmt_push(seen)}</b></div>
          </div>
        </article>''')
    return f'''
    <div class="card vm-disk-detail-card vm-disk-panels-only" id="virtual-disk-io">
      <div class="table-title-row">
        <div><h3>Virtual Disk I/O</h3><div class="table-hint">Each customer disk is shown separately with capacity, Read/Write and IOPS from the selected retained Agent snapshot.</div></div>
        <div class="count-badges"><span>Disks <b>{len(rows)}</b></span><span>Seen <b>{fmt_push(latest)}</b></span></div>
      </div>
      <div class="vm-disk-detail-grid">{''.join(panels)}</div>
    </div>
    '''


V48133_VM_CSS = r'''
<style id="v48134-vm-disk-detail">
.vm-overview-disk-stat{min-width:225px}.vm-disk-stat-label{font-size:10px;font-weight:950;color:#667085;letter-spacing:.055em}.vm-overview-disk-stat>b{display:block;margin-top:5px!important;font-size:15px!important;white-space:nowrap}.vm-overview-disk-stat>small{display:block;margin-top:4px!important}.vm-disk-overview-meter{display:block;height:6px;margin-top:8px;border-radius:999px;background:#e4e7ec;overflow:hidden}.vm-disk-overview-meter i{display:block;height:100%;border-radius:inherit;background:#12b76a}.disk-level-warm .vm-disk-overview-meter i{background:#fdb022}.disk-level-hot .vm-disk-overview-meter i{background:#f79009}.disk-level-critical .vm-disk-overview-meter i{background:#f04438}.vm-disk-storage-line{color:#667085!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.vm-disk-live-line{color:#475467!important;font-size:9px!important;line-height:1.35!important}
.vm-disk-detail-card{margin-top:16px}.vm-disk-detail-card .table-title-row{margin-bottom:13px}.vm-disk-panel-capacity span,.vm-disk-panel-metrics span,.vm-disk-panel-meta span{display:block;color:#667085;font-size:9px;font-weight:900;letter-spacing:.055em}.vm-disk-detail-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(410px,1fr));gap:12px}.vm-disk-panel{border:1px solid #dbe3ef;border-radius:13px;padding:14px;background:#fff;min-width:0}.vm-disk-panel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.vm-disk-panel-head span{font-size:9px;color:#667085;font-weight:900;letter-spacing:.07em}.vm-disk-panel-head h4{font-size:18px;margin:3px 0 0}.vm-disk-storage-badge{text-align:right;min-width:0}.vm-disk-storage-badge b,.vm-disk-storage-badge small{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.vm-disk-storage-badge b{font-size:12px}.vm-disk-storage-badge small{margin-top:3px;color:#667085;font-size:9px}.vm-disk-panel-capacity{margin-top:13px}.vm-disk-panel-capacity b{display:block;margin-top:4px;font-size:15px}.vm-disk-panel-capacity small{display:block;margin-top:3px;color:#667085;font-size:10px}.vm-disk-panel-metrics{display:grid;grid-template-columns:repeat(4,minmax(80px,1fr));gap:8px;margin-top:13px}.vm-disk-panel-metrics>div{padding:10px;border-radius:9px;background:#f8fafc;border:1px solid #edf0f4}.vm-disk-panel-metrics b{display:block;margin-top:4px;font-size:12px;white-space:nowrap}.vm-disk-panel-meta{display:grid;grid-template-columns:minmax(180px,2fr) repeat(3,minmax(90px,1fr));gap:9px;margin-top:12px;padding-top:12px;border-top:1px solid #edf0f4}.vm-disk-panel-meta b,.vm-disk-panel-meta code{display:block;margin-top:4px;font-size:10px}.vm-disk-panel-meta code{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#475467}.vm-disk-panel.disk-level-hot,.vm-disk-panel.disk-level-critical{border-color:#fed7aa}.vm-disk-panel.disk-level-critical{border-color:#fda29b}
html[data-theme=dark] .vm-disk-stat-label,html[data-theme=dark] .vm-disk-storage-line,html[data-theme=dark] .vm-disk-storage-badge small,html[data-theme=dark] .vm-disk-panel-capacity small,html[data-theme=dark] .vm-disk-panel-metrics span,html[data-theme=dark] .vm-disk-panel-meta span{color:#9fb0c4!important}html[data-theme=dark] .vm-disk-overview-meter{background:#334155}html[data-theme=dark] .vm-disk-panel-metrics>div{background:#132238;border-color:#31445e}html[data-theme=dark] .vm-disk-panel{background:#0f1b2c;border-color:#31445e}html[data-theme=dark] .vm-disk-panel-meta{border-top-color:#31445e}html[data-theme=dark] .vm-disk-panel-meta code{color:#d0d9e7}
@media(max-width:900px){.vm-disk-detail-grid{grid-template-columns:1fr}.vm-disk-panel-metrics{grid-template-columns:1fr 1fr}.vm-disk-panel-meta{grid-template-columns:1fr 1fr}}
</style>
'''


_vm_page_v48133_base = app.view_functions.get("vm_page")


def vm_page_v48133():
    response = _vm_page_v48133_base()
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
        if 'id="virtual-disk-io"' in html:
            return response
        cards = _v48133_vm_disk_overview_cards(rows)
        details = _v48133_vm_disk_io_card(rows)
        pattern = re.compile(
            r'(<div class="card"><h3>Overview</h3><div class="grid">)(.*?)(</div></div>\s*)(<div class="vm-charts-grid">)',
            re.S,
        )
        html, count = pattern.subn(lambda m: m.group(1) + m.group(2) + cards + m.group(3) + details + m.group(4), html, count=1)
        if not count:
            html = html.replace('<div class="vm-charts-grid">', details + '<div class="vm-charts-grid">', 1)
        html = html.replace('</head>', V48133_VM_CSS + '</head>', 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.13.4 VM disk details")
    return response


if _vm_page_v48133_base is not None:
    app.view_functions["vm_page"] = vm_page_v48133


_get_node_filesystems_snapshot_v48133_base = get_node_filesystems_snapshot


def get_node_filesystems_snapshot(node, period):
    """Return capacity and I/O from the same selected retained Agent push."""
    period = clean_period(period)
    conn = db()
    try:
        payload, selected_bucket, latest_bucket = _v5054_selected_storage_payload(conn, node, period)
        if payload:
            seen = safe_int(payload.get("t"), selected_bucket)
            rows = []
            for item in payload.get("s") or []:
                if not isinstance(item, (list, tuple)) or len(item) < 14:
                    continue
                (
                    mount, device, block, raid_level, fstype,
                    size, used, avail, use_percent,
                    read_bps, write_bps, read_iops, write_iops, util_percent,
                ) = item[:14]
                mount = str(mount or "").strip()
                if not mount:
                    continue
                rows.append((
                    mount,
                    str(device or (("/dev/" + str(block)) if block else "")),
                    str(fstype or ""),
                    max(0, safe_int(size, 0)),
                    max(0, safe_int(used, 0)),
                    max(0, safe_int(avail, 0)),
                    max(0.0, safe_float(use_percent, 0.0)),
                    seen,
                    max(0.0, safe_float(read_bps, 0.0)),
                    max(0.0, safe_float(write_bps, 0.0)),
                    max(0.0, safe_float(read_iops, 0.0)),
                    max(0.0, safe_float(write_iops, 0.0)),
                    max(0.0, safe_float(util_percent, 0.0)),
                    seen,
                ))
            if rows:
                return sorted(rows, key=lambda r: (-safe_float(r[6], 0), str(r[0]).lower()))

        # Compatibility fallback for snapshots created before retained Storage
        # payloads existed. Capacity remains historical; I/O is deliberately N/A
        # instead of borrowing current rates from another time.
        fs_bucket = selected_bucket if table_columns(conn, "node_filesystem_stats") else 0
        if fs_bucket:
            rows = conn.execute("""
                SELECT mount,device,fstype,size,used,avail,use_percent,last_push,
                       0,0,0,0,0,0
                FROM node_filesystem_stats
                WHERE node=? AND bucket=?
                ORDER BY use_percent DESC,mount COLLATE NOCASE
            """, (node, fs_bucket)).fetchall()
            if rows:
                return rows

        # Only the live/latest page may use current tables as a final fallback.
        live_request = _request_target_ts() is None and period == "5m" and selected_bucket == latest_bucket
        if live_request and table_columns(conn, "node_storage_current"):
            return conn.execute("""
                SELECT mount,device,fstype,size,used,avail,use_percent,last_seen,
                       read_bps,write_bps,read_iops,write_iops,util_percent,last_seen
                FROM node_storage_current
                WHERE node=?
                ORDER BY use_percent DESC,mount COLLATE NOCASE
            """, (node,)).fetchall()
        return []
    finally:
        conn.close()



def _v48133_public_ip_sql(alias="d"):
    return f"COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest b WHERE b.node={alias}.node AND LOWER(b.role)='public' ORDER BY b.last_seen DESC LIMIT 1),'')"


def _v48133_storage_filter_options(conn, values):
    nodes = [r[0] for r in conn.execute("""
        SELECT node FROM (
          SELECT DISTINCT node FROM vm_disk_current WHERE role='customer'
          UNION SELECT DISTINCT node FROM node_storage_current
        ) ORDER BY node COLLATE NOCASE
    """).fetchall()]
    mount_params = []
    mount_where = ""
    if values.get("node"):
        mount_where = " WHERE node=?"
        mount_params.append(values["node"])
    mounts = [r[0] for r in conn.execute(f"""
        SELECT mount FROM (
          SELECT DISTINCT node,mount FROM vm_disk_current WHERE role='customer' AND mount!=''
          UNION SELECT DISTINCT node,mount FROM node_storage_current WHERE mount!=''
        ){mount_where} ORDER BY mount COLLATE NOCASE
    """, mount_params).fetchall()]
    node_options = ['<option value="">All nodes</option>']
    for item in nodes:
        selected = " selected" if item == values.get("node") else ""
        node_options.append(f'<option value="{escape(item,quote=True)}"{selected}>{escape(item)}</option>')
    mount_options = ['<option value="">All storage</option>']
    for item in mounts:
        selected = " selected" if item == values.get("mount") else ""
        mount_options.append(f'<option value="{escape(item,quote=True)}"{selected}>{escape(item)}</option>')
    return "".join(node_options), "".join(mount_options)


def _v48133_storage_disk_groups(conn, values, start_ts):
    sort_map = {
        "node": "g.node", "uuid": "g.vm_uuid", "diskcount": "g.disk_count",
        "assigned": "g.assigned", "allocated": "g.allocated",
        "allocpct": "CASE WHEN g.assigned>0 THEN g.allocated*1.0/g.assigned ELSE 0 END",
        "read": "g.read_bps", "write": "g.write_bps", "readiops": "g.read_iops",
        "writeiops": "g.write_iops", "seen": "g.last_seen",
    }
    if values["sort"] not in sort_map:
        values["sort"] = "writeiops"
    where = ["d.role='customer'", "d.last_seen>=?", "COALESCE(vi.status,'active')!='hidden'"]
    params = [start_ts]
    if values.get("node"):
        where.append("d.node=?")
        params.append(values["node"])
    if values.get("mount"):
        where.append("d.mount=?")
        params.append(values["mount"])
    if values.get("q"):
        p = like_pattern(values["q"])
        where.append(f"(d.node LIKE ? OR d.vm_uuid LIKE ? OR d.target LIKE ? OR d.source LIKE ? OR d.mount LIKE ? OR d.storage_device LIKE ? OR d.storage_block LIKE ? OR {_v48133_public_ip_sql('d')} LIKE ?)")
        params.extend([p] * 8)
    where_sql = " AND ".join(where)
    cte = f"""
      WITH g AS (
        SELECT d.node,d.vm_uuid,
               {_v48133_public_ip_sql('d')} AS public_ipv4,
               COUNT(*) AS disk_count,
               COALESCE(SUM(d.capacity_bytes),0) AS assigned,
               COALESCE(SUM(d.allocation_bytes),0) AS allocated,
               COALESCE(SUM(d.read_bps),0) AS read_bps,
               COALESCE(SUM(d.write_bps),0) AS write_bps,
               COALESCE(SUM(d.read_iops),0) AS read_iops,
               COALESCE(SUM(d.write_iops),0) AS write_iops,
               MAX(d.last_seen) AS last_seen
        FROM vm_disk_current d
        LEFT JOIN vm_inventory vi ON vi.node=d.node AND vi.vm_uuid=d.vm_uuid
        WHERE {where_sql}
        GROUP BY d.node,d.vm_uuid
      )
    """
    total = safe_int(conn.execute(cte + "SELECT COUNT(*) FROM g", params).fetchone()[0],0)
    pages = max(1, int(math.ceil(total / float(values["limit"]))))
    values["page"] = min(values["page"], pages)
    offset = (values["page"] - 1) * values["limit"]
    direction = "ASC" if values["order"] == "asc" else "DESC"
    groups = conn.execute(cte + f"""
      SELECT g.node,g.vm_uuid,g.public_ipv4,g.disk_count,g.assigned,g.allocated,
             g.read_bps,g.write_bps,g.read_iops,g.write_iops,g.last_seen
      FROM g
      ORDER BY {sort_map[values['sort']]} {direction},g.node,g.vm_uuid
      LIMIT ? OFFSET ?
    """, params + [values["limit"],offset]).fetchall()
    details = {}
    keys = [str(r[0]) + "\x1f" + str(r[1]) for r in groups]
    if keys:
        ph = ",".join("?" for _ in keys)
        drows = conn.execute(f"""
          SELECT node,vm_uuid,target,source,mount,storage_device,storage_block,storage_fstype,
                 capacity_bytes,allocation_bytes,read_bps,write_bps,read_iops,write_iops,last_seen
          FROM vm_disk_current
          WHERE role='customer' AND (node || char(31) || vm_uuid) IN ({ph})
          ORDER BY node,vm_uuid,CASE target WHEN 'vda' THEN 0 WHEN 'vdb' THEN 1 ELSE 2 END,target,source
        """, keys).fetchall()
        for r in drows:
            details.setdefault((str(r[0]),str(r[1])),[]).append(r[2:])
    return groups, details, total


def _v48133_storage_disk_table(conn, values, start_ts):
    """Render one real customer disk per row, never hide vda/vdb inside totals."""
    sort_map = {
        "node": "d.node", "uuid": "d.vm_uuid", "disk": "d.target", "mount": "d.mount",
        "diskcount": "vm_disk_count", "assigned": "d.capacity_bytes", "allocated": "d.allocation_bytes",
        "allocpct": "CASE WHEN d.capacity_bytes>0 THEN d.allocation_bytes*1.0/d.capacity_bytes ELSE 0 END",
        "read": "d.read_bps", "write": "d.write_bps", "readiops": "d.read_iops",
        "writeiops": "d.write_iops", "seen": "d.last_seen",
    }
    if values["sort"] not in sort_map:
        values["sort"] = "writeiops"
    where = ["d.role='customer'", "d.last_seen>=?", "COALESCE(vi.status,'active')!='hidden'"]
    params = [start_ts]
    if values.get("node"):
        where.append("d.node=?")
        params.append(values["node"])
    if values.get("mount"):
        where.append("d.mount=?")
        params.append(values["mount"])
    if values.get("q"):
        p = like_pattern(values["q"])
        where.append(f"(d.node LIKE ? OR d.vm_uuid LIKE ? OR d.target LIKE ? OR d.source LIKE ? OR d.mount LIKE ? OR d.storage_device LIKE ? OR d.storage_block LIKE ? OR {_v48133_public_ip_sql('d')} LIKE ?)")
        params.extend([p] * 8)
    where_sql = " AND ".join(where)
    total = safe_int(conn.execute(f"""
        SELECT COUNT(*)
        FROM vm_disk_current d
        LEFT JOIN vm_inventory vi ON vi.node=d.node AND vi.vm_uuid=d.vm_uuid
        WHERE {where_sql}
    """, params).fetchone()[0], 0)
    pages = max(1, int(math.ceil(total / float(values["limit"]))))
    values["page"] = min(values["page"], pages)
    offset = (values["page"] - 1) * values["limit"]
    direction = "ASC" if values["order"] == "asc" else "DESC"
    rows = conn.execute(f"""
        SELECT d.node,d.vm_uuid,{_v48133_public_ip_sql('d')} AS public_ipv4,
               d.target,d.source,d.mount,d.storage_device,d.storage_block,d.storage_fstype,
               d.capacity_bytes,d.allocation_bytes,d.physical_bytes,
               d.read_bps,d.write_bps,d.read_iops,d.write_iops,d.last_seen,
               (SELECT COUNT(*) FROM vm_disk_current x
                WHERE x.node=d.node AND x.vm_uuid=d.vm_uuid AND x.role='customer') AS vm_disk_count
        FROM vm_disk_current d
        LEFT JOIN vm_inventory vi ON vi.node=d.node AND vi.vm_uuid=d.vm_uuid
        WHERE {where_sql}
        ORDER BY {sort_map[values['sort']]} {direction}, d.node COLLATE NOCASE, d.vm_uuid,
                 CASE d.target WHEN 'vda' THEN 0 WHEN 'vdb' THEN 1 ELSE 2 END,
                 d.target COLLATE NOCASE,d.source COLLATE NOCASE
        LIMIT ? OFFSET ?
    """, params + [values["limit"], offset]).fetchall()

    body = []
    previous_vm = None
    for row in rows:
        node,vm_uuid,public_ip,target,source,mount,device,block,fstype,assigned,allocated,physical,rb,wb,ri,wi,seen,vm_disk_count = row
        vm_href = url_for("vm_page", node=node, vm_uuid=vm_uuid, period=values["period"])
        node_href = url_for("node_page", node=node, period=values["period"], q=vm_uuid)
        ip = compact_ipv4(public_ip)
        dev = device or (("/dev/" + block) if block else "-")
        group_key = (str(node), str(vm_uuid))
        row_class = "storage-vm-start" if group_key != previous_vm else "storage-vm-cont"
        previous_vm = group_key
        ip_line = f'<span class="storage-node-ip">{escape(ip)}<button type="button" class="copy-btn" data-copy="{escape(ip)}" title="Copy IP">⧉</button></span>' if ip else ''
        uuid_html = (
            f'<span class="uuid-cell"><a href="{escape(vm_href,quote=True)}" title="{escape(vm_uuid,quote=True)}">{escape(vm_uuid)}</a>'
            f'<button type="button" class="copy-btn" data-copy="{escape(vm_uuid)}" title="Copy UUID">⧉</button></span>'
            f'<small>{safe_int(vm_disk_count,0)} customer disk{"s" if safe_int(vm_disk_count,0) != 1 else ""}</small>'
        )
        body.append(
            f'<tr class="{row_class}">'
            f'<td class="storage-node-cell"><a href="{escape(node_href,quote=True)}"><b>{escape(node)}</b></a>{ip_line}</td>'
            f'<td class="storage-uuid-cell">{uuid_html}</td>'
            f'<td class="storage-one-disk"><div class="storage-disk-title"><b>{escape(target or "-")}</b><span>{escape(mount or "-")} · {escape(dev)}</span></div><code title="{escape(source or "-",quote=True)}">{escape(source or "-")}</code><small>{escape(fstype or "-")} · Physical {_disk_io_bytes(physical)}</small></td>'
            f'<td>{_disk_io_capacity(allocated,assigned)}</td>'
            f'<td class="num">{_disk_io_rate(rb)}</td><td class="num"><b>{_disk_io_rate(wb)}</b></td>'
            f'<td class="num">{_disk_io_iops(ri)}</td><td class="num"><b>{_disk_io_iops(wi)}</b></td><td class="num"><small>{fmt_push(seen)}</small></td>'
            '</tr>'
        )
    if not body:
        body = ['<tr><td colspan="9" class="empty">No customer disk sample in this lookback</td></tr>']
    h = lambda label,key: _storage_sort_header(values,label,key)
    return (
        '<div class="card storage-table-card">'
        '<div class="table-title-row"><div><h3>VM Disks</h3><div class="table-hint">One row per customer disk. UUID and node stay visible on every row, so vda/vdb are separate and sortable.</div></div></div>'
        '<div class="table-wrap"><table class="storage-disk-detail-table"><thead><tr>'
        f'<th>{h("NODE","node")}</th><th>{h("VM UUID","uuid")}</th><th><div>DISK / STORAGE</div><small>{h("DISK","disk")} · {h("STORAGE","mount")} · {h("COUNT","diskcount")}</small></th>'
        f'<th><div>ALLOCATED / ASSIGNED</div><small>{h("ALLOC","allocated")} · {h("ASSIGNED","assigned")} · {h("%","allocpct")}</small></th>'
        f'<th>{h("READ","read")}</th><th>{h("WRITE","write")}</th><th>{h("R IOPS","readiops")}</th><th>{h("W IOPS","writeiops")}</th><th>{h("SEEN","seen")}</th>'
        '</tr></thead><tbody>' + ''.join(body) + '</tbody></table></div>' + _storage_pager(values,total) + '</div>'
    )


def _v48133_storage_node_table(conn, values, start_ts):
    sort_map={
        "node":"s.node","mount":"s.mount","size":"s.size","used":"s.used","usepct":"s.use_percent",
        "read":"s.read_bps","write":"s.write_bps","readiops":"s.read_iops","writeiops":"s.write_iops","util":"s.util_percent","seen":"s.last_seen",
    }
    if values["sort"] not in sort_map:
        values["sort"]="writeiops"
    where=["s.last_seen>=?"]
    params=[start_ts]
    if values.get("node"):
        where.append("s.node=?");params.append(values["node"])
    if values.get("mount"):
        where.append("s.mount=?");params.append(values["mount"])
    if values.get("q"):
        p=like_pattern(values["q"])
        where.append(f"(s.node LIKE ? OR s.mount LIKE ? OR s.device LIKE ? OR s.block LIKE ? OR s.raid_level LIKE ? OR s.fstype LIKE ? OR {_v48133_public_ip_sql('s')} LIKE ?)")
        params.extend([p]*7)
    where_sql=' AND '.join(where)
    total=safe_int(conn.execute(f"SELECT COUNT(*) FROM node_storage_current s WHERE {where_sql}",params).fetchone()[0],0)
    pages=max(1,int(math.ceil(total/float(values["limit"]))))
    values["page"]=min(values["page"],pages)
    offset=(values["page"]-1)*values["limit"]
    direction="ASC" if values["order"]=="asc" else "DESC"
    rows=conn.execute(f"""
      SELECT s.node,{_v48133_public_ip_sql('s')} AS public_ipv4,s.mount,s.device,s.block,s.raid_level,s.fstype,
             s.size,s.used,s.avail,s.use_percent,s.read_bps,s.write_bps,s.read_iops,s.write_iops,s.util_percent,s.last_seen,
             (SELECT COUNT(*) FROM vm_disk_current d WHERE d.node=s.node AND d.mount=s.mount AND d.role='customer') AS disk_count,
             (SELECT COUNT(DISTINCT d.vm_uuid) FROM vm_disk_current d WHERE d.node=s.node AND d.mount=s.mount AND d.role='customer') AS vm_count
      FROM node_storage_current s WHERE {where_sql}
      ORDER BY {sort_map[values['sort']]} {direction},s.node,s.mount
      LIMIT ? OFFSET ?
    """,params+[values["limit"],offset]).fetchall()
    body=[]
    for node,public_ip,mount,device,block,raid,fs,size,used,avail,usep,rb,wb,ri,wi,util,seen,disk_count,vm_count in rows:
        filter_href=_storage_io_url(values,view="disks",node=node,mount=mount,sort="writeiops",order="desc",page=1)
        node_href=url_for("node_page",node=node,period=values["period"])
        ip=compact_ipv4(public_ip)
        ip_line=f'<span class="storage-node-ip">{escape(ip)}<button type="button" class="copy-btn" data-copy="{escape(ip)}" title="Copy IP">⧉</button></span>' if ip else ''
        body.append(
            '<tr>'
            f'<td class="storage-node-cell"><a href="{escape(node_href,quote=True)}"><b>{escape(node)}</b></a>{ip_line}</td>'
            f'<td class="storage-backend"><a href="{escape(filter_href,quote=True)}"><b>{escape(mount or "-")}</b></a><span>{escape(device or "-")} · {escape(raid or "hardware/unknown RAID")} · {escape(fs or "-")}</span></td>'
            f'<td>{_disk_io_capacity(used,size,"used / size")}</td>'
            f'<td class="num">{_disk_io_rate(rb)}</td><td class="num"><b>{_disk_io_rate(wb)}</b></td><td class="num">{_disk_io_iops(ri)}</td><td class="num"><b>{_disk_io_iops(wi)}</b></td><td class="num"><b>{safe_float(util,0):.1f}%</b></td>'
            f'<td class="num"><b>{vm_count}</b><small class="storage-count-sub">{disk_count} disks</small></td><td class="num"><small>{fmt_push(seen)}</small></td>'
            '</tr>'
        )
    if not body:
        body=['<tr><td colspan="10" class="empty">No node storage sample in this lookback</td></tr>']
    h=lambda label,key:_storage_sort_header(values,label,key)
    return (
        '<div class="card storage-table-card">'
        '<div class="table-title-row"><div><h3>Storage Node</h3><div class="table-hint">Every real node mount reported by the Agent. Click a mount to see the VMs and disks mapped to it.</div></div></div>'
        '<div class="table-wrap"><table class="storage-node-table"><thead><tr>'
        f'<th>{h("NODE","node")}</th><th>{h("MOUNT / DEVICE","mount")}</th><th><div>USED / SIZE</div><small>{h("USED","used")} · {h("SIZE","size")} · {h("%","usepct")}</small></th>'
        f'<th>{h("READ","read")}</th><th>{h("WRITE","write")}</th><th>{h("R IOPS","readiops")}</th><th>{h("W IOPS","writeiops")}</th><th>{h("UTIL","util")}</th><th>VM / DISKS</th><th>{h("SEEN","seen")}</th>'
        '</tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'+_storage_pager(values,total)+'</div>'
    )


V48133_STORAGE_CSS = r'''
<style id="v48134-storage-integrated">
.storage-search-bar{display:grid;grid-template-columns:minmax(340px,1.9fr) minmax(150px,.7fr) minmax(150px,.7fr) 78px auto auto;gap:9px;align-items:end}.storage-search-bar label{display:grid;gap:5px;font-size:10px;font-weight:900;color:#667085}.storage-search-bar input,.storage-search-bar select{min-height:41px}.storage-search-bar .storage-search-input{font-size:13px;padding-left:38px}.storage-search-wrap{position:relative}.storage-search-wrap:before{content:'⌕';position:absolute;left:13px;bottom:9px;font-size:20px;color:#667085;z-index:2}.storage-search-wrap input{width:100%}.storage-search-bar button,.storage-search-bar .clear{min-height:41px;display:flex;align-items:center;justify-content:center}
.storage-disk-detail-table{min-width:1740px;table-layout:fixed}.storage-disk-detail-table th:nth-child(1){width:180px}.storage-disk-detail-table th:nth-child(2){width:300px}.storage-disk-detail-table th:nth-child(3){width:420px}.storage-disk-detail-table th:nth-child(4){width:255px}.storage-disk-detail-table th:nth-child(n+5){width:116px}.storage-disk-detail-table td{vertical-align:middle}.storage-disk-detail-table td.num{text-align:right;white-space:nowrap}.storage-disk-detail-table tr.storage-vm-start td{border-top:2px solid #dbe3ef!important}.storage-disk-detail-table tr.storage-vm-start:first-child td{border-top:0!important}.storage-disk-detail-table tr.storage-vm-cont td{background:#fbfcfe}
.storage-node-cell>a,.storage-node-cell>b,.storage-node-ip{display:block}.storage-node-ip{margin-top:5px;font-size:10px;color:#667085}.storage-node-ip .copy-btn{margin-left:5px;transform:scale(.86)}.storage-uuid-cell small{display:block;margin-top:7px;color:#667085}.storage-one-disk{min-width:0}.storage-disk-title{display:flex;align-items:baseline;gap:8px;min-width:0}.storage-disk-title b{font-size:13px}.storage-disk-title span{font-size:10px;color:#667085;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.storage-one-disk code{display:block;margin-top:6px;font-size:9px;color:#667085;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.storage-one-disk small{display:block;margin-top:5px;color:#98a2b3;font-size:9px}.storage-node-table{min-width:1640px;table-layout:fixed}.storage-node-table th:nth-child(1){width:200px}.storage-node-table th:nth-child(2){width:315px}.storage-node-table th:nth-child(3){width:260px}.storage-node-table th:nth-child(n+4){width:120px}.storage-node-table td.num{text-align:right;white-space:nowrap}.storage-count-sub{display:block;margin-top:4px;color:#667085}
html[data-theme=dark] .storage-node-ip,html[data-theme=dark] .storage-uuid-cell small,html[data-theme=dark] .storage-disk-title span,html[data-theme=dark] .storage-one-disk code,html[data-theme=dark] .storage-one-disk small,html[data-theme=dark] .storage-count-sub{color:#9fb0c4}html[data-theme=dark] .storage-disk-detail-table tr.storage-vm-start td{border-top-color:#31445e!important}html[data-theme=dark] .storage-disk-detail-table tr.storage-vm-cont td{background:#101d30}
@media(max-width:1100px){.storage-search-bar{grid-template-columns:1fr 1fr}}
</style>
'''


def storage_io_page_v48133():
    values=_storage_io_params()
    if values["view"] == "backends":
        values["view"]="nodes"
    if values["view"] not in {"disks","nodes"}:
        values["view"]="disks"
    start_ts,end_ts=range_for_period(values["period"])
    conn=db()
    try:
        ensure_disk_io_schema(conn)
        node_options,mount_options=_v48133_storage_filter_options(conn,values)
        table=_v48133_storage_node_table(conn,values,start_ts) if values["view"]=="nodes" else _v48133_storage_disk_table(conn,values,start_ts)
    finally:
        conn.close()
    clear_href=url_for("storage_io_page",view=values["view"],period=values["period"])
    disk_tab=_storage_io_url(values,view="disks",sort="writeiops",order="desc",page=1)
    node_tab=_storage_io_url(values,view="nodes",sort="writeiops",order="desc",page=1)
    content=(
        STORAGE_IO_CSS+V48133_STORAGE_CSS
        +'<div class="card storage-hero"><div><span class="eyebrow">DISK MONITOR</span><h2>Storage I/O</h2><p>See node mount load, then drill into the exact VM and every disk attached to its UUID.</p></div>'
        +f'<div class="storage-tabs"><a class="{"active" if values["view"]=="disks" else ""}" href="{escape(disk_tab,quote=True)}">VM Disks</a><a class="{"active" if values["view"]=="nodes" else ""}" href="{escape(node_tab,quote=True)}">Storage Node</a></div></div>'
        +'<div class="card storage-toolbar">'
        +f'<div><div class="label">Latest sample lookback</div><div class="storage-periods">{_storage_period_links(values)}</div></div>'
        +f'<form class="storage-search-bar" method="get" action="{url_for("storage_io_page")}">'
        +f'<input type="hidden" name="view" value="{escape(values["view"],quote=True)}"><input type="hidden" name="period" value="{escape(values["period"],quote=True)}"><input type="hidden" name="sort" value="{escape(values["sort"],quote=True)}"><input type="hidden" name="order" value="{escape(values["order"],quote=True)}">'
        +f'<label class="storage-search-wrap">SEARCH<input class="storage-search-input" name="q" value="{escape(values["q"],quote=True)}" placeholder="Search node, IP, UUID, disk, path or mount"></label>'
        +f'<label>NODE<select name="node">{node_options}</select></label><label>STORAGE<select name="mount">{mount_options}</select></label>'
        +f'<label>ROWS<input name="limit" value="{values["limit"]}" inputmode="numeric"></label><button type="submit">Search</button><a class="clear" href="{escape(clear_href,quote=True)}">Clear</a></form>'
        +f'<div class="storage-note">Selected window: <b>{escape(values["period"])}</b> · latest samples from <b>{fmt_full(start_ts)}</b> to <b>{fmt_full(end_ts)}</b>. Capacity is current; Read/Write and IOPS are current sample rates.</div>'
        +'</div>'+table
    )
    return page("Storage I/O",content)


app.view_functions["storage_io_page"] = storage_io_page_v48133


def purge_vm_data(conn, node, vm_uuid, refresh_snapshots=True):
    """Purge exactly one UUID from every VM-scoped dataset.

    No broad DELETE is used: other VMs' Current Abuse and Abuse Events remain
    visible.  The UUID is removed across all node copies so Dashboard, Top VM,
    Storage I/O and historical 5m searches cannot leave ghost rows.
    """
    vm_uuid=str(vm_uuid or "").strip()
    node=str(node or "").strip()
    if not vm_uuid:
        raise ValueError("Missing VM UUID")
    ensure_disk_io_schema(conn)
    affected_nodes={str(r[0]) for r in conn.execute("""
      SELECT DISTINCT node FROM (
        SELECT node FROM vm_inventory WHERE vm_uuid=:u
        UNION SELECT node FROM vm_node_presence WHERE vm_uuid=:u
        UNION SELECT node FROM vm_current_fast WHERE vm_uuid=:u
        UNION SELECT node FROM vm_iface_current WHERE vm_uuid=:u
        UNION SELECT node FROM vm_latest_metrics WHERE vm_uuid=:u
        UNION SELECT node FROM vm_perf_stats WHERE vm_uuid=:u
        UNION SELECT node FROM node_stats WHERE vm_uuid=:u
        UNION SELECT node FROM usage WHERE vm_uuid=:u
        UNION SELECT node FROM vm_abuse_state WHERE vm_uuid=:u
        UNION SELECT node FROM vm_abuse_events WHERE vm_uuid=:u
        UNION SELECT node FROM vm_abuse_incidents WHERE vm_uuid=:u
        UNION SELECT node FROM vm_disk_current WHERE vm_uuid=:u
      ) WHERE node IS NOT NULL AND TRIM(node)!=''
    """,{"u":vm_uuid}).fetchall()}
    if node:
        affected_nodes.add(node)
    deleted={}
    uuid_tables=(
        "vm_iface_current","vm_current_fast","vm_abuse_state","vm_abuse_events","vm_abuse_incidents",
        "usage","node_stats","vm_perf_stats","vm_latest_metrics","bandwidth_hourly","bandwidth_daily",
        "vm_node_presence","vm_inventory","vm_disk_current",
    )
    for table in uuid_tables:
        deleted[table]=_delete_count(conn,f"DELETE FROM {table} WHERE vm_uuid=?",(vm_uuid,))
    deleted["vm_migration_events"]=_delete_count(conn,"DELETE FROM vm_migration_events WHERE vm_uuid=?",(vm_uuid,))
    deleted["vm_location_latest"]=_delete_count(conn,"DELETE FROM vm_location_latest WHERE vm_uuid=?",(vm_uuid,))
    for affected in sorted(affected_nodes):
        if refresh_snapshots:
            _refresh_node_snapshot_vm_counts(conn,affected)
        conn.execute("""
          UPDATE node_current_fast
          SET vm_count=(SELECT COUNT(*) FROM vm_current_fast v WHERE v.node=node_current_fast.node),
              iface_count=(SELECT COUNT(*) FROM vm_iface_current i WHERE i.node=node_current_fast.node)
          WHERE node=?
        """,(affected,))
    deleted["affected_nodes"]=len(affected_nodes)
    return deleted

# ---------------------------------------------------------------------------
