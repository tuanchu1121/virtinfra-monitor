#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
I="$ROOT/deploy/postgres/install-postgres-native.sh"
fail(){ echo "ERROR: $*" >&2; exit 1; }
for f in "$ROOT/install.sh" "$ROOT/update.sh" "$I" "$ROOT/deploy/postgres/bw-monitorctl.sh" "$ROOT/deploy/postgres/backup.sh" "$ROOT/deploy/postgres/restore.sh"; do
  [[ -f "$f" ]] || fail "missing $f"
  bash -n "$f"
done

grep -q 'RELEASE="50.6.0-prod-r1-node-groups-additive"' "$I" || fail "release marker missing"
CANONICAL='tuanchu1121/virtinfra-monitor'
[[ "$(cat "$ROOT/CANONICAL_REPOSITORY")" == "$CANONICAL" ]] || fail "canonical repository contract is wrong"
for repo_file in \
  "$ROOT/install.sh" \
  "$ROOT/update.sh" \
  "$ROOT/install-agent.sh" \
  "$ROOT/uninstall-agent.sh" \
  "$ROOT/deploy/postgres/install-postgres-native.sh" \
  "$ROOT/deploy/postgres/bw-monitorctl.sh" \
  "$ROOT/publish-github.sh"
do
  grep -q "$CANONICAL" "$repo_file" || fail "canonical GitHub repository is missing from $repo_file"
done
grep -q 'deploy/postgres/install-postgres-native.sh' "$ROOT/install.sh" || fail "bootstrap does not launch PostgreSQL-native installer"
grep -q 'repo_complete()' "$ROOT/install.sh" || fail "bootstrap repository validation missing"
grep -q 'normalize_shell_modes()' "$ROOT/install.sh" || fail "Windows GitHub Desktop mode normalization missing"
grep -Fq 'stage_canonical_tree "$RAW_ROOT" "$CLEAN_ROOT"' "$ROOT/install.sh" || fail "canonical manifest staging missing"
grep -Fq 'sha256sum -c SHA256SUMS' "$ROOT/install.sh" || fail "canonical source checksum verification missing"
grep -Fq 'bash "$CLEAN_ROOT/deploy/postgres/install-postgres-native.sh"' "$ROOT/install.sh" || fail "staged installer is not invoked through bash"
grep -Fq 'bash "$REPO_ROOT/preflight.sh"' "$I" || fail "installer preflight still depends on executable mode"
grep -Fq 'bash ./tools/test-installer-flow.sh' "$ROOT/preflight.sh" || fail "preflight child script still depends on executable mode"
grep -q -- '--public-ip' "$I" || fail "public IP mode missing"
grep -q -- '--domain' "$I" || fail "domain mode missing"
grep -q -- '--ip-mode' "$I" || fail "domain-to-IP switch missing"
grep -q 'certbot --nginx' "$I" || fail "Let's Encrypt automation missing"
grep -q '127.0.0.1:${BW_PG_PORT:-55432}:5432' "$ROOT/postgres/docker-compose.yml" || fail "database is not loopback-only"
grep -q 'timescale/timescaledb:2.27.2-pg17' "$ROOT/postgres/docker-compose.yml" || fail "pinned Timescale image missing"
grep -qv '2.27.2-pg17-oss' "$ROOT/postgres/docker-compose.yml" || fail "Apache-only Timescale image cannot provide Storage V2 policies"
grep -q "timescaledb.license" "$I" || fail "Timescale Community capability preflight missing"
grep -q "add_retention_policy" "$I" || fail "Timescale retention API preflight missing"
grep -q "add_compression_policy" "$I" || fail "Timescale compression API preflight missing"
grep -q "BW_REDIS_ENABLED='\$REDIS_CACHE'" "$I" || fail "optional Redis switch missing"
grep -q 'REDIS_CACHE=0' "$I" || fail "Redis is not default-off"
grep -q 'Agent cadence:  local 15-second samples, one push every 300 seconds' "$I" || fail "exact Agent cadence output missing"
grep -q 'Chart history:  exact 5-minute VM/node points for 7 days' "$I" || fail "exact chart retention output missing"
grep -q 'Raw detail:     per-interface V2 rows for 48 hours' "$I" || fail "raw-detail retention output missing"
grep -q '004_storage_v2.sql' "$I" || fail "storage V2 migration is not installed"
grep -q '007_safe_maintenance_queue.sql' "$I" || fail "safe maintenance queue migration is not installed"
grep -q 'maintenance_queue.py' "$I" || fail "maintenance queue module is not installed"
grep -q 'maintenance_dispatch.py' "$I" || fail "maintenance dispatcher is not installed"
grep -q 'bw-monitor-maintenance-watchdog.timer' "$I" || fail "maintenance watchdog timer is not installed"
[[ -f "$ROOT/fix-agent-uuid.sh" && -f "$ROOT/deploy/agent/fix-agent-uuid.sh" ]] || fail "Agent UUID repair command is missing"
grep -q "VIRTINFRA_READ_CHART_V2='0'" "$I" || fail "chart V2 flag missing"
grep -q 'pg_dump' "$ROOT/deploy/postgres/backup.sh" || fail "pg_dump backup missing"
grep -q 'pg_restore' "$ROOT/deploy/postgres/restore.sh" || fail "pg_restore restore missing"
grep -q 'timescaledb_pre_restore' "$ROOT/deploy/postgres/restore.sh" || fail "Timescale pre-restore hook missing"
grep -q 'timescaledb_post_restore' "$ROOT/deploy/postgres/restore.sh" || fail "Timescale post-restore hook missing"
grep -q 'ProtectHome=read-only' "$ROOT/deploy/agent/install-agent.sh" || fail "Agent /home visibility fix missing"
! grep -q 'BW_AGENT_BANDWIDTH_CONSUMPTION_' "$ROOT/deploy/agent/install-agent.sh" || fail "obsolete Agent 2-hour Consumption settings remain"
! grep -q 'BW_AGENT_BANDWIDTH_CONSUMPTION_' "$ROOT/ansible/deploy-agent.yml" || fail "obsolete Ansible 2-hour Consumption settings remain"
grep -q '010_consumption_inventory_cleanup.sql' "$I" || fail "Consumption/inventory migration is not installed"
grep -q '011_node_groups_country_flags.sql' "$I" || fail "Node Groups migration is not installed"
grep -q 'node_groups.py' "$I" || fail "Node Groups module is not installed"
grep -q 'static/flags/4x3' "$I" || fail "local SVG flags are not installed"
grep -q 'bw-monitor-inventory-cleanup.timer' "$I" || fail "inventory cleanup timer is not installed"
grep -q 'consumption_rollup.py' "$I" || fail "Consumption backfill worker is not installed"
grep -q 'become: "{{ (ansible_user | default('"'"'root'"'"')) != '"'"'root'"'"' }}"' "$ROOT/ansible/deploy-agent.yml" || fail "Ansible root/sudo behavior missing"

for doc in README.md docs/README_VI.md docs/INSTALL.md docs/DOMAIN.md docs/MANAGEMENT.md docs/DATABASE.md docs/BACKUP_RESTORE.md docs/ANSIBLE.md docs/UPGRADE.md docs/TROUBLESHOOTING.md docs/PUBLISHING.md; do
  [[ -s "$ROOT/$doc" ]] || fail "missing documentation: $doc"
done

echo "PASS: v50 GitHub/new-server/domain/operations installer flow"
