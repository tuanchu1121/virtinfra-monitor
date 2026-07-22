from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
LAYER = ROOT / "app/runtime_layers/48_vm_consumption_shared_snapshot.py"
MIGRATION = ROOT / "postgres/sql/019_vm_consumption_shared_snapshot.sql"
PROVISION = ROOT / "deploy/postgres/provision-postgres-native.sh"


def test_web_vm_rows_reads_only_shared_snapshot():
    tree = ast.parse(LAYER.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_v5058c_vm_rows")
    text = ast.get_source_segment(LAYER.read_text(encoding="utf-8"), fn)
    assert "vm_consumption_snapshot_rows" in text
    assert "COUNT(*) OVER()" not in text
    assert "_v5058c_vm_ctes" not in text
    assert "vm_consumption_hourly" not in text
    assert "vm_consumption_daily" not in text
    assert "node_stats" not in text


def test_builder_aggregates_once_then_materializes_one_row_per_vm():
    text = LAYER.read_text(encoding="utf-8")
    assert "ctes, params = _v5058c_vm_ctes(window_start, window_end, \"\")" in text
    assert "INSERT INTO vm_consumption_snapshot_rows" in text
    assert "FROM vm_rows" in text
    assert "pg_try_advisory_xact_lock" in text


def test_request_count_and_rows_are_separate_snapshot_queries():
    text = LAYER.read_text(encoding="utf-8")
    assert 'SELECT COUNT(*) FROM vm_consumption_snapshot_rows s' in text
    assert "COUNT(*) OVER()" not in text
    assert "ORDER BY %s %s,s.vm_uuid %s LIMIT ? OFFSET ?" in text


def test_snapshot_cache_is_unlogged_and_does_not_change_canonical_rollups():
    text = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE UNLOGGED TABLE IF NOT EXISTS public.vm_consumption_snapshot_batches" in text
    assert "CREATE UNLOGGED TABLE IF NOT EXISTS public.vm_consumption_snapshot_rows" in text
    assert "ALTER TABLE public.vm_consumption_hourly" not in text
    assert "ALTER TABLE public.vm_consumption_daily" not in text


def test_timer_builds_outside_web_request_and_installer_warms_async():
    text = PROVISION.read_text(encoding="utf-8")
    layer = LAYER.read_text(encoding="utf-8")
    timer = (ROOT / "deploy/postgres/bw-monitor-vm-consumption-snapshot.timer").read_text(encoding="utf-8")
    assert "bw-monitor-vm-consumption-snapshot.timer" in text
    assert "systemctl --no-block start bw-monitor-vm-consumption-snapshot.service" in text
    assert '"$APP_DIR/venv/bin/python3" "$APP_DIR/vm_consumption_snapshot.py"' not in text
    assert "019_vm_consumption_shared_snapshot.sql" in text
    assert "R2212_SETTLE_SECONDS" in layer
    assert "*:02/5:00" in timer


def test_stale_snapshot_never_falls_back_to_legacy_vm_pipeline():
    text = LAYER.read_text(encoding="utf-8")
    assert "return [], 0, 1, 1" in text
    assert "_r2212_async_build(period_key, min(requested_end, _r2212_stable_end()))" in text
    assert "Do not revive the expensive request pipeline" in text


def test_full_backup_excludes_derived_snapshot_data_and_restore_rewarms():
    backup = (ROOT / "deploy/postgres/backup.sh").read_text(encoding="utf-8")
    restore = (ROOT / "deploy/postgres/restore.sh").read_text(encoding="utf-8")
    for text in (backup, restore):
        assert "--exclude-table-data=public.vm_consumption_snapshot_rows" in text
        assert "--exclude-table-data=public.vm_consumption_snapshot_batches" in text
    assert "systemctl stop bw-monitor-vm-consumption-snapshot.timer" in restore
    assert "systemctl --no-block start bw-monitor-vm-consumption-snapshot.service" in restore
