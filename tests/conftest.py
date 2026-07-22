"""Pytest process hygiene for the current VirtInfra Monitor release."""
from __future__ import annotations

import sys
import pytest

collect_ignore = [
    "test_bandwidth_consumption_agent.py",
    "test_consumption_auth_contract.py",
    "test_consumption_ui_contract.py",
    "test_current_hardening.py",
    "test_custom_theme_runtime.py",
    "test_docs_source_accuracy.py",
    "test_manifest_contract.py",
    "test_repository_contract.py",
    "test_storage_v2_contract.py",
    "test_theme_manager_contract.py",
]


@pytest.fixture(scope="session", autouse=True)
def _close_application_pool_after_tests():
    yield
    module = sys.modules.get("bw_pg")
    close_pool = getattr(module, "close_pool", None) if module is not None else None
    if callable(close_pool):
        close_pool()
