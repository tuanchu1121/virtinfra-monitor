from __future__ import annotations

import ast
from pathlib import Path

from runtime_source import read_app_source

ROOT = Path(__file__).resolve().parents[1]
SOURCE = read_app_source()
TREE = ast.parse(SOURCE)


def last_function(name: str) -> str:
    matches = [node for node in TREE.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    assert matches, name
    return ast.get_source_segment(SOURCE, matches[-1]) or ""


def test_every_successful_purge_redirects_to_visible_queue() -> None:
    for name in (
        "admin_delete_vm",
        "admin_delete_node",
        "admin_purge_node_vms",
        "admin_bulk_nodes",
        "admin_bulk_vms",
    ):
        body = last_function(name)
        assert 'section="maintenance"' in body, name
        assert '#maintenance-queue' in body, name


def test_purge_enqueue_failure_is_visible_in_maintenance() -> None:
    for name in (
        "admin_delete_vm",
        "admin_delete_node",
        "admin_purge_node_vms",
        "admin_bulk_nodes",
        "admin_bulk_vms",
    ):
        body = last_function(name)
        assert "dberr=err" in body, name
        assert 'section="maintenance"' in body, name


def test_non_purge_hide_restore_flow_stays_on_inventory_pages() -> None:
    assert 'return redirect(url_for("admin_page", section="vms"))' in last_function("admin_delete_vm")
    assert 'return redirect(url_for("admin_page", section="nodes"))' in last_function("admin_delete_node")
    assert 'return redirect(url_for("admin_page", section="nodes"))' in last_function("admin_bulk_nodes")
    assert 'return redirect(url_for("admin_page", section="vms"))' in last_function("admin_bulk_vms")


def test_queue_renderer_shows_all_purge_actions_and_worker_states() -> None:
    for state in ("queued", "starting", "running", "ok", "error", "cancelled"):
        assert f'"{state}"' in SOURCE or f"'{state}'" in SOURCE
    for action in ("purge_nodes", "purge_node_vms", "purge_vms"):
        assert action in SOURCE
    assert "Recent maintenance jobs" in SOURCE
    assert "get_maintenance_jobs(30)" in SOURCE


def test_installer_installs_dispatcher_worker_and_watchdog() -> None:
    installer = (ROOT / "deploy/postgres/provision-postgres-native.sh").read_text(encoding="utf-8")
    for unit in (
        "bw-monitor-maintenance@.service",
        "bw-monitor-maintenance-dispatch.service",
        "bw-monitor-maintenance-watchdog.timer",
    ):
        assert unit in installer
    assert "systemctl enable --now bw-monitor-maintenance-watchdog.timer" in installer
