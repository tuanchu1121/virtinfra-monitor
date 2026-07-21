V5052_VERSION = "50.5.2"
V5052_IFACE_STAGE = "pg_temp.vi5052_iface_stage"
V5052_VM_STAGE = "pg_temp.vi5052_vm_stage"
V5052_SYNC_STAGE = "pg_temp.vi5052_sync_stage"

def _v5052_create_iface_stage(conn):
    conn.execute("""
      CREATE TEMP TABLE IF NOT EXISTS vi5052_iface_stage (
        ord BIGINT NOT NULL,
        hour_start BIGINT NOT NULL,
        day_start BIGINT NOT NULL,
        bucket BIGINT NOT NULL,
        node TEXT NOT NULL,
        bridge TEXT NOT NULL,
        iface TEXT NOT NULL,
        vm_uuid TEXT NOT NULL,
        mac TEXT,
        last_push BIGINT NOT NULL,
        interval_seconds INTEGER NOT NULL,
        rx_delta BIGINT NOT NULL,
        tx_delta BIGINT NOT NULL,
        rx_packets_delta BIGINT NOT NULL,
        tx_packets_delta BIGINT NOT NULL,
        rx_drop_delta BIGINT NOT NULL,
        tx_drop_delta BIGINT NOT NULL,
        rx_error_delta BIGINT NOT NULL,
        tx_error_delta BIGINT NOT NULL,
        rx_mbps DOUBLE PRECISION NOT NULL,
        tx_mbps DOUBLE PRECISION NOT NULL,
        rx_pps DOUBLE PRECISION NOT NULL,
        tx_pps DOUBLE PRECISION NOT NULL,
        rx_mbps_peak DOUBLE PRECISION NOT NULL,
        tx_mbps_peak DOUBLE PRECISION NOT NULL,
        rx_pps_peak DOUBLE PRECISION NOT NULL,
        tx_pps_peak DOUBLE PRECISION NOT NULL,
        rx_packet_size_avg DOUBLE PRECISION NOT NULL,
        tx_packet_size_avg DOUBLE PRECISION NOT NULL,
        network_sample_count BIGINT NOT NULL,
        network_sample_expected BIGINT NOT NULL,
        network_sample_max_gap_seconds DOUBLE PRECISION NOT NULL,
        seconds_over_pps BIGINT NOT NULL,
        seconds_over_mbps BIGINT NOT NULL,
        seconds_over_rx_pps BIGINT NOT NULL,
        seconds_over_tx_pps BIGINT NOT NULL,
        network_sample_quality TEXT NOT NULL,
        quality_rank INTEGER NOT NULL,
        alert_level TEXT NOT NULL,
        alert_flags TEXT NOT NULL
      ) ON COMMIT DELETE ROWS
    """)

def _v5052_create_vm_stage(conn):
    conn.execute("""
      CREATE TEMP TABLE IF NOT EXISTS vi5052_vm_stage (
        ord BIGINT NOT NULL,
        time BIGINT NOT NULL,
        bucket BIGINT NOT NULL,
        node TEXT NOT NULL,
        vm_uuid TEXT NOT NULL,
        interval_seconds INTEGER NOT NULL,
        current_interval_seconds INTEGER NOT NULL,
        vcpu_current INTEGER NOT NULL,
        cpu_percent DOUBLE PRECISION NOT NULL,
        cpu_full_percent DOUBLE PRECISION NOT NULL,
        cpu_core_percent DOUBLE PRECISION NOT NULL,
        ram_current_kib BIGINT NOT NULL,
        ram_maximum_kib BIGINT NOT NULL,
        ram_rss_kib BIGINT NOT NULL,
        ram_available_kib BIGINT NOT NULL,
        ram_unused_kib BIGINT NOT NULL,
        ram_usable_kib BIGINT NOT NULL,
        disk_read_delta BIGINT NOT NULL,
        disk_write_delta BIGINT NOT NULL,
        disk_read_reqs_delta BIGINT NOT NULL,
        disk_write_reqs_delta BIGINT NOT NULL,
        disk_read_bps DOUBLE PRECISION NOT NULL,
        disk_write_bps DOUBLE PRECISION NOT NULL,
        disk_read_iops DOUBLE PRECISION NOT NULL,
        disk_write_iops DOUBLE PRECISION NOT NULL,
        current_disk_read_bps DOUBLE PRECISION NOT NULL,
        current_disk_write_bps DOUBLE PRECISION NOT NULL,
        current_disk_read_iops DOUBLE PRECISION NOT NULL,
        current_disk_write_iops DOUBLE PRECISION NOT NULL,
        last_push BIGINT NOT NULL
      ) ON COMMIT DELETE ROWS
    """)

def _v5052_iface_rows(node, data_time, bucket, interval_seconds, interfaces):
    columns = (
        "ord", "hour_start", "day_start", "bucket", "node", "bridge", "iface", "vm_uuid", "mac",
        "last_push", "interval_seconds",
        "rx_delta", "tx_delta", "rx_packets_delta", "tx_packets_delta",
        "rx_drop_delta", "tx_drop_delta", "rx_error_delta", "tx_error_delta",
        "rx_mbps", "tx_mbps", "rx_pps", "tx_pps",
        "rx_mbps_peak", "tx_mbps_peak", "rx_pps_peak", "tx_pps_peak",
        "rx_packet_size_avg", "tx_packet_size_avg",
        "network_sample_count", "network_sample_expected",
        "network_sample_max_gap_seconds", "seconds_over_pps", "seconds_over_mbps",
        "seconds_over_rx_pps", "seconds_over_tx_pps",
        "network_sample_quality", "quality_rank", "alert_level", "alert_flags",
    )
    rows = []
    hour_start = local_hour_start(data_time)
    day_start = local_day_start(data_time)
    for ordinal, item in enumerate(interfaces or []):
        if not isinstance(item, dict):
            continue
        vm_uuid = str(item.get("vm_uuid") or "").strip()
        if not vm_uuid or vm_uuid == "-":
            continue
        bridge = str(item.get("bridge") or "-")
        iface = str(item.get("iface") or "-")
        sec = max(1, min(86400, safe_int(item.get("interval_seconds"), interval_seconds)))
        rx_delta = max(0, safe_int(item.get("rx_delta"), 0))
        tx_delta = max(0, safe_int(item.get("tx_delta"), 0))
        rx_packets = max(0, safe_int(item.get("rx_packets_delta"), 0))
        tx_packets = max(0, safe_int(item.get("tx_packets_delta"), 0))
        rx_drop = max(0, safe_int(item.get("rx_drop_delta"), 0))
        tx_drop = max(0, safe_int(item.get("tx_drop_delta"), 0))
        rx_error = max(0, safe_int(item.get("rx_error_delta"), 0))
        tx_error = max(0, safe_int(item.get("tx_error_delta"), 0))
        rx_mbps = rx_delta * 8.0 / sec / 1000000.0
        tx_mbps = tx_delta * 8.0 / sec / 1000000.0
        rx_pps = rx_packets / float(sec)
        tx_pps = tx_packets / float(sec)
        rx_mbps_peak = max(rx_mbps, safe_float(item.get("rx_mbps_peak"), 0.0))
        tx_mbps_peak = max(tx_mbps, safe_float(item.get("tx_mbps_peak"), 0.0))
        rx_pps_peak = max(rx_pps, safe_float(item.get("rx_pps_peak"), 0.0))
        tx_pps_peak = max(tx_pps, safe_float(item.get("tx_pps_peak"), 0.0))
        quality = clean_network_sample_quality(item.get("network_sample_quality"))
        over_rx = max(0, safe_int(item.get("seconds_over_rx_pps"), 0))
        over_tx = max(0, safe_int(item.get("seconds_over_tx_pps"), 0))
        combined = max(0, safe_int(item.get("seconds_over_pps"), 0))
        if over_rx == 0 and over_tx == 0 and combined:
            if max(rx_pps, rx_pps_peak) >= ABUSE_NETWORK_PPS:
                over_rx = combined
            if max(tx_pps, tx_pps_peak) >= ABUSE_NETWORK_PPS:
                over_tx = combined
        flags = []
        peak_pps = max(rx_pps_peak, tx_pps_peak)
        peak_mbps = max(rx_mbps_peak, tx_mbps_peak)
        if peak_pps >= VM_NET_CRIT_PPS > 0:
            flags.append("PPS_PEAK_CRITICAL")
        elif peak_pps >= VM_NET_WARN_PPS > 0:
            flags.append("PPS_PEAK_HIGH")
        if peak_mbps >= VM_NET_CRIT_MBPS > 0:
            flags.append("MBPS_PEAK_CRITICAL")
        elif peak_mbps >= VM_NET_WARN_MBPS > 0:
            flags.append("MBPS_PEAK_HIGH")
        if quality == "POOR":
            flags.append("SAMPLE_POOR")
        rows.append((
            ordinal, hour_start, day_start, bucket, node, bridge, iface, vm_uuid,
            normalize_mac_address(item.get("mac")), data_time, sec,
            rx_delta, tx_delta, rx_packets, tx_packets,
            rx_drop, tx_drop, rx_error, tx_error,
            rx_mbps, tx_mbps, rx_pps, tx_pps,
            rx_mbps_peak, tx_mbps_peak, rx_pps_peak, tx_pps_peak,
            max(0.0, safe_float(item.get("rx_packet_size_avg"), 0.0)),
            max(0.0, safe_float(item.get("tx_packet_size_avg"), 0.0)),
            max(0, safe_int(item.get("network_sample_count"), 0)),
            max(0, safe_int(item.get("network_sample_expected"), 0)),
            max(0.0, safe_float(item.get("network_sample_max_gap_seconds"), 0.0)),
            combined,
            max(0, safe_int(item.get("seconds_over_mbps"), 0)),
            over_rx, over_tx, quality, network_sample_quality_rank(quality),
            "warn" if flags else "ok", ",".join(flags),
        ))
    return columns, rows

