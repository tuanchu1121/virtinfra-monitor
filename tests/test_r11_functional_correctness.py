from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def _import_maintenance_queue():
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    import maintenance_queue
    return maintenance_queue


def test_refresh_intervals_and_current_ui_order_are_pinned() -> None:
    shell = (APP / "runtime_layers/07_page_shell_auth_hook.py").read_text(encoding="utf-8")
    groups = (APP / "node_groups.py").read_text(encoding="utf-8")
    assert "const BW_AUTO_REFRESH_MS = 30000;" in shell
    assert "setInterval(refresh,15000)" in groups
    assert 'placeholder="Search group, node or IP"' in groups
    assert 'name="node_q"' not in groups
    assert "<button type=\"submit\">Apply</button><a class=\"clear\"" in groups


def test_maintenance_watchdog_and_starting_state_are_installed() -> None:
    queue = (APP / "maintenance_queue.py").read_text(encoding="utf-8")
    retention = (APP / "retention.py").read_text(encoding="utf-8")
    provision = (ROOT / "deploy/postgres/provision-postgres-native.sh").read_text(encoding="utf-8")
    assert 'ACTIVE_STATES = {"starting", "running"}' in queue
    assert "status IN ('queued','starting','running')" in queue
    assert "status IN ('queued','starting','running')" in retention
    assert "systemctl enable --now bw-monitor-maintenance-watchdog.timer" in provision
    assert "systemctl --no-block start bw-monitor-maintenance-dispatch.service" in provision


def test_wake_dispatcher_surfaces_systemctl_failure(monkeypatch) -> None:
    maintenance_queue = _import_maintenance_queue()

    monkeypatch.setattr(
        maintenance_queue.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=5, stdout="unit failed"),
    )
    ok, detail = maintenance_queue.wake_dispatcher()
    assert ok is False
    assert detail == "unit failed"


def test_wake_dispatcher_surfaces_execution_exception(monkeypatch) -> None:
    maintenance_queue = _import_maintenance_queue()

    def fail(*_args, **_kwargs):
        raise OSError("systemctl unavailable")

    monkeypatch.setattr(maintenance_queue.subprocess, "run", fail)
    ok, detail = maintenance_queue.wake_dispatcher()
    assert ok is False
    assert "OSError" in detail and "systemctl unavailable" in detail
