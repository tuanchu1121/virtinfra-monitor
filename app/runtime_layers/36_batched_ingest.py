V5050_VERSION = "50.5.0"
_V5050_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

def _v5050_ident(value):
    value = str(value or "")
    if not _V5050_IDENT.fullmatch(value):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
    return value

def _v5050_bulk_upsert_rows(conn, table, key_columns, rows):
    """UPSERT a homogeneous row batch with one PostgreSQL statement.

    jsonb_populate_recordset converts the JSON payload directly to the table's
    composite row type. This removes per-row client/server round trips while
    keeping PostgreSQL responsible for type conversion and conflict handling.
    """
    rows = [dict(row) for row in (rows or []) if row]
    if not rows:
        return 0
    table = _v5050_ident(table)
    columns = list(rows[0].keys())
    if not columns or any(list(row.keys()) != columns for row in rows):
        raise ValueError(f"heterogeneous batch for {table}")
    columns = [_v5050_ident(column) for column in columns]
    keys = [_v5050_ident(column) for column in key_columns]
    updates = [column for column in columns if column not in keys]
    column_sql = ",".join(columns)
    key_sql = ",".join(keys)
    select_sql = ",".join(f"src.{column}" for column in columns)
    if updates:
        update_sql = ",".join(f"{column}=excluded.{column}" for column in updates)
        conflict_sql = f"ON CONFLICT({key_sql}) DO UPDATE SET {update_sql}"
    else:
        conflict_sql = f"ON CONFLICT({key_sql}) DO NOTHING"
    payload = json.dumps(rows, separators=(",", ":"), ensure_ascii=False)
    cur = conn.execute(
        f"INSERT INTO {table}({column_sql}) "
        f"SELECT {select_sql} FROM jsonb_populate_recordset(NULL::{table}, ?::jsonb) AS src "
        f"{conflict_sql}",
        (payload,),
    )
    return max(0, safe_int(cur.rowcount, 0))

_v5050_legacy_location_transition = _create_or_update_location

def _v5050_current_writer(conn, node, data_time, interval_seconds, interfaces, vms, node_host, inventory_complete=False):
    """Update small current tables in O(VM + interface) during the existing push.

    Current pages read these bounded tables instead of scanning node_stats and
    vm_perf_stats history. History is still retained for charts and old points.
    """
    interval_seconds = max(1, safe_int(interval_seconds, CACHE_BUCKET_SECONDS))
    by_vm = {}
    iface_rows = []
    current_rows_to_upsert = []

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
        iface_rows.append(iface_row)

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

    _v5050_bulk_upsert_rows(conn, "vm_iface_current", ["node", "vm_uuid", "bridge", "iface"], iface_rows)

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
        rec["ram_unused_kib"] = max(0, safe_int(vm_item.get("ram_unused_kib"), 0))
        rec["ram_usable_kib"] = max(0, safe_int(vm_item.get("ram_usable_kib"), 0))
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
        current_row.setdefault("ram_unused_kib", 0)
        current_row.setdefault("ram_usable_kib", 0)
        current_rows_to_upsert.append(current_row)

    _v5050_bulk_upsert_rows(conn, "vm_current_fast", ["node", "vm_uuid"], current_rows_to_upsert)

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
    _v5050_bulk_upsert_rows(conn, "node_current_fast", ["node"], [node_row])

    if inventory_complete:
        conn.execute("DELETE FROM vm_iface_current WHERE node=? AND last_seen<?", (node, data_time))
        conn.execute("DELETE FROM vm_current_fast WHERE node=? AND last_seen<?", (node, data_time))
        conn.execute("DELETE FROM vm_abuse_state WHERE node=? AND last_seen<?", (node, data_time))

