#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Keep validation deterministic and avoid unrelated globally installed pytest
# plugins holding the process open after the suite has already completed.
export PYTEST_DISABLE_PLUGIN_AUTOLOAD="${PYTEST_DISABLE_PLUGIN_AUTOLOAD:-1}"
PYTHON="${BW_PREFLIGHT_PYTHON:-}"
USE_CURRENT=0
SKIP_LIVE=0
while (($#)); do
  case "$1" in
    --use-current-python) USE_CURRENT=1; shift ;;
    --skip-live) SKIP_LIVE=1; shift ;;
    -h|--help)
      cat <<'EOF'
Usage: ./preflight.sh [--use-current-python] [--skip-live]

Validates the complete PostgreSQL-native source tree. Live integration runs only
when BW_TEST_DATABASE_URL points at a disposable PostgreSQL database.
EOF
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
log(){ printf '\n==> %s\n' "$*"; }
fail(){ echo "ERROR: $*" >&2; exit 1; }
cd "$ROOT"

log "Validate release identity"
[[ "$(cat VERSION)" == "50.5.9-prod-r2-ui-layout-polish-only" ]] || fail "VERSION mismatch"
[[ -f app/app.py && -f app/bw_pg.py && -f app/maintenance_native.py \
   && -f app/maintenance_queue.py && -f app/maintenance_dispatch.py \
   && -f postgres/sql/007_safe_maintenance_queue.sql \
   && -f postgres/sql/010_consumption_inventory_cleanup.sql \
   && -f app/inventory_cleanup.py && -f app/consumption_rollup.py \
   && -f deploy/postgres/bw-monitor-inventory-cleanup.timer \
   && -f deploy/agent/agent.py && -f deploy/agent/fix-agent-uuid.sh ]] \
|| fail "full source tree is incomplete"
[[ ! -d release && ! -d enterprise ]] || fail "legacy duplicate runtime trees must not be shipped"

log "Verify canonical source checksum manifest"
[[ -f SHA256SUMS ]] || fail "SHA256SUMS is missing"
sha256sum -c SHA256SUMS >/dev/null || fail "SHA256SUMS contains stale or missing hashes"
python3 tests/test_manifest_contract.py

log "Reject generated data, caches and obvious secrets"
find . -path './.git' -prune -o -path './dist' -prune -o -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} +
find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -not -path './.git/*' -not -path './dist/*' -delete
bad="$(find . -path './.git' -prune -o -path './dist' -prune -o -type f \( -name 'bandwidth.db*' -o -name '*.sqlite' -o -name '*.sqlite3' -o -name '*.dump' -o -name '*.sql.gz' \) -print)"
[[ -z "$bad" ]] || { printf '%s\n' "$bad"; fail "generated database/backup files are present"; }
if grep -RInE --exclude-dir=.git --exclude-dir=dist --exclude=SHA256SUMS --exclude='*.md' \
  '(bwm_push_[A-Za-z0-9]{40,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY)' .; then
  fail "potential committed secret detected"
fi

log "Validate shell syntax"
while IFS= read -r -d '' file; do
  echo "bash -n $file"
  bash -n "$file"
done < <(find . -path './.git' -prune -o -path './dist' -prune -o -type f -name '*.sh' -print0)

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

log "Validate YAML syntax"
"$PYTHON" - <<'PY'
from pathlib import Path
import yaml
for path in sorted(Path('ansible').glob('*.yml')) + sorted(Path('.github/workflows').glob('*.yml')):
    yaml.safe_load(path.read_text(encoding='utf-8'))
    print('YAML OK:', path)
PY

log "Run v50 source contract"
"$PYTHON" tests/test_v50_contract.py

log "Validate v50.5.2 native COPY ingest contract"
"$PYTHON" -m pytest -q tests/test_v5052_native_copy_ingest.py

log "Validate v50.5.4 selected-snapshot detail correctness"
"$PYTHON" -m pytest -q tests/test_v5054_snapshot_detail_correctness.py

log "Validate v50.5.5 PostgreSQL LIKE compatibility hotfix"
"$PYTHON" -m pytest -q tests/test_v5055_sql_compat_hotfix.py

log "Validate v50.5.6 PostgreSQL-native maintenance compatibility"
"$PYTHON" -m pytest -q tests/test_v5056_postgres_native_maintenance.py

log "Validate v50.5.7 safe FIFO queue and canonical VM detail"
"$PYTHON" -m pytest -q tests/test_v5057_safe_queue_canonical_vm.py

log "Validate standalone repository contract"
"$PYTHON" tests/test_repository_contract.py

log "Run storage V2 contract and multi-NIC regression"
"$PYTHON" tests/test_storage_v2_contract.py

log "Validate source-accurate operations documentation"
"$PYTHON" tests/test_docs_source_accuracy.py

log "Validate Agent v15 single five-minute Consumption delivery path"
"$PYTHON" tests/test_bandwidth_consumption_agent.py

log "Validate Consumption endpoint authentication contract"
"$PYTHON" tests/test_consumption_auth_contract.py

log "Validate Consumption neutral UI contract"
"$PYTHON" tests/test_consumption_ui_contract.py

log "Validate fast Consumption and deadlock-safe inventory contract"
"$PYTHON" -m pytest -q tests/test_v5058_r4_consumption_inventory.py

log "Validate protected core and simple theme selector contract"
"$PYTHON" tests/test_theme_manager_contract.py
"$PYTHON" tests/test_custom_theme_runtime.py

log "Validate v50.5.9 r1 responsive UI, theme and chart-gap contract"
"$PYTHON" -m pytest -q tests/test_v5059_r1_ui_responsive_theme_chart_gaps.py

log "Validate route, endpoint, query, form, sort, Agent and SQL equivalence"
"$PYTHON" -m pytest -q tests/test_v5059_r1_contract_equivalence.py

log "Validate v50.5.9 r2 presentation-only layout polish"
"$PYTHON" -m pytest -q tests/test_v5059_r2_ui_layout_polish_only.py

log "Verify one-command installer and operations flow"
bash ./tools/test-installer-flow.sh

if ((SKIP_LIVE)); then
  log "Skip live PostgreSQL integration by request"
elif [[ -n "${BW_TEST_DATABASE_URL:-}" ]]; then
  log "Run full application integration against disposable PostgreSQL"
  "$PYTHON" tests/test_v50_postgres_integration.py
else
  log "Skip live PostgreSQL integration because BW_TEST_DATABASE_URL is not set"
fi

log "Check documentation for stale runtime architecture"
if grep -RInE --exclude='MIGRATION_NOT_SUPPORTED.md' \
  '(SQLite WAL|bandwidth\.db|Redis Streams|hybrid data plane|deploy/enterprise|deploy/monitor)' README.md docs; then
  fail "stale SQLite/hybrid runtime documentation remains"
fi

find . -path './.git' -prune -o -path './dist' -prune -o -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} +
find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -not -path './.git/*' -not -path './dist/*' -delete
printf '\nPASS: VirtInfra Monitor v50 PostgreSQL Native preflight\n'
