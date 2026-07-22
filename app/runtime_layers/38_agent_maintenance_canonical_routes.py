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

V5057_VERSION = "50.5.9-prod-r20-consumption-node-vm-rollup-alignment-hotfix"

def enqueue_maintenance_job(action, parameters, actor):
    payload = dict(parameters or {})
    payload.setdefault("requested_by", actor or "admin")
    exclusive = str(action or "").strip().lower() in {"reset_app_data", "configuration_restore"}
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
    if not row or str(row[3] or "") != "super_admin" or not safe_int(row[4], 0):
        return False
    return bool(password) and check_password_hash(str(row[2] or ""), str(password))

@app.route("/admin/maintenance/cancel", methods=["POST"])
def admin_cancel_maintenance_v5057():
    deny = require_admin()
    if deny:
        return deny
    job_id = safe_int(request.form.get("job_id"), 0)
    actor = dashboard_username() or get_admin_username()
    if job_id > 0:
        conn = db()
        try:
            job_row = conn.execute("SELECT action FROM maintenance_jobs WHERE id=?", (job_id,)).fetchone()
        finally:
            conn.close()
        sensitive_actions = {"configuration_backup", "configuration_restore", "full_backup", "full_backup_verify", "reset_app_data"}
        if job_row and str(job_row[0] or "") in sensitive_actions and clean_role(dashboard_role()) != "super_admin":
            return Response("Forbidden: super_admin role required\n", status=403, mimetype="text/plain")
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

def _r225_current_super_admin_identity():
    row = current_dashboard_user()
    if not row or str(row[3] or "") != "super_admin" or not safe_int(row[4], 0):
        raise PermissionError("Active super_admin account required")
    return int(row[0]), str(row[1])

