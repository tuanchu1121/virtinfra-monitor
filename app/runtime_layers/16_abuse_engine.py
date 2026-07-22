#
# Goals:
# - Admin policy is the only source of truth. No hard-coded duration labels.
# - Every save creates an explicit monotonically increasing policy revision.
# - CPU / AVG Mbps / Disk sustained duration is counted by complete 5-minute
#   cycles, so a 30-minute rule is exactly 6 good cycles, not 35 minutes because
#   a scheduler produced 297-second intervals.
# - Existing streaks are reset on policy changes. Historical events are kept.
# - Directional PPS remains based on Agent v10's 15-second sampler and is only
#   accepted when the threshold reported by the agent matches the current policy.
# - Current pages read bounded state tables only. No raw-history scan.

V4810_VERSION = "48.10.0"
ABUSE_ENGINE_VERSION = "cycles-v2"
ABUSE_EVAL_CYCLE_SECONDS = CACHE_BUCKET_SECONDS

def _v4810_required_cycles(required_seconds):
    return max(1, int(math.ceil(max(1, safe_int(required_seconds, ABUSE_EVAL_CYCLE_SECONDS)) / float(ABUSE_EVAL_CYCLE_SECONDS))))

def _v4810_bool_int(value):
    return 1 if bool(value) else 0

