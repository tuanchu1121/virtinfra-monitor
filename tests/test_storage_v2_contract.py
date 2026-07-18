#!/usr/bin/env python3
"""Pure-Python contract/regression tests for the storage V2 writer.

No database is required. A strict fake connection verifies generated row widths,
retry-safe UPSERT keys, multi-NIC aggregation and source-value normalization.
"""
from __future__ import annotations
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ["VIRTINFRA_STORAGE_V2"] = "1"
os.environ["VIRTINFRA_RAW_V2"] = "1"
import storage_v2 as s  # noqa: E402


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def iface(vm, bridge, name, rx, tx, rxp, txp, **extra):
    row = {
        "vm_uuid": vm, "bridge": bridge, "iface": name, "interval_seconds": 300,
        "rx_delta": rx, "tx_delta": tx,
        "rx_packets_delta": rxp, "tx_packets_delta": txp,
        "network_sample_count": 20, "network_sample_expected": 20,
        "network_sample_max_gap_seconds": 15.1,
        "network_sample_quality": "GOOD",
    }
    row.update(extra)
    return row


# Single, dual and 3-NIC aggregation. No implementation may assume two NICs.
items = [
    iface("vm-1", "br0", "vnet0", 1000, 2000, 10, 20, seconds_over_pps=5),
    iface("vm-1", "br1", "vnet1", 3000, 4000, 30, 40, seconds_over_mbps=7),
    iface("vm-1", "br-extra", "vnet2", 5000, 6000, 50, 60),
    iface("vm-2", "br0", "vnet3", 7000, 8000, 70, 80),
]
by_vm, raw = s._interface_aggregates(items, 300, "br0", "br1")
need(len(raw) == 4, "raw detail must preserve every interface")
need(all(len(row) == len(s.RAW_COLUMNS) for row in raw), "raw row width mismatch")
need(len(by_vm["vm-1"]["ifaces"]) == 3, "3-NIC VM was truncated")
need(by_vm["vm-1"]["rx_packets"] == 90, "generic RX packets lost an unclassified bridge")
need(by_vm["vm-1"]["tx_packets"] == 120, "generic TX packets lost an unclassified bridge")
need(by_vm["vm-1"]["public_rx_bytes"] == 1000, "public mapping changed")
need(by_vm["vm-1"]["private_rx_bytes"] == 3000, "private mapping changed")
need(by_vm["vm-1"]["sample_count"] == 60, "sample count must match legacy SUM across interfaces")
need(by_vm["vm-1"]["sample_expected"] == 60, "expected samples must match legacy SUM")
need(by_vm["vm-1"]["seconds_over_pps"] == 5, "PPS duration aggregation changed")
need(by_vm["vm-1"]["seconds_over_mbps"] == 7, "Mbps duration aggregation changed")
need(by_vm["vm-1"]["ifaces"][2]["role"] == "other", "unknown bridge must not be forced public/private")
role_labeled, _ = s._interface_aggregates([
    iface("vm-role", "br-extra", "vnet9", 1, 2, 3, 4, role="public")
], 300, "br0", "br1")
need(role_labeled["vm-role"]["ifaces"][0]["role"] == "other", "payload role must not override bridge-based Public/Private semantics")

# Missing/null/bad values are accepted and normalized without negative counters.
missing, missing_raw = s._interface_aggregates([
    {"vm_uuid": "vm-null", "bridge": None, "iface": None, "rx_delta": -1, "tx_delta": None},
    {"vm_uuid": "-", "bridge": "br0", "iface": "ignored"},
    "bad-entry",
], 300, "br0", "br1")
need(list(missing) == ["vm-null"], "invalid VM/interface filtering changed")
need(missing_raw[0][8] == 0 and missing_raw[0][9] == 0, "negative/null counters must clamp to zero")


class Result:
    def __init__(self, rows):
        self.rows = rows
    def fetchall(self):
        return self.rows
    def fetchone(self):
        return self.rows[0] if self.rows else None


