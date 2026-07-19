#!/usr/bin/env bash
set -Eeuo pipefail
REPO="${BW_GITHUB_REPO:-tuanchu1121/virtinfra-monitor}"
REF="${BW_GITHUB_REF:-main}"
TOKEN="${GITHUB_TOKEN:-}"
TMP=""
trap '[[ -n "$TMP" ]] && rm -rf "$TMP"' EXIT
SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$PWD}")" 2>/dev/null && pwd || true)"
if [[ -f "$SELF_DIR/deploy/agent/install-agent.sh" ]]; then
  exec bash "$SELF_DIR/deploy/agent/install-agent.sh" "$@"
fi
command -v curl >/dev/null 2>&1 || { echo 'curl is required' >&2; exit 1; }
TMP="$(mktemp -d)"; mkdir -p "$TMP/deploy/agent"
fetch(){
  local path="$1" out="$2"
  if [[ -n "$TOKEN" ]]; then
    curl -fsSL --retry 3 --connect-timeout 15 \
      -H "Authorization: Bearer $TOKEN" \
      -H "Accept: application/vnd.github.raw+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/$REPO/contents/$path?ref=$REF" -o "$out"
  else
    curl -fsSL --retry 3 --connect-timeout 15 \
      "https://raw.githubusercontent.com/$REPO/$REF/$path" -o "$out"
  fi
}
fetch deploy/agent/install-agent.sh "$TMP/deploy/agent/install-agent.sh"
fetch deploy/agent/agent.py "$TMP/deploy/agent/agent.py"
fetch deploy/agent/doctor-agent.sh "$TMP/deploy/agent/doctor-agent.sh"
chmod +x "$TMP/deploy/agent/install-agent.sh" "$TMP/deploy/agent/doctor-agent.sh"
exec bash "$TMP/deploy/agent/install-agent.sh" "$@"