def _v5052_write_interface_copy_batch(conn, node, data_time, bucket, interval_seconds, interfaces):
    _v5052_create_iface_stage(conn)
    columns, rows = _v5052_iface_rows(node, data_time, bucket, interval_seconds, interfaces)
    copy_started = time.perf_counter()
    if rows:
        conn.copy_rows(V5052_IFACE_STAGE, columns, rows)
    copy_ms = (time.perf_counter() - copy_started) * 1000.0
    merge_started = time.perf_counter()
    if rows:
        conn.execute("""
          WITH grouped AS (
            SELECT bucket,node,bridge,iface,vm_uuid,
                   SUM(rx_delta)::bigint AS rx_delta,
                   SUM(tx_delta)::bigint AS tx_delta,
                   SUM(rx_packets_delta)::bigint AS rx_packets_delta,
                   SUM(tx_packets_delta)::bigint AS tx_packets_delta,
                   SUM(rx_drop_delta)::bigint AS rx_drop_delta,
                   SUM(tx_drop_delta)::bigint AS tx_drop_delta,
                   SUM(rx_error_delta)::bigint AS rx_error_delta,
                   SUM(tx_error_delta)::bigint AS tx_error_delta,
                   MAX(rx_mbps_peak) AS rx_mbps_peak,
                   MAX(tx_mbps_peak) AS tx_mbps_peak,
                   MAX(rx_pps_peak) AS rx_pps_peak,
                   MAX(tx_pps_peak) AS tx_pps_peak,
                   COALESCE((ARRAY_AGG(rx_packet_size_avg ORDER BY ord DESC)
                     FILTER (WHERE rx_packet_size_avg>0))[1],0) AS rx_packet_size_avg,
                   COALESCE((ARRAY_AGG(tx_packet_size_avg ORDER BY ord DESC)
                     FILTER (WHERE tx_packet_size_avg>0))[1],0) AS tx_packet_size_avg,
                   SUM(network_sample_count)::bigint AS network_sample_count,
                   SUM(network_sample_expected)::bigint AS network_sample_expected,
                   MAX(network_sample_max_gap_seconds) AS network_sample_max_gap_seconds,
                   SUM(seconds_over_pps)::bigint AS seconds_over_pps,
                   SUM(seconds_over_mbps)::bigint AS seconds_over_mbps,
                   CASE MAX(quality_rank)
                     WHEN 3 THEN 'POOR' WHEN 2 THEN 'DEGRADED'
                     WHEN 1 THEN 'GOOD' ELSE 'LEGACY' END AS network_sample_quality,
                   (ARRAY_AGG(interval_seconds ORDER BY ord DESC))[1] AS interval_seconds,
                   MAX(last_push)::bigint AS last_push
              FROM pg_temp.vi5052_iface_stage
             GROUP BY bucket,node,bridge,iface,vm_uuid
          )
          INSERT INTO node_stats(
            bucket,node,bridge,iface,vm_uuid,
            rx_delta,tx_delta,rx_packets_delta,tx_packets_delta,
            rx_drop_delta,tx_drop_delta,rx_error_delta,tx_error_delta,
            rx_mbps_peak,tx_mbps_peak,rx_pps_peak,tx_pps_peak,
            rx_packet_size_avg,tx_packet_size_avg,
            network_sample_count,network_sample_expected,network_sample_max_gap_seconds,
            seconds_over_pps,seconds_over_mbps,network_sample_quality,
            interval_seconds,last_push
          )
          SELECT bucket,node,bridge,iface,vm_uuid,
                 rx_delta,tx_delta,rx_packets_delta,tx_packets_delta,
                 rx_drop_delta,tx_drop_delta,rx_error_delta,tx_error_delta,
                 rx_mbps_peak,tx_mbps_peak,rx_pps_peak,tx_pps_peak,
                 rx_packet_size_avg,tx_packet_size_avg,
                 network_sample_count,network_sample_expected,network_sample_max_gap_seconds,
                 seconds_over_pps,seconds_over_mbps,network_sample_quality,
                 interval_seconds,last_push
            FROM grouped
          ON CONFLICT(bucket,node,bridge,iface,vm_uuid) DO UPDATE SET
            rx_delta=node_stats.rx_delta+excluded.rx_delta,
            tx_delta=node_stats.tx_delta+excluded.tx_delta,
            rx_packets_delta=node_stats.rx_packets_delta+excluded.rx_packets_delta,
            tx_packets_delta=node_stats.tx_packets_delta+excluded.tx_packets_delta,
            rx_drop_delta=node_stats.rx_drop_delta+excluded.rx_drop_delta,
            tx_drop_delta=node_stats.tx_drop_delta+excluded.tx_drop_delta,
            rx_error_delta=node_stats.rx_error_delta+excluded.rx_error_delta,
            tx_error_delta=node_stats.tx_error_delta+excluded.tx_error_delta,
            rx_mbps_peak=GREATEST(node_stats.rx_mbps_peak,excluded.rx_mbps_peak),
            tx_mbps_peak=GREATEST(node_stats.tx_mbps_peak,excluded.tx_mbps_peak),
            rx_pps_peak=GREATEST(node_stats.rx_pps_peak,excluded.rx_pps_peak),
            tx_pps_peak=GREATEST(node_stats.tx_pps_peak,excluded.tx_pps_peak),
            rx_packet_size_avg=CASE WHEN excluded.rx_packet_size_avg>0 THEN excluded.rx_packet_size_avg ELSE node_stats.rx_packet_size_avg END,
            tx_packet_size_avg=CASE WHEN excluded.tx_packet_size_avg>0 THEN excluded.tx_packet_size_avg ELSE node_stats.tx_packet_size_avg END,
            network_sample_count=node_stats.network_sample_count+excluded.network_sample_count,
            network_sample_expected=node_stats.network_sample_expected+excluded.network_sample_expected,
            network_sample_max_gap_seconds=GREATEST(node_stats.network_sample_max_gap_seconds,excluded.network_sample_max_gap_seconds),
            seconds_over_pps=node_stats.seconds_over_pps+excluded.seconds_over_pps,
            seconds_over_mbps=node_stats.seconds_over_mbps+excluded.seconds_over_mbps,
            network_sample_quality=CASE
              WHEN node_stats.network_sample_quality='POOR' OR excluded.network_sample_quality='POOR' THEN 'POOR'
              WHEN node_stats.network_sample_quality='DEGRADED' OR excluded.network_sample_quality='DEGRADED' THEN 'DEGRADED'
              WHEN node_stats.network_sample_quality='GOOD' OR excluded.network_sample_quality='GOOD' THEN 'GOOD'
              WHEN excluded.network_sample_quality='NO_DATA' THEN 'NO_DATA'
              ELSE node_stats.network_sample_quality END,
            interval_seconds=excluded.interval_seconds,
            last_push=GREATEST(node_stats.last_push,excluded.last_push)
        """)
        if WRITE_LEGACY_USAGE:
            conn.execute("""
              INSERT INTO usage(
                time,node,vm_uuid,iface,bridge,mac,rx_delta,tx_delta,
                rx_packets_delta,tx_packets_delta,rx_drop_delta,tx_drop_delta,
                rx_error_delta,tx_error_delta,interval_seconds
              )
              SELECT last_push,node,vm_uuid,iface,bridge,mac,rx_delta,tx_delta,
                     rx_packets_delta,tx_packets_delta,rx_drop_delta,tx_drop_delta,
                     rx_error_delta,tx_error_delta,interval_seconds
                FROM pg_temp.vi5052_iface_stage
               ORDER BY ord
            """)
        conn.execute("""
          WITH grouped AS (
            SELECT hour_start,node,vm_uuid,bridge,
                   SUM(rx_delta)::bigint rx_bytes,SUM(tx_delta)::bigint tx_bytes,
                   SUM(rx_packets_delta)::bigint rx_packets,SUM(tx_packets_delta)::bigint tx_packets,
                   SUM(rx_drop_delta)::bigint rx_drops,SUM(tx_drop_delta)::bigint tx_drops,
                   SUM(rx_error_delta)::bigint rx_errors,SUM(tx_error_delta)::bigint tx_errors,
                   COUNT(DISTINCT last_push)::bigint sample_count,MAX(last_push)::bigint last_push
              FROM pg_temp.vi5052_iface_stage
             GROUP BY hour_start,node,vm_uuid,bridge
          )
          INSERT INTO vm_consumption_hourly(
            hour_start,node,vm_uuid,bridge,rx_bytes,tx_bytes,rx_packets,tx_packets,
            rx_drops,tx_drops,rx_errors,tx_errors,sample_count,last_push
          )
          SELECT hour_start,node,vm_uuid,bridge,rx_bytes,tx_bytes,rx_packets,tx_packets,
                 rx_drops,tx_drops,rx_errors,tx_errors,sample_count,last_push FROM grouped
          ON CONFLICT(hour_start,node,vm_uuid,bridge) DO UPDATE SET
            rx_bytes=vm_consumption_hourly.rx_bytes+excluded.rx_bytes,
            tx_bytes=vm_consumption_hourly.tx_bytes+excluded.tx_bytes,
            rx_packets=vm_consumption_hourly.rx_packets+excluded.rx_packets,
            tx_packets=vm_consumption_hourly.tx_packets+excluded.tx_packets,
            rx_drops=vm_consumption_hourly.rx_drops+excluded.rx_drops,
            tx_drops=vm_consumption_hourly.tx_drops+excluded.tx_drops,
            rx_errors=vm_consumption_hourly.rx_errors+excluded.rx_errors,
            tx_errors=vm_consumption_hourly.tx_errors+excluded.tx_errors,
            sample_count=vm_consumption_hourly.sample_count+excluded.sample_count,
            last_push=GREATEST(vm_consumption_hourly.last_push,excluded.last_push)
        """)
        conn.execute("""
          WITH grouped AS (
            SELECT day_start,node,vm_uuid,bridge,
                   SUM(rx_delta)::bigint rx_bytes,SUM(tx_delta)::bigint tx_bytes,
                   SUM(rx_packets_delta)::bigint rx_packets,SUM(tx_packets_delta)::bigint tx_packets,
                   SUM(rx_drop_delta)::bigint rx_drops,SUM(tx_drop_delta)::bigint tx_drops,
                   SUM(rx_error_delta)::bigint rx_errors,SUM(tx_error_delta)::bigint tx_errors,
                   COUNT(DISTINCT last_push)::bigint sample_count,MAX(last_push)::bigint last_push
              FROM pg_temp.vi5052_iface_stage
             GROUP BY day_start,node,vm_uuid,bridge
          )
          INSERT INTO vm_consumption_daily(
            day_start,node,vm_uuid,bridge,rx_bytes,tx_bytes,rx_packets,tx_packets,
            rx_drops,tx_drops,rx_errors,tx_errors,sample_count,last_push
          )
          SELECT day_start,node,vm_uuid,bridge,rx_bytes,tx_bytes,rx_packets,tx_packets,
                 rx_drops,tx_drops,rx_errors,tx_errors,sample_count,last_push FROM grouped
          ON CONFLICT(day_start,node,vm_uuid,bridge) DO UPDATE SET
            rx_bytes=vm_consumption_daily.rx_bytes+excluded.rx_bytes,
            tx_bytes=vm_consumption_daily.tx_bytes+excluded.tx_bytes,
            rx_packets=vm_consumption_daily.rx_packets+excluded.rx_packets,
            tx_packets=vm_consumption_daily.tx_packets+excluded.tx_packets,
            rx_drops=vm_consumption_daily.rx_drops+excluded.rx_drops,
            tx_drops=vm_consumption_daily.tx_drops+excluded.tx_drops,
            rx_errors=vm_consumption_daily.rx_errors+excluded.rx_errors,
            tx_errors=vm_consumption_daily.tx_errors+excluded.tx_errors,
            sample_count=vm_consumption_daily.sample_count+excluded.sample_count,
            last_push=GREATEST(vm_consumption_daily.last_push,excluded.last_push)
        """)
    return {
        "rows": len(rows),
        "copy_ms": copy_ms,
        "merge_ms": (time.perf_counter() - merge_started) * 1000.0,
    }

