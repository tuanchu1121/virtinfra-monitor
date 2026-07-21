from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "postgres/sql/017_vm_consumption_5m_slots.sql"
INGEST = ROOT / "app/runtime_layers/37_native_copy_ingest.py"
ROLLING = ROOT / "app/runtime_layers/47_vm_5m_slot_rolling_window.py"
VIEWS = ROOT / "app/runtime_layers/39_inventory_consumption_views.py"


def _runtime_namespace():
    source = ROLLING.read_text(encoding="utf-8")
    ns = {
        "safe_int": lambda value, default=0: int(default if value is None else value),
        "CACHE_BUCKET_SECONDS": 300,
        "local_hour_start": lambda ts: (int(ts) // 3600) * 3600,
        "local_day_start": lambda ts: (int(ts) // 86400) * 86400,
        "_v5058r7_vm_daily_branch": lambda start, end, node="": (
            "SELECT node,vm_uuid,bridge,rx_bytes,tx_bytes,sample_count,last_push FROM vm_consumption_daily WHERE day_start>=? AND day_start<?",
            [start, end],
        ),
        "_v48140_cache_get": lambda key: None,
        "_v48140_cache_set": lambda *args: None,
        "json": json,
        "V5058R4_SUMMARY_CACHE_TTL": 10,
    }
    exec(compile(source, str(ROLLING), "exec"), ns, ns)
    return ns


def test_schema_adds_packed_slots_without_a_new_5m_table():
    text = MIGRATION.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS rx_5m_slots BIGINT[]" in text
    assert "ADD COLUMN IF NOT EXISTS tx_5m_slots BIGINT[]" in text
    assert "ADD COLUMN IF NOT EXISTS sample_5m_mask INTEGER" in text
    assert "CREATE TABLE" not in text
    assert "CREATE TABLE IF NOT EXISTS vm_consumption_5m" not in text


def test_native_copy_updates_slots_inside_existing_hourly_upsert():
    text = INGEST.read_text(encoding="utf-8")
    assert "rx_5m_slots,tx_5m_slots,sample_5m_mask" in text
    assert "sample_5m_mask=COALESCE(vm_consumption_hourly.sample_5m_mask,0)|excluded.sample_5m_mask" in text
    assert "LEAST(11,GREATEST(0,((MAX(bucket)-hour_start)/300)::integer))" in text
    assert "UPDATE vm_consumption_hourly" not in text


def test_rolling_window_is_exact_duration_and_ends_on_closed_5m_bucket():
    ns = _runtime_namespace()
    end = 19 * 3600 + 32 * 60
    for hours in (1, 2, 6, 12, 24, 48, 168):
        start, normalized_end = ns["_v5058r7_vm_rollup_window"](end - hours * 3600, end)
        assert normalized_end == 19 * 3600 + 30 * 60
        assert normalized_end - start == hours * 3600
        assert start % 300 == 0
        assert normalized_end % 300 == 0


def test_one_hour_uses_two_bounded_slot_edges_and_no_raw_history():
    ns = _runtime_namespace()
    end = 19 * 3600 + 32 * 60
    sql, params = ns["_v5058c_vm_source_sql"](end - 3600, end)
    assert sql.count("WHERE hour_start=?") == 2
    assert "node_stats" not in sql
    assert "usage" not in sql
    assert "rx_delta" not in sql
    assert "rx_5m_slots" in sql
    assert "UNION ALL WITH" not in sql
    assert sql.count("FROM (\n          SELECT *") == 2
    assert params == [18 * 3600, 19 * 3600]


def test_node_scope_is_pushed_into_each_slot_edge_with_stable_parameters():
    ns = _runtime_namespace()
    end = 19 * 3600 + 32 * 60
    sql, params = ns["_v5058c_vm_source_sql"](end - 3600, end, "NODE-A")
    assert sql.count("WHERE hour_start=? AND node=?") == 2
    assert params == [18 * 3600, "NODE-A", 19 * 3600, "NODE-A"]


def test_two_hours_use_edges_plus_one_complete_hour():
    ns = _runtime_namespace()
    end = 19 * 3600 + 32 * 60
    sql, _ = ns["_v5058c_vm_source_sql"](end - 2 * 3600, end)
    assert sql.count("WHERE hour_start=?") == 2
    assert sql.count("hour_start>=? AND hour_start<?") == 1
    assert "node_stats" not in sql


def test_long_window_can_use_daily_totals_between_slot_edges():
    ns = _runtime_namespace()
    end = 7 * 86400 + 19 * 3600 + 32 * 60
    sql, _ = ns["_v5058c_vm_source_sql"](end - 7 * 86400, end)
    assert "vm_consumption_daily" in sql
    assert sql.count("WHERE hour_start=?") == 2
    assert "node_stats" not in sql


def test_legacy_edge_fallback_preserves_unpacked_residual_during_warmup():
    text = ROLLING.read_text(encoding="utf-8")
    assert "COALESCE(rx_bytes,0)-packed_rx" in text
    assert "COALESCE(tx_bytes,0)-packed_tx" in text
    assert "GREATEST(%d-selected_known,0)/GREATEST(12-packed_known,1)" in text
    assert "LEAST(12,COALESCE(sample_count,0))-packed_known" in text
    assert "warm-up monotonic" in text


def test_ui_discloses_rolling_slots_and_no_raw_scan():
    text = VIEWS.read_text(encoding="utf-8")
    assert "rolling five-minute slots packed inside hourly rollups" in text
    assert "no raw VM/NIC history is scanned" in text


def test_installer_and_provision_apply_migration_017():
    assert "postgres/sql/017_vm_consumption_5m_slots.sql" in (ROOT / "install.sh").read_text()
    provision = (ROOT / "deploy/postgres/provision-postgres-native.sh").read_text()
    assert provision.count("017_vm_consumption_5m_slots.sql") >= 2
