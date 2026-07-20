def period_label(period):
    return PERIOD_LABELS.get(period, period)

def period_seconds(period):
    return PERIODS.get(period, PERIODS["1h"])

def clean_period(period):
    period = PERIOD_ALIASES.get(str(period or ""), str(period or ""))
    return period if period in PERIODS else "1h"

def clean_chart_table_sort(sort_by):
    # Raw Data table in the VM chart page.
    allowed = {"time", "rx", "tx", "total", "mbps", "peakmbps", "pps", "peakpps", "sample", "drops", "errors"}
    return sort_by if sort_by in allowed else "time"

def clean_node_chart_sort(sort_by):
    # Raw Data table in the node chart page.
    allowed = {"time", "public", "private", "rx", "tx", "total"}
    return sort_by if sort_by in allowed else "time"

def clean_node_sort(sort_by):
    """Dashboard sort whitelist for coherent exact-snapshot columns."""
    allowed = {
        "node", "last_push", "snapshot", "vm", "load", "uptime",
        "cpu", "ram", "diskr", "diskw", "public", "private", "total",
        "pps", "public_pps", "private_pps", "drops", "errors", "source",
    }
    return sort_by if sort_by in allowed else "node"

def clean_sort_order(order):
    return "asc" if str(order).lower() == "asc" else "desc"

def reverse_order(order):
    return "asc" if clean_sort_order(order) == "desc" else "desc"

def range_for_period(period):
    end = now_ts()
    start = end - period_seconds(period)
    return start, end