def _v5052_vm_rows(node, data_time, bucket, interval_seconds, vms):
    columns = (
        "ord", "time", "bucket", "node", "vm_uuid", "interval_seconds", "current_interval_seconds",
        "vcpu_current", "cpu_percent", "cpu_full_percent", "cpu_core_percent",
        "ram_current_kib", "ram_maximum_kib", "ram_rss_kib", "ram_available_kib",
        "ram_unused_kib", "ram_usable_kib",
        "disk_read_delta", "disk_write_delta", "disk_read_reqs_delta", "disk_write_reqs_delta",
        "disk_read_bps", "disk_write_bps", "disk_read_iops", "disk_write_iops",
        "current_disk_read_bps", "current_disk_write_bps",
        "current_disk_read_iops", "current_disk_write_iops", "last_push",
    )
    rows = []
    for ordinal, item in enumerate(vms or []):
        if not isinstance(item, dict):
            continue
        vm_uuid = str(item.get("vm_uuid") or "").strip()
        if not vm_uuid or vm_uuid == "-":
            continue
        history_sec = max(1, min(3600, safe_int(interval_seconds, CACHE_BUCKET_SECONDS)))
        current_sec = max(1, min(3600, safe_int(item.get("interval_seconds"), history_sec)))
        vcpu = max(0, safe_int(item.get("vcpu_current"), 0))
        full_cpu, core_cpu, _ = _fast_cpu_values(item)
        # Preserve the established history/latest value while keeping the bounded
        # current-cache CPU normalization used by Top VM and Abuse.
        if item.get("cpu_normalized_percent") is not None:
            cpu_percent = max(0.0, min(100.0, safe_float(item.get("cpu_normalized_percent"), 0.0)))
        else:
            cpu_percent = max(0.0, safe_float(item.get("cpu_percent"), 0.0))
        rd = max(0, safe_int(item.get("disk_read_delta"), 0))
        wr = max(0, safe_int(item.get("disk_write_delta"), 0))
        rr = max(0, safe_int(item.get("disk_read_reqs_delta"), 0))
        ww = max(0, safe_int(item.get("disk_write_reqs_delta"), 0))
        rows.append((
            ordinal, data_time, bucket, node, vm_uuid, history_sec, current_sec,
            vcpu, cpu_percent, full_cpu, core_cpu,
            max(0, safe_int(item.get("ram_current_kib"), 0)),
            max(0, safe_int(item.get("ram_maximum_kib"), 0)),
            max(0, safe_int(item.get("ram_rss_kib"), 0)),
            max(0, safe_int(item.get("ram_available_kib"), 0)),
            max(0, safe_int(item.get("ram_unused_kib"), 0)),
            max(0, safe_int(item.get("ram_usable_kib"), 0)),
            rd, wr, rr, ww,
            rd / float(history_sec), wr / float(history_sec),
            rr / float(history_sec), ww / float(history_sec),
            rd / float(current_sec), wr / float(current_sec),
            rr / float(current_sec), ww / float(current_sec),
            data_time,
        ))
    return columns, rows

def _v5052_write_vm_copy_batch(conn, node, data_time, bucket, interval_seconds, vms):
    _v5052_create_vm_stage(conn)
    columns, rows = _v5052_vm_rows(node, data_time, bucket, interval_seconds, vms)
    copy_started = time.perf_counter()
    if rows:
        conn.copy_rows(V5052_VM_STAGE, columns, rows)
    copy_ms = (time.perf_counter() - copy_started) * 1000.0
    merge_started = time.perf_counter()
    if rows:
        conn.execute("""
          INSERT INTO vm_perf_stats(
            time,bucket,node,vm_uuid,interval_seconds,vcpu_current,cpu_percent,
            ram_current_kib,ram_maximum_kib,ram_rss_kib,ram_available_kib,ram_unused_kib,ram_usable_kib,
            disk_read_delta,disk_write_delta,disk_read_reqs_delta,disk_write_reqs_delta,last_push
          )
          SELECT time,bucket,node,vm_uuid,interval_seconds,vcpu_current,cpu_percent,
                 ram_current_kib,ram_maximum_kib,ram_rss_kib,ram_available_kib,ram_unused_kib,ram_usable_kib,
                 disk_read_delta,disk_write_delta,disk_read_reqs_delta,disk_write_reqs_delta,last_push
            FROM pg_temp.vi5052_vm_stage
           ORDER BY ord
        """)
    return {
        "rows": len(rows),
        "copy_ms": copy_ms,
        "merge_ms": (time.perf_counter() - merge_started) * 1000.0,
    }

