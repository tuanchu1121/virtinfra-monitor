#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$SCRIPT_DIR/agent.py"
DOCTOR_SOURCE="$SCRIPT_DIR/doctor-agent.sh"
INSTALL_DIR="/usr/local/lib/virtinfra-agent"
SCRIPT_TARGET="$INSTALL_DIR/agent.py"
STATE_DIR="/var/lib/virtinfra-agent"
ENV_FILE="/etc/virtinfra-agent.env"
SERVICE_FILE="/etc/systemd/system/virtinfra-agent.service"
DOCTOR_TARGET="/usr/local/sbin/virtinfra-agent-doctor"
API="${VIRTINFRA_AGENT_API:-${BW_AGENT_API:-}}"
TOKEN="${VIRTINFRA_AGENT_TOKEN:-${BW_AGENT_TOKEN:-}}"
SAMPLE_SECONDS="${VIRTINFRA_AGENT_SAMPLE_SECONDS:-${BW_AGENT_SAMPLE_SECONDS:-15}}"
PUSH_SECONDS="${VIRTINFRA_AGENT_PUSH_SECONDS:-${BW_AGENT_PUSH_SECONDS:-300}}"
MAX_LOAD="${BW_AGENT_MAX_LOAD:-160}"
SKIP_HEAVY="${BW_AGENT_SKIP_HEAVY_ON_OVERLOAD:-0}"
PPS_WARN="${BW_AGENT_PPS_WARN:-200000}"
MBPS_WARN="${BW_AGENT_MBPS_WARN:-800}"
BRIDGE_ROLES="${BW_AGENT_BRIDGE_ROLES:-public:br0,private:br1}"
HTTP_GZIP="${BW_AGENT_HTTP_GZIP:-1}"
RESET_STATE=0; SKIP_CHECK=0
log(){ printf '\n==> %s\n' "$*"; }
die(){ printf '\nERROR: %s\n' "$*" >&2; exit 1; }
usage(){ cat <<'USAGE'
VirtInfra Agent one-command installer
Usage: install-agent.sh --api https://monitor.example.com/push --token TOKEN [options]
Options:
  --api URL                 VirtInfra Monitor /push endpoint
  --token TOKEN             Monitor Agent token
  --sample-seconds NUMBER   Local sample interval, default 15
  --push-seconds NUMBER     HTTP push interval, default 300
  --bridge-roles VALUE      Default public:br0,private:br1
  --max-load NUMBER         High-load reference, default 160
  --skip-heavy-on-overload  Permit heavy collection to be skipped
  --reset-state             Remove old counters/runtime
  --skip-connectivity-check Skip monitor login pre-check
  -h, --help                Show help
New environment aliases: VIRTINFRA_AGENT_API, VIRTINFRA_AGENT_TOKEN.
Legacy BW_AGENT_* variables remain accepted for upgrade compatibility.
USAGE
}
while (($#)); do case "$1" in
  --api) API="${2:?missing value}"; shift 2;; --token) TOKEN="${2:?missing value}"; shift 2;;
  --sample-seconds) SAMPLE_SECONDS="${2:?missing value}"; shift 2;; --push-seconds) PUSH_SECONDS="${2:?missing value}"; shift 2;;
  --bridge-roles) BRIDGE_ROLES="${2:?missing value}"; shift 2;; --max-load) MAX_LOAD="${2:?missing value}"; shift 2;;
  --skip-heavy-on-overload) SKIP_HEAVY=1; shift;; --reset-state) RESET_STATE=1; shift;;
  --skip-connectivity-check) SKIP_CHECK=1; shift;; -h|--help) usage; exit 0;; *) die "Unknown option: $1";; esac
