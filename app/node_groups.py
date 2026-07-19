"""50.5.9-r7 production-minimal RBAC, visibility and UI hotfix.

This module is installed after the existing append-only app.py runtime has
finished registering its final implementations. It keeps the original call
chain intact and only replaces the final symbols/view functions required for
Node Groups and the admin role split.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

_M = None
_BASE: dict[str, Any] = {}
_CONSUMPTION_STYLE = ""

SYSTEM_GROUP_NAME = "Ungrouped"
_FLAG_DIR = Path(__file__).resolve().parent / "static/flags"
ROLE_MIGRATION_KEY = "node_groups_role_migration_v1"
GROUP_FILTER_ENDPOINTS = {
    "index", "top_page", "node_health_page", "storage_io_page",
    "bandwidth_consumption_page", "vm_abuse_page",
}
ADMIN_ALLOWED_ENDPOINTS = {
    "admin_page", "admin_users_page", "admin_create_user", "admin_user_action",
    "admin_theme_manager", "admin_logs_page", "admin_system_health_page",
    "admin_api_system_health",
    "admin_delete_vm", "admin_restore_vm", "admin_delete_node", "admin_restore_node",
    "admin_purge_node_vms", "admin_bulk_nodes", "admin_bulk_vms",
    "admin_change_password", "admin_logout",
    "admin_node_groups_create", "admin_node_groups_update",
    "admin_node_groups_action", "admin_node_groups_assign", "admin_node_groups_bulk",
}


def _m():
    if _M is None:
        raise RuntimeError("Node Groups hotfix is not installed")
    return _M


def _ts() -> int:
    return int(_m().now_ts())


def _clean_country_code(value: Any) -> str:
    code = str(value or "").strip().lower()
    return code if re.fullmatch(r"[a-z]{2}", code) and (_FLAG_DIR / f"{code}.svg").is_file() else ""


def _clean_group_id(value: Any) -> int:
    raw = str(value or "").strip().lower()
    if not raw or raw == "all":
        return 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def selected_group_id() -> int:
    try:
        gid = _clean_group_id(_m().request.args.get("group"))
    except RuntimeError:
        return 0
    if gid <= 0:
        return 0
    row = group_row(gid, include_hidden=True)
    if not row:
        return 0
    if not bool(row[4]):
        return 0
    return gid



def current_role() -> str:
    m = _m()
    username = m.session.get("admin_username") or m.session.get("dashboard_username") or ""
    if username:
        user = m.get_dashboard_user(username)
        if user:
            return clean_role(user[3])
    return clean_role(m.session.get("dashboard_role") or "")


def is_super_admin() -> bool:
    return current_role() == "super_admin"


def clean_role(value: Any) -> str:
    role = str(value or "viewer").strip().lower()
    return role if role in {"viewer", "admin", "super_admin"} else "viewer"


def ensure_schema(conn=None) -> None:
    m = _m()
    own = conn is None
    conn = conn or m.db()
    now = _ts()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS node_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                country_code TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                is_system INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                hidden_at INTEGER
            )
        """)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_node_groups_name_ci ON node_groups(LOWER(name))")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_node_groups_single_system ON node_groups(is_system) WHERE is_system=1")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_node_groups_hidden ON node_groups(is_active,hidden_at,id)")
        conn.execute("""
            INSERT INTO node_groups(name,description,country_code,is_active,is_system,created_at,updated_at,hidden_at)
            SELECT ?,?, '',1,1,?,?,NULL
            WHERE NOT EXISTS (SELECT 1 FROM node_groups WHERE is_system=1)
        """, (SYSTEM_GROUP_NAME, "Default group for nodes without an explicit assignment", now, now))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS node_group_memberships (
                node TEXT PRIMARY KEY REFERENCES node_inventory(node) ON DELETE CASCADE,
                group_id INTEGER NOT NULL REFERENCES node_groups(id) ON DELETE RESTRICT,
                assigned_at INTEGER NOT NULL,
                assigned_by TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_node_group_memberships_node ON node_group_memberships(node)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_node_group_memberships_group_id ON node_group_memberships(group_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_node_group_memberships_group_node ON node_group_memberships(group_id,node)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS node_group_membership_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT '',
                node TEXT,
                old_group_id INTEGER,
                old_group_name TEXT NOT NULL DEFAULT '',
                new_group_id INTEGER,
                new_group_name TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_node_group_history_time ON node_group_membership_history(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_node_group_history_node_time ON node_group_membership_history(node,created_at)")
        system_id = system_group_id(conn)
        conn.execute("""
            INSERT INTO node_group_memberships(node,group_id,assigned_at,assigned_by)
            SELECT ni.node, ?, ?, 'migration'
              FROM node_inventory ni
             WHERE NOT EXISTS (
                   SELECT 1 FROM node_group_memberships gm WHERE gm.node=ni.node
             )
        """, (system_id, now))
        # SQLite receives the same automatic membership guarantee as the
        # PostgreSQL trigger installed by migration 012.
        if getattr(getattr(conn, "__class__", None), "__module__", "").startswith("sqlite3"):
            conn.execute("DROP TRIGGER IF EXISTS trg_node_inventory_assign_ungrouped")
            conn.execute("""
                CREATE TRIGGER trg_node_inventory_assign_ungrouped
                AFTER INSERT ON node_inventory
                BEGIN
                    INSERT OR IGNORE INTO node_group_memberships(node,group_id,assigned_at,assigned_by)
                    SELECT NEW.node,id,CAST(strftime('%s','now') AS INTEGER),'trigger'
                      FROM node_groups WHERE is_system=1 ORDER BY id LIMIT 1;
                END
            """)
        marker = conn.execute("SELECT value FROM admin_settings WHERE key=?", (ROLE_MIGRATION_KEY,)).fetchone()
        if not marker:
            conn.execute("UPDATE dashboard_users SET role='super_admin',updated_at=? WHERE role='admin'", (now,))
            conn.execute("""
                INSERT INTO admin_settings(key,value,updated_at)
                VALUES (?,?,?) ON CONFLICT(key) DO NOTHING
            """, (ROLE_MIGRATION_KEY, "completed", now))
        if own:
            conn.commit()
    except Exception:
        if own:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if own:
            conn.close()



def system_group_id(conn=None) -> int:
    m = _m()
    own = conn is None
    conn = conn or m.db()
    try:
        row = conn.execute("SELECT id FROM node_groups WHERE is_system=1 ORDER BY id LIMIT 1").fetchone()
        if not row:
            now = _ts()
            result = conn.execute("""
                INSERT INTO node_groups(name,description,country_code,is_active,is_system,created_at,updated_at)
                VALUES (?,?, '',1,1,?,?)
            """, (SYSTEM_GROUP_NAME, "Default group for nodes without an explicit assignment", now, now))
            if own:
                conn.commit()
            return int(result.lastrowid)
        return int(row[0])
    finally:
        if own:
            conn.close()



def group_row(group_id: int, include_hidden: bool = True):
    if group_id <= 0:
        return None
    conn = _m().db()
    try:
        where = "id=?" if include_hidden else "id=? AND is_active=1"
        return conn.execute(f"""
            SELECT id,name,description,country_code,is_active,is_system,created_at,updated_at,hidden_at
              FROM node_groups WHERE {where}
        """, (group_id,)).fetchone()
    finally:
        conn.close()


def group_nodes(group_id: int) -> set[str]:
    if group_id <= 0:
        return set()
    conn = _m().db()
    try:
        return {str(row[0]) for row in conn.execute(
            "SELECT node FROM node_group_memberships WHERE group_id=?", (group_id,)
        ).fetchall()}
    finally:
        conn.close()


def get_visible_node_names(group_id: int = 0) -> set[str]:
    """Return the canonical monitoring visibility set.

    Admin inventory deliberately does not use this helper: hidden groups and
    hidden nodes must remain manageable there. Monitoring pages all consume
    this same set so a hidden group never becomes an ingest/deletion state.
    """
    group_id = int(group_id or 0)
    conn = _m().db()
    try:
        params: list[Any] = []
        group_sql = ""
        if group_id > 0:
            group_sql = " AND g.id=?"
            params.append(group_id)
        return {
            str(row[0])
            for row in conn.execute(
                """SELECT ni.node
                     FROM node_inventory ni
                     JOIN node_group_memberships gm ON gm.node=ni.node
                     JOIN node_groups g ON g.id=gm.group_id
                    WHERE g.is_active=1
                      AND COALESCE(ni.status,'active')!='hidden'
                      AND ni.deleted_at IS NULL""" + group_sql,
                params,
            ).fetchall()
        }
    finally:
        conn.close()


def monitoring_node_visible(node: str) -> bool:
    return str(node or "").strip() in get_visible_node_names()


def monitoring_vm_visible(node: str, vm_uuid: str) -> bool:
    node = str(node or "").strip()
    vm_uuid = str(vm_uuid or "").strip()
    if not node or not vm_uuid or not monitoring_node_visible(node):
        return False
    conn = _m().db()
    try:
        row = conn.execute(
            """SELECT 1 FROM vm_inventory
                WHERE node=? AND vm_uuid=?
                  AND COALESCE(status,'active')!='hidden'
                  AND deleted_at IS NULL""",
            (node, vm_uuid),
        ).fetchone()
        return bool(row)
    finally:
        conn.close()


def active_groups(include_hidden_selected: int = 0):
    include_hidden_selected = int(include_hidden_selected or 0)
    if current_role() == "viewer":
        include_hidden_selected = 0
    conn = _m().db()
    try:
        return conn.execute("""
            SELECT id,name,description,country_code,is_active,is_system,created_at,updated_at,hidden_at
              FROM node_groups
             WHERE is_active=1 OR id=?
             ORDER BY is_system DESC,LOWER(name)
        """, (include_hidden_selected,)).fetchall()
    finally:
        conn.close()


def all_group_rows(q: str = "", visibility: str = "all", sort: str = "name", order: str = "asc"):
    q = str(q or "").strip().lower()
    visibility = str(visibility or "all").strip().lower()
    sort = str(sort or "name").strip().lower()
    order = "desc" if str(order or "asc").strip().lower() == "desc" else "asc"
    if visibility not in {"all", "active", "hidden"}:
        visibility = "all"
    sort_sql = {
        "id": "g.id",
        "name": "LOWER(g.name)",
        "description": "LOWER(g.description)",
        "country": "LOWER(g.country_code)",
        "status": "g.is_active",
        "nodes": "node_count",
        "vms": "vm_count",
    }.get(sort, "LOWER(g.name)")
    where = []
    params = []
    if visibility == "active":
        where.append("g.is_active=1")
    elif visibility == "hidden":
        where.append("g.is_active=0")
    if q:
        needle = "%" + q.replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("""(
            LOWER(g.name) LIKE ? OR LOWER(g.description) LIKE ? OR
            LOWER(g.country_code) LIKE ? OR EXISTS (
                SELECT 1 FROM node_group_memberships gm_search
                 WHERE gm_search.group_id=g.id AND LOWER(gm_search.node) LIKE ?
            ) OR EXISTS (
                SELECT 1
                  FROM node_group_memberships gm_ip
                  JOIN node_bridge_addresses_latest ba_ip ON ba_ip.node=gm_ip.node
                 WHERE gm_ip.group_id=g.id
                   AND (
                       LOWER(COALESCE(ba_ip.primary_ipv4,'')) LIKE ? OR
                       LOWER(COALESCE(ba_ip.ipv4_json,'[]')) LIKE ?
                   )
            )
        )""")
        params.extend((needle, needle, needle, needle, needle, needle))
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    direction = "DESC" if order == "desc" else "ASC"
    conn = _m().db()
    try:
        return conn.execute("""
            SELECT g.id,g.name,g.description,g.country_code,g.is_active,g.is_system,
                   COUNT(DISTINCT gm.node) node_count,
                   COUNT(DISTINCT CASE WHEN COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL THEN vi.node||':'||vi.vm_uuid END) vm_count,
                   g.created_at,g.updated_at,g.hidden_at
              FROM node_groups g
              LEFT JOIN node_group_memberships gm ON gm.group_id=g.id
              LEFT JOIN vm_inventory vi ON vi.node=gm.node
        """ + where_sql + """
             GROUP BY g.id,g.name,g.description,g.country_code,g.is_active,g.is_system,g.created_at,g.updated_at,g.hidden_at
             ORDER BY """ + sort_sql + " " + direction + ", LOWER(g.name) ASC, g.id ASC", tuple(params)).fetchall()
    finally:
        conn.close()


def group_options_html(selected: int = 0, all_label: str = "All Node Groups", include_hidden: bool = False) -> str:
    m = _m()
    rows = (
        [(row[0],row[1],row[2],row[3],row[4],row[5],row[8],row[9],row[10]) for row in all_group_rows()]
        if include_hidden and current_role() in {"admin", "super_admin"}
        else active_groups(selected)
    )
    parts = [f'<option value="">{m.escape(all_label)}</option>']
    for row in rows:
        gid, name, _desc, country, active, _system, *_ = row
        label = str(name)
        if country:
            label = f"{country.upper()} · {label}"
        if not active:
            label += " (Hidden)"
        parts.append('<option value="%s"%s>%s</option>' % (
            int(gid), " selected" if int(gid) == int(selected or 0) else "", m.escape(label),
        ))
    return "".join(parts)


def flag_html(country_code: Any) -> str:
    m = _m()
    code = _clean_country_code(country_code)
    filename = f"{code}.svg" if code else "neutral.svg"
    label = code.upper() if code else "Neutral group"
    return '<img class="node-group-flag" src="%s" width="20" height="15" alt="" aria-hidden="true" title="%s" loading="lazy">' % (
        m.escape(m.url_for("static", filename=f"flags/{filename}"), quote=True),
        m.escape(label, quote=True),
    )



def group_badge(name: Any, country_code: Any = "") -> str:
    m = _m()
    return '<span class="node-group-badge">%s<span>%s</span></span>' % (
        flag_html(country_code), m.escape(str(name or SYSTEM_GROUP_NAME)),
    )


def group_for_node(node: str, conn=None):
    m = _m()
    own = conn is None
    conn = conn or m.db()
    try:
        row = conn.execute("""
            SELECT g.id,g.name,g.country_code,g.is_active,g.is_system
              FROM node_group_memberships gm
              JOIN node_groups g ON g.id=gm.group_id
             WHERE gm.node=?
        """, (node,)).fetchone()
        if row:
            return row
        gid = system_group_id(conn)
        conn.execute("""
            INSERT INTO node_group_memberships(node,group_id,assigned_at,assigned_by)
            SELECT ?,?,?, 'auto' WHERE EXISTS (SELECT 1 FROM node_inventory WHERE node=?)
            ON CONFLICT(node) DO NOTHING
        """, (node, gid, _ts(), node))
        if own:
            conn.commit()
        return conn.execute("SELECT id,name,country_code,is_active,is_system FROM node_groups WHERE id=?", (gid,)).fetchone()
    finally:
        if own:
            conn.close()



def ensure_node_membership(node: str, actor: str = "auto") -> int:
    node = str(node or "").strip()
    if not node:
        return 0
    conn = _m().db()
    try:
        gid = system_group_id(conn)
        inserted = conn.execute("""
            INSERT INTO node_group_memberships(node,group_id,assigned_at,assigned_by)
            SELECT ?,?,?,? WHERE EXISTS (SELECT 1 FROM node_inventory WHERE node=?)
            ON CONFLICT(node) DO NOTHING
            RETURNING node
        """, (node, gid, _ts(), actor[:128], node)).fetchone()
        if inserted:
            target = conn.execute(
                "SELECT id,name,country_code,is_system FROM node_groups WHERE id=?",
                (gid,),
            ).fetchone()
            _audit_membership(conn, "node_group_assigned", actor[:128], node, None, target)
        conn.commit()
        return gid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _actor() -> str:
    m = _m()
    return str(m.session.get("admin_username") or m.dashboard_username() or "system")[:128]


def _audit_membership(conn, event: str, actor: str, node: str, old_row, new_row) -> None:
    old_id = int(old_row[0]) if old_row else None
    old_name = str(old_row[1]) if old_row else ""
    new_id = int(new_row[0]) if new_row else None
    new_name = str(new_row[1]) if new_row else ""
    conn.execute("""
        INSERT INTO node_group_membership_history(
            event,actor,node,old_group_id,old_group_name,new_group_id,new_group_name,created_at
        ) VALUES (?,?,?,?,?,?,?,?)
    """, (event, actor, node, old_id, old_name, new_id, new_name, _ts()))


def _audit_group_event(conn, event: str, actor: str, old_row=None, new_row=None) -> None:
    _audit_membership(conn, event, actor, "", old_row, new_row)


def assign_nodes(nodes: list[str], group_id: int, actor: str) -> dict[str, int]:
    m = _m()
    group_id = int(group_id)
    clean_nodes = list(dict.fromkeys(str(raw or "").strip() for raw in nodes if str(raw or "").strip()))
    conn = m.db()
    changed = assigned = moved = removed = 0
    target = None
    try:
        target = conn.execute(
            "SELECT id,name,country_code,is_system FROM node_groups WHERE id=?",
            (group_id,),
        ).fetchone()
        if not target:
            raise ValueError("Node Group not found")
        if not bool(conn.execute("SELECT is_active FROM node_groups WHERE id=?", (group_id,)).fetchone()[0]):
            raise ValueError("Node Group is hidden")
        system_id = system_group_id(conn)
        conn.execute("BEGIN IMMEDIATE")
        for node in clean_nodes:
            if not conn.execute("SELECT 1 FROM node_inventory WHERE node=?", (node,)).fetchone():
                continue
            old = conn.execute("""
                SELECT g.id,g.name,g.country_code,g.is_system
                  FROM node_group_memberships gm JOIN node_groups g ON g.id=gm.group_id
                 WHERE gm.node=?
            """, (node,)).fetchone()
            if old and int(old[0]) == group_id:
                continue
            conn.execute("""
                INSERT INTO node_group_memberships(node,group_id,assigned_at,assigned_by)
                VALUES (?,?,?,?)
                ON CONFLICT(node) DO UPDATE SET
                    group_id=excluded.group_id,
                    assigned_at=excluded.assigned_at,
                    assigned_by=excluded.assigned_by
            """, (node, group_id, _ts(), actor[:128]))
            if int(group_id) == int(system_id):
                event = "node_group_removed"; removed += 1
            elif not old or int(old[0]) == int(system_id):
                event = "node_group_assigned"; assigned += 1
            else:
                event = "node_group_moved"; moved += 1
            _audit_membership(conn, event, actor[:128], node, old, target)
            changed += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if changed and target:
        event = "node_group_assigned" if changed == assigned else ("node_group_removed" if changed == removed else "node_group_moved")
        m.log_account_event(
            event, username=actor[:128], realm="admin", role=current_role(),
            detail=(f"nodes={','.join(clean_nodes[:100])};new_group={target[1]};"
                    f"assigned={assigned};moved={moved};removed={removed}")[:700],
        )
    return {"changed": changed, "assigned": assigned, "moved": moved, "removed": removed}



def role_migration_completed() -> bool:
    conn = _m().db()
    try:
        row = conn.execute("SELECT value FROM admin_settings WHERE key=?", (ROLE_MIGRATION_KEY,)).fetchone()
        return bool(row and row[0] == "completed")
    finally:
        conn.close()


def admin_allowed() -> bool:
    m = _m()
    if not m.session.get("admin_authenticated"):
        return False
    username = m.session.get("admin_username") or m.session.get("dashboard_username") or ""
    if not username:
        return False
    user = m.get_dashboard_user(username)
    if not user:
        return False
    role = clean_role(user[3])
    return bool(user[4]) and role in {"admin", "super_admin"}


def active_super_admin_count(exclude_user_id=None) -> int:
    conn = _m().db()
    try:
        if exclude_user_id is None:
            row = conn.execute("SELECT COUNT(*) FROM dashboard_users WHERE role='super_admin' AND is_active=1").fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM dashboard_users WHERE role='super_admin' AND is_active=1 AND id!=?", (int(exclude_user_id),)).fetchone()
        return int(row[0] or 0)
    finally:
        conn.close()


def emergency_admin_needed() -> bool:
    return active_super_admin_count() == 0


def is_last_enabled_admin(user_id) -> bool:
    m = _m()
    row = m.get_dashboard_user_by_id(user_id)
    if not row:
        return False
    return clean_role(row[3]) == "super_admin" and bool(row[4]) and active_super_admin_count(user_id) == 0


def require_admin():
    m = _m()
    bootstrap_dashboard_admin_from_settings()
    if not m.admin_is_configured() or emergency_admin_needed():
        if m.request.method == "POST" or m.dashboard_allowed():
            return m.Response("Forbidden\n", status=403, mimetype="text/plain")
        return m.redirect(m.url_for("admin_setup"))
    if not admin_allowed():
        if m.dashboard_allowed() or m.request.method == "POST":
            return m.Response("Forbidden\n", status=403, mimetype="text/plain")
        next_url = m.request.full_path if m.request.query_string else m.request.path
        return m.redirect(m.url_for("admin_login", next=next_url))
    if current_role() == "admin" and m.request.endpoint not in ADMIN_ALLOWED_ENDPOINTS:
        return m.Response("Forbidden\n", status=403, mimetype="text/plain")
    if m.request.method == "POST" and m.request.form.get("csrf_token") != m.session.get("csrf_token"):
        return m.Response("CSRF check failed\n", status=403, mimetype="text/plain")
    return None



def set_admin_credentials(username, password):
    m = _m()
    username = (username or "admin").strip() or "admin"
    m.set_admin_setting("admin_username", username)
    m.set_admin_setting("admin_password_hash", m.generate_password_hash(password))
    m.upsert_dashboard_user(username, password, role="super_admin", is_active=1)


def bootstrap_dashboard_admin_from_settings():
    m = _m()
    if m.dashboard_user_count() > 0:
        return
    username = m.get_admin_username()
    password_hash = m.get_admin_password_hash()
    if not password_hash:
        return
    now = _ts()
    conn = m.db()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO dashboard_users(username,password_hash,role,is_active,created_at,updated_at)
            VALUES (?,?,'super_admin',1,?,?)
        """, (username, password_hash, now, now))
        conn.commit()
    finally:
        conn.close()


def _response_html(response):
    m = _m()
    if isinstance(response, m.Response):
        return response.get_data(as_text=True), response
    return str(response), None


def _replace_response_html(response, html: str):
    m = _m()
    if isinstance(response, m.Response):
        response.set_data(html)
        return response
    return html


def _insert_once(html: str, marker: str, addition: str, before: bool = True) -> str:
    if marker not in html:
        return html
    return html.replace(marker, addition + marker if before else marker + addition, 1)


def _group_select(selected: int = 0, name: str = "group", all_label: str = "All Node Groups", aria: str = "Node Group filter", include_hidden: bool = False) -> str:
    return '<select name="%s" aria-label="%s">%s</select>' % (
        name, _m().escape(aria, quote=True), group_options_html(selected, all_label, include_hidden=include_hidden),
    )


def _flag_css_link() -> str:
    return '<link rel="stylesheet" href="%s">' % _m().url_for("static", filename="flags/node-groups.css")



def page(title, content, *args, **kwargs):
    html = _BASE["page"](title, content, *args, **kwargs)
    text, response = _response_html(html)
    # Keep the baseline layout. Only reorder existing monitoring links and add
    # the one Node Groups monitoring entry requested by r6.
    nav_match = re.search(r'<nav class="main-nav">.*?</nav>', text, flags=re.S)
    if nav_match:
        m = _m()
        items = [
            ("index", "Dashboard"),
            ("node_groups_page", "Node Groups"),
            ("top_page", "Top VM"),
            ("node_health_page", "Node Health"),
            ("storage_io_page", "Storage I/O"),
            ("bandwidth_consumption_page", "Consumption"),
            ("vm_abuse_page", "VM Abuse"),
        ]
        nav = '<nav class="main-nav">' + ''.join(
            '<a href="%s">%s</a>' % (m.escape(m.url_for(endpoint), quote=True), m.escape(label))
            for endpoint, label in items
        ) + '</nav>'
        text = text[:nav_match.start()] + nav + text[nav_match.end():]
    if ("node-group-flag" in text or "node-group-monitor" in text) and "flags/node-groups.css" not in text:
        text = text.replace("</head>", _flag_css_link() + "</head>", 1)
    return _replace_response_html(response or html, text)



def url_for(endpoint, **values):
    m = _m()
    if endpoint in GROUP_FILTER_ENDPOINTS and "group" not in values:
        try:
            gid = selected_group_id()
        except Exception:
            gid = 0
        if gid:
            values["group"] = gid
    return _BASE["url_for"](endpoint, **values)


def admin_nav(active: str) -> str:
    m = _m()
    if current_role() == "admin":
        items = [
            ("overview", "Overview", m.url_for("admin_page", section="overview")),
            ("users", "Users", m.url_for("admin_users_page")),
            ("theme", "Theme", m.url_for("admin_theme_manager")),
            ("account-logs", "Account Logs", m.url_for("admin_logs_page", type="account")),
            ("node-logs", "Node Logs", m.url_for("admin_logs_page", type="node")),
            ("health", "System Health", m.url_for("admin_system_health_page")),
            ("groups", "Node Groups", m.url_for("admin_page", section="groups")),
            ("nodes", "Nodes", m.url_for("admin_page", section="nodes")),
            ("vms", "VMs", m.url_for("admin_page", section="vms")),
        ]
        return '<nav class="admin-tabs">' + "".join(
            '<a class="%s" href="%s">%s</a>' % (
                "active" if active == key else "", m.escape(href, quote=True), m.escape(label),
            ) for key, label, href in items
        ) + "</nav>"
    html = _BASE["admin_nav"](active)
    link = '<a class="%s" href="%s">Node Groups</a>' % (
        "active" if active == "groups" else "",
        m.escape(m.url_for("admin_page", section="groups"), quote=True),
    )
    match = re.search(r'<a[^>]*href="[^"]*section=nodes[^"]*"[^>]*>Nodes</a>', html)
    if match:
        return html[:match.start()] + link + html[match.start():]
    return html.replace("</nav>", link + "</nav>", 1)


def admin_overview(stats) -> str:
    """Render an Admin overview without privileged queue/database affordances."""
    if is_super_admin():
        return _BASE["admin_overview"](stats)
    m = _m()
    conn = m.db()
    try:
        group_count = int(conn.execute("SELECT COUNT(*) FROM node_groups").fetchone()[0] or 0)
        hidden_group_count = int(conn.execute("SELECT COUNT(*) FROM node_groups WHERE is_active=0").fetchone()[0] or 0)
    finally:
        conn.close()
    cards = [
        ("Nodes", f"{stats['nodes']:,}", f"{stats['hidden_nodes']:,} hidden", m.url_for("admin_page", section="nodes")),
        ("VMs", f"{stats['vms']:,}", f"{stats['hidden_vms']:,} hidden", m.url_for("admin_page", section="vms")),
        ("Node Groups", f"{group_count:,}", f"{hidden_group_count:,} hidden", m.url_for("admin_page", section="groups")),
    ]
    card_html = "".join(
        '<a class="admin-kpi" href="%s"><span>%s</span><b>%s</b><small>%s</small></a>' % (
            m.escape(href, quote=True), m.escape(label), m.escape(value), m.escape(note),
        )
        for label, value, note, href in cards
    )
    quick = [
        ("User management", "Create and manage Viewer or Admin accounts", m.url_for("admin_users_page")),
        ("Theme settings", "Keep the current dashboard appearance consistent", m.url_for("admin_theme_manager")),
        ("Account logs", "Authentication and account activity", m.url_for("admin_logs_page", type="account")),
        ("Node logs", "Agent and node-side events", m.url_for("admin_logs_page", type="node")),
        ("System health", "Service and data freshness", m.url_for("admin_system_health_page")),
        ("Change password", "Update only the signed-in account", m.url_for("admin_change_password")),
    ]
    quick_html = "".join(
        '<a class="quick-link-card" href="%s"><b>%s</b><span>%s</span><i>â†’</i></a>' % (
            m.escape(href, quote=True), m.escape(label), m.escape(note),
        )
        for label, note, href in quick
    )
    return (
        f'<div class="admin-kpis">{card_html}</div>'
        '<div class="card"><div class="section-head"><div><h3>Admin tools</h3>'
        '<p>Only capabilities assigned to the Admin role are shown.</p></div></div>'
        f'<div class="quick-link-grid">{quick_html}</div></div>'
    )


def _group_management_section() -> str:
    m = _m()
    q = str(m.request.args.get("group_q") or "").strip()
    visibility = str(m.request.args.get("group_visibility") or "all").strip().lower()
    sort = str(m.request.args.get("group_sort") or "name").strip().lower()
    order = str(m.request.args.get("group_order") or "asc").strip().lower()
    allowed_sort = {"id", "name", "description", "country", "status", "nodes", "vms"}
    if sort not in allowed_sort:
        sort = "name"
    if order not in {"asc", "desc"}:
        order = "asc"
    rows = all_group_rows(q, visibility, sort, order)

    def sort_link(label: str, key: str) -> str:
        next_order = "desc" if sort == key and order == "asc" else "asc"
        href = m.url_for(
            "admin_page", section="groups", group_q=q,
            group_visibility=visibility, group_sort=key, group_order=next_order,
        )
        return '<a class="sort-link" href="%s">%s%s</a>' % (
            m.escape(href, quote=True), m.escape(label),
            " ↑" if sort == key and order == "asc" else " ↓" if sort == key else "",
        )

    body = ""
    for group_id, name, description, country, active, system, node_count, vm_count, created_at, updated_at, hidden_at in rows:
        state = "Active" if active else "Hidden"
        state_cls = "active" if active else "stale"
        flag = flag_html(country)
        if system:
            actions = '<span class="vm-state active">SYSTEM</span>'
            edit = ""
        else:
            toggle_action = "hide" if active else "restore"
            toggle_label = "Hide" if active else "Restore"
            toggle = m.admin_form(
                m.url_for("admin_node_groups_action"), toggle_label,
                {"group_id": group_id, "action": toggle_action},
                danger=bool(active), confirm=f"{toggle_label} this Node Group?",
            )
            delete = m.admin_form(
                m.url_for("admin_node_groups_action"), "Delete",
                {"group_id": group_id, "action": "delete"},
                danger=True, confirm="Delete this empty Node Group?",
            )
            move_all = (
                f'<form method="post" action="{m.url_for("admin_node_groups_bulk")}" '
                f'onsubmit="return confirm(\'Move all {int(node_count or 0)} node(s) in this group to Ungrouped?\')">'
                f'<input type="hidden" name="csrf_token" value="{m.escape(m.csrf_token(), quote=True)}">'
                '<input type="hidden" name="action" value="move_all_ungrouped">'
                f'<input type="hidden" name="source_group_id" value="{int(group_id)}">'
                f'<button type="submit">Move all {int(node_count or 0)} to Ungrouped</button></form>'
            )
            actions = m._v490_action_menu(move_all + toggle + delete)
            edit = (
                f'<details class="action-menu"><summary>Edit</summary><form method="post" action="{m.url_for("admin_node_groups_update")}">'
                f'<input type="hidden" name="csrf_token" value="{m.escape(m.csrf_token(), quote=True)}">'
                f'<input type="hidden" name="group_id" value="{int(group_id)}">'
                f'<input name="name" value="{m.escape(name, quote=True)}" maxlength="80" required>'
                f'<input name="description" value="{m.escape(description or "", quote=True)}" maxlength="500" placeholder="Description">'
                f'<input name="country_code" value="{m.escape(country or "", quote=True)}" maxlength="2" placeholder="Country code">'
                '<button type="submit">Save</button></form></details>'
            )
        body += (
            f'<tr class="{"stale-row" if not active else ""}"><td>{int(group_id)}</td>'
            f'<td><b>{flag}{m.escape(name)}</b>{"<small class=\"row-sub\">Immutable default group</small>" if system else ""}</td>'
            f'<td>{m.escape(description or "-")}</td><td class="mono">{m.escape((country or "-").upper())}</td>'
            f'<td><span class="vm-state {state_cls}">{state.upper()}</span></td>'
            f'<td class="num"><b>{int(node_count or 0)}</b></td><td class="num"><b>{int(vm_count or 0)}</b></td>'
            f'<td>{edit}{actions}</td></tr>'
        )
    if not body:
        body = '<tr><td colspan="8" class="empty">No Node Groups</td></tr>'
    visibility_options = "".join(
        '<option value="%s"%s>%s</option>' % (
            value, " selected" if visibility == value else "", label,
        )
        for value, label in (("all", "All groups"), ("active", "Active"), ("hidden", "Hidden"))
    )
    filters = (
        f'<form class="search" method="get" action="{m.url_for("admin_page")}">'
        '<input type="hidden" name="section" value="groups">'
        f'<input name="group_q" value="{m.escape(q, quote=True)}" placeholder="Search group or node">'
        f'<select name="group_visibility">{visibility_options}</select>'
        f'<input type="hidden" name="group_sort" value="{m.escape(sort, quote=True)}">'
        f'<input type="hidden" name="group_order" value="{m.escape(order, quote=True)}">'
        '<button type="submit">Apply</button>'
        f'<a class="btn" href="{m.url_for("admin_page", section="groups")}">Reset</a></form>'
    )
    headers = [
        sort_link("ID", "id"), sort_link("GROUP NAME", "name"),
        sort_link("DESCRIPTION", "description"), sort_link("REGION", "country"),
        sort_link("STATUS", "status"), sort_link("NODE", "nodes"),
        sort_link("VM", "vms"), "ACTION",
    ]
    return (
        '<div class="card"><div class="section-head"><div><h3>Node Groups</h3>'
        '<p>Persistent node configuration. Hide, restore, move and delete operations never remove node metrics.</p>'
        f'</div></div>{filters}'
        f'<form class="search" method="post" action="{m.url_for("admin_node_groups_create")}">'
        f'<input type="hidden" name="csrf_token" value="{m.escape(m.csrf_token(), quote=True)}">'
        '<input name="name" maxlength="80" placeholder="Group name" required>'
        '<input name="description" maxlength="500" placeholder="Description">'
        '<input name="country_code" maxlength="2" placeholder="Country code">'
        '<button type="submit">Create</button></form><div class="table-wrap"><table class="admin-clean-table">'
        f'<thead><tr>{"".join("<th>" + header + "</th>" for header in headers)}</tr></thead>'
        f'<tbody>{body}</tbody></table></div></div>'
    )



def _admin_group_filter() -> int:
    return _clean_group_id(_m().request.args.get("group"))


def admin_nodes_query(q, status, page_no, per_page):
    m = _m()
    status = m._v48134_clean_admin_status(status)
    status_sql, params = m._v48134_status_sql("ni", "last_push", status)
    where = [status_sql]
    group_id = _admin_group_filter()
    if group_id:
        where.append("gm.group_id=?")
        params.append(group_id)
    if q:
        p = m.like_pattern(q)
        normalized_mac = m.normalize_mac_address(q)
        where.append("""(
            ni.node LIKE ?
            OR ng.name LIKE ?
            OR EXISTS (SELECT 1 FROM node_bridge_addresses_latest b WHERE b.node=ni.node AND (
                COALESCE(b.primary_ipv4,'') LIKE ? OR COALESCE(b.ipv4_json,'[]') LIKE ? OR COALESCE(b.mac,'') LIKE ?
                OR (?<>'' AND LOWER(COALESCE(b.mac,''))=LOWER(?))))
            OR EXISTS (SELECT 1 FROM vm_inventory v WHERE v.node=ni.node AND (
                v.vm_uuid LIKE ? OR COALESCE(v.last_iface,'') LIKE ? OR COALESCE(v.last_bridge,'') LIKE ?))
            OR EXISTS (SELECT 1 FROM vm_iface_current i WHERE i.node=ni.node AND (
                i.vm_uuid LIKE ? OR COALESCE(i.iface,'') LIKE ? OR COALESCE(i.bridge,'') LIKE ?))
            OR EXISTS (SELECT 1 FROM vm_nic_identity_lookup l JOIN vm_iface_current i
                ON i.node=l.node AND i.vm_uuid=l.vm_uuid AND i.bridge=l.bridge AND i.iface=l.iface AND i.mac=l.mac
                WHERE l.node=ni.node AND (l.mac LIKE ? OR (?<>'' AND l.mac=?)))
            OR EXISTS (SELECT 1 FROM node_physical_net_latest pn WHERE pn.node=ni.node AND (
                COALESCE(pn.iface,'') LIKE ? OR COALESCE(pn.bridge,'') LIKE ?))
            OR EXISTS (SELECT 1 FROM node_nic_identity_lookup l JOIN node_physical_net_latest pn
                ON pn.node=l.node AND pn.role=l.role AND pn.mac=l.mac
                WHERE l.node=ni.node AND (l.mac LIKE ? OR (?<>'' AND l.mac=?)))
        )""")
        params.extend([
            p, p, p, p, p, normalized_mac, normalized_mac,
            p, p, p, p, p, p, p, normalized_mac, normalized_mac,
            p, p, p, normalized_mac, normalized_mac,
        ])
    where_sql = "WHERE " + " AND ".join(where)
    sort = str(m.request.args.get("sort") or "node").strip().lower()
    order = str(m.request.args.get("order") or "asc").strip().lower()
    sort_map = {
        "node": "ni.node COLLATE NOCASE",
        "group": "ng.name COLLATE NOCASE",
        "public_ip": "COALESCE(b.public_ipv4,'') COLLATE NOCASE",
        "agent": "CASE WHEN COALESCE(ni.status,'active')='hidden' OR ni.deleted_at IS NOT NULL THEN 2 WHEN COALESCE(ncf.last_seen,ni.last_push,0)<? THEN 1 ELSE 0 END",
        "last_seen": "COALESCE(ncf.last_seen,ni.last_push,0)",
        "vm_count": "COALESCE(vc.vm_count,0)",
        "cpu": "COALESCE(ncf.cpu_percent,-1)",
        "ram": "CASE WHEN COALESCE(ncf.mem_total,0)>0 THEN ncf.mem_used*1.0/ncf.mem_total ELSE -1 END",
        "disk": "COALESCE(ncf.disk_read_bps,0)+COALESCE(ncf.disk_write_bps,0)",
        "network": "COALESCE(ncf.total_bytes,0)",
    }
    if sort not in sort_map:
        sort = "node"
    if order not in {"asc", "desc"}:
        order = "asc"
    order_expr = sort_map[sort]
    order_params = [m.now_ts() - m.VM_STALE_SECONDS] if sort == "agent" else []
    conn = m.db()
    try:
        system_id = system_group_id(conn)
        conn.execute("""
            INSERT INTO node_group_memberships(node,group_id,assigned_at,assigned_by)
            SELECT ni.node,?,?, 'auto' FROM node_inventory ni
            WHERE NOT EXISTS (SELECT 1 FROM node_group_memberships x WHERE x.node=ni.node)
        """, (system_id, _ts()))
        conn.commit()
        from_sql = """node_inventory ni
            JOIN node_group_memberships gm ON gm.node=ni.node
            JOIN node_groups ng ON ng.id=gm.group_id"""
        total = m.safe_int(conn.execute(f"SELECT COUNT(*) FROM {from_sql} {where_sql}", params).fetchone()[0], 0)
        max_page = max(1, math.ceil(total / per_page))
        page_no = max(1, min(page_no, max_page))
        rows = conn.execute(f"""
          WITH bridge_ip AS (
            SELECT node,MAX(CASE WHEN LOWER(role)='public' THEN primary_ipv4 ELSE '' END) public_ipv4,
                        MAX(CASE WHEN LOWER(role)='private' THEN primary_ipv4 ELSE '' END) private_ipv4
            FROM node_bridge_addresses_latest GROUP BY node
          ), vm_count AS (
            SELECT node,COUNT(DISTINCT vm_uuid) vm_count FROM vm_inventory
            WHERE COALESCE(status,'active')!='hidden' AND deleted_at IS NULL GROUP BY node
          )
          SELECT ni.node,ni.status,ni.last_push,ni.deleted_at,COALESCE(vc.vm_count,0),
                 COALESCE(b.public_ipv4,''),COALESCE(b.private_ipv4,''),ng.id,ng.name,ng.country_code,ng.is_active,
                 COALESCE(ncf.last_seen,ni.last_push,0),ncf.cpu_percent,ncf.mem_used,ncf.mem_total,
                 ncf.disk_read_bps,ncf.disk_write_bps,ncf.total_bytes
          FROM {from_sql}
          LEFT JOIN bridge_ip b ON b.node=ni.node LEFT JOIN vm_count vc ON vc.node=ni.node
          LEFT JOIN node_current_fast ncf ON ncf.node=ni.node
          {where_sql}
          ORDER BY {order_expr} {order.upper()},ni.node COLLATE NOCASE
          LIMIT ? OFFSET ?
        """, params + order_params + [per_page, (page_no - 1) * per_page]).fetchall()
        return rows, total, page_no, max_page
    finally:
        conn.close()


def admin_vms_query(q, status, page_no, per_page):
    m = _m()
    status = m._v48134_clean_admin_status(status)
    status_sql, params = m._v48134_status_sql("vi", "last_seen", status)
    where = [status_sql]
    group_id = _admin_group_filter()
    if group_id:
        where.append("gm.group_id=?")
        params.append(group_id)
    if q:
        p = m.like_pattern(q)
        normalized_mac = m.normalize_mac_address(q)
        where.append("""(
            vi.node LIKE ? OR vi.vm_uuid LIKE ? OR COALESCE(vi.last_iface,'') LIKE ? OR COALESCE(vi.last_bridge,'') LIKE ?
            OR EXISTS (SELECT 1 FROM node_bridge_addresses_latest b WHERE b.node=vi.node AND (
                COALESCE(b.primary_ipv4,'') LIKE ? OR COALESCE(b.ipv4_json,'[]') LIKE ? OR COALESCE(b.mac,'') LIKE ?
                OR (?<>'' AND LOWER(COALESCE(b.mac,''))=LOWER(?))))
            OR EXISTS (SELECT 1 FROM vm_iface_current i WHERE i.node=vi.node AND i.vm_uuid=vi.vm_uuid AND (
                COALESCE(i.iface,'') LIKE ? OR COALESCE(i.bridge,'') LIKE ?))
            OR EXISTS (SELECT 1 FROM vm_nic_identity_lookup l JOIN vm_iface_current i
                ON i.node=l.node AND i.vm_uuid=l.vm_uuid AND i.bridge=l.bridge AND i.iface=l.iface AND i.mac=l.mac
                WHERE l.node=vi.node AND l.vm_uuid=vi.vm_uuid AND (l.mac LIKE ? OR (?<>'' AND l.mac=?)))
        )""")
        params.extend([p, p, p, p, p, p, p, normalized_mac, normalized_mac, p, p, p, normalized_mac, normalized_mac])
    where_sql = "WHERE " + " AND ".join(where)
    conn = m.db()
    try:
        from_sql = """vm_inventory vi
            JOIN node_group_memberships gm ON gm.node=vi.node
            JOIN node_groups ng ON ng.id=gm.group_id"""
        total = m.safe_int(conn.execute(f"SELECT COUNT(*) FROM {from_sql} {where_sql}", params).fetchone()[0], 0)
        max_page = max(1, math.ceil(total / per_page))
        page_no = max(1, min(page_no, max_page))
        rows = conn.execute(f"""
          WITH bridge_ip AS (
            SELECT node,MAX(CASE WHEN LOWER(role)='public' THEN primary_ipv4 ELSE '' END) public_ipv4,
                        MAX(CASE WHEN LOWER(role)='private' THEN primary_ipv4 ELSE '' END) private_ipv4
            FROM node_bridge_addresses_latest GROUP BY node
          )
          SELECT vi.node,vi.vm_uuid,vi.status,vi.last_seen,vi.last_bridge,vi.last_iface,vi.deleted_at,
                 COALESCE(b.public_ipv4,''),COALESCE(b.private_ipv4,''),ng.id,ng.name,ng.country_code,ng.is_active
          FROM {from_sql} LEFT JOIN bridge_ip b ON b.node=vi.node
          {where_sql}
          ORDER BY CASE WHEN COALESCE(vi.status,'active')='hidden' OR vi.deleted_at IS NOT NULL THEN 1 ELSE 0 END,
                   vi.node COLLATE NOCASE,vi.last_seen DESC
          LIMIT ? OFFSET ?
        """, params + [per_page, (page_no - 1) * per_page]).fetchall()
        return rows, total, page_no, max_page
    finally:
        conn.close()


def _filtered_admin_nodes(q, status, page_no, per_page):
    return admin_nodes_query(q, status, page_no, per_page)


def _filtered_admin_vms(q, status, page_no, per_page):
    return admin_vms_query(q, status, page_no, per_page)


def _groups_for_nodes(nodes: list[str]) -> dict[str, tuple[str, str]]:
    unique = sorted({str(node or "").strip() for node in nodes if str(node or "").strip()})
    if not unique:
        return {}
    placeholders = ",".join("?" for _ in unique)
    conn = _m().db()
    try:
        rows = conn.execute(f"""
            SELECT gm.node,g.name,g.country_code
              FROM node_group_memberships gm
              JOIN node_groups g ON g.id=gm.group_id
             WHERE gm.node IN ({placeholders})
        """, unique).fetchall()
        return {str(row[0]): (str(row[1]), str(row[2] or "")) for row in rows}
    finally:
        conn.close()


def admin_pager(section, q, status, page_no, max_page, per_page):
    if max_page <= 1:
        return ""
    m = _m(); args = m.request.args.to_dict(flat=True)
    args.update({"section": section, "q": q or None, "status": status, "per_page": per_page})
    previous = m.url_for("admin_page", **args, page=max(1, page_no - 1))
    following = m.url_for("admin_page", **args, page=min(max_page, page_no + 1))
    return ('<div class="pagination"><a class="btn %s" href="%s">Previous</a>'
            '<span>Page <b>%s</b> / <b>%s</b></span><a class="btn %s" href="%s">Next</a></div>') % (
        "disabled" if page_no <= 1 else "", m.escape(previous, quote=True), page_no, max_page,
        "disabled" if page_no >= max_page else "", m.escape(following, quote=True),
    )


def _admin_sort_link(label: str, key: str) -> str:
    m = _m(); args = m.request.args.to_dict(flat=True)
    current = str(args.get("sort") or "node"); order = str(args.get("order") or "asc")
    args["sort"] = key; args["order"] = "desc" if current == key and order == "asc" else "asc"
    return '<a class="sort-link" href="%s">%s%s</a>' % (
        m.escape(m.url_for("admin_page", **args), quote=True), m.escape(label),
        " &#8593;" if current == key and order == "asc" else " &#8595;" if current == key else "",
    )


def admin_nodes_section(q, status, page_no, per_page):
    m=_m(); selected=_admin_group_filter(); rows,total,page_no,max_page=admin_nodes_query(q,status,page_no,per_page)
    cutoff=m.now_ts()-m.VM_STALE_SECONDS; body=[]
    for row in rows:
        node,row_status,last_push,deleted_at,vm_count,pub,_priv,gid,gname,country,group_active,last_seen,cpu,mem_used,mem_total,disk_read,disk_write,network=row
        node_hidden=str(row_status or "active")=="hidden" or bool(deleted_at)
        agent_stale=not node_hidden and int(last_seen or last_push or 0)<cutoff
        agent="HIDDEN" if node_hidden else "INACTIVE" if agent_stale else "ACTIVE"
        agent_cls="stale" if node_hidden or agent_stale else "active"
        group_state='' if group_active else '<span class="vm-state stale">GROUP HIDDEN</span>'
        cpu_html="N/A" if cpu is None else m.metric_pill(f"{float(cpu):.1f}%",m.metric_level(float(cpu),70,85))
        if int(mem_total or 0)>0:
            ram_pct=float(mem_used or 0)*100.0/float(mem_total)
            ram_html=m.metric_pill(f"{ram_pct:.1f}%",m.metric_level(ram_pct,80,90),"RAM used")
        else: ram_html="N/A"
        toggle=(m.admin_form(m.url_for('admin_restore_node'),'Restore',{'node':node},danger=False,confirm='Restore node to monitoring?') if node_hidden else
                m.admin_form(m.url_for('admin_delete_node'),'Hide',{'node':node,'mode':'soft'},danger=True,confirm='Hide node from monitoring? Raw usage is kept.'))
        move=(f'<form class="inline-form" method="post" action="{m.url_for("admin_node_groups_assign")}">'
              f'<input type="hidden" name="csrf_token" value="{m.escape(m.csrf_token(),quote=True)}">'
              f'<input type="hidden" name="nodes" value="{m.escape(node,quote=True)}">'
              f'<select name="group_id" aria-label="Move {m.escape(node,quote=True)} to Node Group">{group_options_html(int(gid),"Move Group")}</select>'
              '<button type="submit">Move</button></form>')
        purge_vms=m.admin_form(m.url_for('admin_purge_node_vms'),'Purge VMs',{'node':node},danger=True,confirm='Purge every VM and VM history under this node?')
        purge=m.admin_form(m.url_for('admin_delete_node'),'Purge Node',{'node':node,'mode':'purge'},danger=True,confirm='Permanently purge this node and all monitoring data?')
        body.append(f'''<tr class="{'stale-row' if node_hidden or agent_stale or not group_active else ''}">
        <td><a href="{m.url_for('node_page',node=node)}"><b>{flag_html(country)}{m.escape(node)}</b></a></td>
        <td><b>{m.escape(gname)}</b><small class="row-sub">{group_state}</small></td>
        <td class="mono">{m.escape(m.compact_ipv4(pub) or '-')}</td><td><span class="vm-state {agent_cls}">{agent}</span></td>
        <td title="{m.escape(m.fmt_full(last_seen),quote=True)}">{m.fmt_push(last_seen)}</td><td class="num">{int(vm_count or 0):,}</td>
        <td class="num">{cpu_html}</td><td class="num">{ram_html}</td>
        <td class="num">R {m._disk_io_rate(float(disk_read or 0))}<small class="row-sub">W {m._disk_io_rate(float(disk_write or 0))}</small></td>
        <td class="num">{m.human(int(network or 0))}</td><td class="direct-actions">{toggle}{move}{purge_vms}{purge}</td></tr>''')
    if not body: body=['<tr><td colspan="11" class="empty">No nodes match this filter</td></tr>']
    headers=[_admin_sort_link('NODE','node'),_admin_sort_link('NODE GROUP','group'),_admin_sort_link('PUBLIC IP','public_ip'),
             _admin_sort_link('AGENT','agent'),_admin_sort_link('LAST SEEN','last_seen'),_admin_sort_link('VM','vm_count'),
             _admin_sort_link('CPU','cpu'),_admin_sort_link('RAM','ram'),_admin_sort_link('DISK','disk'),_admin_sort_link('NETWORK','network'),'ACTIONS']
    filters=f'''<form class="search" method="get"><input type="hidden" name="section" value="nodes">
    <input name="q" value="{m.escape(q,quote=True)}" placeholder="Search node, group, IP, MAC, VM, bridge or interface">
    {_group_select(selected,include_hidden=True)}<select name="status">{m._v48134_status_options(status)}</select>
    <select name="per_page">{''.join(f'<option value="{n}"{" selected" if per_page==n else ""}>{n} rows</option>' for n in (100,200,500))}</select>
    <input type="hidden" name="sort" value="{m.escape(m.request.args.get('sort') or 'node',quote=True)}"><input type="hidden" name="order" value="{m.escape(m.request.args.get('order') or 'asc',quote=True)}">
    <button>Filter</button><a class="clear" href="{m.url_for('admin_page',section='nodes')}">Reset</a></form>'''
    return f'''<div class="card"><div class="section-head"><div><h3>Node management</h3><p>{total:,} matching node(s). Agent state and Node Group visibility are independent.</p></div></div>{filters}
    <div class="table-wrap"><table class="admin-clean-table node-groups-admin-nodes"><thead><tr>{''.join('<th>'+h+'</th>' for h in headers)}</tr></thead><tbody>{''.join(body)}</tbody></table></div>
    {admin_pager('nodes',q,status,page_no,max_page,per_page)}</div>'''



def admin_vms_section(q, status, page_no, per_page):
    m=_m(); selected=_admin_group_filter(); rows,total,page_no,max_page=admin_vms_query(q,status,page_no,per_page); cutoff=m.now_ts()-m.VM_STALE_SECONDS; body=[]
    for node,vm_uuid,row_status,last_seen,bridge,iface,deleted_at,pub,_priv,_gid,gname,country,group_active in rows:
        hidden=str(row_status or 'active')=='hidden' or bool(deleted_at); stale=not hidden and int(last_seen or 0)<cutoff
        state='HIDDEN' if hidden else 'INACTIVE' if stale else 'ACTIVE'; cls='stale' if hidden or stale else 'active'
        toggle=(m.admin_form(m.url_for('admin_restore_vm'),'Restore',{'node':node,'vm_uuid':vm_uuid},danger=False,confirm='Restore VM to monitoring?') if hidden else
                m.admin_form(m.url_for('admin_delete_vm'),'Hide',{'node':node,'vm_uuid':vm_uuid,'mode':'soft'},danger=True,confirm='Hide VM from monitoring? Raw usage is kept.'))
        purge=m.admin_form(m.url_for('admin_delete_vm'),'Purge VM',{'node':node,'vm_uuid':vm_uuid,'mode':'purge'},danger=True,confirm='Permanently purge only this UUID from VM-scoped tables?')
        group_state=' <span class="vm-state stale">GROUP HIDDEN</span>' if not group_active else ''
        body.append(f'''<tr class="{'stale-row' if hidden or stale or not group_active else ''}"><td><b>{flag_html(country)}{m.escape(node)}</b><small class="row-sub">{m.escape(gname)}{group_state} · {m.escape(m.compact_ipv4(pub) or '-')}</small></td>
        <td class="mono"><span class="uuid-cell">{m.escape(vm_uuid)}<button type="button" class="copy-btn" data-copy="{m.escape(vm_uuid,quote=True)}">Copy</button></span></td>
        <td><span class="vm-state {cls}">{state}</span><small class="row-sub">{m.fmt_push(last_seen)}</small></td>
        <td>{m.escape(bridge or '-')}<small class="row-sub">{m.escape(iface or '-')}</small></td><td class="direct-actions">{toggle}{purge}</td></tr>''')
    if not body: body=['<tr><td colspan="5" class="empty">No VMs match this filter</td></tr>']
    filters=f'''<form class="search" method="get"><input type="hidden" name="section" value="vms"><input name="q" value="{m.escape(q,quote=True)}" placeholder="Search node, group, IP, MAC, VM UUID, bridge or interface">
    {_group_select(selected,include_hidden=True)}<select name="status">{m._v48134_status_options(status)}</select><select name="per_page">{''.join(f'<option value="{n}"{" selected" if per_page==n else ""}>{n} rows</option>' for n in (100,200,500))}</select>
    <button>Filter</button><a class="clear" href="{m.url_for('admin_page',section='vms')}">Reset</a></form>'''
    return f'''<div class="card"><div class="section-head"><div><h3>VM management</h3><p>{total:,} matching VM(s). Actions apply to one explicit VM only.</p></div></div>{filters}
    <div class="table-wrap"><table class="admin-clean-table node-groups-admin-vms"><thead><tr><th>NODE / GROUP / IP</th><th>VM UUID</th><th>AGENT STATUS / SEEN</th><th>BRIDGE / IFACE</th><th>ACTIONS</th></tr></thead><tbody>{''.join(body)}</tbody></table></div>
    {admin_pager('vms',q,status,page_no,max_page,per_page)}</div>'''


def admin_page():
    m = _m()
    deny = require_admin()
    if deny:
        return deny
    section = str(m.request.args.get("section") or "overview").strip().lower()
    if current_role() == "admin" and section == "maintenance":
        return m.Response("Forbidden: super_admin role required\n", status=403, mimetype="text/plain")
    if section != "groups":
        return _BASE["admin_page_view"]()
    content = f'''
    <div class="card admin-hero"><div><span class="eyebrow">CONTROL CENTER</span><h2>Administration</h2><p>Inventory, policy, users and maintenance are separated into focused sections.</p></div><div class="admin-user-actions"><a class="btn" href="{m.url_for('index')}">Dashboard</a><a class="btn" href="{m.url_for('admin_logout')}">Logout</a></div></div>
    {admin_nav('groups')}
    {_group_management_section()}
    '''
    return m.page("Admin", content)


def admin_node_groups_create():
    m = _m()
    deny = require_admin()
    if deny:
        return deny
    name = str(m.request.form.get("name") or "").strip()
    description = str(m.request.form.get("description") or "").strip()[:500]
    country = _clean_country_code(m.request.form.get("country_code"))
    if not name or len(name) > 80 or name.lower() == SYSTEM_GROUP_NAME.lower():
        return m.Response("Invalid or reserved group name\n", status=400, mimetype="text/plain")
    actor = _actor()
    conn = m.db()
    try:
        result = conn.execute("""
            INSERT INTO node_groups(name,description,country_code,is_active,is_system,created_at,updated_at)
            VALUES (?,?,?,1,0,?,?)
        """, (name, description, country, _ts(), _ts()))
        group_id = int(result.lastrowid)
        new_row = (group_id, name)
        _audit_group_event(conn, "node_group_created", actor, None, new_row)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        return m.Response(f"Could not create Node Group: {exc}\n", status=400, mimetype="text/plain")
    finally:
        conn.close()
    m.log_account_event("node_group_created", username=actor, realm="admin", role=current_role(), detail=f"group_id={group_id};group={name};country={country}")
    return m.redirect(m.url_for("admin_page", section="groups"))


def admin_node_groups_update():
    m = _m()
    deny = require_admin()
    if deny:
        return deny
    group_id = m.safe_int(m.request.form.get("group_id"), 0)
    name = str(m.request.form.get("name") or "").strip()
    description = str(m.request.form.get("description") or "").strip()[:500]
    country = _clean_country_code(m.request.form.get("country_code"))
    row = group_row(group_id)
    if not row:
        return m.Response("Node Group not found\n", status=404, mimetype="text/plain")
    if row[5]:
        return m.Response("Ungrouped cannot be renamed or edited\n", status=400, mimetype="text/plain")
    if not name or len(name) > 80 or name.lower() == SYSTEM_GROUP_NAME.lower():
        return m.Response("Invalid or reserved group name\n", status=400, mimetype="text/plain")
    actor = _actor()
    conn = m.db()
    try:
        conn.execute("UPDATE node_groups SET name=?,description=?,country_code=?,updated_at=? WHERE id=?", (name, description, country, _ts(), group_id))
        _audit_group_event(conn, "node_group_updated", actor, row, (group_id, name))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        return m.Response(f"Could not update Node Group: {exc}\n", status=400, mimetype="text/plain")
    finally:
        conn.close()
    m.log_account_event("node_group_updated", username=actor, realm="admin", role=current_role(), detail=f"group_id={group_id};old_group={row[1]};new_group={name};country={country}")
    return m.redirect(m.url_for("admin_page", section="groups"))


def admin_node_groups_action():
    m = _m(); deny = require_admin()
    if deny: return deny
    group_id = m.safe_int(m.request.form.get("group_id"), 0); action = str(m.request.form.get("action") or "").strip().lower(); row = group_row(group_id)
    if not row: return m.Response("Node Group not found\n", status=404, mimetype="text/plain")
    if row[5]: return m.Response("Ungrouped cannot be renamed, hidden or deleted\n", status=400, mimetype="text/plain")
    if action not in {"hide", "restore", "delete"}: return m.Response("Invalid Node Group action\n", status=400, mimetype="text/plain")
    actor = _actor(); conn = m.db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT id,name,description,country_code,is_active,is_system,created_at,updated_at,hidden_at FROM node_groups WHERE id=?", (group_id,)).fetchone()
        if not current: conn.rollback(); return m.Response("Node Group not found\n", status=404, mimetype="text/plain")
        if action == "delete":
            count = int(conn.execute("SELECT COUNT(*) FROM node_group_memberships WHERE group_id=?", (group_id,)).fetchone()[0] or 0)
            if count:
                conn.rollback()
                return m.Response("Cannot delete this group because it still contains nodes.\nMove or remove all nodes from the group first.\n", status=409, mimetype="text/plain")
            _audit_group_event(conn, "node_group_deleted", actor, current, None); conn.execute("DELETE FROM node_groups WHERE id=?", (group_id,)); event = "node_group_deleted"
        elif action == "hide":
            conn.execute("UPDATE node_groups SET is_active=0,hidden_at=?,updated_at=? WHERE id=?", (_ts(), _ts(), group_id)); _audit_group_event(conn, "node_group_hidden", actor, current, (group_id, current[1])); event = "node_group_hidden"
        else:
            conn.execute("UPDATE node_groups SET is_active=1,hidden_at=NULL,updated_at=? WHERE id=?", (_ts(), group_id)); _audit_group_event(conn, "node_group_restored", actor, current, (group_id, current[1])); event = "node_group_restored"
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally: conn.close()
    m.log_account_event(event, username=actor, realm="admin", role=current_role(), detail=f"group_id={group_id};group={row[1]}")
    return m.redirect(m.url_for("admin_page", section="groups"))



def admin_node_groups_assign():
    m = _m()
    deny = require_admin()
    if deny:
        return deny
    nodes = [str(x or "").strip() for x in m.request.form.getlist("nodes") if str(x or "").strip()]
    group_id = m.safe_int(m.request.form.get("group_id"), 0)
    if not nodes or group_id <= 0:
        return m.Response("Nodes and group_id are required\n", status=400, mimetype="text/plain")
    assign_nodes(nodes, group_id, _actor())
    return m.redirect(m.url_for("admin_page", section="nodes"))


def admin_bulk_nodes():
    action = str(_m().request.form.get("action") or "").strip().lower()
    if action in {"assign_group", "add_group", "move_group", "remove_group", "move_ungrouped"}:
        return admin_node_groups_bulk()
    return _BASE["admin_bulk_nodes"]()



def dashboard_login():
    m = _m()
    next_url = m.safe_next_url(m.request.args.get("next") or m.request.form.get("next") or m.url_for("index"))
    error = ""
    if m.dashboard_allowed():
        return m.redirect(next_url)
    bootstrap_dashboard_admin_from_settings()
    if not m.admin_is_configured() and m.dashboard_user_count() == 0:
        return m.redirect(m.url_for("admin_setup"))
    username_value = m.clean_username(m.request.form.get("username") or "")
    if m.request.method == "POST":
        password = m.request.form.get("password") or ""
        user = m.get_dashboard_user(username_value)
        if not user:
            m.log_account_event("login_failed", username=username_value, realm="dashboard", detail="unknown user")
            error = "Invalid username or password."
        else:
            user_id, username, password_hash, role, is_active, *_ = user
            role = clean_role(role)
            if not is_active:
                m.log_account_event("login_failed", username=username, realm="dashboard", role=role, detail="disabled user")
                error = "This user is disabled."
            elif not m.check_password_hash(password_hash, password):
                m.log_account_event("login_failed", username=username, realm="dashboard", role=role, detail="bad password")
                error = "Invalid username or password."
            else:
                m.session.clear()
                m.session["dashboard_authenticated"] = True
                m.session["dashboard_user_id"] = int(user_id)
                m.session["dashboard_username"] = username
                m.session["dashboard_role"] = role
                if role in {"admin", "super_admin"}:
                    m.session["admin_authenticated"] = True
                    m.session["admin_username"] = username
                m.session["csrf_token"] = m.secrets.token_urlsafe(32)
                m.update_dashboard_user_login(user_id)
                m.log_account_event("login_success", username=username, realm="dashboard", role=role)
                return m.redirect(next_url)
    error_html = f'<div class="login-alert error">{m.escape(error)}</div>' if error else ""
    note_html = '<div class="login-alert note">No dashboard users exist yet. Open Administrator setup to create the first account.</div>' if m.dashboard_user_count() == 0 else ""
    password_field = m._v48106_password_field("dashboard-login-password", "password", "Password", "current-password")
    return m.Response(m._v48106_login_document(
        action=m.url_for("dashboard_login"), title="Monitoring access",
        subtitle="Sign in to view infrastructure health and performance.",
        username_value=username_value, error_html=error_html, note_html=note_html,
        next_url=next_url, button_label="Sign in", extra_fields=password_field,
    ), mimetype="text/html")



def admin_login():
    m = _m()
    next_url = m.safe_next_url(m.request.args.get("next") or m.request.form.get("next") or m.url_for("admin_page"))
    error = ""
    bootstrap_dashboard_admin_from_settings()
    if emergency_admin_needed():
        return m.redirect(m.url_for("admin_setup"))
    if admin_allowed():
        return m.redirect(next_url)
    admin_username = m.get_admin_username()
    form_username = admin_username
    if m.request.method == "POST":
        username = str(m.request.form.get("username") or "").strip()
        form_username = username or admin_username
        password = m.request.form.get("password") or ""
        user = m.get_dashboard_user(username)
        if user:
            user_id, user_name, user_hash, role, is_active, *_ = user
            role = clean_role(role)
            if role not in {"admin", "super_admin"} or not is_active:
                m.log_account_event("login_failed", username=username, realm="admin", role=role, detail="admin user disabled or invalid")
                error = "This user is disabled or does not have an administrator role."
            elif not m.check_password_hash(user_hash, password):
                m.log_account_event("login_failed", username=username, realm="admin", role=role, detail="bad password")
                error = "Invalid username or password."
            else:
                m.session.clear(); m.session["dashboard_authenticated"] = True; m.session["dashboard_user_id"] = int(user_id); m.session["dashboard_username"] = user_name; m.session["dashboard_role"] = role; m.session["admin_authenticated"] = True; m.session["admin_username"] = user_name; m.session["csrf_token"] = m.secrets.token_urlsafe(32)
                m.update_dashboard_user_login(user_id); m.log_account_event("login_success", username=user_name, realm="admin", role=role)
                return m.redirect(next_url)
        else:
            legacy_name = m.get_admin_username(); legacy_hash = m.get_admin_password_hash()
            if username == legacy_name and legacy_hash and m.check_password_hash(legacy_hash, password):
                m.upsert_dashboard_user(username, password, role="super_admin", is_active=1)
                converted = m.get_dashboard_user(username)
                if converted:
                    m.session.clear(); m.session["dashboard_authenticated"] = True; m.session["dashboard_user_id"] = int(converted[0]); m.session["dashboard_username"] = username; m.session["dashboard_role"] = "super_admin"; m.session["admin_authenticated"] = True; m.session["admin_username"] = username; m.session["csrf_token"] = m.secrets.token_urlsafe(32)
                    m.update_dashboard_user_login(converted[0]); m.log_account_event("login_success", username=username, realm="admin", role="super_admin", detail="legacy admin converted")
                    return m.redirect(next_url)
            m.log_account_event("login_failed", username=username, realm="admin", role="", detail="unknown admin user")
            error = "Invalid username or password."
    error_html = f'<div class="login-alert error">{m.escape(error)}</div>' if error else ""
    note_html = '<div class="login-alert note">Administrator access. Restricted Admin and full Super Admin roles can sign in here.</div>'
    extra = m._v48106_password_field("admin-login-password", "password", "Password", "current-password")
    return m.Response(m._v48106_login_document(action=m.url_for("admin_login"), title="Administrator access", subtitle="Sign in to manage the operations console.", username_value=form_username, error_html=error_html, note_html=note_html, next_url=next_url, button_label="Sign in", extra_fields=extra), mimetype="text/html")


def admin_setup():
    m = _m()
    bootstrap_dashboard_admin_from_settings()
    emergency_mode = emergency_admin_needed()
    if m.admin_is_configured() and not emergency_mode and not admin_allowed():
        return m.redirect(m.url_for("admin_login"))
    if m.admin_is_configured() and not emergency_mode and admin_allowed():
        return m.redirect(m.url_for("admin_page"))
    error = ""
    username_value = str(m.request.form.get("username") or "admin").strip() or "admin"
    if m.request.method == "POST":
        password = m.request.form.get("password") or ""
        confirm = m.request.form.get("confirm") or ""
        if len(username_value) < 3:
            error = "Username must be at least 3 characters."
        elif len(password) < 10:
            error = "Password must be at least 10 characters."
        elif password != confirm:
            error = "Password confirmation does not match."
        else:
            set_admin_credentials(username_value, password)
            created = m.get_dashboard_user(username_value)
            m.session.clear(); m.session["dashboard_authenticated"] = True
            if created:
                m.session["dashboard_user_id"] = int(created[0])
            m.session["dashboard_username"] = username_value; m.session["dashboard_role"] = "super_admin"; m.session["admin_authenticated"] = True; m.session["admin_username"] = username_value; m.session["csrf_token"] = m.secrets.token_urlsafe(32)
            m.log_account_event("setup_admin", username=username_value, realm="admin", role="super_admin")
            return m.redirect(m.url_for("admin_page"))
    error_html = f'<div class="login-alert error">{m.escape(error)}</div>' if error else ""
    note = "No enabled Super Admin exists. Create one here to recover full access." if emergency_mode else "Create the first Super Admin account."
    note_html = f'<div class="login-alert note">{m.escape(note)}</div>'
    extra = m._v48106_password_field("admin-setup-password", "password", "Password", "new-password") + m._v48106_password_field("admin-setup-confirm", "confirm", "Confirm password", "new-password")
    title = "Emergency Super Admin Setup" if emergency_mode else "Initial Super Admin Setup"
    return m.Response(m._v48106_login_document(action=m.url_for("admin_setup"), title=title, subtitle="Create a full-privilege account for the operations console.", username_value=username_value, error_html=error_html, note_html=note_html, next_url="", button_label="Create Super Admin", extra_fields=extra), mimetype="text/html")

# ---------------------------------------------------------------------------
# Role-aware user management
# ---------------------------------------------------------------------------

def dashboard_role():
    return current_role()


def active_admin_count(exclude_user_id=None):
    """Compatibility name: only Super Admin accounts satisfy recovery safety."""
    return active_super_admin_count(exclude_user_id=exclude_user_id)


def _manageable_roles() -> tuple[str, ...]:
    return ("viewer", "admin", "super_admin") if is_super_admin() else ("viewer", "admin")


def _can_manage_user(target_role: Any) -> bool:
    return is_super_admin() or clean_role(target_role) != "super_admin"


def admin_users_page():
    m = _m()
    deny = require_admin()
    if deny:
        return deny
    users = m.get_dashboard_users()
    current_id = m.current_dashboard_user_id()
    roles = _manageable_roles()
    role_options = lambda selected: "".join(
        '<option value="%s"%s>%s</option>' % (
            role, " selected" if role == clean_role(selected) else "", role,
        ) for role in roles
    )
    body = []
    for user_id, username, role, is_active, created_at, _updated_at, last_login in users:
        role = clean_role(role)
        badges = []
        if int(user_id) == int(current_id or 0):
            badges.append('<span class="vm-state active">CURRENT</span>')
        if role == "super_admin" and is_active and is_last_enabled_admin(user_id):
            badges.append('<span class="vm-state stale">LAST SUPER ADMIN</span>')
        can_manage = _can_manage_user(role) and int(user_id) != int(current_id or 0)
        if can_manage:
            toggle_label = "Disable" if is_active else "Enable"
            toggle_action = "disable" if is_active else "enable"
            reset = (
                f'<form class="inline-form" method="post" action="{m.url_for("admin_user_action")}" '
                'onsubmit="return confirm(\'Reset this user password and role?\')">'
                f'<input type="hidden" name="csrf_token" value="{m.escape(m.csrf_token(), quote=True)}">'
                f'<input type="hidden" name="user_id" value="{int(user_id)}">'
                '<input type="hidden" name="action" value="reset_password">'
                '<input name="new_password" type="password" minlength="10" placeholder="New password" autocomplete="new-password" required>'
                f'<select name="role">{role_options(role)}</select><button type="submit">Reset</button></form>'
            )
            actions = reset + m.admin_form(
                m.url_for("admin_user_action"), toggle_label,
                {"user_id": user_id, "action": toggle_action},
                danger=False, confirm=f"{toggle_label} this user?",
            ) + m.admin_form(
                m.url_for("admin_user_action"), "Delete",
                {"user_id": user_id, "action": "delete"},
                danger=True, confirm="Delete this dashboard user?",
            )
        elif int(user_id) == int(current_id or 0):
            actions = f'<a class="btn" href="{m.url_for("admin_change_password")}">Change my password</a>'
        else:
            actions = '<span class="muted">Super Admin only</span>'
        body.append(
            f'<tr><td>{int(user_id)}</td><td class="mono"><b>{m.escape(username)}</b> {" ".join(badges)}</td>'
            f'<td>{m.escape(role)}</td><td><span class="vm-state {"active" if is_active else "stale"}">'
            f'{"ACTIVE" if is_active else "DISABLED"}</span></td><td>{m.fmt_full(created_at)}</td>'
            f'<td>{m.fmt_full(last_login)}</td><td>{actions}</td></tr>'
        )
    if not body:
        body.append('<tr><td colspan="7" class="empty">No dashboard users</td></tr>')
    create_roles = "".join(f'<option value="{role}">{role}</option>' for role in roles)
    content = f'''
    <div class="card"><div class="section-head"><div><h3>Dashboard Users</h3>
    <p>Admins can manage Viewer and Admin accounts. Super Admin accounts remain protected from Admin actions.</p></div>
    <a class="btn" href="{m.url_for('admin_page')}">Back to Admin</a></div></div>
    <div class="card"><h3>Create User</h3><form class="search" method="post" action="{m.url_for('admin_create_user')}">
    <input type="hidden" name="csrf_token" value="{m.escape(m.csrf_token(), quote=True)}">
    <input name="username" minlength="3" placeholder="Username" autocomplete="username" required>
    <input name="password" type="password" minlength="10" placeholder="Password" autocomplete="new-password" required>
    <select name="role">{create_roles}</select><button type="submit">Create user</button></form></div>
    <div class="card"><div class="table-wrap"><table><thead><tr><th>ID</th><th>USERNAME</th><th>ROLE</th>
    <th>STATUS</th><th>CREATED</th><th>LAST LOGIN</th><th>ACTION</th></tr></thead>
    <tbody>{''.join(body)}</tbody></table></div></div>'''
    return m.page("Dashboard Users", content)



def admin_create_user():
    m = _m()
    deny = require_admin()
    if deny:
        return deny
    username = m.clean_username(m.request.form.get("username"))
    password = m.request.form.get("password") or ""
    role = clean_role(m.request.form.get("role"))
    if role not in _manageable_roles() or not username or len(username) < 3 or len(password) < 10:
        return m.Response("Unable to create user with the provided information.\n", status=400, mimetype="text/plain")
    if m.get_dashboard_user(username):
        return m.Response("Unable to create user with the provided information.\n", status=400, mimetype="text/plain")
    m.upsert_dashboard_user(username, password, role=role, is_active=1)
    m.log_account_event("user_created", username=username, realm="admin", role=role, detail=f"created_by={_actor()}")
    return m.redirect(m.url_for("admin_users_page"))



def admin_user_action():
    m = _m()
    deny = require_admin()
    if deny:
        return deny
    user_id = m.safe_int(m.request.form.get("user_id"), 0)
    action = str(m.request.form.get("action") or "").strip().lower()
    if user_id <= 0:
        return m.Response("Missing user_id\n", status=400, mimetype="text/plain")
    target = m.get_dashboard_user_by_id(user_id)
    if not target:
        return m.Response("User not found\n", status=404, mimetype="text/plain")
    _id, username, _password_hash, old_role, old_is_active, *_rest = target
    old_role = clean_role(old_role)
    if not _can_manage_user(old_role):
        return m.Response("Forbidden: Super Admin account is protected\n", status=403, mimetype="text/plain")
    if int(user_id) == int(m.current_dashboard_user_id() or 0):
        return m.Response("Use Change My Password for the signed-in account.\n", status=400, mimetype="text/plain")
    if action in {"disable", "delete"} and is_last_enabled_admin(user_id):
        return m.Response("Safety block: the last enabled Super Admin cannot be disabled or deleted.\n", status=400, mimetype="text/plain")
    if action == "disable":
        m.set_dashboard_user_status(user_id, 0)
        event, event_role = "user_disabled", old_role
    elif action == "enable":
        m.set_dashboard_user_status(user_id, 1)
        event, event_role = "user_enabled", old_role
    elif action == "delete":
        m.delete_dashboard_user(user_id)
        event, event_role = "user_deleted", old_role
    elif action == "reset_password":
        password = m.request.form.get("new_password") or ""
        role = clean_role(m.request.form.get("role") or old_role)
        if len(password) < 10:
            return m.Response("New password must be at least 10 characters\n", status=400, mimetype="text/plain")
        if role not in _manageable_roles():
            return m.Response("Forbidden: role elevation is not allowed\n", status=403, mimetype="text/plain")
        if old_role == "super_admin" and role != "super_admin" and is_last_enabled_admin(user_id):
            return m.Response("Safety block: the last enabled Super Admin cannot be downgraded.\n", status=400, mimetype="text/plain")
        m.reset_dashboard_user_password(user_id, password, role=role)
        event, event_role = "user_password_reset", role
    else:
        return m.Response("Invalid action\n", status=400, mimetype="text/plain")
    m.log_account_event(event, username=username, realm="admin", role=event_role, detail=f"changed_by={_actor()}")
    return m.redirect(m.url_for("admin_users_page"))


def admin_change_password():
    """Change only the signed-in dashboard user's password and no other field."""
    m = _m()
    deny = m.require_dashboard()
    if deny:
        return deny
    user = m.current_dashboard_user()
    if not user or not bool(user[4]):
        return m.Response("Login required\n", status=401, mimetype="text/plain")
    error = ""
    success = ""
    if m.request.method == "POST":
        if m.request.form.get("csrf_token") != m.session.get("csrf_token"):
            return m.Response("CSRF check failed\n", status=403, mimetype="text/plain")
        current = m.request.form.get("current_password") or ""
        password = m.request.form.get("new_password") or ""
        confirm = m.request.form.get("confirm_password") or ""
        if not m.check_password_hash(user[2], current):
            error = "Current password is incorrect."
        elif len(password) < 10:
            error = "New password must be at least 10 characters."
        elif password != confirm:
            error = "Password confirmation does not match."
        else:
            conn = m.db()
            try:
                conn.execute(
                    "UPDATE dashboard_users SET password_hash=?,updated_at=? WHERE id=?",
                    (m.generate_password_hash(password), _ts(), int(user[0])),
                )
                conn.commit()
            finally:
                conn.close()
            m.log_account_event("password_changed", username=user[1], realm="dashboard", role=clean_role(user[3]))
            success = "Your password has been updated."
    back = m.url_for("admin_page") if clean_role(user[3]) in {"admin", "super_admin"} else m.url_for("index")
    content = f'''<div class="card login-card"><h3>Change My Password</h3><a href="{back}">Back</a>
    {'<div class="error-box">'+m.escape(error)+'</div>' if error else ''}
    {'<div class="success-box">'+m.escape(success)+'</div>' if success else ''}
    <form method="post" action="{m.url_for('admin_change_password')}">
    <input type="hidden" name="csrf_token" value="{m.escape(m.csrf_token(), quote=True)}">
    <label>Current Password</label><input name="current_password" type="password" autocomplete="current-password" required autofocus>
    <label>New Password</label><input name="new_password" type="password" minlength="10" autocomplete="new-password" required>
    <label>Confirm New Password</label><input name="confirm_password" type="password" minlength="10" autocomplete="new-password" required>
    <button type="submit">Update my password</button></form></div>'''
    return m.page("Change My Password", content)




# ---------------------------------------------------------------------------
# Monitoring data filters. Every path uses the same active-group visibility set.
# ---------------------------------------------------------------------------

def get_node_rows(period, q="", sort_by="node", order="asc", target_ts=None):
    gid = selected_group_id()
    rows, start, end = _BASE["get_node_rows"](period, q, sort_by=sort_by, order=order, target_ts=target_ts)
    allowed = get_visible_node_names(gid)
    return [row for row in rows if str(row[0]) in allowed], start, end


def get_node_health_rows(q="", sort_by="status", order="asc"):
    gid = selected_group_id()
    rows = _BASE["get_node_health_rows"](q=q, sort_by=sort_by, order=order)
    allowed = get_visible_node_names(gid)
    return [row for row in rows if str(row[0]) in allowed]


def _group_top_raw_rows(period, q, sort_by, order, scope, limit, group_id):
    m = _m()
    history = m._request_target_ts() is not None or m.clean_period(period) != "5m"
    sort_by = m.clean_top_sort(sort_by)
    order = m.clean_sort_order(order)
    scope = m.clean_top_scope(scope)
    limit = max(10, min(1000, m.safe_int(limit, 100)))
    if history:
        m.auto_cleanup_inventory()
        conn = m.db()
        try:
            selected_bucket, latest_bucket = m.resolve_snapshot_bucket(conn, period, node=None)
            if not selected_bucket:
                return [], 0, 0, limit
            params = [m.CACHE_BUCKET_SECONDS, m.CACHE_BUCKET_SECONDS, selected_bucket, m.PUBLIC_BRIDGE, m.PRIVATE_BRIDGE, m.CACHE_BUCKET_SECONDS, m.CACHE_BUCKET_SECONDS, selected_bucket, group_id]
            extra_sql = " AND EXISTS (SELECT 1 FROM node_group_memberships gm WHERE gm.node=ns.node AND gm.group_id=?)"
            if scope == "public":
                extra_sql += " AND ns.bridge=?"; params.append(m.PUBLIC_BRIDGE)
            elif scope == "private":
                extra_sql += " AND ns.bridge=?"; params.append(m.PRIVATE_BRIDGE)
            if q:
                p = m.like_pattern(q)
                extra_sql += """ AND (ns.node LIKE ? OR ns.vm_uuid LIKE ? OR ns.iface LIKE ? OR EXISTS (SELECT 1 FROM node_bridge_addresses_latest bai WHERE bai.node=ns.node AND (COALESCE(bai.primary_ipv4,'') LIKE ? OR COALESCE(bai.ipv4_json,'[]') LIKE ?)))"""
                params.extend([p, p, p, p, p])
            order_map = {"total":"total","rx":"rx","tx":"tx","public":"public_total","private":"private_total","mbps":"avg_mbps","peakmbps":"peak_mbps","pps":"avg_pps","peakpps":"peak_pps","sample":"sample_quality_rank","drops":"drops","errors":"errors","cpu":"core_cpu_percent","cpufull":"cpu_percent","vcpu":"vcpu_current","ram":"ram_rss_kib","diskr":"disk_read_bps","diskw":"disk_write_bps","last_push":"last_push","node":"ns.node COLLATE NOCASE","vm":"ns.vm_uuid COLLATE NOCASE"}
            params.append(limit)
            rows = conn.execute(f"""
              WITH perf AS (
                SELECT node,vm_uuid,MAX(COALESCE(cpu_percent,0)) cpu_percent,MAX(COALESCE(vcpu_current,0)) vcpu_current,MAX(COALESCE(ram_rss_kib,0)) ram_rss_kib,MAX(COALESCE(ram_current_kib,0)) ram_current_kib,
                       MAX(COALESCE(disk_read_delta,0)*1.0/MAX(COALESCE(interval_seconds,?),1)) disk_read_bps,MAX(COALESCE(disk_write_delta,0)*1.0/MAX(COALESCE(interval_seconds,?),1)) disk_write_bps
                  FROM vm_perf_stats WHERE bucket=? GROUP BY node,vm_uuid)
              SELECT ns.node,ns.vm_uuid,COUNT(DISTINCT ns.bridge||':'||ns.iface) iface_count,
                     SUM(CASE WHEN ns.bridge=? THEN ns.rx_delta+ns.tx_delta ELSE 0 END) public_total,SUM(CASE WHEN ns.bridge=? THEN ns.rx_delta+ns.tx_delta ELSE 0 END) private_total,
                     SUM(ns.rx_delta) rx,SUM(ns.tx_delta) tx,SUM(ns.rx_delta+ns.tx_delta) total,SUM(ns.rx_packets_delta+ns.tx_packets_delta) packets,SUM(ns.rx_drop_delta+ns.tx_drop_delta) drops,SUM(ns.rx_error_delta+ns.tx_error_delta) errors,
                     SUM((ns.rx_delta+ns.tx_delta)*8.0/MAX(COALESCE(ns.interval_seconds,1),1)/1000000.0) avg_mbps,MAX(MAX(COALESCE(ns.rx_mbps_peak,0),COALESCE(ns.tx_mbps_peak,0))) peak_mbps,
                     SUM(ns.rx_packets_delta+ns.tx_packets_delta)*1.0/MAX(MAX(COALESCE(ns.interval_seconds,?)),1) avg_pps,MAX(MAX(COALESCE(ns.rx_pps_peak,0),COALESCE(ns.tx_pps_peak,0))) peak_pps,
                     SUM(COALESCE(ns.network_sample_count,0)) sample_count,SUM(COALESCE(ns.network_sample_expected,0)) sample_expected,MAX(COALESCE(ns.network_sample_max_gap_seconds,0)) sample_max_gap_seconds,
                     SUM(COALESCE(ns.seconds_over_pps,0)) seconds_over_pps,SUM(COALESCE(ns.seconds_over_mbps,0)) seconds_over_mbps,
                     MAX(CASE UPPER(COALESCE(ns.network_sample_quality,'LEGACY')) WHEN 'POOR' THEN 3 WHEN 'DEGRADED' THEN 2 WHEN 'GOOD' THEN 1 ELSE 0 END) sample_quality_rank,
                     MAX(COALESCE(p.cpu_percent,0)) cpu_percent,MAX(COALESCE(p.vcpu_current,0)) vcpu_current,
                     MAX(CASE WHEN COALESCE(p.cpu_percent,0)<=100 THEN COALESCE(p.cpu_percent,0)*CASE WHEN COALESCE(p.vcpu_current,0)>0 THEN p.vcpu_current ELSE 1 END ELSE COALESCE(p.cpu_percent,0) END) core_cpu_percent,
                     MAX(COALESCE(p.ram_rss_kib,0)) ram_rss_kib,MAX(COALESCE(p.ram_current_kib,0)) ram_current_kib,MAX(COALESCE(p.disk_read_bps,0)) disk_read_bps,MAX(COALESCE(p.disk_write_bps,0)) disk_write_bps,
                     MAX(ns.last_push) last_push,MAX(COALESCE(ns.interval_seconds,?)) interval_seconds,
                     COALESCE((SELECT bai.primary_ipv4 FROM node_bridge_addresses_latest bai WHERE bai.node=ns.node AND LOWER(bai.role)='public' ORDER BY bai.last_seen DESC LIMIT 1),'') public_ipv4,
                     COALESCE((SELECT bai.primary_ipv4 FROM node_bridge_addresses_latest bai WHERE bai.node=ns.node AND LOWER(bai.role)='private' ORDER BY bai.last_seen DESC LIMIT 1),'') private_ipv4
                FROM node_stats ns LEFT JOIN node_inventory ni ON ni.node=ns.node LEFT JOIN vm_inventory vi ON vi.node=ns.node AND vi.vm_uuid=ns.vm_uuid LEFT JOIN perf p ON p.node=ns.node AND p.vm_uuid=ns.vm_uuid
               WHERE ns.bucket=? AND (ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL)) AND COALESCE(vi.status,'active')!='hidden' {extra_sql}
               GROUP BY ns.node,ns.vm_uuid HAVING SUM(COALESCE(ns.rx_delta,0)+COALESCE(ns.tx_delta,0))>0
               ORDER BY {order_map[sort_by]} {order.upper()},total DESC,ns.node COLLATE NOCASE ASC,ns.vm_uuid COLLATE NOCASE ASC LIMIT ?
            """, params).fetchall()
            return rows, selected_bucket, latest_bucket, limit
        finally:
            conn.close()
    field = {"total":"c.total_bytes","rx":"c.rx_bytes","tx":"c.tx_bytes","public":"(c.public_rx_bytes+c.public_tx_bytes)","private":"(c.private_rx_bytes+c.private_tx_bytes)","mbps":"c.total_mbps","peakmbps":"c.total_peak_mbps","pps":"c.total_pps","peakpps":"c.total_peak_pps","sample":"c.sample_quality","drops":"c.drops","errors":"c.errors","cpu":"c.cpu_core_percent","cpufull":"c.cpu_full_percent","vcpu":"c.vcpu_current","ram":"c.ram_rss_kib","diskr":"c.disk_read_bps","diskw":"c.disk_write_bps","last_push":"c.last_seen","node":"c.node COLLATE NOCASE","vm":"c.vm_uuid COLLATE NOCASE"}[sort_by]
    params = [m.now_ts() - m.FAST_CURRENT_STALE_SECONDS, group_id]
    where_sql = " AND EXISTS (SELECT 1 FROM node_group_memberships gm WHERE gm.node=c.node AND gm.group_id=?)"
    if scope == "public": where_sql += " AND (c.public_rx_bytes+c.public_tx_bytes)>0"
    elif scope == "private": where_sql += " AND (c.private_rx_bytes+c.private_tx_bytes)>0"
    if q:
        p = m.like_pattern(q); where_sql += """ AND (c.node LIKE ? OR c.vm_uuid LIKE ? OR EXISTS(SELECT 1 FROM node_bridge_addresses_latest b WHERE b.node=c.node AND (b.primary_ipv4 LIKE ? OR b.ipv4_json LIKE ?)))"""; params.extend([p,p,p,p])
    params.append(limit)
    conn = m.db()
    try:
        rows = conn.execute(f"""
          SELECT c.node,c.vm_uuid,c.iface_count,c.public_rx_bytes+c.public_tx_bytes,c.private_rx_bytes+c.private_tx_bytes,c.rx_bytes,c.tx_bytes,c.total_bytes,
                 CAST(c.total_pps*c.interval_seconds AS INTEGER),c.drops,c.errors,c.total_mbps,c.total_peak_mbps,c.total_pps,c.total_peak_pps,
                 c.sample_count,c.sample_expected,c.sample_max_gap,c.seconds_over_rx_pps+c.seconds_over_tx_pps,0,
                 CASE UPPER(c.sample_quality) WHEN 'POOR' THEN 3 WHEN 'DEGRADED' THEN 2 WHEN 'GOOD' THEN 1 ELSE 0 END,
                 c.cpu_full_percent,c.vcpu_current,c.cpu_core_percent,c.ram_rss_kib,c.ram_current_kib,c.disk_read_bps,c.disk_write_bps,c.last_seen,c.interval_seconds,
                 COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest b WHERE b.node=c.node AND LOWER(role)='public' LIMIT 1),''),
                 COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest b WHERE b.node=c.node AND LOWER(role)='private' LIMIT 1),'')
            FROM vm_current_fast c LEFT JOIN vm_inventory vi ON vi.node=c.node AND vi.vm_uuid=c.vm_uuid
           WHERE c.last_seen>=? AND COALESCE(vi.status,'active')!='hidden' {where_sql}
           ORDER BY {field} {order.upper()},c.total_bytes DESC,c.node COLLATE NOCASE,c.vm_uuid COLLATE NOCASE LIMIT ?
        """, params).fetchall()
        latest = max([m.safe_int(r[28], 0) for r in rows] or [0])
        return rows, latest, latest, limit
    finally:
        conn.close()


def get_top_vm_rows(period, q="", sort_by="total", order="desc", scope="all", limit=100):
    gid = selected_group_id()
    if not gid:
        rows, selected_bucket, latest_bucket, actual_limit = _BASE["get_top_vm_rows"](
            period, q=q, sort_by=sort_by, order=order, scope=scope, limit=limit,
        )
        allowed = get_visible_node_names()
        return [row for row in rows if str(row[0]) in allowed], selected_bucket, latest_bucket, actual_limit
    m = _m()
    requested_sort = m.clean_top_sort(sort_by)
    requested_order = m.clean_sort_order(order)
    requested_limit = max(10, min(1000, m.safe_int(limit, 100)))
    ram_sort = requested_sort in m.V48103_RAM_SORT_KEYS
    disk_sort = requested_sort in m.V48133_DISK_SORT_KEYS
    base_sort = "total" if ram_sort or disk_sort else requested_sort
    fetch_limit = 1000 if ram_sort or disk_sort else requested_limit
    rows, selected_bucket, latest_bucket, _ = _group_top_raw_rows(period, q, base_sort, requested_order, scope, fetch_limit, gid)
    rows = m._v48103_augment_rows_with_ram(rows, period, selected_bucket, (0, 1, 24, 25))
    if rows:
        conn = m.db()
        try:
            rows = [r for r in rows if m._v48126_is_visible(conn, r[0], r[1])]
        finally:
            conn.close()
    if ram_sort:
        rows = m._v48103_sort_ram_rows(rows, requested_sort, requested_order, extractor=lambda r:(r[25],r[24],r[32],r[33],r[34]), tie_extractor=lambda r:m.safe_float(r[7],0))
    totals = m._v48133_disk_totals_for_pairs([(r[0], r[1]) for r in rows])
    rows = [tuple(r) + totals.get((str(r[0]), str(r[1])), (0,0,0)) for r in rows]
    if disk_sort:
        def disk_metric(row):
            allocated, assigned, count = (max(0.0,m.safe_float(row[i],0)) for i in (35,36,37))
            if requested_sort == "diskallocated": return allocated
            if requested_sort == "diskassigned": return assigned
            if requested_sort == "diskallocpct": return allocated/assigned if assigned > 0 else -1.0
            return count
        def key(row):
            present = any(m.safe_int(row[i],0)>0 for i in (35,36,37)); value=disk_metric(row); tie=m.safe_float(row[7],0)
            return ((0 if present else 1), value if requested_order=="asc" else -value, tie if requested_order=="asc" else -tie)
        rows.sort(key=key)
    allowed = get_visible_node_names(gid)
    return [row for row in rows if str(row[0]) in allowed][:requested_limit], selected_bucket, latest_bucket, requested_limit


def node_page():
    m = _m()
    node = str(m.request.view_args.get("node") or "")
    if not monitoring_node_visible(node):
        return m.Response("Node not found\n", status=404, mimetype="text/plain")
    return _BASE["node_page_view"]()


def vm_page():
    m = _m()
    node = str(m.request.view_args.get("node") or "")
    vm_uuid = str(m.request.view_args.get("vm_uuid") or "")
    if not monitoring_vm_visible(node, vm_uuid):
        return m.Response("VM not found\n", status=404, mimetype="text/plain")
    return _BASE["vm_page_view"]()


def _inject_group_select(response, marker: str, selected: int = 0, css_class: str = ""):
    text, original = _response_html(response)
    select = _group_select(selected)
    if css_class:
        select = select.replace("<select ", f'<select class="{css_class}" ', 1)
    text = _insert_once(text, marker, select, before=True)
    return _replace_response_html(original or response, text)


def index():
    response = _BASE["index_view"]()
    return _inject_group_select(response, '<button type="submit">Search</button>', selected_group_id())


def top_page():
    response = _BASE["top_view"]()
    return _inject_group_select(response, '<select name="limit" aria-label="Row limit">', selected_group_id())


def node_health_page():
    response = _BASE["node_health_view"]()
    return _inject_group_select(response, '<button type="submit">Search</button>', selected_group_id())

# ---------------------------------------------------------------------------
# Storage I/O group filter
# ---------------------------------------------------------------------------

def _storage_io_params(**updates):
    values = _BASE["storage_params"](**updates)
    values["group"] = _clean_group_id(_m().request.args.get("group"))
    values.update(updates)
    return values


def _v48140_disk_search_clause(values, summary_alias="s"):
    clauses, params = _BASE["storage_disk_clause"](values, summary_alias)
    gid = _clean_group_id(values.get("group"))
    group_sql = (
        f"EXISTS (SELECT 1 FROM node_group_memberships ngm JOIN node_groups ng ON ng.id=ngm.group_id "
        f"WHERE ngm.node={summary_alias}.node AND ng.is_active=1"
    )
    if gid:
        group_sql += " AND ngm.group_id=?"
        params.append(gid)
    clauses.append(group_sql + ")")
    return clauses, params


def _v48137_storage_target(conn, values):
    gid = _clean_group_id(values.get("group"))
    m = _m(); m.ensure_storage_snapshot_schema(conn)
    requested_at = m._request_target_ts(); node = str(values.get("node") or "").strip()
    visible = "EXISTS (SELECT 1 FROM node_group_memberships gm JOIN node_groups g ON g.id=gm.group_id WHERE gm.node=node_push_snapshots.node AND g.is_active=1"
    params = []
    if gid:
        visible += " AND gm.group_id=?"
        params.append(gid)
    where = ["storage_payload IS NOT NULL", visible + ")"]
    if node: where.append("node=?"); params.append(node)
    where_sql = " AND ".join(where)
    latest = m.safe_int((conn.execute(f"SELECT MAX(bucket) FROM node_push_snapshots WHERE {where_sql}", params).fetchone() or [0])[0],0)
    if latest <= 0:
        return {"mode":"history" if requested_at is not None or values.get("period")!="5m" else "live","latest":0,"target":0,"requested_at":requested_at}
    target = m.bucket_for(requested_at) if requested_at is not None else latest-max(0,m.period_seconds(m.clean_period(values.get("period") or "5m"))-m.CACHE_BUCKET_SECONDS)
    selected = m.safe_int((conn.execute(f"SELECT MAX(bucket) FROM node_push_snapshots WHERE {where_sql} AND bucket<=?", params+[target]).fetchone() or [0])[0],0)
    if selected <= 0:
        selected = m.safe_int((conn.execute(f"SELECT MIN(bucket) FROM node_push_snapshots WHERE {where_sql}",params).fetchone() or [0])[0],0)
    live = requested_at is None and m.clean_period(values.get("period") or "5m") == "5m"
    return {"mode":"live" if live else "history","latest":latest,"target":selected,"requested_at":requested_at}


def _v48137_snapshot_payload_rows(conn, values, target_bucket):
    gid = _clean_group_id(values.get("group"))
    if target_bucket <= 0: return []
    node = str(values.get("node") or "").strip()
    visible = "EXISTS (SELECT 1 FROM node_group_memberships gm JOIN node_groups g ON g.id=gm.group_id WHERE gm.node=node_push_snapshots.node AND g.is_active=1"
    params = [target_bucket]
    if gid:
        visible += " AND gm.group_id=?"
        params.append(gid)
    where = ["storage_payload IS NOT NULL", "bucket<=?", visible + ")"]
    if node: where.append("node=?"); params.append(node)
    where_sql = " AND ".join(where)
    return conn.execute(f"""WITH picked AS (SELECT node,MAX(bucket) bucket FROM node_push_snapshots WHERE {where_sql} GROUP BY node)
      SELECT s.node,s.bucket,s.push_time,s.storage_payload FROM node_push_snapshots s JOIN picked p ON p.node=s.node AND p.bucket=s.bucket ORDER BY s.node COLLATE NOCASE""",params).fetchall()


def _v48137_storage_filter_options(conn, values):
    gid = _clean_group_id(values.get("group"))
    group_filter = " AND gm.group_id=?" if gid else ""
    group_params = [gid] if gid else []
    nodes = [str(r[0]) for r in conn.execute("""
      SELECT x.node FROM (SELECT node FROM vm_disk_summary_current UNION SELECT node FROM node_storage_mount_summary_current) x
      JOIN node_group_memberships gm ON gm.node=x.node JOIN node_groups g ON g.id=gm.group_id LEFT JOIN node_inventory ni ON ni.node=x.node
      WHERE g.is_active=1""" + group_filter + """ AND (ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))
      GROUP BY x.node ORDER BY x.node COLLATE NOCASE""",group_params).fetchall()]
    node_filter = str(values.get("node") or "").strip()
    params = list(group_params); node_sql = ""
    if node_filter: node_sql=" AND q.node=?"; params.append(node_filter)
    mounts = [str(r[0]) for r in conn.execute(f"""
      SELECT q.mount FROM (
        SELECT d.node,d.mount FROM vm_disk_current d JOIN vm_inventory vi ON vi.node=d.node AND vi.vm_uuid=d.vm_uuid
         WHERE d.role='customer' AND d.mount!='' AND COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL
        UNION SELECT s.node,s.mount FROM node_storage_mount_summary_current s WHERE s.mount!=''
      ) q JOIN node_group_memberships gm ON gm.node=q.node JOIN node_groups g ON g.id=gm.group_id
      WHERE g.is_active=1 {group_filter} {node_sql}
      GROUP BY q.mount ORDER BY q.mount COLLATE NOCASE""",params).fetchall()]
    esc = _m().escape
    return ('<option value="">All nodes</option>'+''.join(f'<option value="{esc(n,quote=True)}"{" selected" if n==node_filter else ""}>{esc(n)}</option>' for n in nodes),
            '<option value="">All storage</option>'+''.join(f'<option value="{esc(x,quote=True)}"{" selected" if x==values.get("mount") else ""}>{esc(x)}</option>' for x in mounts))


def _v48140_node_group_cards_fast(conn, values, start_ts):
    gid = _clean_group_id(values.get("group"))
    m = _m()
    m._v48140_reconcile_summaries_if_needed(conn)
    sort_map={"node":"g.node COLLATE NOCASE","size":"g.size","used":"g.used","usepct":"CASE WHEN g.size>0 THEN g.used*1.0/g.size ELSE 0 END","read":"g.read_bps","write":"g.write_bps","readiops":"g.read_iops","writeiops":"g.write_iops","util":"g.util_percent","seen":"g.last_seen"}
    if values.get("sort") not in sort_map: values["sort"]="writeiops"
    visible = "EXISTS (SELECT 1 FROM node_group_memberships gm JOIN node_groups ng ON ng.id=gm.group_id WHERE gm.node=s.node AND ng.is_active=1"
    params=[start_ts]
    if gid:
        visible += " AND gm.group_id=?"
        params.append(gid)
    where=["s.last_seen>=?","(ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))",visible+")"]
    if values.get("node"): where.append("s.node=?"); params.append(values["node"])
    if values.get("q"):
        p=m.like_pattern(values["q"]); where.append("(s.node LIKE ? OR s.mount LIKE ? OR s.device LIKE ? OR s.block LIKE ? OR s.raid_level LIKE ? OR s.fstype LIKE ? OR COALESCE(b.primary_ipv4,'') LIKE ?)"); params.extend([p]*7)
    where_sql=" AND ".join(where)
    cte=f"""WITH vc AS (
      SELECT d.node,COUNT(*) vm_count,COALESCE(SUM(d.disk_count),0) disk_count FROM vm_disk_summary_current d
      JOIN vm_inventory vi ON vi.node=d.node AND vi.vm_uuid=d.vm_uuid LEFT JOIN node_inventory ni0 ON ni0.node=d.node
      WHERE COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL AND (ni0.node IS NULL OR (COALESCE(ni0.status,'active')!='hidden' AND ni0.deleted_at IS NULL)) GROUP BY d.node),
    g AS (SELECT s.node,COALESCE(MAX(b.primary_ipv4),'') public_ipv4,COUNT(*) mount_count,COALESCE(SUM(s.size),0) size,COALESCE(SUM(s.used),0) used,
      COALESCE(SUM(s.read_bps),0) read_bps,COALESCE(SUM(s.write_bps),0) write_bps,COALESCE(SUM(s.read_iops),0) read_iops,COALESCE(SUM(s.write_iops),0) write_iops,
      COALESCE(MAX(s.util_percent),0) util_percent,MAX(s.last_seen) last_seen,COALESCE(MAX(vc.disk_count),0) disk_count,COALESCE(MAX(vc.vm_count),0) vm_count
      FROM node_storage_mount_summary_current s LEFT JOIN node_inventory ni ON ni.node=s.node LEFT JOIN node_bridge_addresses_latest b ON b.node=s.node AND b.bridge=? LEFT JOIN vc ON vc.node=s.node
      WHERE {where_sql} GROUP BY s.node)"""
    total=m.safe_int(conn.execute(cte+"SELECT COUNT(*) FROM g",[m.PUBLIC_BRIDGE]+params).fetchone()[0],0)
    pages=max(1,int(math.ceil(total/float(values["limit"])))); values["page"]=min(values["page"],pages); offset=(values["page"]-1)*values["limit"]; direction="ASC" if values.get("order")=="asc" else "DESC"
    groups=conn.execute(cte+f"SELECT node,public_ipv4,mount_count,size,used,read_bps,write_bps,read_iops,write_iops,util_percent,last_seen,disk_count,vm_count FROM g ORDER BY {sort_map[values['sort']]} {direction},node COLLATE NOCASE LIMIT ? OFFSET ?",[m.PUBLIC_BRIDGE]+params+[values["limit"],offset]).fetchall()
    names=[str(r[0]) for r in groups]; mounts={n:[] for n in names}
    if names:
        ph=",".join("?" for _ in names)
        for row in conn.execute(f"""SELECT s.node,COALESCE(b.primary_ipv4,''),s.mount,s.device,s.block,s.raid_level,s.fstype,s.size,s.used,s.avail,s.use_percent,s.read_bps,s.write_bps,s.read_iops,s.write_iops,s.util_percent,s.last_seen,s.disk_count,s.vm_count
          FROM node_storage_mount_summary_current s LEFT JOIN node_inventory ni ON ni.node=s.node LEFT JOIN node_bridge_addresses_latest b ON b.node=s.node AND b.bridge=?
          WHERE (ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL)) AND s.node IN ({ph}) ORDER BY s.node COLLATE NOCASE,CASE s.mount WHEN '/' THEN 0 WHEN '[SWAP]' THEN 1 WHEN '/boot' THEN 2 WHEN '/boot/efi' THEN 3 WHEN '/home' THEN 4 ELSE 10 END,s.mount COLLATE NOCASE""",[m.PUBLIC_BRIDGE]+names).fetchall(): mounts.setdefault(str(row[0]),[]).append(row)
    cards=[]
    for node,ip,mount_count,size,used,rb,wb,ri,wi,util,seen,disk_count,vm_count in groups:
        node_href=m.url_for("node_page",node=node,period=values["period"],**({"at":values.get("at")} if values.get("at") else {})); pct=used*100.0/size if m.safe_int(size,0)>0 else 0.0; level=m._v48139_cap_level(pct); mount_rows="".join(m._v48139_node_mount_row(values,row) for row in mounts.get(str(node),[]))
        cards.append(f'''<article class="storage-node-card storage-entity-card-v48139"><div class="storage-entity-head-v48139"><div class="storage-entity-id-v48139"><span class="entity-kicker">Storage Node</span><div class="entity-main"><a href="{m.escape(node_href,quote=True)}">{m.escape(node)}</a></div><div class="entity-context">{f'<span>{m.escape(ip)}</span>' if ip else ''}<span>{m.safe_int(mount_count,0)} filesystems</span><span>· {m.safe_int(vm_count,0)} VMs</span><span>· {m.safe_int(disk_count,0)} disks</span><span>· sample {m.fmt_push(seen)}</span></div></div><div class="storage-entity-actions-v48139"><a class="btn" href="{m.escape(node_href,quote=True)}">View node</a></div></div><div class="storage-overview-v48139"><div class="storage-section-box-v48139"><span class="storage-section-label-v48139">Overall</span><div class="storage-overall-value-v48139"><b>{m._disk_io_bytes(used)} / {m._disk_io_bytes(size)}</b><span>{pct:.1f}% used / size</span></div><div class="storage-cap-track-v48139 disk-cap-meter {level}"><i style="width:{min(100.0,max(0.0,pct)):.1f}%"></i></div></div><div class="storage-section-box-v48139"><span class="storage-section-label-v48139">Performance</span><div class="storage-perf-grid-v48139"><div><span>READ</span><b>{m._disk_io_rate(rb)}</b></div><div><span>WRITE</span><b>{m._disk_io_rate(wb)}</b></div><div><span>IOPS / HOT UTIL</span><b>R {m._disk_io_iops(ri)} / W {m._disk_io_iops(wi)} · {m.safe_float(util,0):.1f}%</b></div></div></div></div><div class="storage-children-v48139"><div class="storage-children-title-v48139"><h4>Filesystems</h4><span>{len(mounts.get(str(node),[]))} real roots</span></div>{mount_rows}</div></article>''')
    if not cards: cards=['<div class="storage-card-empty-v48139">No real node storage sample at this snapshot.</div>']
    sort_bar=m._v48137_sort_bar(values,[("W IOPS","writeiops"),("WRITE","write"),("R IOPS","readiops"),("READ","read"),("UTIL","util"),("USED","used"),("SIZE","size"),("%","usepct"),("NODE","node")])
    return f'''{m.V48139_UI_CSS}<div class="card storage-table-card"><div class="table-title-row"><div><h3>Storage Node</h3><div class="table-hint">One node card per node. SQL pagination loads only filesystems for the visible page.</div></div>{sort_bar}</div><div class="storage-card-list-v48139">{"".join(cards)}</div>{m._storage_pager(values,total)}</div>'''


def storage_io_page():
    response = _BASE["storage_view"]()
    return _inject_group_select(response, '<select name="node" aria-label="Node filter">', selected_group_id())


# ---------------------------------------------------------------------------
# Consumption group filtering and aggregate view
# ---------------------------------------------------------------------------

def _v5058c_common_args(tab, period, q, selected_node, coverage, limit, sort_by, order):
    result = _BASE["consumption_common_args"](tab, period, q, selected_node, coverage, limit, sort_by, order)
    gid = selected_group_id()
    if gid: result["group"] = gid
    return result


def _v5058c_visible_nodes():
    gid=selected_group_id()
    conn=_m().db()
    try:
        group_sql=" AND gm.group_id=?" if gid else ""; params=[gid] if gid else []
        return conn.execute("""SELECT ni.node,COALESCE(MAX(CASE WHEN LOWER(COALESCE(ba.role,''))='public' THEN ba.primary_ipv4 END),'') public_ipv4
          FROM node_inventory ni JOIN node_group_memberships gm ON gm.node=ni.node JOIN node_groups g ON g.id=gm.group_id
          LEFT JOIN node_bridge_addresses_latest ba ON ba.node=ni.node
          WHERE g.is_active=1"""+group_sql+""" AND COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL
          GROUP BY ni.node ORDER BY LOWER(ni.node)""",params).fetchall()
    finally: conn.close()


def _consumption_group_where(alias: str):
    gid=selected_group_id()
    sql=(f" AND EXISTS (SELECT 1 FROM node_group_memberships ngm JOIN node_groups ng ON ng.id=ngm.group_id "
         f"WHERE ngm.node={alias}.node AND ng.is_active=1")
    params=[]
    if gid:
        sql+=" AND ngm.group_id=?"; params.append(gid)
    return sql+")",params


def _v5058c_vm_rows(start,end,selected_node,q,coverage,sort_by,order,page_no,limit):
    m=_m(); ctes,params=m._v5058c_vm_ctes(start,end,selected_node); search_sql,search_params=m._v5058c_search_clause("vm",q); group_sql,group_params=_consumption_group_where("vm_rows")
    where_sql=" WHERE 1=1"+search_sql+m._v5058c_coverage_clause(coverage)+group_sql; order_column=m.V5058C_VM_SORTS[sort_by]; tie="ASC" if sort_by in {"uuid","node"} and order=="asc" else "DESC"; page_no=max(1,page_no)
    def fetch(offset):
        conn=m.db()
        try: return conn.execute(ctes+"""SELECT vm_uuid,node,node_ip,public_configured,private_configured,public_rx,public_tx,public_total,private_rx,private_tx,private_total,coverage_percent,latest_sample,COUNT(*) OVER() total_count FROM vm_rows"""+where_sql+" ORDER BY %s %s,vm_uuid %s LIMIT ? OFFSET ?"%(order_column,order.upper(),tie),params+search_params+group_params+[limit,offset]).fetchall()
        finally: conn.close()
    raw=fetch((page_no-1)*limit)
    if not raw and page_no>1: page_no=1; raw=fetch(0)
    total=m.safe_int(raw[0][-1] if raw else 0,0); max_page=max(1,int(math.ceil(total/float(max(1,limit))))); return [tuple(r[:-1]) for r in raw],total,page_no,max_page


def _v5058c_node_rows(start,end,q,coverage,sort_by,order,page_no,limit):
    m=_m(); ctes,params=m._v5058c_node_ctes(start,end); search_sql,search_params=m._v5058c_search_clause("node",q); group_sql,group_params=_consumption_group_where("node_rows")
    where_sql=" WHERE 1=1"+search_sql+m._v5058c_coverage_clause(coverage)+group_sql; col=m.V5058C_NODE_SORTS[sort_by]; tie="ASC" if sort_by=="node" and order=="asc" else "DESC"; page_no=max(1,page_no)
    def fetch(offset):
        conn=m.db()
        try:return conn.execute(ctes+"""SELECT node,node_ip,public_configured,private_configured,physical_public_rx,physical_public_tx,physical_public_total,physical_private_rx,physical_private_tx,physical_private_total,coverage_percent,latest_sample,COUNT(*) OVER() total_count FROM node_rows"""+where_sql+" ORDER BY %s %s,node %s LIMIT ? OFFSET ?"%(col,order.upper(),tie),params+search_params+group_params+[limit,offset]).fetchall()
        finally:conn.close()
    raw=fetch((page_no-1)*limit)
    if not raw and page_no>1: page_no=1; raw=fetch(0)
    total=m.safe_int(raw[0][-1] if raw else 0,0); max_page=max(1,int(math.ceil(total/float(max(1,limit))))); return [tuple(r[:-1]) for r in raw],total,page_no,max_page


def _v5058c_vm_totals(start,end,selected_node=""):
    m=_m(); ctes,params=m._v5058c_vm_ctes(start,end,selected_node); group_sql,group_params=_consumption_group_where("vm_rows"); conn=m.db()
    try:
        row=conn.execute(ctes+"""SELECT COALESCE(SUM(public_rx),0),COALESCE(SUM(public_tx),0),COALESCE(SUM(private_rx),0),COALESCE(SUM(private_tx),0) FROM vm_rows WHERE 1=1"""+group_sql,params+group_params).fetchone()
        return {"vm_public_rx":m.safe_int(row[0] if row else 0,0),"vm_public_tx":m.safe_int(row[1] if row else 0,0),"vm_private_rx":m.safe_int(row[2] if row else 0,0),"vm_private_tx":m.safe_int(row[3] if row else 0,0)}
    finally:conn.close()


def _v5058c_node_totals(start,end,selected_node=""):
    m=_m(); ctes,params=m._v5058c_node_ctes(start,end); group_sql,group_params=_consumption_group_where("node_rows"); conn=m.db()
    try:
        row=conn.execute(ctes+"""SELECT COALESCE(SUM(physical_public_rx),0),COALESCE(SUM(physical_public_tx),0),COALESCE(SUM(physical_private_rx),0),COALESCE(SUM(physical_private_tx),0) FROM node_rows WHERE 1=1"""+group_sql,params+group_params).fetchone()
        return {"physical_public_rx":m.safe_int(row[0] if row else 0,0),"physical_public_tx":m.safe_int(row[1] if row else 0,0),"physical_private_rx":m.safe_int(row[2] if row else 0,0),"physical_private_tx":m.safe_int(row[3] if row else 0,0)}
    finally:conn.close()


def _consumption_group_page():
    m=_m(); period=m._v5058c_period(m.request.args.get("period")); _label,seconds=m.V5058C_PERIODS[period]; end=m.now_ts(); start=end-seconds; selected=selected_group_id()
    q=str(m.request.args.get('q') or '').strip(); sort=str(m.request.args.get('sort') or 'total').lower(); order=str(m.request.args.get('order') or 'desc').lower()
    allowed={'group','nodes','vms','rx','tx','total','cpu','ram','disk'}
    if sort not in allowed:sort='total'
    if order not in {'asc','desc'}:order='desc'
    vm_ctes,vm_params=m._v5058c_vm_ctes(start,end,""); node_ctes,node_params=m._v5058c_node_ctes(start,end)
    conn=m.db()
    try:
        vm={int(r[0]):int(r[1] or 0) for r in conn.execute(vm_ctes+"""SELECT gm.group_id,COUNT(*) FROM vm_rows JOIN node_group_memberships gm ON gm.node=vm_rows.node JOIN node_groups g ON g.id=gm.group_id WHERE g.is_active=1 GROUP BY gm.group_id""",vm_params).fetchall()}
        network={int(r[0]):tuple(int(x or 0) for x in r[1:]) for r in conn.execute(node_ctes+"""SELECT gm.group_id,
          COALESCE(SUM(physical_public_rx+physical_private_rx),0),COALESCE(SUM(physical_public_tx+physical_private_tx),0)
          FROM node_rows JOIN node_group_memberships gm ON gm.node=node_rows.node JOIN node_groups g ON g.id=gm.group_id
          WHERE g.is_active=1 GROUP BY gm.group_id""",node_params).fetchall()}
        metrics={int(r[0]):r[1:] for r in conn.execute("""SELECT gm.group_id,COUNT(*),AVG(ncf.cpu_percent),SUM(ncf.mem_used),SUM(ncf.mem_total),
          SUM(ncf.disk_read_bps),SUM(ncf.disk_write_bps) FROM node_group_memberships gm JOIN node_groups g ON g.id=gm.group_id
          JOIN node_inventory ni ON ni.node=gm.node LEFT JOIN node_current_fast ncf ON ncf.node=gm.node
          WHERE g.is_active=1 AND COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL GROUP BY gm.group_id""").fetchall()}
        groups=conn.execute("""SELECT id,name,country_code FROM node_groups WHERE is_active=1 ORDER BY name COLLATE NOCASE""").fetchall()
        matched=set()
        if q:
            p=m.like_pattern(q)
            matched={int(r[0]) for r in conn.execute("""SELECT DISTINCT gm.group_id FROM node_group_memberships gm
              LEFT JOIN node_bridge_addresses_latest b ON b.node=gm.node WHERE gm.node LIKE ? OR COALESCE(b.primary_ipv4,'') LIKE ? OR COALESCE(b.ipv4_json,'[]') LIKE ?""",(p,p,p)).fetchall()}
    finally:conn.close()
    data=[]
    for gid,name,country in groups:
        if selected and int(gid)!=selected:continue
        if q and q.lower() not in str(name).lower() and int(gid) not in matched:continue
        rx,tx=network.get(int(gid),(0,0)); count,cpu,used,total_mem,read_bps,write_bps=metrics.get(int(gid),(0,None,0,0,0,0))
        data.append({'id':int(gid),'name':str(name),'country':str(country or ''),'nodes':int(count or 0),'vms':int(vm.get(int(gid),0)),'rx':rx,'tx':tx,'total':rx+tx,'cpu':cpu,'ram':(float(used or 0)*100.0/float(total_mem) if int(total_mem or 0)>0 else None),'used':int(used or 0),'mem_total':int(total_mem or 0),'read':float(read_bps or 0),'write':float(write_bps or 0),'disk':float(read_bps or 0)+float(write_bps or 0)})
    key=(lambda r:r['name'].lower()) if sort=='group' else (lambda r:r[sort])
    present=[r for r in data if key(r) is not None]; missing=[r for r in data if key(r) is None]; present.sort(key=lambda r:r['name'].lower()); present.sort(key=key,reverse=order=='desc'); data=present+missing
    rows=[]
    for row in data:
        href=m.url_for('bandwidth_consumption_page',tab='node',period=period,group=row['id'])
        cpu='N/A' if row['cpu'] is None else m.metric_pill(f"{float(row['cpu']):.1f}%",m.metric_level(float(row['cpu']),70,85))
        ram='N/A' if row['ram'] is None else m.metric_pill(f"{float(row['ram']):.1f}%",m.metric_level(float(row['ram']),80,90),'RAM used')
        rows.append(f'''<tr><td><a href="{m.escape(href,quote=True)}"><b>{flag_html(row['country'])}{m.escape(row['name'])}</b></a></td><td class="num">{row['nodes']:,}</td><td class="num">{row['vms']:,}</td><td class="num">{m.human(row['rx'])}</td><td class="num">{m.human(row['tx'])}</td><td class="num"><b>{m.human(row['total'])}</b></td><td class="num">{cpu}</td><td class="num">{ram}</td><td class="num">R {m._disk_io_rate(row['read'])}<small class="row-sub">W {m._disk_io_rate(row['write'])}</small></td></tr>''')
    body="".join(rows) or '<tr><td colspan="9" class="empty">No Node Group consumption in this range</td></tr>'
    common={'tab':'group','q':q or None,'group':selected or None,'sort':sort,'order':order}
    periods="".join(f'<a class="{"active" if k==period else ""}" href="{m.url_for("bandwidth_consumption_page",period=k,**common)}">{m.escape(v[0])}</a>' for k,v in m.V5058C_PERIODS.items())
    tabs=f'''<div class="v5058c-tabs"><a href="{m.url_for('bandwidth_consumption_page',tab='vm',period=period)}">VM Consumption</a><a href="{m.url_for('bandwidth_consumption_page',tab='node',period=period)}">Node Consumption</a><a class="active" href="{m.url_for('bandwidth_consumption_page',tab='group',period=period)}">Node Group</a></div>'''
    def sort_link(label,key_name):
        next_order='desc' if sort==key_name and order=='asc' else 'asc'; args=dict(common);args.update({'period':period,'sort':key_name,'order':next_order});return '<a href="%s">%s</a>'%(m.escape(m.url_for('bandwidth_consumption_page',**args),quote=True),m.escape(label))
    headers=[sort_link('NODE GROUP','group'),sort_link('NODES','nodes'),sort_link('VMS','vms'),sort_link('RX','rx'),sort_link('TX','tx'),sort_link('TOTAL','total'),sort_link('CPU','cpu'),sort_link('RAM','ram'),sort_link('DISK','disk')]
    content=f'''<div class="card v5058c-shell"><div class="v5058c-head"><div><h2>Consumption</h2><p>Existing node-consumption formulas aggregated by active Node Group.</p></div><div class="v5058c-range"><div class="v5058c-range-block"><span>TIME RANGE</span><div class="v5058c-periods">{periods}</div></div></div></div>{tabs}<form class="v5058c-toolbar" method="get"><input type="hidden" name="tab" value="group"><input type="hidden" name="period" value="{period}"><input type="hidden" name="sort" value="{sort}"><input type="hidden" name="order" value="{order}"><input name="q" value="{m.escape(q,quote=True)}" placeholder="Search group, node or IP">{_group_select(selected)}<button type="submit">Apply</button><a class="clear" href="{m.url_for('bandwidth_consumption_page',tab='group',period=period)}">Reset</a></form><div class="v5058c-table-wrap table-wrap"><table class="v5058c-table v5058c-node-table"><thead><tr>{''.join('<th>'+h+'</th>' for h in headers)}</tr></thead><tbody>{body}</tbody></table></div></div>'''
    # Reuse the exact baseline CSS extracted from app.py at install time. No
    # baseline Consumption query is executed in the additive group view.
    return m.page("Consumption", _CONSUMPTION_STYLE + content)


def bandwidth_consumption_page():
    if str(_m().request.args.get("tab") or "").strip().lower()=="group": return _consumption_group_page()
    response=_BASE["consumption_view"](); text,original=_response_html(response); selected=selected_group_id()
    text=_insert_once(text,'<select name="coverage">',_group_select(selected),before=True)
    if '>Node Group</a>' not in text:
        marker='</div>\n      <div class="v5058c-summary-grid">'
        link=f'<a href="{_m().url_for("bandwidth_consumption_page",tab="group",period=_m().request.args.get("period") or "24h")}">Node Group</a>'
        text=text.replace(marker,link+marker,1)
    return _replace_response_html(original or response,text)

# ---------------------------------------------------------------------------
# VM Abuse group filtering
# ---------------------------------------------------------------------------

def _v48128_filter_values():
    values = _BASE["abuse_filter_values"]()
    values["group"] = _clean_group_id(_m().request.args.get("group"))
    return values


def _v48128_filter_form(tab, values, nodes):
    html = _BASE["abuse_filter_form"](tab, values, nodes)
    return _insert_once(html, '<select name="node">', _group_select(_clean_group_id(values.get("group"))), before=True)


def _v48126_visible_nodes():
    gid=selected_group_id()
    m=_m(); conn=m.db()
    try:
        group_sql=" AND gm.group_id=?" if gid else ""; params=[m.now_ts()-7*86400]+([gid] if gid else [])
        return [str(r[0]) for r in conn.execute("""SELECT DISTINCT a.node FROM vm_abuse_state a JOIN node_group_memberships gm ON gm.node=a.node LEFT JOIN node_inventory ni ON ni.node=a.node
          JOIN node_groups g ON g.id=gm.group_id WHERE a.last_seen>=? AND g.is_active=1"""+group_sql+"""
          AND (ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))
          ORDER BY a.node COLLATE NOCASE""",params).fetchall()]
    finally:conn.close()


def _v48127_event_where(values):
    where,params=_BASE["abuse_event_where"](values)
    gid=_clean_group_id(values.get("group"))
    visible="EXISTS (SELECT 1 FROM node_group_memberships gm JOIN node_groups g ON g.id=gm.group_id WHERE gm.node=i.node AND g.is_active=1"
    if gid: visible+=" AND gm.group_id=?"; params.append(gid)
    where.append(visible+")")
    return where,params


def _v48139_current_rows(values):
    gid=_clean_group_id(values.get("group"))
    m=_m(); cfg=m.get_abuse_settings()
    group_where="EXISTS (SELECT 1 FROM node_group_memberships gm JOIN node_groups g ON g.id=gm.group_id WHERE gm.node=a.node AND g.is_active=1"
    group_params=[]
    if gid: group_where+=" AND gm.group_id=?"; group_params.append(gid)
    group_where+=")"
    where=["a.is_abuse=1","a.last_seen>=?","a.policy_revision=?","a.engine_version=?",m._v48126_visible_sql("ni","vi"),m._v48126_type_condition("a",values["type"]),"a.severity>=?",group_where]
    params=[m.now_ts()-m.FAST_CURRENT_STALE_SECONDS,cfg["revision"],m.ABUSE_ENGINE_VERSION,values["min_severity"]]+group_params
    if values["node"]:where.append("a.node=?");params.append(values["node"])
    if values["q"]:
        p=m.like_pattern(values["q"]);where.append("(a.node LIKE ? OR a.vm_uuid LIKE ? OR a.abuse_flags LIKE ?)");params.extend([p,p,p])
    sort=values.get("sort") or "severity"; order=values.get("order") or "desc"
    sort_map={"node":"a.node COLLATE NOCASE","uuid":"a.vm_uuid COLLATE NOCASE","type":"a.abuse_flags COLLATE NOCASE","severity":"a.severity","rx_mbps":"COALESCE(a.rx_mbps,0)","tx_mbps":"COALESCE(a.tx_mbps,0)","rx_peak":"COALESCE(a.rx_peak_pps,0)","tx_peak":"COALESCE(a.tx_peak_pps,0)","cpu":"COALESCE(a.cpu_full_percent,0)","cpucore":"COALESCE(a.cpu_core_percent,0)","ram":"COALESCE(a.ram_guest_used_percent,-1)","ramused":"CASE WHEN COALESCE(a.ram_guest_used_percent,-1)>=0 THEN MAX(0,COALESCE(a.ram_available_kib,0)-COALESCE(a.ram_usable_kib,0)) ELSE -1 END","ramrss":"COALESCE(a.ram_rss_kib,0)","ramassigned":"COALESCE(a.ram_current_kib,0)","diskallocated":"COALESCE(ds.allocated_bytes,0)","diskassigned":"COALESCE(ds.assigned_bytes,0)","diskallocpct":"COALESCE(ds.allocation_ratio,-1)","diskslots":"COALESCE(ds.disk_count,0)","diskr":"COALESCE(a.disk_read_bps,0)","diskw":"COALESCE(a.disk_write_bps,0)","readiops":"COALESCE(a.disk_read_iops,0)","writeiops":"COALESCE(a.disk_write_iops,0)","last_seen":"a.last_seen"}
    order_sql=f"a.abuse_since {'ASC' if order=='desc' else 'DESC'}" if sort=="duration" else f"{sort_map.get(sort,sort_map['severity'])} {'ASC' if order=='asc' else 'DESC'}"
    where_sql=" AND ".join(where);offset=(values["page"]-1)*values["limit"];conn=m.db()
    try:
        changed=m._v48140_reconcile_summaries_if_needed(conn)
        if changed:conn.commit()
        total=m.safe_int(conn.execute(f"SELECT COUNT(*) FROM vm_abuse_state a LEFT JOIN node_inventory ni ON ni.node=a.node LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid WHERE {where_sql}",params).fetchone()[0],0)
        rows=conn.execute(f"""SELECT a.node,a.vm_uuid,a.abuse_since,a.last_seen,a.abuse_flags,a.severity,a.rx_mbps,a.tx_mbps,a.rx_pps,a.tx_pps,a.rx_peak_pps,a.tx_peak_pps,a.seconds_over_rx_pps,a.seconds_over_tx_pps,
          COALESCE(a.network_rx_mbps_streak_seconds,0),COALESCE(a.network_tx_mbps_streak_seconds,0),a.cpu_full_percent,a.cpu_core_percent,a.vcpu_current,a.cpu_streak_seconds,a.ram_rss_percent,a.ram_guest_used_percent,a.ram_usable_percent,a.ram_streak_seconds,
          a.ram_current_kib,a.ram_rss_kib,a.ram_available_kib,a.ram_usable_kib,a.disk_read_bps,a.disk_write_bps,a.disk_read_iops,a.disk_write_iops,a.disk_streak_seconds,COALESCE(b.primary_ipv4,''),COALESCE(ds.allocated_bytes,0),COALESCE(ds.assigned_bytes,0),COALESCE(ds.disk_count,0)
          FROM vm_abuse_state a LEFT JOIN node_inventory ni ON ni.node=a.node LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid LEFT JOIN node_bridge_addresses_latest b ON b.node=a.node AND b.bridge=? LEFT JOIN vm_disk_summary_current ds ON ds.node=a.node AND ds.vm_uuid=a.vm_uuid
          WHERE {where_sql} ORDER BY {order_sql},a.node COLLATE NOCASE,a.vm_uuid COLLATE NOCASE LIMIT ? OFFSET ?""",[m.PUBLIC_BRIDGE]+params+[values["limit"],offset]).fetchall()
        counts={}
        for key in ("network","cpu","ram","disk"):
            counts[key]=m.safe_int(conn.execute(f"""SELECT COUNT(*) FROM vm_abuse_state a LEFT JOIN node_inventory ni ON ni.node=a.node LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
              WHERE a.is_abuse=1 AND a.last_seen>=? AND a.policy_revision=? AND a.engine_version=? AND {m._v48126_visible_sql('ni','vi')} AND {m._v48126_type_condition('a',key)} AND {group_where}""",
              [m.now_ts()-m.FAST_CURRENT_STALE_SECONDS,cfg["revision"],m.ABUSE_ENGINE_VERSION]+group_params).fetchone()[0],0)
        return rows,total,counts
    finally:conn.close()


# ---------------------------------------------------------------------------
# r6 Node Groups monitoring, flag decoration and bulk management
# ---------------------------------------------------------------------------

def _relative_update(ts: Any) -> str:
    value = int(ts or 0)
    if value <= 0:
        return 'Never'
    age=max(0,_ts()-value)
    if age < 10: return 'Just now'
    if age < 60: return f'{age}s ago'
    if age < 3600: return f'{age//60}m ago'
    if age < 86400: return f'{age//3600}h ago'
    return f'{age//86400}d ago'


def _status_rank(value: str) -> int:
    return {'offline':0,'critical':1,'warning':2,'healthy':3,'empty':4,'unknown':5}.get(str(value or '').lower(),5)


def _node_group_summary_data():
    m=_m(); cfg=m.get_abuse_settings(); stale=_ts()-m.FAST_CURRENT_STALE_SECONDS
    conn=m.db()
    try:
        group_rows=conn.execute("""
            SELECT g.id,g.name,g.description,g.country_code,g.is_system
              FROM node_groups g WHERE g.is_active=1
             ORDER BY g.is_system DESC,LOWER(g.name)
        """).fetchall()
        node_rows=conn.execute("""
            SELECT gm.group_id,ni.node,COALESCE(ncf.last_seen,ni.last_push,0),
                   COALESCE(ncf.load1,0),COALESCE(ncf.load5,0),COALESCE(ncf.load15,0),
                   COALESCE(ncf.cpu_percent,0),COALESCE(ncf.mem_used,0),COALESCE(ncf.mem_total,0),
                   COALESCE(ncf.disk_read_bps,0),COALESCE(ncf.disk_write_bps,0)
              FROM node_group_memberships gm
              JOIN node_inventory ni ON ni.node=gm.node
              LEFT JOIN node_current_fast ncf ON ncf.node=ni.node
             WHERE COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL
        """).fetchall()
        count_rows=conn.execute("""
            WITH visible_nodes AS (
                SELECT gm.group_id,ni.node
                  FROM node_group_memberships gm JOIN node_inventory ni ON ni.node=gm.node
                 WHERE COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL
            ), vm_counts AS (
                SELECT vn.group_id,COUNT(*) AS vm_count
                  FROM visible_nodes vn JOIN vm_inventory vi ON vi.node=vn.node
                 WHERE COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL
                 GROUP BY vn.group_id
            ), abuse_counts AS (
                SELECT vn.group_id,COUNT(DISTINCT a.node||':'||a.vm_uuid) AS abuse_count,
                       MAX(CASE WHEN UPPER(COALESCE(a.abuse_flags,'')) LIKE '%CRITICAL%' THEN 1 ELSE 0 END) AS critical
                  FROM visible_nodes vn
                  JOIN vm_abuse_state a ON a.node=vn.node
                  JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
                 WHERE a.is_abuse=1 AND a.last_seen>=? AND a.policy_revision=? AND a.engine_version=?
                   AND COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL
                 GROUP BY vn.group_id
            )
            SELECT g.id,COALESCE(v.vm_count,0),COALESCE(a.abuse_count,0),COALESCE(a.critical,0)
              FROM node_groups g LEFT JOIN vm_counts v ON v.group_id=g.id
              LEFT JOIN abuse_counts a ON a.group_id=g.id WHERE g.is_active=1
        """,(stale,cfg['revision'],m.ABUSE_ENGINE_VERSION)).fetchall()
    finally: conn.close()
    counts={int(r[0]):(int(r[1] or 0),int(r[2] or 0),bool(r[3])) for r in count_rows}
    by_group={}
    for row in node_rows: by_group.setdefault(int(row[0]),[]).append(row)
    result=[]
    for gid,name,desc,country,system in group_rows:
        nodes=by_group.get(int(gid),[]); last=max((int(r[2] or 0) for r in nodes),default=0)
        vm_count,abuse_count,critical=counts.get(int(gid),(0,0,False))
        states=[m.health_state(int(r[2] or 0)) if int(r[2] or 0)>0 else 'unknown' for r in nodes]
        if not nodes: status='empty'
        elif not last: status='unknown'
        elif all(state=='down' for state in states): status='offline'
        elif critical: status='critical'
        elif abuse_count or any(state in {'down','warning'} for state in states): status='warning'
        else: status='healthy'
        result.append({'id':int(gid),'name':str(name),'description':str(desc or ''),'country_code':str(country or ''),'system':bool(system),'node_count':len(nodes),'vm_count':vm_count,'abuse_count':abuse_count,'last_update':last,'status':status})
    return result


def _filtered_sorted_group_summaries():
    m = _m()
    rows = _node_group_summary_data()
    q = str(m.request.args.get("q") or "").strip().lower()
    status = str(m.request.args.get("status") or "").strip().lower()
    abuse = str(m.request.args.get("abuse") or "").strip().lower()
    online = str(m.request.args.get("online") or "").strip().lower()
    if q:
        conn = m.db()
        try:
            pattern = "%" + q.replace("%", "\\%").replace("_", "\\_") + "%"
            found = {
                int(row[0])
                for row in conn.execute(
                    """SELECT DISTINCT gm.group_id
                         FROM node_group_memberships gm
                         JOIN node_inventory ni ON ni.node=gm.node
                         JOIN node_groups g ON g.id=gm.group_id
                        WHERE g.is_active=1
                          AND COALESCE(ni.status,'active')!='hidden'
                          AND ni.deleted_at IS NULL
                          AND (LOWER(ni.node) LIKE ? OR EXISTS (
                              SELECT 1 FROM node_bridge_addresses_latest b
                               WHERE b.node=ni.node AND (
                                   LOWER(COALESCE(b.primary_ipv4,'')) LIKE ? OR
                                   LOWER(COALESCE(b.ipv4_json,'[]')) LIKE ?)))""",
                    (pattern, pattern, pattern),
                ).fetchall()
            }
        finally:
            conn.close()
        rows = [row for row in rows if row["id"] in found or q in row["name"].lower() or q in row["description"].lower()]
    if status:
        rows = [row for row in rows if row["status"] == status]
    if abuse == "yes":
        rows = [row for row in rows if row["abuse_count"] > 0]
    if abuse == "no":
        rows = [row for row in rows if row["abuse_count"] == 0]
    if online == "online":
        rows = [row for row in rows if row["status"] not in {"offline", "unknown", "empty"}]
    if online == "offline":
        rows = [row for row in rows if row["status"] == "offline"]

    sort = str(m.request.args.get("sort") or "status").strip().lower()
    order = str(m.request.args.get("order") or "asc").strip().lower()
    if sort not in {"name", "nodes", "vms", "abuse", "updated", "status"}:
        sort = "status"
    if order not in {"asc", "desc"}:
        order = "asc"
    descending = order == "desc"

    # Stable name-first pass keeps equal-value ties deterministic and keeps the
    # group-name tie breaker ascending for the default severity ordering.
    rows.sort(key=lambda row: row["name"].lower())
    if sort == "name":
        rows.sort(key=lambda row: row["name"].lower(), reverse=descending)
    elif sort == "updated":
        rows.sort(
            key=lambda row: (
                row["last_update"] <= 0,
                -int(row["last_update"] or 0) if descending else int(row["last_update"] or 0),
            )
        )
    else:
        value = {
            "nodes": lambda row: int(row["node_count"]),
            "vms": lambda row: int(row["vm_count"]),
            "abuse": lambda row: int(row["abuse_count"]),
            "status": lambda row: _status_rank(row["status"]),
        }[sort]
        rows.sort(key=value, reverse=descending)
    return rows

def _sort_link(label,key):
    m=_m(); args=m.request.args.to_dict(flat=True); current=str(args.get('sort') or 'status'); order=str(args.get('order') or 'asc'); args['sort']=key; args['order']='desc' if current==key and order=='asc' else 'asc'; return '<a class="sort-link" href="%s">%s</a>'%(m.escape(m.url_for('node_groups_page',**args),quote=True),m.escape(label))


def _group_summary_html(rows):
    m=_m(); parts=[]
    for row in rows:
        gid=row['id']; abuse_href=m.url_for('vm_abuse_page',group=gid); status=row['status']; updated=m.fmt_full(row['last_update']) if row['last_update'] else 'Never'
        parts.append(f'''<details class="node-group-monitor" data-group-id="{gid}"><summary><span class="ng-chevron" aria-hidden="true">›</span><span class="ng-name">{flag_html(row['country_code'])}<b>{m.escape(row['name'])}</b></span><span class="ng-num" data-field="nodes">{row['node_count']:,} Nodes</span><span class="ng-num" data-field="vms">{row['vm_count']:,} VMs</span><a class="ng-abuse" href="{m.escape(abuse_href,quote=True)}" onclick="event.stopPropagation()">{row['abuse_count']:,} Abuse</a><span class="ng-update" title="{m.escape(updated,quote=True)}">Updated {_relative_update(row['last_update'])}</span><span class="vm-state {m.escape(status)}">{m.escape(status.upper())}</span></summary><div class="node-group-detail" data-loaded="0"><div class="empty">Expand to load current node data.</div></div></details>''')
    return ''.join(parts) or '<div class="card empty">No active Node Groups match the selected filters.</div>'


def node_groups_page():
    m=_m(); deny=m.require_dashboard()
    if deny:return deny
    rows=_filtered_sorted_group_summaries(); role=current_role()
    toolbar=f'''<form class="search node-group-filters" method="get"><input type="hidden" name="sort" value="{m.escape(m.request.args.get('sort') or 'status',quote=True)}"><input type="hidden" name="order" value="{m.escape(m.request.args.get('order') or 'asc',quote=True)}"><input name="q" value="{m.escape(m.request.args.get('q') or '',quote=True)}" placeholder="Search group, node or IP"><select name="status"><option value="">All statuses</option>{''.join('<option value="%s"%s>%s</option>'%(s,' selected' if m.request.args.get('status')==s else '',s.title()) for s in ('offline','critical','warning','healthy','empty','unknown'))}</select><select name="abuse"><option value="">All abuse</option><option value="yes"{' selected' if m.request.args.get('abuse')=='yes' else ''}>Has current abuse</option><option value="no"{' selected' if m.request.args.get('abuse')=='no' else ''}>No current abuse</option></select><select name="online"><option value="">All connectivity</option><option value="online"{' selected' if m.request.args.get('online')=='online' else ''}>Online</option><option value="offline"{' selected' if m.request.args.get('online')=='offline' else ''}>Offline</option></select><button type="submit">Apply</button><a class="btn" href="{m.url_for('node_groups_page')}">Reset</a></form>'''
    header=f'''<div class="card"><div class="section-head"><div><span class="eyebrow">MONITORING</span><h2>Node Groups</h2><p>Current group health from existing node cache, inventory and Current Abuse state.</p></div>{'<a class="btn" href="'+m.url_for('admin_page',section='groups')+'">Manage groups</a>' if role in {'admin','super_admin'} else ''}</div>{toolbar}<div class="table-hint">Sort: {_sort_link('Group','name')} · {_sort_link('Nodes','nodes')} · {_sort_link('VMs','vms')} · {_sort_link('Abuse','abuse')} · {_sort_link('Last Update','updated')} · {_sort_link('Status','status')}</div></div>'''
    script = r'''<script>(function(){
const key='virtinfra-node-groups-r7';
function state(){try{return JSON.parse(sessionStorage.getItem(key)||'{}')}catch(e){return{}}}
function save(value){try{sessionStorage.setItem(key,JSON.stringify(value))}catch(e){}}
async function load(detail,force){
  const id=detail.dataset.groupId,box=detail.querySelector('.node-group-detail'),saved=state();
  const local=saved[id]||{},sort=local.sort||'status',order=local.order||'asc';
  if(!detail.open&&!force)return;
  const url=new URL('/node-groups/'+id+'/nodes',location.origin);
  url.searchParams.set('sort',sort);url.searchParams.set('order',order);
  url.searchParams.set('q',new URLSearchParams(location.search).get('q')||'');
  try{
    const response=await fetch(url,{headers:{'X-Requested-With':'fetch'}});
    if(!response.ok)return;
    box.innerHTML=await response.text();box.dataset.loaded='1';bind(box,id);
  }catch(e){}
}
function bind(root,id){root.querySelectorAll('[data-ng-sort]').forEach(link=>link.onclick=function(event){
  event.preventDefault();event.stopPropagation();const saved=state(),local=saved[id]||{};
  local.order=local.sort===this.dataset.ngSort&&local.order==='asc'?'desc':'asc';
  local.sort=this.dataset.ngSort;saved[id]=local;save(saved);
  const detail=document.querySelector('[data-group-id="'+id+'"]');if(detail)load(detail,true);
});}
function init(){
  const saved=state(),pending=[];
  document.querySelectorAll('.node-group-monitor').forEach(detail=>{
    const id=detail.dataset.groupId,local=saved[id]||{};
    if(local.open){detail.open=true;pending.push(load(detail,true));}
    detail.addEventListener('toggle',()=>{const current=state(),item=current[id]||{};item.open=detail.open;current[id]=item;save(current);if(detail.open)load(detail,true);});
  });
  return Promise.all(pending);
}
async function refresh(){
  const x=window.scrollX,y=window.scrollY;
  try{
    const response=await fetch('/node-groups/summary'+location.search,{headers:{'X-Requested-With':'fetch'}});
    if(!response.ok)return;
    document.getElementById('node-group-list').innerHTML=await response.text();
    await init();requestAnimationFrame(()=>window.scrollTo(x,y));
  }catch(e){}
}
document.addEventListener('DOMContentLoaded',()=>{init();
  if(window.__virtinfraNodeGroupsRefreshTimer)clearInterval(window.__virtinfraNodeGroupsRefreshTimer);
  window.__virtinfraNodeGroupsRefreshTimer=setInterval(refresh,30000);
});
window.addEventListener('pagehide',()=>{if(window.__virtinfraNodeGroupsRefreshTimer){clearInterval(window.__virtinfraNodeGroupsRefreshTimer);window.__virtinfraNodeGroupsRefreshTimer=null;}},{once:true});
})();</script>'''
    css='''<style>.node-group-list{display:grid;gap:8px}.node-group-monitor{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}.node-group-monitor>summary{display:grid;grid-template-columns:18px minmax(180px,1fr) repeat(3,minmax(86px,auto)) minmax(110px,auto) minmax(82px,auto);gap:10px;align-items:center;padding:11px 13px;cursor:pointer;list-style:none}.node-group-monitor>summary::-webkit-details-marker{display:none}.node-group-monitor[open] .ng-chevron{transform:rotate(90deg)}.ng-chevron{transition:transform .15s}.ng-name{display:flex;align-items:center;min-width:0}.ng-abuse{font-weight:800}.node-group-detail{border-top:1px solid var(--line);padding:10px}.node-group-detail table{min-width:1180px}.node-group-filters{margin:12px 0}.node-group-filters input{min-width:145px}@media(max-width:900px){.node-group-monitor>summary{grid-template-columns:18px 1fr auto}.ng-num,.ng-update{display:none}}</style>'''
    return m.page('Node Groups',css+header+'<div id="node-group-list" class="node-group-list">'+_group_summary_html(rows)+'</div>'+script)


def node_groups_summary():
    m=_m(); deny=m.require_dashboard()
    if deny:return deny
    return m.Response(_group_summary_html(_filtered_sorted_group_summaries()),mimetype='text/html')


def _node_group_detail_rows(group_id:int):
    m=_m(); cfg=m.get_abuse_settings(); stale=_ts()-m.FAST_CURRENT_STALE_SECONDS; q=str(m.request.args.get('q') or '').strip().lower(); params=[stale,cfg['revision'],m.ABUSE_ENGINE_VERSION,group_id]; search=''
    if q:
        search=" AND (LOWER(ni.node) LIKE ? OR EXISTS (SELECT 1 FROM node_bridge_addresses_latest ba WHERE ba.node=ni.node AND (LOWER(COALESCE(ba.primary_ipv4,'')) LIKE ? OR LOWER(COALESCE(ba.ipv4_json,'[]')) LIKE ?)))"
        pattern='%'+q.replace('%','\\%').replace('_','\\_')+'%'; params.extend([pattern,pattern,pattern])
    conn=m.db()
    try:
        return conn.execute("""WITH vm_counts AS (SELECT vi.node,COUNT(*) vm_count FROM vm_inventory vi JOIN node_inventory ni2 ON ni2.node=vi.node WHERE COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL AND COALESCE(ni2.status,'active')!='hidden' AND ni2.deleted_at IS NULL GROUP BY vi.node),abuse_counts AS (SELECT a.node,COUNT(DISTINCT a.vm_uuid) abuse_count FROM vm_abuse_state a JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid WHERE a.is_abuse=1 AND a.last_seen>=? AND a.policy_revision=? AND a.engine_version=? AND COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL GROUP BY a.node) SELECT ni.node,COALESCE(v.vm_count,0),ncf.load1,ncf.load5,ncf.load15,ncf.cpu_percent,ncf.mem_used,ncf.mem_total,ncf.disk_read_bps,ncf.disk_write_bps,COALESCE(a.abuse_count,0),COALESCE(ncf.last_seen,ni.last_push,0),g.name,g.country_code FROM node_group_memberships gm JOIN node_groups g ON g.id=gm.group_id JOIN node_inventory ni ON ni.node=gm.node LEFT JOIN node_current_fast ncf ON ncf.node=ni.node LEFT JOIN vm_counts v ON v.node=ni.node LEFT JOIN abuse_counts a ON a.node=ni.node WHERE gm.group_id=? AND COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL"""+search,params).fetchall()
    finally:conn.close()


def _sort_node_detail(rows, sort, order):
    index = {
        "node": 0, "vms": 1, "load": 2, "cpu": 5,
        "ram_used": 6, "ram_total": 7, "read": 8, "write": 9,
        "abuse": 10, "updated": 11, "status": 11,
    }.get(sort, 11)
    descending = order == "desc"

    def raw_value(row):
        if sort == "status":
            last = int(row[11] or 0)
            state = _m().health_state(last) if last > 0 else "unknown"
            return _status_rank("offline" if state == "down" else state)
        if sort == "node":
            return str(row[0] or "").lower()
        return row[index]

    # Name-first stable pass means equal numeric/status values remain ordered by
    # node name. Missing values are appended after every real value for both ASC
    # and DESC sorts.
    ordered = sorted(rows, key=lambda row: str(row[0] or "").lower())
    if sort == "node":
        return sorted(ordered, key=raw_value, reverse=descending)
    available = [row for row in ordered if raw_value(row) is not None]
    missing = [row for row in ordered if raw_value(row) is None]
    available.sort(key=raw_value, reverse=descending)
    return available + missing

def node_group_nodes(group_id):
    m=_m(); deny=m.require_dashboard()
    if deny:return deny
    row=group_row(int(group_id),include_hidden=False)
    if not row:return m.Response('Node Group not found\n',status=404,mimetype='text/plain')
    sort=str(m.request.args.get('sort') or 'status').lower(); order=str(m.request.args.get('order') or 'asc').lower(); allowed={'node','vms','load','cpu','ram_used','ram_total','read','write','abuse','updated','status'}
    if sort not in allowed:sort='status'
    if order not in {'asc','desc'}:order='asc'
    rows=_sort_node_detail(_node_group_detail_rows(int(group_id)),sort,order)
    def link(label,key,title=''):
        return '<a href="#" data-ng-sort="%s"%s>%s</a>'%(key,' title="'+m.escape(title,quote=True)+'"' if title else '',m.escape(label))
    body=[]
    for r in rows:
        node,vmc,l1,l5,l15,cpu,mu,mt,rb,wb,abuse,last,name,country=r; status=m.health_state(int(last or 0)) if int(last or 0)>0 else 'unknown'; abuse_href=m.url_for('vm_abuse_page',group=group_id,node=node)
        load='N/A' if l1 is None else f'{float(l1):.1f} / {float(l5 or 0):.1f} / {float(l15 or 0):.1f}'
        ram='N/A'
        if mt is not None and int(mt or 0)>0:
            pct=float(mu or 0)*100.0/float(mt); ram=m.metric_pill(m.human(int(mu or 0))+' / '+m.human(int(mt or 0)),m.metric_level(pct,80,90),'RAM used')
        body.append(f'''<tr><td>{flag_html(country)}<a href="{m.url_for('node_page',node=node)}"><b>{m.escape(node)}</b></a></td><td class="num">{int(vmc or 0):,}</td><td class="num">{load}</td><td class="num">{'N/A' if cpu is None else f'{float(cpu):.1f}%'}</td><td class="num">{ram}</td><td class="num">{'N/A' if rb is None else m._disk_io_rate(float(rb or 0))}</td><td class="num">{'N/A' if wb is None else m._disk_io_rate(float(wb or 0))}</td><td class="num"><a href="{m.escape(abuse_href,quote=True)}" onclick="event.stopPropagation()">{int(abuse or 0):,}</a></td><td title="{m.escape(m.fmt_full(last),quote=True) if last else 'Never'}">{_relative_update(last)}</td><td><span class="vm-state {m.escape(status)}">{m.escape(status.upper())}</span></td></tr>''')
    headers=[link('NODE','node'),link('VM COUNT','vms'),link('LOAD 1 / 5 / 15','load','Sorted by latest 1-minute load'),link('CPU','cpu'),link('RAM USED','ram_used')+' / '+link('TOTAL','ram_total'),link('DISK READ','read'),link('DISK WRITE','write'),link('ABUSE VM','abuse'),link('LAST UPDATE','updated'),link('STATUS','status')]
    html='<div class="table-wrap"><table><thead><tr>'+''.join('<th>'+h+'</th>' for h in headers)+'</tr></thead><tbody>'+(''.join(body) or '<tr><td colspan="10" class="empty">No visible nodes in this group.</td></tr>')+'</tbody></table></div>'
    return m.Response(html,mimetype='text/html')


def _matching_admin_nodes():
    m=_m(); q=str(m.request.form.get('q') or '').strip(); status=str(m.request.form.get('status') or '').strip(); gid=_clean_group_id(m.request.form.get('current_group'))
    old_args=m.request.args
    # Reuse the existing filtered query contract without N+1. Request args are
    # immutable, so query the base inventory once and apply the optional group
    # membership in a second set-based lookup.
    rows,total,_,_=_BASE['admin_nodes_query'](q,status,1,1000000)
    nodes=[str(r[0]) for r in rows]
    if gid:
        allowed=group_nodes(gid); nodes=[n for n in nodes if n in allowed]
    return nodes


def admin_node_groups_bulk():
    m=_m(); deny=require_admin()
    if deny:return deny
    action=str(m.request.form.get('action') or '').strip().lower(); scope=str(m.request.form.get('selection_scope') or 'selected').strip().lower(); target=m.safe_int(m.request.form.get('group_id'),0)
    if action in {'remove_group','move_ungrouped','move_all_ungrouped'}:target=system_group_id()
    if action=='move_all_ungrouped':
        source=m.safe_int(m.request.form.get('source_group_id'),0); row=group_row(source)
        if not row or row[5]:return m.Response('Invalid source group\n',status=400,mimetype='text/plain')
        nodes=sorted(group_nodes(source))
    elif scope=='matching':nodes=_matching_admin_nodes()
    else:nodes=list(dict.fromkeys(str(x or '').strip() for x in m.request.form.getlist('nodes') if str(x or '').strip()))
    if not nodes:return m.Response('Select at least one node\n',status=400,mimetype='text/plain')
    if target<=0:return m.Response('Select a Node Group\n',status=400,mimetype='text/plain')
    result=assign_nodes(nodes,target,_actor())
    return m.redirect(m.url_for('admin_page',section='nodes',dbmsg=f"Updated {result['changed']} node membership(s)."))



# ---------------------------------------------------------------------------
# Hotfix installer. Called once after app.py finishes its existing runtime.
# ---------------------------------------------------------------------------

def install(module):
    global _M, _CONSUMPTION_STYLE
    if getattr(module, "_NODE_GROUPS_HOTFIX_INSTALLED", False):
        return
    _M=module
    source_text = Path(module.__file__).read_text(encoding="utf-8")
    style_match = re.search(r'<style id="v5058c-consumption-ui">.*?</style>', source_text, re.S)
    if not style_match:
        raise RuntimeError("Could not locate baseline Consumption CSS")
    _CONSUMPTION_STYLE = style_match.group(0).replace("%%", "%")
    app=module.app
    _BASE.update({
        "page":module.page,"url_for":module.url_for,"admin_nav":module._v490_admin_nav,
        "admin_overview":module._v490_admin_overview,
        "admin_page_view":app.view_functions["admin_page"],
        "admin_nodes_query":module._v48134_admin_nodes,"admin_vms_query":module._v48134_admin_vms,
        "admin_nodes_section":module._v48134_admin_nodes_section,"admin_vms_section":module._v48134_admin_vms_section,
        "admin_pager":module._v48134_admin_pager,
        "get_node_rows":module.get_node_rows,"get_node_health_rows":module.get_node_health_rows,"get_top_vm_rows":module.get_top_vm_rows,
        "index_view":app.view_functions["index"],"top_view":app.view_functions["top_page"],"node_health_view":app.view_functions["node_health_page"],
        "node_page_view":app.view_functions["node_page"],"vm_page_view":app.view_functions["vm_page"],
        "admin_bulk_nodes":app.view_functions["admin_bulk_nodes"],
        "admin_users_page_view":app.view_functions["admin_users_page"],"admin_user_action_view":app.view_functions["admin_user_action"],
        "storage_params":module._storage_io_params,"storage_disk_clause":module._v48140_disk_search_clause,"storage_target":module._v48137_storage_target,
        "storage_payload_rows":module._v48137_snapshot_payload_rows,"storage_filter_options":module._v48137_storage_filter_options,"storage_node_cards":module._v48140_node_group_cards_fast,
        "storage_view":app.view_functions["storage_io_page"],
        "consumption_common_args":module._v5058c_common_args,"consumption_visible_nodes":module._v5058c_visible_nodes,"consumption_vm_rows":module._v5058c_vm_rows,"consumption_node_rows":module._v5058c_node_rows,
        "consumption_vm_totals":module._v5058c_vm_totals,"consumption_node_totals":module._v5058c_node_totals,"consumption_view":app.view_functions["bandwidth_consumption_page"],
        "abuse_filter_values":module._v48128_filter_values,"abuse_filter_form":module._v48128_filter_form,"abuse_visible_nodes":module._v48126_visible_nodes,"abuse_event_where":module._v48127_event_where,"abuse_current_rows":module._v48139_current_rows,
    })
    ensure_schema()
    replacements={
        "page":page,"url_for":url_for,"_v490_admin_nav":admin_nav,"_v490_admin_overview":admin_overview,"clean_role":clean_role,"dashboard_role":dashboard_role,"admin_allowed":admin_allowed,"require_admin":require_admin,
        "get_visible_node_names":get_visible_node_names,"monitoring_node_visible":monitoring_node_visible,"monitoring_vm_visible":monitoring_vm_visible,
        "_v48134_admin_nodes":_filtered_admin_nodes,"_v48134_admin_vms":_filtered_admin_vms,
        "_v48134_admin_nodes_section":admin_nodes_section,"_v48134_admin_vms_section":admin_vms_section,"_v48134_admin_pager":admin_pager,
        "active_admin_count":active_admin_count,"emergency_admin_needed":emergency_admin_needed,"is_last_enabled_admin":is_last_enabled_admin,"set_admin_credentials":set_admin_credentials,"bootstrap_dashboard_admin_from_settings":bootstrap_dashboard_admin_from_settings,
        "get_node_rows":get_node_rows,"get_node_health_rows":get_node_health_rows,"get_top_vm_rows":get_top_vm_rows,
        "_storage_io_params":_storage_io_params,"_v48140_disk_search_clause":_v48140_disk_search_clause,"_v48137_storage_target":_v48137_storage_target,"_v48137_snapshot_payload_rows":_v48137_snapshot_payload_rows,"_v48137_storage_filter_options":_v48137_storage_filter_options,"_v48140_node_group_cards_fast":_v48140_node_group_cards_fast,"_v48137_storage_node_group_cards":_v48140_node_group_cards_fast,
        "_v5058c_common_args":_v5058c_common_args,"_v5058c_visible_nodes":_v5058c_visible_nodes,"_v5058c_vm_rows":_v5058c_vm_rows,"_v5058c_node_rows":_v5058c_node_rows,"_v5058c_vm_totals":_v5058c_vm_totals,"_v5058c_node_totals":_v5058c_node_totals,
        "_v48128_filter_values":_v48128_filter_values,"_v48128_filter_form":_v48128_filter_form,"_v48126_visible_nodes":_v48126_visible_nodes,"_v48127_event_where":_v48127_event_where,"_v48139_current_rows":_v48139_current_rows,
    }
    for name,value in replacements.items():setattr(module,name,value)
    view_replacements={"index":index,"top_page":top_page,"node_health_page":node_health_page,"node_page":node_page,"vm_page":vm_page,"storage_io_page":storage_io_page,"bandwidth_consumption_page":bandwidth_consumption_page,"admin_page":admin_page,"admin_users_page":admin_users_page,"admin_create_user":admin_create_user,"admin_user_action":admin_user_action,"admin_change_password":admin_change_password,"admin_bulk_nodes":admin_bulk_nodes,"dashboard_login":dashboard_login,"admin_login":admin_login,"admin_setup":admin_setup}
    for endpoint,view in view_replacements.items():app.view_functions[endpoint]=view
    routes=[
        ("/admin/node-groups/create","admin_node_groups_create",admin_node_groups_create,["POST"]),
        ("/admin/node-groups/update","admin_node_groups_update",admin_node_groups_update,["POST"]),
        ("/admin/node-groups/action","admin_node_groups_action",admin_node_groups_action,["POST"]),
        ("/admin/node-groups/assign","admin_node_groups_assign",admin_node_groups_assign,["POST"]),
        ("/admin/node-groups/bulk","admin_node_groups_bulk",admin_node_groups_bulk,["POST"]),
        ("/node-groups","node_groups_page",node_groups_page,["GET"]),
        ("/node-groups/summary","node_groups_summary",node_groups_summary,["GET"]),
        ("/node-groups/<int:group_id>/nodes","node_group_nodes",node_group_nodes,["GET"]),
    ]
    for rule,endpoint,view,methods in routes:
        if endpoint not in app.view_functions:app.add_url_rule(rule,endpoint,view,methods=methods)
    module._NODE_GROUPS_HOTFIX_INSTALLED=True
