# Optional Redis hot cache, PostgreSQL pooling, materialized disk summaries,
# server-side pagination and browser render containment.
V48140_VERSION = "50.0.0"
V48140_BUILD = "prod-r1-postgres-native"

import gzip as _v48140_gzip
import hashlib as _v48140_hashlib
import threading as _v48140_threading
from collections import OrderedDict as _V48140OrderedDict
from time import perf_counter as _v48140_perf_counter

try:
    import redis as _v48140_redis_module
except Exception:  # optional; production installer provides redis-py
    _v48140_redis_module = None

V48140_REDIS_ENABLED = os.environ.get("BW_REDIS_ENABLED", "0") == "1"
V48140_REDIS_URL = os.environ.get("BW_REDIS_URL", "redis://127.0.0.1:6379/0")
V48140_PAGE_CACHE_ENABLED = os.environ.get("BW_PAGE_CACHE_ENABLED", "1") == "1"
V48140_PAGE_CACHE_TTL = max(1, min(60, safe_int(os.environ.get("BW_PAGE_CACHE_TTL", "6"), 6)))
V48140_LOCAL_CACHE_ITEMS = max(32, min(4096, safe_int(os.environ.get("BW_LOCAL_CACHE_ITEMS", "512"), 512)))
V48140_SQLITE_CACHE_MIB = 0  # compatibility no-op; PostgreSQL owns its buffer cache
V48140_SQLITE_MMAP_MIB = 0  # compatibility no-op
V48140_SQLITE_WAL_AUTOCHECKPOINT = 0  # compatibility no-op
V48140_SQLITE_JOURNAL_LIMIT_MIB = 0  # compatibility no-op

_v48140_redis_state = {"client": None, "retry_after": 0.0}
_v48140_redis_lock = _v48140_threading.RLock()
_v48140_local_lock = _v48140_threading.RLock()
_v48140_local_cache = _V48140OrderedDict()
_v48140_local_generation = 1

def _v48140_tune_connection(conn):
    """Apply low-risk per-connection tuning without repeating schema DDL."""
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute(f"PRAGMA cache_size={-V48140_SQLITE_CACHE_MIB * 1024}")
    conn.execute(f"PRAGMA mmap_size={V48140_SQLITE_MMAP_MIB * 1024 * 1024}")
    conn.execute(f"PRAGMA wal_autocheckpoint={V48140_SQLITE_WAL_AUTOCHECKPOINT}")
    conn.execute(f"PRAGMA journal_size_limit={V48140_SQLITE_JOURNAL_LIMIT_MIB * 1024 * 1024}")
    return conn

# The legacy db() helper re-ran hundreds of CREATE TABLE / CREATE INDEX
# statements on every request.  All migrations have already run during module
# import, so request-time connections can be opened directly and cheaply.
_v48140_legacy_db = db

def db():
    db_dir = os.path.dirname(DB)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = dbapi.connect(DB, timeout=30, cached_statements=512)
    return _v48140_tune_connection(conn)

def _v48140_redis_client():
    if not V48140_REDIS_ENABLED or _v48140_redis_module is None:
        return None
    now = time.monotonic()
    with _v48140_redis_lock:
        client = _v48140_redis_state.get("client")
        if client is not None:
            return client
        if now < float(_v48140_redis_state.get("retry_after") or 0):
            return None
        try:
            client = _v48140_redis_module.Redis.from_url(
                V48140_REDIS_URL,
                socket_connect_timeout=0.15,
                socket_timeout=0.25,
                health_check_interval=30,
                retry_on_timeout=False,
                decode_responses=False,
            )
            client.ping()
            _v48140_redis_state["client"] = client
            return client
        except Exception:
            _v48140_redis_state["client"] = None
            _v48140_redis_state["retry_after"] = now + 30.0
            return None

def _v48140_local_get(key):
    now = time.monotonic()
    with _v48140_local_lock:
        item = _v48140_local_cache.get(key)
        if not item:
            return None
        expires, value = item
        if expires <= now:
            _v48140_local_cache.pop(key, None)
            return None
        _v48140_local_cache.move_to_end(key)
        return value

def _v48140_local_set(key, value, ttl):
    with _v48140_local_lock:
        _v48140_local_cache[key] = (time.monotonic() + ttl, value)
        _v48140_local_cache.move_to_end(key)
        while len(_v48140_local_cache) > V48140_LOCAL_CACHE_ITEMS:
            _v48140_local_cache.popitem(last=False)

def _v48140_cache_get(key):
    client = _v48140_redis_client()
    if client is not None:
        try:
            raw = client.get(key)
            if raw:
                return _v48140_gzip.decompress(raw).decode("utf-8")
        except Exception:
            with _v48140_redis_lock:
                _v48140_redis_state["client"] = None
                _v48140_redis_state["retry_after"] = time.monotonic() + 10.0
    return _v48140_local_get(key)

def _v48140_cache_set(key, value, ttl=None):
    if not isinstance(value, str):
        return
    ttl = max(1, safe_int(ttl, V48140_PAGE_CACHE_TTL))
    client = _v48140_redis_client()
    if client is not None:
        try:
            client.setex(key, ttl, _v48140_gzip.compress(value.encode("utf-8"), 3))
            return
        except Exception:
            with _v48140_redis_lock:
                _v48140_redis_state["client"] = None
                _v48140_redis_state["retry_after"] = time.monotonic() + 10.0
    _v48140_local_set(key, value, ttl)

