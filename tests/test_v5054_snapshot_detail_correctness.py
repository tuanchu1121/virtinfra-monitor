from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
from runtime_source import read_app_source
APP = read_app_source()
APP_TREE = ast.parse(APP)


def function_nodes(name: str):
    return [n for n in APP_TREE.body if isinstance(n, ast.FunctionDef) and n.name == name]


def function_source(name: str, index: int = -1) -> str:
    nodes = function_nodes(name)
    assert nodes, name
    node = nodes[index]
    lines = APP.splitlines()
    return "\n".join(lines[node.lineno - 1:node.end_lineno])


def compile_function(name: str, index: int = -1, namespace=None):
    node = function_nodes(name)[index]
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    scope = dict(namespace or {})
    exec(compile(module, f"<{name}-test>", "exec"), scope)
    return scope[name]


def test_release_identity_and_preflight_dependencies():
    assert (ROOT / "VERSION").read_text().strip() == "50.5.9-prod-r9-safe-runtime-history-prune"
    requirements = (ROOT / "requirements.txt").read_text()
    assert "pytest>=8,<9" in requirements
    assert "PyYAML>=6,<7" in requirements
    preflight = (ROOT / "preflight.sh").read_text()
    assert "tests/test_v5054_snapshot_detail_correctness.py" in preflight
    assert "yaml, pytest" in preflight


def test_dashboard_alignment_and_interface_order_remain_unchanged():
    assert "V5054_DASHBOARD_CSS" in APP
    assert "dashboard-load-pill" in APP
    assert "width:132px" in APP
    assert "font-variant-numeric:tabular-nums" in APP
    assert 'node_sort_header("INTERFACE", "source"' in APP
    assert "dashboard-interface-col" in APP


def test_retained_storage_payload_is_still_used_for_history():
    helper = function_source("_v5054_selected_storage_payload")
    assert "node_push_snapshots" in helper
    assert "bucket=?" in helper
    assert "storage_payload" in helper
    assert "CREATE TABLE" not in helper

    historical_disks = function_source("_v48133_vm_disks", -2)
    final_disks = function_source("_v48133_vm_disks", -1)
    assert '_v5054_selected_storage_payload(conn, node, period)' in historical_disks
    assert 'payload.get("d")' in historical_disks
    assert "FROM vm_disk_current" in final_disks
    assert "_v5057_vm_disks_history_base" in final_disks


def test_historical_overview_uses_one_exact_selected_bucket():
    historical = function_source("_v5054_vm_snapshot_overview", -2)
    assert "resolve_snapshot_bucket" in historical
    assert "FROM node_stats" in historical
    assert "FROM vm_perf_stats" in historical
    assert historical.count("bucket=?") >= 2
    assert "resolve_table_snapshot_bucket" not in historical
    assert "vm_latest_metrics" not in historical
    assert "vm_current_fast" not in historical
    assert 'net_where.append("bridge=?")' in historical
    assert 'net_where.append("iface=?")' in historical


def test_final_overview_uses_live_current_only_for_5m_then_history():
    wrapper = function_source("_v5054_vm_snapshot_overview")
    live = function_source("_v5057_live_vm_snapshot")
    assert '_request_target_ts()isNoneandperiod=="5m"' in wrapper.replace(" ", "")
    assert "_v5057_live_vm_snapshot" in wrapper
    assert "_v5057_vm_snapshot_history_base" in wrapper
    assert "FROM vm_current_fast" in live
    assert "FROM vm_iface_current" in live


def test_cpu_renderer_does_not_divide_normalized_cpu_twice():
    cpu = function_source("_v48129_vm_detail_cpu_stat")
    compact = cpu.replace(" ", "")
    assert "core=full*vcpu_count" in compact
    assert "core/vcpu_count" not in compact


def test_historical_ram_uses_exact_selected_bucket_and_live_ram_uses_current():
    ram = function_source("_v48103_latest_ram")
    assert 'target is None and period == "5m"' in ram
    assert "FROM vm_current_fast" in ram
    assert "resolve_snapshot_bucket" in ram
    assert "FROM vm_perf_stats" in ram
    assert "bucket=?" in ram


class RowCursor:
    def __init__(self, row=None):
        self.row = row
    def fetchone(self):
        return self.row


class HistoryConn:
    def __init__(self):
        self.calls = []
    def execute(self, sql, params=()):
        params = tuple(params)
        assert sql.count("?") == len(params), (sql, params)
        self.calls.append((sql, params))
        if "FROM node_stats" in sql:
            return RowCursor((
                2, 1000, 300, 3000, 6000, 30, 60, 4, 5,
                33.0, 66.0, 333.0, 666.0, 20, 20, 2.5, 120, 180,
                2, "tap1", "br0",
            ))
        if "FROM vm_perf_stats" in sql:
            return RowCursor((1, 1000, 300, 100.0, 7, 7168, 7168, 6500, 1000, 123.0, 456.0))
        raise AssertionError(sql)
    def close(self):
        pass


def test_historical_snapshot_mapping_and_parameter_widths():
    conn = HistoryConn()
    fn = compile_function(
        "_v5054_vm_snapshot_overview",
        -2,
        namespace={
            "clean_period": lambda value: value,
            "db": lambda: conn,
            "resolve_snapshot_bucket": lambda _conn, _period, node=None: (1000, 1300),
            "safe_int": lambda value, default=0: int(value if value is not None else default),
            "safe_float": lambda value, default=0.0: float(value if value is not None else default),
            "network_quality_from_rank": lambda rank: {3: "POOR", 2: "DEGRADED", 1: "GOOD"}.get(rank, "LEGACY"),
            "CACHE_BUCKET_SECONDS": 300,
        },
    )
    result = fn("node-a", "vm-a", "10m", bridge="br0", iface="tap1")
    assert result["selected_bucket"] == 1000
    assert result["rx_bytes"] == 3000 and result["tx_bytes"] == 6000
    assert result["rx_mbps_peak"] == 33.0 and result["tx_mbps_peak"] == 66.0
    assert result["cpu_percent"] == 100.0 and result["vcpu_current"] == 7
    net_call = next(call for call in conn.calls if "FROM node_stats" in call[0])
    assert net_call[1][-2:] == ("br0", "tap1")
