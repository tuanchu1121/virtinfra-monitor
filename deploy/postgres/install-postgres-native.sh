#!/usr/bin/env bash
set -Eeuo pipefail

RELEASE="50.5.9-prod-r7-rbac-node-groups-node-vm-ui-refresh-hotfix-r1"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
APP_SRC="$REPO_ROOT/app"
PG_SRC="$REPO_ROOT/postgres"
APP_DIR="/opt/bw-monitor"
DATA_DIR="/var/lib/bw-monitor"
BACKUP_ROOT="/var/backups/bw-monitor"
ENV_FILE="/etc/default/bw-monitor"
PG_ENV="/etc/default/bw-monitor-postgres"
CRED_FILE="/root/bw-monitor-credentials.env"
SERVICE_FILE="/etc/systemd/system/bw-monitor.service"
NGINX_SITE="/etc/nginx/sites-available/bw-monitor.conf"

GITHUB_REPO="${BW_GITHUB_REPO:-tuanchu1121/virtinfra-monitor}"
GITHUB_REF="${BW_GITHUB_REF:-main}"
DOMAIN=""; EMAIL=""; PUBLIC_IP=""; PORT="8080"; SSH_PORT=""
ADMIN_USER="admin"; ADMIN_PASSWORD="${BW_ADMIN_PASSWORD:-}"; MONITOR_TOKEN="${BW_MONITOR_TOKEN:-}"; LEGACY_MONITOR_TOKENS="${BW_MONITOR_LEGACY_TOKENS:-}"
TIMEZONE="Asia/Ho_Chi_Minh"; WORKERS=""; THREADS="4"
PG_PORT="55432"; PG_USER="bw_monitor"; PG_DATABASE="bw_monitor"
PG_PASSWORD="${BW_PG_PASSWORD:-}"
TIMESCALE_IMAGE="${BW_TIMESCALE_IMAGE:-timescale/timescaledb:2.27.2-pg17}"
NO_TLS=0; NO_NGINX=0; FIREWALL=0; SKIP_PREFLIGHT=0; UPDATE=0; REDIS_CACHE=0; RUN_RETENTION=0; IP_MODE=0
DOMAIN_EXPLICIT=0; PUBLIC_IP_EXPLICIT=0; PORT_EXPLICIT=0; WORKERS_EXPLICIT=0; THREADS_EXPLICIT=0

log(){ printf '\n==> %s\n' "$*"; }
warn(){ printf '\nWARNING: %s\n' "$*" >&2; }
die(){ printf '\nERROR: %s\n' "$*" >&2; exit 1; }
usage(){ cat <<'EOF'
VirtInfra Monitor v50 PostgreSQL Native installer

Fresh server by public IP:
  ./install.sh --public-ip 203.0.113.10 --port 8080

Fresh server by domain + HTTPS:
  ./install.sh --domain monitor.example.com --email ops@example.com

Options:
  --public-ip IP           Public IP used in dashboard/Agent URLs.
  --ip-mode                Switch an existing domain deployment back to IP mode.
  --port N                 Gunicorn port. Default 8080.
  --domain NAME            Configure Nginx for a domain.
  --email ADDRESS          Let's Encrypt email for first certificate.
  --no-tls                 Domain mode over HTTP only.
  --no-nginx               Expose Gunicorn directly; domain TLS unavailable.
  --admin-user NAME        Initial Admin username. Default admin.
  --admin-password VALUE   Prefer BW_ADMIN_PASSWORD environment variable.
  --monitor-token VALUE    Prefer BW_MONITOR_TOKEN environment variable.
  --timezone NAME          Host timezone. Default Asia/Ho_Chi_Minh.
  --workers N              Gunicorn workers. Auto 2-4 by CPU.
  --threads N              Threads per worker. Default 4.
  --pg-port N              Loopback PostgreSQL port. Default 55432.
  --timescale-image TAG    Default timescale/timescaledb:2.27.2-pg17.
  --redis-cache            Optional Redis page cache only. Never source of truth.
  --firewall               Configure UFW after allowing SSH and web ports.
  --ssh-port N             SSH port to allow before enabling UFW.
  --run-retention-now      Run compatibility retention once; Timescale V2 policies run in background.
  --update                 Preserve PostgreSQL/config/secrets and update code.
  --skip-preflight         Skip local syntax/source checks.
  -h, --help               Show this help.

This edition is fresh-install PostgreSQL Native. It does not import SQLite data.
EOF
}

