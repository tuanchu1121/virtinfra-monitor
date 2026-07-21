from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
LAYER = APP / "runtime_layers/44_consumption_node_vm_rollup.py"
MIGRATION = ROOT / "postgres/sql/015_consumption_ingest_preaggregation.sql"
RELEASE = "50.5.9-prod-r22.6-consumption-vm-timeout-hotfix"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def function_source(path: Path, name: str) -> str:
    source = read(path)
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name)
    return ast.get_source_segment(source, node) or ""


def test_release_manifest_and_install_contract() -> None:
    assert read(ROOT / "VERSION").strip() == RELEASE
    manifest = json.loads(read(APP / "runtime_layers/manifest.json"))
    assert manifest[-2]["file"] == LAYER.name
    assert manifest[-1]["file"] == "45_consumption_ingest_preaggregation.py"
    assert "def " not in read(APP / "runtime_layers/45_consumption_ingest_preaggregation.py")
    for path in (ROOT / "install.sh", ROOT / "preflight.sh", ROOT / "deploy/postgres/provision-postgres-native.sh"):
        value = read(path)
        assert "015_consumption_ingest_preaggregation.sql" in value
        assert RELEASE in value or path.name == "install.sh"


def test_migration_establishes_canonical_vm_and_node_rollups() -> None:
    sql = read(MIGRATION)
    assert "ALTER TABLE public.bandwidth_hourly RENAME TO vm_consumption_hourly" in sql
    assert "ALTER TABLE public.bandwidth_daily RENAME TO vm_consumption_daily" in sql
    for table in (
        "vm_consumption_hourly", "vm_consumption_daily",
        "node_consumption_hourly", "node_consumption_daily", "node_consumption_5m",
    ):
        assert table in sql
    assert "PRIMARY KEY (bucket_start,node)" in sql
    assert "idx_node_consumption_5m_node_time" in sql
    assert "create_hypertable('node_consumption_5m'" in sql


def test_bootstrap_creates_canonical_vm_tables_without_aborting_postgres_transactions() -> None:
    source = read(APP / "runtime_layers/00_bootstrap_database.py")
    assert "CREATE TABLE IF NOT EXISTS vm_consumption_hourly" in source
    assert "CREATE TABLE IF NOT EXISTS vm_consumption_daily" in source
    assert "if not DATABASE_URL:" not in source[source.index("CREATE TABLE IF NOT EXISTS bandwidth_daily"):source.index("CREATE TABLE IF NOT EXISTS retention_runs")]
    index_block = source[source.index("idx_vm_consumption_hourly_vm_time"):source.index("idx_maintenance_jobs_created")]
    assert "except Exception" not in index_block
    assert "idx_vm_consumption_daily_node_time" in index_block


def test_vm_pipeline_uses_incremental_ingest_upserts() -> None:
    source = read(APP / "runtime_layers/37_native_copy_ingest.py")
    for table, key in (
        ("vm_consumption_hourly", "hour_start,node,vm_uuid,bridge"),
        ("vm_consumption_daily", "day_start,node,vm_uuid,bridge"),
    ):
        assert f"INSERT INTO {table}" in source
        assert f"ON CONFLICT({key}) DO UPDATE" in source
        assert f"rx_bytes={table}.rx_bytes+excluded.rx_bytes" in source
        assert f"tx_bytes={table}.tx_bytes+excluded.tx_bytes" in source


def test_node_pipeline_is_incremental_in_same_accepted_push_transaction() -> None:
    source = read(LAYER)
    assert "_r21_iface_copy_base = _r20_iface_copy_base" in source
    assert "FROM pg_temp.vi5052_iface_stage GROUP BY bucket,node" in source
    assert "INSERT INTO node_consumption_5m" in source
    assert "ON CONFLICT(bucket_start,node) DO UPDATE" in source
    assert '("node_consumption_hourly", "hour_start", 3600)' in source
    assert '("node_consumption_daily", "day_start", 86400)' in source
    assert "INSERT INTO {table}" in source
    assert "ON CONFLICT({time_column},node) DO UPDATE" in source
    assert "vm_public_rx_bytes=node_consumption_5m.vm_public_rx_bytes+excluded.vm_public_rx_bytes" in source
    assert "physical_public_rx_bytes={table}.physical_public_rx_bytes+excluded.physical_public_rx_bytes" in source


