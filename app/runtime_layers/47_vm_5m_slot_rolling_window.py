# R22.11 exact rolling VM Consumption with end-of-interval slot semantics.
#
# The canonical vm_consumption_hourly row keeps twelve packed five-minute byte
# slots plus a twelve-bit presence mask. Complete hours/days continue to use
# the compact totals; only the two partial hour edges read array elements from
# at most two hourly rows per VM/bridge.

R2210_RELEASE = "50.5.9-prod-r22.12.3-slim-current-only"
R2210_SLOT_SECONDS = max(1, safe_int(CACHE_BUCKET_SECONDS, 300))
R2210_SLOTS_PER_HOUR = 12

def _r21_normalized_range(start, end):
    """Use one shared five-minute rolling boundary for VM, Node and Group."""
    duration = max(R2210_SLOT_SECONDS, safe_int(end, 0) - safe_int(start, 0))
    normalized_end = (safe_int(end, 0) // R2210_SLOT_SECONDS) * R2210_SLOT_SECONDS
    return normalized_end - duration, normalized_end

def _v5058r7_vm_rollup_window(start, end):
    """Return the true rolling window ending at the latest closed 5m bucket."""
    return _r21_normalized_range(start, end)

def _r2210_ceil_hour(ts):
    base = local_hour_start(ts)
    return base if safe_int(ts, 0) == base else base + 3600

def _r2210_slot_bounds(hour_start, start, end):
    first = max(0, min(R2210_SLOTS_PER_HOUR, (safe_int(start, 0) - hour_start) // R2210_SLOT_SECONDS))
    last = max(first, min(R2210_SLOTS_PER_HOUR, (safe_int(end, 0) - hour_start) // R2210_SLOT_SECONDS))
    return int(first), int(last)

def _r2210_slot_sum_sql(column, first, last):
    terms = [
        "CASE WHEN COALESCE(slot_5m_version,1)>=2 THEN COALESCE(%s[%d],0) ELSE 0 END" % (column, index + 1)
        for index in range(first, last)
    ]
    return "+".join(terms) if terms else "0"

def _r2210_mask_count_sql(column, first, last):
    terms = [
        "CASE WHEN COALESCE(slot_5m_version,1)>=2 AND (COALESCE(%s,0)&%d)<>0 THEN 1 ELSE 0 END" % (column, 1 << index)
        for index in range(first, last)
    ]
    return "+".join(terms) if terms else "0"

def _r2210_latest_slot_sql(mask_column, hour_start, first, last):
    values = [
        "CASE WHEN COALESCE(slot_5m_version,1)>=2 AND (COALESCE(%s,0)&%d)<>0 THEN %d ELSE 0 END" % (
            mask_column, 1 << index, hour_start + (index + 1) * R2210_SLOT_SECONDS,
        )
        for index in range(first, last)
    ]
    if not values:
        return "0"
    return "GREATEST(%s)" % ",".join(values)

def _r2210_vm_edge_branch(start, end, selected_node=""):
    """Read one partial-hour segment from packed slots only.

    Existing pre-R22.10 rows have NULL slots. During the bounded warm-up period,
    bytes and coverage use a proportional hourly compatibility estimate. New
    rows become exact to the five-minute bucket as soon as their slots arrive.
    """
    start = safe_int(start, 0); end = safe_int(end, 0)
    if end <= start:
        return "", []
    hour_start = local_hour_start(start)
    if local_hour_start(max(start, end - 1)) != hour_start:
        raise ValueError("VM slot edge must stay within one local hour")
    first, last = _r2210_slot_bounds(hour_start, start, end)
    slot_count = max(0, last - first)
    rx_exact = _r2210_slot_sum_sql("rx_5m_slots", first, last)
    tx_exact = _r2210_slot_sum_sql("tx_5m_slots", first, last)
    rx_all = _r2210_slot_sum_sql("rx_5m_slots", 0, R2210_SLOTS_PER_HOUR)
    tx_all = _r2210_slot_sum_sql("tx_5m_slots", 0, R2210_SLOTS_PER_HOUR)
    samples_exact = _r2210_mask_count_sql("sample_5m_mask", first, last)
    samples_all = _r2210_mask_count_sql("sample_5m_mask", 0, R2210_SLOTS_PER_HOUR)
    latest_exact = _r2210_latest_slot_sql("sample_5m_mask", hour_start, first, last)
    node_clause = " AND node=?" if selected_node else ""

    # A row can straddle the rollout: its hourly total may contain old unpacked
    # samples plus new exact slots. Preserve the exact selected slots and spread
    # only the residual old total across the still-unpacked positions. This makes
    # the warm-up monotonic instead of dropping the pre-upgrade part of an hour as
    # soon as the first R22.10 slot arrives.
    sql = """
      SELECT node,vm_uuid,bridge,
             (selected_rx + CASE WHEN packed_known>=12 THEN 0 ELSE
                ROUND(GREATEST(COALESCE(rx_bytes,0)-packed_rx,0)
                  *GREATEST(%d-selected_known,0)/GREATEST(12-packed_known,1)::numeric)
              END)::bigint AS rx_bytes,
             (selected_tx + CASE WHEN packed_known>=12 THEN 0 ELSE
                ROUND(GREATEST(COALESCE(tx_bytes,0)-packed_tx,0)
                  *GREATEST(%d-selected_known,0)/GREATEST(12-packed_known,1)::numeric)
              END)::bigint AS tx_bytes,
             LEAST(%d,selected_known + CASE WHEN packed_known>=12 THEN 0 ELSE
                LEAST(
                  GREATEST(LEAST(12,COALESCE(sample_count,0))-packed_known,0),
                  GREATEST(%d-selected_known,0)
                )
              END)::bigint AS sample_count,
             GREATEST(selected_latest,CASE WHEN selected_known<%d AND COALESCE(sample_count,0)>packed_known
                THEN LEAST(COALESCE(last_push,0),%d) ELSE 0 END)::bigint AS last_push
        FROM (
          SELECT *,
                 (%s)::bigint AS selected_rx,
                 (%s)::bigint AS selected_tx,
                 (%s)::bigint AS packed_rx,
                 (%s)::bigint AS packed_tx,
                 (%s)::bigint AS selected_known,
                 (%s)::bigint AS packed_known,
                 (%s)::bigint AS selected_latest
            FROM vm_consumption_hourly
           WHERE hour_start=?%s
        ) edge
    """ % (
        slot_count, slot_count, slot_count, slot_count, slot_count,
        max(start, end - 1),
        rx_exact, tx_exact, rx_all, tx_all, samples_exact, samples_all, latest_exact,
        node_clause,
    )
    params = [hour_start]
    if selected_node:
        params.append(selected_node)
    return sql, params

def _r2210_vm_hourly_branch(start, end, selected_node=""):
    if end <= start:
        return "", []
    all_samples = _r2210_mask_count_sql("sample_5m_mask", 0, R2210_SLOTS_PER_HOUR)
    node_clause = " AND node=?" if selected_node else ""
    sql = """
      SELECT node,vm_uuid,bridge,rx_bytes,tx_bytes,
             GREATEST(
               CASE WHEN COALESCE(slot_5m_version,1)>=2 AND COALESCE(sample_5m_mask,0)<>0
                    THEN (%s)::bigint ELSE 0 END,
               LEAST(12,COALESCE(sample_count,0))::bigint
             ) AS sample_count,
             last_push
        FROM vm_consumption_hourly
       WHERE hour_start>=? AND hour_start<?%s
    """ % (all_samples, node_clause)
    params = [start, end]
    if selected_node:
        params.append(selected_node)
    return sql, params

def _r2210_add_edge_parts(branches, params, start, end, selected_node=""):
    cursor = safe_int(start, 0); end = safe_int(end, 0)
    while cursor < end:
        part_end = min(end, local_hour_start(cursor) + 3600)
        sql, values = _r2210_vm_edge_branch(cursor, part_end, selected_node)
        if sql:
            branches.append(sql); params.extend(values)
        cursor = part_end

def _r2210_add_complete_middle(branches, params, start, end, selected_node=""):
    if end <= start:
        return
    first_day = local_day_start(start)
    full_day_start = first_day if start == first_day else first_day + 86400
    full_day_end = local_day_start(end)
    if full_day_start < full_day_end:
        if start < full_day_start:
            sql, values = _r2210_vm_hourly_branch(start, full_day_start, selected_node)
            if sql:
                branches.append(sql); params.extend(values)
        sql, values = _v5058r7_vm_daily_branch(full_day_start, full_day_end, selected_node)
        if sql:
            branches.append(sql); params.extend(values)
        if full_day_end < end:
            sql, values = _r2210_vm_hourly_branch(full_day_end, end, selected_node)
            if sql:
                branches.append(sql); params.extend(values)
    else:
        sql, values = _r2210_vm_hourly_branch(start, end, selected_node)
        if sql:
            branches.append(sql); params.extend(values)

def _v5058c_vm_source_sql(start, end, selected_node=""):
    """Build a bounded rolling source from packed edges plus hour/day totals."""
    start, end = _v5058r7_vm_rollup_window(start, end)
    if end <= start:
        return (
            "SELECT node,vm_uuid,bridge,rx_bytes,tx_bytes,sample_count,last_push "
            "FROM vm_consumption_hourly WHERE 1=0",
            [],
        )

    first_full_hour = _r2210_ceil_hour(start)
    last_full_hour = local_hour_start(end)
    branches, params = [], []

    if first_full_hour >= last_full_hour:
        _r2210_add_edge_parts(branches, params, start, end, selected_node)
    else:
        if start < first_full_hour:
            _r2210_add_edge_parts(branches, params, start, first_full_hour, selected_node)
        _r2210_add_complete_middle(
            branches, params, first_full_hour, last_full_hour, selected_node,
        )
        if last_full_hour < end:
            _r2210_add_edge_parts(branches, params, last_full_hour, end, selected_node)

    if not branches:
        return (
            "SELECT node,vm_uuid,bridge,rx_bytes,tx_bytes,sample_count,last_push "
            "FROM vm_consumption_hourly WHERE 1=0",
            [],
        )
    return " UNION ALL ".join(branches), params

# Summary caches use the same five-minute boundary as the table query.
def _v5058r4_cached_totals(kind, start, end, selected_node, compute):
    seconds = max(R2210_SLOT_SECONDS, safe_int(end, 0) - safe_int(start, 0))
    cache_end = (safe_int(end, 0) // R2210_SLOT_SECONDS) * R2210_SLOT_SECONDS
    cache_start = cache_end - seconds
    key = "v5058r4:summary:%s:%s:%s:%s" % (kind, cache_start, cache_end, selected_node or "*")
    try:
        cached = _v48140_cache_get(key)
        if cached:
            data = json.loads(cached)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    data = compute(cache_start, cache_end, selected_node)
    try:
        _v48140_cache_set(key, json.dumps(data, separators=(",", ":")), V5058R4_SUMMARY_CACHE_TTL)
    except Exception:
        pass
    return data
