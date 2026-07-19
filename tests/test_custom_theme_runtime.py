#!/usr/bin/env python3
"""Pure runtime smoke test for v50.4.9 professional theme helpers."""
from __future__ import annotations

import ast
import json
from html import escape
from pathlib import Path
from runtime_source import read_app_source

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "app.py"
TREE = ast.parse(read_app_source(), filename=str(APP))

ASSIGNMENTS = {
    "V5049_THEME_SETTING_KEY",
    "V5049_LEGACY_THEME_SETTING_KEY",
    "V5049_THEME_SELECTION_KEY",
    "V5049_LEGACY_SELECTION_KEY",
    "V5049_CUSTOM_THEME_ID",
    "V5049_THEME_COLOR_FIELDS",
    "V5049_THEME_DENSITIES",
    "V5049_THEME_PRESETS",
    "V5049_LEGACY_PRESET_MAP",
}
FUNCTIONS = {
    "_v5049_valid_hex",
    "_v5049_bool",
    "_v5049_default_custom_theme",
    "_v5049_default_theme_settings",
    "_v5049_normalize_custom_theme",
    "_v5049_migrate_legacy_settings",
    "_v5049_normalize_theme_settings",
    "_v5049_available_themes",
    "_v5049_theme_css",
    "_v5049_theme_selector_html",
    "_v5049_theme_client_payload",
    "_v5049_early_theme_script",
    "_v5049_runtime_theme_script",
}

selected: list[ast.stmt] = []
for node in TREE.body:
    if isinstance(node, ast.Assign):
        names = {target.id for target in node.targets if isinstance(target, ast.Name)}
        if names & ASSIGNMENTS:
            selected.append(node)
    elif isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
        selected.append(node)

module = ast.Module(body=selected, type_ignores=[])
ast.fix_missing_locations(module)
namespace = {"json": json, "escape": escape}
exec(compile(module, "<professional-theme-runtime>", "exec"), namespace)

settings = namespace["_v5049_default_theme_settings"]()
assert len(settings["enabled_presets"]) == 5
assert settings["custom_enabled"] is False

themes = namespace["_v5049_available_themes"](settings)
assert len(themes) == 5
assert {theme["id"] for theme in themes} == {
    "virtinfra-core", "midnight-signal", "arctic-console", "graphite-edge", "noc-vision"
}
assert all(theme["name"] for theme in themes)
assert all(theme["table_head"] and theme["row_hover"] and theme["shadow"] for theme in themes)

css = namespace["_v5049_theme_css"](settings)
assert 'html[data-custom-theme="virtinfra-core"]' in css
assert 'html[data-custom-theme="noc-vision"]' in css
assert ".appearance-controls" in css
assert "font-variant-numeric:tabular-nums lining-nums" in css
assert "@media(min-width:1900px)" in css
assert "@media(min-width:3000px)" in css
assert ".bwcons-groups" in css
assert "--vi-chart-line" in css

selector = namespace["_v5049_theme_selector_html"](settings)
assert selector.count('<option value="') == 8
assert 'id="unified-theme-select"' in selector
assert '<option value="mode:auto">Auto</option>' in selector
assert '<option value="mode:dark">Dark</option>' in selector
assert '<option value="mode:light">Light</option>' in selector
assert 'id="simple-theme-select"' not in selector
assert '<span>Style</span>' not in selector
assert '<optgroup label="Themes">' in selector

custom_settings = namespace["_v5049_normalize_theme_settings"]({
    "enabled_presets": ["midnight-signal"],
    "custom_enabled": True,
    "custom": {
        "name": "My Theme",
        "base_mode": "light",
        "density": "compact",
        "bg": "#f8fafc", "panel": "#ffffff", "text": "#111827", "line": "#d1d5db",
        "brand": "#2563eb", "rx": "#0284c7", "tx": "#ea580c",
    },
})
custom_themes = namespace["_v5049_available_themes"](custom_settings)
assert len(custom_themes) == 2
assert custom_themes[-1]["id"] == "simple-custom"
assert custom_themes[-1]["name"] == "My Theme"
assert custom_themes[-1]["density"] == "compact"
assert "color-mix" in custom_themes[-1]["panel_soft"]

bad = namespace["_v5049_normalize_theme_settings"]({
    "enabled_presets": ["bad", "midnight-signal", "midnight-signal"],
    "custom_enabled": "yes",
    "custom": {"name": "", "base_mode": "wrong", "density": "giant", "bg": "bad"},
})
assert bad["enabled_presets"] == ["midnight-signal"]
assert bad["custom_enabled"] is True
assert bad["custom"]["base_mode"] == "dark"
assert bad["custom"]["density"] == "normal"
assert bad["custom"]["bg"] == "#0b1220"

legacy = namespace["_v5049_migrate_legacy_settings"]({
    "enabled_presets": ["virtinfra-ocean", "zabbix-inspired", "noc-high-contrast"],
    "custom_enabled": False,
})
assert legacy["enabled_presets"] == ["virtinfra-core", "arctic-console", "noc-vision"]

early = namespace["_v5049_early_theme_script"](custom_settings)
runtime = namespace["_v5049_runtime_theme_script"](custom_settings)
assert "virtinfra-theme-selection-v4" in early
assert "virtinfra-theme-selection-v3" in early
assert "virtinfra-theme-selection-v4" in runtime
assert "simple-custom" in early
assert "bw-theme-mode" in runtime

hidden = namespace["_v5049_normalize_theme_settings"]({"enabled_presets": [], "custom_enabled": False})
assert namespace["_v5049_theme_selector_html"](hidden).count('<option value="') == 3
assert 'data-custom-theme="' not in namespace["_v5049_theme_css"](hidden)

print("PASS: professional preset suite, responsive CSS, migration, one Custom and browser choice")
