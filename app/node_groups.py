"""50.5.9-r6 Node Groups management and retention-safety hotfix.

This module is installed after the existing append-only app.py runtime has
finished registering its final implementations. It keeps the original call
chain intact and only replaces the final symbols/view functions required for
Node Groups and the admin role split.
"""
from __future__ import annotations

import html as html_lib
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
    "admin_page", "admin_abuse_page",
    "reset_all_abuse_data_v48129", "admin_abuse_settings",
    "clear_vm_abuse_data_v48128", "manage_vm_abuse_data_v48129",
    "clear_abuse_events",
    "admin_users_page", "admin_create_user", "admin_user_action",
    "admin_theme_manager", "admin_logs_page", "admin_system_health_page",
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
    if not row or not bool(row[4]):
        return 0
    return gid

def visible_node_names(group_id: int = 0) -> set[str]:
    conn = _m().db()
    try:
        sql = """SELECT ni.node FROM node_inventory ni
                 JOIN node_group_memberships gm ON gm.node=ni.node
                 JOIN node_groups g ON g.id=gm.group_id
                WHERE g.is_active=1 AND COALESCE(ni.status,'active')!='hidden'
                  AND ni.deleted_at IS NULL"""
        params = []
        if int(group_id or 0) > 0:
            sql += " AND g.id=?"
            params.append(int(group_id))
        return {str(row[0]) for row in conn.execute(sql, params).fetchall()}
    finally:
        conn.close()


def _active_membership_clause(node_expr: str, group_id: int = 0, prefix: str = "ngv"):
    sql = f"EXISTS (SELECT 1 FROM node_group_memberships {prefix}m JOIN node_groups {prefix}g ON {prefix}g.id={prefix}m.group_id WHERE {prefix}m.node={node_expr} AND {prefix}g.is_active=1"
    params = []
    if int(group_id or 0) > 0:
        sql += f" AND {prefix}g.id=?"
        params.append(int(group_id))
    return sql + ")", params





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
                SELECT 1
                  FROM node_group_memberships gm_search
                  LEFT JOIN node_bridge_addresses_latest ba_search
                    ON ba_search.node=gm_search.node
                 WHERE gm_search.group_id=g.id
                   AND (
                        LOWER(gm_search.node) LIKE ?
                        OR LOWER(COALESCE(ba_search.primary_ipv4,'')) LIKE ?
                        OR LOWER(COALESCE(ba_search.ipv4_json,'[]')) LIKE ?
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


def group_options_html(selected: int = 0, all_label: str = "All Node Groups") -> str:
    m = _m()
    rows = active_groups(selected)
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
    return '<img class="node-group-flag" src="%s" width="20" height="15" alt="%s" title="%s" loading="lazy">' % (
        m.escape(m.url_for("static", filename=f"flags/{filename}"), quote=True),
        m.escape(label, quote=True), m.escape(label, quote=True),
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


def _group_select(selected: int = 0, name: str = "group", all_label: str = "All Node Groups", aria: str = "Node Group filter") -> str:
    return '<select name="%s" aria-label="%s">%s</select>' % (
        name, _m().escape(aria, quote=True), group_options_html(selected, all_label),
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
    # Flags are rendered only by scoped Node cells. Global link decoration
    # previously attached country alt text to VM UUIDs and metric labels.
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
            ("groups", "Node Groups", m.url_for("admin_page", section="groups")),
            ("nodes", "Nodes", m.url_for("admin_page", section="nodes")),
            ("vms", "VMs", m.url_for("admin_page", section="vms")),
            ("abuse", "Abuse", m.url_for("admin_abuse_page")),
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
        f'<input name="group_q" value="{m.escape(q, quote=True)}" placeholder="Search group, node or IP">'
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


def _filtered_admin_nodes(q, status, page_no, per_page):
    rows, total, page_no, max_page = admin_nodes_query(q, status, page_no, per_page)
    return [tuple(row[:7]) for row in rows], total, page_no, max_page


def _filtered_admin_vms(q, status, page_no, per_page):
    rows, total, page_no, max_page = admin_vms_query(q, status, page_no, per_page)
    return [tuple(row[:9]) for row in rows], total, page_no, max_page


def _admin_sort_state(default="node"):
    m = _m()
    sort = str(m.request.args.get("sort") or default).strip().lower()
    order = str(m.request.args.get("order") or "asc").strip().lower()
    return sort, "desc" if order == "desc" else "asc"


def _admin_sort_link(label, key, section, q, status, per_page, group_id=0):
    m = _m()
    current, order = _admin_sort_state()
    next_order = "desc" if current == key and order == "asc" else "asc"
    values = {
        "section": section,
        "q": q or None,
        "status": status,
        "per_page": per_page,
        "sort": key,
        "order": next_order,
    }
    if group_id:
        values["group"] = group_id
    arrow = " ↑" if current == key and order == "asc" else " ↓" if current == key else ""
    return '<a class="sort-link" href="%s">%s%s</a>' % (
        m.escape(m.url_for("admin_page", **values), quote=True),
        m.escape(label),
        arrow,
    )


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
        pattern = m.like_pattern(q)
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
            pattern, pattern, pattern, pattern, pattern, normalized_mac, normalized_mac,
            pattern, pattern, pattern, pattern, pattern, pattern,
            pattern, normalized_mac, normalized_mac,
            pattern, pattern, pattern, normalized_mac, normalized_mac,
        ])
    where_sql = "WHERE " + " AND ".join(where)
    sort, order = _admin_sort_state("node")
    sort_map = {
        "node": "ni.node COLLATE NOCASE",
        "group": "ng.name COLLATE NOCASE",
        "public": "COALESCE(b.public_ipv4,'') COLLATE NOCASE",
        "private": "COALESCE(b.private_ipv4,'') COLLATE NOCASE",
        "status": "CASE WHEN COALESCE(ni.status,'active')='hidden' OR ni.deleted_at IS NOT NULL THEN 3 WHEN ng.is_active=0 THEN 2 WHEN ni.last_push<? THEN 1 ELSE 0 END",
        "vms": "COALESCE(vc.vm_count,0)",
        "last": "COALESCE(ni.last_push,0)",
        "cpu": "CASE WHEN ncf.node IS NULL THEN 1 ELSE 0 END ASC, COALESCE(ncf.cpu_percent,0)",
        "ram": "CASE WHEN ncf.node IS NULL OR COALESCE(ncf.mem_total,0)<=0 THEN 1 ELSE 0 END ASC, CASE WHEN COALESCE(ncf.mem_total,0)>0 THEN ncf.mem_used*1.0/ncf.mem_total ELSE 0 END",
        "disk": "CASE WHEN ncf.node IS NULL THEN 1 ELSE 0 END ASC, COALESCE(ncf.disk_read_bps,0)+COALESCE(ncf.disk_write_bps,0)",
        "network": "CASE WHEN ncf.node IS NULL OR COALESCE(ncf.interval_seconds,0)<=0 THEN 1 ELSE 0 END ASC, CASE WHEN COALESCE(ncf.interval_seconds,0)>0 THEN ncf.total_bytes*1.0/ncf.interval_seconds ELSE 0 END",
    }
    if sort not in sort_map:
        sort = "node"
    sort_params = [m.now_ts() - m.VM_STALE_SECONDS] if sort == "status" else []
    direction = "DESC" if order == "desc" else "ASC"
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
                 COALESCE(b.public_ipv4,''),COALESCE(b.private_ipv4,''),ng.id,ng.name,ng.country_code,
                 ng.is_active,ncf.cpu_percent,ncf.mem_used,ncf.mem_total,ncf.disk_read_bps,ncf.disk_write_bps,
                 ncf.total_bytes,ncf.interval_seconds
          FROM {from_sql}
          LEFT JOIN bridge_ip b ON b.node=ni.node LEFT JOIN vm_count vc ON vc.node=ni.node
          LEFT JOIN node_current_fast ncf ON ncf.node=ni.node
          {where_sql}
          ORDER BY {sort_map[sort]} {direction},ni.node COLLATE NOCASE ASC
          LIMIT ? OFFSET ?
        """, params + sort_params + [per_page, (page_no - 1) * per_page]).fetchall()
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
        pattern = m.like_pattern(q)
        normalized_mac = m.normalize_mac_address(q)
        where.append("""(
            vi.node LIKE ? OR ng.name LIKE ? OR vi.vm_uuid LIKE ?
            OR COALESCE(vi.last_iface,'') LIKE ? OR COALESCE(vi.last_bridge,'') LIKE ?
            OR EXISTS (SELECT 1 FROM node_bridge_addresses_latest b WHERE b.node=vi.node AND (
                COALESCE(b.primary_ipv4,'') LIKE ? OR COALESCE(b.ipv4_json,'[]') LIKE ? OR COALESCE(b.mac,'') LIKE ?
                OR (?<>'' AND LOWER(COALESCE(b.mac,''))=LOWER(?))))
            OR EXISTS (SELECT 1 FROM vm_iface_current i WHERE i.node=vi.node AND i.vm_uuid=vi.vm_uuid AND (
                COALESCE(i.iface,'') LIKE ? OR COALESCE(i.bridge,'') LIKE ?))
            OR EXISTS (SELECT 1 FROM vm_nic_identity_lookup l JOIN vm_iface_current i
                ON i.node=l.node AND i.vm_uuid=l.vm_uuid AND i.bridge=l.bridge AND i.iface=l.iface AND i.mac=l.mac
                WHERE l.node=vi.node AND l.vm_uuid=vi.vm_uuid AND (l.mac LIKE ? OR (?<>'' AND l.mac=?)))
        )""")
        params.extend([
            pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern,
            normalized_mac, normalized_mac, pattern, pattern, pattern,
            normalized_mac, normalized_mac,
        ])
    where_sql = "WHERE " + " AND ".join(where)
    sort, order = _admin_sort_state("node")
    sort_map = {
        "node": "vi.node COLLATE NOCASE",
        "group": "ng.name COLLATE NOCASE",
        "uuid": "vi.vm_uuid COLLATE NOCASE",
        "status": "CASE WHEN COALESCE(vi.status,'active')='hidden' OR vi.deleted_at IS NOT NULL THEN 2 WHEN vi.last_seen<? THEN 1 ELSE 0 END",
        "seen": "COALESCE(vi.last_seen,0)",
        "bridge": "COALESCE(vi.last_bridge,'') COLLATE NOCASE",
    }
    if sort not in sort_map:
        sort = "node"
    sort_params = [m.now_ts() - m.VM_STALE_SECONDS] if sort == "status" else []
    direction = "DESC" if order == "desc" else "ASC"
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
                 COALESCE(b.public_ipv4,''),COALESCE(b.private_ipv4,''),ng.id,ng.name,ng.country_code,
                 ng.is_active
          FROM {from_sql} LEFT JOIN bridge_ip b ON b.node=vi.node
          {where_sql}
          ORDER BY {sort_map[sort]} {direction},vi.node COLLATE NOCASE ASC,vi.vm_uuid COLLATE NOCASE ASC
          LIMIT ? OFFSET ?
        """, params + sort_params + [per_page, (page_no - 1) * per_page]).fetchall()
        return rows, total, page_no, max_page
    finally:
        conn.close()


