from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from pathlib import Path
from runtime_source import read_app_source

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "app.py"
CONTRACT = json.loads((ROOT / "tests" / "contracts" / "v5059_r1_runtime_contract.json").read_text(encoding="utf-8"))


def attr_chain(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def current_contract():
    tree = ast.parse(read_app_source(), filename=str(APP))
    routes, overrides, args, forms, values, url_endpoints, sort_maps = [], [], [], [], [], [], []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and attr_chain(dec.func) == "app.route" and dec.args):
                    continue
                first = dec.args[0]
                if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                    continue
                methods, endpoint = [], None
                for kw in dec.keywords:
                    if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        methods = [e.value for e in kw.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                    elif kw.arg == "endpoint" and isinstance(kw.value, ast.Constant):
                        endpoint = kw.value.value
                routes.append({"path": first.value, "function": node.name, "methods": methods or ["GET"], "endpoint": endpoint})
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and attr_chain(target.value) == "app.view_functions":
                    sl = target.slice
                    if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                        overrides.append({"endpoint": sl.value, "value": ast.unparse(node.value)})
                if isinstance(target, ast.Name) and ("sort" in target.id.lower() or target.id.lower().endswith("_keys")) and isinstance(node.value, ast.Dict):
                    keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
                    if keys:
                        sort_maps.append({"name": target.id, "keys": keys})
        if isinstance(node, ast.Call):
            chain = attr_chain(node.func)
            if not (node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                continue
            key = node.args[0].value
            if chain in {"request.args.get", "request.args.getlist"}:
                args.append(key)
            elif chain in {"request.form.get", "request.form.getlist"}:
                forms.append(key)
            elif chain in {"request.values.get", "request.values.getlist"}:
                values.append(key)
            elif chain == "url_for":
                url_endpoints.append(key)
    return {
        "routes": routes,
        "view_overrides": overrides,
        "request_args": [list(item) for item in sorted(Counter(args).items())],
        "request_form": [list(item) for item in sorted(Counter(forms).items())],
        "request_values": [list(item) for item in sorted(Counter(values).items())],
        "url_for_endpoints": [list(item) for item in sorted(Counter(url_endpoints).items())],
        "sort_maps": sort_maps,
    }


def digest_tree(paths):
    h = hashlib.sha256()
    for path in sorted(paths):
        rel = path.relative_to(ROOT).as_posix().encode()
        data = path.read_bytes()
        h.update(len(rel).to_bytes(4, "big"))
        h.update(rel)
        h.update(len(data).to_bytes(8, "big"))
        h.update(data)
    return h.hexdigest()


def test_route_endpoint_query_form_sort_contract_is_unchanged():
    actual = current_contract()
    for key in ("routes", "request_values", "sort_maps"):
        assert actual[key] == CONTRACT[key], f"runtime contract changed: {key}"

    # R20 changes only the effective Consumption view and retires the legacy
    # 2-hour writer without adding or removing any Flask route.
    allowed_overrides = [
        {"endpoint": "bandwidth_consumption_page", "value": "bandwidth_consumption_page_r20"},
        {"endpoint": "push_bandwidth_consumption", "value": "push_bandwidth_consumption_retired"},
    ]
    assert all(item in actual["view_overrides"] for item in allowed_overrides)
    filtered_overrides = [item for item in actual["view_overrides"] if item not in allowed_overrides]
    assert filtered_overrides == CONTRACT["view_overrides"]

    expected_args = dict(CONTRACT["request_args"])
    expected_args["period"] += 1
    expected_args["tab"] += 1
    assert dict(actual["request_args"]) == expected_args

    expected_form = dict(CONTRACT["request_form"])
    expected_form["confirm_text"] -= 1  # separate Consumption clear was removed
    assert dict(actual["request_form"]) == expected_form

    expected_urls = dict(CONTRACT["url_for_endpoints"])
    expected_urls["admin_bandwidth_consumption_action"] += 1
    expected_urls["admin_page"] -= 1
    expected_urls["bandwidth_consumption_page"] += 8
    expected_urls["node_page"] += 1
    assert dict(actual["url_for_endpoints"]) == expected_urls


def test_agent_matches_pinned_release_contract():
    actual = hashlib.sha256((ROOT / "deploy" / "agent" / "agent.py").read_bytes()).hexdigest()
    assert actual == CONTRACT["agent_sha256"]


def test_existing_postgresql_sql_is_byte_for_byte_unchanged():
    paths = [path for path in (ROOT / "postgres" / "sql").glob("*.sql") if path.name not in {"011_node_groups.sql", "012_node_groups_r6_safety.sql", "013_maintenance_queue_boolean.sql", "014_node_vm_consumption_rollups.sql"}]
    assert digest_tree(paths) == CONTRACT["postgres_sql_tree_sha256"]


def test_node_groups_schema_is_additive_migration_011():
    path = ROOT / "postgres" / "sql" / "011_node_groups.sql"
    text = path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS node_groups" in text
    assert "CREATE TABLE IF NOT EXISTS node_group_memberships" in text
    assert "CREATE TABLE IF NOT EXISTS node_group_membership_history" in text
