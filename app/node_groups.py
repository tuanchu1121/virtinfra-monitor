"""VirtInfra Monitor 50.6.0 Node Groups and local country flags.

This module is installed after the legacy single-file application has finished
registering its effective routes. It adds isolated PostgreSQL tables, Admin CRUD,
Node-name membership management, shared flag rendering and Group-aware views
without changing the Agent payload or existing API responses.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import unquote

from flask import request, redirect, url_for

_RELEASE = "50.6.0-prod-r1-node-groups-country-flags"
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_NODE_LINK_RE = re.compile(r'(<a\b[^>]*href=["\'](?:https?://[^/]+)?/node/([^"\'?#]+)[^"\']*["\'][^>]*>)(.*?)(</a>)', re.I | re.S)


def install(m):
    app = m.app
    root = Path(m.__file__).resolve().parent
    flags_dir = root / "static" / "flags" / "4x3"
    state = {"schema": False, "map_at": 0.0, "map": {}}

    def db():
        conn = m.db()
        if not state["schema"]:
            ensure_schema(conn)
            state["schema"] = True
        return conn

    def ensure_schema(conn):
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS node_groups (
          id BIGSERIAL PRIMARY KEY,
          name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          country_code VARCHAR(2),
          enabled BOOLEAN NOT NULL DEFAULT TRUE,
          hidden BOOLEAN NOT NULL DEFAULT FALSE,
          is_default BOOLEAN NOT NULL DEFAULT FALSE,
          created_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL,
          CONSTRAINT node_groups_country_code_check
            CHECK(country_code IS NULL OR country_code ~ '^[A-Z]{2}$')
        );
        CREATE UNIQUE INDEX IF NOT EXISTS node_groups_name_unique
          ON node_groups(LOWER(BTRIM(name)));
        CREATE UNIQUE INDEX IF NOT EXISTS node_groups_single_default
          ON node_groups(is_default) WHERE is_default=TRUE;
        CREATE TABLE IF NOT EXISTS node_group_memberships (
          node_name TEXT PRIMARY KEY,
          group_id BIGINT NOT NULL REFERENCES node_groups(id) ON DELETE CASCADE,
          assigned_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS node_group_memberships_group_idx
          ON node_group_memberships(group_id);
        CREATE TABLE IF NOT EXISTS node_group_membership_history (
          id BIGSERIAL PRIMARY KEY,
          node_name TEXT NOT NULL,
          group_id BIGINT REFERENCES node_groups(id) ON DELETE SET NULL,
          valid_from BIGINT NOT NULL,
          valid_to BIGINT,
          changed_at BIGINT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS node_group_history_lookup_idx
          ON node_group_membership_history(node_name,valid_from,valid_to);
        """)
        conn.commit()

    def invalidate():
        state["map_at"] = 0.0
        state["map"] = {}
        for fn in (getattr(m, "_v48140_cache_clear", None), getattr(m, "admin_clear_live_cache", None)):
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass

    def normalize_country(raw):
        code = str(raw or "").strip().upper()
        if not code:
            return None
        if not _COUNTRY_RE.fullmatch(code):
            raise ValueError("Country code must be exactly two letters, for example JP, US or SG.")
        return code

    def group_rows(include_hidden=True):
        conn = db()
        try:
            where = "" if include_hidden else "WHERE g.hidden=FALSE"
            return conn.execute(f"""
              SELECT g.id,g.name,g.description,g.country_code,g.enabled,g.hidden,g.is_default,
                     COUNT(m.node_name)::bigint
                FROM node_groups g
                LEFT JOIN node_group_memberships m ON m.group_id=g.id
                {where}
               GROUP BY g.id,g.name,g.description,g.country_code,g.enabled,g.hidden,g.is_default
               ORDER BY g.is_default DESC,LOWER(g.name)
            """).fetchall()
        finally:
            conn.close()

    def current_map(force=False):
        if not force and state["map"] and time.time() - state["map_at"] < 30:
            return state["map"]
        conn = None
        try:
            conn = db()
            rows = conn.execute("""
              SELECT m.node_name,g.id,g.name,g.description,g.country_code,g.enabled,g.hidden,g.is_default
                FROM node_group_memberships m JOIN node_groups g ON g.id=m.group_id
            """).fetchall()
            data = {}
            for r in rows:
                data[str(r[0])] = {
                    "id": int(r[1]), "name": str(r[2]), "description": str(r[3] or ""),
                    "country_code": str(r[4] or ""), "enabled": bool(r[5]),
                    "hidden": bool(r[6]), "is_default": bool(r[7]),
                }
            state["map"], state["map_at"] = data, time.time()
            return data
        except Exception:
            return {}
        finally:
            if conn is not None:
                conn.close()

    def flag_html(node_name, show_group=False):
        info = current_map().get(str(node_name))
        code = (info or {}).get("country_code", "").upper()
        if code and _COUNTRY_RE.fullmatch(code) and (flags_dir / f"{code.lower()}.svg").is_file():
            flag = f'<img class="node-country-flag" src="/static/flags/4x3/{code.lower()}.svg" alt="{code}" loading="lazy">'
        else:
            flag = '<span class="node-country-fallback" aria-hidden="true">🌐</span>'
        suffix = f'<small class="node-group-name">{html.escape(info["name"])}</small>' if show_group and info else ""
        return f'<span class="node-identity" data-node-name="{html.escape(str(node_name), quote=True)}">{flag}<span class="node-identity-text">{html.escape(str(node_name))}{suffix}</span></span>'

    def require_admin_post():
        deny = m.require_admin()
        if deny:
            return deny
        return None

    def audit(action, node_name="", old_group="", new_group="", detail=""):
        try:
            m.audit_log(action, detail or f"node={node_name} old={old_group} new={new_group}")
        except Exception:
            pass

    def assign_node(conn, node_name, group_id):
        node_name = str(node_name or "").strip()
        if not node_name:
            raise ValueError("Node name is required.")
        exists = conn.execute("SELECT 1 FROM node_inventory WHERE node=?", (node_name,)).fetchone()
        if not exists:
            raise ValueError("Node name does not exist in current inventory.")
        group = conn.execute("SELECT id,name,enabled FROM node_groups WHERE id=?", (group_id,)).fetchone()
        if not group:
            raise ValueError("Group does not exist.")
        if not bool(group[2]):
            raise ValueError("Disabled Group cannot receive new Node assignments.")
        now = int(time.time())
        old = conn.execute("""SELECT m.group_id,g.name FROM node_group_memberships m
                              JOIN node_groups g ON g.id=m.group_id WHERE m.node_name=?""", (node_name,)).fetchone()
        if old and int(old[0]) == int(group_id):
            return str(old[1]), str(group[1])
        conn.execute("UPDATE node_group_membership_history SET valid_to=?,changed_at=? WHERE node_name=? AND valid_to IS NULL", (now, now, node_name))
        conn.execute("""INSERT INTO node_group_memberships(node_name,group_id,assigned_at,updated_at)
                        VALUES(?,?,?,?) ON CONFLICT(node_name) DO UPDATE SET group_id=excluded.group_id,updated_at=excluded.updated_at""",
                     (node_name, group_id, now, now))
        conn.execute("INSERT INTO node_group_membership_history(node_name,group_id,valid_from,valid_to,changed_at) VALUES(?,?,?,NULL,?)",
                     (node_name, group_id, now, now))
        return str(old[1]) if old else "Ungrouped", str(group[1])

    def remove_node(conn, node_name):
        node_name = str(node_name or "").strip()
        now = int(time.time())
        old = conn.execute("""SELECT g.name FROM node_group_memberships m JOIN node_groups g ON g.id=m.group_id
                              WHERE m.node_name=?""", (node_name,)).fetchone()
        conn.execute("UPDATE node_group_membership_history SET valid_to=?,changed_at=? WHERE node_name=? AND valid_to IS NULL", (now, now, node_name))
        conn.execute("DELETE FROM node_group_memberships WHERE node_name=?", (node_name,))
        return str(old[0]) if old else "Ungrouped"

    def group_options(selected="", include_ungrouped=True):
        out = ['<option value="">All Groups</option>']
        if include_ungrouped:
            out.append(f'<option value="ungrouped"{" selected" if selected=="ungrouped" else ""}>🌐 Ungrouped</option>')
        for r in group_rows():
            gid, name, _, code, enabled, hidden, default, _ = r
            label = f"{code or '🌐'} · {name}"
            state_label = " [disabled]" if not enabled else (" [hidden]" if hidden else "")
            out.append(f'<option value="{gid}"{" selected" if str(gid)==str(selected) else ""}>{html.escape(label+state_label)}</option>')
        return "".join(out)

    def admin_nav(active):
        items = (("overview", "Overview"), ("nodes", "Nodes"), ("node_groups", "Node Groups"), ("vms", "VMs"), ("maintenance", "Maintenance"))
        return '<div class="admin-tabs">' + ''.join(
            f'<a class="{"active" if active==key else ""}" href="{url_for("admin_page",section=key)}">{label}</a>'
            for key, label in items
        ) + '</div>'

    def groups_section(message="", error=""):
        cards = []
        for r in group_rows():
            gid, name, desc, code, enabled, hidden, default, count = r
            nodes = []
            conn = db()
            try:
                nodes = conn.execute("SELECT node_name FROM node_group_memberships WHERE group_id=? ORDER BY LOWER(node_name)", (gid,)).fetchall()
            finally:
                conn.close()
            node_list = ', '.join(html.escape(str(x[0])) for x in nodes[:30]) or 'No Nodes assigned'
            if len(nodes) > 30:
                node_list += f" … +{len(nodes)-30}"
            cards.append(f'''
            <div class="card ng-card"><div class="ng-head"><div>{flag_html("",False) if False else ""}<h3>{html.escape(name)}</h3><p>{html.escape(desc or "No description")}</p></div><div class="ng-badges"><span>{html.escape(code or "Global")}</span><span>{count} Nodes</span>{'<span>Default</span>' if default else ''}{'<span>Disabled</span>' if not enabled else ''}{'<span>Hidden</span>' if hidden else ''}</div></div>
              <form class="ng-form" method="post" action="{url_for('node_group_update_v5060')}"><input type="hidden" name="csrf_token" value="{html.escape(m.csrf_token(),quote=True)}"><input type="hidden" name="group_id" value="{gid}"><label>Name<input name="name" required value="{html.escape(name,quote=True)}"></label><label>Description<input name="description" value="{html.escape(desc or '',quote=True)}"></label><label>Country code<input name="country_code" maxlength="2" value="{html.escape(code or '',quote=True)}" placeholder="JP"></label><label class="ng-check"><input type="checkbox" name="enabled" value="1"{' checked' if enabled else ''}> Enabled</label><label class="ng-check"><input type="checkbox" name="hidden" value="1"{' checked' if hidden else ''}> Hidden</label><label class="ng-check"><input type="checkbox" name="is_default" value="1"{' checked' if default else ''}> Default</label><button>Save</button></form>
              <div class="ng-node-list"><b>Nodes:</b> {node_list}</div>
              <form method="post" action="{url_for('node_group_delete_v5060')}" onsubmit="return confirm('Delete this Group? Nodes will become Ungrouped.')"><input type="hidden" name="csrf_token" value="{html.escape(m.csrf_token(),quote=True)}"><input type="hidden" name="group_id" value="{gid}"><button class="btn-danger">Delete Group</button></form>
            </div>''')
        notice = (f'<div class="notice success">{html.escape(message)}</div>' if message else '') + (f'<div class="notice error">{html.escape(error)}</div>' if error else '')
        return f'''{notice}<div class="card"><div class="section-head"><div><h3>Create Node Group</h3><p>Membership uses the exact Node name. Country is stored as an ISO two-letter code.</p></div></div><form class="ng-create" method="post" action="{url_for('node_group_create_v5060')}"><input type="hidden" name="csrf_token" value="{html.escape(m.csrf_token(),quote=True)}"><label>Name<input name="name" required></label><label>Description<input name="description"></label><label>Country code<input name="country_code" maxlength="2" placeholder="JP"></label><label class="ng-check"><input type="checkbox" name="enabled" value="1" checked> Enabled</label><label class="ng-check"><input type="checkbox" name="hidden" value="1"> Hidden</label><label class="ng-check"><input type="checkbox" name="is_default" value="1"> Default</label><button>Create Group</button></form></div>{''.join(cards) or '<div class="card empty">No Node Groups yet.</div>'}'''

    def nodes_section(q, status, page_no, per_page, selected_group):
        where, params = ["1=1"], []
        if q:
            like = "%" + q + "%"
            where.append("(LOWER(ni.node) LIKE LOWER(?) OR LOWER(COALESCE(nm.node_ip,'')) LIKE LOWER(?))")
            params += [like, like]
        if status == "hidden": where.append("(COALESCE(ni.status,'active')='hidden' OR ni.deleted_at IS NOT NULL)")
        elif status == "active": where.append("COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL")
        if selected_group == "ungrouped": where.append("ngm.node_name IS NULL")
        elif str(selected_group).isdigit(): where.append("ngm.group_id=?"); params.append(int(selected_group))
        conn = db()
        try:
            total = int(conn.execute(f"SELECT COUNT(*) FROM node_inventory ni LEFT JOIN node_meta nm ON nm.node=ni.node LEFT JOIN node_group_memberships ngm ON ngm.node_name=ni.node WHERE {' AND '.join(where)}", params).fetchone()[0])
            pages = max(1, (total + per_page - 1)//per_page); page_no=min(page_no,pages)
            rows = conn.execute(f"""SELECT ni.node,COALESCE(ni.status,'active'),ni.last_push,ni.deleted_at,COALESCE(nm.node_ip,''),ng.id,ng.name,ng.country_code
              FROM node_inventory ni LEFT JOIN node_meta nm ON nm.node=ni.node LEFT JOIN node_group_memberships ngm ON ngm.node_name=ni.node LEFT JOIN node_groups ng ON ng.id=ngm.group_id
              WHERE {' AND '.join(where)} ORDER BY LOWER(ni.node) LIMIT ? OFFSET ?""", params+[per_page,(page_no-1)*per_page]).fetchall()
        finally: conn.close()
        groups = [r for r in group_rows() if bool(r[4])]
        body=[]
        for node,row_status,last_push,deleted_at,node_ip,gid,gname,code in rows:
            selector=['<option value="">Choose Group</option>']+[f'<option value="{g[0]}">{html.escape((g[3] or "🌐")+" · "+g[1])}</option>' for g in groups]
            body.append(f'''<tr><td>{flag_html(node)}<small class="row-sub">{html.escape(node_ip or '-')}</small></td><td>{html.escape(gname or 'Ungrouped')}</td><td>{html.escape(row_status)}</td><td>{m.fmt_push(last_push)}</td><td><form class="ng-inline" method="post" action="{url_for('node_group_assign_v5060')}"><input type="hidden" name="csrf_token" value="{html.escape(m.csrf_token(),quote=True)}"><input type="hidden" name="node_name" value="{html.escape(node,quote=True)}"><select name="group_id" required>{''.join(selector)}</select><button>{'Move' if gid else 'Assign'}</button></form>{f'<form class="ng-inline" method="post" action="{url_for("node_group_remove_v5060")}"><input type="hidden" name="csrf_token" value="{html.escape(m.csrf_token(),quote=True)}"><input type="hidden" name="node_name" value="{html.escape(node,quote=True)}"><button class="clear">Remove</button></form>' if gid else ''}</td></tr>''')
        reset=url_for("admin_page",section="nodes")
        return f'''<div class="card"><div class="section-head"><div><h3>Node management</h3><p>{total:,} matching Nodes. Group assignment is based only on the exact Node name.</p></div></div><form class="search ng-filter" method="get"><input type="hidden" name="section" value="nodes"><input name="q" value="{html.escape(q,quote=True)}" placeholder="Search Node"><select name="group_id">{group_options(selected_group)}</select><select name="status">{m._v48134_status_options(status)}</select><select name="per_page"><option>{per_page}</option><option>100</option><option>200</option><option>500</option></select><button>Filter</button><a class="clear" href="{reset}">Reset</a></form><div class="table-wrap"><table class="admin-clean-table"><thead><tr><th>NODE / IP</th><th>GROUP</th><th>STATUS</th><th>LAST PUSH</th><th>GROUP ACTION</th></tr></thead><tbody>{''.join(body) or '<tr><td colspan="5" class="empty">No Nodes match</td></tr>'}</tbody></table></div></div>'''

    def vms_section(q, status, page_no, per_page, selected_group, selected_node):
        where=["1=1"]; params=[]
        if q: where.append("(LOWER(vi.vm_uuid) LIKE LOWER(?) OR LOWER(vi.node) LIKE LOWER(?))"); params += ["%"+q+"%","%"+q+"%"]
        if selected_node: where.append("vi.node=?"); params.append(selected_node)
        if selected_group=="ungrouped": where.append("ngm.node_name IS NULL")
        elif str(selected_group).isdigit(): where.append("ngm.group_id=?"); params.append(int(selected_group))
        if status=="hidden": where.append("(COALESCE(vi.status,'active')='hidden' OR vi.deleted_at IS NOT NULL)")
        elif status=="active": where.append("COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL")
        conn=db()
        try:
            total=int(conn.execute(f"SELECT COUNT(*) FROM vm_inventory vi LEFT JOIN node_group_memberships ngm ON ngm.node_name=vi.node WHERE {' AND '.join(where)}",params).fetchone()[0])
            rows=conn.execute(f"""SELECT vi.node,vi.vm_uuid,COALESCE(vi.status,'active'),vi.last_seen,ng.name,ng.country_code
              FROM vm_inventory vi LEFT JOIN node_group_memberships ngm ON ngm.node_name=vi.node LEFT JOIN node_groups ng ON ng.id=ngm.group_id
              WHERE {' AND '.join(where)} ORDER BY LOWER(vi.node),vi.last_seen DESC LIMIT ? OFFSET ?""",params+[per_page,(page_no-1)*per_page]).fetchall()
            nodes=conn.execute("SELECT node FROM node_inventory ORDER BY LOWER(node)").fetchall()
        finally: conn.close()
        node_opts=['<option value="">All Nodes</option>']+[f'<option value="{html.escape(r[0],quote=True)}"{" selected" if r[0]==selected_node else ""}>{html.escape(r[0])}</option>' for r in nodes]
        body=''.join(f'<tr><td>{flag_html(r[0])}<small class="row-sub">{html.escape(r[4] or "Ungrouped")}</small></td><td class="mono"><span class="uuid-cell">{html.escape(r[1])}<button type="button" class="copy-btn" data-copy="{html.escape(r[1],quote=True)}">⧉</button></span></td><td>{html.escape(r[2])}<small class="row-sub">{m.fmt_push(r[3])}</small></td></tr>' for r in rows)
        return f'''<div class="card"><div class="section-head"><div><h3>VM management</h3><p>{total:,} matching VMs. VM Group is inherited from its Node and cannot be assigned directly.</p></div></div><form class="search ng-filter" method="get"><input type="hidden" name="section" value="vms"><input name="q" value="{html.escape(q,quote=True)}" placeholder="Search VM UUID or Node"><select name="group_id">{group_options(selected_group)}</select><select name="node">{''.join(node_opts)}</select><select name="status">{m._v48134_status_options(status)}</select><button>Filter</button><a class="clear" href="{url_for('admin_page',section='vms')}">Reset</a></form><div class="table-wrap"><table class="admin-clean-table"><thead><tr><th>NODE / GROUP</th><th>VM UUID</th><th>STATUS / SEEN</th></tr></thead><tbody>{body or '<tr><td colspan="3" class="empty">No VMs match</td></tr>'}</tbody></table></div></div>'''

    base_admin = app.view_functions["admin_page"]
    def admin_page_v5060():
        deny=m.require_admin()
        if deny:return deny
        section=(request.args.get("section") or "overview").strip().lower()
        if section not in {"overview","nodes","node_groups","vms","maintenance"}: section="overview"
        q=(request.args.get("q") or "").strip(); status=m._v48134_clean_admin_status(request.args.get("status")); page_no=max(1,m.safe_int(request.args.get("page"),1)); per_page=max(25,min(500,m.safe_int(request.args.get("per_page"),200)))
        gid=(request.args.get("group_id") or "").strip(); node=(request.args.get("node") or "").strip()
        if section=="node_groups": section_html=groups_section((request.args.get("ngmsg") or "")[:500],(request.args.get("ngerr") or "")[:500])
        elif section=="nodes": section_html=nodes_section(q,status,page_no,per_page,gid)
        elif section=="vms": section_html=vms_section(q,status,page_no,per_page,gid,node)
        elif section=="overview": section_html=m._v490_admin_overview(m._v490_admin_stats())
        else: section_html=m._v490_live_cache_card()+m.database_maintenance_card((request.args.get('dbmsg') or '')[:700],(request.args.get('dberr') or '')[:700])
        content=f'''<div class="card admin-hero"><div><span class="eyebrow">CONTROL CENTER</span><h2>Administration</h2><p>Inventory, Node Groups and maintenance are separated into focused sections.</p></div><div class="admin-user-actions"><a class="btn" href="{url_for('index')}">Dashboard</a><a class="btn" href="{url_for('admin_logout')}">Logout</a></div></div>{admin_nav(section)}{section_html}'''
        return m.page("Admin",content)
    app.view_functions["admin_page"]=admin_page_v5060

    def redirect_ng(msg="",err=""):
        return redirect(url_for("admin_page",section="node_groups",ngmsg=msg,ngerr=err))

    def create_group():
        deny=require_admin_post()
        if deny:return deny
        try:
            name=str(request.form.get("name") or "").strip(); desc=str(request.form.get("description") or "").strip()[:1000]; code=normalize_country(request.form.get("country_code")); now=int(time.time())
            if not name: raise ValueError("Group name is required.")
            conn=db()
            try:
                if request.form.get("is_default"): conn.execute("UPDATE node_groups SET is_default=FALSE")
                conn.execute("INSERT INTO node_groups(name,description,country_code,enabled,hidden,is_default,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(name,desc,code,bool(request.form.get("enabled")),bool(request.form.get("hidden")),bool(request.form.get("is_default")),now,now)); conn.commit()
            finally: conn.close()
            invalidate(); return redirect_ng("Group created.")
        except Exception as e:return redirect_ng(err=str(e))

    def update_group():
        deny=require_admin_post()
        if deny:return deny
        try:
            gid=int(request.form.get("group_id") or 0); name=str(request.form.get("name") or "").strip(); code=normalize_country(request.form.get("country_code")); now=int(time.time())
            if not gid or not name: raise ValueError("Group and name are required.")
            conn=db()
            try:
                if request.form.get("is_default"): conn.execute("UPDATE node_groups SET is_default=FALSE WHERE id<>?",(gid,))
                conn.execute("UPDATE node_groups SET name=?,description=?,country_code=?,enabled=?,hidden=?,is_default=?,updated_at=? WHERE id=?",(name,str(request.form.get("description") or "").strip()[:1000],code,bool(request.form.get("enabled")),bool(request.form.get("hidden")),bool(request.form.get("is_default")),now,gid)); conn.commit()
            finally:conn.close()
            invalidate(); return redirect_ng("Group saved.")
        except Exception as e:return redirect_ng(err=str(e))

    def delete_group():
        deny=require_admin_post()
        if deny:return deny
        try:
            gid=int(request.form.get("group_id") or 0); conn=db()
            try: conn.execute("DELETE FROM node_groups WHERE id=?",(gid,)); conn.commit()
            finally:conn.close()
            invalidate(); return redirect_ng("Group deleted; Nodes are now Ungrouped.")
        except Exception as e:return redirect_ng(err=str(e))

    def assign_route():
        deny=require_admin_post()
        if deny:return deny
        try:
            node=str(request.form.get("node_name") or "").strip(); gid=int(request.form.get("group_id") or 0); conn=db()
            try: old,new=assign_node(conn,node,gid); conn.commit()
            finally:conn.close()
            audit("node_group_assign",node,old,new); invalidate(); return redirect(url_for("admin_page",section="nodes",ngmsg=f"{node}: {old} → {new}"))
        except Exception as e:return redirect(url_for("admin_page",section="nodes",ngerr=str(e)))

    def remove_route():
        deny=require_admin_post()
        if deny:return deny
        try:
            node=str(request.form.get("node_name") or "").strip(); conn=db()
            try: old=remove_node(conn,node); conn.commit()
            finally:conn.close()
            audit("node_group_remove",node,old,"Ungrouped"); invalidate(); return redirect(url_for("admin_page",section="nodes"))
        except Exception as e:return redirect(url_for("admin_page",section="nodes",ngerr=str(e)))

    app.add_url_rule("/admin/node-groups/create","node_group_create_v5060",create_group,methods=["POST"])
    app.add_url_rule("/admin/node-groups/update","node_group_update_v5060",update_group,methods=["POST"])
    app.add_url_rule("/admin/node-groups/delete","node_group_delete_v5060",delete_group,methods=["POST"])
    app.add_url_rule("/admin/nodes/group-assign","node_group_assign_v5060",assign_route,methods=["POST"])
    app.add_url_rule("/admin/nodes/group-remove","node_group_remove_v5060",remove_route,methods=["POST"])

    @app.after_request
    def node_group_html_enrichment(response):
        ctype=response.headers.get("Content-Type","")
        if response.status_code!=200 or "text/html" not in ctype:return response
        try: text=response.get_data(as_text=True)
        except Exception:return response
        current_map()
        def repl(match):
            node=unquote(match.group(2)).strip("/")
            if not node:return match.group(0)
            return match.group(1)+flag_html(node)+match.group(4)
        text=_NODE_LINK_RE.sub(repl,text)
        style='''<style id="v5060-node-groups-css">.node-identity{display:inline-flex;align-items:center;gap:6px;min-width:0;vertical-align:middle}.node-country-flag{width:16px;height:12px;flex:0 0 16px;object-fit:cover;border-radius:2px;box-shadow:0 0 0 1px rgba(0,0,0,.12)}.node-country-fallback{display:inline-flex;width:16px;height:12px;align-items:center;justify-content:center;font-size:12px;line-height:12px}.node-identity-text{min-width:0}.node-group-name{display:block;color:var(--muted,#667085);font-size:10px;margin-top:2px}.ng-create,.ng-form{display:grid;grid-template-columns:minmax(150px,1fr) minmax(220px,2fr) 110px repeat(3,auto) auto;gap:10px;align-items:end}.ng-create label,.ng-form label{display:grid;gap:5px;font-size:11px}.ng-check{display:flex!important;align-items:center;gap:6px;padding-bottom:9px;white-space:nowrap}.ng-card{margin-top:12px}.ng-head{display:flex;justify-content:space-between;gap:15px}.ng-head h3{margin:0}.ng-head p{margin:5px 0 0;color:var(--muted,#667085)}.ng-badges{display:flex;gap:6px;flex-wrap:wrap}.ng-badges span{padding:4px 7px;border:1px solid var(--line,#dfe5ec);border-radius:999px;font-size:10px}.ng-node-list{margin:10px 0;font-size:11px}.ng-inline{display:inline-flex;gap:6px;align-items:center;margin-right:6px}.ng-filter{grid-template-columns:minmax(190px,1fr) minmax(160px,.65fr) minmax(145px,.55fr) auto auto auto!important}@media(max-width:1000px){.ng-create,.ng-form{grid-template-columns:1fr 1fr}.ng-filter{display:flex!important;flex-wrap:wrap}.ng-filter>*{flex:1 1 150px}}</style>'''
        if "</head>" in text:text=text.replace("</head>",style+"</head>",1)
        response.set_data(text)
        response.headers["Content-Length"]=str(len(response.get_data()))
        return response

    return {"release":_RELEASE,"flags_dir":str(flags_dir)}