def admin_pager(section, q, status, page_no, max_page, per_page):
    if max_page <= 1:
        return ""
    m = _m()
    sort, order = _admin_sort_state("node")
    common = {
        "section": section,
        "q": q or None,
        "status": status,
        "per_page": per_page,
        "sort": sort,
        "order": order,
    }
    group_id = _admin_group_filter()
    if group_id:
        common["group"] = group_id
    previous = m.url_for("admin_page", **common, page=max(1, page_no - 1))
    following = m.url_for("admin_page", **common, page=min(max_page, page_no + 1))
    return (
        '<div class="pagination">'
        f'<a class="btn {"disabled" if page_no <= 1 else ""}" href="{m.escape(previous, quote=True)}">← Previous</a>'
        f'<span>Page <b>{page_no}</b> / <b>{max_page}</b></span>'
        f'<a class="btn {"disabled" if page_no >= max_page else ""}" href="{m.escape(following, quote=True)}">Next →</a>'
        '</div>'
    )


def _row_action_menu(forms: str, width: int) -> str:
    """Keep the existing desktop action-button geometry after bulk removal."""
    html = _m()._v490_action_menu(forms)
    return html.replace("<div>", f'<div style="width:{int(width)}px">', 1)


def _row_group_move_form(node, selected_group):
    m = _m()
    return (
        f'<form method="post" action="{m.url_for("admin_node_groups_assign")}" '
        'onsubmit="return confirm(\'Move this node to the selected Node Group?\')">'
        f'<input type="hidden" name="csrf_token" value="{m.escape(m.csrf_token(), quote=True)}">'
        f'<input type="hidden" name="nodes" value="{m.escape(node, quote=True)}">'
        f'<select name="group_id" aria-label="Target Node Group">{group_options_html(selected_group, "Target Node Group")}</select>'
        '<button type="submit">Move Group</button></form>'
    )


def admin_nodes_section(q, status, page_no, per_page):
    m = _m()
    rows, total, page_no, max_page = admin_nodes_query(q, status, page_no, per_page)
    group_id = _admin_group_filter()
    cutoff = m.now_ts() - m.VM_STALE_SECONDS
    body = []
    for (node, row_status, last_push, deleted_at, vm_count, public_ip, private_ip,
         gid, group_name, country, group_active, cpu_percent, mem_used, mem_total,
         disk_read_bps, disk_write_bps, total_bytes, interval_seconds) in rows:
        hidden = row_status == "hidden" or bool(deleted_at)
        stale = not hidden and m.safe_int(last_push, 0) < cutoff
        agent_status = "hidden" if hidden else "stale" if stale else "active"
        group_note = '<small class="row-sub">Group Hidden</small>' if not group_active else ""
        has_current = cpu_percent is not None
        cpu_value = m.safe_float(cpu_percent, 0)
        ram_pct = m.ram_used_percent_value(mem_used, mem_total) if has_current else 0.0
        cpu_html = "N/A" if not has_current else m.metric_pill(
            m.fmt_percent(cpu_value), m.metric_level(cpu_value, 70, 85), "Current host CPU"
        )
        ram_html = "N/A" if not has_current or m.safe_int(mem_total, 0) <= 0 else (
            m.metric_pill(
                f"{m.human(mem_used)} / {m.human(mem_total)}",
                m.metric_level(ram_pct, 80, 90),
                f"Current host RAM used {ram_pct:.1f}%",
            ) + f'<small class="row-sub">{ram_pct:.1f}% used</small>'
        )
        disk_total = m.safe_float(disk_read_bps, 0) + m.safe_float(disk_write_bps, 0)
        disk_html = "N/A" if not has_current else (
            f'<b>{m.human_rate(disk_total)}</b>'
            f'<small class="row-sub">R {m.human_rate(disk_read_bps)} · W {m.human_rate(disk_write_bps)}</small>'
        )
        net_html = "N/A" if not has_current or m.safe_int(interval_seconds, 0) <= 0 else (
            f'<b>{m.fmt_mbps(total_bytes, interval_seconds)}</b>'
            f'<small class="row-sub">Current interval {m.safe_int(interval_seconds, 0)}s</small>'
        )
        forms = m.admin_form(m.url_for("admin_delete_node"), "Hide", {"node": node, "mode": "soft"}, danger=True, confirm="Hide node from monitoring? Raw usage is kept.")
        forms += m.admin_form(m.url_for("admin_restore_node"), "Restore", {"node": node}, danger=False, confirm="Restore node to monitoring?")
        forms += _row_group_move_form(node, int(gid))
        forms += m.admin_form(m.url_for("admin_purge_node_vms"), "Purge VMs", {"node": node}, danger=True, confirm="Queue purge of all VM monitoring data under this node?")
        forms += m.admin_form(m.url_for("admin_delete_node"), "Purge node", {"node": node, "mode": "purge"}, danger=True, confirm="Permanently purge this node and its monitoring data?")
        body.append(
            f'<tr class="{"stale-row" if hidden or stale or not group_active else ""}">'
            f'<td>{flag_html(country)}<b>{m.escape(node)}</b><small class="row-sub">{m.escape(agent_status)}</small>{group_note}</td>'
            f'<td>{m.escape(group_name)}</td>'
            f'<td class="mono">{m.escape(m.compact_ipv4(public_ip) or "-")}</td>'
            f'<td class="mono">{m.escape(m.compact_ipv4(private_ip) or "-")}</td>'
            f'<td class="num"><b>{m.safe_int(vm_count, 0)}</b></td>'
            f'<td class="num">{cpu_html}</td>'
            f'<td class="num">{ram_html}</td>'
            f'<td class="num">{disk_html}</td>'
            f'<td class="num">{net_html}</td>'
            f'<td>{m.fmt_full(last_push)}</td>'
            f'<td>{_row_action_menu(forms, 145)}</td></tr>'
        )
    body_html = ''.join(body) or '<tr><td colspan="11" class="empty">No nodes match this filter</td></tr>'
    headers = [
        _admin_sort_link("NODE / STATUS", "node", "nodes", q, status, per_page, group_id),
        _admin_sort_link("NODE GROUP", "group", "nodes", q, status, per_page, group_id),
        _admin_sort_link("PUBLIC IP", "public", "nodes", q, status, per_page, group_id),
        _admin_sort_link("PRIVATE IP", "private", "nodes", q, status, per_page, group_id),
        _admin_sort_link("VM", "vms", "nodes", q, status, per_page, group_id),
        _admin_sort_link("CPU", "cpu", "nodes", q, status, per_page, group_id),
        _admin_sort_link("RAM", "ram", "nodes", q, status, per_page, group_id),
        _admin_sort_link("DISK I/O", "disk", "nodes", q, status, per_page, group_id),
        _admin_sort_link("NETWORK", "network", "nodes", q, status, per_page, group_id),
        _admin_sort_link("LAST PUSH", "last", "nodes", q, status, per_page, group_id),
        "ACTION",
    ]
    filters = (
        '<form class="search" method="get">'
        '<input type="hidden" name="section" value="nodes">'
        f'<input name="q" value="{m.escape(q, quote=True)}" placeholder="Search node, group, IP, MAC, VM, bridge or interface">'
        f'<select name="status">{m._v48134_status_options(status)}</select>'
        f'{_group_select(group_id)}'
        f'<select name="per_page"><option value="100" {"selected" if per_page == 100 else ""}>100 rows</option><option value="200" {"selected" if per_page == 200 else ""}>200 rows</option><option value="500" {"selected" if per_page == 500 else ""}>500 rows</option></select>'
        '<button>Filter</button>'
        f'<a class="clear" href="{m.url_for("admin_page", section="nodes")}">Reset</a></form>'
    )
    return (
        '<div class="card"><div class="section-head"><div><h3>Node management</h3>'
        f'<p>{total:,} matching node(s). Each row has direct actions; group-hidden state is separate from agent state.</p>'
        f'</div></div>{filters}<div class="table-wrap"><table class="admin-clean-table node-groups-admin-nodes">'
        f'<thead><tr>{"".join("<th>" + header + "</th>" for header in headers)}</tr></thead>'
        f'<tbody>{body_html}</tbody></table></div>{admin_pager("nodes", q, status, page_no, max_page, per_page)}</div>'
    )


