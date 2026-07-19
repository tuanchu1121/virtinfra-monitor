# VirtInfra Monitor v50.2.3 Dashboard Selected Snapshot fix
# ---------------------------------------------------------------------------
# Time display is intentionally fixed to the original Asia/Ho_Chi_Minh zone.
# There is no runtime timezone switch. Stored timestamps remain Unix/UTC values;
# only presentation uses the original UTC+7 clock.


def display_timezone_name():
    return TZ_NAME


def _display_timezone():
    return TZ


def fmt_full(ts):
    if not ts:
        return "-"
    return datetime.fromtimestamp(int(ts), TZ).strftime("%Y-%m-%d %H:%M:%S")


def fmt_range(ts):
    if not ts:
        return "-"
    return datetime.fromtimestamp(int(ts), TZ).strftime("%Y-%m-%d %H:%M")


def fmt_push(ts):
    if not ts:
        return "-"
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M")


def fmt_chart_label(ts, step):
    dt = datetime.fromtimestamp(int(ts), TZ)
    if step >= 86400:
        return dt.strftime("%m-%d")
    if step >= 3600:
        return dt.strftime("%m-%d %H:%M")
    return dt.strftime("%H:%M")


def _parse_datetime_local(value):
    value = (value or "").strip()
    if not value:
        return None
    # Keep old @epoch links readable, but new UI keeps the original local-time
    # behavior and does not rewrite normal datetime-local values into @epoch.
    if value.startswith("@"):
        value = value[1:]
    if value.isdigit():
        try:
            ts = int(value)
            return max(now_ts() - HOURLY_RETENTION_DAYS * 86400, min(now_ts(), ts))
        except ValueError:
            return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt).replace(tzinfo=TZ)
            ts = int(dt.timestamp())
            return max(now_ts() - HOURLY_RETENTION_DAYS * 86400, min(now_ts(), ts))
        except ValueError:
            pass
    return None


def _datetime_local_value(ts):
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts), TZ).strftime("%Y-%m-%dT%H:%M")


@app.route("/livez")
def virtinfra_livez():
    return jsonify({"status": "ok", "service": PRODUCT_NAME}), 200


@app.route("/healthz")
def virtinfra_healthz():
    try:
        info = dbapi.healthcheck()
        return jsonify({"status": "ok", "service": PRODUCT_NAME, "database": info.get("database")}), 200
    except Exception as exc:
        return jsonify({"status": "error", "service": PRODUCT_NAME, "database": "unavailable", "detail": str(exc)[:300]}), 503


# Keep the existing Admin overview unchanged. The temporary display-timezone
# card and POST endpoint were removed to restore the original fixed UTC+7 UI.
_v502_admin_overview_base = _v490_admin_overview


def _v490_admin_overview(stats):
    return _v502_admin_overview_base(stats)


# PostgreSQL-backed cache generation invalidates every Gunicorn worker even when
# Redis is disabled. This makes Hide/Restore visible immediately across workers.
def _v48140_cache_generation():
    global _v48140_local_generation
    try:
        conn = db()
        try:
            row = conn.execute("SELECT value FROM admin_settings WHERE key='page_cache_generation'").fetchone()
            if not row:
                conn.execute("""
                  INSERT INTO admin_settings(key,value,updated_at)
                  VALUES('page_cache_generation','1',?)
                  ON CONFLICT(key) DO NOTHING
                """, (now_ts(),))
                conn.commit()
                return 1
            return max(1, safe_int(row[0], 1))
        finally:
            conn.close()
    except Exception:
        return max(1, _v48140_local_generation)


def _v48140_bump_cache_generation():
    global _v48140_local_generation
    with _v48140_local_lock:
        _v48140_local_generation += 1
        _v48140_local_cache.clear()
    generation = _v48140_local_generation
    try:
        conn = db()
        try:
            row = conn.execute("""
              INSERT INTO admin_settings(key,value,updated_at)
              VALUES('page_cache_generation','2',?)
              ON CONFLICT(key) DO UPDATE SET
                value=CAST(CAST(admin_settings.value AS INTEGER)+1 AS TEXT),
                updated_at=excluded.updated_at
              RETURNING value
            """, (now_ts(),)).fetchone()
            conn.commit()
            generation = max(generation, safe_int((row or [generation])[0], generation))
        finally:
            conn.close()
    except Exception:
        pass
    return generation


def _virtinfra_wrap_inventory_mutation(endpoint_name):
    current = app.view_functions.get(endpoint_name)
    if current is None or getattr(current, "_virtinfra_cache_mutation", False):
        return
    def wrapper(*args, **kwargs):
        response = app.make_response(current(*args, **kwargs))
        if request.method == "POST" and response.status_code < 400:
            _v48140_bump_cache_generation()
        return response
    wrapper.__name__ = getattr(current, "__name__", endpoint_name)
    wrapper.__doc__ = getattr(current, "__doc__", None)
    wrapper._virtinfra_cache_mutation = True
    app.view_functions[endpoint_name] = wrapper


