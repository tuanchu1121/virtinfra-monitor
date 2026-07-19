from __future__ import annotations

import importlib.util
from pathlib import Path
from runtime_source import read_app_source

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app" / "app.py"
PG_PATH = ROOT / "app" / "bw_pg.py"
APP = read_app_source()
PG = PG_PATH.read_text(encoding="utf-8")
INSTALLER = (ROOT / "deploy" / "postgres" / "install-postgres-native.sh").read_text(encoding="utf-8")
INDEX_PROFILE = (ROOT / "postgres" / "sql" / "005_ingest_write_profile.sql").read_text(encoding="utf-8")
V5052 = (ROOT / "app/runtime_layers/37_native_copy_ingest.py").read_text(encoding="utf-8")
INGEST_LAYER = (ROOT / "app/runtime_layers/10_ingest_push.py").read_text(encoding="utf-8")


def _v5052_block() -> str:
    return V5052


def _function_source(source: str, name: str) -> str:
    import ast
    tree = ast.parse(source)
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    return "\n".join(source.splitlines()[node.lineno - 1:node.end_lineno])


def test_release_and_native_copy_contract() -> None:
    assert (ROOT / "VERSION").read_text().strip() == "50.5.9-prod-r9-safe-runtime-history-prune"
    assert "def copy_rows(" in PG
    assert "cursor.copy(statement)" in PG
    assert "copy.write_row(values)" in PG
    assert "pg_sql.Identifier" in PG

    block = _v5052_block()
    assert "json.dumps" not in block
    assert "jsonb_to_recordset" not in block
    assert "jsonb_populate_recordset" not in block
    assert "pg_temp.vi5052_iface_stage" in block
    assert "pg_temp.vi5052_vm_stage" in block
    assert "pg_temp.vi5052_presence_stage" in block
    assert "MERGE INTO vm_latest_metrics AS dst" in block
    assert "process_node_vm_presence = _v5052_process_node_vm_presence" in block
    assert "_v5050_bulk_upsert_rows = _v5052_copy_upsert_rows" in block
    assert "_v4810_current_writer = _v5052_current_writer" in block
    assert "ingest_disk_io_current = _v5052_ingest_disk_io_current" in block


def test_push_uses_copy_stages_and_stage_timings() -> None:
    push = _function_source(INGEST_LAYER, "push")
    assert "_v5052_write_interface_copy_batch(" in push
    assert "_v5052_write_vm_copy_batch(" in push
    assert "_v5052_merge_latest_metrics(" in push
    assert "presence_copy_ms=" in push
    assert "iface_copy_ms=" in push
    assert "vm_copy_ms=" in push
    assert "disk_current_ms=" in push
    assert "current_abuse_ms=" in push
    assert "rows_presence=" in push

    # The high-cardinality interface and VM history loops are gone from /push.
    assert "add_bandwidth_rollup(" not in push
    assert "INSERT INTO node_stats(" not in push
    assert "INSERT INTO vm_perf_stats(" not in push


def test_rollups_keep_configured_local_timezone_boundaries() -> None:
    block = _v5052_block()
    assert "hour_start = local_hour_start(data_time)" in block
    assert "day_start = local_day_start(data_time)" in block
    assert "SELECT hour_start,node,vm_uuid,bridge" in block
    assert "SELECT day_start,node,vm_uuid,bridge" in block
    assert "(last_push/3600)*3600" not in block
    assert "(last_push/86400)*86400" not in block


def test_lean_write_index_profile_is_installed() -> None:
    assert "postgres/sql/005_ingest_write_profile.sql" in INSTALLER
    assert "Apply low-write ingest index profile" in INSTALLER
    for name in (
        "idx_v50_vm_current_total_pps",
        "idx_v50_vm_current_total_mbps",
        "idx_v50_vm_current_disk_read",
        "idx_v50_vm_current_disk_write",
        "idx_vm_current_fast_cpu_core",
        "idx_vm_current_fast_cpu_full",
        "idx_vm_latest_cpu",
        "idx_vm_latest_pps",
        "idx_vm_abuse_policy_cpu",
        "idx_vm_abuse_policy_disk_read",
        "idx_v48140_vmdisk_assigned",
        "idx_v48140_vmdisk_ratio",
    ):
        assert f"DROP INDEX CONCURRENTLY IF EXISTS {name};" in INDEX_PROFILE

    # Lookup/default-rank indexes are retained. Volatile disk metric-sort
    # indexes move to the 009 low-I/O profile and must not be recreated.
    for retained in (
        "idx_v50_abuse_current_rank",
        "idx_v50_vm_inventory_uuid_status",
    ):
        assert retained in APP or retained in (ROOT / "postgres" / "sql" / "003_native_indexes.sql").read_text()
        assert f"DROP INDEX CONCURRENTLY IF EXISTS {retained};" not in INDEX_PROFILE
    assert "idx_v48140_vmdisk_alloc" not in APP
    assert "idx_v48140_vmdisk_write_iops" not in APP


def test_copy_stage_row_widths_and_legacy_interval_semantics() -> None:
    import ast

    tree = ast.parse(APP)
    expected = {"_v5052_iface_rows": 40, "_v5052_vm_rows": 30}
    for function_name, width in expected.items():
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        )
        column_width = None
        row_widths = []
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "columns" for target in node.targets)
                and isinstance(node.value, ast.Tuple)
            ):
                column_width = len(node.value.elts)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "rows"
                and node.args
                and isinstance(node.args[0], ast.Tuple)
            ):
                row_widths.append(len(node.args[0].elts))
        assert column_width == width
        assert row_widths == [width]

    block = _v5052_block()
    assert "history_sec = max(1, min(3600, safe_int(interval_seconds" in block
    assert "current_sec = max(1, min(3600, safe_int(item.get(\"interval_seconds\")" in block
    assert "COALESCE(p.current_interval_seconds,n.interval_seconds" in block
    assert "COALESCE(p.current_disk_read_bps,0)" in block


def _load_bw_pg():
    spec = importlib.util.spec_from_file_location("test_bw_pg_v5052", PG_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeCopy:
    def __init__(self) -> None:
        self.rows: list[tuple[object, ...]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def write_row(self, row) -> None:
        self.rows.append(tuple(row))


class _FakeCursor:
    def __init__(self, owner) -> None:
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def copy(self, statement):
        self.owner.statement = statement
        self.owner.copy = _FakeCopy()
        return self.owner.copy


class _FakeRaw:
    def __init__(self) -> None:
        self.statement = None
        self.copy = None

    def cursor(self):
        return _FakeCursor(self)


def test_copy_rows_streams_rows_and_validates_width_and_identifiers() -> None:
    module = _load_bw_pg()
    raw = _FakeRaw()
    conn = module.CompatConnection(raw, None)
    count = conn.copy_rows(
        "pg_temp.vi5052_test_stage",
        ("vm_uuid", "value"),
        (("vm-1", 1), ("vm-2", 2)),
    )
    assert count == 2
    assert conn.total_changes == 2
    assert raw.copy.rows == [("vm-1", 1), ("vm-2", 2)]
    assert '"pg_temp"."vi5052_test_stage"' in raw.statement.as_string()

    with pytest.raises(ValueError, match="row width"):
        conn.copy_rows("pg_temp.vi5052_test_stage", ("a", "b"), ((1,),))
    with pytest.raises(ValueError, match="unsafe COPY table"):
        conn.copy_rows("pg_temp.bad;drop", ("a",), ((1,),))
