from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
VERSION = "50.5.9-prod-r22.9-consumption-sort-regression-hotfix"


def test_release_identity() -> None:
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == VERSION
    installer = (ROOT / "deploy/postgres/provision-postgres-native.sh").read_text(encoding="utf-8")
    assert f'RELEASE="{VERSION}"' in installer


def test_clear_monitoring_covers_current_consumption_rollups() -> None:
    maintenance = (APP / "maintenance_native.py").read_text(encoding="utf-8")
    layer = (APP / "runtime_layers/44_consumption_node_vm_rollup.py").read_text(encoding="utf-8")
    for table in ("node_consumption_5m", "node_consumption_hourly", "node_consumption_daily", "vm_consumption_hourly", "vm_consumption_daily"):
        assert table in maintenance or table in layer
    assert "Clear All Monitoring Data" in (APP / "runtime_layers/34_bandwidth_consumption.py").read_text(encoding="utf-8")


def test_consumption_maintenance_card_uses_current_rollups() -> None:
    layer = (APP / "runtime_layers/44_consumption_node_vm_rollup.py").read_text(encoding="utf-8")
    assert "Consumption Pre-aggregation Storage" in layer
    assert "NODE 5M" in layer and "NODE HOURLY" in layer and "NODE DAILY" in layer
    assert "VM HOURLY" in layer and "VM DAILY" in layer
    assert "planner estimates" in layer
    assert "Consumption has no separate clear action" in layer
    assert 'app.view_functions["admin_bandwidth_consumption_action"]' in layer


def test_custom_theme_controller_is_pjax_safe() -> None:
    theme = (APP / "runtime_layers/42_ui_alignment_r3.py").read_text(encoding="utf-8")
    assert "window.virtinfraApplySelectedTheme=applyStored" in theme
    assert 'target.id==="unified-theme-select"' in theme
    assert "var coreApply=" in theme
    assert "window.applyTheme=function(mode,persist)" in theme


def test_rollup_tool_does_not_import_flask_application() -> None:
    rollup = (APP / "consumption_rollup.py").read_text(encoding="utf-8")
    assert "importlib.util" not in rollup
    assert "app.py" not in rollup
    assert "dedicated_connection" in rollup
    assert "advisory_xact_lock" in rollup


def test_updater_quiesces_runtime_before_schema_and_backfill() -> None:
    installer = (ROOT / "deploy/postgres/provision-postgres-native.sh").read_text(encoding="utf-8")
    quiesce = installer.index('log "Quiesce web, maintenance and cleanup services for schema update"')
    install_code = installer.index('log "Install full application code"')
    backfill = installer.index('log "Backfill recent Consumption pre-aggregates"')
    assert quiesce < install_code < backfill
    assert "Active maintenance job services detected" in installer
    assert "resume_update_services" in installer


def test_agent_tokens_have_no_weak_defaults() -> None:
    bootstrap = (APP / "runtime_layers/00_bootstrap_database.py").read_text(encoding="utf-8")
    agent = (ROOT / "deploy/agent/agent.py").read_text(encoding="utf-8")
    assert 'os.environ.get("BW_MONITOR_TOKEN", "123456")' not in bootstrap
    assert 'TOKEN = str(os.environ.get("BW_MONITOR_TOKEN") or "").strip()' in bootstrap
    assert '103.199.19.207' not in agent
    assert 'BW_AGENT_TOKEN", "123456"' not in agent
    assert 'VIRTINFRA_AGENT_TOKEN/BW_AGENT_TOKEN is required' in agent
