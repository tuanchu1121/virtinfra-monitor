#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from bs4 import BeautifulSoup

REQUIRED_GROUP_FILTERS = {
    "admin-nodes", "admin-vms", "dashboard", "top-vm", "node-health",
    "storage-io", "consumption", "vm-abuse",
}
EXPECTED_MONITORING_NAV = [
    "Dashboard", "Node Groups", "Top VM", "Node Health",
    "Storage I/O", "Consumption", "VM Abuse",
]

ALLOWED_NEW_CLASSES = {
    "node-group-badge", "node-group-flag", "node-group-flag-empty",
    "fi", "data-node-group",
}


def texts(nodes):
    return [node.get_text(" ", strip=True) for node in nodes]


def header_texts(nodes):
    """Normalize only the additive sort direction marker, not the label."""
    return [node.get_text(" ", strip=True).removesuffix(" ↑").removesuffix(" ↓") for node in nodes]


def is_subsequence(old, new):
    it = iter(new)
    return all(any(item == candidate for candidate in it) for item in old)


def style_hashes(soup):
    return [hashlib.sha256((tag.string or tag.get_text()).encode()).hexdigest() for tag in soup.find_all("style")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--json", required=True, type=Path)
    parser.add_argument("--markdown", required=True, type=Path)
    args = parser.parse_args()
    results = {}
    failures = []

    for before_file in sorted(args.before.glob("*.html")):
        name = before_file.stem
        after_file = args.after / before_file.name
        if not after_file.exists():
            failures.append(f"{name}: missing after snapshot")
            continue
        before = BeautifulSoup(before_file.read_text(encoding="utf-8"), "html.parser")
        after = BeautifulSoup(after_file.read_text(encoding="utf-8"), "html.parser")
        item = {}
        item["card_count_before"] = len(before.select(".card"))
        item["card_count_after"] = len(after.select(".card"))
        item["cards_unchanged"] = item["card_count_before"] == item["card_count_after"]

        old_headers = header_texts(before.find_all("th"))
        new_headers = header_texts(after.find_all("th"))
        item["old_table_headers_preserved"] = is_subsequence(old_headers, new_headers)
        item["headers_before"] = old_headers
        item["headers_after"] = new_headers

        old_buttons = Counter(texts(before.find_all("button")))
        new_buttons = Counter(texts(after.find_all("button")))
        item["old_buttons_preserved"] = all(
            new_buttons[key] >= count for key, count in old_buttons.items()
        )

        old_filters = [tag.get("name") for tag in before.select("form.search [name], form.storage-search-bar [name], form.v5058c-toolbar [name], form.abuse-filter [name]") if tag.get("name")]
        new_filters = [tag.get("name") for tag in after.select("form.search [name], form.storage-search-bar [name], form.v5058c-toolbar [name], form.abuse-filter [name]") if tag.get("name")]
        item["old_filters_preserved"] = all(Counter(new_filters)[key] >= count for key, count in Counter(old_filters).items())
        item["group_filter_count"] = len(after.select('select[name="group"]'))
        item["required_group_filter_present"] = name not in REQUIRED_GROUP_FILTERS or item["group_filter_count"] == 1

        item["style_blocks_identical"] = style_hashes(before) == style_hashes(after)
        item["table_wrap_preserved"] = len(after.select(".table-wrap")) >= len(before.select(".table-wrap"))
        item["new_inline_table_width"] = any("width" in (table.get("style") or "").lower() for table in after.find_all("table")) and not any("width" in (table.get("style") or "").lower() for table in before.find_all("table"))

        old_main_nav = texts(before.select("nav.main-nav a"))
        new_main_nav = texts(after.select("nav.main-nav a"))
        old_admin_nav = texts(before.select("nav.admin-tabs a"))
        new_admin_nav = texts(after.select("nav.admin-tabs a"))
        item["monitoring_navigation_exact"] = new_main_nav == EXPECTED_MONITORING_NAV
        item["admin_navigation_preserved"] = old_admin_nav == new_admin_nav
        item["old_navigation_preserved"] = (
            item["monitoring_navigation_exact"] and item["admin_navigation_preserved"]
        )
        if name.startswith("admin-"):
            try:
                item["node_groups_nav_position"] = (
                    new_admin_nav.index("Node Groups") + 1 == new_admin_nav.index("Nodes")
                )
            except ValueError:
                item["node_groups_nav_position"] = False
        else:
            item["node_groups_nav_position"] = True

        checks = [
            "cards_unchanged", "old_table_headers_preserved", "old_buttons_preserved",
            "old_filters_preserved", "required_group_filter_present", "style_blocks_identical",
            "table_wrap_preserved", "old_navigation_preserved", "node_groups_nav_position",
        ]
        item["passed"] = all(item[key] for key in checks) and not item["new_inline_table_width"]
        if not item["passed"]:
            failures.append(name)
        results[name] = item

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Node Groups UI Regression Report", "",
        "The comparison uses deterministic HTML snapshots with the same seeded inventory and fixed time.",
        "All original inline `<style>` blocks must remain byte-identical. Existing cards, headers, buttons, filters, navigation entries and table wrappers must be preserved.", "",
        "| Page | Cards | Old headers | Old buttons | Old filters | Group filter | CSS | Navigation | Result |",
        "|---|---:|---|---|---|---:|---|---|---|",
    ]
    for name, item in sorted(results.items()):
        lines.append(
            f"| {name} | {item['card_count_before']}→{item['card_count_after']} | "
            f"{'PASS' if item['old_table_headers_preserved'] else 'FAIL'} | "
            f"{'PASS' if item['old_buttons_preserved'] else 'FAIL'} | "
            f"{'PASS' if item['old_filters_preserved'] else 'FAIL'} | {item['group_filter_count']} | "
            f"{'IDENTICAL' if item['style_blocks_identical'] else 'CHANGED'} | "
            f"{'PASS' if item['old_navigation_preserved'] and item['node_groups_nav_position'] else 'FAIL'} | "
            f"{'PASS' if item['passed'] else 'FAIL'} |"
        )
    lines += ["", f"Overall: **{'PASS' if not failures else 'FAIL'}**"]
    if failures:
        lines.append("Failures: " + ", ".join(failures))
    args.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if failures:
        print("UI regression failed:", ", ".join(failures))
        return 1
    print(f"UI regression passed for {len(results)} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
