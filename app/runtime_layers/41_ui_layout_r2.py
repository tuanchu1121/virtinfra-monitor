# v50.5.9 r2 layout-polish-only release based on r1
# ---------------------------------------------------------------------------
V5059R2_RELEASE = "50.5.9-prod-r3-ui-alignment-overflow-hotfix"


def _v5058r5_is_transient_iface(value):
    """UI-only filter for transient libguestfs interfaces."""
    return str(value or "").strip().lower().startswith("guestfs-")


# Storage filtered Node view hotfix.
# The previous query referenced node_inventory alias "ni" in WHERE without
# joining it. This replacement adds only the missing LEFT JOIN and preserves
# filtering, sorting, pagination and rendering behavior.
def _v5058r5_storage_node_filtered_table(conn, values, start_ts):
    where = [
        "s.last_seen>=?",
        "(ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))",
    ]
    params = [start_ts]
    if values.get("node"):
        where.append("s.node=?")
        params.append(values["node"])
    if values.get("mount"):
        where.append("s.mount=?")
        params.append(values["mount"])
    if values.get("q"):
        pattern = like_pattern(values["q"])
        where.append(
            f"(s.node LIKE ? OR s.mount LIKE ? OR s.device LIKE ? OR "
            f"s.block LIKE ? OR s.raid_level LIKE ? OR s.fstype LIKE ? OR "
            f"{_v48133_public_ip_sql('s')} LIKE ?)"
        )
        params.extend([pattern] * 7)

    rows = conn.execute(f'''
      SELECT s.node,{_v48133_public_ip_sql('s')} AS public_ipv4,
             s.mount,s.device,s.block,s.raid_level,s.fstype,
             s.size,s.used,s.avail,s.use_percent,s.read_bps,s.write_bps,
             s.read_iops,s.write_iops,s.util_percent,s.last_seen,
             (SELECT COUNT(*) FROM vm_disk_current d
               WHERE d.node=s.node AND d.mount=s.mount AND d.role='customer') AS disk_count,
             (SELECT COUNT(DISTINCT d.vm_uuid) FROM vm_disk_current d
               WHERE d.node=s.node AND d.mount=s.mount AND d.role='customer') AS vm_count
        FROM node_storage_current s
        LEFT JOIN node_inventory ni ON ni.node=s.node
       WHERE {' AND '.join(where)}
    ''', params).fetchall()

    chosen = {}
    for row in rows:
        node, _ip, mount, device, *_rest = row
        if str(mount or "").startswith(("/run", "/sys", "/proc", "/dev")):
            continue
        if "[" in str(device or "") and str(device).endswith("]"):
            continue
        key = (str(node), _v48135_base_device(device) or ("mount:" + str(mount)))
        rank = _v48135_mount_rank(mount)
        old = chosen.get(key)
        if old is None or rank < old[0]:
            chosen[key] = (rank, row)
    rows = [value[1] for value in chosen.values()]

    metric = {
        "node": lambda row: str(row[0]).lower(),
        "mount": lambda row: str(row[2]).lower(),
        "size": lambda row: safe_float(row[7], 0),
        "used": lambda row: safe_float(row[8], 0),
        "usepct": lambda row: safe_float(row[10], 0),
        "read": lambda row: safe_float(row[11], 0),
        "write": lambda row: safe_float(row[12], 0),
        "readiops": lambda row: safe_float(row[13], 0),
        "writeiops": lambda row: safe_float(row[14], 0),
        "util": lambda row: safe_float(row[15], 0),
        "seen": lambda row: safe_float(row[16], 0),
    }
    if values["sort"] not in metric:
        values["sort"] = "writeiops"
    rows.sort(key=metric[values["sort"]], reverse=values["order"] != "asc")
    total = len(rows)
    pages = max(1, int(math.ceil(total / float(values["limit"]))))
    values["page"] = min(values["page"], pages)
    rows = rows[
        (values["page"] - 1) * values["limit"]:
        values["page"] * values["limit"]
    ]

    body = []
    for (
        node, public_ip, mount, device, block, raid, fs, size, used, avail,
        usep, read_bps, write_bps, read_iops, write_iops, util, seen,
        disk_count, vm_count,
    ) in rows:
        filter_href = _storage_io_url(
            values, view="disks", node=node, mount=mount,
            sort="writeiops", order="desc", page=1,
        )
        node_href = url_for("node_page", node=node, period=values["period"])
        ip = compact_ipv4(public_ip)
        ip_line = (
            f'<span class="storage-node-ip">{escape(ip)}'
            f'<button type="button" class="copy-btn" data-copy="{escape(ip)}" '
            f'title="Copy IP">⧉</button></span>'
            if ip else ""
        )
        body.append(f'''
        <tr>
          <td class="storage-node-cell"><a href="{escape(node_href, quote=True)}"><b>{escape(node)}</b></a>{ip_line}</td>
          <td class="storage-backend"><a href="{escape(filter_href, quote=True)}"><b>{escape(mount or '-')}</b></a><span>{escape(_v48135_base_device(device) or '-')} · {escape(raid or 'hardware/unknown RAID')} · {escape(fs or '-')}</span></td>
          <td>{_disk_io_capacity(used, size, 'used / size')}</td>
          <td class="num">{_disk_io_rate(read_bps)}</td>
          <td class="num"><b>{_disk_io_rate(write_bps)}</b></td>
          <td class="num">{_disk_io_iops(read_iops)}</td>
          <td class="num"><b>{_disk_io_iops(write_iops)}</b></td>
          <td class="num"><b>{safe_float(util, 0):.1f}%</b></td>
          <td class="num"><b>{vm_count}</b><small class="storage-count-sub">{disk_count} disks</small></td>
          <td class="num"><small>{fmt_push(seen)}</small></td>
        </tr>''')
    if not body:
        body = ['<tr><td colspan="10" class="empty">No real node storage sample in this lookback</td></tr>']

    header = lambda label, key: _storage_sort_header(values, label, key)
    return f'''
    <div class="card storage-table-card">
      <div class="table-title-row"><div><h3>Storage Node</h3></div></div>
      <div class="table-wrap"><table class="storage-node-table"><thead><tr>
        <th>{header('NODE', 'node')}</th>
        <th>{header('MOUNT / DEVICE', 'mount')}</th>
        <th><div>USED / SIZE</div><small>{header('USED', 'used')} · {header('SIZE', 'size')} · {header('%', 'usepct')}</small></th>
        <th>{header('READ', 'read')}</th><th>{header('WRITE', 'write')}</th>
        <th>{header('R IOPS', 'readiops')}</th><th>{header('W IOPS', 'writeiops')}</th>
        <th>{header('UTIL', 'util')}</th><th>VM / DISKS</th><th>{header('SEEN', 'seen')}</th>
      </tr></thead><tbody>{''.join(body)}</tbody></table></div>
      {_storage_pager(values, total)}
    </div>'''


