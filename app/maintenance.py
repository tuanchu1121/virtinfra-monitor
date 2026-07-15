#!/usr/bin/env python3
"""Out-of-process FIFO PostgreSQL maintenance runner for VirtInfra Monitor v50.

Usage:
    python3 bw_monitor_maintenance.py JOB_ID

The Flask application creates the job row and starts:
    bw-monitor-maintenance@JOB_ID.service

This runner loads the sibling VirtInfra Monitor application module so retention and
history deletion use exactly the same schema and logic as the web application.
"""

from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
import shutil
import signal
from pathlib import Path
import bw_pg as dbapi
import subprocess
import sys
import time
import traceback
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


def update_job(db_path: str, job_id: int, status: str, message: str, *, started: bool = False, finished: bool = False) -> None:
    fields = ["status=?", "message=?"]
    values: list[Any] = [status, message[:4000]]
    if started:
        fields.append("started_at=COALESCE(started_at, ?)")
        values.append(now_ts())
    if finished:
        fields.append("finished_at=?")
        values.append(now_ts())
    values.append(job_id)

    conn = job_conn(db_path)
    try:
        conn.execute(f"UPDATE maintenance_jobs SET {', '.join(fields)} WHERE id=?", values)
        conn.commit()
    finally:
        conn.close()


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
    """Return PostgreSQL WAL/database health without forcing a superuser checkpoint."""
    stats = dbapi.database_stats()
    return {
        "engine": "postgresql",
        "checkpoint": "managed by PostgreSQL",
        "db_bytes": int(stats.get("db_size", 0)),
        "wal_bytes": int(stats.get("wal_size", 0)),
    }


def vacuum_database(db_path: str) -> dict[str, Any]:
    """Run online PostgreSQL VACUUM (ANALYZE).

    PostgreSQL VACUUM does not require a second full-size copy of the database,
    so the old SQLite free-space gate is intentionally gone.
    """
    before = dbapi.database_size()
    conn = dbapi.connect(db_path, timeout=3600)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()
    after = dbapi.database_size()
    return {
        "engine": "postgresql",
        "db_bytes_before": before,
        "db_bytes_after": after,
        "reclaimed_bytes": max(0, before - after),
        "note": "VACUUM ANALYZE completed; physical file shrink is not expected",
    }


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


def _offline_vacuum(db_path: str, app_service: str, result: dict[str, Any]) -> None:
    """VACUUM requires an exclusive maintenance window.

    Keep this window as small as possible.  Callers must complete online/batched
    deletion before entering this helper.  The service is restarted in a
    finally block even if VACUUM or checkpointing fails.
    """
    was_active = stop_service(app_service)
    result["service_was_active"] = bool(was_active)
    vacuum_error: BaseException | None = None
    try:
        result["vacuum"] = vacuum_database(db_path)
    except BaseException as exc:
        vacuum_error = exc
    finally:
        if was_active:
            try:
                _start_service_reliably(app_service)
                result["service_restarted"] = True
            except BaseException as restart_exc:
                result["service_restarted"] = False
                result["restart_error"] = str(restart_exc)
                if vacuum_error is None:
                    vacuum_error = restart_exc
    if vacuum_error is not None:
        raise vacuum_error