def bucket_for(ts):
    ts = int(ts)
    return (ts // CACHE_BUCKET_SECONDS) * CACHE_BUCKET_SECONDS

def _snapshot_bucket_candidates_sql(node_scoped=True):
    """Compatibility fallback for DBs that have not backfilled snapshot index."""
    where = " WHERE node=?" if node_scoped else ""
    return f"""
        SELECT bucket FROM node_stats{where}
        UNION
        SELECT bucket FROM vm_perf_stats{where}
        UNION
        SELECT bucket FROM node_host_stats{where}
        UNION
        SELECT bucket FROM node_physical_net_stats{where}
    """

def resolve_snapshot_bucket(conn, period, node=None):
    """Resolve a real retained snapshot without silently substituting current data.

    The newest bucket anchors the lookback. If the requested point predates the
    available history, select the oldest retained bucket instead of the newest.
    That makes a 2-month request on a 2-day-old installation visibly show the
    oldest available sample rather than pretending current data is 2 months old.
    """
    period = clean_period(period)
    if node:
        latest_row = conn.execute(
            "SELECT MAX(bucket) FROM node_push_snapshots WHERE node=?", (node,)
        ).fetchone()
    else:
        latest_row = conn.execute("SELECT MAX(bucket) FROM node_push_snapshots").fetchone()
    latest = int((latest_row or [0])[0] or 0)

    if latest <= 0:
        node_scoped = bool(node)
        union_sql = _snapshot_bucket_candidates_sql(node_scoped=node_scoped)
        bind = [node, node, node, node] if node_scoped else []
        latest_row = conn.execute(f"SELECT MAX(bucket) FROM ({union_sql})", bind).fetchone()
        latest = int((latest_row or [0])[0] or 0)
        if latest <= 0:
            return 0, 0
        target = latest - max(0, period_seconds(period) - CACHE_BUCKET_SECONDS)
        row = conn.execute(
            f"SELECT MAX(bucket) FROM ({union_sql}) WHERE bucket<=?", bind + [target]
        ).fetchone()
        selected = int((row or [0])[0] or 0)
        if not selected:
            row = conn.execute(f"SELECT MIN(bucket) FROM ({union_sql})", bind).fetchone()
            selected = int((row or [0])[0] or 0)
        return selected, latest

    target = latest - max(0, period_seconds(period) - CACHE_BUCKET_SECONDS)
    if node:
        row = conn.execute(
            "SELECT MAX(bucket) FROM node_push_snapshots WHERE node=? AND bucket<=?",
            (node, target),
        ).fetchone()
        selected = int((row or [0])[0] or 0)
        if not selected:
            row = conn.execute(
                "SELECT MIN(bucket) FROM node_push_snapshots WHERE node=?", (node,)
            ).fetchone()
    else:
        row = conn.execute(
            "SELECT MAX(bucket) FROM node_push_snapshots WHERE bucket<=?", (target,)
        ).fetchone()
        selected = int((row or [0])[0] or 0)
        if not selected:
            row = conn.execute("SELECT MIN(bucket) FROM node_push_snapshots").fetchone()
    selected = selected or int((row or [0])[0] or 0)
    return selected, latest

def resolve_table_snapshot_bucket(conn, table, node, target_bucket):
    """Find the nearest bucket for one metric table around a selected snapshot."""
    if not target_bucket:
        return 0
    row = conn.execute(
        f"""
        SELECT bucket
        FROM {table}
        WHERE node=? AND bucket BETWEEN ? AND ?
        GROUP BY bucket
        ORDER BY ABS(bucket - ?) ASC, bucket DESC
        LIMIT 1
        """,
        (node, target_bucket - CACHE_BUCKET_SECONDS, target_bucket + CACHE_BUCKET_SECONDS, target_bucket),
    ).fetchone()
    return int((row or [0])[0] or 0)

def human(v):
    v = float(v or 0)
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if v < 1024:
            return f"{v:.2f} {unit}"
        v /= 1024
    return f"{v:.2f} PB"

def human_rate(v):
    return f"{human(v)}/s"

def fmt_pps(packets, seconds=None):
    seconds = float(seconds or CACHE_BUCKET_SECONDS or 300)
    if seconds <= 0:
        seconds = CACHE_BUCKET_SECONDS
    return fmt_pps_value(float(packets or 0) / seconds)

def fmt_pps_value(pps):
    pps = float(pps or 0)
    if pps >= 1000000:
        return f"{pps/1000000:.2f}M/s"
    if pps >= 1000:
        return f"{pps/1000:.2f}k/s"
    return f"{pps:.2f}/s"

def fmt_ram_pair(rss_kib, current_kib):
    rss_kib = float(rss_kib or 0)
    current_kib = float(current_kib or 0)
    if rss_kib <= 0 and current_kib <= 0:
        return "-"
    if current_kib > 0:
        return f"{fmt_kib(rss_kib)} / {fmt_kib(current_kib)}"
    return fmt_kib(rss_kib)

def fmt_metric_value(v, kind="raw"):
    v = float(v or 0)
    if kind == "bytes":
        return human(v)
    if kind == "rate":
        return human_rate(v)
    if kind == "pps":
        return fmt_pps_value(v)
    if kind == "mbps":
        return f"{v:.2f} Mbps"
    if kind == "seconds":
        return f"{int(v)} s"
    if kind == "percent":
        return fmt_percent(v)
    if kind == "count":
        return str(int(v))
    if kind == "integer":
        return str(int(v))
    return f"{v:.2f}"

def fmt_mbps(bytes_delta, seconds=None):
    seconds = float(seconds or CACHE_BUCKET_SECONDS or 300)
    if seconds <= 0:
        seconds = CACHE_BUCKET_SECONDS
    return f"{(float(bytes_delta or 0) * 8 / seconds / 1000000):.2f} Mbps"

def fmt_percent(v):
    return f"{float(v or 0):.1f}%"

def pct_clamp(v):
    return max(0.0, min(100.0, float(v or 0)))

def pct_of_ref(value, ref):
    ref = float(ref or 0)
    if ref <= 0:
        return 0.0
    return pct_clamp(float(value or 0) * 100.0 / ref)

def ram_percent(mem_used, mem_total):
    mem_total = float(mem_total or 0)
    if mem_total <= 0:
        return 0.0
    return pct_clamp(float(mem_used or 0) * 100.0 / mem_total)

def vm_core_cpu_percent(cpu_percent, vcpu_current=0):
    """Return VM CPU in core-based percent: 100% = 1 full core, 400% = 4 full cores.

    Older agents may report CPU normalized to the VM's vCPU count, capped around 100.
    In that case multiply by vCPU count. If a future/new agent already reports >100,
    keep the raw value to avoid double multiplying.
    """
    cpu = max(0.0, float(cpu_percent or 0))
    vcpu = max(1, safe_int(vcpu_current, 1))
    if cpu <= 100.0:
        return cpu * vcpu
    return cpu

def fmt_vm_cpu(cpu_percent, vcpu_current=0):
    return f"{vm_core_cpu_percent(cpu_percent, vcpu_current):.1f}%"

def fmt_vm_cpu_with_vcpu(cpu_percent, vcpu_current=0):
    return f"{fmt_vm_cpu(cpu_percent, vcpu_current)} / {int(vcpu_current or 0)} vCPU"

def fmt_kib(v):
    return human(float(v or 0) * 1024)

def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def clean_network_sample_quality(value):
    value = str(value or "LEGACY").strip().upper()
    return value if value in {"GOOD", "DEGRADED", "POOR", "NO_DATA", "LEGACY"} else "LEGACY"

def network_sample_quality_rank(value):
    return {"LEGACY": 0, "NO_DATA": 0, "GOOD": 1, "DEGRADED": 2, "POOR": 3}.get(
        clean_network_sample_quality(value), 0
    )

def network_quality_from_rank(value):
    value = safe_int(value, 0)
    return "POOR" if value >= 3 else "DEGRADED" if value == 2 else "GOOD" if value == 1 else "LEGACY"

def network_sample_badge(quality, actual=0, expected=0, max_gap=0):
    quality = clean_network_sample_quality(quality)
    actual = max(0, safe_int(actual, 0))
    expected = max(0, safe_int(expected, 0))
    max_gap = max(0.0, safe_float(max_gap, 0.0))
    css = {"GOOD": "active", "DEGRADED": "yellow", "POOR": "red", "NO_DATA": "stale", "LEGACY": "stale"}.get(quality, "stale")
    title = f"Network samples {actual}/{expected}; max gap {max_gap:.1f}s"
    return f'<span class="vm-state {css}" title="{escape(title, quote=True)}">{escape(quality)}</span>'

def clean_ip_sequence(value):
    """Return a compact, unique list of address/CIDR strings from agent JSON."""
    if value is None:
        values = []
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]

    result = []
    seen = set()
    for item in values:
        item = str(item or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item[:128])
        if len(result) >= 32:
            break
    return result

