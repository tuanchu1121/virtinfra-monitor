#!/usr/bin/env bash
set -Eeuo pipefail

RELEASE_FROM="50.5.9-prod-r4-dead-code-cleanup"
RELEASE_TO="50.5.9-prod-r3-ui-alignment-overflow-hotfix"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${BW_APP_DIR:-/opt/bw-monitor}"
SERVICE="${BW_SERVICE:-bw-monitor.service}"
HEALTH_BASE_URL="${BW_HEALTH_BASE_URL:-http://127.0.0.1:8080}"
PREVIOUS_ZIP="$SCRIPT_DIR/rollback/virtinfra-monitor-50.5.9-prod-r3-ui-alignment-overflow-hotfix-production-slim.zip"
BACKUP_ROOT="${BW_ROLLBACK_BACKUP_ROOT:-/var/backups/virtinfra-monitor}"
TMP_DIR=""
BACKUP_ARCHIVE=""

log(){ printf '\n==> %s\n' "$*"; }
warn(){ printf '\nWARNING: %s\n' "$*" >&2; }
die(){ printf '\nERROR: %s\n' "$*" >&2; exit 1; }
cleanup(){ [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]] && rm -rf -- "$TMP_DIR"; }
trap cleanup EXIT
trap 'warn "Rollback command failed at line $LINENO."' ERR

[[ $(id -u) -eq 0 ]] || die "Run rollback.sh as root."
for cmd in unzip tar install find sha256sum systemctl curl python3; do
    command -v "$cmd" >/dev/null 2>&1 || die "Required command is missing: $cmd"
done
[[ -d "$APP_DIR" ]] || die "Application directory does not exist: $APP_DIR"
[[ -f "$PREVIOUS_ZIP" ]] || die "Embedded previous release is missing: $PREVIOUS_ZIP"

TMP_DIR="$(mktemp -d /tmp/virtinfra-r4-rollback.XXXXXX)"
mkdir -p "$TMP_DIR/previous"
unzip -q "$PREVIOUS_ZIP" -d "$TMP_DIR/previous"
PREVIOUS_ROOT="$(find "$TMP_DIR/previous" -mindepth 1 -maxdepth 4 -type f -path '*/app/app.py' -printf '%h\n' | sed 's#/app$##' | head -n1)"
[[ -n "$PREVIOUS_ROOT" && -f "$PREVIOUS_ROOT/SHA256SUMS" ]] || die "Cannot locate the embedded previous release root."

log "Verify embedded previous release"
(
    cd "$PREVIOUS_ROOT"
    sha256sum -c SHA256SUMS
) >/dev/null

RUNTIME_FILES=(
    app.py bw_pg.py storage_v2.py maintenance_native.py maintenance_queue.py
    maintenance_dispatch.py maintenance.py retention.py inventory_cleanup.py
    consumption_rollup.py start-monitor.sh DEPLOY_VERSION requirements.txt
    requirements-redis.txt tools/storage-v2-status.py
    tools/validate-storage-v2.py tools/benchmark-storage-v2.py
)

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0750 "$BACKUP_ROOT"
BACKUP_ARCHIVE="$BACKUP_ROOT/source-before-${RELEASE_FROM}-${TIMESTAMP}.tar.gz"
BACKUP_LIST="$TMP_DIR/current-files.txt"
: > "$BACKUP_LIST"
for rel in "${RUNTIME_FILES[@]}"; do
    [[ -f "$APP_DIR/$rel" ]] && printf '%s\n' "$rel" >> "$BACKUP_LIST"
done
[[ -s "$BACKUP_LIST" ]] || die "No runtime source files were found under $APP_DIR"

log "Back up current source"
tar -C "$APP_DIR" -czf "$BACKUP_ARCHIVE" -T "$BACKUP_LIST"
printf 'Backup: %s\n' "$BACKUP_ARCHIVE"

if systemctl is-active --quiet "$SERVICE"; then
    log "Stop $SERVICE before replacing runtime source"
    systemctl stop "$SERVICE"
fi

