V48124_VERSION = "48.12.4"
MAX_ACTIVE_MAINTENANCE_JOBS = 1
V48124_MAX_PURGE_SELECTION_ITEMS = max(
    1, min(1000, int(os.environ.get("BW_MAX_PURGE_SELECTION_ITEMS", "300")))
)
V48124_ENQUEUE_BUSY_TIMEOUT_MS = max(
    500, min(15000, int(os.environ.get("BW_MAINTENANCE_ENQUEUE_BUSY_TIMEOUT_MS", "3000")))
)

def _v48124_maintenance_runner_paths():
    runner = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maintenance.py")
    if not os.path.isfile(runner):
        raise RuntimeError(f"Maintenance runner is missing: {runner}")
    systemctl = shutil.which("systemctl")
    if not systemctl:
        raise RuntimeError("systemctl is not installed")
    template_path = "/etc/systemd/system/bw-monitor-maintenance@.service"
    if not os.path.isfile(template_path):
        raise RuntimeError(f"Maintenance service template is missing: {template_path}")
    return systemctl

def enqueue_batched_purge_jobs(action, items, actor):
    """Queue one exclusive job; the worker performs internal batches.

    The previous implementation created one systemd unit per three selected
    items. A large selection could therefore start dozens of units at once.
    """
    action = str(action or "").strip().lower()
    if action not in {"purge_nodes", "purge_node_vms", "purge_vms"}:
        raise ValueError("Unsupported purge action")
    clean = []
    seen = set()
    if action == "purge_vms":
        for value in items or []:
            if not isinstance(value, dict):
                continue
            node = str(value.get("node") or "").strip()
            vm_uuid = str(value.get("vm_uuid") or "").strip()
            key = (node, vm_uuid)
            if node and vm_uuid and key not in seen:
                seen.add(key)
                clean.append({"node": node, "vm_uuid": vm_uuid})
        parameters = {"vms": clean, "batch_size": MAX_PURGE_ITEMS_PER_JOB}
    else:
        for value in items or []:
            node = str(value or "").strip()
            if node and node not in seen:
                seen.add(node)
                clean.append(node)
        parameters = {"nodes": clean, "batch_size": MAX_PURGE_ITEMS_PER_JOB}
    if not clean:
        raise ValueError("No valid purge item was selected")
    if len(clean) > V48124_MAX_PURGE_SELECTION_ITEMS:
        raise ValueError(
            f"Selection has {len(clean)} items; maximum is {V48124_MAX_PURGE_SELECTION_ITEMS}"
        )
    job_id, unit_name = enqueue_maintenance_job(action, parameters, actor)
    return [(job_id, unit_name, len(clean))]

def _v48124_busy_admin_redirect(message):
    return redirect(url_for("admin_page", dberr=message) + "#maintenance-queue")

_v48124_admin_delete_node_base = app.view_functions.get("admin_delete_node")
_v48124_admin_delete_vm_base = app.view_functions.get("admin_delete_vm")

def admin_delete_node_v48124():
    deny = require_admin()
    if deny:
        return deny
    mode = str(request.form.get("mode") or "soft").strip().lower()
    if mode == "purge":
        return _v48124_admin_delete_node_base()
    node = str(request.form.get("node") or "").strip()
    if not node:
        return Response("Missing node\n", status=400, mimetype="text/plain")
    conn = db()
    try:
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """UPDATE node_inventory
               SET status='hidden',hidden_at=COALESCE(hidden_at,?),deleted_at=NULL
               WHERE node=?""",
            (now_ts(), node),
        )
        conn.commit()
    except dbapi.OperationalError as exc:
        conn.rollback()
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            return _v48124_busy_admin_redirect(
                "Database is busy. The node was not changed; wait for the active maintenance job."
            )
        raise
    finally:
        conn.close()
    return redirect(url_for("admin_page"))

