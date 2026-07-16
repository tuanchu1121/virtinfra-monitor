#!/usr/bin/env python3
"""Live PostgreSQL integration test for the full VirtInfra Monitor application.

Set BW_TEST_DATABASE_URL to a disposable database. The test drops/recreates the
public and bw_meta schemas in that database.
"""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import uuid

import psycopg

ROOT = Path(__file__).resolve().parents[1]
DSN = os.environ.get("BW_TEST_DATABASE_URL", "").strip()
if not DSN:
    print("SKIP: BW_TEST_DATABASE_URL is not set")
    raise SystemExit(0)

with psycopg.connect(DSN, autocommit=True) as conn:
    conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
    conn.execute("DROP SCHEMA IF EXISTS bw_meta CASCADE")
    conn.execute("CREATE SCHEMA public")
    conn.execute("GRANT ALL ON SCHEMA public TO PUBLIC")

os.environ.update({
    "BW_DATABASE_URL": DSN,
    "BW_POSTGRES_DSN": DSN,
    "BW_MONITOR_DB": "/var/lib/bw-monitor/postgresql",
    "BW_MONITOR_TOKEN": "v50-integration-token",
    "BW_ADMIN_USERNAME": "admin",
    "BW_ADMIN_PASSWORD_HASH": "",
    "BW_ADMIN_SECRET_KEY": "v50-integration-secret-key",
    "BW_REDIS_ENABLED": "0",
    "BW_WRITE_LEGACY_USAGE": "0",
    "BW_BACKFILL_CACHE_ON_START": "0",
    "BW_BACKFILL_INVENTORY_ON_START": "0",
})
sys.path.insert(0, str(ROOT / "app"))
spec = importlib.util.spec_from_file_location("bw_monitor_v50_app", ROOT / "app/app.py")
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

# The production installer applies SQL migrations after the application creates
# its backward-compatible base schema and before Gunicorn starts.
def apply_sql(path: Path) -> None:
    sql = "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("\\")
    )
    with psycopg.connect(DSN, autocommit=True) as migration_conn:
        migration_conn.execute(sql, prepare=False)

for migration in (
    "001_bootstrap.sql", "002_timescale.sql", "003_native_indexes.sql", "004_storage_v2.sql",
    "005_ingest_write_profile.sql",
    "006_postgres_native_maintenance.sql",
):
    apply_sql(ROOT / "postgres/sql" / migration)

