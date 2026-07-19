# v48.7.0 fast current cache and sustained abuse state
# ---------------------------------------------------------------------------

def _upsert_internal(conn, table, key_columns, row):
    """Small internal UPSERT helper. Table/column names are hard-coded by this app."""
    columns = list(row.keys())
    placeholders = ",".join("?" for _ in columns)
    update_columns = [c for c in columns if c not in key_columns]
    updates = ",".join(f"{c}=excluded.{c}" for c in update_columns)
    sql = (
        f"INSERT INTO {table}({','.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT({','.join(key_columns)}) DO UPDATE SET {updates}"
    )
    conn.execute(sql, [row[c] for c in columns])


def _fast_cpu_values(vm_item):
    vcpu = max(0, safe_int(vm_item.get("vcpu_current"), 0))
    if vm_item.get("cpu_normalized_percent") is not None:
        full = max(0.0, min(100.0, safe_float(vm_item.get("cpu_normalized_percent"), 0.0)))
    else:
        raw = max(0.0, safe_float(vm_item.get("cpu_percent"), 0.0))
        full = min(100.0, raw / max(vcpu, 1)) if raw > 100.0 else min(100.0, raw)
    core = max(0.0, safe_float(vm_item.get("cpu_core_percent"), full * max(vcpu, 1)))
    return full, core, vcpu


def _empty_fast_vm(node, vm_uuid, data_time, interval_seconds):
    return {
        "node": node, "vm_uuid": vm_uuid, "last_seen": data_time,
        "interval_seconds": interval_seconds, "ifaces": set(),
        "public_rx_bytes": 0, "public_tx_bytes": 0,
        "private_rx_bytes": 0, "private_tx_bytes": 0,
        "rx_bytes": 0, "tx_bytes": 0, "total_bytes": 0,
        "public_mbps": 0.0, "private_mbps": 0.0,
        "rx_mbps": 0.0, "tx_mbps": 0.0, "total_mbps": 0.0,
        "public_pps": 0.0, "private_pps": 0.0,
        "rx_pps": 0.0, "tx_pps": 0.0, "total_pps": 0.0,
        "public_peak_mbps": 0.0, "private_peak_mbps": 0.0,
        "rx_peak_mbps": 0.0, "tx_peak_mbps": 0.0, "total_peak_mbps": 0.0,
        "public_peak_pps": 0.0, "private_peak_pps": 0.0,
        "rx_peak_pps": 0.0, "tx_peak_pps": 0.0, "total_peak_pps": 0.0,
        "sample_count": 0, "sample_expected": 0, "sample_max_gap": 0.0,
        "sample_quality": "LEGACY",
        "seconds_over_rx_pps": 0, "seconds_over_tx_pps": 0,
        "drops": 0, "errors": 0,
        "cpu_full_percent": 0.0, "cpu_core_percent": 0.0, "vcpu_current": 0,
        "ram_current_kib": 0, "ram_rss_kib": 0, "ram_available_kib": 0,
        "disk_read_bps": 0.0, "disk_write_bps": 0.0,
        "disk_read_iops": 0.0, "disk_write_iops": 0.0,
    }


