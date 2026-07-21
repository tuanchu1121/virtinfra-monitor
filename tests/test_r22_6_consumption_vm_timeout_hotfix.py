from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS = (ROOT / "app/runtime_layers/39_inventory_consumption_views.py").read_text()
CONSUMPTION = (ROOT / "app/runtime_layers/40_consumption_cleanup_r4.py").read_text()


def test_consumption_landing_defaults_to_compact_node_pipeline():
    start = VIEWS.index("def _v5058c_tab(value):")
    block = VIEWS[start: VIEWS.index("def _v5058c_limit", start)]
    assert 'value or "node"' in block
    assert 'else "node"' in block


def test_vm_raw_edges_constrain_timescale_partition_column():
    start = CONSUMPTION.index("def _v5058r4_vm_raw_branch")
    block = CONSUMPTION[start: CONSUMPTION.index("def _v5058r4_vm_hourly_branch", start)]
    assert "bucket_start = bucket_for(start)" in block
    assert "bucket_end = bucket_for(max(start, end - 1)) + CACHE_BUCKET_SECONDS" in block
    assert "ns.bucket>=? AND ns.bucket<?" in block
    assert "ns.last_push>=? AND ns.last_push<?" in block
    assert "params = [bucket_start, bucket_end, start, end]" in block


def test_vm_metric_formulas_are_unchanged():
    assert "COALESCE(SUM(ns.rx_delta),0)::bigint AS rx_bytes" in CONSUMPTION
    assert "COALESCE(SUM(ns.tx_delta),0)::bigint AS tx_bytes" in CONSUMPTION
    assert "COUNT(DISTINCT ns.bucket)::bigint AS sample_count" in CONSUMPTION
