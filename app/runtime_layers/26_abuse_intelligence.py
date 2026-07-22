from collections import defaultdict, Counter

V48126_VERSION = "48.12.6"
ABUSE_ENGINE_VERSION = "cycles-v3-ram"

# RAM policy is intentionally disabled on upgrade. Admin can enable one or more
# conditions and apply a new revision without redeploying Agent v10.
ABUSE_SETTING_DEFAULTS.update({
    "abuse_ram_enabled": "0",
    "abuse_ram_rss_percent": "95",
    "abuse_ram_guest_used_percent": "95",
    "abuse_ram_low_usable_percent": "5",
    "abuse_ram_required_seconds": "600",
})

def _v48126_duration(seconds):
    seconds = max(0, safe_int(seconds, 0))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours:02d}h"

def _v48126_primary_type(flags):
    values = [str(x or "").upper() for x in (flags if isinstance(flags, (list, tuple, set)) else _v4810_canonical_flags(flags))]
    if any("NETWORK" in value for value in values):
        return "network"
    if any("CPU" in value for value in values):
        return "cpu"
    if any("RAM" in value for value in values):
        return "ram"
    if any("DISK" in value for value in values):
        return "disk"
    return "other"

def _v48126_flag_union(*values):
    result = []
    for value in values:
        for flag in _v4810_canonical_flags(value):
            if flag not in result:
                result.append(flag)
    return result

def _v48126_incident_score(duration_seconds, max_severity):
    # Every occurrence contributes one point. Duration and severity then add
    # weight, so repeated short incidents and long severe incidents are both visible.
    return round(1.0 + (max(0, safe_int(duration_seconds, 0)) / 3600.0) * max(1.0, safe_float(max_severity, 1.0)), 4)

def _v48126_visible_sql(node_alias="ni", vm_alias="vi"):
    return (
        f"({node_alias}.node IS NULL OR (COALESCE({node_alias}.status,'active')!='hidden' AND {node_alias}.deleted_at IS NULL)) "
        f"AND ({vm_alias}.node IS NULL OR (COALESCE({vm_alias}.status,'active')!='hidden' AND {vm_alias}.deleted_at IS NULL))"
    )

def _v48126_is_visible(conn, node, vm_uuid=None):
    row = conn.execute(
        "SELECT status,deleted_at FROM node_inventory WHERE node=?",
        (str(node or ""),),
    ).fetchone()
    if row and (str(row[0] or "active") == "hidden" or row[1] is not None):
        return False
    if vm_uuid is not None:
        row = conn.execute(
            "SELECT status,deleted_at FROM vm_inventory WHERE node=? AND vm_uuid=?",
            (str(node or ""), str(vm_uuid or "")),
        ).fetchone()
        if row and (str(row[0] or "active") == "hidden" or row[1] is not None):
            return False
    return True

def _v48126_close_incident(conn, incident_id, ended_at, max_severity=None, flags=None, event_count_increment=0):
    row = conn.execute(
        "SELECT started_at,max_severity,abuse_flags,event_count FROM vm_abuse_incidents WHERE id=?",
        (incident_id,),
    ).fetchone()
    if not row:
        return
    started_at = safe_int(row[0], ended_at)
    severity = max(safe_float(row[1], 0), safe_float(max_severity, 0))
    merged = _v48126_flag_union(row[2], flags or "")
    duration = max(0, safe_int(ended_at, started_at) - started_at)
    conn.execute(
        """UPDATE vm_abuse_incidents
           SET ended_at=?,duration_seconds=?,max_severity=?,weighted_score=?,
               abuse_flags=?,primary_type=?,event_count=?,last_event_at=?,status='closed'
           WHERE id=?""",
        (
            safe_int(ended_at, started_at), duration, severity,
            _v48126_incident_score(duration, severity), ",".join(merged),
            _v48126_primary_type(merged), max(1, safe_int(row[3], 1) + safe_int(event_count_increment, 0)),
            safe_int(ended_at, started_at), incident_id,
        ),
    )

def _v48126_apply_incident_event(conn, event_type, state, event_time, flags, severity, policy_revision, engine_version):
    event_type = str(event_type or "updated").strip().lower()
    node = str((state or {}).get("node") or "")
    vm_uuid = str((state or {}).get("vm_uuid") or "")
    if not node or not vm_uuid:
        return
    event_time = safe_int(event_time, now_ts())
    severity = max(0.0, safe_float(severity, 0))
    flags_list = _v48126_flag_union(flags)
    flags_text = ",".join(flags_list)
    primary_type = _v48126_primary_type(flags_list)
    open_row = conn.execute(
        "SELECT id,started_at,max_severity,abuse_flags,event_count FROM vm_abuse_incidents WHERE node=? AND vm_uuid=? AND status='open' ORDER BY id DESC LIMIT 1",
        (node, vm_uuid),
    ).fetchone()

    if event_type == "started":
        if open_row:
            _v48126_close_incident(conn, safe_int(open_row[0], 0), event_time, severity, flags_text)
        conn.execute(
            """INSERT INTO vm_abuse_incidents(
                 node,vm_uuid,started_at,ended_at,duration_seconds,max_severity,weighted_score,
                 abuse_flags,primary_type,event_count,last_event_at,status,policy_revision,engine_version
               ) VALUES(?,?,?,NULL,0,?,0,?,?,1,?,'open',?,?)""",
            (node, vm_uuid, event_time, severity, flags_text, primary_type, event_time,
             safe_int(policy_revision, 0), str(engine_version or ABUSE_ENGINE_VERSION)),
        )
        return

    if event_type == "recovered":
        if open_row:
            _v48126_close_incident(conn, safe_int(open_row[0], 0), event_time, severity, flags_text, 1)
        else:
            started_at = max(0, safe_int((state or {}).get("abuse_since"), event_time)) or event_time
            duration = max(0, event_time - started_at)
            conn.execute(
                """INSERT INTO vm_abuse_incidents(
                     node,vm_uuid,started_at,ended_at,duration_seconds,max_severity,weighted_score,
                     abuse_flags,primary_type,event_count,last_event_at,status,policy_revision,engine_version
                   ) VALUES(?,?,?,?,?,?,?,?,?,1,?,'closed',?,?)""",
                (node, vm_uuid, started_at, event_time, duration, severity,
                 _v48126_incident_score(duration, severity), flags_text, primary_type, event_time,
                 safe_int(policy_revision, 0), str(engine_version or ABUSE_ENGINE_VERSION)),
            )
        return

    # UPDATED and other state-transition events update the current open episode.
    if not open_row:
        started_at = max(0, safe_int((state or {}).get("abuse_since"), event_time)) or event_time
        conn.execute(
            """INSERT INTO vm_abuse_incidents(
                 node,vm_uuid,started_at,ended_at,duration_seconds,max_severity,weighted_score,
                 abuse_flags,primary_type,event_count,last_event_at,status,policy_revision,engine_version
               ) VALUES(?,?,?,NULL,0,?,0,?,?,1,?,'open',?,?)""",
            (node, vm_uuid, started_at, severity, flags_text, primary_type, event_time,
             safe_int(policy_revision, 0), str(engine_version or ABUSE_ENGINE_VERSION)),
        )
    else:
        merged = _v48126_flag_union(open_row[3], flags_text)
        conn.execute(
            """UPDATE vm_abuse_incidents
               SET max_severity=?,abuse_flags=?,primary_type=?,event_count=?,last_event_at=?,
                   policy_revision=?,engine_version=? WHERE id=?""",
            (
                max(safe_float(open_row[2], 0), severity), ",".join(merged),
                _v48126_primary_type(merged), max(1, safe_int(open_row[4], 1) + 1), event_time,
                safe_int(policy_revision, 0), str(engine_version or ABUSE_ENGINE_VERSION), safe_int(open_row[0], 0),
            ),
        )

def _v48126_rebuild_incidents(conn):
    conn.execute("DELETE FROM vm_abuse_incidents")
    cutoff = now_ts() - 7 * 86400
    rows = conn.execute(
        """SELECT event_time,event_type,node,vm_uuid,abuse_flags,severity,policy_revision,engine_version
           FROM vm_abuse_events WHERE event_time>=?
           ORDER BY node COLLATE NOCASE,vm_uuid,event_time,id""",
        (cutoff,),
    ).fetchall()
    for event_time, event_type, node, vm_uuid, flags, severity, revision, engine in rows:
        state = {"node": node, "vm_uuid": vm_uuid, "abuse_since": event_time}
        _v48126_apply_incident_event(
            conn, event_type, state, event_time, flags, severity, revision, engine,
        )

