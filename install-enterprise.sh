#!/usr/bin/env bash
# Backward-compatible name. v50 is PostgreSQL Native and has no hybrid Enterprise data plane.
set -Eeuo pipefail
DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$DIR/install.sh" "$@"
