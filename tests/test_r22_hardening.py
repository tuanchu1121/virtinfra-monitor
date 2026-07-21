from __future__ import annotations

import ast
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
L10 = ROOT / "app/runtime_layers/10_ingest_push.py"
L29 = ROOT / "app/runtime_layers/29_storage_integration.py"
L37 = ROOT / "app/runtime_layers/37_native_copy_ingest.py"
L44 = ROOT / "app/runtime_layers/44_consumption_node_vm_rollup.py"
L45 = ROOT / "app/runtime_layers/45_consumption_ingest_preaggregation.py"
ROLLUP = ROOT / "app/consumption_rollup.py"


def _load_functions(path: Path, names: set[str], namespace: dict):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    selected = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    missing = names - {node.name for node in selected}
    assert not missing, f"Missing functions in {path.name}: {sorted(missing)}"
    module = ast.Module(body=selected, type_ignores=[])
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


def _create_top_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE vm_current_fast (
          node TEXT NOT NULL, vm_uuid TEXT NOT NULL, last_seen INTEGER NOT NULL,
          interval_seconds INTEGER NOT NULL, iface_count INTEGER NOT NULL,
          public_rx_bytes INTEGER NOT NULL, public_tx_bytes INTEGER NOT NULL,
          private_rx_bytes INTEGER NOT NULL, private_tx_bytes INTEGER NOT NULL,
          rx_bytes INTEGER NOT NULL, tx_bytes INTEGER NOT NULL, total_bytes INTEGER NOT NULL,
          total_mbps REAL NOT NULL, total_peak_mbps REAL NOT NULL,
          total_pps REAL NOT NULL, total_peak_pps REAL NOT NULL,
          sample_count INTEGER NOT NULL, sample_expected INTEGER NOT NULL,
          sample_max_gap REAL NOT NULL, sample_quality TEXT NOT NULL,
          seconds_over_rx_pps INTEGER NOT NULL, seconds_over_tx_pps INTEGER NOT NULL,
          drops INTEGER NOT NULL, errors INTEGER NOT NULL,
          cpu_full_percent REAL NOT NULL, vcpu_current INTEGER NOT NULL, cpu_core_percent REAL NOT NULL,
          ram_rss_kib INTEGER NOT NULL, ram_current_kib INTEGER NOT NULL,
          ram_available_kib INTEGER NOT NULL, ram_unused_kib INTEGER NOT NULL,
          ram_usable_kib INTEGER NOT NULL,
          disk_read_bps REAL NOT NULL, disk_write_bps REAL NOT NULL,
          PRIMARY KEY(node, vm_uuid)
        );
        CREATE TABLE vm_disk_summary_current (
          node TEXT NOT NULL, vm_uuid TEXT NOT NULL, disk_count INTEGER NOT NULL,
          allocated_bytes INTEGER NOT NULL, assigned_bytes INTEGER NOT NULL,
          PRIMARY KEY(node, vm_uuid)
        );
        CREATE TABLE node_inventory (
          node TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'active', deleted_at INTEGER
        );
        CREATE TABLE vm_inventory (
          node TEXT NOT NULL, vm_uuid TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
          deleted_at INTEGER, PRIMARY KEY(node, vm_uuid)
        );
        CREATE TABLE node_groups (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE node_group_memberships (
          node TEXT PRIMARY KEY, group_id INTEGER NOT NULL
        );
        CREATE TABLE vm_iface_current (
          node TEXT NOT NULL, vm_uuid TEXT NOT NULL, iface TEXT, mac TEXT
        );
        CREATE TABLE node_bridge_addresses_latest (
          node TEXT NOT NULL, role TEXT NOT NULL, primary_ipv4 TEXT,
          ipv4_json TEXT NOT NULL DEFAULT '[]', last_seen INTEGER NOT NULL DEFAULT 0
        );
        """
    )


def _insert_vm(
    conn: sqlite3.Connection,
    *,
    node: str,
    vm_uuid: str,
    total: int,
    ram_used: int,
    ram_assigned: int,
    disk_allocated: int,
    disk_assigned: int,
    disk_count: int = 1,
    hidden: bool = False,
) -> None:
    now = int(time.time())
    ram_available = max(ram_used, 1) + 1024
    ram_usable = ram_available - ram_used
    conn.execute(
        """
        INSERT INTO vm_current_fast VALUES (
          ?,?,?,300,1,
          ?,0,0,0, ?,0,?,
          ?,?, ?,?,
          20,20,15.0,'GOOD',0,0,0,0,
          10.0,2,20.0,
          1024,?, ?,1,?,
          1.0,2.0
        )
        """,
        (
            node, vm_uuid, now,
            total, total, total,
            total * 8.0 / 300 / 1_000_000,
            total * 8.0 / 300 / 1_000_000,
            total / 300.0, total / 300.0,
            ram_assigned, ram_available, ram_usable,
        ),
    )
    conn.execute(
        "INSERT INTO vm_disk_summary_current VALUES (?,?,?,?,?)",
        (node, vm_uuid, disk_count, disk_allocated, disk_assigned),
    )
    conn.execute(
        "INSERT INTO vm_inventory(node,vm_uuid,status,deleted_at) VALUES (?,?,?,NULL)",
        (node, vm_uuid, "hidden" if hidden else "active"),
    )


def _top_namespace(db_path: Path) -> dict:
    class Logger:
        def exception(self, *_args, **_kwargs):
            raise AssertionError("unexpected reconciliation failure")

    return {
        "db": lambda: sqlite3.connect(db_path),
        "now_ts": lambda: int(time.time()),
        "FAST_CURRENT_STALE_SECONDS": 3600,
        "safe_int": lambda value, default=0: default if value is None else int(value),
        "like_pattern": lambda value: f"%{value}%",
        "app": SimpleNamespace(logger=Logger()),
        "_v48140_reconcile_summaries_if_needed": lambda _conn: None,
        "_R22_RAM_VALID": """(COALESCE({a}.ram_available_kib,0)>0 AND (COALESCE({a}.ram_usable_kib,0)>0 OR COALESCE({a}.ram_unused_kib,0)>0) AND COALESCE({a}.ram_usable_kib,0)<=COALESCE({a}.ram_available_kib,0)*1.05)""",
    }


def test_top_vm_ram_and_disk_sort_across_more_than_1000_vms(tmp_path: Path):
    db_path = tmp_path / "top.sqlite3"
    conn = sqlite3.connect(db_path)
    _create_top_schema(conn)
    conn.execute("INSERT INTO node_groups VALUES (1,'VN',1)")
    conn.execute("INSERT INTO node_groups VALUES (2,'JP',1)")
    for node, group_id in (("NODE-VN", 1), ("NODE-JP", 2), ("NODE-HIDDEN", 1)):
        conn.execute(
            "INSERT INTO node_inventory(node,status,deleted_at) VALUES (?,?,NULL)",
            (node, "hidden" if node == "NODE-HIDDEN" else "active"),
        )
        conn.execute("INSERT INTO node_group_memberships VALUES (?,?)", (node, group_id))

    # 1,500 ordinary VMs have much higher network than the two special VMs.
    for i in range(1500):
        node = "NODE-VN" if i % 2 == 0 else "NODE-JP"
        _insert_vm(
            conn,
            node=node,
            vm_uuid=f"vm-{i:04d}",
            total=10_000_000 - i,
            ram_used=1000 + i,
            ram_assigned=8_000_000,
            disk_allocated=10_000 + i,
            disk_assigned=100_000 + i,
        )
    _insert_vm(
        conn,
        node="NODE-VN",
        vm_uuid="vm-ram-global-winner",
        total=1,
        ram_used=50_000_000,
        ram_assigned=64_000_000,
        disk_allocated=1,
        disk_assigned=2,
    )
    _insert_vm(
        conn,
        node="NODE-JP",
        vm_uuid="vm-disk-global-winner",
        total=2,
        ram_used=10,
        ram_assigned=100,
        disk_allocated=900_000_000,
        disk_assigned=1_000_000_000,
        disk_count=4,
    )
    _insert_vm(
        conn,
        node="NODE-HIDDEN",
        vm_uuid="vm-hidden-would-win",
        total=99_999_999,
        ram_used=99_999_999,
        ram_assigned=100_000_000,
        disk_allocated=99_999_999,
        disk_assigned=100_000_000,
    )
    conn.commit()

    names = {
        "_r22_ram_sort_expressions",
        "_r22_disk_sort_expressions",
        "_r22_top_order_expression",
        "_r22_top_visibility_sql",
        "_r22_get_top_vm_rows_live",
    }
    conn.close()
    ns = _load_functions(L29, names, _top_namespace(db_path))

    ram_rows, *_ = ns["_r22_get_top_vm_rows_live"](
        "", "ramused", "desc", "all", 10, group_id=0
    )
    assert ram_rows[0][1] == "vm-ram-global-winner"
    assert all(row[1] != "vm-hidden-would-win" for row in ram_rows)

    disk_rows, *_ = ns["_r22_get_top_vm_rows_live"](
        "", "diskassigned", "desc", "all", 10, group_id=0
    )
    assert disk_rows[0][1] == "vm-disk-global-winner"

    vn_rows, *_ = ns["_r22_get_top_vm_rows_live"](
        "", "ramused", "desc", "all", 10, group_id=1
    )
    assert vn_rows[0][1] == "vm-ram-global-winner"
    assert all(row[0] == "NODE-VN" for row in vn_rows)

    jp_rows, *_ = ns["_r22_get_top_vm_rows_live"](
        "", "diskassigned", "desc", "all", 10, group_id=2
    )
    assert jp_rows[0][1] == "vm-disk-global-winner"
    assert all(row[0] == "NODE-JP" for row in jp_rows)




def _create_history_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE node_stats(
          bucket INTEGER,node TEXT,vm_uuid TEXT,bridge TEXT,iface TEXT,
          rx_delta INTEGER,tx_delta INTEGER,interval_seconds INTEGER,
          rx_mbps_peak REAL,tx_mbps_peak REAL,rx_pps_peak REAL,tx_pps_peak REAL,
          rx_packets_delta INTEGER,tx_packets_delta INTEGER,
          rx_drop_delta INTEGER,tx_drop_delta INTEGER,rx_error_delta INTEGER,tx_error_delta INTEGER,
          network_sample_count INTEGER,network_sample_expected INTEGER,
          network_sample_max_gap_seconds REAL,seconds_over_pps INTEGER,seconds_over_mbps INTEGER,
          network_sample_quality TEXT,last_push INTEGER
        );
        CREATE TABLE vm_perf_stats(
          bucket INTEGER,node TEXT,vm_uuid TEXT,interval_seconds INTEGER,
          cpu_percent REAL,vcpu_current INTEGER,
          ram_rss_kib INTEGER,ram_current_kib INTEGER,ram_available_kib INTEGER,
          ram_unused_kib INTEGER,ram_usable_kib INTEGER,
          disk_read_delta INTEGER,disk_write_delta INTEGER
        );
        CREATE TABLE vm_disk_summary_current(
          node TEXT,vm_uuid TEXT,disk_count INTEGER,allocated_bytes INTEGER,assigned_bytes INTEGER,
          PRIMARY KEY(node,vm_uuid)
        );
        CREATE TABLE node_inventory(node TEXT PRIMARY KEY,status TEXT,deleted_at INTEGER);
        CREATE TABLE vm_inventory(node TEXT,vm_uuid TEXT,status TEXT,deleted_at INTEGER,PRIMARY KEY(node,vm_uuid));
        CREATE TABLE node_groups(id INTEGER PRIMARY KEY,name TEXT,is_active INTEGER);
        CREATE TABLE node_group_memberships(node TEXT PRIMARY KEY,group_id INTEGER);
        CREATE TABLE node_bridge_addresses_latest(node TEXT,role TEXT,primary_ipv4 TEXT,ipv4_json TEXT,last_seen INTEGER);
        """
    )


