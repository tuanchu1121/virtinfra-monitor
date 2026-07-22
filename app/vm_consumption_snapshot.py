#!/usr/bin/env python3
"""Build shared VM Consumption snapshots outside web requests."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

APP_FILE = Path(os.environ.get("BW_MONITOR_APP_FILE", "/opt/bw-monitor/app.py"))


def load_app_module():
    os.environ["BW_MAINTENANCE_IMPORT"] = "1"
    sys.path.insert(0, str(APP_FILE.parent))
    spec = importlib.util.spec_from_file_location("virtinfra_vm_consumption_snapshot_app", APP_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {APP_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", action="append", dest="periods")
    parser.add_argument("--window-end", type=int, default=0)
    args = parser.parse_args()

    module = load_app_module()
    try:
        builder = getattr(module, "build_vm_consumption_snapshots", None)
        if not callable(builder):
            raise RuntimeError("build_vm_consumption_snapshots is unavailable")
        result = builder(args.periods, args.window_end or None)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
        failed = any(item.get("status") == "failed" for item in result.get("snapshots", []))
        return 1 if failed else 0
    finally:
        try:
            module.dbapi.close_pool()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
