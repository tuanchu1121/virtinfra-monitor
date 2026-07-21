# Release: 50.5.9-prod-r22.7-vm-consumption-rollup-only
# Canonical R22 Consumption runtime. The R20 query/ingest implementations are
# removed; only stable rendering helpers and lifecycle bases are retained.

import math as _r20_math
import threading as _r20_threading
import node_groups as _r20_node_groups

V5060_RELEASE = "50.5.9-prod-r22.7-vm-consumption-rollup-only"
V5060_ROLLUP_RETENTION_SECONDS = 8 * 86400

# Capture the canonical pre-Consumption implementations exactly once. R21/R22
# wrappers below build on these bases without relying on a later layer override.
_r20_iface_copy_base = _v5052_write_interface_copy_batch
_r20_inventory_cleanup_base = run_inventory_cleanup_batches

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

# Register the existing Consumption route wrapper once. The canonical R22
# _r20_group_page implementation is defined below and resolved at request time.
_r20_consumption_view_base = app.view_functions["bandwidth_consumption_page"]

def bandwidth_consumption_page_r22():
    if str(request.args.get("tab") or "").strip().lower() == "group":
        return _r20_group_page()
    return _r20_consumption_view_base()

app.view_functions["bandwidth_consumption_page"] = bandwidth_consumption_page_r22

def push_bandwidth_consumption_retired():
    return jsonify({
        "ok": False,
        "error": "legacy_2h_accounting_retired",
        "message": "Use normal 5-minute /push; server hourly/daily rollups are authoritative.",
    }), 410

app.view_functions["push_bandwidth_consumption"] = push_bandwidth_consumption_retired

# Release: 50.5.9-prod-r22.7-vm-consumption-rollup-only
# Consumption-only architecture: all high-cardinality aggregation happens in
# the accepted /push transaction. Node/Group/Summary render paths read only
# compact node-level 5m/hour/day rows. The VM page has its own per-VM pipeline.

import threading as _r21_threading
import time as _r21_time

V5070_RELEASE = "50.5.9-prod-r22.7-vm-consumption-rollup-only"
V5070_QUERY_CACHE_TTL = max(5, min(15, safe_int(os.environ.get("BW_CONSUMPTION_QUERY_CACHE_TTL", "10"), 10)))
V5070_NODE_RAW_RETENTION_SECONDS = 2 * 86400
V5070_ROLLUP_RETENTION_SECONDS = 8 * 86400

_r21_query_cache = {}
_r21_query_cache_lock = _r21_threading.RLock()

def _r21_cached(key, compute):
    now = _r21_time.monotonic()
    with _r21_query_cache_lock:
        hit = _r21_query_cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = compute()
    with _r21_query_cache_lock:
        _r21_query_cache[key] = (now + V5070_QUERY_CACHE_TTL, value)
        if len(_r21_query_cache) > 512:
            expired = [item for item, entry in _r21_query_cache.items() if entry[0] <= now]
            for item in expired[:256]:
                _r21_query_cache.pop(item, None)
    return value

