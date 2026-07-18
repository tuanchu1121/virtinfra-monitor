#!/usr/bin/env bash
set -Eeuo pipefail
DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "/opt/bw-monitor/collect-diagnostics.sh" && "$(readlink -f "/opt/bw-monitor/collect-diagnostics.sh")" != "$(readlink -f "$0")" ]]; then exec bash "/opt/bw-monitor/collect-diagnostics.sh" "$@"; fi
exec bash "$DIR/deploy/postgres/collect-diagnostics.sh" "$@"
