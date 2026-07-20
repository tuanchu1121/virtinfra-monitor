def _v5057_agent_tokens():
    values = [str(TOKEN or "").strip()]
    legacy = str(os.environ.get("BW_MONITOR_LEGACY_TOKENS", "") or "")
    values.extend(part.strip() for part in re.split(r"[\s,]+", legacy))
    return tuple(dict.fromkeys(value for value in values if value))

V5057_AGENT_TOKENS = _v5057_agent_tokens()
V5057_OPERATIONAL_PUSH_ACCEPT_AFTER = max(
    0,
    safe_int(get_admin_setting("operational_push_accept_after", "0"), 0),
)

def valid_agent_token(value):
    supplied = str(value or "")
    return any(hmac.compare_digest(supplied, expected) for expected in V5057_AGENT_TOKENS)

V5057_VERSION = "50.5.9-prod-r14-purge-queue-visibility-hotfix"

def enqueue_maintenance_job(action, parameters, actor):
    payload = dict(parameters or {})
    payload.setdefault("requested_by", actor or "admin")
    exclusive = str(action or "").strip().lower() == "reset_app_data"
    return maintenance_queue.enqueue_job(
        action,
        payload,
        actor or "admin",
        exclusive=exclusive,
    )

def _v5057_queue_has_pending_jobs():
    conn = db()
    try:
        row = conn.execute(
            "SELECT id,action,status FROM maintenance_jobs "
            "WHERE status IN ('queued','starting','running') ORDER BY id LIMIT 1"
        ).fetchone()
        return row
    finally:
        conn.close()

def _v5057_verify_current_admin_password(password):
    row = current_dashboard_user()
    if not row or str(row[3] or "") not in {"admin", "super_admin"} or not safe_int(row[4], 0):
        return False
    return bool(password) and check_password_hash(str(row[2] or ""), str(password))

@app.route("/admin/maintenance/cancel", methods=["POST"])
def admin_cancel_maintenance_v5057():
    deny = require_admin()
    if deny:
        return deny
    job_id = safe_int(request.form.get("job_id"), 0)
    actor = dashboard_username() or get_admin_username()
    if job_id <= 0:
        return redirect(url_for("admin_page", section="maintenance", dberr="Invalid maintenance job id") + "#maintenance-queue")
    changed = maintenance_queue.cancel_queued_job(job_id, actor)
    message = f"Cancelled waiting maintenance job #{job_id}." if changed else f"Job #{job_id} is no longer waiting and was not cancelled."
    log_account_event(
        "maintenance_job_cancelled" if changed else "maintenance_job_cancel_skipped",
        username=actor, realm="admin", role="admin", detail=message,
    )
    maintenance_queue.wake_dispatcher()
    return redirect(url_for("admin_page", section="maintenance", dbmsg=message) + "#maintenance-queue")

_v5057_admin_database_maintenance_base = app.view_functions.get("admin_database_maintenance")

def admin_database_maintenance_v5057():
    action = str(request.form.get("action") or "").strip().lower()
    role = current_role() if "current_role" in globals() else dashboard_role()
    routine_actions = {"retention", "vacuum", "delete_history", "delete_compact"}
    if action not in {"reset_app_data_preview", "reset_app_data"}:
        if role == "admin" and action not in routine_actions:
            return Response("Forbidden: super_admin role required for destructive maintenance\n", status=403, mimetype="text/plain")
        return _v5057_admin_database_maintenance_base()
    if role != "super_admin":
        return Response("Forbidden: super_admin role required for nuclear reset\n", status=403, mimetype="text/plain")

    deny = require_admin()
    if deny:
        return deny
    actor = dashboard_username() or get_admin_username()
    try:
        if action == "reset_app_data_preview":
            if not _v5057_verify_current_admin_password(request.form.get("admin_password") or ""):
                raise ValueError("Admin password verification failed")
            pending = _v5057_queue_has_pending_jobs()
            if pending:
                raise RuntimeError(
                    f"Queue must be empty before nuclear preview: job #{pending[0]} "
                    f"({pending[1]}) is {pending[2]}"
                )
            preview = maintenance_native.preview_reset_app_data()
            nonce = secrets.token_urlsafe(24)
            code = f"{secrets.randbelow(900000) + 100000:06d}"
            preview_now = now_ts()
            session["v5057_nuclear_preview"] = {
                "nonce": nonce,
                "code": code,
                "not_before": preview_now + 15,
                "expires_at": preview_now + 300,
                "created_at": preview_now,
                "table_count": safe_int(preview.get("table_count"), 0),
                "estimated_rows": safe_int(preview.get("estimated_rows"), 0),
                "estimated_bytes": safe_int(preview.get("estimated_bytes"), 0),
                "database_bytes": safe_int(preview.get("database_bytes"), 0),
            }
            log_account_event(
                "nuclear_reset_preview",
                username=actor, realm="admin", role="admin",
                detail=(
                    f"tables={preview.get('table_count', 0)};"
                    f"estimated_rows={preview.get('estimated_rows', 0)};"
                    f"estimated_bytes={preview.get('estimated_bytes', 0)}"
                ),
            )
            return redirect(url_for("admin_page", section="maintenance", dbmsg="Nuclear preview created. Review it and confirm within 5 minutes.") + "#maintenance-queue")

        preview = session.get("v5057_nuclear_preview") or {}
        if not isinstance(preview, dict):
            preview = {}
        request_now = now_ts()
        if safe_int(preview.get("expires_at"), 0) < request_now:
            session.pop("v5057_nuclear_preview", None)
            raise ValueError("Nuclear preview expired. Create a new preview")
        not_before = safe_int(preview.get("not_before"), 0)
        if not_before and request_now < not_before:
            raise ValueError(
                f"Nuclear safety delay is still active for {not_before - request_now} second(s)"
            )
        nonce = str(request.form.get("preview_nonce") or "")
        if not nonce or not secrets.compare_digest(nonce, str(preview.get("nonce") or "")):
            raise ValueError("Nuclear preview token mismatch")
        if not _v5057_verify_current_admin_password(request.form.get("admin_password") or ""):
            raise ValueError("Admin password verification failed")
        required = f"RESET VIRTINFRA {preview.get('code', '')}"
        if str(request.form.get("confirm_text") or "").strip() != required:
            raise ValueError(f"Confirmation text must be {required}")
        pending = _v5057_queue_has_pending_jobs()
        if pending:
            raise RuntimeError(
                f"Nuclear reset cannot wait in FIFO: job #{pending[0]} "
                f"({pending[1]}) is {pending[2]}"
            )
        parameters = {
            "requested_by": actor,
            "preview_created_at": safe_int(preview.get("created_at"), 0),
            "preview_table_count": safe_int(preview.get("table_count"), 0),
            "preview_estimated_rows": safe_int(preview.get("estimated_rows"), 0),
            "mandatory_verified_backup": True,
            "preserve_queue_audit": True,
        }
        job_id, unit_name = maintenance_queue.enqueue_job(
            "reset_app_data", parameters, actor, exclusive=True
        )
        session.pop("v5057_nuclear_preview", None)
        message = (
            f"Nuclear reset job #{job_id} accepted for immediate execution. "
            "It will abort before TRUNCATE unless a verified backup succeeds."
        )
        log_account_event(
            "nuclear_reset_queued", username=actor, realm="admin", role="admin",
            detail=f"job={job_id};unit={unit_name}",
        )
        return redirect(url_for("admin_page", section="maintenance", dbmsg=message) + "#maintenance-queue")
    except Exception as exc:
        error = f"Nuclear reset was not started: {exc}"
        log_account_event(
            "nuclear_reset_rejected", username=actor, realm="admin", role="admin",
            detail=error[:500],
        )
        return redirect(url_for("admin_page", section="maintenance", dberr=error) + "#maintenance-queue")