def refresh_fast_current_state(conn, node, data_time, interval_seconds, interfaces, vms, node_host, inventory_complete=False):
    """Update small current tables in O(VM + interface) during the existing push.

    Current pages read these bounded tables instead of scanning node_stats and
    vm_perf_stats history. History is still retained for charts and old points.
    """
    interval_seconds = max(1, safe_int(interval_seconds, CACHE_BUCKET_SECONDS))
    by_vm = {}

    for item in interfaces or []:
        if not isinstance(item, dict):
            continue
        vm_uuid = str(item.get("vm_uuid") or "").strip()
        if not vm_uuid or vm_uuid == "-":
            continue
        bridge = str(item.get("bridge") or "-")
        iface = str(item.get("iface") or "-")
        sec = max(1, safe_int(item.get("interval_seconds"), interval_seconds))
        rx_b = max(0, safe_int(item.get("rx_delta"), 0))
        tx_b = max(0, safe_int(item.get("tx_delta"), 0))
        rx_packets = max(0, safe_int(item.get("rx_packets_delta"), 0))
        tx_packets = max(0, safe_int(item.get("tx_packets_delta"), 0))
        rx_mbps = rx_b * 8.0 / sec / 1000000.0
        tx_mbps = tx_b * 8.0 / sec / 1000000.0
        rx_pps = rx_packets / float(sec)
        tx_pps = tx_packets / float(sec)
        rx_peak_mbps = max(rx_mbps, safe_float(item.get("rx_mbps_peak"), 0.0))
        tx_peak_mbps = max(tx_mbps, safe_float(item.get("tx_mbps_peak"), 0.0))
        total_peak_mbps = max(
            rx_mbps + tx_mbps,
            safe_float(item.get("total_mbps_peak"), rx_peak_mbps + tx_peak_mbps),
        )
        rx_peak_pps = max(rx_pps, safe_float(item.get("rx_pps_peak"), 0.0))
        tx_peak_pps = max(tx_pps, safe_float(item.get("tx_pps_peak"), 0.0))
        total_peak_pps = max(
            rx_pps + tx_pps,
            safe_float(item.get("total_pps_peak"), rx_peak_pps + tx_peak_pps),
        )
        sample_count = max(0, safe_int(item.get("network_sample_count"), 0))
        sample_expected = max(0, safe_int(item.get("network_sample_expected"), 0))
        sample_max_gap = max(0.0, safe_float(item.get("network_sample_max_gap_seconds"), 0.0))
        quality = clean_network_sample_quality(item.get("network_sample_quality"))
        over_rx = max(0, safe_int(item.get("seconds_over_rx_pps"), 0))
        over_tx = max(0, safe_int(item.get("seconds_over_tx_pps"), 0))

        # v8 compatibility. v9 sends directional timers directly.
        if over_rx == 0 and over_tx == 0:
            combined = max(0, safe_int(item.get("seconds_over_pps"), 0))
            if max(rx_pps, rx_peak_pps) >= ABUSE_NETWORK_PPS:
                over_rx = combined
            if max(tx_pps, tx_peak_pps) >= ABUSE_NETWORK_PPS:
                over_tx = combined

        drops = max(0, safe_int(item.get("rx_drop_delta"), 0)) + max(0, safe_int(item.get("tx_drop_delta"), 0))
        errors = max(0, safe_int(item.get("rx_error_delta"), 0)) + max(0, safe_int(item.get("tx_error_delta"), 0))

        iface_row = {
            "node": node, "vm_uuid": vm_uuid, "bridge": bridge, "iface": iface,
            "mac": normalize_mac_address(item.get("mac")),
            "last_seen": data_time, "interval_seconds": sec,
            "rx_bytes": rx_b, "tx_bytes": tx_b,
            "rx_packets": rx_packets, "tx_packets": tx_packets,
            "rx_mbps": rx_mbps, "tx_mbps": tx_mbps, "total_mbps": rx_mbps + tx_mbps,
            "rx_peak_mbps": rx_peak_mbps, "tx_peak_mbps": tx_peak_mbps,
            "total_peak_mbps": total_peak_mbps,
            "rx_pps": rx_pps, "tx_pps": tx_pps, "total_pps": rx_pps + tx_pps,
            "rx_peak_pps": rx_peak_pps, "tx_peak_pps": tx_peak_pps,
            "total_peak_pps": total_peak_pps,
            "sample_count": sample_count, "sample_expected": sample_expected,
            "sample_max_gap": sample_max_gap, "sample_quality": quality,
            "seconds_over_rx_pps": over_rx, "seconds_over_tx_pps": over_tx,
            "drops": drops, "errors": errors,
        }
        _upsert_internal(conn, "vm_iface_current", ["node", "vm_uuid", "bridge", "iface"], iface_row)

        rec = by_vm.setdefault(vm_uuid, _empty_fast_vm(node, vm_uuid, data_time, interval_seconds))
        rec["ifaces"].add((bridge, iface))
        rec["rx_bytes"] += rx_b
        rec["tx_bytes"] += tx_b
        rec["total_bytes"] += rx_b + tx_b
        rec["rx_mbps"] += rx_mbps
        rec["tx_mbps"] += tx_mbps
        rec["total_mbps"] += rx_mbps + tx_mbps
        rec["rx_pps"] += rx_pps
        rec["tx_pps"] += tx_pps
        rec["total_pps"] += rx_pps + tx_pps
        # Sum per-interface directional peaks for the generic all-interface view.
        # The VM detail page keeps RX/TX separated and is the authoritative view.
        rec["rx_peak_mbps"] += rx_peak_mbps
        rec["tx_peak_mbps"] += tx_peak_mbps
        rec["total_peak_mbps"] += total_peak_mbps
        rec["rx_peak_pps"] += rx_peak_pps
        rec["tx_peak_pps"] += tx_peak_pps
        rec["total_peak_pps"] += total_peak_pps
        rec["sample_count"] = max(rec["sample_count"], sample_count)
        rec["sample_expected"] = max(rec["sample_expected"], sample_expected)
        rec["sample_max_gap"] = max(rec["sample_max_gap"], sample_max_gap)
        if network_sample_quality_rank(quality) > network_sample_quality_rank(rec["sample_quality"]):
            rec["sample_quality"] = quality
        # Abuse is directional and applies if one VM NIC direction stays high.
        rec["seconds_over_rx_pps"] = max(rec["seconds_over_rx_pps"], over_rx)
        rec["seconds_over_tx_pps"] = max(rec["seconds_over_tx_pps"], over_tx)
        rec["drops"] += drops
        rec["errors"] += errors

        if bridge == PUBLIC_BRIDGE:
            rec["public_rx_bytes"] += rx_b
            rec["public_tx_bytes"] += tx_b
            rec["public_mbps"] += rx_mbps + tx_mbps
            rec["public_pps"] += rx_pps + tx_pps
            rec["public_peak_mbps"] += total_peak_mbps
            rec["public_peak_pps"] += total_peak_pps
        elif bridge == PRIVATE_BRIDGE:
            rec["private_rx_bytes"] += rx_b
            rec["private_tx_bytes"] += tx_b
            rec["private_mbps"] += rx_mbps + tx_mbps
            rec["private_pps"] += rx_pps + tx_pps
            rec["private_peak_mbps"] += total_peak_mbps
            rec["private_peak_pps"] += total_peak_pps

    for vm_item in vms or []:
        if not isinstance(vm_item, dict):
            continue
        vm_uuid = str(vm_item.get("vm_uuid") or "").strip()
        if not vm_uuid or vm_uuid == "-":
            continue
        rec = by_vm.setdefault(vm_uuid, _empty_fast_vm(node, vm_uuid, data_time, interval_seconds))
        full_cpu, core_cpu, vcpu = _fast_cpu_values(vm_item)
        rec["cpu_full_percent"] = full_cpu
        rec["cpu_core_percent"] = core_cpu
        rec["vcpu_current"] = vcpu
        rec["ram_current_kib"] = max(0, safe_int(vm_item.get("ram_current_kib"), 0))
        rec["ram_rss_kib"] = max(0, safe_int(vm_item.get("ram_rss_kib"), 0))
        rec["ram_available_kib"] = max(0, safe_int(vm_item.get("ram_available_kib"), 0))
        sec = max(1, safe_int(vm_item.get("interval_seconds"), interval_seconds))
        rd = max(0, safe_int(vm_item.get("disk_read_delta"), 0))
        wr = max(0, safe_int(vm_item.get("disk_write_delta"), 0))
        rr = max(0, safe_int(vm_item.get("disk_read_reqs_delta"), 0))
        ww = max(0, safe_int(vm_item.get("disk_write_reqs_delta"), 0))
        rec["disk_read_bps"] = rd / float(sec)
        rec["disk_write_bps"] = wr / float(sec)
        rec["disk_read_iops"] = rr / float(sec)
        rec["disk_write_iops"] = ww / float(sec)

    for vm_uuid, rec in by_vm.items():
        rec["total_peak_mbps"] = max(rec["total_mbps"], rec["total_peak_mbps"])
        rec["total_peak_pps"] = max(rec["total_pps"], rec["total_peak_pps"])
        current_row = {k: v for k, v in rec.items() if k != "ifaces"}
        current_row["iface_count"] = len(rec["ifaces"])
        _upsert_internal(conn, "vm_current_fast", ["node", "vm_uuid"], current_row)

        prev = conn.execute(
            "SELECT last_seen,is_abuse,abuse_since,cpu_streak_seconds,disk_streak_seconds "
            "FROM vm_abuse_state WHERE node=? AND vm_uuid=?",
            (node, vm_uuid),
        ).fetchone()
        prev_seen = safe_int((prev or [0, 0, 0, 0, 0])[0], 0)
        prev_abuse = safe_int((prev or [0, 0, 0, 0, 0])[1], 0)
        prev_since = safe_int((prev or [0, 0, 0, 0, 0])[2], 0)
        prev_cpu = safe_int((prev or [0, 0, 0, 0, 0])[3], 0)
        prev_disk = safe_int((prev or [0, 0, 0, 0, 0])[4], 0)

        contiguous = bool(prev_seen and 0 < data_time - prev_seen <= max(interval_seconds + 120, 420))
        step_seconds = min(max(interval_seconds, 1), CACHE_BUCKET_SECONDS)
        cpu_hit = rec["cpu_full_percent"] >= ABUSE_CPU_FULL_PERCENT
        disk_total_bps = rec["disk_read_bps"] + rec["disk_write_bps"]
        disk_total_iops = rec["disk_read_iops"] + rec["disk_write_iops"]
        disk_hit = (
            (ABUSE_DISK_READ_BPS > 0 and rec["disk_read_bps"] >= ABUSE_DISK_READ_BPS)
            or (ABUSE_DISK_WRITE_BPS > 0 and rec["disk_write_bps"] >= ABUSE_DISK_WRITE_BPS)
            or (ABUSE_DISK_BPS > 0 and disk_total_bps >= ABUSE_DISK_BPS)
            or (ABUSE_DISK_IOPS > 0 and disk_total_iops >= ABUSE_DISK_IOPS)
        )
        cpu_streak = (prev_cpu + step_seconds if contiguous else step_seconds) if cpu_hit else 0
        disk_streak = (prev_disk + step_seconds if contiguous else step_seconds) if disk_hit else 0
        required_network = min(
            ABUSE_NETWORK_REQUIRED_SECONDS,
            max(1, int(interval_seconds * 0.90)),
        )
        rx_hit = rec["seconds_over_rx_pps"] >= required_network
        tx_hit = rec["seconds_over_tx_pps"] >= required_network

        flags = []
        severity = []
        if rx_hit:
            flags.append("NETWORK_RX_PPS_5M")
            severity.append(max(1.0, rec["rx_pps"] / max(ABUSE_NETWORK_PPS, 1.0)))
        if tx_hit:
            flags.append("NETWORK_TX_PPS_5M")
            severity.append(max(1.0, rec["tx_pps"] / max(ABUSE_NETWORK_PPS, 1.0)))
        if cpu_streak >= ABUSE_CPU_REQUIRED_SECONDS:
            flags.append("CPU_30M")
            severity.append(max(1.0, rec["cpu_full_percent"] / max(ABUSE_CPU_FULL_PERCENT, 1.0)))
        if disk_streak >= ABUSE_DISK_REQUIRED_SECONDS:
            flags.append("DISK_15M")
            disk_ratios = []
            if ABUSE_DISK_READ_BPS > 0:
                disk_ratios.append(rec["disk_read_bps"] / ABUSE_DISK_READ_BPS)
            if ABUSE_DISK_WRITE_BPS > 0:
                disk_ratios.append(rec["disk_write_bps"] / ABUSE_DISK_WRITE_BPS)
            if ABUSE_DISK_BPS > 0:
                disk_ratios.append(disk_total_bps / ABUSE_DISK_BPS)
            if ABUSE_DISK_IOPS > 0:
                disk_ratios.append(disk_total_iops / ABUSE_DISK_IOPS)
            severity.append(max([1.0] + disk_ratios))

        is_abuse = 1 if flags else 0
        abuse_since = (prev_since if prev_abuse and prev_since else data_time) if is_abuse else 0
        abuse_row = {
            "node": node, "vm_uuid": vm_uuid, "last_seen": data_time,
            "is_abuse": is_abuse, "abuse_since": abuse_since,
            "abuse_flags": ",".join(flags), "severity": max(severity or [0.0]),
            "network_rx_hit": 1 if rx_hit else 0,
            "network_tx_hit": 1 if tx_hit else 0,
            "cpu_streak_seconds": cpu_streak,
            "disk_streak_seconds": disk_streak,
            "rx_pps": rec["rx_pps"], "tx_pps": rec["tx_pps"],
            "rx_peak_pps": rec["rx_peak_pps"], "tx_peak_pps": rec["tx_peak_pps"],
            "seconds_over_rx_pps": rec["seconds_over_rx_pps"],
            "seconds_over_tx_pps": rec["seconds_over_tx_pps"],
            "cpu_full_percent": rec["cpu_full_percent"],
            "cpu_core_percent": rec["cpu_core_percent"],
            "vcpu_current": rec["vcpu_current"],
            "disk_read_bps": rec["disk_read_bps"],
            "disk_write_bps": rec["disk_write_bps"],
            "disk_read_iops": rec["disk_read_iops"],
            "disk_write_iops": rec["disk_write_iops"],
        }
        _upsert_internal(conn, "vm_abuse_state", ["node", "vm_uuid"], abuse_row)

    nh = node_host if isinstance(node_host, dict) else {}
    mem_total = max(0, safe_int(nh.get("mem_total"), 0))
    mem_used = max(0, safe_int(nh.get("mem_used"), 0))
    if mem_used <= 0 and mem_total > 0:
        mem_used = max(0, mem_total - max(0, safe_int(nh.get("mem_available"), 0)))
    node_row = {
        "node": node, "last_seen": data_time, "interval_seconds": interval_seconds,
        "vm_count": len(by_vm), "iface_count": len(interfaces or []),
        "public_bytes": sum(r["public_rx_bytes"] + r["public_tx_bytes"] for r in by_vm.values()),
        "private_bytes": sum(r["private_rx_bytes"] + r["private_tx_bytes"] for r in by_vm.values()),
        "total_bytes": sum(r["total_bytes"] for r in by_vm.values()),
        "public_packets": int(sum(r["public_pps"] * r["interval_seconds"] for r in by_vm.values())),
        "private_packets": int(sum(r["private_pps"] * r["interval_seconds"] for r in by_vm.values())),
        "total_packets": int(sum(r["total_pps"] * r["interval_seconds"] for r in by_vm.values())),
        "drops": sum(r["drops"] for r in by_vm.values()),
        "errors": sum(r["errors"] for r in by_vm.values()),
        "load1": safe_float(nh.get("load1"), 0),
        "load5": safe_float(nh.get("load5"), 0),
        "load15": safe_float(nh.get("load15"), 0),
        "cpu_count": safe_int(nh.get("cpu_count") or nh.get("cpu_cores"), 0),
        "cpu_percent": safe_float(nh.get("cpu_percent"), 0),
        "mem_total": mem_total, "mem_used": mem_used,
        "disk_read_bps": safe_float(nh.get("disk_read_bps"), 0),
        "disk_write_bps": safe_float(nh.get("disk_write_bps"), 0),
        "uptime_seconds": safe_int(nh.get("uptime_seconds"), 0),
    }
    _upsert_internal(conn, "node_current_fast", ["node"], node_row)

    if inventory_complete:
        conn.execute("DELETE FROM vm_iface_current WHERE node=? AND last_seen<?", (node, data_time))
        conn.execute("DELETE FROM vm_current_fast WHERE node=? AND last_seen<?", (node, data_time))
        conn.execute("DELETE FROM vm_abuse_state WHERE node=? AND last_seen<?", (node, data_time))


