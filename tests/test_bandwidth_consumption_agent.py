#!/usr/bin/env python3
"""Agent v15 keeps one 5-minute delivery path and drops obsolete 2-hour state."""
from pathlib import Path
import importlib.util
import json
import tempfile

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "deploy/agent/agent.py"
SOURCE = AGENT.read_text(encoding="utf-8")

assert "AGENT_VERSION = 15" in SOURCE
assert '"VirtInfra-Agent/15"' in SOURCE
assert "def account_bandwidth_consumption" not in SOURCE
assert "def send_bandwidth_consumption_pending" not in SOURCE
assert "BandwidthConsumption/1" not in SOURCE
assert "/push/bandwidth-consumption" not in SOURCE
assert 'data.pop("bandwidth_consumption", None)' in SOURCE
assert "PUSH_SECONDS = max(60" in SOURCE
assert "runtime[\"pending\"]" in SOURCE
assert "send_pending(runtime)" in SOURCE

spec = importlib.util.spec_from_file_location("virtinfra_agent_v15_test", AGENT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.AGENT_VERSION == 15

with tempfile.TemporaryDirectory() as tmp:
    runtime_path = Path(tmp) / "runtime.json"
    runtime_path.write_text(json.dumps({
        "carry": {},
        "iface_map": {},
        "pending": None,
        "bandwidth_consumption": {"buckets": {"old": {}}, "pending": [{"old": 1}]},
    }))
    module.RUNTIME = str(runtime_path)
    runtime = module.load_runtime()
    assert "bandwidth_consumption" not in runtime

print("PASS: Agent v15 uses only normal 5-minute delivery and removes legacy 2-hour state")
