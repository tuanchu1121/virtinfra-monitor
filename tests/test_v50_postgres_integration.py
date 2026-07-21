#!/usr/bin/env python3
"""Live PostgreSQL integration test for the full VirtInfra Monitor application.

Set BW_TEST_DATABASE_URL to a disposable database. The test drops/recreates the
public and bw_meta schemas in that database.
"""
from __future__ import annotations
import copy
import importlib.util
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
import time
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
DSN = os.environ.get("BW_TEST_DATABASE_URL", "").strip()
if not DSN:
    pytest.skip(
        "BW_TEST_DATABASE_URL is not set",
        allow_module_level=True,
    )

import psycopg

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
sys.modules[spec.name] = module
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
    "005_ingest_write_profile.sql", "006_postgres_native_maintenance.sql",
    "007_safe_maintenance_queue.sql", "008_mac_identity_search.sql",
    "009_low_io_compat.sql", "010_consumption_inventory_cleanup.sql",
    "011_node_groups.sql", "012_node_groups_r6_safety.sql",
    "013_maintenance_queue_boolean.sql",
    "014_node_vm_consumption_rollups.sql",
    "015_consumption_ingest_preaggregation.sql",
    "016_configuration_backup_nuclear.sql",
):
    apply_sql(ROOT / "postgres/sql" / migration)

# The additive role namespace keeps the existing administrator fully privileged.
module.set_admin_credentials("admin", "Password123!")

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

# Two web workers receiving the same new sample concurrently must serialize on
# the per-Node advisory lock. Exactly one receipt may add the sample delta.
concurrent_payload = dict(payload)
concurrent_payload["time"] = now + 1
concurrent_bucket = module.bucket_for(concurrent_payload["time"])
def node_vm_total(bucket_value):
    check_conn = module.db()
    try:
        row = check_conn.execute(
            """
            SELECT COALESCE(vm_public_rx_bytes,0)+COALESCE(vm_public_tx_bytes,0)
                 + COALESCE(vm_private_rx_bytes,0)+COALESCE(vm_private_tx_bytes,0)
              FROM node_consumption_5m
             WHERE bucket_start=? AND node=?
            """,
            (bucket_value, "V50-TEST-NODE"),
        ).fetchone()
        return int((row or (0,))[0] or 0)
    finally:
        check_conn.close()

before_concurrent = node_vm_total(concurrent_bucket)
def post_concurrent_sample():
    thread_client = module.app.test_client()
    result = thread_client.post(
        "/push", json=concurrent_payload,
        headers={"X-Token": "v50-integration-token"},
    )
    return result.status_code, result.get_json() or {}

with ThreadPoolExecutor(max_workers=2) as executor:
    concurrent_results = list(executor.map(lambda _index: post_concurrent_sample(), range(2)))
assert all(status == 200 for status, _body in concurrent_results)
assert sorted(bool(body.get("duplicate")) for _status, body in concurrent_results) == [False, True]
after_concurrent = node_vm_total(concurrent_bucket)
assert after_concurrent - before_concurrent == 562500000

# Node and VM rollups are one transaction. Force the VM COPY stage to fail
# after the interface stage has prepared Node rollups, then verify receipt and
# all Node deltas are rolled back and the same sample can be retried normally.
atomic_payload = dict(payload)
atomic_payload["time"] = now + 2
atomic_bucket = module.bucket_for(atomic_payload["time"])
before_atomic = node_vm_total(atomic_bucket)
original_vm_copy = module._v5052_write_vm_copy_batch
def fail_vm_copy(*_args, **_kwargs):
    raise RuntimeError("forced R22 atomicity test failure")
module._v5052_write_vm_copy_batch = fail_vm_copy
try:
    atomic_failed = client.post(
        "/push", json=atomic_payload,
        headers={"X-Token": "v50-integration-token"},
    )
finally:
    module._v5052_write_vm_copy_batch = original_vm_copy
assert atomic_failed.status_code == 500, atomic_failed.get_data(as_text=True)
assert node_vm_total(atomic_bucket) == before_atomic
receipt_conn = module.db()
try:
    receipt_count = int(receipt_conn.execute(
        "SELECT count(*) FROM push_receipts WHERE node=? AND push_time=?",
        ("V50-TEST-NODE", atomic_payload["time"]),
    ).fetchone()[0])