def admin_delete_vm_v48124():
    deny = require_admin()
    if deny:
        return deny
    mode = str(request.form.get("mode") or "soft").strip().lower()
    if mode == "purge":
        return _v48124_admin_delete_vm_base()
    node = str(request.form.get("node") or "").strip()
    vm_uuid = str(request.form.get("vm_uuid") or "").strip()
    if not node or not vm_uuid:
        return Response("Missing node or vm_uuid\n", status=400, mimetype="text/plain")
    conn = db()
    try:
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """UPDATE vm_inventory
               SET status='hidden',hidden_at=COALESCE(hidden_at,?),deleted_at=NULL
               WHERE node=? AND vm_uuid=?""",
            (now_ts(), node, vm_uuid),
        )
        conn.commit()
    except dbapi.OperationalError as exc:
        conn.rollback()
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            return _v48124_busy_admin_redirect(
                "Database is busy. The VM was not changed; wait for the active maintenance job."
            )
        raise
    finally:
        conn.close()
    return redirect(url_for("admin_page"))

if _v48124_admin_delete_node_base is not None:
    app.view_functions["admin_delete_node"] = admin_delete_node_v48124
if _v48124_admin_delete_vm_base is not None:
    app.view_functions["admin_delete_vm"] = admin_delete_vm_v48124

V48124_UI_JS = r"""
<script id="v48124-submit-once">
(function(){
  document.addEventListener('submit',function(event){
    var form=event.target;
    if(!form || String(form.method||'').toLowerCase()!=='post') return;
    if(event.defaultPrevented) return;
    if(form.dataset.bwSubmitting==='1'){
      event.preventDefault();
      return;
    }
    form.dataset.bwSubmitting='1';
    window.setTimeout(function(){
      form.querySelectorAll('button[type="submit"],input[type="submit"]').forEach(function(btn){
        btn.disabled=true;
        if(btn.tagName==='BUTTON') btn.dataset.bwOldText=btn.textContent,btn.textContent='Working…';
      });
    },0);
  },false);
})();
</script>
"""

_page_v48124_base = page

