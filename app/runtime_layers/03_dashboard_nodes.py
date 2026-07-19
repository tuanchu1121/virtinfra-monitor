def get_node_rows(period, q="", sort_by="node", order="asc", target_ts=None):
    """Return one coherent real snapshot per node plus a separate live heartbeat.

    Every metric column is read from the same retained bucket for that node.
    Status is intentionally different: it always reflects the newest heartbeat.
    """
    auto_cleanup_inventory()
    period = clean_period(period)
    sort_by = clean_node_sort(sort_by)
    order = clean_sort_order(order)
    now = now_ts()
    if target_ts is not None:
        # An explicitly selected date/time is an absolute requested point.
        requested = int(target_ts)
        requested = max(now - HOURLY_RETENTION_DAYS * 86400, min(now, requested))
        offset = max(0, now - requested)
    else:
        # Dashboard period buttons are snapshot slots, not elapsed ranges:
        # 5m = latest retained push, 10m = previous push, 15m = third push.
        # Keep this identical to resolve_snapshot_bucket() and Storage I/O.
        offset = max(0, period_seconds(period) - CACHE_BUCKET_SECONDS)
        requested = max(now - HOURLY_RETENTION_DAYS * 86400, now - offset)
    visible_after = now - NODE_AUTO_DELETE_SECONDS
    q = (q or "").strip()
    like = like_pattern(q) if q else ""
    normalized_mac = normalize_mac_address(q) if q else ""

    order_map = {
        "node": "x.node COLLATE NOCASE",
        "last_push": "live_last_seen",
        "snapshot": "selected_bucket",
        "vm": "vm_count",
        "load": "load1",
        "uptime": "uptime_seconds",
        "cpu": "cpu_percent",
        "ram": "ram_percent",
        "diskr": "disk_read_bps",
        "diskw": "disk_write_bps",
        "public": "public_total",
        "private": "private_total",
        "total": "node_total",
        "pps": "node_pps_sort",
        "public_pps": "public_pps_sort",
        "private_pps": "private_pps_sort",
        "drops": "net_drops",
        "errors": "net_errors",
        "source": "net_source",
    }
    order_sql = order_map.get(sort_by, "node COLLATE NOCASE")

    sql = f"""
    WITH node_names AS (
        SELECT node FROM node_inventory
        UNION SELECT node FROM node_push_snapshots
    ),
    physical_live AS (
        SELECT node, MAX(last_seen) AS last_seen
        FROM node_physical_net_latest
        GROUP BY node
    ),
    latest AS (
        SELECT nn.node, MAX(s.bucket) AS latest_bucket
        FROM node_names nn
        LEFT JOIN node_push_snapshots s ON s.node=nn.node
        GROUP BY nn.node
    ),
    visible AS (
        SELECT
            l.node,
            l.latest_bucket,
            MAX(
                COALESCE(ni.last_push, 0), COALESCE(ah.last_seen, 0),
                COALESCE(nhl.last_seen, 0), COALESCE(pl.last_seen, 0),
                COALESCE(l.latest_bucket, 0)
            ) AS live_last_seen
        FROM latest l
        LEFT JOIN node_inventory ni ON ni.node=l.node
        LEFT JOIN agent_health_latest ah ON ah.node=l.node
        LEFT JOIN node_host_latest nhl ON nhl.node=l.node
        LEFT JOIN physical_live pl ON pl.node=l.node
        WHERE COALESCE(l.latest_bucket, 0)>0
          AND (ni.node IS NULL OR (COALESCE(ni.status, 'active')!='hidden' AND ni.deleted_at IS NULL))
          AND MAX(
                COALESCE(ni.last_push, 0), COALESCE(ah.last_seen, 0),
                COALESCE(nhl.last_seen, 0), COALESCE(pl.last_seen, 0),
                COALESCE(l.latest_bucket, 0)
              )>=?
          AND (
                ?=''
                OR l.node LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM node_bridge_addresses_latest bai
                    WHERE bai.node=l.node
                      AND (
                            COALESCE(bai.primary_ipv4, '') LIKE ?
                            OR COALESCE(bai.ipv4_json, '[]') LIKE ?
                            OR COALESCE(bai.primary_ipv6, '') LIKE ?
                            OR COALESCE(bai.ipv6_json, '[]') LIKE ?
                            OR COALESCE(bai.bridge, '') LIKE ?
                            OR COALESCE(bai.mac, '') LIKE ?
                            OR (?<>'' AND LOWER(COALESCE(bai.mac,''))=LOWER(?))
                          )
                )
                OR EXISTS (
                    SELECT 1
                    FROM vm_inventory svi
                    WHERE svi.node=l.node
                      AND COALESCE(svi.status, 'active')!='hidden'
                      AND svi.deleted_at IS NULL
                      AND (
                            svi.vm_uuid LIKE ?
                            OR COALESCE(svi.last_iface, '') LIKE ?
                            OR COALESCE(svi.last_bridge, '') LIKE ?
                          )
                )
                OR EXISTS (
                    SELECT 1
                    FROM vm_location_latest svl
                    WHERE svl.node=l.node
                      AND EXISTS (
                            SELECT 1 FROM vm_inventory svi2
                            WHERE svi2.node=svl.node AND svi2.vm_uuid=svl.vm_uuid
                              AND COALESCE(svi2.status, 'active')!='hidden'
                              AND svi2.deleted_at IS NULL
                          )
                      AND (
                            svl.vm_uuid LIKE ?
                            OR COALESCE(svl.last_iface, '') LIKE ?
                            OR COALESCE(svl.last_bridge, '') LIKE ?
                          )
                )
                OR EXISTS (
                    SELECT 1
                    FROM vm_node_presence svp
                    WHERE svp.node=l.node
                      AND EXISTS (
                            SELECT 1 FROM vm_inventory svi3
                            WHERE svi3.node=svp.node AND svi3.vm_uuid=svp.vm_uuid
                              AND COALESCE(svi3.status, 'active')!='hidden'
                              AND svi3.deleted_at IS NULL
                          )
                      AND (
                            svp.vm_uuid LIKE ?
                            OR COALESCE(svp.last_iface, '') LIKE ?
                            OR COALESCE(svp.last_bridge, '') LIKE ?
                          )
                )
                OR EXISTS (
                    SELECT 1
                    FROM vm_iface_current svi_mac
                    WHERE svi_mac.node=l.node
                      AND EXISTS (
                            SELECT 1 FROM vm_inventory svi_mac_inv
                            WHERE svi_mac_inv.node=svi_mac.node AND svi_mac_inv.vm_uuid=svi_mac.vm_uuid
                              AND COALESCE(svi_mac_inv.status,'active')!='hidden'
                              AND svi_mac_inv.deleted_at IS NULL
                          )
                      AND (
                            COALESCE(svi_mac.iface,'') LIKE ?
                            OR COALESCE(svi_mac.mac,'') LIKE ?
                            OR (?<>'' AND LOWER(COALESCE(svi_mac.mac,''))=LOWER(?))
                          )
                )
                OR EXISTS (
                    SELECT 1
                    FROM vm_latest_metrics svm
                    WHERE svm.node=l.node
                      AND EXISTS (
                            SELECT 1 FROM vm_inventory svi4
                            WHERE svi4.node=svm.node AND svi4.vm_uuid=svm.vm_uuid
                              AND COALESCE(svi4.status, 'active')!='hidden'
                              AND svi4.deleted_at IS NULL
                          )
                      AND (
                            svm.vm_uuid LIKE ?
                            OR COALESCE(svm.iface, '') LIKE ?
                            OR COALESCE(svm.bridge, '') LIKE ?
                          )
                )
                OR EXISTS (
                    SELECT 1
                    FROM node_physical_net_latest snp
                    WHERE snp.node=l.node
                      AND (
                            COALESCE(snp.iface, '') LIKE ?
                            OR COALESCE(snp.bridge, '') LIKE ?
                            OR COALESCE(snp.role, '') LIKE ?
                            OR COALESCE(snp.mac, '') LIKE ?
                            OR (?<>'' AND LOWER(COALESCE(snp.mac,''))=LOWER(?))
                          )
                )
              )
    ),
    selected AS (
        SELECT
            v.node, v.latest_bucket, v.live_last_seen,
            COALESCE(
                (SELECT MAX(s2.bucket) FROM node_push_snapshots s2
                 WHERE s2.node=v.node AND s2.bucket<=CASE WHEN ?>0 THEN ? ELSE v.latest_bucket-? END),
                (SELECT MIN(s3.bucket) FROM node_push_snapshots s3 WHERE s3.node=v.node)
            ) AS selected_bucket
        FROM visible v
    ),
    snap AS (
        SELECT s.node, s.bucket, s.retention_tier, s.vm_count, s.iface_count
        FROM node_push_snapshots s
        JOIN selected x ON x.node=s.node AND x.selected_bucket=s.bucket
    ),
    vm_net AS (
        SELECT
            ns.node,
            COUNT(DISTINCT ns.vm_uuid) AS vm_count,
            COUNT(DISTINCT ns.bridge || ':' || ns.iface) AS iface_count,
            SUM(CASE WHEN ns.bridge='{PUBLIC_BRIDGE}' THEN ns.rx_delta+ns.tx_delta ELSE 0 END) AS public_total,
            SUM(CASE WHEN ns.bridge='{PRIVATE_BRIDGE}' THEN ns.rx_delta+ns.tx_delta ELSE 0 END) AS private_total,
            SUM(CASE WHEN ns.bridge='{PUBLIC_BRIDGE}' THEN ns.rx_packets_delta+ns.tx_packets_delta ELSE 0 END) AS public_packets,
            SUM(CASE WHEN ns.bridge='{PRIVATE_BRIDGE}' THEN ns.rx_packets_delta+ns.tx_packets_delta ELSE 0 END) AS private_packets,
            SUM(CASE WHEN ns.bridge='{PUBLIC_BRIDGE}' THEN ns.rx_drop_delta+ns.tx_drop_delta ELSE 0 END) AS public_drops,
            SUM(CASE WHEN ns.bridge='{PRIVATE_BRIDGE}' THEN ns.rx_drop_delta+ns.tx_drop_delta ELSE 0 END) AS private_drops,
            SUM(CASE WHEN ns.bridge='{PUBLIC_BRIDGE}' THEN ns.rx_error_delta+ns.tx_error_delta ELSE 0 END) AS public_errors,
            SUM(CASE WHEN ns.bridge='{PRIVATE_BRIDGE}' THEN ns.rx_error_delta+ns.tx_error_delta ELSE 0 END) AS private_errors,
            MAX(CASE WHEN ns.bridge='{PUBLIC_BRIDGE}' THEN COALESCE(ns.interval_seconds, {CACHE_BUCKET_SECONDS}) ELSE 0 END) AS public_interval,
            MAX(CASE WHEN ns.bridge='{PRIVATE_BRIDGE}' THEN COALESCE(ns.interval_seconds, {CACHE_BUCKET_SECONDS}) ELSE 0 END) AS private_interval,
            MAX(COALESCE(ns.interval_seconds, {CACHE_BUCKET_SECONDS})) AS node_interval
        FROM node_stats ns
        JOIN selected x ON x.node=ns.node AND x.selected_bucket=ns.bucket
        LEFT JOIN vm_inventory vi ON vi.node=ns.node AND vi.vm_uuid=ns.vm_uuid
        WHERE COALESCE(vi.status, 'active')!='hidden'
          AND vi.deleted_at IS NULL
        GROUP BY ns.node
    ),
    phys_role AS (
        SELECT
            np.node,
            LOWER(COALESCE(NULLIF(np.role, ''), CASE WHEN np.bridge='{PUBLIC_BRIDGE}' THEN 'public' WHEN np.bridge='{PRIVATE_BRIDGE}' THEN 'private' ELSE np.bridge END)) AS role,
            GROUP_CONCAT(DISTINCT np.iface) AS ifaces,
            SUM(np.rx_delta+np.tx_delta) AS total,
            SUM(np.rx_packets_delta+np.tx_packets_delta) AS packets,
            SUM(np.rx_drop_delta+np.tx_drop_delta) AS drops,
            SUM(np.rx_error_delta+np.tx_error_delta) AS errors,
            MAX(COALESCE(np.interval_seconds, {CACHE_BUCKET_SECONDS})) AS interval_seconds
        FROM node_physical_net_stats np
        JOIN selected x ON x.node=np.node AND x.selected_bucket=np.bucket
        GROUP BY np.node, 2
    ),
    phys AS (
        SELECT
            node,
            MAX(CASE WHEN role='public' THEN 1 ELSE 0 END) AS public_present,
            MAX(CASE WHEN role='private' THEN 1 ELSE 0 END) AS private_present,
            SUM(CASE WHEN role='public' THEN total ELSE 0 END) AS public_total,
            SUM(CASE WHEN role='private' THEN total ELSE 0 END) AS private_total,
            SUM(CASE WHEN role='public' THEN packets ELSE 0 END) AS public_packets,
            SUM(CASE WHEN role='private' THEN packets ELSE 0 END) AS private_packets,
            SUM(CASE WHEN role='public' THEN drops ELSE 0 END) AS public_drops,
            SUM(CASE WHEN role='private' THEN drops ELSE 0 END) AS private_drops,
            SUM(CASE WHEN role='public' THEN errors ELSE 0 END) AS public_errors,
            SUM(CASE WHEN role='private' THEN errors ELSE 0 END) AS private_errors,
            MAX(CASE WHEN role='public' THEN interval_seconds ELSE 0 END) AS public_interval,
            MAX(CASE WHEN role='private' THEN interval_seconds ELSE 0 END) AS private_interval,
            MAX(CASE WHEN role='public' THEN ifaces END) AS public_ifaces,
            MAX(CASE WHEN role='private' THEN ifaces END) AS private_ifaces
        FROM phys_role
        WHERE role IN ('public', 'private')
        GROUP BY node
    ),
    bridge_ip AS (
        SELECT
            node,
            MAX(CASE WHEN LOWER(role)='public' THEN primary_ipv4 ELSE '' END) AS public_ipv4,
            MAX(CASE WHEN LOWER(role)='private' THEN primary_ipv4 ELSE '' END) AS private_ipv4
        FROM node_bridge_addresses_latest
        GROUP BY node
    ),
    host AS (
        SELECT h.*
        FROM node_host_stats h
        JOIN selected x ON x.node=h.node AND x.selected_bucket=h.bucket
        WHERE h.id=(
            SELECT h2.id FROM node_host_stats h2
            WHERE h2.node=h.node AND h2.bucket=h.bucket
            ORDER BY h2.time DESC, h2.id DESC LIMIT 1
        )
    )
    SELECT
        x.node,
        x.live_last_seen,
        x.selected_bucket,
        COALESCE(s.retention_tier, 'raw') AS retention_tier,
        COALESCE(NULLIF(s.vm_count, 0), vn.vm_count, 0) AS vm_count,
        COALESCE(NULLIF(s.iface_count, 0), vn.iface_count, 0) AS iface_count,
        CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_total,0) ELSE COALESCE(vn.public_total,0) END AS public_total,
        CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_total,0) ELSE COALESCE(vn.private_total,0) END AS private_total,
        (CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_total,0) ELSE COALESCE(vn.public_total,0) END +
         CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_total,0) ELSE COALESCE(vn.private_total,0) END) AS node_total,
        CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_packets,0) ELSE COALESCE(vn.public_packets,0) END AS public_packets,
        CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_packets,0) ELSE COALESCE(vn.private_packets,0) END AS private_packets,
        CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(NULLIF(p.public_interval,0),{CACHE_BUCKET_SECONDS}) ELSE COALESCE(NULLIF(vn.public_interval,0),{CACHE_BUCKET_SECONDS}) END AS public_interval,
        CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(NULLIF(p.private_interval,0),{CACHE_BUCKET_SECONDS}) ELSE COALESCE(NULLIF(vn.private_interval,0),{CACHE_BUCKET_SECONDS}) END AS private_interval,
        (CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_packets,0) ELSE COALESCE(vn.public_packets,0) END +
         CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_packets,0) ELSE COALESCE(vn.private_packets,0) END) AS node_packets,
        MAX(COALESCE(NULLIF(p.public_interval,0),0), COALESCE(NULLIF(p.private_interval,0),0), COALESCE(NULLIF(vn.node_interval,0),{CACHE_BUCKET_SECONDS})) AS node_interval,
        (CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_drops,0) ELSE COALESCE(vn.public_drops,0) END +
         CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_drops,0) ELSE COALESCE(vn.private_drops,0) END) AS net_drops,
        (CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_errors,0) ELSE COALESCE(vn.public_errors,0) END +
         CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_errors,0) ELSE COALESCE(vn.private_errors,0) END) AS net_errors,
        CASE WHEN h.node IS NULL THEN 0 ELSE 1 END AS host_present,
        COALESCE(h.load1,0) AS load1,
        COALESCE(h.load5,0) AS load5,
        COALESCE(h.load15,0) AS load15,
        COALESCE(h.cpu_count,0) AS cpu_count,
        COALESCE(h.cpu_percent,0) AS cpu_percent,
        CASE WHEN COALESCE(h.mem_total,0)>0 THEN h.mem_used*100.0/h.mem_total ELSE 0 END AS ram_percent,
        COALESCE(h.disk_read_bps,0) AS disk_read_bps,
        COALESCE(h.disk_write_bps,0) AS disk_write_bps,
        COALESCE(h.uptime_seconds,0) AS uptime_seconds,
        CASE
            WHEN COALESCE(p.public_present,0)=1 AND COALESCE(p.private_present,0)=1 THEN 'NIC'
            WHEN COALESCE(p.public_present,0)=1 OR COALESCE(p.private_present,0)=1 THEN 'MIXED'
            WHEN vn.node IS NOT NULL THEN 'VM'
            ELSE '-'
        END AS net_source,
        COALESCE(p.public_ifaces, '-') AS public_ifaces,
        COALESCE(p.private_ifaces, '-') AS private_ifaces,
        (CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_packets,0) ELSE COALESCE(vn.public_packets,0) END)*1.0 /
            MAX(CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(NULLIF(p.public_interval,0),{CACHE_BUCKET_SECONDS}) ELSE COALESCE(NULLIF(vn.public_interval,0),{CACHE_BUCKET_SECONDS}) END,1) AS public_pps_sort,
        (CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_packets,0) ELSE COALESCE(vn.private_packets,0) END)*1.0 /
            MAX(CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(NULLIF(p.private_interval,0),{CACHE_BUCKET_SECONDS}) ELSE COALESCE(NULLIF(vn.private_interval,0),{CACHE_BUCKET_SECONDS}) END,1) AS private_pps_sort,
        (CASE WHEN COALESCE(p.public_present,0)=1 THEN COALESCE(p.public_packets,0) ELSE COALESCE(vn.public_packets,0) END +
         CASE WHEN COALESCE(p.private_present,0)=1 THEN COALESCE(p.private_packets,0) ELSE COALESCE(vn.private_packets,0) END)*1.0 /
            MAX(COALESCE(NULLIF(p.public_interval,0),0), COALESCE(NULLIF(p.private_interval,0),0), COALESCE(NULLIF(vn.node_interval,0),{CACHE_BUCKET_SECONDS}),1) AS node_pps_sort,
        COALESCE(bip.public_ipv4, '') AS public_ipv4,
        COALESCE(bip.private_ipv4, '') AS private_ipv4
    FROM selected x
    LEFT JOIN snap s ON s.node=x.node AND s.bucket=x.selected_bucket
    LEFT JOIN vm_net vn ON vn.node=x.node
    LEFT JOIN phys p ON p.node=x.node
    LEFT JOIN bridge_ip bip ON bip.node=x.node
    LEFT JOIN host h ON h.node=x.node
    ORDER BY {order_sql} {order.upper()}, x.node COLLATE NOCASE ASC
    """

    conn = db()
    try:
        search_params = [
            q,
            like,  # node name
            like, like, like, like, like, like, normalized_mac, normalized_mac,  # node bridge address/bridge/MAC
            like, like, like,  # vm_inventory
            like, like, like,  # vm_location_latest
            like, like, like,  # vm_node_presence
            like, like, normalized_mac, normalized_mac,  # vm_iface_current iface/MAC
            like, like, like,  # vm_latest_metrics
            like, like, like, like, normalized_mac, normalized_mac,  # physical iface/bridge/role/MAC
        ]
        selection_limit = requested if target_ts is not None else 0
        rows = conn.execute(sql, [visible_after] + search_params + [selection_limit, selection_limit, offset]).fetchall()
    finally:
        conn.close()

    # Display the real retained bucket selected by the query, not the wall-clock
    # target. This mirrors the VM Abuse timeline, where the UI shows the actual
    # sample/event timestamp that backs the displayed metrics. Nodes can be a
    # few seconds apart, so the per-node SNAPSHOT column remains authoritative.
    selected_buckets = [safe_int(row[2], 0) for row in rows if safe_int(row[2], 0) > 0]
    selected_display = max(selected_buckets) if selected_buckets else requested
    return rows, selected_display, now



