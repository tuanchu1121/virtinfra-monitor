def page(title, content):
    user_html = ""
    if dashboard_allowed():
        username = escape(dashboard_username() or "user")
        role = escape(dashboard_role() or "viewer")
        # Do not expose the admin route in the shared dashboard header.
        # Admins can still open /admin directly; viewers do not see any admin path.
        user_html = f'<div class="user-bar"><span>Signed in as <b>{username}</b> ({role})</span><a href="{url_for("dashboard_logout")}">Logout</a></div>'
    else:
        user_html = f'<div class="user-bar"><a href="{url_for("dashboard_login")}">Login</a></div>'

    return Response(f"""
    <!doctype html>
    <html>
    <head>
        <title>{escape(title)}</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <script>
        (function() {{
            var mode = 'auto';
            try {{ mode = localStorage.getItem('bw-theme-mode') || 'auto'; }} catch (e) {{}}
            if (mode !== 'dark' && mode !== 'light' && mode !== 'auto') mode = 'auto';
            var hour = new Date().getHours();
            var resolved = mode === 'auto' ? ((hour >= 18 || hour < 6) ? 'dark' : 'light') : mode;
            document.documentElement.setAttribute('data-theme', resolved);
            document.documentElement.setAttribute('data-theme-mode', mode);
        }})();
        </script>
        <style>
            body {{
                margin: 0;
                background: #f3f5f7;
                font-family: Arial, sans-serif;
                color: #111827;
            }}
            header {{
                background: #111827;
                color: white;
                padding: 18px 30px;
            }}
            header h2 {{ margin: 0; }}
            .brand {{ color: #ffffff; margin-right: 0; text-decoration: none; }}
            .brand:hover {{ color: #dbeafe; }}
            .wrap {{
                padding: 24px 30px;
                transition: opacity .12s ease;
            }}
            html.bw-nav-loading .wrap {{
                opacity: .55;
                pointer-events: none;
            }}
            .card {{
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                padding: 18px;
                margin-bottom: 22px;
                box-shadow: 0 1px 2px rgba(0,0,0,.04);
                overflow-x: auto;
            }}
            .top-card {{ overflow-x: visible; }}
            .top-grid {{
                display: grid;
                grid-template-columns: repeat(3, minmax(220px, 1fr));
                gap: 14px;
                margin-bottom: 14px;
            }}
            .label {{
                color: #6b7280;
                font-size: 12px;
                text-transform: uppercase;
                letter-spacing: .04em;
                margin-bottom: 4px;
            }}
            .value {{
                font-size: 16px;
                font-weight: bold;
            }}
            .arrow {{ color: #6b7280; padding: 0 6px; }}
            .period-label {{ margin-top: 10px; }}
            table {{
                width: 100%;
                border-collapse: collapse;
                font-size: 14px;
            }}
            th {{
                text-align: left;
                background: #f9fafb;
                border-bottom: 1px solid #e5e7eb;
                padding: 10px;
            }}
            td {{
                border-bottom: 1px solid #eee;
                padding: 9px 10px;
                white-space: nowrap;
            }}
            tr:hover {{ background: #f9fafb; }}
            a {{
                color: #2563eb;
                text-decoration: none;
                margin-right: 10px;
            }}
            .sort-link {{
                color: #111827;
                font-weight: 800;
                margin-right: 0;
                display: inline-block;
            }}
            .sort-link:hover {{ color: #2563eb; }}

            /* Stable alignment for the 14-column VM tables. */
            .table-vm {{
                min-width: 1580px;
                table-layout: fixed;
            }}
            .table-vm col.col-state {{ width: 92px; }}
            .table-vm col.col-iface {{ width: 115px; }}
            .table-vm col.col-uuid {{ width: 300px; }}
            .table-vm col.col-rx,
            .table-vm col.col-tx {{ width: 105px; }}
            .table-vm col.col-total {{ width: 115px; }}
            .table-vm col.col-pps {{ width: 100px; }}
            .table-vm col.col-drops {{ width: 78px; }}
            .table-vm col.col-errors {{ width: 65px; }}
            .table-vm col.col-cpu {{ width: 92px; }}
            .table-vm col.col-vcpu {{ width: 72px; }}
            .table-vm col.col-ram {{ width: 185px; }}
            .table-vm col.col-diskr,
            .table-vm col.col-diskw {{ width: 120px; }}
            .table-vm th,
            .table-vm td {{
                vertical-align: middle;
                overflow: hidden;
                text-overflow: ellipsis;
            }}
            .table-vm .num,
            .table-vm .num-head {{
                text-align: right;
                font-variant-numeric: tabular-nums;
            }}
            .table-vm .num-head .sort-link {{
                width: 100%;
                text-align: right;
            }}

            /* Stable alignment for the 18-column Top VM exact-snapshot table. */
            .table-top-vm {{
                min-width: 2020px;
                table-layout: fixed;
            }}
            .table-top-vm col.top-rank {{ width: 48px; }}
            .table-top-vm col.top-node {{ width: 155px; }}
            .table-top-vm col.top-uuid {{ width: 330px; }}
            .table-top-vm col.top-ifaces {{ width: 72px; }}
            .table-top-vm col.top-public,
            .table-top-vm col.top-private,
            .table-top-vm col.top-rx,
            .table-top-vm col.top-tx {{ width: 105px; }}
            .table-top-vm col.top-total {{ width: 115px; }}
            .table-top-vm col.top-pps {{ width: 95px; }}
            .table-top-vm col.top-drops {{ width: 78px; }}
            .table-top-vm col.top-errors {{ width: 65px; }}
            .table-top-vm col.top-cpu {{ width: 105px; }}
            .table-top-vm col.top-vcpu {{ width: 72px; }}
            .table-top-vm col.top-ram {{ width: 185px; }}
            .table-top-vm col.top-diskr,
            .table-top-vm col.top-diskw {{ width: 120px; }}
            .table-top-vm col.top-push {{ width: 82px; }}
            .table-top-vm th,
            .table-top-vm td {{
                vertical-align: middle;
                overflow: hidden;
                text-overflow: ellipsis;
            }}
            .table-top-vm .num,
            .table-top-vm .num-head {{
                text-align: right;
                font-variant-numeric: tabular-nums;
            }}
            .table-top-vm .num-head .sort-link {{
                width: 100%;
                text-align: right;
            }}

            .uuid-cell {{
                display: flex;
                align-items: center;
                gap: 6px;
                min-width: 0;
            }}
            .uuid-cell a {{
                min-width: 0;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
                margin-right: 0;
            }}
            .copy-btn {{
                flex: 0 0 auto;
                width: 25px;
                height: 25px;
                padding: 0;
                border: 1px solid #d1d5db;
                border-radius: 6px;
                background: #ffffff;
                color: #374151;
                cursor: pointer;
                line-height: 23px;
                text-align: center;
                font-size: 13px;
            }}
            .copy-btn:hover {{ background: #eff6ff; border-color: #93c5fd; color: #1d4ed8; }}
            .copy-btn.copied {{ background: #dcfce7; border-color: #86efac; color: #166534; }}

            /* Node Host Health threshold colors. */
            .metric-pill {{
                display: inline-block;
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 5px 8px;
                font-variant-numeric: tabular-nums;
            }}
            .metric-ok {{ background: #dcfce7; color: #166534; border-color: #86efac; }}
            .metric-warn {{ background: #fef3c7; color: #92400e; border-color: #fcd34d; }}
            .metric-crit {{ background: #fee2e2; color: #991b1b; border-color: #fca5a5; }}
            .metric-unknown {{ background: #f3f4f6; color: #4b5563; border-color: #d1d5db; }}

            .table-hint {{
                margin-top: 10px;
                color: #6b7280;
                font-size: 12px;
            }}
            .periods a {{
                display: inline-block;
                padding: 7px 12px;
                border: 1px solid #d1d5db;
                border-radius: 7px;
                background: white;
                margin: 4px 4px 4px 0;
            }}
            .periods a.active {{
                background: #2563eb;
                color: white;
                border-color: #2563eb;
            }}
            .search {{
                display: flex;
                gap: 8px;
                align-items: center;
                margin-top: 14px;
                flex-wrap: wrap;
            }}
            .search input {{
                min-width: 280px;
                max-width: 520px;
                flex: 1;
                padding: 9px 11px;
                border: 1px solid #d1d5db;
                border-radius: 7px;
                font-size: 14px;
            }}
            .search button {{
                padding: 9px 13px;
                border: 0;
                border-radius: 7px;
                background: #111827;
                color: white;
                cursor: pointer;
            }}
            .clear {{ color: #dc2626; }}
            .grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
                gap: 12px;
            }}
            .stat {{
                background: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 12px;
            }}
            .stat b {{
                display: block;
                font-size: 20px;
                margin-top: 5px;
            }}
            .overview-card {{ padding: 14px 16px; }}
            .overview-head {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
                margin-bottom: 12px;
                flex-wrap: wrap;
            }}
            .overview-head h3 {{ margin: 0; }}
            .overview-meta {{
                display: flex;
                gap: 10px;
                align-items: center;
                flex-wrap: wrap;
                color: #374151;
                font-size: 13px;
            }}
            .overview-meta span {{
                background: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 999px;
                padding: 5px 10px;
                white-space: nowrap;
            }}
            .overview-meta b {{ font-size: 14px; }}
            .nic-map {{
                display: grid;
                grid-template-columns: repeat(2, minmax(280px, 1fr));
                gap: 10px;
                margin-bottom: 12px;
            }}
            .nic-badge {{
                display: flex;
                flex-direction: column;
                gap: 4px;
                background: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 9px;
                padding: 10px 12px;
                overflow-wrap: anywhere;
            }}
            .nic-badge small {{ color: #6b7280; white-space: normal; }}
            .nic-badge .nic-address {{ color: #111827; font-family: Consolas, monospace; }}
            @media (max-width: 900px) {{ .nic-map {{ grid-template-columns: 1fr; }} }}
            .traffic-grid {{
                display: grid;
                grid-template-columns: repeat(3, minmax(220px, 1fr));
                gap: 12px;
            }}
            .traffic-box {{
                background: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                padding: 12px 14px;
            }}
            .traffic-box-main {{ background: #f3f4f6; }}
            .traffic-title {{
                color: #6b7280;
                font-size: 13px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: .04em;
            }}
            .traffic-total {{
                margin-top: 5px;
                font-size: 23px;
                font-weight: 800;
                color: #111827;
            }}
            .traffic-split {{
                display: flex;
                gap: 14px;
                margin-top: 8px;
                color: #4b5563;
                font-size: 13px;
                flex-wrap: wrap;
            }}
            .traffic-split b {{ color: #111827; }}
            @media (max-width: 900px) {{
                .traffic-grid {{ grid-template-columns: 1fr; }}
            }}
            .mono {{
                font-family: Consolas, monospace;
                font-size: 13px;
            }}
            .node-name-cell {{
                display: flex;
                flex-direction: column;
                align-items: flex-start;
                gap: 3px;
                line-height: 1.15;
            }}
            .node-name-cell a {{ margin-right: 0; }}
            .node-ipv4 {{
                color: #6b7280;
                font-family: Consolas, monospace;
                font-size: 11px;
                font-weight: 500;
                white-space: nowrap;
            }}
            .empty {{
                text-align: center;
                color: #777;
                padding: 20px;
            }}
            .status {{ font-size: 18px; }}
            .clickable {{ cursor: pointer; }}
            .clickable td {{ transition: background .12s ease; }}
            tr.warn td {{ background: #fff7ed; }}
            .chart-card {{ overflow-x: visible; }}
            .small-chart {{ max-width: none; width: 100%; box-sizing: border-box; }}
            .vm-charts-grid, .node-charts-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(520px, 1fr));
                gap: 16px;
                align-items: start;
                margin-bottom: 22px;
            }}
            .vm-charts-grid .card, .node-charts-grid .card {{ margin-bottom: 0; }}
            .vm-raw-table {{ width: 100%; max-width: none; }}
            .node-chart-section {{ display: flex; flex-direction: column; gap: 16px; }}
            .node-chart-head, .node-chart-card, .node-chart-table {{ width: 100%; max-width: none; }}
            .node-chart-card h3, .node-chart-table h3 {{ margin-bottom: 10px; }}
            .svg-wrap {{ width: 100%; overflow-x: auto; }}
            .svg-wrap svg {{ min-width: 520px; max-width: 100%; width: 100%; height: auto; display: block; }}
            .node-svg-wrap svg {{ max-width: 100%; min-width: 520px; }}
            @media (max-width: 1100px) {{
                .vm-charts-grid, .node-charts-grid {{ grid-template-columns: 1fr; }}
            }}
            .grid-line {{ stroke: #e5e7eb; stroke-width: 1; }}
            .axis {{ stroke: #9ca3af; stroke-width: 1; }}
            .axis-label, .x-label {{ fill: #6b7280; font-size: 12px; font-family: Arial, sans-serif; }}
            .line {{ fill: none; stroke-width: 2.5; stroke-linejoin: round; stroke-linecap: round; }}
            .rx-line {{ stroke: #2563eb; }}
            .tx-line {{ stroke: #f59e0b; }}
            .public-line {{ stroke: #2563eb; }}
            .private-line {{ stroke: #f59e0b; }}
            .total-line {{ stroke: #111827; stroke-width: 3; }}
            .metric1-line {{ stroke: #2563eb; }}
            .metric2-line {{ stroke: #f59e0b; }}
            .metric3-line {{ stroke: #10b981; }}
            .metric4-line {{ stroke: #7c3aed; }}
            .dot {{ stroke: white; stroke-width: 1; }}
            .rx-dot {{ fill: #2563eb; }}
            .tx-dot {{ fill: #f59e0b; }}
            .public-dot {{ fill: #2563eb; }}
            .private-dot {{ fill: #f59e0b; }}
            .total-dot {{ fill: #111827; }}
            .metric1-dot {{ fill: #2563eb; }}
            .metric2-dot {{ fill: #f59e0b; }}
            .metric3-dot {{ fill: #10b981; }}
            .metric4-dot {{ fill: #7c3aed; }}
            .hover-zone {{ fill: transparent; pointer-events: all; }}
            .legend {{ display: flex; gap: 14px; align-items: center; margin-bottom: 8px; color: #374151; font-size: 13px; flex-wrap: wrap; }}
            .legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
            .legend i {{ display: inline-block; width: 18px; height: 3px; border-radius: 999px; }}
            .legend .rx {{ background: #2563eb; }}
            .legend .tx {{ background: #f59e0b; }}
            .legend .public {{ background: #2563eb; }}
            .legend .private {{ background: #f59e0b; }}
            .legend .total {{ background: #111827; }}
            .legend .metric1 {{ background: #2563eb; }}
            .legend .metric2 {{ background: #f59e0b; }}
            .legend .metric3 {{ background: #10b981; }}
            .legend .metric4 {{ background: #7c3aed; }}
            .chart-note {{ color: #6b7280; font-size: 12px; }}
            .stale-row {{ opacity: .52; background: #f9fafb; }}
            .vm-state {{ font-size: 11px; font-weight: 800; border-radius: 999px; padding: 4px 8px; }}
            .vm-state.active {{ color: #065f46; background: #d1fae5; }}
            .vm-state.stale {{ color: #92400e; background: #fef3c7; }}
            .btn, .btn-danger {{ border: 0; border-radius: 7px; padding: 7px 10px; cursor: pointer; font-weight: 700; margin: 2px 4px 2px 0; }}
            .btn {{ background: #e5e7eb; color: #111827; }}
            .btn-danger {{ background: #dc2626; color: white; }}
            .table-title-row {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }}
            .table-title-row h3 {{ margin-bottom: 8px; }}
            .count-badges {{ display: flex; gap: 8px; flex-wrap: wrap; }}
            .count-badges span {{ background: #f3f4f6; border: 1px solid #e5e7eb; border-radius: 999px; padding: 5px 10px; font-size: 13px; color: #374151; }}
            .bulk-bar {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 8px 0 12px 0; }}
            .bulk-bar select {{ padding: 7px 10px; border: 1px solid #d1d5db; border-radius: 7px; }}
            .bulk-bar label {{ color: #374151; font-size: 13px; }}
            .pagination {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 12px; color: #374151; font-size: 13px; }}
            .page-links {{ display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }}
            .page-link {{ display: inline-block; padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 7px; background: white; color: #111827; margin-right: 0; }}
            .page-link.active {{ background: #111827; color: white; border-color: #111827; }}
            .page-link.disabled {{ color: #9ca3af; background: #f9fafb; }}
            .page-gap {{ padding: 6px 2px; color: #6b7280; }}
            .log-check {{ width: 16px; height: 16px; }}

            .main-nav {{ display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; }}
            .main-nav a {{ color: #d1d5db; margin-right: 0; font-weight: 700; }}
            .main-nav a:hover {{ color: #ffffff; }}
            .user-bar {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 10px; color: #d1d5db; font-size: 13px; }}
            .user-bar a {{ color: #ffffff; font-weight: 700; margin-right: 0; }}
            .form-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; align-items: end; }}
            .form-grid label {{ display: block; color: #374151; font-size: 13px; font-weight: 700; margin-bottom: 4px; }}
            .form-grid input, .form-grid select {{ width: 100%; box-sizing: border-box; padding: 9px 11px; border: 1px solid #d1d5db; border-radius: 7px; font-size: 14px; }}
            .inline-form {{ display: inline-flex; gap: 6px; align-items: center; flex-wrap: wrap; margin: 2px 4px 2px 0; }}
            .inline-form input, .inline-form select {{ padding: 7px 9px; border: 1px solid #d1d5db; border-radius: 7px; max-width: 170px; }}
            .health-pill {{ font-size: 12px; font-weight: 800; border-radius: 999px; padding: 4px 9px; display: inline-block; }}
            .health-pill.healthy {{ color: #065f46; background: #d1fae5; }}
            .health-pill.warning {{ color: #92400e; background: #fef3c7; }}
            .health-pill.down {{ color: #991b1b; background: #fee2e2; }}
            .missed-cycles-link {{
                display: inline-flex;
                align-items: center;
                justify-content: center;
                min-width: 28px;
                padding: 3px 8px;
                border-radius: 999px;
                background: #eef2ff;
                border: 1px solid #c7d2fe;
                color: #3730a3;
                font-weight: 800;
                text-decoration: underline;
                text-decoration-style: dotted;
                text-underline-offset: 3px;
                cursor: pointer;
            }}
            #bw-floating-tooltip {{
                position: fixed;
                display: none;
                z-index: 100000;
                max-width: 420px;
                padding: 10px 12px;
                border-radius: 9px;
                background: #111827;
                color: #f8fafc;
                border: 1px solid #334155;
                box-shadow: 0 12px 32px rgba(0,0,0,.28);
                white-space: pre-line;
                font-size: 12px;
                line-height: 1.5;
                pointer-events: none;
            }}
            .missed-cycles-link:hover {{ background: #e0e7ff; }}
            .missed-cycles-link.current {{
                background: #fef3c7;
                border-color: #f59e0b;
                color: #92400e;
            }}
            .scope-links {{ margin-top: 12px; }}
            .scope-links a {{ display: inline-block; padding: 7px 12px; border: 1px solid #d1d5db; border-radius: 7px; background: white; margin: 4px 4px 4px 0; }}
            .scope-links a.active {{ background: #111827; color: white; border-color: #111827; }}
            .admin-note {{ color: #6b7280; font-size: 13px; margin-top: 8px; }}
            .login-card {{ max-width: 440px; margin: 40px auto; }}
            .login-card input {{ width: 100%; box-sizing: border-box; padding: 10px 12px; margin: 6px 0 12px 0; border: 1px solid #d1d5db; border-radius: 7px; font-size: 14px; }}
            .login-card button {{ width: 100%; padding: 10px 12px; border: 0; border-radius: 7px; background: #111827; color: white; font-weight: 800; cursor: pointer; }}
            .error-box {{ background: #fee2e2; color: #991b1b; border: 1px solid #fecaca; border-radius: 7px; padding: 9px 11px; margin-bottom: 12px; font-size: 13px; }}
            .success-box {{ background: #dcfce7; color: #166534; border: 1px solid #bbf7d0; border-radius: 7px; padding: 9px 11px; margin-bottom: 12px; font-size: 13px; }}
            .page-title-card {{ padding: 14px 18px; }}
            .page-title-row {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }}
            .page-title-row h3 {{ margin: 0; }}
            .breadcrumb {{ color: #6b7280; font-size: 13px; margin-bottom: 8px; }}
            h3 {{ margin-top: 0; }}
            @media (max-width: 760px) {{
                .wrap {{ padding: 16px; }}
                .top-grid {{ grid-template-columns: 1fr; }}
                .search input {{ min-width: 100%; }}
            }}
        
.vm-state.yellow{{background:#fff7cc;color:#8a5a00;border:1px solid #f1d36b}}
.vm-state.migrated{{background:#e8f0ff;color:#234ca8;border:1px solid #9bb7ff}}
.status-filter-card .periods{{margin-top:10px}}
            .header-row {{ display:flex; align-items:center; justify-content:space-between; gap:14px; flex-wrap:wrap; }}
            .theme-switch {{ display:inline-flex; gap:4px; padding:4px; background:rgba(255,255,255,.10); border:1px solid rgba(255,255,255,.18); border-radius:9px; }}
            .theme-switch button {{ border:0; border-radius:6px; padding:6px 9px; background:transparent; color:#d1d5db; font-size:12px; font-weight:800; cursor:pointer; }}
            .theme-switch button:hover {{ background:rgba(255,255,255,.12); color:#fff; }}
            .theme-switch button.active {{ background:#fff; color:#111827; }}
            .db-danger {{ border-color:#fecaca; background:#fff7f7; }}

            html[data-theme="dark"] body {{ background:#0b1220; color:#e5e7eb; }}
            html[data-theme="dark"] header {{ background:#050b16; border-bottom:1px solid #1f2937; }}
            html[data-theme="dark"] .card {{ background:#111827; border-color:#263244; box-shadow:0 1px 2px rgba(0,0,0,.35); }}
            html[data-theme="dark"] .stat,
            html[data-theme="dark"] .traffic-box,
            html[data-theme="dark"] .overview-meta span,
            html[data-theme="dark"] .count-badges span {{ background:#172033; border-color:#2d3a50; color:#d1d5db; }}
            html[data-theme="dark"] .traffic-box-main {{ background:#192235; }}
            html[data-theme="dark"] .nic-badge {{ background:#172033; border-color:#2d3a50; }}
            html[data-theme="dark"] .nic-badge .nic-address {{ color:#e5e7eb; }}
            html[data-theme="dark"] .traffic-total,
            html[data-theme="dark"] .traffic-split b,
            html[data-theme="dark"] .sort-link,
            html[data-theme="dark"] th {{ color:#f3f4f6; }}
            html[data-theme="dark"] .node-ipv4 {{ color:#94a3b8; }}
            html[data-theme="dark"] .missed-cycles-link {{
                background:#1e293b;
                border-color:#475569;
                color:#c7d2fe;
            }}
            html[data-theme="dark"] .missed-cycles-link.current {{
                background:#3a2713;
                border-color:#a16207;
                color:#fde68a;
            }}
            html[data-theme="dark"] #bw-floating-tooltip {{
                background:#020617;
                color:#e2e8f0;
                border-color:#475569;
            }}
            html[data-theme="dark"] .label,
            html[data-theme="dark"] .traffic-title,
            html[data-theme="dark"] .table-hint,
            html[data-theme="dark"] .admin-note,
            html[data-theme="dark"] .breadcrumb,
            html[data-theme="dark"] .chart-note,
            html[data-theme="dark"] .axis-label,
            html[data-theme="dark"] .x-label {{ color:#9ca3af; fill:#9ca3af; }}
            html[data-theme="dark"] th {{ background:#182235; border-bottom-color:#334155; }}
            html[data-theme="dark"] td {{ border-bottom-color:#263244; }}
            html[data-theme="dark"] tr:hover {{ background:#172033; }}
            html[data-theme="dark"] tr.warn td {{ background:#3a2713; }}
            html[data-theme="dark"] .stale-row {{ background:#111827; }}
            html[data-theme="dark"] a {{ color:#60a5fa; }}
            html[data-theme="dark"] .periods a,
            html[data-theme="dark"] .scope-links a,
            html[data-theme="dark"] .page-link,
            html[data-theme="dark"] .copy-btn,
            html[data-theme="dark"] .btn {{ background:#1f2937; color:#e5e7eb; border-color:#3b4a61; }}
            html[data-theme="dark"] .periods a.active,
            html[data-theme="dark"] .scope-links a.active {{ background:#2563eb; color:#fff; border-color:#3b82f6; }}
            html[data-theme="dark"] .page-link.active {{ background:#e5e7eb; color:#111827; border-color:#e5e7eb; }}
            html[data-theme="dark"] .page-link.disabled {{ background:#111827; color:#64748b; }}
            html[data-theme="dark"] input,
            html[data-theme="dark"] select,
            html[data-theme="dark"] .search input,
            html[data-theme="dark"] .form-grid input,
            html[data-theme="dark"] .form-grid select,
            html[data-theme="dark"] .inline-form input,
            html[data-theme="dark"] .inline-form select {{ background:#0f172a; color:#e5e7eb; border-color:#334155; }}
            html[data-theme="dark"] .search button,
            html[data-theme="dark"] .login-card button {{ background:#334155; color:#fff; }}
            html[data-theme="dark"] .grid-line {{ stroke:#263244; }}
            html[data-theme="dark"] .axis {{ stroke:#64748b; }}
            html[data-theme="dark"] .total-line {{ stroke:#e5e7eb; }}
            html[data-theme="dark"] .total-dot {{ fill:#e5e7eb; }}
            html[data-theme="dark"] .dot {{ stroke:#111827; }}
            html[data-theme="dark"] .legend {{ color:#d1d5db; }}
            html[data-theme="dark"] .legend .total {{ background:#e5e7eb; }}
            html[data-theme="dark"] .theme-switch button.active {{ background:#dbeafe; color:#172554; }}
            html[data-theme="dark"] .error-box {{ background:#3f171d; color:#fecaca; border-color:#7f1d1d; }}
            html[data-theme="dark"] .success-box {{ background:#123222; color:#bbf7d0; border-color:#166534; }}
            html[data-theme="dark"] .db-danger {{ background:#31171a; border-color:#7f1d1d; }}
            html[data-theme="dark"] .metric-unknown {{ background:#1f2937; color:#d1d5db; border-color:#475569; }}

            /* v48.6.2 unified wide-table alignment */
            .table-wrap {{
                width: 100%;
                overflow-x: auto;
                overflow-y: visible;
                border: 1px solid #e5e7eb;
                border-radius: 9px;
                scrollbar-gutter: stable;
            }}
            .table-wrap table {{ margin: 0; }}
            .vm-table-card {{ overflow: visible; }}
            table th, table td {{ vertical-align: middle; }}
            .table-wrap thead th {{
                position: sticky;
                top: 0;
                z-index: 3;
                box-shadow: inset 0 -1px 0 #e5e7eb;
                white-space: nowrap;
            }}
            .table-vm {{ min-width: 2310px; table-layout: fixed; }}
            .table-vm col.col-state {{ width: 95px; }}
            .table-vm col.col-iface {{ width: 120px; }}
            .table-vm col.col-uuid {{ width: 320px; }}
            .table-vm col.col-rx, .table-vm col.col-tx {{ width: 110px; }}
            .table-vm col.col-total {{ width: 120px; }}
            .table-vm col.col-mbps, .table-vm col.col-peakmbps {{ width: 105px; }}
            .table-vm col.col-pps, .table-vm col.col-peakpps {{ width: 105px; }}
            .table-vm col.col-sample {{ width: 170px; }}
            .table-vm col.col-cpu {{ width: 125px; }}
            .table-vm col.col-vcpu {{ width: 72px; }}
            .table-vm col.col-ram {{ width: 200px; }}
            .table-vm col.col-diskr, .table-vm col.col-diskw {{ width: 125px; }}
            .table-vm col.col-drops {{ width: 78px; }}
            .table-vm col.col-errors {{ width: 68px; }}

            .table-top-vm {{ min-width: 2410px; table-layout: fixed; }}
            .table-top-vm col.top-rank {{ width: 50px; }}
            .table-top-vm col.top-node {{ width: 170px; }}
            .table-top-vm col.top-uuid {{ width: 330px; }}
            .table-top-vm col.top-ifaces {{ width: 75px; }}
            .table-top-vm col.top-public, .table-top-vm col.top-private {{ width: 115px; }}
            .table-top-vm col.top-total {{ width: 120px; }}
            .table-top-vm col.top-mbps, .table-top-vm col.top-peakmbps {{ width: 105px; }}
            .table-top-vm col.top-pps, .table-top-vm col.top-peakpps {{ width: 105px; }}
            .table-top-vm col.top-sample {{ width: 145px; }}
            .table-top-vm col.top-cpu {{ width: 125px; }}
            .table-top-vm col.top-vcpu {{ width: 72px; }}
            .table-top-vm col.top-ram {{ width: 200px; }}
            .table-top-vm col.top-diskr, .table-top-vm col.top-diskw {{ width: 125px; }}
            .table-top-vm col.top-push {{ width: 80px; }}
            .table-top-vm col.top-drops {{ width: 78px; }}
            .table-top-vm col.top-errors {{ width: 68px; }}

            .table-abuse {{ min-width: 2380px; table-layout: fixed; }}
            .table-abuse col.ab-rank {{ width: 48px; }}
            .table-abuse col.ab-node {{ width: 170px; }}
            .table-abuse col.ab-uuid {{ width: 325px; }}
            .table-abuse col.ab-reason {{ width: 310px; }}
            .table-abuse col.ab-severity {{ width: 85px; }}
            .table-abuse col.ab-total {{ width: 115px; }}
            .table-abuse col.ab-rate {{ width: 105px; }}
            .table-abuse col.ab-pps {{ width: 105px; }}
            .table-abuse col.ab-sample {{ width: 140px; }}
            .table-abuse col.ab-cpu {{ width: 120px; }}
            .table-abuse col.ab-vcpu {{ width: 70px; }}
            .table-abuse col.ab-ram {{ width: 195px; }}
            .table-abuse col.ab-disk {{ width: 120px; }}
            .table-abuse col.ab-push {{ width: 80px; }}
            .table-abuse col.ab-small {{ width: 68px; }}
            .table-abuse th, .table-abuse td {{ overflow: hidden; text-overflow: ellipsis; }}
            .table-abuse .num, .table-abuse .num-head {{ text-align: right; font-variant-numeric: tabular-nums; }}
            .table-abuse .num-head .sort-link {{ width: 100%; text-align: right; }}
            .metric-subline {{ display: block; margin-top: 4px; color: #6b7280; font-size: 11px; font-weight: 400; white-space: nowrap; }}
            .sample-cell .vm-state {{ margin-right: 0; }}
            .ram-cell {{ line-height: 1.25; }}
            .abuse-reasons {{ display: flex; flex-wrap: wrap; gap: 5px; white-space: normal; }}
            .abuse-reasons .metric-pill {{ padding: 4px 7px; font-size: 11px; font-weight: 700; }}
            .abuse-grid {{ grid-template-columns: repeat(4, minmax(170px, 1fr)); }}
            .bulk-queue-note {{ margin: 10px 0 0; }}
            @media (max-width: 900px) {{
                .wrap {{ padding: 14px; }}
                header {{ padding: 14px; }}
                .abuse-grid {{ grid-template-columns: repeat(2, minmax(140px, 1fr)); }}
            }}
            html[data-theme="dark"] .table-wrap {{ border-color: #374151; }}
            html[data-theme="dark"] .table-wrap thead th {{ box-shadow: inset 0 -1px 0 #374151; }}

</style>
    </head>
    <body>
        <header>
            <h2><a class="brand" href="{url_for('index')}">VirtInfra Monitor</a></h2>
            <div class="header-row">
                <nav class="main-nav">
                    <a href="{url_for('index')}">Dashboard</a>
                    <a href="{url_for('top_page')}">Top VM</a>
                    <a href="{url_for('vm_abuse_page')}">VM Abuse</a>
                    <a href="{url_for('storage_io_page')}">Storage I/O</a>
                    <a href="{url_for('bandwidth_consumption_page')}">Consumption</a>
                    <a href="{url_for('node_health_page')}">Node Health</a>
                </nav>
                <div class="theme-switch" role="group" aria-label="Theme mode">
                    <button type="button" data-theme-mode="auto">Auto</button>
                    <button type="button" data-theme-mode="dark">Dark</button>
                    <button type="button" data-theme-mode="light">Light</button>
                </div>
            </div>
            {user_html}
        </header>
        <div class="wrap" id="bw-content">{content}</div>
        <script>
        function copyText(value, btn) {{
            if (!value) return;
            function mark() {{
                if (!btn) return;
                const old = btn.textContent;
                btn.textContent = "✓";
                btn.classList.add("copied");
                setTimeout(function(){{ btn.textContent = old; btn.classList.remove("copied"); }}, 900);
            }}
            if (navigator.clipboard && navigator.clipboard.writeText) {{
                navigator.clipboard.writeText(value).then(mark).catch(function(){{ fallbackCopy(value); mark(); }});
            }} else {{
                fallbackCopy(value);
                mark();
            }}
        }}
        function fallbackCopy(value) {{
            const el = document.createElement("textarea");
            el.value = value;
            el.setAttribute("readonly", "");
            el.style.position = "absolute";
            el.style.left = "-9999px";
            document.body.appendChild(el);
            el.select();
            try {{ document.execCommand("copy"); }} catch(e) {{}}
            document.body.removeChild(el);
        }}
        function readThemeMode() {{
            try {{ return localStorage.getItem('bw-theme-mode') || 'auto'; }} catch (e) {{ return 'auto'; }}
        }}
        function writeThemeMode(mode) {{
            try {{ localStorage.setItem('bw-theme-mode', mode); }} catch (e) {{}}
        }}
        function resolvedTheme(mode) {{
            if (mode === 'dark' || mode === 'light') return mode;
            const hour = new Date().getHours();
            return (hour >= 18 || hour < 6) ? 'dark' : 'light';
        }}
        function applyTheme(mode, persist) {{
            if (mode !== 'auto' && mode !== 'dark' && mode !== 'light') mode = 'auto';
            if (persist) writeThemeMode(mode);
            document.documentElement.setAttribute('data-theme-mode', mode);
            document.documentElement.setAttribute('data-theme', resolvedTheme(mode));
            document.querySelectorAll('.theme-switch button[data-theme-mode]').forEach(function(btn) {{
                btn.classList.toggle('active', btn.getAttribute('data-theme-mode') === mode);
            }});
        }}
        applyTheme(readThemeMode(), false);
        document.addEventListener("click", function(ev) {{
            const themeBtn = ev.target.closest('.theme-switch button[data-theme-mode]');
            if (themeBtn) {{
                ev.preventDefault();
                applyTheme(themeBtn.getAttribute('data-theme-mode'), true);
                return;
            }}
            const btn = ev.target.closest(".copy-btn");
            if (!btn) return;
            ev.preventDefault();
            ev.stopPropagation();
            copyText(btn.getAttribute("data-copy") || "", btn);
        }}, true);

        let bwTooltipElement = null;
        let bwTooltipTarget = null;

        function bwGetTooltip() {{
            if (!bwTooltipElement) {{
                bwTooltipElement = document.createElement('div');
                bwTooltipElement.id = 'bw-floating-tooltip';
                bwTooltipElement.setAttribute('role', 'tooltip');
                document.body.appendChild(bwTooltipElement);
            }}
            return bwTooltipElement;
        }}

        function bwPositionTooltip(event, target) {{
            const tooltip = bwGetTooltip();
            const gap = 14;
            const viewportPadding = 10;
            const fallback = target.getBoundingClientRect();

            let x = event && Number.isFinite(event.clientX)
                ? event.clientX + gap
                : fallback.left + gap;
            let y = event && Number.isFinite(event.clientY)
                ? event.clientY + gap
                : fallback.bottom + gap;

            tooltip.style.left = '0px';
            tooltip.style.top = '0px';
            const rect = tooltip.getBoundingClientRect();

            if (x + rect.width > window.innerWidth - viewportPadding) {{
                x = Math.max(viewportPadding, window.innerWidth - rect.width - viewportPadding);
            }}
            if (y + rect.height > window.innerHeight - viewportPadding) {{
                y = Math.max(
                    viewportPadding,
                    event && Number.isFinite(event.clientY)
                        ? event.clientY - rect.height - gap
                        : fallback.top - rect.height - gap
                );
            }}

            tooltip.style.left = Math.round(x) + 'px';
            tooltip.style.top = Math.round(y) + 'px';
        }}

        function bwShowTooltip(target, event) {{
            const value = target && target.getAttribute('data-bw-tooltip');
            if (!value) return;

            bwTooltipTarget = target;
            const tooltip = bwGetTooltip();
            tooltip.textContent = value;
            tooltip.style.display = 'block';
            bwPositionTooltip(event, target);
        }}

        function bwHideTooltip(target) {{
            if (target && bwTooltipTarget && target !== bwTooltipTarget) return;
            if (bwTooltipElement) bwTooltipElement.style.display = 'none';
            bwTooltipTarget = null;
        }}

        document.addEventListener('mouseover', function(event) {{
            const target = event.target.closest('[data-bw-tooltip]');
            if (!target) return;
            bwShowTooltip(target, event);
        }});

        document.addEventListener('mousemove', function(event) {{
            if (bwTooltipTarget) bwPositionTooltip(event, bwTooltipTarget);
        }});

        document.addEventListener('mouseout', function(event) {{
            const target = event.target.closest('[data-bw-tooltip]');
            if (!target) return;
            const related = event.relatedTarget;
            if (related && target.contains(related)) return;
            bwHideTooltip(target);
        }});

        document.addEventListener('focusin', function(event) {{
            const target = event.target.closest('[data-bw-tooltip]');
            if (target) bwShowTooltip(target, null);
        }});

        document.addEventListener('focusout', function(event) {{
            const target = event.target.closest('[data-bw-tooltip]');
            if (target) bwHideTooltip(target);
        }});

        let bwNavigationController = null;
        let bwNavigationBusy = false;

        function bwAuthOrActionPath(pathname) {{
            return pathname === '/login'
                || pathname === '/logout'
                || pathname === '/admin/login'
                || pathname === '/admin/logout'
                || pathname === '/admin/setup';
        }}

        function bwCanNavigate(url) {{
            try {{
                const target = new URL(url, window.location.href);
                return target.origin === window.location.origin
                    && !bwAuthOrActionPath(target.pathname);
            }} catch (e) {{
                return false;
            }}
        }}

        function bwCaptureContentState() {{
            const state = {{x: window.scrollX, y: window.scrollY, tables: [], details: []}};
            document.querySelectorAll('#bw-content .table-wrap').forEach(function(el, index) {{
                state.tables.push({{index:index, left:el.scrollLeft, top:el.scrollTop}});
            }});
            document.querySelectorAll('#bw-content details').forEach(function(el, index) {{
                if (el.open) state.details.push(index);
            }});
            return state;
        }}
        function bwRestoreContentState(state) {{
            if (!state) return;
            document.querySelectorAll('#bw-content .table-wrap').forEach(function(el, index) {{
                const saved = state.tables.find(function(x) {{ return x.index === index; }});
                if (saved) {{ el.scrollLeft = saved.left; el.scrollTop = saved.top; }}
            }});
            document.querySelectorAll('#bw-content details').forEach(function(el, index) {{
                el.open = state.details.indexOf(index) !== -1;
            }});
            window.scrollTo({{left: state.x, top: state.y, behavior: 'auto'}});
        }}
        async function bwNavigate(url, options) {{
            options = options || {{}};
            const push = options.push !== false;
            const preserveScroll = options.preserveScroll === true;
            const silent = options.silent === true;
            const requestedUrl = new URL(url, window.location.href).href;
            const preservedState = preserveScroll ? bwCaptureContentState() : null;

            bwHideTooltip();
            if (bwNavigationController) bwNavigationController.abort();
            bwNavigationController = new AbortController();
            bwNavigationBusy = true;
            if (!silent) document.documentElement.classList.add('bw-nav-loading');

            try {{
                const response = await fetch(requestedUrl, {{
                    method: 'GET',
                    credentials: 'same-origin',
                    redirect: 'follow',
                    headers: {{
                        'X-BW-Navigation': 'partial',
                        'Accept': 'text/html'
                    }},
                    signal: bwNavigationController.signal
                }});

                if (!response.ok) throw new Error('HTTP ' + response.status);

                const finalResponseUrl = response.url || requestedUrl;
                const finalResponsePath = new URL(finalResponseUrl, window.location.href).pathname;
                if (bwAuthOrActionPath(finalResponsePath)) {{
                    if (silent) return;
                    window.location.assign(finalResponseUrl);
                    return;
                }}

                const html = await response.text();
                const parsed = new DOMParser().parseFromString(html, 'text/html');
                const incoming = parsed.querySelector('#bw-content');
                const current = document.querySelector('#bw-content');

                if (!incoming || !current) {{
                    // A quiet refresh must never turn a transient backend or
                    // auth response into a full browser reload. Keep the last
                    // good dashboard visible and try again on the next tick.
                    if (silent) return;
                    window.location.assign(response.url || requestedUrl);
                    return;
                }}

                current.innerHTML = incoming.innerHTML;
                if (parsed.title) document.title = parsed.title;
                if (parsed.body && parsed.body.className) {{
                    document.body.className = parsed.body.className;
                }}

                const finalUrl = response.url || requestedUrl;
                if (push) {{
                    history.pushState({{bwNavigation: true}}, '', finalUrl);
                }} else if (options.replace === true) {{
                    history.replaceState({{bwNavigation: true}}, '', finalUrl);
                }}

                applyTheme(readThemeMode(), false);

                if (preserveScroll) {{
                    bwRestoreContentState(preservedState);
                }} else {{
                    window.scrollTo({{top: 0, left: 0, behavior: 'auto'}});
                }}
            }} catch (error) {{
                if (error && error.name === 'AbortError') return;
                // Normal clicks may fall back to a full navigation. The
                // five-second silent refresh intentionally does not reload the
                // document on timeout/5xx/network errors.
                if (!silent) window.location.assign(requestedUrl);
            }} finally {{
                bwNavigationBusy = false;
                document.documentElement.classList.remove('bw-nav-loading');
            }}
        }}

        document.addEventListener('click', function(ev) {{
            if (ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;

            const link = ev.target.closest('a[href]');
            if (!link) return;
            if (link.target && link.target !== '_self') return;
            if (link.hasAttribute('download') || link.hasAttribute('data-no-pjax')) return;

            const rawHref = link.getAttribute('href') || '';
            if (!rawHref || rawHref.startsWith('#') || rawHref.startsWith('javascript:') || rawHref.startsWith('mailto:')) return;
            if (!bwCanNavigate(link.href)) return;

            const target = new URL(link.href, window.location.href);
            const current = new URL(window.location.href);
            const preserveScroll = target.pathname === current.pathname;

            ev.preventDefault();
            bwNavigate(target.href, {{
                push: true,
                preserveScroll: preserveScroll
            }});
        }});

        document.addEventListener('submit', function(ev) {{
            const form = ev.target;
            if (!(form instanceof HTMLFormElement)) return;
            if ((form.method || 'get').toLowerCase() !== 'get') return;
            if (form.target && form.target !== '_self') return;

            const target = new URL(form.action || window.location.href, window.location.href);
            if (!bwCanNavigate(target.href)) return;

            const params = new URLSearchParams();
            new FormData(form).forEach(function(value, key) {{
                if (typeof value === 'string') params.append(key, value);
            }});
            target.search = params.toString();

            ev.preventDefault();
            bwNavigate(target.href, {{
                push: true,
                preserveScroll: true
            }});
        }});

        window.addEventListener('popstate', function() {{
            bwNavigate(window.location.href, {{
                push: false,
                preserveScroll: true,
                silent: true
            }});
        }});

        // Quiet 5-second content refresh for live operational pages only.
        // It never reloads the browser document, never overlaps requests, and
        // pauses while the operator is editing a form.
        const BW_AUTO_REFRESH_MS = 5000;
        function bwIsLivePage() {{
            const p = window.location.pathname;
            return p === '/' || p === '/top' || p === '/top/nodes' || p === '/abuse/vms'
                || p.startsWith('/node/') || p.startsWith('/vm/');
        }}
        function bwOperatorIsEditing() {{
            const el = document.activeElement;
            if (!el || el === document.body) return false;
            return !!el.closest('input,select,textarea,[contenteditable="true"]');
        }}
        setInterval(function() {{
            const mode = readThemeMode();
            if (mode === 'auto') applyTheme('auto', false);
            if (!bwIsLivePage() || document.hidden || bwNavigationBusy || bwOperatorIsEditing()) return;
            bwNavigate(window.location.href, {{
                push: false,
                preserveScroll: true,
                silent: true
            }});
        }}, BW_AUTO_REFRESH_MS);
        </script>
    </body>
    </html>
    """, mimetype="text/html")

@app.before_request
def enforce_dashboard_login():
    endpoint = request.endpoint or ""
    public_endpoints = {
        "health",
        "push",
        "push_bandwidth_consumption",
        "dashboard_login",
        "dashboard_logout",
        "admin_setup",
        "admin_login",
        "admin_logout",
        "static",
    }
    if endpoint in public_endpoints:
        return None
    # REST API v1 authenticates independently with Bearer API keys.
    # It must bypass the dashboard-session gate so @require_api_scopes()
    # can validate Authorization: Bearer ... on the route itself.
    if request.path.startswith("/api/v1/") or endpoint.startswith("api_v1_"):
        return None
    if endpoint == "admin_page" or endpoint.startswith("admin_"):
        return None
    return require_dashboard()

