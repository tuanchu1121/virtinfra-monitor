# VirtInfra Monitor v50.4.9 professional preset suite + one simple custom theme
# ---------------------------------------------------------------------------
# Auto / Light / Dark remain immutable core choices. Administrators only
# choose which VirtInfra presets are visible and may configure one simple
# Custom theme. Presets carry a complete professional visual system including
# typography, density, cards, tables, metrics, charts and HD/2K/4K scaling.

V5049_THEME_SETTING_KEY = "simple_theme_settings_v4"
V5049_LEGACY_THEME_SETTING_KEY = "simple_theme_settings_v3"
V5049_THEME_SELECTION_KEY = "virtinfra-theme-selection-v4"
V5049_LEGACY_SELECTION_KEY = "virtinfra-theme-selection-v3"
V5049_CUSTOM_THEME_ID = "simple-custom"
V5049_THEME_COLOR_FIELDS = ("bg", "panel", "text", "line", "brand", "rx", "tx")
V5049_THEME_DENSITIES = {
    "compact": {
        "base_font": 12, "table_font": 11, "small_font": 10,
        "metric_font": 17, "row_pad": 6, "card_pad": 13, "gap": 10,
    },
    "normal": {
        "base_font": 13, "table_font": 12, "small_font": 11,
        "metric_font": 18, "row_pad": 8, "card_pad": 16, "gap": 12,
    },
    "comfortable": {
        "base_font": 14, "table_font": 13, "small_font": 12,
        "metric_font": 20, "row_pad": 10, "card_pad": 19, "gap": 14,
    },
}
V5049_THEME_PRESETS = {
    "virtinfra-core": {
        "name": "VirtInfra Core",
        "description": "Balanced navy workspace for daily infrastructure operations.",
        "base_mode": "dark", "density": "normal", "radius": 10, "chart_line": 2.2,
        "bg": "#08111f", "panel": "#101c2e", "panel_soft": "#16253a",
        "header": "#091525", "text": "#edf3fb", "muted": "#9fb0c5", "line": "#283a52",
        "brand": "#5b91f5", "rx": "#38bdf8", "tx": "#fb9a5a",
        "success": "#35c979", "warning": "#f5b544", "danger": "#f0646f",
        "table_head": "#15243a", "row_hover": "#142942", "shadow": "0 8px 24px rgba(0,0,0,.18)",
    },
    "midnight-signal": {
        "name": "Midnight Signal",
        "description": "Deep blue-black panels with crisp cyan telemetry.",
        "base_mode": "dark", "density": "normal", "radius": 8, "chart_line": 2.4,
        "bg": "#060b13", "panel": "#0d1622", "panel_soft": "#132131",
        "header": "#07101a", "text": "#f1f6fb", "muted": "#9aaabd", "line": "#253548",
        "brand": "#62a8ff", "rx": "#30c7e8", "tx": "#f6a15f",
        "success": "#36cf84", "warning": "#f4bd4f", "danger": "#f06772",
        "table_head": "#121e2d", "row_hover": "#10273a", "shadow": "0 10px 28px rgba(0,0,0,.24)",
    },
    "arctic-console": {
        "name": "Arctic Console",
        "description": "Cool light surface with dark type and restrained blue accents.",
        "base_mode": "light", "density": "normal", "radius": 10, "chart_line": 2.2,
        "bg": "#edf2f7", "panel": "#ffffff", "panel_soft": "#f5f8fb",
        "header": "#18304d", "text": "#172235", "muted": "#637083", "line": "#d4dde8",
        "brand": "#316fd4", "rx": "#168aad", "tx": "#d97732",
        "success": "#238a57", "warning": "#b97713", "danger": "#c83f4c",
        "table_head": "#f0f4f8", "row_hover": "#f2f7fc", "shadow": "0 5px 18px rgba(31,49,73,.08)",
    },
    "graphite-edge": {
        "name": "Graphite Edge",
        "description": "Neutral graphite, compact geometry and precise blue highlights.",
        "base_mode": "dark", "density": "compact", "radius": 7, "chart_line": 2.0,
        "bg": "#101316", "panel": "#191d22", "panel_soft": "#20262c",
        "header": "#11161b", "text": "#eef1f4", "muted": "#a0a9b3", "line": "#363e47",
        "brand": "#74a7f7", "rx": "#50b9d6", "tx": "#eda45f",
        "success": "#54c782", "warning": "#e9b84f", "danger": "#ea6a72",
        "table_head": "#20252b", "row_hover": "#222b34", "shadow": "0 6px 18px rgba(0,0,0,.17)",
    },
    "noc-vision": {
        "name": "NOC Vision",
        "description": "High contrast and larger metrics for wall displays and control rooms.",
        "base_mode": "dark", "density": "comfortable", "radius": 8, "chart_line": 2.8,
        "bg": "#03070d", "panel": "#0a121d", "panel_soft": "#101c2a",
        "header": "#050b12", "text": "#ffffff", "muted": "#b8c5d4", "line": "#42546b",
        "brand": "#52b6ff", "rx": "#39d0f2", "tx": "#ffad63",
        "success": "#4cdf8b", "warning": "#ffd05a", "danger": "#ff6d78",
        "table_head": "#111e2d", "row_hover": "#10283b", "shadow": "0 9px 26px rgba(0,0,0,.28)",
    },
}
V5049_LEGACY_PRESET_MAP = {
    "virtinfra-ocean": "virtinfra-core",
    "grafana-inspired": "midnight-signal",
    "zabbix-inspired": "arctic-console",
    "prometheus-inspired": "graphite-edge",
    "noc-high-contrast": "noc-vision",
}


