#!/usr/bin/env python3
"""Read-only before/after query benchmark for legacy history versus Storage V2."""
from __future__ import annotations
import argparse
import json
import os
import statistics
import time
import psycopg


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--node',required=True); ap.add_argument('--vm-uuid',required=True)
    ap.add_argument('--start',type=int,required=True); ap.add_argument('--end',type=int,required=True)
    ap.add_argument('--runs',type=int,default=5)
    args=ap.parse_args()
    dsn=os.environ.get('BW_DATABASE_URL') or os.environ.get('BW_POSTGRES_DSN')
    if not dsn: raise SystemExit('BW_DATABASE_URL/BW_POSTGRES_DSN is required')
    queries={
      'legacy_network':("""SELECT bucket,SUM(rx_delta),SUM(tx_delta),SUM(rx_packets_delta),SUM(tx_packets_delta),MAX(last_push) FROM node_stats WHERE node=%s AND vm_uuid=%s AND bucket>=%s AND bucket<%s GROUP BY bucket ORDER BY bucket""",(args.node,args.vm_uuid,args.start,args.end)),
      'v2_network':("""SELECT bucket,rx_bytes,tx_bytes,rx_packets,tx_packets,last_push FROM vm_chart_5m WHERE node=%s AND vm_uuid=%s AND bucket>=%s AND bucket<%s ORDER BY bucket""",(args.node,args.vm_uuid,args.start,args.end)),
      'legacy_perf':("""SELECT bucket,cpu_percent,ram_current_kib,disk_read_delta,disk_write_delta,last_push FROM vm_perf_stats WHERE node=%s AND vm_uuid=%s AND bucket>=%s AND bucket<%s ORDER BY bucket,time""",(args.node,args.vm_uuid,args.start,args.end)),
      'v2_perf':("""SELECT bucket,cpu_full_percent,ram_current_kib,disk_read_bps,disk_write_bps,last_push FROM vm_chart_5m WHERE node=%s AND vm_uuid=%s AND bucket>=%s AND bucket<%s ORDER BY bucket""",(args.node,args.vm_uuid,args.start,args.end)),
    }
    out={}
    with psycopg.connect(dsn) as conn:
      conn.execute('SET TRANSACTION READ ONLY')
      for name,(sql,params) in queries.items():
        times=[]; rows=0
        for _ in range(max(1,args.runs)):
          t=time.perf_counter(); data=conn.execute(sql,params).fetchall(); times.append((time.perf_counter()-t)*1000); rows=len(data)
        plan=conn.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+sql,params).fetchone()[0]
        out[name]={'runs_ms':times,'median_ms':statistics.median(times),'min_ms':min(times),'max_ms':max(times),'rows':rows,'plan':plan}
      sizes=conn.execute("""SELECT relname,pg_total_relation_size(oid) FROM pg_class WHERE oid IN (to_regclass('node_stats'),to_regclass('vm_perf_stats'),to_regclass('vm_chart_5m'),to_regclass('vm_raw_detail_5m')) ORDER BY relname""").fetchall()
      out['sizes_bytes']={name:size for name,size in sizes}
    print(json.dumps(out,indent=2,default=str))
    return 0
if __name__=='__main__': raise SystemExit(main())
