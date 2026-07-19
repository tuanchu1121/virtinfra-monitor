def rebuild_cache_if_empty():
    conn = db()
    try:
        stats_count = conn.execute("SELECT COUNT(*) FROM node_stats").fetchone()[0]
        usage_count = conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0]
        if stats_count == 0 and usage_count > 0:
            conn.execute("""
            INSERT OR REPLACE INTO node_stats(
                bucket, node, bridge, iface, vm_uuid,
                rx_delta, tx_delta,
                rx_packets_delta, tx_packets_delta,
                rx_drop_delta, tx_drop_delta,
                rx_error_delta, tx_error_delta,
                interval_seconds, last_push
            )
            SELECT
                (CAST(time AS INTEGER) / ?) * ? AS bucket,
                COALESCE(NULLIF(node, ''), 'unknown') AS node,
                COALESCE(NULLIF(bridge, ''), '-') AS bridge,
                COALESCE(NULLIF(iface, ''), '-') AS iface,
                COALESCE(NULLIF(vm_uuid, ''), '-') AS vm_uuid,
                SUM(CASE WHEN rx_delta > 0 THEN rx_delta ELSE 0 END) AS rx_delta,
                SUM(CASE WHEN tx_delta > 0 THEN tx_delta ELSE 0 END) AS tx_delta,
                SUM(CASE WHEN rx_packets_delta > 0 THEN rx_packets_delta ELSE 0 END) AS rx_packets_delta,
                SUM(CASE WHEN tx_packets_delta > 0 THEN tx_packets_delta ELSE 0 END) AS tx_packets_delta,
                SUM(CASE WHEN rx_drop_delta > 0 THEN rx_drop_delta ELSE 0 END) AS rx_drop_delta,
                SUM(CASE WHEN tx_drop_delta > 0 THEN tx_drop_delta ELSE 0 END) AS tx_drop_delta,
                SUM(CASE WHEN rx_error_delta > 0 THEN rx_error_delta ELSE 0 END) AS rx_error_delta,
                SUM(CASE WHEN tx_error_delta > 0 THEN tx_error_delta ELSE 0 END) AS tx_error_delta,
                MAX(COALESCE(interval_seconds, ?)) AS interval_seconds,
                MAX(CAST(time AS INTEGER)) AS last_push
            FROM usage
            WHERE node IS NOT NULL AND node != ''
            GROUP BY
                (CAST(time AS INTEGER) / ?) * ?,
                COALESCE(NULLIF(node, ''), 'unknown'),
                COALESCE(NULLIF(bridge, ''), '-'),
                COALESCE(NULLIF(iface, ''), '-'),
                COALESCE(NULLIF(vm_uuid, ''), '-')
            """, (
                CACHE_BUCKET_SECONDS,
                CACHE_BUCKET_SECONDS,
                CACHE_BUCKET_SECONDS,
                CACHE_BUCKET_SECONDS,
                CACHE_BUCKET_SECONDS,
            ))
            conn.commit()
    finally:
        conn.close()