while (($#)); do
  case "$1" in
    --public-ip) PUBLIC_IP="${2:?missing value}"; PUBLIC_IP_EXPLICIT=1; shift 2;;
    --ip-mode) DOMAIN=""; DOMAIN_EXPLICIT=1; IP_MODE=1; shift;;
    --port) PORT="${2:?missing value}"; PORT_EXPLICIT=1; shift 2;;
    --domain) DOMAIN="${2:?missing value}"; DOMAIN_EXPLICIT=1; shift 2;;
    --email) EMAIL="${2:?missing value}"; shift 2;;
    --no-tls) NO_TLS=1; shift;;
    --no-nginx) NO_NGINX=1; shift;;
    --admin-user) ADMIN_USER="${2:?missing value}"; shift 2;;
    --admin-password) ADMIN_PASSWORD="${2:?missing value}"; shift 2;;
    --monitor-token) MONITOR_TOKEN="${2:?missing value}"; shift 2;;
    --timezone) TIMEZONE="${2:?missing value}"; shift 2;;
    --workers) WORKERS="${2:?missing value}"; WORKERS_EXPLICIT=1; shift 2;;
    --threads) THREADS="${2:?missing value}"; THREADS_EXPLICIT=1; shift 2;;
    --pg-port) PG_PORT="${2:?missing value}"; shift 2;;
    --timescale-image) TIMESCALE_IMAGE="${2:?missing value}"; shift 2;;
    --redis-cache) REDIS_CACHE=1; shift;;
    --firewall) FIREWALL=1; shift;;
    --ssh-port) SSH_PORT="${2:?missing value}"; shift 2;;
    --run-retention-now) RUN_RETENTION=1; shift;;
    --update) UPDATE=1; shift;;
    --skip-preflight) SKIP_PREFLIGHT=1; shift;;
    -h|--help) usage; exit 0;;
    *) die "Unknown option: $1";;
  esac
done

[[ $(id -u) -eq 0 ]] || die "Run as root."
[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT>=1 && PORT<=65535)) || die "Invalid port: $PORT"
[[ "$PG_PORT" =~ ^[0-9]+$ ]] && ((PG_PORT>=1 && PG_PORT<=65535)) || die "Invalid PostgreSQL port: $PG_PORT"
[[ "$THREADS" =~ ^[0-9]+$ ]] && ((THREADS>=1 && THREADS<=64)) || die "Invalid threads: $THREADS"
[[ "$ADMIN_USER" =~ ^[A-Za-z0-9_.@-]{1,80}$ ]] || die "Invalid Admin username."
[[ -f "$APP_SRC/app.py" ]] || die "Missing full application source."
[[ -f "$APP_SRC/bw_pg.py" ]] || die "Missing PostgreSQL data layer."
[[ -f "$PG_SRC/docker-compose.yml" ]] || die "Missing PostgreSQL compose file."

if [[ -r /etc/os-release ]]; then . /etc/os-release; else die "/etc/os-release missing"; fi
case "${ID:-}" in debian|ubuntu) ;; *) die "Supported OS: Debian/Ubuntu. Found ${ID:-unknown}";; esac

EXISTING=0
if [[ -r "$ENV_FILE" && -r "$PG_ENV" ]]; then
  EXISTING=1
  set -a; . "$ENV_FILE"; . "$PG_ENV"; set +a
  ((DOMAIN_EXPLICIT)) || DOMAIN="${BW_DOMAIN:-$DOMAIN}"
  [[ -n "$EMAIL" ]] || EMAIL="${BW_LE_EMAIL:-}"
  ((PUBLIC_IP_EXPLICIT)) || PUBLIC_IP="${BW_PUBLIC_IP:-$PUBLIC_IP}"
  ((PORT_EXPLICIT)) || PORT="${BW_PUBLIC_PORT:-$PORT}"
  ((WORKERS_EXPLICIT)) || WORKERS="${BW_GUNICORN_WORKERS:-$WORKERS}"
  ((THREADS_EXPLICIT)) || THREADS="${BW_GUNICORN_THREADS:-$THREADS}"
  ADMIN_USER="${BW_ADMIN_USERNAME:-$ADMIN_USER}"
  MONITOR_TOKEN="${BW_MONITOR_TOKEN:-$MONITOR_TOKEN}"
  LEGACY_MONITOR_TOKENS="${BW_MONITOR_LEGACY_TOKENS:-$LEGACY_MONITOR_TOKENS}"
  PG_PORT="${BW_PG_PORT:-$PG_PORT}"
  PG_USER="${BW_PG_USER:-$PG_USER}"
  PG_DATABASE="${BW_PG_DATABASE:-$PG_DATABASE}"
  PG_PASSWORD="${BW_PG_PASSWORD:-$PG_PASSWORD}"
  TIMESCALE_IMAGE="${BW_TIMESCALE_IMAGE:-$TIMESCALE_IMAGE}"
  [[ "${BW_REDIS_ENABLED:-0}" == 1 ]] && REDIS_CACHE=1
fi
((UPDATE==0 && EXISTING==1)) && UPDATE=1
((UPDATE==1 && EXISTING==0)) && die "--update requires an existing v50 installation."

