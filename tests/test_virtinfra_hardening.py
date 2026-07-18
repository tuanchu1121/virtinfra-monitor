#!/usr/bin/env python3
from pathlib import Path
root=Path(__file__).resolve().parents[1]
app=(root/'app/app.py').read_text()
agent=(root/'deploy/agent/agent.py').read_text()
assert (root/'VERSION').read_text().strip() == '50.6.0-prod-r1-node-groups-country-flags'
assert 'VirtInfra Monitor' in app
assert 'WAL reserved/recycled' in app
assert 'SHM {human' not in app
assert 'pg_advisory_xact_lock' in app
assert 'TZ_NAME = "Asia/Ho_Chi_Minh"' in app
assert 'DISPLAY_TIMEZONES' not in app
assert '@app.route("/admin/display-timezone"' not in app
assert 'period_seconds(period) - CACHE_BUCKET_SECONDS' in app
assert 'period_seconds(clean_period(values.get("period") or "5m")) - CACHE_BUCKET_SECONDS' in app
assert 'virtinfra-v502-final-ui' in app
assert 'td:nth-child(10)::before{content:"Last seen"}' in app
assert "COALESCE(svi.status, 'active')!='hidden'" in app
assert 'page_cache_generation' in app
assert 'VirtInfra Agent v15' in agent and 'VirtInfra-Agent/15' in agent
assert 'VIRTINFRA_AGENT_API' in agent
assert 'HAVING total>0' not in app
assert 'HAVING SUM(COALESCE(ns.rx_delta,0)+COALESCE(ns.tx_delta,0))>0' in app

assert 'DB + WAL' not in app
assert '"timezone":display_timezone_name()' in app
assert 'X-VirtInfra-App-Time-Ms' in app and 'X-VirtInfra-Performance' in app
assert "(ni.node IS NULL OR (COALESCE(ni.status,'active')!='hidden' AND ni.deleted_at IS NULL))" in app
playbook=(root/'ansible/deploy-agent.yml').read_text()
assert 'systemctl is-active virtinfra-agent.service' in playbook
assert 'systemctl is-active bwagent.service' not in playbook
readme=(root/'README.md').read_text()
assert 'virtinfra-agent.service' in readme
print('PASS: VirtInfra Monitor v50.3.1 Consumption route fix contract')