def admin_vms_section(q, status, page_no, per_page):
    m = _m()
    rows, total, page_no, max_page = admin_vms_query(q, status, page_no, per_page)
    group_id = _admin_group_filter()
    cutoff = m.now_ts() - m.VM_STALE_SECONDS
    body = []
    for node, vm_uuid, row_status, last_seen, bridge, iface, deleted_at, public_ip, private_ip, gid, group_name, country, group_active in rows:
        hidden = row_status == "hidden" or bool(deleted_at)
        stale = not hidden and m.safe_int(last_seen, 0) < cutoff
        display_status = "hidden" if hidden else "stale" if stale else "active"
        forms = m.admin_form(m.url_for("admin_delete_vm"), "Hide", {"node": node, "vm_uuid": vm_uuid, "mode": "soft"}, danger=True, confirm="Hide VM from monitoring? Raw usage is kept.")
        forms += m.admin_form(m.url_for("admin_restore_vm"), "Restore", {"node": node, "vm_uuid": vm_uuid}, danger=False, confirm="Restore VM to monitoring?")
        forms += m.admin_form(m.url_for("admin_delete_vm"), "Purge VM", {"node": node, "vm_uuid": vm_uuid, "mode": "purge"}, danger=True, confirm="Permanently purge only this UUID from VM-scoped monitoring data?")
        group_note = ' <span class="vm-state stale">HIDDEN</span>' if not group_active else ''
        body.append(
            f'<tr class="{"stale-row" if hidden or stale or not group_active else ""}">'
            f'<td><b>{m.escape(node)}</b><small class="row-sub">{m.escape(m.compact_ipv4(public_ip) or "-")}</small></td>'
            f'<td>{m.escape(group_name)}{group_note}</td>'
            f'<td class="mono"><span class="uuid-cell">{m.escape(vm_uuid)}<button type="button" class="copy-btn" data-copy="{m.escape(vm_uuid, quote=True)}">⧉</button></span></td>'
            f'<td><b>{m.escape(display_status)}</b><small class="row-sub">{m.fmt_push(last_seen)}</small></td>'
            f'<td>{m.escape(bridge or "-")}<small class="row-sub">{m.escape(iface or "-")}</small></td>'
            f'<td>{m._v490_action_menu(forms)}</td></tr>'
        )
    body_html = ''.join(body) or '<tr><td colspan="6" class="empty">No VMs match this filter</td></tr>'
    headers = [
        _admin_sort_link("NODE / IP", "node", "vms", q, status, per_page, group_id),
        _admin_sort_link("NODE GROUP", "group", "vms", q, status, per_page, group_id),
        _admin_sort_link("VM UUID", "uuid", "vms", q, status, per_page, group_id),
        _admin_sort_link("STATUS / SEEN", "seen", "vms", q, status, per_page, group_id),
        _admin_sort_link("BRIDGE / IFACE", "bridge", "vms", q, status, per_page, group_id),
        "ACTION",
    ]
    filters = (
        '<form class="search" method="get">'
        '<input type="hidden" name="section" value="vms">'
        f'<input name="q" value="{m.escape(q, quote=True)}" placeholder="Search node, group, IP, MAC, VM UUID, bridge or interface">'
        f'<select name="status">{m._v48134_status_options(status)}</select>'
        f'{_group_select(group_id)}'
        f'<select name="per_page"><option value="100" {"selected" if per_page == 100 else ""}>100 rows</option><option value="200" {"selected" if per_page == 200 else ""}>200 rows</option><option value="500" {"selected" if per_page == 500 else ""}>500 rows</option></select>'
        '<button>Filter</button>'
        f'<a class="clear" href="{m.url_for("admin_page", section="vms")}">Reset</a></form>'
    )
    return (
        '<div class="card"><div class="section-head"><div><h3>VM management</h3>'
        f'<p>{total:,} matching VM(s). Each row has direct Hide, Restore and Purge actions.</p>'
        f'</div></div>{filters}<div class="table-wrap"><table class="admin-clean-table node-groups-admin-vms">'
        f'<thead><tr>{"".join("<th>" + header + "</th>" for header in headers)}</tr></thead>'
        f'<tbody>{body_html}</tbody></table></div>{admin_pager("vms", q, status, page_no, max_page, per_page)}</div>'
    )

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
    actor_role = current_role()
    conn = m.db()
    try:
        if actor_role == "admin":
            users = conn.execute("""
                SELECT id,username,role,is_active,created_at,updated_at,last_login
                  FROM dashboard_users
                 WHERE role IN ('viewer','admin')
                 ORDER BY role DESC,LOWER(username),id
            """).fetchall()
        else:
            users = conn.execute("""
                SELECT id,username,role,is_active,created_at,updated_at,last_login
                  FROM dashboard_users
                 ORDER BY CASE role WHEN 'super_admin' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END,
                          LOWER(username),id
            """).fetchall()
    finally:
        conn.close()
    current_id = int(m.current_dashboard_user_id() or 0)
    csrf = m.escape(m.csrf_token(), quote=True)
    body = []
    roles = ("viewer", "admin", "super_admin") if actor_role == "super_admin" else ("viewer", "admin")
    for user_id, username, role, is_active, created_at, updated_at, last_login in users:
        role = clean_role(role)
        if actor_role == "admin" and role == "super_admin":
            continue
        is_current = int(user_id) == current_id
        options = ''.join(
            '<option value="%s"%s>%s</option>' % (
                m.escape(item, quote=True), ' selected' if item == role else '', m.escape(item),
            ) for item in roles
        )
        role_control = (
            '<input type="hidden" name="role" value="%s"><select disabled>%s</select>' %
            (m.escape(role, quote=True), options)
            if is_current else '<select name="role">%s</select>' % options
        )
        badges = '<span class="vm-state active">CURRENT</span>' if is_current else ''
        status = "active" if is_active else "disabled"
        status_cls = "active" if is_active else "stale"
        action = "disable" if is_active else "enable"
        action_label = "Disable" if is_active else "Enable"
        controls = f'''<form class="inline-form" method="post" action="{m.url_for("admin_user_action")}" onsubmit="return confirm('Update this user?')">
          <input type="hidden" name="csrf_token" value="{csrf}"><input type="hidden" name="user_id" value="{int(user_id)}"><input type="hidden" name="action" value="reset_password">
          <input name="new_password" type="password" placeholder="New password" autocomplete="new-password">{role_control}<button class="btn" type="submit">Reset</button></form>'''
        if not is_current:
            controls += m.admin_form(m.url_for('admin_user_action'), action_label, {'user_id': user_id, 'action': action}, danger=False, confirm=f'{action_label} this user?')
            controls += m.admin_form(m.url_for('admin_user_action'), 'Delete', {'user_id': user_id, 'action': 'delete'}, danger=True, confirm='Delete this dashboard user?')
        body.append(f'''<tr><td>{int(user_id)}</td><td class="mono"><b>{m.escape(username)}</b> {badges}</td><td>{m.escape(role)}</td><td><span class="vm-state {status_cls}">{status.upper()}</span></td><td>{m.fmt_full(created_at)}</td><td>{m.fmt_full(last_login)}</td><td>{controls}</td></tr>''')
    role_options = ''.join('<option value="%s">%s</option>' % (r, r) for r in roles)
    body_html = ''.join(body) or '<tr><td colspan="7" class="empty">No dashboard users</td></tr>'
    note = 'Admin can manage Viewer and Admin accounts. Super Admin accounts are not visible to Admin.' if actor_role == 'admin' else 'Super Admin can manage all dashboard roles. The current account and the last enabled Super Admin are protected by backend checks.'
    content = f'''<div class="card"><h3>Dashboard Users</h3><a href="{m.url_for("admin_page")}">Back to Admin</a><a href="{m.url_for("admin_logs_page", type="account")}">Account logs</a><div class="admin-note">{m.escape(note)}</div></div>
    <div class="card"><h3>Create User</h3><form method="post" action="{m.url_for("admin_create_user")}" onsubmit="return confirm('Create this user?')"><input type="hidden" name="csrf_token" value="{csrf}"><div class="form-grid"><div><label>Username</label><input name="username" autocomplete="username" required></div><div><label>Password</label><input name="password" type="password" autocomplete="new-password" required></div><div><label>Role</label><select name="role">{role_options}</select></div><div><button class="btn" type="submit">Create user</button></div></div></form></div>
    <div class="card"><div class="table-title-row"><h3>Users</h3><div class="count-badges"><span>Users <b>{len(users)}</b></span></div></div><div class="table-wrap"><table><thead><tr><th>ID</th><th>USERNAME</th><th>ROLE</th><th>STATUS</th><th>CREATED</th><th>LAST LOGIN</th><th>ACTION</th></tr></thead><tbody>{body_html}</tbody></table></div></div>'''
    return m.page("Dashboard Users", content)




