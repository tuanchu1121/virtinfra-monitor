from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app/app.py").read_text(encoding="utf-8")


def function_block(name: str) -> str:
    matches = list(re.finditer(rf"^def {re.escape(name)}\(", APP, re.M))
    assert matches, f"missing function: {name}"
    start = matches[-1].start()
    next_def = re.search(r"^(?:def |@app\.route|if _|app\.view_functions)", APP[matches[-1].end():], re.M)
    end = matches[-1].end() + next_def.start() if next_def else len(APP)
    return APP[start:end]


def test_release_identity_and_preflight_dependencies():
    assert (ROOT / "VERSION").read_text().strip() == "50.5.5-prod-r1-native-copy-sql-compat-hotfix"
    requirements = (ROOT / "requirements.txt").read_text()
    assert "pytest>=8,<9" in requirements
    assert "PyYAML>=6,<7" in requirements
    preflight = (ROOT / "preflight.sh").read_text()
    assert "tests/test_v5054_snapshot_detail_correctness.py" in preflight
    assert "yaml, pytest" in preflight


def test_dashboard_alignment_and_interface_order():
    assert "V5054_DASHBOARD_CSS" in APP
    assert "dashboard-load-pill" in APP
    assert "width:132px" in APP
    assert "font-variant-numeric:tabular-nums" in APP
    assert 'node_sort_header("INTERFACE", "source"' in APP
    assert "dashboard-interface-col" in APP
    header = re.search(
        r"<th>\{headers\['diskr'\]\}</th><th>\{headers\['diskw'\]\}</th>"
        r"<th>\{headers\['drops'\]\}</th><th>\{headers\['errors'\]\}</th>"
        r"<th class=\"dashboard-interface-col\">\{headers\['source'\]\}</th>",
        APP,
    )
    assert header, "INTERFACE must be the final dashboard column"


def test_storage_details_reuse_existing_retained_payload():
    helper = function_block("_v5054_selected_storage_payload")
    assert "node_push_snapshots" in helper
    assert "bucket=?" in helper
    assert "storage_payload" in helper
    assert "CREATE TABLE" not in helper

    vm_disks = function_block("_v48133_vm_disks")
    assert '_v5054_selected_storage_payload(conn, node, period)' in vm_disks
    assert 'payload.get("d")' in vm_disks
    assert 'if not live_request or not table_columns(conn, "vm_disk_current")' in vm_disks

    filesystems = function_block("get_node_filesystems_snapshot")
    # Last definition is the filtering wrapper, so inspect the retained-snapshot
    # implementation directly from its unique docstring region.
    marker = '"""Return capacity and I/O from the same selected retained Agent push."""'
    pos = APP.index(marker)
    impl_start = APP.rfind("def get_node_filesystems_snapshot", 0, pos)
    impl_end = APP.index("\ndef _v48133_public_ip_sql", pos)
    impl = APP[impl_start:impl_end]
    assert 'payload.get("s")' in impl
    assert 'WHERE node=? AND bucket=?' in impl
    assert '0,0,0,0,0,0' in impl
    assert 'live_request' in impl and 'node_storage_current' in impl
    assert "resolve_table_snapshot_bucket" not in impl


def test_vm_overview_uses_one_exact_selected_bucket():
    overview = function_block("_v5054_vm_snapshot_overview")
    assert "resolve_snapshot_bucket" in overview
    assert "FROM node_stats" in overview
    assert "FROM vm_perf_stats" in overview
    assert overview.count("bucket=?") >= 2
    assert "resolve_table_snapshot_bucket" not in overview
    assert "vm_latest_metrics" not in overview
    assert "vm_current_fast" not in overview
    assert 'net_where.append("bridge=?")' in overview
    assert 'net_where.append("iface=?")' in overview

    page_start = APP.index('@app.route("/vm")\ndef vm_page():')
    page_end = APP.index("\ndef api_vm():", page_start)
    page = APP[page_start:page_end]
    assert "Selected Snapshot" in page
    assert 'overview_rx_total = snapshot["rx_bytes"]' in page
    assert 'overview_drops_total = snapshot["drops"]' in page
    assert "Directional streak counters are current-only" in page