def _r21_normalized_range(start, end):
    duration = max(1, safe_int(end, 0) - safe_int(start, 0))
    normalized_end = (safe_int(end, 0) // V5070_QUERY_CACHE_TTL) * V5070_QUERY_CACHE_TTL
    return normalized_end - duration, normalized_end

# ---------------------------------------------------------------------------
# Ingest-time Node Physical pre-aggregation
# ---------------------------------------------------------------------------

def _v5058r4_rollup_physical_consumption(conn, node, data_time, interval_seconds, physical_interfaces):
    totals = {"public_rx": 0, "public_tx": 0, "private_rx": 0, "private_tx": 0}
    valid_rows = 0
    for item in physical_interfaces or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        bridge = str(item.get("bridge") or "").strip()
        if not role:
            if bridge == PUBLIC_BRIDGE:
                role = "public"
            elif bridge == PRIVATE_BRIDGE:
                role = "private"
        if role not in ("public", "private"):
            continue
        valid_rows += 1
        totals[role + "_rx"] += max(0, safe_int(item.get("rx_delta"), 0))
        totals[role + "_tx"] += max(0, safe_int(item.get("tx_delta"), 0))
    if not valid_rows:
        return False

    interval = max(1, min(3600, safe_int(interval_seconds, CACHE_BUCKET_SECONDS)))
    bucket_start = bucket_for(data_time)
    hour_start = local_hour_start(data_time)
    day_start = local_day_start(data_time)
    metrics = (
        totals["public_rx"], totals["public_tx"],
        totals["private_rx"], totals["private_tx"],
    )
    conn.execute("""
      INSERT INTO node_consumption_5m(
        bucket_start,node,physical_public_rx_bytes,physical_public_tx_bytes,
        physical_private_rx_bytes,physical_private_tx_bytes,
        physical_coverage_seconds,physical_sample_count,last_push)
      VALUES (?,?,?,?,?,?,?,?,?)
      ON CONFLICT(bucket_start,node) DO UPDATE SET
        physical_public_rx_bytes=node_consumption_5m.physical_public_rx_bytes+excluded.physical_public_rx_bytes,
        physical_public_tx_bytes=node_consumption_5m.physical_public_tx_bytes+excluded.physical_public_tx_bytes,
        physical_private_rx_bytes=node_consumption_5m.physical_private_rx_bytes+excluded.physical_private_rx_bytes,
        physical_private_tx_bytes=node_consumption_5m.physical_private_tx_bytes+excluded.physical_private_tx_bytes,
        physical_coverage_seconds=CASE WHEN node_consumption_5m.physical_coverage_seconds+excluded.physical_coverage_seconds>300 THEN 300 ELSE node_consumption_5m.physical_coverage_seconds+excluded.physical_coverage_seconds END,
        physical_sample_count=node_consumption_5m.physical_sample_count+excluded.physical_sample_count,
        last_push=GREATEST(node_consumption_5m.last_push,excluded.last_push)
    """, (bucket_start, node) + metrics + (min(300, interval), 1, data_time))

    for table, time_column, time_value, coverage_cap in (
        ("node_consumption_hourly", "hour_start", hour_start, 3600),
        ("node_consumption_daily", "day_start", day_start, 86400),
    ):
        sql = f"""
          INSERT INTO {table}(
            {time_column},node,physical_public_rx_bytes,physical_public_tx_bytes,
            physical_private_rx_bytes,physical_private_tx_bytes,
            coverage_seconds,sample_count,physical_coverage_seconds,
            physical_sample_count,last_push)
          VALUES (?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT({time_column},node) DO UPDATE SET
            physical_public_rx_bytes={table}.physical_public_rx_bytes+excluded.physical_public_rx_bytes,
            physical_public_tx_bytes={table}.physical_public_tx_bytes+excluded.physical_public_tx_bytes,
            physical_private_rx_bytes={table}.physical_private_rx_bytes+excluded.physical_private_rx_bytes,
            physical_private_tx_bytes={table}.physical_private_tx_bytes+excluded.physical_private_tx_bytes,
            coverage_seconds=CASE WHEN {table}.coverage_seconds+excluded.coverage_seconds>{coverage_cap}
              THEN {coverage_cap} ELSE {table}.coverage_seconds+excluded.coverage_seconds END,
            sample_count={table}.sample_count+excluded.sample_count,
            physical_coverage_seconds=CASE WHEN {table}.physical_coverage_seconds+excluded.physical_coverage_seconds>{coverage_cap}
              THEN {coverage_cap} ELSE {table}.physical_coverage_seconds+excluded.physical_coverage_seconds END,
            physical_sample_count={table}.physical_sample_count+excluded.physical_sample_count,
            last_push=GREATEST({table}.last_push,excluded.last_push)
        """
        conn.execute(sql, (time_value, node) + metrics + (
            min(coverage_cap, interval), 1, min(coverage_cap, interval), 1, data_time,
        ))
    return True

# ---------------------------------------------------------------------------
# Ingest-time per-VM and All-VM-per-Node pre-aggregation
# ---------------------------------------------------------------------------

_r21_iface_copy_base = _r20_iface_copy_base

def _r21_merge_node_vm_preaggregates(conn):
    bridge_params = (PUBLIC_BRIDGE, PUBLIC_BRIDGE, PRIVATE_BRIDGE, PRIVATE_BRIDGE)
    conn.execute("""
      WITH grouped AS (
        SELECT bucket AS bucket_start,node,
          SUM(CASE WHEN bridge=? THEN tx_delta ELSE 0 END) vm_public_rx,
          SUM(CASE WHEN bridge=? THEN rx_delta ELSE 0 END) vm_public_tx,
          SUM(CASE WHEN bridge=? THEN tx_delta ELSE 0 END) vm_private_rx,
          SUM(CASE WHEN bridge=? THEN rx_delta ELSE 0 END) vm_private_tx,
          MAX(interval_seconds) coverage_seconds,
          COUNT(DISTINCT last_push) sample_count,
          COUNT(DISTINCT vm_uuid) vm_count,
          MAX(last_push) last_push
        FROM pg_temp.vi5052_iface_stage GROUP BY bucket,node
      )
      INSERT INTO node_consumption_5m(
        bucket_start,node,vm_public_rx_bytes,vm_public_tx_bytes,
        vm_private_rx_bytes,vm_private_tx_bytes,vm_coverage_seconds,
        vm_sample_count,vm_count,last_push)
      SELECT bucket_start,node,vm_public_rx,vm_public_tx,vm_private_rx,vm_private_tx,
             CASE WHEN coverage_seconds>300 THEN 300 ELSE coverage_seconds END,sample_count,vm_count,last_push FROM grouped
      ON CONFLICT(bucket_start,node) DO UPDATE SET
        vm_public_rx_bytes=node_consumption_5m.vm_public_rx_bytes+excluded.vm_public_rx_bytes,
        vm_public_tx_bytes=node_consumption_5m.vm_public_tx_bytes+excluded.vm_public_tx_bytes,
        vm_private_rx_bytes=node_consumption_5m.vm_private_rx_bytes+excluded.vm_private_rx_bytes,
        vm_private_tx_bytes=node_consumption_5m.vm_private_tx_bytes+excluded.vm_private_tx_bytes,
        vm_coverage_seconds=CASE WHEN node_consumption_5m.vm_coverage_seconds+excluded.vm_coverage_seconds>300 THEN 300 ELSE node_consumption_5m.vm_coverage_seconds+excluded.vm_coverage_seconds END,
        vm_sample_count=node_consumption_5m.vm_sample_count+excluded.vm_sample_count,
        vm_count=GREATEST(node_consumption_5m.vm_count,excluded.vm_count),
        last_push=GREATEST(node_consumption_5m.last_push,excluded.last_push)
    """, bridge_params)

    for table, time_column, coverage_cap in (
        ("node_consumption_hourly", "hour_start", 3600),
        ("node_consumption_daily", "day_start", 86400),
    ):
        sql = f"""
          WITH grouped AS (
            SELECT {time_column},node,
              SUM(CASE WHEN bridge=? THEN tx_delta ELSE 0 END) vm_public_rx,
              SUM(CASE WHEN bridge=? THEN rx_delta ELSE 0 END) vm_public_tx,
              SUM(CASE WHEN bridge=? THEN tx_delta ELSE 0 END) vm_private_rx,
              SUM(CASE WHEN bridge=? THEN rx_delta ELSE 0 END) vm_private_tx,
              MAX(interval_seconds) coverage_seconds,
              COUNT(DISTINCT last_push) sample_count,
              COUNT(DISTINCT vm_uuid) vm_count,
              MAX(last_push) last_push
            FROM pg_temp.vi5052_iface_stage GROUP BY {time_column},node
          )
          INSERT INTO {table}(
            {time_column},node,vm_public_rx_bytes,vm_public_tx_bytes,
            vm_private_rx_bytes,vm_private_tx_bytes,vm_coverage_seconds,
            vm_sample_count,vm_count,last_push)
          SELECT {time_column},node,vm_public_rx,vm_public_tx,vm_private_rx,vm_private_tx,
                 CASE WHEN coverage_seconds>{coverage_cap} THEN {coverage_cap} ELSE coverage_seconds END,
                 sample_count,vm_count,last_push FROM grouped
          ON CONFLICT({time_column},node) DO UPDATE SET
            vm_public_rx_bytes={table}.vm_public_rx_bytes+excluded.vm_public_rx_bytes,
            vm_public_tx_bytes={table}.vm_public_tx_bytes+excluded.vm_public_tx_bytes,
            vm_private_rx_bytes={table}.vm_private_rx_bytes+excluded.vm_private_rx_bytes,
            vm_private_tx_bytes={table}.vm_private_tx_bytes+excluded.vm_private_tx_bytes,
            vm_coverage_seconds=CASE WHEN {table}.vm_coverage_seconds+excluded.vm_coverage_seconds>{coverage_cap}
              THEN {coverage_cap} ELSE {table}.vm_coverage_seconds+excluded.vm_coverage_seconds END,
            vm_sample_count={table}.vm_sample_count+excluded.vm_sample_count,
            vm_count=GREATEST({table}.vm_count,excluded.vm_count),
            last_push=GREATEST({table}.last_push,excluded.last_push)
        """
        conn.execute(sql, bridge_params)

def _v5052_write_interface_copy_batch(conn, node, data_time, bucket, interval_seconds, interfaces):
    started = _r21_time.perf_counter()
    result = _r21_iface_copy_base(conn, node, data_time, bucket, interval_seconds, interfaces)
    if safe_int((result or {}).get("rows"), 0) > 0:
        _r21_merge_node_vm_preaggregates(conn)
    if isinstance(result, dict):
        result["node_rollup_ms"] = (_r21_time.perf_counter() - started) * 1000.0
    return result

# ---------------------------------------------------------------------------
# Node-only hybrid read pipeline. No per-VM table appears below this boundary.
# ---------------------------------------------------------------------------

R21_NODE_FORBIDDEN_RELATIONS = (
    "node_stats", "vm_consumption_hourly", "vm_consumption_daily",
    "node_vm_consumption_hourly", "node_vm_consumption_daily",
)

def _r21_ceil_hour(ts):
    base = local_hour_start(ts)
    return base if safe_int(ts, 0) == base else base + 3600

def _r21_node_raw_branch(start, end):
    return """SELECT node,
      physical_public_rx_bytes,physical_public_tx_bytes,
      physical_private_rx_bytes,physical_private_tx_bytes,
      vm_public_rx_bytes,vm_public_tx_bytes,vm_private_rx_bytes,vm_private_tx_bytes,
      physical_coverage_seconds,vm_coverage_seconds,vm_count,last_push
      FROM node_consumption_5m WHERE bucket_start>=? AND bucket_start<?""", [start, end]

def _r21_node_hourly_branch(start, end):
    return """SELECT node,
      physical_public_rx_bytes,physical_public_tx_bytes,
      physical_private_rx_bytes,physical_private_tx_bytes,
      vm_public_rx_bytes,vm_public_tx_bytes,vm_private_rx_bytes,vm_private_tx_bytes,
      physical_coverage_seconds,vm_coverage_seconds,vm_count,last_push
      FROM node_consumption_hourly WHERE hour_start>=? AND hour_start<?""", [start, end]

def _r21_node_daily_branch(start, end):
    return """SELECT node,
      physical_public_rx_bytes,physical_public_tx_bytes,
      physical_private_rx_bytes,physical_private_tx_bytes,
      vm_public_rx_bytes,vm_public_tx_bytes,vm_private_rx_bytes,vm_private_tx_bytes,
      physical_coverage_seconds,vm_coverage_seconds,vm_count,last_push
      FROM node_consumption_daily WHERE day_start>=? AND day_start<?""", [start, end]

def _r22_node_raw_available_start(reference_now=None):
    """Return the first 5-minute bucket guaranteed to survive raw retention."""
    reference_now = now_ts() if reference_now is None else safe_int(reference_now, 0)
    cutoff = max(0, reference_now - V5070_NODE_RAW_RETENTION_SECONDS)
    step = max(1, safe_int(CACHE_BUCKET_SECONDS, 300))
    return ((cutoff + step - 1) // step) * step

def _r21_node_source_sql(start, end, raw_available_start=None):
    start, end = safe_int(start, 0), safe_int(end, 0)
    if raw_available_start is None:
        raw_available_start = _r22_node_raw_available_start()
    raw_available_start = max(0, safe_int(raw_available_start, 0))
    branches, params = [], []

    def add_raw(raw_start, raw_end):
        # Never query 5-minute data that retention has already removed.  The
        # requested-period denominator remains unchanged, so an unavailable
        # partial edge is represented as reduced coverage rather than zero or
        # an invisible 100% result.
        raw_start = max(safe_int(raw_start, 0), raw_available_start)
        raw_end = safe_int(raw_end, 0)
        if raw_end <= raw_start:
            return
        sql, values = _r21_node_raw_branch(raw_start, raw_end)
        branches.append(sql); params.extend(values)

    first_day = local_day_start(start)
    full_day_start = first_day if start == first_day else first_day + 86400
    full_day_end = local_day_start(end)
    edges = [(start, end)]
    if full_day_start < full_day_end:
        sql, values = _r21_node_daily_branch(full_day_start, full_day_end)
        branches.append(sql); params.extend(values)
        edges = [(start, full_day_start), (full_day_end, end)]
    for edge_start, edge_end in edges:
        if edge_end <= edge_start:
            continue
        full_hour_start = _r21_ceil_hour(edge_start)
        full_hour_end = local_hour_start(edge_end)
        if full_hour_start >= full_hour_end:
            add_raw(edge_start, edge_end)
            continue
        if edge_start < full_hour_start:
            add_raw(edge_start, full_hour_start)
        sql, values = _r21_node_hourly_branch(full_hour_start, full_hour_end)
        branches.append(sql); params.extend(values)
        if full_hour_end < edge_end:
            add_raw(full_hour_end, edge_end)
    if not branches:
        return "SELECT * FROM node_consumption_5m WHERE 1=0", []
    return " UNION ALL ".join(branches), params

def _r21_node_dataset_sql(start, end):
    source_sql, params = _r21_node_source_sql(start, end)
    expected = max(1, safe_int(end, 0) - safe_int(start, 0))
    sql = """WITH node_parts AS (%s),
      node_agg AS (
        SELECT node,
          SUM(physical_public_rx_bytes) physical_public_rx,
          SUM(physical_public_tx_bytes) physical_public_tx,
          SUM(physical_private_rx_bytes) physical_private_rx,
          SUM(physical_private_tx_bytes) physical_private_tx,
          SUM(vm_public_rx_bytes) vm_public_rx,
          SUM(vm_public_tx_bytes) vm_public_tx,
          SUM(vm_private_rx_bytes) vm_private_rx,
          SUM(vm_private_tx_bytes) vm_private_tx,
          CASE WHEN SUM(physical_coverage_seconds)>? THEN ? ELSE SUM(physical_coverage_seconds) END physical_coverage_seconds,
          CASE WHEN SUM(vm_coverage_seconds)>? THEN ? ELSE SUM(vm_coverage_seconds) END vm_coverage_seconds,
          MAX(vm_count) vm_count,MAX(last_push) latest_sample
        FROM node_parts GROUP BY node
      ),
      node_meta AS (
        SELECT ni.node,gm.group_id,
          COALESCE(MAX(CASE WHEN LOWER(COALESCE(ba.role,''))='public' THEN ba.primary_ipv4 END),'') node_ip,
          MAX(CASE WHEN LOWER(COALESCE(pn.role,''))='public' THEN 1 ELSE 0 END) public_configured,
          MAX(CASE WHEN LOWER(COALESCE(pn.role,''))='private' THEN 1 ELSE 0 END) private_configured,
          MAX(CASE WHEN LOWER(COALESCE(ba.role,''))='public' THEN 1 ELSE 0 END) public_addressed,
          MAX(CASE WHEN LOWER(COALESCE(ba.role,''))='private' THEN 1 ELSE 0 END) private_addressed
        FROM node_inventory ni
        JOIN node_group_memberships gm ON gm.node=ni.node
        JOIN node_groups ng ON ng.id=gm.group_id AND ng.is_active=1
        LEFT JOIN node_bridge_addresses_latest ba ON ba.node=ni.node
        LEFT JOIN node_physical_net_latest pn ON pn.node=ni.node
        WHERE COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL
        GROUP BY ni.node,gm.group_id
      )
      SELECT m.node,m.group_id,m.node_ip,
        CASE WHEN m.public_configured>m.public_addressed THEN m.public_configured ELSE m.public_addressed END public_configured,
        CASE WHEN m.private_configured>m.private_addressed THEN m.private_configured ELSE m.private_addressed END private_configured,
        COALESCE(a.physical_public_rx,0) physical_public_rx,
        COALESCE(a.physical_public_tx,0) physical_public_tx,
        COALESCE(a.vm_public_rx,0) vm_public_rx,
        COALESCE(a.vm_public_tx,0) vm_public_tx,
        COALESCE(a.physical_private_rx,0) physical_private_rx,
        COALESCE(a.physical_private_tx,0) physical_private_tx,
        COALESCE(a.vm_private_rx,0) vm_private_rx,
        COALESCE(a.vm_private_tx,0) vm_private_tx,
        COALESCE(a.vm_count,0) vm_count,
        CASE WHEN (CASE WHEN COALESCE(a.physical_coverage_seconds,0)<COALESCE(a.vm_coverage_seconds,0) THEN COALESCE(a.physical_coverage_seconds,0) ELSE COALESCE(a.vm_coverage_seconds,0) END)*100.0/?>100.0 THEN 100.0 ELSE (CASE WHEN COALESCE(a.physical_coverage_seconds,0)<COALESCE(a.vm_coverage_seconds,0) THEN COALESCE(a.physical_coverage_seconds,0) ELSE COALESCE(a.vm_coverage_seconds,0) END)*100.0/? END coverage_percent,
        COALESCE(a.latest_sample,0) latest_sample
      FROM node_meta m LEFT JOIN node_agg a ON a.node=m.node
      ORDER BY LOWER(m.node)""" % source_sql
    return sql, list(params) + [expected, expected, expected, expected, expected, expected]

def _r21_node_dataset_uncached(start, end):
    sql, params = _r21_node_dataset_sql(start, end)
    lowered = sql.lower()
    for forbidden in R21_NODE_FORBIDDEN_RELATIONS:
        if forbidden in lowered:
            raise RuntimeError("node_consumption_forbidden_relation:%s" % forbidden)
    if "vm_uuid" in lowered:
        raise RuntimeError("node_consumption_forbidden_grouping:vm_uuid")
    conn = db()
    try:
        result = []
        for row in conn.execute(sql, params).fetchall():
            (node, group_id, node_ip, pub_cfg, priv_cfg,
             pp_rx, pp_tx, vp_rx, vp_tx, pr_rx, pr_tx, vr_rx, vr_tx,
             vm_count, coverage, latest) = row
            result.append({
                "node": str(node), "group_id": safe_int(group_id, 0), "node_ip": str(node_ip or ""),
                "public_configured": safe_int(pub_cfg, 0), "private_configured": safe_int(priv_cfg, 0),
                "physical_public_rx": safe_int(pp_rx, 0), "physical_public_tx": safe_int(pp_tx, 0),
                "vm_public_rx": safe_int(vp_rx, 0), "vm_public_tx": safe_int(vp_tx, 0),
                "physical_private_rx": safe_int(pr_rx, 0), "physical_private_tx": safe_int(pr_tx, 0),
                "vm_private_rx": safe_int(vr_rx, 0), "vm_private_tx": safe_int(vr_tx, 0),
                "vm_count": safe_int(vm_count, 0), "coverage_percent": safe_float(coverage, 0),
                "latest_sample": safe_int(latest, 0),
            })
        return result
    finally:
        conn.close()

def _r21_node_dataset(start, end):
    start, end = _r21_normalized_range(start, end)
    return _r21_cached(("node-dataset", start, end), lambda: _r21_node_dataset_uncached(start, end))

def _r21_node_tuple(item):
    pp_total = item["physical_public_rx"] + item["physical_public_tx"]
    vp_total = item["vm_public_rx"] + item["vm_public_tx"]
    pr_total = item["physical_private_rx"] + item["physical_private_tx"]
    vr_total = item["vm_private_rx"] + item["vm_private_tx"]
    return (
        item["node"], item["node_ip"], item["public_configured"], item["private_configured"],
        item["physical_public_rx"], item["physical_public_tx"], pp_total,
        item["vm_public_rx"], item["vm_public_tx"], vp_total, pp_total-vp_total,
        item["physical_private_rx"], item["physical_private_tx"], pr_total,
        item["vm_private_rx"], item["vm_private_tx"], vr_total, pr_total-vr_total,
        item["vm_count"], item["coverage_percent"], item["latest_sample"],
    )

def _r21_selected_group_id():
    try:
        return safe_int(_r20_node_groups.selected_group_id(), 0)
    except Exception:
        return 0

def _r21_scoped_nodes(start, end, selected_node=""):
    rows = _r21_node_dataset(start, end)
    gid = _r21_selected_group_id()
    return [item for item in rows if (not selected_node or item["node"] == selected_node) and (not gid or item["group_id"] == gid)]

def _r21_totals_from_items(items):
    keys = (
        "physical_public_rx", "physical_public_tx", "physical_private_rx", "physical_private_tx",
        "vm_public_rx", "vm_public_tx", "vm_private_rx", "vm_private_tx",
    )
    return {key: sum(safe_int(item.get(key), 0) for item in items) for key in keys}

def _v5058c_node_totals(start, end, selected_node=""):
    total = _r21_totals_from_items(_r21_scoped_nodes(start, end, selected_node))
    return {key: total[key] for key in ("physical_public_rx", "physical_public_tx", "physical_private_rx", "physical_private_tx")}

def _v5058c_vm_totals(start, end, selected_node=""):
    total = _r21_totals_from_items(_r21_scoped_nodes(start, end, selected_node))
    return {key: total[key] for key in ("vm_public_rx", "vm_public_tx", "vm_private_rx", "vm_private_tx")}

def _v5058c_node_rows(start, end, q, coverage, sort_by, order, page_no, limit):
    rows = _r21_scoped_nodes(start, end)
    needle = str(q or "").strip().lower()
    if needle:
        rows = [item for item in rows if needle in item["node"].lower() or needle in item["node_ip"].lower()]
    coverage = _v5058c_coverage(coverage)
    if coverage == "complete":
        rows = [item for item in rows if item["latest_sample"] > 0 and item["coverage_percent"] >= 99.5]
    elif coverage == "partial":
        rows = [item for item in rows if item["latest_sample"] > 0 and item["coverage_percent"] < 99.5]
    elif coverage == "no_data":
        rows = [item for item in rows if item["latest_sample"] <= 0]

    def sort_value(item):
        values = {
            "node": item["node"].lower(), "vm_count": item["vm_count"],
            "physical_public_rx": item["physical_public_rx"], "physical_public_tx": item["physical_public_tx"],
            "physical_public_total": item["physical_public_rx"]+item["physical_public_tx"],
            "vm_public_rx": item["vm_public_rx"], "vm_public_tx": item["vm_public_tx"],
            "vm_public_total": item["vm_public_rx"]+item["vm_public_tx"],
            "public_difference": (item["physical_public_rx"]+item["physical_public_tx"])-(item["vm_public_rx"]+item["vm_public_tx"]),
            "physical_private_rx": item["physical_private_rx"], "physical_private_tx": item["physical_private_tx"],
            "physical_private_total": item["physical_private_rx"]+item["physical_private_tx"],
            "vm_private_rx": item["vm_private_rx"], "vm_private_tx": item["vm_private_tx"],
            "vm_private_total": item["vm_private_rx"]+item["vm_private_tx"],
            "private_difference": (item["physical_private_rx"]+item["physical_private_tx"])-(item["vm_private_rx"]+item["vm_private_tx"]),
            "coverage": item["coverage_percent"], "latest_sample": item["latest_sample"],
        }
        return values.get(sort_by, values["physical_public_total"])

    rows.sort(key=lambda item: (sort_value(item), item["node"].lower()), reverse=(order != "asc"))
    total = len(rows); page_no = max(1, safe_int(page_no, 1)); limit = max(1, safe_int(limit, 100))
    max_page = max(1, int(_r20_math.ceil(total / float(limit))))
    if page_no > max_page:
        page_no = 1
    start_at = (page_no-1)*limit
    return [_r21_node_tuple(item) for item in rows[start_at:start_at+limit]], total, page_no, max_page

# VM has a separate hourly/daily rollup-only pipeline and is never invoked by Node/Group requests.
_r21_vm_rows_base = _v5058c_vm_rows

def _v5058c_vm_rows(start, end, selected_node, q, coverage, sort_by, order, page_no, limit):
    start, end = _r21_normalized_range(start, end)
    group_id = _r21_selected_group_id()
    try:
        visibility_generation = safe_int(_v48140_cache_generation(), 0)
    except Exception:
        visibility_generation = 0
    key = (
        "vm-page", start, end, group_id, selected_node, q, coverage,
        sort_by, order, page_no, limit, visibility_generation,
    )
    return _r21_cached(
        key,
        lambda: _r21_vm_rows_base(
            start, end, selected_node, q, coverage,
            sort_by, order, page_no, limit,
        ),
    )

# Keep Node Group aligned with Node and aggregate the already-fetched 350-row
# node dataset in Python. No second SQL statement and no per-VM pipeline.
def _r20_group_page():
    period = _v5058c_period(request.args.get("period")); _label, seconds = V5058C_PERIODS[period]
    end = now_ts(); start = end-seconds; selected = _r21_selected_group_id()
    grouped = {}
    for item in _r21_node_dataset(start, end):
        gid = item["group_id"]
        if selected and gid != selected:
            continue
        bucket = grouped.setdefault(gid, {"nodes": 0, "vm_count": 0, "coverage_sum": 0.0, "latest": 0})
        bucket["nodes"] += 1; bucket["vm_count"] += item["vm_count"]
        bucket["coverage_sum"] += item["coverage_percent"]; bucket["latest"] = max(bucket["latest"], item["latest_sample"])
        for key in ("physical_public_rx", "physical_public_tx", "vm_public_rx", "vm_public_tx", "physical_private_rx", "physical_private_tx", "vm_private_rx", "vm_private_tx"):
            bucket[key] = bucket.get(key, 0) + item[key]
    rows = []
    for group in _r20_node_groups.all_group_rows(visibility="active"):
        gid, name, _desc, country, _active, _system, _nodes, _vms, *_rest = group; gid = safe_int(gid, 0)
        if selected and gid != selected:
            continue
        data = grouped.get(gid, {})
        pp_rx=data.get("physical_public_rx",0); pp_tx=data.get("physical_public_tx",0); vp_rx=data.get("vm_public_rx",0); vp_tx=data.get("vm_public_tx",0)
        pr_rx=data.get("physical_private_rx",0); pr_tx=data.get("physical_private_tx",0); vr_rx=data.get("vm_private_rx",0); vr_tx=data.get("vm_private_tx",0)
        values=(pp_rx,pp_tx,pp_rx+pp_tx,vp_rx,vp_tx,vp_rx+vp_tx,(pp_rx+pp_tx)-(vp_rx+vp_tx),pr_rx,pr_tx,pr_rx+pr_tx,vr_rx,vr_tx,vr_rx+vr_tx,(pr_rx+pr_tx)-(vr_rx+vr_tx))
        href=url_for("bandwidth_consumption_page",tab="node",period=period,group=gid)
        cells=''.join('<td>%s</td>'%_v5058c_bytes(value) for value in values[:6])
        cells+='<td class="v5060-diff">%s</td>'%_r20_signed_bytes(values[6])
        cells+=''.join('<td>%s</td>'%_v5058c_bytes(value) for value in values[7:13])
        cells+='<td class="v5060-diff">%s</td>'%_r20_signed_bytes(values[13])
        count=max(1,data.get("nodes",0)); coverage=data.get("coverage_sum",0.0)/count if data.get("nodes",0) else 0.0
        rows.append('<tr><td class="v5060-group"><a href="%s"><b>%s%s</b></a></td><td>%s</td><td>%s</td>%s<td>%s</td><td class="v5058c-latest">%s</td></tr>'%(
            escape(href,quote=True),_r20_node_groups.flag_html(country),escape(name),f"{data.get('nodes',0):,}",f"{data.get('vm_count',0):,}",cells,_v5058c_coverage_cell(coverage,data.get("latest",0)),_v5058c_latest_cell(data.get("latest",0))))
    body=''.join(rows) or '<tr><td colspan="19" class="empty">No Node Group consumption in this range.</td></tr>'
    periods=''.join('<a class="%s" href="%s">%s</a>'%('active' if key==period else '',url_for("bandwidth_consumption_page",tab="group",period=key,group=selected or None),escape(value[0])) for key,value in V5058C_PERIODS.items())
    tabs='<div class="v5058c-tabs"><a href="%s">VM Consumption</a><a href="%s">Node Consumption</a><a class="active" href="%s">Node Group</a></div>'%(url_for("bandwidth_consumption_page",tab="vm",period=period),url_for("bandwidth_consumption_page",tab="node",period=period),url_for("bandwidth_consumption_page",tab="group",period=period))
    cols='<colgroup><col class="c-id"><col class="c-count"><col class="c-count">'+'<col class="c-metric">'*6+'<col class="c-diff">'+'<col class="c-metric">'*6+'<col class="c-diff"><col class="c-cover"><col class="c-latest"></colgroup>'
    table='''<div class="v5058c-table-wrap table-wrap"><table class="v5058c-table v5058c-node-table v5060-group-table">%s<thead><tr><th rowspan="2">NODE GROUP</th><th rowspan="2">NODES</th><th rowspan="2">VMS</th><th colspan="3">PHYSICAL PUBLIC</th><th colspan="3">ALL VM PUBLIC</th><th rowspan="2">PUBLIC DIFF</th><th colspan="3">PHYSICAL PRIVATE</th><th colspan="3">ALL VM PRIVATE</th><th rowspan="2">PRIVATE DIFF</th><th rowspan="2">COVERAGE</th><th rowspan="2">LATEST</th></tr><tr>%s</tr></thead><tbody>%s</tbody></table></div>'''%(cols,'<th>RX</th><th>TX</th><th>TOTAL</th>'*4,body)
    content='''%s<div class="card v5058c-shell"><div class="v5058c-head"><div><h2>Consumption</h2><p>Node Group totals reuse the node-only ingest-time rollups. No VM/NIC aggregation runs while rendering this tab.</p></div><div class="v5058c-range"><div class="v5058c-range-block"><span>TIME RANGE</span><div class="v5058c-periods">%s</div></div></div></div>%s<form class="v5058c-toolbar" method="get"><input type="hidden" name="tab" value="group"><input type="hidden" name="period" value="%s">%s<button type="submit">Apply</button><a class="clear" href="%s">Reset</a></form>%s</div>'''%(V5060_CONSUMPTION_CSS,periods,tabs,period,_r20_node_groups._group_select(selected),url_for("bandwidth_consumption_page",tab="group",period=period),table)
    return page("Consumption",_r20_node_groups._CONSUMPTION_STYLE+content)

# Export the effective functions to the Node Group wrapper module.
for _name, _value in {
    "_v5058c_node_rows": _v5058c_node_rows,
    "_v5058c_node_totals": _v5058c_node_totals,
    "_v5058c_vm_totals": _v5058c_vm_totals,
}.items():
    setattr(_r20_node_groups, _name, _value)

# ---------------------------------------------------------------------------
# R21 Maintenance visibility and cleanup. Approximate row counts avoid COUNT(*)
# scans on high-cardinality canonical VM rollups.
# ---------------------------------------------------------------------------

def _r21_relation_rows(conn, table):
    try:
        row = conn.execute("SELECT COALESCE(reltuples,0)::bigint FROM pg_class WHERE oid=to_regclass(?)", (table,)).fetchone()
        return max(0, safe_int(row[0] if row else 0, 0))
    except Exception:
        try:
            return max(0, safe_int(conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0], 0))
        except Exception:
            return 0

def _v5030_bandwidth_admin_stats():
    conn = db()
    try:
        def bounds(table, column):
            return conn.execute(
                "SELECT COALESCE(MIN(%s),0),COALESCE(MAX(%s),0),COALESCE(MAX(last_push),0) FROM %s" % (column, column, table)
            ).fetchone()
        five = bounds("node_consumption_5m", "bucket_start")
        hourly = bounds("node_consumption_hourly", "hour_start")
        daily = bounds("node_consumption_daily", "day_start")
        visible = safe_int(conn.execute(
            "SELECT COUNT(*) FROM node_inventory WHERE COALESCE(status,'active')!='hidden' AND deleted_at IS NULL"
        ).fetchone()[0], 0)
        reporting = safe_int(conn.execute(
            "SELECT COUNT(DISTINCT r.node) FROM node_consumption_hourly r "
            "JOIN node_inventory ni ON ni.node=r.node "
            "WHERE ni.deleted_at IS NULL AND COALESCE(ni.status,'active')!='hidden' AND r.last_push>?",
            (now_ts()-7200,),
        ).fetchone()[0], 0)
        tables = ("node_consumption_5m", "node_consumption_hourly", "node_consumption_daily", "vm_consumption_hourly", "vm_consumption_daily")
        try:
            size = safe_int(conn.execute(
                "SELECT " + "+".join("COALESCE(pg_total_relation_size('%s'),0)" % table for table in tables)
            ).fetchone()[0], 0)
        except Exception:
            size = 0
        starts = [safe_int(row[0],0) for row in (five,hourly,daily) if safe_int(row[0],0)>0]
        ends = [safe_int(row[1],0) for row in (five,hourly,daily)]
        latest = [safe_int(row[2],0) for row in (five,hourly,daily)]
        node_5m_rows = _r21_relation_rows(conn,"node_consumption_5m")
        node_hourly_rows = _r21_relation_rows(conn,"node_consumption_hourly")
        node_daily_rows = _r21_relation_rows(conn,"node_consumption_daily")
        vm_hourly_rows = _r21_relation_rows(conn,"vm_consumption_hourly")
        vm_daily_rows = _r21_relation_rows(conn,"vm_consumption_daily")
        return {
            "node_5m_rows":node_5m_rows,"node_hourly_rows":node_hourly_rows,"node_daily_rows":node_daily_rows,
            "vm_hourly_rows":vm_hourly_rows,"vm_daily_rows":vm_daily_rows,"size":size,
            "visible_nodes":visible,"reporting":reporting,"missing":max(0,visible-reporting),
            "oldest":min(starts) if starts else 0,"newest":max(ends) if ends else 0,
            "last_received":max(latest) if latest else 0,
            "physical_hourly_rows":node_hourly_rows,"physical_daily_rows":node_daily_rows,
            "hourly_rows":node_hourly_rows,"daily_rows":node_daily_rows,"legacy_rows":0,
        }
    finally:
        conn.close()

_r21_maintenance_card_base = database_maintenance_card

def _r22_backfill_status():
    conn = db()
    try:
        row = conn.execute(
            "SELECT value,updated_at FROM admin_settings WHERE key=?",
            ("consumption_backfill_status_r22",),
        ).fetchone()
        if not row:
            return {}
        try:
            value = json.loads(str(row[0] or "{}"))
        except Exception:
            value = {"state": "failed", "last_error": "invalid backfill status JSON"}
        value["updated_at"] = safe_int(row[1], 0)
        return value
    finally:
        conn.close()

def _r22_backfill_status_html(status):
    if not status:
        return '<div class="table-hint">Backfill status: not run on this installation.</div>'
    state = str(status.get("state") or "unknown").strip().lower()
    expected = max(0, safe_int(status.get("expected_buckets"), 0))
    processed = max(0, safe_int(status.get("processed_buckets"), 0))
    progress = min(100.0, processed * 100.0 / expected) if expected else (100.0 if state == "completed" else 0.0)
    last_error = str(status.get("last_error") or "").strip()
    error_html = f'<small class="error-text">{escape(last_error[:500])}</small>' if last_error else ""
    warning = ""
    if state in {"failed", "completed_with_gaps"}:
        warning = '<b>Historical Consumption may be incomplete.</b>'
    return (
        f'<div class="table-hint r22-backfill-status"><b>Backfill: {escape(state)}</b> · '
        f'{processed:,}/{expected:,} buckets · {progress:.1f}% · '
        f'Rows {max(0,safe_int(status.get("processed_rows"),0)):,} · '
        f'Finished {fmt_full(safe_int(status.get("finished_at"),0))} {warning}{error_html}</div>'
    )

def database_maintenance_card(message="", error=""):
    """Preserve Nuclear reset preview and Nuclear operational reset controls.

    The base card still states No data has been deleted during preview and
    Backup, verify, then reset before the queued destructive operation.
    """
    html = _r21_maintenance_card_base(message=message,error=error)
    start = html.find('<div class="card admin-section" id="accounting-storage">')
    if start < 0:
        return html
    item = _v5030_bandwidth_admin_stats(); token = escape(csrf_token(),quote=True)
    replacement='''<div class="card admin-section" id="accounting-storage"><div class="section-head"><div><span class="eyebrow">MAINTENANCE</span><h3>Consumption Pre-aggregation Storage</h3><p>Node/Group/Summary read only compact Node 5-minute edges and Node hourly/daily rollups. VM history is maintained by its own pipeline.</p></div><a class="btn" href="%s">Open Consumption</a></div><div class="admin-kpis"><div><small>RETENTION</small><b>Raw 48h · Rollup 7d</b></div><div><small>NODE 5M</small><b>~%s</b></div><div><small>NODE HOURLY</small><b>~%s</b></div><div><small>NODE DAILY</small><b>~%s</b></div><div><small>VM HOURLY</small><b>~%s</b></div><div><small>VM DAILY</small><b>~%s</b></div><div><small>TABLE + INDEX</small><b>%s</b></div><div><small>REPORTING VISIBLE NODES</small><b>%s / %s</b></div><div><small>MISSING RECENT ROLLUP</small><b>%s</b></div><div><small>LAST INGESTION</small><b>%s</b></div><div><small>OLDEST BUCKET</small><b>%s</b></div><div><small>NEWEST BUCKET</small><b>%s</b></div></div><div class="bulk-bar"><form method="post" action="%s"><input type="hidden" name="csrf_token" value="%s"><input type="hidden" name="action" value="cleanup"><button type="submit">Run Consumption retention cleanup</button></form></div><div class="table-hint">Row counts are PostgreSQL planner estimates to avoid expensive COUNT(*) scans. Consumption has no separate clear action; Clear All Monitoring Data removes all raw and rollup monitoring data together.</div></div>'''%(
        url_for("bandwidth_consumption_page"),f"{item['node_5m_rows']:,}",f"{item['node_hourly_rows']:,}",f"{item['node_daily_rows']:,}",f"{item['vm_hourly_rows']:,}",f"{item['vm_daily_rows']:,}",human(item["size"]),item["reporting"],item["visible_nodes"],item["missing"],fmt_full(item["last_received"]),fmt_full(item["oldest"]),fmt_full(item["newest"]),url_for("admin_bandwidth_consumption_action"),token)
    replacement = replacement.replace(
        '<div class="bulk-bar">',
        _r22_backfill_status_html(_r22_backfill_status()) + '<div class="bulk-bar">',
        1,
    )
    return html[:start]+replacement

def _r22_consumption_retention_specs(now=None, include_vm=True):
    current = safe_int(now, 0) or now_ts()
    raw_cutoff = current - V5070_NODE_RAW_RETENTION_SECONDS
    rollup_cutoff = current - 7 * 86400
    specs = [
        ("node_consumption_5m", "bucket_start", raw_cutoff),
        ("node_consumption_hourly", "hour_start", rollup_cutoff),
        ("node_consumption_daily", "day_start", local_day_start(rollup_cutoff)),
    ]
    if include_vm:
        specs.extend((
            ("vm_consumption_hourly", "hour_start", rollup_cutoff),
            ("vm_consumption_daily", "day_start", local_day_start(rollup_cutoff)),
        ))
    return tuple(specs)

def run_consumption_retention_cleanup(dry_run=False, include_vm=True):
    """Apply the R22 Consumption retention policy outside the web request.

    The maintenance worker calls this function for ``retention`` jobs whose
    scope is ``consumption``.  Scheduled full retention reuses it for the new
    Node pre-aggregation tables, while the older VM pipeline remains handled
    by the established retention chain.
    """
    deleted = {}
    conn = db()
    try:
        for table, column, cutoff in _r22_consumption_retention_specs(include_vm=include_vm):
            if dry_run:
                row = conn.execute(
                    "SELECT COUNT(*) FROM %s WHERE %s<?" % (table, column),
                    (cutoff,),
                ).fetchone()
                deleted[table] = max(0, safe_int((row or [0])[0], 0))
            else:
                cur = conn.execute(
                    "DELETE FROM %s WHERE %s<?" % (table, column),
                    (cutoff,),
                )
                deleted[table] = max(0, safe_int(cur.rowcount, 0))
        if not dry_run:
            conn.commit()
    except Exception:
        if not dry_run:
            conn.rollback()
        raise
    finally:
        conn.close()
    if not dry_run:
        _v48140_bump_cache_generation()
        with _r21_query_cache_lock:
            _r21_query_cache.clear()
    return {
        "scope": "consumption",
        "dry_run": bool(dry_run),
        "deleted": deleted,
        "total_deleted": sum(max(0, safe_int(value, 0)) for value in deleted.values()),
        "raw_retention_seconds": V5070_NODE_RAW_RETENTION_SECONDS,
        "rollup_retention_seconds": 7 * 86400,
    }

# Ensure scheduled/global retention also covers the R21/R22 Node rollup tables.
# VM hourly/daily cleanup is already provided by the established retention
# chain, so include_vm=False avoids duplicate work.
_r22_run_retention_base = run_retention

def run_retention(dry_run=False):
    result = dict(_r22_run_retention_base(dry_run=dry_run) or {})
    consumption = run_consumption_retention_cleanup(
        dry_run=dry_run,
        include_vm=False,
    )
    result["consumption_preaggregation"] = consumption
    deleted = result.setdefault("deleted", {})
    for table, count in consumption.get("deleted", {}).items():
        deleted[table] = max(0, safe_int(deleted.get(table), 0)) + max(0, safe_int(count, 0))
    result["total_deleted"] = sum(max(0, safe_int(value, 0)) for value in deleted.values())
    return result

def _r22_consumption_queue_redirect(message, error=False):
    parameter = {"dberr" if error else "dbmsg": message}
    return redirect(
        url_for("admin_page", section="maintenance", **parameter)
        + "#maintenance-queue"
    )

def admin_bandwidth_consumption_action_r21():
    deny = require_admin()
    if deny:
        return deny
    action = str(request.form.get("action") or "").strip().lower()
    if action == "clear":
        role = str(session.get("dashboard_role") or session.get("admin_role") or "admin")
        if role != "super_admin":
            return Response("Forbidden\n", status=403, mimetype="text/plain")
        return Response(
            "Use Clear All Monitoring Data so raw metrics and every Consumption rollup are cleared together.\n",
            status=409,
            mimetype="text/plain",
        )
    if action != "cleanup":
        return Response("Unsupported action\n", status=400, mimetype="text/plain")
    actor = str(session.get("admin_username") or dashboard_username() or get_admin_username() or "admin")
    role = str(session.get("dashboard_role") or session.get("admin_role") or "admin")
    parameters = {
        "scope": "consumption",
        "raw_retention_seconds": V5070_NODE_RAW_RETENTION_SECONDS,
        "rollup_retention_seconds": 7 * 86400,
    }
    try:
        job_id, unit_name = enqueue_maintenance_job("retention", parameters, actor)
        message = (
            "Started Consumption retention job #%s as %s."
            % (job_id, unit_name)
        )
        log_account_event(
            "bandwidth_consumption_cleanup_queued",
            username=actor,
            realm="admin",
            role=role,
            detail=message,
        )
        return _r22_consumption_queue_redirect(message)
    except Exception as exc:
        message = "Could not queue Consumption retention: %s" % exc
        log_account_event(
            "bandwidth_consumption_cleanup_queue_failed",
            username=actor,
            realm="admin",
            role=role,
            detail=message[:500],
        )
        return _r22_consumption_queue_redirect(message, error=True)

app.view_functions["admin_bandwidth_consumption_action"] = admin_bandwidth_consumption_action_r21

# Give scoped retention jobs an explicit queue target without changing the
# existing action name or queue schema.
_r22_maintenance_target_summary_base = _maintenance_target_summary

def _maintenance_target_summary(action, raw_parameters):
    try:
        params = json.loads(raw_parameters or "{}") if not isinstance(raw_parameters, dict) else raw_parameters
    except Exception:
        params = {}
    if str(action or "").strip().lower() == "retention" and str(params.get("scope") or "").strip().lower() == "consumption":
        return "Consumption raw 48h + hourly/daily rollups 7d"
    return _r22_maintenance_target_summary_base(action, raw_parameters)

# ---------------------------------------------------------------------------
# Lifecycle, retention and destructive actions
# ---------------------------------------------------------------------------

_r21_purge_vm_base = purge_vm_data

def _r21_rebuild_node_vm_columns(conn, nodes):
    nodes = sorted({str(node or "").strip() for node in nodes if str(node or "").strip()})
    if not nodes:
        return
    placeholders = ",".join("?" for _ in nodes)
    for table in ("node_consumption_hourly", "node_consumption_daily"):
        conn.execute("UPDATE %s SET vm_public_rx_bytes=0,vm_public_tx_bytes=0,vm_private_rx_bytes=0,vm_private_tx_bytes=0,vm_coverage_seconds=0,vm_sample_count=0,vm_count=0 WHERE node IN (%s)" % (table, placeholders), nodes)
    conn.execute("UPDATE node_consumption_5m SET vm_public_rx_bytes=0,vm_public_tx_bytes=0,vm_private_rx_bytes=0,vm_private_tx_bytes=0,vm_coverage_seconds=0,vm_sample_count=0,vm_count=0 WHERE node IN (%s)" % placeholders, nodes)
    bridge = [PUBLIC_BRIDGE,PUBLIC_BRIDGE,PRIVATE_BRIDGE,PRIVATE_BRIDGE]
    conn.execute("""WITH data AS (
      SELECT bucket AS bucket_start,node,SUM(CASE WHEN bridge=? THEN tx_delta ELSE 0 END) a,
      SUM(CASE WHEN bridge=? THEN rx_delta ELSE 0 END) b,SUM(CASE WHEN bridge=? THEN tx_delta ELSE 0 END) c,
      SUM(CASE WHEN bridge=? THEN rx_delta ELSE 0 END) d,CASE WHEN MAX(interval_seconds)>300 THEN 300 ELSE MAX(interval_seconds) END cov,
      COUNT(DISTINCT last_push) samples,COUNT(DISTINCT vm_uuid) vm_count,MAX(last_push) last_push
      FROM node_stats WHERE node IN (%s) GROUP BY bucket,node)
      UPDATE node_consumption_5m n SET vm_public_rx_bytes=data.a,vm_public_tx_bytes=data.b,
      vm_private_rx_bytes=data.c,vm_private_tx_bytes=data.d,vm_coverage_seconds=data.cov,
      vm_sample_count=data.samples,vm_count=data.vm_count,last_push=GREATEST(n.last_push,data.last_push)
      FROM data WHERE n.bucket_start=data.bucket_start AND n.node=data.node""" % placeholders, bridge+nodes)
    conn.execute("""WITH data AS (
      SELECT hour_start,node,SUM(CASE WHEN bridge=? THEN tx_bytes ELSE 0 END) a,
      SUM(CASE WHEN bridge=? THEN rx_bytes ELSE 0 END) b,SUM(CASE WHEN bridge=? THEN tx_bytes ELSE 0 END) c,
      SUM(CASE WHEN bridge=? THEN rx_bytes ELSE 0 END) d,CASE WHEN MAX(sample_count)*300>3600 THEN 3600 ELSE MAX(sample_count)*300 END cov,
      MAX(sample_count) samples,COUNT(DISTINCT vm_uuid) vm_count,MAX(last_push) last_push
      FROM vm_consumption_hourly WHERE node IN (%s) GROUP BY hour_start,node)
      UPDATE node_consumption_hourly n SET vm_public_rx_bytes=data.a,vm_public_tx_bytes=data.b,
      vm_private_rx_bytes=data.c,vm_private_tx_bytes=data.d,vm_coverage_seconds=data.cov,
      vm_sample_count=data.samples,vm_count=data.vm_count,last_push=GREATEST(n.last_push,data.last_push)
      FROM data WHERE n.hour_start=data.hour_start AND n.node=data.node""" % placeholders, bridge+nodes)
    conn.execute("""WITH data AS (
      SELECT day_start,node,SUM(CASE WHEN bridge=? THEN tx_bytes ELSE 0 END) a,
      SUM(CASE WHEN bridge=? THEN rx_bytes ELSE 0 END) b,SUM(CASE WHEN bridge=? THEN tx_bytes ELSE 0 END) c,
      SUM(CASE WHEN bridge=? THEN rx_bytes ELSE 0 END) d,CASE WHEN MAX(sample_count)*300>86400 THEN 86400 ELSE MAX(sample_count)*300 END cov,
      MAX(sample_count) samples,COUNT(DISTINCT vm_uuid) vm_count,MAX(last_push) last_push
      FROM vm_consumption_daily WHERE node IN (%s) GROUP BY day_start,node)
      UPDATE node_consumption_daily n SET vm_public_rx_bytes=data.a,vm_public_tx_bytes=data.b,
      vm_private_rx_bytes=data.c,vm_private_tx_bytes=data.d,vm_coverage_seconds=data.cov,
      vm_sample_count=data.samples,vm_count=data.vm_count,last_push=GREATEST(n.last_push,data.last_push)
      FROM data WHERE n.day_start=data.day_start AND n.node=data.node""" % placeholders, bridge+nodes)

def purge_vm_data(conn, node, vm_uuid, refresh_snapshots=True):
    affected = {str(node or "").strip()}
    try:
        rows = conn.execute("SELECT DISTINCT node FROM vm_consumption_hourly WHERE vm_uuid=? UNION SELECT DISTINCT node FROM vm_consumption_daily WHERE vm_uuid=?", (vm_uuid, vm_uuid)).fetchall()
        affected.update(str(row[0] or "").strip() for row in rows)
    except Exception:
        pass
    result = _r21_purge_vm_base(conn, node, vm_uuid, refresh_snapshots=refresh_snapshots)
    _r21_rebuild_node_vm_columns(conn, affected)
    return result

_r21_purge_all_base = purge_all_vms_for_node

def purge_all_vms_for_node(conn, node):
    result = _r21_purge_all_base(conn, node)
    for table in ("node_consumption_5m", "node_consumption_hourly", "node_consumption_daily"):
        conn.execute("UPDATE %s SET vm_public_rx_bytes=0,vm_public_tx_bytes=0,vm_private_rx_bytes=0,vm_private_tx_bytes=0,vm_coverage_seconds=0,vm_sample_count=0,vm_count=0 WHERE node=?" % table, (node,))
    return result

_r21_purge_node_base = purge_node_data

def purge_node_data(conn, node):
    result = dict(_r21_purge_node_base(conn, node) or {})
    result["node_consumption_5m"] = _delete_count(conn, "DELETE FROM node_consumption_5m WHERE node=?", (node,))
    return result

MONITORING_DATA_TABLES = tuple(dict.fromkeys(tuple(MONITORING_DATA_TABLES) + (
    "node_consumption_5m", "vm_consumption_hourly", "vm_consumption_daily",
)))
V48102_RESET_APP_TABLES = tuple(dict.fromkeys(tuple(V48102_RESET_APP_TABLES) + (
    "node_consumption_5m", "vm_consumption_hourly", "vm_consumption_daily",
)))

_r21_inventory_cleanup_base = _r20_inventory_cleanup_base

def run_inventory_cleanup_batches(batch_size=None, max_batches=None):
    result = _r21_inventory_cleanup_base(batch_size=batch_size, max_batches=max_batches)
    conn = db(); now = now_ts()
    try:
        raw = conn.execute("DELETE FROM node_consumption_5m WHERE bucket_start<?", (now-V5070_NODE_RAW_RETENTION_SECONDS,))
        hourly = conn.execute("DELETE FROM node_consumption_hourly WHERE hour_start<?", (now-V5070_ROLLUP_RETENTION_SECONDS,))
        daily = conn.execute("DELETE FROM node_consumption_daily WHERE day_start<?", (local_day_start(now-V5070_ROLLUP_RETENTION_SECONDS),))
        conn.commit()
        if isinstance(result, dict):
            result.update({"node_consumption_5m_deleted":max(0,safe_int(raw.rowcount,0)),"node_consumption_hourly_deleted":max(0,safe_int(hourly.rowcount,0)),"node_consumption_daily_deleted":max(0,safe_int(daily.rowcount,0))})
    finally:
        conn.close()
    return result
