#!/usr/bin/env bash
set -Eeuo pipefail
ENV_FILE=/etc/default/bw-monitor
[[ -r "$ENV_FILE" ]] || { echo "Missing $ENV_FILE" >&2; exit 1; }
python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); lines=p.read_text().splitlines(); key='VIRTINFRA_READ_CHART_V2'; found=False; out=[]
for line in lines:
    if line.startswith(key+'='):
        out.append("VIRTINFRA_READ_CHART_V2='0'"); found=True
    else: out.append(line)
if not found: out.append("VIRTINFRA_READ_CHART_V2='0'")
tmp=p.with_suffix('.tmp'); tmp.write_text('\n'.join(out)+'\n'); tmp.chmod(0o600); tmp.replace(p)
PY
systemctl restart bw-monitor.service
sleep 2
systemctl is-active --quiet bw-monitor.service
printf 'Chart reads rolled back to compatibility history. V2 writes and V2 data remain enabled.\n'
