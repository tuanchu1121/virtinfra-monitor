def percent(used, total):
    if not total:
        return 0.0
    return round((float(used) / float(total)) * 100.0, 1)


def read_meminfo():
    data = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.replace(":", "").split()
                if len(parts) >= 2:
                    data[parts[0]] = int(parts[1]) * 1024
    except OSError:
        pass
    total = data.get("MemTotal", 0)
    available = data.get("MemAvailable", 0)
    used = max(0, total - available) if total else 0
    return total, used, available


def read_uptime_seconds():
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            return int(float(f.read().split()[0]))
    except Exception:
        return 0


def get_monitor_system_health():
    monitor_dir = os.path.dirname(DB) or "."
    try:
        disk = shutil.disk_usage(monitor_dir)
        disk_total, disk_used, disk_free = disk.total, disk.used, disk.free
    except Exception:
        disk_total = disk_used = disk_free = 0
    mem_total, mem_used, mem_available = read_meminfo()
    try:
        load1, load5, load15 = os.getloadavg()
    except Exception:
        load1 = load5 = load15 = 0.0
    try:
        _pg_stats = dbapi.database_stats()
    except Exception:
        _pg_stats = {}
    db_size = safe_int(_pg_stats.get("db_size"), 0)
    wal_size = safe_int(_pg_stats.get("wal_size"), 0)
    shm_size = 0
    node_count = vm_count = account_log_count = node_log_count = 0
    try:
        conn = db()
        try:
            node_count = conn.execute("SELECT COUNT(*) FROM node_inventory WHERE COALESCE(status, 'active') != 'hidden' AND deleted_at IS NULL").fetchone()[0] or 0
            vm_count = conn.execute("SELECT COUNT(*) FROM vm_inventory WHERE COALESCE(status, 'active') != 'hidden' AND deleted_at IS NULL").fetchone()[0] or 0
            account_log_count = conn.execute("SELECT COUNT(*) FROM account_logs").fetchone()[0] or 0
            node_log_count = conn.execute("SELECT COUNT(*) FROM node_logs").fetchone()[0] or 0
        finally:
            conn.close()
    except Exception:
        pass
    cpu_count = os.cpu_count() or 1
    disk_pct = percent(disk_used, disk_total)
    mem_pct = percent(mem_used, mem_total)
    load_pct = round((load1 / cpu_count) * 100.0, 1) if cpu_count else 0.0
    warnings = []
    if disk_pct >= 90:
        warnings.append("disk critical")
    elif disk_pct >= 80:
        warnings.append("disk high")
    if mem_pct >= 90:
        warnings.append("memory critical")
    elif mem_pct >= 80:
        warnings.append("memory high")
    if load1 >= cpu_count * 2:
        warnings.append("load high")
    return {
        "status": "Warning" if warnings else "OK", "warnings": ", ".join(warnings) if warnings else "No obvious issue",
        "hostname": platform.node() or "-", "pid": os.getpid(), "python": platform.python_version(), "uptime": read_uptime_seconds(),
        "cpu_count": cpu_count, "load1": load1, "load5": load5, "load15": load15, "load_pct": load_pct,
        "mem_total": mem_total, "mem_used": mem_used, "mem_available": mem_available, "mem_pct": mem_pct,
        "disk_path": monitor_dir, "disk_total": disk_total, "disk_used": disk_used, "disk_free": disk_free, "disk_pct": disk_pct,
        "db_size": db_size, "wal_size": wal_size, "shm_size": shm_size,
        "node_count": node_count, "vm_count": vm_count, "account_log_count": account_log_count, "node_log_count": node_log_count,
    }