def decode_ip_json(value):
    try:
        decoded = json.loads(value or "[]")
    except Exception:
        decoded = []
    return clean_ip_sequence(decoded)

def like_pattern(q):
    q = (q or "").strip()
    return f"%{q}%"

def clean_vm_status(status):
    status = (status or "active").strip().lower()
    aliases = {
        "pending": "pending_migration",
        "pending-migration": "pending_migration",
        "pending_migrate": "pending_migration",
        "move": "pending_migration",
        "moved": "migrated",
        "stale": "missing",
    }
    status = aliases.get(status, status)
    allowed = {"active", "missing", "pending_migration", "migrated", "purged", "all"}
    return status if status in allowed else "active"

def vm_status_label(status):
    status = clean_vm_status(status)
    return {
        "active": "Active",
        "missing": "Missing",
        "pending_migration": "Pending",
        "migrated": "Migrated",
        "purged": "Purged",
        "all": "All",
    }.get(status, "Active")

def vm_status_sql(alias="vi", status="active"):
    """Closed-list SQL fragment, safe because status is normalized."""
    status = clean_vm_status(status)
    col = f"COALESCE({alias}.status, 'active')"
    if status == "all":
        return f"AND {col} != 'hidden'"
    if status == "active":
        return f"AND {col} = 'active' AND {alias}.deleted_at IS NULL"
    if status == "pending_migration":
        return f"AND {col} = 'pending_migration' AND {alias}.deleted_at IS NULL"
    if status == "missing":
        return f"AND {col} = 'missing' AND {alias}.deleted_at IS NULL"
    if status == "migrated":
        return f"AND {col} = 'migrated' AND {alias}.deleted_at IS NULL"
    if status == "purged":
        return f"AND {col} = 'purged'"
    return f"AND {col} = 'active' AND {alias}.deleted_at IS NULL"

def vm_status_badge(status, live=None):
    status = clean_vm_status(status)
    if status == "active" and live == "stale":
        return '<span class="vm-state stale">STALE</span>'
    if status == "active":
        return '<span class="vm-state active">ACTIVE</span>'
    if status == "missing":
        return '<span class="vm-state stale">MISSING</span>'
    if status == "pending_migration":
        return '<span class="vm-state yellow">PENDING</span>'
    if status == "migrated":
        return '<span class="vm-state migrated">MIGRATED</span>'
    if status == "purged":
        return '<span class="vm-state red">PURGED</span>'
    return f'<span class="vm-state">{escape(vm_status_label(status).upper())}</span>'