def query_node_bridge(node, period, bridge, q="", limit=1000, sort_by="total", order="desc", vm_status="active"):
    """Return one exact network snapshot joined to the nearest VM perf snapshot.

    v48.6.2 fixes the old positional bind order that accidentally queried
    vm_perf_stats.bucket=300. That was why node detail rows showed CPU=0,
    vCPU=0 and RAM='-' while the Top VM page still had real values.
    """
    auto_cleanup_inventory()
    auto_purge_migrated_vms()
    sort_by = clean_interface_sort(sort_by)
    order = clean_sort_order(order)

    order_map = {
        "rx": "rx", "tx": "tx", "total": "total",
        "mbps": "avg_mbps", "peakmbps": "peak_mbps",
        "pps": "avg_pps", "peakpps": "peak_pps",
        "sample": "sample_quality_rank",
        "drops": "drops", "errors": "errors",
        "cpu": "core_cpu_percent", "vcpu": "vcpu_current",
        "ram": "ram_rss_kib", "diskr": "disk_read_bps", "diskw": "disk_write_bps",
    }
    order_sql = order_map[sort_by]
    status_sql = vm_status_sql("vi", vm_status)

    conn = db()
    try:
        selected_bucket, latest_bucket = resolve_snapshot_bucket(conn, period, node=node)
        net_bucket = resolve_table_snapshot_bucket(conn, "node_stats", node, selected_bucket)
        perf_bucket = resolve_table_snapshot_bucket(conn, "vm_perf_stats", node, selected_bucket)
        if not net_bucket:
            return [], selected_bucket, latest_bucket

        # A newly upgraded node can have a network bucket before its first exact
        # perf bucket. Use the latest perf bucket not newer than one push window.
        if not perf_bucket:
            row = conn.execute(
                "SELECT MAX(bucket) FROM vm_perf_stats WHERE node=? AND bucket<=?",
                (node, selected_bucket + CACHE_BUCKET_SECONDS),
            ).fetchone()
            perf_bucket = int((row or [0])[0] or 0)

        params = [
            CACHE_BUCKET_SECONDS,          # perf disk read denominator
            CACHE_BUCKET_SECONDS,          # perf disk write denominator
            node,                          # perf node
            perf_bucket,                   # perf bucket
            CACHE_BUCKET_SECONDS,          # network avg PPS denominator
            CACHE_BUCKET_SECONDS,          # returned interval fallback
            node,                          # network node
            bridge,                        # network bridge
            net_bucket,                    # network bucket
        ]
        search_sql = ""
        if q:
            search_sql = " AND (ns.vm_uuid LIKE ? OR ns.iface LIKE ? OR ns.node LIKE ?)"
            p = like_pattern(q)
            params.extend([p, p, p])
        params.append(max(1, min(5000, safe_int(limit, 1000))))

        rows = conn.execute(f"""
            WITH perf AS (
                SELECT
                    node,
                    vm_uuid,
                    MAX(COALESCE(cpu_percent, 0)) AS cpu_percent,
                    MAX(COALESCE(vcpu_current, 0)) AS vcpu_current,
                    MAX(COALESCE(ram_rss_kib, 0)) AS ram_rss_kib,
                    MAX(COALESCE(ram_current_kib, 0)) AS ram_current_kib,
                    MAX(COALESCE(disk_read_delta, 0) * 1.0 /
                        MAX(COALESCE(interval_seconds, ?), 1)) AS disk_read_bps,
                    MAX(COALESCE(disk_write_delta, 0) * 1.0 /
                        MAX(COALESCE(interval_seconds, ?), 1)) AS disk_write_bps
                FROM vm_perf_stats
                WHERE node=? AND bucket=?
                GROUP BY node, vm_uuid
            )
            SELECT
                ns.iface,
                ns.vm_uuid,
                SUM(COALESCE(ns.rx_delta, 0)) AS rx,
                SUM(COALESCE(ns.tx_delta, 0)) AS tx,
                SUM(COALESCE(ns.rx_delta, 0) + COALESCE(ns.tx_delta, 0)) AS total,
                SUM(COALESCE(ns.rx_packets_delta, 0)) AS rx_packets,
                SUM(COALESCE(ns.tx_packets_delta, 0)) AS tx_packets,
                SUM(COALESCE(ns.rx_packets_delta, 0) + COALESCE(ns.tx_packets_delta, 0)) AS packets,
                SUM(COALESCE(ns.rx_drop_delta, 0) + COALESCE(ns.tx_drop_delta, 0)) AS drops,
                SUM(COALESCE(ns.rx_error_delta, 0) + COALESCE(ns.tx_error_delta, 0)) AS errors,
                SUM((COALESCE(ns.rx_delta, 0) + COALESCE(ns.tx_delta, 0)) * 8.0 /
                    MAX(COALESCE(ns.interval_seconds, 1), 1) / 1000000.0) AS avg_mbps,
                MAX(MAX(COALESCE(ns.rx_mbps_peak, 0), COALESCE(ns.tx_mbps_peak, 0))) AS peak_mbps,
                SUM(COALESCE(ns.rx_packets_delta, 0) + COALESCE(ns.tx_packets_delta, 0)) * 1.0 /
                    MAX(MAX(COALESCE(ns.interval_seconds, ?)), 1) AS avg_pps,
                MAX(MAX(COALESCE(ns.rx_pps_peak, 0), COALESCE(ns.tx_pps_peak, 0))) AS peak_pps,
                SUM(COALESCE(ns.network_sample_count, 0)) AS sample_count,
                SUM(COALESCE(ns.network_sample_expected, 0)) AS sample_expected,
                MAX(COALESCE(ns.network_sample_max_gap_seconds, 0)) AS sample_max_gap_seconds,
                SUM(COALESCE(ns.seconds_over_pps, 0)) AS seconds_over_pps,
                SUM(COALESCE(ns.seconds_over_mbps, 0)) AS seconds_over_mbps,
                MAX(CASE UPPER(COALESCE(ns.network_sample_quality, 'LEGACY'))
                    WHEN 'POOR' THEN 3
                    WHEN 'DEGRADED' THEN 2
                    WHEN 'GOOD' THEN 1
                    ELSE 0
                END) AS sample_quality_rank,
                MAX(COALESCE(p.cpu_percent, 0)) AS cpu_percent,
                MAX(COALESCE(p.vcpu_current, 0)) AS vcpu_current,
                MAX(CASE
                    WHEN COALESCE(p.cpu_percent, 0) <= 100
                    THEN COALESCE(p.cpu_percent, 0) *
                        CASE WHEN COALESCE(p.vcpu_current, 0) > 0 THEN p.vcpu_current ELSE 1 END
                    ELSE COALESCE(p.cpu_percent, 0)
                END) AS core_cpu_percent,
                MAX(COALESCE(p.ram_rss_kib, 0)) AS ram_rss_kib,
                MAX(COALESCE(p.ram_current_kib, 0)) AS ram_current_kib,
                MAX(COALESCE(p.disk_read_bps, 0)) AS disk_read_bps,
                MAX(COALESCE(p.disk_write_bps, 0)) AS disk_write_bps,
                MAX(COALESCE(vi.status, 'active')) AS vm_status,
                MAX(ns.last_push) AS last_push,
                MAX(COALESCE(vi.last_seen, ns.last_push)) AS vm_last_seen,
                MAX(COALESCE(ns.interval_seconds, ?)) AS interval_seconds
            FROM node_stats ns
            LEFT JOIN vm_inventory vi
              ON vi.node=ns.node AND vi.vm_uuid=ns.vm_uuid
            LEFT JOIN perf p
              ON p.node=ns.node AND p.vm_uuid=ns.vm_uuid
            WHERE ns.node=? AND ns.bridge=? AND ns.bucket=?
              {status_sql}
              {search_sql}
            GROUP BY ns.iface, ns.vm_uuid
            ORDER BY {order_sql} {order.upper()}, total DESC,
                     ns.iface COLLATE NOCASE ASC, ns.vm_uuid COLLATE NOCASE ASC
            LIMIT ?
        """, params).fetchall()
        return rows, selected_bucket, latest_bucket
    finally:
        conn.close()

