#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
USE_CURRENT=0
SKIP_LIVE=0
while (($#)); do
  case "$1" in
    --use-current-python) USE_CURRENT=1; shift ;;
    --skip-live) SKIP_LIVE=1; shift ;;
    -h|--help) echo "Usage: $0 [--use-current-python] [--skip-live]"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
cd "$ROOT"

printf '\n==> Refresh repository checksum manifest before preflight\n'
find . \
  -path './.git' -prune -o \
  -path './.venv' -prune -o \
  -path './artifacts' -prune -o \
  -path './dist' -prune -o \
  -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -o \
  -type f ! -name SHA256SUMS ! -name '*.pyc' ! -name '*.pyo' -print0 \
| sort -z | xargs -0 sha256sum > SHA256SUMS
sha256sum -c SHA256SUMS >/dev/null

args=()
((USE_CURRENT)) && args+=(--use-current-python)
((SKIP_LIVE)) && args+=(--skip-live)
bash ./preflight.sh "${args[@]}"

printf '\n==> Verify product shell entry points\n'
for f in install.sh update.sh uninstall.sh install-agent.sh uninstall-agent.sh \
  deploy/postgres/*.sh deploy/agent/*.sh ansible/*.sh tools/*.sh; do
  [[ -f "$f" ]] || continue
  head -n 1 "$f" | grep -Eq '^#!/usr/bin/env bash$|^#!/bin/bash$' || { echo "Missing bash shebang: $f" >&2; exit 1; }
  bash -n "$f"
done

printf '\n==> Verify Windows GitHub Desktop mode compatibility\n'
bash ./tools/test-windows-github-desktop.sh

printf '\n==> Verify no duplicate/stale runtime trees\n'
[[ ! -e release && ! -e enterprise && ! -e deploy/monitor && ! -e deploy/enterprise ]]
[[ -f app/app.py && -f app/runtime_loader.py \
   && -f app/runtime_layers/manifest.json \
   && -f app/runtime_layers/00_bootstrap_database.py \
   && -f app/runtime_layers/43_node_groups_loader.py \
   && -f app/bw_pg.py && -f app/maintenance.py \
   && -f app/maintenance_native.py && -f app/maintenance_queue.py \
   && -f app/maintenance_dispatch.py && -f app/retention.py ]]
[[ -f deploy/agent/agent.py && -f deploy/agent/install-agent.sh && -f deploy/agent/fix-agent-uuid.sh ]]
[[ -f postgres/sql/007_safe_maintenance_queue.sql ]]

printf '\n==> Generate repository checksum manifest\n'
find . \
  -path './.git' -prune -o \
  -path './.venv' -prune -o \
  -path './artifacts' -prune -o \
  -path './dist' -prune -o \
  -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -o \
  -type f ! -name SHA256SUMS -print0 \
| sort -z | xargs -0 sha256sum > SHA256SUMS
sha256sum -c SHA256SUMS >/dev/null

printf '\nPASS: VirtInfra Monitor v50 release audit\n'