vm_uuid = str(uuid.uuid4())
now = int(time.time())
payload = {
    "version": 12,
    "node": "V50-TEST-NODE",
    "time": now,
    "interval": 300,
    "inventory_complete": True,
    "vm_inventory": [vm_uuid],
    "interfaces": [{
        "vm_uuid": vm_uuid, "iface": "vnet50", "bridge": "br0",
        "mac": "52:54:00:50:00:01", "interval_seconds": 300,
        "rx_delta": 375000000, "tx_delta": 187500000,
        "rx_packets_delta": 300000, "tx_packets_delta": 150000,
        "rx_drop_delta": 0, "tx_drop_delta": 0,
        "rx_error_delta": 0, "tx_error_delta": 0,
        "rx_mbps_peak": 18.0, "tx_mbps_peak": 10.0,
        "rx_pps_peak": 1400.0, "tx_pps_peak": 900.0,
        "rx_packet_size_avg": 1250.0, "tx_packet_size_avg": 1250.0,
        "network_sample_count": 20, "network_sample_expected": 20,
        "network_sample_max_gap_seconds": 15.2,
        "seconds_over_pps": 0, "seconds_over_mbps": 0,
        "network_sample_quality": "GOOD",
    }],
    "vms": [{
        "vm_uuid": vm_uuid, "vcpu_current": 4,
        "cpu_percent": 115.0, "cpu_core_percent": 115.0,
        "cpu_normalized_percent": 28.75,
        "ram_current_kib": 4194304, "ram_maximum_kib": 4194304,
        "ram_rss_kib": 3145728, "ram_available_kib": 3670016,
        "ram_unused_kib": 1048576, "ram_usable_kib": 3145728,
        "disk_read_delta": 157286400, "disk_write_delta": 78643200,
        "disk_read_reqs_delta": 3000, "disk_write_reqs_delta": 1500,
        "disk_count": 2,
        "disks": [
            {"index": 0, "target": "vda", "source": "/home/vf-data/disk/%s_1.img" % vm_uuid,
             "role": "customer", "mount": "/home", "storage_device": "/dev/mapper/almalinux-home",
             "storage_block": "dm-0", "storage_fstype": "xfs",
             "capacity_bytes": 107374182400, "allocation_bytes": 53687091200,
             "physical_bytes": 53687091200, "read_delta": 104857600,
             "write_delta": 52428800, "read_reqs_delta": 2000,
             "write_reqs_delta": 1000, "interval_seconds": 300},
            {"index": 1, "target": "vdb", "source": "/home2/%s_2.img" % vm_uuid,
             "role": "customer", "mount": "/home2", "storage_device": "/dev/sda1",
             "storage_block": "sda", "storage_fstype": "ext4",
             "capacity_bytes": 214748364800, "allocation_bytes": 107374182400,
             "physical_bytes": 107374182400, "read_delta": 52428800,
             "write_delta": 26214400, "read_reqs_delta": 1000,
             "write_reqs_delta": 500, "interval_seconds": 300},
        ],
    }],
    "node_host": {
        "load1": 1.2, "load5": 1.0, "load15": 0.8, "cpu_count": 32,
        "cpu_percent": 27.5, "mem_total": 137438953472,
        "mem_available": 68719476736, "mem_used": 68719476736,
        "swap_total": 68719476736, "swap_used": 1073741824,
        "disk_read_delta": 314572800, "disk_write_delta": 209715200,
        "disk_read_reqs_delta": 6000, "disk_write_reqs_delta": 4000,
        "disk_read_bps": 1048576.0, "disk_write_bps": 699050.0,
        "uptime_seconds": 864000,
        "filesystems": [
            {"mount": "/", "device": "/dev/md125", "maj_min": "9:125", "fstype": "xfs",
             "size": 167503724544, "used": 53687091200, "avail": 113816633344, "use_percent": 32.0},
            {"mount": "/home", "device": "/dev/mapper/almalinux-home", "maj_min": "253:0", "fstype": "xfs",
             "size": 12094627905536, "used": 7476679068877, "avail": 4617948836659, "use_percent": 61.8},
            {"mount": "/home2", "device": "/dev/sda1", "maj_min": "8:1", "fstype": "ext4",
             "size": 219902325555200, "used": 109951162777600, "avail": 109951162777600, "use_percent": 50.0},
        ],
        "storage_devices": [
            {"mount": "/", "device": "/dev/md125", "block": "md125", "raid_level": "raid1", "fstype": "xfs",
             "size": 167503724544, "used": 53687091200, "avail": 113816633344, "use_percent": 32.0,
             "read_delta": 104857600, "write_delta": 52428800, "read_ios_delta": 2000, "write_ios_delta": 1000,
             "read_bps": 349525.3, "write_bps": 174762.7, "read_iops": 6.67, "write_iops": 3.33, "util_percent": 2.5},
            {"mount": "/home", "device": "/dev/mapper/almalinux-home", "block": "dm-0", "raid_level": "", "fstype": "xfs",
             "size": 12094627905536, "used": 7476679068877, "avail": 4617948836659, "use_percent": 61.8,
             "read_delta": 157286400, "write_delta": 104857600, "read_ios_delta": 3000, "write_ios_delta": 2000,
             "read_bps": 524288.0, "write_bps": 349525.3, "read_iops": 10.0, "write_iops": 6.67, "util_percent": 5.0},
            {"mount": "/home2", "device": "/dev/sda1", "block": "sda", "raid_level": "hardware/unknown", "fstype": "ext4",
             "size": 219902325555200, "used": 109951162777600, "avail": 109951162777600, "use_percent": 50.0,
             "read_delta": 52428800, "write_delta": 52428800, "read_ios_delta": 1000, "write_ios_delta": 1000,
             "read_bps": 174762.7, "write_bps": 174762.7, "read_iops": 3.33, "write_iops": 3.33, "util_percent": 1.5},
        ],
    },
    "physical_interfaces": [],
    "bridge_addresses": [{"role": "public", "bridge": "br0", "ipv4": ["203.0.113.50/24"], "primary_ipv4": "203.0.113.50"}],
    "agent_health": {"version": 13, "duration_ms": 420, "counts": {"vms": 1, "interfaces": 1}, "timings": {}},
}

client = module.app.test_client()
response = client.post("/push", json=payload, headers={"X-Token": "v50-integration-token"})
assert response.status_code == 200, response.get_data(as_text=True)
assert response.get_json().get("ok") is True
response2 = client.post("/push", json=payload, headers={"X-Token": "v50-integration-token"})
assert response2.status_code == 200 and response2.get_json().get("duplicate") is True

# Compact node-only Bandwidth Consumption ingest. No VM UUID is present.
bw_end = module._v5030_local_bucket_start(now)
bw_start = bw_end - module.V5030_BW_BUCKET_SECONDS
bw_payload = {
    "node": "V50-TEST-NODE",
    "bucket_start": bw_start,
    "bucket_end": bw_end,
    "physical_public_rx_bytes": 1000,
    "physical_public_tx_bytes": 2000,
    "physical_private_rx_bytes": 3000,
    "physical_private_tx_bytes": 4000,
    "vm_public_rx_bytes": 900,
    "vm_public_tx_bytes": 1800,
    "vm_private_rx_bytes": 2500,
    "vm_private_tx_bytes": 3500,
    "coverage_seconds": 7200,
    "sample_count": 24,
    "estimated": 0,
    "agent_version": 13,
}
bw_unauthorized = client.post("/push/bandwidth-consumption", json=bw_payload, headers={"X-Token": "wrong-token"})
assert bw_unauthorized.status_code == 401, bw_unauthorized.get_data(as_text=True)