def get_node_overview(node, period, q="", vm_status="active"):
    """Return network counters from one exact selected push bucket."""
    auto_cleanup_inventory()
    status_sql = "AND COALESCE(vi.status, 'active') != 'hidden'"
    conn = db()
    try:
        selected_bucket, _latest_bucket = resolve_snapshot_bucket(conn, period, node=node)
        net_bucket = resolve_table_snapshot_bucket(conn, "node_stats", node, selected_bucket)
        if not net_bucket:
            return (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, CACHE_BUCKET_SECONDS)

        params = [PUBLIC_BRIDGE, PUBLIC_BRIDGE, PUBLIC_BRIDGE,
                  PRIVATE_BRIDGE, PRIVATE_BRIDGE, PRIVATE_BRIDGE,
                  node, net_bucket]
        search_sql = ""
        if q:
            search_sql = " AND (ns.vm_uuid LIKE ? OR ns.iface LIKE ? OR ns.node LIKE ?)"
            p = like_pattern(q)
            params.extend([p, p, p])

        row = conn.execute(f"""
            SELECT
                COUNT(DISTINCT ns.vm_uuid) AS vm_count,
                COUNT(DISTINCT ns.bridge || ':' || ns.iface) AS iface_count,
                SUM(CASE WHEN ns.bridge=? THEN ns.rx_delta ELSE 0 END) AS public_rx,
                SUM(CASE WHEN ns.bridge=? THEN ns.tx_delta ELSE 0 END) AS public_tx,
                SUM(CASE WHEN ns.bridge=? THEN ns.rx_delta + ns.tx_delta ELSE 0 END) AS public_total,
                SUM(CASE WHEN ns.bridge=? THEN ns.rx_delta ELSE 0 END) AS private_rx,
                SUM(CASE WHEN ns.bridge=? THEN ns.tx_delta ELSE 0 END) AS private_tx,
                SUM(CASE WHEN ns.bridge=? THEN ns.rx_delta + ns.tx_delta ELSE 0 END) AS private_total,
                SUM(ns.rx_delta) AS node_rx,
                SUM(ns.tx_delta) AS node_tx,
                SUM(ns.rx_delta + ns.tx_delta) AS node_total,
                SUM(ns.rx_packets_delta + ns.tx_packets_delta) AS node_packets,
                SUM(ns.rx_drop_delta + ns.tx_drop_delta) AS node_drops,
                SUM(ns.rx_error_delta + ns.tx_error_delta) AS node_errors,
                MAX(ns.last_push) AS last_push,
                MAX(COALESCE(ns.interval_seconds, ?)) AS interval_seconds
            FROM node_stats ns
            LEFT JOIN vm_inventory vi
              ON vi.node = ns.node
             AND vi.vm_uuid = ns.vm_uuid
            WHERE ns.node=? AND ns.bucket=?
              {status_sql}
              {search_sql}
        """, params[:6] + [CACHE_BUCKET_SECONDS] + params[6:]).fetchone()
        if not row:
            return (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, CACHE_BUCKET_SECONDS)
        return row
    finally:
        conn.close()

