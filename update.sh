#!/usr/bin/env bash
set -Eeuo pipefail
REPO="${BW_GITHUB_REPO:-}"
REF="${BW_GITHUB_REF:-}"
if [[ -r /etc/default/bw-monitor ]]; then
  set -a
  . /etc/default/bw-monitor
  set +a
fi
REPO="${REPO:-${BW_GITHUB_REPO:-tuanchu1121/virtinfra-monitor}}"
REF="${REF:-${BW_GITHUB_REF:-main}}"
export BW_GITHUB_REPO="$REPO" BW_GITHUB_REF="$REF" BW_BOOTSTRAP_ACTION=update
exec bash -c 'curl -fsSL "https://raw.githubusercontent.com/$BW_GITHUB_REPO/$BW_GITHUB_REF/install.sh" | BW_BOOTSTRAP_ACTION=update bash -s -- "$@"' _ "$@"
