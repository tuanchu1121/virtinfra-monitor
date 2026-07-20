@app.route("/admin/setup", methods=["GET", "POST"])
def admin_setup():
    bootstrap_dashboard_admin_from_settings()
    emergency_mode = emergency_admin_needed()
    if admin_is_configured() and not emergency_mode and not admin_allowed():
        return redirect(url_for("admin_login"))
    if admin_is_configured() and not emergency_mode and admin_allowed():
        return redirect(url_for("admin_page", section="vms"))

    error = ""
    username_value = (request.form.get("username") or "admin").strip() or "admin"
    if request.method == "POST":
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if len(username_value) < 3:
            error = "Username must be at least 3 characters."
        elif len(password) < 10:
            error = "Password must be at least 10 characters."
        elif password != confirm:
            error = "Password confirmation does not match."
        else:
            set_admin_credentials(username_value, password)
            created_user = get_dashboard_user(username_value)
            session.clear()
            session["dashboard_authenticated"] = True
            if created_user:
                session["dashboard_user_id"] = int(created_user[0])
            session["dashboard_username"] = username_value
            session["dashboard_role"] = "admin"
            session["admin_authenticated"] = True
            session["admin_username"] = username_value
            session["csrf_token"] = secrets.token_urlsafe(32)
            log_account_event("setup_admin", username=username_value, realm="admin", role="admin")
            return redirect(url_for("admin_page", section="vms"))

    error_html = f'<div class="error-box">{escape(error)}</div>' if error else ""
    content = f"""
    <div class="card login-card">
        <h3>{'Emergency Admin Setup' if emergency_mode else 'Initial Admin Setup'}</h3>
        {error_html}
        <form method="post" action="{url_for('admin_setup')}">
            <label>Username</label>
            <input name="username" value="{escape(username_value)}" autocomplete="username" autofocus>
            <label>Password</label>
            <input name="password" type="password" autocomplete="new-password">
            <label>Confirm Password</label>
            <input name="confirm" type="password" autocomplete="new-password">
            <button type="submit">Create Admin Account</button>
        </form>
        <div class="admin-note">{'No enabled admin user exists. Create a new admin here to recover access.' if emergency_mode else 'This setup page is only available while no admin password is configured. The password hash will be stored in PostgreSQL.'}</div>
    </div>
    """
    return page("Emergency Admin Setup" if emergency_mode else "Initial Admin Setup", content)

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    next_url = safe_next_url(request.args.get("next") or request.form.get("next"))
    error = ""

    # Upgrade path from older builds: create the initial admin dashboard user
    # from admin_settings when the users table is still empty.
    bootstrap_dashboard_admin_from_settings()

    # If no active admin exists, allow emergency setup to recover access.
    if emergency_admin_needed():
        return redirect(url_for("admin_setup"))

    if admin_allowed():
        return redirect(next_url)

    admin_username = get_admin_username()
    form_username = admin_username

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        form_username = username or admin_username
        password = request.form.get("password") or ""
        user = get_dashboard_user(username)

        # Normal path: any active dashboard user with role=admin may log into /admin.
        if user:
            user_id, user_name, user_hash, role, is_active, _created_at, _updated_at, _last_login = user
            role = clean_role(role)
            if role != "admin" or not is_active:
                log_account_event("login_failed", username=username, realm="admin", role=role, detail="dashboard admin user disabled or invalid")
                error = "This user is disabled or does not have admin role."
            elif not check_password_hash(user_hash, password):
                log_account_event("login_failed", username=username, realm="admin", role=role, detail="bad password")
                error = "Invalid username or password."
            else:
                session.clear()
                session["dashboard_authenticated"] = True
                session["dashboard_user_id"] = int(user_id)
                session["dashboard_username"] = user_name
                session["dashboard_role"] = "admin"
                session["admin_authenticated"] = True
                session["admin_username"] = user_name
                session["csrf_token"] = secrets.token_urlsafe(32)
                update_dashboard_user_login(user_id)
                log_account_event("login_success", username=user_name, realm="admin", role="admin")
                return redirect(next_url)
        else:
            # Legacy fallback: before user-management existed, admin credentials lived
            # only in admin_settings. If they match, convert them to a dashboard admin user.
            legacy_admin_username = get_admin_username()
            legacy_admin_hash = get_admin_password_hash()
            if username == legacy_admin_username and legacy_admin_hash and check_password_hash(legacy_admin_hash, password):
                upsert_dashboard_user(username, password, role="admin", is_active=1)
                converted = get_dashboard_user(username)
                if converted:
                    session.clear()
                    session["dashboard_authenticated"] = True
                    session["dashboard_user_id"] = int(converted[0])
                    session["dashboard_username"] = username
                    session["dashboard_role"] = "admin"
                    session["admin_authenticated"] = True
                    session["admin_username"] = username
                    session["csrf_token"] = secrets.token_urlsafe(32)
                    update_dashboard_user_login(converted[0])
                    log_account_event("login_success", username=username, realm="admin", role="admin", detail="legacy admin converted")
                    return redirect(next_url)
            log_account_event("login_failed", username=username, realm="admin", role="admin", detail="unknown admin user")
            error = "Invalid username or password."

    error_html = f'<div class="error-box">{escape(error)}</div>' if error else ""
    content = f"""
    <div class="card login-card">
        <h3>Admin Login</h3>
        {error_html}
        <form method="post" action="{url_for('admin_login')}">
            <input type="hidden" name="next" value="{escape(next_url, quote=True)}">
            <label>Username</label>
            <input name="username" value="{escape(form_username)}" autocomplete="username">
            <label>Password</label>
            <input name="password" type="password" autocomplete="current-password" autofocus>
            <button type="submit">Login</button>
        </form>
        <div class="admin-note">Any active user with role=admin can log in here. Viewer users can only access dashboard pages.</div>
    </div>
    """
    return page("Admin Login", content)

@app.route("/admin/password", methods=["GET", "POST"])
def admin_change_password():
    deny = require_admin()
    if deny:
        return deny

    error = ""
    success = ""
    admin_username = get_admin_username()
    password_hash = get_admin_password_hash()

    if request.method == "POST":
        current = request.form.get("current_password") or ""
        new_password = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        if not check_password_hash(password_hash, current):
            error = "Current password is incorrect."
        elif len(new_password) < 10:
            error = "New password must be at least 10 characters."
        elif new_password != confirm:
            error = "Password confirmation does not match."
        else:
            set_admin_credentials(admin_username, new_password)
            log_account_event("password_changed", username=admin_username, realm="admin", role="admin")
            success = "Admin password has been updated."

    error_html = f'<div class="error-box">{escape(error)}</div>' if error else ""
    success_html = f'<div class="success-box">{escape(success)}</div>' if success else ""
    content = f"""
    <div class="card login-card">
        <h3>Change Admin Password</h3>
        <a href="{url_for('admin_page')}">Back to Admin</a>
        {error_html}
        {success_html}
        <form method="post" action="{url_for('admin_change_password')}">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}">
            <label>Current Password</label>
            <input name="current_password" type="password" autocomplete="current-password" autofocus>
            <label>New Password</label>
            <input name="new_password" type="password" autocomplete="new-password">
            <label>Confirm New Password</label>
            <input name="confirm_password" type="password" autocomplete="new-password">
            <button type="submit">Update Password</button>
        </form>
    </div>
    """
    return page("Change Admin Password", content)