def node_sort_header(label, key, period, q, current_sort, current_order, vm_status="active"):
    current_sort = clean_node_sort(current_sort)
    current_order = clean_sort_order(current_order)
    default_order = "asc" if key == "node" else "desc"
    next_order = reverse_order(current_order) if current_sort == key else default_order
    arrow = ""
    if current_sort == key:
        arrow = " ↓" if current_order == "desc" else " ↑"
    href = url_for(
        "index",
        period=period,
        q=q,
        sort=key,
        order=next_order,
    )
    return f'<a class="sort-link" href="{escape(href, quote=True)}">{escape(label)}{arrow}</a>'


def compact_ipv4(value):
    """Return an IPv4 address without CIDR prefix for compact dashboard display."""
    value = str(value or "").strip()
    return value.split("/", 1)[0] if value else ""


V5054_DASHBOARD_CSS = r'''
<style id="v5054-dashboard-column-alignment">
.node-dashboard-table{min-width:1960px;table-layout:auto}
.node-dashboard-table th,.node-dashboard-table td{vertical-align:middle}
.node-dashboard-table .dashboard-load-col{width:148px;min-width:148px;max-width:148px;text-align:center;white-space:nowrap}
.node-dashboard-table .dashboard-load-pill{display:inline-flex;box-sizing:border-box;width:132px;min-width:132px;max-width:132px;justify-content:center;align-items:center;white-space:nowrap;font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1}
.node-dashboard-table .dashboard-interface-col{width:210px;min-width:210px;max-width:210px}
.node-dashboard-table .dashboard-interface-cell{width:210px;min-width:210px;max-width:210px;overflow:hidden}
.node-dashboard-table .dashboard-interface-wrap{display:flex;flex-direction:column;align-items:flex-start;gap:3px;min-width:0}
.node-dashboard-table .dashboard-interface-wrap small{display:block;width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.node-dashboard-table .dashboard-interface-wrap .vm-state{display:inline-flex;box-sizing:border-box;min-width:64px;justify-content:center;text-align:center;flex:0 0 auto}
@media(max-width:1500px){.node-dashboard-table{min-width:1880px}.node-dashboard-table .dashboard-interface-col,.node-dashboard-table .dashboard-interface-cell{width:190px;min-width:190px;max-width:190px}}
</style>
'''


