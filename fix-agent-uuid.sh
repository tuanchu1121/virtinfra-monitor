#!/usr/bin/env bash
set -Eeuo pipefail
REPO="${BW_GITHUB_REPO:-tuanchu1121/virtinfra-monitor}"
REF="${BW_GITHUB_REF:-main}"
TOKEN="${GITHUB_TOKEN:-}"
SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$PWD}")" 2>/dev/null && pwd || true)"
if [[ -f "$SELF_DIR/deploy/agent/fix-agent-uuid.sh" ]]; then
  exec bash "$SELF_DIR/deploy/agent/fix-agent-uuid.sh" "$@"
fi
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
if [[ -n "$TOKEN" ]]; then
  curl -fsSL --retry 3 --connect-timeout 15 \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.github.raw+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/repos/$REPO/contents/deploy/agent/fix-agent-uuid.sh?ref=$REF" -o "$TMP"
else
  curl -fsSL --retry 3 --connect-timeout 15 \
    "https://raw.githubusercontent.com/$REPO/$REF/deploy/agent/fix-agent-uuid.sh" -o "$TMP"
fi
exec bash "$TMP" "$@"