def _v5049_valid_hex(value, fallback):
    value = str(value or "").strip().lower()
    if len(value) == 7 and value.startswith("#") and all(ch in "0123456789abcdef" for ch in value[1:]):
        return value
    return fallback


def _v5049_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _v5049_default_custom_theme():
    return {
        "name": "Custom",
        "base_mode": "dark",
        "density": "normal",
        "bg": "#0b1220",
        "panel": "#111d2e",
        "text": "#eaf0f7",
        "line": "#31445d",
        "brand": "#4d8df7",
        "rx": "#38bdf8",
        "tx": "#fb923c",
    }


def _v5049_default_theme_settings():
    return {
        "version": 4,
        "enabled_presets": list(V5049_THEME_PRESETS),
        "custom_enabled": False,
        "custom": _v5049_default_custom_theme(),
    }


def _v5049_normalize_custom_theme(raw):
    fallback = _v5049_default_custom_theme()
    raw = raw if isinstance(raw, dict) else {}
    name = str(raw.get("name") or fallback["name"]).strip()[:40] or fallback["name"]
    base_mode = str(raw.get("base_mode") or fallback["base_mode"]).strip().lower()
    if base_mode not in {"light", "dark"}:
        base_mode = fallback["base_mode"]
    density = str(raw.get("density") or fallback["density"]).strip().lower()
    if density not in V5049_THEME_DENSITIES:
        density = fallback["density"]
    theme = {"name": name, "base_mode": base_mode, "density": density}
    for key in V5049_THEME_COLOR_FIELDS:
        theme[key] = _v5049_valid_hex(raw.get(key), fallback[key])
    return theme


def _v5049_migrate_legacy_settings(raw):
    raw = raw if isinstance(raw, dict) else {}
    enabled = []
    for legacy_id in raw.get("enabled_presets") or []:
        mapped = V5049_LEGACY_PRESET_MAP.get(str(legacy_id or "").strip().lower())
        if mapped and mapped not in enabled:
            enabled.append(mapped)
    if not enabled and raw.get("enabled_presets") is None:
        enabled = list(V5049_THEME_PRESETS)
    return {
        "version": 4,
        "enabled_presets": enabled,
        "custom_enabled": _v5049_bool(raw.get("custom_enabled"), False),
        "custom": _v5049_normalize_custom_theme(raw.get("custom")),
    }


def _v5049_normalize_theme_settings(raw):
    raw = raw if isinstance(raw, dict) else {}
    enabled = []
    source = raw.get("enabled_presets") if isinstance(raw.get("enabled_presets"), list) else list(V5049_THEME_PRESETS)
    for theme_id in source:
        theme_id = str(theme_id or "").strip().lower()
        if theme_id in V5049_THEME_PRESETS and theme_id not in enabled:
            enabled.append(theme_id)
    return {
        "version": 4,
        "enabled_presets": enabled,
        "custom_enabled": _v5049_bool(raw.get("custom_enabled"), False),
        "custom": _v5049_normalize_custom_theme(raw.get("custom")),
    }


def _v5049_theme_settings():
    raw = get_admin_setting(V5049_THEME_SETTING_KEY, "")
    if raw:
        try:
            return _v5049_normalize_theme_settings(json.loads(raw))
        except Exception:
            app.logger.warning("Invalid v50.4.9 theme settings; using defaults")
            return _v5049_default_theme_settings()
    legacy_raw = get_admin_setting(V5049_LEGACY_THEME_SETTING_KEY, "")
    if legacy_raw:
        try:
            migrated = _v5049_migrate_legacy_settings(json.loads(legacy_raw))
            return _v5049_save_theme_settings(migrated)
        except Exception:
            app.logger.warning("Could not migrate legacy theme settings; using defaults")
    return _v5049_default_theme_settings()


def _v5049_save_theme_settings(settings):
    normalized = _v5049_normalize_theme_settings(settings)
    set_admin_setting(V5049_THEME_SETTING_KEY, json.dumps(normalized, separators=(",", ":"), sort_keys=True))
    _v48140_bump_cache_generation()
    return normalized


def _v5049_available_themes(settings=None):
    settings = settings or _v5049_theme_settings()
    themes = []
    for theme_id in settings["enabled_presets"]:
        preset = dict(V5049_THEME_PRESETS[theme_id])
        preset["id"] = theme_id
        themes.append(preset)
    if settings.get("custom_enabled"):
        custom = dict(settings["custom"])
        light = custom["base_mode"] == "light"
        custom.update({
            "id": V5049_CUSTOM_THEME_ID,
            "radius": 9,
            "chart_line": 2.2,
            "panel_soft": "color-mix(in srgb,%s 92%%,%s)" % (custom["panel"], custom["text"]),
            "header": custom["brand"] if light else custom["bg"],
            "muted": "color-mix(in srgb,%s 62%%,%s)" % (custom["text"], custom["bg"]),
            "success": "#238a57" if light else "#35c979",
            "warning": "#b97713" if light else "#f5b544",
            "danger": "#c83f4c" if light else "#f0646f",
            "table_head": "color-mix(in srgb,%s 90%%,%s)" % (custom["panel"], custom["text"]),
            "row_hover": "color-mix(in srgb,%s 8%%,%s)" % (custom["brand"], custom["panel"]),
            "shadow": "0 7px 22px rgba(0,0,0,.16)" if not light else "0 5px 18px rgba(31,49,73,.08)",
            "description": "One simple administrator-defined theme.",
        })
        themes.append(custom)
    return themes


