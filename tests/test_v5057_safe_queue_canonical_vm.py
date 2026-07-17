from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app/app.py").read_text(encoding="utf-8")
QUEUE = (ROOT / "app/maintenance_queue.py").read_text(encoding="utf-8")
DISPATCH = (ROOT / "app/maintenance_dispatch.py").read_text(encoding="utf-8")
RUNNER = (ROOT / "app/maintenance.py").read_text(encoding="utf-8")
NATIVE = (ROOT / "app/maintenance_native.py").read_text(encoding="utf-8")
MIGRATION = (ROOT / "postgres/sql/007_safe_maintenance_queue.sql").read_text(encoding="utf-8")
INSTALLER = (ROOT / "deploy/postgres/install-postgres-native.sh").read_text(encoding="utf-8")
AGENT_FIX = (ROOT / "deploy/agent/fix-agent-uuid.sh").read_text(encoding="utf-8")


_AST_CACHE = {
    id(APP): ast.parse(APP),
    id(QUEUE): ast.parse(QUEUE),
    id(DISPATCH): ast.parse(DISPATCH),
    id(RUNNER): ast.parse(RUNNER),
    id(NATIVE): ast.parse(NATIVE),
}


def function_sources(source: str, name: str):
    tree = _AST_CACHE.get(id(source))
    if tree is None:
        tree = ast.parse(source)
        _AST_CACHE[id(source)] = tree
    lines = source.splitlines()
    return ["\n".join(lines[n.lineno - 1:n.end_lineno]) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]


def last_function(source: str, name: str) -> str:
    matches = function_sources(source, name)
    assert matches, name
    return matches[-1]


def test_release_identity():
    assert (ROOT / "VERSION").read_text().strip() == "50.5.8-prod-r3-consumption-vm-node"


def test_fifo_queue_allows_waiting_rows_but_only_one_worker():
    assert "Waiting in FIFO queue" in QUEUE
    assert "FOR UPDATE SKIP LOCKED" in DISPATCH
    assert "ORDER BY id" in DISPATCH
    assert '["systemctl", "--no-block", "start", unit]' in DISPATCH
    assert "status='starting'" in DISPATCH
    assert "status IN ('starting','running')" in MIGRATION
    assert "uq_maintenance_jobs_one_worker" in MIGRATION
    assert "uq_maintenance_jobs_one_active" in MIGRATION and "DROP INDEX" in MIGRATION
    # The new unique guard must not include queued jobs.
    worker_index = MIGRATION.split("uq_maintenance_jobs_one_worker", 1)[1].split(";", 1)[0]
    assert "queued" not in worker_index


def test_queue_has_heartbeat_watchdog_cancel_and_legacy_recovery():
    for column in ("heartbeat_at", "progress", "attempt", "cancel_requested"):
        assert column in MIGRATION
    assert "clear_live_cache" in MIGRATION and "checkpoint" in MIGRATION
    assert "recover_stale_rows" in DISPATCH
    assert "RUNNING_HEARTBEAT_STALE_SECONDS" in DISPATCH
    assert "unit_active" in DISPATCH
    assert "cancel_queued_job" in QUEUE
    assert "heartbeat_job" in RUNNER
    assert "maintenance_queue.wake_dispatcher()" in RUNNER
    assert "bw-monitor-maintenance-watchdog.timer" in INSTALLER
    assert "bw-monitor-maintenance-dispatch.service" in INSTALLER


def test_nuclear_reset_is_exclusive_previewed_backed_up_and_audited():
    route = last_function(APP, "admin_database_maintenance_v5057")
    card = last_function(APP, "database_maintenance_card")
    assert "reset_app_data_preview" in route
    assert "Admin password verification failed" in route
    assert "RESET VIRTINFRA" in route
    assert "expires_at" in route
    assert "not_before" in route
    assert "safety delay" in route
    assert "exclusive=True" in route
    assert "cannot wait in FIFO" in route
    assert "No data has been deleted" in card
    assert "Backup, verify, then reset" in card
    assert "create_verified_pre_nuclear_backup" in RUNNER
    assert "database.dump" in RUNNER and "database.list" in RUNNER and "SHA256SUMS" in RUNNER
    assert "maintenance_nuclear_audit" in MIGRATION
    assert "write_nuclear_audit" in RUNNER
    execute = last_function(RUNNER, "execute_action")
    assert 'result["completed"] = action_error is None' in execute
    assert 'result["nuclear_audit_written"] = True' in execute
    assert "verify_monitor_health" in execute
    assert "_verify_backup_manifest" in RUNNER
    assert '"maintenance_jobs"' in NATIVE
    assert '"maintenance_nuclear_audit"' in NATIVE


def test_uuid_resolver_prefers_fresh_current_location_and_drops_implicit_nic_scope():
    resolver = last_function(APP, "resolve_direct_vm_search")
    location = last_function(APP, "get_vm_current_location")
    assert "FROM vm_current_fast" in resolver
    assert "ORDER BY exact_uuid DESC,last_seen DESC,source_rank ASC" in resolver
    assert 'result.update({"iface":"","bridge":""})' in resolver
    assert "ORDER BY last_seen DESC,rank ASC" in location


