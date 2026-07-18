"""VirtInfra Monitor 50.6.0 Node Groups and local country flags.

This module is deliberately additive. It is installed after app.py has finished
registering its effective runtime implementations. Existing API endpoints,
Agent payloads, metric formulas, retention and maintenance queues are not
modified.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from html import escape
from pathlib import Path
from typing import Any, Iterable

from flask import Response, abort, redirect, request, send_from_directory, url_for

RELEASE = "50.6.0-prod-r2-node-groups-update-detection-fix"
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
GROUP_FILTER_ENDPOINTS = {
    "index",
    "top_page",
    "vm_abuse_page",
    "node_health_page",
    "node_page",
    "vm_page",
    "storage_io_page",
    "bandwidth_consumption_page",
}

_NS: dict[str, Any] = {}
_APP = None
_DB_BASE = None
_PAGE_BASE = None
_CONSUMPTION_BASE = None
_SCHEMA_READY = False
_SCHEMA_LOCK = threading.RLock()
_CACHE_LOCK = threading.RLock()
_CACHE_AT = 0.0
_CACHE_GROUPS: list[dict[str, Any]] = []
_CACHE_NODE_MAP: dict[str, dict[str, Any]] = {}
_MODULE_DIR = Path(__file__).resolve().parent
_STATIC_ROOT = (_MODULE_DIR.parent / "static") if (_MODULE_DIR.parent / "static").is_dir() else (_MODULE_DIR / "static")
_FLAGS_ROOT = _STATIC_ROOT / "flags" / "4x3"
_COUNTRIES_JSON = _STATIC_ROOT / "flags" / "countries.json"


def _load_country_codes() -> frozenset[str]:
    try:
        values = json.loads(_COUNTRIES_JSON.read_text(encoding="utf-8"))
        return frozenset(
            str(item.get("code") or "").strip().upper()
            for item in values
            if isinstance(item, dict) and COUNTRY_RE.fullmatch(str(item.get("code") or "").strip().upper())
        )
    except Exception:
        return frozenset()


COUNTRY_CODES = _load_country_codes()


SCHEMA_SQL = r"""
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
    CHECK (country_code IS NULL OR country_code ~ '^[A-Z]{2}$'),
  CONSTRAINT node_groups_name_not_blank CHECK (BTRIM(name) <> '')
);
CREATE UNIQUE INDEX IF NOT EXISTS node_groups_name_unique
  ON node_groups (LOWER(BTRIM(name)));
CREATE UNIQUE INDEX IF NOT EXISTS node_groups_single_default
  ON node_groups (is_default) WHERE is_default = TRUE;

CREATE TABLE IF NOT EXISTS node_group_memberships (
  node_name TEXT PRIMARY KEY,
  group_id BIGINT NOT NULL REFERENCES node_groups(id) ON DELETE CASCADE,
  assigned_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  CONSTRAINT node_group_memberships_node_not_blank CHECK (BTRIM(node_name) <> '')
);
CREATE INDEX IF NOT EXISTS node_group_memberships_group_idx
  ON node_group_memberships(group_id,node_name);

