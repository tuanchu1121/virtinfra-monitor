from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app" / "app.py").read_text(encoding="utf-8")


def test_release_marker():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "50.5.8-prod-r5-professional-ui-storage-hotfix"
    assert 'V5058R5_RELEASE = "50.5.8-prod-r5-professional-ui-storage-hotfix"' in APP


def test_storage_filtered_node_query_has_inventory_join():
    start = APP.index("def _v5058r5_storage_node_filtered_table")
    end = APP.index("# Update every saved filtered-view alias", start)
    block = APP[start:end]
    assert "LEFT JOIN node_inventory ni ON ni.node=s.node" in block
    assert "ni.node IS NULL" in block
    assert "_v48136_storage_node_filtered_base = _v5058r5_storage_node_filtered_table" in APP
    assert "_v48137_storage_node_filtered_base = _v5058r5_storage_node_filtered_table" in APP


def test_snapshot_tables_are_collapsed_by_default():
    assert '<details class="card snapshot-fold" id="real-snapshot-samples"' in APP
    assert '<details class="card snapshot-fold" id="retained-network-snapshots"' in APP
    assert 'opened = " open" if any(key in request.args' in APP


def test_charts_split_missing_time_ranges():
    assert "def _v5058r5_chart_segments" in APP
    assert "bucket - previous_bucket > gap_limit" in APP
    assert "def _v5058r5_segment_polylines" in APP
    assert 'item["valid_key"] = "guest_stats_available"' in APP
    assert 'title.strip().lower() == "vm ram"' in APP


def test_guestfs_is_ui_filtered_only():
    assert "def _v5058r5_is_transient_iface" in APP
    assert "Remove transient guestfs names from rendered output only" in APP


def test_professional_ui_contract():
    for marker in (
        "v5058r5-professional-ui",
        ".node-dashboard-table{width:100%;min-width:1600px",
        ".table-top-vm{width:100%;min-width:1760px",
        ".abuse-v48102-table,body.endpoint-vm-abuse-page .abuse-v490-table",
        ".v5058c-table{width:100%;min-width:1160px",
        "core-theme-mode-select",
    ):
        assert marker in APP