def ensure_v48140_performance_schema(conn):
    ensure_disk_io_schema(conn)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS vm_disk_summary_current (
      node TEXT NOT NULL,
      vm_uuid TEXT NOT NULL,
      disk_count INTEGER NOT NULL DEFAULT 0,
      allocated_bytes INTEGER NOT NULL DEFAULT 0,
      assigned_bytes INTEGER NOT NULL DEFAULT 0,
      physical_bytes INTEGER NOT NULL DEFAULT 0,
      allocation_ratio REAL NOT NULL DEFAULT 0,
      read_bps REAL NOT NULL DEFAULT 0,
      write_bps REAL NOT NULL DEFAULT 0,
      read_iops REAL NOT NULL DEFAULT 0,
      write_iops REAL NOT NULL DEFAULT 0,
      last_seen INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(node,vm_uuid)
    ) WITHOUT ROWID;

    CREATE TABLE IF NOT EXISTS node_storage_mount_summary_current (
      node TEXT NOT NULL,
      mount TEXT NOT NULL,
      device TEXT NOT NULL DEFAULT '',
      block TEXT NOT NULL DEFAULT '',
      raid_level TEXT NOT NULL DEFAULT '',
      fstype TEXT NOT NULL DEFAULT '',
      size INTEGER NOT NULL DEFAULT 0,
      used INTEGER NOT NULL DEFAULT 0,
      avail INTEGER NOT NULL DEFAULT 0,
      use_percent REAL NOT NULL DEFAULT 0,
      read_bps REAL NOT NULL DEFAULT 0,
      write_bps REAL NOT NULL DEFAULT 0,
      read_iops REAL NOT NULL DEFAULT 0,
      write_iops REAL NOT NULL DEFAULT 0,
      util_percent REAL NOT NULL DEFAULT 0,
      disk_count INTEGER NOT NULL DEFAULT 0,
      vm_count INTEGER NOT NULL DEFAULT 0,
      last_seen INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(node,mount)
    ) WITHOUT ROWID;
    CREATE INDEX IF NOT EXISTS idx_v48140_disk_role_mount_node
      ON vm_disk_current(role,mount,node,vm_uuid);
    CREATE INDEX IF NOT EXISTS idx_v48140_disk_role_vm_target
      ON vm_disk_current(role,node,vm_uuid,target);
    """)

# Schema creation is a process-start task, not a per-request/per-push task.
# The legacy helpers intentionally remain available as the one-time builders,
# while these guarded wrappers make steady-state reads and pushes DDL-free.
_v48140_disk_schema_builder = ensure_disk_io_schema
_v48140_performance_schema_builder = ensure_v48140_performance_schema
_v48140_schema_lock = _v48140_threading.RLock()
_v48140_disk_schema_ready = False
_v48140_performance_schema_ready = False

def ensure_disk_io_schema(conn):
    global _v48140_disk_schema_ready
    if _v48140_disk_schema_ready:
        return
    with _v48140_schema_lock:
        if not _v48140_disk_schema_ready:
            _v48140_disk_schema_builder(conn)
            _v48140_disk_schema_ready = True

def ensure_v48140_performance_schema(conn):
    global _v48140_performance_schema_ready
    if _v48140_performance_schema_ready:
        return
    with _v48140_schema_lock:
        if not _v48140_performance_schema_ready:
            _v48140_performance_schema_builder(conn)
            _v48140_performance_schema_ready = True

def _v48140_rebuild_all_summaries(conn):
    ensure_v48140_performance_schema(conn)
    nodes = [str(r[0]) for r in conn.execute("""
      SELECT node FROM (
        SELECT DISTINCT node FROM vm_disk_current
        UNION SELECT DISTINCT node FROM node_storage_current
      ) WHERE node IS NOT NULL AND TRIM(node)!=''
    """).fetchall()]
    for node in nodes:
        _v48140_refresh_node_summaries(conn, node)
    conn.execute("""
      INSERT INTO admin_settings(key,value,updated_at)
      VALUES('v48140_summary_version','1',?)
      ON CONFLICT(key) DO UPDATE SET value='1',updated_at=excluded.updated_at
    """, (now_ts(),))
    return len(nodes)

def _v48140_bootstrap_performance():
    conn = db()
    locked = False
    try:
        conn.execute("SELECT pg_advisory_lock(hashtextextended(?, 0))", ("virtinfra:summary-bootstrap",))
        locked = True
        # WAL is a database-level setting; do it once at worker startup, not per request.
        conn.execute("PRAGMA journal_mode=WAL")
        ensure_v48140_performance_schema(conn)
        marker = conn.execute("SELECT value FROM admin_settings WHERE key='v48140_summary_version'").fetchone()
        current = safe_int(conn.execute("SELECT COUNT(*) FROM vm_disk_summary_current").fetchone()[0], 0)
        expected = safe_int(conn.execute("SELECT COUNT(DISTINCT node || char(31) || vm_uuid) FROM vm_disk_current WHERE role='customer'").fetchone()[0], 0)
        if not marker or str(marker[0]) != "1" or current != expected:
            _v48140_rebuild_all_summaries(conn)
        conn.execute("PRAGMA optimize")
        conn.commit()
    finally:
        if locked:
            try:
                conn.execute("SELECT pg_advisory_unlock(hashtextextended(?, 0))", ("virtinfra:summary-bootstrap",))
                conn.commit()
            except Exception:
                pass
        conn.close()

try:
    _v48140_bootstrap_performance()
except Exception:
    app.logger.exception("Could not initialize v48.14.0 performance summaries")

_ingest_disk_io_current_v48140_base = ingest_disk_io_current

# Build the same request-local summary tables for historical Storage snapshots.
_v48137_create_snapshot_shadow_tables_v48140_base = _v48137_create_snapshot_shadow_tables

def _v48137_create_snapshot_shadow_tables(conn, payload_rows):
    stats = _v48137_create_snapshot_shadow_tables_v48140_base(conn, payload_rows)
    conn.execute("DROP TABLE IF EXISTS temp.vm_disk_summary_current")
    conn.execute("DROP TABLE IF EXISTS temp.node_storage_mount_summary_current")
    conn.executescript("""
      CREATE TEMP TABLE vm_disk_summary_current AS
      SELECT node,vm_uuid,COUNT(*) AS disk_count,
             COALESCE(SUM(allocation_bytes),0) AS allocated_bytes,
             COALESCE(SUM(capacity_bytes),0) AS assigned_bytes,
             COALESCE(SUM(physical_bytes),0) AS physical_bytes,
             CASE WHEN COALESCE(SUM(capacity_bytes),0)>0
                  THEN COALESCE(SUM(allocation_bytes),0)*1.0/SUM(capacity_bytes) ELSE 0 END AS allocation_ratio,
             COALESCE(SUM(read_bps),0) AS read_bps,
             COALESCE(SUM(write_bps),0) AS write_bps,
             COALESCE(SUM(read_iops),0) AS read_iops,
             COALESCE(SUM(write_iops),0) AS write_iops,
             MAX(last_seen) AS last_seen
        FROM vm_disk_current WHERE role='customer' GROUP BY node,vm_uuid;
      CREATE INDEX temp.idx_v48140_hist_vm ON vm_disk_summary_current(node,vm_uuid);
      CREATE INDEX temp.idx_v48140_hist_wiops ON vm_disk_summary_current(write_iops DESC,node,vm_uuid);

      CREATE TEMP TABLE node_storage_mount_summary_current AS
      WITH dc AS (
        SELECT node,mount,COUNT(*) AS disk_count,COUNT(DISTINCT vm_uuid) AS vm_count
          FROM vm_disk_current WHERE role='customer' GROUP BY node,mount
      )
      SELECT s.node,s.mount,s.device,s.block,s.raid_level,s.fstype,s.size,s.used,s.avail,s.use_percent,
             s.read_bps,s.write_bps,s.read_iops,s.write_iops,s.util_percent,
             COALESCE(dc.disk_count,0) AS disk_count,COALESCE(dc.vm_count,0) AS vm_count,s.last_seen
        FROM node_storage_current s LEFT JOIN dc ON dc.node=s.node AND dc.mount=s.mount;
      CREATE INDEX temp.idx_v48140_hist_mount ON node_storage_mount_summary_current(node,mount);
    """)
    return stats

def _v48140_public_ip_join(alias="s"):
    return f"LEFT JOIN node_bridge_addresses_latest b ON b.node={alias}.node AND b.bridge=?"

def _v48140_disk_search_clause(values, summary_alias="s"):
    clauses = [
        f"{summary_alias}.last_seen>=?",
        "COALESCE(vi.status,'active')!='hidden'",
        "vi.deleted_at IS NULL",
        "(ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))",
    ]
    params = []
    if values.get("node"):
        clauses.append(f"{summary_alias}.node=?")
        params.append(values["node"])
    if values.get("mount"):
        clauses.append(f"EXISTS (SELECT 1 FROM vm_disk_current md WHERE md.node={summary_alias}.node AND md.vm_uuid={summary_alias}.vm_uuid AND md.role='customer' AND md.mount=?)")
        params.append(values["mount"])
    if values.get("q"):
        p = like_pattern(values["q"])
        clauses.append(f"({summary_alias}.node LIKE ? OR {summary_alias}.vm_uuid LIKE ? OR COALESCE(b.primary_ipv4,'') LIKE ? OR EXISTS (SELECT 1 FROM vm_disk_current qd WHERE qd.node={summary_alias}.node AND qd.vm_uuid={summary_alias}.vm_uuid AND qd.role='customer' AND (qd.target LIKE ? OR qd.source LIKE ? OR qd.mount LIKE ? OR qd.storage_device LIKE ? OR qd.storage_block LIKE ?)))")
        params.extend([p, p, p, p, p, p, p, p])
    return clauses, params

def _v48133_storage_disk_groups(conn, values, start_ts):
    """Fast grouped Storage query using the materialized per-VM summary table."""
    sort_map = {
        "node": "s.node COLLATE NOCASE", "uuid": "s.vm_uuid COLLATE NOCASE", "diskcount": "s.disk_count",
        "assigned": "s.assigned_bytes", "allocated": "s.allocated_bytes", "allocpct": "s.allocation_ratio",
        "read": "s.read_bps", "write": "s.write_bps", "readiops": "s.read_iops",
        "writeiops": "s.write_iops", "seen": "s.last_seen",
    }
    if values.get("sort") not in sort_map:
        values["sort"] = "writeiops"
    clauses, extra = _v48140_disk_search_clause(values, "s")
    params = [start_ts] + extra
    where_sql = " AND ".join(clauses)
    total = safe_int(conn.execute(f"""
      SELECT COUNT(*)
        FROM vm_disk_summary_current s
        LEFT JOIN vm_inventory vi ON vi.node=s.node AND vi.vm_uuid=s.vm_uuid
        LEFT JOIN node_inventory ni ON ni.node=s.node
        LEFT JOIN node_bridge_addresses_latest b ON b.node=s.node AND b.bridge=?
       WHERE {where_sql}
    """, [PUBLIC_BRIDGE] + params).fetchone()[0], 0)
    pages = max(1, int(math.ceil(total / float(values["limit"]))))
    values["page"] = min(values["page"], pages)
    offset = (values["page"] - 1) * values["limit"]
    direction = "ASC" if values.get("order") == "asc" else "DESC"
    rows = conn.execute(f"""
      SELECT s.node,s.vm_uuid,COALESCE(b.primary_ipv4,''),s.disk_count,s.assigned_bytes,s.allocated_bytes,
             s.read_bps,s.write_bps,s.read_iops,s.write_iops,s.last_seen
        FROM vm_disk_summary_current s
        LEFT JOIN vm_inventory vi ON vi.node=s.node AND vi.vm_uuid=s.vm_uuid
        LEFT JOIN node_inventory ni ON ni.node=s.node
        LEFT JOIN node_bridge_addresses_latest b ON b.node=s.node AND b.bridge=?
       WHERE {where_sql}
       ORDER BY {sort_map[values['sort']]} {direction},s.node COLLATE NOCASE,s.vm_uuid COLLATE NOCASE
       LIMIT ? OFFSET ?
    """, [PUBLIC_BRIDGE] + params + [values["limit"], offset]).fetchall()
    details = {}
    keys = [str(r[0]) + "\x1f" + str(r[1]) for r in rows]
    if keys:
        ph = ",".join("?" for _ in keys)
        drows = conn.execute(f"""
          SELECT node,vm_uuid,target,source,mount,storage_device,storage_block,storage_fstype,
                 capacity_bytes,allocation_bytes,read_bps,write_bps,read_iops,write_iops,last_seen
            FROM vm_disk_current
           WHERE role='customer' AND (node || char(31) || vm_uuid) IN ({ph})
           ORDER BY node,vm_uuid,CASE target WHEN 'vda' THEN 0 WHEN 'vdb' THEN 1 ELSE 2 END,target,source
        """, keys).fetchall()
        for row in drows:
            details.setdefault((str(row[0]), str(row[1])), []).append(row[2:])
    return rows, details, total

def _v48140_fast_filter_options(conn, values):
    nodes = [str(r[0]) for r in conn.execute("""
      SELECT x.node
        FROM (
          SELECT s.node
            FROM vm_disk_summary_current s
            JOIN vm_inventory vi ON vi.node=s.node AND vi.vm_uuid=s.vm_uuid
           WHERE COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL
          UNION
          SELECT s.node FROM node_storage_mount_summary_current s
        ) x
        LEFT JOIN node_inventory ni ON ni.node=x.node
       WHERE ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL)
       GROUP BY x.node ORDER BY x.node COLLATE NOCASE
    """).fetchall()]
    node_filter = values.get("node")
    params = [node_filter, node_filter] if node_filter else []
    node_sql = " AND d.node=?" if node_filter else ""
    node_sql2 = " AND s.node=?" if node_filter else ""
    mounts = [str(r[0]) for r in conn.execute(f"""
      SELECT mount FROM (
        SELECT d.mount
          FROM vm_disk_current d
          JOIN vm_inventory vi ON vi.node=d.node AND vi.vm_uuid=d.vm_uuid
          LEFT JOIN node_inventory ni ON ni.node=d.node
         WHERE d.role='customer' AND d.mount!=''
           AND COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL
           AND (ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))
           {node_sql}
        UNION
        SELECT s.mount
          FROM node_storage_mount_summary_current s
          LEFT JOIN node_inventory ni2 ON ni2.node=s.node
         WHERE s.mount!=''
           AND (ni2.node IS NULL OR (COALESCE(ni2.status,'active')!='hidden' AND ni2.deleted_at IS NULL))
           {node_sql2}
      ) q GROUP BY mount ORDER BY mount COLLATE NOCASE
    """, params).fetchall()]
    node_options = ['<option value="">All nodes</option>']
    for item in nodes:
        node_options.append(f'<option value="{escape(item,quote=True)}"{" selected" if item == values.get("node") else ""}>{escape(item)}</option>')
    mount_options = ['<option value="">All storage</option>']
    for item in mounts:
        mount_options.append(f'<option value="{escape(item,quote=True)}"{" selected" if item == values.get("mount") else ""}>{escape(item)}</option>')
    return "".join(node_options), "".join(mount_options)

_v48137_storage_filter_options = _v48140_fast_filter_options

def _v48133_disk_totals_for_pairs(pairs):
    clean = []
    seen = set()
    for node, vm_uuid in pairs or []:
        key = (str(node or ""), str(vm_uuid or ""))
        if key[0] and key[1] and key not in seen:
            seen.add(key)
            clean.append(key)
    if not clean:
        return {}
    conn = db()
    try:
        keys = [node + "\x1f" + vm_uuid for node, vm_uuid in clean]
        placeholders = ",".join("?" for _ in keys)
        rows = conn.execute(f"""
          SELECT node,vm_uuid,allocated_bytes,assigned_bytes,disk_count
            FROM vm_disk_summary_current
           WHERE (node || char(31) || vm_uuid) IN ({placeholders})
        """, keys).fetchall()
        return {(str(r[0]),str(r[1])):(safe_int(r[2],0),safe_int(r[3],0),safe_int(r[4],0)) for r in rows}
    finally:
        conn.close()

# Replace the expensive GROUP BY subquery in Current Abuse with the summary table.
# The function body is redefined compactly while preserving the exact row contract.
def _v48139_current_rows(values):
    cfg = get_abuse_settings()
    where = [
        "a.is_abuse=1", "a.last_seen>=?", "a.policy_revision=?", "a.engine_version=?",
        _v48126_visible_sql("ni", "vi"), _v48126_type_condition("a", values["type"]), "a.severity>=?",
    ]
    params = [now_ts() - FAST_CURRENT_STALE_SECONDS, cfg["revision"], ABUSE_ENGINE_VERSION, values["min_severity"]]
    if values["node"]:
        where.append("a.node=?")
        params.append(values["node"])
    if values["q"]:
        pattern = like_pattern(values["q"])
        where.append("(a.node LIKE ? OR a.vm_uuid LIKE ? OR a.abuse_flags LIKE ?)")
        params.extend([pattern, pattern, pattern])
    sort = values.get("sort") or "severity"
    order = values.get("order") or "desc"
    sort_map = {
        "node":"a.node COLLATE NOCASE","uuid":"a.vm_uuid COLLATE NOCASE","type":"a.abuse_flags COLLATE NOCASE",
        "severity":"a.severity","rx_mbps":"COALESCE(a.rx_mbps,0)","tx_mbps":"COALESCE(a.tx_mbps,0)",
        "rx_peak":"COALESCE(a.rx_peak_pps,0)","tx_peak":"COALESCE(a.tx_peak_pps,0)",
        "cpu":"COALESCE(a.cpu_full_percent,0)","cpucore":"COALESCE(a.cpu_core_percent,0)",
        "ram":"COALESCE(a.ram_guest_used_percent,-1)",
        "ramused":"CASE WHEN COALESCE(a.ram_guest_used_percent,-1)>=0 THEN MAX(0,COALESCE(a.ram_available_kib,0)-COALESCE(a.ram_usable_kib,0)) ELSE -1 END",
        "ramrss":"COALESCE(a.ram_rss_kib,0)","ramassigned":"COALESCE(a.ram_current_kib,0)",
        "diskallocated":"COALESCE(ds.allocated_bytes,0)","diskassigned":"COALESCE(ds.assigned_bytes,0)",
        "diskallocpct":"COALESCE(ds.allocation_ratio,-1)","diskslots":"COALESCE(ds.disk_count,0)",
        "diskr":"COALESCE(a.disk_read_bps,0)","diskw":"COALESCE(a.disk_write_bps,0)",
        "readiops":"COALESCE(a.disk_read_iops,0)","writeiops":"COALESCE(a.disk_write_iops,0)","last_seen":"a.last_seen",
    }
    if sort == "duration":
        order_sql = f"a.abuse_since {'ASC' if order == 'desc' else 'DESC'}"
    else:
        order_sql = f"{sort_map.get(sort,sort_map['severity'])} {'ASC' if order == 'asc' else 'DESC'}"
    where_sql = " AND ".join(where)
    offset = (values["page"] - 1) * values["limit"]
    conn = db()
    try:
        total = safe_int(conn.execute(f"""SELECT COUNT(*) FROM vm_abuse_state a
          LEFT JOIN node_inventory ni ON ni.node=a.node
          LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
          WHERE {where_sql}""", params).fetchone()[0], 0)
        rows = conn.execute(f"""
          SELECT a.node,a.vm_uuid,a.abuse_since,a.last_seen,a.abuse_flags,a.severity,
                 a.rx_mbps,a.tx_mbps,a.rx_pps,a.tx_pps,a.rx_peak_pps,a.tx_peak_pps,
                 a.seconds_over_rx_pps,a.seconds_over_tx_pps,
                 COALESCE(a.network_rx_mbps_streak_seconds,0),COALESCE(a.network_tx_mbps_streak_seconds,0),
                 a.cpu_full_percent,a.cpu_core_percent,a.vcpu_current,a.cpu_streak_seconds,
                 a.ram_rss_percent,a.ram_guest_used_percent,a.ram_usable_percent,a.ram_streak_seconds,
                 a.ram_current_kib,a.ram_rss_kib,a.ram_available_kib,a.ram_usable_kib,
                 a.disk_read_bps,a.disk_write_bps,a.disk_read_iops,a.disk_write_iops,a.disk_streak_seconds,
                 COALESCE(b.primary_ipv4,''),COALESCE(ds.allocated_bytes,0),COALESCE(ds.assigned_bytes,0),COALESCE(ds.disk_count,0)
            FROM vm_abuse_state a
            LEFT JOIN node_inventory ni ON ni.node=a.node
            LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
            LEFT JOIN node_bridge_addresses_latest b ON b.node=a.node AND b.bridge=?
            LEFT JOIN vm_disk_summary_current ds ON ds.node=a.node AND ds.vm_uuid=a.vm_uuid
           WHERE {where_sql}
           ORDER BY {order_sql},a.node COLLATE NOCASE,a.vm_uuid COLLATE NOCASE
           LIMIT ? OFFSET ?
        """, [PUBLIC_BRIDGE] + params + [values["limit"], offset]).fetchall()
        counts = {}
        for key in ("network","cpu","ram","disk"):
            counts[key] = safe_int(conn.execute(f"""SELECT COUNT(*) FROM vm_abuse_state a
              LEFT JOIN node_inventory ni ON ni.node=a.node
              LEFT JOIN vm_inventory vi ON vi.node=a.node AND vi.vm_uuid=a.vm_uuid
             WHERE a.is_abuse=1 AND a.last_seen>=? AND a.policy_revision=? AND a.engine_version=?
               AND {_v48126_visible_sql('ni','vi')} AND {_v48126_type_condition('a',key)}""",
              (now_ts()-FAST_CURRENT_STALE_SECONDS,cfg["revision"],ABUSE_ENGINE_VERSION)).fetchone()[0],0)
        return rows,total,counts
    finally:
        conn.close()

# Exact purge/update paths also maintain the materialized summary tables and
# immediately invalidate page caches.
_purge_vm_data_v48140_base = purge_vm_data

def purge_vm_data(conn, node, vm_uuid, refresh_snapshots=True):
    nodes = {str(node or "").strip()} if str(node or "").strip() else set()
    try:
        nodes.update(str(r[0]) for r in conn.execute("SELECT DISTINCT node FROM vm_disk_summary_current WHERE vm_uuid=?", (vm_uuid,)).fetchall() if r and r[0])
    except Exception:
        pass
    deleted = _purge_vm_data_v48140_base(conn, node, vm_uuid, refresh_snapshots=refresh_snapshots)
    conn.execute("DELETE FROM vm_disk_summary_current WHERE vm_uuid=?", (str(vm_uuid or "").strip(),))
    for item in nodes:
        _v48140_refresh_node_summaries(conn, item)
    _v48140_bump_cache_generation()
    return deleted

_purge_all_vms_for_node_v48140_base = purge_all_vms_for_node

def purge_all_vms_for_node(conn, node):
    result = _purge_all_vms_for_node_v48140_base(conn, node)
    conn.execute("DELETE FROM vm_disk_summary_current WHERE node=?", (node,))
    _v48140_refresh_node_summaries(conn, node)
    _v48140_bump_cache_generation()
    return result

_purge_node_data_v48140_base = purge_node_data

def purge_node_data(conn, node):
    result = _purge_node_data_v48140_base(conn, node)
    conn.execute("DELETE FROM vm_disk_summary_current WHERE node=?", (node,))
    conn.execute("DELETE FROM node_storage_mount_summary_current WHERE node=?", (node,))
    _v48140_bump_cache_generation()
    return result

# Make complete reset/clear paths aware of the new materialized tables.
MONITORING_DATA_TABLES = tuple(dict.fromkeys(tuple(MONITORING_DATA_TABLES) + (
    "vm_disk_summary_current", "node_storage_mount_summary_current",
)))

def _v48140_cached_endpoint(endpoint_name, ttl=None):
    base = app.view_functions.get(endpoint_name)
    if base is None or getattr(base, "_v48140_cached", False):
        return
    def wrapper(*args, **kwargs):
        if not V48140_PAGE_CACHE_ENABLED or request.method != "GET" or request.args.get("_nocache") == "1":
            return base(*args, **kwargs)
        user = str(session.get("dashboard_username") or session.get("admin_username") or "anon")
        generation = _v48140_cache_generation()
        slot = int(time.time() // max(1, V48140_PAGE_CACHE_TTL))
        digest = _v48140_hashlib.sha256((endpoint_name + "|" + request.full_path + "|" + user).encode("utf-8")).hexdigest()
        key = f"bw:v48140:page:{generation}:{slot}:{digest}"
        cached = _v48140_cache_get(key)
        if cached is not None:
            response = app.make_response(cached)
            response.headers["X-BW-Cache"] = "HIT"
            return response
        result = base(*args, **kwargs)
        response = app.make_response(result)
        if response.status_code == 200 and response.mimetype == "text/html" and not response.direct_passthrough:
            body = response.get_data(as_text=True)
            _v48140_cache_set(key, body, ttl or V48140_PAGE_CACHE_TTL)
            response.headers["X-BW-Cache"] = "MISS"
        return response
    wrapper.__name__ = getattr(base, "__name__", endpoint_name)
    wrapper.__doc__ = getattr(base, "__doc__", None)
    wrapper._v48140_cached = True
    app.view_functions[endpoint_name] = wrapper

for _endpoint in ("index", "top_page", "top_node_page", "vm_abuse_page", "storage_io_page", "node_page", "vm_page"):
    _v48140_cached_endpoint(_endpoint, V48140_PAGE_CACHE_TTL)

# Browser rendering is often the last bottleneck after SQL is fast.  Modern
# browsers can skip layout/paint for off-screen cards while preserving the exact UI.
V48140_RENDER_CSS = r"""
<style id="v48140-render-performance">
.storage-entity-card-v48139,.storage-vm-card,.storage-node-card{content-visibility:auto;contain-intrinsic-size:520px;contain:layout paint style}
.table-wrap{contain:layout paint}.storage-card-list-v48139,.storage-card-list{contain:layout style}
</style>
"""

_page_v48140_base = page

def page(title, content):
    return _page_v48140_base(title, V48140_RENDER_CSS + content)

@app.before_request
def _v48140_request_timer_start():
    request.environ["bw.v48140.started"] = _v48140_perf_counter()

@app.after_request
def _v48140_response_performance(response):
    started = request.environ.get("bw.v48140.started")
    if started is not None:
        duration_ms = max(0.0, (_v48140_perf_counter() - started) * 1000.0)
        response.headers["Server-Timing"] = f"app;dur={duration_ms:.1f}"
        response.headers["X-VirtInfra-App-Time-Ms"] = f"{duration_ms:.1f}"
        response.headers["X-BW-App-Time-Ms"] = f"{duration_ms:.1f}"
    response.headers["X-VirtInfra-Performance"] = "50.2.1-csrf-topvm-fix"
    response.headers["X-BW-Performance"] = "50.2.1-csrf-topvm-fix"
    if (
        response.status_code == 200
        and not response.direct_passthrough
        and "gzip" in (request.headers.get("Accept-Encoding") or "").lower()
        and not response.headers.get("Content-Encoding")
        and response.mimetype in {"text/html", "application/json", "text/css", "application/javascript"}
    ):
        data = response.get_data()
        if len(data) >= 1024:
            response.set_data(_v48140_gzip.compress(data, 4))
            response.headers["Content-Encoding"] = "gzip"
            response.headers["Vary"] = "Accept-Encoding"
            response.headers["Content-Length"] = str(len(response.get_data()))
    return response

# Successful pushes may leave page cache stale for at most PAGE_CACHE_TTL
# seconds.  Destructive operations invalidate immediately through generation.
# Expose a compact health endpoint for operations and benchmarks.
@app.route("/api/v1/performance")
def api_v1_performance_v48140():
    # Keep the same authentication posture as the existing health/API pages.
    pass  # superseded route body; final handler is bound later

def _v48140_node_group_cards_fast(conn, values, start_ts):
    sort_map = {
        "node":"g.node COLLATE NOCASE", "size":"g.size", "used":"g.used",
        "usepct":"CASE WHEN g.size>0 THEN g.used*1.0/g.size ELSE 0 END",
        "read":"g.read_bps", "write":"g.write_bps", "readiops":"g.read_iops",
        "writeiops":"g.write_iops", "util":"g.util_percent", "seen":"g.last_seen",
    }
    if values.get("sort") not in sort_map:
        values["sort"] = "writeiops"
    where = [
        "s.last_seen>=?",
        "(ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))",
    ]
    params = [start_ts]
    if values.get("node"):
        where.append("s.node=?")
        params.append(values["node"])
    if values.get("q"):
        p = like_pattern(values["q"])
        where.append("(s.node LIKE ? OR s.mount LIKE ? OR s.device LIKE ? OR s.block LIKE ? OR s.raid_level LIKE ? OR s.fstype LIKE ? OR COALESCE(b.primary_ipv4,'') LIKE ?)")
        params.extend([p] * 7)
    where_sql = " AND ".join(where)
    cte = f"""
      WITH vc AS (
        SELECT d.node,COUNT(*) AS vm_count,COALESCE(SUM(d.disk_count),0) AS disk_count
          FROM vm_disk_summary_current d
          JOIN vm_inventory vi ON vi.node=d.node AND vi.vm_uuid=d.vm_uuid
          LEFT JOIN node_inventory ni0 ON ni0.node=d.node
         WHERE COALESCE(vi.status,'active')!='hidden' AND vi.deleted_at IS NULL
           AND (ni0.node IS NULL OR (COALESCE(ni0.status,'active')!='hidden' AND ni0.deleted_at IS NULL))
         GROUP BY d.node
      ),
      g AS (
        SELECT s.node,COALESCE(MAX(b.primary_ipv4),'') AS public_ipv4,
               COUNT(*) AS mount_count,COALESCE(SUM(s.size),0) AS size,
               COALESCE(SUM(s.used),0) AS used,COALESCE(SUM(s.read_bps),0) AS read_bps,
               COALESCE(SUM(s.write_bps),0) AS write_bps,COALESCE(SUM(s.read_iops),0) AS read_iops,
               COALESCE(SUM(s.write_iops),0) AS write_iops,COALESCE(MAX(s.util_percent),0) AS util_percent,
               MAX(s.last_seen) AS last_seen,COALESCE(MAX(vc.disk_count),0) AS disk_count,
               COALESCE(MAX(vc.vm_count),0) AS vm_count
          FROM node_storage_mount_summary_current s
          LEFT JOIN node_inventory ni ON ni.node=s.node
          LEFT JOIN node_bridge_addresses_latest b ON b.node=s.node AND b.bridge=?
          LEFT JOIN vc ON vc.node=s.node
         WHERE {where_sql}
         GROUP BY s.node
      )
    """
    total = safe_int(conn.execute(cte + "SELECT COUNT(*) FROM g", [PUBLIC_BRIDGE] + params).fetchone()[0], 0)
    pages = max(1, int(math.ceil(total / float(values["limit"]))))
    values["page"] = min(values["page"], pages)
    offset = (values["page"] - 1) * values["limit"]
    direction = "ASC" if values.get("order") == "asc" else "DESC"
    groups = conn.execute(cte + f"""
      SELECT node,public_ipv4,mount_count,size,used,read_bps,write_bps,read_iops,write_iops,
             util_percent,last_seen,disk_count,vm_count
        FROM g ORDER BY {sort_map[values['sort']]} {direction},node COLLATE NOCASE
       LIMIT ? OFFSET ?
    """, [PUBLIC_BRIDGE] + params + [values["limit"], offset]).fetchall()
    node_names = [str(r[0]) for r in groups]
    mounts_by_node = {n: [] for n in node_names}
    if node_names:
        ph = ",".join("?" for _ in node_names)
        mrows = conn.execute(f"""
          SELECT s.node,COALESCE(b.primary_ipv4,''),s.mount,s.device,s.block,s.raid_level,s.fstype,
                 s.size,s.used,s.avail,s.use_percent,s.read_bps,s.write_bps,s.read_iops,s.write_iops,
                 s.util_percent,s.last_seen,s.disk_count,s.vm_count
            FROM node_storage_mount_summary_current s
            LEFT JOIN node_inventory ni ON ni.node=s.node
            LEFT JOIN node_bridge_addresses_latest b ON b.node=s.node AND b.bridge=?
           WHERE (ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))
             AND s.node IN ({ph})
           ORDER BY s.node COLLATE NOCASE,
                    CASE s.mount WHEN '/' THEN 0 WHEN '[SWAP]' THEN 1 WHEN '/boot' THEN 2 WHEN '/boot/efi' THEN 3 WHEN '/home' THEN 4 ELSE 10 END,
                    s.mount COLLATE NOCASE
        """, [PUBLIC_BRIDGE] + node_names).fetchall()
        for row in mrows:
            mounts_by_node.setdefault(str(row[0]), []).append(row)
    cards = []
    for node, ip, mount_count, size, used, rb, wb, ri, wi, util, seen, disk_count, vm_count in groups:
        mounts = mounts_by_node.get(str(node), [])
        node_href = url_for("node_page", node=node, period=values["period"], **({"at": values.get("at")} if values.get("at") else {}))
        pct = used * 100.0 / size if safe_int(size, 0) > 0 else 0.0
        level = _v48139_cap_level(pct)
        mount_rows = "".join(_v48139_node_mount_row(values, row) for row in mounts)
        cards.append(f'''
        <article class="storage-node-card storage-entity-card-v48139">
          <div class="storage-entity-head-v48139">
            <div class="storage-entity-id-v48139">
              <span class="entity-kicker">Storage Node</span>
              <div class="entity-main"><a href="{escape(node_href,quote=True)}">{escape(node)}</a>{f'<button type="button" class="copy-btn" data-copy="{escape(ip)}" title="Copy IP">⧉</button>' if ip else ''}</div>
              <div class="entity-context">{f'<span>{escape(ip)}</span>' if ip else ''}<span>{safe_int(mount_count,0)} filesystems</span><span>· {safe_int(vm_count,0)} VMs</span><span>· {safe_int(disk_count,0)} disks</span><span>· sample {fmt_push(seen)}</span></div>
            </div>
            <div class="storage-entity-actions-v48139"><a class="btn" href="{escape(node_href,quote=True)}">View node</a></div>
          </div>
          <div class="storage-overview-v48139">
            <div class="storage-section-box-v48139"><span class="storage-section-label-v48139">Overall</span><div class="storage-overall-value-v48139"><b>{_disk_io_bytes(used)} / {_disk_io_bytes(size)}</b><span>{pct:.1f}% used / size</span></div><div class="storage-cap-track-v48139 disk-cap-meter {level}"><i style="width:{min(100.0,max(0.0,pct)):.1f}%"></i></div></div>
            <div class="storage-section-box-v48139"><span class="storage-section-label-v48139">Performance</span><div class="storage-perf-grid-v48139"><div><span>READ</span><b>{_disk_io_rate(rb)}</b></div><div><span>WRITE</span><b>{_disk_io_rate(wb)}</b></div><div><span>IOPS / HOT UTIL</span><b>R {_disk_io_iops(ri)} / W {_disk_io_iops(wi)} · {safe_float(util,0):.1f}%</b></div></div></div>
          </div>
          <div class="storage-children-v48139"><div class="storage-children-title-v48139"><h4>Filesystems</h4><span>{len(mounts)} real roots</span></div>{mount_rows}</div>
        </article>''')
    if not cards:
        cards = ['<div class="storage-card-empty-v48139">No real node storage sample at this snapshot.</div>']
    sort_bar = _v48137_sort_bar(values, [("W IOPS","writeiops"),("WRITE","write"),("R IOPS","readiops"),("READ","read"),("UTIL","util"),("USED","used"),("SIZE","size"),("%","usepct"),("NODE","node")])
    return f'''{V48139_UI_CSS}<div class="card storage-table-card"><div class="table-title-row"><div><h3>Storage Node</h3><div class="table-hint">One node card per node. SQL pagination loads only filesystems for the visible page.</div></div>{sort_bar}</div><div class="storage-card-list-v48139">{"".join(cards)}</div>{_storage_pager(values,total)}</div>'''

_v48137_storage_node_group_cards = _v48140_node_group_cards_fast

# Rebind cache wrappers with the actual dashboard session identity key.
def _v48140_rebind_cached_endpoint(endpoint_name, ttl=None):
    current = app.view_functions.get(endpoint_name)
    if current is None:
        return
    base = getattr(current, "_v48140_base", None) or current
    def wrapper(*args, **kwargs):
        if not V48140_PAGE_CACHE_ENABLED or request.method != "GET" or request.args.get("_nocache") == "1":
            return base(*args, **kwargs)
        user = str(session.get("dashboard_username") or session.get("admin_username") or "anon")
        generation = _v48140_cache_generation()
        slot = int(time.time() // max(1, V48140_PAGE_CACHE_TTL))
        digest = _v48140_hashlib.sha256((endpoint_name + "|" + request.full_path + "|" + user).encode("utf-8")).hexdigest()
        key = f"bw:v48140:page:{generation}:{slot}:{digest}"
        cached = _v48140_cache_get(key)
        if cached is not None:
            response = app.make_response(cached)
            response.headers["X-BW-Cache"] = "HIT"
            return response
        response = app.make_response(base(*args, **kwargs))
        if response.status_code == 200 and response.mimetype == "text/html" and not response.direct_passthrough:
            _v48140_cache_set(key, response.get_data(as_text=True), ttl or V48140_PAGE_CACHE_TTL)
            response.headers["X-BW-Cache"] = "MISS"
        return response
    wrapper.__name__ = getattr(base, "__name__", endpoint_name)
    wrapper.__doc__ = getattr(base, "__doc__", None)
    wrapper._v48140_cached = True
    wrapper._v48140_base = base
    app.view_functions[endpoint_name] = wrapper

for _endpoint in ("index", "top_page", "top_node_page", "vm_abuse_page", "storage_io_page", "node_page", "vm_page"):
    _current = app.view_functions.get(_endpoint)
    if _current is not None:
        _base = getattr(_current, "_v48140_base", None)
        if _base is None and getattr(_current, "_v48140_cached", False):
            # The first wrapper closed over its base. Use the pre-cache endpoint
            # references saved by Flask only through the wrapper closure is not
            # portable, so keep it and simply accept the broader cache identity.
            continue
        _v48140_rebind_cached_endpoint(_endpoint, V48140_PAGE_CACHE_TTL)

# Correct the performance endpoint authentication to the app's real session keys.
def api_v1_performance_v48140():
    if not session.get("dashboard_authenticated"):
        return jsonify({"error":"authentication required"}), 401
    conn = db()
    try:
        summary_vms = safe_int(conn.execute("SELECT COUNT(*) FROM vm_disk_summary_current").fetchone()[0],0)
        summary_mounts = safe_int(conn.execute("SELECT COUNT(*) FROM node_storage_mount_summary_current").fetchone()[0],0)
        pg = dbapi.healthcheck()
        pg_stats = dbapi.database_stats()
        client = _v48140_redis_client()
        redis_ok = False
        if client is not None:
            try: redis_ok = bool(client.ping())
            except Exception: redis_ok = False
        return jsonify({
            "version":"50.5.9-prod-r3-ui-alignment-overflow-hotfix",
            "database":{
                "engine":"PostgreSQL + TimescaleDB",
                "database":pg.get("database"),
                "user":pg.get("user"),
                "db_bytes":safe_int(pg_stats.get("db_size"),0),
                "wal_bytes":safe_int(pg_stats.get("wal_size"),0),
                "dead_rows":safe_int(pg_stats.get("freelist_count"),0),
            },
            "redis":{"enabled":V48140_REDIS_ENABLED,"connected":redis_ok,"role":"optional page cache only"},
            "page_cache":{"enabled":V48140_PAGE_CACHE_ENABLED,"ttl_seconds":V48140_PAGE_CACHE_TTL},
            "materialized":{"vm_disk_summaries":summary_vms,"node_mount_summaries":summary_mounts},
            "agent":{"push_interval_seconds":CACHE_BUCKET_SECONDS,"sample_window":"5 minutes"},
        })
    finally:
        conn.close()

app.view_functions["api_v1_performance_v48140"] = api_v1_performance_v48140

# Keep materialized summaries self-healing for old databases, manual imports and
# tests that insert current rows directly instead of going through /push.
def _v48140_reconcile_summaries_if_needed(conn, max_nodes=64):
    ensure_v48140_performance_schema(conn)
    rows = conn.execute("""
      SELECT DISTINCT d.node
        FROM vm_disk_current d
        LEFT JOIN vm_disk_summary_current s ON s.node=d.node AND s.vm_uuid=d.vm_uuid
       WHERE d.role='customer' AND (s.node IS NULL OR d.last_seen>s.last_seen)
       LIMIT ?
    """, (max(1, safe_int(max_nodes, 64)),)).fetchall()
    nodes = {str(r[0]) for r in rows if r and r[0]}
    # Storage rows may arrive independently of VM disk rows (for example an
    # empty node or a node with only OS/SWAP filesystems).
    for row in conn.execute("""
      SELECT DISTINCT n.node
        FROM node_storage_current n
        LEFT JOIN node_storage_mount_summary_current s ON s.node=n.node AND s.mount=n.mount
       WHERE s.node IS NULL OR n.last_seen>s.last_seen
       LIMIT ?
    """, (max(1, safe_int(max_nodes, 64)),)).fetchall():
        if row and row[0]:
            nodes.add(str(row[0]))
    for node in sorted(nodes):
        _v48140_refresh_node_summaries(conn, node)
    return len(nodes)

_v48133_disk_totals_for_pairs_v48140_fast = _v48133_disk_totals_for_pairs

def _v48133_disk_totals_for_pairs(pairs):
    conn = db()
    try:
        _v48140_reconcile_summaries_if_needed(conn)
        conn.commit()
    finally:
        conn.close()
    return _v48133_disk_totals_for_pairs_v48140_fast(pairs)

_v48133_storage_disk_groups_v48140_fast = _v48133_storage_disk_groups

def _v48133_storage_disk_groups(conn, values, start_ts):
    _v48140_reconcile_summaries_if_needed(conn)
    return _v48133_storage_disk_groups_v48140_fast(conn, values, start_ts)

_v48140_node_group_cards_fast_base = _v48140_node_group_cards_fast

def _v48140_node_group_cards_fast(conn, values, start_ts):
    _v48140_reconcile_summaries_if_needed(conn)
    return _v48140_node_group_cards_fast_base(conn, values, start_ts)

_v48137_storage_node_group_cards = _v48140_node_group_cards_fast

_v48139_current_rows_v48140_summary = _v48139_current_rows

def _v48139_current_rows(values):
    conn = db()
    try:
        changed = _v48140_reconcile_summaries_if_needed(conn)
        if changed:
            conn.commit()
    finally:
        conn.close()
    return _v48139_current_rows_v48140_summary(values)