def test_no_new_snapshot_history_tables_or_request_time_ddl():
    forbidden = ("vm_disk_io_history", "node_storage_io_history")
    for name in forbidden:
        assert name not in APP
    helper = function_block("_v5054_selected_storage_payload")
    assert "ensure_storage_snapshot_schema" not in helper
    assert "ensure_column" not in helper


def _compile_function(name: str, predicate=None, namespace=None):
    import ast

    tree = ast.parse(APP)
    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if predicate is not None:
        matches = [node for node in matches if predicate(node)]
    assert matches, f"function AST not found: {name}"
    module = ast.Module(body=[matches[-1]], type_ignores=[])
    ast.fix_missing_locations(module)
    scope = dict(namespace or {})
    exec(compile(module, f"<{name}-test>", "exec"), scope)
    return scope[name]


class _RowCursor:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows if rows is not None else ([] if row is None else [row])

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _OverviewConn:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        params = tuple(params)
        assert sql.count("?") == len(params), (sql, params)
        self.calls.append((sql, params))
        if "FROM node_stats" in sql:
            return _RowCursor((
                2, 1000, 300, 3000, 6000, 30, 60, 4, 5,
                11.0, 22.0, 111.0, 222.0, 40, 50, 2.5, 120, 180,
                2, "tap1", "br0",
            ))
        if "FROM vm_perf_stats" in sql:
            return _RowCursor((1, 1000, 300, 250.0, 4, 1024, 2048, 900, 700, 123.0, 456.0))
        raise AssertionError(sql)

    def close(self):
        pass


def test_vm_snapshot_mapping_and_sql_parameter_widths():
    conn = _OverviewConn()
    fn = _compile_function(
        "_v5054_vm_snapshot_overview",
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
    assert result["latest_bucket"] == 1300
    assert result["rx_bytes"] == 3000 and result["tx_bytes"] == 6000
    assert result["rx_mbps"] == 0.00008 and result["tx_mbps"] == 0.00016
    assert result["packets"] == 90
    assert result["drops"] == 4 and result["errors"] == 5
    assert result["sample_quality"] == "DEGRADED"
    assert result["cpu_percent"] == 250.0 and result["vcpu_current"] == 4
    assert result["disk_read_bps"] == 123.0 and result["disk_write_bps"] == 456.0
    net_call = next(call for call in conn.calls if "FROM node_stats" in call[0])
    assert net_call[1][-2:] == ("br0", "tap1")


def test_retained_payload_mapping_for_node_and_vm_details():
    payload = {
        "v": 1,
        "t": 1001,
        "s": [["/", "/dev/vda1", "vda", "", "ext4", 10000, 6000, 4000, 60.0, 10.0, 20.0, 1.0, 2.0, 3.0]],
        "d": [["vm-a", "vda", "/images/vm-a.qcow2", "/", "/dev/vda1", "vda", "ext4", 10000, 7000, 8000, 30.0, 40.0, 3.0, 4.0]],
    }

    class Conn:
        def close(self):
            pass

    common = {
        "clean_period": lambda value: value,
        "db": lambda: Conn(),
        "_v5054_selected_storage_payload": lambda conn, node, period: (payload, 1000, 1300),
        "safe_int": lambda value, default=0: int(value if value is not None else default),
        "safe_float": lambda value, default=0.0: float(value if value is not None else default),
        "_request_target_ts": lambda: None,
        "table_columns": lambda conn, table: set(),
        "request": type("Request", (), {"args": {"get": lambda self, key, default=None: "10m" if key == "period" else default}})(),
    }
    node_fn = _compile_function(
        "get_node_filesystems_snapshot",
        predicate=lambda node: (
            getattr(node, "body", None)
            and isinstance(node.body[0], __import__("ast").Expr)
            and "same selected retained Agent push" in getattr(node.body[0].value, "value", "")
        ),
        namespace=common,
    )
    node_rows = node_fn("node-a", "10m")
    assert node_rows == [("/", "/dev/vda1", "ext4", 10000, 6000, 4000, 60.0, 1001, 10.0, 20.0, 1.0, 2.0, 3.0, 1001)]

    vm_fn = _compile_function("_v48133_vm_disks", namespace=common)
    vm_rows = vm_fn("node-a", "vm-a")
    assert vm_rows == [("vda", "/images/vm-a.qcow2", "/", "/dev/vda1", "vda", "ext4", 10000, 7000, 8000, 30.0, 40.0, 3.0, 4.0, 1001)]
