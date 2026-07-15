#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
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
[[ "$(cat VERSION)" == "50.4.2-prod-r1-consumption-auth-fix" ]] || fail "VERSION mismatch"
[[ -f app/app.py && -f app/bw_pg.py && -f deploy/agent/agent.py ]] || fail "full source tree is incomplete"
[[ ! -d release && ! -d enterprise ]] || fail "legacy duplicate runtime trees must not be shipped"

log "Reject generated data, caches and obvious secrets"
find . -path './.git' -prune -o -path './dist' -prune -o -type d -name __pycache__ -prune -exec rm -rf {} +
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
if ! "$PYTHON" -c 'import flask, werkzeug, psycopg, psycopg_pool, yaml' >/dev/null 2>&1; then
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

log "Validate standalone repository contract"
"$PYTHON" tests/test_repository_contract.py

log "Run storage V2 contract and multi-NIC regression"
"$PYTHON" tests/test_storage_v2_contract.py

log "Validate source-accurate operations documentation"
"$PYTHON" tests/test_docs_source_accuracy.py

log "Run compact Bandwidth Consumption Agent regression"
"$PYTHON" tests/test_bandwidth_consumption_agent.py

log "Validate Consumption endpoint authentication contract"
"$PYTHON" tests/test_consumption_auth_contract.py

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

find . -path './.git' -prune -o -path './dist' -prune -o -type d -name __pycache__ -prune -exec rm -rf {} +
find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -not -path './.git/*' -not -path './dist/*' -delete
printf '\nPASS: VirtInfra Monitor v50 PostgreSQL Native preflight\n'