def _v5052_merge_latest_metrics(conn, node, data_time):
    """Merge network and VM performance exactly once per VM.

    PostgreSQL MERGE keeps source-presence markers available in the matched
    branch. A network-only push therefore preserves the last VM performance
    fields, and a performance-only row preserves the last network fields,
    without sentinel values or a second UPSERT.
    """
    conn.execute("""
      WITH net AS (
        SELECT DISTINCT ON (vm_uuid)
               vm_uuid,iface,bridge,last_push,interval_seconds,
               rx_mbps,tx_mbps,rx_pps,tx_pps,
               rx_mbps_peak,tx_mbps_peak,rx_pps_peak,tx_pps_peak,
               rx_packet_size_avg,tx_packet_size_avg,
               network_sample_count,network_sample_expected,network_sample_max_gap_seconds,
               seconds_over_pps,seconds_over_mbps,network_sample_quality,
               rx_drop_delta,tx_drop_delta,rx_error_delta,tx_error_delta,
               alert_level,alert_flags
          FROM pg_temp.vi5052_iface_stage
         ORDER BY vm_uuid,ord DESC
      ), perf AS (
        SELECT DISTINCT ON (vm_uuid) *
          FROM pg_temp.vi5052_vm_stage
         ORDER BY vm_uuid,ord DESC
      ), src AS (
        SELECT COALESCE(n.vm_uuid,p.vm_uuid) AS vm_uuid,
               (n.vm_uuid IS NOT NULL) AS has_net,
               (p.vm_uuid IS NOT NULL) AS has_perf,
               n.iface,n.bridge,COALESCE(n.last_push,p.last_push,?) AS last_seen,
               COALESCE(p.interval_seconds,n.interval_seconds,300) AS interval_seconds,
               COALESCE(n.rx_mbps,0) rx_mbps,COALESCE(n.tx_mbps,0) tx_mbps,
               COALESCE(n.rx_pps,0) rx_pps,COALESCE(n.tx_pps,0) tx_pps,
               COALESCE(n.rx_mbps_peak,0) rx_mbps_peak,COALESCE(n.tx_mbps_peak,0) tx_mbps_peak,
               COALESCE(n.rx_pps_peak,0) rx_pps_peak,COALESCE(n.tx_pps_peak,0) tx_pps_peak,
               COALESCE(n.rx_packet_size_avg,0) rx_packet_size_avg,
               COALESCE(n.tx_packet_size_avg,0) tx_packet_size_avg,
               COALESCE(n.network_sample_count,0) network_sample_count,
               COALESCE(n.network_sample_expected,0) network_sample_expected,
               COALESCE(n.network_sample_max_gap_seconds,0) network_sample_max_gap_seconds,
               COALESCE(n.seconds_over_pps,0) seconds_over_pps,
               COALESCE(n.seconds_over_mbps,0) seconds_over_mbps,
               COALESCE(n.network_sample_quality,'LEGACY') network_sample_quality,
               COALESCE(n.rx_drop_delta,0) rx_drop_delta,COALESCE(n.tx_drop_delta,0) tx_drop_delta,
               COALESCE(n.rx_error_delta,0) rx_error_delta,COALESCE(n.tx_error_delta,0) tx_error_delta,
               COALESCE(p.cpu_percent,0) cpu_percent,COALESCE(p.vcpu_current,0) vcpu_current,
               COALESCE(p.ram_current_kib,0) ram_current_kib,
               COALESCE(p.ram_maximum_kib,0) ram_maximum_kib,
               COALESCE(p.ram_rss_kib,0) ram_rss_kib,
               COALESCE(p.ram_available_kib,0) ram_available_kib,
               COALESCE(p.ram_unused_kib,0) ram_unused_kib,
               COALESCE(p.ram_usable_kib,0) ram_usable_kib,
               COALESCE(p.disk_read_bps,0) disk_read_bps,
               COALESCE(p.disk_write_bps,0) disk_write_bps,
               COALESCE(n.alert_level,'ok') alert_level,
               COALESCE(n.alert_flags,'') alert_flags
          FROM net n FULL OUTER JOIN perf p USING(vm_uuid)
      )
      MERGE INTO vm_latest_metrics AS dst
      USING src
         ON dst.node=? AND dst.vm_uuid=src.vm_uuid
      WHEN MATCHED THEN UPDATE SET
        iface=CASE WHEN src.has_net THEN src.iface ELSE dst.iface END,
        bridge=CASE WHEN src.has_net THEN src.bridge ELSE dst.bridge END,
        last_seen=GREATEST(dst.last_seen,src.last_seen),
        interval_seconds=src.interval_seconds,
        rx_mbps=CASE WHEN src.has_net THEN src.rx_mbps ELSE dst.rx_mbps END,
        tx_mbps=CASE WHEN src.has_net THEN src.tx_mbps ELSE dst.tx_mbps END,
        rx_pps=CASE WHEN src.has_net THEN src.rx_pps ELSE dst.rx_pps END,
        tx_pps=CASE WHEN src.has_net THEN src.tx_pps ELSE dst.tx_pps END,
        rx_mbps_peak=CASE WHEN src.has_net THEN src.rx_mbps_peak ELSE dst.rx_mbps_peak END,
        tx_mbps_peak=CASE WHEN src.has_net THEN src.tx_mbps_peak ELSE dst.tx_mbps_peak END,
        rx_pps_peak=CASE WHEN src.has_net THEN src.rx_pps_peak ELSE dst.rx_pps_peak END,
        tx_pps_peak=CASE WHEN src.has_net THEN src.tx_pps_peak ELSE dst.tx_pps_peak END,
        rx_packet_size_avg=CASE WHEN src.has_net THEN src.rx_packet_size_avg ELSE dst.rx_packet_size_avg END,
        tx_packet_size_avg=CASE WHEN src.has_net THEN src.tx_packet_size_avg ELSE dst.tx_packet_size_avg END,
        network_sample_count=CASE WHEN src.has_net THEN src.network_sample_count ELSE dst.network_sample_count END,
        network_sample_expected=CASE WHEN src.has_net THEN src.network_sample_expected ELSE dst.network_sample_expected END,
        network_sample_max_gap_seconds=CASE WHEN src.has_net THEN src.network_sample_max_gap_seconds ELSE dst.network_sample_max_gap_seconds END,
        seconds_over_pps=CASE WHEN src.has_net THEN src.seconds_over_pps ELSE dst.seconds_over_pps END,
        seconds_over_mbps=CASE WHEN src.has_net THEN src.seconds_over_mbps ELSE dst.seconds_over_mbps END,
        network_sample_quality=CASE WHEN src.has_net THEN src.network_sample_quality ELSE dst.network_sample_quality END,
        rx_drop_delta=CASE WHEN src.has_net THEN src.rx_drop_delta ELSE dst.rx_drop_delta END,
        tx_drop_delta=CASE WHEN src.has_net THEN src.tx_drop_delta ELSE dst.tx_drop_delta END,
        rx_error_delta=CASE WHEN src.has_net THEN src.rx_error_delta ELSE dst.rx_error_delta END,
        tx_error_delta=CASE WHEN src.has_net THEN src.tx_error_delta ELSE dst.tx_error_delta END,
        cpu_percent=CASE WHEN src.has_perf THEN src.cpu_percent ELSE dst.cpu_percent END,
        vcpu_current=CASE WHEN src.has_perf THEN src.vcpu_current ELSE dst.vcpu_current END,
        ram_current_kib=CASE WHEN src.has_perf THEN src.ram_current_kib ELSE dst.ram_current_kib END,
        ram_maximum_kib=CASE WHEN src.has_perf THEN src.ram_maximum_kib ELSE dst.ram_maximum_kib END,
        ram_rss_kib=CASE WHEN src.has_perf THEN src.ram_rss_kib ELSE dst.ram_rss_kib END,
        ram_available_kib=CASE WHEN src.has_perf THEN src.ram_available_kib ELSE dst.ram_available_kib END,
        ram_unused_kib=CASE WHEN src.has_perf THEN src.ram_unused_kib ELSE dst.ram_unused_kib END,
        ram_usable_kib=CASE WHEN src.has_perf THEN src.ram_usable_kib ELSE dst.ram_usable_kib END,
        disk_read_bps=CASE WHEN src.has_perf THEN src.disk_read_bps ELSE dst.disk_read_bps END,
        disk_write_bps=CASE WHEN src.has_perf THEN src.disk_write_bps ELSE dst.disk_write_bps END,
        alert_level=CASE WHEN src.has_net THEN src.alert_level ELSE dst.alert_level END,
        alert_flags=CASE WHEN src.has_net THEN src.alert_flags ELSE dst.alert_flags END
      WHEN NOT MATCHED THEN INSERT(
        node,vm_uuid,iface,bridge,last_seen,interval_seconds,
        rx_mbps,tx_mbps,rx_pps,tx_pps,rx_mbps_peak,tx_mbps_peak,rx_pps_peak,tx_pps_peak,
        rx_packet_size_avg,tx_packet_size_avg,network_sample_count,network_sample_expected,
        network_sample_max_gap_seconds,seconds_over_pps,seconds_over_mbps,network_sample_quality,
        rx_drop_delta,tx_drop_delta,rx_error_delta,tx_error_delta,
        cpu_percent,vcpu_current,ram_current_kib,ram_maximum_kib,ram_rss_kib,ram_available_kib,
        ram_unused_kib,ram_usable_kib,disk_read_bps,disk_write_bps,alert_level,alert_flags
      ) VALUES(
        ?,src.vm_uuid,src.iface,src.bridge,src.last_seen,src.interval_seconds,
        src.rx_mbps,src.tx_mbps,src.rx_pps,src.tx_pps,src.rx_mbps_peak,src.tx_mbps_peak,src.rx_pps_peak,src.tx_pps_peak,
        src.rx_packet_size_avg,src.tx_packet_size_avg,src.network_sample_count,src.network_sample_expected,
        src.network_sample_max_gap_seconds,src.seconds_over_pps,src.seconds_over_mbps,src.network_sample_quality,
        src.rx_drop_delta,src.tx_drop_delta,src.rx_error_delta,src.tx_error_delta,
        src.cpu_percent,src.vcpu_current,src.ram_current_kib,src.ram_maximum_kib,src.ram_rss_kib,src.ram_available_kib,
        src.ram_unused_kib,src.ram_usable_kib,src.disk_read_bps,src.disk_write_bps,src.alert_level,src.alert_flags
      )
    """, (data_time, node, node))

