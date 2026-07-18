from pathlib import Path
import hashlib
import re

ROOT = Path(__file__).resolve().parents[1]
VERSION = "50.6.0-prod-r2-node-groups-update-detection-fix"
APP = (ROOT / "app" / "app.py").read_text(encoding="utf-8")
FEATURE = (ROOT / "app" / "node_groups.py").read_text(encoding="utf-8")
SQL = (ROOT / "postgres" / "sql" / "011_node_groups_country_flags.sql").read_text(encoding="utf-8")


def test_release_and_additive_install_hook():
    assert (ROOT / "VERSION").read_text().strip() == VERSION
    assert "import node_groups as _v5060_node_groups" in APP
    assert "_v5060_node_groups.install(globals())" in APP
    assert f'RELEASE = "{VERSION}"' in FEATURE


def test_schema_has_node_only_membership_and_history():
    for marker in (
        "CREATE TABLE IF NOT EXISTS node_groups",
        "CREATE TABLE IF NOT EXISTS node_group_memberships",
        "node_name TEXT PRIMARY KEY",
        "CREATE TABLE IF NOT EXISTS node_group_membership_history",
        "node_groups_single_default",
        "node_group_history_one_open_row",
        "country_code ~ '^[A-Z]{2}$'",
    ):
        assert marker in SQL
    assert "vm_group" not in SQL.lower()
    assert "vm_uuid" not in SQL.lower()
    assert "primary_ipv4" not in SQL.lower()
    assert "private_ipv4" not in SQL.lower()


def test_admin_contract_and_exact_node_assignment():
    assert '("overview", "Overview")' in FEATURE
    assert '("nodes", "Nodes")' in FEATURE
    assert '("node_groups", "Node Groups")' in FEATURE
    assert '("vms", "VMs")' in FEATURE
    assert '("maintenance", "Maintenance")' in FEATURE
    block = FEATURE[FEATURE.index("def _validate_node_exists"):FEATURE.index("def group_save")]
    assert "SELECT 1 FROM node_inventory WHERE node=?" in block
    assert "node_name" in block
    assert "primary_ipv4" not in block
    assert "private_ipv4" not in block
    assert "vm_uuid" not in block


def test_vm_inherits_group_only_from_node():
    block = FEATURE[FEATURE.index("def admin_vms_section"):FEATURE.index("def admin_page")]
    assert "ngm.node_name=vi.node" in block
    assert "VMs have no direct Group assignment" in block
    assert "v5060_node_group_set" not in block
    assert "group_id" not in re.sub(r"group_value|group_name", "", block).split("SELECT vi.node", 1)[1].split("FROM vm_inventory", 1)[0]


def test_flags_are_local_small_and_vendored():
    flags = list((ROOT / "static" / "flags" / "4x3").glob("*.svg"))
    assert len(flags) >= 249
    for code in ("jp", "us", "sg", "vn", "gb"):
        assert (ROOT / "static" / "flags" / "4x3" / f"{code}.svg").is_file()
    assert "width:16px!important;height:12px!important" in FEATURE
    assert "COUNTRY_CODES" in FEATURE
    assert "supported ISO 3166-1 alpha-2" in FEATURE
    assert '/static/flags/4x3/{code.lower()}.svg' in FEATURE
    assert (ROOT / "THIRD_PARTY_LICENSES" / "flag-icons-LICENSE.txt").is_file()
    assert "flag-icons 7.5.0" in (ROOT / "THIRD_PARTY_NOTICES.md").read_text()


def test_group_and_node_filters_and_ungrouped():
    assert 'name="group_id"' in FEATURE
    assert 'name="node"' in FEATURE
    assert 'value="ungrouped"' in FEATURE
    assert "ngm.node_name IS NULL" in FEATURE
    assert "Group filter" not in APP[-1000:]  # feature remains isolated in module


def test_group_consumption_uses_node_counters_and_weighted_coverage():
    block = FEATURE[FEATURE.index("def _group_consumption_rows"):FEATURE.index("def _group_consumption_table")]
    assert '_v5058c_node_source_sql' in block
    assert "SUM(a.coverage_seconds)" in block
    assert "(?*COUNT(v.node))" in block
    assert "AVG(" not in block.upper()
    assert "physical_public_rx" in block and "physical_private_tx" in block
    assert "vm_rows" not in block


def test_existing_agent_is_byte_identical_to_r3_baseline():
    baseline = Path("/mnt/data/_r3_slim/virtinfra-monitor-50.5.9-prod-r3-ui-alignment-overflow-hotfix/deploy/agent/agent.py")
    if not baseline.exists():
        return
    current = ROOT / "deploy" / "agent" / "agent.py"
    assert hashlib.sha256(current.read_bytes()).digest() == hashlib.sha256(baseline.read_bytes()).digest()


def test_installer_applies_new_idempotent_migration():
    installer = (ROOT / "deploy" / "postgres" / "install-postgres-native.sh").read_text()
    assert "011_node_groups_country_flags.sql" in installer
    assert installer.count("011_node_groups_country_flags.sql") >= 3
    assert "CREATE TABLE IF NOT EXISTS" in SQL
    assert "CREATE INDEX IF NOT EXISTS" in SQL


def test_dashboard_node_tuple_contract_is_preserved():
    assert '_wrap_row_function("get_node_rows", tuple_position=0)' in FEATURE
    assert '_wrap_row_function("get_node_health_rows")' in FEATURE


def test_membership_history_preserves_deleted_group_id_and_tracks_ungrouped():
    assert "group_id BIGINT," in SQL
    assert "ON DELETE SET NULL" not in SQL
    block = FEATURE[FEATURE.index("def _set_node_group"):FEATURE.index("def group_save")]
    assert "VALUES(?,NULL,?,NULL,?)" in block
