from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from runtime_source import read_app_source

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
ENTRYPOINT = APP_DIR / "app.py"
LOADER = APP_DIR / "runtime_loader.py"
LAYER_DIR = APP_DIR / "runtime_layers"
MANIFEST = LAYER_DIR / "manifest.json"


def _manifest() -> list[dict[str, object]]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def test_wsgi_entrypoint_is_small_and_declarative() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert len(source.splitlines()) <= 40
    assert "execute_runtime_layers" in source
    assert "@app.route" not in source
    assert "CREATE TABLE" not in source


def test_runtime_manifest_is_complete_ordered_and_hash_pinned() -> None:
    manifest = _manifest()
    assert len(manifest) >= 40
    names = [str(item["file"]) for item in manifest]
    assert names == sorted(names)
    assert len(names) == len(set(names))
    assert names[0] == "00_bootstrap_database.py"
    assert names[-1] == "43_node_groups_loader.py"

    previous_end = 0
    for item in manifest:
        path = LAYER_DIR / str(item["file"])
        assert path.is_file(), path
        start = int(item["start_line"])
        end = int(item["end_line"])
        assert start == previous_end + 1
        assert end >= start
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 2000
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        previous_end = end


def test_combined_runtime_remains_the_full_legacy_contract() -> None:
    source = read_app_source()
    tree = ast.parse(source, filename="<virtinfra-modular-runtime>")
    assert len(source.splitlines()) == 31406
    assert any(isinstance(node, ast.FunctionDef) and node.name == "push" for node in tree.body)
    assert '@app.route("/push", methods=["POST"])' in source
    assert "_node_groups_hotfix.install(_node_groups_module)" in source


def test_loader_and_installer_ship_every_runtime_layer() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    installer = (ROOT / "deploy/postgres/provision-postgres-native.sh").read_text(encoding="utf-8")
    bootstrap = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "manifest.json" in loader
    assert 'rm -rf -- "$APP_DIR/runtime_layers"' in installer
    assert 'find "$APP_SRC/runtime_layers"' in installer
    assert "app/runtime_loader.py" in bootstrap
    assert "app/runtime_layers/manifest.json" in bootstrap
