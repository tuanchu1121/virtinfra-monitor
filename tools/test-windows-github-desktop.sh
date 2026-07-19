#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
COPY="$TMP/repo"
mkdir -p "$COPY"

# Copy only the real bootstrap/entry scripts. Other required release files are
# compact fixtures because this test validates Windows-lost executable bits and
# canonical manifest staging, not application content.
for rel in install.sh update.sh install-agent.sh uninstall-agent.sh preflight.sh \
  deploy/postgres/install-postgres-native.sh \
  deploy/postgres/update-postgres-native.sh \
  deploy/postgres/provision-postgres-native.sh; do
  mkdir -p "$COPY/$(dirname -- "$rel")"
  cp "$ROOT/$rel" "$COPY/$rel"
done

required=(
  app/app.py app/runtime_loader.py app/runtime_layers/manifest.json
  app/runtime_layers/00_bootstrap_database.py app/runtime_layers/43_node_groups_loader.py
  app/node_groups.py app/static/vendor/flag-icons/node-groups.css
  app/static/vendor/flag-icons/LICENSE app/static/vendor/flag-icons/SOURCE.md
  app/static/vendor/flag-icons/flags/4x3/vn.svg app/static/flags/node-groups.css
  app/static/flags/neutral.svg app/static/flags/vn.svg app/bw_pg.py app/storage_v2.py
  app/maintenance_native.py app/maintenance_queue.py app/maintenance_dispatch.py
  postgres/docker-compose.yml postgres/sql/004_storage_v2.sql
  postgres/sql/006_postgres_native_maintenance.sql postgres/sql/007_safe_maintenance_queue.sql
  postgres/sql/011_node_groups.sql postgres/sql/012_node_groups_r6_safety.sql
  requirements.txt VERSION CANONICAL_REPOSITORY README.md
)
for rel in "${required[@]}"; do
  [[ -e "$COPY/$rel" ]] && continue
  mkdir -p "$COPY/$(dirname -- "$rel")"
  printf 'fixture:%s\n' "$rel" > "$COPY/$rel"
done

(
  cd "$COPY"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)
find "$COPY" -type f -name '*.sh' -exec chmod 0644 {} +

mkdir -p "$COPY/release" "$COPY/enterprise" "$COPY/deploy/monitor" "$COPY/deploy/enterprise"
printf 'stale runtime\n' > "$COPY/release/app.py"
printf 'stale documentation\n' > "$COPY/OLD_STALE.md"

[[ ! -x "$COPY/install.sh" ]]
bash "$COPY/install.sh" --help >/dev/null
BW_BOOTSTRAP_ACTION=update bash "$COPY/install.sh" --help >/dev/null
[[ ! -e "$COPY/install-core.sh" && ! -e "$COPY/install-enterprise.sh" ]]
[[ ! -e "$COPY/update-core.sh" && ! -e "$COPY/update-enterprise.sh" ]]
bash "$COPY/preflight.sh" --help >/dev/null

grep -Fq 'stage_canonical_tree "$RAW_ROOT" "$CLEAN_ROOT"' "$COPY/install.sh"
grep -Fq 'sha256sum -c SHA256SUMS' "$COPY/install.sh"
grep -Fq 'Unlisted files are ignored.' "$COPY/install.sh"

echo 'PASS: Windows GitHub Desktop mode and explicit fresh/update bootstrap'