def _v5049_theme_css(settings=None):
    blocks = []
    for theme in _v5049_available_themes(settings):
        density = V5049_THEME_DENSITIES[theme["density"]]
        selector = 'html[data-custom-theme="%s"]' % theme["id"]
        radius = int(theme.get("radius", 9))
        radius_small = max(5, min(radius - 2, 8))
        blocks.append(f"""
{selector} {{
  color-scheme:{theme['base_mode']};
  --custom-bg:{theme['bg']};--custom-panel:{theme['panel']};--custom-panel-soft:{theme['panel_soft']};
  --custom-header:{theme['header']};--custom-text:{theme['text']};--custom-muted:{theme['muted']};
  --custom-line:{theme['line']};--custom-brand:{theme['brand']};--custom-rx:{theme['rx']};--custom-tx:{theme['tx']};
  --custom-success:{theme['success']};--custom-warning:{theme['warning']};--custom-danger:{theme['danger']};
  --custom-table-head:{theme['table_head']};--custom-row-hover:{theme['row_hover']};--custom-shadow:{theme['shadow']};
  --vi-base-font:{density['base_font']}px;--vi-table-font:{density['table_font']}px;--vi-small-font:{density['small_font']}px;
  --vi-metric-font:{density['metric_font']}px;--vi-row-y:{density['row_pad']}px;--vi-card-pad:{density['card_pad']}px;--vi-gap:{density['gap']}px;
  --vi-radius:{radius}px;--vi-radius-small:{radius_small}px;--vi-chart-line:{float(theme.get('chart_line',2.2)):.1f}px;
  --bg:var(--custom-bg);--panel:var(--custom-panel);--card:var(--custom-panel);--panel-soft:var(--custom-panel-soft);
  --line:var(--custom-line);--text:var(--custom-text);--muted:var(--custom-muted);--brand:var(--custom-brand);--shadow:var(--custom-shadow);
}}
{selector} body {{background:var(--custom-bg)!important;color:var(--custom-text)!important;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif!important;font-size:var(--vi-base-font)!important;line-height:1.45;text-rendering:geometricPrecision;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;font-feature-settings:"kern" 1,"liga" 1}}
{selector} header {{background:var(--custom-header)!important;border-bottom:1px solid var(--custom-line)!important;box-shadow:0 1px 0 rgba(255,255,255,.025)!important}}
{selector} .brand {{color:#fff!important}}{selector} a,{selector} .sort-link:hover,{selector} .eyebrow {{color:var(--custom-brand)!important}}
{selector} .wrap {{max-width:1920px!important;padding:22px!important}}
{selector} .card,{selector} .admin-kpi,{selector} .quick-link-card,{selector} .action-menu>div,{selector} .action-menu summary,
{selector} .storage-entity-card-v48139,{selector} .storage-section-box-v48139,{selector} .storage-vm-card,{selector} .storage-node-card,
{selector} .storage-child-item,{selector} .vm-disk-panel {{background:var(--custom-panel)!important;border-color:var(--custom-line)!important;color:var(--custom-text)!important;border-radius:var(--vi-radius)!important;box-shadow:var(--custom-shadow)!important}}
{selector} .card {{padding:var(--vi-card-pad)!important;margin-bottom:var(--vi-gap)!important}}
{selector} .grid,{selector} .admin-kpis,{selector} .quick-link-grid,{selector} .bwcons-summary-grid {{gap:var(--vi-gap)!important}}
{selector} .stat,{selector} .traffic-box,{selector} .admin-kpi {{min-width:0;min-height:88px;display:flex;flex-direction:column;justify-content:center}}
{selector} .stat,{selector} .traffic-box,{selector} .overview-meta span,{selector} .count-badges span,{selector} .info-strip span,
{selector} .node-line span,{selector} .hero-meta span,{selector} .status-chip,{selector} .queue-summary>div {{background:var(--custom-panel-soft)!important;border-color:var(--custom-line)!important;color:var(--custom-text)!important;border-radius:var(--vi-radius-small)!important}}
{selector} .page-hero,{selector} .admin-hero {{background:linear-gradient(135deg,var(--custom-panel),color-mix(in srgb,var(--custom-brand) 7%,var(--custom-panel)))!important;border-color:var(--custom-line)!important}}
{selector} .card h2 {{font-size:clamp(23px,1.15vw,28px)!important;line-height:1.12}}{selector} .card h3 {{font-size:clamp(16px,.82vw,19px)!important}}
{selector} .stat>b,{selector} .traffic-total,{selector} .admin-kpi b,{selector} .storage-overall-value-v48139 b {{font-size:var(--vi-metric-font)!important;line-height:1.16;letter-spacing:-.025em;font-weight:850!important}}
{selector} .stat>b,{selector} .traffic-total,{selector} .admin-kpi b,{selector} .metric-pair b,{selector} .metric-stack b,
{selector} .cpu-core-value,{selector} .ram-guest-value,{selector} .bwcons-triplet b,{selector} .bwcons-summary b,{selector} .mono {{font-variant-numeric:tabular-nums lining-nums;font-feature-settings:"tnum" 1,"lnum" 1}}
{selector} .table-wrap {{background:var(--custom-panel)!important;border-color:var(--custom-line)!important;border-radius:var(--vi-radius)!important;box-shadow:none!important}}
{selector} table {{font-size:var(--vi-table-font)!important;font-variant-numeric:tabular-nums lining-nums}}
{selector} th {{background:var(--custom-table-head)!important;color:var(--custom-muted)!important;border-color:var(--custom-line)!important;padding:var(--vi-row-y) 11px!important;font-size:calc(var(--vi-table-font) - 1px)!important;letter-spacing:.045em}}
{selector} td {{background:transparent!important;border-color:var(--custom-line)!important;color:var(--custom-text)!important;padding:var(--vi-row-y) 11px!important;font-size:var(--vi-table-font)!important}}
{selector} tbody tr:hover {{background:var(--custom-row-hover)!important}}
{selector} small,{selector} .label,{selector} .table-hint,{selector} .admin-note,{selector} .breadcrumb,{selector} .chart-note,
{selector} .row-sub,{selector} .storage-note,{selector} .metric-subline {{color:var(--custom-muted)!important;font-size:var(--vi-small-font)!important;line-height:1.42}}
{selector} input,{selector} select,{selector} textarea,{selector} .search input,{selector} .form-grid input,{selector} .inline-form input {{background:var(--custom-panel-soft)!important;color:var(--custom-text)!important;border-color:var(--custom-line)!important;border-radius:var(--vi-radius-small)!important}}
{selector} .btn,{selector} button:not(.btn-danger):not(.copy-btn),{selector} .periods a,{selector} .scope-links a,{selector} .page-link,{selector} .copy-btn {{background:var(--custom-panel-soft)!important;color:var(--custom-text)!important;border-color:var(--custom-line)!important;border-radius:var(--vi-radius-small)!important}}
{selector} button[type="submit"]:not(.btn-danger),{selector} .search button,{selector} .periods a.active,{selector} .scope-links a.active,{selector} .admin-tabs a.active {{background:var(--custom-brand)!important;border-color:var(--custom-brand)!important;color:#fff!important}}
{selector} .btn-danger {{background:color-mix(in srgb,var(--custom-danger) 12%,var(--custom-panel))!important;color:var(--custom-danger)!important;border-color:color-mix(in srgb,var(--custom-danger) 50%,var(--custom-line))!important}}
{selector} .success-box,{selector} .status.ok {{background:color-mix(in srgb,var(--custom-success) 13%,var(--custom-panel))!important;color:var(--custom-success)!important;border-color:color-mix(in srgb,var(--custom-success) 45%,var(--custom-line))!important}}
{selector} .status.warn,{selector} .health-pill.warning {{background:color-mix(in srgb,var(--custom-warning) 14%,var(--custom-panel))!important;color:var(--custom-warning)!important;border-color:color-mix(in srgb,var(--custom-warning) 45%,var(--custom-line))!important}}
{selector} .error-box,{selector} .status.crit {{background:color-mix(in srgb,var(--custom-danger) 13%,var(--custom-panel))!important;color:var(--custom-danger)!important;border-color:color-mix(in srgb,var(--custom-danger) 45%,var(--custom-line))!important}}
{selector} .rx-line {{stroke:var(--custom-rx)!important;stroke-width:var(--vi-chart-line)!important}}{selector} .rx-dot,{selector} .legend .rx {{fill:var(--custom-rx)!important;background:var(--custom-rx)!important}}
{selector} .tx-line {{stroke:var(--custom-tx)!important;stroke-width:var(--vi-chart-line)!important}}{selector} .tx-dot,{selector} .legend .tx {{fill:var(--custom-tx)!important;background:var(--custom-tx)!important}}
{selector} .total-line {{stroke:var(--custom-text)!important;stroke-width:var(--vi-chart-line)!important}}{selector} .total-dot {{fill:var(--custom-text)!important}}{selector} .grid-line {{stroke:var(--custom-line)!important}}
{selector} .bwcons-groups {{grid-template-columns:repeat(2,minmax(225px,1fr))!important;gap:var(--vi-gap)!important}}
{selector} .bwcons-group {{min-width:0;min-height:82px;display:flex;flex-direction:column;justify-content:center;background:var(--custom-panel-soft)!important;border-color:var(--custom-line)!important;border-radius:var(--vi-radius-small)!important;padding:11px!important}}
{selector} .bwcons-group-title {{color:var(--custom-muted)!important;font-size:var(--vi-small-font)!important;letter-spacing:.055em}}
{selector} .bwcons-triplet {{grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:8px!important}}
{selector} .bwcons-triplet span {{min-width:0;color:var(--custom-muted)!important}}{selector} .bwcons-triplet b {{font-size:calc(var(--vi-table-font) + 1px)!important;color:var(--custom-text)!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
{selector} .bwcons-triplet .rx b {{color:var(--custom-rx)!important}}{selector} .bwcons-triplet .tx b {{color:var(--custom-tx)!important}}{selector} .bwcons-triplet .total b {{color:var(--custom-text)!important;font-weight:900!important}}
{selector} .bwcons-summary {{min-height:122px;display:grid;align-content:center}}{selector} .bwcons-summary b {{font-size:calc(var(--vi-table-font) + 1px)!important}}
{selector} .storage-child-metric b,{selector} .storage-row-perf-v48139 b {{font-size:max(10px,var(--vi-table-font))!important}}
@media(max-width:1450px){{
  {selector}{{--vi-base-font:{max(11,density['base_font']-1)}px;--vi-table-font:{max(10,density['table_font']-1)}px;--vi-small-font:{max(9,density['small_font']-1)}px;--vi-metric-font:{max(16,density['metric_font']-1)}px;--vi-card-pad:{max(12,density['card_pad']-2)}px;--vi-gap:{max(9,density['gap']-2)}px}}
  {selector} .wrap{{padding:16px!important}}{selector} .stat,{selector} .traffic-box,{selector} .admin-kpi{{min-height:80px}}
}}
@media(min-width:1900px){{
  {selector}{{--vi-base-font:{density['base_font']+1}px;--vi-table-font:{density['table_font']+1}px;--vi-small-font:{density['small_font']+1}px;--vi-metric-font:{density['metric_font']+2}px;--vi-card-pad:{density['card_pad']+2}px;--vi-gap:{density['gap']+2}px}}
  {selector} .wrap{{max-width:2440px!important;padding:26px!important}}{selector} .bwcons-groups{{grid-template-columns:repeat(3,minmax(220px,1fr))!important}}
}}
@media(min-width:3000px){{
  {selector}{{--vi-base-font:{density['base_font']+2}px;--vi-table-font:{density['table_font']+2}px;--vi-small-font:{density['small_font']+2}px;--vi-metric-font:{density['metric_font']+4}px;--vi-card-pad:{density['card_pad']+4}px;--vi-gap:{density['gap']+4}px}}
  {selector} .wrap{{max-width:3360px!important;padding:32px!important}}{selector} .stat,{selector} .traffic-box,{selector} .admin-kpi{{min-height:108px}}
}}
@media(max-width:900px){{{selector} .bwcons-groups{{grid-template-columns:1fr!important}}{selector} .wrap{{padding:12px!important}}}}
""")
    controls = """
<style>
.appearance-controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.simple-theme-picker{display:flex;align-items:center;gap:6px;margin:0;color:#cbd5e1;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.04em}.simple-theme-picker select{min-width:154px;max-width:220px;padding:7px 30px 7px 9px;border-radius:8px;border:1px solid rgba(255,255,255,.20);background:#111827;color:#fff;font-size:12px;font-weight:750;text-transform:none;letter-spacing:0}.simple-theme-picker select:focus{outline:2px solid #60a5fa;outline-offset:1px}@media(max-width:760px){.appearance-controls{width:100%}.simple-theme-picker{width:100%}.simple-theme-picker select{flex:1;max-width:none}}
</style>
"""
    return controls + "<style>" + "\n".join(blocks) + "</style>"