def vm_status_tabs(node, period, q, sort_by, sort_order, vm_status):
    current = clean_vm_status(vm_status)
    items = [
        ("active", "Active"),
        ("missing", "Missing"),
        ("pending_migration", "Pending"),
        ("migrated", "Migrated"),
        ("purged", "Purged"),
        ("all", "All"),
    ]
    links = []
    for key, label in items:
        href = url_for(
            "node_page",
            node=node,
            period=period,
            q=q,
            sort=sort_by,
            order=sort_order,
            vm_status=key,
        )
        cls = "active" if current == key else ""
        links.append(f'<a class="{cls}" href="{escape(href, quote=True)}">{escape(label)}</a>')
    return f"""
    <div class="card status-filter-card">
        <div class="table-title-row">
            <h3>VM Status Filter</h3>
            <div class="count-badges">
                <span>Current <b>{escape(vm_status_label(current))}</b></span>
                <span>Migration confirm <b>{VM_MIGRATION_CONFIRM_PUSHES} pushes</b></span>
                <span>Purge migrated <b>{int(VM_MIGRATION_PURGE_SECONDS / 86400)}d</b></span>
            </div>
        </div>
        <div class="periods">{''.join(links)}</div>
        <div class="admin-note">Migrated VM rows are kept for review, then dashboard/cache rows are purged automatically. Raw usage history is kept unless BW_VM_MIGRATION_PURGE_RAW_HISTORY=1.</div>
    </div>
    """

def _presence_upsert_seen(conn, vm_uuid, node, seen_ts, iface="-", bridge="-"):
    conn.execute("""
        INSERT INTO vm_node_presence(
            vm_uuid, node, first_seen, last_seen, last_push, missing_since,
            missing_count, present_count, status, pending_node, migrated_to,
            migrated_at, purged_at, last_iface, last_bridge, alert_flags
        )
        VALUES (?, ?, ?, ?, ?, NULL, 0, 1, 'active', NULL, NULL, NULL, NULL, ?, ?, '')
        ON CONFLICT(vm_uuid, node)
        DO UPDATE SET
            last_seen=MAX(vm_node_presence.last_seen, excluded.last_seen),
            last_push=excluded.last_push,
            missing_since=NULL,
            missing_count=0,
            present_count=vm_node_presence.present_count + 1,
            status=CASE
                WHEN vm_node_presence.status='purged' THEN 'active'
                WHEN vm_node_presence.status='migrated' THEN 'active'
                ELSE 'active'
            END,
            pending_node=NULL,
            migrated_to=NULL,
            migrated_at=NULL,
            purged_at=NULL,
            last_iface=excluded.last_iface,
            last_bridge=excluded.last_bridge,
            alert_flags=''
    """, (vm_uuid, node, seen_ts, seen_ts, seen_ts, iface, bridge))

    conn.execute("""
        INSERT INTO vm_inventory(node, vm_uuid, first_seen, last_seen, last_iface, last_bridge, status, hidden_at, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, 'active', NULL, NULL)
        ON CONFLICT(node, vm_uuid)
        DO UPDATE SET
            last_seen=MAX(vm_inventory.last_seen, excluded.last_seen),
            last_iface=excluded.last_iface,
            last_bridge=excluded.last_bridge,
            status=CASE
                WHEN vm_inventory.status='hidden' THEN 'hidden'
                ELSE 'active'
            END,
            hidden_at=CASE
                WHEN vm_inventory.status='hidden' THEN vm_inventory.hidden_at
                ELSE NULL
            END,
            deleted_at=CASE
                WHEN vm_inventory.status='hidden' THEN vm_inventory.deleted_at
                ELSE NULL
            END
    """, (node, vm_uuid, seen_ts, seen_ts, iface, bridge))

def _mark_missing_on_node(conn, node, seen_set, seen_ts):
    rows = conn.execute("""
        SELECT vm_uuid, missing_since, missing_count, status
        FROM vm_node_presence
        WHERE node=?
          AND status IN ('active', 'pending_migration')
    """, (node,)).fetchall()
    for vm_uuid, missing_since, missing_count, status in rows:
        if vm_uuid in seen_set:
            continue
        ms = int(missing_since or seen_ts)
        mc = int(missing_count or 0) + 1
        conn.execute("""
            UPDATE vm_node_presence
            SET status='missing', missing_since=?, missing_count=?, last_push=?, alert_flags=?
            WHERE vm_uuid=? AND node=?
        """, (ms, mc, seen_ts, f"MISSING:{mc}", vm_uuid, node))
        conn.execute("""
            UPDATE vm_inventory
            SET status='missing', hidden_at=NULL, deleted_at=NULL
            WHERE vm_uuid=? AND node=? AND COALESCE(status, 'active') != 'hidden'
        """, (vm_uuid, node))