def _v5050_refresh_fast_current_state(conn, node, data_time, interval_seconds, interfaces, vms, node_host, inventory_complete=False):
    cfg = get_abuse_settings(conn)
    _apply_abuse_settings_to_runtime(cfg)
    before = _v4810_state_map(conn, node)
    sync_map = _v4810_pps_sync_map(interfaces, cfg)

    normalized_interfaces = []
    for item in interfaces or []:
        if not isinstance(item, dict):
            normalized_interfaces.append(item)
            continue
        copy_item = dict(item)
        vm_uuid = str(copy_item.get("vm_uuid") or "").strip()
        synced = bool(sync_map.get(vm_uuid, {}).get("synced")) if cfg["network_enabled"] else False
        if not synced:
            for key in ("seconds_over_pps", "seconds_over_rx_pps", "seconds_over_tx_pps"):
                copy_item[key] = 0
        normalized_interfaces.append(copy_item)

    result = _v4810_current_writer(
        conn, node, data_time, interval_seconds,
        normalized_interfaces, vms, node_host, inventory_complete,
    )

    current_rows = conn.execute("""
        SELECT c.vm_uuid,c.last_seen,c.interval_seconds,
               c.rx_mbps,c.tx_mbps,c.rx_pps,c.tx_pps,c.rx_peak_pps,c.tx_peak_pps,
               c.seconds_over_rx_pps,c.seconds_over_tx_pps,
               c.cpu_full_percent,c.cpu_core_percent,c.vcpu_current,
               c.disk_read_bps,c.disk_write_bps,c.disk_read_iops,c.disk_write_iops,
               COALESCE(c.ram_current_kib,0),COALESCE(c.ram_rss_kib,0),
               COALESCE(c.ram_available_kib,0),COALESCE(c.ram_unused_kib,0),COALESCE(c.ram_usable_kib,0)
        FROM vm_current_fast c WHERE c.node=? AND c.last_seen=?
    """, (node, data_time)).fetchall()

    current_bucket = bucket_for(data_time)
    abuse_rows = []
    for row in current_rows:
        (
            vm_uuid,last_seen,vm_interval,rx_mbps,tx_mbps,rx_pps,tx_pps,rx_peak_pps,tx_peak_pps,
            over_rx_pps,over_tx_pps,cpu_full,cpu_core,vcpu,
            disk_read,disk_write,disk_read_iops,disk_write_iops,
            ram_current,ram_rss,ram_available,ram_unused,ram_usable,
        ) = row
        vm_uuid = str(vm_uuid)
        old = before.get(vm_uuid) or {}
        old_revision = safe_int(old.get("policy_revision"), 0)
        policy_same = old_revision == cfg["revision"] and str(old.get("engine_version") or "") == ABUSE_ENGINE_VERSION
        old_bucket = safe_int(old.get("last_eval_bucket"), 0)
        advance_cycle = old_bucket != current_bucket
        contiguous = bool(old_bucket and current_bucket - old_bucket == ABUSE_EVAL_CYCLE_SECONDS)

        cpu_now = bool(cfg["cpu_enabled"] and safe_float(cpu_full, 0) >= cfg["cpu_full_percent"])
        cpu_cycles = _v4810_next_streak(old.get("cpu_streak_cycles", 0), cpu_now, policy_same, contiguous, advance_cycle)
        cpu_active = bool(cpu_now and cpu_cycles >= cfg["cpu_required_cycles"])

        rx_mbps_now = bool(cfg["network_mbps_enabled"] and cfg["network_avg_mbps"] > 0 and safe_float(rx_mbps, 0) >= cfg["network_avg_mbps"])
        tx_mbps_now = bool(cfg["network_mbps_enabled"] and cfg["network_avg_mbps"] > 0 and safe_float(tx_mbps, 0) >= cfg["network_avg_mbps"])
        rx_mbps_cycles = _v4810_next_streak(old.get("network_rx_mbps_streak_cycles", 0), rx_mbps_now, policy_same, contiguous, advance_cycle)
        tx_mbps_cycles = _v4810_next_streak(old.get("network_tx_mbps_streak_cycles", 0), tx_mbps_now, policy_same, contiguous, advance_cycle)
        rx_mbps_active = bool(rx_mbps_now and rx_mbps_cycles >= cfg["network_mbps_required_cycles"])
        tx_mbps_active = bool(tx_mbps_now and tx_mbps_cycles >= cfg["network_mbps_required_cycles"])

        disk_now, disk_ratios = _v4810_disk_hit(
            cfg, safe_float(disk_read, 0), safe_float(disk_write, 0),
            safe_float(disk_read_iops, 0), safe_float(disk_write_iops, 0),
        )
        disk_cycles = _v4810_next_streak(old.get("disk_streak_cycles", 0), disk_now, policy_same, contiguous, advance_cycle)
        disk_active = bool(disk_now and disk_cycles >= cfg["disk_required_cycles"])

        ram_metrics = _v48126_ram_metrics(ram_current, ram_rss, ram_available, ram_unused, ram_usable)
        ram_now, ram_ratios = _v48126_ram_hit(cfg, ram_metrics)
        ram_cycles = _v4810_next_streak(old.get("ram_streak_cycles", 0), ram_now, policy_same, contiguous, advance_cycle)
        ram_active = bool(ram_now and ram_cycles >= cfg["ram_required_cycles"])

        sync_info = sync_map.get(vm_uuid, {})
        pps_synced = bool(cfg["network_enabled"] and sync_info.get("synced"))
        rx_pps_active = bool(pps_synced and safe_int(over_rx_pps, 0) >= cfg["network_required_seconds"])
        tx_pps_active = bool(pps_synced and safe_int(over_tx_pps, 0) >= cfg["network_required_seconds"])

        flags, severity = [], []
        if rx_pps_active:
            flags.append("NETWORK_RX_PPS"); severity.append(max(1.0, safe_float(rx_pps, 0) / max(cfg["network_pps"], 1.0)))
        if tx_pps_active:
            flags.append("NETWORK_TX_PPS"); severity.append(max(1.0, safe_float(tx_pps, 0) / max(cfg["network_pps"], 1.0)))
        if rx_mbps_active:
            flags.append("NETWORK_RX_AVG_MBPS"); severity.append(max(1.0, safe_float(rx_mbps, 0) / max(cfg["network_avg_mbps"], 0.001)))
        if tx_mbps_active:
            flags.append("NETWORK_TX_AVG_MBPS"); severity.append(max(1.0, safe_float(tx_mbps, 0) / max(cfg["network_avg_mbps"], 0.001)))
        if cpu_active:
            flags.append("CPU_SUSTAINED"); severity.append(max(1.0, safe_float(cpu_full, 0) / max(cfg["cpu_full_percent"], 0.001)))
        if ram_active:
            flags.append("RAM_SUSTAINED"); severity.append(max([1.0] + ram_ratios))
        if disk_active:
            flags.append("DISK_SUSTAINED"); severity.append(max([1.0] + disk_ratios))

        final_active = bool(flags)
        old_active = bool(safe_int(old.get("is_abuse"), 0)) and policy_same
        abuse_since = safe_int(old.get("abuse_since"), 0) if final_active and old_active and safe_int(old.get("abuse_since"), 0) else (data_time if final_active else 0)
        policy_applied_at = safe_int(old.get("policy_applied_at"), 0) if policy_same else data_time

        abuse_rows.append({
            "node": node, "vm_uuid": vm_uuid,
            "last_seen": safe_int(last_seen, data_time),
            "is_abuse": _v4810_bool_int(final_active),
            "abuse_since": abuse_since or None,
            "abuse_flags": ",".join(flags),
            "severity": max(severity or [0.0]),
            "network_rx_hit": _v4810_bool_int(rx_pps_active),
            "network_tx_hit": _v4810_bool_int(tx_pps_active),
            "network_rx_mbps_hit": _v4810_bool_int(rx_mbps_active),
            "network_tx_mbps_hit": _v4810_bool_int(tx_mbps_active),
            "cpu_streak_seconds": cpu_cycles * ABUSE_EVAL_CYCLE_SECONDS,
            "disk_streak_seconds": disk_cycles * ABUSE_EVAL_CYCLE_SECONDS,
            "ram_streak_seconds": ram_cycles * ABUSE_EVAL_CYCLE_SECONDS,
            "network_rx_mbps_streak_seconds": rx_mbps_cycles * ABUSE_EVAL_CYCLE_SECONDS,
            "network_tx_mbps_streak_seconds": tx_mbps_cycles * ABUSE_EVAL_CYCLE_SECONDS,
            "cpu_streak_cycles": cpu_cycles,
            "disk_streak_cycles": disk_cycles,
            "ram_streak_cycles": ram_cycles,
            "network_rx_mbps_streak_cycles": rx_mbps_cycles,
            "network_tx_mbps_streak_cycles": tx_mbps_cycles,
            "rx_pps": safe_float(rx_pps, 0),
            "tx_pps": safe_float(tx_pps, 0),
            "rx_peak_pps": safe_float(rx_peak_pps, 0),
            "tx_peak_pps": safe_float(tx_peak_pps, 0),
            "seconds_over_rx_pps": safe_int(over_rx_pps, 0) if pps_synced else 0,
            "seconds_over_tx_pps": safe_int(over_tx_pps, 0) if pps_synced else 0,
            "rx_mbps": safe_float(rx_mbps, 0),
            "tx_mbps": safe_float(tx_mbps, 0),
            "cpu_full_percent": safe_float(cpu_full, 0),
            "cpu_core_percent": safe_float(cpu_core, 0),
            "vcpu_current": safe_int(vcpu, 0),
            "disk_read_bps": safe_float(disk_read, 0),
            "disk_write_bps": safe_float(disk_write, 0),
            "disk_read_iops": safe_float(disk_read_iops, 0),
            "disk_write_iops": safe_float(disk_write_iops, 0),
            "ram_current_kib": ram_metrics["current_kib"],
            "ram_rss_kib": ram_metrics["rss_kib"],
            "ram_available_kib": ram_metrics["available_kib"],
            "ram_usable_kib": ram_metrics["usable_kib"],
            "ram_rss_percent": ram_metrics["rss_percent"],
            "ram_guest_used_percent": ram_metrics["guest_used_percent"],
            "ram_usable_percent": ram_metrics["usable_percent"],
            "network_pps_policy_synced": _v4810_bool_int(pps_synced),
            "network_pps_reported_threshold": safe_float(sync_info.get("reported"), 0),
            "policy_revision": cfg["revision"],
            "policy_applied_at": policy_applied_at,
            "last_eval_bucket": current_bucket,
            "engine_version": ABUSE_ENGINE_VERSION,
        })

    _v5050_bulk_upsert_rows(conn, "vm_abuse_state", ["node", "vm_uuid"], abuse_rows)

    after = _v4810_state_map(conn, node)
    for vm_uuid in sorted(set(before) | set(after)):
        old, new = before.get(vm_uuid), after.get(vm_uuid)
        old_same_policy = bool(
            old and safe_int(old.get("policy_revision"), 0) == cfg["revision"]
            and str(old.get("engine_version") or "") == ABUSE_ENGINE_VERSION
        )
        old_active = bool(safe_int((old or {}).get("is_abuse"), 0)) and old_same_policy
        new_active = bool(safe_int((new or {}).get("is_abuse"), 0))
        old_flags = ",".join(_v4810_canonical_flags((old or {}).get("abuse_flags")))
        new_flags = ",".join(_v4810_canonical_flags((new or {}).get("abuse_flags")))
        if new_active and not old_active:
            _v4810_insert_abuse_event(conn, "started", new, data_time, cfg=cfg,
                detail=f"Policy v{cfg['revision']}: VM entered sustained abuse state")
        elif new_active and old_active and new_flags != old_flags:
            _v4810_insert_abuse_event(conn, "updated", new, data_time, cfg=cfg,
                detail=f"Policy v{cfg['revision']}: flags {old_flags or '-'} -> {new_flags or '-'}")
        elif old_active and not new_active:
            state = dict(new or old or {})
            state["node"], state["vm_uuid"] = node, vm_uuid
            state["abuse_since"] = safe_int((old or {}).get("abuse_since"), data_time)
            _v4810_insert_abuse_event(conn, "recovered", state, data_time, flags=old_flags,
                severity=safe_float((old or {}).get("severity"), 0), cfg=cfg,
                detail=f"Policy v{cfg['revision']}: VM no longer satisfies any sustained abuse rule")
    return result