restore_previous_source(){
    install -d -m 0755 "$APP_DIR/tools"
    install -m 0644 "$PREVIOUS_ROOT/app/app.py" "$APP_DIR/app.py"
    install -m 0644 "$PREVIOUS_ROOT/app/bw_pg.py" "$APP_DIR/bw_pg.py"
    install -m 0644 "$PREVIOUS_ROOT/app/storage_v2.py" "$APP_DIR/storage_v2.py"
    install -m 0644 "$PREVIOUS_ROOT/app/maintenance_native.py" "$APP_DIR/maintenance_native.py"
    install -m 0644 "$PREVIOUS_ROOT/app/maintenance_queue.py" "$APP_DIR/maintenance_queue.py"
    install -m 0755 "$PREVIOUS_ROOT/app/maintenance_dispatch.py" "$APP_DIR/maintenance_dispatch.py"
    install -m 0755 "$PREVIOUS_ROOT/app/maintenance.py" "$APP_DIR/maintenance.py"
    install -m 0755 "$PREVIOUS_ROOT/app/retention.py" "$APP_DIR/retention.py"
    install -m 0755 "$PREVIOUS_ROOT/app/inventory_cleanup.py" "$APP_DIR/inventory_cleanup.py"
    install -m 0755 "$PREVIOUS_ROOT/app/consumption_rollup.py" "$APP_DIR/consumption_rollup.py"
    install -m 0755 "$PREVIOUS_ROOT/deploy/postgres/start-monitor.sh" "$APP_DIR/start-monitor.sh"
    install -m 0644 "$PREVIOUS_ROOT/VERSION" "$APP_DIR/DEPLOY_VERSION"
    install -m 0644 "$PREVIOUS_ROOT/requirements.txt" "$APP_DIR/requirements.txt"
    install -m 0644 "$PREVIOUS_ROOT/requirements-redis.txt" "$APP_DIR/requirements-redis.txt"
    install -m 0755 "$PREVIOUS_ROOT/tools/storage-v2-status.py" "$APP_DIR/tools/storage-v2-status.py"
    install -m 0755 "$PREVIOUS_ROOT/tools/validate-storage-v2.py" "$APP_DIR/tools/validate-storage-v2.py"
    install -m 0755 "$PREVIOUS_ROOT/tools/benchmark-storage-v2.py" "$APP_DIR/tools/benchmark-storage-v2.py"
}

restore_backup_source(){
    tar -C "$APP_DIR" -xzf "$BACKUP_ARCHIVE"
}

compile_source(){
    local python_bin="$APP_DIR/venv/bin/python3"
    [[ -x "$python_bin" ]] || python_bin="$(command -v python3)"
    "$python_bin" -m compileall -q \
        "$APP_DIR/app.py" \
        "$APP_DIR/bw_pg.py" \
        "$APP_DIR/storage_v2.py" \
        "$APP_DIR/maintenance_native.py" \
        "$APP_DIR/maintenance_queue.py" \
        "$APP_DIR/maintenance_dispatch.py" \
        "$APP_DIR/maintenance.py" \
        "$APP_DIR/retention.py" \
        "$APP_DIR/inventory_cleanup.py" \
        "$APP_DIR/consumption_rollup.py" \
        "$APP_DIR/tools"
}

health_check(){
    local attempt
    for attempt in $(seq 1 30); do
        if curl -fsS --max-time 5 "$HEALTH_BASE_URL/livez" >/dev/null \
            && curl -fsS --max-time 5 "$HEALTH_BASE_URL/healthz" >/dev/null; then
            return 0
        fi
        sleep 2
    done
    return 1
}

log "Restore source from $RELEASE_TO"
restore_previous_source

log "Compile restored source"
if ! compile_source; then
    warn "Compile check failed. Restoring the source backup."
    restore_backup_source
    compile_source || true
    systemctl start "$SERVICE" || true
    die "Rollback aborted; original source was restored from $BACKUP_ARCHIVE"
fi

log "Start $SERVICE"
systemctl start "$SERVICE"

log "Verify /livez and /healthz"
if health_check; then
    printf '\nRollback completed successfully.\n'
    printf 'Release: %s -> %s\n' "$RELEASE_FROM" "$RELEASE_TO"
    printf 'Safety backup: %s\n' "$BACKUP_ARCHIVE"
    printf 'Database and logs were not modified.\n'
    exit 0
fi

warn "Health checks failed after rollback. Restoring the source backup."
systemctl stop "$SERVICE" || true
restore_backup_source
compile_source || true
systemctl start "$SERVICE" || true
if health_check; then
    die "Rollback failed; the pre-rollback source was restored and is healthy. Backup: $BACKUP_ARCHIVE"
fi
die "Rollback and automatic source recovery both failed health checks. Inspect $SERVICE and backup $BACKUP_ARCHIVE"
