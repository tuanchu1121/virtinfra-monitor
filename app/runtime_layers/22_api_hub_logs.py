# v48.12.0 Abuse-focused API Hub, request logs and full API cleanup
# ---------------------------------------------------------------------------
# This layer intentionally keeps the v48.11.0 routes backward compatible while
# making the Admin experience abuse-first and operationally complete.
# ---------------------------------------------------------------------------

V48120_VERSION = "48.12.0"
API_ACCESS_LOG_RETENTION_DAYS = min(7, max(1, int(os.environ.get("BW_API_ACCESS_LOG_RETENTION_DAYS", "7"))))
API_ACCESS_LOGS_ENABLED = os.environ.get("BW_API_ACCESS_LOGS", "1") == "1"
API_PRIMARY_SCOPES = {
    "abuse:read": "Read the current VM abuse list and one active abuse VM",
    "abuse_events:read": "Read persistent VM abuse history / event logs",
}
_api_access_retention_lock = threading.Lock()
_api_access_retention_last = 0


def _v48120_ensure_schema():
    conn = db()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS api_access_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_time INTEGER NOT NULL,
            request_id TEXT NOT NULL DEFAULT '',
            key_id TEXT NOT NULL DEFAULT '',
            key_name TEXT NOT NULL DEFAULT '',
            source_ip TEXT NOT NULL DEFAULT '',
            method TEXT NOT NULL DEFAULT '',
            path TEXT NOT NULL DEFAULT '',
            query_string TEXT NOT NULL DEFAULT '',
            endpoint TEXT NOT NULL DEFAULT '',
            status_code INTEGER NOT NULL DEFAULT 0,
            duration_ms REAL NOT NULL DEFAULT 0,
            response_bytes INTEGER NOT NULL DEFAULT 0,
            user_agent TEXT NOT NULL DEFAULT '',
            error_code TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_api_access_logs_time
            ON api_access_logs(request_time DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_api_access_logs_key_time
            ON api_access_logs(key_id, request_time DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_api_access_logs_status_time
            ON api_access_logs(status_code, request_time DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_api_access_logs_path_time
            ON api_access_logs(path, request_time DESC, id DESC);
        """)
        conn.commit()
    finally:
        conn.close()


try:
    _v48120_ensure_schema()
except Exception:
    app.logger.exception("Could not initialize v48.12.0 API access-log schema")


# Capture authenticated API calls. Authentication failures for known keys remain
# visible in Management Events, while normal requests appear in Request Logs.
_v48120_api_authenticate_base = _api_authenticate


def _api_authenticate(required_scopes=()):
    g.api_started_perf = time.perf_counter()
    key, error = _v48120_api_authenticate_base(required_scopes)
    if key:
        g.api_access_log_key_id = str(key.get("key_id") or "")
        g.api_access_log_key_name = str(key.get("name") or "")
        g.api_access_log_source_ip = str(getattr(g, "api_client_ip", "") or api_client_ip())
    return key, error


def _v48120_prune_api_access_logs_if_due(conn):
    global _api_access_retention_last
    now = now_ts()
    with _api_access_retention_lock:
        if now - _api_access_retention_last < 3600:
            return 0
        _api_access_retention_last = now
    cutoff = now - API_ACCESS_LOG_RETENTION_DAYS * 86400
    cur = conn.execute("DELETE FROM api_access_logs WHERE request_time<?", (cutoff,))
    return max(0, safe_int(cur.rowcount, 0))


@app.after_request
def _v48120_store_api_request_log(response):
    if not API_ACCESS_LOGS_ENABLED or not request.path.startswith("/api/v1/"):
        return response
    key_id = str(getattr(g, "api_access_log_key_id", "") or "")
    if not key_id:
        return response
    try:
        started = float(getattr(g, "api_started_perf", time.perf_counter()))
        duration_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        error_code = ""
        try:
            payload = response.get_json(silent=True)
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                error_code = str(payload["error"].get("code") or "")[:80]
        except Exception:
            error_code = ""
        conn = db()
        try:
            conn.execute(
                """INSERT INTO api_access_logs(
                    request_time,request_id,key_id,key_name,source_ip,method,path,query_string,
                    endpoint,status_code,duration_ms,response_bytes,user_agent,error_code
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    now_ts(), str(getattr(g, "api_request_id", "") or "")[:64], key_id,
                    str(getattr(g, "api_access_log_key_name", "") or "")[:120],
                    str(getattr(g, "api_access_log_source_ip", "") or "")[:128],
                    str(request.method or "")[:12], str(request.path or "")[:500],
                    str(request.query_string.decode("utf-8", "replace") if request.query_string else "")[:1000],
                    str(request.endpoint or "")[:160], safe_int(response.status_code, 0),
                    round(duration_ms, 3), safe_int(response.calculate_content_length(), 0),
                    str(request.headers.get("User-Agent") or "")[:500], error_code,
                ),
            )
            _v48120_prune_api_access_logs_if_due(conn)
            conn.commit()
        finally:
            conn.close()
    except Exception:
        # API logging must never break the API response.
        app.logger.exception("Could not persist API request log")
    return response


def _v48120_reset_sequences(conn, tables):
    has_sequence = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
    ).fetchone()
    if not has_sequence:
        return
    for table in tables:
        conn.execute("DELETE FROM sqlite_sequence WHERE name=?", (table,))


def clear_api_logs(kind="all"):
    """Delete API request logs and/or API management events, preserving keys."""
    kind = str(kind or "all").strip().lower()
    if kind not in {"access", "events", "all"}:
        raise ValueError("kind must be access, events or all")
    tables = []
    if kind in {"access", "all"}:
        tables.append("api_access_logs")
    if kind in {"events", "all"}:
        tables.append("api_key_events")
    conn = db()
    result = {"kind": kind, "tables": {}, "total_deleted": 0}
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for table in tables:
            if table not in existing:
                result["tables"][table] = 0
                continue
            count = safe_int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
            conn.execute(f"DELETE FROM {table}")
            result["tables"][table] = count
            result["total_deleted"] += count
        _v48120_reset_sequences(conn, tables)
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def clear_all_api_data():
    """Permanently delete every external API key and all API-owned logs."""
    conn = db()
    tables = ("api_access_logs", "api_key_events", "api_keys")
    result = {"tables": {}, "total_deleted": 0}
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for table in tables:
            if table not in existing:
                result["tables"][table] = 0
                continue
            count = safe_int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
            conn.execute(f"DELETE FROM {table}")
            result["tables"][table] = count
            result["total_deleted"] += count
        _v48120_reset_sequences(conn, tables)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    with _api_last_used_lock:
        _api_last_used_cache.clear()
    with _api_rate_lock:
        _api_rate_windows.clear()
    return result


# A true "Reset ALL app data" now includes API keys and API-owned logs.
_v48120_reset_all_app_data_base = reset_all_app_data


def reset_all_app_data():
    result = _v48120_reset_all_app_data_base()
    result["api"] = clear_all_api_data()
    return result


# ------------------------- Abuse-focused JSON shapes -----------------------

def _v48120_primary_abuse_type(flags):
    flags = [str(x or "").upper() for x in (flags or [])]
    if any("NETWORK" in x for x in flags):
        return "network"
    if any("CPU" in x for x in flags):
        return "cpu"
    if any("DISK" in x for x in flags):
        return "disk"
    return "other"


def _v48120_abuse_summary_text(flags):
    labels = []
    for flag in flags or []:
        name = str(flag or "").upper()
        if name == "CPU_SUSTAINED":
            labels.append("Sustained CPU saturation")
        elif "NETWORK_RX_PPS" in name:
            labels.append("Sustained RX PPS")
        elif "NETWORK_TX_PPS" in name:
            labels.append("Sustained TX PPS")
        elif "NETWORK_RX_AVG_MBPS" in name:
            labels.append("Sustained RX bandwidth")
        elif "NETWORK_TX_AVG_MBPS" in name:
            labels.append("Sustained TX bandwidth")
        elif "DISK" in name:
            labels.append("Sustained disk activity")
        else:
            labels.append(name.replace("_", " ").title())
    return ", ".join(labels) if labels else "Active abuse policy match"


def _v48120_compact_abuse_item(full):
    flags = list(full.get("flags") or [])
    item = {
        "node": full.get("node"),
        "vm_uuid": full.get("vm_uuid"),
        "primary_type": _v48120_primary_abuse_type(flags),
        "summary": _v48120_abuse_summary_text(flags),
        "flags": flags,
        "severity": full.get("severity"),
        "abuse_since": full.get("abuse_since"),
        "last_seen": full.get("last_seen"),
        "duration_seconds": max(0, safe_int(full.get("last_seen"), 0) - safe_int(full.get("abuse_since"), 0)),
        "placement": full.get("placement") or {},
        "sample": {"quality": (full.get("sample") or {}).get("quality", "UNKNOWN")},
    }
    if any("NETWORK" in str(flag).upper() for flag in flags):
        n = full.get("network") or {}
        item["network"] = {
            "rx_mbps": n.get("rx_mbps", 0), "tx_mbps": n.get("tx_mbps", 0),
            "rx_pps": n.get("rx_pps", 0), "tx_pps": n.get("tx_pps", 0),
            "rx_peak_pps": n.get("rx_peak_pps", 0), "tx_peak_pps": n.get("tx_peak_pps", 0),
            "rx_streak_seconds": max(safe_int(n.get("seconds_over_rx_pps"), 0), safe_int(n.get("rx_mbps_streak_seconds"), 0)),
            "tx_streak_seconds": max(safe_int(n.get("seconds_over_tx_pps"), 0), safe_int(n.get("tx_mbps_streak_seconds"), 0)),
        }
    if any("CPU" in str(flag).upper() for flag in flags):
        c = full.get("cpu") or {}
        item["cpu"] = {
            "full_percent": c.get("full_percent", 0), "core_percent": c.get("core_percent", 0),
            "vcpu": c.get("vcpu", 0), "streak_seconds": c.get("streak_seconds", 0),
        }
    if any("DISK" in str(flag).upper() for flag in flags):
        d = full.get("disk") or {}
        item["disk"] = {
            "read_bps": d.get("read_bps", 0), "write_bps": d.get("write_bps", 0),
            "read_iops": d.get("read_iops", 0), "write_iops": d.get("write_iops", 0),
            "streak_seconds": d.get("streak_seconds", 0),
        }
    return item


def _v48120_api_abuse_vms_impl():
    try:
        where, params = _api_abuse_filters()
    except ValueError as exc:
        return _api_error("invalid_filter", str(exc), 400)
    view = str(request.args.get("view") or "summary").strip().lower()
    if view not in {"summary", "full"}:
        return _api_error("invalid_view", "view must be summary or full.", 400)
    limit, offset = _api_limit_offset(200)
    sort = str(request.args.get("sort") or "severity").strip().lower()
    order = "ASC" if str(request.args.get("order") or "desc").strip().lower() == "asc" else "DESC"
    sort_map = {
        "severity": "a.severity", "last_seen": "a.last_seen", "abuse_since": "a.abuse_since",
        "node": "a.node", "rx_pps": "a.rx_pps", "tx_pps": "a.tx_pps",
        "rx_peak_pps": "a.rx_peak_pps", "tx_peak_pps": "a.tx_peak_pps",
        "rx_mbps": "a.rx_mbps", "tx_mbps": "a.tx_mbps",
        "cpu": "a.cpu_full_percent", "disk_read": "a.disk_read_bps", "disk_write": "a.disk_write_bps",
        "iops": "MAX(a.disk_read_iops,a.disk_write_iops)",
    }
    sort_sql = sort_map.get(sort, "a.severity")
    where_sql = " WHERE " + " AND ".join(where)
    conn = db()
    try:
        total = safe_int(conn.execute(f"SELECT COUNT(*) FROM vm_abuse_state a{where_sql}", params).fetchone()[0], 0)
        rows = conn.execute(
            _API_ABUSE_SELECT + where_sql + f" ORDER BY {sort_sql} {order},a.last_seen DESC,a.node COLLATE NOCASE,a.vm_uuid LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
    finally:
        conn.close()
    full_items = [_api_vm_abuse_item(row) for row in rows]
    data = full_items if view == "full" else [_v48120_compact_abuse_item(item) for item in full_items]
    return _api_response({"data": data, "meta": {
        "count": len(data), "total": total, "limit": limit, "offset": offset,
        "sort": sort if sort in sort_map else "severity", "order": order.lower(), "view": view,
    }})


app.view_functions["api_v1_abuse_vms"] = require_api_scopes("abuse:read")(_v48120_api_abuse_vms_impl)


def _v48120_api_abuse_vm_impl(vm_uuid):
    vm_uuid = str(vm_uuid or "").strip()
    if len(vm_uuid) > 128:
        return _api_error("invalid_vm_uuid", "VM UUID is invalid.", 400)
    view = str(request.args.get("view") or "summary").strip().lower()
    if view not in {"summary", "full"}:
        return _api_error("invalid_view", "view must be summary or full.", 400)
    node = str(request.args.get("node") or "").strip()
    where = ["a.vm_uuid=?", "a.is_abuse=1", "a.last_seen>=?"]
    params = [vm_uuid, now_ts() - FAST_CURRENT_STALE_SECONDS]
    if node:
        where.append("a.node=?")
        params.append(node)
    conn = db()
    try:
        rows = conn.execute(_API_ABUSE_SELECT + " WHERE " + " AND ".join(where) + " ORDER BY a.last_seen DESC LIMIT 2", params).fetchall()
    finally:
        conn.close()
    if not rows:
        return _api_error("abuse_vm_not_found", "No active abuse record was found for this VM.", 404)
    if len(rows) > 1 and not node:
        return _api_error("ambiguous_vm_location", "The VM UUID exists on more than one node. Provide ?node=<node>.", 409)
    full = _api_vm_abuse_item(rows[0])
    return _api_response({"data": full if view == "full" else _v48120_compact_abuse_item(full)})


app.view_functions["api_v1_abuse_vm"] = require_api_scopes("abuse:read")(_v48120_api_abuse_vm_impl)


def _v48120_event_compact(item):
    flags = list(item.get("flags") or [])
    result = {
        "event_id": item.get("event_id"), "event_time": item.get("event_time"),
        "event_type": item.get("event_type"), "node": item.get("node"), "vm_uuid": item.get("vm_uuid"),
        "primary_type": _v48120_primary_abuse_type(flags), "summary": _v48120_abuse_summary_text(flags),
        "flags": flags, "severity": item.get("severity"), "detail": item.get("detail", ""),
    }
    if any("NETWORK" in str(flag).upper() for flag in flags):
        result["network"] = item.get("network") or {}
    if any("CPU" in str(flag).upper() for flag in flags):
        result["cpu"] = item.get("cpu") or {}
    if any("DISK" in str(flag).upper() for flag in flags):
        result["disk"] = item.get("disk") or {}
    return result


def _v48120_api_abuse_events_impl():
    limit, offset = _api_limit_offset(200)
    view = str(request.args.get("view") or "summary").strip().lower()
    if view not in {"summary", "full"}:
        return _api_error("invalid_view", "view must be summary or full.", 400)
    where, params = [], []
    node = str(request.args.get("node") or "").strip()
    vm_uuid = str(request.args.get("vm_uuid") or "").strip()
    q = str(request.args.get("q") or "").strip()
    event_type = str(request.args.get("event_type") or "").strip().lower()
    since = max(0, safe_int(request.args.get("since"), 0))
    until = max(0, safe_int(request.args.get("until"), 0))
    if node: where.append("e.node=?"); params.append(node)
    if vm_uuid: where.append("e.vm_uuid=?"); params.append(vm_uuid)
    if q:
        p = like_pattern(q); where.append("(e.node LIKE ? OR e.vm_uuid LIKE ? OR e.abuse_flags LIKE ? OR e.detail LIKE ?)"); params.extend([p,p,p,p])
    if event_type:
        if event_type not in ("started", "updated", "recovered"):
            return _api_error("invalid_filter", "event_type must be started, updated or recovered.", 400)
        where.append("e.event_type=?"); params.append(event_type)
    if since: where.append("e.event_time>=?"); params.append(since)
    if until: where.append("e.event_time<=?"); params.append(until)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    conn = db()
    try:
        total = safe_int(conn.execute(f"SELECT COUNT(*) FROM vm_abuse_events e{where_sql}", params).fetchone()[0], 0)
        rows = conn.execute(f"""
            SELECT e.id,e.event_time,e.event_type,e.node,e.vm_uuid,e.abuse_flags,e.severity,
                   e.rx_mbps,e.tx_mbps,e.rx_pps,e.tx_pps,e.rx_peak_pps,e.tx_peak_pps,
                   e.seconds_over_rx_pps,e.seconds_over_tx_pps,
                   e.cpu_full_percent,e.cpu_core_percent,e.vcpu_current,e.cpu_streak_seconds,
                   e.disk_read_bps,e.disk_write_bps,e.disk_read_iops,e.disk_write_iops,e.disk_streak_seconds,
                   e.policy_revision,e.engine_version,e.detail
            FROM vm_abuse_events e{where_sql}
            ORDER BY e.event_time DESC,e.id DESC LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()
    finally:
        conn.close()
    data = []
    for row in rows:
        item = {
            "event_id": safe_int(row[0], 0), "event_time": safe_int(row[1], 0), "event_type": str(row[2]),
            "node": str(row[3]), "vm_uuid": str(row[4]), "flags": _api_parse_flags(row[5]),
            "severity": round(safe_float(row[6], 0), 4),
            "network": {
                "rx_mbps": round(safe_float(row[7], 0), 4), "tx_mbps": round(safe_float(row[8], 0), 4),
                "rx_pps": round(safe_float(row[9], 0), 4), "tx_pps": round(safe_float(row[10], 0), 4),
                "rx_peak_pps": round(safe_float(row[11], 0), 4), "tx_peak_pps": round(safe_float(row[12], 0), 4),
                "seconds_over_rx_pps": safe_int(row[13], 0), "seconds_over_tx_pps": safe_int(row[14], 0),
            },
            "cpu": {"full_percent": round(safe_float(row[15], 0), 4), "core_percent": round(safe_float(row[16], 0), 4), "vcpu": safe_int(row[17], 0), "streak_seconds": safe_int(row[18], 0)},
            "disk": {"read_bps": round(safe_float(row[19], 0), 4), "write_bps": round(safe_float(row[20], 0), 4), "read_iops": round(safe_float(row[21], 0), 4), "write_iops": round(safe_float(row[22], 0), 4), "streak_seconds": safe_int(row[23], 0)},
            "policy": {"revision": safe_int(row[24], 0), "engine_version": str(row[25] or "")},
            "detail": str(row[26] or ""),
        }
        data.append(item if view == "full" else _v48120_event_compact(item))
    return _api_response({"data": data, "meta": {"count": len(data), "total": total, "limit": limit, "offset": offset, "view": view}})


app.view_functions["api_v1_abuse_events"] = require_api_scopes("abuse_events:read")(_v48120_api_abuse_events_impl)


@app.route("/api/v1/abuse/summary", methods=["GET"])
@require_api_scopes("abuse:read")
def api_v1_abuse_summary():
    cutoff = now_ts() - FAST_CURRENT_STALE_SECONDS
    conn = db()
    try:
        total = safe_int(conn.execute("SELECT COUNT(*) FROM vm_abuse_state WHERE is_abuse=1 AND last_seen>=?", (cutoff,)).fetchone()[0], 0)
        network = safe_int(conn.execute("SELECT COUNT(*) FROM vm_abuse_state WHERE is_abuse=1 AND last_seen>=? AND abuse_flags LIKE '%NETWORK%'", (cutoff,)).fetchone()[0], 0)
        cpu = safe_int(conn.execute("SELECT COUNT(*) FROM vm_abuse_state WHERE is_abuse=1 AND last_seen>=? AND abuse_flags LIKE '%CPU%'", (cutoff,)).fetchone()[0], 0)
        disk = safe_int(conn.execute("SELECT COUNT(*) FROM vm_abuse_state WHERE is_abuse=1 AND last_seen>=? AND abuse_flags LIKE '%DISK%'", (cutoff,)).fetchone()[0], 0)
        oldest = conn.execute("SELECT MIN(abuse_since),MAX(last_seen),MAX(severity) FROM vm_abuse_state WHERE is_abuse=1 AND last_seen>=?", (cutoff,)).fetchone()
        nodes = conn.execute("""
            SELECT node,COUNT(*) AS cnt,MAX(severity) AS max_severity
            FROM vm_abuse_state WHERE is_abuse=1 AND last_seen>=?
            GROUP BY node ORDER BY cnt DESC,max_severity DESC,node COLLATE NOCASE LIMIT 20
        """, (cutoff,)).fetchall()
        flags = conn.execute("SELECT abuse_flags FROM vm_abuse_state WHERE is_abuse=1 AND last_seen>=?", (cutoff,)).fetchall()
    finally:
        conn.close()
    flag_counts = {}
    for row in flags:
        for flag in _api_parse_flags(row[0]):
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
    return _api_response({"data": {
        "current_abuse": total,
        "by_type": {"network": network, "cpu": cpu, "disk": disk},
        "by_flag": dict(sorted(flag_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "nodes": [{"node": str(r[0]), "count": safe_int(r[1], 0), "max_severity": round(safe_float(r[2], 0), 4)} for r in nodes],
        "oldest_abuse_since": safe_int((oldest or [0])[0], 0) or None,
        "latest_seen": safe_int((oldest or [0,0])[1], 0) or None,
        "max_severity": round(safe_float((oldest or [0,0,0])[2], 0), 4),
    }})


# ---------------------- Full Admin API Management UI ----------------------

def _v48120_api_scope_checkboxes():
    rows = []
    for scope, label in API_PRIMARY_SCOPES.items():
        rows.append(
            f'<label class="api-scope"><input type="checkbox" name="scopes" value="{escape(scope,quote=True)}" checked>'
            f'<span><b>{escape(scope)}</b><small>{escape(label)}</small></span></label>'
        )
    return "".join(rows)


def _v48120_api_counts():
    conn = db()
    try:
        now = now_ts()
        keys = conn.execute("""
            SELECT
              SUM(CASE WHEN is_active=1 AND (expires_at IS NULL OR expires_at>?) THEN 1 ELSE 0 END),
              SUM(CASE WHEN is_active=0 THEN 1 ELSE 0 END),
              SUM(CASE WHEN is_active=1 AND expires_at IS NOT NULL AND expires_at<=? THEN 1 ELSE 0 END)
            FROM api_keys
        """, (now, now)).fetchone() or (0,0,0)
        requests_24h = safe_int(conn.execute("SELECT COUNT(*) FROM api_access_logs WHERE request_time>=?", (now-86400,)).fetchone()[0], 0)
        errors_24h = safe_int(conn.execute("SELECT COUNT(*) FROM api_access_logs WHERE request_time>=? AND status_code>=400", (now-86400,)).fetchone()[0], 0)
        denied_24h = safe_int(conn.execute("SELECT COUNT(*) FROM api_key_events WHERE event_time>=? AND event_type IN ('AUTH_FAILED','IP_DENIED','SCOPE_DENIED')", (now-86400,)).fetchone()[0], 0)
        access_total = safe_int(conn.execute("SELECT COUNT(*) FROM api_access_logs").fetchone()[0], 0)
        event_total = safe_int(conn.execute("SELECT COUNT(*) FROM api_key_events").fetchone()[0], 0)
    finally:
        conn.close()
    return {
        "active": safe_int(keys[0],0), "revoked": safe_int(keys[1],0), "expired": safe_int(keys[2],0),
        "requests_24h": requests_24h, "errors_24h": errors_24h, "denied_24h": denied_24h,
        "access_total": access_total, "event_total": event_total,
    }


def _v48120_api_nav(tab, counts):
    items = [
        ("keys", "Keys", counts["active"]),
        ("requests", "Request Logs", counts["access_total"]),
        ("events", "Management Events", counts["event_total"]),
        ("docs", "API Reference", None),
    ]
    return '<nav class="api-tabs">' + ''.join(
        f'<a class="{"active" if tab==name else ""}" href="{url_for("admin_api_keys_page",tab=name)}">{escape(label)}'
        + (f'<span>{count:,}</span>' if count is not None else '') + '</a>'
        for name,label,count in items
    ) + '</nav>'


def _v48120_api_key_table():
    conn = db()
    try:
        rows = conn.execute(
            """SELECT id,key_id,name,secret_hash,scopes_json,allowed_ips_json,is_active,
                      created_at,created_by,expires_at,last_used_at,last_used_ip,use_count,
                      revoked_at,revoked_by,rotated_from_key_id,note
               FROM api_keys ORDER BY is_active DESC,created_at DESC,id DESC"""
        ).fetchall()
    finally:
        conn.close()
    keys = [_api_key_row_to_dict(row) for row in rows]
    body = []
    for key in keys:
        status_label, status_class = _api_admin_status(key)
        scopes = ''.join(f'<span class="api-chip">{escape(scope)}</span>' for scope in key.get('scopes') or []) or '-'
        allowed = '<br>'.join(escape(x) for x in key.get('allowed_ips') or []) or '<span class="muted">Any source</span>'
        expiry = fmt_full(key.get('expires_at')) if key.get('expires_at') else 'Never'
        used = fmt_full(key.get('last_used_at')) if key.get('last_used_at') else 'Never'
        rotate_revoke = ''
        if status_label == 'Active':
            rotate_revoke = f'''
              <form method="post" action="{url_for('admin_api_key_rotate')}" onsubmit="return confirm('Rotate this key? The current secret will stop working immediately.')">
                <input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="key_id" value="{escape(key['key_id'],quote=True)}"><button class="btn" type="submit">Rotate</button>
              </form>
              <form method="post" action="{url_for('admin_api_key_revoke')}" onsubmit="return confirm('Revoke this key now?')">
                <input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="key_id" value="{escape(key['key_id'],quote=True)}"><button class="btn-warn" type="submit">Revoke</button>
              </form>'''
        delete_phrase = f"DELETE {key['key_id']}"
        delete_form = f'''
          <form method="post" action="{url_for('admin_api_key_delete')}" onsubmit="const expected='{escape(delete_phrase,quote=True)}';const v=prompt('Permanently delete this key and ALL of its API logs? Type: '+expected);if(v!==expected)return false;this.querySelector('[name=confirm_text]').value=v;return confirm('This cannot be undone. Continue?')">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="key_id" value="{escape(key['key_id'],quote=True)}"><input type="hidden" name="confirm_text" value=""><button class="btn-danger" type="submit">Delete permanently</button>
          </form>'''
        body.append(f'''
        <tr>
          <td><b>{escape(key['name'])}</b><code class="key-id">{escape(API_KEY_PREFIX)}_{escape(key['key_id'])}_…</code>{f'<small>{escape(key.get("note") or "")}</small>' if key.get('note') else ''}</td>
          <td><span class="status {status_class}">{escape(status_label)}</span><small>Created {escape(fmt_full(key['created_at']))}<br>by {escape(key.get('created_by') or '-')}</small></td>
          <td><div class="api-chip-wrap">{scopes}</div></td>
          <td><small>{allowed}</small></td>
          <td><b>{escape(used)}</b><small>{escape(key.get('last_used_ip') or '-')} · {safe_int(key.get('use_count'),0):,} flush(es)</small></td>
          <td>{escape(expiry)}</td>
          <td><div class="api-actions">{rotate_revoke}{delete_form}</div></td>
        </tr>''')
    if not body:
        body.append('<tr><td colspan="7" class="empty">No API keys. Create the first Abuse integration key above.</td></tr>')
    return ''.join(body), len(keys)


def _v48120_access_log_query():
    q = str(request.args.get('q') or '').strip()
    status = str(request.args.get('status') or '').strip().lower()
    key_id = str(request.args.get('key_id') or '').strip().lower()
    where, params = [], []
    if q:
        p = like_pattern(q)
        where.append('(key_name LIKE ? OR key_id LIKE ? OR source_ip LIKE ? OR path LIKE ? OR request_id LIKE ? OR user_agent LIKE ?)')
        params.extend([p,p,p,p,p,p])
    if key_id:
        where.append('key_id=?'); params.append(key_id)
    if status == '2xx': where.append('status_code BETWEEN 200 AND 299')
    elif status == '3xx': where.append('status_code BETWEEN 300 AND 399')
    elif status == '4xx': where.append('status_code BETWEEN 400 AND 499')
    elif status == '5xx': where.append('status_code>=500')
    elif status not in ('', 'all'): status = ''
    return q, status, key_id, where, params


def _v48120_request_logs_tab(counts):
    q, status, key_id, where, params = _v48120_access_log_query()
    page_no = max(1, safe_int(request.args.get('page'), 1)); per_page = 100; offset = (page_no-1)*per_page
    where_sql = (' WHERE ' + ' AND '.join(where)) if where else ''
    conn = db()
    try:
        total = safe_int(conn.execute(f'SELECT COUNT(*) FROM api_access_logs{where_sql}', params).fetchone()[0], 0)
        rows = conn.execute(f'''SELECT id,request_time,request_id,key_id,key_name,source_ip,method,path,query_string,status_code,duration_ms,response_bytes,user_agent,error_code
                              FROM api_access_logs{where_sql} ORDER BY request_time DESC,id DESC LIMIT ? OFFSET ?''', params+[per_page,offset]).fetchall()
    finally:
        conn.close()
    body=[]
    for r in rows:
        path = str(r[7] or '') + (('?' + str(r[8])) if r[8] else '')
        status_code=safe_int(r[9],0); cls='ok' if status_code<400 else ('warn' if status_code<500 else 'bad')
        body.append(f'''<tr><td><input class="api-log-check" form="api-access-selected" type="checkbox" name="ids" value="{safe_int(r[0],0)}"></td><td>{escape(fmt_full(r[1]))}<small>{escape(r[2] or '-')}</small></td><td><b>{escape(r[4] or '-')}</b><small>{escape(r[3] or '-')}</small></td><td>{escape(r[5] or '-')}</td><td><span class="method">{escape(r[6] or '-')}</span><code class="api-path">{escape(path)}</code></td><td><span class="http-status {cls}">{status_code}</span>{f'<small>{escape(r[13])}</small>' if r[13] else ''}</td><td>{safe_float(r[10],0):.1f} ms<small>{human(safe_int(r[11],0))}</small></td><td><small class="ua">{escape(r[12] or '-')}</small></td></tr>''')
    if not body: body=['<tr><td colspan="8" class="empty">No request logs match this filter</td></tr>']
    pages=max(1,(total+per_page-1)//per_page)
    prev=url_for('admin_api_keys_page',tab='requests',q=q or None,status=status or None,key_id=key_id or None,page=max(1,page_no-1))
    nxt=url_for('admin_api_keys_page',tab='requests',q=q or None,status=status or None,key_id=key_id or None,page=min(pages,page_no+1))
    filter_hidden=f'<input type="hidden" name="q" value="{escape(q,quote=True)}"><input type="hidden" name="status" value="{escape(status,quote=True)}"><input type="hidden" name="key_id_filter" value="{escape(key_id,quote=True)}">'
    return f'''
    <div class="card">
      <div class="table-title-row"><div><h3>API Request Logs</h3><div class="table-hint">Every authenticated API request. Secrets and Authorization headers are never stored. Automatic retention: {API_ACCESS_LOG_RETENTION_DAYS} day(s).</div></div><div class="count-badges"><span>Total <b>{counts['access_total']:,}</b></span><span>24h <b>{counts['requests_24h']:,}</b></span><span>Errors 24h <b>{counts['errors_24h']:,}</b></span></div></div>
      <form class="api-filter" method="get" action="{url_for('admin_api_keys_page')}"><input type="hidden" name="tab" value="requests"><input name="q" value="{escape(q,quote=True)}" placeholder="Key, IP, endpoint, request ID, user agent"><select name="status"><option value="">All status</option><option value="2xx" {'selected' if status=='2xx' else ''}>2xx</option><option value="3xx" {'selected' if status=='3xx' else ''}>3xx</option><option value="4xx" {'selected' if status=='4xx' else ''}>4xx</option><option value="5xx" {'selected' if status=='5xx' else ''}>5xx</option></select><input name="key_id" value="{escape(key_id,quote=True)}" placeholder="Exact key ID"><button class="btn" type="submit">Filter</button><a class="btn-ghost" href="{url_for('admin_api_keys_page',tab='requests')}">Reset</a></form>
      <div class="api-log-tools">
        <form id="api-access-selected" method="post" action="{url_for('admin_api_logs_clear')}" onsubmit="return confirm('Delete selected request logs?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="kind" value="access"><input type="hidden" name="mode" value="selected"><button class="btn-danger" type="submit">Delete selected</button></form>
        <form method="post" action="{url_for('admin_api_logs_clear')}" onsubmit="return confirm('Delete every request log matching the current filter?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="kind" value="access"><input type="hidden" name="mode" value="filtered">{filter_hidden}<input name="confirm_text" placeholder="CLEAR FILTERED" required><button class="btn-danger" type="submit">Clear filtered</button></form>
        <form method="post" action="{url_for('admin_api_logs_clear')}" onsubmit="return confirm('Delete ALL API request logs?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="kind" value="access"><input type="hidden" name="mode" value="all"><input name="confirm_text" placeholder="CLEAR ALL API LOGS" required><button class="btn-danger" type="submit">Clear all request logs</button></form>
      </div>
      <div class="table-wrap"><table class="api-log-table"><thead><tr><th><input type="checkbox" onclick="document.querySelectorAll('.api-log-check').forEach(x=>x.checked=this.checked)"></th><th>Time / Request ID</th><th>Key</th><th>Source IP</th><th>Request</th><th>Status</th><th>Latency / Size</th><th>User agent</th></tr></thead><tbody>{''.join(body)}</tbody></table></div>
      <div class="pager"><a class="btn-ghost {'disabled' if page_no<=1 else ''}" href="{escape(prev,quote=True)}">Previous</a><span>Page {page_no:,} / {pages:,} · {total:,} row(s)</span><a class="btn-ghost {'disabled' if page_no>=pages else ''}" href="{escape(nxt,quote=True)}">Next</a></div>
    </div>'''


def _v48120_event_log_query():
    q=str(request.args.get('q') or '').strip(); event_type=str(request.args.get('event_type') or '').strip().upper(); where=[]; params=[]
    if q:
        p=like_pattern(q); where.append('(key_name LIKE ? OR key_id LIKE ? OR actor LIKE ? OR source_ip LIKE ? OR detail LIKE ?)'); params.extend([p,p,p,p,p])
    if event_type:
        where.append('event_type=?'); params.append(event_type)
    return q,event_type,where,params


def _v48120_events_tab(counts):
    q,event_type,where,params=_v48120_event_log_query(); page_no=max(1,safe_int(request.args.get('page'),1)); per_page=100; offset=(page_no-1)*per_page; where_sql=(' WHERE '+' AND '.join(where)) if where else ''
    conn=db()
    try:
        total=safe_int(conn.execute(f'SELECT COUNT(*) FROM api_key_events{where_sql}',params).fetchone()[0],0)
        rows=conn.execute(f'''SELECT id,event_time,event_type,key_id,key_name,actor,source_ip,detail FROM api_key_events{where_sql} ORDER BY event_time DESC,id DESC LIMIT ? OFFSET ?''',params+[per_page,offset]).fetchall()
        event_types=[str(r[0]) for r in conn.execute('SELECT DISTINCT event_type FROM api_key_events ORDER BY event_type').fetchall()]
    finally: conn.close()
    body=[]
    for r in rows:
        body.append(f'''<tr><td><input class="api-event-check" form="api-event-selected" type="checkbox" name="ids" value="{safe_int(r[0],0)}"></td><td>{escape(fmt_full(r[1]))}</td><td><span class="event-type">{escape(r[2] or '-')}</span></td><td><b>{escape(r[4] or '-')}</b><small>{escape(r[3] or '-')}</small></td><td>{escape(r[5] or '-')}</td><td>{escape(r[6] or '-')}</td><td>{escape(r[7] or '')}</td></tr>''')
    if not body: body=['<tr><td colspan="7" class="empty">No management events match this filter</td></tr>']
    options=''.join(f'<option value="{escape(t,quote=True)}" {"selected" if t==event_type else ""}>{escape(t)}</option>' for t in event_types)
    filter_hidden=f'<input type="hidden" name="q" value="{escape(q,quote=True)}"><input type="hidden" name="event_type_filter" value="{escape(event_type,quote=True)}">'
    return f'''
    <div class="card"><div class="table-title-row"><div><h3>API Management Events</h3><div class="table-hint">Key lifecycle and authentication denials. Successful endpoint calls belong in Request Logs.</div></div><div class="count-badges"><span>Total <b>{counts['event_total']:,}</b></span><span>Denied 24h <b>{counts['denied_24h']:,}</b></span></div></div>
      <form class="api-filter" method="get" action="{url_for('admin_api_keys_page')}"><input type="hidden" name="tab" value="events"><input name="q" value="{escape(q,quote=True)}" placeholder="Key, actor, IP or detail"><select name="event_type"><option value="">All events</option>{options}</select><button class="btn" type="submit">Filter</button><a class="btn-ghost" href="{url_for('admin_api_keys_page',tab='events')}">Reset</a></form>
      <div class="api-log-tools"><form id="api-event-selected" method="post" action="{url_for('admin_api_logs_clear')}" onsubmit="return confirm('Delete selected management events?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="kind" value="events"><input type="hidden" name="mode" value="selected"><button class="btn-danger" type="submit">Delete selected</button></form><form method="post" action="{url_for('admin_api_logs_clear')}" onsubmit="return confirm('Delete every management event matching the filter?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="kind" value="events"><input type="hidden" name="mode" value="filtered">{filter_hidden}<input name="confirm_text" placeholder="CLEAR FILTERED" required><button class="btn-danger" type="submit">Clear filtered</button></form><form method="post" action="{url_for('admin_api_logs_clear')}" onsubmit="return confirm('Delete ALL API management events?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><input type="hidden" name="kind" value="events"><input type="hidden" name="mode" value="all"><input name="confirm_text" placeholder="CLEAR ALL API LOGS" required><button class="btn-danger" type="submit">Clear all events</button></form></div>
      <div class="table-wrap"><table class="api-log-table"><thead><tr><th><input type="checkbox" onclick="document.querySelectorAll('.api-event-check').forEach(x=>x.checked=this.checked)"></th><th>Time</th><th>Event</th><th>Key</th><th>Actor</th><th>Source IP</th><th>Detail</th></tr></thead><tbody>{''.join(body)}</tbody></table></div>
    </div>'''


def _v48120_docs_tab():
    base=request.url_root.rstrip('/')
    return f'''
    <div class="docs-grid">
      <div class="card"><span class="eyebrow">ABUSE API V1</span><h3>Small surface, clear purpose</h3><p class="muted">The primary API is now centered on current Abuse state and Abuse history. Old VM/node/bandwidth endpoints remain available for backward compatibility but are intentionally not promoted here.</p><div class="endpoint-list"><div><code>GET /api/v1/me</code><span>Validate key and show granted scopes</span></div><div><code>GET /api/v1/abuse/summary</code><span>Counts by type, flag and node</span></div><div><code>GET /api/v1/abuse/vms</code><span>Compact current Abuse list by default</span></div><div><code>GET /api/v1/abuse/vms?view=full</code><span>Full CPU/network/disk/sample payload</span></div><div><code>GET /api/v1/abuse/vms/&lt;uuid&gt;?node=&lt;node&gt;</code><span>One active Abuse VM</span></div><div><code>GET /api/v1/abuse/events</code><span>Compact persistent Abuse history</span></div><div><code>GET /api/v1/abuse/events?view=full</code><span>Full event metrics and policy revision</span></div></div></div>
      <div class="card"><h3>Quick test</h3><pre class="api-code">API_KEY='bwm_live_xxxxxxxxxxxx_SECRET'

curl -sS \\
-H "Authorization: Bearer ${{API_KEY}}" \\
'{escape(base)}/api/v1/abuse/vms?limit=500' | jq</pre><h3 style="margin-top:18px">Only UUIDs</h3><pre class="api-code">curl -sS \\
-H "Authorization: Bearer ${{API_KEY}}" \\
'{escape(base)}/api/v1/abuse/vms?limit=500' \\
| jq -r '.data[].vm_uuid'</pre></div>
    </div>'''


def _v48120_admin_api_keys_page():
    auth=require_admin()
    if auth: return auth
    tab=str(request.args.get('tab') or 'keys').strip().lower()
    if tab not in {'keys','requests','events','docs'}: tab='keys'
    counts=_v48120_api_counts(); once=session.pop('api_key_once',None); msg=str(request.args.get('apimsg') or '').strip(); err=str(request.args.get('apierr') or '').strip()
    once_html=''
    if isinstance(once,dict) and once.get('token'):
        once_html=f'''<div class="card api-secret-once"><div><span class="eyebrow">COPY NOW</span><h3>{escape(once.get('title') or 'API key created')}</h3><p>Plaintext is shown once. Only a SHA-256 hash is stored.</p></div><div class="api-secret-line"><code>{escape(once['token'])}</code><button class="btn" type="button" data-copy="{escape(once['token'],quote=True)}">Copy key</button></div></div>'''
    if tab=='keys':
        rows,key_count=_v48120_api_key_table()
        content_tab=f'''
        <div class="api-grid"><div class="card"><div class="table-title-row"><div><h3>Create API key</h3><div class="table-hint">Abuse permissions are preselected. Enable VM, Node, Bandwidth or API Log access only when the client needs them.</div></div></div><form method="post" action="{url_for('admin_api_key_create')}"><input type="hidden" name="csrf_token" value="{escape(csrf_token(),quote=True)}"><div class="api-form-row"><label>Name<input name="name" maxlength="80" placeholder="Windows Abuse App" required></label><label>Expiration<select name="expiration"><option value="never">Never</option><option value="7">7 days</option><option value="30">30 days</option><option value="90">90 days</option><option value="180">180 days</option><option value="365">365 days</option></select></label></div><div class="api-scope-grid">{_v48120_api_scope_checkboxes()}</div><label class="api-form-full">Allowed source IP/CIDR<textarea name="allowed_ips" placeholder="Optional, one per line\n103.199.16.36\n10.20.0.0/16"></textarea><small>Empty means any source IP. API request logs will record the effective source address.</small></label><label class="api-form-full">Note<input name="note" maxlength="500" placeholder="Owner, app or purpose"></label><button class="btn primary-action" type="submit">Generate API key</button></form></div><div class="card api-principles"><h3>Operational rules</h3><div class="principle"><b>Agent token stays separate</b><span>External apps never receive BW_MONITOR_TOKEN.</span></div><div class="principle"><b>Rotate without downtime</b><span>Create the replacement, then update the client immediately.</span></div><div class="principle"><b>Delete really means delete</b><span>Permanent delete removes the key, its request logs and its management events.</span></div><div class="principle"><b>Abuse-first payloads</b><span>Summary JSON is compact by default; add <code>?view=full</code> for diagnostics.</span></div></div></div>
        <div class="card vm-table-card"><div class="table-title-row"><div><h3>API Keys</h3><div class="table-hint">{key_count} key record(s). Revoke keeps history. Delete permanently removes the record and every related API log.</div></div></div><div class="table-wrap"><table class="api-table"><thead><tr><th>Name / Key ID</th><th>Status</th><th>Permissions</th><th>Allowed IP</th><th>Last used</th><th>Expires</th><th>Actions</th></tr></thead><tbody>{rows}</tbody></table></div></div>'''
    elif tab=='requests': content_tab=_v48120_request_logs_tab(counts)
    elif tab=='events': content_tab=_v48120_events_tab(counts)
    else: content_tab=_v48120_docs_tab()
    content=f'''
    <style>
    .api-hero{{display:flex;justify-content:space-between;gap:18px;align-items:center}}.api-stat-grid{{display:grid;grid-template-columns:repeat(6,minmax(110px,1fr));gap:8px;margin:14px 0}}.api-stat{{border:1px solid var(--line,#e5e7eb);border-radius:11px;padding:11px;background:var(--card,#fff)}}.api-stat small{{display:block;color:#667085;font-size:10px;font-weight:800;text-transform:uppercase}}.api-stat b{{display:block;font-size:21px;margin-top:4px}}.api-tabs{{display:flex;gap:7px;flex-wrap:wrap;margin:0 0 14px}}.api-tabs a{{display:flex;gap:7px;align-items:center;padding:9px 13px;border:1px solid var(--line,#d0d5dd);border-radius:9px;text-decoration:none;font-weight:800;color:inherit}}.api-tabs a.active{{background:#175cd3;color:#fff;border-color:#175cd3}}.api-tabs span{{padding:2px 6px;border-radius:999px;background:rgba(127,127,127,.18);font-size:10px}}.api-grid{{display:grid;grid-template-columns:minmax(360px,.9fr) minmax(360px,1.1fr);gap:14px;align-items:start}}.api-form-row{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}.api-form-row label,.api-form-full{{display:grid;gap:5px;font-size:12px;font-weight:800}}.api-form-full{{margin-top:11px}}.api-form-full input,.api-form-full textarea,.api-form-row input,.api-form-row select{{width:100%;box-sizing:border-box}}.api-form-full textarea{{min-height:86px}}.api-scope-grid{{display:grid;gap:8px;margin:13px 0}}.api-scope{{display:flex;gap:9px;padding:12px;border:1px solid var(--line,#d0d5dd);border-radius:10px}}.api-scope span{{display:grid;gap:3px}}.api-scope small,.muted,.api-table small,.api-log-table small{{display:block;color:#667085;font-size:10px;margin-top:3px}}.primary-action{{margin-top:13px}}.api-principles .principle{{display:grid;gap:3px;padding:12px 0;border-bottom:1px solid var(--line,#e5e7eb)}}.api-principles .principle:last-child{{border-bottom:0}}.api-principles span{{color:#667085;font-size:12px}}.api-table{{min-width:1300px}}.api-actions{{display:flex;gap:5px;flex-wrap:wrap}}.api-actions form{{margin:0}}.api-chip-wrap{{display:flex;gap:4px;flex-wrap:wrap}}.api-chip{{padding:4px 7px;border-radius:999px;background:#eaf2ff;color:#175cd3;font-size:10px;font-weight:900}}.key-id{{display:block;margin-top:5px;font-size:10px}}.api-secret-once{{border:2px solid #12b76a!important;background:linear-gradient(135deg,#ecfdf3,#fff)!important}}.api-secret-line{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}.api-secret-line code{{flex:1;min-width:280px;word-break:break-all;padding:11px;background:#101828;color:#fff;border-radius:8px}}.api-filter,.api-log-tools{{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin:12px 0}}.api-filter input{{min-width:220px}}.api-log-tools form{{display:flex;gap:6px;align-items:center;margin:0}}.api-log-tools input{{max-width:180px}}.api-log-table{{min-width:1350px}}.api-path{{display:block;max-width:520px;white-space:normal;word-break:break-all;margin-top:4px}}.method,.event-type{{display:inline-flex;padding:3px 6px;border-radius:6px;background:#f2f4f7;font-size:10px;font-weight:900}}.http-status{{display:inline-flex;padding:3px 7px;border-radius:999px;font-weight:900}}.http-status.ok{{background:#dcfae6;color:#067647}}.http-status.warn{{background:#fef0c7;color:#b54708}}.http-status.bad{{background:#fee4e2;color:#b42318}}.ua{{max-width:260px;word-break:break-word}}.pager{{display:flex;justify-content:center;gap:12px;align-items:center;margin-top:12px}}.btn-ghost{{display:inline-flex;padding:8px 11px;border:1px solid var(--line,#d0d5dd);border-radius:8px;text-decoration:none;color:inherit}}.btn-ghost.disabled{{pointer-events:none;opacity:.45}}.docs-grid{{display:grid;grid-template-columns:1.1fr .9fr;gap:14px}}.endpoint-list{{display:grid;gap:8px;margin-top:14px}}.endpoint-list>div{{display:grid;grid-template-columns:minmax(280px,.8fr) 1fr;gap:12px;align-items:center}}.endpoint-list code{{padding:7px;background:#f2f4f7;border-radius:7px}}.endpoint-list span{{color:#667085;font-size:12px}}.api-code{{white-space:pre-wrap;word-break:break-word;background:#101828;color:#e6edf3;padding:14px;border-radius:10px}}html[data-theme=dark] .api-chip{{background:#17365d;color:#b9d7ff}}html[data-theme=dark] .api-secret-once{{background:linear-gradient(135deg,#0f2f24,#172033)!important}}html[data-theme=dark] .endpoint-list code,html[data-theme=dark] .method,html[data-theme=dark] .event-type{{background:#1d2939;color:#d0d5dd}}@media(max-width:1100px){{.api-stat-grid{{grid-template-columns:repeat(3,1fr)}}.api-grid,.docs-grid{{grid-template-columns:1fr}}}}@media(max-width:650px){{.api-stat-grid{{grid-template-columns:repeat(2,1fr)}}.api-form-row,.endpoint-list>div{{grid-template-columns:1fr}}}}
    </style>
    <div class="card page-hero api-hero"><div><span class="eyebrow">ADMIN / API CONTROL CENTER</span><h2>API Management</h2><p>Abuse-first monitoring with complete read-only VM, Node, Bandwidth and API Log integrations.</p></div><div class="hero-meta"><span>API <b>read-only</b></span><span>Access logs <b>{'ON' if API_ACCESS_LOGS_ENABLED else 'OFF'}</b></span></div></div>
    {_v490_admin_nav('api')}
    <div class="api-stat-grid"><div class="api-stat"><small>Active keys</small><b>{counts['active']:,}</b></div><div class="api-stat"><small>Revoked</small><b>{counts['revoked']:,}</b></div><div class="api-stat"><small>Expired</small><b>{counts['expired']:,}</b></div><div class="api-stat"><small>Requests 24h</small><b>{counts['requests_24h']:,}</b></div><div class="api-stat"><small>HTTP errors 24h</small><b>{counts['errors_24h']:,}</b></div><div class="api-stat"><small>Auth denials 24h</small><b>{counts['denied_24h']:,}</b></div></div>
    {_v48120_api_nav(tab,counts)}{f'<div class="success-box">{escape(msg)}</div>' if msg else ''}{f'<div class="error-box">{escape(err)}</div>' if err else ''}{once_html}{content_tab}'''
    return page('API Management',content)


app.view_functions['admin_api_keys_page'] = _v48120_admin_api_keys_page


@app.route('/admin/api-keys/delete',methods=['POST'])
def admin_api_key_delete():
    auth=require_admin()
    if auth: return auth
    key_id=str(request.form.get('key_id') or '').strip().lower(); expected=f'DELETE {key_id}'; actor=_api_admin_actor()
    if request.form.get('confirm_text') != expected:
        return _api_admin_redirect(err=f'Confirmation text must be {expected}')
    conn=db()
    try:
        conn.execute('BEGIN IMMEDIATE'); key=_api_get_key_by_id(conn,key_id)
        if not key: raise ValueError('API key not found.')
        access=safe_int(conn.execute('SELECT COUNT(*) FROM api_access_logs WHERE key_id=?',(key_id,)).fetchone()[0],0)
        events=safe_int(conn.execute('SELECT COUNT(*) FROM api_key_events WHERE key_id=?',(key_id,)).fetchone()[0],0)
        conn.execute('DELETE FROM api_access_logs WHERE key_id=?',(key_id,)); conn.execute('DELETE FROM api_key_events WHERE key_id=?',(key_id,)); conn.execute('DELETE FROM api_keys WHERE key_id=?',(key_id,)); conn.commit()
    except Exception as exc:
        conn.rollback(); return _api_admin_redirect(err=str(exc)[:500])
    finally: conn.close()
    with _api_last_used_lock:
        for k in [x for x in _api_last_used_cache if x[0]==key_id]: _api_last_used_cache.pop(k,None)
    with _api_rate_lock:
        for k in [x for x in _api_rate_windows if x[0]==key_id]: _api_rate_windows.pop(k,None)
    log_account_event('api_key_deleted_permanently',username=actor,realm='admin',role='admin',detail=f'key_id={key_id};name={key.get("name")};access_logs={access};events={events}'[:500])
    return _api_admin_redirect(msg=f'API key {key.get("name")} and {access+events:,} related log row(s) were permanently deleted.')


def _v48120_delete_ids(conn,table,ids):
    clean=[]
    for value in ids or []:
        n=safe_int(value,0)
        if n>0 and n not in clean: clean.append(n)
    if not clean: return 0
    marks=','.join('?' for _ in clean); cur=conn.execute(f'DELETE FROM {table} WHERE id IN ({marks})',clean); return max(0,safe_int(cur.rowcount,0))


@app.route('/admin/api-logs/clear',methods=['POST'])
def admin_api_logs_clear():
    auth=require_admin()
    if auth: return auth
    kind=str(request.form.get('kind') or '').strip().lower(); mode=str(request.form.get('mode') or '').strip().lower(); actor=_api_admin_actor()
    if kind not in {'access','events'} or mode not in {'selected','filtered','all'}:
        return _api_admin_redirect(err='Invalid API log cleanup request.')
    table='api_access_logs' if kind=='access' else 'api_key_events'; deleted=0
    conn=db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        if mode=='selected':
            deleted=_v48120_delete_ids(conn,table,request.form.getlist('ids'))
        elif mode=='all':
            if request.form.get('confirm_text')!='CLEAR ALL API LOGS': raise ValueError('Confirmation text must be CLEAR ALL API LOGS')
            cur=conn.execute(f'DELETE FROM {table}'); deleted=max(0,safe_int(cur.rowcount,0)); _v48120_reset_sequences(conn,[table])
        else:
            if request.form.get('confirm_text')!='CLEAR FILTERED': raise ValueError('Confirmation text must be CLEAR FILTERED')
            if kind=='access':
                # Build the same safe filter explicitly for POST form values.
                q=str(request.form.get('q') or '').strip(); status=str(request.form.get('status') or '').strip().lower(); kid=str(request.form.get('key_id_filter') or '').strip().lower(); where=[]; params=[]
                if q:
                    p=like_pattern(q); where.append('(key_name LIKE ? OR key_id LIKE ? OR source_ip LIKE ? OR path LIKE ? OR request_id LIKE ? OR user_agent LIKE ?)'); params.extend([p,p,p,p,p,p])
                if kid: where.append('key_id=?'); params.append(kid)
                if status=='2xx': where.append('status_code BETWEEN 200 AND 299')
                elif status=='3xx': where.append('status_code BETWEEN 300 AND 399')
                elif status=='4xx': where.append('status_code BETWEEN 400 AND 499')
                elif status=='5xx': where.append('status_code>=500')
            else:
                q=str(request.form.get('q') or '').strip(); et=str(request.form.get('event_type_filter') or '').strip().upper(); where=[]; params=[]
                if q:
                    p=like_pattern(q); where.append('(key_name LIKE ? OR key_id LIKE ? OR actor LIKE ? OR source_ip LIKE ? OR detail LIKE ?)'); params.extend([p,p,p,p,p])
                if et: where.append('event_type=?'); params.append(et)
            where_sql=(' WHERE '+' AND '.join(where)) if where else ''
            cur=conn.execute(f'DELETE FROM {table}{where_sql}',params); deleted=max(0,safe_int(cur.rowcount,0))
        conn.commit()
    except Exception as exc:
        conn.rollback(); return _api_admin_redirect(err=str(exc)[:500])
    finally: conn.close()
    log_account_event('api_logs_cleared',username=actor,realm='admin',role='admin',detail=f'kind={kind};mode={mode};deleted={deleted}'[:500])
    return redirect(url_for('admin_api_keys_page',tab='requests' if kind=='access' else 'events',apimsg=f'Deleted {deleted:,} API log row(s).'))


# --------------------------- Maintenance integration ----------------------
_v48120_enqueue_maintenance_base = enqueue_maintenance_job


def enqueue_maintenance_job(action, parameters, actor):
    action=str(action or '').strip().lower()
    if action not in {'clear_api_logs','clear_api_data'}:
        return _v48120_enqueue_maintenance_base(action,parameters,actor)
    runner=os.path.join(os.path.dirname(os.path.abspath(__file__)),'maintenance.py')
    if not os.path.isfile(runner): raise RuntimeError(f'Maintenance runner is missing: {runner}')
    systemctl=shutil.which('systemctl')
    if not systemctl: raise RuntimeError('systemctl is not installed')
    template_path='/etc/systemd/system/bw-monitor-maintenance@.service'
    if not os.path.isfile(template_path): raise RuntimeError(f'Maintenance service template is missing: {template_path}')
    conn=db()
    try:
        stale_before=now_ts()-24*3600
        conn.execute("UPDATE maintenance_jobs SET status='error',finished_at=?,message='Recovered stale queued/running maintenance job' WHERE status IN ('queued','running') AND created_at<?",(now_ts(),stale_before))
        active=safe_int(conn.execute("SELECT COUNT(*) FROM maintenance_jobs WHERE status IN ('queued','running')").fetchone()[0],0)
        if active>=MAX_ACTIVE_MAINTENANCE_JOBS: raise RuntimeError(f'Maintenance queue is full ({active} active jobs)')
        cur=conn.execute("INSERT INTO maintenance_jobs(created_at,action,parameters,status,requested_by,message) VALUES(?,?,?,'queued',?,'Waiting for maintenance worker')",(now_ts(),action,json.dumps(parameters or {},separators=(',',':')),actor or 'admin'))
        job_id=int(cur.lastrowid); unit_name=f'bw-monitor-maintenance@{job_id}.service'; conn.execute('UPDATE maintenance_jobs SET unit_name=? WHERE id=?',(unit_name,job_id)); conn.commit()
    finally: conn.close()
    proc=subprocess.run([systemctl,'--no-block','start',unit_name],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=20,check=False)
    if proc.returncode!=0:
        msg=(proc.stdout or 'systemctl start failed').strip()[:1000]; conn=db()
        try: conn.execute("UPDATE maintenance_jobs SET status='error',finished_at=?,message=? WHERE id=?",(now_ts(),msg,job_id)); conn.commit()
        finally: conn.close()
        raise RuntimeError(msg)
    return job_id,unit_name


_v48120_admin_database_maintenance_base = admin_database_maintenance


def _v48120_admin_database_maintenance():
    action=(request.form.get('action') or '').strip().lower()
    if action not in {'clear_api_logs','clear_api_data'}:
        return _v48120_admin_database_maintenance_base()
    deny=require_admin()
    if deny: return deny
    actor=dashboard_username() or get_admin_username(); parameters={}
    try:
        if action=='clear_api_logs':
            if (request.form.get('confirm_text') or '').strip()!='CLEAR API LOGS': raise ValueError('Confirmation text must be CLEAR API LOGS')
            parameters['kind']='all'; parameters['compact']=False
        else:
            if (request.form.get('confirm_text') or '').strip()!='CLEAR ALL API DATA': raise ValueError('Confirmation text must be CLEAR ALL API DATA')
            parameters['compact']=False
        job_id,unit_name=enqueue_maintenance_job(action,parameters,actor); msg=f'Started maintenance job #{job_id} ({action}) as {unit_name}.'
        log_account_event('database_maintenance_queued',username=actor,realm='admin',role='admin',detail=msg)
        return redirect(url_for('admin_page',dbmsg=msg)+'#maintenance-queue')
    except Exception as exc:
        err=f'Could not start maintenance: {exc}'; log_account_event('database_maintenance_queue_failed',username=actor,realm='admin',role='admin',detail=err[:500]); return redirect(url_for('admin_page',dberr=err)+'#maintenance-queue')


app.view_functions['admin_database_maintenance'] = _v48120_admin_database_maintenance


_v48120_maintenance_card_base = database_maintenance_card


def database_maintenance_card(message="", error=""):
    """Render the PostgreSQL-native maintenance control surface."""
    stats = get_database_maintenance_stats()
    jobs = get_maintenance_jobs(30)
    conn = db()
    try:
        status_rows = conn.execute(
            "SELECT status,COUNT(*) FROM maintenance_jobs GROUP BY status"
        ).fetchall()
        status_counts = {str(k or "queued"): safe_int(v, 0) for k, v in status_rows}
    finally:
        conn.close()

    active_count = status_counts.get("queued", 0) + status_counts.get("starting", 0) + status_counts.get("running", 0)
    notice = (
        f'<div class="error-box">{escape(error)}</div>'
        if error
        else (f'<div class="success-box">{escape(message)}</div>' if message else "")
    )

    rows = ""
    for (
        job_id, created_at, started_at, finished_at, action, parameters,
        status, requested_by, job_message, unit_name,
    ) in jobs:
        status = str(status or "queued").lower()
        label = {"queued": "WAITING", "starting": "STARTING", "running": "RUNNING", "ok": "DONE", "error": "FAILED", "cancelled": "CANCELLED"}.get(status, status.upper())
        icon = {"queued": "◷", "starting": "◌", "running": "◉", "ok": "✓", "error": "!", "cancelled": "×"}.get(status, "•")
        cls = {"queued": "yellow", "starting": "yellow", "running": "yellow", "ok": "active", "error": "red", "cancelled": "red"}.get(status, "yellow")
        target = _maintenance_target_summary(action, parameters)
        friendly = _maintenance_friendly_message(action, status, job_message)
        raw_detail = escape((job_message or "-")[:3500])
        rows += f"""
        <tr class="queue-row queue-{escape(status)}">
          <td class="num"><b>#{job_id}</b></td>
          <td><b>{escape(_maintenance_action_label(action))}</b><small class="queue-sub">{escape(target)}</small></td>
          <td><span class="vm-state {cls}">{icon} {escape(label)}</span></td>
          <td>{fmt_full(created_at)}<small class="queue-sub">{escape(_maintenance_elapsed(started_at, finished_at, created_at, status))}</small></td>
          <td>{escape(requested_by or '-')}</td>
          <td><b>{escape(friendly)}</b><details><summary>Technical detail</summary><pre>{raw_detail}</pre><small class="mono">{escape(unit_name or '-')}</small></details></td>
        </tr>"""
    if not rows:
        rows = '<tr><td colspan="6" class="empty">No maintenance jobs yet</td></tr>'

    csrf = escape(csrf_token(), quote=True)
    endpoint = url_for("admin_database_maintenance")
    refresh_href = url_for("admin_page", section="maintenance") + "#maintenance-queue"

    return f"""
    <style id="v5056-maintenance-ui">
      .maint-grid{{display:grid;grid-template-columns:repeat(2,minmax(320px,1fr));gap:14px;margin:14px 0}}
      .maint-grid .card{{margin:0!important}}
      .maint-safe{{border-color:#86b7fe!important}}
      .maint-danger{{border:1px solid #fca5a5!important}}
      .maint-nuclear{{border:2px solid #b91c1c!important}}
      .maint-actions{{display:flex;flex-wrap:wrap;gap:8px;align-items:end}}
      .maint-actions form{{display:flex;flex-wrap:wrap;gap:8px;align-items:end}}
      .maint-actions label{{display:grid;gap:4px}}
      .maint-policy{{display:grid;grid-template-columns:repeat(3,minmax(150px,1fr));gap:8px;margin:10px 0}}
      .maint-policy>div,.queue-summary>div{{border:1px solid #dbe3ee;border-radius:10px;padding:10px;background:#fff}}
      .maint-policy small,.queue-sub,.queue-summary small{{display:block;color:#64748b;font-size:11px;margin-top:3px}}
      .queue-summary{{display:grid;grid-template-columns:repeat(5,minmax(110px,1fr));gap:8px;margin:12px 0}}
      .queue-table{{min-width:1120px}}.queue-table td{{vertical-align:top}}
      .queue-table details{{margin-top:5px}}.queue-table summary{{cursor:pointer;color:#2563eb;font-size:11px}}
      .queue-table pre{{white-space:pre-wrap;max-width:650px;max-height:180px;overflow:auto;font-size:10px}}
      html[data-theme=dark] .maint-policy>div,html[data-theme=dark] .queue-summary>div{{background:#111827;border-color:#334155}}
      @media(max-width:980px){{.maint-grid{{grid-template-columns:1fr}}.maint-policy{{grid-template-columns:1fr}}.queue-summary{{grid-template-columns:repeat(2,minmax(110px,1fr))}}}}
    </style>

    <div class="card" id="maintenance-queue">
      <div class="table-title-row"><h3>PostgreSQL Maintenance</h3><div class="count-badges"><span>Execution <b>single worker</b></span><span>Active <b>{active_count}</b></span></div></div>
      {notice}
      <div class="admin-note"><b>FIFO queue with one worker.</b> Multiple routine jobs may wait safely. The dispatcher atomically starts only one worker, records heartbeat, recovers dead units, and automatically runs the next job. Nuclear reset never waits in the queue.</div>
      <div class="queue-summary">
        <div><small>Waiting</small><b>{status_counts.get('queued', 0)}</b></div>
        <div><small>Starting</small><b>{status_counts.get('starting', 0)}</b></div>
        <div><small>Running</small><b>{status_counts.get('running', 0)}</b></div>
        <div><small>Completed</small><b>{status_counts.get('ok', 0)}</b></div>
        <div><small>Failed</small><b>{status_counts.get('error', 0)}</b></div>
        <div><small>Cancelled</small><b>{status_counts.get('cancelled', 0)}</b></div>
        <div><small>PostgreSQL data</small><b>{human(stats['db_size'])}</b></div>
      </div>
      <div class="bulk-bar"><a class="btn" href="{escape(refresh_href, quote=True)}">Refresh queue</a><span class="table-hint">WAL reserved/recycled {human(stats['wal_size'])}. Normal VACUUM reuses dead space but does not promise a smaller database file.</span></div>
    </div>

    <div class="maint-policy">
      <div><b>Latest 48 hours</b><small>Keep every real 5-minute snapshot.</small></div>
      <div><b>Days 3–7</b><small>Keep one real snapshot per local hour.</small></div>
      <div><b>Older than 7 days</b><small>Delete bounded history, events and logs.</small></div>
    </div>

    <div class="maint-grid">
      <div class="card maint-safe">
        <h3>Routine retention</h3>
        <div class="admin-note">Runs the same bounded policy as <code>bw-monitor-retention.timer</code>. Dashboard and Agent ingestion remain online.</div>
        <div class="maint-actions">
          <form method="post" action="{endpoint}" onsubmit="return confirm('Run the normal 2-day raw / 7-day retention policy now?')">
            <input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="retention">
            <button class="btn" type="submit">Run retention now</button>
          </form>
        </div>
      </div>

      <div class="card maint-safe">
        <h3>VACUUM ANALYZE</h3>
        <div class="admin-note">Online PostgreSQL VACUUM with no maintenance statement timeout. It refreshes planner statistics and makes dead tuples reusable. It does not stop the dashboard and is not VACUUM FULL.</div>
        <div class="maint-actions">
          <form method="post" action="{endpoint}" onsubmit="return confirm('Run online PostgreSQL VACUUM ANALYZE?')">
            <input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="vacuum">
            <label>Type <b>VACUUM</b><input name="confirm_text" placeholder="VACUUM" required></label>
            <button class="btn" type="submit">Run online VACUUM</button>
          </form>
        </div>
      </div>

      <div class="card maint-safe">
        <h3>Manual history cleanup</h3>
        <div class="admin-note">Deletes history older than the selected age in committed batches while the web remains available. Current/latest tables and inventory are preserved.</div>
        <div class="maint-actions">
          <form method="post" action="{endpoint}" onsubmit="return confirm('Delete old history only?')">
            <input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="delete_history">
            <label>Older than<select name="days"><option value="1">1 day</option><option value="3">3 days</option><option value="7" selected>7 days</option></select></label>
            <label>Type <b>DELETE HISTORY</b><input name="confirm_text" placeholder="DELETE HISTORY" required></label>
            <button class="btn" type="submit">Delete history</button>
          </form>
        </div>
      </div>

      <div class="card maint-safe">
        <h3>Delete history + VACUUM</h3>
        <div class="admin-note">Runs the same online batched deletion, then online VACUUM ANALYZE. No intentional Agent outage.</div>
        <div class="maint-actions">
          <form method="post" action="{endpoint}" onsubmit="return confirm('Delete old history and then run online VACUUM ANALYZE?')">
            <input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="delete_compact">
            <label>Older than<select name="days"><option value="1">1 day</option><option value="3">3 days</option><option value="7" selected>7 days</option></select></label>
            <label>Type <b>DELETE AND VACUUM</b><input name="confirm_text" placeholder="DELETE AND VACUUM" required></label>
            <button class="btn" type="submit">Delete + VACUUM</button>
          </form>
        </div>
      </div>

      <div class="card maint-danger">
        <h3>Clear monitoring data</h3>
        <div class="admin-note"><b>Destructive monitoring reset.</b> Briefly stops Monitor, then atomically TRUNCATEs monitoring history, current caches, inventory, node logs and abuse rows. Preserves dashboard users, Admin settings, account logs, API keys/logs and maintenance history. Agents repopulate fresh data after restart.</div>
        <div class="maint-actions">
          <form method="post" action="{endpoint}" onsubmit="return confirm('Permanently clear all monitoring data?')">
            <input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="clear_monitoring_data">
            <label>Type <b>CLEAR ALL MONITORING DATA</b><input name="confirm_text" placeholder="CLEAR ALL MONITORING DATA" required></label>
            <button class="btn-danger" type="submit">Clear monitoring data</button>
          </form>
        </div>
      </div>

      <div class="card maint-nuclear">
        <h3>Reset ALL app data + queue</h3>
        <div class="admin-note"><b>Nuclear operational reset.</b> Briefly stops Monitor and TRUNCATEs monitoring data, inventory, abuse policy history, account logs, API keys/logs and old maintenance rows. Preserves only dashboard users, Admin settings and schema metadata. Agent token is unchanged.</div>
        <div class="maint-actions">
          <form method="post" action="{endpoint}" onsubmit="return confirm('Reset all operational app data and clear the maintenance queue?')">
            <input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="reset_app_data">
            <label>Type <b>RESET ALL APP DATA</b><input name="confirm_text" placeholder="RESET ALL APP DATA" required></label>
            <button class="btn-danger" type="submit">Reset app data + queue</button>
          </form>
        </div>
      </div>

      <div class="card maint-danger">
        <h3>API logs</h3>
        <div class="admin-note">TRUNCATEs API request logs and API management events. API keys remain active. The Agent token is unrelated and remains unchanged.</div>
        <div class="maint-actions">
          <form method="post" action="{endpoint}" onsubmit="return confirm('Clear all API logs?')">
            <input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="clear_api_logs">
            <label>Type <b>CLEAR API LOGS</b><input name="confirm_text" placeholder="CLEAR API LOGS" required></label>
            <button class="btn-danger" type="submit">Clear API logs</button>
          </form>
        </div>
      </div>

      <div class="card maint-nuclear">
        <h3>All external API data</h3>
        <div class="admin-note"><b>External integrations stop immediately.</b> TRUNCATEs API keys, request logs and management events. The Agent <code>BW_MONITOR_TOKEN</code> remains unchanged.</div>
        <div class="maint-actions">
          <form method="post" action="{endpoint}" onsubmit="return confirm('Delete all external API keys and API logs?')">
            <input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="clear_api_data">
            <label>Type <b>CLEAR ALL API DATA</b><input name="confirm_text" placeholder="CLEAR ALL API DATA" required></label>
            <button class="btn-danger" type="submit">Clear all API data</button>
          </form>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="table-title-row"><h3>Recent maintenance jobs</h3></div>
      <div class="table-wrap"><table class="queue-table"><thead><tr><th>ID</th><th>ACTION / TARGET</th><th>STATUS</th><th>CREATED / ELAPSED</th><th>REQUESTED BY</th><th>RESULT</th></tr></thead><tbody>{rows}</tbody></table></div>
    </div>
    """


def _v5056_admin_clear_live_cache_removed():
    """Retire the old live-cache action without deleting any current data."""
    deny = require_admin()
    if deny:
        return deny
    message = (
        "CLEAR LIVE 5M was removed in 50.5.6. Current snapshots were not changed. "
        "Use targeted VM/node purge for stale inventory or wait for the next Agent push."
    )
    return redirect(
        url_for("admin_page", section="maintenance", dbmsg=message)
        + "#maintenance-queue"
    )


app.view_functions["admin_clear_live_cache"] = _v5056_admin_clear_live_cache_removed


_v48120_action_label_base = _maintenance_action_label
_v48120_target_summary_base = _maintenance_target_summary
_v48120_friendly_message_base = _maintenance_friendly_message


def _maintenance_action_label(action):
    labels = {
        "retention": "Run retention",
        "vacuum": "Online VACUUM ANALYZE",
        "delete_history": "Delete old history",
        "delete_compact": "Delete history + VACUUM",
        "clear_monitoring_data": "Clear monitoring data",
        "reset_app_data": "Reset all app data + queue",
        "purge_nodes": "Purge node",
        "purge_node_vms": "Purge all VMs on node",
        "purge_vms": "Purge VM",
        "clear_api_logs": "Clear API logs",
        "clear_api_data": "Clear all API data",
        # Historical queue rows from releases before 50.5.6 remain readable.
        "checkpoint": "Legacy database status",
        "clear_live_cache": "Legacy current-cache clear",
    }
    return labels.get(str(action or "").strip().lower(), str(action or "-").replace("_", " ").title())


def _v48122_parse_maintenance_parameters(parameters):
    """Normalize maintenance parameters from DB JSON text or an in-memory dict.

    maintenance_jobs.parameters is persisted as JSON TEXT. The queue renderer
    passes that raw value to _maintenance_target_summary(), while a few tests
    and helper paths may pass an already-decoded dict. Accept both forms so a
    newly queued API cleanup job can never break the Admin page.
    """
    if isinstance(parameters, dict):
        return parameters
    if parameters in (None, ""):
        return {}
    try:
        decoded = json.loads(str(parameters))
    except Exception:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _maintenance_target_summary(action,parameters):
    action = str(action or '').strip().lower()
    if action in {'clear_api_logs','clear_api_data'}:
        params = _v48122_parse_maintenance_parameters(parameters)
        suffix = ' + VACUUM' if bool(params.get('compact')) else ''
        if action == 'clear_api_logs':
            kind = str(params.get('kind') or 'all').strip().lower()
            target = {
                'access': 'API Request Logs',
                'events': 'API Management Events',
                'all': 'Request Logs + Management Events',
            }.get(kind, 'Request Logs + Management Events')
            return target + suffix
        return 'All external API keys + all API logs' + suffix
    return _v48120_target_summary_base(action,parameters)


def _maintenance_friendly_message(action, status, message):
    action = str(action or "").strip().lower()
    status = str(status or "").strip().lower()
    if status == "queued":
        return "Waiting for the serialized maintenance worker"
    if status == "running":
        return "Worker is processing this job"
    if status == "ok":
        try:
            data = json.loads(str(message or "{}")) if not isinstance(message, dict) else message
            if action in {"clear_api_logs", "clear_api_data"}:
                result = (data or {}).get("clear") or (data or {}).get("result") or {}
                rows = safe_int(result.get("estimated_rows_removed", result.get("total_deleted", 0)), 0)
                return f"{'API data' if action == 'clear_api_data' else 'API logs'} cleared · approximately {rows:,} row(s)"
            if action == "vacuum":
                return "Online VACUUM ANALYZE completed"
            if action == "delete_compact":
                return "History cleanup and online VACUUM completed"
            if action == "delete_history":
                return "History cleanup completed"
            if action == "clear_monitoring_data":
                return "Monitoring tables truncated and service restarted"
            if action == "reset_app_data":
                return "Operational data reset and maintenance queue cleared"
            if action == "retention":
                return "Bounded retention completed"
            if action in {"purge_nodes", "purge_node_vms", "purge_vms"}:
                result = (data or {}).get("result", data or {})
                return f"Completed {safe_int(result.get('count'), 0)} item(s)"
            return "Completed successfully"
        except Exception:
            return "Completed successfully"
    return str(message or "Job failed")[:240]



# ---------------------------------------------------------------------------