@app.route("/admin/logout")
def admin_logout():
    username = session.get("admin_username") or dashboard_username()
    if username:
        log_account_event("logout", username=username, realm="admin", role="admin")
    session.clear()
    return redirect(url_for("admin_login"))

@app.route("/admin/users")
def admin_users_page():
    deny = require_admin()
    if deny:
        return deny

    users = [row for row in get_dashboard_users() if clean_role(dashboard_role()) == "super_admin" or clean_role(row[2]) != "super_admin"]
    body = ""
    current_id = current_dashboard_user_id()
    for user_id, username, role, is_active, created_at, updated_at, last_login in users:
        status = "active" if is_active else "disabled"
        status_cls = "active" if is_active else "stale"
        action_label = "Disable" if is_active else "Enable"
        action_value = "disable" if is_active else "enable"
        badges = []
        if int(user_id) == int(current_id or 0):
            badges.append('<span class="vm-state active">CURRENT</span>')
        if clean_role(role) == 'admin' and is_active and is_last_enabled_admin(user_id):
            badges.append('<span class="vm-state stale">LAST ADMIN</span>')
        badge_html = " ".join(badges)
        body += f"""
        <tr>
            <td>{int(user_id)}</td>
            <td class="mono"><b>{escape(username)}</b> {badge_html}</td>
            <td>{escape(role)}</td>
            <td><span class="vm-state {status_cls}">{escape(status.upper())}</span></td>
            <td>{fmt_full(created_at)}</td>
            <td>{fmt_full(last_login)}</td>
            <td>
                <form class="inline-form" method="post" action="{url_for('admin_user_action')}" onsubmit="return confirm('Update this user?')">
                    <input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}">
                    <input type="hidden" name="user_id" value="{int(user_id)}">
                    <input type="hidden" name="action" value="reset_password">
                    <input name="new_password" type="password" placeholder="New password" autocomplete="new-password">
                    <select name="role">
                        <option value="viewer" {'selected' if role == 'viewer' else ''}>viewer</option>
                        <option value="admin" {'selected' if role == 'admin' else ''}>admin</option>
                        {"<option value=\"super_admin\" selected>super_admin</option>" if role == "super_admin" and clean_role(dashboard_role()) == "super_admin" else ""}
                    </select>
                    <button class="btn" type="submit">Reset</button>
                </form>
                {admin_form(url_for('admin_user_action'), action_label, {'user_id': user_id, 'action': action_value}, danger=False, confirm=f'{action_label} this user?')}
                {admin_form(url_for('admin_user_action'), 'Delete', {'user_id': user_id, 'action': 'delete'}, danger=True, confirm='Delete this dashboard user?')}
            </td>
        </tr>
        """

    if not body:
        body = '<tr><td colspan="7" class="empty">No dashboard users</td></tr>'

    content = f"""
    <div class="card">
        <h3>Dashboard Users</h3>
        <a href="{url_for('admin_page')}">Back to Admin</a>
        <a href="{url_for('admin_logs_page', type='account')}">Account logs</a>
        <div class="admin-note">Viewer users can access dashboard pages only. Admin users can also access /admin. Safety rules: you cannot disable/delete your own account, and the last enabled admin cannot be disabled, deleted, or downgraded to viewer.</div>
    </div>

    <div class="card">
        <h3>Create User</h3>
        <form method="post" action="{url_for('admin_create_user')}" onsubmit="return confirm('Create this user?')">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}">
            <div class="form-grid">
                <div>
                    <label>Username</label>
                    <input name="username" autocomplete="username" required>
                </div>
                <div>
                    <label>Password</label>
                    <input name="password" type="password" autocomplete="new-password" required>
                </div>
                <div>
                    <label>Role</label>
                    <select name="role">
                        <option value="viewer">viewer</option>
                        <option value="admin">admin</option>
                    </select>
                </div>
                <div>
                    <button class="btn" type="submit">Create user</button>
                </div>
            </div>
        </form>
    </div>

    <div class="card">
        <div class="table-title-row">
            <h3>Users</h3>
            <div class="count-badges"><span>Users <b>{len(users)}</b></span></div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>USERNAME</th>
                    <th>ROLE</th>
                    <th>STATUS</th>
                    <th>CREATED</th>
                    <th>LAST LOGIN</th>
                    <th>ACTION</th>
                </tr>
            </thead>
            <tbody>{body}</tbody>
        </table>
    </div>
    """
    return page("Dashboard Users", content)

@app.route("/admin/users/create", methods=["POST"])
def admin_create_user():
    deny = require_admin()
    if deny:
        return deny

    username = clean_username(request.form.get("username"))
    password = request.form.get("password") or ""
    role = clean_role(request.form.get("role"))
    if role == "super_admin" and not clean_role(dashboard_role()) == "super_admin":
        return Response("Forbidden role assignment\n", status=403, mimetype="text/plain")
    if not username or len(username) < 3:
        return Response("Username must be at least 3 characters\n", status=400, mimetype="text/plain")
    if len(password) < 10:
        return Response("Password must be at least 10 characters\n", status=400, mimetype="text/plain")
    upsert_dashboard_user(username, password, role=role, is_active=1)
    log_account_event("user_created", username=username, realm="admin", role=role, detail=f"created_by={session.get('admin_username') or dashboard_username()}")
    return redirect(url_for("admin_users_page"))

