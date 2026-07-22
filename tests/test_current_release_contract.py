from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
VERSION = "50.5.9-prod-r22.12.3-slim-current-only"


def test_current_release_identity_and_snapshot_runtime():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == VERSION
    manifest = json.loads((ROOT / "app/runtime_layers/manifest.json").read_text(encoding="utf-8"))
    files = [str(item["file"]) for item in manifest]
    assert "48_vm_consumption_shared_snapshot.py" in files
    assert (ROOT / "postgres/sql/019_vm_consumption_shared_snapshot.sql").is_file()


def test_no_legacy_version_test_suites_or_contract_snapshots():
    tests = ROOT / "tests"
    assert not list(tests.glob("test_r[0-9]*.py"))
    assert not list(tests.glob("test_v[0-9]*.py"))
    assert not (tests / "contracts").exists()


def test_no_historical_release_logs_or_reports():
    patterns = (
        "VALIDATION_REPORT_R*.md",
        "R22*_CHANGESET.md",
        "BENCHMARK_REPORT_R*.md",
        "QUERY_PLAN_REPORT_R*.md",
        "EXPLAIN_ANALYZE_R*.json",
        "*.log",
    )
    for pattern in patterns:
        assert not list(ROOT.glob(pattern)), pattern