def test_historical_top_vm_global_ram_and_disk_sort(tmp_path: Path):
    db_path = tmp_path / "history.sqlite3"
    conn = sqlite3.connect(db_path)
    _create_history_schema(conn)
    bucket = 1_700_000_000
    conn.execute("INSERT INTO node_groups VALUES (1,'ALL',1)")
    for node in ("NODE-A", "NODE-B"):
        conn.execute("INSERT INTO node_inventory VALUES (?,'active',NULL)", (node,))
        conn.execute("INSERT INTO node_group_memberships VALUES (?,1)", (node,))
    for i in range(1500):
        node = "NODE-A" if i % 2 == 0 else "NODE-B"
        vm = f"hist-{i:04d}"
        total = 9_000_000 - i
        conn.execute(
            "INSERT INTO node_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (bucket,node,vm,'br0',f'vnet{i}',total,0,300,1,1,1,1,10,0,0,0,0,0,20,20,15,0,0,'GOOD',bucket+299),
        )
        conn.execute(
            "INSERT INTO vm_perf_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (bucket,node,vm,300,10,2,1024,8_000_000,8_000_000,1024,7_999_000,1,1),
        )
        conn.execute("INSERT INTO vm_disk_summary_current VALUES (?,?,?,?,?)", (node,vm,1,1000+i,10000+i))
        conn.execute("INSERT INTO vm_inventory VALUES (?,?,'active',NULL)", (node,vm))
    conn.execute(
        "INSERT INTO node_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (bucket,'NODE-A','hist-ram-winner','br0','vnetx',1,0,300,1,1,1,1,1,0,0,0,0,0,20,20,15,0,0,'GOOD',bucket+299),
    )
    conn.execute(
        "INSERT INTO vm_perf_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (bucket,'NODE-A','hist-ram-winner',300,1,1,1024,64_000_000,64_000_000,1,1000,1,1),
    )
    conn.execute("INSERT INTO vm_disk_summary_current VALUES ('NODE-A','hist-ram-winner',1,1,2)")
    conn.execute("INSERT INTO vm_inventory VALUES ('NODE-A','hist-ram-winner','active',NULL)")
    conn.execute(
        "INSERT INTO node_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (bucket,'NODE-B','hist-disk-winner','br0','vnety',2,0,300,1,1,1,1,1,0,0,0,0,0,20,20,15,0,0,'GOOD',bucket+299),
    )
    conn.execute(
        "INSERT INTO vm_perf_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (bucket,'NODE-B','hist-disk-winner',300,1,1,1,1,1,1,1,1,1),
    )
    conn.execute("INSERT INTO vm_disk_summary_current VALUES ('NODE-B','hist-disk-winner',8,900000000,1000000000)")
    conn.execute("INSERT INTO vm_inventory VALUES ('NODE-B','hist-disk-winner','active',NULL)")
    conn.commit(); conn.close()

    ns = _top_namespace(db_path)
    ns.update({
        "auto_cleanup_inventory": lambda: None,
        "resolve_snapshot_bucket": lambda _conn, _period, node=None: (bucket, bucket),
        "CACHE_BUCKET_SECONDS": 300,
        "PUBLIC_BRIDGE": "br0",
        "PRIVATE_BRIDGE": "br1",
    })
    names = {
        "_r22_ram_sort_expressions", "_r22_disk_sort_expressions",
        "_r22_top_order_expression", "_r22_top_visibility_sql",
        "_r22_get_top_vm_rows_history",
    }
    ns = _load_functions(L29, names, ns)
    ram_rows, *_ = ns["_r22_get_top_vm_rows_history"]("1h", "", "ramused", "desc", "all", 10, 0)
    assert ram_rows[0][1] == "hist-ram-winner"
    disk_rows, *_ = ns["_r22_get_top_vm_rows_history"]("1h", "", "diskassigned", "desc", "all", 10, 0)
    assert disk_rows[0][1] == "hist-disk-winner"