def get_vm_directional_current(node, vm_uuid):
    conn = db()
    try:
        row = conn.execute(
            "SELECT seconds_over_rx_pps,seconds_over_tx_pps,rx_pps,tx_pps,rx_peak_pps,tx_peak_pps "
            "FROM vm_current_fast WHERE node=? AND vm_uuid=?",
            (node, vm_uuid),
        ).fetchone()
        if not row:
            return {}
        return {
            "seconds_over_rx_pps": safe_int(row[0], 0),
            "seconds_over_tx_pps": safe_int(row[1], 0),
            "rx_pps": safe_float(row[2], 0),
            "tx_pps": safe_float(row[3], 0),
            "rx_peak_pps": safe_float(row[4], 0),
            "tx_peak_pps": safe_float(row[5], 0),
        }
    finally:
        conn.close()


# Keep historical code for period links older than current 5m.
_get_top_vm_rows_history = get_top_vm_rows
_query_node_bridge_history = query_node_bridge
_get_node_rows_history = get_node_rows
_get_vm_latest_metric_history = get_vm_latest_metric


def get_vm_latest_metric(node, vm_uuid):
    conn = db()
    try:
        row = conn.execute("""
            SELECT last_seen,interval_seconds,'','',rx_mbps,tx_mbps,rx_pps,tx_pps,
                   rx_peak_mbps,tx_peak_mbps,rx_peak_pps,tx_peak_pps,0,0,
                   sample_count,sample_expected,sample_max_gap,
                   seconds_over_rx_pps+seconds_over_tx_pps,0,sample_quality,
                   drops,errors,cpu_full_percent,vcpu_current,
                   ram_current_kib,0,ram_rss_kib,ram_available_kib,
                   disk_read_bps,disk_write_bps
            FROM vm_current_fast WHERE node=? AND vm_uuid=?
        """, (node, vm_uuid)).fetchone()
        return row if row else _get_vm_latest_metric_history(node, vm_uuid)
    finally:
        conn.close()