CREATE TABLE IF NOT EXISTS node_group_membership_history (
  id BIGSERIAL PRIMARY KEY,
  node_name TEXT NOT NULL,
  group_id BIGINT,
  valid_from BIGINT NOT NULL,
  valid_to BIGINT,
  changed_at BIGINT NOT NULL,
  CONSTRAINT node_group_history_node_not_blank CHECK (BTRIM(node_name) <> ''),
  CONSTRAINT node_group_history_window_check CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE INDEX IF NOT EXISTS node_group_history_lookup_idx
  ON node_group_membership_history(node_name,valid_from,valid_to);
CREATE UNIQUE INDEX IF NOT EXISTS node_group_history_one_open_row
  ON node_group_membership_history(node_name) WHERE valid_to IS NULL;
"""


CSS = r"""
<style id="v5060-node-groups-css">
.node-identity-v5060{display:inline-flex;align-items:center;gap:6px;min-width:0;max-width:100%;vertical-align:middle}
.node-identity-v5060>.node-flag-v5060{width:16px!important;height:12px!important;min-width:16px!important;max-width:16px!important;flex:0 0 16px!important;display:inline-block!important;object-fit:cover;border-radius:2px;box-shadow:0 0 0 1px rgba(15,23,42,.12);margin:0!important}
.node-identity-v5060>.node-flag-fallback-v5060{width:16px;height:12px;line-height:12px;font-size:12px;text-align:center;flex:0 0 16px;overflow:hidden}
.node-group-sub-v5060{display:block;margin-top:3px;color:var(--muted,#667085);font-size:9px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.v5060-filter-card{padding:12px 14px!important;margin-bottom:12px!important;overflow:visible!important}
.v5060-filter-form{display:grid;grid-template-columns:minmax(190px,280px) minmax(230px,360px) auto auto;gap:8px;align-items:end}
.v5060-filter-form label{display:grid;gap:4px;color:var(--muted,#667085);font-size:9px;font-weight:900;letter-spacing:.04em;text-transform:uppercase}
.v5060-filter-form select{min-height:38px;width:100%;box-sizing:border-box}
.v5060-filter-form button,.v5060-filter-form .clear{min-height:38px;display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box}
.v5060-group-chip{display:inline-flex;align-items:center;gap:6px;max-width:100%;padding:4px 8px;border:1px solid var(--line,#dfe5ec);border-radius:999px;font-size:10px;font-weight:800;white-space:nowrap}
.v5060-admin-grid{display:grid;grid-template-columns:minmax(320px,.7fr) minmax(560px,1.3fr);gap:14px;align-items:start}
.v5060-group-form{display:grid;gap:10px}.v5060-group-form label{display:grid;gap:5px;font-size:11px;font-weight:800}.v5060-group-form textarea{min-height:82px;resize:vertical}.v5060-group-form .checks{display:flex;gap:14px;align-items:center;flex-wrap:wrap}.v5060-group-form .checks label{display:flex;gap:6px;align-items:center}
.v5060-group-actions{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.v5060-group-members{max-height:220px;overflow:auto;padding:8px;border:1px solid var(--line,#dfe5ec);border-radius:8px}.v5060-group-members a{display:block;margin:0;padding:5px 6px}
.v5060-inline-assign{display:flex;gap:5px;align-items:center;flex-wrap:wrap}.v5060-inline-assign select{max-width:190px;min-width:130px;padding:6px}.v5060-inline-assign button{padding:6px 9px}
.v5060-group-table td,.v5060-group-table th{vertical-align:middle}.v5060-country-code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;font-weight:850}
.v5060-group-consumption{min-width:1180px;table-layout:fixed}.v5060-group-consumption th,.v5060-group-consumption td{vertical-align:middle}.v5060-group-consumption td:not(:first-child),.v5060-group-consumption th:not(:first-child){text-align:right;font-variant-numeric:tabular-nums}.v5060-group-consumption th:first-child,.v5060-group-consumption td:first-child{text-align:left}
.v5058c-shell{padding:16px!important}.v5058c-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;flex-wrap:wrap}.v5058c-head h2{margin:0}.v5058c-head p{margin:5px 0 0;color:var(--muted,#667085);font-size:12px}.v5058c-periods{display:flex;gap:6px;flex-wrap:wrap}.v5058c-periods a{min-width:46px;padding:8px 11px;border:1px solid var(--line,#dfe5ec);border-radius:8px;text-align:center;text-decoration:none;font-size:12px;font-weight:800}.v5058c-periods a.active{background:var(--brand,#2563eb);border-color:var(--brand,#2563eb);color:#fff!important}.v5058c-tabs{display:flex;gap:6px;margin:16px 0 10px;border-bottom:1px solid var(--line,#dfe5ec)}.v5058c-tabs a{padding:9px 14px;text-decoration:none;color:var(--muted,#667085);font-size:12px;font-weight:800;border-bottom:2px solid transparent}.v5058c-tabs a.active{color:var(--brand,#2563eb);border-bottom-color:var(--brand,#2563eb)}
.v5060-hidden-by-group{display:none!important}
@media(max-width:980px){.v5060-filter-form{grid-template-columns:1fr 1fr}.v5060-admin-grid{grid-template-columns:1fr}}
@media(max-width:640px){.v5060-filter-form{grid-template-columns:1fr}}
</style>
"""


def _now() -> int:
    fn = _NS.get("now_ts")
    return int(fn()) if callable(fn) else int(time.time())


def _safe_int(value: Any, default: int = 0) -> int:
    fn = _NS.get("safe_int")
    if callable(fn):
        return int(fn(value, default))
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _clean_country(value: Any) -> str | None:
    code = str(value or "").strip().upper()
    if not code:
        return None
    if not COUNTRY_RE.fullmatch(code):
        raise ValueError("Country code must contain exactly two ISO letters, for example JP, US or SG.")
    if COUNTRY_CODES and code not in COUNTRY_CODES:
        raise ValueError("Country code is not a supported ISO 3166-1 alpha-2 value.")
    return code


def _flag_emoji(code: str | None) -> str:
    value = str(code or "").upper()
    if not COUNTRY_RE.fullmatch(value):
        return "🌐"
    return "".join(chr(127397 + ord(char)) for char in value)


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        _SCHEMA_READY = True


def db():
    conn = _DB_BASE()
    _ensure_schema(conn)
    return conn


def invalidate_cache() -> None:
    global _CACHE_AT, _CACHE_GROUPS, _CACHE_NODE_MAP
    with _CACHE_LOCK:
        _CACHE_AT = 0.0
        _CACHE_GROUPS = []
        _CACHE_NODE_MAP = {}
    for name in ("_v48140_bump_cache_generation", "_v48140_cache_clear", "clear_dashboard_cache", "invalidate_page_cache"):
        fn = _NS.get(name)
        if callable(fn):
            try:
                fn()
            except TypeError:
                pass
            except Exception:
                if _APP:
                    _APP.logger.exception("Could not invalidate %s after Node Group change", name)


def _load_cache(force: bool = False) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    global _CACHE_AT, _CACHE_GROUPS, _CACHE_NODE_MAP
    now = time.monotonic()
    with _CACHE_LOCK:
        if not force and _CACHE_AT > 0 and now - _CACHE_AT < 30:
            return list(_CACHE_GROUPS), dict(_CACHE_NODE_MAP)
        conn = db()
        try:
            groups_rows = conn.execute("""
              SELECT g.id,g.name,g.description,g.country_code,g.enabled,g.hidden,g.is_default,
                     g.created_at,g.updated_at,COUNT(m.node_name) node_count
                FROM node_groups g
                LEFT JOIN node_group_memberships m ON m.group_id=g.id
               GROUP BY g.id,g.name,g.description,g.country_code,g.enabled,g.hidden,g.is_default,g.created_at,g.updated_at
               ORDER BY CASE WHEN g.is_default THEN 0 ELSE 1 END,LOWER(g.name),g.id
            """).fetchall()
            map_rows = conn.execute("""
              SELECT m.node_name,g.id,g.name,g.description,g.country_code,g.enabled,g.hidden,g.is_default
                FROM node_group_memberships m JOIN node_groups g ON g.id=m.group_id
            """).fetchall()
        finally:
            conn.close()
        groups = [
            {
                "id": _safe_int(r[0]), "name": str(r[1] or ""), "description": str(r[2] or ""),
                "country_code": str(r[3] or "") or None, "enabled": bool(r[4]), "hidden": bool(r[5]),
                "is_default": bool(r[6]), "created_at": _safe_int(r[7]), "updated_at": _safe_int(r[8]),
                "node_count": _safe_int(r[9]),
            }
            for r in groups_rows
        ]
        node_map = {
            str(r[0]): {
                "id": _safe_int(r[1]), "name": str(r[2] or ""), "description": str(r[3] or ""),
                "country_code": str(r[4] or "") or None, "enabled": bool(r[5]), "hidden": bool(r[6]),
                "is_default": bool(r[7]),
            }
            for r in map_rows if r and r[0]
        }
        _CACHE_GROUPS = groups
        _CACHE_NODE_MAP = node_map
        _CACHE_AT = now
        return list(groups), dict(node_map)


def groups(include_hidden: bool = True) -> list[dict[str, Any]]:
    values, _ = _load_cache()
    return values if include_hidden else [g for g in values if g["enabled"] and not g["hidden"]]


def node_group_map() -> dict[str, dict[str, Any]]:
    return _load_cache()[1]


def _group_value() -> str:
    value = str(request.args.get("group_id") or "").strip().lower()
    return value if value == "ungrouped" or value.isdigit() else ""


def _node_value() -> str:
    return str(request.args.get("node") or "").strip()


def _group_matches(node_name: str, group_value: str | None = None, node_value: str | None = None) -> bool:
    node_name = str(node_name or "")
    group_value = _group_value() if group_value is None else str(group_value or "").lower()
    node_value = _node_value() if node_value is None else str(node_value or "")
    if node_value and node_name != node_value:
        return False
    if not group_value:
        return True
    info = node_group_map().get(node_name)
    if group_value == "ungrouped":
        return info is None
    return bool(info and str(info.get("id")) == group_value)


def _node_from_row(row: Any, index: int = 0) -> str:
    if isinstance(row, dict):
        return str(row.get("node") or row.get("node_name") or "")
    try:
        return str(row[index] or "")
    except (TypeError, IndexError):
        return ""


def _filter_rows(rows: Iterable[Any], index: int = 0) -> list[Any]:
    return [row for row in (rows or []) if _group_matches(_node_from_row(row, index))]


def _flag_exists(code: str | None) -> bool:
    value = str(code or "").lower()
    return bool(COUNTRY_RE.fullmatch(value.upper()) and (_FLAGS_ROOT / f"{value}.svg").is_file())


def flag_html(country_code: str | None, *, title: str = "") -> str:
    code = str(country_code or "").upper()
    if _flag_exists(code):
        label = title or code
        return (
            f'<img class="node-flag-v5060" src="/static/flags/4x3/{code.lower()}.svg" '
            f'alt="{escape(code, quote=True)}" title="{escape(label, quote=True)}" loading="lazy">'
        )
    return f'<span class="node-flag-fallback-v5060" title="{escape(title or code or "Global", quote=True)}">{_flag_emoji(code)}</span>'


def node_identity_html(node_name: str, *, show_group: bool = False, link: str | None = None) -> str:
    node_name = str(node_name or "")
    info = node_group_map().get(node_name)
    flag = flag_html(info.get("country_code") if info else None, title=info.get("name", "") if info else "Global")
    label = escape(node_name)
    if link:
        label = f'<a href="{escape(link, quote=True)}"><b>{label}</b></a>'
    else:
        label = f"<b>{label}</b>"
    group_line = f'<small class="node-group-sub-v5060">{escape(info["name"])}</small>' if show_group and info else ""
    return f'<span class="node-identity-v5060" data-node-name="{escape(node_name, quote=True)}">{flag}<span>{label}{group_line}</span></span>'


def _node_names_for_filter(group_value: str = "") -> list[str]:
    conn = db()
    try:
        where = ["COALESCE(ni.status,'active')!='hidden'", "ni.deleted_at IS NULL"]
        params: list[Any] = []
        if group_value == "ungrouped":
            where.append("m.node_name IS NULL")
        elif group_value.isdigit():
            where.append("m.group_id=?")
            params.append(int(group_value))
        rows = conn.execute(
            "SELECT ni.node FROM node_inventory ni LEFT JOIN node_group_memberships m ON m.node_name=ni.node WHERE "
            + " AND ".join(where) + " ORDER BY LOWER(ni.node)", params,
        ).fetchall()
        return [str(r[0]) for r in rows if r and r[0]]
    finally:
        conn.close()


def _group_options_html(selected: str, *, include_hidden: bool = False) -> str:
    values = ['<option value="">All Groups</option>', f'<option value="ungrouped"{" selected" if selected == "ungrouped" else ""}>🌐 Ungrouped</option>']
    current_id = selected if selected.isdigit() else ""
    for group in groups(include_hidden=True):
        if not include_hidden and (group["hidden"] or not group["enabled"]) and str(group["id"]) != current_id:
            continue
        state = ""
        if not group["enabled"]:
            state = " · disabled"
        elif group["hidden"]:
            state = " · hidden"
        label = f'{_flag_emoji(group.get("country_code"))} {group["name"]}{state}'
        values.append(f'<option value="{group["id"]}"{" selected" if str(group["id"]) == selected else ""}>{escape(label)}</option>')
    return "".join(values)


def _node_options_html(selected_group: str, selected_node: str) -> str:
    values = ['<option value="">All Nodes</option>']
    for node in _node_names_for_filter(selected_group):
        info = node_group_map().get(node)
        label = f'{_flag_emoji(info.get("country_code") if info else None)} {node}'
        values.append(f'<option value="{escape(node, quote=True)}"{" selected" if node == selected_node else ""}>{escape(label)}</option>')
    return "".join(values)


def global_filter_html() -> str:
    endpoint = request.endpoint or ""
    if endpoint not in GROUP_FILTER_ENDPOINTS or endpoint == "bandwidth_consumption_page" and request.args.get("tab") == "group":
        return ""
    selected_group = _group_value()
    selected_node = _node_value()
    hidden = []
    for key, value in request.args.items():
        if key in {"group_id", "node", "page"}:
            continue
        hidden.append(f'<input type="hidden" name="{escape(key, quote=True)}" value="{escape(value, quote=True)}">')
    return f'''
    <div class="card v5060-filter-card" data-v5060-group-filter>
      <form class="v5060-filter-form" method="get" action="{escape(request.path, quote=True)}">
        {''.join(hidden)}
        <label>Group<select name="group_id">{_group_options_html(selected_group)}</select></label>
        <label>Node<select name="node">{_node_options_html(selected_group, selected_node)}</select></label>
        <button type="submit">Apply</button>
        <a class="clear" href="{escape(request.path, quote=True)}">Reset</a>
      </form>
    </div>'''


def _json_script_data() -> tuple[str, str]:
    mapping = node_group_map()
    safe_map = {
        node: {
            "name": item.get("name") or "",
            "country_code": item.get("country_code") or "",
            "flag_url": f'/static/flags/4x3/{str(item.get("country_code") or "").lower()}.svg' if _flag_exists(item.get("country_code")) else "",
            "emoji": _flag_emoji(item.get("country_code")),
        }
        for node, item in mapping.items()
    }
    allowed = _node_names_for_filter(_group_value()) if _group_value() else []
    return json.dumps(safe_map, ensure_ascii=False).replace("</", "<\\/"), json.dumps(allowed, ensure_ascii=False).replace("</", "<\\/")


def runtime_script() -> str:
    map_json, allowed_json = _json_script_data()
    group_selected = "true" if _group_value() else "false"
    return f'''
<script id="v5060-node-groups-runtime">
(function(){{
  const nodeMap={map_json};
  const allowedNodes=new Set({allowed_json});
  const groupSelected={group_selected};
  function makeFlag(node){{
    const info=nodeMap[node]||null;
    const wrap=document.createElement('span'); wrap.className='node-identity-v5060'; wrap.dataset.nodeName=node;
    if(info&&info.flag_url){{const img=document.createElement('img');img.className='node-flag-v5060';img.src=info.flag_url;img.alt=info.country_code||'';img.title=info.name||info.country_code||'';img.loading='lazy';wrap.appendChild(img);}}
    else{{const fallback=document.createElement('span');fallback.className='node-flag-fallback-v5060';fallback.textContent=info&&info.emoji?info.emoji:'🌐';fallback.title=info&&info.name?info.name:'Global';wrap.appendChild(fallback);}}
    return wrap;
  }}
  function decorate(root){{
    root=root||document;
    const selectors=['a[href*="/node/"]','a[href*="node="]','.node-name-cell b','.node-line b','.identity-node a','.v5058c-node b','td b','h2','h3'];
    root.querySelectorAll(selectors.join(',')).forEach(function(el){{
      if(el.closest('.node-identity-v5060')||el.dataset.v5060Flagged==='1')return;
      const text=(el.textContent||'').trim(); if(!text||!(text in nodeMap))return;
      el.dataset.v5060Flagged='1';
      const holder=makeFlag(text); el.parentNode.insertBefore(holder,el); holder.appendChild(el);
      const info=nodeMap[text]; if(info&&info.name){{const small=document.createElement('small');small.className='node-group-sub-v5060';small.textContent=info.name;holder.lastChild.appendChild(small);}}
    }});
    if(groupSelected){{
      root.querySelectorAll('tr,article.storage-vm-card,.storage-child-item,.card').forEach(function(container){{
        const anchors=Array.from(container.querySelectorAll('a[href*="/node/"],a[href*="node="]'));
        const nodes=anchors.map(a=>(a.textContent||'').trim()).filter(n=>n in nodeMap||n);
        const exact=nodes.find(n=>allowedNodes.has(n));
        const known=nodes.find(n=>(n in nodeMap)||allowedNodes.has(n));
        if(known&&!exact&&container.tagName!=='DIV')container.classList.add('v5060-hidden-by-group');
      }});
    }}
  }}
  function preserveFilters(root){{
    const p=new URLSearchParams(location.search); const g=p.get('group_id')||''; const n=p.get('node')||'';
    if(!g&&!n)return;
    (root||document).querySelectorAll('a[href]').forEach(function(a){{
      let u;try{{u=new URL(a.href,location.href)}}catch(e){{return}}
      if(u.origin!==location.origin)return;
      if(g&&!u.searchParams.has('group_id'))u.searchParams.set('group_id',g);
      if(n&&!u.searchParams.has('node'))u.searchParams.set('node',n);
      a.href=u.pathname+u.search+u.hash;
    }});
    (root||document).querySelectorAll('form[method="get"],form:not([method])').forEach(function(form){{
      if(g&&!form.querySelector('[name="group_id"]')){{const i=document.createElement('input');i.type='hidden';i.name='group_id';i.value=g;form.appendChild(i);}}
      if(n&&!form.querySelector('[name="node"]')){{const i=document.createElement('input');i.type='hidden';i.name='node';i.value=n;form.appendChild(i);}}
    }});
  }}
  function run(root){{decorate(root||document);preserveFilters(root||document)}}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>run(document));else run(document);
  new MutationObserver(m=>m.forEach(x=>x.addedNodes.forEach(n=>{{if(n.nodeType===1)run(n)}}))).observe(document.documentElement,{{childList:true,subtree:true}});
}})();
</script>'''


def page(title: str, content: str):
    response = _PAGE_BASE(title, content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace("</head>", CSS + "</head>", 1)
        filter_html = global_filter_html()
        if filter_html and '<div class="wrap" id="bw-content">' in html:
            html = html.replace('<div class="wrap" id="bw-content">', '<div class="wrap" id="bw-content">' + filter_html, 1)
        html = html.replace("</body>", runtime_script() + "</body>", 1)
        response.set_data(html)
    except Exception:
        _APP.logger.exception("Could not apply Node Group presentation layer")
    return response


def _admin_nav(active: str) -> str:
    entries = (
        ("overview", "Overview"),
        ("nodes", "Nodes"),
        ("node_groups", "Node Groups"),
        ("vms", "VMs"),
        ("maintenance", "Maintenance"),
    )
    return '<nav class="admin-nav">' + "".join(
        f'<a class="{"active" if key == active else ""}" href="{escape(url_for("admin_page", section=key), quote=True)}">{label}</a>'
        for key, label in entries
    ) + "</nav>"


def _admin_redirect(section: str, *, message: str = "", error: str = ""):
    kwargs: dict[str, Any] = {"section": section}
    if message:
        kwargs["ngmsg"] = message[:500]
    if error:
        kwargs["ngerr"] = error[:500]
    return redirect(url_for("admin_page", **kwargs))


def _admin_notice() -> str:
    message = str(request.args.get("ngmsg") or "")[:500]
    error = str(request.args.get("ngerr") or "")[:500]
    items = []
    if message:
        items.append(f'<div class="notice success">{escape(message)}</div>')
    if error:
        items.append(f'<div class="notice error">{escape(error)}</div>')
    return "".join(items)


def _country_options(selected: str | None) -> str:
    selected = str(selected or "").upper()
    path = _STATIC_ROOT / "flags" / "countries.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = []
    values = [f'<option value=""{" selected" if not selected else ""}>Global / no country</option>']
    for item in data:
        code = str(item.get("code") or "").upper()
        if not COUNTRY_RE.fullmatch(code):
            continue
        label = f'{_flag_emoji(code)} {item.get("name") or code} ({code})'
        values.append(f'<option value="{code}"{" selected" if code == selected else ""}>{escape(label)}</option>')
    return "".join(values)


def _group_form(edit_id: int = 0) -> str:
    current = {"id": 0, "name": "", "description": "", "country_code": "", "enabled": True, "hidden": False, "is_default": False}
    if edit_id:
        current = next((g for g in groups(True) if g["id"] == edit_id), current)
    return f'''
    <div class="card">
      <div class="section-head"><div><h3>{'Edit Group' if edit_id else 'Create Group'}</h3><p>Membership is keyed only by the exact Node name. No IP field participates in assignment.</p></div></div>
      <form class="v5060-group-form" method="post" action="{escape(url_for('v5060_group_save'), quote=True)}">
        <input type="hidden" name="csrf_token" value="{escape(_NS['csrf_token'](), quote=True)}">
        <input type="hidden" name="group_id" value="{current.get('id',0)}">
        <label>Name<input name="name" maxlength="120" required value="{escape(str(current.get('name') or ''), quote=True)}"></label>
        <label>Description<textarea name="description" maxlength="1000">{escape(str(current.get('description') or ''))}</textarea></label>
        <label>Country<select name="country_code">{_country_options(current.get('country_code'))}</select></label>
        <div class="checks">
          <label><input type="checkbox" name="enabled" value="1"{' checked' if current.get('enabled') else ''}> Enabled</label>
          <label><input type="checkbox" name="hidden" value="1"{' checked' if current.get('hidden') else ''}> Hidden</label>
          <label><input type="checkbox" name="is_default" value="1"{' checked' if current.get('is_default') else ''}> Default</label>
        </div>
        <div class="v5060-group-actions"><button type="submit">Save Group</button>{f'<a class="clear" href="{url_for("admin_page",section="node_groups")}">Cancel</a>' if edit_id else ''}</div>
      </form>
    </div>'''


def _group_members(group_id: int) -> list[str]:
    conn = db()
    try:
        rows = conn.execute("SELECT node_name FROM node_group_memberships WHERE group_id=? ORDER BY LOWER(node_name)", (group_id,)).fetchall()
        return [str(r[0]) for r in rows if r and r[0]]
    finally:
        conn.close()


def admin_groups_section() -> str:
    edit_id = _safe_int(request.args.get("edit"), 0)
    rows = []
    for group in groups(True):
        members = _group_members(group["id"])
        member_html = "".join(
            f'<a href="{escape(url_for("node_page", node=node, period="5m"), quote=True)}">{node_identity_html(node)}</a>'
            for node in members
        ) or '<span class="empty">No Nodes assigned</span>'
        states = []
        states.append("Enabled" if group["enabled"] else "Disabled")
        if group["hidden"]:
            states.append("Hidden")
        if group["is_default"]:
            states.append("Default")
        edit_url = url_for("admin_page", section="node_groups", edit=group["id"])
        delete_form = f'''<form class="inline-form" method="post" action="{url_for('v5060_group_delete')}" onsubmit="return confirm('Delete this Group? Assigned Nodes become Ungrouped; metrics are kept.')"><input type="hidden" name="csrf_token" value="{escape(_NS['csrf_token'](),quote=True)}"><input type="hidden" name="group_id" value="{group['id']}"><button class="btn-danger">Delete</button></form>'''
        rows.append(f'''
        <tr>
          <td>{flag_html(group.get('country_code'), title=group['name'])}</td>
          <td><b>{escape(group['name'])}</b><small class="row-sub">{escape(group.get('description') or '-')}</small></td>
          <td class="v5060-country-code">{escape(group.get('country_code') or 'GLOBAL')}</td>
          <td>{' · '.join(states)}</td><td class="num"><b>{group['node_count']}</b></td>
          <td><details><summary>View Nodes</summary><div class="v5060-group-members">{member_html}</div></details></td>
          <td><div class="v5060-group-actions"><a class="btn" href="{escape(edit_url,quote=True)}">Edit</a>{delete_form}</div></td>
        </tr>''')
    body = "".join(rows) or '<tr><td colspan="7" class="empty">No Node Groups yet</td></tr>'
    return _admin_notice() + f'''
    <div class="v5060-admin-grid">
      {_group_form(edit_id)}
      <div class="card"><div class="section-head"><div><h3>Node Groups</h3><p>Country flags are vendored SVG assets. The database stores only the ISO two-letter code.</p></div></div>
        <div class="table-wrap"><table class="admin-clean-table v5060-group-table"><thead><tr><th>FLAG</th><th>GROUP / DESCRIPTION</th><th>COUNTRY</th><th>STATE</th><th>NODES</th><th>MEMBERS</th><th>ACTION</th></tr></thead><tbody>{body}</tbody></table></div>
      </div>
    </div>'''


def _status_sql(alias: str, column: str, status: str) -> tuple[str, list[Any]]:
    fn = _NS.get("_v48134_status_sql")
    if callable(fn):
        return fn(alias, column, status)
    return "1=1", []


def _admin_pager(section: str, q: str, status: str, page_no: int, max_page: int, per_page: int, group_value: str = "", node_value: str = "") -> str:
    if max_page <= 1:
        return ""
    common = {"section": section, "q": q or None, "status": status, "per_page": per_page, "group_id": group_value or None, "node": node_value or None}
    prev_url = url_for("admin_page", **common, page=max(1, page_no - 1))
    next_url = url_for("admin_page", **common, page=min(max_page, page_no + 1))
    return f'<div class="pagination"><a class="btn {"disabled" if page_no<=1 else ""}" href="{escape(prev_url,quote=True)}">← Previous</a><span>Page <b>{page_no}</b> / <b>{max_page}</b></span><a class="btn {"disabled" if page_no>=max_page else ""}" href="{escape(next_url,quote=True)}">Next →</a></div>'


def _group_filter_sql(alias: str, group_value: str, node_value: str) -> tuple[list[str], list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    if group_value == "ungrouped":
        where.append("ngm.node_name IS NULL")
    elif group_value.isdigit():
        where.append("ngm.group_id=?")
        params.append(int(group_value))
    if node_value:
        where.append(f"{alias}.node=?")
        params.append(node_value)
    return where, params


def admin_nodes_section(q: str, status: str, page_no: int, per_page: int) -> str:
    group_value, node_value = _group_value(), _node_value()
    status_sql, params = _status_sql("ni", "last_push", status)
    where = [status_sql]
    extra, extra_params = _group_filter_sql("ni", group_value, node_value)
    where.extend(extra); params.extend(extra_params)
    if q:
        p = _NS["like_pattern"](q)
        where.append("(ni.node LIKE ? OR COALESCE(g.name,'') LIKE ?)")
        params.extend([p, p])
    where_sql = "WHERE " + " AND ".join(where)
    conn = db()
    try:
        total = _safe_int(conn.execute(f"""SELECT COUNT(*) FROM node_inventory ni LEFT JOIN node_group_memberships ngm ON ngm.node_name=ni.node LEFT JOIN node_groups g ON g.id=ngm.group_id {where_sql}""", params).fetchone()[0])
        max_page = max(1, int(math.ceil(total / float(max(1, per_page)))))
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
                 COALESCE(b.public_ipv4,''),COALESCE(b.private_ipv4,''),
                 g.id,g.name,g.country_code,g.enabled,g.hidden
            FROM node_inventory ni
            LEFT JOIN bridge_ip b ON b.node=ni.node
            LEFT JOIN vm_count vc ON vc.node=ni.node
            LEFT JOIN node_group_memberships ngm ON ngm.node_name=ni.node
            LEFT JOIN node_groups g ON g.id=ngm.group_id
            {where_sql}
           ORDER BY CASE WHEN COALESCE(ni.status,'active')='hidden' OR ni.deleted_at IS NOT NULL THEN 1 ELSE 0 END,
                    LOWER(ni.node) LIMIT ? OFFSET ?
        """, params + [per_page, (page_no - 1) * per_page]).fetchall()
    finally:
        conn.close()
    group_select = _group_options_html("", include_hidden=True).replace('value=""', 'value=""', 1)
    body = []
    cutoff = _now() - int(_NS.get("VM_STALE_SECONDS", 3 * 86400))
    for row in rows:
        node, row_status, last_push, deleted_at, vm_count, pub, priv, group_id, group_name, country_code, enabled, hidden = row
        is_hidden = row_status == "hidden" or bool(deleted_at)
        is_stale = not is_hidden and _safe_int(last_push) < cutoff
        display_status = "hidden" if is_hidden else ("stale" if is_stale else "active")
        default_group = next((g for g in groups(True) if g.get("is_default") and g.get("enabled")), None)
        selected = str(group_id or (default_group.get("id") if default_group else ""))
        select_html = _group_options_html(selected, include_hidden=True).replace('<option value="">All Groups</option>', '<option value="">Ungrouped / remove</option>', 1).replace('<option value="ungrouped"', '<option disabled value="ungrouped"', 1)
        assign_form = f'''<form class="v5060-inline-assign" method="post" action="{url_for('v5060_node_group_set')}"><input type="hidden" name="csrf_token" value="{escape(_NS['csrf_token'](),quote=True)}"><input type="hidden" name="node_name" value="{escape(node,quote=True)}"><select name="group_id">{select_html}</select><button>{'Move' if group_id else 'Assign'}</button></form>'''
        existing_forms = _NS["admin_form"](url_for('admin_delete_node'), 'Hide', {'node': node, 'mode': 'soft'}, danger=True, confirm='Hide node from dashboard? Raw usage is kept.')
        existing_forms += _NS["admin_form"](url_for('admin_restore_node'), 'Restore', {'node': node}, danger=False, confirm='Restore node to dashboard?')
        existing_forms += _NS["admin_form"](url_for('admin_purge_node_vms'), 'Purge VMs', {'node': node}, danger=True, confirm='Purge every VM and VM history under this node?')
        existing_forms += _NS["admin_form"](url_for('admin_delete_node'), 'Purge node', {'node': node, 'mode': 'purge'}, danger=True, confirm='Permanently purge this node and all monitoring data?')
        group_html = f'{flag_html(country_code,title=group_name or "Global")}<span><b>{escape(group_name or "Ungrouped")}</b><small class="row-sub">{escape(str(country_code or "GLOBAL"))}</small></span>'
        body.append(f'''<tr class="{'stale-row' if is_hidden or is_stale else ''}"><td>{node_identity_html(node)}</td><td>{group_html}</td><td>{escape(display_status)}</td><td class="mono">{escape(_NS['compact_ipv4'](pub) or '-')}</td><td class="num"><b>{_safe_int(vm_count)}</b></td><td>{_NS['fmt_full'](last_push)}</td><td>{assign_form}</td><td>{_NS['_v490_action_menu'](existing_forms)}</td></tr>''')
    if not body:
        body.append('<tr><td colspan="8" class="empty">No Nodes match this filter</td></tr>')
    filter_form = f'''<form class="search" method="get"><input type="hidden" name="section" value="nodes"><input name="q" value="{escape(q,quote=True)}" placeholder="Search exact Node name or Group"><select name="status">{_NS['_v48134_status_options'](status)}</select><select name="group_id">{_group_options_html(group_value,include_hidden=True)}</select><select name="node">{_node_options_html(group_value,node_value)}</select><select name="per_page"><option value="100"{' selected' if per_page==100 else ''}>100 rows</option><option value="200"{' selected' if per_page==200 else ''}>200 rows</option><option value="500"{' selected' if per_page==500 else ''}>500 rows</option></select><button>Filter</button><a class="clear" href="{url_for('admin_page',section='nodes')}">Reset</a></form>'''
    return _admin_notice() + f'''<div class="card"><div class="section-head"><div><h3>Node management</h3><p>{total:,} matching Node(s). Group membership is stored and changed only by exact Node name.</p></div></div>{filter_form}<div class="table-wrap"><table class="admin-clean-table"><thead><tr><th>NODE</th><th>GROUP / FLAG</th><th>STATUS</th><th>PUBLIC IP</th><th>VM</th><th>LAST PUSH</th><th>GROUP ACTION</th><th>NODE ACTION</th></tr></thead><tbody>{''.join(body)}</tbody></table></div>{_admin_pager('nodes',q,status,page_no,max_page,per_page,group_value,node_value)}</div>'''


def admin_vms_section(q: str, status: str, page_no: int, per_page: int) -> str:
    group_value, node_value = _group_value(), _node_value()
    status_sql, params = _status_sql("vi", "last_seen", status)
    where = [status_sql]
    extra, extra_params = _group_filter_sql("vi", group_value, node_value)
    where.extend(extra); params.extend(extra_params)
    if q:
        p = _NS["like_pattern"](q)
        where.append("(vi.node LIKE ? OR vi.vm_uuid LIKE ? OR COALESCE(g.name,'') LIKE ? OR COALESCE(vi.last_iface,'') LIKE ? OR COALESCE(vi.last_bridge,'') LIKE ?)")
        params.extend([p, p, p, p, p])
    where_sql = "WHERE " + " AND ".join(where)
    conn = db()
    try:
        total = _safe_int(conn.execute(f"""SELECT COUNT(*) FROM vm_inventory vi LEFT JOIN node_group_memberships ngm ON ngm.node_name=vi.node LEFT JOIN node_groups g ON g.id=ngm.group_id {where_sql}""", params).fetchone()[0])
        max_page = max(1, int(math.ceil(total / float(max(1, per_page)))))
        page_no = max(1, min(page_no, max_page))
        rows = conn.execute(f"""
          SELECT vi.node,vi.vm_uuid,vi.status,vi.last_seen,vi.last_bridge,vi.last_iface,vi.deleted_at,
                 g.name,g.country_code
            FROM vm_inventory vi
            LEFT JOIN node_group_memberships ngm ON ngm.node_name=vi.node
            LEFT JOIN node_groups g ON g.id=ngm.group_id
            {where_sql}
           ORDER BY CASE WHEN COALESCE(vi.status,'active')='hidden' OR vi.deleted_at IS NOT NULL THEN 1 ELSE 0 END,
                    LOWER(vi.node),vi.last_seen DESC LIMIT ? OFFSET ?
        """, params + [per_page, (page_no - 1) * per_page]).fetchall()
    finally:
        conn.close()
    body = []
    cutoff = _now() - int(_NS.get("VM_STALE_SECONDS", 3 * 86400))
    for node, vm_uuid, row_status, last_seen, bridge, iface, deleted_at, group_name, country_code in rows:
        is_hidden = row_status == "hidden" or bool(deleted_at)
        is_stale = not is_hidden and _safe_int(last_seen) < cutoff
        display_status = "hidden" if is_hidden else ("stale" if is_stale else "active")
        forms = _NS["admin_form"](url_for('admin_delete_vm'), 'Hide', {'node': node, 'vm_uuid': vm_uuid, 'mode': 'soft'}, danger=True, confirm='Hide VM from dashboard? Raw usage is kept.')
        forms += _NS["admin_form"](url_for('admin_restore_vm'), 'Restore', {'node': node, 'vm_uuid': vm_uuid}, danger=False, confirm='Restore VM to dashboard?')
        forms += _NS["admin_form"](url_for('admin_delete_vm'), 'Purge VM', {'node': node, 'vm_uuid': vm_uuid, 'mode': 'purge'}, danger=True, confirm='Permanently purge only this UUID from every VM-scoped table?')
        inherited = f'{flag_html(country_code,title=group_name or "Global")}<span><b>{escape(node)}</b><small class="row-sub">{escape(group_name or "Ungrouped")}</small></span>'
        body.append(f'''<tr class="{'stale-row' if is_hidden or is_stale else ''}"><td>{inherited}</td><td class="mono"><span class="uuid-cell">{escape(vm_uuid)}<button type="button" class="copy-btn" data-copy="{escape(vm_uuid,quote=True)}">⧉</button></span></td><td><b>{display_status}</b><small class="row-sub">{_NS['fmt_push'](last_seen)}</small></td><td>{escape(bridge or '-')}<small class="row-sub">{escape(iface or '-')}</small></td><td>{_NS['_v490_action_menu'](forms)}</td></tr>''')
    if not body:
        body.append('<tr><td colspan="5" class="empty">No VMs match this filter</td></tr>')
    filter_form = f'''<form class="search" method="get"><input type="hidden" name="section" value="vms"><input name="q" value="{escape(q,quote=True)}" placeholder="Search Node, Group, VM UUID, bridge or interface"><select name="status">{_NS['_v48134_status_options'](status)}</select><select name="group_id">{_group_options_html(group_value,include_hidden=True)}</select><select name="node">{_node_options_html(group_value,node_value)}</select><select name="per_page"><option value="100"{' selected' if per_page==100 else ''}>100 rows</option><option value="200"{' selected' if per_page==200 else ''}>200 rows</option><option value="500"{' selected' if per_page==500 else ''}>500 rows</option></select><button>Filter</button><a class="clear" href="{url_for('admin_page',section='vms')}">Reset</a></form>'''
    return _admin_notice() + f'''<div class="card"><div class="section-head"><div><h3>VM management</h3><p>{total:,} matching VM(s). Group and flag are inherited from the VM's Node; VMs have no direct Group assignment.</p></div></div>{filter_form}<div class="table-wrap"><table class="admin-clean-table"><thead><tr><th>NODE / INHERITED GROUP</th><th>VM UUID</th><th>STATUS / SEEN</th><th>BRIDGE / IFACE</th><th>ACTION</th></tr></thead><tbody>{''.join(body)}</tbody></table></div>{_admin_pager('vms',q,status,page_no,max_page,per_page,group_value,node_value)}</div>'''


def admin_page():
    deny = _NS["require_admin"]()
    if deny:
        return deny
    section = str(request.args.get("section") or "overview").strip().lower()
    if section not in {"overview", "nodes", "node_groups", "vms", "maintenance"}:
        section = "overview"
    q = str(request.args.get("q") or "").strip()
    clean_status = _NS.get("_v48134_clean_admin_status")
    status = clean_status(request.args.get("status")) if callable(clean_status) else "all"
    page_no = max(1, _safe_int(request.args.get("page"), 1))
    per_page = max(25, min(500, _safe_int(request.args.get("per_page"), 200)))
    stats = _NS["_v490_admin_stats"]()
    if section == "overview":
        section_html = _admin_notice() + _NS["_v490_admin_overview"](stats)
    elif section == "nodes":
        section_html = admin_nodes_section(q, status, page_no, per_page)
    elif section == "node_groups":
        section_html = admin_groups_section()
    elif section == "vms":
        section_html = admin_vms_section(q, status, page_no, per_page)
    else:
        dbmsg = str(request.args.get("dbmsg") or "")[:700]
        dberr = str(request.args.get("dberr") or "")[:700]
        section_html = _admin_notice() + _NS["_v490_live_cache_card"]() + _NS["database_maintenance_card"](dbmsg, dberr)
    content = f'''<div class="card admin-hero"><div><span class="eyebrow">CONTROL CENTER</span><h2>Administration</h2><p>Inventory, Node Groups and maintenance are separated into focused sections.</p></div><div class="admin-user-actions"><a class="btn" href="{url_for('index')}">Dashboard</a><a class="btn" href="{url_for('admin_logout')}">Logout</a></div></div>{_admin_nav(section)}{section_html}'''
    return _NS["page"]("Admin", content)


def _validate_node_exists(conn, node_name: str) -> None:
    if not node_name or node_name != node_name.strip():
        raise ValueError("Node name is required and must match the exact inventory name.")
    row = conn.execute("SELECT 1 FROM node_inventory WHERE node=? LIMIT 1", (node_name,)).fetchone()
    if not row:
        raise ValueError("Exact Node name was not found in node_inventory.")


def _set_node_group(conn, node_name: str, group_id: int | None) -> tuple[int | None, int | None]:
    _validate_node_exists(conn, node_name)
    current = conn.execute("SELECT group_id FROM node_group_memberships WHERE node_name=?", (node_name,)).fetchone()
    old_id = _safe_int(current[0]) if current else None
    now = _now()
    if group_id is None:
        if old_id is None:
            return None, None
        conn.execute("UPDATE node_group_membership_history SET valid_to=?,changed_at=? WHERE node_name=? AND valid_to IS NULL", (now, now, node_name))
        conn.execute("DELETE FROM node_group_memberships WHERE node_name=?", (node_name,))
        conn.execute(
            "INSERT INTO node_group_membership_history(node_name,group_id,valid_from,valid_to,changed_at) VALUES(?,NULL,?,NULL,?)",
            (node_name, now, now),
        )
        return old_id, None
    group = conn.execute("SELECT id,enabled FROM node_groups WHERE id=?", (group_id,)).fetchone()
    if not group:
        raise ValueError("Node Group does not exist.")
    if not bool(group[1]) and old_id != group_id:
        raise ValueError("Disabled Group cannot receive new Node assignments.")
    if old_id == group_id:
        conn.execute("UPDATE node_group_memberships SET updated_at=? WHERE node_name=?", (now, node_name))
        return old_id, group_id
    conn.execute("UPDATE node_group_membership_history SET valid_to=?,changed_at=? WHERE node_name=? AND valid_to IS NULL", (now, now, node_name))
    conn.execute("""
      INSERT INTO node_group_memberships(node_name,group_id,assigned_at,updated_at)
      VALUES(?,?,?,?)
      ON CONFLICT(node_name) DO UPDATE SET group_id=EXCLUDED.group_id,updated_at=EXCLUDED.updated_at
    """, (node_name, group_id, now, now))
    conn.execute("INSERT INTO node_group_membership_history(node_name,group_id,valid_from,valid_to,changed_at) VALUES(?,?,?,NULL,?)", (node_name, group_id, now, now))
    return old_id, group_id


def group_save():
    deny = _NS["require_admin"]()
    if deny:
        return deny
    try:
        group_id = _safe_int(request.form.get("group_id"), 0)
        name = str(request.form.get("name") or "").strip()
        if not name:
            raise ValueError("Group name is required.")
        if len(name) > 120:
            raise ValueError("Group name is too long.")
        description = str(request.form.get("description") or "").strip()[:1000]
        country = _clean_country(request.form.get("country_code"))
        enabled = request.form.get("enabled") == "1"
        hidden = request.form.get("hidden") == "1"
        is_default = request.form.get("is_default") == "1"
        now = _now()
        conn = db()
        try:
            if is_default:
                conn.execute("UPDATE node_groups SET is_default=FALSE,updated_at=? WHERE is_default=TRUE", (now,))
            if group_id:
                result = conn.execute("UPDATE node_groups SET name=?,description=?,country_code=?,enabled=?,hidden=?,is_default=?,updated_at=? WHERE id=?", (name, description, country, enabled, hidden, is_default, now, group_id))
                if getattr(result, "rowcount", 0) == 0:
                    raise ValueError("Node Group was not found.")
            else:
                conn.execute("INSERT INTO node_groups(name,description,country_code,enabled,hidden,is_default,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (name, description, country, enabled, hidden, is_default, now, now))
            conn.commit()
        finally:
            conn.close()
        invalidate_cache()
        return _admin_redirect("node_groups", message="Node Group saved.")
    except Exception as exc:
        if _APP:
            _APP.logger.warning("node_group_save_failed detail=%s", str(exc)[:300])
        return _admin_redirect("node_groups", error=str(exc))


def group_delete():
    deny = _NS["require_admin"]()
    if deny:
        return deny
    try:
        group_id = _safe_int(request.form.get("group_id"), 0)
        if not group_id:
            raise ValueError("Missing Node Group ID.")
        now = _now()
        conn = db()
        try:
            member_rows = conn.execute(
                "SELECT node_name FROM node_group_memberships WHERE group_id=? ORDER BY node_name",
                (group_id,),
            ).fetchall()
            members = [str(row[0]) for row in member_rows if row and row[0]]
            conn.execute(
                "UPDATE node_group_membership_history SET valid_to=?,changed_at=? WHERE group_id=? AND valid_to IS NULL",
                (now, now, group_id),
            )
            deleted = conn.execute("DELETE FROM node_groups WHERE id=?", (group_id,))
            if getattr(deleted, "rowcount", 0) == 0:
                raise ValueError("Node Group was not found.")
            for node_name in members:
                conn.execute(
                    "INSERT INTO node_group_membership_history(node_name,group_id,valid_from,valid_to,changed_at) VALUES(?,NULL,?,NULL,?)",
                    (node_name, now, now),
                )
            conn.commit()
        finally:
            conn.close()
        invalidate_cache()
        return _admin_redirect("node_groups", message="Node Group deleted. Its Nodes are now Ungrouped; monitoring data was not deleted.")
    except Exception as exc:
        return _admin_redirect("node_groups", error=str(exc))


def node_group_set():
    deny = _NS["require_admin"]()
    if deny:
        return deny
    node_name = str(request.form.get("node_name") or "")
    raw_group = str(request.form.get("group_id") or "").strip()
    try:
        group_id = int(raw_group) if raw_group.isdigit() else None
        conn = db()
        try:
            old_id, new_id = _set_node_group(conn, node_name, group_id)
            conn.commit()
        finally:
            conn.close()
        invalidate_cache()
        action = "removed from its Group" if new_id is None else ("assigned to Group" if old_id is None else "moved to another Group")
        return _admin_redirect("nodes", message=f"{node_name} was {action}.")
    except Exception as exc:
        return _admin_redirect("nodes", error=str(exc))


def flag_svg(filename: str):
    code = str(filename or "").lower()
    if not re.fullmatch(r"[a-z]{2}\.svg", code):
        abort(404)
    path = _FLAGS_ROOT / code
    if not path.is_file():
        abort(404)
    response = send_from_directory(_FLAGS_ROOT, code, mimetype="image/svg+xml", conditional=True, max_age=31536000)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _group_where(group_value: str, alias: str = "vm_rows") -> tuple[str, list[Any]]:
    if group_value == "ungrouped":
        return f" AND NOT EXISTS(SELECT 1 FROM node_group_memberships gm WHERE gm.node_name={alias}.node)", []
    if group_value.isdigit():
        return f" AND EXISTS(SELECT 1 FROM node_group_memberships gm WHERE gm.node_name={alias}.node AND gm.group_id=?)", [int(group_value)]
    return "", []


def _wrap_consumption_queries() -> None:
    base_vm_rows = _NS.get("_v5058c_vm_rows")
    base_node_rows = _NS.get("_v5058c_node_rows")
    base_vm_totals = _NS.get("_v5058c_vm_totals")
    base_node_totals = _NS.get("_v5058c_node_totals")
    if not all(callable(x) for x in (base_vm_rows, base_node_rows, base_vm_totals, base_node_totals)):
        return

    def vm_rows(start, end, selected_node, q, coverage, sort_by, order, page_no, limit):
        group_value, node_value = _group_value(), _node_value()
        selected_node = node_value or selected_node
        ctes, params = _NS["_v5058c_vm_ctes"](start, end, selected_node)
        search_sql, search_params = _NS["_v5058c_search_clause"]("vm", q)
        group_sql, group_params = _group_where(group_value, "vm_rows")
        where_sql = " WHERE 1=1" + search_sql + _NS["_v5058c_coverage_clause"](coverage) + group_sql
        order_column = _NS["V5058C_VM_SORTS"][sort_by]
        tie_order = "ASC" if sort_by in {"uuid", "node"} and order == "asc" else "DESC"
        page_no = max(1, page_no)
        def fetch(offset):
            conn = db()
            try:
                return conn.execute(ctes + """SELECT vm_uuid,node,node_ip,public_configured,private_configured,public_rx,public_tx,public_total,private_rx,private_tx,private_total,coverage_percent,latest_sample,COUNT(*) OVER() total_count FROM vm_rows""" + where_sql + " ORDER BY %s %s,vm_uuid %s LIMIT ? OFFSET ?" % (order_column, order.upper(), tie_order), params + search_params + group_params + [limit, offset]).fetchall()
            finally:
                conn.close()
        raw = fetch((page_no - 1) * limit)
        if not raw and page_no > 1:
            page_no = 1; raw = fetch(0)
        total = _safe_int(raw[0][-1] if raw else 0)
        return [tuple(r[:-1]) for r in raw], total, page_no, max(1, int(math.ceil(total / float(max(1, limit)))))

    def node_rows(start, end, q, coverage, sort_by, order, page_no, limit):
        group_value, node_value = _group_value(), _node_value()
        ctes, params = _NS["_v5058c_node_ctes"](start, end, node_value)
        search_sql, search_params = _NS["_v5058c_search_clause"]("node", q)
        group_sql, group_params = _group_where(group_value, "node_rows")
        where_sql = " WHERE 1=1" + search_sql + _NS["_v5058c_coverage_clause"](coverage) + group_sql
        order_column = _NS["V5058C_NODE_SORTS"][sort_by]
        tie_order = "ASC" if sort_by == "node" and order == "asc" else "DESC"
        page_no = max(1, page_no)
        def fetch(offset):
            conn = db()
            try:
                return conn.execute(ctes + """SELECT node,node_ip,public_configured,private_configured,physical_public_rx,physical_public_tx,physical_public_total,physical_private_rx,physical_private_tx,physical_private_total,coverage_percent,latest_sample,COUNT(*) OVER() total_count FROM node_rows""" + where_sql + " ORDER BY %s %s,node %s LIMIT ? OFFSET ?" % (order_column, order.upper(), tie_order), params + search_params + group_params + [limit, offset]).fetchall()
            finally:
                conn.close()
        raw = fetch((page_no - 1) * limit)
        if not raw and page_no > 1:
            page_no = 1; raw = fetch(0)
        total = _safe_int(raw[0][-1] if raw else 0)
        return [tuple(r[:-1]) for r in raw], total, page_no, max(1, int(math.ceil(total / float(max(1, limit)))))

    def vm_totals(start, end, selected_node=""):
        group_value, node_value = _group_value(), _node_value()
        selected_node = node_value or selected_node
        ctes, params = _NS["_v5058c_vm_ctes"](start, end, selected_node)
        group_sql, group_params = _group_where(group_value, "vm_rows")
        conn = db()
        try:
            row = conn.execute(ctes + "SELECT COALESCE(SUM(public_rx),0),COALESCE(SUM(public_tx),0),COALESCE(SUM(private_rx),0),COALESCE(SUM(private_tx),0) FROM vm_rows WHERE 1=1" + group_sql, params + group_params).fetchone()
            return {"vm_public_rx": _safe_int(row[0] if row else 0), "vm_public_tx": _safe_int(row[1] if row else 0), "vm_private_rx": _safe_int(row[2] if row else 0), "vm_private_tx": _safe_int(row[3] if row else 0)}
        finally:
            conn.close()

    def node_totals(start, end, selected_node=""):
        group_value, node_value = _group_value(), _node_value()
        selected_node = node_value or selected_node
        ctes, params = _NS["_v5058c_node_ctes"](start, end, selected_node)
        group_sql, group_params = _group_where(group_value, "node_rows")
        conn = db()
        try:
            row = conn.execute(ctes + "SELECT COALESCE(SUM(physical_public_rx),0),COALESCE(SUM(physical_public_tx),0),COALESCE(SUM(physical_private_rx),0),COALESCE(SUM(physical_private_tx),0) FROM node_rows WHERE 1=1" + group_sql, params + group_params).fetchone()
            return {"physical_public_rx": _safe_int(row[0] if row else 0), "physical_public_tx": _safe_int(row[1] if row else 0), "physical_private_rx": _safe_int(row[2] if row else 0), "physical_private_tx": _safe_int(row[3] if row else 0)}
        finally:
            conn.close()

    _NS["_v5058c_vm_rows"] = vm_rows
    _NS["_v5058c_node_rows"] = node_rows
    _NS["_v5058c_vm_totals"] = vm_totals
    _NS["_v5058c_node_totals"] = node_totals


def _group_consumption_rows(start: int, end: int, q: str, coverage: str, sort_by: str, order: str, page_no: int, limit: int):
    selected_group, selected_node = _group_value(), _node_value()
    source_sql, params = _NS["_v5058c_node_source_sql"](start, end, selected_node)
    expected_seconds = max(1, end - start)
    where = ["1=1"]
    where_params: list[Any] = []
    if selected_group == "ungrouped":
        where.append("group_id IS NULL")
    elif selected_group.isdigit():
        where.append("group_id=?"); where_params.append(int(selected_group))
    if q:
        like = _NS["like_pattern"](q)
        where.append("(LOWER(group_name) LIKE LOWER(?) OR LOWER(COALESCE(country_code,'')) LIKE LOWER(?))")
        where_params.extend([like, like])
    if coverage == "complete":
        where.append("coverage_percent>=99.999")
    elif coverage == "partial":
        where.append("coverage_percent>0 AND coverage_percent<99.999")
    elif coverage == "none":
        where.append("coverage_percent<=0")
    sort_map = {
        "group": "LOWER(group_name)", "nodes": "node_count", "physical_public_rx": "physical_public_rx",
        "physical_public_tx": "physical_public_tx", "physical_public_total": "physical_public_total",
        "physical_private_rx": "physical_private_rx", "physical_private_tx": "physical_private_tx",
        "physical_private_total": "physical_private_total", "coverage": "coverage_percent", "latest_sample": "latest_sample",
    }
    sort_col = sort_map.get(sort_by, "physical_public_total")
    direction = "ASC" if order == "asc" else "DESC"
    sql = f"""
      WITH source_parts AS ({source_sql}),
      node_agg AS (
        SELECT node,COALESCE(SUM(physical_public_rx),0)::bigint physical_public_rx,
               COALESCE(SUM(physical_public_tx),0)::bigint physical_public_tx,
               COALESCE(SUM(physical_private_rx),0)::bigint physical_private_rx,
               COALESCE(SUM(physical_private_tx),0)::bigint physical_private_tx,
               LEAST(?,COALESCE(SUM(coverage_seconds),0))::bigint coverage_seconds,
               COALESCE(MAX(latest_sample),0)::bigint latest_sample
          FROM source_parts GROUP BY node
      ), visible_nodes AS (
        SELECT ni.node FROM node_inventory ni
         WHERE COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL
         {"AND ni.node=?" if selected_node else ""}
      ), grouped AS (
        SELECT g.id group_id,COALESCE(g.name,'Ungrouped') group_name,g.country_code,
               COUNT(v.node)::bigint node_count,
               COALESCE(SUM(a.physical_public_rx),0)::bigint physical_public_rx,
               COALESCE(SUM(a.physical_public_tx),0)::bigint physical_public_tx,
               COALESCE(SUM(a.physical_public_rx+a.physical_public_tx),0)::bigint physical_public_total,
               COALESCE(SUM(a.physical_private_rx),0)::bigint physical_private_rx,
               COALESCE(SUM(a.physical_private_tx),0)::bigint physical_private_tx,
               COALESCE(SUM(a.physical_private_rx+a.physical_private_tx),0)::bigint physical_private_total,
               LEAST(100.0,COALESCE(SUM(a.coverage_seconds),0)*100.0/(?*COUNT(v.node))) coverage_percent,
               COALESCE(MAX(a.latest_sample),0)::bigint latest_sample
          FROM visible_nodes v
          LEFT JOIN node_agg a ON a.node=v.node
          LEFT JOIN node_group_memberships m ON m.node_name=v.node
          LEFT JOIN node_groups g ON g.id=m.group_id
         GROUP BY g.id,COALESCE(g.name,'Ungrouped'),g.country_code
      )
      SELECT group_id,group_name,country_code,node_count,physical_public_rx,physical_public_tx,physical_public_total,
             physical_private_rx,physical_private_tx,physical_private_total,coverage_percent,latest_sample,
             COUNT(*) OVER() total_count
        FROM grouped WHERE {' AND '.join(where)}
       ORDER BY {sort_col} {direction},LOWER(group_name) ASC LIMIT ? OFFSET ?
    """
    full_params = list(params) + [expected_seconds]
    if selected_node:
        full_params.append(selected_node)
    full_params.append(expected_seconds)
    page_no = max(1, page_no)
    conn = db()
    try:
        raw = conn.execute(sql, full_params + where_params + [limit, (page_no - 1) * limit]).fetchall()
        if not raw and page_no > 1:
            page_no = 1
            raw = conn.execute(sql, full_params + where_params + [limit, 0]).fetchall()
    finally:
        conn.close()
    total = _safe_int(raw[0][-1] if raw else 0)
    return [tuple(r[:-1]) for r in raw], total, page_no, max(1, int(math.ceil(total / float(max(1, limit)))))


def _group_consumption_table(rows: list[tuple[Any, ...]]) -> str:
    body = []
    for group_id, name, country, node_count, pub_rx, pub_tx, pub_total, pri_rx, pri_tx, pri_total, coverage, latest in rows:
        identity = f'<span class="node-identity-v5060">{flag_html(country,title=name)}<span><b>{escape(name)}</b><small class="node-group-sub-v5060">{escape(country or "GLOBAL")}</small></span></span>'
        body.append(f'''<tr><td>{identity}</td><td>{_safe_int(node_count)}</td><td>{_NS['human'](pub_rx)}</td><td>{_NS['human'](pub_tx)}</td><td><b>{_NS['human'](pub_total)}</b></td><td>{_NS['human'](pri_rx)}</td><td>{_NS['human'](pri_tx)}</td><td><b>{_NS['human'](pri_total)}</b></td><td>{float(coverage or 0):.1f}%</td><td>{_NS['fmt_full'](latest)}<small class="row-sub">{_NS['fmt_push'](latest)}</small></td></tr>''')
    if not body:
        body.append('<tr><td colspan="10" class="empty">No Group consumption matches the selected filters.</td></tr>')
    return f'''<div class="table-wrap"><table class="v5060-group-consumption"><thead><tr><th>GROUP / COUNTRY</th><th>NODES</th><th>PUBLIC RX</th><th>PUBLIC TX</th><th>PUBLIC TOTAL</th><th>PRIVATE RX</th><th>PRIVATE TX</th><th>PRIVATE TOTAL</th><th>COVERAGE</th><th>LATEST SAMPLE</th></tr></thead><tbody>{''.join(body)}</tbody></table></div>'''


def _consumption_pager(page_no: int, max_page: int, limit: int, period: str, q: str, coverage: str, sort_by: str, order: str, group_value: str, node_value: str) -> str:
    if max_page <= 1:
        return ""
    def link(target: int, label: str, disabled: bool = False) -> str:
        href = url_for("bandwidth_consumption_page", tab="group", period=period, q=q or None, coverage=coverage, sort=sort_by, order=order, limit=limit, page=target, group_id=group_value or None, node=node_value or None)
        return f'<a class="btn {"disabled" if disabled else ""}" href="{escape(href,quote=True)}">{label}</a>'
    return f'<div class="pagination">{link(max(1,page_no-1),"← Previous",page_no<=1)}<span>Page <b>{page_no}</b> / <b>{max_page}</b></span>{link(min(max_page,page_no+1),"Next →",page_no>=max_page)}</div>'


def group_consumption_page():
    period = str(request.args.get("period") or "24h").lower()
    if period not in set(_NS.get("V5058C_PERIODS", ("1h", "2h", "6h", "12h", "24h", "2d", "7d"))):
        period = "24h"
    end = _now()
    start = end - int(_NS["period_seconds"](period))
    q = str(request.args.get("q") or "").strip()
    coverage = str(request.args.get("coverage") or "all").lower()
    if coverage not in {"all", "complete", "partial", "none"}:
        coverage = "all"
    sort_by = str(request.args.get("sort") or "physical_public_total")
    order = "asc" if str(request.args.get("order") or "desc").lower() == "asc" else "desc"
    page_no = max(1, _safe_int(request.args.get("page"), 1))
    limit = max(25, min(500, _safe_int(request.args.get("limit"), 100)))
    rows, total, page_no, max_page = _group_consumption_rows(start, end, q, coverage, sort_by, order, page_no, limit)
    group_value, node_value = _group_value(), _node_value()
    hidden = f'<input type="hidden" name="tab" value="group"><input type="hidden" name="period" value="{escape(period,quote=True)}">'
    toolbar = f'''<form class="v5060-filter-form" method="get" action="{url_for('bandwidth_consumption_page')}">{hidden}<label>Search<input name="q" value="{escape(q,quote=True)}" placeholder="Group name or country code"></label><label>Group<select name="group_id">{_group_options_html(group_value)}</select></label><label>Node<select name="node">{_node_options_html(group_value,node_value)}</select></label><label>Coverage<select name="coverage"><option value="all">All Coverage</option><option value="complete"{' selected' if coverage=='complete' else ''}>Complete</option><option value="partial"{' selected' if coverage=='partial' else ''}>Partial</option><option value="none"{' selected' if coverage=='none' else ''}>No Data</option></select></label><button>Apply</button><a class="clear" href="{url_for('bandwidth_consumption_page',tab='group',period=period)}">Reset</a></form>'''
    periods = "".join(f'<a class="{"active" if item==period else ""}" href="{url_for("bandwidth_consumption_page",tab="group",period=item,group_id=group_value or None,node=node_value or None)}">{item.upper()}</a>' for item in _NS.get("V5058C_PERIODS", ("1h","2h","6h","12h","24h","2d","7d")))
    pager = _consumption_pager(page_no, max_page, limit, period, q, coverage, sort_by, order, group_value, node_value)
    content = f'''<div class="card v5058c-shell"><div class="v5058c-head"><div><h2>Consumption</h2><p>Group totals are calculated from physical Node counters. Coverage is SUM(valid bucket seconds) / SUM(expected bucket seconds), never an average of Node percentages.</p></div><div class="v5058c-periods">{periods}</div></div><div class="v5058c-tabs"><a href="{url_for('bandwidth_consumption_page',tab='vm',period=period)}">VM Consumption</a><a href="{url_for('bandwidth_consumption_page',tab='node',period=period)}">Node Consumption</a><a class="active" href="{url_for('bandwidth_consumption_page',tab='group',period=period)}">Group Consumption</a></div><div class="card v5060-filter-card">{toolbar}</div>{_group_consumption_table(rows)}<div class="table-hint">{total:,} Group row(s). Ungrouped is virtual and contains Nodes without a membership. VM rows never store a direct Group relation.</div>{pager}</div>'''
    return _NS["page"]("Consumption · Group", content)


def consumption_page():
    if str(request.args.get("tab") or "vm").lower() == "group":
        return group_consumption_page()
    response = _CONSUMPTION_BASE()
    try:
        html = response.get_data(as_text=True)
        marker = '</div>\n      <div class="v5058c-summary-grid">'
        group_link = f'<a href="{escape(url_for("bandwidth_consumption_page",tab="group",period=request.args.get("period") or "24h",group_id=_group_value() or None,node=_node_value() or None),quote=True)}">Group Consumption</a>'
        if marker in html and "Group Consumption" not in html:
            html = html.replace(marker, group_link + marker, 1)
        response.set_data(html)
    except Exception:
        _APP.logger.exception("Could not add Group Consumption tab")
    return response


def _wrap_row_function(name: str, *, tuple_position: int | None = None) -> None:
    base = _NS.get(name)
    if not callable(base):
        return
    def wrapped(*args, **kwargs):
        result = base(*args, **kwargs)
        if tuple_position is None:
            return _filter_rows(result, 0)
        if not isinstance(result, tuple) or len(result) <= tuple_position:
            return result
        values = list(result)
        values[tuple_position] = _filter_rows(values[tuple_position], 0)
        return tuple(values)
    wrapped.__name__ = getattr(base, "__name__", name)
    _NS[name] = wrapped



def _wrap_top_vm() -> None:
    base = _NS.get("get_top_vm_rows")
    if not callable(base):
        return
    def wrapped(period, q="", sort_by="total", order="desc", scope="all", limit=100):
        requested = max(10, min(1000, _safe_int(limit, 100)))
        if not _group_value() and not _node_value():
            return base(period, q=q, sort_by=sort_by, order=order, scope=scope, limit=requested)
        rows, selected_bucket, latest_bucket, _ = base(
            period, q=q, sort_by=sort_by, order=order, scope=scope, limit=1000,
        )
        filtered = _filter_rows(rows, 0)[:requested]
        return filtered, selected_bucket, latest_bucket, requested
    wrapped.__name__ = getattr(base, "__name__", "get_top_vm_rows")
    _NS["get_top_vm_rows"] = wrapped


def _wrap_abuse_queries() -> None:
    current_base = _NS.get("_v48139_current_rows")
    if callable(current_base):
        def current_rows(values):
            if not _group_value() and not _node_value():
                return current_base(values)
            requested_page = max(1, _safe_int(values.get("page"), 1))
            requested_limit = max(10, min(500, _safe_int(values.get("limit"), 100)))
            expanded = dict(values)
            expanded["page"] = 1
            expanded["limit"] = 10000
            if _node_value():
                expanded["node"] = _node_value()
            rows, _total, _counts = current_base(expanded)
            filtered = _filter_rows(rows, 0)
            start = (requested_page - 1) * requested_limit
            page_rows = filtered[start:start + requested_limit]
            counts = {key: 0 for key in ("network", "cpu", "ram", "disk")}
            for row in filtered:
                flags = str(row[4] if len(row) > 4 else "").lower()
                for key in counts:
                    if key in flags:
                        counts[key] += 1
            return page_rows, len(filtered), counts
        current_rows.__name__ = getattr(current_base, "__name__", "_v48139_current_rows")
        _NS["_v48139_current_rows"] = current_rows

    events_base = _NS.get("_v48127_event_groups")
    if callable(events_base):
        def event_groups(values):
            if not _group_value() and not _node_value():
                return events_base(values)
            requested_page = max(1, _safe_int(values.get("page"), 1))
            requested_limit = max(10, min(200, _safe_int(values.get("limit"), 100)))
            all_rows = []
            all_details = {}
            for page_no in range(1, 51):
                expanded = dict(values)
                expanded["page"] = page_no
                expanded["limit"] = 200
                if _node_value():
                    expanded["node"] = _node_value()
                rows, total, details = events_base(expanded)
                all_rows.extend(rows)
                all_details.update(details)
                if page_no * 200 >= total or not rows:
                    break
            filtered = _filter_rows(all_rows, 0)
            start = (requested_page - 1) * requested_limit
            page_rows = filtered[start:start + requested_limit]
            keys = {(str(row[0]), str(row[1])) for row in page_rows}
            page_details = {key: value for key, value in all_details.items() if key in keys}
            return page_rows, len(filtered), page_details
        event_groups.__name__ = getattr(events_base, "__name__", "_v48127_event_groups")
        _NS["_v48127_event_groups"] = event_groups


def install(ns: dict[str, Any]) -> None:
    global _NS, _APP, _DB_BASE, _PAGE_BASE, _CONSUMPTION_BASE
    if ns.get("_V5060_NODE_GROUPS_INSTALLED"):
        return
    ns["_V5060_NODE_GROUPS_INSTALLED"] = True
    _NS = ns
    _APP = ns["app"]
    _DB_BASE = ns["db"]
    _PAGE_BASE = ns["page"]
    _CONSUMPTION_BASE = _APP.view_functions.get("bandwidth_consumption_page")

    # New DB tables are initialized lazily on the first normal connection.
    ns["db"] = db

    # Register only new feature endpoints. Existing endpoint names and payloads remain unchanged.
    _APP.add_url_rule("/static/flags/4x3/<path:filename>", "v5060_flag_svg", flag_svg, methods=["GET"])
    _APP.add_url_rule("/admin/node-groups/save", "v5060_group_save", group_save, methods=["POST"])
    _APP.add_url_rule("/admin/node-groups/delete", "v5060_group_delete", group_delete, methods=["POST"])
    _APP.add_url_rule("/admin/nodes/group", "v5060_node_group_set", node_group_set, methods=["POST"])

    # Filter the principal Node/VM tables before their established renderers run.
    _wrap_row_function("get_node_rows", tuple_position=0)
    _wrap_row_function("get_node_health_rows")
    _wrap_top_vm()
    _wrap_abuse_queries()

    _wrap_consumption_queries()

    # Replace only the effective server-rendered page implementations.
    ns["page"] = page
    _APP.view_functions["admin_page"] = admin_page
    if _CONSUMPTION_BASE is not None:
        _APP.view_functions["bandwidth_consumption_page"] = consumption_page

    # Expose helpers for tests and future presentation-only renderers.
    ns["v5060_node_group_map"] = node_group_map
    ns["v5060_node_identity_html"] = node_identity_html
    ns["v5060_group_matches"] = _group_matches