bw_response = client.post("/push/bandwidth-consumption", json=bw_payload, headers={"X-Token": "v50-integration-token"})
assert bw_response.status_code == 200, bw_response.get_data(as_text=True)
assert bw_response.get_json().get("ok") is True
# Retry is an idempotent UPSERT, not a second row.
bw_retry = client.post("/push/bandwidth-consumption", json=bw_payload, headers={"X-Token": "v50-integration-token"})
assert bw_retry.status_code == 200 and bw_retry.get_json().get("ok") is True

with client.session_transaction() as sess:
    sess["dashboard_authenticated"] = True
    sess["dashboard_username"] = "admin"
    sess["dashboard_role"] = "admin"
    sess["admin_authenticated"] = True
    sess["admin_username"] = "admin"
    sess["csrf_token"] = "test-csrf"

paths = [
    "/", "/top", "/top?period=10m", "/top?period=30m", "/top?period=1h",
    "/abuse/vms", "/storage", "/bandwidth-consumption",
    "/bandwidth-consumption/node/V50-TEST-NODE", "/node/V50-TEST-NODE",
    f"/vm?node=V50-TEST-NODE&vm_uuid={vm_uuid}", "/api/v1/performance",
    "/admin?section=overview",
]
for path in paths:
    result = client.get(path)
    assert result.status_code == 200, f"{path}: {result.status_code} {result.get_data(as_text=True)[:500]}"

# Regression: the temporary runtime timezone selector is gone. The UI remains
# fixed to the original Asia/Ho_Chi_Minh clock and the old route is absent.
overview = client.get("/admin?section=overview")
overview_html = overview.get_data(as_text=True)
assert 'action="/admin/display-timezone"' not in overview_html
assert module.display_timezone_name() == "Asia/Ho_Chi_Minh"
assert client.post("/admin/display-timezone", data={"timezone": "UTC"}).status_code == 404

# Regression: abuse_policy_versions uses revision as its primary key and has no
# id column. Saving a policy must not receive an automatic RETURNING id suffix.
policy = module._v4810_save_policy({}, "integration-admin", "save")
assert int(policy.get("revision") or 0) >= 1

conn = module.db()
try:
    policy_count = int(conn.execute("SELECT count(*) FROM abuse_policy_versions").fetchone()[0])
    assert policy_count >= 1, "abuse policy version was not saved"
    checks = {
        "vm_current_fast": "SELECT count(*) FROM vm_current_fast WHERE node=? AND vm_uuid=?",
        "vm_disk_current": "SELECT count(*) FROM vm_disk_current WHERE node=? AND vm_uuid=?",
        "node_storage_current": "SELECT count(*) FROM node_storage_current WHERE node=?",
        "node_stats": "SELECT count(*) FROM node_stats WHERE node=? AND vm_uuid=?",
        "vm_perf_stats": "SELECT count(*) FROM vm_perf_stats WHERE node=? AND vm_uuid=?",
        "node_push_snapshots": "SELECT count(*) FROM node_push_snapshots WHERE node=?",
        "node_bandwidth_consumption_2h": "SELECT count(*) FROM node_bandwidth_consumption_2h WHERE node=?",
        "vm_chart_5m": "SELECT count(*) FROM vm_chart_5m WHERE node=? AND vm_uuid=?",
        "vm_raw_detail_5m": "SELECT count(*) FROM vm_raw_detail_5m WHERE node=? AND vm_uuid=?",
        "node_chart_5m": "SELECT count(*) FROM node_chart_5m WHERE node=?",
    }
    for table, sql in checks.items():
        params = ("V50-TEST-NODE", vm_uuid) if "vm_uuid" in sql else ("V50-TEST-NODE",)
        count = int(conn.execute(sql, params).fetchone()[0])
        assert count >= 1, f"{table} was not populated"
    chart_rows, _start, _end, _step = module.query_vm_chart("V50-TEST-NODE", vm_uuid, "7d")
    perf_rows, _start, _end, _step = module.query_vm_perf_chart("V50-TEST-NODE", vm_uuid, "7d")
    assert chart_rows and chart_rows[-1]["bucket"] == module.bucket_for(now), "V2 network chart read failed"
    assert perf_rows and perf_rows[-1]["cpu_core_percent"] == 115.0, "V2 performance chart semantics changed"
    module.purge_vm_data(conn, "V50-TEST-NODE", vm_uuid)
    conn.commit()
    for table in ("vm_current_fast", "vm_disk_current", "vm_inventory", "vm_perf_stats", "node_stats", "vm_chart_5m", "vm_raw_detail_5m"):
        count = int(conn.execute(f"SELECT count(*) FROM {table} WHERE node=? AND vm_uuid=?", ("V50-TEST-NODE", vm_uuid)).fetchone()[0])
        assert count == 0, f"purge left {table} rows"
finally:
    conn.close()
    module.dbapi.close_pool()

print("PASS: full v50 app PostgreSQL/Timescale integration, V2 chart/raw writes, pages, duplicate push and exact UUID purge")