def admin_create_user():
    m = _m()
    deny = require_admin()
    if deny:
        return deny
    actor_role = current_role()
    username = m.clean_username(m.request.form.get("username"))
    password = m.request.form.get("password") or ""
    requested_role = clean_role(m.request.form.get("role"))
    allowed = {"viewer", "admin", "super_admin"} if actor_role == "super_admin" else {"viewer", "admin"}
    if requested_role not in allowed or not username or len(username) < 3 or len(password) < 10:
        return m.Response("Unable to create user with the provided information.\n", status=400, mimetype="text/plain")
    if m.get_dashboard_user(username):
        return m.Response("Unable to create user with the provided information.\n", status=400, mimetype="text/plain")
    m.upsert_dashboard_user(username, password, role=requested_role, is_active=1)
    m.log_account_event("user_created", username=username, realm="admin", role=requested_role, detail=f"created_by={_actor()}")
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
    row = m.get_dashboard_user_by_id(user_id)
    if not row:
        return m.Response("User not found\n", status=404, mimetype="text/plain")
    _, username, _, old_role, old_active, *_ = row
    old_role = clean_role(old_role)
    actor_role = current_role()
    current_id = int(m.current_dashboard_user_id() or 0)
    if actor_role == "admin" and old_role == "super_admin":
        return m.Response("User not found\n", status=404, mimetype="text/plain")
    if action in {"disable", "delete"} and user_id == current_id:
        return m.Response("Safety block: you cannot disable or delete the account you are currently using.\n", status=400, mimetype="text/plain")
    if action in {"disable", "delete"} and old_role == "super_admin" and active_super_admin_count(user_id) == 0:
        return m.Response("Safety block: the last enabled Super Admin cannot be disabled or deleted.\n", status=400, mimetype="text/plain")
    if action == "disable":
        m.set_dashboard_user_status(user_id, 0)
        event = "user_disabled"
    elif action == "enable":
        m.set_dashboard_user_status(user_id, 1)
        event = "user_enabled"
    elif action == "delete":
        m.delete_dashboard_user(user_id)
        event = "user_deleted"
    elif action == "reset_password":
        new_password = m.request.form.get("new_password") or ""
        if len(new_password) < 10:
            return m.Response("New password must be at least 10 characters\n", status=400, mimetype="text/plain")
        requested_role = clean_role(m.request.form.get("role") or old_role)
        allowed = {"viewer", "admin", "super_admin"} if actor_role == "super_admin" else {"viewer", "admin"}
        if requested_role not in allowed:
            return m.Response("User not found\n", status=404, mimetype="text/plain")
        if user_id == current_id and requested_role != old_role:
            return m.Response("Safety block: you cannot change the role of the account you are currently using.\n", status=400, mimetype="text/plain")
        if old_role == "super_admin" and requested_role != "super_admin" and active_super_admin_count(user_id) == 0:
            return m.Response("Safety block: the last enabled Super Admin cannot be downgraded.\n", status=400, mimetype="text/plain")
        m.reset_dashboard_user_password(user_id, new_password, role=requested_role)
        old_role = requested_role
        event = "user_password_reset"
    else:
        return m.Response("Invalid action\n", status=400, mimetype="text/plain")
    m.log_account_event(event, username=username, realm="admin", role=old_role, detail=f"actor={_actor()}")
    return m.redirect(m.url_for("admin_users_page"))





def admin_change_password():
    m = _m()
    deny = require_admin()
    if deny:
        return deny
    row = m.current_dashboard_user()
    if not row:
        return m.Response("Forbidden\n", status=403, mimetype="text/plain")
    user_id, username, password_hash, role, is_active, *_ = row
    error = success = ""
    if m.request.method == "POST":
        current = m.request.form.get("current_password") or ""
        new_password = m.request.form.get("new_password") or ""
        confirm = m.request.form.get("confirm_password") or ""
        if not m.check_password_hash(password_hash, current):
            error = "Current password is incorrect."
        elif len(new_password) < 10:
            error = "New password must be at least 10 characters."
        elif new_password != confirm:
            error = "Password confirmation does not match."
        else:
            conn = m.db()
            try:
                conn.execute("UPDATE dashboard_users SET password_hash=?,updated_at=? WHERE id=?", (m.generate_password_hash(new_password), _ts(), int(user_id)))
                conn.commit()
            finally:
                conn.close()
            m.log_account_event("password_changed", username=username, realm="admin", role=clean_role(role), detail="self_service=1")
            success = "Your password has been updated."
    content = f'''<div class="card login-card"><h3>Change Password</h3><a href="{m.url_for("admin_page")}">Back to Admin</a>{f'<div class="error-box">{m.escape(error)}</div>' if error else ''}{f'<div class="success-box">{m.escape(success)}</div>' if success else ''}<form method="post" action="{m.url_for("admin_change_password")}"><input type="hidden" name="csrf_token" value="{m.escape(m.csrf_token(), quote=True)}"><label>Current Password</label><input name="current_password" type="password" autocomplete="current-password" autofocus><label>New Password</label><input name="new_password" type="password" autocomplete="new-password"><label>Confirm New Password</label><input name="confirm_password" type="password" autocomplete="new-password"><button type="submit">Update Password</button></form></div>'''
    return m.page("Change Password", content)


# ---------------------------------------------------------------------------
# Monitoring data filters. All/no-group returns the untouched baseline path.
# ---------------------------------------------------------------------------

def get_node_rows(period, q="", sort_by="node", order="asc", target_ts=None):
    rows, start, end = _BASE["get_node_rows"](period, q, sort_by=sort_by, order=order, target_ts=target_ts)
    allowed = visible_node_names(selected_group_id())
    return [row for row in rows if str(row[0]) in allowed], start, end



def get_node_health_rows(q="", sort_by="status", order="asc"):
    rows = _BASE["get_node_health_rows"](q=q, sort_by=sort_by, order=order)
    allowed = visible_node_names(selected_group_id())
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
        rows, selected_bucket, latest_bucket, used_limit = _BASE["get_top_vm_rows"](period, q=q, sort_by=sort_by, order=order, scope=scope, limit=limit)
        allowed = visible_node_names()
        return [row for row in rows if str(row[0]) in allowed], selected_bucket, latest_bucket, used_limit
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
    allowed = visible_node_names(gid)
    rows = [r for r in rows if str(r[0]) in allowed]
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
        rows.sort(key=lambda row: (0 if any(m.safe_int(row[i],0)>0 for i in (35,36,37)) else 1, disk_metric(row) if requested_order=="asc" else -disk_metric(row), m.safe_float(row[7],0)))
    return rows[:requested_limit], selected_bucket, latest_bucket, requested_limit



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
    clause, group_params = _active_membership_clause(f"{summary_alias}.node", gid, "stg")
    clauses.append(clause)
    params.extend(group_params)
    return clauses, params


def _v48137_storage_target(conn, values):
    gid = _clean_group_id(values.get("group"))
    m = _m(); m.ensure_storage_snapshot_schema(conn)
    requested_at = m._request_target_ts(); node = str(values.get("node") or "").strip()
    clause, params = _active_membership_clause("node_push_snapshots.node", gid, "stt")
    where = ["storage_payload IS NOT NULL", clause]
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
    clause, group_params = _active_membership_clause("node_push_snapshots.node", gid, "stp")
    where = ["storage_payload IS NOT NULL", "bucket<=?", clause]
    params = [target_bucket] + group_params
    if node: where.append("node=?"); params.append(node)
    where_sql = " AND ".join(where)
    return conn.execute(f"""WITH picked AS (SELECT node,MAX(bucket) bucket FROM node_push_snapshots WHERE {where_sql} GROUP BY node)
      SELECT s.node,s.bucket,s.push_time,s.storage_payload FROM node_push_snapshots s JOIN picked p ON p.node=s.node AND p.bucket=s.bucket ORDER BY s.node COLLATE NOCASE""",params).fetchall()