# Update every saved filtered-view alias used by the later Storage wrappers.
_v48135_storage_node_table = _v5058r5_storage_node_filtered_table
_v48136_storage_node_filtered_base = _v5058r5_storage_node_filtered_table
_v48137_storage_node_filtered_base = _v5058r5_storage_node_filtered_table


# UI-only interface sanitization. Collection and database rows are untouched.
_v5058r5_interface_table_base = interface_table


def interface_table(title, bridge, node, rows, period, q="", sort_by="total", order="desc", vm_status="active"):
    filtered = [row for row in (rows or []) if not _v5058r5_is_transient_iface(row[0] if row else "")]
    return _v5058r5_interface_table_base(
        title, bridge, node, filtered, period,
        q=q, sort_by=sort_by, order=order, vm_status=vm_status,
    )


# Physical interface names are sanitized in the final rendered HTML layer.


# Gap-aware chart helpers. A real zero remains a point at zero. A missing time
# bucket starts a new SVG polyline so the unavailable interval stays blank.
def _v5058r5_sorted_chart_rows(rows):
    by_bucket = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        bucket = safe_int(row.get("bucket"), 0)
        if bucket > 0:
            by_bucket[bucket] = row
    return [by_bucket[key] for key in sorted(by_bucket)]


def _v5058r5_chart_cadence(rows):
    ordered = _v5058r5_sorted_chart_rows(rows)
    gaps = [
        safe_int(ordered[index]["bucket"], 0) - safe_int(ordered[index - 1]["bucket"], 0)
        for index in range(1, len(ordered))
        if safe_int(ordered[index]["bucket"], 0) > safe_int(ordered[index - 1]["bucket"], 0)
    ]
    if not gaps:
        return CACHE_BUCKET_SECONDS
    gaps.sort()
    lower = gaps[:max(1, min(len(gaps), max(3, len(gaps) // 2)))]
    return max(1, safe_int(lower[len(lower) // 2], CACHE_BUCKET_SECONDS))


def _v5058r5_sample_segments(segments, max_points=360):
    total = sum(len(segment) for segment in segments)
    if total <= max_points:
        return segments
    sampled = []
    for segment in segments:
        if not segment:
            continue
        allowance = max(2, int(round(max_points * len(segment) / float(total))))
        if len(segment) <= allowance:
            sampled.append(segment)
            continue
        stride = max(1, int(math.ceil((len(segment) - 1) / float(max(1, allowance - 1)))))
        current = segment[::stride]
        if current[-1] is not segment[-1]:
            current.append(segment[-1])
        sampled.append(current)
    return sampled


def _v5058r5_chart_segments(rows, key=None, valid_key=None, max_points=360):
    ordered = _v5058r5_sorted_chart_rows(rows)
    if not ordered:
        return []
    cadence = _v5058r5_chart_cadence(ordered)
    gap_limit = max(cadence + 60, int(cadence * 1.8))
    segments = []
    current = []
    previous_bucket = None
    for row in ordered:
        bucket = safe_int(row.get("bucket"), 0)
        valid = True
        if valid_key:
            valid = bool(safe_int(row.get(valid_key), 0))
        if key is not None and row.get(key) is None:
            valid = False
        if not valid:
            if current:
                segments.append(current)
                current = []
            previous_bucket = None
            continue
        if previous_bucket is not None and bucket - previous_bucket > gap_limit:
            if current:
                segments.append(current)
            current = []
        current.append(row)
        previous_bucket = bucket
    if current:
        segments.append(current)
    return _v5058r5_sample_segments(segments, max_points=max_points)


def _v5058r5_chart_domain(rows):
    ordered = _v5058r5_sorted_chart_rows(rows)
    if not ordered:
        return 0, 1
    start = safe_int(ordered[0].get("bucket"), 0)
    end = safe_int(ordered[-1].get("bucket"), start)
    return start, max(start + 1, end)


def _v5058r5_xy(row, key, start_ts, end_ts, x0, y0, plot_w, plot_h, max_v):
    bucket = safe_int(row.get("bucket"), start_ts)
    x = x0 + ((bucket - start_ts) / float(max(1, end_ts - start_ts))) * plot_w
    value = max(0.0, safe_float(row.get(key), 0.0))
    y = y0 + plot_h - ((value / max_v) * plot_h if max_v else 0)
    return x, y


def _v5058r5_segment_polylines(rows, key, css_class, start_ts, end_ts, x0, y0, plot_w, plot_h, max_v, valid_key=None):
    items = []
    for segment in _v5058r5_chart_segments(rows, key=key, valid_key=valid_key):
        points = []
        for row in segment:
            x, y = _v5058r5_xy(row, key, start_ts, end_ts, x0, y0, plot_w, plot_h, max_v)
            points.append(f"{x:.1f},{y:.1f}")
        if len(points) >= 2:
            items.append(f'<polyline points="{" ".join(points)}" class="line {css_class}"/>')
        elif points:
            x, y = points[0].split(",")
            items.append(f'<circle cx="{x}" cy="{y}" r="2.6" class="dot {css_class.replace("-line", "-dot")}"/>')
    return "".join(items)


def _v5058r5_x_labels(rows, left, plot_w, h):
    ordered = _v5058r5_sorted_chart_rows(rows)
    if not ordered:
        return ""
    start_ts, end_ts = _v5058r5_chart_domain(ordered)
    targets = [0.0, 0.25, 0.5, 0.75, 1.0] if len(ordered) > 5 else [index / max(1, len(ordered) - 1) for index in range(len(ordered))]
    selected = []
    for ratio in targets:
        target = start_ts + ratio * (end_ts - start_ts)
        row = min(ordered, key=lambda item: abs(safe_int(item.get("bucket"), 0) - target))
        if row not in selected:
            selected.append(row)
    labels = []
    for row in selected:
        bucket = safe_int(row.get("bucket"), start_ts)
        x = left + ((bucket - start_ts) / float(max(1, end_ts - start_ts))) * plot_w
        label = row.get("label") or fmt_chart_label(bucket, _v5058r5_chart_cadence(ordered))
        labels.append(f'<text x="{x:.1f}" y="{h - 15}" class="x-label" text-anchor="middle">{escape(label)}</text>')
    return "".join(labels)


def _v5058r5_hover_zones(rows, series, start_ts, end_ts, left, top, plot_w, plot_h):
    ordered = _v5058r5_sorted_chart_rows(rows)
    if not ordered:
        return ""
    positions = []
    for row in ordered:
        bucket = safe_int(row.get("bucket"), start_ts)
        positions.append(left + ((bucket - start_ts) / float(max(1, end_ts - start_ts))) * plot_w)
    items = []
    for index, row in enumerate(ordered):
        x = positions[index]
        previous_x = positions[index - 1] if index else left
        next_x = positions[index + 1] if index + 1 < len(positions) else left + plot_w
        zone_left = max(left, (previous_x + x) / 2 if index else left)
        zone_right = min(left + plot_w, (x + next_x) / 2 if index + 1 < len(positions) else left + plot_w)
        parts = [fmt_full(row["bucket"])]
        for item in series:
            key = item["key"]
            valid_key = item.get("valid_key")
            if valid_key and not safe_int(row.get(valid_key), 0):
                value = "No data"
            else:
                value = fmt_metric_value(row.get(key, 0), item.get("kind", "raw"))
            parts.append(f'{item.get("label", key)}: {value}')
        items.append(
            f'<rect x="{zone_left:.1f}" y="{top}" width="{max(1.0, zone_right - zone_left):.1f}" '
            f'height="{plot_h}" class="hover-zone"><title>{escape(chr(10).join(parts))}</title></rect>'
        )
    return "".join(items)


def node_chart_svg(rows, title):
    ordered = _v5058r5_sorted_chart_rows(rows)
    if not ordered or max((max(safe_float(row.get("public"), 0), safe_float(row.get("private"), 0)) for row in ordered), default=0) <= 0:
        return f'<div class="card chart-card node-chart-card"><h3>{escape(title)}</h3><div class="empty">No chart data in this period</div></div>'
    w, h = 1100, 280
    left, right, top, bottom = 74, 18, 18, 42
    plot_w, plot_h = w - left - right, h - top - bottom
    real_max = max(max(safe_float(row.get("public"), 0), safe_float(row.get("private"), 0)) for row in ordered) or 1
    max_v = nice_ceiling(real_max)
    start_ts, end_ts = _v5058r5_chart_domain(ordered)
    grid, labels = [], []
    for index in range(5):
        ratio = index / 4
        y = top + plot_h - ratio * plot_h
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w-right}" y2="{y:.1f}" class="grid-line"/>')
        labels.append(f'<text x="8" y="{y+4:.1f}" class="axis-label">{escape(human(max_v * ratio))}</text>')
    series = [
        {"key": "public", "label": "Public", "kind": "bytes"},
        {"key": "private", "label": "Private", "kind": "bytes"},
    ]
    return f'''
    <div class="card chart-card node-chart-card">
      <h3>{escape(title)}</h3>
      <div class="legend"><span><i class="public"></i>Public</span><span><i class="private"></i>Private</span></div>
      <div class="svg-wrap node-svg-wrap"><svg viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">
        {''.join(grid)}{''.join(labels)}
        <line x1="{left}" y1="{top}" x2="{left}" y2="{h-bottom}" class="axis"/>
        <line x1="{left}" y1="{h-bottom}" x2="{w-right}" y2="{h-bottom}" class="axis"/>
        {_v5058r5_segment_polylines(ordered, 'public', 'public-line', start_ts, end_ts, left, top, plot_w, plot_h, max_v)}
        {_v5058r5_segment_polylines(ordered, 'private', 'private-line', start_ts, end_ts, left, top, plot_w, plot_h, max_v)}
        {_v5058r5_x_labels(ordered, left, plot_w, h)}
        {_v5058r5_hover_zones(ordered, series, start_ts, end_ts, left, top, plot_w, plot_h)}
      </svg></div>
    </div>'''


def vm_chart_svg(rows, title):
    ordered = _v5058r5_sorted_chart_rows(rows)
    if not ordered or max((safe_float(row.get("rx"), 0) + safe_float(row.get("tx"), 0) for row in ordered), default=0) <= 0:
        return f'<div class="card chart-card small-chart"><h3>{escape(title)}</h3><div class="empty">No chart data in this period</div></div>'
    w, h = 860, 240
    left, right, top, bottom = 74, 18, 18, 42
    plot_w, plot_h = w - left - right, h - top - bottom
    real_max = max(max(safe_float(row.get("rx"), 0), safe_float(row.get("tx"), 0)) for row in ordered) or 1
    max_v = nice_ceiling(real_max)
    start_ts, end_ts = _v5058r5_chart_domain(ordered)
    grid, labels = [], []
    for index in range(5):
        ratio = index / 4
        y = top + plot_h - ratio * plot_h
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w-right}" y2="{y:.1f}" class="grid-line"/>')
        labels.append(f'<text x="8" y="{y+4:.1f}" class="axis-label">{escape(human(max_v * ratio))}</text>')
    series = [
        {"key": "rx", "label": "RX", "kind": "bytes"},
        {"key": "tx", "label": "TX", "kind": "bytes"},
    ]
    return f'''
    <div class="card chart-card small-chart">
      <h3>{escape(title)}</h3>
      <div class="legend"><span><i class="rx"></i>RX</span><span><i class="tx"></i>TX</span></div>
      <div class="svg-wrap"><svg viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">
        {''.join(grid)}{''.join(labels)}
        <line x1="{left}" y1="{top}" x2="{left}" y2="{h-bottom}" class="axis"/>
        <line x1="{left}" y1="{h-bottom}" x2="{w-right}" y2="{h-bottom}" class="axis"/>
        {_v5058r5_segment_polylines(ordered, 'rx', 'rx-line', start_ts, end_ts, left, top, plot_w, plot_h, max_v)}
        {_v5058r5_segment_polylines(ordered, 'tx', 'tx-line', start_ts, end_ts, left, top, plot_w, plot_h, max_v)}
        {_v5058r5_x_labels(ordered, left, plot_w, h)}
        {_v5058r5_hover_zones(ordered, series, start_ts, end_ts, left, top, plot_w, plot_h)}
      </svg></div>
    </div>'''


def vm_metric_chart_svg(rows, title, series, source_note="", render_zero=False):
    ordered = _v5058r5_sorted_chart_rows(rows)
    series = [dict(item) for item in (series or [])]
    if not series:
        return ""
    for item in series:
        if item.get("key") == "guest_used_bytes":
            item["valid_key"] = "guest_stats_available"
    real_max = 0.0
    has_valid = False
    for row in ordered:
        for item in series:
            if item.get("valid_key") and not safe_int(row.get(item["valid_key"]), 0):
                continue
            has_valid = True
            real_max = max(real_max, safe_float(row.get(item["key"]), 0.0))
    if not ordered or not has_valid or (real_max <= 0 and not render_zero):
        return f'<div class="card chart-card small-chart"><h3>{escape(title)}</h3><div class="empty">No chart data in this period</div></div>'
    zero_chart = real_max <= 0
    w, h = 860, 240
    left, right, top, bottom = 74, 18, 18, 42
    plot_w, plot_h = w - left - right, h - top - bottom
    max_v = 1 if zero_chart else nice_ceiling(real_max)
    start_ts, end_ts = _v5058r5_chart_domain(ordered)
    first_kind = series[0].get("kind", "raw")
    grid, labels = [], []
    for index in range(5):
        ratio = index / 4
        y = top + plot_h - ratio * plot_h
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w-right}" y2="{y:.1f}" class="grid-line"/>')
        labels.append(f'<text x="8" y="{y+4:.1f}" class="axis-label">{escape(fmt_metric_value(max_v * ratio, first_kind))}</text>')
    lines, legends = [], []
    for index, item in enumerate(series):
        key = item["key"]
        css = item.get("class", f"metric{index + 1}")
        lines.append(_v5058r5_segment_polylines(
            ordered, key, css + "-line", start_ts, end_ts,
            left, top, plot_w, plot_h, max_v,
            valid_key=item.get("valid_key"),
        ))
        legends.append(f'<span><i class="{css}"></i>{escape(item.get("label", key))}</span>')
    # The long RAM implementation note is intentionally omitted from the UI.
    note_html = "" if title.strip().lower() == "vm ram" else (f'<span class="chart-note">{escape(source_note)}</span>' if source_note else "")
    return f'''
    <div class="card chart-card small-chart">
      <h3>{escape(title)}</h3>
      <div class="legend">{''.join(legends)}{note_html}</div>
      <div class="svg-wrap"><svg viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">
        {''.join(grid)}{''.join(labels)}
        <line x1="{left}" y1="{top}" x2="{left}" y2="{h-bottom}" class="axis"/>
        <line x1="{left}" y1="{h-bottom}" x2="{w-right}" y2="{h-bottom}" class="axis"/>
        {''.join(lines)}
        {_v5058r5_x_labels(ordered, left, plot_w, h)}
        {_v5058r5_hover_zones(ordered, series, start_ts, end_ts, left, top, plot_w, plot_h)}
      </svg></div>
    </div>'''


# Snapshot tables remain fully functional but are closed by default. They
# automatically reopen after a sort or pagination action.
_v5058r5_node_chart_table_base = node_chart_table
_v5058r5_vm_chart_table_base = vm_chart_table


def _v5058r5_strip_snapshot_hint(html):
    return re.sub(r'<div class="table-hint">.*?</div>', '', str(html or ''), count=1, flags=re.S)


def node_chart_table(rows, node, period, q="", chart_sort="time", chart_order="desc", table_sort="total", table_order="desc"):
    inner = _v5058r5_node_chart_table_base(
        rows, node, period, q=q, chart_sort=chart_sort, chart_order=chart_order,
        table_sort=table_sort, table_order=table_order,
    )
    inner = _v5058r5_strip_snapshot_hint(inner).replace(' id="real-snapshot-samples"', '', 1)
    opened = " open" if any(key in request.args for key in ("raw_page", "chart_sort", "chart_order")) else ""
    expanded = "true" if opened else "false"
    return f'''
    <details class="card snapshot-fold" id="real-snapshot-samples"{opened}>
      <summary aria-expanded="{expanded}" aria-controls="real-snapshot-samples-panel"><span>Real Snapshot Samples</span><small>{len(rows or [])} retained points · click to expand</small></summary>
      <div class="snapshot-fold-body" id="real-snapshot-samples-panel">{inner}</div>
    </details>'''


def vm_chart_table(rows, node, vm_uuid, bridge, iface, period, raw_sort="time", raw_order="desc"):
    inner = _v5058r5_vm_chart_table_base(
        rows, node, vm_uuid, bridge, iface, period,
        raw_sort=raw_sort, raw_order=raw_order,
    )
    inner = _v5058r5_strip_snapshot_hint(inner)
    opened = " open" if any(key in request.args for key in ("raw_page", "raw_sort", "raw_order", "raw_limit")) else ""
    expanded = "true" if opened else "false"
    return f'''
    <details class="card snapshot-fold" id="retained-network-snapshots"{opened}>
      <summary aria-expanded="{expanded}" aria-controls="retained-network-snapshots-panel"><span>Retained Network Snapshots</span><small>{len(rows or [])} retained points · click to expand</small></summary>
      <div class="snapshot-fold-body" id="retained-network-snapshots-panel">{inner}</div>
    </details>'''


# Compact select-based appearance controls in the upper-right header area.




V5059R1_A11Y_SCRIPT = r'''
<script id="v5059r1-snapshot-accessibility">
(function(){
  function sync(details){
    if(!details || !details.matches || !details.matches('details.snapshot-fold')) return;
    var summary=details.querySelector(':scope > summary');
    if(summary) summary.setAttribute('aria-expanded', details.open ? 'true' : 'false');
  }
  document.addEventListener('toggle',function(event){sync(event.target)},true);
  document.addEventListener('DOMContentLoaded',function(){
    document.querySelectorAll('details.snapshot-fold').forEach(sync);
  });
})();
</script>
'''


V5058R5_UI_CSS = r'''
<style id="v5058r5-professional-ui">
:root{--r5-row-y:10px;--r5-head-size:12px;--r5-cell-size:12.5px}
.wrap{width:min(100%,1920px);max-width:1920px!important;box-sizing:border-box;margin-inline:auto;padding-inline:18px!important}
.table-wrap{max-width:100%;overflow:auto;overscroll-behavior-inline:contain}
table{font-variant-numeric:tabular-nums lining-nums}
th{font-size:var(--r5-head-size)!important;font-weight:850!important;line-height:1.28!important;padding:9px 8px!important;letter-spacing:.035em!important}
td{font-size:var(--r5-cell-size)!important;line-height:1.38!important;padding:var(--r5-row-y) 8px!important}
.num,.v5058c-number{text-align:right;font-variant-numeric:tabular-nums lining-nums}
.node-name-cell>a b,.node-line>a b{font-size:15px;line-height:1.15;font-weight:900;letter-spacing:-.01em}
.node-name-cell small,.node-ipv4{margin-top:4px!important;font-size:10.5px!important;line-height:1.2!important}

/* Dashboard */
body.endpoint-index .node-dashboard-table{width:100%;min-width:1600px!important;table-layout:fixed!important}
body.endpoint-index .node-dashboard-table th:nth-child(1){width:130px}body.endpoint-index .node-dashboard-table th:nth-child(2){width:78px}body.endpoint-index .node-dashboard-table th:nth-child(3){width:130px}body.endpoint-index .node-dashboard-table th:nth-child(4){width:50px}body.endpoint-index .node-dashboard-table th:nth-child(5){width:150px}body.endpoint-index .node-dashboard-table th:nth-child(6){width:78px}body.endpoint-index .node-dashboard-table th:nth-child(7),body.endpoint-index .node-dashboard-table th:nth-child(8){width:72px}body.endpoint-index .node-dashboard-table th:nth-child(9),body.endpoint-index .node-dashboard-table th:nth-child(10){width:85px}body.endpoint-index .node-dashboard-table th:nth-child(11),body.endpoint-index .node-dashboard-table th:nth-child(12),body.endpoint-index .node-dashboard-table th:nth-child(13){width:85px}body.endpoint-index .node-dashboard-table th:nth-child(14),body.endpoint-index .node-dashboard-table th:nth-child(15){width:82px}body.endpoint-index .node-dashboard-table th:nth-child(16){width:65px}body.endpoint-index .node-dashboard-table th:nth-child(17){width:55px}body.endpoint-index .node-dashboard-table th:nth-child(18){width:150px}
body.endpoint-index .node-dashboard-table .dashboard-load-col{width:150px!important;min-width:150px!important;max-width:150px!important}
body.endpoint-index .dashboard-load-pill{width:138px!important;min-width:138px!important;max-width:138px!important;padding:6px 8px!important;font-size:12px!important}
body.endpoint-index .node-dashboard-table tbody tr{height:58px}
body.endpoint-index .node-dashboard-table td:nth-child(n+4):not(:last-child){white-space:nowrap}
body.endpoint-index .dashboard-interface-col,body.endpoint-index .dashboard-interface-cell{width:150px!important;min-width:150px!important;max-width:150px!important}
body.endpoint-index .dashboard-interface-wrap small{font-size:9.5px!important}
body.endpoint-index .table-hint{display:none!important}
body.endpoint-index .overview-card{padding:14px 16px!important}.overview-card .traffic-grid{gap:10px!important}.overview-card .traffic-box{min-height:74px!important}

/* Node and VM detail */
body.endpoint-node-page .page-hero,body.endpoint-vm-page .page-hero{padding:16px 18px!important;min-height:auto!important}
body.endpoint-node-page .page-hero h2,body.endpoint-vm-page .page-hero h2{font-size:26px!important;line-height:1.08!important;letter-spacing:-.025em}
body.endpoint-node-page .hero-meta,body.endpoint-vm-page .hero-meta{gap:7px!important;align-content:flex-start}
body.endpoint-node-page .hero-meta span,body.endpoint-vm-page .hero-meta span{padding:6px 9px!important;min-height:0!important}
body.endpoint-node-page .grid,body.endpoint-vm-page .grid,body.endpoint-node-page .vm-charts-grid,body.endpoint-vm-page .vm-charts-grid{gap:12px!important}
body.endpoint-node-page .card,body.endpoint-vm-page .card{margin-bottom:12px!important}
body.endpoint-node-page .stat,body.endpoint-vm-page .stat{min-height:82px!important;padding:11px!important}
body.endpoint-node-page .stat>b,body.endpoint-vm-page .stat>b{font-size:18px!important;line-height:1.15!important}
body.endpoint-node-page .table-vm{min-width:1680px!important;table-layout:fixed!important}
body.endpoint-node-page .table-vm .col-state{width:76px}.table-vm .col-iface{width:92px}.table-vm .col-uuid{width:250px}.table-vm .col-vcpu{width:54px}.table-vm .col-cpu{width:118px}.table-vm .col-ram{width:176px}.table-vm .col-drops,.table-vm .col-errors{width:58px}
body.endpoint-node-page .table-vm th,body.endpoint-vm-page table th{white-space:normal!important}
body.endpoint-vm-page .uuid-line,body.endpoint-node-page .uuid-cell{min-width:0}.uuid-cell>a,.uuid-line>a{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* Collapsed retained snapshots */
.snapshot-fold{padding:0!important;overflow:hidden}
.snapshot-fold>summary{list-style:none;cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:14px;padding:14px 16px;font-weight:900;font-size:14px;user-select:none}
.snapshot-fold>summary::-webkit-details-marker{display:none}.snapshot-fold>summary:before{content:"▸";font-size:13px;color:var(--brand,#2563eb);transition:transform .15s}.snapshot-fold[open]>summary:before{transform:rotate(90deg)}
.snapshot-fold>summary:focus-visible{outline:2px solid var(--brand,#2563eb);outline-offset:-3px;border-radius:8px}
.snapshot-fold>summary span{margin-right:auto}.snapshot-fold>summary small{font-weight:650;color:var(--muted,#667085);font-size:10.5px}
.snapshot-fold[open]>summary{border-bottom:1px solid var(--line,#d0d5dd)}.snapshot-fold-body{padding:12px}.snapshot-fold-body>.card{border:0!important;box-shadow:none!important;margin:0!important;padding:0!important}.snapshot-fold-body .table-hint{display:none!important}

/* Charts */
.chart-card .legend{gap:12px!important;min-height:22px}.chart-card .chart-note{font-size:9.5px!important}.chart-card svg .line{fill:none}.chart-card .svg-wrap{border-radius:8px;overflow:hidden}

/* Consumption */
.v5058c-toolbar{gap:8px!important}.v5058c-toolbar input,.v5058c-toolbar select,.v5058c-toolbar button,.v5058c-toolbar .btn{height:36px!important;box-sizing:border-box}
.v5058c-summary-grid{gap:10px!important}.v5058c-summary{min-height:108px!important;padding:12px!important}
.v5058c-table{width:100%;min-width:1160px!important;table-layout:fixed!important}.v5058c-node-table{min-width:1040px!important}
.v5058c-table th{font-size:11px!important}.v5058c-table td{font-size:12px!important;padding:9px 7px!important}
.v5058c-table .v5058c-node a,.v5058c-table .v5058c-uuid a{font-weight:850}.v5058c-triplet,.bwcons-triplet{gap:5px!important}.v5058c-number{white-space:nowrap}.v5058c-na{font-size:9.5px!important}

/* Top VM */
body.endpoint-top-page .table-top-vm{width:100%;min-width:1760px!important;table-layout:fixed!important}
body.endpoint-top-page .table-top-vm .top-rank{width:42px}.table-top-vm .top-node{width:128px!important}.table-top-vm .top-uuid{width:242px!important}.table-top-vm .top-ifaces{width:54px}.table-top-vm .top-cpu{width:112px!important}.table-top-vm .top-vcpu{width:54px}.table-top-vm .top-ram{width:170px}.table-top-vm .top-diskcap{width:184px}.table-top-vm .top-drops,.table-top-vm .top-errors{width:58px}
body.endpoint-top-page .table-top-vm th{font-size:10.5px!important;padding:8px 5px!important;white-space:normal!important}body.endpoint-top-page .table-top-vm td{font-size:11.5px!important;padding:9px 6px!important}
.cpu-dual-head small,.ram-compact-sort-head small,.disk-cap-compact-head small{display:flex!important;align-items:center;justify-content:center;gap:3px;flex-wrap:wrap;line-height:1.1!important}.cpu-sort-link,.ram-sort-link,.disk-cap-compact-head .sort-link{padding:2px 3px!important;font-size:9px!important}
body.endpoint-top-page .table-hint{display:none!important}

/* VM Abuse */
body.endpoint-vm-abuse-page .table-wrap{max-width:100%}
body.endpoint-vm-abuse-page .abuse-v48102-table,body.endpoint-vm-abuse-page .abuse-v490-table{width:100%;min-width:1380px!important;table-layout:fixed!important}
body.endpoint-vm-abuse-page .abuse-v48102-table .c-rank{width:42px}.abuse-v48102-table .c-id{width:250px!important}.abuse-v48102-table .c-reason{width:220px!important}.abuse-v48102-table .c-network{width:190px!important}.abuse-v48102-table .c-peak{width:190px!important}.abuse-v48102-table .c-cpu{width:112px!important}.abuse-v48102-table .c-ram{width:168px!important}.abuse-v48102-table .c-disk{width:185px!important}.abuse-v48102-table .c-time{width:155px!important}
body.endpoint-vm-abuse-page th{font-size:10.5px!important;white-space:normal!important;padding:8px 6px!important}body.endpoint-vm-abuse-page td{font-size:11.5px!important;padding:9px 7px!important}
body.endpoint-vm-abuse-page .abuse-reasons{display:flex;flex-wrap:wrap;gap:4px}.abuse-reasons .metric-pill{max-width:100%;white-space:normal;line-height:1.15}.reason-cell,.identity-cell{overflow-wrap:anywhere}.timeline-cell{gap:2px!important}.metric-pair{gap:5px!important}
body.endpoint-vm-abuse-page .table-hint{display:none!important}

/* Compact select appearance controls */
.appearance-controls-r5{margin-left:auto!important;display:flex!important;align-items:center!important;gap:7px!important;flex-wrap:nowrap!important}
.appearance-select{display:grid;grid-template-columns:auto minmax(88px,auto);align-items:center;gap:5px;margin:0!important;color:#cbd5e1;font-size:9px;font-weight:850;text-transform:uppercase;letter-spacing:.04em}
.appearance-select select{height:32px;min-width:96px;max-width:160px;padding:5px 26px 5px 8px;border-radius:7px;border:1px solid rgba(255,255,255,.2);background:#111827;color:#fff;font-size:11px;font-weight:750;text-transform:none;letter-spacing:0}
.appearance-select:last-child select{min-width:132px}

@media(max-width:1500px){:root{--r5-cell-size:11.5px;--r5-head-size:10.8px}.wrap{padding-inline:12px!important}.node-name-cell>a b,.node-line>a b{font-size:14px}.v5058c-table td{font-size:11px!important}}
@media(max-width:900px){.appearance-controls-r5{width:100%;justify-content:flex-end;flex-wrap:wrap!important}.appearance-select{grid-template-columns:auto minmax(100px,1fr)}.snapshot-fold>summary{align-items:flex-start;flex-wrap:wrap}.snapshot-fold>summary small{width:100%;padding-left:22px}}
</style>
'''

V5059R2_UI_CSS = r'''
<style id="v5059r2-layout-polish-only">
/* 50.5.9 r2: presentation-only layout corrections. No data, URL or behavior changes. */

/* Dashboard: reserve real space for live status and snapshot so text cannot overlap. */
body.endpoint-index .node-dashboard-table{
  width:100%;min-width:1768px!important;table-layout:fixed!important
}
body.endpoint-index .node-dashboard-table th,
body.endpoint-index .node-dashboard-table td{vertical-align:middle!important;box-sizing:border-box}
body.endpoint-index .node-dashboard-table th:nth-child(1),body.endpoint-index .node-dashboard-table td:nth-child(1){width:148px!important;padding-left:12px!important}
body.endpoint-index .node-dashboard-table th:nth-child(2),body.endpoint-index .node-dashboard-table td:nth-child(2){width:148px!important;min-width:148px!important;max-width:148px!important;overflow:hidden}
body.endpoint-index .node-dashboard-table th:nth-child(3),body.endpoint-index .node-dashboard-table td:nth-child(3){width:146px!important;min-width:146px!important;max-width:146px!important;text-align:center!important;white-space:nowrap!important}
body.endpoint-index .node-dashboard-table th:nth-child(4),body.endpoint-index .node-dashboard-table td:nth-child(4){width:50px!important}
body.endpoint-index .node-dashboard-table th:nth-child(5),body.endpoint-index .node-dashboard-table td:nth-child(5){width:150px!important}
body.endpoint-index .node-dashboard-table th:nth-child(6),body.endpoint-index .node-dashboard-table td:nth-child(6){width:82px!important}
body.endpoint-index .node-dashboard-table th:nth-child(7),body.endpoint-index .node-dashboard-table td:nth-child(7),body.endpoint-index .node-dashboard-table th:nth-child(8),body.endpoint-index .node-dashboard-table td:nth-child(8){width:76px!important}
body.endpoint-index .node-dashboard-table th:nth-child(9),body.endpoint-index .node-dashboard-table td:nth-child(9),body.endpoint-index .node-dashboard-table th:nth-child(10),body.endpoint-index .node-dashboard-table td:nth-child(10){width:94px!important}
body.endpoint-index .node-dashboard-table th:nth-child(11),body.endpoint-index .node-dashboard-table td:nth-child(11),body.endpoint-index .node-dashboard-table th:nth-child(12),body.endpoint-index .node-dashboard-table td:nth-child(12),body.endpoint-index .node-dashboard-table th:nth-child(13),body.endpoint-index .node-dashboard-table td:nth-child(13){width:92px!important}
body.endpoint-index .node-dashboard-table th:nth-child(14),body.endpoint-index .node-dashboard-table td:nth-child(14),body.endpoint-index .node-dashboard-table th:nth-child(15),body.endpoint-index .node-dashboard-table td:nth-child(15){width:90px!important}
body.endpoint-index .node-dashboard-table th:nth-child(16),body.endpoint-index .node-dashboard-table td:nth-child(16){width:58px!important}
body.endpoint-index .node-dashboard-table th:nth-child(17),body.endpoint-index .node-dashboard-table td:nth-child(17){width:48px!important}
body.endpoint-index .node-dashboard-table th:nth-child(18),body.endpoint-index .node-dashboard-table td:nth-child(18){width:142px!important}
body.endpoint-index .node-dashboard-table td:nth-child(2) .status{
  display:inline-block!important;max-width:100%;font-size:13.5px!important;line-height:1.25!important;
  white-space:normal!important;overflow:hidden;overflow-wrap:normal;vertical-align:middle
}
body.endpoint-index .node-dashboard-table td:nth-child(3){font-size:11px!important;letter-spacing:-.015em}
body.endpoint-index .node-dashboard-table .node-name-cell{min-width:0}
body.endpoint-index .node-dashboard-table .node-name-cell>a,
body.endpoint-index .node-dashboard-table .node-name-cell small{max-width:100%;overflow:hidden;text-overflow:ellipsis}
body.endpoint-index .node-dashboard-table .dashboard-load-col{width:150px!important;min-width:150px!important;max-width:150px!important}
body.endpoint-index .node-dashboard-table .dashboard-load-pill{width:138px!important;min-width:138px!important;max-width:138px!important;margin-inline:auto}

/* Top VM: compact leading columns and keep compound headers on one centered line. */
body.endpoint-top-page .table-top-vm{width:100%;min-width:1940px!important;table-layout:fixed!important}
body.endpoint-top-page .table-top-vm col.top-rank{width:30px!important}
body.endpoint-top-page .table-top-vm col.top-node{width:132px!important}
body.endpoint-top-page .table-top-vm col.top-uuid{width:220px!important}
body.endpoint-top-page .table-top-vm col.top-ifaces{width:50px!important}
body.endpoint-top-page .table-top-vm col.top-public,body.endpoint-top-page .table-top-vm col.top-private{width:76px!important}
body.endpoint-top-page .table-top-vm col.top-total{width:86px!important}
body.endpoint-top-page .table-top-vm col.top-mbps{width:70px!important}
body.endpoint-top-page .table-top-vm col.top-peakmbps{width:74px!important}
body.endpoint-top-page .table-top-vm col.top-pps{width:76px!important}
body.endpoint-top-page .table-top-vm col.top-peakpps{width:80px!important}
body.endpoint-top-page .table-top-vm col.top-sample{width:90px!important}
body.endpoint-top-page .table-top-vm col.top-cpu{width:114px!important}
body.endpoint-top-page .table-top-vm col.top-vcpu{width:46px!important}
body.endpoint-top-page .table-top-vm col.top-ram{width:180px!important}
body.endpoint-top-page .table-top-vm col.top-diskcap{width:220px!important}
body.endpoint-top-page .table-top-vm col.top-diskr,body.endpoint-top-page .table-top-vm col.top-diskw{width:84px!important}
body.endpoint-top-page .table-top-vm col.top-push{width:60px!important}
body.endpoint-top-page .table-top-vm col.top-drops{width:46px!important}
body.endpoint-top-page .table-top-vm col.top-errors{width:42px!important}
body.endpoint-top-page .table-top-vm th,body.endpoint-top-page .table-top-vm td{vertical-align:middle!important}
body.endpoint-top-page .table-top-vm th:first-child,body.endpoint-top-page .table-top-vm td:first-child{padding-left:3px!important;padding-right:3px!important;text-align:center!important}
body.endpoint-top-page .table-top-vm th:nth-child(2),body.endpoint-top-page .table-top-vm td:nth-child(2){padding-left:7px!important}
body.endpoint-top-page .cpu-dual-head,body.endpoint-top-page .ram-compact-sort-head,body.endpoint-top-page .disk-capacity-sort-head{text-align:center!important}
body.endpoint-top-page .cpu-dual-head>div,body.endpoint-top-page .ram-compact-head,body.endpoint-top-page .disk-cap-compact-head{width:100%;justify-items:center;align-items:center;text-align:center}
body.endpoint-top-page .cpu-dual-head small,
body.endpoint-top-page .disk-cap-compact-head small{
  display:inline-flex!important;flex-wrap:nowrap!important;align-items:center!important;justify-content:center!important;
  gap:4px!important;width:auto!important;max-width:100%;white-space:nowrap!important;line-height:1.1!important
}
body.endpoint-top-page .disk-cap-compact-head>div{font-size:9.5px!important;white-space:nowrap!important}
body.endpoint-top-page .disk-cap-sort-link{font-size:8.5px!important;padding:1px 2px!important;white-space:nowrap!important}
body.endpoint-top-page .cpu-dual-cell,body.endpoint-top-page .ram-cell,body.endpoint-top-page .disk-cap-cell{text-align:center!important}
body.endpoint-top-page .cpu-dual-cell .cpu-meter{width:96px;max-width:100%;margin:6px auto 0!important}
body.endpoint-top-page .vm-ram-compact{margin-inline:auto!important;text-align:center!important;min-width:0!important;width:156px;max-width:100%}
body.endpoint-top-page .vm-ram-compact .ram-meter{width:100%;margin-left:auto!important;margin-right:auto!important}
body.endpoint-top-page .top-disk-capacity{text-align:center!important;margin-inline:auto;max-width:194px}
body.endpoint-top-page .top-disk-capacity .disk-cap-meter{margin-left:auto;margin-right:auto}

/* Consumption: explicit identity/metric proportions and a toolbar grid matching each tab. */
body.endpoint-bandwidth-consumption-page .v5058c-toolbar:has(select[name="node"]){grid-template-columns:minmax(360px,1.45fr) minmax(185px,.72fr) minmax(175px,.68fr) auto auto auto!important}
body.endpoint-bandwidth-consumption-page .v5058c-toolbar:not(:has(select[name="node"])){grid-template-columns:minmax(360px,1.6fr) minmax(190px,.72fr) auto auto auto!important}
body.endpoint-bandwidth-consumption-page .v5058c-table{width:100%!important;table-layout:auto!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table{min-width:1340px!important}
body.endpoint-bandwidth-consumption-page .v5058c-node-table{min-width:1180px!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table thead tr:first-child th:nth-child(1),body.endpoint-bandwidth-consumption-page .v5058c-vm-table tbody td:nth-child(1){width:220px!important;min-width:220px!important;max-width:260px!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table thead tr:first-child th:nth-child(2),body.endpoint-bandwidth-consumption-page .v5058c-vm-table tbody td:nth-child(2){width:190px!important;min-width:190px!important;max-width:230px!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table thead tr:first-child th:nth-child(3),body.endpoint-bandwidth-consumption-page .v5058c-vm-table thead tr:first-child th:nth-child(4){min-width:330px!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table tbody td:nth-child(n+3):nth-child(-n+8){width:108px!important;min-width:96px!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table thead tr:first-child th:nth-child(5),body.endpoint-bandwidth-consumption-page .v5058c-vm-table tbody td:nth-child(9){width:100px!important;min-width:100px!important}
body.endpoint-bandwidth-consumption-page .v5058c-vm-table thead tr:first-child th:nth-child(6),body.endpoint-bandwidth-consumption-page .v5058c-vm-table tbody td:nth-child(10){width:150px!important;min-width:150px!important}
body.endpoint-bandwidth-consumption-page .v5058c-node-table thead tr:first-child th:nth-child(1),body.endpoint-bandwidth-consumption-page .v5058c-node-table tbody td:nth-child(1){width:200px!important;min-width:200px!important;max-width:250px!important}
body.endpoint-bandwidth-consumption-page .v5058c-node-table thead tr:first-child th:nth-child(2),body.endpoint-bandwidth-consumption-page .v5058c-node-table thead tr:first-child th:nth-child(3){min-width:330px!important}
body.endpoint-bandwidth-consumption-page .v5058c-node-table tbody td:nth-child(n+2):nth-child(-n+7){width:108px!important;min-width:96px!important}
body.endpoint-bandwidth-consumption-page .v5058c-node-table thead tr:first-child th:nth-child(4),body.endpoint-bandwidth-consumption-page .v5058c-node-table tbody td:nth-child(8){width:100px!important;min-width:100px!important}
body.endpoint-bandwidth-consumption-page .v5058c-node-table thead tr:first-child th:nth-child(5),body.endpoint-bandwidth-consumption-page .v5058c-node-table tbody td:nth-child(9){width:150px!important;min-width:150px!important}
body.endpoint-bandwidth-consumption-page .v5058c-table th{padding-left:8px!important;padding-right:8px!important}
body.endpoint-bandwidth-consumption-page .v5058c-table td{padding-left:10px!important;padding-right:10px!important}
body.endpoint-bandwidth-consumption-page .v5058c-table .v5058c-uuid .uuid-cell{max-width:none!important;min-width:0}
body.endpoint-bandwidth-consumption-page .v5058c-table .v5058c-node>a b{font-size:12.5px;line-height:1.15}
body.endpoint-bandwidth-consumption-page .v5058c-table .v5058c-total{text-align:right!important}
body.endpoint-bandwidth-consumption-page .v5058c-table td:nth-last-child(2){text-align:center!important}
body.endpoint-bandwidth-consumption-page .v5058c-table td:nth-last-child(2) .status{font-size:13px!important;font-weight:850!important;line-height:1.15!important;white-space:nowrap!important}
body.endpoint-bandwidth-consumption-page .v5058c-latest{text-align:right!important;padding-right:14px!important}
body.endpoint-bandwidth-consumption-page .v5058c-latest .v5058c-time{font-size:10.5px!important;white-space:nowrap}
body.endpoint-bandwidth-consumption-page .v5058c-na{display:inline-block;min-width:78px;text-align:center;opacity:.78}

/* Node Health: comfortable first-column inset and balanced operational columns. */
body.endpoint-node-health-page .top-card{padding:14px 16px!important}
body.endpoint-node-health-page .top-card .top-grid{gap:18px!important}
body.endpoint-node-health-page .top-card .search{max-width:520px;margin-top:10px!important}
body.endpoint-node-health-page .card>table{width:100%;table-layout:fixed}
body.endpoint-node-health-page .card>table th,body.endpoint-node-health-page .card>table td{vertical-align:middle!important}
body.endpoint-node-health-page .card>table th:nth-child(1),body.endpoint-node-health-page .card>table td:nth-child(1){width:220px!important;padding-left:18px!important}
body.endpoint-node-health-page .card>table th:nth-child(2),body.endpoint-node-health-page .card>table td:nth-child(2){width:130px!important}
body.endpoint-node-health-page .card>table th:nth-child(3),body.endpoint-node-health-page .card>table td:nth-child(3){width:170px!important;white-space:nowrap}
body.endpoint-node-health-page .card>table th:nth-child(4),body.endpoint-node-health-page .card>table td:nth-child(4){width:90px!important}
body.endpoint-node-health-page .card>table th:nth-child(5),body.endpoint-node-health-page .card>table td:nth-child(5){width:110px!important;text-align:center}
body.endpoint-node-health-page .card>table th:nth-child(6),body.endpoint-node-health-page .card>table td:nth-child(6){width:70px!important;text-align:center}
body.endpoint-node-health-page .card>table th:nth-child(7),body.endpoint-node-health-page .card>table td:nth-child(7){width:90px!important;text-align:center}
body.endpoint-node-health-page .card>table th:nth-child(8),body.endpoint-node-health-page .card>table td:nth-child(8){width:120px!important;text-align:right;padding-right:18px!important}
body.endpoint-node-health-page .card>table .node-name-cell>a b{font-size:14px}
body.endpoint-node-health-page .card>table .node-name-cell small{margin-top:3px!important}

@media(max-width:1500px){
  body.endpoint-bandwidth-consumption-page .v5058c-toolbar:has(select[name="node"]){grid-template-columns:minmax(280px,1fr) minmax(145px,.52fr) minmax(145px,.5fr) auto auto auto!important}
  body.endpoint-bandwidth-consumption-page .v5058c-toolbar:not(:has(select[name="node"])){grid-template-columns:minmax(300px,1fr) minmax(170px,.6fr) auto auto auto!important}
}
</style>
'''


_page_v5058r5_base = page


def page(title, content):
    response = _page_v5058r5_base(title, content)
    try:
        html = response.get_data(as_text=True)
        # Remove transient guestfs names from rendered output only.
        html = re.sub(r'guestfs-[A-Za-z0-9_.:-]+', '-', html, flags=re.I)
        html = html.replace('</head>', V5058R5_UI_CSS + V5059R2_UI_CSS + V5059R1_A11Y_SCRIPT + '</head>', 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply r5 professional UI layer")
    return response


# ---------------------------------------------------------------------------
