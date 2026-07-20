#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
FRESH="$ROOT/deploy/postgres/install-postgres-native.sh"
UPDATE="$ROOT/deploy/postgres/update-postgres-native.sh"
ENGINE="$ROOT/deploy/postgres/provision-postgres-native.sh"
CTL="$ROOT/deploy/postgres/bw-monitorctl.sh"
fail(){ echo "ERROR: $*" >&2; exit 1; }

for f in "$ROOT/install.sh" "$ROOT/update.sh" "$FRESH" "$UPDATE" "$ENGINE" "$CTL" \
         "$ROOT/deploy/postgres/backup.sh" "$ROOT/deploy/postgres/restore.sh"; do
  [[ -f "$f" ]] || fail "missing $f"
  bash -n "$f"
done

RELEASE='50.5.9-prod-r17-operations-single-shell-hotfix'
grep -q "RELEASE=\"$RELEASE\"" "$ENGINE" || fail "release marker missing"
[[ "$(cat "$ROOT/VERSION")" == "$RELEASE" ]] || fail "VERSION mismatch"
CANONICAL='tuanchu1121/virtinfra-monitor'
[[ "$(cat "$ROOT/CANONICAL_REPOSITORY")" == "$CANONICAL" ]] || fail "canonical repository contract is wrong"

for repo_file in \
  "$ROOT/install.sh" "$ROOT/update.sh" "$ROOT/install-agent.sh" \
  "$ROOT/uninstall-agent.sh" "$ENGINE" "$CTL" "$ROOT/publish-github.sh"; do
  grep -q "$CANONICAL" "$repo_file" || fail "canonical GitHub repository is missing from $repo_file"
done

# Fresh and update entry points must be explicit and must not alias old editions.
grep -Fq 'provision-postgres-native.sh" --mode fresh' "$FRESH" || fail "fresh wrapper does not force fresh mode"
grep -Fq 'provision-postgres-native.sh" --mode update' "$UPDATE" || fail "update wrapper does not force update mode"
grep -q 'BW_BOOTSTRAP_ACTION=update' "$ROOT/update.sh" || fail "update bootstrap action missing"
grep -q 'case "$ACTION" in' "$ROOT/install.sh" || fail "bootstrap action dispatcher missing"
grep -q 'update-postgres-native.sh' "$ROOT/install.sh" || fail "update dispatcher missing"
! grep -q -- '--update' "$ROOT/install.sh" "$ROOT/update.sh" "$ENGINE" "$CTL" || fail "obsolete --update flag remains"
for obsolete in setup.sh install-core.sh install-enterprise.sh update-core.sh update-enterprise.sh uninstall-core.sh uninstall-enterprise.sh; do
  [[ ! -e "$ROOT/$obsolete" ]] || fail "obsolete setup alias remains: $obsolete"
done

grep -q 'Existing VirtInfra Monitor configuration detected' "$ENGINE" || fail "fresh existing-config guard missing"
grep -q 'Existing bw-timescaledb container detected' "$ENGINE" || fail "fresh container guard missing"
grep -q 'Existing PostgreSQL volume detected' "$ENGINE" || fail "fresh volume guard missing"
grep -q 'update.sh requires an existing VirtInfra Monitor installation' "$ENGINE" || fail "update existing-install guard missing"
grep -q 'Create PostgreSQL backup before update' "$ENGINE" || fail "pre-update backup missing"
grep -q '\[\[ "$MODE" == "update"' "$ENGINE" || fail "update-only backup branch missing"
grep -q 'update.sh" | bash -s -- --domain' "$CTL" || fail "domain set does not use update.sh"
grep -q 'update.sh" | bash -s -- --ip-mode' "$CTL" || fail "domain remove does not use update.sh"

