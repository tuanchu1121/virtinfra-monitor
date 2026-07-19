# v48.12.3 safe compact workflow
# - batched history deletion stays online
# - PostgreSQL VACUUM ANALYZE remains online; destructive jobs are still serialized
# - API log cleanup stays online unless compact is explicitly requested

# v48.12.2 maintenance queue render fix
# ---------------------------------------------------------------------------
V48122_MAINTENANCE_FIX = True

# ---------------------------------------------------------------------------
# v48.12.2 API admin polish, editable allowlists, password UX and proxy support
# ---------------------------------------------------------------------------
V48122_VERSION = "48.12.2"
V48123_VERSION = "48.12.3"

# Optional scope for external operational tools that need API connection/audit logs.
API_SUPPORTED_SCOPES["api_logs:read"] = "Read API request logs and API management/authentication events"


def _v48122_scope_checkboxes(selected=None):
    selected = set(selected if selected is not None else API_DEFAULT_SCOPES)
    groups = [
        ("Abuse monitoring", ("abuse:read", "abuse_events:read"), "Recommended"),
        ("Extended monitor data", ("vm:read", "node:read", "bandwidth:read"), "Optional"),
        ("API observability", ("api_logs:read",), "Optional"),
    ]
    html = []
    for title, scopes, badge in groups:
        html.append(
            f'<div class="api-scope-section"><div class="api-scope-heading">'
            f'<b>{escape(title)}</b><span>{escape(badge)}</span></div>'
        )
        for scope in scopes:
            label = API_SUPPORTED_SCOPES.get(scope, scope)
            checked = ' checked' if scope in selected else ''
            html.append(
                f'<label class="api-scope"><input type="checkbox" name="scopes" '
                f'value="{escape(scope, quote=True)}"{checked}>'
                f'<span><b>{escape(scope)}</b><small>{escape(label)}</small></span></label>'
            )
        html.append('</div>')
    return ''.join(html)


def _v48120_api_scope_checkboxes():
    return _v48122_scope_checkboxes()


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
        scopes = ''.join(
            f'<span class="api-chip">{escape(scope)}</span>'
            for scope in key.get('scopes') or []
        ) or '-'
        allowed = '<br>'.join(escape(x) for x in key.get('allowed_ips') or []) \
            or '<span class="muted">Any source</span>'
        expiry = fmt_full(key.get('expires_at')) if key.get('expires_at') else 'Never'
        used = fmt_full(key.get('last_used_at')) if key.get('last_used_at') else 'Never'
        edit_link = (
            f'<a class="btn" href="{url_for("admin_api_key_edit", key_id=key["key_id"])}">'
            f'Edit</a>'
        )
        rotate_revoke = ''
        if status_label == 'Active':
            rotate_revoke = f'''
              <form method="post" action="{url_for('admin_api_key_rotate')}" onsubmit="return confirm('Rotate this key? The current secret will stop working immediately.')">
                <input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}"><input type="hidden" name="key_id" value="{escape(key['key_id'], quote=True)}"><button class="btn" type="submit">Rotate</button>
              </form>
              <form method="post" action="{url_for('admin_api_key_revoke')}" onsubmit="return confirm('Revoke this key now?')">
                <input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}"><input type="hidden" name="key_id" value="{escape(key['key_id'], quote=True)}"><button class="btn-warn" type="submit">Revoke</button>
              </form>'''
        delete_phrase = f"DELETE {key['key_id']}"
        delete_form = f'''
          <form method="post" action="{url_for('admin_api_key_delete')}" onsubmit="const expected='{escape(delete_phrase, quote=True)}';const v=prompt('Permanently delete this key and ALL of its API logs? Type: '+expected);if(v!==expected)return false;this.querySelector('[name=confirm_text]').value=v;return confirm('This cannot be undone. Continue?')">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}"><input type="hidden" name="key_id" value="{escape(key['key_id'], quote=True)}"><input type="hidden" name="confirm_text" value=""><button class="btn-danger" type="submit">Delete permanently</button>
          </form>'''
        note_html = f'<small>{escape(key.get("note") or "")}</small>' if key.get('note') else ''
        body.append(f'''
        <tr>
          <td><b>{escape(key['name'])}</b><code class="key-id">{escape(API_KEY_PREFIX)}_{escape(key['key_id'])}_…</code>{note_html}</td>
          <td><span class="status {status_class}">{escape(status_label)}</span><small>Created {escape(fmt_full(key['created_at']))}<br>by {escape(key.get('created_by') or '-')}</small></td>
          <td><div class="api-chip-wrap">{scopes}</div></td>
          <td><small>{allowed}</small></td>
          <td><b>{escape(used)}</b><small>{escape(key.get('last_used_ip') or '-')} · {safe_int(key.get('use_count'), 0):,} flush(es)</small></td>
          <td>{escape(expiry)}</td>
          <td><div class="api-actions">{edit_link}{rotate_revoke}{delete_form}</div></td>
        </tr>''')
    if not body:
        body.append(
            '<tr><td colspan="7" class="empty">No API keys. '
            'Create the first integration key above.</td></tr>'
        )
    return ''.join(body), len(keys)