@app.route("/admin/users/action", methods=["POST"])
def admin_user_action():
    deny = require_admin()
    if deny:
        return deny

    user_id = safe_int(request.form.get("user_id"), 0)
    action = (request.form.get("action") or "").strip()
    if user_id <= 0:
        return Response("Missing user_id\n", status=400, mimetype="text/plain")

    conn = db()
    try:
        row = conn.execute("SELECT username, role, is_active FROM dashboard_users WHERE id=?", (user_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return Response("User not found\n", status=404, mimetype="text/plain")
    username, old_role, old_is_active = row
    if clean_role(dashboard_role()) == "admin" and clean_role(old_role) == "super_admin":
        return Response("User not found\n", status=404, mimetype="text/plain")
    current_id = current_dashboard_user_id()

    if action in ("disable", "delete") and int(user_id) == int(current_id or 0):
        return Response("Safety block: you cannot disable or delete the account you are currently using.\n", status=400, mimetype="text/plain")

    if action in ("disable", "delete") and is_last_enabled_admin(user_id):
        return Response("Safety block: you cannot disable or delete the last enabled admin. Create another admin first.\n", status=400, mimetype="text/plain")

    if action == "disable":
        set_dashboard_user_status(user_id, 0)
        log_account_event("user_disabled", username=username, realm="admin", role=old_role)
    elif action == "enable":
        set_dashboard_user_status(user_id, 1)
        log_account_event("user_enabled", username=username, realm="admin", role=old_role)
    elif action == "delete":
        delete_dashboard_user(user_id)
        log_account_event("user_deleted", username=username, realm="admin", role=old_role)
    elif action == "reset_password":
        new_password = request.form.get("new_password") or ""
        role = clean_role(request.form.get("role") or old_role)
        if role == "super_admin" and not clean_role(dashboard_role()) == "super_admin":
            return Response("Forbidden role assignment\n", status=403, mimetype="text/plain")
        if len(new_password) < 10:
            return Response("New password must be at least 10 characters\n", status=400, mimetype="text/plain")
        if clean_role(old_role) == "admin" and role != "admin" and is_last_enabled_admin(user_id):
            return Response("Safety block: you cannot downgrade the last enabled admin to viewer. Create another admin first.\n", status=400, mimetype="text/plain")
        reset_dashboard_user_password(user_id, new_password, role=role)
        log_account_event("user_password_reset", username=username, realm="admin", role=role)
    else:
        return Response("Invalid action\n", status=400, mimetype="text/plain")

    return redirect(url_for("admin_users_page"))

@app.route("/admin/logs")
def admin_logs_page():
    deny = require_admin()
    if deny:
        return deny

    log_type = clean_log_type(request.args.get("type") or "account")
    q = (request.args.get("q") or "").strip()
    limit = clean_log_limit(request.args.get("limit"))
    page_no = clean_page(request.args.get("page"))

    tabs = f"""
    <div class="scope-links">
        <a class="{'active' if log_type == 'account' else ''}" href="{url_for('admin_logs_page', type='account', q=q, limit=limit, page=1)}">Account Login Logs</a>
        <a class="{'active' if log_type == 'node' else ''}" href="{url_for('admin_logs_page', type='node', q=q, limit=limit, page=1)}">Node Agent Logs</a>
    </div>
    """

    if log_type == "node":
        rows, total_rows, limit, page_no = node_log_rows(q=q, limit=limit, page_no=page_no)
        total_pages = max(1, int(math.ceil((total_rows or 0) / limit)))
        if page_no > total_pages:
            return redirect(url_for('admin_logs_page', type=log_type, q=q, limit=limit, page=total_pages))
        body = ""
        for log_id, ts, event, node, source_ip, status_code, vm_count, iface_count, detail in rows:
            body += f"""
            <tr>
                <td><input class="log-check" type="checkbox" name="log_id" value="{int(log_id)}"></td>
                <td>{fmt_full(ts)}</td>
                <td>{escape(event or '-')}</td>
                <td class="mono">{escape(node or '-')}</td>
                <td class="mono">{escape(source_ip or '-')}</td>
                <td>{status_code or '-'}</td>
                <td>{vm_count or 0}</td>
                <td>{iface_count or 0}</td>
                <td>{escape(detail or '')}</td>
            </tr>
            """
        if not body:
            body = '<tr><td colspan="9" class="empty">No node logs</td></tr>'
        pagination = pagination_links('admin_logs_page', page_no, total_rows, limit, type=log_type, q=q)
        table = f"""
        <div class="card">
            <div class="table-title-row">
                <h3>Node Agent Logs</h3>
                <div class="count-badges"><span>Total <b>{total_rows}</b></span><span>Page <b>{page_no}</b></span><span>Rows/page <b>{limit}</b></span></div>
            </div>
            <form id="logs-bulk-form" method="post" action="{url_for('admin_logs_clear')}" onsubmit="return confirm('Clear selected logs or all matching filtered logs?')">
                <input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}">
                <input type="hidden" name="type" value="{escape(log_type, quote=True)}">
                <input type="hidden" name="q" value="{escape(q, quote=True)}">
                <input type="hidden" name="limit" value="{limit}">
                <input type="hidden" name="page" value="{page_no}">
                <div class="bulk-bar">
                    <label><input id="log-select-all" type="checkbox" onclick="document.querySelectorAll('input[name=log_id]').forEach(cb => cb.checked = this.checked)"> Select all on this page</label>
                    <button class="btn-danger" type="submit" name="mode" value="selected">Clear selected</button>
                    <button class="btn-danger" type="submit" name="mode" value="matching">Clear all matching filter</button>
                </div>
                <table>
                    <thead><tr><th>SELECT</th><th>TIME</th><th>EVENT</th><th>NODE</th><th>SOURCE IP</th><th>HTTP</th><th>VM</th><th>IFACES</th><th>DETAIL</th></tr></thead>
                    <tbody>{body}</tbody>
                </table>
            </form>
            {pagination}
            <div class="table-hint">Node logs are separate from account logs. Use pagination for long history. Clear selected removes checked rows; Clear all matching filter removes all rows matching the current search.</div>
        </div>
        """
    else:
        rows, total_rows, limit, page_no = account_log_rows(q=q, limit=limit, page_no=page_no)
        total_pages = max(1, int(math.ceil((total_rows or 0) / limit)))
        if page_no > total_pages:
            return redirect(url_for('admin_logs_page', type=log_type, q=q, limit=limit, page=total_pages))
        body = ""
        for log_id, ts, realm, event, username, role, source_ip, path, detail in rows:
            body += f"""
            <tr>
                <td><input class="log-check" type="checkbox" name="log_id" value="{int(log_id)}"></td>
                <td>{fmt_full(ts)}</td>
                <td>{escape(realm or '-')}</td>
                <td>{escape(event or '-')}</td>
                <td class="mono">{escape(username or '-')}</td>
                <td>{escape(role or '-')}</td>
                <td class="mono">{escape(source_ip or '-')}</td>
                <td>{escape(path or '-')}</td>
                <td>{escape(detail or '')}</td>
            </tr>
            """
        if not body:
            body = '<tr><td colspan="9" class="empty">No account logs</td></tr>'
        pagination = pagination_links('admin_logs_page', page_no, total_rows, limit, type=log_type, q=q)
        table = f"""
        <div class="card">
            <div class="table-title-row">
                <h3>Account Login Logs</h3>
                <div class="count-badges"><span>Total <b>{total_rows}</b></span><span>Page <b>{page_no}</b></span><span>Rows/page <b>{limit}</b></span></div>
            </div>
            <form id="logs-bulk-form" method="post" action="{url_for('admin_logs_clear')}" onsubmit="return confirm('Clear selected logs or all matching filtered logs?')">
                <input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}">
                <input type="hidden" name="type" value="{escape(log_type, quote=True)}">
                <input type="hidden" name="q" value="{escape(q, quote=True)}">
                <input type="hidden" name="limit" value="{limit}">
                <input type="hidden" name="page" value="{page_no}">
                <div class="bulk-bar">
                    <label><input id="log-select-all" type="checkbox" onclick="document.querySelectorAll('input[name=log_id]').forEach(cb => cb.checked = this.checked)"> Select all on this page</label>
                    <button class="btn-danger" type="submit" name="mode" value="selected">Clear selected</button>
                    <button class="btn-danger" type="submit" name="mode" value="matching">Clear all matching filter</button>
                </div>
                <table>
                    <thead><tr><th>SELECT</th><th>TIME</th><th>REALM</th><th>EVENT</th><th>USERNAME</th><th>ROLE</th><th>SOURCE IP</th><th>PATH</th><th>DETAIL</th></tr></thead>
                    <tbody>{body}</tbody>
                </table>
            </form>
            {pagination}
            <div class="table-hint">Account logs include dashboard/admin login, logout, failed login, and user-management actions. Use pagination for long history. Clear selected removes checked rows; Clear all matching filter removes all rows matching the current search.</div>
        </div>
        """

    content = f"""
    <div class="card">
        <h3>Logs</h3>
        <a href="{url_for('admin_page')}">Back to Admin</a>
        {tabs}
        <form class="search" method="get" action="{url_for('admin_logs_page')}">
            <input type="hidden" name="type" value="{escape(log_type)}">
            <input name="q" value="{escape(q)}" placeholder="Search username / node / IP / event">
            <input name="limit" value="{limit}" style="max-width:100px; min-width:80px" placeholder="Rows/page">
            <button type="submit">Search</button>
            <a class="clear" href="{url_for('admin_logs_page', type=log_type)}">Clear search</a>
        </form>
    </div>
    {table}
    """
    return page("Logs", content)

@app.route("/admin/logs/clear", methods=["POST"])
def admin_logs_clear():
    deny = require_admin()
    if deny:
        return deny

    log_type = clean_log_type(request.form.get("type"))
    q = (request.form.get("q") or "").strip()
    limit = clean_log_limit(request.form.get("limit"))
    page_no = clean_page(request.form.get("page"))
    mode = (request.form.get("mode") or "selected").strip().lower()
    if mode not in ("selected", "matching"):
        mode = "selected"

    ids = request.form.getlist("log_id")
    deleted = delete_logs(log_type, mode=mode, ids=ids, q=q)
    actor = session.get("admin_username") or dashboard_username()
    log_account_event("logs_cleared", username=actor, realm="admin", role="admin", detail=f"type={log_type}; mode={mode}; deleted={deleted}; filter={q}")
    return redirect(url_for('admin_logs_page', type=log_type, q=q, limit=limit, page=page_no))

@app.route("/admin/system-health")
def admin_system_health_page():
    deny = require_admin()
    if deny:
        return deny
    content = f"""
    <div class="card">
        <h3>Admin</h3>
        <a href="{url_for('admin_page')}">Back to Admin</a>
        <a href="{url_for('admin_users_page')}">User management</a>
        <a href="{url_for('admin_logs_page', type='account')}">Account logs</a>
        <a href="{url_for('admin_logs_page', type='node')}">Node logs</a>
    </div>
    {monitor_system_health_card()}
    """
    return page("System Health", content)

@app.route("/admin")
def admin_page():
    deny = require_admin()
    if deny:
        return deny

    q = (request.args.get("q") or "").strip()
    dbmsg = (request.args.get("dbmsg") or "").strip()[:700]
    dberr = (request.args.get("dberr") or "").strip()[:700]
    nodes = admin_node_rows(q=q)
    vms = admin_vm_rows(q=q)

    node_body = ""
    for node, status, first_seen, last_push, deleted_at, vm_count, public_ipv4, private_ipv4 in nodes:
        is_hidden = (status == 'hidden') or bool(deleted_at)
        row_cls = 'stale-row' if is_hidden else ''
        checked_value = escape(node, quote=True)
        node_body += f"""
        <tr class="{row_cls}">
            <td><input class="node-select" form="bulk-nodes-form" type="checkbox" name="nodes" value="{checked_value}"></td>
            <td class="mono"><b>{escape(node)}</b></td>
            <td class="mono">{escape(compact_ipv4(public_ipv4) or '-')}</td>
            <td class="mono">{escape(compact_ipv4(private_ipv4) or '-')}</td>
            <td>{escape(status or '-')}</td>
            <td>{fmt_full(last_push)}</td>
            <td>{vm_count or 0}</td>
            <td>
                {admin_form(url_for('admin_delete_node'), 'Hide node', {'node': node, 'mode': 'soft'}, danger=True, confirm='Hide node from dashboard? Raw usage is kept.')}
                {admin_form(url_for('admin_delete_node'), 'Purge node', {'node': node, 'mode': 'purge'}, danger=True, confirm='PURGE NODE: permanently delete this node, all VMs, metrics, billing, snapshots and node logs?')}
                {admin_form(url_for('admin_purge_node_vms'), 'Purge all VM of node', {'node': node}, danger=True, confirm='Purge every VM and VM history under this node, but keep node host, NIC, agent and node records?')}
                {admin_form(url_for('admin_restore_node'), 'Restore', {'node': node}, danger=False, confirm='Restore node to dashboard?')}
            </td>
        </tr>
        """
    if not node_body:
        node_body = '<tr><td colspan="8" class="empty">No nodes</td></tr>'

    vm_body = ""
    stale_before = now_ts() - VM_STALE_SECONDS
    for node, vm_uuid, status, last_seen, last_bridge, last_iface, deleted_at, public_ipv4, private_ipv4 in vms:
        row_cls = 'stale-row' if (last_seen or 0) < stale_before or deleted_at or status == 'hidden' else ''
        vm_value = escape(f"{node}	{vm_uuid}", quote=True)
        vm_body += f"""
        <tr class="{row_cls}">
            <td><input class="vm-select" form="bulk-vms-form" type="checkbox" name="vms" value="{vm_value}"></td>
            <td class="mono">{escape(node)}</td>
            <td class="mono">{escape(compact_ipv4(public_ipv4) or '-')}</td>
            <td class="mono">{escape(compact_ipv4(private_ipv4) or '-')}</td>
            <td class="mono"><b>{escape(vm_uuid)}</b></td>
            <td>{escape(status or '-')}</td>
            <td>{fmt_full(last_seen)}</td>
            <td>{escape(last_bridge or '-')}</td>
            <td>{escape(last_iface or '-')}</td>
            <td>
                {admin_form(url_for('admin_delete_vm'), 'Hide VM', {'node': node, 'vm_uuid': vm_uuid, 'mode': 'soft'}, danger=True, confirm='Hide VM from dashboard? Raw usage is kept.')}
                {admin_form(url_for('admin_delete_vm'), 'Purge VM', {'node': node, 'vm_uuid': vm_uuid, 'mode': 'purge'}, danger=True, confirm='PURGE VM: permanently delete only this VM and all of its history on this node?')}
                {admin_form(url_for('admin_restore_vm'), 'Restore', {'node': node, 'vm_uuid': vm_uuid}, danger=False, confirm='Restore VM to dashboard?')}
            </td>
        </tr>
        """
    if not vm_body:
        vm_body = '<tr><td colspan="10" class="empty">No VMs</td></tr>'

    content = f"""
    <div class="card">
        <h3>Admin</h3>
        <a href="{url_for('index')}">Back to dashboard</a>
        <a href="{url_for('admin_users_page')}">User management</a>
        <a href="{url_for('admin_logs_page', type='account')}">Account logs</a>
        <a href="{url_for('admin_logs_page', type='node')}">Node logs</a>
        <a href="{url_for('admin_system_health_page')}">System Health</a>
        <a href="{url_for('admin_abuse_page')}">Abuse Management</a>
        <a href="{url_for('admin_change_password')}">Change password</a>
        <a href="{url_for('admin_logout')}">Logout</a>
        <div class="admin-note">
            Auto policy: VM &gt; 3d no push = stale/grey/bottom. VM &gt; 15d = hidden. Node &gt; 7d no push = hidden. Raw usage is kept unless using Purge. Manual Hide is sticky and will not be undone by new /push.
        </div>
        <div class="admin-note bulk-queue-note"><b>Purge queue:</b> destructive node/VM purges are processed outside the web request. Bulk selections are stored in one job and processed internally in batches of at most {MAX_PURGE_ITEMS_PER_JOB} items.</div>
        <form class="search" method="get" action="{url_for('admin_page')}">
            <input name="q" value="{escape(q)}" placeholder="Search node / IPv4 / MAC / VM UUID / bridge / interface">
            <button type="submit">Search</button>
            <a class="clear" href="{url_for('admin_page')}">Clear</a>
        </form>
        <div class="table-hint">Search matches node name, public/private IPv4, VM UUID, bridge and interface.</div>
        {admin_form(url_for('admin_run_cleanup'), 'Run cleanup now', {}, danger=False, confirm='Run auto cleanup rules now?')}
    </div>

    {abuse_settings_admin_card()}

    {monitor_system_health_card()}

    {database_maintenance_card(dbmsg, dberr)}

    <div class="card">
        <div class="table-title-row">
            <h3>Nodes</h3>
            <div class="count-badges"><span>Nodes <b>{len(nodes)}</b></span></div>
        </div>
        <form id="bulk-nodes-form" method="post" action="{url_for('admin_bulk_nodes')}" onsubmit="return confirm('Apply selected node action?')">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}">
            <div class="bulk-bar">
                <label><input type="checkbox" onclick="document.querySelectorAll('.node-select').forEach(cb => cb.checked = this.checked)"> Select all</label>
                <select name="action">
                    <option value="hide">Hide selected nodes</option>
                    <option value="restore">Restore selected nodes</option>
                    <option value="purge_vms">Purge all VM of selected nodes</option>
                    <option value="purge">Purge selected nodes</option>
                </select>
                <button class="btn-danger" type="submit">Apply to selected</button>
            </div>
        </form>
        <table>
            <thead>
                <tr>
                    <th></th>
                    <th>NODE</th>
                    <th>PUBLIC IPv4</th>
                    <th>PRIVATE IPv4</th>
                    <th>STATUS</th>
                    <th>LAST PUSH</th>
                    <th>VM</th>
                    <th>ACTION</th>
                </tr>
            </thead>
            <tbody>{node_body}</tbody>
        </table>
    </div>

    <div class="card">
        <div class="table-title-row">
            <h3>VMs</h3>
            <div class="count-badges"><span>VM <b>{len(vms)}</b></span></div>
        </div>
        <form id="bulk-vms-form" method="post" action="{url_for('admin_bulk_vms')}" onsubmit="return confirm('Apply selected VM action?')">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}">
            <div class="bulk-bar">
                <label><input type="checkbox" onclick="document.querySelectorAll('.vm-select').forEach(cb => cb.checked = this.checked)"> Select all</label>
                <select name="action">
                    <option value="hide">Hide selected VM</option>
                    <option value="restore">Restore selected VM</option>
                    <option value="purge">Purge selected VM</option>
                </select>
                <button class="btn-danger" type="submit">Apply to selected</button>
            </div>
        </form>
        <table>
            <thead>
                <tr>
                    <th></th>
                    <th>NODE</th>
                    <th>PUBLIC IPv4</th>
                    <th>PRIVATE IPv4</th>
                    <th>VM UUID</th>
                    <th>STATUS</th>
                    <th>LAST SEEN</th>
                    <th>BRIDGE</th>
                    <th>IFACE</th>
                    <th>ACTION</th>
                </tr>
            </thead>
            <tbody>{vm_body}</tbody>
        </table>
    </div>
    """
    # The VM Abuse Policy card is rendered directly near the top of content.
    # v48.8.0/v48.8.1 attempted to inject before </main>, but this layout
    # uses <div id="bw-content"> and has no </main>, so the card was invisible.
    return page("Admin", content)

@app.route("/admin/database-maintenance", methods=["POST"])
@app.route("/admin/database-maintenance", methods=["POST"])
def admin_database_maintenance():
    deny = require_admin()
    if deny:
        return deny
    action = (request.form.get("action") or "").strip().lower()
    actor = dashboard_username() or get_admin_username()
    parameters = {}
    try:
        if action in {"delete_history", "delete_compact"}:
            required = "DELETE AND VACUUM" if action == "delete_compact" else "DELETE HISTORY"
            if (request.form.get("confirm_text") or "").strip() != required:
                raise ValueError(f"Confirmation text must be {required}")
            days = safe_int(request.form.get("days"), 7)
            if days not in {1, 2, 3, 7}:
                raise ValueError("Unsupported history age")
            parameters["days"] = days
        elif action == "vacuum":
            if (request.form.get("confirm_text") or "").strip() != "VACUUM":
                raise ValueError("Confirmation text must be VACUUM")
        elif action == "retention":
            parameters["raw_days"] = RAW_RETENTION_DAYS
            parameters["hourly_days"] = HOURLY_RETENTION_DAYS
        elif action == "clear_monitoring_data":
            if (request.form.get("confirm_text") or "").strip() != "CLEAR ALL MONITORING DATA":
                raise ValueError("Confirmation text must be CLEAR ALL MONITORING DATA")
        elif action == "reset_app_data":
            if (request.form.get("confirm_text") or "").strip() != "RESET ALL APP DATA":
                raise ValueError("Confirmation text must be RESET ALL APP DATA")
            parameters["clear_queue"] = True
            parameters["clear_account_logs"] = True
        else:
            raise ValueError("Unknown database maintenance action")
        job_id, unit_name = enqueue_maintenance_job(action, parameters, actor)
        msg = f"Started maintenance job #{job_id} ({action}) as {unit_name}."
        log_account_event(
            "database_maintenance_queued",
            username=actor,
            realm="admin",
            role="admin",
            detail=msg,
        )
        return redirect(url_for("admin_page", section="maintenance", dbmsg=msg) + "#maintenance-queue")
    except Exception as exc:
        err = f"Could not start maintenance: {exc}"
        log_account_event(
            "database_maintenance_queue_failed",
            username=actor,
            realm="admin",
            role="admin",
            detail=err[:500],
        )
        return redirect(url_for("admin_page", section="maintenance", dberr=err) + "#maintenance-queue")

def _delete_count(conn, sql, params=()):
    """Execute one DELETE statement and return a stable non-negative row count."""
    cur = conn.execute(sql, params)
    return max(0, int(cur.rowcount or 0))

def _collect_node_vm_uuids(conn, node):
    """Return all real VM UUIDs that still reference a node in any VM table."""
    rows = conn.execute("""
        SELECT DISTINCT vm_uuid
        FROM (
            SELECT vm_uuid FROM vm_inventory WHERE node=:node
            UNION
            SELECT vm_uuid FROM vm_node_presence WHERE node=:node
            UNION
            SELECT vm_uuid FROM vm_latest_metrics WHERE node=:node
            UNION
            SELECT vm_uuid FROM vm_perf_stats WHERE node=:node
            UNION
            SELECT vm_uuid FROM node_stats WHERE node=:node
            UNION
            SELECT vm_uuid FROM usage WHERE node=:node
            UNION
            SELECT vm_uuid FROM bandwidth_hourly WHERE node=:node
            UNION
            SELECT vm_uuid FROM bandwidth_daily WHERE node=:node
            UNION
            SELECT vm_uuid FROM vm_location_latest
            WHERE node=:node OR previous_node=:node
            UNION
            SELECT vm_uuid FROM vm_migration_events
            WHERE old_node=:node OR new_node=:node
        )
        WHERE vm_uuid IS NOT NULL
          AND TRIM(vm_uuid) != ''
          AND vm_uuid != '-'
    """, {"node": node}).fetchall()
    return sorted({str(row[0]).strip() for row in rows if row and row[0]})

def _repair_vm_location_after_purge(conn, vm_uuid, removed_node):
    """Repair or remove the global VM location after purging one node's copy.

    A UUID can temporarily exist on more than one node during migration. Purging
    the old-node copy must not delete the current location on another node.
    """
    location = conn.execute("""
        SELECT node, previous_node
        FROM vm_location_latest
        WHERE vm_uuid=?
    """, (vm_uuid,)).fetchone()
    if not location:
        return

    current_node, previous_node = location
    if current_node != removed_node:
        if previous_node == removed_node:
            conn.execute("""
                UPDATE vm_location_latest
                SET previous_node=NULL
                WHERE vm_uuid=?
            """, (vm_uuid,))
        return

    remaining = conn.execute("""
        SELECT node, last_seen, last_iface, last_bridge
        FROM (
            SELECT
                node,
                last_seen,
                last_iface,
                last_bridge,
                0 AS source_priority
            FROM vm_node_presence
            WHERE vm_uuid=?
              AND node!=?
              AND COALESCE(status, 'active')!='purged'

            UNION ALL

            SELECT
                node,
                last_seen,
                last_iface,
                last_bridge,
                1 AS source_priority
            FROM vm_inventory
            WHERE vm_uuid=?
              AND node!=?
              AND COALESCE(status, 'active')!='hidden'
              AND deleted_at IS NULL

            UNION ALL

            SELECT
                node,
                last_seen,
                iface AS last_iface,
                bridge AS last_bridge,
                2 AS source_priority
            FROM vm_latest_metrics
            WHERE vm_uuid=?
              AND node!=?
        )
        ORDER BY last_seen DESC, source_priority ASC
        LIMIT 1
    """, (
        vm_uuid, removed_node,
        vm_uuid, removed_node,
        vm_uuid, removed_node,
    )).fetchone()

    if remaining:
        new_node, last_seen, last_iface, last_bridge = remaining
        conn.execute("""
            UPDATE vm_location_latest
            SET node=?,
                previous_node=NULL,
                moved_at=NULL,
                last_seen=?,
                last_iface=?,
                last_bridge=?,
                alert_level='ok',
                alert_flags=''
            WHERE vm_uuid=?
        """, (
            new_node,
            int(last_seen or now_ts()),
            last_iface or '-',
            last_bridge or '-',
            vm_uuid,
        ))
    else:
        conn.execute("DELETE FROM vm_location_latest WHERE vm_uuid=?", (vm_uuid,))

def _refresh_node_snapshot_vm_counts(conn, node):
    """Recalculate VM/interface counts while preserving node push snapshots."""
    conn.execute("""
        UPDATE node_push_snapshots
        SET vm_count=MAX(
                COALESCE((
                    SELECT COUNT(DISTINCT ns.vm_uuid)
                    FROM node_stats ns
                    WHERE ns.node=node_push_snapshots.node
                      AND ns.bucket=node_push_snapshots.bucket
                      AND ns.vm_uuid IS NOT NULL
                      AND ns.vm_uuid!='-'
                ), 0),
                COALESCE((
                    SELECT COUNT(DISTINCT vp.vm_uuid)
                    FROM vm_perf_stats vp
                    WHERE vp.node=node_push_snapshots.node
                      AND vp.bucket=node_push_snapshots.bucket
                      AND vp.vm_uuid IS NOT NULL
                      AND vp.vm_uuid!='-'
                ), 0)
            ),
            iface_count=COALESCE((
                SELECT COUNT(DISTINCT ns.bridge || ':' || ns.iface)
                FROM node_stats ns
                WHERE ns.node=node_push_snapshots.node
                  AND ns.bucket=node_push_snapshots.bucket
            ), 0)
        WHERE node=?
    """, (node,))

def purge_all_vms_for_node(conn, node):
    """Delete every VM and VM history under a node, but keep the node itself.

    Preserved:
    - node_inventory
    - node host CPU/RAM/disk/filesystem metrics
    - physical NIC metrics
    - agent health
    - node push snapshots/receipts/logs
    """
    vm_uuids = _collect_node_vm_uuids(conn, node)
    deleted = {}

    # Remove all VM-scoped current caches and Abuse history for this node.
    # Node host/filesystem/storage metrics remain intact by design.
    for table in (
        "vm_iface_current",
        "vm_current_fast",
        "vm_abuse_state",
        "vm_abuse_events",
        "vm_abuse_incidents",
    ):
        deleted[table] = _delete_count(conn, f"DELETE FROM {table} WHERE node=?", (node,))

    # VM network/performance history and latest caches.
    deleted["usage"] = _delete_count(
        conn, "DELETE FROM usage WHERE node=?", (node,)
    )
    deleted["node_stats"] = _delete_count(
        conn, "DELETE FROM node_stats WHERE node=?", (node,)
    )
    deleted["vm_perf_stats"] = _delete_count(
        conn, "DELETE FROM vm_perf_stats WHERE node=?", (node,)
    )
    deleted["vm_latest_metrics"] = _delete_count(
        conn, "DELETE FROM vm_latest_metrics WHERE node=?", (node,)
    )

    # VM billing history for this node.
    deleted["bandwidth_hourly"] = _delete_count(
        conn, "DELETE FROM bandwidth_hourly WHERE node=?", (node,)
    )
    deleted["bandwidth_daily"] = _delete_count(
        conn, "DELETE FROM bandwidth_daily WHERE node=?", (node,)
    )

    # VM lifecycle/inventory state.
    deleted["vm_node_presence"] = _delete_count(
        conn, "DELETE FROM vm_node_presence WHERE node=?", (node,)
    )
    deleted["vm_inventory"] = _delete_count(
        conn, "DELETE FROM vm_inventory WHERE node=?", (node,)
    )
    deleted["vm_migration_events"] = _delete_count(
        conn,
        "DELETE FROM vm_migration_events WHERE old_node=? OR new_node=?",
        (node, node),
    )
    ensure_disk_io_schema(conn)
    deleted["vm_disk_current"] = _delete_count(
        conn, "DELETE FROM vm_disk_current WHERE node=?", (node,)
    )

    for vm_uuid in vm_uuids:
        _repair_vm_location_after_purge(conn, vm_uuid, node)

    # The push rows are node-level history and remain. Their VM counters must no
    # longer advertise purged VMs.
    conn.execute("""
        UPDATE node_push_snapshots
        SET vm_count=0,
            iface_count=0
        WHERE node=?
    """, (node,))

    deleted["vm_uuids"] = len(vm_uuids)
    return deleted

def purge_node_data(conn, node):
    """Permanently delete every database row belonging to one node."""
    deleted = purge_all_vms_for_node(conn, node)

    for table in (
        "node_host_stats",
        "node_host_latest",
        "node_filesystem_stats",
        "node_filesystem_latest",
        "node_physical_net_stats",
        "node_physical_net_latest",
        "node_storage_current",
        "node_bridge_addresses_latest",
        "agent_health_stats",
        "agent_health_latest",
        "node_push_snapshots",
        "push_receipts",
        "node_missed_events",
        "node_logs",
        "node_inventory",
    ):
        deleted[table] = _delete_count(
            conn,
            f"DELETE FROM {table} WHERE node=?",
            (node,),
        )

    return deleted

@app.route("/admin/cleanup", methods=["POST"])
def admin_run_cleanup():
    deny = require_admin()
    if deny:
        return deny
    auto_cleanup_inventory()
    return redirect(url_for("admin_page", section="nodes"))

@app.route("/admin/delete_vm", methods=["POST"])
def admin_delete_vm():
    deny = require_admin()
    if deny:
        return deny

    node = (request.form.get("node") or "").strip()
    vm_uuid = (request.form.get("vm_uuid") or "").strip()
    mode = (request.form.get("mode") or "soft").strip()
    if not node or not vm_uuid:
        return Response("Missing node or vm_uuid\n", status=400, mimetype="text/plain")

    actor = session.get("admin_username") or dashboard_username()
    if mode == "purge":
        conn = db()
        previous = None
        try:
            previous = conn.execute("SELECT status,hidden_at FROM vm_inventory WHERE node=? AND vm_uuid=?", (node, vm_uuid)).fetchone()
            conn.execute("UPDATE vm_inventory SET status='hidden', hidden_at=COALESCE(hidden_at, ?) WHERE node=? AND vm_uuid=?", (now_ts(), node, vm_uuid))
            conn.commit()
        finally:
            conn.close()
        try:
            jobs = enqueue_batched_purge_jobs("purge_vms", [{"node": node, "vm_uuid": vm_uuid}], actor)
            msg = f"Queued VM purge job #{jobs[0][0]} for {node}/{vm_uuid}."
            log_account_event("vm_purge_queued", username=actor, realm="admin", role="admin", detail=msg)
            return redirect(url_for("admin_page", section="maintenance", dbmsg=msg) + "#maintenance-queue")
        except Exception as exc:
            conn = db()
            try:
                if previous:
                    conn.execute("UPDATE vm_inventory SET status=?, hidden_at=? WHERE node=? AND vm_uuid=?", (previous[0], previous[1], node, vm_uuid))
                conn.commit()
            finally:
                conn.close()
            err = f"Could not queue VM purge: {exc}"
            log_account_event("vm_purge_queue_failed", username=actor, realm="admin", role="admin", detail=err[:500])
            return redirect(url_for("admin_page", section="maintenance", dberr=err) + "#maintenance-queue")

    conn = db()
    try:
        conn.execute("""
            UPDATE vm_inventory
            SET status='hidden', hidden_at=COALESCE(hidden_at, ?), deleted_at=NULL
            WHERE node=? AND vm_uuid=?
        """, (now_ts(), node, vm_uuid))
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("admin_page", section="vms"))

@app.route("/admin/restore_vm", methods=["POST"])
def admin_restore_vm():
    deny = require_admin()
    if deny:
        return deny

    node = (request.form.get("node") or "").strip()
    vm_uuid = (request.form.get("vm_uuid") or "").strip()
    conn = db()
    try:
        conn.execute("""
            UPDATE vm_inventory
            SET status='active', hidden_at=NULL, deleted_at=NULL
            WHERE node=? AND vm_uuid=?
        """, (node, vm_uuid))
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("admin_page", section="vms"))

