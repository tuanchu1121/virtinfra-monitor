"""PostgreSQL-backed FIFO maintenance queue for VirtInfra Monitor.

The web process only inserts jobs and wakes the dispatcher.  The dispatcher
atomically claims one queued row, starts the matching systemd worker, and the
worker reports heartbeat/progress until it reaches a terminal state.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any

import psycopg

import maintenance_native

DISPATCH_SERVICE = os.environ.get(
    "BW_MAINTENANCE_DISPATCH_SERVICE",
    "bw-monitor-maintenance-dispatch.service",
)
ALLOWED_ACTIONS = {
    "retention", "vacuum", "delete_history", "delete_compact",
    "clear_monitoring_data", "reset_app_data",
    "purge_nodes", "purge_node_vms", "purge_vms",
    "clear_api_logs", "clear_api_data",
}
TERMINAL_STATES = {"ok", "error", "cancelled"}
ACTIVE_STATES = {"starting", "running"}


def now_ts() -> int:
    return int(time.time())


def connect(*, autocommit: bool = False) -> psycopg.Connection:
    return maintenance_native.dedicated_connection(
        autocommit=autocommit,
        application_name="virtinfra-maintenance-queue",
        statement_timeout_ms=30_000,
        lock_timeout_ms=15_000,
    )


def wake_dispatcher() -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["systemctl", "--no-block", "start", DISPATCH_SERVICE],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
            check=False,
        )
        return proc.returncode == 0, (proc.stdout or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def enqueue_job(
    action: str,
    parameters: dict[str, Any] | None,
    actor: str,
    *,
    exclusive: bool = False,
) -> tuple[int, str]:
    action = str(action or "").strip().lower()
    if action not in ALLOWED_ACTIONS:
        raise ValueError("Unsupported maintenance action")
    payload = json.dumps(parameters or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    created = now_ts()
    conn = connect()
    try:
        with conn.cursor() as cur:
            maintenance_native.advisory_xact_lock(cur, maintenance_native.MAINTENANCE_ENQUEUE_LOCK)
            cur.execute(
                """
                SELECT id, status
                FROM public.maintenance_jobs
                WHERE action='reset_app_data'
                  AND status IN ('queued','starting','running')
                ORDER BY id
                LIMIT 1
                """
            )
            nuclear = cur.fetchone()
            if nuclear and not exclusive:
                raise RuntimeError(
                    f"Nuclear reset job #{nuclear[0]} is {nuclear[1]}; "
                    "new maintenance work is blocked until it finishes"
                )
            if exclusive:
                cur.execute(
                    """
                    SELECT id, action, status
                    FROM public.maintenance_jobs
                    WHERE status IN ('queued','starting','running')
                    ORDER BY id
                    LIMIT 1
                    """
                )
                active = cur.fetchone()
                if active:
                    raise RuntimeError(
                        f"Maintenance queue is not empty: job #{active[0]} "
                        f"({active[1]}) is {active[2]}"
                    )
            cur.execute(
                """
                INSERT INTO public.maintenance_jobs(
                    created_at, action, parameters, status, requested_by,
                    message, heartbeat_at, progress, attempt, cancel_requested
                )
                VALUES (%s,%s,%s,'queued',%s,'Waiting in FIFO queue',NULL,0,0,FALSE)
                RETURNING id
                """,
                (created, action, payload, actor or "admin"),
            )
            job_id = int(cur.fetchone()[0])
            unit_name = f"bw-monitor-maintenance@{job_id}.service"
            cur.execute(
                "UPDATE public.maintenance_jobs SET unit_name=%s WHERE id=%s",
                (unit_name, job_id),
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    woke, detail = wake_dispatcher()
    if not woke:
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE public.maintenance_jobs SET message=%s WHERE id=%s AND status='queued'", ("Queued; immediate dispatcher wake failed, watchdog will retry: " + detail[:500], job_id))
            conn.commit()
        finally:
            conn.close()
    return job_id, unit_name


def cancel_queued_job(job_id: int, actor: str) -> bool:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.maintenance_jobs
                   SET status='cancelled', finished_at=%s, progress=100,
                       message=%s
                 WHERE id=%s AND status='queued'
                """,
                (now_ts(), f"Cancelled by {actor or 'admin'} before execution", int(job_id)),
            )
            changed = cur.rowcount == 1
        conn.commit()
        return changed
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def active_job() -> tuple[int, str, str] | None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, action, status
                FROM public.maintenance_jobs
                WHERE status IN ('starting','running')
                ORDER BY id
                LIMIT 1
                """
            )
            row = cur.fetchone()
            return (int(row[0]), str(row[1]), str(row[2])) if row else None
    finally:
        conn.close()
