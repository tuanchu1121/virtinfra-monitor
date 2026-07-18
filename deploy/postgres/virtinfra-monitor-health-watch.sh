#!/usr/bin/env bash
set -Eeuo pipefail
ENV=/etc/default/bw-monitor
[[ -r "$ENV" ]] && { set -a; . "$ENV"; set +a; }
port="${BW_PUBLIC_PORT:-8080}"
state=/run/virtinfra-monitor-health-watch.failures
failures=0; [[ -r "$state" ]] && read -r failures < "$state" || true
if curl -fsS --connect-timeout 2 --max-time 4 "http://127.0.0.1:${port}/livez" >/dev/null; then
  printf '0\n' > "$state"
  exit 0
fi
failures=$((failures+1)); printf '%s\n' "$failures" > "$state"
logger -t virtinfra-monitor-health "livez failed (${failures}/2)"
if ((failures>=2)); then
  systemctl restart bw-monitor.service
  printf '0\n' > "$state"
  logger -t virtinfra-monitor-health 'restarted bw-monitor.service after two failed live checks'
fi
