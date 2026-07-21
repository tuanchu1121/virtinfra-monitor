import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYER = ROOT / "app/runtime_layers/46_consumption_sort_alignment_hotfix.py"


def source() -> str:
    return LAYER.read_text(encoding="utf-8")


def test_node_sort_allowlist_covers_every_rendered_r22_column() -> None:
    text = source()
    for key in (
        "vm_count", "vm_public_rx", "vm_public_tx", "vm_public_total",
        "public_difference", "vm_private_rx", "vm_private_tx",
        "vm_private_total", "private_difference",
    ):
        assert f'"{key}"' in text


def test_common_vm_sort_path_drops_window_count_and_scopes_early() -> None:
    text = source()
    optimized = text[text.index("def _v5058c_vm_rows("):text.index("# Deterministic Node sorting")]
    assert "COUNT(*) OVER()" not in optimized
    assert "_v5080_visible_vm_count" in optimized
    assert "_v5080_group_scope_sql" in optimized
    assert "ORDER BY %s %s,%s %s" in optimized
    assert "scoped_location AS" in text
    assert "JOIN scoped_location sl" in text


def test_text_sort_first_click_is_ascending_and_group_sort_exists() -> None:
    text = source()
    assert 'next_order = "asc" if key in V5080_TEXT_SORTS else "desc"' in text
    assert 'V5080_GROUP_SORTS' in text
    assert 'h("VMS", "vms")' in text
    assert 'h("PUBLIC DIFF", "public_difference")' in text
    assert 'h("PRIVATE DIFF", "private_difference")' in text


def test_consumption_alignment_targets_vm_node_and_group_only() -> None:
    text = source()
    assert ".v5058c-vm-table col.c-vm" in text
    assert ".v5060-node-table tbody td:nth-child(2)" in text
    assert ".v5060-node-table tbody td:nth-child(9)" in text
    assert ".v5060-node-table tbody td:nth-child(16)" in text
    assert ".v5060-group-table tbody td:nth-child(3)" in text
    assert ".v5060-group-table tbody td:nth-child(10)" in text
    assert ".v5060-group-table tbody td:nth-child(17)" in text
    assert "No ingest, schema, formula, endpoint, payload, retention" in text


def test_node_sort_helper_uses_vm_count_and_signed_differences() -> None:
    tree = ast.parse(source())
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "_v5080_node_sort_value")
    namespace: dict[str, object] = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(LAYER), "exec"), namespace)
    helper = namespace["_v5080_node_sort_value"]
    item = {
        "node":"node-a", "vm_count":17,
        "physical_public_rx":1000, "physical_public_tx":500,
        "vm_public_rx":400, "vm_public_tx":300,
        "physical_private_rx":600, "physical_private_tx":400,
        "vm_private_rx":900, "vm_private_tx":300,
        "coverage_percent":88.5, "latest_sample":123,
    }
    assert helper(item, "vm_count") == 17
    assert helper(item, "public_difference") == 800
    assert helper(item, "private_difference") == -200