app.view_functions["admin_database_maintenance"] = admin_database_maintenance_v5057

_v5057_database_maintenance_card_base = database_maintenance_card

def database_maintenance_card(message="", error=""):
    html = _v5057_database_maintenance_card_base(message, error)
    preview = session.get("v5057_nuclear_preview") or {}
    valid_preview = isinstance(preview, dict) and safe_int(preview.get("expires_at"), 0) >= now_ts()
    csrf = escape(csrf_token(), quote=True)
    endpoint = escape(url_for("admin_database_maintenance"), quote=True)
    if valid_preview:
        code = str(preview.get("code") or "")
        nuclear = f'''
      <div class="card maint-nuclear">
        <h3>Nuclear reset preview ready</h3>
        <div class="admin-note"><b>No data has been deleted.</b> Final confirmation is accepted after {fmt_full(preview.get('not_before'))} and expires at {fmt_full(preview.get('expires_at'))}. The job cannot wait behind another task and must create a verified PostgreSQL backup before any TRUNCATE.</div>
        <div class="maint-policy">
          <div><b>{safe_int(preview.get('table_count'),0)} tables</b><small>Explicit allow-list only</small></div>
          <div><b>{safe_int(preview.get('estimated_rows'),0):,} rows</b><small>PostgreSQL estimate</small></div>
          <div><b>{human(safe_int(preview.get('estimated_bytes'),0))}</b><small>Estimated relation size</small></div>
        </div>
        <div class="maint-actions">
          <form method="post" action="{endpoint}" onsubmit="return confirm('Final confirmation: create a verified backup and permanently reset operational app data?')">
            <input type="hidden" name="csrf_token" value="{csrf}">
            <input type="hidden" name="action" value="reset_app_data">
            <input type="hidden" name="preview_nonce" value="{escape(str(preview.get('nonce') or ''), quote=True)}">
            <label>Admin password<input type="password" name="admin_password" autocomplete="current-password" required></label>
            <label>Type <b>RESET VIRTINFRA {escape(code)}</b><input name="confirm_text" placeholder="RESET VIRTINFRA {escape(code)}" required></label>
            <button class="btn-danger" type="submit">Backup, verify, then reset</button>
          </form>
        </div>
      </div>'''
    else:
        nuclear = f'''
      <div class="card maint-nuclear">
        <h3>Nuclear operational reset</h3>
        <div class="admin-note"><b>Two-step safety workflow.</b> First re-enter the Admin password to create a read-only preview. Final execution requires a new one-time phrase, an empty queue and a verified backup. Dashboard users, Admin settings, queue history, nuclear audit and schema metadata are preserved.</div>
        <div class="maint-actions">
          <form method="post" action="{endpoint}">
            <input type="hidden" name="csrf_token" value="{csrf}">
            <input type="hidden" name="action" value="reset_app_data_preview">
            <label>Admin password<input type="password" name="admin_password" autocomplete="current-password" required></label>
            <button class="btn-danger" type="submit">Create reset preview</button>
          </form>
        </div>
      </div>'''

    if clean_role(dashboard_role()) != "super_admin":
        nuclear = '''
      <div class="card maint-nuclear">
        <h3>Nuclear operational reset</h3>
        <div class="admin-note"><b>Super Admin only.</b> Routine retention, 2/7-day history cleanup, online VACUUM and queue monitoring remain available to Admin accounts.</div>
      </div>'''

    start_marker = '<div class="card maint-nuclear">\n        <h3>Reset ALL app data + queue</h3>'
    end_marker = '<div class="card maint-danger">\n        <h3>API logs</h3>'
    start = html.find(start_marker)
    end = html.find(end_marker, start + 1) if start >= 0 else -1
    if start >= 0 and end > start:
        html = html[:start] + nuclear + "\n\n      " + html[end:]

    # Add a Cancel button only for waiting jobs. The dispatcher/worker state is
    # immutable once execution starts.
    def add_cancel(match):
        job_id = match.group(1)
        block = match.group(0)
        if "queue-queued" not in block:
            return block
        form = (
            f'<form method="post" action="{escape(url_for("admin_cancel_maintenance_v5057"), quote=True)}" '
            f'onsubmit="return confirm(\'Cancel waiting job #{job_id}?\')" style="margin-top:6px">'
            f'<input type="hidden" name="csrf_token" value="{csrf}">'
            f'<input type="hidden" name="job_id" value="{job_id}">'
            f'<button class="btn-danger" type="submit">Cancel waiting job</button></form>'
        )
        return block.replace("</td>\n        </tr>", form + "</td>\n        </tr>", 1)

    try:
        import re as _re_v5057
        html = _re_v5057.sub(
            r'<tr class="queue-row queue-[^"]+">.*?<td class="num"><b>#(\d+)</b></td>.*?</tr>',
            add_cancel,
            html,
            flags=_re_v5057.S,
        )
    except Exception:
        pass
    try:
        item = _v5030_bandwidth_admin_stats()
        token = escape(csrf_token(), quote=True)
        accounting = """
      <div class="card admin-section" id="accounting-storage">
        <div class="section-head"><div><span class="eyebrow">MAINTENANCE</span><h3>2-hour Node Accounting Storage</h3><p>Direct idempotent ingestion. No monitor-side queue and no per-VM UUID rows.</p></div><a class="btn" href="%s">Open Consumption</a></div>
        <div class="admin-kpis"><div><small>RETENTION</small><b>7 days</b></div><div><small>ROWS</small><b>%s</b></div><div><small>TABLE + INDEX</small><b>%s</b></div><div><small>REPORTING VISIBLE NODES</small><b>%s / %s</b></div><div><small>MISSING</small><b>%s</b></div><div><small>LAST INGESTION</small><b>%s</b></div><div><small>OLDEST BUCKET</small><b>%s</b></div><div><small>NEWEST BUCKET</small><b>%s</b></div></div>
        <div class="bulk-bar"><form method="post" action="%s"><input type="hidden" name="csrf_token" value="%s"><input type="hidden" name="action" value="cleanup"><button type="submit">Run RETENTION7 cleanup</button></form><form method="post" action="%s" onsubmit="return confirm('Delete all Consumption history?');"><input type="hidden" name="csrf_token" value="%s"><input type="hidden" name="action" value="clear"><input name="confirm_text" placeholder="CLEAR BANDWIDTH HISTORY"><button class="btn-danger" type="submit">Clear accounting history</button></form></div>
        <div class="table-hint">These controls only affect node_bandwidth_consumption_2h. Node Groups, memberships and membership history are configuration data and are not part of RETENTION7.</div>
      </div>
        """ % (url_for("bandwidth_consumption_page"), f"{item['rows']:,}", human(item["size"]), item["reporting"], item["visible_nodes"], item["missing"], fmt_full(item["last_received"]), fmt_full(item["oldest"]), fmt_full(item["newest"]), url_for("admin_bandwidth_consumption_action"), token, url_for("admin_bandwidth_consumption_action"), token)
        html += accounting
    except Exception:
        app.logger.exception("Could not render accounting maintenance card")
    return html