def execute_action(module, action: str, params: dict[str, Any]) -> dict[str, Any]:
    db_path = str(module.DB)
    if action == "retention":
        return {"action": action, "result": module.run_retention(dry_run=False)}
    if action == "checkpoint":
        return {"action": action, "result": checkpoint_database(db_path)}
    if action == "delete_history":
        days = int(params.get("days", 7))
        return {"action": action, "result": module.delete_history_older_than(days)}
    if action in {"purge_nodes", "purge_node_vms", "purge_vms"}:
        return _transactional_purge(module, action, params)

    if action not in {
        "vacuum", "delete_compact", "clear_monitoring_data", "clear_live_cache",
        "reset_app_data", "clear_api_logs", "clear_api_data"
    }:
        raise RuntimeError(f"Unsupported maintenance action: {action}")

    app_service = detect_app_service()
    result: dict[str, Any] = {"action": action, "service": app_service}

    # Fast API cleanup does not require an outage.  Only an explicitly selected
    # compact step enters the short exclusive VACUUM window.
    if action == "clear_api_logs":
        if not hasattr(module, "clear_api_logs"):
            raise RuntimeError("Application is missing clear_api_logs()")
        result["clear"] = module.clear_api_logs(str(params.get("kind", "all")))
        if bool(params.get("compact", False)):
            _offline_vacuum(db_path, app_service, result)
        return result

    if action == "clear_api_data":
        if not hasattr(module, "clear_all_api_data"):
            raise RuntimeError("Application is missing clear_all_api_data()")
        result["clear"] = module.clear_all_api_data()
        if bool(params.get("compact", False)):
            _offline_vacuum(db_path, app_service, result)
        return result

    # Delete old metric rows in short committed batches while Gunicorn remains
    # available.  Stop the web service only for the unavoidable VACUUM rewrite.
    if action == "delete_compact":
        days = int(params.get("days", 7))
        result["delete"] = module.delete_history_older_than(days)
        job_id = int(params.get("_job_id", 0) or 0)
        if job_id > 0:
            try:
                update_job(
                    db_path,
                    job_id,
                    "running",
                    "History deletion completed. Running PostgreSQL VACUUM ANALYZE.",
                )
            except BaseException:
                pass
        _offline_vacuum(db_path, app_service, result)
        return result

    # The remaining operations alter current-state tables or explicitly request
    # a standalone VACUUM, so keep the original full offline safety boundary.
    was_active = False
    action_error: BaseException | None = None
    try:
        was_active = stop_service(app_service)
        if action == "clear_live_cache":
            if not hasattr(module, "clear_live_5m_cache"):
                raise RuntimeError("Application is missing clear_live_5m_cache()")
            result["clear"] = module.clear_live_5m_cache()
            result["checkpoint"] = checkpoint_database(db_path)
        elif action == "clear_monitoring_data":
            if not hasattr(module, "clear_all_monitoring_data"):
                raise RuntimeError("Application is missing clear_all_monitoring_data()")
            result["clear"] = module.clear_all_monitoring_data()
            result["checkpoint"] = checkpoint_database(db_path)
            if bool(params.get("compact", False)):
                result["vacuum"] = vacuum_database(db_path)
        elif action == "reset_app_data":
            if not hasattr(module, "reset_all_app_data"):
                raise RuntimeError("Application is missing reset_all_app_data()")
            current_job_id = int(params.get("_job_id", 0) or 0)
            if current_job_id <= 0:
                raise RuntimeError("reset_app_data is missing the current maintenance job id")
            result["queue"] = cancel_and_clear_other_maintenance_jobs(db_path, current_job_id)
            result["reset"] = module.reset_all_app_data()
            result["checkpoint"] = checkpoint_database(db_path)
            if bool(params.get("compact", False)):
                result["vacuum"] = vacuum_database(db_path)
        else:
            result["vacuum"] = vacuum_database(db_path)
    except BaseException as exc:
        action_error = exc
    finally:
        if was_active:
            try:
                _start_service_reliably(app_service)
                result["service_restarted"] = True
            except BaseException as restart_exc:
                result["service_restarted"] = False
                result["restart_error"] = str(restart_exc)
                if action_error is None:
                    action_error = restart_exc

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
    parser = argparse.ArgumentParser(description="VirtInfra Monitor single-worker maintenance runner")
    parser.add_argument("job_id", type=int, help="maintenance_jobs.id")
    args = parser.parse_args()

    install_signal_handlers()
    module = None
    db_path = ""
    lock_handle = None
    job_id = args.job_id
    try:
        module, app_file = load_app_module()
        db_path = str(module.DB)
        lock_handle = acquire_lock()
        action, params, current_status = read_job(db_path, job_id)
        params = dict(params)
        params["_job_id"] = job_id
        if current_status not in {"queued", "running"}:
            raise RuntimeError(f"Maintenance job #{job_id} is already {current_status}")

        update_job(
            db_path,
            job_id,
            "running",
            f"Running {action} with {app_file.name} under the exclusive worker lock",
            started=True,
        )
        result = execute_action(module, action, params)
        update_job(db_path, job_id, "ok", compact_json(result), finished=True)
        if action == "reset_app_data":
            delete_current_reset_job(db_path, job_id)
        print(compact_json(result), flush=True)
        return 0
    except BaseException as exc:
        message = f"{type(exc).__name__}: {exc}"
        if db_path:
            try:
                update_job(db_path, job_id, "error", message, finished=True)
            except BaseException:
                pass
        traceback.print_exc()
        return 1
    finally:
        if lock_handle is not None:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            finally:
                lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
