from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "deploy" / "postgres" / "install-postgres-native.sh"
SERVICE = ROOT / "deploy" / "postgres" / "bw-monitor.service"


def test_release_identity():
    expected = "50.6.0-prod-r2-node-groups-update-detection-fix"
    assert (ROOT / "VERSION").read_text().strip() == expected
    assert f'RELEASE="{expected}"' in INSTALLER.read_text()


def test_update_detection_does_not_require_pg_env_marker():
    text = INSTALLER.read_text()
    assert 'APP_PRESENT=0; ENV_PRESENT=0; SERVICE_PRESENT=0; PG_ENV_PRESENT=0' in text
    assert 'if ((APP_PRESENT && ENV_PRESENT && SERVICE_PRESENT)); then' in text
    assert '[[ -r "$PG_ENV" ]] && PG_ENV_PRESENT=1' in text
    assert '[[ -r "$ENV_FILE" && -r "$PG_ENV" ]]' not in text
    assert '--update requires an existing v50 installation.' not in text


def test_missing_pg_env_is_recovered_without_generating_a_new_db_password():
    text = INSTALLER.read_text()
    assert 'EXISTING_DSN="${BW_POSTGRES_DSN:-${BW_DATABASE_URL:-}}"' in text
    assert 'docker inspect bw-timescaledb' in text
    assert 'Could not recover the existing PostgreSQL password.' in text
    recovery_pos = text.index('if ((!PG_ENV_PRESENT)); then')
    random_pos = text.index('[[ -n "$PG_PASSWORD" ]] || PG_PASSWORD="$(random_hex 32)"')
    assert recovery_pos < random_pos


def test_non_local_existing_dsn_is_refused():
    text = INSTALLER.read_text()
    assert '127.0.0.1|localhost|::1' in text
    assert 'Existing PostgreSQL DSN points to non-local host' in text


def test_node_groups_is_compiled_before_service_start():
    text = SERVICE.read_text()
    assert '/opt/bw-monitor/node_groups.py' in text


def test_all_vendored_flags_are_present():
    flags = list((ROOT / "static" / "flags" / "4x3").glob("*.svg"))
    assert len(flags) == 271
    for code in ("jp", "us", "sg", "vn", "gb"):
        assert (ROOT / "static" / "flags" / "4x3" / f"{code}.svg").is_file()


def test_installer_replaces_flag_directory_atomically_enough_for_update():
    text = INSTALLER.read_text()
    assert 'rm -rf "$APP_DIR/static/flags/4x3"' in text
    assert 'find "$REPO_ROOT/static/flags/4x3"' in text