def rebuild_inventory_from_usage():
    """Backfill inventory from existing raw/cache data without changing usage."""
    conn = db()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO node_inventory(node, first_seen, last_push, status)
            SELECT
                COALESCE(NULLIF(node, ''), 'unknown') AS node,
                MIN(CAST(time AS INTEGER)) AS first_seen,
                MAX(CAST(time AS INTEGER)) AS last_push,
                'active' AS status
            FROM usage
            WHERE node IS NOT NULL AND node != ''
            GROUP BY COALESCE(NULLIF(node, ''), 'unknown')
        """)

        conn.execute("""
            INSERT OR IGNORE INTO vm_inventory(
                node, vm_uuid, first_seen, last_seen, last_iface, last_bridge, status
            )
            SELECT
                COALESCE(NULLIF(u.node, ''), 'unknown') AS node,
                COALESCE(NULLIF(u.vm_uuid, ''), '-') AS vm_uuid,
                MIN(CAST(u.time AS INTEGER)) AS first_seen,
                MAX(CAST(u.time AS INTEGER)) AS last_seen,
                (
                    SELECT COALESCE(NULLIF(u2.iface, ''), '-')
                    FROM usage u2
                    WHERE COALESCE(NULLIF(u2.node, ''), 'unknown') = COALESCE(NULLIF(u.node, ''), 'unknown')
                      AND COALESCE(NULLIF(u2.vm_uuid, ''), '-') = COALESCE(NULLIF(u.vm_uuid, ''), '-')
                    ORDER BY CAST(u2.time AS INTEGER) DESC, u2.id DESC
                    LIMIT 1
                ) AS last_iface,
                (
                    SELECT COALESCE(NULLIF(u3.bridge, ''), '-')
                    FROM usage u3
                    WHERE COALESCE(NULLIF(u3.node, ''), 'unknown') = COALESCE(NULLIF(u.node, ''), 'unknown')
                      AND COALESCE(NULLIF(u3.vm_uuid, ''), '-') = COALESCE(NULLIF(u.vm_uuid, ''), '-')
                    ORDER BY CAST(u3.time AS INTEGER) DESC, u3.id DESC
                    LIMIT 1
                ) AS last_bridge,
                'active' AS status
            FROM usage u
            WHERE u.node IS NOT NULL AND u.node != ''
            GROUP BY
                COALESCE(NULLIF(u.node, ''), 'unknown'),
                COALESCE(NULLIF(u.vm_uuid, ''), '-')
        """)
        conn.commit()
    finally:
        conn.close()


def auto_cleanup_inventory():
    """Compatibility no-op for request/read paths.

    Inventory expiry is executed by the dedicated background timer through
    run_inventory_cleanup_batches(). Keeping this symbol avoids changing every
    legacy caller while guaranteeing that GET/refresh requests never issue
    broad UPDATE statements against vm_inventory or node_inventory.
    """
    return {"deferred": True}


def vm_live_status(last_seen):
    if not last_seen:
        return "stale"
    age = now_ts() - int(last_seen)
    if age > VM_STALE_SECONDS:
        return "stale"
    return "active"


def admin_allowed():
    if not session.get("admin_authenticated"):
        return False
    username = session.get("admin_username") or session.get("dashboard_username") or ""
    if not username:
        return False
    user = get_dashboard_user(username)
    if not user:
        return False
    _user_id, _username, _password_hash, role, is_active, _created_at, _updated_at, _last_login = user
    return bool(is_active) and clean_role(role) == "admin"


def get_admin_setting(key, default=""):
    conn = db()
    try:
        row = conn.execute("SELECT value FROM admin_settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default
    finally:
        conn.close()


def set_admin_setting(key, value):
    conn = db()
    try:
        conn.execute("""
            INSERT INTO admin_settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """, (key, value, now_ts()))
        conn.commit()
    finally:
        conn.close()


def get_admin_username():
    return get_admin_setting("admin_username", ADMIN_USERNAME or "admin")


def get_admin_password_hash():
    # DB value wins. BW_ADMIN_PASSWORD_HASH remains a bootstrap/fallback option.
    return get_admin_setting("admin_password_hash", ADMIN_PASSWORD_HASH or "")


def admin_is_configured():
    return bool(get_admin_password_hash())


def set_admin_credentials(username, password):
    username = (username or "admin").strip() or "admin"
    set_admin_setting("admin_username", username)
    set_admin_setting("admin_password_hash", generate_password_hash(password))
    # Keep the initial admin usable for dashboard login too.
    upsert_dashboard_user(username, password, role="admin", is_active=1)


def clean_username(value):
    return (value or "").strip()


def clean_role(value):
    value = (value or "viewer").strip().lower()
    return value if value in ("viewer", "admin") else "viewer"


def client_ip():
    # Good enough for audit display. If behind a trusted reverse proxy, X-Forwarded-For/X-Real-IP helps.
    xff = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return xff or request.headers.get("X-Real-IP") or request.remote_addr or "-"


def user_agent_short():
    ua = request.headers.get("User-Agent") or "-"
    return ua[:255]


def log_account_event(event, username="", realm="dashboard", role="", detail=""):
    conn = db()
    try:
        conn.execute("""
            INSERT INTO account_logs(time, realm, event, username, role, source_ip, user_agent, path, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now_ts(),
            (realm or "dashboard")[:32],
            (event or "event")[:64],
            (username or "")[:128],
            (role or "")[:32],
            client_ip(),
            user_agent_short(),
            request.path[:255],
            (detail or "")[:500],
        ))
        # v48.12.5 hard cap: account/audit history is bounded to 7 days.
        conn.execute("DELETE FROM account_logs WHERE time < ?", (now_ts() - EVENT_RETENTION_DAYS * 86400,))
        conn.commit()
    finally:
        conn.close()