def dashboard_load_html(load1, load5, load15, cpu_count, host_present=True):
    """Render a fixed-width Load 1/5/15 pill for stable dashboard alignment."""
    if not host_present:
        return '<span class="metric-pill metric-unknown dashboard-load-pill" title="Host load is not reported">-</span>'

    values = f"{float(load1 or 0):.2f} / {float(load5 or 0):.2f} / {float(load15 or 0):.2f}"
    cores = max(0, safe_int(cpu_count, 0))
    if cores <= 0:
        return (
            '<span class="metric-pill metric-unknown dashboard-load-pill" '
            'title="CPU core count is missing in this retained snapshot">'
            f'{values}</span>'
        )

    load_pct = max(0.0, float(load1 or 0) * 100.0 / float(cores))
    if load_pct < 60.0:
        level = "ok"
    elif load_pct < 90.0:
        level = "warn"
    else:
        level = "crit"

    return (
        f'<span class="metric-pill metric-{level} dashboard-load-pill" '
        f'title="Load1 {load_pct:.1f}% of {cores} CPU cores; green &lt;60%, orange 60-&lt;90%, red ≥90%">'
        f'{values}</span>'
    )


def node_table(rows, sort_by="node", order="asc"):
    period = clean_period(request.args.get("period", "5m"))
    q = (request.args.get("q") or "").strip()
    body = ""
    total_nodes = len(rows)
    total_vms = sum(int(row[4] or 0) for row in rows)
    total_public = total_private = total_all = 0.0

    for row in rows:
        (
            node, live_last_seen, selected_bucket, retention_tier, vm_count, iface_count,
            public_total, private_total, node_total,
            public_packets, private_packets, public_interval, private_interval,
            node_packets, node_interval, net_drops, net_errors,
            host_present, load1, load5, load15, cpu_count, cpu_percent, ram_percent,
            disk_read_bps, disk_write_bps, uptime_seconds,
            net_source, public_ifaces, private_ifaces,
            public_pps_sort, private_pps_sort, node_pps_sort,
            public_ipv4, private_ipv4,
        ) = row
        total_public += float(public_total or 0)
        total_private += float(private_total or 0)
        total_all += float(node_total or 0)
        _row_at = (request.args.get("at") or "").strip()
        href = url_for("node_page", node=node, period=period, **({"at": _row_at} if _row_at else {}))
        source = str(net_source or "-")
        source_cls = "active" if source == "NIC" else ("yellow" if source in ("MIXED", "VM") else "stale")
        iface_note = ""
        if source in ("NIC", "MIXED"):
            iface_note = f'<small title="Public {escape(str(public_ifaces or "-"), quote=True)} · Private {escape(str(private_ifaces or "-"), quote=True)}">pub {escape(str(public_ifaces or "-"))} · pri {escape(str(private_ifaces or "-"))}</small>'
        elif source == "VM":
            source = "VM TAP"
            iface_note = '<small class="metric-subline">physical uplink sample unavailable</small>'
        load_html = dashboard_load_html(load1, load5, load15, cpu_count, host_present=bool(host_present))
        cpu_html = fmt_percent(cpu_percent) if host_present else "-"
        ram_html = fmt_percent(ram_percent) if host_present else "-"
        disk_r_html = human_rate(disk_read_bps) if host_present else "-"
        disk_w_html = human_rate(disk_write_bps) if host_present else "-"
        public_pps = float(public_packets or 0) / max(1.0, float(public_interval or CACHE_BUCKET_SECONDS))
        private_pps = float(private_packets or 0) / max(1.0, float(private_interval or CACHE_BUCKET_SECONDS))

        body += f"""
        <tr>
            <td>
                <div class="node-name-cell">
                    <a href="{escape(href, quote=True)}"><b>{escape(node)}</b></a>
                    {f'<small class="node-ipv4" title="Public IPv4">{escape(compact_ipv4(public_ipv4))}</small>' if public_ipv4 else ''}
                </div>
            </td>
            <td>{status_badge(live_last_seen)}</td>
            <td class="mono">{fmt_full(selected_bucket)}</td>
            <td class="num">{int(vm_count or 0)}</td>
            <td class="num dashboard-load-col" title="Host load average captured at the displayed snapshot">{load_html}</td>
            <td class="num">{fmt_uptime(uptime_seconds) if host_present else '-'}</td>
            <td class="num">{cpu_html}</td>
            <td class="num">{ram_html}</td>
            <td class="num">{fmt_pps_value(public_pps)}</td>
            <td class="num">{fmt_pps_value(private_pps)}</td>
            <td class="num"><b>{human(public_total)}</b></td>
            <td class="num"><b>{human(private_total)}</b></td>
            <td class="num"><b>{human(node_total)}</b></td>
            <td class="num">{disk_r_html}</td>
            <td class="num">{disk_w_html}</td>
            <td class="num">{int(net_drops or 0)}</td>
            <td class="num">{int(net_errors or 0)}</td>
            <td class="dashboard-interface-cell"><div class="dashboard-interface-wrap"><span class="vm-state {source_cls}">{escape(source)}</span>{iface_note}</div></td>
        </tr>
        """

    if not body:
        body = '<tr><td colspan="18" class="empty">No retained snapshot data</td></tr>'

    headers = {
        "node": node_sort_header("NODE", "node", period, q, sort_by, order),
        "status": node_sort_header("STATUS", "last_push", period, q, sort_by, order),
        "snapshot": node_sort_header("SNAPSHOT", "snapshot", period, q, sort_by, order),
        "vm": node_sort_header("VM", "vm", period, q, sort_by, order),
        "load": node_sort_header("LOAD 1/5/15", "load", period, q, sort_by, order),
        "uptime": node_sort_header("UPTIME", "uptime", period, q, sort_by, order),
        "cpu": node_sort_header("HOST CPU", "cpu", period, q, sort_by, order),
        "ram": node_sort_header("HOST RAM", "ram", period, q, sort_by, order),
        "pubpps": node_sort_header("PUBLIC PPS", "public_pps", period, q, sort_by, order),
        "pripps": node_sort_header("PRIVATE PPS", "private_pps", period, q, sort_by, order),
        "public": node_sort_header("PUBLIC", "public", period, q, sort_by, order),
        "private": node_sort_header("PRIVATE", "private", period, q, sort_by, order),
        "total": node_sort_header("TOTAL", "total", period, q, sort_by, order),
        "diskr": node_sort_header("DISK R/s", "diskr", period, q, sort_by, order),
        "diskw": node_sort_header("DISK W/s", "diskw", period, q, sort_by, order),
        "drops": node_sort_header("DROPS", "drops", period, q, sort_by, order),
        "errors": node_sort_header("ERR", "errors", period, q, sort_by, order),
        "source": node_sort_header("INTERFACE", "source", period, q, sort_by, order),
    }
    return f"""
    {V5054_DASHBOARD_CSS}
    <div class="card overview-card">
        <div class="overview-head"><h3>Exact Snapshot Summary</h3>
            <div class="overview-meta"><span>Nodes <b>{total_nodes}</b></span><span>VM <b>{total_vms}</b></span><span>Mode <b>one real push per node</b></span></div>
        </div>
        <div class="traffic-grid">
            <div class="traffic-box"><div class="traffic-title">Public</div><div class="traffic-total">{human(total_public)}</div></div>
            <div class="traffic-box"><div class="traffic-title">Private</div><div class="traffic-total">{human(total_private)}</div></div>
            <div class="traffic-box traffic-box-main"><div class="traffic-title">Total</div><div class="traffic-total">{human(total_all)}</div></div>
        </div>
    </div>
    <div class="card">
        <div class="table-title-row"><h3>Nodes</h3><div class="count-badges"><span>Sort <b>{escape(sort_by)} {escape(order)}</b></span><span>Status <b>live</b></span><span>Metrics <b>selected snapshot</b></span></div></div>
        <div class="table-wrap"><table class="node-dashboard-table"><thead><tr>
            <th>{headers['node']}</th><th>{headers['status']}</th><th>{headers['snapshot']}</th>
            <th>{headers['vm']}</th><th class="dashboard-load-col">{headers['load']}</th><th>{headers['uptime']}</th><th>{headers['cpu']}</th><th>{headers['ram']}</th>
            <th>{headers['pubpps']}</th><th>{headers['pripps']}</th><th>{headers['public']}</th><th>{headers['private']}</th><th>{headers['total']}</th>
            <th>{headers['diskr']}</th><th>{headers['diskw']}</th><th>{headers['drops']}</th><th>{headers['errors']}</th><th class="dashboard-interface-col">{headers['source']}</th>
        </tr></thead><tbody>{body}</tbody></table></div>
        <div class="table-hint">STATUS is live: Online with fewer than 2 missed pushes, Missed at exactly 2, Down after that. LOAD color uses Load1 / CPU cores: green below 60%, orange from 60% to below 90%, red at 90% or higher. LOAD 1/5/15 and every other metric come from the displayed SNAPSHOT. INTERFACE is shown last to keep the numeric columns aligned.</div>
    </div>
    """



