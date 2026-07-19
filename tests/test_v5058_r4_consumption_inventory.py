from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app" / "app.py").read_text(encoding="utf-8")
AGENT = (ROOT / "deploy" / "agent" / "agent.py").read_text(encoding="utf-8")
INSTALLER = (ROOT / "deploy" / "postgres" / "install-postgres-native.sh").read_text(encoding="utf-8")
TIMER = (ROOT / "deploy" / "postgres" / "bw-monitor-inventory-cleanup.timer").read_text(encoding="utf-8")
SQL = (ROOT / "postgres" / "sql" / "010_consumption_inventory_cleanup.sql").read_text(encoding="utf-8")
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_release_identity():
    assert VERSION == "50.5.9-prod-r7-production-minimal-rbac-visibility-ui-hotfix"
    assert VERSION in APP
    assert VERSION in INSTALLER


def test_inventory_cleanup_is_not_executed_by_get_routes():
    start = APP.index("def auto_cleanup_inventory():")
    body = APP[start:APP.index("def vm_live_status", start)]
    assert 'return {"deferred": True}' in body
    assert "UPDATE vm_inventory" not in body
    assert "run_inventory_cleanup_batches" in APP
    cleanup = APP[APP.index("def run_inventory_cleanup_batches"):]
    assert "FOR UPDATE SKIP LOCKED" in cleanup
    assert "pg_try_advisory_lock" in cleanup
    assert "status='active'" in cleanup
    assert "last_seen<?" in cleanup
    assert "status='stale'" in cleanup
    assert "status IN ('active','stale','missing')" in cleanup
    assert "SET status='active'" not in cleanup.split("# ----- Fast, rolling-window Consumption readers", 1)[0]


def test_cleanup_timer_is_offset_from_five_minute_pushes():
    assert "OnCalendar=*-*-* *:02/10:00" in TIMER
    assert "RandomizedDelaySec=30" in TIMER
    assert "Persistent=true" in TIMER
    assert "bw-monitor-inventory-cleanup.timer" in INSTALLER
    assert "inventory_cleanup.py" in INSTALLER


def test_push_has_transaction_retry_for_residual_deadlocks():
    final = APP[APP.index("# Last-resort protection for residual PostgreSQL deadlocks"):]
    assert 'app.view_functions["push"] = push_v5058r4_deadlock_retry' in final
    assert 'request.get_data(cache=True' in final
    assert 'BW_PUSH_DEADLOCK_RETRIES' in final
    assert '"40P01"' in APP


def test_consumption_uses_server_rollups_and_exact_edges():
    final = APP[APP.index("# 50.5.8-r4 fast Consumption + deadlock-safe inventory cleanup"):]
    assert "node_consumption_hourly" in final
    assert "node_consumption_daily" in final
    assert "FROM bandwidth_hourly" in final
    assert "FROM bandwidth_daily" in final
    assert "FROM node_stats ns" in final
    assert "FROM node_physical_net_stats" in final
    assert "def _v5058r4_ceil_hour" in final
    assert "COUNT(*) OVER()" in final
    assert "V5058R4_SUMMARY_CACHE_TTL = 60" in final
    assert "COUNT(DISTINCT last_push)::bigint sample_count" in APP
    assert "CASE WHEN bridge=? THEN host_tx" in final
    assert "CASE WHEN bridge=? THEN host_rx" in final


def test_agent_no_longer_sends_a_separate_two_hour_payload():
    assert "AGENT_VERSION = 15" in AGENT
    assert "/push/bandwidth-consumption" not in AGENT
    assert "account_bandwidth_consumption" not in AGENT
    assert "send_bandwidth_consumption_pending" not in AGENT
    assert 'data.pop("bandwidth_consumption", None)' in AGENT
    assert "post_json_payload(API, payload" in AGENT


def test_ui_contract_and_no_timezone_switch():
    final = APP[APP.index("# 50.5.8-r3 Consumption VM/Node view"):]
    for marker in (
        '"1h": ("1H", 3600)', '"2h": ("2H", 2 * 3600)',
        '"6h": ("6H", 6 * 3600)', '"12h": ("12H", 12 * 3600)',
        '"24h": ("24H", 24 * 3600)', '"2d": ("2D", 2 * 86400)',
        '"7d": ("7D", 7 * 86400)',
        "Search by VM name, UUID, MAC, Node or Node IP...",
        "Search by Node or Node IP...", "VM / UUID", "Node / Node IP",
        "PHYSICAL PUBLIC", "PHYSICAL PRIVATE", "Latest Sample",
    ):
        assert marker in final
    assert 'name="timezone"' not in final
    assert "VM Public IP" not in final


def test_additive_migration_and_cleanup_indexes_are_packaged():
    assert "CREATE TABLE IF NOT EXISTS node_consumption_hourly" in SQL
    assert "CREATE TABLE IF NOT EXISTS node_consumption_daily" in SQL
    assert "idx_vm_inventory_cleanup_stale" in SQL
    assert "idx_node_inventory_cleanup_delete" in SQL
    assert "010_consumption_inventory_cleanup.sql" in INSTALLER