done
[[ $(id -u) -eq 0 ]] || die 'Run as root or through sudo.'
[[ -f "$SOURCE" && -f "$DOCTOR_SOURCE" ]] || die 'VirtInfra Agent source is incomplete.'
[[ -n "$API" ]] || die 'Missing --api or VIRTINFRA_AGENT_API/BW_AGENT_API.'
[[ -n "$TOKEN" ]] || die 'Missing --token or VIRTINFRA_AGENT_TOKEN/BW_AGENT_TOKEN.'
[[ "$API" =~ ^https?://[^[:space:]\']+$ ]] || die 'Invalid Agent API URL.'
[[ "$TOKEN" =~ ^[A-Za-z0-9._:-]{6,200}$ ]] || die 'Invalid token format.'
[[ "$SAMPLE_SECONDS" =~ ^[0-9]+$ ]] && ((SAMPLE_SECONDS>=5 && SAMPLE_SECONDS<=300)) || die 'sample-seconds must be 5-300.'
[[ "$PUSH_SECONDS" =~ ^[0-9]+$ ]] && ((PUSH_SECONDS>=60 && PUSH_SECONDS<=3600)) || die 'push-seconds must be 60-3600.'
[[ "$API" == */push ]] || API="${API%/}/push"
for cmd in python3 virsh ip df systemctl; do command -v "$cmd" >/dev/null || die "Required command is missing: $cmd"; done
if ((SKIP_CHECK==0)); then base="${API%/push}"; log 'Check VirtInfra Monitor endpoint'; code="$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 10 --max-time 20 "$base/login" || true)"; [[ "$code" == 200 || "$code" == 302 ]] || die "Monitor pre-check failed: $base/login returned ${code:-no response}."; fi
log 'Stop old and current Agent units'
for unit in virtinfra-agent.service bwagent.service bwagent.timer bw-agent.service bw-agent.timer; do systemctl disable --now "$unit" >/dev/null 2>&1 || true; done
pkill -TERM -f '/usr/local/lib/(virtinfra-agent|bwagent)/agent.py' 2>/dev/null || true
sleep 1
log 'Install VirtInfra Agent source and protected environment'
install -d -o root -g root -m 0755 "$INSTALL_DIR"
install -d -o root -g root -m 0700 "$STATE_DIR"
if [[ ! -e "$STATE_DIR/state.json" && -f /var/lib/bw-agent/state.json ]]; then cp -a /var/lib/bw-agent/state.json "$STATE_DIR/state.json"; fi
if [[ ! -e "$STATE_DIR/runtime.json" && -f /var/lib/bw-agent/runtime.json ]]; then cp -a /var/lib/bw-agent/runtime.json "$STATE_DIR/runtime.json"; fi
install -o root -g root -m 0755 "$SOURCE" "$SCRIPT_TARGET"
install -o root -g root -m 0755 "$DOCTOR_SOURCE" "$DOCTOR_TARGET"
python3 -m py_compile "$SCRIPT_TARGET"
((RESET_STATE==0)) || rm -f "$STATE_DIR/state.json" "$STATE_DIR/runtime.json"
cat > "$ENV_FILE" <<EOF
VIRTINFRA_AGENT_API='$API'
VIRTINFRA_AGENT_TOKEN='$TOKEN'
VIRTINFRA_AGENT_STATE='$STATE_DIR/state.json'
VIRTINFRA_AGENT_RUNTIME='$STATE_DIR/runtime.json'
VIRTINFRA_AGENT_SAMPLE_SECONDS='$SAMPLE_SECONDS'
VIRTINFRA_AGENT_PUSH_SECONDS='$PUSH_SECONDS'
BW_AGENT_MAX_LOAD='$MAX_LOAD'
BW_AGENT_SKIP_HEAVY_ON_OVERLOAD='$SKIP_HEAVY'
BW_AGENT_PPS_WARN='$PPS_WARN'
BW_AGENT_MBPS_WARN='$MBPS_WARN'
BW_AGENT_STALE_IFACE_SECONDS='600'
BW_AGENT_COLLECT_VM_NET='1'
BW_AGENT_COLLECT_VM_PERF='1'
BW_AGENT_COLLECT_NODE_HOST='1'
BW_AGENT_COLLECT_PHYSICAL_NET='1'
BW_AGENT_BRIDGE_ROLES='$BRIDGE_ROLES'
BW_AGENT_BANDWIDTH_CONSUMPTION_ENABLED='1'
BW_AGENT_BANDWIDTH_CONSUMPTION_JITTER_SECONDS='240'
BW_AGENT_API_TIMEOUT='30'
BW_AGENT_HTTP_GZIP='$HTTP_GZIP'
BW_AGENT_HTTP_GZIP_MIN_BYTES='1024'
BW_AGENT_DOMSTATS_TIMEOUT='180'
BW_AGENT_VIRSH_LIST_TIMEOUT='30'
BW_AGENT_DOMIFLIST_TIMEOUT='30'
BW_AGENT_QUIET='0'
EOF
chmod 0600 "$ENV_FILE"
cat > "$SERVICE_FILE" <<'EOF'
[Unit]
Description=VirtInfra Agent v14 persistent infrastructure collector
Wants=network-online.target
After=network-online.target libvirtd.service
ConditionPathExists=/usr/local/lib/virtinfra-agent/agent.py
[Service]
Type=simple
User=root
Group=root
EnvironmentFile=/etc/virtinfra-agent.env
ExecStart=/usr/bin/python3 /usr/local/lib/virtinfra-agent/agent.py
Restart=always
RestartSec=5
Nice=10
IOSchedulingClass=idle
MemoryHigh=256M
MemoryMax=512M
TimeoutStopSec=30
KillSignal=SIGTERM
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=read-only
ProtectSystem=full
ReadWritePaths=/var/lib/virtinfra-agent /run
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
StandardOutput=journal
StandardError=journal
[Install]
WantedBy=multi-user.target
EOF
rm -f /etc/systemd/system/bwagent.service /etc/systemd/system/bwagent.timer /etc/systemd/system/bw-agent.service /etc/systemd/system/bw-agent.timer
ln -sfn "$DOCTOR_TARGET" /usr/local/sbin/bwagent-doctor
systemctl daemon-reload
systemctl reset-failed virtinfra-agent.service >/dev/null 2>&1 || true
systemctl enable --now virtinfra-agent.service
for _ in $(seq 1 20); do systemctl is-active --quiet virtinfra-agent.service && break; sleep 1; done
systemctl is-active --quiet virtinfra-agent.service || { journalctl -u virtinfra-agent.service -n 100 --no-pager >&2 || true; die 'virtinfra-agent.service did not become active.'; }
sleep 3; systemctl is-active --quiet virtinfra-agent.service || die 'virtinfra-agent.service exited after startup.'
cat <<EOF

VirtInfra Agent installed successfully.
Service:       virtinfra-agent.service (active)
Monitor API:   $API
Sample:        ${SAMPLE_SECONDS}s
Push:          ${PUSH_SECONDS}s
Transport:     gzip level 1 for JSON payloads (plain JSON compatible)
Bandwidth:     compact node totals every completed local 2h bucket
Environment:   $ENV_FILE (0600)
State:         $STATE_DIR
Logs:          journalctl -fu virtinfra-agent.service
Doctor:        virtinfra-agent-doctor
EOF