if [[ -n "$DOMAIN" ]]; then
  [[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "Invalid domain: $DOMAIN"
  ((NO_NGINX==0)) || ((NO_TLS==1)) || die "TLS requires Nginx."
  if ((NO_TLS==0)) && [[ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]]; then
    [[ "$EMAIL" == *@*.* ]] || die "--email is required for first Let's Encrypt certificate."
  fi
fi

if [[ -z "$WORKERS" ]]; then
  cpus=$(nproc 2>/dev/null || echo 2)
  if ((cpus>=8)); then WORKERS=4; elif ((cpus>=4)); then WORKERS=3; else WORKERS=2; fi
fi
[[ "$WORKERS" =~ ^[0-9]+$ ]] && ((WORKERS>=1 && WORKERS<=8)) || die "Workers must be 1-8."

random_hex(){ openssl rand -hex "$1"; }
[[ -n "$PUBLIC_IP" ]] || PUBLIC_IP="$(ip -o route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++)if($i=="src"){print $(i+1);exit}}')"
[[ -n "$PUBLIC_IP" ]] || PUBLIC_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[[ -n "$PG_PASSWORD" ]] || PG_PASSWORD="$(random_hex 32)"
[[ -n "$MONITOR_TOKEN" ]] || MONITOR_TOKEN="bwm_push_$(random_hex 32)"
APP_SECRET="${BW_ADMIN_SECRET_KEY:-}"
[[ -n "$APP_SECRET" ]] || APP_SECRET="$(random_hex 48)"

SAVED_PASSWORD=""
if [[ -r "$CRED_FILE" ]]; then SAVED_PASSWORD="$(bash -c 'set -a;. "$1";printf %s "${BW_ADMIN_PASSWORD:-}"' _ "$CRED_FILE" 2>/dev/null || true)"; fi
[[ -n "$ADMIN_PASSWORD" ]] || ADMIN_PASSWORD="$SAVED_PASSWORD"
GENERATED_PASSWORD=0
if [[ -z "$ADMIN_PASSWORD" && $EXISTING -eq 0 ]]; then ADMIN_PASSWORD="$(random_hex 16)"; GENERATED_PASSWORD=1; fi
if ((EXISTING)); then
  OLD_ADMIN_HASH="${BW_ADMIN_PASSWORD_HASH:-}"
  OLD_APP_SECRET="${BW_ADMIN_SECRET_KEY:-$APP_SECRET}"
else
  OLD_ADMIN_HASH=""; OLD_APP_SECRET="$APP_SECRET"
fi

log "Install operating-system dependencies"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
packages=(ca-certificates curl openssl python3 python3-venv python3-pip docker.io jq)
if [[ -n "$DOMAIN" && $NO_NGINX -eq 0 ]]; then packages+=(nginx); ((NO_TLS)) || packages+=(certbot python3-certbot-nginx); fi
((FIREWALL)) && packages+=(ufw)
((REDIS_CACHE)) && packages+=(redis-server)
apt-get install -y --no-install-recommends "${packages[@]}"
systemctl enable --now docker
if ! docker compose version >/dev/null 2>&1; then
  apt-get install -y docker-compose-plugin 2>/dev/null || apt-get install -y docker-compose
fi
if docker compose version >/dev/null 2>&1; then COMPOSE=(docker compose); else COMPOSE=(docker-compose); fi
if ((REDIS_CACHE)); then systemctl enable --now redis-server >/dev/null 2>&1 || systemctl enable --now redis >/dev/null 2>&1 || true; fi
command -v timedatectl >/dev/null 2>&1 && timedatectl set-timezone "$TIMEZONE" || true

log "Prepare directories and Python environment"
install -d -m 0750 "$APP_DIR" "$APP_DIR/postgres" "$APP_DIR/postgres/sql" "$APP_DIR/tools" "$DATA_DIR" "$BACKUP_ROOT"
if [[ ! -x "$APP_DIR/venv/bin/python3" ]]; then python3 -m venv "$APP_DIR/venv"; fi
"$APP_DIR/venv/bin/python3" -m pip install --upgrade pip wheel setuptools
"$APP_DIR/venv/bin/pip" install --upgrade -r "$REPO_ROOT/requirements.txt"
if ((REDIS_CACHE)); then
  "$APP_DIR/venv/bin/pip" install --upgrade -r "$REPO_ROOT/requirements-redis.txt"
fi
if ((SKIP_PREFLIGHT==0)); then
  log "Run v50 source and deployment preflight"
  BW_PREFLIGHT_PYTHON="$APP_DIR/venv/bin/python3" bash "$REPO_ROOT/preflight.sh" --use-current-python --skip-live
fi

if [[ -n "$ADMIN_PASSWORD" ]]; then
  ((${#ADMIN_PASSWORD}>=12)) || die "Admin password must be at least 12 characters."
  ADMIN_HASH="$("$APP_DIR/venv/bin/python3" - "$ADMIN_PASSWORD" <<'PY'
import sys
from werkzeug.security import generate_password_hash
print(generate_password_hash(sys.argv[1]))
PY
)"
else
  ADMIN_HASH="$OLD_ADMIN_HASH"
fi
[[ -n "$ADMIN_HASH" ]] || die "No Admin password/hash available."
APP_SECRET="$OLD_APP_SECRET"

log "Size PostgreSQL from host RAM"
RAM_MIB=$(( $(awk '/^MemTotal:/{print $2;exit}' /proc/meminfo) / 1024 ))
shared=$((RAM_MIB/4)); ((shared<256))&&shared=256; ((shared>8192))&&shared=8192
effective=$((RAM_MIB*65/100)); ((effective<768))&&effective=768; ((effective>32768))&&effective=32768
maint=$((RAM_MIB/16)); ((maint<128))&&maint=128; ((maint>2048))&&maint=2048
if ((RAM_MIB>=32768)); then work=32; shm=4gb; pgworkers=24; parallel=12
elif ((RAM_MIB>=16384)); then work=16; shm=2gb; pgworkers=16; parallel=8
elif ((RAM_MIB>=8192)); then work=8; shm=1gb; pgworkers=12; parallel=6
else work=4; shm=512mb; pgworkers=8; parallel=4; fi

cat > "$PG_ENV.tmp" <<EOF
BW_TIMESCALE_IMAGE=$TIMESCALE_IMAGE
BW_PG_PORT=$PG_PORT
BW_PG_USER=$PG_USER
BW_PG_DATABASE=$PG_DATABASE
BW_PG_PASSWORD=$PG_PASSWORD
BW_PG_SHARED_BUFFERS=${shared}MB
BW_PG_EFFECTIVE_CACHE_SIZE=${effective}MB
BW_PG_MAINTENANCE_WORK_MEM=${maint}MB
BW_PG_WORK_MEM=${work}MB
BW_PG_MAX_CONNECTIONS=150
BW_PG_MAX_WORKERS=$pgworkers
BW_PG_MAX_PARALLEL_WORKERS=$parallel
BW_PG_MAX_PARALLEL_PER_GATHER=4
BW_TSDB_BACKGROUND_WORKERS=8
BW_PG_SHM_SIZE=$shm
BW_PG_MAX_WAL_SIZE=${BW_PG_MAX_WAL_SIZE:-8GB}
BW_PG_MIN_WAL_SIZE=${BW_PG_MIN_WAL_SIZE:-2GB}
EOF
install -o root -g root -m 0600 "$PG_ENV.tmp" "$PG_ENV"; rm -f "$PG_ENV.tmp"

log "Install PostgreSQL/TimescaleDB compose definition"
install -m 0644 "$PG_SRC/docker-compose.yml" "$APP_DIR/postgres/docker-compose.yml"
install -m 0644 "$PG_SRC/sql/001_bootstrap.sql" "$APP_DIR/postgres/sql/001_bootstrap.sql"
install -m 0644 "$PG_SRC/sql/002_timescale.sql" "$APP_DIR/postgres/sql/002_timescale.sql"
install -m 0644 "$PG_SRC/sql/003_native_indexes.sql" "$APP_DIR/postgres/sql/003_native_indexes.sql"
install -m 0644 "$PG_SRC/sql/004_storage_v2.sql" "$APP_DIR/postgres/sql/004_storage_v2.sql"
install -m 0644 "$PG_SRC/sql/005_ingest_write_profile.sql" "$APP_DIR/postgres/sql/005_ingest_write_profile.sql"
install -m 0644 "$PG_SRC/sql/006_postgres_native_maintenance.sql" "$APP_DIR/postgres/sql/006_postgres_native_maintenance.sql"
install -m 0644 "$PG_SRC/sql/007_safe_maintenance_queue.sql" "$APP_DIR/postgres/sql/007_safe_maintenance_queue.sql"
install -m 0644 "$PG_SRC/sql/008_mac_identity_search.sql" "$APP_DIR/postgres/sql/008_mac_identity_search.sql"
install -m 0644 "$PG_SRC/sql/009_low_io_compat.sql" "$APP_DIR/postgres/sql/009_low_io_compat.sql"
install -m 0644 "$PG_SRC/sql/010_consumption_inventory_cleanup.sql" "$APP_DIR/postgres/sql/010_consumption_inventory_cleanup.sql"
install -m 0644 "$PG_SRC/sql/011_node_groups.sql" "$APP_DIR/postgres/sql/011_node_groups.sql"
install -m 0644 "$PG_SRC/sql/012_node_groups_r6_safety.sql" "$APP_DIR/postgres/sql/012_node_groups_r6_safety.sql"

log "Start PostgreSQL 17 + TimescaleDB"
"${COMPOSE[@]}" --env-file "$PG_ENV" -f "$APP_DIR/postgres/docker-compose.yml" pull
"${COMPOSE[@]}" --env-file "$PG_ENV" -f "$APP_DIR/postgres/docker-compose.yml" up -d
for i in $(seq 1 90); do
  if docker exec bw-timescaledb pg_isready -U "$PG_USER" -d "$PG_DATABASE" >/dev/null 2>&1; then break; fi
  ((i==90)) && { docker logs --tail 250 bw-timescaledb >&2 || true; die "TimescaleDB did not become ready"; }
  sleep 2
done

if ((UPDATE)) && [[ -f "$APP_DIR/backup.sh" ]]; then
  log "Create PostgreSQL backup before update"
  bash "$APP_DIR/backup.sh"
fi

log "Install full application code"
install -m 0644 "$APP_SRC/app.py" "$APP_DIR/app.py"
install -m 0644 "$APP_SRC/node_groups.py" "$APP_DIR/node_groups.py"
install -d -m 0755 "$APP_DIR/static/vendor/flag-icons/flags/4x3"
install -m 0644 "$APP_SRC/static/vendor/flag-icons/node-groups.css" "$APP_DIR/static/vendor/flag-icons/node-groups.css"
install -m 0644 "$APP_SRC/static/vendor/flag-icons/LICENSE" "$APP_DIR/static/vendor/flag-icons/LICENSE"
install -m 0644 "$APP_SRC/static/vendor/flag-icons/SOURCE.md" "$APP_DIR/static/vendor/flag-icons/SOURCE.md"
find "$APP_SRC/static/vendor/flag-icons/flags/4x3" -maxdepth 1 -type f -name "*.svg" -exec install -m 0644 {} "$APP_DIR/static/vendor/flag-icons/flags/4x3/" \;
install -d -m 0755 "$APP_DIR/static/flags"
install -m 0644 "$APP_SRC/static/flags/node-groups.css" "$APP_DIR/static/flags/node-groups.css"
find "$APP_SRC/static/flags" -maxdepth 1 -type f -name "*.svg" -exec install -m 0644 {} "$APP_DIR/static/flags/" \;
install -m 0644 "$APP_SRC/bw_pg.py" "$APP_DIR/bw_pg.py"
install -m 0644 "$APP_SRC/storage_v2.py" "$APP_DIR/storage_v2.py"
install -m 0644 "$APP_SRC/maintenance_native.py" "$APP_DIR/maintenance_native.py"
install -m 0644 "$APP_SRC/maintenance_queue.py" "$APP_DIR/maintenance_queue.py"
install -m 0755 "$APP_SRC/maintenance_dispatch.py" "$APP_DIR/maintenance_dispatch.py"
install -m 0755 "$APP_SRC/maintenance.py" "$APP_DIR/maintenance.py"
install -m 0755 "$APP_SRC/retention.py" "$APP_DIR/retention.py"
install -m 0755 "$APP_SRC/inventory_cleanup.py" "$APP_DIR/inventory_cleanup.py"
install -m 0755 "$APP_SRC/consumption_rollup.py" "$APP_DIR/consumption_rollup.py"
install -m 0755 "$REPO_ROOT/tools/storage-v2-status.py" "$APP_DIR/tools/storage-v2-status.py"
install -m 0755 "$REPO_ROOT/tools/validate-storage-v2.py" "$APP_DIR/tools/validate-storage-v2.py"
install -m 0755 "$REPO_ROOT/tools/benchmark-storage-v2.py" "$APP_DIR/tools/benchmark-storage-v2.py"
install -m 0755 "$SCRIPT_DIR/start-monitor.sh" "$APP_DIR/start-monitor.sh"
install -m 0644 "$REPO_ROOT/VERSION" "$APP_DIR/DEPLOY_VERSION"
install -m 0644 "$REPO_ROOT/requirements.txt" "$APP_DIR/requirements.txt"
install -m 0644 "$REPO_ROOT/requirements-redis.txt" "$APP_DIR/requirements-redis.txt"

DATABASE_URL="postgresql://$PG_USER:$PG_PASSWORD@127.0.0.1:$PG_PORT/$PG_DATABASE"
if [[ -n "$DOMAIN" && $NO_NGINX -eq 0 ]]; then BIND="127.0.0.1:$PORT"; TRUST_PROXY=1; else BIND="0.0.0.0:$PORT"; TRUST_PROXY=0; fi
if [[ -n "$DOMAIN" ]]; then
  if ((NO_TLS)); then PUBLIC_URL="http://$DOMAIN"; else PUBLIC_URL="https://$DOMAIN"; fi
else PUBLIC_URL="http://$PUBLIC_IP:$PORT"; fi
PUSH_URL="$PUBLIC_URL/push"

cat > "$ENV_FILE.tmp" <<EOF
BW_MONITOR_RELEASE='$RELEASE'
BW_DATABASE_URL='$DATABASE_URL'
BW_POSTGRES_DSN='$DATABASE_URL'
BW_MONITOR_DB='$DATA_DIR/postgresql'
BW_MONITOR_TOKEN='$MONITOR_TOKEN'
BW_MONITOR_LEGACY_TOKENS='$LEGACY_MONITOR_TOKENS'
BW_ADMIN_USERNAME='$ADMIN_USER'
BW_ADMIN_PASSWORD_HASH='$ADMIN_HASH'
BW_ADMIN_SECRET_KEY='$APP_SECRET'
BW_ADMIN_COOKIE_SECURE='$(( ${#DOMAIN}>0 && NO_TLS==0 ? 1 : 0 ))'
BW_WEB_TRUST_PROXY='$TRUST_PROXY'
BW_API_TRUST_PROXY='$TRUST_PROXY'
BW_API_TRUSTED_PROXIES='127.0.0.1/32,::1/128'
BW_API_ACCESS_LOGS='1'
BW_API_ACCESS_LOG_RETENTION_DAYS='7'
BW_API_RATE_LIMIT_PER_MINUTE='120'
BW_API_MAX_LIMIT='500'
BW_RAW_RETENTION_DAYS='2'
BW_HOURLY_RETENTION_DAYS='7'
BW_RETENTION_BATCH_ROWS='25000'
BW_RETENTION_TZ_OFFSET_SECONDS='25200'
BW_WRITE_LEGACY_USAGE='0'
VIRTINFRA_STORAGE_V2='0'
VIRTINFRA_READ_CHART_V2='0'
VIRTINFRA_RAW_V2='0'
VIRTINFRA_PUSH_OBSERVABILITY='1'
BW_REDIS_ENABLED='$REDIS_CACHE'
BW_REDIS_URL='redis://127.0.0.1:6379/0'
BW_PAGE_CACHE_ENABLED='1'
BW_MAX_COMPRESSED_PUSH_BYTES='16777216'
BW_MAX_UNCOMPRESSED_PUSH_BYTES='67108864'
BW_PAGE_CACHE_TTL='6'
BW_LOCAL_CACHE_ITEMS='1024'
BW_DB_POOL_MIN='1'
BW_DB_POOL_MAX='12'
BW_DB_POOL_TIMEOUT='10'
BW_DB_STATEMENT_TIMEOUT_MS='60000'
BW_DB_LOCK_TIMEOUT_MS='15000'
BW_DB_IDLE_TX_TIMEOUT_MS='60000'
BW_BACKFILL_CACHE_ON_START='0'
BW_BACKFILL_INVENTORY_ON_START='0'
BW_MAX_PURGE_ITEMS_PER_JOB='3'
BW_MAX_PURGE_SELECTION_ITEMS='300'
BW_GUNICORN_BIND='$BIND'
BW_GUNICORN_WORKERS='$WORKERS'
BW_GUNICORN_THREADS='$THREADS'
BW_GUNICORN_TIMEOUT='300'
BW_GUNICORN_GRACEFUL_TIMEOUT='60'
BW_GUNICORN_KEEPALIVE='5'
BW_GUNICORN_MAX_REQUESTS='3000'
BW_GUNICORN_MAX_REQUESTS_JITTER='300'
BW_GUNICORN_LOG_LEVEL='info'
BW_GUNICORN_ACCESS_LOG='-'
BW_GUNICORN_ERROR_LOG='-'
BW_DOMAIN='$DOMAIN'
BW_LE_EMAIL='$EMAIL'
BW_GITHUB_REPO='$GITHUB_REPO'
BW_GITHUB_REF='$GITHUB_REF'
BW_PUBLIC_IP='$PUBLIC_IP'
BW_PUBLIC_PORT='$PORT'
BW_PUBLIC_URL='$PUBLIC_URL'
BW_PUSH_URL='$PUSH_URL'
BW_TLS_ENABLED='$(( ${#DOMAIN}>0 && NO_TLS==0 ? 1 : 0 ))'
BW_NGINX_ENABLED='$(( ${#DOMAIN}>0 && NO_NGINX==0 ? 1 : 0 ))'
EOF
install -o root -g root -m 0600 "$ENV_FILE.tmp" "$ENV_FILE"; rm -f "$ENV_FILE.tmp"

cat > "$CRED_FILE" <<EOF
BW_MONITOR_RELEASE='$RELEASE'
BW_MONITOR_URL='$PUBLIC_URL'
BW_PUSH_URL='$PUSH_URL'
BW_MONITOR_TOKEN='$MONITOR_TOKEN'
BW_ADMIN_USERNAME='$ADMIN_USER'
BW_ADMIN_PASSWORD='$ADMIN_PASSWORD'
BW_DOMAIN='$DOMAIN'
BW_PUBLIC_IP='$PUBLIC_IP'
BW_GITHUB_REPO='$GITHUB_REPO'
BW_GITHUB_REF='$GITHUB_REF'
EOF
chmod 0600 "$CRED_FILE"

log "Create PostgreSQL schema catalog and application schema"
docker exec -i bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DATABASE" < "$APP_DIR/postgres/sql/001_bootstrap.sql"
set -a; . "$ENV_FILE"; set +a
(
  cd "$APP_DIR"
  "$APP_DIR/venv/bin/python3" - <<'PY'
import importlib.util
spec=importlib.util.spec_from_file_location('bw_monitor_schema','/opt/bw-monitor/app.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.dbapi.close_pool()
print('Application schema initialized; routes:', len(module.app.url_map._rules))
PY
)

log "Convert metric/history tables to Timescale hypertables"
docker exec -i bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DATABASE" < "$APP_DIR/postgres/sql/002_timescale.sql"

log "Verify TimescaleDB Community Edition capabilities"
TS_LICENSE="$(docker exec bw-timescaledb psql -U "$PG_USER" -d "$PG_DATABASE" -Atqc "SELECT current_setting('timescaledb.license', true)" 2>/dev/null || true)"
[[ "$TS_LICENSE" == "timescale" ]] || die "Storage V2 requires TimescaleDB Community Edition. Found timescaledb.license=${TS_LICENSE:-unset}. Use timescale/timescaledb:2.27.2-pg17, not a -oss image."
TS_CAPS="$(docker exec bw-timescaledb psql -U "$PG_USER" -d "$PG_DATABASE" -Atqc "SELECT count(DISTINCT proname) FROM pg_proc WHERE proname IN ('add_retention_policy','add_compression_policy')" 2>/dev/null || true)"
[[ "$TS_CAPS" == "2" ]] || die "TimescaleDB retention/compression policy functions are unavailable; refusing a partial Storage V2 install."
docker exec -i bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DATABASE" < "$APP_DIR/postgres/sql/003_native_indexes.sql"
docker exec -i bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DATABASE" < "$APP_DIR/postgres/sql/004_storage_v2.sql"
log "Apply low-write ingest index profile"
docker exec -i bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DATABASE" < "$APP_DIR/postgres/sql/005_ingest_write_profile.sql"
log "Apply PostgreSQL-native maintenance guards"
docker exec -i bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DATABASE" < "$APP_DIR/postgres/sql/006_postgres_native_maintenance.sql"
docker exec -i bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DATABASE" < "$APP_DIR/postgres/sql/007_safe_maintenance_queue.sql"
log "Apply MAC identity and search schema"
docker exec -i bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DATABASE" < "$APP_DIR/postgres/sql/008_mac_identity_search.sql"
log "Apply low-I/O compatible current-state profile"
docker exec -i bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DATABASE" < "$APP_DIR/postgres/sql/009_low_io_compat.sql"
log "Apply fast Consumption rollups and inventory cleanup indexes"
docker exec -i bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DATABASE" < "$APP_DIR/postgres/sql/010_consumption_inventory_cleanup.sql"
log "Apply Node Groups and role migration"
docker exec -i bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DATABASE" < "$APP_DIR/postgres/sql/011_node_groups.sql"
docker exec -i bw-timescaledb psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DATABASE" < "$APP_DIR/postgres/sql/012_node_groups_r6_safety.sql"

log "Backfill recent physical Consumption rollups"
if ! "$APP_DIR/venv/bin/python3" "$APP_DIR/consumption_rollup.py" --hours 48; then
  warn "Consumption backfill did not complete. New 5-minute pushes will populate rollups automatically."
fi

log "Install services and management tools"
install -m 0644 "$SCRIPT_DIR/bw-monitor.service" "$SERVICE_FILE"
install -m 0644 "$SCRIPT_DIR/bw-monitor-maintenance@.service" /etc/systemd/system/bw-monitor-maintenance@.service
install -m 0644 "$SCRIPT_DIR/bw-monitor-maintenance-dispatch.service" /etc/systemd/system/bw-monitor-maintenance-dispatch.service
install -m 0644 "$SCRIPT_DIR/bw-monitor-maintenance-watchdog.timer" /etc/systemd/system/bw-monitor-maintenance-watchdog.timer
install -m 0644 "$SCRIPT_DIR/bw-monitor-retention.service" /etc/systemd/system/bw-monitor-retention.service
install -m 0644 "$SCRIPT_DIR/bw-monitor-retention.timer" /etc/systemd/system/bw-monitor-retention.timer
install -m 0644 "$SCRIPT_DIR/bw-monitor-inventory-cleanup.service" /etc/systemd/system/bw-monitor-inventory-cleanup.service
install -m 0644 "$SCRIPT_DIR/bw-monitor-inventory-cleanup.timer" /etc/systemd/system/bw-monitor-inventory-cleanup.timer
install -m 0755 "$SCRIPT_DIR/virtinfra-monitor-health-watch.sh" "$APP_DIR/virtinfra-monitor-health-watch.sh"
install -m 0644 "$SCRIPT_DIR/virtinfra-monitor-health-watch.service" /etc/systemd/system/virtinfra-monitor-health-watch.service
install -m 0644 "$SCRIPT_DIR/virtinfra-monitor-health-watch.timer" /etc/systemd/system/virtinfra-monitor-health-watch.timer
for helper in backup restore doctor db-check audit collect-diagnostics bw-monitorctl storage-v2-status rollback-storage-v2; do
  install -m 0755 "$SCRIPT_DIR/$helper.sh" "$APP_DIR/$helper.sh"
done
ln -sfn "$APP_DIR/bw-monitorctl.sh" /usr/local/sbin/bw-monitorctl
ln -sfn "$APP_DIR/bw-monitorctl.sh" /usr/local/sbin/virtinfra-monitorctl
ln -sfn "$APP_DIR/doctor.sh" /usr/local/sbin/bw-monitor-doctor
ln -sfn "$APP_DIR/doctor.sh" /usr/local/sbin/virtinfra-monitor-doctor

cat > /etc/systemd/system/bw-monitor-backup.service <<'UNIT'
[Unit]
Description=VirtInfra Monitor PostgreSQL/TimescaleDB backup
After=docker.service
[Service]
Type=oneshot
User=root
Group=root
ExecStart=/opt/bw-monitor/backup.sh
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
UNIT
cat > /etc/systemd/system/bw-monitor-backup.timer <<'UNIT'
[Unit]
Description=Daily VirtInfra Monitor PostgreSQL backup
[Timer]
OnCalendar=*-*-* 02:20:00
RandomizedDelaySec=15m
Persistent=true
[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now bw-monitor-maintenance-watchdog.timer
systemctl --no-block start bw-monitor-maintenance-dispatch.service || true
systemctl enable bw-monitor.service bw-monitor-retention.timer bw-monitor-backup.timer virtinfra-monitor-health-watch.timer bw-monitor-inventory-cleanup.timer
systemctl restart bw-monitor-retention.timer bw-monitor-backup.timer virtinfra-monitor-health-watch.timer

if [[ -n "$DOMAIN" && $NO_NGINX -eq 0 ]]; then
  log "Configure Nginx for $DOMAIN"
  sed -e "s/__DOMAIN__/$DOMAIN/g" -e "s/__PORT__/$PORT/g" "$SCRIPT_DIR/nginx.conf.tpl" > "$NGINX_SITE"
  ln -sfn "$NGINX_SITE" /etc/nginx/sites-enabled/bw-monitor.conf
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl enable --now nginx
  systemctl reload nginx
  if ((NO_TLS==0)); then
    log "Issue/install Let's Encrypt certificate"
    getent ahosts "$DOMAIN" >/dev/null 2>&1 || die "Domain $DOMAIN does not resolve. Point DNS first, then rerun."
    if [[ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]]; then
      certbot --nginx --non-interactive --redirect -d "$DOMAIN"
    else
      certbot --nginx --non-interactive --agree-tos --redirect --email "$EMAIL" -d "$DOMAIN"
    fi
  fi
fi

if [[ -z "$DOMAIN" || $NO_NGINX -eq 1 ]]; then
  rm -f /etc/nginx/sites-enabled/bw-monitor.conf /etc/nginx/sites-available/bw-monitor.conf
  if command -v nginx >/dev/null 2>&1; then
    nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
  fi
fi

if ((FIREWALL)); then
  log "Configure UFW"
  [[ -n "$SSH_PORT" ]] || SSH_PORT="$(sshd -T 2>/dev/null | awk '$1=="port"{print $2;exit}')"
  [[ -n "$SSH_PORT" ]] || SSH_PORT=22
  ufw allow "$SSH_PORT/tcp"
  if [[ -n "$DOMAIN" && $NO_NGINX -eq 0 ]]; then ufw allow 80/tcp; ufw allow 443/tcp; else ufw allow "$PORT/tcp"; fi
  ufw --force enable
fi

log "Start and verify VirtInfra Monitor"
systemctl restart bw-monitor.service
for i in $(seq 1 60); do
  code=$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 2 --max-time 5 "http://127.0.0.1:$PORT/login" 2>/dev/null || true)
  case "$code" in 200|302) break;; esac
  ((i==60)) && { systemctl status bw-monitor.service --no-pager -l >&2 || true; journalctl -u bw-monitor.service -n 250 --no-pager >&2 || true; die "Local web health check failed"; }
  sleep 2
done
systemctl is-active --quiet bw-monitor.service || die "bw-monitor.service inactive"
systemctl restart bw-monitor-inventory-cleanup.timer
if [[ -n "$DOMAIN" && $NO_TLS -eq 0 ]]; then
  for i in $(seq 1 30); do curl -fsS --max-time 10 "https://$DOMAIN/login" >/dev/null && break; ((i==30)) && die "HTTPS health check failed"; sleep 2; done
fi
if ((RUN_RETENTION)); then systemctl start bw-monitor-retention.service; fi

[[ -f "$APP_DIR/bandwidth.db" ]] && warn "Legacy $APP_DIR/bandwidth.db is ignored. v50 runtime uses PostgreSQL only."

cat <<EOF

============================================================
VirtInfra Monitor $RELEASE installed
============================================================
Dashboard:      $PUBLIC_URL/
Admin:          $PUBLIC_URL/admin
Agent push:     $PUSH_URL
Admin user:     $ADMIN_USER
Credentials:    $CRED_FILE
Database:       PostgreSQL 17 + TimescaleDB (single source of truth)
PostgreSQL:     127.0.0.1:$PG_PORT (loopback only)
Agent cadence:  local 15-second samples, one push every 300 seconds
Chart history:  exact 5-minute VM/node points for 7 days
Raw detail:     per-interface V2 rows for 48 hours
Retention:      Timescale background chunk retention; compatibility history unchanged
Management:     virtinfra-monitorctl help
Compatibility:  bw-monitorctl remains available
Doctor:         virtinfra-monitorctl doctor
Logs:           virtinfra-monitorctl logs all 200
============================================================
EOF
if ((GENERATED_PASSWORD)); then echo "Generated Admin password: $ADMIN_PASSWORD"; fi
