#!/usr/bin/env python3
"""Pure runtime smoke test for the custom theme helpers without a database."""
from __future__ import annotations

import ast
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "app.py"
TREE = ast.parse(APP.read_text(encoding="utf-8"), filename=str(APP))

ASSIGNMENTS = {
    "V5047_THEME_SETTING_KEY",
    "V5047_THEME_SELECTION_KEY",
    "V5047_THEME_MAX_ITEMS",
    "V5047_THEME_COLOR_FIELDS",
    "V5047_THEME_FONT_PROFILES",
    "V5047_THEME_SHADOWS",
    "V5047_THEME_TEMPLATES",
}
FUNCTIONS = {
    "_v5047_valid_hex",
    "_v5047_slug",
    "_v5047_int",
    "_v5047_bool",
    "_v5047_template_theme",
    "_v5047_normalize_theme",
    "_v5047_default_theme_library",
    "_v5047_normalize_theme_library",
    "_v5047_enabled_themes",
    "_v5047_custom_theme_css",
    "_v5047_theme_client_payload",
    "_v5047_theme_selector_html",
    "_v5047_early_theme_script",
    "_v5047_runtime_theme_script",
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
exec(compile(module, "<custom-theme-runtime>", "exec"), namespace)

themes = namespace["_v5047_default_theme_library"]()
assert len(themes) == 7
assert all(theme["enabled"] for theme in themes)
assert len({theme["id"] for theme in themes}) == 7

css = namespace["_v5047_custom_theme_css"](themes)
assert 'html[data-custom-theme="grafana-inspired"]' in css
assert 'html[data-custom-theme="noc-high-contrast"]' in css
assert "font-size:16px" in css
assert ".appearance-controls" in css

selector = namespace["_v5047_theme_selector_html"](themes)
assert selector.count('<option value="custom:') == 7
assert 'data-theme-mode="auto"' in selector
assert 'data-theme-mode="dark"' in selector
assert 'data-theme-mode="light"' in selector

early = namespace["_v5047_early_theme_script"](themes)
runtime = namespace["_v5047_runtime_theme_script"](themes)
assert "virtinfra-theme-selection-v2" in early
assert "virtinfra-theme-selection-v2" in runtime
assert "bw-theme-mode" not in runtime

bad = {
    "themes": [
        dict(themes[0], id="bad id", bg="not-a-color", base_font_size=999),
        dict(themes[1], id="bad id"),
    ]
}
normalized = namespace["_v5047_normalize_theme_library"](bad)
assert normalized[0]["id"] == "bad-id"
assert normalized[1]["id"] == "bad-id-2"
assert normalized[0]["base_font_size"] == 18
assert normalized[0]["bg"] == themes[0]["bg"]

hidden = [dict(theme, enabled=False) for theme in themes]
assert namespace["_v5047_theme_selector_html"](hidden).count('<option value="custom:') == 0
assert 'data-custom-theme="' not in namespace["_v5047_custom_theme_css"](hidden)

print("PASS: custom theme runtime helpers, seven templates, scoped CSS and selector payload")