MONITORING_DATA_TABLES = (
    # Fast/current state first, so stale 5m dashboard rows disappear even if a
    # very large historical cleanup is interrupted later.
    "vm_iface_current",
    "vm_current_fast",
    "node_current_fast",
    "vm_abuse_state",
    "vm_abuse_events",
    "vm_disk_current",
    "node_storage_current",
    "vm_latest_metrics",
    "node_host_latest",
    "node_filesystem_latest",
    "node_physical_net_latest",
    "node_bridge_addresses_latest",
    "agent_health_latest",
    "vm_location_latest",
    "vm_node_presence",
    # Inventory and event/current bookkeeping.
    "vm_inventory",
    "node_inventory",
    "vm_migration_events",
    "node_missed_events",
    "push_receipts",
    "node_push_snapshots",
    # Rollups and raw history.
    "bandwidth_daily",
    "bandwidth_hourly",
    "usage",
    "node_stats",
    "vm_perf_stats",
    "node_host_stats",
    "node_filesystem_stats",
    "node_physical_net_stats",
    "agent_health_stats",
    # Monitoring-side operational history. Account/admin logs are preserved.
    "node_logs",
    "retention_runs",
)


def clear_all_monitoring_data():
    """Delete all monitoring, inventory, current-cache and abuse rows.

    This deliberately preserves admin_settings, dashboard_users, account_logs
    and maintenance_jobs. It is intended to be called by the out-of-process
    maintenance worker while bw-monitor.service is stopped. Each table is
    committed separately, avoiding one enormous rollback transaction on very
    large PostgreSQL datasets.
    """
    result = {"tables": {}, "total_deleted": 0, "preserved": [
        "admin_settings", "dashboard_users", "account_logs", "maintenance_jobs"
    ]}
    for table in MONITORING_DATA_TABLES:
        conn = db()
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                result["tables"][table] = {"status": "missing", "deleted": 0}
                continue
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(f'DELETE FROM "{table}"')
            deleted = max(0, safe_int(cur.rowcount, 0))
            conn.commit()
            result["tables"][table] = {"status": "ok", "deleted": deleted}
            result["total_deleted"] += deleted
        except BaseException:
            try:
                conn.rollback()
            except BaseException:
                pass
            raise
        finally:
            conn.close()

    # Reset AUTOINCREMENT counters only for tables that were cleared. This is
    # cosmetic and safely skipped when sqlite_sequence does not exist.
    conn = db()
    try:
        has_sequence = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
        ).fetchone()
        if has_sequence:
            placeholders = ",".join("?" for _ in MONITORING_DATA_TABLES)
            conn.execute(
                f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})",
                tuple(MONITORING_DATA_TABLES),
            )
            conn.commit()
        conn.execute("PRAGMA optimize")
    finally:
        conn.close()
    return result


def get_database_maintenance_stats():
    """Cheap PostgreSQL size and dead-row stats. Never scan history on page load."""
    try:
        stats = dbapi.database_stats()
    except Exception:
        stats = {}
    db_size = safe_int(stats.get("db_size"), 0)
    wal_size = safe_int(stats.get("wal_size"), 0)
    dead_rows = safe_int(stats.get("freelist_count"), 0)
    page_size = safe_int(stats.get("page_size"), 8192)
    page_count = safe_int(stats.get("page_count"), 0)
    return {
        "db_size": db_size,
        "wal_size": wal_size,
        "shm_size": 0,
        "total_size": db_size + wal_size,
        "page_count": page_count,
        "freelist_count": dead_rows,
        "reusable_bytes": 0,
    }


def get_maintenance_jobs(limit=10):
    conn = db()
    try:
        return conn.execute("""
            SELECT id, created_at, started_at, finished_at, action, parameters,
                   status, requested_by, message, unit_name
            FROM maintenance_jobs
            ORDER BY id DESC
            LIMIT ?
        """, (max(1, min(50, safe_int(limit, 10))),)).fetchall()
    finally:
        conn.close()


def maintenance_status_badge(status):
    status = (status or "queued").strip().lower()
    if status == "ok":
        cls = "active"
    elif status in ("queued", "running"):
        cls = "yellow"
    else:
        cls = "red"
    return f'<span class="vm-state {cls}">{escape(status.upper())}</span>'