def admin_database_maintenance_v5057():
    action = str(request.form.get("action") or "").strip().lower()
    sensitive = {
        "configuration_backup", "configuration_restore", "configuration_backup_protect",
        "configuration_backup_unprotect", "configuration_backup_delete", "configuration_backup_download", "full_backup",
        "full_backup_verify", "full_backup_protect", "full_backup_unprotect", "full_backup_delete", "full_backup_download",
        "reset_app_data_preview", "reset_app_data",
    }
    if action not in sensitive:
        return _v5057_admin_database_maintenance_base()
    role = clean_role(dashboard_role())
    if role != "super_admin":
        return Response("Forbidden: super_admin role required\n", status=403, mimetype="text/plain")
    deny = require_admin()
    if deny:
        return deny
    actor_user_id, actor = _r225_current_super_admin_identity()
    try:
        if not _v5057_verify_current_admin_password(request.form.get("admin_password") or ""):
            raise ValueError("Super Admin password verification failed")

        if action == "configuration_backup":
            job_id, unit_name = maintenance_queue.enqueue_job(
                "configuration_backup", {"requested_by": actor, "reason": "manual"}, actor
            )
            message = f"Configuration Backup job #{job_id} queued."
        elif action == "full_backup":
            job_id, unit_name = maintenance_queue.enqueue_job(
                "full_backup", {"requested_by": actor}, actor
            )
            message = f"Full Emergency Database Backup job #{job_id} queued. No web restore is provided."
        elif action == "full_backup_verify":
            backup_id = str(request.form.get("backup_id") or "").strip()
            emergency_backup.emergency_dump_path(backup_id)
            job_id, unit_name = maintenance_queue.enqueue_job(
                "full_backup_verify", {"requested_by": actor, "backup_id": backup_id}, actor
            )
            message = f"Full Emergency Backup verification job #{job_id} queued for {backup_id}."
        elif action in {"full_backup_protect", "full_backup_unprotect"}:
            backup_id = str(request.form.get("backup_id") or "").strip()
            protected = action == "full_backup_protect"
            emergency_backup.set_emergency_backup_protected(backup_id, protected)
            message = f"Full Emergency Backup {backup_id} is now {'protected' if protected else 'unprotected'}."
        elif action == "full_backup_download":
            backup_id = str(request.form.get("backup_id") or "").strip()
            path = emergency_backup.emergency_dump_path(backup_id)
            log_account_event(
                "super_admin_maintenance_action", username=actor, realm="admin", role="super_admin",
                detail=f"action={action};backup_id={backup_id}",
            )
            return send_file(
                path,
                as_attachment=True,
                download_name=f"{backup_id}-database.dump",
                mimetype="application/octet-stream",
                conditional=True,
                max_age=0,
            )
        elif action == "full_backup_delete":
            backup_id = str(request.form.get("backup_id") or "").strip()
            if str(request.form.get("confirm_text") or "").strip() != "DELETE FULL EMERGENCY BACKUP":
                raise ValueError("Confirmation text must be DELETE FULL EMERGENCY BACKUP")
            emergency_backup.delete_emergency_backup(backup_id)
            message = f"Full Emergency Backup {backup_id} deleted."
        elif action == "configuration_restore":
            if str(request.form.get("confirm_text") or "").strip() != "RESTORE CONFIGURATION":
                raise ValueError("Confirmation text must be RESTORE CONFIGURATION")
            backup_id = str(request.form.get("backup_id") or "").strip()
            configuration_backup.verify_configuration_backup(backup_id)
            sections = [name for name in sorted(configuration_backup.VALID_SECTIONS) if request.form.get(f"section_{name}") == "1"]
            if not sections:
                raise ValueError("Select at least one configuration section")
            job_id, unit_name = maintenance_queue.enqueue_job(
                "configuration_restore",
                {
                    "requested_by": actor,
                    "actor_user_id": actor_user_id,
                    "actor_username": actor,
                    "backup_id": backup_id,
                    "sections": sections,
                },
                actor,
                exclusive=True,
            )
            message = f"Configuration Restore job #{job_id} accepted. A protected safety snapshot will be created first."
        elif action in {"configuration_backup_protect", "configuration_backup_unprotect"}:
            backup_id = str(request.form.get("backup_id") or "").strip()
            protected = action == "configuration_backup_protect"
            configuration_backup.set_configuration_backup_protected(backup_id, protected)
            message = f"Configuration backup {backup_id} is now {'protected' if protected else 'unprotected'}."
        elif action == "configuration_backup_download":
            backup_id = str(request.form.get("backup_id") or "").strip()
            path = configuration_backup.configuration_backup_path(backup_id)
            payload = path.read_bytes()
            log_account_event(
                "super_admin_maintenance_action", username=actor, realm="admin", role="super_admin",
                detail=f"action={action};backup_id={backup_id}",
            )
            return Response(
                payload, status=200, mimetype="application/zip",
                headers={
                    "Content-Disposition": f'attachment; filename="{path.name}"',
                    "Content-Length": str(len(payload)),
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                },
            )
        elif action == "configuration_backup_delete":
            backup_id = str(request.form.get("backup_id") or "").strip()
            if str(request.form.get("confirm_text") or "").strip() != "DELETE CONFIGURATION BACKUP":
                raise ValueError("Confirmation text must be DELETE CONFIGURATION BACKUP")
            configuration_backup.delete_configuration_backup(backup_id)
            message = f"Configuration backup {backup_id} deleted."
        elif action == "reset_app_data_preview":
            pending = _v5057_queue_has_pending_jobs()
            if pending:
                raise RuntimeError(f"Queue must be empty before Nuclear preview: job #{pending[0]} ({pending[1]}) is {pending[2]}")
            options_present = request.form.get("backup_options_present") == "1"
            create_config = request.form.get("create_configuration_backup") == "1" if options_present else True
            create_full = request.form.get("create_full_backup") == "1" if options_present else False
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
                "create_configuration_backup": create_config,
                "create_full_backup": create_full,
            }
            message = "Nuclear preview created. Review and confirm within 5 minutes."
        else:
            preview = session.get("v5057_nuclear_preview") or {}
            request_now = now_ts()
            if not isinstance(preview, dict) or safe_int(preview.get("expires_at"), 0) < request_now:
                session.pop("v5057_nuclear_preview", None)
                raise ValueError("Nuclear preview expired. Create a new preview")
            if request_now < safe_int(preview.get("not_before"), 0):
                raise ValueError(f"Nuclear safety delay is active for {safe_int(preview.get('not_before'),0)-request_now} second(s)")
            nonce = str(request.form.get("preview_nonce") or "")
            if not nonce or not secrets.compare_digest(nonce, str(preview.get("nonce") or "")):
                raise ValueError("Nuclear preview token mismatch")
            create_config = bool(preview.get("create_configuration_backup"))
            create_full = bool(preview.get("create_full_backup"))
            prefix = "RESET VIRTINFRA" if (create_config or create_full) else "RESET VIRTINFRA WITHOUT BACKUP"
            required = f"{prefix} {preview.get('code', '')}"
            if str(request.form.get("confirm_text") or "").strip() != required:
                raise ValueError(f"Confirmation text must be {required}")
            pending = _v5057_queue_has_pending_jobs()
            if pending:
                raise RuntimeError(f"Nuclear reset cannot wait in FIFO: job #{pending[0]} ({pending[1]}) is {pending[2]}")
            parameters = {
                "requested_by": actor,
                "actor_user_id": actor_user_id,
                "actor_username": actor,
                "preview_created_at": safe_int(preview.get("created_at"), 0),
                "preview_table_count": safe_int(preview.get("table_count"), 0),
                "preview_estimated_rows": safe_int(preview.get("estimated_rows"), 0),
                "create_configuration_backup": create_config,
                "create_full_backup": create_full,
            }
            job_id, unit_name = maintenance_queue.enqueue_job("reset_app_data", parameters, actor, exclusive=True)
            session.pop("v5057_nuclear_preview", None)
            message = f"True Nuclear Reset job #{job_id} accepted. Only this super_admin, this job and one Nuclear audit will remain."

        log_account_event(
            "super_admin_maintenance_action", username=actor, realm="admin", role="super_admin",
            detail=f"action={action};message={message[:300]}",
        )
        return redirect(url_for("admin_page", section="maintenance", dbmsg=message) + "#maintenance-queue")
    except Exception as exc:
        error = f"Super Admin maintenance action was not started: {exc}"
        log_account_event(
            "super_admin_maintenance_rejected", username=actor, realm="admin", role="super_admin",
            detail=f"action={action};error={error[:400]}",
        )
        return redirect(url_for("admin_page", section="maintenance", dberr=error) + "#maintenance-queue")

