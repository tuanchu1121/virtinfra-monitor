# VirtInfra Monitor Theme Manager

## Open the manager

Sign in as an administrator and open:

```text
Admin -> Theme
```

Direct route:

```text
/admin/theme
```

## Built-in presets

- Neutral Blue, the production default
- Slate Indigo
- Emerald
- Graphite
- Warm Amber

Selecting a preset fills every Light, Dark and semantic color. Administrators may then adjust any color with the color picker; the palette becomes `Custom`.

## Customizable application colors

Light and Dark modes each expose:

- application background
- panel background
- soft panel and table-header background
- header background
- main text
- muted text
- border
- accent / primary action

Shared semantic colors:

- RX
- TX
- Success
- Warning
- Danger

All values are validated as six-digit hexadecimal colors before saving. Invalid values are rejected and the existing theme remains active.

## User appearance behavior

The administrator selects the default appearance: Auto, Light or Dark. Each signed-in user may still choose Auto, Light or Dark from the header. The user's browser choice overrides the administrator default and remains stored in local storage.

## Storage and activation

The configuration is stored under `application_theme_v1` in PostgreSQL `admin_settings`. Saving a theme increments the page-cache generation, so newly rendered pages use the palette immediately. No Monitor or Agent restart is required.

## Reset

Use `Reset default` to restore Neutral Blue. This changes only application appearance. It does not modify users, metrics, history, Abuse, Consumption or Agent configuration.
