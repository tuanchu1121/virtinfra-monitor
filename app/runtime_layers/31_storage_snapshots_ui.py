
V48137_VERSION = "48.13.7"
V48137_BUILD = "r1"

import zlib

V48137_STORAGE_PAYLOAD_VERSION = 1
V48137_STORAGE_DEFAULT_ROWS = 30

def ensure_storage_snapshot_schema(conn):
    """Attach compact compressed Storage I/O payloads to retained node pushes.

    Retention already keeps node_push_snapshots at raw resolution for the first
    two days and hourly resolution through day seven.  Keeping the disk payload
    on the same row means Storage I/O follows the exact same bounded retention
    policy without creating tens of millions of per-disk history rows.
    """
    ensure_disk_io_schema(conn)
    ensure_column(conn, "node_push_snapshots", "storage_payload", "BLOB")
    ensure_column(conn, "node_push_snapshots", "storage_payload_version", "INTEGER NOT NULL DEFAULT 0")

def _v48137_pack_storage_payload(vms, node_host, data_time, interval_seconds):
    disks = []
    default_interval = max(1, safe_int(interval_seconds, CACHE_BUCKET_SECONDS))
    for vm in vms or []:
        if not isinstance(vm, dict):
            continue
        vm_uuid = str(vm.get("vm_uuid") or vm.get("uuid") or "").strip()
        if not vm_uuid:
            continue
        for disk in vm.get("disks") or []:
            if not isinstance(disk, dict):
                continue
            if str(disk.get("role") or "unknown").strip().lower() != "customer":
                continue
            target = str(disk.get("target") or "").strip()
            if not target:
                continue
            di = max(1, safe_int(disk.get("interval_seconds"), default_interval))
            disks.append([
                vm_uuid,
                target,
                str(disk.get("source") or ""),
                str(disk.get("mount") or ""),
                str(disk.get("storage_device") or ""),
                str(disk.get("storage_block") or ""),
                str(disk.get("storage_fstype") or ""),
                max(0, safe_int(disk.get("capacity_bytes"), 0)),
                max(0, safe_int(disk.get("allocation_bytes"), 0)),
                max(0, safe_int(disk.get("physical_bytes"), 0)),
                max(0, safe_int(disk.get("read_delta"), 0)) / float(di),
                max(0, safe_int(disk.get("write_delta"), 0)) / float(di),
                max(0, safe_int(disk.get("read_reqs_delta"), 0)) / float(di),
                max(0, safe_int(disk.get("write_reqs_delta"), 0)) / float(di),
            ])

    storages = []
    for storage in (node_host or {}).get("storage_devices") or []:
        if not isinstance(storage, dict):
            continue
        mount = str(storage.get("mount") or "").strip()
        if not mount:
            continue
        storages.append([
            mount,
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
        ])
    payload = {
        "v": V48137_STORAGE_PAYLOAD_VERSION,
        "t": safe_int(data_time, 0),
        "i": default_interval,
        "d": disks,
        "s": storages,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return dbapi.Binary(zlib.compress(raw, 3))

def _v48137_unpack_storage_payload(blob):
    if blob is None:
        return None
    try:
        raw = bytes(blob)
        data = json.loads(zlib.decompress(raw).decode("utf-8"))
        if not isinstance(data, dict) or safe_int(data.get("v"), 0) <= 0:
            return None
        return data
    except Exception:
        app.logger.exception("Could not decode retained Storage I/O payload")
        return None

def _v5054_selected_storage_payload(conn, node, period):
    """Return the exact retained Storage I/O payload for the selected node snapshot.

    Reads never create or alter schema. Historical pages must not silently overlay
    current disk rates when the selected retained payload is unavailable.
    """
    if "storage_payload" not in table_columns(conn, "node_push_snapshots"):
        return None, 0, 0
    selected_bucket, latest_bucket = resolve_snapshot_bucket(conn, period, node=node)
    if selected_bucket <= 0:
        return None, 0, latest_bucket
    row = conn.execute(
        """
        SELECT bucket, storage_payload
        FROM node_push_snapshots
        WHERE node=? AND bucket=? AND storage_payload IS NOT NULL
        LIMIT 1
        """,
        (node, selected_bucket),
    ).fetchone()
    if not row:
        return None, selected_bucket, latest_bucket
    payload = _v48137_unpack_storage_payload(row[1])
    return payload, safe_int(row[0], selected_bucket), latest_bucket

_ingest_disk_io_current_v48137_base = ingest_disk_io_current

def ingest_disk_io_current(conn, node, data_time, interval_seconds, vms, node_host):
    _ingest_disk_io_current_v48137_base(conn, node, data_time, interval_seconds, vms, node_host)
    ensure_storage_snapshot_schema(conn)
    try:
        payload = _v48137_pack_storage_payload(vms, node_host, data_time, interval_seconds)
        conn.execute(
            """
            UPDATE node_push_snapshots
               SET storage_payload=?, storage_payload_version=?
             WHERE node=? AND bucket=?
            """,
            (payload, V48137_STORAGE_PAYLOAD_VERSION, node, bucket_for(data_time)),
        )
    except Exception:
        # Never reject an Agent push merely because the optional retained disk
        # payload could not be serialized. Current metrics remain available.
        app.logger.exception("Could not retain Storage I/O snapshot for %s", node)

def _v48137_storage_target(conn, values):
    """Resolve Storage I/O to the same retained snapshot semantics as Top VM.

    - 5m without a custom time is the fast live/current path.
    - 10m..7d select the retained point at that age from the newest real push.
    - `at=` selects the nearest retained point at or before that exact time.
    """
    ensure_storage_snapshot_schema(conn)
    requested_at = _request_target_ts()
    node = str(values.get("node") or "").strip()
    where = ["storage_payload IS NOT NULL"]
    params = []
    if node:
        where.append("node=?")
        params.append(node)
    where_sql = " AND ".join(where)
    latest_row = conn.execute(
        f"SELECT MAX(bucket) FROM node_push_snapshots WHERE {where_sql}", params
    ).fetchone()
    latest = safe_int((latest_row or [0])[0], 0)
    if latest <= 0:
        return {
            "mode": "history" if requested_at is not None or values.get("period") != "5m" else "live",
            "latest": 0,
            "target": 0,
            "requested_at": requested_at,
        }
    if requested_at is not None:
        target = bucket_for(requested_at)
    else:
        target = latest - max(0, period_seconds(clean_period(values.get("period") or "5m")) - CACHE_BUCKET_SECONDS)
    selected_row = conn.execute(
        f"SELECT MAX(bucket) FROM node_push_snapshots WHERE {where_sql} AND bucket<=?",
        params + [target],
    ).fetchone()
    selected = safe_int((selected_row or [0])[0], 0)
    if selected <= 0:
        oldest_row = conn.execute(
            f"SELECT MIN(bucket) FROM node_push_snapshots WHERE {where_sql}", params
        ).fetchone()
        selected = safe_int((oldest_row or [0])[0], 0)
    live = requested_at is None and clean_period(values.get("period") or "5m") == "5m"
    return {
        "mode": "live" if live else "history",
        "latest": latest,
        "target": selected,
        "requested_at": requested_at,
    }

def _v48137_snapshot_payload_rows(conn, values, target_bucket):
    if target_bucket <= 0:
        return []
    node = str(values.get("node") or "").strip()
    where = ["storage_payload IS NOT NULL", "bucket<=?"]
    params = [target_bucket]
    if node:
        where.append("node=?")
        params.append(node)
    where_sql = " AND ".join(where)
    return conn.execute(
        f"""
        WITH picked AS (
          SELECT node,MAX(bucket) AS bucket
            FROM node_push_snapshots
           WHERE {where_sql}
           GROUP BY node
        )
        SELECT s.node,s.bucket,s.push_time,s.storage_payload
          FROM node_push_snapshots s
          JOIN picked p ON p.node=s.node AND p.bucket=s.bucket
         ORDER BY s.node COLLATE NOCASE
        """,
        params,
    ).fetchall()

def _v48137_create_snapshot_shadow_tables(conn, payload_rows):
    """Shadow the two current tables with request-local TEMP snapshot tables."""
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("DROP TABLE IF EXISTS temp.vm_disk_current")
    conn.execute("DROP TABLE IF EXISTS temp.node_storage_current")
    conn.executescript(
        """
        CREATE TEMP TABLE vm_disk_current (
          node TEXT NOT NULL, vm_uuid TEXT NOT NULL, target TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT 'customer',
          mount TEXT NOT NULL DEFAULT '', storage_device TEXT NOT NULL DEFAULT '',
          storage_block TEXT NOT NULL DEFAULT '', storage_fstype TEXT NOT NULL DEFAULT '',
          capacity_bytes INTEGER NOT NULL DEFAULT 0, allocation_bytes INTEGER NOT NULL DEFAULT 0,
          physical_bytes INTEGER NOT NULL DEFAULT 0, interval_seconds INTEGER NOT NULL DEFAULT 300,
          read_bps REAL NOT NULL DEFAULT 0, write_bps REAL NOT NULL DEFAULT 0,
          read_iops REAL NOT NULL DEFAULT 0, write_iops REAL NOT NULL DEFAULT 0,
          last_seen INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX temp.idx_v48137_disk_node_vm ON vm_disk_current(node,vm_uuid);
        CREATE INDEX temp.idx_v48137_disk_mount ON vm_disk_current(node,mount);
        CREATE TEMP TABLE node_storage_current (
          node TEXT NOT NULL, mount TEXT NOT NULL, device TEXT NOT NULL DEFAULT '',
          block TEXT NOT NULL DEFAULT '', raid_level TEXT NOT NULL DEFAULT '',
          fstype TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0,
          used INTEGER NOT NULL DEFAULT 0, avail INTEGER NOT NULL DEFAULT 0,
          use_percent REAL NOT NULL DEFAULT 0, read_bps REAL NOT NULL DEFAULT 0,
          write_bps REAL NOT NULL DEFAULT 0, read_iops REAL NOT NULL DEFAULT 0,
          write_iops REAL NOT NULL DEFAULT 0, util_percent REAL NOT NULL DEFAULT 0,
          last_seen INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX temp.idx_v48137_storage_node_mount ON node_storage_current(node,mount);
        """
    )
    disk_rows = []
    storage_rows = []
    min_seen = 0
    max_seen = 0
    for node, _bucket, push_time, blob in payload_rows:
        data = _v48137_unpack_storage_payload(blob)
        if not data:
            continue
        seen = safe_int(data.get("t"), safe_int(push_time, 0))
        interval = max(1, safe_int(data.get("i"), CACHE_BUCKET_SECONDS))
        min_seen = seen if min_seen <= 0 else min(min_seen, seen)
        max_seen = max(max_seen, seen)
        for row in data.get("d") or []:
            if not isinstance(row, list) or len(row) < 14:
                continue
            disk_rows.append((
                node, str(row[0] or ""), str(row[1] or ""), str(row[2] or ""), "customer",
                str(row[3] or ""), str(row[4] or ""), str(row[5] or ""), str(row[6] or ""),
                max(0, safe_int(row[7], 0)), max(0, safe_int(row[8], 0)), max(0, safe_int(row[9], 0)),
                interval, max(0.0, safe_float(row[10], 0.0)), max(0.0, safe_float(row[11], 0.0)),
                max(0.0, safe_float(row[12], 0.0)), max(0.0, safe_float(row[13], 0.0)), seen,
            ))
        for row in data.get("s") or []:
            if not isinstance(row, list) or len(row) < 14:
                continue
            storage_rows.append((
                node, str(row[0] or ""), str(row[1] or ""), str(row[2] or ""), str(row[3] or ""),
                str(row[4] or ""), max(0, safe_int(row[5], 0)), max(0, safe_int(row[6], 0)),
                max(0, safe_int(row[7], 0)), max(0.0, safe_float(row[8], 0.0)),
                max(0.0, safe_float(row[9], 0.0)), max(0.0, safe_float(row[10], 0.0)),
                max(0.0, safe_float(row[11], 0.0)), max(0.0, safe_float(row[12], 0.0)),
                max(0.0, safe_float(row[13], 0.0)), seen,
            ))
    if disk_rows:
        conn.executemany(
            """
            INSERT INTO temp.vm_disk_current(
              node,vm_uuid,target,source,role,mount,storage_device,storage_block,storage_fstype,
              capacity_bytes,allocation_bytes,physical_bytes,interval_seconds,
              read_bps,write_bps,read_iops,write_iops,last_seen
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            disk_rows,
        )
    if storage_rows:
        conn.executemany(
            """
            INSERT INTO temp.node_storage_current(
              node,mount,device,block,raid_level,fstype,size,used,avail,use_percent,
              read_bps,write_bps,read_iops,write_iops,util_percent,last_seen
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            storage_rows,
        )
    return {"nodes": len(payload_rows), "disks": len(disk_rows), "storages": len(storage_rows), "min_seen": min_seen, "max_seen": max_seen}

_storage_io_params_v48137_base = _storage_io_params

def _storage_io_params(**updates):
    values = _storage_io_params_v48137_base(**updates)
    values["at"] = (request.args.get("at") or "").strip()
    if request.args.get("limit") is None and "limit" not in updates:
        values["limit"] = V48137_STORAGE_DEFAULT_ROWS
    values["limit"] = max(10, min(200, safe_int(values.get("limit"), V48137_STORAGE_DEFAULT_ROWS)))
    values.update(updates)
    return values

def _v48137_storage_filter_options(conn, values):
    nodes = [r[0] for r in conn.execute(
        """
        SELECT DISTINCT node FROM (
          SELECT node FROM vm_disk_current WHERE role='customer'
          UNION ALL SELECT node FROM node_storage_current
        ) ORDER BY node COLLATE NOCASE
        """
    ).fetchall()]
    mount_params = []
    mount_where = ""
    if values.get("node"):
        mount_where = " WHERE node=?"
        mount_params.append(values["node"])
    # Outer DISTINCT is required. The same /, /boot or /home mount exists on
    # many nodes and should appear only once in the dropdown.
    mounts = [r[0] for r in conn.execute(
        f"""
        SELECT DISTINCT mount FROM (
          SELECT node,mount FROM vm_disk_current WHERE role='customer' AND mount!=''
          UNION ALL SELECT node,mount FROM node_storage_current WHERE mount!=''
        ){mount_where}
        ORDER BY mount COLLATE NOCASE
        """,
        mount_params,
    ).fetchall()]
    node_options = ['<option value="">All nodes</option>']
    for item in nodes:
        selected = " selected" if item == values.get("node") else ""
        node_options.append(f'<option value="{escape(item,quote=True)}"{selected}>{escape(item)}</option>')
    mount_options = ['<option value="">All storage</option>']
    for item in mounts:
        selected = " selected" if item == values.get("mount") else ""
        mount_options.append(f'<option value="{escape(item,quote=True)}"{selected}>{escape(item)}</option>')
    return "".join(node_options), "".join(mount_options)

# Keep the public helper name used by the route.
_storage_filter_options = _v48137_storage_filter_options
_v48133_storage_filter_options = _v48137_storage_filter_options

def _storage_period_links(values):
    """Age buttons are an alternative to custom time, so they clear `at`."""
    links = []
    custom_active = bool(values.get("at"))
    for key in PERIODS:
        label = PERIOD_LABELS.get(key, key)
        cls = "active" if (not custom_active and key == values.get("period")) else ""
        href = _storage_io_url(values, period=key, at="", page=1)
        links.append(f'<a class="{cls}" href="{escape(href,quote=True)}">{escape(label)}</a>')
    return "".join(links)

def _v48137_sort_bar(values, options):
    links = []
    for label, key in options:
        active = values.get("sort") == key
        next_order = "asc" if active and values.get("order") == "desc" else "desc"
        arrow = " ↓" if active and values.get("order") == "desc" else (" ↑" if active else "")
        href = _storage_io_url(values, sort=key, order=next_order, page=1)
        links.append(f'<a class="{"active" if active else ""}" href="{escape(href,quote=True)}">{escape(label)}{arrow}</a>')
    return '<div class="storage-card-sort"><span>SORT</span>' + "".join(links) + "</div>"

V48137_STORAGE_CSS = r'''
<style id="v48137-storage-history-cards">
.storage-history-state{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.storage-history-state span{padding:5px 9px;border:1px solid #d0d5dd;border-radius:999px;font-size:10px;font-weight:850}.storage-history-state .live{background:#ecfdf3;border-color:#abefc6;color:#067647}.storage-history-state .history{background:#eff8ff;border-color:#b2ddff;color:#175cd3}
.storage-time-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(360px,.72fr);gap:14px;align-items:start}.storage-time-grid .custom-time-card{margin:0;padding:14px}.storage-time-grid .custom-time-card h3{font-size:13px}.storage-time-grid .custom-time-form{margin-top:9px}.storage-time-grid .table-hint{font-size:9px}.storage-period-title{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:8px}.storage-period-title small{color:#667085}
.storage-card-sort{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.storage-card-sort>span{font-size:9px;font-weight:950;color:#667085;margin-right:2px}.storage-card-sort a{padding:5px 8px;border:1px solid #d0d5dd;border-radius:7px;text-decoration:none;color:inherit;font-size:10px;font-weight:850;background:#fff}.storage-card-sort a.active{background:#1570ef;border-color:#1570ef;color:#fff}
.storage-card-list{display:grid;gap:12px}.storage-vm-card,.storage-node-card{border:1px solid #dbe3ef;border-radius:14px;background:#fff;overflow:hidden;box-shadow:0 1px 2px rgba(16,24,40,.04)}.storage-card-head{display:grid;grid-template-columns:minmax(190px,.7fr) minmax(300px,1.15fr) minmax(310px,1fr);gap:16px;align-items:center;padding:13px 15px;background:#f8fafc;border-bottom:1px solid #e4e7ec}.storage-card-node>a,.storage-card-uuid>a{font-weight:900}.storage-card-node small,.storage-card-uuid small{display:block;margin-top:5px;color:#667085;font-size:9px}.storage-card-node .storage-node-ip{display:flex}.storage-card-uuid .uuid-cell{display:flex;gap:7px;align-items:center}.storage-card-uuid .uuid-cell>a{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.storage-card-summary{display:grid;grid-template-columns:minmax(190px,1.4fr) repeat(4,minmax(58px,.55fr));gap:8px;align-items:center}.storage-card-summary .disk-capacity{min-width:0}.storage-summary-metric{padding-left:8px;border-left:1px solid #d0d5dd;min-width:0}.storage-summary-metric span{display:block;font-size:8px;font-weight:900;color:#667085}.storage-summary-metric b{display:block;margin-top:3px;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.storage-card-body{padding:12px 15px}.storage-disk-grid,.storage-mount-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.storage-disk-grid .storage-child-item,.storage-mount-grid .storage-child-item{grid-template-columns:minmax(170px,1.15fr) minmax(170px,.9fr);align-items:start}.storage-disk-grid .storage-child-metrics,.storage-mount-grid .storage-child-metrics{grid-column:1/-1}.storage-disk-grid .storage-child-footer{grid-column:1/-1}.storage-node-card .storage-card-head{grid-template-columns:minmax(220px,.8fr) minmax(0,1.5fr)}.storage-node-card .storage-card-summary{grid-template-columns:minmax(210px,1.25fr) repeat(5,minmax(58px,.5fr))}.storage-card-empty{padding:28px;text-align:center;color:#667085}
.storage-snapshot-note{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;padding:9px 11px;border-radius:9px;background:#f8fafc;border:1px solid #e4e7ec;font-size:10px;color:#475467}.storage-snapshot-note b{color:#101828}.storage-snapshot-note .warn{color:#b54708}
.storage-filter select,.storage-search-bar select{max-height:42px}.storage-rows-select{min-height:39px}
html[data-theme=dark] .storage-vm-card,html[data-theme=dark] .storage-node-card,html[data-theme=dark] .storage-card-sort a{background:#0f1b2c;border-color:#31445e}html[data-theme=dark] .storage-card-head,html[data-theme=dark] .storage-snapshot-note{background:#101d30;border-color:#31445e}html[data-theme=dark] .storage-card-node small,html[data-theme=dark] .storage-card-uuid small,html[data-theme=dark] .storage-summary-metric span,html[data-theme=dark] .storage-period-title small,html[data-theme=dark] .storage-card-sort>span,html[data-theme=dark] .storage-snapshot-note{color:#9fb0c4}html[data-theme=dark] .storage-summary-metric{border-left-color:#31445e}html[data-theme=dark] .storage-snapshot-note b{color:#e5edf7}
@media(max-width:1450px){.storage-card-head{grid-template-columns:190px minmax(260px,1fr);}.storage-card-summary{grid-column:1/-1}.storage-node-card .storage-card-head{grid-template-columns:1fr}.storage-node-card .storage-card-summary{grid-column:1}.storage-time-grid{grid-template-columns:1fr}}
@media(max-width:980px){.storage-disk-grid,.storage-mount-grid{grid-template-columns:1fr}.storage-card-head{grid-template-columns:1fr}.storage-card-summary,.storage-node-card .storage-card-summary{grid-template-columns:1fr 1fr}.storage-card-summary .disk-capacity{grid-column:1/-1}}
</style>
'''

def _v48137_summary_metrics(allocated, assigned, rb, wb, ri, wi, label="allocated / assigned"):
    return f'''
      <div class="storage-card-summary">
        {_disk_io_capacity(allocated, assigned, label)}
        <div class="storage-summary-metric"><span>READ</span><b>{_disk_io_rate(rb)}</b></div>
        <div class="storage-summary-metric"><span>WRITE</span><b>{_disk_io_rate(wb)}</b></div>
        <div class="storage-summary-metric"><span>R IOPS</span><b>{_disk_io_iops(ri)}</b></div>
        <div class="storage-summary-metric"><span>W IOPS</span><b>{_disk_io_iops(wi)}</b></div>
      </div>'''

def _v48137_storage_disk_group_cards(conn, values, start_ts):
    groups, details, total = _v48133_storage_disk_groups(conn, values, start_ts)
    cards = []
    for node, vm_uuid, public_ip, disk_count, assigned, allocated, rb, wb, ri, wi, seen in groups:
        ip = compact_ipv4(public_ip)
        node_href = url_for("node_page", node=node, period=values["period"], q=vm_uuid, **({"at": values.get("at")} if values.get("at") else {}))
        vm_href = url_for("vm_page", node=node, vm_uuid=vm_uuid, period=values["period"], **({"at": values.get("at")} if values.get("at") else {}))
        ip_line = f'<span class="storage-node-ip">{escape(ip)}<button type="button" class="copy-btn" data-copy="{escape(ip)}" title="Copy IP">⧉</button></span>' if ip else ''
        child_html = ''.join(_v48136_disk_child_html(node, vm_uuid, r, values["period"]) for r in details.get((str(node), str(vm_uuid)), []))
        cards.append(f'''
        <article class="storage-vm-card">
          <div class="storage-card-head">
            <div class="storage-card-node"><a href="{escape(node_href,quote=True)}">{escape(node)}</a>{ip_line}<small>{safe_int(disk_count,0)} customer disk{'s' if safe_int(disk_count,0)!=1 else ''}</small></div>
            <div class="storage-card-uuid"><span class="uuid-cell"><a href="{escape(vm_href,quote=True)}" title="{escape(vm_uuid,quote=True)}">{escape(vm_uuid)}</a><button type="button" class="copy-btn" data-copy="{escape(vm_uuid)}" title="Copy UUID">⧉</button></span><small>Latest sample {fmt_push(seen)}</small></div>
            {_v48137_summary_metrics(allocated,assigned,rb,wb,ri,wi)}
          </div>
          <div class="storage-card-body"><div class="storage-disk-grid">{child_html}</div></div>
        </article>''')
    if not cards:
        cards = ['<div class="storage-card-empty">No customer disk sample at this snapshot.</div>']
    sort_bar = _v48137_sort_bar(values, [
        ("W IOPS","writeiops"),("WRITE","write"),("R IOPS","readiops"),("READ","read"),
        ("ALLOC","allocated"),("ASSIGNED","assigned"),("%","allocpct"),("DISKS","diskcount"),("NODE","node"),("UUID","uuid"),
    ])
    return f'''
    {V48136_STORAGE_CSS}{V48137_STORAGE_CSS}
    <div class="card storage-table-card">
      <div class="table-title-row"><div><h3>VM Disks</h3><div class="table-hint">One VM card, every customer disk nested under its UUID. Select a storage mount for one-disk-per-row forensic comparison.</div></div>{sort_bar}</div>
      <div class="storage-card-list">{''.join(cards)}</div>{_storage_pager(values,total)}
    </div>'''

def _v48137_storage_node_group_cards(conn, values, start_ts):
    rows = _v48136_real_storage_rows(conn, values, start_ts)
    grouped = {}
    for row in rows:
        grouped.setdefault(str(row[0]), []).append(row)
    count_map = {str(r[0]): (safe_int(r[1],0), safe_int(r[2],0)) for r in conn.execute(
        "SELECT node,COUNT(DISTINCT vm_uuid),COUNT(*) FROM vm_disk_current WHERE role='customer' GROUP BY node"
    ).fetchall()}
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
        vm_count, disk_count = count_map.get(node, (0, 0))
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
    cards = []
    for node, ip, mounts, size, used, rb, wb, ri, wi, util, seen, disk_count, vm_count in groups:
        node_href = url_for("node_page", node=node, period=values["period"], **({"at": values.get("at")} if values.get("at") else {}))
        ip_line = f'<span class="storage-node-ip">{escape(ip)}<button type="button" class="copy-btn" data-copy="{escape(ip)}" title="Copy IP">⧉</button></span>' if ip else ''
        children = ''.join(_v48136_node_mount_child(values, row) for row in mounts)
        node_summary = f'''
          <div class="storage-card-summary">
            {_disk_io_capacity(used,size,'total used / size')}
            <div class="storage-summary-metric"><span>READ</span><b>{_disk_io_rate(rb)}</b></div>
            <div class="storage-summary-metric"><span>WRITE</span><b>{_disk_io_rate(wb)}</b></div>
            <div class="storage-summary-metric"><span>R IOPS</span><b>{_disk_io_iops(ri)}</b></div>
            <div class="storage-summary-metric"><span>W IOPS</span><b>{_disk_io_iops(wi)}</b></div>
            <div class="storage-summary-metric"><span>HOT UTIL</span><b>{util:.1f}%</b></div>
          </div>'''
        cards.append(f'''
        <article class="storage-node-card">
          <div class="storage-card-head">
            <div class="storage-card-node"><a href="{escape(node_href,quote=True)}">{escape(node)}</a>{ip_line}<small>{len(mounts)} filesystems · {vm_count} VMs · {disk_count} disks · seen {fmt_push(seen)}</small></div>
            {node_summary}
          </div>
          <div class="storage-card-body"><div class="storage-mount-grid">{children}</div></div>
        </article>''')
    if not cards:
        cards = ['<div class="storage-card-empty">No real node storage sample at this snapshot.</div>']
    sort_bar = _v48137_sort_bar(values, [
        ("W IOPS","writeiops"),("WRITE","write"),("R IOPS","readiops"),("READ","read"),
        ("UTIL","util"),("USED","used"),("SIZE","size"),("%","usepct"),("NODE","node"),
    ])
    return f'''
    {V48136_STORAGE_CSS}{V48137_STORAGE_CSS}
    <div class="card storage-table-card">
      <div class="table-title-row"><div><h3>Storage Node</h3><div class="table-hint">One node card with every real filesystem root inside. Select a mount for direct cross-node comparison.</div></div>{sort_bar}</div>
      <div class="storage-card-list">{''.join(cards)}</div>{_storage_pager(values,total)}
    </div>'''

_v48137_storage_disk_filtered_base = _v48136_storage_disk_filtered_base
_v48137_storage_node_filtered_base = _v48136_storage_node_filtered_base

def _v48133_storage_disk_table(conn, values, start_ts):
    if not str(values.get("mount") or "").strip():
        return _v48137_storage_disk_group_cards(conn, values, start_ts)
    filtered = _v48137_storage_disk_filtered_base(conn, values, start_ts)
    clear_mount = _storage_io_url(values, mount="", page=1)
    return (
        V48136_STORAGE_CSS + V48137_STORAGE_CSS
        + f'<div class="storage-filtered-banner"><div><b>FILTERED STORAGE: {escape(values.get("mount") or "-")}</b><span> · one matching virtual disk per row for direct I/O comparison</span></div><a href="{escape(clear_mount,quote=True)}">Back to grouped All view</a></div>'
        + filtered
    )

def _v48133_storage_node_table(conn, values, start_ts):
    if not str(values.get("mount") or "").strip():
        return _v48137_storage_node_group_cards(conn, values, start_ts)
    filtered = _v48137_storage_node_filtered_base(conn, values, start_ts)
    clear_mount = _storage_io_url(values, mount="", page=1)
    return (
        V48136_STORAGE_CSS + V48137_STORAGE_CSS
        + f'<div class="storage-filtered-banner"><div><b>FILTERED FILESYSTEM: {escape(values.get("mount") or "-")}</b><span> · matching node mount rows</span></div><a href="{escape(clear_mount,quote=True)}">Back to grouped All view</a></div>'
        + filtered
    )

def _v48137_storage_snapshot_note(snapshot, stats):
    if snapshot["mode"] == "live":
        return (
            '<div class="storage-snapshot-note"><div><b>LIVE CURRENT</b> · newest current tables for the fastest page load.</div>'
            f'<div>Latest retained push <b>{fmt_full(snapshot["latest"]) if snapshot["latest"] else "N/A"}</b></div></div>'
        )
    target = snapshot.get("target") or 0
    if not stats.get("nodes"):
        return (
            '<div class="storage-snapshot-note"><div class="warn"><b>NO RETAINED STORAGE PAYLOAD AT THIS TIME</b> · history starts after v48.13.7 receives new Agent pushes.</div>'
            f'<div>Requested retained point <b>{fmt_full(target) if target else "N/A"}</b></div></div>'
        )
    return (
        '<div class="storage-snapshot-note"><div><b>RETAINED SNAPSHOT</b> · nearest real Agent push at or before the selected point, not current data.</div>'
        f'<div>Requested <b>{fmt_full(target)}</b> · actual node samples <b>{fmt_full(stats.get("min_seen"))}</b> to <b>{fmt_full(stats.get("max_seen"))}</b> · {stats.get("nodes",0)} nodes</div></div>'
    )

def storage_io_page_v48137():
    values = _storage_io_params()
    if values["view"] not in {"disks", "nodes", "backends"}:
        values["view"] = "disks"
    if values["view"] == "backends":
        values["view"] = "nodes"
    conn = db()
    snapshot = None
    stats = {"nodes": 0, "disks": 0, "storages": 0, "min_seen": 0, "max_seen": 0}
    try:
        ensure_storage_snapshot_schema(conn)
        snapshot = _v48137_storage_target(conn, values)
        if snapshot["mode"] == "history":
            payload_rows = _v48137_snapshot_payload_rows(conn, values, snapshot["target"])
            stats = _v48137_create_snapshot_shadow_tables(conn, payload_rows)
            start_ts = 0
        else:
            start_ts = now_ts() - max(CACHE_BUCKET_SECONDS * 2, period_seconds("5m"))
        node_options, mount_options = _v48137_storage_filter_options(conn, values)
        if values["view"] == "nodes":
            table = _v48133_storage_node_table(conn, values, start_ts)
        else:
            table = _v48133_storage_disk_table(conn, values, start_ts)
    finally:
        conn.close()

    at_value = values.get("at") or ""
    clear_kwargs = {"view": values["view"], "period": values["period"], "limit": values["limit"]}
    if at_value:
        clear_kwargs["at"] = at_value
    clear_href = url_for("storage_io_page", **clear_kwargs)
    disk_tab = _storage_io_url(values, view="disks", sort="writeiops", order="desc", page=1)
    node_tab = _storage_io_url(values, view="nodes", sort="writeiops", order="desc", page=1)
    disk_active = "active" if values["view"] == "disks" else ""
    node_active = "active" if values["view"] == "nodes" else ""
    target_ts = _request_target_ts()
    time_card = _custom_snapshot_control(
        "storage_io_page", target_ts, title="Custom Snapshot Time",
        view=values["view"], period="5m", q=values["q"] or None,
        node=values["node"] or None, mount=values["mount"] or None,
        sort=values["sort"], order=values["order"], limit=values["limit"], page=1,
    )
    history_class = "live" if snapshot and snapshot["mode"] == "live" else "history"
    history_label = "LIVE" if history_class == "live" else "HISTORICAL"
    hidden_at = f'<input type="hidden" name="at" value="{escape(at_value,quote=True)}">' if at_value else ""
    row_options = "".join(
        f'<option value="{n}"{" selected" if values["limit"]==n else ""}>{n}</option>' for n in (10, 20, 30, 50, 100, 200)
    )
    content = (
        V48137_STORAGE_CSS
        + '<div class="card storage-hero"><div><span class="eyebrow">DISK MONITOR</span><h2>Storage I/O</h2><p>Use snapshot age or an exact time, then drill from node storage to the VM and disk causing load.</p></div>'
        + f'<div><div class="storage-tabs"><a class="{disk_active}" href="{escape(disk_tab,quote=True)}">VM Disks</a><a class="{node_active}" href="{escape(node_tab,quote=True)}">Storage Node</a></div><div class="storage-history-state"><span class="{history_class}">{history_label}</span></div></div></div>'
        + '<div class="card storage-toolbar">'
        + '<div class="storage-time-grid"><div>'
        + f'<div class="storage-period-title"><div><div class="label">SNAPSHOT AGE</div><small>5m is live. 10m–7d open the retained point at that age.</small></div></div><div class="storage-periods">{_storage_period_links(values)}</div>'
        + '</div>' + time_card + '</div>'
        + f'<form class="storage-search-bar" method="get" action="{url_for("storage_io_page")}">'
        + f'<input type="hidden" name="view" value="{escape(values["view"],quote=True)}"><input type="hidden" name="period" value="{escape(values["period"],quote=True)}"><input type="hidden" name="sort" value="{escape(values["sort"],quote=True)}"><input type="hidden" name="order" value="{escape(values["order"],quote=True)}">{hidden_at}'
        + f'<label class="storage-search-wrap">SEARCH<input class="storage-search-input" name="q" value="{escape(values["q"],quote=True)}" placeholder="Search node, IP, UUID, disk, path or mount"></label>'
        + f'<label>NODE<select name="node">{node_options}</select></label><label>STORAGE<select name="mount">{mount_options}</select></label>'
        + f'<label>ROWS<select class="storage-rows-select" name="limit">{row_options}</select></label><button type="submit">Search</button><a class="clear" href="{escape(clear_href,quote=True)}">Clear</a></form>'
        + _v48137_storage_snapshot_note(snapshot or {"mode":"live","latest":0,"target":0}, stats)
        + '</div>' + table
    )
    return page("Storage I/O", content)

app.view_functions["storage_io_page"] = storage_io_page_v48137

_purge_vm_data_v48137_base = purge_vm_data

def _v48137_scrub_uuid_from_storage_snapshots(conn, vm_uuid, nodes):
    ensure_storage_snapshot_schema(conn)
    nodes = sorted({str(n or "").strip() for n in nodes if str(n or "").strip()})
    if not nodes:
        return 0
    changed = 0
    placeholders = ",".join("?" for _ in nodes)
    rows = conn.execute(
        f"SELECT node,bucket,storage_payload FROM node_push_snapshots WHERE node IN ({placeholders}) AND storage_payload IS NOT NULL",
        nodes,
    ).fetchall()
    for node, bucket, blob in rows:
        data = _v48137_unpack_storage_payload(blob)
        if not data:
            continue
        old = data.get("d") or []
        new = [r for r in old if not (isinstance(r, list) and r and str(r[0]) == vm_uuid)]
        if len(new) == len(old):
            continue
        data["d"] = new
        packed = dbapi.Binary(zlib.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 3))
        conn.execute(
            "UPDATE node_push_snapshots SET storage_payload=? WHERE node=? AND bucket=?",
            (packed, node, bucket),
        )
        changed += 1
    return changed

def purge_vm_data(conn, node, vm_uuid, refresh_snapshots=True):
    vm_uuid = str(vm_uuid or "").strip()
    nodes = {str(node or "").strip()} if str(node or "").strip() else set()
    try:
        for row in conn.execute(
            """
            SELECT node FROM vm_node_presence WHERE vm_uuid=?
            UNION SELECT node FROM vm_inventory WHERE vm_uuid=?
            UNION SELECT old_node FROM vm_migration_events WHERE vm_uuid=?
            UNION SELECT new_node FROM vm_migration_events WHERE vm_uuid=?
            """,
            (vm_uuid, vm_uuid, vm_uuid, vm_uuid),
        ).fetchall():
            if row and row[0]:
                nodes.add(str(row[0]))
    except Exception:
        pass
    deleted = _purge_vm_data_v48137_base(conn, node, vm_uuid, refresh_snapshots=refresh_snapshots)
    deleted["storage_snapshot_payloads"] = _v48137_scrub_uuid_from_storage_snapshots(conn, vm_uuid, nodes)
    return deleted

V48138_VERSION = "48.13.8"
V48138_BUILD = "r1"

V48138_STORAGE_CSS = r'''
<style id="v48138-storage-identity-controls">
/* Reuse the exact visual language of Top VM for lookback/search controls. */
.storage-top-card{display:grid;gap:12px}.storage-top-card .top-grid{grid-template-columns:repeat(3,minmax(180px,1fr))}.storage-top-card .periods{margin-top:4px}.storage-top-card .search{display:grid;grid-template-columns:minmax(320px,1fr) minmax(150px,.34fr) minmax(170px,.38fr) minmax(105px,.18fr) auto auto;gap:8px;align-items:center}.storage-top-card .search input,.storage-top-card .search select{min-height:39px}.storage-top-card .search .clear{min-height:39px;display:flex;align-items:center;justify-content:center}.storage-top-card .storage-toolbar-state{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.storage-top-card .storage-toolbar-state span{padding:4px 8px;border:1px solid #d0d5dd;border-radius:999px;font-size:9px;font-weight:900}.storage-top-card .storage-toolbar-state .live{background:#ecfdf3;border-color:#abefc6;color:#067647}.storage-top-card .storage-toolbar-state .history{background:#eff8ff;border-color:#b2ddff;color:#175cd3}
/* UUID is the primary identity. Node/IP are compact supporting metadata. */
.storage-vm-card .storage-card-head{grid-template-columns:minmax(390px,.86fr) minmax(620px,1.4fr);gap:18px;padding:14px 16px}.storage-vm-identity{min-width:0}.storage-vm-identity .identity-kicker{display:block;font-size:8px;font-weight:950;letter-spacing:.08em;color:#667085}.storage-vm-identity .identity-uuid{display:flex;align-items:center;gap:7px;min-width:0;margin-top:4px}.storage-vm-identity .identity-uuid>a{display:block;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;font-weight:900}.storage-vm-identity .identity-node{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:7px;font-size:9px;color:#667085}.storage-vm-identity .identity-node>a{font-weight:900}.storage-vm-identity .identity-node .storage-node-ip{display:inline-flex;align-items:center;gap:4px}.storage-vm-identity .identity-foot{display:block;margin-top:5px;font-size:8.5px;color:#98a2b3}.storage-vm-card .storage-card-summary{grid-template-columns:minmax(230px,1.45fr) repeat(4,minmax(70px,.52fr));gap:9px}.storage-vm-card .storage-card-summary .disk-capacity>b{font-size:12px}.storage-vm-card .storage-card-summary .disk-cap-meter,.storage-vm-card .storage-child-cap .disk-cap-meter{display:block!important;height:7px!important;margin-top:7px!important;background:#e4e7ec!important;border-radius:999px!important;overflow:hidden!important}.storage-vm-card .storage-card-summary .disk-cap-meter i,.storage-vm-card .storage-child-cap .disk-cap-meter i{display:block!important;height:100%!important;border-radius:inherit!important;background:#12b76a!important}.storage-vm-card .disk-cap-warm .disk-cap-meter i{background:#fdb022!important}.storage-vm-card .disk-cap-hot .disk-cap-meter i{background:#f79009!important}.storage-vm-card .disk-cap-critical .disk-cap-meter i{background:#f04438!important}.storage-vm-card .storage-summary-metric b{font-size:11px}.storage-vm-card .storage-card-body{padding:12px 16px 15px}.storage-vm-card .storage-disk-grid{gap:11px}.storage-vm-card .storage-child-item{border-color:#d6dfeb;box-shadow:none}.storage-vm-card .storage-child-title b{font-size:13px}.storage-vm-card .storage-child-cap .disk-capacity b{font-size:11px}.storage-vm-card .storage-child-cap .disk-capacity small{font-size:8px}
/* Make the historical note compact, like the status strips on Top VM. */
.storage-snapshot-note{margin-top:0}.storage-history-card{margin:0 0 12px}.storage-history-card .storage-snapshot-note{border:0;background:transparent;padding:0}
html[data-theme=dark] .storage-vm-identity .identity-kicker,html[data-theme=dark] .storage-vm-identity .identity-node,html[data-theme=dark] .storage-vm-identity .identity-foot{color:#9fb0c4}html[data-theme=dark] .storage-vm-card .storage-card-summary .disk-cap-meter,html[data-theme=dark] .storage-vm-card .storage-child-cap .disk-cap-meter{background:#334155!important}
@media(max-width:1450px){.storage-vm-card .storage-card-head{grid-template-columns:1fr}.storage-vm-card .storage-card-summary{grid-column:1}.storage-top-card .search{grid-template-columns:minmax(260px,1fr) 150px 170px 100px auto auto}}
@media(max-width:980px){.storage-top-card .top-grid{grid-template-columns:1fr}.storage-top-card .search{grid-template-columns:1fr 1fr}.storage-top-card .search input{grid-column:1/-1}.storage-vm-card .storage-card-summary{grid-template-columns:1fr 1fr}.storage-vm-card .storage-card-summary .disk-capacity{grid-column:1/-1}}
</style>
'''

def _v48138_storage_disk_group_cards(conn, values, start_ts):
    groups, details, total = _v48133_storage_disk_groups(conn, values, start_ts)
    cards = []
    for node, vm_uuid, public_ip, disk_count, assigned, allocated, rb, wb, ri, wi, seen in groups:
        ip = compact_ipv4(public_ip)
        node_href = url_for(
            "node_page", node=node, period=values["period"], q=vm_uuid,
            **({"at": values.get("at")} if values.get("at") else {}),
        )
        vm_href = url_for(
            "vm_page", node=node, vm_uuid=vm_uuid, period=values["period"],
            **({"at": values.get("at")} if values.get("at") else {}),
        )
        ip_line = (
            f'<span class="storage-node-ip">{escape(ip)}'
            f'<button type="button" class="copy-btn" data-copy="{escape(ip)}" title="Copy IP">⧉</button></span>'
            if ip else ""
        )
        child_html = "".join(
            _v48136_disk_child_html(node, vm_uuid, row, values["period"])
            for row in details.get((str(node), str(vm_uuid)), [])
        )
        disk_word = "disk" if safe_int(disk_count, 0) == 1 else "disks"
        identity = f'''
          <div class="storage-vm-identity">
            <span class="identity-kicker">VM UUID</span>
            <div class="identity-uuid"><a href="{escape(vm_href,quote=True)}" title="{escape(vm_uuid,quote=True)}">{escape(vm_uuid)}</a><button type="button" class="copy-btn" data-copy="{escape(vm_uuid)}" title="Copy UUID">⧉</button></div>
            <div class="identity-node"><span>Node</span><a href="{escape(node_href,quote=True)}">{escape(node)}</a>{ip_line}</div>
            <small class="identity-foot">{safe_int(disk_count,0)} customer {disk_word} · latest sample {fmt_push(seen)}</small>
          </div>'''
        cards.append(f'''
        <article class="storage-vm-card">
          <div class="storage-card-head">
            {identity}
            {_v48137_summary_metrics(allocated,assigned,rb,wb,ri,wi)}
          </div>
          <div class="storage-card-body"><div class="storage-disk-grid">{child_html}</div></div>
        </article>''')
    if not cards:
        cards = ['<div class="storage-card-empty">No customer disk sample at this snapshot.</div>']
    sort_bar = _v48137_sort_bar(values, [
        ("W IOPS","writeiops"),("WRITE","write"),("R IOPS","readiops"),("READ","read"),
        ("ALLOC","allocated"),("ASSIGNED","assigned"),("%","allocpct"),("DISKS","diskcount"),("UUID","uuid"),("NODE","node"),
    ])
    return f'''
    {STORAGE_IO_CSS}{V48136_STORAGE_CSS}{V48137_STORAGE_CSS}{V48138_STORAGE_CSS}
    <div class="card storage-table-card">
      <div class="table-title-row"><div><h3>VM Disks</h3><div class="table-hint">One VM card per UUID. UUID is the primary object; node and IP stay as supporting context, and every customer disk remains nested below the VM.</div></div>{sort_bar}</div>
      <div class="storage-card-list">{"".join(cards)}</div>{_storage_pager(values,total)}
    </div>'''

# The existing dispatch function resolves this name at request time.
_v48137_storage_disk_group_cards = _v48138_storage_disk_group_cards

def _v48138_storage_status_summary(snapshot, stats):
    if snapshot and snapshot.get("mode") == "history":
        actual = stats.get("max_seen") or snapshot.get("target") or 0
        return "HISTORICAL", "history", actual
    latest = (snapshot or {}).get("latest") or 0
    return "LIVE", "live", latest

def storage_io_page_v48138():
    values = _storage_io_params()
    if values["view"] not in {"disks", "nodes", "backends"}:
        values["view"] = "disks"
    if values["view"] == "backends":
        values["view"] = "nodes"

    conn = db()
    snapshot = None
    stats = {"nodes": 0, "disks": 0, "storages": 0, "min_seen": 0, "max_seen": 0}
    try:
        ensure_storage_snapshot_schema(conn)
        snapshot = _v48137_storage_target(conn, values)
        if snapshot["mode"] == "history":
            payload_rows = _v48137_snapshot_payload_rows(conn, values, snapshot["target"])
            stats = _v48137_create_snapshot_shadow_tables(conn, payload_rows)
            start_ts = 0
        else:
            start_ts = now_ts() - max(CACHE_BUCKET_SECONDS * 2, period_seconds("5m"))
        node_options, mount_options = _v48137_storage_filter_options(conn, values)
        if values["view"] == "nodes":
            table = _v48133_storage_node_table(conn, values, start_ts)
        else:
            table = _v48133_storage_disk_table(conn, values, start_ts)
    finally:
        conn.close()

    at_value = values.get("at") or ""
    disk_tab = _storage_io_url(values, view="disks", sort="writeiops", order="desc", page=1)
    node_tab = _storage_io_url(values, view="nodes", sort="writeiops", order="desc", page=1)
    disk_active = "active" if values["view"] == "disks" else ""
    node_active = "active" if values["view"] == "nodes" else ""
    history_label, history_class, selected_ts = _v48138_storage_status_summary(snapshot, stats)
    latest_ts = (snapshot or {}).get("latest") or selected_ts or now_ts()
    selected_text = "Live current" if history_class == "live" else (fmt_full(selected_ts) if selected_ts else "No retained point")
    hidden_at = f'<input type="hidden" name="at" value="{escape(at_value,quote=True)}">' if at_value else ""
    row_options = "".join(
        f'<option value="{n}"{" selected" if values["limit"]==n else ""}>{n} rows</option>'
        for n in (10, 20, 30, 50, 100, 200)
    )
    clear_kwargs = {"view": values["view"], "period": values["period"], "limit": values["limit"]}
    clear_href = url_for("storage_io_page", **clear_kwargs)
    target_ts = _request_target_ts()

    toolbar = f'''
    <div class="card top-card storage-top-card">
      <div class="top-grid">
        <div><div class="label">Latest Available</div><div class="value">{fmt_full(latest_ts)}</div></div>
        <div><div class="label">Timezone</div><div class="value">{escape(display_timezone_name())}</div></div>
        <div><div class="label">Selected Snapshot</div><div class="value">{escape(selected_text)}</div></div>
      </div>
      <div class="table-title-row"><div><div class="label period-label">Snapshot lookback</div></div><div class="storage-toolbar-state"><span class="{history_class}">{history_label}</span></div></div>
      <div class="periods storage-periods">{_storage_period_links(values)}</div>
      <form class="search" method="get" action="{url_for('storage_io_page')}">
        <input type="hidden" name="view" value="{escape(values['view'],quote=True)}"><input type="hidden" name="period" value="{escape(values['period'],quote=True)}"><input type="hidden" name="sort" value="{escape(values['sort'],quote=True)}"><input type="hidden" name="order" value="{escape(values['order'],quote=True)}">{hidden_at}
        <input name="q" value="{escape(values['q'],quote=True)}" placeholder="Search node, IP, UUID, disk, path or mount">
        <select name="node" aria-label="Node filter">{node_options}</select>
        <select name="mount" aria-label="Storage filter">{mount_options}</select>
        <select name="limit" aria-label="Row limit">{row_options}</select>
        <button type="submit">Search</button><a class="clear" href="{escape(clear_href,quote=True)}">Clear</a>
      </form>
    </div>'''

    time_card = _custom_snapshot_control(
        "storage_io_page", target_ts, title="Custom Snapshot Time",
        view=values["view"], period=values["period"], q=values["q"] or None,
        node=values["node"] or None, mount=values["mount"] or None,
        sort=values["sort"], order=values["order"], limit=values["limit"], page=1,
    )
    note = f'<div class="card storage-history-card">{_v48137_storage_snapshot_note(snapshot or {"mode":"live","latest":0,"target":0}, stats)}</div>'
    content = (
        STORAGE_IO_CSS + V48137_STORAGE_CSS + V48138_STORAGE_CSS
        + '<div class="card storage-hero"><div><span class="eyebrow">DISK MONITOR</span><h2>Storage I/O</h2><p>Search and open retained snapshots with the same workflow as Top VM.</p></div>'
        + f'<div class="storage-tabs"><a class="{disk_active}" href="{escape(disk_tab,quote=True)}">VM Disks</a><a class="{node_active}" href="{escape(node_tab,quote=True)}">Storage Node</a></div></div>'
        + toolbar + time_card + note + table
    )
    return page("Storage I/O", content)

app.view_functions["storage_io_page"] = storage_io_page_v48138

V48139_VERSION = "48.13.9"
V48139_BUILD = "r2"

V48139_UI_CSS = r'''
<style id="v48139-abuse-storage-cards">
/* Current Abuse: add one compact disk-capacity column without changing the rest. */
.abuse-current-v48139{min-width:2380px!important}
.abuse-current-v48139 th:nth-child(1){width:42px!important}
.abuse-current-v48139 th:nth-child(2){width:292px!important}
.abuse-current-v48139 th:nth-child(3){width:370px!important}
.abuse-current-v48139 th:nth-child(4){width:235px!important}
.abuse-current-v48139 th:nth-child(5){width:250px!important}
.abuse-current-v48139 th:nth-child(6){width:195px!important}
.abuse-current-v48139 th:nth-child(7){width:280px!important}
.abuse-current-v48139 th:nth-child(8){width:205px!important}
.abuse-current-v48139 th:nth-child(9){width:235px!important}
.abuse-current-v48139 th:nth-child(10){width:165px!important}
.abuse-disk-capacity{min-width:0;text-align:left}
.abuse-disk-capacity .resource-primary{font-size:14px!important}
.abuse-disk-capacity .resource-context{justify-content:flex-start}
.abuse-disk-capacity .resource-foot{text-align:left!important}
.abuse-disk-capacity.resource-na .resource-primary{color:#98a2b3!important}

/* Storage cards: one strong VM/Node card, clear sections, compact disk rows. */
.storage-card-list-v48139{display:grid;gap:14px}
.storage-entity-card-v48139{border:2px solid #cbd5e1;border-radius:15px;background:#fff;overflow:hidden;box-shadow:0 2px 7px rgba(15,23,42,.045)}
.storage-entity-card-v48139+.storage-entity-card-v48139{margin-top:2px}
.storage-entity-head-v48139{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:14px 16px;border-bottom:2px solid #dbe4ee;background:linear-gradient(180deg,#f8fbff,#f4f7fb)}
.storage-entity-id-v48139{min-width:0;flex:1}
.storage-entity-id-v48139 .entity-kicker{display:block;font-size:8px;font-weight:950;letter-spacing:.08em;color:#667085;text-transform:uppercase}
.storage-entity-id-v48139 .entity-main{display:flex;align-items:center;gap:7px;min-width:0;margin-top:3px}
.storage-entity-id-v48139 .entity-main>a{font-size:14px;font-weight:950;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#175cd3}
.storage-entity-id-v48139 .entity-context{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:6px;font-size:9px;color:#667085}
.storage-entity-id-v48139 .entity-context a{font-weight:850}
.storage-entity-actions-v48139{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.storage-entity-actions-v48139 .btn{padding:7px 10px!important;font-size:9px!important}
.storage-overview-v48139{display:grid;grid-template-columns:minmax(280px,1.2fr) minmax(360px,1fr);gap:12px;padding:14px 16px;border-bottom:1px solid #e5eaf0}
.storage-section-box-v48139{border:1px solid #dbe3ec;border-radius:12px;padding:12px;background:#fff}
.storage-section-label-v48139{display:block;font-size:9px;font-weight:950;letter-spacing:.065em;color:#667085;text-transform:uppercase}
.storage-overall-value-v48139{display:flex;align-items:baseline;gap:7px;flex-wrap:wrap;margin-top:6px}
.storage-overall-value-v48139 b{font-size:18px;line-height:1}
.storage-overall-value-v48139 span{font-size:10px;color:#667085;font-weight:800}
.storage-cap-track-v48139{height:8px;margin-top:10px;border-radius:999px;background:#e5e7eb;overflow:hidden}
.storage-cap-track-v48139>i{display:block;height:100%;border-radius:inherit;background:#12b76a}
.storage-cap-warm-v48139>i{background:#fdb022}.storage-cap-hot-v48139>i{background:#f79009}.storage-cap-critical-v48139>i{background:#f04438}
.storage-perf-grid-v48139{display:grid;grid-template-columns:repeat(3,minmax(88px,1fr));gap:8px;margin-top:7px}
.storage-perf-grid-v48139>div{padding:9px 10px;border-left:3px solid #dbe4ee;background:#f8fafc;border-radius:7px}
.storage-perf-grid-v48139 span{display:block;font-size:8px;font-weight:950;letter-spacing:.05em;color:#667085}
.storage-perf-grid-v48139 b{display:block;margin-top:4px;font-size:11px;white-space:nowrap}
.storage-children-v48139{padding:14px 16px 16px}
.storage-children-title-v48139{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:9px}
.storage-children-title-v48139 h4{margin:0;font-size:12px}
.storage-children-title-v48139 span{font-size:9px;color:#667085}
.storage-disk-row-v48139,.storage-mount-row-v48139{display:grid;grid-template-columns:minmax(245px,1.05fr) minmax(300px,1.25fr) minmax(360px,1.5fr);gap:14px;align-items:center;padding:12px 10px;border-top:1px solid #dbe3ec}
.storage-disk-row-v48139:first-child,.storage-mount-row-v48139:first-child{border-top:2px solid #94a3b8}
.storage-disk-id-v48139{min-width:0}
.storage-disk-id-v48139 .disk-title{display:flex;align-items:center;gap:8px;min-width:0}
.storage-disk-id-v48139 .disk-title b{font-size:14px}
.storage-disk-id-v48139 .disk-title span{font-size:9px;color:#475467;font-weight:850;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.storage-disk-id-v48139 code{display:block;margin-top:5px;font-size:8.5px;color:#667085;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.storage-row-cap-v48139 b{font-size:12px}.storage-row-cap-v48139 small{display:block;margin-top:4px;font-size:9px;color:#667085}
.storage-row-cap-v48139 .storage-cap-track-v48139{height:6px;margin-top:7px}
.storage-row-perf-v48139{display:grid;grid-template-columns:repeat(3,minmax(82px,1fr));gap:8px}
.storage-row-perf-v48139>div{padding-left:9px;border-left:1px solid #dbe3ec;min-width:0}
.storage-row-perf-v48139 span{display:block;font-size:8px;font-weight:950;color:#667085}
.storage-row-perf-v48139 b{display:block;margin-top:3px;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.storage-card-empty-v48139{padding:18px;border:1px dashed #cbd5e1;border-radius:12px;color:#667085;text-align:center}
.storage-entity-card-v48139 .copy-btn{flex:0 0 auto}
html[data-theme=dark] .storage-entity-card-v48139,html[data-theme=dark] .storage-section-box-v48139{background:#0f1b2c;border-color:#31445e}
html[data-theme=dark] .storage-entity-head-v48139{background:linear-gradient(180deg,#142238,#101c2d);border-bottom-color:#31445e}
html[data-theme=dark] .storage-overview-v48139,html[data-theme=dark] .storage-disk-row-v48139,html[data-theme=dark] .storage-mount-row-v48139{border-color:#31445e}
html[data-theme=dark] .storage-perf-grid-v48139>div{background:#132238;border-left-color:#3b4f6a}
html[data-theme=dark] .storage-cap-track-v48139{background:#334155}
html[data-theme=dark] .storage-entity-id-v48139 .entity-kicker,html[data-theme=dark] .storage-entity-id-v48139 .entity-context,html[data-theme=dark] .storage-section-label-v48139,html[data-theme=dark] .storage-overall-value-v48139 span,html[data-theme=dark] .storage-perf-grid-v48139 span,html[data-theme=dark] .storage-children-title-v48139 span,html[data-theme=dark] .storage-disk-id-v48139 .disk-title span,html[data-theme=dark] .storage-disk-id-v48139 code,html[data-theme=dark] .storage-row-cap-v48139 small,html[data-theme=dark] .storage-row-perf-v48139 span{color:#9fb0c4}
@media(max-width:1180px){.storage-overview-v48139{grid-template-columns:1fr}.storage-disk-row-v48139,.storage-mount-row-v48139{grid-template-columns:1fr 1fr}.storage-row-perf-v48139{grid-column:1/-1}}
@media(max-width:760px){.storage-entity-head-v48139{flex-direction:column}.storage-entity-actions-v48139{justify-content:flex-start}.storage-disk-row-v48139,.storage-mount-row-v48139{grid-template-columns:1fr}.storage-row-perf-v48139,.storage-perf-grid-v48139{grid-template-columns:1fr 1fr}}
</style>
'''

def _v48139_cap_level(pct):
    pct = max(0.0, safe_float(pct, 0.0))
    if pct >= 90:
        return "storage-cap-critical-v48139"
    if pct >= 75:
        return "storage-cap-hot-v48139"
    if pct >= 50:
        return "storage-cap-warm-v48139"
    return ""

def _v48139_capacity_bar(used, size, suffix="allocated / assigned"):
    used = max(0, safe_int(used, 0))
    size = max(0, safe_int(size, 0))
    pct = (used * 100.0 / size) if size > 0 else 0.0
    level = _v48139_cap_level(pct)
    return (
        f'<div class="storage-row-cap-v48139">'
        f'<b>{_disk_io_bytes(used)} / {_disk_io_bytes(size)}</b>'
        f'<small>{pct:.1f}% · {escape(suffix)}</small>'
        f'<div class="storage-cap-track-v48139 disk-cap-meter {level}"><i style="width:{min(100.0,pct):.1f}%"></i></div>'
        f'</div>'
    )

def _v48139_abuse_disk_capacity(allocated, assigned, slots, selected=""):
    allocated = max(0, safe_int(allocated, 0))
    assigned = max(0, safe_int(assigned, 0))
    slots = max(0, safe_int(slots, 0))
    if slots <= 0 and allocated <= 0 and assigned <= 0:
        return '<div class="resource-block abuse-disk-capacity resource-na"><b class="resource-primary">N/A</b><small class="resource-foot">No customer disk data</small></div>'
    pct = allocated * 100.0 / assigned if assigned > 0 else 0.0
    level = _v48129_level(pct)
    labels = {
        "diskallocated": "Allocated", "diskassigned": "Assigned",
        "diskallocpct": "Allocated %", "diskslots": "Disk slots",
    }
    return f'''
    <div class="resource-block abuse-disk-capacity resource-{level}" title="Sorted by {escape(labels.get(selected,'Disk capacity'),quote=True)}">
      <b class="resource-primary">{_disk_io_bytes(allocated)} / {_disk_io_bytes(assigned)}</b>
      <div class="resource-context"><b>{pct:.1f}% allocated</b></div>
      <span class="resource-meter"><i style="width:{min(100.0,max(0.0,pct)):.1f}%"></i></span>
      <small class="resource-foot">{slots} disk slot{'s' if slots != 1 else ''}</small>
    </div>'''

# Preserve the v48.12.9 operations query contract, only adding one aggregated
# disk-capacity join and four opt-in sort keys.

def _v48139_current_page(values):
    cfg = get_abuse_settings()
    rows, total, counts = _v48139_current_rows(values)
    body = ""
    rank_start = (values["page"] - 1) * values["limit"]
    for index, row in enumerate(rows, 1):
        (
            node, uuid, started, last_seen, flags, stored_severity,
            rxm, txm, rxp, txp, rxpk, txpk, rx_high, tx_high, rx_mbps_streak, tx_mbps_streak,
            cpu, core, vcpu, cpu_streak, rss_pct, guest_pct, usable_pct, ram_streak,
            ram_current, ram_rss, ram_available, ram_usable,
            dr, dw, dri, dwi, disk_streak, ip, disk_allocated, disk_assigned, disk_slots,
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
          <td>{_v48139_abuse_disk_capacity(disk_allocated,disk_assigned,disk_slots,values.get('sort'))}</td>
          <td><div class="metric-pair metric-pair-rich"><div class="{'selected' if values.get('sort') in {'diskr','readiops'} else ''}"><span>READ</span><b>{human_rate(dr)}</b><small>{safe_float(dri,0):,.0f} IOPS</small></div><div class="{'selected' if values.get('sort') in {'diskw','writeiops'} else ''}"><span>WRITE</span><b>{human_rate(dw)}</b><small>{safe_float(dwi,0):,.0f} IOPS</small></div></div>{disk_time}</td>
          <td><div class="timeline-cell"><b>{fmt_full(last_seen)}</b><small>{fmt_push(last_seen)}</small></div></td>
        </tr>"""
    if not body:
        body = '<tr><td colspan="10" class="empty">No visible VM matches the selected Current Abuse filters</td></tr>'
    pages = max(1, math.ceil(total / values["limit"]))
    h = lambda label, key, default="desc": _v48127_sort_link("current", values, key, label, default)
    ram_header = _v48128_group_sort_header("RAM", [
        ("Guest %", "ram", h("Guest %", "ram")), ("Used GiB", "ramused", h("Used GiB", "ramused")),
        ("Host RSS", "ramrss", h("Host RSS", "ramrss")), ("Assigned", "ramassigned", h("Assigned", "ramassigned")),
    ], values["sort"], values["order"])
    disk_cap_header = _v48128_group_sort_header("ALLOCATED / ASSIGNED", [
        ("Alloc", "diskallocated", h("ALLOC", "diskallocated")),
        ("Assigned", "diskassigned", h("ASSIGNED", "diskassigned")),
        ("%", "diskallocpct", h("%", "diskallocpct")),
        ("Slots", "diskslots", h("SLOTS", "diskslots")),
    ], values["sort"], values["order"])
    headers = (
        '<th>#</th>'
        f'<th>{h("NODE / VM","node","asc")}</th>'
        f'<th>{h("REASON / SEVERITY","severity")}</th>'
        f'<th>{_v48129_group_header("NETWORK AVG", [("RX Mbps","rx_mbps","desc"),("TX Mbps","tx_mbps","desc")], values)}</th>'
        f'<th>{_v48129_group_header("PPS PEAK / WINDOW", [("RX PPS","rx_peak","desc"),("TX PPS","tx_peak","desc")], values)}</th>'
        f'<th>{_v48129_group_header("CPU", [("Full %","cpu","desc"),("Core %","cpucore","desc")], values)}</th>'
        f'<th class="ram-compact-sort-head">{ram_header}</th>'
        f'<th>{disk_cap_header}</th>'
        f'<th>{_v48129_group_header("DISK I/O", [("Read","diskr","desc"),("Write","diskw","desc"),("Read IOPS","readiops","desc"),("Write IOPS","writeiops","desc")], values)}</th>'
        f'<th>{h("LAST SEEN","last_seen")}</th>'
    )
    return f"""
    {V48139_UI_CSS}
    <div class="abuse-kpis-v48126"><div><span>Filtered</span><b>{total}</b></div><div><span>Network</span><b>{counts['network']}</b></div><div><span>CPU</span><b>{counts['cpu']}</b></div><div><span>RAM</span><b>{counts['ram']}</b></div><div><span>Disk</span><b>{counts['disk']}</b></div></div>
    <div class="card"><div class="section-head"><div><h3>Current VM Abuse</h3><p>Original Abuse operations table plus compact disk capacity. ALLOC, ASSIGNED, %, and disk slots are independently sortable.</p></div><div class="count-badges"><span>All <b>{total}</b></span><span>Page <b>{values['page']}/{pages}</b></span><span>Policy <b>v{cfg['revision']}</b></span></div></div>
    <div class="table-wrap"><table class="abuse-current-v48129 abuse-current-v48139"><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>
    <div class="table-hint"><b>DISK CAPACITY:</b> Host Allocated / Assigned across customer disks. SLOTS is the number of attached customer disks. Existing Abuse policy and I/O logic are unchanged.</div>
    {_v48126_pagination('current', values, total)}</div>"""

def vm_abuse_page_v48139():
    tab = (request.args.get("tab") or "current").strip().lower()
    if tab in {"history", "incidents", "summary", "events", "raw", "raw-events"}:
        tab = "events"
    if tab not in {"current", "events"}:
        tab = "current"
    values = _v48128_filter_values()
    if tab == "events":
        values["limit"] = min(values["limit"], 200)
    current_sorts = {
        "node", "uuid", "type", "severity", "rx_mbps", "tx_mbps", "rx_peak", "tx_peak",
        "cpu", "cpucore", "ram", "ramused", "ramrss", "ramassigned",
        "diskallocated", "diskassigned", "diskallocpct", "diskslots",
        "diskr", "diskw", "readiops", "writeiops", "duration", "last_seen",
    }
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
    content += _v48139_current_page(values) if tab == "current" else _v48129_events_page(values)
    return page("VM Abuse", content)

# Keep the historical function name for old regression contracts while using
# the v48.13.9 implementation.
vm_abuse_page_v48139.__name__ = "vm_abuse_page_v48129"
app.view_functions["vm_abuse_page"] = vm_abuse_page_v48139

def _v48139_vm_disk_row(node, vm_uuid, row, values):
    target, source, mount, device, block, fstype, assigned, allocated, rb, wb, ri, wi, seen = row
    dev = device or (("/dev/" + block) if block else "-")
    filter_href = _storage_io_url(
        values, view="disks", node=node, mount=mount or "", q=vm_uuid,
        sort="writeiops", order="desc", page=1,
    )
    iops_text = f'R {_disk_io_iops(ri)} / W {_disk_io_iops(wi)}'
    return f'''
    <div class="storage-child-item storage-disk-row-v48139">
      <div class="storage-disk-id-v48139">
        <div class="disk-title"><b>{escape(target or '-')}</b><span>{escape(mount or '-')} · {escape(dev)}</span></div>
        <code title="{escape(source or '-',quote=True)}">{escape(source or '-')}</code>
      </div>
      {_v48139_capacity_bar(allocated,assigned)}
      <div class="storage-row-perf-v48139">
        <div><span>READ</span><b>{_disk_io_rate(rb)}</b></div>
        <div><span>WRITE</span><b>{_disk_io_rate(wb)}</b></div>
        <div><span>IOPS</span><b>{iops_text}</b></div>
      </div>
    </div>'''

def _v48139_storage_disk_group_cards(conn, values, start_ts):
    groups, details, total = _v48133_storage_disk_groups(conn, values, start_ts)
    cards = []
    for node, vm_uuid, public_ip, disk_count, assigned, allocated, rb, wb, ri, wi, seen in groups:
        ip = compact_ipv4(public_ip)
        node_href = url_for("node_page", node=node, period=values["period"], q=vm_uuid, **({"at": values.get("at")} if values.get("at") else {}))
        vm_href = url_for("vm_page", node=node, vm_uuid=vm_uuid, period=values["period"], **({"at": values.get("at")} if values.get("at") else {}))
        disk_rows = "".join(_v48139_vm_disk_row(node, vm_uuid, row, values) for row in details.get((str(node), str(vm_uuid)), []))
        pct = allocated * 100.0 / assigned if safe_int(assigned,0) > 0 else 0.0
        level = _v48139_cap_level(pct)
        cards.append(f'''
        <article class="storage-vm-card storage-entity-card-v48139">
          <div class="storage-entity-head-v48139">
            <div class="storage-vm-identity storage-entity-id-v48139">
              <span class="entity-kicker">VM UUID</span>
              <div class="entity-main"><a href="{escape(vm_href,quote=True)}" title="{escape(vm_uuid,quote=True)}">{escape(vm_uuid)}</a><button type="button" class="copy-btn" data-copy="{escape(vm_uuid)}" title="Copy UUID">⧉</button></div>
              <div class="entity-context"><span>Node</span><a href="{escape(node_href,quote=True)}">{escape(node)}</a>{f'<span>{escape(ip)}</span><button type="button" class="copy-btn" data-copy="{escape(ip)}" title="Copy IP">⧉</button>' if ip else ''}<span>· {safe_int(disk_count,0)} disk{'s' if safe_int(disk_count,0)!=1 else ''}</span><span>· sample {fmt_push(seen)}</span></div>
            </div>
            <div class="storage-entity-actions-v48139"><a class="btn" href="{escape(vm_href,quote=True)}">View details</a></div>
          </div>
          <div class="storage-overview-v48139">
            <div class="storage-section-box-v48139">
              <span class="storage-section-label-v48139">Overall</span>
              <div class="storage-overall-value-v48139"><b>{_disk_io_bytes(allocated)} / {_disk_io_bytes(assigned)}</b><span>{pct:.1f}% allocated / assigned</span></div>
              <div class="storage-cap-track-v48139 disk-cap-meter {level}"><i style="width:{min(100.0,max(0.0,pct)):.1f}%"></i></div>
            </div>
            <div class="storage-section-box-v48139">
              <span class="storage-section-label-v48139">Performance</span>
              <div class="storage-perf-grid-v48139"><div><span>READ</span><b>{_disk_io_rate(rb)}</b></div><div><span>WRITE</span><b>{_disk_io_rate(wb)}</b></div><div><span>IOPS</span><b>R {_disk_io_iops(ri)} / W {_disk_io_iops(wi)}</b></div></div>
            </div>
          </div>
          <div class="storage-children-v48139">
            <div class="storage-children-title-v48139"><h4>Disks</h4><span>{safe_int(disk_count,0)} customer disk{'s' if safe_int(disk_count,0)!=1 else ''}</span></div>
            {disk_rows}
          </div>
        </article>''')
    if not cards:
        cards = ['<div class="storage-card-empty-v48139">No customer disk sample at this snapshot.</div>']
    sort_bar = _v48137_sort_bar(values, [
        ("W IOPS","writeiops"),("WRITE","write"),("R IOPS","readiops"),("READ","read"),
        ("ALLOC","allocated"),("ASSIGNED","assigned"),("%","allocpct"),("DISKS","diskcount"),("UUID","uuid"),("NODE","node"),
    ])
    return f'''
    {V48139_UI_CSS}
    <div class="card storage-table-card">
      <div class="table-title-row"><div><h3>VM Disks</h3><div class="table-hint">One VM card per UUID. Overall capacity and performance stay at the top; every vda/vdb/vdc is separated below.</div></div>{sort_bar}</div>
      <div class="storage-card-list-v48139">{"".join(cards)}</div>{_storage_pager(values,total)}
    </div>'''

def _v48139_node_mount_row(values, row):
    node, _public_ip, mount, device, block, raid, fs, size, used, avail, usep, rb, wb, ri, wi, util, seen, disk_count, vm_count = row
    dev = _v48135_base_device(device) or (("/dev/" + block) if block else "-")
    filter_href = _storage_io_url(values, view="disks", node=node, mount=mount or "", q="", sort="writeiops", order="desc", page=1)
    return f'''
    <div class="storage-mount-row-v48139">
      <div class="storage-disk-id-v48139">
        <div class="disk-title"><b><a href="{escape(filter_href,quote=True)}">{escape(mount or '-')}</a></b><span>{escape(dev)} · {escape(raid or 'hardware/unknown RAID')} · {escape(fs or '-')}</span></div>
        <code>{safe_int(vm_count,0)} VMs · {safe_int(disk_count,0)} disks · seen {fmt_push(seen)}</code>
      </div>
      {_v48139_capacity_bar(used,size,'used / size')}
      <div class="storage-row-perf-v48139">
        <div><span>READ</span><b>{_disk_io_rate(rb)}</b></div>
        <div><span>WRITE</span><b>{_disk_io_rate(wb)}</b></div>
        <div><span>IOPS / UTIL</span><b>R {_disk_io_iops(ri)} / W {_disk_io_iops(wi)} · {safe_float(util,0):.1f}%</b></div>
      </div>
    </div>'''

def _v48139_storage_node_group_cards(conn, values, start_ts):
    rows = _v48136_real_storage_rows(conn, values, start_ts)
    grouped = {}
    for row in rows:
        grouped.setdefault(str(row[0]), []).append(row)
    count_map = {str(r[0]): (safe_int(r[1],0), safe_int(r[2],0)) for r in conn.execute(
        "SELECT node,COUNT(DISTINCT vm_uuid),COUNT(*) FROM vm_disk_current WHERE role='customer' GROUP BY node"
    ).fetchall()}
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
        vm_count, disk_count = count_map.get(node, (0, 0))
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
    cards = []
    for node, ip, mounts, size, used, rb, wb, ri, wi, util, seen, disk_count, vm_count in groups:
        node_href = url_for("node_page", node=node, period=values["period"], **({"at": values.get("at")} if values.get("at") else {}))
        pct = used * 100.0 / size if safe_int(size,0) > 0 else 0.0
        level = _v48139_cap_level(pct)
        mount_rows = "".join(_v48139_node_mount_row(values, row) for row in mounts)
        cards.append(f'''
        <article class="storage-node-card storage-entity-card-v48139">
          <div class="storage-entity-head-v48139">
            <div class="storage-entity-id-v48139">
              <span class="entity-kicker">Storage Node</span>
              <div class="entity-main"><a href="{escape(node_href,quote=True)}">{escape(node)}</a>{f'<button type="button" class="copy-btn" data-copy="{escape(ip)}" title="Copy IP">⧉</button>' if ip else ''}</div>
              <div class="entity-context">{f'<span>{escape(ip)}</span>' if ip else ''}<span>{len(mounts)} filesystems</span><span>· {vm_count} VMs</span><span>· {disk_count} disks</span><span>· sample {fmt_push(seen)}</span></div>
            </div>
            <div class="storage-entity-actions-v48139"><a class="btn" href="{escape(node_href,quote=True)}">View node</a></div>
          </div>
          <div class="storage-overview-v48139">
            <div class="storage-section-box-v48139">
              <span class="storage-section-label-v48139">Overall</span>
              <div class="storage-overall-value-v48139"><b>{_disk_io_bytes(used)} / {_disk_io_bytes(size)}</b><span>{pct:.1f}% used / size</span></div>
              <div class="storage-cap-track-v48139 disk-cap-meter {level}"><i style="width:{min(100.0,max(0.0,pct)):.1f}%"></i></div>
            </div>
            <div class="storage-section-box-v48139">
              <span class="storage-section-label-v48139">Performance</span>
              <div class="storage-perf-grid-v48139"><div><span>READ</span><b>{_disk_io_rate(rb)}</b></div><div><span>WRITE</span><b>{_disk_io_rate(wb)}</b></div><div><span>IOPS / HOT UTIL</span><b>R {_disk_io_iops(ri)} / W {_disk_io_iops(wi)} · {util:.1f}%</b></div></div>
            </div>
          </div>
          <div class="storage-children-v48139">
            <div class="storage-children-title-v48139"><h4>Filesystems</h4><span>{len(mounts)} real roots</span></div>
            {mount_rows}
          </div>
        </article>''')
    if not cards:
        cards = ['<div class="storage-card-empty-v48139">No real node storage sample at this snapshot.</div>']
    sort_bar = _v48137_sort_bar(values, [
        ("W IOPS","writeiops"),("WRITE","write"),("R IOPS","readiops"),("READ","read"),
        ("UTIL","util"),("USED","used"),("SIZE","size"),("%","usepct"),("NODE","node"),
    ])
    return f'''
    {V48139_UI_CSS}
    <div class="card storage-table-card">
      <div class="table-title-row"><div><h3>Storage Node</h3><div class="table-hint">One node card per node. Overall usage and performance stay at the top; each real filesystem is separated below.</div></div>{sort_bar}</div>
      <div class="storage-card-list-v48139">{"".join(cards)}</div>{_storage_pager(values,total)}
    </div>'''

# Existing dispatchers resolve these names at request time. Filtered mount
# views remain the original one-disk-per-row / one-mount-per-row tables.
_v48137_storage_disk_group_cards = _v48139_storage_disk_group_cards
_v48137_storage_node_group_cards = _v48139_storage_node_group_cards