app.view_functions["admin_database_maintenance"] = admin_database_maintenance_v5057

_v5057_database_maintenance_card_base = database_maintenance_card

def _r225_configuration_backup_card(csrf, endpoint):
    try:
        backups = configuration_backup.list_configuration_backups()
        list_error = ""
    except Exception as exc:
        backups = []
        list_error = str(exc)
    rows = []
    for item in backups[:50]:
        backup_id = str(item.get("backup_id") or "")
        status = str(item.get("status") or "unknown")
        counts = item.get("counts") or {}
        protected = bool(item.get("protected"))
        actions = []
        if status == "verified":
            restore_checks = "".join(
                f'<label><input type="checkbox" name="section_{name}" value="1" checked> {label}</label>'
                for name, label in (
                    ("users", "Users & roles"), ("api_keys", "API keys"),
                    ("settings", "Theme & policies"), ("groups", "Node Groups"),
                    ("node_group_mapping", "Node to Group mapping"),
                )
            )
            actions.append(f"""<details><summary>Restore</summary><form method="post" action="{endpoint}" onsubmit="return confirm('Restore selected configuration from {escape(backup_id)}? Current monitoring data is not touched.');"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="configuration_restore"><input type="hidden" name="backup_id" value="{escape(backup_id,quote=True)}"><div class="restore-sections">{restore_checks}</div><label>Super Admin password<input type="password" name="admin_password" required autocomplete="current-password"></label><label>Type RESTORE CONFIGURATION<input name="confirm_text" required></label><button type="submit">Restore Configuration</button></form></details>""")
            actions.append(f"""<details><summary>Download</summary><form method="post" action="{endpoint}"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="configuration_backup_download"><input type="hidden" name="backup_id" value="{escape(backup_id,quote=True)}"><label>Super Admin password<input type="password" name="admin_password" required autocomplete="current-password"></label><button type="submit">Download</button></form></details>""")
        protect_action = "configuration_backup_unprotect" if protected else "configuration_backup_protect"
        protect_label = "Unprotect" if protected else "Protect"
        actions.append(f"""<details><summary>{protect_label}</summary><form method="post" action="{endpoint}"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="{protect_action}"><input type="hidden" name="backup_id" value="{escape(backup_id,quote=True)}"><label>Super Admin password<input type="password" name="admin_password" required autocomplete="current-password"></label><button type="submit">{protect_label}</button></form></details>""")
        if not protected:
            actions.append(f"""<details><summary>Delete</summary><form method="post" action="{endpoint}" onsubmit="return confirm('Delete configuration backup {escape(backup_id)}?');"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="configuration_backup_delete"><input type="hidden" name="backup_id" value="{escape(backup_id,quote=True)}"><label>Super Admin password<input type="password" name="admin_password" required autocomplete="current-password"></label><label>Type DELETE CONFIGURATION BACKUP<input name="confirm_text" required></label><button class="btn-danger" type="submit">Delete</button></form></details>""")
        rows.append(
            f'<tr><td><b>{escape(backup_id)}</b><small>{escape(str(item.get("app_version") or ""))}</small></td>'
            f'<td>{fmt_full(item.get("created_at"))}<small>{escape(str(item.get("created_by") or ""))}</small></td>'
            f'<td>{escape(status.upper())}<small>{human(safe_int(item.get("size_bytes"),0))} | users {safe_int(counts.get("users"),0)} | groups {safe_int(counts.get("groups"),0)}</small></td>'
            f'<td>{"PROTECTED" if protected else "Normal"}</td><td><div class="maint-actions compact-actions">{"".join(actions)}</div></td></tr>'
        )
    config_body = "".join(rows) or '<tr><td colspan="5"><div class="empty-state">No Configuration Backup has been created.</div></td></tr>'
    config_error_html = f'<div class="alert error">{escape(list_error)}</div>' if list_error else ''

    try:
        full_backups = emergency_backup.list_emergency_backups()
        full_error = ""
    except Exception as exc:
        full_backups = []
        full_error = str(exc)
    full_rows = []
    for item in full_backups[:30]:
        backup_id = str(item.get("backup_id") or "")
        status = str(item.get("status") or "unknown")
        protected = bool(item.get("protected"))
        metadata = item.get("metadata") or {}
        actions = []
        actions.append(f"""<details><summary>Verify</summary><form method="post" action="{endpoint}"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="full_backup_verify"><input type="hidden" name="backup_id" value="{escape(backup_id,quote=True)}"><label>Super Admin password<input type="password" name="admin_password" required autocomplete="current-password"></label><button type="submit">Verify</button></form></details>""")
        if status == "verified":
            actions.append(f"""<details><summary>Download DB dump</summary><form method="post" action="{endpoint}"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="full_backup_download"><input type="hidden" name="backup_id" value="{escape(backup_id,quote=True)}"><label>Super Admin password<input type="password" name="admin_password" required autocomplete="current-password"></label><button type="submit">Download DB dump</button></form></details>""")
        protect_action = "full_backup_unprotect" if protected else "full_backup_protect"
        protect_label = "Unprotect" if protected else "Protect"
        actions.append(f"""<details><summary>{protect_label}</summary><form method="post" action="{endpoint}"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="{protect_action}"><input type="hidden" name="backup_id" value="{escape(backup_id,quote=True)}"><label>Super Admin password<input type="password" name="admin_password" required autocomplete="current-password"></label><button type="submit">{protect_label}</button></form></details>""")
        if not protected:
            actions.append(f"""<details><summary>Delete</summary><form method="post" action="{endpoint}" onsubmit="return confirm('Delete Full Emergency Backup {escape(backup_id)}?');"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="full_backup_delete"><input type="hidden" name="backup_id" value="{escape(backup_id,quote=True)}"><label>Super Admin password<input type="password" name="admin_password" required autocomplete="current-password"></label><label>Type DELETE FULL EMERGENCY BACKUP<input name="confirm_text" required></label><button class="btn-danger" type="submit">Delete</button></form></details>""")
        if status != "verified":
            actions.append(f"""<details><summary>Status detail</summary><pre>{escape(str(item.get('error') or 'Verification has not been run'))}</pre></details>""")
        full_rows.append(
            f'<tr><td><b>{escape(backup_id)}</b><small>{escape(str(metadata.get("release") or "unknown"))}</small></td>'
            f'<td>{fmt_full(item.get("created_at"))}<small>{escape(str(metadata.get("hostname") or ""))}</small></td>'
            f'<td>{escape(status.upper())}<small>{human(safe_int(item.get("dump_bytes"),0))} database.dump</small></td>'
            f'<td>{"PROTECTED" if protected else "Normal"}</td><td><div class="maint-actions compact-actions">{"".join(actions)}</div></td></tr>'
        )
    full_body = "".join(full_rows) or '<tr><td colspan="5"><div class="empty-state">No Full Emergency Backup has been created.</div></td></tr>'
    full_error_html = f'<div class="alert error">{escape(full_error)}</div>' if full_error else ''

    return f"""
      <div class="card admin-section" id="configuration-backup-restore">
        <div class="section-head"><div><span class="eyebrow">SUPER ADMIN ONLY</span><h3>Backup & Restore</h3><p>Configuration Restore never brings back Node/VM inventory, metrics, Consumption, logs or maintenance history.</p></div></div>
        {config_error_html}
        <div class="maint-actions">
          <form method="post" action="{endpoint}"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="configuration_backup"><label>Super Admin password<input type="password" name="admin_password" required autocomplete="current-password"></label><button type="submit">Create Configuration Backup</button></form>
        </div>
        <h4>Configuration Backups</h4>
        <div class="table-wrap"><table><thead><tr><th>Backup</th><th>Created</th><th>Status</th><th>Protection</th><th>Actions</th></tr></thead><tbody>{config_body}</tbody></table></div>
        <hr>
        <div class="section-head"><div><h4>Full Emergency Database Backups</h4><p>Disaster recovery artifact only. There is no direct web restore.</p></div></div>
        {full_error_html}
        <div class="maint-actions"><form method="post" action="{endpoint}"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="full_backup"><label>Super Admin password<input type="password" name="admin_password" required autocomplete="current-password"></label><button type="submit">Create Full Emergency Backup</button></form></div>
        <div class="table-wrap"><table><thead><tr><th>Backup</th><th>Created</th><th>Status</th><th>Protection</th><th>Actions</th></tr></thead><tbody>{full_body}</tbody></table></div>
      </div>"""

