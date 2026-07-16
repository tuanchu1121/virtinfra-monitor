from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app" / "app.py").read_text(encoding="utf-8")
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    need(VERSION == "50.5.1-prod-r1-full-batch-ingest", "release mismatch")
    need('V5051_VERSION = "50.5.1"' in APP, "v50.5.1 marker missing")
    for symbol in (
        "_v5051_write_interface_batch",
        "_v5051_write_vm_perf_batch",
        "_v5051_ingest_disk_io_current",
        "ingest_disk_io_current = _v5051_ingest_disk_io_current",
    ):
        need(symbol in APP, f"missing {symbol}")

    push_start = APP.index('def push():')
    push_end = APP.index('\n\n\n# ---------------------------------------------------------------------------\n# v48.7.0', push_start)
    push = APP[push_start:push_end]
    need("v5051_iface_stats = _v5051_write_interface_batch" in push, "interface batch not active")
    need("v5051_vm_stats = _v5051_write_vm_perf_batch" in push, "VM batch not active")
    need("add_bandwidth_rollup(" not in push, "per-interface bandwidth rollup remains in /push")
    need("INSERT INTO node_stats(" not in push, "per-interface node_stats SQL remains in /push")
    need("INSERT INTO vm_perf_stats(" not in push, "per-VM perf SQL remains in /push")
    need("INSERT INTO vm_inventory(" not in push[push.index('auto_purge_migrated_vms(conn)'):],
         "duplicate interface-loop inventory write remains")

    need("jsonb_to_recordset(?::jsonb)" in APP, "JSONB set-based source missing")
    need("rows_iface=%s rows_vm=%s" in APP, "batch observability missing")
    need("WITH src AS" in APP and "bandwidth_hourly" in APP and "bandwidth_daily" in APP,
         "set-based bandwidth writer missing")
    print("PASS: v50.5.1 full batch ingest source contract")


if __name__ == "__main__":
    main()