def test_live_uuid_snapshot_uses_canonical_current_tables_and_explicit_cpu_fields():
    live = last_function(APP, "_v5057_live_vm_snapshot")
    wrapper = last_function(APP, "_v5054_vm_snapshot_overview")
    cpu = last_function(APP, "_v48129_vm_detail_cpu_stat")
    assert "FROM vm_current_fast" in live
    assert "FROM vm_iface_current" in live
    assert '"cpu_full_percent"' in live and '"cpu_core_percent"' in live
    assert 'period=="5m"' in wrapper.replace(" ", "")
    assert "_v5057_vm_snapshot_history_base" in wrapper
    assert "core=full*vcpu_count" in cpu.replace(" ", "")
    assert "core / vcpu_count" not in cpu


def test_history_multi_nic_peak_and_ram_use_same_selected_snapshot():
    historical = function_sources(APP, "_v5054_vm_snapshot_overview")[-2]
    ram = last_function(APP, "_v48103_latest_ram")
    assert "SUM(rx_mbps_peak)" in historical
    assert "SUM(tx_mbps_peak)" in historical
    assert "SUM(rx_pps_peak)" in historical
    assert "MAX(COALESCE(network_sample_count, 0))" in historical
    assert "resolve_snapshot_bucket" in ram
    assert "bucket=?" in ram
    assert 'period == "5m"' in ram


def test_live_disk_reads_exact_uuid_current_rows_and_assigned_is_primary():
    disks = last_function(APP, "_v48133_vm_disks")
    total = last_function(APP, "_v48135_vm_disk_total_overview")
    card = last_function(APP, "_v48133_vm_disk_io_card")
    assert "FROM vm_disk_current" in disks
    assert "WHERE node=? AND vm_uuid=? AND role='customer'" in disks
    assert "_v5057_vm_disks_history_base" in disks
    assert "VM DISK ASSIGNED" in total
    assert "ASSIGNED DISK SIZE" in card
    assert "Host allocated" in card


def test_agent_uuid_repair_is_targeted_backed_up_and_does_not_reinstall():
    assert "--node" in AGENT_FIX and "--purge-vm" in AGENT_FIX
    assert "VIRTINFRA_AGENT_NODE" in AGENT_FIX
    assert "state.json" in AGENT_FIX and "runtime.json" in AGENT_FIX
    assert "bak-$STAMP" in AGENT_FIX
    assert 'systemctl restart "$SERVICE"' in AGENT_FIX
    assert "install-agent" not in AGENT_FIX


def test_reset_epochs_block_old_agent_retries_without_agent_reinstall():
    push = last_function(APP, "push")
    assert "V5057_OPERATIONAL_PUSH_ACCEPT_AFTER" in APP
    assert 'get_admin_setting("operational_push_accept_after", "0")' in APP
    assert '"reason": "before reset epoch"' in push
    assert "set_reset_acceptance_epochs" in NATIVE
    assert '"operational_push_accept_after"' in NATIVE
    assert '"bandwidth_consumption_accept_after"' in NATIVE


def test_old_agent_tokens_are_supported_by_monitor_side_configuration():
    validator = last_function(APP, "valid_agent_token")
    tokens = last_function(APP, "_v5057_agent_tokens")
    assert "BW_MONITOR_LEGACY_TOKENS" in tokens
    assert "compare_digest" in validator
    assert "BW_MONITOR_LEGACY_TOKENS" in INSTALLER


def test_routine_jobs_cannot_queue_behind_nuclear_reset():
    enqueue = last_function(QUEUE, "enqueue_job")
    assert "action='reset_app_data'" in enqueue
    assert "new maintenance work is blocked until it finishes" in enqueue


def test_live_uuid_links_and_stale_node_routes_land_on_current_whole_vm():
    current_abuse = last_function(APP, "_v48103_current_abuse_page")
    route = last_function(APP, "vm_page_v5057")
    base_vm = last_function(APP, "vm_page")
    assert 'period="5m"' in current_abuse
    assert 'period="1h"' not in current_abuse
    assert 'request.args.get("period", "5m")' in base_vm
    assert 'current_node != node' in route
    assert 'bridge="", iface="", period="5m"' in route


def test_live_node_detail_uses_same_current_tables_as_dashboard_and_top_vm():
    overview = last_function(APP, "get_node_overview")
    metrics = last_function(APP, "get_node_metric_overview")
    host = last_function(APP, "get_node_host_period")
    filesystems = last_function(APP, "get_node_filesystems_snapshot")
    assert "FROM vm_iface_current" in overview
    assert "FROM vm_current_fast" in metrics
    assert "cpu_core_percent" in metrics
    assert "FROM node_host_latest" in host
    assert "FROM node_storage_current" in filesystems
    assert "_v5057_get_node_overview_history" in overview
    assert "_v5057_get_node_metric_overview_history" in metrics
    assert "_v5057_get_node_host_period_history" in host
    assert "_v5057_get_node_filesystems_snapshot_history" in filesystems