# --- Canonical current VM resolver ----------------------------------------
def resolve_direct_vm_search(q):
    q = str(q or "").strip()
    if not q:
        return None
    like = like_pattern(q)
    normalized_mac = normalize_mac_address(q)
    conn = db()
    try:
        rows = conn.execute("""
          SELECT node,vm_uuid,last_seen,source_rank,exact_uuid
          FROM (
            SELECT node,vm_uuid,last_seen,0 source_rank,
                   CASE WHEN LOWER(vm_uuid)=LOWER(?) THEN 1 ELSE 0 END exact_uuid
              FROM vm_current_fast
             WHERE vm_uuid LIKE ?
            UNION ALL
            SELECT node,vm_uuid,last_seen,1 source_rank,
                   CASE WHEN LOWER(vm_uuid)=LOWER(?) THEN 1 ELSE 0 END exact_uuid
              FROM vm_latest_metrics
             WHERE vm_uuid LIKE ? OR COALESCE(iface,'')=? COLLATE NOCASE
            UNION ALL
            SELECT node,vm_uuid,last_seen,2 source_rank,
                   CASE WHEN LOWER(vm_uuid)=LOWER(?) THEN 1 ELSE 0 END exact_uuid
              FROM vm_location_latest
             WHERE vm_uuid LIKE ? OR COALESCE(last_iface,'')=? COLLATE NOCASE
            UNION ALL
            SELECT node,vm_uuid,last_seen,3 source_rank,
                   CASE WHEN LOWER(vm_uuid)=LOWER(?) THEN 1 ELSE 0 END exact_uuid
              FROM vm_inventory
             WHERE deleted_at IS NULL AND COALESCE(status,'active')!='hidden'
               AND (vm_uuid LIKE ? OR COALESCE(last_iface,'')=? COLLATE NOCASE)
            UNION ALL
            SELECT i.node,i.vm_uuid,i.last_seen,4 source_rank,
                   CASE WHEN l.mac=? THEN 1 ELSE 0 END exact_uuid
              FROM vm_nic_identity_lookup l
              JOIN vm_iface_current i
                ON i.node=l.node AND i.vm_uuid=l.vm_uuid
               AND i.bridge=l.bridge AND i.iface=l.iface AND i.mac=l.mac
              LEFT JOIN vm_inventory vi ON vi.node=i.node AND vi.vm_uuid=i.vm_uuid
             WHERE COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL
               AND (
                    COALESCE(i.iface,'')=? COLLATE NOCASE
                    OR l.mac LIKE ?
                    OR (?<>'' AND l.mac=?)
               )
          ) candidates
          ORDER BY exact_uuid DESC,last_seen DESC,source_rank ASC
          LIMIT 300
        """, (
            q,like,q,like,q,q,like,q,q,like,q,
            normalized_mac,q,like,normalized_mac,normalized_mac,
        )).fetchall()
    finally:
        conn.close()
    if not rows:
        return None
    exact_rows = [r for r in rows if safe_int(r[4],0)==1]
    pool = exact_rows or rows
    unique = {}
    for node,vm_uuid,last_seen,source_rank,exact_uuid in pool:
        key=(str(node or ""),str(vm_uuid or ""))
        if not all(key):
            continue
        candidate={"node":key[0],"vm_uuid":key[1],"last_seen":safe_int(last_seen,0),"source_rank":safe_int(source_rank,99)}
        current=unique.get(key)
        if current is None or (candidate["last_seen"],-candidate["source_rank"]) > (current["last_seen"],-current["source_rank"]):
            unique[key]=candidate
    values=sorted(unique.values(),key=lambda item:(-item["last_seen"],item["source_rank"],item["node"]))
    if exact_rows or len(values)==1:
        result=dict(values[0])
        # Search opens the whole VM. It must not silently inherit one stale NIC.
        result.update({"iface":"","bridge":""})
        return result
    return None

