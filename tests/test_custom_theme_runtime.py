#!/usr/bin/env python3
"""Pure runtime smoke test for simple theme helpers without a database."""
from __future__ import annotations

import ast
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "app.py"
TREE = ast.parse(APP.read_text(encoding="utf-8"), filename=str(APP))

ASSIGNMENTS = {
    "V5048_THEME_SETTING_KEY",
    "V5048_THEME_SELECTION_KEY",
    "V5048_CUSTOM_THEME_ID",
    "V5048_THEME_COLOR_FIELDS",
    "V5048_THEME_DENSITIES",
    "V5048_THEME_PRESETS",
}
FUNCTIONS = {
    "_v5048_valid_hex",
    "_v5048_bool",
    "_v5048_default_custom_theme",
    "_v5048_default_theme_settings",
    "_v5048_normalize_custom_theme",
    "_v5048_normalize_theme_settings",
    "_v5048_available_themes",
    "_v5048_theme_css",
    "_v5048_theme_selector_html",
    "_v5048_theme_client_payload",
    "_v5048_early_theme_script",
    "_v5048_runtime_theme_script",
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
exec(compile(module, "<simple-theme-runtime>", "exec"), namespace)

settings = namespace["_v5048_default_theme_settings"]()
assert len(settings["enabled_presets"]) == 5
assert settings["custom_enabled"] is False

themes = namespace["_v5048_available_themes"](settings)
assert len(themes) == 5
assert {theme["id"] for theme in themes} == {
    "virtinfra-ocean", "grafana-inspired", "zabbix-inspired", "prometheus-inspired", "noc-high-contrast"
}

css = namespace["_v5048_theme_css"](settings)
assert 'html[data-custom-theme="grafana-inspired"]' in css
assert 'html[data-custom-theme="noc-high-contrast"]' in css
assert ".appearance-controls" in css

selector = namespace["_v5048_theme_selector_html"](settings)
assert selector.count('<option value="') == 6  # placeholder + five presets
assert 'data-theme-mode="auto"' in selector
assert 'data-theme-mode="dark"' in selector
assert 'data-theme-mode="light"' in selector
assert 'id="simple-theme-select"' in selector

custom_settings = namespace["_v5048_normalize_theme_settings"]({
    "enabled_presets": ["grafana-inspired"],
    "custom_enabled": True,
    "custom": {
        "name": "My Theme",
        "base_mode": "light",
        "density": "compact",
        "bg": "#f8fafc", "panel": "#ffffff", "text": "#111827", "line": "#d1d5db",
        "brand": "#2563eb", "rx": "#0284c7", "tx": "#ea580c",
    },
})
custom_themes = namespace["_v5048_available_themes"](custom_settings)
assert len(custom_themes) == 2
assert custom_themes[-1]["id"] == "simple-custom"
assert custom_themes[-1]["name"] == "My Theme"
assert custom_themes[-1]["density"] == "compact"

bad = namespace["_v5048_normalize_theme_settings"]({
    "enabled_presets": ["bad", "grafana-inspired", "grafana-inspired"],
    "custom_enabled": "yes",
    "custom": {"name": "", "base_mode": "wrong", "density": "giant", "bg": "bad"},
})
assert bad["enabled_presets"] == ["grafana-inspired"]
assert bad["custom_enabled"] is True
assert bad["custom"]["base_mode"] == "dark"
assert bad["custom"]["density"] == "normal"
assert bad["custom"]["bg"] == "#0b1220"

early = namespace["_v5048_early_theme_script"](custom_settings)
runtime = namespace["_v5048_runtime_theme_script"](custom_settings)
assert "virtinfra-theme-selection-v3" in early
assert "virtinfra-theme-selection-v3" in runtime
assert "simple-custom" in early
assert "bw-theme-mode" not in runtime

hidden = namespace["_v5048_normalize_theme_settings"]({"enabled_presets": [], "custom_enabled": False})
assert namespace["_v5048_theme_selector_html"](hidden).count('<option value="') == 1
assert 'data-custom-theme="' not in namespace["_v5048_theme_css"](hidden)

print("PASS: simple preset selector, one custom slot, scoped CSS and browser choice")
