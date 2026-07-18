#!/usr/bin/env python3
"""Always-on regression contract for Consumption endpoint authentication."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app" / "app.py"
SOURCE = APP_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(APP_PATH))


def fail(message: str) -> None:
    raise AssertionError(message)


def route_paths(node: ast.FunctionDef) -> set[str]:
    paths: set[str] = set()
    for decorator in node.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        if not call or not call.args:
            continue
        first = call.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            paths.add(first.value)
    return paths


matches = [
    node
    for node in TREE.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "push_bandwidth_consumption"
    and "/push/bandwidth-consumption" in route_paths(node)
]
if len(matches) != 1:
    fail(f"expected exactly one Consumption push route, found {len(matches)}")

route = matches[0]
loaded_names = {
    node.id
    for node in ast.walk(route)
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
}
if "API_TOKEN" in loaded_names:
    fail("Consumption route still references undefined legacy API_TOKEN")
if "valid_agent_token" not in loaded_names:
    fail("Consumption route no longer uses shared Agent token validation")

header_reads = []
for node in ast.walk(route):
    if not isinstance(node, ast.Call):
        continue
    func = node.func
    if not (
        isinstance(func, ast.Attribute)
        and func.attr == "get"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "headers"
    ):
        continue
    if node.args and isinstance(node.args[0], ast.Constant):
        header_reads.append(node.args[0].value)

if "X-Token" not in header_reads:
    fail("Consumption route no longer reads the X-Token header")

# The main push route must continue using the same canonical token contract.
main_matches = [
    node
    for node in TREE.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "push"
    and "/push" in route_paths(node)
]
if len(main_matches) != 1:
    fail(f"expected exactly one main /push route, found {len(main_matches)}")
main_loaded = {
    node.id
    for node in ast.walk(main_matches[0])
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
}
if "valid_agent_token" not in main_loaded:
    fail("main /push route no longer uses shared Agent token validation")

validators = [
    node for node in TREE.body
    if isinstance(node, ast.FunctionDef) and node.name == "_v5057_agent_tokens"
]
if len(validators) != 1:
    fail("shared Agent token set builder is missing")
validator_loaded = {
    node.id for node in ast.walk(validators[0])
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
}
if "TOKEN" not in validator_loaded:
    fail("shared Agent token validation no longer includes canonical TOKEN")
if "BW_MONITOR_LEGACY_TOKENS" not in SOURCE:
    fail("legacy Agent token compatibility environment is missing")

print("PASS: /push and Consumption share canonical plus legacy X-Token authentication")
