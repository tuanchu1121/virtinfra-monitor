"""Pytest process hygiene for VirtInfra Monitor source validation.

The files listed in ``collect_ignore`` are executable source-contract scripts,
not pytest test modules.  ``preflight.sh`` runs each of them directly so their
module-level assertions still execute.  Ignoring them during pytest discovery
prevents pytest from retaining several complete ASTs of the combined modular
runtime source at the same time.
"""
from __future__ import annotations

import sys

import pytest


collect_ignore = [
    "test_bandwidth_consumption_agent.py",
    "test_consumption_auth_contract.py",
    "test_consumption_ui_contract.py",
    "test_custom_theme_runtime.py",
    "test_docs_source_accuracy.py",
    "test_manifest_contract.py",
    "test_repository_contract.py",
    "test_storage_v2_contract.py",
    "test_theme_manager_contract.py",
    "test_v50_contract.py",
    "test_v50_postgres_integration.py",
    "test_virtinfra_hardening.py",
]


@pytest.fixture(scope="session", autouse=True)
def _close_application_pool_after_tests():
    """Close test-created DB pool workers after all pytest assertions finish."""
    yield
    module = sys.modules.get("bw_pg")
    close_pool = getattr(module, "close_pool", None) if module is not None else None
    if callable(close_pool):
        close_pool()
