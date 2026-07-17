from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app" / "app.py").read_text(encoding="utf-8")
AGENT = ROOT / "deploy" / "agent" / "agent.py"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_release_and_agent_are_preserved():
    assert VERSION == "50.5.8-prod-r3-consumption-vm-node"
    assert hashlib.sha256(AGENT.read_bytes()).hexdigest() == (
        "87a145a7287739788f24b4d913fc9b58b904de1045312e5748b8ed8f29e0550b"
    )


def test_only_effective_consumption_page_is_replaced():
    assert APP.count('@app.route("/push/bandwidth-consumption", methods=["POST"])') == 1
    assert 'app.view_functions["bandwidth_consumption_page"] = bandwidth_consumption_page_v5058c' in APP
    assert '_v48140_cached_endpoint("bandwidth_consumption_page", V48140_PAGE_CACHE_TTL)' in APP
    assert APP.rfind('app.view_functions["bandwidth_consumption_page"]') > APP.find(
        'def bandwidth_consumption_page():'
    )


def test_final_ranges_tabs_limits_and_default_sort_contract():
    for marker in (
        '"1h": ("1H", 3600)',
        '"2h": ("2H", 2 * 3600)',
        '"6h": ("6H", 6 * 3600)',
        '"12h": ("12H", 12 * 3600)',
        '"24h": ("24H", 24 * 3600)',
        '"2d": ("2D", 2 * 86400)',
        '"7d": ("7D", 7 * 86400)',
        'V5058C_LIMITS = (100, 200, 500)',
        'return value if value in V5058C_PERIODS else "24h"',
        'default = "physical_public_total" if tab == "node" else "public_total"',
        'VM Consumption',
        'Node Consumption',
    ):
        assert marker in APP


def test_vm_consumption_reuses_existing_rollups_and_guest_direction():
    final = APP[APP.index("# 50.5.8-r3 Consumption VM/Node view") :]
    assert "FROM bandwidth_hourly" in final
    assert "FROM bandwidth_daily" in final
    assert "FROM node_bandwidth_consumption_2h" in final
    assert "FROM node_physical_net_stats" in final
    assert "consumption_vm_hourly" not in final
    assert "node_consumption_hourly" not in final
    assert "CASE WHEN bridge=? THEN host_tx" in final
    assert "CASE WHEN bridge=? THEN host_rx" in final


def test_final_ui_matches_agreed_identity_and_filter_contract():
    final = APP[APP.index("# 50.5.8-r3 Consumption VM/Node view") :]
    for marker in (
        "Search by UUID, Node, MAC or Node IP...",
        "Search by Node or Node IP...",
        "Node / Node IP",
        "PHYSICAL PUBLIC",
        "PHYSICAL PRIVATE",
        "PUBLIC CARD",
        "PRIVATE CARD",
        "All Coverage",
        "Latest Sample",
    ):
        assert marker in final
    assert "VM Public IP" not in final
    assert "Card 1" not in final
    assert "Card 2" not in final
    assert 'name="timezone"' not in final
    assert "Timezone</span>" not in final


def test_mac_is_search_only_not_a_visible_column():
    final = APP[APP.index("# 50.5.8-r3 Consumption VM/Node view") :]
    assert "vm_nic_identity_lookup" in final
    assert "LOWER(COALESCE(mil.mac,'')) LIKE LOWER(?)" in final
    assert "normalized_mac = normalize_mac_address(q)" in final
    assert 'mac_exact_sql = " OR mil.mac=?" if normalized_mac else ""' in final
    assert "<th>MAC</th>" not in final
    assert "Public IP / MAC" not in final