def _old_node_missing_enough(conn, vm_uuid, old_node, seen_ts):
    row = conn.execute("""
        SELECT status, missing_since, missing_count, last_seen
        FROM vm_node_presence
        WHERE vm_uuid=? AND node=?
    """, (vm_uuid, old_node)).fetchone()
    if not row:
        return False, "old-node presence not confirmed missing"
    status, missing_since, missing_count, old_last_seen = row
    missing_count = int(missing_count or 0)
    missing_since = int(missing_since or 0)
    if status in ("missing", "migrated", "purged") and missing_count >= VM_MIGRATION_CONFIRM_PUSHES:
        return True, f"old node missing for {missing_count} pushes"
    if status in ("missing", "migrated", "purged") and missing_since and (seen_ts - missing_since) >= VM_MIGRATION_CONFIRM_SECONDS:
        return True, f"old node missing since {fmt_full(missing_since)}"
    return False, f"waiting old node missing confirmation ({missing_count}/{VM_MIGRATION_CONFIRM_PUSHES} pushes)"

def _create_or_update_location(conn, vm_uuid, node, seen_ts, iface="-", bridge="-"):
    old = conn.execute("""
        SELECT node, last_seen, move_count
        FROM vm_location_latest
        WHERE vm_uuid=?
    """, (vm_uuid,)).fetchone()

    if not old:
        conn.execute("""
            INSERT INTO vm_location_latest(
                vm_uuid, node, first_seen, last_seen, previous_node, moved_at,
                move_count, last_iface, last_bridge, alert_level, alert_flags
            )
            VALUES (?, ?, ?, ?, NULL, NULL, 0, ?, ?, 'ok', '')
        """, (vm_uuid, node, seen_ts, seen_ts, iface, bridge))
        return

    old_node, old_last_seen, move_count = old
    move_count = int(move_count or 0)
    if old_node == node:
        conn.execute("""
            UPDATE vm_location_latest
            SET last_seen=MAX(last_seen, ?),
                last_iface=?,
                last_bridge=?,
                alert_level='ok',
                alert_flags=''
            WHERE vm_uuid=?
        """, (seen_ts, iface, bridge, vm_uuid))
        return

    confirmed, reason = _old_node_missing_enough(conn, vm_uuid, old_node, seen_ts)
    if not confirmed:
        conn.execute("""
            UPDATE vm_node_presence
            SET status='pending_migration', pending_node=?, alert_flags=?
            WHERE vm_uuid=? AND node=?
        """, (node, f"PENDING_TO:{node}; {reason}", vm_uuid, old_node))
        conn.execute("""
            UPDATE vm_node_presence
            SET status='pending_migration', pending_node=?, alert_flags=?
            WHERE vm_uuid=? AND node=?
        """, (old_node, f"PENDING_FROM:{old_node}; {reason}", vm_uuid, node))
        conn.execute("""
            UPDATE vm_inventory
            SET status='pending_migration', hidden_at=NULL, deleted_at=NULL
            WHERE vm_uuid=? AND node IN (?, ?) AND COALESCE(status, 'active') != 'hidden'
        """, (vm_uuid, old_node, node))
        conn.execute("""
            UPDATE vm_location_latest
            SET last_seen=MAX(last_seen, ?),
                alert_level='pending_migration',
                alert_flags=?
            WHERE vm_uuid=?
        """, (seen_ts, f"PENDING_MOVE:{old_node}->{node}; {reason}", vm_uuid))
        return

    # Confirmed migration: old node has missed this VM for enough pushes.
    conn.execute("""
        INSERT INTO vm_migration_events(
            time, vm_uuid, old_node, new_node, old_last_seen, new_seen, detail
        )
        SELECT ?, ?, ?, ?, ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM vm_migration_events
            WHERE vm_uuid=? AND old_node=? AND new_node=? AND time>=?
        )
    """, (
        seen_ts, vm_uuid, old_node, node, old_last_seen, seen_ts,
        f"VM moved from {old_node} to {node}; {reason}",
        vm_uuid, old_node, node, seen_ts - 86400,
    ))

    conn.execute("""
        UPDATE vm_node_presence
        SET status='migrated', migrated_to=?, migrated_at=?, alert_flags=?
        WHERE vm_uuid=? AND node=?
    """, (node, seen_ts, f"MIGRATED_TO:{node}", vm_uuid, old_node))

    conn.execute("""
        UPDATE vm_inventory
        SET status='migrated', hidden_at=NULL, deleted_at=NULL
        WHERE node=? AND vm_uuid=? AND COALESCE(status, 'active') != 'hidden'
    """, (old_node, vm_uuid))

    conn.execute("""
        UPDATE vm_latest_metrics
        SET alert_level='migrated', alert_flags=?
        WHERE node=? AND vm_uuid=?
    """, (f"MIGRATED_TO:{node}", old_node, vm_uuid))

    conn.execute("""
        UPDATE vm_location_latest
        SET node=?, previous_node=?, moved_at=?, move_count=?, last_seen=?,
            last_iface=?, last_bridge=?, alert_level='migrated', alert_flags=?
        WHERE vm_uuid=?
    """, (node, old_node, seen_ts, move_count + 1, seen_ts, iface, bridge, f"MIGRATED_FROM:{old_node}", vm_uuid))

