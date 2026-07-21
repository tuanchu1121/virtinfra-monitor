from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
INGEST = ROOT / "app/runtime_layers/10_ingest_push.py"
NATIVE = ROOT / "app/runtime_layers/37_native_copy_ingest.py"
ROLLING = ROOT / "app/runtime_layers/47_vm_5m_slot_rolling_window.py"
MIGRATION = ROOT / "postgres/sql/018_vm_consumption_slot_boundary_semantics.sql"


def _slot_coordinates():
    tree = ast.parse(INGEST.read_text(encoding="utf-8"))
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_r2211_slot_coordinates")
    module = ast.Module(body=[fn], type_ignores=[])
    ns = {
        "bucket_for": lambda ts: (int(ts) // 300) * 300,
        "CACHE_BUCKET_SECONDS": 300,
        "local_hour_start": lambda ts: (int(ts) // 3600) * 3600,
        "local_day_start": lambda ts: (int(ts) // 86400) * 86400,
    }
    exec(compile(module, str(INGEST), "exec"), ns, ns)
    return ns["_r2211_slot_coordinates"]


def test_push_timestamp_is_interval_end_not_interval_start():
    slot = _slot_coordinates()
    slot_start, hour_start, day_start, slot_no = slot(19 * 3600 + 30 * 60)
    assert slot_start == 19 * 3600 + 25 * 60
    assert hour_start == 19 * 3600
    assert day_start == 0
    assert slot_no == 5


def test_exact_hour_boundary_belongs_to_previous_hour_last_slot():
    slot = _slot_coordinates()
    slot_start, hour_start, _, slot_no = slot(20 * 3600)
    assert slot_start == 19 * 3600 + 55 * 60
    assert hour_start == 19 * 3600
    assert slot_no == 11


def test_midnight_boundary_belongs_to_previous_day():
    slot = _slot_coordinates()
    slot_start, hour_start, day_start, slot_no = slot(86400)
    assert slot_start == 86400 - 300
    assert hour_start == 86400 - 3600
    assert day_start == 0
    assert slot_no == 11


def test_both_ingest_paths_use_same_slot_coordinates():
    legacy = INGEST.read_text(encoding="utf-8")
    native = NATIVE.read_text(encoding="utf-8")
    assert "_r2211_slot_coordinates(data_time)" in legacy
    assert "_r2211_slot_coordinates(data_time)" in native
    assert "MAX(bucket)-300-hour_start" in native
    assert "MAX(bucket)-hour_start" not in native


def test_v2_rows_reset_bad_r2210_arrays_lazily_without_table_rewrite():
    legacy = INGEST.read_text(encoding="utf-8")
    native = NATIVE.read_text(encoding="utf-8")
    migration = MIGRATION.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS slot_5m_version SMALLINT NOT NULL DEFAULT 1" in migration
    assert "UPDATE vm_consumption_hourly" not in migration
    for text in (legacy, native):
        assert "slot_5m_version" in text
        assert "COALESCE(vm_consumption_hourly.slot_5m_version,1)<2" in text
        assert "slot_5m_version=2" in text


def test_rolling_reader_ignores_legacy_shifted_masks_and_uses_slot_end_time():
    text = ROLLING.read_text(encoding="utf-8")
    assert "COALESCE(slot_5m_version,1)>=2" in text
    assert "hour_start + (index + 1) * R2210_SLOT_SECONDS" in text
    assert "hour_start + index * R2210_SLOT_SECONDS" not in text


def test_coverage_uses_received_sample_count_during_lazy_warmup():
    text = ROLLING.read_text(encoding="utf-8")
    assert "GREATEST(\n               CASE WHEN COALESCE(slot_5m_version,1)>=2" in text
    assert "LEAST(12,COALESCE(sample_count,0))::bigint" in text
    assert "GREATEST(%d-selected_known,0)/GREATEST(12-packed_known,1)" in text  # bytes only
    assert "GREATEST(LEAST(12,COALESCE(sample_count,0))-packed_known,0)" in text


def test_installer_applies_migration_018():
    assert "postgres/sql/018_vm_consumption_slot_boundary_semantics.sql" in (ROOT / "install.sh").read_text()
    provision = (ROOT / "deploy/postgres/provision-postgres-native.sh").read_text()
    assert provision.count("018_vm_consumption_slot_boundary_semantics.sql") >= 2