def get_vm_current_location(vm_uuid):
    conn = db()
    try:
        row = conn.execute("""
          SELECT node,last_seen FROM (
            SELECT node,last_seen,0 rank FROM vm_current_fast WHERE vm_uuid=?
            UNION ALL SELECT node,last_seen,1 rank FROM vm_latest_metrics WHERE vm_uuid=?
            UNION ALL SELECT node,last_seen,2 rank FROM vm_location_latest WHERE vm_uuid=?
          ) x ORDER BY last_seen DESC,rank ASC LIMIT 1
        """, (vm_uuid,vm_uuid,vm_uuid)).fetchone()
        if not row:
            return None
        loc = conn.execute("""
          SELECT previous_node,moved_at,move_count,last_iface,last_bridge,alert_flags
          FROM vm_location_latest WHERE vm_uuid=?
        """, (vm_uuid,)).fetchone()
        loc = loc or (None,None,0,"","","")
        return {
            "vm_uuid":vm_uuid,"node":row[0],"last_seen":row[1],
            "previous_node":loc[0],"moved_at":loc[1],"move_count":loc[2],
            "last_iface":loc[3],"last_bridge":loc[4],"alert_flags":loc[5],
        }
    finally:
        conn.close()

_v5057_vm_snapshot_history_base = _v5054_vm_snapshot_overview

def _v5057_live_vm_snapshot(node, vm_uuid, bridge="", iface=""):
    conn = db()
    try:
        current = conn.execute("""
          SELECT last_seen,interval_seconds,iface_count,
                 rx_bytes,tx_bytes,rx_mbps,tx_mbps,rx_peak_mbps,tx_peak_mbps,
                 rx_pps,tx_pps,rx_peak_pps,tx_peak_pps,
                 sample_count,sample_expected,sample_max_gap,sample_quality,
                 seconds_over_rx_pps,seconds_over_tx_pps,drops,errors,
                 cpu_full_percent,cpu_core_percent,vcpu_current,
                 ram_current_kib,ram_rss_kib,ram_available_kib,
                 disk_read_bps,disk_write_bps
            FROM vm_current_fast WHERE node=? AND vm_uuid=?
        """, (node,vm_uuid)).fetchone()
        if not current:
            return None
        if bridge or iface:
            where=["node=?","vm_uuid=?"]
            params=[node,vm_uuid]
            if bridge:
                where.append("bridge=?"); params.append(bridge)
            if iface:
                where.append("iface=?"); params.append(iface)
            net=conn.execute(f"""
              SELECT COUNT(*),MAX(last_seen),MAX(interval_seconds),
                     SUM(rx_bytes),SUM(tx_bytes),SUM(rx_packets),SUM(tx_packets),
                     SUM(rx_mbps),SUM(tx_mbps),SUM(rx_peak_mbps),SUM(tx_peak_mbps),
                     SUM(rx_pps),SUM(tx_pps),SUM(rx_peak_pps),SUM(tx_peak_pps),
                     SUM(sample_count),SUM(sample_expected),MAX(sample_max_gap),
                     MAX(CASE UPPER(sample_quality) WHEN 'POOR' THEN 3 WHEN 'DEGRADED' THEN 2 WHEN 'GOOD' THEN 1 ELSE 0 END),
                     SUM(seconds_over_rx_pps),SUM(seconds_over_tx_pps),SUM(drops),SUM(errors),
                     MAX(iface),MAX(bridge)
                FROM vm_iface_current WHERE {' AND '.join(where)}
            """,params).fetchone()
            if safe_int(net[0],0)<=0:
                return None
            quality=network_quality_from_rank(safe_int(net[18],0))
            last_seen=safe_int(net[1],current[0]); interval=max(1,safe_int(net[2],current[1]))
            rx_bytes=safe_int(net[3],0); tx_bytes=safe_int(net[4],0)
            rx_packets=safe_int(net[5],0); tx_packets=safe_int(net[6],0)
            values={
                "rx_mbps":safe_float(net[7],0),"tx_mbps":safe_float(net[8],0),
                "rx_mbps_peak":safe_float(net[9],0),"tx_mbps_peak":safe_float(net[10],0),
                "rx_pps":safe_float(net[11],0),"tx_pps":safe_float(net[12],0),
                "rx_pps_peak":safe_float(net[13],0),"tx_pps_peak":safe_float(net[14],0),
                "sample_count":safe_int(net[15],0),"sample_expected":safe_int(net[16],0),
                "sample_max_gap":safe_float(net[17],0),"sample_quality":quality,
                "seconds_over_pps":max(safe_int(net[19],0),safe_int(net[20],0)),
                "drops":safe_int(net[21],0),"errors":safe_int(net[22],0),
                "iface":str(net[23] or iface or ""),"bridge":str(net[24] or bridge or ""),
            }
        else:
            last_seen=safe_int(current[0],0); interval=max(1,safe_int(current[1],CACHE_BUCKET_SECONDS))
            rx_bytes=safe_int(current[3],0); tx_bytes=safe_int(current[4],0)
            rx_packets=int(round(safe_float(current[9],0)*interval)); tx_packets=int(round(safe_float(current[10],0)*interval))
            values={
                "rx_mbps":safe_float(current[5],0),"tx_mbps":safe_float(current[6],0),
                "rx_mbps_peak":safe_float(current[7],0),"tx_mbps_peak":safe_float(current[8],0),
                "rx_pps":safe_float(current[9],0),"tx_pps":safe_float(current[10],0),
                "rx_pps_peak":safe_float(current[11],0),"tx_pps_peak":safe_float(current[12],0),
                "sample_count":safe_int(current[13],0),"sample_expected":safe_int(current[14],0),
                "sample_max_gap":safe_float(current[15],0),"sample_quality":str(current[16] or "LEGACY"),
                "seconds_over_pps":max(safe_int(current[17],0),safe_int(current[18],0)),
                "drops":safe_int(current[19],0),"errors":safe_int(current[20],0),
                "iface":"","bridge":"",
            }
        result={
            "selected_bucket":last_seen,"latest_bucket":last_seen,"last_push":last_seen,
            "interval_seconds":interval,"rx_bytes":rx_bytes,"tx_bytes":tx_bytes,
            "rx_packets":rx_packets,"tx_packets":tx_packets,
            "rx_packet_size_avg":rx_bytes/float(rx_packets) if rx_packets else 0.0,
            "tx_packet_size_avg":tx_bytes/float(tx_packets) if tx_packets else 0.0,
            "cpu_percent":safe_float(current[21],0),"cpu_full_percent":safe_float(current[21],0),
            "cpu_core_percent":safe_float(current[22],0),"vcpu_current":safe_int(current[23],0),
            "ram_current_kib":safe_int(current[24],0),"ram_maximum_kib":safe_int(current[24],0),
            "ram_rss_kib":safe_int(current[25],0),"ram_available_kib":safe_int(current[26],0),
            "disk_read_bps":safe_float(current[27],0),"disk_write_bps":safe_float(current[28],0),
            "sample_max_gap":values["sample_max_gap"],"sample_count":values["sample_count"],
            "sample_expected":values["sample_expected"],"sample_quality":values["sample_quality"],
            "seconds_over_pps":values["seconds_over_pps"],"seconds_over_mbps":0,
            "drops":values["drops"],"errors":values["errors"],
            "iface":values["iface"],"bridge":values["bridge"],
            **{k:v for k,v in values.items() if k in {"rx_mbps","tx_mbps","rx_mbps_peak","tx_mbps_peak","rx_pps","tx_pps","rx_pps_peak","tx_pps_peak"}},
        }
        result["total_bytes"]=rx_bytes+tx_bytes; result["packets"]=rx_packets+tx_packets
        return result
    finally:
        conn.close()

