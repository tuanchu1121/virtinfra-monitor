from pathlib import Path
import importlib.util
import gzip
import json

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app/app.py").read_text(encoding="utf-8")
AGENT_PATH = ROOT / "deploy/agent/agent.py"
AGENT = AGENT_PATH.read_text(encoding="utf-8")
MIGRATION = (ROOT / "postgres/sql/009_low_io_compat.sql").read_text(encoding="utf-8")
INSTALLER = (ROOT / "deploy/postgres/install-postgres-native.sh").read_text(encoding="utf-8")
COMPOSE = (ROOT / "postgres/docker-compose.yml").read_text(encoding="utf-8")


def test_plain_and_gzip_transport_contract():
    assert "def read_agent_json_request" in APP
    assert 'encoding == "gzip"' in APP
    assert "MAX_UNCOMPRESSED_PUSH_BYTES + 1" in APP
    assert "def encode_http_payload" in AGENT
    assert 'gzip.compress(raw, compresslevel=1)' in AGENT
    assert 'headers["Content-Encoding"] = "gzip"' in AGENT


def test_agent_gzip_falls_back_to_plain_json_for_old_monitor(monkeypatch):
    spec = importlib.util.spec_from_file_location("virtinfra_agent_fallback", AGENT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HTTP_GZIP = True
    module.HTTP_GZIP_MIN_BYTES = 0

    requests = []

    class Response:
        def read(self):
            return b'{"ok":true}'

    def fake_urlopen(request, timeout):
        requests.append(request)
        if len(requests) == 1:
            import urllib.error
            raise urllib.error.HTTPError(
                request.full_url,
                415,
                "Unsupported Media Type",
                {},
                None,
            )
        return Response()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    result = module.post_json_payload(
        "https://monitor.invalid/push",
        {"node": "node-1", "items": list(range(100))},
        "VirtInfra-Agent/Test",
    )

    assert json.loads(result) == {"ok": True}
    assert len(requests) == 2
    assert requests[0].get_header("Content-encoding") == "gzip"
    assert requests[1].get_header("Content-encoding") is None
    assert json.loads(requests[1].data.decode("utf-8"))["node"] == "node-1"


def test_agent_gzip_encoder_round_trip():
    spec = importlib.util.spec_from_file_location("virtinfra_agent_lowio", AGENT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HTTP_GZIP = True
    module.HTTP_GZIP_MIN_BYTES = 0
    payload = {"node": "node-1", "items": [{"vm_uuid": f"vm-{i}", "rx": i} for i in range(100)]}
    encoded, headers = module.encode_http_payload(payload)
    assert headers.get("Content-Encoding") == "gzip"
    assert json.loads(gzip.decompress(encoded).decode("utf-8")) == payload


def test_mac_lookup_is_write_on_change_and_hot_table_mac_indexes_are_removed():
    assert "vm_nic_identity_lookup" in APP
    assert "node_nic_identity_lookup" in APP
    assert "IS DISTINCT FROM excluded.mac" in APP
    assert "idx_vm_iface_current_mac ON vm_iface_current" not in APP
    assert "idx_node_physical_net_latest_mac ON node_physical_net_latest" not in APP
    assert "DROP INDEX CONCURRENTLY IF EXISTS public.idx_vm_iface_current_mac" in MIGRATION
    assert "idx_vm_nic_identity_lookup_mac" in MIGRATION
    assert "FROM vm_nic_identity_lookup" in APP
    assert "FROM node_nic_identity_lookup" in APP


def test_current_table_index_profile_is_hot_friendly():
    assert "idx_vm_current_fast_seen ON" not in APP
    assert "idx_vm_current_fast_node_seen ON" not in APP
    assert "ON vm_iface_current(node,bridge,last_seen" not in APP
    assert "ON vm_iface_current(node,bridge);" in APP
    assert "fillfactor=75" in MIGRATION
    assert "autovacuum_vacuum_scale_factor=0.02" in MIGRATION
    assert "WHERE is_abuse=1" in MIGRATION


def test_installer_applies_low_io_migration_and_wal_limits():
    assert "009_low_io_compat.sql" in INSTALLER
    assert "Apply low-I/O compatible current-state profile" in INSTALLER
    assert "max_wal_size=${BW_PG_MAX_WAL_SIZE:-8GB}" in COMPOSE
    assert "min_wal_size=${BW_PG_MIN_WAL_SIZE:-2GB}" in COMPOSE