finally:
    receipt_conn.close()
assert receipt_count == 0
atomic_retry = client.post(
    "/push", json=atomic_payload,
    headers={"X-Token": "v50-integration-token"},
)
assert atomic_retry.status_code == 200
assert not atomic_retry.get_json().get("duplicate")
assert node_vm_total(atomic_bucket) - before_atomic == 562500000

# R22: a missing/invalid VM metrics section is partial data, not an empty VM
# inventory. It must not erase or zero the latest CPU/RAM/disk snapshot.
conn = module.db()
try:
    before_partial = conn.execute(
        "SELECT last_seen,ram_current_kib,ram_rss_kib FROM vm_current_fast WHERE node=? AND vm_uuid=?",
        ("V50-TEST-NODE", vm_uuid),
    ).fetchone()
finally:
    conn.close()
partial_payload = dict(payload)
partial_payload["time"] = now + 30
partial_payload.pop("vms", None)
partial_response = client.post("/push", json=partial_payload, headers={"X-Token": "v50-integration-token"})
assert partial_response.status_code == 200, partial_response.get_data(as_text=True)
conn = module.db()
try:
    after_partial = conn.execute(
        "SELECT last_seen,ram_current_kib,ram_rss_kib FROM vm_current_fast WHERE node=? AND vm_uuid=?",
        ("V50-TEST-NODE", vm_uuid),
    ).fetchone()
finally:
    conn.close()
assert tuple(after_partial) == tuple(before_partial)

# Newer current state wins. A later-arriving older retry may still populate
# history, but it must never rewind current tables.
newer_payload = dict(payload)
newer_payload["time"] = now + 120
newer_payload["vms"] = [dict(payload["vms"][0], ram_current_kib=8388608, ram_rss_kib=7340032)]
newer_response = client.post("/push", json=newer_payload, headers={"X-Token": "v50-integration-token"})
assert newer_response.status_code == 200, newer_response.get_data(as_text=True)
older_payload = dict(payload)
older_payload["time"] = now + 60
older_payload["vms"] = [dict(payload["vms"][0], ram_current_kib=1048576, ram_rss_kib=524288)]
older_response = client.post("/push", json=older_payload, headers={"X-Token": "v50-integration-token"})
assert older_response.status_code == 200, older_response.get_data(as_text=True)
conn = module.db()
try:
    current_after_reorder = conn.execute(
        "SELECT last_seen,ram_current_kib,ram_rss_kib FROM vm_current_fast WHERE node=? AND vm_uuid=?",
        ("V50-TEST-NODE", vm_uuid),
    ).fetchone()
finally:
    conn.close()
assert int(current_after_reorder[0]) == now + 120
assert int(current_after_reorder[1]) == 8388608
assert int(current_after_reorder[2]) == 7340032

future_payload = dict(payload)
future_payload["time"] = int(time.time()) + module.V50_MAX_FUTURE_PUSH_SECONDS + 60
future_response = client.post("/push", json=future_payload, headers={"X-Token": "v50-integration-token"})
assert future_response.status_code == 400
assert future_response.get_json().get("error") == "bad_payload"

# A VM may move between Nodes without rewriting old Consumption history.
move_uuid = str(uuid.uuid4())
def moved_payload(node_name, sample_time):
    moved = copy.deepcopy(payload)
    moved["node"] = node_name
    moved["time"] = sample_time
    moved["inventory_complete"] = False
    moved["vm_inventory"] = [move_uuid]
    moved["interfaces"][0]["vm_uuid"] = move_uuid
    moved["vms"][0]["vm_uuid"] = move_uuid
    return moved
move_a = client.post(
    "/push", json=moved_payload("V50-MOVE-A", now + 240),
    headers={"X-Token": "v50-integration-token"},
)
move_b = client.post(
    "/push", json=moved_payload("V50-MOVE-B", now + 360),
    headers={"X-Token": "v50-integration-token"},
)
assert move_a.status_code == 200 and move_b.status_code == 200
move_conn = module.db()
try:
    move_nodes = {
        str(row[0]) for row in move_conn.execute(
            "SELECT DISTINCT node FROM vm_consumption_hourly WHERE vm_uuid=?",
            (move_uuid,),
        ).fetchall()
    }
