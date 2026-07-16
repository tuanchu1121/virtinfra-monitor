#!/usr/bin/env python3
"""Static regression contract for the application-wide Theme Manager."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "app.py"
SOURCE = APP.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(APP))


def fail(message: str) -> None:
    raise AssertionError(message)


required_source = [
    'V5046_THEME_SETTING_KEY = "application_theme_v1"',
    'V5046_THEME_DEFAULT_PRESET = "neutral_blue"',
    '"neutral_blue"',
    '"slate_indigo"',
    '"emerald"',
    '"graphite"',
    '"warm_amber"',
    '@app.route("/admin/theme", methods=["GET", "POST"])',
    'set_admin_setting(V5046_THEME_SETTING_KEY',
    '_v48140_bump_cache_generation()',
    'localStorage.getItem(\'bw-theme-mode\') || %s',
    '--theme-bg:',
    '--theme-panel:',
    '--theme-brand:',
    '--theme-rx:',
    '--theme-tx:',
    'Theme Manager',
    'Reset default',
]
for needle in required_source:
    if needle not in SOURCE:
        fail(f"Theme Manager contract missing: {needle}")

if "eval(" in SOURCE[SOURCE.find("V5046_THEME_SETTING_KEY"):]:
    fail("Theme Manager must not evaluate stored configuration")

routes = []
for node in TREE.body:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not decorator.args:
            continue
        first = decorator.args[0]
        if isinstance(first, ast.Constant) and first.value == "/admin/theme":
            routes.append(node.name)
if routes != ["admin_theme_manager"]:
    fail(f"expected exactly one /admin/theme route, got {routes}")

preset_count = sum(1 for key in ("neutral_blue", "slate_indigo", "emerald", "graphite", "warm_amber") if f'"{key}": {{' in SOURCE)
if preset_count != 5:
    fail(f"expected 5 built-in presets, found {preset_count}")

if "all(ch in \"0123456789abcdef\"" not in SOURCE:
    fail("server-side six-digit hexadecimal validation is missing")

if "get_admin_setting(V5046_THEME_SETTING_KEY" not in SOURCE:
    fail("Theme Manager no longer reads from admin_settings")

print("PASS: application-wide Theme Manager presets, custom validation, persistence and CSS injection")