def log_node_event(event, node="", status_code=200, vm_count=0, iface_count=0, detail=""):
    conn = db()
    try:
        conn.execute("""
            INSERT INTO node_logs(time, event, node, source_ip, user_agent, status_code, vm_count, iface_count, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now_ts(),
            (event or "event")[:64],
            (node or "")[:128],
            client_ip(),
            user_agent_short(),
            int(status_code or 0),
            int(vm_count or 0),
            int(iface_count or 0),
            (detail or "")[:500],
        ))
        # v48.12.5 hard cap: node/agent logs are bounded to 7 days.
        conn.execute("DELETE FROM node_logs WHERE time < ?", (now_ts() - EVENT_RETENTION_DAYS * 86400,))
        conn.commit()
    finally:
        conn.close()


def dashboard_allowed():
    return bool(session.get("dashboard_authenticated") or session.get("admin_authenticated"))


def dashboard_username():
    return session.get("dashboard_username") or session.get("admin_username") or ""


def dashboard_role():
    return session.get("dashboard_role") or ("admin" if session.get("admin_authenticated") else "")


def require_dashboard():
    if dashboard_allowed():
        return None
    if request.path.startswith("/api/") or request.path == "/summary":
        return jsonify({"error": "login_required"}), 401
    if request.method == "POST":
        return Response("Login required\n", status=401, mimetype="text/plain")
    next_url = request.full_path if request.query_string else request.path
    return redirect(url_for("dashboard_login", next=next_url))


def get_dashboard_user(username):
    username = clean_username(username)
    if not username:
        return None
    conn = db()
    try:
        return conn.execute("""
            SELECT id, username, password_hash, role, is_active, created_at, updated_at, last_login
            FROM dashboard_users
            WHERE username=?
        """, (username,)).fetchone()
    finally:
        conn.close()


def dashboard_user_count():
    conn = db()
    try:
        return conn.execute("SELECT COUNT(*) FROM dashboard_users").fetchone()[0]
    finally:
        conn.close()


def active_admin_count(exclude_user_id=None):
    conn = db()
    try:
        if exclude_user_id is None:
            return conn.execute("""
                SELECT COUNT(*)
                FROM dashboard_users
                WHERE role='admin' AND is_active=1
            """).fetchone()[0]
        return conn.execute("""
            SELECT COUNT(*)
            FROM dashboard_users
            WHERE role='admin' AND is_active=1 AND id != ?
        """, (int(exclude_user_id),)).fetchone()[0]
    finally:
        conn.close()


def emergency_admin_needed():
    # If no enabled admin user exists, /admin/setup becomes available again.
    return active_admin_count() == 0


def get_dashboard_user_by_id(user_id):
    conn = db()
    try:
        return conn.execute("""
            SELECT id, username, password_hash, role, is_active, created_at, updated_at, last_login
            FROM dashboard_users
            WHERE id=?
        """, (int(user_id),)).fetchone()
    finally:
        conn.close()


def current_dashboard_user():
    user_id = session.get("dashboard_user_id")
    if user_id:
        row = get_dashboard_user_by_id(user_id)
        if row:
            return row
    username = dashboard_username()
    return get_dashboard_user(username) if username else None


def current_dashboard_user_id():
    row = current_dashboard_user()
    return int(row[0]) if row else 0


def is_last_enabled_admin(user_id):
    row = get_dashboard_user_by_id(user_id)
    if not row:
        return False
    _id, _username, _password_hash, role, is_active, _created_at, _updated_at, _last_login = row
    return clean_role(role) == "admin" and bool(is_active) and active_admin_count(exclude_user_id=user_id) == 0


def bootstrap_dashboard_admin_from_settings():
    # Upgrade path from older builds: reuse the existing admin password hash as a dashboard admin user.
    if dashboard_user_count() > 0:
        return
    username = get_admin_username()
    password_hash = get_admin_password_hash()
    if not password_hash:
        return
    ts = now_ts()
    conn = db()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO dashboard_users(username, password_hash, role, is_active, created_at, updated_at)
            VALUES (?, ?, 'admin', 1, ?, ?)
        """, (username, password_hash, ts, ts))
        conn.commit()
    finally:
        conn.close()