@app.route("/admin/delete_node", methods=["POST"])
def admin_delete_node():
    deny = require_admin()
    if deny:
        return deny

    node = (request.form.get("node") or "").strip()
    mode = (request.form.get("mode") or "soft").strip()
    if not node:
        return Response("Missing node\n", status=400, mimetype="text/plain")

    actor = session.get("admin_username") or dashboard_username()
    if mode == "purge":
        conn = db()
        previous = None
        try:
            previous = conn.execute("SELECT status,hidden_at FROM node_inventory WHERE node=?", (node,)).fetchone()
            conn.execute("UPDATE node_inventory SET status='hidden', hidden_at=COALESCE(hidden_at, ?) WHERE node=?", (now_ts(), node))
            conn.commit()
        finally:
            conn.close()
        try:
            jobs = enqueue_batched_purge_jobs("purge_nodes", [node], actor)
            msg = f"Queued node purge job #{jobs[0][0]} for {node}."
            log_account_event("node_purge_queued", username=actor, realm="admin", role="admin", detail=msg)
            return redirect(url_for("admin_page", section="maintenance", dbmsg=msg) + "#maintenance-queue")
        except Exception as exc:
            conn = db()
            try:
                if previous:
                    conn.execute("UPDATE node_inventory SET status=?, hidden_at=? WHERE node=?", (previous[0], previous[1], node))
                conn.commit()
            finally:
                conn.close()
            err = f"Could not queue node purge: {exc}"
            log_account_event("node_purge_queue_failed", username=actor, realm="admin", role="admin", detail=err[:500])
            return redirect(url_for("admin_page", section="maintenance", dberr=err) + "#maintenance-queue")

    conn = db()
    try:
        conn.execute("""
            UPDATE node_inventory
            SET status='hidden', hidden_at=COALESCE(hidden_at, ?), deleted_at=NULL
            WHERE node=?
        """, (now_ts(), node))
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("admin_page", section="nodes"))