def process_node_vm_presence(conn, node, seen_vm_locations, seen_ts, inventory_complete=False):
    """Refresh seen VMs; mark unseen VMs missing only after a complete inventory."""
    seen_set = set()
    for vm_uuid, loc in (seen_vm_locations or {}).items():
        vm_uuid = str(vm_uuid or "").strip()
        if not vm_uuid or vm_uuid == "-":
            continue
        seen_set.add(vm_uuid)
        _presence_upsert_seen(conn, vm_uuid, node, seen_ts, str(loc.get("iface") or "-"), str(loc.get("bridge") or "-"))

    if inventory_complete:
        _mark_missing_on_node(conn, node, seen_set, seen_ts)

    for vm_uuid in seen_set:
        loc = seen_vm_locations.get(vm_uuid) or {}
        _create_or_update_location(conn, vm_uuid, node, seen_ts, str(loc.get("iface") or "-"), str(loc.get("bridge") or "-"))

def auto_purge_migrated_vms(conn=None):
    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        cutoff = now_ts() - VM_MIGRATION_PURGE_SECONDS
        rows = conn.execute("""
            SELECT vm_uuid, node, migrated_to, migrated_at
            FROM vm_node_presence
            WHERE status='migrated'
              AND purged_at IS NULL
              AND migrated_at IS NOT NULL
              AND migrated_at <= ?
            LIMIT 500
        """, (cutoff,)).fetchall()
        if not rows:
            if own_conn:
                conn.commit()
            return 0
        ts = now_ts()
        for vm_uuid, old_node, new_node, migrated_at in rows:
            conn.execute("""
                UPDATE vm_node_presence
                SET status='purged', purged_at=?, alert_flags=?
                WHERE vm_uuid=? AND node=?
            """, (ts, f"PURGED_AFTER_MIGRATION_TO:{new_node}", vm_uuid, old_node))
            conn.execute("""
                UPDATE vm_inventory
                SET status='purged', hidden_at=COALESCE(hidden_at, ?), deleted_at=COALESCE(deleted_at, ?)
                WHERE vm_uuid=? AND node=? AND COALESCE(status, 'active') != 'hidden'
            """, (ts, ts, vm_uuid, old_node))
            conn.execute("DELETE FROM vm_latest_metrics WHERE vm_uuid=? AND node=?", (vm_uuid, old_node))
            conn.execute("DELETE FROM node_stats WHERE vm_uuid=? AND node=?", (vm_uuid, old_node))
            if VM_MIGRATION_PURGE_RAW_HISTORY:
                conn.execute("DELETE FROM usage WHERE vm_uuid=? AND node=?", (vm_uuid, old_node))
        if own_conn:
            conn.commit()
        return len(rows)
    finally:
        if own_conn:
            conn.close()

# Backward-compatible name used by older code paths. It records a seen VM but
# migration is now confirmed by process_node_vm_presence(), not immediately.
def update_vm_location(conn, vm_uuid, node, seen_ts, iface="-", bridge="-"):
    process_node_vm_presence(conn, node, {vm_uuid: {"iface": iface, "bridge": bridge}}, seen_ts)
    return False