def upsert_dashboard_user(username, password, role="viewer", is_active=1):
    username = clean_username(username)
    if not username:
        raise ValueError("Username is required")
    role = clean_role(role)
    ts = now_ts()
    password_hash = generate_password_hash(password)
    conn = db()
    try:
        conn.execute("""
            INSERT INTO dashboard_users(username, password_hash, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(username)
            DO UPDATE SET
                password_hash=excluded.password_hash,
                role=excluded.role,
                is_active=excluded.is_active,
                updated_at=excluded.updated_at
        """, (username, password_hash, role, int(is_active), ts, ts))
        conn.commit()
    finally:
        conn.close()


def update_dashboard_user_login(user_id):
    conn = db()
    try:
        conn.execute("UPDATE dashboard_users SET last_login=?, updated_at=? WHERE id=?", (now_ts(), now_ts(), user_id))
        conn.commit()
    finally:
        conn.close()


def get_dashboard_users():
    conn = db()
    try:
        return conn.execute("""
            SELECT id, username, role, is_active, created_at, updated_at, last_login
            FROM dashboard_users
            ORDER BY role DESC, username COLLATE NOCASE ASC
        """).fetchall()
    finally:
        conn.close()


def set_dashboard_user_status(user_id, is_active):
    conn = db()
    try:
        conn.execute("UPDATE dashboard_users SET is_active=?, updated_at=? WHERE id=?", (int(is_active), now_ts(), int(user_id)))
        conn.commit()
    finally:
        conn.close()


def delete_dashboard_user(user_id):
    conn = db()
    try:
        conn.execute("DELETE FROM dashboard_users WHERE id=?", (int(user_id),))
        conn.commit()
    finally:
        conn.close()


def reset_dashboard_user_password(user_id, password, role=None):
    password_hash = generate_password_hash(password)
    conn = db()
    try:
        if role is None:
            conn.execute("UPDATE dashboard_users SET password_hash=?, updated_at=? WHERE id=?", (password_hash, now_ts(), int(user_id)))
        else:
            conn.execute("UPDATE dashboard_users SET password_hash=?, role=?, updated_at=? WHERE id=?", (password_hash, clean_role(role), now_ts(), int(user_id)))
        conn.commit()
    finally:
        conn.close()


def clean_log_type(log_type):
    log_type = (log_type or "account").strip().lower()
    return log_type if log_type in ("account", "node") else "account"


def clean_log_limit(value):
    # Keep each page light. Larger history should be browsed with pagination, not one giant table.
    return max(20, min(500, safe_int(value, 100)))


def clean_page(value):
    return max(1, safe_int(value, 1))


def account_log_where(q=""):
    params = []
    where = ""
    if q:
        p = like_pattern(q)
        where = "WHERE username LIKE ? OR event LIKE ? OR realm LIKE ? OR source_ip LIKE ? OR path LIKE ? OR detail LIKE ?"
        params.extend([p, p, p, p, p, p])
    return where, params


def node_log_where(q=""):
    params = []
    where = ""
    if q:
        p = like_pattern(q)
        where = "WHERE node LIKE ? OR event LIKE ? OR source_ip LIKE ? OR detail LIKE ?"
        params.extend([p, p, p, p])
    return where, params


