#!/usr/bin/env python3
"""Static regression contract for effective professional presets, unified selector and one Custom theme."""
from __future__ import annotations

import ast
from pathlib import Path
from runtime_source import read_app_source

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "app.py"
SOURCE = read_app_source()
TREE = ast.parse(SOURCE, filename=str(APP))


def need(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


required = [
    'V5049_THEME_SETTING_KEY = "simple_theme_settings_v4"',
    'V5049_THEME_SELECTION_KEY = "virtinfra-theme-selection-v4"',
    'V5049_CUSTOM_THEME_ID = "simple-custom"',
    'data-custom-theme',
    'unified-theme-select',
    'simple_theme_settings_updated',
    '@app.route("/admin/theme", methods=["GET", "POST"])',
    'require_admin()',
    'Ready-made VirtInfra themes',
    'One simple Custom theme',
    'HD / 2K / 4K',
    'Save themes',
    'Reset theme settings',
    'bw-theme-mode',
    'font-variant-numeric:tabular-nums lining-nums',
    'text-rendering:geometricPrecision',
    '@media(min-width:1900px)',
    '@media(min-width:3000px)',
]
for item in required:
    need(item in SOURCE, f"professional theme contract missing: {item}")

for key in (
    "virtinfra-core",
    "midnight-signal",
    "arctic-console",
    "graphite-edge",
    "noc-vision",
):
    need(f'"{key}": {{' in SOURCE, f"built-in VirtInfra preset missing: {key}")

block = SOURCE[SOURCE.index("V5049_THEME_SETTING_KEY"):]
for forbidden in (
    "V5047_THEME_MAX_ITEMS",
    "custom_theme_library_v2",
    'action == "duplicate"',
    'action == "delete"',
    'action == "toggle"',
    "Create from monitoring presets",
    "Theme key cannot change",
    "Grafana Inspired",
    "Zabbix Inspired",
    "Prometheus Inspired",
    "Datadog Inspired",
):
    need(forbidden not in block, f"removed or copied theme concept remains: {forbidden}")

need(SOURCE.count('data-theme-mode="auto"') >= 2, "Auto core theme control missing")
need(SOURCE.count('data-theme-mode="dark"') >= 2, "Dark core theme control missing")
need(SOURCE.count('data-theme-mode="light"') >= 2, "Light core theme control missing")
need("localStorage.getItem('bw-theme-mode') || 'auto'" in SOURCE, "core theme preference was rewritten")
need('html[data-custom-theme="%s"]' in block, "custom CSS selector is not scoped")
need('html[data-theme="light"] {' not in block, "theme manager overwrites core Light")
need('html[data-theme="dark"] {' not in block, "theme manager overwrites core Dark")
need("eval(" not in block, "stored theme configuration must not be evaluated")

routes = []
for node in TREE.body:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not decorator.args:
            continue
        arg = decorator.args[0]
        if isinstance(arg, ast.Constant) and arg.value == "/admin/theme":
            routes.append(node.name)
need(routes == ["admin_theme_manager"], f"expected one /admin/theme route, got {routes}")

need('all(ch in "0123456789abcdef"' in block, "hex validation missing")
need("_v48140_bump_cache_generation()" in block, "page cache invalidation missing")
need("set_admin_setting(V5049_THEME_SETTING_KEY" in block, "PostgreSQL persistence missing")
need("V5049_LEGACY_PRESET_MAP" in block, "legacy preset compatibility map missing")

print("PASS: original VirtInfra presets, professional responsive styling, one Custom and protected core modes")
