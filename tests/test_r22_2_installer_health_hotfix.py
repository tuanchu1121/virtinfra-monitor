from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_timescale_conversion_skips_views():
    sql = (ROOT / "postgres/sql/002_timescale.sql").read_text(encoding="utf-8")
    assert "IF relation_kind IN ('r', 'p') THEN" in sql
    assert "skipping hypertable conversion" in sql


def test_health_endpoints_bypass_dashboard_login():
    source = (ROOT / "app/runtime_layers/07_page_shell_auth_hook.py").read_text(encoding="utf-8")
    assert '"virtinfra_livez"' in source
    assert '"virtinfra_healthz"' in source


def test_internal_health_checks_reject_redirects():
    maintenance = (ROOT / "app/maintenance.py").read_text(encoding="utf-8")
    watchdog = (ROOT / "deploy/postgres/virtinfra-monitor-health-watch.sh").read_text(encoding="utf-8")
    assert "redirected to {final_url}" in maintenance
    assert "[[ \"$code\" == \"200\" ]]" in watchdog


def test_update_failure_restores_backup_timer():
    provision = (ROOT / "deploy/postgres/provision-postgres-native.sh").read_text(encoding="utf-8")
    assert "bw-monitor-backup.timer" in provision
