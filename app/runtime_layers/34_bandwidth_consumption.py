# VirtInfra Monitor v50.3.0 Bandwidth Consumption
# ---------------------------------------------------------------------------
# This module is intentionally additive. It does not change the operational
# 5-minute metrics, Abuse engine, Storage I/O, Dashboard or existing /push
# protocol. Agents submit one compact node aggregate for each completed local
# 2-hour bucket. VM UUIDs and per-VM history are deliberately not stored.

V5030_RELEASE = "50.5.9-prod-r3-ui-alignment-overflow-hotfix"
V5030_BW_TABLE = "node_bandwidth_consumption_2h"
V5030_BW_BUCKET_SECONDS = 2 * 3600
V5030_BW_RETENTION_SECONDS = 7 * 86400
V5030_BW_TZ_OFFSET_SECONDS = 7 * 3600
V5030_BW_ACCEPT_AFTER_KEY = "bandwidth_consumption_accept_after"
V5030_BW_PERIODS = {
    "2h": ("2H", 2 * 3600),
    "6h": ("6H", 6 * 3600),
    "12h": ("12H", 12 * 3600),
    "1d": ("1D", 86400),
    "2d": ("2D", 2 * 86400),
    "3d": ("3D", 3 * 86400),
    "4d": ("4D", 4 * 86400),
    "5d": ("5D", 5 * 86400),
    "6d": ("6D", 6 * 86400),
    "7d": ("7D", 7 * 86400),
}
V5030_BW_COUNTER_COLUMNS = (
    "physical_public_rx_bytes",
    "physical_public_tx_bytes",
    "physical_private_rx_bytes",
    "physical_private_tx_bytes",
    "vm_public_rx_bytes",
    "vm_public_tx_bytes",
    "vm_private_rx_bytes",
    "vm_private_tx_bytes",
)


