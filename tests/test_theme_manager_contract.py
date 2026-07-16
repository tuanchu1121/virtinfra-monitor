#!/usr/bin/env python3
"""Static regression contract for protected core modes and custom themes."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "app.py"
SOURCE = APP.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(APP))


def need(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


required = [
    'V5047_THEME_SETTING_KEY = "custom_theme_library_v2"',
    'V5047_THEME_SELECTION_KEY = "virtinfra-theme-selection-v2"',
    'data-custom-theme',
    'custom-theme-select',
    'custom_theme_library_updated',
    '@app.route("/admin/theme", methods=["GET", "POST"])',
    'require_admin()',
    '"toggle"',
    '"duplicate"',
    '"delete"',
    '"reset"',
    'Core Auto, Light and Dark',
    'Auto, Light and Dark remain untouched',
    'bw-theme-mode',
    'V5047_THEME_MAX_ITEMS = 24',
]
for item in required:
    need(item in SOURCE, f"custom theme contract missing: {item}")

for key in (
    "virtinfra_ocean",
    "grafana_inspired",
    "zabbix_inspired",
    "datadog_inspired",
    "prometheus_inspired",
    "noc_high_contrast",
    "dense_operations",
):
    need(f'"{key}": {{' in SOURCE, f"built-in theme template missing: {key}")

# Original core controls must remain explicit and protected.
need(SOURCE.count('data-theme-mode="auto"') >= 2, "Auto core theme control missing")
need(SOURCE.count('data-theme-mode="dark"') >= 2, "Dark core theme control missing")
need(SOURCE.count('data-theme-mode="light"') >= 2, "Light core theme control missing")
need("localStorage.getItem('bw-theme-mode') || 'auto'" in SOURCE, "core theme preference was rewritten")
need("localStorage.getItem('bw-theme-mode') || %s" not in SOURCE, "admin default still overwrites core mode")

# Custom CSS must be scoped, not injected globally into Light/Dark.
block = SOURCE[SOURCE.index("V5047_THEME_SETTING_KEY"):]
need('html[data-custom-theme="%s"]' in block, "custom CSS selector is not scoped")
need('html[data-theme="light"] {' not in block, "custom manager overwrites core Light")
need('html[data-theme="dark"] {' not in block, "custom manager overwrites core Dark")
need("application_theme_v1" not in block, "legacy shared-palette setting still active")
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
need("set_admin_setting(V5047_THEME_SETTING_KEY" in block, "PostgreSQL persistence missing")

print("PASS: protected Auto/Light/Dark and admin-published custom theme library")