def _v48137_storage_filter_options(conn, values):
    gid = _clean_group_id(values.get("group"))
    membership_clause, membership_params = _active_membership_clause("x.node", gid, "sfo")
    nodes = [
        str(row[0])
        for row in conn.execute(
            f"""SELECT x.node
              FROM (
                    SELECT node FROM vm_disk_summary_current
                    UNION
                    SELECT node FROM node_storage_mount_summary_current
                   ) x
              LEFT JOIN node_inventory ni ON ni.node=x.node
             WHERE {membership_clause}
               AND (ni.node IS NULL OR (
                    COALESCE(ni.status,'active')!='hidden'
                    AND ni.deleted_at IS NULL
               ))
             GROUP BY x.node
             ORDER BY x.node COLLATE NOCASE""",
            membership_params,
        ).fetchall()
    ]
    node_filter = str(values.get("node") or "").strip()
    mount_clause, mount_params = _active_membership_clause("q.node", gid, "sfm")
    mount_where = [mount_clause]
    params = list(mount_params)
    if node_filter:
        mount_where.append("q.node=?")
        params.append(node_filter)
    mounts = [
        str(row[0])
        for row in conn.execute(
            f"""SELECT q.mount
              FROM (
                    SELECT d.node,d.mount
                      FROM vm_disk_current d
                      JOIN vm_inventory vi
                        ON vi.node=d.node AND vi.vm_uuid=d.vm_uuid
                     WHERE d.role='customer'
                       AND d.mount!=''
                       AND COALESCE(vi.status,'active')!='hidden'
                       AND vi.deleted_at IS NULL
                    UNION
                    SELECT s.node,s.mount
                      FROM node_storage_mount_summary_current s
                     WHERE s.mount!=''
                   ) q
              LEFT JOIN node_inventory ni ON ni.node=q.node
             WHERE {' AND '.join(mount_where)}
               AND (ni.node IS NULL OR (
                    COALESCE(ni.status,'active')!='hidden'
                    AND ni.deleted_at IS NULL
               ))
             GROUP BY q.mount
             ORDER BY q.mount COLLATE NOCASE""",
            params,
        ).fetchall()
    ]
    esc = _m().escape
    node_html = '<option value="">All nodes</option>' + ''.join(
        f'<option value="{esc(node, quote=True)}"'
        f'{" selected" if node == node_filter else ""}>{esc(node)}</option>'
        for node in nodes
    )
    mount_html = '<option value="">All storage</option>' + ''.join(
        f'<option value="{esc(mount, quote=True)}"'
        f'{" selected" if mount == values.get("mount") else ""}>{esc(mount)}</option>'
        for mount in mounts
    )
    return node_html, mount_html

def _v48140_node_group_cards_fast(conn, values, start_ts):
    gid = _clean_group_id(values.get("group"))
    m = _m()
    m._v48140_reconcile_summaries_if_needed(conn)
    sort_map={"node":"g.node COLLATE NOCASE","size":"g.size","used":"g.used","usepct":"CASE WHEN g.size>0 THEN g.used*1.0/g.size ELSE 0 END","read":"g.read_bps","write":"g.write_bps","readiops":"g.read_iops","writeiops":"g.write_iops","util":"g.util_percent","seen":"g.last_seen"}
    if values.get("sort") not in sort_map: values["sort"]="writeiops"
    membership_clause, membership_params = _active_membership_clause("s.node", gid, "snc")
    where=["s.last_seen>=?","(ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))",membership_clause]
    params=[start_ts]+membership_params
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
    gid = selected_group_id()
    clause, params = _active_membership_clause("ni.node", gid, "cvis")
    conn = _m().db()
    try:
        return conn.execute(f"""SELECT ni.node,COALESCE(MAX(CASE WHEN LOWER(COALESCE(ba.role,''))='public' THEN ba.primary_ipv4 END),'') public_ipv4
          FROM node_inventory ni LEFT JOIN node_bridge_addresses_latest ba ON ba.node=ni.node
          WHERE {clause} AND COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL
          GROUP BY ni.node ORDER BY LOWER(ni.node)""", params).fetchall()
    finally:
        conn.close()



def _consumption_group_where(alias: str):
    clause, params = _active_membership_clause(f"{alias}.node", selected_group_id(), "cgrp")
    return " AND " + clause, params



def _v5058c_vm_rows(start,end,selected_node,q,coverage,sort_by,order,page_no,limit):
    gid=selected_group_id()
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
    gid=selected_group_id()
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
    gid=selected_group_id()
    m=_m(); ctes,params=m._v5058c_vm_ctes(start,end,selected_node); conn=m.db()
    clause,group_params=_active_membership_clause("vm_rows.node",gid,"cvt")
    try:
        row=conn.execute(ctes+f"""SELECT COALESCE(SUM(public_rx),0),COALESCE(SUM(public_tx),0),COALESCE(SUM(private_rx),0),COALESCE(SUM(private_tx),0) FROM vm_rows WHERE {clause}""",params+group_params).fetchone()
        return {"vm_public_rx":m.safe_int(row[0] if row else 0,0),"vm_public_tx":m.safe_int(row[1] if row else 0,0),"vm_private_rx":m.safe_int(row[2] if row else 0,0),"vm_private_tx":m.safe_int(row[3] if row else 0,0)}
    finally:conn.close()


def _v5058c_node_totals(start,end,selected_node=""):
    gid=selected_group_id()
    m=_m(); ctes,params=m._v5058c_node_ctes(start,end); conn=m.db()
    clause,group_params=_active_membership_clause("node_rows.node",gid,"cnt")
    try:
        row=conn.execute(ctes+f"""SELECT COALESCE(SUM(physical_public_rx),0),COALESCE(SUM(physical_public_tx),0),COALESCE(SUM(physical_private_rx),0),COALESCE(SUM(physical_private_tx),0) FROM node_rows WHERE {clause}""",params+group_params).fetchone()
        return {"physical_public_rx":m.safe_int(row[0] if row else 0,0),"physical_public_tx":m.safe_int(row[1] if row else 0,0),"physical_private_rx":m.safe_int(row[2] if row else 0,0),"physical_private_tx":m.safe_int(row[3] if row else 0,0)}
    finally:conn.close()