for _virtinfra_endpoint in (
    "admin_delete_node", "admin_restore_node", "admin_delete_vm", "admin_restore_vm",
    "admin_bulk_nodes", "admin_bulk_vms", "admin_purge_node_vms",
):
    _virtinfra_wrap_inventory_mutation(_virtinfra_endpoint)


VIRTINFRA_FINAL_CSS = r"""
<style id="virtinfra-v502-final-ui">
/* Current Abuse must fit a normal desktop viewport instead of forcing 2380px. */
.abuse-current-v48129,.abuse-current-v48139{width:100%!important;min-width:0!important;table-layout:fixed!important}
.abuse-current-v48139 th,.abuse-current-v48139 td{padding:7px 6px!important;font-size:10px!important;vertical-align:top}
.abuse-current-v48139 th:nth-child(1){width:3%!important}.abuse-current-v48139 th:nth-child(2){width:14%!important}.abuse-current-v48139 th:nth-child(3){width:15%!important}.abuse-current-v48139 th:nth-child(4){width:12%!important}.abuse-current-v48139 th:nth-child(5){width:12%!important}.abuse-current-v48139 th:nth-child(6){width:9%!important}.abuse-current-v48139 th:nth-child(7){width:10%!important}.abuse-current-v48139 th:nth-child(8){width:10%!important}.abuse-current-v48139 th:nth-child(9){width:10%!important}.abuse-current-v48139 th:nth-child(10){width:5%!important}
.abuse-current-v48139 .uuid-cell,.abuse-current-v48139 .resource-primary,.abuse-current-v48139 .resource-secondary{min-width:0!important;white-space:normal!important;overflow-wrap:anywhere;word-break:break-word}
.abuse-current-v48139 .resource-meter{min-width:0!important}.abuse-current-v48139 .resource-primary{font-size:10px!important}.abuse-current-v48139 .resource-secondary{font-size:8px!important}
@media(max-width:1200px){.abuse-current-v48139 th,.abuse-current-v48139 td{padding:6px 4px!important;font-size:9px!important}.abuse-current-v48139 .metric-chip{padding:3px 4px!important}}
@media(max-width:900px){
.abuse-current-v48139,.abuse-current-v48139 tbody,.abuse-current-v48139 tr,.abuse-current-v48139 td{display:block!important;width:100%!important;min-width:0!important}
.abuse-current-v48139 thead{display:none!important}
.abuse-current-v48139 tr{margin:0 0 12px!important;padding:8px!important;border:1px solid var(--line,#d9e1ee)!important;border-radius:10px!important;background:var(--card,#fff)!important;box-sizing:border-box!important}
.abuse-current-v48139 td{position:relative!important;min-height:32px!important;padding:7px 6px 7px 39%!important;border:0!important;border-bottom:1px dashed var(--line,#d9e1ee)!important;box-sizing:border-box!important;font-size:10px!important;text-align:left!important}
.abuse-current-v48139 td:last-child{border-bottom:0!important}
.abuse-current-v48139 td::before{position:absolute;left:6px;top:7px;width:31%;font-size:9px;font-weight:900;letter-spacing:.04em;color:var(--muted,#64748b);text-transform:uppercase;white-space:normal}
.abuse-current-v48139 td:nth-child(1)::before{content:"#"}.abuse-current-v48139 td:nth-child(2)::before{content:"Node / VM"}.abuse-current-v48139 td:nth-child(3)::before{content:"Reason / Severity"}.abuse-current-v48139 td:nth-child(4)::before{content:"Network AVG"}.abuse-current-v48139 td:nth-child(5)::before{content:"PPS Peak / Window"}.abuse-current-v48139 td:nth-child(6)::before{content:"CPU"}.abuse-current-v48139 td:nth-child(7)::before{content:"RAM"}.abuse-current-v48139 td:nth-child(8)::before{content:"Capacity"}.abuse-current-v48139 td:nth-child(9)::before{content:"Disk I/O"}.abuse-current-v48139 td:nth-child(10)::before{content:"Last seen"}
.abuse-current-v48139 .resource-meter,.abuse-current-v48139 .metric-pair-rich{width:100%!important;max-width:none!important}
}
</style>
"""


_page_virtinfra_v502_base = page


def page(title, content):
    response = _page_virtinfra_v502_base(title, VIRTINFRA_FINAL_CSS + content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace("VirtInfra Monitor", PRODUCT_NAME)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply VirtInfra final UI layer")
    return response

# ---------------------------------------------------------------------------
