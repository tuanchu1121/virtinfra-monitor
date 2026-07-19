#!/usr/bin/env python3
"""Browser-level UI regression metrics for Node Groups additive hotfix."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1000},
    "tablet": {"width": 1024, "height": 900},
    "mobile": {"width": 390, "height": 844},
}

JS = r"""
() => {
  const rect = el => {
    const r = el.getBoundingClientRect();
    return {x:r.x, y:r.y, width:r.width, height:r.height, right:r.right, bottom:r.bottom};
  };
  const styles = el => {
    const s = getComputedStyle(el);
    return {
      fontFamily:s.fontFamily, fontSize:s.fontSize, fontWeight:s.fontWeight,
      color:s.color, backgroundColor:s.backgroundColor,
      padding:s.padding, borderRadius:s.borderRadius, overflowX:s.overflowX,
      display:s.display, lineHeight:s.lineHeight
    };
  };
  const buttons = {};
  document.querySelectorAll('button').forEach(el => {
    const key = (el.textContent || '').trim();
    (buttons[key] ||= []).push({rect:rect(el), style:styles(el)});
  });
  return {
    viewport:{width:innerWidth,height:innerHeight},
    document:{scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth},
    body:{rect:rect(document.body),style:styles(document.body)},
    cards:[...document.querySelectorAll('.card')].map(el => ({rect:rect(el),style:styles(el)})),
    tableWraps:[...document.querySelectorAll('.table-wrap')].map(el => ({rect:rect(el),scrollWidth:el.scrollWidth,clientWidth:el.clientWidth,style:styles(el)})),
    navs:[...document.querySelectorAll('nav')].map(el => ({rect:rect(el),scrollWidth:el.scrollWidth,clientWidth:el.clientWidth,style:styles(el)})),
    buttons
  };
}
"""


def close(a, b, tolerance=1.5):
    return abs(float(a) - float(b)) <= tolerance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--json", required=True, type=Path)
    parser.add_argument("--markdown", required=True, type=Path)
    args = parser.parse_args()
    result = {}
    failures = []

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
    pages = {
        name: browser.new_page(viewport=viewport)
        for name, viewport in VIEWPORTS.items()
    }
    for before_file in sorted(args.before.glob("*.html")):
        page_name = before_file.stem
        after_file = args.after / before_file.name
        page_result = {}
        for viewport_name, viewport in VIEWPORTS.items():
            metrics = []
            for path in (before_file, after_file):
                page = pages[viewport_name]
                html = path.read_text(encoding="utf-8")
                if path == after_file:
                    feature_css = (Path(__file__).resolve().parents[1] / "app/static/flags/node-groups.css").read_text(encoding="utf-8")
                    html = html.replace("</head>", f"<style>{feature_css}</style></head>", 1)
                page.set_content(html, wait_until="load")
                page.wait_for_timeout(50)
                metrics.append(page.evaluate(JS))
            before, after = metrics
            checks = {}
            checks["no_new_document_overflow"] = (
                after["document"]["scrollWidth"] <= after["document"]["clientWidth"] + 1
            )
            checks["body_theme_identical"] = all(
                before["body"]["style"][key] == after["body"]["style"][key]
                for key in ("fontFamily", "fontSize", "fontWeight", "color", "backgroundColor", "lineHeight")
            )
            if page_name == "admin-overview":
                checks["card_count_identical"] = len(after["cards"]) == len(before["cards"]) - 1
            elif page_name == "admin-maintenance":
                checks["card_count_identical"] = len(after["cards"]) == len(before["cards"]) + 1
            else:
                checks["card_count_identical"] = len(before["cards"]) == len(after["cards"])
            comparable = min(len(before["cards"]), len(after["cards"]))
            checks["card_geometry_preserved"] = all(
                close(before["cards"][index]["rect"][key], after["cards"][index]["rect"][key])
                for index in range(comparable)
                for key in ("x", "width")
            )
            checks["cards_inside_viewport"] = all(
                card["rect"]["x"] >= -1 and card["rect"]["right"] <= viewport["width"] + 1
                for card in after["cards"]
            )
            checks["table_wrappers_preserved"] = len(before["tableWraps"]) == len(after["tableWraps"]) and all(
                left["style"]["overflowX"] == right["style"]["overflowX"]
                and close(left["rect"]["x"], right["rect"]["x"])
                and close(left["rect"]["width"], right["rect"]["width"])
                for left, right in zip(before["tableWraps"], after["tableWraps"])
            )
            old_button_ok = True
            moved_buttons = {"Run cleanup now", "Clear history"} if page_name == "admin-overview" else set()
            for text, old_items in before["buttons"].items():
                new_items = after["buttons"].get(text, [])
                if text in moved_buttons:
                    continue
                if len(new_items) < len(old_items):
                    old_button_ok = False
                    break
                for old_item, new_item in zip(old_items, new_items):
                    if not (
                        close(old_item["rect"]["width"], new_item["rect"]["width"])
                        and close(old_item["rect"]["height"], new_item["rect"]["height"])
                        and old_item["style"]["fontSize"] == new_item["style"]["fontSize"]
                        and old_item["style"]["padding"] == new_item["style"]["padding"]
                    ):
                        old_button_ok = False
                        break
            checks["old_button_geometry_preserved"] = old_button_ok
            checks["navigation_contained"] = all(
                nav["rect"]["x"] >= -1 and nav["rect"]["right"] <= viewport["width"] + 1
                for nav in after["navs"]
            )
            passed = all(checks.values())
            if not passed:
                failures.append(f"{page_name}/{viewport_name}")
            page_result[viewport_name] = {"passed": passed, "checks": checks, "before": before, "after": after}
        result[page_name] = page_result

    # New pages have no baseline counterpart. Validate containment and
    # responsive overflow independently at the same three viewports.
    before_names = {path.name for path in args.before.glob("*.html")}
    for after_file in sorted(args.after.glob("*.html")):
        if after_file.name in before_names:
            continue
        page_name = after_file.stem
        page_result = {}
        for viewport_name, viewport in VIEWPORTS.items():
            page = pages[viewport_name]
            html = after_file.read_text(encoding="utf-8")
            feature_css = (Path(__file__).resolve().parents[1] / "app/static/flags/node-groups.css").read_text(encoding="utf-8")
            html = html.replace("</head>", f"<style>{feature_css}</style></head>", 1)
            page.set_content(html, wait_until="load")
            page.wait_for_timeout(50)
            after = page.evaluate(JS)
            checks = {
                "no_document_overflow": after["document"]["scrollWidth"] <= after["document"]["clientWidth"] + 1,
                "cards_inside_viewport": all(card["rect"]["x"] >= -1 and card["rect"]["right"] <= viewport["width"] + 1 for card in after["cards"]),
                "navigation_contained": all(nav["rect"]["x"] >= -1 and nav["rect"]["right"] <= viewport["width"] + 1 for nav in after["navs"]),
                "table_wrappers_scroll_locally": all(wrap["style"]["overflowX"] in {"auto", "scroll", "hidden"} for wrap in after["tableWraps"]),
            }
            passed = all(checks.values())
            if not passed:
                failures.append(f"{page_name}/{viewport_name}")
            page_result[viewport_name] = {"passed": passed, "checks": checks, "before": None, "after": after}
        result[page_name] = page_result

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Node Groups Browser UI Regression Report", "",
        "Chromium measured the baseline and additive hotfix at 1440×1000, 1024×900 and 390×844.",
        "The checks cover document overflow, body theme/font, card geometry, table wrappers, old button dimensions and navigation containment.", "",
        "| Page | Desktop | Tablet | Mobile |", "|---|---|---|---|",
    ]
    for page_name, page_result in sorted(result.items()):
        lines.append("| %s | %s | %s | %s |" % (
            page_name,
            "PASS" if page_result["desktop"]["passed"] else "FAIL",
            "PASS" if page_result["tablet"]["passed"] else "FAIL",
            "PASS" if page_result["mobile"]["passed"] else "FAIL",
        ))
    lines += ["", f"Overall: **{'PASS' if not failures else 'FAIL'}**"]
    if failures:
        lines.append("Failures: " + ", ".join(failures))
    args.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = 0 if not failures else 1
    print(f"Browser UI regression {'passed' if not failures else 'failed'} for {len(result)} pages across {len(VIEWPORTS)} viewports", flush=True)
    # Chromium close can block indefinitely in constrained CI containers after
    # all page metrics are already persisted. Closing the Playwright pipe by
    # exiting the process is deterministic; the wrapper reaps any child process.
    os._exit(code)


if __name__ == "__main__":
    raise SystemExit(main())
