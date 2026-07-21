from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYER = (ROOT / "app/runtime_layers/46_vm_consumption_exact_window.py").read_text()
VIEWS = (ROOT / "app/runtime_layers/39_inventory_consumption_views.py").read_text()


def block(name: str, next_name: str) -> str:
    start = LAYER.index(f"def {name}")
    return LAYER[start:LAYER.index(f"def {next_name}", start)]


def test_r228_is_a_final_layer_on_top_of_r227():
    manifest = (ROOT / "app/runtime_layers/manifest.json").read_text()
    assert '"46_vm_consumption_exact_window.py"' in manifest
    assert "R22.8 keeps the complete R22.7 runtime as its base" in LAYER


def test_vm_range_uses_daily_hourly_and_only_raw_edges():
    source = block("_v5058c_vm_source_sql", "_v5058c_visible_vm_cte")
    assert "_r228_vm_daily_branch" in source
    assert "_r228_vm_hourly_branch" in source
    assert "_r228_vm_raw_branch" in source
    assert "full_hour_start" in source
    assert "full_hour_end" in source
    assert "UNION ALL" in source


def test_raw_edge_has_chunk_pruning_and_exact_time_predicates():
    raw = block("_r228_vm_raw_branch", "_r228_vm_hourly_branch")
    assert "ns.bucket>=? AND ns.bucket<?" in raw
    assert "ns.last_push>=? AND ns.last_push<?" in raw
    assert "GROUP BY ns.node,ns.vm_uuid,ns.bridge" in raw


def test_group_and_node_scope_are_pushed_into_every_source_branch():
    scope = block("_r228_scope_sql", "_r228_ceil_hour")
    assert "node_group_memberships" in scope
    assert "r228_g.is_active=1" in scope
    assert 'if selected_node:' in scope
    assert 'params.append(selected_node)' in scope
    assert scope.index('params.append(selected_node)') < scope.index('if group_id:')
    for name, next_name in (
        ("_r228_vm_raw_branch", "_r228_vm_hourly_branch"),
        ("_r228_vm_hourly_branch", "_r228_vm_daily_branch"),
        ("_r228_vm_daily_branch", "_v5058c_vm_source_sql"),
    ):
        assert "_r228_scope_sql" in block(name, next_name)


def test_all_vm_migration_segments_are_merged_by_uuid():
    ctes = block("_v5058c_vm_ctes", "_r228_vm_rows_uncached")
    assert "FROM source_per_bridge" in ctes
    assert "GROUP BY vm_uuid,bridge" in ctes
    assert "LEFT JOIN vm_agg a ON a.vm_uuid=v.vm_uuid" in ctes
    assert "a.node=v.node" not in ctes


def test_coverage_uses_weakest_configured_bridge():
    ctes = block("_v5058c_vm_ctes", "_r228_vm_rows_uncached")
    assert "LEAST(public_samples,private_samples)" in ctes
    assert "WHEN public_configured=1 THEN public_samples" in ctes
    assert "WHEN private_configured=1 THEN private_samples" in ctes


def test_every_rendered_vm_metric_is_globally_sortable_before_limit():
    expected = {
        '"uuid": "vm_uuid"',
        '"node": "node"',
        '"public_rx": "public_rx"',
        '"public_tx": "public_tx"',
        '"public_total": "public_total"',
        '"private_rx": "private_rx"',
        '"private_tx": "private_tx"',
        '"private_total": "private_total"',
        '"coverage": "coverage_percent"',
        '"latest_sample": "latest_sample"',
    }
    for item in expected:
        assert item in VIEWS
    rows = block("_r228_vm_rows_uncached", "_v5058c_vm_rows")
    assert "FROM vm_rows" in rows
    assert "ORDER BY %s %s,node ASC,vm_uuid ASC LIMIT ? OFFSET ?" in rows
    assert rows.index("ORDER BY") < rows.index("LIMIT ? OFFSET ?")
    assert "COUNT(*) OVER()" in rows


def test_vm_alignment_and_exact_range_note_are_installed_last():
    assert 'id="r228-vm-consumption-alignment"' in LAYER
    assert "table-layout:fixed" in LAYER
    assert 'VM ranges are exact to the retained five-minute samples' in VIEWS


def test_agent_and_ingest_are_not_modified_by_the_new_layer():
    lowered = LAYER.lower()
    assert "insert into vm_consumption_hourly" not in lowered
    assert "insert into vm_consumption_daily" not in lowered
    assert "@app.route('/push'" not in lowered
    assert 'app.view_functions["push"]' not in lowered


def test_explicit_node_does_not_bypass_group_and_dropdown_is_group_scoped():
    scope = block("_r228_scope_sql", "_r228_ceil_hour")
    assert "return \" AND %s.node=?\"" not in scope
    visible = block("_v5058c_visible_nodes", "_v5058c_vm_ctes")
    assert "JOIN node_group_memberships" in visible
    assert "r228_g.is_active=1" in visible
    assert 'group_sql = " AND r228_g.id=?" if group_id else ""' in visible


def test_vm_query_cache_uses_r227_time_normalization():
    wrapper = block("_v5058c_vm_rows", "_v5058c_vm_table")
    assert "start, end = _r21_normalized_range(start, end)" in wrapper