def _v5052_copy_upsert_rows(conn, table, key_columns, rows):
    rows = [dict(row) for row in (rows or []) if row]
    if not rows:
        return 0
    table = _v5050_ident(table)
    columns = list(rows[0].keys())
    if not columns or any(list(row.keys()) != columns for row in rows):
        raise ValueError(f"heterogeneous batch for {table}")
    columns = [_v5050_ident(column) for column in columns]
    keys = [_v5050_ident(column) for column in key_columns]
    stage = _v5050_ident(f"vi5052_up_{table}")
    conn.execute(
        f"CREATE TEMP TABLE IF NOT EXISTS {stage} "
        f"(LIKE public.{table} INCLUDING DEFAULTS) ON COMMIT DELETE ROWS"
    )
    conn.copy_rows(
        f"pg_temp.{stage}", columns,
        ([row[column] for column in columns] for row in rows),
    )
    updates = [column for column in columns if column not in keys]
    column_sql = ",".join(columns)
    key_sql = ",".join(keys)
    if updates:
        update_sql = ",".join(f"{column}=excluded.{column}" for column in updates)
        conflict_sql = f"ON CONFLICT({key_sql}) DO UPDATE SET {update_sql}"
    else:
        conflict_sql = f"ON CONFLICT({key_sql}) DO NOTHING"
    cur = conn.execute(
        f"INSERT INTO public.{table}({column_sql}) "
        f"SELECT {column_sql} FROM pg_temp.{stage} {conflict_sql}"
    )
    return max(0, safe_int(cur.rowcount, 0))