def _v5054_vm_snapshot_overview(node, vm_uuid, period, bridge="", iface=""):
    period=clean_period(period)
    if _request_target_ts() is None and period=="5m":
        live=_v5057_live_vm_snapshot(node,vm_uuid,bridge=bridge,iface=iface)
        if live:
            return live
    result=_v5057_vm_snapshot_history_base(node,vm_uuid,period,bridge=bridge,iface=iface)
    if result:
        # History cpu_percent has stored normalized/full utilization since the
        # v50 native ingest. Keep explicit semantics for renderers.
        full=max(0.0,min(100.0,safe_float(result.get("cpu_percent"),0)))
        vcpu=max(0,safe_int(result.get("vcpu_current"),0))
        result["cpu_full_percent"]=full
        result["cpu_core_percent"]=full*vcpu
    return result

def _v48129_vm_detail_cpu_stat(full_percent, vcpu):
    full=max(0.0,min(100.0,safe_float(full_percent,0.0)))
    vcpu_count=max(0,safe_int(vcpu,0))
    core=full*vcpu_count
    level=_v48129_level(full)
    return f'''<div class="stat vm-detail-cpu-stat resource-{level}"><span class="vm-detail-stat-label">CPU</span><b>{full:.1f}% full</b><span class="resource-meter vm-detail-cpu-meter"><i style="width:{min(100.0,full):.1f}%"></i></span><small>{core:.1f}% core · {vcpu_count} vCPU</small></div>'''

_v5057_vm_disks_history_base = _v48133_vm_disks

def _v48133_vm_disks(node, vm_uuid):
    period=clean_period(request.args.get("period","5m"))
    if _request_target_ts() is None and period=="5m":
        conn=db()
        try:
            rows=conn.execute("""
              SELECT target,source,mount,storage_device,storage_block,storage_fstype,
                     capacity_bytes,allocation_bytes,physical_bytes,
                     read_bps,write_bps,read_iops,write_iops,last_seen
                FROM vm_disk_current
               WHERE node=? AND vm_uuid=? AND role='customer'
               ORDER BY CASE target WHEN 'vda' THEN 0 WHEN 'vdb' THEN 1 ELSE 2 END,
                        target COLLATE NOCASE,source COLLATE NOCASE
            """,(node,vm_uuid)).fetchall()
            if rows:
                return rows
        finally:
            conn.close()
    return _v5057_vm_disks_history_base(node,vm_uuid)

