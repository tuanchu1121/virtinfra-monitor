#!/usr/bin/env bash
set -Eeuo pipefail
FROM=""; YES=0; RESTORE_CONFIG=0
while (($#)); do
  case "$1" in
    --from) FROM="${2:?missing path}"; shift 2 ;;
    --with-config) RESTORE_CONFIG=1; shift ;;
    --yes) YES=1; shift ;;
    -h|--help)
      cat <<'HELP'
Usage: restore.sh --from /var/backups/bw-monitor/TIMESTAMP [--with-config] [--yes]

By default only PostgreSQL/TimescaleDB data is restored. --with-config also
restores protected Monitor/PostgreSQL environment files and credentials from
the bundle when present.
HELP
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
[[ $(id -u) -eq 0 ]] || { echo "Run as root" >&2; exit 1; }
[[ -d "$FROM" && -s "$FROM/database.dump" ]] || { echo "Invalid backup: $FROM" >&2; exit 1; }
if [[ -s "$FROM/SHA256SUMS" ]]; then (cd "$FROM" && sha256sum -c SHA256SUMS); fi
if ((YES==0)); then
  read -r -p "Restore $FROM over the current database? Type RESTORE: " answer
  [[ "$answer" == RESTORE ]] || exit 1
fi
[[ -r /etc/default/bw-monitor-postgres ]] || { echo 'Missing /etc/default/bw-monitor-postgres' >&2; exit 1; }
set -a; . /etc/default/bw-monitor-postgres; set +a
if [[ -r /etc/default/bw-monitor ]]; then set -a; . /etc/default/bw-monitor; set +a; fi
STAMP="$(date +%Y%m%d-%H%M%S)"
PRE="/var/backups/bw-monitor/pre-restore-$STAMP"
mkdir -p "$PRE"; chmod 0700 "$PRE"
echo "Creating pre-restore PostgreSQL backup: $PRE"
docker exec bw-timescaledb pg_dump \
  -U "$BW_PG_USER" -d "$BW_PG_DATABASE" \
  --format=custom --compress=6 --no-owner --no-privileges \
  --exclude-table-data=public.vm_consumption_snapshot_rows \
  --exclude-table-data=public.vm_consumption_snapshot_batches \
  > "$PRE/database.dump"

systemctl stop bw-monitor-vm-consumption-snapshot.timer bw-monitor-vm-consumption-snapshot.service 2>/dev/null || true
systemctl stop bw-monitor.service
trap 'systemctl start bw-monitor.service >/dev/null 2>&1 || true; systemctl start bw-monitor-vm-consumption-snapshot.timer >/dev/null 2>&1 || true' EXIT

# Recreate the database to avoid stale objects from a newer or partial schema.
docker exec bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$BW_PG_USER" -d postgres \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$BW_PG_DATABASE' AND pid<>pg_backend_pid();" >/dev/null
docker exec bw-timescaledb dropdb --if-exists -U "$BW_PG_USER" "$BW_PG_DATABASE"
docker exec bw-timescaledb createdb -U "$BW_PG_USER" -O "$BW_PG_USER" "$BW_PG_DATABASE"
docker exec bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$BW_PG_USER" -d "$BW_PG_DATABASE" \
  -c 'CREATE EXTENSION IF NOT EXISTS timescaledb;' >/dev/null
# Timescale's restore hooks suppress background activity while catalog/data are restored.
docker exec bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$BW_PG_USER" -d "$BW_PG_DATABASE" \
  -c 'SELECT timescaledb_pre_restore();' >/dev/null
cat "$FROM/database.dump" | docker exec -i bw-timescaledb pg_restore \
  -U "$BW_PG_USER" -d "$BW_PG_DATABASE" \
  --no-owner --no-privileges --exit-on-error
docker exec bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$BW_PG_USER" -d "$BW_PG_DATABASE" \
  -c 'SELECT timescaledb_post_restore();' >/dev/null

if ((RESTORE_CONFIG)); then
  declare -A files=(
    [etc__default__bw-monitor]="/etc/default/bw-monitor"
    [etc__default__bw-monitor-postgres]="/etc/default/bw-monitor-postgres"
    [root__bw-monitor-credentials.env]="/root/bw-monitor-credentials.env"
    [etc__nginx__sites-available__bw-monitor.conf]="/etc/nginx/sites-available/bw-monitor.conf"
  )
  for archived in "${!files[@]}"; do
    [[ -f "$FROM/$archived" ]] || continue
    install -o root -g root -m 0600 "$FROM/$archived" "${files[$archived]}"
  done
  [[ -f /etc/nginx/sites-available/bw-monitor.conf ]] && chmod 0644 /etc/nginx/sites-available/bw-monitor.conf
fi

systemctl start bw-monitor.service
systemctl start bw-monitor-vm-consumption-snapshot.timer 2>/dev/null || true
systemctl --no-block start bw-monitor-vm-consumption-snapshot.service 2>/dev/null || true
port="${BW_PUBLIC_PORT:-8080}"
for i in $(seq 1 60); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$port/login" 2>/dev/null || true)"
  case "$code" in 200|302) break;; esac
  ((i==60)) && { journalctl -u bw-monitor.service -n 200 --no-pager >&2 || true; exit 1; }
  sleep 2
done
trap - EXIT
echo "Restore complete. Pre-restore backup: $PRE"