def account_log_rows(q="", limit=100, page_no=1):
    limit = clean_log_limit(limit)
    page_no = clean_page(page_no)
    offset = (page_no - 1) * limit
    where, params = account_log_where(q)
    conn = db()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM account_logs {where}", params).fetchone()[0]
        rows = conn.execute(f"""
            SELECT id, time, realm, event, username, role, source_ip, path, detail
            FROM account_logs
            {where}
            ORDER BY time DESC, id DESC
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()
        return rows, int(total or 0), limit, page_no
    finally:
        conn.close()


def node_log_rows(q="", limit=100, page_no=1):
    limit = clean_log_limit(limit)
    page_no = clean_page(page_no)
    offset = (page_no - 1) * limit
    where, params = node_log_where(q)
    conn = db()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM node_logs {where}", params).fetchone()[0]
        rows = conn.execute(f"""
            SELECT id, time, event, node, source_ip, status_code, vm_count, iface_count, detail
            FROM node_logs
            {where}
            ORDER BY time DESC, id DESC
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()
        return rows, int(total or 0), limit, page_no
    finally:
        conn.close()


def delete_logs(log_type, mode="selected", ids=None, q=""):
    log_type = clean_log_type(log_type)
    mode = (mode or "selected").strip().lower()
    ids = ids or []
    table = "node_logs" if log_type == "node" else "account_logs"

    conn = db()
    try:
        if mode == "matching":
            if log_type == "node":
                where, params = node_log_where(q)
            else:
                where, params = account_log_where(q)
            cur = conn.execute(f"DELETE FROM {table} {where}", params)
            changed = cur.rowcount if cur.rowcount is not None else 0
        else:
            safe_ids = []
            for value in ids:
                try:
                    safe_ids.append(int(value))
                except (TypeError, ValueError):
                    pass
            if not safe_ids:
                conn.commit()
                return 0
            placeholders = ",".join("?" for _ in safe_ids)
            cur = conn.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", safe_ids)
            changed = cur.rowcount if cur.rowcount is not None else len(safe_ids)
        conn.commit()
        return int(changed or 0)
    finally:
        conn.close()


def pagination_links(endpoint, page_no, total, limit, **params):
    page_no = clean_page(page_no)
    limit = clean_log_limit(limit)
    total_pages = max(1, int(math.ceil((total or 0) / limit)))
    page_no = min(page_no, total_pages)

    def link(label, target, active=False, disabled=False):
        if disabled:
            return f'<span class="page-link disabled">{escape(str(label))}</span>'
        href = url_for(endpoint, page=target, limit=limit, **params)
        cls = "page-link active" if active else "page-link"
        return f'<a class="{cls}" href="{escape(href, quote=True)}">{escape(str(label))}</a>'

    items = []
    items.append(link("Prev", max(1, page_no - 1), disabled=(page_no <= 1)))

    page_set = {1, total_pages, page_no, page_no - 1, page_no + 1}
    page_set = {pnum for pnum in page_set if 1 <= pnum <= total_pages}
    last = 0
    for pnum in sorted(page_set):
        if last and pnum - last > 1:
            items.append('<span class="page-gap">...</span>')
        items.append(link(pnum, pnum, active=(pnum == page_no)))
        last = pnum

    items.append(link("Next", min(total_pages, page_no + 1), disabled=(page_no >= total_pages)))
    start_row = 0 if total == 0 else ((page_no - 1) * limit + 1)
    end_row = min(total, page_no * limit)
    return f"""
    <div class="pagination">
        <div class="page-summary">Showing <b>{start_row}</b>-<b>{end_row}</b> of <b>{int(total or 0)}</b></div>
        <div class="page-links">{''.join(items)}</div>
    </div>
    """


def safe_next_url(value):
    value = (value or "").strip()
    if value.startswith("/") and not value.startswith("//"):
        return value
    return url_for("admin_page")


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def require_admin():
    bootstrap_dashboard_admin_from_settings()
    if not admin_is_configured() or emergency_admin_needed():
        if request.method == "POST":
            return Response("No enabled admin exists. Open /admin/setup to create a new admin.\n", status=403, mimetype="text/plain")
        return redirect(url_for("admin_setup"))
    if not admin_allowed():
        if request.method == "POST":
            return Response("Forbidden\n", status=403, mimetype="text/plain")
        next_url = request.full_path if request.query_string else request.path
        return redirect(url_for("admin_login", next=next_url))
    if request.method == "POST" and request.form.get("csrf_token") != session.get("csrf_token"):
        return Response("CSRF check failed\n", status=403, mimetype="text/plain")
    return None


def admin_form(action, label, fields, danger=True, confirm="Are you sure?"):
    hidden = f'<input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}">'
    for k, v in fields.items():
        hidden += f'<input type="hidden" name="{escape(k, quote=True)}" value="{escape(str(v), quote=True)}">'
    cls = "btn-danger" if danger else "btn"
    return f"""
    <form method="post" action="{escape(action, quote=True)}" style="display:inline" onsubmit="return confirm('{escape(confirm, quote=True)}')">
        {hidden}
        <button class="{cls}" type="submit">{escape(label)}</button>
    </form>
    """


def now_ts():
    return int(time.time())