def query_node_bridge(node, period, bridge, q="", limit=1000, sort_by="total", order="desc", vm_status="active"):
    if clean_period(period) != "5m":
        return _query_node_bridge_history(
            node, period, bridge, q=q, limit=limit,
            sort_by=sort_by, order=order, vm_status=vm_status,
        )
    sort_by = clean_interface_sort(sort_by)
    order = clean_sort_order(order)
    order_map = {
        "rx": "i.rx_bytes", "tx": "i.tx_bytes", "total": "(i.rx_bytes+i.tx_bytes)",
        "mbps": "i.total_mbps", "peakmbps": "i.total_peak_mbps",
        "pps": "i.total_pps", "peakpps": "i.total_peak_pps",
        "sample": "i.sample_quality", "drops": "i.drops", "errors": "i.errors",
        "cpu": "c.cpu_core_percent", "cpufull": "c.cpu_full_percent", "vcpu": "c.vcpu_current", "ram": "c.ram_rss_kib",
        "diskr": "c.disk_read_bps", "diskw": "c.disk_write_bps",
    }
    params = [node, bridge, now_ts() - FAST_CURRENT_STALE_SECONDS]
    search_sql = ""
    if q:
        p = like_pattern(q)
        search_sql = " AND (i.vm_uuid LIKE ? OR i.iface LIKE ? OR i.node LIKE ?)"
        params.extend([p, p, p])
    params.append(max(1, min(5000, safe_int(limit, 1000))))
    conn = db()
    try:
        rows = conn.execute(f"""
            SELECT i.iface,i.vm_uuid,i.rx_bytes,i.tx_bytes,i.rx_bytes+i.tx_bytes,
                   i.rx_packets,i.tx_packets,i.rx_packets+i.tx_packets,i.drops,i.errors,
                   i.total_mbps,i.total_peak_mbps,i.total_pps,i.total_peak_pps,
                   i.sample_count,i.sample_expected,i.sample_max_gap,
                   i.seconds_over_rx_pps+i.seconds_over_tx_pps,0,
                   CASE UPPER(i.sample_quality)
                     WHEN 'POOR' THEN 3 WHEN 'DEGRADED' THEN 2 WHEN 'GOOD' THEN 1 ELSE 0 END,
                   COALESCE(c.cpu_full_percent,0),COALESCE(c.vcpu_current,0),COALESCE(c.cpu_core_percent,0),
                   COALESCE(c.ram_rss_kib,0),COALESCE(c.ram_current_kib,0),
                   COALESCE(c.disk_read_bps,0),COALESCE(c.disk_write_bps,0),
                   COALESCE(vi.status,'active'),i.last_seen,COALESCE(vi.last_seen,i.last_seen),i.interval_seconds
            FROM vm_iface_current i
            LEFT JOIN vm_current_fast c ON c.node=i.node AND c.vm_uuid=i.vm_uuid
            LEFT JOIN vm_inventory vi ON vi.node=i.node AND vi.vm_uuid=i.vm_uuid
            WHERE i.node=? AND i.bridge=? AND i.last_seen>=?
              AND COALESCE(vi.status,'active')!='hidden' {search_sql}
            ORDER BY {order_map[sort_by]} {order.upper()},i.vm_uuid COLLATE NOCASE
            LIMIT ?
        """, params).fetchall()
        latest = max([safe_int(r[28], 0) for r in rows] or [0])
        return rows, latest, latest
    finally:
        conn.close()