finally:
    move_conn.close()
assert move_nodes == {"V50-MOVE-A", "V50-MOVE-B"}

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
# The legacy Agent-side two-hour endpoint is deliberately retired. Normal
# five-minute /push is the only active writer and owns all compact rollups.
bw_unauthorized = client.post("/push/bandwidth-consumption", json=bw_payload, headers={"X-Token": "wrong-token"})
assert bw_unauthorized.status_code == 410, bw_unauthorized.get_data(as_text=True)
assert bw_unauthorized.get_json().get("error") == "legacy_2h_accounting_retired"

bw_response = client.post("/push/bandwidth-consumption", json=bw_payload, headers={"X-Token": "v50-integration-token"})
assert bw_response.status_code == 410, bw_response.get_data(as_text=True)
assert bw_response.get_json().get("error") == "legacy_2h_accounting_retired"
bw_retry = client.post("/push/bandwidth-consumption", json=bw_payload, headers={"X-Token": "v50-integration-token"})
assert bw_retry.status_code == 410

admin_user = module.get_dashboard_user("admin")
node_groups_module = sys.modules["node_groups"]
with client.session_transaction() as sess:
    sess["dashboard_authenticated"] = True
    sess["dashboard_user_id"] = int(admin_user[0])
    sess["dashboard_username"] = "admin"
    sess["dashboard_role"] = "super_admin"
    sess["admin_authenticated"] = True
    sess["admin_username"] = "admin"
    sess["csrf_token"] = "test-csrf"
    sess["dashboard_auth_stamp"] = node_groups_module._user_auth_stamp(admin_user)

# Live PostgreSQL Node Group create/assign/inheritance contract.
created = client.post("/admin/node-groups/create", data={
    "csrf_token": "test-csrf", "name": "Integration Group",
    "description": "PostgreSQL integration", "country_code": "vn",
})
assert created.status_code == 302, created.get_data(as_text=True)
conn = module.db()
try:
    integration_group_id = int(conn.execute(
        "SELECT id FROM node_groups WHERE name='Integration Group'"
    ).fetchone()[0])
finally:
    conn.close()
assigned = client.post("/admin/node-groups/assign", data={
    "csrf_token": "test-csrf", "group_id": integration_group_id,
    "nodes": ["V50-TEST-NODE"],
})
assert assigned.status_code == 302, assigned.get_data(as_text=True)
conn = module.db()
try:
    assert conn.execute(
        "SELECT group_id FROM node_group_memberships WHERE node=?", ("V50-TEST-NODE",)
    ).fetchone()[0] == integration_group_id
    assert conn.execute(
        "SELECT ng.name FROM vm_inventory vi "
        "JOIN node_group_memberships gm ON gm.node=vi.node "
        "JOIN node_groups ng ON ng.id=gm.group_id "
        "WHERE vi.node=? AND vi.vm_uuid=?", ("V50-TEST-NODE", vm_uuid)
    ).fetchone()[0] == "Integration Group"
finally:
    conn.close()

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
        "node_consumption_5m": "SELECT count(*) FROM node_consumption_5m WHERE node=?",
        "vm_consumption_hourly": "SELECT count(*) FROM vm_consumption_hourly WHERE node=? AND vm_uuid=?",
        "vm_consumption_daily": "SELECT count(*) FROM vm_consumption_daily WHERE node=? AND vm_uuid=?",
        "vm_chart_5m": "SELECT count(*) FROM vm_chart_5m WHERE node=? AND vm_uuid=?",
        "vm_raw_detail_5m": "SELECT count(*) FROM vm_raw_detail_5m WHERE node=? AND vm_uuid=?",
        "node_chart_5m": "SELECT count(*) FROM node_chart_5m WHERE node=?",
    }
    for table, sql in checks.items():
        params = ("V50-TEST-NODE", vm_uuid) if "vm_uuid" in sql else ("V50-TEST-NODE",)
        count = int(conn.execute(sql, params).fetchone()[0])
        assert count >= 1, f"{table} was not populated"
    legacy_count = int(conn.execute(
        "SELECT count(*) FROM node_bandwidth_consumption_2h WHERE node=?",
        ("V50-TEST-NODE",),
    ).fetchone()[0])
    assert legacy_count == 0, "retired legacy two-hour writer accepted data"
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
