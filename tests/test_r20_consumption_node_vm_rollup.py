from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
CANONICAL_LAYER = APP / "runtime_layers/44_consumption_node_vm_rollup.py"
SHIM_LAYER = APP / "runtime_layers/45_consumption_ingest_preaggregation.py"
R20_LAYER = CANONICAL_LAYER
R21_LAYER = CANONICAL_LAYER
RELEASE = "50.5.9-prod-r22.6-consumption-vm-timeout-hotfix"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_r22_consumption_is_canonical_in_layer44_and_layer45_is_a_shim() -> None:
    assert text(ROOT / "VERSION").strip() == RELEASE
    manifest = json.loads(text(APP / "runtime_layers/manifest.json"))
    names = [item["file"] for item in manifest]
    assert CANONICAL_LAYER.name in names
    assert names[-1] == SHIM_LAYER.name
    assert names.index(CANONICAL_LAYER.name) < names.index(SHIM_LAYER.name)
    shim = text(SHIM_LAYER)
    assert "R22_CONSUMPTION_CANONICAL_LAYER = 44" in shim
    assert "def " not in shim


def test_r20_table_alignment_contract_remains_available() -> None:
    source = text(R20_LAYER) + text(R21_LAYER)
    for header in ("PHYSICAL PUBLIC", "ALL VM PUBLIC", "PHYSICAL PRIVATE", "ALL VM PRIVATE"):
        assert source.count(header) >= 2
    for header in ("PUBLIC DIFF", "PRIVATE DIFF", "COVERAGE", "LATEST"):
        assert header in source
    assert "v5060-node-table" in source
    assert "v5060-group-table" in source
    assert "table-layout:fixed!important" in source
    assert "font-variant-numeric:tabular-nums" in source


def test_r21_bypasses_r20_query_time_node_vm_aggregation() -> None:
    source = text(R21_LAYER)
    assert "_r21_iface_copy_base = _r20_iface_copy_base" in source
    assert "node_consumption_5m" in source
    assert "node_consumption_hourly" in source
    assert "node_consumption_daily" in source
    assert "R21_NODE_FORBIDDEN_RELATIONS" in source
    assert "node_vm_consumption_hourly" in source  # forbidden/legacy lifecycle marker only
    assert "node_consumption_forbidden_relation" in source


def test_dashboard_and_route_count_contract_stay_unchanged() -> None:
    source = text(R21_LAYER)
    assert 'app.view_functions["dashboard"]' not in source
    assert "dashboard_page" not in source
    assert "@app.route" not in source
    # Existing Flask endpoint is replaced in-place rather than adding routes.
    assert 'app.view_functions["admin_bandwidth_consumption_action"]' in source


def test_legacy_two_hour_ingest_remains_retired() -> None:
    source = text(R20_LAYER)
    assert "legacy_2h_accounting_retired" in source
    assert "Use normal 5-minute /push" in source


def test_r21_clear_all_and_recovery_cover_canonical_rollups() -> None:
    maintenance = text(APP / "maintenance_native.py")
    source = text(R21_LAYER)
    rollup = text(APP / "consumption_rollup.py")
    for table in (
        "node_consumption_5m", "node_consumption_hourly", "node_consumption_daily",
        "vm_consumption_hourly", "vm_consumption_daily",
    ):
        assert table in maintenance or table in source
        assert table in source or table in rollup
    assert "node_vm_consumption_hourly" not in rollup
    assert "node_vm_consumption_daily" not in rollup
    assert "dedicated_connection" in rollup
    assert "app.py" not in rollup


def test_installer_supports_r20_and_r21_additive_migrations() -> None:
    installer = text(ROOT / "deploy/postgres/provision-postgres-native.sh")
    bootstrap = text(ROOT / "install.sh")
    for migration in ("014_node_vm_consumption_rollups.sql", "015_consumption_ingest_preaggregation.sql"):
        assert migration in installer
        assert migration in bootstrap
