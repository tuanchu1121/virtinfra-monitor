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

    # R22 preserves the route contract while making the canonical Consumption
    # implementation explicit and keeping the legacy 2-hour writer retired.
    allowed_overrides = [
        {"endpoint": "bandwidth_consumption_page", "value": "bandwidth_consumption_page_r22"},
        {"endpoint": "push_bandwidth_consumption", "value": "push_bandwidth_consumption_retired"},
        {"endpoint": "admin_bandwidth_consumption_action", "value": "admin_bandwidth_consumption_action_r21"},
    ]
    assert all(item in actual["view_overrides"] for item in allowed_overrides)
    filtered_overrides = [item for item in actual["view_overrides"] if item not in allowed_overrides]
    assert filtered_overrides == CONTRACT["view_overrides"]

    expected_args = dict(CONTRACT["request_args"])
    expected_args["period"] += 2
    expected_args["tab"] += 1
    expected_args["sort"] += 1
    expected_args["order"] += 1
    assert dict(actual["request_args"]) == expected_args

    expected_form = dict(CONTRACT["request_form"])
    expected_form["action"] += 1  # R21 cleanup override keeps the existing endpoint
    # R22.5 intentionally extends the existing Maintenance POST endpoint. No
    # public route/API endpoint was added; only Super Admin form fields changed.
    expected_form["admin_password"] -= 1
    expected_form["confirm_text"] += 2
    expected_form["backup_id"] = 8
    expected_form["backup_options_present"] = 1
    expected_form["create_configuration_backup"] = 1
    expected_form["create_full_backup"] = 1
    assert dict(actual["request_form"]) == expected_form

    expected_urls = dict(CONTRACT["url_for_endpoints"])
    expected_urls["admin_bandwidth_consumption_action"] += 1
    expected_urls["bandwidth_consumption_page"] += 15
    expected_urls["node_page"] += 1
    expected_urls["admin_page"] -= 1  # consolidated Super Admin maintenance redirect
    assert dict(actual["url_for_endpoints"]) == expected_urls


def test_agent_matches_pinned_release_contract():
    actual = hashlib.sha256((ROOT / "deploy" / "agent" / "agent.py").read_bytes()).hexdigest()
    assert actual == CONTRACT["agent_sha256"]


def test_existing_postgresql_sql_matches_approved_release_contract():
    # The legacy aggregate digest predates the approved R22.1 fix to
    # 002_timescale.sql. Validate each protected migration against the
    # per-file release manifest instead, so an intentional fix does not make
    # preflight fail while any unexpected SQL edit is still detected exactly.
    approved = json.loads(
        (ROOT / "tests" / "contracts" / "node_groups_sql_hashes.json").read_text(
            encoding="utf-8"
        )
    )
    excluded = {
        "011_node_groups.sql",
        "012_node_groups_r6_safety.sql",
        "013_maintenance_queue_boolean.sql",
        "014_node_vm_consumption_rollups.sql",
        "015_consumption_ingest_preaggregation.sql",
        "016_configuration_backup_nuclear.sql",
        "017_vm_consumption_5m_slots.sql",
    }
    paths = [
        path
        for path in (ROOT / "postgres" / "sql").glob("*.sql")
        if path.name not in excluded
    ]
    assert paths
    for path in sorted(paths):
        rel = path.relative_to(ROOT).as_posix()
        assert rel in approved, f"missing approved SQL digest: {rel}"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == approved[rel], f"protected SQL changed: {rel}"


def test_node_groups_schema_is_additive_migration_011():
    path = ROOT / "postgres" / "sql" / "011_node_groups.sql"
    text = path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS node_groups" in text
    assert "CREATE TABLE IF NOT EXISTS node_group_memberships" in text
    assert "CREATE TABLE IF NOT EXISTS node_group_membership_history" in text