def get_top_vm_rows(period, q="", sort_by="total", order="desc", scope="all", limit=100):
    if clean_period(period) != "5m":
        return _get_top_vm_rows_history(
            period, q=q, sort_by=sort_by, order=order, scope=scope, limit=limit,
        )
    sort_by = clean_top_sort(sort_by)
    order = clean_sort_order(order)
    scope = clean_top_scope(scope)
    limit = max(10, min(1000, safe_int(limit, 100)))
    field = {
        "total": "c.total_bytes", "rx": "c.rx_bytes", "tx": "c.tx_bytes",
        "public": "(c.public_rx_bytes+c.public_tx_bytes)",
        "private": "(c.private_rx_bytes+c.private_tx_bytes)",
        "mbps": "c.total_mbps", "peakmbps": "c.total_peak_mbps",
        "pps": "c.total_pps", "peakpps": "c.total_peak_pps",
        "sample": "c.sample_quality", "drops": "c.drops", "errors": "c.errors",
        "cpu": "c.cpu_core_percent", "cpufull": "c.cpu_full_percent", "vcpu": "c.vcpu_current", "ram": "c.ram_rss_kib",
        "diskr": "c.disk_read_bps", "diskw": "c.disk_write_bps",
        "last_push": "c.last_seen", "node": "c.node COLLATE NOCASE", "vm": "c.vm_uuid COLLATE NOCASE",
    }[sort_by]
    params = [now_ts() - FAST_CURRENT_STALE_SECONDS]
    where_sql = ""
    if scope == "public":
        where_sql += " AND (c.public_rx_bytes+c.public_tx_bytes)>0"
    elif scope == "private":
        where_sql += " AND (c.private_rx_bytes+c.private_tx_bytes)>0"
    if q:
        p = like_pattern(q)
        where_sql += """ AND (
            c.node LIKE ? OR c.vm_uuid LIKE ?
            OR EXISTS(SELECT 1 FROM node_bridge_addresses_latest b
                      WHERE b.node=c.node AND (b.primary_ipv4 LIKE ? OR b.ipv4_json LIKE ?))
        )"""
        params.extend([p, p, p, p])
    params.append(limit)
    conn = db()
    try:
        rows = conn.execute(f"""
            SELECT c.node,c.vm_uuid,c.iface_count,
                   c.public_rx_bytes+c.public_tx_bytes,
                   c.private_rx_bytes+c.private_tx_bytes,
                   c.rx_bytes,c.tx_bytes,c.total_bytes,
                   CAST(c.total_pps*c.interval_seconds AS INTEGER),c.drops,c.errors,
                   c.total_mbps,c.total_peak_mbps,c.total_pps,c.total_peak_pps,
                   c.sample_count,c.sample_expected,c.sample_max_gap,
                   c.seconds_over_rx_pps+c.seconds_over_tx_pps,0,
                   CASE UPPER(c.sample_quality)
                     WHEN 'POOR' THEN 3 WHEN 'DEGRADED' THEN 2 WHEN 'GOOD' THEN 1 ELSE 0 END,
                   c.cpu_full_percent,c.vcpu_current,c.cpu_core_percent,
                   c.ram_rss_kib,c.ram_current_kib,c.disk_read_bps,c.disk_write_bps,
                   c.last_seen,c.interval_seconds,
                   COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest b
                             WHERE b.node=c.node AND LOWER(role)='public' LIMIT 1),''),
                   COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest b
                             WHERE b.node=c.node AND LOWER(role)='private' LIMIT 1),'')
            FROM vm_current_fast c
            LEFT JOIN vm_inventory vi ON vi.node=c.node AND vi.vm_uuid=c.vm_uuid
            WHERE c.last_seen>=? AND COALESCE(vi.status,'active')!='hidden' {where_sql}
            ORDER BY {field} {order.upper()},c.total_bytes DESC,
                     c.node COLLATE NOCASE,c.vm_uuid COLLATE NOCASE
            LIMIT ?
        """, params).fetchall()
        latest = max([safe_int(r[28], 0) for r in rows] or [0])
        return rows, latest, latest, limit
    finally:
        conn.close()


