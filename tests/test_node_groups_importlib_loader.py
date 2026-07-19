import importlib.util
import sys
import types
from pathlib import Path
from runtime_source import read_app_source


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "app.py"
MARKER = "# VirtInfra Monitor 50.5.9 prod-r5 - additive Node Groups hotfix"


def _loader_source() -> str:
    source = read_app_source()
    marker_pos = source.index(MARKER)
    block_start = source.rfind("# ---------------------------------------------------------------------------", 0, marker_pos)
    assert block_start >= 0
    return "sentinel = 'before'\n" + source[block_start:]


def _execute_loader(tmp_path: Path, *, register_target: bool):
    target_name = "bw_monitor_schema_loader_contract"
    target_file = tmp_path / "loader_contract.py"
    target_file.write_text(_loader_source(), encoding="utf-8")

    fake_node_groups = types.ModuleType("node_groups")
    received = {}

    def install(module):
        received["module"] = module
        assert getattr(module, "sentinel") == "before"
        setattr(module, "sentinel", "after")
        setattr(module, "_NODE_GROUPS_HOTFIX_INSTALLED", True)

    fake_node_groups.install = install

    old_node_groups = sys.modules.get("node_groups")
    old_target = sys.modules.get(target_name)
    try:
        sys.modules["node_groups"] = fake_node_groups
        spec = importlib.util.spec_from_file_location(target_name, target_file)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        if register_target:
            sys.modules[target_name] = module
        else:
            sys.modules.pop(target_name, None)
        spec.loader.exec_module(module)
        return module, received["module"]
    finally:
        if old_node_groups is None:
            sys.modules.pop("node_groups", None)
        else:
            sys.modules["node_groups"] = old_node_groups
        if old_target is None:
            sys.modules.pop(target_name, None)
        else:
            sys.modules[target_name] = old_target


def test_loader_supports_exec_module_without_sys_modules_registration(tmp_path):
    module, installed_target = _execute_loader(tmp_path, register_target=False)
    assert module.sentinel == "after"
    assert module._NODE_GROUPS_HOTFIX_INSTALLED is True
    assert installed_target.__class__.__name__ == "_NodeGroupsModuleProxy"


def test_loader_preserves_normal_import_module_identity(tmp_path):
    module, installed_target = _execute_loader(tmp_path, register_target=True)
    assert installed_target is module
    assert module.sentinel == "after"
    assert module._NODE_GROUPS_HOTFIX_INSTALLED is True


def test_actual_app_schema_import_matches_installer_without_sys_modules_registration(tmp_path):
    import os
    import subprocess

    script = r'''
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

root = Path(os.environ["VIRTINFRA_ROOT"])
helper_spec = importlib.util.spec_from_file_location(
    "node_groups_runtime_validation",
    root / "tools" / "node-groups-runtime-validation.py",
)
helper = importlib.util.module_from_spec(helper_spec)
helper_spec.loader.exec_module(helper)

with tempfile.TemporaryDirectory(prefix="virtinfra-schema-import-") as temp:
    database = Path(temp) / "schema.sqlite3"
    os.environ.update({
        "BW_MONITOR_DB": str(database),
        "BW_ADMIN_USERNAME": "rootadmin",
        "BW_ADMIN_PASSWORD_HASH": "",
        "BW_ADMIN_SECRET_KEY": "schema-import-contract-secret",
        "BW_MONITOR_TOKEN": "schema-import-contract-token",
        "BW_START_BACKGROUND_THREADS": "0",
    })
    helper.install_sqlite_shim(database)
    sys.path.insert(0, str(root / "app"))
    spec = importlib.util.spec_from_file_location("bw_monitor_schema", root / "app" / "app.py")
    module = importlib.util.module_from_spec(spec)
    assert "bw_monitor_schema" not in sys.modules
    spec.loader.exec_module(module)
    assert module._NODE_GROUPS_HOTFIX_INSTALLED is True
    assert len(module.app.url_map._rules) == 83
    print("SCHEMA_IMPORT_OK")
'''
    env = dict(os.environ)
    env["VIRTINFRA_ROOT"] = str(ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "SCHEMA_IMPORT_OK" in proc.stdout
