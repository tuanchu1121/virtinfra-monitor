#!/usr/bin/env bash
set -Eeuo pipefail
ENV_FILE="/etc/default/bw-monitor"
PG_ENV="/etc/default/bw-monitor-postgres"
BACKUP_ROOT="${BW_BACKUP_ROOT:-/var/backups/bw-monitor}"
KEEP_DAYS="${BW_BACKUP_KEEP_DAYS:-14}"
[[ $(id -u) -eq 0 ]] || { echo "Run as root" >&2; exit 1; }
[[ -r "$PG_ENV" ]] || { echo "Missing $PG_ENV" >&2; exit 1; }
set -a; . "$PG_ENV"; set +a
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_ROOT/$STAMP"
mkdir -p "$OUT"
chmod 0700 "$OUT"
echo "Backing up PostgreSQL/TimescaleDB..."
docker exec bw-timescaledb pg_dump \
  -U "$BW_PG_USER" -d "$BW_PG_DATABASE" \
  --format=custom --compress=6 --no-owner --no-privileges \
  > "$OUT/database.dump"
[[ -s "$OUT/database.dump" ]] || { echo "pg_dump produced an empty file" >&2; exit 1; }
docker exec -i bw-timescaledb pg_restore --list < "$OUT/database.dump" > "$OUT/database.list"
for f in "$ENV_FILE" "$PG_ENV" /root/bw-monitor-credentials.env /etc/nginx/sites-available/bw-monitor.conf /opt/bw-monitor/DEPLOY_VERSION; do
  [[ -f "$f" ]] || continue
  name="$(printf '%s' "$f" | sed 's#^/##;s#/#__#g')"
  cp -a "$f" "$OUT/$name"
done
cat > "$OUT/metadata.txt" <<EOF
release=$(cat /opt/bw-monitor/DEPLOY_VERSION 2>/dev/null || echo unknown)
created_at=$(date --iso-8601=seconds)
hostname=$(hostname -f 2>/dev/null || hostname)
database=$BW_PG_DATABASE
image=$BW_TIMESCALE_IMAGE
EOF
(
  cd "$OUT"
  find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%f\0' | sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)
chmod -R go-rwx "$OUT"
while IFS= read -r -d '' old_backup; do
  # Selective Configuration Backups live in a permanent catalog directory.
  # Full-backup retention must never treat that catalog itself as an old dump.
  [[ "$(basename -- "$old_backup")" == "configuration" ]] && continue
  [[ -e "$old_backup/.protected" ]] && continue
  rm -rf -- "$old_backup"
done < <(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime "+$KEEP_DAYS" -print0 2>/dev/null)
echo "$OUT"