def get_node_rows(period, q="", sort_by="node", order="asc", target_ts=None):
    if target_ts is not None:
        return _get_node_rows_history(period, q=q, sort_by=sort_by, order=order, target_ts=target_ts)
    if clean_period(period) != "5m":
        return _get_node_rows_history(period, q=q, sort_by=sort_by, order=order, target_ts=None)
    sort_by = clean_node_sort(sort_by)
    order = clean_sort_order(order)
    order_map = {
        "node": "n.node COLLATE NOCASE", "last_push": "n.last_seen", "snapshot": "n.last_seen",
        "vm": "n.vm_count", "load": "n.load1", "uptime": "n.uptime_seconds",
        "cpu": "n.cpu_percent", "ram": "ram_pct", "diskr": "n.disk_read_bps", "diskw": "n.disk_write_bps",
        "public": "n.public_bytes", "private": "n.private_bytes", "total": "n.total_bytes",
        "pps": "node_pps", "public_pps": "public_pps", "private_pps": "private_pps",
        "drops": "n.drops", "errors": "n.errors", "source": "n.node COLLATE NOCASE",
    }
    params = [now_ts() - FAST_CURRENT_STALE_SECONDS]
    search_sql = ""
    if q:
        p = like_pattern(q)
        search_sql = """ AND (
            n.node LIKE ?
            OR EXISTS(SELECT 1 FROM vm_current_fast v WHERE v.node=n.node AND v.vm_uuid LIKE ?)
            OR EXISTS(SELECT 1 FROM node_bridge_addresses_latest b
                      WHERE b.node=n.node AND (b.primary_ipv4 LIKE ? OR b.ipv4_json LIKE ?))
        )"""
        params.extend([p, p, p, p])
    conn = db()
    try:
        rows = conn.execute(f"""
            SELECT n.node,n.last_seen,n.last_seen,'current',n.vm_count,n.iface_count,
                   n.public_bytes,n.private_bytes,n.total_bytes,
                   n.public_packets,n.private_packets,n.interval_seconds,n.interval_seconds,
                   n.total_packets,n.interval_seconds,n.drops,n.errors,
                   CASE WHEN n.cpu_count>0 OR n.mem_total>0 THEN 1 ELSE 0 END,
                   n.load1,n.load5,n.load15,n.cpu_count,n.cpu_percent,
                   CASE WHEN n.mem_total>0 THEN n.mem_used*100.0/n.mem_total ELSE 0 END AS ram_pct,
                   n.disk_read_bps,n.disk_write_bps,n.uptime_seconds,
                   'VM','-','-',
                   n.public_packets*1.0/MAX(n.interval_seconds,1) AS public_pps,
                   n.private_packets*1.0/MAX(n.interval_seconds,1) AS private_pps,
                   n.total_packets*1.0/MAX(n.interval_seconds,1) AS node_pps,
                   COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest b
                             WHERE b.node=n.node AND LOWER(role)='public' LIMIT 1),''),
                   COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest b
                             WHERE b.node=n.node AND LOWER(role)='private' LIMIT 1),'')
            FROM node_current_fast n
            LEFT JOIN node_inventory ni ON ni.node=n.node
            WHERE n.last_seen>=?
              AND (ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))
              {search_sql}
            ORDER BY {order_map[sort_by]} {order.upper()},n.node COLLATE NOCASE
        """, params).fetchall()
        latest = max([safe_int(r[1], 0) for r in rows] or [now_ts()])
        return rows, latest, latest
    finally:
        conn.close()