def _v5049_theme_selector_html(settings=None):
    options = ['<option value="">More themes</option>']
    for theme in _v5049_available_themes(settings):
        options.append('<option value="%s">%s</option>' % (escape(theme["id"], quote=True), escape(theme["name"])))
    return '''<div class="appearance-controls">
                <div class="theme-switch" role="group" aria-label="Theme mode">
                    <button type="button" data-theme-mode="auto">Auto</button>
                    <button type="button" data-theme-mode="dark">Dark</button>
                    <button type="button" data-theme-mode="light">Light</button>
                </div>
                <label class="simple-theme-picker"><span>Theme</span><select id="simple-theme-select" aria-label="Additional theme">%s</select></label>
            </div>''' % "".join(options)


def _v5049_theme_client_payload(settings=None):
    return {theme["id"]: theme["base_mode"] for theme in _v5049_available_themes(settings)}


def _v5049_early_theme_script(settings=None):
    payload = json.dumps(_v5049_theme_client_payload(settings), separators=(",", ":"), sort_keys=True)
    legacy_map = json.dumps(V5049_LEGACY_PRESET_MAP, separators=(",", ":"), sort_keys=True)
    return f'''<script>(function(){{var themes={payload},legacy={legacy_map},id="";try{{id=localStorage.getItem("{V5049_THEME_SELECTION_KEY}")||"";if(!id){{var old=localStorage.getItem("{V5049_LEGACY_SELECTION_KEY}")||"";id=legacy[old]||old;if(id)localStorage.setItem("{V5049_THEME_SELECTION_KEY}",id);localStorage.removeItem("{V5049_LEGACY_SELECTION_KEY}")}}}}catch(e){{}}if(themes[id]){{document.documentElement.setAttribute("data-custom-theme",id);document.documentElement.setAttribute("data-theme",themes[id]);document.documentElement.setAttribute("data-theme-mode","custom")}}else if(id){{try{{localStorage.removeItem("{V5049_THEME_SELECTION_KEY}")}}catch(e){{}}}}}})();</script>\n'''


