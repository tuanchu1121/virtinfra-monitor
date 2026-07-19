# v48.13.2 disk-only extension
# Original Dashboard, Top VM, VM Abuse and Node Health renderers stay untouched.
# ---------------------------------------------------------------------------

NODE_FILESYSTEM_IO_CSS = r'''
<style id="node-filesystem-io-v48132r2">
.node-filesystem-io-table{min-width:1420px}.node-filesystem-io-table td.num,.node-filesystem-io-table th:nth-child(n+8){text-align:right;white-space:nowrap}
</style>
'''


def ensure_disk_io_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS vm_disk_current (
      node TEXT NOT NULL,
      vm_uuid TEXT NOT NULL,
      target TEXT NOT NULL,
      source TEXT NOT NULL DEFAULT '',
      role TEXT NOT NULL DEFAULT 'unknown',
      mount TEXT NOT NULL DEFAULT '',
      storage_device TEXT NOT NULL DEFAULT '',
      storage_block TEXT NOT NULL DEFAULT '',
      storage_fstype TEXT NOT NULL DEFAULT '',
      capacity_bytes INTEGER NOT NULL DEFAULT 0,
      allocation_bytes INTEGER NOT NULL DEFAULT 0,
      physical_bytes INTEGER NOT NULL DEFAULT 0,
      interval_seconds INTEGER NOT NULL DEFAULT 300,
      read_bps REAL NOT NULL DEFAULT 0,
      write_bps REAL NOT NULL DEFAULT 0,
      read_iops REAL NOT NULL DEFAULT 0,
      write_iops REAL NOT NULL DEFAULT 0,
      last_seen INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(node, vm_uuid, target, source)
    );
    CREATE INDEX IF NOT EXISTS idx_vm_disk_current_vm
      ON vm_disk_current(node, vm_uuid, role, target);
    CREATE INDEX IF NOT EXISTS idx_vm_disk_current_mount
      ON vm_disk_current(role, mount, node, vm_uuid);

    CREATE TABLE IF NOT EXISTS node_storage_current (
      node TEXT NOT NULL,
      mount TEXT NOT NULL,
      device TEXT NOT NULL DEFAULT '',
      block TEXT NOT NULL DEFAULT '',
      raid_level TEXT NOT NULL DEFAULT '',
      fstype TEXT NOT NULL DEFAULT '',
      size INTEGER NOT NULL DEFAULT 0,
      used INTEGER NOT NULL DEFAULT 0,
      avail INTEGER NOT NULL DEFAULT 0,
      use_percent REAL NOT NULL DEFAULT 0,
      read_bps REAL NOT NULL DEFAULT 0,
      write_bps REAL NOT NULL DEFAULT 0,
      read_iops REAL NOT NULL DEFAULT 0,
      write_iops REAL NOT NULL DEFAULT 0,
      util_percent REAL NOT NULL DEFAULT 0,
      last_seen INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(node, mount)
    );
    """)


def ingest_disk_io_current(conn, node, data_time, interval_seconds, vms, node_host):
    """Store only the latest per-disk and per-storage sample.

    The period selector on Storage I/O is a latest-sample lookback. We avoid a
    high-volume per-disk history table so the primary database remains bounded at large scale.
    """
    ensure_disk_io_schema(conn)
    interval_seconds = max(1, safe_int(interval_seconds, CACHE_BUCKET_SECONDS))

    for vm in vms or []:
        if not isinstance(vm, dict):
            continue
        vm_uuid = str(vm.get("vm_uuid") or "").strip()
        if not vm_uuid:
            continue
        for disk in vm.get("disks") or []:
            if not isinstance(disk, dict):
                continue
            target = str(disk.get("target") or "").strip()
            if not target:
                continue
            source = str(disk.get("source") or "").strip()
            role = str(disk.get("role") or "unknown").strip().lower()[:32]
            di = max(1, safe_int(disk.get("interval_seconds"), interval_seconds))
            read_delta = max(0, safe_int(disk.get("read_delta"), 0))
            write_delta = max(0, safe_int(disk.get("write_delta"), 0))
            read_reqs = max(0, safe_int(disk.get("read_reqs_delta"), 0))
            write_reqs = max(0, safe_int(disk.get("write_reqs_delta"), 0))
            conn.execute("""
                INSERT INTO vm_disk_current(
                  node,vm_uuid,target,source,role,mount,storage_device,storage_block,storage_fstype,
                  capacity_bytes,allocation_bytes,physical_bytes,interval_seconds,
                  read_bps,write_bps,read_iops,write_iops,last_seen
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(node,vm_uuid,target,source) DO UPDATE SET
                  role=excluded.role,
                  mount=excluded.mount,
                  storage_device=excluded.storage_device,
                  storage_block=excluded.storage_block,
                  storage_fstype=excluded.storage_fstype,
                  capacity_bytes=excluded.capacity_bytes,
                  allocation_bytes=excluded.allocation_bytes,
                  physical_bytes=excluded.physical_bytes,
                  interval_seconds=excluded.interval_seconds,
                  read_bps=excluded.read_bps,
                  write_bps=excluded.write_bps,
                  read_iops=excluded.read_iops,
                  write_iops=excluded.write_iops,
                  last_seen=excluded.last_seen
            """, (
                node, vm_uuid, target, source, role,
                str(disk.get("mount") or ""),
                str(disk.get("storage_device") or ""),
                str(disk.get("storage_block") or ""),
                str(disk.get("storage_fstype") or ""),
                max(0, safe_int(disk.get("capacity_bytes"), 0)),
                max(0, safe_int(disk.get("allocation_bytes"), 0)),
                max(0, safe_int(disk.get("physical_bytes"), 0)),
                di,
                read_delta / float(di), write_delta / float(di),
                read_reqs / float(di), write_reqs / float(di), data_time,
            ))

    # A complete node sample replaces the previous latest disk inventory.
    conn.execute("DELETE FROM vm_disk_current WHERE node=? AND last_seen<?", (node, data_time))

    for storage in (node_host or {}).get("storage_devices") or []:
        if not isinstance(storage, dict):
            continue
        mount = str(storage.get("mount") or "").strip()
        if not mount:
            continue
        conn.execute("""
            INSERT INTO node_storage_current(
              node,mount,device,block,raid_level,fstype,size,used,avail,use_percent,
              read_bps,write_bps,read_iops,write_iops,util_percent,last_seen
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(node,mount) DO UPDATE SET
              device=excluded.device,
              block=excluded.block,
              raid_level=excluded.raid_level,
              fstype=excluded.fstype,
              size=excluded.size,
              used=excluded.used,
              avail=excluded.avail,
              use_percent=excluded.use_percent,
              read_bps=excluded.read_bps,
              write_bps=excluded.write_bps,
              read_iops=excluded.read_iops,
              write_iops=excluded.write_iops,
              util_percent=excluded.util_percent,
              last_seen=excluded.last_seen
        """, (
            node, mount,
            str(storage.get("device") or ""),
            str(storage.get("block") or ""),
            str(storage.get("raid_level") or ""),
            str(storage.get("fstype") or ""),
            max(0, safe_int(storage.get("size"), 0)),
            max(0, safe_int(storage.get("used"), 0)),
            max(0, safe_int(storage.get("avail"), 0)),
            max(0.0, safe_float(storage.get("use_percent"), 0.0)),
            max(0.0, safe_float(storage.get("read_bps"), 0.0)),
            max(0.0, safe_float(storage.get("write_bps"), 0.0)),
            max(0.0, safe_float(storage.get("read_iops"), 0.0)),
            max(0.0, safe_float(storage.get("write_iops"), 0.0)),
            max(0.0, safe_float(storage.get("util_percent"), 0.0)),
            data_time,
        ))
    conn.execute("DELETE FROM node_storage_current WHERE node=? AND last_seen<?", (node, data_time))


def _disk_io_bytes(value):
    value = max(0.0, safe_float(value, 0.0))
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1024.0
    return "0 B"


def _disk_io_rate(value):
    return _disk_io_bytes(value) + "/s"


def _disk_io_iops(value):
    return f"{max(0.0, safe_float(value, 0.0)):,.1f}"


def _disk_io_capacity(allocated, assigned, label="allocated / assigned"):
    allocated = max(0, safe_int(allocated, 0))
    assigned = max(0, safe_int(assigned, 0))
    pct = min(999.9, allocated * 100.0 / assigned) if assigned else 0.0
    level = "disk-cap-ok"
    if pct >= 90:
        level = "disk-cap-critical"
    elif pct >= 75:
        level = "disk-cap-hot"
    elif pct >= 50:
        level = "disk-cap-warm"
    width = min(100.0, pct)
    return (
        f'<div class="disk-capacity {level}">'
        f'<b>{_disk_io_bytes(allocated)} <span>/ {_disk_io_bytes(assigned)}</span></b>'
        f'<div class="disk-cap-meter"><i style="width:{width:.1f}%"></i></div>'
        f'<small>{pct:.1f}% · {escape(label)}</small>'
        f'</div>'
    )


def _storage_io_params(**updates):
    values = {
        "view": (request.args.get("view") or "disks").strip().lower(),
        "period": clean_period(request.args.get("period") or "15m"),
        "q": (request.args.get("q") or "").strip(),
        "node": (request.args.get("node") or "").strip(),
        "mount": (request.args.get("mount") or "").strip(),
        "sort": (request.args.get("sort") or "writeiops").strip().lower(),
        "order": clean_sort_order(request.args.get("order") or "desc"),
        "limit": max(20, min(500, safe_int(request.args.get("limit"), 100))),
        "page": max(1, safe_int(request.args.get("page"), 1)),
    }
    values.update(updates)
    return values


def _storage_io_url(values, **updates):
    merged = dict(values)
    merged.update(updates)
    return url_for("storage_io_page", **merged)


def _storage_sort_header(values, label, key):
    active = values["sort"] == key
    order = "asc" if active and values["order"] == "desc" else "desc"
    arrow = " ↓" if active and values["order"] == "desc" else (" ↑" if active else "")
    href = _storage_io_url(values, sort=key, order=order, page=1)
    active_class = " active" if active else ""
    return f'<a class="storage-sort{active_class}" href="{escape(href, quote=True)}">{escape(label)}{arrow}</a>'


def _storage_period_links(values):
    links = []
    for key in PERIODS:
        label = PERIOD_LABELS.get(key, key)
        cls = "active" if key == values["period"] else ""
        href = _storage_io_url(values, period=key, page=1)
        links.append(f'<a class="{cls}" href="{escape(href, quote=True)}">{escape(label)}</a>')
    return "".join(links)


def _storage_pager(values, total):
    limit = values["limit"]
    pages = max(1, int(math.ceil(total / float(limit))))
    page_no = min(values["page"], pages)
    if pages <= 1:
        return f'<div class="storage-page-summary">Rows <b>{total}</b></div>'
    pieces = []
    for pno in sorted({1, pages, page_no - 1, page_no, page_no + 1}):
        if 1 <= pno <= pages:
            cls = "active" if pno == page_no else ""
            pieces.append(f'<a class="{cls}" href="{escape(_storage_io_url(values, page=pno), quote=True)}">{pno}</a>')
    prev = max(1, page_no - 1)
    nxt = min(pages, page_no + 1)
    return (
        '<div class="storage-pager">'
        f'<div>Rows <b>{total}</b> · Page <b>{page_no}/{pages}</b></div>'
        f'<div><a href="{escape(_storage_io_url(values, page=prev), quote=True)}">Prev</a>'
        + "".join(pieces)
        + f'<a href="{escape(_storage_io_url(values, page=nxt), quote=True)}">Next</a></div></div>'
    )


def _storage_filter_options(conn, values):
    nodes = [r[0] for r in conn.execute(
        "SELECT DISTINCT node FROM vm_disk_current WHERE role='customer' ORDER BY node"
    ).fetchall()]
    if values["node"]:
        mounts = [r[0] for r in conn.execute(
            "SELECT DISTINCT mount FROM vm_disk_current WHERE role='customer' AND node=? AND mount!='' ORDER BY mount",
            (values["node"],),
        ).fetchall()]
    else:
        mounts = [r[0] for r in conn.execute(
            "SELECT DISTINCT mount FROM vm_disk_current WHERE role='customer' AND mount!='' ORDER BY mount"
        ).fetchall()]
    node_options = ['<option value="">All nodes</option>']
    for item in nodes:
        selected = " selected" if item == values["node"] else ""
        node_options.append(f'<option value="{escape(item, quote=True)}"{selected}>{escape(item)}</option>')
    mount_options = ['<option value="">All storage</option>']
    for item in mounts:
        selected = " selected" if item == values["mount"] else ""
        mount_options.append(f'<option value="{escape(item, quote=True)}"{selected}>{escape(item)}</option>')
    return "".join(node_options), "".join(mount_options)


def _storage_io_disk_table(conn, values, start_ts):
    sort_map = {
        "node": "d.node", "uuid": "d.vm_uuid", "disk": "d.target", "mount": "d.mount",
        "assigned": "d.capacity_bytes", "allocated": "d.allocation_bytes",
        "allocpct": "CASE WHEN d.capacity_bytes>0 THEN d.allocation_bytes*1.0/d.capacity_bytes ELSE 0 END",
        "read": "d.read_bps", "write": "d.write_bps",
        "readiops": "d.read_iops", "writeiops": "d.write_iops", "seen": "d.last_seen",
    }
    if values["sort"] not in sort_map:
        values["sort"] = "writeiops"
    where = ["d.role='customer'", "d.last_seen>=?", "COALESCE(vi.status,'active')!='hidden'"]
    params = [start_ts]
    if values["node"]:
        where.append("d.node=?")
        params.append(values["node"])
    if values["mount"]:
        where.append("d.mount=?")
        params.append(values["mount"])
    if values["q"]:
        pattern = like_pattern(values["q"])
        where.append("(d.node LIKE ? OR d.vm_uuid LIKE ? OR d.target LIKE ? OR d.source LIKE ? OR d.mount LIKE ? OR d.storage_device LIKE ? OR d.storage_block LIKE ?)")
        params.extend([pattern] * 7)
    where_sql = " AND ".join(where)
    total = conn.execute(f"""
        SELECT COUNT(*)
        FROM vm_disk_current d
        LEFT JOIN vm_inventory vi ON vi.node=d.node AND vi.vm_uuid=d.vm_uuid
        WHERE {where_sql}
    """, params).fetchone()[0]
    pages = max(1, int(math.ceil(total / float(values["limit"]))))
    values["page"] = min(values["page"], pages)
    offset = (values["page"] - 1) * values["limit"]
    direction = "ASC" if values["order"] == "asc" else "DESC"
    rows = conn.execute(f"""
        SELECT d.node,d.vm_uuid,d.target,d.mount,d.storage_device,d.storage_block,d.source,
               d.capacity_bytes,d.allocation_bytes,d.physical_bytes,
               d.read_bps,d.write_bps,d.read_iops,d.write_iops,d.last_seen
        FROM vm_disk_current d
        LEFT JOIN vm_inventory vi ON vi.node=d.node AND vi.vm_uuid=d.vm_uuid
        WHERE {where_sql}
        ORDER BY {sort_map[values['sort']]} {direction}, d.node, d.vm_uuid, d.target
        LIMIT ? OFFSET ?
    """, params + [values["limit"], offset]).fetchall()
    body = []
    for row in rows:
        node, vm_uuid, target, mount, device, block, source, assigned, allocated, physical, rb, wb, ri, wi, seen = row
        href = url_for("vm_page", node=node, vm_uuid=vm_uuid, period=values["period"])
        storage = mount or "-"
        storage_meta = device or (("/dev/" + block) if block else "-")
        body.append(
            '<tr>'
            f'<td class="storage-id"><b>{escape(node)}</b><a href="{escape(href, quote=True)}">{escape(vm_uuid)}</a></td>'
            f'<td class="storage-disk"><b>{escape(target or "-")}</b><span>{escape(storage)} · {escape(storage_meta)}</span><small title="{escape(source, quote=True)}">{escape(source or "-")}</small></td>'
            f'<td>{_disk_io_capacity(allocated, assigned)}</td>'
            f'<td class="num">{_disk_io_rate(rb)}</td>'
            f'<td class="num"><b>{_disk_io_rate(wb)}</b></td>'
            f'<td class="num">{_disk_io_iops(ri)}</td>'
            f'<td class="num"><b>{_disk_io_iops(wi)}</b></td>'
            f'<td class="num"><small>{fmt_push(seen)}</small></td>'
            '</tr>'
        )
    if not body:
        body = ['<tr><td colspan="8" class="empty">No customer disk sample in this lookback</td></tr>']
    h = lambda label, key: _storage_sort_header(values, label, key)
    return (
        '<div class="card storage-table-card">'
        '<div class="table-title-row"><div><h3>VM Disks</h3><div class="table-hint">One row per customer disk. Allocation is host-side file/block allocation, not guest filesystem usage.</div></div></div>'
        '<div class="table-wrap"><table class="storage-disk-table"><thead><tr>'
        f'<th><div>NODE / VM</div><small>{h("NODE","node")} · {h("UUID","uuid")}</small></th>'
        f'<th><div>DISK / STORAGE</div><small>{h("DISK","disk")} · {h("STORAGE","mount")}</small></th>'
        f'<th><div>ALLOCATED / ASSIGNED</div><small>{h("ALLOC","allocated")} · {h("ASSIGNED","assigned")} · {h("%","allocpct")}</small></th>'
        f'<th>{h("READ","read")}</th><th>{h("WRITE","write")}</th><th>{h("R IOPS","readiops")}</th><th>{h("W IOPS","writeiops")}</th><th>{h("SEEN","seen")}</th>'
        '</tr></thead><tbody>' + "".join(body) + '</tbody></table></div>' + _storage_pager(values, total) + '</div>'
    )


def _storage_io_backend_table(conn, values, start_ts):
    sort_map = {
        "node": "s.node", "mount": "s.mount", "size": "s.size", "used": "s.used",
        "usepct": "s.use_percent", "read": "s.read_bps", "write": "s.write_bps",
        "readiops": "s.read_iops", "writeiops": "s.write_iops", "util": "s.util_percent", "seen": "s.last_seen",
    }
    if values["sort"] not in sort_map:
        values["sort"] = "writeiops"
    where = [
        "s.last_seen>=?",
        "EXISTS (SELECT 1 FROM vm_disk_current dx WHERE dx.node=s.node AND dx.mount=s.mount AND dx.role='customer')",
    ]
    params = [start_ts]
    if values["node"]:
        where.append("s.node=?")
        params.append(values["node"])
    if values["mount"]:
        where.append("s.mount=?")
        params.append(values["mount"])
    if values["q"]:
        pattern = like_pattern(values["q"])
        where.append("(s.node LIKE ? OR s.mount LIKE ? OR s.device LIKE ? OR s.block LIKE ? OR s.raid_level LIKE ? OR s.fstype LIKE ?)")
        params.extend([pattern] * 6)
    where_sql = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM node_storage_current s WHERE {where_sql}", params).fetchone()[0]
    pages = max(1, int(math.ceil(total / float(values["limit"]))))
    values["page"] = min(values["page"], pages)
    offset = (values["page"] - 1) * values["limit"]
    direction = "ASC" if values["order"] == "asc" else "DESC"
    rows = conn.execute(f"""
      SELECT s.node,s.mount,s.device,s.block,s.raid_level,s.fstype,s.size,s.used,s.avail,s.use_percent,
             s.read_bps,s.write_bps,s.read_iops,s.write_iops,s.util_percent,s.last_seen,
             (SELECT COUNT(*) FROM vm_disk_current d WHERE d.node=s.node AND d.mount=s.mount AND d.role='customer')
      FROM node_storage_current s
      WHERE {where_sql}
      ORDER BY {sort_map[values['sort']]} {direction}, s.node, s.mount
      LIMIT ? OFFSET ?
    """, params + [values["limit"], offset]).fetchall()
    body = []
    for row in rows:
        node,mount,device,block,raid,fs,size,used,avail,usep,rb,wb,ri,wi,util,seen,disk_count = row
        filter_href = _storage_io_url(values, view="disks", node=node, mount=mount, sort="writeiops", order="desc", page=1)
        body.append(
            '<tr>'
            f'<td><b>{escape(node)}</b></td>'
            f'<td class="storage-backend"><a href="{escape(filter_href, quote=True)}"><b>{escape(mount)}</b></a><span>{escape(device or "-")} · {escape(raid or "hardware/unknown RAID")} · {escape(fs or "-")}</span></td>'
            f'<td>{_disk_io_capacity(used, size, "used / size")}</td>'
            f'<td class="num">{_disk_io_rate(rb)}</td><td class="num"><b>{_disk_io_rate(wb)}</b></td>'
            f'<td class="num">{_disk_io_iops(ri)}</td><td class="num"><b>{_disk_io_iops(wi)}</b></td>'
            f'<td class="num"><b>{safe_float(util,0):.1f}%</b></td><td class="num">{disk_count}</td><td class="num"><small>{fmt_push(seen)}</small></td>'
            '</tr>'
        )
    if not body:
        body = ['<tr><td colspan="10" class="empty">No storage sample in this lookback</td></tr>']
    h = lambda label, key: _storage_sort_header(values, label, key)
    return (
        '<div class="card storage-table-card">'
        '<div class="table-title-row"><div><h3>Storage Backends</h3><div class="table-hint">Node mount/device load. Click a mount to filter the VM disk list for that storage.</div></div></div>'
        '<div class="table-wrap"><table class="storage-backend-table"><thead><tr>'
        f'<th>{h("NODE","node")}</th><th>{h("STORAGE","mount")}</th>'
        f'<th><div>USED / SIZE</div><small>{h("USED","used")} · {h("SIZE","size")} · {h("%","usepct")}</small></th>'
        f'<th>{h("READ","read")}</th><th>{h("WRITE","write")}</th><th>{h("R IOPS","readiops")}</th><th>{h("W IOPS","writeiops")}</th><th>{h("UTIL","util")}</th><th>VM DISKS</th><th>{h("SEEN","seen")}</th>'
        '</tr></thead><tbody>' + "".join(body) + '</tbody></table></div>' + _storage_pager(values, total) + '</div>'
    )


STORAGE_IO_CSS = r'''
<style id="storage-io-v48132">
.storage-hero{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}.storage-hero h2{margin:4px 0 6px}.storage-hero p{margin:0;color:var(--muted,#667085)}
.storage-tabs{display:flex;gap:8px;flex-wrap:wrap}.storage-tabs a,.storage-periods a{display:inline-flex;align-items:center;justify-content:center;padding:7px 11px;border:1px solid var(--line,#d0d5dd);border-radius:8px;text-decoration:none;font-size:12px;font-weight:800;color:inherit}.storage-tabs a.active,.storage-periods a.active{background:#1570ef;color:#fff;border-color:#1570ef}
.storage-periods{display:flex;gap:5px;flex-wrap:wrap}.storage-toolbar{display:grid;gap:14px}.storage-filter{display:grid;grid-template-columns:minmax(180px,1.2fr) minmax(145px,.8fr) minmax(145px,.8fr) 90px auto auto;gap:9px;align-items:end}.storage-filter label{display:grid;gap:5px;font-size:10px;font-weight:900;color:#667085}.storage-filter input,.storage-filter select{min-height:39px}.storage-filter button,.storage-filter .clear{min-height:39px;display:flex;align-items:center;justify-content:center}.storage-note{font-size:11px;color:#667085}
.storage-disk-table{min-width:1500px;table-layout:fixed}.storage-disk-table th:nth-child(1){width:280px}.storage-disk-table th:nth-child(2){width:365px}.storage-disk-table th:nth-child(3){width:265px}.storage-disk-table th:nth-child(n+4){width:135px}.storage-backend-table{min-width:1650px;table-layout:fixed}.storage-backend-table th:nth-child(1){width:220px}.storage-backend-table th:nth-child(2){width:310px}.storage-backend-table th:nth-child(3){width:265px}.storage-backend-table th:nth-child(n+4){width:130px}
.storage-sort{color:inherit;text-decoration:none;font-weight:900}.storage-sort.active{color:#1570ef}.storage-id b,.storage-id a,.storage-disk b,.storage-disk span,.storage-disk small,.storage-backend b,.storage-backend span{display:block}.storage-id a{margin-top:5px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px}.storage-disk span,.storage-backend span{margin-top:5px;font-size:10px;color:#667085}.storage-disk small{margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#98a2b3;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.storage-disk-table td,.storage-backend-table td{vertical-align:middle}.storage-disk-table td.num,.storage-backend-table td.num{text-align:right;white-space:nowrap}
.disk-capacity{min-width:220px}.disk-capacity>b{display:block;font-size:13px}.disk-capacity>b span{font-size:10px;color:#667085}.disk-cap-meter{height:6px;background:#e4e7ec;border-radius:999px;overflow:hidden;margin-top:8px}.disk-cap-meter i{display:block;height:100%;background:#12b76a;border-radius:inherit}.disk-capacity small{display:block;margin-top:5px;color:#667085;font-size:9px}.disk-cap-warm .disk-cap-meter i{background:#fdb022}.disk-cap-hot .disk-cap-meter i{background:#f79009}.disk-cap-critical .disk-cap-meter i{background:#f04438}
.storage-pager{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-top:14px;font-size:11px;color:#667085}.storage-pager>div:last-child{display:flex;gap:5px}.storage-pager a{padding:5px 8px;border:1px solid var(--line,#d0d5dd);border-radius:6px;text-decoration:none;color:inherit}.storage-pager a.active{background:#1570ef;color:#fff;border-color:#1570ef}
html[data-theme=dark] .storage-sort.active{color:#84adff}html[data-theme=dark] .disk-cap-meter{background:#334155}html[data-theme=dark] .storage-disk span,html[data-theme=dark] .storage-backend span,html[data-theme=dark] .storage-disk small,html[data-theme=dark] .storage-note{color:#94a3b8}
@media(max-width:1050px){.storage-filter{grid-template-columns:1fr 1fr}.storage-hero{display:block}.storage-tabs{margin-top:12px}}
</style>
'''


@app.route("/storage")
def storage_io_page():
    values = _storage_io_params()
    if values["view"] not in {"disks", "backends"}:
        values["view"] = "disks"
    start_ts, end_ts = range_for_period(values["period"])
    conn = db()
    try:
        ensure_disk_io_schema(conn)
        node_options, mount_options = _storage_filter_options(conn, values)
        if values["view"] == "backends":
            table = _storage_io_backend_table(conn, values, start_ts)
        else:
            table = _storage_io_disk_table(conn, values, start_ts)
    finally:
        conn.close()

    clear_href = url_for("storage_io_page", view=values["view"], period=values["period"])
    disk_tab = _storage_io_url(values, view="disks", sort="writeiops", order="desc", page=1)
    backend_tab = _storage_io_url(values, view="backends", sort="writeiops", order="desc", page=1)
    disk_active = "active" if values["view"] == "disks" else ""
    backend_active = "active" if values["view"] == "backends" else ""
    content = (
        STORAGE_IO_CSS
        + '<div class="card storage-hero"><div><span class="eyebrow">DISK MONITOR</span><h2>Storage I/O</h2><p>Find the busy node storage, then identify the exact VM disk causing throughput or IOPS load.</p></div>'
        + f'<div class="storage-tabs"><a class="{disk_active}" href="{escape(disk_tab, quote=True)}">VM Disks</a><a class="{backend_active}" href="{escape(backend_tab, quote=True)}">Storage Backends</a></div></div>'
        + '<div class="card storage-toolbar">'
        + f'<div><div class="label">Latest sample lookback</div><div class="storage-periods">{_storage_period_links(values)}</div></div>'
        + f'<form class="storage-filter" method="get" action="{url_for("storage_io_page")}">'
        + f'<input type="hidden" name="view" value="{escape(values["view"], quote=True)}"><input type="hidden" name="period" value="{escape(values["period"], quote=True)}"><input type="hidden" name="sort" value="{escape(values["sort"], quote=True)}"><input type="hidden" name="order" value="{escape(values["order"], quote=True)}">'
        + f'<label>SEARCH<input name="q" value="{escape(values["q"], quote=True)}" placeholder="Node / UUID / disk / path / mount"></label>'
        + f'<label>NODE<select name="node">{node_options}</select></label><label>STORAGE<select name="mount">{mount_options}</select></label>'
        + f'<label>ROWS<input name="limit" value="{values["limit"]}" inputmode="numeric"></label><button type="submit">Apply</button><a class="clear" href="{escape(clear_href, quote=True)}">Clear</a></form>'
        + f'<div class="storage-note">Selected window: <b>{escape(values["period"])}</b> · newest Agent samples received from <b>{fmt_full(start_ts)}</b> to <b>{fmt_full(end_ts)}</b>. Values are current sample rates, not a long-window average.</div>'
        + '</div>' + table
    )
    return page("Storage I/O", content)

# ---------------------------------------------------------------------------