def _v48140_refresh_node_summaries(conn, node):
    node = str(node or "").strip()
    if not node:
        return
    ensure_v48140_performance_schema(conn)
    conn.execute("""
      INSERT INTO vm_disk_summary_current(
        node,vm_uuid,disk_count,allocated_bytes,assigned_bytes,physical_bytes,
        allocation_ratio,read_bps,write_bps,read_iops,write_iops,last_seen
      )
      SELECT node,vm_uuid,COUNT(*),COALESCE(SUM(allocation_bytes),0),
             COALESCE(SUM(capacity_bytes),0),COALESCE(SUM(physical_bytes),0),
             CASE WHEN COALESCE(SUM(capacity_bytes),0)>0
                  THEN COALESCE(SUM(allocation_bytes),0)*1.0/SUM(capacity_bytes) ELSE 0 END,
             COALESCE(SUM(read_bps),0),COALESCE(SUM(write_bps),0),
             COALESCE(SUM(read_iops),0),COALESCE(SUM(write_iops),0),MAX(last_seen)
        FROM vm_disk_current WHERE node=? AND role='customer'
       GROUP BY node,vm_uuid
      ON CONFLICT(node,vm_uuid) DO UPDATE SET
        disk_count=excluded.disk_count,allocated_bytes=excluded.allocated_bytes,
        assigned_bytes=excluded.assigned_bytes,physical_bytes=excluded.physical_bytes,
        allocation_ratio=excluded.allocation_ratio,read_bps=excluded.read_bps,
        write_bps=excluded.write_bps,read_iops=excluded.read_iops,
        write_iops=excluded.write_iops,last_seen=excluded.last_seen
      WHERE vm_disk_summary_current.disk_count IS DISTINCT FROM excluded.disk_count
         OR vm_disk_summary_current.allocated_bytes IS DISTINCT FROM excluded.allocated_bytes
         OR vm_disk_summary_current.assigned_bytes IS DISTINCT FROM excluded.assigned_bytes
         OR vm_disk_summary_current.physical_bytes IS DISTINCT FROM excluded.physical_bytes
         OR vm_disk_summary_current.allocation_ratio IS DISTINCT FROM excluded.allocation_ratio
         OR vm_disk_summary_current.read_bps IS DISTINCT FROM excluded.read_bps
         OR vm_disk_summary_current.write_bps IS DISTINCT FROM excluded.write_bps
         OR vm_disk_summary_current.read_iops IS DISTINCT FROM excluded.read_iops
         OR vm_disk_summary_current.write_iops IS DISTINCT FROM excluded.write_iops
         OR vm_disk_summary_current.last_seen IS DISTINCT FROM excluded.last_seen
    """, (node,))
    conn.execute("""
      DELETE FROM vm_disk_summary_current s
       WHERE s.node=? AND NOT EXISTS (
         SELECT 1 FROM vm_disk_current d
          WHERE d.node=s.node AND d.vm_uuid=s.vm_uuid AND d.role='customer'
       )
    """, (node,))
    conn.execute("""
      WITH dc AS (
        SELECT node,mount,COUNT(*) disk_count,COUNT(DISTINCT vm_uuid) vm_count
          FROM vm_disk_current WHERE node=? AND role='customer' GROUP BY node,mount
      )
      INSERT INTO node_storage_mount_summary_current(
        node,mount,device,block,raid_level,fstype,size,used,avail,use_percent,
        read_bps,write_bps,read_iops,write_iops,util_percent,disk_count,vm_count,last_seen
      )
      SELECT s.node,s.mount,s.device,s.block,s.raid_level,s.fstype,s.size,s.used,s.avail,
             s.use_percent,s.read_bps,s.write_bps,s.read_iops,s.write_iops,s.util_percent,
             COALESCE(dc.disk_count,0),COALESCE(dc.vm_count,0),s.last_seen
        FROM node_storage_current s LEFT JOIN dc ON dc.node=s.node AND dc.mount=s.mount
       WHERE s.node=?
      ON CONFLICT(node,mount) DO UPDATE SET
        device=excluded.device,block=excluded.block,raid_level=excluded.raid_level,
        fstype=excluded.fstype,size=excluded.size,used=excluded.used,avail=excluded.avail,
        use_percent=excluded.use_percent,read_bps=excluded.read_bps,write_bps=excluded.write_bps,
        read_iops=excluded.read_iops,write_iops=excluded.write_iops,util_percent=excluded.util_percent,
        disk_count=excluded.disk_count,vm_count=excluded.vm_count,last_seen=excluded.last_seen
    """, (node, node))
    conn.execute("""
      DELETE FROM node_storage_mount_summary_current s
       WHERE s.node=? AND NOT EXISTS (
         SELECT 1 FROM node_storage_current n WHERE n.node=s.node AND n.mount=s.mount
       )
    """, (node,))

# Activate optimized implementations after every legacy compatibility layer loaded.
_v4810_current_writer = _v5050_current_writer
refresh_fast_current_state = _v5050_refresh_fast_current_state

