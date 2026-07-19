from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app" / "app.py").read_text(encoding="utf-8")
VERSION = "50.5.9-prod-r3-ui-alignment-overflow-hotfix"


def effective_block():
    return APP[APP.index("# v50.5.9 r3 UI alignment and overflow hotfix"):]


def test_release_identity_and_scope_marker():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == VERSION
    assert f'V5059R3_RELEASE = "{VERSION}"' in APP
    assert 'style id="v5059r3-ui-alignment-overflow-hotfix"' in APP


def test_effective_theme_control_is_one_select_with_all_choices():
    block = effective_block()
    selector_start = block.index("def _v5049_theme_selector_html")
    selector_end = block.index("def _v5049_runtime_theme_script", selector_start)
    selector = block[selector_start:selector_end]
    assert 'id="unified-theme-select"' in selector
    assert 'value="mode:auto"' in selector
    assert 'value="mode:light"' in selector
    assert 'value="mode:dark"' in selector
    assert 'value="theme:%s"' in selector
    assert '<span>Style</span>' not in selector
    assert 'simple-theme-select' not in selector


def test_consumption_uses_fixed_colgroups_and_compact_toolbar():
    block = effective_block()
    assert 'v5059r3-cons-vm' in block
    assert 'v5059r3-cons-node-only' in block
    assert 'table-layout:fixed!important' in block
    assert 'grid-template-columns:minmax(320px,520px)' in block
    assert 'grid-template-columns:minmax(300px,460px)' in block
    assert 'thead tr:nth-child(2)>th .sort-link' in block


def test_top_vm_resource_tracks_are_identical_and_node_uuid_are_restored():
    block = effective_block()
    assert 'col.top-node{width:135px!important}' in block
    assert 'col.top-uuid{width:290px!important}' in block
    assert 'width:136px!important;min-width:136px!important;max-width:136px!important' in block
    assert '.cpu-dual-cell .cpu-meter,' in block
    assert '.vm-ram-compact .ram-meter,' in block
    assert '.top-disk-capacity .disk-cap-meter{' in block


def test_dashboard_and_node_health_are_aligned_and_contained():
    block = effective_block()
    assert '.node-dashboard-table th:nth-child(n+4)' in block
    assert '.dashboard-interface-wrap{' in block
    assert 'padding-right:14px!important;text-align:center!important' in block
    assert 'node-health-table-wrap' in block
    assert '<table class="node-health-table">' in block


def test_tables_scroll_inside_cards_not_the_page():
    block = effective_block()
    assert 'html,body{max-width:100%;overflow-x:hidden!important}' in block
    assert 'overflow-x:auto!important;overflow-y:hidden!important' in block
    assert 'clip-path:inset(0 round 9px)' in block


def test_r3_does_not_register_routes_or_touch_database_code():
    block = effective_block()
    assert '@app.route' not in block
    assert 'CREATE TABLE' not in block
    assert 'SELECT ' not in block
    assert 'INSERT INTO' not in block
    assert 'UPDATE ' not in block
    assert 'DELETE FROM' not in block