def _v5049_runtime_theme_script(settings=None):
    payload = json.dumps(_v5049_theme_client_payload(settings), separators=(",", ":"), sort_keys=True)
    return f'''
<script>
(function(){{
  var themes={payload};
  var key="{V5049_THEME_SELECTION_KEY}";
  var select=document.getElementById("simple-theme-select");
  function read(){{try{{return localStorage.getItem(key)||""}}catch(e){{return""}}}}
  function write(id){{try{{if(id)localStorage.setItem(key,id);else localStorage.removeItem(key)}}catch(e){{}}}}
  function useCore(){{document.documentElement.removeAttribute("data-custom-theme");if(typeof applyTheme==="function")applyTheme(typeof readThemeMode==="function"?readThemeMode():"auto",false);if(select)select.value=""}}
  function useCustom(id,persist){{if(!themes[id]){{if(persist)write("");useCore();return}}if(persist)write(id);document.documentElement.setAttribute("data-custom-theme",id);document.documentElement.setAttribute("data-theme",themes[id]);document.documentElement.setAttribute("data-theme-mode","custom");document.querySelectorAll('.theme-switch button[data-theme-mode]').forEach(function(btn){{btn.classList.remove("active")}});if(select)select.value=id}}
  if(select)select.addEventListener("change",function(){{if(this.value)useCustom(this.value,true);else{{write("");useCore()}}}});
  document.addEventListener("click",function(ev){{var core=ev.target.closest('.theme-switch button[data-theme-mode]');if(core){{write("");document.documentElement.removeAttribute("data-custom-theme");if(select)select.value=""}}}},true);
  window.addEventListener("storage",function(ev){{if(ev.key===key){{var id=read();if(id)useCustom(id,false);else useCore()}}}});
  var current=read();if(current)useCustom(current,false);else useCore();
}})();
</script>
'''


