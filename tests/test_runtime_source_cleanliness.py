from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "50.5.9-prod-r10-fresh-install-update-split"
LAYER_DIR = ROOT / "app/runtime_layers"
MANIFEST = LAYER_DIR / "manifest.json"


def _manifest() -> list[dict[str, object]]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_release_identity_and_history_reports_are_not_packaged() -> None:
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == EXPECTED_VERSION
    for obsolete in (
        "CLEANUP_REPORT_R9.md", "VALIDATION_REPORT_R9.md",
        "MODULAR_RUNTIME_ARCHITECTURE.md", "ROLLBACK_INSTRUCTIONS.md",
    ):
        assert not (ROOT / obsolete).exists()


def test_runtime_layers_are_hash_pinned_and_contiguous() -> None:
    expected_start = 1
    total = 0
    for item in _manifest():
        path = LAYER_DIR / str(item["file"])
        data = path.read_bytes()
        line_count = len(data.decode("utf-8").splitlines())
        assert int(item["start_line"]) == expected_start
        assert int(item["end_line"]) == expected_start + line_count - 1
        assert item["sha256"] == hashlib.sha256(data).hexdigest()
        expected_start += line_count
        total += line_count
    assert total == 31305


def test_runtime_contains_no_historical_release_banners_or_repeated_blank_runs() -> None:
    historical = re.compile(r"^#\\s*(?:VirtInfra Monitor\\s+)?v?\\d+(?:\\.\\d+)+(?:\\s|$)", re.I)
    for item in _manifest():
        path = LAYER_DIR / str(item["file"])
        text = path.read_text(encoding="utf-8")
        assert not any(historical.match(line.strip()) for line in text.splitlines()), path
        assert "\n\n\n" not in text, path


def test_superseded_route_body_is_only_a_registration_stub() -> None:
    path = LAYER_DIR / "32_performance_runtime.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "api_v1_performance_v48140"]
    assert len(defs) == 2
    first, final = defs
    assert first.decorator_list
    assert len(first.body) == 1 and isinstance(first.body[0], ast.Pass)
    assert len(final.body) > 1


def test_generated_cache_and_historical_audit_payloads_are_not_packaged() -> None:
    manifest = (ROOT / "SHA256SUMS").read_text(encoding="utf-8")
    assert "__pycache__" not in manifest
    assert ".pytest_cache" not in manifest
    assert not (ROOT / "audit").exists()
    for obsolete in (
        "DEAD_CODE_AUDIT_R8.md", "RUNTIME_EQUIVALENCE_R8.md",
        "REFACTOR_REPORT_R7.md", "TEST_RESULTS_R8_SAFE_DEAD_CODE_PRUNE.md",
    ):
        assert not (ROOT / obsolete).exists()
