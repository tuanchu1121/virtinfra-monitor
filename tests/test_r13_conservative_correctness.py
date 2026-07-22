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


def test_original_ui_mechanisms_are_preserved() -> None:
    shell = (APP / "runtime_layers/07_page_shell_auth_hook.py").read_text(encoding="utf-8")
    groups = (APP / "node_groups.py").read_text(encoding="utf-8")
    assert "const BW_AUTO_REFRESH_MS = 30000;" in shell
    assert "setInterval(refresh,30000)" in groups
    assert 'placeholder="Search group"' in groups
    assert 'placeholder="Search node"' in groups
    assert 'name="node_q"' in groups
    assert 'name="selection_scope"' in groups
    assert 'Selected nodes' in groups and 'All matching nodes' in groups
    assert "r11-consumption-group-alignment" not in groups
    assert "_admin_inventory_sort_link" not in groups
    assert "ram-warning" not in groups and "ram-critical" not in groups


def test_required_functional_hotfixes_remain_present() -> None:
    groups = (APP / "node_groups.py").read_text(encoding="utf-8")
    admin = (APP / "runtime_layers/09_admin_routes.py").read_text(encoding="utf-8")
    maintenance = (APP / "runtime_layers/38_agent_maintenance_canonical_routes.py").read_text(encoding="utf-8")
    assert "move_all_ungrouped" in groups
    assert "effective_visible_nodes" in groups
    assert "admin_change_password" in groups
    assert "current_dashboard_user" in groups
    assert 're.fullmatch(r"/node/([^/]+)", path)' in groups
    assert "previous_nodes" in admin and "previous_vms" in admin
    assert 'role != "super_admin"' in maintenance
    assert 'Forbidden: super_admin role required' in maintenance
    assert 'routine_actions = {' not in maintenance


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


def test_retention_keeps_five_minute_rows_for_two_days_then_one_hourly_row_until_day_seven() -> None:
    """Exercise the effective retention function in an isolated subprocess."""
    import os
    import subprocess
    import textwrap

    script = textwrap.dedent(
        r'''
        import importlib.util
        import os
        import sys
        import tempfile
        from pathlib import Path

        root = Path(os.environ["VIRTINFRA_ROOT"])
        helper_spec = importlib.util.spec_from_file_location(
            "retention_runtime_helper",
            root / "tools" / "node-groups-runtime-validation.py",
        )
        helper = importlib.util.module_from_spec(helper_spec)
        helper_spec.loader.exec_module(helper)

        now = 1_700_000_000
        with tempfile.TemporaryDirectory(prefix="virtinfra-retention-") as temp:
            database = Path(temp) / "retention-contract.db"
            os.environ.update({
                "BW_MONITOR_DB": str(database),
                "BW_ADMIN_USERNAME": "rootadmin",
                "BW_ADMIN_PASSWORD_HASH": "",
                "BW_ADMIN_SECRET_KEY": "retention-contract-secret",
                "BW_MONITOR_TOKEN": "retention-contract-token",
                "BW_START_BACKGROUND_THREADS": "0",
                "BW_MAINTENANCE_IMPORT": "1",
            })
            helper.install_sqlite_shim(database)
            sys.path.insert(0, str(root / "app"))
            spec = importlib.util.spec_from_file_location(
                "virtinfra_retention_contract",
                root / "app" / "app.py",
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.now_ts = lambda: now

            assert module.RAW_RETENTION_DAYS == 2
            assert module.HOURLY_RETENTION_DAYS == 7
            assert module.HISTORY_RETENTION_DAYS == 7

            # Two raw points inside day 2, three points in one hour on day 3,
            # two points in one hour on day 6, and one expired point on day 8.
            offsets = [
                (1, 0, 0),
                (1, 5, 0),
                (3, 0, 0),
                (3, 5, 1),
                (3, 10, 0),
                (6, 0, 0),
                (6, 5, 1),
                (8, 0, 0),
            ]
            buckets = []
            conn = module.db()
            try:
                for index, (days, minutes, inventory_complete) in enumerate(offsets):
                    bucket = module.bucket_for(now - days * 86400 - minutes * 60)
                    buckets.append(bucket)
                    conn.execute(
                        """
                        INSERT INTO node_push_snapshots(
                            node,bucket,push_time,last_push,vm_count,iface_count,
                            inventory_complete,retention_tier
                        ) VALUES (?,?,?,?,0,1,?,'raw')
                        """,
                        ("node-a", bucket, bucket, bucket, inventory_complete),
                    )
                    conn.execute(
                        """
                        INSERT INTO node_stats(
                            bucket,node,bridge,iface,vm_uuid,last_push
                        ) VALUES (?,?,?,?,?,?)
                        """,
                        (bucket, "node-a", "br0", f"vnet{index}", f"vm{index}", bucket),
                    )
                conn.commit()
            finally:
                conn.close()

            result = module.run_retention(dry_run=False)
            assert result["policy"] == {
                "raw_days": 2,
                "hourly_days": 7,
                "history_days": 7,
                "raw_resolution_seconds": 300,
                "hourly_resolution_seconds": 3600,
                "mode": "real_snapshot",
            }

            conn = module.db()
            try:
                retained = conn.execute(
                    "SELECT bucket,retention_tier FROM node_push_snapshots ORDER BY bucket"
                ).fetchall()
                retained_metrics = {
                    row[0] for row in conn.execute(
                        "SELECT bucket FROM node_stats ORDER BY bucket"
                    ).fetchall()
                }
            finally:
                conn.close()

            # Both five-minute points from day 1 remain raw.
            assert (buckets[0], "raw") in retained
            assert (buckets[1], "raw") in retained
            # Exactly one real point remains for each tested local hour on days 3 and 6.
            day3 = [row for row in retained if row[0] in set(buckets[2:5])]
            day6 = [row for row in retained if row[0] in set(buckets[5:7])]
            assert len(day3) == 1 and day3[0][1] == "hourly"
            assert len(day6) == 1 and day6[0][1] == "hourly"
            # The day-8 point is removed from both the snapshot index and metric table.
            assert all(row[0] != buckets[7] for row in retained)
            assert buckets[7] not in retained_metrics
            assert {row[0] for row in retained} == retained_metrics

            print("RETENTION_2D_RAW_7D_HOURLY_OK")
        '''
    )
    env = dict(os.environ)
    env["VIRTINFRA_ROOT"] = str(ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "RETENTION_2D_RAW_7D_HOURLY_OK" in proc.stdout