def _v48126_migrate_schema():
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        state_columns = {
            "ram_streak_seconds": "INTEGER NOT NULL DEFAULT 0",
            "ram_streak_cycles": "INTEGER NOT NULL DEFAULT 0",
            "ram_current_kib": "INTEGER NOT NULL DEFAULT 0",
            "ram_rss_kib": "INTEGER NOT NULL DEFAULT 0",
            "ram_available_kib": "INTEGER NOT NULL DEFAULT 0",
            "ram_usable_kib": "INTEGER NOT NULL DEFAULT 0",
            "ram_rss_percent": "REAL NOT NULL DEFAULT 0",
            "ram_guest_used_percent": "REAL NOT NULL DEFAULT -1",
            "ram_usable_percent": "REAL NOT NULL DEFAULT -1",
        }
        for column, ddl in state_columns.items():
            ensure_column(conn, "vm_abuse_state", column, ddl)
        event_columns = {
            "ram_streak_seconds": "INTEGER NOT NULL DEFAULT 0",
            "ram_current_kib": "INTEGER NOT NULL DEFAULT 0",
            "ram_rss_kib": "INTEGER NOT NULL DEFAULT 0",
            "ram_available_kib": "INTEGER NOT NULL DEFAULT 0",
            "ram_usable_kib": "INTEGER NOT NULL DEFAULT 0",
            "ram_rss_percent": "REAL NOT NULL DEFAULT 0",
            "ram_guest_used_percent": "REAL NOT NULL DEFAULT -1",
            "ram_usable_percent": "REAL NOT NULL DEFAULT -1",
        }
        for column, ddl in event_columns.items():
            ensure_column(conn, "vm_abuse_events", column, ddl)
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS vm_abuse_incidents (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          node TEXT NOT NULL,
          vm_uuid TEXT NOT NULL,
          started_at INTEGER NOT NULL,
          ended_at INTEGER,
          duration_seconds INTEGER NOT NULL DEFAULT 0,
          max_severity REAL NOT NULL DEFAULT 0,
          weighted_score REAL NOT NULL DEFAULT 0,
          abuse_flags TEXT NOT NULL DEFAULT '',
          primary_type TEXT NOT NULL DEFAULT 'other',
          event_count INTEGER NOT NULL DEFAULT 1,
          last_event_at INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'open',
          policy_revision INTEGER NOT NULL DEFAULT 0,
          engine_version TEXT NOT NULL DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_vm_abuse_incident_open
          ON vm_abuse_incidents(node,vm_uuid) WHERE status='open';
        CREATE INDEX IF NOT EXISTS idx_vm_abuse_incidents_started
          ON vm_abuse_incidents(started_at DESC,id DESC);
        CREATE INDEX IF NOT EXISTS idx_vm_abuse_incidents_vm
          ON vm_abuse_incidents(node,vm_uuid,started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_vm_abuse_incidents_score
          ON vm_abuse_incidents(weighted_score DESC,max_severity DESC,started_at DESC);
        """)
        now = now_ts()
        # cycles-v3 adds RAM but keeps the cycles-v2 Network/CPU/Disk
        # semantics. Preserve current truth and existing streaks across the
        # upgrade, initialize only RAM state, and adopt the new engine marker.
        conn.execute(
            """UPDATE vm_abuse_state SET
                   ram_streak_seconds=0,ram_streak_cycles=0,
                   ram_rss_percent=0,ram_guest_used_percent=-1,ram_usable_percent=-1,
                   engine_version=? WHERE COALESCE(engine_version,'')!=?""",
            (ABUSE_ENGINE_VERSION, ABUSE_ENGINE_VERSION),
        )
        marker = conn.execute(
            "SELECT value FROM admin_settings WHERE key='v48126_incident_backfill'"
        ).fetchone()
        if not marker:
            _v48126_rebuild_incidents(conn)
            conn.execute(
                "INSERT INTO admin_settings(key,value,updated_at) VALUES('v48126_incident_backfill','1',?)",
                (now,),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

_v48126_migrate_schema()

# ---------- Dynamic policy with RAM ---------------------------------------
_v48126_get_abuse_settings_base = get_abuse_settings
_v48126_apply_settings_base = _apply_abuse_settings_to_runtime
_v48126_policy_json_base = _v4810_policy_json
_v48126_reset_state_base = _v4810_reset_current_state_for_policy

def get_abuse_settings(conn=None):
    own = conn is None
    if own:
        conn = db()
    try:
        cfg = _v48126_get_abuse_settings_base(conn)
        keys = (
            "abuse_ram_enabled", "abuse_ram_rss_percent",
            "abuse_ram_guest_used_percent", "abuse_ram_low_usable_percent",
            "abuse_ram_required_seconds",
        )
        placeholders = ",".join("?" for _ in keys)
        values = dict(ABUSE_SETTING_DEFAULTS)
        for key, value in conn.execute(
            f"SELECT key,value FROM admin_settings WHERE key IN ({placeholders})", keys
        ).fetchall():
            values[str(key)] = str(value)
        cfg.update({
            "ram_enabled": _setting_bool(values["abuse_ram_enabled"], False),
            "ram_rss_percent": max(0.0, min(100.0, safe_float(values["abuse_ram_rss_percent"], 95.0))),
            "ram_guest_used_percent": max(0.0, min(100.0, safe_float(values["abuse_ram_guest_used_percent"], 95.0))),
            "ram_low_usable_percent": max(0.0, min(100.0, safe_float(values["abuse_ram_low_usable_percent"], 5.0))),
            "ram_required_seconds": max(300, min(86400, safe_int(values["abuse_ram_required_seconds"], 600))),
        })
        cfg["ram_required_cycles"] = _v4810_required_cycles(cfg["ram_required_seconds"])
        cfg["ram_effective_enabled"] = bool(
            cfg["ram_enabled"] and any(
                safe_float(cfg[key], 0) > 0 for key in (
                    "ram_rss_percent", "ram_guest_used_percent", "ram_low_usable_percent"
                )
            )
        )
        cfg["engine_version"] = ABUSE_ENGINE_VERSION
        return cfg
    finally:
        if own:
            conn.close()

def _apply_abuse_settings_to_runtime(cfg):
    _v48126_apply_settings_base(cfg)
    global ABUSE_RAM_RSS_PERCENT
    ABUSE_RAM_RSS_PERCENT = cfg["ram_rss_percent"] if cfg.get("ram_effective_enabled") else 10**9

def _v4810_policy_json(cfg):
    result = _v48126_policy_json_base(cfg)
    result.update({
        "engine_version": ABUSE_ENGINE_VERSION,
        "ram_enabled": bool(cfg.get("ram_enabled")),
        "ram_effective_enabled": bool(cfg.get("ram_effective_enabled")),
        "ram_rss_percent": safe_float(cfg.get("ram_rss_percent"), 0),
        "ram_guest_used_percent": safe_float(cfg.get("ram_guest_used_percent"), 0),
        "ram_low_usable_percent": safe_float(cfg.get("ram_low_usable_percent"), 0),
        "ram_required_seconds": safe_int(cfg.get("ram_required_seconds"), 600),
        "ram_required_cycles": safe_int(cfg.get("ram_required_cycles"), 2),
    })
    return result

def _v4810_reset_current_state_for_policy(conn, revision, changed_at):
    # A policy revision starts a new evaluation epoch. Close open incidents at
    # the exact revision boundary before current streaks are reset.
    for incident_row in conn.execute(
        "SELECT id FROM vm_abuse_incidents WHERE status='open'"
    ).fetchall():
        _v48126_close_incident(conn, safe_int(incident_row[0], 0), changed_at)
    _v48126_reset_state_base(conn, revision, changed_at)
    conn.execute(
        """UPDATE vm_abuse_state SET ram_streak_seconds=0,ram_streak_cycles=0,
               ram_rss_percent=0,ram_guest_used_percent=-1,ram_usable_percent=-1,
               engine_version=?""",
        (ABUSE_ENGINE_VERSION,),
    )

def _v4810_state_map(conn, node):
    rows = conn.execute("""
        SELECT node,vm_uuid,last_seen,is_abuse,abuse_since,abuse_flags,severity,
               network_rx_hit,network_tx_hit,cpu_streak_seconds,disk_streak_seconds,
               rx_pps,tx_pps,rx_peak_pps,tx_peak_pps,seconds_over_rx_pps,seconds_over_tx_pps,
               cpu_full_percent,cpu_core_percent,vcpu_current,
               disk_read_bps,disk_write_bps,disk_read_iops,disk_write_iops,
               COALESCE(network_rx_mbps_hit,0),COALESCE(network_tx_mbps_hit,0),
               COALESCE(network_rx_mbps_streak_seconds,0),COALESCE(network_tx_mbps_streak_seconds,0),
               COALESCE(rx_mbps,0),COALESCE(tx_mbps,0),
               COALESCE(policy_revision,0),COALESCE(policy_applied_at,0),COALESCE(last_eval_bucket,0),
               COALESCE(cpu_streak_cycles,0),COALESCE(disk_streak_cycles,0),
               COALESCE(network_rx_mbps_streak_cycles,0),COALESCE(network_tx_mbps_streak_cycles,0),
               COALESCE(network_pps_policy_synced,0),COALESCE(network_pps_reported_threshold,0),
               COALESCE(engine_version,''),COALESCE(ram_streak_seconds,0),COALESCE(ram_streak_cycles,0),
               COALESCE(ram_current_kib,0),COALESCE(ram_rss_kib,0),COALESCE(ram_available_kib,0),
               COALESCE(ram_usable_kib,0),COALESCE(ram_rss_percent,0),
               COALESCE(ram_guest_used_percent,-1),COALESCE(ram_usable_percent,-1)
        FROM vm_abuse_state WHERE node=?
    """, (node,)).fetchall()
    keys = [
        "node","vm_uuid","last_seen","is_abuse","abuse_since","abuse_flags","severity",
        "network_rx_hit","network_tx_hit","cpu_streak_seconds","disk_streak_seconds",
        "rx_pps","tx_pps","rx_peak_pps","tx_peak_pps","seconds_over_rx_pps","seconds_over_tx_pps",
        "cpu_full_percent","cpu_core_percent","vcpu_current",
        "disk_read_bps","disk_write_bps","disk_read_iops","disk_write_iops",
        "network_rx_mbps_hit","network_tx_mbps_hit",
        "network_rx_mbps_streak_seconds","network_tx_mbps_streak_seconds",
        "rx_mbps","tx_mbps","policy_revision","policy_applied_at","last_eval_bucket",
        "cpu_streak_cycles","disk_streak_cycles",
        "network_rx_mbps_streak_cycles","network_tx_mbps_streak_cycles",
        "network_pps_policy_synced","network_pps_reported_threshold","engine_version",
        "ram_streak_seconds","ram_streak_cycles","ram_current_kib","ram_rss_kib",
        "ram_available_kib","ram_usable_kib","ram_rss_percent","ram_guest_used_percent","ram_usable_percent",
    ]
    return {str(row[1]): dict(zip(keys, row)) for row in rows}

_v48126_insert_event_base = _v4810_insert_abuse_event

def _v48126_insert_abuse_event(conn, event_type, state, event_time, flags=None, severity=None, cfg=None, detail=""):
    cfg = cfg or get_abuse_settings(conn)
    effective_flags = str((state or {}).get("abuse_flags") or "") if flags is None else str(flags or "")
    effective_severity = safe_float((state or {}).get("severity"), 0) if severity is None else safe_float(severity, 0)
    before_changes = conn.total_changes
    _v48126_insert_event_base(conn, event_type, state, event_time, flags, severity, cfg, detail)
    if conn.total_changes <= before_changes:
        return
    conn.execute(
        """UPDATE vm_abuse_events SET
             ram_streak_seconds=?,ram_current_kib=?,ram_rss_kib=?,ram_available_kib=?,ram_usable_kib=?,
             ram_rss_percent=?,ram_guest_used_percent=?,ram_usable_percent=?
           WHERE node=? AND vm_uuid=? AND event_time=? AND event_type=? AND abuse_flags=?""",
        (
            safe_int((state or {}).get("ram_streak_seconds"), 0),
            safe_int((state or {}).get("ram_current_kib"), 0),
            safe_int((state or {}).get("ram_rss_kib"), 0),
            safe_int((state or {}).get("ram_available_kib"), 0),
            safe_int((state or {}).get("ram_usable_kib"), 0),
            safe_float((state or {}).get("ram_rss_percent"), 0),
            safe_float((state or {}).get("ram_guest_used_percent"), -1),
            safe_float((state or {}).get("ram_usable_percent"), -1),
            str((state or {}).get("node") or ""), str((state or {}).get("vm_uuid") or ""),
            safe_int(event_time, now_ts()), str(event_type or "updated"), effective_flags,
        ),
    )
    _v48126_apply_incident_event(
        conn, event_type, state, event_time, effective_flags, effective_severity,
        safe_int((state or {}).get("policy_revision"), cfg.get("revision", 0)), ABUSE_ENGINE_VERSION,
    )

_v4810_insert_abuse_event = _v48126_insert_abuse_event
_insert_abuse_event = _v48126_insert_abuse_event

def _v48126_ram_metrics(current_kib, rss_kib, available_kib, unused_kib, usable_kib):
    current = max(0, safe_int(current_kib, 0))
    rss = max(0, safe_int(rss_kib, 0))
    available = max(0, safe_int(available_kib, 0))
    unused = max(0, safe_int(unused_kib, 0))
    usable = max(0, safe_int(usable_kib, 0))
    rss_pct = (rss * 100.0 / current) if current > 0 else 0.0
    guest_valid = bool(
        available > 0 and (usable > 0 or unused > 0) and usable <= available * 1.05
    )
    if guest_valid:
        guest_used_pct = max(0.0, min(100.0, (available - usable) * 100.0 / available))
        usable_pct = max(0.0, min(100.0, usable * 100.0 / available))
    else:
        guest_used_pct = -1.0
        usable_pct = -1.0
    return {
        "current_kib": current, "rss_kib": rss, "available_kib": available,
        "unused_kib": unused, "usable_kib": usable, "rss_percent": rss_pct,
        "guest_used_percent": guest_used_pct, "usable_percent": usable_pct,
        "guest_valid": guest_valid,
    }

# Authoritative v48.12.6 state writer. It preserves the exact cycle logic from
# cycles-v2 and adds a sustained RAM rule evaluated from the same accepted push.

# ---------- Policy Admin --------------------------------------------------
_v48126_abuse_settings_card_base = abuse_settings_admin_card

def abuse_settings_admin_card():
    cfg = get_abuse_settings()
    html = _v48126_abuse_settings_card_base()
    ram_card = f"""
          <div class="policy-card-v4810 policy-card-ram-v48126"><h4><span>RAM</span><small>OR logic</small></h4>
            <label class="enable-line"><input type="checkbox" name="ram_enabled" {'checked' if cfg['ram_enabled'] else ''}> Enable RAM abuse</label>
            <label>Host RSS % of assigned <small>0 disables</small><input type="number" name="ram_rss_percent" min="0" max="100" step="0.1" value="{cfg['ram_rss_percent']:.1f}"></label>
            <label>Guest Used % <small>requires balloon stats, 0 disables</small><input type="number" name="ram_guest_used_percent" min="0" max="100" step="0.1" value="{cfg['ram_guest_used_percent']:.1f}"></label>
            <label>Low Usable % <small>trigger when at or below, 0 disables</small><input type="number" name="ram_low_usable_percent" min="0" max="100" step="0.1" value="{cfg['ram_low_usable_percent']:.1f}"></label>
            <label>Consecutive minutes<input type="number" name="ram_required_minutes" min="5" max="1440" step="5" value="{cfg['ram_required_seconds']//60}"></label>
            <div class="policy-help-v4810">Any enabled non-zero RAM condition may match. The VM must match for {cfg['ram_required_cycles']*5} consecutive minute(s). Missing guest balloon data never triggers Guest Used or Low Usable.</div>
          </div>
"""
    marker = "        </div>\n        <div class=\"policy-actions-v4810\">"
    if marker in html:
        html = html.replace(marker, ram_card + marker, 1)
    html = html.replace(
        "CPU, AVG Mbps and Disk start counting on the next complete push.",
        "CPU, RAM, AVG Mbps and Disk start counting on the next complete push.",
    )
    return html

def admin_abuse_settings_v48126():
    deny = require_admin()
    if deny:
        return deny
    action = (request.form.get("action") or "save").strip().lower()
    if action not in {"save", "reset"}:
        return redirect(url_for("admin_abuse_page", err="Unsupported policy action"))
    if action == "reset":
        values = dict(ABUSE_SETTING_DEFAULTS)
    else:
        network_pps = max(1000.0, min(100000000.0, safe_float(request.form.get("network_pps"), 200000)))
        network_seconds = max(15, min(300, safe_int(request.form.get("network_required_seconds"), 270)))
        network_avg_mbps = max(0.0, min(1000000.0, safe_float(request.form.get("network_avg_mbps"), 800)))
        network_mbps_minutes = max(5, min(1440, safe_int(request.form.get("network_mbps_required_minutes"), 5)))
        cpu_percent = max(1.0, min(100.0, safe_float(request.form.get("cpu_full_percent"), 90)))
        cpu_minutes = max(5, min(1440, safe_int(request.form.get("cpu_required_minutes"), 30)))
        ram_rss = max(0.0, min(100.0, safe_float(request.form.get("ram_rss_percent"), 95)))
        ram_guest = max(0.0, min(100.0, safe_float(request.form.get("ram_guest_used_percent"), 95)))
        ram_low = max(0.0, min(100.0, safe_float(request.form.get("ram_low_usable_percent"), 5)))
        ram_minutes = max(5, min(1440, safe_int(request.form.get("ram_required_minutes"), 10)))
        disk_read = max(0.0, min(100000.0, safe_float(request.form.get("disk_read_mibps"), 0)))
        disk_write = max(0.0, min(100000.0, safe_float(request.form.get("disk_write_mibps"), 0)))
        disk_total = max(0.0, min(100000.0, safe_float(request.form.get("disk_mibps"), 200)))
        disk_iops = max(0.0, min(10000000.0, safe_float(request.form.get("disk_iops"), 5000)))
        disk_minutes = max(5, min(1440, safe_int(request.form.get("disk_required_minutes"), 15)))
        values = {
            "abuse_network_enabled": "1" if request.form.get("network_enabled") else "0",
            "abuse_network_pps": str(network_pps),
            "abuse_network_required_seconds": str(network_seconds),
            "abuse_network_mbps_enabled": "1" if request.form.get("network_mbps_enabled") else "0",
            "abuse_network_avg_mbps": str(network_avg_mbps),
            "abuse_network_mbps_required_seconds": str(network_mbps_minutes * 60),
            "abuse_cpu_enabled": "1" if request.form.get("cpu_enabled") else "0",
            "abuse_cpu_full_percent": str(cpu_percent),
            "abuse_cpu_required_seconds": str(cpu_minutes * 60),
            "abuse_ram_enabled": "1" if request.form.get("ram_enabled") else "0",
            "abuse_ram_rss_percent": str(ram_rss),
            "abuse_ram_guest_used_percent": str(ram_guest),
            "abuse_ram_low_usable_percent": str(ram_low),
            "abuse_ram_required_seconds": str(ram_minutes * 60),
            "abuse_disk_enabled": "1" if request.form.get("disk_enabled") else "0",
            "abuse_disk_read_bps": str(disk_read * 1024 * 1024),
            "abuse_disk_write_bps": str(disk_write * 1024 * 1024),
            "abuse_disk_bps": str(disk_total * 1024 * 1024),
            "abuse_disk_iops": str(disk_iops),
            "abuse_disk_required_seconds": str(disk_minutes * 60),
        }
    actor = dashboard_username() or get_admin_username() or "admin"
    try:
        cfg = _v4810_save_policy(values, actor, action)
    except Exception as exc:
        app.logger.exception("Could not save v48.12.6 abuse policy")
        return redirect(url_for("admin_abuse_page", err=str(exc)[:700]))
    log_account_event(
        "abuse_policy_saved", username=actor, realm="admin", role="admin",
        detail=(f"action={action};revision={cfg['revision']};ram={cfg['ram_enabled']};"
                f"ram_rss={cfg['ram_rss_percent']};ram_guest={cfg['ram_guest_used_percent']};"
                f"ram_low={cfg['ram_low_usable_percent']};ram_cycles={cfg['ram_required_cycles']}")[:1000],
    )
    return redirect(url_for(
        "admin_abuse_page",
        msg=(f"Policy v{cfg['revision']} saved. Current streaks were reset; history was preserved. "
             "CPU, RAM, AVG Mbps and Disk start on the next complete push. PPS waits for Agent synchronization."),
    ))

app.view_functions["admin_abuse_settings"] = admin_abuse_settings_v48126

def _public_abuse_policy(cfg):
    pps = f"RX or TX ≥ {cfg['network_pps']:,.0f} PPS for {cfg['network_required_seconds']}s" if cfg["network_enabled"] else "Disabled"
    mbps = f"RX or TX AVG ≥ {cfg['network_avg_mbps']:,.1f} Mbps for {cfg['network_mbps_required_cycles']*5} min" if cfg["network_mbps_enabled"] and cfg["network_avg_mbps"] > 0 else "Disabled"
    cpu = f"CPU Full ≥ {cfg['cpu_full_percent']:.1f}% for {cfg['cpu_required_cycles']*5} min" if cfg["cpu_enabled"] else "Disabled"
    ram_rules = []
    if cfg.get("ram_rss_percent", 0) > 0: ram_rules.append(f"RSS ≥ {cfg['ram_rss_percent']:.1f}%")
    if cfg.get("ram_guest_used_percent", 0) > 0: ram_rules.append(f"Guest Used ≥ {cfg['ram_guest_used_percent']:.1f}%")
    if cfg.get("ram_low_usable_percent", 0) > 0: ram_rules.append(f"Usable ≤ {cfg['ram_low_usable_percent']:.1f}%")
    ram = (" OR ".join(ram_rules) + f" for {cfg['ram_required_cycles']*5} min") if cfg.get("ram_effective_enabled") else "Disabled"
    disk = (_disk_policy_text(cfg) + f" for {cfg['disk_required_cycles']*5} min") if cfg["disk_effective_enabled"] else "Disabled"
    return f"""
    <div class="abuse-policy abuse-policy-v48126">
      <div><b>Network PPS {'ON' if cfg['network_enabled'] else 'OFF'}</b><small>{escape(pps)}</small></div>
      <div><b>Network AVG {'ON' if cfg['network_mbps_enabled'] and cfg['network_avg_mbps']>0 else 'OFF'}</b><small>{escape(mbps)}</small></div>
      <div><b>CPU {'ON' if cfg['cpu_enabled'] else 'OFF'}</b><small>{escape(cpu)}</small></div>
      <div><b>RAM {'ON' if cfg.get('ram_effective_enabled') else 'OFF'}</b><small>{escape(ram)}</small></div>
      <div><b>Disk {'ON' if cfg['disk_effective_enabled'] else 'OFF'}</b><small>{escape(disk)}</small></div>
    </div>"""

def _abuse_flag_labels(flags, cfg):
    values = set(_v4810_canonical_flags(flags))
    result = []
    if "NETWORK_RX_PPS" in values: result.append(f"RX PPS ≥ {cfg['network_pps']:,.0f}")
    if "NETWORK_TX_PPS" in values: result.append(f"TX PPS ≥ {cfg['network_pps']:,.0f}")
    if "NETWORK_RX_AVG_MBPS" in values: result.append(f"RX AVG ≥ {cfg['network_avg_mbps']:,.0f} Mbps")
    if "NETWORK_TX_AVG_MBPS" in values: result.append(f"TX AVG ≥ {cfg['network_avg_mbps']:,.0f} Mbps")
    if "CPU_SUSTAINED" in values: result.append(f"CPU Full ≥ {cfg['cpu_full_percent']:.1f}%")
    if "RAM_SUSTAINED" in values: result.append("RAM sustained")
    if "DISK_SUSTAINED" in values: result.append("Disk sustained")
    return result or ["Policy match"]

# ---------- Effective visibility -----------------------------------------
_get_top_vm_rows_v48126_base = get_top_vm_rows

def get_top_vm_rows(period, q="", sort_by="total", order="desc", scope="all", limit=100):
    requested_limit = max(10, min(1000, safe_int(limit, 100)))
    rows, selected_bucket, latest_bucket, _ = _get_top_vm_rows_v48126_base(
        period, q=q, sort_by=sort_by, order=order, scope=scope, limit=1000,
    )
    if rows:
        conn = db()
        try:
            rows = [row for row in rows if _v48126_is_visible(conn, row[0], row[1])]
        finally:
            conn.close()
    return rows[:requested_limit], selected_bucket, latest_bucket, requested_limit

# ---------- Abuse Viewer --------------------------------------------------
def _v48126_type_condition(alias, abuse_type):
    abuse_type = str(abuse_type or "all").strip().lower()
    if abuse_type == "network": return f"{alias}.abuse_flags LIKE '%NETWORK%'"
    if abuse_type == "cpu": return f"{alias}.abuse_flags LIKE '%CPU%'"
    if abuse_type == "ram": return f"{alias}.abuse_flags LIKE '%RAM%'"
    if abuse_type == "disk": return f"{alias}.abuse_flags LIKE '%DISK%'"
    return "1=1"

def _v48126_range_seconds(value):
    return {"1h":3600,"6h":21600,"24h":86400,"2d":172800,"7d":604800}.get(str(value or "7d"),604800)

def _v48126_filter_values():
    return {
        "q": (request.args.get("q") or "").strip(),
        "node": (request.args.get("node") or "").strip(),
        "type": (request.args.get("type") or "all").strip().lower(),
        "min_severity": max(0.0, min(1000.0, safe_float(request.args.get("min_severity"), 0))),
        "range": (request.args.get("range") or "7d").strip().lower(),
        "limit": max(25, min(500, safe_int(request.args.get("limit"), 100))),
        "page": max(1, safe_int(request.args.get("page"), 1)),
    }

def _v48126_filter_form(tab, values, nodes):
    node_options = '<option value="">All nodes</option>' + ''.join(
        f'<option value="{escape(node,quote=True)}" {"selected" if node==values["node"] else ""}>{escape(node)}</option>'
        for node in nodes
    )
    type_options = ''.join(
        f'<option value="{key}" {"selected" if key==values["type"] else ""}>{label}</option>'
        for key,label in (("all","All types"),("network","Network"),("cpu","CPU"),("ram","RAM"),("disk","Disk"))
    )
    range_html = ""
    if tab != "current":
        range_html = '<select name="range">' + ''.join(
            f'<option value="{key}" {"selected" if key==values["range"] else ""}>{label}</option>'
            for key,label in (("1h","Last 1h"),("6h","Last 6h"),("24h","Last 24h"),("2d","Last 2d"),("7d","Last 7d"))
        ) + '</select>'
    return f"""
    <form class="search compact-search abuse-filter-v48126" method="get" action="{url_for('vm_abuse_page')}">
      <input type="hidden" name="tab" value="{escape(tab,quote=True)}">
      <input name="q" value="{escape(values['q'],quote=True)}" placeholder="Search node / VM UUID / flag / detail">
      <select name="node">{node_options}</select><select name="type">{type_options}</select>
      <input type="number" name="min_severity" min="0" step="0.1" value="{values['min_severity'] or ''}" placeholder="Min severity">
      {range_html}<select name="limit">{''.join(f'<option value="{n}" {"selected" if n==values["limit"] else ""}>{n} / page</option>' for n in (50,100,200,500))}</select>
      <button type="submit">Filter</button><a class="clear" href="{url_for('vm_abuse_page',tab=tab)}">Clear</a>
    </form>"""

def _v48126_tabs(active):
    items = (("current","Current"),("incidents","Incidents"),("summary","Summary"),("events","Raw Events"))
    return '<div class="abuse-tabs abuse-tabs-v48126">' + ''.join(
        f'<a class="{"active" if active==key else ""}" href="{url_for("vm_abuse_page",tab=key)}">{label}</a>'
        for key,label in items
    ) + '</div>'

def _v48126_visible_nodes():
    conn = db()
    try:
        return [str(row[0]) for row in conn.execute("""
            SELECT DISTINCT a.node FROM vm_abuse_state a
            LEFT JOIN node_inventory ni ON ni.node=a.node
            WHERE a.last_seen>=? AND (ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))
            ORDER BY a.node COLLATE NOCASE
        """, (now_ts()-7*86400,)).fetchall()]
    finally:
        conn.close()

def _v48126_current_rows(values):
    cfg = get_abuse_settings()
    where = [
        "a.is_abuse=1", "a.last_seen>=?", "a.policy_revision=?", "a.engine_version=?",
        _v48126_visible_sql("ni","vi"), _v48126_type_condition("a", values["type"]), "a.severity>=?",
    ]
    params = [now_ts()-FAST_CURRENT_STALE_SECONDS, cfg["revision"], ABUSE_ENGINE_VERSION, values["min_severity"]]
    if values["node"]: where.append("a.node=?"); params.append(values["node"])
    if values["q"]:
        p=like_pattern(values["q"]); where.append("(a.node LIKE ? OR a.vm_uuid LIKE ? OR a.abuse_flags LIKE ?)"); params.extend([p,p,p])
    order_map = {
        "severity":"a.severity DESC","duration":"a.abuse_since ASC","node":"a.node COLLATE NOCASE",
        "last_seen":"a.last_seen DESC","cpu":"a.cpu_full_percent DESC","ram":"MAX(a.ram_guest_used_percent,a.ram_rss_percent) DESC",
        "network":"MAX(a.rx_pps,a.tx_pps) DESC","disk":"(a.disk_read_bps+a.disk_write_bps) DESC",
    }
    sort = (request.args.get("sort") or "severity").strip().lower()
    order_sql = order_map.get(sort, order_map["severity"])
    where_sql = " AND ".join(where)
    offset = (values["page"]-1)*values["limit"]
    conn=db()
    try:
        total=safe_int(conn.execute(f"""SELECT COUNT(*) FROM vm_abuse_state a
            LEFT JOIN node_inventory ni ON ni.node=a.node
            LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
            WHERE {where_sql}""",params).fetchone()[0],0)
        rows=conn.execute(f"""
            SELECT a.node,a.vm_uuid,a.abuse_since,a.last_seen,a.abuse_flags,a.severity,
                   a.rx_mbps,a.tx_mbps,a.rx_pps,a.tx_pps,a.rx_peak_pps,a.tx_peak_pps,
                   a.cpu_full_percent,a.cpu_core_percent,a.vcpu_current,
                   a.ram_rss_percent,a.ram_guest_used_percent,a.ram_usable_percent,a.ram_streak_seconds,
                   a.disk_read_bps,a.disk_write_bps,a.disk_read_iops,a.disk_write_iops,
                   COALESCE(b.primary_ipv4,'')
            FROM vm_abuse_state a
            LEFT JOIN node_inventory ni ON ni.node=a.node
            LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
            LEFT JOIN node_bridge_addresses_latest b ON b.node=a.node AND b.bridge=?
            WHERE {where_sql} ORDER BY {order_sql},a.node COLLATE NOCASE,a.vm_uuid LIMIT ? OFFSET ?
        """,[PUBLIC_BRIDGE]+params+[values["limit"],offset]).fetchall()
        counts={}
        for key in ("network","cpu","ram","disk"):
            counts[key]=safe_int(conn.execute(f"""SELECT COUNT(*) FROM vm_abuse_state a
              LEFT JOIN node_inventory ni ON ni.node=a.node
              LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
              WHERE a.is_abuse=1 AND a.last_seen>=? AND a.policy_revision=? AND a.engine_version=?
                AND {_v48126_visible_sql('ni','vi')} AND {_v48126_type_condition('a',key)}""",
              (now_ts()-FAST_CURRENT_STALE_SECONDS,cfg["revision"],ABUSE_ENGINE_VERSION)).fetchone()[0],0)
        return rows,total,counts
    finally: conn.close()

def _v48126_reason_badges(flags, cfg):
    return ''.join(f'<span class="metric-pill">{escape(label)}</span>' for label in _abuse_flag_labels(flags,cfg))

def _v48126_current_page(values, nodes):
    cfg=get_abuse_settings(); rows,total,counts=_v48126_current_rows(values)
    body=""
    for row in rows:
        node,uuid,started,last_seen,flags,severity,rxm,txm,rxp,txp,rxpk,txpk,cpu,core,vcpu,rss_pct,guest_pct,usable_pct,ram_streak,dr,dw,dri,dwi,ip=row
        href=url_for("node_page",node=node,period="1h",q=uuid)
        ram_main = f"Guest {guest_pct:.1f}%" if safe_float(guest_pct,-1)>=0 else f"RSS {safe_float(rss_pct,0):.1f}%"
        ram_sub = f"Usable {usable_pct:.1f}%" if safe_float(usable_pct,-1)>=0 else "Guest stats N/A"
        body += f"""<tr><td><div class="node-line"><a href="{escape(href,quote=True)}"><b>{escape(node)}</b></a>{f'<span>{escape(compact_ipv4(ip))}</span>' if ip else ''}</div><div class="uuid-line"><a class="mono" href="{escape(href,quote=True)}">{escape(uuid)}</a><button type="button" class="copy-btn" data-copy="{escape(uuid,quote=True)}">⧉</button></div></td>
        <td><div class="severity-line"><b>{safe_float(severity,0):.2f}x</b><span>{escape(_v48126_primary_type(flags))}</span></div><div class="abuse-reasons">{_v48126_reason_badges(flags,cfg)}</div></td>
        <td><div class="metric-pair"><div><span>RX AVG</span><b>{safe_float(rxm,0):.2f} Mbps</b><small>{fmt_pps_value(rxp)} PPS</small></div><div><span>TX AVG</span><b>{safe_float(txm,0):.2f} Mbps</b><small>{fmt_pps_value(txp)} PPS</small></div></div></td>
        <td><div class="metric-pair"><div><span>RX PEAK</span><b>{fmt_pps_value(rxpk)} PPS</b></div><div><span>TX PEAK</span><b>{fmt_pps_value(txpk)} PPS</b></div></div></td>
        <td><div class="metric-stack"><b>{safe_float(cpu,0):.1f}%</b><span>{safe_float(core,0):.1f}% core</span><small>{safe_int(vcpu,0)} vCPU</small></div></td>
        <td><div class="metric-stack"><b>{ram_main}</b><span>{ram_sub}</span><small>{_v48126_duration(ram_streak)} streak</small></div></td>
        <td><div class="metric-pair"><div><span>READ</span><b>{human_rate(dr)}</b><small>{safe_float(dri,0):,.0f} IOPS</small></div><div><span>WRITE</span><b>{human_rate(dw)}</b><small>{safe_float(dwi,0):,.0f} IOPS</small></div></div></td>
        <td><div class="timeline-cell"><b>{fmt_full(started) if started else '-'}</b><small>Started · {_v48126_duration(safe_int(last_seen,0)-safe_int(started,last_seen))}</small><span>{fmt_push(last_seen)}</span><small>Last push</small></div></td></tr>"""
    if not body: body='<tr><td colspan="8" class="empty">No visible VM matches the selected current-abuse filters</td></tr>'
    pages=max(1,math.ceil(total/values["limit"]))
    return f"""
    <div class="abuse-kpis-v48126"><div><span>Filtered</span><b>{total}</b></div><div><span>Network</span><b>{counts['network']}</b></div><div><span>CPU</span><b>{counts['cpu']}</b></div><div><span>RAM</span><b>{counts['ram']}</b></div><div><span>Disk</span><b>{counts['disk']}</b></div></div>
    <div class="card"><div class="section-head"><div><h3>Current VM Abuse</h3><p>Only visible VMs whose parent Node is also visible are shown.</p></div><div class="count-badges"><span>Page <b>{values['page']}/{pages}</b></span><span>Policy <b>v{cfg['revision']}</b></span></div></div>
    <div class="table-wrap"><table class="abuse-current-v48126"><thead><tr><th>NODE / VM</th><th>REASON / SEVERITY</th><th>NETWORK AVG</th><th>PPS PEAK</th><th>CPU</th><th>RAM</th><th>DISK</th><th>TIMELINE</th></tr></thead><tbody>{body}</tbody></table></div>{_v48126_pagination('current',values,total)}</div>"""

def _v48126_pagination(tab, values, total):
    pages=max(1,math.ceil(total/values["limit"])); page=min(values["page"],pages)
    if pages<=1: return ""
    def href(target):
        args=dict(values); args["tab"]=tab; args["page"]=target
        return url_for("vm_abuse_page",**{k:v for k,v in args.items() if v not in ("",0,"all")})
    prev=f'<a class="btn {"disabled" if page<=1 else ""}" href="{href(max(1,page-1))}">Previous</a>'
    nxt=f'<a class="btn {"disabled" if page>=pages else ""}" href="{href(min(pages,page+1))}">Next</a>'
    return f'<div class="pagination">{prev}<span>Page <b>{page}</b> of <b>{pages}</b></span>{nxt}</div>'

def _v48126_incident_query(values):
    cutoff=now_ts()-_v48126_range_seconds(values["range"])
    where=["(i.status='open' OR COALESCE(i.ended_at,i.last_event_at)>=?)",_v48126_visible_sql("ni","vi"),_v48126_type_condition("i",values["type"]),"i.max_severity>=?"]
    params=[cutoff,values["min_severity"]]
    if values["node"]: where.append("i.node=?");params.append(values["node"])
    if values["q"]:
        p=like_pattern(values["q"]);where.append("(i.node LIKE ? OR i.vm_uuid LIKE ? OR i.abuse_flags LIKE ?)");params.extend([p,p,p])
    where_sql=" AND ".join(where);offset=(values["page"]-1)*values["limit"]
    conn=db()
    try:
        total=safe_int(conn.execute(f"""SELECT COUNT(*) FROM vm_abuse_incidents i LEFT JOIN node_inventory ni ON ni.node=i.node LEFT JOIN vm_inventory vi ON vi.node=i.node AND vi.vm_uuid=i.vm_uuid WHERE {where_sql}""",params).fetchone()[0],0)
        rows=conn.execute(f"""SELECT i.id,i.node,i.vm_uuid,i.started_at,i.ended_at,i.duration_seconds,i.max_severity,i.weighted_score,i.abuse_flags,i.primary_type,i.event_count,i.last_event_at,i.status
          FROM vm_abuse_incidents i LEFT JOIN node_inventory ni ON ni.node=i.node LEFT JOIN vm_inventory vi ON vi.node=i.node AND vi.vm_uuid=i.vm_uuid
          WHERE {where_sql} ORDER BY CASE WHEN i.status='open' THEN 0 ELSE 1 END,i.started_at DESC,i.id DESC LIMIT ? OFFSET ?""",params+[values["limit"],offset]).fetchall()
        return rows,total
    finally:conn.close()

def _v48126_incidents_page(values,nodes):
    rows,total=_v48126_incident_query(values);now=now_ts();cfg=get_abuse_settings();body=""
    for row in rows:
        iid,node,uuid,started,ended,duration,maxsev,score,flags,ptype,event_count,last_event,status=row
        effective_duration=max(0,(now if status=='open' else safe_int(ended,started))-safe_int(started,0))
        effective_score=_v48126_incident_score(effective_duration,maxsev)
        href=url_for("node_page",node=node,period="1h",q=uuid)
        body+=f"""<tr><td><span class="status-chip {'status-ok' if status=='open' else ''}">{'ACTIVE' if status=='open' else 'RECOVERED'}</span></td><td><a href="{escape(href,quote=True)}"><b>{escape(node)}</b></a><small class="row-sub mono">{escape(uuid)}</small></td><td>{fmt_full(started)}</td><td>{fmt_full(ended) if ended else '<b>Active now</b>'}</td><td><b>{_v48126_duration(effective_duration)}</b></td><td><b>{safe_float(maxsev,0):.2f}x</b></td><td><b>{effective_score:.2f}</b><small class="row-sub">1 occurrence + severity × hours</small></td><td><div class="abuse-reasons">{_v48126_reason_badges(flags,cfg)}</div></td><td class="num">{safe_int(event_count,0)}</td></tr>"""
    if not body:body='<tr><td colspan="9" class="empty">No visible incident matches the selected filters</td></tr>'
    return f"""<div class="card"><div class="section-head"><div><h3>Abuse Incidents</h3><p>STARTED, UPDATED and RECOVERED events are paired into episodes with a real duration.</p></div><div class="count-badges"><span>Matched <b>{total}</b></span><span>Window <b>{escape(values['range'])}</b></span></div></div><div class="table-wrap"><table class="incident-table-v48126"><thead><tr><th>STATE</th><th>NODE / VM</th><th>START</th><th>END</th><th>DURATION</th><th>MAX SEVERITY</th><th>WEIGHTED SCORE</th><th>REASONS</th><th>EVENTS</th></tr></thead><tbody>{body}</tbody></table></div>{_v48126_pagination('incidents',values,total)}</div>"""

def _v48126_summary_data(values):
    cutoff=now_ts()-_v48126_range_seconds(values["range"])
    since=max(0,safe_int(values.get("since"),0))
    if since: cutoff=max(cutoff,since)
    now=now_ts()
    where=["(i.status='open' OR COALESCE(i.ended_at,i.last_event_at)>=?)",_v48126_visible_sql("ni","vi"),_v48126_type_condition("i",values["type"])]
    params=[cutoff]
    if values["node"]:where.append("i.node=?");params.append(values["node"])
    if values["q"]:
        p=like_pattern(values["q"]);where.append("(i.node LIKE ? OR i.vm_uuid LIKE ? OR i.abuse_flags LIKE ?)");params.extend([p,p,p])
    conn=db()
    try:
        rows=conn.execute(f"""SELECT i.node,i.vm_uuid,i.started_at,i.ended_at,i.max_severity,i.abuse_flags,i.primary_type,i.status,i.event_count
          FROM vm_abuse_incidents i LEFT JOIN node_inventory ni ON ni.node=i.node LEFT JOIN vm_inventory vi ON vi.node=i.node AND vi.vm_uuid=i.vm_uuid
          WHERE {' AND '.join(where)} ORDER BY i.started_at""",params).fetchall()
    finally:conn.close()
    by_vm={};by_day=Counter();by_type=Counter();active=0;total_duration=0
    for node,uuid,started,ended,maxsev,flags,ptype,status,event_count in rows:
        duration=max(0,(now if status=='open' else safe_int(ended,started))-safe_int(started,0));score=_v48126_incident_score(duration,maxsev)
        total_duration+=duration;active+=1 if status=='open' else 0;by_type[ptype]+=1
        day=datetime.fromtimestamp(safe_int(started,0),TZ).strftime('%m-%d');by_day[day]+=1
        key=(str(node),str(uuid));rec=by_vm.setdefault(key,{"node":str(node),"vm_uuid":str(uuid),"incidents":0,"active":0,"duration":0,"longest":0,"max_severity":0.0,"score":0.0,"last_seen":0,"types":Counter(),"flags":[]})
        rec["incidents"]+=1;rec["active"]+=1 if status=='open' else 0;rec["duration"]+=duration;rec["longest"]=max(rec["longest"],duration);rec["max_severity"]=max(rec["max_severity"],safe_float(maxsev,0));rec["score"]+=score;rec["last_seen"]=max(rec["last_seen"],safe_int(ended or started,0));rec["types"][ptype]+=1;rec["flags"]=_v48126_flag_union(rec["flags"],flags)
    ranking=sorted(by_vm.values(),key=lambda x:(x["score"],x["incidents"],x["duration"]),reverse=True)
    return rows,ranking,by_day,by_type,active,total_duration

def _v48126_summary_page(values,nodes):
    rows,ranking,by_day,by_type,active,total_duration=_v48126_summary_data(values)
    top=ranking[:20];max_score=max([x["score"] for x in top] or [1]);max_day=max(by_day.values() or [1]);cfg=get_abuse_settings()
    bars=''.join(f'<div class="hbar-row"><span title="{escape(r["node"])} / {escape(r["vm_uuid"])}">{escape(r["node"])} · {escape(r["vm_uuid"][:14])}</span><i><b style="width:{max(2,r["score"]*100/max_score):.1f}%"></b></i><strong>{r["score"]:.2f}</strong></div>' for r in top[:10]) or '<div class="empty">No incident data</div>'
    day_items=''.join(f'<div class="vbar"><b style="height:{max(4,count*100/max_day):.1f}%"></b><span>{escape(day)}</span><small>{count}</small></div>' for day,count in sorted(by_day.items())) or '<div class="empty">No incident data</div>'
    body=""
    for rank,r in enumerate(top,1):
        dominant=r["types"].most_common(1)[0][0] if r["types"] else "other"
        href=url_for("node_page",node=r["node"],period="1h",q=r["vm_uuid"])
        body+=f"""<tr><td class="rank-cell">{rank}</td><td><a href="{escape(href,quote=True)}"><b>{escape(r['node'])}</b></a><small class="row-sub mono">{escape(r['vm_uuid'])}</small></td><td><b>{r['incidents']}</b>{f'<small class="row-sub">{r["active"]} active</small>' if r['active'] else ''}</td><td><b>{_v48126_duration(r['duration'])}</b></td><td>{_v48126_duration(r['longest'])}</td><td>{r['max_severity']:.2f}x</td><td><b>{r['score']:.2f}</b></td><td><span class="type-chip type-{escape(dominant)}">{escape(dominant.upper())}</span></td><td>{fmt_full(r['last_seen'])}</td></tr>"""
    if not body:body='<tr><td colspan="9" class="empty">No visible VM incident summary in this window</td></tr>'
    top_name=(f"{ranking[0]['node']} / {ranking[0]['vm_uuid']}" if ranking else "-")
    return f"""
    <div class="abuse-kpis-v48126"><div><span>Incidents</span><b>{len(rows)}</b></div><div><span>Active now</span><b>{active}</b></div><div><span>Total duration</span><b>{_v48126_duration(total_duration)}</b></div><div class="wide"><span>Top abused VM</span><b title="{escape(top_name)}">{escape(top_name[:42])}</b></div></div>
    <div class="abuse-chart-grid-v48126"><div class="card chart-card"><div class="chart-title-v48126"><h3>Top VMs by weighted score</h3><small>Click to enlarge</small></div><div class="hbar-chart">{bars}</div></div><div class="card chart-card"><div class="chart-title-v48126"><h3>Incidents by day</h3><small>Click to enlarge</small></div><div class="vbar-chart">{day_items}</div></div></div>
    <div class="card"><div class="section-head"><div><h3>VM Abuse Ranking</h3><p>Score = one point per incident + duration hours × maximum severity.</p></div><div class="count-badges"><span>VM <b>{len(ranking)}</b></span><span>Window <b>{escape(values['range'])}</b></span></div></div><div class="table-wrap"><table class="summary-table-v48126"><thead><tr><th>#</th><th>NODE / VM</th><th>INCIDENTS</th><th>TOTAL DURATION</th><th>LONGEST</th><th>MAX SEVERITY</th><th>SCORE</th><th>PRIMARY</th><th>LAST SEEN</th></tr></thead><tbody>{body}</tbody></table></div></div>"""

def _v48126_events_page(values,nodes):
    cutoff=now_ts()-_v48126_range_seconds(values["range"])
    where=["e.event_time>=?",_v48126_visible_sql("ni","vi"),_v48126_type_condition("e",values["type"]),"e.severity>=?"];params=[cutoff,values["min_severity"]]
    if values["node"]:where.append("e.node=?");params.append(values["node"])
    if values["q"]:
        p=like_pattern(values["q"]);where.append("(e.node LIKE ? OR e.vm_uuid LIKE ? OR e.abuse_flags LIKE ? OR e.detail LIKE ?)");params.extend([p,p,p,p])
    offset=(values["page"]-1)*values["limit"]
    conn=db()
    try:
        total=safe_int(conn.execute(f"""SELECT COUNT(*) FROM vm_abuse_events e LEFT JOIN node_inventory ni ON ni.node=e.node LEFT JOIN vm_inventory vi ON vi.node=e.node AND vi.vm_uuid=e.vm_uuid WHERE {' AND '.join(where)}""",params).fetchone()[0],0)
        rows=conn.execute(f"""SELECT e.event_time,e.event_type,e.node,e.vm_uuid,e.abuse_flags,e.severity,e.detail,e.ram_rss_percent,e.ram_guest_used_percent,e.ram_usable_percent
          FROM vm_abuse_events e LEFT JOIN node_inventory ni ON ni.node=e.node LEFT JOIN vm_inventory vi ON vi.node=e.node AND vi.vm_uuid=e.vm_uuid
          WHERE {' AND '.join(where)} ORDER BY e.event_time DESC,e.id DESC LIMIT ? OFFSET ?""",params+[values["limit"],offset]).fetchall()
    finally:conn.close()
    cfg=get_abuse_settings();body=""
    for event_time,event_type,node,uuid,flags,severity,detail,rss,guest,usable in rows:
        ram="-"
        if "RAM" in str(flags): ram=(f"Guest {guest:.1f}%" if safe_float(guest,-1)>=0 else f"RSS {safe_float(rss,0):.1f}%")
        body+=f"""<tr><td>{fmt_full(event_time)}</td><td><span class="event-chip event-{escape(str(event_type))}">{escape(str(event_type).upper())}</span></td><td><b>{escape(node)}</b><small class="row-sub mono">{escape(uuid)}</small></td><td><div class="abuse-reasons">{_v48126_reason_badges(flags,cfg)}</div></td><td>{safe_float(severity,0):.2f}x</td><td>{escape(ram)}</td><td class="detail-cell">{escape(str(detail or ''))}</td></tr>"""
    if not body:body='<tr><td colspan="7" class="empty">No visible raw event matches the selected filters</td></tr>'
    return f"""<div class="card"><div class="section-head"><div><h3>Raw Abuse Events</h3><p>Read-only viewer. Deletion and cleanup remain in Admin → Abuse.</p></div><div class="count-badges"><span>Matched <b>{total}</b></span><span>Retention <b>7 days</b></span></div></div><div class="table-wrap"><table class="events-table-v48126"><thead><tr><th>TIME</th><th>EVENT</th><th>NODE / VM</th><th>REASON</th><th>SEVERITY</th><th>RAM</th><th>DETAIL</th></tr></thead><tbody>{body}</tbody></table></div>{_v48126_pagination('events',values,total)}</div>"""

def vm_abuse_page_v48126():
    tab=(request.args.get("tab") or "current").strip().lower()
    if tab=="history":tab="incidents"
    if tab not in {"current","incidents","summary","events"}:tab="current"
    values=_v48126_filter_values();nodes=_v48126_visible_nodes();cfg=get_abuse_settings()
    content=f"""<div class="card page-hero"><div><span class="eyebrow">ABUSE INTELLIGENCE</span><h2>VM Abuse</h2><p>Current state, paired incidents, weighted rankings and raw events in one read-only dashboard.</p></div><div class="hero-meta"><span>Policy <b>v{cfg['revision']}</b></span><span>Engine <b>{ABUSE_ENGINE_VERSION}</b></span><span>Retention <b>7 days</b></span></div></div><div class="card abuse-toolbar abuse-toolbar-v48126">{_v48126_tabs(tab)}{_v48126_filter_form(tab,values,nodes)}</div><details class="card policy-fold"><summary>Current policy</summary>{_public_abuse_policy(cfg)}</details>"""
    if tab=="current":content+=_v48126_current_page(values,nodes)
    elif tab=="incidents":content+=_v48126_incidents_page(values,nodes)
    elif tab=="summary":content+=_v48126_summary_page(values,nodes)
    else:content+=_v48126_events_page(values,nodes)
    return page("VM Abuse",content)

app.view_functions["vm_abuse_page"] = vm_abuse_page_v48126

# ---------- REST API visibility + RAM + incidents ------------------------
def _v48126_api_full_item(row):
    flags=_api_parse_flags(row[4])
    return {
        "node":str(row[0]),"vm_uuid":str(row[1]),"abuse_since":safe_int(row[2],0) or None,"last_seen":safe_int(row[3],0),
        "flags":flags,"primary_type":_v48126_primary_type(flags),"severity":round(safe_float(row[5],0),4),
        "network":{"rx_mbps":round(safe_float(row[6],0),4),"tx_mbps":round(safe_float(row[7],0),4),"rx_pps":round(safe_float(row[8],0),4),"tx_pps":round(safe_float(row[9],0),4),"rx_peak_pps":round(safe_float(row[10],0),4),"tx_peak_pps":round(safe_float(row[11],0),4)},
        "cpu":{"full_percent":round(safe_float(row[12],0),4),"core_percent":round(safe_float(row[13],0),4),"vcpu":safe_int(row[14],0),"streak_seconds":safe_int(row[31],0)},
        "ram":{"rss_percent":round(safe_float(row[15],0),4),"guest_used_percent":None if safe_float(row[16],-1)<0 else round(safe_float(row[16],0),4),"usable_percent":None if safe_float(row[17],-1)<0 else round(safe_float(row[17],0),4),"streak_seconds":safe_int(row[18],0)},
        "disk":{"read_bps":round(safe_float(row[19],0),4),"write_bps":round(safe_float(row[20],0),4),"read_iops":round(safe_float(row[21],0),4),"write_iops":round(safe_float(row[22],0),4),"streak_seconds":safe_int(row[32],0)},
        "sample":{"quality":str(row[25] or "UNKNOWN"),"count":safe_int(row[26],0),"expected":safe_int(row[27],0),"max_gap_seconds":round(safe_float(row[28],0),4)},
        "placement":{"bridge":str(row[29] or ""),"iface":str(row[30] or "")},
        "policy":{"revision":safe_int(row[23],0),"engine_version":str(row[24] or "")},
        "duration_seconds":max(0,safe_int(row[3],0)-safe_int(row[2],row[3])),
    }

def _v48126_api_abuse_query(single_uuid=None):
    cfg=get_abuse_settings();where=["a.is_abuse=1","a.last_seen>=?","a.policy_revision=?","a.engine_version=?",_v48126_visible_sql("ni","vi")];params=[now_ts()-FAST_CURRENT_STALE_SECONDS,cfg["revision"],ABUSE_ENGINE_VERSION]
    if single_uuid is not None:where.append("a.vm_uuid=?");params.append(str(single_uuid))
    node=(request.args.get("node") or "").strip();atype=(request.args.get("type") or "all").strip().lower();q=(request.args.get("q") or "").strip();minsev=max(0.0,safe_float(request.args.get("min_severity"),0))
    if node:where.append("a.node=?");params.append(node)
    if atype in {"network","cpu","ram","disk"}:where.append(_v48126_type_condition("a",atype))
    if q:p=like_pattern(q);where.append("(a.node LIKE ? OR a.vm_uuid LIKE ? OR a.abuse_flags LIKE ?)");params.extend([p,p,p])
    where.append("a.severity>=?");params.append(minsev)
    return where,params

_V48126_API_ABUSE_SELECT = """SELECT a.node,a.vm_uuid,a.abuse_since,a.last_seen,a.abuse_flags,a.severity,
 a.rx_mbps,a.tx_mbps,a.rx_pps,a.tx_pps,a.rx_peak_pps,a.tx_peak_pps,
 a.cpu_full_percent,a.cpu_core_percent,a.vcpu_current,
 a.ram_rss_percent,a.ram_guest_used_percent,a.ram_usable_percent,a.ram_streak_seconds,
 a.disk_read_bps,a.disk_write_bps,a.disk_read_iops,a.disk_write_iops,
 a.policy_revision,a.engine_version,
 COALESCE(c.sample_quality,'UNKNOWN'),COALESCE(c.sample_count,0),COALESCE(c.sample_expected,0),COALESCE(c.sample_max_gap,0),
 COALESCE(vi.last_bridge,''),COALESCE(vi.last_iface,''),
 COALESCE(a.cpu_streak_seconds,0),COALESCE(a.disk_streak_seconds,0)
 FROM vm_abuse_state a
 LEFT JOIN vm_current_fast c ON c.node=a.node AND c.vm_uuid=a.vm_uuid
 LEFT JOIN node_inventory ni ON ni.node=a.node
 LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid"""

def _v48126_api_abuse_vms_impl():
    where,params=_v48126_api_abuse_query();limit,offset=_api_limit_offset(200);view=(request.args.get("view") or "summary").strip().lower()
    if view not in {"summary","full"}:return _api_error("invalid_view","view must be summary or full.",400)
    conn=db()
    try:
        where_sql=" AND ".join(where);total=safe_int(conn.execute(f"""SELECT COUNT(*) FROM vm_abuse_state a LEFT JOIN node_inventory ni ON ni.node=a.node LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid WHERE {where_sql}""",params).fetchone()[0],0)
        rows=conn.execute(f"{_V48126_API_ABUSE_SELECT} WHERE {where_sql} ORDER BY a.severity DESC,a.last_seen DESC LIMIT ? OFFSET ?",params+[limit,offset]).fetchall()
    finally:conn.close()
    full=[_v48126_api_full_item(r) for r in rows]
    if view=="full":
        data=full
    else:
        data=[]
        for item in full:
            compact={k:v for k,v in item.items() if k in {"node","vm_uuid","abuse_since","last_seen","flags","primary_type","severity","duration_seconds","placement"}}
            compact["summary"] = ", ".join(_abuse_flag_labels(item.get("flags") or [], get_abuse_settings()))
            compact["sample"] = {"quality": (item.get("sample") or {}).get("quality", "UNKNOWN")}
            primary=item.get("primary_type")
            if primary in {"network","cpu","ram","disk"}:
                compact[primary]=item[primary]
            data.append(compact)
    return _api_response({"data":data,"meta":{"count":len(data),"total":total,"limit":limit,"offset":offset,"view":view}})

def _v48126_api_abuse_vm_impl(vm_uuid):
    where,params=_v48126_api_abuse_query(vm_uuid);conn=db()
    try:
        rows=conn.execute(f"{_V48126_API_ABUSE_SELECT} WHERE {' AND '.join(where)} ORDER BY a.last_seen DESC LIMIT 2",params).fetchall()
    finally:conn.close()
    if not rows:return _api_error("abuse_vm_not_found","No visible active abuse record was found for this VM.",404)
    if len(rows)>1 and not (request.args.get("node") or "").strip():return _api_error("ambiguous_vm_location","Provide ?node=<node>.",409)
    return _api_response({"data":_v48126_api_full_item(rows[0])})

app.view_functions["api_v1_abuse_vms"] = require_api_scopes("abuse:read")(_v48126_api_abuse_vms_impl)
app.view_functions["api_v1_abuse_vm"] = require_api_scopes("abuse:read")(_v48126_api_abuse_vm_impl)

def _v48126_api_abuse_summary_impl():
    where,params=_v48126_api_abuse_query();conn=db()
    try:
        rows=conn.execute(f"""SELECT a.node,a.abuse_flags,a.severity,a.abuse_since,a.last_seen FROM vm_abuse_state a LEFT JOIN node_inventory ni ON ni.node=a.node LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid WHERE {' AND '.join(where)}""",params).fetchall()
    finally:conn.close()
    by_type=Counter();by_flag=Counter();by_node=defaultdict(lambda:{"count":0,"max_severity":0.0});oldest=None;latest=None;maxsev=0.0
    for node,flags,severity,since,last in rows:
        parsed=_api_parse_flags(flags);by_type[_v48126_primary_type(parsed)]+=1
        for flag in parsed:by_flag[flag]+=1
        by_node[str(node)]["count"]+=1;by_node[str(node)]["max_severity"]=max(by_node[str(node)]["max_severity"],safe_float(severity,0));oldest=safe_int(since,0) if oldest is None else min(oldest,safe_int(since,oldest));latest=max(latest or 0,safe_int(last,0));maxsev=max(maxsev,safe_float(severity,0))
    nodes=sorted(({"node":k,**v} for k,v in by_node.items()),key=lambda x:(x["count"],x["max_severity"]),reverse=True)[:20]
    return _api_response({"data":{"current_abuse":len(rows),"by_type":dict(by_type),"by_flag":dict(by_flag),"nodes":nodes,"oldest_abuse_since":oldest,"latest_seen":latest,"max_severity":round(maxsev,4)}})

app.view_functions["api_v1_abuse_summary"] = require_api_scopes("abuse:read")(_v48126_api_abuse_summary_impl)

def api_v1_abuse_incidents_v48126():
    limit,offset=_api_limit_offset(200)
    cutoff=now_ts()-_v48126_range_seconds(request.args.get("range") or "7d")
    since=max(0,safe_int(request.args.get("since"),0))
    if since: cutoff=max(cutoff,since)
    where=["(i.status='open' OR COALESCE(i.ended_at,i.last_event_at)>=?)",_v48126_visible_sql("ni","vi")];params=[cutoff]
    node=(request.args.get("node") or "").strip();uuid=(request.args.get("vm_uuid") or "").strip();atype=(request.args.get("type") or "all").strip().lower();q=(request.args.get("q") or "").strip();status=(request.args.get("status") or "all").strip().lower();minsev=max(0.0,safe_float(request.args.get("min_severity"),0))
    if node:where.append("i.node=?");params.append(node)
    if uuid:where.append("i.vm_uuid=?");params.append(uuid)
    if q:
        pattern=like_pattern(q);where.append("(i.node LIKE ? OR i.vm_uuid LIKE ? OR i.abuse_flags LIKE ?)");params.extend([pattern,pattern,pattern])
    if atype in {"network","cpu","ram","disk"}:where.append(_v48126_type_condition("i",atype))
    if status in {"open","closed"}:where.append("i.status=?");params.append(status)
    where.append("i.max_severity>=?");params.append(minsev)
    conn=db();now=now_ts()
    try:
        total=safe_int(conn.execute(f"""SELECT COUNT(*) FROM vm_abuse_incidents i LEFT JOIN node_inventory ni ON ni.node=i.node LEFT JOIN vm_inventory vi ON vi.node=i.node AND vi.vm_uuid=i.vm_uuid WHERE {' AND '.join(where)}""",params).fetchone()[0],0)
        rows=conn.execute(f"""SELECT i.id,i.node,i.vm_uuid,i.started_at,i.ended_at,i.max_severity,i.abuse_flags,i.primary_type,i.event_count,i.status FROM vm_abuse_incidents i LEFT JOIN node_inventory ni ON ni.node=i.node LEFT JOIN vm_inventory vi ON vi.node=i.node AND vi.vm_uuid=i.vm_uuid WHERE {' AND '.join(where)} ORDER BY i.started_at DESC LIMIT ? OFFSET ?""",params+[limit,offset]).fetchall()
    finally:conn.close()
    data=[]
    for iid,node,uuid,started,ended,maxsev,flags,ptype,event_count,status in rows:
        duration=max(0,(now if status=='open' else safe_int(ended,started))-safe_int(started,0));data.append({"incident_id":safe_int(iid,0),"node":str(node),"vm_uuid":str(uuid),"started_at":safe_int(started,0),"ended_at":safe_int(ended,0) or None,"duration_seconds":duration,"status":str(status),"max_severity":round(safe_float(maxsev,0),4),"weighted_score":_v48126_incident_score(duration,maxsev),"flags":_api_parse_flags(flags),"primary_type":str(ptype),"event_count":safe_int(event_count,0)})
    return _api_response({"data":data,"meta":{"count":len(data),"total":total,"limit":limit,"offset":offset}})

def api_v1_abuse_rankings_v48126():
    values={"q":(request.args.get("q") or "").strip(),"node":(request.args.get("node") or "").strip(),"type":(request.args.get("type") or "all").strip().lower(),"range":(request.args.get("range") or "7d").strip().lower(),"since":max(0,safe_int(request.args.get("since"),0))}
    values.update({"min_severity":0,"limit":500,"page":1});_rows,ranking,_days,_types,active,total_duration=_v48126_summary_data(values);limit=max(1,min(500,safe_int(request.args.get("limit"),100)))
    return _api_response({"data":[{"node":r["node"],"vm_uuid":r["vm_uuid"],"incidents":r["incidents"],"active_incidents":r["active"],"total_duration_seconds":r["duration"],"longest_duration_seconds":r["longest"],"max_severity":round(r["max_severity"],4),"weighted_score":round(r["score"],4),"primary_type":r["types"].most_common(1)[0][0] if r["types"] else "other","last_seen":r["last_seen"]} for r in ranking[:limit]],"meta":{"count":min(limit,len(ranking)),"total":len(ranking),"active_incidents":active,"total_duration_seconds":total_duration}})

app.add_url_rule("/api/v1/abuse/incidents", "api_v1_abuse_incidents_v48126", require_api_scopes("abuse_events:read")(api_v1_abuse_incidents_v48126), methods=["GET"])
app.add_url_rule("/api/v1/abuse/rankings", "api_v1_abuse_rankings_v48126", require_api_scopes("abuse_events:read")(api_v1_abuse_rankings_v48126), methods=["GET"])

# Filter legacy list APIs as a final safety net. Hidden parent Nodes are never
# returned by monitoring APIs, even if the child VM inventory row is active.
def _v48126_wrap_api_visibility(endpoint, mode):
    base=app.view_functions.get(endpoint)
    if base is None:return
    def wrapped(*args,**kwargs):
        response=base(*args,**kwargs)
        if not isinstance(response,Response) or response.status_code>=400:return response
        payload=response.get_json(silent=True)
        if not isinstance(payload,dict) or "data" not in payload:return response
        conn=db()
        try:
            data=payload.get("data")
            if isinstance(data,list):
                filtered=[]
                for item in data:
                    if not isinstance(item,dict):continue
                    node=item.get("node") or item.get("current_node")
                    uuid=item.get("vm_uuid")
                    visible=_v48126_is_visible(conn,node,uuid if mode!="node" else None)
                    if visible:filtered.append(item)
                payload["data"]=filtered
                if isinstance(payload.get("meta"),dict):payload["meta"]["count"]=len(filtered);payload["meta"]["visible_only"]=True
            elif isinstance(data,dict):
                node=data.get("node") or data.get("current_node");uuid=data.get("vm_uuid")
                if node and not _v48126_is_visible(conn,node,uuid if mode!="node" else None):
                    return _api_error("not_found","The requested object is hidden by inventory visibility.",404)
        finally:conn.close()
        response.set_data(json.dumps(payload,separators=(",",":"),default=str));response.headers["Content-Type"]="application/json"
        return response
    wrapped.__name__=f"{getattr(base,'__name__',endpoint)}_v48126_visible"
    app.view_functions[endpoint]=wrapped

for _endpoint,_mode in (
    ("api_v1_vms","vm"),("api_v1_vm_current","vm"),("api_v1_nodes","node"),
    ("api_v1_bandwidth_vms","vm"),("api_v1_bandwidth_vm","vm"),
):
    _v48126_wrap_api_visibility(_endpoint,_mode)

# ---------- Retention for incident summaries -----------------------------
_v48126_run_retention_base = run_retention

def run_retention(dry_run=False):
    stats=_v48126_run_retention_base(dry_run=dry_run);cutoff=now_ts()-HISTORY_RETENTION_DAYS*86400;conn=db()
    try:
        if dry_run:
            count=safe_int(conn.execute("SELECT COUNT(*) FROM vm_abuse_incidents WHERE status='closed' AND ended_at<?",(cutoff,)).fetchone()[0],0)
        else:
            count=_delete_in_batches(conn,"vm_abuse_incidents","status='closed' AND ended_at<?",(cutoff,));conn.execute("PRAGMA optimize");conn.commit()
        stats.setdefault("deleted",{})["vm_abuse_incidents"]=safe_int(count,0);stats["total_deleted"]=sum(safe_int(v,0) for v in stats.get("deleted",{}).values());return stats
    finally:conn.close()

# ---------- UI: chart fullscreen, select-all, cleanup alignment -----------
V48126_UI_CSS = r"""
<style id="v48126-abuse-intelligence-ui">
.abuse-policy-v48126{grid-template-columns:repeat(5,minmax(190px,1fr))!important}.policy-v4810{grid-template-columns:repeat(4,minmax(220px,1fr))!important}
.abuse-toolbar-v48126{display:grid!important;grid-template-columns:auto minmax(0,1fr);align-items:center}.abuse-tabs-v48126{white-space:nowrap}.abuse-filter-v48126{justify-content:flex-end!important}.abuse-filter-v48126 input[name=q]{min-width:280px}
.abuse-kpis-v48126{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr));gap:10px;margin-bottom:16px}.abuse-kpis-v48126>div{background:var(--panel,#fff);border:1px solid var(--line,#e5eaf1);border-radius:13px;padding:14px;box-shadow:var(--shadow)}.abuse-kpis-v48126 span,.abuse-kpis-v48126 b{display:block}.abuse-kpis-v48126 span{font-size:11px;color:var(--muted,#667085)}.abuse-kpis-v48126 b{font-size:22px;margin-top:5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.abuse-kpis-v48126 .wide{grid-column:span 2}
.abuse-current-v48126{min-width:1740px;table-layout:fixed}.abuse-current-v48126 th:nth-child(1){width:285px}.abuse-current-v48126 th:nth-child(2){width:270px}.abuse-current-v48126 th:nth-child(3),.abuse-current-v48126 th:nth-child(4){width:210px}.abuse-current-v48126 th:nth-child(5){width:125px}.abuse-current-v48126 th:nth-child(6){width:165px}.abuse-current-v48126 th:nth-child(7){width:220px}.abuse-current-v48126 th:nth-child(8){width:175px}
.incident-table-v48126{min-width:1420px}.events-table-v48126{min-width:1350px}.summary-table-v48126{min-width:1200px}.row-sub{display:block;color:var(--muted,#667085);font-size:10px;margin-top:4px}.detail-cell{max-width:420px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.type-chip,.event-chip{display:inline-flex;padding:4px 7px;border-radius:999px;font-size:9px;font-weight:900}.type-network{background:#dbeafe;color:#1d4ed8}.type-cpu{background:#fee2e2;color:#b91c1c}.type-ram{background:#ede9fe;color:#6d28d9}.type-disk{background:#ffedd5;color:#c2410c}.event-started{background:#fee2e2;color:#b91c1c}.event-updated{background:#fef3c7;color:#92400e}.event-recovered{background:#dcfce7;color:#166534}
.abuse-chart-grid-v48126{display:grid;grid-template-columns:1.2fr 1fr;gap:16px}.chart-title-v48126{display:flex;align-items:center;justify-content:space-between;gap:10px}.chart-title-v48126 h3{margin:0}.chart-title-v48126 small{color:var(--muted,#667085)}.hbar-chart{display:grid;gap:8px;margin-top:16px}.hbar-row{display:grid;grid-template-columns:minmax(150px,230px) 1fr 58px;gap:10px;align-items:center;font-size:11px}.hbar-row>span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.hbar-row>i{display:block;height:10px;background:#e5e7eb;border-radius:999px;overflow:hidden}.hbar-row>i>b{display:block;height:100%;background:linear-gradient(90deg,#2563eb,#7c3aed);border-radius:999px}.hbar-row>strong{text-align:right}.vbar-chart{height:260px;display:flex;align-items:end;gap:8px;padding:18px 4px 0}.vbar{flex:1;min-width:34px;height:100%;display:grid;grid-template-rows:1fr auto auto;gap:4px;align-items:end;text-align:center}.vbar>b{display:block;width:72%;margin:auto;background:linear-gradient(180deg,#7c3aed,#2563eb);border-radius:7px 7px 2px 2px}.vbar>span,.vbar>small{font-size:9px;color:var(--muted,#667085)}
.chart-card{position:relative;cursor:zoom-in}.bw-chart-expand{position:absolute;right:14px;top:14px;z-index:4;width:32px;height:32px;min-height:32px!important;padding:0!important;border-radius:9px!important;background:rgba(255,255,255,.92)!important;color:#1d4ed8!important}.bw-chart-modal{position:fixed;inset:0;z-index:9999;background:rgba(3,10,22,.82);display:none;align-items:center;justify-content:center;padding:28px}.bw-chart-modal.open{display:flex}.bw-chart-dialog{width:min(1500px,96vw);max-height:94vh;overflow:auto;background:var(--panel,#fff);border:1px solid var(--line,#e5eaf1);border-radius:18px;padding:20px;box-shadow:0 30px 80px rgba(0,0,0,.4)}.bw-chart-modal-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.bw-chart-modal-body .chart-card{box-shadow:none!important;border:0!important;margin:0!important;cursor:default}.bw-chart-modal-body svg{width:100%!important;height:auto!important;min-height:480px}.bw-chart-close{font-size:20px!important;width:38px;height:38px;padding:0!important}
.bw-select-tools{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:8px 0;padding:8px 10px;border:1px solid var(--line,#e5eaf1);border-radius:10px;background:var(--panel-soft,#f8fafc)}.bw-select-tools span{font-size:11px;color:var(--muted,#667085)}
.admin-abuse-danger>.bulk-bar:first-child label{display:flex!important;align-items:center!important;gap:8px!important}.admin-abuse-danger input[type=checkbox]{width:16px!important;height:16px!important;min-height:0!important;padding:0!important;flex:0 0 auto}.admin-abuse-danger>.bulk-bar{grid-template-rows:auto 42px!important;min-height:132px}.admin-abuse-danger>.bulk-bar label{min-height:60px}
html[data-theme=dark] .hbar-row>i{background:#26374f}.bw-chart-modal{background:rgba(0,0,0,.86)}html[data-theme=dark] .bw-chart-expand{background:#162941!important;color:#8bc1ff!important}
@media(max-width:1250px){.policy-v4810{grid-template-columns:repeat(2,minmax(220px,1fr))!important}.abuse-policy-v48126{grid-template-columns:repeat(2,minmax(190px,1fr))!important}.abuse-toolbar-v48126{grid-template-columns:1fr}.abuse-filter-v48126{justify-content:flex-start!important}.abuse-chart-grid-v48126{grid-template-columns:1fr}}
@media(max-width:760px){.policy-v4810,.abuse-policy-v48126{grid-template-columns:1fr!important}.abuse-kpis-v48126{grid-template-columns:repeat(2,minmax(120px,1fr))}.abuse-kpis-v48126 .wide{grid-column:span 2}.abuse-filter-v48126 input[name=q]{min-width:100%;width:100%}.bw-chart-modal{padding:8px}.bw-chart-dialog{width:100%;max-height:98vh;padding:12px}}
</style>
"""

V48126_UI_JS = r"""
<script id="v48126-interactions">
(function(){
  function ensureModal(){
    var modal=document.getElementById('bw-chart-modal'); if(modal) return modal;
    modal=document.createElement('div'); modal.id='bw-chart-modal'; modal.className='bw-chart-modal';
    modal.innerHTML='<div class="bw-chart-dialog" role="dialog" aria-modal="true"><div class="bw-chart-modal-head"><b>Expanded chart</b><button type="button" class="bw-chart-close" aria-label="Close">×</button></div><div class="bw-chart-modal-body"></div></div>';
    document.body.appendChild(modal);
    function close(){modal.classList.remove('open');document.body.style.overflow='';modal.querySelector('.bw-chart-modal-body').innerHTML='';}
    modal.querySelector('.bw-chart-close').addEventListener('click',close);
    modal.addEventListener('click',function(e){if(e.target===modal)close();});
    document.addEventListener('keydown',function(e){if(e.key==='Escape'&&modal.classList.contains('open'))close();});
    return modal;
  }
  function decorateCharts(root){
    (root||document).querySelectorAll('.chart-card').forEach(function(card){
      if(card.dataset.bwExpandable==='1'||card.closest('.bw-chart-modal-body'))return; card.dataset.bwExpandable='1';
      var btn=document.createElement('button');btn.type='button';btn.className='bw-chart-expand';btn.title='Expand chart';btn.textContent='⤢';card.appendChild(btn);
      function open(e){if(e)e.stopPropagation();var modal=ensureModal(),body=modal.querySelector('.bw-chart-modal-body'),clone=card.cloneNode(true);clone.querySelectorAll('.bw-chart-expand').forEach(function(x){x.remove();});body.innerHTML='';body.appendChild(clone);modal.classList.add('open');document.body.style.overflow='hidden';}
      btn.addEventListener('click',open);card.addEventListener('dblclick',open);
    });
  }
  function decorateSelections(root){
    (root||document).querySelectorAll('form').forEach(function(form){
      if(form.dataset.bwSelectTools==='1')return;
      var boxes=form.querySelectorAll('input[type=checkbox][name="vms"],input[type=checkbox][name="nodes"]');if(!boxes.length)return;
      form.dataset.bwSelectTools='1';var tools=document.createElement('div');tools.className='bw-select-tools';tools.innerHTML='<button type="button" data-a="all">Select all on this page</button><button type="button" data-a="none">Clear selection</button><span>0 selected</span>';
      var anchor=form.querySelector('.bulk-bar,.table-wrap');form.insertBefore(tools,anchor||form.firstChild);var count=tools.querySelector('span');
      function update(){var n=form.querySelectorAll('input[type=checkbox][name="vms"]:checked,input[type=checkbox][name="nodes"]:checked').length;count.textContent=n+' selected';}
      tools.addEventListener('click',function(e){var a=e.target&&e.target.dataset&&e.target.dataset.a;if(!a)return;boxes.forEach(function(box){box.checked=a==='all';});update();});boxes.forEach(function(box){box.addEventListener('change',update);});update();
    });
  }
  function init(root){decorateCharts(root);decorateSelections(root);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',function(){init(document);});else init(document);
  new MutationObserver(function(records){records.forEach(function(r){r.addedNodes.forEach(function(n){if(n.nodeType===1)init(n);});});}).observe(document.documentElement,{childList:true,subtree:true});
})();
</script>
"""

_page_v48126_base = page

def page(title, content):
    response = _page_v48126_base(title, content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace("</head>", V48126_UI_CSS + "</head>", 1)
        html = html.replace("</body>", V48126_UI_JS + "</body>", 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.12.6 UI layer")
    return response