def _abuse_reason_fast(flags, row):
    html = []
    if "NETWORK_RX_PPS_5M" in flags:
        html.append(_abuse_reason("RX PPS 5m", fmt_pps_value(row["rx_pps"])))
    if "NETWORK_TX_PPS_5M" in flags:
        html.append(_abuse_reason("TX PPS 5m", fmt_pps_value(row["tx_pps"])))
    if "CPU_30M" in flags:
        html.append(_abuse_reason("CPU 30m", f"{row['cpu_full_percent']:.1f}%"))
    if "DISK_15M" in flags:
        html.append(_abuse_reason("DISK 15m", human_rate(row["disk_read_bps"] + row["disk_write_bps"])))
    return "".join(html)


def vm_abuse_page_fast():
    q = (request.args.get("q") or "").strip()
    order = clean_sort_order(request.args.get("order", "desc"))
    limit = max(10, min(1000, safe_int(request.args.get("limit"), 200)))
    params = [now_ts() - FAST_CURRENT_STALE_SECONDS]
    search_sql = ""
    if q:
        p = like_pattern(q)
        search_sql = """ AND (
            a.node LIKE ? OR a.vm_uuid LIKE ?
            OR EXISTS(SELECT 1 FROM node_bridge_addresses_latest b
                      WHERE b.node=a.node AND (b.primary_ipv4 LIKE ? OR b.ipv4_json LIKE ?))
        )"""
        params.extend([p, p, p, p])
    conn = db()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM vm_abuse_state a WHERE a.is_abuse=1 AND a.last_seen>=? {search_sql}",
            params,
        ).fetchone()[0]
        rows = conn.execute(f"""
            SELECT a.node,a.vm_uuid,a.last_seen,a.abuse_since,a.abuse_flags,a.severity,
                   a.rx_pps,a.tx_pps,a.rx_peak_pps,a.tx_peak_pps,
                   a.seconds_over_rx_pps,a.seconds_over_tx_pps,
                   a.cpu_full_percent,a.cpu_core_percent,a.vcpu_current,a.cpu_streak_seconds,
                   a.disk_read_bps,a.disk_write_bps,a.disk_read_iops,a.disk_write_iops,a.disk_streak_seconds,
                   COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest b
                             WHERE b.node=a.node AND LOWER(role)='public' LIMIT 1),'')
            FROM vm_abuse_state a
            LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
            WHERE a.is_abuse=1 AND a.last_seen>=?
              AND COALESCE(vi.status,'active')!='hidden' {search_sql}
            ORDER BY a.severity {order.upper()},a.last_seen DESC
            LIMIT ?
        """, params + [limit]).fetchall()
    finally:
        conn.close()

    body = ""
    network_count = cpu_count = disk_count = 0
    for rank, r in enumerate(rows, 1):
        flags = {x for x in str(r[4] or "").split(",") if x}
        item = {
            "rx_pps": safe_float(r[6], 0), "tx_pps": safe_float(r[7], 0),
            "cpu_full_percent": safe_float(r[12], 0),
            "disk_read_bps": safe_float(r[16], 0), "disk_write_bps": safe_float(r[17], 0),
        }
        if flags & {"NETWORK_RX_PPS_5M", "NETWORK_TX_PPS_5M"}:
            network_count += 1
        if "CPU_30M" in flags:
            cpu_count += 1
        if "DISK_15M" in flags:
            disk_count += 1
        href = url_for("vm_page", node=r[0], vm_uuid=r[1], period="1h")
        href_e = escape(href, quote=True)
        ip = compact_ipv4(r[21])
        ip_html = f'<small class="node-ipv4">{escape(ip)}</small>' if ip else ""
        abuse_age = human_age(max(0, now_ts() - safe_int(r[3], 0))) if r[3] else "-"
        body += f"""
        <tr>
          <td class="num">{rank}</td>
          <td><div class="node-name-cell"><a href="{href_e}"><b>{escape(r[0])}</b></a>{ip_html}</div></td>
          <td class="mono"><span class="uuid-cell"><a href="{href_e}">{escape(r[1])}</a><button type="button" class="copy-btn" data-copy="{escape(r[1])}">⧉</button></span></td>
          <td><div class="abuse-reasons">{_abuse_reason_fast(flags, item)}</div></td>
          <td class="num"><b>{safe_float(r[5],0):.2f}x</b></td>
          <td class="num">{fmt_pps_value(r[6])}<small class="metric-subline">{safe_int(r[10],0)}s ≥ limit</small></td>
          <td class="num">{fmt_pps_value(r[7])}<small class="metric-subline">{safe_int(r[11],0)}s ≥ limit</small></td>
          <td class="num"><b>{fmt_pps_value(r[8])}</b></td>
          <td class="num"><b>{fmt_pps_value(r[9])}</b></td>
          <td class="num"><b>{safe_float(r[12],0):.1f}%</b><small class="metric-subline">{safe_int(r[15],0)//60}m streak</small></td>
          <td class="num">{safe_int(r[14],0)}</td>
          <td class="num">{human_rate(r[16])}</td>
          <td class="num">{human_rate(r[17])}</td>
          <td class="num">{safe_float(r[18],0)+safe_float(r[19],0):.1f}<small class="metric-subline">IOPS</small></td>
          <td class="num">{fmt_push(r[2])}</td>
          <td class="num">{abuse_age}</td>
        </tr>
        """
    if not body:
        body = '<tr><td colspan="16" class="empty">No VM currently satisfies a sustained abuse rule</td></tr>'

    content = f"""
    <div class="card top-card">
      <div class="overview-head"><h3>Current VM Abuse</h3><div class="overview-meta"><span>Source <b>fast current state</b></span><span>History scan <b>none</b></span></div></div>
      <div class="traffic-grid abuse-grid">
        <div class="traffic-box traffic-box-main"><div class="traffic-title">Matched</div><div class="traffic-total">{int(total or 0)}</div></div>
        <div class="traffic-box"><div class="traffic-title">Network</div><div class="traffic-total">{network_count}</div></div>
        <div class="traffic-box"><div class="traffic-title">CPU</div><div class="traffic-total">{cpu_count}</div></div>
        <div class="traffic-box"><div class="traffic-title">Disk</div><div class="traffic-total">{disk_count}</div></div>
      </div>
      <form class="search" method="get" action="{url_for('vm_abuse_page')}">
        <input name="q" value="{escape(q)}" placeholder="Search node / IPv4 / VM UUID">
        <input name="limit" value="{limit}" style="max-width:100px;min-width:80px">
        <button type="submit">Search</button>
      </form>
    </div>
    <div class="card vm-table-card abuse-card">
      <div class="table-title-row"><h3>VM Abuse</h3><div class="count-badges">
        <span>Network <b>RX or TX ≥ {ABUSE_NETWORK_PPS:,.0f} PPS for ~5m</b></span>
        <span>CPU <b>≥ {ABUSE_CPU_FULL_PERCENT:.0f}% for 30m</b></span>
        <span>Disk <b>15m</b></span>
      </div></div>
      <div class="table-wrap"><table class="table-abuse"><thead><tr>
        <th>#</th><th>NODE</th><th>VM UUID</th><th>REASON</th><th>SEVERITY</th>
        <th>RX PPS</th><th>TX PPS</th><th>RX PEAK</th><th>TX PEAK</th>
        <th>CPU FULL%</th><th>vCPU</th><th>DISK R/s</th><th>DISK W/s</th><th>IOPS</th><th>PUSH</th><th>ABUSE AGE</th>
      </tr></thead><tbody>{body}</tbody></table></div>
      <div class="table-hint">RAM is intentionally excluded. Network is directional: RX or TX must stay above the threshold for almost the full five-minute sampled window. CPU is normalized across all assigned vCPUs and must remain above the threshold for 30 consecutive minutes. Disk defaults to ≥ {human_rate(ABUSE_DISK_BPS)} or ≥ {ABUSE_DISK_IOPS:.0f} IOPS for 15 minutes. All thresholds can be changed by environment variables.</div>
    </div>
    """
    return page("VM Abuse", content)