def _v5052_current_writer(conn, node, data_time, interval_seconds, interfaces, vms, node_host, inventory_complete=False):
    """Build bounded current tables from the two already-COPYed request stages."""
    interval_seconds = max(1, safe_int(interval_seconds, CACHE_BUCKET_SECONDS))
    # The caller passes normalized interfaces after PPS policy sync. Re-copy only
    # the directional timers into a tiny temp table instead of re-encoding all rows.
    conn.execute("""
      CREATE TEMP TABLE IF NOT EXISTS vi5052_sync_stage(
        vm_uuid TEXT PRIMARY KEY,
        seconds_over_rx_pps BIGINT NOT NULL,
        seconds_over_tx_pps BIGINT NOT NULL
      ) ON COMMIT DELETE ROWS
    """)
    sync_rows = {}
    for item in interfaces or []:
        if not isinstance(item, dict):
            continue
        vm_uuid = str(item.get("vm_uuid") or "").strip()
        if not vm_uuid or vm_uuid == "-":
            continue
        current = sync_rows.setdefault(vm_uuid, [0, 0])
        current[0] = max(current[0], max(0, safe_int(item.get("seconds_over_rx_pps"), 0)))
        current[1] = max(current[1], max(0, safe_int(item.get("seconds_over_tx_pps"), 0)))
    if sync_rows:
        conn.copy_rows(
            V5052_SYNC_STAGE,
            ("vm_uuid", "seconds_over_rx_pps", "seconds_over_tx_pps"),
            ((vm_uuid, values[0], values[1]) for vm_uuid, values in sync_rows.items()),
        )

    conn.execute("""
      WITH picked AS (
        SELECT DISTINCT ON (node,vm_uuid,bridge,iface) *
          FROM pg_temp.vi5052_iface_stage
         ORDER BY node,vm_uuid,bridge,iface,ord DESC
      )
      INSERT INTO vm_iface_current(
        node,vm_uuid,bridge,iface,mac,last_seen,interval_seconds,
        rx_bytes,tx_bytes,rx_packets,tx_packets,
        rx_mbps,tx_mbps,total_mbps,rx_peak_mbps,tx_peak_mbps,total_peak_mbps,
        rx_pps,tx_pps,total_pps,rx_peak_pps,tx_peak_pps,total_peak_pps,
        sample_count,sample_expected,sample_max_gap,sample_quality,
        seconds_over_rx_pps,seconds_over_tx_pps,drops,errors
      )
      SELECT p.node,p.vm_uuid,p.bridge,p.iface,COALESCE(p.mac,''),p.last_push,p.interval_seconds,
             p.rx_delta,p.tx_delta,p.rx_packets_delta,p.tx_packets_delta,
             p.rx_mbps,p.tx_mbps,p.rx_mbps+p.tx_mbps,
             p.rx_mbps_peak,p.tx_mbps_peak,GREATEST(p.rx_mbps+p.tx_mbps,p.rx_mbps_peak+p.tx_mbps_peak),
             p.rx_pps,p.tx_pps,p.rx_pps+p.tx_pps,
             p.rx_pps_peak,p.tx_pps_peak,GREATEST(p.rx_pps+p.tx_pps,p.rx_pps_peak+p.tx_pps_peak),
             p.network_sample_count,p.network_sample_expected,p.network_sample_max_gap_seconds,
             p.network_sample_quality,COALESCE(s.seconds_over_rx_pps,0),COALESCE(s.seconds_over_tx_pps,0),
             p.rx_drop_delta+p.tx_drop_delta,p.rx_error_delta+p.tx_error_delta
        FROM picked p LEFT JOIN pg_temp.vi5052_sync_stage s USING(vm_uuid)
      ON CONFLICT(node,vm_uuid,bridge,iface) DO UPDATE SET
        mac=CASE WHEN excluded.mac<>'' THEN excluded.mac ELSE vm_iface_current.mac END,
        last_seen=excluded.last_seen,interval_seconds=excluded.interval_seconds,
        rx_bytes=excluded.rx_bytes,tx_bytes=excluded.tx_bytes,
        rx_packets=excluded.rx_packets,tx_packets=excluded.tx_packets,
        rx_mbps=excluded.rx_mbps,tx_mbps=excluded.tx_mbps,total_mbps=excluded.total_mbps,
        rx_peak_mbps=excluded.rx_peak_mbps,tx_peak_mbps=excluded.tx_peak_mbps,total_peak_mbps=excluded.total_peak_mbps,
        rx_pps=excluded.rx_pps,tx_pps=excluded.tx_pps,total_pps=excluded.total_pps,
        rx_peak_pps=excluded.rx_peak_pps,tx_peak_pps=excluded.tx_peak_pps,total_peak_pps=excluded.total_peak_pps,
        sample_count=excluded.sample_count,sample_expected=excluded.sample_expected,
        sample_max_gap=excluded.sample_max_gap,sample_quality=excluded.sample_quality,
        seconds_over_rx_pps=excluded.seconds_over_rx_pps,
        seconds_over_tx_pps=excluded.seconds_over_tx_pps,
        drops=excluded.drops,errors=excluded.errors
    """)

    conn.execute("""
      WITH picked AS (
        SELECT DISTINCT ON (node,vm_uuid,bridge,iface)
               node,vm_uuid,bridge,iface,mac,last_push
          FROM pg_temp.vi5052_iface_stage
         WHERE COALESCE(mac,'')<>''
         ORDER BY node,vm_uuid,bridge,iface,ord DESC
      )
      INSERT INTO vm_nic_identity_lookup(
        node,vm_uuid,bridge,iface,mac,first_seen,changed_at
      )
      SELECT node,vm_uuid,bridge,iface,mac,last_push,last_push FROM picked
      ON CONFLICT(node,vm_uuid,bridge,iface) DO UPDATE SET
        mac=excluded.mac,changed_at=excluded.changed_at
      WHERE vm_nic_identity_lookup.mac IS DISTINCT FROM excluded.mac
    """)

    conn.execute("""
      WITH net AS (
        SELECT i.node,i.vm_uuid,MAX(i.last_push)::bigint last_seen,
               MAX(i.interval_seconds)::integer interval_seconds,
               COUNT(DISTINCT (i.bridge,i.iface))::integer iface_count,
               SUM(CASE WHEN i.bridge=? THEN i.rx_delta ELSE 0 END)::bigint public_rx_bytes,
               SUM(CASE WHEN i.bridge=? THEN i.tx_delta ELSE 0 END)::bigint public_tx_bytes,
               SUM(CASE WHEN i.bridge=? THEN i.rx_delta ELSE 0 END)::bigint private_rx_bytes,
               SUM(CASE WHEN i.bridge=? THEN i.tx_delta ELSE 0 END)::bigint private_tx_bytes,
               SUM(i.rx_delta)::bigint rx_bytes,SUM(i.tx_delta)::bigint tx_bytes,
               SUM(i.rx_delta+i.tx_delta)::bigint total_bytes,
               SUM(CASE WHEN i.bridge=? THEN i.rx_mbps+i.tx_mbps ELSE 0 END) public_mbps,
               SUM(CASE WHEN i.bridge=? THEN i.rx_mbps+i.tx_mbps ELSE 0 END) private_mbps,
               SUM(i.rx_mbps) rx_mbps,SUM(i.tx_mbps) tx_mbps,SUM(i.rx_mbps+i.tx_mbps) total_mbps,
               SUM(CASE WHEN i.bridge=? THEN i.rx_pps+i.tx_pps ELSE 0 END) public_pps,
               SUM(CASE WHEN i.bridge=? THEN i.rx_pps+i.tx_pps ELSE 0 END) private_pps,
               SUM(i.rx_pps) rx_pps,SUM(i.tx_pps) tx_pps,SUM(i.rx_pps+i.tx_pps) total_pps,
               SUM(CASE WHEN i.bridge=? THEN GREATEST(i.rx_mbps+i.tx_mbps,i.rx_mbps_peak+i.tx_mbps_peak) ELSE 0 END) public_peak_mbps,
               SUM(CASE WHEN i.bridge=? THEN GREATEST(i.rx_mbps+i.tx_mbps,i.rx_mbps_peak+i.tx_mbps_peak) ELSE 0 END) private_peak_mbps,
               SUM(i.rx_mbps_peak) rx_peak_mbps,SUM(i.tx_mbps_peak) tx_peak_mbps,
               SUM(GREATEST(i.rx_mbps+i.tx_mbps,i.rx_mbps_peak+i.tx_mbps_peak)) total_peak_mbps,
               SUM(CASE WHEN i.bridge=? THEN GREATEST(i.rx_pps+i.tx_pps,i.rx_pps_peak+i.tx_pps_peak) ELSE 0 END) public_peak_pps,
               SUM(CASE WHEN i.bridge=? THEN GREATEST(i.rx_pps+i.tx_pps,i.rx_pps_peak+i.tx_pps_peak) ELSE 0 END) private_peak_pps,
               SUM(i.rx_pps_peak) rx_peak_pps,SUM(i.tx_pps_peak) tx_peak_pps,
               SUM(GREATEST(i.rx_pps+i.tx_pps,i.rx_pps_peak+i.tx_pps_peak)) total_peak_pps,
               MAX(i.network_sample_count)::bigint sample_count,
               MAX(i.network_sample_expected)::bigint sample_expected,
               MAX(i.network_sample_max_gap_seconds) sample_max_gap,
               CASE MAX(i.quality_rank) WHEN 3 THEN 'POOR' WHEN 2 THEN 'DEGRADED' WHEN 1 THEN 'GOOD' ELSE 'LEGACY' END sample_quality,
               MAX(COALESCE(s.seconds_over_rx_pps,0))::bigint seconds_over_rx_pps,
               MAX(COALESCE(s.seconds_over_tx_pps,0))::bigint seconds_over_tx_pps,
               SUM(i.rx_drop_delta+i.tx_drop_delta)::bigint drops,
               SUM(i.rx_error_delta+i.tx_error_delta)::bigint errors
          FROM pg_temp.vi5052_iface_stage i
          LEFT JOIN pg_temp.vi5052_sync_stage s USING(vm_uuid)
         GROUP BY i.node,i.vm_uuid
      ), perf AS (
        SELECT DISTINCT ON (node,vm_uuid) *
          FROM pg_temp.vi5052_vm_stage
         ORDER BY node,vm_uuid,ord DESC
      ), src AS (
        SELECT COALESCE(n.node,p.node) node,COALESCE(n.vm_uuid,p.vm_uuid) vm_uuid,
               COALESCE(n.last_seen,p.last_push,?) last_seen,
               COALESCE(p.current_interval_seconds,n.interval_seconds,?) interval_seconds,
               COALESCE(n.iface_count,0) iface_count,
               COALESCE(n.public_rx_bytes,0) public_rx_bytes,COALESCE(n.public_tx_bytes,0) public_tx_bytes,
               COALESCE(n.private_rx_bytes,0) private_rx_bytes,COALESCE(n.private_tx_bytes,0) private_tx_bytes,
               COALESCE(n.rx_bytes,0) rx_bytes,COALESCE(n.tx_bytes,0) tx_bytes,COALESCE(n.total_bytes,0) total_bytes,
               COALESCE(n.public_mbps,0) public_mbps,COALESCE(n.private_mbps,0) private_mbps,
               COALESCE(n.rx_mbps,0) rx_mbps,COALESCE(n.tx_mbps,0) tx_mbps,COALESCE(n.total_mbps,0) total_mbps,
               COALESCE(n.public_pps,0) public_pps,COALESCE(n.private_pps,0) private_pps,
               COALESCE(n.rx_pps,0) rx_pps,COALESCE(n.tx_pps,0) tx_pps,COALESCE(n.total_pps,0) total_pps,
               COALESCE(n.public_peak_mbps,0) public_peak_mbps,COALESCE(n.private_peak_mbps,0) private_peak_mbps,
               COALESCE(n.rx_peak_mbps,0) rx_peak_mbps,COALESCE(n.tx_peak_mbps,0) tx_peak_mbps,
               GREATEST(COALESCE(n.total_mbps,0),COALESCE(n.total_peak_mbps,0)) total_peak_mbps,
               COALESCE(n.public_peak_pps,0) public_peak_pps,COALESCE(n.private_peak_pps,0) private_peak_pps,
               COALESCE(n.rx_peak_pps,0) rx_peak_pps,COALESCE(n.tx_peak_pps,0) tx_peak_pps,
               GREATEST(COALESCE(n.total_pps,0),COALESCE(n.total_peak_pps,0)) total_peak_pps,
               COALESCE(n.sample_count,0) sample_count,COALESCE(n.sample_expected,0) sample_expected,
               COALESCE(n.sample_max_gap,0) sample_max_gap,COALESCE(n.sample_quality,'LEGACY') sample_quality,
               COALESCE(n.seconds_over_rx_pps,0) seconds_over_rx_pps,
               COALESCE(n.seconds_over_tx_pps,0) seconds_over_tx_pps,
               COALESCE(n.drops,0) drops,COALESCE(n.errors,0) errors,
               COALESCE(p.cpu_full_percent,0) cpu_full_percent,COALESCE(p.cpu_core_percent,0) cpu_core_percent,
               COALESCE(p.vcpu_current,0) vcpu_current,
               COALESCE(p.ram_current_kib,0) ram_current_kib,COALESCE(p.ram_rss_kib,0) ram_rss_kib,
               COALESCE(p.ram_available_kib,0) ram_available_kib,
               COALESCE(p.ram_unused_kib,0) ram_unused_kib,COALESCE(p.ram_usable_kib,0) ram_usable_kib,
               COALESCE(p.current_disk_read_bps,0) disk_read_bps,
               COALESCE(p.current_disk_write_bps,0) disk_write_bps,
               COALESCE(p.current_disk_read_iops,0) disk_read_iops,
               COALESCE(p.current_disk_write_iops,0) disk_write_iops
          FROM net n FULL OUTER JOIN perf p ON p.node=n.node AND p.vm_uuid=n.vm_uuid
      )
      INSERT INTO vm_current_fast(
        node,vm_uuid,last_seen,interval_seconds,iface_count,
        public_rx_bytes,public_tx_bytes,private_rx_bytes,private_tx_bytes,
        rx_bytes,tx_bytes,total_bytes,public_mbps,private_mbps,rx_mbps,tx_mbps,total_mbps,
        public_pps,private_pps,rx_pps,tx_pps,total_pps,
        public_peak_mbps,private_peak_mbps,rx_peak_mbps,tx_peak_mbps,total_peak_mbps,
        public_peak_pps,private_peak_pps,rx_peak_pps,tx_peak_pps,total_peak_pps,
        sample_count,sample_expected,sample_max_gap,sample_quality,
        seconds_over_rx_pps,seconds_over_tx_pps,drops,errors,
        cpu_full_percent,cpu_core_percent,vcpu_current,
        ram_current_kib,ram_rss_kib,ram_available_kib,ram_unused_kib,ram_usable_kib,
        disk_read_bps,disk_write_bps,disk_read_iops,disk_write_iops
      ) SELECT * FROM src
      ON CONFLICT(node,vm_uuid) DO UPDATE SET
        last_seen=excluded.last_seen,interval_seconds=excluded.interval_seconds,iface_count=excluded.iface_count,
        public_rx_bytes=excluded.public_rx_bytes,public_tx_bytes=excluded.public_tx_bytes,
        private_rx_bytes=excluded.private_rx_bytes,private_tx_bytes=excluded.private_tx_bytes,
        rx_bytes=excluded.rx_bytes,tx_bytes=excluded.tx_bytes,total_bytes=excluded.total_bytes,
        public_mbps=excluded.public_mbps,private_mbps=excluded.private_mbps,
        rx_mbps=excluded.rx_mbps,tx_mbps=excluded.tx_mbps,total_mbps=excluded.total_mbps,
        public_pps=excluded.public_pps,private_pps=excluded.private_pps,
        rx_pps=excluded.rx_pps,tx_pps=excluded.tx_pps,total_pps=excluded.total_pps,
        public_peak_mbps=excluded.public_peak_mbps,private_peak_mbps=excluded.private_peak_mbps,
        rx_peak_mbps=excluded.rx_peak_mbps,tx_peak_mbps=excluded.tx_peak_mbps,total_peak_mbps=excluded.total_peak_mbps,
        public_peak_pps=excluded.public_peak_pps,private_peak_pps=excluded.private_peak_pps,
        rx_peak_pps=excluded.rx_peak_pps,tx_peak_pps=excluded.tx_peak_pps,total_peak_pps=excluded.total_peak_pps,
        sample_count=excluded.sample_count,sample_expected=excluded.sample_expected,
        sample_max_gap=excluded.sample_max_gap,sample_quality=excluded.sample_quality,
        seconds_over_rx_pps=excluded.seconds_over_rx_pps,seconds_over_tx_pps=excluded.seconds_over_tx_pps,
        drops=excluded.drops,errors=excluded.errors,
        cpu_full_percent=excluded.cpu_full_percent,cpu_core_percent=excluded.cpu_core_percent,
        vcpu_current=excluded.vcpu_current,ram_current_kib=excluded.ram_current_kib,
        ram_rss_kib=excluded.ram_rss_kib,ram_available_kib=excluded.ram_available_kib,
        ram_unused_kib=excluded.ram_unused_kib,ram_usable_kib=excluded.ram_usable_kib,
        disk_read_bps=excluded.disk_read_bps,disk_write_bps=excluded.disk_write_bps,
        disk_read_iops=excluded.disk_read_iops,disk_write_iops=excluded.disk_write_iops
    """, (
        PUBLIC_BRIDGE, PUBLIC_BRIDGE, PRIVATE_BRIDGE, PRIVATE_BRIDGE,
        PUBLIC_BRIDGE, PRIVATE_BRIDGE, PUBLIC_BRIDGE, PRIVATE_BRIDGE,
        PUBLIC_BRIDGE, PRIVATE_BRIDGE, PUBLIC_BRIDGE, PRIVATE_BRIDGE,
        data_time, interval_seconds,
    ))

    nh = node_host if isinstance(node_host, dict) else {}
    mem_total = max(0, safe_int(nh.get("mem_total"), 0))
    mem_used = max(0, safe_int(nh.get("mem_used"), 0))
    if mem_used <= 0 and mem_total > 0:
        mem_used = max(0, mem_total - max(0, safe_int(nh.get("mem_available"), 0)))
    conn.execute("""
      INSERT INTO node_current_fast(
        node,last_seen,interval_seconds,vm_count,iface_count,
        public_bytes,private_bytes,total_bytes,public_packets,private_packets,total_packets,
        drops,errors,load1,load5,load15,cpu_count,cpu_percent,
        mem_total,mem_used,disk_read_bps,disk_write_bps,uptime_seconds
      )
      SELECT ?,?,?,COUNT(*),COALESCE(SUM(iface_count),0),
             COALESCE(SUM(public_rx_bytes+public_tx_bytes),0),
             COALESCE(SUM(private_rx_bytes+private_tx_bytes),0),
             COALESCE(SUM(total_bytes),0),
             COALESCE(SUM(public_pps*interval_seconds),0)::bigint,
             COALESCE(SUM(private_pps*interval_seconds),0)::bigint,
             COALESCE(SUM(total_pps*interval_seconds),0)::bigint,
             COALESCE(SUM(drops),0),COALESCE(SUM(errors),0),?,?,?,?,?,?,?,?,?,?
        FROM vm_current_fast WHERE node=? AND last_seen=?
      ON CONFLICT(node) DO UPDATE SET
        last_seen=excluded.last_seen,interval_seconds=excluded.interval_seconds,
        vm_count=excluded.vm_count,iface_count=excluded.iface_count,
        public_bytes=excluded.public_bytes,private_bytes=excluded.private_bytes,total_bytes=excluded.total_bytes,
        public_packets=excluded.public_packets,private_packets=excluded.private_packets,total_packets=excluded.total_packets,
        drops=excluded.drops,errors=excluded.errors,load1=excluded.load1,load5=excluded.load5,load15=excluded.load15,
        cpu_count=excluded.cpu_count,cpu_percent=excluded.cpu_percent,
        mem_total=excluded.mem_total,mem_used=excluded.mem_used,
        disk_read_bps=excluded.disk_read_bps,disk_write_bps=excluded.disk_write_bps,
        uptime_seconds=excluded.uptime_seconds
    """, (
        node, data_time, interval_seconds,
        safe_float(nh.get("load1"), 0), safe_float(nh.get("load5"), 0), safe_float(nh.get("load15"), 0),
        safe_int(nh.get("cpu_count") or nh.get("cpu_cores"), 0), safe_float(nh.get("cpu_percent"), 0),
        mem_total, mem_used, safe_float(nh.get("disk_read_bps"), 0),
        safe_float(nh.get("disk_write_bps"), 0), safe_int(nh.get("uptime_seconds"), 0),
        node, data_time,
    ))
    if inventory_complete:
        conn.execute("DELETE FROM vm_iface_current WHERE node=? AND last_seen<?", (node, data_time))
        conn.execute("DELETE FROM vm_current_fast WHERE node=? AND last_seen<?", (node, data_time))
        conn.execute("DELETE FROM vm_abuse_state WHERE node=? AND last_seen<?", (node, data_time))