def test_r22_source_contracts_are_hardened_without_second_snapshot_table():
    top = L29.read_text(encoding="utf-8")
    consumption = L44.read_text(encoding="utf-8")
    shim = L45.read_text(encoding="utf-8")
    ingest = L10.read_text(encoding="utf-8")
    native = L37.read_text(encoding="utf-8")
    rollup = ROLLUP.read_text(encoding="utf-8")

    assert "vm_top_current" not in top
    assert "ORDER BY {order_expr}" in top
    assert "LIMIT ?" in top
    assert "fetch_limit = 1000" not in top
    global_helper = top[top.index("def _r22_get_top_vm_rows_live"):top.index("def _v48133_disk_sort_link")]
    assert "rows.sort(" not in global_helper

    assert "group_id, selected_node, q, coverage" in consumption
    assert "visibility_generation" in consumption
    assert "_v48140_cache_generation" in consumption
    assert "raw_available_start" in consumption
    assert "expected = max(1, safe_int(end, 0) - safe_int(start, 0))" in consumption

    assert "V50_MAX_FUTURE_PUSH_SECONDS" in ingest
    assert "future_payload" in ingest
    assert 'vm_metrics_present = "vms" in data' in ingest
    assert "if vm_metrics_present:" in ingest
    assert "WHEN MATCHED AND src.last_seen >= dst.last_seen" in native
    assert "excluded.last_seen >= vm_iface_current.last_seen" in native
    assert "excluded.last_seen >= vm_current_fast.last_seen" in native
    assert "excluded.last_seen >= node_current_fast.last_seen" in native
    for state in ("pending", "running", "completed", "completed_with_gaps", "failed"):
        assert state in rollup

    assert "def " not in shim
    assert "R22_CONSUMPTION_CANONICAL_LAYER = 44" in shim


def test_r22_benchmark_covers_every_existing_top_vm_sort_key():
    benchmark_path = ROOT / "tools/benchmark-r22-top-vm.py"
    tree = ast.parse(benchmark_path.read_text(encoding="utf-8"), filename=str(benchmark_path))
    sorts = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SORTS" for t in node.targets):
            sorts = ast.literal_eval(node.value)
            break
    assert sorts is not None
    expected = {
        "total", "rx", "tx", "public", "private", "mbps", "peakmbps",
        "pps", "peakpps", "sample", "drops", "errors", "cpu", "cpufull",
        "vcpu", "ram", "ramguest", "ramused", "ramrss", "ramassigned",
        "diskr", "diskw", "diskallocated", "diskassigned", "diskallocpct",
        "diskcount", "last_push", "node", "vm",
    }
    assert set(sorts) == expected

    for root in (ROOT / "app", ROOT / "postgres", ROOT / "deploy"):
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".sql", ".sh", ".yml", ".yaml"}:
                assert "vm_top_current" not in path.read_text(encoding="utf-8", errors="replace"), path