def _v48122_expiration_value(value, current):
    value = str(value or 'keep').strip().lower()
    if value == 'keep':
        return safe_int(current, 0) or None
    if value == 'never':
        return None
    if value not in {'7', '30', '90', '180', '365'}:
        raise ValueError('Invalid expiration option.')
    return now_ts() + int(value) * 86400


@app.route('/admin/api-keys/edit', methods=['GET', 'POST'])
def admin_api_key_edit():
    auth = require_admin()
    if auth:
        return auth
    key_id = str(request.values.get('key_id') or '').strip().lower()
    conn = db()
    try:
        key = _api_get_key_by_id(conn, key_id)
    finally:
        conn.close()
    if not key:
        return Response('API key not found\n', status=404, mimetype='text/plain')

    if request.method == 'POST':
        actor = _api_admin_actor()
        try:
            name = _api_clean_name(request.form.get('name') or key.get('name'))
            scopes = _api_clean_scopes(request.form.getlist('scopes'))
            if not scopes:
                raise ValueError('Select at least one API permission.')
            allowed_ips = _api_normalize_allowlist(request.form.get('allowed_ips') or '')
            expires_at = _v48122_expiration_value(
                request.form.get('expiration'), key.get('expires_at')
            )
            note = str(request.form.get('note') or '').strip()[:500]
            before = {
                'name': key.get('name'),
                'scopes': key.get('scopes') or [],
                'allowed_ips': key.get('allowed_ips') or [],
                'expires_at': key.get('expires_at'),
                'note': key.get('note') or '',
            }
            conn = db()
            try:
                conn.execute('BEGIN IMMEDIATE')
                conn.execute(
                    '''UPDATE api_keys
                       SET name=?,scopes_json=?,allowed_ips_json=?,expires_at=?,note=?
                       WHERE key_id=?''',
                    (
                        name,
                        json.dumps(scopes, separators=(',', ':')),
                        json.dumps(allowed_ips, separators=(',', ':')),
                        expires_at,
                        note,
                        key_id,
                    ),
                )
                after = {
                    'name': name,
                    'scopes': scopes,
                    'allowed_ips': allowed_ips,
                    'expires_at': expires_at,
                    'note': note,
                }
                detail = json.dumps(
                    {'before': before, 'after': after}, separators=(',', ':')
                )
                _api_log_event(
                    conn,
                    'KEY_UPDATED',
                    key_id=key_id,
                    key_name=name,
                    actor=actor,
                    source_ip=api_client_ip(),
                    detail=detail[:1000],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            return _api_admin_redirect(
                msg=f'API key {name} was updated. The existing secret remains valid.'
            )
        except Exception as exc:
            return redirect(
                url_for('admin_api_key_edit', key_id=key_id, apierr=str(exc)[:500])
            )

    err = str(request.args.get('apierr') or '').strip()
    allowed_text = '\n'.join(key.get('allowed_ips') or [])
    scopes_html = _v48122_scope_checkboxes(key.get('scopes') or [])
    status_label, status_class = _api_admin_status(key)
    current_expiry = fmt_full(key.get('expires_at')) if key.get('expires_at') else 'Never'
    last_used = fmt_full(key.get('last_used_at')) if key.get('last_used_at') else 'Never'
    content = f'''
    <style>
    .api-edit-grid{{display:grid;grid-template-columns:minmax(0,1fr) minmax(280px,.42fr);gap:16px;align-items:start}}.api-edit-form{{display:grid;gap:13px}}.api-edit-form label{{display:grid;gap:6px;font-size:12px;font-weight:850}}.api-edit-form input,.api-edit-form textarea,.api-edit-form select{{width:100%;box-sizing:border-box}}.api-edit-form textarea{{min-height:118px}}.api-scope-section{{display:grid;gap:7px;padding:11px;border:1px solid var(--line,#d0d5dd);border-radius:11px}}.api-scope-heading{{display:flex;justify-content:space-between;gap:8px;align-items:center}}.api-scope-heading span{{font-size:9px;font-weight:900;padding:3px 7px;border-radius:999px;background:#eaf2ff;color:#175cd3}}.api-scope{{display:flex;gap:9px;padding:10px;border:1px solid var(--line,#d0d5dd);border-radius:9px}}.api-scope span{{display:grid;gap:3px}}.api-scope small{{color:#667085;font-size:10px}}.api-key-summary{{display:grid;gap:10px}}.api-key-summary>div{{padding:11px;border:1px solid var(--line,#d0d5dd);border-radius:10px}}.api-key-summary small{{display:block;color:#667085;font-size:10px;text-transform:uppercase;font-weight:900}}.api-key-summary b,.api-key-summary code{{display:block;margin-top:5px;word-break:break-all}}@media(max-width:900px){{.api-edit-grid{{grid-template-columns:1fr}}}}
    </style>
    <div class="card page-hero"><div><span class="eyebrow">ADMIN / API KEY</span><h2>Edit API key</h2><p>Add or remove Allowed IP/CIDR entries without rotating the secret or creating a new key.</p></div><div class="hero-meta"><span>Status <b class="status {status_class}">{escape(status_label)}</b></span></div></div>
    {_v490_admin_nav('api')}
    {f'<div class="error-box">{escape(err)}</div>' if err else ''}
    <div class="api-edit-grid">
      <div class="card"><form class="api-edit-form" method="post" action="{url_for('admin_api_key_edit')}">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}"><input type="hidden" name="key_id" value="{escape(key_id, quote=True)}">
        <label>Name<input name="name" maxlength="80" value="{escape(key.get('name') or '', quote=True)}" required></label>
        <div>{scopes_html}</div>
        <label>Allowed source IP/CIDR<textarea name="allowed_ips" placeholder="One per line. Empty means any source.">{escape(allowed_text)}</textarea><small>Changes apply immediately. Existing API secret is preserved.</small></label>
        <label>Expiration<select name="expiration"><option value="keep">Keep current ({escape(current_expiry)})</option><option value="never">Never</option><option value="7">7 days from now</option><option value="30">30 days from now</option><option value="90">90 days from now</option><option value="180">180 days from now</option><option value="365">365 days from now</option></select></label>
        <label>Note<input name="note" maxlength="500" value="{escape(key.get('note') or '', quote=True)}" placeholder="Owner, app or purpose"></label>
        <div class="api-actions"><button class="btn primary-action" type="submit">Save changes</button><a class="btn" href="{url_for('admin_api_keys_page', tab='keys')}">Cancel</a></div>
      </form></div>
      <div class="card api-key-summary"><h3>Key identity</h3><div><small>Key ID</small><code>{escape(API_KEY_PREFIX)}_{escape(key_id)}_…</code></div><div><small>Last used</small><b>{escape(last_used)}</b><span>{escape(key.get('last_used_ip') or '-')}</span></div><div><small>Important</small><b>The secret does not change</b><span>Use Rotate only when the secret itself must be replaced.</span></div></div>
    </div>'''
    return page('Edit API Key', content)


def _v48122_api_log_filters():
    limit, offset = _api_limit_offset(default=100)
    since = max(0, safe_int(request.args.get('since'), 0))
    key_id = str(request.args.get('key_id') or '').strip().lower()
    return limit, offset, since, key_id


@app.route('/api/v1/logs/requests', methods=['GET'])
@require_api_scopes('api_logs:read')
def api_v1_request_logs():
    limit, offset, since, key_id = _v48122_api_log_filters()
    where, params = [], []
    if since:
        where.append('request_time>=?')
        params.append(since)
    if key_id:
        where.append('key_id=?')
        params.append(key_id)
    where_sql = (' WHERE ' + ' AND '.join(where)) if where else ''
    conn = db()
    try:
        total = safe_int(
            conn.execute(
                f'SELECT COUNT(*) FROM api_access_logs{where_sql}', params
            ).fetchone()[0],
            0,
        )
        rows = conn.execute(
            f'''SELECT request_time,request_id,key_id,key_name,source_ip,method,
                       path,query_string,status_code,duration_ms,response_bytes,
                       user_agent,error_code
                FROM api_access_logs{where_sql}
                ORDER BY request_time DESC,id DESC LIMIT ? OFFSET ?''',
            params + [limit, offset],
        ).fetchall()
    finally:
        conn.close()
    data = []
    for r in rows:
        data.append({
            'request_time': safe_int(r[0], 0),
            'request_id': str(r[1] or ''),
            'key_id': str(r[2] or ''),
            'key_name': str(r[3] or ''),
            'source_ip': str(r[4] or ''),
            'method': str(r[5] or ''),
            'path': str(r[6] or ''),
            'query_string': str(r[7] or ''),
            'status_code': safe_int(r[8], 0),
            'duration_ms': round(safe_float(r[9], 0), 3),
            'response_bytes': safe_int(r[10], 0),
            'user_agent': str(r[11] or ''),
            'error_code': str(r[12] or ''),
        })
    return _api_response({
        'data': data,
        'meta': {'total': total, 'count': len(data), 'limit': limit, 'offset': offset},
    })


@app.route('/api/v1/logs/events', methods=['GET'])
@require_api_scopes('api_logs:read')
def api_v1_management_logs():
    limit, offset, since, key_id = _v48122_api_log_filters()
    event_type = str(request.args.get('event_type') or '').strip().upper()
    where, params = [], []
    if since:
        where.append('event_time>=?')
        params.append(since)
    if key_id:
        where.append('key_id=?')
        params.append(key_id)
    if event_type:
        where.append('event_type=?')
        params.append(event_type)
    where_sql = (' WHERE ' + ' AND '.join(where)) if where else ''
    conn = db()
    try:
        total = safe_int(
            conn.execute(
                f'SELECT COUNT(*) FROM api_key_events{where_sql}', params
            ).fetchone()[0],
            0,
        )
        rows = conn.execute(
            f'''SELECT event_time,event_type,key_id,key_name,actor,source_ip,detail
                FROM api_key_events{where_sql}
                ORDER BY event_time DESC,id DESC LIMIT ? OFFSET ?''',
            params + [limit, offset],
        ).fetchall()
    finally:
        conn.close()
    data = [
        {
            'event_time': safe_int(r[0], 0),
            'event_type': str(r[1] or ''),
            'key_id': str(r[2] or ''),
            'key_name': str(r[3] or ''),
            'actor': str(r[4] or ''),
            'source_ip': str(r[5] or ''),
            'detail': str(r[6] or ''),
        }
        for r in rows
    ]
    return _api_response({
        'data': data,
        'meta': {'total': total, 'count': len(data), 'limit': limit, 'offset': offset},
    })


def _v48120_docs_tab():
    base = request.url_root.rstrip('/')
    return f'''
    <div class="docs-grid">
      <div class="card"><span class="eyebrow">ABUSE-FIRST API V1</span><h3>Primary monitoring endpoints</h3><p class="muted">Abuse remains the primary workflow, while VM, Node, Bandwidth and API Log endpoints are available when an integration needs more context.</p><div class="endpoint-list"><div><code>GET /api/v1/me</code><span>Validate key and show granted scopes</span></div><div><code>GET /api/v1/health</code><span>Application and database health</span></div><div><code>GET /api/v1/abuse/summary</code><span>Counts by type, flag and node</span></div><div><code>GET /api/v1/abuse/vms</code><span>Compact current Abuse list by default</span></div><div><code>GET /api/v1/abuse/vms?view=full</code><span>Full CPU/network/disk/sample payload</span></div><div><code>GET /api/v1/abuse/vms/&lt;uuid&gt;?node=&lt;node&gt;</code><span>One active Abuse VM</span></div><div><code>GET /api/v1/abuse/events</code><span>Persistent Abuse history / logs</span></div></div></div>
      <div class="card"><h3>Quick test</h3><pre class="api-code">API_KEY='bwm_live_xxxxxxxxxxxx_SECRET'

curl -sS \\
-H "Authorization: Bearer ${{API_KEY}}" \\
'{escape(base)}/api/v1/abuse/vms?limit=500' | jq</pre><h3 style="margin-top:18px">Only UUIDs</h3><pre class="api-code">curl -sS \\
-H "Authorization: Bearer ${{API_KEY}}" \\
'{escape(base)}/api/v1/abuse/vms?limit=500' \\
| jq -r '.data[].vm_uuid'</pre></div>
    </div>
    <div class="card" style="margin-top:14px"><span class="eyebrow">EXTENDED READ-ONLY API</span><h3>Optional context endpoints</h3><div class="endpoint-list"><div><code>GET /api/v1/vms</code><span>Current VM metrics, scope <b>vm:read</b></span></div><div><code>GET /api/v1/vms/&lt;uuid&gt;/current?node=&lt;node&gt;</code><span>One VM snapshot, scope <b>vm:read</b></span></div><div><code>GET /api/v1/nodes</code><span>Lightweight node context, scope <b>node:read</b></span></div><div><code>GET /api/v1/bandwidth/vms</code><span>Current VM Mbps/PPS, scope <b>bandwidth:read</b></span></div><div><code>GET /api/v1/bandwidth/vms/&lt;uuid&gt;?node=&lt;node&gt;</code><span>One VM network snapshot, scope <b>bandwidth:read</b></span></div><div><code>GET /api/v1/logs/requests</code><span>API connection/request logs, scope <b>api_logs:read</b></span></div><div><code>GET /api/v1/logs/events</code><span>Key lifecycle and authentication events, scope <b>api_logs:read</b></span></div></div></div>'''


# Controlled reverse-proxy support. Enable only when port 8080 is not publicly
# reachable and Nginx/HAProxy is the sole trusted hop.
WEB_TRUST_PROXY = os.environ.get('BW_WEB_TRUST_PROXY', '0') == '1'
if WEB_TRUST_PROXY:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)