def _v5049_admin_theme_content(settings, message="", error=""):
    preset_cards = []
    enabled = set(settings["enabled_presets"])
    for theme_id, theme in V5049_THEME_PRESETS.items():
        checked = " checked" if theme_id in enabled else ""
        preset_cards.append(f'''
        <label class="simple-preset-card">
          <input type="checkbox" name="preset_{escape(theme_id, quote=True)}" value="1"{checked}>
          <span class="simple-preset-swatch" style="--p-bg:{theme['bg']};--p-panel:{theme['panel']};--p-soft:{theme['panel_soft']};--p-brand:{theme['brand']};--p-rx:{theme['rx']};--p-tx:{theme['tx']};--p-text:{theme['text']}"><i></i><b></b><em></em><u></u></span>
          <span class="simple-preset-copy"><b>{escape(theme['name'])}</b><small>{escape(theme['description'])}</small><span>{escape(theme['base_mode'].title())} · {escape(theme['density'].title())} · HD / 2K / 4K</span></span>
        </label>''')
    custom = settings["custom"]
    color_labels = {
        "bg": "Background", "panel": "Panel", "text": "Text", "line": "Border",
        "brand": "Accent", "rx": "RX", "tx": "TX",
    }
    colors = []
    for key in V5049_THEME_COLOR_FIELDS:
        value = custom[key]
        colors.append(f'''<label>{color_labels[key]}<div><input type="color" name="{key}" value="{escape(value, quote=True)}"><code>{escape(value)}</code></div></label>''')
    return f'''
    <style>
    .simple-theme-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}}.simple-theme-head p{{max-width:820px}}
    .simple-preset-grid{{display:grid;grid-template-columns:repeat(2,minmax(300px,1fr));gap:11px;margin-top:14px}}.simple-preset-card{{display:grid;grid-template-columns:20px 90px 1fr;align-items:center;gap:12px;border:1px solid var(--line,#dfe5ec);border-radius:11px;padding:12px;background:var(--panel-soft,#f8fafc);cursor:pointer;transition:border-color .15s,transform .15s}}.simple-preset-card:hover{{border-color:color-mix(in srgb,var(--brand,#1677ff) 45%,var(--line,#dfe5ec));transform:translateY(-1px)}}.simple-preset-card>input{{width:17px;height:17px;margin:0}}.simple-preset-copy>b,.simple-preset-copy>small,.simple-preset-copy>span{{display:block}}.simple-preset-copy>small{{margin-top:4px;color:var(--muted,#667085);line-height:1.38}}.simple-preset-copy>span{{margin-top:7px;font-size:9px;font-weight:850;letter-spacing:.045em;text-transform:uppercase;color:var(--brand,#1677ff)}}
    .simple-preset-swatch{{height:58px;border-radius:8px;background:var(--p-bg);border:1px solid color-mix(in srgb,var(--p-text) 25%,var(--p-bg));padding:7px;display:grid;grid-template-columns:1.2fr .8fr;grid-template-rows:7px 1fr 5px;gap:5px;overflow:hidden}}.simple-preset-swatch i{{grid-column:1/-1;background:var(--p-brand);border-radius:2px}}.simple-preset-swatch b{{background:var(--p-panel);border-radius:3px}}.simple-preset-swatch em{{background:var(--p-soft);border-radius:3px}}.simple-preset-swatch u{{grid-column:1/-1;background:linear-gradient(90deg,var(--p-rx) 0 48%,transparent 48% 52%,var(--p-tx) 52% 100%);border-radius:2px;text-decoration:none}}
    .simple-custom-grid{{display:grid;grid-template-columns:repeat(3,minmax(160px,1fr));gap:11px;margin-top:14px}}.simple-custom-grid>label{{display:flex;flex-direction:column;gap:5px;font-size:11px;font-weight:800;color:var(--muted,#667085)}}.simple-custom-grid input,.simple-custom-grid select{{width:100%}}.simple-custom-enable{{display:flex!important;flex-direction:row!important;align-items:center;gap:8px!important;font-size:13px!important;color:var(--text,#111827)!important}}.simple-custom-enable input{{width:18px!important;height:18px}}
    .simple-color-grid{{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:9px;margin-top:13px}}.simple-color-grid label{{display:flex;flex-direction:column;gap:5px;font-size:11px;font-weight:800;color:var(--muted,#667085)}}.simple-color-grid label>div{{display:flex;align-items:center;gap:7px}}.simple-color-grid input[type=color]{{width:44px;height:34px;padding:2px}}.simple-color-grid code{{font-size:10px}}
    .simple-theme-actions{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:16px}}.simple-core-note{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px}}.simple-core-note div{{padding:10px;border:1px solid var(--line,#dfe5ec);border-radius:8px;background:var(--panel-soft,#f8fafc)}}.simple-core-note b,.simple-core-note span{{display:block}}.simple-core-note span{{font-size:10px;color:var(--muted,#667085);margin-top:3px;line-height:1.35}}
    @media(max-width:980px){{.simple-preset-grid{{grid-template-columns:1fr}}.simple-color-grid{{grid-template-columns:repeat(2,minmax(120px,1fr))}}.simple-core-note{{grid-template-columns:repeat(2,1fr)}}}}@media(max-width:620px){{.simple-preset-card{{grid-template-columns:20px 72px 1fr}}.simple-custom-grid,.simple-color-grid,.simple-core-note{{grid-template-columns:1fr}}}}
    </style>
    {f'<div class="success-box">{escape(message)}</div>' if message else ''}
    {f'<div class="error-box">{escape(error)}</div>' if error else ''}
    <form method="post" action="{url_for('admin_theme_manager')}">
      <input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}">
      <input type="hidden" name="action" value="save">
      <div class="card">
        <div class="simple-theme-head"><div><span class="eyebrow">VIRTINFRA APPEARANCE</span><h2>Theme settings</h2><p>Auto, Dark and Light remain original. Enable the complete VirtInfra presets users may select. Each preset already includes coordinated typography, metrics, panels, tables, charts and responsive HD, 2K and 4K sizing.</p></div></div>
        <div class="simple-core-note"><div><b>Auto</b><span>Original automatic mode</span></div><div><b>Dark</b><span>Original dark theme</span></div><div><b>Light</b><span>Original light theme</span></div><div><b>Responsive</b><span>Automatic HD, 2K and 4K scaling</span></div></div>
      </div>
      <div class="card"><div class="section-head"><div><h3>Ready-made VirtInfra themes</h3><p>Tick to show, untick to hide. Colors, text contrast, spacing and metric sizing are already balanced as one visual system.</p></div></div><div class="simple-preset-grid">{''.join(preset_cards)}</div></div>
      <div class="card"><div class="section-head"><div><h3>One simple Custom theme</h3><p>Optional. Keep customization small: base mode, density and seven core colors. The application derives the remaining surfaces and states automatically.</p></div></div>
        <div class="simple-custom-grid">
          <label class="simple-custom-enable"><input type="checkbox" name="custom_enabled" value="1"{' checked' if settings['custom_enabled'] else ''}>Show Custom theme to users</label>
          <label>Theme name<input name="custom_name" maxlength="40" value="{escape(custom['name'], quote=True)}"></label>
          <label>Base<select name="custom_base_mode"><option value="dark"{' selected' if custom['base_mode']=='dark' else ''}>Dark</option><option value="light"{' selected' if custom['base_mode']=='light' else ''}>Light</option></select></label>
          <label>Density<select name="custom_density"><option value="compact"{' selected' if custom['density']=='compact' else ''}>Compact</option><option value="normal"{' selected' if custom['density']=='normal' else ''}>Normal</option><option value="comfortable"{' selected' if custom['density']=='comfortable' else ''}>Comfortable</option></select></label>
        </div>
        <div class="simple-color-grid">{''.join(colors)}</div>
      </div>
      <div class="card"><div class="simple-theme-actions"><button type="submit">Save themes</button><span class="table-hint">Applies on the next page load. No Monitor restart or Agent update.</span></div></div>
    </form>
    <form method="post" action="{url_for('admin_theme_manager')}" onsubmit="return confirm('Reset preset visibility and the simple Custom theme?')">
      <input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}"><input type="hidden" name="action" value="reset"><button class="btn-danger" type="submit">Reset theme settings</button>
    </form>
    '''