def database_maintenance_card(message="", error=""):
    html = _v5057_database_maintenance_card_base(message, error)
    preview = session.get("v5057_nuclear_preview") or {}
    valid_preview = isinstance(preview, dict) and safe_int(preview.get("expires_at"), 0) >= now_ts()
    csrf = escape(csrf_token(), quote=True)
    endpoint = escape(url_for("admin_database_maintenance"), quote=True)
    is_super_admin = clean_role(dashboard_role()) == "super_admin"
    if valid_preview and is_super_admin:
        code = str(preview.get("code") or "")
        create_config = bool(preview.get("create_configuration_backup"))
        create_full = bool(preview.get("create_full_backup"))
        prefix = "RESET VIRTINFRA" if (create_config or create_full) else "RESET VIRTINFRA WITHOUT BACKUP"
        policy = []
        if create_config:
            policy.append("Protected Configuration Backup")
        if create_full:
            policy.append("Verified Full Emergency Backup")
        if not policy:
            policy.append("NO BACKUP, permanently irreversible")
        required = f"{prefix} {code}"
        nuclear = f"""
      <div class="card maint-nuclear">
        <h3>True Nuclear Reset preview ready</h3>
        <div class="admin-note"><b>No data has been deleted.</b> This resets every application table and account. Only the current super_admin, this Nuclear job, one Nuclear audit and schema metadata remain.</div>
        <div class="maint-policy"><div><b>{safe_int(preview.get('table_count'),0)} tables</b><small>All public application tables</small></div><div><b>{safe_int(preview.get('estimated_rows'),0):,} rows</b><small>PostgreSQL estimate</small></div><div><b>{human(safe_int(preview.get('estimated_bytes'),0))}</b><small>Estimated relation size</small></div></div>
        <div class="alert {'error' if not (create_config or create_full) else 'success'}">Backup policy: {escape(' + '.join(policy))}</div>
        <div class="maint-actions"><form method="post" action="{endpoint}" onsubmit="return confirm('Final Nuclear Reset confirmation. This permanently deletes all application data.');"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="reset_app_data"><input type="hidden" name="preview_nonce" value="{escape(str(preview.get('nonce') or ''),quote=True)}"><label>Super Admin password<input type="password" name="admin_password" required autocomplete="current-password"></label><label>Type <b>{escape(required)}</b><input name="confirm_text" placeholder="{escape(required,quote=True)}" required></label><button class="btn-danger" type="submit">Execute True Nuclear Reset</button></form></div>
      </div>"""
    elif is_super_admin:
        nuclear = f"""
      <div class="card maint-nuclear">
        <h3>True Nuclear Reset</h3>
        <div class="admin-note"><b>Super Admin only.</b> Deletes all users except the current super_admin, all API keys, settings, Groups, inventory, metrics, Consumption, Abuse data, logs and previous queue history. Only one Nuclear audit remains.</div>
        <div class="maint-actions"><form method="post" action="{endpoint}"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="action" value="reset_app_data_preview"><input type="hidden" name="backup_options_present" value="1"><label><input type="checkbox" name="create_configuration_backup" value="1" checked> Create protected Configuration Backup</label><label><input type="checkbox" name="create_full_backup" value="1"> Create Full Emergency Database Backup</label><label>Super Admin password<input type="password" name="admin_password" required autocomplete="current-password"></label><button class="btn-danger" type="submit">Create Nuclear preview</button></form></div>
      </div>"""
    else:
        nuclear = ""

    start_marker = '<div class="card maint-nuclear">\n        <h3>Reset ALL app data + queue</h3>'
    end_marker = '<div class="card maint-danger">\n        <h3>API logs</h3>'
    start = html.find(start_marker)
    end = html.find(end_marker, start + 1) if start >= 0 else -1
    if start >= 0 and end > start:
        html = html[:start] + nuclear + "\n\n      " + html[end:]

    if clean_role(dashboard_role()) == "super_admin":
        config_card = _r225_configuration_backup_card(csrf, endpoint)
        marker = '<div class="maint-grid">'
        pos = html.find(marker)
        html = html[:pos] + config_card + "\n" + html[pos:] if pos >= 0 else config_card + html

    def add_cancel(match):
        job_id = match.group(1)
        block = match.group(0)
        if "queue-queued" not in block:
            return block
        form = f'<form method="post" action="{escape(url_for("admin_cancel_maintenance_v5057"),quote=True)}" onsubmit="return confirm(\'Cancel waiting job #{job_id}?\')" style="margin-top:6px"><input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="job_id" value="{job_id}"><button class="btn-danger" type="submit">Cancel waiting job</button></form>'
        return block.replace("</td>\n        </tr>", form + "</td>\n        </tr>", 1)
    try:
        import re as _re_v5057
        html = _re_v5057.sub(r'<tr class="queue-row queue-[^"]+">.*?<td class="num"><b>#(\d+)</b></td>.*?</tr>', add_cancel, html, flags=_re_v5057.S)
    except Exception:
        pass
    try:
        item = _v5030_bandwidth_admin_stats()
        token = escape(csrf_token(), quote=True)
        accounting = """
      <div class="card admin-section" id="accounting-storage">
        <div class="section-head"><div><span class="eyebrow">MAINTENANCE</span><h3>Node Consumption Rollup Storage</h3><p>Current hourly/daily physical Node rollups created from normal 5-minute Agent pushes. No per-VM accounting rows.</p></div><a class="btn" href="%s">Open Consumption</a></div>
        <div class="admin-kpis"><div><small>RETENTION</small><b>7 days</b></div><div><small>HOURLY ROWS</small><b>%s</b></div><div><small>DAILY ROWS</small><b>%s</b></div><div><small>LEGACY 2H ROWS</small><b>%s</b></div><div><small>TABLE + INDEX</small><b>%s</b></div><div><small>REPORTING VISIBLE NODES</small><b>%s / %s</b></div><div><small>MISSING RECENT ROLLUP</small><b>%s</b></div><div><small>LAST INGESTION</small><b>%s</b></div><div><small>OLDEST BUCKET</small><b>%s</b></div><div><small>NEWEST BUCKET</small><b>%s</b></div></div>
        <div class="bulk-bar"><form method="post" action="%s"><input type="hidden" name="csrf_token" value="%s"><input type="hidden" name="action" value="cleanup"><button type="submit">Run 7-day Consumption cleanup</button></form><form method="post" action="%s" onsubmit="return confirm('Delete all hourly, daily and legacy Consumption history?');"><input type="hidden" name="csrf_token" value="%s"><input type="hidden" name="action" value="clear"><input name="confirm_text" placeholder="CLEAR CONSUMPTION HISTORY"><button class="btn-danger" type="submit">Clear Consumption history</button></form></div>
      </div>""" % (url_for("bandwidth_consumption_page"), f"{item['hourly_rows']:,}", f"{item['daily_rows']:,}", f"{item['legacy_rows']:,}", human(item["size"]), item["reporting"], item["visible_nodes"], item["missing"], fmt_full(item["last_received"]), fmt_full(item["oldest"]), fmt_full(item["newest"]), url_for("admin_bandwidth_consumption_action"), token, url_for("admin_bandwidth_consumption_action"), token)
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