def _v48135_vm_disk_total_overview(rows):
    if not rows:
        return ""
    assigned=sum(max(0,safe_int(row[6],0)) for row in rows)
    allocated=sum(max(0,safe_int(row[7],0)) for row in rows)
    physical=sum(max(0,safe_int(row[8],0)) for row in rows)
    pct=allocated*100.0/assigned if assigned>0 else 0.0
    level=_v48133_disk_level(pct)
    return f'''<div class="stat vm-disk-total-overview disk-level-{level}"><div class="vm-disk-stat-label">VM DISK ASSIGNED</div><b>{_disk_io_bytes(assigned)}</b><small>Host allocated {_disk_io_bytes(allocated)} · {pct:.1f}% · {len(rows)} disk{'s' if len(rows)!=1 else ''}</small><span class="vm-disk-overview-meter"><i style="width:{min(100.0,max(0.0,pct)):.1f}%"></i></span><small class="vm-disk-storage-line">Physical {_disk_io_bytes(physical)}</small></div>'''

def _v48133_vm_disk_io_card(rows):
    if not rows:
        return ""
    panels=[]; latest=0
    for target,source,mount,device,block,fstype,assigned,allocated,physical,rb,wb,ri,wi,seen in rows:
        assigned=max(0,safe_int(assigned,0)); allocated=max(0,safe_int(allocated,0)); physical=max(0,safe_int(physical,0))
        pct=allocated*100.0/assigned if assigned>0 else 0.0; level=_v48133_disk_level(pct); latest=max(latest,safe_int(seen,0)); dev=device or (("/dev/"+block) if block else "-")
        panels.append(f'''<article class="vm-disk-panel disk-level-{level}"><div class="vm-disk-panel-head"><div><span>VIRTUAL DISK</span><h4>{escape(target or '-')}</h4></div><div class="vm-disk-storage-badge"><b>{escape(mount or '-')}</b><small>{escape(dev)}</small></div></div><div class="vm-disk-panel-capacity"><div><span>ASSIGNED DISK SIZE</span><b>{_disk_io_bytes(assigned)}</b><small>Host allocated {_disk_io_bytes(allocated)} · {pct:.1f}%</small></div><span class="vm-disk-overview-meter"><i style="width:{min(100.0,max(0.0,pct)):.1f}%"></i></span></div><div class="vm-disk-panel-metrics"><div><span>READ</span><b>{_disk_io_rate(rb)}</b></div><div><span>WRITE</span><b>{_disk_io_rate(wb)}</b></div><div><span>READ IOPS</span><b>{_disk_io_iops(ri)}</b></div><div><span>WRITE IOPS</span><b>{_disk_io_iops(wi)}</b></div></div><div class="vm-disk-panel-meta"><div><span>SOURCE</span><code title="{escape(source or '-',quote=True)}">{escape(source or '-')}</code></div><div><span>FILESYSTEM</span><b>{escape(fstype or '-')}</b></div><div><span>PHYSICAL</span><b>{_disk_io_bytes(physical)}</b></div><div><span>LAST SAMPLE</span><b>{fmt_push(seen)}</b></div></div></article>''')
    return f'''<div class="card vm-disk-detail-card vm-disk-panels-only" id="virtual-disk-io"><div class="table-title-row"><div><h3>Virtual Disk I/O</h3><div class="table-hint">Assigned disk size is the guest-visible capacity. Host allocated is shown separately. Live 5m reads vm_disk_current; historical periods read the exact retained storage snapshot.</div></div><div class="count-badges"><span>Disks <b>{len(rows)}</b></span><span>Seen <b>{fmt_push(latest)}</b></span></div></div><div class="vm-disk-detail-grid">{''.join(panels)}</div></div>'''

# Historical VM RAM must use the same selected snapshot as CPU/network/disk.
# Live 5m uses the current cache; all other periods use the exact retained
# vm_perf_stats bucket selected for the page.
def _v48103_latest_ram(node, vm_uuid):
    period = clean_period(request.args.get("period", "5m"))
    target = _request_target_ts()
    conn = db()
    try:
        if target is None and period == "5m":
            return conn.execute("""
                SELECT ram_current_kib,ram_rss_kib,ram_available_kib,
                       ram_unused_kib,ram_usable_kib,last_seen
                  FROM vm_current_fast
                 WHERE node=? AND vm_uuid=?
            """, (node, vm_uuid)).fetchone()
        selected_bucket, _latest_bucket = resolve_snapshot_bucket(conn, period, node=node)
        if safe_int(selected_bucket, 0) <= 0:
            return None
        return conn.execute("""
            SELECT ram_current_kib,ram_rss_kib,ram_available_kib,
                   ram_unused_kib,ram_usable_kib,time
              FROM vm_perf_stats
             WHERE node=? AND vm_uuid=? AND bucket=?
             ORDER BY time DESC
             LIMIT 1
        """, (node, vm_uuid, selected_bucket)).fetchone()
    finally:
        conn.close()

# current cards from an obsolete node. Historical/custom-time views retain the
# requested node so migration investigations remain possible.
_v5057_vm_page_route_base = app.view_functions.get("vm_page")

def vm_page_v5057():
    node = (request.args.get("node") or "").strip()
    vm_uuid = (request.args.get("vm_uuid") or "").strip()
    period = clean_period(request.args.get("period", "5m"))
    if node and vm_uuid and period == "5m" and _request_target_ts() is None:
        current = get_vm_current_location(vm_uuid)
        current_node = str((current or {}).get("node") or "").strip()
        if current_node and current_node != node:
            return redirect(url_for(
                "vm_page", node=current_node, vm_uuid=vm_uuid,
                bridge="", iface="", period="5m",
            ))
    return _v5057_vm_page_route_base()

app.view_functions["vm_page"] = vm_page_v5057