def test_node_render_sql_has_strict_node_only_boundary() -> None:
    functions = "\n".join(function_source(LAYER, name) for name in (
        "_r21_node_raw_branch", "_r21_node_hourly_branch", "_r21_node_daily_branch",
        "_r21_node_source_sql", "_r21_node_dataset_sql",
    )).lower()
    for relation in ("node_consumption_5m", "node_consumption_hourly", "node_consumption_daily"):
        assert relation in functions
    for forbidden in (
        "node_stats", "vm_consumption_hourly", "vm_consumption_daily",
        "node_vm_consumption_hourly", "node_vm_consumption_daily",
    ):
        assert forbidden not in functions
    assert "group by vm_uuid" not in functions
    assert "vm_uuid" not in function_source(LAYER, "_r21_node_dataset_sql").lower()
    guard = function_source(LAYER, "_r21_node_dataset_uncached").lower()
    assert "node_consumption_forbidden_relation" in guard
    assert "node_consumption_forbidden_grouping:vm_uuid" in guard


def test_hybrid_24h_path_uses_retained_raw_edges_and_hourly_middle() -> None:
    source = function_source(LAYER, "_r21_node_source_sql")
    assert "add_raw(edge_start, full_hour_start)" in source
    assert "_r21_node_hourly_branch(full_hour_start, full_hour_end)" in source
    assert "add_raw(full_hour_end, edge_end)" in source
    assert "raw_start = max" in source
    assert "raw_available_start" in source
    assert "UNION ALL" in source


def test_node_group_summary_reuse_one_cached_node_dataset() -> None:
    source = read(LAYER)
    assert "V5070_QUERY_CACHE_TTL = max(5, min(15" in source
    assert 'return _r21_cached(("node-dataset", start, end)' in source
    assert function_source(LAYER, "_v5058c_node_totals").count("_r21_scoped_nodes") == 1
    assert function_source(LAYER, "_v5058c_vm_totals").count("_r21_scoped_nodes") == 1
    assert function_source(LAYER, "_v5058c_node_rows").count("_r21_scoped_nodes") == 1
    group = function_source(LAYER, "_r20_group_page")
    assert group.count("_r21_node_dataset(") == 1
    assert "_v5058c_vm_rows" not in group
    assert "vm_consumption_" not in group
    assert "node_stats" not in group


def test_vm_pipeline_remains_separate_and_hybrid() -> None:
    source = read(APP / "runtime_layers/40_consumption_cleanup_r4.py")
    assert "FROM vm_consumption_daily" in source
    assert "FROM vm_consumption_hourly" in source
    assert "FROM node_stats ns" in source
    assert "def _v5058c_vm_source_sql" in source
    node_group = function_source(LAYER, "_r20_group_page")
    assert "_v5058c_vm_source_sql" not in node_group
    assert "_v5058c_vm_rows" not in node_group


def test_explain_analyze_validator_enforces_forbidden_relations() -> None:
    validator = read(ROOT / "tools/validate-consumption-query-plans.py")
    assert "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)" in validator
    assert "seeded_nodes" in validator
    assert "node_consumption_hourly" in validator
    assert "vm_consumption_hourly" in validator
    assert "forbidden relations in EXPLAIN plan" in validator
    assert "vm_uuid" in validator


def test_clear_all_and_retention_cover_r21_tables() -> None:
    source = read(LAYER)
    maintenance = read(APP / "maintenance_native.py")
    for table in ("node_consumption_5m", "node_consumption_hourly", "node_consumption_daily", "vm_consumption_hourly", "vm_consumption_daily"):
        assert table in source or table in maintenance
    assert "DELETE FROM node_consumption_5m WHERE bucket_start<?" in source
    assert "Clear All Monitoring Data" in read(APP / "runtime_layers/34_bandwidth_consumption.py")