def sort_header(label, key, node, period, q, current_sort, current_order, vm_status="active"):
    current_sort = clean_interface_sort(current_sort)
    current_order = clean_sort_order(current_order)
    next_order = reverse_order(current_order) if current_sort == key else "desc"
    arrow = ""
    if current_sort == key:
        arrow = " ↓" if current_order == "desc" else " ↑"
    net_mode = clean_node_net_mode(request.args.get("net", "both"))
    href = url_for(
        "node_page",
        node=node,
        period=period,
        q=q,
        sort=key,
        order=next_order,
        net=net_mode,
    )
    return f'<a class="sort-link" href="{escape(href, quote=True)}">{escape(label)}{arrow}</a>'


def interface_table(title, bridge, node, rows, period, q="", sort_by="total", order="desc", vm_status="active"):
    body = ""
    for (
        iface, vm_uuid, rx, tx, total, rx_packets, tx_packets, packets, drops, errors,
        avg_mbps, peak_mbps, avg_pps, peak_pps,
        sample_count, sample_expected, sample_max_gap_seconds, seconds_over_pps, seconds_over_mbps, sample_quality_rank,
        cpu_percent, vcpu_current, core_cpu_percent, ram_rss_kib, ram_current_kib,
        disk_read_bps, disk_write_bps, row_vm_status, last_push, vm_last_seen, interval_seconds,
    ) in rows:
        _row_at = (request.args.get("at") or "").strip()
        href = url_for("vm_page", node=node, vm_uuid=vm_uuid, bridge=bridge, iface=iface, period=period, **({"at": _row_at} if _row_at else {}))
        href_e = escape(href, quote=True)
        live = vm_live_status(vm_last_seen)
        row_status = clean_vm_status(row_vm_status)
        row_cls = "clickable stale-row" if (live == "stale" or row_status != "active") else "clickable"
        state_html = vm_status_badge(row_status, live)
        vm_uuid_e = escape(vm_uuid)
        quality = network_quality_from_rank(sample_quality_rank)
        sample_html = network_sample_badge(quality, sample_count, sample_expected, sample_max_gap_seconds)
        ram_pct = (float(ram_rss_kib or 0) * 100.0 / float(ram_current_kib or 1)) if ram_current_kib else 0.0
        ram_html = fmt_ram_pair(ram_rss_kib, ram_current_kib)
        if ram_current_kib:
            ram_html += f'<small class="metric-subline">{ram_pct:.1f}% RSS</small>'
        body += f"""
        <tr class="{row_cls}" onclick="if (!event.target.closest('a, button, input, select, textarea, label, form')) window.location='{href_e}'">
            <td>{state_html}</td>
            <td class="mono"><a href="{href_e}"><b>{escape(iface)}</b></a></td>
            <td class="mono"><span class="uuid-cell"><a href="{href_e}" title="{vm_uuid_e}">{vm_uuid_e}</a><button type="button" class="copy-btn" data-copy="{vm_uuid_e}" title="Copy UUID">⧉</button></span></td>
            <td class="num">{human(rx)}</td>
            <td class="num">{human(tx)}</td>
            <td class="num"><b>{human(total)}</b></td>
            <td class="num">{float(avg_mbps or 0):.2f}</td>
            <td class="num"><b>{float(peak_mbps or 0):.2f}</b></td>
            <td class="num">{fmt_pps_value(avg_pps)}</td>
            <td class="num"><b>{fmt_pps_value(peak_pps)}</b></td>
            <td class="num sample-cell">{sample_html}<small class="metric-subline">{int(seconds_over_pps or 0)}s PPS · {int(seconds_over_mbps or 0)}s Mbps</small></td>
            <td class="num"><b>{fmt_vm_cpu(cpu_percent, vcpu_current)}</b><small class="metric-subline">{float(cpu_percent or 0):.1f}% full</small></td>
            <td class="num">{int(vcpu_current or 0)}</td>
            <td class="num ram-cell">{ram_html}</td>
            <td class="num">{human_rate(disk_read_bps)}</td>
            <td class="num">{human_rate(disk_write_bps)}</td>
            <td class="num">{int(drops or 0)}</td>
            <td class="num">{int(errors or 0)}</td>
        </tr>"""
    if not body:
        body = '<tr><td colspan="18" class="empty">No data in this selected snapshot</td></tr>'

    hs = {
        "rx": sort_header("RX", "rx", node, period, q, sort_by, order, vm_status),
        "tx": sort_header("TX", "tx", node, period, q, sort_by, order, vm_status),
        "total": sort_header("TOTAL", "total", node, period, q, sort_by, order, vm_status),
        "mbps": sort_header("AVG Mbps", "mbps", node, period, q, sort_by, order, vm_status),
        "peakmbps": sort_header("PEAK Mbps", "peakmbps", node, period, q, sort_by, order, vm_status),
        "pps": sort_header("AVG PPS", "pps", node, period, q, sort_by, order, vm_status),
        "peakpps": sort_header("PEAK PPS", "peakpps", node, period, q, sort_by, order, vm_status),
        "sample": sort_header("SAMPLE", "sample", node, period, q, sort_by, order, vm_status),
        "cpu": sort_header("CPU Core%", "cpu", node, period, q, sort_by, order, vm_status),
        "vcpu": sort_header("vCPU", "vcpu", node, period, q, sort_by, order, vm_status),
        "ram": sort_header("RAM RSS / Assigned", "ram", node, period, q, sort_by, order, vm_status),
        "diskr": sort_header("DISK R/s", "diskr", node, period, q, sort_by, order, vm_status),
        "diskw": sort_header("DISK W/s", "diskw", node, period, q, sort_by, order, vm_status),
        "drops": sort_header("DROPS", "drops", node, period, q, sort_by, order, vm_status),
        "errors": sort_header("ERR", "errors", node, period, q, sort_by, order, vm_status),
    }
    return f"""
    <div class="card vm-table-card">
        <div class="table-title-row">
            <h3>{escape(title)}</h3>
            <div class="count-badges"><span>VM rows <b>{len(rows)}</b></span><span>Snapshot <b>exact</b></span></div>
        </div>
        <div class="table-wrap">
        <table class="table-vm">
            <colgroup>
                <col class="col-state"><col class="col-iface"><col class="col-uuid">
                <col class="col-rx"><col class="col-tx"><col class="col-total">
                <col class="col-mbps"><col class="col-peakmbps"><col class="col-pps"><col class="col-peakpps">
                <col class="col-sample"><col class="col-cpu"><col class="col-vcpu"><col class="col-ram">
                <col class="col-diskr"><col class="col-diskw"><col class="col-drops"><col class="col-errors">
            </colgroup>
            <thead><tr>
                <th>STATE</th><th>INTERFACE</th><th>VM UUID</th>
                <th class="num-head">{hs['rx']}</th><th class="num-head">{hs['tx']}</th><th class="num-head">{hs['total']}</th>
                <th class="num-head">{hs['mbps']}</th><th class="num-head">{hs['peakmbps']}</th>
                <th class="num-head">{hs['pps']}</th><th class="num-head">{hs['peakpps']}</th><th class="num-head">{hs['sample']}</th>
                <th class="num-head">{hs['cpu']}</th><th class="num-head">{hs['vcpu']}</th><th class="num-head">{hs['ram']}</th>
                <th class="num-head">{hs['diskr']}</th><th class="num-head">{hs['diskw']}</th><th class="num-head">{hs['drops']}</th><th class="num-head">{hs['errors']}</th>
            </tr></thead>
            <tbody>{body}</tbody>
        </table>
        </div>
        <div class="table-hint">CPU Core% uses 100% per fully used vCPU. The smaller “full” value is utilization across all assigned vCPUs. RAM is RSS / assigned memory.</div>
    </div>"""

