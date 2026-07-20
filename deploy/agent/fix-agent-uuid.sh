#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE="${VIRTINFRA_AGENT_ENV:-/etc/virtinfra-agent.env}"
STATE_FILE="${VIRTINFRA_AGENT_STATE:-/var/lib/virtinfra-agent/state.json}"
RUNTIME_FILE="${VIRTINFRA_AGENT_RUNTIME:-/var/lib/virtinfra-agent/runtime.json}"
SERVICE="${VIRTINFRA_AGENT_SERVICE:-virtinfra-agent.service}"
NODE_NAME=""
PURGE_VM_UUID=""

usage() {
  cat <<'TXT'
Usage:
  fix-agent-uuid.sh --node NEW_NODE_NAME
  fix-agent-uuid.sh --purge-vm OLD_VM_UUID
  fix-agent-uuid.sh --node NEW_NODE_NAME --purge-vm OLD_VM_UUID

Notes:
  --node changes the Agent node identity without reinstalling the Agent.
  --purge-vm removes only stale local counters/pending rows for one VM UUID.
             The next Agent scan reads the real UUID again from libvirt.
TXT
}

while (($#)); do
  case "$1" in
    --node) NODE_NAME="${2:-}"; shift 2 ;;
    --purge-vm) PURGE_VM_UUID="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ $(id -u) -eq 0 ]] || { echo "Run as root" >&2; exit 1; }
[[ -n "$NODE_NAME" || -n "$PURGE_VM_UUID" ]] || { usage >&2; exit 2; }
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE" >&2; exit 1; }

STAMP="$(date +%Y%m%d-%H%M%S)"
cp -a "$ENV_FILE" "$ENV_FILE.bak-$STAMP"
[[ ! -f "$STATE_FILE" ]] || cp -a "$STATE_FILE" "$STATE_FILE.bak-$STAMP"
[[ ! -f "$RUNTIME_FILE" ]] || cp -a "$RUNTIME_FILE" "$RUNTIME_FILE.bak-$STAMP"

if [[ -n "$NODE_NAME" ]]; then
  python3 - "$ENV_FILE" "$NODE_NAME" <<'PY'
from pathlib import Path
import shlex, sys
path=Path(sys.argv[1]); value=sys.argv[2].strip()
if not value or any(ch in value for ch in "\r\n\0"):
    raise SystemExit("Invalid node name")
lines=path.read_text(encoding="utf-8", errors="replace").splitlines()
key="VIRTINFRA_AGENT_NODE"
out=[]; replaced=False
for line in lines:
    if line.startswith(key+"="):
        if not replaced:
            out.append(f"{key}={shlex.quote(value)}")
            replaced=True
        continue
    out.append(line)
if not replaced:
    out.append(f"{key}={shlex.quote(value)}")
path.write_text("\n".join(out)+"\n", encoding="utf-8")
PY
fi

if [[ -n "$PURGE_VM_UUID" ]]; then
  python3 - "$STATE_FILE" "$RUNTIME_FILE" "$PURGE_VM_UUID" <<'PY'
from pathlib import Path
import json, os, sys, tempfile
state_path=Path(sys.argv[1]); runtime_path=Path(sys.argv[2]); uuid=sys.argv[3].strip()
if not uuid or any(ch in uuid for ch in "\r\n\0"):
    raise SystemExit("Invalid VM UUID")

def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+".", dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(data,f,separators=(",",":"),sort_keys=True)
            f.write("\n")
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass

def load(path):
    if not path.exists(): return None
    with path.open("r",encoding="utf-8") as f: return json.load(f)

def scrub(value):
    if isinstance(value, dict):
        out={}
        for k,v in value.items():
            ks=str(k)
            if ks==f"perf:{uuid}" or ks.startswith(f"net:{uuid}:"):
                continue
            if ks in {"vm_uuid","uuid"} and str(v)==uuid:
                return None
            cleaned=scrub(v)
            if cleaned is not None:
                out[k]=cleaned
        return out
    if isinstance(value, list):
        out=[]
        for item in value:
            if isinstance(item,dict) and str(item.get("vm_uuid") or item.get("uuid") or "")==uuid:
                continue
            cleaned=scrub(item)
            if cleaned is not None: out.append(cleaned)
        return out
    return value

for path in (state_path,runtime_path):
    data=load(path)
    if data is not None:
        atomic_write(path,scrub(data))
PY
fi

systemctl daemon-reload
systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" || {
  systemctl status "$SERVICE" --no-pager -l >&2 || true
  exit 1
}

echo "Agent identity repair completed."
[[ -z "$NODE_NAME" ]] || echo "Node identity: $NODE_NAME"
[[ -z "$PURGE_VM_UUID" ]] || echo "Purged stale local state for VM UUID: $PURGE_VM_UUID"
echo "Backups use suffix: .bak-$STAMP"