def _consumption_group_page():
    m = _m()
    period = m._v5058c_period(m.request.args.get("period"))
    _label, seconds = m.V5058C_PERIODS[period]
    end = m.now_ts()
    start = end - seconds
    selected = selected_group_id()
    q = str(m.request.args.get("q") or "").strip().lower()
    sort = str(m.request.args.get("sort") or "total").strip().lower()
    order = str(m.request.args.get("order") or "desc").strip().lower()
    allowed_sort = {"group", "nodes", "vms", "rx", "tx", "total", "physical", "vm"}
    if sort not in allowed_sort:
        sort = "total"
    if order not in {"asc", "desc"}:
        order = "desc"

    vm_ctes, vm_params = m._v5058c_vm_ctes(start, end, "")
    node_ctes, node_params = m._v5058c_node_ctes(start, end)
    conn = m.db()
    try:
        vm = {
            int(row[0]): row[1:]
            for row in conn.execute(
                vm_ctes + """SELECT gm.group_id,COUNT(*),
                    COALESCE(SUM(public_rx),0),COALESCE(SUM(public_tx),0),
                    COALESCE(SUM(private_rx),0),COALESCE(SUM(private_tx),0)
                  FROM vm_rows
                  JOIN node_group_memberships gm ON gm.node=vm_rows.node
                  JOIN node_groups g ON g.id=gm.group_id AND g.is_active=1
                 GROUP BY gm.group_id""",
                vm_params,
            ).fetchall()
        }
        node = {
            int(row[0]): row[1:]
            for row in conn.execute(
                node_ctes + """SELECT gm.group_id,COUNT(*),
                    COALESCE(SUM(physical_public_rx),0),COALESCE(SUM(physical_public_tx),0),
                    COALESCE(SUM(physical_private_rx),0),COALESCE(SUM(physical_private_tx),0)
                  FROM node_rows
                  JOIN node_group_memberships gm ON gm.node=node_rows.node
                  JOIN node_groups g ON g.id=gm.group_id AND g.is_active=1
                 GROUP BY gm.group_id""",
                node_params,
            ).fetchall()
        }
    finally:
        conn.close()

    records = []
    for group in all_group_rows(visibility="active"):
        gid, name, _desc, country, _active, _system, _node_count, _vm_count, *_ = group
        gid = int(gid)
        if selected and gid != selected:
            continue
        if q and q not in str(name).lower():
            continue
        node_values = node.get(gid, (0, 0, 0, 0, 0))
        vm_values = vm.get(gid, (0, 0, 0, 0, 0))
        physical_rx = int(node_values[1] or 0) + int(node_values[3] or 0)
        physical_tx = int(node_values[2] or 0) + int(node_values[4] or 0)
        vm_rx = int(vm_values[1] or 0) + int(vm_values[3] or 0)
        vm_tx = int(vm_values[2] or 0) + int(vm_values[4] or 0)
        rx = physical_rx + vm_rx
        tx = physical_tx + vm_tx
        records.append({
            "id": gid,
            "name": str(name),
            "country": str(country or ""),
            "nodes": int(node_values[0] or 0),
            "vms": int(vm_values[0] or 0),
            "rx": rx,
            "tx": tx,
            "total": rx + tx,
            "physical": physical_rx + physical_tx,
            "vm": vm_rx + vm_tx,
        })

    records.sort(key=lambda item: item["name"].lower())
    if sort == "group":
        records.sort(key=lambda item: item["name"].lower(), reverse=order == "desc")
    else:
        records.sort(key=lambda item: int(item[sort]), reverse=order == "desc")

    def sort_link(label, key):
        next_order = "desc" if sort == key and order == "asc" else "asc"
        href = m.url_for(
            "bandwidth_consumption_page",
            tab="group",
            period=period,
            group=selected or None,
            q=q or None,
            sort=key,
            order=next_order,
        )
        arrow = " ↑" if sort == key and order == "asc" else " ↓" if sort == key else ""
        return '<a class="sort-link" href="%s">%s%s</a>' % (
            m.escape(href, quote=True), m.escape(label), arrow,
        )

    body = []
    for item in records:
        href = m.url_for("bandwidth_consumption_page", tab="node", period=period, group=item["id"])
        body.append(
            f'<tr><td><a href="{m.escape(href, quote=True)}"><b>{flag_html(item["country"])}{m.escape(item["name"])}</b></a></td>'
            f'<td class="num">{item["nodes"]:,}</td><td class="num">{item["vms"]:,}</td>'
            f'<td class="num">{m.human(item["rx"])}</td><td class="num">{m.human(item["tx"])}</td>'
            f'<td class="num v5058c-total">{m.human(item["total"])}</td>'
            f'<td class="num">{m.human(item["physical"])}</td><td class="num">{m.human(item["vm"])}</td></tr>'
        )
    body_html = ''.join(body) or '<tr><td colspan="8" class="empty">No Node Group consumption in this range</td></tr>'
    periods = ''.join(
        f'<a class="{"active" if key == period else ""}" href="{m.url_for("bandwidth_consumption_page", tab="group", period=key, group=selected or None, q=q or None, sort=sort, order=order)}">{m.escape(value[0])}</a>'
        for key, value in m.V5058C_PERIODS.items()
    )
    tabs = (
        f'<div class="v5058c-tabs"><a href="{m.url_for("bandwidth_consumption_page", tab="vm", period=period)}">VM Consumption</a>'
        f'<a href="{m.url_for("bandwidth_consumption_page", tab="node", period=period)}">Node Consumption</a>'
        f'<a class="active" href="{m.url_for("bandwidth_consumption_page", tab="group", period=period)}">Node Group</a></div>'
    )
    reset_href = m.url_for("bandwidth_consumption_page", tab="group", period=period)
    content = (
        '<div class="card v5058c-shell"><div class="v5058c-head"><div><h2>Consumption</h2>'
        '<p>Existing consumption counters aggregated by inherited Node Group. RX/TX are raw byte sums from the same Node and VM consumption sources.</p></div>'
        f'<div class="v5058c-range"><div class="v5058c-range-block"><span>TIME RANGE</span><div class="v5058c-periods">{periods}</div></div></div></div>'
        f'{tabs}<form class="v5058c-toolbar" method="get"><input type="hidden" name="tab" value="group"><input type="hidden" name="period" value="{period}">'
        f'<input type="hidden" name="sort" value="{m.escape(sort, quote=True)}"><input type="hidden" name="order" value="{m.escape(order, quote=True)}">'
        f'<div class="v5058c-search"><input name="q" value="{m.escape(q, quote=True)}" placeholder="Search Node Group"><span>⌕</span></div>'
        f'{_group_select(selected)}<button type="submit">Apply</button><a class="clear" href="{m.escape(reset_href, quote=True)}">Reset</a></form>'
        '<div class="v5058c-table-wrap table-wrap"><table class="v5058c-table v5058c-node-table"><thead><tr>'
        f'<th>{sort_link("NODE GROUP", "group")}</th><th>{sort_link("NODES", "nodes")}</th><th>{sort_link("VMS", "vms")}</th>'
        f'<th>{sort_link("RX", "rx")}</th><th>{sort_link("TX", "tx")}</th><th>{sort_link("TOTAL", "total")}</th>'
        f'<th>{sort_link("PHYSICAL", "physical")}</th><th>{sort_link("VM", "vm")}</th>'
        f'</tr></thead><tbody>{body_html}</tbody></table></div></div>'
    )
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
    m = _m()
    gid = selected_group_id()
    clause, params = _active_membership_clause("a.node", gid, "avis")
    conn = m.db()
    try:
        return [str(r[0]) for r in conn.execute(f"""SELECT DISTINCT a.node
          FROM vm_abuse_state a LEFT JOIN node_inventory ni ON ni.node=a.node
          WHERE {clause} AND a.last_seen>=?
            AND (ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))
          ORDER BY a.node COLLATE NOCASE""", params + [m.now_ts()-7*86400]).fetchall()]
    finally:
        conn.close()



def _v48127_event_where(values):
    where, params = _BASE["abuse_event_where"](values)
    gid = _clean_group_id(values.get("group"))
    clause, group_params = _active_membership_clause("i.node", gid, "aevt")
    where.append(clause)
    params.extend(group_params)
    return where, params



def _v48139_current_rows(values):
    gid = _clean_group_id(values.get("group"))
    m = _m()
    cfg = m.get_abuse_settings()
    group_clause, group_params = _active_membership_clause("a.node", gid, "acur")
    where = [
        "a.is_abuse=1",
        "a.last_seen>=?",
        "a.policy_revision=?",
        "a.engine_version=?",
        m._v48126_visible_sql("ni", "vi"),
        m._v48126_type_condition("a", values["type"]),
        "a.severity>=?",
        group_clause,
    ]
    params = [
        m.now_ts() - m.FAST_CURRENT_STALE_SECONDS,
        cfg["revision"],
        m.ABUSE_ENGINE_VERSION,
        values["min_severity"],
    ] + group_params
    if values["node"]:
        where.append("a.node=?")
        params.append(values["node"])
    if values["q"]:
        pattern = m.like_pattern(values["q"])
        where.append("(a.node LIKE ? OR a.vm_uuid LIKE ? OR a.abuse_flags LIKE ?)")
        params.extend([pattern, pattern, pattern])

    sort = values.get("sort") or "severity"
    order = values.get("order") or "desc"
    sort_map = {
        "node": "a.node COLLATE NOCASE",
        "uuid": "a.vm_uuid COLLATE NOCASE",
        "type": "a.abuse_flags COLLATE NOCASE",
        "severity": "a.severity",
        "rx_mbps": "COALESCE(a.rx_mbps,0)",
        "tx_mbps": "COALESCE(a.tx_mbps,0)",
        "rx_peak": "COALESCE(a.rx_peak_pps,0)",
        "tx_peak": "COALESCE(a.tx_peak_pps,0)",
        "cpu": "COALESCE(a.cpu_full_percent,0)",
        "cpucore": "COALESCE(a.cpu_core_percent,0)",
        "ram": "COALESCE(a.ram_guest_used_percent,-1)",
        "ramused": "CASE WHEN COALESCE(a.ram_guest_used_percent,-1)>=0 THEN MAX(0,COALESCE(a.ram_available_kib,0)-COALESCE(a.ram_usable_kib,0)) ELSE -1 END",
        "ramrss": "COALESCE(a.ram_rss_kib,0)",
        "ramassigned": "COALESCE(a.ram_current_kib,0)",
        "diskallocated": "COALESCE(ds.allocated_bytes,0)",
        "diskassigned": "COALESCE(ds.assigned_bytes,0)",
        "diskallocpct": "COALESCE(ds.allocation_ratio,-1)",
        "diskslots": "COALESCE(ds.disk_count,0)",
        "diskr": "COALESCE(a.disk_read_bps,0)",
        "diskw": "COALESCE(a.disk_write_bps,0)",
        "readiops": "COALESCE(a.disk_read_iops,0)",
        "writeiops": "COALESCE(a.disk_write_iops,0)",
        "last_seen": "a.last_seen",
    }
    if sort == "duration":
        order_sql = f"a.abuse_since {'ASC' if order == 'desc' else 'DESC'}"
    else:
        order_sql = f"{sort_map.get(sort, sort_map['severity'])} {'ASC' if order == 'asc' else 'DESC'}"

    where_sql = " AND ".join(where)
    offset = (values["page"] - 1) * values["limit"]
    conn = m.db()
    try:
        changed = m._v48140_reconcile_summaries_if_needed(conn)
        if changed:
            conn.commit()
        total = m.safe_int(
            conn.execute(
                f"SELECT COUNT(*) FROM vm_abuse_state a "
                "LEFT JOIN node_inventory ni ON ni.node=a.node "
                "LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid "
                f"WHERE {where_sql}",
                params,
            ).fetchone()[0],
            0,
        )
        rows = conn.execute(
            f"""SELECT a.node,a.vm_uuid,a.abuse_since,a.last_seen,a.abuse_flags,a.severity,a.rx_mbps,a.tx_mbps,a.rx_pps,a.tx_pps,a.rx_peak_pps,a.tx_peak_pps,a.seconds_over_rx_pps,a.seconds_over_tx_pps,
              COALESCE(a.network_rx_mbps_streak_seconds,0),COALESCE(a.network_tx_mbps_streak_seconds,0),a.cpu_full_percent,a.cpu_core_percent,a.vcpu_current,a.cpu_streak_seconds,a.ram_rss_percent,a.ram_guest_used_percent,a.ram_usable_percent,a.ram_streak_seconds,
              a.ram_current_kib,a.ram_rss_kib,a.ram_available_kib,a.ram_usable_kib,a.disk_read_bps,a.disk_write_bps,a.disk_read_iops,a.disk_write_iops,a.disk_streak_seconds,COALESCE(b.primary_ipv4,''),COALESCE(ds.allocated_bytes,0),COALESCE(ds.assigned_bytes,0),COALESCE(ds.disk_count,0)
              FROM vm_abuse_state a LEFT JOIN node_inventory ni ON ni.node=a.node LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid LEFT JOIN node_bridge_addresses_latest b ON b.node=a.node AND b.bridge=? LEFT JOIN vm_disk_summary_current ds ON ds.node=a.node AND ds.vm_uuid=a.vm_uuid
              WHERE {where_sql} ORDER BY {order_sql},a.node COLLATE NOCASE,a.vm_uuid COLLATE NOCASE LIMIT ? OFFSET ?""",
            [m.PUBLIC_BRIDGE] + params + [values["limit"], offset],
        ).fetchall()
        counts = {}
        for key in ("network", "cpu", "ram", "disk"):
            count_clause, count_group_params = _active_membership_clause(
                "a.node", gid, f"acnt_{key}"
            )
            count_params = [
                m.now_ts() - m.FAST_CURRENT_STALE_SECONDS,
                cfg["revision"],
                m.ABUSE_ENGINE_VERSION,
            ] + count_group_params
            counts[key] = m.safe_int(
                conn.execute(
                    f"""SELECT COUNT(*) FROM vm_abuse_state a
                      LEFT JOIN node_inventory ni ON ni.node=a.node
                      LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
                      WHERE a.is_abuse=1 AND a.last_seen>=? AND a.policy_revision=? AND a.engine_version=?
                        AND {m._v48126_visible_sql('ni','vi')}
                        AND {m._v48126_type_condition('a', key)}
                        AND {count_clause}""",
                    count_params,
                ).fetchone()[0],
                0,
            )
        return rows, total, counts
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# r6 Node Groups monitoring, flag decoration and bulk management
# ---------------------------------------------------------------------------

