#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD="${PYTEST_DISABLE_PLUGIN_AUTOLOAD:-1}"
PYTHON="${BW_PREFLIGHT_PYTHON:-}"
USE_CURRENT=0
SKIP_LIVE=0
while (($#)); do
  case "$1" in
    --use-current-python) USE_CURRENT=1; shift ;;
    --skip-live) SKIP_LIVE=1; shift ;;
    -h|--help)
      cat <<'HELP'
Usage: ./preflight.sh [--use-current-python] [--skip-live]

Validates only the current production source and current runtime contracts.
Live integration runs only when BW_TEST_DATABASE_URL points at a disposable PostgreSQL database.
HELP
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
log(){ printf '\n==> %s\n' "$*"; }
fail(){ echo "ERROR: $*" >&2; exit 1; }
run_isolated(){
  local success_pattern="$1"; shift
  "$PYTHON" tools/run-isolated-validation.py \
    --timeout "${BW_PREFLIGHT_TEST_TIMEOUT_SECONDS:-120}" \
    --success-pattern "$success_pattern" -- "$@"
}
run_pytest(){
  run_isolated '([0-9]+ passed|[0-9]+ skipped)(, [0-9]+ skipped)? in [0-9.]+' \
    "$PYTHON" -m pytest "$@"
}
run_contract(){
  run_isolated '^PASS:' "$PYTHON" "$@"
}
cd "$ROOT"

log "Validate current release identity"
[[ "$(cat VERSION)" == "50.5.9-prod-r22.12.3-slim-current-only" ]] || fail "VERSION mismatch"
required=(
  app/app.py app/runtime_loader.py app/bw_pg.py app/node_groups.py
  app/runtime_layers/manifest.json
  app/runtime_layers/44_consumption_node_vm_rollup.py
  app/runtime_layers/47_vm_5m_slot_rolling_window.py
  app/runtime_layers/48_vm_consumption_shared_snapshot.py
  app/vm_consumption_snapshot.py
  postgres/sql/017_vm_consumption_5m_slots.sql
  postgres/sql/018_vm_consumption_slot_boundary_semantics.sql
  postgres/sql/019_vm_consumption_shared_snapshot.sql
  deploy/postgres/provision-postgres-native.sh
  deploy/postgres/bw-monitor-vm-consumption-snapshot.service
  deploy/postgres/bw-monitor-vm-consumption-snapshot.timer
  tests/test_current_release_contract.py
  tests/test_current_vm_5m_slot_rolling.py
  tests/test_current_vm_slot_boundary_coverage.py
  tests/test_current_vm_consumption_shared_snapshot.py
)
for file in "${required[@]}"; do [[ -f "$file" ]] || fail "missing current source: $file"; done
[[ ! -d release && ! -d enterprise ]] || fail "legacy duplicate runtime trees must not be shipped"

log "Verify canonical source checksum manifest"
[[ -f SHA256SUMS ]] || fail "SHA256SUMS is missing"
sha256sum -c SHA256SUMS >/dev/null || fail "SHA256SUMS contains stale or missing hashes"
python3 tests/test_manifest_contract.py

log "Reject generated data, caches, historical release payloads and obvious secrets"
find . -path './.git' -prune -o -path './.venv' -prune -o -path './artifacts' -prune -o -path './dist' -prune -o -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} +
find . \( -path './.git' -o -path './.venv' -o -path './artifacts' -o -path './dist' \) -prune -o -type f \( -name '*.pyc' -o -name '*.pyo' \) -exec rm -f {} +
bad="$(find . -path './.git' -prune -o -path './.venv' -prune -o -path './artifacts' -prune -o -path './dist' -prune -o -type f \( -name 'bandwidth.db*' -o -name '*.sqlite' -o -name '*.sqlite3' -o -name '*.dump' -o -name '*.sql.gz' -o -name '*.log' \) -print)"
[[ -z "$bad" ]] || { printf '%s\n' "$bad"; fail "generated database/backup/log files are present"; }
if find . -maxdepth 1 -type f \( -name 'VALIDATION_REPORT_R*.md' -o -name 'R22*_CHANGESET.md' -o -name 'BENCHMARK_REPORT_R*.md' -o -name 'QUERY_PLAN_REPORT_R*.md' -o -name 'EXPLAIN_ANALYZE_R*.json' \) | grep -q .; then
  fail "historical release reports remain"
