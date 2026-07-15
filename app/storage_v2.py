"""Compact 5-minute chart and short raw-detail storage for VirtInfra Monitor.

This module is intentionally isolated from Flask/UI code.  The existing Agent
payload, routes, authentication, current-state tables, Abuse engine, Storage I/O
and Consumption module remain authoritative.  The module receives an already
validated push and writes three append-oriented Timescale hypertables:

* vm_chart_5m: one compact row per VM and 5-minute bucket, retained 7 days.
* vm_raw_detail_5m: one row per VM interface and bucket, retained 48 hours.
* node_chart_5m: one compact row per node and bucket, retained 7 days.

The chart row is built from vm_current_fast after the existing current writer has
finished.  That preserves the exact multi-NIC, CPU, RAM and multi-disk formulas
already used by the production UI and Abuse engine instead of reimplementing
business logic in a second place.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Any, Iterable

STORAGE_V2_ENABLED = os.environ.get("VIRTINFRA_STORAGE_V2", "1") == "1"
CHART_V2_READ_ENABLED = os.environ.get("VIRTINFRA_READ_CHART_V2", "1") == "1"
RAW_V2_ENABLED = os.environ.get("VIRTINFRA_RAW_V2", "1") == "1"
OBSERVABILITY_ENABLED = os.environ.get("VIRTINFRA_PUSH_OBSERVABILITY", "1") == "1"

VM_CHART_TABLE = "vm_chart_5m"
VM_RAW_TABLE = "vm_raw_detail_5m"
NODE_CHART_TABLE = "node_chart_5m"


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return int(default)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _non_negative_i(value: Any) -> int:
    return max(0, _i(value, 0))


def _non_negative_f(value: Any) -> float:
    return max(0.0, _f(value, 0.0))


def _quality(value: Any) -> str:
    value = str(value or "LEGACY").strip().upper()
    return value if value in {"GOOD", "DEGRADED", "POOR", "LEGACY"} else "LEGACY"


def _quality_rank(value: str) -> int:
    return {"LEGACY": 0, "GOOD": 1, "DEGRADED": 2, "POOR": 3}.get(_quality(value), 0)


def _role(item: dict[str, Any], public_bridge: str, private_bridge: str) -> str:
    """Classify exactly like the existing production current-state writer.

    Public/private meaning is bridge-driven in the current application.  Do not
    let an optional payload label silently change chart semantics.
    """
    bridge = str(item.get("bridge") or "").strip()
    if bridge == public_bridge:
        return "public"
    if bridge == private_bridge:
        return "private"
    return "other"


def _upsert_sql(table: str, columns: tuple[str, ...], keys: tuple[str, ...]) -> str:
    placeholders = ",".join("?" for _ in columns)
    updates = ",".join(f"{c}=excluded.{c}" for c in columns if c not in keys)
    return (
        f"INSERT INTO {table}({','.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT({','.join(keys)}) DO UPDATE SET {updates}"
    )


@dataclass
class WriteStats:
    enabled: bool = True
    chart_rows: int = 0
    raw_rows: int = 0
    node_rows: int = 0
    chart_write_ms: float = 0.0
    raw_write_ms: float = 0.0
    node_write_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


VM_CHART_COLUMNS = (
    "bucket", "node", "vm_uuid", "last_push", "interval_seconds", "iface_count",
    "public_rx_bytes", "public_tx_bytes", "private_rx_bytes", "private_tx_bytes",
    "rx_bytes", "tx_bytes", "total_bytes",
    "public_rx_packets", "public_tx_packets", "private_rx_packets", "private_tx_packets",
    "rx_packets", "tx_packets", "total_packets",
    "public_rx_mbps", "public_tx_mbps", "private_rx_mbps", "private_tx_mbps",
    "rx_mbps", "tx_mbps", "total_mbps",
    "public_rx_pps", "public_tx_pps", "private_rx_pps", "private_tx_pps",
    "rx_pps", "tx_pps", "total_pps",
    "public_peak_mbps", "private_peak_mbps", "rx_peak_mbps", "tx_peak_mbps", "total_peak_mbps",
    "public_peak_pps", "private_peak_pps", "rx_peak_pps", "tx_peak_pps", "total_peak_pps",
    "sample_count", "sample_expected", "sample_max_gap", "sample_quality",
    "seconds_over_pps", "seconds_over_mbps", "seconds_over_rx_pps", "seconds_over_tx_pps", "drops", "errors",
    "cpu_full_percent", "cpu_core_percent", "vcpu_current",
    "ram_current_kib", "ram_maximum_kib", "ram_rss_kib", "ram_available_kib",
    "ram_unused_kib", "ram_usable_kib",
    "disk_read_bps", "disk_write_bps", "disk_read_iops", "disk_write_iops",
    "interfaces_json",
)

RAW_COLUMNS = (
    "bucket", "node", "vm_uuid", "bridge", "iface", "role", "last_push", "interval_seconds",
    "rx_delta", "tx_delta", "rx_packets_delta", "tx_packets_delta",
    "rx_drop_delta", "tx_drop_delta", "rx_error_delta", "tx_error_delta",
    "rx_mbps_peak", "tx_mbps_peak", "rx_pps_peak", "tx_pps_peak",
    "rx_packet_size_avg", "tx_packet_size_avg",
    "network_sample_count", "network_sample_expected", "network_sample_max_gap_seconds",
    "seconds_over_pps", "seconds_over_mbps", "seconds_over_rx_pps", "seconds_over_tx_pps", "network_sample_quality",
)

NODE_CHART_COLUMNS = (
    "bucket", "node", "last_push", "interval_seconds", "vm_count", "iface_count",
    "public_bytes", "private_bytes", "total_bytes",
    "public_packets", "private_packets", "total_packets", "drops", "errors",
    "load1", "load5", "load15", "cpu_count", "cpu_percent",
    "mem_total", "mem_available", "mem_used", "swap_total", "swap_used",
    "disk_read_bps", "disk_write_bps", "uptime_seconds",
)


def _interface_aggregates(
    interfaces: Iterable[Any],
    interval_seconds: int,
    public_bridge: str,
    private_bridge: str,
) -> tuple[dict[str, dict[str, Any]], list[tuple[Any, ...]]]:
    """Return compact per-VM network aggregates plus raw interface rows."""
    by_vm: dict[str, dict[str, Any]] = {}
    raw_rows: list[tuple[Any, ...]] = []

    for source in interfaces or []:
        if not isinstance(source, dict):
            continue
        vm_uuid = str(source.get("vm_uuid") or "").strip()
        if not vm_uuid or vm_uuid == "-":
            continue
        bridge = str(source.get("bridge") or "-").strip() or "-"
        iface = str(source.get("iface") or "-").strip() or "-"
        sec = max(1, min(86400, _i(source.get("interval_seconds"), interval_seconds)))
        role = _role(source, public_bridge, private_bridge)

        rx_b = _non_negative_i(source.get("rx_delta"))
        tx_b = _non_negative_i(source.get("tx_delta"))
        rx_p = _non_negative_i(source.get("rx_packets_delta"))
        tx_p = _non_negative_i(source.get("tx_packets_delta"))
        rx_d = _non_negative_i(source.get("rx_drop_delta"))
        tx_d = _non_negative_i(source.get("tx_drop_delta"))
        rx_e = _non_negative_i(source.get("rx_error_delta"))
        tx_e = _non_negative_i(source.get("tx_error_delta"))
        rx_mbps = rx_b * 8.0 / sec / 1_000_000.0
        tx_mbps = tx_b * 8.0 / sec / 1_000_000.0
        rx_pps = rx_p / float(sec)
        tx_pps = tx_p / float(sec)
        rx_mbps_peak = max(rx_mbps, _non_negative_f(source.get("rx_mbps_peak")))
        tx_mbps_peak = max(tx_mbps, _non_negative_f(source.get("tx_mbps_peak")))
        rx_pps_peak = max(rx_pps, _non_negative_f(source.get("rx_pps_peak")))
        tx_pps_peak = max(tx_pps, _non_negative_f(source.get("tx_pps_peak")))
        total_mbps_peak = max(
            rx_mbps + tx_mbps,
            _non_negative_f(source.get("total_mbps_peak")) or (rx_mbps_peak + tx_mbps_peak),
        )
        total_pps_peak = max(
            rx_pps + tx_pps,
            _non_negative_f(source.get("total_pps_peak")) or (rx_pps_peak + tx_pps_peak),
        )
        sample_count = _non_negative_i(source.get("network_sample_count"))
        sample_expected = _non_negative_i(source.get("network_sample_expected"))
        max_gap = _non_negative_f(source.get("network_sample_max_gap_seconds"))
        over = _non_negative_i(source.get("seconds_over_pps"))
        over_mbps = _non_negative_i(source.get("seconds_over_mbps"))
        over_rx = _non_negative_i(source.get("seconds_over_rx_pps"))
        over_tx = _non_negative_i(source.get("seconds_over_tx_pps"))
        quality = _quality(source.get("network_sample_quality"))

        raw_rows.append((
            None, None, vm_uuid, bridge, iface, role, None, sec,
            rx_b, tx_b, rx_p, tx_p, rx_d, tx_d, rx_e, tx_e,
            rx_mbps_peak, tx_mbps_peak, rx_pps_peak, tx_pps_peak,
            _non_negative_f(source.get("rx_packet_size_avg")),
            _non_negative_f(source.get("tx_packet_size_avg")),
            sample_count, sample_expected, max_gap, over, over_mbps, over_rx, over_tx, quality,
        ))

        rec = by_vm.setdefault(vm_uuid, {
            "ifaces": [],
            "public_rx_bytes": 0, "public_tx_bytes": 0,
            "private_rx_bytes": 0, "private_tx_bytes": 0,
            "public_rx_packets": 0, "public_tx_packets": 0,
            "private_rx_packets": 0, "private_tx_packets": 0,
            "rx_packets": 0, "tx_packets": 0,
            "public_rx_mbps": 0.0, "public_tx_mbps": 0.0,
            "private_rx_mbps": 0.0, "private_tx_mbps": 0.0,
            "public_rx_pps": 0.0, "public_tx_pps": 0.0,
            "private_rx_pps": 0.0, "private_tx_pps": 0.0,
            "sample_count": 0, "sample_expected": 0, "sample_max_gap": 0.0,
            "sample_quality": "LEGACY", "seconds_over_pps": 0, "seconds_over_mbps": 0,
            "seconds_over_rx_pps": 0, "seconds_over_tx_pps": 0,
            "drops": 0, "errors": 0,
        })
        rec["ifaces"].append({
            "bridge": bridge, "iface": iface, "role": role, "interval_seconds": sec,
            "rx_bytes": rx_b, "tx_bytes": tx_b, "rx_packets": rx_p, "tx_packets": tx_p,
            "rx_drops": rx_d, "tx_drops": tx_d, "rx_errors": rx_e, "tx_errors": tx_e,
            "rx_mbps_peak": rx_mbps_peak, "tx_mbps_peak": tx_mbps_peak,
            "rx_pps_peak": rx_pps_peak, "tx_pps_peak": tx_pps_peak,
            "total_mbps_peak": total_mbps_peak, "total_pps_peak": total_pps_peak,
            "sample_count": sample_count, "sample_expected": sample_expected,
            "sample_max_gap": max_gap, "sample_quality": quality,
            "seconds_over_pps": over, "seconds_over_mbps": over_mbps,
            "seconds_over_rx_pps": over_rx, "seconds_over_tx_pps": over_tx,
        })
        prefix = role if role in {"public", "private"} else None
        if prefix:
            rec[f"{prefix}_rx_bytes"] += rx_b
            rec[f"{prefix}_tx_bytes"] += tx_b
            rec[f"{prefix}_rx_packets"] += rx_p
            rec[f"{prefix}_tx_packets"] += tx_p
            rec[f"{prefix}_rx_mbps"] += rx_mbps
            rec[f"{prefix}_tx_mbps"] += tx_mbps
            rec[f"{prefix}_rx_pps"] += rx_pps
            rec[f"{prefix}_tx_pps"] += tx_pps
        # Generic VM charts include every interface, even bridges that are not
        # configured as Public or Private.
        rec["rx_packets"] += rx_p
        rec["tx_packets"] += tx_p
        rec["sample_count"] += sample_count
        rec["sample_expected"] += sample_expected
        rec["sample_max_gap"] = max(rec["sample_max_gap"], max_gap)
        if _quality_rank(quality) > _quality_rank(rec["sample_quality"]):
            rec["sample_quality"] = quality
        rec["seconds_over_pps"] += over
        rec["seconds_over_mbps"] += over_mbps
        rec["seconds_over_rx_pps"] = max(rec["seconds_over_rx_pps"], over_rx)
        rec["seconds_over_tx_pps"] = max(rec["seconds_over_tx_pps"], over_tx)
        rec["drops"] += rx_d + tx_d
        rec["errors"] += rx_e + tx_e

    return by_vm, raw_rows


def write_storage_v2(
    conn: Any,
    *,
    node: str,
    bucket: int,
    data_time: int,
    interval_seconds: int,
    interfaces: Iterable[Any],
    public_bridge: str,
    private_bridge: str,
) -> WriteStats:
    """Write chart/raw rows inside the caller's existing transaction."""
    stats = WriteStats(enabled=STORAGE_V2_ENABLED)
    if not STORAGE_V2_ENABLED:
        return stats

    interval_seconds = max(1, _i(interval_seconds, 300))
    net_by_vm, raw_template = _interface_aggregates(
        interfaces, interval_seconds, public_bridge, private_bridge
    )

    if RAW_V2_ENABLED and raw_template:
        raw_rows = []
        for row in raw_template:
            row = list(row)
            row[0] = int(bucket)
            row[1] = node
            row[6] = int(data_time)
            raw_rows.append(tuple(row))
        started = time.perf_counter()
        conn.executemany(
            _upsert_sql(VM_RAW_TABLE, RAW_COLUMNS, ("bucket", "node", "vm_uuid", "bridge", "iface")),
            raw_rows,
        )
        stats.raw_write_ms = (time.perf_counter() - started) * 1000.0
        stats.raw_rows = len(raw_rows)

    current_rows = conn.execute("""
        SELECT
            c.vm_uuid,c.last_seen,c.interval_seconds,c.iface_count,
            c.public_rx_bytes,c.public_tx_bytes,c.private_rx_bytes,c.private_tx_bytes,
            c.rx_bytes,c.tx_bytes,c.total_bytes,
            c.public_mbps,c.private_mbps,c.rx_mbps,c.tx_mbps,c.total_mbps,
            c.public_pps,c.private_pps,c.rx_pps,c.tx_pps,c.total_pps,
            c.public_peak_mbps,c.private_peak_mbps,c.rx_peak_mbps,c.tx_peak_mbps,c.total_peak_mbps,
            c.public_peak_pps,c.private_peak_pps,c.rx_peak_pps,c.tx_peak_pps,c.total_peak_pps,
            c.sample_count,c.sample_expected,c.sample_max_gap,c.sample_quality,
            c.seconds_over_rx_pps,c.seconds_over_tx_pps,c.drops,c.errors,
            c.cpu_full_percent,c.cpu_core_percent,c.vcpu_current,
            c.ram_current_kib,COALESCE(m.ram_maximum_kib,0),c.ram_rss_kib,c.ram_available_kib,
            COALESCE(c.ram_unused_kib,0),COALESCE(c.ram_usable_kib,0),
            c.disk_read_bps,c.disk_write_bps,c.disk_read_iops,c.disk_write_iops
        FROM vm_current_fast c
        LEFT JOIN vm_latest_metrics m ON m.node=c.node AND m.vm_uuid=c.vm_uuid
        WHERE c.node=? AND c.last_seen=?
        ORDER BY c.vm_uuid
    """, (node, data_time)).fetchall()

    chart_rows: list[tuple[Any, ...]] = []
    for row in current_rows:
        (
            vm_uuid,last_push,vm_interval,iface_count,
            public_rx_bytes,public_tx_bytes,private_rx_bytes,private_tx_bytes,
            rx_bytes,tx_bytes,total_bytes,
            public_mbps,private_mbps,rx_mbps,tx_mbps,total_mbps,
            public_pps,private_pps,rx_pps,tx_pps,total_pps,
            public_peak_mbps,private_peak_mbps,rx_peak_mbps,tx_peak_mbps,total_peak_mbps,
            public_peak_pps,private_peak_pps,rx_peak_pps,tx_peak_pps,total_peak_pps,
            sample_count,sample_expected,sample_max_gap,sample_quality,
            seconds_over_rx_pps,seconds_over_tx_pps,drops,errors,
            cpu_full,cpu_core,vcpu,
            ram_current,ram_maximum,ram_rss,ram_available,ram_unused,ram_usable,
            disk_read,disk_write,disk_read_iops,disk_write_iops,
        ) = row
        agg = net_by_vm.get(str(vm_uuid), {})
        public_rx_packets = _i(agg.get("public_rx_packets"), 0)
        public_tx_packets = _i(agg.get("public_tx_packets"), 0)
        private_rx_packets = _i(agg.get("private_rx_packets"), 0)
        private_tx_packets = _i(agg.get("private_tx_packets"), 0)
        all_rx_packets = _i(agg.get("rx_packets"), 0)
        all_tx_packets = _i(agg.get("tx_packets"), 0)
        interfaces_json = json.dumps(agg.get("ifaces", []), separators=(",", ":"), ensure_ascii=False)
        chart_rows.append((
            int(bucket), node, str(vm_uuid), _i(last_push, data_time), max(1, _i(vm_interval, interval_seconds)), _i(iface_count, 0),
            _i(public_rx_bytes, 0), _i(public_tx_bytes, 0), _i(private_rx_bytes, 0), _i(private_tx_bytes, 0),
            _i(rx_bytes, 0), _i(tx_bytes, 0), _i(total_bytes, 0),
            public_rx_packets, public_tx_packets, private_rx_packets, private_tx_packets,
            all_rx_packets, all_tx_packets, all_rx_packets + all_tx_packets,
            _f(agg.get("public_rx_mbps"), 0), _f(agg.get("public_tx_mbps"), 0),
            _f(agg.get("private_rx_mbps"), 0), _f(agg.get("private_tx_mbps"), 0),
            _f(rx_mbps, 0), _f(tx_mbps, 0), _f(total_mbps, 0),
            _f(agg.get("public_rx_pps"), 0), _f(agg.get("public_tx_pps"), 0),
            _f(agg.get("private_rx_pps"), 0), _f(agg.get("private_tx_pps"), 0),
            _f(rx_pps, 0), _f(tx_pps, 0), _f(total_pps, 0),
            _f(public_peak_mbps, 0), _f(private_peak_mbps, 0), _f(rx_peak_mbps, 0),
            _f(tx_peak_mbps, 0), _f(total_peak_mbps, 0),
            _f(public_peak_pps, 0), _f(private_peak_pps, 0), _f(rx_peak_pps, 0),
            _f(tx_peak_pps, 0), _f(total_peak_pps, 0),
            _i(agg.get("sample_count"), sample_count), _i(agg.get("sample_expected"), sample_expected),
            _f(agg.get("sample_max_gap"), sample_max_gap), str(agg.get("sample_quality") or sample_quality or "LEGACY"),
            _i(agg.get("seconds_over_pps"), 0), _i(agg.get("seconds_over_mbps"), 0),
            _i(seconds_over_rx_pps, 0), _i(seconds_over_tx_pps, 0), _i(drops, 0), _i(errors, 0),
            _f(cpu_full, 0), _f(cpu_core, 0), _i(vcpu, 0),
            _i(ram_current, 0), _i(ram_maximum, 0), _i(ram_rss, 0), _i(ram_available, 0),
            _i(ram_unused, 0), _i(ram_usable, 0),
            _f(disk_read, 0), _f(disk_write, 0), _f(disk_read_iops, 0), _f(disk_write_iops, 0),
            interfaces_json,
        ))

    if chart_rows:
        started = time.perf_counter()
        conn.executemany(
            _upsert_sql(VM_CHART_TABLE, VM_CHART_COLUMNS, ("bucket", "node", "vm_uuid")),
            chart_rows,
        )
        stats.chart_write_ms = (time.perf_counter() - started) * 1000.0
        stats.chart_rows = len(chart_rows)

    node_row = conn.execute("""
        SELECT n.last_seen,n.interval_seconds,n.vm_count,n.iface_count,
               n.public_bytes,n.private_bytes,n.total_bytes,
               n.public_packets,n.private_packets,n.total_packets,n.drops,n.errors,
               n.load1,n.load5,n.load15,n.cpu_count,n.cpu_percent,n.mem_total,
               COALESCE(h.mem_available,0),n.mem_used,COALESCE(h.swap_total,0),COALESCE(h.swap_used,0),
               n.disk_read_bps,n.disk_write_bps,n.uptime_seconds
        FROM node_current_fast n
        LEFT JOIN node_host_latest h ON h.node=n.node
        WHERE n.node=? AND n.last_seen=?
    """, (node, data_time)).fetchone()
    if node_row:
        started = time.perf_counter()
        values = (int(bucket), node) + tuple(node_row)
        conn.execute(
            _upsert_sql(NODE_CHART_TABLE, NODE_CHART_COLUMNS, ("bucket", "node")),
            values,
        )
        stats.node_write_ms = (time.perf_counter() - started) * 1000.0
        stats.node_rows = 1

    return stats


def parse_interfaces_json(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [x for x in parsed if isinstance(x, dict)] if isinstance(parsed, list) else []


def storage_v2_status(conn: Any) -> dict[str, Any]:
    """Small health payload used by doctor/health checks and tests."""
    result: dict[str, Any] = {
        "enabled": STORAGE_V2_ENABLED,
        "read_chart_v2": CHART_V2_READ_ENABLED,
        "raw_v2": RAW_V2_ENABLED,
        "tables": {},
    }
    for table in (VM_CHART_TABLE, VM_RAW_TABLE, NODE_CHART_TABLE):
        row = conn.execute(
            "SELECT to_regclass(?) IS NOT NULL, COALESCE((SELECT reltuples::bigint FROM pg_class WHERE oid=to_regclass(?)),0)",
            (f"public.{table}", f"public.{table}"),
        ).fetchone()
        result["tables"][table] = {"exists": bool(row and row[0]), "estimated_rows": _i((row or [0, 0])[1], 0)}
    return result