@app.route("/admin/restore_node", methods=["POST"])
def admin_restore_node():
    deny = require_admin()
    if deny:
        return deny

    node = (request.form.get("node") or "").strip()
    conn = db()
    try:
        conn.execute("""
            UPDATE node_inventory
            SET status='active', hidden_at=NULL, deleted_at=NULL
            WHERE node=?
        """, (node,))
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("admin_page", section="nodes"))

@app.route("/admin/purge_node_vms", methods=["POST"])
def admin_purge_node_vms():
    deny = require_admin()
    if deny:
        return deny

    node = (request.form.get("node") or "").strip()
    if not node:
        return Response("Missing node\n", status=400, mimetype="text/plain")
    actor = session.get("admin_username") or dashboard_username()
    conn = db(); previous = []
    try:
        previous = conn.execute("SELECT vm_uuid,status,hidden_at FROM vm_inventory WHERE node=?", (node,)).fetchall()
        conn.execute("UPDATE vm_inventory SET status='hidden', hidden_at=COALESCE(hidden_at, ?) WHERE node=?", (now_ts(), node))
        conn.commit()
    finally:
        conn.close()
    try:
        jobs = enqueue_batched_purge_jobs("purge_node_vms", [node], actor)
        msg = f"Queued purge-all-VM job #{jobs[0][0]} for node {node}."
        log_account_event("node_vms_purge_queued", username=actor, realm="admin", role="admin", detail=msg)
        return redirect(url_for("admin_page", section="maintenance", dbmsg=msg) + "#maintenance-queue")
    except Exception as exc:
        conn = db()
        try:
            for vm_uuid, old_status, old_hidden_at in previous:
                conn.execute("UPDATE vm_inventory SET status=?, hidden_at=? WHERE node=? AND vm_uuid=?", (old_status, old_hidden_at, node, vm_uuid))
            conn.commit()
        finally:
            conn.close()
        err = f"Could not queue node VM purge: {exc}"
        log_account_event("node_vms_purge_queue_failed", username=actor, realm="admin", role="admin", detail=err[:500])
        return redirect(url_for("admin_page", section="maintenance", dberr=err) + "#maintenance-queue")