def get_recent_vm_migrations(node=None, limit=10):
    limit = max(1, min(100, safe_int(limit, 10)))
    conn = db()
    try:
        if node:
            return conn.execute("""
                SELECT time, vm_uuid, old_node, new_node, old_last_seen, new_seen, detail
                FROM vm_migration_events
                WHERE old_node=? OR new_node=?
                ORDER BY time DESC
                LIMIT ?
            """, (node, node, limit)).fetchall()
        return conn.execute("""
            SELECT time, vm_uuid, old_node, new_node, old_last_seen, new_seen, detail
            FROM vm_migration_events
            ORDER BY time DESC
            LIMIT ?
        """, (limit,)).fetchall()
    finally:
        conn.close()

def vm_migration_table(rows, title="Recent VM Migrations"):
    body = ""
    for ts, vm_uuid, old_node, new_node, old_last_seen, new_seen, detail in rows:
        href = url_for("vm_page", node=new_node, vm_uuid=vm_uuid, period="1h")
        body += f"""
        <tr>
            <td>{fmt_full(ts)}</td>
            <td class="mono"><span class="uuid-cell"><a href="{escape(href, quote=True)}" title="{escape(vm_uuid)}">{escape(vm_uuid)}</a><button type="button" class="copy-btn" data-copy="{escape(vm_uuid)}" title="Copy UUID">⧉</button></span></td>
            <td class="mono">{escape(old_node)}</td>
            <td class="mono"><b>{escape(new_node)}</b></td>
            <td>{fmt_push(old_last_seen)}</td>
            <td>{fmt_push(new_seen)}</td>
        </tr>
        """
    if not body:
        body = '<tr><td colspan="6" class="empty">No VM migration detected yet</td></tr>'
    return f"""
    <div class="card">
        <h3>{escape(title)}</h3>
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>VM UUID</th>
                    <th>Old Node</th>
                    <th>Current Node</th>
                    <th>Old Seen</th>
                    <th>New Seen</th>
                </tr>
            </thead>
            <tbody>{body}</tbody>
        </table>
    </div>
    """

def clean_node_net_mode(mode):
    mode = (mode or "both").strip().lower()
    aliases = {
        "all": "both",
        "any": "both",
        "pub": "public",
        "pri": "private",
        "private-only": "private",
        "public-only": "public",
    }
    mode = aliases.get(mode, mode)
    return mode if mode in {"both", "public", "private"} else "both"

def node_net_label(mode):
    mode = clean_node_net_mode(mode)
    return {"both": "Public + Private", "public": "Public", "private": "Private"}.get(mode, "Public + Private")

def node_net_tabs(node, period, q, sort_by, sort_order, net_mode):
    current = clean_node_net_mode(net_mode)
    items = [("both", "Both cards"), ("public", "Public only"), ("private", "Private only")]
    links = []
    for key, label in items:
        href = url_for(
            "node_page",
            node=node,
            period=period,
            q=q,
            sort=sort_by,
            order=sort_order,
            net=key,
        )
        cls = "active" if key == current else ""
        links.append(f'<a class="{cls}" href="{escape(href, quote=True)}">{escape(label)}</a>')
    return f"""
    <div class="card status-filter-card">
        <div class="table-title-row">
            <h3>Network Cards</h3>
            <div class="count-badges">
                <span>Current <b>{escape(node_net_label(current))}</b></span>
            </div>
        </div>
        <div class="periods">{''.join(links)}</div>
    </div>
    """

def human_age_short(seconds):
    seconds = max(0, int(seconds or 0))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h {minutes % 60}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"

def node_status_state(last_push):
    """Return live status from the number of missed 5-minute pushes.

    Online: fewer than STATUS_WARNING_MISSES missed pushes.
    Missed: exactly STATUS_WARNING_MISSES missed pushes.
    Down: more than STATUS_WARNING_MISSES missed pushes, or never seen.
    """
    if not last_push:
        return "red", None, STATUS_WARNING_MISSES + 1
    age = max(0, now_ts() - int(last_push))
    missed_pushes = age // STATUS_PUSH_SECONDS
    if missed_pushes < STATUS_WARNING_MISSES:
        return "green", age, missed_pushes
    if missed_pushes == STATUS_WARNING_MISSES:
        return "yellow", age, missed_pushes
    return "red", age, missed_pushes

