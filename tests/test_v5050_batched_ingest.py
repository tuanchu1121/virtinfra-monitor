from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from runtime_source import read_app_source
APP = read_app_source()
SV2 = (ROOT / "app" / "storage_v2.py").read_text(encoding="utf-8")
INSTALLER = (ROOT / "deploy" / "postgres" / "install-postgres-native.sh").read_text(encoding="utf-8")


def test_batched_ingest_contract():
    assert 'V5050_VERSION = "50.5.0"' in APP
    assert 'jsonb_populate_recordset(NULL::' in APP
    assert '_v4810_current_writer = _v5050_current_writer' in APP
    assert 'refresh_fast_current_state = _v5050_refresh_fast_current_state' in APP
    assert 'WITH src AS (' in APP
    assert 'DELETE FROM vm_disk_summary_current WHERE node=?' not in APP[APP.rfind('def _v48140_refresh_node_summaries'):]


def test_single_write_defaults():
    assert 'VIRTINFRA_STORAGE_V2", "0"' in SV2
    assert 'VIRTINFRA_READ_CHART_V2", "0"' in SV2
    assert 'VIRTINFRA_RAW_V2", "0"' in SV2
    assert "VIRTINFRA_STORAGE_V2='0'" in INSTALLER
    assert "VIRTINFRA_READ_CHART_V2='0'" in INSTALLER
    assert "VIRTINFRA_RAW_V2='0'" in INSTALLER
