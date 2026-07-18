#!/usr/bin/env python3
"""Claim and start exactly one FIFO maintenance job."""
from __future__ import annotations

import subprocess
import time

import maintenance_native
import maintenance_queue

STARTING_STALE_SECONDS = 120
RUNNING_HEARTBEAT_STALE_SECONDS = 300
LEGACY_ACTIONS = {"clear_live_cache", "checkpoint"}


def unit_active(unit: str) -> bool:
    if not unit:
        return False
    proc = subprocess.run(
        ["systemctl", "is-active", "--quiet", unit],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    return proc.returncode == 0


def recover_stale_rows() -> None:
    now = int(time.time())
    conn = maintenance_queue.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.maintenance_jobs
                   SET status='cancelled', finished_at=%s, progress=100,
                       message='Legacy maintenance action retired during 50.5.7 upgrade'
                 WHERE action = ANY(%s)
                   AND status IN ('queued','starting','running')
                """,
                (now, list(LEGACY_ACTIONS)),
            )
            cur.execute(
                """
                SELECT id,status,COALESCE(unit_name,''),created_at,
                       COALESCE(started_at,0),COALESCE(heartbeat_at,0)
                  FROM public.maintenance_jobs
                 WHERE status IN ('starting','running')
                 ORDER BY id
                """
            )
            rows = cur.fetchall()
        conn.commit()
    finally:
        conn.close()

    for job_id, status, unit, created_at, started_at, heartbeat_at in rows:
        if unit_active(str(unit or "")):
            continue
        age = now - int(started_at or created_at or now)
        heartbeat_age = now - int(heartbeat_at or started_at or created_at or now)
        stale = (
            (status == "starting" and age >= STARTING_STALE_SECONDS)
            or (status == "running" and heartbeat_age >= RUNNING_HEARTBEAT_STALE_SECONDS)
        )
        if not stale:
            continue
        conn = maintenance_queue.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.maintenance_jobs
                       SET status='error', finished_at=%s, progress=100,
                           message=%s
                     WHERE id=%s AND status=%s
                    """,
                    (now, f"Recovered stale {status} job; systemd unit is inactive", int(job_id), status),
                )
            conn.commit()
        finally:
            conn.close()


def claim_next() -> tuple[int, str] | None:
    now = int(time.time())
    conn = maintenance_queue.connect()
    try:
        with conn.cursor() as cur:
            maintenance_native.advisory_xact_lock(cur, "virtinfra-monitor:maintenance:dispatch")
            cur.execute(
                """
                SELECT 1 FROM public.maintenance_jobs
                 WHERE status IN ('starting','running')
                 LIMIT 1
                """
            )
            if cur.fetchone():
                conn.commit()
                return None
            cur.execute(
                """
                WITH next_job AS (
                    SELECT id
                      FROM public.maintenance_jobs
                     WHERE status='queued' AND COALESCE(cancel_requested,FALSE)=FALSE
                     ORDER BY id
                     FOR UPDATE SKIP LOCKED
                     LIMIT 1
                )
                UPDATE public.maintenance_jobs AS jobs
                   SET status='starting',
                       started_at=COALESCE(jobs.started_at,%s),
                       heartbeat_at=%s,
                       attempt=COALESCE(jobs.attempt,0)+1,
                       message='Dispatcher claimed job; starting systemd worker'
                  FROM next_job
                 WHERE jobs.id=next_job.id
                RETURNING jobs.id, jobs.unit_name
                """,
                (now, now),
            )
            row = cur.fetchone()
        conn.commit()
        return (int(row[0]), str(row[1])) if row else None
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_start_error(job_id: int, message: str) -> None:
    conn = maintenance_queue.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.maintenance_jobs
                   SET status='error', finished_at=%s, progress=100, message=%s
                 WHERE id=%s AND status='starting'
                """,
                (int(time.time()), message[:4000], int(job_id)),
            )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    recover_stale_rows()
    claimed = claim_next()
    if not claimed:
        return 0
    job_id, unit = claimed
    proc = subprocess.run(
        ["systemctl", "--no-block", "start", unit],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        mark_start_error(job_id, (proc.stdout or "systemctl start failed").strip())
        maintenance_queue.wake_dispatcher()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
