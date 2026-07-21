# Release: 50.5.9-prod-r20-consumption-node-vm-rollup-alignment-hotfix
# Additive Consumption-only layer. Dashboard, Agent payload/cadence, Abuse,
# Storage I/O, Queue, RBAC and existing per-VM rollups remain unchanged.

import math as _r20_math
import threading as _r20_threading
import node_groups as _r20_node_groups

V5060_RELEASE = "50.5.9-prod-r20-consumption-node-vm-rollup-alignment-hotfix"
V5060_ROLLUP_RETENTION_SECONDS = 8 * 86400

_r20_schema_ready = False
_r20_schema_lock = _r20_threading.RLock()
_r20_db_base = db

def _r20_schema_exists(conn):
    try:
        conn.execute("SELECT 1 FROM node_vm_consumption_hourly LIMIT 0")
        conn.execute("SELECT 1 FROM node_vm_consumption_daily LIMIT 0")
        return True
    except Exception:
        return False

def _r20_ensure_schema(conn):
    # Migration 014 is authoritative in production. This fallback is reached
    # only by disposable/dev runtimes that did not run the installer migration.
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS node_vm_consumption_hourly (
      hour_start INTEGER NOT NULL,node TEXT NOT NULL,
      vm_public_rx_bytes INTEGER NOT NULL DEFAULT 0,
      vm_public_tx_bytes INTEGER NOT NULL DEFAULT 0,
      vm_private_rx_bytes INTEGER NOT NULL DEFAULT 0,
      vm_private_tx_bytes INTEGER NOT NULL DEFAULT 0,
      coverage_seconds INTEGER NOT NULL DEFAULT 0,
      sample_count INTEGER NOT NULL DEFAULT 0,
      vm_count INTEGER NOT NULL DEFAULT 0,
      last_push INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(hour_start,node)
    );
    CREATE TABLE IF NOT EXISTS node_vm_consumption_daily (
      day_start INTEGER NOT NULL,node TEXT NOT NULL,
      vm_public_rx_bytes INTEGER NOT NULL DEFAULT 0,
      vm_public_tx_bytes INTEGER NOT NULL DEFAULT 0,
      vm_private_rx_bytes INTEGER NOT NULL DEFAULT 0,
      vm_private_tx_bytes INTEGER NOT NULL DEFAULT 0,
      coverage_seconds INTEGER NOT NULL DEFAULT 0,
      sample_count INTEGER NOT NULL DEFAULT 0,
      vm_count INTEGER NOT NULL DEFAULT 0,
      last_push INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(day_start,node)
    );
    CREATE INDEX IF NOT EXISTS idx_node_vm_consumption_hourly_node_time
      ON node_vm_consumption_hourly(node,hour_start);
    CREATE INDEX IF NOT EXISTS idx_node_vm_consumption_daily_node_time
      ON node_vm_consumption_daily(node,day_start);
    """)
    conn.commit()

def db():
    global _r20_schema_ready
    conn = _r20_db_base()
    if not _r20_schema_ready:
        with _r20_schema_lock:
            if not _r20_schema_ready:
                if not _r20_schema_exists(conn):
                    _r20_ensure_schema(conn)
                _r20_schema_ready = True
    return conn

# The existing native COPY stage already contains one accepted push. Merge one
# compact All-VM row per Node into the same transaction as raw/per-VM writes.
_r20_iface_copy_base = _v5052_write_interface_copy_batch

def _r20_merge_node_vm_rollups(conn):
    values = (PUBLIC_BRIDGE, PUBLIC_BRIDGE, PRIVATE_BRIDGE, PRIVATE_BRIDGE)
    conn.execute("""
      WITH grouped AS (
        SELECT hour_start,node,
          SUM(CASE WHEN bridge=? THEN tx_delta ELSE 0 END)::bigint vm_public_rx,
          SUM(CASE WHEN bridge=? THEN rx_delta ELSE 0 END)::bigint vm_public_tx,
          SUM(CASE WHEN bridge=? THEN tx_delta ELSE 0 END)::bigint vm_private_rx,
          SUM(CASE WHEN bridge=? THEN rx_delta ELSE 0 END)::bigint vm_private_tx,
          MAX(interval_seconds)::bigint coverage_seconds,
          COUNT(DISTINCT last_push)::bigint sample_count,
          COUNT(DISTINCT vm_uuid)::bigint vm_count,
          MAX(last_push)::bigint last_push
        FROM pg_temp.vi5052_iface_stage GROUP BY hour_start,node
      )
      INSERT INTO node_vm_consumption_hourly(
        hour_start,node,vm_public_rx_bytes,vm_public_tx_bytes,
        vm_private_rx_bytes,vm_private_tx_bytes,
        coverage_seconds,sample_count,vm_count,last_push)
      SELECT hour_start,node,vm_public_rx,vm_public_tx,vm_private_rx,vm_private_tx,
             coverage_seconds,sample_count,vm_count,last_push FROM grouped
      ON CONFLICT(hour_start,node) DO UPDATE SET
        vm_public_rx_bytes=node_vm_consumption_hourly.vm_public_rx_bytes+excluded.vm_public_rx_bytes,
        vm_public_tx_bytes=node_vm_consumption_hourly.vm_public_tx_bytes+excluded.vm_public_tx_bytes,
        vm_private_rx_bytes=node_vm_consumption_hourly.vm_private_rx_bytes+excluded.vm_private_rx_bytes,
        vm_private_tx_bytes=node_vm_consumption_hourly.vm_private_tx_bytes+excluded.vm_private_tx_bytes,
        coverage_seconds=LEAST(3600,node_vm_consumption_hourly.coverage_seconds+excluded.coverage_seconds),
        sample_count=node_vm_consumption_hourly.sample_count+excluded.sample_count,
        vm_count=GREATEST(node_vm_consumption_hourly.vm_count,excluded.vm_count),
        last_push=GREATEST(node_vm_consumption_hourly.last_push,excluded.last_push)
    """, values)
    conn.execute("""
      WITH grouped AS (
        SELECT day_start,node,
          SUM(CASE WHEN bridge=? THEN tx_delta ELSE 0 END)::bigint vm_public_rx,
          SUM(CASE WHEN bridge=? THEN rx_delta ELSE 0 END)::bigint vm_public_tx,
          SUM(CASE WHEN bridge=? THEN tx_delta ELSE 0 END)::bigint vm_private_rx,
          SUM(CASE WHEN bridge=? THEN rx_delta ELSE 0 END)::bigint vm_private_tx,
          MAX(interval_seconds)::bigint coverage_seconds,
          COUNT(DISTINCT last_push)::bigint sample_count,
          COUNT(DISTINCT vm_uuid)::bigint vm_count,
          MAX(last_push)::bigint last_push
        FROM pg_temp.vi5052_iface_stage GROUP BY day_start,node
      )
      INSERT INTO node_vm_consumption_daily(
        day_start,node,vm_public_rx_bytes,vm_public_tx_bytes,
        vm_private_rx_bytes,vm_private_tx_bytes,
        coverage_seconds,sample_count,vm_count,last_push)
      SELECT day_start,node,vm_public_rx,vm_public_tx,vm_private_rx,vm_private_tx,
             coverage_seconds,sample_count,vm_count,last_push FROM grouped
      ON CONFLICT(day_start,node) DO UPDATE SET
        vm_public_rx_bytes=node_vm_consumption_daily.vm_public_rx_bytes+excluded.vm_public_rx_bytes,
        vm_public_tx_bytes=node_vm_consumption_daily.vm_public_tx_bytes+excluded.vm_public_tx_bytes,
        vm_private_rx_bytes=node_vm_consumption_daily.vm_private_rx_bytes+excluded.vm_private_rx_bytes,
        vm_private_tx_bytes=node_vm_consumption_daily.vm_private_tx_bytes+excluded.vm_private_tx_bytes,
        coverage_seconds=LEAST(86400,node_vm_consumption_daily.coverage_seconds+excluded.coverage_seconds),
        sample_count=node_vm_consumption_daily.sample_count+excluded.sample_count,
        vm_count=GREATEST(node_vm_consumption_daily.vm_count,excluded.vm_count),
        last_push=GREATEST(node_vm_consumption_daily.last_push,excluded.last_push)
    """, values)

def _v5052_write_interface_copy_batch(conn,node,data_time,bucket,interval_seconds,interfaces):
    result = _r20_iface_copy_base(conn,node,data_time,bucket,interval_seconds,interfaces)
    if safe_int((result or {}).get("rows"),0) > 0:
        _r20_merge_node_vm_rollups(conn)
    return result

def _r20_ceil_hour(ts):
    base = local_hour_start(ts)
    return base if safe_int(ts,0) == base else base + 3600

def _r20_physical_raw(start,end,selected_node=""):
    return _v5058c_raw_node_branch(start,end,selected_node)

def _r20_physical_hourly(start,end,selected_node=""):
    clause = " AND node=?" if selected_node else ""
    return """SELECT node,physical_public_rx_bytes::bigint physical_public_rx,
      physical_public_tx_bytes::bigint physical_public_tx,
      physical_private_rx_bytes::bigint physical_private_rx,
      physical_private_tx_bytes::bigint physical_private_tx,
      coverage_seconds::bigint coverage_seconds,last_push::bigint latest_sample
      FROM node_consumption_hourly WHERE hour_start>=? AND hour_start<?%s""" % clause, [start,end]+([selected_node] if selected_node else [])

def _r20_physical_daily(start,end,selected_node=""):
    clause = " AND node=?" if selected_node else ""
    return """SELECT node,physical_public_rx_bytes::bigint physical_public_rx,
      physical_public_tx_bytes::bigint physical_public_tx,
      physical_private_rx_bytes::bigint physical_private_rx,
      physical_private_tx_bytes::bigint physical_private_tx,
      coverage_seconds::bigint coverage_seconds,last_push::bigint latest_sample
      FROM node_consumption_daily WHERE day_start>=? AND day_start<?%s""" % clause, [start,end]+([selected_node] if selected_node else [])

def _r20_vm_node_raw(start,end,selected_node=""):
    clause = " AND ns.node=?" if selected_node else ""
    sql = """SELECT ns.node,
      COALESCE(SUM(CASE WHEN ns.bridge=? THEN ns.tx_delta ELSE 0 END),0)::bigint vm_public_rx,
      COALESCE(SUM(CASE WHEN ns.bridge=? THEN ns.rx_delta ELSE 0 END),0)::bigint vm_public_tx,
      COALESCE(SUM(CASE WHEN ns.bridge=? THEN ns.tx_delta ELSE 0 END),0)::bigint vm_private_rx,
      COALESCE(SUM(CASE WHEN ns.bridge=? THEN ns.rx_delta ELSE 0 END),0)::bigint vm_private_tx,
      COALESCE(MAX(ns.interval_seconds),0)::bigint coverage_seconds,
      COUNT(DISTINCT ns.vm_uuid)::bigint vm_count,
      COALESCE(MAX(ns.last_push),0)::bigint latest_sample
      FROM node_stats ns WHERE ns.last_push>=? AND ns.last_push<?%s
      GROUP BY ns.node,ns.bucket""" % clause
    return sql,[PUBLIC_BRIDGE,PUBLIC_BRIDGE,PRIVATE_BRIDGE,PRIVATE_BRIDGE,start,end]+([selected_node] if selected_node else [])

def _r20_vm_node_hourly(start,end,selected_node=""):
    clause = " AND node=?" if selected_node else ""
    return """SELECT node,vm_public_rx_bytes::bigint vm_public_rx,
      vm_public_tx_bytes::bigint vm_public_tx,vm_private_rx_bytes::bigint vm_private_rx,
      vm_private_tx_bytes::bigint vm_private_tx,coverage_seconds::bigint coverage_seconds,
      vm_count::bigint vm_count,last_push::bigint latest_sample
      FROM node_vm_consumption_hourly WHERE hour_start>=? AND hour_start<?%s""" % clause,[start,end]+([selected_node] if selected_node else [])

def _r20_vm_node_daily(start,end,selected_node=""):
    clause = " AND node=?" if selected_node else ""
    return """SELECT node,vm_public_rx_bytes::bigint vm_public_rx,
      vm_public_tx_bytes::bigint vm_public_tx,vm_private_rx_bytes::bigint vm_private_rx,
      vm_private_tx_bytes::bigint vm_private_tx,coverage_seconds::bigint coverage_seconds,
      vm_count::bigint vm_count,last_push::bigint latest_sample
      FROM node_vm_consumption_daily WHERE day_start>=? AND day_start<?%s""" % clause,[start,end]+([selected_node] if selected_node else [])

def _r20_tiered_source(start,end,selected_node,raw_fn,hourly_fn,daily_fn):
    start,end=safe_int(start,0),safe_int(end,0)
    branches,params=[],[]
    first_day=local_day_start(start)
    full_day_start=first_day if start==first_day else first_day+86400
    full_day_end=local_day_start(end)
    edges=[(start,end)]
    if full_day_start<full_day_end:
        sql,values=daily_fn(full_day_start,full_day_end,selected_node); branches.append(sql); params.extend(values)
        edges=[(start,full_day_start),(full_day_end,end)]
    for edge_start,edge_end in edges:
        if edge_end<=edge_start: continue
        full_hour_start=_r20_ceil_hour(edge_start); full_hour_end=local_hour_start(edge_end)
        if full_hour_start>=full_hour_end:
            sql,values=raw_fn(edge_start,edge_end,selected_node); branches.append(sql); params.extend(values); continue
        if edge_start<full_hour_start:
            sql,values=raw_fn(edge_start,full_hour_start,selected_node); branches.append(sql); params.extend(values)
        sql,values=hourly_fn(full_hour_start,full_hour_end,selected_node); branches.append(sql); params.extend(values)
        if full_hour_end<edge_end:
            sql,values=raw_fn(full_hour_end,edge_end,selected_node); branches.append(sql); params.extend(values)
    return " UNION ALL ".join(branches),params

def _r20_selected_group_id():
    try:return safe_int(_r20_node_groups.selected_group_id(),0)
    except Exception:return 0

def _v5058c_node_ctes(start,end,selected_node=""):
    physical_sql,physical_params=_r20_tiered_source(start,end,selected_node,_r20_physical_raw,_r20_physical_hourly,_r20_physical_daily)
    vm_sql,vm_params=_r20_tiered_source(start,end,selected_node,_r20_vm_node_raw,_r20_vm_node_hourly,_r20_vm_node_daily)
    node_filter=" AND ni.node=?" if selected_node else ""
    expected=max(1,safe_int(end,0)-safe_int(start,0))
    sql="""WITH physical_parts AS (%s),vm_parts AS (%s),
      physical_agg AS (
        SELECT node,SUM(physical_public_rx)::bigint physical_public_rx,
          SUM(physical_public_tx)::bigint physical_public_tx,
          SUM(physical_private_rx)::bigint physical_private_rx,
          SUM(physical_private_tx)::bigint physical_private_tx,
          LEAST(?,SUM(coverage_seconds))::bigint coverage_seconds,
          MAX(latest_sample)::bigint latest_sample FROM physical_parts GROUP BY node),
      vm_node_agg AS (
        SELECT node,SUM(vm_public_rx)::bigint vm_public_rx,
          SUM(vm_public_tx)::bigint vm_public_tx,
          SUM(vm_private_rx)::bigint vm_private_rx,
          SUM(vm_private_tx)::bigint vm_private_tx,
          LEAST(?,SUM(coverage_seconds))::bigint coverage_seconds,
          MAX(vm_count)::bigint vm_count,MAX(latest_sample)::bigint latest_sample
          FROM vm_parts GROUP BY node),
      node_meta AS (
        SELECT ni.node,COALESCE(MAX(CASE WHEN LOWER(COALESCE(ba.role,''))='public' THEN ba.primary_ipv4 END),'') node_ip,
          MAX(CASE WHEN LOWER(COALESCE(pn.role,''))='public' THEN 1 ELSE 0 END)::integer public_configured,
          MAX(CASE WHEN LOWER(COALESCE(pn.role,''))='private' THEN 1 ELSE 0 END)::integer private_configured,
          MAX(CASE WHEN LOWER(COALESCE(ba.role,''))='public' THEN 1 ELSE 0 END)::integer public_addressed,
          MAX(CASE WHEN LOWER(COALESCE(ba.role,''))='private' THEN 1 ELSE 0 END)::integer private_addressed
        FROM node_inventory ni
        JOIN node_group_memberships gm_visible ON gm_visible.node=ni.node
        JOIN node_groups ng_visible ON ng_visible.id=gm_visible.group_id AND ng_visible.is_active=1
        LEFT JOIN node_bridge_addresses_latest ba ON ba.node=ni.node
        LEFT JOIN node_physical_net_latest pn ON pn.node=ni.node
        WHERE COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL%s GROUP BY ni.node),
      node_rows AS (
        SELECT m.node,m.node_ip,GREATEST(m.public_configured,m.public_addressed) public_configured,
          GREATEST(m.private_configured,m.private_addressed) private_configured,
          COALESCE(p.physical_public_rx,0)::bigint physical_public_rx,
          COALESCE(p.physical_public_tx,0)::bigint physical_public_tx,
          (COALESCE(p.physical_public_rx,0)+COALESCE(p.physical_public_tx,0))::bigint physical_public_total,
          COALESCE(v.vm_public_rx,0)::bigint vm_public_rx,COALESCE(v.vm_public_tx,0)::bigint vm_public_tx,
          (COALESCE(v.vm_public_rx,0)+COALESCE(v.vm_public_tx,0))::bigint vm_public_total,
          ((COALESCE(p.physical_public_rx,0)+COALESCE(p.physical_public_tx,0))-(COALESCE(v.vm_public_rx,0)+COALESCE(v.vm_public_tx,0)))::bigint public_difference,
          COALESCE(p.physical_private_rx,0)::bigint physical_private_rx,
          COALESCE(p.physical_private_tx,0)::bigint physical_private_tx,
          (COALESCE(p.physical_private_rx,0)+COALESCE(p.physical_private_tx,0))::bigint physical_private_total,
          COALESCE(v.vm_private_rx,0)::bigint vm_private_rx,COALESCE(v.vm_private_tx,0)::bigint vm_private_tx,
          (COALESCE(v.vm_private_rx,0)+COALESCE(v.vm_private_tx,0))::bigint vm_private_total,
          ((COALESCE(p.physical_private_rx,0)+COALESCE(p.physical_private_tx,0))-(COALESCE(v.vm_private_rx,0)+COALESCE(v.vm_private_tx,0)))::bigint private_difference,
          COALESCE(v.vm_count,0)::bigint vm_count,
          LEAST(100.0,LEAST(COALESCE(p.coverage_seconds,0),COALESCE(v.coverage_seconds,0))*100.0/?) coverage_percent,
          GREATEST(COALESCE(p.latest_sample,0),COALESCE(v.latest_sample,0))::bigint latest_sample
        FROM node_meta m LEFT JOIN physical_agg p ON p.node=m.node LEFT JOIN vm_node_agg v ON v.node=m.node)
    """%(physical_sql,vm_sql,node_filter)
    params=list(physical_params)+list(vm_params)+[expected,expected]
    if selected_node:params.append(selected_node)
    params.append(expected)
    return sql,params

V5058C_NODE_SORTS.update({
 "vm_public_rx":"vm_public_rx","vm_public_tx":"vm_public_tx","vm_public_total":"vm_public_total",
 "public_difference":"public_difference","vm_private_rx":"vm_private_rx","vm_private_tx":"vm_private_tx",
 "vm_private_total":"vm_private_total","private_difference":"private_difference","vm_count":"vm_count"})

def _v5058c_node_rows(start,end,q,coverage,sort_by,order,page_no,limit):
    ctes,params=_v5058c_node_ctes(start,end); search_sql,search_params=_v5058c_search_clause("node",q)
    gid=_r20_selected_group_id(); group_sql=""; group_params=[]
    if gid:
        group_sql=" AND EXISTS (SELECT 1 FROM node_group_memberships gm JOIN node_groups ng ON ng.id=gm.group_id AND ng.is_active=1 WHERE gm.node=node_rows.node AND gm.group_id=?)"; group_params=[gid]
    where=" WHERE 1=1"+search_sql+_v5058c_coverage_clause(coverage)+group_sql
    col=V5058C_NODE_SORTS.get(sort_by,"physical_public_total"); tie="ASC" if sort_by=="node" and order=="asc" else "DESC"; page_no=max(1,page_no)
    select="""SELECT node,node_ip,public_configured,private_configured,
      physical_public_rx,physical_public_tx,physical_public_total,
      vm_public_rx,vm_public_tx,vm_public_total,public_difference,
      physical_private_rx,physical_private_tx,physical_private_total,
      vm_private_rx,vm_private_tx,vm_private_total,private_difference,
      vm_count,coverage_percent,latest_sample,COUNT(*) OVER() total_count FROM node_rows"""
    def fetch(offset):
        conn=db()
        try:return conn.execute(ctes+select+where+" ORDER BY %s %s,node %s LIMIT ? OFFSET ?"%(col,order.upper(),tie),params+search_params+group_params+[limit,offset]).fetchall()
        finally:conn.close()
    raw=fetch((page_no-1)*limit)
    if not raw and page_no>1:page_no=1;raw=fetch(0)
    total=safe_int(raw[0][-1] if raw else 0,0);max_page=max(1,int(_r20_math.ceil(total/float(max(1,limit)))))
    return [tuple(r[:-1]) for r in raw],total,page_no,max_page

def _r20_totals(start,end,selected_node=""):
    ctes,params=_v5058c_node_ctes(start,end,selected_node);gid=_r20_selected_group_id();where="";extra=[]
    if gid:where=" WHERE EXISTS (SELECT 1 FROM node_group_memberships gm JOIN node_groups ng ON ng.id=gm.group_id AND ng.is_active=1 WHERE gm.node=node_rows.node AND gm.group_id=?)";extra=[gid]
    conn=db()
    try:
        row=conn.execute(ctes+"""SELECT COALESCE(SUM(physical_public_rx),0),COALESCE(SUM(physical_public_tx),0),
          COALESCE(SUM(physical_private_rx),0),COALESCE(SUM(physical_private_tx),0),
          COALESCE(SUM(vm_public_rx),0),COALESCE(SUM(vm_public_tx),0),
          COALESCE(SUM(vm_private_rx),0),COALESCE(SUM(vm_private_tx),0) FROM node_rows"""+where,params+extra).fetchone()
        return tuple(safe_int(v,0) for v in (row or (0,)*8))
    finally:conn.close()

def _v5058c_node_totals(start,end,selected_node=""):
    v=_r20_totals(start,end,selected_node);return {"physical_public_rx":v[0],"physical_public_tx":v[1],"physical_private_rx":v[2],"physical_private_tx":v[3]}

def _v5058c_vm_totals(start,end,selected_node=""):
    v=_r20_totals(start,end,selected_node);return {"vm_public_rx":v[4],"vm_public_tx":v[5],"vm_private_rx":v[6],"vm_private_tx":v[7]}

def _r20_signed_bytes(value):
    value=safe_int(value,0);return ("+" if value>0 else "-" if value<0 else "")+_v5058c_bytes(abs(value))

V5060_CONSUMPTION_CSS=r'''<style id="v5060-consumption-node-alignment">
body.endpoint-bandwidth-consumption-page .v5060-node-table{min-width:2260px!important;table-layout:fixed!important}
body.endpoint-bandwidth-consumption-page .v5060-group-table{min-width:2360px!important;table-layout:fixed!important}
.v5058c-table.v5060-node-table th,.v5058c-table.v5060-node-table td,.v5058c-table.v5060-group-table th,.v5058c-table.v5060-group-table td{vertical-align:middle!important;box-sizing:border-box}
.v5058c-table.v5060-node-table th,.v5058c-table.v5060-group-table th{text-align:center!important;white-space:nowrap}
.v5058c-table.v5060-node-table td,.v5058c-table.v5060-group-table td{text-align:right!important;white-space:nowrap;font-variant-numeric:tabular-nums}
.v5058c-table.v5060-node-table th:first-child,.v5058c-table.v5060-node-table td.v5060-node,.v5058c-table.v5060-group-table th:first-child,.v5058c-table.v5060-group-table td.v5060-group{text-align:left!important}
.v5060-node-table td.v5060-node,.v5060-group-table td.v5060-group{white-space:normal!important}
.v5060-node-table col.c-id{width:190px}.v5060-group-table col.c-id{width:210px}
.v5060-node-table col.c-count,.v5060-group-table col.c-count{width:78px}.v5060-node-table col.c-metric,.v5060-group-table col.c-metric{width:108px}
.v5060-node-table col.c-diff,.v5060-group-table col.c-diff{width:122px}.v5060-node-table col.c-cover,.v5060-group-table col.c-cover{width:90px}
.v5060-node-table col.c-latest,.v5060-group-table col.c-latest{width:135px}.v5060-diff.positive{color:var(--warn,#d59b36)}.v5060-diff.negative{color:var(--crit,#d66)}
.v5060-drill{display:block;margin-top:3px;font-size:11px;font-weight:600}</style>'''

def _v5058c_node_table(rows,common,sort_by,order):
    h=lambda label,key:_v5058c_sort_link(label,key,"node",common,sort_by,order);body=[]
    for row in rows:
        (node,node_ip,pub_cfg,priv_cfg,pp_rx,pp_tx,pp_total,vp_rx,vp_tx,vp_total,pdiff,pr_rx,pr_tx,pr_total,vr_rx,vr_tx,vr_total,rdiff,vm_count,coverage,latest)=row
        node_href=url_for("node_page",node=node,period="5m")
        drill=url_for("bandwidth_consumption_page",tab="vm",period=common.get("period","24h"),node=node,sort="public_total",order="desc")
        dpc="positive" if pdiff>0 else "negative" if pdiff<0 else "";drc="positive" if rdiff>0 else "negative" if rdiff<0 else ""
        body.append("""<tr><td class="v5060-node"><a href="%s"><b>%s</b></a><small>%s</small><a class="v5060-drill" href="%s">VM consumption →</a></td><td>%s</td>
          <td>%s</td><td>%s</td><td class="v5058c-total">%s</td><td>%s</td><td>%s</td><td class="v5058c-total">%s</td><td class="v5060-diff %s">%s</td>
          <td>%s</td><td>%s</td><td class="v5058c-total">%s</td><td>%s</td><td>%s</td><td class="v5058c-total">%s</td><td class="v5060-diff %s">%s</td><td>%s</td><td class="v5058c-latest">%s</td></tr>"""%(
          escape(node_href,quote=True),escape(node),escape(compact_ipv4(node_ip) or "-"),escape(drill,quote=True),f"{safe_int(vm_count,0):,}",
          _v5058c_metric_cell(pp_rx,bool(pub_cfg),"public"),_v5058c_metric_cell(pp_tx,bool(pub_cfg),"public"),_v5058c_metric_cell(pp_total,bool(pub_cfg)),
          _v5058c_metric_cell(vp_rx,bool(pub_cfg),"public"),_v5058c_metric_cell(vp_tx,bool(pub_cfg),"public"),_v5058c_metric_cell(vp_total,bool(pub_cfg)),dpc,_r20_signed_bytes(pdiff),
          _v5058c_metric_cell(pr_rx,bool(priv_cfg),"private"),_v5058c_metric_cell(pr_tx,bool(priv_cfg),"private"),_v5058c_metric_cell(pr_total,bool(priv_cfg)),
          _v5058c_metric_cell(vr_rx,bool(priv_cfg),"private"),_v5058c_metric_cell(vr_tx,bool(priv_cfg),"private"),_v5058c_metric_cell(vr_total,bool(priv_cfg)),drc,_r20_signed_bytes(rdiff),
          _v5058c_coverage_cell(coverage,latest),_v5058c_latest_cell(latest)))
    if not body:body.append('<tr><td colspan="18" class="empty">No node matches the selected filters.</td></tr>')
    cols='<colgroup><col class="c-id"><col class="c-count">'+'<col class="c-metric">'*6+'<col class="c-diff">'+'<col class="c-metric">'*6+'<col class="c-diff"><col class="c-cover"><col class="c-latest"></colgroup>'
    return V5060_CONSUMPTION_CSS+'''<div class="table-wrap v5058c-table-wrap"><table class="v5058c-table v5058c-node-table v5060-node-table">%s<thead><tr><th rowspan="2">%s</th><th rowspan="2">%s</th><th colspan="3">PHYSICAL PUBLIC</th><th colspan="3">ALL VM PUBLIC</th><th rowspan="2">%s</th><th colspan="3">PHYSICAL PRIVATE</th><th colspan="3">ALL VM PRIVATE</th><th rowspan="2">%s</th><th rowspan="2">%s</th><th rowspan="2">%s</th></tr><tr><th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr></thead><tbody>%s</tbody></table></div>'''%(
      cols,h("Node / Node IP","node"),h("VMs","vm_count"),h("Public Diff","public_difference"),h("Private Diff","private_difference"),h("Coverage","coverage"),h("Latest Sample","latest_sample"),
      h("RX","physical_public_rx"),h("TX","physical_public_tx"),h("Total","physical_public_total"),h("RX","vm_public_rx"),h("TX","vm_public_tx"),h("Total","vm_public_total"),
      h("RX","physical_private_rx"),h("TX","physical_private_tx"),h("Total","physical_private_total"),h("RX","vm_private_rx"),h("TX","vm_private_tx"),h("Total","vm_private_total"),"".join(body))

def _r20_group_page():
    period=_v5058c_period(request.args.get("period"));_label,seconds=V5058C_PERIODS[period];end=now_ts();start=end-seconds;selected=_r20_selected_group_id()
    ctes,params=_v5058c_node_ctes(start,end);conn=db()
    try:
        data={safe_int(r[0],0):tuple(r[1:]) for r in conn.execute(ctes+"""SELECT gm.group_id,COUNT(*),SUM(vm_count),
          SUM(physical_public_rx),SUM(physical_public_tx),SUM(physical_public_total),SUM(vm_public_rx),SUM(vm_public_tx),SUM(vm_public_total),SUM(public_difference),
          SUM(physical_private_rx),SUM(physical_private_tx),SUM(physical_private_total),SUM(vm_private_rx),SUM(vm_private_tx),SUM(vm_private_total),SUM(private_difference),AVG(coverage_percent),MAX(latest_sample)
          FROM node_rows JOIN node_group_memberships gm ON gm.node=node_rows.node JOIN node_groups ng ON ng.id=gm.group_id AND ng.is_active=1 GROUP BY gm.group_id""",params).fetchall()}
    finally:conn.close()
    rows=[]
    for g in _r20_node_groups.all_group_rows(visibility="active"):
        gid,name,_desc,country,_active,_system,_nodes,_vms,*_=g;gid=safe_int(gid,0)
        if selected and gid!=selected:continue
        v=data.get(gid,(0,)*18);node_count,vm_count,*vals=v;vals=list(vals)
        pdiff=safe_int(vals[6],0);rdiff=safe_int(vals[13],0);coverage=safe_float(vals[14],0);latest=safe_int(vals[15],0)
        href=url_for("bandwidth_consumption_page",tab="node",period=period,group=gid)
        cells=''.join('<td>%s</td>'%_v5058c_bytes(safe_int(x,0)) for x in vals[0:6])
        cells+='<td class="v5060-diff %s">%s</td>'%(("positive" if pdiff>0 else "negative" if pdiff<0 else ""),_r20_signed_bytes(pdiff))
        cells+=''.join('<td>%s</td>'%_v5058c_bytes(safe_int(x,0)) for x in vals[7:13])
        cells+='<td class="v5060-diff %s">%s</td>'%(("positive" if rdiff>0 else "negative" if rdiff<0 else ""),_r20_signed_bytes(rdiff))
        rows.append('<tr><td class="v5060-group"><a href="%s"><b>%s%s</b></a></td><td>%s</td><td>%s</td>%s<td>%s</td><td class="v5058c-latest">%s</td></tr>'%(
          escape(href,quote=True),_r20_node_groups.flag_html(country),escape(name),f"{safe_int(node_count,0):,}",f"{safe_int(vm_count,0):,}",cells,_v5058c_coverage_cell(coverage,latest),_v5058c_latest_cell(latest)))
    body=''.join(rows) or '<tr><td colspan="19" class="empty">No Node Group consumption in this range.</td></tr>'
    periods=''.join('<a class="%s" href="%s">%s</a>'%('active' if k==period else '',url_for("bandwidth_consumption_page",tab="group",period=k,group=selected or None),escape(v[0])) for k,v in V5058C_PERIODS.items())
    tabs='<div class="v5058c-tabs"><a href="%s">VM Consumption</a><a href="%s">Node Consumption</a><a class="active" href="%s">Node Group</a></div>'%(url_for("bandwidth_consumption_page",tab="vm",period=period),url_for("bandwidth_consumption_page",tab="node",period=period),url_for("bandwidth_consumption_page",tab="group",period=period))
    cols='<colgroup><col class="c-id"><col class="c-count"><col class="c-count">'+'<col class="c-metric">'*6+'<col class="c-diff">'+'<col class="c-metric">'*6+'<col class="c-diff"><col class="c-cover"><col class="c-latest"></colgroup>'
    table='''<div class="v5058c-table-wrap table-wrap"><table class="v5058c-table v5058c-node-table v5060-group-table">%s<thead><tr><th rowspan="2">NODE GROUP</th><th rowspan="2">NODES</th><th rowspan="2">VMS</th><th colspan="3">PHYSICAL PUBLIC</th><th colspan="3">ALL VM PUBLIC</th><th rowspan="2">PUBLIC DIFF</th><th colspan="3">PHYSICAL PRIVATE</th><th colspan="3">ALL VM PRIVATE</th><th rowspan="2">PRIVATE DIFF</th><th rowspan="2">COVERAGE</th><th rowspan="2">LATEST</th></tr><tr>%s</tr></thead><tbody>%s</tbody></table></div>'''%(cols,'<th>RX</th><th>TX</th><th>TOTAL</th>'*4,body)
    content='''%s<div class="card v5058c-shell"><div class="v5058c-head"><div><h2>Consumption</h2><p>Physical Node traffic compared with the compact total of all VMs inherited by each Node Group.</p></div><div class="v5058c-range"><div class="v5058c-range-block"><span>TIME RANGE</span><div class="v5058c-periods">%s</div></div></div></div>%s<form class="v5058c-toolbar" method="get"><input type="hidden" name="tab" value="group"><input type="hidden" name="period" value="%s">%s<button type="submit">Apply</button><a class="clear" href="%s">Reset</a></form>%s</div>'''%(V5060_CONSUMPTION_CSS,periods,tabs,period,_r20_node_groups._group_select(selected),url_for("bandwidth_consumption_page",tab="group",period=period),table)
    return page("Consumption",_r20_node_groups._CONSUMPTION_STYLE+content)

_r20_consumption_view_base=app.view_functions["bandwidth_consumption_page"]
def bandwidth_consumption_page_r20():
    if str(request.args.get("tab") or "").strip().lower()=="group":return _r20_group_page()
    return _r20_consumption_view_base()
app.view_functions["bandwidth_consumption_page"]=bandwidth_consumption_page_r20

# Retire the old Agent-side 2-hour writer while preserving route/table contracts.
def push_bandwidth_consumption_retired():
    return jsonify({"ok":False,"error":"legacy_2h_accounting_retired","message":"Use normal 5-minute /push; server hourly/daily rollups are authoritative."}),410
app.view_functions["push_bandwidth_consumption"]=push_bandwidth_consumption_retired

for _name,_value in {"_v5058c_node_ctes":_v5058c_node_ctes,"_v5058c_node_rows":_v5058c_node_rows,"_v5058c_node_totals":_v5058c_node_totals,"_v5058c_vm_totals":_v5058c_vm_totals}.items():
    setattr(_r20_node_groups,_name,_value)

def _r20_rebuild_node_vm_rollups(conn, nodes):
    nodes=sorted({str(node or "").strip() for node in nodes if str(node or "").strip()})
    if not nodes:
        return
    placeholders=",".join("?" for _ in nodes)
    conn.execute("DELETE FROM node_vm_consumption_hourly WHERE node IN (%s)"%placeholders,nodes)
    conn.execute("DELETE FROM node_vm_consumption_daily WHERE node IN (%s)"%placeholders,nodes)
    bridge_params=[PUBLIC_BRIDGE,PUBLIC_BRIDGE,PRIVATE_BRIDGE,PRIVATE_BRIDGE]+nodes
    conn.execute("""INSERT INTO node_vm_consumption_hourly(
      hour_start,node,vm_public_rx_bytes,vm_public_tx_bytes,vm_private_rx_bytes,
      vm_private_tx_bytes,coverage_seconds,sample_count,vm_count,last_push)
      SELECT hour_start,node,
        SUM(CASE WHEN bridge=? THEN tx_bytes ELSE 0 END),
        SUM(CASE WHEN bridge=? THEN rx_bytes ELSE 0 END),
        SUM(CASE WHEN bridge=? THEN tx_bytes ELSE 0 END),
        SUM(CASE WHEN bridge=? THEN rx_bytes ELSE 0 END),
        LEAST(3600,COALESCE(MAX(sample_count),0)*300),
        COALESCE(MAX(sample_count),0),COUNT(DISTINCT vm_uuid),MAX(last_push)
      FROM vm_consumption_hourly WHERE node IN (%s) GROUP BY hour_start,node"""%placeholders,bridge_params)
    conn.execute("""INSERT INTO node_vm_consumption_daily(
      day_start,node,vm_public_rx_bytes,vm_public_tx_bytes,vm_private_rx_bytes,
      vm_private_tx_bytes,coverage_seconds,sample_count,vm_count,last_push)
      SELECT day_start,node,
        SUM(CASE WHEN bridge=? THEN tx_bytes ELSE 0 END),
        SUM(CASE WHEN bridge=? THEN rx_bytes ELSE 0 END),
        SUM(CASE WHEN bridge=? THEN tx_bytes ELSE 0 END),
        SUM(CASE WHEN bridge=? THEN rx_bytes ELSE 0 END),
        LEAST(86400,COALESCE(MAX(sample_count),0)*300),
        COALESCE(MAX(sample_count),0),COUNT(DISTINCT vm_uuid),MAX(last_push)
      FROM vm_consumption_daily WHERE node IN (%s) GROUP BY day_start,node"""%placeholders,bridge_params)

_r20_purge_vm_base=purge_vm_data
def purge_vm_data(conn,node,vm_uuid,refresh_snapshots=True):
    affected={str(node or "").strip()}
    try:
        rows=conn.execute("""SELECT DISTINCT node FROM vm_consumption_hourly WHERE vm_uuid=?
          UNION SELECT DISTINCT node FROM vm_consumption_daily WHERE vm_uuid=?
          UNION SELECT DISTINCT node FROM node_stats WHERE vm_uuid=?""",(vm_uuid,vm_uuid,vm_uuid)).fetchall()
        affected.update(str(row[0] or "").strip() for row in rows)
    except Exception:
        pass
    result=_r20_purge_vm_base(conn,node,vm_uuid,refresh_snapshots=refresh_snapshots)
    _r20_rebuild_node_vm_rollups(conn,affected)
    return result

_r20_purge_all_vms_base=purge_all_vms_for_node
def purge_all_vms_for_node(conn,node):
    result=_r20_purge_all_vms_base(conn,node)
    _delete_count(conn,"DELETE FROM node_vm_consumption_hourly WHERE node=?",(node,))
    _delete_count(conn,"DELETE FROM node_vm_consumption_daily WHERE node=?",(node,))
    return result

_r20_purge_node_base=purge_node_data
def purge_node_data(conn,node):
    result=dict(_r20_purge_node_base(conn,node) or {})
    result["node_vm_consumption_hourly"]=_delete_count(conn,"DELETE FROM node_vm_consumption_hourly WHERE node=?",(node,))
    result["node_vm_consumption_daily"]=_delete_count(conn,"DELETE FROM node_vm_consumption_daily WHERE node=?",(node,))
    return result

MONITORING_DATA_TABLES=tuple(dict.fromkeys(tuple(MONITORING_DATA_TABLES)+("node_vm_consumption_hourly","node_vm_consumption_daily")))
V48102_RESET_APP_TABLES=tuple(dict.fromkeys(tuple(V48102_RESET_APP_TABLES)+("node_vm_consumption_hourly","node_vm_consumption_daily")))

_r20_inventory_cleanup_base=run_inventory_cleanup_batches
def run_inventory_cleanup_batches(batch_size=None,max_batches=None):
    result=_r20_inventory_cleanup_base(batch_size=batch_size,max_batches=max_batches);cutoff=now_ts()-V5060_ROLLUP_RETENTION_SECONDS;conn=db()
    try:
        h=conn.execute("DELETE FROM node_vm_consumption_hourly WHERE hour_start<?",(cutoff,));d=conn.execute("DELETE FROM node_vm_consumption_daily WHERE day_start<?",(local_day_start(cutoff),));conn.commit()
        if isinstance(result,dict):result["node_vm_hourly_deleted"]=max(0,safe_int(h.rowcount,0));result["node_vm_daily_deleted"]=max(0,safe_int(d.rowcount,0))
    finally:conn.close()
    return result

def _v5030_bandwidth_admin_stats():
    conn=db()
    try:
        def stat(table,col):return conn.execute("SELECT COUNT(*),COALESCE(MIN(%s),0),COALESCE(MAX(%s),0),COALESCE(MAX(last_push),0) FROM %s"%(col,col,table)).fetchone()
        ph=stat("node_consumption_hourly","hour_start");pd=stat("node_consumption_daily","day_start");vh=stat("node_vm_consumption_hourly","hour_start");vd=stat("node_vm_consumption_daily","day_start")
        visible=safe_int(conn.execute("SELECT COUNT(*) FROM node_inventory WHERE COALESCE(status,'active')!='hidden' AND deleted_at IS NULL").fetchone()[0],0)
        reporting=safe_int(conn.execute("SELECT COUNT(DISTINCT p.node) FROM node_consumption_hourly p JOIN node_vm_consumption_hourly v ON v.node=p.node AND v.hour_start=p.hour_start JOIN node_inventory ni ON ni.node=p.node WHERE ni.deleted_at IS NULL AND COALESCE(ni.status,'active')!='hidden' AND (CASE WHEN p.last_push>v.last_push THEN p.last_push ELSE v.last_push END)>?",(now_ts()-7200,)).fetchone()[0],0)
        try:size=safe_int(conn.execute("SELECT "+"+".join("COALESCE(pg_total_relation_size('%s'),0)"%t for t in ("node_consumption_hourly","node_consumption_daily","node_vm_consumption_hourly","node_vm_consumption_daily"))).fetchone()[0],0)
        except Exception:size=0
        starts=[safe_int(x[1],0) for x in (ph,pd,vh,vd) if safe_int(x[1],0)>0];ends=[safe_int(x[2],0) for x in (ph,pd,vh,vd)];latest=[safe_int(x[3],0) for x in (ph,pd,vh,vd)]
        phr=safe_int(ph[0],0);pdr=safe_int(pd[0],0)
        try:legacy=safe_int(conn.execute("SELECT COUNT(*) FROM node_bandwidth_consumption_2h").fetchone()[0],0)
        except Exception:legacy=0
        return {"physical_hourly_rows":phr,"physical_daily_rows":pdr,"vm_hourly_rows":safe_int(vh[0],0),"vm_daily_rows":safe_int(vd[0],0),"size":size,"visible_nodes":visible,"reporting":reporting,"missing":max(0,visible-reporting),"oldest":min(starts) if starts else 0,"newest":max(ends) if ends else 0,"last_received":max(latest) if latest else 0,"hourly_rows":phr,"daily_rows":pdr,"legacy_rows":legacy}
    finally:conn.close()

_r20_maintenance_card_base=database_maintenance_card
def database_maintenance_card(message="",error=""):
    # Preserve the existing Nuclear reset preview / Nuclear operational reset,
    # including "No data has been deleted" and "Backup, verify, then reset".
    html=_r20_maintenance_card_base(message=message,error=error);start=html.find('<div class="card admin-section" id="accounting-storage">')
    if start<0:return html
    item=_v5030_bandwidth_admin_stats();token=escape(csrf_token(),quote=True)
    replacement='''<div class="card admin-section" id="accounting-storage"><div class="section-head"><div><span class="eyebrow">MAINTENANCE</span><h3>Consumption Rollup Storage</h3><p>Compact Physical Node and All-VM-per-Node hourly/daily rollups from normal 5-minute pushes.</p></div><a class="btn" href="%s">Open Consumption</a></div><div class="admin-kpis"><div><small>RETENTION</small><b>7 days</b></div><div><small>PHYSICAL HOURLY</small><b>%s</b></div><div><small>PHYSICAL DAILY</small><b>%s</b></div><div><small>VM NODE HOURLY</small><b>%s</b></div><div><small>VM NODE DAILY</small><b>%s</b></div><div><small>TABLE + INDEX</small><b>%s</b></div><div><small>REPORTING VISIBLE NODES</small><b>%s / %s</b></div><div><small>MISSING RECENT ROLLUP</small><b>%s</b></div><div><small>LAST INGESTION</small><b>%s</b></div><div><small>OLDEST BUCKET</small><b>%s</b></div><div><small>NEWEST BUCKET</small><b>%s</b></div></div><div class="bulk-bar"><form method="post" action="%s"><input type="hidden" name="csrf_token" value="%s"><input type="hidden" name="action" value="cleanup"><button type="submit">Run 7-day Consumption cleanup</button></form></div><div class="table-hint">Consumption has no separate clear button. Clear All Monitoring Data removes raw metrics and every Consumption rollup together while preserving inventory, Node Groups, users and settings.</div></div>'''%(url_for("bandwidth_consumption_page"),f"{item['physical_hourly_rows']:,}",f"{item['physical_daily_rows']:,}",f"{item['vm_hourly_rows']:,}",f"{item['vm_daily_rows']:,}",human(item["size"]),item["reporting"],item["visible_nodes"],item["missing"],fmt_full(item["last_received"]),fmt_full(item["oldest"]),fmt_full(item["newest"]),url_for("admin_bandwidth_consumption_action"),token)
    return html[:start]+replacement