# Canonical manifest staging and Windows mode normalization remain required.
grep -q 'repo_complete()' "$ROOT/install.sh" || fail "bootstrap repository validation missing"
grep -q 'normalize_shell_modes()' "$ROOT/install.sh" || fail "Windows mode normalization missing"
grep -Fq 'stage_canonical_tree "$RAW_ROOT" "$CLEAN_ROOT"' "$ROOT/install.sh" || fail "manifest staging missing"
grep -Fq 'sha256sum -c SHA256SUMS' "$ROOT/install.sh" || fail "source checksum verification missing"
if grep -Eq '(^|[[:space:]])\.?/?.*\.(zip|tar\.gz)$' "$ROOT/SHA256SUMS"; then
  fail "SHA256SUMS must not contain generated archives"
fi

# Installation capabilities.
grep -q -- '--public-ip' "$ENGINE" || fail "public IP mode missing"
grep -q -- '--domain' "$ENGINE" || fail "domain mode missing"
grep -q -- '--ip-mode' "$ENGINE" || fail "update IP mode missing"
grep -q 'certbot --nginx' "$ENGINE" || fail "Let's Encrypt automation missing"
grep -q '127.0.0.1:${BW_PG_PORT:-55432}:5432' "$ROOT/postgres/docker-compose.yml" || fail "database is not loopback-only"
grep -q 'timescale/timescaledb:2.27.2-pg17' "$ROOT/postgres/docker-compose.yml" || fail "pinned Timescale image missing"
grep -q 'timescaledb.license' "$ENGINE" || fail "Timescale capability check missing"
grep -q 'add_retention_policy' "$ENGINE" || fail "retention capability check missing"
grep -q 'add_compression_policy' "$ENGINE" || fail "compression capability check missing"
grep -q "BW_REDIS_ENABLED='\$REDIS_CACHE'" "$ENGINE" || fail "optional Redis switch missing"
grep -q 'REDIS_CACHE=0' "$ENGINE" || fail "Redis is not default-off"
grep -q 'Agent cadence:  local 15-second samples, one push every 300 seconds' "$ENGINE" || fail "Agent cadence output missing"
grep -q 'Chart history:  exact 5-minute VM/node points for 7 days' "$ENGINE" || fail "chart retention output missing"
grep -q 'Raw detail:     per-interface V2 rows for 48 hours' "$ENGINE" || fail "raw retention output missing"

for required in \
  004_storage_v2.sql 007_safe_maintenance_queue.sql 010_consumption_inventory_cleanup.sql \
  011_node_groups.sql 012_node_groups_r6_safety.sql 013_maintenance_queue_boolean.sql maintenance_queue.py \
  maintenance_dispatch.py runtime_loader.py runtime_layers node_groups.py \
  consumption_rollup.py bw-monitor-inventory-cleanup.timer; do
  grep -q "$required" "$ENGINE" || fail "installer does not deploy $required"
done

grep -q 'pg_dump' "$ROOT/deploy/postgres/backup.sh" || fail "pg_dump backup missing"
grep -q 'pg_restore' "$ROOT/deploy/postgres/restore.sh" || fail "pg_restore restore missing"
grep -q 'timescaledb_pre_restore' "$ROOT/deploy/postgres/restore.sh" || fail "Timescale pre-restore hook missing"
grep -q 'timescaledb_post_restore' "$ROOT/deploy/postgres/restore.sh" || fail "Timescale post-restore hook missing"
grep -q 'ProtectHome=read-only' "$ROOT/deploy/agent/install-agent.sh" || fail "Agent /home visibility fix missing"
! grep -q 'BW_AGENT_BANDWIDTH_CONSUMPTION_' "$ROOT/deploy/agent/install-agent.sh" || fail "obsolete Agent Consumption settings remain"
! grep -q 'BW_AGENT_BANDWIDTH_CONSUMPTION_' "$ROOT/ansible/deploy-agent.yml" || fail "obsolete Ansible Consumption settings remain"

for doc in README.md COMMANDS_A_TO_Z_VI.md docs/README_VI.md docs/INSTALL.md docs/DOMAIN.md docs/MANAGEMENT.md docs/DATABASE.md docs/BACKUP_RESTORE.md docs/ANSIBLE.md docs/UPGRADE.md docs/TROUBLESHOOTING.md docs/PUBLISHING.md; do
  [[ -s "$ROOT/$doc" ]] || fail "missing documentation: $doc"
done

echo "PASS: fresh-install/update split and operations flow"