def get_vm_interface_identities(node, vm_uuid, bridge="", iface=""):
    """Return all current virtual NIC identities for one VM.

    MAC is interface inventory metadata. It is read from the bounded current
    table even when an older retained metrics snapshot is selected.
    """
    params = [node, vm_uuid]
    where = "WHERE node=? AND vm_uuid=?"
    if bridge:
        where += " AND bridge=?"
        params.append(bridge)
    if iface:
        where += " AND iface=?"
        params.append(iface)
    conn = db()
    try:
        return conn.execute(f"""
            SELECT iface,bridge,mac,last_seen
              FROM vm_iface_current
              {where}
             ORDER BY CASE bridge WHEN ? THEN 0 WHEN ? THEN 1 ELSE 2 END,
                      iface COLLATE NOCASE
        """, params + [PUBLIC_BRIDGE, PRIVATE_BRIDGE]).fetchall()
    finally:
        conn.close()

def vm_network_identity_card(node, vm_uuid, bridge="", iface=""):
    rows = get_vm_interface_identities(node, vm_uuid, bridge=bridge, iface=iface)
    if not rows:
        return '<div class="card vm-network-identity-card"><h3>VM Network Identity</h3><div class="empty">MAC has not been reported yet. Existing agents will populate it on the next accepted push.</div></div>'
    cards = []
    for nic_iface, nic_bridge, nic_mac, seen in rows:
        cards.append(f'''
          <div class="vm-network-identity-row">
            <div class="stat"><span>Interface</span><b class="mono">{escape(nic_iface or '-')}</b></div>
            <div class="stat"><span>MAC</span><b class="mono">{escape(normalize_mac_address(nic_mac) or '-')}</b></div>
            <div class="stat"><span>VM UUID</span><b class="mono">{escape(vm_uuid)}</b></div>
            <div class="stat"><span>Node</span><b class="mono">{escape(node)}</b></div>
            <div class="stat"><span>Bridge</span><b class="mono">{escape(nic_bridge or '-')}</b></div>
            <div class="stat"><span>Seen</span><b>{fmt_push(seen)}</b></div>
          </div>''')
    return f'''
    <div class="card vm-network-identity-card">
      <div class="table-title-row">
        <div><h3>VM Network Identity</h3><div class="table-hint">Virtual NIC identity reported by libvirt. A unique MAC search opens this VM directly.</div></div>
        <div class="count-badges"><span>NICs <b>{len(rows)}</b></span></div>
      </div>
      <div class="vm-network-identity-list">{"".join(cards)}</div>
    </div>'''

V5057_MAC_IDENTITY_CSS = r'''
<style id="v5057-mac-identity">
.vm-network-identity-list{display:flex;flex-direction:column;gap:10px}
.vm-network-identity-row{display:grid;grid-template-columns:minmax(150px,1fr) minmax(180px,1.15fr) minmax(230px,1.5fr) minmax(150px,1fr) minmax(120px,.8fr) minmax(130px,.85fr);gap:10px}
.vm-network-identity-row .stat{min-width:0}
.vm-network-identity-row .stat span{display:block;font-size:10px;font-weight:900;letter-spacing:.055em;color:#667085}
.vm-network-identity-row .stat b{display:block;margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nic-badge .nic-address{display:block}
html[data-theme=dark] .vm-network-identity-row .stat span{color:#9fb0c4}
@media(max-width:1200px){.vm-network-identity-row{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:700px){.vm-network-identity-row{grid-template-columns:1fr}}
</style>
'''

_v5057_mac_vm_page_base = app.view_functions.get("vm_page")

def vm_page_v5057_mac_identity():
    response = _v5057_mac_vm_page_base()
    try:
        if not hasattr(response, "get_data"):
            return response
        node = (request.args.get("node") or "").strip()
        vm_uuid = (request.args.get("vm_uuid") or "").strip()
        bridge = (request.args.get("bridge") or "").strip()
        iface = (request.args.get("iface") or "").strip()
        if not node or not vm_uuid:
            return response
        html = response.get_data(as_text=True)
        if 'id="v5057-mac-identity"' not in html:
            html = html.replace("</head>", V5057_MAC_IDENTITY_CSS + "</head>", 1)
        if "vm-network-identity-card" not in html:
            card = vm_network_identity_card(node, vm_uuid)
            marker = '<div class="card top-card">'
            pos = html.find(marker)
            if pos >= 0:
                html = html[:pos] + card + html[pos:]
            else:
                html += card
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply VM MAC identity UI")
    return response

if _v5057_mac_vm_page_base is not None:
    app.view_functions["vm_page"] = vm_page_v5057_mac_identity

# current rows as Dashboard/Top VM. Historical/custom-time views keep the exact
# retained snapshot path.
_v5057_get_node_overview_history = get_node_overview
_v5057_get_node_metric_overview_history = get_node_metric_overview
_v5057_get_node_host_period_history = get_node_host_period
_v5057_get_node_filesystems_snapshot_history = get_node_filesystems_snapshot

def _v5057_node_live_request(period):
    return _request_target_ts() is None and clean_period(period) == "5m"