def status_badge(last_push, show_age=True):
    state, age, missed_pushes = node_status_state(last_push)
    if state == "green":
        icon, label = "🟢", "Online"
    elif state == "yellow":
        icon, label = "🟡", "Missed"
    else:
        icon, label = "🔴", "Down"
    age_text = "never" if age is None else f"{human_age_short(age)} ago"
    miss_text = f"{int(missed_pushes)} missed push" + ("es" if int(missed_pushes) != 1 else "")
    visible = f"{icon} {label}" + (f" · {age_text}" if show_age else "")
    return (
        f'<span class="status {escape(state)}" '
        f'title="Live heartbeat: {escape(age_text, quote=True)}; {escape(miss_text, quote=True)}">{escape(visible)}</span>'
    )

def get_node_live_last_seen(node):
    conn = db()
    try:
        row = conn.execute("""
            WITH physical AS (
                SELECT node, MAX(last_seen) AS last_seen
                FROM node_physical_net_latest
                WHERE node=?
                GROUP BY node
            ), snapshots AS (
                SELECT node, MAX(bucket) AS last_seen
                FROM node_push_snapshots
                WHERE node=?
                GROUP BY node
            )
            SELECT MAX(
                COALESCE(ni.last_push, 0),
                COALESCE(ah.last_seen, 0),
                COALESCE(nh.last_seen, 0),
                COALESCE(p.last_seen, 0),
                COALESCE(s.last_seen, 0)
            )
            FROM (SELECT ? AS node) n
            LEFT JOIN node_inventory ni ON ni.node=n.node
            LEFT JOIN agent_health_latest ah ON ah.node=n.node
            LEFT JOIN node_host_latest nh ON nh.node=n.node
            LEFT JOIN physical p ON p.node=n.node
            LEFT JOIN snapshots s ON s.node=n.node
        """, (node, node, node)).fetchone()
        return int((row or [0])[0] or 0)
    finally:
        conn.close()

def get_snapshot_tier(node, bucket):
    if not bucket:
        return "-"
    conn = db()
    try:
        row = conn.execute(
            "SELECT retention_tier FROM node_push_snapshots WHERE node=? AND bucket=?",
            (node, int(bucket)),
        ).fetchone()
        return str((row or ["raw"])[0] or "raw")
    finally:
        conn.close()

def range_card(period, start, end, q="", endpoint="index", node=None, vm_status="active", net="both"):
    # The visible search box is global everywhere. On a node page it returns to
    # the dashboard, where node name/IP, VM UUID and interface are all resolved.
    search_q = "" if endpoint == "node_page" else (q or "")
    q_html = escape(search_q)
    action = url_for("index")
    if endpoint == "node_page":
        time_cells = f"""
            <div><div class="label">Latest Available</div><div class="value">{fmt_full(end)}</div></div>
            <div><div class="label">Timezone</div><div class="value">{display_timezone_name()}</div></div>
            <div><div class="label">Selected Snapshot</div><div class="value">{fmt_full(start)}</div></div>
        """
        period_title = "Snapshot lookback"
        note = "All snapshot cards use the nearest retained real push. Live status always uses the newest heartbeat."
    else:
        time_cells = f"""
            <div><div class="label">Live Updated</div><div class="value">{fmt_full(end)}</div></div>
            <div><div class="label">Timezone</div><div class="value">{display_timezone_name()}</div></div>
            <div><div class="label">Selected Snapshot</div><div class="value">{fmt_full(start)}</div></div>
        """
        period_title = "Snapshot lookback"
        note = "Selected Snapshot is the retained push actually used. Each node still uses its own nearest real push, shown exactly in the SNAPSHOT column; no CPU/RAM averaging and no multi-push traffic sum."

    return f"""
    <div class="card top-card">
        <div class="top-grid">{time_cells}</div>
        <div class="label period-label">{period_title}</div>
        <div class="periods">{period_links(period, endpoint=endpoint, node=node, q=q, vm_status=vm_status, net=net)}</div>
        <div class="table-hint">{escape(note)}</div>
        <form class="search" method="get" action="{action}">
            <input type="hidden" name="period" value="{escape(period)}">
            <input name="q" value="{q_html}" placeholder="Search Node / IP / MAC / VM UUID / Interface">
            <button type="submit">Search</button>
            {f'<a class="clear" href="{url_for("index", period=period)}">Clear</a>' if search_q else ''}
        </form>
    </div>
    """