def _v4810_migrate_schema():
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        state_columns = {
            "policy_revision": "INTEGER NOT NULL DEFAULT 0",
            "policy_applied_at": "INTEGER NOT NULL DEFAULT 0",
            "last_eval_bucket": "INTEGER NOT NULL DEFAULT 0",
            "cpu_streak_cycles": "INTEGER NOT NULL DEFAULT 0",
            "disk_streak_cycles": "INTEGER NOT NULL DEFAULT 0",
            "network_rx_mbps_streak_cycles": "INTEGER NOT NULL DEFAULT 0",
            "network_tx_mbps_streak_cycles": "INTEGER NOT NULL DEFAULT 0",
            "network_pps_policy_synced": "INTEGER NOT NULL DEFAULT 0",
            "network_pps_reported_threshold": "REAL NOT NULL DEFAULT 0",
            "engine_version": "TEXT NOT NULL DEFAULT ''",
        }
        for column, ddl in state_columns.items():
            ensure_column(conn, "vm_abuse_state", column, ddl)

        event_columns = {
            "policy_revision": "INTEGER NOT NULL DEFAULT 0",
            "engine_version": "TEXT NOT NULL DEFAULT ''",
        }
        for column, ddl in event_columns.items():
            ensure_column(conn, "vm_abuse_events", column, ddl)

        conn.executescript("""
        CREATE TABLE IF NOT EXISTS abuse_policy_versions (
          revision INTEGER PRIMARY KEY,
          changed_at INTEGER NOT NULL,
          changed_by TEXT NOT NULL DEFAULT '',
          action TEXT NOT NULL DEFAULT 'save',
          config_json TEXT NOT NULL DEFAULT '{}',
          detail TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_abuse_policy_versions_time
          ON abuse_policy_versions(changed_at DESC, revision DESC);
        """)

        now = now_ts()
        row = conn.execute("SELECT value FROM admin_settings WHERE key='abuse_policy_revision'").fetchone()
        if not row:
            legacy_row = conn.execute(
                "SELECT MAX(updated_at) FROM admin_settings WHERE key LIKE 'abuse_%'"
            ).fetchone()
            initial_revision = max(1, safe_int((legacy_row or [0])[0], 0))
            conn.execute(
                "INSERT INTO admin_settings(key,value,updated_at) VALUES('abuse_policy_revision',?,?)",
                (str(initial_revision), now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO admin_settings(key,value,updated_at) VALUES('abuse_policy_updated_at',?,?)",
                (str(now), now),
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO admin_settings(key,value,updated_at) VALUES('abuse_policy_updated_at',?,?)",
                (str(now), now),
            )

        # One-time invalidation of states produced by older duration logic. The
        # next accepted push rebuilds them under the current policy. Event history
        # is intentionally preserved.
        conn.execute("""
            UPDATE vm_abuse_state
            SET is_abuse=0,
                abuse_since=NULL,
                abuse_flags='',
                severity=0,
                network_rx_hit=0,
                network_tx_hit=0,
                network_rx_mbps_hit=0,
                network_tx_mbps_hit=0,
                cpu_streak_seconds=0,
                disk_streak_seconds=0,
                network_rx_mbps_streak_seconds=0,
                network_tx_mbps_streak_seconds=0,
                cpu_streak_cycles=0,
                disk_streak_cycles=0,
                network_rx_mbps_streak_cycles=0,
                network_tx_mbps_streak_cycles=0,
                network_pps_policy_synced=0,
                network_pps_reported_threshold=0,
                policy_revision=0,
                policy_applied_at=0,
                last_eval_bucket=0,
                engine_version=?
            WHERE COALESCE(engine_version,'') NOT IN ('cycles-v2','cycles-v3','cycles-v3-ram')
        """, (ABUSE_ENGINE_VERSION,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

_v4810_migrate_schema()

# Ensure all final policy keys exist in the defaults dictionary used by Admin.
ABUSE_SETTING_DEFAULTS.update({
    "abuse_network_enabled": "1",
    "abuse_network_pps": "200000",
    "abuse_network_required_seconds": "270",
    "abuse_network_mbps_enabled": "1",
    "abuse_network_avg_mbps": "800",
    "abuse_network_mbps_required_seconds": "300",
    "abuse_cpu_enabled": "1",
    "abuse_cpu_full_percent": "90",
    "abuse_cpu_required_seconds": "1800",
    "abuse_disk_enabled": "1",
    "abuse_disk_read_bps": "0",
    "abuse_disk_write_bps": "0",
    "abuse_disk_bps": str(200 * 1024 * 1024),
    "abuse_disk_iops": "5000",
    "abuse_disk_required_seconds": "900",
})

def get_abuse_settings(conn=None):
    own = conn is None
    if own:
        conn = db()
    try:
        keys = tuple(ABUSE_SETTING_DEFAULTS)
        placeholders = ",".join("?" for _ in keys)
        rows = conn.execute(
            f"SELECT key,value,updated_at FROM admin_settings WHERE key IN ({placeholders})",
            keys,
        ).fetchall()
        values = dict(ABUSE_SETTING_DEFAULTS)
        for key, value, _updated_at in rows:
            values[str(key)] = str(value)

        revision_row = conn.execute(
            "SELECT value FROM admin_settings WHERE key='abuse_policy_revision'"
        ).fetchone()
        updated_row = conn.execute(
            "SELECT value FROM admin_settings WHERE key='abuse_policy_updated_at'"
        ).fetchone()
        revision = max(1, safe_int((revision_row or [1])[0], 1))
        policy_updated_at = max(0, safe_int((updated_row or [0])[0], 0))

        cfg = {
            "network_enabled": _setting_bool(values["abuse_network_enabled"], True),
            "network_pps": max(1000.0, min(100000000.0, safe_float(values["abuse_network_pps"], 200000.0))),
            "network_required_seconds": max(15, min(300, safe_int(values["abuse_network_required_seconds"], 270))),
            "network_mbps_enabled": _setting_bool(values["abuse_network_mbps_enabled"], True),
            "network_avg_mbps": max(0.0, min(1000000.0, safe_float(values["abuse_network_avg_mbps"], 800.0))),
            "network_mbps_required_seconds": max(300, min(86400, safe_int(values["abuse_network_mbps_required_seconds"], 300))),
            "cpu_enabled": _setting_bool(values["abuse_cpu_enabled"], True),
            "cpu_full_percent": max(1.0, min(100.0, safe_float(values["abuse_cpu_full_percent"], 90.0))),
            "cpu_required_seconds": max(300, min(86400, safe_int(values["abuse_cpu_required_seconds"], 1800))),
            "disk_enabled": _setting_bool(values["abuse_disk_enabled"], True),
            "disk_read_bps": max(0.0, safe_float(values["abuse_disk_read_bps"], 0.0)),
            "disk_write_bps": max(0.0, safe_float(values["abuse_disk_write_bps"], 0.0)),
            "disk_bps": max(0.0, safe_float(values["abuse_disk_bps"], 200.0 * 1024 * 1024)),
            "disk_iops": max(0.0, safe_float(values["abuse_disk_iops"], 5000.0)),
            "disk_required_seconds": max(300, min(86400, safe_int(values["abuse_disk_required_seconds"], 900))),
            "revision": revision,
            "policy_updated_at": policy_updated_at,
            "engine_version": ABUSE_ENGINE_VERSION,
        }
        cfg["network_mbps_required_cycles"] = _v4810_required_cycles(cfg["network_mbps_required_seconds"])
        cfg["cpu_required_cycles"] = _v4810_required_cycles(cfg["cpu_required_seconds"])
        cfg["disk_required_cycles"] = _v4810_required_cycles(cfg["disk_required_seconds"])
        cfg["disk_effective_enabled"] = bool(
            cfg["disk_enabled"] and any(
                x > 0 for x in (
                    cfg["disk_read_bps"], cfg["disk_write_bps"],
                    cfg["disk_bps"], cfg["disk_iops"],
                )
            )
        )
        return cfg
    finally:
        if own:
            conn.close()

def _apply_abuse_settings_to_runtime(cfg):
    # Keep legacy globals synchronized for old labels/routes, while the v48.10
    # engine below evaluates directly from cfg and is therefore worker-safe.
    global ABUSE_NETWORK_PPS, ABUSE_NETWORK_REQUIRED_SECONDS
    global ABUSE_NETWORK_AVG_MBPS, ABUSE_NETWORK_MBPS_REQUIRED_SECONDS
    global ABUSE_CPU_FULL_PERCENT, ABUSE_CPU_REQUIRED_SECONDS
    global ABUSE_DISK_READ_BPS, ABUSE_DISK_WRITE_BPS
    global ABUSE_DISK_BPS, ABUSE_DISK_IOPS, ABUSE_DISK_REQUIRED_SECONDS

    ABUSE_NETWORK_PPS = cfg["network_pps"] if cfg["network_enabled"] else 10**18
    ABUSE_NETWORK_REQUIRED_SECONDS = cfg["network_required_seconds"] if cfg["network_enabled"] else 10**9
    ABUSE_NETWORK_AVG_MBPS = cfg["network_avg_mbps"] if cfg["network_mbps_enabled"] and cfg["network_avg_mbps"] > 0 else 10**18
    ABUSE_NETWORK_MBPS_REQUIRED_SECONDS = cfg["network_mbps_required_seconds"] if cfg["network_mbps_enabled"] and cfg["network_avg_mbps"] > 0 else 10**9
    ABUSE_CPU_FULL_PERCENT = cfg["cpu_full_percent"] if cfg["cpu_enabled"] else 10**9
    ABUSE_CPU_REQUIRED_SECONDS = cfg["cpu_required_seconds"] if cfg["cpu_enabled"] else 10**9
    if cfg["disk_effective_enabled"]:
        ABUSE_DISK_READ_BPS = cfg["disk_read_bps"]
        ABUSE_DISK_WRITE_BPS = cfg["disk_write_bps"]
        ABUSE_DISK_BPS = cfg["disk_bps"]
        ABUSE_DISK_IOPS = cfg["disk_iops"]
        ABUSE_DISK_REQUIRED_SECONDS = cfg["disk_required_seconds"]
    else:
        ABUSE_DISK_READ_BPS = ABUSE_DISK_WRITE_BPS = ABUSE_DISK_BPS = ABUSE_DISK_IOPS = 0.0
        ABUSE_DISK_REQUIRED_SECONDS = 10**9

def get_agent_runtime_config():
    cfg = get_abuse_settings()
    return {
        "revision": cfg["revision"],
        "policy_updated_at": cfg["policy_updated_at"],
        "engine_version": ABUSE_ENGINE_VERSION,
        "pps_warn": cfg["network_pps"] if cfg["network_enabled"] else 0,
        "network_enabled": bool(cfg["network_enabled"]),
    }

def _v4810_policy_json(cfg):
    return {
        "revision": cfg["revision"],
        "policy_updated_at": cfg["policy_updated_at"],
        "engine_version": ABUSE_ENGINE_VERSION,
        "network_enabled": cfg["network_enabled"],
        "network_pps": cfg["network_pps"],
        "network_required_seconds": cfg["network_required_seconds"],
        "network_mbps_enabled": cfg["network_mbps_enabled"],
        "network_avg_mbps": cfg["network_avg_mbps"],
        "network_mbps_required_seconds": cfg["network_mbps_required_seconds"],
        "network_mbps_required_cycles": cfg["network_mbps_required_cycles"],
        "cpu_enabled": cfg["cpu_enabled"],
        "cpu_full_percent": cfg["cpu_full_percent"],
        "cpu_required_seconds": cfg["cpu_required_seconds"],
        "cpu_required_cycles": cfg["cpu_required_cycles"],
        "disk_enabled": cfg["disk_enabled"],
        "disk_read_bps": cfg["disk_read_bps"],
        "disk_write_bps": cfg["disk_write_bps"],
        "disk_bps": cfg["disk_bps"],
        "disk_iops": cfg["disk_iops"],
        "disk_required_seconds": cfg["disk_required_seconds"],
        "disk_required_cycles": cfg["disk_required_cycles"],
    }

# Keep the authoritative original current-table writer captured before older
# policy wrappers. It updates vm_current_fast / vm_iface_current / node_current_fast.
_v4810_current_writer = _refresh_fast_current_state_v470

def _v4810_pps_sync_map(interfaces, cfg):
    result = {}
    for item in interfaces or []:
        if not isinstance(item, dict):
            continue
        vm_uuid = str(item.get("vm_uuid") or "").strip()
        if not vm_uuid or vm_uuid == "-":
            continue
        rec = result.setdefault(vm_uuid, {
            "count": 0,
            "all_match": True,
            "has_report": True,
            "reported": 0.0,
        })
        rec["count"] += 1
        reported = item.get("pps_warn_threshold")
        if reported is None:
            rec["has_report"] = False
            rec["all_match"] = False
            continue
        reported_value = max(0.0, safe_float(reported, 0.0))
        rec["reported"] = reported_value
        if cfg["network_enabled"]:
            tolerance = max(1.0, cfg["network_pps"] * 0.001)
            if abs(reported_value - cfg["network_pps"]) > tolerance:
                rec["all_match"] = False
        elif reported_value > 0:
            rec["all_match"] = False
    for rec in result.values():
        rec["synced"] = bool(rec["count"] > 0 and rec["has_report"] and rec["all_match"])
    return result

def _v4810_next_streak(old_cycles, hit, policy_same, contiguous, advance_cycle):
    old_cycles = max(0, safe_int(old_cycles, 0))
    if not hit:
        return 0
    if not advance_cycle:
        return max(1, old_cycles)
    if policy_same and contiguous:
        return old_cycles + 1
    return 1

def _v4810_disk_hit(cfg, read_bps, write_bps, read_iops, write_iops):
    if not cfg["disk_effective_enabled"]:
        return False, []
    total_bps = read_bps + write_bps
    total_iops = read_iops + write_iops
    matches = []
    if cfg["disk_read_bps"] > 0 and read_bps >= cfg["disk_read_bps"]:
        matches.append(read_bps / cfg["disk_read_bps"])
    if cfg["disk_write_bps"] > 0 and write_bps >= cfg["disk_write_bps"]:
        matches.append(write_bps / cfg["disk_write_bps"])
    if cfg["disk_bps"] > 0 and total_bps >= cfg["disk_bps"]:
        matches.append(total_bps / cfg["disk_bps"])
    if cfg["disk_iops"] > 0 and total_iops >= cfg["disk_iops"]:
        matches.append(total_iops / cfg["disk_iops"])
    return bool(matches), matches

def _v4810_canonical_flags(flags):
    result = []
    mapping = {
        "NETWORK_RX_PPS_5M": "NETWORK_RX_PPS",
        "NETWORK_TX_PPS_5M": "NETWORK_TX_PPS",
        "CPU_30M": "CPU_SUSTAINED",
        "DISK_15M": "DISK_SUSTAINED",
    }
    for flag in str(flags or "").split(","):
        flag = flag.strip()
        if not flag:
            continue
        flag = mapping.get(flag, flag)
        if flag not in result:
            result.append(flag)
    return result

def _v4810_insert_abuse_event(conn, event_type, state, event_time, flags=None, severity=None, cfg=None, detail=""):
    if not state:
        return
    cfg = cfg or get_abuse_settings(conn)
    flags = str(state.get("abuse_flags") or "") if flags is None else str(flags or "")
    severity = safe_float(state.get("severity"), 0.0) if severity is None else safe_float(severity, 0.0)
    thresholds = _v4810_policy_json(cfg)
    conn.execute("""
        INSERT OR IGNORE INTO vm_abuse_events(
          event_time,event_type,node,vm_uuid,abuse_flags,severity,
          rx_pps,tx_pps,rx_peak_pps,tx_peak_pps,seconds_over_rx_pps,seconds_over_tx_pps,
          cpu_full_percent,cpu_core_percent,vcpu_current,cpu_streak_seconds,
          disk_read_bps,disk_write_bps,disk_read_iops,disk_write_iops,disk_streak_seconds,
          thresholds_json,detail,rx_mbps,tx_mbps,
          network_rx_mbps_streak_seconds,network_tx_mbps_streak_seconds,
          policy_revision,engine_version
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        safe_int(event_time, now_ts()), str(event_type or "updated"),
        str(state.get("node") or ""), str(state.get("vm_uuid") or ""),
        flags, severity,
        safe_float(state.get("rx_pps"),0), safe_float(state.get("tx_pps"),0),
        safe_float(state.get("rx_peak_pps"),0), safe_float(state.get("tx_peak_pps"),0),
        safe_int(state.get("seconds_over_rx_pps"),0), safe_int(state.get("seconds_over_tx_pps"),0),
        safe_float(state.get("cpu_full_percent"),0), safe_float(state.get("cpu_core_percent"),0),
        safe_int(state.get("vcpu_current"),0), safe_int(state.get("cpu_streak_seconds"),0),
        safe_float(state.get("disk_read_bps"),0), safe_float(state.get("disk_write_bps"),0),
        safe_float(state.get("disk_read_iops"),0), safe_float(state.get("disk_write_iops"),0),
        safe_int(state.get("disk_streak_seconds"),0),
        json.dumps(thresholds, separators=(",", ":")),
        str(detail or "")[:1000],
        safe_float(state.get("rx_mbps"),0), safe_float(state.get("tx_mbps"),0),
        safe_int(state.get("network_rx_mbps_streak_seconds"),0),
        safe_int(state.get("network_tx_mbps_streak_seconds"),0),
        safe_int(state.get("policy_revision"), cfg["revision"]),
        ABUSE_ENGINE_VERSION,
    ))

# Compatibility alias used by existing history code.
_insert_abuse_event = _v4810_insert_abuse_event

def refresh_fast_current_state(conn, node, data_time, interval_seconds, interfaces, vms, node_host, inventory_complete=False):
    """Authoritative bounded-state abuse evaluation.

    Complexity is O(number of VMs + number of VM interfaces) per accepted push.
    It never scans raw history. All sustained monitor-side rules use exact
    5-minute cycle counts and the configured policy revision.
    """
    cfg = get_abuse_settings(conn)
    _apply_abuse_settings_to_runtime(cfg)
    before = _v4810_state_map(conn, node)
    sync_map = _v4810_pps_sync_map(interfaces, cfg)

    # Do not let old/missing sampler thresholds create a PPS alert under a new
    # policy. The existing payload is otherwise untouched.
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

    # The original writer refreshes all small current tables. Its old state
    # calculation is overwritten below in the same transaction.
    result = _v4810_current_writer(
        conn, node, data_time, interval_seconds,
        normalized_interfaces, vms, node_host, inventory_complete,
    )

    current_rows = conn.execute("""
        SELECT c.vm_uuid,c.last_seen,c.interval_seconds,
               c.rx_mbps,c.tx_mbps,c.rx_pps,c.tx_pps,c.rx_peak_pps,c.tx_peak_pps,
               c.seconds_over_rx_pps,c.seconds_over_tx_pps,
               c.cpu_full_percent,c.cpu_core_percent,c.vcpu_current,
               c.disk_read_bps,c.disk_write_bps,c.disk_read_iops,c.disk_write_iops
        FROM vm_current_fast c
        WHERE c.node=? AND c.last_seen=?
    """, (node, data_time)).fetchall()

    current_bucket = bucket_for(data_time)
    seen_vm_uuids = set()
    for row in current_rows:
        (
            vm_uuid,last_seen,vm_interval,rx_mbps,tx_mbps,rx_pps,tx_pps,rx_peak_pps,tx_peak_pps,
            over_rx_pps,over_tx_pps,cpu_full,cpu_core,vcpu,
            disk_read,disk_write,disk_read_iops,disk_write_iops,
        ) = row
        vm_uuid = str(vm_uuid)
        seen_vm_uuids.add(vm_uuid)
        old = before.get(vm_uuid) or {}
        old_revision = safe_int(old.get("policy_revision"), 0)
        policy_same = old_revision == cfg["revision"] and str(old.get("engine_version") or "") == ABUSE_ENGINE_VERSION
        old_bucket = safe_int(old.get("last_eval_bucket"), 0)
        advance_cycle = old_bucket != current_bucket
        contiguous = bool(old_bucket and current_bucket - old_bucket == ABUSE_EVAL_CYCLE_SECONDS)

        cpu_now = bool(cfg["cpu_enabled"] and safe_float(cpu_full,0) >= cfg["cpu_full_percent"])
        cpu_cycles = _v4810_next_streak(
            old.get("cpu_streak_cycles",0), cpu_now, policy_same, contiguous, advance_cycle
        )
        cpu_active = bool(cpu_now and cpu_cycles >= cfg["cpu_required_cycles"])

        rx_mbps_now = bool(
            cfg["network_mbps_enabled"] and cfg["network_avg_mbps"] > 0
            and safe_float(rx_mbps,0) >= cfg["network_avg_mbps"]
        )
        tx_mbps_now = bool(
            cfg["network_mbps_enabled"] and cfg["network_avg_mbps"] > 0
            and safe_float(tx_mbps,0) >= cfg["network_avg_mbps"]
        )
        rx_mbps_cycles = _v4810_next_streak(
            old.get("network_rx_mbps_streak_cycles",0), rx_mbps_now,
            policy_same, contiguous, advance_cycle,
        )
        tx_mbps_cycles = _v4810_next_streak(
            old.get("network_tx_mbps_streak_cycles",0), tx_mbps_now,
            policy_same, contiguous, advance_cycle,
        )
        rx_mbps_active = bool(rx_mbps_now and rx_mbps_cycles >= cfg["network_mbps_required_cycles"])
        tx_mbps_active = bool(tx_mbps_now and tx_mbps_cycles >= cfg["network_mbps_required_cycles"])

        disk_now, disk_ratios = _v4810_disk_hit(
            cfg, safe_float(disk_read,0), safe_float(disk_write,0),
            safe_float(disk_read_iops,0), safe_float(disk_write_iops,0),
        )
        disk_cycles = _v4810_next_streak(
            old.get("disk_streak_cycles",0), disk_now, policy_same, contiguous, advance_cycle
        )
        disk_active = bool(disk_now and disk_cycles >= cfg["disk_required_cycles"])

        sync_info = sync_map.get(vm_uuid, {})
        pps_synced = bool(cfg["network_enabled"] and sync_info.get("synced"))
        rx_pps_active = bool(
            pps_synced and safe_int(over_rx_pps,0) >= cfg["network_required_seconds"]
        )
        tx_pps_active = bool(
            pps_synced and safe_int(over_tx_pps,0) >= cfg["network_required_seconds"]
        )

        flags = []
        severity = []
        if rx_pps_active:
            flags.append("NETWORK_RX_PPS")
            severity.append(max(1.0, safe_float(rx_pps,0) / max(cfg["network_pps"],1.0)))
        if tx_pps_active:
            flags.append("NETWORK_TX_PPS")
            severity.append(max(1.0, safe_float(tx_pps,0) / max(cfg["network_pps"],1.0)))
        if rx_mbps_active:
            flags.append("NETWORK_RX_AVG_MBPS")
            severity.append(max(1.0, safe_float(rx_mbps,0) / max(cfg["network_avg_mbps"],0.001)))
        if tx_mbps_active:
            flags.append("NETWORK_TX_AVG_MBPS")
            severity.append(max(1.0, safe_float(tx_mbps,0) / max(cfg["network_avg_mbps"],0.001)))
        if cpu_active:
            flags.append("CPU_SUSTAINED")
            severity.append(max(1.0, safe_float(cpu_full,0) / max(cfg["cpu_full_percent"],0.001)))
        if disk_active:
            flags.append("DISK_SUSTAINED")
            severity.append(max([1.0] + disk_ratios))

        final_active = bool(flags)
        old_active = bool(safe_int(old.get("is_abuse"),0)) and policy_same
        if final_active:
            abuse_since = safe_int(old.get("abuse_since"),0) if old_active and safe_int(old.get("abuse_since"),0) else data_time
        else:
            abuse_since = 0
        policy_applied_at = safe_int(old.get("policy_applied_at"),0) if policy_same else data_time

        conn.execute("""
            UPDATE vm_abuse_state
            SET last_seen=?,is_abuse=?,abuse_since=?,abuse_flags=?,severity=?,
                network_rx_hit=?,network_tx_hit=?,network_rx_mbps_hit=?,network_tx_mbps_hit=?,
                cpu_streak_seconds=?,disk_streak_seconds=?,
                network_rx_mbps_streak_seconds=?,network_tx_mbps_streak_seconds=?,
                cpu_streak_cycles=?,disk_streak_cycles=?,
                network_rx_mbps_streak_cycles=?,network_tx_mbps_streak_cycles=?,
                rx_pps=?,tx_pps=?,rx_peak_pps=?,tx_peak_pps=?,
                seconds_over_rx_pps=?,seconds_over_tx_pps=?,
                rx_mbps=?,tx_mbps=?,
                cpu_full_percent=?,cpu_core_percent=?,vcpu_current=?,
                disk_read_bps=?,disk_write_bps=?,disk_read_iops=?,disk_write_iops=?,
                network_pps_policy_synced=?,network_pps_reported_threshold=?,
                policy_revision=?,policy_applied_at=?,last_eval_bucket=?,engine_version=?
            WHERE node=? AND vm_uuid=?
        """, (
            safe_int(last_seen,data_time), _v4810_bool_int(final_active), abuse_since or None,
            ",".join(flags), max(severity or [0.0]),
            _v4810_bool_int(rx_pps_active), _v4810_bool_int(tx_pps_active),
            _v4810_bool_int(rx_mbps_active), _v4810_bool_int(tx_mbps_active),
            cpu_cycles * ABUSE_EVAL_CYCLE_SECONDS,
            disk_cycles * ABUSE_EVAL_CYCLE_SECONDS,
            rx_mbps_cycles * ABUSE_EVAL_CYCLE_SECONDS,
            tx_mbps_cycles * ABUSE_EVAL_CYCLE_SECONDS,
            cpu_cycles,disk_cycles,rx_mbps_cycles,tx_mbps_cycles,
            safe_float(rx_pps,0),safe_float(tx_pps,0),safe_float(rx_peak_pps,0),safe_float(tx_peak_pps,0),
            safe_int(over_rx_pps,0) if pps_synced else 0,
            safe_int(over_tx_pps,0) if pps_synced else 0,
            safe_float(rx_mbps,0),safe_float(tx_mbps,0),
            safe_float(cpu_full,0),safe_float(cpu_core,0),safe_int(vcpu,0),
            safe_float(disk_read,0),safe_float(disk_write,0),
            safe_float(disk_read_iops,0),safe_float(disk_write_iops,0),
            _v4810_bool_int(pps_synced),safe_float(sync_info.get("reported"),0),
            cfg["revision"],policy_applied_at,current_bucket,ABUSE_ENGINE_VERSION,
            node,vm_uuid,
        ))

    after = _v4810_state_map(conn, node)
    for vm_uuid in sorted(set(before) | set(after)):
        old = before.get(vm_uuid)
        new = after.get(vm_uuid)
        old_same_policy = bool(
            old and safe_int(old.get("policy_revision"),0) == cfg["revision"]
            and str(old.get("engine_version") or "") == ABUSE_ENGINE_VERSION
        )
        old_active = bool(safe_int((old or {}).get("is_abuse"),0)) and old_same_policy
        new_active = bool(safe_int((new or {}).get("is_abuse"),0))
        old_flags = ",".join(_v4810_canonical_flags((old or {}).get("abuse_flags")))
        new_flags = ",".join(_v4810_canonical_flags((new or {}).get("abuse_flags")))
        if new_active and not old_active:
            _v4810_insert_abuse_event(
                conn,"started",new,data_time,cfg=cfg,
                detail=f"Policy v{cfg['revision']}: VM entered sustained abuse state",
            )
        elif new_active and old_active and new_flags != old_flags:
            _v4810_insert_abuse_event(
                conn,"updated",new,data_time,cfg=cfg,
                detail=f"Policy v{cfg['revision']}: flags {old_flags or '-'} -> {new_flags or '-'}",
            )
        elif old_active and not new_active:
            state = dict(new or old or {})
            state["node"] = node
            state["vm_uuid"] = vm_uuid
            _v4810_insert_abuse_event(
                conn,"recovered",state,data_time,flags=old_flags,
                severity=safe_float((old or {}).get("severity"),0),cfg=cfg,
                detail=f"Policy v{cfg['revision']}: VM no longer satisfies any sustained abuse rule",
            )
    return result

def _v4810_reset_current_state_for_policy(conn, revision, changed_at):
    conn.execute("""
        UPDATE vm_abuse_state
        SET is_abuse=0,abuse_since=NULL,abuse_flags='',severity=0,
            network_rx_hit=0,network_tx_hit=0,
            network_rx_mbps_hit=0,network_tx_mbps_hit=0,
            cpu_streak_seconds=0,disk_streak_seconds=0,
            network_rx_mbps_streak_seconds=0,network_tx_mbps_streak_seconds=0,
            cpu_streak_cycles=0,disk_streak_cycles=0,
            network_rx_mbps_streak_cycles=0,network_tx_mbps_streak_cycles=0,
            seconds_over_rx_pps=0,seconds_over_tx_pps=0,
            network_pps_policy_synced=0,network_pps_reported_threshold=0,
            policy_revision=?,policy_applied_at=?,last_eval_bucket=0,
            engine_version=?
    """, (revision, changed_at, ABUSE_ENGINE_VERSION))

def _v4810_save_policy(values, actor, action="save"):
    conn = db()
    now = now_ts()
    try:
        conn.execute("BEGIN IMMEDIATE")
        current_row = conn.execute(
            "SELECT value FROM admin_settings WHERE key='abuse_policy_revision'"
        ).fetchone()
        revision = max(1, safe_int((current_row or [0])[0],0) + 1)
        for key, value in values.items():
            conn.execute("""
                INSERT INTO admin_settings(key,value,updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at
            """, (str(key),str(value),now))
        for key, value in (
            ("abuse_policy_revision",str(revision)),
            ("abuse_policy_updated_at",str(now)),
        ):
            conn.execute("""
                INSERT INTO admin_settings(key,value,updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at
            """, (key,value,now))
        cfg = get_abuse_settings(conn)
        _v4810_reset_current_state_for_policy(conn,revision,now)
        conn.execute("""
            INSERT INTO abuse_policy_versions(revision,changed_at,changed_by,action,config_json,detail)
            VALUES(?,?,?,?,?,?)
        """, (
            revision,now,str(actor or "admin"),str(action or "save"),
            json.dumps(_v4810_policy_json(cfg),separators=(",",":")),
            "Existing current streaks were reset. Historical abuse events were preserved.",
        ))
        conn.commit()
        _apply_abuse_settings_to_runtime(cfg)
        return cfg
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def admin_abuse_settings_v4810():
    deny = require_admin()
    if deny:
        return deny
    action = (request.form.get("action") or "save").strip().lower()
    if action not in {"save","reset"}:
        return redirect(url_for("admin_abuse_page",err="Unsupported policy action"))

    if action == "reset":
        values = dict(ABUSE_SETTING_DEFAULTS)
    else:
        network_pps = max(1000.0,min(100000000.0,safe_float(request.form.get("network_pps"),200000)))
        network_seconds = max(15,min(300,safe_int(request.form.get("network_required_seconds"),270)))
        network_avg_mbps = max(0.0,min(1000000.0,safe_float(request.form.get("network_avg_mbps"),800)))
        network_mbps_minutes = max(5,min(1440,safe_int(request.form.get("network_mbps_required_minutes"),5)))
        cpu_percent = max(1.0,min(100.0,safe_float(request.form.get("cpu_full_percent"),90)))
        cpu_minutes = max(5,min(1440,safe_int(request.form.get("cpu_required_minutes"),30)))
        disk_read_mibps = max(0.0,min(100000.0,safe_float(request.form.get("disk_read_mibps"),0)))
        disk_write_mibps = max(0.0,min(100000.0,safe_float(request.form.get("disk_write_mibps"),0)))
        disk_mibps = max(0.0,min(100000.0,safe_float(request.form.get("disk_mibps"),200)))
        disk_iops = max(0.0,min(10000000.0,safe_float(request.form.get("disk_iops"),5000)))
        disk_minutes = max(5,min(1440,safe_int(request.form.get("disk_required_minutes"),15)))
        values = {
            "abuse_network_enabled":"1" if request.form.get("network_enabled") else "0",
            "abuse_network_pps":str(network_pps),
            "abuse_network_required_seconds":str(network_seconds),
            "abuse_network_mbps_enabled":"1" if request.form.get("network_mbps_enabled") else "0",
            "abuse_network_avg_mbps":str(network_avg_mbps),
            "abuse_network_mbps_required_seconds":str(network_mbps_minutes*60),
            "abuse_cpu_enabled":"1" if request.form.get("cpu_enabled") else "0",
            "abuse_cpu_full_percent":str(cpu_percent),
            "abuse_cpu_required_seconds":str(cpu_minutes*60),
            "abuse_disk_enabled":"1" if request.form.get("disk_enabled") else "0",
            "abuse_disk_read_bps":str(disk_read_mibps*1024*1024),
            "abuse_disk_write_bps":str(disk_write_mibps*1024*1024),
            "abuse_disk_bps":str(disk_mibps*1024*1024),
            "abuse_disk_iops":str(disk_iops),
            "abuse_disk_required_seconds":str(disk_minutes*60),
        }

    actor = dashboard_username() or get_admin_username() or "admin"
    try:
        cfg = _v4810_save_policy(values,actor,action)
    except Exception as exc:
        app.logger.exception("Could not save abuse policy")
        return redirect(url_for("admin_abuse_page",err=str(exc)[:700]))

    detail = (
        f"action={action};revision={cfg['revision']};network_pps={cfg['network_pps']};"
        f"network_seconds={cfg['network_required_seconds']};network_avg_mbps={cfg['network_avg_mbps']};"
        f"network_mbps_cycles={cfg['network_mbps_required_cycles']};cpu={cfg['cpu_full_percent']};"
        f"cpu_cycles={cfg['cpu_required_cycles']};disk_cycles={cfg['disk_required_cycles']}"
    )
    log_account_event(
        "abuse_policy_saved",username=actor,realm="admin",role="admin",detail=detail[:1000]
    )
    msg = (
        f"Policy v{cfg['revision']} saved and applied. Existing streaks were reset. "
        f"CPU, AVG Mbps and Disk start from the next complete push. PPS becomes authoritative "
        f"after Agent v10 receives v{cfg['revision']} and returns one complete 5-minute sampled window."
    )
    return redirect(url_for("admin_abuse_page",msg=msg))

app.view_functions["admin_abuse_settings"] = admin_abuse_settings_v4810

def _v4810_policy_status():
    cfg = get_abuse_settings()
    stale_after = now_ts() - FAST_CURRENT_STALE_SECONDS
    conn = db()
    try:
        row = conn.execute("""
            SELECT COUNT(*),
                   SUM(CASE WHEN is_abuse=1 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN policy_revision=? AND engine_version=? THEN 1 ELSE 0 END),
                   SUM(CASE WHEN policy_revision=? AND engine_version=? AND network_pps_policy_synced=1 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN policy_revision=? AND engine_version=? AND network_pps_policy_synced=0 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN cpu_streak_cycles>0 OR disk_streak_cycles>0 OR network_rx_mbps_streak_cycles>0 OR network_tx_mbps_streak_cycles>0 THEN 1 ELSE 0 END),
                   MAX(last_seen)
            FROM vm_abuse_state WHERE last_seen>=?
        """, (
            cfg["revision"],ABUSE_ENGINE_VERSION,
            cfg["revision"],ABUSE_ENGINE_VERSION,
            cfg["revision"],ABUSE_ENGINE_VERSION,
            stale_after,
        )).fetchone()
        versions = conn.execute("""
            SELECT revision,changed_at,changed_by,action
            FROM abuse_policy_versions ORDER BY revision DESC LIMIT 5
        """).fetchall()
        progress = conn.execute("""
            SELECT node,vm_uuid,last_seen,is_abuse,abuse_flags,
                   cpu_full_percent,cpu_streak_cycles,
                   rx_mbps,tx_mbps,network_rx_mbps_streak_cycles,network_tx_mbps_streak_cycles,
                   disk_read_bps,disk_write_bps,disk_read_iops,disk_write_iops,disk_streak_cycles,
                   network_pps_policy_synced,network_pps_reported_threshold,
                   seconds_over_rx_pps,seconds_over_tx_pps
            FROM vm_abuse_state
            WHERE last_seen>=? AND policy_revision=? AND engine_version=?
              AND (is_abuse=1 OR cpu_streak_cycles>0 OR disk_streak_cycles>0
                   OR network_rx_mbps_streak_cycles>0 OR network_tx_mbps_streak_cycles>0
                   OR network_pps_policy_synced=0)
            ORDER BY is_abuse DESC,
                     MAX(cpu_streak_cycles*1.0/MAX(?,1),
                         disk_streak_cycles*1.0/MAX(?,1),
                         network_rx_mbps_streak_cycles*1.0/MAX(?,1),
                         network_tx_mbps_streak_cycles*1.0/MAX(?,1)) DESC,
                     last_seen DESC
            LIMIT 30
        """, (
            stale_after,cfg["revision"],ABUSE_ENGINE_VERSION,
            cfg["cpu_required_cycles"],cfg["disk_required_cycles"],
            cfg["network_mbps_required_cycles"],cfg["network_mbps_required_cycles"],
        )).fetchall()
        return cfg,row or (0,0,0,0,0,0,0),versions,progress
    finally:
        conn.close()

def abuse_settings_admin_card():
    cfg,status,versions,progress = _v4810_policy_status()
    total,active,applied,synced,waiting,evaluating,last_seen = [safe_int(x,0) for x in status]
    msg = (request.args.get("abusemsg") or request.args.get("msg") or "").strip()[:700]
    err = (request.args.get("err") or "").strip()[:700]

    version_rows = "".join(
        f'<tr><td class="num">v{safe_int(r[0],0)}</td><td>{fmt_full(r[1])}</td><td>{escape(r[2] or "-")}</td><td>{escape(r[3] or "save")}</td></tr>'
        for r in versions
    ) or '<tr><td colspan="4" class="empty">No policy audit row yet</td></tr>'

    progress_rows = ""
    for r in progress:
        href = url_for("vm_page",node=r[0],vm_uuid=r[1],period="1h")
        cpu_prog = _v4810_progress_bar(r[6],cfg["cpu_required_cycles"])
        mbps_cycles = max(safe_int(r[9],0),safe_int(r[10],0))
        mbps_prog = _v4810_progress_bar(mbps_cycles,cfg["network_mbps_required_cycles"])
        disk_prog = _v4810_progress_bar(r[15],cfg["disk_required_cycles"])
        pps_state = (
            '<span class="sync-badge ok">SYNCED</span>' if safe_int(r[16],0)
            else '<span class="sync-badge wait">WAITING</span>'
        )
        progress_rows += f"""
        <tr><td><a href="{escape(href,quote=True)}"><b>{escape(r[0])}</b></a><small class="row-sub mono">{escape(r[1])}</small></td>
        <td>{'ABUSE' if safe_int(r[3],0) else 'Evaluating'}<small class="row-sub">{escape(r[4] or '-')}</small></td>
        <td><b>{safe_float(r[5],0):.1f}%</b>{cpu_prog}</td>
        <td><b>RX {safe_float(r[7],0):.1f} / TX {safe_float(r[8],0):.1f} Mbps</b>{mbps_prog}</td>
        <td><b>{human_rate(safe_float(r[11],0)+safe_float(r[12],0))}</b><small class="row-sub">{safe_float(r[13],0)+safe_float(r[14],0):,.1f} IOPS</small>{disk_prog}</td>
        <td>{pps_state}<small class="row-sub">agent {safe_float(r[17],0):,.0f} PPS · RX {safe_int(r[18],0)}s · TX {safe_int(r[19],0)}s</small></td>
        <td>{fmt_push(r[2])}</td></tr>"""
    if not progress_rows:
        progress_rows = '<tr><td colspan="7" class="empty">No current VM is progressing toward a rule yet</td></tr>'

    disk_rules = []
    if cfg["disk_read_bps"] > 0: disk_rules.append(f"Read ≥ {human_rate(cfg['disk_read_bps'])}")
    if cfg["disk_write_bps"] > 0: disk_rules.append(f"Write ≥ {human_rate(cfg['disk_write_bps'])}")
    if cfg["disk_bps"] > 0: disk_rules.append(f"R+W ≥ {human_rate(cfg['disk_bps'])}")
    if cfg["disk_iops"] > 0: disk_rules.append(f"IOPS ≥ {cfg['disk_iops']:,.0f}")
    disk_summary = " OR ".join(disk_rules) if disk_rules else "No non-zero disk threshold"

    return f"""
    <style>
      .policy-v4810{{display:grid;grid-template-columns:1.25fr 1fr 1.25fr;gap:12px}}
      .policy-card-v4810{{border:1px solid var(--line,#e5e7eb);border-radius:13px;padding:14px;background:var(--panel-soft,#f8fafc)}}
      .policy-card-v4810 h4{{margin:0 0 11px;display:flex;justify-content:space-between;gap:8px}}
      .policy-card-v4810 label{{display:grid;gap:5px;margin:9px 0;font-size:11px;color:var(--muted,#667085)}}
      .policy-card-v4810 .enable-line{{display:flex;align-items:center;gap:7px;color:inherit;font-weight:800}}
      .policy-card-v4810 .enable-line input{{min-height:auto!important;width:auto}}
      .policy-help-v4810{{font-size:10px;color:var(--muted,#667085);line-height:1.5;margin-top:7px}}
      .policy-status-v4810{{display:grid;grid-template-columns:repeat(6,minmax(115px,1fr));gap:9px;margin:12px 0}}
      .policy-status-v4810>div{{border:1px solid var(--line,#e5e7eb);border-radius:11px;padding:11px;background:var(--panel-soft,#f8fafc)}}
      .policy-status-v4810 small,.policy-status-v4810 b{{display:block}}.policy-status-v4810 b{{font-size:20px;margin-top:4px}}
      .rule-progress{{height:5px;border-radius:99px;background:#e5e7eb;overflow:hidden;margin-top:5px}}.rule-progress span{{display:block;height:100%;background:#2563eb}}
      .sync-badge{{display:inline-flex;padding:4px 7px;border-radius:999px;font-size:9px;font-weight:900}}.sync-badge.ok{{background:#dcfce7;color:#166534}}.sync-badge.wait{{background:#fef3c7;color:#92400e}}
      .policy-actions-v4810{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px}}
      @media(max-width:1100px){{.policy-v4810{{grid-template-columns:1fr}}.policy-status-v4810{{grid-template-columns:repeat(3,minmax(110px,1fr))}}}}
      @media(max-width:680px){{.policy-status-v4810{{grid-template-columns:repeat(2,minmax(100px,1fr))}}}}
    </style>
    <div class="card" id="abuse-policy-admin">
      <div class="section-head"><div><span class="eyebrow">AUTHORITATIVE POLICY</span><h3>VM Abuse Policy</h3><p>Policy v{cfg['revision']} · engine {ABUSE_ENGINE_VERSION} · saved {fmt_full(cfg['policy_updated_at']) if cfg['policy_updated_at'] else '-'}</p></div><div class="hero-meta"><span>Cycle <b>5 minutes</b></span><span>Rule source <b>Admin DB</b></span><span>Restart <b>not required</b></span></div></div>
      {f'<div class="success-box">{escape(msg)}</div>' if msg else ''}
      {f'<div class="error-box">{escape(err)}</div>' if err else ''}
      <div class="admin-note"><b>How Apply works:</b> saving creates a new policy revision and resets only current streak counters. Abuse history is not deleted. CPU, AVG Mbps and Disk start counting on the next complete push. PPS is accepted only after Agent v10 reports the exact new threshold, preventing old and new rules from being mixed.</div>
      <div class="policy-status-v4810">
        <div><small>Tracked current</small><b>{total:,}</b></div><div><small>Active abuse</small><b>{active:,}</b></div>
        <div><small>Policy applied</small><b>{applied:,}</b></div><div><small>PPS synced</small><b>{synced:,}</b></div>
        <div><small>PPS waiting</small><b>{waiting:,}</b></div><div><small>Evaluating</small><b>{evaluating:,}</b></div>
      </div>
      <form method="post" action="{url_for('admin_abuse_settings')}">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="action" value="save">
        <div class="policy-v4810">
          <div class="policy-card-v4810"><h4><span>Network</span><small>Directional</small></h4>
            <label class="enable-line"><input type="checkbox" name="network_enabled" {'checked' if cfg['network_enabled'] else ''}> Enable RX or TX PPS</label>
            <label>PPS threshold<input type="number" name="network_pps" min="1000" max="100000000" step="1000" value="{cfg['network_pps']:.0f}"></label>
            <label>Required seconds inside one 5-minute sampled window<input type="number" name="network_required_seconds" min="15" max="300" step="15" value="{cfg['network_required_seconds']}"></label>
            <hr><label class="enable-line"><input type="checkbox" name="network_mbps_enabled" {'checked' if cfg['network_mbps_enabled'] else ''}> Enable RX or TX AVG Mbps</label>
            <label>AVG Mbps threshold<input type="number" name="network_avg_mbps" min="0" max="1000000" step="10" value="{cfg['network_avg_mbps']:.1f}"></label>
            <label>Consecutive minutes<input type="number" name="network_mbps_required_minutes" min="5" max="1440" step="5" value="{cfg['network_mbps_required_seconds']//60}"></label>
            <div class="policy-help-v4810">Current rule: {cfg['network_mbps_required_cycles']*5} consecutive minute(s). RX and TX are evaluated independently.</div>
          </div>
          <div class="policy-card-v4810"><h4><span>CPU</span><small>Normalized</small></h4>
            <label class="enable-line"><input type="checkbox" name="cpu_enabled" {'checked' if cfg['cpu_enabled'] else ''}> Enable CPU abuse</label>
            <label>CPU Full % of assigned vCPU<input type="number" name="cpu_full_percent" min="1" max="100" step="0.1" value="{cfg['cpu_full_percent']:.1f}"></label>
            <label>Consecutive minutes<input type="number" name="cpu_required_minutes" min="5" max="1440" step="5" value="{cfg['cpu_required_seconds']//60}"></label>
            <div class="policy-help-v4810">Current rule: {cfg['cpu_required_cycles']*5} consecutive minute(s). Example: 360 Core% on 4 vCPU = 90 Full%.</div>
          </div>
          <div class="policy-card-v4810"><h4><span>Disk I/O</span><small>OR logic</small></h4>
            <label class="enable-line"><input type="checkbox" name="disk_enabled" {'checked' if cfg['disk_enabled'] else ''}> Enable disk abuse</label>
            <label>Read MiB/s <small>0 disables</small><input type="number" name="disk_read_mibps" min="0" max="100000" step="1" value="{cfg['disk_read_bps']/1024/1024:.0f}"></label>
            <label>Write MiB/s <small>0 disables</small><input type="number" name="disk_write_mibps" min="0" max="100000" step="1" value="{cfg['disk_write_bps']/1024/1024:.0f}"></label>
            <label>Read + Write MiB/s <small>0 disables</small><input type="number" name="disk_mibps" min="0" max="100000" step="1" value="{cfg['disk_bps']/1024/1024:.0f}"></label>
            <label>Total IOPS <small>0 disables</small><input type="number" name="disk_iops" min="0" max="10000000" step="100" value="{cfg['disk_iops']:.0f}"></label>
            <label>Consecutive minutes<input type="number" name="disk_required_minutes" min="5" max="1440" step="5" value="{cfg['disk_required_seconds']//60}"></label>
            <div class="policy-help-v4810">{escape(disk_summary)} · {cfg['disk_required_cycles']*5} consecutive minute(s).</div>
          </div>
        </div>
        <div class="policy-actions-v4810"><button type="submit">Save & Apply New Revision</button><a class="btn" href="{url_for('vm_abuse_page')}">Open Abuse Viewer</a><span class="table-hint">Last current-state push: {fmt_push(last_seen) if last_seen else '-'}</span></div>
      </form>
      <form method="post" action="{url_for('admin_abuse_settings')}" onsubmit="return confirm('Reset all abuse thresholds to defaults and start a new policy revision?')" style="margin-top:8px">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="action" value="reset"><button class="btn" type="submit">Reset defaults</button>
      </form>
    </div>
    <details class="card admin-fold"><summary>Rule engine progress and PPS synchronization</summary><div class="fold-content">
      <div class="table-wrap"><table class="admin-clean-table"><thead><tr><th>VM</th><th>STATE</th><th>CPU</th><th>AVG Mbps</th><th>DISK</th><th>PPS POLICY</th><th>PUSH</th></tr></thead><tbody>{progress_rows}</tbody></table></div>
    </div></details>
    <details class="card admin-fold"><summary>Recent policy revisions</summary><div class="fold-content"><div class="table-wrap"><table><thead><tr><th>REVISION</th><th>CHANGED</th><th>ADMIN</th><th>ACTION</th></tr></thead><tbody>{version_rows}</tbody></table></div></div></details>
    """

def _v4810_current_abuse_query(q,sort_by,order,limit):
    allowed = {
        "severity":"a.severity","node":"a.node COLLATE NOCASE","vm":"a.vm_uuid COLLATE NOCASE",
        "rx_mbps":"a.rx_mbps","tx_mbps":"a.tx_mbps","rx_pps":"a.rx_pps","tx_pps":"a.tx_pps",
        "rx_peak":"a.rx_peak_pps","tx_peak":"a.tx_peak_pps","cpu":"a.cpu_full_percent",
        "vcpu":"a.vcpu_current","diskr":"a.disk_read_bps","diskw":"a.disk_write_bps",
        "iops":"(a.disk_read_iops+a.disk_write_iops)","last_seen":"a.last_seen","since":"a.abuse_since",
    }
    sort_by = sort_by if sort_by in allowed else "severity"
    order = clean_sort_order(order)
    cfg = get_abuse_settings()
    params = [now_ts()-FAST_CURRENT_STALE_SECONDS,cfg["revision"],ABUSE_ENGINE_VERSION]
    search_sql = ""
    if q:
        p = like_pattern(q)
        search_sql = """ AND (a.node LIKE ? OR a.vm_uuid LIKE ? OR EXISTS(
          SELECT 1 FROM node_bridge_addresses_latest b WHERE b.node=a.node
          AND (COALESCE(b.primary_ipv4,'') LIKE ? OR COALESCE(b.ipv4_json,'') LIKE ?)))"""
        params.extend([p,p,p,p])
    conn = db()
    try:
        base_where = "a.is_abuse=1 AND a.last_seen>=? AND a.policy_revision=? AND a.engine_version=?"
        total = safe_int(conn.execute(
            f"SELECT COUNT(*) FROM vm_abuse_state a WHERE {base_where} {search_sql}",params
        ).fetchone()[0],0)
        counts = conn.execute(f"""
          SELECT SUM(CASE WHEN a.abuse_flags LIKE '%PPS%' THEN 1 ELSE 0 END),
                 SUM(CASE WHEN a.abuse_flags LIKE '%AVG_MBPS%' THEN 1 ELSE 0 END),
                 SUM(CASE WHEN a.abuse_flags LIKE '%CPU%' THEN 1 ELSE 0 END),
                 SUM(CASE WHEN a.abuse_flags LIKE '%DISK%' THEN 1 ELSE 0 END)
          FROM vm_abuse_state a WHERE {base_where} {search_sql}
        """,params).fetchone()
        rows = conn.execute(f"""
          SELECT a.node,a.vm_uuid,a.last_seen,a.abuse_since,a.abuse_flags,a.severity,
                 a.rx_pps,a.tx_pps,a.rx_peak_pps,a.tx_peak_pps,
                 a.seconds_over_rx_pps,a.seconds_over_tx_pps,
                 a.cpu_full_percent,a.cpu_core_percent,a.vcpu_current,a.cpu_streak_seconds,
                 a.disk_read_bps,a.disk_write_bps,a.disk_read_iops,a.disk_write_iops,a.disk_streak_seconds,
                 COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest b WHERE b.node=a.node AND LOWER(role)='public' LIMIT 1),''),
                 COALESCE(a.rx_mbps,0),COALESCE(a.tx_mbps,0),
                 COALESCE(a.network_rx_mbps_streak_seconds,0),COALESCE(a.network_tx_mbps_streak_seconds,0),
                 COALESCE(a.cpu_streak_cycles,0),COALESCE(a.disk_streak_cycles,0),
                 COALESCE(a.network_rx_mbps_streak_cycles,0),COALESCE(a.network_tx_mbps_streak_cycles,0),
                 COALESCE(a.network_pps_policy_synced,0),COALESCE(a.network_pps_reported_threshold,0),
                 COALESCE(a.policy_revision,0)
          FROM vm_abuse_state a
          LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
          WHERE {base_where} AND COALESCE(vi.status,'active')!='hidden' {search_sql}
          ORDER BY {allowed[sort_by]} {order.upper()},a.last_seen DESC,a.node COLLATE NOCASE,a.vm_uuid COLLATE NOCASE
          LIMIT ?
        """,params+[limit]).fetchall()
        return rows,total,tuple(safe_int(x,0) for x in (counts or (0,0,0,0))),sort_by,order,cfg
    finally:
        conn.close()

def _v4810_metric_pair(label_a,value_a,label_b,value_b,sub_a="",sub_b=""):
    return f"""<div class="metric-pair"><div><span>{escape(label_a)}</span><b>{value_a}</b>{f'<small>{escape(sub_a)}</small>' if sub_a else ''}</div><div><span>{escape(label_b)}</span><b>{value_b}</b>{f'<small>{escape(sub_b)}</small>' if sub_b else ''}</div></div>"""

def _v4810_abuse_current_page(q,sort_by,order,limit):
    rows,total,counts,sort_by,order,cfg = _v4810_current_abuse_query(q,sort_by,order,limit)
    def h(label,key):
        next_order = reverse_order(order) if sort_by == key else "desc"
        arrow = " ↓" if sort_by == key and order == "desc" else (" ↑" if sort_by == key else "")
        href = url_for("vm_abuse_page",tab="current",q=q or None,sort=key,order=next_order,limit=limit)
        return f'<a class="sort-link" href="{escape(href,quote=True)}">{escape(label)}{arrow}</a>'

    body = ""
    for rank,r in enumerate(rows,1):
        labels = _abuse_flag_labels(r[4],cfg)
        reasons = "".join(metric_pill(escape(x),"crit") for x in labels)
        href = url_for("vm_page",node=r[0],vm_uuid=r[1],period="1h")
        ip = compact_ipv4(r[21])
        network = _v4810_metric_pair(
            "RX AVG",f"{safe_float(r[22],0):.2f} Mbps","TX AVG",f"{safe_float(r[23],0):.2f} Mbps",
            f"{safe_int(r[28],0)}/{cfg['network_mbps_required_cycles']} cycles",
            f"{safe_int(r[29],0)}/{cfg['network_mbps_required_cycles']} cycles",
        )
        pps_sync = "synced" if safe_int(r[30],0) else "waiting"
        peak = _v4810_metric_pair(
            "RX PEAK",f"{fmt_pps_value(r[8])} PPS","TX PEAK",f"{fmt_pps_value(r[9])} PPS",
            f"{safe_int(r[10],0)}s high · {pps_sync}",f"{safe_int(r[11],0)}s high · {pps_sync}",
        )
        cpu = f'<div class="metric-stack"><b>{safe_float(r[12],0):.1f}%</b><span>{safe_int(r[14],0)} vCPU</span><small>{safe_int(r[26],0)}/{cfg["cpu_required_cycles"]} cycles</small></div>'
        disk_iops = safe_float(r[18],0)+safe_float(r[19],0)
        disk = _v4810_metric_pair(
            "READ",human_rate(r[16]),"WRITE",human_rate(r[17]),
            f"{disk_iops:,.1f} IOPS",f"{safe_int(r[27],0)}/{cfg['disk_required_cycles']} cycles",
        )
        timeline = f'<div class="timeline-cell"><b>{fmt_full(r[3]) if r[3] else "-"}</b><small>Started</small><span>{fmt_push(r[2])}</span><small>Last push · policy v{safe_int(r[32],0)}</small></div>'
        body += f"""
        <tr><td class="rank-cell">{rank}</td><td class="identity-cell"><div class="node-line"><a href="{escape(href,quote=True)}"><b>{escape(r[0])}</b></a>{f'<span>{escape(ip)}</span>' if ip else ''}</div><div class="uuid-line"><a class="mono" href="{escape(href,quote=True)}">{escape(r[1])}</a><button type="button" class="copy-btn" data-copy="{escape(r[1],quote=True)}">⧉</button></div></td>
        <td class="reason-cell"><div class="severity-line"><b>{safe_float(r[5],0):.2f}x</b><span>severity</span></div><div class="abuse-reasons">{reasons}</div></td><td>{network}</td><td>{peak}</td><td>{cpu}</td><td>{disk}</td><td>{timeline}</td></tr>"""
    if not body:
        body = '<tr><td colspan="8" class="empty">No VM currently satisfies the active policy revision</td></tr>'

    current_href = url_for("vm_abuse_page",tab="current",q=q or None,sort=sort_by,order=order,limit=limit)
    history_href = url_for("vm_abuse_page",tab="history",q=q or None,limit=limit)
    search = f"""<form class="search compact-search" method="get" action="{url_for('vm_abuse_page')}"><input type="hidden" name="tab" value="current"><input type="hidden" name="sort" value="{escape(sort_by,quote=True)}"><input type="hidden" name="order" value="{escape(order,quote=True)}"><input name="q" value="{escape(q,quote=True)}" placeholder="Search node, IPv4 or VM UUID"><select name="limit"><option value="100" {'selected' if limit==100 else ''}>100 rows</option><option value="200" {'selected' if limit==200 else ''}>200 rows</option><option value="500" {'selected' if limit==500 else ''}>500 rows</option></select><button type="submit">Search</button>{f'<a class="clear" href="{url_for("vm_abuse_page",tab="current",limit=limit)}">Reset</a>' if q else ''}</form>"""
    tabs = f'<div class="abuse-tabs"><a class="active" href="{escape(current_href,quote=True)}">Current Abuse</a><a href="{escape(history_href,quote=True)}">History / Logs</a></div>'
    table = f"""<div class="card abuse-current-card"><div class="section-head"><div><h3>Current VM Abuse</h3><p>Policy v{cfg['revision']} · exact 5-minute cycle engine · bounded current-state query.</p></div><div class="count-badges"><span>All <b>{total}</b></span><span>PPS <b>{counts[0]}</b></span><span>AVG Mbps <b>{counts[1]}</b></span><span>CPU <b>{counts[2]}</b></span><span>Disk <b>{counts[3]}</b></span></div></div><div class="table-wrap"><table class="abuse-v490-table"><colgroup><col class="c-rank"><col class="c-id"><col class="c-reason"><col class="c-network"><col class="c-peak"><col class="c-cpu"><col class="c-disk"><col class="c-time"></colgroup><thead><tr><th>#</th><th>{h('NODE / VM','node')}</th><th>{h('REASON / SEVERITY','severity')}</th><th><div>NETWORK AVG</div><small>{h('RX Mbps','rx_mbps')} · {h('TX Mbps','tx_mbps')}</small></th><th><div>PPS PEAK / WINDOW</div><small>{h('RX PPS','rx_peak')} · {h('TX PPS','tx_peak')}</small></th><th>{h('CPU','cpu')}</th><th>{h('DISK','iops')}</th><th>{h('TIMELINE','last_seen')}</th></tr></thead><tbody>{body}</tbody></table></div></div>"""
    return f"""<div class="card page-hero"><div><span class="eyebrow">ABUSE MONITORING</span><h2>VM Abuse</h2><p>Admin policy is authoritative. Directional PPS is sampler-verified; sustained monitor rules use complete five-minute cycles.</p></div><div class="hero-meta"><span>Policy <b>v{cfg['revision']}</b></span><span>Engine <b>{ABUSE_ENGINE_VERSION}</b></span><span>Delete <b>Admin only</b></span></div></div><div class="card abuse-toolbar">{tabs}{search}</div><details class="card policy-fold"><summary>Current policy</summary>{_public_abuse_policy(cfg)}</details>{table}"""

def vm_abuse_page_v4810():
    tab = (request.args.get("tab") or "current").strip().lower()
    if tab == "history":
        return vm_abuse_page_v483()
    q = (request.args.get("q") or "").strip()
    sort_by = (request.args.get("sort") or "severity").strip().lower()
    order = clean_sort_order(request.args.get("order","desc"))
    limit = max(10,min(1000,safe_int(request.args.get("limit"),200)))
    return page("VM Abuse",_v4810_abuse_current_page(q,sort_by,order,limit))

app.view_functions["vm_abuse_page"] = vm_abuse_page_v4810

# Add a final visual polish layer for the new policy diagnostics without changing
# the rest of the v48.9 theme.
V4810_GLOBAL_CSS = """
<style>
.app-v490 .policy-v4810 hr{border:0;border-top:1px solid var(--line,#e5e7eb);margin:13px 0}
.app-v490 .policy-status-v4810 small{color:var(--muted,#667085)}
.app-v490 .policy-status-v4810 b{color:var(--text,#101828)}
html[data-theme=dark] .policy-card-v4810,html[data-theme=dark] .policy-status-v4810>div{background:#132238!important;border-color:#2b3d57!important}
html[data-theme=dark] .rule-progress{background:#26374f}html[data-theme=dark] .policy-status-v4810 b{color:#e7edf7}
</style>
"""
_page_v4810_base = page

def page(title,content):
    response = _page_v4810_base(title,content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace("</head>",V4810_GLOBAL_CSS+"</head>",1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.10.0 visual layer")
    return response

def _merge_event_abuse_cfg(current_cfg, event_cfg):
    merged = dict(current_cfg)
    event_cfg = event_cfg if isinstance(event_cfg, dict) else {}
    for key, value in event_cfg.items():
        if key in merged:
            merged[key] = value
    if "disk_read_bps" not in event_cfg:
        merged["disk_read_bps"] = 0.0
    if "disk_write_bps" not in event_cfg:
        merged["disk_write_bps"] = 0.0
    merged["network_mbps_required_cycles"] = _v4810_required_cycles(
        merged.get("network_mbps_required_seconds", 300)
    )
    merged["cpu_required_cycles"] = _v4810_required_cycles(
        merged.get("cpu_required_seconds", 1800)
    )
    merged["disk_required_cycles"] = _v4810_required_cycles(
        merged.get("disk_required_seconds", 900)
    )
    merged["disk_effective_enabled"] = bool(
        merged.get("disk_enabled") and any(
            safe_float(merged.get(key),0) > 0
            for key in ("disk_read_bps","disk_write_bps","disk_bps","disk_iops")
        )
    )
    return merged