def database_maintenance_card(message="", error=""):
    s = get_database_maintenance_stats()
    jobs = get_maintenance_jobs(10)
    notice = f'<div class="error-box">{escape(error)}</div>' if error else (f'<div class="success-box">{escape(message)}</div>' if message else "")
    rows = ""
    for job_id, created_at, started_at, finished_at, action, parameters, status, requested_by, job_message, unit_name in jobs:
        rows += f"""<tr><td>{job_id}</td><td>{fmt_full(created_at)}</td><td>{escape(action or '-')}</td><td>{maintenance_status_badge(status)}</td><td>{fmt_full(started_at)}</td><td>{fmt_full(finished_at)}</td><td>{escape((job_message or '-')[:700])}</td><td class="mono">{escape(unit_name or '-')}</td></tr>"""
    if not rows:
        rows = '<tr><td colspan="8" class="empty">No maintenance jobs yet</td></tr>'
    return f"""
    <div class="card">
        <div class="table-title-row"><h3>Maintenance & Purge Queue</h3><div class="count-badges"><span>PostgreSQL data <b>{human(s['db_size'])}</b></span><span>WAL reserved/recycled <b>{human(s['wal_size'])}</b></span><span>Dead rows <b>{s['freelist_count']:,}</b></span></div></div>
        {notice}
        <div class="admin-note">Jobs run outside Gunicorn through <b>bw-monitor-maintenance@.service</b>. Purge actions are queued in batches of at most <b>3 nodes or VMs</b> and executed one batch at a time, so the Admin request returns immediately instead of holding a web worker.</div>
        <div class="bulk-bar">
            <form class="inline-form" method="post" action="{url_for('admin_database_maintenance')}" onsubmit="return confirm('Run bounded retention now? Latest 48 hours stay at 5-minute resolution; days 3-7 keep one real snapshot per hour; older history is deleted.')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}"><input type="hidden" name="action" value="retention"><button class="btn" type="submit">Run 2d raw / 7d retention</button></form>
            <form class="inline-form" method="post" action="{url_for('admin_database_maintenance')}" onsubmit="return confirm('Request PostgreSQL checkpoint? Normally this is not required.')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}"><input type="hidden" name="action" value="checkpoint"><button class="btn" type="submit">Checkpoint</button></form>
            <form class="inline-form" method="post" action="{url_for('admin_database_maintenance')}" onsubmit="return confirm('Run PostgreSQL VACUUM ANALYZE now? Continue?')"><input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}"><input type="hidden" name="action" value="vacuum"><label>Type <b>VACUUM</b><input name="confirm_text" autocomplete="off" placeholder="VACUUM" required></label><button class="btn" type="submit">VACUUM ANALYZE</button></form>
        </div>
        <div class="card db-danger" style="margin-top:14px;margin-bottom:14px;">
            <h3>Delete old history and optimize PostgreSQL</h3>
            <div class="admin-note"><b>Recommended:</b> delete old history first while the dashboard remains available. PostgreSQL reuses dead tuples after VACUUM. Routine VACUUM ANALYZE is online; use VACUUM FULL only during a planned maintenance window outside this tool.</div>
            <form class="bulk-bar" method="post" action="{url_for('admin_database_maintenance')}" onsubmit="return confirm('Delete old metric history in committed batches? The dashboard stays available, but some pages may be slower during the cleanup.')">
                <input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}"><input type="hidden" name="action" value="delete_history">
                <label>Delete metrics older than <select name="days"><option value="1">1 day</option><option value="3">3 days</option><option value="7" selected>7 days</option></select></label>
                <label>Type <b>DELETE HISTORY</b><input name="confirm_text" autocomplete="off" placeholder="DELETE HISTORY" required></label>
                <button class="btn-danger" type="submit">Delete history only</button>
            </form>
            <div class="admin-note" style="margin-top:12px"><b>Delete + compact:</b> history deletion runs first in batches while the web remains online. The maintenance worker then runs PostgreSQL <code>VACUUM (ANALYZE)</code>. Normal VACUUM is online and does not rewrite the whole database. The maintenance worker automatically restarts <code>bw-monitor.service</code> even if compact fails.</div>
            <form class="bulk-bar" method="post" action="{url_for('admin_database_maintenance')}" onsubmit="return confirm('Delete old history and then run PostgreSQL VACUUM ANALYZE?')">
                <input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}"><input type="hidden" name="action" value="delete_compact">
                <label>Delete metrics older than <select name="days"><option value="1">1 day</option><option value="3">3 days</option><option value="7" selected>7 days</option></select></label>
                <label>Type <b>DELETE AND OPTIMIZE</b><input name="confirm_text" autocomplete="off" placeholder="DELETE AND OPTIMIZE" required></label>
                <button class="btn-danger" type="submit">Delete + compact (offline during VACUUM)</button>
            </form>
        </div>
        <div class="card db-danger" style="margin-top:14px;margin-bottom:14px;border-color:#ef4444;">
            <h3>Clear all monitoring data</h3>
            <div class="admin-note"><b>This is a complete monitoring reset.</b> It deletes raw/history metrics, hourly/daily rollups, node and VM inventory, missed cycles, node logs, abuse current/history, and all fast current-cache tables used by the 5m Dashboard, Top VM and Node pages. It preserves dashboard users, admin settings, account login logs and maintenance-job records. Active agents can send fresh rows again after the service restarts.</div>
            <form class="bulk-bar" method="post" action="{url_for('admin_database_maintenance')}" onsubmit="return confirm('Permanently clear ALL monitoring data and current dashboard caches? Active agents may repopulate fresh data after the service restarts.')">
                <input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}"><input type="hidden" name="action" value="clear_monitoring_data">
                <label>Type <b>CLEAR ALL MONITORING DATA</b><input name="confirm_text" autocomplete="off" placeholder="CLEAR ALL MONITORING DATA" required></label>
                <label class="enable-line"><input type="checkbox" name="compact" value="1"> VACUUM after clear (slower, returns disk space)</label>
                <button class="btn-danger" type="submit">Clear all monitoring data</button>
            </form>
        </div>
        <div class="table-wrap"><table><thead><tr><th>ID</th><th>CREATED</th><th>ACTION</th><th>STATUS</th><th>STARTED</th><th>FINISHED</th><th>MESSAGE</th><th>UNIT</th></tr></thead><tbody>{rows}</tbody></table></div>
        <div class="table-hint">For routine retention, prefer <b>Delete history only</b>. A successful compact job reports deleted row counts and before/after file sizes. During VACUUM, check the maintenance systemd unit from SSH because the dashboard is intentionally offline.</div>
    </div>
    """