@app.route("/admin/bulk_nodes", methods=["POST"])
def admin_bulk_nodes():
    deny = require_admin()
    if deny:
        return deny

    nodes = []
    seen = set()
    for value in request.form.getlist("nodes"):
        node = value.strip()
        if node and node not in seen:
            seen.add(node)
            nodes.append(node)
    action = (request.form.get("action") or "hide").strip()
    if not nodes:
        return redirect(url_for("admin_page", section="nodes"))
    if action not in {"hide", "restore", "purge_vms", "purge"}:
        return Response("Invalid node action\n", status=400, mimetype="text/plain")

    actor = session.get("admin_username") or dashboard_username()
    if action in {"purge", "purge_vms"}:
        conn = db(); previous_nodes = []; previous_vms = []
        try:
            if action == "purge":
                placeholders = ",".join("?" for _ in nodes)
                previous_nodes = conn.execute(f"SELECT node,status,hidden_at FROM node_inventory WHERE node IN ({placeholders})", nodes).fetchall()
                for node in nodes:
                    conn.execute("UPDATE node_inventory SET status='hidden', hidden_at=COALESCE(hidden_at, ?) WHERE node=?", (now_ts(), node))
            else:
                placeholders = ",".join("?" for _ in nodes)
                previous_vms = conn.execute(f"SELECT node,vm_uuid,status,hidden_at FROM vm_inventory WHERE node IN ({placeholders})", nodes).fetchall()
                for node in nodes:
                    conn.execute("UPDATE vm_inventory SET status='hidden', hidden_at=COALESCE(hidden_at, ?) WHERE node=?", (now_ts(), node))
            conn.commit()
        finally:
            conn.close()
        queue_action = "purge_nodes" if action == "purge" else "purge_node_vms"
        try:
            jobs = enqueue_batched_purge_jobs(queue_action, nodes, actor)
            job_list = ", ".join(f"#{job_id}" for job_id, _unit, _count in jobs)
            msg = f"Queued {len(nodes)} node item(s) in exclusive purge job #{jobs[0][0]}. Internal batch size: {MAX_PURGE_ITEMS_PER_JOB}."
            log_account_event("bulk_node_purge_queued", username=actor, realm="admin", role="admin", detail=f"action={action};nodes={len(nodes)};jobs={job_list}")
            return redirect(url_for("admin_page", section="maintenance", dbmsg=msg) + "#maintenance-queue")
        except Exception as exc:
            conn = db()
            try:
                for old_node, old_status, old_hidden_at in previous_nodes:
                    conn.execute("UPDATE node_inventory SET status=?, hidden_at=? WHERE node=?", (old_status, old_hidden_at, old_node))
                for old_node, old_uuid, old_status, old_hidden_at in previous_vms:
                    conn.execute("UPDATE vm_inventory SET status=?, hidden_at=? WHERE node=? AND vm_uuid=?", (old_status, old_hidden_at, old_node, old_uuid))
                conn.commit()
            finally:
                conn.close()
            err = f"Could not queue bulk node purge: {exc}"
            log_account_event("bulk_node_purge_queue_failed", username=actor, realm="admin", role="admin", detail=err[:500])
            return redirect(url_for("admin_page", section="maintenance", dberr=err) + "#maintenance-queue")

    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for node in nodes:
            if action == "restore":
                conn.execute("""
                    UPDATE node_inventory
                    SET status='active', hidden_at=NULL, deleted_at=NULL
                    WHERE node=?
                """, (node,))
            else:
                conn.execute("""
                    UPDATE node_inventory
                    SET status='hidden', hidden_at=COALESCE(hidden_at, ?), deleted_at=NULL
                    WHERE node=?
                """, (now_ts(), node))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    log_account_event("bulk_node_action", username=actor, realm="admin", role="admin", detail=f"action={action};nodes={','.join(nodes[:100])}")
    return redirect(url_for("admin_page", section="nodes"))

