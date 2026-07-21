from __future__ import annotations

import ast
import hashlib
import hmac
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE = ROOT / "app" / "maintenance.py"
LAYER44 = ROOT / "app" / "runtime_layers" / "44_consumption_node_vm_rollup.py"
BACKUP = ROOT / "deploy" / "postgres" / "backup.sh"
VERSION = ROOT / "VERSION"


def _load_manifest_functions():
    source = MAINTENANCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {"_sha256_file", "_verify_backup_manifest"}
    body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    assert {node.name for node in body} == wanted
    module = ast.Module(body=body, type_ignores=[])
    namespace = {
        "Path": Path,
        "PurePosixPath": PurePosixPath,
        "hashlib": hashlib,
        "hmac": hmac,
        "RuntimeError": RuntimeError,
    }
    exec(compile(module, str(MAINTENANCE), "exec"), namespace)
    return namespace["_verify_backup_manifest"]


def test_release_and_consumption_cleanup_use_fifo_queue():
    assert VERSION.read_text(encoding="utf-8").strip() == "50.5.9-prod-r22.4-preflight-contract-hotfix"
    source = LAYER44.read_text(encoding="utf-8")
    route = source.split("def admin_bandwidth_consumption_action_r21():", 1)[1].split(
        'app.view_functions["admin_bandwidth_consumption_action"]', 1
    )[0]
    assert 'enqueue_maintenance_job("retention", parameters, actor)' in route
    assert '"scope": "consumption"' in route
    assert "DELETE FROM" not in route
    assert "def run_consumption_retention_cleanup(" in source
    assert "include_vm=False" in source
    assert "Consumption raw 48h + hourly/daily rollups 7d" in source


def test_worker_dispatches_consumption_retention_scope():
    source = MAINTENANCE.read_text(encoding="utf-8")
    assert 'scope = str(params.get("scope") or "all")' in source
    assert 'if scope == "consumption":' in source
    assert 'getattr(module, "run_consumption_retention_cleanup", None)' in source
    assert '"scope": "consumption"' in source


def test_existing_dot_slash_backup_manifest_is_verified(tmp_path):
    dump = tmp_path / "database.dump"
    listing = tmp_path / "database.list"
    dump.write_bytes(b"postgres custom dump\n")
    listing.write_text("header\nentry\n", encoding="utf-8")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(
        f"{hashlib.sha256(dump.read_bytes()).hexdigest()}  ./database.dump\n"
        f"{hashlib.sha256(listing.read_bytes()).hexdigest()}  ./database.list\n",
        encoding="utf-8",
    )
    verified = _load_manifest_functions()(tmp_path, sums)
    assert verified["database.dump"] == hashlib.sha256(dump.read_bytes()).hexdigest()
    assert verified["database.list"] == hashlib.sha256(listing.read_bytes()).hexdigest()
    assert "./database.dump" not in verified


def test_manifest_still_rejects_parent_traversal(tmp_path):
    outside = tmp_path.parent / "database.dump"
    outside.write_bytes(b"outside")
    listing = tmp_path / "database.list"
    listing.write_text("header\nentry\n", encoding="utf-8")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(
        f"{hashlib.sha256(outside.read_bytes()).hexdigest()}  ../database.dump\n"
        f"{hashlib.sha256(listing.read_bytes()).hexdigest()}  database.list\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="Unsafe backup manifest path"):
        _load_manifest_functions()(tmp_path, sums)


def test_new_backup_manifest_uses_bare_names():
    source = BACKUP.read_text(encoding="utf-8")
    assert "-printf '%f\\0'" in source
    assert "sha256sum -c SHA256SUMS" in source