@app.route("/admin/theme", methods=["GET", "POST"])
def admin_theme_manager():
    deny = require_admin()
    if deny:
        return deny
    settings = _v5049_theme_settings()
    message = str(request.args.get("message") or "").strip()[:260]
    error = ""
    if request.method == "POST":
        action = str(request.form.get("action") or "save").strip().lower()
        if action == "reset":
            settings = _v5049_save_theme_settings(_v5049_default_theme_settings())
            log_account_event("simple_theme_settings_updated", username=dashboard_username() or get_admin_username(), realm="admin", role="admin", detail="action=reset;version=4")
            return redirect(url_for("admin_theme_manager", message="Theme settings reset. Auto, Dark and Light were not changed."))
        if action != "save":
            return redirect(url_for("admin_theme_manager", message="Unknown theme action."))

        enabled = [theme_id for theme_id in V5049_THEME_PRESETS if request.form.get("preset_" + theme_id) == "1"]
        custom_raw = {
            "name": str(request.form.get("custom_name") or "").strip(),
            "base_mode": str(request.form.get("custom_base_mode") or "dark").strip().lower(),
            "density": str(request.form.get("custom_density") or "normal").strip().lower(),
        }
        errors = []
        if not custom_raw["name"]:
            errors.append("Custom theme name is required")
        if custom_raw["base_mode"] not in {"light", "dark"}:
            errors.append("Invalid Custom base mode")
        if custom_raw["density"] not in V5049_THEME_DENSITIES:
            errors.append("Invalid Custom density")
        fallback = _v5049_default_custom_theme()
        for key in V5049_THEME_COLOR_FIELDS:
            value = str(request.form.get(key) or "").strip().lower()
            if not (len(value) == 7 and value.startswith("#") and all(ch in "0123456789abcdef" for ch in value[1:])):
                errors.append("Invalid hexadecimal color: " + key)
                value = fallback[key]
            custom_raw[key] = value
        submitted = _v5049_normalize_theme_settings({
            "enabled_presets": enabled,
            "custom_enabled": request.form.get("custom_enabled") == "1",
            "custom": custom_raw,
        })
        if errors:
            content = _v5049_admin_theme_content(submitted, message=message, error="; ".join(errors))
            shell = '<div class="card admin-hero"><div><span class="eyebrow">CONTROL CENTER</span><h2>Administration</h2><p>Professional preset visibility and one simple Custom theme.</p></div></div>' + _v490_admin_nav("theme") + content
            return page("Admin · Themes", shell), 400
        settings = _v5049_save_theme_settings(submitted)
        detail = "presets=%s;custom=%s;version=4" % (len(settings["enabled_presets"]), int(settings["custom_enabled"]))
        log_account_event("simple_theme_settings_updated", username=dashboard_username() or get_admin_username(), realm="admin", role="admin", detail=detail)
        return redirect(url_for("admin_theme_manager", message="Theme choices saved."))

    content = _v5049_admin_theme_content(settings, message=message, error=error)
    shell = f'''
    <div class="card admin-hero"><div><span class="eyebrow">CONTROL CENTER</span><h2>Administration</h2><p>Professional VirtInfra presets and one optional Custom theme.</p></div><div class="admin-user-actions"><a class="btn" href="{url_for('index')}">Dashboard</a><a class="btn" href="{url_for('admin_logout')}">Logout</a></div></div>
    {_v490_admin_nav('theme')}
    {content}
    '''
    return page("Admin · Themes", shell)


