#!/usr/bin/env python3
"""Automatic bounded-retention runner for VirtInfra Monitor v50 PostgreSQL Native.

This VirtInfra Monitor service is started by bw-monitor-retention.timer.  It shares the same
non-blocking global lock as manual maintenance, skips when a queued/running
manual job exists, and never VACUUMs the database.
"""
from __future__ import annotations

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import bw_pg as dbapi
import sys
import time

APP_FILE = Path(os.environ.get("BW_MONITOR_APP_FILE", "/opt/bw-monitor/app.py"))
LOCK_FILE = Path(os.environ.get("BW_MONITOR_MAINTENANCE_LOCK", "/run/lock/bw-monitor-maintenance.lock"))


def load_app():
    # Retention imports app.py only for the mature retention policy. Prevent
    # import-time inventory cleanup and any other startup write side effects.
    os.environ["BW_MAINTENANCE_IMPORT"] = "1"
    if not APP_FILE.is_file():
        raise RuntimeError(f"Application file not found: {APP_FILE}")
    sys.path.insert(0, str(APP_FILE.parent))
    spec = importlib.util.spec_from_file_location("bw_monitor_retention_app", str(APP_FILE))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load application module: {APP_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "run_retention") or not hasattr(module, "DB"):
        raise RuntimeError("Application does not expose run_retention() and DB")
    return module


def active_manual_jobs(db_path: str) -> int:
    conn = dbapi.connect(db_path, timeout=3)
    try:
        conn.execute("PRAGMA busy_timeout=3000")
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='maintenance_jobs'"
        ).fetchone()
        if not exists:
            return 0
        return int(conn.execute(
            "SELECT COUNT(*) FROM maintenance_jobs WHERE status IN ('queued','running')"
        ).fetchone()[0] or 0)
    finally:
        conn.close()


def main() -> int:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = LOCK_FILE.open("a+")
    try:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Retention skipped: another maintenance worker owns the global lock.")
            return 0

        module = load_app()
        db_path = str(module.DB)
        active = active_manual_jobs(db_path)
        if active:
            print(f"Retention skipped: {active} queued/running manual maintenance job(s).")
            return 0

        started = int(time.time())
        result = module.run_retention(dry_run=False)
        print(json.dumps({
            "ok": True,
            "version": "50.5.9-prod-r9-safe-runtime-history-prune",
            "started_at": started,
            "finished_at": int(time.time()),
            "result": result,
        }, ensure_ascii=False, separators=(",", ":"), default=str))
        return 0
    finally:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
