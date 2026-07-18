#!/usr/bin/env python3
"""Run deadlock-safe VirtInfra inventory expiry outside web requests."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

APP_FILE = Path(os.environ.get("BW_MONITOR_APP_FILE", "/opt/bw-monitor/app.py"))


def load_app_module():
    os.environ["BW_MAINTENANCE_IMPORT"] = "1"
    sys.path.insert(0, str(APP_FILE.parent))
    spec = importlib.util.spec_from_file_location("virtinfra_inventory_cleanup_app", APP_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {APP_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = load_app_module()
    try:
        runner = getattr(module, "run_inventory_cleanup_batches", None)
        if not callable(runner):
            raise RuntimeError("run_inventory_cleanup_batches is unavailable")
        result = runner()
        print(json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
        return 0
    finally:
        try:
            module.dbapi.close_pool()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