def enqueue_maintenance_job(action, parameters, actor):
    action = (action or "").strip().lower()
    allowed_actions = {
        "retention", "checkpoint", "vacuum", "delete_history", "delete_compact",
        "clear_monitoring_data", "reset_app_data",
        "purge_nodes", "purge_node_vms", "purge_vms",
    }
    if action not in allowed_actions:
        raise ValueError("Unsupported maintenance action")
    runner = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maintenance.py")
    if not os.path.isfile(runner):
        raise RuntimeError(f"Maintenance runner is missing: {runner}")
    systemctl = shutil.which("systemctl")
    if not systemctl:
        raise RuntimeError("systemctl is not installed")
    template_path = "/etc/systemd/system/bw-monitor-maintenance@.service"
    if not os.path.isfile(template_path):
        raise RuntimeError(f"Maintenance service template is missing: {template_path}")

    conn = db()
    try:
        stale_before = now_ts() - 24 * 3600
        conn.execute("""
            UPDATE maintenance_jobs
            SET status='error', finished_at=?,
                message='Recovered stale queued/running maintenance job'
            WHERE status IN ('queued','running') AND created_at<?
        """, (now_ts(), stale_before))
        active_count = int(conn.execute(
            "SELECT COUNT(*) FROM maintenance_jobs WHERE status IN ('queued','running')"
        ).fetchone()[0] or 0)
        if active_count >= MAX_ACTIVE_MAINTENANCE_JOBS:
            raise RuntimeError(f"Maintenance queue is full ({active_count} active jobs)")
        cur = conn.execute("""
            INSERT INTO maintenance_jobs(created_at, action, parameters, status, requested_by, message)
            VALUES (?, ?, ?, 'queued', ?, 'Waiting for maintenance worker')
        """, (now_ts(), action, json.dumps(parameters or {}, separators=(",", ":")), actor or "admin"))
        job_id = int(cur.lastrowid)
        unit_name = f"bw-monitor-maintenance@{job_id}.service"
        conn.execute("UPDATE maintenance_jobs SET unit_name=? WHERE id=?", (unit_name, job_id))
        conn.commit()
    finally:
        conn.close()

    # --no-block is critical for Type=oneshot. Without it, the HTTP request can
    # wait for the whole purge/VACUUM job and appear frozen.
    proc = subprocess.run(
        [systemctl, "--no-block", "start", unit_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=20,
        check=False,
    )
    if proc.returncode != 0:
        msg = (proc.stdout or "systemctl start failed").strip()[:1000]
        conn = db()
        try:
            conn.execute(
                "UPDATE maintenance_jobs SET status='error', finished_at=?, message=? WHERE id=?",
                (now_ts(), msg, job_id),
            )
            conn.commit()
        finally:
            conn.close()
        raise RuntimeError(msg)
    return job_id, unit_name


def enqueue_batched_purge_jobs(action, items, actor):
    """Split destructive work into small FIFO jobs, max 3 items per job by default."""
    clean_items = list(items or [])
    if not clean_items:
        return []
    job_ids = []
    for offset in range(0, len(clean_items), MAX_PURGE_ITEMS_PER_JOB):
        chunk = clean_items[offset:offset + MAX_PURGE_ITEMS_PER_JOB]
        parameters = {"vms": chunk} if action == "purge_vms" else {"nodes": chunk}
        job_id, unit_name = enqueue_maintenance_job(action, parameters, actor)
        job_ids.append((job_id, unit_name, len(chunk)))
    return job_ids

def monitor_system_health_card():
    h = get_monitor_system_health()
    status_cls = "active" if h["status"] == "OK" else "stale"
    return f"""
    <div class="card">
        <div class="table-title-row"><h3>System Health</h3><div class="count-badges"><span>Status <b>{escape(h['status'])}</b></span><span>Host <b>{escape(h['hostname'])}</b></span><span>PID <b>{h['pid']}</b></span></div></div>
        <div class="admin-note"><span class="vm-state {status_cls}">{escape(h['status'].upper())}</span> {escape(h['warnings'])}</div>
        <div class="grid">
            <div class="stat">CPU Load 1/5/15<b>{h['load1']:.2f} / {h['load5']:.2f} / {h['load15']:.2f}</b><small>{h['cpu_count']} CPU cores, load1 ~= {h['load_pct']}%</small></div>
            <div class="stat">Memory<b>{human(h['mem_used'])} / {human(h['mem_total'])}</b><small>Available {human(h['mem_available'])}, used {h['mem_pct']}%</small></div>
            <div class="stat">Disk<b>{human(h['disk_used'])} / {human(h['disk_total'])}</b><small>{escape(h['disk_path'])}, free {human(h['disk_free'])}, used {h['disk_pct']}%</small></div>
            <div class="stat">PostgreSQL data<b>{human(h['db_size'])}</b><small>WAL reserved/recycled {human(h['wal_size'])}; PostgreSQL manages and reuses it automatically</small></div>
            <div class="stat">Inventory<b>{h['node_count']} nodes / {h['vm_count']} VMs</b><small>Visible inventory rows only</small></div>
            <div class="stat">Logs<b>{h['account_log_count']} account / {h['node_log_count']} node</b><small>Retention still applies automatically</small></div>
            <div class="stat">Uptime<b>{human_age(h['uptime'])}</b><small>Python {escape(h['python'])}</small></div>
        </div>
    </div>
    """


