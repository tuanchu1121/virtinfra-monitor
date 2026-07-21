from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from runtime_source import read_app_source
APP = read_app_source()
FEATURE_VERSION = "50.5.9-prod-r3-ui-alignment-overflow-hotfix"


def test_release_identity():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "50.5.9-prod-r22.8-consumption-sort-alignment-hotfix"
    assert f'V5059R2_RELEASE = "{FEATURE_VERSION}"' in APP
    assert 'style id="v5059r2-layout-polish-only"' in APP


def test_dashboard_overlap_is_fixed_by_presentation_css_only():
    assert 'body.endpoint-index .node-dashboard-table th:nth-child(2)' in APP
    assert 'width:148px!important;min-width:148px!important;max-width:148px!important' in APP
    assert 'body.endpoint-index .node-dashboard-table th:nth-child(3)' in APP
    assert 'white-space:normal!important;overflow:hidden;overflow-wrap:normal' in APP


def test_top_vm_compound_headers_are_compact_and_centered():
    assert 'body.endpoint-top-page .disk-cap-compact-head small' in APP
    assert 'flex-wrap:nowrap!important' in APP
    assert 'body.endpoint-top-page .cpu-dual-cell,body.endpoint-top-page .ram-cell,body.endpoint-top-page .disk-cap-cell{text-align:center!important}' in APP
    assert 'body.endpoint-top-page .table-top-vm col.top-rank{width:30px!important}' in APP


def test_consumption_tabs_have_explicit_identity_and_metric_widths():
    assert '.v5058c-toolbar:has(select[name="node"])' in APP
    assert '.v5058c-toolbar:not(:has(select[name="node"]))' in APP
    assert '.v5058c-vm-table tbody td:nth-child(1){width:220px!important' in APP
    assert '.v5058c-node-table tbody td:nth-child(1){width:200px!important' in APP
    assert '.v5058c-table td:nth-last-child(2) .status{font-size:13px!important' in APP


def test_node_health_first_column_has_operational_inset():
    assert 'body.endpoint-node-health-page .card>table th:nth-child(1)' in APP
    assert 'width:220px!important;padding-left:18px!important' in APP


def test_r2_is_css_only_beyond_release_metadata():
    start = APP.index("V5059R2_UI_CSS = r'''")
    end = APP.index("_page_v5058r5_base = page", start)
    block = APP[start:end]
    assert "<style" in block and "</style>" in block
    assert "<script" not in block
    assert "def " not in block
    assert "@app.route" not in block