def _v5052_ingest_disk_io_current(conn, node, data_time, interval_seconds, vms, node_host):
    ensure_disk_io_schema(conn)
    disk_rows = []
    for vm in vms or []:
        if not isinstance(vm, dict):
            continue
        vm_uuid = str(vm.get("vm_uuid") or "").strip()
        if not vm_uuid:
            continue
        for disk in vm.get("disks") or []:
            if not isinstance(disk, dict):
                continue
            target = str(disk.get("target") or "").strip()
            if not target:
                continue
            sec = max(1, safe_int(disk.get("interval_seconds"), interval_seconds))
            rd = max(0, safe_int(disk.get("read_delta"), 0))
            wr = max(0, safe_int(disk.get("write_delta"), 0))
            rr = max(0, safe_int(disk.get("read_reqs_delta"), 0))
            ww = max(0, safe_int(disk.get("write_reqs_delta"), 0))
            disk_rows.append({
                "node": node, "vm_uuid": vm_uuid, "target": target,
                "source": str(disk.get("source") or "").strip(),
                "role": str(disk.get("role") or "unknown").strip().lower()[:32],
                "mount": str(disk.get("mount") or ""),
                "storage_device": str(disk.get("storage_device") or ""),
                "storage_block": str(disk.get("storage_block") or ""),
                "storage_fstype": str(disk.get("storage_fstype") or ""),
                "capacity_bytes": max(0, safe_int(disk.get("capacity_bytes"), 0)),
                "allocation_bytes": max(0, safe_int(disk.get("allocation_bytes"), 0)),
                "physical_bytes": max(0, safe_int(disk.get("physical_bytes"), 0)),
                "interval_seconds": sec,
                "read_bps": rd / float(sec), "write_bps": wr / float(sec),
                "read_iops": rr / float(sec), "write_iops": ww / float(sec),
                "last_seen": data_time,
            })
    _v5052_copy_upsert_rows(conn, "vm_disk_current", ["node", "vm_uuid", "target", "source"], disk_rows)
    conn.execute("DELETE FROM vm_disk_current WHERE node=? AND last_seen<?", (node, data_time))

    storage_rows = []
    for storage in (node_host or {}).get("storage_devices") or []:
        if not isinstance(storage, dict):
            continue
        mount = str(storage.get("mount") or "").strip()
        if not mount:
            continue
        storage_rows.append({
            "node": node, "mount": mount,
            "device": str(storage.get("device") or ""),
            "block": str(storage.get("block") or ""),
            "raid_level": str(storage.get("raid_level") or ""),
            "fstype": str(storage.get("fstype") or ""),
            "size": max(0, safe_int(storage.get("size"), 0)),
            "used": max(0, safe_int(storage.get("used"), 0)),
            "avail": max(0, safe_int(storage.get("avail"), 0)),
            "use_percent": max(0.0, safe_float(storage.get("use_percent"), 0.0)),
            "read_bps": max(0.0, safe_float(storage.get("read_bps"), 0.0)),
            "write_bps": max(0.0, safe_float(storage.get("write_bps"), 0.0)),
            "read_iops": max(0.0, safe_float(storage.get("read_iops"), 0.0)),
            "write_iops": max(0.0, safe_float(storage.get("write_iops"), 0.0)),
            "util_percent": max(0.0, safe_float(storage.get("util_percent"), 0.0)),
            "last_seen": data_time,
        })
    _v5052_copy_upsert_rows(conn, "node_storage_current", ["node", "mount"], storage_rows)
    conn.execute("DELETE FROM node_storage_current WHERE node=? AND last_seen<?", (node, data_time))
    ensure_storage_snapshot_schema(conn)
    try:
        packed = _v48137_pack_storage_payload(vms, node_host, data_time, interval_seconds)
        conn.execute(
            "UPDATE node_push_snapshots SET storage_payload=?,storage_payload_version=? WHERE node=? AND bucket=?",
            (packed, V48137_STORAGE_PAYLOAD_VERSION, node, bucket_for(data_time)),
        )
    except Exception:
        app.logger.exception("Could not retain Storage I/O snapshot for %s", node)
    _v48140_refresh_node_summaries(conn, node)

