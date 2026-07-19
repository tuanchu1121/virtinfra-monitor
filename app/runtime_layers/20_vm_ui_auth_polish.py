# v48.10.4 compact VM RAM presentation layer
# ---------------------------------------------------------------------------
V48104_UI_CSS = r"""
<style id="v48104-compact-ram-ui">
.ram-compact-sort-head{overflow:visible!important;position:relative;z-index:8}
.ram-compact-head{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;min-height:34px}
.ram-main-sort{line-height:1}.ram-main-sort .sort-link{font-size:10.5px!important;font-weight:900!important;letter-spacing:.03em}
.ram-sort-menu{position:relative;display:block;margin:0;padding:0;line-height:1}
.ram-sort-menu>summary{list-style:none;cursor:pointer;user-select:none;color:#667085;font-size:8.5px;font-weight:800;white-space:nowrap;padding:2px 5px;border-radius:5px;border:1px solid transparent}
.ram-sort-menu>summary::-webkit-details-marker{display:none}
.ram-sort-menu>summary:hover,.ram-sort-menu[open]>summary{color:#175cd3;background:#eff4ff;border-color:#b2ccff}
.ram-sort-options{position:absolute;top:calc(100% + 4px);right:50%;transform:translateX(50%);z-index:90;min-width:128px;padding:5px;background:#fff;border:1px solid #d0d5dd;border-radius:8px;box-shadow:0 12px 28px rgba(16,24,40,.18);text-align:left}
.ram-sort-option{display:block}.ram-sort-option .sort-link{display:block!important;width:100%;box-sizing:border-box;padding:6px 8px!important;border-radius:5px;font-size:9.5px!important;line-height:1.15!important;white-space:nowrap;text-transform:none!important;letter-spacing:0!important}
.ram-sort-option .sort-link:hover{background:#f2f4f7}
.vm-ram-compact{min-width:132px!important;line-height:1.15}.vm-ram-compact .ram-guest-value{font-size:12.5px}.vm-ram-compact .ram-guest-label{margin-top:2px!important;font-size:9px!important;text-transform:none;letter-spacing:0}.vm-ram-compact .ram-meter{height:3px;margin-top:4px}.vm-ram-compact .ram-host-line{margin-top:4px!important;font-size:9px!important}.vm-ram-compact .ram-host-line b{font-size:9px!important}
.ram-detail-kicker{display:block!important;margin-bottom:3px!important;font-size:9px!important;font-weight:900!important;letter-spacing:.05em;color:#667085!important}
.top-vm-v48103 .top-ram{width:165px!important}.table-vm .col-ram{width:165px!important}.abuse-v48103-table .c-ram{width:175px!important}.abuse-v48103-table .vm-ram-block{min-width:145px!important}.abuse-v48103-table{min-width:1700px!important}
html[data-theme=dark] .ram-sort-menu>summary{color:#94a3b8}html[data-theme=dark] .ram-sort-menu>summary:hover,html[data-theme=dark] .ram-sort-menu[open]>summary{color:#bfdbfe;background:#172554;border-color:#1d4ed8}html[data-theme=dark] .ram-sort-options{background:#111827;border-color:#334155;box-shadow:0 12px 30px rgba(0,0,0,.45)}html[data-theme=dark] .ram-sort-option .sort-link:hover{background:#1f2937}html[data-theme=dark] .ram-detail-kicker{color:#94a3b8!important}
</style>
"""
_page_v48104_base = page