@app.route("/admin/bulk_vms", methods=["POST"])
def admin_bulk_vms():
    deny = require_admin()
    if deny:
        return deny

    selected = []
    seen = set()
    for value in request.form.getlist("vms"):
        if "\t" not in value:
            continue
        node, vm_uuid = value.split("\t", 1)
        node = node.strip()
        vm_uuid = vm_uuid.strip()
        key = (node, vm_uuid)
        if node and vm_uuid and key not in seen:
            seen.add(key)
            selected.append({"node": node, "vm_uuid": vm_uuid})

    action = (request.form.get("action") or "hide").strip()
    if not selected:
        return redirect(url_for("admin_page", section="vms"))
    if action not in {"hide", "restore", "purge"}:
        return Response("Invalid VM action\n", status=400, mimetype="text/plain")

    actor = session.get("admin_username") or dashboard_username()
    if action == "purge":
        conn = db(); previous = []
        try:
            for item in selected:
                row = conn.execute("SELECT status,hidden_at FROM vm_inventory WHERE node=? AND vm_uuid=?", (item["node"], item["vm_uuid"])).fetchone()
                if row: previous.append((item["node"], item["vm_uuid"], row[0], row[1]))
                conn.execute("UPDATE vm_inventory SET status='hidden', hidden_at=COALESCE(hidden_at, ?) WHERE node=? AND vm_uuid=?", (now_ts(), item["node"], item["vm_uuid"]))
            conn.commit()
        finally:
            conn.close()
        try:
            jobs = enqueue_batched_purge_jobs("purge_vms", selected, actor)
            job_list = ", ".join(f"#{job_id}" for job_id, _unit, _count in jobs)
            msg = f"Queued {len(selected)} VM purge(s) in exclusive purge job #{jobs[0][0]}. Internal batch size: {MAX_PURGE_ITEMS_PER_JOB}."
            log_account_event("bulk_vm_purge_queued", username=actor, realm="admin", role="admin", detail=f"vms={len(selected)};jobs={job_list}")
            return redirect(url_for("admin_page", section="maintenance", dbmsg=msg) + "#maintenance-queue")
        except Exception as exc:
            conn = db()
            try:
                for old_node, old_uuid, old_status, old_hidden_at in previous:
                    conn.execute("UPDATE vm_inventory SET status=?, hidden_at=? WHERE node=? AND vm_uuid=?", (old_status, old_hidden_at, old_node, old_uuid))
                conn.commit()
            finally:
                conn.close()
            err = f"Could not queue bulk VM purge: {exc}"
            log_account_event("bulk_vm_purge_queue_failed", username=actor, realm="admin", role="admin", detail=err[:500])
            return redirect(url_for("admin_page", section="maintenance", dberr=err) + "#maintenance-queue")

    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for item in selected:
            node = item["node"]
            vm_uuid = item["vm_uuid"]
            if action == "restore":
                conn.execute("""
                    UPDATE vm_inventory
                    SET status='active', hidden_at=NULL, deleted_at=NULL
                    WHERE node=? AND vm_uuid=?
                """, (node, vm_uuid))
            else:
                conn.execute("""
                    UPDATE vm_inventory
                    SET status='hidden', hidden_at=COALESCE(hidden_at, ?), deleted_at=NULL
                    WHERE node=? AND vm_uuid=?
                """, (now_ts(), node, vm_uuid))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    affected_nodes = sorted({item["node"] for item in selected})
    log_account_event("bulk_vm_action", username=actor, realm="admin", role="admin", detail=f"action={action};selected={len(selected)};nodes={','.join(affected_nodes[:100])}")
    return redirect(url_for("admin_page", section="vms"))

@app.route("/admin/api/system-health")
def admin_api_system_health():
    deny = require_admin()
    if deny:
        return deny
    return jsonify(get_monitor_system_health())

@app.route("/health")
def health():
    return {
        "status": "ok",
        "timezone": display_timezone_name(),
        "cache": "node_stats",
    }
