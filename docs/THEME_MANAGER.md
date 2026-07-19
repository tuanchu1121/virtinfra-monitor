# VirtInfra Monitor themes

## Simple behavior

The dashboard always keeps the original core choices:

- `Auto`
- `Dark`
- `Light`

Admin settings never overwrite those three modes.

The Admin page only controls which additional VirtInfra presets appear to users. Every browser keeps its own selection. If a preset is hidden, the browser safely returns to its previous Auto, Dark or Light mode.

## Open settings

```text
Admin -> Themes
```

Direct route:

```text
/admin/theme
```

## Ready-made VirtInfra presets

Admin enables or hides these fixed themes with checkboxes:

- `VirtInfra Core`: balanced navy for daily operations
- `Midnight Signal`: deep blue-black with crisp telemetry
- `Arctic Console`: clean cool light interface
- `Graphite Edge`: compact neutral graphite
- `NOC Vision`: high contrast and larger metrics for wall displays

There is no create, duplicate, delete or per-theme publishing workflow. The presets already coordinate background, text, muted text, borders, cards, tables, metric weight, numeric alignment, RX/TX, chart line width, density and responsive sizing.

Responsive profiles automatically adjust spacing and metric size for common HD, 2K and 4K viewports. SVG charts remain vector sharp, and operational values use tabular lining numerals so columns stay aligned.

## One Custom theme

There is exactly one optional Custom theme. Admin can set:

- displayed name
- Light or Dark base
- Compact, Normal or Comfortable density
- background
- panel
- text
- border
- accent
- RX
- TX

The application derives soft panels, table headers, hover states, status colors, shadows, chart width and responsive sizing automatically. Users can select Custom but cannot edit it.

## Storage

Settings are stored in PostgreSQL `admin_settings` under:

```text
simple_theme_settings_v4
```

The user's additional-theme choice is stored in the browser under:

```text
virtinfra-theme-selection-v4
```

The original core preference remains separate:

```text
bw-theme-mode
```

Release 50.4.9 migrates the previous simple selector settings and browser choice when available. Saving settings clears the rendered-page cache. No Monitor restart or Agent update is required.