def _v5030_local_bucket_start(ts):
    ts = safe_int(ts, now_ts())
    return (
        ((ts + V5030_BW_TZ_OFFSET_SECONDS) // V5030_BW_BUCKET_SECONDS)
        * V5030_BW_BUCKET_SECONDS
        - V5030_BW_TZ_OFFSET_SECONDS
    )


def _v5030_period(value):
    value = str(value or "1d").strip().lower()
    return value if value in V5030_BW_PERIODS else "1d"


def _v5030_section(value):
    value = str(value or "all").strip().lower()
    allowed = {
        "all",
        "physical_public",
        "physical_private",
        "vm_public",
        "vm_private",
        "public_difference",
        "private_difference",
    }
    return value if value in allowed else "all"


def _v5030_node_status_filter(value):
    value = str(value or "all").strip().lower()
    return value if value in {"all", "online", "missed", "down"} else "all"


def _v5030_coverage_filter(value):
    value = str(value or "all").strip().lower()
    return value if value in {"all", "complete", "incomplete", "no_data"} else "all"


def _v5030_sort(value):
    value = str(value or "node").strip().lower()
    allowed = {
        "node", "status", "coverage", "last_received",
        "physical_public_rx", "physical_public_tx", "physical_public_total",
        "physical_private_rx", "physical_private_tx", "physical_private_total",
        "vm_public_rx", "vm_public_tx", "vm_public_total",
        "vm_private_rx", "vm_private_tx", "vm_private_total",
        "public_difference_rx", "public_difference_tx", "public_difference_total",
        "private_difference_rx", "private_difference_tx", "private_difference_total",
    }
    return value if value in allowed else "node"


def _v5030_ensure_bandwidth_consumption_schema():
    conn = db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS node_bandwidth_consumption_2h (
                node TEXT NOT NULL,
                bucket_start INTEGER NOT NULL,
                bucket_end INTEGER NOT NULL,
                physical_public_rx_bytes BIGINT NOT NULL DEFAULT 0,
                physical_public_tx_bytes BIGINT NOT NULL DEFAULT 0,
                physical_private_rx_bytes BIGINT NOT NULL DEFAULT 0,
                physical_private_tx_bytes BIGINT NOT NULL DEFAULT 0,
                vm_public_rx_bytes BIGINT NOT NULL DEFAULT 0,
                vm_public_tx_bytes BIGINT NOT NULL DEFAULT 0,
                vm_private_rx_bytes BIGINT NOT NULL DEFAULT 0,
                vm_private_tx_bytes BIGINT NOT NULL DEFAULT 0,
                coverage_seconds INTEGER NOT NULL DEFAULT 0,
                sample_count INTEGER NOT NULL DEFAULT 0,
                estimated INTEGER NOT NULL DEFAULT 0,
                agent_version INTEGER NOT NULL DEFAULT 0,
                received_at INTEGER NOT NULL,
                PRIMARY KEY (node, bucket_start)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_node_bw_consumption_bucket
            ON node_bandwidth_consumption_2h(bucket_start DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_node_bw_consumption_node_bucket
            ON node_bandwidth_consumption_2h(node, bucket_start DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_node_bw_consumption_received
            ON node_bandwidth_consumption_2h(received_at DESC)
        """)
        conn.commit()
    finally:
        conn.close()


_v5030_ensure_bandwidth_consumption_schema()


def _v5030_cleanup_bandwidth_consumption(cutoff=None):
    cutoff = safe_int(cutoff, now_ts() - V5030_BW_RETENTION_SECONDS)
    conn = db()
    try:
        cur = conn.execute(
            "DELETE FROM node_bandwidth_consumption_2h WHERE bucket_end<=?",
            (cutoff,),
        )
        deleted = max(0, safe_int(cur.rowcount, 0))
        conn.commit()
        return deleted
    finally:
        conn.close()


def _v5030_bandwidth_accept_after():
    return max(0, safe_int(get_admin_setting(V5030_BW_ACCEPT_AFTER_KEY, "0"), 0))


def _v5030_set_bandwidth_accept_after(ts=None):
    ts = max(0, safe_int(ts, now_ts()))
    set_admin_setting(V5030_BW_ACCEPT_AFTER_KEY, str(ts))
    return ts


@app.route("/push/bandwidth-consumption", methods=["POST"])
def push_bandwidth_consumption():
    if not valid_agent_token(request.headers.get("X-Token", "")):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        payload = read_agent_json_request()
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    node = str(payload.get("node") or "").strip()[:255]
    bucket_start = safe_int(payload.get("bucket_start"), 0)
    bucket_end = safe_int(payload.get("bucket_end"), 0)
    if not node:
        return jsonify({"ok": False, "error": "missing node"}), 400
    if bucket_start <= 0 or bucket_end - bucket_start != V5030_BW_BUCKET_SECONDS:
        return jsonify({"ok": False, "error": "invalid 2-hour bucket"}), 400
    if _v5030_local_bucket_start(bucket_start) != bucket_start:
        return jsonify({"ok": False, "error": "bucket is not aligned to local 2-hour boundary"}), 400
    if bucket_end > now_ts() + 300:
        return jsonify({"ok": False, "error": "future bucket"}), 400

    # A full reset establishes a hard epoch. Old Agent-local retries are
    # acknowledged but ignored so deleted history cannot reappear.
    accept_after = _v5030_bandwidth_accept_after()
    if accept_after and bucket_start < accept_after:
        return jsonify({
            "ok": True,
            "ignored": True,
            "reason": "before reset epoch",
            "accept_after": accept_after,
        })

    values = [max(0, safe_int(payload.get(name), 0)) for name in V5030_BW_COUNTER_COLUMNS]
    coverage_seconds = max(0, min(V5030_BW_BUCKET_SECONDS, safe_int(payload.get("coverage_seconds"), 0)))
    sample_count = max(0, safe_int(payload.get("sample_count"), 0))
    estimated = 1 if bool(payload.get("estimated")) else 0
    agent_version = max(0, safe_int(payload.get("agent_version"), 0))
    received_at = now_ts()

    conn = db()
    try:
        # Serialize only the same node. The PK and UPSERT make retries safe.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("virtinfra-bwcons:" + node,))
        conn.execute("""
            INSERT INTO node_bandwidth_consumption_2h(
                node,bucket_start,bucket_end,
                physical_public_rx_bytes,physical_public_tx_bytes,
                physical_private_rx_bytes,physical_private_tx_bytes,
                vm_public_rx_bytes,vm_public_tx_bytes,
                vm_private_rx_bytes,vm_private_tx_bytes,
                coverage_seconds,sample_count,estimated,agent_version,received_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(node,bucket_start) DO UPDATE SET
                bucket_end=excluded.bucket_end,
                physical_public_rx_bytes=excluded.physical_public_rx_bytes,
                physical_public_tx_bytes=excluded.physical_public_tx_bytes,
                physical_private_rx_bytes=excluded.physical_private_rx_bytes,
                physical_private_tx_bytes=excluded.physical_private_tx_bytes,
                vm_public_rx_bytes=excluded.vm_public_rx_bytes,
                vm_public_tx_bytes=excluded.vm_public_tx_bytes,
                vm_private_rx_bytes=excluded.vm_private_rx_bytes,
                vm_private_tx_bytes=excluded.vm_private_tx_bytes,
                coverage_seconds=excluded.coverage_seconds,
                sample_count=excluded.sample_count,
                estimated=excluded.estimated,
                agent_version=excluded.agent_version,
                received_at=excluded.received_at
        """, (
            node, bucket_start, bucket_end,
            *values,
            coverage_seconds, sample_count, estimated, agent_version, received_at,
        ))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "node": node,
        "bucket_start": bucket_start,
        "bucket_end": bucket_end,
        "retention_days": 7,
    })


def _v5030_status_name(last_push):
    state, _age, _misses = node_status_state(last_push)
    if state == "green":
        return "online"
    if state == "yellow":
        return "missed"
    return "down"


def _v5030_row_values(row, expected_buckets):
    item = dict(row)
    item["node"] = str(item.get("node") or "")
    item["public_ipv4"] = compact_ipv4(item.get("public_ipv4") or "")
    item["private_ipv4"] = compact_ipv4(item.get("private_ipv4") or "")
    for name in V5030_BW_COUNTER_COLUMNS:
        item[name] = max(0, safe_int(item.get(name), 0))
    item["bucket_count"] = max(0, safe_int(item.get("bucket_count"), 0))
    item["coverage_seconds"] = max(0, safe_int(item.get("coverage_seconds"), 0))
    item["last_received"] = max(0, safe_int(item.get("last_received"), 0))
    item["last_push"] = max(0, safe_int(item.get("last_push"), 0))
    item["estimated_count"] = max(0, safe_int(item.get("estimated_count"), 0))
    item["status"] = _v5030_status_name(item["last_push"])
    item["expected_buckets"] = max(1, safe_int(expected_buckets, 1))
    expected_seconds = item["expected_buckets"] * V5030_BW_BUCKET_SECONDS
    item["coverage_ratio"] = min(1.0, item["coverage_seconds"] / float(max(1, expected_seconds)))
    item["coverage"] = item["coverage_ratio"]
    if item["bucket_count"] <= 0:
        item["coverage_state"] = "no_data"
    elif item["bucket_count"] >= item["expected_buckets"] and item["coverage_seconds"] >= expected_seconds:
        item["coverage_state"] = "complete"
    else:
        item["coverage_state"] = "incomplete"

    item["physical_public_rx"] = item["physical_public_rx_bytes"]
    item["physical_public_tx"] = item["physical_public_tx_bytes"]
    item["physical_public_total"] = item["physical_public_rx"] + item["physical_public_tx"]
    item["physical_private_rx"] = item["physical_private_rx_bytes"]
    item["physical_private_tx"] = item["physical_private_tx_bytes"]
    item["physical_private_total"] = item["physical_private_rx"] + item["physical_private_tx"]
    item["vm_public_rx"] = item["vm_public_rx_bytes"]
    item["vm_public_tx"] = item["vm_public_tx_bytes"]
    item["vm_public_total"] = item["vm_public_rx"] + item["vm_public_tx"]
    item["vm_private_rx"] = item["vm_private_rx_bytes"]
    item["vm_private_tx"] = item["vm_private_tx_bytes"]
    item["vm_private_total"] = item["vm_private_rx"] + item["vm_private_tx"]
    item["public_difference_rx"] = item["physical_public_rx"] - item["vm_public_rx"]
    item["public_difference_tx"] = item["physical_public_tx"] - item["vm_public_tx"]
    item["public_difference_total"] = item["physical_public_total"] - item["vm_public_total"]
    item["private_difference_rx"] = item["physical_private_rx"] - item["vm_private_rx"]
    item["private_difference_tx"] = item["physical_private_tx"] - item["vm_private_tx"]
    item["private_difference_total"] = item["physical_private_total"] - item["vm_private_total"]
    return item


def _v5030_bandwidth_rows(start, end, expected_buckets, q=""):
    q = str(q or "").strip()
    params = [start, end]
    search_sql = ""
    if q:
        like = "%" + q + "%"
        search_sql = """
          AND (
            LOWER(ni.node) LIKE LOWER(?)
            OR EXISTS(
              SELECT 1 FROM node_bridge_addresses_latest ba
              WHERE ba.node=ni.node
                AND (LOWER(COALESCE(ba.primary_ipv4,'')) LIKE LOWER(?)
                     OR LOWER(COALESCE(ba.ipv4_json,'')) LIKE LOWER(?))
            )
          )
        """
        params.extend([like, like, like])

    conn = db()
    try:
        rows = conn.execute("""
            SELECT
                ni.node AS node,
                COALESCE(ni.last_push,0) AS last_push,
                COUNT(b.bucket_start) AS bucket_count,
                COALESCE(SUM(b.coverage_seconds),0) AS coverage_seconds,
                COALESCE(SUM(b.physical_public_rx_bytes),0) AS physical_public_rx_bytes,
                COALESCE(SUM(b.physical_public_tx_bytes),0) AS physical_public_tx_bytes,
                COALESCE(SUM(b.physical_private_rx_bytes),0) AS physical_private_rx_bytes,
                COALESCE(SUM(b.physical_private_tx_bytes),0) AS physical_private_tx_bytes,
                COALESCE(SUM(b.vm_public_rx_bytes),0) AS vm_public_rx_bytes,
                COALESCE(SUM(b.vm_public_tx_bytes),0) AS vm_public_tx_bytes,
                COALESCE(SUM(b.vm_private_rx_bytes),0) AS vm_private_rx_bytes,
                COALESCE(SUM(b.vm_private_tx_bytes),0) AS vm_private_tx_bytes,
                COALESCE(MAX(b.received_at),0) AS last_received,
                COALESCE(SUM(CASE WHEN b.estimated=1 THEN 1 ELSE 0 END),0) AS estimated_count,
                COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest ba
                          WHERE ba.node=ni.node AND LOWER(COALESCE(ba.role,''))='public'
                          ORDER BY ba.last_seen DESC LIMIT 1),'') AS public_ipv4,
                COALESCE((SELECT primary_ipv4 FROM node_bridge_addresses_latest ba
                          WHERE ba.node=ni.node AND LOWER(COALESCE(ba.role,''))='private'
                          ORDER BY ba.last_seen DESC LIMIT 1),'') AS private_ipv4
            FROM node_inventory ni
            LEFT JOIN node_bandwidth_consumption_2h b
              ON b.node=ni.node
             AND b.bucket_start>=?
             AND b.bucket_start<?
            WHERE COALESCE(ni.status,'active')!='hidden'
              AND ni.deleted_at IS NULL
        """ + search_sql + """
            GROUP BY ni.node,ni.last_push
        """, tuple(params)).fetchall()
        result = []
        for row in rows:
            mapped = {
                "node": row[0],
                "last_push": row[1],
                "bucket_count": row[2],
                "coverage_seconds": row[3],
                "physical_public_rx_bytes": row[4],
                "physical_public_tx_bytes": row[5],
                "physical_private_rx_bytes": row[6],
                "physical_private_tx_bytes": row[7],
                "vm_public_rx_bytes": row[8],
                "vm_public_tx_bytes": row[9],
                "vm_private_rx_bytes": row[10],
                "vm_private_tx_bytes": row[11],
                "last_received": row[12],
                "estimated_count": row[13],
                "public_ipv4": row[14],
                "private_ipv4": row[15],
            }
            result.append(_v5030_row_values(mapped, expected_buckets))
        return result
    finally:
        conn.close()


def _v5030_sort_rows(rows, sort_by, order):
    reverse = clean_sort_order(order) == "desc"
    if sort_by == "node":
        return sorted(rows, key=lambda x: str(x.get("node") or "").lower(), reverse=reverse)
    if sort_by == "status":
        rank = {"online": 0, "missed": 1, "down": 2}
        return sorted(rows, key=lambda x: (rank.get(x.get("status"), 9), str(x.get("node") or "").lower()), reverse=reverse)
    return sorted(
        rows,
        key=lambda x: (safe_float(x.get(sort_by), 0.0), str(x.get("node") or "").lower()),
        reverse=reverse,
    )


def _v5030_fmt_signed(value):
    value = safe_int(value, 0)
    sign = "+" if value > 0 else ("-" if value < 0 else "")
    absolute = abs(float(value))
    if absolute >= 1024.0 ** 4:
        scaled, unit = absolute / (1024.0 ** 4), "TB"
    elif absolute >= 1024.0 ** 3:
        scaled, unit = absolute / (1024.0 ** 3), "GB"
    else:
        # Difference values intentionally use MB as the minimum display unit so
        # small byte deltas do not expand into long, noisy integer strings.
        scaled, unit = absolute / (1024.0 ** 2), "MB"
    return f"{sign}{scaled:.2f} {unit}"


def _v5030_sort_link(label, key, current, order, **kwargs):
    next_order = reverse_order(order) if key == current else "desc"
    arrow = ""
    if key == current:
        arrow = " ↓" if clean_sort_order(order) == "desc" else " ↑"
    href = url_for("bandwidth_consumption_page", sort=key, order=next_order, **kwargs)
    active = " active" if key == current else ""
    return '<a class="sort-link%s" href="%s">%s%s</a>' % (
        active,
        escape(href, quote=True),
        escape(label),
        arrow,
    )


def _v5030_group_tone(prefix, diff=False):
    if diff or prefix.startswith("public_difference") or prefix.startswith("private_difference"):
        return "difference"
    tones = {
        "physical_public": "physical-public",
        "physical_private": "physical-private",
        "vm_public": "vm-public",
        "vm_private": "vm-private",
    }
    return tones.get(prefix, "neutral")


def _v5030_metric_group(title, prefix, item, diff=False):
    rx = item.get(prefix + "_rx", 0)
    tx = item.get(prefix + "_tx", 0)
    total = item.get(prefix + "_total", 0)
    formatter = _v5030_fmt_signed if diff else human
    tone = _v5030_group_tone(prefix, diff=diff)
    return """
      <div class="bwcons-group %s">
        <div class="bwcons-group-title">%s</div>
        <div class="bwcons-triplet">
          <span class="rx">RX<b>%s</b></span>
          <span class="tx">TX<b>%s</b></span>
          <span class="total">TOTAL<b>%s</b></span>
        </div>
      </div>
    """ % (tone, escape(title), formatter(rx), formatter(tx), formatter(total))


def _v5030_summary_card(title, prefix, totals, tone):
    return """
      <div class="card bwcons-summary %s">
        <span>%s</span>
        <div><small>RX</small><b>%s</b></div>
        <div><small>TX</small><b>%s</b></div>
        <div><small>TOTAL</small><b>%s</b></div>
      </div>
    """ % (
        tone,
        escape(title),
        human(totals.get(prefix + "_rx", 0)),
        human(totals.get(prefix + "_tx", 0)),
        human(totals.get(prefix + "_total", 0)),
    )


@app.route("/bandwidth-consumption")
def bandwidth_consumption_page():
    period = _v5030_period(request.args.get("period"))
    q = str(request.args.get("q") or "").strip()
    section = _v5030_section(request.args.get("section"))
    status_filter = _v5030_node_status_filter(request.args.get("status"))
    coverage_filter = _v5030_coverage_filter(request.args.get("coverage"))
    sort_by = _v5030_sort(request.args.get("sort"))
    order = clean_sort_order(request.args.get("order", "desc" if sort_by != "node" else "asc"))

    label, seconds = V5030_BW_PERIODS[period]
    end = _v5030_local_bucket_start(now_ts())
    start = end - seconds
    expected_buckets = max(1, seconds // V5030_BW_BUCKET_SECONDS)
    rows = _v5030_bandwidth_rows(start, end, expected_buckets, q=q)
    if status_filter != "all":
        rows = [row for row in rows if row.get("status") == status_filter]
    if coverage_filter != "all":
        rows = [row for row in rows if row.get("coverage_state") == coverage_filter]
    rows = _v5030_sort_rows(rows, sort_by, order)

    totals = {}
    for prefix in ("physical_public", "physical_private", "vm_public", "vm_private"):
        totals[prefix + "_rx"] = sum(safe_int(row.get(prefix + "_rx"), 0) for row in rows)
        totals[prefix + "_tx"] = sum(safe_int(row.get(prefix + "_tx"), 0) for row in rows)
        totals[prefix + "_total"] = totals[prefix + "_rx"] + totals[prefix + "_tx"]

    common = {
        "period": period,
        "q": q or None,
        "section": section,
        "status": status_filter,
        "coverage": coverage_filter,
    }
    period_links = []
    for key, (text, _value) in V5030_BW_PERIODS.items():
        href = url_for("bandwidth_consumption_page", period=key, q=q or None, section=section, status=status_filter, coverage=coverage_filter, sort=sort_by, order=order)
        period_links.append('<a class="%s" href="%s">%s</a>' % ("active" if key == period else "", escape(href, quote=True), text))

    section_options = [
        ("all", "All sections"),
        ("physical_public", "Physical Public"),
        ("physical_private", "Physical Private"),
        ("vm_public", "VM Public"),
        ("vm_private", "VM Private"),
        ("public_difference", "Public Difference"),
        ("private_difference", "Private Difference"),
    ]
    section_html = "".join('<option value="%s"%s>%s</option>' % (key, " selected" if key == section else "", text) for key, text in section_options)
    status_options = [("all", "All status"), ("online", "Online"), ("missed", "Missed"), ("down", "Down")]
    status_html = "".join('<option value="%s"%s>%s</option>' % (key, " selected" if key == status_filter else "", text) for key, text in status_options)
    coverage_options = [("all", "All coverage"), ("complete", "Complete"), ("incomplete", "Incomplete"), ("no_data", "No data")]
    coverage_html = "".join('<option value="%s"%s>%s</option>' % (key, " selected" if key == coverage_filter else "", text) for key, text in coverage_options)

    table_rows = []
    for row in rows:
        node = row["node"]
        href = url_for("bandwidth_consumption_node_page", node=node, period=period)
        state = row["status"]
        badge_cls = "ok" if state == "online" else ("warn" if state == "missed" else "crit")
        coverage_state = row["coverage_state"]
        coverage_cls = "ok" if coverage_state == "complete" else ("warn" if coverage_state == "incomplete" else "neutral")
        coverage_text = "%s / %s" % (row["bucket_count"], row["expected_buckets"])
        if row["estimated_count"]:
            coverage_text += " · %s estimated" % row["estimated_count"]

        groups = []
        if section in {"all", "physical_public"}:
            groups.append(_v5030_metric_group("Physical Public", "physical_public", row))
        if section in {"all", "physical_private"}:
            groups.append(_v5030_metric_group("Physical Private", "physical_private", row))
        if section in {"all", "vm_public"}:
            groups.append(_v5030_metric_group("VM Public", "vm_public", row))
        if section in {"all", "vm_private"}:
            groups.append(_v5030_metric_group("VM Private", "vm_private", row))
        if section in {"all", "public_difference"}:
            groups.append(_v5030_metric_group("Public Difference", "public_difference", row, diff=True))
        if section in {"all", "private_difference"}:
            groups.append(_v5030_metric_group("Private Difference", "private_difference", row, diff=True))
        public_ip = str(row.get("public_ipv4") or "").strip()
        ip_line = (
            '<span class="bwcons-ip"><span class="mono">%s</span><button type="button" class="copy-btn" data-copy="%s" title="Copy Public IP">⧉</button></span>'
            % (escape(public_ip), escape(public_ip, quote=True))
            if public_ip
            else '<span class="bwcons-ip muted"><span class="mono">-</span></span>'
        )
        table_rows.append("""
          <tr>
            <td class="bwcons-node">
              <div class="bwcons-node-main"><a href="%s"><b>%s</b></a><span class="status %s">%s</span></div>
              <div class="bwcons-node-ips">%s</div>
            </td>
            <td><div class="bwcons-groups">%s</div></td>
            <td><span class="status %s">%s</span><small>%s%% complete</small></td>
            <td><b>%s</b><small>%s</small></td>
          </tr>
        """ % (
            escape(href, quote=True), escape(node), badge_cls, state.title(),
            ip_line,
            "".join(groups), coverage_cls, escape(coverage_text), round(row["coverage_ratio"] * 100.0, 1),
            fmt_full(row["last_received"]) if row["last_received"] else "-",
            "Latest completed bucket: " + fmt_full(end),
        ))
    if not table_rows:
        table_rows.append('<tr><td colspan="4" class="empty">No visible node matches the selected search and filters.</td></tr>')

    sort_specs = [
        ("Node", "node"),
        ("Physical Public RX", "physical_public_rx"),
        ("Physical Public TX", "physical_public_tx"),
        ("Physical Public Total", "physical_public_total"),
        ("Physical Private RX", "physical_private_rx"),
        ("Physical Private TX", "physical_private_tx"),
        ("Physical Private Total", "physical_private_total"),
        ("VM Public RX", "vm_public_rx"),
        ("VM Public TX", "vm_public_tx"),
        ("VM Public Total", "vm_public_total"),
        ("VM Private RX", "vm_private_rx"),
        ("VM Private TX", "vm_private_tx"),
        ("VM Private Total", "vm_private_total"),
        ("Public Difference RX", "public_difference_rx"),
        ("Public Difference TX", "public_difference_tx"),
        ("Public Difference Total", "public_difference_total"),
        ("Private Difference RX", "private_difference_rx"),
        ("Private Difference TX", "private_difference_tx"),
        ("Private Difference Total", "private_difference_total"),
        ("Coverage", "coverage"),
        ("Last Received", "last_received"),
    ]
    sort_bar = "".join(
        _v5030_sort_link(text, key, sort_by, order, **common)
        for text, key in sort_specs
    )

    content = """
    <style id="v5030-bandwidth-consumption-css">
      .bwcons-hero{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}.bwcons-hero h2{margin:4px 0}.bwcons-hero p{margin:0;color:var(--muted,#667085)}
      .bwcons-periods,.bwcons-sortbar{display:flex;gap:7px;flex-wrap:wrap}.bwcons-periods a,.bwcons-sortbar a{padding:7px 10px;border:1px solid var(--line,#dfe5ec);border-radius:9px;text-decoration:none;font-size:12px}.bwcons-periods a.active,.bwcons-sortbar a.active{background:#1677ff;color:#fff;border-color:#1677ff}
      .bwcons-summary-grid{display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:12px}.bwcons-summary{padding:15px;background:var(--panel,#fff);border-top:1px solid var(--line,#dfe5ec)}.bwcons-summary>span{display:block;font-weight:800;margin-bottom:10px}.bwcons-summary>div{display:flex;justify-content:space-between;padding:5px 0}.bwcons-summary small{color:var(--muted,#667085)}.bwcons-summary b{font-variant-numeric:tabular-nums;color:var(--text,#111827)}.bwcons-summary.public,.bwcons-summary.private,.bwcons-summary.vmpublic,.bwcons-summary.vmprivate{border-top-color:var(--line,#dfe5ec)}
      .bwcons-toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.bwcons-toolbar input{min-width:260px;flex:1}.bwcons-toolbar select{min-width:150px}.bwcons-sortbar{margin-top:12px}.bwcons-table{min-width:1220px}.bwcons-table th:nth-child(1){width:215px}.bwcons-table th:nth-child(3){width:160px}.bwcons-table th:nth-child(4){width:190px}
      .bwcons-node{vertical-align:top}.bwcons-node-main{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}.bwcons-node-main a{display:block}.bwcons-node-ips{display:flex;flex-direction:column;gap:6px}.bwcons-ip{display:inline-flex;align-items:center;gap:6px;width:max-content;max-width:100%%;padding:4px 7px;border-radius:8px;border:1px solid var(--line,#d9e2ec);background:var(--panel,#fff);color:var(--muted,#667085)}.bwcons-ip .mono{font-size:11px;font-variant-numeric:tabular-nums;color:var(--text,#111827)}.bwcons-ip.muted{color:var(--muted,#667085)}.bwcons-ip .copy-btn{margin-left:2px;transform:scale(.84)}
      .bwcons-groups{display:grid;grid-template-columns:repeat(2,minmax(215px,1fr));gap:10px}.bwcons-group,.bwcons-group.physical-public,.bwcons-group.physical-private,.bwcons-group.vm-public,.bwcons-group.vm-private,.bwcons-group.difference{border:1px solid var(--line,#e2e8f0);border-radius:10px;padding:10px;background:var(--panel,#fff)}.bwcons-group-title{font-size:11px;font-weight:800;text-transform:uppercase;color:var(--muted,#667085);margin-bottom:7px}.bwcons-triplet{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.bwcons-triplet span{font-size:10px;color:var(--muted,#667085);font-weight:700}.bwcons-triplet span.rx b,.bwcons-triplet span.tx b{color:var(--text,#111827)}.bwcons-triplet span.total b{color:var(--text,#111827);font-weight:900}.bwcons-triplet b{display:block;margin-top:3px;font-size:12px;font-variant-numeric:tabular-nums}.bwcons-table td>small{display:block;margin-top:6px;color:var(--muted,#667085)}
      @media(max-width:1250px){.bwcons-summary-grid{grid-template-columns:repeat(2,minmax(180px,1fr))}.bwcons-groups{grid-template-columns:repeat(2,minmax(190px,1fr))}}@media(max-width:760px){.bwcons-summary-grid{grid-template-columns:1fr}.bwcons-toolbar input{min-width:100%%}.bwcons-groups{grid-template-columns:1fr}}
    </style>
    <div class="card bwcons-hero"><div><span class="eyebrow">NODE ACCOUNTING</span><h2>Consumption</h2><p>Physical and aggregate VM traffic remain separate for Public and Private networks. No per-VM UUID history is stored.</p></div><div class="hero-meta"><span>Bucket <b>2 hours</b></span><span>Retention <b>7 days</b></span><span>Timezone <b>%s</b></span></div></div>
    <div class="card"><div class="label">Time range · latest completed local bucket</div><div class="bwcons-periods">%s</div><div class="table-hint">Range: %s → %s. The current unfinished 2-hour bucket is not included.</div></div>
    <div class="bwcons-summary-grid">%s%s%s%s</div>
    <div class="card">
      <form class="bwcons-toolbar" method="get" action="%s">
        <input type="hidden" name="period" value="%s"><input type="hidden" name="sort" value="%s"><input type="hidden" name="order" value="%s">
        <input name="q" value="%s" placeholder="Search visible node or node IP">
        <select name="section">%s</select><select name="status">%s</select><select name="coverage">%s</select>
        <button type="submit">Apply</button><a class="clear" href="%s">Reset</a>
      </form>
      <div class="bwcons-sortbar">%s</div>
    </div>
    <div class="card"><div class="table-wrap"><table class="bwcons-table"><thead><tr><th>NODE</th><th>SEPARATE NETWORK SECTIONS</th><th>COVERAGE</th><th>LAST RECEIVED</th></tr></thead><tbody>%s</tbody></table></div></div>
    """ % (
        escape(TZ_NAME), "".join(period_links), fmt_full(start), fmt_full(end),
        _v5030_summary_card("Physical Public", "physical_public", totals, "public"),
        _v5030_summary_card("Physical Private", "physical_private", totals, "private"),
        _v5030_summary_card("VM Public", "vm_public", totals, "vmpublic"),
        _v5030_summary_card("VM Private", "vm_private", totals, "vmprivate"),
        url_for("bandwidth_consumption_page"), escape(period, quote=True), escape(sort_by, quote=True), escape(order, quote=True), escape(q, quote=True),
        section_html, status_html, coverage_html, url_for("bandwidth_consumption_page"), sort_bar, "".join(table_rows),
    )
    return page("Consumption", content)


def _v5030_bandwidth_admin_stats():
    conn = db()
    try:
        row = conn.execute("""
            SELECT COUNT(*),COALESCE(MIN(bucket_start),0),COALESCE(MAX(bucket_end),0),
                   COALESCE(MAX(received_at),0)
            FROM node_bandwidth_consumption_2h
        """).fetchone()
        visible_nodes = safe_int(conn.execute("""
            SELECT COUNT(*) FROM node_inventory
            WHERE COALESCE(status,'active')!='hidden' AND deleted_at IS NULL
        """).fetchone()[0], 0)
        reporting = safe_int(conn.execute("""
            SELECT COUNT(DISTINCT b.node)
            FROM node_bandwidth_consumption_2h b
            JOIN node_inventory ni ON ni.node=b.node
            WHERE COALESCE(ni.status,'active')!='hidden'
              AND ni.deleted_at IS NULL
              AND b.bucket_end>?
        """, (now_ts() - V5030_BW_RETENTION_SECONDS,)).fetchone()[0], 0)
        try:
            size = safe_int(conn.execute("SELECT COALESCE(pg_total_relation_size('node_bandwidth_consumption_2h'),0)").fetchone()[0], 0)
        except Exception:
            size = 0
        return {
            "rows": safe_int(row[0], 0),
            "oldest": safe_int(row[1], 0),
            "newest": safe_int(row[2], 0),
            "last_received": safe_int(row[3], 0),
            "size": size,
            "visible_nodes": visible_nodes,
            "reporting": reporting,
            "missing": max(0, visible_nodes - reporting),
            "accept_after": _v5030_bandwidth_accept_after(),
        }
    finally:
        conn.close()


_v5030_admin_overview_base = _v490_admin_overview


def _v490_admin_overview(stats):
    # r6: accounting/RETENTION7 controls live only under Maintenance.
    return _v5030_admin_overview_base(stats)



@app.route("/admin/bandwidth-consumption", methods=["POST"])
def admin_bandwidth_consumption_action():
    deny = require_admin()
    if deny:
        return deny
    action = str(request.form.get("action") or "").strip().lower()
    if action == "cleanup":
        deleted = _v5030_cleanup_bandwidth_consumption()
        log_account_event("bandwidth_consumption_cleanup", username=str(session.get("admin_username") or ""), realm="admin", role="admin", detail="deleted=%s" % deleted)
        _v48140_bump_cache_generation()
        return redirect(url_for("admin_page", section="system", message="Bandwidth cleanup deleted %s expired rows." % deleted))
    if action == "clear":
        if str(request.form.get("confirm_text") or "").strip() != "CLEAR BANDWIDTH HISTORY":
            return Response("Confirmation text mismatch\n", status=400, mimetype="text/plain")
        conn = db()
        try:
            cur = conn.execute("DELETE FROM node_bandwidth_consumption_2h")
            deleted = max(0, safe_int(cur.rowcount, 0))
            conn.commit()
        finally:
            conn.close()
        epoch = _v5030_set_bandwidth_accept_after(now_ts())
        log_account_event("bandwidth_consumption_clear", username=str(session.get("admin_username") or ""), realm="admin", role="admin", detail="deleted=%s accept_after=%s" % (deleted, epoch))
        _v48140_bump_cache_generation()
        return redirect(url_for("admin_page", section="system", message="Bandwidth history cleared."))
    return Response("Unsupported action\n", status=400, mimetype="text/plain")


# Existing retention and manual history cleanup now include the dedicated table.
_v5030_run_retention_base = run_retention


def run_retention(dry_run=False):
    result = dict(_v5030_run_retention_base(dry_run=dry_run) or {})
    if dry_run:
        conn = db()
        try:
            cutoff = now_ts() - V5030_BW_RETENTION_SECONDS
            count = safe_int(conn.execute("SELECT COUNT(*) FROM node_bandwidth_consumption_2h WHERE bucket_end<=?", (cutoff,)).fetchone()[0], 0)
        finally:
            conn.close()
    else:
        count = _v5030_cleanup_bandwidth_consumption()
    result.setdefault("deleted", {})[V5030_BW_TABLE] = max(0, safe_int(count, 0))
    result["total_deleted"] = sum(safe_int(value, 0) for value in result.get("deleted", {}).values())
    result["bandwidth_consumption_retention_days"] = 7
    return result


_v5030_delete_history_base = delete_history_older_than


def delete_history_older_than(days):
    result = dict(_v5030_delete_history_base(days) or {})
    # The feature has a strict 7-day maximum. Manual 1/3/7-day cleanup follows
    # the selected age for consistency with the existing Admin operation.
    cutoff = now_ts() - safe_int(days, 7) * 86400
    result["node_bandwidth_consumption_2h"] = _v5030_cleanup_bandwidth_consumption(cutoff=cutoff)
    return result


# Purging a node permanently removes its accounting history. Hide/restore does
# not delete anything because page queries use node_inventory visibility.
_v5030_purge_node_data_base = purge_node_data


def purge_node_data(conn, node):
    result = dict(_v5030_purge_node_data_base(conn, node) or {})
    result[V5030_BW_TABLE] = _delete_count(conn, "DELETE FROM node_bandwidth_consumption_2h WHERE node=?", (node,))
    return result


# Complete monitoring clear/reset paths must include the new table.
MONITORING_DATA_TABLES = tuple(dict.fromkeys(tuple(MONITORING_DATA_TABLES) + (V5030_BW_TABLE,)))
V48102_RESET_APP_TABLES = tuple(dict.fromkeys(tuple(V48102_RESET_APP_TABLES) + (V5030_BW_TABLE,)))


_v5030_clear_all_monitoring_data_base = clear_all_monitoring_data


def clear_all_monitoring_data():
    result = _v5030_clear_all_monitoring_data_base()
    epoch = _v5030_set_bandwidth_accept_after(now_ts())
    result["bandwidth_consumption_accept_after"] = epoch
    return result


_v5030_reset_all_app_data_base = reset_all_app_data


def reset_all_app_data():
    result = _v5030_reset_all_app_data_base()
    epoch = _v5030_set_bandwidth_accept_after(now_ts())
    if isinstance(result, dict):
        result["bandwidth_consumption_accept_after"] = epoch
    return result


# Keep the page cheap and consistent with the existing cross-worker cache.
_v48140_cached_endpoint("bandwidth_consumption_page", V48140_PAGE_CACHE_TTL)



def _v5030_bandwidth_node_buckets(node, start, end):
    conn = db()
    try:
        visible = conn.execute("""
            SELECT node,COALESCE(last_push,0)
            FROM node_inventory
            WHERE node=?
              AND COALESCE(status,'active')!='hidden'
              AND deleted_at IS NULL
        """, (node,)).fetchone()
        if not visible:
            return None, []
        rows = conn.execute("""
            SELECT *
            FROM node_bandwidth_consumption_2h
            WHERE node=? AND bucket_start>=? AND bucket_start<?
            ORDER BY bucket_start DESC
        """, (node, start, end)).fetchall()
        mapped_rows = []
        for row in rows:
            mapped_rows.append({
                "node": row[0],
                "bucket_start": row[1],
                "bucket_end": row[2],
                "physical_public_rx_bytes": row[3],
                "physical_public_tx_bytes": row[4],
                "physical_private_rx_bytes": row[5],
                "physical_private_tx_bytes": row[6],
                "vm_public_rx_bytes": row[7],
                "vm_public_tx_bytes": row[8],
                "vm_private_rx_bytes": row[9],
                "vm_private_tx_bytes": row[10],
                "coverage_seconds": row[11],
                "sample_count": row[12],
                "estimated": row[13],
                "agent_version": row[14],
                "received_at": row[15],
            })
        return {"node": str(visible[0]), "last_push": safe_int(visible[1], 0)}, mapped_rows
    finally:
        conn.close()


@app.route("/bandwidth-consumption/node/<path:node>")
def bandwidth_consumption_node_page(node):
    node = str(node or "").strip()
    period = _v5030_period(request.args.get("period"))
    label, seconds = V5030_BW_PERIODS[period]
    end = _v5030_local_bucket_start(now_ts())
    start = end - seconds
    inventory, buckets = _v5030_bandwidth_node_buckets(node, start, end)
    if not inventory:
        return page(
            "Consumption",
            '<div class="card"><h3>Node unavailable</h3><div class="empty">The node does not exist or is hidden.</div></div>',
        ), 404

    period_links = []
    for key, (text, _value) in V5030_BW_PERIODS.items():
        href = url_for("bandwidth_consumption_node_page", node=node, period=key)
        period_links.append('<a class="%s" href="%s">%s</a>' % (
            "active" if key == period else "",
            escape(href, quote=True),
            text,
        ))

    rows = []
    for raw in buckets:
        item = _v5030_row_values(raw, 1)
        coverage = min(100.0, item["coverage_seconds"] * 100.0 / V5030_BW_BUCKET_SECONDS)
        coverage_cls = "ok" if coverage >= 100.0 else "warn"
        rows.append("""
          <tr>
            <td><b>%s → %s</b><small>Received %s</small></td>
            <td>%s</td><td>%s</td><td>%s</td><td>%s</td>
            <td>%s</td><td>%s</td>
            <td><span class="status %s">%.1f%%</span><small>%s samples%s</small></td>
          </tr>
        """ % (
            fmt_full(item["bucket_start"]), fmt_full(item["bucket_end"]), fmt_full(item["received_at"]),
            _v5030_metric_group("Physical Public", "physical_public", item),
            _v5030_metric_group("Physical Private", "physical_private", item),
            _v5030_metric_group("VM Public", "vm_public", item),
            _v5030_metric_group("VM Private", "vm_private", item),
            _v5030_metric_group("Public Difference", "public_difference", item, diff=True),
            _v5030_metric_group("Private Difference", "private_difference", item, diff=True),
            coverage_cls, coverage, item["sample_count"], " · estimated" if item["estimated"] else "",
        ))
    if not rows:
        rows.append('<tr><td colspan="8" class="empty">No completed 2-hour bucket is available for this node in the selected range.</td></tr>')

    content = """
    <style id="v5030-bandwidth-node-css">
      .bwcons-periods{display:flex;gap:7px;flex-wrap:wrap}.bwcons-periods a{padding:7px 10px;border:1px solid var(--line,#dfe5ec);border-radius:9px;text-decoration:none;font-size:12px}.bwcons-periods a.active{background:#1677ff;color:#fff;border-color:#1677ff}
      .bwcons-detail-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.bwcons-detail-head h2{margin:4px 0}.bwcons-detail-head p{margin:0;color:var(--muted,#667085)}
      .bwcons-detail-table{min-width:2200px}.bwcons-detail-table th:first-child{width:245px}.bwcons-detail-table th:last-child{width:145px}.bwcons-detail-table td{vertical-align:top}.bwcons-detail-table td>small{display:block;margin-top:7px;color:var(--muted,#667085)}
      .bwcons-group{border:1px solid var(--line,#e2e8f0);border-radius:10px;padding:8px;min-width:225px}.bwcons-group-title{font-size:11px;font-weight:800;text-transform:uppercase;color:var(--muted,#667085);margin-bottom:6px}.bwcons-triplet{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}.bwcons-triplet span{font-size:10px;color:var(--muted,#667085)}.bwcons-triplet b{display:block;margin-top:2px;color:var(--text,#111827);font-size:12px;font-variant-numeric:tabular-nums}
    </style>
    <div class="card bwcons-detail-head"><div><span class="eyebrow">CONSUMPTION · NODE</span><h2>%s</h2><p>Completed local 2-hour buckets. Public and Private remain separate; VM values are aggregate node totals.</p></div><div class="hero-meta"><a class="btn" href="%s">Open Node</a><a class="btn" href="%s">Back to Consumption</a></div></div>
    <div class="card"><div class="label">Time range · %s</div><div class="bwcons-periods">%s</div><div class="table-hint">%s → %s · Node status: %s · Last operational push: %s</div></div>
    <div class="card"><div class="table-wrap"><table class="bwcons-detail-table"><thead><tr><th>BUCKET</th><th>PHYSICAL PUBLIC</th><th>PHYSICAL PRIVATE</th><th>VM PUBLIC</th><th>VM PRIVATE</th><th>PUBLIC DIFFERENCE</th><th>PRIVATE DIFFERENCE</th><th>COVERAGE</th></tr></thead><tbody>%s</tbody></table></div></div>
    """ % (
        escape(node),
        escape(url_for("node_page", node=node, period="2h"), quote=True),
        escape(url_for("bandwidth_consumption_page", period=period), quote=True),
        label, "".join(period_links), fmt_full(start), fmt_full(end),
        _v5030_status_name(inventory["last_push"]).title(), fmt_full(inventory["last_push"]),
        "".join(rows),
    )
    return page("Consumption · %s" % node, content)


_v48140_cached_endpoint("bandwidth_consumption_node_page", V48140_PAGE_CACHE_TTL)


# ---------------------------------------------------------------------------
# v50.4.2 Consumption authentication hotfix + storage V2: exact 5-minute charts with short raw detail
# ---------------------------------------------------------------------------
# UI routes, HTML/CSS, chart JavaScript, API responses, current-state writers,
# Abuse and Consumption stay unchanged. Only the backend history source used by
# existing chart helper functions is switched when VIRTINFRA_READ_CHART_V2=1.

_v5040_query_vm_chart_legacy = query_vm_chart
_v5040_query_node_chart_legacy = query_node_chart
_v5040_query_vm_perf_chart_legacy = query_vm_perf_chart
_v5040_query_node_network_health_chart_legacy = query_node_network_health_chart
_v5040_query_node_perf_chart_legacy = query_node_perf_chart
_v5040_query_node_host_chart_legacy = query_node_host_chart


def _v5040_chart_step(rows, period):
    gaps = [
        safe_int(rows[i].get("bucket"), 0) - safe_int(rows[i - 1].get("bucket"), 0)
        for i in range(1, len(rows))
        if safe_int(rows[i].get("bucket"), 0) > safe_int(rows[i - 1].get("bucket"), 0)
    ]
    # V2 never down-samples to hourly. Even an empty or one-point result must
    # keep the existing chart contract on the native 5-minute resolution.
    return min(gaps) if gaps else CACHE_BUCKET_SECONDS


def _v5040_iface_values(raw_value, bridge="", iface=""):
    items = []
    for item in storage_v2.parse_interfaces_json(raw_value):
        if bridge and str(item.get("bridge") or "") != bridge:
            continue
        if iface and str(item.get("iface") or "") != iface:
            continue
        items.append(item)
    return items


def _v5040_network_row(bucket, interval, last_push, values, sample_defaults=None):
    interval = max(1, safe_int(interval, CACHE_BUCKET_SECONDS))
    sample_defaults = sample_defaults or {}
    rx = sum(max(0, safe_int(x.get("rx_bytes"), 0)) for x in values)
    tx = sum(max(0, safe_int(x.get("tx_bytes"), 0)) for x in values)
    rxp = sum(max(0, safe_int(x.get("rx_packets"), 0)) for x in values)
    txp = sum(max(0, safe_int(x.get("tx_packets"), 0)) for x in values)
    rxd = sum(max(0, safe_int(x.get("rx_drops"), 0)) for x in values)
    txd = sum(max(0, safe_int(x.get("tx_drops"), 0)) for x in values)
    rxe = sum(max(0, safe_int(x.get("rx_errors"), 0)) for x in values)
    txe = sum(max(0, safe_int(x.get("tx_errors"), 0)) for x in values)
    rx_mbps_peak = max([0.0] + [max(0.0, safe_float(x.get("rx_mbps_peak"), 0)) for x in values])
    tx_mbps_peak = max([0.0] + [max(0.0, safe_float(x.get("tx_mbps_peak"), 0)) for x in values])
    rx_pps_peak = max([0.0] + [max(0.0, safe_float(x.get("rx_pps_peak"), 0)) for x in values])
    tx_pps_peak = max([0.0] + [max(0.0, safe_float(x.get("tx_pps_peak"), 0)) for x in values])
    quality_rank = max(
        [0] + [
            {"POOR": 3, "DEGRADED": 2, "GOOD": 1}.get(str(x.get("sample_quality") or "LEGACY").upper(), 0)
            for x in values
        ]
    )
    return {
        "bucket": safe_int(bucket, 0),
        "label": fmt_chart_label(bucket, interval),
        "rx": rx, "tx": tx, "total": rx + tx,
        "rx_mbps": rx * 8.0 / interval / 1000000.0,
        "tx_mbps": tx * 8.0 / interval / 1000000.0,
        "mbps": (rx + tx) * 8.0 / interval / 1000000.0,
        "rx_mbps_peak": rx_mbps_peak, "tx_mbps_peak": tx_mbps_peak,
        "peak_mbps": max(rx_mbps_peak, tx_mbps_peak),
        "rx_packets": rxp, "tx_packets": txp, "packets": rxp + txp,
        "rx_pps": rxp / interval, "tx_pps": txp / interval, "pps": (rxp + txp) / interval,
        "rx_pps_peak": rx_pps_peak, "tx_pps_peak": tx_pps_peak,
        "peak_pps": max(rx_pps_peak, tx_pps_peak),
        "rx_packet_size_avg": rx / float(rxp) if rxp else 0.0,
        "tx_packet_size_avg": tx / float(txp) if txp else 0.0,
        "sample_count": sum(max(0, safe_int(x.get("sample_count"), 0)) for x in values) if values else safe_int(sample_defaults.get("sample_count"), 0),
        "sample_expected": sum(max(0, safe_int(x.get("sample_expected"), 0)) for x in values) if values else safe_int(sample_defaults.get("sample_expected"), 0),
        "sample_max_gap_seconds": max([safe_float(sample_defaults.get("sample_max_gap"), 0.0)] + [safe_float(x.get("sample_max_gap"), 0.0) for x in values]),
        "seconds_over_pps": sum(max(0, safe_int(x.get("seconds_over_pps"), 0)) for x in values) if values else safe_int(sample_defaults.get("seconds_over_pps"), 0),
        "seconds_over_mbps": sum(max(0, safe_int(x.get("seconds_over_mbps"), 0)) for x in values) if values else safe_int(sample_defaults.get("seconds_over_mbps"), 0),
        "sample_quality": network_quality_from_rank(quality_rank if values else safe_int(sample_defaults.get("quality_rank"), 0)),
        "rx_drops": rxd, "tx_drops": txd, "drops": rxd + txd,
        "rx_errors": rxe, "tx_errors": txe, "errors": rxe + txe,
        "last_push": safe_int(last_push, 0), "interval_seconds": interval,
    }


def query_vm_chart(node, vm_uuid, period, bridge="", iface=""):
    if not storage_v2.CHART_V2_READ_ENABLED:
        return _v5040_query_vm_chart_legacy(node, vm_uuid, period, bridge=bridge, iface=iface)
    start, end = range_for_period(period)
    conn = db()
    try:
        raw = conn.execute("""
            SELECT bucket,last_push,interval_seconds,interfaces_json,
                   sample_count,sample_expected,sample_max_gap,sample_quality,
                   seconds_over_pps,seconds_over_mbps
            FROM vm_chart_5m
            WHERE node=? AND vm_uuid=? AND bucket>=? AND bucket<?
            ORDER BY bucket
        """, (node, vm_uuid, start, end)).fetchall()
    finally:
        conn.close()
    rows = []
    for r in raw:
        values = _v5040_iface_values(r[3], bridge=bridge, iface=iface)
        # A selected bridge/interface with no match must behave like the legacy
        # GROUP BY query and omit that bucket instead of creating a fake zero.
        if (bridge or iface) and not values:
            continue
        rank = {"POOR": 3, "DEGRADED": 2, "GOOD": 1}.get(str(r[7] or "LEGACY").upper(), 0)
        rows.append(_v5040_network_row(
            r[0], r[2], r[1], values,
            {
                "sample_count": r[4], "sample_expected": r[5],
                "sample_max_gap": r[6], "quality_rank": rank,
                "seconds_over_pps": r[8], "seconds_over_mbps": r[9],
            },
        ))
    return rows, start, end, _v5040_chart_step(rows, period)


def query_vm_perf_chart(node, vm_uuid, period):
    if not storage_v2.CHART_V2_READ_ENABLED:
        return _v5040_query_vm_perf_chart_legacy(node, vm_uuid, period)
    start, end = range_for_period(period)
    conn = db()
    try:
        raw = conn.execute("""
            SELECT bucket,cpu_full_percent,cpu_core_percent,vcpu_current,
                   ram_current_kib,ram_maximum_kib,ram_rss_kib,ram_available_kib,
                   ram_unused_kib,ram_usable_kib,disk_read_bps,disk_write_bps,
                   disk_read_iops,disk_write_iops,last_push,interval_seconds
            FROM vm_chart_5m
            WHERE node=? AND vm_uuid=? AND bucket>=? AND bucket<?
            ORDER BY bucket
        """, (node, vm_uuid, start, end)).fetchall()
    finally:
        conn.close()
    rows = []
    for r in raw:
        interval = max(1, safe_int(r[15], CACHE_BUCKET_SECONDS))
        ram = vm_guest_ram_metrics(r[4], r[6], r[7], r[8], r[9])
        rd = max(0, int(round(safe_float(r[10], 0) * interval)))
        wd = max(0, int(round(safe_float(r[11], 0) * interval)))
        rows.append({
            "bucket": safe_int(r[0], 0), "label": fmt_chart_label(r[0], interval),
            "cpu_percent": safe_float(r[1], 0), "vcpu_current": safe_int(r[3], 0),
            "cpu_core_percent": safe_float(r[2], 0),
            "ram_current_bytes": safe_float(r[4], 0) * 1024,
            "ram_maximum_bytes": safe_float(r[5], 0) * 1024,
            "ram_rss_bytes": safe_float(r[6], 0) * 1024,
            "ram_available_bytes": safe_float(r[7], 0) * 1024,
            "ram_unused_bytes": safe_float(r[8], 0) * 1024,
            "ram_usable_bytes": safe_float(r[9], 0) * 1024,
            "guest_used_bytes": ram["guest_used_kib"] * 1024 if ram["has_guest"] else 0,
            "guest_total_bytes": ram["guest_total_kib"] * 1024 if ram["has_guest"] else 0,
            "guest_used_percent": ram["guest_used_pct"] if ram["has_guest"] else 0,
            "guest_stats_available": 1 if ram["has_guest"] else 0,
            "disk_read_delta": rd, "disk_write_delta": wd,
            "disk_read_bps": safe_float(r[10], 0), "disk_write_bps": safe_float(r[11], 0),
            "disk_read_reqs": max(0, int(round(safe_float(r[12], 0) * interval))),
            "disk_write_reqs": max(0, int(round(safe_float(r[13], 0) * interval))),
            "last_push": safe_int(r[14], 0),
        })
    return rows, start, end, _v5040_chart_step(rows, period)


def _v5040_node_chart_where(q):
    if not q:
        return "", []
    pattern = like_pattern(q)
    return " AND (c.vm_uuid LIKE ? OR c.node LIKE ? OR c.interfaces_json LIKE ?)", [pattern, pattern, pattern]


def query_node_chart(node, period, q="", vm_status="active"):
    if not storage_v2.CHART_V2_READ_ENABLED:
        return _v5040_query_node_chart_legacy(node, period, q=q, vm_status=vm_status)
    start, end = range_for_period(period)
    search_sql, search_params = _v5040_node_chart_where(q)
    conn = db()
    try:
        raw = conn.execute(f"""
            SELECT c.bucket,SUM(c.public_rx_bytes+c.public_tx_bytes),
                   SUM(c.private_rx_bytes+c.private_tx_bytes),
                   SUM(c.rx_bytes),SUM(c.tx_bytes),SUM(c.total_bytes),MAX(c.last_push)
            FROM vm_chart_5m c
            LEFT JOIN vm_inventory vi ON vi.node=c.node AND vi.vm_uuid=c.vm_uuid
            WHERE c.node=? AND c.bucket>=? AND c.bucket<?
              AND COALESCE(vi.status,'active')!='hidden' {search_sql}
            GROUP BY c.bucket ORDER BY c.bucket
        """, [node, start, end] + search_params).fetchall()
    finally:
        conn.close()
    rows = [{
        "bucket": safe_int(r[0], 0), "label": fmt_chart_label(r[0], CACHE_BUCKET_SECONDS),
        "public": safe_int(r[1], 0), "private": safe_int(r[2], 0),
        "rx": safe_int(r[3], 0), "tx": safe_int(r[4], 0), "total": safe_int(r[5], 0),
        "last_push": safe_int(r[6], 0),
    } for r in raw]
    return rows, start, end, _v5040_chart_step(rows, period)


def query_node_network_health_chart(node, period, q=""):
    if not storage_v2.CHART_V2_READ_ENABLED:
        return _v5040_query_node_network_health_chart_legacy(node, period, q=q)
    start, end = range_for_period(period)
    search_sql, search_params = _v5040_node_chart_where(q)
    conn = db()
    try:
        raw = conn.execute(f"""
            SELECT c.bucket,SUM(c.rx_packets),SUM(c.tx_packets),SUM(c.drops),SUM(c.errors),
                   MAX(c.last_push),MAX(c.interval_seconds)
            FROM vm_chart_5m c
            LEFT JOIN vm_inventory vi ON vi.node=c.node AND vi.vm_uuid=c.vm_uuid
            WHERE c.node=? AND c.bucket>=? AND c.bucket<?
              AND COALESCE(vi.status,'active')!='hidden' {search_sql}
            GROUP BY c.bucket ORDER BY c.bucket
        """, [node, start, end] + search_params).fetchall()
    finally:
        conn.close()
    rows = []
    for r in raw:
        interval = max(1, safe_int(r[6], CACHE_BUCKET_SECONDS))
        rxp, txp = safe_int(r[1], 0), safe_int(r[2], 0)
        rows.append({
            "bucket": safe_int(r[0], 0), "label": fmt_chart_label(r[0], interval),
            "rx_pps": rxp / interval, "tx_pps": txp / interval, "pps": (rxp + txp) / interval,
            "drops": safe_int(r[3], 0), "errors": safe_int(r[4], 0), "last_push": safe_int(r[5], 0),
        })
    return rows, start, end, _v5040_chart_step(rows, period)


def query_node_perf_chart(node, period, q=""):
    if not storage_v2.CHART_V2_READ_ENABLED:
        return _v5040_query_node_perf_chart_legacy(node, period, q=q)
    start, end = range_for_period(period)
    search_sql, search_params = _v5040_node_chart_where(q)
    conn = db()
    try:
        raw = conn.execute(f"""
            SELECT c.bucket,SUM(c.cpu_core_percent),MAX(c.cpu_core_percent),
                   SUM(c.ram_rss_kib),SUM(c.ram_current_kib),
                   SUM(CASE WHEN c.ram_available_kib>0 AND (c.ram_usable_kib>0 OR c.ram_unused_kib>0)
                                AND c.ram_usable_kib<=c.ram_available_kib*1.05
                            THEN GREATEST(c.ram_available_kib-c.ram_usable_kib,0) ELSE 0 END),
                   SUM(CASE WHEN c.ram_available_kib>0 AND (c.ram_usable_kib>0 OR c.ram_unused_kib>0)
                                AND c.ram_usable_kib<=c.ram_available_kib*1.05
                            THEN c.ram_available_kib ELSE 0 END),
                   SUM(CASE WHEN c.ram_available_kib>0 AND (c.ram_usable_kib>0 OR c.ram_unused_kib>0)
                                AND c.ram_usable_kib<=c.ram_available_kib*1.05
                            THEN 1 ELSE 0 END),
                   SUM(c.disk_read_bps),SUM(c.disk_write_bps),MAX(c.last_push)
            FROM vm_chart_5m c
            LEFT JOIN vm_inventory vi ON vi.node=c.node AND vi.vm_uuid=c.vm_uuid
            WHERE c.node=? AND c.bucket>=? AND c.bucket<?
              AND COALESCE(vi.status,'active')!='hidden' {search_sql}
            GROUP BY c.bucket ORDER BY c.bucket
        """, [node, start, end] + search_params).fetchall()
    finally:
        conn.close()
    rows = [{
        "bucket": safe_int(r[0], 0), "label": fmt_chart_label(r[0], CACHE_BUCKET_SECONDS),
        "total_cpu_percent": safe_float(r[1], 0), "max_cpu_percent": safe_float(r[2], 0),
        "ram_rss_bytes": safe_float(r[3], 0) * 1024,
        "ram_current_bytes": safe_float(r[4], 0) * 1024,
        "guest_used_bytes": safe_float(r[5], 0) * 1024,
        "guest_total_bytes": safe_float(r[6], 0) * 1024,
        "guest_stats_count": safe_int(r[7], 0),
        "disk_read_bps": safe_float(r[8], 0), "disk_write_bps": safe_float(r[9], 0),
        "last_push": safe_int(r[10], 0),
    } for r in raw]
    return rows, start, end, _v5040_chart_step(rows, period)


def query_node_host_chart(node, period):
    if not storage_v2.CHART_V2_READ_ENABLED:
        return _v5040_query_node_host_chart_legacy(node, period)
    start, end = range_for_period(period)
    conn = db()
    try:
        raw = conn.execute("""
            SELECT bucket,load1,load5,load15,cpu_percent,mem_total,mem_used,mem_available,
                   swap_total,swap_used,disk_read_bps,disk_write_bps,last_push,interval_seconds
            FROM node_chart_5m
            WHERE node=? AND bucket>=? AND bucket<?
            ORDER BY bucket
        """, (node, start, end)).fetchall()
    finally:
        conn.close()
    rows = []
    for r in raw:
        interval = max(1, safe_int(r[13], CACHE_BUCKET_SECONDS))
        rows.append({
            "bucket": safe_int(r[0], 0), "label": fmt_chart_label(r[0], interval),
            "load1": safe_float(r[1], 0), "load5": safe_float(r[2], 0), "load15": safe_float(r[3], 0),
            "host_cpu_percent": safe_float(r[4], 0),
            "mem_total_bytes": safe_float(r[5], 0), "mem_used_bytes": safe_float(r[6], 0),
            "mem_available_bytes": safe_float(r[7], 0),
            "swap_total_bytes": safe_float(r[8], 0), "swap_used_bytes": safe_float(r[9], 0),
            "host_disk_read_bps": safe_float(r[10], 0), "host_disk_write_bps": safe_float(r[11], 0),
            "last_push": safe_int(r[12], 0),
        })
    return rows, start, end, _v5040_chart_step(rows, period)


# Purge/reset paths include V2 history without changing any route or UI action.
_v5040_purge_vm_data_base = purge_vm_data


def purge_vm_data(conn, node, vm_uuid, refresh_snapshots=True):
    result = _v5040_purge_vm_data_base(conn, node, vm_uuid, refresh_snapshots=refresh_snapshots)
    deleted_chart = _delete_count(conn, "DELETE FROM vm_chart_5m WHERE node=? AND vm_uuid=?", (node, vm_uuid))
    deleted_raw = _delete_count(conn, "DELETE FROM vm_raw_detail_5m WHERE node=? AND vm_uuid=?", (node, vm_uuid))
    if isinstance(result, dict):
        result["vm_chart_5m"] = deleted_chart
        result["vm_raw_detail_5m"] = deleted_raw
    return result


_v5040_purge_node_data_base = purge_node_data


def purge_node_data(conn, node):
    result = dict(_v5040_purge_node_data_base(conn, node) or {})
    result["vm_chart_5m"] = _delete_count(conn, "DELETE FROM vm_chart_5m WHERE node=?", (node,))
    result["vm_raw_detail_5m"] = _delete_count(conn, "DELETE FROM vm_raw_detail_5m WHERE node=?", (node,))
    result["node_chart_5m"] = _delete_count(conn, "DELETE FROM node_chart_5m WHERE node=?", (node,))
    return result


MONITORING_DATA_TABLES = tuple(dict.fromkeys(tuple(MONITORING_DATA_TABLES) + (
    "vm_chart_5m", "vm_raw_detail_5m", "node_chart_5m",
)))
V48102_RESET_APP_TABLES = tuple(dict.fromkeys(tuple(V48102_RESET_APP_TABLES) + (
    "vm_chart_5m", "vm_raw_detail_5m", "node_chart_5m",
)))


def _v5040_healthz():
    try:
        info = dbapi.healthcheck()
        conn = db()
        try:
            v2 = storage_v2.storage_v2_status(conn)
        finally:
            conn.close()
        required = (storage_v2.VM_CHART_TABLE, storage_v2.VM_RAW_TABLE, storage_v2.NODE_CHART_TABLE)
        v2["ok"] = all(v2.get("tables", {}).get(name, {}).get("exists") for name in required)
        return jsonify({
            "status": "ok" if v2["ok"] else "degraded",
            "service": PRODUCT_NAME,
            "database": info.get("database"),
            "storage_v2": v2,
        }), 200 if v2["ok"] else 503
    except Exception as exc:
        app.logger.exception("healthz_storage_v2_failed")
        return jsonify({"status": "error", "service": PRODUCT_NAME, "error": str(exc)[:300]}), 503


app.view_functions["virtinfra_healthz"] = _v5040_healthz


# ---------------------------------------------------------------------------
