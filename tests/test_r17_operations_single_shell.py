from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "app/node_groups.py"
VERSION = "50.5.9-prod-r22.12.2-preflight-contract-hotfix"


def _load_module():
    spec = importlib.util.spec_from_file_location("node_groups_r17_contract", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_release_and_operations_navigation_contract() -> None:
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == VERSION
    text = MODULE.read_text(encoding="utf-8")
    assert 'items.append(("admin_page", "Operations"))' in text
    assert 'current_role() in {"admin", "super_admin"}' in text
    assert 'Short-term infrastructure monitoring, inventory and maintenance operations.' in text
    assert '"maintenance", "Maintenance"' in text
    assert 'if is_super_admin():' in text and '"api", "API"' in text


def test_node_flag_is_limited_to_visible_node_identity() -> None:
    module = _load_module()
    module._groups_for_node_links = lambda nodes: {node: ("Germany", "de") for node in nodes}
    module.flag_html = lambda country: f'<img class="node-group-flag" alt="{country}">'
    html = (
        '<a href="/node/node-de"><b>node-de</b></a>'
        '<a href="/node/node-de?period=5m">5m</a>'
        '<a href="/node/node-de?period=10m">10m</a>'
        '<a href="/node/node-de?net=both">Both Cards</a>'
        '<a href="/node/node-de?net=public">Public Only</a>'
        '<a href="/node/node-de?net=private">Private Only</a>'
        '<a href="/node/node-de?sort=rx">RX</a>'
        '<a href="/node/node-de?sort=tx">TX</a>'
        '<a href="/node/node-de?sort=total">TOTAL</a>'
        '<a href="/node/node-de?sort=mbps">AVG Mbps</a>'
        '<a href="/node/node-de?sort=peakmbps">PEAK Mbps</a>'
        '<a href="/node/node-de?sort=pps">AVG PPS</a>'
        '<a href="/node/node-de?sort=peakpps">PEAK PPS</a>'
        '<a href="/node/node-de?sort=sample">SAMPLE</a>'
        '<a href="/node/node-de?sort=cpu">CPU Core%</a>'
        '<a href="/node/node-de?sort=vcpu">vCPU</a>'
        '<a href="/node/node-de?sort=ram">RAM</a>'
        '<a href="/node/node-de?sort=diskr">DISK R/s</a>'
        '<a href="/node/node-de?sort=diskw">DISK W/s</a>'
        '<a href="/node/node-de?sort=drops">DROPS</a>'
        '<a href="/node/node-de?sort=errors">ERR</a>'
        '<a href="/node/node-de">vm-uuid-not-node</a>'
        '<a href="/vm?node=node-de&amp;vm_uuid=vm-1">vm-1</a>'
        '<a href="/node/node-de">← Back to node</a>'
    )
    rendered = module._inject_node_flags(html)
    assert rendered.count("node-group-flag") == 1
    assert '<img class="node-group-flag" alt="de"><b>node-de</b>' in rendered
    for label in (
        "5m", "10m", "Both Cards", "Public Only", "Private Only", "RX", "TX",
        "TOTAL", "AVG Mbps", "PEAK Mbps", "AVG PPS", "PEAK PPS", "SAMPLE",
        "CPU Core%", "vCPU", "RAM", "DISK R/s", "DISK W/s", "DROPS", "ERR",
        "vm-uuid-not-node", "vm-1", "← Back to node",
    ):
        assert f'alt="de">{label}' not in rendered


def test_operator_and_super_admin_permission_split() -> None:
    text = MODULE.read_text(encoding="utf-8")
    whitelist = text.split("ADMIN_ALLOWED_ENDPOINTS", 1)[1].split("}", 1)[0]
    for endpoint in (
        "admin_database_maintenance", "admin_cancel_maintenance_v5057",
        "admin_purge_node_vms", "admin_delete_node", "admin_delete_vm",
    ):
        assert f'"{endpoint}"' in whitelist
    assert 'SUPER_ADMIN_ONLY_MAINTENANCE_ACTIONS' in text
    for action in (
        "clear_monitoring_data", "reset_app_data_preview", "reset_app_data",
        "clear_api_logs", "clear_api_data",
    ):
        assert f'"{action}"' in text
    canonical = (ROOT / "app/runtime_layers/38_agent_maintenance_canonical_routes.py").read_text(encoding="utf-8")
    assert 'sensitive = {' in canonical
    for action in (
        "configuration_backup", "configuration_restore", "configuration_backup_protect",
        "configuration_backup_unprotect", "configuration_backup_delete",
        "configuration_backup_download", "full_backup",
        "full_backup_verify", "full_backup_protect", "full_backup_unprotect",
        "full_backup_delete", "full_backup_download",
        "reset_app_data_preview", "reset_app_data",
    ):
        assert f'"{action}"' in canonical
    assert 'if action not in sensitive' in canonical
    assert 'if role != "super_admin"' in canonical
    assert 'in {"reset_app_data", "configuration_restore"}' in canonical


def test_operations_shell_is_rendered_exactly_once() -> None:
    module = _load_module()

    class Request:
        endpoint = "admin_page"
        path = "/admin"

    class FakeModule:
        request = Request()

        @staticmethod
        def url_for(endpoint, **values):
            if endpoint == "index":
                return "/"
            if endpoint == "admin_logout":
                return "/admin/logout"
            return "/admin"

    module._m = lambda: FakeModule
    module.admin_allowed = lambda: True
    module.current_role = lambda: "admin"
    module._operations_active_section = lambda: "overview"
    module.admin_nav = lambda active: '<nav class="admin-tabs"><a class="active">Overview</a></nav>'

    html = '''
    <html><body><div class="wrap" id="bw-content">
      <div class="card admin-hero operations-hero"><div><span class="eyebrow">OPERATIONS</span><h2>Operations</h2></div><div></div></div>
      <nav class="admin-tabs"><a>Overview</a></nav>
      <div class="retention-policy-strip"><div>Latest 48 hours</div></div>
      <div class="card admin-hero"><div><span class="eyebrow">CONTROL CENTER</span><h2>Administration</h2></div><div></div></div>
      <nav class="admin-tabs"><a>Overview</a></nav>
      <div class="card">Actual page content</div>
    </div></body></html>
    '''
    rendered = module._normalize_operations_shell(html)
    assert rendered.count('class="card admin-hero operations-hero"') == 1
    assert rendered.count('class="admin-tabs"') == 1
    assert "CONTROL CENTER" not in rendered
    assert "Administration</h2>" not in rendered
    assert "Latest 48 hours" in rendered
    assert "Actual page content" in rendered
    assert rendered.index("OPERATIONS") < rendered.index("Latest 48 hours")