V48122_UI_CSS = r"""
<style id="v48122-ui-polish">
.api-scope-section{display:grid;gap:7px;padding:10px;border:1px solid var(--line,#d0d5dd);border-radius:11px;margin-bottom:9px}
.api-scope-heading{display:flex;justify-content:space-between;gap:8px;align-items:center}
.api-scope-heading>span{font-size:9px;font-weight:900;padding:3px 7px;border-radius:999px;background:#eaf2ff;color:#175cd3}
.bw-password-wrap{position:relative;display:block;width:100%}
.bw-password-wrap>input{width:100%!important;padding-right:70px!important}
.bw-password-toggle{position:absolute;right:7px;top:50%;transform:translateY(-50%);height:30px;padding:0 10px;border:1px solid var(--line,#d0d5dd);border-radius:7px;background:var(--input,#fff);color:var(--text,#344054);font-size:10px;font-weight:900;cursor:pointer;z-index:2}
.bw-password-toggle:hover{border-color:#2f6fed;color:#175cd3}
html[data-theme=dark] body.app-v490 .api-scope-heading>span{background:#17365d;color:#b9d7ff}
html[data-theme=dark] body.app-v490 .bw-password-toggle{background:#10243a!important;border-color:#31577e!important;color:#d9e7f5!important}
</style>
"""