def get_node_physical_nic_period(node, period):
    """Return physical-NIC snapshot plus current br0/br1 addresses."""
    period = clean_period(period)
    conn = db()
    try:
        result = {}

        # IPs are current node configuration. They are stored independently from
        # historical counter snapshots because the address belongs to br0/br1.
        address_rows = conn.execute("""
            SELECT role, bridge, last_seen, primary_ipv4,
                   ipv4_json, operstate, carrier, mtu, mac
            FROM node_bridge_addresses_latest
            WHERE node=?
            ORDER BY CASE role WHEN 'public' THEN 1 WHEN 'private' THEN 2 ELSE 9 END, role
        """, (node,)).fetchall()

        for (role, bridge, address_seen, primary_ipv4,
             ipv4_json, operstate, carrier, mtu, mac) in address_rows:
            key = str(role or "").lower()
            result[key] = {
                "role": key,
                "bridge": bridge or "-",
                "iface": "-",
                "rx_mbps": 0.0,
                "tx_mbps": 0.0,
                "rx_pps": 0.0,
                "tx_pps": 0.0,
                "last_seen": int(address_seen or 0),
                "samples": 0,
                "covered_seconds": 0,
                "source": "bridge address",
                "ipv4": decode_ip_json(ipv4_json),
                "primary_ipv4": primary_ipv4 or "",
                "operstate": operstate or "-",
                "carrier": int(carrier or 0),
                "mtu": int(mtu or 0),
                "bridge_mac": normalize_mac_address(mac),
                "mac": "",
            }

        physical_identity_rows = conn.execute("""
            SELECT role,bridge,iface,mac,last_seen
              FROM node_physical_net_latest
             WHERE node=?
             ORDER BY CASE role WHEN 'public' THEN 1 WHEN 'private' THEN 2 ELSE 9 END,role
        """, (node,)).fetchall()
        for role, bridge, iface, mac, identity_seen in physical_identity_rows:
            key = str(role or "").lower()
            current = result.setdefault(key, {
                "role": key,
                "ipv4": [],
                "primary_ipv4": "",
                "operstate": "-",
                "carrier": 0,
                "mtu": 0,
                "bridge_mac": "",
            })
            current["bridge"] = bridge or current.get("bridge") or "-"
            current["iface"] = iface or current.get("iface") or "-"
            current["mac"] = normalize_mac_address(mac)
            current["identity_seen"] = int(identity_seen or 0)

        selected_bucket, _latest_bucket = resolve_snapshot_bucket(conn, period, node=node)
        nic_bucket = resolve_table_snapshot_bucket(conn, "node_physical_net_stats", node, selected_bucket)
        if not nic_bucket:
            return result

        rows = conn.execute("""
            SELECT
                role,
                MAX(bridge) AS bridge,
                MAX(iface) AS iface,
                SUM(COALESCE(rx_delta, 0)) AS rx_delta,
                SUM(COALESCE(tx_delta, 0)) AS tx_delta,
                SUM(COALESCE(rx_packets_delta, 0)) AS rx_packets_delta,
                SUM(COALESCE(tx_packets_delta, 0)) AS tx_packets_delta,
                MAX(COALESCE(interval_seconds, ?)) AS interval_seconds,
                MAX(time) AS last_seen
            FROM node_physical_net_stats
            WHERE node=? AND bucket=?
            GROUP BY role
            ORDER BY CASE role WHEN 'public' THEN 1 WHEN 'private' THEN 2 ELSE 9 END, role
        """, (CACHE_BUCKET_SECONDS, node, nic_bucket)).fetchall()

        for role, bridge, iface, rx_delta, tx_delta, rx_packets, tx_packets, interval_seconds, last_seen in rows:
            key = str(role or "").lower()
            interval = max(1, int(interval_seconds or CACHE_BUCKET_SECONDS))
            current = result.setdefault(key, {
                "role": key,
                "ipv4": [],
                "primary_ipv4": "",
                "operstate": "-",
                "carrier": 0,
                "mtu": 0,
                "bridge_mac": "",
                "mac": "",
            })
            current.update({
                "bridge": bridge or current.get("bridge") or "-",
                "iface": iface or "-",
                "rx_mbps": float(rx_delta or 0) * 8.0 / interval / 1_000_000.0,
                "tx_mbps": float(tx_delta or 0) * 8.0 / interval / 1_000_000.0,
                "rx_pps": float(rx_packets or 0) / interval,
                "tx_pps": float(tx_packets or 0) / interval,
                "last_seen": int(last_seen or nic_bucket),
                "samples": 1,
                "covered_seconds": interval,
                "source": "exact snapshot",
            })
        return result
    finally:
        conn.close()


