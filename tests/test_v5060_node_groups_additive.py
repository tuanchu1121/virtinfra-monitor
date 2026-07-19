from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app" / "app.py"
APP = APP_PATH.read_text(encoding="utf-8")
MODULE_PATH = ROOT / "app" / "node_groups.py"
MODULE = MODULE_PATH.read_text(encoding="utf-8")
VERSION = "50.6.0-prod-r1-node-groups-additive"
BASELINE_APP_SIZE = 2049352
BASELINE_APP_SHA256 = "d4f24dc98fa36d7037462a0d57b5cde075de1261eb9c3b8e8effde2e1627a5ef"

PROTECTED = {
    "deploy/agent/agent.py": "d637ec4fa0de2e07622402e3da60ae54ccf2d3f84f046de2141c813ee3b58081",
    "deploy/agent/fix-agent-uuid.sh": "12b4e2b5359198f6ba5c0947f1e6ca21bf4d58bdce9c05a91d7dec49b4eae0e1",
    "app/bw_pg.py": "c13ced0096c939dc89e2ffceb9f6ee08be60512c2b15337370c80bd8e437568b",
    "app/storage_v2.py": "064ef89bb5ee86cfe65ed7b400c4d52194dd9ea7b4654e054f36e712c633dd1a",
    "app/retention.py": "5c77773ba1ff011b0a36c495f64051431fdb40b508d6ae514911253753d85aac",
    "app/maintenance_native.py": "8530519896f19d27e2b0e9b686519e9e95bf3a30f3b49833cab7b71747ca9935",
    "app/maintenance_queue.py": "e1bb7ca921c3c01c6649f627127aa1336824bae33675da0bf229d28fc2084442",
    "app/maintenance_dispatch.py": "ac772f1b92da9159e1913ed8060dfc534dbf4c16ae802048bb01f4ac3198d163",
    "app/inventory_cleanup.py": "b3ec9a4cf718ad05be2bc1549ae1cab267f43f04ce17fbd369477c1b985d914a",
    "app/consumption_rollup.py": "551abed8f714557cb40bc604913242adc2fb2856f9fc9096aeae21291cd80b8d",
    "postgres/sql/001_bootstrap.sql": "5cf8ab9cf07c206d6d995d1b8577c0dc1536ee858c0fa26466f6d73ad94f1ee9",
    "postgres/sql/002_timescale.sql": "4d731d64f1fa24c1f99c4cb39348c4f1c2b66e3a48dfa0d54a0bb2ce60593424",
    "postgres/sql/003_native_indexes.sql": "e9c8f01d402aedc0ab71f513ec71d420e9f8b9a6a3c26f907a761a299cb5ca4b",
    "postgres/sql/004_storage_v2.sql": "34386ec8032aecb7b334dbdcf841c20631f23144660d1463cf6cdf8b46b2f5d2",
    "postgres/sql/005_ingest_write_profile.sql": "ea6345d96143030468205b9fdf5a7119482da5f004f7b9c54946c7c33a769769",
    "postgres/sql/006_postgres_native_maintenance.sql": "f4f1b35a8bcc0e3d1d3372c4bdc8d9af44beda2d1db06d8ab2fea9c9dbc62466",
    "postgres/sql/007_safe_maintenance_queue.sql": "7b27833ab03b4056eb7474a185928f5298d0fbe06cfafceeb06828fc6ec3feb1",
    "postgres/sql/008_mac_identity_search.sql": "3914303221f7445aa3e91fada5a095030ccf7211cb2e1fb59bcb6360b31a54b1",
    "postgres/sql/009_low_io_compat.sql": "17e732b1521a1274b558fa765b0692881d8b5c87086c65b2b746e9f3ed99f827",
    "postgres/sql/010_consumption_inventory_cleanup.sql": "8751dcb01bd2788d00a61a537510e47a492284cb788ab9ecb3e78557b90f80b4",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function_source(name: str) -> str:
    tree = ast.parse(MODULE)
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    return ast.get_source_segment(MODULE, node) or ""


def test_release_is_built_directly_on_the_r3_slim_application_prefix():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == VERSION
    data = APP_PATH.read_bytes()
    assert len(data) > BASELINE_APP_SIZE
    assert hashlib.sha256(data[:BASELINE_APP_SIZE]).hexdigest() == BASELINE_APP_SHA256
    suffix = data[BASELINE_APP_SIZE:].decode("utf-8")
    assert "V5060_RELEASE" in suffix
    assert "_v5060_node_groups.install(globals())" in suffix


def test_protected_runtime_agent_metric_retention_queue_and_sql_files_are_unchanged():
    for rel, expected in PROTECTED.items():
        assert sha(ROOT / rel) == expected, rel


def test_schema_is_additive_and_vm_has_no_direct_group_relation():
    migration = (ROOT / "postgres/sql/011_node_groups_country_flags.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS node_groups" in migration
    assert "CREATE TABLE IF NOT EXISTS node_group_memberships" in migration
    assert "CREATE TABLE IF NOT EXISTS node_group_membership_history" in migration
    assert "node_name TEXT PRIMARY KEY" in migration
    assert "ALTER TABLE vm_inventory" not in migration
    assert not re.search(r"CREATE\s+TABLE[^;]*vm[_-]?group", migration, re.I | re.S)


def test_assignment_is_exact_node_name_only_and_not_ip_based():
    source = function_source("_set_node_group") + function_source("_validate_node_exists")
    assert "node_inventory WHERE node=?" in source
    assert "node_group_memberships WHERE node_name=?" in source
    assert "primary_ipv4" not in source
    assert "private_ipv4" not in source
    assert "public_ipv4" not in source


def test_existing_admin_bulk_actions_and_search_contract_are_retained():
    nodes = function_source("admin_nodes_section")
    vms = function_source("admin_vms_section")
    for marker in ("admin_bulk_nodes", "purge_vms", "admin_delete_node", "admin_restore_node"):
        assert marker in nodes
    for marker in ("admin_bulk_vms", "admin_delete_vm", "admin_restore_vm"):
        assert marker in vms
    assert "primary_ipv4" in nodes and "ipv4_json" in nodes and "last_iface" in nodes
    assert "primary_ipv4" in vms and "ipv4_json" in vms and "last_iface" in vms


def test_new_api_namespace_and_scopes_are_additive():
    required = {
        "/api/v1/node-groups",
        "/api/v1/node-groups/<int:group_id>",
        "/api/v1/node-groups/<int:group_id>/nodes",
        "/api/v1/node-groups/<int:group_id>/vms",
        "/api/v1/node-groups/<int:group_id>/consumption",
        "/api/v1/nodes/<path:node_name>/group",
        "/api/v1/nodes/ungrouped",
    }
    for path in required:
        assert path in MODULE
    assert 'supported["node_groups:read"]' in MODULE
    assert 'supported["node_groups:write"]' in MODULE
    assert "API_SUPPORTED_SCOPES[" not in APP[BASELINE_APP_SIZE:]


def test_local_flags_are_small_vendored_and_iso_country_list_is_used():
    flags = sorted((ROOT / "static/flags/4x3").glob("*.svg"))
    assert len(flags) == 271
    for code in ("jp", "us", "sg", "vn", "gb"):
        assert (ROOT / f"static/flags/4x3/{code}.svg").is_file()
    countries = json.loads((ROOT / "static/flags/countries.json").read_text(encoding="utf-8"))
    iso_codes = {str(item["code"]).upper() for item in countries if item.get("iso")}
    assert {"JP", "US", "SG", "VN", "GB"} <= iso_codes
    assert "width:16px!important;height:12px!important" in MODULE
    assert (ROOT / "THIRD_PARTY_LICENSES/flag-icons-LICENSE.txt").is_file()
    assert "flag-icons" in (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")


def test_no_filter_wrappers_return_the_established_result_untouched():
    source = function_source("_wrap_row_function")
    assert "if not _group_value() and not _node_value():" in source
    assert "return base(*args, **kwargs)" in source


def test_installer_only_adds_module_migration_flags_and_safe_update_detection():
    installer = (ROOT / "deploy/postgres/install-postgres-native.sh").read_text(encoding="utf-8")
    assert 'install -m 0644 "$APP_SRC/node_groups.py"' in installer
    assert "011_node_groups_country_flags.sql" in installer
    assert 'install -m 0644 "$REPO_ROOT/static/flags/4x3/"*.svg' in installer
    assert "APP_PRESENT" in installer and "SERVICE_PRESENT" in installer
    assert "Could not recover the existing PostgreSQL password" in installer


def test_group_consumption_coverage_is_weighted_by_valid_and_expected_seconds():
    source = function_source("_group_consumption_rows") + function_source("_consumption_group_snapshot")
    assert "SUM(a.coverage_seconds)" in source
    assert "expected_seconds" in source
    assert "AVG(" not in source.upper()
