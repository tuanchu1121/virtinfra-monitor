# VirtInfra Monitor simple themes

## Behavior

The dashboard always keeps the original core choices:

- `Auto`
- `Dark`
- `Light`

Admin settings never overwrite these three themes.

The Admin page only controls which additional presets appear to users. Each user chooses a theme in their own browser. When a preset is hidden, browsers using it safely return to their previous Auto, Dark, or Light mode.

## Open settings

```text
Admin -> Themes
```

Direct route:

```text
/admin/theme
```

## Ready-made presets

Admin can show or hide these fixed presets with checkboxes:

- VirtInfra Ocean
- Grafana Inspired
- Zabbix Inspired
- Prometheus Inspired
- NOC High Contrast

The presets are fixed. There is no create, edit, duplicate, delete, or separate publish workflow.

## One Custom theme

There is exactly one optional Custom theme. Admin can set:

- displayed name
- Light or Dark base
- Compact, Normal, or Comfortable density
- background
- panel
- text
- border
- accent
- RX
- TX

Admin checks `Show Custom theme to users` to make it available. Users can only select it, not edit it.

## Storage

Settings are stored in PostgreSQL `admin_settings` under:

```text
simple_theme_settings_v3
```

The user's additional-theme choice is stored in the browser under:

```text
virtinfra-theme-selection-v3
```

The original core preference remains separate:

```text
bw-theme-mode
```

Saving settings clears the rendered-page cache. No Monitor restart or Agent update is required.
