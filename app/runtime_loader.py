"""Ordered loader for the modular VirtInfra Monitor runtime.

Each layer is compiled with its own filename for useful tracebacks, then executed
inside the application module namespace.  This preserves the exact historical
binding/override order while keeping the entrypoint small and reviewable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import MutableMapping, Any


def runtime_layer_paths(app_dir: Path) -> tuple[Path, ...]:
    layer_dir = app_dir / "runtime_layers"
    manifest = json.loads((layer_dir / "manifest.json").read_text(encoding="utf-8"))
    paths = tuple(layer_dir / item["file"] for item in manifest)
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing VirtInfra runtime layers: {missing}")
    return paths


def read_runtime_source(app_dir: Path) -> str:
    """Return the canonical runtime source in original execution order."""
    return "".join(path.read_text(encoding="utf-8") for path in runtime_layer_paths(app_dir))


def execute_runtime_layers(namespace: MutableMapping[str, Any], app_dir: Path) -> None:
    """Execute every runtime layer in one shared module namespace."""
    for path in runtime_layer_paths(app_dir):
        source = path.read_text(encoding="utf-8")
        code = compile(source, str(path), "exec")
        exec(code, namespace, namespace)