class StrictConnection:
    def __init__(self):
        self.sql = []
        self.chart_rows = []
        self.raw_rows = []
        self.node_rows = []
    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        if "FROM vm_current_fast c" in sql:
            row = (
                "vm-1", 1710000000, 300, 3,
                1000, 2000, 3000, 4000, 9000, 12000, 21000,
                0.00008, 0.0001866667, 0.00024, 0.00032, 0.00056,
                0.1, 0.233333, 0.3, 0.4, 0.7,
                10.0, 20.0, 11.0, 21.0, 32.0,
                1000.0, 2000.0, 1100.0, 2100.0, 3200.0,
                60, 60, 15.1, "GOOD", 5, 0, 0, 0,
                28.75, 115.0, 4,
                4194304, 4194304, 3145728, 3670016, 1048576, 3145728,
                524288.0, 262144.0, 10.0, 5.0,
            )
            need(len(row) == 52, "fake vm_current_fast row contract drift")
            return Result([row])
        if "FROM node_current_fast n" in sql:
            row = (
                1710000000, 300, 1, 3,
                10000, 7000, 21000, 100, 70, 210, 0, 0,
                1.2, 1.0, 0.8, 32, 27.5,
                137438953472, 68719476736, 68719476736, 68719476736, 1073741824,
                1048576.0, 699050.0, 864000,
            )
            need(len(row) == 25, "fake node_current_fast row contract drift")
            return Result([row])
        if "node_chart_5m" in sql and sql.lstrip().startswith("INSERT"):
            need(len(params) == len(s.NODE_CHART_COLUMNS), "node chart row width mismatch")
            self.node_rows.append(tuple(params))
        return Result([])
    def executemany(self, sql, rows):
        rows = list(rows)
        self.sql.append((sql, rows))
        if "vm_raw_detail_5m" in sql:
            need("ON CONFLICT(bucket,node,vm_uuid,bridge,iface)" in sql, "raw retry key changed")
            need(all(len(row) == len(s.RAW_COLUMNS) for row in rows), "raw write width mismatch")
            self.raw_rows.extend(rows)
        elif "vm_chart_5m" in sql:
            need("ON CONFLICT(bucket,node,vm_uuid)" in sql, "chart retry key changed")
            need(all(len(row) == len(s.VM_CHART_COLUMNS) for row in rows), "chart write width mismatch")
            self.chart_rows.extend(rows)
        else:
            raise AssertionError("unexpected executemany target")


conn = StrictConnection()
stats = s.write_storage_v2(
    conn,
    node="node-1", bucket=1709999700, data_time=1710000000, interval_seconds=300,
    interfaces=items[:3], public_bridge="br0", private_bridge="br1",
)
need(stats.chart_rows == 1 and stats.raw_rows == 3 and stats.node_rows == 1, "writer row counts changed")
need(len(conn.chart_rows) == 1 and len(conn.raw_rows) == 3 and len(conn.node_rows) == 1, "writer did not emit all V2 layers")
chart = dict(zip(s.VM_CHART_COLUMNS, conn.chart_rows[0]))
need(chart["bucket"] == 1709999700 and chart["vm_uuid"] == "vm-1", "chart identity/timestamp changed")
need(chart["cpu_full_percent"] == 28.75 and chart["cpu_core_percent"] == 115.0, "CPU full/core semantics changed")
need(chart["ram_maximum_kib"] == 4194304, "assigned RAM was lost")
need(chart["disk_read_bps"] == 524288.0 and chart["disk_write_iops"] == 5.0, "disk metrics changed")
need(chart["rx_packets"] == 90 and chart["tx_packets"] == 120, "chart generic packets lost an unclassified bridge")
parsed = s.parse_interfaces_json(chart["interfaces_json"])
need(len(parsed) == 3, "compact chart interface snapshot lost N-NIC detail")

# Retry/out-of-order safety is enforced by stable bucket+identity UPSERT keys.
need(s._upsert_sql("vm_chart_5m", s.VM_CHART_COLUMNS, ("bucket", "node", "vm_uuid")).count("ON CONFLICT") == 1, "idempotent chart UPSERT missing")

print("PASS: storage V2 pure contract, N-NIC aggregation, null handling and batch row widths")
