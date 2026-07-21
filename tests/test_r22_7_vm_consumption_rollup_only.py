from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS = (ROOT / "app/runtime_layers/39_inventory_consumption_views.py").read_text()
CONSUMPTION = (ROOT / "app/runtime_layers/40_consumption_cleanup_r4.py").read_text()


def function_block(name: str, next_name: str) -> str:
    start = CONSUMPTION.index(f"def {name}")
    return CONSUMPTION[start:CONSUMPTION.index(f"def {next_name}", start)]


def test_consumption_landing_defaults_to_compact_node_pipeline():
    start = VIEWS.index("def _v5058c_tab(value):")
    block = VIEWS[start: VIEWS.index("def _v5058c_limit", start)]
    assert 'value or "node"' in block
    assert 'else "node"' in block


def test_vm_source_is_rollup_only():
    block = function_block("_v5058c_vm_source_sql", "_v5058c_visible_vm_cte")
    assert "FROM vm_consumption_hourly" in CONSUMPTION
    assert "FROM vm_consumption_daily" in CONSUMPTION
    assert "_v5058r7_vm_daily_branch" in block
    assert "node_stats" in block  # explicit prohibition in the contract docstring
    assert "FROM node_stats" not in block
    assert "FROM usage" not in block
    assert "rx_delta" not in block
    assert "tx_delta" not in block


def test_vm_window_selects_a_fixed_number_of_hour_buckets():
    block = function_block("_v5058r7_vm_rollup_window", "_v5058r7_vm_hourly_branch")
    assert "requested_hours" in block
    assert "math.ceil((end - start) / 3600.0)" in block
    assert "aligned_end" in block
    assert "aligned_start" in block


def test_current_hour_is_read_from_hourly_rollup():
    block = function_block("_v5058c_vm_source_sql", "_v5058c_visible_vm_cte")
    assert "full_day_end < aligned_end" in block
    assert "_v5058r7_vm_hourly_branch" in block


def test_short_ranges_do_not_duplicate_the_hourly_branch():
    block = function_block("_v5058c_vm_source_sql", "_v5058c_visible_vm_cte")
    assert "if full_day_start < full_day_end:" in block
    assert "else:\n        sql, values = _v5058r7_vm_hourly_branch" in block


def test_vm_ui_discloses_r228_exact_hybrid_resolution():
    assert "VM ranges are exact to the retained five-minute samples" in VIEWS
    assert "complete days use daily rollups" in VIEWS
    assert "complete hours use hourly rollups" in VIEWS
    assert "two partial-hour edges read bounded raw VM/NIC buckets" in VIEWS


def test_vm_metric_direction_formulas_are_unchanged():
    assert "CASE WHEN bridge=? THEN host_tx" in CONSUMPTION
    assert "CASE WHEN bridge=? THEN host_rx" in CONSUMPTION