def page(title, content):
    response = _page_v48104_base(title, content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace("</head>", V48104_UI_CSS + "</head>", 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.10.4 compact RAM UI layer")
    return response


# ---------------------------------------------------------------------------
# v48.10.6 visual polish, balanced tables, reusable CPU meters, dedicated login
# ---------------------------------------------------------------------------
V48105_VERSION = "48.10.5"


def _v48105_cpu_usage_block(core_percent, full_percent, vcpu=0, progress_text="", compact=False):
    """Render one consistent VM CPU cell.

    CORE is host-style aggregate usage where 100% equals one fully used vCPU.
    FULL is normalized against the VM's assigned vCPU count and drives the bar.
    """
    core_value = max(0.0, safe_float(core_percent, 0.0))
    full_value = max(0.0, safe_float(full_percent, 0.0))
    level = _v48102_cpu_level(full_value)
    bar = min(100.0, full_value)
    extra = f" · {escape(progress_text)}" if progress_text else ""
    compact_class = " cpu-usage-compact" if compact else ""
    vcpu_line = f'<span class="cpu-vcpu-line">{max(0, safe_int(vcpu, 0))} vCPU</span>' if vcpu is not None else ""
    return (
        f'<div class="cpu-usage-block cpu-{level}{compact_class}">'
        f'<b class="cpu-core-value">{core_value:.1f}%</b>'
        f'<small class="cpu-full-value">{full_value:.1f}% full{extra}</small>'
        f'<span class="cpu-meter"><i style="width:{bar:.1f}%"></i></span>'
        f'{vcpu_line}'
        f'</div>'
    )


# Node detail VM tables now use the same CPU block as /top.
def interface_table(title, bridge, node, rows, period, q="", sort_by="total", order="desc", vm_status="active"):
    body = ""
    for row in rows:
        (
            iface, vm_uuid, rx, tx, total, rx_packets, tx_packets, packets, drops, errors,
            avg_mbps, peak_mbps, avg_pps, peak_pps, sample_count, sample_expected,
            sample_max_gap_seconds, seconds_over_pps, seconds_over_mbps, sample_quality_rank,
            cpu_percent, vcpu_current, core_cpu_percent, ram_rss_kib, ram_current_kib,
            disk_read_bps, disk_write_bps, row_vm_status, last_push, vm_last_seen,
            interval_seconds, ram_available_kib, ram_unused_kib, ram_usable_kib,
        ) = row
        row_at = (request.args.get("at") or "").strip()
        href = url_for("vm_page", node=node, vm_uuid=vm_uuid, bridge=bridge, iface=iface, period=period, **({"at": row_at} if row_at else {}))
        href_e = escape(href, quote=True)
        live = vm_live_status(vm_last_seen)
        row_status = clean_vm_status(row_vm_status)
        row_cls = "clickable stale-row" if (live == "stale" or row_status != "active") else "clickable"
        state_html = vm_status_badge(row_status, live)
        vm_uuid_e = escape(vm_uuid)
        quality = network_quality_from_rank(sample_quality_rank)
        sample_html = network_sample_badge(quality, sample_count, sample_expected, sample_max_gap_seconds)
        ram_html = fmt_vm_ram_block(ram_current_kib, ram_rss_kib, ram_available_kib, ram_unused_kib, ram_usable_kib, compact=True)
        cpu_html = _v48105_cpu_usage_block(core_cpu_percent, cpu_percent, vcpu_current, compact=True)
        body += f"""
        <tr class="{row_cls}" onclick="if (!event.target.closest('a, button, input, select, textarea, label, form')) window.location='{href_e}'">
          <td>{state_html}</td><td class="mono"><a href="{href_e}"><b>{escape(iface)}</b></a></td><td class="mono"><span class="uuid-cell"><a href="{href_e}" title="{vm_uuid_e}">{vm_uuid_e}</a><button type="button" class="copy-btn" data-copy="{vm_uuid_e}" title="Copy UUID">⧉</button></span></td>
          <td class="num">{human(rx)}</td><td class="num">{human(tx)}</td><td class="num"><b>{human(total)}</b></td><td class="num">{float(avg_mbps or 0):.2f}</td><td class="num"><b>{float(peak_mbps or 0):.2f}</b></td><td class="num">{fmt_pps_value(avg_pps)}</td><td class="num"><b>{fmt_pps_value(peak_pps)}</b></td><td class="num sample-cell">{sample_html}<small class="metric-subline">{int(seconds_over_pps or 0)}s PPS · {int(seconds_over_mbps or 0)}s Mbps</small></td>
          <td class="num cpu-polished-cell">{cpu_html}</td><td class="num">{int(vcpu_current or 0)}</td><td class="num ram-cell">{ram_html}</td><td class="num">{human_rate(disk_read_bps)}</td><td class="num">{human_rate(disk_write_bps)}</td><td class="num">{int(drops or 0)}</td><td class="num">{int(errors or 0)}</td>
        </tr>"""
    if not body:
        body = '<tr><td colspan="18" class="empty">No data in this selected snapshot</td></tr>'
    hs = {
        "rx": sort_header("RX","rx",node,period,q,sort_by,order,vm_status),
        "tx": sort_header("TX","tx",node,period,q,sort_by,order,vm_status),
        "total": sort_header("TOTAL","total",node,period,q,sort_by,order,vm_status),
        "mbps": sort_header("AVG Mbps","mbps",node,period,q,sort_by,order,vm_status),
        "peakmbps": sort_header("PEAK Mbps","peakmbps",node,period,q,sort_by,order,vm_status),
        "pps": sort_header("AVG PPS","pps",node,period,q,sort_by,order,vm_status),
        "peakpps": sort_header("PEAK PPS","peakpps",node,period,q,sort_by,order,vm_status),
        "sample": sort_header("SAMPLE","sample",node,period,q,sort_by,order,vm_status),
        "cpu": sort_header("CPU Core%","cpu",node,period,q,sort_by,order,vm_status),
        "vcpu": sort_header("vCPU","vcpu",node,period,q,sort_by,order,vm_status),
        "diskr": sort_header("DISK R/s","diskr",node,period,q,sort_by,order,vm_status),
        "diskw": sort_header("DISK W/s","diskw",node,period,q,sort_by,order,vm_status),
        "drops": sort_header("DROPS","drops",node,period,q,sort_by,order,vm_status),
        "errors": sort_header("ERR","errors",node,period,q,sort_by,order,vm_status),
    }
    ram_header = _v48104_ram_sort_header(
        sort_header("RAM","ram",node,period,q,sort_by,order,vm_status),
        [
            sort_header("Guest %","ram",node,period,q,sort_by,order,vm_status),
            sort_header("Used GiB","ramused",node,period,q,sort_by,order,vm_status),
            sort_header("Host RSS","ramrss",node,period,q,sort_by,order,vm_status),
            sort_header("Assigned","ramassigned",node,period,q,sort_by,order,vm_status),
        ],
        sort_by,
        order,
    )
    return f"""
    <div class="card vm-table-card"><div class="table-title-row"><h3>{escape(title)}</h3><div class="count-badges"><span>VM rows <b>{len(rows)}</b></span><span>Snapshot <b>exact</b></span></div></div><div class="table-wrap"><table class="table-vm table-vm-polished"><colgroup><col class="col-state"><col class="col-iface"><col class="col-uuid"><col class="col-rx"><col class="col-tx"><col class="col-total"><col class="col-mbps"><col class="col-peakmbps"><col class="col-pps"><col class="col-peakpps"><col class="col-sample"><col class="col-cpu"><col class="col-vcpu"><col class="col-ram"><col class="col-diskr"><col class="col-diskw"><col class="col-drops"><col class="col-errors"></colgroup>
      <thead><tr><th>STATE</th><th>INTERFACE</th><th>VM UUID</th><th class="num-head">{hs['rx']}</th><th class="num-head">{hs['tx']}</th><th class="num-head">{hs['total']}</th><th class="num-head">{hs['mbps']}</th><th class="num-head">{hs['peakmbps']}</th><th class="num-head">{hs['pps']}</th><th class="num-head">{hs['peakpps']}</th><th class="num-head">{hs['sample']}</th><th class="num-head">{hs['cpu']}</th><th class="num-head">{hs['vcpu']}</th><th class="num-head ram-compact-sort-head">{ram_header}</th><th class="num-head">{hs['diskr']}</th><th class="num-head">{hs['diskw']}</th><th class="num-head">{hs['drops']}</th><th class="num-head">{hs['errors']}</th></tr></thead><tbody>{body}</tbody></table></div>
      <div class="table-hint">CPU bar is normalized by assigned vCPU. RAM shows estimated <b>Guest Used / Assigned</b>; <b>RSS</b> remains host-side.</div>
    </div>"""


# Current Abuse receives the same CPU visual without changing abuse evaluation.
def _v48103_current_abuse_page(q,sort_by,order,limit):
    rows,total,counts,sort_by,order,cfg=_v48103_current_abuse_query(q,sort_by,order,limit)
    def h(label,key):
        next_order=reverse_order(order) if sort_by==key else "desc"; arrow=" ↓" if sort_by==key and order=="desc" else (" ↑" if sort_by==key else "")
        href=url_for("vm_abuse_page",tab="current",q=q or None,sort=key,order=next_order,limit=limit)
        return f'<a class="sort-link" href="{escape(href,quote=True)}">{escape(label)}{arrow}</a>'
    body=""
    for rank,r in enumerate(rows,1):
        labels=_abuse_flag_labels(r[4],cfg); reasons="".join(metric_pill(escape(x),"crit") for x in labels); href=url_for("vm_page",node=r[0],vm_uuid=r[1],period="5m"); ip=compact_ipv4(r[21])
        network=_v4810_metric_pair("RX AVG",f"{safe_float(r[22],0):.2f} Mbps","TX AVG",f"{safe_float(r[23],0):.2f} Mbps",_v48102_minutes_progress(r[28],cfg["network_mbps_required_cycles"]),_v48102_minutes_progress(r[29],cfg["network_mbps_required_cycles"]))
        pps_sync="synced" if safe_int(r[30],0) else "waiting"; peak=_v4810_metric_pair("RX PEAK",f"{fmt_pps_value(r[8])} PPS","TX PEAK",f"{fmt_pps_value(r[9])} PPS",f"{safe_int(r[10],0)}s high · {pps_sync}",f"{safe_int(r[11],0)}s high · {pps_sync}")
        cpu_progress=_v48102_minutes_progress(r[26],cfg["cpu_required_cycles"])+" sustained"
        cpu=_v48105_cpu_usage_block(r[13],r[12],r[14],cpu_progress,compact=True)
        ram=fmt_vm_ram_block(r[33],r[34],r[35],r[36],r[37],compact=True)
        disk_iops=safe_float(r[18],0)+safe_float(r[19],0); disk=_v4810_metric_pair("READ",human_rate(r[16]),"WRITE",human_rate(r[17]),f"{disk_iops:,.1f} IOPS",_v48102_minutes_progress(r[27],cfg["disk_required_cycles"]))
        timeline=f'<div class="timeline-cell"><b>{fmt_full(r[3]) if r[3] else "-"}</b><small>Started</small><span>{fmt_push(r[2])}</span><small>Last push · policy v{safe_int(r[32],0)}</small></div>'
        body+=f"""<tr><td class="rank-cell">{rank}</td><td class="identity-cell"><div class="node-line"><a href="{escape(href,quote=True)}"><b>{escape(r[0])}</b></a>{f'<span>{escape(ip)}</span>' if ip else ''}</div><div class="uuid-line"><a class="mono" href="{escape(href,quote=True)}">{escape(r[1])}</a><button type="button" class="copy-btn" data-copy="{escape(r[1],quote=True)}">⧉</button></div></td><td class="reason-cell"><div class="severity-line"><b>{safe_float(r[5],0):.2f}x</b><span>severity</span></div><div class="abuse-reasons">{reasons}</div></td><td>{network}</td><td>{peak}</td><td class="cpu-polished-cell">{cpu}</td><td class="ram-cell">{ram}</td><td>{disk}</td><td>{timeline}</td></tr>"""
    if not body: body='<tr><td colspan="9" class="empty">No VM currently satisfies the active policy revision</td></tr>'
    current_href=url_for("vm_abuse_page",tab="current",q=q or None,sort=sort_by,order=order,limit=limit); history_href=url_for("vm_abuse_page",tab="history",q=q or None,limit=limit)
    search=f"""<form class="search compact-search" method="get" action="{url_for('vm_abuse_page')}"><input type="hidden" name="tab" value="current"><input type="hidden" name="sort" value="{escape(sort_by,quote=True)}"><input type="hidden" name="order" value="{escape(order,quote=True)}"><input name="q" value="{escape(q,quote=True)}" placeholder="Search node, IPv4 or VM UUID"><select name="limit"><option value="100" {'selected' if limit==100 else ''}>100 rows</option><option value="200" {'selected' if limit==200 else ''}>200 rows</option><option value="500" {'selected' if limit==500 else ''}>500 rows</option><option value="1000" {'selected' if limit==1000 else ''}>1000 rows</option></select><button type="submit">Search</button>{f'<a class="clear" href="{url_for("vm_abuse_page",tab="current",limit=limit)}">Reset</a>' if q else ''}</form>"""
    tabs=f'<div class="abuse-tabs"><a class="active" href="{escape(current_href,quote=True)}">Current Abuse</a><a href="{escape(history_href,quote=True)}">History / Logs</a></div>'
    disk_header=f'<div>DISK</div><small>{h("READ","diskr")}<span> · </span>{h("WRITE","diskw")}</small>'
    ram_header = _v48104_ram_sort_header(h("RAM", "ram"),[h("Guest %", "ram"), h("Used GiB", "ramused"), h("Host RSS", "ramrss"), h("Assigned", "ramassigned")],sort_by,order)
    table=f"""<div class="card abuse-current-card abuse-v48102-card abuse-v48103-card abuse-v48105-card"><div class="section-head"><div><h3>Current VM Abuse</h3><p>Policy v{cfg['revision']} · exact five-minute windows · RAM is visibility only.</p></div><div class="count-badges"><span>All <b>{total}</b></span><span>PPS <b>{counts[0]}</b></span><span>AVG Mbps <b>{counts[1]}</b></span><span>CPU <b>{counts[2]}</b></span><span>Disk <b>{counts[3]}</b></span></div></div><div class="table-wrap"><table class="abuse-v490-table abuse-v48102-table abuse-v48103-table abuse-v48105-table"><colgroup><col class="c-rank"><col class="c-id"><col class="c-reason"><col class="c-network"><col class="c-peak"><col class="c-cpu"><col class="c-ram"><col class="c-disk"><col class="c-time"></colgroup><thead><tr><th>#</th><th>{h('NODE / VM','node')}</th><th>{h('REASON / SEVERITY','severity')}</th><th><div>NETWORK AVG</div><small>{h('RX Mbps','rx_mbps')} · {h('TX Mbps','tx_mbps')}</small></th><th><div>PPS PEAK / WINDOW</div><small>{h('RX PPS','rx_peak')} · {h('TX PPS','tx_peak')}</small></th><th>{h('CPU','cpu')}</th><th class="ram-compact-sort-head">{ram_header}</th><th>{disk_header}</th><th>{h('TIMELINE','last_seen')}</th></tr></thead><tbody>{body}</tbody></table></div><div class="table-hint">CPU bar is normalized by assigned vCPU. RAM is <b>visibility only</b> and never creates an automatic suspend condition.</div></div>"""
    return f"""<div class="card page-hero" data-engine="{escape(ABUSE_ENGINE_VERSION,quote=True)}"><div><span class="eyebrow">ABUSE MONITORING</span><h2>VM Abuse</h2><p>Directional network, CPU and disk signals from the current bounded state table.</p></div><div class="hero-meta"><span>Policy <b>v{cfg['revision']}</b></span><span>Refresh <b>5s partial</b></span><span>RAM <b>visibility only</b></span></div></div><div class="card abuse-toolbar">{tabs}{search}</div><details class="card policy-fold"><summary>Current policy</summary>{_public_abuse_policy(cfg)}</details>{table}"""


V48105_UI_CSS = r"""
<style id="v48105-ui-polish">
/* Contrast hierarchy: primary, secondary, muted. */
body.app-v490{--v5-text:#182230;--v5-secondary:#475467;--v5-muted:#667085;--v5-head:#344054;--v5-line:#d0d5dd;--v5-row:#f8fafc;--v5-hover:#edf6ff}
body.app-v490 .table-wrap{border-color:var(--v5-line)!important;border-radius:12px!important}
body.app-v490 .table-wrap thead th{background:#f2f5f9!important;color:var(--v5-head)!important;font-size:10.5px!important;font-weight:900!important;letter-spacing:.035em!important;line-height:1.25!important;padding:10px 10px!important;box-shadow:inset 0 -1px 0 #c8d1dc!important}
body.app-v490 .table-wrap tbody td{color:var(--v5-text)!important;font-size:12px!important;line-height:1.38!important;padding:10px 10px!important;vertical-align:middle!important;border-bottom-color:#e4e9f0!important}
body.app-v490 .table-wrap tbody tr:nth-child(even){background:var(--v5-row)!important}
body.app-v490 .table-wrap tbody tr:hover{background:var(--v5-hover)!important}
body.app-v490 .sort-link{color:#344054!important;font-weight:850!important}
body.app-v490 .sort-link:hover{color:#175cd3!important}
body.app-v490 .metric-subline,body.app-v490 .metric-pair small,body.app-v490 .metric-stack small,body.app-v490 .timeline-cell small,body.app-v490 .table-hint,body.app-v490 .admin-note{color:var(--v5-muted)!important}
body.app-v490 .metric-pair span,body.app-v490 .severity-line span{color:#59677a!important}
body.app-v490 .metric-pair b,body.app-v490 .timeline-cell b,body.app-v490 .timeline-cell span{color:var(--v5-text)!important}
body.app-v490 .node-line span{color:#526174!important;background:#eef2f6!important;border:1px solid #dce3eb!important}
body.app-v490 .uuid-line>a,body.app-v490 .mono a{color:#335ea8!important}

/* Reusable CPU visual. */
.cpu-polished-cell{overflow:visible!important}
.cpu-usage-block{min-width:112px;line-height:1.15;text-align:right}
.cpu-usage-block .cpu-core-value{display:block;font-size:14px!important;line-height:1.05!important;font-weight:900!important;color:#182230!important}
.cpu-usage-block .cpu-full-value{display:block!important;margin-top:3px!important;font-size:9.5px!important;font-weight:800!important;letter-spacing:0!important;color:#526174!important;white-space:normal!important}
.cpu-usage-block .cpu-meter{display:block;height:5px;margin-top:6px;border-radius:999px;background:#dce3eb;overflow:hidden}
.cpu-usage-block .cpu-meter i{display:block;height:100%;border-radius:inherit;background:#2e90fa}
.cpu-usage-block .cpu-vcpu-line{display:block;margin-top:4px;font-size:9px;color:#667085;font-weight:750}
.cpu-usage-compact{min-width:104px}.cpu-usage-compact .cpu-core-value{font-size:13.5px!important}.cpu-usage-compact .cpu-meter{height:4px;margin-top:5px}.cpu-usage-compact .cpu-vcpu-line{font-size:8.5px}
.cpu-busy .cpu-core-value{color:#175cd3!important}.cpu-warm .cpu-core-value,.cpu-warm .cpu-full-value{color:#b54708!important}.cpu-warm .cpu-meter i{background:#f79009!important}.cpu-hot .cpu-core-value,.cpu-hot .cpu-full-value{color:#b42318!important}.cpu-hot .cpu-meter i{background:#f04438!important}

/* Balanced widths: identifiers and multi-line metrics get room; scalar counters stay narrow. */
body.app-v490 .table-vm-polished{min-width:2000px!important;table-layout:fixed!important}
body.app-v490 .table-vm-polished col.col-state{width:86px!important}body.app-v490 .table-vm-polished col.col-iface{width:96px!important}body.app-v490 .table-vm-polished col.col-uuid{width:290px!important}
body.app-v490 .table-vm-polished col.col-rx,body.app-v490 .table-vm-polished col.col-tx{width:96px!important}body.app-v490 .table-vm-polished col.col-total{width:110px!important}
body.app-v490 .table-vm-polished col.col-mbps{width:92px!important}body.app-v490 .table-vm-polished col.col-peakmbps{width:96px!important}body.app-v490 .table-vm-polished col.col-pps{width:96px!important}body.app-v490 .table-vm-polished col.col-peakpps{width:100px!important}
body.app-v490 .table-vm-polished col.col-sample{width:145px!important}body.app-v490 .table-vm-polished col.col-cpu{width:132px!important}body.app-v490 .table-vm-polished col.col-vcpu{width:58px!important}body.app-v490 .table-vm-polished col.col-ram{width:175px!important}
body.app-v490 .table-vm-polished col.col-diskr,body.app-v490 .table-vm-polished col.col-diskw{width:105px!important}body.app-v490 .table-vm-polished col.col-drops{width:56px!important}body.app-v490 .table-vm-polished col.col-errors{width:50px!important}
body.app-v490.endpoint-top-page .table-top-vm{min-width:2350px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-rank{width:46px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-node{width:160px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-uuid{width:300px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-ifaces{width:62px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-public,body.app-v490.endpoint-top-page .table-top-vm col.top-private{width:100px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-total{width:110px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-mbps{width:92px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-peakmbps{width:96px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-pps{width:96px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-peakpps{width:100px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-sample{width:140px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-cpu{width:135px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-vcpu{width:56px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-ram{width:175px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-diskr,body.app-v490.endpoint-top-page .table-top-vm col.top-diskw{width:105px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-push{width:72px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-drops{width:56px!important}body.app-v490.endpoint-top-page .table-top-vm col.top-errors{width:50px!important}
body.app-v490.endpoint-vm-abuse-page .abuse-v48105-table{min-width:1780px!important;table-layout:fixed!important}body.app-v490.endpoint-vm-abuse-page .abuse-v48105-table .c-rank{width:44px!important}body.app-v490.endpoint-vm-abuse-page .abuse-v48105-table .c-id{width:300px!important}body.app-v490.endpoint-vm-abuse-page .abuse-v48105-table .c-reason{width:270px!important}body.app-v490.endpoint-vm-abuse-page .abuse-v48105-table .c-network{width:220px!important}body.app-v490.endpoint-vm-abuse-page .abuse-v48105-table .c-peak{width:220px!important}body.app-v490.endpoint-vm-abuse-page .abuse-v48105-table .c-cpu{width:150px!important}body.app-v490.endpoint-vm-abuse-page .abuse-v48105-table .c-ram{width:180px!important}body.app-v490.endpoint-vm-abuse-page .abuse-v48105-table .c-disk{width:215px!important}body.app-v490.endpoint-vm-abuse-page .abuse-v48105-table .c-time{width:175px!important}

/* RAM is compact but no longer washed out. */
body.app-v490 .ram-guest-value{font-weight:900!important;color:#182230!important}body.app-v490 .ram-guest-label{color:#475467!important;font-weight:800!important}body.app-v490 .ram-host-line{color:#667085!important}body.app-v490 .ram-meter{background:#dce3eb!important}

html[data-theme=dark] body.app-v490{--v5-text:#edf4fc;--v5-secondary:#c3cfdd;--v5-muted:#9fb0c4;--v5-head:#d9e5f3;--v5-line:#31445e;--v5-row:rgba(255,255,255,.025);--v5-hover:#183552}
html[data-theme=dark] body.app-v490 .table-wrap{border-color:#31445e!important;background:#0f1b2c!important}
html[data-theme=dark] body.app-v490 .table-wrap thead th{background:#14263c!important;color:#d9e5f3!important;box-shadow:inset 0 -1px 0 #3a506d!important}
html[data-theme=dark] body.app-v490 .table-wrap tbody td{color:#edf4fc!important;border-bottom-color:#263a53!important}
html[data-theme=dark] body.app-v490 .table-wrap tbody tr:nth-child(even){background:rgba(255,255,255,.025)!important}
html[data-theme=dark] body.app-v490 .table-wrap tbody tr:hover{background:#183552!important}
html[data-theme=dark] body.app-v490 .sort-link{color:#cbd8e8!important}html[data-theme=dark] body.app-v490 .sort-link:hover{color:#7db4ff!important}
html[data-theme=dark] body.app-v490 .metric-subline,html[data-theme=dark] body.app-v490 .metric-pair small,html[data-theme=dark] body.app-v490 .metric-stack small,html[data-theme=dark] body.app-v490 .timeline-cell small,html[data-theme=dark] body.app-v490 .table-hint,html[data-theme=dark] body.app-v490 .admin-note{color:#9fb0c4!important}
html[data-theme=dark] body.app-v490 .metric-pair span,html[data-theme=dark] body.app-v490 .severity-line span{color:#a9b8ca!important}
html[data-theme=dark] body.app-v490 .metric-pair b,html[data-theme=dark] body.app-v490 .timeline-cell b,html[data-theme=dark] body.app-v490 .timeline-cell span{color:#edf4fc!important}
html[data-theme=dark] body.app-v490 .node-line span{color:#b6c5d7!important;background:#18283c!important;border-color:#31445e!important}
html[data-theme=dark] body.app-v490 .uuid-line>a,html[data-theme=dark] body.app-v490 .mono a{color:#7db4ff!important}
html[data-theme=dark] .cpu-usage-block .cpu-core-value{color:#f8fbff!important}html[data-theme=dark] .cpu-usage-block .cpu-full-value{color:#bdcad9!important}html[data-theme=dark] .cpu-usage-block .cpu-vcpu-line{color:#9fb0c4!important}html[data-theme=dark] .cpu-usage-block .cpu-meter{background:#2a405b!important}
html[data-theme=dark] body.app-v490 .ram-guest-value{color:#f8fbff!important}html[data-theme=dark] body.app-v490 .ram-guest-label{color:#bdcad9!important}html[data-theme=dark] body.app-v490 .ram-host-line{color:#9fb0c4!important}html[data-theme=dark] body.app-v490 .ram-meter{background:#2a405b!important}
@media(max-width:900px){body.app-v490 .table-wrap tbody td{font-size:11.5px!important;padding:9px 8px!important}.cpu-usage-block .cpu-core-value{font-size:13px!important}}
</style>
"""
_page_v48105_base = page


def page(title, content):
    response = _page_v48105_base(title, content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace("</head>", V48105_UI_CSS + "</head>", 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.10.6 UI polish layer")
    return response


def _v48105_login_document(next_url, username_value, error_html, no_users_note):
    action = url_for("dashboard_login")
    return f"""<!doctype html>
<html lang="en" data-theme="dark" data-theme-mode="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Sign in · VirtInfra Monitor</title>
<style>
*{{box-sizing:border-box}}:root{{--bg:#f4f7fb;--panel:#ffffff;--panel-2:#f8fafc;--line:#d8e0ea;--text:#172033;--muted:#66758a;--brand:#2f6fed;--brand-2:#2458c8;--shadow:0 24px 70px rgba(31,52,83,.16);--input:#fff}}html[data-theme=dark]{{--bg:#07111f;--panel:#0f1b2c;--panel-2:#122239;--line:#2b3e58;--text:#edf4fc;--muted:#9fb0c4;--brand:#4f7df3;--brand-2:#3f6de3;--shadow:0 28px 80px rgba(0,0,0,.38);--input:#0b1728}}html,body{{min-height:100%;margin:0}}body{{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:radial-gradient(circle at 12% 8%,rgba(47,111,237,.16),transparent 34%),radial-gradient(circle at 88% 92%,rgba(62,180,255,.10),transparent 35%),var(--bg);color:var(--text);display:flex;flex-direction:column}}
.login-topbar{{height:76px;display:flex;align-items:center;justify-content:space-between;padding:0 30px;border-bottom:1px solid color-mix(in srgb,var(--line) 78%,transparent);background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(14px)}}.login-brand{{display:flex;align-items:center;gap:12px;font-weight:850;letter-spacing:-.025em}}.brand-mark{{width:34px;height:34px;border-radius:10px;background:linear-gradient(145deg,var(--brand),#69a5ff);box-shadow:0 7px 20px rgba(47,111,237,.30);display:grid;place-items:center}}.brand-mark:before{{content:"";width:16px;height:13px;border:2px solid #fff;border-radius:4px;box-shadow:inset 0 -4px 0 rgba(255,255,255,.22)}}.brand-copy b,.brand-copy small{{display:block}}.brand-copy b{{font-size:15px}}.brand-copy small{{font-size:10px;color:var(--muted);font-weight:700;letter-spacing:.07em;text-transform:uppercase;margin-top:2px}}
.theme-switch{{display:flex;gap:3px;padding:4px;border:1px solid var(--line);border-radius:11px;background:var(--panel)}}.theme-switch button{{border:0;background:transparent;color:var(--muted);height:30px;padding:0 10px;border-radius:7px;font-size:11px;font-weight:800;cursor:pointer}}.theme-switch button.active{{background:var(--panel-2);color:var(--text);box-shadow:0 1px 3px rgba(15,23,42,.12)}}
.login-main{{flex:1;display:grid;place-items:center;padding:48px 20px}}.login-shell{{width:min(100%,440px)}}.login-intro{{text-align:center;margin-bottom:20px}}.login-intro h1{{font-size:28px;line-height:1.1;letter-spacing:-.045em;margin:0 0 9px}}.login-intro p{{margin:0;color:var(--muted);font-size:13px;line-height:1.55}}.login-card-pro{{background:var(--panel);border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow);padding:28px}}.login-card-pro form{{display:grid;gap:15px}}.field{{display:grid;gap:7px}}.field label{{font-size:11px;font-weight:850;color:var(--text)}}.field input{{width:100%;height:44px;border:1px solid var(--line);border-radius:10px;background:var(--input);color:var(--text);padding:0 13px;font-size:13px;outline:none;transition:border-color .15s,box-shadow .15s}}.field input:focus{{border-color:var(--brand);box-shadow:0 0 0 3px color-mix(in srgb,var(--brand) 18%,transparent)}}.password-wrap{{position:relative}}.password-wrap input{{padding-right:68px}}.password-toggle{{position:absolute;right:7px;top:7px;height:30px;border:0;border-radius:7px;background:var(--panel-2);color:var(--muted);padding:0 9px;font-size:10px;font-weight:850;cursor:pointer}}.login-submit{{height:44px;border:0;border-radius:10px;background:linear-gradient(135deg,var(--brand),var(--brand-2));color:#fff;font-size:12px;font-weight:900;cursor:pointer;box-shadow:0 8px 18px rgba(47,111,237,.25);margin-top:2px}}.login-submit:hover{{filter:brightness(1.04)}}.login-submit:active{{transform:translateY(1px)}}.login-alert{{border-radius:10px;padding:10px 12px;margin-bottom:14px;font-size:11px;line-height:1.45}}.login-alert.error{{background:#fff1f2;color:#b42318;border:1px solid #fecdd3}}html[data-theme=dark] .login-alert.error{{background:#32181d;color:#fecaca;border-color:#7f1d1d}}.login-alert.note{{background:var(--panel-2);color:var(--muted);border:1px solid var(--line)}}.login-security{{display:flex;align-items:center;justify-content:center;gap:7px;margin-top:17px;color:var(--muted);font-size:10px}}.login-security:before{{content:"";width:7px;height:7px;border-radius:50%;background:#12b76a;box-shadow:0 0 0 3px rgba(18,183,106,.12)}}.login-footer{{padding:18px 20px 24px;text-align:center;color:var(--muted);font-size:10px}}
@media(max-width:620px){{.login-topbar{{height:68px;padding:0 16px}}.brand-copy small{{display:none}}.theme-switch button{{padding:0 8px}}.login-main{{padding:34px 16px}}.login-card-pro{{padding:22px;border-radius:15px}}.login-intro h1{{font-size:24px}}}}
</style>
<script>(function(){{var m='auto';try{{m=localStorage.getItem('bw-theme-mode')||'auto'}}catch(e){{}}var h=new Date().getHours();var r=m==='auto'?((h>=18||h<6)?'dark':'light'):m;document.documentElement.setAttribute('data-theme-mode',m);document.documentElement.setAttribute('data-theme',r)}})();</script>
</head>
<body>
<header class="login-topbar"><div class="login-brand"><span class="brand-mark" aria-hidden="true"></span><span class="brand-copy"><b>VirtInfra Monitor</b><small>Operations Console</small></span></div><div class="theme-switch" role="group" aria-label="Theme mode"><button type="button" data-theme-mode="auto">Auto</button><button type="button" data-theme-mode="dark">Dark</button><button type="button" data-theme-mode="light">Light</button></div></header>
<main class="login-main"><section class="login-shell"><div class="login-intro"><h1>Welcome back</h1><p>Sign in to access infrastructure monitoring and operations.</p></div><div class="login-card-pro">{error_html}{no_users_note}<form method="post" action="{action}"><input type="hidden" name="next" value="{escape(next_url,quote=True)}"><div class="field"><label for="login-username">Username</label><input id="login-username" name="username" value="{escape(username_value)}" autocomplete="username" autofocus required></div><div class="field"><label for="login-password">Password</label><div class="password-wrap"><input id="login-password" name="password" type="password" autocomplete="current-password" required><button class="password-toggle" type="button" aria-label="Show password">Show</button></div></div><button class="login-submit" type="submit">Sign in</button></form><div class="login-security">Authorized access only</div></div></section></main><footer class="login-footer">VirtInfra Monitor · Secure operations access</footer>
<script>
function readMode(){{try{{return localStorage.getItem('bw-theme-mode')||'auto'}}catch(e){{return'auto'}}}}function resolved(m){{if(m==='dark'||m==='light')return m;var h=new Date().getHours();return(h>=18||h<6)?'dark':'light'}}function applyMode(m,p){{if(!['auto','dark','light'].includes(m))m='auto';if(p)try{{localStorage.setItem('bw-theme-mode',m)}}catch(e){{}}document.documentElement.setAttribute('data-theme-mode',m);document.documentElement.setAttribute('data-theme',resolved(m));document.querySelectorAll('[data-theme-mode]').forEach(function(b){{b.classList.toggle('active',b.dataset.themeMode===m)}})}}applyMode(readMode(),false);document.addEventListener('click',function(e){{var t=e.target.closest('[data-theme-mode]');if(t){{applyMode(t.dataset.themeMode,true);return}}var p=e.target.closest('.password-toggle');if(p){{var i=document.getElementById('login-password');var show=i.type==='password';i.type=show?'text':'password';p.textContent=show?'Hide':'Show';p.setAttribute('aria-label',show?'Hide password':'Show password')}}}});
</script>
</body></html>"""


def dashboard_login_v48105():
    next_url = safe_next_url(request.args.get("next") or request.form.get("next") or url_for("index"))
    error = ""
    if dashboard_allowed():
        return redirect(next_url)
    bootstrap_dashboard_admin_from_settings()
    if not admin_is_configured() and dashboard_user_count() == 0:
        return redirect(url_for("admin_setup"))
    username_value = clean_username(request.form.get("username") or "")
    if request.method == "POST":
        password = request.form.get("password") or ""
        user = get_dashboard_user(username_value)
        if not user:
            log_account_event("login_failed", username=username_value, realm="dashboard", detail="unknown user")
            error = "Invalid username or password."
        else:
            user_id, username, password_hash, role, is_active, created_at, updated_at, last_login = user
            role = clean_role(role)
            if not is_active:
                log_account_event("login_failed", username=username, realm="dashboard", role=role, detail="disabled user")
                error = "This user is disabled."
            elif not check_password_hash(password_hash, password):
                log_account_event("login_failed", username=username, realm="dashboard", role=role, detail="bad password")
                error = "Invalid username or password."
            else:
                session.clear()
                session["dashboard_authenticated"] = True
                session["dashboard_user_id"] = int(user_id)
                session["dashboard_username"] = username
                session["dashboard_role"] = role
                if role == "admin":
                    session["admin_authenticated"] = True
                    session["admin_username"] = username
                session["csrf_token"] = secrets.token_urlsafe(32)
                update_dashboard_user_login(user_id)
                log_account_event("login_success", username=username, realm="dashboard", role=role)
                return redirect(next_url)
    error_html = f'<div class="login-alert error">{escape(error)}</div>' if error else ""
    no_users_note = '<div class="login-alert note">No dashboard users exist yet. Sign in to Admin setup first and create an account.</div>' if dashboard_user_count() == 0 else ""
    return Response(_v48105_login_document(next_url, username_value, error_html, no_users_note), mimetype="text/html")


app.view_functions["dashboard_login"] = dashboard_login_v48105


# ---------------------------------------------------------------------------
# v48.10.6 admin login parity + darker chips/inputs + robust password toggles
# ---------------------------------------------------------------------------
V48106_VERSION = "48.10.6"
V48106_UI_CSS = r"""
<style id="v48106-login-darkfix-ui">

/* Neutral information chips in dark mode */
html[data-theme=dark] body.app-v490 .count-badges > span,
html[data-theme=dark] body.app-v490 .overview-meta > span,
html[data-theme=dark] body.app-v490 .hero-meta > span,
html[data-theme=dark] body.app-v490 .info-strip > span {
  background:#10243a!important;
  border:1px solid #31577e!important;
  color:#c9d9ea!important;
  box-shadow:0 1px 2px rgba(0,0,0,.25)!important;
}

/* Main value inside each chip */
html[data-theme=dark] body.app-v490 .count-badges > span > b,
html[data-theme=dark] body.app-v490 .overview-meta > span > b,
html[data-theme=dark] body.app-v490 .hero-meta > span > b,
html[data-theme=dark] body.app-v490 .info-strip > span > b {
  color:#ffffff!important;
}

/* Dark input fields */
html[data-theme=dark] body.app-v490 input,
html[data-theme=dark] body.app-v490 select,
html[data-theme=dark] body.app-v490 textarea,
html[data-theme=dark] body.app-v490 .search input,
html[data-theme=dark] body.app-v490 .search select,
html[data-theme=dark] body.app-v490 .custom-time-form input {
  background:#07111b!important;
  border-color:#2b4260!important;
  color:#edf4fc!important;
}

html[data-theme=dark] body.app-v490 input::placeholder,
html[data-theme=dark] body.app-v490 textarea::placeholder {
  color:#8ea2ba!important;
}

</style>
"""
_page_v48106_base = page

def page(title, content):
    response = _page_v48106_base(title, content)
    try:
        html = response.get_data(as_text=True)
        html = html.replace("</head>", V48106_UI_CSS + "</head>", 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v48.10.6 UI darkfix layer")
    return response


def _v48106_password_field(field_id, field_name, label, autocomplete, required=True):
    return (
        f'<div class="field"><label for="{escape(field_id, quote=True)}">{escape(label)}</label>'
        f'<div class="password-wrap"><input id="{escape(field_id, quote=True)}" '
        f'name="{escape(field_name, quote=True)}" type="password" autocomplete="{escape(autocomplete, quote=True)}"'
        f'{" required" if required else ""}>'
        f'<button class="password-toggle" type="button" data-target="{escape(field_id, quote=True)}" '
        f'aria-label="Show password">Show</button></div></div>'
    )


def _v48106_login_document(*, action, title, subtitle, username_value, error_html="", note_html="", next_url="", button_label="Sign in", extra_fields=""):
    return f"""<!doctype html>
<html lang="en" data-theme="dark" data-theme-mode="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{escape(title)} · VirtInfra Monitor</title>
<style>
*{{box-sizing:border-box}}:root{{--bg:#f4f7fb;--panel:#ffffff;--panel-2:#f5f7fb;--line:#d8e0ea;--text:#172033;--muted:#66758a;--brand:#2f6fed;--brand-2:#2458c8;--shadow:0 24px 70px rgba(31,52,83,.16);--input:#ffffff;--input-2:#f8fbff}}html[data-theme=dark]{{--bg:#050c16;--panel:#0d1726;--panel-2:#111e30;--line:#24364f;--text:#edf4fc;--muted:#9fb0c4;--brand:#4f7df3;--brand-2:#3f6de3;--shadow:0 28px 80px rgba(0,0,0,.42);--input:#050d18;--input-2:#0a1421}}html,body{{min-height:100%;margin:0}}body{{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:radial-gradient(circle at 12% 8%,rgba(47,111,237,.15),transparent 34%),radial-gradient(circle at 88% 92%,rgba(62,180,255,.08),transparent 35%),var(--bg);color:var(--text);display:flex;flex-direction:column}}
.login-topbar{{height:76px;display:flex;align-items:center;justify-content:space-between;padding:0 30px;border-bottom:1px solid color-mix(in srgb,var(--line) 82%,transparent);background:color-mix(in srgb,var(--bg) 90%,transparent);backdrop-filter:blur(14px)}}.login-brand{{display:flex;align-items:center;gap:12px;font-weight:850;letter-spacing:-.025em}}.brand-mark{{width:34px;height:34px;border-radius:10px;background:linear-gradient(145deg,var(--brand),#69a5ff);box-shadow:0 7px 20px rgba(47,111,237,.30);display:grid;place-items:center}}.brand-mark:before{{content:"";width:16px;height:13px;border:2px solid #fff;border-radius:4px;box-shadow:inset 0 -4px 0 rgba(255,255,255,.22)}}.brand-copy b,.brand-copy small{{display:block}}.brand-copy b{{font-size:15px}}.brand-copy small{{font-size:10px;color:var(--muted);font-weight:700;letter-spacing:.07em;text-transform:uppercase;margin-top:2px}}
.theme-switch{{display:flex;gap:3px;padding:4px;border:1px solid var(--line);border-radius:11px;background:var(--panel)}}.theme-switch button{{border:0;background:transparent;color:var(--muted);height:30px;padding:0 10px;border-radius:7px;font-size:11px;font-weight:800;cursor:pointer}}.theme-switch button.active{{background:var(--panel-2);color:var(--text);box-shadow:0 1px 3px rgba(15,23,42,.12)}}
.login-main{{flex:1;display:grid;place-items:center;padding:48px 20px}}.login-shell{{width:min(100%,448px)}}.login-intro{{text-align:center;margin-bottom:20px}}.login-intro h1{{font-size:28px;line-height:1.1;letter-spacing:-.045em;margin:0 0 9px}}.login-intro p{{margin:0;color:var(--muted);font-size:13px;line-height:1.55}}.login-card-pro{{background:var(--panel);border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow);padding:28px}}.login-card-pro form{{display:grid;gap:15px}}.field{{display:grid;gap:7px}}.field label{{font-size:11px;font-weight:850;color:var(--text)}}.field input{{width:100%;height:44px;border:1px solid var(--line);border-radius:10px;background:var(--input);color:var(--text);padding:0 13px;font-size:13px;outline:none;transition:border-color .15s,box-shadow .15s}}.field input:focus{{border-color:var(--brand);box-shadow:0 0 0 3px color-mix(in srgb,var(--brand) 18%,transparent)}}.field input::placeholder{{color:var(--muted)}}.password-wrap{{position:relative}}.password-wrap input{{padding-right:72px}}.password-toggle{{position:absolute;right:7px;top:7px;height:30px;border:1px solid var(--line);border-radius:7px;background:var(--input-2);color:var(--muted);padding:0 10px;font-size:10px;font-weight:850;cursor:pointer}}.password-toggle:hover{{color:var(--text);border-color:color-mix(in srgb,var(--brand) 48%,var(--line))}}.login-submit{{height:44px;border:0;border-radius:10px;background:linear-gradient(135deg,var(--brand),var(--brand-2));color:#fff;font-size:12px;font-weight:900;cursor:pointer;box-shadow:0 8px 18px rgba(47,111,237,.25);margin-top:2px}}.login-submit:hover{{filter:brightness(1.04)}}.login-submit:active{{transform:translateY(1px)}}.login-alert{{border-radius:10px;padding:10px 12px;margin-bottom:14px;font-size:11px;line-height:1.45}}.login-alert.error{{background:#fff1f2;color:#b42318;border:1px solid #fecdd3}}html[data-theme=dark] .login-alert.error{{background:#32181d;color:#fecaca;border-color:#7f1d1d}}.login-alert.note{{background:var(--panel-2);color:var(--muted);border:1px solid var(--line)}}.login-security{{display:flex;align-items:center;justify-content:center;gap:7px;margin-top:17px;color:var(--muted);font-size:10px}}.login-security:before{{content:"";width:7px;height:7px;border-radius:50%;background:#12b76a;box-shadow:0 0 0 3px rgba(18,183,106,.12)}}.login-footer{{padding:18px 20px 24px;text-align:center;color:var(--muted);font-size:10px}}
@media(max-width:620px){{.login-topbar{{height:68px;padding:0 16px}}.brand-copy small{{display:none}}.theme-switch button{{padding:0 8px}}.login-main{{padding:34px 16px}}.login-card-pro{{padding:22px;border-radius:15px}}.login-intro h1{{font-size:24px}}}}
</style>
<script>(function(){{var m='auto';try{{m=localStorage.getItem('bw-theme-mode')||'auto'}}catch(e){{}}var h=new Date().getHours();var r=m==='auto'?((h>=18||h<6)?'dark':'light'):m;document.documentElement.setAttribute('data-theme-mode',m);document.documentElement.setAttribute('data-theme',r)}})();</script>
</head>
<body>
<header class="login-topbar"><div class="login-brand"><span class="brand-mark" aria-hidden="true"></span><span class="brand-copy"><b>VirtInfra Monitor</b><small>Operations Console</small></span></div><div class="theme-switch" role="group" aria-label="Theme mode"><button type="button" data-theme-mode="auto">Auto</button><button type="button" data-theme-mode="dark">Dark</button><button type="button" data-theme-mode="light">Light</button></div></header>
<main class="login-main"><section class="login-shell"><div class="login-intro"><h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div><div class="login-card-pro">{error_html}{note_html}<form method="post" action="{action}"><input type="hidden" name="next" value="{escape(next_url,quote=True)}"><div class="field"><label for="login-username">Username</label><input id="login-username" name="username" value="{escape(username_value)}" autocomplete="username" autofocus required></div>{extra_fields}<button class="login-submit" type="submit">{escape(button_label)}</button></form><div class="login-security">Authorized access only</div></div></section></main><footer class="login-footer">VirtInfra Monitor · Secure operations access</footer>
<script>
function readMode(){{try{{return localStorage.getItem('bw-theme-mode')||'auto'}}catch(e){{return'auto'}}}}
function resolved(m){{if(m==='dark'||m==='light')return m;var h=new Date().getHours();return(h>=18||h<6)?'dark':'light'}}
function applyMode(m,p){{if(!['auto','dark','light'].includes(m))m='auto';if(p)try{{localStorage.setItem('bw-theme-mode',m)}}catch(e){{}}document.documentElement.setAttribute('data-theme-mode',m);document.documentElement.setAttribute('data-theme',resolved(m));document.querySelectorAll('[data-theme-mode]').forEach(function(b){{b.classList.toggle('active',b.dataset.themeMode===m)}})}}
function bindPasswordToggles(){{document.querySelectorAll('.password-toggle').forEach(function(btn){{if(btn.dataset.bwToggleBound==='1')return;btn.dataset.bwToggleBound='1';btn.addEventListener('click',function(ev){{ev.preventDefault();var id=this.getAttribute('data-target');var input=id?document.getElementById(id):null;if(!input)return;var show=input.type==='password';input.type=show?'text':'password';this.textContent=show?'Hide':'Show';this.setAttribute('aria-label',show?'Hide password':'Show password')}})}})}}
applyMode(readMode(),false);document.addEventListener('click',function(e){{var t=e.target.closest('[data-theme-mode]');if(t){{applyMode(t.dataset.themeMode,true)}}}});document.addEventListener('DOMContentLoaded',bindPasswordToggles);bindPasswordToggles();
</script>
</body></html>"""


def dashboard_login_v48106():
    next_url = safe_next_url(request.args.get("next") or request.form.get("next") or url_for("index"))
    error = ""
    if dashboard_allowed():
        return redirect(next_url)
    bootstrap_dashboard_admin_from_settings()
    if not admin_is_configured() and dashboard_user_count() == 0:
        return redirect(url_for("admin_setup"))
    username_value = clean_username(request.form.get("username") or "")
    if request.method == "POST":
        password = request.form.get("password") or ""
        user = get_dashboard_user(username_value)
        if not user:
            log_account_event("login_failed", username=username_value, realm="dashboard", detail="unknown user")
            error = "Invalid username or password."
        else:
            user_id, username, password_hash, role, is_active, created_at, updated_at, last_login = user
            role = clean_role(role)
            if not is_active:
                log_account_event("login_failed", username=username, realm="dashboard", role=role, detail="disabled user")
                error = "This user is disabled."
            elif not check_password_hash(password_hash, password):
                log_account_event("login_failed", username=username, realm="dashboard", role=role, detail="bad password")
                error = "Invalid username or password."
            else:
                session.clear()
                session["dashboard_authenticated"] = True
                session["dashboard_user_id"] = int(user_id)
                session["dashboard_username"] = username
                session["dashboard_role"] = role
                if role == "admin":
                    session["admin_authenticated"] = True
                    session["admin_username"] = username
                session["csrf_token"] = secrets.token_urlsafe(32)
                update_dashboard_user_login(user_id)
                log_account_event("login_success", username=username, realm="dashboard", role=role)
                return redirect(next_url)
    error_html = f'<div class="login-alert error">{escape(error)}</div>' if error else ""
    note_html = '<div class="login-alert note">No dashboard users exist yet. Sign in to Admin setup first and create an account.</div>' if dashboard_user_count() == 0 else ""
    extra = _v48106_password_field("login-password", "password", "Password", "current-password")
    return Response(_v48106_login_document(action=url_for("dashboard_login"), title="Welcome back", subtitle="Sign in to access infrastructure monitoring and operations.", username_value=username_value, error_html=error_html, note_html=note_html, next_url=next_url, button_label="Sign in", extra_fields=extra), mimetype="text/html")


def admin_login_v48106():
    next_url = safe_next_url(request.args.get("next") or request.form.get("next") or url_for("admin_page"))
    error = ""
    bootstrap_dashboard_admin_from_settings()
    if emergency_admin_needed():
        return redirect(url_for("admin_setup"))
    if admin_allowed():
        return redirect(next_url)
    admin_username = get_admin_username()
    form_username = admin_username
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        form_username = username or admin_username
        password = request.form.get("password") or ""
        user = get_dashboard_user(username)
        if user:
            user_id, user_name, user_hash, role, is_active, _created_at, _updated_at, _last_login = user
            role = clean_role(role)
            if role != "admin" or not is_active:
                log_account_event("login_failed", username=username, realm="admin", role=role, detail="dashboard admin user disabled or invalid")
                error = "This user is disabled or does not have admin role."
            elif not check_password_hash(user_hash, password):
                log_account_event("login_failed", username=username, realm="admin", role=role, detail="bad password")
                error = "Invalid username or password."
            else:
                session.clear(); session["dashboard_authenticated"] = True; session["dashboard_user_id"] = int(user_id); session["dashboard_username"] = user_name; session["dashboard_role"] = "admin"; session["admin_authenticated"] = True; session["admin_username"] = user_name; session["csrf_token"] = secrets.token_urlsafe(32); update_dashboard_user_login(user_id); log_account_event("login_success", username=user_name, realm="admin", role="admin")
                return redirect(next_url)
        else:
            legacy_admin_username = get_admin_username(); legacy_admin_hash = get_admin_password_hash()
            if username == legacy_admin_username and legacy_admin_hash and check_password_hash(legacy_admin_hash, password):
                upsert_dashboard_user(username, password, role="admin", is_active=1)
                converted = get_dashboard_user(username)
                if converted:
                    session.clear(); session["dashboard_authenticated"] = True; session["dashboard_user_id"] = int(converted[0]); session["dashboard_username"] = username; session["dashboard_role"] = "admin"; session["admin_authenticated"] = True; session["admin_username"] = username; session["csrf_token"] = secrets.token_urlsafe(32); update_dashboard_user_login(converted[0]); log_account_event("login_success", username=username, realm="admin", role="admin", detail="legacy admin converted")
                    return redirect(next_url)
            log_account_event("login_failed", username=username, realm="admin", role="admin", detail="unknown admin user")
            error = "Invalid username or password."
    error_html = f'<div class="login-alert error">{escape(error)}</div>' if error else ""
    note_html = '<div class="login-alert note">Administrator access only. Active dashboard users with role = admin can sign in here.</div>'
    extra = _v48106_password_field("admin-login-password", "password", "Password", "current-password")
    return Response(_v48106_login_document(action=url_for("admin_login"), title="Administrator access", subtitle="Sign in to manage policy, queue, users and system settings.", username_value=form_username, error_html=error_html, note_html=note_html, next_url=next_url, button_label="Sign in", extra_fields=extra), mimetype="text/html")


def admin_setup_v48106():
    bootstrap_dashboard_admin_from_settings()
    emergency_mode = emergency_admin_needed()
    if admin_is_configured() and not emergency_mode and not admin_allowed():
        return redirect(url_for("admin_login"))
    if admin_is_configured() and not emergency_mode and admin_allowed():
        return redirect(url_for("admin_page"))
    error = ""
    username_value = (request.form.get("username") or "admin").strip() or "admin"
    if request.method == "POST":
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if len(username_value) < 3:
            error = "Username must be at least 3 characters."
        elif len(password) < 10:
            error = "Password must be at least 10 characters."
        elif password != confirm:
            error = "Password confirmation does not match."
        else:
            set_admin_credentials(username_value, password)
            created_user = get_dashboard_user(username_value)
            session.clear(); session["dashboard_authenticated"] = True
            if created_user:
                session["dashboard_user_id"] = int(created_user[0])
            session["dashboard_username"] = username_value; session["dashboard_role"] = "admin"; session["admin_authenticated"] = True; session["admin_username"] = username_value; session["csrf_token"] = secrets.token_urlsafe(32)
            log_account_event("setup_admin", username=username_value, realm="admin", role="admin")
            return redirect(url_for("admin_page"))
    error_html = f'<div class="login-alert error">{escape(error)}</div>' if error else ""
    note_text = 'No enabled admin user exists. Create a new admin here to recover access.' if emergency_mode else 'This setup page is available only while no admin password is configured. The password hash is stored in PostgreSQL.'
    note_html = f'<div class="login-alert note">{escape(note_text)}</div>'
    extra = _v48106_password_field("admin-setup-password", "password", "Password", "new-password") + _v48106_password_field("admin-setup-confirm", "confirm", "Confirm password", "new-password")
    title = 'Emergency Admin Setup' if emergency_mode else 'Initial Admin Setup'
    subtitle = 'Create the first administrator account for the operations console.' if not emergency_mode else 'Recover administrator access by creating a new enabled admin account.'
    return Response(_v48106_login_document(action=url_for("admin_setup"), title=title, subtitle=subtitle, username_value=username_value, error_html=error_html, note_html=note_html, next_url="", button_label="Create admin account", extra_fields=extra), mimetype="text/html")

app.view_functions["dashboard_login"] = dashboard_login_v48106
app.view_functions["admin_login"] = admin_login_v48106
app.view_functions["admin_setup"] = admin_setup_v48106


# ---------------------------------------------------------------------------
