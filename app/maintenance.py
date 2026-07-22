#!/usr/bin/env python3
"""Out-of-process FIFO PostgreSQL maintenance runner for VirtInfra Monitor v50.

Usage:
    python3 bw_monitor_maintenance.py JOB_ID

The Flask application creates the job row and starts:
    bw-monitor-maintenance@JOB_ID.service

The worker uses PostgreSQL-native maintenance primitives for VACUUM and destructive
resets. It imports the web application only for retention and targeted purge logic,
with startup side effects explicitly disabled.
"""

from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
import shutil
import signal
import threading
import hashlib
import hmac
from pathlib import Path, PurePosixPath
import bw_pg as dbapi
import maintenance_native
import maintenance_queue
import configuration_backup
import emergency_backup
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
BASE_DIR = SCRIPT_PATH.parent
LOCK_PATH = Path(os.environ.get("BW_MONITOR_MAINTENANCE_LOCK", "/run/lock/bw-monitor-maintenance.lock"))
OFFLINE_MARKER = Path(os.environ.get("BW_MONITOR_OFFLINE_MARKER", "/run/bw-monitor-maintenance-web-offline"))
MAX_SELECTION_ITEMS = max(1, min(1000, int(os.environ.get("BW_MAX_PURGE_SELECTION_ITEMS", "300"))))
VACUUM_FREE_RESERVE = max(64 * 1024 * 1024, int(os.environ.get("BW_VACUUM_FREE_RESERVE_BYTES", str(256 * 1024 * 1024))))


def now_ts() -> int:
    return int(time.time())


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def find_app_file() -> Path:
    explicit = (os.environ.get("BW_MONITOR_APP_FILE") or "").strip()
    if explicit:
        path = Path(explicit).resolve()
        if not path.is_file():
            raise RuntimeError(f"BW_MONITOR_APP_FILE does not exist: {path}")
        return path

    preferred = (
        "app.py",
        "bw_monitor.py",
        "bandwidth_monitor.py",
        "monitor.py",
        "server.py",
        "main.py",
    )
    candidates: list[Path] = []
    for name in preferred:
        path = BASE_DIR / name
        if path.is_file() and path != SCRIPT_PATH:
            candidates.append(path)

    for path in sorted(BASE_DIR.glob("*.py")):
        if path != SCRIPT_PATH and path not in candidates:
            candidates.append(path)

    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "def run_retention(" in text and "def delete_history_older_than(" in text and "maintenance_jobs" in text:
            return path

    raise RuntimeError(
        "Cannot locate the VirtInfra Monitor application Python file. "
        "Set BW_MONITOR_APP_FILE=/opt/bw-monitor/<main-file>.py in the service template."
    )


