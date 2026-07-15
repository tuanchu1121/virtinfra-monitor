#!/usr/bin/env bash
set -Eeuo pipefail
PURGE=0; YES=0; PURGE_CERT=0
while (($#)); do
  case "$1" in
    --purge-data) PURGE=1; shift;;
    --purge-cert) PURGE_CERT=1; shift;;
    --yes) YES=1; shift;;
    -h|--help) echo 'Usage: uninstall.sh [--purge-data] [--purge-cert] [--yes]'; exit 0;;
    *) echo "Unknown option: $1" >&2; exit 2;;
  esac
done
[[ $(id -u) -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }
if [[ -r /etc/default/bw-monitor ]]; then set -a; . /etc/default/bw-monitor; set +a; fi
if ((YES==0)); then
  prompt='UNINSTALL'; ((PURGE)) && prompt='PURGE'
  read -r -p "Type $prompt to continue: " answer
  [[ "$answer" == "$prompt" ]] || exit 1
fi
if [[ -x /opt/bw-monitor/backup.sh && $PURGE -eq 0 ]]; then /opt/bw-monitor/backup.sh || true; fi
systemctl disable --now bw-monitor.service bw-monitor-retention.timer bw-monitor-backup.timer virtinfra-monitor-health-watch.timer 2>/dev/null || true
rm -f /etc/systemd/system/bw-monitor.service /etc/systemd/system/bw-monitor-maintenance@.service \
      /etc/systemd/system/bw-monitor-retention.service /etc/systemd/system/bw-monitor-retention.timer \
      /etc/systemd/system/bw-monitor-backup.service /etc/systemd/system/bw-monitor-backup.timer \
      /etc/systemd/system/virtinfra-monitor-health-watch.service /etc/systemd/system/virtinfra-monitor-health-watch.timer
systemctl daemon-reload
rm -f /etc/nginx/sites-enabled/bw-monitor.conf /etc/nginx/sites-available/bw-monitor.conf
command -v nginx >/dev/null && nginx -t >/dev/null 2>&1 && systemctl reload nginx || true
if [[ -r /etc/default/bw-monitor-postgres ]]; then
  set -a; . /etc/default/bw-monitor-postgres; set +a
  if docker compose version >/dev/null 2>&1; then compose=(docker compose); else compose=(docker-compose); fi
  if [[ -f /opt/bw-monitor/postgres/docker-compose.yml ]]; then
    if ((PURGE)); then
      "${compose[@]}" --env-file /etc/default/bw-monitor-postgres -f /opt/bw-monitor/postgres/docker-compose.yml down -v || true
    else
      "${compose[@]}" --env-file /etc/default/bw-monitor-postgres -f /opt/bw-monitor/postgres/docker-compose.yml down || true
    fi
  fi
fi
if ((PURGE)); then
  rm -rf /opt/bw-monitor /var/lib/bw-monitor /var/backups/bw-monitor
  rm -f /etc/default/bw-monitor /etc/default/bw-monitor-postgres /root/bw-monitor-credentials.env
else
  mv /opt/bw-monitor "/opt/bw-monitor.uninstalled.$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true
fi
rm -f /usr/local/sbin/bw-monitorctl /usr/local/sbin/bw-monitor-doctor /usr/local/sbin/virtinfra-monitorctl /usr/local/sbin/virtinfra-monitor-doctor
if ((PURGE_CERT)) && [[ -n "${BW_DOMAIN:-}" ]] && command -v certbot >/dev/null; then certbot delete --non-interactive --cert-name "$BW_DOMAIN" || true; fi
echo 'VirtInfra Monitor uninstalled.'
