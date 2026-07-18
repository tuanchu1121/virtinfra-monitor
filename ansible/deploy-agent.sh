#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INVENTORY=""
API="${BW_AGENT_API:-}"
TOKEN="${BW_AGENT_TOKEN:-}"
LIMIT=""
FORKS="20"
SERIAL="10"

usage() {
  echo 'Usage: deploy-agent.sh -i inventory.ini --api URL --token TOKEN [--limit PATTERN] [--forks N] [--serial N]'
}
while (($#)); do
  case "$1" in
    -i|--inventory) INVENTORY="${2:?missing value}"; shift 2 ;;
    --api) API="${2:?missing value}"; shift 2 ;;
    --token) TOKEN="${2:?missing value}"; shift 2 ;;
    --limit) LIMIT="${2:?missing value}"; shift 2 ;;
    --forks) FORKS="${2:?missing value}"; shift 2 ;;
    --serial) SERIAL="${2:?missing value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done
[[ -n "$INVENTORY" && -f "$INVENTORY" ]] || { usage; echo 'Inventory file is required.' >&2; exit 1; }
[[ -n "$API" ]] || { echo 'Missing --api or BW_AGENT_API.' >&2; exit 1; }
[[ -n "$TOKEN" ]] || { echo 'Missing --token or BW_AGENT_TOKEN.' >&2; exit 1; }
command -v ansible-playbook >/dev/null 2>&1 || { echo 'ansible-playbook is not installed.' >&2; exit 1; }

vars_file="$(mktemp)"
trap 'rm -f "$vars_file"' EXIT
chmod 0600 "$vars_file"
python3 - "$vars_file" "$API" "$TOKEN" "$SERIAL" <<'PY'
import json, sys
with open(sys.argv[1], 'w', encoding='utf-8') as f:
    json.dump({'bwagent_api': sys.argv[2], 'bwagent_token': sys.argv[3], 'bwagent_serial': int(sys.argv[4])}, f)
PY
args=(ansible-playbook -i "$INVENTORY" "$SCRIPT_DIR/deploy-agent.yml" --forks "$FORKS" -e "@$vars_file")
[[ -z "$LIMIT" ]] || args+=(--limit "$LIMIT")
ANSIBLE_HOST_KEY_CHECKING="${ANSIBLE_HOST_KEY_CHECKING:-False}" "${args[@]}"
