from pathlib import Path
import ast
from functools import lru_cache

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app/app.py").read_text(encoding="utf-8")
AGENT = (ROOT / "deploy/agent/agent.py").read_text(encoding="utf-8")
INSTALLER = (ROOT / "deploy/postgres/install-postgres-native.sh").read_text(encoding="utf-8")
MIGRATION = (ROOT / "postgres/sql/008_mac_identity_search.sql").read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def function_sources(source: str, name: str):
    tree = ast.parse(source)
    lines = source.splitlines()
    return [
        "\n".join(lines[node.lineno - 1:node.end_lineno])
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]


def last_function(source: str, name: str) -> str:
    matches = function_sources(source, name)
    assert matches, name
    return matches[-1]


def load_normalizer():
    source = last_function(APP, "normalize_mac_address")
    namespace = {}
    exec(source, namespace)
    return namespace["normalize_mac_address"]


def test_release_identity():
    assert (ROOT / "VERSION").read_text().strip() == "50.5.9-prod-r5-node-groups-hotfix-additive"


def test_existing_agent_already_reports_vm_and_physical_mac():
    domif = last_function(AGENT, "parse_domiflist")
    assert '"mac": p[4]' in domif
    assert '"mac": mac' in AGENT
    assert '"physical_interfaces"' in AGENT
    assert 'meta["address"]' in AGENT


def test_mac_normalizer_accepts_common_operator_formats():
    normalize = load_normalizer()
    expected = "52:54:00:ab:cd:ef"
    assert normalize(expected) == expected
    assert normalize("52-54-00-AB-CD-EF") == expected
    assert normalize("5254.00ab.cdef") == expected
    assert normalize("525400abcdef") == expected
    assert normalize("invalid") == ""


def test_additive_schema_and_indexes_exist():
    assert "ALTER TABLE public.vm_iface_current" in MIGRATION
    assert "ADD COLUMN IF NOT EXISTS mac" in MIGRATION
    assert "ALTER TABLE public.node_physical_net_latest" in MIGRATION
    assert "idx_vm_iface_current_mac" in MIGRATION
    assert "idx_node_physical_net_latest_mac" in MIGRATION
    assert "008_mac_identity_search.sql" in INSTALLER
    assert "Apply MAC identity and search schema" in INSTALLER


def test_application_schema_can_self_heal_existing_installations():
    assert 'ensure_column(conn, "vm_iface_current", "mac"' in APP
    assert 'ensure_column(conn, "node_physical_net_latest", "mac"' in APP
    assert "vm_nic_identity_lookup" in APP
    assert "node_nic_identity_lookup" in APP
    assert "idx_vm_iface_current_mac ON vm_iface_current" not in APP
    assert "idx_node_physical_net_latest_mac ON node_physical_net_latest" not in APP


def test_vm_mac_survives_native_copy_and_current_merge():
    rows = last_function(APP, "_v5052_iface_rows")
    writer = last_function(APP, "_v5052_current_writer")
    assert "normalize_mac_address(item.get(\"mac\"))" in rows
    assert "INSERT INTO vm_iface_current" in writer
    assert "mac,last_seen" in writer.replace(" ", "")
    assert "excluded.mac" in writer
    assert "vm_iface_current.mac" in writer


def test_physical_uplink_mac_is_persisted_for_br0_br1_roles():
    push = last_function(APP, "push")
    assert "INSERT INTO node_physical_net_latest" in push
    assert "alert_level, alert_flags, mac" in push
    assert "excluded.mac" in push
    assert "node_physical_net_latest.mac" in push
    assert "normalize_mac_address(item.get(\"mac\"))" in push


def test_search_accepts_mac_and_opens_unique_vm_directly():
    resolver = last_function(APP, "resolve_direct_vm_search")
    top = last_function(APP, "top_page_v484")
    nodes = last_function(APP, "_v48134_admin_nodes")
    vms = last_function(APP, "_v48134_admin_vms")
    assert "FROM vm_nic_identity_lookup" in resolver
    assert "JOIN vm_iface_current" in resolver
    assert "normalize_mac_address(q)" in resolver
    assert "l.mac LIKE ?" in resolver
    assert 'result.update({"iface":"","bridge":""})' in resolver
    assert "resolve_direct_vm_search(q)" in top
    assert "node_physical_net_latest" in nodes
    assert "vm_iface_current" in nodes
    assert "vm_iface_current" in vms


def test_vm_and_node_detail_show_requested_identity():
    vm_card = last_function(APP, "vm_network_identity_card")
    vm_route = last_function(APP, "vm_page_v5057_mac_identity")
    node_badges = last_function(APP, "node_nic_badges")
    physical_period = last_function(APP, "get_node_physical_nic_period")
    for label in ("Interface", "MAC", "VM UUID", "Node", "Bridge", "Seen"):
        assert label in vm_card
    assert "vm_network_identity_card(node, vm_uuid)" in vm_route
    assert "Physical MAC" in node_badges
    assert "FROM node_physical_net_latest" in physical_period
    assert '"bridge_mac"' in physical_period


def test_bridge_and_physical_mac_upserts_reference_their_own_target_tables():
    push = last_function(APP, "push")
    bridge_start = push.index("INSERT INTO node_bridge_addresses_latest")
    physical_start = push.index("INSERT INTO node_physical_net_latest", bridge_start)
    bridge_upsert = push[bridge_start:physical_start]
    physical_upsert = push[physical_start:]

    assert "ELSE node_bridge_addresses_latest.mac" in bridge_upsert
    assert "ELSE node_physical_net_latest.mac" not in bridge_upsert
    assert "ELSE node_physical_net_latest.mac" in physical_upsert
