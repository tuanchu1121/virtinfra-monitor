#!/usr/bin/env python3
"""Regression contract for the compact neutral Consumption node layout."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "app.py"
SOURCE = APP.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(APP))


def fail(message: str) -> None:
    raise AssertionError(message)


# Difference values must remain compact and deterministic.
formatters = [
    node
    for node in TREE.body
    if isinstance(node, ast.FunctionDef) and node.name == "_v5030_fmt_signed"
]
if len(formatters) != 1:
    fail(f"expected one _v5030_fmt_signed function, found {len(formatters)}")
segment = ast.get_source_segment(SOURCE, formatters[0]) or ""
for token in ('"MB"', '"GB"', '"TB"', ':.2f'):
    if token not in segment:
        fail(f"Difference formatter is missing {token}")
if 'human(value)' in segment:
    fail("Difference formatter regressed to generic byte formatting")

# The main list should show only Public IP, not a second Private IP pill.
if 'title="Copy Public IP"' not in SOURCE:
    fail("Consumption Public IP copy action is missing")
if 'title="Copy Private IP"' in SOURCE:
    fail("Consumption main list still renders a Private IP copy action")

start = SOURCE.find('<style id="v5030-bandwidth-consumption-css">')
end = SOURCE.find('</style>', start)
if start < 0 or end < 0:
    fail("Consumption stylesheet block not found")
css = SOURCE[start:end]
if 'background:var(--panel,#fff)' not in css:
    fail("Consumption cards no longer use the application panel background")
for old_color in ('#eff6ff', '#f5f3ff', '#ecfdf3', '#fff7ed', '#fff1f3'):
    if old_color in css:
        fail(f"bright pastel Consumption background remains: {old_color}")

print("PASS: Consumption neutral UI, Public-IP-only row and compact Difference units")