def page(title, content):
    response = _page_v48124_base(title, content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace("</body>", V48124_UI_JS + "</body>", 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.12.4 submit-once guard")
    return response

_v48124_admin_restore_node_base = app.view_functions.get("admin_restore_node")
_v48124_admin_restore_vm_base = app.view_functions.get("admin_restore_vm")
_v48124_admin_bulk_nodes_base = app.view_functions.get("admin_bulk_nodes")
_v48124_admin_bulk_vms_base = app.view_functions.get("admin_bulk_vms")

def _v48124_inventory_write(executor):
    conn = db()
    try:
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute("BEGIN IMMEDIATE")
        executor(conn)
        conn.commit()
        return None
    except dbapi.OperationalError as exc:
        conn.rollback()
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            return _v48124_busy_admin_redirect(
                "Database is busy. No inventory change was committed; wait for the active maintenance job."
            )
        raise
    finally:
        conn.close()

def admin_restore_node_v48124():
    deny = require_admin()
    if deny:
        return deny
    node = str(request.form.get("node") or "").strip()
    if not node:
        return Response("Missing node\n", status=400, mimetype="text/plain")
    response = _v48124_inventory_write(
        lambda conn: conn.execute(
            """UPDATE node_inventory SET status='active',hidden_at=NULL,deleted_at=NULL
               WHERE node=?""",
            (node,),
        )
    )
    return response or redirect(url_for("admin_page"))

def admin_restore_vm_v48124():
    deny = require_admin()
    if deny:
        return deny
    node = str(request.form.get("node") or "").strip()
    vm_uuid = str(request.form.get("vm_uuid") or "").strip()
    if not node or not vm_uuid:
        return Response("Missing node or vm_uuid\n", status=400, mimetype="text/plain")
    response = _v48124_inventory_write(
        lambda conn: conn.execute(
            """UPDATE vm_inventory SET status='active',hidden_at=NULL,deleted_at=NULL
               WHERE node=? AND vm_uuid=?""",
            (node, vm_uuid),
        )
    )
    return response or redirect(url_for("admin_page"))

def admin_bulk_nodes_v48124():
    action = str(request.form.get("action") or "hide").strip().lower()
    if action in {"purge", "purge_vms"}:
        return _v48124_admin_bulk_nodes_base()
    deny = require_admin()
    if deny:
        return deny
    nodes, seen = [], set()
    for value in request.form.getlist("nodes"):
        node = str(value or "").strip()
        if node and node not in seen:
            seen.add(node)
            nodes.append(node)
    if not nodes:
        return redirect(url_for("admin_page"))
    if action not in {"hide", "restore"}:
        return Response("Invalid node action\n", status=400, mimetype="text/plain")

    def write(conn):
        for node in nodes:
            if action == "restore":
                conn.execute(
                    "UPDATE node_inventory SET status='active',hidden_at=NULL,deleted_at=NULL WHERE node=?",
                    (node,),
                )
            else:
                conn.execute(
                    """UPDATE node_inventory
                       SET status='hidden',hidden_at=COALESCE(hidden_at,?),deleted_at=NULL
                       WHERE node=?""",
                    (now_ts(), node),
                )
    response = _v48124_inventory_write(write)
    if response:
        return response
    actor = session.get("admin_username") or dashboard_username()
    log_account_event(
        "bulk_node_action", username=actor, realm="admin", role="admin",
        detail=f"action={action};nodes={','.join(nodes[:100])}",
    )
    return redirect(url_for("admin_page"))

def admin_bulk_vms_v48124():
    action = str(request.form.get("action") or "hide").strip().lower()
    if action == "purge":
        return _v48124_admin_bulk_vms_base()
    deny = require_admin()
    if deny:
        return deny
    selected, seen = [], set()
    for value in request.form.getlist("vms"):
        if "\t" not in str(value):
            continue
        node, vm_uuid = str(value).split("\t", 1)
        node, vm_uuid = node.strip(), vm_uuid.strip()
        key = (node, vm_uuid)
        if node and vm_uuid and key not in seen:
            seen.add(key)
            selected.append({"node": node, "vm_uuid": vm_uuid})
    if not selected:
        return redirect(url_for("admin_page"))
    if action not in {"hide", "restore"}:
        return Response("Invalid VM action\n", status=400, mimetype="text/plain")

    def write(conn):
        for item in selected:
            node, vm_uuid = item["node"], item["vm_uuid"]
            if action == "restore":
                conn.execute(
                    """UPDATE vm_inventory SET status='active',hidden_at=NULL,deleted_at=NULL
                       WHERE node=? AND vm_uuid=?""",
                    (node, vm_uuid),
                )
            else:
                conn.execute(
                    """UPDATE vm_inventory
                       SET status='hidden',hidden_at=COALESCE(hidden_at,?),deleted_at=NULL
                       WHERE node=? AND vm_uuid=?""",
                    (now_ts(), node, vm_uuid),
                )
    response = _v48124_inventory_write(write)
    if response:
        return response
    actor = session.get("admin_username") or dashboard_username()
    affected_nodes = sorted({item["node"] for item in selected})
    log_account_event(
        "bulk_vm_action", username=actor, realm="admin", role="admin",
        detail=f"action={action};selected={len(selected)};nodes={','.join(affected_nodes[:100])}",
    )
    return redirect(url_for("admin_page"))

if _v48124_admin_restore_node_base is not None:
    app.view_functions["admin_restore_node"] = admin_restore_node_v48124
if _v48124_admin_restore_vm_base is not None:
    app.view_functions["admin_restore_vm"] = admin_restore_vm_v48124
if _v48124_admin_bulk_nodes_base is not None:
    app.view_functions["admin_bulk_nodes"] = admin_bulk_nodes_v48124
if _v48124_admin_bulk_vms_base is not None:
    app.view_functions["admin_bulk_vms"] = admin_bulk_vms_v48124

