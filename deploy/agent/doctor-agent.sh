#!/usr/bin/env bash
set -Eeuo pipefail
FAIL=0
ok(){ echo "[ OK ] $*"; }; fail(){ echo "[FAIL] $*"; FAIL=$((FAIL+1)); }; warn(){ echo "[WARN] $*"; }
SRC=/usr/local/lib/virtinfra-agent/agent.py
ENV=/etc/virtinfra-agent.env
UNIT=virtinfra-agent.service
[[ -f "$SRC" ]] && ok 'VirtInfra Agent source exists' || fail 'VirtInfra Agent source is missing'
python3 -m py_compile "$SRC" && ok 'Agent source compiles' || fail 'Agent source does not compile'
systemctl is-active --quiet "$UNIT" && ok "$UNIT is active" || fail "$UNIT is not active"
systemctl is-enabled --quiet "$UNIT" && ok "$UNIT is enabled" || warn "$UNIT is not enabled"
if [[ -f "$ENV" ]]; then mode="$(stat -c %a "$ENV")"; [[ "$mode" == 600 ]] && ok "$ENV mode is 0600" || warn "$ENV mode is $mode"; awk -F= '/^(VIRTINFRA_AGENT_API|VIRTINFRA_AGENT_SAMPLE_SECONDS|VIRTINFRA_AGENT_PUSH_SECONDS|BW_AGENT_BRIDGE_ROLES)=/{print}' "$ENV"; else fail "$ENV is missing"; fi
command -v virsh >/dev/null && ok 'virsh is available' || fail 'virsh is missing'
if [[ -f /var/lib/virtinfra-agent/runtime.json ]]; then
  python3 - <<'PY_RUNTIME'
import json
from pathlib import Path
try:
    data=json.loads(Path('/var/lib/virtinfra-agent/runtime.json').read_text())
    pending=1 if isinstance(data,dict) and isinstance(data.get('pending'),dict) else 0
    obsolete=1 if isinstance(data,dict) and 'bandwidth_consumption' in data else 0
    print('[INFO] Delivery pending=%s obsolete_2h_state=%s' % (pending, obsolete))
except Exception as exc:
    print('[WARN] Cannot read Agent runtime state: %s' % exc)
PY_RUNTIME
fi
echo; journalctl -u "$UNIT" -n 40 --no-pager || true
((FAIL==0)) || exit 2
