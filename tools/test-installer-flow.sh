#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
I="$ROOT/deploy/postgres/install-postgres-native.sh"
fail(){ echo "ERROR: $*" >&2; exit 1; }
for f in "$ROOT/install.sh" "$ROOT/update.sh" "$I" "$ROOT/deploy/postgres/bw-monitorctl.sh" "$ROOT/deploy/postgres/backup.sh" "$ROOT/deploy/postgres/restore.sh"; do
  [[ -f "$f" ]] || fail "missing $f"
  bash -n "$f"
done

grep -q 'RELEASE="50.3.2-prod-r1-github-desktop-operations-guide"' "$I" || fail "release marker missing"
grep -q 'tuanchu1121/bw-monitor-production.1' "$ROOT/install.sh" || fail "default GitHub repository is wrong"
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
grep -q 'timescale/timescaledb:2.27.2-pg17-oss' "$ROOT/postgres/docker-compose.yml" || fail "pinned Timescale image missing"
grep -q "BW_REDIS_ENABLED='\$REDIS_CACHE'" "$I" || fail "optional Redis switch missing"
grep -q 'REDIS_CACHE=0' "$I" || fail "Redis is not default-off"
grep -q 'Agent cadence:  local 15-second samples, one push every 300 seconds' "$I" || fail "exact Agent cadence output missing"
grep -q 'Retention:      0-48h real 5-minute pushes; 48h-7d one real/hour; >7d delete' "$I" || fail "exact retention output missing"
grep -q 'pg_dump' "$ROOT/deploy/postgres/backup.sh" || fail "pg_dump backup missing"
grep -q 'pg_restore' "$ROOT/deploy/postgres/restore.sh" || fail "pg_restore restore missing"
grep -q 'timescaledb_pre_restore' "$ROOT/deploy/postgres/restore.sh" || fail "Timescale pre-restore hook missing"
grep -q 'timescaledb_post_restore' "$ROOT/deploy/postgres/restore.sh" || fail "Timescale post-restore hook missing"
grep -q 'ProtectHome=read-only' "$ROOT/deploy/agent/install-agent.sh" || fail "Agent /home visibility fix missing"
grep -q "BW_AGENT_BANDWIDTH_CONSUMPTION_ENABLED='1'" "$ROOT/deploy/agent/install-agent.sh" || fail "Bandwidth Consumption Agent default missing"
grep -q 'BW_AGENT_BANDWIDTH_CONSUMPTION_ENABLED="1"' "$ROOT/ansible/deploy-agent.yml" || fail "Bandwidth Consumption Ansible default missing"
grep -q 'become: "{{ (ansible_user | default('"'"'root'"'"')) != '"'"'root'"'"' }}"' "$ROOT/ansible/deploy-agent.yml" || fail "Ansible root/sudo behavior missing"

for doc in README.md docs/README_VI.md docs/INSTALL.md docs/DOMAIN.md docs/MANAGEMENT.md docs/DATABASE.md docs/BACKUP_RESTORE.md docs/ANSIBLE.md docs/UPGRADE.md docs/TROUBLESHOOTING.md docs/PUBLISHING.md; do
  [[ -s "$ROOT/$doc" ]] || fail "missing documentation: $doc"
done

echo "PASS: v50 GitHub/new-server/domain/operations installer flow"
