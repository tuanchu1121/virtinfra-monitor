#!/usr/bin/env python3
"""Regression test for compact node-only 2-hour bandwidth accounting."""
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "deploy/agent/agent.py"
spec = importlib.util.spec_from_file_location("virtinfra_agent_bwcons_test", AGENT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

runtime = {}
# 2026-07-15 12:00 Asia/Ho_Chi_Minh. First cycle is a clean baseline.
base = 1784091600
for index in range(25):
    module.account_bandwidth_consumption(runtime, {
        "time": base + index * 300,
        "interval": 300,
        "interfaces": [
            {"vm_uuid": "u1", "bridge": "br0", "rx_delta": 100, "tx_delta": 200},
            {"vm_uuid": "u2", "bridge": "br0", "rx_delta": 300, "tx_delta": 400},
            {"vm_uuid": "u3", "bridge": "br1", "rx_delta": 50, "tx_delta": 70},
        ],
        "physical_interfaces": [
            {"role": "public", "rx_delta": 1000, "tx_delta": 2000},
            {"role": "private", "rx_delta": 500, "tx_delta": 700},
        ],
    })

state = runtime["bandwidth_consumption"]
assert len(state["pending"]) == 1
assert not state["buckets"]
row = state["pending"][0]
assert row["coverage_seconds"] == 7200
assert row["sample_count"] == 24
assert row["estimated"] == 0
assert row["physical_public_rx_bytes"] == 24 * 1000
assert row["physical_public_tx_bytes"] == 24 * 2000
assert row["physical_private_rx_bytes"] == 24 * 500
assert row["physical_private_tx_bytes"] == 24 * 700
# Guest perspective normalization: host vnet TX -> VM RX, host vnet RX -> VM TX.
assert row["vm_public_rx_bytes"] == 24 * 600
assert row["vm_public_tx_bytes"] == 24 * 400
assert row["vm_private_rx_bytes"] == 24 * 70
assert row["vm_private_tx_bytes"] == 24 * 50
assert "vm_uuid" not in row
assert all("uuid" not in key.lower() for key in row)
print("PASS: compact 2-hour bandwidth accounting, guest RX/TX normalization, no UUID payload")
