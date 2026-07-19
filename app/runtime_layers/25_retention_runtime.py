# v48.12.5 bounded 7-day retention + hourly automatic cleanup
# ---------------------------------------------------------------------------
V48125_VERSION = "48.12.5"

# The earlier retention implementation already preserves one *real* agent push
# per node/local-hour.  This layer bounds every historical/log table to seven
# days while preserving current state, inventory, users, settings and API keys.
_run_retention_v48125_base = run_retention


def _v48125_retention_specs(cutoff):
    return (
        ("bandwidth_daily", "day_start<?", (cutoff,)),
        ("api_access_logs", "request_time<?", (cutoff,)),
        ("api_key_events", "event_time<?", (cutoff,)),
        ("node_logs", "time<?", (cutoff,)),
        ("account_logs", "time<?", (cutoff,)),
        ("node_missed_events", "created_at<?", (cutoff,)),
        ("vm_migration_events", "time<?", (cutoff,)),
        ("maintenance_jobs", "status NOT IN ('queued','running') AND COALESCE(finished_at,created_at)<?", (cutoff,)),
        ("retention_runs", "COALESCE(finished_at,started_at)<?", (cutoff,)),
    )


def run_retention(dry_run=False):
    stats = _run_retention_v48125_base(dry_run=dry_run)
    cutoff = now_ts() - HISTORY_RETENTION_DAYS * 86400
    stats["policy"] = {
        "raw_days": RAW_RETENTION_DAYS,
        "hourly_days": HOURLY_RETENTION_DAYS,
        "history_days": HISTORY_RETENTION_DAYS,
        "raw_resolution_seconds": CACHE_BUCKET_SECONDS,
        "hourly_resolution_seconds": 3600,
        "mode": "real_snapshot",
    }
    conn = db()
    try:
        existing_tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for table, where_sql, params in _v48125_retention_specs(cutoff):
            if table not in existing_tables:
                continue
            if dry_run:
                value = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where_sql}", params).fetchone()[0]
                stats.setdefault("deleted", {})[table] = int(value or 0)
            else:
                value = _delete_in_batches(conn, table, where_sql, params)
                stats.setdefault("deleted", {})[table] = int(value or 0)
        stats["total_deleted"] = sum(safe_int(v, 0) for v in stats.get("deleted", {}).values())
        if not dry_run:
            conn.execute("PRAGMA optimize")
            conn.commit()
            # The base retention function records its core metrics before this
            # bounded-event sweep. Refresh the newest successful run so Admin
            # shows the complete v48.12.5 result, including log/event cleanup.
            latest = conn.execute(
                "SELECT id FROM retention_runs WHERE status='ok' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if latest:
                conn.execute(
                    "UPDATE retention_runs SET detail=? WHERE id=?",
                    (json.dumps(stats, separators=(",", ":"), default=str), int(latest[0])),
                )
                conn.commit()
        return stats
    finally:
        conn.close()


V48125_UI_CSS = r"""
<style id="v48125-retention-admin-layout">
.retention-policy-strip{display:grid;grid-template-columns:repeat(3,minmax(180px,1fr));gap:10px;margin:10px 0 14px}
.retention-policy-strip>div{border:1px solid #cbd5e1;border-radius:10px;padding:11px 12px;background:#f8fafc}
.retention-policy-strip b{display:block;font-size:14px;color:#0f172a}.retention-policy-strip small{display:block;margin-top:3px;color:#64748b}
.admin-abuse-danger{display:grid!important;grid-template-columns:repeat(3,minmax(230px,1fr));gap:12px!important;align-items:stretch}
.admin-abuse-danger>.bulk-bar{display:grid!important;grid-template-columns:1fr!important;grid-template-rows:minmax(58px,auto) 42px;gap:9px!important;align-content:start!important;margin:0!important;padding:12px!important;border:1px solid #fecaca;border-radius:10px;background:#fff!important}
.admin-abuse-danger>.bulk-bar label{display:grid!important;align-content:start;gap:5px;margin:0!important;min-width:0!important}
.admin-abuse-danger>.bulk-bar input[type=text],.admin-abuse-danger>.bulk-bar input:not([type]){width:100%!important;min-width:0!important}
.admin-abuse-danger>.bulk-bar button{width:100%;min-height:40px;align-self:end}
.admin-abuse-danger>.table-hint{grid-column:1/-1;margin-top:0}
html[data-theme=dark] .retention-policy-strip>div{background:#10243a;border-color:#31577e}
html[data-theme=dark] .retention-policy-strip b{color:#fff}
html[data-theme=dark] .retention-policy-strip small{color:#c9d9ea}
html[data-theme=dark] .admin-abuse-danger>.bulk-bar{background:#1d1519!important;border-color:#7f1d1d}
@media(max-width:1050px){.admin-abuse-danger{grid-template-columns:1fr!important}.retention-policy-strip{grid-template-columns:1fr}}
</style>
"""

_page_v48125_base = page


def page(title, content):
    policy = f"""
    <div class="retention-policy-strip">
      <div><b>Latest 48 hours</b><small>Every real 5-minute Agent push</small></div>
      <div><b>Days 3-7</b><small>One real retained snapshot per local hour</small></div>
      <div><b>Older than 7 days</b><small>Automatically deleted; current state is preserved</small></div>
    </div>
    """
    if title in {"Admin", "Abuse Management"} and "retention-policy-strip" not in content:
        content = policy + content
    response = _page_v48125_base(title, content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace("</head>", V48125_UI_CSS + "</head>", 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.12.5 retention layout")
    return response

# ---------------------------------------------------------------------------
