#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INVENTORY=""
LIMIT=""
FORKS="20"
KEEP_STATE=0
while (($#)); do
  case "$1" in
    -i|--inventory) INVENTORY="${2:?missing value}"; shift 2 ;;
    --limit) LIMIT="${2:?missing value}"; shift 2 ;;
    --forks) FORKS="${2:?missing value}"; shift 2 ;;
    --keep-state) KEEP_STATE=1; shift ;;
    -h|--help) echo 'Usage: remove-agent.sh -i inventory.ini [--limit PATTERN] [--forks N] [--keep-state]'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done
[[ -n "$INVENTORY" && -f "$INVENTORY" ]] || { echo 'Inventory file is required.' >&2; exit 1; }
args=(ansible-playbook -i "$INVENTORY" "$SCRIPT_DIR/remove-agent.yml" --forks "$FORKS" -e "bwagent_keep_state=$KEEP_STATE")
[[ -z "$LIMIT" ]] || args+=(--limit "$LIMIT")
ANSIBLE_HOST_KEY_CHECKING="${ANSIBLE_HOST_KEY_CHECKING:-False}" "${args[@]}"
