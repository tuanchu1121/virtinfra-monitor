import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "50.5.9-prod-r8-safe-dead-code-prune"
REMOVED_SHA256 = {
    "00d199d1498080e198f3dd307cad60c5efe8f3c4544e416529280434201e71c3",  # round 1: app/runtime_layers/12_abuse_policy.py:558 abuse_settings_admin_card
    "02dd66e7ec4f9cc095cf0723524007feaef0a34c7277ec43dca62edaa448169b",  # round 1: app/runtime_layers/12_abuse_policy.py:76 get_agent_runtime_config
    "5959241c364cd9c97445fb4a7ebb92643387dd3b8fe9ce24e9f6178e7996d572",  # round 1: app/runtime_layers/13_admin_abuse_queue.py:71 _insert_abuse_event
    "2ed786294c28c19be28a66bc1a319fbd24260ffcb7957ef524170f337fa5fade",  # round 1: app/runtime_layers/12_abuse_policy.py:158 refresh_fast_current_state
    "2bf92750f093f6028690d1f4e7dd274184ef7a62bdd01a1ac8a08373f51449cd",  # round 1: app/runtime_layers/14_abuse_metrics_ui.py:1037 vm_period_links
    "e23b1064aa1345265e11bd98c1404ffe9a2606fc6150d2b53eb06a136d8afc05",  # round 1: app/runtime_layers/14_abuse_metrics_ui.py:113 get_agent_runtime_config
    "48435ace089766f3e045fa36317fdcf979420b21fa3f60d89d55b06d574f2fd1",  # round 1: app/runtime_layers/14_abuse_metrics_ui.py:222 refresh_fast_current_state
    "151ec71ea1dcbefdc31b92d09d18ad3c5e678733a8e205683c69f568b374be21",  # round 1: app/runtime_layers/14_abuse_metrics_ui.py:329 abuse_settings_admin_card
    "d76692876b6bf371ba57aea5cbb4a4f71935e1bfb67bf0d784f813afd13485d6",  # round 1: app/runtime_layers/18_operations_reset.py:133 top_vm_table
    "c20377900de7f80463be618276d22f59790ac9d2e07fa136df749ef6e18cf2e7",  # round 1: app/runtime_layers/19_guest_ram.py:428 interface_table
    "eaa036a95e4920543c7a68e709c94220efecc3b12c8db868178d576b77b64e69",  # round 1: app/runtime_layers/19_guest_ram.py:42 refresh_fast_current_state
    "d385b19804ea3ab569374aff7eb6a79161da0813bfd8e970ec1ac403d16a68ba",  # round 1: app/runtime_layers/19_guest_ram.py:325 top_vm_table
    "17b3511a83123c06eb5f6feaf57acaa184c9af7b5b2639cb6edf2ce0e08c6cee",  # round 1: app/runtime_layers/09_admin_routes.py:948 purge_vm_data
    "6b3dc0d111a9a8e16d07e0402b1c19f81df3c5c99b789447fcc3926af8942db8",  # round 1: app/runtime_layers/30_inventory_storage_precision.py:707 _v48133_storage_disk_table
    "7b48fbed46573735599201c5a6d0b4d3bb8f503bae2c1369065f4fc299533f25",  # round 1: app/runtime_layers/30_inventory_storage_precision.py:838 _v48133_storage_node_table
    "c2cd997ac2cdf57fedb0c6376d7cb4f5273fc9f8d24d27def3205e99727d9fff",  # round 1: app/runtime_layers/26_abuse_intelligence.py:486 refresh_fast_current_state
    "2e72c93bbc1171d72bc2d4d9059883451aee7bbd76e6b800d1321e30de13771e",  # round 1: app/runtime_layers/36_batched_ingest.py:52 process_node_vm_presence
    "70957e64a8cf46a3770b083b066b20765b4829a58f386fc3f855e580a3c3fd30",  # round 1: app/runtime_layers/32_performance_runtime.py:348 ingest_disk_io_current
    "bd155ada898c6b90354f06182e71905a9846f355906d3e363bc3033b14199ecd",  # round 1: app/runtime_layers/27_abuse_dashboard.py:1298 _v48129_vm_detail_cpu_stat
    "f6f094f0a929847a17bba9c779db79571ab96a7d991de2bd35e1282acb37972c",  # round 1: app/runtime_layers/04_charts_vm.py:502 vm_chart_svg
    "c2d376c710b749ac0c93e44a2b7e85eb907435cda0d99dd75cfa9dc0d98421a9",  # round 1: app/runtime_layers/41_ui_layout_r2.py:494 _v5049_theme_selector_html
    "8fabbbacbd1c660e83c658be077b24e9ccc36203ce2316a1eccb7208538816bc",  # round 1: app/runtime_layers/41_ui_layout_r2.py:515 _v5049_runtime_theme_script
    "8f77597a3f7f026294c62f7649d0417254160e120f7b13812daf10e7acab75f2",  # round 2: app/runtime_layers/12_abuse_policy.py:88 _abuse_state_map
    "10a61f693293c1b71b9071ceb4a30763ac46faccf179f3d36fdbe7616daa603e",  # round 2: app/runtime_layers/12_abuse_policy.py:107 _insert_abuse_event
    "03b24108549d9cee8e5c180be108136786b525bf92b6790d4993843266edc5e1",  # round 2: app/runtime_layers/14_abuse_metrics_ui.py:140 _insert_abuse_event
    "622e91a007471f34374f7c38b2c80ff4ab358f51cf0d204dca9aee8d8661e945",  # round 2: app/runtime_layers/26_abuse_intelligence.py:468 _v48126_ram_hit
}


def canonical_runtime_source() -> str:
    manifest = json.loads((ROOT / "app/runtime_layers/manifest.json").read_text(encoding="utf-8"))
    return "".join((ROOT / "app/runtime_layers" / item["file"]).read_text(encoding="utf-8") for item in manifest)


def test_r8_release_identity_and_audit_report_exist() -> None:
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == EXPECTED_VERSION
    assert (ROOT / "DEAD_CODE_AUDIT_R8.md").is_file()


def test_removed_implementation_hashes_are_absent() -> None:
    import ast
    source = canonical_runtime_source()
    tree = ast.parse(source)
    lines = source.splitlines()
    remaining = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            segment = "\n".join(lines[node.lineno - 1 : node.end_lineno])
            remaining.add(hashlib.sha256(segment.encode()).hexdigest())
    assert REMOVED_SHA256.isdisjoint(remaining)


def test_runtime_manifest_is_contiguous_and_hash_pinned() -> None:
    manifest = json.loads((ROOT / "app/runtime_layers/manifest.json").read_text(encoding="utf-8"))
    expected_start = 1
    for item in manifest:
        path = ROOT / "app/runtime_layers" / item["file"]
        data = path.read_bytes()
        line_count = len(data.decode("utf-8").splitlines())
        assert item["start_line"] == expected_start
        assert item["end_line"] == expected_start + line_count - 1
        assert item["sha256"] == hashlib.sha256(data).hexdigest()
        expected_start = item["end_line"] + 1
    assert expected_start - 1 == 35241