def load_app_module():
    # Importing app.py must never run startup inventory cleanup from a maintenance
    # worker. The application checks this flag around import-time side effects.
    os.environ["BW_MAINTENANCE_IMPORT"] = "1"
    app_file = find_app_file()
    sys.path.insert(0, str(app_file.parent))
    spec = importlib.util.spec_from_file_location("bw_monitor_application", app_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load application module: {app_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    required = ("DB", "db", "run_retention", "delete_history_older_than")
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise RuntimeError(f"Application module {app_file} is missing: {', '.join(missing)}")
    return module, app_file


def job_conn(db_path: str) -> dbapi.Connection:
    conn = dbapi.connect(db_path, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def read_job(db_path: str, job_id: int) -> tuple[str, dict[str, Any], str]:
    conn = job_conn(db_path)
    try:
        row = conn.execute(
            "SELECT action, parameters, status FROM maintenance_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"Maintenance job #{job_id} does not exist")
        action = (row[0] or "").strip().lower()
        try:
            params = json.loads(row[1] or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Maintenance job #{job_id} has invalid parameters JSON") from exc
        if not isinstance(params, dict):
            raise RuntimeError(f"Maintenance job #{job_id} parameters must be an object")
        return action, params, (row[2] or "queued").strip().lower()
    finally:
        conn.close()


def update_job(
    db_path: str,
    job_id: int,
    status: str,
    message: str,
    *,
    started: bool = False,
    finished: bool = False,
    heartbeat: bool = False,
    progress: int | None = None,
    expected_status: str | None = None,
) -> bool:
    fields = ["status=?", "message=?"]
    values: list[Any] = [status, message[:4000]]
    now = now_ts()
    if started:
        fields.append("started_at=COALESCE(started_at, ?)")
        values.append(now)
    if finished:
        fields.append("finished_at=?")
        values.append(now)
    if heartbeat or status in {"starting", "running"}:
        fields.append("heartbeat_at=?")
        values.append(now)
    if progress is not None:
        fields.append("progress=?")
        values.append(max(0, min(100, int(progress))))
    sql = f"UPDATE maintenance_jobs SET {', '.join(fields)} WHERE id=?"
    values.append(job_id)
    if expected_status:
        sql += " AND status=?"
        values.append(expected_status)

    conn = job_conn(db_path)
    try:
        cur = conn.execute(sql, values)
        conn.commit()
        return int(cur.rowcount or 0) == 1
    finally:
        conn.close()


def heartbeat_job(db_path: str, job_id: int, stop_event: threading.Event) -> None:
    while not stop_event.wait(30):
        try:
            conn = job_conn(db_path)
            try:
                conn.execute(
                    "UPDATE maintenance_jobs SET heartbeat_at=? "
                    "WHERE id=? AND status='running'",
                    (now_ts(), job_id),
                )
                conn.commit()
            finally:
                conn.close()
        except BaseException:
            # The watchdog also checks the systemd unit. A temporary heartbeat
            # write failure must not abort a healthy VACUUM or reset.
            pass


def run_command(args: list[str], timeout: int = 300, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and proc.returncode != 0:
        output = (proc.stdout or "").strip()
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(args)}: {output}")
    return proc


def systemd_load_state(service: str) -> str:
    proc = run_command(
        ["systemctl", "show", "--property=LoadState", "--value", service],
        timeout=30,
        check=False,
    )
    return (proc.stdout or "").strip()


def detect_app_service() -> str:
    explicit = (os.environ.get("BW_MONITOR_APP_SERVICE") or "").strip()
    if explicit:
        return explicit

    for service in ("bw-monitor.service", "bandwidth-monitor.service"):
        if systemd_load_state(service) not in ("", "not-found"):
            return service
    return "bw-monitor.service"


def service_is_active(service: str) -> bool:
    proc = run_command(["systemctl", "is-active", "--quiet", service], timeout=30, check=False)
    return proc.returncode == 0


def verify_monitor_health(attempts: int = 30) -> dict[str, Any]:
    port = max(1, min(65535, int(os.environ.get("BW_PUBLIC_PORT", "8080"))))
    urls = [f"http://127.0.0.1:{port}/livez", f"http://127.0.0.1:{port}/healthz"]
    errors: list[str] = []
    for attempt in range(1, max(1, attempts) + 1):
        current: list[str] = []
        ok = True
        for url in urls:
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    code = int(getattr(response, "status", 0) or 0)
                    final_url = str(getattr(response, "geturl", lambda: url)() or url)
                    body = response.read(4096).decode("utf-8", errors="replace")
                if final_url.rstrip("/") != url.rstrip("/"):
                    ok = False
                    current.append(f"{url}: redirected to {final_url}")
                elif code < 200 or code >= 300:
                    ok = False
                    current.append(f"{url}: HTTP {code}")
                elif not body.strip():
                    ok = False
                    current.append(f"{url}: empty response")
            except (OSError, urllib.error.URLError, TimeoutError) as exc:
                ok = False
                current.append(f"{url}: {exc}")
        if ok:
            return {"ok": True, "attempt": attempt, "urls": urls}
        errors = current
        time.sleep(min(1.0, 0.2 + attempt * 0.05))
    raise RuntimeError("Monitor health check failed: " + "; ".join(errors[:4]))


def _write_offline_marker(service: str) -> None:
    try:
        OFFLINE_MARKER.parent.mkdir(parents=True, exist_ok=True)
        OFFLINE_MARKER.write_text(service + "\n", encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Could not create web recovery marker {OFFLINE_MARKER}: {exc}") from exc


def _clear_offline_marker() -> None:
    try:
        OFFLINE_MARKER.unlink(missing_ok=True)
    except OSError:
        pass


def stop_service(service: str) -> bool:
    load_state = systemd_load_state(service)
    if load_state in ("", "not-found"):
        raise RuntimeError(
            f"Dashboard service {service} was not found. "
            "Set BW_MONITOR_APP_SERVICE to the real systemd unit name."
        )
    was_active = service_is_active(service)
    if was_active:
        # The systemd unit has an ExecStopPost safety net which reads this marker.
        # If Python is killed during VACUUM, systemd still starts the web service.
        _write_offline_marker(service)
        run_command(["systemctl", "stop", service], timeout=300)
    return was_active


def start_service(service: str) -> None:
    run_command(["systemctl", "start", service], timeout=300)


def checkpoint_database(db_path: str) -> dict[str, Any]:
    """Compatibility helper retained for old queued rows; no checkpoint is forced."""
    return maintenance_native.database_status()


def vacuum_database(db_path: str) -> dict[str, Any]:
    """Run online PostgreSQL VACUUM (ANALYZE) on a dedicated connection."""
    return maintenance_native.vacuum_analyze()


def _transactional_purge(module, action: str, params: dict[str, Any]) -> dict[str, Any]:
    """Process one exclusive purge job in small internal batches.

    v48.12.6 no longer creates one systemd unit per three selected items. The
    job may contain a larger selection, but each item gets its own short PostgreSQL
    transaction and progress is written after every internal batch.
    """
    batch_size = max(
        1,
        min(
            10,
            int(params.get("batch_size") or getattr(module, "MAX_PURGE_ITEMS_PER_JOB", 3)),
        ),
    )
    job_id = int(params.get("_job_id", 0) or 0)
    db_path = str(module.DB)
    result: dict[str, Any] = {
        "action": action,
        "items": [],
        "batch_size": batch_size,
    }

    def report(done: int, total: int, label: str) -> None:
        if job_id <= 0:
            return
        try:
            update_job(
                db_path,
                job_id,
                "running",
                f"{label}: {done}/{total} item(s) completed; internal batch size {batch_size}",
            )
        except BaseException:
            pass

    if action in {"purge_nodes", "purge_node_vms"}:
        raw_nodes = params.get("nodes") or []
        if not isinstance(raw_nodes, list):
            raise RuntimeError("nodes must be a list")
        nodes: list[str] = []
        seen: set[str] = set()
        for value in raw_nodes:
            node = str(value or "").strip()
            if node and node not in seen:
                seen.add(node)
                nodes.append(node)
        if not nodes:
            raise RuntimeError("purge job has no nodes")
        if len(nodes) > MAX_SELECTION_ITEMS:
            raise RuntimeError(f"purge selection exceeds max {MAX_SELECTION_ITEMS} nodes")

        required = "purge_node_data" if action == "purge_nodes" else "purge_all_vms_for_node"
        if not hasattr(module, required):
            raise RuntimeError(f"Application is missing {required}()")

        total = len(nodes)
        for index, node in enumerate(nodes, start=1):
            conn = module.db()
            try:
                conn.execute("PRAGMA busy_timeout=60000")
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
                    (maintenance_native.NODE_LOCK_PREFIX + node,),
                )
                if action == "purge_nodes":
                    deleted = module.purge_node_data(conn, node)
                else:
                    deleted = module.purge_all_vms_for_node(conn, node)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()
            if hasattr(module, "enterprise_enqueue_control"):
                control_action = "purge_node" if action == "purge_nodes" else "purge_node_vms"
                queue_state = module.enterprise_enqueue_control(control_action, node=node)
                if isinstance(deleted, dict):
                    deleted["enterprise_queue"] = queue_state
            result["items"].append({"node": node, "deleted": deleted})
            if index % batch_size == 0 or index == total:
                report(index, total, "Node purge")
                time.sleep(0.25)
        result["count"] = total
        return result

    if action == "purge_vms":
        raw_vms = params.get("vms") or []
        if not isinstance(raw_vms, list):
            raise RuntimeError("vms must be a list")
        vms: list[dict[str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for value in raw_vms:
            if not isinstance(value, dict):
                continue
            node = str(value.get("node") or "").strip()
            vm_uuid = str(value.get("vm_uuid") or "").strip()
            pair = (node, vm_uuid)
            if node and vm_uuid and pair not in seen_pairs:
                seen_pairs.add(pair)
                vms.append({"node": node, "vm_uuid": vm_uuid})
        if not vms:
            raise RuntimeError("purge job has no VMs")
        if len(vms) > MAX_SELECTION_ITEMS:
            raise RuntimeError(f"purge selection exceeds max {MAX_SELECTION_ITEMS} VMs")
        if not hasattr(module, "purge_vm_data"):
            raise RuntimeError("Application is missing purge_vm_data()")

        total = len(vms)
        for index, item in enumerate(vms, start=1):
            conn = module.db()
            try:
                conn.execute("PRAGMA busy_timeout=60000")
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
                    (maintenance_native.NODE_LOCK_PREFIX + item["node"],),
                )
                deleted = module.purge_vm_data(
                    conn,
                    item["node"],
                    item["vm_uuid"],
                    refresh_snapshots=True,
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()
            if hasattr(module, "enterprise_enqueue_control"):
                queue_state = module.enterprise_enqueue_control("purge_vm", node=item["node"], vm_uuid=item["vm_uuid"])
                if isinstance(deleted, dict):
                    deleted["enterprise_queue"] = queue_state
            result["items"].append({**item, "deleted": deleted})
            if index % batch_size == 0 or index == total:
                report(index, total, "VM purge")
                time.sleep(0.25)
        result["count"] = total
        return result

    raise RuntimeError(f"Unsupported purge action: {action}")


def cancel_and_clear_other_maintenance_jobs(db_path: str, current_job_id: int) -> dict[str, Any]:
    """Stop every older/newer maintenance unit and clear its queue/history row.

    The current worker already owns the global maintenance flock, therefore
    other active workers can only be waiting. Stop their systemd units before
    deleting the rows so they cannot wake later and operate on a reset DB.
    """
    conn = job_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT id, COALESCE(unit_name,''), COALESCE(status,'') "
            "FROM maintenance_jobs WHERE id<>? ORDER BY id",
            (current_job_id,),
        ).fetchall()
    finally:
        conn.close()

    stopped: list[dict[str, Any]] = []
    for other_id, unit_name, status in rows:
        unit_name = str(unit_name or "").strip()
        status = str(status or "").strip().lower()
        if unit_name and status in {"queued", "running"}:
            proc = run_command(["systemctl", "stop", unit_name], timeout=60, check=False)
            stopped.append({
                "id": int(other_id),
                "unit": unit_name,
                "returncode": int(proc.returncode),
                "output": (proc.stdout or "").strip()[:500],
            })

    conn = job_conn(db_path)
    try:
        cur = conn.execute("DELETE FROM maintenance_jobs WHERE id<>?", (current_job_id,))
        deleted = max(0, int(cur.rowcount or 0))
        conn.commit()
    finally:
        conn.close()
    return {"deleted_rows": deleted, "stopped_units": stopped}


def delete_current_reset_job(db_path: str, job_id: int) -> None:
    """Remove the successful reset job so the maintenance queue is truly empty."""
    conn = job_conn(db_path)
    try:
        conn.execute("DELETE FROM maintenance_jobs WHERE id=?", (job_id,))
        has_sequence = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
        ).fetchone()
        if has_sequence:
            remaining = conn.execute("SELECT MAX(id) FROM maintenance_jobs").fetchone()
            max_id = int((remaining or [0])[0] or 0)
            conn.execute("DELETE FROM sqlite_sequence WHERE name='maintenance_jobs'")
            if max_id > 0:
                conn.execute(
                    "INSERT INTO sqlite_sequence(name,seq) VALUES('maintenance_jobs',?)",
                    (max_id,),
                )
        conn.commit()
    finally:
        conn.close()

def _start_service_reliably(service: str, attempts: int = 3) -> None:
    """Start the dashboard and verify it is actually active.

    A maintenance failure must never leave the web service stopped merely
    because an earlier maintenance unit was interrupted before it could claim the PostgreSQL job.
    """
    attempts = max(1, int(attempts or 1))
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        run_command(["systemctl", "reset-failed", service], timeout=30, check=False)
        proc = run_command(["systemctl", "start", service], timeout=300, check=False)
        if proc.returncode == 0:
            for _ in range(20):
                if service_is_active(service):
                    _clear_offline_marker()
                    return
                time.sleep(0.5)
        errors.append(
            f"attempt {attempt}: rc={proc.returncode} output={(proc.stdout or '').strip()[:500]}"
        )
        time.sleep(min(5.0, float(attempt)))
    raise RuntimeError(f"Could not restart {service}: {'; '.join(errors)}")



def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_backup_manifest(backup_dir: Path, sums_file: Path) -> dict[str, str]:
    verified: dict[str, str] = {}
    for raw in sums_file.read_text(encoding="utf-8", errors="strict").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = raw.split(None, 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise RuntimeError(f"Invalid SHA256SUMS line: {raw[:120]}")
        expected = parts[0].lower()
        relative = parts[1].lstrip("* ").replace("\\", "/")
        # GNU sha256sum commonly writes paths from ``find .`` as
        # ``./database.dump``.  Normalize that harmless prefix so backups
        # created by R20-R22 remain valid, while still rejecting absolute or
        # parent-traversal paths.
        while relative.startswith("./"):
            relative = relative[2:]
        manifest_path = PurePosixPath(relative)
        if (
            not relative
            or manifest_path.is_absolute()
            or any(part in {"", ".", ".."} for part in manifest_path.parts)
        ):
            raise RuntimeError(f"Unsafe backup manifest path: {relative}")
        normalized = manifest_path.as_posix()
        target = (backup_dir / Path(*manifest_path.parts)).resolve()
        try:
            target.relative_to(backup_dir.resolve())
        except ValueError as exc:
            raise RuntimeError(f"Unsafe backup manifest path: {relative}") from exc
        if not target.is_file():
            raise RuntimeError(f"Backup manifest file is missing: {target}")
        actual = _sha256_file(target)
        if not hmac.compare_digest(actual, expected):
            raise RuntimeError(f"Backup checksum mismatch: {normalized}")
        previous = verified.get(normalized)
        if previous is not None and not hmac.compare_digest(previous, actual):
            raise RuntimeError(f"Conflicting backup manifest entry: {normalized}")
        verified[normalized] = actual
    if "database.dump" not in verified or "database.list" not in verified:
        raise RuntimeError("Backup manifest does not cover database.dump and database.list")
    return verified


def create_verified_pre_nuclear_backup(*, protect: bool = False) -> dict[str, Any]:
    backup_script = Path(os.environ.get("BW_MONITOR_BACKUP_SCRIPT", "/opt/bw-monitor/backup.sh"))
    if not backup_script.is_file():
        raise RuntimeError(f"Backup script is missing: {backup_script}")
    root = Path(os.environ.get("BW_BACKUP_ROOT", "/var/backups/bw-monitor"))
    root.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(root).free
    minimum = max(512 * 1024 * 1024, int(os.environ.get("BW_NUCLEAR_MIN_FREE_BYTES", str(1024 * 1024 * 1024))))
    if free < minimum:
        raise RuntimeError(f"Not enough free space for verified pre-reset backup: {free} < {minimum}")
    proc = run_command([str(backup_script)], timeout=12 * 3600, check=True)
    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Backup script did not return a backup directory")
    backup_dir = Path(lines[-1])
    dump_file = backup_dir / "database.dump"
    list_file = backup_dir / "database.list"
    sums_file = backup_dir / "SHA256SUMS"
    if not dump_file.is_file() or dump_file.stat().st_size <= 0:
        raise RuntimeError(f"Verified backup dump is missing or empty: {dump_file}")
    if not list_file.is_file() or list_file.stat().st_size <= 0 or not sums_file.is_file():
        raise RuntimeError(f"Backup verification files are incomplete in {backup_dir}")
    verified = _verify_backup_manifest(backup_dir, sums_file)
    if len(list_file.read_text(encoding="utf-8", errors="replace").splitlines()) < 2:
        raise RuntimeError(f"pg_restore catalog is unexpectedly empty: {list_file}")
    emergency_backup.record_verified_backup(
        backup_dir.name,
        dump_sha256=verified["database.dump"],
        dump_bytes=dump_file.stat().st_size,
        manifest_files_verified=len(verified),
    )
    if protect:
        emergency_backup.set_emergency_backup_protected(backup_dir.name, True)
    return {
        "backup_id": backup_dir.name,
        "path": str(backup_dir),
        "dump": str(dump_file),
        "dump_bytes": dump_file.stat().st_size,
        "sha256": verified["database.dump"],
        "manifest_files_verified": len(verified),
        "free_bytes_before": free,
        "protected": bool(protect),
    }


def write_nuclear_audit(db_path: str, job_id: int, actor: str, backup: dict[str, Any], result: dict[str, Any]) -> None:
    release = "unknown"
    try:
        release = Path("/opt/bw-monitor/DEPLOY_VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        pass
    conn = job_conn(db_path)
    try:
        conn.execute(
            """INSERT INTO maintenance_nuclear_audit(
                   job_id,requested_by,created_at,backup_path,backup_sha256,release_version,result_json
               ) VALUES(?,?,?,?,?,?,?)""",
            (job_id, actor or "admin", now_ts(), str(backup.get("path") or ""),
             str(backup.get("sha256") or ""), release, compact_json(result)),
        )
        conn.commit()
    finally:
        conn.close()


def execute_action(module, action: str, params: dict[str, Any], *, db_path: str) -> dict[str, Any]:
    # Compatibility for jobs queued immediately before an in-place upgrade.
    # New 50.5.7 submissions cannot create these actions.
    if action == "checkpoint":
        return {
            "action": action,
            "legacy": True,
            "result": checkpoint_database(db_path),
            "note": "No checkpoint was forced; PostgreSQL manages checkpoints automatically.",
        }
    if action == "clear_live_cache":
        return {
            "action": action,
            "legacy": True,
            "skipped": True,
            "note": "CLEAR LIVE 5M was removed before 50.5.7; no current cache was deleted.",
        }

    if action == "retention":
        if module is None:
            raise RuntimeError("Retention requires the application policy module")
        scope = str(params.get("scope") or "all").strip().lower()
        if scope == "consumption":
            cleanup = getattr(module, "run_consumption_retention_cleanup", None)
            if not callable(cleanup):
                raise RuntimeError("Consumption retention helper is unavailable")
            return {
                "action": action,
                "scope": "consumption",
                "result": cleanup(dry_run=False),
            }
        if scope not in {"", "all"}:
            raise RuntimeError(f"Unsupported retention scope: {scope}")
        return {"action": action, "scope": "all", "result": module.run_retention(dry_run=False)}

    if action == "delete_history":
        if module is None:
            raise RuntimeError("History deletion requires the application policy module")
        days = int(params.get("days", 7))
        return {"action": action, "result": module.delete_history_older_than(days)}

    if action in {"purge_nodes", "purge_node_vms", "purge_vms"}:
        if module is None:
            raise RuntimeError("Targeted purge requires the application purge module")
        return _transactional_purge(module, action, params)

    if action == "configuration_backup":
        return {
            "action": action,
            "backup": configuration_backup.create_configuration_backup(
                str(params.get("requested_by") or params.get("actor") or "super_admin"),
                reason=str(params.get("reason") or "manual"),
                protect=bool(params.get("protect", False)),
            ),
        }

    if action == "full_backup":
        return {"action": action, "backup": create_verified_pre_nuclear_backup()}

    if action == "full_backup_verify":
        backup_id = str(params.get("backup_id") or "").strip()
        return {"action": action, "verification": emergency_backup.verify_emergency_backup(backup_id)}

    if action not in {
        "vacuum",
        "delete_compact",
        "clear_monitoring_data",
        "reset_app_data",
        "configuration_restore",
        "clear_api_logs",
        "clear_api_data",
    }:
        raise RuntimeError(f"Unsupported maintenance action: {action}")

    app_service = detect_app_service()
    result: dict[str, Any] = {"action": action, "service": app_service}

    # PostgreSQL VACUUM is online and runs with statement_timeout=0 on a
    # dedicated autocommit connection. Gunicorn and Agent ingestion stay up.
    if action == "vacuum":
        result["vacuum"] = vacuum_database(db_path)
        return result

    # Manual history deletion stays online. The optional VACUUM that follows is
    # also online; this operation never creates an intentional Agent outage.
    if action == "delete_compact":
        if module is None:
            raise RuntimeError("History deletion requires the application policy module")
        days = int(params.get("days", 7))
        result["delete"] = module.delete_history_older_than(days)
        job_id = int(params.get("_job_id", 0) or 0)
        if job_id > 0:
            try:
                update_job(
                    db_path,
                    job_id,
                    "running",
                    "History deletion completed. Running online PostgreSQL VACUUM ANALYZE.",
                )
            except BaseException:
                pass
        result["vacuum"] = vacuum_database(db_path)
        return result

    # API cleanup is small, online and uses TRUNCATE rather than row-by-row
    # DELETE. API keys are preserved by clear_api_logs and removed by
    # clear_api_data. The Agent BW_MONITOR_TOKEN is never changed.
    if action == "clear_api_logs":
        result["clear"] = maintenance_native.clear_api_logs()
        result["vacuum_skipped"] = "TRUNCATE already releases the API log relations"
        return result

    if action == "clear_api_data":
        result["clear"] = maintenance_native.clear_api_data()
        result["vacuum_skipped"] = "TRUNCATE already releases the API relations"
        return result

    # Restore and Nuclear are exclusive offline operations. Backups are
    # created and verified while the dashboard is still online.
    current_job_id = int(params.get("_job_id", 0) or 0)
    if action in {"reset_app_data", "configuration_restore"} and current_job_id <= 0:
        raise RuntimeError(f"{action} is missing the current maintenance job id")

    if action == "configuration_restore":
        backup_id = str(params.get("backup_id") or "").strip()
        sections = params.get("sections") or []
        configuration_backup.verify_configuration_backup(backup_id)
        update_job(db_path, current_job_id, "running", "Configuration backup verified. Creating a protected safety snapshot", heartbeat=True, progress=15)
        result["safety_backup"] = configuration_backup.create_configuration_backup(
            str(params.get("requested_by") or "super_admin"),
            reason=f"pre-restore:{backup_id}",
            protect=True,
        )
        update_job(db_path, current_job_id, "running", "Safety snapshot verified. Restoring selected configuration", heartbeat=True, progress=45)

    if action == "reset_app_data":
        create_config = bool(params.get("create_configuration_backup", True))
        create_full = bool(params.get("create_full_backup", False))
        actor = str(params.get("requested_by") or params.get("actor_username") or "super_admin")
        backups: dict[str, Any] = {}
        if create_config:
            update_job(db_path, current_job_id, "running", "Creating protected Configuration Backup before Nuclear Reset", heartbeat=True, progress=10)
            backups["configuration"] = configuration_backup.create_configuration_backup(
                actor, reason="pre-nuclear", protect=True
            )
        if create_full:
            update_job(db_path, current_job_id, "running", "Creating verified Full Emergency Database Backup", heartbeat=True, progress=25)
            backups["full"] = create_verified_pre_nuclear_backup(protect=True)
        result["backups"] = backups
        if backups:
            result["backup_status"] = "verified"
            result["backup_kind"] = "+".join(sorted(backups))
        else:
            result["backup_status"] = "skipped_by_super_admin"
            result["backup_kind"] = "none"
        update_job(db_path, current_job_id, "running", "Backup policy complete. Preparing true Nuclear Reset", heartbeat=True, progress=50)

    was_active = False
    action_error: BaseException | None = None
    nuclear_committed = False
    try:
        was_active = stop_service(app_service)
        result["service_was_active"] = bool(was_active)
        if action == "clear_monitoring_data":
            result["clear"] = maintenance_native.clear_monitoring_data()
        elif action == "configuration_restore":
            result["restore"] = configuration_backup.restore_configuration_backup(
                str(params.get("backup_id") or ""),
                actor_user_id=int(params.get("actor_user_id", 0) or 0),
                actor_username=str(params.get("actor_username") or params.get("requested_by") or ""),
                sections=params.get("sections") or [],
            )
        elif action == "reset_app_data":
            update_job(db_path, current_job_id, "running", "Resetting all application data except current super_admin and this Nuclear record", heartbeat=True, progress=70)
            primary_backup = dict((result.get("backups") or {}).get("configuration") or (result.get("backups") or {}).get("full") or {})
            result["reset"] = maintenance_native.reset_app_data(
                actor_user_id=int(params.get("actor_user_id", 0) or 0),
                actor_username=str(params.get("actor_username") or params.get("requested_by") or ""),
                current_job_id=current_job_id,
                backup_status=str(result.get("backup_status") or "unknown"),
                backup_kind=str(result.get("backup_kind") or ""),
                backup_path=str(primary_backup.get("path") or ""),
                backup_sha256=str(primary_backup.get("sha256") or ""),
            )
            nuclear_committed = True
            result["queue_preserved"] = "current_nuclear_job_only"
        else:  # pragma: no cover - guarded above
            raise RuntimeError(f"Unsupported destructive action: {action}")
    except BaseException as exc:
        action_error = exc
    finally:
        if was_active:
            try:
                _start_service_reliably(app_service)
                result["service_restarted"] = True
                result["health_check"] = verify_monitor_health()
            except BaseException as restart_exc:
                result["service_restarted"] = False
                result["restart_error"] = str(restart_exc)
                if action_error is None:
                    action_error = restart_exc

    if action == "reset_app_data" and nuclear_committed:
        result["completed"] = action_error is None
        if action_error is not None:
            result["error"] = f"{type(action_error).__name__}: {action_error}"
        try:
            maintenance_native.finalize_nuclear_audit(
                current_job_id,
                status="done" if action_error is None else "reset_done_service_failed",
                result=result,
            )
            result["nuclear_audit_written"] = True
        except BaseException as audit_exc:
            result["nuclear_audit_written"] = False
            result["nuclear_audit_error"] = f"{type(audit_exc).__name__}: {audit_exc}"
            if action_error is None:
                action_error = audit_exc

    # TRUNCATE already releases relation storage. An automatic post-reset
    # VACUUM adds downtime and work without benefit, so compact is ignored.
    result["compact_requested"] = bool(params.get("compact", False))
    result["compact_skipped"] = True


    if action_error is not None:
        raise action_error
    return result

class MaintenanceInterrupted(RuntimeError):
    pass


def _termination_handler(signum, frame):
    raise MaintenanceInterrupted(f"maintenance worker received signal {signum}")


def install_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, _termination_handler)
    signal.signal(signal.SIGINT, _termination_handler)


def acquire_lock():
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        path = LOCK_PATH
    except OSError:
        path = Path("/tmp/bw-monitor-maintenance.lock")
    handle = path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError(
            "Another maintenance worker already owns the exclusive lock; "
            "this duplicate unit will not wait in the background"
        )
    return handle


def main() -> int:
    parser = argparse.ArgumentParser(description="VirtInfra Monitor FIFO maintenance runner")
    parser.add_argument("job_id", type=int, help="maintenance_jobs.id")
    args = parser.parse_args()

    install_signal_handlers()
    module = None
    app_file = None
    db_path = os.environ.get("BW_MONITOR_DB", "/var/lib/bw-monitor/postgresql")
    lock_handle = None
    heartbeat_stop = threading.Event()
    heartbeat_thread = None
    job_id = args.job_id
    action = ""
    params: dict[str, Any] = {}
    try:
        lock_handle = acquire_lock()
        action, params, current_status = read_job(db_path, job_id)
        params = dict(params)
        params["_job_id"] = job_id
        if current_status not in {"starting", "queued"}:
            raise RuntimeError(f"Maintenance job #{job_id} is already {current_status}")

        application_actions = {
            "retention", "delete_history", "delete_compact",
            "purge_nodes", "purge_node_vms", "purge_vms",
        }
        if action in application_actions:
            module, app_file = load_app_module()
            db_path = str(module.DB)
            backend = app_file.name
        else:
            backend = "maintenance_native.py"

        claimed = update_job(
            db_path, job_id, "running",
            f"Running {action} with {backend} under the exclusive worker lock",
            started=True, heartbeat=True, progress=1, expected_status=current_status,
        )
        if not claimed:
            raise RuntimeError(f"Maintenance job #{job_id} could not be claimed atomically")
        heartbeat_thread = threading.Thread(
            target=heartbeat_job, args=(db_path, job_id, heartbeat_stop), daemon=True
        )
        heartbeat_thread.start()

        result = execute_action(module, action, params, db_path=db_path)
        update_job(db_path, job_id, "ok", compact_json(result), finished=True, progress=100)
        print(compact_json(result), flush=True)
        return 0
    except BaseException as exc:
        message = f"{type(exc).__name__}: {exc}"
        if db_path:
            try:
                update_job(db_path, job_id, "error", message, finished=True, progress=100)
            except BaseException:
                pass
        traceback.print_exc()
        return 1
    finally:
        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=2)
        if lock_handle is not None:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            finally:
                lock_handle.close()
        maintenance_queue.wake_dispatcher()


if __name__ == "__main__":
    raise SystemExit(main())
