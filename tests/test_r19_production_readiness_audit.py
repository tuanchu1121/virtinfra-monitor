from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
VERSION = "50.5.9-prod-r20-consumption-node-vm-rollup-alignment-hotfix"


def test_release_identity() -> None:
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == VERSION
    installer = (ROOT / "deploy/postgres/provision-postgres-native.sh").read_text(encoding="utf-8")
    assert f'RELEASE="{VERSION}"' in installer


def test_clear_monitoring_covers_current_consumption_rollups() -> None:
    maintenance = (APP / "maintenance_native.py").read_text(encoding="utf-8")
    assert '"node_consumption_hourly"' in maintenance
    assert '"node_consumption_daily"' in maintenance
    tree = ast.parse(maintenance)
    monitoring = next(
        node for node in tree.body
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "MONITORING_TABLES"
    )
    values = {elt.value for elt in monitoring.value.elts if isinstance(elt, ast.Constant)}
    assert {"node_consumption_hourly", "node_consumption_daily", "node_vm_consumption_hourly", "node_vm_consumption_daily"} <= values


def test_consumption_maintenance_card_uses_current_rollups() -> None:
    route = (APP / "runtime_layers/44_consumption_node_vm_rollup.py").read_text(encoding="utf-8")
    action = (APP / "runtime_layers/34_bandwidth_consumption.py").read_text(encoding="utf-8")
    assert "Consumption Rollup Storage" in route
    assert "PHYSICAL HOURLY" in route and "VM NODE HOURLY" in route
    assert "MISSING RECENT ROLLUP" in route
    assert "2-hour Node Accounting Storage" not in route
    assert "Consumption has no separate clear button" in route
    assert "CLEAR CONSUMPTION HISTORY" not in route
    assert 'DELETE FROM node_consumption_hourly' in action
    assert 'DELETE FROM node_consumption_daily' in action
    assert 'DELETE FROM node_vm_consumption_hourly' in action
    assert 'DELETE FROM node_vm_consumption_daily' in action
    assert "Use Clear All Monitoring Data" in action


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
    backfill = installer.index('log "Backfill recent physical Consumption rollups"')
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
