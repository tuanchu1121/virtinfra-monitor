#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT.joinpath("VERSION").read_text().strip()

markdown = "\n".join(
    p.read_text(encoding="utf-8", errors="strict")
    for p in ROOT.rglob("*.md")
)

# User-facing documentation must describe the current PostgreSQL/TimescaleDB runtime.
for obsolete in ("SQLite", "sqlite", "bandwidth.db", "VACUUM INTO"):
    assert obsolete not in markdown, f"obsolete datastore wording in Markdown: {obsolete}"

required = [
    "PostgreSQL 17", "TimescaleDB", "bw-timescaledb",
    "bw_monitor_postgres_data", "127.0.0.1:55432",
    "bw-monitor.service", "bw-monitor-retention.timer",
    "bw-monitor-backup.timer", "virtinfra-monitor-health-watch.timer",
    "virtinfra-agent.service", "/etc/virtinfra-agent.env",
    "node_bandwidth_consumption_2h", "/bandwidth-consumption",
    "vm_chart_5m", "vm_raw_detail_5m", "node_chart_5m",
    "VIRTINFRA_READ_CHART_V2", "VIRTINFRA_RAW_V2",
    "virtinfra-monitorctl backup", "virtinfra-monitorctl update",
    "virtinfra-monitorctl db-check", "virtinfra-monitorctl vacuum",
    "virtinfra-monitorctl storage-v2", "virtinfra-monitorctl rollback-storage-v2",
]
for item in required:
    assert item in markdown, f"missing source-accurate documentation: {item}"

allowed = {
    "status", "health", "doctor", "audit", "db-check", "database",
    "backup", "restore", "diagnostics", "logs", "follow", "restart",
    "retention", "vacuum", "psql", "credentials", "urls", "version",
    "update", "domain", "storage-v2", "rollback-storage-v2", "help",
}
for cmd in re.findall(r"virtinfra-monitorctl\s+([a-z0-9-]+)", markdown):
    assert cmd in allowed, f"unsupported documented virtinfra-monitorctl command: {cmd}"

for name in (
    "README.md", "START_HERE_VI.md", "SOURCE_OF_TRUTH_VI.md",
    "GITHUB_DESKTOP_VI.md", "COMMANDS_A_TO_Z_VI.md",
):
    assert VERSION in ROOT.joinpath(name).read_text(), f"{name} version mismatch"

print("PASS: PostgreSQL/TimescaleDB source-accurate documentation")