def get_node_overview(node, period, q="", vm_status="active"):
    if not _v5057_node_live_request(period):
        return _v5057_get_node_overview_history(
            node, period, q=q, vm_status=vm_status
        )
    params = [
        PUBLIC_BRIDGE, PUBLIC_BRIDGE, PUBLIC_BRIDGE,
        PRIVATE_BRIDGE, PRIVATE_BRIDGE, PRIVATE_BRIDGE,
        node, now_ts() - FAST_CURRENT_STALE_SECONDS,
    ]
    search_sql = ""
    if q:
        pattern = like_pattern(q)
        search_sql = " AND (i.vm_uuid LIKE ? OR i.iface LIKE ? OR i.node LIKE ?)"
        params.extend([pattern, pattern, pattern])
    conn = db()
    try:
        row = conn.execute(f"""
            SELECT
                COUNT(DISTINCT i.vm_uuid),
                COUNT(DISTINCT i.bridge || ':' || i.iface),
                COALESCE(SUM(CASE WHEN i.bridge=? THEN i.rx_bytes ELSE 0 END),0),
                COALESCE(SUM(CASE WHEN i.bridge=? THEN i.tx_bytes ELSE 0 END),0),
                COALESCE(SUM(CASE WHEN i.bridge=? THEN i.rx_bytes+i.tx_bytes ELSE 0 END),0),
                COALESCE(SUM(CASE WHEN i.bridge=? THEN i.rx_bytes ELSE 0 END),0),
                COALESCE(SUM(CASE WHEN i.bridge=? THEN i.tx_bytes ELSE 0 END),0),
                COALESCE(SUM(CASE WHEN i.bridge=? THEN i.rx_bytes+i.tx_bytes ELSE 0 END),0),
                COALESCE(SUM(i.rx_bytes),0),
                COALESCE(SUM(i.tx_bytes),0),
                COALESCE(SUM(i.rx_bytes+i.tx_bytes),0),
                COALESCE(SUM(i.rx_packets+i.tx_packets),0),
                COALESCE(SUM(i.drops),0),
                COALESCE(SUM(i.errors),0),
                COALESCE(MAX(i.last_seen),0),
                COALESCE(MAX(i.interval_seconds),?)
            FROM vm_iface_current i
            LEFT JOIN vm_inventory vi
              ON vi.node=i.node AND vi.vm_uuid=i.vm_uuid
            WHERE i.node=? AND i.last_seen>=?
              AND COALESCE(vi.status,'active')!='hidden'
              {search_sql}
        """, params[:6] + [CACHE_BUCKET_SECONDS] + params[6:]).fetchone()
        return row or (
            0, 0, 0, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0, 0, CACHE_BUCKET_SECONDS,
        )
    finally:
        conn.close()

def get_node_metric_overview(node, period, q="", vm_status="active"):
    if not _v5057_node_live_request(period):
        return _v5057_get_node_metric_overview_history(
            node, period, q=q, vm_status=vm_status
        )
    params = [node, now_ts() - FAST_CURRENT_STALE_SECONDS]
    search_sql = ""
    if q:
        pattern = like_pattern(q)
        search_sql = " AND (c.vm_uuid LIKE ? OR c.node LIKE ?)"
        params.extend([pattern, pattern])
    conn = db()
    try:
        row = conn.execute(f"""
            SELECT
                COUNT(DISTINCT c.vm_uuid),
                COALESCE(SUM(c.total_pps),0),
                COALESCE(SUM(c.drops),0),
                COALESCE(SUM(c.errors),0),
                COALESCE(SUM(c.cpu_core_percent),0),
                COALESCE(MAX(c.cpu_core_percent),0),
                COALESCE(SUM(CASE
                    WHEN c.ram_available_kib>0
                     AND (c.ram_usable_kib>0 OR c.ram_unused_kib>0)
                     AND c.ram_usable_kib<=c.ram_available_kib*1.05
                    THEN GREATEST(c.ram_available_kib-c.ram_usable_kib,0)
                    ELSE 0 END),0),
                COALESCE(SUM(CASE
                    WHEN c.ram_available_kib>0
                     AND (c.ram_usable_kib>0 OR c.ram_unused_kib>0)
                     AND c.ram_usable_kib<=c.ram_available_kib*1.05
                    THEN c.ram_available_kib ELSE 0 END),0),
                COALESCE(SUM(c.ram_rss_kib),0),
                COALESCE(SUM(c.ram_current_kib),0),
                COALESCE(SUM(CASE
                    WHEN c.ram_available_kib>0
                     AND (c.ram_usable_kib>0 OR c.ram_unused_kib>0)
                     AND c.ram_usable_kib<=c.ram_available_kib*1.05
                    THEN 1 ELSE 0 END),0),
                COALESCE(SUM(c.disk_read_bps),0),
                COALESCE(SUM(c.disk_write_bps),0),
                COALESCE(MAX(c.last_seen),0)
            FROM vm_current_fast c
            LEFT JOIN vm_inventory vi
              ON vi.node=c.node AND vi.vm_uuid=c.vm_uuid
            WHERE c.node=? AND c.last_seen>=?
              AND COALESCE(vi.status,'active')!='hidden'
              {search_sql}
        """, params).fetchone()
        return row or (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    finally:
        conn.close()

def get_node_host_period(node, period):
    if not _v5057_node_live_request(period):
        return _v5057_get_node_host_period_history(node, period)
    conn = db()
    try:
        row = conn.execute("""
            SELECT last_seen,interval_seconds,load1,load5,load15,
                   cpu_count,cpu_percent,mem_total,mem_available,mem_used,
                   swap_total,swap_used,disk_read_bps,disk_write_bps,
                   disk_read_delta,disk_write_delta,uptime_seconds,
                   alert_level,alert_flags,1
              FROM node_host_latest
             WHERE node=?
        """, (node,)).fetchone()
        return row
    finally:
        conn.close()

def get_node_filesystems_snapshot(node, period):
    if not _v5057_node_live_request(period):
        return _v5057_get_node_filesystems_snapshot_history(node, period)
    conn = db()
    try:
        rows = conn.execute("""
            SELECT mount,device,fstype,size,used,avail,use_percent,last_seen,
                   read_bps,write_bps,read_iops,write_iops,util_percent,last_seen
              FROM node_storage_current
             WHERE node=?
             ORDER BY use_percent DESC,mount COLLATE NOCASE
        """, (node,)).fetchall()
        if not rows:
            rows = conn.execute("""
                SELECT mount,device,fstype,size,used,avail,use_percent,last_seen,
                       0,0,0,0,0,last_seen
                  FROM node_filesystem_latest
                 WHERE node=?
                 ORDER BY use_percent DESC,mount COLLATE NOCASE
            """, (node,)).fetchall()
        return _v48135_real_filesystem_rows(rows)
    finally:
        conn.close()