def _groups_for_node_links(nodes):
    return _groups_for_nodes(nodes)


def _inject_node_flags(text: str) -> str:
    m = _m()
    matches = list(re.finditer(r'<a(?P<attrs>[^>]*?)href="(?P<href>[^"]*/node/(?P<node>[^/?#\"]+)[^"]*)"(?P<tail>[^>]*)>(?P<label>.*?)</a>', text, flags=re.I | re.S))
    if not matches:
        return text
    from urllib.parse import unquote
    nodes = [unquote(match.group('node')) for match in matches]
    mapping = _groups_for_node_links(nodes)
    pieces=[]; pos=0
    for match in matches:
        pieces.append(text[pos:match.start()])
        node=unquote(match.group('node'))
        name,country=mapping.get(node,(SYSTEM_GROUP_NAME,''))
        label=match.group('label')
        if 'node-group-flag' not in label:
            label=flag_html(country)+label
        pieces.append('<a%s href="%s"%s>%s</a>' % (match.group('attrs'),match.group('href'),match.group('tail'),label))
        pos=match.end()
    pieces.append(text[pos:])
    return ''.join(pieces)


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
        pattern = "%" + q.replace("%", "\\%").replace("_", "\\_") + "%"
        conn = m.db()
        try:
            matched = {int(r[0]) for r in conn.execute("""
                SELECT DISTINCT g.id
                  FROM node_groups g
                  LEFT JOIN node_group_memberships gm ON gm.group_id=g.id
                  LEFT JOIN node_inventory ni ON ni.node=gm.node
                  LEFT JOIN node_bridge_addresses_latest ba ON ba.node=ni.node
                 WHERE g.is_active=1 AND (
                       LOWER(g.name) LIKE ? OR LOWER(COALESCE(g.description,'')) LIKE ?
                       OR LOWER(COALESCE(g.country_code,'')) LIKE ? OR LOWER(COALESCE(ni.node,'')) LIKE ?
                       OR LOWER(COALESCE(ba.primary_ipv4,'')) LIKE ? OR LOWER(COALESCE(ba.ipv4_json,'[]')) LIKE ?)
            """, (pattern, pattern, pattern, pattern, pattern, pattern)).fetchall()}
        finally:
            conn.close()
        rows = [row for row in rows if row["id"] in matched]
    if status:
        rows = [row for row in rows if row["status"] == status]
    if abuse == "yes": rows = [row for row in rows if row["abuse_count"] > 0]
    if abuse == "no": rows = [row for row in rows if row["abuse_count"] == 0]
    if online == "online": rows = [row for row in rows if row["status"] not in {"offline", "unknown", "empty"}]
    if online == "offline": rows = [row for row in rows if row["status"] == "offline"]
    sort = str(m.request.args.get("sort") or "status").strip().lower()
    order = str(m.request.args.get("order") or "asc").strip().lower()
    if sort not in {"name", "nodes", "vms", "abuse", "updated", "status"}: sort = "status"
    if order not in {"asc", "desc"}: order = "asc"
    descending = order == "desc"
    rows.sort(key=lambda row: row["name"].lower())
    if sort == "name": rows.sort(key=lambda row: row["name"].lower(), reverse=descending)
    elif sort == "updated":
        available=[r for r in rows if int(r["last_update"] or 0)>0]; missing=[r for r in rows if int(r["last_update"] or 0)<=0]
        available.sort(key=lambda r:int(r["last_update"]),reverse=descending); rows=available+missing
    else:
        key={"nodes":lambda r:int(r["node_count"]),"vms":lambda r:int(r["vm_count"]),"abuse":lambda r:int(r["abuse_count"]),"status":lambda r:_status_rank(r["status"])}[sort]
        rows.sort(key=key,reverse=descending)
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
const key='virtinfra-node-groups-r6';
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
document.addEventListener('DOMContentLoaded',()=>{init();setInterval(refresh,30000);});
})();</script>'''
    css='''<style>.node-group-list{display:grid;gap:8px}.node-group-monitor{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}.node-group-monitor>summary{display:grid;grid-template-columns:18px minmax(180px,1fr) repeat(3,minmax(86px,auto)) minmax(110px,auto) minmax(82px,auto);gap:10px;align-items:center;padding:11px 13px;cursor:pointer;list-style:none}.node-group-monitor>summary::-webkit-details-marker{display:none}.node-group-monitor[open] .ng-chevron{transform:rotate(90deg)}.ng-chevron{transition:transform .15s}.ng-name{display:flex;align-items:center;min-width:0}.ng-abuse{font-weight:800}.node-group-detail{border-top:1px solid var(--line);padding:10px}.node-group-detail table{min-width:1180px}.node-group-filters{margin:12px 0}.node-group-filters input{min-width:145px}@media(max-width:900px){.node-group-monitor>summary{grid-template-columns:18px 1fr auto}.ng-num,.ng-update{display:none}}</style>'''
    return m.page('Node Groups',css+header+'<div id="node-group-list" class="node-group-list">'+_group_summary_html(rows)+'</div>'+script)


def node_groups_summary():
    m=_m(); deny=m.require_dashboard()
    if deny:return deny
    return m.Response(_group_summary_html(_filtered_sorted_group_summaries()),mimetype='text/html')


def _node_group_detail_rows(group_id: int):
    m = _m()
    cfg = m.get_abuse_settings()
    stale = _ts() - m.FAST_CURRENT_STALE_SECONDS
    q = str(m.request.args.get('q') or '').strip().lower()
    params = [stale, cfg['revision'], m.ABUSE_ENGINE_VERSION, group_id]
    search = ''
    if q:
        pattern = '%' + q.replace('%','\\%').replace('_','\\_') + '%'
        search = """ AND (LOWER(ni.node) LIKE ? OR EXISTS (
            SELECT 1 FROM node_bridge_addresses_latest ba WHERE ba.node=ni.node
              AND (LOWER(COALESCE(ba.primary_ipv4,'')) LIKE ? OR LOWER(COALESCE(ba.ipv4_json,'[]')) LIKE ?)))"""
        params.extend([pattern, pattern, pattern])
    conn = m.db()
    try:
        return conn.execute("""WITH vm_counts AS (
            SELECT vi.node,COUNT(*) vm_count FROM vm_inventory vi JOIN node_inventory ni2 ON ni2.node=vi.node
             WHERE COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL
               AND COALESCE(ni2.status,'active')!='hidden' AND ni2.deleted_at IS NULL GROUP BY vi.node),
        abuse_counts AS (
            SELECT a.node,COUNT(DISTINCT a.vm_uuid) abuse_count FROM vm_abuse_state a
            JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
             WHERE a.is_abuse=1 AND a.last_seen>=? AND a.policy_revision=? AND a.engine_version=?
               AND COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL GROUP BY a.node)
        SELECT ni.node,COALESCE(v.vm_count,0),ncf.load1,ncf.load5,ncf.load15,ncf.cpu_percent,
               ncf.mem_used,ncf.mem_total,ncf.disk_read_bps,ncf.disk_write_bps,COALESCE(a.abuse_count,0),
               COALESCE(ncf.last_seen,ni.last_push,0),g.name,g.country_code
          FROM node_group_memberships gm JOIN node_groups g ON g.id=gm.group_id
          JOIN node_inventory ni ON ni.node=gm.node LEFT JOIN node_current_fast ncf ON ncf.node=ni.node
          LEFT JOIN vm_counts v ON v.node=ni.node LEFT JOIN abuse_counts a ON a.node=ni.node
         WHERE gm.group_id=? AND g.is_active=1 AND COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL""" + search, params).fetchall()
    finally:
        conn.close()



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
        node,vmc,l1,l5,l15,cpu,mu,mt,rb,wb,abuse,last,name,country=r
        status=m.health_state(int(last or 0)) if int(last or 0)>0 else 'unknown'
        if status == 'down':
            status = 'offline'
        abuse_href=m.url_for('vm_abuse_page',group=group_id,node=node)
        load='N/A' if l1 is None else f'{float(l1):.1f} / {float(l5 or 0):.1f} / {float(l15 or 0):.1f}'
        if mt is None or int(mt or 0) <= 0:
            ram_html = 'N/A'
        else:
            ram_pct = max(0.0, min(100.0, float(mu or 0) * 100.0 / float(mt)))
            ram_html = m.metric_pill(
                m.human(int(mu or 0)) + ' / ' + m.human(int(mt or 0)),
                m.metric_level(ram_pct, 80, 90),
                f'Host RAM used {ram_pct:.1f}% · warning >=80%, critical >=90%',
            )
        body.append(f'''<tr><td>{flag_html(country)}<a href="{m.url_for('node_page',node=node)}"><b>{m.escape(node)}</b></a></td><td class="num">{int(vmc or 0):,}</td><td class="num">{load}</td><td class="num">{'N/A' if cpu is None else f'{float(cpu):.1f}%'}</td><td class="num">{ram_html}</td><td class="num">{'N/A' if rb is None else m._disk_io_rate(float(rb or 0))}</td><td class="num">{'N/A' if wb is None else m._disk_io_rate(float(wb or 0))}</td><td class="num"><a href="{m.escape(abuse_href,quote=True)}" onclick="event.stopPropagation()">{int(abuse or 0):,}</a></td><td title="{m.escape(m.fmt_full(last),quote=True) if last else 'Never'}">{_relative_update(last)}</td><td><span class="vm-state {m.escape(status)}">{m.escape(status.upper())}</span></td></tr>''')
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
    if action in {'remove_group','move_ungrouped'}:target=system_group_id()
    if action=='move_all_ungrouped':
        source=m.safe_int(m.request.form.get('source_group_id'),0); row=group_row(source)
        if not row or row[5]:return m.Response('Invalid source group\n',status=400,mimetype='text/plain')
        target=system_group_id()
        nodes=sorted(group_nodes(source))
    elif scope=='matching':nodes=_matching_admin_nodes()
    else:nodes=list(dict.fromkeys(str(x or '').strip() for x in m.request.form.getlist('nodes') if str(x or '').strip()))
    if not nodes:return m.Response('Select at least one node\n',status=400,mimetype='text/plain')
    if target<=0:return m.Response('Select a Node Group\n',status=400,mimetype='text/plain')
    result=assign_nodes(nodes,target,_actor())
    return m.redirect(m.url_for('admin_page',section='groups' if action=='move_all_ungrouped' else 'nodes',dbmsg=f"Updated {result['changed']} node membership(s)."))



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
        "admin_page_view":app.view_functions["admin_page"],
        "admin_nodes_query":module._v48134_admin_nodes,"admin_vms_query":module._v48134_admin_vms,
        "admin_nodes_section":module._v48134_admin_nodes_section,"admin_vms_section":module._v48134_admin_vms_section,
        "admin_pager":module._v48134_admin_pager,
        "get_node_rows":module.get_node_rows,"get_node_health_rows":module.get_node_health_rows,"get_top_vm_rows":module.get_top_vm_rows,
        "index_view":app.view_functions["index"],"top_view":app.view_functions["top_page"],"node_health_view":app.view_functions["node_health_page"],
        "admin_bulk_nodes":app.view_functions["admin_bulk_nodes"],
        "admin_users_page_view":app.view_functions["admin_users_page"],"admin_user_action_view":app.view_functions["admin_user_action"],
        "admin_change_password_view":app.view_functions["admin_change_password"],
        "storage_params":module._storage_io_params,"storage_disk_clause":module._v48140_disk_search_clause,"storage_target":module._v48137_storage_target,
        "storage_payload_rows":module._v48137_snapshot_payload_rows,"storage_filter_options":module._v48137_storage_filter_options,"storage_node_cards":module._v48140_node_group_cards_fast,
        "storage_view":app.view_functions["storage_io_page"],
        "consumption_common_args":module._v5058c_common_args,"consumption_visible_nodes":module._v5058c_visible_nodes,"consumption_vm_rows":module._v5058c_vm_rows,"consumption_node_rows":module._v5058c_node_rows,
        "consumption_vm_totals":module._v5058c_vm_totals,"consumption_node_totals":module._v5058c_node_totals,"consumption_view":app.view_functions["bandwidth_consumption_page"],
        "abuse_filter_values":module._v48128_filter_values,"abuse_filter_form":module._v48128_filter_form,"abuse_visible_nodes":module._v48126_visible_nodes,"abuse_event_where":module._v48127_event_where,"abuse_current_rows":module._v48139_current_rows,
    })
    ensure_schema()
    replacements={
        "page":page,"url_for":url_for,"_v490_admin_nav":admin_nav,"clean_role":clean_role,"dashboard_role":dashboard_role,"admin_allowed":admin_allowed,"require_admin":require_admin,
        "_v48134_admin_nodes":_filtered_admin_nodes,"_v48134_admin_vms":_filtered_admin_vms,
        "_v48134_admin_nodes_section":admin_nodes_section,"_v48134_admin_vms_section":admin_vms_section,"_v48134_admin_pager":admin_pager,
        "active_admin_count":active_admin_count,"emergency_admin_needed":emergency_admin_needed,"is_last_enabled_admin":is_last_enabled_admin,"set_admin_credentials":set_admin_credentials,"bootstrap_dashboard_admin_from_settings":bootstrap_dashboard_admin_from_settings,
        "get_node_rows":get_node_rows,"get_node_health_rows":get_node_health_rows,"get_top_vm_rows":get_top_vm_rows,
        "_storage_io_params":_storage_io_params,"_v48140_disk_search_clause":_v48140_disk_search_clause,"_v48137_storage_target":_v48137_storage_target,"_v48137_snapshot_payload_rows":_v48137_snapshot_payload_rows,"_v48137_storage_filter_options":_v48137_storage_filter_options,"_v48140_node_group_cards_fast":_v48140_node_group_cards_fast,"_v48137_storage_node_group_cards":_v48140_node_group_cards_fast,
        "_v5058c_common_args":_v5058c_common_args,"_v5058c_visible_nodes":_v5058c_visible_nodes,"_v5058c_vm_rows":_v5058c_vm_rows,"_v5058c_node_rows":_v5058c_node_rows,"_v5058c_vm_totals":_v5058c_vm_totals,"_v5058c_node_totals":_v5058c_node_totals,
        "_v48128_filter_values":_v48128_filter_values,"_v48128_filter_form":_v48128_filter_form,"_v48126_visible_nodes":_v48126_visible_nodes,"_v48127_event_where":_v48127_event_where,"_v48139_current_rows":_v48139_current_rows,
    }
    for name,value in replacements.items():setattr(module,name,value)
    view_replacements={"index":index,"top_page":top_page,"node_health_page":node_health_page,"storage_io_page":storage_io_page,"bandwidth_consumption_page":bandwidth_consumption_page,"admin_page":admin_page,"admin_users_page":admin_users_page,"admin_create_user":admin_create_user,"admin_user_action":admin_user_action,"admin_change_password":admin_change_password,"admin_bulk_nodes":admin_bulk_nodes,"dashboard_login":dashboard_login,"admin_login":admin_login,"admin_setup":admin_setup}
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