_v5049_admin_nav_base = _v490_admin_nav


def _v490_admin_nav(active):
    html = _v5049_admin_nav_base(active)
    link = '<a class="%s" href="%s">Themes</a>' % (
        "active" if active == "theme" else "",
        escape(url_for("admin_theme_manager"), quote=True),
    )
    return html.replace("</nav>", link + "</nav>", 1)


_v5049_admin_overview_base = _v490_admin_overview


def _v490_admin_overview(stats):
    base = _v5049_admin_overview_base(stats)
    settings = _v5049_theme_settings()
    available = len(settings["enabled_presets"]) + int(settings["custom_enabled"])
    card = f'''
    <div class="card admin-section">
      <div class="section-head"><div><span class="eyebrow">THEMES</span><h3>Professional appearance choices</h3><p>Core Auto, Dark and Light remain original. VirtInfra presets include coordinated type, metrics, cards, tables and responsive HD, 2K and 4K sizing.</p></div><a class="btn" href="{url_for('admin_theme_manager')}">Theme settings</a></div>
      <div class="admin-kpis"><div><small>CORE</small><b>3 protected</b></div><div><small>PRESETS SHOWN</small><b>{len(settings['enabled_presets'])}</b></div><div><small>CUSTOM</small><b>{'Shown' if settings['custom_enabled'] else 'Hidden'}</b></div><div><small>USER CHOICES</small><b>{available + 3}</b></div><div><small>SCALING</small><b>HD · 2K · 4K</b></div></div>
    </div>
    '''
    return base + card


_page_v5049_theme_base = page


def page(title, content):
    response = _page_v5049_theme_base(title, content)
    try:
        settings = _v5049_theme_settings()
        html = response.get_data(as_text=True)
        original_switch = '''<div class="theme-switch" role="group" aria-label="Theme mode">
                    <button type="button" data-theme-mode="auto">Auto</button>
                    <button type="button" data-theme-mode="dark">Dark</button>
                    <button type="button" data-theme-mode="light">Light</button>
                </div>'''
        html = html.replace(original_switch, _v5049_theme_selector_html(settings), 1)
        marker = "</script>\n        <style>"
        if marker in html:
            html = html.replace(marker, "</script>" + _v5049_early_theme_script(settings) + "        <style>", 1)
        html = html.replace("</head>", _v5049_theme_css(settings) + "</head>", 1)
        html = html.replace("</body>", _v5049_runtime_theme_script(settings) + "</body>", 1)
        response.set_data(html)
    except Exception:
        app.logger.exception("Could not apply v50.4.9 theme settings")
    return response


# ---------------------------------------------------------------------------
