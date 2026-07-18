from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PG_PATH = ROOT / "app" / "bw_pg.py"
APP_PATH = ROOT / "app" / "app.py"


def _load_bw_pg():
    spec = importlib.util.spec_from_file_location("test_bw_pg_v5055", PG_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_identity_and_native_copy_clone_contract() -> None:
    assert (ROOT / "VERSION").read_text().strip() == "50.6.0-prod-r1-node-groups-country-flags"
    app = APP_PATH.read_text(encoding="utf-8")
    pg = PG_PATH.read_text(encoding="utf-8")
    assert "(LIKE public.{table} INCLUDING DEFAULTS) ON COMMIT DELETE ROWS" in app
    assert "def _translate_like_operators" in pg
    assert "_RE_TABLE_LIKE_CLAUSE" in pg


def test_create_table_like_clause_is_not_rewritten_to_ilike() -> None:
    module = _load_bw_pg()
    source = (
        "CREATE TEMP TABLE IF NOT EXISTS vi5052_up_vm_disk_current "
        "(LIKE public.vm_disk_current INCLUDING DEFAULTS) ON COMMIT DELETE ROWS"
    )
    translated = module.translate_sql(None, source)
    assert "(LIKE public.vm_disk_current INCLUDING DEFAULTS)" in translated
    assert "ILIKE public.vm_disk_current" not in translated


def test_multiple_table_clone_options_remain_postgresql_ddl() -> None:
    module = _load_bw_pg()
    source = (
        'CREATE TEMPORARY TABLE "stage" '
        '(LIKE "public"."vm_disk_current" INCLUDING DEFAULTS EXCLUDING INDEXES INCLUDING STORAGE)'
    )
    translated = module.translate_sql(None, source)
    assert '(LIKE "public"."vm_disk_current" INCLUDING DEFAULTS EXCLUDING INDEXES INCLUDING STORAGE)' in translated
    assert "ILIKE" not in translated


def test_search_like_still_translates_to_ilike() -> None:
    module = _load_bw_pg()
    translated = module.translate_sql(None, "SELECT * FROM vm_inventory WHERE vm_uuid LIKE ? OR node NOT LIKE ?")
    assert "vm_uuid ILIKE %s" in translated
    assert "node NOT ILIKE %s" in translated
