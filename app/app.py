"""VirtInfra Monitor WSGI entrypoint.

The production runtime is split into ordered modules under ``runtime_layers``.
All layers execute in this module namespace so existing Gunicorn imports,
endpoint names and append-only compatibility overrides remain unchanged.
"""
from pathlib import Path as _Path

from runtime_loader import execute_runtime_layers as _execute_runtime_layers

_execute_runtime_layers(globals(), _Path(__file__).resolve().parent)

del _execute_runtime_layers
# Keep _Path private; some operational debuggers inspect the module namespace.
