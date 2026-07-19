#!/usr/bin/env bash
set -Eeuo pipefail
DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "/opt/bw-monitor/backup.sh" && "$(readlink -f "/opt/bw-monitor/backup.sh")" != "$(readlink -f "$0")" ]]; then exec bash "/opt/bw-monitor/backup.sh" "$@"; fi
exec bash "$DIR/deploy/postgres/backup.sh" "$@"