def node_nic_badges(node, period):
    data = get_node_physical_nic_period(node, period)

    def badge(role, default_bridge):
        r = data.get(role)
        if r:
            bridge = r.get("bridge") or default_bridge
            iface = r.get("iface") or "-"
            label = f"{bridge} / {iface}"
            total_pps = float(r.get("rx_pps") or 0) + float(r.get("tx_pps") or 0)
            ipv4 = ", ".join(r.get("ipv4") or []) or "not assigned"
            traffic = (
                f"RX {float(r.get('rx_mbps') or 0):.2f} Mbps · "
                f"TX {float(r.get('tx_mbps') or 0):.2f} Mbps · "
                f"PPS {fmt_pps_value(total_pps)} · "
                f"snapshot {fmt_push(r.get('last_seen'))}"
            )
            address_detail = f"Current IPv4 {ipv4}"
            physical_mac = normalize_mac_address(r.get("mac")) or "not reported"
            return (
                f'<span class="nic-badge"><b>{role.title()}</b> '
                f'{escape(label)}<small class="nic-address">{escape(address_detail)}</small>'
                f'<small class="nic-address">Physical MAC {escape(physical_mac)}</small>'
                f'<small>{escape(traffic)}</small></span>'
            )
        return (
            f'<span class="nic-badge"><b>{role.title()}</b> '
            f'{escape(default_bridge)} / no data '
            f'<small>Agent has not reported bridge addresses yet</small></span>'
        )

    return f'<div class="nic-map">{badge("public", PUBLIC_BRIDGE)}{badge("private", PRIVATE_BRIDGE)}</div>'


def overview_cards(row, node, period):
    (vm_count, iface_count, pub_rx, pub_tx, pub_total, pri_rx, pri_tx, pri_total,
     node_rx, node_tx, node_total, node_packets, node_drops, node_errors,
     last_push, interval_seconds) = row
    live_last_seen = get_node_live_last_seen(node)
    tier = get_snapshot_tier(node, last_push)
    return f"""
    <div class="card overview-card">
        <div class="overview-head">
            <h3>Overview</h3>
            <div class="overview-meta">
                <span>Live {status_badge(live_last_seen)}</span>
                <span>Snapshot <b>{fmt_full(last_push)}</b></span>
                <span>Resolution <b>{escape(tier)}</b></span>
                <span>VM <b>{vm_count or 0}</b></span>
                <span>Interfaces <b>{iface_count or 0}</b></span>
                <span>PPS <b>{fmt_pps(node_packets, interval_seconds)}</b></span>
                <span>Drops <b>{int(node_drops or 0)}</b></span>
                <span>Err <b>{int(node_errors or 0)}</b></span>
            </div>
        </div>
        {node_nic_badges(node, period)}
        <div class="traffic-grid">
            <div class="traffic-box"><div class="traffic-title">Public</div><div class="traffic-total">{human(pub_total)}</div><div class="traffic-split"><span>RX <b>{human(pub_rx)}</b></span><span>TX <b>{human(pub_tx)}</b></span></div></div>
            <div class="traffic-box"><div class="traffic-title">Private</div><div class="traffic-total">{human(pri_total)}</div><div class="traffic-split"><span>RX <b>{human(pri_rx)}</b></span><span>TX <b>{human(pri_tx)}</b></span></div></div>
            <div class="traffic-box traffic-box-main"><div class="traffic-title">Node</div><div class="traffic-total">{human(node_total)}</div><div class="traffic-split"><span>RX <b>{human(node_rx)}</b></span><span>TX <b>{human(node_tx)}</b></span></div></div>
        </div>
        <div class="table-hint">Status uses the newest heartbeat. Counters and rates use one retained real push only.</div>
    </div>
    """