V5052_PRESENCE_STAGE = "pg_temp.vi5052_presence_stage"

def _v5052_process_node_vm_presence(conn, node, seen_vm_locations, seen_ts, inventory_complete=False):
    """Apply VM presence/inventory/location updates from one native COPY stage."""
    conn.execute("""
      CREATE TEMP TABLE IF NOT EXISTS vi5052_presence_stage(
        vm_uuid TEXT PRIMARY KEY,
        iface TEXT NOT NULL,
        bridge TEXT NOT NULL
      ) ON COMMIT DELETE ROWS
    """)
    rows = []
    for vm_uuid, loc in (seen_vm_locations or {}).items():
        vm_uuid = str(vm_uuid or "").strip()
        if not vm_uuid or vm_uuid == "-":
            continue
        loc = loc if isinstance(loc, dict) else {}
        rows.append((
            vm_uuid,
            str(loc.get("iface") or "-"),
            str(loc.get("bridge") or "-"),
        ))
    copy_started = time.perf_counter()
    if rows:
        conn.copy_rows(
            V5052_PRESENCE_STAGE,
            ("vm_uuid", "iface", "bridge"),
            rows,
        )
    copy_ms = (time.perf_counter() - copy_started) * 1000.0
    merge_started = time.perf_counter()

    if rows:
        conn.execute("""
          INSERT INTO vm_node_presence(
            vm_uuid,node,first_seen,last_seen,last_push,missing_since,
            missing_count,present_count,status,pending_node,migrated_to,
            migrated_at,purged_at,last_iface,last_bridge,alert_flags
          )
          SELECT vm_uuid,?,?,?, ?,NULL,0,1,'active',NULL,NULL,NULL,NULL,iface,bridge,''
            FROM pg_temp.vi5052_presence_stage
          ON CONFLICT(vm_uuid,node) DO UPDATE SET
            last_seen=GREATEST(vm_node_presence.last_seen,excluded.last_seen),
            last_push=excluded.last_push,missing_since=NULL,missing_count=0,
            present_count=vm_node_presence.present_count+1,status='active',
            pending_node=NULL,migrated_to=NULL,migrated_at=NULL,purged_at=NULL,
            last_iface=excluded.last_iface,last_bridge=excluded.last_bridge,alert_flags=''
        """, (node, seen_ts, seen_ts, seen_ts))
        conn.execute("""
          INSERT INTO vm_inventory(
            node,vm_uuid,first_seen,last_seen,last_iface,last_bridge,status,hidden_at,deleted_at
          )
          SELECT ?,vm_uuid,?,?,iface,bridge,'active',NULL,NULL
            FROM pg_temp.vi5052_presence_stage
          ON CONFLICT(node,vm_uuid) DO UPDATE SET
            last_seen=GREATEST(vm_inventory.last_seen,excluded.last_seen),
            last_iface=excluded.last_iface,last_bridge=excluded.last_bridge,
            status=CASE WHEN vm_inventory.status='hidden' THEN 'hidden' ELSE 'active' END,
            hidden_at=CASE WHEN vm_inventory.status='hidden' THEN vm_inventory.hidden_at ELSE NULL END,
            deleted_at=CASE WHEN vm_inventory.status='hidden' THEN vm_inventory.deleted_at ELSE NULL END
        """, (node, seen_ts, seen_ts))

    if inventory_complete:
        conn.execute("""
          WITH missing AS (
            UPDATE vm_node_presence p
               SET status='missing',
                   missing_since=COALESCE(p.missing_since,?),
                   missing_count=p.missing_count+1,
                   last_push=?,
                   alert_flags='MISSING:'||(p.missing_count+1)::text
             WHERE p.node=?
               AND p.status IN ('active','pending_migration')
               AND NOT EXISTS (
                 SELECT 1 FROM pg_temp.vi5052_presence_stage src
                  WHERE src.vm_uuid=p.vm_uuid
               )
            RETURNING p.vm_uuid
          )
          UPDATE vm_inventory i
             SET status='missing',hidden_at=NULL,deleted_at=NULL
           WHERE i.node=?
             AND COALESCE(i.status,'active')!='hidden'
             AND EXISTS (SELECT 1 FROM missing m WHERE m.vm_uuid=i.vm_uuid)
        """, (seen_ts, seen_ts, node, node))

    moved_rows = []
    if rows:
        moved_rows = conn.execute("""
          SELECT src.vm_uuid,src.iface,src.bridge
            FROM pg_temp.vi5052_presence_stage src
            JOIN vm_location_latest old ON old.vm_uuid=src.vm_uuid
           WHERE old.node<>?
           ORDER BY src.vm_uuid
        """, (node,)).fetchall()
        conn.execute("""
          INSERT INTO vm_location_latest(
            vm_uuid,node,first_seen,last_seen,previous_node,moved_at,move_count,
            last_iface,last_bridge,alert_level,alert_flags
          )
          SELECT src.vm_uuid,?,?,?,NULL,NULL,0,src.iface,src.bridge,'ok',''
            FROM pg_temp.vi5052_presence_stage src
           WHERE NOT EXISTS (
             SELECT 1 FROM vm_location_latest old WHERE old.vm_uuid=src.vm_uuid
           )
          ON CONFLICT(vm_uuid) DO NOTHING
        """, (node, seen_ts, seen_ts))
        conn.execute("""
          UPDATE vm_location_latest dst
             SET last_seen=GREATEST(dst.last_seen,?),
                 last_iface=src.iface,last_bridge=src.bridge,
                 alert_level='ok',alert_flags=''
            FROM pg_temp.vi5052_presence_stage src
           WHERE dst.vm_uuid=src.vm_uuid AND dst.node=?
        """, (seen_ts, node))

    # Cross-node transitions need the established confirmation/event workflow.
    for vm_uuid, iface, bridge in moved_rows:
        _v5050_legacy_location_transition(
            conn, str(vm_uuid), node, seen_ts, str(iface), str(bridge)
        )
    return {
        "rows": len(rows),
        "copy_ms": copy_ms,
        "merge_ms": (time.perf_counter() - merge_started) * 1000.0,
    }

# Late binding is intentional: all existing callers now use native COPY while
# the public API, Agent payload, schemas, dashboard and abuse semantics stay intact.
process_node_vm_presence = _v5052_process_node_vm_presence
_v5050_bulk_upsert_rows = _v5052_copy_upsert_rows
_v4810_current_writer = _v5052_current_writer
ingest_disk_io_current = _v5052_ingest_disk_io_current