# Replace old view function while keeping the same URL rule and endpoint.
app.view_functions["vm_abuse_page"] = vm_abuse_page_fast


@app.route("/summary")
def summary():
    period=clean_period(request.args.get("period","1h")); q=(request.args.get("q") or "").strip()
    rows,start,end=get_node_rows(period,q)
    data=[]
    for r in rows:
        (node,live_seen,snapshot,tier,vm_count,iface_count,public_total,private_total,node_total,
         public_packets,private_packets,public_interval,private_interval,node_packets,node_interval,
         drops,errors,host_present,load1,load5,load15,cpu_count,cpu_percent,ram_percent,
         disk_read,disk_write,uptime,source,pub_ifaces,pri_ifaces,pub_pps,pri_pps,node_pps,
         public_ipv4,private_ipv4)=r
        state,_age,_missed=node_status_state(live_seen)
        data.append({"node":node,"status":state,"live_last_seen":live_seen,"live_last_seen_vn":fmt_full(live_seen),"snapshot":snapshot,"snapshot_vn":fmt_full(snapshot),"resolution":tier,"vm_count":vm_count or 0,"interface_count":iface_count or 0,"load1":load1 or 0,"load5":load5 or 0,"load15":load15 or 0,"uptime_seconds":uptime or 0,"cpu_percent":cpu_percent or 0,"ram_percent":ram_percent or 0,"public_bytes":public_total or 0,"private_bytes":private_total or 0,"total_bytes":node_total or 0,"drops":drops or 0,"errors":errors or 0,"source":source,"public_ipv4":public_ipv4 or "","private_ipv4":private_ipv4 or ""})
    return jsonify({"updated":fmt_full(end),"timezone":display_timezone_name(),"period":period,"requested_snapshot":start,"requested_snapshot_vn":fmt_full(start),"nodes":data})





# ---------------------------------------------------------------------------