V48122_UI_JS = r"""
<script id="v48122-password-ui">
(function(){
  function ensurePasswordControls(root){
    (root||document).querySelectorAll('input[type="password"]').forEach(function(input){
      if(input.closest('.password-wrap')||input.closest('.bw-password-wrap')) return;
      var wrap=document.createElement('span');wrap.className='bw-password-wrap';
      input.parentNode.insertBefore(wrap,input);wrap.appendChild(input);
      var button=document.createElement('button');button.type='button';button.className='bw-password-toggle';button.textContent='Show';button.setAttribute('aria-label','Show password');wrap.appendChild(button);
    });
  }
  function toggle(button){
    var wrap=button.closest('.password-wrap,.bw-password-wrap');
    var input=null;
    var target=button.getAttribute('data-target');
    if(target) input=document.getElementById(target);
    if(!input&&wrap) input=wrap.querySelector('input');
    if(!input) return;
    var show=input.type==='password';input.type=show?'text':'password';button.textContent=show?'Hide':'Show';button.setAttribute('aria-label',show?'Hide password':'Show password');
  }
  document.addEventListener('click',function(event){var button=event.target.closest('.bw-password-toggle');if(!button)return;event.preventDefault();toggle(button)});
  function init(){ensurePasswordControls(document)}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
</script>
"""

_page_v48122_base = page


def page(title, content):
    response = _page_v48122_base(title, content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace('</head>', V48122_UI_CSS + '</head>', 1)
        html = html.replace('</body>', V48122_UI_JS + '</body>', 1)
        response.set_data(html)
    except Exception:
        app.logger.exception('Could not apply v48.12.2 UI polish layer')
    return response


# ---------------------------------------------------------------------------
