"""Canonical source reader for the modular VirtInfra Monitor runtime."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
APP_PATH = APP_DIR / "app.py"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from runtime_loader import read_runtime_source  # noqa: E402


def read_app_source() -> str:
    return read_runtime_source(APP_DIR)
