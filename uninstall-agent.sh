#!/usr/bin/env bash
set -Eeuo pipefail
REPO="${BW_GITHUB_REPO:-tuanchu1121/bw-monitor-production.1}"
REF="${BW_GITHUB_REF:-main}"
TOKEN="${GITHUB_TOKEN:-}"
TMP=""
trap '[[ -n "$TMP" ]] && rm -rf "$TMP"' EXIT
SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$PWD}")" 2>/dev/null && pwd || true)"
if [[ -f "$SELF_DIR/deploy/agent/uninstall-agent.sh" ]]; then
  exec bash "$SELF_DIR/deploy/agent/uninstall-agent.sh" "$@"
fi
command -v curl >/dev/null 2>&1 || { echo 'curl is required' >&2; exit 1; }
TMP="$(mktemp -d)"
if [[ -n "$TOKEN" ]]; then
  curl -fsSL --retry 3 --connect-timeout 15 \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.github.raw+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/repos/$REPO/contents/deploy/agent/uninstall-agent.sh?ref=$REF" \
    -o "$TMP/uninstall-agent.sh"
else
  curl -fsSL --retry 3 --connect-timeout 15 \
    "https://raw.githubusercontent.com/$REPO/$REF/deploy/agent/uninstall-agent.sh" \
    -o "$TMP/uninstall-agent.sh"
fi
chmod +x "$TMP/uninstall-agent.sh"
exec bash "$TMP/uninstall-agent.sh" "$@"
