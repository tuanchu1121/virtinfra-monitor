#!/usr/bin/env python3
"""Compare legacy history rows with Storage V2 for one VM and time range.

The old tables remain written for compatibility in 50.4.1, making this tool
useful on a fresh deployment after 24-48 hours of traffic. It never changes data.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import math
import os
import psycopg
from psycopg.rows import dict_row


def parse_time(value: str) -> int:
    value = value.strip()
    if value.isdigit():
        return int(value)
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def close(a, b, tolerance):
    a, b = float(a or 0), float(b or 0)
    diff = abs(a-b)
    allowed = max(float(tolerance), abs(a) * float(tolerance) / 100.0)
    return diff <= allowed, diff, (diff / abs(a) * 100.0 if a else (0.0 if b == 0 else math.inf))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", required=True)
    ap.add_argument("--vm-uuid", required=True)
    ap.add_argument("--start", required=True, help="epoch or ISO-8601")
    ap.add_argument("--end", required=True, help="epoch or ISO-8601")
    ap.add_argument("--tolerance", type=float, default=0.01, help="absolute value and percent tolerance")
    args = ap.parse_args()
    dsn = os.environ.get("BW_DATABASE_URL") or os.environ.get("BW_POSTGRES_DSN")
    if not dsn:
        raise SystemExit("BW_DATABASE_URL/BW_POSTGRES_DSN is required")
    start, end = parse_time(args.start), parse_time(args.end)
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        old_net = conn.execute("""
            SELECT bucket,
                   SUM(GREATEST(rx_delta,0)) rx_bytes,SUM(GREATEST(tx_delta,0)) tx_bytes,
                   SUM(GREATEST(rx_packets_delta,0)) rx_packets,SUM(GREATEST(tx_packets_delta,0)) tx_packets,
                   MAX(COALESCE(rx_mbps_peak,0)) rx_peak_mbps,MAX(COALESCE(tx_mbps_peak,0)) tx_peak_mbps,
                   MAX(COALESCE(rx_pps_peak,0)) rx_peak_pps,MAX(COALESCE(tx_pps_peak,0)) tx_peak_pps,
                   SUM(COALESCE(network_sample_count,0)) sample_count,
                   SUM(COALESCE(network_sample_expected,0)) sample_expected,
                   MAX(last_push) last_push,MAX(COALESCE(interval_seconds,300)) interval_seconds
            FROM node_stats
            WHERE node=%s AND vm_uuid=%s AND bucket>=%s AND bucket<%s
            GROUP BY bucket ORDER BY bucket
        """, (args.node,args.vm_uuid,start,end)).fetchall()
        old_perf = conn.execute("""
            SELECT DISTINCT ON (bucket) bucket,cpu_percent,vcpu_current,ram_current_kib,ram_maximum_kib,
                   ram_rss_kib,ram_available_kib,ram_unused_kib,ram_usable_kib,
                   disk_read_delta,disk_write_delta,disk_read_reqs_delta,disk_write_reqs_delta,
                   last_push,COALESCE(interval_seconds,300) interval_seconds
            FROM vm_perf_stats
            WHERE node=%s AND vm_uuid=%s AND bucket>=%s AND bucket<%s
            ORDER BY bucket,time DESC
        """, (args.node,args.vm_uuid,start,end)).fetchall()
        new = conn.execute("""
            SELECT * FROM vm_chart_5m
            WHERE node=%s AND vm_uuid=%s AND bucket>=%s AND bucket<%s
            ORDER BY bucket
        """, (args.node,args.vm_uuid,start,end)).fetchall()
    by_old_net={int(r['bucket']):r for r in old_net}; by_old_perf={int(r['bucket']):r for r in old_perf}; by_new={int(r['bucket']):r for r in new}
    buckets=sorted(set(by_old_net)|set(by_old_perf)|set(by_new))
    checks=0; warnings=0; failures=0
    fields=(
        ('rx_bytes','rx_bytes'),('tx_bytes','tx_bytes'),('rx_packets','rx_packets'),('tx_packets','tx_packets'),
        ('rx_peak_mbps','rx_peak_mbps'),('tx_peak_mbps','tx_peak_mbps'),
        ('rx_peak_pps','rx_peak_pps'),('tx_peak_pps','tx_peak_pps'),
        ('sample_count','sample_count'),('sample_expected','sample_expected'),
    )
    perf_fields=(
        ('cpu_percent','cpu_full_percent'),('ram_current_kib','ram_current_kib'),
        ('ram_maximum_kib','ram_maximum_kib'),('ram_rss_kib','ram_rss_kib'),
        ('ram_available_kib','ram_available_kib'),('ram_unused_kib','ram_unused_kib'),('ram_usable_kib','ram_usable_kib'),
    )
    print(f"Validate node={args.node} vm={args.vm_uuid} range={start}..{end} buckets={len(buckets)}")
    for bucket in buckets:
        on, op, nv = by_old_net.get(bucket), by_old_perf.get(bucket), by_new.get(bucket)
        if not nv or not on or not op:
            failures += 1
            print(f"FAIL bucket={bucket} old_net={bool(on)} old_perf={bool(op)} new={bool(nv)}")
            continue
        for old_name,new_name in fields:
            ok,diff,pct=close(on[old_name],nv[new_name],args.tolerance); checks+=1
            if not ok:
                failures+=1; print(f"FAIL bucket={bucket} metric={new_name} old={on[old_name]} new={nv[new_name]} diff={diff} pct={pct}")
        for old_name,new_name in perf_fields:
            old_value=op[old_name]
            if old_name=='cpu_percent':
                raw=float(old_value or 0); vcpu=max(1,int(op['vcpu_current'] or 0)); old_value=min(100.0,raw/vcpu) if raw>100 else min(100.0,raw)
            ok,diff,pct=close(old_value,nv[new_name],args.tolerance); checks+=1
            if not ok:
                failures+=1; print(f"FAIL bucket={bucket} metric={new_name} old={old_value} new={nv[new_name]} diff={diff} pct={pct}")
        interval=max(1,int(op['interval_seconds'] or 300))
        derived=(('disk_read_bps',float(op['disk_read_delta'] or 0)/interval),('disk_write_bps',float(op['disk_write_delta'] or 0)/interval),('disk_read_iops',float(op['disk_read_reqs_delta'] or 0)/interval),('disk_write_iops',float(op['disk_write_reqs_delta'] or 0)/interval))
        for name,old_value in derived:
            ok,diff,pct=close(old_value,nv[name],args.tolerance); checks+=1
            if not ok:
                failures+=1; print(f"FAIL bucket={bucket} metric={name} old={old_value} new={nv[name]} diff={diff} pct={pct}")
    status='PASS' if failures==0 else 'FAIL'
    print(f"{status}: checks={checks} warnings={warnings} failures={failures} old_net={len(old_net)} old_perf={len(old_perf)} new={len(new)}")
    return 0 if failures==0 else 2

if __name__ == '__main__':
    raise SystemExit(main())
