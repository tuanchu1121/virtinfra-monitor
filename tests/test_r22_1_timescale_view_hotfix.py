from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "postgres/sql/002_timescale.sql").read_text(encoding="utf-8")


def test_timescale_bootstrap_checks_relation_kind_before_conversion():
    assert 'relation_kind "char"' in SQL
    assert "IF relation_kind IN ('r', 'p') THEN" in SQL
    assert "skipping hypertable conversion" in SQL


def test_legacy_consumption_compatibility_views_remain_listed_but_are_skipped():
    assert "('bandwidth_hourly', 'hour_start'" in SQL
    assert "('bandwidth_daily', 'day_start'" in SQL
    assert "to_regclass('public.' || r.table_name)" not in SQL


def test_failed_update_resume_includes_backup_timer():
    provision = (ROOT / "deploy/postgres/provision-postgres-native.sh").read_text(encoding="utf-8")
    resume_block = provision.split("resume_update_services(){", 1)[1].split("}", 1)[0]
    assert "bw-monitor-backup.timer" in resume_block
