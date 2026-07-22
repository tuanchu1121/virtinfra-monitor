from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYER = ROOT / "app/runtime_layers/46_consumption_sort_alignment_hotfix.py"


def source() -> str:
    return LAYER.read_text(encoding="utf-8")


def test_r22_9_keeps_vm_query_pipeline_untouched():
    text = source()
    forbidden = (
        "def _v5058c_vm_rows(",
        "def _v5058c_vm_source_sql(",
        "def _v5058c_visible_vm_cte(",
        "def _v5090_visible_vm_count(",
        "COUNT(*) OVER()",
        "vm-visible-count",
        "vm-page-r228",
    )
    for value in forbidden:
        assert value not in text
    assert "VM query functions intentionally remain untouched" in text


def test_r22_9_authorizes_every_node_sort_key_rendered_by_table():
    text = source()
    for key in (
        "vm_count", "vm_public_rx", "vm_public_tx", "vm_public_total",
        "public_difference", "vm_private_rx", "vm_private_tx",
        "vm_private_total", "private_difference",
    ):
        assert f'"{key}"' in text


def test_r22_9_group_sort_uses_compact_node_dataset_only():
    text = source()
    assert "for item in _r21_node_dataset(start, end)" in text
    assert "_v5058c_vm_ctes" not in text
    assert "node_stats" not in text
    assert "vm_consumption_hourly" not in text
    assert "vm_consumption_daily" not in text


def test_r22_9_alignment_is_consumption_scoped():
    text = source()
    assert "body.endpoint-bandwidth-consumption-page" in text
    assert "v5058c-vm-table" in text
    assert "v5060-node-table" in text
    assert "v5060-group-table" in text
