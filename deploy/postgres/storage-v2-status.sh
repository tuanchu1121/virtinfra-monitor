#!/usr/bin/env bash
set -Eeuo pipefail
set -a; . /etc/default/bw-monitor; set +a
exec /opt/bw-monitor/venv/bin/python3 /opt/bw-monitor/tools/storage-v2-status.py "$@"
