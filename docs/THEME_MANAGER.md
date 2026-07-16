# VirtInfra Monitor Theme Manager

## Behavior model

The dashboard always keeps the three protected core choices:

- `Auto`
- `Light`
- `Dark`

These use the original VirtInfra Monitor CSS and are never overwritten by Admin settings.

Administrators manage a separate custom theme library. Only custom themes marked as published appear in the dashboard theme selector. Dashboard users may select a published custom theme, but they cannot create, edit, publish, hide, duplicate, or delete themes.

Each browser stores its own selection. Choosing or removing a custom theme does not erase the browser's existing Auto, Light, or Dark preference. If an administrator hides or deletes a theme that a browser was using, that browser automatically falls back to its protected core preference.

## Open the manager

Sign in as an administrator and open:

```text
Admin -> Themes
```

Direct route:

```text
/admin/theme
```

## Built-in custom templates

The library starts with original VirtInfra implementations inspired by common monitoring aesthetics:

- VirtInfra Ocean
- Grafana Inspired
- Zabbix Inspired
- Datadog Inspired
- Prometheus Inspired
- NOC High Contrast
- Dense Operations

No vendor logos, trademarks, copied stylesheets, or external theme assets are included.

## Admin actions

An administrator can:

- create a theme from a built-in template
- edit a theme
- publish or hide a theme from dashboard users
- duplicate a theme
- delete a theme
- restore the built-in custom theme library

The protected Auto, Light, and Dark choices cannot be deleted or edited.

## Custom controls

Each custom theme has its own:

- fixed Light or Dark base appearance
- background, panel, soft panel, header, text, muted text, border, and accent colors
- RX, TX, Success, Warning, and Danger colors
- font profile
- base, table, and small text sizes
- table row height
- card padding
- border radius
- shadow strength
- chart line width

All colors are validated as six-digit hexadecimal values. Numeric fields are range checked server-side.

## Storage and activation

The library is stored in PostgreSQL `admin_settings` under:

```text
custom_theme_library_v2
```

Saving any theme action increments the shared page-cache generation. Newly rendered pages receive the updated selector and CSS immediately. No Monitor or Agent restart is required.

The browser choice is stored in local storage under:

```text
virtinfra-theme-selection-v2
```

The original core preference remains stored separately under the existing:

```text
bw-theme-mode
```