fi
if find tests -maxdepth 1 -type f \( -name 'test_r[0-9]*.py' -o -name 'test_v[0-9]*.py' \) | grep -q .; then
  fail "legacy version-specific tests remain"
fi
if grep -RInE --exclude-dir=.git --exclude-dir=.venv --exclude-dir=artifacts --exclude-dir=dist --exclude=SHA256SUMS --exclude='*.md' \
  '(bwm_push_[A-Za-z0-9]{40,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY)' .; then
  fail "potential committed secret detected"
fi

log "Validate shell syntax"
while IFS= read -r -d '' file; do bash -n "$file"; done < <(find . -path './.git' -prune -o -path './.venv' -prune -o -path './artifacts' -prune -o -path './dist' -prune -o -type f -name '*.sh' -print0)

if [[ -z "$PYTHON" ]]; then
  if ((USE_CURRENT)); then
    PYTHON="$(command -v python3)"
  else
    log "Create isolated validation environment"
    python3 -m venv "$TMP/venv"
    PYTHON="$TMP/venv/bin/python3"
    "$PYTHON" -m pip install --upgrade pip >/dev/null
    "$PYTHON" -m pip install -r requirements.txt PyYAML >/dev/null
  fi
fi
[[ -x "$PYTHON" ]] || fail "Python not executable: $PYTHON"
if ! "$PYTHON" -c 'import flask, werkzeug, psycopg, psycopg_pool, yaml, pytest' >/dev/null 2>&1; then
  "$PYTHON" -m pip install -r requirements.txt PyYAML >/dev/null
fi

log "Validate Python syntax"
mapfile -d '' pyfiles < <(find app deploy/agent tests tools -type f -name '*.py' -print0)
"$PYTHON" -m py_compile "${pyfiles[@]}"

log "Validate current runtime architecture and source cleanliness"
run_pytest -q tests/test_modular_runtime_architecture.py tests/test_runtime_source_cleanliness.py tests/test_current_release_contract.py

log "Validate current VM Consumption pipeline"
run_pytest -q \
  tests/test_current_vm_5m_slot_rolling.py \
  tests/test_current_vm_slot_boundary_coverage.py \
  tests/test_current_vm_consumption_shared_snapshot.py

log "Validate current Node Groups loader"
run_pytest -q tests/test_node_groups_importlib_loader.py

log "Validate current source contracts"
run_contract tests/test_repository_contract.py
run_contract tests/test_current_hardening.py
run_contract tests/test_storage_v2_contract.py
run_contract tests/test_docs_source_accuracy.py
run_contract tests/test_bandwidth_consumption_agent.py
run_contract tests/test_consumption_auth_contract.py
run_contract tests/test_consumption_ui_contract.py
run_contract tests/test_theme_manager_contract.py
run_contract tests/test_custom_theme_runtime.py

log "Validate YAML syntax"
"$PYTHON" - <<'PY'
from pathlib import Path
import yaml
for path in sorted(Path('ansible').glob('*.yml')) + sorted(Path('.github/workflows').glob('*.yml')):
    yaml.safe_load(path.read_text(encoding='utf-8'))
    print('YAML OK:', path)
PY

log "Verify one-command installer and operations flow"
bash ./tools/test-installer-flow.sh
bash ./tools/test-installer-manifest-paths.sh

if ((SKIP_LIVE)); then
  log "Skip live PostgreSQL integration by request"
elif [[ -n "${BW_TEST_DATABASE_URL:-}" ]]; then
  log "Run current PostgreSQL application integration"
  run_pytest -q tests/test_current_postgres_integration.py tests/test_node_groups_postgres_integration.py
else
  log "Skip live PostgreSQL integration because BW_TEST_DATABASE_URL is not set"
fi

log "Check documentation for stale runtime architecture"
if grep -RInE --exclude='MIGRATION_NOT_SUPPORTED.md' \
  '(SQLite WAL|bandwidth\.db|Redis Streams|hybrid data plane|deploy/enterprise|deploy/monitor)' README.md docs; then
  fail "stale datastore/hybrid runtime documentation remains"
fi

find . -path './.git' -prune -o -path './.venv' -prune -o -path './artifacts' -prune -o -path './dist' -prune -o -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} +
find . \( -path './.git' -o -path './.venv' -o -path './artifacts' -o -path './dist' \) -prune -o -type f \( -name '*.pyc' -o -name '*.pyo' \) -exec rm -f {} +
printf '\nPASS: current VirtInfra Monitor production preflight\n'
